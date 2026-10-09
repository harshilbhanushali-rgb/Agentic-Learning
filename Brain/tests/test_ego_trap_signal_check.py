"""Tests for ego_trap/signal_check.py -- Step 0 signal detection, both modes.

similarity-mode tests patch score_client_turns with hand-built similarity matrices
rather than mocking the embedder and Pinecone. That follows
test_layer_b_assignment.py: the rule under test is the relative-margin accept/reject
decision, and it should stay verifiable whatever the embedding model does to any
particular sentence. It also means these tests no longer mutate module globals --
tuning is an explicit argument now, not a patched attribute.
"""
import numpy as np
import pytest

from ego_trap import signal_check
from ego_trap.transcript_parser import EgoTrapRole, EgoTrapTurn
from shared.tuning import LayerDTuning, load_tuning


def _turn(idx, role, text, call_id="c1"):
    return EgoTrapTurn(index=idx, speaker_raw="X", role=role, text=text, call_id=call_id)


def _tuning(**overrides):
    base = dict(
        signal_detection_mode="similarity",
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
        # Added 2026-08-19: LayerDTuning gained these two fields with the call-level scoring
        # work and this helper was not updated, so every test in this file died at
        # construction with a TypeError. Set to tuning.yaml's shipped values so the helper
        # keeps describing production rather than inventing a config no run uses.
        scoring_unit="moment",
        scenarios_per_request=3,
        # Added 2026-08-20: the Layer D redesign keys (Brain/layer_d/). None of them is
        # read by ego_trap code, but LayerDTuning is one dataclass, so the helper must
        # supply them. Shipped tuning.yaml values, same rule as the 2026-08-19 pair above.
        segmentation_arm="e",
        grader_arm="checks",
        grader_model="gemini-3.6-flash",
        grader_reasoning_effort="medium",
        grader_k_runs=1,
        pairwise_swap=True,
        quote_verify_min_overlap=0.80,
        shrinkage_prior_strength=5.0,
        dead_check_naren_floor=0.50,
        min_attempts_to_rank=8,
    )
    base.update(overrides)
    return LayerDTuning(**base)


def _patch_scores(mocker, keys, is_sink, rows):
    """Stub score_client_turns so the accept/reject rule is tested, not the embedder."""
    mocker.patch.object(
        signal_check, "score_client_turns",
        return_value=(keys, is_sink, np.array(rows, dtype=float)),
    )


# --- similarity mode: the accept/reject rule --------------------------------

def test_similarity_mode_detects_signal_and_response(mocker):
    turns = [
        _turn(0, EgoTrapRole.CLIENT, "We've been running programmatic elsewhere."),
        _turn(1, EgoTrapRole.CSM, "I understand that concern."),
    ]
    _patch_scores(mocker, ["competitive_objection", "fillers"], [False, True], [[0.62, 0.30]])

    signals = signal_check.check_signals(
        turns, "raw text", {}, {}, mocker.Mock(), _tuning()
    )

    assert len(signals) == 1
    assert signals[0]["scenario_key"] == "competitive_objection"
    assert signals[0]["turn_index"] == 0
    assert signals[0]["response_outcome"] == "csm"


def test_similarity_mode_rejects_a_turn_whose_best_match_is_a_sink(mocker):
    """The sink IS the rejection mechanism. This replaces the old absolute 0.35 floor:
    the turn is dropped because backchannel beat every real scenario, not because its
    raw cosine was low -- which is what makes the rule scale-invariant."""
    turns = [_turn(0, EgoTrapRole.CLIENT, "Yeah, sounds good, thanks.")]
    _patch_scores(mocker, ["competitive_objection", "fillers"], [False, True], [[0.55, 0.71]])

    assert signal_check.check_signals(turns, "raw", {}, {}, mocker.Mock(), _tuning()) == []


def test_similarity_mode_high_absolute_cosine_is_not_enough_on_its_own(mocker):
    """Regression against reintroducing an absolute floor: a turn can score well above
    the old 0.35 against a real scenario and still be correctly rejected, because a
    sink scored higher."""
    turns = [_turn(0, EgoTrapRole.CLIENT, "Perfect, alright then.")]
    _patch_scores(mocker, ["real", "sink"], [False, True], [[0.60, 0.62]])

    assert signal_check.check_signals(turns, "raw", {}, {}, mocker.Mock(), _tuning()) == []


def test_similarity_mode_margin_governs_how_many_candidates_survive(mocker):
    turns = [_turn(0, EgoTrapRole.CLIENT, "Ambiguous but real content here.")]
    _patch_scores(mocker, ["a", "b"], [False, False], [[0.60, 0.59]])

    signals = signal_check.check_signals(
        turns, "raw", {}, {}, mocker.Mock(),
        _tuning(similarity_relative_margin=0.90, max_scenarios_per_signal=2),
    )
    assert signals[0]["candidate_scenario_keys"] == ["a", "b"]

    signals = signal_check.check_signals(
        turns, "raw", {}, {}, mocker.Mock(),
        _tuning(similarity_relative_margin=0.999, max_scenarios_per_signal=2),
    )
    assert signals[0]["candidate_scenario_keys"] == ["a"]


def test_similarity_mode_scenario_key_always_comes_from_the_local_map(mocker):
    """It used to come from Pinecone metadata and was never validated against the
    taxonomy, so a stale index could inject a key that no longer exists."""
    turns = [_turn(0, EgoTrapRole.CLIENT, "Real content.")]
    _patch_scores(mocker, ["only_real_key"], [False], [[0.7]])

    signals = signal_check.check_signals(turns, "raw", {}, {}, mocker.Mock(), _tuning())
    assert signals[0]["scenario_key"] == "only_real_key"


def test_similarity_mode_no_client_turns_is_not_an_error(mocker):
    turns = [_turn(0, EgoTrapRole.CSM, "Just me talking.")]
    assert signal_check.check_signals(turns, "raw", {}, {}, mocker.Mock(), _tuning()) == []


# --- similarity mode: response_outcome regressions (behaviour must not change) ---

def test_similarity_mode_no_response_before_next_client(mocker):
    turns = [
        _turn(0, EgoTrapRole.CLIENT, "We've been running programmatic elsewhere."),
        _turn(1, EgoTrapRole.CLIENT, "Another client turn before anyone responds."),
    ]
    _patch_scores(mocker, ["competitive_objection"], [False], [[0.7], [0.2]])

    signals = signal_check.check_signals(turns, "raw", {}, {}, mocker.Mock(), _tuning())
    assert signals[0]["response_outcome"] == "none"


def test_similarity_mode_other_joveo_response_is_not_csm_failure(mocker):
    """Regression: a teammate answering must not be conflated with true CSM silence."""
    turns = [
        _turn(0, EgoTrapRole.CLIENT, "We've been running programmatic elsewhere."),
        _turn(1, EgoTrapRole.OTHER_JOVEO, "Let me answer that — here's how it works."),
        _turn(2, EgoTrapRole.CLIENT, "Another client turn."),
    ]
    _patch_scores(mocker, ["competitive_objection"], [False], [[0.7], [0.2]])

    signals = signal_check.check_signals(turns, "raw", {}, {}, mocker.Mock(), _tuning())
    assert signals[0]["response_outcome"] == "other_joveo"


# --- gemma mode -------------------------------------------------------------

def _patch_gemma(mocker, signals):
    mocker.patch.object(
        signal_check, "call_gemma", return_value={"signals_detected": signals}
    )


def test_gemma_mode_resolves_turn_index_from_utterance(mocker):
    turns = [
        _turn(0, EgoTrapRole.CLIENT, "We spent a lot."),
        _turn(1, EgoTrapRole.CSM, "Understood."),
    ]
    _patch_gemma(mocker, [
        {"scenario_key": "budget_concern", "client_utterance": "We spent a lot."}
    ])

    signals = signal_check.check_signals(
        turns, "raw text", {}, {"budget_concern": {}}, mocker.Mock(),
        _tuning(signal_detection_mode="gemma"),
    )
    assert signals[0]["scenario_key"] == "budget_concern"
    assert signals[0]["turn_index"] == 0
    assert signals[0]["response_outcome"] == "csm"


def test_gemma_mode_response_outcome_derived_from_turns_not_llm(mocker):
    """response_outcome must come from actual turn roles, not any LLM-provided field."""
    turns = [
        _turn(0, EgoTrapRole.CLIENT, "We spent a lot."),
        _turn(1, EgoTrapRole.OTHER_JOVEO, "Let me take that one."),
    ]
    _patch_gemma(mocker, [
        {"scenario_key": "budget_concern", "client_utterance": "We spent a lot."}
    ])

    signals = signal_check.check_signals(
        turns, "raw text", {}, {"budget_concern": {}}, mocker.Mock(),
        _tuning(signal_detection_mode="gemma"),
    )
    assert signals[0]["response_outcome"] == "other_joveo"


def test_gemma_mode_skips_unmatched_utterance(mocker):
    turns = [_turn(0, EgoTrapRole.CLIENT, "Something else entirely.")]
    _patch_gemma(mocker, [
        {"scenario_key": "budget_concern", "client_utterance": "Not in the transcript."}
    ])

    signals = signal_check.check_signals(
        turns, "raw text", {}, {"budget_concern": {}}, mocker.Mock(),
        _tuning(signal_detection_mode="gemma"),
    )
    assert signals == []


def test_gemma_mode_prompt_lists_only_the_coachable_map(mocker):
    """The whole point of the split: a sink in the prompt is an invitation to report
    backchannel as a coachable signal."""
    turns = [_turn(0, EgoTrapRole.CLIENT, "We spent a lot.")]
    gemma = mocker.patch.object(
        signal_check, "call_gemma", return_value={"signals_detected": []}
    )
    scenario_map = {
        "budget_concern": {"business_description": "budget talk", "keyphrases": []},
        "fillers": {"business_description": "backchannel", "keyphrases": []},
    }
    coachable = {"budget_concern": scenario_map["budget_concern"]}

    signal_check.check_signals(
        turns, "raw text", scenario_map, coachable, mocker.Mock(),
        _tuning(signal_detection_mode="gemma"),
    )
    prompt = gemma.call_args[0][0]
    assert "budget_concern" in prompt
    assert "fillers" not in prompt


def test_unknown_detection_mode_raises_rather_than_silently_picking_one(mocker):
    with pytest.raises(ValueError, match="unknown signal_detection_mode"):
        signal_check.check_signals(
            [], "raw", {}, {}, mocker.Mock(), _tuning(signal_detection_mode="typo")
        )


# --- turn matching ----------------------------------------------------------

def _client(text):
    return [_turn(0, EgoTrapRole.CLIENT, text)]


def test_exact_mode_matches_verbatim():
    idx, reason = signal_check.find_turn_index(
        _client("We spent a lot."), "We spent a lot.", mode="exact", min_ratio=0.85
    )
    assert (idx, reason) == (0, "")


def test_exact_mode_fails_on_punctuation_drift():
    idx, reason = signal_check.find_turn_index(
        _client("We spent a lot."), "we spent a lot", mode="exact", min_ratio=0.85
    )
    assert idx is None
    assert reason == "no_matching_client_turn"


def test_normalized_mode_survives_punctuation_and_case_drift():
    """The default. Introduces no threshold -- it only stops a smart quote or a
    trailing period from discarding a real signal."""
    idx, _ = signal_check.find_turn_index(
        _client("We spent a lot, honestly."), "we spent a lot honestly",
        mode="normalized", min_ratio=0.85,
    )
    assert idx == 0


def test_normalized_mode_matches_a_quote_inside_a_longer_turn():
    idx, _ = signal_check.find_turn_index(
        _client("So, honestly, we spent a lot last quarter on this."), "we spent a lot",
        mode="normalized", min_ratio=0.85,
    )
    assert idx == 0


def test_normalized_mode_does_not_match_in_reverse():
    """A two-word turn is contained in almost any long paraphrase, so the reverse
    direction needs a minimum-length guard -- an uncalibrated number. Not shipped."""
    idx, _ = signal_check.find_turn_index(
        _client("Yeah."), "Yeah, we spent a great deal on this last quarter.",
        mode="normalized", min_ratio=0.85,
    )
    assert idx is None


def test_ratio_mode_matches_a_paraphrase_that_normalized_cannot():
    idx, _ = signal_check.find_turn_index(
        _client("We spent a lot of money last quarter."),
        "We spent a lot of money last quater.",  # typo
        mode="ratio", min_ratio=0.85,
    )
    assert idx == 0


def test_ratio_mode_rejects_below_its_floor():
    idx, _ = signal_check.find_turn_index(
        _client("We spent a lot of money last quarter."),
        "Completely unrelated sentence about scheduling.",
        mode="ratio", min_ratio=0.85,
    )
    assert idx is None


def test_quoted_non_client_turn_is_a_distinct_diagnosis():
    """Previously indistinguishable from a paraphrase, and the log truncated at 80
    chars -- which is why the dropped signals on record cannot be diagnosed at all."""
    turns = [
        _turn(0, EgoTrapRole.CLIENT, "Sounds fine."),
        _turn(1, EgoTrapRole.CSM, "Our platform optimizes spend across every job board."),
    ]
    idx, reason = signal_check.find_turn_index(
        turns, "Our platform optimizes spend across every job board.",
        mode="normalized", min_ratio=0.85,
    )
    assert idx is None
    assert reason == "quoted_non_client_turn"


def test_unknown_turn_match_mode_raises():
    with pytest.raises(ValueError, match="unknown turn_match_mode"):
        signal_check.find_turn_index(_client("x"), "x", mode="fuzzy", min_ratio=0.85)


# --- resolve_signals --------------------------------------------------------

def test_resolve_signals_returns_rejections_instead_of_only_printing():
    """Returned, not printed, so the harness can replay a persisted Gemma response
    through this exact function under every match mode with zero new Gemma calls."""
    turns = [_turn(0, EgoTrapRole.CLIENT, "We spent a lot.")]
    resolved, unresolved = signal_check.resolve_signals(
        turns,
        [
            {"scenario_key": "a", "client_utterance": "We spent a lot."},
            {"scenario_key": "b", "client_utterance": "Never said this."},
        ],
        mode="normalized", min_ratio=0.85,
    )
    assert [s["scenario_key"] for s in resolved] == ["a"]
    assert [u["scenario_key"] for u in unresolved] == ["b"]
    assert unresolved[0]["reason"] == "no_matching_client_turn"


def test_resolve_signals_flags_a_malformed_entry_rather_than_raising():
    """Gemma omitting a field must not KeyError the whole transcript."""
    turns = [_turn(0, EgoTrapRole.CLIENT, "Hi.")]
    resolved, unresolved = signal_check.resolve_signals(
        turns, [{"scenario_key": "a"}, {"client_utterance": "Hi."}],
        mode="normalized", min_ratio=0.85,
    )
    assert resolved == []
    assert [u["reason"] for u in unresolved] == ["malformed_signal", "malformed_signal"]


# --- shortlist --------------------------------------------------------------

def test_shortlist_k_zero_is_a_no_op():
    """The shipped default. Any K > 0 trades recall for precision, so it must not
    engage until the recall sweep justifies a value."""
    pool = {"a": {}, "b": {}, "c": {}}
    assert signal_check.shortlist_scenarios(pool, ["some text"], 0) is pool


def test_shortlist_returns_pool_unchanged_when_k_exceeds_it():
    pool = {"a": {}, "b": {}}
    assert signal_check.shortlist_scenarios(pool, ["text"], 10) is pool


def test_shortlist_keeps_the_k_nearest(mocker):
    pool = {"near": {}, "far": {}, "mid": {}}
    mocker.patch.object(
        signal_check, "_score",
        return_value=(["near", "far", "mid"], np.array([[0.9, 0.1, 0.5]])),
    )
    assert set(signal_check.shortlist_scenarios(pool, ["text"], 2)) == {"near", "mid"}


def test_shortlist_ranks_by_max_over_turns_not_mean(mocker):
    """A scenario raised once, sharply, in a long call is exactly what Layer D exists
    to catch. A mean over turns would bury it under the chatter."""
    pool = {"spike": {}, "steady": {}}
    mocker.patch.object(
        signal_check, "_score",
        return_value=(["spike", "steady"], np.array([[0.95, 0.40], [0.05, 0.40]])),
    )
    assert set(signal_check.shortlist_scenarios(pool, ["a", "b"], 1)) == {"spike"}


# --- score_client_turns edge cases -----------------------------------------

def test_score_client_turns_handles_empty_input():
    keys, is_sink, sims = signal_check.score_client_turns([], {"a": {}})
    assert keys == [] and is_sink == [] and sims.size == 0
    keys, is_sink, sims = signal_check.score_client_turns(["text"], {})
    assert keys == [] and is_sink == [] and sims.size == 0


def test_select_signal_on_empty_row_is_not_a_signal():
    assert signal_check.select_signal(np.array([]), [], [], margin=0.95, cap=1) is None


# --- the shipped configuration ---------------------------------------------

def test_shipped_tuning_modes_are_ones_this_module_implements():
    """Guards against tuning.yaml being edited to a mode signal_check would reject at
    runtime, deep into a Gemma-spending run."""
    t = load_tuning().layer_d
    assert t.signal_detection_mode in ("gemma", "similarity")
    assert t.turn_match_mode in signal_check._TURN_MATCH_MODES
