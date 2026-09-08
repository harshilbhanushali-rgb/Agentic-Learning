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
    assert result["grouped"] is True
    assert [t["topic"] for t in result["topics"]] == ["Budget", "Performance"]
    assert result["total"] == 3


def test_discovery_cannot_emit_a_scenario_the_taxonomy_does_not_have():
    """The whole reason this path renders instead of generating (#12: "a rendered list of
    the 34 scenario descriptions cannot invent a 35th topic"). Every key out came from a
    row in."""
    given = {"performance_pushback", "spend_pacing"}
    result = rendering.discovery([_scenario(k) for k in sorted(given)])
    # Read from BOTH shapes, so the assertion holds whether or not the taxonomy happens to
    # support grouping -- the property is about what can be emitted, not about the layout.
    emitted = ({s["scenario_key"] for t in result["topics"] for s in t["scenarios"]}
               | {s["scenario_key"] for s in result["scenarios"]})
    assert emitted == given


def test_a_scenario_with_no_primary_topic_is_kept_rather_than_dropped():
    """Dropping it would quietly under-report what the tool covers, which is the one thing
    this intent exists to get right."""
    result = rendering.discovery([_scenario("orphan", topic="")])
    assert result["total"] == 1
    assert [s["scenario_key"] for s in result["scenarios"]] == ["orphan"]


def test_a_taxonomy_with_one_topic_renders_flat_rather_than_inventing_a_heading():
    """MEASURED on the live taxonomy 2026-09-09: all 259 scenarios carry
    `primary_topic = 'ungrouped'` and `primary_topic_key` is NULL, and the primary-topic
    hierarchy is recorded as rejected. Grouping would put all 34 coachable situations under
    one heading called "ungrouped", which tells a CSM the tool is disorganised rather than
    that one field was never populated for this taxonomy."""
    result = rendering.discovery([_scenario(k, topic="ungrouped")
                                  for k in ("a", "b", "c")])
    assert result["grouped"] is False
    assert result["topics"] == []
    assert [s["scenario_key"] for s in result["scenarios"]] == ["a", "b", "c"]
    assert result["total"] == 3


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


def test_coverage_check_flags_thin_evidence_rather_than_implying_coverage():
    """Retrieval returns a nearest exchange for ANY string, so a confident "the closest
    thing we cover is X" reads as a yes even when the topic is absent. It cannot say "we do
    not cover that" either -- ADR 0005 rules out a cosine threshold -- so it reports how
    much evidence sits behind the nearest thing and lets the CSM judge."""
    thin = rendering.coverage_check("quantum widgets", _match(), _scenario("x", calls=1))
    assert thin["nearest"]["evidence"] == "thin"
    solid = rendering.coverage_check("cost per hire", _match(), _scenario("x", calls=40))
    assert solid["nearest"]["evidence"] == "solid"


def test_coverage_check_quotes_the_csm_not_the_extracted_query():
    """The page renders `asked_about` back in quote marks. Quoting a model-authored span as
    though the CSM wrote it is a small lie that gets believed."""
    result = rendering.coverage_check("do you have anything on renewals?", _match(), None)
    assert result["asked_about"] == "do you have anything on renewals?"


# -- the Layer C playbook, rendered (issue #18) ---------------------------------------------

PLAYBOOK = {
    "situation_signature": "The client challenges cost per hire against what was pitched.",
    "arc": ["Reframe on their own baseline", "Agree a realistic target"],
    "key_moves": [
        {"name": "Reframe on their own baseline", "criterion": "Compare against history.",
         "evidence": [{"quote": "against their own baseline", "call": CALL}]},
    ],
    "signature_language": [
        {"phrase": "their own baseline", "quote": "show them cost per hire against their "
         "own baseline", "call": CALL, "account": "uber.com"},
        {"phrase": "", "quote": "  ", "call": CALL, "account": "uber.com"},
    ],
    "pitfalls_and_variants": [
        {"text": "Quoting the market benchmark instead of their own history.",
         "evidence": [{"quote": "not against our benchmark", "call": CALL}]},
    ],
}
RECORD = {"playbook": PLAYBOOK, "n_evidence": 7}


def test_sequence_renders_the_arc_in_order():
    """`db/schema.sql` records that the order is load-bearing, so nothing re-sorts it."""
    result = rendering.sequence("performance_pushback", PLAYBOOK)
    assert result["kind"] == "sequence"
    assert result["steps"] == ["Reframe on their own baseline", "Agree a realistic target"]


def test_phrasing_pairs_every_phrase_with_the_quote_it_came_from():
    """The strongest-grounded path in the tool, by accident of shape: a signature_language
    entry is phrase-and-quote one-to-one, so unlike a `procedure` answer (ADR 0009) there is
    no part of this that a quote does not cover."""
    result = rendering.phrasing("performance_pushback", PLAYBOOK)
    assert len(result["phrases"]) == 1          # the quote-less entry is not a phrase
    assert result["phrases"][0]["phrase"] == "their own baseline"
    assert "own baseline" in result["phrases"][0]["quote"]


def test_pitfalls_shows_the_claim_and_the_moment_it_came_from():
    result = rendering.pitfalls("performance_pushback", PLAYBOOK)
    assert result["pitfalls"][0]["text"].startswith("Quoting the market benchmark")
    assert result["pitfalls"][0]["evidence"][0]["quote"] == "not against our benchmark"


def test_scenario_check_does_not_answer_yes_or_no():
    """Whether a play fits a live client is a judgement about a situation Ask Naren has only
    the CSM's sentence for. Claiming it would be the confident-and-wrong answer a catch-all
    scenario produces, so it shows WHEN the play applies and lets the CSM compare."""
    result = rendering.scenario_check("client keeps comparing us to Indeed",
                                      "performance_pushback", PLAYBOOK)
    assert result["applies_when"].startswith("The client challenges cost per hire")
    assert result["asked_about"] == "client keeps comparing us to Indeed"
    assert "applies" not in result.get("answer", "")     # there is no verdict field at all


def test_play_confidence_reports_the_records_evidence_count_not_the_documents():
    """`n_evidence` sits BESIDE the document rather than inside it, which is why the service
    keeps the whole row. Reading it off the document would report zero for every play."""
    result = rendering.play_confidence("performance_pushback", RECORD)
    assert result["n_evidence"] == 7
    assert result["moves"] == 1
    assert result["quotes"] == 1
    assert "not whether the play is right" in result["basis"]


def test_play_confidence_says_when_n_evidence_is_the_selection_cap_rather_than_a_count():
    """MEASURED on the live rows, 2026-09-09: 25 of 33 live playbooks carry n_evidence == 50
    exactly, because `playbook_backfill` sets it to len(selected evidence) with the selection
    capped at N_EVIDENCE_MAX = 50 -- and never recomputes it after the verbatim snap drops
    quotes and moves.

    So for three quarters of the corpus it is a constant, and it can invert the truth:
    programmatic_advertising_scope_and_capability shows 50 and rests on 8 verified quotes,
    while non_technical_stakeholder_translation shows 16 and rests on 9. Reported bare, the
    number a CSM reads as 3x better evidenced is the thinner play.

    `Brain/docs/findings/layer-d-say-arm.md` already recorded the median as 50 for both good
    and bad move groups, so this is a re-derivation of a measured non-signal."""
    capped = rendering.play_confidence("k", {"playbook": PLAYBOOK, "n_evidence": 50})
    assert capped["n_evidence_capped"] is True
    assert rendering.play_confidence("k", RECORD)["n_evidence_capped"] is False


def test_play_confidence_leads_with_what_survived_the_snap():
    """Criterion 5 asks what the play RESTS ON. `moves` and `quotes` are counted from the
    live document, so they describe what is really there; `n_evidence` describes what was
    fed to the builder before the snap. The basis line must not present the second as the
    first."""
    result = rendering.play_confidence("k", {"playbook": PLAYBOOK, "n_evidence": 50})
    assert "considered" in result["basis"]
    assert result["quotes"] == 1 and result["moves"] == 1


def test_phrasing_attributes_every_quote_to_the_call_it_came_from():
    """A verbatim client-call quote shown with no attribution is exactly what ADR 0002 says
    a citation exists to prevent -- "a verifiable, real citation is what makes the answer
    trustworthy rather than a bare assertion". ADR 0009 singles this path out as the one
    that can vouch for its whole answer, so it is the last place to drop the source.

    `label` beside `call` rather than replacing it, matching `answering._citation`: the raw
    filename stays for an engineer tracing a bad answer."""
    result = rendering.phrasing("performance_pushback", PLAYBOOK,
                                label_for=lambda f: "Uber · 3 May 2023")
    assert result["phrases"][0]["call"] == CALL
    assert result["phrases"][0]["label"] == "Uber · 3 May 2023"


def test_pitfalls_attributes_every_quote_to_the_call_it_came_from():
    result = rendering.pitfalls("performance_pushback", PLAYBOOK,
                                label_for=lambda f: "Uber · 3 May 2023")
    assert result["pitfalls"][0]["evidence"][0]["call"] == CALL
    assert result["pitfalls"][0]["evidence"][0]["label"] == "Uber · 3 May 2023"


def test_an_unresolvable_call_falls_back_to_the_raw_filename_rather_than_showing_nothing():
    """`resolve_label` returns the raw filename whenever resolution would have to guess, and
    31.3% of citable calls are opaque UUIDs. An empty label would render a quote with a
    blank source line, which reads as less trustworthy than the filename it really has."""
    result = rendering.phrasing("performance_pushback", PLAYBOOK, label_for=lambda f: "")
    assert result["phrases"][0]["label"] == CALL


def test_every_playbook_render_is_still_a_rendered_outcome():
    for result in (rendering.sequence("k", PLAYBOOK), rendering.phrasing("k", PLAYBOOK),
                   rendering.pitfalls("k", PLAYBOOK),
                   rendering.scenario_check("x", "k", PLAYBOOK),
                   rendering.play_confidence("k", RECORD)):
        assert result["outcome"] == "rendered"
        assert "answer" not in result and "quote" not in result
