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

import asyncio
from dataclasses import dataclass

from ask_naren import answering, citations, intake, rendering, threads
from ask_naren.retrieval import Match, RetrievalPool


@dataclass(frozen=True)
class Anchor:
    """What one answer is about, resolved into the form its path consumes
    (`ask-naren/CONTEXT.md` **Anchor**).

    `scenario_key` is always set: an exchange implies its scenario. `pair` is the exchange,
    when the anchor holds one. `match` is the retrieval the anchor came from, and is None
    when nothing was searched -- which is why a path reports a match only if this holds one.
    """
    scenario_key: str
    pair: dict | None = None
    match: Match | None = None

    @classmethod
    def searched(cls, match: Match) -> "Anchor":
        return cls(scenario_key=match.pair["scenario_key"], pair=match.pair, match=match)


#: What Ask Naren asks when a message is on a carried situation but the last answer holds
#: nothing of the kind it needs (ADR 0013 point 3). WRITTEN HERE, NOT BY THE MODEL: it is the
#: same question every time and can invent nothing, and the never-ask-twice guard matches
#: on exactly this text.
NO_CARRIED_ANCHOR = ("Which conversation do you mean? Paste what the client said and Ask "
                     "Naren will answer from the closest real exchange in Naren's calls.")


async def _resolve_anchor(decision: intake.IntakeDecision, pool: RetrievalPool,
                          embed_query, *, carried: Anchor | None = None) -> Anchor:
    """THE ONE PLACE a scenario or exchange path gets the thing it answers about (#51).

    It replaces the "embed the query and take the nearest" each of those paths used to run
    for itself, so that how an anchor is found -- by searching, or from the thread -- is
    decided once, from `intake.ANCHORS`, rather than once per path.

    `carried` is the anchor `_carried_anchor` already looked up for a message on a carried
    situation (issue #53); it is used as it is, and nothing is embedded or searched.
    Otherwise the query is embedded exactly as on every other retrieving path: the current
    message alone (ADR 0006).
    """
    need = intake.ANCHORS[decision.intent]
    if need.kind not in (intake.SCENARIO_ANCHOR, intake.EXCHANGE_ANCHOR):
        raise ValueError(f"{decision.intent} consumes no scenario or exchange anchor")
    if carried is not None:
        return carried
    query_vec = (await embed_query([decision.retrieval_query]))[0]
    return Anchor.searched(await pool.top1(query_vec))


def _carried_anchor(decision: intake.IntakeDecision, turns,
                    pool: RetrievalPool) -> Anchor | None:
    """The anchor a message on a carried situation inherits, or None if there is none.

    A LOOKUP, NEVER A JUDGEMENT (ADR 0013 point 2): the model says only THAT the message is
    carried; which scenario is carried is whatever the last answer rested on. A model that
    can name a row can name one that does not exist.

    It reads the MOST RECENT answered or rendered turn and never walks further back -- the
    same rule as `threads.carried_source`, for the same reason: walking past a turn that
    holds no anchor would answer about an older, unrelated thing while the CSM is asking
    about what they just read. Clarifies and declines are skipped, because they rest on
    nothing.

    A scenario need is met by the turn's scenario, or by its pair's: an exchange implies its
    scenario. A carried pair the pool no longer holds is no anchor at all -- the pool is
    loaded once at startup and a pipeline re-run can retire a pair mid-conversation.
    """
    turn = threads.last_answer(turns)
    if turn is None:
        return None
    pair = pool.by_pair_id(turn.pair_id) if turn.pair_id is not None else None
    scenario_key = turn.scenario_key or (pair or {}).get("scenario_key") or ""
    if intake.ANCHORS[decision.intent].kind == intake.SCENARIO_ANCHOR and scenario_key:
        return Anchor(scenario_key=scenario_key, pair=pair)
    return None


async def respond(message: str, pool: RetrievalPool, gateway, *, embed_query, thread=(),
                  classify=intake.classify, k: int = answering.DEFAULT_K,
                  label_for=citations.resolve_label, moves_for=None,
                  playbook_for=None, scenarios_for=None, following_for=None,
                  account_for=citations.account_for) -> dict:
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
        decision, _meta = await classify(message, gateway, thread=turns)
    except Exception:                       # noqa: BLE001 -- see the docstring
        # ONE definition of the fallback, shared with intake's own retry exhaustion. Two
        # copies of a safety net is two places for them to stop agreeing.
        decision = intake.fallback_decision(message)

    decision = _guarded(decision, message, turns, pool)

    carried = None
    if decision.situation == intake.CARRIED and decision.intent != intake.FOLLOW_UP:
        # ON A CARRIED SITUATION (issue #53): the anchor comes from the thread, so it is
        # looked up before any path runs. When the last answer holds nothing of the kind
        # this intent needs, Ask Naren asks -- it never searches the fragment and never
        # walks back to an older turn (ADR 0013 point 3).
        carried = _carried_anchor(decision, turns, pool)
        if carried is None:
            if (threads.awaiting_clarify(turns)
                    or threads.clarify_already_asked(turns, NO_CARRIED_ANCHOR)):
                # The same clarify is never asked twice (`_guarded` rule 1): the CSM is
                # answering it now, so their message is answered as written.
                decision = intake.fallback_decision(message)
            else:
                return _with_intake(answering.clarify(NO_CARRIED_ANCHOR), decision)

    if decision.intent == intake.FOLLOW_UP:
        # NO RETRIEVAL AND NO EMBEDDING (ADR 0006). `_guarded` has already established that
        # a carried source exists and is still in the pool, so this cannot be reached with
        # nothing to ground on.
        source = pool.by_pair_id(threads.carried_source(turns).pair_id)
        return _with_intake(
            await answering.answer_follow_up(message, turns, source, gateway,
                                             label_for=label_for), decision)

    if decision.intent in intake.RENDERED_INTENTS:
        # NO MODEL CALL AT ALL (issues #19, #20). These answer from stored rows, so their
        # grounding guarantee is structural rather than verified -- a rendered list of the
        # coachable scenarios cannot invent a 35th. Nothing here can reach the gate because
        # nothing here generates anything for it to check.
        return _with_intake(
            await _rendered(message, decision, pool, embed_query=embed_query,
                            label_for=label_for, scenarios_for=scenarios_for,
                            following_for=following_for, playbook_for=playbook_for,
                            account_for=account_for, carried=carried),
            decision)

    if decision.intent == intake.PROCEDURE:
        # THE SCENARIO IS FOUND BY RETRIEVING or carried from the thread, never by asking
        # the model to name one. A model that can name a scenario can name one that does not
        # exist, and the taxonomy is Brain's to define. Opening a situation embeds the
        # question and takes the nearest exchange's scenario -- which is also what gives
        # that response a real cosine to report.
        return _with_intake(
            await _procedure(message, decision, pool, gateway, embed_query=embed_query,
                             label_for=label_for, playbook_for=playbook_for, k=k,
                             moves_for=moves_for, carried=carried),
            decision)

    if decision.intent == intake.CONTRAST_MY_REPLY:
        # THE CLIENT'S WORDS ARE THE QUERY, not the CSM's reply -- the question is "what did
        # Naren say when a client said this". `_guarded` has already established that both
        # spans were copied from the message rather than composed.
        return _with_intake(
            await answering.answer_contrast(
                decision.retrieval_query, decision.my_reply, pool, gateway,
                embed_query=embed_query, label_for=label_for),
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
        await answering.answer_situation(
            decision.retrieval_query, pool, gateway, embed_query=embed_query, k=k,
            label_for=label_for, moves_for=moves_for),
        decision)


async def _rendered(message: str, decision: intake.IntakeDecision, pool: RetrievalPool,
                    *, embed_query, label_for, scenarios_for, following_for,
                    playbook_for, account_for=citations.account_for,
                    carried: Anchor | None = None) -> dict:
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

    if intake.ANCHORS[decision.intent].kind == intake.NEIGHBOURHOOD_ANCHOR:
        # The query is embedded exactly as on every other retrieving path -- the current
        # message alone (ADR 0006). A neighbourhood is always searched (ADR 0013 point 4).
        neighbours = await pool.topk((await embed_query([decision.retrieval_query]))[0],
                                     rendering.NEIGHBOURS_SCANNED)

        if decision.intent == intake.CALL_PREP:
            # A COMPOSITE, AND EVERY PART OF IT IS RENDERED (issue #23). It reads a
            # neighbourhood the way `where_else_seen` does, each scenario's `arc` the way
            # `sequence` does, and one stored exchange the way `show_exchange` does.
            # Composing only rendered paths is what keeps ADR 0009's warning inapplicable:
            # there is no weaker guarantee to inherit, because neither half generates
            # anything.
            return rendering.call_prep(
                message, neighbours, scenarios=(scenarios_for() if scenarios_for else []),
                playbook_for=playbook_for, label_for=label_for)

        # THE ONE RENDERED INTENT THAT READS A NEIGHBOURHOOD RATHER THAN A NEAREST MATCH
        # (issue #22). "Is this a one-client quirk or a pattern" has no single-exchange form,
        # so the breadth is required by the question rather than chosen -- see
        # `rendering.NEIGHBOURS_SCANNED` for why that is not the shortlist ADR 0005 rejected.
        return rendering.where_else_seen(message, neighbours, account_for=account_for)

    # The rest are ABOUT one situation, and answer from its anchor.
    anchor = await _resolve_anchor(decision, pool, embed_query, carried=carried)

    if decision.intent == intake.SHOW_EXCHANGE:
        return rendering.show_exchange(anchor.match, label_for=label_for)

    if decision.intent == intake.WHAT_HAPPENED_NEXT:
        following = following_for(anchor.pair["pair_id"]) if following_for else []
        return rendering.what_happened_next(anchor.match, following, label_for=label_for)

    if decision.intent == intake.IMPROVE_AT_MOVE:
        # THE SCENARIO COMES FROM THE ANCHOR, as on every playbook path, and never from the
        # model -- a model that can name a scenario can name one that does not exist. No
        # live playbook is the same clarify `_from_playbook` returns, and for the same
        # reason: there is no Layer B substitute for "the criterion for this move".
        record = playbook_for(anchor.scenario_key) if playbook_for else None
        if not (record or {}).get("playbook"):
            return _no_play(anchor)
        return _matched(
            rendering.improve_at_move(message, anchor.scenario_key, record,
                                      label_for=label_for),
            anchor)

    if decision.intent in intake.PLAYBOOK_INTENTS:
        return _from_playbook(message, decision, anchor, playbook_for, label_for=label_for)

    scenario = None
    if scenarios_for:
        scenario = next((s for s in scenarios_for()
                         if s["scenario_key"] == anchor.scenario_key), None)
    return rendering.coverage_check(message, anchor.match, scenario, label_for=label_for)


async def _procedure(message: str, decision: intake.IntakeDecision,
                     pool: RetrievalPool, gateway, *, embed_query, label_for,
                     playbook_for, k: int, moves_for,
                     carried: Anchor | None = None) -> dict:
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

    A CARRIED SCENARIO HAS NO LAYER B FALLBACK (issue #53). Layer B answers from a search,
    and a message on a carried situation has nothing of its own to search on -- searching
    "what's the general approach here" is exactly the noise carrying exists to avoid. So no
    usable play is the no-recorded-play clarify, as on the rendered playbook paths.
    """
    embed_once = _memoised(embed_query)

    if carried is not None or playbook_for is not None:
        anchor = await _resolve_anchor(decision, pool, embed_once, carried=carried)
        record = playbook_for(anchor.scenario_key) if playbook_for else None
        playbook = (record or {}).get("playbook")
        if playbook:
            # None means the playbook carries no quotable evidence, which degrades to
            # Layer B below on the same footing as a scenario with no playbook at all.
            answered = await answering.answer_procedure(
                message, anchor.scenario_key, playbook, gateway, match=anchor.match,
                label_for=label_for)
            if answered is not None:
                return answered
        if anchor.match is None:
            return _no_play(anchor)

    return await answering.answer_situation(
        decision.retrieval_query, pool, gateway, embed_query=embed_once, k=k,
        label_for=label_for, moves_for=moves_for)


def _memoised(embed_query):
    """`embed_query`, but each distinct text is embedded ONCE per request.

    Finding the scenario needs a vector and so does the Layer B fallback, and they are the
    same vector -- yet the embedder's disk cache cannot save the second call, because a live
    CSM query is a novel string and therefore a guaranteed miss. Without this the fallback
    path silently bills two gateway embeddings for one question.

    *** IT CACHES THE IN-FLIGHT OPERATION, NOT THE FINISHED VECTOR. *** The synchronous
    version stored the result, which is safe only while nothing else can run during the
    call. Under async, `await` is a suspension point: two awaits on a cold key would BOTH
    see an empty dict and BOTH start an embedding.

    BE PRECISE ABOUT WHEN THAT CAN HAPPEN, because an earlier version of this comment was
    not. `_procedure` awaits sequentially, so it cannot double-bill even with a naive
    value-cache -- a review proved that by reverting this to value-caching and watching the
    test still pass. So this is not fixing a live defect on today's path; it is making the
    double-bill unreachable for ANY caller, including a future one that embeds a situation
    and its variants concurrently. The test drives it concurrently on purpose, since the
    production path does not.

    EXTRACTED FROM `_procedure` RATHER THAN LEFT A CLOSURE for exactly that reason: a memo
    whose correctness argument is about concurrency has to be reachable by a test that is
    concurrent, and a closure inside a dispatch function is not.
    """
    embedded: dict[tuple, "asyncio.Task"] = {}

    async def embed_once(texts):
        key = tuple(texts)
        task = embedded.get(key)
        if task is None:
            # ensure_future, not a bare coroutine: a coroutine can only be awaited once, so
            # caching one would make the second caller raise instead of reuse it.
            task = asyncio.ensure_future(embed_query(texts))
            embedded[key] = task
        return await task

    return embed_once


def _from_playbook(message: str, decision: intake.IntakeDecision, anchor: Anchor,
                   playbook_for, *, label_for=citations.resolve_label) -> dict:
    """The five questions a scenario's Layer C playbook answers by being rendered (#18).

    `label_for` reaches the two of the five that show Naren's verbatim words -- `phrasing`
    and `pitfalls`. The other three have nothing quotable even in principle (`arc` is a list
    of move NAMES, `situation_signature` and `n_evidence` are a sentence and a number), so
    they take no label and carry no source.

    THE SCENARIO COMES FROM THE ANCHOR, exactly as on the `procedure` path and for the same
    reason: a model that can name a scenario can name one that does not exist, and the
    taxonomy is Brain's to define.

    NO LIVE PLAYBOOK IS A CLARIFY, not a decline and not a Layer B fallback. Unlike
    `procedure` -- where Layer B still knows what Naren SAID about the situation, so a
    grounded answer to a slightly different question is worth having -- there is no Layer B
    substitute for "what order do I do this in" or "how many calls is this built on". The
    honest move is to say the play is not recorded for this situation and point at the thing
    that does work.
    """
    scenario_key = anchor.scenario_key
    record = playbook_for(scenario_key) if playbook_for else None
    playbook = (record or {}).get("playbook")
    if not playbook:
        return _no_play(anchor)

    if decision.intent == intake.SEQUENCE:
        rendered = rendering.sequence(scenario_key, playbook)
    elif decision.intent == intake.PHRASING:
        rendered = rendering.phrasing(scenario_key, playbook, label_for=label_for)
    elif decision.intent == intake.PITFALLS:
        rendered = rendering.pitfalls(scenario_key, playbook, label_for=label_for)
    elif decision.intent == intake.SCENARIO_CHECK:
        rendered = rendering.scenario_check(message, scenario_key, playbook)
    else:
        rendered = rendering.play_confidence(scenario_key, record)
    return _matched(rendered, anchor)


def _matched(response: dict, anchor: Anchor) -> dict:
    """`response`, carrying the `match` that picked its scenario (issue #45) -- when one
    did. An anchor that was not searched for has no match, and inventing one would put a
    cosine for a search that never ran into the record.

    EVERY PATH THAT RAN `pool.top1` REPORTS WHAT IT FOUND, in the one shape the answered and
    declined responses already use. These paths found their scenario by retrieving and had
    the cosine in hand, but sent none -- so a stored turn recorded NULL for a number that was
    computed and thrown away.

    ATTACHED HERE RATHER THAN INSIDE `rendering`, because the playbook renderers are handed a
    scenario key, not a match: they render a PLAY, which is the same document whichever
    exchange led to it. The match is a fact about this request's retrieval, and this is the
    layer that ran it.

    `answering._match_info` is the one definition of the shape, so this cannot drift from
    the answered and declined paths. `rank` is 1: the scenario came from the nearest
    exchange, and there is no shortlist on these paths.
    """
    if anchor.match is None:
        return response
    return {**response, "match": answering._match_info(anchor.match, 1)}


def _no_play(anchor: Anchor) -> dict:
    """No live playbook for the closest situation -- a CLARIFY, not a decline and not a
    Layer B fallback.

    ONE DEFINITION, shared by `_from_playbook` and `improve_at_move` (issue #23), because
    both say the same thing for the same reason: unlike `procedure`, where Layer B still
    knows what Naren SAID about the situation, there is no Layer B substitute for "what
    order do i do this in" or "what is the criterion for this move". Two copies would be two
    places for the sentence a CSM reads to drift.

    IT CARRIES `match`, UNLIKE EVERY OTHER CLARIFY (issue #45), when it searched: the
    scenario it names came from retrieval. A clarify's "no unverified text in any field"
    rule is untouched -- a cosine, a scenario key and a rank are numbers and an identifier
    the service computed, not prose for a CSM to believe. On a CARRIED scenario nothing was
    searched, so it carries none, and it does not call the scenario "the closest".
    """
    scenario = anchor.scenario_key.replace("_", " ")
    which = ("the closest situation to what you asked" if anchor.match is not None
             else "the situation this conversation is about")
    return _matched(answering.clarify(
        f"There is no recorded play for {scenario}, which is {which}. Describe a specific "
        f"client situation instead and Ask Naren will answer from the closest real "
        f"exchange."), anchor)


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

    5. SO IS THE CSM'S OWN REPLY (issue #21). `my_reply` is never embedded, so ADR 0006 does
       not reach it -- but it is rendered back to the CSM as the thing Naren is contrasted
       against, and a composed one puts words in their mouth. The tool would then show a
       CSM a comparison against a reply they never wrote, on a page whose whole subject is
       what they wrote. That is worse than a wrong answer, because there is nothing in it
       for them to disbelieve.

    6. NOTHING IS CARRIED INTO A FIRST MESSAGE (issue #53, ADR 0013 point 5). There is no
       thread to carry from; `intake.classify` forces this too, and this is what holds it
       for any other classifier.

    7. AN EXCHANGE IS NOT CARRIED YET. That is issue #54; until it ships, a carried
       exchange question is answered as written, as it was before carrying existed.
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

    elif decision.situation == intake.CARRIED:
        # 6. A FIRST MESSAGE OPENS ITS SITUATION (ADR 0013 point 5). `intake.classify`
        #    already forces this; an injected classify, or a future caller, may not. A
        #    carried decision has no query left, so "behaves as opens" is the fallback.
        if not turns:
            return intake.fallback_decision(message)
        # 7. CARRYING AN EXCHANGE IS NOT BUILT YET (issue #54). Until it is, a carried
        #    exchange question takes the fallback rather than an exchange found any other
        #    way -- the same answer it would have got before carrying existed.
        if intake.ANCHORS[decision.intent].kind == intake.EXCHANGE_ANCHOR:
            return intake.fallback_decision(message)

    # Rule 4 binds a decision that OPENS a situation: a carried one embeds nothing, so there
    # is no query to check. A decision that opens and fails it falls back and is NEVER
    # treated as carried instead -- ADR 0013's rejected option, because the copy check also
    # fails when the model paraphrases a NEW situation, and only intake can tell those apart.
    if (decision.situation == intake.OPENS
            and decision.intent in intake.RETRIEVING_INTENTS
            and not intake.is_verbatim_span(decision.retrieval_query, message)):
        return intake.fallback_decision(message)

    if (decision.intent == intake.CONTRAST_MY_REPLY
            and not intake.is_verbatim_span(decision.my_reply, message)):
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
                       "retrieval_query": decision.retrieval_query,
                       # Whether the answer was carried or searched for (issue #53): the one
                       # thing that tells a carried answer from a searched one when the
                       # answer itself looks the same.
                       "situation": decision.situation}}
