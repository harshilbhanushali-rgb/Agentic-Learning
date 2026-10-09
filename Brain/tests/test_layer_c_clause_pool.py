"""Guards the build_clause_pool extraction out of _pass1_cluster_scenario.

replay_layer_c_admitted.py's entire validity rests on reproducing Layer C's
Pass 1 exactly -- this codebase has already been burned by a dry run that
reimplemented production logic and disagreed with it by 99.7% vs 14%. So the
extraction must be provably behavior-preserving, not merely look equivalent.

Fixtures use sentences of >=4 tokens on purpose: segmenter.segment_into_clauses
silently drops anything shorter, so the first version of this file asserted
against clauses that never existed. That filter is pinned by its own test below
rather than left as a trap for the next person.
"""
from preprocessing.segmenter import segment_into_clauses
from v2.layer_c import build_clause_pool

_THREE_SENTENCES = ("We segment bids by device type. "
                    "Mobile traffic converts noticeably worse. "
                    "So we cap the desktop spend.")
_ONE_SENTENCE = "That is a single clause of prose."


def test_the_segmenter_drops_sentences_under_four_tokens():
    """Pinned because build_clause_pool inherits it, and because it means clause
    count is NOT sentence count -- an admitted response of only short sentences
    contributes nothing to a clause pool at all.
    """
    assert segment_into_clauses("Sure.") == []
    assert len(segment_into_clauses(_ONE_SENTENCE)) == 1


def test_four_lists_stay_index_aligned():
    responses = [
        {"response_text": _THREE_SENTENCES, "call_filename": "call_a"},
        {"response_text": _ONE_SENTENCE, "call_filename": "call_b"},
    ]
    clauses, positions, calls, pairs = build_clause_pool(responses)

    assert len(clauses) == len(positions) == len(calls) == len(pairs)
    assert len(clauses) == 4  # 3 from call_a, 1 from call_b


def test_every_clause_carries_its_own_source_call():
    """The distinct-call support gate is the whole reason clause_calls exists --
    two adjacent clauses of ONE response counting as 'recurring' was the
    95-milestone bug. Attribution must never smear across responses.
    """
    responses = [
        {"response_text": _THREE_SENTENCES, "call_filename": "call_a"},
        {"response_text": _ONE_SENTENCE, "call_filename": "call_b"},
    ]
    _, _, calls, _ = build_clause_pool(responses)

    assert calls == ["call_a", "call_a", "call_a", "call_b"]


def test_positions_span_zero_to_one_within_a_multi_clause_response():
    responses = [{"response_text": _THREE_SENTENCES, "call_filename": "call_a"}]
    _, positions, _, _ = build_clause_pool(responses)

    assert positions == [0.0, 0.5, 1.0]


def test_single_clause_response_gets_position_zero_not_a_zero_division():
    """n = max(len(clauses) - 1, 1) exists solely for this case. Dropping the
    guard raises ZeroDivisionError on any response the segmenter returns as one
    clause -- which is most short responses in the sink pool.
    """
    responses = [{"response_text": _ONE_SENTENCE, "call_filename": "call_a"}]
    clauses, positions, calls, _ = build_clause_pool(responses)

    assert len(clauses) == 1
    assert positions == [0.0]
    assert calls == ["call_a"]


def test_positions_restart_per_response_not_across_the_pool():
    """Position is normalised within each response, so two responses each yield
    their own 0.0 -> 1.0 ramp. A pool-wide ramp would corrupt median_position,
    which is what orders milestones in a rubric.
    """
    responses = [
        {"response_text": _THREE_SENTENCES, "call_filename": "call_a"},
        {"response_text": _THREE_SENTENCES, "call_filename": "call_b"},
    ]
    _, positions, _, _ = build_clause_pool(responses)

    assert positions == [0.0, 0.5, 1.0, 0.0, 0.5, 1.0]


def test_empty_response_list_returns_four_empty_lists():
    assert build_clause_pool([]) == ([], [], [], [])


# --- clause -> pair provenance (added 2026-08-12) --------------------------------------
#
# Design: docs/superpowers/specs/2026-08-12-layer-c-profile-rebuild-design.md §3.2.
# Layer C's describe step is blind to the CLIENT TRIGGER, which is why it cannot state a
# move's precondition -- it has never been shown one. Reaching the trigger needs each
# clause to know which PAIR it came from; call_filename is not enough, because one call
# contributes many pairs with different triggers.


def test_every_clause_carries_its_own_source_pair():
    responses = [
        {"response_text": _THREE_SENTENCES, "call_filename": "call_a", "pair_id": 11},
        {"response_text": _ONE_SENTENCE, "call_filename": "call_b", "pair_id": 12},
    ]
    _, _, _, pairs = build_clause_pool(responses)

    assert pairs == [11, 11, 11, 12]


def test_two_responses_from_one_call_stay_distinguishable():
    """THE REASON pair provenance is needed at all. Both responses share a call, so
    clause_calls cannot tell them apart -- but they answer DIFFERENT client turns, and a
    cluster's triggers must be exactly its own members' triggers. Attributing a trigger
    to the wrong clause is how a precondition gets written for a moment that never
    happened."""
    responses = [
        {"response_text": _ONE_SENTENCE, "call_filename": "call_a", "pair_id": 11},
        {"response_text": _ONE_SENTENCE, "call_filename": "call_a", "pair_id": 12},
    ]
    _, _, calls, pairs = build_clause_pool(responses)

    assert calls == ["call_a", "call_a"]   # indistinguishable
    assert pairs == [11, 12]               # distinguishable


def test_a_response_without_a_pair_id_yields_none_rather_than_raising():
    """calibration/replay_layer_c_admitted.py builds its own response dicts. A KeyError
    there would break a harness whose whole purpose is reproducing production exactly,
    and None correctly says "no pair recorded" rather than inventing one."""
    responses = [{"response_text": _ONE_SENTENCE, "call_filename": "call_a"}]
    _, _, _, pairs = build_clause_pool(responses)

    assert pairs == [None]


def test_pair_provenance_does_not_disturb_the_other_three_lists():
    """Behaviour-preservation is the contract: replay_layer_c_admitted's validity rests
    on reproducing Pass 1 byte-for-byte, so adding a return value must change nothing
    about the pool itself."""
    responses = [
        {"response_text": _THREE_SENTENCES, "call_filename": "call_a", "pair_id": 11},
        {"response_text": _ONE_SENTENCE, "call_filename": "call_b", "pair_id": 12},
    ]
    clauses, positions, calls, _ = build_clause_pool(responses)

    assert calls == ["call_a", "call_a", "call_a", "call_b"]
    assert positions == [0.0, 0.5, 1.0, 0.0]
    assert len(clauses) == 4
