from __future__ import annotations
import torch
from sentence_transformers import SentenceTransformer

_MODEL_NAME = "BAAI/bge-base-en-v1.5"
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
_BATCH_SIZE = 256 if _DEVICE == "cuda" else 64

_model: SentenceTransformer | None = None

def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"[embedder] Loading local model {_MODEL_NAME} on {_DEVICE}...")
        _model = SentenceTransformer(_MODEL_NAME, device=_DEVICE)
    return _model

def _embed(texts: list[str], prefix: str = "") -> list[list[float]]:
    if not texts:
        return []
    model = _get_model()
    inputs = [prefix + t for t in texts] if prefix else texts
    vecs = model.encode(inputs, batch_size=_BATCH_SIZE, normalize_embeddings=True, show_progress_bar=False)
    return vecs.tolist()

def embed_query(texts: list[str]) -> list[list[float]]:
    return _embed(texts, _QUERY_PREFIX)

def embed_document(texts: list[str]) -> list[list[float]]:
    return _embed(texts)
