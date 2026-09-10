#!/usr/bin/env python3
"""Do the async transports behave against the REAL services? (issues #28, #29)

Run from Brain/, with the Joveo VPN up:

    ../.venv/Scripts/python.exe ../ask-naren/audit/check_async_transport.py

Exits non-zero if either check fails, so it can gate a ship.

WHY THIS IS NOT COVERED BY THE TEST SUITE. `Brain/tests/test_gateway_async.py` and
`test_pinecone_async.py` are network-free by design -- they drive a fake transport and a
fake index, which is what makes them runnable without the VPN and what lets them observe
concurrency precisely. What they cannot do is prove the real gateway accepts what we send
or that the real index answers the same as it does synchronously. Two things here are ONLY
reachable live: HTTP/2 negotiation, and `AsyncTriggerIndex.open()`, which every unit test
bypasses by injecting a fake index.

CHECK 1 (#28) is a before/after, and the "before" is the number
`probe_gateway_concurrency.py` measured: 6 chat + 6 embed with no admission control took
**3 `max_parallel_requests` rejections**. The same 12 calls through `AsyncGatewayClient`
must take **zero**, because the semaphore keeps 6 in flight against a ceiling of 8.

*** IT WATCHES `_backoff`, NOT `_asleep`. *** The first version of this check patched
`_asleep` and reported FAIL on a clean run: `_asleep` is awaited by the rate limiter too,
so the five waits it recorded (0.4/0.9/1.3/1.7/2.1s) were just the embedding quota pacing
calls 2-6 at 60/140 = 0.43s apart -- correct behaviour, counted as rejections. `_backoff`
is only ever reached by a rejected attempt. The client absorbs rejections by design, which
is why 12/12 successes can still hide them and why the ladder has to be watched at all.

CHECK 2 (#29) runs each of the three reads both ways against the live index and compares
field by field. The ranking runs UNFILTERED so no coachable scenario keys are needed and
Postgres is never touched.

Read-only throughout: /chat/completions, /embeddings, /models, and Pinecone query + fetch.
No upsert, no index creation, no database. Keys come from Brain/.env and are never printed.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Brain"))

import numpy as np                              # noqa: E402
from dotenv import load_dotenv                  # noqa: E402

load_dotenv(ROOT / "Brain" / ".env")

from shared import gateway as gw                # noqa: E402
from shared import pinecone_store as ps         # noqa: E402

INDEX = "narens-brain-3072"
TOP_K = 25

#: What the unguarded probe took on this exact workload, 2026-09-10. The whole claim of
#: check 1 is that the same 12 calls now take none.
REJECTIONS_WITHOUT_ADMISSION_CONTROL = 3


async def check_gateway() -> bool:
    print("=" * 78)
    print("CHECK 1 (#28) -- the admission limit, against the real gateway")
    print("=" * 78)
    print(f"bound: {gw.GATEWAY_MAX_PARALLEL} (ceiling measured at 8, shared across "
          f"both endpoints)")

    rejections: list[str] = []
    real_backoff = gw.AsyncGatewayClient._backoff

    def watched_backoff(self, message, attempt, limiter, path):
        rejections.append(f"{path} attempt {attempt + 1}: {message[:120]}")
        return real_backoff(self, message, attempt, limiter, path)

    paced: list[float] = []
    real_sleep = gw._asleep

    async def watched_sleep(seconds):
        paced.append(seconds)
        await real_sleep(seconds)

    gw.AsyncGatewayClient._backoff = watched_backoff
    gw._asleep = watched_sleep
    try:
        async with gw.AsyncGatewayClient() as c:
            models = await c.list_models()
            print(f"  preflight /models: {len(models)} models, http2 requested={c.http2}")

            t0 = time.monotonic()
            results = await asyncio.gather(
                *(c.chat_json(f"Return JSON with key n set to {uuid.uuid4().hex[:8]}.",
                              max_tokens=64, no_cache=True) for _ in range(6)),
                *(c.embed_one(f"probe {uuid.uuid4().hex[:8]} client pricing pushback")
                  for _ in range(6)),
                return_exceptions=True)
            elapsed = time.monotonic() - t0
    finally:
        gw.AsyncGatewayClient._backoff = real_backoff
        gw._asleep = real_sleep

    failed = [r for r in results if isinstance(r, BaseException)]
    print(f"  12 mixed calls (6 chat + 6 embed) in {elapsed:.2f}s")
    print(f"    succeeded: {len(results) - len(failed)}/12   failed: {len(failed)}")
    for f in failed:
        print(f"      -> {type(f).__name__}: {str(f)[:200]}")
    print(f"    gateway rejections (retried attempts): {len(rejections)}")
    for r in rejections:
        print(f"      -> {r}")
    print(f"    quota pacing waits (expected, embeddings only): "
          f"{[round(p, 2) for p in paced]}")

    ok = not failed and not rejections
    print(f"  {'PASS' if ok else 'FAIL'}: 12 concurrent calls, {len(rejections)} rejections "
          f"(unguarded, this workload took {REJECTIONS_WITHOUT_ADMISSION_CONTROL})")
    return ok


def _query_vector() -> list[float]:
    """A fixed pseudo-random unit vector, so both paths ask the identical question. A
    different vector per path would make any disagreement unattributable."""
    rng = np.random.default_rng(20260910)
    v = rng.normal(size=3072).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


async def check_pinecone() -> bool:
    print()
    print("=" * 78)
    print("CHECK 2 (#29) -- the async reads agree with the synchronous ones")
    print("=" * 78)
    api_key = os.environ.get("PINECONE_API_KEY", "")
    if not api_key:
        raise SystemExit("PINECONE_API_KEY is not set in Brain/.env")

    vec = _query_vector()
    ok = True

    sync_rank = ps.query_trigger_vectors(api_key, INDEX, vec, top_k=TOP_K)
    print(f"  sync  ranking: {len(sync_rank)} matches, "
          f"top = {sync_rank[0] if sync_rank else None}")

    # `open()` is the one code path no unit test exercises -- every test injects a fake
    # index -- so reaching this line at all is part of what the check is for.
    async with await ps.AsyncTriggerIndex.open(api_key, INDEX) as idx:
        async_rank = await idx.query_trigger_vectors(vec, top_k=TOP_K)
        print(f"  async ranking: {len(async_rank)} matches, "
              f"top = {async_rank[0] if async_rank else None}")
        if async_rank == sync_rank:
            print("    ranking: IDENTICAL (ids, order and scores)")
        else:
            ok = False
            print("    ranking: DISAGREES")
            for a, b in zip(async_rank, sync_rank):
                if a != b:
                    print(f"      async {a}  vs  sync {b}")

        pair_ids = [rid.removeprefix("trigger_") for rid, _ in sync_rank[:10]]
        record_ids = [f"trigger_{p}" for p in pair_ids]

        sync_present = ps.present_trigger_pair_ids(api_key, INDEX, pair_ids)
        async_present = await idx.present_trigger_pair_ids(pair_ids)
        same = async_present == sync_present
        ok = ok and same
        print(f"    presence ({len(pair_ids)} ids): "
              f"{'IDENTICAL' if same else 'DISAGREES'} -- {len(async_present)} found")
        if not same:
            print(f"      async {async_present}")
            print(f"      sync  {sync_present}")

        sync_fetch = ps.fetch_trigger_ids(api_key, INDEX, record_ids)
        async_fetch = await idx.fetch_trigger_ids(record_ids)
        same = async_fetch == sync_fetch
        ok = ok and same
        print(f"    fetch ({len(record_ids)} ids): "
              f"{'IDENTICAL' if same else 'DISAGREES'} -- {len(async_fetch)} present")

        # Eight simultaneous rankings on one held-open index: the shape a concurrent
        # service actually uses, and what a per-call client could not do cheaply.
        many = await asyncio.gather(*(idx.query_trigger_vectors(vec, top_k=5)
                                      for _ in range(8)))
        consistent = all(m == many[0] for m in many)
        ok = ok and consistent
        print(f"    8 concurrent rankings on one connection: "
              f"{'all agree' if consistent else 'DIVERGED'}")

    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


async def main() -> int:
    gateway_ok = await check_gateway()
    pinecone_ok = await check_pinecone()
    print()
    if gateway_ok and pinecone_ok:
        print("BOTH CHECKS PASS")
        return 0
    print("FAILED: " + ", ".join(
        name for name, good in (("#28 gateway", gateway_ok), ("#29 pinecone", pinecone_ok))
        if not good))
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
