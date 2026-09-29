"""Ask Naren's HTTP boundary: one endpoint, plus liveness and readiness.

A FASTAPI APPLICATION ON UVICORN (2026-09-29).

It began as the stdlib `http.server` (ADR 0003), became a raw ASGI app with no framework in
issue #31 ("there is nothing here a framework would do"), and is now FastAPI -- the operator's
decision, reversing #31's, so the service follows Joveo's applib convention and its contract
is a schema at `/docs` rather than prose. The request is a Pydantic model (`AskRequest`), the
responses are documented models (`ask_naren/api_models.py`), the routes are an `APIRouter`,
the gate and the answerer are dependencies, and every way of saying no is an exception with
a handler.

WHAT THE CALLER SEES DID NOT MOVE, and three decisions are what keep it that way:

  * A BODY THAT FAILS VALIDATION IS A 400, NOT FASTAPI'S 422. The frontend's proxy leaves
    validating `situation` to this service and forwards its 400 as its own (route.ts), and
    it keys "answered nothing, do not record" on 400 (#37), as its own invalid-body answers
    are. A 422 would be a third status meaning the same thing. So a
    `RequestValidationError` handler answers `{"error": ...}` with 400, as before.
  * THE 64 KB CAP IS ENFORCED WHILE THE BODY STREAMS IN, by `_BodyCap`, an ASGI middleware
    in front of FastAPI. FastAPI buffers the whole body before any dependency runs, so a cap
    anywhere inside it would be checked after the memory was already spent.
  * ANYTHING UNROUTED IS A JSON `{"error": "not found"}` 404 -- including a wrong method,
    which FastAPI would call a 405 -- and `/ask/` is `/ask` rather than a redirect, because a
    redirected POST arrives as a GET.

The one visible difference is the JSON's whitespace: responses are FastAPI's compact JSON
rather than `json.dumps`'s default separators. Nothing parses whitespace.

STILL ONE PROCESS, ONE EVENT LOOP (ADR 0010). FastAPI changes nothing about that: the
gateway's in-flight budget belongs to the API key, and the admission gate here is the only
thing enforcing it.

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
import sys
import traceback
from typing import Annotated, Awaitable, Callable

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from ask_naren import admission
from ask_naren.api_models import AskRequest, AskResponse, Declined, Error, Health, Readiness

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

# A body big enough for any real situation and small enough that a runaway client cannot
# make the service read itself out of memory. Enforced WHILE the body streams in, not after
# it has all arrived -- see `_BodyCap`.
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


#: The answerer takes the situation AND the thread it arrived in (issue #15), and is AWAITED
#: (issue #30). Still ONE callable -- the layer did not grow a second entry point for a
#: multi-turn request, because a thread is not a different kind of question, it is context
#: on the same one.
Answerer = Callable[[str, tuple], Awaitable[dict]]

#: Whether the service can answer yet. Separate from liveness on purpose: a process that is
#: up but not able to answer is not a dead one, and an ingress that cannot tell the
#: difference will kill something that is merely starting.
ReadyCheck = Callable[[], bool]


# -- the ways of saying no that THIS layer writes ----------------------------------------

class Refusal(Exception):
    """A decline written by this layer rather than by the answerer: busy, out of time, or
    broken. Raised from anywhere under `/ask` and turned into its response by ONE handler,
    `_refused`, so the status, the reason code and the sentence cannot be assembled in two
    places and drift apart.

    The body is built through `api_models.Declined`, so what this layer writes is checked
    against the same schema `/docs` publishes.
    """

    status: int

    def __init__(self, reason: str, message: str, *, headers: dict | None = None,
                 **extra) -> None:
        super().__init__(reason)
        self.body = Declined(outcome="declined", reason=reason, message=message,
                             **extra).model_dump(exclude_none=True)
        self.headers = headers or {}


class ServiceBusy(Refusal):
    """REFUSED ON ARRIVAL, having waited for nothing. 429 and not 503: a busy lunchtime must
    not look like an outage to whatever counts 5xx, and `Retry-After` carries the same
    estimate as the prose for anything reading headers rather than sentences."""

    status = 429

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(SERVICE_BUSY,
                         _SERVICE_BUSY_MESSAGE.format(seconds=retry_after_seconds),
                         headers={"Retry-After": str(retry_after_seconds)},
                         retry_after_seconds=retry_after_seconds)


class DeadlineExceeded(Refusal):
    status = 504

    def __init__(self) -> None:
        super().__init__(DEADLINE_EXCEEDED, _DEADLINE_MESSAGE)


class ServiceFault(Refusal):
    """Something broke on our side. Reported generically: the underlying message could name
    internal hosts, and it is not something a CSM can act on. The 503 is what tells an
    operator this was a fault rather than a decline."""

    status = 503

    def __init__(self) -> None:
        super().__init__(SERVICE_ERROR, _SERVICE_ERROR_MESSAGE)


# -- dependencies ------------------------------------------------------------------------
#
# What `build_app` was given, handed to the routes through FastAPI's dependency system
# rather than closed over, so the routes are defined once at module level and a test that
# wants a different gate passes one to `build_app` instead of patching anything.

def _gate(request: Request) -> admission.Admission:
    return request.app.state.gate


def _answerer(request: Request) -> Answerer:
    return request.app.state.answerer


def _is_ready(request: Request) -> ReadyCheck:
    return request.app.state.is_ready


GateDep = Annotated[admission.Admission, Depends(_gate)]
AnswererDep = Annotated[Answerer, Depends(_answerer)]
ReadyDep = Annotated[ReadyCheck, Depends(_is_ready)]


# -- routes ------------------------------------------------------------------------------

router = APIRouter()

_DECLINE = {"model": Declined}


@router.get("/health", response_model=Health, summary="Liveness")
@router.get("/healthz", response_model=Health, summary="Liveness (the applib probe spelling)")
async def health() -> dict:
    """LIVENESS. Awaits nothing, so it cannot queue behind an answer no matter how many are
    in flight. Deliberately says nothing about readiness: an ingress restarting a
    busy-but-healthy process is the failure this endpoint exists to prevent.

    TWO SPELLINGS, ONE ANSWER. `/health` is this service's own contract and what the audit
    harnesses poll; `/healthz` is what the Joveo applib template's probes expect.
    """
    return {"status": "ok"}


@router.get("/ready", response_model=Readiness, summary="Readiness and saturation",
            responses={503: {"model": Readiness,
                             "description": "`starting`, or `saturated`: alive and healthy, "
                                            "but the queue is as deep as the deadline can "
                                            "absorb."}})
async def ready(gate: GateDep, is_ready: ReadyDep) -> JSONResponse:
    """READINESS, AND SATURATION (issue #32). "Saturated" is alive, healthy, answering as many
    as it can, and unable to take another without breaking the deadline -- the QUEUE behind
    the busy slots is as deep as the deadline can absorb. The counts ride along on all three
    answers, because the peaks and the refusal count are how an operator tells whether we
    have outgrown this API key's allowance."""
    if not is_ready():
        return JSONResponse({"status": "starting", **gate.snapshot()}, status_code=503)
    if gate.saturated:
        return JSONResponse({"status": "saturated", **gate.snapshot()}, status_code=503)
    return JSONResponse({"status": "ready", **gate.snapshot()})


@router.post(
    "/ask",
    summary="Answer one situation",
    response_model=None,
    responses={
        200: {"model": AskResponse,
              "description": "An answer, a rendered answer, a clarify, or a decline. A "
                             "`no_close_match` decline is a 200: it is the tool working "
                             "correctly, not an error."},
        400: {"model": Error, "description": "The body could not be read: not JSON, no "
                                             "`situation`, a blank one, a malformed "
                                             "`thread`, or over 64 KB. Costs no slot."},
        429: {**_DECLINE, "description": "`service_busy`: refused on arrival, with "
                                         "`Retry-After`.",
              "headers": {"Retry-After": {"schema": {"type": "integer"},
                                          "description": "Seconds until there is room."}}},
        503: {**_DECLINE, "description": "`service_error`: a fault on our side."},
        504: {**_DECLINE, "description": "`deadline_exceeded`: admitted, then ran out of "
                                         "time."},
    },
)
async def ask(body: AskRequest, request: Request, gate: GateDep,
              answerer: AnswererDep) -> Response:
    """One question, under a bound and a deadline, and abandonable (issue #32).

    THE ORDER OF THE THREE THINGS HERE IS THE DESIGN:

      1. The body is read and validated FIRST -- by FastAPI, before this function runs. A
         malformed request is a 400 that costs no slot: it would be perverse to queue
         someone behind a request that was never going to be answered, and worse to refuse
         them as "busy" because of it.

      2. The disconnect watcher starts BEFORE the slot is taken, not after. That ordering is
         the whole of the abandonment criterion: the expensive case is a CSM who closed the
         tab while still QUEUED, and a watcher started after admission would not notice them
         until they were already being answered. Started here, they simply leave the queue
         and the colleague behind them moves up.

      3. Admission and the answer run inside ONE deadline that starts at arrival, so the
         budget covers the wait as well as the work. A deadline measured from admission
         would be a promise about the part we control instead of about what a CSM
         experiences, and the queue depth is derived from the whole-request figure.

    The answerer's response is sent AS IT COMPOSED IT, not through `AskResponse` -- see
    `api_models` for why the response models document rather than filter.
    """
    answer = await _unless_abandoned(
        _admit_and_answer(answerer, body.situation, body.turns(), gate), request.receive)
    if answer is None:
        # THE CALLER IS GONE. Nothing useful can be sent; this empty response exists only
        # so the framework has something to return on a socket that no longer exists.
        return Response(status_code=499)
    return JSONResponse(answer)


# -- exception handlers ------------------------------------------------------------------

async def _refused(_request: Request, exc: Refusal) -> JSONResponse:
    return JSONResponse(exc.body, status_code=exc.status, headers=exc.headers)


async def _malformed(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """400, not 422 -- see the module docstring. `error` names the field and what was wrong
    with it, for the engineer reading it; nothing here reaches a CSM."""
    problems = []
    for e in exc.errors():
        loc = tuple(e.get("loc", ()))[1:]         # drop the leading "body"
        if e.get("type") == "json_invalid":
            problems.append("body must be JSON")
        elif not loc and e.get("type") == "missing":
            problems.append("empty request body")
        elif not loc:
            problems.append("body must be a JSON object")
        else:
            problems.append(f"{'.'.join(map(str, loc))}: {e['msg']}")
    return JSONResponse({"error": "; ".join(dict.fromkeys(problems)) or "invalid request"},
                        status_code=400)


def _without_422(app: FastAPI):
    """The OpenAPI document, minus the 422 FastAPI documents on every route with a body.
    This service never sends one (`_malformed` answers 400), and a schema that promises a
    status the service cannot produce is the drift a schema exists to prevent."""
    def openapi() -> dict:
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, summary=app.summary,
                                 routes=app.routes)
            for path in schema.get("paths", {}).values():
                for operation in path.values():
                    operation.get("responses", {}).pop("422", None)
            for name in ("HTTPValidationError", "ValidationError"):
                schema.get("components", {}).get("schemas", {}).pop(name, None)
            app.openapi_schema = schema
        return app.openapi_schema
    return openapi


async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Unknown path OR unsupported method: the service's own JSON 404 -- not FastAPI's
    `{"detail": ...}`, and not a 405. Every response this service gives is JSON with an
    `error` or an `outcome`, and the proxy in front of it parses every body."""
    if exc.status_code in (404, 405):
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code,
                        headers=exc.headers)


# -- the application ---------------------------------------------------------------------

def build_app(answerer: Answerer, *, ready: ReadyCheck | None = None,
              on_shutdown: "Callable[[], Awaitable[None]] | None" = None,
              gate: "admission.Admission | None" = None) -> FastAPI:
    """The FastAPI application. `ready` defaults to always-ready.

    IT HOLDS ONE PIECE OF STATE: `gate` counts what is in flight and what is queued (issue
    #32), which is unavoidable -- a bound is by definition something remembered between
    requests. It is not state about any PARTICULAR request, and nothing a CSM asked is
    retained.

    `gate` defaults to a fresh `Admission` built from the shipped numbers. A test passes its
    own to make the bound small enough to reach.

    `on_shutdown` IS AWAITED FROM THE LIFESPAN, and that is load-bearing rather than
    stylistic. See `_lifespan` for the Ctrl-C failure it exists to avoid.
    """
    app = FastAPI(
        title="Ask Naren",
        summary="Answers a CSM's live client situation from Naren's closest real recorded "
                "exchange, or declines.",
        lifespan=_lifespan(on_shutdown),
        # `_StripTrailingSlash` normalises instead: a redirected POST arrives as a GET.
        redirect_slashes=False,
    )
    app.state.answerer = answerer
    app.state.is_ready = ready if ready is not None else (lambda: True)
    app.state.gate = gate if gate is not None else admission.Admission()

    app.include_router(router)
    app.openapi = _without_422(app)
    app.add_exception_handler(Refusal, _refused)
    app.add_exception_handler(RequestValidationError, _malformed)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    # Outermost last: the slash is normalised before anything reads the path, and the cap
    # is enforced before FastAPI buffers a byte.
    app.add_middleware(_BodyCap, limit=MAX_BODY_BYTES)
    app.add_middleware(_StripTrailingSlash)
    return app


async def serve(answerer: Answerer, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                ready: ReadyCheck | None = None,
                on_shutdown: "Callable[[], Awaitable[None]] | None" = None,
                gate: "admission.Admission | None" = None) -> None:
    """Serve until interrupted. AWAITED, because uvicorn owns the event loop.

    `uvicorn` is imported here rather than at module scope so `--ask` and the answer-path
    tests can use this module without it. It is a server, needed only to serve.

    ONE uvicorn SERVER IN THIS PROCESS, NEVER `--workers` (ADR 0010): the gateway's budget
    belongs to the API key, and each worker would keep its own gate.

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
          f"POST /ask  GET /health  GET /ready  GET /docs", flush=True)
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


def _lifespan(on_shutdown=None):
    """FastAPI's lifespan, running the caller's teardown at shutdown.

    STARTUP does nothing: the pool, the gateway client and the store are loaded by
    `ops/serve_ask_naren.py` BEFORE the server starts. Moving that in here would turn the
    coverage guard's refuse-to-serve decision into a lifespan failure, which is a worse
    place to report it from.

    *** SHUTDOWN IS WHERE THE TEARDOWN HAS TO HAPPEN, AND A `finally` AROUND `serve()` IS
    NOT ENOUGH. *** Measured on Ctrl-C: `asyncio.run` installs a SIGINT handler that
    cancels the main task, and uvicorn's `capture_signals` restores the previous handler
    and re-raises the signal into it -- so the caller's task is already cancelled by the
    time its `finally` runs, and the first `await gateway.aclose()` there raises
    CancelledError immediately. Uvicorn runs the lifespan shutdown as part of its GRACEFUL
    shutdown, before any of that -- so teardown awaited here completes normally.
    """
    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if on_shutdown is not None:
            await on_shutdown()
    return lifespan


# -- the answer, under a bound, a deadline and a watcher ---------------------------------

async def _unless_abandoned(work_coro: Awaitable[dict], receive) -> dict | None:
    """The answer, or None if the caller left first. A `Refusal` from the work propagates
    to its handler.

    `asyncio.wait` rather than `gather`: we need to know WHICH of the two finished, and the
    loser must be cancelled and awaited rather than left to surface later as an
    unretrieved-task warning.
    """
    abandoned = asyncio.create_task(_wait_for_disconnect(receive))
    work = asyncio.ensure_future(work_coro)
    try:
        done, _ = await asyncio.wait({work, abandoned}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Also on OUR cancellation (a server shutting down mid-answer): neither task may
        # outlive the request.
        for task in (work, abandoned):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    if work not in done:
        # THE CALLER IS GONE. Cancelling (above) is what released the slot or dropped us out
        # of the queue -- `Admission.slot`'s teardown is await-free precisely so it
        # completes inside a cancellation.
        return None
    return work.result()


async def _admit_and_answer(answerer: Answerer, situation: str, thread: tuple,
                            gate: "admission.Admission") -> dict:
    """Take a slot and answer -- or raise the `Refusal` that says why not.

    Every exit is the answer or one of the three refusals; nothing else escapes, because a
    CSM must never see a traceback.
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
                    return await answerer(situation, thread)
            except admission.Busy as busy:
                print(f"[ask-naren] busy: refused a question with {gate.queued} queued "
                      f"and {gate.in_flight} in flight ({gate.refused} refused so far)",
                      file=sys.stderr, flush=True)
                raise ServiceBusy(busy.retry_after_seconds) from None
    except Refusal:
        raise
    except TimeoutError:
        if budget.expired():
            # The only timeout before this was the gateway's 120s, and no CSM waits 120s.
            # Counted, because a rising number here means the cost estimate the depth is
            # sized from has drifted, and the depth is now admitting people it cannot serve.
            gate.note_deadline_missed()
            print(f"[ask-naren] deadline: gave up after {gate.deadline:.0f}s "
                  f"({gate.deadlines_missed} so far)", file=sys.stderr, flush=True)
            raise DeadlineExceeded() from None
        traceback.print_exc(file=sys.stderr)
        raise ServiceFault() from None
    except Exception:                     # noqa: BLE001 -- a CSM must never see a traceback
        traceback.print_exc(file=sys.stderr)
        raise ServiceFault() from None


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


# -- ASGI middleware ---------------------------------------------------------------------

class _BodyCap:
    """The request body, refused if it is over the cap WHILE it arrives -- then replayed to
    FastAPI as one message.

    IT HAS TO BE OUTSIDE FASTAPI. FastAPI reads the whole body before validation or any
    dependency runs, so a cap inside it is checked after the memory is already spent. And a
    client is free to send a wrong `Content-Length` or none at all (chunked), so the cap is
    checked against what has ACTUALLY been received; a declared length over the cap is
    refused without reading a byte.

    After the replayed body, `receive` passes straight through to the server, which is how
    `_wait_for_disconnect` still hears `http.disconnect`.
    """

    _BODYLESS = frozenset({"GET", "HEAD", "OPTIONS"})

    def __init__(self, app, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["method"] in self._BODYLESS:
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.limit:
            await self._too_large(scope, receive, send)
            return

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return                    # nobody left to answer
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            if size > self.limit:
                await self._too_large(scope, receive, send)
                return
            if not message.get("more_body"):
                break

        body = b"".join(chunks)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _too_large(scope, receive, send) -> None:
        await JSONResponse({"error": "request body too large"},
                           status_code=400)(scope, receive, send)


class _StripTrailingSlash:
    """`/health/` is `/health` and `/ask/` is `/ask` -- normalised rather than redirected,
    because a redirected POST loses its body."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["path"] != "/" and scope["path"].endswith("/"):
            scope = dict(scope, path=scope["path"].rstrip("/") or "/")
        await self.app(scope, receive, send)
