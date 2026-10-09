"""`build_app`: the FastAPI application, assembled from the pieces in this package."""
from __future__ import annotations

import contextlib
from typing import Awaitable, Callable

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from starlette.exceptions import HTTPException as StarletteHTTPException

from ask_naren.api import admission
from ask_naren.api.dependencies import Answerer, ReadyCheck
from ask_naren.api.handlers import http_error, malformed, refused
from ask_naren.api.middleware import MAX_BODY_BYTES, BodyCap, StripTrailingSlash
from ask_naren.api.refusals import Refusal
from ask_naren.api.routes import router


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
    stylistic. See `_lifespan` below for the Ctrl-C failure it exists to avoid.
    """
    app = FastAPI(
        title="Ask Naren",
        summary="Answers a CSM's live client situation from Naren's closest real recorded "
                "exchange, or declines.",
        lifespan=_lifespan(on_shutdown),
        # `middleware.StripTrailingSlash` normalises instead: a redirected POST arrives as a GET.
        redirect_slashes=False,
    )
    app.state.answerer = answerer
    app.state.is_ready = ready if ready is not None else (lambda: True)
    app.state.gate = gate if gate is not None else admission.Admission()

    app.include_router(router)
    app.openapi = _without_422(app)
    app.add_exception_handler(Refusal, refused)
    app.add_exception_handler(RequestValidationError, malformed)
    app.add_exception_handler(StarletteHTTPException, http_error)
    # Outermost last: the slash is normalised before anything reads the path, and the cap
    # is enforced before FastAPI buffers a byte.
    app.add_middleware(BodyCap, limit=MAX_BODY_BYTES)
    app.add_middleware(StripTrailingSlash)
    return app


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


def _without_422(app: FastAPI):
    """The OpenAPI document, minus the 422 FastAPI documents on every route with a body.
    This service never sends one (`handlers.malformed` answers 400), and a schema that promises a
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
