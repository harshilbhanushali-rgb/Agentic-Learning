"""Ask Naren's HTTP boundary: one endpoint, plus liveness and readiness.

A RAW ASGI APPLICATION ON UVICORN, AND STILL NO WEB FRAMEWORK (issue #31).

ADR 0003 gave two reasons for the stdlib `http.server`. The first -- the embedder's disk
cache holds a thread-bound SQLite connection -- is gone: issue #30 routed the request path
around that cache entirely, so the object that raises is never constructed.

The second, quoted VERBATIM because half of it is now overridden and the halves must not
be blurred together:

    "There is nothing here a framework would do. One JSON POST and one health GET. Adding
     `fastapi` and `uvicorn` to Brain's venv to route two paths is cost without benefit."

The `fastapi` half still holds and is honoured: there is no framework here. The
application is a plain `async def app(scope, receive, send)` doing its own routing in about
as many lines as a decorator table would take. The `uvicorn` half is OVERRIDDEN,
deliberately -- that dependency is what buys concurrency, and the ADR was weighing it
against routing two paths rather than against answering more than one CSM at a time. It is
a server, not a framework, and it is the only new dependency.

The response shapes, the 503 fault, the malformed-thread 400 and the decline-is-200 rule
are byte-identical to the stdlib version, pinned by a test file whose contract assertions
are unchanged. Four things DID move, all accidental improvements, all now pinned by their
own tests so they cannot silently revert: a query string no longer defeats path matching
(the stdlib handler matched `self.path`, which includes the `?...` part); an unsupported
method is a JSON 404 rather than the stdlib's HTML 501; and a body with no Content-Length
is now read and size-capped by what actually arrives rather than rejected as empty.

WHAT CHANGED FOR A CSM: ABOUT SIX OF THEM ARE ANSWERED AT ONCE, and the rest wait in a
bounded queue rather than being accepted and left to contend. Requests overlap while they
wait on the gateway, which is where essentially all of an answer goes.

*** SIX IS THE CEILING AND IT IS NOT OURS TO RAISE. *** It is the gateway's 8 requests in
flight per API KEY -- shared across chat and embeddings -- operated at 6 so a retry has
somewhere to go. Because that budget belongs to the key rather than the process, running a
second process does not double capacity; it violates one budget twice while looking healthy.
So the process count is part of the correctness argument, which is the whole subject of
ask-naren/docs/adr/0010-ask-naren-answers-concurrently-in-one-asyncio-process.md.

Behind those six, issue #32's `ask_naren/admission.py` holds a queue as deep as the request
deadline can absorb, refuses anyone past it immediately with an estimate rather than late
with nothing, and enforces the deadline on whoever it admits.

NO LATENCY FIGURE IS QUOTED HERE, deliberately: an answer's cost has been observed moving by
several times between runs, so any number written into this docstring is stale within a day
and checkable against nothing. The harnesses in ask-naren/audit/ measure it and write the
result to that directory's artifacts/ -- check_concurrent_service.py for overlap,
check_admission_live.py for the bound, the queue and the deadline.

WHAT CHANGED FOR AN OPERATOR: `/health` no longer queues behind an in-flight generation.
That was not cosmetic -- with a normal ingress health-check timeout it marked a healthy
process dead during EVERY answer, then flapped and killed it, which is why this service
could not be deployed behind a load balancer at all, even for one user.

KEEP-ALIVE IS ALLOWED AGAIN, and the `Connection: close` header is gone. ADR 0003 forced it
because keep-alive on a SERIAL server is a self-inflicted outage: the accept loop blocked in
`handle_one_request` on an idle socket and the next CSM's question waited on a connection
nobody was using (measured -- one lingering client made every subsequent request time out).
That failure mode is a property of serialisation and disappeared with it; an idle connection
now occupies no worker, while a fresh handshake per question is pure cost. The test that
caught the original defect still runs, with the same assertion and a new reason.

IT NOW DECIDES WHO IS ANSWERED, WHICH IS A DELIBERATE ADDITION AND NOT A DRIFT (issue #32).
The bound the async chain removed had to be put back: the real ceiling is the gateway's 8
requests in flight per API key, operated at 6, so accepting thirty simultaneous questions
means thirty people contending for six slots and everyone waiting about a minute -- WORSE
for the people at the front than the serial server was. So `/ask` takes a slot from
`ask_naren/admission.py`, waits for one if they are all busy (the default path, and what
almost every caller does), and refuses on arrival only when the queue is already as deep as
the deadline can absorb. The arithmetic is there; the statuses, reason codes and CSM-facing
sentences are here, because this is the layer that writes what a CSM reads.

A request also has a DEADLINE now, measured from arrival so it covers the wait as well as
the work, and an ABANDONED request is cancelled -- a CSM closing the tab releases their slot
or leaves the queue instead of making a colleague wait behind an answer nobody will read.
That last one is only expressible because of #30/#31: the threaded design had no way to
notice a vanished caller and no way to stop the work.

WHAT THIS LAYER STILL DOES NOT DO: no reshaping. Whatever the answerer decided is what the
caller reads -- retrieval, grounding and model-calling all live in one place, and it is not
here. Admission is not an exception to that: it decides WHETHER the answerer runs, never
what it says.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import traceback
from typing import Awaitable, Callable

from ask_naren import admission, threads

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

# A body big enough for any real situation and small enough that a runaway client cannot
# make the service read itself out of memory. Enforced WHILE the body streams in, not after
# it has all arrived -- see `_read_body`.
MAX_BODY_BYTES = 64 * 1024

# *** THREE WAYS OF SAYING NO, AND THEY MUST STAY DISTINGUISHABLE (issue #32). ***
#
# A capacity problem wearing a quality problem's clothes is the main hazard here: if "too
# many questions right now" arrived as a no-close-match, the tool would look like it was
# working perfectly and simply declining a lot, and the decline rate calibration reads
# would be measuring load. So each one differs in THREE places at once -- the HTTP status an
# operator watches, the reason code an engineer greps, and the sentence a CSM reads:
#
#   service_error       503  something broke on our side            -> tell someone
#   service_busy        429  too many questions right now           -> ask again in a moment
#   deadline_exceeded   504  this one ran out of time               -> ask again
#   (no_close_match)    200  nothing in Naren's calls is close      -> rephrase, or accept
#
# The first three are all `outcome: declined` in the body, which is the shape the fault
# already used: the frontend then needs no new render path, and its reason->copy table is
# exhaustive over the union, so a new reason is a BUILD failure rather than a busy response
# quietly rendering as "no grounded answer".
SERVICE_ERROR = "service_error"
_SERVICE_ERROR_MESSAGE = (
    "Ask Naren could not reach its knowledge base just now. Nothing was answered -- this "
    "is a fault on our side, not a 'no close match'. Try again in a moment."
)

SERVICE_BUSY = "service_busy"
_SERVICE_BUSY_MESSAGE = (
    "Ask Naren is answering as many people as it can right now, and could not get to this "
    "one in time to be useful. Nothing is wrong with your question and nothing is broken "
    "-- ask again in about {seconds} seconds."
)

DEADLINE_EXCEEDED = "deadline_exceeded"
_DEADLINE_MESSAGE = (
    "Ask Naren did not finish this one in time, and stopped rather than leave you waiting "
    "on a spinner. Nothing you typed caused it -- ask again."
)

_JSON = [(b"content-type", b"application/json; charset=utf-8")]


#: The answerer takes the situation AND the thread it arrived in (issue #15), and is AWAITED
#: (issue #30). Still ONE callable -- the layer did not grow a second entry point for a
#: multi-turn request, because a thread is not a different kind of question, it is context
#: on the same one.
Answerer = Callable[[str, tuple], Awaitable[dict]]

#: Whether the service can answer yet. Separate from liveness on purpose: a process that is
#: up but not able to answer is not a dead one, and an ingress that cannot tell the
#: difference will kill something that is merely starting.
ReadyCheck = Callable[[], bool]


def build_app(answerer: Answerer, *, ready: ReadyCheck | None = None,
              on_shutdown: "Callable[[], Awaitable[None]] | None" = None,
              gate: "admission.Admission | None" = None):
    """The ASGI application. `ready` defaults to always-ready.

    Returns a callable rather than an object because that is the whole ASGI contract.

    IT NOW HOLDS ONE PIECE OF STATE, and the previous version of this docstring said it held
    none -- `gate` counts what is in flight and what is queued (issue #32), which is
    unavoidable: a bound is by definition something remembered between requests. It is
    still not state about any PARTICULAR request, and nothing a CSM asked is retained.

    `gate` defaults to a fresh `Admission` built from the shipped numbers. A test passes its
    own to make the bound small enough to reach.

    `on_shutdown` IS AWAITED FROM THE LIFESPAN, and that is load-bearing rather than
    stylistic. See `_lifespan` for the Ctrl-C failure it exists to avoid.
    """
    is_ready = ready if ready is not None else (lambda: True)
    gate = gate if gate is not None else admission.Admission()

    async def app(scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            await _lifespan(receive, send, on_shutdown)
            return
        if scope["type"] != "http":            # pragma: no cover -- uvicorn sends no other
            return

        path = scope["path"].rstrip("/") or "/"
        method = scope["method"]

        if method == "GET" and path == "/health":
            # LIVENESS. Awaits nothing, so it cannot queue behind an answer no matter how
            # many are in flight. Deliberately says nothing about readiness: an ingress
            # restarting a busy-but-healthy process is the failure this endpoint exists to
            # prevent, not to cause.
            return await _send(send, 200, {"status": "ok"})

        if method == "GET" and path == "/ready":
            # READINESS, AND NOW SATURATION (issue #32). Note what already covers the
            # startup window: during the Postgres read and the coverage guard the port is
            # not open at all, so a check gets connection-refused, which every ingress
            # reads as "not yet". This endpoint is for a state the process can report WHILE
            # listening, and until #32 there was no such state, so it always said ready.
            #
            # "Saturated" is that state: alive, healthy, answering as many as it can, and
            # unable to take another without breaking the deadline. Note it is NOT "every
            # slot busy" -- a busy slot means someone is being answered, which is the
            # service working. It is the QUEUE behind them being as deep as the deadline
            # can absorb.
            #
            # The counts ride along on all three answers, because the peaks and the refusal
            # count are how an operator tells whether we have outgrown this API key's
            # allowance -- and an instantaneous reading taken at a quiet moment says
            # nothing, since the interesting moment is never the one anybody is watching.
            if not is_ready():
                return await _send(send, 503, {"status": "starting", **gate.snapshot()})
            if gate.saturated:
                return await _send(send, 503, {"status": "saturated", **gate.snapshot()})
            return await _send(send, 200, {"status": "ready", **gate.snapshot()})

        if method == "POST" and path == "/ask":
            return await _ask(answerer, receive, send, gate)

        await _send(send, 404, {"error": "not found"})

    return app


async def serve(answerer: Answerer, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                ready: ReadyCheck | None = None,
                on_shutdown: "Callable[[], Awaitable[None]] | None" = None,
                gate: "admission.Admission | None" = None) -> None:
    """Serve until interrupted. AWAITED, because uvicorn owns the event loop.

    `uvicorn` is imported here rather than at module scope so the whole test suite -- and
    `--ask` -- can use this module without it installed. It is a server, needed only to
    serve.

    THE SOCKET IS BOUND BEFORE ANYTHING IS ANNOUNCED. The first version printed the banner
    and then called `serve()`, so an occupied port printed "listening on ..." and then
    failed, and `port=0` printed a literal `:0`. Binding first means the message names the
    port that is actually accepting, and a bind failure is reported instead of contradicted.

    ACCESS LOGGING IS OFF, restoring a decision the stdlib handler made explicitly -- it
    overrode `log_message` to silence the per-request stderr log, because faults are
    reported by the traceback and that is the part worth reading. Leaving it on also made
    the service hang for any caller that started it with a stdout pipe it did not drain,
    and an ingress polling /health is one line per second forever.
    """
    import uvicorn

    gate = gate if gate is not None else admission.Admission()
    config = uvicorn.Config(
        build_app(answerer, ready=ready, on_shutdown=on_shutdown, gate=gate),
        host=host, port=port, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    sock = config.bind_socket()
    bound_host, bound_port = sock.getsockname()[:2]
    print(f"[ask-naren] listening on http://{bound_host}:{bound_port}  "
          f"POST /ask  GET /health  GET /ready", flush=True)
    # ANNOUNCED, because these are the numbers that decide who gets refused and an operator
    # should not have to read the source to learn them -- particularly the depth, which is
    # derived and therefore changes when either of the other two does. `/ready` reports the
    # same set live.
    print(f"[ask-naren] answering {gate.in_flight_limit} at once, queueing up to "
          f"{gate.queue_limit} behind them, {gate.deadline:.0f}s deadline per question",
          flush=True)
    try:
        await server.serve(sockets=[sock])
    finally:
        print("[ask-naren] shutting down", flush=True)


async def _lifespan(receive, send, on_shutdown=None) -> None:
    """Answer uvicorn's startup/shutdown handshake, and run the caller's teardown.

    STARTUP does nothing: the pool, the gateway client and the store are loaded by
    `ops/serve_ask_naren.py` BEFORE the server starts. Moving that in here would turn the
    coverage guard's refuse-to-serve decision into a lifespan failure, which is a worse
    place to report it from.

    *** SHUTDOWN IS WHERE THE TEARDOWN HAS TO HAPPEN, AND A `finally` AROUND `serve()` IS
    NOT ENOUGH. *** Measured on Ctrl-C: `asyncio.run` installs a SIGINT handler that
    cancels the main task, and uvicorn's `capture_signals` restores the previous handler
    and re-raises the signal into it -- so the caller's task is already cancelled by the
    time its `finally` runs, and the first `await gateway.aclose()` there raises
    CancelledError immediately. The client and the Pinecone session leak, the process exits
    130 with a KeyboardInterrupt traceback, and a comment promising cleanup is simply
    false. The old stdlib server could not show this: it caught KeyboardInterrupt itself
    and its cleanup was synchronous.

    Uvicorn runs this handshake as part of its GRACEFUL shutdown, before any of that -- so
    teardown awaited here completes normally.
    """
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            if on_shutdown is not None:
                await on_shutdown()
            await send({"type": "lifespan.shutdown.complete"})
            return


async def _ask(answerer: Answerer, receive, send, gate: "admission.Admission") -> None:
    """One question, under a bound and a deadline, and abandonable (issue #32).

    THE ORDER OF THE THREE THINGS HERE IS THE DESIGN:

      1. The body is read and validated FIRST. A malformed request is a 400 that costs no
         slot -- it would be perverse to queue someone behind a request that was never
         going to be answered, and worse to refuse them as "busy" because of it.

      2. The disconnect watcher starts BEFORE the slot is taken, not after. That ordering is
         the whole of the abandonment criterion: the expensive case is a CSM who closed the
         tab while still QUEUED, and a watcher started after admission would not notice them
         until they were already being answered. Started here, they simply leave the queue
         and the colleague behind them moves up.

      3. Admission and the answer run inside ONE deadline that starts at arrival, so the
         budget covers the wait as well as the work. A deadline measured from admission
         would be a promise about the part we control instead of about what a CSM
         experiences, and the queue depth is derived from the whole-request figure.
    """
    try:
        situation, thread = await _read_request(receive)
    except ValueError as e:
        return await _send(send, 400, {"error": str(e)})

    # `asyncio.wait` rather than `gather`: we need to know WHICH of the two finished, and
    # the loser must be cancelled and awaited rather than left to surface later as an
    # unretrieved-task warning.
    abandoned = asyncio.create_task(_wait_for_disconnect(receive))
    work = asyncio.create_task(_admit_and_answer(answerer, situation, thread, gate))
    done, _ = await asyncio.wait({work, abandoned}, return_when=asyncio.FIRST_COMPLETED)

    if work not in done:
        # THE CALLER IS GONE. Cancelling is what releases the slot or drops us out of the
        # queue -- `Admission.slot`'s teardown is await-free precisely so it completes
        # inside a cancellation. Nothing is sent: there is no socket left to send on, and
        # uvicorn already knows the connection is dead.
        work.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await work
        return

    abandoned.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await abandoned
    status, payload, headers = work.result()
    await _send(send, status, payload, headers)


async def _admit_and_answer(answerer: Answerer, situation: str, thread: tuple,
                            gate: "admission.Admission") -> "tuple[int, dict, list]":
    """Take a slot, answer, and return what to send -- or say why not.

    Returns rather than sends, so the caller can drop the whole thing on the floor if the
    CSM has left. Every exit is one of the four documented statuses; nothing here escapes
    as an exception, because the layer above has a socket to answer and a CSM who must
    never see a traceback.
    """
    # The deadline object is bound so `expired()` can be asked afterwards. A `TimeoutError`
    # is NOT proof that our budget ran out -- anything underneath us may raise one, and in
    # 3.11 `asyncio.TimeoutError` IS the builtin `TimeoutError`, an `OSError`. Treating
    # every TimeoutError as ours would report a gateway socket timeout as "we ran out of
    # time": a fault mislabelled as a capacity event, which is exactly the conflation this
    # ticket exists to prevent, one layer further down.
    budget = asyncio.timeout(gate.deadline)
    try:
        async with budget:
            try:
                async with gate.slot():
                    return 200, await answerer(situation, thread), []
            except admission.Busy as busy:
                # REFUSED ON ARRIVAL, having waited for nothing. 429 and not 503: a busy
                # lunchtime must not look like an outage to whatever counts 5xx, and
                # `Retry-After` carries the same estimate as the prose for anything reading
                # headers rather than sentences.
                print(f"[ask-naren] busy: refused a question with {gate.queued} queued "
                      f"and {gate.in_flight} in flight ({gate.refused} refused so far)",
                      file=sys.stderr, flush=True)
                return (429,
                        {"outcome": "declined", "reason": SERVICE_BUSY,
                         "message": _SERVICE_BUSY_MESSAGE.format(
                             seconds=busy.retry_after_seconds),
                         "retry_after_seconds": busy.retry_after_seconds},
                        [(b"retry-after", str(busy.retry_after_seconds).encode())])
    except TimeoutError:
        if budget.expired():
            # The only timeout before this was the gateway's 120s, and no CSM waits 120s.
            # Counted, because a rising number here means the cost estimate the depth is
            # sized from has drifted, and the depth is now admitting people it cannot serve.
            gate.note_deadline_missed()
            print(f"[ask-naren] deadline: gave up after {gate.deadline:.0f}s "
                  f"({gate.deadlines_missed} so far)", file=sys.stderr, flush=True)
            return 504, {"outcome": "declined", "reason": DEADLINE_EXCEEDED,
                         "message": _DEADLINE_MESSAGE}, []
        return _fault()
    except Exception:                     # noqa: BLE001 -- a CSM must never see a traceback
        return _fault()


def _fault() -> "tuple[int, dict, list]":
    """Logged in full, reported generically: the message could name internal hosts, and it
    is not something a CSM can act on. The 503 is what tells an operator this was a fault
    rather than a decline."""
    traceback.print_exc(file=sys.stderr)
    return 503, {"outcome": "declined", "reason": SERVICE_ERROR,
                 "message": _SERVICE_ERROR_MESSAGE}, []


async def _wait_for_disconnect(receive) -> None:
    """Return once the client has gone.

    ASGI reports a vanished caller by handing `http.disconnect` to the next `receive()`, so
    noticing means having a `receive()` outstanding -- which is why this is a task of its
    own rather than a check somewhere. Calling `receive()` again after the body is complete
    is safe, and is what Starlette's `is_disconnected` does: a keep-alive connection's NEXT
    request cannot arrive as an event on this one, because HTTP/1.1 will not begin it until
    this response is finished.
    """
    while True:
        if (await receive())["type"] == "http.disconnect":
            return


async def _read_request(receive) -> tuple[str, tuple]:
    """The situation, and the thread it arrived in (issue #15).

    `thread` is OPTIONAL and absent means an empty thread -- every caller written before
    threads existed keeps working unchanged, including `--ask`.

    A thread that is PRESENT and malformed is a 400, not an ignored field. It means our own
    frontend and this service disagree about the shape, and answering the message anyway
    would read every follow-up as a brand new question while looking perfectly healthy. See
    `threads.parse`.
    """
    raw = await _read_body(receive)
    if not raw:
        raise ValueError("empty request body")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("body must be JSON") from None
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    situation = body.get("situation")
    if not isinstance(situation, str) or not situation.strip():
        raise ValueError("'situation' must be a non-empty string")
    return situation, threads.parse(body.get("thread"))


async def _read_body(receive) -> bytes:
    """The request body, refusing anything over the cap WHILE it arrives.

    The stdlib version could trust `Content-Length` because it read the socket itself. ASGI
    hands the body over in chunks and a client is free to send a wrong length or none at
    all, so the cap is checked against what has ACTUALLY been received. Checking the header
    instead would let a chunked request walk straight past it.
    """
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            raise ValueError("client disconnected before the body arrived")
        chunks.append(message.get("body", b""))
        size += len(chunks[-1])
        if size > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        if not message.get("more_body"):
            return b"".join(chunks)


async def _send(send, status: int, payload: dict, headers: list | None = None) -> None:
    data = json.dumps(payload).encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": _JSON + [(b"content-length", str(len(data)).encode())]
                + list(headers or ())})
    await send({"type": "http.response.body", "body": data})
