#!/usr/bin/env python3
"""Does the RUNNING SERVICE answer several CSMs at once? (issue #31)

Run from Brain/, with the Joveo VPN up:

    ../.venv/Scripts/python.exe ../ask-naren/audit/check_concurrent_service.py

Exits non-zero if the requests did not overlap, or if /health queued behind an answer.

WHY THIS EXISTS ON TOP OF EVERYTHING ELSE. Three checks each prove a different layer:

    tests/test_ask_naren_service.py      the ASGI app does not block the loop, vs a stub
    check_async_concurrency.py           `respond` overlaps, against the real gateway
    THIS                                 the real PROCESS overlaps, over real SOCKETS

Only the last exercises what a CSM actually hits: a separate process, uvicorn's HTTP
parsing and worker model, and the connection pool. The layers below can all be correct
while the server still serialises -- that was exactly the state after #30, with every
offline test passing throughout. It does NOT go through the Next.js proxy; nothing here
tests that.

It launches `ops/serve_ask_naren.py` as a SUBPROCESS rather than importing it, because "the
thing an operator starts" is what is being checked. Startup costs a Postgres read and a
Pinecone coverage sample, so expect ~20s before the first request.

*** HOW OVERLAP IS MEASURED, AND WHY NOT THE OBVIOUS WAY. ***

The first version of this harness recorded each request's start and end CLIENT-SIDE and
asserted that the intervals intersect and that end-to-end came in under 85% of their sum.
Both checks are worthless over a socket, and a review proved it arithmetically:
`asyncio.gather` dispatches N requests at once, so every recorded start is ~0 and the
intervals ALWAYS intersect -- even on a strictly serial server. Worse, the client-measured
durations then become d, 2d, 3d..., because the queueing happens inside the span the client
can see; their sum is d*N*(N+1)/2 against a wall of N*d, so `wall < 0.85 * sum` reduces to
`N > 1.35` and is true for every N >= 2. It would have printed "PASS: answered 3 CSMs at
once (36.0s against 72.0s serialised)" for a server answering them one after another.

The second version measured against a baseline: ONE situation answered alone, then N
together. That can fail, but it also fails when nothing is wrong -- the baseline situation
routed to `clarify` (5.8s, no generation at all) while the concurrent three were
generations (12-19s), so a perfectly concurrent server was reported as serialising. Ask
Naren's intents differ in cost by ~6x, so any baseline drawn from a DIFFERENT question is
comparing two workloads.

So this runs THE SAME THREE SITUATIONS TWICE: once strictly one at a time, then once all
together. Same questions, same intents, same generations -- the only variable is whether
they overlap. The gateway's completion cache cannot flatter the second run, because the
service passes `no_cache=True` on every generation and on intake. Six answers, and the
comparison means exactly what it says.

TWO THINGS IT ASSERTS, and they fail independently -- which is the point of keeping both:

  1. The same N situations cost MUCH less together than one at a time.
  2. `/health` answers PROMPTLY WHILE answers are in flight. It used to queue behind them,
     so an ingress with a normal timeout marked a healthy process dead during every
     generation, then flapped and killed it. This is the sharper of the two signals today
     -- 75 polls at a 0ms median during three 12s answers is something a serial server
     cannot fake -- and it is also the one that stops discriminating once issue #32 bounds
     `/ask` separately from `/health`. Do not delete assertion 1 on the grounds that 2 is
     better.

Read-only: the service reads Postgres once at startup through a connection Postgres refuses
to write through, and only queries Pinecone. This harness sends 2N questions.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
BRAIN = ROOT / "Brain"

HOST = "127.0.0.1"
PORT = 8791                       # not the default, so this cannot fight a service already up
BASE = f"http://{HOST}:{PORT}"

#: Deliberately DIFFERENT questions from each other, so the concurrent run cannot be
#: served from the gateway's completion cache. They are asked TWICE -- once sequentially,
#: once together -- and that is safe because the service passes `no_cache=True` on every
#: generation and on intake, so the second run pays full price too.
SITUATIONS = [
    "client says our cost per hire is way too high",
    "the client wants to pause spend until next quarter",
    "they are asking why our applicant quality dropped this month",
]

STARTUP_TIMEOUT_S = 180

#: A generation takes ~12.5s, so a health check must answer in a tiny fraction of that or it
#: is queueing. Generous enough not to flake on a loaded machine.
HEALTH_BUDGET_S = 2.0

#: The concurrent run must come in under this multiple of the LONGEST answer measured
#: alone -- not under a fraction of their sum.
#:
#: The sum form nearly failed a healthy run: answers vary hugely by intent, and when one
#: situation generates for 14s while the others decline in 3s, the concurrent wall is
#: necessarily ~14s (it cannot beat its slowest member) against a 25s sum -- a ratio of
#: only 1.7x that sat right on a 0.6 budget. Perfect overlap means `wall == max(solo)`, so
#: that is what to measure against; serialisation means `wall == sum(solo)`, which for any
#: realistic spread is far above this multiple.
CONCURRENT_BUDGET = 1.6

#: The service's own output goes to a FILE, not to a pipe.
#:
#: An earlier version used `stdout=subprocess.PIPE` and never read it. With uvicorn's access
#: log on, the buffer filled and the service BLOCKED on write -- requests timed out and it
#: looked exactly like the serialisation this check exists to disprove. The access log is
#: off now (see `service.serve`), but a log nobody drains is still a deadlock waiting to
#: happen. Temp dir rather than audit/artifacts/, which is tracked.
LOG = Path(tempfile.gettempdir()) / "ask_naren_check_concurrent_service.log"

#: The MEASUREMENT, however, is written into the repo like every other harness here.
#:
#: Not housekeeping. The numbers this produces vary a lot run to run -- the same three
#: situations have measured anywhere from 1.4s to 14.7s each, because generation length and
#: gateway latency both move -- so any figure quoted in a docstring is stale the next day
#: and cannot be checked against anything. The docs therefore describe the PROPERTY and
#: point here; this file is where the last measured numbers actually live.
ARTIFACT = Path(__file__).resolve().parent / "artifacts" / "concurrent_service.json"


def _start_service():
    handle = LOG.open("w", encoding="utf-8")
    # NEW PROCESS GROUP so an interrupt can be delivered to the child alone. Without it,
    # CTRL_BREAK_EVENT on Windows goes to this harness too, and there is no other way to
    # reach the child's signal handlers -- `terminate()` is TerminateProcess, a hard kill
    # that runs no shutdown at all, which is why the graceful path went unverified at first.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(
        [sys.executable, "ops/serve_ask_naren.py", "--host", HOST, "--port", str(PORT)],
        cwd=str(BRAIN), stdout=handle, stderr=subprocess.STDOUT, text=True,
        creationflags=flags)
    return proc, handle


def _interrupt(proc) -> None:
    """Ask the service to stop the way an operator does, not with a hard kill."""
    if os.name == "nt":
        proc.send_signal(signal.CTRL_BREAK_EVENT)
    else:                                       # pragma: no cover -- not this machine
        proc.send_signal(signal.SIGINT)


def _check_graceful_shutdown(proc, handle) -> bool:
    """Interrupt the service and confirm it tore its own resources down.

    WHY THIS IS WORTH THE EXTRA 15 SECONDS. A review found that the teardown did not run on
    interrupt at all: `asyncio.run` installs a SIGINT handler that cancels the main task,
    uvicorn re-raises the signal into it, and the caller's `finally` was therefore already
    cancelled when it reached `await gateway.aclose()`. The httpx client and the Pinecone
    session leaked, and the process exited 130 with a traceback. The fix moved the teardown
    into the ASGI lifespan shutdown, which uvicorn runs BEFORE any of that.

    *** NOT ENFORCEABLE ON WINDOWS, AND THAT IS THE PLATFORM RATHER THAN THE SERVICE. ***
    Measured here: uvicorn does register a SIGBREAK handler, but under asyncio's proactor
    loop the Python-level handler does not get to run before the OS terminates the process
    (exit 3, no shutdown line). There is no way to deliver a real Ctrl-C to a specific child
    from a parent on Windows -- CTRL_C_EVENT ignores the process group. So on Windows this
    REPORTS what it saw and does not gate; on a POSIX host, where SIGINT arrives properly,
    it gates.

    What covers the mechanism regardless of platform is
    `tests/test_ask_naren_service.py::test_a_real_uvicorn_run_invokes_the_lifespan_shutdown`,
    which runs a real uvicorn, serves a request, stops it on the same graceful path a signal
    triggers, and asserts the teardown ran.
    """
    _interrupt(proc)
    try:
        code = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        print("  the service did not stop on an interrupt -- hard-killing it")
        proc.kill()
        return False if os.name != "nt" else True
    handle.flush()
    log = LOG.read_text(encoding="utf-8", errors="replace")
    shut_down = "[ask-naren] shutting down" in log
    leaked = "Unclosed" in log
    crashed = "Traceback (most recent call last)" in log
    print(f"  exit code {code}   graceful line: {shut_down}   "
          f"unclosed-session warning: {leaked}   traceback: {crashed}")
    if os.name == "nt" and not shut_down:
        print("  NOT GATED on Windows: the OS killed the process before its signal handler "
              "ran, which is a platform limit. The teardown mechanism is covered by "
              "test_a_real_uvicorn_run_invokes_the_lifespan_shutdown.")
        # A leak or a traceback would still be real signals if they appeared.
        return not leaked and not crashed
    return shut_down and not leaked and not crashed


async def _await_ready(proc) -> bool:
    """Poll until the port answers.

    A CLOSED PORT DURING STARTUP IS CORRECT, not a failure: the pool is still loading and
    there is nothing to answer with, and connection-refused is what every ingress already
    reads as "not yet". `/ready` is for the states the process can report once it is
    already listening.
    """
    started_at = time.monotonic()
    async with httpx.AsyncClient(timeout=5.0) as c:
        while time.monotonic() - started_at < STARTUP_TIMEOUT_S:
            if proc.poll() is not None:
                print(f"  service exited during startup (code {proc.returncode}) "
                      f"-- see {LOG}")
                return False
            try:
                if (await c.get(f"{BASE}/health")).status_code == 200:
                    ready = await c.get(f"{BASE}/ready")
                    print(f"  listening after {time.monotonic() - started_at:.1f}s   "
                          f"/ready -> {ready.status_code} {ready.json()}")
                    return True
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.5)
    print(f"  timed out waiting for the service to listen -- see {LOG}")
    return False


async def main() -> int:
    print(f"starting ops/serve_ask_naren.py on {BASE} ...", flush=True)
    proc, log_handle = _start_service()
    try:
        if not await _await_ready(proc):
            return 1

        health_ms: list[float] = []

        async with httpx.AsyncClient(timeout=180.0) as c:

            async def ask(situation: str):
                started = time.monotonic()
                r = await c.post(f"{BASE}/ask", json={"situation": situation})
                return (started, time.monotonic(), r.status_code,
                        r.json().get("outcome", "?"))

            # -- phase 1: the same situations, strictly ONE AT A TIME ------------------
            print(f"\nphase 1: {len(SITUATIONS)} situations, one at a time ...", flush=True)
            sequential = []
            for situation in SITUATIONS:
                start, end, status, outcome = await ask(situation)
                sequential.append((end - start, status, outcome))
                print(f"  {end - start:5.1f}s  {status} {outcome:<9} {situation[:40]}",
                      flush=True)
            serial_total = sum(d for d, _, _ in sequential)
            serial_slowest = max(d for d, _, _ in sequential)
            if any(status != 200 for _, status, _ in sequential):
                print(f"  a sequential request failed -- see {LOG}")
                return 1
            print(f"  sequential total: {serial_total:.1f}s   "
                  f"(slowest alone: {serial_slowest:.1f}s)")

            async def poll_health() -> None:
                while True:
                    t0 = time.monotonic()
                    r = await c.get(f"{BASE}/health")
                    health_ms.append((time.monotonic() - t0) * 1000)
                    if r.status_code != 200:
                        raise AssertionError(f"/health returned {r.status_code}")
                    await asyncio.sleep(0.25)

            print(f"\nphase 2: the SAME {len(SITUATIONS)} situations at once, polling "
                  f"/health throughout ...", flush=True)
            watcher = asyncio.create_task(poll_health())
            wall_start = time.monotonic()
            results = await asyncio.gather(*(ask(s) for s in SITUATIONS))
            wall = time.monotonic() - wall_start
            watcher.cancel()
            # AWAITED, not merely cancelled. A bare cancel leaves an AssertionError from a
            # non-200 /health unretrieved: it surfaces as a GC warning, never touches the
            # exit code, and the run could print PASS with /health returning 503.
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

        spans = sorted(zip(SITUATIONS, results), key=lambda sr: sr[1][0])
        base_t = spans[0][1][0]
        durations = [end - start for _, (start, end, _, _) in spans]
        print(f"\n{len(spans)} answers together in {wall:.1f}s\n")
        for situation, (start, end, status, outcome) in spans:
            lead = int((start - base_t) / max(wall, 0.001) * 40)
            span = max(1, int((end - start) / max(wall, 0.001) * 40))
            print(f"  {' ' * lead}{'#' * span}  {end - start:5.1f}s  {status} "
                  f"{outcome:<9} {situation[:40]}")

        allowed = serial_slowest * CONCURRENT_BUDGET
        slowest = max(durations)
        all_ok = all(status == 200 for _, (_, _, status, _) in spans)
        worst_health = max(health_ms) if health_ms else float("inf")
        median_health = (sorted(health_ms)[len(health_ms) // 2] if health_ms
                         else float("nan"))

        speedup = serial_total / max(wall, 0.001)
        # A speedup above N is not better-than-perfect concurrency -- it is arithmetically
        # impossible for N requests. It means the two phases met different gateway latency
        # (one solo answer measured 16.3s while the concurrent three were ~2.8s each). The
        # RATIO is therefore reporting, not a benchmark; the gate is `wall` against the
        # slowest solo answer, and /health is the signal that does not move.
        noisy = speedup > len(SITUATIONS) * 1.2
        print(f"\n  one at a time:  {serial_total:5.1f}s   "
              f"(slowest alone {serial_slowest:.1f}s)")
        print(f"  all together:   {wall:5.1f}s   "
              f"({speedup:.1f}x faster; must beat {allowed:.1f}s, "
              f"i.e. {CONCURRENT_BUDGET}x the slowest single answer)")
        print(f"  slowest single: {slowest:5.1f}s")
        print(f"  /health polls:  {len(health_ms)}, worst {worst_health:.0f}ms, "
              f"median {median_health:.0f}ms")
        if noisy:
            print(f"  NOTE: {speedup:.1f}x exceeds the {len(SITUATIONS)}x that "
                  f"{len(SITUATIONS)} requests can possibly gain, so the two phases met "
                  f"different gateway latency. The overlap is real -- do not quote the "
                  f"ratio as a benchmark.")

        print("\ninterrupting the service, to check it closes what it opened ...",
              flush=True)
        shutdown_ok = _check_graceful_shutdown(proc, log_handle)
        # On Windows the interrupt cannot be delivered before the OS kills the process, so
        # the check reports rather than gates. Tracked separately so the PASS line does not
        # claim a verification that was skipped.
        shutdown_gated = os.name != "nt"

        ok = (all_ok and wall < allowed and worst_health < HEALTH_BUDGET_S * 1000
              and shutdown_ok)

        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps({
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "situations": len(SITUATIONS),
            "sequential_total_s": round(serial_total, 2),
            "sequential_slowest_s": round(serial_slowest, 2),
            "concurrent_wall_s": round(wall, 2),
            "speedup_vs_sequential": round(speedup, 2),
            "budget_s": round(allowed, 2),
            "concurrent_budget_multiple_of_slowest": CONCURRENT_BUDGET,
            "per_answer": [
                {"situation": sit, "seconds": round(end - start, 2),
                 "status": status, "outcome": outcome}
                for sit, (start, end, status, outcome) in spans],
            "health_polls": len(health_ms),
            "health_worst_ms": round(worst_health, 1),
            "health_median_ms": round(median_health, 1),
            "shutdown_gated": shutdown_gated,
            "shutdown_clean": shutdown_ok,
            "speedup_is_noisy": noisy,
            "passed": ok,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\n  -> {ARTIFACT}")
        # What the PASS line may claim about shutdown depends on whether it was GATED.
        shutdown_note = ("and it closed its client and index on an interrupt"
                         if shutdown_gated else
                         "(clean shutdown NOT verified here -- see the note above)")
        if ok:
            print(f"\nPASS: the same {len(SITUATIONS)} situations took {wall:.1f}s together "
                  f"against {serial_total:.1f}s one at a time ({speedup:.1f}x, and within "
                  f"{CONCURRENT_BUDGET}x the {serial_slowest:.1f}s slowest single answer), "
                  f"/health never took more than {worst_health:.0f}ms while they were in "
                  f"flight, {shutdown_note}.")
            return 0
        print("\nFAIL:")
        if not all_ok:
            print(f"  not every request returned 200: "
                  f"{[st for _, (_, _, st, _) in spans]}")
        if wall >= allowed:
            print(f"  together ({wall:.1f}s) is not close to the slowest single answer "
                  f"({serial_slowest:.1f}s) -- the answers queued rather than overlapped.")
        if worst_health >= HEALTH_BUDGET_S * 1000:
            print(f"  /health took {worst_health:.0f}ms -- it is queueing behind answers, "
                  f"which is what makes an ingress kill a healthy process.")
        if not shutdown_ok:
            print("  the service did not shut down cleanly -- it leaked a client session, "
                  "crashed, or never reached its teardown.")
        print(f"  service log: {LOG}")
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:       # pragma: no cover
            proc.kill()
        log_handle.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
