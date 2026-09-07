"""ask_naren/responding.py -- the one call the HTTP layer makes, and where an intake
decision becomes a response.

`classify` is INJECTED in every test here, the same way `embed_query` and `label_for` are
elsewhere. Two reasons, both deliberate: a dispatch test must not pay for a generation, and
routing accuracy is a separate question measured against labelled messages
(`ask-naren/audit/measure_intake_accuracy.py`) rather than smuggled into behaviour tests.
"""
import numpy as np
import pytest

from ask_naren import intake, responding, retrieval

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


def _decides(intent, retrieval_query="", question=""):
    """A stand-in intake that returns a fixed decision without calling a gateway."""
    def _classify(message, gateway):
        return intake.IntakeDecision(intent=intent, retrieval_query=retrieval_query,
                                     question=question), {}
    return _classify


def _respond(classify, *payloads, message=FRAMED, embedder=None):
    gw = StubGateway(*payloads)
    embed = embedder or RecordingEmbedder()
    result = responding.respond(message, _pool(), gw, embed_query=embed, classify=classify)
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
    def _boom(message, gateway):
        raise RuntimeError("intake exploded")

    result, _, _ = _respond(_boom, _answer_payload())
    assert result["intake"]["retrieval_query"] == FRAMED


def test_a_post_retrieval_reason_cannot_be_declined_as_if_nothing_was_searched():
    """Guards the calibration invariant from the other side: every decline that DID retrieve
    must report how close the match it turned down was."""
    from ask_naren import answering
    with pytest.raises(ValueError):
        answering.decline_before_retrieval(answering.NO_CLOSE_MATCH)


def test_an_empty_message_is_refused():
    with pytest.raises(ValueError):
        responding.respond("   ", _pool(), StubGateway(),
                           embed_query=RecordingEmbedder(),
                           classify=_decides("reply_to_client", "x"))


def test_intake_failing_completely_still_answers_the_message_as_written():
    """Intake is an optimisation on a path that already worked. A classify that raises must
    degrade to the pre-intake behaviour rather than fail the request."""
    def _boom(message, gateway):
        raise RuntimeError("intake exploded")

    result, _, embed = _respond(_boom, _answer_payload())
    assert result["outcome"] == "answered"
    assert embed.seen == [FRAMED]
