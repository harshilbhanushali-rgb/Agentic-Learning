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

from preprocessing import embedder


def scenario_text(info: dict) -> str:
    """The canonical text standing in for a scenario.

    sub_topic carries the situation; keyphrases pull in the client's own wording,
    which is what triggers actually resemble.
    """
    return info.get("sub_topic", "") + " " + " ".join(info.get("keyphrases", []) or [])


def build_scenario_vecs(scenario_map: dict) -> tuple[list[str], list[list[float]]]:
    """Parallel (keys, vectors) over a scenario map, in a stable order."""
    keys = list(scenario_map.keys())
    if not keys:
        return [], []
    vecs = embedder.embed_document([scenario_text(scenario_map[k]) for k in keys])
    return keys, vecs


def scenario_vec(info: dict) -> list[float]:
    """Vector for a single scenario, embedded the same way as in the batch path."""
    return embedder.embed_document([scenario_text(info)])[0]
