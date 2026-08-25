"""layer_d/graders.py -- verdict paths driven by hand-built chat responses.

No network, no tuning reads: the chat callable is a fake, exactly as the
similarity-mode tests patch score_client_turns instead of mocking the embedder.
"""
from layer_d.graders import (
    CHECKS_BATCH_SIZE, GradedMoment, MoveVerdict, aggregate_runs,
    build_checks_prompt, grade_checks_batch, grade_pairwise, merge_swapped,
    parse_checks_response, parse_pairwise_response,
)

MOVES = [
    {"move_id": "M1", "name": "Probe", "criterion": "Probe the mechanics"},
    {"move_id": "M2", "name": "Track", "criterion": "Confirm down-funnel tracking"},
]
MOMENT = {
    "moment_id": "call1:t4",
    "trigger_text": "We are drowning in applications.",
    "response_text": "Let me pull up the funnel first. Do you have UTM tags on those redirects?",
}


# ------------------------------------------------------------------ checks arm

def test_verified_credit_is_a_hit_with_the_quote_kept():
    raw = [{"moment_id": "call1:t4", "verdicts": [
        {"move_id": "M1", "performed": "full", "quote": "Let me pull up the funnel first"},
        {"move_id": "M2", "performed": "full", "quote": "Do you have UTM tags on those redirects?"},
    ]}]
    [g] = parse_checks_response(raw, [MOMENT], MOVES, 0.80)
    assert [v.verdict for v in g.verdicts] == ["hit", "hit"]
    assert g.verdicts[0].quote == "Let me pull up the funnel first"


def test_fabricated_quote_is_unscored_not_miss():
    raw = [{"moment_id": "call1:t4", "verdicts": [
        {"move_id": "M1", "performed": "full", "quote": "I guarantee a 40% lift by Friday"},
        {"move_id": "M2", "performed": "no", "quote": ""},
    ]}]
    [g] = parse_checks_response(raw, [MOMENT], MOVES, 0.80)
    assert g.verdicts[0].verdict == "unscored"
    assert g.verdicts[0].reason == "quote_unverified"
    assert g.verdicts[1].verdict == "miss"


def test_performed_false_is_a_miss_without_needing_a_quote():
    raw = [{"moment_id": "call1:t4", "verdicts": [
        {"move_id": "M1", "performed": "no"},
        {"move_id": "M2", "performed": "no", "quote": "irrelevant"},
    ]}]
    [g] = parse_checks_response(raw, [MOMENT], MOVES, 0.80)
    assert [v.verdict for v in g.verdicts] == ["miss", "miss"]


def test_missing_move_id_is_unscored_never_a_miss():
    # The truncation defect: a dropped id must not manufacture a coaching failure.
    raw = [{"moment_id": "call1:t4", "verdicts": [
        {"move_id": "M1", "performed": "no"},
    ]}]
    [g] = parse_checks_response(raw, [MOMENT], MOVES, 0.80)
    assert g.verdicts[1].move_id == "M2"
    assert g.verdicts[1].verdict == "unscored"
    assert g.verdicts[1].reason == "missing_from_response"


def test_whole_moment_missing_from_response_is_fully_unscored():
    [g] = parse_checks_response([], [MOMENT], MOVES, 0.80)
    assert all(v.verdict == "unscored" for v in g.verdicts)


def test_verified_partial_is_a_partial():
    raw = [{"moment_id": "call1:t4", "verdicts": [
        {"move_id": "M1", "performed": "partial", "quote": "Let me pull up the funnel"},
        {"move_id": "M2", "performed": "no"},
    ]}]
    [g] = parse_checks_response(raw, [MOMENT], MOVES, 0.80)
    assert g.verdicts[0].verdict == "partial"
    assert g.verdicts[0].quote == "Let me pull up the funnel"


def test_unverified_partial_is_unscored_not_miss():
    raw = [{"moment_id": "call1:t4", "verdicts": [
        {"move_id": "M1", "performed": "partial", "quote": "words never spoken here"},
        {"move_id": "M2", "performed": "no"},
    ]}]
    [g] = parse_checks_response(raw, [MOMENT], MOVES, 0.80)
    assert g.verdicts[0].verdict == "unscored"
    assert g.verdicts[0].reason == "quote_unverified"


def test_legacy_boolean_performed_is_unscored():
    raw = [{"moment_id": "call1:t4", "verdicts": [
        {"move_id": "M1", "performed": True, "quote": "Let me pull up the funnel"},
        {"move_id": "M2", "performed": "no"},
    ]}]
    [g] = parse_checks_response(raw, [MOMENT], MOVES, 0.80)
    assert g.verdicts[0].verdict == "unscored"


def test_grade_checks_batch_respects_batch_size_and_covers_all():
    calls = []
    moments = [dict(MOMENT, moment_id=f"c:{i}") for i in range(CHECKS_BATCH_SIZE + 2)]

    def chat(prompt):
        calls.append(prompt)
        return []                              # everything unscored, but everything answered

    graded = grade_checks_batch(chat, "s", "sig", MOVES, moments, 0.80)
    assert len(calls) == 2                     # one full batch + one remainder
    assert len(graded) == len(moments)
    assert {g.moment_id for g in graded} == {m["moment_id"] for m in moments}


def test_grade_checks_batch_propagates_chat_errors():
    # The caller must see the failure so it never checkpoints the transcript.
    def chat(prompt):
        raise RuntimeError("gateway down")
    try:
        grade_checks_batch(chat, "s", "sig", MOVES, [MOMENT], 0.80)
        assert False, "should have raised"
    except RuntimeError:
        pass


def test_checks_prompt_contains_moves_and_moments():
    p = build_checks_prompt("app_volume", "signature text", MOVES, [MOMENT])
    assert "M1" in p and "Probe the mechanics" in p
    assert "call1:t4" in p and "drowning in applications" in p


def test_dict_wrapped_array_is_unwrapped():
    # response_format json_object makes some models wrap the array in a key; a
    # paid batch must not silently parse to all-unscored (audit finding).
    raw = {"results": [{"moment_id": "call1:t4", "verdicts": [
        {"move_id": "M1", "performed": "no"},
        {"move_id": "M2", "performed": "no"},
    ]}]}
    [g] = parse_checks_response(raw, [MOMENT], MOVES, 0.80)
    assert [v.verdict for v in g.verdicts] == ["miss", "miss"]


def test_dict_with_multiple_lists_is_not_guessed_at():
    raw = {"a": [{"moment_id": "call1:t4", "verdicts": []}], "b": []}
    [g] = parse_checks_response(raw, [MOMENT], MOVES, 0.80)
    assert all(v.verdict == "unscored" for v in g.verdicts)


# ---------------------------------------------------------------- pairwise arm

def test_parse_pairwise_normalizes_case_and_drops_junk():
    raw = [{"move_id": "M1", "better": "a"}, {"move_id": "M2", "better": "maybe"},
           {"move_id": "M9", "better": "B"}]
    assert parse_pairwise_response(raw, MOVES) == {"M1": "A"}


def test_merge_swapped_consistent_win_is_a_hit():
    verdicts = merge_swapped({"M1": "A", "M2": "equal"},
                             {"M1": "B", "M2": "equal"}, MOVES)
    assert [v.verdict for v in verdicts] == ["hit", "partial"]


def test_merge_swapped_consistent_loss_is_a_miss():
    [v, _] = merge_swapped({"M1": "B", "M2": "equal"},
                           {"M1": "A", "M2": "equal"}, MOVES)
    assert v.verdict == "miss"


def test_merge_swapped_position_flip_is_unscored():
    # Judge says "A" in both orders -> pure position bias -> unscored.
    [v, _] = merge_swapped({"M1": "A", "M2": "equal"},
                           {"M1": "A", "M2": "equal"}, MOVES)
    assert v.verdict == "unscored" and v.reason == "swap_inconsistent"


def test_merge_swapped_missing_either_order_is_unscored():
    [v, _] = merge_swapped({"M2": "equal"}, {"M1": "B", "M2": "equal"}, MOVES)
    assert v.verdict == "unscored" and v.reason == "missing_from_response"


def test_grade_pairwise_makes_exactly_two_calls_and_swaps():
    prompts = []
    exemplar = {"trigger_text": "volume worry", "response_text": "naren reply"}

    def chat(prompt):
        prompts.append(prompt)
        return [{"move_id": "M1", "better": "A" if len(prompts) == 1 else "B"},
                {"move_id": "M2", "better": "equal"}]

    g = grade_pairwise(chat, "s", "sig", MOVES, MOMENT, exemplar)
    assert len(prompts) == 2
    # first order: CSM reply is A; second order it is B
    assert prompts[0].index(MOMENT["response_text"]) < prompts[0].index("naren reply")
    assert prompts[1].index("naren reply") < prompts[1].index(MOMENT["response_text"])
    assert [v.verdict for v in g.verdicts] == ["hit", "partial"]


def test_single_order_maps_picks_relative_to_csm_side():
    from layer_d.graders import single_order_verdicts
    picks = {"M1": "B", "M2": "equal"}
    v = single_order_verdicts(picks, MOVES, csm_side="B")
    assert [x.verdict for x in v] == ["hit", "partial"]
    v2 = single_order_verdicts(picks, MOVES, csm_side="A")
    assert [x.verdict for x in v2] == ["miss", "partial"]


def test_grade_pairwise_single_order_makes_one_call():
    prompts = []
    exemplar = {"trigger_text": "volume worry", "response_text": "naren reply"}

    def chat(prompt):
        prompts.append(prompt)
        return [{"move_id": "M1", "better": "B"}, {"move_id": "M2", "better": "equal"}]

    g = grade_pairwise(chat, "s", "sig", MOVES, MOMENT, exemplar,
                       swap=False, csm_side="B")
    assert len(prompts) == 1
    # CSM on side B -> exemplar text comes first in the single prompt
    assert prompts[0].index("naren reply") < prompts[0].index(MOMENT["response_text"])
    assert [v.verdict for v in g.verdicts] == ["hit", "partial"]


# ------------------------------------------------------------- k-run consensus

def _v(move_id, verdict, reason=""):
    return MoveVerdict(move_id, verdict, reason=reason)


def test_aggregate_runs_majority_wins():
    runs = [[_v("M1", "hit")], [_v("M1", "hit")], [_v("M1", "miss")]]
    [v] = aggregate_runs(runs, [MOVES[0]])
    assert v.verdict == "hit"


def test_aggregate_runs_tie_is_unscored():
    runs = [[_v("M1", "hit")], [_v("M1", "miss")]]
    [v] = aggregate_runs(runs, [MOVES[0]])
    assert v.verdict == "unscored" and v.reason == "run_disagreement"


def test_aggregate_runs_unscored_votes_do_not_count():
    runs = [[_v("M1", "unscored", "quote_unverified")],
            [_v("M1", "hit")], [_v("M1", "unscored", "missing_from_response")]]
    [v] = aggregate_runs(runs, [MOVES[0]])
    assert v.verdict == "hit"


def test_aggregate_runs_all_unscored_stays_unscored():
    runs = [[_v("M1", "unscored", "x")], [_v("M1", "unscored", "y")]]
    [v] = aggregate_runs(runs, [MOVES[0]])
    assert v.verdict == "unscored" and v.reason == "all_runs_unscored"


def test_aggregate_single_run_is_identity():
    run = [[_v("M1", "hit"), _v("M2", "unscored", "quote_unverified")]]
    assert aggregate_runs(run, MOVES) == run[0]
