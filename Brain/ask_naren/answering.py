"""Situation in, grounded answer or decline out -- Ask Naren's whole request path.

The prompt is the one the prototype eval validated (ask-naren/prototype/
eval_pairs_vs_playbook.py `_build_prompt`), in its pairs-only form: ADR 0001 measured no
lift from adding the scenario's Layer C playbook, so the PAIRS-ONLY prompt is what ships.
The playbook-augmented variant lives here too (issue #5) and is dark -- reachable only by a
caller passing `moves_for`, which only the service entry point does, and only when its own
PLAYBOOK_AUGMENTED constant is flipped in code. Nothing a request carries can select it.

Nothing here talks to Postgres. The pool arrives already loaded, deduped and embedded; this
module embeds only the incoming situation, generates, and applies the grounding gate.
"""
from __future__ import annotations

from ask_naren import citations, grounding, threads
from ask_naren.retrieval import Match, RetrievalPool

# The licensed config already used for Layer C's playbook backfill and Layer D's pairwise
# grader, and the config the eval behind ADR 0001 ran on. Brain measures the MODEL as the
# lever on this corpus -- gemini-3.5-flash-lite follows grounding instructions 11% of the
# time against 3.6-flash's 77% -- so this is not a free knob.
CHAT_MODEL = "gemini-3.6-flash"
REASONING_EFFORT = "medium"
TEMPERATURE = 0.2

# reasoning_effort=medium spends part of the budget on reasoning tokens before the visible
# completion, so the ceiling needs real headroom: 2048 truncated a JSON response mid-string
# on the prototype's first real run.
MAX_TOKENS = 8192

# One retry. The gate failing twice on the same grounding is not a transient blip worth
# spending a third call on -- it means this exchange is not one the model can answer from
# without inventing, which is exactly what a decline is for.
MAX_ATTEMPTS = 2

# The shipped shortlist size. 1 is the rank-1 selection issue #7 measured at 83%; issue #8
# A/Bs 5 against it. This default does not move until that decision is recorded -- widening
# it would ship an unmeasured change to the only path with a measured quality number.
DEFAULT_K = 1

# THE RESPONSE CONTRACT DISCRIMINATES ON `outcome`, NOT ON A BOOLEAN. A caller switches on
# this one key and the three values are exhaustive. There is deliberately no `declined` flag
# alongside it: two discriminators for one decision is how the answered and declined paths
# eventually disagree about which one a response is.
#
# NOT the `declined` key in the MODEL's JSON. build_prompt asks the model for that one and
# grounding.check reads it; it is frozen by ADR 0001 and is a different contract that happens
# to share an English word. Renaming one must never rename the other.
ANSWERED = "answered"
DECLINED = "declined"
CLARIFY = "clarify"

NO_CLOSE_MATCH = "no_close_match"
GROUNDING_UNVERIFIED = "grounding_unverified"
OUT_OF_SCOPE = "out_of_scope"
FOLLOW_UP_UNGROUNDED = "follow_up_ungrounded"

_MESSAGES = {
    NO_CLOSE_MATCH: (
        "No close match in Naren's calls. Nothing in his history is near enough to this "
        "situation to answer from, so Ask Naren is declining rather than guessing."
    ),
    GROUNDING_UNVERIFIED: (
        "No answer could be grounded in the matched call. The closest exchange was found, "
        "but the drafted answer could not be verified against what Naren actually said, so "
        "Ask Naren is declining rather than showing it."
    ),
    OUT_OF_SCOPE: (
        "Ask Naren answers from what Naren said on real client calls, so it cannot answer "
        "questions about Joveo's product, pricing or contract terms. Rewording this will "
        "not help -- the answer is not in his calls to find."
    ),
    FOLLOW_UP_UNGROUNDED: (
        "That follow-up goes beyond what Naren said in the call the last answer came from. "
        "Rather than guess, Ask Naren is declining -- describe the situation as a fresh "
        "question and it will search his calls for a closer moment."
    ),
}


def build_prompt(situation: str, matched: dict) -> str:
    """The pairs-only prompt, verbatim in shape from the validated prototype.

    The JSON contract (declined / answer / quote / cited_call) is what the grounding gate
    checks, so changing these key names is changing the gate's input, not just wording.
    """
    return "\n".join([
        'You are "Ask Naren", an internal Joveo tool that helps a CSM handle a live client '
        "situation by grounding the answer in Naren's closest real historical response.",
        "",
        f"CSM's situation: {situation}",
        "",
        "Closest matching real exchange from Naren's own calls:",
        f"  Client said: {matched['trigger_text']}",
        f"  Naren replied: {matched['response_text']}",
        f"  (call: {matched['call_filename']})",
        "",
        "Using ONLY the grounding above, write the answer a CSM should give. Paraphrase "
        "Naren's real reply rather than inventing a new answer. If the retrieved exchange "
        "is not actually a close match to the CSM's situation, decline instead of "
        "answering ungrounded.",
        "",
        "Respond as JSON with exactly these keys:",
        '  "declined": boolean,',
        '  "answer": the coaching answer for the CSM (empty string if declined),',
        '  "quote": a verbatim substring copied from Naren\'s reply above that the answer '
        'is based on (empty string if declined),',
        '  "cited_call": the call identifier given above, copied exactly (empty string if '
        "declined).",
    ])


def build_candidates_prompt(situation: str, candidates: list[dict]) -> str:
    """The shortlist form of the prompt: several retrieved exchanges, nearest first, and the
    model choosing which one to answer from.

    Kept SEPARATE from build_prompt rather than generalising it. build_prompt is the exact
    string the 83% in issue #7 was measured on, and issue #8 is an A/B against that number:
    a refactor that unified the two would move BOTH arms at once and leave nothing to
    compare. The JSON contract is deliberately unchanged -- `cited_call` already carries
    which call the answer rests on, which is what lets the grounding gate resolve one
    candidate out of a shortlist without a new field for the model to get wrong.
    """
    lines = [
        'You are "Ask Naren", an internal Joveo tool that helps a CSM handle a live client '
        "situation by grounding the answer in Naren's closest real historical response.",
        "",
        f"CSM's situation: {situation}",
        "",
        f"The {len(candidates)} closest matching real exchanges from Naren's own calls, "
        "closest first:",
    ]
    for n, candidate in enumerate(candidates, 1):
        lines += [
            "",
            f"  [{n}] Client said: {candidate['trigger_text']}",
            f"      Naren replied: {candidate['response_text']}",
            f"      (call: {candidate['call_filename']})",
        ]
    lines += [
        "",
        "Pick the ONE exchange that genuinely matches the CSM's situation and write the "
        "answer a CSM should give, using ONLY that exchange as grounding. Being listed "
        "first does not make an exchange the right one. Paraphrase Naren's real reply "
        "rather than inventing a new answer. If NONE of them is actually a close match to "
        "the CSM's situation, decline instead of answering ungrounded.",
        "",
        "Respond as JSON with exactly these keys:",
        '  "declined": boolean,',
        '  "answer": the coaching answer for the CSM (empty string if declined),',
        '  "quote": a verbatim substring copied from the reply of the ONE exchange you '
        'chose (empty string if declined),',
        '  "cited_call": the call identifier of the ONE exchange you chose, copied exactly '
        '(empty string if declined).',
    ]
    return "\n".join(lines)


def build_playbook_prompt(situation: str, matched: dict, moves: list[dict]) -> str:
    """The playbook-augmented variant (issue #5), byte-identical in shape to the prototype
    that ADR 0001 measured -- the pairs-only prompt plus the scenario's Layer C `key_moves`.

    Held to the measured shape deliberately: ADR 0001 found no lift and explicitly left the
    switch as an empirical question to revisit if Layer C's criterion quality improves. A
    re-measure is only comparable to the recorded result if the variant is the same variant.
    Improving this wording would silently invalidate the number it would be compared against.
    """
    lines = [
        'You are "Ask Naren", an internal Joveo tool that helps a CSM handle a live client '
        "situation by grounding the answer in Naren's closest real historical response.",
        "",
        f"CSM's situation: {situation}",
        "",
        "Closest matching real exchange from Naren's own calls:",
        f"  Client said: {matched['trigger_text']}",
        f"  Naren replied: {matched['response_text']}",
        f"  (call: {matched['call_filename']})",
        "",
        "Known best-practice moves for this type of situation:",
    ]
    for move in moves:
        lines.append(f"  - {move.get('name', '')}: {move.get('criterion', '')}")
    lines += [
        "",
        "Using ONLY the grounding above, write the answer a CSM should give. Paraphrase "
        "Naren's real reply rather than inventing a new answer. If the retrieved exchange "
        "is not actually a close match to the CSM's situation, decline instead of "
        "answering ungrounded.",
        "",
        "Respond as JSON with exactly these keys:",
        '  "declined": boolean,',
        '  "answer": the coaching answer for the CSM (empty string if declined),',
        '  "quote": a verbatim substring copied from Naren\'s reply above that the answer '
        'is based on (empty string if declined),',
        '  "cited_call": the call identifier given above, copied exactly (empty string if '
        "declined).",
    ]
    return "\n".join(lines)


def build_follow_up_prompt(message: str, turns, source: dict) -> str:
    """The follow-up variant (issue #16): the conversation so far, the ONE exchange the
    previous answer rested on, and a question that only means something against them.

    A NEW VARIANT, NOT AN EDIT. `build_prompt` is byte-identical to what ADR 0001 measured
    and stays that way; a prompt carrying a conversation is a different prompt and gets its
    own function, exactly as the playbook and shortlist variants did.

    THE JSON CONTRACT IS THE SAME FOUR KEYS, deliberately. That is what lets `grounding.check`
    hold this answer to the identical bar without a second gate -- one gate, a different
    grounding source, which is the rule `ask-naren/CONTEXT.md` states.

    ONLY THE CARRIED SOURCE IS SHOWN. The conversation above contains previous ANSWERS,
    which are paraphrases of Naren, and if an earlier turn cited a different call its
    identifier is in there too. Showing one exchange is the first half of stopping a quote
    being stitched out of the wrong one; the gate verifying against that same one exchange
    is the half that is actually enforced.
    """
    return "\n".join([
        'You are "Ask Naren", an internal Joveo tool that helps a CSM handle a live client '
        "situation by grounding the answer in Naren's closest real historical response.",
        "",
        "The CSM is FOLLOWING UP on an answer you already gave. This is not a new "
        "situation, and nothing new has been searched for.",
        "",
        "The conversation so far, oldest first:",
        "",
        threads.render(turns),
        "",
        f"The CSM's follow-up: {message}",
        "",
        "The exchange the previous answer rested on, from Naren's own calls -- this is the "
        "ONLY grounding you have:",
        f"  Client said: {source['trigger_text']}",
        f"  Naren replied: {source['response_text']}",
        f"  (call: {source['call_filename']})",
        "",
        "Answer the follow-up using ONLY that exchange. Paraphrase what Naren really said "
        "rather than inventing a new answer, and do not draw on anything else in the "
        "conversation as if it were something he said. If the follow-up needs something "
        "Naren did not say in that exchange, decline instead of answering ungrounded -- "
        "the CSM can ask it as a fresh question and get a real search.",
        "",
        "Respond as JSON with exactly these keys:",
        '  "declined": boolean,',
        '  "answer": the coaching answer for the CSM (empty string if declined),',
        '  "quote": a verbatim substring copied from Naren\'s reply above that the answer '
        'is based on (empty string if declined),',
        '  "cited_call": the call identifier given above, copied exactly (empty string if '
        "declined).",
    ])


def build_contrast_prompt(client_words: str, my_reply: str, matched: dict) -> str:
    """The `contrast_my_reply` prompt (issue #21): the client's words, what the CSM already
    replied, and what Naren really said to the same thing.

    A NEW VARIANT. `build_prompt` and `build_playbook_prompt` are frozen against ADR 0001 and
    are not touched -- the ticket says so explicitly.

    That freeze is now actually CHECKED, which it was not:
    `test_the_frozen_prompts_are_byte_identical_to_the_ones_adr_0001_measured` compares both
    against the prototype ADR 0001 measured, byte for byte. `sanity_check_harness.py` only
    ever asserted that `answer_situation` USES `build_prompt`, which stays true however the
    text changes -- so the freeze was an assertion in three docstrings and nowhere else, and
    a reword would have passed the whole suite while invalidating the recorded number.

    THE SAME FOUR-KEY JSON CONTRACT as every other generating path, deliberately. One
    contract is what lets ONE grounding gate serve all of them (ADR 0009 rejected a second
    shape for exactly this reason), so a contrast is verified by the same `grounding.check`
    against the same `from_pairs` source, with no new gate and no new rule.

    IT MAY NOT SAY THE CSM WAS RIGHT OR WRONG, and that is the ticket's fourth criterion
    rather than a stylistic choice. Judging a reply against a standard is Layer D's grader:
    it needs a rubric, a pairwise comparison and a measured instrument, none of which exist
    on this path. What Ask Naren honestly has is ONE real moment where Naren faced the same
    thing -- which is evidence a CSM can weigh, not a verdict.

    The difference matters because a verdict would be believed. A single retrieved exchange
    is one data point from one call; "Naren did X here" supports "you did not do X", and
    supports nothing at all about whether X was the better move for THIS client.
    """
    return "\n".join([
        'You are "Ask Naren", an internal Joveo tool. A CSM has ALREADY replied to a client '
        "and wants to see how Naren handled the closest real moment from his own calls.",
        "",
        f"What the client said: {client_words}",
        "",
        f"What the CSM replied: {my_reply}",
        "",
        "The closest matching real exchange from Naren's own calls:",
        f"  Client said: {matched['trigger_text']}",
        f"  Naren replied: {matched['response_text']}",
        f"  (call: {matched['call_filename']})",
        "",
        "Using ONLY the grounding above, describe how Naren's real reply differs from what "
        "the CSM wrote -- what he does that they did not, and what he leaves out that they "
        "put in. Be concrete and short.",
        "",
        "DO NOT SAY THE CSM WAS RIGHT OR WRONG, and do not score, grade or rank their "
        "reply. You are looking at one real moment from one call, which is enough to say "
        "what Naren did and not enough to say what the CSM should have done. Do not write "
        "\"you should have\", \"a better reply would be\", or \"correct\"/\"incorrect\". "
        "Describe the difference and let the CSM judge it.",
        "",
        "If the retrieved exchange is not actually a close match to what this client said, "
        "decline instead of contrasting against something unrelated.",
        "",
        "Respond as JSON with exactly these keys:",
        '  "declined": boolean,',
        '  "answer": the contrast for the CSM (empty string if declined),',
        '  "quote": a verbatim substring copied from Naren\'s reply above that the contrast '
        'is based on (empty string if declined),',
        '  "cited_call": the call identifier given above, copied exactly (empty string if '
        "declined).",
    ])


def answer_contrast(client_words: str, my_reply: str, pool: RetrievalPool, gateway, *,
                    embed_query, label_for=citations.resolve_label) -> dict:
    """Set the CSM's own reply against Naren's closest real one (issue #21).

    WHAT GETS EMBEDDED IS THE CLIENT'S WORDS, NOT THE CSM'S REPLY. The question being
    answered is "what did Naren say when a client said this", so the client's turn is the
    query -- exactly as on the `reply_to_client` path, and for the same measured reason
    (`docs/findings/answer-failure-modes.md`). Embedding the CSM's reply would search the
    responder's side of the corpus for a trigger, which is a different conversation.

    THE SAME GATE, THE SAME SOURCE. A contrast is a model paraphrasing Naren's real reply,
    so it is grounded identically to a Layer B answer: `grounding.from_pairs`, one verified
    quote covering essentially the whole answer. Unlike a Layer C answer (ADR 0009) there is
    no build-time verification to lean on and none is needed.

    `my_reply` COMES BACK ON THE RESPONSE because the answer is a comparison, and a contrast
    rendered without the thing being contrasted is half an answer. It is the CSM's own text
    echoed back, never anything drawn from Naren's calls, so it cannot carry ungrounded
    content into a response -- the same property that makes `retrieval_query` safe to echo.

    NO `k`, AND THAT IS DELIBERATE RATHER THAN AN OMISSION. `build_contrast_prompt` is
    defined for ONE exchange; a shortlist form of it is a prompt nobody has evaluated, which
    is the same reason `answer_situation` refuses to combine a shortlist with playbook moves
    rather than inventing a third variant at request time. Accepting `k` while prompting
    with `pairs[0]` would be worse than either: the gate would hold sources the model was
    never shown, and since two pairs can share a `call_filename` (`grounding.check` says so
    explicitly) a quote could verify against a candidate that was not in the prompt -- citing
    a call the answer does not come from, with every gate metric still reporting a pass.
    Retrieving one is what the prompt can honestly use.
    """
    if not (client_words or "").strip():
        raise ValueError("client_words is empty")
    if not (my_reply or "").strip():
        # The intake validator already refuses this, so arriving here means a caller
        # bypassed it. A contrast with nothing to contrast would quietly answer a different
        # question -- louder is better than helpful.
        raise ValueError("a contrast with no reply to contrast has nothing to compare")

    candidates = pool.topk(embed_query([client_words])[0], 1)
    if not candidates:
        # Same RuntimeError, same reason as answer_situation: an entirely unauthorised
        # ranking is a fact about the INDEX, not about the corpus, and dressing it as a
        # decline would hide a broken index behind a normal-looking answer (ADR 0008).
        raise RuntimeError(
            "retrieval returned no kb_pair the pool authorises -- the vector store and the "
            "pool disagree about what exists. Run ops/check_vector_coverage.py.")
    # ONE candidate, and the gate is given exactly it -- the source list IS what the prompt
    # showed, which is half of what the gate means (`ask-naren/CONTEXT.md`).
    pairs = [candidates[0].pair]

    prompt = build_contrast_prompt(client_words, my_reply, pairs[0])
    for _ in range(MAX_ATTEMPTS):
        payload, _meta = gateway.chat_json(
            prompt, model=CHAT_MODEL, reasoning_effort=REASONING_EFFORT,
            temperature=TEMPERATURE, max_tokens=MAX_TOKENS, no_cache=True)
        if payload.get("declined"):
            return _decline(NO_CLOSE_MATCH, candidates[0], 1, label_for)
        gate = grounding.check(payload, grounding.from_pairs(pairs))
        if gate.passed:
            rank = next(i for i, m in enumerate(candidates, 1)
                        if m.pair is gate.source.payload)
            return {**_answer(payload, candidates[rank - 1], rank, label_for),
                    "my_reply": my_reply.strip()}

    return _decline(GROUNDING_UNVERIFIED, candidates[0], 1, label_for)


def answer_follow_up(message: str, turns, source: dict, gateway, *,
                     label_for=citations.resolve_label) -> dict:
    """Answer a follow-up from the thread and the grounding source already cited.

    NO RETRIEVAL AND NO EMBEDDING. That is the point, and it is ADR 0006's answer to "how
    does a question like 'and if they push back on price?' get answered at all" -- the ADR
    rejected rewriting such a message into a searchable query, on the grounds that the case
    is already covered by not searching.

    `source` is a `kb_pairs` row resolved from the thread's carried `pair_id`. The caller
    resolves it, because the caller holds the pool.

    NO `match` ON THE RESPONSE, for exactly the reason `decline_without_search` carries
    none: nothing was searched, so there is no cosine and no rank, and reporting one would
    put a fabricated number into the record decline-rate calibration will later read. The
    `citation` still says precisely which exchange the answer rests on.
    """
    if not (message or "").strip():
        raise ValueError("message is empty")

    prompt = build_follow_up_prompt(message, turns, source)
    for _ in range(MAX_ATTEMPTS):
        payload, _meta = gateway.chat_json(
            prompt, model=CHAT_MODEL, reasoning_effort=REASONING_EFFORT,
            temperature=TEMPERATURE, max_tokens=MAX_TOKENS, no_cache=True)
        if payload.get("declined"):
            return decline_without_search(FOLLOW_UP_UNGROUNDED)
        # ONE candidate: the carried source and nothing else. A quote lifted from an
        # EARLIER turn's grounding source fails here -- it either cites a call not in this
        # list, or it does not verify against this reply. That is the quote-bleed guarantee,
        # and it is a property of what the gate is given rather than of the prompt asking
        # nicely.
        if grounding.check(payload, grounding.from_pairs([source])).passed:
            return {"outcome": ANSWERED,
                    "answer": payload["answer"].strip(),
                    "quote": payload["quote"].strip(),
                    "citation": _citation(source, label_for)}

    return decline_without_search(FOLLOW_UP_UNGROUNDED)


def build_procedure_prompt(question: str, scenario_key: str, playbook: dict) -> str:
    """The Layer C `procedure` prompt (issue #17): the scenario's play, and the real quotes
    it was derived from.

    A NEW VARIANT. `build_prompt` and `build_playbook_prompt` are frozen against ADR 0001
    and are not touched. Note this is NOT `build_playbook_prompt`, which answers a CLIENT
    SITUATION with playbook moves as extra context and was measured at no lift. This one
    answers a question ABOUT the play, which that variant cannot do at all.

    MOVES ARE RENDERED WHOLE -- name, criterion and evidence together, never split into
    separate items. Measured: bundled criteria are credited more often (rho +0.35, p=0.001),
    and the "one statable thing per move" rule was WITHDRAWN on that measurement
    (`Brain/docs/findings/layer-d-say-arm.md` §14). Splitting them here would re-introduce a
    rule the pipeline already retired.

    `arc` is rendered as the ORDER, which is what it is -- a list of the move names in the
    sequence Naren tends to run them. `db/schema.sql` warns that `key_moves` order is
    load-bearing, so neither list is re-sorted.
    """
    lines = [
        'You are "Ask Naren", an internal Joveo tool that answers a CSM from what Naren '
        "actually does on real client calls.",
        "",
        "The CSM is asking about the GENERAL PLAY for a kind of situation, not about one "
        "client's words. Answer from the play below.",
        "",
        f"CSM's question: {question}",
        "",
        f"The play for this situation ({scenario_key}):",
        f"  When it applies: {playbook.get('situation_signature', '')}",
    ]

    arc = [step for step in (playbook.get("arc") or []) if str(step).strip()]
    if arc:
        lines += ["", "  The order Naren tends to run it in:"]
        lines += [f"    {n}. {step}" for n, step in enumerate(arc, 1)]

    lines += ["", "  The moves, each with what Naren really said:"]
    for n, move in enumerate(procedure_moves(playbook), 1):
        lines += [
            "",
            f"  [{n}] {move.get('name', '')}",
            f"      What it means: {move.get('criterion', '')}",
        ]
        for evidence in move.get("evidence") or []:
            lines += [
                f"      Naren said: {evidence.get('quote', '')}",
                f"      (call: {evidence.get('call', '')})",
            ]

    lines += [
        "",
        "Using ONLY the play above, tell the CSM what to do. Say what the moves are and "
        "what order to run them in. Do not invent a move that is not listed.",
        "",
        "Respond as JSON with exactly these keys:",
        '  "declined": boolean,',
        '  "answer": the coaching answer for the CSM (empty string if declined),',
        '  "quote": a verbatim substring copied from one of the "Naren said" lines above -- '
        "NOT from a move's name or from what it means, which are our words rather than his "
        "(empty string if declined),",
        '  "cited_call": the call identifier printed beside the quote you chose, copied '
        "exactly (empty string if declined).",
    ]
    return "\n".join(lines)


def answer_procedure(question: str, match: Match, playbook: dict, gateway, *,
                     label_for=citations.resolve_label) -> dict:
    """Answer "what is the general play for X" from the scenario's Layer C playbook.

    `match` is how the SCENARIO was chosen: the question is embedded and the nearest
    exchange's scenario is the one whose play gets answered. That is a retrieval, so unlike
    a follow-up this response reports its cosine -- and it is why the answer names its
    scenario, because a catch-all can absorb a question that is not really about it
    (`application_volume_and_prioritization` carries 11.8% of coachable pairs and 16% of
    what routes there is about jobs rather than applications).

    THE GATE IS THE SAME GATE, with a different source (issue #17): the quote must appear
    verbatim in one of the playbook's EVIDENCE quotes, not in a criterion. A criterion is
    model-written prose sitting in the prompt beside the real thing, so quoting it reads as
    grounded and is not -- which is the failure this path is most likely to produce.
    """
    if not (question or "").strip():
        raise ValueError("question is empty")

    scenario_key = match.pair["scenario_key"]
    # THE SAME MOVES THE PROMPT RENDERS, which is the whole point of routing both through
    # `procedure_moves`. A gate handed sources the prompt never showed would accept a quote
    # the model was not given -- and "what it cites must be something it was actually shown"
    # is half of what the gate means (`ask-naren/CONTEXT.md`). Two independent traversals of
    # this document is exactly how that guarantee rots.
    sources = grounding.from_playbook_evidence(move_evidence(procedure_moves(playbook)))
    if not sources:
        # NOT AN ANSWER AND NOT A DECLINE -- the caller degrades to Layer B, exactly as it
        # does for a scenario with no live playbook at all. A playbook whose moves carry no
        # quotable evidence cannot ground a Layer C answer, but the tool still knows what
        # Naren SAID in the closest real exchange, and this ticket's stated principle is
        # that a missing playbook degrades rather than fails. Returning None here rather
        # than generating also means the failure costs no gateway call.
        return None

    prompt = build_procedure_prompt(question, scenario_key, playbook)
    for _ in range(MAX_ATTEMPTS):
        payload, _meta = gateway.chat_json(
            prompt, model=CHAT_MODEL, reasoning_effort=REASONING_EFFORT,
            temperature=TEMPERATURE, max_tokens=MAX_TOKENS, no_cache=True)
        if payload.get("declined"):
            return _decline(NO_CLOSE_MATCH, match, 1, label_for)
        gate = grounding.check(payload, sources)
        if gate.passed:
            evidence = gate.source.payload
            return {
                "outcome": ANSWERED,
                "answer": payload["answer"].strip(),
                "quote": payload["quote"].strip(),
                # NO pair_id: a playbook evidence quote records the call it came from, not a
                # kb_pairs row. Inventing one would point an engineer at an exchange this
                # answer does not rest on.
                "citation": {
                    "label": label_for(evidence["call"]) or evidence["call"],
                    "call_filename": evidence["call"],
                    "scenario_key": scenario_key,
                },
                "match": _match_info(match, 1),
            }

    return _decline(GROUNDING_UNVERIFIED, match, 1, label_for)


def procedure_moves(playbook: dict) -> list[dict]:
    """The moves the `procedure` path answers from: `key_moves`, in order.

    ONE DEFINITION WITH TWO CONSUMERS -- the prompt renders these, and the gate's sources are
    built from these. It exists as a function rather than as two `playbook["key_moves"]`
    reads precisely so a later section cannot be added to one and forgotten in the other: a
    gate holding sources the prompt never showed silently drops the "cited something it was
    actually shown" half of the guarantee, which nothing downstream would catch.

    `signature_language` and `pitfalls_and_variants` are deliberately NOT here. They are
    issue #18's intents (`phrasing`, `pitfalls`), and neither has a prompt or a gate:
    #18 RENDERS both rather than generating them, so there is nothing for a request-time gate
    to check. Their quotes were verified offline instead -- `playbook_snap_trial.py` runs the
    verbatim snap over `signature_language` and each `pitfalls_and_variants[].evidence`, not
    only over `key_moves`. Keeping them out of this function is still the right call for the
    reason above: the prompt and the gate must traverse the same document once.

    Order is preserved: `db/schema.sql` records that `key_moves` order is load-bearing.
    """
    return list(playbook.get("key_moves") or [])


def move_evidence(moves: list[dict]) -> list[dict]:
    """Every evidence entry carried by these moves, flattened, in the order shown."""
    entries: list[dict] = []
    for move in moves:
        entries.extend(move.get("evidence") or [])
    return entries


def answer_situation(situation: str, pool: RetrievalPool, gateway, *, embed_query,
                     k: int = DEFAULT_K, label_for=citations.resolve_label,
                     moves_for=None) -> dict:
    """The one call the HTTP layer makes. Returns the response body itself.

    `embed_query` is passed in rather than imported so this module stays free of the
    embedder's disk-cache side effects -- which matter, because that cache holds a
    thread-bound sqlite connection (see ask_naren/service.py).

    `label_for` turns a call filename into the label a CSM reads (issue #4). Injected the
    same way `embed_query` is, rather than read from module state: resolving an opaque UUID
    call needs an index built from the recorded participant sidecars at startup, and that
    index is the caller's to own. The default resolves what the FILENAME alone states, which
    is everything `--ask` needs and degrades honestly where the corpus is absent.

    `moves_for` selects the PLAYBOOK-AUGMENTED variant (issue #5) and defaults to None,
    which is pairs-only -- the shipped path, byte-identical to what ADR 0001 measured. When
    supplied it is called with the grounded scenario's key and may return None, which is the
    ordinary case for a scenario with no live playbook (1 of 34) and degrades to pairs-only
    rather than failing. It is a CALLER-SUPPLIED function rather than a lookup here because
    the service holds no database handle while answering: the playbooks are read once at
    startup, like the pool.

    `k` is how many retrieved exchanges the model is shown. It defaults to DEFAULT_K == 1,
    which is the shipped path and the arm issue #7's 83% was measured on; issue #8 A/Bs
    k=5 against it. With k == 1 every step below reduces to what that measurement ran on.
    """
    if not (situation or "").strip():
        raise ValueError("situation is empty")

    query_vec = embed_query([situation])[0]
    candidates = pool.topk(query_vec, k)
    if not candidates:
        # Unreachable before ADR 0008: an exact in-memory search over a non-empty pool
        # always ranked its own rows. A store's ranking can now be entirely unauthorised,
        # and `pairs[0]` below would then raise a bare IndexError.
        #
        # DELIBERATELY NOT A DECLINE. A decline says "nothing close enough", which a CSM
        # reads as a fact about the corpus; this is a fact about the infrastructure -- the
        # index is missing this pool's vectors, or their scenario_key metadata is no longer
        # admitted by the search filter. Dressing it as no_close_match would hide a broken
        # index behind a normal-looking answer for as long as nobody checked, which is the
        # silent-failure shape the coverage guard exists to prevent.
        raise RuntimeError(
            "retrieval returned no kb_pair the pool authorises -- the vector store and the "
            "pool disagree about what exists. Run ops/check_vector_coverage.py.")
    pairs = [m.pair for m in candidates]
    # The playbook variant is defined for the SINGLE-candidate path, which is what ADR
    # 0001 measured and what ships. Combining a shortlist with playbook moves is a prompt
    # nobody has evaluated, so k > 1 uses the shortlist prompt and ignores moves rather than
    # inventing a third variant at request time. Both switches are off by default, so this
    # combination cannot arise in production.
    moves = moves_for(pairs[0]["scenario_key"]) if moves_for and len(pairs) == 1 else None
    if len(pairs) > 1:
        prompt = build_candidates_prompt(situation, pairs)
    elif moves:
        prompt = build_playbook_prompt(situation, pairs[0], moves)
    else:
        prompt = build_prompt(situation, pairs[0])

    for _ in range(MAX_ATTEMPTS):
        payload, _meta = gateway.chat_json(
            prompt,
            model=CHAT_MODEL,
            reasoning_effort=REASONING_EFFORT,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            # The gateway caches chat completions by default -- verified byte-identical
            # across calls that look like fresh generations. A CSM-facing answer must never
            # be an echo of another CSM's question.
            no_cache=True,
        )
        if payload.get("declined"):
            return _decline(NO_CLOSE_MATCH, candidates[0], 1, label_for)
        gate = grounding.check(payload, grounding.from_pairs(pairs))
        if gate.passed:
            # Identity, not equality: two candidates can hold equal dicts, and resolving by
            # value would report whichever compared equal first rather than the exchange the
            # gate actually verified the quote against.
            rank = next(i for i, m in enumerate(candidates, 1)
                        if m.pair is gate.source.payload)
            return _answer(payload, candidates[rank - 1], rank, label_for)

    # Deliberately NOT the last payload with a warning attached: an ungrounded answer must
    # not reach the caller in any field, or the gate is advisory rather than a gate.
    return _decline(GROUNDING_UNVERIFIED, candidates[0], 1, label_for)


def clarify(question: str) -> dict:
    """A question back to the CSM instead of an answer, decided BEFORE retrieval -- so
    nothing has been searched and there is nothing to be grounded in (ask-naren/CONTEXT.md).

    Carries NO answer, quote or citation key, and that is structural rather than tidiness:
    the guarantee is that unverified text never reaches a CSM in ANY field, and a shape with
    no such field cannot leak one even by mistake.

    Produced by `responding.respond` when intake decides the message lacks the client's
    own words (issue #14). It lives here, beside the other response builders, so the
    contract is defined in one place.
    """
    if not (question or "").strip():
        raise ValueError("a clarify with no question is a dead end, not a clarify")
    return {"outcome": CLARIFY, "question": question.strip()}


#: Reasons a request can be declined on a path where NO SEARCH RAN AT ALL. Only these may
#: reach `decline_without_search` -- see the guard there for why the allowlist exists.
#:
#: NAMED FOR THE PROPERTY, NOT FOR THE TIMING. `out_of_scope` is decided before a
#: generation and `follow_up_ungrounded` after one, so "pre-retrieval" described only half
#: of it. What both share, and what the allowlist actually protects, is that nothing was
#: searched -- so there is no cosine to report and no rank to report it at.
NO_SEARCH_REASONS = frozenset({OUT_OF_SCOPE, FOLLOW_UP_UNGROUNDED})


def decline_without_search(reason: str) -> dict:
    """A decline on a path that searched nothing -- `out_of_scope`, or a follow-up whose
    answer could not be grounded in the exchange the thread carried.

    Carries NO `match`, deliberately. Every other decline records how close the match it
    turned down actually was, because decline-rate calibration is deferred to real usage and
    is only answerable later if each decline says that. This one searched nothing, so there
    is no match to report and inventing one would put a fabricated cosine into that record.

    THE ALLOWLIST IS THE POINT, not defensive habit. Called with `NO_CLOSE_MATCH` this would
    happily emit a searched-for reason with no match attached -- silently defeating the very
    invariant the paragraph above defends, in the one direction nothing else would catch. A
    new no-search reason must be added to NO_SEARCH_REASONS deliberately.
    """
    if reason not in NO_SEARCH_REASONS:
        raise ValueError(
            f"{reason!r} comes from a path that SEARCHED, so it has a match to report. Use "
            f"_decline, or add it to NO_SEARCH_REASONS if it genuinely has none.")
    return {"outcome": DECLINED, "reason": reason, "message": _MESSAGES[reason]}


def _answer(payload: dict, match: Match, rank: int, label_for) -> dict:
    return {
        "outcome": ANSWERED,
        "answer": payload["answer"].strip(),
        "quote": payload["quote"].strip(),
        "citation": _citation(match.pair, label_for),
        "match": _match_info(match, rank),
    }


def _decline(reason: str, match: Match, rank: int, label_for) -> dict:
    return {
        "outcome": DECLINED,
        "reason": reason,
        "message": _MESSAGES[reason],
        # Recorded even on a decline: the spec defers decline-rate calibration to real
        # usage, and that is only answerable later if each decline says how close the match
        # it turned down actually was. On a decline this is the NEAREST candidate (rank 1);
        # no single candidate was chosen, so there is no grounded one to report.
        "match": _match_info(match, rank),
    }


def _match_info(match: Match, rank: int) -> dict:
    """Describes the exchange the answer actually rests on -- which under a shortlist is
    frequently not the nearest one. `rank` is its position in the shortlist, and is what
    makes "the useful moment was at rank 3" observable instead of inferred; issue #8's
    per-item analysis reads it directly."""
    return {"cosine": match.cosine, "scenario_key": match.pair["scenario_key"],
            "rank": rank}

def _citation(pair: dict, label_for) -> dict:
    """Unredacted per ADR 0002, and resolvable back to its exact source rows.

    `label` is what a CSM reads: an account and a date where the recorded data states them
    unambiguously, else the raw filename (ask_naren/citations.py). It is a SEPARATE key from
    `call_filename` precisely so resolving it was not a shape change for any caller -- and so
    the raw identifier stays available to an engineer tracing a bad answer, which is what
    pair_id and call_filename are for.
    """
    return {
        "label": label_for(pair["call_filename"]) or pair["call_filename"],
        "call_filename": pair["call_filename"],
        "pair_id": pair["pair_id"],
        "scenario_key": pair["scenario_key"],
    }
