from config import Config
from ego_trap import milestone_scoring


def _config():
    return Config(
        gemma_api_key="key",
        database_url="",
        joveo_speakers_lower=frozenset(),
        naren_name_lower="",
        pinecone_api_key="",
        pinecone_index_name="",
    )


def test_score_milestones_full_hit_has_no_evidence(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value={"verdict": "full_hit", "confidence": "high", "reason": "Covered fully.", "quote": "", "gap_to_ideal": ""},
    )
    rubric = {"milestones": [{"order": 1, "description": "Acknowledge urgency", "detection_hint": "hint"}]}

    results = milestone_scoring.score_milestones(rubric, "We'll fix this today.", "benchmark text", _config())

    assert results == [{
        "milestone_id": "M1",
        "milestone_description": "Acknowledge urgency",
        "verdict": "full_hit",
        "confidence": "high",
        "reason": "Covered fully.",
        "quote": "",
        "gap_to_ideal": "",
    }]


def test_score_milestones_partial_hit_carries_evidence(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value={
            "verdict": "partial_hit",
            "confidence": "medium",
            "reason": "Acknowledged but no timeline given.",
            "quote": "We'll look into it.",
            "gap_to_ideal": "Should have committed to a specific resolution date.",
        },
    )
    rubric = {"milestones": [{"order": 1, "description": "Commit to a resolution date", "detection_hint": "hint"}]}

    results = milestone_scoring.score_milestones(rubric, "We'll look into it.", "benchmark text", _config())

    assert results[0]["verdict"] == "partial_hit"
    assert results[0]["quote"] == "We'll look into it."
    assert results[0]["gap_to_ideal"] == "Should have committed to a specific resolution date."


def test_score_milestones_unrecognized_verdict_defaults_to_miss(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value={"confidence": "low", "reason": "unparseable"},
    )
    rubric = {"milestones": [{"order": 1, "description": "d", "detection_hint": "h"}]}

    results = milestone_scoring.score_milestones(rubric, "text", "benchmark", _config())

    assert results[0]["verdict"] == "miss"
    assert results[0]["quote"] == ""
    assert results[0]["gap_to_ideal"] == ""


def test_score_milestones_batch_matches_by_id_and_defaults_missing_to_miss(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[
            {"id": "S0_M1", "verdict": "full_hit", "confidence": "high", "reason": "r0", "quote": "", "gap_to_ideal": ""},
            {"id": "S1_M1", "verdict": "miss", "confidence": "high", "reason": "r1", "quote": "", "gap_to_ideal": "Should have addressed pricing."},
        ],
    )
    items = [
        {"rubric": {"milestones": [{"order": 1, "description": "d0", "detection_hint": "h0"}]}, "csm_response_text": "resp0", "benchmark_response": "bench0"},
        {"rubric": {"milestones": [{"order": 1, "description": "d1", "detection_hint": "h1"}]}, "csm_response_text": "resp1", "benchmark_response": "bench1"},
        {"rubric": {"milestones": [{"order": 1, "description": "d2", "detection_hint": "h2"}]}, "csm_response_text": "resp2", "benchmark_response": "bench2"},
    ]

    results_by_item = milestone_scoring.score_milestones_batch(items, _config())

    assert results_by_item[0][0]["verdict"] == "full_hit"
    assert results_by_item[1][0]["verdict"] == "miss"
    assert results_by_item[1][0]["gap_to_ideal"] == "Should have addressed pricing."
    # item 2's id (S2_M1) was never returned by Gemma -> defaults to miss, not a crash
    assert results_by_item[2][0]["verdict"] == "miss"
