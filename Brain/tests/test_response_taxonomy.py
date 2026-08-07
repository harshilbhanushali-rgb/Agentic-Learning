"""build_records is response_taxonomy.py's one purely-testable piece -- everything else in
the module touches the DB, Gemma, or the real embedding model. Hand-built vecs/labels/
scenario_map, no DB, no Gemma -- embed_document is patched (same technique
test_layer_b_assignment.py uses) so build_records' internal scenario-vector lookup
(via shared.scenario_vectors.build_scenario_vecs) never touches the real embedding model.
"""
import numpy as np
import pytest

from preprocessing import embedder
from shared import response_taxonomy as rt


@pytest.fixture(autouse=True)
def _stub_embedder(monkeypatch):
    # Scenario-side vectors don't need to be meaningful here -- every test below has at
    # most one candidate on each coachable/sink side, so which vector comes back never
    # changes which key is nearest.
    monkeypatch.setattr(embedder, "embed_document", lambda texts: [[1.0, 0.0] for _ in texts])


def _pair(pair_id, scenario_key, call_filename="call1.txt"):
    return {
        "pair_id": pair_id, "trigger_text": "t", "response_text": "r",
        "scenario_key": scenario_key, "call_filename": call_filename,
    }


def _scenario(key, coachable, description="desc"):
    return {"scenario_key": key, "business_description": description, "keyphrases": [],
            "is_coachable": coachable}


class TestBuildRecords:
    def test_one_cluster_one_record(self):
        pairs = [_pair(1, "sink_a"), _pair(2, "sink_a")]
        vecs = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
        labels = [0, 0]
        scenario_map = {"sink_a": _scenario("sink_a", False),
                         "coachable_a": _scenario("coachable_a", True)}
        records = rt.build_records(pairs, vecs, labels, scenario_map, total_calls=10,
                                    purity_gate=0.90, seed=0)
        assert len(records) == 1
        assert records[0]["member_pair_ids"] == [1, 2]
        assert records[0]["nearest_coachable"] == "coachable_a"

    def test_noise_label_minus_one_is_excluded(self):
        pairs = [_pair(1, "sink_a"), _pair(2, "sink_a")]
        vecs = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
        labels = [-1, 0]
        scenario_map = {"sink_a": _scenario("sink_a", False)}
        records = rt.build_records(pairs, vecs, labels, scenario_map, total_calls=10,
                                    purity_gate=0.90, seed=0)
        assert len(records) == 1
        assert records[0]["member_pair_ids"] == [2]

    def test_purity_gate_skips_when_one_coachable_scenario_dominates(self):
        pairs = [_pair(i, "coachable_a") for i in range(9)] + [_pair(9, "coachable_b")]
        vecs = np.ones((10, 2), dtype=np.float32)
        labels = [0] * 10
        scenario_map = {"coachable_a": _scenario("coachable_a", True),
                         "coachable_b": _scenario("coachable_b", True)}
        records = rt.build_records(pairs, vecs, labels, scenario_map, total_calls=10,
                                    purity_gate=0.90, seed=0)
        assert records[0]["purity_gated"] is True

    def test_distinct_calls_counts_unique_call_filenames(self):
        pairs = [_pair(1, "sink_a", "call1.txt"), _pair(2, "sink_a", "call1.txt"),
                  _pair(3, "sink_a", "call2.txt")]
        vecs = np.ones((3, 2), dtype=np.float32)
        labels = [0, 0, 0]
        scenario_map = {"sink_a": _scenario("sink_a", False)}
        records = rt.build_records(pairs, vecs, labels, scenario_map, total_calls=10,
                                    purity_gate=0.90, seed=0)
        assert records[0]["distinct_calls"] == 2

    def test_no_coachable_scenarios_does_not_crash(self):
        pairs = [_pair(1, "sink_a"), _pair(2, "sink_a")]
        vecs = np.ones((2, 2), dtype=np.float32)
        labels = [0, 0]
        scenario_map = {"sink_a": _scenario("sink_a", False)}
        records = rt.build_records(pairs, vecs, labels, scenario_map, total_calls=10,
                                    purity_gate=0.90, seed=0)
        assert records[0]["nearest_coachable"] is None

    def test_no_sink_scenarios_does_not_crash(self):
        pairs = [_pair(1, "coachable_a"), _pair(2, "coachable_a")]
        vecs = np.ones((2, 2), dtype=np.float32)
        labels = [0, 0]
        scenario_map = {"coachable_a": _scenario("coachable_a", True)}
        records = rt.build_records(pairs, vecs, labels, scenario_map, total_calls=10,
                                    purity_gate=0.90, seed=0)
        assert records[0]["nearest_sink"] is None
