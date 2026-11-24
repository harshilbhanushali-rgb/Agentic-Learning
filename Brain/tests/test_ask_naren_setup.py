"""POST /admin/setup: filling a database only the deployment can reach (2026-11-24).

Network-free: the routes and the background job run with fake steps, and the guards on the
logins' URLs are pure functions. The steps themselves are rehearsed against a throwaway
database on staging (Brain/ask_naren/db/README.md), because their whole job is SQL.
"""
from __future__ import annotations

import asyncio
import threading

import httpx
import pytest

from ask_naren import api
from ask_naren.db import copy as tables_copy
from ask_naren.db import admin_setup as setup
from ask_naren.db.copy import CopyRefused

TOKEN = "t" * 40


async def _answer(situation, thread=()):
    return {"outcome": "declined"}


def _client(jobs):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=api.build_app(_answer, setup=jobs)),
                             base_url="http://test")


def _auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


# -- off, and the token -------------------------------------------------------------------------

def test_off_by_default_both_routes_look_like_they_do_not_exist():
    async def go():
        async with _client(None) as c:
            return (await c.post("/admin/setup/brain", headers=_auth())).status_code, \
                   (await c.get("/admin/setup", headers=_auth())).status_code
    assert asyncio.run(go()) == (404, 404)


def test_a_wrong_or_missing_token_is_refused():
    jobs = setup.SetupJobs(TOKEN, runners={"brain": lambda log: {}})

    async def go():
        async with _client(jobs) as c:
            return [(await c.post("/admin/setup/brain", headers=h)).status_code
                    for h in (_auth("x" * 40), _auth(TOKEN[:-1]), {})]
    assert asyncio.run(go()) == [401, 401, 401]
    assert jobs.state["status"] == "idle"


def test_a_short_token_keeps_the_endpoint_off(monkeypatch):
    monkeypatch.setenv(setup.TOKEN_ENV, "short")
    assert setup.SetupJobs.from_env() is None
    monkeypatch.delenv(setup.TOKEN_ENV)
    assert setup.SetupJobs.from_env() is None
    monkeypatch.setenv(setup.TOKEN_ENV, TOKEN)
    assert setup.SetupJobs.from_env() is not None


# -- the background job -------------------------------------------------------------------------

def test_a_step_runs_in_the_background_and_reports_its_result():
    jobs = setup.SetupJobs(TOKEN, runners={"brain": lambda log: (log("working"), {"n": 1})[1],
                                           "logins": lambda log: {}})

    async def go():
        async with _client(jobs) as c:
            started = await c.post("/admin/setup/brain", headers=_auth())
            for _ in range(100):
                status = (await c.get("/admin/setup", headers=_auth())).json()
                if status["status"] != "running":
                    break
                await asyncio.sleep(0.01)
            return started, status
    started, status = asyncio.run(go())
    assert started.status_code == 202 and started.json()["step"] == "brain"
    assert status["status"] == "done" and status["result"] == {"n": 1}
    assert any("working" in line for line in status["log"])


def test_only_one_step_runs_at_a_time():
    release = threading.Event()
    jobs = setup.SetupJobs(TOKEN, runners={"brain": lambda log: release.wait(5) and {},
                                           "logins": lambda log: {}})

    async def go():
        async with _client(jobs) as c:
            first = await c.post("/admin/setup/brain", headers=_auth())
            second = await c.post("/admin/setup/logins", headers=_auth())
            release.set()
            await jobs._task
            return first.status_code, second.status_code
    assert asyncio.run(go()) == (202, 409)


def test_an_unknown_step_is_a_400():
    jobs = setup.SetupJobs(TOKEN)

    async def go():
        async with _client(jobs) as c:
            return await c.post("/admin/setup/everything", headers=_auth())
    r = asyncio.run(go())
    assert r.status_code == 400 and r.json()["steps"] == ["brain", "logins"]


def _finished(jobs, step):
    async def go():
        assert jobs.start(step)
        await jobs._task
    asyncio.run(go())
    return jobs.snapshot()


def test_a_refusal_is_reported_not_raised():
    def refuse(log):
        raise CopyRefused("the target already holds rows")
    snap = _finished(setup.SetupJobs(TOKEN, runners={"brain": refuse}), "brain")
    assert snap["status"] == "refused" and "already holds rows" in snap["error"]


def test_a_crash_is_reported_not_raised():
    def crash(log):
        raise RuntimeError("connection refused")
    snap = _finished(setup.SetupJobs(TOKEN, runners={"brain": crash}), "brain")
    assert snap["status"] == "failed" and "connection refused" in snap["error"]


def test_a_system_exit_inside_a_step_is_reported_and_the_service_keeps_running():
    """Bug hunt 2026-11-24: SystemExit escaped `except Exception` and stopped the process."""
    def edited_migration(log):
        raise SystemExit("these migrations were applied and have been EDITED since")
    snap = _finished(setup.SetupJobs(TOKEN, runners={"brain": edited_migration}), "brain")
    assert snap["status"] == "failed" and "EDITED" in snap["error"]


def test_the_migration_runner_refuses_with_an_exception_not_an_exit():
    from ask_naren.db import migrate
    ms = migrate.collect([("brain", migrate.MIGRATIONS)])

    class _Tracked:
        def execute(self, sql, params=None):
            class _C:
                def fetchall(self_inner):
                    return [(ms[0].name, "0" * 64)]
            return _C()
    with pytest.raises(migrate.MigrationRefused):
        migrate.pending(_Tracked(), ms)


# -- the target, the new logins, and the same-database check ------------------------------------

TARGET = "postgresql://postgres:mpw@prod.abc.us-east-1.rds.amazonaws.com:5432/ask_naren?sslmode=require"


def test_the_target_is_postgres_url_unless_an_explicit_override_is_set(monkeypatch):
    monkeypatch.delenv("ASK_NAREN_MIGRATE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    with pytest.raises(CopyRefused, match="POSTGRES_URL"):
        setup.target_url()
    monkeypatch.setenv("POSTGRES_URL", TARGET)
    assert setup.target_url() == TARGET
    monkeypatch.setenv("ASK_NAREN_MIGRATE_URL", "postgresql://other@h/db")
    assert setup.target_url() == "postgresql://other@h/db"


def test_a_login_url_is_the_admin_url_with_only_the_login_swapped():
    url = setup.role_url(TARGET, "ask_naren_service", "a/b@c:d%e" + "x" * 10)
    from urllib.parse import unquote, urlparse
    p = urlparse(url)
    assert (p.username, unquote(p.password)) == ("ask_naren_service", "a/b@c:d%e" + "x" * 10)
    assert (p.hostname, p.port, p.path, p.query) == ("prod.abc.us-east-1.rds.amazonaws.com",
                                                     5432, "/ask_naren", "sslmode=require")


def test_same_database_ignores_the_login_but_not_the_host_or_database():
    other_login = "postgresql://ask_naren_service:x@prod.abc.us-east-1.rds.amazonaws.com/ask_naren"
    assert setup._same_database(TARGET, other_login)
    assert not setup._same_database(TARGET, other_login.replace("/ask_naren", "/staging"))
    assert not setup._same_database(TARGET, other_login.replace("prod.abc", "stg.xyz"))


def test_a_short_new_password_is_refused(monkeypatch):
    monkeypatch.setenv(setup.SERVICE_PASSWORD_ENV, "short")
    with pytest.raises(CopyRefused, match="16"):
        setup._new_password(setup.SERVICE_PASSWORD_ENV)
    monkeypatch.delenv(setup.SERVICE_PASSWORD_ENV)
    assert setup._new_password(setup.SERVICE_PASSWORD_ENV) is None


class _Admin:
    def __init__(self, live=0):
        self.live, self.statements = live, []

    def execute(self, statement, params=None):
        self.statements.append(statement)
        live = self.live

        class _C:
            def fetchone(self_inner):
                return (live,)
        return _C()


def test_a_password_is_set_only_while_nobody_uses_that_login_anywhere():
    """Bug hunt 2026-11-24: RDS roles are instance-wide; changing a live login's password
    cuts off whatever app uses it, on any database."""
    admin = _Admin(live=0)
    setup._set_password(admin, "ask_naren_service", "p" * 20, log=lambda line: None)
    assert len(admin.statements) == 2
    busy = _Admin(live=3)
    with pytest.raises(CopyRefused, match="open connection"):
        setup._set_password(busy, "ask_naren_service", "p" * 20, log=lambda line: None)
    assert len(busy.statements) == 1        # only the check; no ALTER ROLE


# -- the sign-in copy refuses to finish without every table and a person ------------------------

def test_a_sign_in_source_missing_a_table_or_people_is_refused():
    """Bug hunt 2026-11-24: an unreadable source finished "done" with nothing copied."""
    setup.require_sign_in_source(["users", "threads", "turns", "feedback"], users=5)
    with pytest.raises(CopyRefused, match="feedback"):
        setup.require_sign_in_source(["users", "threads", "turns"], users=5)
    with pytest.raises(CopyRefused, match="users"):
        setup.require_sign_in_source([], users=0)
    with pytest.raises(CopyRefused, match="no users"):
        setup.require_sign_in_source(["users", "threads", "turns", "feedback"], users=0)


# -- no secret reaches a log line or the GET response -------------------------------------------

def test_every_setup_secret_is_scrubbed_including_from_malformed_urls(monkeypatch):
    """Bug hunt 2026-11-24: libpq quoted a raw password back ("invalid percent-encoded token")
    and a raw `/` put part of one into the host name."""
    monkeypatch.setenv("POSTGRES_URL", "postgresql://master:Pa/ss%zzWord@db.x.rds.amazonaws.com/d")
    monkeypatch.setenv(setup.SERVICE_PASSWORD_ENV, "svc-password-0123456789")
    monkeypatch.setenv(setup.TOKEN_ENV, TOKEN)
    # Built by role_url (as production builds the logins' URLs), so it arrives URL-encoded.
    monkeypatch.setenv("ASK_NAREN_SETUP_LOGINS_FROM",
                       setup.role_url("postgresql://x@n.neon.tech/db", "app", "enc@oded/pw"))
    line = ('invalid percent-encoded token: "Pa/ss%zzWord"; host "ss%zzWord@db.x"; '
            'svc-password-0123456789; ' + TOKEN + '; enc@oded/pw; enc%40oded%2Fpw')
    out = setup.scrub(line)
    for secret in ("Pa/ss%zzWord", "svc-password-0123456789", TOKEN, "enc@oded/pw", "enc%40oded%2Fpw"):
        assert secret not in out, secret


def test_errors_and_log_lines_from_a_step_are_scrubbed(monkeypatch):
    monkeypatch.setenv("POSTGRES_URL", "postgresql://master:Se/CrEt%zzPASS@db.x.rds.amazonaws.com/d")

    def leaky(log):
        log("connecting with Se/CrEt%zzPASS")
        raise RuntimeError('invalid percent-encoded token: "Se/CrEt%zzPASS"')
    snap = _finished(setup.SetupJobs(TOKEN, runners={"brain": leaky}), "brain")
    assert "CrEt" not in snap["error"] and not any("CrEt" in line for line in snap["log"])


def test_a_url_that_does_not_parse_cleanly_is_never_echoed():
    from ask_naren.db import redacted
    for url in ("postgresql://master/PASSWORD@db.nohost.invalid/naren",
                "postgresql://master:pa/ss@db.x.rds.amazonaws.com/d"):
        assert "PASSWORD" not in redacted(url) and "pa/ss" not in redacted(url)


def test_the_scram_verifier_never_contains_the_password():
    verifier = setup._scram_verifier("correct horse battery staple")
    assert verifier.startswith("SCRAM-SHA-256$4096:") and "horse" not in verifier


# -- the SQL it applies is found upstream and in the image --------------------------------------

def test_brains_schema_and_the_web_apps_migrations_are_found():
    assert tables_copy.brain_schema_sql().read_text().count("CREATE TABLE") > 5
    web = tables_copy.web_app_db_dir()
    assert (web / "migrations").is_dir() and (web / "provision" / "grants.sql").is_file()


def test_every_migration_and_grants_file_one_database_needs():
    from ask_naren.db import migrate
    trees, grants = migrate.everything()
    assert [track for track, _ in trees] == ["brain", "ask_naren"]
    assert [g.name for g in grants] == ["grants.sql", "roles.sql", "grants.sql"]
