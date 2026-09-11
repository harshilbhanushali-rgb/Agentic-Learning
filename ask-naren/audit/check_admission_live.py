#!/usr/bin/env python3
"""Does the RUNNING SERVICE queue, refuse and give up honestly at its bound? (issue #32)

Run from Brain/, with the Joveo VPN up:

    ../.venv/Scripts/python.exe ../ask-naren/audit/check_admission_live.py

Pass `--hostaddr <ip>` when the Neon address the service pins is the unhealthy one -- see
the note on HOSTADDR below, and expect `server closed the connection unexpectedly` during
startup when it bites.

Exits non-zero if the bound did not hold, if a queued caller was refused, if a caller past
the queue depth was not refused promptly, if a busy refusal was indistinguishable from a
fault, if `/ready` did not report saturation, or if an abandoned request kept its slot.

WHY THIS EXISTS ON TOP OF THE OFFLINE TESTS. The offline suite imports nothing from `ops/`,
so it cannot see the service an operator actually starts: a separate process, one event
loop for its whole life, the real answerer, real gateway calls, and the admission gate
wired through `serve_ask_naren.py` rather than constructed by a test. Every layer below can
be correct while the wiring is wrong -- that was exactly the state after #30, with every
offline test passing throughout, and a live check has already caught a defect the whole
suite agreed was fine.

*** THE CHECK SHRINKS THE GATE, AND THAT IS THE ONE DEVIATION FROM THE SHIPPED
CONFIGURATION. *** It starts the service with `BRAIN_GATEWAY_MAX_PARALLEL=2` and a generous
sizing cost, which derives a queue four deep behind two slots rather than eight behind six.
Reaching the shipped refusal means fifteen simultaneous generations, several minutes of
gateway time, and a queue long enough that its own tail becomes a second variable -- so the
run would be expensive AND flaky, and flaky is the worse half. Lowering the KEY's allowance
is also the honest way to do it: it is the same number the gateway team would change, so
nothing here is a special case the shipped path does not take.

WHAT THAT DOES NOT WEAKEN, because it is where the "checks that cannot fail" hazard lives:

  * the expectations are computed HERE, from first principles, and not read back from the
    service. `_depth_from_first_principles` searches for the last queue position that can
    still be ANSWERED inside the deadline, instead of restating
    `admission.queue_depth_within`'s expression, and the service's reported `queue_limit` is
    then asserted AGAINST it. Deriving the expectation from `/ready` would make any wrong
    depth invisible -- the check would simply agree with whatever the service believed.
    THIS IS NOT HYPOTHETICAL: the first version of that function reproduced issue #32's own
    table, which sizes the queue by the WAIT, and this check went on to catch the resulting
    defect anyway -- through `deadlines_missed`, which no offline test can produce because a
    stubbed answerer returns instantly.
  * `peak_in_flight` is asserted EQUAL to the bound, not merely `<=`. An unbounded service
    passes a `<=` assertion trivially.
  * the refusals are asserted to arrive FAST and before the first answer. A 429 that
    arrived after a full deadline would satisfy every count in this file while being the
    precise behaviour the ticket rejects.

NO LATENCY FIGURE IS ASSERTED OR QUOTED. Gateway latency has been observed moving ~6x
between runs, so everything timing-related here is either a generous ceiling (a refusal must
beat the first real answer) or reporting. The measured numbers go to
`artifacts/admission_live.json`, which is what any doc should point at.

Read-only, like every harness here: the service reads Postgres once at startup through a
connection Postgres refuses to write through, and only queries Pinecone. This check sends
one burst plus one abandoned request.
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
PORT = 8792                       # not the default, and not check_concurrent_service's
BASE = f"http://{HOST}:{PORT}"

#: The deviation, in one place. See the module docstring for why the bound is lowered.
#: `BRAIN_GATEWAY_MAX_PARALLEL` is the gateway's own per-key knob, which the service reads
#: rather than copies -- so setting it here exercises the shipped wiring, not a test hook.
GATEWAY_PARALLEL = 2
#: A sizing cost deliberately LARGER than any real answer, which keeps the queue shallow
#: (few requests needed to reach a refusal) and every admitted caller comfortably inside the
#: deadline.
#:
#: *** 60s, AND THE FIRST TWO ATTEMPTS AT THIS NUMBER BOTH FAILED, which is why it is
#: annotated rather than tuned. *** The depth is what the deadline can absorb GIVEN this
#: cost, so if a real answer turns out to cost more than this, the tail of the queue misses
#: the deadline and the run reports `deadlines_missed` -- correct behaviour from the service
#: (that counter exists precisely to say "the sizing cost has drifted") and a useless result
#: from the harness, which was measuring something else. 25s was not enough: a burst on a
#: slow afternoon produced three 504s. Answers have measured between ~1s and ~60s across
#: runs of this file on the same machine, so the sizing cost here sits at the top of the
#: observed range rather than near the middle of it.
ANSWER_COST_S = 60.0
#: RAISED WELL ABOVE THE SHIPPED 30s, and that is safe HERE and nowhere else. It has to be
#: generous for the same reason the sizing cost above is: the queue's tail must clear the
#: deadline on the slowest gateway this file has met, or the run measures gateway latency
#: instead of admission.
#:
#: What makes raising it safe is that this harness talks to the service DIRECTLY. A CSM's
#: request goes through `frontend/src/app/api/ask-naren/route.ts`, which aborts a few seconds
#: after the deadline, so raising the deadline in a deployed service would make the PROXY
#: fire first and relabel a capacity event as a fault. See the note on
#: ANSWER_DEADLINE_SECONDS in Brain/ask_naren/admission.py.
DEADLINE_S = 180.0

#: Distinct questions, so nothing can be served from a cache -- though the service already
#: passes `no_cache=True` on intake and every generation, so this is belt and braces.
SITUATIONS = [
    "client says our cost per hire is way too high",
    "the client wants to pause spend until next quarter",
    "they are asking why our applicant quality dropped this month",
    "the client is threatening to move budget to a competitor",
    "they want a discount because last month underdelivered",
    "the client says our reporting does not match their ATS",
    "they are unhappy that we changed their campaign without telling them",
    "the client asked for a weekly call instead of monthly",
    "they say the candidates we send are not senior enough",
    "the client wants to cut the contract short",
]

#: GENEROUS, because a startup timeout here is not a finding and must not be mistaken for
#: one. Startup is a Postgres read over the VPN plus a Pinecone coverage sample, and it was
#: measured at ~26s and then at over 200s within the same hour on the same machine -- the
#: read is the same size either way, the network is not. 180s produced a "FAIL" that said
#: nothing about admission at all.
STARTUP_TIMEOUT_S = 600

#: A refusal must beat the first real answer by a wide margin -- it does no work at all. A
#: ceiling rather than a measurement, generous enough not to flake on a loaded machine, and
#: still nowhere near the deadline a wrongly-queued refusal would have waited out.
REFUSAL_BUDGET_S = 5.0

#: `/health` must stay prompt while `/ask` is saturated. Orthogonal here in a way it was not
#: in check_concurrent_service.py: there, a busy /ask and a busy /health were the same
#: condition, and its docstring notes this check stops discriminating once #32 bounds them
#: separately. It now asserts something different -- that the bound on answers did not leak
#: into liveness, so an ingress does not restart the process precisely when it is busiest.
HEALTH_BUDGET_S = 2.0

#: PASSED THROUGH TO THE SERVICE, because the pinned Neon IP can be the sick one.
#:
#: The local resolver refuses `*.neon.tech`, so `ops/serve_ask_naren.py` pins an address and
#: keeps the hostname in the URL for SNI/SCRAM. That address is ONE OF SEVERAL the host
#: resolves to, and when the pinned one is unhealthy the read fails mid-flight with
#: `consuming input failed: server closed the connection unexpectedly` -- the connection
#: opens, then dies partway through the pool load. Measured 2026-09-11: the pinned default
#: failed twice in a row while a sibling address loaded the pool in one go.
#:
#: A harness that cannot be pointed at a different address turns that into an unexplainable
#: startup failure, which is the worst kind of result here -- it looks like a finding and is
#: not one. Empty means "use the service's own default".
#:
#:     ../.venv/Scripts/python.exe <this file> --hostaddr 13.251.17.193
#:
#: Get the current set with:
#:     Resolve-DnsName -Name <the pooler host> -Type A -Server 8.8.8.8
HOSTADDR = None


#: The service's output goes to a FILE, never to a pipe nobody drains -- an earlier harness
#: filled the pipe buffer and the service BLOCKED on write, which looked exactly like the
#: defect it was hunting.
LOG = Path(tempfile.gettempdir()) / "ask_naren_check_admission_live.log"
ARTIFACT = Path(__file__).resolve().parent / "artifacts" / "admission_live.json"


def _depth_from_first_principles(deadline: float, cost: float, limit: int) -> int:
    """The last queue position that can still be ANSWERED inside the deadline.

    A SEARCH, not the production expression rewritten. Restating
    `admission.queue_depth_within`'s arithmetic here would assert only that the same
    expression gives the same answer twice. This walks positions outward from zero asking
    the question the deadline actually poses -- "would the person at this position have
    their answer in hand before the budget runs out?" -- so it agrees with the shipped code
    only if the shipped code means what the deadline means.

    NOTE THE `+ cost`, which is the whole point and which an earlier version of this
    function omitted, faithfully reproducing the ticket's table and the defect with it. A
    caller is not served when their slot frees; they are served when their own answer
    finishes. The two differ by exactly one round of answers, and every caller inside that
    gap was admitted and then killed by the deadline they were admitted under.
    """
    depth = 0
    while (depth + 1) * cost / limit + cost <= deadline:
        depth += 1
    return depth


def _start_service():
    handle = LOG.open("w", encoding="utf-8")
    env = dict(os.environ)
    env["BRAIN_GATEWAY_MAX_PARALLEL"] = str(GATEWAY_PARALLEL)
    env["ASK_NAREN_ANSWER_COST_SECONDS"] = str(ANSWER_COST_S)
    env["ASK_NAREN_DEADLINE_SECONDS"] = str(DEADLINE_S)
    # NEW PROCESS GROUP so an interrupt can be delivered to the child alone, as in
    # check_concurrent_service.py.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    argv = [sys.executable, "ops/serve_ask_naren.py", "--host", HOST, "--port", str(PORT)]
    if HOSTADDR:
        argv += ["--hostaddr", HOSTADDR]
    proc = subprocess.Popen(
        argv,
        cwd=str(BRAIN), stdout=handle, stderr=subprocess.STDOUT, text=True,
        env=env, creationflags=flags)
    return proc, handle


def _stop_service(proc) -> None:
    if os.name == "nt":
        with contextlib.suppress(Exception):
            proc.send_signal(signal.CTRL_BREAK_EVENT)
    else:                                       # pragma: no cover -- not this machine
        proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


async def _await_ready(proc) -> dict | None:
    """Poll until the port answers, and return what `/ready` first reported.

    A CLOSED PORT DURING STARTUP IS CORRECT: the pool is still loading, and
    connection-refused is what every ingress reads as "not yet".
    """
    started_at = time.monotonic()
    async with httpx.AsyncClient(timeout=5.0) as c:
        while time.monotonic() - started_at < STARTUP_TIMEOUT_S:
            if proc.poll() is not None:
                print(f"  service exited during startup (code {proc.returncode}) "
                      f"-- see {LOG}")
                return None
            try:
                if (await c.get(f"{BASE}/health")).status_code == 200:
                    ready = await c.get(f"{BASE}/ready")
                    print(f"  listening after {time.monotonic() - started_at:.1f}s")
                    return ready.json()
            except httpx.TransportError:
                pass
            waited = time.monotonic() - started_at
            if waited > 45 and int(waited) % 30 < 1:
                print(f"  still starting after {waited:.0f}s (Postgres read over the "
                      f"VPN) ...", flush=True)
            await asyncio.sleep(0.5)
    print(f"  the service never opened its port within {STARTUP_TIMEOUT_S}s. THIS SAYS "
          f"NOTHING ABOUT ADMISSION -- it is startup: the VPN, the Postgres read or the "
          f"Pinecone coverage sample. See {LOG}.")
    return None


async def _ask_then_hang_up(situation: str, started_answering: asyncio.Event) -> float:
    """Send a real question over a raw socket, hang up as soon as it is being answered,
    and return the moment the socket closed.

    A raw connection rather than httpx, because an HTTP client will not let go of a request
    it has sent: it is the FIN on the socket that makes ASGI deliver `http.disconnect`, and
    that is the only signal the service has that a CSM closed the tab.

    IT HANGS UP THE INSTANT THE ANSWER STARTS, on the caller's signal, rather than after a
    fixed hold. A fixed hold went into the measurement: the first version reported ~2s for a
    release that was actually immediate, and would have reported the same ~2s for one that
    was not.
    """
    _, writer = await asyncio.open_connection(HOST, PORT)
    payload = json.dumps({"situation": situation}).encode()
    writer.write(b"POST /ask HTTP/1.1\r\nHost: " + HOST.encode()
                 + b"\r\nContent-Type: application/json\r\nContent-Length: "
                 + str(len(payload)).encode() + b"\r\n\r\n" + payload)
    await writer.drain()
    await asyncio.wait_for(started_answering.wait(), timeout=30)
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    return time.monotonic()


async def main() -> int:
    limit = GATEWAY_PARALLEL
    depth = _depth_from_first_principles(DEADLINE_S, ANSWER_COST_S, limit)
    sent = limit + depth + 2
    expect_refused = sent - (limit + depth)
    assert sent <= len(SITUATIONS), "not enough distinct situations for this burst"

    print(f"starting ops/serve_ask_naren.py on {BASE}")
    print(f"  DEVIATION FROM SHIPPED: BRAIN_GATEWAY_MAX_PARALLEL={limit}, "
          f"sizing cost {ANSWER_COST_S:.0f}s, deadline {DEADLINE_S:.0f}s")
    print(f"  so: {limit} answered at once, {depth} queued behind them, and a "
          f"{sent}-request burst must refuse exactly {expect_refused}", flush=True)

    proc, log_handle = _start_service()
    # All bound BEFORE the try, because the artifact is written after the `finally` and a
    # failure part-way through must produce a readable record rather than a NameError on
    # top of the real problem.
    results: list[dict] = []
    health_ms: list[float] = []
    saturated_seen: list[dict] = []
    failures: list[str] = []
    wall = 0.0
    released_in: float | None = None
    final: dict = {}
    try:
        ready = await _await_ready(proc)
        if ready is None:
            return 1

        # -- the service's own derivation, against ours ---------------------------------
        print(f"\nwhat the service reports at /ready: in_flight_limit="
              f"{ready.get('in_flight_limit')}  queue_limit={ready.get('queue_limit')}  "
              f"deadline={ready.get('deadline_seconds')}s", flush=True)
        if ready.get("in_flight_limit") != limit:
            failures.append(
                f"the service bounds answers at {ready.get('in_flight_limit')}, not at the "
                f"gateway's {limit} -- the bound is not reading the key's allowance")
        if ready.get("queue_limit") != depth:
            failures.append(
                f"the service queues {ready.get('queue_limit')} behind its slots; the last "
                f"position that fits a {DEADLINE_S:.0f}s deadline is {depth}")
        if ready.get("deadline_seconds") != DEADLINE_S:
            failures.append(
                f"the service's deadline is {ready.get('deadline_seconds')}s, not the "
                f"{DEADLINE_S:.0f}s it was started with")

        async with httpx.AsyncClient(
                timeout=DEADLINE_S + 30,
                limits=httpx.Limits(max_connections=sent + 8)) as c:

            async def ask(situation: str) -> dict:
                started = time.monotonic()
                r = await c.post(f"{BASE}/ask", json={"situation": situation})
                body = {}
                with contextlib.suppress(ValueError):
                    body = r.json()
                return {"situation": situation, "status": r.status_code,
                        "seconds": time.monotonic() - started,
                        "outcome": body.get("outcome", "?"),
                        "reason": body.get("reason"),
                        "retry_after_seconds": body.get("retry_after_seconds"),
                        "retry_after_header": r.headers.get("retry-after"),
                        "message": body.get("message", "")}

            async def watch() -> None:
                """Poll /health and /ready throughout, recording saturation when it
                appears. `/health` must stay prompt: the bound on ANSWERS must not leak
                into liveness, or an ingress restarts the process exactly when it is
                busiest."""
                while True:
                    t0 = time.monotonic()
                    h = await c.get(f"{BASE}/health", timeout=10.0)
                    health_ms.append((time.monotonic() - t0) * 1000)
                    if h.status_code != 200:
                        raise AssertionError(f"/health returned {h.status_code}")
                    r = await c.get(f"{BASE}/ready", timeout=10.0)
                    if r.json().get("status") == "saturated":
                        # `http_status`, NOT `status`: the body carries its own `status`
                        # key ("saturated") and splatting it over an HTTP status silently
                        # replaced 503 with a string. The first run of this check failed on
                        # a perfectly correct service because of it.
                        saturated_seen.append({"http_status": r.status_code, **r.json()})
                    await asyncio.sleep(0.25)

            print(f"\nphase 1: {sent} questions at once, against {limit} slots and a "
                  f"{depth}-deep queue ...", flush=True)
            watcher = asyncio.create_task(watch())
            wall_start = time.monotonic()
            results = await asyncio.gather(*(ask(s) for s in SITUATIONS[:sent]))
            wall = time.monotonic() - wall_start
            watcher.cancel()
            # AWAITED, not merely cancelled: a bare cancel leaves an AssertionError from a
            # non-200 /health unretrieved, where it surfaces as a GC warning and never
            # touches the exit code.
            #
            # AND THE AssertionError BECOMES A FAILURE RATHER THAN BEING RAISED. Letting it
            # propagate skips the artifact write below, so the one condition this poller
            # exists to catch would produce a traceback and no record -- a check that
            # reports its own most interesting result worst. Found by review.
            try:
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher
            except AssertionError as e:
                failures.append(f"while /ask was saturated: {e}")

            for r in sorted(results, key=lambda r: r["seconds"]):
                note = (f"retry in {r['retry_after_seconds']}s"
                        if r["retry_after_seconds"] else r["outcome"])
                print(f"  {r['seconds']:6.1f}s  {r['status']}  {note:<18} "
                      f"{r['situation'][:44]}", flush=True)

            refused = [r for r in results if r["status"] == 429]
            served = [r for r in results if r["status"] == 200]
            other = [r for r in results if r["status"] not in (200, 429)]

            after_burst = (await c.get(f"{BASE}/ready")).json()
            print(f"\n  after the burst: peak_in_flight="
                  f"{after_burst.get('peak_in_flight')}  peak_queued="
                  f"{after_burst.get('peak_queued')}  "
                  f"admitted={after_burst.get('admitted')}  "
                  f"refused={after_burst.get('refused')}"
                  f"  deadlines_missed={after_burst.get('deadlines_missed')}", flush=True)

            # -- the counter an operator reads, against what actually came back ---------
            #
            # An INDEPENDENT cross-check rather than a restatement: `admitted` is counted
            # inside the gate, `len(served)` is counted from HTTP statuses on this side of
            # the socket. They agree only if the gate is counting the same events the
            # callers experienced. It is also the denominator that makes `refused` mean
            # anything -- a refusal count with no admissions beside it cannot say whether
            # this API key's allowance is still enough, which is the criterion.
            if after_burst.get("admitted") != len(served):
                failures.append(
                    f"the gate says it admitted {after_burst.get('admitted')} while "
                    f"{len(served)} requests came back answered")

            # -- the bound held, EXACTLY. `<=` would pass for an unbounded service. -----
            if after_burst.get("peak_in_flight") != limit:
                failures.append(
                    f"{after_burst.get('peak_in_flight')} answers were in flight at once "
                    f"against a bound of {limit}")
            if after_burst.get("peak_queued") != depth:
                failures.append(
                    f"the queue peaked at {after_burst.get('peak_queued')}, not at the "
                    f"{depth} the deadline can absorb")

            # -- exactly the callers past the depth were refused, and nobody else -------
            if len(refused) != expect_refused:
                failures.append(
                    f"{len(refused)} of {sent} were refused; {sent} requests against "
                    f"{limit} slots and a {depth}-deep queue must refuse exactly "
                    f"{expect_refused}")
            if len(served) != limit + depth:
                failures.append(
                    f"{len(served)} were answered; the {limit} in flight plus the {depth} "
                    f"queued behind them should all have been served")
            if other:
                failures.append(
                    f"{len(other)} request(s) came back {sorted({r['status'] for r in other})}"
                    f" -- neither answered nor refused")

            # -- a queued caller was SERVED, which is the default path ------------------
            if len(served) <= limit:
                failures.append(
                    "nobody was queued and then served -- the queue either refused or was "
                    "never reached, and queueing is the path almost every caller takes")

            # -- the refusal is a busy refusal, distinguishable from a fault ------------
            for r in refused:
                if r["reason"] != "service_busy":
                    failures.append(f"a refusal carried reason {r['reason']!r}, which a CSM "
                                    f"cannot tell from a no-match or a fault")
                if not r["retry_after_seconds"]:
                    failures.append("a busy refusal carried no estimate of how long")
                if r["retry_after_header"] != str(r["retry_after_seconds"]):
                    failures.append(
                        f"Retry-After said {r['retry_after_header']!r} while the body said "
                        f"{r['retry_after_seconds']!r}")
                if r["retry_after_seconds"] and str(r["retry_after_seconds"]) \
                        not in r["message"]:
                    failures.append("the sentence a CSM reads does not name the estimate")
                if r["seconds"] > REFUSAL_BUDGET_S:
                    failures.append(
                        f"a refusal took {r['seconds']:.1f}s -- it was queued before being "
                        f"refused, which is the behaviour the ticket rejects")

            # -- and it was refused BEFORE the first answer came back -------------------
            if refused and served and max(r["seconds"] for r in refused) \
                    >= min(r["seconds"] for r in served):
                failures.append(
                    "a refusal arrived no sooner than the fastest answer -- refusing is "
                    "supposed to cost nothing")

            # -- nobody admitted was failed later --------------------------------------
            if after_burst.get("deadlines_missed"):
                failures.append(
                    f"{after_burst['deadlines_missed']} admitted request(s) missed the "
                    f"deadline -- the depth is admitting people it cannot serve")

            # -- /ready said saturated, and /health stayed prompt ----------------------
            if not saturated_seen:
                failures.append(
                    "/ready never reported saturation, so there is still no state it can "
                    "report for a process that cannot take more work")
            elif saturated_seen[0]["http_status"] != 503:
                failures.append(f"/ready reported saturation as HTTP "
                                f"{saturated_seen[0]['http_status']}, not 503")
            worst_health = max(health_ms) if health_ms else float("inf")
            if worst_health > HEALTH_BUDGET_S * 1000:
                failures.append(
                    f"/health took {worst_health:.0f}ms while /ask was saturated -- the "
                    f"bound on answers leaked into liveness")
            print(f"  /health: {len(health_ms)} polls, worst {worst_health:.0f}ms   "
                  f"/ready reported saturated {len(saturated_seen)} time(s)", flush=True)

            # -- phase 2: a caller who hangs up -----------------------------------------
            #
            # *** MEASURED AGAINST THE SAME QUESTION ANSWERED NORMALLY, and a fixed
            # deadline will not do. *** The obvious form -- "the slot must come back within
            # 20 seconds" -- passes against a service that does not cancel at all whenever
            # the gateway is quick: the answer simply finishes on its own inside the window
            # and hands the slot back, and nothing was proven. Observed across two runs of
            # this very check: the same eight situations took 9-13s each and then 2.6-4.4s
            # each, a ~4x swing, so ANY constant is either flaky or vacuous depending on
            # the day.
            #
            # So the baseline is the identical situation, asked alone, on this run's
            # gateway: the release must beat HALF of the time that answer actually took.
            # Cancelling releases the slot immediately (the teardown awaits nothing);
            # failing to cancel releases it only when the answer completes, which is by
            # construction most of that duration away. The service passes `no_cache=True`
            # on intake and every generation, so asking the same thing twice pays full
            # price both times and the two halves are comparable -- the same reasoning
            # check_concurrent_service.py records for why it re-asks its own situations.
            probe = SITUATIONS[0]
            print(f"\nphase 2: the same question answered normally, then abandoned "
                  f"mid-answer ...", flush=True)
            solo = await ask(probe)
            print(f"  answered alone in {solo['seconds']:.1f}s  ({solo['status']} "
                  f"{solo['outcome']})", flush=True)
            if solo["status"] != 200:
                failures.append(f"the abandonment baseline came back {solo['status']}, so "
                                f"there is nothing to compare a release against")

            before = (await c.get(f"{BASE}/ready")).json()["in_flight"]
            started_answering = asyncio.Event()
            abandon = asyncio.create_task(_ask_then_hang_up(probe, started_answering))
            watch_until = time.monotonic() + 30
            while time.monotonic() < watch_until:
                if (await c.get(f"{BASE}/ready")).json()["in_flight"] > before:
                    started_answering.set()
                    break
                await asyncio.sleep(0.05)
            if not started_answering.is_set():
                failures.append("the abandoned question never reached the answerer, so "
                                "nothing was proven about releasing its slot")
                abandon.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await abandon
            else:
                closed_at = await abandon
                give_up = time.monotonic() + DEADLINE_S + 10
                while time.monotonic() < give_up:
                    if (await c.get(f"{BASE}/ready")).json()["in_flight"] <= before:
                        released_in = time.monotonic() - closed_at
                        break
                    await asyncio.sleep(0.05)
                must_beat = solo["seconds"] * 0.5
                if released_in is None:
                    failures.append(
                        "the slot was never given back after the caller hung up -- an "
                        "abandoned request keeps consuming capacity, so a colleague waits "
                        "behind an answer nobody will read")
                else:
                    print(f"  slot came back {released_in:.1f}s after the socket closed "
                          f"(must beat {must_beat:.1f}s, half of the {solo['seconds']:.1f}s "
                          f"that answer took)", flush=True)
                    if released_in >= must_beat:
                        failures.append(
                            f"the slot came back {released_in:.1f}s after the caller hung "
                            f"up, against the {solo['seconds']:.1f}s that same answer "
                            f"takes -- consistent with the answer simply running to "
                            f"completion rather than being cancelled")

            final = (await c.get(f"{BASE}/ready")).json()

    finally:
        print("\nstopping the service ...", flush=True)
        _stop_service(proc)
        log_handle.close()

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps({
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "issue": 32,
        "deviation_from_shipped": {
            "BRAIN_GATEWAY_MAX_PARALLEL": GATEWAY_PARALLEL,
            "ASK_NAREN_ANSWER_COST_SECONDS": ANSWER_COST_S,
            "ASK_NAREN_DEADLINE_SECONDS": DEADLINE_S,
            "why": "reaching the shipped depth of 8 behind 6 slots costs 15 simultaneous "
                   "generations, several minutes of gateway time, and a queue long enough "
                   "that its own tail becomes a second variable",
        },
        "expected": {"in_flight_limit": limit, "queue_limit": depth,
                     "sent": sent, "refused": expect_refused},
        "burst_wall_seconds": wall,
        "requests": results,
        "health_ms": {"polls": len(health_ms),
                      "worst": max(health_ms) if health_ms else None,
                      "median": (sorted(health_ms)[len(health_ms) // 2]
                                 if health_ms else None)},
        "saturated_reports": len(saturated_seen),
        "abandoned_slot_released_seconds": released_in,
        "ready_at_end": final,
        "failures": failures,
    }, indent=2), encoding="utf-8")
    print(f"\nmeasurement written to {ARTIFACT.relative_to(ROOT)}")

    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  - {f}")
        print(f"\n  service log: {LOG}")
        return 1
    print(f"\nPASS: {limit} answered at once, {depth} queued and served, "
          f"{expect_refused} refused promptly as busy with an estimate, /ready reported "
          f"saturation, and an abandoned request gave its slot back")
    return 0


if __name__ == "__main__":
    # One flag, parsed by hand: argparse for a single optional string would be more code
    # than it saves, and this harness takes no other input.
    if "--hostaddr" in sys.argv:
        HOSTADDR = sys.argv[sys.argv.index("--hostaddr") + 1]
    sys.exit(asyncio.run(main()))
