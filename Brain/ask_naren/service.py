"""Ask Naren's HTTP boundary: one endpoint, plus a readiness check.

STDLIB `http.server`, AND SINGLE-THREADED, BOTH ON PURPOSE.

  * No web framework, because there is nothing here a framework would do: one JSON POST,
    one health GET. Adding fastapi/uvicorn would add two dependencies to Brain's venv for
    routing two paths.

  * NOT ThreadingHTTPServer. Requests are served one at a time because the request path
    embeds the incoming situation, and the embedder's disk cache (shared/embed_cache.py)
    holds a `sqlite3.connect` made WITHOUT check_same_thread=False. A second request thread
    touching that connection raises outright. Serialising is the honest fix for an internal
    tool whose requests take a few seconds each; making the cache thread-safe, or pinning
    embedding to a dedicated worker thread, is a real change to shared/ and not this
    ticket's job. The consequence to know: /health queues behind an in-flight generation.

The layer does no reshaping. Whatever the answerer decided is what the caller reads --
retrieval, grounding and model-calling all live in one place, and it is not here.
"""
from __future__ import annotations

import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

# A body big enough for any real situation and small enough that a runaway client cannot
# make the service read itself out of memory.
MAX_BODY_BYTES = 64 * 1024

SERVICE_ERROR = "service_error"
_SERVICE_ERROR_MESSAGE = (
    "Ask Naren could not reach its knowledge base just now. Nothing was answered -- this "
    "is a fault on our side, not a 'no close match'. Try again in a moment."
)


def build_server(answerer: Callable[[str], dict], *, host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT) -> HTTPServer:
    """An unstarted server. `port=0` binds an ephemeral port, which is what tests use."""
    return HTTPServer((host, port), _make_handler(answerer))


def serve(answerer: Callable[[str], dict], *, host: str = DEFAULT_HOST,
          port: int = DEFAULT_PORT) -> None:
    httpd = build_server(answerer, host=host, port=port)
    print(f"[ask-naren] listening on http://{host}:{httpd.server_address[1]}  "
          f"POST /ask  GET /health", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("[ask-naren] shutting down", flush=True)
    finally:
        httpd.server_close()


def _make_handler(answerer: Callable[[str], dict]) -> type[BaseHTTPRequestHandler]:

    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.1 for correct semantics, but every response closes its connection (see
        # _send). Keep-alive on a SERIAL server is a self-inflicted outage: the accept loop
        # blocks in handle_one_request waiting for another request on an idle socket, and
        # the next CSM's question waits behind a connection nobody is using. Measured: one
        # lingering client made every subsequent request time out.
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:         # noqa: N802 -- stdlib naming
            if self.path.rstrip("/") == "/health":
                self._send(200, {"status": "ok"})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:        # noqa: N802 -- stdlib naming
            if self.path.rstrip("/") != "/ask":
                self._send(404, {"error": "not found"})
                return
            try:
                situation = self._read_situation()
            except ValueError as e:
                self._send(400, {"error": str(e)})
                return
            try:
                self._send(200, answerer(situation))
            except Exception:             # noqa: BLE001 -- a CSM must never see a traceback
                # Logged in full here, reported as a generic fault to the caller: the
                # message could name internal hosts, and it is not something a CSM can act
                # on. The 503 is what tells an operator this was a fault, not a decline.
                traceback.print_exc(file=sys.stderr)
                self._send(503, {"outcome": "declined", "reason": SERVICE_ERROR,
                                 "message": _SERVICE_ERROR_MESSAGE})

        def _read_situation(self) -> str:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                raise ValueError("empty request body")
            if length > MAX_BODY_BYTES:
                raise ValueError("request body too large")
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise ValueError("body must be JSON") from None
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            situation = body.get("situation")
            if not isinstance(situation, str) or not situation.strip():
                raise ValueError("'situation' must be a non-empty string")
            return situation

        def _send(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.close_connection = True
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args) -> None:
            """Silences BaseHTTPRequestHandler's per-request stderr access log. Faults are
            reported by do_POST's traceback instead, which is the part worth reading."""

    return Handler
