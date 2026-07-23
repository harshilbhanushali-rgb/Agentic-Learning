from __future__ import annotations
import os
from pinecone import Pinecone

_pc = None
_BATCH_SIZE = 96  # Pinecone's hard input-batch limit for llama-text-embed-v2

def _get_client() -> Pinecone:
    global _pc
    if _pc is None:
        from dotenv import load_dotenv
        load_dotenv()
        _pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    return _pc

def _embed(texts: list[str], input_type: str) -> list[list[float]]:
    if not texts:
        return []
    pc = _get_client()
    vecs: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i:i + _BATCH_SIZE]
        result = pc.inference.embed(
            model="llama-text-embed-v2",
            inputs=batch,
            parameters={"input_type": input_type, "dimension": 2048, "truncate": "END"},
        )
        vecs.extend(e.values for e in result)
    return vecs

def embed_query(texts: list[str]) -> list[list[float]]:
    return _embed(texts, "query")

def embed_document(texts: list[str]) -> list[list[float]]:
    return _embed(texts, "passage")
