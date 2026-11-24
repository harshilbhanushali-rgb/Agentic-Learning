"""Copying tables between Postgres databases: the machinery both copy paths share.

  * ops/copy_brain_to_rds.py (CS-platform, a laptop): Neon -> RDS, with the trigger vectors
    loaded from the local embedding cache.
  * ask_naren/db/setup.py (inside the deployed image, behind POST /admin/setup): RDS -> RDS
    for the Brain (its vectors are already in pgvector), Neon -> RDS for sign-in data.

Every function takes open psycopg connections and raises `CopyRefused` -- never exits -- so a
caller inside the running service can report a refusal instead of dying of it. Nothing here
reads an environment variable or prints a URL.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from psycopg import sql

HERE = Path(__file__).resolve().parent
SERVICE_ROOT = HERE.parents[1]          # Brain/ upstream, the service root in the image

# Not Brain data in the Neon -> RDS path: the vector table is filled from the cache there, and
# the tracking table belongs to the migration runner in every path.
TRACKING_TABLE = "schema_migrations"

Log = Callable[[str], None]


class CopyRefused(Exception):
    """A copy that would lose, overwrite or corrupt data. Nothing was written."""


# ---------------------------------------------------------------------------------------
# where the SQL lives: in the repo upstream, under sql/ in the deployed image
# ---------------------------------------------------------------------------------------

def brain_schema_sql() -> Path:
    """Brain's DDL. Upstream it is Brain/db/schema.sql; the sync copies it into the image at
    sql/brain/schema.sql, because the image carries no Brain/db."""
    for path in (SERVICE_ROOT / "sql" / "brain" / "schema.sql", SERVICE_ROOT / "db" / "schema.sql"):
        if path.is_file():
            return path
    raise FileNotFoundError("Brain's schema.sql is neither in sql/brain/ nor in db/")


def web_app_db_dir() -> Path:
    """The web app's migrations/ and provision/. Upstream frontend/db; sql/web_app in the image."""
    for path in (SERVICE_ROOT / "sql" / "web_app", SERVICE_ROOT.parent / "frontend" / "db"):
        if (path / "migrations").is_dir():
            return path
    raise FileNotFoundError("the web app's migrations are neither in sql/web_app nor frontend/db")


# ---------------------------------------------------------------------------------------
# catalog
# ---------------------------------------------------------------------------------------

def tables(conn, schema: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "select table_name from information_schema.tables "
        "where table_schema = %s and table_type = 'BASE TABLE' order by table_name",
        (schema,)).fetchall()]


def readable_tables(conn, schema: str) -> list[str]:
    """Tables in `schema` the current login can SELECT -- a read-only source login sees only
    what it was granted. Through pg_class, so a schema without USAGE does not raise."""
    return [r[0] for r in conn.execute(
        """select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
           where n.nspname = %s and c.relkind = 'r' and has_table_privilege(c.oid, 'SELECT')
           order by c.relname""", (schema,)).fetchall()]


def columns(conn, schema: str, table: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "select column_name from information_schema.columns "
        "where table_schema = %s and table_name = %s order by ordinal_position",
        (schema, table)).fetchall()]


def fk_order(conn, schema: str, names: list[str]) -> list[str]:
    """`names` ordered so every table comes after the tables it references."""
    deps = {t: set() for t in names}
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
            raise CopyRefused(f"foreign-key cycle among {sorted(deps)}")
        for t in ready:
            ordered.append(t)
            del deps[t]
    return ordered


def count(conn, schema: str, table: str) -> int:
    return conn.execute(sql.SQL("select count(*) from {}.{}").format(
        sql.Identifier(schema), sql.Identifier(table))).fetchone()[0]


# ---------------------------------------------------------------------------------------
# planning and guards
# ---------------------------------------------------------------------------------------

def plan(src, dst, src_schema: str, dst_schema: str, *, src_tables: set[str],
         exclude: frozenset[str] = frozenset(), log: Log = print) -> list[str]:
    """The tables to copy, in FK order, after refusing any that would lose columns."""
    dst_tables = set(tables(dst, dst_schema)) - {TRACKING_TABLE}
    src_tables = set(src_tables) - {TRACKING_TABLE}
    both = src_tables & dst_tables
    for label, names in (("source tables with no target table, NOT copied", src_tables - dst_tables),
                         ("target tables not read from the source, left empty", dst_tables - src_tables),
                         ("left out on purpose", both & exclude)):
        if names:
            log(f"[plan] {label}: {', '.join(sorted(names))}")
    chosen = [t for t in fk_order(dst, dst_schema, sorted(dst_tables)) if t in both - exclude]
    for t in chosen:
        lost = set(columns(src, src_schema, t)) - set(columns(dst, dst_schema, t))
        if lost:
            raise CopyRefused(f"{src_schema}.{t} has columns the target lacks "
                              f"({', '.join(sorted(lost))}) -- they would be dropped")
    return chosen


def refuse_if_live(dst, role: str) -> None:
    """Refuse while `role` is connected to the target -- i.e. while the app that reads these
    tables is running against them (bug hunt, 2026-11-23): the emptying TRUNCATE would block
    every request for the whole copy, and a running Ask Naren keeps the pool it loaded at
    startup, keyed by pair_id, while a replaced Brain reuses those ids."""
    n = dst.execute("select count(*) from pg_stat_activity "
                    "where usename = %s and datname = current_database()", (role,)).fetchone()[0]
    if n:
        raise CopyRefused(f"{n} connection(s) from {role} are open on the target -- the app is "
                          f"running against it. Stop it, copy, then restart it.")


def require_empty(dst, schema: str, names: list[str]) -> None:
    held = {t: n for t in names if (n := count(dst, schema, t))}
    if held:
        raise CopyRefused(f"the target already holds rows ({held}); this path only fills an "
                          f"empty database")


def empty_or_refuse(dst, schema: str, names: list[str], replace: bool, log: Log = print) -> None:
    held = {t: n for t in names if (n := count(dst, schema, t))}
    if held and not replace:
        raise CopyRefused(f"target already holds rows ({held}) -- pass --replace to empty "
                          f"these tables first")
    if names:
        # CASCADE: a table left out of the copy can still point at one being emptied (target
        # sessions -> users). Everything it reaches is in this same schema and is reported.
        if held:
            log(f"[replace] emptying {schema}: {held} (and any rows referencing them)")
        dst.execute(sql.SQL("truncate {} restart identity cascade").format(sql.SQL(", ").join(
            sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(t)) for t in names)))


# ---------------------------------------------------------------------------------------
# copying
# ---------------------------------------------------------------------------------------

def copy_table(src, dst, src_schema: str, dst_schema: str, table: str, *,
               binary: bool = False) -> int:
    """COPY one table across. BINARY only between identical types on both sides (pgvector to
    pgvector, same version): a 3072-float vector is ~12 KB binary against ~35 KB as text."""
    cols = columns(src, src_schema, table)
    col_list = sql.SQL(", ").join(map(sql.Identifier, cols))
    fmt = sql.SQL(" (format binary)") if binary else sql.SQL("")
    out_q = sql.SQL("copy (select {} from {}.{}) to stdout{}").format(
        col_list, sql.Identifier(src_schema), sql.Identifier(table), fmt)
    in_q = sql.SQL("copy {}.{} ({}) from stdin{}").format(
        sql.Identifier(dst_schema), sql.Identifier(table), col_list, fmt)
    with src.cursor().copy(out_q) as out, dst.cursor().copy(in_q) as inp:
        for chunk in out:
            inp.write(chunk)
    return count(dst, dst_schema, table)


def reset_sequences(dst, schema: str, table: str) -> None:
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


def copy_tables(src, dst, src_schema: str, dst_schema: str, names: list[str], *,
                binary_tables: frozenset[str] = frozenset(), log: Log = print) -> dict[str, int]:
    counts = {}
    for t in names:
        t0 = time.time()
        counts[t] = copy_table(src, dst, src_schema, dst_schema, t, binary=t in binary_tables)
        reset_sequences(dst, dst_schema, t)
        log(f"[copy] {dst_schema}.{t}: {counts[t]} rows ({time.time() - t0:.1f}s)")
    return counts


def mismatched_counts(src, src_schema: str, counts: dict[str, int]) -> dict[str, tuple[int, int]]:
    """Tables whose target count differs from the source's, read in the SAME source snapshot."""
    return {t: (s, n) for t, n in counts.items() if (s := count(src, src_schema, t)) != n}
