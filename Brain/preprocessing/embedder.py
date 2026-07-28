from __future__ import annotations
from pathlib import Path
import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from shared import embed_cache
from shared.tuning import get_tuning

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

def _encode(texts: list[str], prefix: str) -> list[list[float]]:
    model = _get_model()
    inputs = [prefix + t for t in texts] if prefix else texts
    vecs = model.encode(inputs, batch_size=_BATCH_SIZE, normalize_embeddings=True, show_progress_bar=False)
    return vecs.tolist()

def _embed_matrix(texts: list[str], prefix: str = "") -> np.ndarray:
    """Embed with a disk cache so re-running a stage does not re-encode the corpus.

    Keyed on prefix as well as text -- bge embeds the same string differently
    as a query than as a document.

    Returns a (n, dim) float32 array. Everything downstream does linear algebra
    on these, so staying in numpy avoids materialising tens of millions of Python
    floats on the cache-hit path.
    """
    if not texts:
        return np.empty((0, 0), dtype=np.float32)
    cfg = get_tuning().embedding
    if not cfg.cache_enabled:
        return np.asarray(_encode(texts, prefix), dtype=np.float32)

    cache = embed_cache.get_cache(Path(__file__).parent.parent / cfg.cache_path)
    cached = cache.get_many(_MODEL_NAME, prefix, texts)
    missing = [i for i in range(len(texts)) if i not in cached]
    if missing:
        fresh = _encode([texts[i] for i in missing], prefix)
        cache.put_many(_MODEL_NAME, prefix, [texts[i] for i in missing], fresh)
        cached.update({i: np.asarray(v, dtype=np.float32) for i, v in zip(missing, fresh)})
    return np.stack([cached[i] for i in range(len(texts))])


def embed_query_matrix(texts: list[str]) -> np.ndarray:
    """Prefer this over embed_query for large pools -- no list round-trip."""
    return _embed_matrix(texts, _QUERY_PREFIX)

def embed_document_matrix(texts: list[str]) -> np.ndarray:
    return _embed_matrix(texts)

def embed_query(texts: list[str]) -> list[list[float]]:
    return _embed_matrix(texts, _QUERY_PREFIX).tolist()

def embed_document(texts: list[str]) -> list[list[float]]:
    return _embed_matrix(texts).tolist()
