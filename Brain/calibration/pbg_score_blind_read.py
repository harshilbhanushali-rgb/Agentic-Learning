#!/usr/bin/env python3
"""SCORE a blind gradability read against the withheld key. ZERO chat calls, ZERO writes.

Companion to `playbook_gradability_census.py --packet`. The packet went to a reader with the
cohort and scenario withheld; this joins the returned buckets back to the key and reports the
gradable rate PER COHORT -- which is the number the "re-run all 34 at the gradable config"
decision turns on.

Input format, one line per item, exactly as the packet asks for:
    C001 GRADABLE names a specific ZIP-radius number

REFUSES to score a partial read. A reader that silently skipped items would otherwise report
a rate over whatever it happened to cover, which is the §11.3 trap (a subset promising a rate)
wearing different clothes.

Also reports the agreement between the deterministic banned-adjective scan (instrument A) and
the blind read (instrument B). They are NOT expected to agree: A is a declared lower bound.
Printing the confusion is how we keep A honest about being a floor -- every NOT_GRADABLE item
with no banned adjective is an item A structurally cannot see.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibration import ARTIFACTS_DIR  # noqa: E402

BUCKETS = ("GRADABLE", "BORDERLINE", "NOT_GRADABLE")
_LINE = re.compile(r"^\s*(C\d{3})\s+(GRADABLE|BORDERLINE|NOT_GRADABLE)\b(.*)$")


def parse(text: str) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for raw in text.splitlines():
        m = _LINE.match(raw)
        if not m:
            continue
        cid, bucket, reason = m.group(1), m.group(2), m.group(3).strip()
        if cid in out and out[cid][0] != bucket:
            raise SystemExit(f"{cid} classified twice and inconsistently: "
                             f"{out[cid][0]} then {bucket}")
        out[cid] = (bucket, reason)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("read", type=Path, help="the reader's verbatim output")
    ap.add_argument("--key", type=Path, default=ARTIFACTS_DIR / "pbg_criteria_KEY.json")
    ap.add_argument("--dump", type=Path, default=None)
    a = ap.parse_args()

    key = json.loads(a.key.read_text(encoding="utf-8"))
    got = parse(a.read.read_text(encoding="utf-8-sig"))

    missing = sorted(set(key) - set(got))
    extra = sorted(set(got) - set(key))
    if extra:
        raise SystemExit(f"read contains {len(extra)} ids not in the key: {extra[:8]}")
    if missing:
        raise SystemExit(
            f"PARTIAL READ -- {len(missing)} of {len(key)} items unclassified "
            f"({missing[:10]}...). Refusing to score: a rate over a subset the reader chose "
            f"is not a rate over the population.")

    by_cohort: dict[str, Counter] = defaultdict(Counter)
    for cid, meta in key.items():
        by_cohort[meta["cohort"]][got[cid][0]] += 1

    print(f"\n[blind read] {len(got)}/{len(key)} criteria classified, none missing\n")
    print(f"{'cohort':<32} {'n':>4} {'GRAD':>6} {'BORD':>6} {'NOT':>6} {'gradable':>9} "
          f"{'usable*':>8}")
    print("-" * 78)
    order = sorted(by_cohort, key=lambda c: (not c.startswith("original"), c))
    for cohort in order:
        c = by_cohort[cohort]
        n = sum(c.values())
        print(f"{cohort:<32} {n:>4} {c['GRADABLE']:>6} {c['BORDERLINE']:>6} "
              f"{c['NOT_GRADABLE']:>6} {c['GRADABLE'] / n:>8.0%} "
              f"{(c['GRADABLE'] + c['BORDERLINE']) / n:>7.0%}")
    tot = Counter()
    for c in by_cohort.values():
        tot += c
    n = sum(tot.values())
    print("-" * 78)
    print(f"{'ALL LIVE':<32} {n:>4} {tot['GRADABLE']:>6} {tot['BORDERLINE']:>6} "
          f"{tot['NOT_GRADABLE']:>6} {tot['GRADABLE'] / n:>8.0%} "
          f"{(tot['GRADABLE'] + tot['BORDERLINE']) / n:>7.0%}")
    print("\n  *usable = GRADABLE + BORDERLINE, i.e. the generous reading. The strict reading\n"
          "   is the 'gradable' column. Report both; do not quietly pick the flattering one.")

    print("\nINSTRUMENT A vs B -- is the banned-adjective scan a usable proxy?")
    a_hit_b = Counter()
    for cid, meta in key.items():
        a_hit_b[(bool(meta["banned"]), got[cid][0])] += 1
    print(f"{'':<22} {'GRADABLE':>10} {'BORDERLINE':>11} {'NOT_GRADABLE':>13}")
    for flag, label in ((True, "banned adjective"), (False, "no banned adj.")):
        print(f"{label:<22} {a_hit_b[(flag, 'GRADABLE')]:>10} "
              f"{a_hit_b[(flag, 'BORDERLINE')]:>11} "
              f"{a_hit_b[(flag, 'NOT_GRADABLE')]:>13}")
    ungrad = tot["NOT_GRADABLE"]
    invisible = a_hit_b[(False, "NOT_GRADABLE")]
    if ungrad:
        print(f"\n  {invisible}/{ungrad} ({invisible / ungrad:.0%}) of ungradable criteria carry "
              f"NO banned adjective:\n  the deterministic scan structurally cannot see them. It "
              f"is a floor, not the rate.")

    worst = sorted(
        ((sum(1 for cid, m in key.items()
              if m["scenario_key"] == sk and got[cid][0] == "NOT_GRADABLE"),
          sum(1 for m in key.values() if m["scenario_key"] == sk), sk)
         for sk in {m["scenario_key"] for m in key.values()}),
        key=lambda t: (-t[0] / t[1], -t[0]))
    print("\nWORST DOCUMENTS by ungradable share (re-run candidates, worst first):")
    for bad, n_moves, sk in worst[:10]:
        if not bad:
            break
        print(f"    {bad}/{n_moves} ungradable  {sk}")
    clean = [sk for bad, _n, sk in worst if bad == 0]
    print(f"\n  {len(clean)} of {len(worst)} documents have ZERO ungradable criteria.")

    if a.dump:
        a.dump.write_text(json.dumps(
            {cid: {**key[cid], "bucket": got[cid][0], "reason": got[cid][1]} for cid in key},
            indent=2), encoding="utf-8")
        print(f"\n[dump] {a.dump}")


if __name__ == "__main__":
    main()
