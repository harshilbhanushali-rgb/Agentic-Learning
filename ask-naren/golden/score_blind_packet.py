"""Unblind a reader's grades and report, calibration FIRST.

Calibration: the reader's grade of the prod baseline vs Naren's own verdict on it. If they
disagree on more than `--max-disagree` cases the reader is not trusted and the comparison is
printed only as a warning, never as a result.

Naren's scale maps to the reader's: right -> pass; right_with_gaps / partly_right -> partial;
wrong / wrongly_declined -> fail.

Usage: python ask-naren/golden/score_blind_packet.py <golden.json> <name>.key.json <grades.json>
grades.json: {"<case>": {"<label>": {"grade": "pass|partial|fail", "why": "..."}}}
"""
import argparse
import json
from collections import defaultdict

NAREN = {"right": "pass", "right_with_gaps": "partial", "partly_right": "partial",
         "wrong": "fail", "wrongly_declined": "fail"}
POINTS = {"pass": 2, "partial": 1, "fail": 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("golden")
    ap.add_argument("key")
    ap.add_argument("grades")
    ap.add_argument("--max-disagree", type=int, default=2)
    a = ap.parse_args()
    cases = {c["id"]: c for c in json.load(open(a.golden, encoding="utf-8"))["cases"]}
    key = json.load(open(a.key))
    grades = json.load(open(a.grades))

    by_src = defaultdict(dict)
    for cid, labels in key.items():
        for lab, src in labels.items():
            by_src[src][cid] = grades[cid][lab]

    print("CALIBRATION -- reader vs Naren on the prod baseline")
    off = 0
    for cid, c in cases.items():
        want, got = NAREN[c["naren_verdict"]], by_src["baseline"][cid]["grade"]
        mark = "ok " if want == got else "OFF"
        off += want != got
        print(f"  {mark} {cid}  naren={c['naren_verdict']:<17} ({want:<7}) reader={got}")
    trusted = off <= a.max_disagree
    print(f"  {off} disagreement(s); bar <= {a.max_disagree}: {'PASS' if trusted else 'FAIL -- results below are NOT trustworthy'}\n")

    print("RESULTS (pass=2, partial=1, fail=0)")
    srcs = ["baseline"] + sorted(s for s in by_src if s != "baseline")
    print("  case       " + "  ".join(f"{s[:16]:<16}" for s in srcs))
    for cid in cases:
        print(f"  {cid}  " + "  ".join(f"{by_src[s][cid]['grade']:<16}" for s in srcs))
    print("  total      " + "  ".join(f"{sum(POINTS[g['grade']] for g in by_src[s].values()):<2}/{2 * len(cases):<13}" for s in srcs))
    for s in srcs:
        n = defaultdict(int)
        for g in by_src[s].values():
            n[g["grade"]] += 1
        print(f"  {s}: {n['pass']} pass, {n['partial']} partial, {n['fail']} fail")
    if not trusted:
        print("\nREADER FAILED CALIBRATION -- re-read, do not report these numbers.")


if __name__ == "__main__":
    main()
