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

# NER-enabled pass -- v1/layer_b.py's own _nlp disables NER for speed in
# _is_substantive; that path is untouched, this is an additional narrow pass.
# Parser stays disabled on cost grounds (noun-chunk detection is out of scope).
_nlp_ner = spacy.load("en_core_web_lg", disable=["parser"])


def concrete_entity_density(text: str) -> float:
    """Named-entity count (spaCy NER) normalized by content-word count.
    Higher = more concrete/specific (names, numbers, tools, places);
    lower = more generic. Returns 0.0 for text with no content words at all."""
    doc = _nlp_ner(text)
    content_words = [t for t in doc if t.is_alpha and not t.is_stop]
    if not content_words:
        return 0.0
    return len(doc.ents) / len(content_words)
