from __future__ import annotations
import time
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
# Floor for the OOM backoff in _encode. Below this, a batch is small enough that an
# OOM is about the model or the machine, not the batch, so failing loudly is right.
_MIN_BATCH_SIZE = 8

_model: SentenceTransformer | None = None

def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"[embedder] Loading local model {_MODEL_NAME} on {_DEVICE}...")
        _model = SentenceTransformer(_MODEL_NAME, device=_DEVICE)
    return _model

def _encode(texts: list[str], prefix: str) -> list[list[float]]:
    """Dispatch to whichever backend tuning.yaml selects. The only fork in this module."""
    backend = get_tuning().embedding.backend
    if backend == "local":
        return _encode_local(texts, prefix)
    if backend == "gemini":
        return _encode_gemini(texts, prefix)
    raise ValueError(f"unknown embedding backend {backend!r}; expected 'local' or 'gemini'")


def _encode_local(texts: list[str], prefix: str) -> list[list[float]]:
    """Encode with an automatic batch-size backoff on CUDA OOM.

    _BATCH_SIZE is tuned for the sentence-length CLAUSES Layer A embeds. Layer D
    (ego_trap) embeds whole SPEAKER TURNS, which are far longer -- 256 of them at
    bge's 512-token limit overflowed a 6GB card, so a fixed batch size makes the
    embedder's usability depend on which layer is calling it.

    Halving on OOM rather than exposing a knob, because the right batch size is a
    property of the machine and the text length, not a decision the caller can
    reasonably make. Embeddings are unaffected: batching only groups the forward
    passes, so the vectors -- and therefore the cache -- are identical either way.
    """
    model = _get_model()
    inputs = [prefix + t for t in texts] if prefix else texts
    batch = _BATCH_SIZE
    while True:
        try:
            vecs = model.encode(
                inputs, batch_size=batch, normalize_embeddings=True, show_progress_bar=False
            )
            return vecs.tolist()
        except torch.OutOfMemoryError:
            if batch <= _MIN_BATCH_SIZE:
                raise
            batch //= 2
            # Hand the freed blocks back, or the next attempt inherits the
            # fragmentation that caused this one to fail.
            if _DEVICE == "cuda":
                torch.cuda.empty_cache()
            print(f"[embedder] CUDA OOM — retrying at batch_size={batch}")

# --- hosted backend -------------------------------------------------------------------
#
# bge encodes query-vs-document by PREPENDING a text prefix. Gemini expresses the same
# asymmetry as a task type, so the prefix is translated rather than sent as text -- sending
# bge's instruction sentence to Gemini would embed the instruction itself.
_GEMINI_TASK = {_QUERY_PREFIX: "RETRIEVAL_QUERY", "": "RETRIEVAL_DOCUMENT"}

# Same split gemma.py draws: a quota error means this key is done, so rotate immediately
# rather than sleeping on it; a transient error means retry the same key with backoff.
_LIMIT_MARKERS = ("429", "resource_exhausted", "quota", "rate limit", "exhausted")
_TRANSIENT_MARKERS = ("500", "503", "504", "deadline", "unavailable", "internal",
                      "connection", "timeout", "timed out", "disconnect")
_MAX_ROUNDS = 5

# MEASURED 2026-08-13, not assumed: embed_content(contents=[3 strings]) returns ONE
# embedding. The sync endpoint treats a list as the parts of a single document, so it
# cannot batch -- N texts cost N requests. The first version assumed list-in/list-out and
# silently produced 2 vectors for 161 scenarios, which surfaced as an IndexError only
# because a boolean mask happened to check the length.
#
# Consequence for production: a 74k-clause backfill is 74k requests against a 1k/day cap,
# i.e. impossible on this endpoint. That is what client.batches.create_embeddings is for.
_SYNC_EMBEDS_ONE_AT_A_TIME = True

# Both ceilings are enforced, because the binding one changes with text length. Measured
# on the first real run: 6/100 RPM and 7/1000 RPD used while TPM hit 34.66K/30K -- tokens
# blew first and by a wide margin, so pacing on request count alone would 429 immediately.
_RPM_LIMIT = 100
_TPM_LIMIT = 30_000
_RATE_WINDOW = 60.0
_recent_calls: list[tuple[float, int]] = []


def _estimate_tokens(text: str) -> int:
    """~4 characters per token. Deliberately rough and deliberately an OVER-estimate for
    short strings (the +8 floor), because under-estimating means a 429 while
    over-estimating only costs a little throughput."""
    return max(8, len(text) // 4 + 8)


def _throttle(tokens: int) -> None:
    """Block until this request fits inside BOTH rolling-60s budgets."""
    while True:
        now = time.time()
        _recent_calls[:] = [(t, n) for t, n in _recent_calls if now - t < _RATE_WINDOW]
        spent = sum(n for _, n in _recent_calls)
        if len(_recent_calls) < _RPM_LIMIT and spent + tokens <= _TPM_LIMIT:
            _recent_calls.append((now, tokens))
            return
        oldest = min(t for t, _ in _recent_calls)
        time.sleep(max(0.25, _RATE_WINDOW - (now - oldest) + 0.15))


def _classify(err: Exception) -> str:
    text = str(err).lower()
    if any(m in text for m in _LIMIT_MARKERS):
        return "limit"
    if any(m in text for m in _TRANSIENT_MARKERS):
        return "transient"
    return "fatal"


_gemini_clients: dict[str, object] = {}


def _gemini_client(key: str):
    """One client per key, held at module level.

    Building it inline per call -- genai.Client(...).models.embed_content(...) -- lets the
    temporary be garbage-collected mid-request and raises "Cannot send a request, as the
    client has been closed". Same rule pinecone_store already learned: these objects are
    long-lived handles, not per-call values.
    """
    from google import genai
    if key not in _gemini_clients:
        _gemini_clients[key] = genai.Client(api_key=key)
    return _gemini_clients[key]


def _encode_gemini(texts: list[str], prefix: str) -> list[list[float]]:
    """Hosted embeddings, rotating across every configured API key.

    KEY ROTATION, not just retry. With a hard requests-per-day cap, a second key is a
    second day's quota -- so a limit error rotates keys immediately instead of sleeping,
    and only when EVERY key has hit a limit in the same round does it back off and start
    the chain again. Mirrors call_gemma's escalate-then-rotate structure so both surfaces
    behave the same way under quota pressure.

    Vectors are always L2-normalised here. Gemini only normalises its full-width output,
    so a truncated Matryoshka vector arrives un-normalised -- and everything downstream in
    this codebase computes cosine as a bare dot product. Skipping this would not raise;
    it would silently shift every similarity in the pipeline.
    """
    from config import load_config

    cfg = get_tuning().embedding
    keys = list(load_config().gemma_api_keys) or [load_config().gemma_api_key]
    task = _GEMINI_TASK.get(prefix, "RETRIEVAL_DOCUMENT")

    out: list[list[float]] = []
    for i, text in enumerate(texts):
        _throttle(_estimate_tokens(text))
        vector, last_err = None, None
        for attempt in range(_MAX_ROUNDS):
            for n, key in enumerate(keys):
                try:
                    resp = _gemini_client(key).models.embed_content(
                        model=cfg.gemini_model,
                        contents=text,
                        config={"task_type": task,
                                "output_dimensionality": cfg.gemini_dimensions},
                    )
                    got = resp.embeddings
                    if len(got) != 1:
                        raise RuntimeError(
                            f"expected 1 embedding for 1 text, got {len(got)}")
                    vector = got[0].values
                    break
                except Exception as e:                      # noqa: BLE001 - classified below
                    last_err, kind = e, _classify(e)
                    if kind == "fatal":
                        raise
                    print(f"[embedder] key {n + 1}/{len(keys)} {kind}: {str(e)[:120]}")
            if vector is not None:
                break
            wait = 2 ** (attempt + 1)
            print(f"[embedder] all {len(keys)} keys unavailable; waiting {wait}s")
            time.sleep(wait)
        if vector is None:
            raise RuntimeError(f"embedding failed after {_MAX_ROUNDS} rounds: {last_err}")

        v = np.asarray(vector, dtype=np.float32)
        out.append((v / (np.linalg.norm(v) + 1e-10)).tolist())
        if (i + 1) % 25 == 0 or i + 1 == len(texts):
            print(f"[embedder] {i + 1}/{len(texts)}", flush=True)

    if len(out) != len(texts):
        # The failure that started this: fewer vectors than texts, surfacing far away as a
        # shape error. Fail here, where the cause is legible.
        raise RuntimeError(f"embedded {len(out)} vectors for {len(texts)} texts")
    return out


def _cache_model_key() -> str:
    """What the cache is keyed on. MUST carry the dimension.

    A 768-truncated vector and a 3072 vector come from the same model name but are
    different vectors, so keying on the name alone would serve one where the other was
    asked for -- silently, and only for texts that happened to be cached already.
    """
    cfg = get_tuning().embedding
    if cfg.backend == "local":
        return _MODEL_NAME
    return f"{cfg.gemini_model}@{cfg.gemini_dimensions}"


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
    model_key = _cache_model_key()
    cached = cache.get_many(model_key, prefix, texts)
    missing = [i for i in range(len(texts)) if i not in cached]
    if missing:
        fresh = _encode([texts[i] for i in missing], prefix)
        cache.put_many(model_key, prefix, [texts[i] for i in missing], fresh)
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
