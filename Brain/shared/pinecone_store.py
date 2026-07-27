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

def init_index(api_key: str, index_name: str) -> None:
    pc = _get_client(api_key)
    if index_name not in [i.name for i in pc.list_indexes()]:
        pc.create_index(
            name=index_name,
            dimension=768,  # BAAI/bge-base-en-v1.5 (local embedder)
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        print(f"[pinecone] Created index '{index_name}'.")
    else:
        print(f"[pinecone] Index '{index_name}' already exists.")

def upsert_pairs(api_key: str, index_name: str, pairs: list[dict]) -> None:
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
    response_vecs = [(
        f"response_{p['pair_id']}",
        p["response_vec"],
        {"pair_id": p["pair_id"], "call_id": p["call_id"],
         "scenario_key": p.get("scenario_key") or "", "turn_index": p["turn_index"],
         "text": p["response_text"][:500]},
    ) for p in pairs]
    BATCH = 100
    for i in range(0, len(trigger_vecs), BATCH):
        idx.upsert(vectors=trigger_vecs[i:i+BATCH], namespace="triggers")
    for i in range(0, len(response_vecs), BATCH):
        idx.upsert(vectors=response_vecs[i:i+BATCH], namespace="responses")

def query_triggers(api_key: str, index_name: str, query_vec: list[float],
                   top_k: int = 5, scenario_key: str | None = None) -> list[dict]:
    idx = _get_index(api_key, index_name)
    filter_ = {"scenario_key": {"$eq": scenario_key}} if scenario_key else None
    results = idx.query(vector=query_vec, top_k=top_k, namespace="triggers",
                        include_metadata=True, filter=filter_)
    return results.get("matches", [])
