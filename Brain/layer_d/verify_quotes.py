"""Programmatic quote verification -- the piece of the call-level trial that survived.

The call-level scoring trial (2026-08-15) was rejected by its own gate after 23% of
credited quotes could not be located in the transcript, including quotes traced to
OTHER transcripts the model was never shown. The free, model-free check that caught
that is now a production gate: a grader credit whose quote does not verify against
the CSM's actual response text is REFUSED (downgraded to unscored, never counted).

Alignment follows calibration/playbook_snap_trial.py's frozen best_span rule
(SequenceMatcher over normalized text), which already shipped the playbook citations.
Pure: no I/O, no tuning reads -- callers pass min_overlap in.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QuoteCheck:
    verified: bool
    score: float          # 1.0 on containment, else best_span ratio
    span: str             # the matched source span ("" when nothing matched)


def norm_quote(text: str) -> str:
    """Case/punctuation/whitespace-insensitive form, same intent as
    ego_trap.signal_check._norm: removes only the ways a quote can differ from its
    source WITHOUT differing in content. No stemming, no synonyms."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def best_span(quote: str, text: str) -> tuple[float, str]:
    """Minimal span of `text` covering every non-empty matching block against `quote`,
    scored by SequenceMatcher ratio. Deterministic. Verbatim rule from
    calibration/playbook_snap_trial.best_span (autojunk off for the same reason:
    autojunk silently disables matching on repeated short tokens, which conversational
    text is full of)."""
    sm = difflib.SequenceMatcher(None, quote, text, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    if not blocks:
        return 0.0, ""
    span = text[blocks[0].b: blocks[-1].b + blocks[-1].size]
    return difflib.SequenceMatcher(None, quote, span).ratio(), span


def verify_quote(quote: str, source_text: str, min_overlap: float) -> QuoteCheck:
    """Does `quote` genuinely appear in `source_text`?

    Containment on the normalized forms verifies outright (score 1.0). Otherwise the
    best aligned span must reach min_overlap. An empty quote NEVER verifies: a credit
    with no evidence is exactly what this gate exists to refuse.
    """
    q = norm_quote(quote)
    if not q:
        return QuoteCheck(False, 0.0, "")
    s = norm_quote(source_text)
    if not s:
        return QuoteCheck(False, 0.0, "")
    if q in s:
        return QuoteCheck(True, 1.0, quote.strip())
    score, span = best_span(q, s)
    return QuoteCheck(score >= min_overlap, score, span)
