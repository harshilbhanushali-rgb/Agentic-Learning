"""Tests for ops/sync_to_deploy.py (issue #43), on throwaway upstream/downstream trees.

    ../.venv/Scripts/python -m pytest ops/test_sync_to_deploy.py -q     # from CS-platform
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_to_deploy as s  # noqa: E402


def write(root: Path, rel: str, text: str, crlf: bool = False) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.replace("\n", "\r\n").encode() if crlf else text.encode())
    return p


@pytest.fixture
def repos(tmp_path):
    up, down = tmp_path / "cs-platform", tmp_path / "coder-pets-tray"
    (down / "coder-pets-tray-app").mkdir(parents=True)
    (down / "ask-naren").mkdir(parents=True)
    return up, down


def keys(plan_items):
    return sorted(k for k, *_ in plan_items)


def test_adds_updates_and_skips_unchanged_on_first_sync(repos):
    up, down = repos
    write(up, "frontend/src/new.ts", "new\n")
    write(up, "frontend/src/changed.ts", "v2\n")
    write(up, "frontend/src/same.ts", "same\n")
    write(down, "coder-pets-tray-app/src/changed.ts", "v1\n")
    write(down, "coder-pets-tray-app/src/same.ts", "same\n", crlf=True)  # CRLF is not a change
    p = s.plan(up, down, {}, init=True)
    assert keys(p.write) == ["coder-pets-tray-app/src/changed.ts", "coder-pets-tray-app/src/new.ts"]
    assert p.unchanged == 1 and not p.drift


def test_first_sync_without_init_refuses_to_overwrite_a_differing_file(repos):
    up, down = repos
    write(up, "frontend/src/changed.ts", "v2\n")
    write(down, "coder-pets-tray-app/src/changed.ts", "v1\n")
    p = s.plan(up, down, {}, init=False)
    assert not p.write and len(p.drift) == 1 and "--init" in p.drift[0]


def test_never_writes_or_deletes_deployment_owned_files(repos):
    up, down = repos
    write(up, "frontend/src/app/api/health/route.ts", "upstream version\n")
    write(down, "coder-pets-tray-app/src/app/api/health/route.ts", "deploy version\n")
    write(down, "coder-pets-tray-app/src/app/api/metrics/route.ts", "deploy only\n")
    write(down, "coder-pets-tray-app/src/instrumentation.ts", "deploy only\n")
    write(up, "Brain/serve_ask_naren.py", "brain\n")
    write(down, "ask-naren/serve_ask_naren.py", "adapted\n")
    p = s.plan(up, down, {}, init=True)
    assert not p.write and not p.delete and not p.drift


def test_vendored_trees_are_refreshed_but_never_grown(repos):
    up, down = repos
    write(up, "Brain/shared/gateway.py", "fixed\n")
    write(up, "Brain/shared/unused_by_service.py", "pipeline only\n")
    write(down, "ask-naren/shared/gateway.py", "old\n")
    p = s.plan(up, down, {}, init=True)
    assert keys(p.write) == ["ask-naren/shared/gateway.py"]


def test_a_downstream_edit_since_the_last_sync_stops_it(repos):
    up, down = repos
    write(up, "frontend/src/a.ts", "v2\n")
    write(down, "coder-pets-tray-app/src/a.ts", "v1 plus a downstream hotfix\n")
    manifest = {"coder-pets-tray-app/src/a.ts": s._norm_hash(b"v1\n")}
    p = s.plan(up, down, manifest, init=False)
    assert not p.write and p.drift == ["coder-pets-tray-app/src/a.ts  (edited downstream since the last sync)"]


def test_an_untouched_synced_file_is_updated_on_later_syncs(repos):
    up, down = repos
    write(up, "frontend/src/a.ts", "v2\n")
    write(down, "coder-pets-tray-app/src/a.ts", "v1\n")
    manifest = {"coder-pets-tray-app/src/a.ts": s._norm_hash(b"v1\n")}
    assert keys(s.plan(up, down, manifest, init=False).write) == ["coder-pets-tray-app/src/a.ts"]


def test_deletes_only_what_it_synced_before_and_reports_the_rest(repos):
    up, down = repos
    write(up, "frontend/src/keep.ts", "k\n")
    write(down, "coder-pets-tray-app/src/keep.ts", "k\n")
    write(down, "coder-pets-tray-app/src/app/workspace/page.tsx", "archived upstream\n")
    write(down, "coder-pets-tray-app/src/stray.ts", "someone added this downstream\n")
    manifest = {"coder-pets-tray-app/src/app/workspace/page.tsx": s._norm_hash(b"archived upstream\n")}
    p = s.plan(up, down, manifest, init=False)
    assert keys(p.delete) == ["coder-pets-tray-app/src/app/workspace/page.tsx"]
    assert p.unknown == ["coder-pets-tray-app/src/stray.ts"]


def test_a_file_removed_upstream_but_edited_downstream_is_drift_not_a_delete(repos):
    up, down = repos
    write(down, "coder-pets-tray-app/src/gone.ts", "edited downstream\n")
    manifest = {"coder-pets-tray-app/src/gone.ts": s._norm_hash(b"as synced\n")}
    p = s.plan(up, down, manifest, init=False)
    assert not p.delete and len(p.drift) == 1


def test_apply_writes_deletes_and_records_hashes_for_the_next_run(repos):
    up, down = repos
    write(up, "frontend/src/a.ts", "v2\n")
    write(up, "frontend/src/same.ts", "same\n")
    write(down, "coder-pets-tray-app/src/a.ts", "v1\n")
    write(down, "coder-pets-tray-app/src/same.ts", "same\n")
    write(down, "coder-pets-tray-app/src/old.ts", "old\n")
    p = s.plan(up, down, {}, init=True)
    files = s.apply(p, up, down, {})
    assert (down / "coder-pets-tray-app/src/a.ts").read_text() == "v2\n"
    assert not (down / "coder-pets-tray-app/src/old.ts").exists()
    assert set(files) == {"coder-pets-tray-app/src/a.ts", "coder-pets-tray-app/src/same.ts"}
    # A second run is a no-op, and a later downstream edit to an identical file is caught.
    assert not s.plan(up, down, files, init=False).write
    write(down, "coder-pets-tray-app/src/same.ts", "hotfix\n")
    write(up, "frontend/src/same.ts", "same v2\n")
    assert len(s.plan(up, down, files, init=False).drift) == 1
