"""ask_naren/api/ -- the HTTP contract, over a real socket against a stubbed
answerer. No gateway, no Postgres, no embeddings.

STILL A REAL SOCKET AFTER ISSUE #31, deliberately. Driving the ASGI app in-process with
`httpx.ASGITransport` would be faster and needs no thread, and #31's ticket suggested it --
but this file's job is to pin an HTTP CONTRACT that a Next.js proxy depends on, and
ASGITransport bypasses the actual HTTP parsing, status line and header handling. The
concurrency tests at the bottom DO use the in-process transport, where precise ordering is
the thing being asserted and the socket adds nothing.

The fixture accepts a plain synchronous answerer and adapts it, so every contract test
below is byte-identical to the one that ran against the stdlib server. The tests that need
real overlap pass an `async` answerer instead.
"""
import asyncio
import contextlib
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from ask_naren import api
from ask_naren.api import admission

ANSWER = {"outcome": "answered", "answer": "Reframe on their own baseline.",
          "quote": "their own baseline", "citation": {"label": "a_call.txt"},
          "match": {"cosine": 0.71, "scenario_key": "performance_pushback"}}


def _as_async(answerer):
    """Adapt a synchronous stub to the awaited contract the app now requires.

    Only for stubs. The real answerer is `async` all the way down -- this exists so the
    contract tests written against the stdlib server keep their exact bodies, rather than
    being rewritten (and possibly weakened) alongside the layer they are meant to pin.
    """
    if asyncio.iscoroutinefunction(answerer):
        return answerer

    async def adapted(situation, thread=()):
        return answerer(situation, thread)
    return adapted


@pytest.fixture
def serve_with():
    """Runs the real server on an ephemeral port with whatever answerer a test supplies."""
    started = []

    def _start(answerer, ready=None, gate=None):
        app = api.build_app(_as_async(answerer), ready=ready, gate=gate)
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:            # pragma: no cover
                raise RuntimeError("uvicorn did not start")
            time.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        started.append((server, thread))
        return f"http://127.0.0.1:{port}"

    yield _start
    for server, thread in started:
        server.should_exit = True
        thread.join(timeout=5)


def _drive(app):
    """An httpx client that speaks to the ASGI app in-process -- no socket, no thread.

    Used only where the assertion is about ORDERING between overlapping requests, which a
    real socket makes noisier rather than more faithful.
    """
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="http://asgi")


def test_a_situation_gets_the_answerers_response_unchanged(serve_with):
    """The HTTP layer is transport only: whatever the answerer decided is what a caller
    reads, with no reshaping in between for the frontend to have to know about."""
    base = serve_with(lambda situation, thread=():ANSWER)
    r = httpx.post(f"{base}/ask", json={"situation": "cost per hire is too high"})
    assert r.status_code == 200
    assert r.json() == ANSWER


def test_the_situation_reaches_the_answerer_verbatim(serve_with):
    seen = []
    base = serve_with(lambda situation, thread=():(seen.append(situation), ANSWER)[1])
    httpx.post(f"{base}/ask", json={"situation": "  client is angry about spend  "})
    assert seen == ["  client is angry about spend  "]


# -- the thread a caller replays (issue #15) ---------------------------------------------

def test_a_request_with_no_thread_is_an_empty_thread(serve_with):
    """Every caller written before threads existed, `--ask` included, sends no `thread` key
    and must keep working exactly as it did."""
    seen = []
    base = serve_with(lambda situation, thread=():(seen.append(thread), ANSWER)[1])
    httpx.post(f"{base}/ask", json={"situation": "cost per hire is too high"})
    assert seen == [()]


def test_a_thread_reaches_the_answerer_as_validated_turns(serve_with):
    seen = []
    base = serve_with(lambda situation, thread=():(seen.append(thread), ANSWER)[1])
    r = httpx.post(f"{base}/ask", json={
        "situation": "and if they push back on price?",
        "thread": [{"message": "client says our cpa is 3x", "outcome": "answered",
                    "reply": "reframe on their own baseline", "pair_id": 11,
                    "scenario_key": "performance_pushback", "call_filename": "a.txt"}],
    })
    assert r.status_code == 200
    assert len(seen[0]) == 1
    assert seen[0][0].pair_id == 11
    assert seen[0][0].scenario_key == "performance_pushback"


def test_a_malformed_thread_is_rejected_rather_than_silently_ignored(serve_with):
    """Ignoring it would answer every follow-up as a brand new question while the tool
    looked perfectly healthy -- the same class of silent failure the `intake` echo on every
    response exists to prevent."""
    called = []
    base = serve_with(lambda situation, thread=():called.append(situation) or ANSWER)
    r = httpx.post(f"{base}/ask", json={"situation": "anything",
                                        "thread": [{"outcome": "sideways"}]})
    assert r.status_code == 400
    assert called == []


def test_a_decline_is_a_successful_response_not_an_error(serve_with):
    """A decline is Ask Naren working correctly. Returning it as an HTTP error would make
    every caller treat conservative behaviour as an outage."""
    decline = {"outcome": "declined", "reason": "no_close_match", "message": "No close match."}
    base = serve_with(lambda situation, thread=():decline)
    r = httpx.post(f"{base}/ask", json={"situation": "anything"})
    assert r.status_code == 200
    assert r.json()["outcome"] == "declined"


def test_a_blank_situation_is_rejected_without_reaching_the_answerer(serve_with):
    called = []
    base = serve_with(lambda situation, thread=():called.append(situation) or ANSWER)
    r = httpx.post(f"{base}/ask", json={"situation": "   "})
    assert r.status_code == 400
    assert called == []


def test_a_missing_situation_field_is_rejected(serve_with):
    base = serve_with(lambda situation, thread=():ANSWER)
    assert httpx.post(f"{base}/ask", json={"question": "wrong key"}).status_code == 400


def test_a_malformed_body_is_rejected_rather_than_crashing_the_server(serve_with):
    base = serve_with(lambda situation, thread=():ANSWER)
    r = httpx.post(f"{base}/ask", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400
    # the server is still answering afterwards
    assert httpx.post(f"{base}/ask", json={"situation": "still up"}).status_code == 200


def test_an_answerer_failure_reads_as_a_decline_not_a_traceback(serve_with):
    """A gateway outage or a dropped VPN must not put a stack trace in front of a CSM. The
    status distinguishes it from a genuine decline for whoever is debugging."""
    def explode(situation, thread=()):
        raise RuntimeError("gateway unreachable")

    base = serve_with(explode)
    r = httpx.post(f"{base}/ask", json={"situation": "anything"})
    assert r.status_code == 503
    body = r.json()
    assert body["outcome"] == "declined"
    assert body["reason"] == "service_error"
    assert body["message"]
    assert "gateway unreachable" not in json.dumps(body)


def test_health_reports_readiness_without_spending_a_generation(serve_with):
    called = []
    base = serve_with(lambda situation, thread=():called.append(situation) or ANSWER)
    r = httpx.get(f"{base}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert called == []


def test_an_unknown_path_is_a_404(serve_with):
    base = serve_with(lambda situation, thread=():ANSWER)
    assert httpx.post(f"{base}/answer", json={"situation": "x"}).status_code == 404
    assert httpx.get(f"{base}/ask").status_code == 404


def test_responses_are_json(serve_with):
    base = serve_with(lambda situation, thread=():ANSWER)
    r = httpx.post(f"{base}/ask", json={"situation": "x"})
    assert r.headers["content-type"].startswith("application/json")


def test_an_idle_client_connection_does_not_block_the_next_caller(serve_with):
    """Same assertion as before issue #31, for a completely different reason -- which is
    why the docstring changed and the body did not.

    It used to pass because the serial stdlib server closed every connection: with HTTP/1.1
    keep-alive, the accept loop would block in `handle_one_request` on an idle socket and
    the next CSM's question would wait on a connection nobody was using. Measured, not
    theorised -- one lingering client made every subsequent request time out.

    KEEP-ALIVE IS NOW ALLOWED, because that failure mode was a property of serialisation
    and disappeared with it: an idle connection occupies no worker. So this now pins the
    behaviour rather than the workaround. If a future change re-serialises the server, this
    is one of the tests that fails.
    """
    base = serve_with(lambda situation, thread=():ANSWER)
    lingering = httpx.Client()
    assert lingering.post(f"{base}/ask", json={"situation": "first"}).status_code == 200
    try:
        r = httpx.post(f"{base}/ask", json={"situation": "second"}, timeout=3.0)
        assert r.status_code == 200
    finally:
        lingering.close()


def test_a_response_no_longer_forces_the_connection_shut(serve_with):
    """The `Connection: close` header was a consequence of serialisation, and ADR 0003 said
    not to remove it without removing the single-threading first. That has now happened, so
    the header goes -- a fresh TLS/TCP handshake per question is pure cost once an idle
    connection is harmless."""
    base = serve_with(lambda situation, thread=():ANSWER)
    r = httpx.post(f"{base}/ask", json={"situation": "x"})
    assert r.status_code == 200
    assert r.headers.get("connection", "").lower() != "close"


# -- what issue #31 is actually for ------------------------------------------------------

def test_two_csms_are_answered_at_once_rather_than_one_after_the_other():
    """THE POINT OF THE TICKET.

    Two requests arrive while a slow answer is in flight. Both must be accepted and their
    waits must OVERLAP -- if the server serialised, the second answer would not start until
    the first finished, and the recorded order would be two disjoint pairs.
    """
    order = []

    async def slow(situation, thread=()):
        order.append(f"{situation}:start")
        await asyncio.sleep(0.05)
        order.append(f"{situation}:done")
        return ANSWER

    app = api.build_app(slow)

    async def body():
        async with _drive(app) as c:
            return await asyncio.gather(
                c.post("/ask", json={"situation": "A"}),
                c.post("/ask", json={"situation": "B"}))

    first, second = asyncio.run(body())
    assert first.status_code == second.status_code == 200
    assert order.index("B:start") < order.index("A:done"), order


def test_health_answers_while_a_generation_is_in_flight():
    """THE DEPLOY BLOCKER ADR 0003 NAMED.

    `/health` used to queue behind an in-flight answer, so an ingress with a normal
    health-check timeout marked a healthy process dead during EVERY generation, then
    flapped and killed it. That is why the service could not sit behind a load balancer at
    all, even for a single user.
    """
    answering = asyncio.Event()

    async def slow(situation, thread=()):
        answering.set()
        await asyncio.sleep(0.2)
        return ANSWER

    app = api.build_app(slow)

    async def body():
        async with _drive(app) as c:
            ask = asyncio.create_task(c.post("/ask", json={"situation": "x"}))
            await answering.wait()          # the answer is genuinely in flight
            started = time.monotonic()
            health = await c.get("/health")
            elapsed = time.monotonic() - started
            await ask
            return health, elapsed

    health, elapsed = asyncio.run(body())
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert elapsed < 0.15, f"/health waited {elapsed:.3f}s -- it queued behind the answer"


def test_readiness_is_reported_separately_from_liveness(serve_with):
    """A process that is up but not yet able to answer is NOT a dead one, and an ingress
    has to be able to tell the difference or it will kill something that is merely starting.

    Note what covers the pool load itself: during it the port is not open at all, so a
    check gets connection-refused, which every ingress already reads as "not yet". `/ready`
    is the seam for a state the process can report while listening -- which is what #32's
    queue bound will need."""
    base = serve_with(lambda situation, thread=():ANSWER, ready=lambda: False)
    r = httpx.get(f"{base}/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "starting"
    # Liveness must NOT follow readiness: the process is alive either way.
    assert httpx.get(f"{base}/health").status_code == 200


def test_readiness_is_ok_once_the_service_can_answer(serve_with):
    base = serve_with(lambda situation, thread=():ANSWER, ready=lambda: True)
    r = httpx.get(f"{base}/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_a_service_with_no_readiness_predicate_reports_ready(serve_with):
    """`--ask` and the tests build an app with no predicate. Defaulting to ready keeps the
    endpoint honest for a process that has nothing to wait for."""
    base = serve_with(lambda situation, thread=():ANSWER)
    assert httpx.get(f"{base}/ready").status_code == 200


def test_an_oversized_body_is_refused_without_being_read_into_memory():
    """A runaway client must not be able to make the service read itself out of memory. The
    cap is enforced while the body streams in, not after."""
    app = api.build_app(_as_async(lambda situation, thread=():ANSWER))

    async def body():
        async with _drive(app) as c:
            return await c.post("/ask", content=b'{"situation":"' + b"x" * 200_000 + b'"}',
                                headers={"content-type": "application/json"})

    r = asyncio.run(body())
    assert r.status_code == 400
    assert "too large" in r.json()["error"]


def test_a_request_cannot_select_the_playbook_variant(serve_with):
    """Issue #5: the playbook-augmented prompt is selectable by internal configuration
    ONLY. The HTTP layer reads exactly two fields -- the situation and the thread -- and
    extra keys are not rejected, they are simply never read. This pins that boundary: the
    day someone adds `body.get("playbook")` to the handler, this test fails.

    The THREAD does not widen that channel either (issue #15). A turn forbids unknown keys,
    so a caller cannot smuggle a variant, a prompt or a move list through the one field
    that did grow."""
    seen = []

    def answerer(situation, thread=()):
        seen.append((situation, thread))
        return ANSWER

    base = serve_with(answerer)
    r = httpx.post(f"{base}/ask", json={
        "situation": "cost per hire is too high",
        "playbook": True,
        "use_playbook": True,
        "moves": [{"name": "injected", "criterion": "injected"}],
        "prompt_variant": "playbook_augmented",
    })
    assert r.status_code == 200
    # The answerer received the situation and an empty thread, and nothing else.
    assert seen == [("cost per hire is too high", ())]

    # A variant smuggled inside a thread turn is refused at the boundary, not ignored.
    r = httpx.post(f"{base}/ask", json={
        "situation": "cost per hire is too high",
        "thread": [{"message": "x", "outcome": "answered",
                    "moves": [{"name": "injected", "criterion": "injected"}]}],
    })
    assert r.status_code == 400


# -- the four contract changes the rewrite brought, pinned so they cannot revert ---------

def test_a_query_string_no_longer_defeats_path_matching(serve_with):
    """A CHANGE, and an improvement, but an unpinned one is an accident waiting to be
    undone. The stdlib handler matched on `self.path`, which in BaseHTTPRequestHandler
    INCLUDES the query string -- so `POST /ask?debug=1` was a 404 and `GET /health?x=1`
    was too. ASGI splits the query out of `scope["path"]`, so both now route."""
    base = serve_with(lambda situation, thread=():ANSWER)
    assert httpx.post(f"{base}/ask?debug=1", json={"situation": "x"}).status_code == 200
    assert httpx.get(f"{base}/health?probe=1").status_code == 200


def test_an_unsupported_method_is_a_json_404_not_an_html_error_page(serve_with):
    """The stdlib server answered PUT/OPTIONS with a 501 and an HTML error page. Every
    response this service gives is JSON, and the proxy in front of it parses every body --
    an HTML 501 was the one shape that could reach it and fail to parse."""
    base = serve_with(lambda situation, thread=():ANSWER)
    for request in (httpx.put, httpx.options):
        r = request(f"{base}/ask")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")
        assert r.json() == {"error": "not found"}


def test_a_body_with_no_content_length_is_read_rather_than_called_empty():
    """The stdlib reader trusted `Content-Length` and rejected its absence as an empty
    body. ASGI hands the body over in chunks, so the cap is enforced against what actually
    arrives -- which means a chunked request is now answered instead of refused, AND
    cannot walk past the cap by lying about its length."""
    app = api.build_app(_as_async(lambda situation, thread=():ANSWER))

    async def chunks():
        # An ASYNC generator: httpx refuses a sync one on an AsyncClient.
        yield b'{"situation":'
        yield b' "cost per hire is too high"}'

    async def body():
        async with _drive(app) as c:
            # httpx sends a generator body with Transfer-Encoding: chunked, no length.
            return await c.post("/ask", content=chunks(),
                                headers={"content-type": "application/json"})

    r = asyncio.run(body())
    assert r.status_code == 200
    assert r.json() == ANSWER


# -- shutdown, which a `finally` around serve() cannot be trusted to do -----------------

def test_the_lifespan_shutdown_runs_the_callers_teardown():
    """THE Ctrl-C FIX, at the only layer that can be tested without sending a signal.

    On Ctrl-C, `asyncio.run` cancels the main task and uvicorn re-raises the signal into
    that handler, so the caller's own `finally` is already cancelled when it tries to
    `await gateway.aclose()` -- the client and the Pinecone session leak, and the process
    exits 130. Uvicorn runs this handshake as part of its GRACEFUL shutdown instead, before
    any of that, which is why the teardown is wired here.
    """
    closed = []

    async def on_shutdown():
        closed.append("closed")

    app = api.build_app(_as_async(lambda situation, thread=():ANSWER),
                            on_shutdown=on_shutdown)

    async def body():
        # The lifespan protocol, driven directly: startup, then shutdown.
        sent = []
        events = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]

        async def receive():
            return events.pop(0)

        async def send(message):
            sent.append(message["type"])

        await app({"type": "lifespan"}, receive, send)
        return sent

    sent = asyncio.run(body())
    assert sent == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
    assert closed == ["closed"], "the caller's teardown did not run on shutdown"


def test_a_shutdown_with_no_teardown_registered_still_completes():
    """`--ask` and every test build an app without one. A missing callback must not stall
    the handshake, or uvicorn waits on a shutdown that never completes."""
    app = api.build_app(_as_async(lambda situation, thread=():ANSWER))

    async def body():
        sent = []
        events = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]

        async def receive():
            return events.pop(0)

        async def send(message):
            sent.append(message["type"])

        await app({"type": "lifespan"}, receive, send)
        return sent

    assert asyncio.run(body()) == ["lifespan.startup.complete",
                                   "lifespan.shutdown.complete"]


def test_a_real_uvicorn_run_invokes_the_lifespan_shutdown():
    """The teardown claim, against a REAL server rather than a hand-driven handshake.

    The two tests above prove our lifespan handler calls the callback when the protocol is
    driven by hand. What they cannot prove is the part the fix actually depends on: that
    uvicorn runs that handshake at all on the way down. If it did not, the teardown would
    never fire and the client and Pinecone session would leak on every stop.

    Driven by `should_exit` rather than a signal, deliberately. A real SIGINT cannot be
    delivered to a child process reliably on Windows -- asyncio's proactor loop does not
    reach the Python-level handler in time and the process is killed outright -- so a
    signal-based test here would be testing the platform, not the service. `should_exit` is
    the same graceful path uvicorn takes once it HAS received a signal.
    """
    closed = []

    async def on_shutdown():
        closed.append("closed")

    app = api.build_app(_as_async(lambda situation, thread=():ANSWER),
                            on_shutdown=on_shutdown)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:            # pragma: no cover
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.01)

    # Answer one request first, so this is a shutdown of a server that actually served.
    port = server.servers[0].sockets[0].getsockname()[1]
    assert httpx.post(f"http://127.0.0.1:{port}/ask",
                      json={"situation": "x"}).status_code == 200
    assert closed == [], "the teardown ran before shutdown"

    server.should_exit = True
    thread.join(timeout=10)
    assert not thread.is_alive(), "the server did not stop"
    assert closed == ["closed"], "uvicorn shut down without running the teardown"


def _free_port() -> int:
    """A port nothing is listening on right now.

    `serve()` binds its own socket, so a test cannot hand it `port=0` and then discover
    what it chose. Claiming a port, closing it, and passing the number carries a small race
    with anything else on the machine -- acceptable, and the alternative is adding a
    report-the-bound-port hook to production code purely for this test.
    """
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_serve_itself_answers_two_requests_concurrently():
    """CLOSES THE ONE BLIND SPOT IN THIS FILE.

    Every other concurrency test drives `build_app` -- through ASGITransport, or through a
    uvicorn the FIXTURE configures. None of them touches `api.serve()`, which is the
    only thing production calls, and which is where a re-serialisation would most naturally
    be introduced: `limit_concurrency=1` in its `uvicorn.Config`, a sync wrapper around the
    app, a worker setting. All of that passes every other test in this file.

    So this runs the real `serve()` and asserts overlap through it. Two 0.4s answers must
    complete in well under their serial sum.
    """
    port = _free_port()

    async def slow(situation, thread=()):
        await asyncio.sleep(0.4)
        return ANSWER

    stop = asyncio.Event()

    async def body():
        server = asyncio.create_task(
            api.serve(slow, host="127.0.0.1", port=port))
        try:
            async with httpx.AsyncClient(timeout=20.0) as c:
                # Wait for the socket rather than sleeping a guess.
                deadline = time.monotonic() + 15
                while True:
                    try:
                        if (await c.get(f"http://127.0.0.1:{port}/health")).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() > deadline:      # pragma: no cover
                        raise RuntimeError("serve() never started listening")
                    await asyncio.sleep(0.05)

                started = time.monotonic()
                first, second = await asyncio.gather(
                    c.post(f"http://127.0.0.1:{port}/ask", json={"situation": "A"}),
                    c.post(f"http://127.0.0.1:{port}/ask", json={"situation": "B"}))
                return first, second, time.monotonic() - started
        finally:
            server.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await server

    first, second, elapsed = asyncio.run(body())
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == ANSWER
    # Serial would be >= 0.8s. Generous margin: this is a serialisation check, not a
    # latency benchmark, and a loaded machine must not make it flake.
    assert elapsed < 0.7, (
        f"two 0.4s answers through serve() took {elapsed:.2f}s -- the server serialised "
        f"them")


# -- the bound, the queue and the deadline (issue #32) -----------------------------------
#
# THE NUMBERS HERE ARE TINY ON PURPOSE. The shipped gate answers six at once and queues
# fourteen behind them, so reaching the refusal through HTTP would mean twenty-one
# simultaneous requests to observe one number. A gate of one slot and a one-deep queue
# exercises the identical code paths and makes the arithmetic readable in the assertion.
# The arithmetic ITSELF -- that the depth really is what the deadline can absorb -- is
# pinned against the shipped numbers in test_ask_naren_admission.py.


def _tiny_gate(**kw):
    """One slot, one queued behind it, refuse the third. A long deadline unless a test is
    about the deadline, so a slow stub cannot turn a queueing test into a timeout test.

    25s against a 12.5s answer is the smallest deadline that admits exactly one waiter: the
    budget has to cover the wait AND that caller's own answer, so a one-answer deadline
    queues nobody at all. See admission.total_seconds_for."""
    kw.setdefault("in_flight_limit", 1)
    kw.setdefault("answer_cost", 12.5)
    kw.setdefault("deadline", 25.0)
    return admission.Admission(**kw)


def test_a_third_caller_is_refused_as_busy_rather_than_accepted_and_failed():
    """The whole argument of issue #32 in one assertion.

    Waiting 30 seconds to be told nothing is strictly worse than being told immediately, so
    a request that cannot be served inside the deadline is refused ON ARRIVAL. The timing
    assertion is the load-bearing half: a 429 that arrived after a full deadline would
    satisfy every other check in this file and be the exact behaviour the ticket rejects.
    """
    gate = _tiny_gate()
    assert gate.queue_limit == 1
    release = asyncio.Event()

    async def slow(situation, thread=()):
        await release.wait()
        return ANSWER

    app = api.build_app(slow, gate=gate)

    async def body():
        async with _drive(app) as c:
            first = asyncio.create_task(c.post("/ask", json={"situation": "A"}))
            second = asyncio.create_task(c.post("/ask", json={"situation": "B"}))
            await asyncio.sleep(0.05)              # one in flight, one queued
            started = time.monotonic()
            third = await c.post("/ask", json={"situation": "C"})
            waited = time.monotonic() - started
            release.set()
            await asyncio.gather(first, second)
            return third, waited

    third, waited = asyncio.run(body())
    assert third.status_code == 429
    assert third.json()["outcome"] == "declined"
    assert third.json()["reason"] == api.SERVICE_BUSY
    assert waited < 1.0, f"the refusal took {waited:.2f}s -- it queued before refusing"


def test_the_busy_refusal_says_roughly_how_long():
    """"Busy" alone reads as "broken". The service knows the queue depth, so the estimate
    costs nothing -- and it is the difference between a CSM thinking the tool is down and a
    CSM asking again in a minute. Carried BOTH as prose (which is what gets rendered) and
    as `Retry-After` (for anything reading headers)."""
    gate = _tiny_gate()
    release = asyncio.Event()

    async def slow(situation, thread=()):
        await release.wait()
        return ANSWER

    app = api.build_app(slow, gate=gate)

    async def body():
        async with _drive(app) as c:
            held = [asyncio.create_task(c.post("/ask", json={"situation": n}))
                    for n in "AB"]
            await asyncio.sleep(0.05)
            third = await c.post("/ask", json={"situation": "C"})
            release.set()
            await asyncio.gather(*held)
            return third

    third = asyncio.run(body())
    estimate = third.json()["retry_after_seconds"]
    assert estimate == gate.retry_after_seconds_at(gate.queue_limit + 1)
    assert third.headers["retry-after"] == str(estimate)
    # And the sentence a CSM reads names it, rather than leaving the number to the header.
    assert str(estimate) in third.json()["message"]


def test_a_queued_caller_is_served_rather_than_refused():
    """THE DEFAULT PATH. At this team's load the queue is empty or one deep, so almost
    every caller who waits at all is this one -- and a short wait is invisible. A gate that
    refused rather than queued would make a rejection a routine part of using the tool,
    which is what the ticket was amended to stop."""
    gate = _tiny_gate()
    order = []

    async def slow(situation, thread=()):
        order.append(f"{situation}:start")
        await asyncio.sleep(0.05)
        order.append(f"{situation}:done")
        return ANSWER

    app = api.build_app(slow, gate=gate)

    async def body():
        async with _drive(app) as c:
            return await asyncio.gather(c.post("/ask", json={"situation": "A"}),
                                        c.post("/ask", json={"situation": "B"}))

    first, second = asyncio.run(body())
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == ANSWER

    # SERIALISED, but WHICH ONE WENT FIRST IS NOT ASSERTED. Both are dispatched by one
    # `gather` and each has a body to read before it reaches admission, so nothing promises
    # A is admitted before B; pinning the exact sequence would make this fail for a reason
    # unrelated to the bound. What must hold is that the second one WAITED rather than
    # overlapping or being refused -- and that still fails if the slot is not held, because
    # two concurrent answers interleave to start, start, done, done.
    assert [step.split(":")[1] for step in order] == ["start", "done", "start", "done"],         order
    assert order[0].split(":")[0] == order[1].split(":")[0], order


def test_no_more_than_the_bound_are_answered_at_once():
    """The bound the gateway's shared 8-per-key allowance requires. Over HTTP, because
    that is where over-acceptance happens: the layer below cannot over-accept anything."""
    gate = _tiny_gate(in_flight_limit=2, deadline=100.0)
    live = 0
    peak = 0

    async def slow(situation, thread=()):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.05)
        live -= 1
        return ANSWER

    app = api.build_app(slow, gate=gate)

    async def body():
        async with _drive(app) as c:
            return await asyncio.gather(*(c.post("/ask", json={"situation": str(n)})
                                          for n in range(8)))

    results = asyncio.run(body())
    assert [r.status_code for r in results] == [200] * 8
    assert peak == 2, f"{peak} answers were in flight against a bound of 2"


def test_the_deadline_fires_rather_than_letting_a_caller_hang():
    """The only timeout before this was the gateway's 120s, and no CSM waits 120s. 504 and
    its own reason code: this is neither a fault (nothing broke) nor a busy refusal
    (this one was admitted), and reporting it as either would hide it."""
    gate = _tiny_gate(deadline=0.05)

    async def far_too_slow(situation, thread=()):
        await asyncio.sleep(30)
        return ANSWER                          # pragma: no cover -- never reached

    app = api.build_app(far_too_slow, gate=gate)

    async def body():
        async with _drive(app) as c:
            started = time.monotonic()
            r = await c.post("/ask", json={"situation": "x"})
            return r, time.monotonic() - started

    r, elapsed = asyncio.run(body())
    assert r.status_code == 504
    assert r.json()["reason"] == api.DEADLINE_EXCEEDED
    assert r.json()["outcome"] == "declined"
    assert elapsed < 5, f"took {elapsed:.1f}s -- the deadline did not fire"
    assert gate.deadlines_missed == 1
    # And the slot went back, rather than being lost with the abandoned answer.
    assert gate.in_flight == 0


def test_a_timeout_from_underneath_is_a_fault_and_not_our_deadline():
    """`asyncio.TimeoutError` IS the builtin `TimeoutError` in 3.11, so anything below --
    a gateway socket timeout, say -- raises the same class our own budget does. Reporting
    that as `deadline_exceeded` would file a fault under capacity, which is the conflation
    this whole ticket exists to prevent, one layer further down."""
    gate = _tiny_gate(deadline=100.0)

    async def blows_up(situation, thread=()):
        raise TimeoutError("the gateway socket gave up")

    app = api.build_app(blows_up, gate=gate)

    async def body():
        async with _drive(app) as c:
            return await c.post("/ask", json={"situation": "x"})

    r = asyncio.run(body())
    assert r.status_code == 503
    assert r.json()["reason"] == api.SERVICE_ERROR
    assert gate.deadlines_missed == 0, "someone else's timeout was counted as ours"


def test_busy_is_distinguishable_from_a_fault_and_from_a_no_match_decline():
    """THE MAIN HAZARD IN ISSUE #32, asserted in one place so it cannot drift apart.

    A capacity problem wearing a quality problem's clothes would make the tool look like it
    was working perfectly and simply declining a lot -- and the decline-rate reads would
    quietly be measuring load. So all three differ in the status an operator watches AND in
    the reason code an engineer greps, and each of the three is checkable without the
    other two.
    """
    no_match = {"outcome": "declined", "reason": "no_close_match",
                "message": "Nothing in Naren's calls is close enough."}

    gate = _tiny_gate()
    release = asyncio.Event()

    async def answerer(situation, thread=()):
        if situation == "fault":
            raise RuntimeError("the answerer blew up")
        if situation == "hold":
            await release.wait()
        return no_match

    app = api.build_app(answerer, gate=gate)

    async def body():
        async with _drive(app) as c:
            declined = await c.post("/ask", json={"situation": "nothing close"})
            fault = await c.post("/ask", json={"situation": "fault"})
            held = [asyncio.create_task(c.post("/ask", json={"situation": "hold"}))
                    for _ in range(2)]
            await asyncio.sleep(0.05)
            busy = await c.post("/ask", json={"situation": "third"})
            release.set()
            await asyncio.gather(*held)
            return declined, fault, busy

    declined, fault, busy = asyncio.run(body())

    assert (declined.status_code, declined.json()["reason"]) == (200, "no_close_match")
    assert (fault.status_code, fault.json()["reason"]) == (503, api.SERVICE_ERROR)
    assert (busy.status_code, busy.json()["reason"]) == (429, api.SERVICE_BUSY)

    statuses = {declined.status_code, fault.status_code, busy.status_code}
    reasons = {declined.json()["reason"], fault.json()["reason"], busy.json()["reason"]}
    assert len(statuses) == len(reasons) == 3
    # And the words a CSM reads differ too, which is the half no monitor checks.
    assert len({declined.json()["message"], fault.json()["message"],
                busy.json()["message"]}) == 3


def test_ready_reports_saturation_and_the_counts_behind_it():
    """What `/ready` had no state to report before (issue #31 left it always-ready).

    Note what saturation is NOT: every slot busy is the service working, because a busy
    slot means somebody is being answered. It is the QUEUE behind them being as deep as the
    deadline can absorb -- the point past which accepting anyone is a promise we cannot
    keep."""
    gate = _tiny_gate()
    release = asyncio.Event()

    async def slow(situation, thread=()):
        await release.wait()
        return ANSWER

    app = api.build_app(slow, gate=gate)

    async def body():
        async with _drive(app) as c:
            calm = await c.get("/ready")
            held = [asyncio.create_task(c.post("/ask", json={"situation": n}))
                    for n in "AB"]
            await asyncio.sleep(0.05)
            saturated = await c.get("/ready")
            alive = await c.get("/health")
            release.set()
            await asyncio.gather(*held)
            drained = await c.get("/ready")
            return calm, saturated, alive, drained

    calm, saturated, alive, drained = asyncio.run(body())

    assert (calm.status_code, calm.json()["status"]) == (200, "ready")
    assert (saturated.status_code, saturated.json()["status"]) == (503, "saturated")
    # LIVENESS MUST NOT FOLLOW IT. A saturated process is healthy and busy; an ingress that
    # cannot tell the difference restarts the thing that is working hardest.
    assert alive.status_code == 200
    assert alive.json() == {"status": "ok"}
    assert (drained.status_code, drained.json()["status"]) == (200, "ready")

    # The counts an operator reads to decide whether this API key's allowance is still
    # enough. The peaks, not the instantaneous numbers: the interesting moment is never the
    # one anybody is watching.
    body_at_peak = saturated.json()
    assert body_at_peak["in_flight"] == 1
    assert body_at_peak["in_flight_limit"] == 1
    assert body_at_peak["queued"] == 1
    assert body_at_peak["queue_limit"] == 1
    assert drained.json()["peak_in_flight"] == 1
    assert drained.json()["peak_queued"] == 1


def test_a_malformed_request_costs_nobody_a_slot():
    """Validated before admission, so a bad body cannot queue anyone behind a request that
    was never going to be answered -- nor get itself refused as "busy" for it."""
    gate = _tiny_gate()
    app = api.build_app(_as_async(lambda situation, thread=(): ANSWER), gate=gate)

    async def body():
        async with _drive(app) as c:
            bad = await c.post("/ask", json={"situation": "   "})
            return bad, await c.get("/ready")

    bad, ready = asyncio.run(body())
    assert bad.status_code == 400
    assert ready.json()["peak_in_flight"] == 0
    assert ready.json()["refused"] == 0


def test_an_abandoned_request_gives_its_slot_straight_back(serve_with):
    """A CSM closing the tab must not leave a colleague queued behind an answer nobody will
    read. Async is what makes this expressible: the threaded design had no way to notice a
    vanished caller and no way to stop the work.

    OVER A REAL SOCKET, and it has to be -- `httpx.ASGITransport` only reports
    `http.disconnect` after the response is complete, so an in-process client CANNOT
    abandon a request. Nothing below this layer can test this.
    """
    gate = _tiny_gate(in_flight_limit=1, deadline=100.0)
    answering = threading.Event()

    async def slow(situation, thread=()):
        answering.set()
        await asyncio.sleep(20)
        return ANSWER                          # pragma: no cover -- never reached

    base = serve_with(slow, gate=gate)
    host, port = base.removeprefix("http://").split(":")

    raw = socket.create_connection((host, int(port)))
    payload = b'{"situation":"a CSM who is about to close the tab"}'
    raw.sendall(b"POST /ask HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload)
    assert answering.wait(timeout=10), "the answer never started"
    assert httpx.get(f"{base}/ready").json()["in_flight"] == 1

    raw.close()

    # The answer would have run for 20 more seconds. The slot must come back now, not then.
    deadline = time.monotonic() + 5
    while httpx.get(f"{base}/ready").json()["in_flight"] != 0:
        assert time.monotonic() < deadline, (
            "the slot was still held 5s after the caller vanished -- an abandoned request "
            "is still consuming capacity")
        time.sleep(0.05)


def test_healthz_is_the_same_liveness_answer_as_health(serve_with):
    """THE PROBE SPELLING MUST NOT DECIDE WHETHER THE POD LIVES.

    This service's own contract is `/health`, and the audit harnesses poll that. The Joveo
    applib template this repo is built from probes `/healthz`. A deployment that guessed the
    other spelling would get a 404 from a perfectly healthy process, read it as dead, and
    restart it forever -- the same failure mode ADR 0003 named, arriving through the front
    door instead. Aliasing costs one tuple entry; this is what keeps it aliased.
    """
    called = []
    base = serve_with(lambda situation, thread=():called.append(situation) or ANSWER)

    healthz = httpx.get(f"{base}/healthz")
    assert healthz.status_code == 200
    assert healthz.json() == httpx.get(f"{base}/health").json()
    # Liveness, so it must not have cost a generation either.
    assert called == []


# -- the FastAPI conversion (2026-09-29): the schema, and the choices that kept the contract

def _openapi():
    app = api.build_app(_as_async(lambda situation, thread=(): ANSWER))

    async def body():
        async with _drive(app) as c:
            return (await c.get("/openapi.json")).json(), (await c.get("/docs")).status_code

    return asyncio.run(body())


def test_the_contract_is_published_as_a_schema():
    """The point of the conversion: `/docs` shows the request model and every outcome, so
    the contract is readable without this file or `types.ts`."""
    schema, docs_status = _openapi()
    assert docs_status == 200
    ask = schema["paths"]["/ask"]["post"]
    assert ask["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AskRequest"}
    assert set(schema["components"]["schemas"]["AskRequest"]["required"]) == {"situation"}
    for outcome in ("Answered", "Declined", "Clarify", "Discovery", "CoverageCheck"):
        assert outcome in schema["components"]["schemas"]
    assert "Retry-After" in ask["responses"]["429"]["headers"]


def test_the_schema_promises_exactly_the_statuses_the_service_sends():
    """No 422: a malformed body is a 400 here, and a schema advertising a status the service
    cannot produce is exactly the drift it exists to prevent."""
    schema, _ = _openapi()
    assert sorted(schema["paths"]["/ask"]["post"]["responses"]) == [
        "200", "400", "429", "503", "504"]
    assert "HTTPValidationError" not in schema["components"]["schemas"]


def test_a_validation_failure_is_the_services_own_400_not_fastapis_422(serve_with):
    """The proxy forwards this 400 as its own and does not record it (#37). FastAPI's
    default -- a 422 with `{"detail": [...]}` -- would be a third status meaning the same
    thing, in a shape nothing downstream reads."""
    base = serve_with(lambda situation, thread=(): ANSWER)
    for body in ({"situation": 5}, {"situation": "x", "thread": "not a list"}, [1]):
        r = httpx.post(f"{base}/ask", json=body)
        assert r.status_code == 400, body
        assert set(r.json()) == {"error"}, body


def test_a_chunked_body_cannot_walk_past_the_cap():
    """The other half of the no-Content-Length test: with no declared length to refuse, the
    cap is enforced against what actually arrives -- before FastAPI buffers it."""
    app = api.build_app(_as_async(lambda situation, thread=(): ANSWER))

    async def chunks():
        yield b'{"situation":"'
        for _ in range(10):
            yield b"x" * 10_000
        yield b'"}'

    async def body():
        async with _drive(app) as c:
            return await c.post("/ask", content=chunks(),
                                headers={"content-type": "application/json"})

    r = asyncio.run(body())
    assert r.status_code == 400
    assert "too large" in r.json()["error"]


def test_the_services_own_declines_match_the_published_schema():
    """Busy, deadline and fault are the three responses THIS layer writes, so they are the
    three the published schema can be held to."""
    from pydantic import TypeAdapter
    from ask_naren.api.models import AskResponse

    for refusal in (api.ServiceBusy(7), api.DeadlineExceeded(), api.ServiceFault()):
        TypeAdapter(AskResponse).validate_python(refusal.body)
    assert api.ServiceBusy(7).body["retry_after_seconds"] == 7
    assert api.ServiceBusy(7).headers == {"Retry-After": "7"}


def test_a_trailing_slash_is_the_same_route_not_a_redirect(serve_with):
    """A redirected POST arrives as a GET and loses its body -- so `/ask/` is `/ask`."""
    base = serve_with(lambda situation, thread=(): ANSWER)
    r = httpx.post(f"{base}/ask/", json={"situation": "x"})
    assert r.status_code == 200
    assert r.json() == ANSWER
    assert httpx.get(f"{base}/health/").json() == {"status": "ok"}
