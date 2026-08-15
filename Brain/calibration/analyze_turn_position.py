#!/usr/bin/env python3
"""Zero-Gemma calibration script (Approach B of the sink-rescue combined-signal effort): checks
whether a trigger's POSITION within its call -- not its content at all -- separates coachable from
junk. Motivated by reading real false positives from the length signal (Brain/analyze_combined_signal.py):
meeting wrap-ups, logistics, and small talk read as structurally clustered near the start (greetings)
or end (wrap-up) of a call, while substantive discussion happens in the middle -- a property no prior
signal in this effort has looked at, since all of them treat each pair in isolation.

Reads Postgres only to map call_id -> filename (kb_pairs' own call_id/turn_index are already in the
persisted sample); re-parses the source transcript to get each call's total turn count -- same
transcript_parser call label_trigger_quality_sample.py already makes. No Gemma calls, no DB writes.

Usage (from Brain/, venv active):
    python calibration/analyze_turn_position.py [recordings_dir] [labeled_sample.json]
"""
from __future__ import annotations
import json
import random
import sys
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np
from sklearn.metrics import roc_auc_score

# Brain/ is this file's parent -- put it on sys.path so the shared packages
# (config, shared, v1, v2, preprocessing) resolve whether this script is run
# directly (python calibration/x.py) or imported (from calibration import x).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

from config import load_config
from preprocessing.transcript_parser import load_roster, parse_transcript
from shared import storage


def _load_judged(path: Path) -> list[dict]:
    sample = json.loads(path.read_text(encoding="utf-8"))
    return [p for p in sample if p["coachable"] is not None]


def _total_turns_by_call(conn, config, recordings_dir: Path, call_ids: set[int]) -> dict[int, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT call_id, filename FROM calls WHERE call_id = ANY(%s)", (list(call_ids),))
        rows = cur.fetchall()
    totals: dict[int, int] = {}
    missing = 0
    for call_id, filename in rows:
        txt_path = recordings_dir / filename
        if not txt_path.exists():
            missing += 1
            continue
        turns = parse_transcript(
            str(txt_path), config.joveo_speakers_lower, config.naren_name_lower,
            roster=load_roster(str(txt_path)),
        )
        totals[call_id] = len(turns)
    if missing:
        print(f"WARNING: {missing} call(s) have no transcript file under {recordings_dir}.")
    return totals


def _add_position_features(judged: list[dict], totals: dict[int, int]) -> list[dict]:
    kept = []
    for p in judged:
        total = totals.get(p["call_id"])
        if not total or total <= 1:
            continue
        norm = p["turn_index"] / (total - 1)
        p["normalized_position"] = norm
        p["edge_distance"] = min(norm, 1 - norm)
        kept.append(p)
    return kept


def _auc(judged: list[dict], field: str) -> float:
    y = [1 if p["coachable"] else 0 for p in judged]
    scores = [p[field] for p in judged]
    return roc_auc_score(y, scores)


def _percentiles(values: list[float]) -> str:
    return "  ".join(f"p{pct}={np.percentile(values, pct):.3f}" for pct in (10, 25, 50, 75, 90))


def _report(judged: list[dict]) -> None:
    coachable = [p for p in judged if p["coachable"]]
    not_coachable = [p for p in judged if not p["coachable"]]
    print(f"\n{len(judged)} pair(s) with a reconstructed total-turn-count "
          f"({len(coachable)} coachable / {len(not_coachable)} not).")

    print("\nnormalized_position (0=start of call, 1=end) split by label:")
    print("  coachable    :", _percentiles([p["normalized_position"] for p in coachable]))
    print("  not coachable:", _percentiles([p["normalized_position"] for p in not_coachable]))
    print(f"  AUC (coachable > not_coachable) = {_auc(judged, 'normalized_position'):.3f}")

    print("\nedge_distance (0=at either edge, 0.5=exact middle) split by label -- tests the "
          "U-shaped hypothesis (junk clusters at BOTH the start and the end):")
    print("  coachable    :", _percentiles([p["edge_distance"] for p in coachable]))
    print("  not coachable:", _percentiles([p["edge_distance"] for p in not_coachable]))
    print(f"  AUC (coachable > not_coachable) = {_auc(judged, 'edge_distance'):.3f}")

    rng = random.Random(0)
    print("\n10 random pairs near either edge (edge_distance < 0.1), for manual reading:")
    near_edge = [p for p in judged if p["edge_distance"] < 0.1]
    for p in rng.sample(near_edge, min(10, len(near_edge))):
        print(f"  [{p['pair_id']}] coachable={p['coachable']} pos={p['normalized_position']:.2f} "
              f"reason={p['reason']!r}")
        print(f"      trigger : {p['trigger_text'][:100]!r}")
        print(f"      response: {p['response_text'][:150]!r}")


def main() -> None:
    args = sys.argv[1:]
    recordings_dir = Path(args[0]) if args else Path("recordings")
    sample_path = Path(args[1]) if len(args) > 1 else ARTIFACTS_DIR / "labeled_trigger_quality_sample.json"

    judged = _load_judged(sample_path)
    print(f"Loaded {len(judged)} judged pair(s) from {sample_path}.")

    config = load_config()
    conn = storage.get_connection(config.database_url)
    totals = _total_turns_by_call(conn, config, recordings_dir, {p["call_id"] for p in judged})
    conn.close()

    judged = _add_position_features(judged, totals)
    _report(judged)


if __name__ == "__main__":
    main()
