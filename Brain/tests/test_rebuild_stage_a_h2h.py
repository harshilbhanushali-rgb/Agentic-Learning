"""Pure helpers of calibration/rebuild_stage_a_h2h.py (Stage A head-to-head)."""
import json
import random

import pytest

from calibration import ARTIFACTS_DIR
from calibration import rebuild_stage_a_h2h as h
from calibration.layer_bc_arms import scenario_map_from_rows


def _row(cid, kind, key, merge_into=None):
    return {"cluster_id": cid, "kind": kind, "scenario_key": key,
            "merge_into_key": merge_into, "business_description": key, "keyphrases": []}


OLD = [_row("c1", "scenario", "pricing"), _row("c2", "scenario", "ats"),
       _row("c3", "mechanics", "ok"), _row("c4", "scenario", "pixel")]
NEW = [_row("c1", "scenario", "budget_and_pricing"), _row("c2", "merged", None, "budget_and_pricing"),
       _row("c3", "mechanics", "ack"), _row("c4", "logistics", "pixel_sched")]


def _maps():
    om, ocok = scenario_map_from_rows(OLD)
    nm, ncok = scenario_map_from_rows(NEW)
    return om, nm, h.counterparts(ocok, NEW, nm, ncok)


def test_counterpart_follows_the_home_cluster_and_merges():
    _, _, cp = _maps()
    assert cp == {"pricing": "budget_and_pricing", "ats": "budget_and_pricing",
                  "ok": "ack", "pixel": "pixel_sched"}


def test_categorise_checks_coachability_before_counterpart():
    om, nm, cp = _maps()
    assert h.categorise("pricing", "budget_and_pricing", om, nm, cp) == "same"
    assert h.categorise("ats", "budget_and_pricing", om, nm, cp) == "same"   # merged in
    assert h.categorise("pixel", "pixel_sched", om, nm, cp) == "lost"        # now a sink
    assert h.categorise("ok", "budget_and_pricing", om, nm, cp) == "gained"
    assert h.categorise("ok", "pixel_sched", om, nm, cp) == "sink_to_sink"


def test_categorise_moved_between_coachable_scenarios():
    om, nm, cp = _maps()
    nm2 = dict(nm, other={**nm["budget_and_pricing"], "scenario_key": "other"})
    assert h.categorise("pricing", "other", om, nm2, cp) == "moved"


def test_stratified_equal_then_top_up():
    by = {"gained": list(range(100)), "lost": list(range(100, 105)),
          "moved": list(range(200, 300))}
    got = h.stratified(by, 60, random.Random(1))
    assert len(got) == 60 and len(set(got)) == 60
    assert sum(100 <= x < 105 for x in got) == 5


def test_binom_two_sided():
    assert h.binom_two_sided(10, 20) == pytest.approx(1.0)
    assert h.binom_two_sided(15, 20) == pytest.approx(0.04139, abs=1e-4)
    assert h.binom_two_sided(0, 0) == 1.0


def _key(n_changed=30):
    items = {f"c{i}": {"type": "changed", "new_side": "A", "category": "moved"}
             for i in range(n_changed)}
    items.update({f"n{i}": {"type": "neg", "correct": "B"} for i in range(6)})
    return {"items": items}


def _reader(name, changed_answer, neg_right=6):
    ans = {f"c{i}": changed_answer for i in range(30)}
    ans.update({f"n{i}": ("B" if i < neg_right else "A") for i in range(6)})
    return {"_file": name, "answers": ans}


def test_score_refuses_partial_read():
    r = _reader("r1", "A")
    del r["answers"]["c0"]
    with pytest.raises(SystemExit):
        h.score(_key(), [r])


def test_score_needs_three_valid_readers():
    res = h.score(_key(), [_reader("r1", "A"), _reader("r2", "A"), _reader("r3", "A", 4)])
    assert res["verdict"] == "INSTRUMENT_INCOMPLETE"


def test_score_new_wins_and_old_wins():
    res = h.score(_key(), [_reader(f"r{i}", "A") for i in range(3)])
    assert res["verdict"] == "NEW_MAP_WINS" and res["tally"] == {"new": 30}
    res = h.score(_key(), [_reader(f"r{i}", "B") for i in range(3)])
    assert res["verdict"] == "KEEP_UNION_BASE"


def test_score_same_votes_are_undecided():
    res = h.score(_key(), [_reader(f"r{i}", "same") for i in range(3)])
    assert res["decided"] == 0 and res["verdict"] == "KEEP_UNION_BASE"


@pytest.mark.skipif(not (ARTIFACTS_DIR / "adjudication_ab_union_base.json").exists(),
                    reason="live taxonomy artifact not on this machine")
def test_live_map_is_its_own_counterpart():
    rows = json.loads((ARTIFACTS_DIR / "adjudication_ab_union_base.json")
                      .read_text(encoding="utf-8-sig"))["rows"]
    m, cok = scenario_map_from_rows(rows)
    cp = h.counterparts(cok, rows, m, cok)
    assert all(cp[k] == k for k in m)
