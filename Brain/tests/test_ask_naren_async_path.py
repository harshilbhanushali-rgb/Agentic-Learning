"""What became true when Ask Naren's request path went async -- issue #30.

The four ask_naren test files already cover WHAT each intent answers, and they now drive the
awaited path, so they are the regression net for the conversion itself. This file covers the
things that only became possible to get wrong once `await` entered the path, and which no
existing test would notice:

  * two awaits on the per-request embedding memo billing two gateway calls instead of one
  * a thread-bound SQLite connection appearing anywhere in the request path
  * one store implementation staying synchronous, so the rollback constant stops working
  * a blocking call in the path, which would serialise the very requests #27 exists to
    overlap

Network-free, and no `pytest-asyncio`: `asyncio.run` per test also gives each test a fresh
event loop, which is what the gateway's per-loop admission gate needs.
"""
import asyncio
import inspect
import sqlite3

import numpy as np
import pytest

from ask_naren import answering, citations, grounding, intake, rendering, responding
from ask_naren import retrieval, threads, vector_store

CALL = "20230503_uber_joveo_weekly_performance_review_d18cc178.txt"
QUOTE = "show them cost per hire against their own baseline"
RESPONSE = f"I would {QUOTE} before touching the rate card."


def _pairs():
    return [{"pair_id": 11, "call_id": 1, "turn_index": 3, "scenario_key": "s1",
             "trigger_text": "our cost per hire is way too high",
             "response_text": RESPONSE, "call_filename": CALL}]


def _pool():
    return retrieval.RetrievalPool(_pairs(), np.array([[1.0, 0.0]]))


class _CountingEmbedder:
    """Counts how many times the gateway would actually have been asked."""

    def __init__(self):
        self.calls = 0
        self.texts: list[str] = []

    async def __call__(self, texts):
        self.calls += 1
        self.texts.extend(texts)
        await asyncio.sleep(0)          # a real suspension point, like a real request
        return np.array([[1.0, 0.0]] * len(texts))


class _StubGateway:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    async def chat_json(self, prompt, **kwargs):
        self.calls.append(kwargs)
        if not self.payloads:
            raise AssertionError("more generations than the contract allows")
        return self.payloads.pop(0), {"served_model": kwargs.get("model")}


def _decides(intent, retrieval_query="", **kw):
    async def _classify(message, gateway, *, thread=()):
        return intake.IntakeDecision(intent=intent, retrieval_query=retrieval_query,
                                     question=kw.get("question", ""),
                                     my_reply=kw.get("my_reply", "")), {}
    return _classify


# -- the memo, which the conversion could silently have broken ----------------------------

def test_two_concurrent_awaits_on_the_memo_bill_one_embedding():
    """The memo must cache the IN-FLIGHT operation, not the finished vector.

    DRIVEN CONCURRENTLY ON PURPOSE. An earlier version of this test went through the
    `procedure` path and asserted one embedding for one question -- and a review proved it
    worthless by reverting `_memoised` to naive value-caching and watching it still pass.
    It passed because that path awaits SEQUENTIALLY, so the race the memo guards against
    cannot occur there at all.

    So the memo is now a named function and this drives it the only way that can fail: two
    awaits on a cold key at the same time. With value-caching, both see an empty dict and
    both embed. With task-caching, the second awaits the first one's request.
    """
    embedder = _CountingEmbedder()
    embed_once = responding._memoised(embedder)

    async def body():
        return await asyncio.gather(embed_once(["same text"]), embed_once(["same text"]))

    first, second = asyncio.run(body())
    assert embedder.calls == 1, (
        f"the same text was embedded {embedder.calls} times by two concurrent awaits -- "
        f"the memo is caching the result rather than the in-flight operation")
    assert (first == second).all(), "both callers must get the same vector"


def test_the_memo_keys_on_the_texts_so_a_different_query_is_not_reused():
    """A memo that returned one request's vector for a different text would ground an answer
    in the wrong situation -- the worst failure shape available here."""
    embedder = _CountingEmbedder()
    embed_once = responding._memoised(embedder)

    async def body():
        await embed_once(["first situation"])
        await embed_once(["second situation"])
        await embed_once(["first situation"])

    asyncio.run(body())
    assert embedder.calls == 2, embedder.calls
    assert embedder.texts == ["first situation", "second situation"]


def test_the_procedure_path_embeds_its_question_once():
    """The behaviour the memo exists for, at the layer a CSM's question actually takes.

    Sequential, so it cannot catch the concurrent race above -- that is what the previous
    test is for. What it does catch is the memo being removed from `_procedure` entirely,
    which would bill two gateway embeddings for one question.
    """
    embedder = _CountingEmbedder()
    # A playbook whose evidence is unquotable degrades to the Layer B answer, which is what
    # makes this path need the SAME vector twice -- once to find the scenario, once to answer.
    playbook = {"key_moves": [{"move": "reframe", "criterion": "c", "evidence": []}]}
    gw = _StubGateway({"declined": False, "answer": "Reframe on their own baseline.",
                       "quote": QUOTE, "cited_call": CALL})

    result = asyncio.run(responding.respond(
        "what is the general play for cost per hire pushback", _pool(), gw,
        embed_query=embedder, classify=_decides("procedure", "cost per hire pushback"),
        playbook_for=lambda key: {"playbook": playbook}))

    assert result["outcome"] == "answered"
    assert embedder.calls == 1, embedder.calls


def test_the_memo_is_not_shared_between_requests():
    """Scoped per request, deliberately: a process-wide cache of CSM situations would be a
    store of client-identifying text that nothing clears, and the service holds no state
    between requests by design."""
    embedder = _CountingEmbedder()
    gw = _StubGateway(
        {"declined": False, "answer": "a", "quote": QUOTE, "cited_call": CALL},
        {"declined": False, "answer": "a", "quote": QUOTE, "cited_call": CALL})
    for _ in range(2):
        asyncio.run(responding.respond(
            "situation", _pool(), gw, embed_query=embedder,
            classify=_decides("reply_to_client", "cost per hire is too high")))
    assert embedder.calls == 2, "the second request reused the first request's memo"


# -- no thread-bound state in the path ----------------------------------------------------

def test_answering_a_situation_opens_no_sqlite_connection(monkeypatch):
    """ADR 0003's stated blocker, asserted gone.

    `shared/embed_cache.py` opens SQLite WITHOUT `check_same_thread=False`, so a second
    request thread touching that connection raises outright -- which is the entire reason
    the service was single-threaded. The fix is not to make that cache thread-safe: it is
    that the request path no longer constructs it at all, so the object that raises does not
    exist. A live CSM situation is a novel string and therefore a guaranteed cache miss,
    so nothing is lost.

    Asserted by making `sqlite3.connect` itself a test failure, which catches the connection
    wherever in the path it might be opened rather than only in the module we expect.
    """
    def _refuse(*args, **kwargs):
        raise AssertionError(
            "the request path opened a SQLite connection -- that is the thread-bound object "
            "ADR 0003 was built around, and answering must not touch it")

    monkeypatch.setattr(sqlite3, "connect", _refuse)

    gw = _StubGateway({"declined": False, "answer": "Reframe on their own baseline.",
                       "quote": QUOTE, "cited_call": CALL})
    result = asyncio.run(responding.respond(
        "our cost per hire is way too high", _pool(), gw, embed_query=_CountingEmbedder(),
        classify=_decides("reply_to_client", "our cost per hire is way too high")))
    assert result["outcome"] == "answered"


def test_the_service_embeds_through_the_async_gateway_not_the_cached_embedder():
    """THE ACTUAL REGRESSION SURFACE, which is one argument wide.

    An earlier version of this test grepped `ask_naren/*` for `import threading`. That
    could never fail: none of those modules ever contained it, before or after this ticket.
    The threads it claimed to be guarding against live in `shared/gateway.py`'s
    ThreadPoolExecutor, and the request path reached them through
    `preprocessing.embedder.embed_query_matrix` -- which is also what opens the thread-bound
    SQLite cache. So the thing that must not regress is `ops/serve_ask_naren.py` passing
    `embed_query=_embed_query(gateway)` rather than `embed_query=embedder.embed_query_matrix`.
    Reverting that one argument restores both the thread pool and the SQLite connection, and
    every other test in this file still passes, because they all inject their own embedder.

    Checked behaviourally: `_embed_query` must go to the gateway and to nothing else.
    """
    from ops import serve_ask_naren as serve

    asked: list[list[str]] = []

    class _Gateway:
        async def embed(self, texts, **kwargs):
            asked.append(list(texts))
            return [[0.5] * 4 for _ in texts]

    embed = serve._embed_query(_Gateway())
    got = asyncio.run(embed(["our cost per hire is too high"]))

    assert asked == [["our cost per hire is too high"]], "the gateway was not the embedder"
    assert got.dtype == np.float32, "callers do linear algebra on this; it must be a matrix"
    assert got.shape == (1, 4)

    # And the wiring actually uses it. A source check, because the alternative is standing
    # up the whole service; precedented by tests/test_ship_union_taxonomy_transaction.py.
    wiring = inspect.getsource(serve._run)
    assert "embed_query = _embed_query(gateway)" in wiring
    assert "embedder.embed_query_matrix" not in wiring, (
        "the request path is wired back to the cached embedder -- that restores the thread "
        "pool and the thread-bound SQLite connection ADR 0003 was built around")


# -- one seam, both implementations -------------------------------------------------------

def test_both_stores_are_awaited_so_the_rollback_constant_still_works():
    """`ops/serve_ask_naren.py` swaps the store in ONE line. If only the Pinecone store were
    awaited, that line would stop being a swap and become a rewrite -- and the in-memory
    store is also what keeps this whole suite network-free."""
    assert inspect.iscoroutinefunction(vector_store.InMemoryTriggerStore.search)
    assert inspect.iscoroutinefunction(vector_store.PineconeTriggerStore.search)
    assert inspect.iscoroutinefunction(vector_store.PineconeTriggerStore.unretrievable)


def test_the_in_memory_store_still_ranks_correctly_when_awaited():
    store = vector_store.InMemoryTriggerStore([1, 2], np.array([[1.0, 0.0], [0.0, 1.0]]))
    ranked = asyncio.run(store.search(np.array([1.0, 0.0]), 2))
    assert [pair_id for pair_id, _ in ranked] == ["1", "2"]
    assert ranked[0][1] == pytest.approx(1.0)


def test_the_pinecone_store_still_strips_the_prefix_and_clamps_the_cosine():
    """The two conversions issue #29 handed to this ticket, and both fail SILENTLY.

    A prefixed id post-filters to nothing, so Ask Naren declines every situation -- which
    reads as a quality problem rather than a type bug. And a score of 1.00135 is not a
    cosine at all; it comes from the index's quantized representation and would be read
    against ADR 0005's measured bands.
    """
    class _FakeIndex:
        async def query_trigger_vectors(self, query_vec, top_k, namespace=None,
                                        scenario_keys=None):
            return [("trigger_11", 1.00135), ("trigger_12", -1.004)]

    store = vector_store.PineconeTriggerStore(_FakeIndex(), scenario_keys=["s1"])
    ranked = asyncio.run(store.search(np.array([1.0, 0.0]), 2))
    assert [pair_id for pair_id, _ in ranked] == ["11", "12"], "the prefix was not stripped"
    assert ranked[0][1] == 1.0, "a score above 1 is not a cosine"
    assert ranked[1][1] == -1.0


def test_a_pool_refuses_a_store_with_no_coachable_scenarios():
    """An unrestricted filter would let Ask Naren answer from scenarios it is not allowed to
    coach, and `open()` must refuse BEFORE opening a connection it would have to close."""
    with pytest.raises(ValueError, match="coachable"):
        vector_store.PineconeTriggerStore(object(), scenario_keys=[])
    with pytest.raises(ValueError, match="coachable"):
        asyncio.run(vector_store.PineconeTriggerStore.open("k", "idx", scenario_keys=[]))


# -- the path is genuinely concurrent -----------------------------------------------------

def test_two_situations_answered_at_once_do_not_serialise():
    """The point of the whole conversion, at the layer this ticket owns.

    The HTTP server is still synchronous (issue #31), so this drives `respond` directly --
    which is exactly where the overlap has to work before a concurrent server can exploit
    it. If any step blocked instead of awaiting, the two answers would take twice as long
    and the interleave below would not appear.
    """
    order: list[str] = []

    class _SlowEmbedder:
        def __init__(self, tag):
            self.tag = tag

        async def __call__(self, texts):
            order.append(f"{self.tag}:embed-start")
            await asyncio.sleep(0.02)
            order.append(f"{self.tag}:embed-done")
            return np.array([[1.0, 0.0]] * len(texts))

    async def both():
        return await asyncio.gather(*(
            responding.respond(
                "our cost per hire is way too high", _pool(),
                _StubGateway({"declined": False, "answer": "a", "quote": QUOTE,
                              "cited_call": CALL}),
                embed_query=_SlowEmbedder(tag),
                classify=_decides("reply_to_client", "cost per hire"))
            for tag in ("A", "B")))

    results = asyncio.run(both())
    assert all(r["outcome"] == "answered" for r in results)
    # Both embeddings start before either finishes -- they overlapped rather than queued.
    assert order.index("B:embed-start") < order.index("A:embed-done"), order


def test_the_pure_modules_stayed_synchronous():
    """An `async def` with nothing to await hides where the real waiting happens, so the
    modules that only compute must NOT have been converted."""
    for fn in (grounding.check, grounding.from_pairs, rendering.discovery,
               citations.resolve_label, threads.trim, threads.parse,
               answering.clarify, answering.decline_without_search):
        assert not inspect.iscoroutinefunction(fn), fn.__name__
