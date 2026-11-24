"""What POST /admin/setup does: fill an EMPTY Ask Naren database, from inside the deployment.

Production's RDS is reachable only from inside production, so it cannot be set up from a
laptop (ops/copy_brain_to_rds.py). Two steps, each started over HTTP and run in the
background, reported by GET /admin/setup:

  brain    migrations (Brain's and the web app's), the logins' passwords, then the Brain --
           tables AND trigger vectors -- copied from a database that already holds it in
           pgvector (staging). Proves each login can and cannot do what it should.
  logins   users, threads, turns and feedback from the current sign-in database (Neon).
           Run at cutover with the web app stopped, so nothing written mid-copy is lost.

WHAT MAKES IT SAFE TO LEAVE REACHABLE FOR A FEW DAYS:
  * OFF unless ASK_NAREN_SETUP_TOKEN (>= 32 characters) is set; the routes answer 404 then.
  * IT ONLY FILLS AN EMPTY DATABASE, and checks that FIRST: a target holding a Brain, or one
    Ask Naren is connected to, is refused before any migration or password change runs. A
    leaked token cannot wipe, replace or overwrite anything.
  * A login's password is never changed while that login is connected anywhere on the
    instance -- RDS roles are instance-wide, so that would cut off a live deployment.
  * The SOURCE logins only read: staging's ask_naren_service for the Brain, the web app's
    own login for sign-in data.
  * No secret is logged or returned: every line and error is scrubbed of every setup secret.

Settings of the ask-naren deployment:
  POSTGRES_URL                 the NEW database, admin login -- created by the platform
                               (ASK_NAREN_MIGRATE_URL, if set, is used instead)
  ASK_NAREN_SETUP_TOKEN        enables the endpoint; sent as `Authorization: Bearer <token>`
  ASK_NAREN_SETUP_BRAIN_FROM   a pgvector Brain to copy (staging, ask_naren_service login)
  ASK_NAREN_SETUP_LOGINS_FROM  the current sign-in database (Neon, ask_naren_app login)
  ASK_NAREN_SETUP_SERVICE_PASSWORD  new password for ask_naren_service (16+ characters)
  ASK_NAREN_SETUP_APP_PASSWORD      new password for ask_naren_app (16+ characters)
All but POSTGRES_URL are temporary: remove them after cutover.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlparse, urlunparse

from ask_naren.db import GRANTS, connection_url, redacted
from ask_naren.db import copy as tables_copy
from ask_naren.db.copy import CopyRefused

TOKEN_ENV = "ASK_NAREN_SETUP_TOKEN"
TARGET_ENVS = ("ASK_NAREN_MIGRATE_URL", "POSTGRES_URL")       # explicit override first
SERVICE_PASSWORD_ENV = "ASK_NAREN_SETUP_SERVICE_PASSWORD"
APP_PASSWORD_ENV = "ASK_NAREN_SETUP_APP_PASSWORD"
#: Every setting that holds a secret. Their values -- and the passwords inside URLs -- are
#: scrubbed from every log line and error this module produces.
SECRET_ENVS = (TOKEN_ENV, *TARGET_ENVS, "RDS_PASSWORD", "ASK_NAREN_SETUP_BRAIN_FROM",
               "ASK_NAREN_SETUP_LOGINS_FROM", SERVICE_PASSWORD_ENV, APP_PASSWORD_ENV)
MIN_TOKEN_CHARS = 32
MIN_PASSWORD_CHARS = 16
STEPS = ("brain", "logins")
#: What ask_naren_service reads (grants.sql). A Brain source missing any of these is refused.
SERVICE_TABLES = ("scenarios", "kb_pairs", "calls", "playbooks", "brain_meta", "trigger_vectors")
#: What the web app's sign-in needs. A copy that would leave any of these empty is refused:
#: an empty `users` at cutover locks every person out (Google admits only known users).
SIGN_IN_TABLES = ("users", "threads", "turns", "feedback")
MAX_LOG_LINES = 400


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CopyRefused(f"{name} is not set on this deployment")
    return value


def target_url() -> str:
    for name in TARGET_ENVS:
        if value := os.environ.get(name, "").strip():
            return value
    raise CopyRefused("neither POSTGRES_URL nor ASK_NAREN_MIGRATE_URL is set on this deployment")


def _same_database(a: str, b: str) -> bool:
    """Host, port and database name -- NOT the login, so two logins to one database match."""
    pa, pb = urlparse(a), urlparse(b)
    return ((pa.hostname, pa.port or 5432, pa.path.rstrip("/"))
            == (pb.hostname, pb.port or 5432, pb.path.rstrip("/")))


def role_url(admin_url: str, role: str, password: str) -> str:
    """`admin_url` with the login swapped for `role` -- the same host, port, database and
    options. The password is URL-encoded, so any characters are safe."""
    p = urlparse(admin_url)
    port = f":{p.port}" if p.port else ""
    return urlunparse(p._replace(netloc=f"{quote(role)}:{quote(password, safe='')}@{p.hostname}{port}"))


def _new_password(env: str) -> str | None:
    value = os.environ.get(env, "")
    if not value:
        return None
    if len(value) < MIN_PASSWORD_CHARS:
        raise CopyRefused(f"{env} must be at least {MIN_PASSWORD_CHARS} characters")
    return value


# ---------------------------------------------------------------------------------------
# keeping secrets out of logs and responses
# ---------------------------------------------------------------------------------------

_URL_PASSWORD = re.compile(r"^[a-z][a-z0-9+.-]*://[^:/@]*:(?P<pw>.+)@[^@]+$", re.I)


def secrets_in_env() -> list[str]:
    """Every secret a setup step could ever echo: each secret setting's whole value, and the
    password inside each URL -- raw AND URL-decoded, and found even when the URL is malformed
    (a raw `/` or `@` in it), because a malformed one is exactly what libpq quotes back."""
    found: set[str] = set()
    for name in SECRET_ENVS:
        value = os.environ.get(name, "").strip()
        if not value:
            continue
        found.add(value)
        if m := _URL_PASSWORD.match(value):
            found.update({m["pw"], unquote(m["pw"])})
        parsed = urlparse(value).password
        if parsed:
            found.update({parsed, unquote(parsed)})
    return sorted((s for s in found if len(s) >= 4), key=len, reverse=True)


def scrub(text: str, secrets: list[str] | None = None) -> str:
    for secret in secrets if secrets is not None else secrets_in_env():
        text = text.replace(secret, "***")
    return text


# ---------------------------------------------------------------------------------------
# logins and passwords
# ---------------------------------------------------------------------------------------

def _scram_verifier(password: str) -> str:
    """A SCRAM-SHA-256 verifier, so the password itself never reaches the server's logs."""
    salt = os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 4096)
    client_key = hmac.new(salted, b"Client Key", "sha256").digest()
    server_key = hmac.new(salted, b"Server Key", "sha256").digest()
    b64 = lambda raw: base64.b64encode(raw).decode()  # noqa: E731
    return (f"SCRAM-SHA-256$4096:{b64(salt)}${b64(hashlib.sha256(client_key).digest())}"
            f":{b64(server_key)}")


def _set_password(admin, role: str, password: str, log) -> None:
    """Give `role` this password -- refused while `role` is connected ANYWHERE on the instance.
    RDS roles are instance-wide, so a live deployment on another database could be cut off
    (bug hunt, 2026-11-24)."""
    from psycopg import sql
    live = admin.execute("select count(*) from pg_stat_activity where usename = %s",
                         (role,)).fetchone()[0]
    if live:
        raise CopyRefused(f"{role} has {live} open connection(s) on this instance -- changing "
                          f"its password now would cut a running app off")
    admin.execute(sql.SQL("alter role {} password {}").format(
        sql.Identifier(role), sql.Literal(_scram_verifier(password))))
    log(f"[logins] password set for {role}")


def _prove_logins(service_url: str | None, app_url: str | None, log) -> dict:
    """Log in as each new login and check what it can and cannot do."""
    import psycopg
    proof = {}
    if service_url:
        with psycopg.connect(connection_url(service_url), autocommit=True,
                             connect_timeout=15) as c:
            ro = c.execute("select current_setting('default_transaction_read_only')").fetchone()[0]
            pairs = c.execute("select count(*) from brain.kb_pairs").fetchone()[0]
            proof["ask_naren_service"] = {"read_only": ro, "reads_kb_pairs": pairs}
            if ro != "on":
                raise CopyRefused("ask_naren_service is not read-only")
    if app_url:
        with psycopg.connect(connection_url(app_url), autocommit=True, connect_timeout=15) as c:
            row = c.execute(
                """select (r.rolsuper or r.rolcreaterole or r.rolcreatedb or r.rolbypassrls),
                          exists (select 1 from pg_roles s
                                  where s.rolname in ('rds_superuser', 'pg_write_all_data')
                                    and pg_has_role(current_user, s.oid, 'MEMBER')),
                          coalesce((select has_table_privilege(c.oid, 'SELECT')
                                    from pg_class c join pg_namespace n on n.oid = c.relnamespace
                                    where n.nspname = 'brain' and c.relname = 'kb_pairs'), false),
                          has_table_privilege('ask_naren.users', 'SELECT')
                   from pg_roles r where r.rolname = current_user""").fetchone()
            proof["ask_naren_app"] = {"elevated": row[0], "privileged_member": row[1],
                                      "reads_brain": row[2], "reads_users": row[3]}
            if row[0] or row[1] or row[2] or not row[3]:
                raise CopyRefused(f"ask_naren_app has the wrong privileges: "
                                  f"{proof['ask_naren_app']}")
    for role, facts in proof.items():
        log(f"[logins] {role} checked: {facts}")
    return proof


# ---------------------------------------------------------------------------------------
# the two steps
# ---------------------------------------------------------------------------------------

def _refuse_unless_empty_brain(target: str) -> None:
    """BEFORE anything is written: refuse a target that already holds a Brain or that Ask
    Naren is connected to. Migrations and passwords used to run first, so even a refused run
    changed the logins' passwords (bug hunt, 2026-11-24)."""
    import psycopg
    with psycopg.connect(connection_url(target), autocommit=True, connect_timeout=15) as admin:
        tables_copy.refuse_if_live(admin, "ask_naren_service")
        if admin.execute("select to_regclass('brain.kb_pairs')").fetchone()[0] is not None:
            tables_copy.require_empty(admin, "brain", ["kb_pairs", "trigger_vectors"])


def run_brain(log) -> dict:
    import psycopg
    from ask_naren.db.migrate import everything, migrate_database, run_grants

    target = target_url()
    source = _env("ASK_NAREN_SETUP_BRAIN_FROM")
    service_pw, app_pw = _new_password(SERVICE_PASSWORD_ENV), _new_password(APP_PASSWORD_ENV)
    if _same_database(source, target):
        raise CopyRefused("the Brain source and the target are the same database")
    log(f"[brain] from {redacted(source)} into {redacted(target)}")

    _refuse_unless_empty_brain(target)
    migrate_database(target, *everything(), log=log)
    with psycopg.connect(connection_url(target), autocommit=True, connect_timeout=15) as admin:
        if service_pw:
            _set_password(admin, "ask_naren_service", service_pw, log)
        if app_pw:
            _set_password(admin, "ask_naren_app", app_pw, log)

    # The target in AUTOCOMMIT, with one explicit transaction for the copy: a non-autocommit
    # connection would open an implicit transaction on its first query, and the copy's block
    # would silently become a savepoint inside it.
    with psycopg.connect(connection_url(source), connect_timeout=30) as src, \
         psycopg.connect(connection_url(target), autocommit=True, connect_timeout=30) as dst:
        src.execute("set transaction isolation level repeatable read read only")
        # The source is read with staging's ask_naren_service, whose role caps statements at
        # 30s for SEARCHES. Copying ~160 MB of vectors is not a search.
        src.execute("set statement_timeout = '15min'")
        src_tables = set(tables_copy.readable_tables(src, "brain"))
        missing = [t for t in SERVICE_TABLES if t not in src_tables]
        if missing:
            raise CopyRefused(f"the Brain source cannot be read for {missing} -- it must be a "
                              f"pgvector Brain (brain_meta.vector_store = pgvector)")
        meta = dict(src.execute("select key, value from brain.brain_meta").fetchall())
        if meta.get("vector_store") != "pgvector":
            raise CopyRefused("the Brain source is not a pgvector Brain")
        same_pgvector = (src.execute("select extversion from pg_extension where extname = 'vector'")
                         .fetchone() == dst.execute("select extversion from pg_extension "
                                                    "where extname = 'vector'").fetchone())
        with dst.transaction():
            dst.execute("set local search_path = brain, extensions")
            dst.execute(tables_copy.brain_schema_sql().read_text(encoding="utf-8-sig"))
            names = tables_copy.plan(src, dst, "brain", "brain", src_tables=src_tables, log=log)
            tables_copy.refuse_if_live(dst, "ask_naren_service")
            tables_copy.require_empty(dst, "brain", names)
            counts = tables_copy.copy_tables(
                src, dst, "brain", "brain", names, log=log,
                binary_tables=frozenset({"trigger_vectors"}) if same_pgvector else frozenset())
            # This copy is a new generation: the store refuses to search a Brain whose
            # copied_at changed under it (vector_store.PgVectorTriggerStore).
            for key, value in {"copied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "copied_from": redacted(source)}.items():
                dst.execute("insert into brain.brain_meta (key, value) values (%s, %s) "
                            "on conflict (key) do update set value = excluded.value", (key, value))
            bad = tables_copy.mismatched_counts(
                src, "brain", {t: n for t, n in counts.items() if t != "brain_meta"})
            if bad:
                raise CopyRefused(f"counts differ after the copy (source, target): {bad}")
            if not counts.get("kb_pairs") or counts.get("trigger_vectors") != counts.get("kb_pairs"):
                raise CopyRefused(f"{counts.get('trigger_vectors')} vectors for "
                                  f"{counts.get('kb_pairs')} pairs")
        src.rollback()
        run_grants(dst, [GRANTS], log=log)  # Brain's tables exist now; grant them

    proof = _prove_logins(role_url(target, "ask_naren_service", service_pw) if service_pw else None,
                          role_url(target, "ask_naren_app", app_pw) if app_pw else None, log)
    log(f"[brain] done: {counts}")
    return {"copied": counts, "source": meta.get("source"), "logins": proof}


def require_sign_in_source(names: list[str], users: int) -> None:
    """Every sign-in table, and at least one person, or nothing. A source login that cannot
    see a table (the wrong Neon database, a missing grant) used to finish "done" having copied
    nothing into it -- and an empty `users` at cutover locks everyone out (bug hunt,
    2026-11-24)."""
    unread = [t for t in SIGN_IN_TABLES if t not in names]
    if unread:
        raise CopyRefused(f"the sign-in source cannot be read for {unread} -- is "
                          f"ASK_NAREN_SETUP_LOGINS_FROM the web app's own database?")
    if not users:
        raise CopyRefused("the sign-in source has no users -- is ASK_NAREN_SETUP_LOGINS_FROM "
                          "the web app's own database?")


def run_logins(log) -> dict:
    import psycopg

    target = target_url()
    source = _env("ASK_NAREN_SETUP_LOGINS_FROM")
    if _same_database(source, target):
        raise CopyRefused("the sign-in source and the target are the same database")
    log(f"[logins] from {redacted(source)} into {redacted(target)}")
    with psycopg.connect(connection_url(source), connect_timeout=30) as src, \
         psycopg.connect(connection_url(target), autocommit=True, connect_timeout=30) as dst:
        src.execute("set transaction isolation level repeatable read read only")
        others = src.execute(
            "select count(*) from pg_stat_activity where usename = current_user "
            "and pid <> pg_backend_pid() and datname = current_database()").fetchone()[0]
        if others:
            log(f"[logins] NOTE: {others} other session(s) of this login are open on the "
                f"source -- if the web app is still running, anything it writes after this "
                f"snapshot will not be copied")
        if dst.execute("select to_regclass('ask_naren.users')").fetchone()[0] is None:
            raise CopyRefused("the target has no ask_naren tables -- run the brain step first")
        with dst.transaction():
            names = tables_copy.plan(src, dst, "ask_naren", "ask_naren",
                                     src_tables=set(tables_copy.readable_tables(src, "ask_naren")),
                                     exclude=frozenset({"sessions"}), log=log)
            require_sign_in_source(names, tables_copy.count(src, "ask_naren", "users")
                                   if "users" in names else 0)
            tables_copy.refuse_if_live(dst, "ask_naren_app")
            tables_copy.require_empty(dst, "ask_naren", names)
            counts = tables_copy.copy_tables(src, dst, "ask_naren", "ask_naren", names, log=log)
            bad = tables_copy.mismatched_counts(src, "ask_naren", counts)
            if bad:
                raise CopyRefused(f"counts differ after the copy (source, target): {bad}")
        src.rollback()
    log(f"[logins] done: {counts}")
    return {"copied": counts}


RUNNERS = {"brain": run_brain, "logins": run_logins}


# ---------------------------------------------------------------------------------------
# the background job behind the endpoint
# ---------------------------------------------------------------------------------------

class SetupJobs:
    """At most one step running at a time; its log and outcome kept for GET /admin/setup."""

    def __init__(self, token: str, runners=None):
        if len(token) < MIN_TOKEN_CHARS:
            raise ValueError(f"{TOKEN_ENV} must be at least {MIN_TOKEN_CHARS} characters")
        self._token = token.encode()
        self._runners = runners or RUNNERS
        self._lock = threading.Lock()
        self._task: asyncio.Task | None = None
        self.state = {"step": None, "status": "idle", "started_at": None,
                      "finished_at": None, "result": None, "error": None, "log": []}

    @classmethod
    def from_env(cls) -> "SetupJobs | None":
        token = os.environ.get(TOKEN_ENV, "").strip()
        if not token:
            return None
        if len(token) < MIN_TOKEN_CHARS:
            print(f"[setup] {TOKEN_ENV} is shorter than {MIN_TOKEN_CHARS} characters -- "
                  f"POST /admin/setup stays OFF", flush=True)
            return None
        print("[setup] POST /admin/setup is ON -- remove the setup settings after cutover",
              flush=True)
        return cls(token)

    def authorised(self, header: str | None) -> bool:
        given = (header or "").removeprefix("Bearer ").strip().encode()
        return hmac.compare_digest(given, self._token)

    def _log(self, line: str) -> None:
        line = scrub(line)
        stamped = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {line}"
        print(f"[setup] {line}", flush=True)
        with self._lock:
            self.state["log"] = (self.state["log"] + [stamped])[-MAX_LOG_LINES:]

    def start(self, step: str) -> bool:
        """Start `step` in the background. False if one is already running."""
        if self._task is not None and not self._task.done():
            return False
        self.state = {"step": step, "status": "running",
                      "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "finished_at": None, "result": None, "error": None, "log": []}
        self._task = asyncio.get_running_loop().create_task(self._run(step))
        return True

    async def _run(self, step: str) -> None:
        t0 = time.monotonic()
        try:
            result = await asyncio.to_thread(self._runners[step], self._log)
            self.state.update(status="done", result=result)
        except CopyRefused as refusal:
            message = scrub(str(refusal))
            self._log(f"REFUSED: {message}")
            self.state.update(status="refused", error=message)
        # SystemExit too: one escaping from a step used to stop the WHOLE service, cutting off
        # every answer in flight (bug hunt, 2026-11-24). Never CancelledError -- shutdown.
        except (Exception, SystemExit) as exc:  # noqa: BLE001 -- reported, never raised
            message = scrub(f"{type(exc).__name__}: {exc}")
            self._log(f"FAILED: {message}")
            self.state.update(status="failed", error=message)
        finally:
            self.state["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._log(f"{step}: {self.state['status']} in {time.monotonic() - t0:.0f}s")

    def snapshot(self) -> dict:
        with self._lock:
            return {**self.state, "log": list(self.state["log"])}
