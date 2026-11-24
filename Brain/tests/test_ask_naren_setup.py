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
from ask_naren.db import setup
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


# -- the guards on the new logins' URLs ---------------------------------------------------------

class _Admin:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append(statement)


TARGET = "postgresql://postgres:pw@prod.abc.us-east-1.rds.amazonaws.com:5432/ask_naren"


def test_a_login_url_for_the_right_database_sets_that_roles_password():
    admin = _Admin()
    setup._set_password_from(
        admin, "postgresql://ask_naren_service:" + "p" * 20 + "@prod.abc.us-east-1.rds.amazonaws.com/ask_naren",
        "ask_naren_service", TARGET, log=lambda line: None)
    assert len(admin.statements) == 1


@pytest.mark.parametrize("url, why", [
    ("postgresql://ask_naren_app:" + "p" * 20 + "@prod.abc.us-east-1.rds.amazonaws.com/ask_naren",
     "logs in as"),
    ("postgresql://ask_naren_service:" + "p" * 20 + "@staging.xyz.us-east-1.rds.amazonaws.com/ask_naren",
     "not at"),
    ("postgresql://ask_naren_service:short@prod.abc.us-east-1.rds.amazonaws.com/ask_naren",
     "16\\+ characters"),
])
def test_a_login_url_for_another_role_database_or_with_a_weak_password_is_refused(url, why):
    admin = _Admin()
    with pytest.raises(CopyRefused, match=why):
        setup._set_password_from(admin, url, "ask_naren_service", TARGET, log=lambda line: None)
    assert admin.statements == []


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
