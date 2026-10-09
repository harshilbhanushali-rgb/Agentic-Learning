#!/usr/bin/env python3
"""Does ranking in Pinecone return the SAME kb_pairs as ranking in memory? (ADR 0008)

Run from Brain/:

    ../.venv/Scripts/python.exe ../ask-naren/audit/equivalence_vector_store.py

THE ONE MEASUREMENT ADR 0008 RESTS ON. Moving every vector operation into Pinecone is only
safe because the stored vectors are the same vectors the service used to embed at startup
(spot-checked at cos = 1.000000 on 24/24 pairs). This turns that spot check into a real
comparison: for each situation, rank the whole coachable pool BOTH ways and compare.

PINECONE'S QUERY IS APPROXIMATE, AND THAT IS THE POINT OF MEASURING RATHER THAN ASSERTING.
The stored values are exact -- a fetched vector has norm 1.00000 and reproduces
cos = 1.00000000 against itself. But querying the index with a stored unit vector returns
its OWN record at scores from 0.999321 to 1.00135, and a score above 1 cannot be a cosine,
so the scores come from a quantized ANN representation. The error is ~1.5e-3 and it is
inherent to a serverless vector index, not a defect to fix.

Bars:
  * BLOCKING: the top-ranked kb_pair is identical for 100% of situations.
  * BLOCKING: cosines agree to within 5e-3. Justified against the decision the number
    feeds, not picked for tightness: nothing thresholds on cosine (ADR 0005 measured and
    rejected every floor), and the measured gap between right and wrong answers is 0.016 --
    an order of magnitude larger than this error. An earlier 1e-5 bar was used here and was
    wrong: it was never implied by the cos = 1.000000 spot check, which only bounds the
    angle to ~1e-3.
  * REPORTED, not blocking: identical top-5 ordering. Ranks 2..k reorder among near-ties,
    and the shipped candidate selection is 1 (ADR 0005), so nothing consumes that order.

The number that actually quantifies the risk is the rank-1 MARGIN: how often the gap
between the best and second-best cosine is smaller than the approximation error, because
that is when the approximation could pick a different exchange. Reported below.

Situations come from the existing audit artifacts -- 36 from the answer audit and 11 from
the held-out intake set -- rather than being invented here, so this measures the same text
the quality numbers were measured on.

READ-ONLY throughout. Postgres is read through a connection it refuses to write through and
closed before ranking; Pinecone is only queried. Needs the VPN: it embeds the pool for the
in-memory arm (~60s off a warm cache) and each situation once.

Exit 0 when both bars pass, 1 otherwise.
"""
from __future__ import annotations

import json
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "Brain"))

import numpy as np                                       # noqa: E402

from ask_naren import retrieval, vector_store            # noqa: E402
from config import load_config                           # noqa: E402
from ops.serve_ask_naren import (DEFAULT_HOSTADDR,       # noqa: E402
                                 VECTOR_INDEX_NAME, _connect_read_only)
from preprocessing import embedder                       # noqa: E402

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
K = 5
COSINE_BAR = 5e-3
# The measured ANN error, from querying the index with its own stored vectors.
ANN_ERROR = 1.5e-3


def load_situations() -> list[tuple[str, str]]:
    """(source, text) for every real situation the audits already use."""
    out: list[tuple[str, str]] = []
    raw = ARTIFACTS / "answer_audit_raw.json"
    if raw.exists():
        for row in json.loads(raw.read_text(encoding="utf-8")):
            text = (row.get("situation") or "").strip()
            if text:
                out.append(("answer_audit", text))
    heldout = ARTIFACTS / "intake_accuracy_heldout_post_threads.json"
    if heldout.exists():
        for row in json.loads(heldout.read_text(encoding="utf-8")):
            text = (row.get("message") or "").strip()
            if text:
                out.append(("intake_heldout", text))
    return out


async def main() -> int:
    situations = load_situations()
    if not situations:
        print("ERROR: no situations found in audit artifacts.")
        return 1
    print(f"[situations] {len(situations)} real situations "
          f"({len({s for s, _ in situations})} sources)")

    config = load_config()
    conn = _connect_read_only(config.database_url, DEFAULT_HOSTADDR)
    try:
        pairs = retrieval.load_coachable_pairs(conn)
    finally:
        conn.close()
    scenario_keys = sorted({p["scenario_key"] for p in pairs})
    print(f"[pool] {len(pairs)} coachable kb_pairs, {len(scenario_keys)} scenarios")

    print(f"[memory arm] embedding {len(pairs)} triggers...", flush=True)
    t0 = time.time()
    vectors = embedder.embed_query_matrix([p["trigger_text"] for p in pairs])
    print(f"[memory arm] ready in {time.time() - t0:.1f}s")
    memory_pool = retrieval.RetrievalPool(pairs, vectors)

    pinecone_store_ = await vector_store.PineconeTriggerStore.open(
        config.pinecone_api_key, VECTOR_INDEX_NAME, scenario_keys=scenario_keys)
    pinecone_pool = retrieval.RetrievalPool(pairs, store=pinecone_store_)
    print(f"[pinecone arm] {VECTOR_INDEX_NAME}, no vectors held")

    print(f"[queries] embedding {len(situations)} situations...", flush=True)
    query_vecs = embedder.embed_query_matrix([text for _, text in situations])

    rows = []
    margins: list[float] = []
    top1_agree = 0
    shortlist_agree = 0
    deltas: list[float] = []
    pinecone_ms: list[float] = []
    memory_ms: list[float] = []

    for (source, text), qv in zip(situations, query_vecs):
        t0 = time.time()
        mem = await memory_pool.topk(np.asarray(qv), K)
        memory_ms.append((time.time() - t0) * 1000)
        t0 = time.time()
        pine = await pinecone_pool.topk(np.asarray(qv), K)
        pinecone_ms.append((time.time() - t0) * 1000)

        mem_ids = [m.pair["pair_id"] for m in mem]
        pine_ids = [m.pair["pair_id"] for m in pine]
        same_top1 = bool(mem_ids and pine_ids and str(mem_ids[0]) == str(pine_ids[0]))
        same_list = [str(i) for i in mem_ids] == [str(i) for i in pine_ids]
        top1_agree += int(same_top1)
        shortlist_agree += int(same_list)

        # Cosine comparison only where the two arms named the same pair at the same rank;
        # comparing a cosine across DIFFERENT pairs would measure the disagreement twice.
        for m, p in zip(mem, pine):
            if str(m.pair["pair_id"]) == str(p.pair["pair_id"]):
                deltas.append(abs(m.cosine - p.cosine))

        # The rank-1 margin in the EXACT arm: how much better the winner was than the
        # runner-up. Smaller than ANN_ERROR means the approximation could have picked the
        # other one, which is the only way this change can alter a shipped (k=1) answer.
        if len(mem) >= 2:
            margins.append(mem[0].cosine - mem[1].cosine)

        rows.append({"source": source, "situation": text[:120],
                     "memory_top5": [str(i) for i in mem_ids],
                     "pinecone_top5": [str(i) for i in pine_ids],
                     "same_top1": same_top1, "same_shortlist": same_list,
                     "memory_cosines": [round(m.cosine, 6) for m in mem],
                     "pinecone_cosines": [round(p.cosine, 6) for p in pine]})
        if not same_top1:
            print(f"  MISMATCH [{source}] {text[:70]!r}")
            print(f"    memory  : {mem_ids} {[round(m.cosine, 4) for m in mem]}")
            print(f"    pinecone: {pine_ids} {[round(p.cosine, 4) for p in pine]}")

    n = len(situations)
    d = np.array(deltas) if deltas else np.array([0.0])
    print()
    print("=" * 68)
    print("EQUIVALENCE: ranking in Pinecone vs ranking in memory")
    print("=" * 68)
    print(f"  situations                     {n}")
    print(f"  same top-ranked kb_pair        {top1_agree}/{n}  "
          f"({100.0 * top1_agree / n:.1f}%)")
    print(f"  identical top-{K} shortlist      {shortlist_agree}/{n}  "
          f"({100.0 * shortlist_agree / n:.1f}%)")
    print(f"  cosine |delta| on shared ranks max={d.max():.2e} mean={d.mean():.2e} "
          f"(n={len(deltas)})")
    print(f"  latency per situation          memory {np.median(memory_ms):.1f}ms  "
          f"pinecone {np.median(pinecone_ms):.0f}ms (median)")
    m = np.array(margins) if margins else np.array([1.0])
    tight = int((m < ANN_ERROR).sum())
    print()
    print(f"  rank-1 margin (exact arm)      p50={np.median(m):.4f} p10={np.percentile(m, 10):.4f} "
          f"min={m.min():.5f}")
    print(f"  margin BELOW the {ANN_ERROR:.1e} ANN error  {tight}/{len(m)} situations "
          f"({100.0 * tight / len(m):.1f}%)  <-- where top-1 could flip")

    out = ARTIFACTS / "equivalence_vector_store.json"
    out.write_text(json.dumps({
        "index": VECTOR_INDEX_NAME, "k": K, "situations": n,
        "same_top1": top1_agree, "same_shortlist": shortlist_agree,
        "cosine_delta_max": float(d.max()), "cosine_delta_mean": float(d.mean()),
        "margin_p50": float(np.median(m)), "margin_min": float(m.min()),
        "margins_below_ann_error": tight, "ann_error": ANN_ERROR,
        "memory_ms_median": float(np.median(memory_ms)),
        "pinecone_ms_median": float(np.median(pinecone_ms)),
        "rows": rows}, indent=2), encoding="utf-8")
    print(f"  -> artifacts/{out.name}")

    passed = top1_agree == n and float(d.max()) <= COSINE_BAR
    print()
    print("PASS: Pinecone ranks identically to the in-memory search."
          if passed else
          f"FAIL: top-1 {top1_agree}/{n}, max cosine delta {d.max():.2e} "
          f"(bar {COSINE_BAR:.0e}).")
    # The pool owns its store (RetrievalPool.aclose); an open Pinecone session
    # outlives the useful part of this run and warns on exit.
    await pinecone_pool.aclose()
    return 0 if passed else 1


if __name__ == "__main__":
    # ONE loop for the process (issue #30), the same rule ops/serve_ask_naren.py follows.
    sys.exit(asyncio.run(main()))
