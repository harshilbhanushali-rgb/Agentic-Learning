"""Tests for shared/head_to_head.py -- the pure logic of the pairwise comparison harness.

No Gemma, no DB, no embeddings. Everything here is the arithmetic a silent bug would render
meaningless, which is exactly the split shared/cluster_evidence.py and shared/topic_grouping.py
already follow.

Design spec: docs/superpowers/specs/2026-08-13-head-to-head-comparison-design.md
"""
import math
import random

import pytest

from shared.head_to_head import (
    adjacent_rank_pair,
    assign_swap_batches,
    by_decile,
    length_matched,
    moments_sha,
    normalize_winner,
    order_average,
    swap_agreement,
    win_rate,
)


# ---------------------------------------------------------------------------------------
# T1.1 -- swap-batch assignment
# ---------------------------------------------------------------------------------------

class TestAssignSwapBatches:
    def test_every_item_appears_exactly_twice_once_per_order(self):
        batches = assign_swap_batches(["a", "b", "c"], batch_size=2, seed=1)
        seen = [entry for batch in batches for entry in batch]
        assert sorted(seen) == sorted(
            [("a", "AB"), ("a", "BA"), ("b", "AB"), ("b", "BA"), ("c", "AB"), ("c", "BA")]
        )

    def test_no_batch_holds_both_orders_of_one_item(self):
        """The load-bearing guarantee. A judge shown the same pair twice in one call is
        consistent from MEMORY, and C1 would report that memory as reliability."""
        batches = assign_swap_batches(["a", "b"], batch_size=99, seed=7)
        for batch in batches:
            ids = [item_id for item_id, _ in batch]
            assert len(ids) == len(set(ids))

    def test_the_guarantee_holds_across_200_random_shapes(self):
        rng = random.Random(20260813)
        for _ in range(200):
            n = rng.randint(1, 40)
            batch_size = rng.randint(1, 12)
            items = [f"i{k}" for k in range(n)]
            batches = assign_swap_batches(items, batch_size=batch_size, seed=rng.randint(0, 10**6))

            flat = [e for b in batches for e in b]
            assert len(flat) == 2 * n
            assert sorted(flat) == sorted([(i, o) for i in items for o in ("AB", "BA")])
            for b in batches:
                assert len(b) <= batch_size
                ids = [i for i, _ in b]
                assert len(ids) == len(set(ids))

    def test_is_deterministic_for_one_seed(self):
        assert assign_swap_batches(list("abcdef"), 3, seed=42) == \
               assign_swap_batches(list("abcdef"), 3, seed=42)

    def test_different_seeds_shuffle_differently(self):
        a = assign_swap_batches([f"i{k}" for k in range(30)], 4, seed=1)
        b = assign_swap_batches([f"i{k}" for k in range(30)], 4, seed=2)
        assert a != b

    def test_empty_input_yields_no_batches(self):
        assert assign_swap_batches([], batch_size=5, seed=1) == []

    def test_rejects_duplicate_item_ids(self):
        """A duplicate id would silently double one item's weight in every rate."""
        with pytest.raises(ValueError):
            assign_swap_batches(["a", "a"], batch_size=2, seed=1)


# ---------------------------------------------------------------------------------------
# T1.2 -- normalising a slot verdict, and averaging the two orders
# ---------------------------------------------------------------------------------------

class TestNormalizeWinner:
    def test_ab_order_maps_slot_one_to_a(self):
        assert normalize_winner("AB", "1") == "A"
        assert normalize_winner("AB", "2") == "B"

    def test_ba_order_maps_slot_one_to_b(self):
        """The whole point of the swap: in BA the sides are physically exchanged."""
        assert normalize_winner("BA", "1") == "B"
        assert normalize_winner("BA", "2") == "A"

    def test_tie_passes_through_either_order(self):
        assert normalize_winner("AB", "tie") == "tie"
        assert normalize_winner("BA", "tie") == "tie"

    def test_unknown_verdict_raises_rather_than_defaulting(self):
        """A model returning '3' or 'Response 1' must fail loudly. Coercing it to a tie
        would bury a parse failure inside the tie share."""
        with pytest.raises(ValueError):
            normalize_winner("AB", "3")


class TestOrderAverage:
    def test_agreement_yields_that_side(self):
        assert order_average("A", "A") == "A"
        assert order_average("B", "B") == "B"

    def test_disagreement_is_a_tie_not_a_coin_flip(self):
        """A judge that flips when the layout flips has told us nothing about this item."""
        assert order_average("A", "B") == "tie"
        assert order_average("B", "A") == "tie"

    def test_one_decisive_order_carries_the_item(self):
        """Not a contradiction -- one order was simply less decisive."""
        assert order_average("A", "tie") == "A"
        assert order_average("tie", "B") == "B"

    def test_both_ties_stay_a_tie(self):
        assert order_average("tie", "tie") == "tie"


# ---------------------------------------------------------------------------------------
# T1.2 -- win rates
# ---------------------------------------------------------------------------------------

class TestWinRate:
    def test_counts_only_decisive_items_in_the_denominator(self):
        r = win_rate(["A", "A", "B", "tie"], side="A")
        assert r["n_total"] == 4
        assert r["n_decisive"] == 3
        assert r["rate"] == pytest.approx(2 / 3)
        assert r["tie_share"] == pytest.approx(0.25)

    def test_rate_is_none_when_everything_tied(self):
        """0.0 would read as 'lost every comparison', which is a different claim."""
        r = win_rate(["tie", "tie"], side="A")
        assert r["rate"] is None
        assert r["n_decisive"] == 0
        assert r["tie_share"] == 1.0

    def test_side_b_is_the_complement_of_side_a(self):
        outcomes = ["A", "B", "B", "tie"]
        assert win_rate(outcomes, "A")["rate"] + win_rate(outcomes, "B")["rate"] == \
            pytest.approx(1.0)

    def test_empty_input_reports_no_rate(self):
        r = win_rate([], side="A")
        assert r["rate"] is None and r["n_total"] == 0


# ---------------------------------------------------------------------------------------
# T1.3 -- C1 agreement
# ---------------------------------------------------------------------------------------

class TestSwapAgreement:
    def test_all_consistent_scores_one(self):
        assert swap_agreement([("A", "A"), ("B", "B")])["agreement"] == 1.0

    def test_all_flipped_scores_zero(self):
        s = swap_agreement([("A", "B"), ("B", "A")])
        assert s["agreement"] == 0.0
        assert s["flip_rate"] == 1.0

    def test_both_tie_items_are_excluded_not_counted_as_agreement(self):
        """Two ties agree trivially. Counting them would let an indecisive judge pass C1."""
        s = swap_agreement([("A", "A"), ("tie", "tie")])
        assert s["n_scored"] == 1
        assert s["agreement"] == 1.0
        assert s["both_tie_share"] == pytest.approx(0.5)

    def test_one_decisive_one_tie_is_not_agreement_but_is_not_a_flip(self):
        s = swap_agreement([("A", "tie")])
        assert s["n_scored"] == 1
        assert s["agreement"] == 0.0
        assert s["flip_rate"] == 0.0

    def test_reports_nothing_when_every_item_double_tied(self):
        s = swap_agreement([("tie", "tie")])
        assert s["agreement"] is None and s["n_scored"] == 0


# ---------------------------------------------------------------------------------------
# T1.4 -- C2 adjacent-rank pair selection
# ---------------------------------------------------------------------------------------

class TestAdjacentRankPair:
    def test_picks_the_tightest_adjacent_pair(self):
        # ranks by similarity: 0.90, 0.88, 0.60, 0.59 -> the 0.60/0.59 pair is tightest
        sims = [0.90, 0.88, 0.60, 0.59]
        assert adjacent_rank_pair(sims, tolerance=0.05) == (2, 3)

    def test_returns_the_higher_similarity_index_first(self):
        hi, lo = adjacent_rank_pair([0.50, 0.71, 0.70], tolerance=0.05)
        assert (hi, lo) == (1, 2)

    def test_returns_none_when_no_adjacent_pair_is_within_tolerance(self):
        assert adjacent_rank_pair([0.90, 0.50, 0.10], tolerance=0.01) is None

    def test_returns_none_with_fewer_than_two_candidates(self):
        assert adjacent_rank_pair([0.9], tolerance=0.1) is None
        assert adjacent_rank_pair([], tolerance=0.1) is None

    def test_only_adjacent_ranks_qualify(self):
        """0.80 and 0.79 are within tolerance but rank 1 and rank 3 are not adjacent --
        pairing them would hand the judge a candidate the retrieval never ranked second."""
        assert adjacent_rank_pair([0.80, 0.60, 0.79], tolerance=0.02) == (0, 2)


# ---------------------------------------------------------------------------------------
# T1.5 -- stratifiers
# ---------------------------------------------------------------------------------------

class TestByDecile:
    def test_recovers_a_rate_that_differs_between_strata(self):
        # low half always loses, high half always wins
        values = list(range(20))
        outcomes = ["B"] * 10 + ["A"] * 10
        strata = by_decile(outcomes, values, side="A", bins=2)
        assert strata[0]["rate"] == 0.0
        assert strata[1]["rate"] == 1.0
        assert strata[0]["n"] == strata[1]["n"] == 10

    def test_rejects_mismatched_lengths(self):
        with pytest.raises(ValueError):
            by_decile(["A"], [1.0, 2.0], side="A", bins=2)

    def test_a_stratum_with_no_decisive_item_reports_no_rate(self):
        strata = by_decile(["tie", "A"], [0.0, 1.0], side="A", bins=2)
        assert strata[0]["rate"] is None
        assert strata[1]["rate"] == 1.0


class TestLengthMatched:
    def test_keeps_only_pairs_within_the_log_ratio_band(self):
        # log(100/100)=0 keep; log(200/100)=0.69 drop; log(110/100)=0.095 keep
        keep = length_matched([100, 200, 110], [100, 100, 100], band=0.25)
        assert keep == [0, 2]

    def test_band_is_symmetric_in_direction(self):
        assert length_matched([100], [200], band=0.25) == []
        assert length_matched([200], [100], band=0.25) == []
        assert length_matched([100], [200], band=0.75) == [0]

    def test_zero_length_never_silently_passes(self):
        """log(0) is undefined; an empty response must be excluded, not treated as matched."""
        assert length_matched([0], [100], band=10.0) == []


# ---------------------------------------------------------------------------------------
# T1.6 -- content hash of the frozen moment set
# ---------------------------------------------------------------------------------------

class TestMomentsSha:
    def _m(self, tid, trig, resp):
        return {"item_id": tid, "trigger_text": trig, "csm_response": resp,
                "naren_response": "x", "cosine": 0.7}

    def test_is_insensitive_to_list_order(self):
        a = [self._m("1", "t1", "r1"), self._m("2", "t2", "r2")]
        assert moments_sha(a) == moments_sha(list(reversed(a)))

    def test_is_insensitive_to_key_order(self):
        a = [{"item_id": "1", "trigger_text": "t", "csm_response": "r"}]
        b = [{"csm_response": "r", "trigger_text": "t", "item_id": "1"}]
        assert moments_sha(a) == moments_sha(b)

    def test_changes_when_any_text_changes(self):
        base = [self._m("1", "t1", "r1")]
        assert moments_sha(base) != moments_sha([self._m("1", "t1", "r1-EDITED")])
        assert moments_sha(base) != moments_sha([self._m("1", "t1-EDITED", "r1")])

    def test_changes_when_an_item_is_added(self):
        base = [self._m("1", "t1", "r1")]
        assert moments_sha(base) != moments_sha(base + [self._m("2", "t2", "r2")])

    def test_is_stable_across_calls(self):
        m = [self._m("1", "t", "r")]
        assert moments_sha(m) == moments_sha(m)


# ---------------------------------------------------------------------------------------
# T1.7 -- the judge prompt. Its invariants ARE the instrument, so they are pinned here
# rather than left to survive the next edit on trust.
# ---------------------------------------------------------------------------------------

class TestHeadToHeadPrompt:
    def _rendered(self):
        from shared.prompts import PROMPT_HEAD_TO_HEAD_BATCH
        return PROMPT_HEAD_TO_HEAD_BATCH.format(items_block="<ITEMS>")

    def test_labels_the_two_sides_by_slot_only(self):
        text = self._rendered()
        assert "Response 1" in text and "Response 2" in text

    def test_never_names_a_participant_or_a_role(self):
        """Blinding IS the instrument. One leaked 'Naren' and the judge stops comparing
        quality and starts identifying the expert."""
        low = self._rendered().lower()
        for leak in ("naren", "csm", "expert", "junior", "coach", "benchmark"):
            assert leak not in low, f"identity leak in the judge prompt: {leak!r}"

    def test_demands_a_verdict_on_every_item_never_a_subset(self):
        """The generalising lesson from the objective function's failure: its prompt
        instructed sparsity, and 'return a subset' invites picking a top few and stopping."""
        low = self._rendered().lower()
        assert "every item" in low
        assert "exactly one object per item" in low

    def test_offers_exactly_the_three_verdicts_the_maths_expects(self):
        text = self._rendered()
        for verdict in ('"1"', '"2"', '"tie"'):
            assert verdict in text

    def test_does_not_try_to_instruct_away_the_length_bias(self):
        """Length is handled by the length-matched stratum, not by asking nicely --
        three wording passes have already failed in this codebase. An instruction here
        would also be an unmeasured change to the judge."""
        low = self._rendered().lower()
        assert "longer" not in low and "length" not in low

    def test_carries_the_items_block_placeholder(self):
        from shared.prompts import PROMPT_HEAD_TO_HEAD_BATCH
        assert "{items_block}" in PROMPT_HEAD_TO_HEAD_BATCH
