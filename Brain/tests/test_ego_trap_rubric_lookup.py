"""Tests for ego_trap/rubric_lookup.py -- benchmark reference selection.

rank_benchmark_responses is exercised against hand-built orthogonal vectors rather
than the real embedder, so these test the RANKING RULE and stay true whatever the model
does to any particular sentence (same reason as test_layer_b_assignment.py).
"""
import numpy as np

from ego_trap import rubric_lookup
from ego_trap.transcript_parser import EgoTrapRole, EgoTrapTurn


def _resp(pair_id, text, is_primary=True):
    return {
        "pair_id": pair_id, "response_text": text,
        "call_filename": "c.txt", "is_primary": is_primary,
    }


def _patch_vectors(mocker, response_vecs, scenario_vec):
    """Make each response's embedding explicit so the cosine ordering is known."""
    mocker.patch.object(
        rubric_lookup.embedder, "embed_document_matrix",
        return_value=np.array(response_vecs, dtype=float),
    )
    mocker.patch.object(
        rubric_lookup, "scenario_vec", return_value=list(scenario_vec)
    )


def test_ranking_prefers_the_most_on_topic_response(mocker):
    """Replaces "ORDER BY pair_id, take the first two", which picked the two OLDEST
    rows by insertion order -- unrelated to how well a response represents the topic."""
    responses = [_resp(1, "off topic"), _resp(2, "on topic"), _resp(3, "middling")]
    _patch_vectors(
        mocker,
        [[0.0, 1.0], [1.0, 0.0], [0.7, 0.7]],
        [1.0, 0.0],
    )
    ranked = rubric_lookup.rank_benchmark_responses(responses, {}, 2)
    assert [r["pair_id"] for r in ranked] == [2, 3]


def test_ranking_attaches_the_similarity_it_ranked_on(mocker):
    responses = [_resp(1, "a"), _resp(2, "b"), _resp(3, "c")]
    _patch_vectors(mocker, [[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]], [1.0, 0.0])
    ranked = rubric_lookup.rank_benchmark_responses(responses, {}, 1)
    assert ranked[0]["scenario_similarity"] > 0.9


def test_ranking_can_choose_a_secondary_label_response(mocker):
    """The multilabel query's whole point: a pair whose PRIMARY key is another scenario
    can still be this scenario's best example, and used to be invisible entirely."""
    responses = [_resp(1, "weak primary", True), _resp(2, "strong secondary", False)]
    _patch_vectors(mocker, [[0.0, 1.0], [1.0, 0.0]], [1.0, 0.0])
    ranked = rubric_lookup.rank_benchmark_responses(responses, {}, 1)
    assert ranked[0]["pair_id"] == 2
    assert ranked[0]["is_primary"] is False


def test_ranking_does_not_embed_when_the_pool_already_fits(mocker):
    """Cheap short-circuit: with <= limit candidates the order cannot matter, so there
    is nothing to rank and no reason to touch the embed cache."""
    embed = mocker.patch.object(rubric_lookup.embedder, "embed_document_matrix")
    responses = [_resp(1, "a"), _resp(2, "b")]
    assert rubric_lookup.rank_benchmark_responses(responses, {}, 2) == responses
    embed.assert_not_called()


def test_ranking_an_empty_pool_is_not_an_error(mocker):
    embed = mocker.patch.object(rubric_lookup.embedder, "embed_document_matrix")
    assert rubric_lookup.rank_benchmark_responses([], {}, 2) == []
    embed.assert_not_called()


def test_ranking_does_not_mutate_the_input_rows(mocker):
    """The caller caches these dicts; adding a similarity key in place would leak a
    stale score into a later scenario's ranking."""
    responses = [_resp(1, "a"), _resp(2, "b"), _resp(3, "c")]
    _patch_vectors(mocker, [[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]], [1.0, 0.0])
    rubric_lookup.rank_benchmark_responses(responses, {}, 2)
    assert all("scenario_similarity" not in r for r in responses)


def test_benchmark_reference_reads_the_multilabel_population(mocker):
    """Must NOT call get_naren_responses_for_scenario -- that WHERE clause is Layer C's
    clause-pool predicate and widening it would change every rubric."""
    multilabel = mocker.patch.object(
        rubric_lookup.storage, "get_responses_for_scenario_multilabel",
        return_value=[_resp(1, "first"), _resp(2, "second")],
    )
    scalar = mocker.patch.object(rubric_lookup.storage, "get_naren_responses_for_scenario")

    text = rubric_lookup.get_benchmark_reference(mocker.Mock(), "scenario_a", {})

    multilabel.assert_called_once()
    scalar.assert_not_called()
    assert text == "first\n\nsecond"


def test_benchmark_reference_caps_at_the_prompt_budget(mocker):
    mocker.patch.object(
        rubric_lookup.storage, "get_responses_for_scenario_multilabel",
        return_value=[_resp(i, f"r{i}") for i in range(1, 6)],
    )
    _patch_vectors(
        mocker,
        [[1.0, 0.0], [0.9, 0.1], [0.5, 0.5], [0.1, 0.9], [0.0, 1.0]],
        [1.0, 0.0],
    )
    text = rubric_lookup.get_benchmark_reference(mocker.Mock(), "s", {})
    assert len(text.split("\n\n")) == rubric_lookup._MAX_BENCHMARK_EXAMPLES


def test_benchmark_reference_with_no_responses_is_empty_not_an_error(mocker):
    mocker.patch.object(
        rubric_lookup.storage, "get_responses_for_scenario_multilabel", return_value=[]
    )
    assert rubric_lookup.get_benchmark_reference(mocker.Mock(), "s", {}) == ""


def test_fetch_rubric_passes_pipeline_version_through(mocker):
    """A consumer cannot interpret a rubric without knowing whether its milestones are
    HDBSCAN clusters or Gemma free-text."""
    mocker.patch.object(
        rubric_lookup.storage, "get_rubric_for_scenario",
        return_value={"rubric_id": 1, "milestones": [], "pipeline_version": "v1"},
    )
    assert rubric_lookup.fetch_rubric(mocker.Mock(), "s")["pipeline_version"] == "v1"


def test_response_window_takes_only_csm_turns_before_the_next_client():
    turns = [
        EgoTrapTurn(0, "C", EgoTrapRole.CLIENT, "What about attribution?", "c"),
        EgoTrapTurn(1, "M", EgoTrapRole.CSM, "Good question.", "c"),
        EgoTrapTurn(2, "O", EgoTrapRole.OTHER_JOVEO, "I can add to that.", "c"),
        EgoTrapTurn(3, "M", EgoTrapRole.CSM, "We track it per source.", "c"),
        EgoTrapTurn(4, "C", EgoTrapRole.CLIENT, "Got it.", "c"),
        EgoTrapTurn(5, "M", EgoTrapRole.CSM, "Anything else?", "c"),
    ]
    window = rubric_lookup.extract_csm_response_window(turns, {"turn_index": 0})
    assert window == "Good question. We track it per source."
