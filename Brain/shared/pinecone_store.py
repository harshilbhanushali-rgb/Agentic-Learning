from __future__ import annotations
import os
from pinecone import Pinecone, ServerlessSpec

_pc_cache: dict[str, Pinecone] = {}
_index_cache: dict[tuple[str, str], object] = {}

def _get_client(api_key: str) -> Pinecone:
    if api_key not in _pc_cache:
        _pc_cache[api_key] = Pinecone(api_key=api_key)
    return _pc_cache[api_key]

def _get_index(api_key: str, index_name: str):
    key = (api_key, index_name)
    if key not in _index_cache:
        _index_cache[key] = _get_client(api_key).Index(index_name)
    return _index_cache[key]

def init_index(api_key: str, index_name: str, dimension: int | None = None) -> None:
    """Create the index if absent. `dimension` MUST match the active embedder's width.

    *** THIS USED TO HARDCODE 768 AND THAT IS A TRAP ONCE THE BACKEND CAN MOVE. *** 768 is
    bge's width; `gemini-embedding-2` is 3072 natively. A hardcoded 768 silently creates an
    index that every gemini upsert then fails against, or worse, that accepts truncated
    vectors nobody asked for. Pinecone dimension is immutable after creation, so getting this
    wrong means a new index, not an ALTER -- which is exactly why it is derived rather than
    assumed, and why the caller may state it explicitly.
    """
    if dimension is None:
        from shared.tuning import get_tuning
        emb = get_tuning().embedding
        # Derived by asking "is this the LOCAL model?", never by listing the hosted ones.
        # This read `== "gemini"` until 2026-08-19, when a third backend (`gateway`) was
        # added -- and an allow-list of hosted names fails OPEN on any name not in it, so
        # `gateway` silently took the 768 branch while producing 3072-dim vectors. Pinecone's
        # dimension is IMMUTABLE, so that mistake is not a wrong config value, it is a wrong
        # index that has to be recreated. Only `local` is 768; every hosted backend embeds at
        # gemini_dimensions, and a future fourth backend inherits the right answer by default.
        dimension = 768 if emb.backend == "local" else emb.gemini_dimensions
    pc = _get_client(api_key)
    if index_name not in [i.name for i in pc.list_indexes()]:
        pc.create_index(
            name=index_name,
            dimension=dimension,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        print(f"[pinecone] Created index '{index_name}' at dim={dimension}.")
    else:
        print(f"[pinecone] Index '{index_name}' already exists.")

def upsert_pairs(api_key: str, index_name: str, pairs: list[dict],
                 namespaces: tuple[str, ...] = ("triggers", "responses")) -> None:
    """`namespaces` exists so the two sides can land INDEPENDENTLY. Trigger vectors are
    typically already cached while response vectors are not, and the gateway caps embeddings
    at 150 requests/window — so forcing both together makes a corpus-sized job an 85-minute
    prerequisite for any of it. `query_triggers` reads the triggers namespace, so triggers
    alone is a serviceable state, not a broken one."""
    if not pairs:
        return
    idx = _get_index(api_key, index_name)
    trigger_vecs = [(
        f"trigger_{p['pair_id']}",
        p["trigger_vec"],
        {"pair_id": p["pair_id"], "call_id": p["call_id"],
         "scenario_key": p.get("scenario_key") or "", "turn_index": p["turn_index"],
         "text": p["trigger_text"][:500]},
    ) for p in pairs]
    response_vecs = [] if "responses" not in namespaces else [(
        f"response_{p['pair_id']}",
        p["response_vec"],
        {"pair_id": p["pair_id"], "call_id": p["call_id"],
         "scenario_key": p.get("scenario_key") or "", "turn_index": p["turn_index"],
         "text": p["response_text"][:500]},
    ) for p in pairs]
    # BATCH SIZED BY VECTOR WIDTH, NOT A FIXED 100. Pinecone caps a request at ~2 MB, and
    # 100 x 768 float32 is ~300 KB while 100 x 3072 is ~1.2 MB plus metadata -- close enough
    # to the ceiling that a slightly longer `text` field tips it over. Deriving the batch from
    # the actual width keeps the 768 path at EXACTLY its historical 100 (asserted below) and shrinks it
    # for wider embedders instead of failing mid-upsert on a corpus-sized job.
    width = len(pairs[0]["trigger_vec"]) or 768
    BATCH = max(10, min(100, int(320_000 / max(width * 4, 1))))
    if "triggers" in namespaces:
        for i in range(0, len(trigger_vecs), BATCH):
            idx.upsert(vectors=trigger_vecs[i:i+BATCH], namespace="triggers")
    if "responses" in namespaces:
        for i in range(0, len(response_vecs), BATCH):
            idx.upsert(vectors=response_vecs[i:i+BATCH], namespace="responses")

def query_triggers(api_key: str, index_name: str, query_vec: list[float],
                   top_k: int = 5, scenario_key: str | None = None) -> list[dict]:
    idx = _get_index(api_key, index_name)
    filter_ = {"scenario_key": {"$eq": scenario_key}} if scenario_key else None
    results = idx.query(vector=query_vec, top_k=top_k, namespace="triggers",
                        include_metadata=True, filter=filter_)
    return results.get("matches", [])

def query_trigger_vectors(api_key: str, index_name: str, query_vec: list[float],
                          top_k: int = 25, namespace: str = "triggers",
                          scenario_keys: list[str] | None = None) -> list[tuple[str, float]]:
    """Rank trigger vectors and return (record_id, score) -- ADDITIVE, for Ask Naren (ADR 0008).

    Deliberately NOT a change to `query_triggers` above, which returns whole match objects
    including metadata and has a pipeline caller (calibration/dry_run_ego_trap.py). This
    exists because Ask Naren needs three things that one does not offer: an `$in` filter over
    MANY scenario keys rather than `$eq` on one, a caller-chosen index (the 3072 one), and
    ids plus scores WITHOUT metadata -- Pinecone truncates the stored `text` to 500 chars, so
    an answer must never be grounded in it.

    `include_metadata=False` is the load-bearing part of that last point: the field cannot be
    read from a payload that was never requested.
    """
    idx = _get_index(api_key, index_name)
    filter_ = {"scenario_key": {"$in": list(scenario_keys)}} if scenario_keys else None
    results = idx.query(vector=query_vec, top_k=top_k, namespace=namespace,
                        include_metadata=False, include_values=False, filter=filter_)
    matches = results.get("matches", []) if isinstance(results, dict) else results.matches
    out = []
    for m in matches:
        m_id = m.get("id") if isinstance(m, dict) else m.id
        score = m.get("score") if isinstance(m, dict) else m.score
        out.append((str(m_id), float(score)))
    return out


def fetch_trigger_ids(api_key: str, index_name: str, record_ids: list[str],
                      namespace: str = "triggers") -> set[str]:
    """Which of `record_ids` the namespace actually holds. ADDITIVE (ADR 0008).

    Vectors are NOT requested: this answers presence, for Ask Naren's startup coverage guard,
    and pulling 3072 floats per id to answer a yes/no question is the thing that makes
    extracting the pool cost ~168s. Batched because fetch caps a request's id count.
    """
    idx = _get_index(api_key, index_name)
    found: set[str] = set()
    BATCH = 250
    for i in range(0, len(record_ids), BATCH):
        got = idx.fetch(ids=record_ids[i:i + BATCH], namespace=namespace)
        vectors = got.get("vectors", {}) if isinstance(got, dict) else got.vectors
        found.update(str(k) for k in vectors)
    return found

def present_trigger_pair_ids(api_key: str, index_name: str, pair_ids: list[str],
                             namespace: str = "triggers") -> dict[str, str]:
    """`pair_id` -> the `scenario_key` the INDEX has for it, for the ids it holds.

    ADDITIVE (ADR 0008). Returns the scenario_key rather than just presence because the
    metadata is already in the response, so checking it is free -- and because presence
    alone is not what makes a pair retrievable. Ask Naren's search restricts on
    `scenario_key`, and that value was written at vector-ship time while the pool's copy is
    read live from Postgres. `response_taxonomy_auto_pass.py` and
    `calibration/graduate_sink_topics.py` both UPDATE `kb_pairs.scenario_key` with no
    re-upsert, so the two can diverge -- and a pair whose indexed key is no longer in the
    filter is invisible to retrieval while still being unambiguously PRESENT.

    This exists because `fetch` is the wrong shape for the question: it returns 3072 floats
    per record, measured at 46.3s for 200 ids, against 0.44s here for the same 200 and 1.7s
    for 1,000.

    The query VECTOR is a dummy and the ranking is irrelevant: the metadata filter selects
    exactly the requested pair_ids, `top_k` covers the whole batch, and the triggers
    namespace holds one record per pair_id -- so every present id comes back regardless of
    order. Verified exhaustive at 200/200, 500/500, 1000/1000 and 6496/6496.

    Because it is still an ANN query, a caller must treat a REPORTED ABSENCE as provisional
    and confirm it with `fetch_trigger_ids`, which is exact. A false alarm would otherwise
    refuse to serve a healthy index. A key that IS returned needs no confirmation.
    """
    idx = _get_index(api_key, index_name)
    dummy = [0.0] * 3072
    dummy[0] = 1.0
    found: dict[str, str] = {}
    BATCH = 1000
    for i in range(0, len(pair_ids), BATCH):
        batch = pair_ids[i:i + BATCH]
        results = idx.query(vector=dummy, top_k=len(batch), namespace=namespace,
                            include_values=False, include_metadata=True,
                            filter={"pair_id": {"$in": [int(p) for p in batch]}})
        matches = results.get("matches", []) if isinstance(results, dict) else results.matches
        for m in matches:
            md = (m.get("metadata") if isinstance(m, dict) else m.metadata) or {}
            if "pair_id" in md:
                found[str(int(md["pair_id"]))] = md.get("scenario_key") or ""
    return found


# =========================================================================================
# THE ASYNC READS (added 2026-09-10, issue #29)
# =========================================================================================
#
# Everything above is unchanged and stays synchronous: the upsert path, index creation, and
# the pipeline's own `query_triggers`. Those run in batch jobs where blocking is correct.
#
# Below are async twins of the THREE reads Ask Naren makes -- the ranking search on every
# request, and the two startup coverage checks. They exist because a blocking HTTP call
# inside a coroutine freezes the event loop for its duration, which would serialise exactly
# the requests issue #27 is making concurrent. Pinecone's own async client is used, so NO
# THREAD is involved; #27 commits to no threads in the request path.
#
# READ-ONLY BY CONSTRUCTION. There is no async upsert and no async index creation here, and
# there must not be: Ask Naren issues no writes anywhere (ADR 0008).


class AsyncTriggerIndex:
    """Ask Naren's three reads against one index, held open for the process lifetime.

    A CLASS RATHER THAN THREE FUNCTIONS, and the reason is not style. The sync reads can be
    stateless functions taking an api_key because the pipeline calls them in batches and an
    index handle is cached module-level. Pinecone's async client resolves an index by HOST
    and both the client and the index are async context managers, so a stateless async
    function would have to open a client, resolve the host, open the index, query, and tear
    all three down -- on every single CSM question. Opened once at startup and closed at
    shutdown, the same lifetime as the gateway client.

    `index` is the test seam, mirroring `transport` on `AsyncGatewayClient`: production
    calls `open()`, tests inject a fake. When a test supplies the index, this object closes
    only what it was given and never touches a network.
    """

    def __init__(self, index, client=None):
        self._index = index
        self._client = client

    @classmethod
    async def open(cls, api_key: str, index_name: str) -> "AsyncTriggerIndex":
        """Resolve the index's host ONCE, then hold the connection.

        `pc.index(name=...)` does the describe-index host resolution itself, with a cache.
        An earlier version of this hand-rolled that with `describe_index` and then
        `IndexAsyncio(host=...)`, which pinecone 9.1.0 documents as `:meta private:` and a
        "backwards-compatibility shim ... new code should use pc.index(host=...)" -- an SDK
        bump that drops the shim would be an AttributeError at service startup.

        Note `index()` is itself a COROUTINE despite returning an `AsyncIndex` rather than
        an awaitable-looking object; forgetting the await yields a coroutine that fails
        later with "'coroutine' object has no attribute 'query'".

        Either way the lookup is a real round trip, which is why it happens here, once, and
        not on the request path.
        """
        from pinecone import PineconeAsyncio
        client = PineconeAsyncio(api_key=api_key)
        return cls(await client.index(name=index_name), client=client)

    async def aclose(self) -> None:
        await self._index.close()
        if self._client is not None:
            await self._client.close()

    async def __aenter__(self) -> "AsyncTriggerIndex":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # -- the ranking search, on every request ------------------------------------

    async def query_trigger_vectors(self, query_vec: list[float], top_k: int = 25,
                                    namespace: str = "triggers",
                                    scenario_keys: list[str] | None = None
                                    ) -> list[tuple[str, float]]:
        """Rank trigger vectors and return `(record_id, score)`, nearest first.

        The async twin of the module-level function of the same name, and it must keep
        asking the SAME question: `include_metadata=False` is load-bearing, not an
        optimisation. Pinecone truncates the stored `text` to 500 characters, so an answer
        must never be groundable in it -- and a field cannot be read from a payload that was
        never requested.

        Ordering is Pinecone's and is not recomputed here.

        *** TWO THINGS THE CALLER STILL OWES, AND BOTH FAIL SILENTLY IF FORGOTTEN. *** This
        returns exactly what the sync twin returns -- Pinecone's RAW record ids and RAW
        scores -- because this layer is the transport, not the store:

          * `trigger_1234`, not `1234`. Ask Naren's pool keys on the bare pair_id, and a
            store handing it prefixed ids post-filters to nothing, so the tool declines
            every situation. `ask_naren/vector_store.py` warns that this "reads as a quality
            problem rather than a type bug".
          * Scores are NOT clamped. Querying this index with one of its own stored unit
            vectors returns that record at up to 1.00135, which is not a cosine at all --
            it comes from a quantized ANN representation. `Match.cosine` is documented as a
            real cosine and is read against ADR 0005's measured bands.

        `ask_naren/vector_store.PineconeTriggerStore` does both with `_bare_id` and
        `_clamp_cosine`. Its async twin (issue #30) must reuse those two functions rather
        than re-deriving them here -- putting them in this layer would give the sync and
        async stores two different contracts, which is the specific rollback hazard ADR 0008
        exists to prevent.
        """
        filter_ = ({"scenario_key": {"$in": list(scenario_keys)}}
                   if scenario_keys else None)
        results = await self._index.query(
            vector=query_vec, top_k=top_k, namespace=namespace,
            include_metadata=False, include_values=False, filter=filter_)
        return [(str(m_id), float(score)) for m_id, score in _id_scores(results)]

    # -- the startup coverage guard ----------------------------------------------

    async def present_trigger_pair_ids(self, pair_ids: list[str],
                                       namespace: str = "triggers") -> dict[str, str]:
        """`pair_id` -> the `scenario_key` the INDEX has for it, for the ids it holds.

        Returns the key rather than bare presence because presence alone is not what makes
        a pair retrievable: the search restricts on `scenario_key`, and the index's copy was
        written at vector-ship time while the pool's is read live from Postgres. Two jobs
        UPDATE that column with no re-upsert, so they can diverge -- and a pair whose
        indexed key has left the filter is invisible to retrieval while being unambiguously
        present. A presence-only guard reports full coverage while every pair in a graduated
        scenario is unreachable.

        The query vector is a dummy and the ranking is irrelevant: the metadata filter
        selects exactly the requested ids, `top_k` covers the whole batch, and the namespace
        holds one record per pair_id, so every present id comes back regardless of order.

        Still an ANN query, so a caller must treat a reported ABSENCE as provisional and
        confirm it with `fetch_trigger_ids`, which is exact.
        """
        dummy = [0.0] * 3072
        dummy[0] = 1.0
        found: dict[str, str] = {}
        BATCH = 1000
        for i in range(0, len(pair_ids), BATCH):
            batch = pair_ids[i:i + BATCH]
            results = await self._index.query(
                vector=dummy, top_k=len(batch), namespace=namespace,
                include_values=False, include_metadata=True,
                filter={"pair_id": {"$in": [int(p) for p in batch]}})
            for md in _metadatas(results):
                if "pair_id" in md:
                    found[str(int(md["pair_id"]))] = md.get("scenario_key") or ""
        return found

    async def fetch_trigger_ids(self, record_ids: list[str],
                                namespace: str = "triggers") -> set[str]:
        """Which of `record_ids` the namespace actually holds -- the EXACT confirmation.

        Vectors are not requested; this answers presence. Batched because fetch caps a
        request's id count. Used only to confirm an absence the cheap ANN check reported,
        because a false alarm must not refuse to serve a healthy index.
        """
        found: set[str] = set()
        BATCH = 250
        for i in range(0, len(record_ids), BATCH):
            got = await self._index.fetch(ids=record_ids[i:i + BATCH], namespace=namespace)
            found.update(str(k) for k in _vectors_of(got))
        return found


def _matches_of(results):
    """The SDK has answered with a dict and with an object across versions, and the three
    synchronous reads above each inline that check.

    Shared by the ASYNC reads only -- deliberately not retrofitted upward, because #29's
    contract is that the synchronous functions are untouched. So this is not yet "the one
    place" the shapes are understood; it is the one place the async reads understand them,
    and a future SDK shape change still has to be fixed in the sync functions too."""
    if isinstance(results, dict):
        return results.get("matches", [])
    return results.matches


def _id_scores(results):
    for m in _matches_of(results):
        if isinstance(m, dict):
            yield m.get("id"), m.get("score")
        else:
            yield m.id, m.score


def _metadatas(results):
    for m in _matches_of(results):
        md = (m.get("metadata") if isinstance(m, dict) else m.metadata) or {}
        yield md


def _vectors_of(fetched):
    """A `fetch` response's records, in either SDK shape. Keys only are ever used: this
    answers presence, and pulling 3072 floats per id to answer yes/no is what made
    extracting the pool cost ~168s."""
    return fetched.get("vectors", {}) if isinstance(fetched, dict) else fetched.vectors
