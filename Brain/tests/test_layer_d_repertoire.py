"""Repertoire coverage (docs/findings/layer-d-say-arm.md §11): the three-way
uses-it / never / insufficient rule, with the POWER RULE pinned per cell (gate
G-R3 -- a "never" over fewer calls than the move's n_needed must come out as
insufficient data, never as a gap).
"""
import math

import pytest

from layer_d import repertoire
from layer_d.aggregate import MoveRate
from layer_d.repertoire import (
    INSUFFICIENT, NEVER, USES, RepertoireMove, classify, format_repertoire_report,
    n_needed, naren_repertoire, repertoire_coverage,
)


# ------------------------------------------------------------------ power rule

def test_n_needed_at_the_measured_median_rate_is_19():
    # (1 - 0.15)^18 = 0.0536 > 0.05 ; (1 - 0.15)^19 = 0.0456 < 0.05
    assert n_needed(0.15) == 19
    assert (1 - 0.15) ** 18 > 0.05 > (1 - 0.15) ** 19


@pytest.mark.parametrize("p", [0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.9])
def test_n_needed_is_the_smallest_n_with_zero_in_n_below_alpha(p):
    n = n_needed(p)
    assert (1 - p) ** n < 0.05
    assert n == 1 or (1 - p) ** (n - 1) >= 0.05


def test_n_needed_edge_cases():
    assert n_needed(1.0) == 1
    assert n_needed(0.0) == math.inf
    assert n_needed(0.5) == 5                         # 0.5^4 = 0.0625, 0.5^5 = 0.03125
    with pytest.raises(ValueError):
        n_needed(0.3, alpha=1.0)


def test_calls_needed_tracks_alpha():
    m = RepertoireMove(7, "M1", naren_said_calls=3, naren_calls=20)   # p = 0.15
    assert m.calls_needed() == 19
    assert m.calls_needed(alpha=0.01) == 29                            # 0.85^29 = 0.0090
    assert m.every_n_calls == 7                                        # round(1/0.15)


# ------------------------------------------------------------- the three states

MOVE = RepertoireMove(7, "M1", naren_said_calls=3, naren_calls=20)     # needs 19 calls


def test_one_verified_instance_is_uses_it_regardless_of_call_count():
    assert classify(MOVE, MoveRate(7, "M1", attempts=1, hits=0, partials=1)) == USES
    assert classify(MOVE, MoveRate(7, "M1", attempts=50, hits=1, partials=0)) == USES


def test_zero_instances_over_enough_calls_is_never():
    assert classify(MOVE, MoveRate(7, "M1", attempts=19, hits=0, partials=0)) == NEVER
    assert classify(MOVE, MoveRate(7, "M1", attempts=55, hits=0, partials=0)) == NEVER


def test_zero_instances_over_too_few_calls_is_insufficient_not_never():
    """G-R3: the power rule per cell. 18 calls at p=0.15 leaves a 5.4% chance of a
    zero by luck -- above alpha -- so it must NOT be reported as a gap."""
    assert classify(MOVE, MoveRate(7, "M1", attempts=18, hits=0, partials=0)) == INSUFFICIENT
    assert classify(MOVE, MoveRate(7, "M1", attempts=1, hits=0, partials=0)) == INSUFFICIENT
    assert classify(MOVE, None) == INSUFFICIENT                        # no routed calls at all


def test_a_move_naren_says_often_needs_fewer_calls():
    frequent = RepertoireMove(7, "M2", naren_said_calls=10, naren_calls=20)   # p = 0.5 -> 5
    assert classify(frequent, MoveRate(7, "M2", attempts=5, hits=0, partials=0)) == NEVER
    assert classify(frequent, MoveRate(7, "M2", attempts=4, hits=0, partials=0)) == INSUFFICIENT


# ------------------------------------------------------------------ repertoire

def test_naren_repertoire_requires_two_distinct_calls_said():
    rates = [
        MoveRate(7, "M1", attempts=20, hits=2, partials=1),    # 3 calls -> in
        MoveRate(7, "M2", attempts=20, hits=1, partials=1),    # 2 calls -> in (boundary)
        MoveRate(7, "M3", attempts=20, hits=1, partials=0),    # 1 call  -> out
        MoveRate(7, "M4", attempts=20, hits=0, partials=0),    # never   -> out
        MoveRate(8, "M1", attempts=0, hits=0, partials=0),     # unmeasured -> out
    ]
    rep = naren_repertoire(rates)
    assert set(rep) == {(7, "M1"), (7, "M2")}
    assert rep[(7, "M1")].p_hat == pytest.approx(0.15)
    assert rep[(7, "M2")].naren_said_calls == 2


def test_repertoire_coverage_covers_every_move_for_every_rater():
    rep = naren_repertoire([MoveRate(7, "M1", 20, 3, 0), MoveRate(7, "M2", 20, 10, 0)])
    csm = {"csm1": [MoveRate(7, "M1", attempts=25, hits=0, partials=0)],   # never (needs 19)
           "csm2": [MoveRate(7, "M2", attempts=3, hits=1, partials=0)]}     # uses
    cov = repertoire_coverage(rep, csm)
    by = {(r, c.move.move_id): c.state for r, cells in cov.items() for c in cells}
    assert by == {
        ("csm1", "M1"): NEVER, ("csm1", "M2"): INSUFFICIENT,   # no row -> 0 calls
        ("csm2", "M1"): INSUFFICIENT, ("csm2", "M2"): USES,
    }
    assert all(len(cells) == 2 for cells in cov.values())        # counts sum to repertoire


# ---------------------------------------------------------------------- report

META = {
    (7, "M1"): {"scenario_key": "app_volume", "name": "Probe",
                "criterion": "Probe the mechanics",
                "naren_quotes": ["do you have UTM tags?", "where does the pixel fire?"]},
    (7, "M2"): {"scenario_key": "app_volume", "name": "Warn",
                "criterion": "Warn about the deadline", "naren_quotes": ["by Friday"]},
    (9, "M1"): {"scenario_key": "budget_pacing", "name": "Reframe",
                "criterion": "Reframe spend as pacing", "naren_quotes": []},
}


def make_cells():
    rep = naren_repertoire([
        MoveRate(7, "M1", 20, 3, 0),     # p .15, needs 19
        MoveRate(7, "M2", 20, 10, 0),    # p .50, needs 5
        MoveRate(9, "M1", 20, 4, 0),     # p .20, needs 14
    ])
    csm = {"csm1": [
        MoveRate(7, "M1", attempts=25, hits=0, partials=0),   # never
        MoveRate(7, "M2", attempts=25, hits=2, partials=1),   # uses
        MoveRate(9, "M1", attempts=6, hits=0, partials=0),    # insufficient
    ]}
    return repertoire_coverage(rep, csm)["csm1"]


def test_report_states_every_cell_in_the_right_section():
    text = format_repertoire_report(
        "Madhumita", make_cells(), META,
        csm_quotes={(7, "M2"): ["we need this live by Friday", "second", "third", "fourth"]})
    assert "uses it: 1    never (enough calls to say so): 1    insufficient data: 1" in text
    never_i, uses_i, insuff_i = (text.index("NEVER USED"), text.index("USES IT"),
                                 text.index("INSUFFICIENT DATA"))
    assert never_i < uses_i < insuff_i
    # the never cell: her count, the power rule's n, Naren's frequency, his quotes
    never_block = text[never_i:uses_i]
    assert "M1: Probe" in never_block
    assert "you: 0 of 25 calls (19 needed)" in never_block
    assert "Naren: says it every ~7 calls (3/20)" in never_block
    assert 'Naren, real call: "do you have UTM tags?"' in never_block
    assert 'Naren, real call: "where does the pixel fire?"' in never_block
    # the uses cell: her verified quotes, capped at 3
    uses_block = text[uses_i:insuff_i]
    assert "M2: Warn -- you: 3 of 25 calls; Naren every ~2" in uses_block
    assert uses_block.count("your call:") == 3 and "fourth" not in uses_block
    # the insufficient cell: worded as data, never as a gap, with the count needed
    insuff_block = text[insuff_i:]
    assert "M1: Reframe -- 0 of 6 calls (14 needed at Naren's rate of every ~5)" in insuff_block
    assert "gap" not in insuff_block.split("(not a finding):")[1].lower()


def test_report_orders_never_cells_by_narens_frequency():
    rep = naren_repertoire([MoveRate(7, "M1", 20, 3, 0), MoveRate(9, "M1", 20, 10, 0)])
    cells = repertoire_coverage(rep, {"csm1": [
        MoveRate(7, "M1", attempts=30, hits=0, partials=0),
        MoveRate(9, "M1", attempts=30, hits=0, partials=0)]})["csm1"]
    text = format_repertoire_report("M", cells, META)
    # budget_pacing's move (p .50) is the one he uses most -> it must lead
    assert text.index("#1  budget_pacing") < text.index("#2  app_volume")


def test_report_with_no_cells_says_so():
    assert "No in-repertoire moves" in format_repertoire_report("M", [], META)


def test_report_never_reports_an_insufficient_cell_as_never():
    """The whole point of G-R3, end to end through the text: a zero over too few
    calls must not appear under NEVER USED."""
    rep = naren_repertoire([MoveRate(7, "M1", 20, 3, 0)])            # needs 19
    cells = repertoire_coverage(rep, {"csm1": [MoveRate(7, "M1", 18, 0, 0)]})["csm1"]
    text = format_repertoire_report("M", cells, META)
    never_block = text[text.index("NEVER USED"):text.index("USES IT")]
    assert "(none)" in never_block and "Probe" not in never_block
    assert "0 of 18 calls (19 needed" in text[text.index("INSUFFICIENT DATA"):]


def test_module_constants_match_the_findings_doc():
    assert repertoire.ALPHA == 0.05
    assert repertoire.MIN_REPERTOIRE_CALLS == 2


# ------------------------------------------------ wiring: build_combined_reports

def test_build_combined_reports_leads_with_the_repertoire_section(monkeypatch):
    """End to end through pipeline.build_combined_reports with storage mocked:
    the repertoire block comes first, carries Naren's evidence quotes from the
    playbook (not just the first one), pulls HER quotes through
    get_verified_quotes (hit AND partial), and applies the power rule."""
    from types import SimpleNamespace
    from layer_d import move_classes, pipeline
    from tests.test_layer_d_pipeline import PLAYBOOK_ROW, fake_tuning

    row = {**PLAYBOOK_ROW, "playbook": {**PLAYBOOK_ROW["playbook"], "key_moves": [
        {"move_id": "M1", "name": "Probe", "criterion": "Probe the mechanics",
         "evidence": [{"quote": "do you have UTM tags?"}, {"quote": "where does it fire?"}]},
        {"move_id": "M2", "name": "Warn", "criterion": "Warn about the deadline",
         "evidence": [{"quote": "by Friday"}]},
    ]}}
    st = pipeline.storage
    monkeypatch.setattr(st, "get_playbooks", lambda conn, status=None: [row])
    monkeypatch.setattr(move_classes, "load_move_classes", lambda path=None: {
        "app_volume:M1": {"route": "say"}, "app_volume:M2": {"route": "say"}})
    monkeypatch.setattr(pipeline, "get_tuning", lambda: fake_tuning(grader_arm="say"))

    def move_rates(conn, population, arm):
        if arm == "say" and population == "naren":
            return {"naren": [
                {"playbook_id": 7, "move_id": "M1", "attempts": 20, "hits": 2, "partials": 1, "unscored": 0},
                {"playbook_id": 7, "move_id": "M2", "attempts": 20, "hits": 5, "partials": 5, "unscored": 0},
            ]}
        if arm == "say" and population == "csm":
            return {"csm1": [
                {"playbook_id": 7, "move_id": "M1", "attempts": 25, "hits": 0, "partials": 0, "unscored": 0},
                {"playbook_id": 7, "move_id": "M2", "attempts": 25, "hits": 0, "partials": 1, "unscored": 0},
            ]}
        return {}
    monkeypatch.setattr(st, "get_move_rates", move_rates)
    monkeypatch.setattr(st, "get_say_densities", lambda conn: {})
    monkeypatch.setattr(st, "get_hit_quotes", lambda conn, rid, arm: {})
    asked = []

    def verified(conn, rid, arm):
        asked.append((rid, arm))
        return {(7, "M2"): ["we need it live by Friday"]}
    monkeypatch.setattr(st, "get_verified_quotes", verified)

    text = pipeline.build_combined_reports(object(), {"csm1": "Madhumita"})
    assert text.startswith("Repertoire coverage (say-type moves) -- Madhumita")
    assert asked == [("csm1", "say")]
    never_block = text[text.index("NEVER USED"):text.index("USES IT")]
    assert "M1: Probe" in never_block and "you: 0 of 25 calls (19 needed)" in never_block
    assert 'Naren, real call: "do you have UTM tags?"' in never_block
    assert 'Naren, real call: "where does it fire?"' in never_block      # not just the first
    uses_block = text[text.index("USES IT"):text.index("INSUFFICIENT DATA")]
    assert "M2: Warn -- you: 1 of 25 calls" in uses_block                # a PARTIAL counts
    assert 'your call: "we need it live by Friday"' in uses_block
