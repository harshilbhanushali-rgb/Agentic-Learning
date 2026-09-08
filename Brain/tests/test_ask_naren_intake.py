"""ask_naren/intake.py -- what happens to a message BEFORE anything is retrieved.

Every generation here comes from a stubbed gateway: no API calls, no live embeddings. What
is tested is the EXTERNAL contract -- what a caller receives for a given model reply -- plus
the validation that stands between an untrusted model reply and the rest of the request path
(ADR 0007).

The intake PROMPT's wording is deliberately not asserted. It is not frozen the way the
answering prompts are (ADR 0001), and pinning wording in a test would make every prompt
improvement look like a regression. What routing accuracy actually is gets measured by
`ask-naren/audit/measure_intake_accuracy.py` against labelled messages, not here.
"""
import pytest

from ask_naren import intake, threads


class StubGateway:
    """Returns queued payloads in order, and records what it was asked for."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    def chat_json(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if not self.payloads:
            raise AssertionError("intake asked for more generations than the contract allows")
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload, {"served_model": kwargs.get("model")}


def _reply(intent="reply_to_client", retrieval_query="our cost per hire is way too high",
           question=""):
    return {"intent": intent, "retrieval_query": retrieval_query, "question": question}


SITUATION = "client said our cost per hire is way too high"


# -- the decision itself ----------------------------------------------------------------

def test_a_relayed_client_turn_routes_to_the_answering_path():
    decision, _ = intake.classify(SITUATION, StubGateway(_reply()))
    assert decision.intent == "reply_to_client"
    assert decision.retrieval_query == "our cost per hire is way too high"


def test_the_retrieval_query_is_what_reaches_retrieval_not_the_whole_message():
    """The framing measurement is the whole reason intake exists: a request frame wrapped
    around the client's words changes which exchange retrieval reaches for 81% of
    situations. Intake's job is to hand retrieval the CLIENT'S WORDS."""
    framed = "A client said this, can you help with how Naren would reply? " + SITUATION
    decision, _ = intake.classify(framed, StubGateway(_reply()))
    assert decision.retrieval_query == "our cost per hire is way too high"
    assert "can you help" not in decision.retrieval_query


def test_a_message_with_no_client_words_asks_for_them():
    decision, _ = intake.classify(
        "client is unhappy about pricing",
        StubGateway(_reply(intent="clarify", retrieval_query="",
                           question="What did the client actually say?")))
    assert decision.intent == "clarify"
    assert decision.question == "What did the client actually say?"


def test_an_out_of_scope_question_is_not_a_clarify():
    """Asking a CSM to reword something Ask Naren fundamentally cannot answer helps nobody.
    Naren's calls are not a product document, so a pricing fact is a decline."""
    decision, _ = intake.classify(
        "what is our actual list price for a 12 month contract",
        StubGateway(_reply(intent="out_of_scope", retrieval_query="", question="")))
    assert decision.intent == "out_of_scope"


# -- the thread (issues #15, #16) --------------------------------------------------------

def _turn(message="client says our cpa is 3x", reply="Reframe on their own baseline.",
          outcome="answered", pair_id=11):
    return threads.ThreadTurn(message=message, reply=reply, outcome=outcome,
                              pair_id=pair_id, call_filename="a_call.txt",
                              scenario_key="performance_pushback")


def test_a_first_message_is_not_offered_an_intent_it_cannot_have():
    """MEASURED, not assumed. The first version of this prompt listed `follow_up` always and
    said it only applied when there was a conversation -- and on the thread-shaped set, "and
    what if they push back on price?" with no conversation was routed `follow_up` anyway.
    Not offering the option is the fix; a rule saying an option does not apply is weaker
    than its absence.

    It also keeps a FIRST message classified by the intent list #14's routing accuracy was
    measured on."""
    assert "follow_up" not in intake.build_prompt(SITUATION)
    assert "follow_up" in intake.build_prompt(SITUATION, (_turn(),))


def test_the_conversation_reaches_the_model_when_there_is_one():
    gw = StubGateway(_reply())
    intake.classify("and what if they push back on price?", gw, thread=(_turn(),))
    prompt = gw.calls[0]["prompt"]
    assert "client says our cpa is 3x" in prompt
    assert "Reframe on their own baseline." in prompt


def test_a_follow_up_is_an_intent_the_model_may_return():
    decision, _ = intake.classify(
        "and what if they push back on price?",
        StubGateway(_reply(intent="follow_up", retrieval_query="")), thread=(_turn(),))
    assert decision.intent == "follow_up"


def test_a_follow_up_carries_no_retrieval_query_even_if_the_model_writes_one():
    """The follow-up path embeds nothing. Every response echoes `retrieval_query` so a bad
    extraction is visible in production; a query echoed here would report a search that
    never happened."""
    decision = intake.IntakeDecision(intent="follow_up",
                                     retrieval_query="pushing back on price")
    assert decision.retrieval_query == ""


# -- validation of an untrusted reply ---------------------------------------------------

def test_an_unusable_reply_is_retried_once_and_the_retry_can_succeed():
    gw = StubGateway(_reply(intent="clarify", question=""), _reply())
    decision, _ = intake.classify(SITUATION, gw)
    assert decision.intent == "reply_to_client"
    assert len(gw.calls) == 2


def test_two_unusable_replies_fall_through_to_the_answering_path():
    """Falling through to reply_to_client rather than raising: intake is an OPTIMISATION on
    a path that already works. If it cannot decide, the CSM gets the answer they would have
    got before intake existed, which is a working tool rather than an error."""
    gw = StubGateway(_reply(intent="nonsense"), _reply(intent="nonsense"))
    decision, _ = intake.classify(SITUATION, gw)
    assert decision.intent == "reply_to_client"
    assert decision.retrieval_query == SITUATION
    assert len(gw.calls) == 2


def test_a_gateway_failure_falls_through_rather_than_breaking_the_request():
    gw = StubGateway(RuntimeError("gateway down"), RuntimeError("gateway down"))
    decision, _ = intake.classify(SITUATION, gw)
    assert decision.intent == "reply_to_client"
    assert decision.retrieval_query == SITUATION


def test_a_clarify_without_a_question_is_not_a_usable_decision():
    """A clarify whose question is empty is a dead end -- the CSM is shown nothing to answer.
    Rejected at the model boundary rather than rendered."""
    with pytest.raises(ValueError):
        intake.IntakeDecision(intent="clarify", retrieval_query="", question="")


def test_an_answering_decision_without_a_retrieval_query_is_not_usable():
    with pytest.raises(ValueError):
        intake.IntakeDecision(intent="reply_to_client", retrieval_query="   ", question="")


def test_an_unknown_intent_is_refused_at_the_boundary():
    with pytest.raises(ValueError):
        intake.IntakeDecision(intent="do_my_taxes", retrieval_query="x", question="")


def test_extra_keys_from_the_model_are_refused():
    """The schema forbids them at the gateway (ADR 0007), but enforcement is a property of a
    deployment that can change. Validating here too means a silent regression surfaces as an
    error rather than as a field nobody checked."""
    with pytest.raises(ValueError):
        intake.IntakeDecision(intent="reply_to_client", retrieval_query="x",
                              question="", confidence=0.9)


# -- what is asked of the gateway -------------------------------------------------------

def test_intake_sends_a_schema_so_the_shape_is_constrained_at_the_gateway():
    gw = StubGateway(_reply())
    intake.classify(SITUATION, gw)
    schema = gw.calls[0]["schema"]
    assert schema["schema"]["additionalProperties"] is False
    assert set(schema["schema"]["properties"]["intent"]["enum"]) == set(intake.INTENTS)


def test_intake_never_serves_one_csm_another_csms_cached_decision():
    gw = StubGateway(_reply())
    intake.classify(SITUATION, gw)
    assert gw.calls[0]["no_cache"] is True
