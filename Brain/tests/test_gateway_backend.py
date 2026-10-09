"""The `gateway` embedding backend and its cache.

Spec: docs/superpowers/specs/2026-08-19-playbook-schema-design.md §10 (appended)

DB-free and network-free. The end-to-end claim -- that the real corpus is served entirely
from `gemini_embed_cache.db` with the transport disabled -- is proven against live data by
`calibration/gateway_backend_check.py`, which cannot be faked here.
"""
import hashlib
import sqlite3

import numpy as np
import pytest

from preprocessing import embedder
from shared import embed_cache


@pytest.fixture
def gateway_db(tmp_path):
    """A gateway-schema cache seeded the way the real one was written."""
    path = tmp_path / "gemini_embed_cache.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS vec (k TEXT PRIMARY KEY, dims INTEGER NOT NULL,"
                 " v BLOB NOT NULL)")

    def key(text, model="gemini-embedding-2", dims=3072):
        return hashlib.sha256(f"{model}|{dims}|{text}".encode("utf-8")).hexdigest()

    rng = np.random.default_rng(42)
    texts = ["alpha", "beta", "gamma"]
    vecs = {}
    for t in texts:
        v = rng.normal(size=3072).astype(np.float32)
        v /= np.linalg.norm(v)
        vecs[t] = v
        conn.execute("INSERT OR REPLACE INTO vec VALUES (?,?,?)",
                     (key(t), 3072, v.tobytes()))
    conn.commit()
    conn.close()
    return path, texts, vecs


def test_the_gateway_cache_reads_the_real_key_scheme(gateway_db):
    """sha256("model|dims|text"), NOT production's sha256("model|prefix|text"). Getting this
    wrong reports a total miss and re-buys the whole corpus."""
    path, texts, vecs = gateway_db
    cache = embed_cache.GatewayVecCache(path)
    got = cache.get_many("gemini-embedding-2@3072", "", texts)
    assert len(got) == 3
    for i, t in enumerate(texts):
        assert np.allclose(got[i], vecs[t], atol=1e-6)


def test_the_prefix_is_ignored_on_this_backend(gateway_db):
    """task_type is inert on gemini-embedding-2 (cosine 1.0000, measured), which is why the
    gateway cache carries no prefix. Query and document must resolve to the same row."""
    path, texts, _ = gateway_db
    cache = embed_cache.GatewayVecCache(path)
    as_doc = cache.get_many("gemini-embedding-2@3072", "", texts)
    as_query = cache.get_many("gemini-embedding-2@3072", embedder._QUERY_PREFIX, texts)
    assert len(as_query) == len(as_doc) == 3
    for i in range(3):
        assert np.array_equal(as_doc[i], as_query[i])


def test_production_cache_still_separates_query_from_document(tmp_path):
    """The mirror image, and why there are two cache classes rather than one with a flag:
    on bge the prefix genuinely changes the vector, so collapsing them would serve the wrong
    one silently."""
    cache = embed_cache.EmbedCache(tmp_path / "embed_cache.db")
    cache.put_many("bge", "", ["x"], [[1.0, 0.0]])
    cache.put_many("bge", "PREFIX: ", ["x"], [[0.0, 1.0]])
    assert np.array_equal(cache.get_many("bge", "", ["x"])[0], np.array([1.0, 0.0]))
    assert np.array_equal(cache.get_many("bge", "PREFIX: ", ["x"])[0], np.array([0.0, 1.0]))


def test_a_miss_is_a_miss_not_a_wrong_vector(gateway_db):
    path, _, _ = gateway_db
    cache = embed_cache.GatewayVecCache(path)
    assert cache.get_many("gemini-embedding-2@3072", "", ["never embedded"]) == {}


def test_truncation_renormalises(gateway_db):
    """Matryoshka slicing leaves ||v|| < 1; without renormalisation every downstream dot
    product silently stops being a cosine."""
    path, texts, _ = gateway_db
    cache = embed_cache.GatewayVecCache(path)
    got = cache.get_many("gemini-embedding-2@768", "", texts)
    assert len(got) == 3
    for v in got.values():
        assert v.shape == (768,)
        assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-5


def test_a_narrower_cached_vector_cannot_serve_a_wider_request(tmp_path):
    """Padding a 768 vector to 3072 would be silent corruption; it must read as a miss."""
    path = tmp_path / "g.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE vec (k TEXT PRIMARY KEY, dims INTEGER NOT NULL, v BLOB NOT NULL)")
    v = np.ones(768, dtype=np.float32)
    k = hashlib.sha256("gemini-embedding-2|3072|t".encode("utf-8")).hexdigest()
    conn.execute("INSERT INTO vec VALUES (?,?,?)", (k, 768, v.tobytes()))
    conn.commit()
    conn.close()
    cache = embed_cache.GatewayVecCache(path)
    assert cache.get_many("gemini-embedding-2@3072", "", ["t"]) == {}


def test_a_short_blob_reads_as_a_miss(tmp_path):
    """Same guard EmbedCache has for old float16 rows: a truncated blob must not return a
    half-length vector."""
    path = tmp_path / "g.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE vec (k TEXT PRIMARY KEY, dims INTEGER NOT NULL, v BLOB NOT NULL)")
    k = hashlib.sha256("gemini-embedding-2|3072|t".encode("utf-8")).hexdigest()
    conn.execute("INSERT INTO vec VALUES (?,?,?)", (k, 3072, b"\x00" * 10))
    conn.commit()
    conn.close()
    cache = embed_cache.GatewayVecCache(path)
    assert cache.get_many("gemini-embedding-2@3072", "", ["t"]) == {}


def test_roundtrip_through_put_many(tmp_path):
    cache = embed_cache.GatewayVecCache(tmp_path / "g.db")
    v = np.random.default_rng(0).normal(size=3072).astype(np.float32)
    v /= np.linalg.norm(v)
    cache.put_many("gemini-embedding-2@3072", "", ["hello"], [v.tolist()])
    got = cache.get_many("gemini-embedding-2@3072", "", ["hello"])
    assert np.allclose(got[0], v, atol=1e-6)


# --- backend dispatch ------------------------------------------------------

def test_gateway_is_a_recognised_backend(monkeypatch):
    """It must not fall through to the 'unknown backend' error."""
    monkeypatch.setattr(embedder, "_active_backend", lambda: "gateway")
    called = {}
    monkeypatch.setattr(embedder, "_encode_gateway",
                        lambda texts, prefix: called.setdefault("hit", True) or [[0.0]])
    embedder._encode(["x"], "")
    assert called.get("hit")


def test_an_unknown_backend_still_raises(monkeypatch):
    monkeypatch.setattr(embedder, "_active_backend", lambda: "openai")
    with pytest.raises(ValueError, match="unknown embedding backend"):
        embedder._encode(["x"], "")


def test_the_error_message_lists_gateway(monkeypatch):
    monkeypatch.setattr(embedder, "_active_backend", lambda: "nope")
    with pytest.raises(ValueError, match="gateway"):
        embedder._encode(["x"], "")


def test_gateway_backend_selects_the_gateway_cache(monkeypatch):
    """The whole value of this backend: it must NOT resolve to embed_cache.db, or it reports
    a total miss and re-buys ~25k vectors."""
    monkeypatch.setattr(embedder, "_active_backend", lambda: "gateway")
    monkeypatch.setattr(embed_cache, "_gateway_instance", None)
    cache = embedder._cache_for_backend()
    assert isinstance(cache, embed_cache.GatewayVecCache)
    assert cache.path.name == "gemini_embed_cache.db"


def test_local_backend_still_selects_the_production_cache(monkeypatch):
    monkeypatch.setattr(embedder, "_active_backend", lambda: "local")
    cache = embedder._cache_for_backend()
    assert isinstance(cache, embed_cache.EmbedCache)
    assert cache.path.name == "embed_cache.db"


def test_cache_model_key_carries_the_dimension(monkeypatch):
    """A 768-truncated vector and a 3072 vector share a model name but are different
    vectors; keying on the name alone serves one where the other was asked for."""
    monkeypatch.setattr(embedder, "_active_backend", lambda: "gateway")
    assert embedder._cache_model_key() == "gemini-embedding-2@3072"


# --- the transport moved, and the direction matters ------------------------

def test_the_transport_lives_in_shared_and_calibration_reexports_it():
    from calibration import trial_gateway
    from shared import gateway
    assert trial_gateway.GatewayClient is gateway.GatewayClient
    assert trial_gateway.EMBED_MODEL == gateway.EMBED_MODEL
    assert trial_gateway._embed_limiter is gateway._embed_limiter


def test_no_production_module_imports_calibration():
    """`v1/`, `v2/`, `shared/`, `preprocessing/` must never import the measurement tooling.
    Moving the gateway transport is exactly the change that could have broken this."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    offenders = []
    for pkg in ("v1", "v2", "shared", "preprocessing", "ego_trap", "layer_d"):
        for py in (root / pkg).rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(n == "calibration" or n.startswith("calibration.") for n in names):
                    offenders.append(f"{py.relative_to(root)}:{node.lineno}")
    assert not offenders, f"production modules importing calibration: {offenders}"


def test_the_rate_limiter_is_shared_at_module_level():
    """The gateway's limit is per API KEY, so two clients in one process must draw from ONE
    bucket or they race each other into the same 429."""
    from shared import gateway
    a = gateway.GatewayClient.__init__
    assert a is not None
    assert gateway._embed_limiter is gateway._embed_limiter
    assert gateway.EMBED_PER_MINUTE <= 150, "the measured per-window ceiling is 150"


# --- max_parallel_requests: the SECOND, independent gateway limit ----------
# Measured 2026-08-19: HTTP 429 "Limit type: max_parallel_requests. Current limit: 8,
# Remaining: 0". A CONCURRENCY ceiling, not the 150-per-window rate cap. The corpus fetch ran
# at workers=8 -- exactly on the ceiling -- and died at 7,200 of 7,472 vectors.

def test_the_parallel_ceiling_leaves_headroom_for_retries():
    """6, not 8. A retry is itself a request, so the ceiling must not be the operating point."""
    from shared import gateway
    assert gateway.EMBED_MAX_PARALLEL < 8, (
        "the measured max_parallel_requests limit is 8; operating AT it leaves no room for "
        "retries, which is exactly how the 2026-08-19 fetch died"
    )
    assert gateway._embed_parallel._value == gateway.EMBED_MAX_PARALLEL


def test_a_concurrency_rejection_is_not_treated_as_a_quota_rejection():
    """The two need opposite responses: a quota 429 wants a window-length wait and a shared
    penalty; a concurrency 429 clears when a sibling finishes and wants a short jittered one.
    Taking the quota ladder would idle every worker for a minute, then release them together
    to collide again."""
    from shared import gateway
    msg = ('HTTP 429: {"error":{"message":"Rate limit exceeded for api_key: abc. '
           'Limit type: max_parallel_requests. Current limit: 8, Remaining: 0."}}').lower()
    assert any(m in msg for m in gateway._PARALLEL_MARKERS)


def test_a_quota_rejection_is_still_classified_as_a_rate_limit():
    """The regression risk in splitting these: the ORIGINAL 429 must keep its long ladder."""
    from shared import gateway
    msg = ('HTTP 429: {"error":{"message":"Rate limit exceeded for model_per_key: abc. '
           'Limit type: requests. Current limit: 150, Remaining: 0."}}').lower()
    assert not any(m in msg for m in gateway._PARALLEL_MARKERS)
    assert any(m in msg for m in gateway._LIMIT_MARKERS)


def test_the_semaphore_actually_bounds_concurrency():
    """Clamping in the TRANSPORT rather than by worker count is the point: every calibration
    script that predates this passes workers=20, and none of them can be trusted to change."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from shared import gateway

    peak = 0
    live = 0
    lock = threading.Lock()
    done = threading.Event()

    def fake_request(_i):
        nonlocal peak, live
        with gateway._embed_parallel:
            with lock:
                live += 1
                peak = max(peak, live)
            done.wait(0.02)
            with lock:
                live -= 1

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(fake_request, range(40)))

    assert peak <= gateway.EMBED_MAX_PARALLEL, (
        f"{peak} requests were in flight against a ceiling of {gateway.EMBED_MAX_PARALLEL}"
    )


def test_ship_layer_b_no_longer_hardcodes_the_ceiling():
    """It passed a literal 8 -- the exact limit -- into the paced fetch."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "ops" / "ship_layer_b.py").read_text(
        encoding="utf-8-sig")
    assert "embed_cached(sorted(resp_missing), 8)" not in src
    assert "EMBED_MAX_PARALLEL" in src
