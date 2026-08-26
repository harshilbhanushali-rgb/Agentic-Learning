#!/usr/bin/env python3
"""Scores a blind auditor's verdicts against the packet key. Reports CONTROL DETECTION
FIRST, and refuses to report a rate over the real items unless the controls were separated.

The order is the whole point. A blind reader's absolute rate on this kind of material is an
artifact of framing (measured on this project: 84% vs 17% gradable on the same 123 criteria,
differing only in framing). So "N% of Ask Naren's answers are right" is meaningless on its
own; it is only worth reading from an auditor that demonstrably told known-wrong from
known-right on the same packet, in the same framing, in the same pass.

Gate, applied before any headline number is printed:
  * control_wrong  must be judged wrong at a high rate  -- a reader that passes these is
                   credulous, and its "right" verdicts on real items mean nothing.
  * control_right  must be judged right at a high rate  -- a reader that fails these is
                   indiscriminate, and its "wrong" verdicts mean nothing.

    python ask-naren/audit/score_answer_audit.py --verdicts artifacts/answer_audit_verdicts.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE / "artifacts"

# Both bars are deliberately high: the gate exists to disqualify an uninformative read, and
# a reader that cannot clear 2/3 on plants built to be obvious is not measuring judgment.
MIN_WRONG_CAUGHT = 0.67
MIN_RIGHT_KEPT = 0.67


def _verdict_of(v) -> str:
    """Normalise to right / wrong / uncertain, whatever shape the auditor emitted."""
    raw = (v.get("verdict") if isinstance(v, dict) else v) or ""
    raw = str(raw).strip().lower()
    if raw.startswith("right") or raw in {"yes", "correct", "good"}:
        return "right"
    if raw.startswith("wrong") or raw in {"no", "incorrect", "bad"}:
        return "wrong"
    return "uncertain"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default=str(ARTIFACTS / "answer_audit_key.json"))
    ap.add_argument("--verdicts", default=str(ARTIFACTS / "answer_audit_verdicts.json"))
    ap.add_argument("--packet", default=str(ARTIFACTS / "answer_audit_packet.json"))
    args = ap.parse_args()

    key = {k["id"]: k for k in json.loads(Path(args.key).read_text(encoding="utf-8"))}
    packet = {p["id"]: p for p in json.loads(Path(args.packet).read_text(encoding="utf-8"))}
    raw = json.loads(Path(args.verdicts).read_text(encoding="utf-8-sig"))
    verdicts = raw.get("verdicts", raw) if isinstance(raw, dict) else raw
    got = {int(v["id"]): v for v in verdicts}

    missing = sorted(set(key) - set(got))
    if missing:
        print(f"WARNING: no verdict for id(s) {missing} -- excluded from every rate below")

    def group(kind):
        return [(i, got[i]) for i in sorted(key) if key[i]["kind"] == kind and i in got]

    wrong_plants, right_plants, real = (group("control_wrong"), group("control_right"),
                                        group("real"))

    print("=" * 78)
    print("STEP 1 -- CONTROL DETECTION. If this fails, nothing below it is readable.")
    print("=" * 78)
    caught = sum(1 for _, v in wrong_plants if _verdict_of(v) == "wrong")
    kept = sum(1 for _, v in right_plants if _verdict_of(v) == "right")
    w_rate = caught / len(wrong_plants) if wrong_plants else 0.0
    r_rate = kept / len(right_plants) if right_plants else 0.0
    print(f"  known-WRONG plants judged wrong: {caught}/{len(wrong_plants)} "
          f"({w_rate:.0%})   bar {MIN_WRONG_CAUGHT:.0%}")
    print(f"  known-RIGHT plants judged right: {kept}/{len(right_plants)} "
          f"({r_rate:.0%})   bar {MIN_RIGHT_KEPT:.0%}")
    for label, items in (("wrong-plant MISSED", wrong_plants), ("right-plant REJECTED",
                                                               right_plants)):
        want = "wrong" if "wrong" in label else "right"
        for i, v in items:
            if _verdict_of(v) != want:
                reason = (v.get("reason") or "")[:100] if isinstance(v, dict) else ""
                print(f"    {label} id={i} -> {_verdict_of(v)}: {reason}")

    passed = w_rate >= MIN_WRONG_CAUGHT and r_rate >= MIN_RIGHT_KEPT
    print(f"\n  GATE: {'PASSED' if passed else 'FAILED'}")
    if not passed:
        print("  The auditor did not separate the plants, so its verdicts on the real items")
        print("  carry no information and are NOT reported as a rate. This is a real result")
        print("  about the instrument, not a failed run: it says this packet cannot be read")
        print("  this way, and the question needs a human reader or a different design.")
        return 0

    print("\n" + "=" * 78)
    print("STEP 2 -- THE REAL ITEMS (readable only because the gate passed)")
    print("=" * 78)
    counts = Counter(_verdict_of(v) for _, v in real)
    n = len(real)
    for label in ("right", "wrong", "uncertain"):
        print(f"  {label:9s}: {counts[label]:2d}/{n}  ({counts[label] / n:.0%})")

    print("\n  split by whether retrieval landed in the same primary scenario:")
    for same in (True, False):
        grp = [(i, v) for i, v in real if key[i].get("same_scenario") is same]
        if not grp:
            continue
        right = sum(1 for _, v in grp if _verdict_of(v) == "right")
        print(f"    same_scenario={str(same):5s}: {right}/{len(grp)} judged right")

    cos_right = [key[i]["cosine"] for i, v in real if _verdict_of(v) == "right"]
    cos_wrong = [key[i]["cosine"] for i, v in real if _verdict_of(v) == "wrong"]
    if cos_right and cos_wrong:
        print(f"\n  retrieval cosine: judged-right mean "
              f"{sum(cos_right) / len(cos_right):.3f}  vs judged-wrong mean "
              f"{sum(cos_wrong) / len(cos_wrong):.3f}")
        print("  (a real separation here is what a retrieval floor would need; the earlier")
        print("   diagnosis found none between answered and declined items)")

    print("\n  every real item judged WRONG, with the auditor's reason:")
    for i, v in real:
        if _verdict_of(v) == "wrong":
            print(f"    id={i} cos={key[i]['cosine']:.3f} "
                  f"held={key[i]['held_out_scenario'][:30]} "
                  f"ret={key[i]['retrieved_scenario'][:30]}")
            print(f"      {(v.get('reason') or '')[:200]}")
            print(f"      situation: {packet[i]['situation'][:160]}")

    out = ARTIFACTS / "answer_audit_scored.json"
    out.write_text(json.dumps({
        "gate": {"wrong_caught": caught, "wrong_total": len(wrong_plants),
                 "right_kept": kept, "right_total": len(right_plants), "passed": passed},
        "real": {"n": n, **{k: counts[k] for k in ("right", "wrong", "uncertain")}},
        "items": [{"id": i, "kind": key[i]["kind"], "verdict": _verdict_of(v),
                   "reason": v.get("reason") if isinstance(v, dict) else None,
                   **{k: key[i].get(k) for k in ("cosine", "same_scenario",
                                                 "held_out_scenario", "retrieved_scenario")}}
                  for i, v in sorted(got.items()) if i in key],
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
