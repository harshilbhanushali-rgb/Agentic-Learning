"""ask_naren/grounding.py -- the grounding gate (ask-naren/CONTEXT.md), on hand-built text.

What each test protects: an answer that reaches a CSM carrying a quote that is not really
in the cited response, or citing a call that was never retrieved. ADR 0002's guarantee is
supposed to hold on every live answer, not on average across an eval.
"""
from ask_naren import grounding

RESPONSE = (
    "Yeah, so what I usually do there is pull the last 90 days of spend and show them "
    "cost per hire against their own baseline, not against our benchmark. That reframes "
    "the whole conversation."
)
CALL = "20230503_uber_joveo_weekly_performance_review_d18cc178.txt"
MATCHED = {"response_text": RESPONSE, "call_filename": CALL}


def _model(answer="Pull their last 90 days of spend and reframe on their own baseline.",
           quote="show them cost per hire against their own baseline",
           cited_call=CALL):
    return {"declined": False, "answer": answer, "quote": quote, "cited_call": cited_call}


def test_a_real_quote_from_the_retrieved_call_passes():
    assert grounding.check(_model(), grounding.from_pairs([MATCHED])).passed


def test_case_and_punctuation_differences_do_not_fail_a_real_quote():
    """A model re-capitalising or dropping a comma has not fabricated anything. Uses
    layer_d.verify_quotes, whose normalization Brain already settled for exactly this."""
    quote = "Show them Cost Per Hire against their own baseline!"
    assert grounding.check(_model(quote=quote), grounding.from_pairs([MATCHED])).passed


def test_a_fabricated_quote_is_refused():
    result = grounding.check(_model(quote="we guarantee a 40% lift by Friday"),
                             grounding.from_pairs([MATCHED]))
    assert not result.passed
    assert result.reason == "quote_not_verbatim"


def test_a_paraphrase_of_the_response_is_not_a_verbatim_quote():
    """The gate is verbatim containment, not similarity -- a close paraphrase is exactly
    the failure mode that reads as grounded and is not."""
    quote = "showed them their cost-per-hire versus their own historical baseline numbers"
    assert not grounding.check(_model(quote=quote), grounding.from_pairs([MATCHED])).passed


def test_an_empty_quote_never_passes():
    result = grounding.check(_model(quote="   "), grounding.from_pairs([MATCHED]))
    assert not result.passed
    assert result.reason == "quote_not_verbatim"


def test_a_real_quote_under_a_call_it_was_not_shown_cites_the_call_it_is_in():
    """Since 2026-11-07 the gate checks the QUOTE against everything shown and cites where it
    really is. A wrong `cited_call` with a verbatim quote is a citation slip, not an invented
    quote -- the CSM is shown the call the words actually come from."""
    result = grounding.check(_model(cited_call="some_other_call.txt"),
                             grounding.from_pairs([MATCHED]))
    assert result.passed and result.corrected
    assert result.source.identifier == CALL


def test_a_fabricated_quote_under_a_call_it_was_not_shown_is_refused():
    result = grounding.check(_model(quote="we guarantee a 40% lift by Friday",
                                    cited_call="some_other_call.txt"),
                             grounding.from_pairs([MATCHED]))
    assert not result.passed
    assert result.reason == "wrong_call_cited"


def test_a_quote_in_the_call_it_names_is_not_marked_corrected():
    assert not grounding.check(_model(), grounding.from_pairs([MATCHED])).corrected


def test_a_citation_differing_only_in_case_or_spacing_still_passes():
    assert grounding.check(_model(cited_call=f"  {CALL.upper()} "), grounding.from_pairs([MATCHED])).passed


def test_an_empty_answer_is_refused_even_when_the_quote_verifies():
    """A verified quote with nothing built on it is not an answer; forwarding it would show
    a CSM a citation and no guidance."""
    result = grounding.check(_model(answer="  "), grounding.from_pairs([MATCHED]))
    assert not result.passed
    assert result.reason == "empty_answer"


def test_a_missing_key_is_refused_rather_than_treated_as_absent_evidence():
    """A malformed payload must fail closed. `.get` returning None on `quote` is the one
    shape that could otherwise slip through a truthiness check as 'nothing to verify'."""
    assert not grounding.check({"declined": False, "answer": "x"},
                               grounding.from_pairs([MATCHED])).passed


# -- the candidate shortlist (issue #8) -------------------------------------------------

RESPONSE_B = (
    "Honestly the localized boards in APAC are a different story. We do have coverage "
    "there, but it is nothing like the global footprint people tend to assume."
)
CALL_B = "20230711_lyft_joveo_quarterly_business_review_9f2a1c33.txt"
MATCHED_B = {"response_text": RESPONSE_B, "call_filename": CALL_B}
QUOTE_B = "We do have coverage there"


def test_the_gate_resolves_the_candidate_the_answer_actually_rests_on():
    """With a shortlist in the prompt, "cited the call it was given" no longer identifies
    WHICH exchange the answer rests on -- several were given. The citation a CSM reads has
    to name that exchange, not whichever one retrieval ranked first, or every top-K
    citation is quietly wrong while the gate still reports pass."""
    result = grounding.check(_model(quote=QUOTE_B, cited_call=CALL_B),
                             grounding.from_pairs([MATCHED, MATCHED_B]))
    assert result.passed
    assert result.source.payload["call_filename"] == CALL_B


def test_quoting_one_candidate_while_citing_another_cites_the_one_quoted():
    """The shortlist's characteristic slip: both texts are in front of the model, so a quote
    lifted from candidate B lands under candidate A's citation. Until 2026-11-07 this was
    refused; now the citation is CORRECTED to B, so the CSM is still never pointed at a
    call the words are not in -- the reason the old refusal existed."""
    quote = "We do have coverage there, but it is nothing like the global footprint"
    result = grounding.check(_model(quote=quote, cited_call=CALL),
                             grounding.from_pairs([MATCHED, MATCHED_B]))
    assert result.passed and result.corrected
    assert result.source.payload["call_filename"] == CALL_B


def test_a_short_quote_is_never_moved_to_another_call():
    """A short phrase ("We do have coverage there") can sit in many calls by coincidence, so
    finding it in a call the model did NOT name says nothing about where the answer came
    from. Only a quote of `MIN_CORRECTED_QUOTE_WORDS` or more is re-cited."""
    assert len(QUOTE_B.split()) < grounding.MIN_CORRECTED_QUOTE_WORDS
    result = grounding.check(_model(quote=QUOTE_B, cited_call=CALL),
                             grounding.from_pairs([MATCHED, MATCHED_B]))
    assert not result.passed and result.reason == "quote_not_verbatim"


def test_a_short_quote_in_the_call_it_names_still_passes():
    result = grounding.check(_model(quote=QUOTE_B, cited_call=CALL_B),
                             grounding.from_pairs([MATCHED, MATCHED_B]))
    assert result.passed and not result.corrected


def test_a_quote_in_both_the_named_call_and_another_cites_the_named_one():
    shared = "pull the last 90 days of spend"
    also_has_it = {"response_text": "First we pull the last 90 days of spend.",
                   "call_filename": CALL_B}
    result = grounding.check(_model(quote=shared, cited_call=CALL),
                             grounding.from_pairs([also_has_it, MATCHED]))
    assert result.passed and not result.corrected
    assert result.source.identifier == CALL


def test_a_quote_in_none_of_the_candidates_is_refused_whatever_it_cites():
    for cited in (CALL, "never_retrieved.txt"):
        result = grounding.check(_model(quote="we guarantee a 40% lift by Friday",
                                        cited_call=cited),
                                 grounding.from_pairs([MATCHED, MATCHED_B]))
        assert not result.passed
    assert result.reason == "wrong_call_cited"


def test_two_candidates_from_the_same_call_are_separated_by_the_quote_not_by_rank():
    """Dedup is keyed on content, so one call can contribute two exchanges to a shortlist
    and cited_call cannot tell them apart. Resolving by rank would cite the nearer exchange
    for a quote that came from the further one."""
    other_exchange_same_call = {
        "response_text": "That renewal date is locked, I checked it with finance on Monday.",
        "call_filename": CALL}
    result = grounding.check(
        _model(quote="I checked it with finance on Monday", cited_call=CALL),
        grounding.from_pairs([MATCHED, other_exchange_same_call]))
    assert result.passed
    assert result.source.payload["response_text"].startswith("That renewal date")


# -- a variable grounding source (issue #17) -----------------------------------------------
#
# ONE GATE, A DIFFERENT SOURCE. A Layer C answer rests on a playbook's evidence quotes rather
# than on a retrieved exchange, and it is held to exactly the same bar by exactly the same
# function -- which is the point of `GroundingSource`. What follows is the Layer B block
# above, re-run against playbook evidence.

MOVE_QUOTE = (
    "if there are certain jobs that have a much higher cost per hire goal than what you "
    "have, we will turn those off. Our system will automatically turn those off."
)
MOVE_CALL = "20250313_lululemon_joveo_global_strategy_727bb086"
EVIDENCE = [{"quote": MOVE_QUOTE, "call": MOVE_CALL, "account": "lululemon.com"}]


def test_a_playbook_answer_quoting_its_evidence_verbatim_passes():
    result = grounding.check(
        _model(answer="Tell them the guardrails turn those jobs off automatically.",
               quote="our system will automatically turn those off",
               cited_call=MOVE_CALL),
        grounding.from_playbook_evidence(EVIDENCE))
    assert result.passed
    assert result.source.payload["account"] == "lululemon.com"


def test_a_playbook_answer_quoting_a_plausible_near_miss_fails():
    """The failure a Layer C answer is MOST likely to produce: the playbook's criterion is
    written in the model's own words, sitting in the prompt right beside the evidence, and
    quoting the criterion instead of the evidence reads as grounded and is not."""
    result = grounding.check(
        _model(answer="Tell them the system turns those off.",
               quote="the system automatically disables jobs that exceed the target",
               cited_call=MOVE_CALL),
        grounding.from_playbook_evidence(EVIDENCE))
    assert not result.passed
    assert result.reason == "quote_not_verbatim"


def test_a_playbook_quote_cited_with_txt_added_cites_the_evidence_call():
    """Exchanges carry `call_filename` WITH `.txt`, evidence records `call` WITHOUT it, and
    the writer -- shown both -- adds it to evidence calls (3 of 18 tries, 2026-11-06)."""
    result = grounding.check(
        _model(quote="our system will automatically turn those off",
               cited_call=MOVE_CALL + ".txt"),
        grounding.from_playbook_evidence(EVIDENCE))
    assert result.passed and result.source.identifier == MOVE_CALL
    assert not result.corrected          # the right call, named with `.txt`: not a slip


def test_a_playbook_answer_citing_a_call_it_was_not_shown_with_an_invented_quote_fails():
    result = grounding.check(
        _model(quote="the system automatically disables jobs that exceed the target",
               cited_call="20240101_someone_else_joveo_call_abc123"),
        grounding.from_playbook_evidence(EVIDENCE))
    assert not result.passed
    assert result.reason == "wrong_call_cited"


def test_one_call_supplying_evidence_for_two_moves_is_separated_by_the_quote():
    """Routine on the Layer C path in a way it is only occasional on Layer B: one call
    frequently supplies evidence for several moves, so the citation alone cannot say which
    quote an answer rests on."""
    second = {"quote": "we flag them rather than auto rejecting them on that time frame",
              "call": MOVE_CALL, "account": "lululemon.com"}
    result = grounding.check(
        _model(quote="we flag them rather than auto rejecting them", cited_call=MOVE_CALL),
        grounding.from_playbook_evidence(EVIDENCE + [second]))
    assert result.passed
    assert result.source.payload["quote"].startswith("we flag them")


def test_an_evidence_entry_with_no_quote_is_not_a_source():
    """A playbook move can carry an empty evidence slot. An empty source would make the
    gate's containment check trivially true for any quote."""
    assert grounding.from_playbook_evidence([{"quote": "  ", "call": MOVE_CALL}]) == []


def test_an_evidence_entry_with_no_call_is_not_a_source():
    """These come from a model-authored jsonb document, so a missing key is a real shape.
    Without a `call` there is no identifier for the model to cite, so the source could never
    be selected -- and reading it defensively into a broken source would turn a malformed
    playbook into a 500 instead of a decline."""
    assert grounding.from_playbook_evidence([{"quote": MOVE_QUOTE}]) == []
    assert grounding.from_playbook_evidence([{"quote": MOVE_QUOTE, "call": "  "}]) == []
