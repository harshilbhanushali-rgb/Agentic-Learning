"""The move to Postgres + pgvector on RDS (2026-11-23): the store, GET /verify, the migration
runner, and how RDS URLs are connected to.

Two kinds of test, as elsewhere here:

  * network-free -- the route, the checks against a fake store, the runner's bookkeeping, URL
    handling. Always run.

  * AGAINST A REAL POSTGRES WITH pgvector, because the store's whole job is SQL: that the
    ranking is the exact cosine order, that the scenario filter is the live kb_pairs key,
    that sessions are read-only. A fake would only assert what the fake was told. Skipped
    unless ASK_NAREN_PG_TEST_URL is set (env or Brain/.env): the local Docker pgvector
    (ask_naren/db/docker-compose.yml) or a staging database. Each test works in its own
    scratch schema and drops it, so a shared database is left as it was found.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import httpx
import numpy as np
import pytest

from ask_naren import api, verification
from ask_naren.db import RDS_CA_BUNDLE, connection_url, redacted
from ask_naren.db import migrate
from ask_naren.vector_store import PgVectorTriggerStore, _vector_literal

DIMS = 3072


# ---------------------------------------------------------------------------------------
# connecting to RDS
# ---------------------------------------------------------------------------------------

def test_an_rds_url_is_upgraded_to_a_verified_connection():
    url = connection_url("postgresql://u:p@db.abc.us-east-1.rds.amazonaws.com:5432/x"
                         "?sslmode=require")
    assert "sslmode=verify-full" in url
    assert f"sslrootcert={RDS_CA_BUNDLE}".replace("/", "%2F") in url
    assert RDS_CA_BUNDLE.read_text().count("BEGIN CERTIFICATE") > 10


def test_a_non_rds_url_is_left_exactly_as_given():
    url = "postgresql://u:p@ep-x-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
    assert connection_url(url) == url


def test_a_non_rds_url_asking_for_verification_gets_public_authorities():
    """2026-11-24: the web app's verify-full Neon URL failed from Python with no root.crt."""
    import certifi
    url = "postgresql://u:p@ep-x-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=verify-full"
    out = connection_url(url)
    assert "sslmode=verify-full" in out and "sslrootcert=" in out
    assert certifi.where().replace("/", "%2F") in out


def test_an_explicit_root_certificate_is_respected():
    url = "postgresql://u:p@h.rds.amazonaws.com/x?sslmode=verify-ca&sslrootcert=/etc/ca.pem"
    assert connection_url(url) == url


def test_a_redacted_url_never_carries_the_password():
    # A two-letter stand-in password: the repository's secrets hook rightly refuses anything
    # longer in a URL, and the property under test does not depend on its length.
    assert redacted("postgresql://svc:pw@h.rds.amazonaws.com:5432/db?x=1") == \
        "svc@h.rds.amazonaws.com/db"


_KEYVALUE = "host=db.x.rds.amazonaws.com user=u password=pw dbname=d"


def test_a_key_value_connection_string_is_refused_not_connected_unverified():
    """Bug hunt 2026-11-23: is_rds said False, so TLS was NOT upgraded to verify-full."""
    with pytest.raises(ValueError, match="postgresql:// URI"):
        connection_url(_KEYVALUE)


def test_a_key_value_connection_string_is_never_printed():
    """Bug hunt 2026-11-23: redacted() returned it whole, password included."""
    assert "pw" not in redacted(_KEYVALUE) and "host=" not in redacted(_KEYVALUE)


def test_the_copy_refuses_while_the_app_is_connected():
    # Shared by the laptop copy and POST /admin/setup since 2026-11-24.
    from ask_naren.db import copy
    from ask_naren.db.copy import CopyRefused

    class _Conn:
        def __init__(self, n):
            self.n = n

        def execute(self, sql, params=None):
            n = self.n

            class _Cur:
                def fetchone(self):
                    return (n,)
            return _Cur()

    copy.refuse_if_live(_Conn(0), "ask_naren_service")
    with pytest.raises(CopyRefused, match="app is"):
        copy.refuse_if_live(_Conn(2), "ask_naren_service")


# ---------------------------------------------------------------------------------------
# the migration runner's bookkeeping
# ---------------------------------------------------------------------------------------

class _TrackingConn:
    def __init__(self, applied: dict[str, str]):
        self.applied = applied

    def execute(self, sql, params=None):
        rows = list(self.applied.items())

        class _Cur:
            def fetchall(self):
                return rows
        return _Cur()


def test_the_shipped_migrations_are_collected_in_order():
    names = [m.name for m in migrate.collect([("brain", migrate.MIGRATIONS)])]
    assert names == sorted(names)
    assert names[0] == "brain/0001_pgvector_and_brain_schema.sql"


def test_only_unapplied_migrations_are_pending():
    ms = migrate.collect([("brain", migrate.MIGRATIONS)])
    conn = _TrackingConn({ms[0].name: ms[0].sha256})
    assert [m.name for m in migrate.pending(conn, ms)] == [m.name for m in ms[1:]]


def test_an_applied_migration_that_was_edited_stops_the_run():
    ms = migrate.collect([("brain", migrate.MIGRATIONS)])
    conn = _TrackingConn({ms[0].name: "0" * 64})
    with pytest.raises(SystemExit, match="EDITED"):
        migrate.pending(conn, ms)


def test_the_url_comes_from_the_environment_never_the_command_line(monkeypatch, tmp_path):
    monkeypatch.delenv("NO_SUCH_URL_VAR", raising=False)
    with pytest.raises(SystemExit, match="NO_SUCH_URL_VAR is not set"):
        migrate.main(["--url-env", "NO_SUCH_URL_VAR", "--dry-run"])


# ---------------------------------------------------------------------------------------
# GET /verify
# ---------------------------------------------------------------------------------------

def _get(app, path):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as client:
            return await client.get(path)
    return asyncio.run(go())


async def _answer(situation, thread=()):
    return {"outcome": "declined"}


def test_verify_without_a_verifier_is_not_configured():
    r = _get(api.build_app(_answer), "/verify")
    assert r.status_code == 404 and r.json() == {"status": "not_configured"}


def test_verify_passing_is_200_and_failing_is_503_with_the_report():
    async def good():
        return True, {"status": "ok", "checks": []}

    async def bad():
        return False, {"status": "failed", "checks": [{"name": "x", "ok": False}]}

    assert _get(api.build_app(_answer, verify=good), "/verify").status_code == 200
    r = _get(api.build_app(_answer, verify=bad), "/verify")
    assert r.status_code == 503 and r.json()["checks"][0]["name"] == "x"


class _FakeStore:
    """Answers verify_pgvector's queries like a healthy pgvector Brain, unless told not to."""

    def __init__(self, missing=(), broken=False):
        self.missing, self.broken = set(missing), broken
        self.vectors = {"1": [1.0] + [0.0] * (DIMS - 1), "2": [0.0, 1.0] + [0.0] * (DIMS - 2)}

    async def fetch(self, sql, params=()):
        if self.broken and "count(*)" in sql:
            raise RuntimeError("relation \"kb_pairs\" does not exist")
        if "current_user" in sql:
            return [("ask_naren_service", "ask_naren_test", "on", "0.8.1")]
        if "count(*)" in sql:
            return [(2, 2, 3, 1, 1)]
        if "vector_dims" in sql:
            return [(DIMS, DIMS)]
        if "brain_meta" in sql:
            return [("source", "bridge"), ("vector_store", "pgvector")]
        raise AssertionError(sql)

    async def unretrievable(self, pairs):
        return [(str(p["pair_id"]), "no vector") for p in pairs
                if str(p["pair_id"]) in self.missing], []

    async def stored_vectors(self, ids):
        return {str(i): self.vectors[str(i)] for i in ids if str(i) not in self.missing}

    async def search(self, vec, k):
        pid = "1" if vec[0] == 1.0 else "2"
        return [(pid, 1.0)]


_PAIRS = [{"pair_id": 1, "scenario_key": "a"}, {"pair_id": 2, "scenario_key": "a"}]


def _verify(store):
    return asyncio.run(verification.verify_pgvector(
        store, _PAIRS, database="svc@h/db", expected_dims=DIMS))


def test_a_healthy_pgvector_brain_passes_every_check():
    ok, report = _verify(_FakeStore())
    assert ok and report["status"] == "ok"
    assert {c["name"] for c in report["checks"]} >= {
        "connection", "tables", "vector_dimensions", "every_answerable_pair_has_a_vector",
        "stored_vectors_find_themselves", "brain_meta"}
    assert report["database"] == "svc@h/db"


def test_an_answerable_pair_without_a_vector_fails_and_is_named():
    ok, report = _verify(_FakeStore(missing={"2"}))
    coverage = next(c for c in report["checks"]
                    if c["name"] == "every_answerable_pair_has_a_vector")
    assert not ok and not coverage["ok"] and coverage["detail"]["examples"] == ["2"]


def test_a_check_that_raises_is_reported_failed_not_raised():
    ok, report = _verify(_FakeStore(broken=True))
    tables = next(c for c in report["checks"] if c["name"] == "tables")
    assert not ok and not tables["ok"] and "does not exist" in tables["detail"]


def test_the_pinecone_path_says_it_is_not_verified_here():
    ok, report = asyncio.run(verification.not_verifiable("pinecone"))
    assert ok and report["status"] == "not_applicable"


# ---------------------------------------------------------------------------------------
# the store, network-free parts
# ---------------------------------------------------------------------------------------

def test_the_store_refuses_an_unrestricted_scenario_filter():
    with pytest.raises(ValueError, match="unrestricted"):
        PgVectorTriggerStore(object(), scenario_keys=[])


def test_the_vector_literal_is_pgvectors_text_form():
    assert _vector_literal(np.array([0.5, -1.0, 0.25])) == "[0.5,-1.0,0.25]"


# ---------------------------------------------------------------------------------------
# the store, against a real Postgres with pgvector
# ---------------------------------------------------------------------------------------

def _test_url() -> str | None:
    if not os.environ.get("ASK_NAREN_PG_TEST_URL"):
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    return os.environ.get("ASK_NAREN_PG_TEST_URL")


needs_pg = pytest.mark.skipif(not _test_url(), reason="ASK_NAREN_PG_TEST_URL not set")


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


@pytest.fixture
def scratch():
    """A scratch schema with kb_pairs + trigger_vectors, dropped afterwards.

    Five pairs: 1-4 in coachable scenario `a`, 5 in sink `z`. Pair 4 has NO vector. Vector 99
    has no pair. Random 3072-dim unit vectors, so the expected order is computed, not chosen.
    """
    import psycopg
    url = connection_url(_test_url())
    schema = f"test_pgv_{uuid.uuid4().hex[:10]}"
    rng = np.random.default_rng(7)
    vecs = {pid: _unit(rng.normal(size=DIMS)) for pid in (1, 2, 3, 5, 99)}
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("create schema if not exists extensions")
        c.execute("create extension if not exists vector with schema extensions")
        c.execute(f"create schema {schema}")
        c.execute(f"create table {schema}.kb_pairs (pair_id int primary key, scenario_key text)")
        c.execute(f"create table {schema}.trigger_vectors (pair_id int primary key, "
                  f"embedding extensions.vector({DIMS}) not null, model text not null)")
        c.execute(f"insert into {schema}.kb_pairs values (1,'a'),(2,'a'),(3,'a'),(4,'a'),(5,'z')")
        for pid, v in vecs.items():
            c.execute(f"insert into {schema}.trigger_vectors values (%s, %s::extensions.vector, 'test')",
                      (pid, _vector_literal(v)))
    try:
        yield {"url": _test_url(), "schema": schema, "vecs": vecs}
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(f"drop schema {schema} cascade")


def _with_store(scratch, keys, body):
    async def go():
        store = await PgVectorTriggerStore.open(
            scratch["url"], scenario_keys=keys,
            search_path=f"{scratch['schema']},extensions", max_connections=2)
        try:
            return await body(store)
        finally:
            await store.aclose()
    return asyncio.run(go())


@needs_pg
def test_the_ranking_is_the_exact_cosine_order(scratch):
    rng = np.random.default_rng(11)
    query = rng.normal(size=DIMS)          # deliberately NOT unit length
    got = _with_store(scratch, ["a"], lambda s: s.search(query, 10))
    q = _unit(query)
    expected = sorted(((str(pid), float(scratch["vecs"][pid] @ q)) for pid in (1, 2, 3)),
                      key=lambda t: -t[1])
    assert [pid for pid, _ in got] == [pid for pid, _ in expected]
    for (_, cos), (_, want) in zip(got, expected):
        assert abs(cos - want) < 1e-5 and -1.0 <= cos <= 1.0


@needs_pg
def test_a_stored_vector_finds_itself_at_cosine_one(scratch):
    got = _with_store(scratch, ["a"], lambda s: s.search(scratch["vecs"][2], 1))
    assert got[0][0] == "2" and abs(got[0][1] - 1.0) < 1e-5


@needs_pg
def test_sinks_and_orphan_vectors_are_never_returned(scratch):
    got = _with_store(scratch, ["a"], lambda s: s.search(scratch["vecs"][5], 10))
    assert {pid for pid, _ in got} == {"1", "2", "3"}
    got = _with_store(scratch, ["a"], lambda s: s.search(scratch["vecs"][99], 10))
    assert "99" not in {pid for pid, _ in got}


@needs_pg
def test_a_pair_without_a_vector_is_reported_unretrievable(scratch):
    pairs = [{"pair_id": i, "scenario_key": "a"} for i in (1, 2, 3, 4)]
    fatal, stale = _with_store(scratch, ["a"], lambda s: s.unretrievable(pairs))
    assert [pid for pid, _ in fatal] == ["4"] and stale == []


@needs_pg
def test_stored_vectors_round_trip(scratch):
    got = _with_store(scratch, ["a"], lambda s: s.stored_vectors([1, 4]))
    assert set(got) == {"1"}
    assert np.allclose(got["1"], scratch["vecs"][1], atol=1e-6)


@needs_pg
def test_the_stores_sessions_cannot_write(scratch):
    import psycopg

    async def write(store):
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            await store.fetch("insert into kb_pairs values (100, 'a')")
    _with_store(scratch, ["a"], write)


@needs_pg
def test_a_brain_replaced_under_a_running_store_is_an_error_not_wrong_answers(scratch):
    """Bug hunt 2026-11-23: the pool is keyed by pair_id from startup, the search is live, and
    a --replace copy reuses ids for different exchanges. The store must refuse, loudly."""
    import psycopg
    url, s = connection_url(_test_url()), scratch["schema"]
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(f"create table {s}.brain_meta (key text primary key, value text)")
        c.execute(f"insert into {s}.brain_meta values ('copied_at', '2026-11-23T10:00:00')")

    async def body(store):
        assert (await store.search(scratch["vecs"][1], 1))[0][0] == "1"   # same Brain: fine
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(f"update {s}.brain_meta set value = '2026-11-24T09:00:00' "
                      f"where key = 'copied_at'")
        with pytest.raises(RuntimeError, match="replaced"):
            await store.search(scratch["vecs"][1], 1)
    _with_store(scratch, ["a"], body)


@needs_pg
def test_verify_passes_on_a_whole_brain_and_fails_on_a_gap(scratch):
    import psycopg
    url = connection_url(_test_url())
    with psycopg.connect(url, autocommit=True) as c:
        s = scratch["schema"]
        c.execute(f"create table {s}.scenarios (k int)")
        c.execute(f"create table {s}.calls (k int)")
        c.execute(f"create table {s}.playbooks (status text)")
        c.execute(f"create table {s}.brain_meta (key text primary key, value text)")
        c.execute(f"insert into {s}.scenarios values (1)")
        c.execute(f"insert into {s}.brain_meta values ('vector_store', 'pgvector')")

    async def run(pairs):
        async def body(store):
            return await verification.verify_pgvector(
                store, pairs, database="t", expected_dims=DIMS)
        return body

    whole = [{"pair_id": i, "scenario_key": "a"} for i in (1, 2, 3)]
    ok, report = _with_store(scratch, ["a"], asyncio.run(run(whole)))
    assert ok, report
    gap = whole + [{"pair_id": 4, "scenario_key": "a"}]
    ok, report = _with_store(scratch, ["a"], asyncio.run(run(gap)))
    assert not ok
