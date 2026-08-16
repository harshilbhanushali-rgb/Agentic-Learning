"""Tests for calibration/layer_b_arms.py -- step 1 of the Layer B redesign trial.

Spec: docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md

Everything here is hand-built. No corpus, no embedder, no database. The precedent is
`tests/test_layer_b_assignment.py`, which tests the relative top-K RULE against orthogonal
unit vectors -- a suite that passes because the model happened to agree proves nothing.

TWO REGRESSIONS ARE PINNED FIRST, because the metric has been wrong twice:

  rev 1  ">= 3 distinct accounts"  -- an audit found the published RTX-98% case has FOUR
         distinct accounts and PASSED. A count sees presence; the defect is dominance.
  rev 2  "N_eff"                   -- N_eff <= k, so an arm that puts more calls into each
         milestone raises the ceiling mechanically and the volume objective leaks back in.

`test_the_published_RTX_case_is_NOT_usable` pins the first.
`test_lift_removes_the_size_advantage_that_killed_revision_2` pins the second.

A third audit finding shaped this file directly: every rev-1 `usable_milestones` test passed
identically under a "count distinct CALLS" implementation, so none tested the property the
metric exists to have. `test_a_metric_that_counted_calls_would_disagree_here` fixes that.

The sign test is pinned against FIVE numbers already published in CLAUDE.md from four
different trials -- external anchors, not self-consistency.
"""
import math

import pytest

from calibration import layer_b_arms as lb


# c1/c3 are one client (uber), c2 banfield, c4 rtx.
ACCOUNTS = {"c1": "uber.com", "c2": "banfield.com", "c3": "uber.com", "c4": "rtx.com"}


def _ms(files, **kw):
    m = {"support_call_files": list(files), "support_calls": len(set(files))}
    m.update(kw)
    return m


def _flat(max_k=64):
    """A null table where E[N_eff] == 1.0 for every k, so `lift == N_eff` exactly.

    Used ONLY where a test is about the bar mechanics rather than about the null, so the
    assertions read in familiar N_eff units. The null's own behaviour is tested separately
    against `expected_neff_table`; conflating the two would let a broken null hide behind a
    passing bar test.
    """
    return {k: 1.0 for k in range(1, max_k + 1)}


# ---------------------------------------------------------------------------------------
# REGRESSION 1 -- the audit finding that killed revision 1's metric
# ---------------------------------------------------------------------------------------

def test_the_published_RTX_case_is_NOT_usable():
    """98% one client plus three strays. FOUR distinct accounts -- it cleared the old bar.

    `experiential_branding_...` is recorded in CLAUDE.md at 98% RTX and was the example cited
    to justify this metric. Under a distinct-account count it scored 4 and passed. It must
    collapse to ~1, because it IS one client's rubric.
    """
    accounts = {f"rtx{i}": "rtx.com" for i in range(48)}
    accounts.update({"a": "acme.com", "b": "beta.com", "g": "gamma.com"})
    calls = [f"rtx{i}.txt" for i in range(48)] + ["a.txt", "b.txt", "g.txt"]

    neff, distinct, _ = lb.effective_accounts(calls, accounts)
    assert distinct == 4, "four distinct accounts -- this is what the old count saw"
    assert neff == pytest.approx(1.127, abs=0.01), "but effectively ONE client"
    assert lb.usable_milestones([_ms(calls)], accounts, 3.0, _flat(64)) == (0, 1, 0)


def test_the_published_UBER_case_is_NOT_usable():
    """The other cited case: 95% one client over five distinct accounts."""
    accounts = {f"u{i}": "uber.com" for i in range(38)}
    accounts.update({c: f"{c}.com" for c in "wxyz"})
    calls = [f"u{i}.txt" for i in range(38)] + [f"{c}.txt" for c in "wxyz"]

    neff, distinct, _ = lb.effective_accounts(calls, accounts)
    assert distinct == 5
    assert neff < 1.3
    assert lb.usable_milestones([_ms(calls)], accounts, 3.0, _flat(64))[0] == 0


def test_a_metric_that_counted_calls_would_disagree_here():
    """The defining property, which no revision-1 test exercised.

    Four distinct CALLS, but only TWO clients. A call-counting implementation scores 4 and
    passes a bar of 3; the real metric scores 2.0 and fails.
    """
    m = _ms(["c1.txt", "c3.txt", "c2.txt", "c2b.txt"])
    accounts = {**ACCOUNTS, "c2b": "banfield.com"}

    assert len({lb.call_stem(c) for c in m["support_call_files"]}) == 4   # four calls
    neff, distinct, _ = lb.effective_accounts(m["support_call_files"], accounts)
    assert (distinct, neff) == (2, pytest.approx(2.0))
    assert lb.usable_milestones([m], accounts, 3.0, _flat()) == (0, 1, 0)


# ---------------------------------------------------------------------------------------
# REGRESSION 2 -- the size confound that killed revision 2's metric
# ---------------------------------------------------------------------------------------

def test_lift_removes_the_size_advantage_that_killed_revision_2():
    """N_eff <= k, so a 20-call milestone can outscore a 4-call one on SIZE alone.

    Both milestones here are perfectly diverse -- every call a different client -- so neither
    is more transferable than the other. Raw N_eff says 20 beats 4 (a 5x 'win' that is purely
    the arm having routed more calls in). Lift says they are identical, which is correct.
    """
    accounts = {f"k{i}": f"c{i}.com" for i in range(24)}
    small = _ms([f"k{i}.txt" for i in range(4)])
    big = _ms([f"k{i}.txt" for i in range(20)])
    pool = lb.corpus_account_pool(accounts)
    table = lb.expected_neff_table(pool, [4, 20], trials=200)

    assert lb.milestone_neff(small, accounts)[0] == pytest.approx(4.0)
    assert lb.milestone_neff(big, accounts)[0] == pytest.approx(20.0)   # raw: 5x apart

    a = lb.milestone_lift(small, accounts, table)["lift"]
    b = lb.milestone_lift(big, accounts, table)["lift"]
    assert a == pytest.approx(b, rel=0.02), "lift must not reward the bigger milestone"


def test_lift_still_punishes_concentration_at_any_size():
    """The correction must not throw away the thing it is correcting for."""
    accounts = {f"u{i}": "uber.com" for i in range(10)}
    accounts.update({f"k{i}": f"c{i}.com" for i in range(10)})
    pool = lb.corpus_account_pool(accounts)
    table = lb.expected_neff_table(pool, [10], trials=300)

    concentrated = _ms([f"u{i}.txt" for i in range(10)])     # all one client
    diverse = _ms([f"k{i}.txt" for i in range(10)])          # ten clients

    lo = lb.milestone_lift(concentrated, accounts, table)["lift"]
    hi = lb.milestone_lift(diverse, accounts, table)["lift"]
    assert lo < 0.4 < hi


def test_lift_returns_its_components_so_the_ratio_cannot_hide_which_half_moved():
    """An arm can raise lift by finding more accounts OR by shrinking k. Different findings."""
    accounts = {"a": "a.com", "b": "b.com"}
    table = lb.expected_neff_table(lb.corpus_account_pool(accounts), [2], trials=50)
    r = lb.milestone_lift(_ms(["a.txt", "b.txt"]), accounts, table)
    assert set(r) == {"lift", "neff", "expected", "k", "distinct", "unaccounted"}
    assert r["k"] == 2 and r["distinct"] == 2


# ---------------------------------------------------------------------------------------
# the null table
# ---------------------------------------------------------------------------------------

def test_the_null_prices_in_corpus_skew():
    """uber.com at 16% of calls means a general 9-call move is EXPECTED to draw one or two
    Uber calls. The null must reflect that rather than assuming uniform clients."""
    skewed = {f"u{i}": "uber.com" for i in range(55)}
    skewed.update({f"k{i}": f"c{i}.com" for i in range(288)})
    even = {f"k{i}": f"c{i}.com" for i in range(343)}

    e_skew = lb.expected_neff_table(lb.corpus_account_pool(skewed), [9], trials=300)[9]
    e_even = lb.expected_neff_table(lb.corpus_account_pool(even), [9], trials=300)[9]
    assert e_skew < e_even <= 9.0


def test_the_null_is_deterministic_across_calls_and_orderings():
    """Seeded per k, so the table cannot depend on the order the ks arrive in -- otherwise
    two arms could be scored against different yardsticks."""
    accounts = {f"k{i}": f"c{i % 20}.com" for i in range(200)}
    pool = lb.corpus_account_pool(accounts)
    a = lb.expected_neff_table(pool, [3, 7, 11], trials=100)
    b = lb.expected_neff_table(pool, [11, 3, 7], trials=100)
    assert a == b


def test_a_single_call_has_expectation_exactly_one():
    accounts = {"a": "a.com", "b": "b.com"}
    assert lb.expected_neff_table(lb.corpus_account_pool(accounts), [1])[1] == 1.0


def test_k_at_or_above_the_pool_size_is_computed_exactly_not_sampled():
    """Drawing the whole pool has no variance, so sampling it would only add noise."""
    accounts = {"a": "x.com", "b": "x.com", "c": "y.com", "d": "y.com"}
    t = lb.expected_neff_table(lb.corpus_account_pool(accounts), [4], trials=1)
    assert t[4] == pytest.approx(2.0)


def test_an_empty_pool_RAISES():
    with pytest.raises(ValueError, match="empty account pool"):
        lb.expected_neff_table([], [3])


def test_zero_trials_is_rejected():
    with pytest.raises(ValueError, match="trials"):
        lb.expected_neff_table(["a.com"], [1], trials=0)


def test_a_missing_k_RAISES_rather_than_scoring_against_nothing():
    """The table must be built from the SAME population being scored. A silent default would
    score some milestones against a yardstick that does not exist."""
    accounts = {"a": "a.com", "b": "b.com", "c": "c.com"}
    table = lb.expected_neff_table(lb.corpus_account_pool(accounts), [2])
    with pytest.raises(KeyError, match="no null expectation"):
        lb.milestone_lift(_ms(["a.txt", "b.txt", "c.txt"]), accounts, table)


def test_milestone_ks_uses_the_ACCOUNTED_count_not_support_calls():
    """N_eff is computed over accounted calls only, so the null must draw that many. Using
    the raw support count would score every milestone with unaccounted calls too low, by an
    amount proportional to roster coverage."""
    accounts = {"a": "a.com", "b": "b.com"}
    per_scenario = {"s": {"cluster_id": "1",
                          "milestones": [_ms(["a.txt", "b.txt", "zz.txt", "yy.txt"])]}}
    assert per_scenario["s"]["milestones"][0]["support_calls"] == 4
    assert lb.milestone_ks(per_scenario, accounts) == {2}


def test_milestone_ks_skips_wholly_unaccounted_milestones():
    accounts = {"a": "a.com"}
    per_scenario = {"s": {"cluster_id": "1", "milestones": [_ms(["zz.txt"])]}}
    assert lb.milestone_ks(per_scenario, accounts) == set()


# ---------------------------------------------------------------------------------------
# effective_accounts -- the statistic underneath
# ---------------------------------------------------------------------------------------

def test_one_account_is_neff_one():
    neff, distinct, _ = lb.effective_accounts(["c1.txt", "c3.txt"], ACCOUNTS)
    assert (distinct, neff) == (1, pytest.approx(1.0))


def test_evenly_split_accounts_give_neff_equal_to_the_count():
    accounts = {c: f"{c}.com" for c in "abcd"}
    neff, distinct, _ = lb.effective_accounts(["a.txt", "b.txt", "c.txt", "d.txt"], accounts)
    assert (distinct, neff) == (4, pytest.approx(4.0))


def test_neff_never_exceeds_the_distinct_count():
    """The gap between them IS the dominance, so the ordering must always hold."""
    accounts = {f"k{i}": ("big.com" if i < 7 else f"s{i}.com") for i in range(10)}
    neff, distinct, _ = lb.effective_accounts([f"k{i}.txt" for i in range(10)], accounts)
    assert 1.0 <= neff <= distinct


def test_repeated_calls_are_deduplicated_before_weighting():
    assert lb.effective_accounts(["c1.txt", "c2.txt"], ACCOUNTS) == \
        lb.effective_accounts(["c1.txt", "c1.txt", "c2.txt"], ACCOUNTS)


def test_no_accounted_call_is_NaN_not_zero():
    """0.0 reads as MORE concentrated than the most concentrated real milestone, i.e. it
    would silently rank an unmeasurable milestone as the worst one."""
    neff, distinct, unacc = lb.effective_accounts(["x.txt", "y.txt"], ACCOUNTS)
    assert math.isnan(neff) and (distinct, unacc) == (0, 2)


def test_unaccounted_calls_contribute_nothing_and_are_reported():
    """The safe direction: they can only ever make a milestone look LESS transferable.
    Counting each as its own account would ASSERT they are different clients -- the exact
    quantity being measured -- and would inflate toward a false positive."""
    neff, distinct, unacc = lb.effective_accounts(
        ["c1.txt", "c2.txt", "x.txt", "y.txt"], ACCOUNTS)
    assert (distinct, unacc) == (2, 2)
    assert neff == pytest.approx(2.0), "the unaccounted calls do not dilute the split"


def test_empty_call_list_is_NaN():
    neff, distinct, unacc = lb.effective_accounts([], ACCOUNTS)
    assert math.isnan(neff) and (distinct, unacc) == (0, 0)


# ---------------------------------------------------------------------------------------
# sibling domains
# ---------------------------------------------------------------------------------------

def test_a_subdomain_folds_into_its_parent_when_BOTH_are_observed():
    """The live corpus case: contractors.scale.com (12 calls) + scale.com (8) are one
    client, already recorded in CLAUDE.md as a correction nothing applies."""
    acct = {"a": "contractors.scale.com", "b": "scale.com", "c": "uber.com"}
    new, merges = lb.collapse_sibling_domains(acct)
    assert merges == {"contractors.scale.com": "scale.com"}
    assert new == {"a": "scale.com", "b": "scale.com", "c": "uber.com"}


def test_a_subdomain_is_LEFT_ALONE_when_the_parent_is_not_observed():
    """The corpus itself must supply the evidence that two domains are one organisation. A
    public-suffix list would be a curated list by another name."""
    acct = {"a": "eu.example.com", "b": "uber.com"}
    new, merges = lb.collapse_sibling_domains(acct)
    assert merges == {} and new == acct


def test_two_unrelated_domains_are_never_fused():
    assert lb.collapse_sibling_domains({"a": "uber.com", "b": "banfield.com"})[1] == {}


def test_a_suffix_that_is_not_on_a_label_boundary_does_not_fold():
    """`notscale.com` ends with `scale.com` as a STRING but is a different organisation."""
    assert lb.collapse_sibling_domains({"a": "notscale.com", "b": "scale.com"})[1] == {}


def test_a_chain_folds_to_the_shortest_observed_ancestor_in_one_step():
    acct = {"a": "x.y.corp.com", "b": "y.corp.com", "c": "corp.com"}
    new, merges = lb.collapse_sibling_domains(acct)
    assert merges["x.y.corp.com"] == "corp.com"
    assert set(new.values()) == {"corp.com"}


def test_collapse_is_idempotent():
    once, _ = lb.collapse_sibling_domains({"a": "contractors.scale.com", "b": "scale.com"})
    twice, merges = lb.collapse_sibling_domains(once)
    assert twice == once and merges == {}


def test_collapse_changes_the_verdict_on_a_scale_only_milestone():
    """Why it matters: without it a milestone resting on Scale alone reads as two clients --
    inflating in the unsafe direction."""
    raw = {"s1": "scale.com", "s2": "contractors.scale.com"}
    assert lb.effective_accounts(["s1.txt", "s2.txt"], raw)[1] == 2
    collapsed, _ = lb.collapse_sibling_domains(raw)
    neff, distinct, _ = lb.effective_accounts(["s1.txt", "s2.txt"], collapsed)
    assert (distinct, neff) == (1, pytest.approx(1.0))


# ---------------------------------------------------------------------------------------
# call_stem -- the join that would fail SILENTLY
# ---------------------------------------------------------------------------------------

def test_call_stem_matches_the_key_account_map_builds():
    """If the two ends disagree, EVERY milestone is unscoreable, every arm ties, and the sign
    test returns p=1.0 -- a broken join that reads as 'the arms do not differ'."""
    assert lb.call_stem("acme_call_01.txt") == \
        "acme_call_01.speakers.json"[: -len(".speakers.json")]


def test_call_stem_leaves_a_bare_stem_alone():
    assert lb.call_stem("acme_call_01") == "acme_call_01"


# ---------------------------------------------------------------------------------------
# milestone_calls -- the stale-artifact guard
# ---------------------------------------------------------------------------------------

def test_a_milestone_without_support_call_files_RAISES():
    """A pre-trial artifact must not become an empty list: that would read as 'unscoreable',
    be excluded from every mean, and produce a clean-looking report over no data."""
    with pytest.raises(KeyError, match="support_call_files"):
        lb.milestone_calls({"support_calls": 4})


def test_the_real_pre_trial_field_set_is_rejected():
    """The exact shape pass1 writes TODAY, pinned so a future reader cannot mistake it for
    something this metric can consume."""
    real = {"cluster_id": 3, "clauses": ["x"], "support_calls": 9, "support_clauses": 40,
            "support_frac": 0.3, "median_position": 0.5, "relevance_mean": 0.6}
    with pytest.raises(KeyError):
        lb.milestone_calls(real)


# ---------------------------------------------------------------------------------------
# usable_milestones
# ---------------------------------------------------------------------------------------

def test_usable_scoreable_and_unscoreable_are_reported_separately():
    """An arm must not be able to win by producing milestones the metric cannot see."""
    accounts = {c: f"{c}.com" for c in "abc"}
    ms = [_ms(["a.txt", "b.txt", "c.txt"]),   # 3.0 -> usable
          _ms(["a.txt", "b.txt"]),            # 2.0 -> scoreable, not usable
          _ms(["zz.txt"])]                    # unscoreable
    assert lb.usable_milestones(ms, accounts, 3.0, _flat()) == (1, 2, 1)


def test_the_bar_is_a_float_parameter_so_sensitivity_can_be_reported():
    accounts = {c: f"{c}.com" for c in "abc"}
    ms = [_ms(["a.txt", "b.txt"]), _ms(["a.txt", "b.txt", "c.txt"])]
    assert lb.usable_milestones(ms, accounts, 2.0, _flat())[0] == 2
    assert lb.usable_milestones(ms, accounts, 3.0, _flat())[0] == 1
    assert lb.usable_milestones(ms, accounts, 4.0, _flat())[0] == 0


def test_no_milestones_is_all_zero():
    assert lb.usable_milestones([], ACCOUNTS, 3.0, _flat()) == (0, 0, 0)


# ---------------------------------------------------------------------------------------
# derive_bar -- the rule, not the number
# ---------------------------------------------------------------------------------------

def _scen(cid, mss):
    return {"cluster_id": cid, "milestones": mss}


def test_derive_bar_returns_the_control_median_by_default():
    """~50% of control milestones are usable by construction: maximally non-saturated, and
    sensitive in both directions. Revision 1's guessed bar put 91% over it."""
    accounts = {c: f"{c}.com" for c in "abcdef"}
    per_scenario = {
        "s1": _scen("1", [_ms(["a.txt"]), _ms(["a.txt", "b.txt"])]),
        "s2": _scen("2", [_ms(["a.txt", "b.txt", "c.txt"]),
                          _ms(["a.txt", "b.txt", "c.txt", "d.txt"])]),
    }
    assert lb.derive_bar(per_scenario, accounts, _flat()) == pytest.approx(2.5)


def test_derive_bar_takes_any_quantile():
    accounts = {c: f"{c}.com" for c in "abcd"}
    per_scenario = {"s": _scen("1", [_ms(["a.txt"]), _ms(["a.txt", "b.txt"]),
                                     _ms(["a.txt", "b.txt", "c.txt"])])}
    assert lb.derive_bar(per_scenario, accounts, _flat(), 0.0) == pytest.approx(1.0)
    assert lb.derive_bar(per_scenario, accounts, _flat(), 1.0) == pytest.approx(3.0)


def test_derive_bar_ignores_unscoreable_milestones():
    accounts = {"a": "a.com", "b": "b.com"}
    per_scenario = {"s": _scen("1", [_ms(["zz.txt"]), _ms(["a.txt"]),
                                     _ms(["a.txt", "b.txt"])])}
    assert lb.derive_bar(per_scenario, accounts, _flat()) == pytest.approx(1.5)


def test_derive_bar_RAISES_when_nothing_is_scoreable():
    """A default here would be a guess of exactly the kind that already failed twice."""
    with pytest.raises(ValueError, match="cannot be derived"):
        lb.derive_bar({"s": _scen("1", [_ms(["zz.txt"])])}, {"a": "a.com"}, _flat())


# ---------------------------------------------------------------------------------------
# per_cluster_stats
# ---------------------------------------------------------------------------------------

def test_per_cluster_stats_keys_on_cluster_id_not_scenario_key():
    accounts = {c: f"{c}.com" for c in "abc"}
    per_scenario = {"some_name_gemma_invented": _scen("37", [_ms(["a.txt", "b.txt", "c.txt"])]),
                    "another_name": _scen("12", [_ms(["a.txt"])])}
    got = lb.per_cluster_stats(per_scenario, accounts, 3.0, _flat())
    assert set(got) == {"37", "12"}
    assert got["37"]["usable"] == 1 and got["12"]["usable"] == 0


def test_mean_lift_falls_when_a_single_client_milestone_is_added():
    """The count-independent companion. `usable` can only rise with milestone count; this
    cannot, which is why F12 requires the two to agree in direction."""
    accounts = {c: f"{c}.com" for c in "abc"}
    good, junk = _ms(["a.txt", "b.txt", "c.txt"]), _ms(["a.txt"])
    before = lb.per_cluster_stats({"s": _scen("1", [good])}, accounts, 3.0, _flat())["1"]
    after = lb.per_cluster_stats({"s": _scen("1", [good, junk])}, accounts, 3.0, _flat())["1"]
    assert after["usable"] == before["usable"]        # the count did not notice
    assert after["mean_lift"] < before["mean_lift"]   # the mean did


def test_raw_neff_rides_along_as_a_diagnostic():
    """F12: a disagreement between lift and raw must be visible, not silently resolved."""
    accounts = {c: f"{c}.com" for c in "abc"}
    got = lb.per_cluster_stats({"s": _scen("1", [_ms(["a.txt", "b.txt", "c.txt"])])},
                               accounts, 3.0, _flat())["1"]
    assert got["mean_neff"] == pytest.approx(3.0)
    assert "mean_lift" in got and "mean_neff" in got


def test_scenarios_without_a_cluster_id_are_dropped_not_bucketed():
    """Bucketing them under "" would silently fuse several scenarios into one row."""
    per_scenario = {"x": {"cluster_id": "", "milestones": []},
                    "y": {"milestones": []},
                    "z": _scen("9", [])}
    assert set(lb.per_cluster_stats(per_scenario, {"a": "a.com"}, 3.0, _flat())) == {"9"}


def test_a_duplicate_cluster_id_within_one_arm_RAISES():
    with pytest.raises(ValueError, match="duplicate cluster_id"):
        lb.per_cluster_stats({"a": _scen("37", []), "b": _scen("37", [])},
                             {"a": "a.com"}, 3.0, _flat())


def test_a_cluster_with_no_scoreable_milestone_has_NaN_means():
    got = lb.per_cluster_stats({"s": _scen("1", [_ms(["zz.txt"])])},
                               {"a": "a.com"}, 3.0, _flat())["1"]
    assert math.isnan(got["mean_lift"]) and math.isnan(got["mean_neff"])
    assert got["unscoreable"] == 1


# ---------------------------------------------------------------------------------------
# sign_test -- pinned to FIVE published numbers from four different trials
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("up,down,expected,source", [
    (8,  0, 0.0078, "rescue_centroid seed 42, +8/-0, CLAUDE.md p=0.0078"),
    (9,  0, 0.0039, "rescue_centroid seed 7,  +9/-0, CLAUDE.md p=0.0039"),
    (11, 2, 0.0225, "rescue_centroid seed 1,  +11/-2, CLAUDE.md p=0.0225"),
    (12, 1, 0.003,  "routing_bench blend vs description, 12-1, CLAUDE.md p=0.003"),
    (6,  3, 0.508,  "routing_bench blend vs centroid, 6-3, CLAUDE.md p=0.508"),
])
def test_sign_test_reproduces_published_repo_results(up, down, expected, source):
    assert lb.sign_test(up, down) == pytest.approx(expected, abs=5e-4), source


def test_sign_test_is_symmetric():
    """Load-bearing: all five anchors have down <= up, so an implementation using `down`
    instead of `min(up, down)` passes every anchor and is caught only here."""
    assert lb.sign_test(8, 0) == lb.sign_test(0, 8)
    assert lb.sign_test(2, 11) == lb.sign_test(11, 2)


def test_no_movement_at_all_is_p_one():
    assert lb.sign_test(0, 0) == 1.0


def test_a_perfect_split_is_p_one():
    assert lb.sign_test(5, 5) == pytest.approx(1.0)


def test_p_is_always_a_probability():
    for up in range(8):
        for down in range(8):
            assert 0.0 <= lb.sign_test(up, down) <= 1.0


def test_negative_counts_are_rejected():
    with pytest.raises(ValueError):
        lb.sign_test(-1, 3)


# ---------------------------------------------------------------------------------------
# compare_arms -- direction, never a rate
# ---------------------------------------------------------------------------------------

def _cl(d):
    return {k: {"usable": v, "mean_lift": float(v)} for k, v in d.items()}


def test_compare_reports_direction_not_a_rate():
    """The published failure this guards against: a noise floor whose flips were SYMMETRIC
    (12 up, 10 down, net +2) and a treatment whose flips were ASYMMETRIC (12 up, 6 down,
    net +6) gave the SAME flip rate and the A/B was unreadable."""
    ctrl = _cl({f"c{i}": 1 for i in range(22)})
    noise = _cl({**{f"c{i}": 2 for i in range(12)},
                 **{f"c{i}": 0 for i in range(12, 22)}})
    treat = _cl({**{f"c{i}": 2 for i in range(12)},
                 **{f"c{i}": 0 for i in range(12, 18)},
                 **{f"c{i}": 1 for i in range(18, 22)}})

    n, t = lb.compare_arms(ctrl, noise), lb.compare_arms(ctrl, treat)
    assert (n["up"], n["down"], n["net"]) == (12, 10, 2)
    assert (t["up"], t["down"], t["net"]) == (12, 6, 6)
    assert t["p"] < n["p"]


def test_compare_can_read_either_field():
    ctrl = {"a": {"usable": 1, "mean_lift": 5.0}}
    arm = {"a": {"usable": 2, "mean_lift": 3.0}}
    assert lb.compare_arms(ctrl, arm, "usable")["up"] == 1
    assert lb.compare_arms(ctrl, arm, "mean_lift")["down"] == 1


def test_a_cluster_missing_from_one_arm_is_NOT_scored_as_zero():
    """Scoring an absence as a decrease attributes a taxonomy fact to Layer B."""
    d = lb.compare_arms(_cl({"a": 5, "b": 1}), _cl({"b": 1, "c": 4}))
    assert d["n_shared"] == 1
    assert (d["only_control"], d["only_arm"]) == (1, 1)
    assert (d["up"], d["down"], d["net"]) == (0, 0, 0)


def test_NaN_clusters_are_excluded_not_treated_as_zero():
    """0.0 is the worst possible score, so imputing it would rank an unmeasurable cluster
    below every real one."""
    ctrl = {"a": {"mean_lift": float("nan")}, "b": {"mean_lift": 1.0}}
    arm = {"a": {"mean_lift": 4.0}, "b": {"mean_lift": 2.0}}
    d = lb.compare_arms(ctrl, arm, "mean_lift")
    assert d["unscoreable_pairs"] == 1
    assert (d["up"], d["down"]) == (1, 0)


def test_ties_are_counted_and_excluded_from_the_test():
    d = lb.compare_arms(_cl({"a": 1, "b": 2, "c": 3}), _cl({"a": 2, "b": 2, "c": 1}))
    assert (d["up"], d["down"], d["tie"]) == (1, 1, 1)


def test_no_shared_clusters_at_all_is_p_one_not_a_crash():
    d = lb.compare_arms(_cl({"a": 1}), _cl({"b": 1}))
    assert d["n_shared"] == 0 and d["p"] == 1.0


# ---------------------------------------------------------------------------------------
# multiplicity
# ---------------------------------------------------------------------------------------

def test_multiplicity_note_quantifies_the_thirteen_arm_risk():
    """~49% chance at least one of 13 arms clears 0.05 by chance alone."""
    n = lb.multiplicity_note(13)
    assert n["expected_false_passes"] == pytest.approx(0.65)
    assert n["p_at_least_one"] == pytest.approx(0.4867, abs=1e-3)
    assert n["bonferroni_alpha"] == pytest.approx(0.05 / 13)


def test_multiplicity_note_of_a_single_arm_is_alpha():
    assert lb.multiplicity_note(1)["p_at_least_one"] == pytest.approx(0.05)


def test_multiplicity_note_of_zero_arms_does_not_divide_by_zero():
    assert lb.multiplicity_note(0)["bonferroni_alpha"] == 0.05


# ---------------------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------------------

def test_score_distribution_makes_a_saturated_bar_visible():
    """Revision 1's bar was saturated and the report could not show it. This can."""
    accounts = {c: f"{c}.com" for c in "abcd"}
    per_scenario = {"s": _scen("1", [
        _ms(["a.txt"]),
        _ms(["a.txt", "b.txt"]),
        _ms(["a.txt", "b.txt", "c.txt", "d.txt"]),
        _ms(["zz.txt"]),
    ])}
    d = lb.score_distribution(per_scenario, accounts, _flat())
    assert d["unscoreable"] == 1
    assert d["neff"]["n"] == 3 and d["lift"]["n"] == 3
    assert d["neff"]["median"] == pytest.approx(2.0)
    assert d["neff"]["min"] == pytest.approx(1.0) and d["neff"]["max"] == pytest.approx(4.0)


def test_score_distribution_reports_lift_and_raw_side_by_side():
    """They are the pair F12 is about; seeing them together is what makes a disagreement
    legible instead of a surprise."""
    accounts = {c: f"{c}.com" for c in "abc"}
    table = lb.expected_neff_table(lb.corpus_account_pool(accounts), [1, 3], trials=50)
    d = lb.score_distribution(
        {"s": _scen("1", [_ms(["a.txt"]), _ms(["a.txt", "b.txt", "c.txt"])])},
        accounts, table)
    assert set(d) == {"lift", "neff", "unscoreable"}
    assert d["neff"]["max"] == pytest.approx(3.0)
    assert d["lift"]["max"] <= 1.5


def test_top_account_share_finds_a_dominated_milestone():
    assert lb.top_account_share(_ms(["c1.txt", "c3.txt", "c2.txt"]), ACCOUNTS) \
        == pytest.approx(2 / 3)


def test_top_account_share_with_no_accounted_calls_is_NaN_not_zero():
    """0.0 reads as maximally diverse -- the flattering direction -- and would bias any
    per-arm mean toward 'less concentrated than reality'."""
    assert math.isnan(lb.top_account_share(_ms(["zz.txt"]), ACCOUNTS))


def test_unaccounted_rate_exposes_an_asymmetry_between_arms():
    """If roster coverage differs between two arms, the comparison measures coverage rather
    than routing -- and that cannot be seen from the usable counts alone."""
    accounts = {"a": "a.com", "b": "b.com"}
    d = lb.unaccounted_rate(
        {"s": _scen("1", [_ms(["a.txt", "b.txt"]), _ms(["a.txt", "zz.txt"])])}, accounts)
    assert d["milestones"] == 2
    assert (d["calls"], d["accounted_calls"]) == (4, 3)
    assert d["accounted_frac"] == pytest.approx(0.75)
    assert d["unscoreable_milestones"] == 0
