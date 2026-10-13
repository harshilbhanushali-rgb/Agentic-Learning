"""ask_naren/composing.py -- Plan -> Gather -> Write.

The gateway and the embedder are stubbed: these tests pin what each stage is handed and what
the gate accepts, not what a model writes. Answer quality is a blind-read question.
"""
import asyncio

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


def test_a_broad_question_is_searched_on_every_angle_in_one_embedding_call():
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
                             _written(SETUP_REPLY, SETUP_CALL))
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


def test_a_rework_searches_nothing_and_grounds_in_what_the_last_answer_rested_on():
    result, gw, embed = _run(_plan("pixel testing", kind="from_conversation"),
                             _written(TEST_REPLY, TEST_CALL),
                             message="turn that into an email for the client", turns=_thread())
    assert embed.calls == []
    writer_prompt = gw.calls[1]["prompt"]
    assert "Nothing new was looked up" in writer_prompt
    assert TEST_REPLY in writer_prompt and CSP_QUOTE in writer_prompt
    assert SETUP_REPLY not in writer_prompt.split("HOW NAREN RUNS")[0]
    assert result["outcome"] == "answered"
    assert result["citation"]["pair_id"] == 2 and "match" not in result
    assert result["intake"]["situation"] == "carried"
    assert result["intake"]["retrieval_query"] == ""


def test_a_rework_after_a_playbook_answer_grounds_in_that_playbook():
    result, _, embed = _run(_plan(kind="from_conversation"), _written(CSP_QUOTE, CSP_CALL),
                            message="make it shorter", turns=_thread(pair_id=None))
    assert embed.calls == []
    assert result["citation"]["call_filename"] == CSP_CALL


def test_a_rework_that_cannot_be_grounded_is_the_follow_up_decline():
    result, _, _ = _run(_plan(kind="from_conversation"), {"declined": True},
                        message="make it shorter", turns=_thread())
    assert result["reason"] == "follow_up_ungrounded" and "match" not in result


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
