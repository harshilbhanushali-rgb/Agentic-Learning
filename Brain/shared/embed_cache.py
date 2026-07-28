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
