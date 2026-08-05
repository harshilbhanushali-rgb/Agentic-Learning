"""Non-embedding signals for judging trigger/response quality.

Shared between docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md
(Status update 3) and 2026-08-04-layer-b-trigger-quality-gate-design.md --
whichever design's code lands first owns this module, the other imports it.

Built after two rounds of cosine-floor-based rescue strategies in layer_b.py
failed to separate real content from junk (see the sink-rescue design's status
updates 1-2): centroid similarity measures topical resemblance, not content
specificity. These functions look at what's literally in the text, or at
conversational structure, instead.
"""
from __future__ import annotations

import numpy as np
import spacy

from preprocessing.transcript_parser import SpeakerRole, Turn

_nlp = spacy.load("en_core_web_lg")

_WH_TAGS = {"WDT", "WP", "WP$", "WRB"}


def content_word_count(text: str) -> int:
    """Non-stop, alphabetic token count -- the same content-word definition
    concrete_content_density divides by, exposed standalone so the gate's
    minimum-length guard doesn't need to compute a density ratio just to
    check length.
    """
    doc = _nlp(text)
    return sum(1 for t in doc if t.is_alpha and not t.is_stop)


def concrete_content_density(text: str) -> float:
    """(named_entity_count + noun_chunk_count) / content_word_count.

    noun_chunk_count excludes chunks whose root is a bare pronoun (e.g. "I",
    "that", "me") -- spaCy counts these as noun chunks, but measured directly
    against real filler text ("Yeah, I think so. Sounds good to me.") they
    inflated density to 0.5, comparable to genuinely specific content. See
    the design docs for the measured before/after this exclusion.

    Requires NER and the dependency parser enabled, unlike v1/layer_b.py's
    own _nlp (which disables both for speed in _is_substantive) -- this is a
    separate, narrower pass over already-extracted candidate pairs' text,
    not the corpus-wide clause pool Layer A/C process.
    """
    doc = _nlp(text)
    content_words = [t for t in doc if t.is_alpha and not t.is_stop]
    if not content_words:
        return 0.0
    entity_count = len(doc.ents)
    chunk_count = sum(1 for c in doc.noun_chunks if c.root.pos_ != "PRON")
    return (entity_count + chunk_count) / len(content_words)


def preceding_turn_is_question(turns: list[Turn], turn_index: int) -> bool:
    """True if turns[turn_index - 1] is a NAREN turn ending in '?' or opening
    with a closed-class interrogative word or auxiliary-inversion (a
    grammatical category, not a curated content list). False if the prior
    turn isn't NAREN, or there is no prior turn. Trigger-side only --
    irrelevant to the response.
    """
    if turn_index <= 0:
        return False
    prior = turns[turn_index - 1]
    if prior.role != SpeakerRole.NAREN:
        return False
    text = prior.text.strip()
    if text.endswith("?"):
        return True
    doc = _nlp(text)
    if len(doc) == 0:
        return False
    first = doc[0]
    return first.tag_ in _WH_TAGS or first.pos_ == "AUX"


def sink_real_margin(
    trigger_vec: np.ndarray,
    sink_centroids: np.ndarray,
    real_centroids: np.ndarray,
) -> float:
    """max(cos(trigger, sink centroids)) - max(cos(trigger, real centroids)).
    Higher = more filler-like. Not consumed by the sink-rescue design's
    gate -- the trigger-quality-gate design's own drop decision depends on it.
    """
    if sink_centroids.shape[0] == 0:
        raise ValueError("sink_centroids must not be empty")
    if real_centroids.shape[0] == 0:
        raise ValueError("real_centroids must not be empty")
    t = trigger_vec / (np.linalg.norm(trigger_vec) + 1e-10)
    sinks = sink_centroids / (np.linalg.norm(sink_centroids, axis=1, keepdims=True) + 1e-10)
    reals = real_centroids / (np.linalg.norm(real_centroids, axis=1, keepdims=True) + 1e-10)
    return float(np.max(sinks @ t) - np.max(reals @ t))


def trigger_response_coupling(trigger_vec: np.ndarray, response_vec: np.ndarray) -> float:
    """Plain cosine between a pair's own trigger and response embeddings. Not
    consumed by the sink-rescue design's gate -- available for the
    trigger-quality-gate design's combining logic.
    """
    t = trigger_vec / (np.linalg.norm(trigger_vec) + 1e-10)
    r = response_vec / (np.linalg.norm(response_vec) + 1e-10)
    return float(np.dot(t, r))
