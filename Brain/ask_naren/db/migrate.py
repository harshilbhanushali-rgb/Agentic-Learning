#!/usr/bin/env python3
"""Apply Ask Naren's database migrations to Postgres (RDS, or a local Docker pgvector).

    python -m ask_naren.db.migrate                      # apply what is pending, then grants
    python -m ask_naren.db.migrate --dry-run            # list what is pending; change nothing
    python -m ask_naren.db.migrate --also ask_naren=../frontend/db/migrations \\
        --grants ../frontend/db/provision/roles.sql ../frontend/db/provision/grants.sql

Inside the deployed image (same code, no laptop needed):

    docker run --rm --env-file .env <ask-naren image> python -m ask_naren.db.migrate

THE URL COMES FROM THE ENVIRONMENT, NEVER THE COMMAND LINE: `--url-env` names the variable
(default ASK_NAREN_MIGRATE_URL), read from the process environment or the service root's
`.env`. A command holding a password ends up in shell history and, approved once with
"always allow", in a tracked settings file (CLAUDE.md, "Secrets"). It must be a login that
can create schemas and extensions -- on RDS, the master user. The running app never gets it.

EACH FILE RUNS ONCE, in its own transaction, and is recorded with its SHA-256 in
brain.schema_migrations. A recorded file whose contents have since changed STOPS the run:
an applied migration is history, and editing it changes nothing on databases that already
ran it -- write a new numbered file instead. A session advisory lock stops two runs racing.

Grants files are re-applied on every run (they are idempotent), AFTER the migrations, because
a new table has no grants until they run.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ask_naren.db import GRANTS, MIGRATIONS, connection_url, redacted

SERVICE_ROOT = Path(__file__).resolve().parents[2]
TRACKING = "brain.schema_migrations"
# Any constant works; it only has to be the same in every run of this script.
LOCK_KEY = 0x41534B4E  # "ASKN"


@dataclass(frozen=True)
class Migration:
    name: str        # what is recorded: "<track>/<file name>"
    path: Path
    sha256: str


def collect(trees: list[tuple[str, Path]]) -> list[Migration]:
    """Every migration, in apply order: tree by tree as given, files by name within a tree."""
    found: list[Migration] = []
    for track, directory in trees:
        if not directory.is_dir():
            raise SystemExit(f"ERROR: migrations directory not found: {directory}")
        for path in sorted(directory.glob("*.sql")):
            found.append(Migration(f"{track}/{path.name}", path,
                                   hashlib.sha256(path.read_bytes()).hexdigest()))
    return found


def pending(conn, migrations: list[Migration]) -> list[Migration]:
    """What has not run yet. Refuses if an applied file was edited afterwards."""
    applied = dict(conn.execute(f"select name, sha256 from {TRACKING}").fetchall())
    edited = [m.name for m in migrations if m.name in applied and applied[m.name] != m.sha256]
    if edited:
        raise SystemExit(
            "ERROR: these migrations were applied and have been EDITED since: "
            + ", ".join(edited) + ". Restore them and put the change in a new numbered file.")
    return [m for m in migrations if m.name not in applied]


def ensure_tracking(conn) -> None:
    with conn.transaction():
        conn.execute("create schema if not exists brain")
        conn.execute(f"""create table if not exists {TRACKING} (
                             name       text primary key,
                             sha256     text not null,
                             applied_at timestamptz not null default now())""")


def apply(conn, migration: Migration) -> None:
    sql = migration.path.read_text(encoding="utf-8-sig")
    with conn.transaction():
        conn.execute(sql)
        conn.execute(f"insert into {TRACKING} (name, sha256) values (%s, %s)",
                     (migration.name, migration.sha256))


def run_grants(conn, files: list[Path], log=lambda line: print(line, flush=True)) -> None:
    for path in files:
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8-sig"))
        log(f"[grants] {path.name}")


def _parse_also(values: list[str]) -> list[tuple[str, Path]]:
    trees = []
    for value in values:
        track, sep, directory = value.partition("=")
        if not sep or not track or not directory:
            raise SystemExit(f"ERROR: --also expects TRACK=DIR, got {value!r}")
        trees.append((track, Path(directory).resolve()))
    return trees


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url-env", default="ASK_NAREN_MIGRATE_URL",
                    help="environment variable holding the database URL (never the URL itself)")
    ap.add_argument("--also", action="append", default=[], metavar="TRACK=DIR",
                    help="another migrations directory, applied after this one's")
    ap.add_argument("--grants", nargs="*", type=Path, default=[],
                    help="grants files to apply after migrations (this one's is always applied)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from dotenv import load_dotenv
    load_dotenv(SERVICE_ROOT / ".env")
    url = os.environ.get(args.url_env)
    if not url:
        raise SystemExit(f"ERROR: {args.url_env} is not set (environment or {SERVICE_ROOT / '.env'})")

    migrate_database(url, [("brain", MIGRATIONS), *_parse_also(args.also)],
                     [GRANTS, *[g.resolve() for g in args.grants]], dry_run=args.dry_run)
    return 0


def everything() -> tuple[list[tuple[str, Path]], list[Path]]:
    """Every migration and grants file one Ask Naren database needs: Brain's (this folder)
    and the web app's (frontend/db upstream, sql/web_app in the deployed image)."""
    from ask_naren.db.copy import web_app_db_dir
    web = web_app_db_dir()
    return ([("brain", MIGRATIONS), ("ask_naren", web / "migrations")],
            [GRANTS, web / "provision" / "roles.sql", web / "provision" / "grants.sql"])


def migrate_database(url: str, trees: list[tuple[str, Path]], grants: list[Path], *,
                     dry_run: bool = False, log=lambda line: print(line, flush=True)) -> list[str]:
    """Apply what is pending from `trees`, then every grants file. Returns what was applied
    (or would be, on a dry run). The one implementation behind the CLI and POST /admin/setup."""
    import psycopg

    migrations = collect(trees)
    log(f"[migrate] {redacted(url)}")
    with psycopg.connect(connection_url(url), autocommit=True, connect_timeout=15) as conn:
        conn.execute("select pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            # A dry run writes nothing, not even the tracking table: absent, nothing has run.
            tracked = conn.execute("select to_regclass(%s)", (TRACKING,)).fetchone()[0]
            if dry_run and tracked is None:
                todo = migrations
            else:
                if not dry_run:
                    ensure_tracking(conn)
                todo = pending(conn, migrations)
            for m in todo:
                log(f"[migrate] {'would apply' if dry_run else 'applying'} {m.name}")
                if not dry_run:
                    apply(conn, m)
            if not todo:
                log("[migrate] nothing pending")
            if dry_run:
                log(f"[migrate] dry run: {len(todo)} pending, grants not applied")
                return [m.name for m in todo]
            run_grants(conn, grants, log=log)
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (LOCK_KEY,))
    log("[migrate] done")
    return [m.name for m in todo]


if __name__ == "__main__":
    sys.path.insert(0, str(SERVICE_ROOT))
    sys.exit(main())
