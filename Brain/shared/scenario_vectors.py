"""Embedding of scenario descriptions, shared by Layer B and Layer C.

Layer B matches client triggers against these vectors; Layer C measures whether a
response clause is even relevant to the scenario it was filed under. Both must
embed the description identically or the two stages disagree about what a
scenario means, so there is exactly one definition of "the scenario vector" and
it lives here.

Embeddings go through the disk cache, so the same description is encoded once per
run no matter how many stages ask for it.
"""
from __future__ import annotations

import logging

from preprocessing import embedder
from shared.tuning import get_tuning

_logger = logging.getLogger(__name__)

# `layer_a.scenario_vector_mode` -- which REGISTER of a scenario's text is embedded.
#   concat      business_description + keyphrases. THE DEFAULT AND WHAT SHIPS.
#   keyphrases  the client's own wording alone.
#   prose       the analyst description alone.
MODES = ("concat", "keyphrases", "prose")


def _resolve_mode(mode: str | None) -> str:
    """Read the mode ONCE per batch, never per scenario, and never at import time.

    Import-time config reads are how `ego_trap/settings.py` came to hold a value that read
    as authoritative while doing nothing. `get_tuning()` is the process-wide singleton, so
    resolving here costs nothing after the first call.
    """
    resolved = get_tuning().layer_a.scenario_vector_mode if mode is None else mode
    if resolved not in MODES:
        raise ValueError(f"scenario_vector_mode must be one of {MODES}, got {resolved!r}")
    return resolved


def scenario_text(info: dict, mode: str | None = None) -> str:
    """The canonical text standing in for a scenario.

    business_description carries the situation; keyphrases pull in the client's
    own wording, which is what triggers actually resemble.

    *** THAT SECOND CLAUSE WAS AN UNTESTED ASSERTION FOR MONTHS, AND IT IS NOW MEASURED --
    the two registers should not be concatenated. *** Routing every one of the 23,949 client
    turns against each variant and scoring the resulting populations against a length-matched
    random null (`calibration/routing_bench.py`, 4-fold CV over calls, 3 fold seeds, band
    2.6pp): keyphrases alone clears 42.1% of scenarios, prose alone 34.2%, and the shipped
    concatenation **31.6% -- below either component**. Mixing an analyst register with a
    client register in one averaged vector is worse than picking either. Both figures are
    range-0 across seeds, and the gap is 4x the band.

    STILL `concat` BY DEFAULT, because the measurement was taken in gemini-embedding-2 space
    (the turn-mode taxonomy is gemini-native) while production embeds with local bge, and the
    transfer was deliberately NOT tested. The mechanism is a property of the TEXT rather than
    of a cosine threshold, so it plausibly carries over -- but this repo has been burned
    before by shipping a plausible mechanism instead of a measured one.
    Spec: docs/superpowers/specs/2026-08-16-layer-a-routing-method-design.md
    """
    m = _resolve_mode(mode)
    if m == "concat":
        # LITERALLY the pre-flag expression, so the default path is byte-identical in every
        # case -- including the TypeError it has always raised on a None description. A
        # "harmless" tidy-up here would make the flag-off path something other than what
        # shipped, which is the one thing it must never be.
        return info.get("business_description", "") + " " + " ".join(
            info.get("keyphrases", []) or [])

    prose = (info.get("business_description") or "").strip()
    phrases = " ".join(info.get("keyphrases", []) or []).strip()
    text = phrases if m == "keyphrases" else prose
    if not text:
        # A VISIBLE fallback, never a silent one. Embedding "" would give every text-less
        # scenario the same degenerate vector and let it win matches at random; falling back
        # to the full text keeps it comparable, and the warning says it happened.
        _logger.warning("scenario_vector_mode=%s but that field is empty; falling back to "
                        "concat for this scenario", m)
        return scenario_text(info, mode="concat")
    return text


def build_scenario_vecs(scenario_map: dict, mode: str | None = None
                        ) -> tuple[list[str], list[list[float]]]:
    """Parallel (keys, vectors) over a scenario map, in a stable order."""
    keys = list(scenario_map.keys())
    if not keys:
        return [], []
    m = _resolve_mode(mode)
    vecs = embedder.embed_document([scenario_text(scenario_map[k], m) for k in keys])
    return keys, vecs


def scenario_vec(info: dict, mode: str | None = None) -> list[float]:
    """Vector for a single scenario, embedded the same way as in the batch path."""
    return embedder.embed_document([scenario_text(info, mode)])[0]


def primary_topic_text(info: dict) -> str:
    """Canonical text for a primary_topic, mirroring scenario_text()."""
    return info.get("description", "") + " " + " ".join(info.get("keyphrases", []) or [])


def build_primary_topic_vecs(primary_topic_map: dict) -> tuple[list[str], list[list[float]]]:
    """Parallel (keys, vectors) over a primary_topic map, mirroring build_scenario_vecs()."""
    keys = list(primary_topic_map.keys())
    if not keys:
        return [], []
    vecs = embedder.embed_document([primary_topic_text(primary_topic_map[k]) for k in keys])
    return keys, vecs
