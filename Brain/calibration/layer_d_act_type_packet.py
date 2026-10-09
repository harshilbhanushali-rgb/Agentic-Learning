#!/usr/bin/env python3
"""ACT-TYPE BLIND CLASSIFICATION — does a move's ACT TYPE predict pairwise blurriness?

Zero chat calls, zero writes. Read-only Postgres.

THE QUESTION. On the 2026-08-26/27 regrade, 24 of 77 rankable (scenario, move) cells came
back BLURRY (>=80% of pairwise comparisons a tie). Five mechanical explanations were measured
and all came back null (see docs/findings/layer-d-redesign.md):

    vague/evaluative wording   only 2 of 24 blurry cells carry a banned adjective
    criterion length           27.2 words blurry vs 26.9 sharp
    bundling (conjunctions)    2.4 marks blurry vs 2.2 sharp
    low volume                 blurry rate RISES with attempts (33/24/33/43%)
    exemplar pool size         233 pairs/155 calls blurry vs 221/153 sharp

The surviving hypothesis is about what the move IS, not how it is worded:

    A move that is COMPLETE ONCE SAID ("recommend X", "warn about Y", "state that Z")
    admits no better-or-worse. Once both replies have said it or not said it, "which
    handled this better" has no answer, so a tie is the CORRECT verdict and the cell is
    structurally unrankable by a pairwise judge.

    A move that is WORK PERFORMED WITH VARIABLE DEPTH ("investigate the discrepancy",
    "provision access", "coordinate the deliverable") has a quality gradient a judge can
    rank.

If that holds, roughly half the playbook's moves cannot be scored by this arm at all --
a DESIGN finding about the grader/move fit, not a backlog of badly written criteria. And
it predicts a rewrite makes things WORSE: making a speech act more concrete makes it more
binary, which is consistent with the gradability-remade documents being 44% blurry against
the backfill's 27%.

WHY BLIND. A crude head-verb regex already separated (SAY 38% blurry vs DO 10%), but that
regex was written by the same person who formed the hypothesis, after seeing which cells
were blurry. This replaces it with a reader that cannot see tie rates, scenario names, or
move ids -- so the classification cannot be fitted to the outcome.

PRE-REGISTERED, before the packet was built:
    prediction     blurry rate among SAY > blurry rate among DO
    supported if   SAY blurry rate >= 2x DO's AND >= 15 of the 24 blurry cells are SAY
    refuted if     the two rates are within noise of each other
    A PARTIAL READ IS NOT SCORED -- pbg_score_blind_read's rule, same reason.

Usage:
    python calibration/layer_d_act_type_packet.py --packet     # build packet + withheld key
    python calibration/layer_d_act_type_packet.py --score FILE # join a read back to the key
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibration import ARTIFACTS_DIR  # noqa: E402

RUN = "137706da74c6"
ARM = "pairwise"
FLOOR = 8      # the report's ranking floor
BLURRY = 0.80  # >=80% tie

PACKET = ARTIFACTS_DIR / "ld_acttype_packet.txt"
KEY = ARTIFACTS_DIR / "ld_acttype_KEY.json"

BUCKETS = ("SAY", "DO", "MIXED")
_LINE = re.compile(r"^\s*(A\d{3})\s+(SAY|DO|MIXED)\b(.*)$")


def _connect():
    """Plain connection. Deliberately does NOT set default_transaction_read_only --
    that setting leaks across unrelated clients through Neon's pooler and has already
    cost this project a full Layer D run (docs/GOTCHAS.md, 2026-08-26). This script
    simply never writes."""
    import psycopg
    from config import load_config
    url = load_config().database_url
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + "hostaddr=18.138.49.39"
    return psycopg.connect(url, autocommit=True)


def collect() -> list[dict]:
    """Every rankable cell with its criterion and measured tie rate. Read-only."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT scenario_key, verdicts FROM move_events
                       WHERE run_id = %s AND grader_arm = %s
                         AND rater_population = 'csm'""", (RUN, ARM))
        tally: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for sk, vjson in cur.fetchall():
            vs = vjson if isinstance(vjson, list) else json.loads(vjson or "[]")
            for v in vs:
                if v.get("verdict") in ("hit", "partial", "miss") and v.get("move_id"):
                    tally[(sk, v["move_id"])][v["verdict"]] += 1

        cur.execute("""SELECT scenario_key, playbook_id, key_moves
                       FROM playbooks WHERE status = 'live'""")
        moves = {}
        for sk, pid, km in cur.fetchall():
            for i, mv in enumerate(km or [], start=1):
                moves[(sk, f"M{i}")] = (pid, mv.get("criterion", ""), mv.get("name", ""))

    out = []
    for (sk, mid), c in tally.items():
        n = c["hit"] + c["partial"] + c["miss"]
        if n < FLOOR:
            continue
        entry = moves.get((sk, mid))
        if not entry:
            continue
        pid, criterion, name = entry
        if not criterion.strip():
            continue
        out.append({
            "scenario": sk, "move_id": mid, "playbook_id": pid,
            "name": name, "criterion": criterion,
            "attempts": n, "ties": c["partial"],
            "tie_rate": c["partial"] / n,
            "blurry": (c["partial"] / n) >= BLURRY,
        })
    out.sort(key=lambda r: (r["scenario"], r["move_id"]))
    return out


def write_packet(rows: list[dict], seed: int = 20260827) -> None:
    """Opaque ids, seeded shuffle, and NO scenario name, move id, or tie rate.

    The shuffle matters for a specific reason: insertion order groups a document's moves
    together, and blurriness clusters by scenario, so unshuffled ids would hand the reader
    the very structure the hypothesis is about.
    """
    order = list(range(len(rows)))
    random.Random(seed).shuffle(order)

    lines = [
        "MOVE ACT-TYPE PACKET",
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
            "playbook_id": r["playbook_id"], "attempts": r["attempts"],
            "tie_rate": r["tie_rate"], "blurry": r["blurry"],
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
    nb = sum(1 for v in keymap.values() if v["blurry"])
    print(f"[withheld] {nb} of {len(keymap)} cells are blurry — NOT in the packet")


def score(read_path: Path) -> None:
    key = json.loads(KEY.read_text(encoding="utf-8"))
    got: dict[str, tuple[str, str]] = {}
    for raw in read_path.read_text(encoding="utf-8-sig").splitlines():
        m = _LINE.match(raw)
        if not m:
            continue
        aid, bucket, reason = m.group(1), m.group(2), m.group(3).strip()
        if aid in got and got[aid][0] != bucket:
            raise SystemExit(f"{aid} classified twice, inconsistently: "
                             f"{got[aid][0]} then {bucket}")
        got[aid] = (bucket, reason)

    extra = sorted(set(got) - set(key))
    if extra:
        raise SystemExit(f"read has {len(extra)} unknown ids: {extra[:8]}")
    missing = sorted(set(key) - set(got))
    if missing:
        raise SystemExit(
            f"PARTIAL READ — {len(missing)} of {len(key)} unclassified ({missing[:10]}...). "
            f"Refusing to score: a rate over the subset a reader happened to finish is not "
            f"a rate over the population.")

    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for aid, meta in key.items():
        by_bucket[got[aid][0]].append(meta)

    print(f"\n[act-type blind read] {len(got)}/{len(key)} classified, none missing\n")
    print(f"{'bucket':<10} {'cells':>6} {'blurry':>7} {'blurry rate':>12} {'mean tie':>9}")
    print("-" * 50)
    stats = {}
    for b in BUCKETS:
        rs = by_bucket.get(b)
        if not rs:
            continue
        nb = sum(1 for r in rs if r["blurry"])
        stats[b] = {"n": len(rs), "blurry": nb, "rate": nb / len(rs),
                    "tie": sum(r["tie_rate"] for r in rs) / len(rs)}
        print(f"{b:<10} {len(rs):>6} {nb:>7} {nb/len(rs):>11.0%} "
              f"{stats[b]['tie']:>8.0%}")
    tot_blurry = sum(1 for r in key.values() if r["blurry"])
    print("-" * 50)
    print(f"{'ALL':<10} {len(key):>6} {tot_blurry:>7} {tot_blurry/len(key):>11.0%}")

    print("\nPRE-REGISTERED DECISION RULE")
    say, do = stats.get("SAY"), stats.get("DO")
    if not say or not do:
        print("  INDETERMINATE — one of the two buckets is empty.")
        return
    say_blurry_share = (sum(1 for aid, m in key.items()
                            if m["blurry"] and got[aid][0] == "SAY"))
    ratio = (say["rate"] / do["rate"]) if do["rate"] else float("inf")
    print(f"  SAY blurry rate {say['rate']:.0%} vs DO {do['rate']:.0%}  ->  ratio "
          f"{ratio:.1f}x  (bar: >= 2.0x)")
    print(f"  blurry cells landing in SAY: {say_blurry_share}/{tot_blurry}  (bar: >= 15)")
    ok = ratio >= 2.0 and say_blurry_share >= 15
    print(f"\n  VERDICT: {'SUPPORTED' if ok else 'NOT SUPPORTED'} — "
          + ("act type predicts blurriness; ~half the playbook's moves are structurally "
             "unrankable by the pairwise arm, and rewriting their wording cannot fix that."
             if ok else
             "act type does NOT separate blurry from sharp cells. The hypothesis joins the "
             "other five as a null, and the cause of blurriness remains unidentified."))

    print("\nWhere the SAY cells actually are (scenario-level, for the record):")
    per = defaultdict(lambda: [0, 0])
    for aid, m in key.items():
        if got[aid][0] == "SAY":
            per[m["scenario"]][0] += 1
            per[m["scenario"]][1] += 1 if m["blurry"] else 0
    for sk, (n, nb) in sorted(per.items(), key=lambda kv: -kv[1][1])[:12]:
        print(f"    {sk[:52]:<52} {nb}/{n} blurry")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--packet", action="store_true", help="build the packet + withheld key")
    ap.add_argument("--score", type=Path, default=None, help="score a returned read")
    a = ap.parse_args()
    if a.packet:
        rows = collect()
        if not rows:
            raise SystemExit("no rankable cells found — check RUN/ARM")
        write_packet(rows)
    elif a.score:
        score(a.score)
    else:
        raise SystemExit("pass --packet or --score FILE")


if __name__ == "__main__":
    main()
