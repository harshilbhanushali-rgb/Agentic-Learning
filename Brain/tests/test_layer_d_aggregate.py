"""layer_d/aggregate.py -- shrinkage, dead checks, ranking, report text. Pure math."""
import pytest

from layer_d.aggregate import (
    DeadCheck, Gap, MoveRate, cohort_prior, dead_checks, format_priorities,
    rank_gaps, shrunk_rate,
)


def mr(pb, mv, attempts, hits, partials=0):
    return MoveRate(playbook_id=pb, move_id=mv, attempts=attempts, hits=hits,
                    partials=partials)


# ------------------------------------------------------------------- shrinkage

def test_shrunk_rate_is_prior_at_zero_attempts():
    assert shrunk_rate(mr(1, "M1", 0, 0), prior_rate=0.4, prior_strength=5) == 0.4


def test_shrunk_rate_approaches_raw_rate_as_attempts_grow():
    sparse = shrunk_rate(mr(1, "M1", 2, 2), 0.2, 5)      # raw 1.0
    dense = shrunk_rate(mr(1, "M1", 200, 200), 0.2, 5)   # raw 1.0
    assert sparse < dense < 1.0
    assert dense > 0.97


def test_partial_hits_count_half():
    r = mr(1, "M1", 10, 2, partials=4)
    assert r.weighted == 4.0
    assert r.raw_rate == pytest.approx(0.4)


def test_cohort_prior_is_attempt_weighted():
    # 40-attempt rater at 0.5 must dominate a 2-attempt rater at 0.0
    prior = cohort_prior([mr(1, "M1", 40, 20), mr(1, "M1", 2, 0)])
    assert prior == pytest.approx(20 / 42)


def test_cohort_prior_zero_attempts_is_zero_not_nan():
    assert cohort_prior([mr(1, "M1", 0, 0)]) == 0.0


# ----------------------------------------------------------------- dead checks

def test_dead_check_fires_below_floor_with_enough_attempts():
    [d] = dead_checks([mr(1, "M2", 10, 2)], floor=0.5, min_attempts=8)
    assert (d.playbook_id, d.move_id, d.naren_rate) == (1, "M2", 0.2)


def test_unmeasured_check_is_not_dead():
    assert dead_checks([mr(1, "M2", 3, 0)], floor=0.5, min_attempts=8) == []


def test_check_naren_passes_is_not_dead():
    assert dead_checks([mr(1, "M2", 10, 8)], floor=0.5, min_attempts=8) == []


# --------------------------------------------------------------------- ranking

NAREN = [mr(1, "M1", 9, 8), mr(1, "M2", 9, 7), mr(1, "M3", 10, 1)]  # M3 is dead @0.5


def test_rank_gaps_orders_by_size_and_excludes_dead():
    csm = {"madhu": [mr(1, "M1", 12, 1), mr(1, "M2", 12, 8), mr(1, "M3", 12, 0)]}
    ranked, dead = rank_gaps(csm, NAREN, prior_strength=5.0, min_attempts=8,
                             dead_floor=0.5)
    gaps = ranked["madhu"]
    assert [g.move_id for g in gaps] == ["M1", "M2"]      # M3 excluded as dead
    assert gaps[0].size > gaps[1].size
    assert [d.move_id for d in dead] == ["M3"]


def test_gap_requires_both_sides_measured():
    csm = {"madhu": [mr(1, "M1", 3, 0)]}                   # below min_attempts
    ranked, _ = rank_gaps(csm, NAREN, prior_strength=5.0, min_attempts=8,
                          dead_floor=0.5)
    assert ranked["madhu"] == []


def test_gap_ignores_moves_with_no_benchmark():
    csm = {"madhu": [mr(2, "M1", 20, 0)]}                  # playbook 2 never measured
    ranked, _ = rank_gaps(csm, NAREN, prior_strength=5.0, min_attempts=8,
                          dead_floor=0.5)
    assert ranked["madhu"] == []


def test_shrinkage_prior_pools_across_the_csm_cohort():
    # Two raters on the same cell: the sparse one is pulled toward the pooled rate.
    csm = {
        "a": [mr(1, "M1", 40, 20)],    # raw 0.5, dominates the prior
        "b": [mr(1, "M1", 8, 0)],      # raw 0.0
    }
    ranked, _ = rank_gaps(csm, NAREN, prior_strength=5.0, min_attempts=8,
                          dead_floor=0.5)
    [gap_b] = ranked["b"]
    assert gap_b.csm_rate_raw == 0.0
    assert gap_b.csm_rate_shrunk > 0.0          # pulled up by the cohort prior


# ------------------------------------------------------------- pairwise ranking

from layer_d.aggregate import (  # noqa: E402
    format_pairwise_priorities, group_by_scenario, rank_pairwise,
)


def test_rank_pairwise_orders_by_shrunken_loss_share():
    csm = {"m": [mr(1, "M1", 12, 2, partials=2),      # match-or-beat 3/12 = 0.25
                 mr(1, "M2", 12, 8, partials=2)]}     # match-or-beat 9/12 = 0.75
    ranked, blurry = rank_pairwise(csm, prior_strength=0.0, min_attempts=8)
    gaps = ranked["m"]
    assert [g["move_id"] for g in gaps] == ["M1", "M2"]
    assert gaps[0]["gap"] == pytest.approx(0.75)
    assert gaps[0]["losses"] == 8
    assert blurry == []


def test_rank_pairwise_needs_min_attempts():
    ranked, _ = rank_pairwise({"m": [mr(1, "M1", 3, 0)]},
                              prior_strength=0.0, min_attempts=8)
    assert ranked["m"] == []


def test_rank_pairwise_flags_blurry_axes_and_excludes_them():
    # 10 of 12 verdicts are 'equal' -> the judge cannot separate anyone here
    csm = {"m": [mr(1, "M1", 12, 1, partials=10)]}
    ranked, blurry = rank_pairwise(csm, prior_strength=0.0, min_attempts=8)
    assert ranked["m"] == []
    [b] = blurry
    assert (b["playbook_id"], b["move_id"]) == (1, "M1")
    assert b["tie_share"] == pytest.approx(10 / 12, abs=1e-3)


def test_rank_pairwise_shrinks_toward_cohort():
    csm = {"a": [mr(1, "M1", 40, 20)], "b": [mr(1, "M1", 8, 0)]}
    ranked, _ = rank_pairwise(csm, prior_strength=5.0, min_attempts=8)
    [gap_b] = ranked["b"]
    assert gap_b["match_or_beat_raw"] == 0.0
    assert gap_b["match_or_beat_shrunk"] > 0.0


def test_format_pairwise_priorities_renders_record_and_benchmark_quote():
    gaps = [{"rater_id": "m", "playbook_id": 1, "move_id": "M1", "attempts": 14,
             "wins": 1, "equals": 2, "losses": 11,
             "match_or_beat_raw": 0.14, "match_or_beat_shrunk": 0.18, "gap": 0.82}]
    text = format_pairwise_priorities(
        "Madhumita", gaps,
        {(1, "M1"): {"scenario_key": "app_volume", "name": "Track down-funnel",
                     "criterion": "Confirm UTM tags", "naren_quote": "do you have UTM tags?"}})
    assert "won 1, equal 2, lost 11 of 14" in text
    assert "18%" in text and "UTM tags" in text
    assert "score" not in text.lower()


def test_format_pairwise_priorities_empty_says_so():
    assert "No rankable gaps" in format_pairwise_priorities("M", [], {})


# ---------------------------------------------------------- scenario grouping

MOVE_META = {
    (1, "M1"): {"scenario_key": "attribution", "name": "Explain mechanisms"},
    (1, "M2"): {"scenario_key": "attribution", "name": "Diagnose discrepancies"},
    (2, "M1"): {"scenario_key": "publisher_mgmt", "name": "Guide platform UI"},
}


def test_group_by_scenario_groups_moves_and_orders_by_worst_gap():
    # Globally sorted by gap desc (rank_pairwise's contract): attribution's M2 is
    # its worst move and appears before its M1; publisher_mgmt is worse overall
    # than attribution's WORST move, so it must rank first as its own group.
    gaps = [
        {"playbook_id": 2, "move_id": "M1", "gap": 0.90},
        {"playbook_id": 1, "move_id": "M2", "gap": 0.77},
        {"playbook_id": 1, "move_id": "M1", "gap": 0.20},
    ]
    groups = group_by_scenario(gaps, MOVE_META)
    assert [g["scenario_key"] for g in groups] == ["publisher_mgmt", "attribution"]
    assert groups[1]["worst_gap"] == 0.77
    assert [m["move_id"] for m in groups[1]["moves"]] == ["M2", "M1"]


def test_group_by_scenario_worst_move_not_averaged():
    # A scenario with one severe move (0.90) and one fine move (0.10) must still
    # rank ahead of a scenario that is uniformly mediocre (0.40, 0.40) -- an
    # average would flip this order (0.50 vs 0.40) and bury the severe move.
    gaps = [
        {"playbook_id": 1, "move_id": "M1", "gap": 0.90},
        {"playbook_id": 3, "move_id": "M1", "gap": 0.40},
        {"playbook_id": 3, "move_id": "M2", "gap": 0.40},
        {"playbook_id": 1, "move_id": "M2", "gap": 0.10},
    ]
    meta = {**MOVE_META,
            (3, "M1"): {"scenario_key": "mediocre_everywhere"},
            (3, "M2"): {"scenario_key": "mediocre_everywhere"}}
    groups = group_by_scenario(gaps, meta)
    assert groups[0]["scenario_key"] == "attribution"       # the 0.90 scenario
    assert groups[0]["worst_gap"] == 0.90


def test_format_pairwise_priorities_shows_every_scenario_no_cutoff():
    """The report-grouping fix: no top-N truncation. Verified 2026-08-26 that the
    real scale (19 scenarios on the first production run) doesn't need one --
    this pins the CONTRACT (all scenarios appear), not the specific count."""
    gaps = [{"playbook_id": i, "move_id": "M1", "attempts": 10, "wins": 0,
             "equals": 0, "losses": 10, "match_or_beat_raw": 0.0,
             "match_or_beat_shrunk": 0.0, "gap": 1.0 - i * 0.01}
            for i in range(8)]                                    # more than the old top_n=5
    meta = {(i, "M1"): {"scenario_key": f"topic_{i}"} for i in range(8)}
    text = format_pairwise_priorities("Madhumita", gaps, meta)
    for i in range(8):
        assert f"topic_{i}" in text
    assert "#8" in text                                            # all 8 printed, not just 5


def test_format_pairwise_priorities_groups_one_scenario_into_one_block():
    """The exact defect from the read-through: one scenario's moves must render
    as ONE numbered block, not one block per move."""
    gaps = [
        {"playbook_id": 1, "move_id": "M2", "attempts": 11, "wins": 1, "equals": 3,
         "losses": 7, "match_or_beat_raw": 0.23, "match_or_beat_shrunk": 0.23, "gap": 0.77},
        {"playbook_id": 1, "move_id": "M1", "attempts": 11, "wins": 0, "equals": 7,
         "losses": 4, "match_or_beat_raw": 0.32, "match_or_beat_shrunk": 0.32, "gap": 0.68},
    ]
    text = format_pairwise_priorities("Madhumita", gaps, MOVE_META)
    assert text.count("#1") == 1                       # one heading for the group
    assert "attribution" in text
    assert "M2" in text and "M1" in text                # both moves listed within it


# ---------------------------------------------------------------------- report

def test_format_priorities_renders_ranked_gaps_with_evidence():
    gap = Gap(rater_id="m", playbook_id=1, move_id="M1", naren_rate=0.89,
              naren_attempts=9, csm_rate_raw=0.08, csm_rate_shrunk=0.15,
              csm_attempts=12)
    text = format_priorities(
        "Madhumita", [gap],
        move_meta={(1, "M1"): {"scenario_key": "app_volume", "name": "Probe bottlenecks",
                               "criterion": "Probe the mechanics",
                               "naren_quote": "do you have UTM tags on those?"}},
        evidence={(1, "M1"): ["let me check the dashboard", "second quote", "third"]},
        top_n=5,
    )
    assert "Madhumita" in text and "app_volume" in text and "Probe bottlenecks" in text
    assert "UTM tags" in text and "let me check the dashboard" in text
    assert "third" not in text                   # capped at 2 evidence quotes
    assert "score" not in text.lower()           # no headline score, by design


def test_format_priorities_empty_says_so():
    text = format_priorities("M", [], {}, {}, 5)
    assert "No rankable gaps" in text
