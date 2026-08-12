"""Tests for ego_trap/scenario_pool.py -- the Layer D two-population split."""
from ego_trap import scenario_pool


def _scn(coachable=True, kind="scenario", status="rubric_generated"):
    return {"is_coachable": coachable, "cluster_kind": kind, "rubric_status": status}


def _pool():
    return {
        "budget_disclosure": _scn(),
        "ats_integration": _scn(),
        "conversational_fillers": _scn(False, "mechanics"),
        "scheduling_logistics": _scn(False, "logistics"),
    }


def test_coachable_only_drops_sinks():
    assert set(scenario_pool.coachable_only(_pool())) == {
        "budget_disclosure", "ats_integration"
    }


def test_sink_keys_is_the_complement():
    pool = _pool()
    coachable = scenario_pool.coachable_only(pool)
    assert scenario_pool.sink_keys(pool) == set(pool) - set(coachable)


def test_missing_is_coachable_defaults_to_coachable():
    """Matches shared.relative_match.is_sink_flags, so the two definitions of "sink"
    cannot drift apart."""
    assert scenario_pool.is_coachable({}) is True
    assert set(scenario_pool.coachable_only({"a": {}})) == {"a"}


def test_coachable_without_rubric_is_kept():
    """A scenario Layer C could not build a rubric for is still a real coachable topic.
    Filtering it out at detection time would hide the coverage gap that Layer D exists
    to report -- 'a client raised this and we have no answer key'."""
    pool = {"new_topic": _scn(status="skipped_insufficient_responses")}
    assert "new_topic" in scenario_pool.coachable_only(pool)


def test_a_graduated_sink_appears_with_no_code_change():
    """response_taxonomy_auto_pass flips is_coachable on a previously-sunk scenario
    between runs. The split must be derived from the data, never a hardcoded key list."""
    pool = _pool()
    assert "conversational_fillers" not in scenario_pool.coachable_only(pool)
    pool["conversational_fillers"]["is_coachable"] = True
    assert "conversational_fillers" in scenario_pool.coachable_only(pool)


def test_cluster_kind_alone_does_not_decide():
    """is_coachable is the load-bearing field. A row whose cluster_kind says mechanics
    but which has been graduated to coachable must be treated as coachable."""
    pool = {"odd": _scn(coachable=True, kind="mechanics")}
    assert "odd" in scenario_pool.coachable_only(pool)


def test_pool_summary_reports_the_split_and_the_coverage_gap():
    pool = _pool()
    pool["no_rubric_yet"] = _scn(status="skipped_insufficient_responses")
    summary = scenario_pool.pool_summary(pool)
    assert "5 total" in summary
    assert "3 coachable" in summary
    assert "2 sink" in summary
    assert "1 mechanics" in summary and "1 logistics" in summary
    assert "1 coachable scenario(s) have no rubric" in summary


def test_pool_summary_handles_an_all_coachable_pool():
    summary = scenario_pool.pool_summary({"a": _scn()})
    assert "0 sink (none)" in summary


def test_empty_pool_is_not_an_error():
    assert scenario_pool.coachable_only({}) == {}
    assert scenario_pool.sink_keys({}) == set()
    assert "0 total" in scenario_pool.pool_summary({})
