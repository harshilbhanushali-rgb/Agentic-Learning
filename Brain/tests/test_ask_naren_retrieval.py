"""ask_naren/retrieval.py -- the rules a wrong answer would come from, on hand-built
vectors. Same discipline as tests/test_layer_b_assignment.py: exercise the RULE
(nearest-neighbour selection, coachable-only filtering, dedup-before-search), never a
live embedding."""
import numpy as np
import pytest

from ask_naren import retrieval


def _pair(pair_id, trigger, response, filename="a.txt", scenario_key="budget_disclosure"):
    return {"pair_id": pair_id, "trigger_text": trigger, "response_text": response,
            "call_filename": filename, "scenario_key": scenario_key}


def _scn(key, coachable=True, kind="scenario"):
    return {"scenario_key": key, "is_coachable": coachable, "cluster_kind": kind}


# -- the coachable restriction ----------------------------------------------------------

def test_coachable_scenario_keys_drops_sinks():
    scenarios = [_scn("budget_disclosure"), _scn("conversational_fillers", False, "mechanics")]
    assert retrieval.coachable_scenario_keys(scenarios) == ["budget_disclosure"]


def test_cluster_kind_alone_does_not_decide_coachability():
    """is_coachable is the load-bearing field -- a graduated sink whose cluster_kind still
    says mechanics is coachable. Delegates to shared.relative_match.is_sink_flags -- Brain's
    single definition of "sink" -- so Ask Naren cannot invent a second one."""
    assert retrieval.coachable_scenario_keys([_scn("odd", True, "mechanics")]) == ["odd"]


# -- dedup before search ---------------------------------------------------------------

def test_content_duplicate_under_another_filename_is_dropped():
    """The measured corpus hazard: 64 of 6528 coachable rows are byte-identical pairs
    ingested twice under two different calls.filename values. Un-deduped, a situation can
    match the same content twice and a held-out item can retrieve its own twin."""
    pairs = [_pair(1, "client asks about budget", "here is how I frame it", "call_a.txt"),
             _pair(2, "client asks about budget", "here is how I frame it", "call_b.txt")]
    kept = retrieval.dedupe_pairs(pairs)
    assert [p["pair_id"] for p in kept] == [1]


def test_dedup_keys_on_content_not_filename():
    """Two genuinely different pairs from the SAME call must both survive -- dedup is a
    content rule, and collapsing by filename would silently shrink the pool."""
    pairs = [_pair(1, "budget question", "answer one", "call_a.txt"),
             _pair(2, "timeline question", "answer two", "call_a.txt")]
    assert len(retrieval.dedupe_pairs(pairs)) == 2


def test_dedup_ignores_case_and_whitespace_differences():
    pairs = [_pair(1, "Client   asks about BUDGET", "Here is how I frame it"),
             _pair(2, "client asks about budget", "here  is how i frame it", "other.txt")]
    assert len(retrieval.dedupe_pairs(pairs)) == 1


def test_a_pair_differing_only_in_response_is_kept():
    pairs = [_pair(1, "same trigger", "response one"),
             _pair(2, "same trigger", "response two", "other.txt")]
    assert len(retrieval.dedupe_pairs(pairs)) == 2


# -- nearest-neighbour selection --------------------------------------------------------

def test_top1_returns_the_nearest_pair_by_cosine():
    pairs = [_pair(1, "budget", "b"), _pair(2, "timeline", "t")]
    vectors = np.array([[1.0, 0.0], [0.0, 1.0]])
    pool = retrieval.RetrievalPool(pairs, vectors)
    match = pool.top1(np.array([0.9, 0.1]))
    assert match.pair["pair_id"] == 1
    assert match.cosine == pytest.approx(0.9939, abs=1e-3)


def test_a_long_pool_vector_cannot_win_on_magnitude_alone():
    """Rows are L2-normalized on the way in. Without that, ranking by raw dot product hands
    the match to whichever stored vector happens to be longest, which is not similarity."""
    pairs = [_pair(1, "near", "b"), _pair(2, "far but long", "t")]
    vectors = np.array([[1.0, 0.0], [0.0, 50.0]])
    pool = retrieval.RetrievalPool(pairs, vectors)
    assert pool.top1(np.array([1.0, 0.2])).pair["pair_id"] == 1


def test_reported_cosine_is_a_true_cosine_for_an_unnormalized_query():
    """The query is normalized too. Ranking survives an unnormalized query (a positive
    scalar cannot reorder an argmax) but the REPORTED number would be a dot product wearing
    a cosine's name -- and that number is what a caller reads as match strength."""
    pool = retrieval.RetrievalPool([_pair(1, "x", "y")], np.array([[1.0, 0.0]]))
    assert pool.top1(np.array([7.0, 0.0])).cosine == pytest.approx(1.0)


def test_pool_rejects_a_vector_count_that_disagrees_with_the_pairs():
    with pytest.raises(ValueError):
        retrieval.RetrievalPool([_pair(1, "x", "y")], np.array([[1.0, 0.0], [0.0, 1.0]]))


def test_an_empty_pool_raises_rather_than_answering_from_nothing():
    pool = retrieval.RetrievalPool([], np.empty((0, 2)))
    with pytest.raises(ValueError):
        pool.top1(np.array([1.0, 0.0]))
