"""Tests for ego_trap/gap_output.py -- gap records, severity, and the gap profile."""
import pytest

from ego_trap import gap_output
from shared.tuning import LayerDTuning, load_tuning


def _tuning(**overrides):
    base = dict(
        signal_detection_mode="gemma",
        scoring_unit="moment",
        scenarios_per_request=3,
        similarity_relative_margin=0.95,
        max_scenarios_per_signal=1,
        gemma_scenario_shortlist_k=0,
        turn_match_mode="normalized",
        turn_match_min_ratio=0.85,
        gap_events_enabled=True,
        skip_uncoachable_milestones=True,
        require_validated_milestones=False,
        score_soft_skills=True,
        gap_severity_critical_miss_rate=0.60,
        gap_severity_high_miss_rate=0.35,
        gap_severity_moderate_miss_rate=0.15,
    )
    base.update(overrides)
    return LayerDTuning(**base)


def _row(milestone_id="M1", attempts=1, hits=0, partial=0, key="scenario_a",
         rubric_id=7, version="v2"):
    return {
        "scenario_key": key, "rubric_id": rubric_id, "milestone_id": milestone_id,
        "attempts": attempts, "hits": hits, "partial_hits": partial,
        "last_attempted": None, "pipeline_version": version,
    }


# --- miss rate --------------------------------------------------------------

def test_miss_rate_is_the_exact_complement_of_the_weighted_score():
    """db/schema.sql documents the weighted score as (hits + 0.5*partial)/attempts.
    Defining miss_rate as its complement is what stops severity and a reported score
    from ever disagreeing."""
    for attempts, hits, partial in [(4, 1, 2), (10, 3, 1), (2, 0, 0), (3, 3, 0)]:
        weighted = (hits + 0.5 * partial) / attempts
        assert gap_output.milestone_miss_rate(attempts, hits, partial) == pytest.approx(
            1 - weighted
        )


def test_miss_rate_of_zero_attempts_is_zero_not_one():
    """A milestone nobody attempted has no gap. Calling it critical would be a lie
    about a CSM who was never tested."""
    assert gap_output.milestone_miss_rate(0, 0, 0) == 0.0
    assert gap_output.compute_severity(
        gap_output.milestone_miss_rate(0, 0, 0), _tuning()
    ) == "low"


def test_a_partial_hit_counts_half():
    # One attempt, scored partial -> half credit -> half a miss.
    assert gap_output.milestone_miss_rate(1, 0, 1) == pytest.approx(0.5)
    # Two attempts, one partial and one outright miss -> 0.25 credit, 0.75 missed.
    assert gap_output.milestone_miss_rate(2, 0, 1) == pytest.approx(0.75)


# --- severity ---------------------------------------------------------------

def test_severity_buckets():
    t = _tuning()
    assert gap_output.compute_severity(0.65, t) == "critical"
    assert gap_output.compute_severity(0.40, t) == "high"
    assert gap_output.compute_severity(0.20, t) == "moderate"
    assert gap_output.compute_severity(0.05, t) == "low"


def test_severity_boundaries_are_inclusive():
    t = _tuning()
    assert gap_output.compute_severity(0.60, t) == "critical"
    assert gap_output.compute_severity(0.35, t) == "high"
    assert gap_output.compute_severity(0.15, t) == "moderate"


def test_severity_reads_the_shipped_thresholds():
    """Guards the wiring: severity must come from tuning.yaml, not from a module
    constant that a tuning edit would silently fail to change."""
    t = load_tuning().layer_d
    assert gap_output.compute_severity(t.gap_severity_critical_miss_rate, t) == "critical"
    assert gap_output.compute_severity(t.gap_severity_moderate_miss_rate, t) == "moderate"
    assert gap_output.compute_severity(0.0, t) == "low"


def test_severity_follows_a_retuned_threshold():
    assert gap_output.compute_severity(
        0.40, _tuning(gap_severity_critical_miss_rate=0.30)
    ) == "critical"


# --- build_gap_record -------------------------------------------------------

def _milestone_result(mid, verdict, evidence=None, **kw):
    base = {
        "milestone_id": mid, "milestone_description": f"d{mid}", "verdict": verdict,
        "confidence": "high", "reason": f"r{mid}", "quote": "", "gap_to_ideal": "",
        "milestone_order": None, "evidence": evidence or {},
    }
    base.update(kw)
    return base


def test_build_gap_record_separates_full_hit_partial_hit_and_miss():
    signal = {"turn_index": 4, "client_utterance": "..."}
    milestone_results = [
        _milestone_result("M1", "full_hit"),
        _milestone_result("M2", "partial_hit", quote="q2", gap_to_ideal="g2",
                          confidence="medium"),
        _milestone_result("M3", "miss", quote="q3", gap_to_ideal="g3"),
    ]
    soft_skill_results = [
        {"skill": "Confidence Under Pushback", "rating": "failing",
         "confidence": "high", "reason": "r4"},
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

    assert record["gaps"][1]["verdict"] == "miss"
    assert record["gaps"][1]["quote"] == "q3"

    assert record["gaps"][2]["gap_type"] == "Soft_Skill_Failure"
    assert record["gaps"][2]["skill"] == "Confidence Under Pushback"


def test_gap_carries_a_copy_of_the_evidence_it_was_scored_against():
    """upsert_rubric replaces rubrics.milestones in place under the same rubric_id, so
    the next Layer C run destroys the evidence a past gap_event was graded against. The
    copy in gaps is the only durable record."""
    evidence = {"support_calls": 12, "support_clauses": 40, "relevance_mean": 0.66,
                "sequencing_type": "fixed", "position_variance": 0.1,
                "source_v": "v2_hdbscan"}
    record = gap_output.build_gap_record(
        "c", "CSM_X", "s", 7, {"turn_index": 1},
        [_milestone_result("M1", "miss", evidence)], [], pipeline_version="v2",
    )
    assert record["gaps"][0]["evidence"] == evidence
    assert record["gaps"][0]["rubric_pipeline_version"] == "v2"


def test_gap_carries_the_model_that_scored_it():
    """The model chain downgrades silently on a rate limit, so a verdict whose scorer is
    unknown cannot be compared against one from another run. This was set on the result
    dict but never persisted -- the field came back empty on the first real run."""
    r = _milestone_result("M1", "miss")
    r["scored_by"] = "gemini-3.1-flash-lite"
    record = gap_output.build_gap_record("c", "X", "s", 7, {"turn_index": 1}, [r], [])
    assert record["gaps"][0]["scored_by"] == "gemini-3.1-flash-lite"


def test_gap_scored_by_is_none_when_absent():
    record = gap_output.build_gap_record(
        "c", "X", "s", 7, {"turn_index": 1}, [_milestone_result("M1", "miss")], []
    )
    assert record["gaps"][0]["scored_by"] is None


def test_v1_evidence_is_recorded_as_none_not_dropped():
    record = gap_output.build_gap_record(
        "c", "CSM_X", "s", 7, {"turn_index": 1},
        [_milestone_result("M1", "miss", {"support_calls": None, "source_v": "v1_gemma"})],
        [], pipeline_version="v1",
    )
    assert record["gaps"][0]["evidence"]["support_calls"] is None
    assert record["gaps"][0]["rubric_pipeline_version"] == "v1"


def test_full_hits_produce_no_gap_entry():
    """gaps holds only non-full_hit entries. Adding hits would break the column's
    documented semantics and any reader counting len(gaps)."""
    record = gap_output.build_gap_record(
        "c", "CSM_X", "s", 7, {"turn_index": 1},
        [_milestone_result("M1", "full_hit", {"support_calls": 9})], [],
    )
    assert record["gaps"] == []
    assert record["milestones_hit"] == ["M1"]


def test_only_failing_soft_skills_become_gaps():
    record = gap_output.build_gap_record(
        "c", "CSM_X", "s", 7, {"turn_index": 1}, [],
        [{"skill": "a", "rating": "adequate", "reason": "r"},
         {"skill": "b", "rating": "excellent", "reason": "r"},
         {"skill": "c", "rating": "failing", "reason": "r"}],
    )
    assert [g["skill"] for g in record["gaps"]] == ["c"]


def test_build_gap_record_tolerates_a_result_without_an_evidence_key():
    """Forward-compatibility: an older cached result dict must not KeyError."""
    bare = {"milestone_id": "M1", "milestone_description": "d", "verdict": "miss",
            "confidence": "low", "reason": "r", "quote": "", "gap_to_ideal": ""}
    record = gap_output.build_gap_record("c", "X", "s", 7, {"turn_index": 1}, [bare], [])
    assert record["gaps"][0]["evidence"] == {}


# --- format_gap_profile -----------------------------------------------------

def test_profile_orders_by_miss_rate_descending():
    rows = [
        _row("M1", attempts=4, hits=4),            # miss_rate 0.00
        _row("M2", attempts=4, hits=0),            # miss_rate 1.00
        _row("M3", attempts=4, hits=2),            # miss_rate 0.50
    ]
    out = gap_output.format_gap_profile(rows, {}, _tuning())
    positions = [out.index(f":: {m}") for m in ("M2", "M3", "M1")]
    assert positions == sorted(positions)


def test_profile_labels_milestones_positionally():
    """milestone_performance stores only "M3"; the human-readable label has to come
    from the rubric, indexed by the position the id encodes."""
    rows = [_row("M2", attempts=2, hits=0)]
    milestones = {7: [{"label": "First"}, {"label": "Second"}]}
    assert "Second" in gap_output.format_gap_profile(rows, milestones, _tuning())


def test_profile_tolerates_a_rubric_that_shrank():
    """A later Layer C run can replace milestones under the same rubric_id with a
    shorter list, so the position may no longer exist."""
    rows = [_row("M9", attempts=1, hits=0)]
    out = gap_output.format_gap_profile(rows, {7: [{"label": "only one"}]}, _tuning())
    assert "M9" in out
    assert "only one" not in out


def test_profile_tolerates_a_missing_rubric_and_a_malformed_id():
    rows = [_row("M1"), _row("weird")]
    out = gap_output.format_gap_profile(rows, {}, _tuning())
    assert "M1" in out and "weird" in out


def test_profile_shows_the_pipeline_version():
    """A profile built mostly from v1-fallback rubrics is measuring Gemma free-text,
    not clustering evidence -- the numbers are uninterpretable without the split."""
    out = gap_output.format_gap_profile(
        [_row("M1", version="v1")], {}, _tuning()
    )
    assert "v1" in out


def test_empty_profile_says_so_rather_than_rendering_an_empty_table():
    assert "no milestone attempts" in gap_output.format_gap_profile([], {}, _tuning())


# --- gap_events_enabled gating ---------------------------------------------

def test_gap_events_flag_gates_the_event_but_not_the_aggregates(mocker):
    """The aggregate tables must still be written with the flag off -- it gates only
    the traceability record."""
    storage = mocker.patch("ego_trap.gap_output.storage")
    record = gap_output.build_gap_record(
        "c", "CSM_X", "s", 7, {"turn_index": 1},
        [_milestone_result("M1", "miss")], [],
    )

    gap_output.write_gap_record(
        mocker.Mock(), "CSM_X", "X", 7, record, _tuning(gap_events_enabled=False)
    )
    storage.insert_gap_event.assert_not_called()
    storage.upsert_milestone_performance.assert_called_once()
    storage.upsert_signal_recognition_gap.assert_called_once()

    gap_output.write_gap_record(
        mocker.Mock(), "CSM_X", "X", 7, record, _tuning(gap_events_enabled=True)
    )
    storage.insert_gap_event.assert_called_once()


# --- write_rubric_coverage_gap ---------------------------------------------

def test_rubric_coverage_gap_is_recorded_instead_of_vanishing(mocker):
    """This case used to produce NO row anywhere: a real coachable signal on a
    rubric-less scenario was printed and dropped."""
    storage = mocker.patch("ego_trap.gap_output.storage")
    gap_output.write_rubric_coverage_gap(
        mocker.Mock(), "CSM_X", "X", "call1", "new_topic",
        {"turn_index": 3, "client_utterance": "How does attribution work?"},
        "skipped_insufficient_responses", _tuning(),
    )
    event = storage.insert_gap_event.call_args[0][1]
    assert event["rubric_id"] is None
    assert event["signal_turn_index"] == 3
    gap = event["gaps"][0]
    assert gap["gap_type"] == "Rubric_Coverage_Gap"
    assert gap["rubric_status"] == "skipped_insufficient_responses"
    assert gap["client_utterance"] == "How does attribution work?"


def test_rubric_coverage_gap_does_not_touch_signal_recognition(mocker):
    """The CSM recognized the signal and answered it; there is just nothing to score
    against. recognized=True would inflate the recognition rate with un-scored events,
    and missed=True would be a straightforward lie."""
    storage = mocker.patch("ego_trap.gap_output.storage")
    gap_output.write_rubric_coverage_gap(
        mocker.Mock(), "CSM_X", "X", "call1", "new_topic",
        {"turn_index": 3, "client_utterance": "..."}, None, _tuning(),
    )
    storage.upsert_signal_recognition_gap.assert_not_called()
    storage.upsert_milestone_performance.assert_not_called()
    storage.upsert_csm.assert_called_once()


def test_deferred_to_teammate_still_skips_signal_recognition(mocker):
    """Pre-existing behaviour that must not regress: a teammate answering should not
    count against the CSM's own recognition rate."""
    storage = mocker.patch("ego_trap.gap_output.storage")
    gap_output.write_deferred_to_teammate(
        mocker.Mock(), "CSM_X", "X", "call1", "s",
        {"turn_index": 1, "client_utterance": "..."}, _tuning(),
    )
    storage.upsert_signal_recognition_gap.assert_not_called()
    assert storage.insert_gap_event.call_args[0][1]["gaps"][0]["gap_type"] == "Deferred_To_Teammate"


def test_signal_recognition_failure_records_a_miss(mocker):
    storage = mocker.patch("ego_trap.gap_output.storage")
    gap_output.write_signal_recognition_failure(
        mocker.Mock(), "CSM_X", "X", "call1", "s",
        {"turn_index": 1, "client_utterance": "..."}, _tuning(),
    )
    assert storage.upsert_signal_recognition_gap.call_args.kwargs["recognized"] is False
