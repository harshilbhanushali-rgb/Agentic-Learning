"""Pure functions of the C2 harness (calibration/layer_d_grader_ab.py)."""
import pytest

from calibration.layer_d_grader_ab import (
    binom_p_at_least, gate_report, majority_outcome, size_matched_partner,
    weighted_score,
)
from layer_d.graders import MoveVerdict


def pb(key, n_moves):
    return {"scenario_key": key, "key_moves": [{"move_id": f"M{i}"} for i in range(n_moves)]}


def test_size_matched_partner_prefers_equal_move_count():
    books = {"a": pb("a", 4), "b": pb("b", 3), "c": pb("c", 4), "d": pb("d", 5)}
    assert size_matched_partner("a", books) == "c"
    assert size_matched_partner("c", books) == "a"


def test_size_matched_partner_falls_back_to_closest_alphabetical():
    books = {"a": pb("a", 5), "b": pb("b", 3), "c": pb("c", 3)}
    assert size_matched_partner("a", books) == "b"      # closest count, alpha tiebreak


def test_weighted_score_counts_partial_as_half_and_skips_unscored():
    verdicts = [MoveVerdict("M1", "hit"), MoveVerdict("M2", "partial"),
                MoveVerdict("M3", "miss"), MoveVerdict("M4", "unscored", reason="x")]
    assert weighted_score(verdicts) == pytest.approx(1.5 / 3)


def test_weighted_score_all_unscored_is_none():
    assert weighted_score([MoveVerdict("M1", "unscored", reason="x")]) is None


def test_majority_outcome_requires_strict_majority():
    assert majority_outcome(["win", "win", "loss"]) == "win"
    assert majority_outcome(["win", "loss"]) == "tie"
    assert majority_outcome(["tie", "tie", "win"]) == "win"   # ties don't vote
    assert majority_outcome(["tie", "tie", "tie"]) == "tie"


def test_binomial_p_exact_values():
    assert binom_p_at_least(0, 0) == 1.0
    assert binom_p_at_least(10, 10) == pytest.approx(1 / 1024)
    assert binom_p_at_least(5, 10) == pytest.approx(0.623046875)


def test_gate_passes_at_seventy_percent_with_significance():
    g = gate_report(decided=50, wins=35)        # 70%, p ~= 0.0033
    assert g["G_C2a_pass"] is True
    g2 = gate_report(decided=10, wins=7)        # 70% but p ~= 0.17 -> underpowered
    assert g2["G_C2a_pass"] is False
    g3 = gate_report(decided=50, wins=30)       # 60% -> below the bar
    assert g3["G_C2a_pass"] is False


def test_gate_zero_decided_never_passes():
    assert gate_report(0, 0)["G_C2a_pass"] is False
