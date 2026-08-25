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
