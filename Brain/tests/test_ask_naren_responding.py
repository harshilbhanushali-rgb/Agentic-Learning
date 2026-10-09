"""ask_naren/responding.py -- the one call the HTTP layer makes, and where an intake
decision becomes a response.

`classify` is INJECTED in every test here, the same way `embed_query` and `label_for` are
elsewhere. Two reasons, both deliberate: a dispatch test must not pay for a generation, and
routing accuracy is a separate question measured against labelled messages
(`ask-naren/audit/measure_intake_accuracy.py`) rather than smuggled into behaviour tests.
"""
import asyncio
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

    async def __call__(self, texts):
        self.seen.extend(texts)
        return np.array([[1.0, 0.05]] * len(texts))


class StubGateway:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    async def chat_json(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if not self.payloads:
            raise AssertionError("more generations than the contract allows")
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload, {"served_model": kwargs.get("model")}


def _answer_payload():
    return {"declined": False, "answer": "Reframe on their own baseline.",
            "quote": GOOD_QUOTE, "cited_call": CALL}


def _decides(intent, retrieval_query="", question="", seen_threads=None, my_reply="",
             situation="opens"):
    """A stand-in intake that returns a fixed decision without calling a gateway.

    `seen_threads` records what thread intake was handed, which is the only externally
    observable part of "history reaches intake" (issue #15).
    """
    async def _classify(message, gateway, *, thread=()):
        if seen_threads is not None:
            seen_threads.append(thread)
        return intake.IntakeDecision(intent=intent, retrieval_query=retrieval_query,
                                     question=question, my_reply=my_reply,
                                     situation=situation), {}
    return _classify


def _respond(classify, *payloads, message=FRAMED, embedder=None, thread=()):
    gw = StubGateway(*payloads)
    embed = embedder or RecordingEmbedder()
    result = asyncio.run(responding.respond(message, _pool(), gw, embed_query=embed,
                                            thread=thread, classify=classify))
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
    assert result["intake"] == {"intent": "follow_up", "retrieval_query": "",
                                "situation": "carried"}


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
                                  "retrieval_query": CLIENT_WORDS, "situation": "opens"}

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
        asyncio.run(responding.respond("   ", _pool(), StubGateway(),
                           embed_query=RecordingEmbedder(),
                           classify=_decides("reply_to_client", "x")))


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

#: The RECORD, not the document. `n_evidence` sits beside `playbook` rather than inside it,
#: which is why the service keeps the whole row -- `play_confidence` (issue #18) reports
#: exactly that number.
PLAYBOOK_RECORD = {"playbook": PLAYBOOK, "n_evidence": 7, "scenario_key": "performance_pushback"}


def _play_payload(quote=PLAY_QUOTE, cited_call=CALL):
    return {"declined": False, "answer": "Reframe on their own baseline first.",
            "quote": quote, "cited_call": cited_call}


def _ask_procedure(*payloads, playbook_for=lambda key: PLAYBOOK_RECORD, query=None):
    gw = StubGateway(*payloads)
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        PLAY_QUESTION, _pool(), gw, embed_query=embed,
        classify=_decides("procedure", query or "cost per hire pushback"),
        playbook_for=playbook_for))
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
    result = asyncio.run(responding.respond(
        PLAY_QUESTION, _pool(), gw, embed_query=RecordingEmbedder(),
        classify=_decides("procedure", "cost per hire pushback"), playbook_for=None))
    assert result["outcome"] == "answered"


def test_a_live_playbook_with_no_quotable_evidence_degrades_to_layer_b():
    """Same footing as a scenario with no playbook at all: the play cannot be grounded, but
    the tool still knows what Naren SAID in the closest real exchange. It costs no gateway
    call to discover this -- the Layer C generation is never attempted."""
    empty = {**PLAYBOOK_RECORD,
             "playbook": {**PLAYBOOK, "key_moves": [{"name": "x", "criterion": "y",
                                                     "evidence": []}]}}
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
        **PLAYBOOK_RECORD,
        "playbook": {
            **PLAYBOOK,
            "key_moves": [{"name": "x", "criterion": "y", "evidence": []}],
            "signature_language": [{"phrase": "attribute it back", "quote": elsewhere,
                                    "call": CALL, "account": "uber.com"}],
        },
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
    corpus = intent in ("discovery", "frequency")
    # THE MESSAGE MUST CONTAIN THE QUERY. That is the only shape intake is allowed to
    # produce (ADR 0006: the embedded query is a span of THIS message), and `_guarded`
    # enforces it on every intent that embeds. A fixture whose query is absent from its
    # message is exercising a decision the guard exists to reject, so it would measure the
    # fallback rather than the path it names.
    message = "what do you cover" if corpus else f"can you show me {query}"
    gw = StubGateway()          # NO payloads queued: a generation here is a test failure
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        message, _pool(), gw, embed_query=embed,
        classify=_decides(intent, "" if corpus else query),
        scenarios_for=scenarios_for, following_for=following_for))
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


# -- the five playbook intents through the seam (issue #18) --------------------------------

def _ask_playbook(intent, playbook_for=lambda key: PLAYBOOK_RECORD):
    # The query is a span of the message, for the reason `_ask_rendered` spells out.
    gw = StubGateway()          # a generation here is a test failure
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        "what order do i do these in for cost per hire pushback", _pool(), gw,
        embed_query=embed, classify=_decides(intent, "cost per hire pushback"),
        playbook_for=playbook_for))
    return result, gw, embed


def test_every_playbook_intent_renders_without_generating():
    for intent in ("sequence", "phrasing", "pitfalls", "scenario_check", "play_confidence"):
        result, gw, _ = _ask_playbook(intent)
        assert result["outcome"] == "rendered", intent
        assert result["kind"] == intent, intent
        assert gw.calls == [], intent


def test_a_composed_query_is_not_embedded_on_any_intent_that_retrieves():
    """ADR 0006 is about THE VECTOR, not about which intent produced it. Eight intents now
    embed `retrieval_query`; the guard originally covered two, so six could reach the vector
    with text intake composed out of the thread.

    The shape that makes it matter: turn 1 answers a question about cost per hire, turn 2 is
    "and what usually goes wrong?" -- which names no situation, so a model that composes
    rather than copies will lift one from the history. That decides WHICH PLAY gets
    rendered, with `scenario_key` the only tell."""
    from_history = "pull the last 90 days of spend"      # a previous ANSWER, not this message
    for intent in ("sequence", "phrasing", "pitfalls", "scenario_check", "play_confidence",
                   "show_exchange", "what_happened_next", "coverage_check"):
        embed = RecordingEmbedder()
        asyncio.run(responding.respond(
            "and what usually goes wrong?", _pool(), StubGateway(_answer_payload()),
            embed_query=embed, classify=_decides(intent, from_history),
            playbook_for=lambda key: PLAYBOOK_RECORD,
            scenarios_for=lambda: SCENARIOS,
            thread=(_prior(reply=from_history),)))
        assert from_history not in embed.seen, intent


def test_a_copied_span_still_reaches_the_vector_on_a_playbook_intent():
    """The guard must not fire on a real extraction, or every threaded playbook question
    degrades to a Layer B generation on a fragment."""
    message = "what usually goes wrong with cost per hire pushback"
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        message, _pool(), StubGateway(), embed_query=embed,
        classify=_decides("pitfalls", "cost per hire pushback"),
        playbook_for=lambda key: PLAYBOOK_RECORD))
    assert embed.seen == ["cost per hire pushback"]
    assert result["kind"] == "pitfalls"


def test_a_playbook_intent_names_the_scenario_it_answered_from():
    """A catch-all can absorb the question, and these answers have no citation to give it
    away -- the scenario key is the only thing that makes a misroute visible."""
    result, _, _ = _ask_playbook("sequence")
    assert result["scenario_key"] == "performance_pushback"


def test_a_scenario_with_no_live_playbook_asks_rather_than_declining_or_faking_one():
    """Unlike `procedure`, there is no Layer B substitute for "what order do i do this in".
    Saying so and pointing at what does work beats both a decline and a fabricated play."""
    result, gw, _ = _ask_playbook("sequence", playbook_for=lambda key: None)
    assert result["outcome"] == "clarify"
    assert "performance pushback" in result["question"]
    assert gw.calls == []


# -- contrasting the CSM's own reply through the seam (issue #21) --------------------------

CONTRAST_MESSAGE = ('client said "our cost per hire is way too high" and i told them we '
                    "would review the campaign settings this week -- how does that compare")
CSM_REPLY = "we would review the campaign settings this week"


def _ask_contrast(*payloads, message=CONTRAST_MESSAGE, my_reply=CSM_REPLY,
                  query="our cost per hire is way too high"):
    gw = StubGateway(*payloads)
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        message, _pool(), gw, embed_query=embed,
        classify=_decides("contrast_my_reply", query, my_reply=my_reply)))
    return result, gw, embed


def test_a_contrast_searches_on_the_clients_words_not_on_the_csms_reply():
    """The question is "what did Naren say when a client said this", so the CLIENT'S turn is
    the query. Embedding the CSM's reply would search the responder's side of the corpus for
    a trigger, which is a different conversation entirely."""
    result, _, embed = _ask_contrast(_answer_payload())
    assert embed.seen == ["our cost per hire is way too high"]
    assert CSM_REPLY not in embed.seen
    assert result["outcome"] == "answered"
    assert result["my_reply"] == CSM_REPLY


def test_a_reply_the_model_composed_rather_than_copied_is_not_put_in_the_csms_mouth():
    """`my_reply` is never embedded, so ADR 0006 does not reach it -- but it is rendered
    back as the thing Naren is contrasted against. A composed one shows a CSM a comparison
    against a reply they never wrote, on a page whose whole subject is what they wrote."""
    result, _, _ = _ask_contrast(_answer_payload(),
                                 my_reply="i promised them a 40% improvement by Friday")
    # Fell back to answering the message as written, so nothing is attributed to the CSM.
    assert "my_reply" not in result
    assert result["intake"]["intent"] == "reply_to_client"


def test_a_contrast_still_records_what_intake_decided():
    result, _, _ = _ask_contrast(_answer_payload())
    assert result["intake"]["intent"] == "contrast_my_reply"
    assert result["intake"]["retrieval_query"] == "our cost per hire is way too high"


# -- which accounts a situation has come up with, through the seam (issue #22) --------------

def _wide_pool():
    """Three pairs across three calls, two of them the same account."""
    pairs = [
        {"pair_id": 1, "trigger_text": "cost per hire is too high",
         "response_text": RESPONSE,
         "call_filename": "20230503_uber_joveo_weekly_performance_review_d18cc178.txt",
         "scenario_key": "performance_pushback"},
        {"pair_id": 2, "trigger_text": "cost per hire looks wrong",
         "response_text": RESPONSE,
         "call_filename": "20230509_uber_joveo_connect_409d34b7.txt",
         "scenario_key": "performance_pushback"},
        {"pair_id": 3, "trigger_text": "our cost per hire is way off",
         "response_text": RESPONSE,
         "call_filename": "3e4c3393-c3cc-4047-a5bc-57bccbfaee4f.txt",
         "scenario_key": "performance_pushback"},
    ]
    return retrieval.RetrievalPool(
        pairs, np.array([[1.0, 0.0], [0.99, 0.1], [0.98, 0.2]]))


def _ask_where_else(account_for=lambda call: "Uber" if "uber" in call else None):
    gw = StubGateway()          # a generation here is a test failure
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        "which other clients have raised cost per hire", _wide_pool(), gw,
        embed_query=embed,
        classify=_decides("where_else_seen", "cost per hire"),
        account_for=account_for))
    return result, gw, embed


def test_where_else_seen_reads_a_neighbourhood_rather_than_the_nearest_match():
    """The one rendered intent that cannot be answered from one exchange: "is this a
    one-client quirk or a pattern" has no single-exchange form."""
    result, gw, embed = _ask_where_else()
    assert result["kind"] == "where_else_seen"
    assert result["exchanges"] == 3            # all three neighbours were read, not just one
    assert gw.calls == []                      # and nothing was generated
    assert embed.seen == ["cost per hire"]     # one embedding, of the current message alone


def test_where_else_seen_collapses_one_account_and_refuses_to_name_the_other():
    result, _, _ = _ask_where_else()
    assert result["accounts_named"] == 1
    named = [a for a in result["accounts"] if a["named"]][0]
    assert named["account"] == "Uber" and named["exchanges"] == 2 and named["calls"] == 2
    assert result["unnamed_calls"] == 1
    assert result["accounts_at_most"] == 2     # Uber, plus the one call nothing can name


def test_where_else_seen_still_answers_when_no_account_can_be_named_at_all():
    """Criterion 3 through the seam: with no sidecars every call is unnameable, and the
    answer is thinner rather than absent or broken."""
    result, _, _ = _ask_where_else(account_for=lambda call: None)
    assert result["outcome"] == "rendered"
    assert result["accounts_named"] == 0
    assert result["unnamed_calls"] == 3
    assert all(a["named"] is False for a in result["accounts"])


# -- the two composites through the seam (issue #23) ----------------------------------------

def test_call_prep_composes_rendered_paths_and_generates_nothing():
    """Criterion 3: composes existing answer paths rather than introducing a new grounding
    rule. Composing only RENDERED paths is what makes that true -- ADR 0009 warns a composite
    inherits the weaker of its halves' guarantees, and neither half here has a weaker one."""
    gw = StubGateway()          # a generation here is a test failure
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        "im on a renewal call tomorrow about cost per hire", _wide_pool(), gw,
        embed_query=embed,
        classify=_decides("call_prep", "cost per hire"),
        scenarios_for=lambda: SCENARIOS,
        playbook_for=lambda key: PLAYBOOK_RECORD))
    assert result["outcome"] == "rendered"
    assert result["kind"] == "call_prep"
    assert gw.calls == []
    assert embed.seen == ["cost per hire"]
    assert result["scenarios"][0]["scenario_key"] == "performance_pushback"
    assert result["intake"]["intent"] == "call_prep"


def test_improve_at_move_names_its_scenario_and_generates_nothing():
    """Criterion 4: names its scenarios so a misroute is visible."""
    gw = StubGateway()
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        "i keep fumbling the reframe on their own baseline", _pool(), gw, embed_query=embed,
        classify=_decides("improve_at_move", "reframe on their own baseline"),
        playbook_for=lambda key: PLAYBOOK_RECORD))
    assert result["kind"] == "improve_at_move"
    assert result["scenario_key"] == "performance_pushback"
    assert gw.calls == []


def test_improve_at_move_with_no_recorded_play_asks_rather_than_faking_one():
    """Same clarify `_from_playbook` returns, from the same definition: there is no Layer B
    substitute for "the criterion for this move"."""
    gw = StubGateway()
    result = asyncio.run(responding.respond(
        "i keep fumbling the reframe", _pool(), gw, embed_query=RecordingEmbedder(),
        classify=_decides("improve_at_move", "reframe"),
        playbook_for=lambda key: None))
    assert result["outcome"] == "clarify"
    assert "performance pushback" in result["question"]
    assert gw.calls == []


# -- every path that ran `pool.top1` reports its match (issue #45) ---------------------------

class FixedEmbedder:
    """Embeds everything to one fixed vector, so a test chooses WHICH pair is nearest."""

    def __init__(self, vector):
        self.vector = vector

    async def __call__(self, texts):
        return np.array([self.vector] * len(texts))


#: Both pairs in `_pool()`, reached on purpose, so a `scenario_key` that merely happened to
#: equal a constant cannot pass: it has to be the one retrieval actually reached.
NEAREST = [([1.0, 0.05], "performance_pushback"), ([0.05, 1.0], "timeline_question")]

#: The eight paths #45 names. The query is a span of the message for the reason
#: `_ask_rendered` spells out.
MATCHED_PATHS = ("sequence", "phrasing", "pitfalls", "scenario_check", "play_confidence",
                 "improve_at_move", "what_happened_next")


def _ask_path(intent, vector, playbook_for=lambda key: {**PLAYBOOK_RECORD,
                                                        "scenario_key": key}):
    gw = StubGateway()          # a generation here is a test failure
    result = asyncio.run(responding.respond(
        "tell me about cost per hire pushback", _pool(), gw,
        embed_query=FixedEmbedder(vector),
        classify=_decides(intent, "cost per hire pushback"),
        playbook_for=playbook_for, following_for=lambda pair_id: [],
        scenarios_for=lambda: SCENARIOS))
    assert gw.calls == [], intent
    return result


def _expected_match(vector, scenario_key):
    """What `show_exchange` -- a path that ALREADY reported its match -- says for the same
    vector. The new paths must say exactly the same thing, not a near copy."""
    return asyncio.run(responding.respond(
        "can you show me cost per hire pushback", _pool(), StubGateway(),
        embed_query=FixedEmbedder(vector),
        classify=_decides("show_exchange", "cost per hire pushback")))["match"]


@pytest.mark.parametrize("vector,scenario_key", NEAREST)
@pytest.mark.parametrize("intent", MATCHED_PATHS)
def test_every_rendered_path_that_retrieved_reports_its_match(intent, vector, scenario_key):
    result = _ask_path(intent, vector)
    assert result["outcome"] == "rendered" and result["kind"] == intent
    assert set(result["match"]) == {"cosine", "scenario_key", "rank"}
    assert isinstance(result["match"]["cosine"], float)
    assert result["match"]["scenario_key"] == scenario_key
    assert result["match"]["rank"] == 1
    assert result["match"] == _expected_match(vector, scenario_key)


@pytest.mark.parametrize("vector,scenario_key", NEAREST)
@pytest.mark.parametrize("intent", ("sequence", "phrasing", "pitfalls", "scenario_check",
                                    "play_confidence", "improve_at_move"))
def test_the_no_recorded_play_clarify_reports_the_match_that_named_its_scenario(
        intent, vector, scenario_key):
    """The one clarify that searched: the scenario it names came from retrieval, so it has a
    real cosine. Still no answer, quote or citation -- the rule is about unverified TEXT."""
    result = _ask_path(intent, vector, playbook_for=lambda key: None)
    assert result["outcome"] == "clarify"
    assert scenario_key.replace("_", " ") in result["question"]
    assert isinstance(result["match"]["cosine"], float)
    assert result["match"] == _expected_match(vector, scenario_key)
    assert "answer" not in result and "quote" not in result and "citation" not in result


def test_a_clarify_that_searched_nothing_still_carries_no_match():
    """Where a path legitimately has no match it stays absent rather than being invented:
    intake's clarify and the no-topic-index clarify ran no retrieval."""
    intake_clarify, _, _ = _respond(_decides("clarify", question="What did they say?"),
                                    message="client is unhappy")
    no_index, _, _ = _ask_rendered("discovery", scenarios_for=lambda: [])
    assert intake_clarify["outcome"] == no_index["outcome"] == "clarify"
    assert "match" not in intake_clarify and "match" not in no_index


def test_the_paths_that_already_reported_a_match_are_unchanged():
    """show_exchange and coverage_check reported `match` before #45; the rendered paths that
    read a neighbourhood or the whole corpus never did, and still do not."""
    for intent in ("show_exchange", "coverage_check"):
        result, _, _ = _ask_rendered(intent)
        assert result["match"] == {"cosine": pytest.approx(1 / np.sqrt(1.0025)),
                                   "scenario_key": "performance_pushback", "rank": 1}, intent
    for intent in ("discovery", "frequency"):
        result, _, _ = _ask_rendered(intent)
        assert "match" not in result, intent
    where, _, _ = _ask_where_else()
    assert "match" not in where


# -- a message on a carried situation answers from it (issue #53, ADR 0013) ----------------

class NoSearchPool(retrieval.RetrievalPool):
    """`_pool()`, except that ranking anything fails the test. A carried answer must run no
    vector search at all, not merely ignore one."""

    async def top1(self, query_vec):
        raise AssertionError("a carried answer ran a vector search")

    async def topk(self, query_vec, k):
        raise AssertionError("a carried answer ran a vector search")


def _no_search_pool():
    return NoSearchPool(_pool().pairs, np.array([[1.0, 0.0], [0.0, 1.0]]))


#: The thread's scenario is NOT the one a search would reach: `RecordingEmbedder` lands on
#: pair 11 (performance_pushback), and these turns are about pair 22 (timeline_question).
#: So an answer about timeline_question can only have come from the thread.
CARRIED_SCENARIO = "timeline_question"


def _on_timeline(outcome="answered", pair_id=22, scenario_key=CARRIED_SCENARIO):
    return threads.ThreadTurn(message="client asks when the integration goes live",
                              reply="Let me check with the team.", outcome=outcome,
                              pair_id=pair_id, scenario_key=scenario_key)


def _carried(intent, thread, message="what's the play here", pool=None, payloads=(),
             playbook_for=lambda key: {**PLAYBOOK_RECORD, "scenario_key": key}):
    gw = StubGateway(*payloads)
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        message, pool or _no_search_pool(), gw, embed_query=embed, thread=thread,
        classify=_decides(intent, situation="carried"), playbook_for=playbook_for,
        scenarios_for=lambda: SCENARIOS, following_for=lambda pair_id: []))
    return result, gw, embed


SCENARIO_RENDERED = ("sequence", "phrasing", "pitfalls", "scenario_check", "play_confidence",
                     "improve_at_move")


@pytest.mark.parametrize("intent", SCENARIO_RENDERED)
def test_a_carried_scenario_question_answers_for_the_last_answers_scenario(intent):
    """Story 1-6: "what's the play here" after an answer gets the play for THAT situation --
    with no embedding and no vector search, and no match, because nothing was searched."""
    result, gw, embed = _carried(intent, (_on_timeline(),))
    assert result["outcome"] == "rendered" and result["kind"] == intent
    assert result["scenario_key"] == CARRIED_SCENARIO
    assert embed.seen == []
    assert gw.calls == []
    assert "match" not in result


def test_a_carried_procedure_answers_the_play_for_the_carried_scenario():
    """Story 7. Generated from the carried scenario's playbook, so one generation and no
    search -- and the answer names that scenario."""
    seen_keys = []

    def playbook_for(key):
        seen_keys.append(key)
        return {**PLAYBOOK_RECORD, "scenario_key": key}

    result, gw, embed = _carried("procedure", (_on_timeline(),), payloads=(_play_payload(),),
                                 playbook_for=playbook_for)
    assert result["outcome"] == "answered"
    assert result["citation"]["scenario_key"] == CARRIED_SCENARIO
    assert seen_keys == [CARRIED_SCENARIO]
    assert embed.seen == [] and len(gw.calls) == 1
    assert "match" not in result


def test_a_carried_procedure_that_cannot_be_grounded_declines_without_inventing_a_match():
    composed = _play_payload(quote="Compare cost per hire against the client's own history")
    result, _, embed = _carried("procedure", (_on_timeline(),), payloads=(composed, composed))
    assert result["outcome"] == "declined"
    assert result["reason"] == "grounding_unverified"
    assert "match" not in result
    assert embed.seen == []


def test_a_carried_procedure_with_no_recorded_play_says_so_rather_than_searching():
    """`procedure` normally degrades to Layer B -- but that answers from a SEARCH, and a
    carried message has nothing of its own to search on."""
    result, gw, embed = _carried("procedure", (_on_timeline(),),
                                 playbook_for=lambda key: None)
    assert result["outcome"] == "clarify"
    assert "timeline question" in result["question"]
    assert embed.seen == [] and gw.calls == []
    assert "match" not in result


def test_a_rendered_turn_is_carried_too():
    """After "what's the play for X", "and how does he word it?" stays on X. The rendered
    turn holds a scenario and no pair (issue #52)."""
    played = _on_timeline(outcome="rendered", pair_id=None)
    result, _, embed = _carried("phrasing", (played,), message="and how does he word it?")
    assert result["scenario_key"] == CARRIED_SCENARIO
    assert embed.seen == []


def test_a_carried_pairs_scenario_counts_as_the_scenario():
    """An exchange implies its scenario (CONTEXT.md **Anchor**)."""
    exchange_only = _on_timeline(outcome="rendered", scenario_key="")
    result, _, _ = _carried("sequence", (exchange_only,))
    assert result["scenario_key"] == CARRIED_SCENARIO


def test_clarifies_and_declines_are_skipped_when_finding_what_is_carried():
    """Story 17: "what's the play" after "no close match" still means the last real answer."""
    thread = (_on_timeline(),
              threads.ThreadTurn(message="x", outcome="declined", reply="Nothing close."),
              threads.ThreadTurn(message="y", outcome="clarify", reply="Which account?"))
    result, _, embed = _carried("sequence", thread)
    assert result["scenario_key"] == CARRIED_SCENARIO
    assert embed.seen == []


def test_carrying_never_walks_back_past_the_most_recent_answer():
    """Story 16: "show me that" means the thing just read. The newest answered or rendered
    turn here is about many situations and holds no scenario -- so Ask Naren asks, rather
    than reaching back to the older answer about something else."""
    thread = (_on_timeline(),
              threads.ThreadTurn(message="what do you cover", outcome="rendered",
                                 reply="Showed what Ask Naren covers."))
    result, gw, embed = _carried("sequence", thread)
    assert result["outcome"] == "clarify"
    assert result["question"] == responding.NO_CARRIED_ANCHOR
    assert embed.seen == [] and gw.calls == []
    assert "match" not in result


def test_nothing_to_carry_is_the_fixed_clarify():
    """Stories 14-15: asked by Ask Naren itself, worded the same way every time."""
    thread = (threads.ThreadTurn(message="x", outcome="declined", reply="Nothing close."),)
    result, _, _ = _carried("pitfalls", thread)
    assert result["outcome"] == "clarify"
    assert result["question"] == responding.NO_CARRIED_ANCHOR
    assert "paste what the client said" in result["question"].lower()


def test_a_carried_pair_gone_from_the_pool_with_no_scenario_is_not_an_anchor():
    stale = _on_timeline(outcome="rendered", pair_id=9999, scenario_key="")
    result, _, _ = _carried("sequence", (stale,))
    assert result["question"] == responding.NO_CARRIED_ANCHOR


def test_the_fixed_clarify_is_never_asked_twice_in_a_row():
    """The existing guard: the CSM is answering it right now, so asking again is the loop.
    The message is answered as written instead."""
    asked = threads.ThreadTurn(message="what's the play here", outcome="clarify",
                               reply=responding.NO_CARRIED_ANCHOR)
    result, _, embed = _carried("sequence", (asked,), message="still not sure",
                                pool=_pool(), payloads=(_answer_payload(),))
    assert result["outcome"] == "answered"
    assert embed.seen == ["still not sure"]


def test_with_no_thread_a_carried_decision_behaves_as_opening_one():
    """Story 18: a single question behaves exactly as today. Nothing above it to carry, so
    no copied query is left and the existing fallback answers the message as written."""
    result, _, embed = _carried("sequence", (), message="what's the play here",
                                pool=_pool(), payloads=(_answer_payload(),))
    assert embed.seen == ["what's the play here"]
    assert result["intake"]["situation"] == "opens"


@pytest.mark.parametrize("intent,extra", [
    ("reply_to_client", {}),
    ("contrast_my_reply", {"my_reply": "i said we would look into it"}),
])
def test_a_new_only_intent_searches_fresh_and_never_inherits(intent, extra):
    """Stories 11-12: new client words are never answered from the previous client's
    situation."""
    message = f"client said {CLIENT_WORDS} and i said we would look into it"
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        message, _pool(), StubGateway(_answer_payload()), embed_query=embed,
        thread=(_on_timeline(),),
        classify=_decides(intent, CLIENT_WORDS, situation="carried", **extra)))
    assert embed.seen == [CLIENT_WORDS]
    assert result["citation"]["pair_id"] == 11          # the search's pair, not the thread's 22
    assert result["intake"]["situation"] == "opens"


@pytest.mark.parametrize("intent", ("where_else_seen", "call_prep"))
def test_a_neighbourhood_intent_searches_fresh(intent):
    """Story 13, until carrying a neighbourhood is designed separately."""
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        "which other clients have raised cost per hire", _wide_pool(), StubGateway(),
        embed_query=embed, thread=(_on_timeline(),),
        classify=_decides(intent, "cost per hire", situation="carried"),
        scenarios_for=lambda: SCENARIOS, playbook_for=lambda key: PLAYBOOK_RECORD))
    assert embed.seen == ["cost per hire"]
    assert result["kind"] == intent


def test_an_opening_decision_that_fails_the_copy_check_falls_back_and_is_never_carried():
    """Story 28, and ADR 0013's rejected option: a paraphrased NEW situation must not
    inherit the previous client's scenario."""
    message = "and what usually goes wrong?"
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        message, _pool(), StubGateway(_answer_payload()), embed_query=embed,
        thread=(_on_timeline(),),
        classify=_decides("pitfalls", "timeline integration problems", situation="opens"),
        playbook_for=lambda key: PLAYBOOK_RECORD))
    assert embed.seen == [message]
    assert result["intake"] == {"intent": "reply_to_client", "retrieval_query": message,
                                "situation": "opens"}


def test_the_intake_echo_shows_a_carried_situation():
    """Story 24: a carried answer is told apart from a searched one when debugging."""
    result, _, _ = _carried("sequence", (_on_timeline(),))
    assert result["intake"] == {"intent": "sequence", "retrieval_query": "",
                                "situation": "carried"}


def test_carrying_embeds_no_thread_text():
    """Story 27, ADR 0006: the thread supplies an identifier, never text that is embedded."""
    for intent in (*SCENARIO_RENDERED, "procedure"):
        _, _, embed = _carried(intent, (_on_timeline(),), payloads=(_play_payload(),))
        assert embed.seen == [], intent


# -- a carried exchange question answers from the exchange the last answer rested on (#54) --

EXCHANGE_INTENTS = ("show_exchange", "what_happened_next", "coverage_check")


def _carried_exchange(intent, thread, message="show me the actual exchange",
                      following_for=lambda pair_id: [], pool=None, payloads=()):
    gw = StubGateway(*payloads)
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        message, pool or _no_search_pool(), gw, embed_query=embed, thread=thread,
        classify=_decides(intent, situation="carried"), scenarios_for=lambda: SCENARIOS,
        following_for=following_for))
    return result, gw, embed


def test_a_carried_show_exchange_shows_the_exchange_the_last_answer_rested_on():
    """Story 8. The thread's pair 22 is NOT the one a search would reach (pair 11), so
    showing it can only have come from the thread -- and the pool fails on any search."""
    result, gw, embed = _carried_exchange("show_exchange", (_on_timeline(),))
    assert result["kind"] == "show_exchange"
    assert result["citation"]["pair_id"] == 22
    assert result["exchange"]["client_said"] == "when does the integration go live"
    assert embed.seen == [] and gw.calls == []
    assert "match" not in result


def test_a_carried_what_happened_next_shows_what_followed_that_exchange():
    """Story 9: what followed THAT exchange in its call."""
    asked_after = []

    def following_for(pair_id):
        asked_after.append(pair_id)
        return [{"trigger_text": "and after go-live?", "response_text": "We monitor it.",
                 "scenario_key": "timeline_question"}]

    result, _, embed = _carried_exchange("what_happened_next", (_on_timeline(),),
                                         message="what happened after that",
                                         following_for=following_for)
    assert asked_after == [22]
    assert result["following"][0]["client_said"] == "and after go-live?"
    assert result["citation"]["pair_id"] == 22
    assert embed.seen == []
    assert "match" not in result


def test_a_carried_coverage_check_reports_on_the_carried_pairs_situation():
    """Story 10."""
    result, _, embed = _carried_exchange("coverage_check", (_on_timeline(),),
                                         message="do we have much on this")
    assert result["nearest"]["scenario_key"] == CARRIED_SCENARIO
    assert result["nearest"]["support_calls"] == 9          # from SCENARIOS
    assert result["asked_about"] == "do we have much on this"
    assert embed.seen == []
    assert "match" not in result


def test_a_carried_exchange_after_a_rendered_exchange_continues_from_it():
    """Story 9's second half: "what happened after that" after an exchange view."""
    shown = _on_timeline(outcome="rendered")
    result, _, _ = _carried_exchange("what_happened_next", (shown,),
                                     message="what happened after that")
    assert result["citation"]["pair_id"] == 22


@pytest.mark.parametrize("intent", EXCHANGE_INTENTS)
def test_an_answer_resting_on_no_single_exchange_is_the_fixed_clarify(intent):
    """Story 14. A playbook answer rests on a scenario, not an exchange, and a scenario never
    picks one (CONTEXT.md **Anchor**). Ask Naren asks rather than showing one at random."""
    played = _on_timeline(outcome="rendered", pair_id=None)
    result, gw, embed = _carried_exchange(intent, (played,))
    assert result["outcome"] == "clarify"
    assert result["question"] == responding.NO_CARRIED_ANCHOR
    assert embed.seen == [] and gw.calls == []
    assert "match" not in result


@pytest.mark.parametrize("intent", EXCHANGE_INTENTS)
def test_a_carried_pair_gone_from_the_pool_is_the_fixed_clarify(intent):
    """The pool is loaded once at startup, and a pipeline re-run can retire a pair. The
    turn's scenario is still known -- and is still not an exchange."""
    stale = _on_timeline(pair_id=9999)
    result, _, embed = _carried_exchange(intent, (stale,))
    assert result["question"] == responding.NO_CARRIED_ANCHOR
    assert embed.seen == []


def test_the_fixed_exchange_clarify_is_never_asked_twice_in_a_row():
    asked = threads.ThreadTurn(message="show me the actual exchange", outcome="clarify",
                               reply=responding.NO_CARRIED_ANCHOR)
    played = _on_timeline(outcome="rendered", pair_id=None)     # holds no exchange
    result, _, embed = _carried_exchange("show_exchange", (played, asked),
                                         message="the one about go-live", pool=_pool(),
                                         payloads=(_answer_payload(),))
    assert result["outcome"] == "answered"
    assert embed.seen == ["the one about go-live"]


def test_an_exchange_question_that_opens_a_situation_still_searches_and_reports_its_match():
    """Opening a situation is unchanged: search, and say how close the match was."""
    result, _, _ = _ask_rendered("show_exchange")
    assert result["citation"]["pair_id"] == 11
    assert set(result["match"]) == {"cosine", "scenario_key", "rank"}


# -- the conversation-aware search (issue #25) --------------------------------------------

ATS_EARLIER = ("they said the integration was supposed to be live 3 weeks ago and nothing "
               "is syncing")
ATS_SEARCH = "integration was supposed to be live 3 weeks ago and nothing is syncing"
ATS_THREAD = (_prior(message=ATS_EARLIER, reply="Which exchange do you mean?",
                     outcome="clarify", pair_id=None, scenario_key=""),)


def _rewrites(intent, retrieval_query, search_query, situation="opens", seen=None):
    """A stand-in intake that writes a conversation-aware search, and records whether it was
    asked to (`seen` gets the `rewrite` flag it was called with)."""
    async def _classify(message, gateway, *, thread=(), rewrite=False):
        if seen is not None:
            seen.append(rewrite)
        return intake.IntakeDecision(intent=intent, retrieval_query=retrieval_query,
                                     search_query=search_query, situation=situation), {}
    return _classify


def _respond_25(classify, *payloads, message="the ats one", thread=ATS_THREAD,
                search=True, sees=True, **kwargs):
    gw = StubGateway(*payloads)
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(message, _pool(), gw, embed_query=embed,
                                            thread=thread, classify=classify,
                                            search_from_conversation=search,
                                            answer_sees_conversation=sees, **kwargs))
    return result, gw, embed


def test_with_the_switch_on_a_vague_message_is_searched_with_the_conversation():
    """B5 in the live run: 'the ats one' searched on its own three words reached an
    unrelated roadmap answer. The CSM had already said what it was."""
    asked = []
    _, _, embed = _respond_25(_rewrites("reply_to_client", "the ats one", ATS_SEARCH,
                                        seen=asked), _answer_payload())
    assert asked == [True]
    assert embed.seen == [ATS_SEARCH]


def test_a_search_with_words_the_csm_never_typed_is_not_used():
    """The check ADR 0006 asked for: a bad rewrite falls back to the plain words."""
    _, _, embed = _respond_25(
        _rewrites("reply_to_client", "the ats one", "ats sync failure our fault"),
        _answer_payload())
    assert embed.seen == ["the ats one"]


def test_with_the_switch_off_nothing_changes():
    """Even when a classifier hands back a search, off means today's behaviour exactly:
    intake is not asked for one, the plain words are searched, and nothing new is echoed."""
    asked = []
    result, gw, embed = _respond_25(
        _rewrites("reply_to_client", "the ats one", ATS_SEARCH, seen=asked),
        _answer_payload(), search=False, sees=False)
    assert asked == [False]
    assert embed.seen == ["the ats one"]
    assert "search_query" not in result["intake"]
    assert "conversation so far" not in gw.calls[0]["prompt"]


def test_the_search_that_ran_is_echoed():
    """A rewrite must be checkable in production, not only offline."""
    result, _, _ = _respond_25(_rewrites("reply_to_client", "the ats one", ATS_SEARCH),
                               _answer_payload())
    assert result["intake"]["search_query"] == ATS_SEARCH


def test_a_rejected_search_is_echoed_as_empty():
    result, _, _ = _respond_25(
        _rewrites("reply_to_client", "the ats one", "ats sync failure our fault"),
        _answer_payload())
    assert result["intake"]["search_query"] == ""


def test_the_answer_is_written_seeing_the_conversation_and_the_whole_message():
    """Told only 'the ats one', the answer model cannot tell whether the exchange fits."""
    _, gw, _ = _respond_25(_rewrites("reply_to_client", "the ats one", ATS_SEARCH),
                           _answer_payload())
    prompt = gw.calls[0]["prompt"]
    assert ATS_EARLIER in prompt
    assert "the ats one" in prompt
    assert RESPONSE in prompt


def test_a_carried_message_still_searches_nothing_with_the_switch_on():
    """Rewriting must never cancel carrying (#53/#54)."""
    thread = (_prior(),)
    result, _, embed = _respond_25(
        _rewrites("sequence", "", ATS_SEARCH, situation="carried"),
        thread=thread, message="whats the play here", playbook_for=lambda key: None)
    assert embed.seen == []
    assert result["intake"]["search_query"] == ""      # nothing was searched


def test_a_carried_message_with_nothing_to_carry_is_searched_on_its_rewrite():
    """'the ats one' after a clarify: the last turn holds no answer to carry, so instead of
    asking 'which conversation do you mean?' it is searched on what the CSM said earlier."""
    _, _, embed = _respond_25(
        _rewrites("show_exchange", "", ATS_SEARCH, situation="carried"))
    assert embed.seen == [ATS_SEARCH]


def test_where_else_with_no_words_of_its_own_searches_the_conversation():
    """'where else has this come up' mid-thread used to search that literal sentence."""
    feed = "half their reqs dont show up after the import"
    thread = (_prior(message=f"one of my clients feed has been dropping jobs, {feed}"),)
    _, _, embed = _respond_25(
        _rewrites("where_else_seen", "where else has this come up",
                  "feed has been dropping jobs, half their reqs dont show up after the import"),
        thread=thread, message="where else has this come up")
    assert embed.seen == ["feed has been dropping jobs, half their reqs dont show up after "
                          "the import"]


# -- the wide retry (issue #25, half 2) ---------------------------------------------------

DECLINES = {"declined": True, "answer": "", "quote": "", "cited_call": ""}
OTHER_QUOTE = "Let me check with the team"


def _rescue_payload():
    """An answer from the SECOND-nearest exchange, which only a wider look can reach."""
    return {"declined": False, "answer": "Tell them you will check with the team today.",
            "quote": OTHER_QUOTE, "cited_call": "other_call.txt"}


def _respond_wide(*payloads, time_left=None, both=False, message=FRAMED,
                  classify=None, thread=()):
    gw = StubGateway(*payloads)
    embed = RecordingEmbedder()
    result = asyncio.run(responding.respond(
        message, _pool(), gw, embed_query=embed, thread=thread,
        classify=classify or _decides("reply_to_client", CLIENT_WORDS),
        wide_retry=True, time_left=time_left, search_from_conversation=both,
        answer_sees_conversation=both))
    return result, gw, embed


def test_a_no_close_match_is_retried_with_the_wider_shortlist():
    """#49: the exchange that answers is often at rank 5-22, never shown at k=1."""
    result, gw, embed = _respond_wide(DECLINES, _rescue_payload())
    assert result["outcome"] == "answered"
    assert result["citation"]["call_filename"] == "other_call.txt"
    assert result["match"]["rank"] == 2
    assert result["retries"] == ["wide"]
    assert len(gw.calls) == 2
    assert OTHER_QUOTE in gw.calls[1]["prompt"]        # the shortlist reached the model
    assert embed.seen == [CLIENT_WORDS]                # embedded once, not twice


def test_a_good_first_answer_is_never_touched():
    result, gw, _ = _respond_wide(_answer_payload())
    assert result["outcome"] == "answered"
    assert "retries" not in result
    assert len(gw.calls) == 1


def test_an_unverified_quote_is_not_retried():
    """The model DID answer; its quote did not check out. A wider shortlist is not the cure
    for that, so only 'no close match' is retried."""
    bad = {**_answer_payload(), "quote": "words Naren never said"}
    result, gw, _ = _respond_wide(bad, bad)
    assert result["reason"] == "grounding_unverified"
    assert len(gw.calls) == 2                          # the gate's own two attempts only


def test_no_retry_without_fifteen_seconds_left():
    """A clean decline beats a timeout."""
    result, gw, _ = _respond_wide(DECLINES, time_left=lambda: 14.0)
    assert result["reason"] == "no_close_match"
    assert len(gw.calls) == 1


def test_a_retry_that_also_declines_returns_the_first_decline():
    """The decline the CSM sees -- and the nearest match it records -- is today's."""
    result, _, _ = _respond_wide(DECLINES, DECLINES, time_left=lambda: 20.0)
    assert result["reason"] == "no_close_match"
    assert result["match"]["rank"] == 1
    assert result["retries"] == ["wide"]


def test_a_retry_that_fails_returns_the_first_decline():
    """A broken retry must not turn a decline into a service error."""
    result, _, _ = _respond_wide(DECLINES, RuntimeError("gateway fell over"))
    assert result["reason"] == "no_close_match"


def test_with_the_switch_off_a_decline_is_not_retried():
    result, gw, _ = _respond(_decides("reply_to_client", CLIENT_WORDS), DECLINES)
    assert result["reason"] == "no_close_match"
    assert len(gw.calls) == 1


def test_the_retry_sees_the_conversation_when_both_switches_are_on():
    result, gw, _ = _respond_wide(
        DECLINES, _rescue_payload(), both=True, thread=ATS_THREAD,
        message="the ats one",
        classify=_rewrites("reply_to_client", "the ats one", ATS_SEARCH))
    assert result["outcome"] == "answered"
    assert ATS_EARLIER in gw.calls[1]["prompt"]
    assert OTHER_QUOTE in gw.calls[1]["prompt"]


# -- a follow-up the carried exchange cannot answer (issue #25, A9) -----------------------

PUSHBACK = "and if they push back and say its our parser not their xml?"
FEED_EARLIER = "client says their feed is dropping jobs after the import"
FEED_THREAD = (_prior(message=FEED_EARLIER),)
FEED_SEARCH = "push back and say its our parser not their xml feed dropping jobs"


def _follow_up(search_query=FEED_SEARCH):
    return _rewrites("follow_up", "", search_query)


def test_a_follow_up_the_carried_exchange_cannot_answer_is_searched():
    """A9 in the live run: declined, because the exchange it carried grounds no answer to
    the pushback. The CSM gave enough to search on; with the switch on it is searched."""
    result, gw, embed = _respond_25(_follow_up(), DECLINES, _answer_payload(),
                                    message=PUSHBACK, thread=FEED_THREAD)
    assert result["outcome"] == "answered"
    assert result["retries"] == ["searched"]
    assert embed.seen == [FEED_SEARCH]
    assert result["intake"]["search_query"] == FEED_SEARCH
    assert FEED_EARLIER in gw.calls[1]["prompt"]       # the search answer sees the thread


def test_a_follow_up_with_no_search_of_its_own_searches_its_own_words():
    _, _, embed = _respond_25(_follow_up(search_query=""), DECLINES, _answer_payload(),
                              message=PUSHBACK, thread=FEED_THREAD)
    assert embed.seen == [PUSHBACK]


def test_a_follow_up_answered_from_the_carried_exchange_searches_nothing():
    result, gw, embed = _respond_25(_follow_up(), _answer_payload(), message=PUSHBACK,
                                    thread=FEED_THREAD)
    assert result["outcome"] == "answered"
    assert embed.seen == [] and len(gw.calls) == 1
    assert "retries" not in result
    assert result["intake"]["search_query"] == ""      # nothing was searched


def test_a_follow_up_is_not_searched_without_fifteen_seconds_left():
    result, gw, embed = _respond_25(_follow_up(), DECLINES, message=PUSHBACK,
                                    thread=FEED_THREAD, time_left=lambda: 10.0)
    assert result["reason"] == "follow_up_ungrounded"
    assert embed.seen == []


def test_with_the_switch_off_a_follow_up_decline_stays_a_decline():
    result, _, embed = _respond_25(_follow_up(), DECLINES, message=PUSHBACK,
                                   thread=FEED_THREAD, search=False, sees=False)
    assert result["reason"] == "follow_up_ungrounded"
    assert embed.seen == []


def test_a_searched_follow_up_that_declines_gets_the_wide_retry_too():
    result, _, _ = _respond_25(_follow_up(), DECLINES, DECLINES, _rescue_payload(),
                               message=PUSHBACK, thread=FEED_THREAD, wide_retry=True)
    assert result["outcome"] == "answered"
    assert result["retries"] == ["searched", "wide"]


# -- the two half-1 switches on their own (issue #25, Q14) -----------------------------

def test_search_from_conversation_alone_leaves_the_answer_prompt_as_it_was():
    _, gw, embed = _respond_25(_rewrites("reply_to_client", "the ats one", ATS_SEARCH),
                               _answer_payload(), sees=False)
    assert embed.seen == [ATS_SEARCH]
    assert ATS_EARLIER not in gw.calls[0]["prompt"]
    assert "CSM's situation: " + ATS_SEARCH in gw.calls[0]["prompt"]


def test_answer_sees_conversation_alone_searches_the_plain_words():
    asked = []
    result, gw, embed = _respond_25(
        _rewrites("reply_to_client", "the ats one", ATS_SEARCH, seen=asked),
        _answer_payload(), search=False)
    assert asked == [False]
    assert embed.seen == ["the ats one"]
    assert ATS_EARLIER in gw.calls[0]["prompt"]
    assert "search_query" not in result["intake"]


def test_a_follow_up_is_not_searched_without_search_from_conversation():
    """A9's fall-through searches on the rewrite, so it belongs to that switch."""
    result, _, embed = _respond_25(_follow_up(), DECLINES, message=PUSHBACK,
                                   thread=FEED_THREAD, search=False)
    assert result["reason"] == "follow_up_ungrounded"
    assert embed.seen == []


# -- the stopwatch on a second generation (issue #25, Q18) -----------------------------

class SlowSecondGateway(StubGateway):
    """Answers the first generation at once and stalls on every later one."""

    async def chat_json(self, prompt, **kwargs):
        if self.calls:
            await asyncio.sleep(5)
        return await super().chat_json(prompt, **kwargs)


def _tight_clock(monkeypatch):
    monkeypatch.setattr(responding, "RETRY_NEEDS_SECONDS", 0.1)
    monkeypatch.setattr(responding, "RETRY_MARGIN_SECONDS", 0.0)
    return lambda: 0.2


def test_a_retry_still_running_at_the_deadline_is_dropped_for_the_first_decline(
        monkeypatch):
    """Live, three questions timed out: the retry started with 15s left and took longer.
    A clean decline beats a timeout, so the retry gets a stopwatch, not just a start rule."""
    gw = SlowSecondGateway(DECLINES, _rescue_payload())
    result = asyncio.run(responding.respond(
        FRAMED, _pool(), gw, embed_query=RecordingEmbedder(),
        classify=_decides("reply_to_client", CLIENT_WORDS), wide_retry=True,
        time_left=_tight_clock(monkeypatch)))
    assert result["reason"] == "no_close_match"
    assert result["retries"] == ["wide"]


def test_a_follow_up_search_still_running_at_the_deadline_returns_the_follow_up_decline(
        monkeypatch):
    gw = SlowSecondGateway(DECLINES, _answer_payload())
    result = asyncio.run(responding.respond(
        PUSHBACK, _pool(), gw, embed_query=RecordingEmbedder(), thread=FEED_THREAD,
        classify=_follow_up(), search_from_conversation=True,
        time_left=_tight_clock(monkeypatch)))
    assert result["reason"] == "follow_up_ungrounded"
    assert result["retries"] == ["searched"]
