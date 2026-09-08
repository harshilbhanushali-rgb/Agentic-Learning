"""ask_naren/rendering.py -- the answers built from stored rows (issues #19, #20).

THE PROPERTY EVERY TEST HERE PROTECTS: these paths never generate, so they cannot invent.
A rendered list of the coachable scenarios cannot emit a 35th, and a rendered exchange
cannot drift from the exchange. There is no gateway in this file because there is no
gateway in the module -- that absence IS the guarantee, and `test_ask_naren_responding.py`
pins it from the outside by asserting no generation happens.
"""
import numpy as np

from ask_naren import rendering, retrieval

CALL = "20230503_uber_joveo_weekly_performance_review_d18cc178.txt"
TRIGGER = "our cost per hire looks terrible this quarter"
RESPONSE = "Pull the last 90 days and show cost per hire against their own baseline."


def _scenario(key, topic="Performance", desc="", calls=0, coverage=None):
    return {"scenario_key": key, "primary_topic": topic, "business_description": desc,
            "support_calls": calls, "call_coverage": coverage}


def _pool():
    pairs = [{"pair_id": 11, "trigger_text": TRIGGER, "response_text": RESPONSE,
              "call_filename": CALL, "scenario_key": "performance_pushback"}]
    return retrieval.RetrievalPool(pairs, np.array([[1.0, 0.0]]))


def _match():
    return _pool().top1(np.array([1.0, 0.0]))


# -- discovery (issue #19) -----------------------------------------------------------------

def test_discovery_groups_scenarios_by_primary_topic():
    result = rendering.discovery([
        _scenario("performance_pushback", "Performance"),
        _scenario("spend_pacing", "Budget"),
        _scenario("cpa_complaints", "Performance"),
    ])
    assert result["outcome"] == "rendered"
    assert result["kind"] == "discovery"
    assert [t["topic"] for t in result["topics"]] == ["Budget", "Performance"]
    assert result["total"] == 3


def test_discovery_cannot_emit_a_scenario_the_taxonomy_does_not_have():
    """The whole reason this path renders instead of generating (#12: "a rendered list of
    the 34 scenario descriptions cannot invent a 35th topic"). Every key out came from a
    row in."""
    given = {"performance_pushback", "spend_pacing"}
    result = rendering.discovery([_scenario(k) for k in sorted(given)])
    emitted = {s["scenario_key"] for t in result["topics"] for s in t["scenarios"]}
    assert emitted == given


def test_a_scenario_with_no_primary_topic_is_grouped_rather_than_dropped():
    """Dropping it would quietly under-report what the tool covers, which is the one thing
    this intent exists to get right."""
    result = rendering.discovery([_scenario("orphan", topic="")])
    assert result["total"] == 1
    assert result["topics"][0]["topic"] == "Other"


# -- frequency (issue #19) -----------------------------------------------------------------

def test_frequency_ranks_by_the_calls_a_scenario_was_drawn_from():
    result = rendering.frequency([
        _scenario("rare", calls=2), _scenario("common", calls=40),
        _scenario("middling", calls=11),
    ])
    assert [s["scenario_key"] for s in result["scenarios"]] == ["common", "middling", "rare"]


def test_frequency_says_what_it_is_ranking_rather_than_letting_a_csm_assume():
    """It ranks THIS CORPUS, not the world. A CSM reading "most common" without that
    qualifier would take it as a fact about clients, which Ask Naren has no telemetry to
    support."""
    result = rendering.frequency([_scenario("x", calls=1)])
    assert "corpus" in result["basis"]


def test_frequency_shows_the_head_not_all_34():
    result = rendering.frequency([_scenario(f"s{n}", calls=n) for n in range(30)],
                                 top_n=5)
    assert len(result["scenarios"]) == 5
    assert result["total"] == 30           # and still reports how many there really are


def test_a_scenario_with_no_recorded_support_ranks_last_rather_than_crashing():
    result = rendering.frequency([_scenario("unknown", calls=None), _scenario("known", calls=3)])
    assert [s["scenario_key"] for s in result["scenarios"]] == ["known", "unknown"]


# -- show_exchange (issue #20) --------------------------------------------------------------

def test_show_exchange_returns_the_stored_text_untouched():
    """A CSM asking to SEE the exchange wants to judge the fit themselves. A paraphrase
    would defeat the entire intent."""
    result = rendering.show_exchange(_match(), label_for=lambda f: "Uber - 3 May 2023")
    assert result["kind"] == "show_exchange"
    assert result["exchange"]["client_said"] == TRIGGER
    assert result["exchange"]["naren_replied"] == RESPONSE
    assert result["citation"]["label"] == "Uber - 3 May 2023"


def test_show_exchange_carries_no_generated_prose_at_all():
    """Nothing in this response may be model-written, because no model ran."""
    result = rendering.show_exchange(_match())
    assert "answer" not in result and "quote" not in result


# -- what_happened_next (issue #20) ---------------------------------------------------------

def test_what_happened_next_returns_the_following_exchanges_in_order():
    following = [
        {"trigger_text": "so what do we do about it", "response_text": "Start with pacing.",
         "scenario_key": "spend_pacing"},
        {"trigger_text": "and the timeline", "response_text": "Two weeks.",
         "scenario_key": "timeline_question"},
    ]
    result = rendering.what_happened_next(_match(), following)
    assert result["kind"] == "what_happened_next"
    assert [f["client_said"] for f in result["following"]] == [
        "so what do we do about it", "and the timeline"]
    assert result["is_last"] is False


def test_the_last_exchange_in_a_call_says_so_rather_than_returning_an_empty_list():
    """An empty list is something a CSM has to interpret. "There was nothing after this" is
    an answer."""
    result = rendering.what_happened_next(_match(), [])
    assert result["is_last"] is True
    assert result["following"] == []


# -- coverage_check (issue #20) -------------------------------------------------------------

def test_coverage_check_is_an_answer_not_a_decline():
    """The whole point of the intent. Today a CSM cannot tell "Ask Naren has nothing on
    this" from "I asked it the wrong way" because both look like a decline -- so the intent
    that separates them must never itself decline."""
    result = rendering.coverage_check("renewals", _match(),
                                      _scenario("performance_pushback", desc="Client "
                                                "challenges performance against the pitch.",
                                                calls=12))
    assert result["outcome"] == "rendered"
    assert result["nearest"]["scenario_key"] == "performance_pushback"
    assert result["nearest"]["support_calls"] == 12
    assert result["asked_about"] == "renewals"


def test_coverage_check_survives_a_scenario_the_taxonomy_no_longer_has():
    """The pool is a startup snapshot and Layer A can move under it. A missing row must
    degrade to a thinner answer rather than raise."""
    result = rendering.coverage_check("renewals", _match(), None)
    assert result["nearest"]["description"] == ""
    assert result["nearest"]["support_calls"] == 0
