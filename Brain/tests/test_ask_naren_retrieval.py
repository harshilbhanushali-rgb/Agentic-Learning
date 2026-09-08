"""ask_naren/retrieval.py -- the rules a wrong answer would come from, on hand-built
vectors. Same discipline as tests/test_layer_b_assignment.py: exercise the RULE
(nearest-neighbour selection, coachable-only filtering, dedup-before-search), never a
live embedding."""
import numpy as np
import pytest

from ask_naren import retrieval, vector_store


def _pair(pair_id, trigger, response, filename="a.txt", scenario_key="budget_disclosure"):
    return {"pair_id": pair_id, "trigger_text": trigger, "response_text": response,
            "call_filename": filename, "scenario_key": scenario_key}


def _scn(key, coachable=True, kind="scenario"):
    return {"scenario_key": key, "is_coachable": coachable, "cluster_kind": kind}


class _FakeStore:
    """A ranking handed in whole, so the POST-FILTER can be tested without a network.

    The live store is Pinecone (ADR 0008) and is deliberately not mocked anywhere: a mock
    would assert only that the SDK is called as imagined, which is the belief most likely
    to be wrong. What is worth pinning is what the pool does with a ranking it is given --
    which identifiers it refuses to answer from, and in what order -- and that is exactly
    what this fake supplies.
    """

    def __init__(self, ranked):
        self.ranked = list(ranked)
        self.asked_for = []

    def search(self, query_vec, top_k):
        self.asked_for.append(top_k)
        return self.ranked[:top_k]


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


# -- the candidate shortlist (issue #8) -------------------------------------------------

def test_topk_returns_the_k_nearest_pairs_ranked_nearest_first():
    """Rank order is the whole point of the shortlist: #8's premise is that the right
    moment is usually PRESENT but not first, so a caller must be able to see position."""
    pairs = [_pair(1, "budget", "b"), _pair(2, "timeline", "t"),
             _pair(3, "half way between", "h", "c.txt")]
    vectors = np.array([[1.0, 0.0], [0.0, 1.0], [0.707, 0.707]])
    pool = retrieval.RetrievalPool(pairs, vectors)
    got = pool.topk(np.array([0.9, 0.1]), 2)
    assert [m.pair["pair_id"] for m in got] == [1, 3]


def test_topk_returns_the_whole_pool_when_k_exceeds_it():
    """A caller must not assume len(...) == k. The live pool is ~6.5k so k=5 never runs
    short there, but a masked or filtered view can, and padding a shortlist with a repeated
    or absent candidate would put a moment in the prompt that retrieval never chose."""
    pool = retrieval.RetrievalPool([_pair(1, "x", "y")], np.array([[1.0, 0.0]]))
    assert len(pool.topk(np.array([1.0, 0.0]), 5)) == 1


# -- resolving a carried identifier (issue #16) -------------------------------------------

def test_a_carried_pair_id_resolves_without_searching_for_it():
    """How a follow-up grounds under ADR 0006: the thread supplies an IDENTIFIER and the
    text comes from the pool already in memory. Nothing is embedded and nothing is ranked,
    which is exactly why carrying an identifier is not the dilution the ADR forbids."""
    pairs = [_pair(1, "budget", "b"), _pair(2, "timeline", "t")]
    pool = retrieval.RetrievalPool(pairs, np.array([[1.0, 0.0], [0.0, 1.0]]))
    assert pool.by_pair_id(2) is pairs[1]


def test_a_pair_id_the_pool_no_longer_holds_resolves_to_nothing():
    """A real case, not a defensive nicety: the pool is loaded once at startup, and a
    pipeline re-run between restarts can retire a pair an open thread still points at."""
    pool = retrieval.RetrievalPool([_pair(1, "x", "y")], np.array([[1.0, 0.0]]))
    assert pool.by_pair_id(999_999) is None


# -- the store seam: Pinecone ranks, the pool authorises (ADR 0008) ---------------------

def test_a_ranked_identifier_the_pool_does_not_hold_is_skipped():
    """The authorisation half of ADR 0008. Pinecone holds whatever the pipeline shipped --
    measured at 1.92x the coachable pool -- so a ranking WILL contain identifiers the pool
    deliberately excludes. Skipping is the mechanism that keeps the pool the authority;
    returning them would answer a CSM from a scenario Ask Naren is not allowed to coach."""
    pairs = [_pair(1, "budget", "b")]
    store = _FakeStore([("999999", 0.95), ("1", 0.81)])
    pool = retrieval.RetrievalPool(pairs, store=store)
    got = pool.topk(np.array([1.0, 0.0]), 2)
    assert [m.pair["pair_id"] for m in got] == [1]


def test_a_content_duplicate_the_pool_dropped_cannot_be_retrieved_through_the_store():
    """The dedup half, and the reason the post-filter is a CORRECTNESS gate not a nicety.

    The corpus holds transcripts ingested twice under two filenames -- 32 byte-identical
    pairs across 15 scenarios. dedupe_pairs drops the second copy, but BOTH pair_ids are in
    Pinecone carrying coachable scenario keys, so the metadata filter admits both. Only this
    skip stops two identical exchanges competing as separate neighbours for one situation."""
    kept = retrieval.dedupe_pairs([_pair(1, "same", "text"), _pair(2, "same", "text", "b.txt")])
    assert [p["pair_id"] for p in kept] == [1]
    store = _FakeStore([("2", 0.99), ("1", 0.90)])
    pool = retrieval.RetrievalPool(kept, store=store)
    got = pool.topk(np.array([1.0, 0.0]), 5)
    assert [m.pair["pair_id"] for m in got] == [1]


def test_the_rank_order_is_the_stores_and_is_not_recomputed():
    """Ranking moved OUT of the service (ADR 0008). If the pool re-sorted, there would be
    two ranking implementations able to disagree silently -- the thing RetrievalPool.top1
    already delegates to topk to avoid."""
    pairs = [_pair(1, "a", "a"), _pair(2, "b", "b"), _pair(3, "c", "c")]
    store = _FakeStore([("3", 0.71), ("1", 0.70), ("2", 0.69)])
    pool = retrieval.RetrievalPool(pairs, store=store)
    assert [m.pair["pair_id"] for m in pool.topk(np.array([1.0, 0.0]), 3)] == [3, 1, 2]


def test_the_reported_cosine_is_the_stores_score_unchanged():
    """`match.cosine` is read against ADR 0005's measured bands, so it must keep meaning
    the same number. The stored vectors are bit-identical to what the service used to embed
    (cos = 1.000000 on 24/24, ADR 0008), so passing the score through is what preserves it."""
    pool = retrieval.RetrievalPool([_pair(1, "x", "y")], store=_FakeStore([("1", 0.8137)]))
    assert pool.top1(np.array([1.0, 0.0])).cosine == pytest.approx(0.8137)


def test_a_string_identifier_from_the_store_resolves_against_an_integer_pair_id():
    """The silent-total-failure case. Pinecone keys records as `trigger_<id>` strings while
    Postgres yields an integer pair_id; unnormalised, EVERY post-filter lookup misses, the
    pool authorises nothing and Ask Naren declines every situation -- which looks like a
    quality problem, not a type bug. Pinned so it cannot ship."""
    pool = retrieval.RetrievalPool([_pair(7, "x", "y")], store=_FakeStore([("7", 0.5)]))
    assert pool.top1(np.array([1.0, 0.0])).pair["pair_id"] == 7


def test_a_run_of_unauthorised_hits_does_not_starve_the_result():
    """Why the search over-fetches. Skipping is only safe if the ranking asked for is deeper
    than k -- otherwise a handful of duplicates or retired pairs at the top of the ranking
    would make Ask Naren decline a situation it can answer."""
    junk = [(str(900000 + i), 0.99 - i / 1000) for i in range(24)]
    store = _FakeStore(junk + [("1", 0.5)])
    pool = retrieval.RetrievalPool([_pair(1, "x", "y")], store=store)
    assert [m.pair["pair_id"] for m in pool.topk(np.array([1.0, 0.0]), 1)] == [1]


def test_fewer_than_k_authorised_hits_returns_what_was_found():
    """Same contract the in-memory path already had: a caller must not assume len(...) == k.
    Padding a shortlist with an absent or repeated candidate would put a moment in the
    prompt that retrieval never chose."""
    store = _FakeStore([("1", 0.9), ("999999", 0.8)])
    pool = retrieval.RetrievalPool([_pair(1, "x", "y")], store=store)
    assert len(pool.topk(np.array([1.0, 0.0]), 5)) == 1


def test_an_empty_pool_with_a_store_still_refuses_to_answer_from_nothing():
    pool = retrieval.RetrievalPool([], store=_FakeStore([]))
    with pytest.raises(ValueError):
        pool.top1(np.array([1.0, 0.0]))


def test_a_pool_cannot_be_given_both_a_matrix_and_a_store():
    """Two sources of ranking is the ambiguity ADR 0008's rollback constant switches
    between; a pool holding both would make which one is live a matter of reading order."""
    with pytest.raises(ValueError):
        retrieval.RetrievalPool([_pair(1, "x", "y")], np.array([[1.0, 0.0]]),
                                store=_FakeStore([("1", 0.9)]))


def test_a_pool_needs_either_a_matrix_or_a_store():
    with pytest.raises(ValueError):
        retrieval.RetrievalPool([_pair(1, "x", "y")])


# -- the in-memory store, which is what makes rollback one line ------------------------

def test_the_in_memory_store_ranks_by_cosine_and_reports_bare_identifiers():
    """The rollback path (ADR 0008) and the reason the suite needs no network. It must speak
    the SAME contract as the Pinecone store -- bare string identifiers, nearest first --
    or a rollback would swap in a store the pool cannot post-filter."""
    store = vector_store.InMemoryTriggerStore([1, 2], np.array([[1.0, 0.0], [0.0, 1.0]]))
    got = store.search(np.array([0.9, 0.1]), 2)
    assert [pair_id for pair_id, _ in got] == ["1", "2"]
    assert got[0][1] == pytest.approx(0.9939, abs=1e-3)


def test_the_in_memory_store_rejects_a_vector_count_that_disagrees():
    with pytest.raises(ValueError):
        vector_store.InMemoryTriggerStore([1], np.array([[1.0, 0.0], [0.0, 1.0]]))


def test_a_score_above_one_is_not_reported_as_a_cosine():
    """Measured, not hypothetical: querying the index with a STORED unit vector returns its
    own record at up to 1.00135. Nothing above 1 is a cosine, and `Match.cosine` is read
    against ADR 0005's measured bands, so the store clamps rather than hand a caller a
    number that cannot exist. The approximation itself is characterised in
    ask-naren/audit/equivalence_vector_store.py, not hidden here."""
    assert vector_store._clamp_cosine(1.00135) == 1.0
    assert vector_store._clamp_cosine(-1.2) == -1.0
    assert vector_store._clamp_cosine(0.8137) == pytest.approx(0.8137)
