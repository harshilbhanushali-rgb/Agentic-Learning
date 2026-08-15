"""Tests for ego_trap/call_scoring.py -- call-level milestone scoring.

Design: docs/superpowers/specs/2026-08-15-layer-d-call-level-scoring-design.md

Everything except score_call is pure, so the cases that matter -- chunking, id
reconciliation, missing-id defaulting, and the quote verifier that is the design's
hallucination check -- are testable with no network and no DB.
"""
import pytest

from config import Config
from ego_trap import call_scoring
from ego_trap.call_scoring import ScenarioBlock


def _config():
    return Config(
        gemma_api_key="key",
        database_url="",
        joveo_speakers_lower=frozenset(),
        naren_name_lower="",
        pinecone_api_key="",
        pinecone_index_name="",
    )


def _milestone(order, description="d", **extra):
    base = {"order": order, "label": f"L{order}", "description": description,
            "detection_hint": "hint", "sequencing_type": "fixed", "position_variance": 0.1,
            "support_calls": 12, "support_clauses": 40, "relevance_mean": 0.66,
            "source_v": "v2_hdbscan"}
    base.update(extra)
    return base


def _block(key, n_milestones=2, **kw):
    return ScenarioBlock(
        scenario_key=key,
        description=f"what {key} is",
        rubric={"milestones": [_milestone(i + 1) for i in range(n_milestones)]},
        **kw,
    )


TURNS = [
    ("Client", "So what do we do about the ATS integration?"),
    ("CSM", "We can bridge it with a pixel on the apply page."),
    ("Client", "And the budget?"),
    ("CSM", "Right — on budget, we'd start at fifty thousand a quarter."),
]


# --- chunking -------------------------------------------------------------

def test_chunks_respect_the_requested_size():
    blocks = [_block(f"s{i}") for i in range(7)]
    chunks = call_scoring.chunk_scenarios(blocks, 3)
    assert [len(c) for c in chunks] == [3, 3, 1]


def test_chunk_size_below_one_raises_rather_than_looping_forever():
    with pytest.raises(ValueError, match="scenarios_per_request"):
        call_scoring.chunk_scenarios([_block("s")], 0)


# --- transcript -----------------------------------------------------------

def test_transcript_is_one_based_and_numbers_every_turn():
    out = call_scoring.format_transcript(TURNS)
    assert out.startswith("[1] Client:")
    assert "[4] CSM:" in out
    # 1-based because `turn` in a verdict is checked against these numbers.
    assert "[0]" not in out


# --- ids ------------------------------------------------------------------

def test_ids_come_from_the_full_list_even_when_some_are_skipped():
    """milestone_id is the array POSITION. Deriving ids from a FILTERED list would
    renumber every later milestone and silently repoint milestone_performance rows."""
    ms = [_milestone(1), _milestone(2, not_coachable_flag=True), _milestone(3)]
    block = ScenarioBlock("s", "d", {"milestones": ms})
    _, expected = call_scoring.build_situations_block([block], skip_uncoachable=True)
    assert [mid for mid, _ in expected["S0"]] == ["M1", "M3"]


def test_a_scenario_with_no_scoreable_milestones_is_dropped_entirely():
    block = ScenarioBlock("s", "d", {"milestones": []})
    situations, expected = call_scoring.build_situations_block([block])
    assert expected == {} and situations == ""


# --- parsing --------------------------------------------------------------

def _parse(reply, blocks, skip_uncoachable=False):
    _, expected = call_scoring.build_situations_block(blocks, skip_uncoachable)
    return call_scoring.parse_response(reply, expected, blocks)


def test_did_occur_false_scores_nothing_and_is_not_a_pile_of_misses():
    """The whole point of over-including candidate scenarios. If a declined scenario
    came back as all-miss it would tank the score instead of being excluded."""
    blocks = [_block("s0")]
    results, _ = _parse([{"situation_id": "S0", "did_occur": False,
                          "occurrence_reason": "never came up"}], blocks)
    assert results[0]["did_occur"] is False
    assert results[0]["milestones"] == []


def test_a_scenario_the_model_never_mentions_is_NOT_OCCURRED_not_all_miss():
    """A dropped id must not become a full set of fabricated coaching failures --
    that is precisely how truncation would corrupt a run."""
    blocks = [_block("s0"), _block("s1")]
    results, warnings = _parse([{"situation_id": "S0", "did_occur": True, "milestones": [
        {"id": "M1", "verdict": "full_hit"}, {"id": "M2", "verdict": "miss"}]}], blocks)
    s1 = [r for r in results if r["scenario_key"] == "s1"][0]
    assert s1["did_occur"] is False and s1["milestones"] == [] and s1["returned"] is False
    assert any("no verdict returned" in w for w in warnings)


def test_a_missing_milestone_inside_a_scored_scenario_defaults_to_miss_and_warns():
    blocks = [_block("s0", n_milestones=3)]
    results, warnings = _parse([{"situation_id": "S0", "did_occur": True, "milestones": [
        {"id": "M1", "verdict": "full_hit"}]}], blocks)
    verdicts = {m["milestone_id"]: m["verdict"] for m in results[0]["milestones"]}
    assert verdicts == {"M1": "full_hit", "M2": "miss", "M3": "miss"}
    assert results[0]["milestones"][1]["returned"] is False
    assert any("missing" in w for w in warnings)


def test_unrecognised_verdict_becomes_miss():
    blocks = [_block("s0", n_milestones=1)]
    results, _ = _parse([{"situation_id": "S0", "did_occur": True,
                          "milestones": [{"id": "M1", "verdict": "brilliant"}]}], blocks)
    assert results[0]["milestones"][0]["verdict"] == "miss"


def test_evidence_is_gated_on_full_hit_exactly_as_the_moment_scorer_gates_it():
    blocks = [_block("s0", n_milestones=2)]
    results, _ = _parse([{"situation_id": "S0", "did_occur": True, "milestones": [
        {"id": "M1", "verdict": "full_hit", "quote": "x", "turn": 2, "gap_to_ideal": "g"},
        {"id": "M2", "verdict": "partial_hit", "quote": "y", "turn": 4, "gap_to_ideal": "g"}]}],
        blocks)
    full, partial = results[0]["milestones"]
    assert full["quote"] == "" and full["turn"] is None and full["gap_to_ideal"] == ""
    assert partial["quote"] == "y" and partial["turn"] == 4


def test_non_integer_turn_degrades_to_none_rather_than_crashing():
    blocks = [_block("s0", n_milestones=1)]
    results, _ = _parse([{"situation_id": "S0", "did_occur": True, "milestones": [
        {"id": "M1", "verdict": "partial_hit", "quote": "q", "turn": "somewhere"}]}], blocks)
    assert results[0]["milestones"][0]["turn"] is None


def test_unknown_situation_ids_are_reported():
    blocks = [_block("s0", n_milestones=1)]
    _, warnings = _parse([{"situation_id": "S0", "did_occur": True,
                           "milestones": [{"id": "M1", "verdict": "miss"}]},
                          {"situation_id": "S9", "did_occur": True, "milestones": []}], blocks)
    assert any("unknown situation ids" in w for w in warnings)


def test_a_dict_wrapped_reply_is_accepted_like_the_batch_scorer():
    blocks = [_block("s0", n_milestones=1)]
    results, _ = _parse({"results": [{"situation_id": "S0", "did_occur": True,
                                      "milestones": [{"id": "M1", "verdict": "full_hit"}]}]},
                        blocks)
    assert results[0]["milestones"][0]["verdict"] == "full_hit"


# --- quote verification: the design's hallucination check -----------------

def _res(quote, turn, verdict="partial_hit"):
    return [{"scenario_key": "s", "did_occur": True, "milestones": [
        {"milestone_id": "M1", "verdict": verdict, "quote": quote, "turn": turn}]}]


def test_a_real_quote_at_the_right_turn_verifies():
    v = call_scoring.verify_quotes(_res("bridge it with a pixel", 2), TURNS)
    assert v["checked"] == 1 and v["verified"] == 1 and v["rate"] == 1.0


def test_whitespace_and_case_do_not_break_verification():
    v = call_scoring.verify_quotes(_res("BRIDGE  IT   with a PIXEL", 2), TURNS)
    assert v["verified"] == 1


def test_an_invented_quote_fails_and_is_reported_verbatim():
    v = call_scoring.verify_quotes(_res("I guarantee a 300% lift", 2), TURNS)
    assert v["verified"] == 0
    assert v["failures"][0]["found_elsewhere"] is False
    assert "300%" in v["failures"][0]["quote"]


def test_a_real_quote_cited_at_the_wrong_turn_is_flagged_but_marked_found_elsewhere():
    """Distinguishing 'fabricated' from 'misattributed' matters: one is a lie, the
    other is a citation bug, and they need different responses."""
    v = call_scoring.verify_quotes(_res("fifty thousand a quarter", 1), TURNS, window=0)
    assert v["verified"] == 0 and v["failures"][0]["found_elsewhere"] is True


def test_an_adjacent_turn_still_verifies_within_the_window():
    v = call_scoring.verify_quotes(_res("bridge it with a pixel", 3), TURNS, window=2)
    assert v["verified"] == 1


def test_empty_quotes_are_not_counted_as_failures():
    """A full hit is not required to quote, so an empty quote must not depress the rate."""
    v = call_scoring.verify_quotes(_res("", None, verdict="full_hit"), TURNS)
    assert v["checked"] == 0 and v["failures"] == []


# --- the impure entry point ----------------------------------------------

def test_score_call_chunks_and_pins_the_model(mocker):
    spy = mocker.patch(
        "ego_trap.call_scoring.call_gemma",
        return_value=[{"situation_id": "S0", "did_occur": True,
                       "milestones": [{"id": "M1", "verdict": "full_hit"},
                                      {"id": "M2", "verdict": "miss"}]}],
    )
    blocks = [_block(f"s{i}") for i in range(4)]
    results, _ = call_scoring.score_call(TURNS, blocks, _config(), scenarios_per_request=2,
                                         model="pinned", fallback_models=())
    assert spy.call_count == 2                       # 4 scenarios / 2 per request
    assert spy.call_args.kwargs["model"] == "pinned"
    assert spy.call_args.kwargs["fallback_models"] == ()
    # Each request answers only S0, so the second scenario in each chunk is not-occurred.
    assert sum(1 for r in results if r["did_occur"]) == 2


def test_score_call_puts_the_whole_transcript_in_every_request():
    """The unit change IS the transcript being present. If a chunk ever went out without
    it, call mode would silently degrade to a worse version of moment mode."""
    import unittest.mock as um
    with um.patch("ego_trap.call_scoring.call_gemma", return_value=[]) as spy:
        call_scoring.score_call(TURNS, [_block("s0")], _config())
    prompt = spy.call_args[0][0]
    assert "[4] CSM: Right — on budget" in prompt
    assert "SITUATION S0: s0" in prompt
