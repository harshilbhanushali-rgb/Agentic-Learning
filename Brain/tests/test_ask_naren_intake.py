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
import asyncio
import pytest

from ask_naren import intake, threads


class StubGateway:
    """Returns queued payloads in order, and records what it was asked for."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    async def chat_json(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if not self.payloads:
            raise AssertionError("intake asked for more generations than the contract allows")
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload, {"served_model": kwargs.get("model")}


def _reply(intent="reply_to_client", retrieval_query="our cost per hire is way too high",
           question="", my_reply=""):
    return {"intent": intent, "retrieval_query": retrieval_query, "question": question,
            "my_reply": my_reply}


SITUATION = "client said our cost per hire is way too high"


# -- the decision itself ----------------------------------------------------------------

def test_a_relayed_client_turn_routes_to_the_answering_path():
    decision, _ = asyncio.run(intake.classify(SITUATION, StubGateway(_reply())))
    assert decision.intent == "reply_to_client"
    assert decision.retrieval_query == "our cost per hire is way too high"


def test_the_retrieval_query_is_what_reaches_retrieval_not_the_whole_message():
    """The framing measurement is the whole reason intake exists: a request frame wrapped
    around the client's words changes which exchange retrieval reaches for 81% of
    situations. Intake's job is to hand retrieval the CLIENT'S WORDS."""
    framed = "A client said this, can you help with how Naren would reply? " + SITUATION
    decision, _ = asyncio.run(intake.classify(framed, StubGateway(_reply())))
    assert decision.retrieval_query == "our cost per hire is way too high"
    assert "can you help" not in decision.retrieval_query


def test_a_message_with_no_client_words_asks_for_them():
    decision, _ = asyncio.run(intake.classify(
        "client is unhappy about pricing",
        StubGateway(_reply(intent="clarify", retrieval_query="",
                           question="What did the client actually say?"))))
    assert decision.intent == "clarify"
    assert decision.question == "What did the client actually say?"


def test_an_out_of_scope_question_is_not_a_clarify():
    """Asking a CSM to reword something Ask Naren fundamentally cannot answer helps nobody.
    Naren's calls are not a product document, so a pricing fact is a decline."""
    decision, _ = asyncio.run(intake.classify(
        "what is our actual list price for a 12 month contract",
        StubGateway(_reply(intent="out_of_scope", retrieval_query="", question=""))))
    assert decision.intent == "out_of_scope"


# -- the CSM's own reply (issue #21) -----------------------------------------------------

CONTRAST = ('client said "your cost per hire is way off what you pitched" and i replied '
            "that we would review the campaign settings this week -- is that how naren "
            "would have handled it")


def test_a_message_carrying_the_csms_own_reply_extracts_both_halves():
    """Two spans, not one. The CLIENT's words are what gets embedded, exactly as on every
    retrieving path; the CSM's own reply is what the answer contrasts against and is never
    embedded -- adding it to the query would be the boilerplate dilution intake exists to
    strip, with the CSM's own wording as the boilerplate."""
    decision, _ = asyncio.run(intake.classify(CONTRAST, StubGateway(_reply(
        intent="contrast_my_reply",
        retrieval_query="your cost per hire is way off what you pitched",
        my_reply="we would review the campaign settings this week"))))
    assert decision.intent == "contrast_my_reply"
    assert decision.retrieval_query == "your cost per hire is way off what you pitched"
    assert decision.my_reply == "we would review the campaign settings this week"


def test_a_contrast_with_no_reply_to_contrast_is_rejected():
    """Shape-valid and useless: the whole answer is the comparison, so without the CSM's
    reply there is nothing to compare Naren against. Rejecting sends it to the retry and
    then to the fallback, which answers the situation as written -- still useful."""
    with pytest.raises(ValueError):
        intake.IntakeDecision(intent="contrast_my_reply",
                              retrieval_query="your cost per hire is way off", my_reply="")


def test_only_a_contrast_may_carry_a_reply_even_if_the_model_writes_one():
    """Cleared rather than rejected, the same treatment `retrieval_query` gets on a
    follow-up: a model that helpfully fills the field is being misleading, not unusable, and
    a `my_reply` on a path that never shows one would report a comparison that never ran."""
    decision = intake.IntakeDecision(intent="reply_to_client",
                                     retrieval_query="our cost per hire is way too high",
                                     my_reply="i told them we would look into it")
    assert decision.my_reply == ""


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


def test_every_intent_that_needs_a_query_is_told_to_produce_one():
    """The validator REJECTS a retrieving intent with an empty `retrieval_query`, so an
    intent the prompt never gives a rule for is a rejected decision, one retry, and then the
    fallback -- a full Layer B generation on the raw framed message, which is exactly the
    boilerplate dilution intake exists to strip.

    Derived from RETRIEVING_INTENTS rather than a hand-written list, so the module's own
    stated invariant -- 'a change to the schema AND to the prompt's discriminators, never
    one alone' -- is checked instead of restated. #17 and #18 each added intents to the
    schema; #18's five never reached the rules block."""
    rules = intake.build_prompt(SITUATION).split("Rules:", 1)[1]
    for intent in intake.RETRIEVING_INTENTS:
        assert intent in rules, intent


def test_the_intents_that_search_for_nothing_are_told_to_leave_it_empty():
    """The other half of the same invariant: an intent that retrieves nothing must not be
    asked for a query, or the response echoes a search that never happened."""
    rules = intake.build_prompt(SITUATION).split("Rules:", 1)[1]
    for intent in intake.CORPUS_INTENTS:
        assert intent in rules, intent
    assert not set(intake.CORPUS_INTENTS) & set(intake.RETRIEVING_INTENTS)


def test_the_conversation_reaches_the_model_when_there_is_one():
    gw = StubGateway(_reply())
    asyncio.run(intake.classify("and what if they push back on price?", gw, thread=(_turn(),)))
    prompt = gw.calls[0]["prompt"]
    assert "client says our cpa is 3x" in prompt
    assert "Reframe on their own baseline." in prompt


def test_a_follow_up_is_an_intent_the_model_may_return():
    decision, _ = asyncio.run(intake.classify(
        "and what if they push back on price?",
        StubGateway(_reply(intent="follow_up", retrieval_query="")), thread=(_turn(),)))
    assert decision.intent == "follow_up"


def test_a_follow_up_carries_no_retrieval_query_even_if_the_model_writes_one():
    """The follow-up path embeds nothing. Every response echoes `retrieval_query` so a bad
    extraction is visible in production; a query echoed here would report a search that
    never happened."""
    decision = intake.IntakeDecision(intent="follow_up",
                                     retrieval_query="pushing back on price")
    assert decision.retrieval_query == ""


# -- the anchor each intent's path consumes (issue #51, ADR 0013) ------------------------

def test_every_intent_declares_the_anchor_its_path_consumes():
    """THE STRUCTURAL GUARANTEE FOR INTENTS THAT DO NOT EXIST YET. Carrying a situation is
    resolved from this table, so an intent missing from it would get no carried-situation
    behaviour at all -- silently, with every other test green. One session added nine
    intents; this is what stops the tenth being forgotten."""
    assert set(intake.ANCHORS) == set(intake.INTENTS)
    assert len(intake.ANCHORS) == len(intake.INTENTS)


def test_the_anchor_table_is_the_one_the_spec_decided():
    """Spelled out from #50's table rather than derived from the code, so a wrong
    declaration cannot pass by agreeing with itself."""
    expected = {
        "sequence": ("scenario", False), "phrasing": ("scenario", False),
        "pitfalls": ("scenario", False), "scenario_check": ("scenario", False),
        "play_confidence": ("scenario", False), "improve_at_move": ("scenario", False),
        "procedure": ("scenario", False),
        "show_exchange": ("exchange", False), "what_happened_next": ("exchange", False),
        "coverage_check": ("exchange", False),
        "where_else_seen": ("neighbourhood", False), "call_prep": ("neighbourhood", False),
        "reply_to_client": ("exchange", True), "contrast_my_reply": ("exchange", True),
        "discovery": ("none", False), "frequency": ("none", False),
        "clarify": ("none", False), "out_of_scope": ("none", False),
        "follow_up": ("own_path", False),
    }
    assert {i: (a.kind, a.new_only) for i, a in intake.ANCHORS.items()} == expected


def test_only_scenario_and_exchange_anchors_may_be_carried():
    """New-only intents always carry new client words, and a neighbourhood cannot be carried
    until the vector store can be queried by id (ADR 0013 point 4)."""
    carriable = {i for i in intake.INTENTS if intake.may_carry(i)}
    assert carriable == {"sequence", "phrasing", "pitfalls", "scenario_check",
                         "play_confidence", "improve_at_move", "procedure",
                         "show_exchange", "what_happened_next", "coverage_check"}


# -- the situation field: on a carried situation, or opening one (issue #53, ADR 0013) ---

def test_a_carried_decision_searches_for_nothing_so_carries_no_query():
    """Cleared, the way a follow-up's is: the echo would otherwise report a search that
    never ran, on a message whose subject came from the thread."""
    decision = intake.IntakeDecision(intent="sequence", situation="carried",
                                     retrieval_query="the play here")
    assert decision.situation == "carried"
    assert decision.retrieval_query == ""


def test_a_follow_up_is_always_on_a_carried_situation():
    for said in ("opens", "carried"):
        decision = intake.IntakeDecision(intent="follow_up", situation=said)
        assert decision.situation == "carried", said
    assert intake.IntakeDecision(intent="follow_up").situation == "carried"


def test_a_new_only_or_neighbourhood_intent_never_carries_and_keeps_its_query():
    """These always search fresh (ADR 0013 point 4), so "carried" is read as opens -- and
    the query is kept, because it is what they search on."""
    for intent in ("reply_to_client", "where_else_seen", "call_prep"):
        decision = intake.IntakeDecision(intent=intent, situation="carried",
                                         retrieval_query="our cost per hire is way too high")
        assert decision.situation == "opens", intent
        assert decision.retrieval_query == "our cost per hire is way too high", intent


def test_an_opening_decision_on_a_retrieving_intent_still_needs_a_query():
    with pytest.raises(ValueError):
        intake.IntakeDecision(intent="sequence", situation="opens", retrieval_query="")


def test_an_unknown_situation_is_refused_at_the_boundary():
    with pytest.raises(ValueError):
        intake.IntakeDecision(intent="sequence", situation="maybe",
                              retrieval_query="cost per hire")


def test_the_gateway_schema_requires_the_situation():
    schema = intake.response_schema()["schema"]
    assert "situation" in schema["required"]
    assert set(schema["properties"]["situation"]["enum"]) == {"carried", "opens"}


def test_with_no_thread_a_carried_reply_is_read_as_opening_and_keeps_its_query():
    """A first message has nothing to carry. Forced in code BEFORE validation, so the copied
    query the model also wrote survives and the message is searched as it always was."""
    gw = StubGateway({**_reply(intent="sequence", retrieval_query="cost per hire"),
                      "situation": "carried"})
    decision, _ = asyncio.run(intake.classify("what's the play for cost per hire", gw))
    assert decision.situation == "opens"
    assert decision.retrieval_query == "cost per hire"


def test_in_a_thread_the_model_may_say_carried():
    gw = StubGateway({**_reply(intent="sequence", retrieval_query=""), "situation": "carried"})
    decision, _ = asyncio.run(intake.classify("what's the play here", gw, thread=(_turn(),)))
    assert decision.situation == "carried"
    assert decision.intent == "sequence"


def test_the_situation_rule_is_shown_only_when_there_is_a_conversation():
    """ADR 0013 point 5: block placement in this prompt has been measured moving other
    intents' routing, so a first message sees no new prompt text at all."""
    assert '"carried"' not in intake.build_prompt(SITUATION)
    assert '"carried"' in intake.build_prompt(SITUATION, (_turn(),))


# -- validation of an untrusted reply ---------------------------------------------------

def test_an_unusable_reply_is_retried_once_and_the_retry_can_succeed():
    gw = StubGateway(_reply(intent="clarify", question=""), _reply())
    decision, _ = asyncio.run(intake.classify(SITUATION, gw))
    assert decision.intent == "reply_to_client"
    assert len(gw.calls) == 2


def test_two_unusable_replies_fall_through_to_the_answering_path():
    """Falling through to reply_to_client rather than raising: intake is an OPTIMISATION on
    a path that already works. If it cannot decide, the CSM gets the answer they would have
    got before intake existed, which is a working tool rather than an error."""
    gw = StubGateway(_reply(intent="nonsense"), _reply(intent="nonsense"))
    decision, _ = asyncio.run(intake.classify(SITUATION, gw))
    assert decision.intent == "reply_to_client"
    assert decision.retrieval_query == SITUATION
    assert len(gw.calls) == 2


def test_a_gateway_failure_falls_through_rather_than_breaking_the_request():
    gw = StubGateway(RuntimeError("gateway down"), RuntimeError("gateway down"))
    decision, _ = asyncio.run(intake.classify(SITUATION, gw))
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
    asyncio.run(intake.classify(SITUATION, gw))
    schema = gw.calls[0]["schema"]
    assert schema["schema"]["additionalProperties"] is False
    assert set(schema["schema"]["properties"]["intent"]["enum"]) == set(intake.INTENTS)


def test_intake_never_serves_one_csm_another_csms_cached_decision():
    gw = StubGateway(_reply())
    asyncio.run(intake.classify(SITUATION, gw))
    assert gw.calls[0]["no_cache"] is True
