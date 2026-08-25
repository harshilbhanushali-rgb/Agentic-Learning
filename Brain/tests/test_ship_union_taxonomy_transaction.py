"""The single-transaction guarantee in ops/ship_union_taxonomy.py, pinned.

The script's docstring promises "Deletes and the load run in ONE transaction. Any failure
rolls the whole thing back." That promise was FALSE from the day it was written and stayed
false for five days: `storage.upsert_scenario` ends in `conn.commit()`, and the script's
connection is deliberately not autocommit, so the first of 259 upserts committed step 2's
children-first DELETEs. Worse, the post-load `conn.rollback()` then had nothing to undo and
still printed "rolled back" -- a false negative on the one check protecting a taxonomy
replacement.

Two tests, because there are two independent ways to break it again:
  1. `upsert_scenario` must honour `commit=False`.
  2. the script must actually PASS `commit=False`.

The second is a source-level tripwire rather than an import: `ops/` is deliberately not a
package (see Brain/CLAUDE.md), so there is no `ops.ship_union_taxonomy` to import, and
that is on purpose -- importing a sibling like `clear_data.py` wipes live data.
"""
from pathlib import Path

import pytest

from shared import storage

SHIP = Path(__file__).resolve().parent.parent / "ops" / "ship_union_taxonomy.py"


class _FakeCursor:
    def __init__(self, owner):
        self._owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._owner.executed.append(sql)

    def fetchone(self):
        return (4242,)


class _FakeConn:
    """Records commits instead of performing them."""

    def __init__(self):
        self.commits = 0
        self.executed: list[str] = []

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1


def _row():
    return {
        "scenario_key": "k",
        "primary_topic": "t",
        "business_description": "d",
        "keyphrases": [],
        "soft_skills": [],
        "bloom_level": "understand",
    }


def test_upsert_scenario_commits_by_default():
    """The default must stay True -- Layer A writes ~259 scenarios across a long run and
    must not hold one transaction open across slow work."""
    conn = _FakeConn()
    assert storage.upsert_scenario(conn, _row()) == 4242
    assert conn.commits == 1


def test_upsert_scenario_does_not_commit_when_told_not_to():
    conn = _FakeConn()
    assert storage.upsert_scenario(conn, _row(), commit=False) == 4242
    assert conn.commits == 0, "commit=False still committed — the guarantee is broken again"


def test_commit_is_keyword_only():
    """Positional would let a caller pass a dict-shaped second arg into it by accident."""
    import inspect
    p = inspect.signature(storage.upsert_scenario).parameters["commit"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY
    assert p.default is True


@pytest.mark.parametrize("needle", ["storage.upsert_scenario(conn, r, commit=False)"])
def test_ship_script_passes_commit_false(needle):
    """THE TRIPWIRE. If this fails, the migration silently stopped being atomic."""
    src = SHIP.read_text(encoding="utf-8-sig")
    assert needle in src, (
        "ops/ship_union_taxonomy.py no longer passes commit=False — its "
        "single-transaction guarantee is false again and a failed taxonomy "
        "replacement can leave every child table deleted")


def test_ship_script_has_exactly_one_commit():
    """A second commit anywhere in the migration re-opens the same hole."""
    src = SHIP.read_text(encoding="utf-8-sig")
    assert src.count("conn.commit()") == 1, \
        "more than one commit in the migration path — it is no longer one transaction"
    # Matches real usage, not the word: the explanatory comment above the call site says
    # "deliberately not autocommit", and an earlier version of this test tripped on it.
    assert "autocommit=True" not in src, \
        "an autocommit connection would defeat the whole guarantee"
