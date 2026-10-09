#!/usr/bin/env python3
"""Do several CSM situations actually overlap on the async path? (issue #30)

Run from Brain/, with the Joveo VPN up:

    ../.venv/Scripts/python.exe ../ask-naren/audit/check_async_concurrency.py

Exits non-zero if the answers did not overlap, so it can gate a ship.

WHY THIS EXISTS SEPARATELY FROM THE TEST SUITE. `tests/test_ask_naren_async_path.py` proves
the overlap against a fake gateway, which is the right place for it -- fast, offline, and
precise about ordering. What it cannot prove is that the overlap survives contact with the
REAL services: the gateway's admission limit, its rate pacing, Pinecone's connection, and
the actual latency shape of a generation. A blocking call anywhere in that stack would make
the offline test pass and this one fail.

WHY IT DRIVES `respond` DIRECTLY RATHER THAN THE HTTP SERVER. It was written while the
server was still the serial stdlib one, to prove the layer BELOW it overlapped.

#31 HAS SINCE LANDED, and `check_concurrent_service.py` is the socket-level check -- it
starts the real service and measures against a single-answer baseline. This one is kept
rather than replaced, because the two fail differently: a blocking call inside `respond`
shows up here immediately and precisely, while the socket check also has to survive
uvicorn's worker model and a subprocess. Run both.

HOW OVERLAP IS MEASURED. Each answer records when it started and finished. If the path
serialised, every interval would be disjoint and end-to-end would be the SUM of them. If it
overlaps, intervals intersect and end-to-end is closer to the SLOWEST one. No baseline run
is needed, so this costs N answers rather than 2N.

COST: N generations (default 3) plus their embeddings, one Postgres read at startup, and a
Pinecone coverage sample. Read-only everywhere -- Postgres is opened through a connection it
refuses to write through and closed before any answering, and Pinecone is only queried.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Brain"))

from ask_naren import responding                       # noqa: E402
# `ops.serve_ask_naren`, NOT a bare `import serve_ask_naren` off a sys.path entry
# pointing at Brain/ops -- that would also make `import clear_data` resolvable, and
# Brain/CLAUDE.md records that IMPORTING that module wipes live data. Same form as
# ops/check_vector_coverage.py uses.
from ops import serve_ask_naren as serve                # noqa: E402

#: Deliberately DIFFERENT situations. Identical prompts would be served from the gateway's
#: completion cache in milliseconds, which would look like spectacular concurrency and
#: measure nothing -- the same trap `probe_gateway_concurrency.py` documents.
SITUATIONS = [
    "client says our cost per hire is way too high",
    "the client wants to pause spend until next quarter",
    "they are asking why our applicant quality dropped this month",
]


async def main() -> int:
    print(f"loading the pool (Postgres read + Pinecone coverage guard)...", flush=True)
    t0 = time.monotonic()
    (pool, moves_by_scenario, playbooks_by_scenario, coachable_scenarios,
     following_by_pair) = await serve.build_pool(serve.DEFAULT_HOSTADDR)
    label_for, account_for = serve.build_label_resolver()
    print(f"pool ready in {time.monotonic() - t0:.1f}s: {len(pool)} pairs\n", flush=True)

    gateway = serve.AsyncGatewayClient()
    embed_query = serve._embed_query(gateway)
    spans: list[tuple[str, float, float, str]] = []

    async def answer(situation: str) -> None:
        started = time.monotonic()
        result = await responding.respond(
            situation, pool, gateway, embed_query=embed_query,
            label_for=label_for, playbook_for=playbooks_by_scenario.get,
            scenarios_for=lambda: coachable_scenarios,
            following_for=lambda pair_id: following_by_pair.get(pair_id, []),
            account_for=account_for)
        spans.append((situation, started, time.monotonic(), result.get("outcome", "?")))

    try:
        wall_start = time.monotonic()
        await asyncio.gather(*(answer(s) for s in SITUATIONS))
        wall = time.monotonic() - wall_start
    finally:
        await gateway.aclose()
        await pool.aclose()          # the pool owns its store; see RetrievalPool.aclose

    spans.sort(key=lambda s: s[1])
    base = spans[0][1]
    durations = [end - start for _, start, end, _ in spans]
    print(f"{len(spans)} situations answered in {wall:.1f}s "
          f"(serialised would be {sum(durations):.1f}s)\n")
    for situation, start, end, outcome in spans:
        # A crude timeline, so an overlap is visible rather than only computed.
        lead = int((start - base) / max(wall, 0.001) * 40)
        span = max(1, int((end - start) / max(wall, 0.001) * 40))
        print(f"  {' ' * lead}{'#' * span}  {end - start:5.1f}s  {outcome:<9} "
              f"{situation[:44]}")

    # Overlap, stated two ways, because either alone can mislead. The interval test is the
    # real one; the wall-clock ratio is what a reader will want to see.
    overlapping = any(spans[i][2] > spans[i + 1][1] for i in range(len(spans) - 1))
    slowest = max(durations)
    print(f"\n  slowest single answer: {slowest:.1f}s")
    print(f"  end to end:            {wall:.1f}s")
    print(f"  sum if serialised:     {sum(durations):.1f}s")

    answered = [s for s in spans if s[3] in ("answered", "declined", "clarify")]
    ok = overlapping and wall < sum(durations) * 0.85 and len(answered) == len(SITUATIONS)
    if ok:
        print(f"\nPASS: the answers overlapped -- end to end is {wall:.1f}s against "
              f"{sum(durations):.1f}s serialised, and every situation got a response.")
        return 0
    print("\nFAIL:")
    if not overlapping:
        print("  no two answers were in flight at the same time -- something in the path "
              "is blocking rather than awaiting.")
    if wall >= sum(durations) * 0.85:
        print(f"  end to end ({wall:.1f}s) is not meaningfully below the serialised sum "
              f"({sum(durations):.1f}s).")
    if len(answered) != len(SITUATIONS):
        print(f"  only {len(answered)} of {len(SITUATIONS)} situations produced a response.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
