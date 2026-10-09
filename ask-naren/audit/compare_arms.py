#!/usr/bin/env python3
"""Issue #8: A/B the candidate-shortlist arms (k=1 against k=5) as a PAIRED, WITHIN-PACKET
comparison, and report per-item movement in both directions.

    python ask-naren/audit/compare_arms.py --build      # one blind packet, both arms
    python ask-naren/audit/compare_arms.py --score      # gate, then the comparison

WHY BOTH ARMS GO IN ONE PACKET. The obvious design -- read the k=5 arm and compare its rate
against issue #7's cached 83% -- is the single most expensive mistake available here. A
blind reader's ABSOLUTE rate on this material is an artifact of framing: measured on this
project, two reads of the same 123 criteria returned 84% and 17% gradable, differing only
in how the reader was framed. Two reads at two times, however carefully worded, cannot be
subtracted from each other. So every item from both arms is shuffled into ONE packet, read
in ONE pass under ONE framing, with the same controls gating both. What survives is a
DIFFERENCE measured under a constant, which is the only thing this instrument can supply.

Known cost of that choice: a situation appears TWICE in the packet, once per arm, so a
reader may notice the pairing and anchor the second on the first. Judged the lesser risk --
issue #7's packet already contained the same situation twice (id 28/30, a real item and its
positive control) and the reader handled both on their merits. The alternative is comparing
across framings, which is not a comparison at all.

WHAT IS COMPARED WITHOUT A READER AT ALL. Decline rate, grounding-failure rate, and the
rank the answer was actually grounded at are all recorded facts, not judgments; --score
reports them from the raw files whether verdicts exist or not. Only "is the answer right"
needs the blind read.

PAIRING RULE. An item enters the judged comparison only if BOTH arms answered that
situation. A situation answered in one arm and declined in the other is a decline-rate
movement and is reported as one -- scoring it as a win or loss for rightness would be
comparing an answer against a non-answer.

The controls are REUSED VERBATIM from each arm's own packet rather than rebuilt, so the
gate the reader clears here is the gate issue #7 validated. Both arms' positive controls are
included: k=1's, and k=5's, which additionally asks whether the shortlist prompt can still
get an easy item right when retrieval is perfect.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE / "artifacts"

_spec = importlib.util.spec_from_file_location("saa", HERE / "score_answer_audit.py")
_saa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_saa)
# One definition of the verdict normaliser and of the control bars, shared with the
# single-arm scorer. Two copies would let the A/B's gate drift from the gate that produced
# the number it is being compared against.
_verdict_of = _saa._verdict_of
MIN_WRONG_CAUGHT = _saa.MIN_WRONG_CAUGHT
MIN_RIGHT_KEPT = _saa.MIN_RIGHT_KEPT

ARMS = (1, 5)
SEED = 20260827


def _was_declined(result: dict) -> bool:
    """Whether a recorded result was a decline, across BOTH artifact generations.

    The response contract discriminates on `outcome` (issue #13); artifacts written before
    that carry a `declined` boolean. The committed artifacts behind the measured ~80% are
    FROZEN and still carry the boolean -- regenerating them costs real spend and a
    regenerated arm is no longer comparable to the number it exists to be compared against.
    So both shapes stay readable, permanently. Same rule as build_answer_audit.was_declined,
    repeated rather than imported because that module pulls in the embedder.
    """
    if "outcome" in result:
        return result["outcome"] != "answered"
    return bool(result["declined"])


def _arm_file(name: str, k: int) -> Path:
    return ARTIFACTS / (f"{name}.json" if k == 1 else f"{name}_k{k}.json")


def _load(path: Path):
    if not path.exists():
        raise SystemExit(f"ERROR: {path} not found -- generate that arm first "
                         f"(build_answer_audit.py --k N)")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _raw_by_situation(k: int) -> dict[str, dict]:
    return {r["situation"]: r for r in _load(_arm_file("answer_audit_raw", k))}


def build(args) -> int:
    raw = {k: _raw_by_situation(k) for k in ARMS}

    shared = sorted(set(raw[1]) & set(raw[5]))
    print(f"[situations] k=1 {len(raw[1])}, k=5 {len(raw[5])}, "
          f"in both {len(shared)}")
    if len(shared) < min(len(raw[1]), len(raw[5])):
        print("  NOTE: the arms do not cover identical situations. Only the shared ones "
              "are paired; the rest are excluded from the judged comparison.")

    judged = [s for s in shared
              if not _was_declined(raw[1][s]["result"])
              and not _was_declined(raw[5][s]["result"])]
    print(f"[paired] {len(judged)} situations answered by BOTH arms -> "
          f"{len(judged) * 2} real items")

    items, key = [], []

    def add(situation, client_said, naren_replied, answer, meta):
        items.append({"situation": situation, "retrieved_client_said": client_said,
                      "retrieved_naren_replied": naren_replied, "answer": answer})
        key.append(meta)

    for n, situation in enumerate(judged):
        for k in ARMS:
            r = raw[k][situation]
            add(situation, r["retrieved_trigger"], r["retrieved_response"],
                r["result"]["answer"],
                {"kind": "real", "arm": k, "pair_index": n,
                 "same_scenario": r["same_scenario"], "cosine": r["cosine"],
                 "grounded_rank": r.get("grounded_rank"),
                 "held_out_scenario": r["held_out_scenario"],
                 "retrieved_scenario": r["retrieved_scenario"]})

    # Controls, lifted verbatim from each arm's own packet: the gate the reader clears here
    # is the gate issue #7 validated, not a fresh one built alongside the comparison.
    for k in ARMS:
        packet = {p["id"]: p for p in _load(_arm_file("answer_audit_packet", k))}
        for entry in _load(_arm_file("answer_audit_key", k)):
            if entry["kind"] not in ("control_wrong", "control_right"):
                continue
            p = packet[entry["id"]]
            add(p["situation"], p["retrieved_client_said"], p["retrieved_naren_replied"],
                p["answer"], {"kind": entry["kind"], "arm": k})

    rng = np.random.default_rng(args.seed)
    order = rng.permutation(len(items))
    blind = [{"id": n + 1, **items[j]} for n, j in enumerate(order)]
    answer_key = [{"id": n + 1, **key[j]} for n, j in enumerate(order)]

    (ARTIFACTS / "arms_packet.json").write_text(
        json.dumps(blind, indent=2), encoding="utf-8")
    (ARTIFACTS / "arms_key.json").write_text(
        json.dumps(answer_key, indent=2), encoding="utf-8")

    counts: dict[str, int] = {}
    for entry in answer_key:
        label = f"{entry['kind']}(arm {entry['arm']})"
        counts[label] = counts.get(label, 0) + 1
    print(f"[packet] {len(blind)} items {counts} -> artifacts/arms_packet.json")
    print("         the packet does NOT say which arm any item came from; arms_key.json "
          "does.")
    return 0


def _exact_two_sided_p(a: int, b: int) -> float:
    """McNemar's exact test on the discordant pairs: if the shortlist changed nothing, each
    disagreement is a coin flip. Reported instead of a chi-square because the counts here
    are single digits, where the approximation is not trustworthy."""
    n = a + b
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(a, b) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def _structural(raw) -> None:
    print("=" * 78)
    print("RECORDED FACTS -- no reader involved, no gate needed")
    print("=" * 78)
    for k in ARMS:
        rows = list(raw[k].values())
        declined = [r for r in rows if _was_declined(r["result"])]
        reasons: dict[str, int] = {}
        for r in declined:
            reasons[r["result"]["reason"]] = reasons.get(r["result"]["reason"], 0) + 1
        answered = [r for r in rows if not _was_declined(r["result"])]
        same = sum(1 for r in answered if r["same_scenario"])
        print(f"  k={k}: {len(rows)} items, {len(answered)} answered, "
              f"{len(declined)} declined ({len(declined) / max(len(rows), 1):.0%}) "
              f"{reasons}")
        print(f"        answered items whose grounded exchange shares the situation's "
              f"primary scenario: {same}/{len(answered)}")
        ranks: dict = {}
        for r in answered:
            rk = r.get("grounded_rank")
            ranks[rk] = ranks.get(rk, 0) + 1
        if any(x is not None for x in ranks):
            print(f"        rank the answer was grounded at: "
                  f"{dict(sorted(ranks.items(), key=lambda kv: (kv[0] is None, kv[0])))}")
    print()


def score(args) -> int:
    raw = {k: _raw_by_situation(k) for k in ARMS}
    _structural(raw)

    key_path, verdict_path = ARTIFACTS / "arms_key.json", Path(args.verdicts)
    if not verdict_path.exists():
        print(f"No verdicts at {verdict_path} yet -- the recorded facts above stand "
              f"without them.\nRun the blind read over artifacts/arms_packet.json, save "
              f"verdicts, then re-run with --score.")
        return 0

    key = {e["id"]: e for e in _load(key_path)}
    rawv = _load(verdict_path)
    verdicts = rawv.get("verdicts", rawv) if isinstance(rawv, dict) else rawv
    got = {int(v["id"]): v for v in verdicts}

    missing = sorted(set(key) - set(got))
    if missing:
        print(f"WARNING: no verdict for id(s) {missing} -- excluded from every rate below")

    print("=" * 78)
    print("STEP 1 -- CONTROL DETECTION. If this fails, nothing below it is readable.")
    print("=" * 78)
    wrong = [(i, got[i]) for i in sorted(key)
             if key[i]["kind"] == "control_wrong" and i in got]
    right = [(i, got[i]) for i in sorted(key)
             if key[i]["kind"] == "control_right" and i in got]
    caught = sum(1 for _, v in wrong if _verdict_of(v) == "wrong")
    kept = sum(1 for _, v in right if _verdict_of(v) == "right")
    w_rate = caught / len(wrong) if wrong else 0.0
    r_rate = kept / len(right) if right else 0.0
    print(f"  known-WRONG plants judged wrong: {caught}/{len(wrong)} ({w_rate:.0%})   "
          f"bar {MIN_WRONG_CAUGHT:.0%}")
    print(f"  known-RIGHT plants judged right: {kept}/{len(right)} ({r_rate:.0%})   "
          f"bar {MIN_RIGHT_KEPT:.0%}")
    for k in ARMS:
        arm_right = [(i, v) for i, v in right if key[i]["arm"] == k]
        if arm_right:
            ok = sum(1 for _, v in arm_right if _verdict_of(v) == "right")
            print(f"    of which arm k={k}: {ok}/{len(arm_right)} -- whether THAT arm's "
                  f"prompt can get an easy item right when retrieval is perfect")
    if w_rate < MIN_WRONG_CAUGHT or r_rate < MIN_RIGHT_KEPT:
        print("\nGATE FAILED. This read does not separate known-wrong from known-right, "
              "so no comparison is printed. Re-frame the read and repeat -- do NOT quote "
              "a number from this pass.")
        return 1
    print("  gate PASSED -- the comparison below is readable.\n")

    print("=" * 78)
    print("STEP 2 -- PER-ITEM MOVEMENT (the paired comparison)")
    print("=" * 78)
    by_pair: dict[int, dict[int, str]] = {}
    for i, entry in key.items():
        if entry["kind"] != "real" or i not in got:
            continue
        by_pair.setdefault(entry["pair_index"], {})[entry["arm"]] = _verdict_of(got[i])

    complete = {p: v for p, v in by_pair.items() if set(v) == set(ARMS)}
    fixed = [p for p, v in complete.items() if v[1] != "right" and v[5] == "right"]
    broke = [p for p, v in complete.items() if v[1] == "right" and v[5] != "right"]
    both_r = [p for p, v in complete.items() if v[1] == "right" and v[5] == "right"]
    both_w = [p for p, v in complete.items() if v[1] != "right" and v[5] != "right"]

    print(f"  paired situations judged in both arms: {len(complete)}")
    print(f"    right in both              : {len(both_r)}")
    print(f"    FIXED by k=5               : {len(fixed)}")
    print(f"    BROKEN by k=5              : {len(broke)}")
    print(f"    wrong in both              : {len(both_w)}")
    for k in ARMS:
        n_right = sum(1 for v in complete.values() if v[k] == "right")
        print(f"  k={k} right: {n_right}/{len(complete)} "
              f"({n_right / max(len(complete), 1):.0%})")
    p = _exact_two_sided_p(len(fixed), len(broke))
    print(f"  discordant pairs {len(fixed)} vs {len(broke)}, McNemar exact two-sided "
          f"p = {p:.3f}")
    print("  A wash in the headline can hide equal numbers fixed and broken -- which is "
          "why\n  the two directions are printed separately and are the result, not the "
          "rate.")

    out = {"paired": len(complete), "fixed_by_k5": len(fixed), "broken_by_k5": len(broke),
           "right_in_both": len(both_r), "wrong_in_both": len(both_w), "mcnemar_p": p,
           "per_arm_right": {str(k): sum(1 for v in complete.values() if v[k] == "right")
                             for k in ARMS},
           "control_wrong_caught": [caught, len(wrong)],
           "control_right_kept": [kept, len(right)]}
    (ARTIFACTS / "arms_comparison.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    print("\n-> artifacts/arms_comparison.json")
    return 0


# ---------------------------------------------------------------------------------------
# The EXCLUSIVE items: situations exactly one arm answered.
#
# The paired comparison above is structurally blind to these, and they are where the whole
# coverage question lives. k=5 declining a situation k=1 answered is only a loss if that
# answer was RIGHT, and k=5 answering one k=1 declined is only a gain if that answer is
# right -- neither is knowable from the decline counts, which is why "k=5 declines more" is
# not by itself a verdict in either direction.
#
# Both directions go in ONE packet under ONE framing, for the same reason the arms did:
# these ten items are being compared against each other, and half of them were previously
# judged only under issue #7's framing, which was never written down.
# ---------------------------------------------------------------------------------------

def build_unpaired(args) -> int:
    raw = {k: _raw_by_situation(k) for k in ARMS}
    shared = sorted(set(raw[1]) & set(raw[5]))
    def dec(r):
        return _was_declined(r["result"])

    exclusive = []
    for s in shared:
        answered = [k for k in ARMS if not dec(raw[k][s])]
        if len(answered) == 1:
            exclusive.append((s, answered[0]))
    counts = {k: sum(1 for _, a in exclusive if a == k) for k in ARMS}
    print(f"[exclusive] {len(exclusive)} situations answered by exactly ONE arm: "
          f"{{k=1 only: {counts[1]}, k=5 only: {counts[5]}}}")

    items, key = [], []

    def add(situation, client_said, naren_replied, answer, meta):
        items.append({"situation": situation, "retrieved_client_said": client_said,
                      "retrieved_naren_replied": naren_replied, "answer": answer})
        key.append(meta)

    for situation, arm in exclusive:
        r = raw[arm][situation]
        add(situation, r["retrieved_trigger"], r["retrieved_response"],
            r["result"]["answer"],
            {"kind": "real", "arm": arm, "grounded_rank": r.get("grounded_rank"),
             "same_scenario": r["same_scenario"], "cosine": r["cosine"],
             "declined_by": [k for k in ARMS if k != arm]})

    # The same controls, verbatim, that gated the paired read. Reused rather than rebuilt so
    # this read clears the identical bar -- and so a gate failure here means the reader, not
    # a freshly-built plant.
    for k in ARMS:
        packet = {p["id"]: p for p in _load(_arm_file("answer_audit_packet", k))}
        for entry in _load(_arm_file("answer_audit_key", k)):
            if entry["kind"] not in ("control_wrong", "control_right"):
                continue
            pk = packet[entry["id"]]
            add(pk["situation"], pk["retrieved_client_said"],
                pk["retrieved_naren_replied"], pk["answer"],
                {"kind": entry["kind"], "arm": k})

    rng = np.random.default_rng(args.seed + 1)
    order = rng.permutation(len(items))
    blind = [{"id": n + 1, **items[j]} for n, j in enumerate(order)]
    answer_key = [{"id": n + 1, **key[j]} for n, j in enumerate(order)]
    (ARTIFACTS / "unpaired_packet.json").write_text(
        json.dumps(blind, indent=2), encoding="utf-8")
    (ARTIFACTS / "unpaired_key.json").write_text(
        json.dumps(answer_key, indent=2), encoding="utf-8")
    kinds: dict[str, int] = {}
    for e in answer_key:
        kinds[f"{e['kind']}(arm {e['arm']})"] = kinds.get(f"{e['kind']}(arm {e['arm']})", 0) + 1
    print(f"[packet] {len(blind)} items {kinds} -> artifacts/unpaired_packet.json")
    return 0


def score_unpaired(args) -> int:
    key = {e["id"]: e for e in _load(ARTIFACTS / "unpaired_key.json")}
    vpath = Path(args.verdicts if args.verdicts != str(ARTIFACTS / "arms_verdicts.json")
                 else ARTIFACTS / "unpaired_verdicts.json")
    if not vpath.exists():
        raise SystemExit(f"ERROR: no verdicts at {vpath} -- run the blind read over "
                         f"artifacts/unpaired_packet.json first")
    rawv = _load(vpath)
    verdicts = rawv.get("verdicts", rawv) if isinstance(rawv, dict) else rawv
    got = {int(v["id"]): v for v in verdicts}

    print("=" * 78)
    print("STEP 1 -- CONTROL DETECTION (the same plants that gated the paired read)")
    print("=" * 78)
    wrong = [(i, got[i]) for i in sorted(key)
             if key[i]["kind"] == "control_wrong" and i in got]
    right = [(i, got[i]) for i in sorted(key)
             if key[i]["kind"] == "control_right" and i in got]
    caught = sum(1 for _, v in wrong if _verdict_of(v) == "wrong")
    kept = sum(1 for _, v in right if _verdict_of(v) == "right")
    w_rate = caught / len(wrong) if wrong else 0.0
    r_rate = kept / len(right) if right else 0.0
    print(f"  known-WRONG judged wrong: {caught}/{len(wrong)} ({w_rate:.0%})  "
          f"bar {MIN_WRONG_CAUGHT:.0%}")
    print(f"  known-RIGHT judged right: {kept}/{len(right)} ({r_rate:.0%})  "
          f"bar {MIN_RIGHT_KEPT:.0%}")
    if w_rate < MIN_WRONG_CAUGHT or r_rate < MIN_RIGHT_KEPT:
        print("\nGATE FAILED -- no verdicts reported from this pass.")
        return 1
    print("  gate PASSED\n")

    print("=" * 78)
    print("STEP 2 -- WHAT EACH ARM'S EXCLUSIVE ANSWERS ARE WORTH")
    print("=" * 78)
    out = {}
    for k in ARMS:
        rows = [(i, key[i], got[i]) for i in sorted(key)
                if key[i]["kind"] == "real" and key[i]["arm"] == k and i in got]
        n_right = sum(1 for _, _, v in rows if _verdict_of(v) == "right")
        other = [a for a in ARMS if a != k][0]
        print(f"  answers ONLY k={k} gives (k={other} declined these): "
              f"{n_right}/{len(rows)} right")
        for _, e, v in rows:
            print(f"      {_verdict_of(v):9s} rank={e.get('grounded_rank')} "
                  f"cos={e['cosine']:.3f}")
        out[f"k{k}_only"] = {"n": len(rows), "right": n_right}

    print()
    print("=" * 78)
    print("STEP 3 -- USEFUL RIGHT ANSWERS DELIVERED, over all 36 situations")
    print("=" * 78)
    paired = _load(ARTIFACTS / "arms_comparison.json")
    for k in ARMS:
        pr = paired["per_arm_right"][str(k)]
        ex = out[f"k{k}_only"]["right"]
        print(f"  k={k}: {pr} right on the {paired['paired']} both arms answered "
              f"+ {ex} right among its own exclusive answers = {pr + ex}")
    print("  A declined situation delivers nothing, so it counts as neither right nor "
          "wrong\n  here -- this is a COVERAGE tally, not an accuracy rate.")
    out["totals"] = {str(k): paired["per_arm_right"][str(k)] + out[f"k{k}_only"]["right"]
                     for k in ARMS}
    (ARTIFACTS / "unpaired_comparison.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    print("-> artifacts/unpaired_comparison.json")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true",
                      help="assemble ONE blind packet holding both arms")
    mode.add_argument("--score", action="store_true",
                      help="recorded facts, then the gate, then the paired comparison")
    mode.add_argument("--build-unpaired", action="store_true",
                      help="one blind packet of the answers only ONE arm gives")
    mode.add_argument("--score-unpaired", action="store_true",
                      help="gate, then what each arm's exclusive answers are worth")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--verdicts", default=str(ARTIFACTS / "arms_verdicts.json"))
    args = ap.parse_args()
    if args.build_unpaired:
        return build_unpaired(args)
    if args.score_unpaired:
        return score_unpaired(args)
    return build(args) if args.build else score(args)


if __name__ == "__main__":
    sys.exit(main())
