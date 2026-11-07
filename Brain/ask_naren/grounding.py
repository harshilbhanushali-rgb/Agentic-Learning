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

#: A quote is re-cited to a shown call OTHER than the one the model named only when it is at
#: least this many words. A short phrase ("we can do that") sits in many calls by coincidence,
#: so finding it elsewhere says nothing about where the answer came from. Every one of the
#: 205 answered quotes in the 2026-11-06/07 golden and held-out runs was 18 words or more.
MIN_CORRECTED_QUOTE_WORDS = 8

@dataclass(frozen=True)
class GroundingSource:
    """One thing an answer is allowed to rest on (`ask-naren/CONTEXT.md`, issue #17).

    THERE IS ONE GATE; WHAT VARIES BETWEEN ANSWER PATHS IS THE SOURCE. A Layer B answer
    grounds in a matched `kb_pair`'s response text. A Layer C answer grounds in a playbook's
    evidence quotes. Both reduce to the same two questions -- did the model cite something it
    was actually shown, and does its quote really appear in that thing -- so both go through
    the same `check` rather than through a second gate that could drift from this one.

    `identifier` is what the model's `cited_call` names -- and, since 2026-11-07, what the
    answer is cited to when the quote turns out to be in a different shown source than the
    one named (`check`). It is a call filename on both
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

    AN ENTRY MISSING EITHER FIELD IS DROPPED, not read defensively into a broken source.
    These come from a model-authored jsonb document, so a missing key is a real shape rather
    than a hypothetical: without a `quote` the containment check is trivially true for
    anything, and without a `call` there is no identifier for the model to cite, so the
    source could never be selected and would only pad the list. Dropping them means a
    playbook whose evidence is entirely malformed produces NO sources -- which the caller
    already turns into an honest decline rather than a 500.
    """
    return [GroundingSource(identifier=(e.get("call") or "").strip(),
                            text=e["quote"], payload=e)
            for e in entries
            if (e.get("quote") or "").strip() and (e.get("call") or "").strip()]


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reason: str = ""       # "" when passed; a stable machine-readable cause otherwise
    # On a pass, the ONE source the quote verified against. The caller cites this source,
    # not the nearest-ranked one -- with a shortlist those are frequently not the same, and
    # citing rank 1 regardless would point a CSM at a call the answer does not come from
    # while every gate metric still reported a pass.
    source: GroundingSource | None = None
    # True when the quote verified in a shown source OTHER than the call the model named, so
    # the citation was corrected to where the words really are (`check`, 2026-11-07).
    corrected: bool = False


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def call_key(name: str | None) -> str:
    """A call's identity for matching a name the model wrote against a source shown to it:
    case, spacing and a trailing `.txt` ignored. Exchanges carry `call_filename` WITH `.txt`,
    playbook evidence records `call` WITHOUT it, and the writer -- shown both -- names
    evidence calls with the extension (3 of 18 tries, 2026-11-06). That is the right call
    named in the other spelling, not a citation slip."""
    norm = _norm(name)
    return norm[:-4] if norm.endswith(".txt") else norm


def explain_failure(model_json: dict, sources: list[GroundingSource]) -> dict:
    """Why a payload failed `check`, as one loggable record. Never changes a verdict.

    Added 2026-11-06: golden-set runs kept losing answers to `grounding_unverified` and the
    server recorded nothing about why, so each drop needed an in-process rerun to diagnose.
    The two fields that settle most cases: whether the cited call was among those shown,
    and which shown call (if any) actually contains the quote -- a quote verbatim in a
    DIFFERENT call than the one cited is a citation slip, not an invented quote.
    """
    quote = model_json.get("quote") or ""
    cited = call_key(model_json.get("cited_call"))
    named = [s for s in sources if call_key(s.identifier) == cited]
    best = max((verify_quote(quote, s.text, QUOTE_MIN_OVERLAP).score for s in named),
               default=0.0)
    found_in = next((s.identifier for s in sources
                     if verify_quote(quote, s.text, QUOTE_MIN_OVERLAP).verified), None)
    return {"cited_call": model_json.get("cited_call") or "",
            "cited_was_shown": bool(named),
            "quote_chars": len(quote.strip()),
            "best_overlap_in_cited": round(best, 3),
            "quote_verbatim_in": found_in,
            "quote_start": " ".join(quote.split())[:80],
            "sources_shown": len(sources)}


def check(model_json: dict, sources: list[GroundingSource]) -> GateResult:
    """Does this generated payload rest on one of the sources it was actually given?

    THE RULE SINCE 2026-11-07: the quote must be verbatim in a source the prompt SHOWED, and
    the answer is cited to the source it is actually in. Before, it had to be verbatim in
    the call the model NAMED, and a quote verbatim in a different shown call was refused --
    which threw away real answers over a citation slip (the writer naming a playbook call
    with `.txt` added, or quoting exchange B under exchange A's call, both measured on the
    golden set). The guarantee a CSM relies on is unchanged: the quote is Naren's real words
    and the citation points at the call they are in. What is given up is only the check
    that the MODEL knew which call that was; `corrected` records each time it did not. A
    quote shorter than `MIN_CORRECTED_QUOTE_WORDS` is never re-cited: it must be in the call
    named, as before. A name differing only in `.txt` is the call named (`call_key`).

    `sources` is what the prompt showed, in the order it showed them -- a ONE-element list on
    the shipped rank-1 Layer B path, where a wrong `cited_call` over a verbatim quote now
    passes cited to that one source.

    Fails closed on every malformed shape: a missing key, a blank quote and a blank answer
    are all refusals, never "nothing to check".

    Two sources CAN share an identifier (dedup is keyed on content, and one call supplies
    evidence for several playbook moves), and a short quote can appear in more than one
    source. So the sources the model NAMED are tried first, and among any group the tie is
    broken by which source's TEXT the quote verifies against, then by the order shown.

    Reasons on a refusal: `wrong_call_cited` when the named call was not shown at all,
    `quote_not_verbatim` when it was -- either way the quote is in no shown source.
    """
    if not _norm(model_json.get("answer")):
        return GateResult(False, "empty_answer")

    cited = call_key(model_json.get("cited_call"))
    named = [s for s in sources if call_key(s.identifier) == cited]
    others = [s for s in sources if call_key(s.identifier) != cited]

    quote = model_json.get("quote") or ""
    groups = [(named, False)]
    if len(quote.split()) >= MIN_CORRECTED_QUOTE_WORDS:
        groups.append((others, True))
    for group, corrected in groups:
        for source in group:
            if verify_quote(quote, source.text, QUOTE_MIN_OVERLAP).verified:
                return GateResult(True, source=source, corrected=corrected)

    return GateResult(False, "quote_not_verbatim" if named else "wrong_call_cited")
