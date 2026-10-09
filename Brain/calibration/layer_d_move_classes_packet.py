#!/usr/bin/env python3
"""SAY/DO ROUTING CLASSIFICATION -- every move of every live playbook, blind.

Zero chat calls, zero writes to Postgres. Read-only.

WHY THIS EXISTS. The say-arm design (docs/findings/layer-d-say-arm.md) routes each
playbook move to a grader arm by its ACT TYPE: SAY moves (complete once said) go to
the new occurrence+specificity arm, DO/MIXED moves stay on pairwise. The routing
label must therefore exist for ALL 121 live moves -- not just the 77 rankable cells
the 2026-08-27 act-type packet covered -- and the earlier blind read's labels were
never persisted, so this re-runs the same blind protocol over the full population.

PROTOCOL (identical to layer_d_act_type_packet.py, which see for the rationale):
  * opaque ids, seeded shuffle, criteria only -- no scenario names, no move ids,
    no tie rates. The reader cannot fit the labels to any outcome.
  * TWO independent readers, each returning a FULL read (a partial read is refused).
  * ADJUDICATION (pre-registered in the design doc): readers agree -> that label;
    readers disagree in ANY way -> the move routes to PAIRWISE (the validated
    incumbent instrument -- the conservative side).
  * The artifact pins each move's criterion by sha256; layer_d.move_classes REFUSES
    to route a move whose live criterion no longer matches (a remade playbook must
    be re-classified loudly, never silently mis-routed).

Usage (from Brain/):
    python calibration/layer_d_move_classes_packet.py --packet
    python calibration/layer_d_move_classes_packet.py --score READ1 READ2 [--write]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibration import ARTIFACTS_DIR  # noqa: E402

PACKET = ARTIFACTS_DIR / "ld_moveclass_packet.txt"
KEY = ARTIFACTS_DIR / "ld_moveclass_KEY.json"
ARTIFACT = ARTIFACTS_DIR / "layer_d_move_classes.json"

BUCKETS = ("SAY", "DO", "MIXED")
_LINE = re.compile(r"^\s*(A\d{3})\s+(SAY|DO|MIXED)\b(.*)$")

# Different seed than the 77-cell packet on purpose: a reader who somehow saw that
# packet must not find the items in a recognizable order here.
SEED = 20260828


def criterion_hash(criterion: str) -> str:
    return hashlib.sha256(" ".join(criterion.split()).encode("utf-8")).hexdigest()


def _connect():
    """Plain connection, never writes. Deliberately does NOT set
    default_transaction_read_only -- that setting leaks across unrelated clients
    through Neon's pooler (docs/GOTCHAS.md, 2026-08-26)."""
    import psycopg
    from config import load_config
    url = load_config().database_url
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + "hostaddr=18.138.49.39"
    return psycopg.connect(url, autocommit=True)


def collect() -> list[dict]:
    """Every move of every LIVE playbook, in (scenario_key, move position) order."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT scenario_key, playbook_id, key_moves
                       FROM playbooks WHERE status = 'live'
                       ORDER BY scenario_key""")
        rows = cur.fetchall()
    out = []
    for sk, pid, km in rows:
        for i, mv in enumerate(km or [], start=1):
            criterion = (mv.get("criterion") or "").strip()
            if not criterion:
                # A move with no criterion cannot be graded by ANY arm; recorded so
                # the count is honest, routed to pairwise by omission downstream.
                print(f"[collect] WARNING: {sk} M{i} has an empty criterion; skipped")
                continue
            out.append({
                "scenario": sk, "move_id": f"M{i}", "playbook_id": pid,
                "name": (mv.get("name") or "").strip(), "criterion": criterion,
            })
    return out


def write_packet(rows: list[dict]) -> None:
    order = list(range(len(rows)))
    random.Random(SEED).shuffle(order)

    lines = [
        "MOVE ACT-TYPE PACKET (routing edition -- full live playbook population)",
        "",
        "Each item is one CRITERION from a sales-coaching playbook. It describes something a",
        "Customer Success rep might do during a client call.",
        "",
        "For each item, answer ONE question: is this something that is COMPLETE ONCE SAID, or",
        "is it WORK CARRIED OUT WITH VARIABLE DEPTH?",
        "",
        "  SAY   -- the move is finished the moment the words leave the rep's mouth. Stating a",
        "           fact, giving a warning, making a recommendation, offering to do something,",
        "           explaining how a thing works. Two reps who both said it have BOTH done it;",
        "           there is no meaningful better-or-worse.",
        "",
        "  DO    -- the move is work with a quality gradient. Investigating a problem,",
        "           diagnosing a discrepancy, provisioning access, coordinating across teams,",
        "           configuring or validating something, running a test. One rep can do it",
        "           thoroughly and another shallowly, and you could tell them apart.",
        "",
        "  MIXED -- genuinely both, or you cannot tell. Use this sparingly and only when the",
        "           item really does not sit on one side.",
        "",
        "THE TEST TO APPLY. Imagine two competent reps who both addressed this item on a call.",
        "Could you say which one handled it BETTER? If yes -> DO. If they are simply both done",
        "-> SAY.",
        "",
        "Judge the ACT, not the writing. A long, detailed, concrete criterion can still be a",
        "SAY (a detailed warning is still a warning). A short plain one can be a DO. Do not",
        "reward or penalise specificity, jargon, or polish. Do not guess where an item came",
        "from or which items resemble each other.",
        "",
        "=" * 78,
        "",
    ]

    keymap: dict[str, dict] = {}
    for n, idx in enumerate(order, start=1):
        aid = f"A{n:03d}"
        r = rows[idx]
        keymap[aid] = {
            "scenario": r["scenario"], "move_id": r["move_id"],
            "playbook_id": r["playbook_id"], "name": r["name"],
            "criterion": r["criterion"],
            "criterion_sha256": criterion_hash(r["criterion"]),
        }
        lines.append(f"{aid}: {r['criterion']}")

    lines += ["", "=" * 78, "",
              "Return ONE line per item, every item, ascending id order, no preamble:",
              "  <id> <SAY|DO|MIXED> <reason, 12 words max>",
              "",
              f"Then one final line: TALLY say=<n> do=<n> mixed=<n>  (summing to {len(rows)})",
              ""]

    PACKET.write_text("\n".join(lines), encoding="utf-8")
    KEY.write_text(json.dumps(keymap, indent=2), encoding="utf-8")
    print(f"[packet] {len(keymap)} criteria -> {PACKET}")
    print(f"[key]    withheld  -> {KEY}")


def parse_read(read_path: Path, key: dict) -> dict[str, str]:
    """One reader's labels, full-read enforced (a rate over the subset a reader
    happened to finish is not a rate over the population)."""
    got: dict[str, str] = {}
    for raw in read_path.read_text(encoding="utf-8-sig").splitlines():
        m = _LINE.match(raw)
        if not m:
            continue
        aid, bucket = m.group(1), m.group(2)
        if aid in got and got[aid] != bucket:
            raise SystemExit(f"{read_path.name}: {aid} classified twice, "
                             f"inconsistently: {got[aid]} then {bucket}")
        got[aid] = bucket
    extra = sorted(set(got) - set(key))
    if extra:
        raise SystemExit(f"{read_path.name}: {len(extra)} unknown ids: {extra[:8]}")
    missing = sorted(set(key) - set(got))
    if missing:
        raise SystemExit(f"{read_path.name}: PARTIAL READ -- {len(missing)} of "
                         f"{len(key)} unclassified ({missing[:10]}...). Refused.")
    return got


def score(read_paths: list[Path], write: bool) -> None:
    key = json.loads(KEY.read_text(encoding="utf-8"))
    reads = [parse_read(p, key) for p in read_paths]

    for p, r in zip(read_paths, reads):
        c = Counter(r.values())
        print(f"[{p.name}] " + "  ".join(f"{b}={c.get(b, 0)}" for b in BUCKETS))

    if len(reads) == 1:
        print("\nONE read only -- agreement unmeasurable, artifact NOT writable. "
              "The protocol requires two independent readers.")
        return

    r1, r2 = reads[0], reads[1]
    agree = sum(1 for aid in key if r1[aid] == r2[aid])
    print(f"\nreader agreement: {agree}/{len(key)} ({agree / len(key):.0%})")
    conf = Counter((r1[aid], r2[aid]) for aid in key)
    for (b1, b2), n in sorted(conf.items(), key=lambda kv: -kv[1]):
        marker = "" if b1 == b2 else "   <- disagreement -> pairwise"
        print(f"    r1={b1:<5} r2={b2:<5} {n:>4}{marker}")

    moves = {}
    routed_say = 0
    for aid, meta in key.items():
        agreed = r1[aid] if r1[aid] == r2[aid] else None
        route = "say" if agreed == "SAY" else "pairwise"
        routed_say += route == "say"
        moves[f"{meta['scenario']}:{meta['move_id']}"] = {
            "route": route,
            "class": agreed or "DISAGREEMENT",
            "readers": [r1[aid], r2[aid]],
            "playbook_id": meta["playbook_id"],
            "criterion_sha256": meta["criterion_sha256"],
        }
    print(f"\nrouting: {routed_say} moves -> say arm, "
          f"{len(moves) - routed_say} moves -> pairwise")

    if not write:
        print(f"\n(dry run -- pass --write to write {ARTIFACT.name})")
        return
    ARTIFACT.write_text(json.dumps({
        "created": date.today().isoformat(),
        "protocol": ("two independent blind readers over ld_moveclass_packet.txt "
                     "(opaque ids, seeded shuffle, criteria only); disagreement "
                     "routes to pairwise; criteria pinned by sha256"),
        "reads": [p.name for p in read_paths],
        "reader_agreement": f"{agree}/{len(key)}",
        "moves": moves,
    }, indent=2), encoding="utf-8")
    print(f"[artifact] {len(moves)} moves -> {ARTIFACT}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--packet", action="store_true")
    ap.add_argument("--score", nargs="+", type=Path, default=None,
                    metavar="READ", help="score 1+ returned reads (2 to adjudicate)")
    ap.add_argument("--write", action="store_true",
                    help="with --score and 2 reads: write the routing artifact")
    a = ap.parse_args()
    if a.packet:
        rows = collect()
        if not rows:
            raise SystemExit("no live playbook moves found")
        write_packet(rows)
    elif a.score:
        score(a.score, a.write)
    else:
        raise SystemExit("pass --packet or --score READ1 [READ2]")


if __name__ == "__main__":
    main()
