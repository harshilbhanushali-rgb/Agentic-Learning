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

from ask_naren import answering, citations, intake, rendering, threads
from ask_naren.retrieval import RetrievalPool


def respond(message: str, pool: RetrievalPool, gateway, *, embed_query, thread=(),
            classify=intake.classify, k: int = answering.DEFAULT_K,
            label_for=citations.resolve_label, moves_for=None,
            playbook_for=None, scenarios_for=None, following_for=None) -> dict:
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

    if decision.intent in intake.RENDERED_INTENTS:
        # NO MODEL CALL AT ALL (issues #19, #20). These answer from stored rows, so their
        # grounding guarantee is structural rather than verified -- a rendered list of the
        # coachable scenarios cannot invent a 35th. Nothing here can reach the gate because
        # nothing here generates anything for it to check.
        return _with_intake(
            _rendered(message, decision, pool, embed_query=embed_query, label_for=label_for,
                      scenarios_for=scenarios_for, following_for=following_for,
                      playbook_for=playbook_for),
            decision)

    if decision.intent == intake.PROCEDURE:
        # THE SCENARIO IS FOUND BY RETRIEVING, not by asking the model to name one. A model
        # that can name a scenario can name one that does not exist, and the taxonomy is
        # Brain's to define. So the question is embedded, the nearest exchange is found, and
        # its scenario is the one whose play gets answered -- which is also what gives this
        # response a real cosine to report.
        return _with_intake(
            _procedure(message, decision, pool, gateway, embed_query=embed_query,
                       label_for=label_for, playbook_for=playbook_for, k=k,
                       moves_for=moves_for),
            decision)

    if decision.intent == intake.CLARIFY:
        # Returned WITHOUT retrieving or generating. That is what makes a clarify cheap
        # enough to be worth asking, and it is why a clarify has nothing to ground.
        return _with_intake(answering.clarify(decision.question), decision)

    if decision.intent == intake.OUT_OF_SCOPE:
        # Deliberately a decline rather than a question back: there is nothing the CSM could
        # reword that would put a product fact into Naren's call transcripts.
        return _with_intake(
            answering.decline_without_search(answering.OUT_OF_SCOPE), decision)

    return _with_intake(
        answering.answer_situation(
            decision.retrieval_query, pool, gateway, embed_query=embed_query, k=k,
            label_for=label_for, moves_for=moves_for),
        decision)


def _rendered(message: str, decision: intake.IntakeDecision, pool: RetrievalPool, *,
              embed_query, label_for, scenarios_for, following_for, playbook_for) -> dict:
    """The five answers built from stored rows (issues #19, #20).

    `scenarios_for` returns the COACHABLE Layer A rows, and `following_for` returns the
    exchanges after a given pair in the same call. Both are injected functions loaded at
    startup, the same shape as `label_for` and `playbook_for` -- because the service holds no
    database handle while answering, so neither can be looked up per request.

    DEGRADES TO A CLARIFY, NOT AN ERROR, when the rows a path needs were never loaded. A
    service started without Layer A rows cannot answer "what do you cover", and saying so is
    better than a traceback or an empty list that reads as "nothing is covered".
    """
    if decision.intent in intake.CORPUS_INTENTS:
        scenarios = scenarios_for() if scenarios_for else []
        if not scenarios:
            return answering.clarify(
                "Ask Naren cannot list what it covers just now -- its topic index was not "
                "loaded. Describe a client situation instead and it will search Naren's "
                "calls directly.")
        if decision.intent == intake.DISCOVERY:
            return rendering.discovery(scenarios)
        return rendering.frequency(scenarios)

    # The three that are ABOUT a situation and therefore retrieve one. The query is embedded
    # exactly as on every other retrieving path -- the current message alone (ADR 0006).
    match = pool.top1(embed_query([decision.retrieval_query])[0])

    if decision.intent == intake.SHOW_EXCHANGE:
        return rendering.show_exchange(match, label_for=label_for)

    if decision.intent == intake.WHAT_HAPPENED_NEXT:
        following = following_for(match.pair["pair_id"]) if following_for else []
        return rendering.what_happened_next(match, following, label_for=label_for)

    if decision.intent in intake.PLAYBOOK_INTENTS:
        return _from_playbook(message, decision, match, playbook_for, label_for=label_for)

    scenario = None
    if scenarios_for:
        scenario = next((s for s in scenarios_for()
                         if s["scenario_key"] == match.pair["scenario_key"]), None)
    return rendering.coverage_check(message, match, scenario, label_for=label_for)


def _procedure(message: str, decision: intake.IntakeDecision, pool: RetrievalPool, gateway,
               *, embed_query, label_for, playbook_for, k: int, moves_for) -> dict:
    """The Layer C `procedure` path (issue #17), and its degradation.

    NO LIVE PLAYBOOK FALLS BACK TO THE LAYER B ANSWER rather than declining. 1 of 34
    coachable scenarios has no live playbook (contract_and_legal_review, whose snap collapsed
    below the move floor), and `playbook_for` is None entirely when the service was started
    without loading them. In both cases the tool still knows what Naren SAID in the closest
    real exchange, and a grounded answer to a slightly different question beats "no" -- which
    is the ticket's "degrades rather than fails".

    The retrieval here is `decision.retrieval_query`, the situation with the asking-framing
    stripped, exactly as on the reply_to_client path. It is embedded once and used twice: to
    pick the scenario, and -- on the fallback -- to answer from.
    """
    # EMBEDDED ONCE PER REQUEST, not once per caller. Finding the scenario needs a vector
    # and so does the Layer B fallback, and they are the same vector -- but the embedder's
    # disk cache cannot save the second call, because a live CSM query is a novel string and
    # therefore a guaranteed miss. Without this memo the fallback path silently bills two
    # gateway embeddings for one question.
    embedded: dict[tuple, object] = {}

    def embed_once(texts):
        key = tuple(texts)
        if key not in embedded:
            embedded[key] = embed_query(texts)
        return embedded[key]

    if playbook_for is not None:
        match = pool.top1(embed_once([decision.retrieval_query])[0])
        record = playbook_for(match.pair["scenario_key"])
        playbook = (record or {}).get("playbook")
        if playbook:
            # None means the playbook carries no quotable evidence, which degrades to
            # Layer B below on the same footing as a scenario with no playbook at all.
            answered = answering.answer_procedure(message, match, playbook, gateway,
                                                  label_for=label_for)
            if answered is not None:
                return answered

    return answering.answer_situation(
        decision.retrieval_query, pool, gateway, embed_query=embed_once, k=k,
        label_for=label_for, moves_for=moves_for)


def _from_playbook(message: str, decision: intake.IntakeDecision, match,
                   playbook_for, *, label_for=citations.resolve_label) -> dict:
    """The five questions a scenario's Layer C playbook answers by being rendered (#18).

    `label_for` reaches the two of the five that show Naren's verbatim words -- `phrasing`
    and `pitfalls`. The other three have nothing quotable even in principle (`arc` is a list
    of move NAMES, `situation_signature` and `n_evidence` are a sentence and a number), so
    they take no label and carry no source.

    THE SCENARIO IS FOUND BY RETRIEVING, exactly as on the `procedure` path and for the same
    reason: a model that can name a scenario can name one that does not exist, and the
    taxonomy is Brain's to define.

    NO LIVE PLAYBOOK IS A CLARIFY, not a decline and not a Layer B fallback. Unlike
    `procedure` -- where Layer B still knows what Naren SAID about the situation, so a
    grounded answer to a slightly different question is worth having -- there is no Layer B
    substitute for "what order do I do this in" or "how many calls is this built on". The
    honest move is to say the play is not recorded for this situation and point at the thing
    that does work.
    """
    scenario_key = match.pair["scenario_key"]
    record = playbook_for(scenario_key) if playbook_for else None
    playbook = (record or {}).get("playbook")
    if not playbook:
        return answering.clarify(
            f"There is no recorded play for {scenario_key.replace('_', ' ')}, which is the "
            f"closest situation to what you asked. Describe a specific client situation "
            f"instead and Ask Naren will answer from the closest real exchange.")

    if decision.intent == intake.SEQUENCE:
        return rendering.sequence(scenario_key, playbook)
    if decision.intent == intake.PHRASING:
        return rendering.phrasing(scenario_key, playbook, label_for=label_for)
    if decision.intent == intake.PITFALLS:
        return rendering.pitfalls(scenario_key, playbook, label_for=label_for)
    if decision.intent == intake.SCENARIO_CHECK:
        return rendering.scenario_check(message, scenario_key, playbook)
    return rendering.play_confidence(scenario_key, record)


def _guarded(decision: intake.IntakeDecision, message: str, turns,
             pool: RetrievalPool) -> intake.IntakeDecision:
    """The rules a thread makes checkable, enforced in CODE rather than in a prompt.

    All four are in intake's prompt as well, and that is not duplication for its own sake:
    the prompt is how the model usually gets it right, and this is what happens when it does
    not. A rule a CSM would experience as the tool being broken -- being asked the same
    question forever, or getting a confident answer about the wrong client -- is not
    something to leave to a classifier.

    Every failure lands on `fallback_decision`: answer the message as written. That is the
    behaviour the tool had before intake existed, so a guard firing costs the framing strip
    for one message and never costs an answer.

    1. THE SAME CLARIFY IS NEVER ASKED TWICE. If Ask Naren's last turn was a question, this
       message is the CSM answering it; asking again is the loop. The same question
       reappearing later in a thread is caught too.

    2. A FOLLOW-UP NEEDS SOMETHING TO FOLLOW UP ON. No answered turn in the thread, or a
       carried `pair_id` the pool no longer holds (the pool is loaded once at startup and a
       pipeline re-run can retire a pair mid-conversation), and there is nothing to ground
       in. Declining would tell a CSM nothing was found when nothing was looked for.

    3. NOTHING IS A FOLLOW-UP TO A QUESTION. If Ask Naren's last turn asked the CSM
       something, there is no answer for this message to be going deeper on -- it is either
       the material that was asked for or a change of subject, and both need a search. Left
       unguarded this is the worst shape of wrong this tool has: rule 2 walks back past the
       clarify to an OLDER answered turn, finds a real `pair_id`, and answers the client's
       newly supplied words from a call about something else -- grounded, coherent, and
       about the wrong client.

    4. THE EMBEDDED QUERY IS A SPAN OF THIS MESSAGE (ADR 0006). Since intake is shown the
       thread it can compose a query out of HISTORY, which is the one thing the ADR forbids
       reaching the vector. The prompt says to copy from the current message; this is what
       makes it true. `intake.is_verbatim_span` is the same predicate the offline harness
       scores, so the instrument and the guard cannot drift apart.

       ON EVERY INTENT THAT EMBEDS, which it was not until this was found in #18's review.
       The rule is about THE VECTOR, not about which intent produced it, but this listed
       only `reply_to_client` and `procedure` while eight intents embed -- so the six added
       by #18, #19 and #20 could reach the vector with composed text. The shape that makes
       it matter is the one ADR 0006 itself names: "and what usually goes wrong?" names no
       situation, so a model that composes rather than copies lifts one from the history,
       and that decides WHICH PLAY gets rendered with `scenario_key` the only tell.

       Reading `intake.RETRIEVING_INTENTS` rather than a list written out here is the point
       -- that drift is what the constant exists to make impossible.
    """
    if decision.intent == intake.CLARIFY and (
            threads.awaiting_clarify(turns)
            or threads.clarify_already_asked(turns, decision.question)):
        return intake.fallback_decision(message)

    if decision.intent == intake.FOLLOW_UP:
        carried = threads.carried_source(turns)
        if (threads.awaiting_clarify(turns)
                or carried is None
                or pool.by_pair_id(carried.pair_id) is None):
            return intake.fallback_decision(message)

    if (decision.intent in intake.RETRIEVING_INTENTS
            and not intake.is_verbatim_span(decision.retrieval_query, message)):
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
