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
class GroundingSource:
    """One thing an answer is allowed to rest on (`ask-naren/CONTEXT.md`, issue #17).

    THERE IS ONE GATE; WHAT VARIES BETWEEN ANSWER PATHS IS THE SOURCE. A Layer B answer
    grounds in a matched `kb_pair`'s response text. A Layer C answer grounds in a playbook's
    evidence quotes. Both reduce to the same two questions -- did the model cite something it
    was actually shown, and does its quote really appear in that thing -- so both go through
    the same `check` rather than through a second gate that could drift from this one.

    `identifier` is what the model's `cited_call` must name. It is a call filename on both
    paths today, because a playbook's evidence quotes each record the call they came from --
    which is why generalising the gate did not need a new field in the model's JSON contract.

    `payload` is whatever the CALLER needs back when this source is the one that verified: a
    `kb_pair` row on the Layer B path, a playbook move on the Layer C path. The gate never
    looks inside it.
    """
    identifier: str
    text: str
    payload: dict


def from_pairs(pairs: list[dict]) -> list[GroundingSource]:
    """The Layer B sources: the retrieved exchanges the prompt showed."""
    return [GroundingSource(identifier=p["call_filename"], text=p["response_text"],
                            payload=p) for p in pairs]


def from_playbook_evidence(entries: list[dict]) -> list[GroundingSource]:
    """The Layer C sources: every evidence quote the playbook document carries.

    An entry is a playbook `evidence` item -- `{quote, call, account}` -- flattened out of
    whichever section it came from. Each quote is its own source rather than the section
    being one big source, because the gate must be able to say WHICH quote an answer rests
    on, exactly as it says which exchange on the Layer B path.
    """
    return [GroundingSource(identifier=e["call"], text=e["quote"], payload=e)
            for e in entries if (e.get("quote") or "").strip()]


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reason: str = ""       # "" when passed; a stable machine-readable cause otherwise
    # On a pass, the ONE source the quote verified against. The caller cites this source,
    # not the nearest-ranked one -- with a shortlist those are frequently not the same, and
    # citing rank 1 regardless would point a CSM at a call the answer does not come from
    # while every gate metric still reported a pass.
    source: GroundingSource | None = None


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def check(model_json: dict, sources: list[GroundingSource]) -> GateResult:
    """Does this generated payload rest on one of the sources it was actually given?

    `sources` is what the prompt showed, in the order it showed them -- a ONE-element list on
    the shipped rank-1 Layer B path, which is why widening this signature does not change
    that path's behaviour: with one source the checks below reduce exactly to the previous
    equality-plus-containment pair, in the same order, with the same reasons.

    Fails closed on every malformed shape: a missing key, a blank quote and a blank answer
    are all refusals, never "nothing to check".

    Two sources CAN share an identifier. On the Layer B path dedup is keyed on content, so
    two different exchanges from the same call both survive the pool
    (tests/test_ask_naren_retrieval.py pins that); on the Layer C path one call routinely
    supplies evidence for several moves. So `cited_call` does not always identify a single
    source, and the tie is broken by which source's TEXT the quote actually verifies against
    rather than by order: order would resolve ambiguity in favour of the source the model may
    not have used.
    """
    if not _norm(model_json.get("answer")):
        return GateResult(False, "empty_answer")

    cited = _norm(model_json.get("cited_call"))
    named = [s for s in sources if _norm(s.identifier) == cited]
    if not named:
        return GateResult(False, "wrong_call_cited")

    quote = model_json.get("quote") or ""
    for source in named:
        if verify_quote(quote, source.text, QUOTE_MIN_OVERLAP).verified:
            return GateResult(True, source=source)

    return GateResult(False, "quote_not_verbatim")
