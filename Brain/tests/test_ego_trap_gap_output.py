from ego_trap import gap_output


def test_compute_severity_buckets():
    assert gap_output.compute_severity(0.65) == "critical"
    assert gap_output.compute_severity(0.40) == "high"
    assert gap_output.compute_severity(0.20) == "moderate"
    assert gap_output.compute_severity(0.05) == "low"


def test_compute_severity_boundaries():
    assert gap_output.compute_severity(0.60) == "critical"
    assert gap_output.compute_severity(0.35) == "high"
    assert gap_output.compute_severity(0.15) == "moderate"


def test_build_gap_record_separates_full_hit_partial_hit_and_miss():
    signal = {"turn_index": 4, "client_utterance": "..."}
    milestone_results = [
        {"milestone_id": "M1", "milestone_description": "d1", "verdict": "full_hit", "confidence": "high", "reason": "r1", "quote": "", "gap_to_ideal": ""},
        {"milestone_id": "M2", "milestone_description": "d2", "verdict": "partial_hit", "confidence": "medium", "reason": "r2", "quote": "q2", "gap_to_ideal": "g2"},
        {"milestone_id": "M3", "milestone_description": "d3", "verdict": "miss", "confidence": "high", "reason": "r3", "quote": "q3", "gap_to_ideal": "g3"},
    ]
    soft_skill_results = [
        {"skill": "Confidence Under Pushback", "rating": "failing", "confidence": "high", "reason": "r4"},
        {"skill": "Empathy", "rating": "excellent", "confidence": "high", "reason": "r5"},
    ]

    record = gap_output.build_gap_record(
        "call1", "CSM_X", "scenario_a", 7, signal, milestone_results, soft_skill_results
    )

    assert record["milestones_hit"] == ["M1"]
    assert record["milestones_partial_hit"] == ["M2"]
    assert record["milestones_missed"] == ["M3"]
    assert len(record["gaps"]) == 3

    partial_gap = record["gaps"][0]
    assert partial_gap["gap_type"] == "Milestone_Omission"
    assert partial_gap["verdict"] == "partial_hit"
    assert partial_gap["quote"] == "q2"
    assert partial_gap["gap_to_ideal"] == "g2"

    miss_gap = record["gaps"][1]
    assert miss_gap["verdict"] == "miss"
    assert miss_gap["quote"] == "q3"

    assert record["gaps"][2]["gap_type"] == "Soft_Skill_Failure"
    assert record["gaps"][2]["skill"] == "Confidence Under Pushback"

