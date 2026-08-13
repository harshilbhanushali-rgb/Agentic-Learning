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

_backend_override: str | None = None


def set_backend(name: str | None) -> None:
    """Override tuning.yaml's backend for THIS PROCESS only.

    Exists so a calibration harness can compare backends without editing the shipped
    config -- editing tuning.yaml to run a comparison is how a temporary experiment
    becomes the production default by accident. Pass None to fall back to the file.

    The cache key follows the override (see _cache_model_key), so vectors from the two
    backends never collide and switching back never re-embeds anything.
    """
    global _backend_override
    _backend_override = name


def _active_backend() -> str:
    return _backend_override or get_tuning().embedding.backend


_reverse_key_order = False


def set_key_order(reverse: bool) -> None:
    """Try the LAST configured key first, for this process only.

    Both keys look identical to the picker on a cold start -- neither has history, so it
    takes keys[0] and that key absorbs the opening burst. When one key has already been
    worked hard (or is nearer a daily ceiling), starting from the other end spreads the
    load instead of reproducing the imbalance. After the first minute the headroom picker
    balances them regardless of order.
    """
    global _reverse_key_order
    _reverse_key_order = reverse


def _ordered_keys(keys: list[str]) -> list[str]:
    return list(reversed(keys)) if _reverse_key_order else keys


def _encode(texts: list[str], prefix: str) -> list[list[float]]:
    """Dispatch to whichever backend is active. The only fork in this module."""
    backend = _active_backend()
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
    # The symmetric sentinel is a task-type marker, not text -- prepending it would embed
    # a control string.
    prefix = "" if prefix == SYMMETRIC_PREFIX else prefix
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
#
# *** task_type IS INERT ON gemini-embedding-2 -- MEASURED 2026-08-13. ***
# All four valid values (RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY / SEMANTIC_SIMILARITY /
# CLUSTERING) return BYTE-IDENTICAL vectors, cosine 1.0000. It is not being dropped: the
# SDK rejects unknown config keys with a pydantic error and the API rejects an invalid
# task_type with a 400, so the enum is validated and then simply has no effect on this
# model. Consequence: **Gemini has no query/document asymmetry at all**, unlike bge, whose
# embed_query genuinely produces a different vector. Any design that leans on that split
# -- layer_b matching a short utterance against an abstract scenario description -- loses
# the mechanism entirely on this backend, it does not merely change it.
#
# The mapping is kept because it is correct for bge and may be honoured by other models;
# it is just currently a no-op here. Do not "fix" a result by changing task_type.
#
# SYMMETRIC_PREFIX is a sentinel, never prepended to any text. bge has no equivalent, so
# the local backend treats the sentinel as no prefix.
SYMMETRIC_PREFIX = "\x00symmetric\x00"
_GEMINI_TASK = {_QUERY_PREFIX: "RETRIEVAL_QUERY", "": "RETRIEVAL_DOCUMENT",
                SYMMETRIC_PREFIX: "SEMANTIC_SIMILARITY"}

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
# PER KEY, not global. The limits are enforced per key, so a global budget aimed at
# whichever key is tried first wastes every other key: measured 2026-08-13, a global
# 100 RPM throttle sent all 100 to key 1, which then 429'd on its own RPM ceiling while
# key 2 sat idle picking up only the overflow. Two keys, one key's throughput.
_RPM_LIMIT = 100
_TPM_LIMIT = 30_000
_RATE_WINDOW = 60.0
_recent_by_key: dict[str, list[tuple[float, int]]] = {}


def _headroom(key: str, tokens: int) -> bool:
    """Does this key have room for a request of this size inside its own rolling minute?"""
    now = time.time()
    hist = [(t, n) for t, n in _recent_by_key.get(key, []) if now - t < _RATE_WINDOW]
    _recent_by_key[key] = hist
    return (len(hist) < _RPM_LIMIT
            and sum(n for _, n in hist) + tokens <= _TPM_LIMIT)


def _record(key: str, tokens: int) -> None:
    _recent_by_key.setdefault(key, []).append((time.time(), tokens))


def _pick_key(keys: list[str], tokens: int) -> str:
    """The first unparked key with headroom, waiting only if every key is saturated.

    Ordering by headroom rather than always starting at keys[0] is what actually uses a
    second key: with 2 keys this roughly doubles throughput instead of making key 2 a
    failover that only sees traffic after key 1 has already 429'd.
    """
    while True:
        for key in _available(keys) or []:
            if _headroom(key, tokens):
                return key
        now = time.time()
        waits = []
        for key in keys:
            hist = _recent_by_key.get(key, [])
            if hist:
                waits.append(_RATE_WINDOW - (now - min(t for t, _ in hist)) + 0.15)
            parked = _key_parked_until.get(key, 0.0) - now
            if parked > 0:
                waits.append(parked + 0.15)
        time.sleep(max(0.25, min(waits) if waits else 0.25))


def _estimate_tokens(text: str) -> int:
    """~4 characters per token. Deliberately rough and deliberately an OVER-estimate for
    short strings (the +8 floor), because under-estimating means a 429 while
    over-estimating only costs a little throughput."""
    return max(8, len(text) // 4 + 8)


# _throttle is gone. It enforced ONE global budget and then spent all of it on whichever
# key was tried first, so a second key only ever saw traffic after the first had already
# 429'd. Rate accounting is per key now -- see _pick_key.


# A key that hit a limit is parked rather than retried on the very next request. Without
# this, an exhausted key costs a wasted round-trip on EVERY subsequent call -- observed
# 2026-08-13, key 1 exhausted its daily quota and every one of the remaining ~330 requests
# paid a rejection before falling through to key 2.
#
# The park doubles on consecutive failures because a per-minute limit and a per-DAY limit
# report the same message, and nothing in the error distinguishes them. Backing off
# geometrically costs one wasted call every few minutes for a dead key, while a key that
# was merely rate-limited comes back on its own.
_key_parked_until: dict[str, float] = {}
_key_fail_streak: dict[str, int] = {}
_PARK_BASE = 60.0
_PARK_MAX = 900.0

# How many hosted embeddings to buy before writing them to the cache. Small enough that a
# crash loses little, large enough that the sqlite write is not per-request.
_CACHE_FLUSH_EVERY = 25


def _park(key: str) -> None:
    streak = _key_fail_streak.get(key, 0) + 1
    _key_fail_streak[key] = streak
    _key_parked_until[key] = time.time() + min(_PARK_BASE * 2 ** (streak - 1), _PARK_MAX)


def _unpark(key: str) -> None:
    _key_fail_streak.pop(key, None)
    _key_parked_until.pop(key, None)


def _available(keys: list[str]) -> list[str]:
    """Keys not currently parked, in order. Empty means every key is cooling down."""
    now = time.time()
    return [k for k in keys if _key_parked_until.get(k, 0.0) <= now]


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

    Vectors are L2-normalised here defensively. MEASURED 2026-08-13: this model already
    returns unit vectors at EVERY width (3072/1536/768/256), so the normalisation is
    currently a no-op -- an earlier comment here claimed truncated output arrives
    un-normalised, which is false for gemini-embedding-2. It stays because everything
    downstream computes cosine as a bare dot product, so a model that ever returned
    un-normalised vectors would corrupt every similarity silently rather than raising.

    Also measured: Matryoshka truncation is EXACT. Asking the API for 768 and slicing the
    first 768 values off a 3072 vector give cosine 1.00000. So one call at full width
    yields every narrower width for free, and changing your mind about dimensions never
    requires re-embedding a corpus.
    """
    from config import load_config

    cfg = get_tuning().embedding
    keys = _ordered_keys(list(load_config().gemma_api_keys)
                         or [load_config().gemma_api_key])
    task = _GEMINI_TASK.get(prefix, "RETRIEVAL_DOCUMENT")

    out: list[list[float]] = []
    for i, text in enumerate(texts):
        tokens = _estimate_tokens(text)
        vector, last_err = None, None
        for attempt in range(_MAX_ROUNDS):
            # Choose a key that has room, rather than always starting at the first one.
            usable = [_pick_key(keys, tokens)]
            for n, key in enumerate(usable):
                _record(key, tokens)
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
                    _unpark(key)
                    break
                except Exception as e:                      # noqa: BLE001 - classified below
                    last_err, kind = e, _classify(e)
                    if kind == "fatal":
                        raise
                    if kind == "limit":
                        _park(key)
                        wait = _key_parked_until[key] - time.time()
                        print(f"[embedder] key {n + 1}/{len(usable)} limited; "
                              f"parked {wait:.0f}s")
                    else:
                        print(f"[embedder] key {n + 1}/{len(usable)} {kind}: {str(e)[:100]}")
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
    if _active_backend() == "local":
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
        # Cache in CHUNKS, not once at the end. put_many used to run only after _encode
        # finished the whole list, so a crash partway through discarded every vector
        # already paid for -- measured 2026-08-13, a run died at 200 of 405 and lost all
        # 200. Harmless when embedding is local and free; on a metered backend it is real
        # money. Same rule as flushing paid LLM results before anything free can block them.
        chunk = _CACHE_FLUSH_EVERY if _active_backend() != "local" else len(missing)
        for start in range(0, len(missing), chunk):
            idx = missing[start:start + chunk]
            fresh = _encode([texts[i] for i in idx], prefix)
            cache.put_many(model_key, prefix, [texts[i] for i in idx], fresh)
            cached.update({i: np.asarray(v, dtype=np.float32) for i, v in zip(idx, fresh)})
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
