"""Pure, testable signals for judging trigger/response content quality --
shared by the sink-rescue design (docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md,
Status update 3) and the trigger-quality-gate design
(docs/superpowers/specs/2026-08-04-layer-b-trigger-quality-gate-design.md).
No I/O, no Gemma, no DB -- same style as shared/cluster_evidence.py.

Whichever design is implemented first creates this file; the other imports it
unchanged -- do not re-author it a second time.
"""
from __future__ import annotations

import numpy as np
import spacy

from preprocessing.transcript_parser import SpeakerRole, Turn

# NER-enabled pass -- v1/layer_b.py's own _nlp disables NER for speed in
# _is_substantive; that path is untouched, this is an additional narrow pass.
# Parser stays disabled on cost grounds (noun-chunk detection is out of scope).
_nlp_ner = spacy.load("en_core_web_lg", disable=["parser"])

_WH_TAGS = {"WDT", "WP", "WP$", "WRB"}


def concrete_entity_density(text: str) -> float:
    """Named-entity count (spaCy NER) normalized by content-word count.
    Higher = more concrete/specific (names, numbers, tools, places);
    lower = more generic. Returns 0.0 for text with no content words at all."""
    doc = _nlp_ner(text)
    content_words = [t for t in doc if t.is_alpha and not t.is_stop]
    if not content_words:
        return 0.0
    return len(doc.ents) / len(content_words)


def preceding_turn_is_question(turns: list[Turn], turn_index: int) -> bool:
    """True if the NAREN turn immediately before turn_index ends in '?' or
    opens with a WH-word/auxiliary verb -- grammatical categories via spaCy's
    own tagger, not a curated content word list. False if turn_index is 0 or
    the prior turn isn't NAREN."""
    if turn_index <= 0:
        return False
    prev = turns[turn_index - 1]
    if prev.role != SpeakerRole.NAREN:
        return False
    text = prev.text.strip()
    if not text:
        return False
    if text.endswith("?"):
        return True
    doc = _nlp_ner(text)
    if len(doc) == 0:
        return False
    first = doc[0]
    return first.tag_ in _WH_TAGS or first.pos_ == "AUX"


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-10)


def sink_real_margin(
    trigger_vec: list[float],
    sink_centroids: list[list[float]],
    real_centroids: list[list[float]],
) -> float:
    """max(cos(trigger, sink)) - max(cos(trigger, real)). Higher = more
    filler-like. Not consumed by the sink-rescue gate -- specified here for
    module completeness; the trigger-quality-gate design's drop decision uses it."""
    t = _unit(np.array(trigger_vec))
    sink_sims = [float(t @ _unit(np.array(c))) for c in sink_centroids]
    real_sims = [float(t @ _unit(np.array(c))) for c in real_centroids]
    return max(sink_sims) - max(real_sims)


def trigger_response_coupling(trigger_vec: list[float], response_vec: list[float]) -> float:
    """Plain cosine between a pair's own trigger and response embeddings.
    Not consumed by the sink-rescue gate -- available for the
    trigger-quality-gate design's combining logic."""
    return float(_unit(np.array(trigger_vec)) @ _unit(np.array(response_vec)))
