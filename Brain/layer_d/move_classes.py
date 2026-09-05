"""SAY/DO routing for the say arm: which grader arm each playbook move belongs to.

The routing artifact (artifacts/layer_d_move_classes.json) is produced by
calibration/layer_d_move_classes_packet.py: two independent BLIND readers classify
every live move's criterion (opaque ids, no scenario names), disagreements route to
pairwise, and each move's criterion is pinned by sha256.

This module is the FAIL-CLOSED consumer. Two refusals, both loud:

  * a live playbook move with no entry in the artifact -> raise. Routing a move by
    guesswork would put it on an arm whose verdict semantics it was never
    classified for.
  * a live move whose criterion hash no longer matches the pinned one -> raise. A
    remade playbook gets fresh criteria; grading them under the OLD classification
    would be the silent per-item drift this project has been burned by 9 times.
    Re-run the packet + reads, then re-ship the artifact.

Design record: docs/findings/layer-d-say-arm.md §4.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "artifacts" / "layer_d_move_classes.json"


def criterion_hash(criterion: str) -> str:
    """Whitespace-normalized sha256 -- MUST stay identical to
    calibration/layer_d_move_classes_packet.criterion_hash (the producer)."""
    return hashlib.sha256(" ".join(criterion.split()).encode("utf-8")).hexdigest()


def load_move_classes(path: str | Path = ARTIFACT_PATH) -> dict[str, dict]:
    """{'<scenario_key>:<move_id>': {route, class, criterion_sha256, ...}}"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"routing artifact not found: {p}. Build it with "
            f"calibration/layer_d_move_classes_packet.py (--packet, two blind "
            f"reads, --score READ1 READ2 --write). The say arm cannot run "
            f"without it.")
    data = json.loads(p.read_text(encoding="utf-8"))
    moves = data.get("moves")
    if not isinstance(moves, dict) or not moves:
        raise ValueError(f"routing artifact {p} has no 'moves' mapping")
    return moves


def classes_fingerprint(moves: dict[str, dict]) -> str:
    """Short stable hash of the ROUTING (keys + routes), for the checkpoint layer
    string: a changed classification is an instrument change and must invalidate
    prior progress, same rule as a model or effort change."""
    canon = "|".join(f"{k}={v['route']}" for k, v in sorted(moves.items()))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:8]


def say_moves(playbook: dict, classes: dict[str, dict]) -> list[dict]:
    """The SAY-routed subset of one FLATTENED playbook's grader-facing move specs,
    with each move's first evidence quote carried along as the specificity anchor.

    Validates EVERY move of the playbook against the artifact (not just the say
    ones): a missing entry or a criterion-hash mismatch anywhere in the document
    means the classification no longer describes this playbook -- refuse it whole.
    """
    scenario_key = playbook["scenario_key"]
    out: list[dict] = []
    for m in playbook["key_moves"]:
        key = f"{scenario_key}:{m['move_id']}"
        entry = classes.get(key)
        criterion = (m.get("criterion") or "").strip()
        if entry is None:
            if not criterion:
                continue    # never classified because never gradable; no route needed
            raise KeyError(
                f"move {key} is live but missing from the routing artifact -- "
                f"re-run calibration/layer_d_move_classes_packet.py")
        if entry["criterion_sha256"] != criterion_hash(criterion):
            raise ValueError(
                f"move {key}: live criterion no longer matches the classified one "
                f"(playbook remade since classification?) -- re-run the packet "
                f"and re-ship the routing artifact")
        if entry["route"] == "say":
            anchor = ""
            for ev in (m.get("evidence") or []):
                q = (ev.get("quote") or "").strip()
                if q:
                    anchor = q
                    break
            out.append({"move_id": m["move_id"], "name": m.get("name", ""),
                        "criterion": criterion, "anchor": anchor})
    return out
