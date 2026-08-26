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


def answer_situation(situation: str, pool: RetrievalPool, gateway, *, embed_query) -> dict:
    """The one call the HTTP layer makes. Returns the response body itself.

    `embed_query` is passed in rather than imported so this module stays free of the
    embedder's disk-cache side effects -- which matter, because that cache holds a
    thread-bound sqlite connection (see ask_naren/service.py).
    """
    if not (situation or "").strip():
        raise ValueError("situation is empty")

    query_vec = embed_query([situation])[0]
    match = pool.top1(query_vec)
    prompt = build_prompt(situation, match.pair)

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
            return _decline(NO_CLOSE_MATCH, match)
        if grounding.check(payload, match.pair).passed:
            return _answer(payload, match)

    # Deliberately NOT the last payload with a warning attached: an ungrounded answer must
    # not reach the caller in any field, or the gate is advisory rather than a gate.
    return _decline(GROUNDING_UNVERIFIED, match)


def _answer(payload: dict, match: Match) -> dict:
    return {
        "declined": False,
        "answer": payload["answer"].strip(),
        "quote": payload["quote"].strip(),
        "citation": _citation(match.pair),
        "match": _match_info(match),
    }


def _decline(reason: str, match: Match) -> dict:
    return {
        "declined": True,
        "reason": reason,
        "message": _MESSAGES[reason],
        # Recorded even on a decline: the spec defers decline-rate calibration to real
        # usage, and that is only answerable later if each decline says how close the match
        # it turned down actually was.
        "match": _match_info(match),
    }


def _match_info(match: Match) -> dict:
    return {"cosine": match.cosine, "scenario_key": match.pair["scenario_key"]}


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
