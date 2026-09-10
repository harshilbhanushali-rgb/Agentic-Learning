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

WHAT CHANGED FOR A CSM: two of them are answered at once. Requests overlap while they wait
on the gateway, which is where essentially all of an answer's ~12.5s goes. Measured live at
the layer below this one before this layer existed: 3 situations in 15.2s against 30.4s
serialised (ask-naren/audit/check_async_concurrency.py).

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

WHAT THIS LAYER STILL DOES NOT DO: no reshaping. Whatever the answerer decided is what the
caller reads -- retrieval, grounding and model-calling all live in one place, and it is not
here.
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Awaitable, Callable

from ask_naren import threads

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

# A body big enough for any real situation and small enough that a runaway client cannot
# make the service read itself out of memory. Enforced WHILE the body streams in, not after
# it has all arrived -- see `_read_body`.
MAX_BODY_BYTES = 64 * 1024

SERVICE_ERROR = "service_error"
_SERVICE_ERROR_MESSAGE = (
    "Ask Naren could not reach its knowledge base just now. Nothing was answered -- this "
    "is a fault on our side, not a 'no close match'. Try again in a moment."
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
              on_shutdown: "Callable[[], Awaitable[None]] | None" = None):
    """The ASGI application. `ready` defaults to always-ready.

    Returns a callable rather than an object because that is the whole ASGI contract, and
    an object would imply state this layer does not have -- it holds the answerer and
    nothing else, and stores nothing between requests.

    `on_shutdown` IS AWAITED FROM THE LIFESPAN, and that is load-bearing rather than
    stylistic. See `_lifespan` for the Ctrl-C failure it exists to avoid.
    """
    is_ready = ready if ready is not None else (lambda: True)

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
            # READINESS. Note what already covers the startup window: during the Postgres
            # read and the coverage guard the port is not open at all, so a check gets
            # connection-refused, which every ingress reads as "not yet". This endpoint is
            # for a state the process can report WHILE listening -- which is what issue
            # #32's queue bound will need.
            if is_ready():
                return await _send(send, 200, {"status": "ready"})
            return await _send(send, 503, {"status": "starting"})

        if method == "POST" and path == "/ask":
            return await _ask(answerer, receive, send)

        await _send(send, 404, {"error": "not found"})

    return app


async def serve(answerer: Answerer, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                ready: ReadyCheck | None = None,
                on_shutdown: "Callable[[], Awaitable[None]] | None" = None) -> None:
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

    config = uvicorn.Config(
        build_app(answerer, ready=ready, on_shutdown=on_shutdown),
        host=host, port=port, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    sock = config.bind_socket()
    bound_host, bound_port = sock.getsockname()[:2]
    print(f"[ask-naren] listening on http://{bound_host}:{bound_port}  "
          f"POST /ask  GET /health  GET /ready", flush=True)
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


async def _ask(answerer: Answerer, receive, send) -> None:
    try:
        situation, thread = await _read_request(receive)
    except ValueError as e:
        return await _send(send, 400, {"error": str(e)})
    try:
        await _send(send, 200, await answerer(situation, thread))
    except Exception:                     # noqa: BLE001 -- a CSM must never see a traceback
        # Logged in full here, reported as a generic fault to the caller: the message could
        # name internal hosts, and it is not something a CSM can act on. The 503 is what
        # tells an operator this was a fault, not a decline.
        traceback.print_exc(file=sys.stderr)
        await _send(send, 503, {"outcome": "declined", "reason": SERVICE_ERROR,
                                "message": _SERVICE_ERROR_MESSAGE})


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


async def _send(send, status: int, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": _JSON + [(b"content-length", str(len(data)).encode())]})
    await send({"type": "http.response.body", "body": data})
