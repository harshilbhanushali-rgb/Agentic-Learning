"""ask_naren/rendering.py -- the answers built from stored rows (issues #19, #20).

THE PROPERTY EVERY TEST HERE PROTECTS: these paths never generate, so they cannot invent.
A rendered list of the coachable scenarios cannot emit a 35th, and a rendered exchange
cannot drift from the exchange. There is no gateway in this file because there is no
gateway in the module -- that absence IS the guarantee, and `test_ask_naren_responding.py`
pins it from the outside by asserting no generation happens.
"""
import asyncio
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
    return asyncio.run(_pool().top1(np.array([1.0, 0.0])))


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


def test_what_happened_next_reports_the_match_it_retrieved_like_show_exchange():
    """Issue #45: it retrieves its exchange exactly as `show_exchange` does, so it reports
    the same block -- otherwise a stored turn records NULL for a cosine that was computed."""
    match = _match()
    result = rendering.what_happened_next(match, [])
    assert result["match"] == rendering.show_exchange(match)["match"]
    assert result["match"] == {"cosine": match.cosine,
                               "scenario_key": "performance_pushback", "rank": 1}
    assert isinstance(result["match"]["cosine"], float)


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


# -- which accounts a situation has come up with (issue #22) --------------------------------

from ask_naren import citations                                        # noqa: E402

UBER_A = "20230503_uber_joveo_weekly_performance_review_d18cc178.txt"
UBER_B = "20230509_uber_joveo_connect_409d34b7.txt"
RECKITT = "015a5979-4c9f-44ae-9b9d-f642529a5478.txt"
OPAQUE = "3e4c3393-c3cc-4047-a5bc-57bccbfaee4f.txt"

#: The RECORDED PARTICIPANTS, which is the only thing that names an account (issue #22).
#: Both Uber calls resolve through it, exactly as they do live -- the filename cannot name
#: them, because `uber_corporate` and `uber_emea` are one company and two calendar titles.
SIDECARS = {RECKITT: "Reckitt", UBER_A: "Uber", UBER_B: "Uber"}


def _seen(call, pair_id=1, cosine=0.8):
    return retrieval.Match(
        pair={"pair_id": pair_id, "call_filename": call, "trigger_text": TRIGGER,
              "response_text": RESPONSE, "scenario_key": "performance_pushback"},
        cosine=cosine)


def _accounts(index=SIDECARS):
    return lambda call: citations.account_for(call, index)


def test_exchanges_from_the_same_account_collapse_into_one_entry():
    """The question is "one client quirk or a pattern across the book", so two calls with
    the same client must read as one client rather than two."""
    result = rendering.where_else_seen(
        "cost per hire pushback",
        [_seen(UBER_A, 1), _seen(UBER_B, 2), _seen(UBER_A, 3)], account_for=_accounts())
    named = [a for a in result["accounts"] if a["named"]]
    assert len(named) == 1
    assert named[0]["account"] == "Uber"
    assert named[0]["exchanges"] == 3
    assert named[0]["calls"] == 2


def test_a_call_the_data_cannot_name_is_shown_as_its_filename_not_guessed_or_dropped():
    """#22's stated constraint: a wrong client name is worse than an opaque one. Dropping it
    would UNDER-report the spread; guessing would name the wrong client. So it is listed as
    exactly what it is."""
    result = rendering.where_else_seen(
        "x", [_seen(UBER_A, 1), _seen(OPAQUE, 2)], account_for=_accounts())
    unnamed = [a for a in result["accounts"] if not a["named"]]
    assert len(unnamed) == 1
    assert unnamed[0]["account"] == OPAQUE


def test_the_account_count_is_a_range_because_the_unnamed_calls_might_be_anyone():
    """The honest answer to "how many clients". Two named accounts plus two calls nothing
    can name is between two and four distinct clients -- each unnamed call could be a new
    client or could be one of the two already listed. A single number picks one end of that
    and states it as fact."""
    result = rendering.where_else_seen(
        "x", [_seen(UBER_A, 1), _seen(RECKITT, 2), _seen(OPAQUE, 3), _seen("Call9.txt", 4)],
        account_for=_accounts())
    assert result["accounts_named"] == 2
    assert result["accounts_at_most"] == 4
    assert result["unnamed_calls"] == 2


def test_absent_sidecars_degrade_to_filenames_rather_than_breaking():
    """Criterion 3, and the behaviour on any machine without the (gitignored, machine-local)
    recordings directories.

    IT DEGRADES FURTHER THAN IT USED TO, and that is the correct trade. The participant
    sidecars are now the ONLY thing that names an account, so with no index NOTHING is named
    -- where reading the filename would have named some. What reading the filename actually
    produced was "Review" for a call with AMN Healthcare and five separate Ubers, so the
    coverage it bought was partly wrong.

    Thinner, not broken: still a `rendered` answer, every call shown as the filename it
    really is, and `accounts_at_least` keeping the range from claiming zero clients for two
    real exchanges."""
    result = rendering.where_else_seen(
        "x", [_seen(RECKITT, 1), _seen(UBER_A, 2)], account_for=_accounts(index={}))
    assert result["outcome"] == "rendered"
    assert result["accounts_named"] == 0
    assert result["unnamed_calls"] == 2
    assert result["accounts_at_least"] == 1     # two exchanges came from somebody
    assert all(a["named"] is False for a in result["accounts"])


def test_where_else_seen_generates_nothing_and_carries_no_answer():
    result = rendering.where_else_seen("x", [_seen(UBER_A)], account_for=_accounts())
    assert result["outcome"] == "rendered"
    assert result["kind"] == "where_else_seen"
    assert "answer" not in result and "quote" not in result


def test_accounts_are_ranked_by_what_they_carry_with_named_ones_first():
    """A CSM scanning this wants the pattern first. An unnameable call is real evidence but
    nothing they can act on, so it sorts below every account that has a name -- even when it
    carries more exchanges."""
    result = rendering.where_else_seen(
        "x", [_seen(OPAQUE, 1), _seen(OPAQUE, 2), _seen(OPAQUE, 3),
              _seen(UBER_A, 4), _seen(RECKITT, 5), _seen(RECKITT, 6)],
        account_for=_accounts())
    assert [a["account"] for a in result["accounts"]][:2] == ["Reckitt", "Uber"]
    assert result["accounts"][-1]["named"] is False


def test_an_empty_ranking_raises_rather_than_reporting_that_nobody_else_raised_it():
    """ADR 0008 and the same rule `RetrievalPool.top1` states: an empty authorised ranking
    is a fact about the INDEX, not about the corpus -- the store and the pool disagree about
    what exists.

    Every other retrieving path already raises on it. Rendered as an answer this one would
    say "0 accounts, across 0 exchanges", which a CSM reads as "no other client has ever
    raised this" -- the exact wrong conclusion this intent exists to prevent, and a broken
    index hidden behind a normal-looking answer for as long as nobody checked."""
    import pytest
    with pytest.raises(RuntimeError, match="no kb_pair the pool authorises"):
        rendering.where_else_seen("x", [], account_for=_accounts())


def test_the_range_floor_is_never_zero_once_an_exchange_was_found():
    """Criterion 3's shape: with no participant sidecars every UUID call is unnameable, so
    `accounts_named` is 0 -- but three recorded exchanges cannot have come from zero
    clients. "Between 0 and 3 accounts" states something impossible; the honest floor is 1.

    `accounts_named` stays a plain fact (how many we could name). `accounts_at_least` is what
    the range is rendered from."""
    result = rendering.where_else_seen(
        "x", [_seen(OPAQUE, 1), _seen(OPAQUE, 2), _seen("Call9.txt", 3)],
        account_for=_accounts())
    assert result["accounts_named"] == 0
    assert result["accounts_at_least"] == 1
    assert result["accounts_at_most"] == 2      # two distinct calls nothing can name


def test_the_floor_is_the_named_count_when_there_is_one():
    result = rendering.where_else_seen(
        "x", [_seen(UBER_A, 1), _seen(RECKITT, 2), _seen(OPAQUE, 3)],
        account_for=_accounts())
    assert result["accounts_named"] == 2
    assert result["accounts_at_least"] == 2
    assert result["accounts_at_most"] == 3


def test_where_else_seen_names_its_scenario_and_says_how_coherent_the_neighbourhood_is():
    """#12's story 10 wants every answer to name the scenario it is about, so a CSM can see
    a misroute. This path had no `match` block at all, which left it the one Layer B answer
    a CSM could not check.

    It matters more here than elsewhere, because the answer is an aggregate over 25
    neighbours and `ask-naren/audit/artifacts/topk_headroom.json` measures the top-20
    neighbourhood as only 6.19/20 same-situation on average. So some of the accounts listed
    are about something else, and without this the CSM cannot tell a genuine book-wide
    pattern from a wide, incoherent neighbourhood -- which is exactly the discrimination
    this intent exists to provide."""
    result = rendering.where_else_seen(
        "x",
        [_seen(UBER_A, 1), _seen(RECKITT, 2), _seen(OPAQUE, 3)],
        account_for=_accounts())
    assert result["scenario_key"] == "performance_pushback"
    assert result["same_scenario"] == 3
    assert result["exchanges"] == 3


def test_a_neighbourhood_that_drifted_reports_how_far():
    """The number that makes the drift visible rather than inferable."""
    drifted = _seen(OPAQUE, 4)
    drifted.pair["scenario_key"] = "timeline_question"
    result = rendering.where_else_seen(
        "x", [_seen(UBER_A, 1), _seen(RECKITT, 2), drifted], account_for=_accounts())
    assert result["scenario_key"] == "performance_pushback"   # the nearest one
    assert result["same_scenario"] == 2
    assert result["exchanges"] == 3


# -- the two composites (issue #23) ---------------------------------------------------------
#
# BOTH RENDER, and that is the reading of criterion 3 ("composes existing answer paths rather
# than introducing a new grounding rule"). Composing only RENDERED paths means there is
# nothing to mix: ADR 0009 warns that stitching a Layer C summary to a Layer B answer
# inherits the weaker of the two guarantees, and the way not to inherit a weaker guarantee is
# not to take one on.

def _prep_scenarios():
    return [_scenario("performance_pushback", desc="Client challenges the pitch.", calls=40),
            _scenario("timeline_question", desc="Client asks when it lands.", calls=9)]


def _prep_playbooks():
    return {"performance_pushback": {"playbook": PLAYBOOK, "n_evidence": 7}}


def test_call_prep_names_the_likely_scenarios_with_their_plays_and_a_real_example():
    other = _seen(UBER_B, 2)
    other.pair["scenario_key"] = "timeline_question"
    result = rendering.call_prep(
        "renewal call tomorrow", [_seen(UBER_A, 1), other, _seen(RECKITT, 3)],
        scenarios=_prep_scenarios(), playbook_for=_prep_playbooks().get,
        label_for=lambda f: "Uber - 3 May 2023")
    assert result["outcome"] == "rendered"
    assert result["kind"] == "call_prep"
    keys = [s["scenario_key"] for s in result["scenarios"]]
    assert keys[0] == "performance_pushback"      # most exchanges first
    assert "timeline_question" in keys
    first = result["scenarios"][0]
    assert first["description"] == "Client challenges the pitch."
    assert first["steps"] == ["Reframe on their own baseline", "Agree a realistic target"]
    assert first["example"]["naren_replied"] == RESPONSE
    assert first["example"]["citation"]["label"] == "Uber - 3 May 2023"


def test_call_prep_says_plainly_when_a_scenario_has_no_recorded_play():
    """1 of 34 coachable scenarios has no live playbook. Showing the scenario with an empty
    step list would read as "there is no play here"; saying so is an answer."""
    other = _seen(UBER_B, 2)
    other.pair["scenario_key"] = "timeline_question"
    result = rendering.call_prep(
        "x", [_seen(UBER_A, 1), other], scenarios=_prep_scenarios(),
        playbook_for=_prep_playbooks().get)
    by_key = {s["scenario_key"]: s for s in result["scenarios"]}
    assert by_key["performance_pushback"]["has_play"] is True
    assert by_key["timeline_question"]["has_play"] is False
    assert by_key["timeline_question"]["steps"] == []


def test_call_prep_generates_nothing_and_shows_stored_text_verbatim():
    result = rendering.call_prep(
        "x", [_seen(UBER_A, 1)], scenarios=_prep_scenarios(),
        playbook_for=_prep_playbooks().get)
    assert "answer" not in result and "quote" not in result
    assert result["scenarios"][0]["example"]["client_said"] == TRIGGER


def test_call_prep_raises_on_an_empty_ranking_like_every_other_retrieving_path():
    import pytest
    with pytest.raises(RuntimeError, match="no kb_pair the pool authorises"):
        rendering.call_prep("x", [], scenarios=_prep_scenarios(),
                            playbook_for=_prep_playbooks().get)


def test_improve_at_move_focuses_the_move_the_csm_actually_named():
    """Criterion 2: the criterion, its pitfalls, and Naren doing it. The move is chosen by
    plain word overlap with what the CSM asked -- deterministic, no model, no embedding."""
    result = rendering.improve_at_move(
        "i want to get better at reframing on their own baseline",
        "performance_pushback", {"playbook": PLAYBOOK, "n_evidence": 7},
        label_for=lambda f: "Uber - 3 May 2023")
    assert result["kind"] == "improve_at_move"
    assert result["focused"] is True
    assert len(result["moves"]) == 1
    move = result["moves"][0]
    assert move["name"] == "Reframe on their own baseline"
    assert move["criterion"] == "Compare against history."
    assert move["evidence"][0]["quote"] == "against their own baseline"
    assert move["evidence"][0]["label"] == "Uber - 3 May 2023"
    assert result["pitfalls"][0]["text"].startswith("Quoting the market benchmark")


def test_improve_at_move_shows_every_move_when_nothing_the_csm_said_matches_one():
    """DEGRADES TO THE WHOLE PLAY rather than guessing a move. Picking one on no evidence
    would answer a question the CSM did not ask, and `focused` says which happened."""
    result = rendering.improve_at_move(
        "i want to get better at this", "performance_pushback",
        {"playbook": PLAYBOOK, "n_evidence": 7})
    assert result["focused"] is False
    assert [m["name"] for m in result["moves"]] == ["Reframe on their own baseline"]


def test_improve_at_move_names_its_scenario_and_generates_nothing():
    result = rendering.improve_at_move("x", "performance_pushback",
                                       {"playbook": PLAYBOOK, "n_evidence": 7})
    assert result["scenario_key"] == "performance_pushback"
    assert result["outcome"] == "rendered"
    assert "answer" not in result and "quote" not in result


def test_call_prep_breaks_ties_by_nearness_rather_than_alphabetically():
    """MEASURED WHY THIS MATTERS: `topk_headroom.json` puts the top-20 neighbourhood at a
    mean of 6.19/20 same-situation, so ONE scenario usually dominates and the rest of the
    list is a long tail of singletons. Positions 2 and 3 -- two of the three things a CSM is
    told to walk into the call ready for -- are therefore decided by the tiebreak almost
    every time.

    Sorting on the key would hand them to whichever scenario starts with the earliest
    letter, and `application_volume_and_prioritization` -- the catch-all ADR 0009 names,
    carrying 11.8% of coachable pairs with 16% of what routes there off-topic -- starts with
    'a' and would win nearly every tie. Python's sort is stable and the groups are built
    nearest-first, so dropping the key restores proximity for free."""
    near = _seen(UBER_A, 1)
    near.pair["scenario_key"] = "zzz_the_second_nearest"
    far = _seen(UBER_B, 2)
    far.pair["scenario_key"] = "aaa_much_further_away"
    dominant = [_seen(RECKITT, 10 + i) for i in range(3)]
    for m in dominant:
        m.pair["scenario_key"] = "performance_pushback"

    result = rendering.call_prep(
        "x", dominant + [near, far], scenarios=_prep_scenarios(),
        playbook_for=_prep_playbooks().get)
    keys = [s["scenario_key"] for s in result["scenarios"]]
    assert keys == ["performance_pushback", "zzz_the_second_nearest", "aaa_much_further_away"]
