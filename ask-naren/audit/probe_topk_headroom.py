#!/usr/bin/env python3
"""Issue #7 follow-up: would showing the model the top-K retrieved moments instead of the
top-1 fix the off-primary failures?

THE PROPOSAL. The blind read found 20/24 answers right, with all 4 wrong ones coming from
retrievals whose PRIMARY scenario differed from the situation's (11/11 right on-primary
against 9/13 off-primary). The natural fix: hand the model several candidates and let it
pick, on the theory that the right moment is in the pool but not at rank 1.

WHAT THIS MEASURES, and why it comes before building anything. The proposal has a testable
premise -- that a right-topic neighbour exists at rank 2..K -- and it costs nothing to check
against the ranking already computed. If a same-primary neighbour is not in the top-K for
the items that failed, top-K prompting cannot fix them and would only add prompt cost and a
new failure mode (the model choosing whichever candidate is easiest to quote).

So: for each sampled situation, where does the FIRST same-primary-scenario neighbour rank,
and what share of a top-K shortlist would be same-primary at all?

CAVEAT THAT LIMITS WHAT THIS CAN CONCLUDE. "Same primary scenario" is the proxy the blind
read validated against human-style judgment, but the situation's own primary label only
exists because these situations are corpus rows. A real CSM types free text with no label,
so nothing at runtime knows the "right" primary -- that is a separate design problem (match
the situation against scenario vectors the way Layer B matches a trigger). This probe
measures HEADROOM, i.e. whether the information is present in the ranking at all. It does
not measure whether a model could exploit it.

Retrieval masks each situation's own call, matching the audit harness. Read-only, no chat
calls; embeddings come off the warm cache.

    python ask-naren/audit/probe_topk_headroom.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "Brain"))

from ask_naren import retrieval             # noqa: E402
from config import load_config              # noqa: E402
from preprocessing import embedder          # noqa: E402
from shared import storage                  # noqa: E402

HOSTADDR = "18.138.49.39"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
KS = (1, 3, 5, 10, 20)


def _connect_read_only(url: str):
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + f"hostaddr={HOSTADDR}"
    conn = storage.get_connection(url)
    conn.execute("SET SESSION default_transaction_read_only = on")
    setting = conn.execute(
        "SELECT current_setting('default_transaction_read_only')").fetchone()[0]
    if setting != "on":
        raise RuntimeError(f"read-only enforcement failed: {setting!r}")
    return conn


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=str(ARTIFACTS / "answer_audit_raw.json"))
    ap.add_argument("--scored", default=str(ARTIFACTS / "answer_audit_scored.json"))
    args = ap.parse_args()

    records = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    scored = json.loads(Path(args.scored).read_text(encoding="utf-8"))
    # Map situation -> blind verdict, so the headroom can be split by what the audit found.
    packet = json.loads((ARTIFACTS / "answer_audit_packet.json").read_text(encoding="utf-8"))
    key = json.loads((ARTIFACTS / "answer_audit_key.json").read_text(encoding="utf-8"))
    verdict_by_situation = {}
    by_id = {p["id"]: p for p in packet}
    kind_by_id = {k["id"]: k["kind"] for k in key}
    for item in scored["items"]:
        if kind_by_id.get(item["id"]) == "real":
            verdict_by_situation[by_id[item["id"]]["situation"]] = item["verdict"]

    conn = _connect_read_only(load_config().database_url)
    try:
        pairs = retrieval.load_coachable_pairs(conn)
    finally:
        conn.close()
    print(f"[pool] {len(pairs)} coachable pairs", flush=True)
    vectors = embedder.embed_query_matrix([p["trigger_text"] for p in pairs])
    pool = retrieval.RetrievalPool(pairs, vectors)
    primaries = np.array([p["scenario_key"] for p in pairs])
    calls = np.array([p["call_filename"] for p in pairs])

    rows = []
    q = embedder.embed_query_matrix([r["situation"] for r in records])
    q = np.asarray(q, dtype=np.float32)
    q /= np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)

    for rec, qv in zip(records, q):

        mask = calls != _own_call(rec, pairs)
        sims = np.where(mask, pool.vectors @ qv, -np.inf)
        order = np.argsort(sims)[::-1]
        want = rec["held_out_scenario"]
        hits = [int(j) for j in order[:max(KS)] if primaries[j] == want]
        first_rank = None
        for n, j in enumerate(order, 1):
            if primaries[j] == want:
                first_rank = n
                break
        rows.append({
            "situation": rec["situation"][:70],
            "held_out_scenario": want,
            "declined": rec["result"]["declined"],
            "verdict": verdict_by_situation.get(rec["situation"]),
            "top1_primary": str(primaries[order[0]]),
            "first_same_primary_rank": first_rank,
            "same_primary_in_topk": {str(k): int(sum(1 for j in order[:k]
                                                     if primaries[j] == want))
                                     for k in KS},
        })

    print("\n" + "=" * 78)
    print("Does a same-primary-scenario neighbour exist in the top-K?")
    print("=" * 78)
    answered = [r for r in rows if not r["declined"]]
    wrong = [r for r in answered if r["verdict"] == "wrong"]
    right = [r for r in answered if r["verdict"] == "right"]

    for label, grp in (("ALL sampled", rows), ("answered", answered),
                       ("judged RIGHT", right), ("judged WRONG", wrong)):
        if not grp:
            continue
        print(f"\n  {label} (n={len(grp)}):")
        for k in KS:
            hit = sum(1 for r in grp if r["same_primary_in_topk"][str(k)] > 0)
            print(f"    a same-primary neighbour is in the top-{k:<2d}: {hit}/{len(grp)} "
                  f"({hit / len(grp):.0%})")
        ranks = [r["first_same_primary_rank"] for r in grp
                 if r["first_same_primary_rank"] is not None]
        if ranks:
            print(f"    rank of the FIRST same-primary neighbour: "
                  f"median={int(np.median(ranks))}  min={min(ranks)}  max={max(ranks)}")

    print("\n" + "=" * 78)
    print("THE FOUR ITEMS THE BLIND READ JUDGED WRONG")
    print("=" * 78)
    for r in wrong:
        print(f"\n  situation: {r['situation']}...")
        print(f"    wanted primary : {r['held_out_scenario']}")
        print(f"    top-1 gave     : {r['top1_primary']}")
        print(f"    first same-primary neighbour is at rank "
              f"{r['first_same_primary_rank']}")
        print(f"    same-primary count in top-5: "
              f"{r['same_primary_in_topk']['5']}/5   top-10: "
              f"{r['same_primary_in_topk']['10']}/10")

    print("\n" + "=" * 78)
    print("READING")
    print("=" * 78)
    if wrong:
        in5 = sum(1 for r in wrong if r["same_primary_in_topk"]["5"] > 0)
        print(f"  {in5}/{len(wrong)} of the wrong answers had a right-topic moment inside")
        print(f"  the top-5. That is the ceiling on what top-K prompting could recover here,")
        print("  and it is a CEILING, not an expected gain: a model handed 5 candidates still")
        print("  has to choose the right one, and the shortlist is mostly off-topic (see the")
        print("  same-primary counts above), so it also gains 4 new chances to pick wrong.")
    OUT = ARTIFACTS / "topk_headroom.json"
    OUT.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {OUT.name}")
    return 0


def _own_call(rec: dict, pairs: list[dict]) -> str:
    """The call the situation came from -- needed for the leave-one-call-out mask. The raw
    record does not carry it, so recover it from the pair whose trigger IS the situation."""
    for p in pairs:
        if p["trigger_text"] == rec["situation"]:
            return p["call_filename"]
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
