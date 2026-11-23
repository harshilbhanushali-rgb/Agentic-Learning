#!/usr/bin/env python3
"""Copy a Brain, or Ask Naren's sign-in data, from Neon into Postgres on AWS RDS (2026-11-23).

    python ops/copy_brain_to_rds.py brain --from DATABASE_URL_BRIDGE --label bridge-v3
    python ops/copy_brain_to_rds.py ask-naren --from DATABASE_URL_PRE_REBUILD
    ... --dry-run     read the source and check everything; write nothing
    ... --replace     empty the target tables first (refused otherwise if they hold rows)

`brain`: every table of Brain/db/schema.sql, from the source's `public` into the target's
`brain` schema, PLUS one trigger vector per kb_pair into `brain.trigger_vectors` (pgvector),
and `brain_meta` rows saying what this is: `vector_store = pgvector`, the model, the source.
That `vector_store` row is what makes Ask Naren search Postgres instead of Pinecone
(ops/serve_ask_naren.py `_vector_store_for`), so DATABASE_URL alone decides the store.

`ask-naren`: users, threads, turns and feedback from the source's `ask_naren` schema. Sessions
are NOT copied unless `--with-sessions`: a fresh sign-in on the new database is the honest
default, and a session row is a live credential.

THE VECTORS COME FROM THE LOCAL CACHE (Brain/gemini_embed_cache.db), the same lookup
ops/load_index_from_cache.py filled Pinecone from: keyed by model, width and exact text, so a
hit is byte-for-byte the vector the index got. Nothing is read from Pinecone -- bulk vector
reads there exhausted the account's 1 GB monthly egress on 2026-11-11 and took production
search down -- and nothing is embedded. A missing vector REFUSES the copy.

ONE TRANSACTION ON THE TARGET: schema, emptying, every table, sequences, vectors and
brain_meta commit together or not at all. The source is read in ONE read-only
repeatable-read snapshot, so the tables agree with each other.

URLs come from Brain/.env, never the command line: `--from` names the SOURCE variable, and the
target is ASK_NAREN_MIGRATE_URL (a login that can create tables: on RDS, the master user).
Migrations and grants run first (ask_naren.db.migrate, idempotent).
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRAIN))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BRAIN / ".env")

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402

from ask_naren.db import GRANTS, connection_url, redacted  # noqa: E402

TARGET_ENV = "ASK_NAREN_MIGRATE_URL"
SCHEMA_SQL = BRAIN / "db" / "schema.sql"
FRONTEND_DB = BRAIN.parent / "frontend" / "db"
# Not Brain data: the vector table is filled from the cache, and the tracking table is the
# migration runner's.
NOT_COPIED = {"trigger_vectors", "schema_migrations"}
WIDTH = 3072
VECTOR_BATCH = 500


# ---------------------------------------------------------------------------------------
# connections
# ---------------------------------------------------------------------------------------

def _source_url(key: str, hostaddr: str | None) -> str:
    url = os.environ.get(key)
    if not url:
        raise SystemExit(f"ERROR: {key} is not set in {BRAIN / '.env'}")
    if hostaddr:
        return url + ("&" if "?" in url else "?") + f"hostaddr={hostaddr}"
    try:  # the laptop resolver refuses *.neon.tech on some networks; use the helper if present
        from shared.neon_dns import with_hostaddr
        return with_hostaddr(url)
    except ImportError:
        return url


def _target_url() -> str:
    url = os.environ.get(TARGET_ENV)
    if not url:
        raise SystemExit(f"ERROR: {TARGET_ENV} is not set in {BRAIN / '.env'}")
    return url


# ---------------------------------------------------------------------------------------
# catalog helpers
# ---------------------------------------------------------------------------------------

def _tables(conn, schema: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "select table_name from information_schema.tables "
        "where table_schema = %s and table_type = 'BASE TABLE' order by table_name",
        (schema,)).fetchall()]


def _columns(conn, schema: str, table: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "select column_name from information_schema.columns "
        "where table_schema = %s and table_name = %s order by ordinal_position",
        (schema, table)).fetchall()]


def _fk_order(conn, schema: str, tables: list[str]) -> list[str]:
    """`tables` ordered so every table comes after the tables it references."""
    deps = {t: set() for t in tables}
    for child, parent in conn.execute(
            """select cl.relname, pl.relname
               from pg_constraint c
               join pg_class cl on cl.oid = c.conrelid
               join pg_class pl on pl.oid = c.confrelid
               join pg_namespace n on n.oid = cl.relnamespace
               where c.contype = 'f' and n.nspname = %s""", (schema,)).fetchall():
        if child in deps and parent in deps and parent != child:
            deps[child].add(parent)
    ordered: list[str] = []
    while deps:
        ready = sorted(t for t, d in deps.items() if not d - set(ordered))
        if not ready:
            raise SystemExit(f"ERROR: foreign-key cycle among {sorted(deps)}")
        for t in ready:
            ordered.append(t)
            del deps[t]
    return ordered


def _count(conn, schema: str, table: str) -> int:
    return conn.execute(sql.SQL("select count(*) from {}.{}").format(
        sql.Identifier(schema), sql.Identifier(table))).fetchone()[0]


# ---------------------------------------------------------------------------------------
# copying
# ---------------------------------------------------------------------------------------

def _plan(src, dst, src_schema: str, dst_schema: str,
          exclude: frozenset[str] = frozenset()) -> list[str]:
    """The tables to copy, in FK order, after refusing any that would lose columns."""
    src_tables = set(_tables(src, src_schema)) - NOT_COPIED
    dst_tables = set(_tables(dst, dst_schema)) - NOT_COPIED
    both = src_tables & dst_tables
    for label, names in (("source tables with no target table, NOT copied", src_tables - dst_tables),
                         ("target tables absent from the source, left empty", dst_tables - src_tables),
                         ("left out on purpose", both & exclude)):
        if names:
            print(f"[plan] {label}: {', '.join(sorted(names))}")
    tables = [t for t in _fk_order(dst, dst_schema, sorted(dst_tables)) if t in both - exclude]
    for t in tables:
        lost = set(_columns(src, src_schema, t)) - set(_columns(dst, dst_schema, t))
        if lost:
            raise SystemExit(f"ERROR: {src_schema}.{t} has columns the target lacks "
                             f"({', '.join(sorted(lost))}) -- they would be dropped. Add them "
                             f"to the target's schema first.")
    return tables


def _copy_table(src, dst, src_schema: str, dst_schema: str, table: str) -> int:
    cols = _columns(src, src_schema, table)
    col_list = sql.SQL(", ").join(map(sql.Identifier, cols))
    out_q = sql.SQL("copy (select {} from {}.{}) to stdout").format(
        col_list, sql.Identifier(src_schema), sql.Identifier(table))
    in_q = sql.SQL("copy {}.{} ({}) from stdin").format(
        sql.Identifier(dst_schema), sql.Identifier(table), col_list)
    with src.cursor().copy(out_q) as out, dst.cursor().copy(in_q) as inp:
        for chunk in out:
            inp.write(chunk)
    return _count(dst, dst_schema, table)


def _reset_sequences(dst, schema: str, table: str) -> None:
    """Point every serial/identity sequence past the copied ids, or the next insert collides."""
    for col, seq in dst.execute(
            """select a.attname, pg_get_serial_sequence(format('%%I.%%I', %s::text, %s::text),
                                                       a.attname)
               from pg_attribute a join pg_class c on c.oid = a.attrelid
               join pg_namespace n on n.oid = c.relnamespace
               where n.nspname = %s and c.relname = %s and a.attnum > 0
                 and not a.attisdropped""", (schema, table, schema, table)).fetchall():
        if seq:
            dst.execute(sql.SQL("select setval(%s, coalesce(max({}), 0) + 1, false) "
                                "from {}.{}").format(sql.Identifier(col), sql.Identifier(schema),
                                                     sql.Identifier(table)), (seq,))


def _empty_or_refuse(dst, schema: str, tables: list[str], replace: bool) -> None:
    held = {t: n for t in tables if (n := _count(dst, schema, t))}
    if held and not replace:
        raise SystemExit(f"ERROR: target already holds rows ({held}) -- pass --replace to "
                         f"empty these tables first. Nothing was written.")
    if tables:
        # CASCADE: a table left out of the copy can still point at one being emptied (target
        # sessions -> users), and Postgres refuses to truncate a referenced table otherwise.
        # Everything it reaches is in this same schema and is reported.
        if held:
            print(f"[replace] emptying {schema}: {held} (and any rows referencing them)")
        dst.execute(sql.SQL("truncate {} restart identity cascade").format(sql.SQL(", ").join(
            sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(t))
            for t in tables)))


# ---------------------------------------------------------------------------------------
# vectors
# ---------------------------------------------------------------------------------------

def _cached_vectors(pairs: list[tuple[int, str]]):
    """(pair_ids, unit-norm matrix) from the local cache, or refuse naming what is missing."""
    from calibration.layer_bc_arms import _load_cached
    from calibration.trial_pool_unit_gemini import CACHE, EMBED_DIMS, EMBED_MODEL
    if EMBED_DIMS != WIDTH:
        raise SystemExit(f"ERROR: cache width {EMBED_DIMS} != {WIDTH}")
    if not CACHE.exists():
        raise SystemExit(f"ERROR: the embedding cache is not at {CACHE}")
    mat, missing = _load_cached([text for _, text in pairs], WIDTH)
    if mat is None:
        raise SystemExit(
            f"ERROR: the local cache has no vector for {len(missing)} of {len(pairs)} trigger "
            f"texts (e.g. {missing[0][:80]!r}). Nothing was written. Fill the cache first "
            f"(ops/rebuild_bridge.py vectors embeds only what is missing) -- never fetch "
            f"vectors back from Pinecone.")
    return [pid for pid, _ in pairs], mat, EMBED_MODEL


def _binary_rows(pair_ids, mat: np.ndarray, model: str):
    """COPY ... (FORMAT BINARY) for (pair_id int4, embedding vector, model text).

    pgvector's binary form is int16 dims, int16 unused, then float4s, all big-endian. About
    12 KB per row against ~35 KB as text -- the difference between a quick upload and a slow
    one when the target is on another continent.
    """
    m = model.encode()
    yield b"PGCOPY\n\xff\r\n\x00" + struct.pack("!ii", 0, 0)
    for i in range(0, len(pair_ids), VECTOR_BATCH):
        buf = bytearray()
        for pid, vec in zip(pair_ids[i:i + VECTOR_BATCH], mat[i:i + VECTOR_BATCH]):
            vb = struct.pack("!hh", len(vec), 0) + vec.astype(">f4").tobytes()
            buf += struct.pack("!h", 3)
            buf += struct.pack("!ii", 4, int(pid))
            buf += struct.pack("!i", len(vb)) + vb
            buf += struct.pack("!i", len(m)) + m
        yield bytes(buf)
    yield struct.pack("!h", -1)


def _load_vectors(dst, pair_ids, mat, model: str) -> int:
    with dst.cursor().copy("copy brain.trigger_vectors (pair_id, embedding, model) "
                           "from stdin (format binary)") as inp:
        for chunk in _binary_rows(pair_ids, mat, model):
            inp.write(chunk)
    return _count(dst, "brain", "trigger_vectors")


# ---------------------------------------------------------------------------------------
# the two parts
# ---------------------------------------------------------------------------------------

def _migrate() -> None:
    from ask_naren.db import migrate
    migrate.main(["--url-env", TARGET_ENV,
                  "--also", f"ask_naren={FRONTEND_DB / 'migrations'}",
                  "--grants", str(FRONTEND_DB / "provision" / "roles.sql"),
                  str(FRONTEND_DB / "provision" / "grants.sql")])


def copy_brain(src, dst, args) -> dict[str, int]:
    with dst.transaction():
        # Brain's own DDL, inside `brain`. Idempotent; creates what a fresh target lacks.
        dst.execute("set local search_path = brain, extensions")
        dst.execute(SCHEMA_SQL.read_text(encoding="utf-8-sig"))
        tables = _plan(src, dst, "public", "brain")
        print(f"[plan] {len(tables)} tables, in FK order: {', '.join(tables)}", flush=True)

        pairs = src.execute("select pair_id, trigger_text from public.kb_pairs "
                            "order by pair_id").fetchall()
        pair_ids, mat, model = _cached_vectors(pairs)
        print(f"[cache] all {len(pair_ids)} trigger vectors found locally ({model}, "
              f"{WIDTH} dims)", flush=True)
        if args.dry_run:
            raise _DryRun

        _empty_or_refuse(dst, "brain", tables + ["trigger_vectors"], args.replace)
        counts = {}
        for t in tables:
            t0 = time.time()
            counts[t] = _copy_table(src, dst, "public", "brain", t)
            _reset_sequences(dst, "brain", t)
            print(f"[copy] brain.{t}: {counts[t]} rows ({time.time() - t0:.1f}s)", flush=True)
        t0 = time.time()
        counts["trigger_vectors"] = _load_vectors(dst, pair_ids, mat, model)
        print(f"[vectors] {counts['trigger_vectors']} loaded ({time.time() - t0:.1f}s)",
              flush=True)
        meta = {"vector_store": "pgvector", "vector_model": model,
                "source": args.label, "source_database": redacted(os.environ[args.source]),
                "copied_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        for key, value in meta.items():
            dst.execute("insert into brain.brain_meta (key, value) values (%s, %s) "
                        "on conflict (key) do update set value = excluded.value", (key, value))
        print(f"[meta] {meta}", flush=True)
    with dst.transaction():
        dst.execute(GRANTS.read_text(encoding="utf-8-sig"))
    return counts


def copy_ask_naren(src, dst, args) -> dict[str, int]:
    exclude = frozenset() if args.with_sessions else frozenset({"sessions"})
    with dst.transaction():
        tables = _plan(src, dst, "ask_naren", "ask_naren", exclude)
        print(f"[plan] {len(tables)} tables, in FK order: {', '.join(tables)}"
              f"{'' if args.with_sessions else ' (sessions NOT copied)'}", flush=True)
        if args.dry_run:
            raise _DryRun
        _empty_or_refuse(dst, "ask_naren", tables, args.replace)
        counts = {}
        for t in tables:
            counts[t] = _copy_table(src, dst, "ask_naren", "ask_naren", t)
            _reset_sequences(dst, "ask_naren", t)
            print(f"[copy] ask_naren.{t}: {counts[t]} rows", flush=True)
    return counts


class _DryRun(Exception):
    """Raised inside the target transaction so a dry run rolls back even the DDL."""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("part", choices=["brain", "ask-naren"])
    ap.add_argument("--from", dest="source", required=True,
                    help="Brain/.env variable holding the SOURCE database URL")
    ap.add_argument("--label", default=None,
                    help="brain: what this Brain is, recorded in brain_meta (e.g. bridge-v3)")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--with-sessions", action="store_true")
    ap.add_argument("--source-hostaddr", default=None,
                    help="an IP for a Neon host the local resolver refuses")
    args = ap.parse_args()
    if args.part == "brain" and not args.label:
        raise SystemExit("ERROR: brain copies need --label (what this Brain is)")

    src_url, dst_url = _source_url(args.source, args.source_hostaddr), _target_url()
    if redacted(src_url) == redacted(dst_url):
        raise SystemExit("ERROR: source and target are the same database")
    print(f"[from] {redacted(src_url)}\n[to]   {redacted(dst_url)}"
          f"{'   (DRY RUN: nothing will be written)' if args.dry_run else ''}", flush=True)

    if not args.dry_run:
        _migrate()
    with psycopg.connect(src_url, connect_timeout=30) as src, \
         psycopg.connect(connection_url(dst_url), connect_timeout=30) as dst:
        src.execute("set transaction isolation level repeatable read read only")
        try:
            counts = (copy_brain if args.part == "brain" else copy_ask_naren)(src, dst, args)
        except _DryRun:
            print("[dry run] every check passed; nothing written", flush=True)
            return 0
        # Source counts from the SAME snapshot the copy read.
        schema = "public" if args.part == "brain" else "ask_naren"
        bad = {t: (_count(src, schema, t), n) for t, n in counts.items()
               if t != "trigger_vectors" and _count(src, schema, t) != n}
        if args.part == "brain" and counts.get("trigger_vectors") != counts.get("kb_pairs"):
            bad["trigger_vectors"] = (counts.get("kb_pairs"), counts.get("trigger_vectors"))
        src.rollback()
    if bad:
        print(f"VERIFY FAILED (source, target): {bad}")
        return 1
    print(f"COPIED AND COUNTED: {counts}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
