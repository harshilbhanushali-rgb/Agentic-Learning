"""calibration/graduate_sink_topics.py's write path, verified against a mocked
connection/cursor -- no real database, per this plan's Global Constraints (reads against prod
are fine, writes are not during this pass). Asserts the exact SQL and bound parameters
_graduate_one would send.
"""
from unittest.mock import MagicMock, call

from calibration import graduate_sink_topics as gst
from shared import cluster_evidence


def _record(sim=0.726):
    return {
        "nearest_coachable_sim": sim,
        "nearest_coachable": "client_requests_operational_visualization",
        "sink_member_pair_ids": [101, 102, 103],
        "samples": [{"pair_id": 101, "trigger_text": "t", "response_text": "r"}],
    }


def _verdict():
    return {
        "verdict": "new_coachable_topic",
        "proposed_label": "strategic_performance_consulting",
        "proposed_description": "desc",
        "reason": "reason text",
    }


def _mock_conn(distinct_calls=2, total_calls=10, rowcount=3):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    # _support_stats_for_pairs issues COUNT(*) FROM calls then COUNT(DISTINCT call_id) ...
    cur.fetchone.side_effect = [(total_calls,), (distinct_calls,)]
    cur.rowcount = rowcount
    return conn, cur


def _stub_primary_topic_resolution(monkeypatch, key="strategic_performance_consulting"):
    """_graduate_one's write path now also resolves primary_topic_key (fixes the
    orphaning bug) -- stub the resolution out so these SQL-assertion tests don't need a
    real embedder or a real primary_topics population."""
    monkeypatch.setattr(gst, "_resolve_primary_topic_key", lambda conn, row: key)


class TestResolvePrimaryTopicKey:
    def test_close_match_reuses_existing_key(self, monkeypatch):
        conn = MagicMock()
        monkeypatch.setattr(gst.storage, "get_primary_topics", lambda c: [
            {"primary_topic_key": "pt_existing", "label": "L", "description": "D", "keyphrases": []},
        ])
        monkeypatch.setattr(gst.scenario_vectors, "build_primary_topic_vecs",
                             lambda m: (["pt_existing"], [[1.0, 0.0]]))
        monkeypatch.setattr(gst.scenario_vectors, "scenario_vec", lambda row: [1.0, 0.0])
        monkeypatch.setattr(gst.topic_grouping, "match_existing_primary_topic",
                             lambda centroid, keys, vecs, threshold: "pt_existing")
        upsert_mock = MagicMock()
        monkeypatch.setattr(gst.storage, "upsert_primary_topic", upsert_mock)

        key = gst._resolve_primary_topic_key(conn, row={
            "business_description": "d", "keyphrases": [], "scenario_key": "new_s",
            "support_calls": 5, "call_coverage": 0.1,
        })
        assert key == "pt_existing"
        upsert_mock.assert_not_called()

    def test_no_match_creates_singleton_primary_topic(self, monkeypatch):
        conn = MagicMock()
        monkeypatch.setattr(gst.storage, "get_primary_topics", lambda c: [])
        monkeypatch.setattr(gst.scenario_vectors, "build_primary_topic_vecs", lambda m: ([], []))
        monkeypatch.setattr(gst.scenario_vectors, "scenario_vec", lambda row: [1.0, 0.0])
        upsert_mock = MagicMock()
        monkeypatch.setattr(gst.storage, "upsert_primary_topic", upsert_mock)

        row = {"business_description": "d", "keyphrases": ["kp"], "scenario_key": "new_s",
               "support_calls": 5, "call_coverage": 0.1}
        key = gst._resolve_primary_topic_key(conn, row=row)

        assert key == "new_s"
        upsert_mock.assert_called_once()
        written = upsert_mock.call_args.args[1]
        assert written["grouping_method"] == "graduated_singleton"


class TestGraduateOne:
    def test_skips_when_verdict_is_not_new_coachable_topic(self, monkeypatch):
        conn, cur = _mock_conn()
        result = gst._graduate_one(
            "cluster_5", _record(), {"verdict": "genuine_sink"}, config=None, conn=conn,
            dry_run=False,
        )
        assert result is None
        cur.execute.assert_not_called()

    def test_skips_when_reconciliation_gate_fails(self, monkeypatch):
        conn, cur = _mock_conn()
        result = gst._graduate_one(
            "cluster_5", _record(sim=0.90), _verdict(), config=None, conn=conn, dry_run=False,
        )
        assert result is None
        cur.execute.assert_not_called()

    def test_writes_expected_insert_and_reroute_sql(self, monkeypatch):
        monkeypatch.setattr(gst, "_generate_metadata", lambda record, verdict, config: {
            "scenario_key": "strategic_performance_consulting",
            "business_description": "desc",
            "keyphrases": ["kp"],
            "soft_skills": ["skill"],
            "bloom_level": "apply",
        })
        conn, cur = _mock_conn(distinct_calls=2, total_calls=10, rowcount=3)
        monkeypatch.setattr(gst.storage, "upsert_scenario", lambda c, row: 999)
        _stub_primary_topic_resolution(monkeypatch)

        result = gst._graduate_one(
            "cluster_5", _record(), _verdict(), config=None, conn=conn, dry_run=False,
        )

        assert result == "strategic_performance_consulting"
        reroute_call = cur.execute.call_args
        sql, params = reroute_call.args
        assert "UPDATE kb_pairs" in sql
        assert "array_append(scenario_keys" in sql
        assert params == (
            "strategic_performance_consulting", 999, "strategic_performance_consulting",
            [101, 102, 103],
        )
        conn.commit.assert_called()

    def test_raises_when_rerouted_count_does_not_match(self, monkeypatch):
        monkeypatch.setattr(gst, "_generate_metadata", lambda record, verdict, config: {
            "scenario_key": "x", "business_description": "d", "keyphrases": [],
            "soft_skills": [], "bloom_level": "apply",
        })
        conn, cur = _mock_conn(rowcount=2)  # expects 3, mock returns 2
        monkeypatch.setattr(gst.storage, "upsert_scenario", lambda c, row: 999)
        _stub_primary_topic_resolution(monkeypatch)

        import pytest
        with pytest.raises(RuntimeError, match="rerouted 2"):
            gst._graduate_one(
                "cluster_5", _record(), _verdict(), config=None, conn=conn, dry_run=False,
            )

    def test_dry_run_makes_no_writes(self, monkeypatch):
        monkeypatch.setattr(gst, "_generate_metadata", lambda record, verdict, config: {
            "scenario_key": "x", "business_description": "d", "keyphrases": [],
            "soft_skills": [], "bloom_level": "apply",
        })
        monkeypatch.setattr(gst, "_support_stats_for_pairs", lambda conn, pair_ids: (2, 3, 0.2))
        conn, cur = _mock_conn()
        result = gst._graduate_one(
            "cluster_5", _record(), _verdict(), config=None, conn=conn, dry_run=True,
        )
        assert result is None
        cur.execute.assert_not_called()
        conn.commit.assert_not_called()
