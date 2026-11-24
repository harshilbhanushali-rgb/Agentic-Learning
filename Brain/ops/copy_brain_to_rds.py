#!/usr/bin/env python3
"""Copy a Brain, or Ask Naren's sign-in data, from Neon into Postgres on AWS RDS (2026-11-23).

    python ops/copy_brain_to_rds.py brain --from DATABASE_URL_BRIDGE --label bridge-v3
    python ops/copy_brain_to_rds.py ask-naren --from DATABASE_URL_PRE_REBUILD
    ... --dry-run     read the source and check everything; write nothing
    ... --replace     empty the target tables first (refused otherwise if they hold rows)
    ... --to VAR      the Brain/.env variable naming the target (default ASK_NAREN_MIGRATE_URL)

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

A database this laptop cannot reach (production RDS) is filled from INSIDE the deployment
instead: POST /admin/setup, ask_naren/db/setup.py. Both paths share ask_naren/db/copy.py.

URLs come from Brain/.env, never the command line: `--from` names the SOURCE variable, and
`--to` the target (a login that can create tables: on RDS, the master user). Migrations and
grants run first (ask_naren.db.migrate, idempotent).
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

from ask_naren.db import GRANTS, connection_url, redacted  # noqa: E402
from ask_naren.db import copy as tables_copy  # noqa: E402
from ask_naren.db.copy import CopyRefused  # noqa: E402

TARGET_ENV = "ASK_NAREN_MIGRATE_URL"
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


def _target_url(key: str) -> str:
    url = os.environ.get(key)
    if not url:
        raise SystemExit(f"ERROR: {key} is not set in {BRAIN / '.env'}")
    return url


# ---------------------------------------------------------------------------------------
# vectors from the local cache
# ---------------------------------------------------------------------------------------

def _cached_vectors(pairs: list[tuple[int, str]]):
    """(pair_ids, unit-norm matrix) from the local cache, or refuse naming what is missing."""
    from calibration.layer_bc_arms import _load_cached
    from calibration.trial_pool_unit_gemini import CACHE, EMBED_DIMS, EMBED_MODEL
    if EMBED_DIMS != WIDTH:
        raise CopyRefused(f"cache width {EMBED_DIMS} != {WIDTH}")
    if not CACHE.exists():
        raise CopyRefused(f"the embedding cache is not at {CACHE}")
    mat, missing = _load_cached([text for _, text in pairs], WIDTH)
    if mat is None:
        raise CopyRefused(
            f"the local cache has no vector for {len(missing)} of {len(pairs)} trigger "
            f"texts (e.g. {missing[0][:80]!r}). Fill the cache first (ops/rebuild_bridge.py "
            f"vectors embeds only what is missing) -- never fetch vectors back from Pinecone.")
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
    return tables_copy.count(dst, "brain", "trigger_vectors")


# ---------------------------------------------------------------------------------------
# the two parts
# ---------------------------------------------------------------------------------------

def _migrate(target_env: str) -> None:
    from ask_naren.db import migrate
    web = tables_copy.web_app_db_dir()
    migrate.main(["--url-env", target_env,
                  "--also", f"ask_naren={web / 'migrations'}",
                  "--grants", str(web / "provision" / "roles.sql"),
                  str(web / "provision" / "grants.sql")])


def copy_brain(src, dst, args) -> dict[str, int]:
    with dst.transaction():
        # Brain's own DDL, inside `brain`. Idempotent; creates what a fresh target lacks.
        dst.execute("set local search_path = brain, extensions")
        dst.execute(tables_copy.brain_schema_sql().read_text(encoding="utf-8-sig"))
        names = tables_copy.plan(src, dst, "public", "brain",
                                 src_tables=set(tables_copy.tables(src, "public")),
                                 exclude=frozenset({"trigger_vectors"}))
        print(f"[plan] {len(names)} tables, in FK order: {', '.join(names)}", flush=True)

        pairs = src.execute("select pair_id, trigger_text from public.kb_pairs "
                            "order by pair_id").fetchall()
        pair_ids, mat, model = _cached_vectors(pairs)
        print(f"[cache] all {len(pair_ids)} trigger vectors found locally ({model}, "
              f"{WIDTH} dims)", flush=True)
        tables_copy.refuse_if_live(dst, "ask_naren_service")
        if args.dry_run:
            raise _DryRun

        tables_copy.empty_or_refuse(dst, "brain", names + ["trigger_vectors"], args.replace)
        counts = tables_copy.copy_tables(src, dst, "public", "brain", names)
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
        names = tables_copy.plan(src, dst, "ask_naren", "ask_naren",
                                 src_tables=set(tables_copy.tables(src, "ask_naren")),
                                 exclude=exclude)
        print(f"[plan] {len(names)} tables, in FK order: {', '.join(names)}"
              f"{'' if args.with_sessions else ' (sessions NOT copied)'}", flush=True)
        tables_copy.refuse_if_live(dst, "ask_naren_app")
        if args.dry_run:
            raise _DryRun
        tables_copy.empty_or_refuse(dst, "ask_naren", names, args.replace)
        return tables_copy.copy_tables(src, dst, "ask_naren", "ask_naren", names)


class _DryRun(Exception):
    """Raised inside the target transaction so a dry run rolls back even the DDL."""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("part", choices=["brain", "ask-naren"])
    ap.add_argument("--from", dest="source", required=True,
                    help="Brain/.env variable holding the SOURCE database URL")
    ap.add_argument("--to", dest="target", default=TARGET_ENV,
                    help=f"Brain/.env variable holding the TARGET URL (default {TARGET_ENV})")
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

    src_url, dst_url = _source_url(args.source, args.source_hostaddr), _target_url(args.target)
    if redacted(src_url) == redacted(dst_url):
        raise SystemExit("ERROR: source and target are the same database")
    print(f"[from] {redacted(src_url)}\n[to]   {redacted(dst_url)}"
          f"{'   (DRY RUN: nothing will be written)' if args.dry_run else ''}", flush=True)

    if not args.dry_run:
        _migrate(args.target)
    with psycopg.connect(src_url, connect_timeout=30) as src, \
         psycopg.connect(connection_url(dst_url), connect_timeout=30) as dst:
        src.execute("set transaction isolation level repeatable read read only")
        try:
            counts = (copy_brain if args.part == "brain" else copy_ask_naren)(src, dst, args)
        except _DryRun:
            print("[dry run] every check passed; nothing written", flush=True)
            return 0
        except CopyRefused as refusal:
            print(f"ERROR: {refusal}. Nothing was written.", file=sys.stderr)
            return 1
        schema = "public" if args.part == "brain" else "ask_naren"
        bad = tables_copy.mismatched_counts(
            src, schema, {t: n for t, n in counts.items() if t != "trigger_vectors"})
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
