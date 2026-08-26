"""Situation in, grounded answer or decline out -- Ask Naren's whole request path.

The prompt is the one the prototype eval validated (ask-naren/prototype/
eval_pairs_vs_playbook.py `_build_prompt`), in its pairs-only form: ADR 0001 measured no
lift from adding the scenario's Layer C playbook, so the playbook-augmented prompt is not
built here (issue #5 adds it behind internal config, off by default).

Nothing here talks to Postgres. The pool arrives already loaded, deduped and embedded; this
module embeds only the incoming situation, generates, and applies the grounding gate.
"""
from __future__ import annotations

from ask_naren import grounding
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

NO_CLOSE_MATCH = "no_close_match"
GROUNDING_UNVERIFIED = "grounding_unverified"

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


def answer_situation(situation: str, pool: RetrievalPool, gateway, *, embed_query,
                     k: int = DEFAULT_K) -> dict:
    """The one call the HTTP layer makes. Returns the response body itself.

    `embed_query` is passed in rather than imported so this module stays free of the
    embedder's disk-cache side effects -- which matter, because that cache holds a
    thread-bound sqlite connection (see ask_naren/service.py).

    `k` is how many retrieved exchanges the model is shown. It defaults to DEFAULT_K == 1,
    which is the shipped path and the arm issue #7's 83% was measured on; issue #8 A/Bs
    k=5 against it. With k == 1 every step below reduces to what that measurement ran on.
    """
    if not (situation or "").strip():
        raise ValueError("situation is empty")

    query_vec = embed_query([situation])[0]
    candidates = pool.topk(query_vec, k)
    pairs = [m.pair for m in candidates]
    prompt = (build_prompt(situation, pairs[0]) if len(pairs) == 1
              else build_candidates_prompt(situation, pairs))

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
            return _decline(NO_CLOSE_MATCH, candidates[0], 1)
        gate = grounding.check(payload, pairs)
        if gate.passed:
            # Identity, not equality: two candidates can hold equal dicts, and resolving by
            # value would report whichever compared equal first rather than the exchange the
            # gate actually verified the quote against.
            rank = next(i for i, m in enumerate(candidates, 1) if m.pair is gate.pair)
            return _answer(payload, candidates[rank - 1], rank)

    # Deliberately NOT the last payload with a warning attached: an ungrounded answer must
    # not reach the caller in any field, or the gate is advisory rather than a gate.
    return _decline(GROUNDING_UNVERIFIED, candidates[0], 1)


def _answer(payload: dict, match: Match, rank: int) -> dict:
    return {
        "declined": False,
        "answer": payload["answer"].strip(),
        "quote": payload["quote"].strip(),
        "citation": _citation(match.pair),
        "match": _match_info(match, rank),
    }


def _decline(reason: str, match: Match, rank: int) -> dict:
    return {
        "declined": True,
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

def _citation(pair: dict) -> dict:
    """Unredacted per ADR 0002, and resolvable back to its exact source rows.

    `label` is what a CSM reads and is the raw filename for now; issue #4 resolves it to an
    account and a date. It is a separate key from `call_filename` so that resolution is not
    a shape change for every caller -- and so the raw identifier stays available to an
    engineer tracing a bad answer, which is what pair_id and call_filename are for.
    """
    return {
        "label": pair["call_filename"],
        "call_filename": pair["call_filename"],
        "pair_id": pair["pair_id"],
        "scenario_key": pair["scenario_key"],
    }
