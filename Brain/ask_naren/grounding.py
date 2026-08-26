"""The grounding gate (see ask-naren/CONTEXT.md): the check every Ask Naren answer passes
before a CSM sees it.

WHY THIS IS A RUNTIME GATE AND NOT A SCORE. The prototype eval measured `quote_verbatim`
offline and found it at or near 100% -- which is a statistic about a sample, not a property
of the next answer. ADR 0002 says every answer cites the specific past call it paraphrases;
that only holds if an answer failing this check cannot be shown at all. Layer D learned the
same lesson the expensive way: 23% of credited quotes in the 2026-08-15 call-level trial
could not be located in the transcript, some traced to transcripts the model was never
shown, and the trial was rejected by its own gate.

Verification reuses layer_d/verify_quotes.py rather than reimplementing containment. That
module's normalization (case, punctuation, whitespace -- no stemming, no synonyms) is
already Brain's settled answer to "how may a quote differ from its source without differing
in content", and it is the same rule that shipped the playbook citations.
"""
from __future__ import annotations

from dataclasses import dataclass

from layer_d.verify_quotes import verify_quote

# Containment, not fuzzy alignment. verify_quote returns 1.0 on containment and a
# SequenceMatcher ratio otherwise, so a 1.0 bar admits exactly the quotes that genuinely
# appear in the source -- matching the prototype's offline `quote_verbatim` check, which is
# what the eval behind ADR 0001 actually measured. Anything lower would admit paraphrase,
# and paraphrase-that-reads-as-a-quote is the failure this gate exists to stop.
QUOTE_MIN_OVERLAP = 1.0

@dataclass(frozen=True)
class GateResult:
    passed: bool
    reason: str = ""       # "" when passed; a stable machine-readable cause otherwise
    # On a pass, the ONE candidate the quote verified against. The caller cites this pair,
    # not the nearest-ranked one -- with a shortlist those are frequently not the same pair,
    # and citing rank 1 regardless would point a CSM at a call the answer does not come
    # from while every gate metric still reported a pass.
    pair: dict | None = None


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def check(model_json: dict, candidates: list[dict]) -> GateResult:
    """Does this generated payload rest on one of the exchanges it was actually given?

    `candidates` is the shortlist the prompt showed, nearest first -- a ONE-element list on
    the shipped rank-1 path, which is why widening this signature does not change that
    path's behaviour: with one candidate the checks below reduce exactly to the previous
    equality-plus-containment pair, in the same order, with the same reasons.

    Fails closed on every malformed shape: a missing key, a blank quote and a blank answer
    are all refusals, never "nothing to check".

    Two candidates CAN share a call_filename -- dedup is keyed on content, so two different
    exchanges from the same call both survive the pool (tests/test_ask_naren_retrieval.py
    pins that). So cited_call does not always identify a single exchange, and the tie is
    broken by which candidate's reply the quote actually verifies against rather than by
    rank: rank would resolve ambiguity in favour of the pair the model may not have used.
    """
    if not _norm(model_json.get("answer")):
        return GateResult(False, "empty_answer")

    cited = _norm(model_json.get("cited_call"))
    named = [c for c in candidates if _norm(c["call_filename"]) == cited]
    if not named:
        return GateResult(False, "wrong_call_cited")

    quote = model_json.get("quote") or ""
    for candidate in named:
        if verify_quote(quote, candidate["response_text"], QUOTE_MIN_OVERLAP).verified:
            return GateResult(True, pair=candidate)

    return GateResult(False, "quote_not_verbatim")
