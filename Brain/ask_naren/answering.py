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
