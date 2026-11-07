"""ask_naren/composing.py -- Plan -> Gather -> Write.

The gateway and the embedder are stubbed: these tests pin what each stage is handed and what
the gate accepts, not what a model writes. Answer quality is a blind-read question.
"""
import asyncio
import json

import numpy as np

from ask_naren import composing, responding, retrieval, threads

SETUP_CALL = "20240226_wsa_joveo_implementation_kick_off_90930c1e.txt"
TEST_CALL = "20240327_hope_leigh_joveo_standardized_onboarding_30f73cf3.txt"
CSP_CALL = "950cdbfc-b5a7-4888-81e6-88916702c3d6"

SETUP_REPLY = ("Place pixels is essentially where we'll need your help, and then our team "
               "sets up jobs, maps them into our system and tests tracking.")
TEST_REPLY = "So we'll do one test application. We'll confirm that the pixels are firing."
CSP_QUOTE = "But there is a content security policy that's stopping the pixel from firing."

PIXEL = "tracking_pixel_and_tag_manager_implementation"


def _pool():
    pairs = [
        {"pair_id": 1, "trigger_text": "where do we place the pixel",
         "response_text": SETUP_REPLY, "call_filename": SETUP_CALL, "scenario_key": PIXEL},
        {"pair_id": 2, "trigger_text": "how do we know the pixel works",
         "response_text": TEST_REPLY, "call_filename": TEST_CALL, "scenario_key": PIXEL},
        {"pair_id": 3, "trigger_text": "when does the integration go live",
         "response_text": "Let me check with the team and come back to you today.",
         "call_filename": "other_call.txt", "scenario_key": "timeline_question"},
    ]
    return retrieval.RetrievalPool(pairs, np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                                                    [0.0, 0.0, 1.0]]))


PLAYBOOK = {
    "situation_signature": "Client raises tracking pixel requirements.",
    "arc": ["Provide documentation", "Test"],
    "key_moves": [{"name": "Provide documentation", "criterion": "Send a placement doc.",
                   "evidence": [{"call": SETUP_CALL, "quote": SETUP_REPLY}]}],
    "signature_language": [{"call": TEST_CALL, "quote": TEST_REPLY, "phrase": "test"}],
    "pitfalls_and_variants": [{"text": "Not checking Content Security Policy headers.",
                               "evidence": [{"call": CSP_CALL, "quote": CSP_QUOTE}]}],
}


def _playbook_for(key):
    return {"playbook": PLAYBOOK} if key == PIXEL else None


class Embedder:
    """'test' or 'verify' points at the testing exchange, anything else at the setup one."""

    def __init__(self):
        self.calls = []

    async def __call__(self, texts):
        self.calls.append(list(texts))
        return np.array([[0.1, 1.0, 0.0] if ("test" in t or "verify" in t)
                         else [1.0, 0.1, 0.0] for t in texts])


class StubGateway:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    async def chat_json(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if not self.payloads:
            raise AssertionError("more generations than the path allows")
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload, {}


def _plan(*searches, kind="situation", question="", reply=""):
    return {"kind": kind, "searches": list(searches), "question": question, "reply": reply}


def _written(quote, call, used=()):
    return {"declined": False, "answer": "Here is how Naren runs it.", "quote": quote,
            "cited_call": call, "used_calls": list(used)}


def _run(*payloads, message="everything on pixel placement", turns=(), time_left=None,
         scenarios_for=None):
    gw, embed = StubGateway(*payloads), Embedder()
    result = asyncio.run(composing.respond(
        message, turns, _pool(), gw, embed_query=embed, label_for=lambda call: f"L:{call}",
        playbook_for=_playbook_for, scenarios_for=scenarios_for, time_left=time_left))
    return result, gw, embed


def test_a_broad_question_is_searched_on_every_angle_in_one_embedding_call(monkeypatch):
    monkeypatch.setattr(composing, "SEARCH_CSM_WORDS", False)   # the planner's angles alone
    result, gw, embed = _run(_plan("where to place the pixel", "how to test the pixel"),
                             _written(TEST_REPLY, TEST_CALL))
    assert embed.calls == [["where to place the pixel", "how to test the pixel"]]
    writer_prompt = gw.calls[1]["prompt"]
    assert SETUP_REPLY in writer_prompt and TEST_REPLY in writer_prompt
    assert result["outcome"] == "answered"
    assert result["intake"]["retrieval_query"] == "where to place the pixel | how to test the pixel"


def test_the_writer_sees_the_whole_playbook_including_phrasing_and_pitfalls():
    _result, gw, _ = _run(_plan("where to place the pixel"), _written(SETUP_REPLY, SETUP_CALL))
    writer_prompt = gw.calls[1]["prompt"]
    assert "Provide documentation" in writer_prompt
    assert "Not checking Content Security Policy headers." in writer_prompt
    assert CSP_QUOTE in writer_prompt


def test_an_exchange_quote_cites_its_pair_and_reports_its_match():
    result, _, _ = _run(_plan("how to test the pixel"), _written(TEST_REPLY, TEST_CALL))
    assert result["citation"]["pair_id"] == 2
    assert result["match"]["rank"] >= 1


def test_a_pitfall_quote_verifies_and_cites_its_call_with_no_pair():
    result, _, _ = _run(_plan("where to place the pixel"), _written(CSP_QUOTE, CSP_CALL))
    assert result["outcome"] == "answered"
    assert result["citation"] == {"label": f"L:{CSP_CALL}", "call_filename": CSP_CALL,
                                  "scenario_key": PIXEL}
    assert "match" not in result


def test_a_quote_that_is_not_verbatim_twice_declines_without_a_third_generation():
    made_up = "Always tell the client the pixel takes five minutes."
    result, gw, _ = _run(_plan("where to place the pixel"), _written(made_up, SETUP_CALL),
                         _written(made_up, SETUP_CALL))
    assert result["outcome"] == "declined"
    assert result["reason"] == "grounding_unverified"
    assert len(gw.calls) == 3


def test_no_retry_when_the_deadline_cannot_fit_one():
    made_up = "Always tell the client the pixel takes five minutes."
    result, gw, _ = _run(_plan("where to place the pixel"), _written(made_up, SETUP_CALL),
                         time_left=lambda: 5.0)
    assert result["reason"] == "grounding_unverified"
    assert len(gw.calls) == 2


def test_drawn_from_keeps_only_calls_the_writer_was_shown():
    result, _, _ = _run(_plan("where to place the pixel"),
                        _written(SETUP_REPLY, SETUP_CALL,
                                 used=[SETUP_CALL, CSP_CALL, "invented_call.txt"]))
    assert [c["call_filename"] for c in result["drawn_from"]] == [SETUP_CALL, CSP_CALL]


def test_a_failed_plan_searches_the_message_as_written():
    result, _, embed = _run(RuntimeError("gateway down"), _written(SETUP_REPLY, SETUP_CALL),
                            message="pixel placement please")
    assert embed.calls == [["pixel placement please"]]
    assert result["outcome"] == "answered"


def test_a_plan_with_an_unknown_kind_falls_back_to_the_message():
    _result, _, embed = _run({"kind": "playbook", "searches": ["x"], "question": ""},
                             _written(SETUP_REPLY, SETUP_CALL), message="pixel placement")
    assert embed.calls == [["pixel placement"]]


def test_duplicate_searches_are_embedded_once():
    _result, _, embed = _run(_plan("Pixel placement", "pixel placement", "pixel  placement"),
                             _written(SETUP_REPLY, SETUP_CALL), message="PIXEL PLACEMENT")
    assert embed.calls == [["Pixel placement"]]


def test_a_topics_question_is_rendered_with_no_search_and_no_writer():
    scenarios = [{"scenario_key": PIXEL, "business_description": "Pixels.",
                  "primary_topic": "", "support_calls": 99}]
    result, gw, embed = _run(_plan(kind="topics"), scenarios_for=lambda: scenarios)
    assert result["kind"] == "discovery"
    assert embed.calls == [] and len(gw.calls) == 1


def test_a_clarify_is_asked_without_searching():
    result, _, embed = _run(_plan(kind="clarify", question="Which client is this?"))
    assert result == {**result, "outcome": "clarify", "question": "Which client is this?"}
    assert embed.calls == []


def test_out_of_scope_declines_without_searching():
    result, _, embed = _run(_plan(kind="out_of_scope"))
    assert result["reason"] == "out_of_scope" and "match" not in result
    assert embed.calls == []


def test_respond_with_compose_skips_the_intent_router():
    async def classify(*_a, **_k):
        raise AssertionError("intake must not run when composing")
    gw = StubGateway(_plan("where to place the pixel"), _written(SETUP_REPLY, SETUP_CALL))
    result = asyncio.run(responding.respond(
        "pixel placement", _pool(), gw, embed_query=Embedder(), classify=classify,
        playbook_for=_playbook_for, compose=True))
    assert result["outcome"] == "answered"
    assert result["intake"]["intent"] == composing.INTENT


# -- from_conversation: the plan chooses not to search --------------------------------------

def _thread(pair_id=2, scenario_key=PIXEL):
    return threads.parse([{"message": "how do we know the pixel works", "outcome": "answered",
                           "reply": "Naren runs one test application to confirm it fires.",
                           "scenario_key": scenario_key, "pair_id": pair_id,
                           "call_filename": TEST_CALL}])


def test_a_rework_shows_what_the_last_answer_rested_on_and_also_searches_the_backup_searches():
    result, gw, embed = _run(_plan("where to place the pixel", kind="from_conversation"),
                             _written(SETUP_REPLY, SETUP_CALL),
                             message="turn that into an email for the client", turns=_thread())
    assert embed.calls == [["where to place the pixel"]]     # backups only: not the message
    writer_prompt = gw.calls[1]["prompt"]
    assert "rework what you have already told them" in writer_prompt
    assert "Nothing new was looked up" not in writer_prompt
    carried, looked_up = writer_prompt.split("What was looked up for it:")
    assert TEST_REPLY in carried and SETUP_REPLY in looked_up
    assert result["outcome"] == "answered"
    assert result["citation"]["pair_id"] == 1 and result["match"]["rank"] == 1
    assert result["intake"]["situation"] == "carried"
    assert result["intake"]["retrieval_query"] == "where to place the pixel"


def test_a_rework_quoting_the_carried_exchange_cites_it():
    result, gw, _ = _run(_plan("where to place the pixel", kind="from_conversation"),
                         _written(TEST_REPLY, TEST_CALL),
                         message="make it shorter", turns=_thread())
    assert result["citation"]["pair_id"] == 2
    assert gw.calls[1]["prompt"].count(TEST_REPLY) == 2      # the exchange + playbook phrasing


def test_a_carried_exchange_the_search_finds_again_is_shown_once():
    _result, gw, _ = _run(_plan("how to test the pixel", kind="from_conversation"),
                          _written(TEST_REPLY, TEST_CALL),
                          message="make it shorter", turns=_thread())
    exchanges = gw.calls[1]["prompt"].split("HOW NAREN RUNS")[0]
    assert exchanges.count(TEST_REPLY) == 1


def test_a_rework_with_no_backup_searches_searches_the_message():
    _result, _, embed = _run(_plan(kind="from_conversation"), _written(TEST_REPLY, TEST_CALL),
                             message="make it about pixel placement", turns=_thread())
    assert embed.calls == [["make it about pixel placement"]]


def test_a_rework_after_a_playbook_answer_grounds_in_that_playbook():
    result, _, _ = _run(_plan("where to place the pixel", kind="from_conversation"),
                        _written(CSP_QUOTE, CSP_CALL),
                        message="make it shorter", turns=_thread(pair_id=None))
    assert result["citation"]["call_filename"] == CSP_CALL


def test_a_declined_rework_is_a_searched_decline_with_no_second_write():
    result, gw, _ = _run(_plan("where to place the pixel", kind="from_conversation"),
                         {"declined": True}, message="make it shorter", turns=_thread())
    assert len(gw.calls) == 2
    assert result["reason"] == "no_close_match" and "match" in result


def test_the_planner_is_told_an_earlier_answer_covers_only_what_it_was_asked():
    prompt = composing.build_plan_prompt("what do I need to do to get it set up", _thread())
    assert "covers only what it was asked" in prompt


def test_a_rework_with_nothing_to_rework_searches_the_backup_searches():
    result, _, embed = _run(_plan("how to test the pixel", kind="from_conversation"),
                            _written(TEST_REPLY, TEST_CALL), message="make it shorter")
    assert embed.calls == [["how to test the pixel"]]
    assert result["intake"]["plan_kind"] == "situation"


def test_a_rework_with_nothing_to_rework_and_no_backup_searches_the_message():
    _result, _, embed = _run(_plan(kind="from_conversation"),
                             _written(SETUP_REPLY, SETUP_CALL), message="pixel placement")
    assert embed.calls == [["pixel placement"]]


# -- conversation: talk with Ask Naren itself ------------------------------------------------

def test_small_talk_gets_the_planners_reply_with_no_search_and_no_writer():
    result, gw, embed = _run(_plan(kind="conversation", reply="Doing well! What's the client situation?"),
                             message="how are you")
    assert embed.calls == [] and len(gw.calls) == 1
    assert result["outcome"] == "clarify" and result["conversational"] is True
    assert result["question"] == "Doing well! What's the client situation?"
    assert "answer" not in result and "quote" not in result and "citation" not in result


def test_small_talk_with_no_reply_written_gets_the_fallback():
    result, _, _ = _run(_plan(kind="conversation"), message="hey")
    assert result["question"] == composing.CONVERSATION_FALLBACK


# -- call names: `.txt` on one side only (2026-11-06) ------------------------------------------

def test_a_playbook_quote_cited_with_txt_still_verifies():
    # Playbook evidence records CSP_CALL without the extension; the writer added it.
    assert not CSP_CALL.endswith(".txt")
    result, _, _ = _run(_plan("where to place the pixel"),
                        _written(CSP_QUOTE, CSP_CALL + ".txt", used=[CSP_CALL + ".txt"]))
    assert result["outcome"] == "answered"
    assert result["citation"]["call_filename"] == CSP_CALL
    assert [d["call_filename"] for d in result["drawn_from"]] == [CSP_CALL]


def test_a_quote_that_is_not_in_the_cited_call_still_fails_with_txt_ignored():
    result, _, _ = _run(_plan("where to place the pixel"),
                        _written("a sentence Naren never said", CSP_CALL + ".txt"),
                        _written("a sentence Naren never said", CSP_CALL + ".txt"))
    assert result["outcome"] == "declined" and result["reason"] == "grounding_unverified"


# -- a failed grounding check is logged with its cause (2026-11-06) --------------------------

def test_a_failed_gate_logs_why_without_the_full_quote(capsys):
    long_quote = "a sentence Naren never said " * 10
    _run(_plan("where to place the pixel"), _written(long_quote, SETUP_CALL),
         _written(SETUP_REPLY, SETUP_CALL))
    lines = [l for l in capsys.readouterr().err.splitlines() if "grounding_failed" in l]
    assert len(lines) == 1
    record = json.loads(lines[0].split("[ask-naren] ", 1)[1])
    assert record["reason"] == "quote_not_verbatim" and record["cited_was_shown"] is True
    assert record["quote_verbatim_in"] is None and len(record["quote_start"]) <= 80


def test_a_real_quote_cited_to_the_wrong_call_answers_cited_where_it_is_and_logs_it(capsys):
    result, gw, _ = _run(_plan("where to place the pixel"),
                         _written(TEST_REPLY, SETUP_CALL))
    assert result["outcome"] == "answered" and len(gw.calls) == 2
    assert result["citation"]["call_filename"] == TEST_CALL
    assert result["citation"]["pair_id"] == 2
    lines = [l for l in capsys.readouterr().err.splitlines() if "citation_corrected" in l]
    assert len(lines) == 1
    record = json.loads(lines[0].split("[ask-naren] ", 1)[1])
    assert record["cited_call"] == SETUP_CALL and record["actual_call"] == TEST_CALL


def test_a_playbook_call_named_with_txt_is_not_logged_as_a_correction(capsys):
    result, _, _ = _run(_plan("where to place the pixel"), _written(CSP_QUOTE, CSP_CALL + ".txt"))
    assert result["citation"]["call_filename"] == CSP_CALL
    assert "citation_corrected" not in capsys.readouterr().err


# -- the CSM's own words as an extra search (2026-11-07; ON by default) -----------------------

def test_the_csms_words_are_searched_by_default():
    assert composing.SEARCH_CSM_WORDS is True


def test_a_situation_also_searches_the_message_as_written_in_the_same_embedding_call(monkeypatch):
    monkeypatch.setattr(composing, "SEARCH_CSM_WORDS", True)
    result, _, embed = _run(_plan("where to place the pixel", "how to test the pixel"),
                            _written(TEST_REPLY, TEST_CALL),
                            message="  What does the client need to do for tracking?  ")
    assert embed.calls == [["where to place the pixel", "how to test the pixel",
                            "What does the client need to do for tracking?"]]
    assert result["intake"]["retrieval_query"].endswith(
        "| What does the client need to do for tracking?")


def test_the_message_is_not_searched_twice_when_the_planner_already_searched_it(monkeypatch):
    monkeypatch.setattr(composing, "SEARCH_CSM_WORDS", True)
    _result, _, embed = _run(_plan("Pixel placement"), _written(SETUP_REPLY, SETUP_CALL),
                             message="pixel  placement")
    assert embed.calls == [["Pixel placement"]]


def test_a_long_message_is_searched_cut_to_the_search_length(monkeypatch):
    monkeypatch.setattr(composing, "SEARCH_CSM_WORDS", True)
    message = "pixel " * 100
    _result, _, embed = _run(_plan("where to place the pixel"),
                             _written(SETUP_REPLY, SETUP_CALL), message=message)
    assert len(embed.calls[0]) == 2
    assert len(embed.calls[0][1]) <= composing.MAX_SEARCH_CHARS


# -- the writer's principles (2026-11-07) -----------------------------------------------------

def test_the_writer_builds_on_naren_answering_the_same_question_and_keeps_his_reasons():
    prompt = composing.build_write_prompt("what is a title expansion", (), ["title expansion"],
                                          [], [], lambda c: c)
    assert "Start from the exchanges where Naren answers this same question" in prompt
    assert "the reasons he gives for why it matters to the client" in prompt
    assert "Answer in the form the question asks for." in prompt
    assert "go with the most recent call" in prompt
    for removed in ("experienced colleague", "walk them through it: how it usually goes",
                    "Use everything above that is relevant and combine it",
                    "Talk about what Naren does and says"):
        assert removed not in prompt


def test_a_failed_plan_on_a_multi_line_message_searches_it_once():
    _result, _, embed = _run(RuntimeError("gateway down"), _written(SETUP_REPLY, SETUP_CALL),
                             message="pixel placement\n\nplease help")
    assert embed.calls == [["pixel placement please help"]]


# -- a broken-JSON reply from the writer is retried once (2026-11-07) -------------------------

from shared.gateway import GatewayError, GatewayReplyNotJSON  # noqa: E402
import pytest  # noqa: E402


def test_a_broken_json_reply_is_retried_once_and_the_retry_answers():
    result, gw, _ = _run(_plan("where to place the pixel"),
                         GatewayReplyNotJSON("non-JSON from gemini"),
                         _written(SETUP_REPLY, SETUP_CALL))
    assert result["outcome"] == "answered" and len(gw.calls) == 3


def test_broken_json_twice_still_raises_as_a_service_fault():
    with pytest.raises(GatewayReplyNotJSON):
        _run(_plan("where to place the pixel"), GatewayReplyNotJSON("bad"),
             GatewayReplyNotJSON("bad again"))


def test_broken_json_is_not_retried_when_the_deadline_cannot_fit_one():
    with pytest.raises(GatewayReplyNotJSON):
        _run(_plan("where to place the pixel"), GatewayReplyNotJSON("bad"),
             _written(SETUP_REPLY, SETUP_CALL), time_left=lambda: 5.0)


def test_other_gateway_faults_are_not_retried():
    with pytest.raises(GatewayError):
        _run(_plan("where to place the pixel"), GatewayError("HTTP 500"),
             _written(SETUP_REPLY, SETUP_CALL))


def test_the_writer_is_asked_for_a_short_quote_and_not_for_reasons_from_other_situations():
    # The "reasons from anywhere" line was measured and removed 2026-11-07: it did not fix its
    # target and the held-out read fell with it in. Paragraph-long quotes were the main grounding
    # failure (99.8%-verbatim misses), hence the one-or-two-sentence quote.
    prompt = composing.build_write_prompt("how can Joveo help me hire nurses", (), ["x"], [], [],
                                          lambda c: c)
    assert "even an exchange about a different situation" not in prompt
    assert "one or two sentences" in prompt


def test_the_csms_words_are_not_searched_when_switched_off(monkeypatch):
    monkeypatch.setattr(composing, "SEARCH_CSM_WORDS", False)
    _result, _, embed = _run(_plan("where to place the pixel"), _written(SETUP_REPLY, SETUP_CALL),
                             message="What does the client need to do for tracking?")
    assert embed.calls == [["where to place the pixel"]]


# -- the "why" search (2026-11-07; switched OFF by default until measured) ----------------------
#
# A bullet in the planner's list was tried first and skipped by the planner (1 of 2 golden runs
# wrote any why search for the nurses question, and that one named the topic, not the reason).
# A field of its own is considered on every plan.

def test_the_plan_has_no_why_search_when_switched_off():
    assert composing.SEARCH_FOR_THE_WHY is False
    assert "why_search" not in composing.plan_schema()["schema"]["properties"]
    assert "why_search" not in composing.build_plan_prompt("how do I hire nurses faster", ())


def test_when_switched_on_the_planner_writes_a_why_search_that_is_searched(monkeypatch):
    monkeypatch.setattr(composing, "SEARCH_FOR_THE_WHY", True)
    monkeypatch.setattr(composing, "SEARCH_CSM_WORDS", False)
    assert "why_search" in composing.plan_schema()["schema"]["required"]
    assert "why_search" in composing.build_plan_prompt("how do I hire nurses faster", ())
    plan = {**_plan("where to place the pixel"), "why_search": "how testing the pixel proves it works"}
    result, _, embed = _run(plan, _written(TEST_REPLY, TEST_CALL))
    assert embed.calls == [["where to place the pixel", "how testing the pixel proves it works"]]
    assert result["intake"]["retrieval_query"].endswith("| how testing the pixel proves it works")


def test_an_empty_why_search_adds_nothing(monkeypatch):
    monkeypatch.setattr(composing, "SEARCH_FOR_THE_WHY", True)
    monkeypatch.setattr(composing, "SEARCH_CSM_WORDS", False)
    _result, _, embed = _run({**_plan("where to place the pixel"), "why_search": "  "},
                             _written(SETUP_REPLY, SETUP_CALL))
    assert embed.calls == [["where to place the pixel"]]


# -- the stage trace never carries what the CSM typed (2026-11-08) -----------------------------

def test_the_plan_trace_logs_how_many_searches_not_their_text(capsys):
    # A failed plan falls back to searching the message as written; before this fix the trace
    # wrote that search -- the CSM's message, client names and all -- to the server log.
    secret = "Client Acme Hospital says our CPA doubled, contact jane@acme.com"
    _run({"kind": "situation", "searches": [], "question": "", "reply": ""},
         _written(SETUP_REPLY, SETUP_CALL), message=secret)
    err = capsys.readouterr().err
    assert "Acme" not in err and "jane@acme.com" not in err
    plan_line = next(l for l in err.splitlines() if '"event": "plan"' in l)
    assert json.loads(plan_line.split("[ask-naren] ", 1)[1])["searches"] == 1


# -- the writer states the why (2026-11-08; switched OFF by default until measured) -------------
#
# The search already finds Naren's reasons for "hire nurses faster" (attached 3/3 in the bug hunt);
# the writer dropped them. Asking for the reason as a key of its own, before the answer, makes it
# considered on every answer instead of only when the same-question exchanges carry it.

def _pair(n, scenario_key="craigslist_and_flat_fee_channel_evaluation"):
    return {"pair_id": n, "trigger_text": f"client turn {n}", "response_text": f"naren reply {n}",
            "call_filename": f"call_{n}.txt", "scenario_key": scenario_key}


def test_the_writer_is_not_asked_for_a_why_when_switched_off():
    assert composing.WRITER_STATES_THE_WHY is False
    prompt = composing.build_write_prompt("how do I hire nurses faster", (), ["x"], [_pair(1)], [],
                                          lambda c: c)
    assert '"why"' not in prompt


def test_when_switched_on_the_writer_states_the_why_before_the_answer(monkeypatch):
    monkeypatch.setattr(composing, "WRITER_STATES_THE_WHY", True)
    prompt = composing.build_write_prompt("how do I hire nurses faster", (), ["x"], [_pair(1)], [],
                                          lambda c: c)
    assert '"why"' in prompt
    assert prompt.index('"why"') < prompt.index('"answer"')
    # The why may be empty, and must not loosen the rule that everything comes from the material.
    assert "Everything you state must come from the material above." in prompt


def test_when_switched_on_an_exchange_carries_no_situation_label_and_order_is_not_a_ranking(
        monkeypatch):
    pairs = [_pair(1), _pair(2, "client_interview_tracking")]
    off = composing.build_write_prompt("how do I hire nurses faster", (), ["a", "b"], pairs, [],
                                       lambda c: c)
    assert "situation: craigslist and flat fee channel evaluation" in off   # X stays as measured
    monkeypatch.setattr(composing, "WRITER_STATES_THE_WHY", True)
    on = composing.build_write_prompt("how do I hire nurses faster", (), ["a", "b"], pairs, [],
                                      lambda c: c)
    assert "craigslist" not in on and "client interview tracking" not in on
    assert "closest first" not in on
    assert "naren reply 1" in on and "naren reply 2" in on and "(call: call_2.txt" in on


def test_when_switched_on_the_answer_states_the_why_and_move_evidence_may_be_quoted(monkeypatch):
    off = composing.build_write_prompt("how do I hire nurses faster", (), ["x"], [_pair(1)], [],
                                       lambda c: c)
    monkeypatch.setattr(composing, "WRITER_STATES_THE_WHY", True)
    on = composing.build_write_prompt("how do I hire nurses faster", (), ["x"], [_pair(1)], [],
                                      lambda c: c)
    assert "the answer states it" in on and "the answer states it" not in off
    # Evidence is printed under "Move:" headers; only the move's own description is a summary.
    assert "never from a move's own description" in on
    assert "never from a move, a 'when it comes up'" in off


def test_a_written_why_leaves_the_gate_and_the_response_contract_alone_and_logs_only_its_length(
        monkeypatch, capsys):
    monkeypatch.setattr(composing, "WRITER_STATES_THE_WHY", True)
    why = "Secret Hospital Inc wants interviews, so we optimize towards them"
    result, gw, _ = _run(_plan("where to place the pixel"),
                         {**_written(SETUP_REPLY, SETUP_CALL), "why": why})
    assert result["outcome"] == "answered" and result["quote"] == SETUP_REPLY
    assert "why" not in result                      # frontend AskNarenResponse mirrors this exactly
    err = capsys.readouterr().err
    assert "Secret Hospital" not in err
    write_line = next(l for l in err.splitlines() if '"event": "write"' in l)
    assert json.loads(write_line.split("[ask-naren] ", 1)[1])["why_chars"] == len(why)
