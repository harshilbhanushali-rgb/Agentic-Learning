"""`shared/pinecone_store.py`'s ASYNC reads -- issue #29.

Network-free: an async fake index records what was asked of it. The claim that the async
reads agree with the real index is proven live by the ticket's own check, not here.

WHY A CLASS RATHER THAN THREE MODULE FUNCTIONS. The synchronous reads are stateless
functions taking an api_key, and they can afford to be: the pipeline calls them in batches.
Pinecone's async client resolves an index by HOST and both the client and the index are
context managers, so a stateless async function would open and tear down a connection on
every request -- on the path that answers a CSM mid-call. `AsyncTriggerIndex` opens once
and is closed at shutdown, the same lifetime as the gateway client.

The `index` constructor argument is the test seam, mirroring `transport` on the async
gateway client: production uses `open()`, tests inject a fake.
"""
import asyncio

import pytest

from shared import pinecone_store as ps

KEYS = ["performance_pushback", "pricing_objection"]


class _FakeAsyncIndex:
    """Records calls; answers with whatever the test scripted.

    Deliberately has `upsert` raise. These reads must never write, and a test that proves it
    is cheaper than trusting that nobody adds one later.
    """

    def __init__(self, query_results=None, fetch_results=None):
        self.query_results = list(query_results or [])
        self.fetch_results = list(fetch_results or [])
        self.queries: list[dict] = []
        self.fetches: list[dict] = []
        self.closed = False

    async def query(self, **kwargs):
        self.queries.append(kwargs)
        return self.query_results.pop(0) if self.query_results else {"matches": []}

    async def fetch(self, **kwargs):
        self.fetches.append(kwargs)
        return self.fetch_results.pop(0) if self.fetch_results else {"vectors": {}}

    async def upsert(self, **kwargs):
        raise AssertionError("Ask Naren issues no writes -- there is no upsert on this path")

    async def close(self):
        self.closed = True


def _matches(*pairs):
    return {"matches": [{"id": i, "score": s} for i, s in pairs]}


def _run(coro):
    return asyncio.run(coro)


# -- the ranking search -------------------------------------------------------------------

def test_the_ranking_returns_ids_and_scores_in_the_order_pinecone_gave_them():
    """Ordering is the store's and is not recomputed. Two ranking implementations would be a
    place for the shortlist and the shipped rank-1 path to disagree about "closest"."""
    fake = _FakeAsyncIndex([_matches(("trigger_7", 0.81), ("trigger_3", 0.74))])

    async def body():
        async with ps.AsyncTriggerIndex(index=fake) as idx:
            return await idx.query_trigger_vectors([0.1] * 3072, top_k=25,
                                                   scenario_keys=KEYS)

    assert _run(body()) == [("trigger_7", 0.81), ("trigger_3", 0.74)]


def test_the_ranking_never_requests_stored_text():
    """THE load-bearing line of ADR 0008. Pinecone truncates the stored `text` to 500 chars,
    so an answer must never be groundable in it -- and a field cannot be read from a payload
    that was never requested."""
    fake = _FakeAsyncIndex([_matches(("trigger_1", 0.9))])

    async def body():
        async with ps.AsyncTriggerIndex(index=fake) as idx:
            await idx.query_trigger_vectors([0.1] * 3072, top_k=5, scenario_keys=KEYS)

    _run(body())
    assert fake.queries[0]["include_metadata"] is False
    assert fake.queries[0]["include_values"] is False


def test_the_coachable_restriction_is_an_in_filter_over_many_keys():
    """`$in` over many keys, not `$eq` on one: coachability is a property of a SCENARIO and
    `scenario_key` is in the metadata, which is what makes the restriction expressible here
    at all (measured free -- 218ms filtered against 221ms unfiltered)."""
    fake = _FakeAsyncIndex([_matches()])

    async def body():
        async with ps.AsyncTriggerIndex(index=fake) as idx:
            await idx.query_trigger_vectors([0.1] * 3072, top_k=5, scenario_keys=KEYS)

    _run(body())
    assert fake.queries[0]["filter"] == {"scenario_key": {"$in": KEYS}}
    assert fake.queries[0]["namespace"] == "triggers"
    assert fake.queries[0]["top_k"] == 5


def test_no_keys_means_no_filter_rather_than_an_empty_one():
    """An empty `$in` would match nothing and Ask Naren would decline every situation, which
    reads as a quality problem rather than a filter bug. The caller above this one is what
    refuses to run unrestricted; here, absent means absent."""
    fake = _FakeAsyncIndex([_matches(("trigger_1", 0.5))])

    async def body():
        async with ps.AsyncTriggerIndex(index=fake) as idx:
            await idx.query_trigger_vectors([0.1] * 3072, top_k=5, scenario_keys=None)

    _run(body())
    assert fake.queries[0]["filter"] is None


def test_a_namespace_can_be_chosen():
    """Response vectors live in a sibling namespace and are not what a situation is matched
    against, so the namespace is the caller's to state."""
    fake = _FakeAsyncIndex([_matches()])

    async def body():
        async with ps.AsyncTriggerIndex(index=fake) as idx:
            await idx.query_trigger_vectors([0.1] * 3072, top_k=5, scenario_keys=KEYS,
                                            namespace="responses")

    _run(body())
    assert fake.queries[0]["namespace"] == "responses"


def test_attribute_style_results_are_read_too():
    """The SDK has answered with both shapes across versions, and the sync reads already
    handle either. An async twin that only understood dicts would fail on a version bump
    with a confusing AttributeError rather than a clear one."""
    class _M:
        def __init__(self, i, s):
            self.id, self.score = i, s

    class _R:
        matches = [_M("trigger_9", 0.66)]

    fake = _FakeAsyncIndex([_R()])

    async def body():
        async with ps.AsyncTriggerIndex(index=fake) as idx:
            return await idx.query_trigger_vectors([0.1] * 3072, top_k=5, scenario_keys=KEYS)

    assert _run(body()) == [("trigger_9", 0.66)]


# -- the presence check -------------------------------------------------------------------

def test_presence_returns_the_scenario_key_the_index_holds():
    """Presence alone is not what makes a pair retrievable. The search restricts on
    `scenario_key`, written at vector-ship time, while the pool's copy is read live from
    Postgres -- and two jobs UPDATE it with no re-upsert. A pair whose indexed key has left
    the filter is invisible to retrieval while being unambiguously present."""
    fake = _FakeAsyncIndex([{"matches": [
        {"metadata": {"pair_id": 12, "scenario_key": "pricing_objection"}},
        {"metadata": {"pair_id": 13, "scenario_key": ""}},
    ]}])

    async def body():
        async with ps.AsyncTriggerIndex(index=fake) as idx:
            return await idx.present_trigger_pair_ids(["12", "13", "14"])

    assert _run(body()) == {"12": "pricing_objection", "13": ""}


def test_presence_asks_for_metadata_but_not_vectors():
    """`fetch` is the wrong shape for this question: it returns 3072 floats per record,
    measured at 46.3s for 200 ids against 0.44s here for the same 200."""
    fake = _FakeAsyncIndex([{"matches": []}])

    async def body():
        async with ps.AsyncTriggerIndex(index=fake) as idx:
            await idx.present_trigger_pair_ids(["1", "2"])

    _run(body())
    q = fake.queries[0]
    assert q["include_metadata"] is True
    assert q["include_values"] is False
    assert q["filter"] == {"pair_id": {"$in": [1, 2]}}
    assert q["top_k"] == 2, "top_k must cover the whole batch or present ids are dropped"


def test_presence_batches_so_a_corpus_sized_check_is_one_query_per_thousand():
    fake = _FakeAsyncIndex([{"matches": []}, {"matches": []}, {"matches": []}])

    async def body():
        async with ps.AsyncTriggerIndex(index=fake) as idx:
            await idx.present_trigger_pair_ids([str(i) for i in range(2500)])

    _run(body())
    assert [q["top_k"] for q in fake.queries] == [1000, 1000, 500]


# -- the exact confirmation ---------------------------------------------------------------

def test_fetch_confirms_which_ids_the_namespace_actually_holds():
    """The presence check is an ANN query, so a reported absence is PROVISIONAL. A false
    alarm must not refuse to serve a healthy index, which is why absence is confirmed here
    and a key that came back needs no confirmation."""
    fake = _FakeAsyncIndex(fetch_results=[
        {"vectors": {"trigger_5": {}, "trigger_6": {}}}])

    async def body():
        async with ps.AsyncTriggerIndex(index=fake) as idx:
            return await idx.fetch_trigger_ids(["trigger_5", "trigger_6", "trigger_7"])

    assert _run(body()) == {"trigger_5", "trigger_6"}


def test_fetch_batches_at_the_id_cap():
    fake = _FakeAsyncIndex(fetch_results=[{"vectors": {}}, {"vectors": {}}])

    async def body():
        async with ps.AsyncTriggerIndex(index=fake) as idx:
            await idx.fetch_trigger_ids([f"trigger_{i}" for i in range(300)])

    _run(body())
    assert [len(f["ids"]) for f in fake.fetches] == [250, 50]


# -- agreement with the synchronous reads -------------------------------------------------

def test_the_async_ranking_agrees_with_the_synchronous_one(monkeypatch):
    """#29's acceptance criterion, as a test rather than a promise: same index answer in,
    same tuples out. Two implementations of one read are a place to drift silently."""
    answer = _matches(("trigger_4", 0.77), ("trigger_1", 0.52))

    class _SyncFake:
        def __init__(self, result):
            self.result = result
            self.queries = []

        def query(self, **kwargs):
            self.queries.append(kwargs)
            return self.result

    sync_fake = _SyncFake(answer)
    monkeypatch.setitem(ps._index_cache, ("k", "narens-brain-3072"), sync_fake)
    from_sync = ps.query_trigger_vectors("k", "narens-brain-3072", [0.1] * 3072,
                                         top_k=25, scenario_keys=KEYS)

    async_fake = _FakeAsyncIndex([answer])

    async def body():
        async with ps.AsyncTriggerIndex(index=async_fake) as idx:
            return await idx.query_trigger_vectors([0.1] * 3072, top_k=25,
                                                   scenario_keys=KEYS)

    from_async = _run(body())
    assert from_async == from_sync
    # And the REQUEST is the same shape too -- agreeing on the answer while asking a
    # different question would still be a drift.
    for field in ("top_k", "namespace", "include_metadata", "include_values", "filter"):
        assert async_fake.queries[0][field] == sync_fake.queries[0][field], field


# -- lifecycle and read-only ---------------------------------------------------------------

def test_closing_the_index_closes_what_it_opened():
    fake = _FakeAsyncIndex()

    async def body():
        async with ps.AsyncTriggerIndex(index=fake) as idx:
            await idx.query_trigger_vectors([0.1] * 3072, top_k=1, scenario_keys=KEYS)
        return fake.closed

    assert _run(body()) is True


def test_there_is_no_write_on_this_path():
    """Ask Naren issues no upsert and no index creation anywhere (ADR 0008).

    Two halves, and they catch different mistakes. This one is a tripwire on the class
    surface: a write METHOD must never be added here. The other half is that
    `_FakeAsyncIndex.upsert` raises, so every read test in this file would fail loudly if
    one of the three reads started writing through the index it was handed.
    """
    assert not hasattr(ps.AsyncTriggerIndex, "upsert")
    assert not hasattr(ps.AsyncTriggerIndex, "init_index")
    assert not hasattr(ps.AsyncTriggerIndex, "upsert_pairs")
    assert not hasattr(ps.AsyncTriggerIndex, "delete")


def test_the_synchronous_reads_are_untouched():
    """#29's contract. If the sync functions had to change, that is a defect in this work."""
    import inspect
    for name in ("query_triggers", "query_trigger_vectors", "fetch_trigger_ids",
                 "present_trigger_pair_ids", "upsert_pairs", "init_index"):
        fn = getattr(ps, name)
        assert not inspect.iscoroutinefunction(fn), f"{name} became async"


def test_concurrent_reads_share_one_index_connection():
    """The point of holding the index open: eight simultaneous CSM questions must not open
    eight connections, and must not serialise behind one lock either."""
    fake = _FakeAsyncIndex([_matches(("trigger_1", 0.5)) for _ in range(8)])

    async def body():
        async with ps.AsyncTriggerIndex(index=fake) as idx:
            return await asyncio.gather(*(
                idx.query_trigger_vectors([0.1] * 3072, top_k=1, scenario_keys=KEYS)
                for _ in range(8)))

    results = _run(body())
    assert len(results) == 8
    assert len(fake.queries) == 8
