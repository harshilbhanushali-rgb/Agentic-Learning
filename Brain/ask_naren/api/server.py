"""`serve`: one uvicorn server for the application, in THIS process (ADR 0010)."""
from __future__ import annotations

from typing import Awaitable, Callable

from ask_naren.api import admission
from ask_naren.api.app import build_app
from ask_naren.api.dependencies import Answerer, ReadyCheck

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


async def serve(answerer: Answerer, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                ready: ReadyCheck | None = None,
                on_shutdown: "Callable[[], Awaitable[None]] | None" = None,
                gate: "admission.Admission | None" = None) -> None:
    """Serve until interrupted. AWAITED, because uvicorn owns the event loop.

    `uvicorn` is imported here rather than at module scope so `--ask` and the answer-path
    tests can import `ask_naren.api` without it. It is a server, needed only to serve.

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
