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


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def check(model_json: dict, matched_pair: dict) -> GateResult:
    """Does this generated payload rest on the exchange it was actually given?

    Fails closed on every malformed shape: a missing key, a blank quote and a blank answer
    are all refusals, never "nothing to check".
    """
    if not _norm(model_json.get("answer")):
        return GateResult(False, "empty_answer")

    if _norm(model_json.get("cited_call")) != _norm(matched_pair["call_filename"]):
        return GateResult(False, "wrong_call_cited")

    quote = model_json.get("quote") or ""
    if not verify_quote(quote, matched_pair["response_text"], QUOTE_MIN_OVERLAP).verified:
        return GateResult(False, "quote_not_verbatim")

    return GateResult(True)
