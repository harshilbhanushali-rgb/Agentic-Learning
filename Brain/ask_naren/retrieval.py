"""Ask Naren's retrieval pool: which kb_pairs are eligible, and which one a situation
matches. Pure rules plus one loader -- no generation, no gateway.

Mirrors what ask-naren/prototype/eval_pairs_vs_playbook.py already validated end-to-end,
with the prototype's leave-one-call-out mask REMOVED: that rule exists to stop a held-out
corpus item retrieving its own call, and a live CSM situation is not a corpus item. The
dedup the prototype's second audit added stays, and is now the only content-level guard.

The nearest-neighbour search is an in-memory cosine, deliberately not a live Pinecone
query: `is_coachable` is not in Pinecone's metadata, so the coachable-only restriction
cannot be expressed there at all. Same reasoning calibration/probe_retrieval_gate.py and
the prototype both document.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared import relative_match, storage


@dataclass(frozen=True)
class Match:
    """The one kb_pair a situation is answered from, and how close it actually was.

    `cosine` is in gemini-embedding-2@3072 space (tuning.yaml `embedding.backend: gateway`),
    NOT the bge@768 space every absolute threshold in tuning.yaml was fitted to. The bands
    differ by roughly +0.14 and are tighter (bge trigger p50=0.550 against gemini's 0.690),
    so this number must not be read against a bge-era floor -- see Brain/CLAUDE.md's
    embedding-backend note. Recorded for later decline-rate calibration; nothing here
    thresholds on it.
    """
    pair: dict
    cosine: float


def normalize(text: str | None) -> str:
    """Case- and whitespace-insensitive form, for comparing CONTENT. Same rule the
    prototype's `_normalize` used, so the dedup measured there is the dedup applied here."""
    return " ".join((text or "").split()).lower()


def coachable_scenario_keys(scenarios: list[dict]) -> list[str]:
    """The scenarios Ask Naren is allowed to answer from, in input order.

    Delegates the predicate to shared.relative_match.is_sink_flags -- which that module
    calls "the one definition of 'this scenario is a sink'" -- rather than reading
    `is_coachable` here. Brain's own docstrings warn repeatedly that two definitions of
    "sink" agreeing today is a latent bug, and a CSM-facing tool is the worst place to
    discover one.

    NOT ego_trap.scenario_pool.is_coachable, which is the same rule: `ego_trap/` is the
    rubric-era pipeline, dark since the union taxonomy replacement and documented in
    Brain/CLAUDE.md as retiring once the Layer D redesign passes its gates -- which it did
    on 2026-08-25. A new production service must not depend on a package scheduled for
    deletion. `shared/` is not going anywhere.

    cluster_kind is NOT consulted: response_taxonomy_auto_pass graduates sinks into
    coachable scenarios between runs, and only is_coachable moves when it does.
    """
    keys = [s["scenario_key"] for s in scenarios]
    sinks = relative_match.is_sink_flags({s["scenario_key"]: s for s in scenarios}, keys)
    return [key for key, is_sink in zip(keys, sinks) if not is_sink]


def dedupe_pairs(pairs: list[dict]) -> list[dict]:
    """Drop pairs whose (trigger, response) CONTENT already appeared, keeping the first.

    Not an optimisation -- a correctness gate found by the prototype's second audit. The
    corpus holds transcripts ingested twice under two different `calls.filename` values
    with byte-identical pairs (measured: 64 of 6528 coachable rows, 32 distinct pairs x 2
    filenames, across 15 scenarios). Keying on filename instead of content leaves both
    copies in the pool, where they compete as separate neighbours for the same situation.
    """
    seen: set[tuple[str, str]] = set()
    kept = []
    for p in pairs:
        key = (normalize(p["trigger_text"]), normalize(p["response_text"]))
        if key in seen:
            continue
        seen.add(key)
        kept.append(p)
    return kept


class RetrievalPool:
    """The deduped coachable pool and its trigger vectors, ready to search.

    Built ONCE at startup, not per request: the pool is ~6.5k rows, re-querying Postgres
    and re-embedding it on every question is latency nobody is buying anything with.
    """

    def __init__(self, pairs: list[dict], vectors: np.ndarray):
        if len(pairs) != len(vectors):
            raise ValueError(
                f"{len(pairs)} pairs but {len(vectors)} vectors -- a pool whose rows and "
                f"vectors disagree would answer from the wrong kb_pair silently")
        self.pairs = pairs
        self.vectors = _unit_rows(np.asarray(vectors, dtype=np.float32))

    def __len__(self) -> int:
        return len(self.pairs)

    def top1(self, query_vec: np.ndarray) -> Match:
        """The closest pair to this situation, with a real cosine.

        Delegates to topk so there is ONE ranking implementation: two would be a place for
        the shortlist and the shipped rank-1 path to disagree silently about what "closest"
        means, which is the class of bug issue #8 is being run to avoid, not to introduce.
        """
        return self.topk(query_vec, 1)[0]

    def topk(self, query_vec: np.ndarray, k: int) -> list[Match]:
        """The k closest pairs, nearest first, with real cosines.

        Both sides are unit-normalized, so the returned numbers ARE cosines. Normalizing
        the query cannot change the ranking (a positive scalar does not reorder a sort) but
        it is what makes the reported figures mean what a caller reads them as.
        """
        if not self.pairs:
            raise ValueError("retrieval pool is empty -- refusing to answer from nothing")
        q = _unit_rows(np.asarray([query_vec], dtype=np.float32))[0]
        sims = self.vectors @ q
        order = np.argsort(-sims)[:k]
        return [Match(pair=self.pairs[int(i)], cosine=float(sims[int(i)])) for i in order]


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)


def load_coachable_pairs(conn) -> list[dict]:
    """Every kb_pair filed under a coachable scenario, deduped on content. Read-only."""
    pairs: list[dict] = []
    for key in coachable_scenario_keys(storage.get_scenarios(conn)):
        for p in storage.get_naren_responses_for_scenario(conn, key):
            pairs.append({**p, "scenario_key": key})
    return dedupe_pairs(pairs)
