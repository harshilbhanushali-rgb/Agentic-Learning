"""ask_naren/answering.py -- situation in, grounded answer or decline out.

Every generation here comes from a stubbed gateway: no API calls, no live embeddings. What
is being tested is the EXTERNAL contract (what a caller receives), not prompt strings or
internal call counts -- except where the contract itself is about a second attempt, which
has no other observable.
"""
import numpy as np
import pytest

from ask_naren import answering, retrieval

RESPONSE = ("Yeah, so what I usually do there is pull the last 90 days of spend and show "
            "them cost per hire against their own baseline, not against our benchmark.")
CALL = "20230503_uber_joveo_weekly_performance_review_d18cc178.txt"
GOOD_QUOTE = "show them cost per hire against their own baseline"


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


def _embed_query(texts):
    """Stands in for the live embedder: always lands on the first pool pair."""
    return np.array([[1.0, 0.05]] * len(texts))


class StubGateway:
    """Returns the queued payloads in order. Raises if asked for one more generation than
    the test provided -- that is how the retry contract is bounded without counting calls."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    def chat_json(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if not self.payloads:
            raise AssertionError("the service asked for more generations than the contract "
                                 "allows")
        return self.payloads.pop(0), {"served_model": kwargs.get("model")}


def _payload(answer="Pull their last 90 days and reframe on their own baseline.",
             quote=GOOD_QUOTE, cited_call=CALL, declined=False):
    return {"declined": declined, "answer": answer, "quote": quote,
            "cited_call": cited_call}


def _ask(*payloads, situation="client says our cost per hire is way too high"):
    gw = StubGateway(*payloads)
    result = answering.answer_situation(situation, _pool(), gw, embed_query=_embed_query)
    return result, gw


# -- the answered path -----------------------------------------------------------------

def test_a_grounded_generation_is_returned_with_its_citation():
    result, _ = _ask(_payload())
    assert result["outcome"] == "answered"
    assert result["answer"] == "Pull their last 90 days and reframe on their own baseline."
    assert result["quote"] == GOOD_QUOTE
    assert result["citation"]["call_filename"] == CALL
    assert result["citation"]["pair_id"] == 11
    assert result["citation"]["scenario_key"] == "performance_pushback"


def test_the_citation_carries_a_display_label_a_reader_could_use():
    """Raw filename for now -- issue #4 resolves it to an account and a date. The KEY has
    to exist from the start so resolving it later is not a shape change for every caller."""
    result, _ = _ask(_payload())
    assert result["citation"]["label"]


def test_an_answer_reports_how_close_the_match_actually_was():
    result, _ = _ask(_payload())
    assert result["match"]["cosine"] == pytest.approx(0.9988, abs=1e-3)
    assert result["match"]["scenario_key"] == "performance_pushback"


# -- the decline paths -----------------------------------------------------------------

def test_a_model_decline_is_reported_as_no_close_match():
    result, _ = _ask(_payload(declined=True, answer="", quote="", cited_call=""))
    assert result["outcome"] == "declined"
    assert result["reason"] == "no_close_match"
    assert result["message"]


def test_a_decline_carries_no_answer_or_quote_for_a_caller_to_render():
    result, _ = _ask(_payload(declined=True, answer="", quote="", cited_call=""))
    assert "answer" not in result and "quote" not in result


def test_no_response_carries_the_old_declined_boolean():
    """The response contract discriminates on `outcome`, not on a boolean.

    Two discriminators for one decision is how the answered and declined paths eventually
    disagree about which one a response is, so the boolean is GONE rather than kept
    alongside. Asserted on both outcomes because a leftover on either is the bug.
    """
    answered, _ = _ask(_payload())
    declined, _ = _ask(_payload(declined=True, answer="", quote="", cited_call=""))
    assert "declined" not in answered
    assert "declined" not in declined


def test_the_models_declined_key_is_not_the_responses_outcome():
    """`declined` still exists -- in the MODEL's JSON, which build_prompt asks for and the
    grounding gate reads. That key is frozen by ADR 0001 and is a different thing from the
    response's `outcome`. This pins that renaming one did not rename the other."""
    _, gw = _ask(_payload(declined=True, answer="", quote="", cited_call=""))
    assert '"declined": boolean' in gw.calls[0]["prompt"]


def test_a_clarify_carries_no_field_an_ungrounded_answer_could_ride_in():
    """Nothing produces a clarify yet (issue #14 does). The SHAPE is defined here because
    the grounding guarantee is structural: a clarify has no answer, quote or citation field
    at all, so there is nowhere for unverified text to reach a CSM even by mistake."""
    result = answering.clarify("What did the client actually say?")
    assert result["outcome"] == "clarify"
    assert result["question"] == "What did the client actually say?"
    assert "answer" not in result
    assert "quote" not in result
    assert "citation" not in result


def test_a_decline_still_reports_the_retrieval_cosine():
    """The spec defers decline-rate calibration to real usage data. That is only possible
    if a decline records how close the match it declined actually was."""
    result, _ = _ask(_payload(declined=True, answer="", quote="", cited_call=""))
    assert result["match"]["cosine"] == pytest.approx(0.9988, abs=1e-3)


# -- the grounding gate, live -----------------------------------------------------------

def test_an_unverifiable_generation_is_retried_once_and_the_retry_can_succeed():
    result, _ = _ask(_payload(quote="we guarantee a 40% lift by Friday"), _payload())
    assert result["outcome"] == "answered"
    assert result["quote"] == GOOD_QUOTE


def test_two_unverifiable_generations_decline_rather_than_answer():
    """The bounded-retry contract: the stub raises on a third generation, so reaching a
    decline proves the service stopped at one retry instead of looping."""
    fabricated = _payload(answer="Promise them a 40% lift.", quote="a 40% lift by Friday")
    result, _ = _ask(fabricated, fabricated)
    assert result["outcome"] == "declined"
    assert result["reason"] == "grounding_unverified"


def test_an_unverified_answer_is_never_forwarded_in_any_field():
    """The whole point of the gate: the ungrounded text must not reach the caller at all,
    not even as a note or a fallback."""
    fabricated = _payload(answer="Promise them a 40% lift.", quote="a 40% lift by Friday")
    result, _ = _ask(fabricated, fabricated)
    assert "40% lift" not in repr(result)


def test_a_generation_citing_the_wrong_call_is_refused():
    wrong = _payload(cited_call="a_call_never_retrieved.txt")
    result, _ = _ask(wrong, wrong)
    assert result["outcome"] == "declined"
    assert result["reason"] == "grounding_unverified"


# -- gateway discipline -----------------------------------------------------------------

def test_generation_never_serves_a_cached_completion():
    """shared/gateway.py caches chat completions BY DEFAULT, measured byte-identical across
    calls. Two CSMs asking similarly-worded questions would receive an echo of each other's
    answer, and nothing in the response would show it. The outgoing request is the only
    place this is observable, so it is asserted there."""
    _, gw = _ask(_payload())
    assert gw.calls and all(c["no_cache"] is True for c in gw.calls)


def test_generation_asks_for_the_licensed_model_and_reasoning_effort():
    """gemini-3.6-flash at reasoning_effort=medium is what the eval behind ADR 0001 ran on,
    and Brain measures the MODEL as the lever on this corpus (3.5-flash-lite follows
    grounding instructions 11% of the time vs 3.6-flash at 77%)."""
    _, gw = _ask(_payload())
    assert gw.calls[0]["model"] == "gemini-3.6-flash"
    assert gw.calls[0]["reasoning_effort"] == "medium"


# -- input handling ---------------------------------------------------------------------

def test_a_blank_situation_is_refused_without_spending_a_generation():
    gw = StubGateway()
    with pytest.raises(ValueError):
        answering.answer_situation("   ", _pool(), gw, embed_query=_embed_query)
    assert gw.calls == []


# -- the candidate shortlist (issue #8) -------------------------------------------------

SECOND_CALL = "other_call.txt"
SECOND_QUOTE = "come back to you today"


def _ask_k(*payloads, k, situation="client says our cost per hire is way too high"):
    gw = StubGateway(*payloads)
    result = answering.answer_situation(situation, _pool(), gw,
                                        embed_query=_embed_query, k=k)
    return result, gw


def test_an_answer_grounded_in_the_second_candidate_cites_the_second_candidate():
    """#8's premise is that the useful moment is often not rank 1. If the response still
    described rank 1, a CSM would be handed an answer from one call under another call's
    citation -- an ADR 0002 violation that no gate metric would show, since the gate itself
    passed."""
    result, _ = _ask_k(_payload(answer="Tell them you will confirm today.",
                                quote=SECOND_QUOTE, cited_call=SECOND_CALL), k=2)
    assert result["outcome"] == "answered"
    assert result["citation"]["pair_id"] == 22
    assert result["citation"]["scenario_key"] == "timeline_question"
    assert result["match"]["scenario_key"] == "timeline_question"
    assert result["match"]["rank"] == 2


def test_the_rank_1_arm_still_sends_the_single_candidate_prompt():
    """Routing, and it is what keeps issue #8's A/B honest: the k=1 arm is compared against
    the already-paid-for generations in artifacts/answer_audit_raw.json, which came from
    build_prompt. Had widening k also routed k=1 through the shortlist prompt, both arms
    would have moved and there would be nothing left to compare against."""
    _, gw = _ask(_payload())
    assert gw.calls[0]["prompt"] == answering.build_prompt(
        "client says our cost per hire is way too high", _pool().pairs[0])


def test_every_candidate_in_the_shortlist_reaches_the_prompt_with_its_own_identifier():
    """Both replies AND both call identifiers: a candidate shown without its identifier
    cannot be cited, so the model could only ever ground in the ones that carry one."""
    _, gw = _ask_k(_payload(quote=SECOND_QUOTE, cited_call=SECOND_CALL), k=2)
    prompt = gw.calls[0]["prompt"]
    assert RESPONSE in prompt and "Let me check with the team" in prompt
    assert CALL in prompt and SECOND_CALL in prompt


# -- readable citations (issue #4) -------------------------------------------------------

def test_the_citation_label_is_resolved_to_an_account_and_a_date():
    """The raw filename stays available beside it -- an engineer tracing a bad answer needs
    the exact source rows, and a CSM needs to recognise the call."""
    result, _ = _ask(_payload())
    assert result["citation"]["label"] == "Uber · Weekly Performance Review · 3 May 2023"
    assert result["citation"]["call_filename"] == CALL
    assert result["citation"]["pair_id"] == 11
    assert result["citation"]["scenario_key"] == "performance_pushback"


# -- the playbook-augmented variant, dark by default (issue #5) --------------------------

MOVES = [
    {"name": "Reframe on their own baseline",
     "criterion": "Compare cost per hire against the client's own prior period, not a "
                  "Joveo benchmark."},
    {"name": "Name the window",
     "criterion": "State the exact lookback window used, in days."},
]


def _moves_for(_scenario_key):
    return MOVES


def test_by_default_the_playbook_is_not_in_the_prompt():
    """ADR 0001 measured no lift, so pairs-only is the shipped path. This asserts the
    DEFAULT, which is the half of the switch that actually ships."""
    _, gw = _ask(_payload())
    assert "best-practice moves" not in gw.calls[0]["prompt"]
    assert MOVES[0]["name"] not in gw.calls[0]["prompt"]


def test_with_no_moves_supplied_the_prompt_is_byte_identical_to_pairs_only():
    _, gw = _ask(_payload())
    assert gw.calls[0]["prompt"] == answering.build_prompt(
        "client says our cost per hire is way too high", _pool().pairs[0])


def test_when_switched_on_the_key_moves_reach_the_prompt():
    gw = StubGateway(_payload())
    answering.answer_situation("client says our cost per hire is way too high", _pool(), gw,
                               embed_query=_embed_query, moves_for=_moves_for)
    prompt = gw.calls[0]["prompt"]
    for move in MOVES:
        assert move["name"] in prompt
        assert move["criterion"] in prompt


def test_switched_on_but_the_scenario_has_no_live_playbook_degrades_to_pairs_only():
    """33 of 34 coachable scenarios have a live playbook; contract_and_legal_review has
    none. A missing playbook must not be an error -- it is the ordinary case for that
    scenario, and a CSM asking about it should still get an answer."""
    gw = StubGateway(_payload())
    result = answering.answer_situation(
        "client says our cost per hire is way too high", _pool(), gw,
        embed_query=_embed_query, moves_for=lambda _key: None)
    assert result["outcome"] == "answered"
    assert gw.calls[0]["prompt"] == answering.build_prompt(
        "client says our cost per hire is way too high", _pool().pairs[0])


def test_the_grounding_gate_applies_identically_in_the_playbook_variant():
    """The gate is not relaxed because the prompt got richer -- a fabricated quote still
    declines, and still after exactly one retry."""
    fabricated = _payload(answer="Promise them a 40% lift.", quote="a 40% lift by Friday")
    gw = StubGateway(fabricated, fabricated)
    result = answering.answer_situation(
        "client says our cost per hire is way too high", _pool(), gw,
        embed_query=_embed_query, moves_for=_moves_for)
    assert result["outcome"] == "declined"
    assert result["reason"] == "grounding_unverified"
    assert "40% lift" not in repr(result)


def test_an_entirely_unauthorised_ranking_raises_rather_than_declining():
    """ADR 0008. A decline says "nothing close enough", which a CSM reads as a fact about
    the corpus. An empty authorised ranking is a fact about the infrastructure -- the index
    is missing this pool's vectors, or their scenario_key metadata is no longer admitted by
    the search filter. Returning no_close_match here would hide a broken index behind a
    normal-looking answer for as long as nobody looked."""
    class _NothingAuthorised:
        def search(self, query_vec, top_k):
            return [("999999", 0.99)]

    pairs = [{"pair_id": 11, "trigger_text": "t", "response_text": RESPONSE,
              "call_filename": CALL, "scenario_key": "performance_pushback"}]
    pool = retrieval.RetrievalPool(pairs, store=_NothingAuthorised())
    with pytest.raises(RuntimeError, match="no kb_pair the pool authorises"):
        answering.answer_situation("a client situation", pool, StubGateway(_payload()),
                                   embed_query=_embed_query)
