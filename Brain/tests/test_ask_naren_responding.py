"""ask_naren/responding.py -- the one call the HTTP layer makes, and where an intake
decision becomes a response.

`classify` is INJECTED in every test here, the same way `embed_query` and `label_for` are
elsewhere. Two reasons, both deliberate: a dispatch test must not pay for a generation, and
routing accuracy is a separate question measured against labelled messages
(`ask-naren/audit/measure_intake_accuracy.py`) rather than smuggled into behaviour tests.
"""
import json

import numpy as np
import pytest

from ask_naren import intake, responding, retrieval, threads

RESPONSE = ("Yeah, so what I usually do there is pull the last 90 days of spend and show "
            "them cost per hire against their own baseline, not against our benchmark.")
CALL = "20230503_uber_joveo_weekly_performance_review_d18cc178.txt"
GOOD_QUOTE = "show them cost per hire against their own baseline"

FRAMED = ("A client said this, can you help with how Naren would reply? "
          "our cost per hire is way too high")
CLIENT_WORDS = "our cost per hire is way too high"


def _pool():
    pairs = [
        {"pair_id": 11, "trigger_text": "our cost per hire looks terrible this quarter",
         "response_text": RESPONSE, "call_filename": CALL,
         "scenario_key": "performance_pushback"},
        {"pair_id": 22, "trigger_text": "when does the integration go live",
         "response_text": "Let me check with the team and come back to you today.",
         "call_filename": "other_call.txt", "scenario_key": "timeline_question"},
    ]
    return retrieval.RetrievalPool(pairs, np.array([[1.0, 0.0], [0.0, 1.0]]))


class RecordingEmbedder:
    """Records what was actually embedded -- which is the whole point of intake."""

    def __init__(self):
        self.seen = []

    def __call__(self, texts):
        self.seen.extend(texts)
        return np.array([[1.0, 0.05]] * len(texts))


class StubGateway:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    def chat_json(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if not self.payloads:
            raise AssertionError("more generations than the contract allows")
        return self.payloads.pop(0), {"served_model": kwargs.get("model")}


def _answer_payload():
    return {"declined": False, "answer": "Reframe on their own baseline.",
            "quote": GOOD_QUOTE, "cited_call": CALL}


def _decides(intent, retrieval_query="", question="", seen_threads=None):
    """A stand-in intake that returns a fixed decision without calling a gateway.

    `seen_threads` records what thread intake was handed, which is the only externally
    observable part of "history reaches intake" (issue #15).
    """
    def _classify(message, gateway, *, thread=()):
        if seen_threads is not None:
            seen_threads.append(thread)
        return intake.IntakeDecision(intent=intent, retrieval_query=retrieval_query,
                                     question=question), {}
    return _classify


def _respond(classify, *payloads, message=FRAMED, embedder=None, thread=()):
    gw = StubGateway(*payloads)
    embed = embedder or RecordingEmbedder()
    result = responding.respond(message, _pool(), gw, embed_query=embed, thread=thread,
                                classify=classify)
    return result, gw, embed


# -- reply_to_client: the shipped answering path, reached through intake ----------------

def test_an_answerable_message_is_answered_as_before():
    result, _, _ = _respond(_decides("reply_to_client", CLIENT_WORDS), _answer_payload())
    assert result["outcome"] == "answered"
    assert result["citation"]["call_filename"] == CALL


def test_retrieval_embeds_the_clients_words_not_the_csms_framing():
    """The reason intake exists. A request frame is boilerplate shared by every question and
    it moves which exchange retrieval reaches for 81% of situations, so the framing must not
    reach the embedder."""
    _, _, embed = _respond(_decides("reply_to_client", CLIENT_WORDS), _answer_payload())
    assert embed.seen == [CLIENT_WORDS]
    assert not any("can you help" in t for t in embed.seen)


# -- clarify: decided before retrieval --------------------------------------------------

def test_a_clarify_returns_the_question_and_never_retrieves():
    result, gw, embed = _respond(
        _decides("clarify", question="What did the client actually say?"),
        message="client is unhappy about pricing")
    assert result["outcome"] == "clarify"
    assert result["question"] == "What did the client actually say?"
    assert embed.seen == []      # nothing was embedded
    assert gw.calls == []        # nothing was generated


def test_a_clarify_carries_no_field_an_ungrounded_answer_could_ride_in():
    result, _, _ = _respond(_decides("clarify", question="What did they say?"),
                            message="client is unhappy")
    assert "answer" not in result and "quote" not in result and "citation" not in result


# -- out of scope: a decline, not a question back ---------------------------------------

def test_an_out_of_scope_question_declines_without_retrieving():
    result, gw, embed = _respond(_decides("out_of_scope"),
                                 message="what is our list price for 12 months")
    assert result["outcome"] == "declined"
    assert result["reason"] == "out_of_scope"
    assert result["message"]
    assert embed.seen == [] and gw.calls == []


def test_an_out_of_scope_decline_reports_no_match_because_nothing_was_searched():
    """Every other decline records how close the match it turned down was, for decline-rate
    calibration. This one has no match to report and must not invent one."""
    result, _, _ = _respond(_decides("out_of_scope"), message="what is our list price")
    assert "match" not in result


# -- the thread (issue #15) ---------------------------------------------------------------

def _prior(message="client says our cpa is 3x", reply="reframe on their own baseline",
           outcome="answered", pair_id=11, scenario_key="performance_pushback"):
    return threads.ThreadTurn(message=message, reply=reply, outcome=outcome,
                              pair_id=pair_id, scenario_key=scenario_key)


def test_history_reaches_intake():
    """Intake cannot detect a follow-up, resolve its own clarify or avoid re-asking one
    without the thread. This is the plumbing that makes issue #16 possible."""
    seen = []
    _respond(_decides("reply_to_client", CLIENT_WORDS, seen_threads=seen),
             _answer_payload(), thread=(_prior(),))
    assert len(seen) == 1
    assert seen[0][0].pair_id == 11


def test_history_never_reaches_the_embedded_query():
    """ADR 0006, and the single most important property of a thread here. Retrieval embeds
    the CURRENT message alone: previous turns are text shared by every later query in the
    thread, and shared text pulls all queries toward each other -- measured at 81% of
    situations reaching a different exchange, with the cosine range collapsing from 0.124 to
    0.076 wide."""
    prior = _prior(message="client says our cpa is 3x",
                   reply="pull the last 90 days of spend and show cost per hire")
    _, _, embed = _respond(_decides("reply_to_client", CLIENT_WORDS), _answer_payload(),
                           thread=(prior,))
    assert embed.seen == [CLIENT_WORDS]
    assert not any("90 days" in t for t in embed.seen)
    assert not any("3x" in t for t in embed.seen)


def test_a_long_thread_is_trimmed_before_intake_sees_it():
    """A conversation that has run all afternoon must not quietly turn one question into a
    60KB generation."""
    seen = []
    long_thread = tuple(_prior(message="m" * 4_000, reply="r" * 4_000, pair_id=n)
                        for n in range(1, 12))
    _respond(_decides("reply_to_client", CLIENT_WORDS, seen_threads=seen),
             _answer_payload(), thread=long_thread)
    total = sum(len(t.message) + len(t.reply) for t in seen[0])
    assert total <= threads.MAX_THREAD_CHARS


def test_trimming_a_thread_does_not_lose_a_carried_identifier():
    """The rule ADR 0006 makes load-bearing: the first message usually established the
    scenario, and every later turn inherits its identifier. Whatever a trim drops, it is
    never that."""
    seen = []
    long_thread = tuple(_prior(message="m" * 4_000, reply="r" * 4_000, pair_id=n,
                               scenario_key=f"scenario_{n}") for n in range(1, 12))
    _respond(_decides("reply_to_client", CLIENT_WORDS, seen_threads=seen),
             _answer_payload(), thread=long_thread)
    assert [t.pair_id for t in seen[0]] == list(range(1, 12))
    assert [t.scenario_key for t in seen[0]] == [f"scenario_{n}" for n in range(1, 12)]


def test_no_thread_behaves_exactly_as_before_threads_existed():
    seen = []
    result, _, embed = _respond(_decides("reply_to_client", CLIENT_WORDS, seen_threads=seen),
                                _answer_payload())
    assert seen == [()]
    assert result["outcome"] == "answered"
    assert embed.seen == [CLIENT_WORDS]


# -- follow-ups: answered from the thread, with no new search (issue #16) ------------------

FOLLOW_UP = "and what if they push back on price?"
OTHER_RESPONSE = "Let me check with the team and come back to you today."


def _answered_turn(pair_id=11, call=CALL, scenario="performance_pushback"):
    return threads.ThreadTurn(message="client says our cpa is 3x",
                              reply="Reframe on their own baseline.", outcome="answered",
                              pair_id=pair_id, call_filename=call, scenario_key=scenario)


def test_a_follow_up_is_answered_without_searching_for_anything():
    """ADR 0006's answer to "and if they push back on price?": there is no new search to
    dilute, because there is no new search."""
    result, gw, embed = _respond(_decides("follow_up"), _answer_payload(),
                                 message=FOLLOW_UP, thread=(_answered_turn(),))
    assert result["outcome"] == "answered"
    assert embed.seen == []                 # nothing was embedded
    assert len(gw.calls) == 1               # one generation, no retrieval


def test_a_follow_up_grounds_in_the_source_the_thread_carried():
    result, _, _ = _respond(_decides("follow_up"), _answer_payload(),
                            message=FOLLOW_UP, thread=(_answered_turn(),))
    assert result["citation"]["pair_id"] == 11
    assert result["citation"]["call_filename"] == CALL


def test_a_follow_up_answer_reports_no_match_because_nothing_was_searched():
    """Same rule as an out-of-scope decline. A cosine here would be invented, and it would
    be invented into the record decline-rate calibration later reads."""
    result, _, _ = _respond(_decides("follow_up"), _answer_payload(),
                            message=FOLLOW_UP, thread=(_answered_turn(),))
    assert "match" not in result


def test_a_quote_from_an_earlier_turns_source_does_not_pass_as_grounding():
    """QUOTE BLEED, the hazard putting history in a prompt creates. An earlier turn cited a
    different call; a quote lifted from THAT call must not ground THIS answer, however
    verbatim it is of something Naren really said."""
    thread = (_answered_turn(pair_id=22, call="other_call.txt", scenario="timeline_question"),
              _answered_turn(pair_id=11, call=CALL))
    bleed = {"declined": False, "answer": "Tell them you will check.",
             "quote": "come back to you today",     # verbatim -- of the WRONG call
             "cited_call": "other_call.txt"}

    result, _, _ = _respond(_decides("follow_up"), bleed, bleed,
                            message=FOLLOW_UP, thread=thread)
    assert result["outcome"] == "declined"
    assert result["reason"] == "follow_up_ungrounded"
    assert "come back to you today" not in json.dumps(result)


def test_a_follow_up_the_carried_source_cannot_answer_declines():
    ungroundable = {"declined": False, "answer": "Offer a discount.",
                    "quote": "offer them fifteen percent off", "cited_call": CALL}
    result, _, _ = _respond(_decides("follow_up"), ungroundable, ungroundable,
                            message=FOLLOW_UP, thread=(_answered_turn(),))
    assert result["outcome"] == "declined"
    assert result["reason"] == "follow_up_ungrounded"
    assert "answer" not in result and "quote" not in result


def test_a_follow_up_with_nothing_to_follow_up_on_is_answered_as_a_new_question():
    """An all-clarify thread carries no grounding source. Declining would tell a CSM nothing
    was found when nothing was looked for; searching on their words is the honest fallback."""
    clarified = threads.ThreadTurn(message="client is unhappy", outcome="clarify",
                                   reply="What did they actually say?")
    result, _, embed = _respond(_decides("follow_up"), _answer_payload(),
                                message=FOLLOW_UP, thread=(clarified,))
    assert result["outcome"] == "answered"
    assert embed.seen == [FOLLOW_UP]        # it really did search, on the message as written


def test_a_follow_up_whose_carried_pair_left_the_pool_is_answered_as_a_new_question():
    """The pool is loaded once at startup. A pipeline re-run between restarts can retire a
    pair an open thread still points at."""
    stale = _answered_turn(pair_id=9999, call="retired_call.txt")
    result, _, embed = _respond(_decides("follow_up"), _answer_payload(),
                                message=FOLLOW_UP, thread=(stale,))
    assert result["outcome"] == "answered"
    assert embed.seen == [FOLLOW_UP]


def test_a_follow_up_echoes_no_retrieval_query_because_it_embedded_nothing():
    result, _, _ = _respond(_decides("follow_up", retrieval_query="pushing back on price"),
                            _answer_payload(), message=FOLLOW_UP, thread=(_answered_turn(),))
    assert result["intake"] == {"intent": "follow_up", "retrieval_query": ""}


# -- clarify: asked once, never twice (issue #16) ------------------------------------------

def test_the_same_clarify_is_not_asked_twice_in_a_row():
    """The CSM is answering the question right now. Asking again is the loop story 14
    forbids, so the path falls through to a best-effort answer instead."""
    asked = threads.ThreadTurn(message="client is unhappy about pricing", outcome="clarify",
                               reply="What did the client actually say?")
    result, _, embed = _respond(_decides("clarify", question="What did the client actually say?"),
                                _answer_payload(),
                                message="he said our rates are 30% above market",
                                thread=(asked,))
    assert result["outcome"] == "answered"
    assert embed.seen == ["he said our rates are 30% above market"]


def test_a_question_already_asked_earlier_in_the_thread_is_not_repeated():
    """The repeat `awaiting_clarify` does not catch: the same question again, several turns
    later."""
    thread = (threads.ThreadTurn(message="client is unhappy", outcome="clarify",
                                 reply="What did the client actually say?"),
              _answered_turn())
    result, _, _ = _respond(_decides("clarify", question="what did the client ACTUALLY say?"),
                            _answer_payload(), message="they are annoyed again",
                            thread=thread)
    assert result["outcome"] == "answered"


def test_nothing_is_a_follow_up_to_a_question():
    """THE WORST SHAPE OF WRONG THIS TOOL HAS. Ask Naren asked a question, the CSM supplied
    the client's words -- and if that is misread as a follow-up, the carried-source lookup
    walks back PAST the clarify to an older answered turn, finds a real pair_id, and answers
    the new words from a call about something else. Grounded, coherent, wrong client.

    There is nothing for a message after a question to be going deeper on, so a follow-up
    there is wrong by construction rather than by judgement."""
    thread = (_answered_turn(pair_id=11),
              threads.ThreadTurn(message="client is unhappy about pricing",
                                 outcome="clarify",
                                 reply="What did the client actually say?"))
    supplied = "he said \"your rates are 30% above what we budgeted\""

    result, _, embed = _respond(_decides("follow_up"), _answer_payload(),
                                message=supplied, thread=thread)
    assert result["outcome"] == "answered"
    assert embed.seen == [supplied]     # the words the CSM just gave were actually searched


def test_a_query_the_model_composed_rather_than_copied_is_not_embedded():
    """ADR 0006, enforced rather than requested. Since intake is shown the thread it can
    assemble a query out of HISTORY -- the one thing the ADR forbids reaching the vector.
    The prompt says to copy a span of the current message; this is what makes it true."""
    from_history = "pull the last 90 days of spend"      # a previous ANSWER, not this message
    _, _, embed = _respond(_decides("reply_to_client", from_history), _answer_payload(),
                           message=FRAMED, thread=(_prior(reply=from_history),))
    assert embed.seen == [FRAMED]
    assert from_history not in embed.seen


def test_a_genuinely_copied_span_is_left_alone_however_it_was_quoted():
    """The guard must not fire on a real extraction. Lifting a span out of quotation marks,
    or normalising spacing and case, is still copying -- the same rule the offline harness
    scores, so the instrument and the guard cannot drift apart."""
    message = 'Client said "Our Cost Per Hire   is way too high", what do i say'
    _, _, embed = _respond(_decides("reply_to_client", "our cost per hire is way too high"),
                           _answer_payload(), message=message)
    assert embed.seen == ["our cost per hire is way too high"]


def test_a_genuinely_new_clarify_later_in_a_thread_is_still_allowed():
    """A CSM may switch to an unrelated situation without starting a new thread (story 19).
    That situation deserves its own question -- loop prevention must not become never
    asking."""
    thread = (threads.ThreadTurn(message="client is unhappy", outcome="clarify",
                                 reply="What did the client actually say?"),
              _answered_turn())
    result, _, _ = _respond(
        _decides("clarify", question="Which account is this about?"),
        message="different client now, they are unhappy too", thread=thread)
    assert result["outcome"] == "clarify"
    assert result["question"] == "Which account is this about?"


# -- the request boundary ----------------------------------------------------------------

def test_every_response_records_what_intake_decided():
    """Without this, an intake failing on every single request is indistinguishable from one
    that is working: both fall through to answering the message as written and both return a
    normal answer. This is what makes a silent failure observable."""
    answered, _, _ = _respond(_decides("reply_to_client", CLIENT_WORDS), _answer_payload())
    assert answered["intake"] == {"intent": "reply_to_client",
                                  "retrieval_query": CLIENT_WORDS}

    clarified, _, _ = _respond(_decides("clarify", question="What did they say?"),
                               message="client is unhappy")
    assert clarified["intake"]["intent"] == "clarify"

    declined, _, _ = _respond(_decides("out_of_scope"), message="what is our list price")
    assert declined["intake"]["intent"] == "out_of_scope"


def test_the_fallback_is_visible_in_the_response_when_intake_breaks():
    def _boom(message, gateway, *, thread=()):
        raise RuntimeError("intake exploded")

    result, _, _ = _respond(_boom, _answer_payload())
    assert result["intake"]["retrieval_query"] == FRAMED


def test_a_post_retrieval_reason_cannot_be_declined_as_if_nothing_was_searched():
    """Guards the calibration invariant from the other side: every decline that DID retrieve
    must report how close the match it turned down was."""
    from ask_naren import answering
    with pytest.raises(ValueError):
        answering.decline_without_search(answering.NO_CLOSE_MATCH)


def test_an_empty_message_is_refused():
    with pytest.raises(ValueError):
        responding.respond("   ", _pool(), StubGateway(),
                           embed_query=RecordingEmbedder(),
                           classify=_decides("reply_to_client", "x"))


def test_intake_failing_completely_still_answers_the_message_as_written():
    """Intake is an optimisation on a path that already worked. A classify that raises must
    degrade to the pre-intake behaviour rather than fail the request."""
    def _boom(message, gateway, *, thread=()):
        raise RuntimeError("intake exploded")

    result, _, embed = _respond(_boom, _answer_payload())
    assert result["outcome"] == "answered"
    assert embed.seen == [FRAMED]


# -- procedure: the general play, from Layer C (issue #17) ---------------------------------

PLAY_QUOTE = "show them cost per hire against their own baseline"
PLAYBOOK = {
    "situation_signature": "The client challenges cost per hire against what was pitched.",
    "arc": ["Reframe on their own baseline", "Agree a realistic target"],
    "key_moves": [
        {"name": "Reframe on their own baseline",
         "criterion": "Compare cost per hire against the client's own history, not a "
                      "benchmark.",
         "evidence": [{"quote": PLAY_QUOTE, "call": CALL, "account": "uber.com"}]},
    ],
    "signature_language": [],
    "pitfalls_and_variants": [],
}

PLAY_QUESTION = "how do we usually handle cost per hire pushback"


def _play_payload(quote=PLAY_QUOTE, cited_call=CALL):
    return {"declined": False, "answer": "Reframe on their own baseline first.",
            "quote": quote, "cited_call": cited_call}


def _ask_procedure(*payloads, playbook_for=lambda key: PLAYBOOK, query=None):
    gw = StubGateway(*payloads)
    embed = RecordingEmbedder()
    result = responding.respond(
        PLAY_QUESTION, _pool(), gw, embed_query=embed,
        classify=_decides("procedure", query or "cost per hire pushback"),
        playbook_for=playbook_for)
    return result, gw, embed


def test_a_procedure_question_is_answered_from_the_playbook():
    result, _, _ = _ask_procedure(_play_payload())
    assert result["outcome"] == "answered"
    assert result["quote"] == PLAY_QUOTE
    assert result["citation"]["scenario_key"] == "performance_pushback"


def test_a_procedure_answer_names_its_scenario():
    """A catch-all can absorb a question that is not really about it --
    application_volume_and_prioritization carries 11.8% of coachable pairs and 16% of what
    routes there is about jobs rather than applications. Naming it is what lets a CSM
    reject a misroute."""
    result, _, _ = _ask_procedure(_play_payload())
    assert result["match"]["scenario_key"] == "performance_pushback"
    assert result["citation"]["scenario_key"] == "performance_pushback"


def test_a_procedure_answer_carries_no_pair_id_because_it_rests_on_a_playbook_quote():
    """A playbook evidence quote records the call it came from, not a kb_pairs row.
    Inventing a pair_id would point an engineer at an exchange the answer does not rest
    on."""
    result, _, _ = _ask_procedure(_play_payload())
    assert "pair_id" not in result["citation"]
    assert result["citation"]["call_filename"] == CALL


def test_quoting_the_criterion_instead_of_the_evidence_declines():
    """The failure this path is most likely to produce: a criterion is model-written prose
    sitting in the prompt right beside the real quote, so quoting it reads as grounded."""
    composed = _play_payload(quote="Compare cost per hire against the client's own history")
    result, _, _ = _ask_procedure(composed, composed)
    assert result["outcome"] == "declined"
    assert result["reason"] == "grounding_unverified"
    assert "answer" not in result


def test_a_scenario_with_no_live_playbook_falls_back_to_the_layer_b_answer():
    """1 of 34 coachable scenarios has none. The tool still knows what Naren SAID in the
    closest real exchange, and a grounded answer to a slightly different question beats a
    decline -- the ticket's 'degrades rather than fails'."""
    result, _, embed = _ask_procedure(_answer_payload(), playbook_for=lambda key: None)
    assert result["outcome"] == "answered"
    assert result["citation"]["pair_id"] == 11        # the Layer B shape, with a pair
    assert embed.seen == ["cost per hire pushback"]


def test_a_service_started_without_playbooks_still_answers():
    """`playbook_for` is None when the caller loaded none at all. That must degrade to the
    Layer B path rather than raise."""
    gw = StubGateway(_answer_payload())
    result = responding.respond(
        PLAY_QUESTION, _pool(), gw, embed_query=RecordingEmbedder(),
        classify=_decides("procedure", "cost per hire pushback"), playbook_for=None)
    assert result["outcome"] == "answered"


def test_a_live_playbook_with_no_quotable_evidence_degrades_to_layer_b():
    """Same footing as a scenario with no playbook at all: the play cannot be grounded, but
    the tool still knows what Naren SAID in the closest real exchange. It costs no gateway
    call to discover this -- the Layer C generation is never attempted."""
    empty = {**PLAYBOOK, "key_moves": [{"name": "x", "criterion": "y", "evidence": []}]}
    result, gw, _ = _ask_procedure(_answer_payload(), playbook_for=lambda key: empty)
    assert result["outcome"] == "answered"
    assert result["citation"]["pair_id"] == 11        # the Layer B shape
    assert len(gw.calls) == 1                         # one generation, not two


def test_the_procedure_query_is_still_a_span_of_the_message():
    """ADR 0006 applies here too: a query the model composed rather than copied is
    discarded and the message is answered as written."""
    _, _, embed = _ask_procedure(_answer_payload(), query="something it made up",
                                 playbook_for=lambda key: None)
    assert embed.seen == [PLAY_QUESTION]


def test_the_gate_is_not_given_evidence_the_prompt_never_showed():
    """`procedure` renders key_moves. If the gate's sources were built from the whole
    document, a quote from signature_language -- which this prompt does not show -- would
    pass, dropping the "cited something it was actually shown" half of the guarantee.

    It also makes the cheap pre-decline honest: a playbook whose key_moves carry no evidence
    must decline WITHOUT generating, even when other sections have quotes."""
    elsewhere = "we always attribute it back to the source"
    playbook = {
        **PLAYBOOK,
        "key_moves": [{"name": "x", "criterion": "y", "evidence": []}],
        "signature_language": [{"phrase": "attribute it back",
                                "quote": elsewhere, "call": CALL, "account": "uber.com"}],
    }
    result, gw, _ = _ask_procedure(_answer_payload(), playbook_for=lambda key: playbook)
    assert result["outcome"] == "answered"
    assert result["citation"]["pair_id"] == 11        # degraded to Layer B, not Layer C
    assert len(gw.calls) == 1
    assert elsewhere not in gw.calls[0]["prompt"]


# -- the rendered intents, through the seam (issues #19, #20) ------------------------------

SCENARIOS = [
    {"scenario_key": "performance_pushback", "primary_topic": "Performance",
     "business_description": "Client challenges performance against the pitch.",
     "support_calls": 40, "call_coverage": 0.3},
    {"scenario_key": "timeline_question", "primary_topic": "Delivery",
     "business_description": "Client asks when something lands.",
     "support_calls": 9, "call_coverage": 0.1},
]


def _ask_rendered(intent, query="cost per hire pushback", scenarios_for=lambda: SCENARIOS,
                  following_for=None):
    gw = StubGateway()          # NO payloads queued: a generation here is a test failure
    embed = RecordingEmbedder()
    result = responding.respond(
        "what do you cover", _pool(), gw, embed_query=embed,
        classify=_decides(intent, query if intent not in
                          ("discovery", "frequency") else ""),
        scenarios_for=scenarios_for, following_for=following_for)
    return result, gw, embed


def test_a_rendered_intent_never_calls_the_model():
    """The guarantee these paths rest on is that nothing is generated. StubGateway raises on
    any call, so a generation slipping in here fails loudly rather than silently costing a
    token and an invention risk."""
    for intent in ("discovery", "frequency", "show_exchange", "coverage_check"):
        result, gw, _ = _ask_rendered(intent)
        assert result["outcome"] == "rendered", intent
        assert gw.calls == [], intent


def test_a_corpus_question_searches_for_nothing():
    """`discovery` and `frequency` are about the whole corpus, so there is no situation to
    embed. Retrieving anyway would spend a gateway call to ignore the result."""
    for intent in ("discovery", "frequency"):
        _, _, embed = _ask_rendered(intent)
        assert embed.seen == [], intent


def test_a_situation_question_embeds_the_current_message_only():
    _, _, embed = _ask_rendered("show_exchange", query="cost per hire pushback")
    assert embed.seen == ["cost per hire pushback"]


def test_show_exchange_returns_the_stored_pair_through_the_seam():
    result, _, _ = _ask_rendered("show_exchange")
    assert result["kind"] == "show_exchange"
    assert result["citation"]["pair_id"] == 11


def test_what_happened_next_uses_the_injected_adjacency():
    following = [{"trigger_text": "and then", "response_text": "we paced it",
                  "scenario_key": "spend_pacing"}]
    result, _, _ = _ask_rendered("what_happened_next",
                                 following_for=lambda pair_id: following)
    assert result["following"][0]["client_said"] == "and then"


def test_a_service_started_without_layer_a_rows_asks_rather_than_showing_nothing():
    """An empty topic list reads as "nothing is covered", which is false and alarming. A
    clarify says what actually happened and offers the path that still works."""
    result, gw, _ = _ask_rendered("discovery", scenarios_for=lambda: [])
    assert result["outcome"] == "clarify"
    assert result["question"]
    assert gw.calls == []


def test_every_rendered_response_still_records_what_intake_decided():
    result, _, _ = _ask_rendered("frequency")
    assert result["intake"]["intent"] == "frequency"
    assert result["intake"]["retrieval_query"] == ""
