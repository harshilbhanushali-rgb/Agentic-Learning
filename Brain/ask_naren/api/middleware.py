"""ASGI middleware that has to run BEFORE FastAPI sees the request: the body cap and the
trailing-slash normaliser."""
from __future__ import annotations

from fastapi.responses import JSONResponse

# A body big enough for any real situation and small enough that a runaway client cannot
# make the service read itself out of memory. Enforced WHILE the body streams in, not after
# it has all arrived -- see `BodyCap`.
MAX_BODY_BYTES = 64 * 1024


class BodyCap:
    """The request body, refused if it is over the cap WHILE it arrives -- then replayed to
    FastAPI as one message.

    IT HAS TO BE OUTSIDE FASTAPI. FastAPI reads the whole body before validation or any
    dependency runs, so a cap inside it is checked after the memory is already spent. And a
    client is free to send a wrong `Content-Length` or none at all (chunked), so the cap is
    checked against what has ACTUALLY been received; a declared length over the cap is
    refused without reading a byte.

    After the replayed body, `receive` passes straight through to the server, which is how
    `answer_flow.wait_for_disconnect` still hears `http.disconnect`.
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


class StripTrailingSlash:
    """`/health/` is `/health` and `/ask/` is `/ask` -- normalised rather than redirected,
    because a redirected POST loses its body."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["path"] != "/" and scope["path"].endswith("/"):
            scope = dict(scope, path=scope["path"].rstrip("/") or "/")
        await self.app(scope, receive, send)
