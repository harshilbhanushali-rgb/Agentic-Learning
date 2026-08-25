"""Playbook schema/storage/loader tests.

Spec: docs/superpowers/specs/2026-08-19-playbook-schema-design.md

Everything here is DB-free. The gates that are genuinely properties of Postgres (G-P2
round-trip through JSONB, G-P4's partial unique index) are verified by
`ops/load_playbooks.py --apply` against the live database and cannot be faked here — a stub
connection that "enforces" a unique index would be testing the stub, which is the exact
failure mode `test_layer_b_assignment.py` avoids by testing the rule rather than the model.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from shared.storage import (
    _VALID_PLAYBOOK_STATUSES,
    assign_move_ids,
    get_playbook_for_scenario,
    get_playbooks,
    strip_move_ids,
    upsert_playbook,
)

_OPS = Path(__file__).resolve().parent.parent / "ops"


def _load_ops_module(name: str):
    """Import an ops/ script BY EXPLICIT PATH.

    `ops/` is deliberately not a package: `clear_data.py` and `clear_ego_trap_data.py` have no
    __main__ guard, so with no ops/__init__.py there is no `ops.clear_data` for anything to
    import by accident and wipe live data. That protection is worth keeping, so tests reach
    the two safe, guarded modules they need by file path rather than by adding a package.
    """
    spec = importlib.util.spec_from_file_location(f"_ops_{name}", _OPS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


load_playbooks = _load_ops_module("load_playbooks")
ship_union_taxonomy = _load_ops_module("ship_union_taxonomy")


# --- move ids are the array position (G-P5) -------------------------------

def test_move_ids_are_positional():
    moves = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    assert [m["move_id"] for m in assign_move_ids(moves)] == ["M1", "M2", "M3"]


def test_model_supplied_move_id_is_discarded():
    """A model-chosen id is exactly what must never survive -- it lets a re-synthesis
    silently repoint accumulated history at different criteria."""
    moves = [{"name": "a", "move_id": "whatever-the-model-said"}, {"name": "b"}]
    assert [m["move_id"] for m in assign_move_ids(moves)] == ["M1", "M2"]


def test_assign_move_ids_does_not_mutate_the_caller():
    """The loader hashes the artifact object for G-P2 after calling this."""
    moves = [{"name": "a"}, {"name": "b"}]
    assign_move_ids(moves)
    assert all("move_id" not in m for m in moves)


def test_reordering_renumbers_which_is_why_order_is_load_bearing():
    a = assign_move_ids([{"name": "x"}, {"name": "y"}])
    b = assign_move_ids([{"name": "y"}, {"name": "x"}])
    assert a[0]["name"] == "x" and a[0]["move_id"] == "M1"
    assert b[0]["name"] == "y" and b[0]["move_id"] == "M1"


def test_strip_move_ids_is_the_inverse():
    original = [{"name": "a", "criterion": "c"}, {"name": "b", "criterion": "d"}]
    assert strip_move_ids(assign_move_ids(original)) == original


def test_empty_moves_is_not_an_error_here():
    """Move-count floors are the synthesis harness's gate, not storage's."""
    assert assign_move_ids([]) == []


# --- status validation ----------------------------------------------------

class _ExplodingConn:
    """Any DB access at all is a test failure -- validation must precede it."""

    def cursor(self):
        raise AssertionError("validation must reject before touching the database")


def test_upsert_rejects_an_unknown_status_before_touching_the_db():
    bad = {"status": "shipped", "scenario_key": "k", "playbook": {}}
    with pytest.raises(ValueError, match="invalid playbook status"):
        upsert_playbook(_ExplodingConn(), bad)


@pytest.mark.parametrize("status", sorted(_VALID_PLAYBOOK_STATUSES))
def test_valid_statuses_pass_validation(status):
    """They must get past the guard -- proven by reaching the exploding cursor."""
    doc = {"status": status, "scenario_key": "k", "playbook": {"situation_signature": "s"}}
    with pytest.raises(AssertionError, match="must reject before"):
        upsert_playbook(_ExplodingConn(), doc)


def test_read_helpers_reject_an_unknown_status_filter():
    with pytest.raises(ValueError, match="invalid playbook status filter"):
        get_playbook_for_scenario(_ExplodingConn(), "k", status="bogus")
    with pytest.raises(ValueError, match="invalid playbook status filter"):
        get_playbooks(_ExplodingConn(), status="bogus")


def test_get_playbooks_accepts_none_meaning_every_status():
    """None is the inventory path the loader's gates use; it must not be rejected."""
    with pytest.raises(AssertionError, match="must reject before"):
        get_playbooks(_ExplodingConn(), status=None)


def test_get_playbook_for_scenario_defaults_to_live():
    """The default is the guard against serving a placebo twin as production content."""
    import inspect
    sig = inspect.signature(get_playbook_for_scenario)
    assert sig.parameters["status"].default == "live"


# --- the real artifacts (G-P3, G-P5, status mapping) ----------------------

def test_builds_exactly_sixty_five_documents():
    """The literal is deliberate: EXPECTED_TOTAL alone would pass against itself.

    65 = 60 pre-promotion + the 5 pbq gradability remakes added 2026-08-24. The 5 pbv
    originals they supersede are still counted here — superseded rows are retained for
    traceability, not deleted.
    """
    docs = load_playbooks.build_documents()
    assert len(docs) == load_playbooks.EXPECTED_TOTAL == 65


def test_per_artifact_counts_match_the_frozen_expectation():
    """Built documents are POST-exclusion, so they must be checked against EXPECTED_LOADED.

    Checking them against EXPECTED_COUNTS is the "one constant, two meanings" bug that
    broke G-P3 on the first backfill load (findings §11.6): EXPECTED_COUNTS is the RAW
    count in the artifact (26 for pbf_rest), EXPECTED_LOADED is what survives the
    schema_collapsed exclusion (25). This test was the last place still conflating them.
    """
    docs = load_playbooks.build_documents()
    counts = {}
    for d in docs:
        counts[d["source_artifact"]] = counts.get(d["source_artifact"], 0) + 1
    assert counts == load_playbooks.EXPECTED_LOADED
    assert (load_playbooks.EXPECTED_COUNTS["pbf_rest_snapped.json"]
            != load_playbooks.EXPECTED_LOADED["pbf_rest_snapped.json"]), \
        "the two constants have converged — the distinction this test guards is gone"


def test_thirty_three_documents_are_live_across_the_three_real_artifacts():
    """33 of 34 coachable scenarios: 5 pbq remakes + 25 backfill + 3 thin.

    Coverage is UNCHANGED by the 2026-08-24 promotion — the pbq arm replaced the pbv
    originals one-for-one. The placebo twins and the trial documents share this table, so
    the live SET, not just its size, is the thing worth pinning.
    """
    docs = load_playbooks.build_documents()
    live = [d for d in docs if d["status"] == "live"]
    assert len(live) == 33
    assert {d["arm"] for d in live} == {"real"}
    per_artifact = {}
    for d in live:
        per_artifact[d["source_artifact"]] = per_artifact.get(d["source_artifact"], 0) + 1
    assert per_artifact == {
        "pbq_36flash_medium_grad_snapped.json": 5,
        "pbf_rest_snapped.json": 25,
        "pbf_thin_snapped.json": 3,
    }
    assert len({d["scenario_key"] for d in live}) == 33, \
        "two live documents for one scenario — idx_playbooks_one_live would refuse the load"


def test_the_superseded_originals_cover_exactly_the_promoted_scenarios():
    """A promotion must be one-for-one: every demoted scenario gets a replacement.

    Catches the two ways this goes wrong silently — demoting a scenario without replacing it
    (coverage drops, and G-P4's live count would still pass if something else moved), or
    promoting a scenario whose incumbent was never demoted (the load dies on
    idx_playbooks_one_live, but late, after writes have begun).
    """
    docs = load_playbooks.build_documents()
    superseded = {d["scenario_key"] for d in docs if d["status"] == "superseded"}
    promoted = {d["scenario_key"] for d in docs
                if d["source_artifact"] == "pbq_36flash_medium_grad_snapped.json"}
    assert superseded == promoted, (
        f"promotion is not one-for-one: demoted-not-replaced={sorted(superseded - promoted)}, "
        f"replaced-not-demoted={sorted(promoted - superseded)}")
    assert len(superseded) == 5


def test_a_demotion_is_ordered_before_its_replacement():
    """THE ORDERING TRIPWIRE. idx_playbooks_one_live is a partial unique index, so the
    incumbent must be demoted BEFORE the replacement is inserted. Documents are written in
    ARTIFACT_PLAN order, so this is a property of that tuple, and nothing else checks it.
    """
    order = [name for name, _ in load_playbooks.ARTIFACT_PLAN]
    demoting = [i for i, (_n, arms) in enumerate(load_playbooks.ARTIFACT_PLAN)
                if "superseded" in arms.values()]
    assert demoting, "no artifact demotes anything — this test is passing vacuously"
    promoting = order.index("pbq_36flash_medium_grad_snapped.json")
    assert max(demoting) < promoting, (
        "an artifact that demotes an incumbent sits AFTER the artifact that replaces it — "
        "the load will violate idx_playbooks_one_live")


def test_placebo_twins_are_never_live():
    docs = load_playbooks.build_documents()
    placebo = [d for d in docs if d["arm"] == "placebo"]
    assert len(placebo) == 5
    assert all(d["status"] == "placebo" for d in placebo)
    assert all(d["donor_scenario_key"] for d in placebo), "a placebo twin without a donor"


def test_r1_documents_land_as_trial_not_live():
    """r1 is UNRESOLVED and was deliberately not shipped."""
    docs = load_playbooks.build_documents()
    r1 = [d for d in docs if d["arm"] == "r1"]
    assert len(r1) == 11
    assert all(d["status"] == "trial" for d in r1)


def test_at_most_one_live_document_per_scenario():
    """G-P4 as a property of the load plan; the DB index enforces it independently."""
    docs = load_playbooks.build_documents()
    live_keys = [d["scenario_key"] for d in docs if d["status"] == "live"]
    assert len(live_keys) == len(set(live_keys))


def test_every_document_carries_provenance():
    docs = load_playbooks.build_documents()
    for d in docs:
        assert d["identity"], f"{d['scenario_key']}/{d['arm']} has no identity block"
        assert isinstance(d["n_evidence"], int)


def test_move_id_gate_passes_on_the_real_artifacts():
    load_playbooks.check_move_ids(load_playbooks.build_documents())


def test_key_move_counts_respect_the_schema_floor():
    """The trial spec froze 3..6 moves. A document below 3 is the 'too shallow to reach the
    floor' tail the handoff warns no retry budget can rescue -- it must not pass silently."""
    docs = load_playbooks.build_documents()
    counts = [len(d["playbook"]["key_moves"]) for d in docs]
    assert min(counts) >= 3, f"a document fell below the 3-move floor: {counts}"
    assert max(counts) <= 6


def test_round_trip_shape_is_json_stable():
    """G-P2's comparison relies on sort_keys making the artifact order-insensitive."""
    docs = load_playbooks.build_documents()
    for d in docs:
        body = d["playbook"]
        assert json.dumps(body, sort_keys=True) == json.dumps(
            json.loads(json.dumps(body)), sort_keys=True
        )


def test_body_keys_are_exactly_the_frozen_set():
    docs = load_playbooks.build_documents()
    for d in docs:
        assert set(d["playbook"]) == load_playbooks.BODY_KEYS


def test_an_unmapped_arm_is_refused_rather_than_defaulted(monkeypatch, tmp_path):
    """Guessing 'trial' for a new arm could silently promote or bury a document."""
    art = {
        "identity": {"seed": 42},
        "documents": {
            "some_scenario::r2": {
                "scenario": "some_scenario", "arm": "r2", "n_evidence": 10,
                "playbook": {k: [] for k in load_playbooks.BODY_KEYS},
            }
        },
    }
    (tmp_path / "fake.json").write_text(json.dumps(art), encoding="utf-8")
    monkeypatch.setattr(load_playbooks, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(load_playbooks, "ARTIFACT_PLAN", (("fake.json", {"concat": "trial"}),))
    monkeypatch.setattr(load_playbooks, "EXPECTED_COUNTS", {"fake.json": 1})
    with pytest.raises(SystemExit, match="unmapped arm"):
        load_playbooks.build_documents()


def test_a_dropped_document_fails_the_count_gate(monkeypatch, tmp_path):
    art = {"identity": {}, "documents": {}}
    (tmp_path / "fake.json").write_text(json.dumps(art), encoding="utf-8")
    monkeypatch.setattr(load_playbooks, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(load_playbooks, "ARTIFACT_PLAN", (("fake.json", {"concat": "trial"}),))
    monkeypatch.setattr(load_playbooks, "EXPECTED_COUNTS", {"fake.json": 5})
    with pytest.raises(SystemExit, match="G-P3 FAIL"):
        load_playbooks.build_documents()


def test_an_extra_body_key_is_refused(monkeypatch, tmp_path):
    """An unexpected key would be silently dropped by the column mapping."""
    body = {k: [] for k in load_playbooks.BODY_KEYS}
    body["surprise_field"] = "value"
    art = {
        "identity": {},
        "documents": {
            "s::concat": {"scenario": "s", "arm": "concat", "n_evidence": 1, "playbook": body}
        },
    }
    (tmp_path / "fake.json").write_text(json.dumps(art), encoding="utf-8")
    monkeypatch.setattr(load_playbooks, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(load_playbooks, "ARTIFACT_PLAN", (("fake.json", {"concat": "trial"}),))
    monkeypatch.setattr(load_playbooks, "EXPECTED_COUNTS", {"fake.json": 1})
    with pytest.raises(SystemExit, match="body shape mismatch"):
        load_playbooks.build_documents()


def test_ddl_is_extractable_from_schema_sql():
    """The loader creates the table from db/schema.sql's marked block rather than running
    db/init_db.py, which would open its own connection (skipping the hostaddr DNS fix) and
    take ACCESS EXCLUSIVE on five unrelated tables. Extraction keeps ONE definition."""
    ddl = load_playbooks.playbooks_ddl()
    assert "CREATE TABLE IF NOT EXISTS playbooks" in ddl
    assert "idx_playbooks_one_live" in ddl
    assert "WHERE status = 'live'" in ddl
    # It must NOT drag in the rest of the schema.
    assert "CREATE TABLE IF NOT EXISTS scenarios" not in ddl
    assert "ALTER TABLE" not in ddl


def test_ddl_extraction_refuses_when_the_markers_are_gone(monkeypatch, tmp_path):
    fake = tmp_path / "schema.sql"
    fake.write_text("CREATE TABLE IF NOT EXISTS playbooks (x int);", encoding="utf-8")
    monkeypatch.setattr(load_playbooks, "SCHEMA_SQL", fake)
    with pytest.raises(SystemExit, match="markers"):
        load_playbooks.playbooks_ddl()


def test_expected_statuses_matches_the_built_plan():
    """G-P4 asserts this histogram; if the two ever disagree the gate is meaningless."""
    docs = load_playbooks.build_documents()
    actual = {}
    for d in docs:
        actual[d["status"]] = actual.get(d["status"], 0) + 1
    assert actual == load_playbooks.EXPECTED_STATUSES


class _MultiRowConn:
    """Returns two rows -- the real shape of a status='trial' lookup, where every scenario
    has both a `concat` and an `r1` document."""

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            self.sql = sql

        def fetchall(self):
            return [tuple(range(16)), tuple(range(16))]

    def cursor(self):
        return self._Cur()


def test_an_ambiguous_lookup_raises_instead_of_returning_an_arbitrary_row():
    """playbooks is deliberately not unique per scenario, so a bare LIMIT 1 could hand back
    the r1 arm -- UNRESOLVED and never shipped -- while the caller believed it asked for one
    thing. rubrics gets away with LIMIT 1 only because rubrics.scenario_id is UNIQUE."""
    with pytest.raises(ValueError, match="pass arm="):
        get_playbook_for_scenario(_MultiRowConn(), "some_scenario", status="trial")


def test_the_lookup_query_is_deterministically_ordered():
    conn = _MultiRowConn()
    cur = conn._Cur()
    try:
        get_playbook_for_scenario(conn, "k", status="live")
    except ValueError:
        pass
    # Rebuild the SQL the same way the function does, to assert the ORDER BY is present.
    cur.execute("", None)
    import inspect
    src = inspect.getsource(get_playbook_for_scenario)
    assert "ORDER BY arm, source_artifact" in src


# --- the delete chain (G-P7) ----------------------------------------------

def test_playbooks_is_in_the_taxonomy_delete_chain():
    """A NOT NULL FK to scenarios means omitting this makes the NEXT taxonomy replacement
    fail partway through, not corrupt -- but fail."""
    order = ship_union_taxonomy.DELETE_ORDER
    assert "playbooks" in order
    assert order.index("playbooks") < order.index("scenarios")
    assert "playbooks" in ship_union_taxonomy.SNAPSHOT_TABLES


class _CatalogConn:
    """A cursor that reports only `scenarios` as existing."""

    def __init__(self):
        self.answer = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.answer = params[0] if params and params[0].endswith("scenarios") else None

    def fetchone(self):
        return (self.answer,)


def test_missing_tables_are_skipped_rather_than_crashing_the_migration():
    """Adding a table to SNAPSHOT_TABLES must not render ship_union_taxonomy unrunnable on a
    database that predates it -- the row count runs BEFORE the dry-run guard, so an
    UndefinedTable there aborts even a dry run."""
    cur = _CatalogConn()
    got = ship_union_taxonomy.existing(cur, ("playbooks", "scenarios", "nope"))
    assert got == ("scenarios",)


def test_existing_preserves_order():
    cur = _CatalogConn()
    assert ship_union_taxonomy.existing(cur, ("scenarios",)) == ("scenarios",)


# --- the snapped-artifact guard (2026-08-19) -------------------------------
# 22 PRE-SNAP documents were loaded while all seven gates passed, because G-P2 verifies
# fidelity to the artifact it is pointed at and cannot notice that the wrong artifact was
# chosen. Selection is not fidelity. These pin the check that closes that gap.


def test_every_planned_artifact_is_a_snapped_one():
    """The load plan itself must not name a pre-snap file."""
    for filename, _ in load_playbooks.ARTIFACT_PLAN:
        load_playbooks.assert_snapped(filename)          # must not raise
        assert "snapped" in filename, filename


def test_a_known_pre_snap_artifact_is_refused():
    with pytest.raises(SystemExit, match="PRE-SNAP"):
        load_playbooks.assert_snapped("rte_playbooks_concat.json")


def test_the_refusal_names_the_replacement():
    with pytest.raises(SystemExit, match="rte_snapped_concat.json"):
        load_playbooks.assert_snapped("rte_playbooks_concat.json")


def test_pbv_pre_snap_is_refused_too():
    """pbv_playbooks.json was never loaded, but it is the same hazard."""
    with pytest.raises(SystemExit, match="PRE-SNAP"):
        load_playbooks.assert_snapped("pbv_playbooks.json")


def test_an_unknown_artifact_with_a_snapped_sibling_is_refused(monkeypatch, tmp_path):
    """The list of known pre-snap names cannot be relied on to stay complete, so a
    `_snapped_` sibling existing on disk is refused on its own."""
    (tmp_path / "zz_snapped_x.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(load_playbooks, "ARTIFACTS_DIR", tmp_path)
    with pytest.raises(SystemExit, match="snapped form"):
        load_playbooks.assert_snapped("zz_playbooks_x.json")


def test_an_artifact_with_no_snapped_sibling_passes(monkeypatch, tmp_path):
    """A file that genuinely has no snapped form must not be blocked."""
    monkeypatch.setattr(load_playbooks, "ARTIFACTS_DIR", tmp_path)
    load_playbooks.assert_snapped("zz_playbooks_x.json")


def test_the_purge_list_covers_every_pre_snap_name_in_the_repo(monkeypatch):
    """If a `*_playbooks_*.json` has a snapped sibling on disk, it must be in
    SUPERSEDED_BY_SNAP -- otherwise a stale load of it would never be purged."""
    from pathlib import Path
    art = Path(load_playbooks.ARTIFACTS_DIR)
    missing = []
    for p in art.glob("*_playbooks_*.json"):
        sib = p.name.replace("_playbooks_", "_snapped_")
        if (art / sib).exists() and p.name not in load_playbooks.SUPERSEDED_BY_SNAP:
            missing.append(p.name)
    assert not missing, f"pre-snap artifacts absent from SUPERSEDED_BY_SNAP: {missing}"


def test_snapped_documents_carry_a_snap_log():
    """The positive signal that a loaded document really went through the snap.

    A collapsed document is allowed to EXIST in an artifact — `contract_and_legal_review`
    does, and that null result is deliberately kept on disk rather than deleted. The
    invariant is that the loader EXCLUDES it, which the next test asserts. Requiring the
    artifact itself to be collapse-free would make the honest record of a null result look
    like a defect.
    """
    import json
    from pathlib import Path
    art = Path(load_playbooks.ARTIFACTS_DIR)
    for filename, _ in load_playbooks.ARTIFACT_PLAN:
        d = json.loads((art / filename).read_text(encoding="utf-8-sig"))
        for doc_id, doc in d["documents"].items():
            assert "snap_log" in doc, f"{filename}:{doc_id} has no snap_log"


def test_collapsed_documents_are_excluded_from_the_load():
    """The pre-registered exclusion rule, asserted end to end rather than trusted.

    A schema_collapsed document has fewer than MIN_MOVES=3 evidenced moves. Loading one
    would put an unfinished playbook in front of a CSM as if it were finished, so the
    absence of every collapsed scenario_key from the built set is the real gate.
    """
    import json
    from pathlib import Path
    art = Path(load_playbooks.ARTIFACTS_DIR)
    collapsed = set()
    for filename, _ in load_playbooks.ARTIFACT_PLAN:
        d = json.loads((art / filename).read_text(encoding="utf-8-sig"))
        for doc in d["documents"].values():
            if doc.get("snap_log", {}).get("schema_collapsed"):
                collapsed.add((filename, doc["scenario"], doc["arm"]))

    assert collapsed, \
        "no collapsed document anywhere — this test would pass vacuously; re-check the fixture"

    built = {(d["source_artifact"], d["scenario_key"], d["arm"])
             for d in load_playbooks.build_documents()}
    leaked = sorted(collapsed & built)
    assert not leaked, f"schema_collapsed documents reached the load plan: {leaked}"
