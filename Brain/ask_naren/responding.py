"""The one call the HTTP layer makes: a CSM's message in, a response body out.

This is the seam intake sits behind. It runs intake, then dispatches to the ANSWER PATH for
whichever intent came back (`ask-naren/CONTEXT.md`).

WHY THIS SITS ABOVE `answering.answer_situation` RATHER THAN INSIDE IT. That function is the
arm Ask Naren's measured accuracy was recorded on, and its prompts are frozen against ADR
0001. Keeping it callable EXACTLY as before means a re-measurement still compares against the
recorded number instead of a drifted one. Intake changes what reaches it; it does not change
it.

`classify` and `embed_query` are injected rather than imported, matching how `label_for` and
`moves_for` already work in this package: a dispatch test must not pay for a generation, and
routing accuracy is measured separately against labelled messages.
"""
from __future__ import annotations

from ask_naren import answering, citations, intake
from ask_naren.retrieval import RetrievalPool


def respond(message: str, pool: RetrievalPool, gateway, *, embed_query,
            classify=intake.classify, k: int = answering.DEFAULT_K,
            label_for=citations.resolve_label, moves_for=None) -> dict:
    """Answer one message, ask the CSM something, or decline.

    `message` is what the CSM typed, framing and all. What reaches RETRIEVAL is intake's
    `retrieval_query` -- the client's own words -- which is the entire point: a request frame
    is boilerplate shared by every question, and adding one changes which exchange retrieval
    reaches for 81% of situations.

    INTAKE CANNOT TAKE THE TOOL DOWN. `intake.classify` already falls through to answering
    the message as written when the model or gateway misbehaves; the try here covers the
    remaining case of classify itself raising (an injected one in a test, or a future bug).
    Both land on the pre-intake behaviour, which is a working tool.
    """
    if not (message or "").strip():
        raise ValueError("message is empty")

    try:
        decision, _meta = classify(message, gateway)
    except Exception:                       # noqa: BLE001 -- see the docstring
        # ONE definition of the fallback, shared with intake's own retry exhaustion. Two
        # copies of a safety net is two places for them to stop agreeing.
        decision = intake.fallback_decision(message)

    if decision.intent == intake.CLARIFY:
        # Returned WITHOUT retrieving or generating. That is what makes a clarify cheap
        # enough to be worth asking, and it is why a clarify has nothing to ground.
        return _with_intake(answering.clarify(decision.question), decision)

    if decision.intent == intake.OUT_OF_SCOPE:
        # Deliberately a decline rather than a question back: there is nothing the CSM could
        # reword that would put a product fact into Naren's call transcripts.
        return _with_intake(
            answering.decline_before_retrieval(answering.OUT_OF_SCOPE), decision)

    return _with_intake(
        answering.answer_situation(
            decision.retrieval_query, pool, gateway, embed_query=embed_query, k=k,
            label_for=label_for, moves_for=moves_for),
        decision)


def _with_intake(response: dict, decision: intake.IntakeDecision) -> dict:
    """Record what intake decided, on every response.

    Without this an intake that is silently failing every request is INDISTINGUISHABLE from
    one that is working: both fall through to answering the message as written, both return a
    normal answer, and nothing says which happened.

    It also answers ADR 0006's objection to query rewriting -- "a bad rewrite would be
    invisible in the response". Intake is ASKED for a verbatim span, but asking is not
    enforcing: a model told to copy will sometimes compose, and `measure_intake_accuracy.py`
    caught it doing exactly that, once with a perspective flip ("their side" -> "our side")
    that inverts meaning while staying near-identical in embedding space. Echoing the query
    is what makes that visible in production rather than only in an offline run.

    Safe to echo because `retrieval_query` derives from the CSM's OWN message -- it is never
    an answer, a quote or anything drawn from Naren's calls, so it cannot carry ungrounded
    content into a declined response. That, not its provenance, is the property that decides
    whether a new response field is safe.
    """
    return {**response,
            "intake": {"intent": decision.intent,
                       "retrieval_query": decision.retrieval_query}}
