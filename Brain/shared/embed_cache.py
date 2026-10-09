"""On-disk embedding cache so threshold tuning does not re-embed the corpus.

Keyed on sha256(model | prefix | text). The prefix matters because bge uses a
query instruction prefix, so the same string embeds differently as a query than
as a document.

Vectors are stored float32, matching what the model emits. An earlier version
stored float16 on the reasoning that these embeddings are L2-normalised so fp16
rounding moves a cosine similarity by under 1e-3. That reasoning holds for
cosine comparisons and is still wrong here: UMAP and HDBSCAN run *upstream* of
any threshold, and their neighbour graphs amplify tie-breaks. The same corpus at
the same seed produced 241 raw clusters uncached and 231 cached. Reproducible
calibration requires bit-identical vectors, so the extra 2 bytes per dimension
is not optional.

Stores derived vectors only. No transcript text is written to this file.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import numpy as np

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vectors (
    key TEXT PRIMARY KEY,
    dim INTEGER NOT NULL,
    vec BLOB NOT NULL
)
"""

# SQLite caps host variables per statement; stay well under the 999 default.
_CHUNK = 500


def _key(model: str, prefix: str, text: str) -> str:
    return hashlib.sha256(f"{model}|{prefix}|{text}".encode("utf-8")).hexdigest()


class EmbedCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get_many(self, model: str, prefix: str, texts: list[str]) -> dict[int, np.ndarray]:
        """Return {index_in_texts: vector} for whichever texts are already cached.

        Values stay as numpy arrays. Converting each one to a Python list here
        would allocate ~56 million float objects for a 74k-clause corpus, which
        costs more than re-embedding the whole thing on a GPU -- the opposite of
        what a cache is for. Callers that need lists convert once, at the end.
        """
        if not texts:
            return {}
        keys = [_key(model, prefix, t) for t in texts]
        found: dict[str, np.ndarray] = {}
        for start in range(0, len(keys), _CHUNK):
            chunk = keys[start:start + _CHUNK]
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT key, dim, vec FROM vectors WHERE key IN ({placeholders})", chunk
            ).fetchall()
            for k, dim, blob in rows:
                # A row written by the old float16 build has half the expected
                # bytes. Treat it as a miss so the caller re-embeds and
                # overwrites it, rather than returning a half-length vector.
                if len(blob) != dim * 4:
                    continue
                found[k] = np.frombuffer(blob, dtype=np.float32)
        return {i: found[k] for i, k in enumerate(keys) if k in found}

    def put_many(self, model: str, prefix: str, texts: list[str], vecs: list[list[float]]) -> None:
        if not texts:
            return
        rows = [
            (_key(model, prefix, t), len(v), np.asarray(v, dtype=np.float32).tobytes())
            for t, v in zip(texts, vecs)
        ]
        self._conn.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?)", rows)
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]

    def close(self) -> None:
        self._conn.close()


_instance: EmbedCache | None = None


def get_cache(path: str | Path) -> EmbedCache:
    """Module-level singleton -- reopening SQLite per batch is needless overhead."""
    global _instance
    if _instance is None:
        _instance = EmbedCache(path)
    return _instance


# --- the gateway cache (added 2026-08-19) ----------------------------------
# A SECOND cache with a DIFFERENT schema and a DIFFERENT key, deliberately not merged into
# EmbedCache above. It is the file the Joveo gateway corpus was actually paid into:
# `Brain/gemini_embed_cache.db`, table `vec(k, dims, v)`, keyed sha256("model|dims|text").
#
# WHY NOT JUST REKEY IT INTO `vectors`. Because the vectors already exist under those keys —
# every trigger, every response clause and the whole taxonomy for this corpus — and a
# migration would either re-embed them (~12k gateway requests at 140/min) or hand-copy a
# database this project treats as a paid artifact. Reading the file where it lies is free.
#
# *** THE PREFIX IS IGNORED HERE, AND THAT IS CORRECT ONLY ON THIS BACKEND. *** On
# gemini-embedding-2 the task_type is INERT — all four values return byte-identical vectors,
# cosine 1.0000, measured 2026-08-13 — which is exactly why the gateway cache was keyed
# without one. *** THIS WOULD BE WRONG ON bge ***, whose embed_query genuinely prepends an
# instruction prefix and returns a different vector; keying its query and document vectors
# to one slot would serve the wrong vector silently. Hence two cache classes rather than one
# with a flag: the distinction is a property of the model, not a caller's preference.

_GATEWAY_SCHEMA = """
CREATE TABLE IF NOT EXISTS vec (
    k TEXT PRIMARY KEY,
    dims INTEGER NOT NULL,
    v BLOB NOT NULL
)
"""


# The NATIVE width of gemini-embedding-2, and the width every cached vector was stored at.
# It is NOT the width a caller may ask for.
_GATEWAY_NATIVE_DIMS = 3072


def _gateway_key(model: str, text: str) -> str:
    """sha256("name|NATIVE_dims|text"). The caller's requested width is NOT in the key.

    *** THIS IS THE POINT, AND KEYING ON THE REQUESTED WIDTH INSTEAD SILENTLY RE-BUYS THE
    CORPUS. *** Every vector in this file was stored at the model's native 3072, and
    Matryoshka truncation is exact, so a 768-dim request is served by slicing the cached 3072
    vector -- which is why calibration can re-analyse at any width for free. Keying on the
    requested width would make `gemini_dimensions: 768` miss all ~196k rows and re-embed the
    whole corpus at 140 requests/min. Caught by tests/test_gateway_backend.py before it could
    happen; `calibration/trial_pool_unit_gemini._key` has always keyed on the native width for
    the same reason.
    """
    name, _, _requested = model.partition("@")
    return hashlib.sha256(
        f"{name}|{_GATEWAY_NATIVE_DIMS}|{text}".encode("utf-8")
    ).hexdigest()


class GatewayVecCache:
    """Same get_many/put_many surface as EmbedCache, over the gateway's `vec` schema.

    Matching the interface is what lets `_embed_matrix` stay one code path for both
    backends instead of forking on the cache type.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute(_GATEWAY_SCHEMA)
        self._conn.commit()

    def get_many(self, model: str, prefix: str, texts: list[str]) -> dict[int, np.ndarray]:
        if not texts:
            return {}
        _, _, dims = model.partition("@")
        want = int(dims) if dims else 0
        keys = [_gateway_key(model, t) for t in texts]
        found: dict[str, np.ndarray] = {}
        for start in range(0, len(keys), _CHUNK):
            chunk = keys[start:start + _CHUNK]
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT k, dims, v FROM vec WHERE k IN ({placeholders})", chunk
            ).fetchall()
            for k, dim, blob in rows:
                if len(blob) != dim * 4:
                    continue
                vec = np.frombuffer(blob, dtype=np.float32)
                if want and dim != want:
                    # Matryoshka truncation is EXACT on this model (measured: asking the API
                    # for 768 and slicing 768 off a 3072 vector give cosine 1.00000), so a
                    # wider cached vector legitimately serves a narrower request.
                    if dim < want:
                        continue
                    vec = vec[:want]
                # RENORMALISE UNCONDITIONALLY, not just after truncation.
                #
                # Truncation obviously needs it -- cutting a unit vector's tail leaves
                # ||v|| < 1 and every downstream dot product silently stops being a cosine.
                # The un-truncated case gets it too so this path matches
                # `calibration/layer_bc_arms._load_cached`, the cache-only shim every Layer
                # B/C measurement on this corpus was taken through, which divides by the norm
                # on EVERY read.
                #
                # THAT MATCH IS TO ~1e-7, NOT BIT-FOR-BIT, AND IT CANNOT BE MADE EXACT.
                # Measured 2026-08-19 over 300 real triggers: 85 of 300 rows differ in the
                # last float32 bit (max 2.98e-8), in BOTH directions. The cause is reduction
                # order, not a logic difference -- the shim normalises the whole (n, 3072)
                # matrix at once, so numpy's pairwise summation blocks differently than it
                # does for the single row normalised here. Same arithmetic, different
                # association. It is the same class of irreducible noise CLAUDE.md already
                # records for CUDA matmul order on bge, and at 1e-8 against a cosine band
                # whose decisions turn on ~1e-2 it cannot change any routing outcome.
                # calibration/gateway_backend_check.py therefore asserts agreement to a
                # float32 tolerance plus cosine 1.0, not equality.
                vec = vec / (np.linalg.norm(vec) + 1e-10)
                found[k] = vec.astype(np.float32)
        return {i: found[k] for i, k in enumerate(keys) if k in found}

    def put_many(self, model: str, prefix: str, texts: list[str],
                 vecs: list[list[float]]) -> None:
        if not texts:
            return
        rows = [
            (_gateway_key(model, t), len(v), np.asarray(v, dtype=np.float32).tobytes())
            for t, v in zip(texts, vecs)
        ]
        self._conn.executemany("INSERT OR REPLACE INTO vec VALUES (?, ?, ?)", rows)
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM vec").fetchone()[0]

    def close(self) -> None:
        self._conn.close()


_gateway_instance: GatewayVecCache | None = None


def get_gateway_cache(path: str | Path) -> GatewayVecCache:
    """Module-level singleton, separate from get_cache's -- the two are different files."""
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = GatewayVecCache(path)
    return _gateway_instance
