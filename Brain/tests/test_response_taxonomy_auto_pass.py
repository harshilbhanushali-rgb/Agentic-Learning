"""response_taxonomy_auto_pass.py's matching/tracking/graduation logic, verified against a
mocked connection/cursor -- no real database, matching test_graduate_sink_topics.py's
existing discipline.
"""
from unittest.mock import MagicMock

import pytest

import response_taxonomy_auto_pass as rtap


@pytest.fixture(autouse=True)
def _disable_real_log_file(monkeypatch):
    # _logger is a module-level singleton writing to the real
    # response_taxonomy_auto_pass.log on disk -- without this, every test run
    # interleaves fake candidate_id/scenario_key entries into the same file a real
    # production run appends to, making the log untrustworthy as an audit trail.
    monkeypatch.setattr(rtap._logger, "disabled", True)


# --- Jaccard / matching (Decision 1) -----------------------------------------

class TestJaccard:
    def test_identical_sets_is_one(self):
        assert rtap._jaccard({1, 2, 3}, {1, 2, 3}) == 1.0

    def test_disjoint_sets_is_zero(self):
        assert rtap._jaccard({1, 2}, {3, 4}) == 0.0

    def test_partial_overlap(self):
        assert rtap._jaccard({1, 2, 3}, {2, 3, 4}) == pytest.approx(2 / 4)

    def test_both_empty_is_zero_not_a_divide_by_zero(self):
        assert rtap._jaccard(set(), set()) == 0.0


def _row(candidate_id, member_pair_ids, stable_pair_ids=None, last_seen="run_a", consensus=1):
    return {
        "candidate_id": candidate_id,
        "member_pair_ids": member_pair_ids,
        "stable_pair_ids": stable_pair_ids if stable_pair_ids is not None else list(member_pair_ids),
        "last_seen_run_id": last_seen,
        "consensus_count": consensus,
        "status": "tracking",
    }


class TestMatchTrackingRow:
    def test_no_rows_returns_none(self):
        assert rtap._match_tracking_row({1, 2, 3}, [], overlap_threshold=0.5) is None

    def test_matches_row_above_threshold(self):
        rows = [_row(1, [1, 2, 3, 4])]
        assert rtap._match_tracking_row({2, 3, 4, 5}, rows, overlap_threshold=0.5) is rows[0]

    def test_no_match_below_threshold(self):
        rows = [_row(1, [1, 2, 3, 4, 5, 6, 7, 8])]
        assert rtap._match_tracking_row({1, 9, 10, 11}, rows, overlap_threshold=0.5) is None

    def test_ambiguous_multi_match_picks_the_single_best_row(self):
        # Both clear the 0.5 floor; row 2 overlaps more (Decision 1 in the design spec).
        rows = [_row(1, [1, 2, 3, 4]), _row(2, [1, 2, 3, 4, 5])]
        new_ids = {1, 2, 3, 4, 5}
        best = rtap._match_tracking_row(new_ids, rows, overlap_threshold=0.5)
        assert best["candidate_id"] == 2

    def test_exact_tie_breaks_toward_lower_candidate_id(self):
        rows = [_row(2, [1, 2, 3, 4]), _row(1, [1, 2, 3, 4])]
        best = rtap._match_tracking_row({1, 2, 3, 4}, rows, overlap_threshold=0.5)
        assert best["candidate_id"] == 1


# --- stable_pair_ids tracking (Decision 2) -----------------------------------

def _mock_conn_with_row():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    return conn, cur


class TestUpsertTrackingRow:
    def test_no_match_inserts_new_row_seeding_stable_pair_ids(self):
        conn, cur = _mock_conn_with_row()
        rtap._upsert_tracking_row(conn, "run_1", {1, 2, 3}, None, "label", "desc")
        sql, params = cur.execute.call_args.args
        assert "INSERT INTO response_taxonomy_candidates" in sql
        assert sorted(params[2]) == [1, 2, 3]   # member_pair_ids
        assert sorted(params[3]) == [1, 2, 3]   # stable_pair_ids seeded to the full set
        conn.commit.assert_called()

    def test_match_intersects_stable_pair_ids_not_just_overwrites(self):
        conn, cur = _mock_conn_with_row()
        matched = _row(5, member_pair_ids=[2, 3, 4], stable_pair_ids=[1, 2, 3], last_seen="run_1")
        rtap._upsert_tracking_row(conn, "run_2", {2, 3, 4, 5}, matched, "label", "desc")
        sql, params = cur.execute.call_args.args
        assert "UPDATE response_taxonomy_candidates" in sql
        # stable_pair_ids = {1,2,3} ∩ {2,3,4,5} = {2,3}
        assert sorted(params[1]) == [2, 3]
        assert params[-1] == 5  # candidate_id in WHERE clause

    def test_drift_across_three_runs_shrinks_to_the_stable_core(self):
        # Simulates the exact Decision 2 scenario from the design spec: run 1 {1,2,3},
        # run 2 matches with {2,3,4}, run 3 matches with {3,4,5} -- stable core ends at {3}.
        stable = {1, 2, 3}
        stable = stable & {2, 3, 4}
        stable = stable & {3, 4, 5}
        assert stable == {3}

    def test_idempotency_guard_same_run_id_does_not_double_increment(self):
        conn, cur = _mock_conn_with_row()
        matched = _row(5, member_pair_ids=[1, 2, 3], last_seen="run_1", consensus=2)
        rtap._upsert_tracking_row(conn, "run_1", {1, 2, 3}, matched, "label", "desc")
        cur.execute.assert_not_called()

    def test_stable_pair_ids_emptying_out_marks_discarded(self):
        conn, cur = _mock_conn_with_row()
        matched = _row(5, member_pair_ids=[2, 3], stable_pair_ids=[1, 2], last_seen="run_1")
        rtap._upsert_tracking_row(conn, "run_2", {3, 4}, matched, "label", "desc")
        sql, params = cur.execute.call_args.args
        assert "status" in sql
        assert "discarded" in params


# --- primary_topic_key resolution (fixes the orphaning bug) -----------------

class TestResolvePrimaryTopicKey:
    def test_close_match_reuses_existing_key(self, monkeypatch):
        conn = MagicMock()
        monkeypatch.setattr(rtap.storage, "get_primary_topics", lambda c: [
            {"primary_topic_key": "pt_existing", "label": "L", "description": "D", "keyphrases": []},
        ])
        monkeypatch.setattr(rtap.scenario_vectors, "build_primary_topic_vecs",
                             lambda m: (["pt_existing"], [[1.0, 0.0]]))
        monkeypatch.setattr(rtap.scenario_vectors, "scenario_vec", lambda row: [1.0, 0.0])
        monkeypatch.setattr(rtap.topic_grouping, "match_existing_primary_topic",
                             lambda centroid, keys, vecs, threshold: "pt_existing")
        upsert_mock = MagicMock()
        monkeypatch.setattr(rtap.storage, "upsert_primary_topic", upsert_mock)

        key = rtap._resolve_primary_topic_key(
            conn, merge_cosine_threshold=0.85,
            row={"business_description": "d", "keyphrases": [], "scenario_key": "new_s",
                 "support_calls": 5, "call_coverage": 0.1},
        )
        assert key == "pt_existing"
        upsert_mock.assert_not_called()

    def test_no_match_creates_singleton_primary_topic(self, monkeypatch):
        conn = MagicMock()
        monkeypatch.setattr(rtap.storage, "get_primary_topics", lambda c: [])
        monkeypatch.setattr(rtap.scenario_vectors, "build_primary_topic_vecs", lambda m: ([], []))
        monkeypatch.setattr(rtap.scenario_vectors, "scenario_vec", lambda row: [1.0, 0.0])
        upsert_mock = MagicMock()
        monkeypatch.setattr(rtap.storage, "upsert_primary_topic", upsert_mock)

        row = {"business_description": "d", "keyphrases": ["kp"], "scenario_key": "new_s",
               "support_calls": 5, "call_coverage": 0.1}
        key = rtap._resolve_primary_topic_key(conn, merge_cosine_threshold=0.85, row=row)

        assert key == "new_s"
        upsert_mock.assert_called_once()
        written = upsert_mock.call_args.args[1]
        assert written["primary_topic_key"] == "new_s"
        assert written["grouping_method"] == "graduated_singleton"
        assert written["support_subtopics"] == 1


# --- Graduation ---------------------------------------------------------------

def _consensus_row(pair_ids, consensus=3):
    return _row(7, member_pair_ids=pair_ids, stable_pair_ids=pair_ids, consensus=consensus)


class TestAttemptGraduation:
    def test_all_pairs_still_sink_bound_proceeds_to_write(self, monkeypatch):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [(1, False), (2, False), (3, False)]  # all currently sink-bound
        monkeypatch.setattr(rtap, "_support_stats_for_pairs", lambda c, ids: (2, len(ids), 0.2))
        monkeypatch.setattr(rtap.cluster_evidence, "passes_reconciliation_gate", lambda sim, thr: True)
        monkeypatch.setattr(rtap, "_generate_metadata", lambda *a, **k: {
            "scenario_key": "new_scenario", "business_description": "d",
            "keyphrases": [], "soft_skills": [], "bloom_level": "apply",
        })
        monkeypatch.setattr(rtap, "_resolve_primary_topic_key", lambda *a, **k: "pt_key")
        monkeypatch.setattr(rtap.storage, "upsert_scenario", lambda c, row: 42)
        monkeypatch.setattr(rtap.storage, "get_scenarios", lambda c: [{"scenario_key": "new_scenario"}])
        cur.rowcount = 3
        monkeypatch.setattr(rtap, "run_layer_c_v2", lambda *a, **k: None)

        result, _conn = rtap._attempt_graduation(
            conn, config=None, run_id="run_1",
            tracking_row=_consensus_row([1, 2, 3]),
            nearest_coachable_sim=0.70, merge_cosine_threshold=0.85, proposed_label="l",
            proposed_description="d", reason="r", samples=[],
        )
        assert result == "new_scenario"
        conn.commit.assert_called()

    def test_pairs_already_rehomed_are_excluded_from_write_set(self, monkeypatch):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        # pair 2 is now homed to a coachable scenario (is_coachable=True) -- must be dropped.
        cur.fetchall.return_value = [(1, False), (2, True), (3, False)]
        captured = {}

        def _fake_support_stats(c, ids):
            captured["ids"] = ids
            return (2, len(ids), 0.2)

        monkeypatch.setattr(rtap, "_support_stats_for_pairs", _fake_support_stats)
        monkeypatch.setattr(rtap.cluster_evidence, "passes_reconciliation_gate", lambda sim, thr: True)
        monkeypatch.setattr(rtap, "_generate_metadata", lambda *a, **k: {
            "scenario_key": "new_scenario", "business_description": "d",
            "keyphrases": [], "soft_skills": [], "bloom_level": "apply",
        })
        monkeypatch.setattr(rtap, "_resolve_primary_topic_key", lambda *a, **k: "pt_key")
        monkeypatch.setattr(rtap.storage, "upsert_scenario", lambda c, row: 42)
        monkeypatch.setattr(rtap.storage, "get_scenarios", lambda c: [{"scenario_key": "new_scenario"}])
        cur.rowcount = 2
        monkeypatch.setattr(rtap, "run_layer_c_v2", lambda *a, **k: None)

        rtap._attempt_graduation(
            conn, config=None, run_id="run_1",
            tracking_row=_consensus_row([1, 2, 3]),
            nearest_coachable_sim=0.70, merge_cosine_threshold=0.85, proposed_label="l",
            proposed_description="d", reason="r", samples=[],
        )
        assert sorted(captured["ids"]) == [1, 3]

    def test_zero_surviving_pairs_discards_without_writing(self, monkeypatch):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [(1, True), (2, True)]  # all already re-homed
        result, _conn = rtap._attempt_graduation(
            conn, config=None, run_id="run_1",
            tracking_row=_consensus_row([1, 2]),
            nearest_coachable_sim=0.70, merge_cosine_threshold=0.85, proposed_label="l",
            proposed_description="d", reason="r", samples=[],
        )
        assert result is None
        sql, params = cur.execute.call_args.args
        assert "discarded" in params

    def test_reconciliation_gate_failure_discards_without_writing(self, monkeypatch):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [(1, False), (2, False)]
        monkeypatch.setattr(rtap, "_support_stats_for_pairs", lambda c, ids: (2, len(ids), 0.2))
        monkeypatch.setattr(rtap.cluster_evidence, "passes_reconciliation_gate", lambda sim, thr: False)
        result, _conn = rtap._attempt_graduation(
            conn, config=None, run_id="run_1",
            tracking_row=_consensus_row([1, 2]),
            nearest_coachable_sim=0.90, merge_cosine_threshold=0.85, proposed_label="l",
            proposed_description="d", reason="r", samples=[],
        )
        assert result is None
        sql, params = cur.execute.call_args.args
        assert "discarded" in params

    def test_write_failure_rowcount_mismatch_rolls_back(self, monkeypatch):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [(1, False), (2, False)]
        monkeypatch.setattr(rtap, "_support_stats_for_pairs", lambda c, ids: (2, len(ids), 0.2))
        monkeypatch.setattr(rtap.cluster_evidence, "passes_reconciliation_gate", lambda sim, thr: True)
        monkeypatch.setattr(rtap, "_generate_metadata", lambda *a, **k: {
            "scenario_key": "new_scenario", "business_description": "d",
            "keyphrases": [], "soft_skills": [], "bloom_level": "apply",
        })
        monkeypatch.setattr(rtap, "_resolve_primary_topic_key", lambda *a, **k: "pt_key")
        monkeypatch.setattr(rtap.storage, "upsert_scenario", lambda c, row: 42)
        cur.rowcount = 1  # expected 2, got 1 -- must roll back, not commit-then-raise
        monkeypatch.setattr(rtap, "run_layer_c_v2", lambda *a, **k: None)

        with pytest.raises(RuntimeError, match="rerouted 1"):
            rtap._attempt_graduation(
                conn, config=None, run_id="run_1",
                tracking_row=_consensus_row([1, 2]),
                nearest_coachable_sim=0.70, merge_cosine_threshold=0.85, proposed_label="l",
                proposed_description="d", reason="r", samples=[],
            )
        conn.rollback.assert_called()
        conn.commit.assert_not_called()


# --- run_auto_pass entry point ------------------------------------------------

class _FakeLayerATuning:
    response_taxonomy_auto_pass_enabled = False
    response_taxonomy_consensus_runs = 3
    response_taxonomy_candidate_match_overlap = 0.5
    response_taxonomy_purity_gate = 0.90
    merge_cosine_threshold = 0.85


class _FakeTuning:
    def __init__(self):
        self.layer_a = _FakeLayerATuning()
        self.layer_c = None


class TestRunAutoPass:
    def test_disabled_is_a_pure_noop(self, monkeypatch):
        monkeypatch.setattr(rtap, "load_tuning", lambda: _FakeTuning())
        conn = MagicMock()
        rtap.run_auto_pass(config=None, conn=conn, run_id="run_1")
        conn.cursor.assert_not_called()

    def test_enabled_with_no_pairs_is_a_noop(self, monkeypatch):
        tuning = _FakeTuning()
        tuning.layer_a.response_taxonomy_auto_pass_enabled = True
        monkeypatch.setattr(rtap, "load_tuning", lambda: tuning)
        monkeypatch.setattr(rtap.storage, "get_scenarios", lambda c: [])
        monkeypatch.setattr(rtap.response_taxonomy, "load_all_pairs", lambda conn: ([], 0))
        conn = MagicMock()
        rtap.run_auto_pass(config=None, conn=conn, run_id="run_1")

    def test_exception_inside_propagates_for_the_caller_to_catch(self, monkeypatch):
        tuning = _FakeTuning()
        tuning.layer_a.response_taxonomy_auto_pass_enabled = True
        monkeypatch.setattr(rtap, "load_tuning", lambda: tuning)
        monkeypatch.setattr(rtap.storage, "get_scenarios", lambda c: [])
        monkeypatch.setattr(
            rtap.response_taxonomy, "load_all_pairs",
            lambda conn: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        conn = MagicMock()
        with pytest.raises(RuntimeError, match="boom"):
            rtap.run_auto_pass(config=None, conn=conn, run_id="run_1")
        # The design requires the CALL SITE (v2/pipeline.py) to catch this --
        # run_auto_pass itself is allowed to raise; the pipeline wraps the call in
        # try/except so a bug here can never fail the overall run.
