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

from ask_naren import answering, citations, intake, threads
from ask_naren.retrieval import RetrievalPool


def respond(message: str, pool: RetrievalPool, gateway, *, embed_query, thread=(),
            classify=intake.classify, k: int = answering.DEFAULT_K,
            label_for=citations.resolve_label, moves_for=None) -> dict:
    """Answer one message, ask the CSM something, or decline.

    `message` is what the CSM typed, framing and all. What reaches RETRIEVAL is intake's
    `retrieval_query` -- the client's own words -- which is the entire point: a request frame
    is boilerplate shared by every question, and adding one changes which exchange retrieval
    reaches for 81% of situations.

    `thread` is the conversation so far, held by the CALLER and replayed (issue #15). It
    reaches INTAKE, which cannot detect a follow-up, resolve its own clarify or avoid
    re-asking one without it. It NEVER reaches the embedded query -- ADR 0006 -- and the
    line below is where that holds: what gets embedded is `decision.retrieval_query`, which
    intake derives from THIS message alone. Defaults to empty, so `--ask` and every
    pre-thread caller behave exactly as before.

    INTAKE CANNOT TAKE THE TOOL DOWN. `intake.classify` already falls through to answering
    the message as written when the model or gateway misbehaves; the try here covers the
    remaining case of classify itself raising (an injected one in a test, or a future bug).
    Both land on the pre-intake behaviour, which is a working tool.
    """
    if not (message or "").strip():
        raise ValueError("message is empty")

    # Trimmed HERE rather than at the HTTP boundary so every caller gets the same bound --
    # `--ask`, a harness, and the service alike. A thread that has run all afternoon must
    # not quietly turn one question into a 60KB generation.
    turns = threads.trim(thread)

    try:
        decision, _meta = classify(message, gateway, thread=turns)
    except Exception:                       # noqa: BLE001 -- see the docstring
        # ONE definition of the fallback, shared with intake's own retry exhaustion. Two
        # copies of a safety net is two places for them to stop agreeing.
        decision = intake.fallback_decision(message)

    decision = _guarded(decision, message, turns, pool)

    if decision.intent == intake.FOLLOW_UP:
        # NO RETRIEVAL AND NO EMBEDDING (ADR 0006). `_guarded` has already established that
        # a carried source exists and is still in the pool, so this cannot be reached with
        # nothing to ground on.
        source = pool.by_pair_id(threads.carried_source(turns).pair_id)
        return _with_intake(
            answering.answer_follow_up(message, turns, source, gateway,
                                       label_for=label_for), decision)

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


def _guarded(decision: intake.IntakeDecision, message: str, turns,
             pool: RetrievalPool) -> intake.IntakeDecision:
    """Two rules the thread makes checkable, enforced in CODE rather than in a prompt.

    Both are in intake's prompt as well, and that is not duplication for its own sake: the
    prompt is how the model usually gets it right, and this is what happens when it does
    not. A rule a CSM would experience as the tool being broken -- being asked the same
    question forever, or being told nothing was found when nothing was searched -- is not
    something to leave to a classifier.

    1. THE SAME CLARIFY IS NEVER ASKED TWICE. If Ask Naren's last turn was a question, this
       message is the CSM answering it; asking again is the loop. The same question
       reappearing later in a thread is caught too. Falls through to answering the message
       as written, which is a best-effort answer rather than a dead end.

    2. A FOLLOW-UP NEEDS SOMETHING TO FOLLOW UP ON. No answered turn in the thread, or a
       carried `pair_id` the pool no longer holds (the pool is loaded once at startup and a
       pipeline re-run can retire a pair mid-conversation), and there is nothing to ground
       in. Answering the message as a fresh question is the honest degradation; declining
       would tell a CSM nothing was found when nothing was looked for.
    """
    if decision.intent == intake.CLARIFY and (
            threads.awaiting_clarify(turns)
            or threads.clarify_already_asked(turns, decision.question)):
        return intake.fallback_decision(message)

    if decision.intent == intake.FOLLOW_UP:
        carried = threads.carried_source(turns)
        if carried is None or pool.by_pair_id(carried.pair_id) is None:
            return intake.fallback_decision(message)

    return decision


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
