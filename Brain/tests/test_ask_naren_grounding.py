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
    assert grounding.check(_model(), MATCHED).passed


def test_case_and_punctuation_differences_do_not_fail_a_real_quote():
    """A model re-capitalising or dropping a comma has not fabricated anything. Uses
    layer_d.verify_quotes, whose normalization Brain already settled for exactly this."""
    quote = "Show them Cost Per Hire against their own baseline!"
    assert grounding.check(_model(quote=quote), MATCHED).passed


def test_a_fabricated_quote_is_refused():
    result = grounding.check(_model(quote="we guarantee a 40% lift by Friday"), MATCHED)
    assert not result.passed
    assert result.reason == "quote_not_verbatim"


def test_a_paraphrase_of_the_response_is_not_a_verbatim_quote():
    """The gate is verbatim containment, not similarity -- a close paraphrase is exactly
    the failure mode that reads as grounded and is not."""
    quote = "showed them their cost-per-hire versus their own historical baseline numbers"
    assert not grounding.check(_model(quote=quote), MATCHED).passed


def test_an_empty_quote_never_passes():
    result = grounding.check(_model(quote="   "), MATCHED)
    assert not result.passed
    assert result.reason == "quote_not_verbatim"


def test_citing_a_call_that_was_not_retrieved_is_refused():
    """Only one exchange is ever put in the prompt, so a different citation means the model
    named a source it was not shown -- the citation would point a CSM at the wrong call."""
    result = grounding.check(_model(cited_call="some_other_call.txt"), MATCHED)
    assert not result.passed
    assert result.reason == "wrong_call_cited"


def test_a_citation_differing_only_in_case_or_spacing_still_passes():
    assert grounding.check(_model(cited_call=f"  {CALL.upper()} "), MATCHED).passed


def test_an_empty_answer_is_refused_even_when_the_quote_verifies():
    """A verified quote with nothing built on it is not an answer; forwarding it would show
    a CSM a citation and no guidance."""
    result = grounding.check(_model(answer="  "), MATCHED)
    assert not result.passed
    assert result.reason == "empty_answer"


def test_a_missing_key_is_refused_rather_than_treated_as_absent_evidence():
    """A malformed payload must fail closed. `.get` returning None on `quote` is the one
    shape that could otherwise slip through a truthiness check as 'nothing to verify'."""
    assert not grounding.check({"declined": False, "answer": "x"}, MATCHED).passed
