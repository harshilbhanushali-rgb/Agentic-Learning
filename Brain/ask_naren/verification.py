"""What GET /verify checks: that this process is answering from the database and vectors it
should be, and that they are whole.

Built for the move from Neon + Pinecone to Postgres + pgvector on RDS. After a copy, or a
deploy pointed at a new database, one request answers "is it really reading what we think,
and can every answerable exchange be found?" -- the questions a passing /health cannot.

Every check is reported, pass or fail, with the detail that explains it. A check that
raises is a FAILED check with the error as its detail, never a 500: a verification endpoint
that falls over when something is wrong would hide exactly what it exists to show.

Only the pgvector store is verified. On the Pinecone path the endpoint reports that and
nothing else; that store has its own startup guard and ops/check_vector_coverage.py.
"""
from __future__ import annotations

import random
from typing import Awaitable, Callable, Sequence

#: A sampled pair must find ITSELF at rank 1 -- or a different pair scoring this close,
#: which is a byte-identical trigger text filed twice (content dedup keeps one in the pool,
#: but both rows have vectors).
SELF_MATCH_FLOOR = 0.9999
SELF_MATCH_SAMPLE = 5


async def verify_pgvector(store, pool_pairs: Sequence[dict], *, database: str,
                          expected_dims: int,
                          sample: int = SELF_MATCH_SAMPLE) -> tuple[bool, dict]:
    """(all checks passed, report). `database` is the redacted `user@host/db` in use."""
    checks: list[dict] = []

    async def check(name: str, run: Callable[[], Awaitable[tuple[bool, object]]]) -> None:
        try:
            ok, detail = await run()
        except Exception as exc:  # noqa: BLE001 -- reported, see the module docstring
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    async def connection():
        (user, db, read_only, pgvector), = await store.fetch(
            "select current_user, current_database(), "
            "current_setting('default_transaction_read_only'), "
            "(select extversion from pg_extension where extname = 'vector')")
        detail = {"user": user, "database": db, "read_only": read_only, "pgvector": pgvector}
        return read_only == "on" and pgvector is not None, detail

    async def tables():
        (pairs, vectors, scenarios, calls, live_playbooks), = await store.fetch(
            "select (select count(*) from kb_pairs), (select count(*) from trigger_vectors), "
            "(select count(*) from scenarios), (select count(*) from calls), "
            "(select count(*) from playbooks where status = 'live')")
        detail = {"kb_pairs": pairs, "trigger_vectors": vectors, "scenarios": scenarios,
                  "calls": calls, "live_playbooks": live_playbooks}
        return pairs > 0 and vectors > 0 and scenarios > 0, detail

    async def dimensions():
        rows = await store.fetch(
            "select min(vector_dims(embedding)), max(vector_dims(embedding)) "
            "from trigger_vectors")
        lo, hi = rows[0]
        return lo == hi == expected_dims, {"expected": expected_dims, "min": lo, "max": hi}

    async def coverage():
        fatal, _ = await store.unretrievable(pool_pairs)
        detail = {"answerable_pairs": len(pool_pairs), "without_a_vector": len(fatal)}
        if fatal:
            detail["examples"] = [pair_id for pair_id, _ in fatal[:5]]
        return not fatal, detail

    async def self_match():
        chosen = random.sample(list(pool_pairs), min(sample, len(pool_pairs)))
        vectors = await store.stored_vectors([p["pair_id"] for p in chosen])
        results = []
        for p in chosen:
            pid = str(p["pair_id"])
            if pid not in vectors:
                results.append({"pair_id": pid, "ok": False, "found": None})
                continue
            top = await store.search(vectors[pid], 1)
            found, score = top[0] if top else (None, 0.0)
            results.append({"pair_id": pid, "found": found, "cosine": round(score, 6),
                            "ok": found == pid or score >= SELF_MATCH_FLOOR})
        return all(r["ok"] for r in results) and bool(results), results

    async def brain():
        rows = await store.fetch("select key, value from brain_meta order by key")
        return True, dict(rows)

    await check("connection", connection)
    await check("tables", tables)
    await check("vector_dimensions", dimensions)
    await check("every_answerable_pair_has_a_vector", coverage)
    await check("stored_vectors_find_themselves", self_match)
    await check("brain_meta", brain)

    ok = all(c["ok"] for c in checks)
    return ok, {"status": "ok" if ok else "failed", "vector_store": "pgvector",
                "database": database, "answerable_pairs_loaded": len(pool_pairs),
                "checks": checks}


async def not_verifiable(vector_store: str) -> tuple[bool, dict]:
    """The report on a store this endpoint does not verify (Pinecone, in-memory)."""
    return True, {"status": "not_applicable", "vector_store": vector_store,
                  "detail": "GET /verify checks the Postgres (pgvector) store; this process "
                            "searches another. Use ops/check_vector_coverage.py for Pinecone."}
