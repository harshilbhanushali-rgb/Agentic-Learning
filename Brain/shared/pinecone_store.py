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
