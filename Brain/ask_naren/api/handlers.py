"""The exception handlers: every response that is not a route's own return value.

Between them they keep the service's promise that EVERY body is JSON carrying either an
`outcome` or an `error` -- the proxy in front of it parses every body, and FastAPI's
defaults (`{"detail": ...}`, a 422, a 405) are shapes it was never written for.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ask_naren.api.refusals import Refusal


async def refused(_request: Request, exc: Refusal) -> JSONResponse:
    return JSONResponse(exc.body, status_code=exc.status, headers=exc.headers)


async def malformed(_request: Request, exc: RequestValidationError) -> JSONResponse:
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


async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Unknown path OR unsupported method: the service's own JSON 404 -- not FastAPI's
    `{"detail": ...}`, and not a 405. Every response this service gives is JSON with an
    `error` or an `outcome`, and the proxy in front of it parses every body."""
    if exc.status_code in (404, 405):
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code,
                        headers=exc.headers)
