"""`shared/gateway.py`'s ASYNC transport -- issue #28.

Network-free: every test drives a custom `httpx.AsyncBaseTransport` that can await, so
concurrency is genuinely observable rather than simulated.

NO `pytest-asyncio`. This venv has no pip, and the plugin is not needed: each test runs its
coroutine through `asyncio.run`, which also gives every test a FRESH EVENT LOOP -- which
matters here, because the admission gate is per-loop by design (see `_async_gate`).

WHAT THESE TESTS ARE FOR. The measured fact behind the whole ticket is that the gateway
allows 8 requests in flight PER KEY and that budget is SHARED between /chat/completions and
/embeddings (measured 2026-09-10: 6 chat + 6 embed fired together took 3
`max_parallel_requests` rejections). The synchronous client's semaphore guards only
`embed_one`, so chat is entirely unpaced. These tests pin the async twin's admission
control at the one place both endpoints pass through.
"""
import asyncio
import json

import httpx
import pytest

from shared import gateway as gw

BASE = "https://gw.test"
KEY = "test-key"

CHAT_OK = {"choices": [{"message": {"content": json.dumps({"a": 1})}}],
           "usage": {"total_tokens": 7}, "model": "served-model-x"}


def _embed_ok(n=1, dims=gw.EMBED_DIMENSIONS):
    return {"data": [{"index": i, "embedding": [0.1] * dims} for i in range(n)]}


class _Transport(httpx.AsyncBaseTransport):
    """An async transport that records what happened and can hold requests open.

    `handler(request, n)` returns an `httpx.Response`, or raises. `n` is the 1-based call
    number, so a test can script "fail once, then succeed" without a mutable closure.

    Tracks `peak` in-flight and the `starts` order, which is how the admission tests observe
    behaviour instead of poking at semaphore internals.
    """

    def __init__(self, handler, hold: float = 0.0):
        self._handler = handler
        self._hold = hold
        self.calls = 0
        self.in_flight = 0
        self.peak = 0
        self.starts: list[str] = []
        self.bodies: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        n = self.calls
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        self.starts.append(request.url.path)
        try:
            self.bodies.append(json.loads(request.content or b"{}"))
        except json.JSONDecodeError:
            self.bodies.append({})
        try:
            if self._hold:
                await asyncio.sleep(self._hold)
            return self._handler(request, n)
        finally:
            self.in_flight -= 1


def _client(transport, **kw):
    return gw.AsyncGatewayClient(base_url=BASE, api_key=KEY, transport=transport, **kw)


@pytest.fixture
def no_waiting(monkeypatch):
    """Records every backoff the transport asks for, and yields instead of sleeping.

    Patched at the module's own `_asleep` indirection rather than at `asyncio.sleep`, so a
    test cannot accidentally slow the whole suite down by a retry ladder, AND -- the point --
    an implementation that used a BLOCKING sleep would never call this, leaving `waits`
    empty and failing the tests that assert on it.
    """
    waits: list[float] = []

    async def fake(seconds):
        waits.append(seconds)
        await asyncio.sleep(0)

    monkeypatch.setattr(gw, "_asleep", fake)
    return waits


# -- the measured finding: ONE budget, both endpoints -------------------------------------

def test_chat_and_embeddings_draw_from_one_admission_limit(monkeypatch):
    """THE reason this ticket exists. Measured 2026-09-10: the gateway's 8-in-flight cap is
    shared across both endpoints, and the sync client guards only the embedding call. Six
    chat plus six embed must never put more than the bound in flight."""
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 3)

    def handler(request, n):
        if request.url.path == "/embeddings":
            return httpx.Response(200, json=_embed_ok())
        return httpx.Response(200, json=CHAT_OK)

    transport = _Transport(handler, hold=0.02)

    async def body():
        async with _client(transport) as c:
            await asyncio.gather(
                *(c.chat_json("p") for _ in range(6)),
                *(c.embed_one("t") for _ in range(6)))

    asyncio.run(body())
    assert transport.calls == 12
    assert transport.peak <= 3, f"{transport.peak} in flight against a bound of 3"


def test_the_limit_admits_up_to_its_bound_and_makes_the_next_caller_wait(monkeypatch):
    """Waits, not fails. A caller past the bound is queued locally rather than sent to the
    gateway to be rejected -- a rejected request still spends quota."""
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 4)
    transport = _Transport(lambda r, n: httpx.Response(200, json=CHAT_OK), hold=0.02)

    async def body():
        async with _client(transport) as c:
            return await asyncio.gather(*(c.chat_json("p") for _ in range(9)))

    results = asyncio.run(body())
    assert len(results) == 9, "every caller is served eventually"
    assert transport.peak == 4, f"expected exactly the bound in flight, saw {transport.peak}"


def test_a_backing_off_request_gives_its_slot_back(monkeypatch):
    """The slot covers a REQUEST, not a whole retry ladder.

    A request sleeping out a backoff is not in flight at the gateway, so it must not hold a
    slot that a waiting sibling could use. Bound of 1 and two callers: the second caller's
    attempt must land BETWEEN the first caller's two attempts.

    The first version of this test asserted the opposite -- copied from the sync client,
    where the semaphore sits outside `_post` and cannot be released between attempts. See
    the next test for what that costs.
    """
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 1)
    order: list[str] = []

    async def slow_backoff(seconds):
        await asyncio.sleep(0.03)

    monkeypatch.setattr(gw, "_asleep", slow_backoff)

    def handler(request, n):
        label = json.loads(request.content)["messages"][0]["content"]
        order.append(f"{label}#{n}")
        if label == "first" and n == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json=CHAT_OK)

    transport = _Transport(handler)

    async def body():
        async with _client(transport) as c:
            first = asyncio.create_task(c.chat_json("first"))
            await asyncio.sleep(0.005)      # let `first` take the only slot
            second = asyncio.create_task(c.chat_json("second"))
            await asyncio.gather(first, second)

    asyncio.run(body())
    assert order == ["first#1", "second#2", "first#3"], order
    assert transport.peak == 1, "the bound must still hold while the slot changes hands"


def test_an_embedding_quota_stall_does_not_block_generation(monkeypatch):
    """THE DEFECT THAT HOLDING A SLOT ACROSS THE LADDER CAUSED, found in review of #28.

    A quota rejection escalates to 15/30/45s and `penalise` deliberately synchronises every
    sibling into that wait. Chat is not subject to the per-window limit at all -- but it
    does need a slot. Holding the slot through the ladder therefore let a purely EMBEDDING
    quota event freeze every CSM's generation for up to ~90s, which is the exact freeze this
    module exists to prevent. The sync client cannot exhibit it because its semaphore never
    covers chat.
    """
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 1)
    monkeypatch.setattr(gw, "EMBED_PER_MINUTE", 6000)   # pacing out of the way
    events: list[str] = []

    async def backoff(seconds):
        events.append(f"embed backs off {seconds:.0f}s")
        await asyncio.sleep(0.03)

    monkeypatch.setattr(gw, "_asleep", backoff)

    def handler(request, n):
        if request.url.path == "/embeddings":
            if n == 1:
                return httpx.Response(
                    429, text="Limit type: requests. Current limit: 150, Remaining: 0")
            return httpx.Response(200, json=_embed_ok())
        events.append("chat served")
        return httpx.Response(200, json=CHAT_OK)

    transport = _Transport(handler)

    async def body():
        async with _client(transport) as c:
            emb = asyncio.create_task(c.embed_one("t"))
            await asyncio.sleep(0.005)      # let the embedding take the only slot
            chat = asyncio.create_task(c.chat_json("p"))
            await asyncio.gather(emb, chat)

    asyncio.run(body())
    assert events[0].startswith("embed backs off"), events
    assert events[1] == "chat served", \
        f"generation waited for the embedding quota window: {events}"


def test_the_bound_holds_across_a_storm_of_retries(monkeypatch):
    """Releasing the slot per attempt must not let the in-flight count drift above the
    bound: a retry has to queue again like any other caller."""
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 3)

    def handler(request, n):
        # Every third attempt fails, so retries and fresh calls interleave constantly.
        if n % 3 == 0:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json=CHAT_OK)

    transport = _Transport(handler, hold=0.005)

    async def body():
        async with _client(transport) as c:
            await asyncio.gather(*(c.chat_json("p") for _ in range(12)))

    asyncio.run(body())
    assert transport.peak <= 3, f"{transport.peak} in flight against a bound of 3"


def test_a_failed_call_returns_its_slot(monkeypatch, no_waiting):
    """A leaked slot is the worst failure this module has: permanent, cumulative capacity
    loss ending in a total outage that looks like the gateway being slow.

    Bound of 1, so a leak makes the second call hang forever -- bounded by `wait_for` here
    so the failure is a clear assertion rather than a hung suite.
    """
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 1)

    def handler(request, n):
        if n == 1:
            return httpx.Response(400, text="bad model")      # hard failure, no retry
        if n == 2:
            raise httpx.ReadError("dropped")                  # exception path
        return httpx.Response(200, json=CHAT_OK)

    transport = _Transport(handler)

    async def body():
        async with _client(transport, max_retries=1) as c:
            for expected in ("400", "after 1 attempts"):
                with pytest.raises(gw.GatewayError, match=expected):
                    await asyncio.wait_for(c.chat_json("p"), timeout=1.0)
            return await asyncio.wait_for(c.chat_json("p"), timeout=1.0)

    parsed, _meta = asyncio.run(body())
    assert parsed == {"a": 1}, "the slot survived two different failure paths"


# -- awaited, not blocked -----------------------------------------------------------------

def test_a_backoff_lets_unrelated_work_continue(monkeypatch):
    """A blocking sleep in a coroutine freezes every other CSM's request in the process.
    While one call is backing off, an unrelated task must keep making progress.

    The competing task yields with `sleep(0)` rather than ticking on a wall-clock interval.
    An earlier version slept 0.005s per tick and expected more than 3 ticks inside a 0.05s
    backoff, which is ~10 when the machine is idle and FEWER THAN 4 under full-suite load --
    it failed once that way. Counting yields instead of elapsed time discriminates far more
    sharply and does not depend on scheduling latency at all: a blocking sleep yields
    exactly zero, an awaited one yields hundreds.
    """
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 4)
    ticks = 0

    async def slow_backoff(seconds):
        await asyncio.sleep(0.05)

    monkeypatch.setattr(gw, "_asleep", slow_backoff)

    def handler(request, n):
        return httpx.Response(503, text="unavailable") if n == 1 \
            else httpx.Response(200, json=CHAT_OK)

    transport = _Transport(handler)

    async def counter():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0)

    async def body():
        async with _client(transport) as c:
            spin = asyncio.create_task(counter())
            await c.chat_json("p")
            spin.cancel()

    asyncio.run(body())
    assert ticks > 20, f"only {ticks} yields -- the backoff blocked the event loop"


# -- the two rejections are not the same thing --------------------------------------------

def test_a_quota_rejection_paces_the_shared_bucket(monkeypatch, no_waiting):
    """A quota rejection needs a window-length wait AND must slow every sibling: the limit
    is per key, so the others are about to be rejected too."""
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 4)

    def handler(request, n):
        if n == 1:
            return httpx.Response(429, text="Limit type: requests. Current limit: 150")
        return httpx.Response(200, json=_embed_ok())

    transport = _Transport(handler)

    async def body():
        async with _client(transport) as c:
            await c.embed_one("t")          # takes the rejection and the penalty
            await c.embed_one("t")          # a SIBLING, which must inherit the penalty

    asyncio.run(body())
    # Observed through pacing rather than by reading `_next`: the first wait is the retry
    # ladder, the second is the next caller being held back by the penalised bucket. Normal
    # pacing at the default rate is well under a second, so a second long wait can only
    # have come from `penalise`.
    assert len(no_waiting) >= 2, f"expected a retry wait and a paced sibling: {no_waiting}"
    assert no_waiting[0] >= 15.0, f"quota retry wait was {no_waiting[0]}"
    assert no_waiting[1] >= 10.0, \
        f"the sibling waited only {no_waiting[1]:.2f}s -- that is pacing, not a penalty"


def test_a_concurrency_rejection_waits_briefly_and_does_not_pace_the_bucket(
        monkeypatch, no_waiting):
    """It clears the moment a sibling finishes, so it wants a SHORT wait. Slowing the whole
    key down does not create a free parallel slot."""
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 4)

    def handler(request, n):
        if n == 1:
            return httpx.Response(
                429, text="Limit type: max_parallel_requests. Current limit: 8, Remaining: 0")
        if request.url.path == "/embeddings":
            return httpx.Response(200, json=_embed_ok())
        return httpx.Response(200, json=CHAT_OK)

    monkeypatch.setattr(gw, "EMBED_PER_MINUTE", 6000)   # pacing interval ~0.01s
    transport = _Transport(handler)

    async def body():
        async with _client(transport) as c:
            await c.chat_json("p")          # takes the concurrency rejection
            await c.embed_one("t")          # the bucket's next customer

    asyncio.run(body())
    assert no_waiting[0] < 15.0, f"a concurrency rejection took a quota wait: {no_waiting}"
    # Observed through the bucket's next customer rather than by reading `_next`: had the
    # rejection penalised the bucket, this embedding would have been held back by the
    # penalty. Slowing the key down creates no parallel slot, so it must not.
    assert all(w < 1.0 for w in no_waiting[1:]), \
        f"a concurrency rejection paced the shared bucket: {no_waiting}"


def test_sibling_backoffs_are_jittered_apart(monkeypatch, no_waiting):
    """The synchronous jitter derives from the THREAD identity, which is one constant with a
    single event loop -- every sibling would then retry in lockstep and reproduce exactly
    the collision the jitter exists to prevent."""
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 8)

    def handler(request, n):
        if n <= 4:
            return httpx.Response(429, text="Limit type: max_parallel_requests")
        return httpx.Response(200, json=CHAT_OK)

    transport = _Transport(handler)

    async def body():
        async with _client(transport) as c:
            await asyncio.gather(*(c.chat_json("p") for _ in range(4)))

    asyncio.run(body())
    assert len(set(no_waiting)) > 1, f"all four siblings waited the same: {no_waiting}"


# -- retry classification, unchanged from the sync client ---------------------------------

def test_a_request_that_is_simply_wrong_is_not_retried(no_waiting):
    """A 4xx that is not a rate limit means the request is malformed. Retrying it wastes the
    same call four times."""
    transport = _Transport(lambda r, n: httpx.Response(400, text="bad model"))

    async def body():
        async with _client(transport) as c:
            await c.chat_json("p")

    with pytest.raises(gw.GatewayError, match="400"):
        asyncio.run(body())
    assert transport.calls == 1


def test_a_transport_drop_is_retried_by_type_not_by_message(no_waiting):
    """CLAUDE.md records the same fix in gemma.py: socket-layer drops phrase themselves too
    many ways ("_ssl.c:2580") for a marker list to keep up."""
    def handler(request, n):
        if n == 1:
            raise httpx.ReadError("_ssl.c:2580 something opaque")
        return httpx.Response(200, json=CHAT_OK)

    transport = _Transport(handler)

    async def body():
        async with _client(transport) as c:
            return await c.chat_json("p")

    parsed, _meta = asyncio.run(body())
    assert parsed == {"a": 1}
    assert transport.calls == 2


def test_exhausting_every_attempt_raises_with_the_last_error(no_waiting):
    transport = _Transport(lambda r, n: httpx.Response(503, text="unavailable"))

    async def body():
        async with _client(transport, max_retries=3) as c:
            await c.chat_json("p")

    with pytest.raises(gw.GatewayError, match="after 3 attempts"):
        asyncio.run(body())
    assert transport.calls == 3


# -- the chat contract, matching the sync client ------------------------------------------

def test_chat_returns_parsed_json_and_reports_which_model_actually_answered():
    transport = _Transport(lambda r, n: httpx.Response(200, json=CHAT_OK))

    async def body():
        async with _client(transport) as c:
            return await c.chat_json("p")

    parsed, meta = asyncio.run(body())
    assert parsed == {"a": 1}
    assert meta["total_tokens"] == 7
    assert meta["served_model"] == "served-model-x", \
        "the response reports which model answered after any fallback"


def test_optional_request_knobs_ride_along_only_when_asked():
    """Default None/False keeps a request body BYTE-IDENTICAL to the sync client's. Ask
    Naren's answering prompts are frozen against a measured accuracy number (ADR 0001), so
    a changed body could move what the model returns."""
    transport = _Transport(lambda r, n: httpx.Response(200, json=CHAT_OK))

    async def body():
        async with _client(transport) as c:
            await c.chat_json("p")
            await c.chat_json("p", no_cache=True, reasoning_effort="low",
                              system="be terse")

    asyncio.run(body())
    plain, loaded = transport.bodies
    assert "cache" not in plain and "reasoning_effort" not in plain
    assert plain["messages"] == [{"role": "user", "content": "p"}]
    assert loaded["cache"] == {"no-cache": True}
    # `cache.no-cache` ALONE STOPPED BYPASSING THE GATEWAY CACHE (measured 2026-09-28: 1 distinct
    # text in 3 at temperature 1.0, repeats in 1.3s). `caching: false` does bypass it (3/3
    # distinct, full latency each), so no_cache must send it.
    assert loaded["caching"] is False
    assert "caching" not in plain
    assert loaded["reasoning_effort"] == "low"
    assert loaded["messages"][0] == {"role": "system", "content": "be terse"}


def test_an_empty_completion_is_an_error_not_an_empty_answer():
    transport = _Transport(lambda r, n: httpx.Response(
        200, json={"choices": [{"message": {"content": "  "}}]}))

    async def body():
        async with _client(transport) as c:
            await c.chat_json("p")

    with pytest.raises(gw.GatewayError, match="empty completion"):
        asyncio.run(body())


# -- embeddings: the collapse hazard survives the port ------------------------------------

def test_one_text_per_embedding_request():
    """NEVER BATCH THIS ENDPOINT. /embeddings intermittently returns fewer vectors than
    inputs at HTTP 200 with no warning."""
    transport = _Transport(lambda r, n: httpx.Response(200, json=_embed_ok()))

    async def body():
        async with _client(transport) as c:
            await c.embed("a b c".split())

    asyncio.run(body())
    assert transport.calls == 3
    assert all(len(b["input"]) == 1 for b in transport.bodies)


def test_a_collapsed_embedding_response_is_caught_rather_than_mis_attributed():
    """The count assertion is the entire point: it is the only thing standing between a
    silent collapse and vectors attributed to the wrong text."""
    transport = _Transport(lambda r, n: httpx.Response(200, json=_embed_ok(n=0)))

    async def body():
        async with _client(transport) as c:
            await c.embed_one("t")

    with pytest.raises(gw.GatewayError, match="collapsed"):
        asyncio.run(body())


def test_a_wrong_width_vector_is_rejected():
    transport = _Transport(lambda r, n: httpx.Response(200, json=_embed_ok(dims=768)))

    async def body():
        async with _client(transport) as c:
            await c.embed_one("t")

    with pytest.raises(gw.GatewayError, match="768"):
        asyncio.run(body())


def test_embedding_order_is_preserved_under_concurrency(monkeypatch):
    """`embed` fans out, so the result must be reassembled by position rather than by
    completion order."""
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 4)

    def handler(request, n):
        text = json.loads(request.content)["input"][0]
        return httpx.Response(200, json={
            "data": [{"index": 0, "embedding": [float(text)] * gw.EMBED_DIMENSIONS}]})

    # Later texts answer sooner, so a naive gather-and-append would scramble them.
    transport = _Transport(handler)

    async def body():
        async with _client(transport) as c:
            return await c.embed([str(i) for i in range(8)])

    got = asyncio.run(body())
    assert [v[0] for v in got] == [float(i) for i in range(8)]


def test_embeddings_are_paced_against_the_per_window_quota(monkeypatch, no_waiting):
    """The 150-requests-per-window ceiling is an EMBEDDING limit and still applies. The
    parallel bound alone is not enough -- it happily starts a full bound of requests inside
    one interval."""
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 8)
    monkeypatch.setattr(gw, "EMBED_PER_MINUTE", 60)      # one per second, easy to assert
    transport = _Transport(lambda r, n: httpx.Response(200, json=_embed_ok()))

    async def body():
        async with _client(transport) as c:
            await c.embed(["a", "b", "c"])

    asyncio.run(body())
    paced = [w for w in no_waiting if w > 0]
    assert len(paced) >= 2, f"expected the bucket to pace later calls, waits={no_waiting}"


def test_chat_is_not_paced_by_the_embedding_quota(monkeypatch, no_waiting):
    """The per-window ceiling was measured on gemini-embedding-2. Pacing chat with it would
    throttle generation for a limit it is not subject to -- the SHARED limit is the parallel
    one, and that is enforced separately."""
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 8)
    monkeypatch.setattr(gw, "EMBED_PER_MINUTE", 60)
    transport = _Transport(lambda r, n: httpx.Response(200, json=CHAT_OK))

    async def body():
        async with _client(transport) as c:
            await asyncio.gather(*(c.chat_json("p") for _ in range(4)))

    asyncio.run(body())
    assert not [w for w in no_waiting if w > 0], f"chat was paced: {no_waiting}"


# -- construction -------------------------------------------------------------------------

@pytest.mark.parametrize("given", ["https://gw.test/", "https://gw.test/v1",
                                   "https://gw.test/v1/"])
def test_a_trailing_slash_or_a_helpful_v1_is_normalised_away(given):
    """Both break this gateway, and a `/v1` segment does not 404 -- it connect-times-out, so
    the symptom is a 20-second hang rather than an error."""
    c = gw.AsyncGatewayClient(base_url=given, api_key=KEY,
                              transport=_Transport(lambda r, n: httpx.Response(200)))
    assert c.base_url == "https://gw.test"


def test_missing_credentials_say_where_they_belong(monkeypatch):
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    monkeypatch.delenv("LLM_GATEWAY_KEY", raising=False)
    with pytest.raises(gw.GatewayError, match="Brain/.env"):
        gw.AsyncGatewayClient()


def test_http2_reaches_the_real_client(monkeypatch):
    """Measured 2026-09-10: this gateway negotiates HTTP/2, so concurrent calls can
    multiplex over ONE connection instead of opening a socket each.

    Asserts on what is handed to httpx, not on the echoed `http2` attribute. The first
    version of this test checked the attribute, which is copied straight from the argument
    -- and because injecting a transport skips the `http2` kwarg entirely, deleting that
    line would have left the test green with multiplexing silently off. The live check is
    what proves negotiation actually happens.
    """
    seen: list[dict] = []
    real = httpx.AsyncClient

    class _Spy(real):
        def __init__(self, **kw):
            seen.append(kw)
            super().__init__(**kw)

    monkeypatch.setattr(httpx, "AsyncClient", _Spy)

    gw.AsyncGatewayClient(base_url=BASE, api_key=KEY)
    assert seen[-1]["http2"] is True

    gw.AsyncGatewayClient(base_url=BASE, api_key=KEY, http2=False)
    assert seen[-1]["http2"] is False

    # With a transport injected, http2 is not passed at all -- httpx would ignore it, and
    # passing both would imply a choice that is not being made.
    gw.AsyncGatewayClient(base_url=BASE, api_key=KEY,
                          transport=_Transport(lambda r, n: httpx.Response(200)))
    assert "http2" not in seen[-1]
    assert "transport" in seen[-1]


def test_two_clients_in_one_process_share_one_bound(monkeypatch):
    """THE reason the gate is module-level rather than per client. The sync limiter's own
    docstring: two clients in one process must draw from ONE bucket "or they simply race
    each other into the same rejection".

    Asserted through the in-flight count rather than by comparing semaphore identities,
    because the identity is an implementation detail and the bound is the behaviour.
    """
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 2)
    transport = _Transport(lambda r, n: httpx.Response(200, json=CHAT_OK), hold=0.02)

    async def body():
        async with _client(transport) as a, _client(transport) as b:
            await asyncio.gather(*(a.chat_json("p") for _ in range(3)),
                                 *(b.chat_json("p") for _ in range(3)))

    asyncio.run(body())
    assert transport.calls == 6
    assert transport.peak <= 2, \
        f"{transport.peak} in flight -- the two clients did not share the bound"


def test_a_second_event_loop_does_not_inherit_a_dead_gate(monkeypatch):
    """An asyncio primitive binds to the first loop that WAITS on it and raises if awaited
    from another, so a gate must not outlive its loop. Contended on purpose: the
    uncontended fast path never binds, so it would not exercise this at all."""
    monkeypatch.setattr(gw, "GATEWAY_MAX_PARALLEL", 1)
    transport = _Transport(lambda r, n: httpx.Response(200, json=CHAT_OK), hold=0.01)

    async def contended():
        async with _client(transport) as c:
            await asyncio.gather(*(c.chat_json("p") for _ in range(3)))

    asyncio.run(contended())
    asyncio.run(contended())        # RuntimeError here if the gate were reused
    assert transport.calls == 6


@pytest.mark.parametrize("kwargs", [
    {},
    {"no_cache": True},
    {"reasoning_effort": "low"},
    {"system": "be terse"},
    {"model": "gemini-3.6-flash", "temperature": 0.7, "max_tokens": 1024},
    {"schema": {"name": "s", "schema": {"type": "object"}}},
    {"no_cache": True, "reasoning_effort": "medium", "system": "s", "max_tokens": 42},
])
def test_the_two_clients_build_byte_identical_chat_requests(kwargs):
    """The async docstring PROMISES the body matches the sync client's "down to which keys
    are omitted", and explains why it matters: Ask Naren's answering prompts are frozen
    against a measured accuracy number (ADR 0001), so a body differing by one key could
    move what the model returns and quietly invalidate that measurement.

    A promise no test enforces is how the two definitions drift. This is the same
    sync-versus-async agreement check the Pinecone tests make, and it is the reason the
    duplication is acceptable at all.

    Reaches into `_http` on the SYNC client because that client has no transport seam --
    and giving it one would be a change to the path #28 promises not to touch.
    """
    bodies: dict[str, dict] = {}

    def capture(which):
        def handler(request):
            bodies[which] = json.loads(request.content)
            return httpx.Response(200, json=CHAT_OK)
        return handler

    sync = gw.GatewayClient(base_url=BASE, api_key=KEY)
    sync._http = httpx.Client(transport=httpx.MockTransport(capture("sync")))
    sync.chat_json("the prompt", **kwargs)

    async def run_async():
        async with gw.AsyncGatewayClient(
                base_url=BASE, api_key=KEY,
                transport=httpx.MockTransport(capture("async"))) as c:
            await c.chat_json("the prompt", **kwargs)

    asyncio.run(run_async())
    assert bodies["async"] == bodies["sync"], kwargs


def test_the_sync_client_is_untouched():
    """#28's contract: if the synchronous path had to change, that is a defect. Its own
    limiter and semaphore must still be the thread-based ones the pipeline relies on."""
    import threading
    assert isinstance(gw._embed_parallel, type(threading.Semaphore(1)))
    assert hasattr(gw.GatewayClient, "chat_json")
    assert not asyncio.iscoroutinefunction(gw.GatewayClient.chat_json)
