"""Ask Naren's retrieval pool: which kb_pairs are eligible, and which one a situation
matches. Pure rules plus one loader -- no generation, no gateway.

Mirrors what ask-naren/prototype/eval_pairs_vs_playbook.py already validated end-to-end,
with the prototype's leave-one-call-out mask REMOVED: that rule exists to stop a held-out
corpus item retrieving its own call, and a live CSM situation is not a corpus item. The
dedup the prototype's second audit added stays, and is now the only content-level guard.

The nearest-neighbour search runs IN PINECONE (ADR 0008), not here. This docstring used to
say the opposite, and the reason it gave was wrong: `is_coachable` is indeed absent from
Pinecone's metadata, but the conclusion that the coachable-only restriction "cannot be
expressed there at all" does not follow -- coachability is a property of a SCENARIO, and
`scenario_key` IS in the metadata. Expressing it as `scenario_key $in [the coachable keys]`
was measured free (218ms filtered against 221ms unfiltered).

What stays here is the part a metadata filter cannot do. Pinecone ranks; this module
AUTHORISES, post-filtering the ranking through the pool so that content dedup and the
coachable restriction keep their existing single definitions. See vector_store.py.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ask_naren import vector_store
from shared import relative_match, storage

# How deep a ranking topk asks a store for, so its post-filter cannot starve the result.
OVERFETCH_FLOOR = 25
OVERFETCH_FACTOR = 5


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

    def __init__(self, pairs: list[dict], vectors: np.ndarray | None = None, *,
                 store=None):
        """Either a `vectors` matrix (the in-memory path) or a `store`, never both.

        Both is refused rather than resolved by precedence: which one was live would become a
        matter of reading order, and that is exactly the ambiguity ops/serve_ask_naren.py's
        rollback constant exists to make explicit.
        """
        if vectors is not None and store is not None:
            raise ValueError("pass either vectors or store, not both -- two rankings in one "
                             "pool makes which is live a matter of reading order")
        if vectors is None and store is None:
            raise ValueError("a pool needs either a vectors matrix or a store to rank with")
        if vectors is not None:
            if len(pairs) != len(vectors):
                raise ValueError(
                    f"{len(pairs)} pairs but {len(vectors)} vectors -- a pool whose rows and "
                    f"vectors disagree would answer from the wrong kb_pair silently")
            store = vector_store.InMemoryTriggerStore(
                [p["pair_id"] for p in pairs], vectors)
        self.pairs = pairs
        self._store = store
        # Kept ONLY for the in-memory path, because three offline audit scripts
        # (probe_topk_headroom, probe_query_framing, build_answer_audit) reach for
        # `pool.vectors` to build their own masked rankings. None under the Pinecone store,
        # where the process holds no vectors at all -- which is the point of ADR 0008.
        self.vectors = getattr(store, "vectors", None)
        # Built once, alongside the vectors, because a follow-up resolves a carried pair_id
        # on every message and a linear scan of 6.5k rows per question is a cost with no
        # buyer. First wins, matching dedupe_pairs -- two rows with one id would be a
        # corpus bug, and answering from whichever came second is not a better outcome.
        self._by_pair_id = {}
        for pair in pairs:
            self._by_pair_id.setdefault(pair["pair_id"], pair)
        # A SECOND index, keyed on the identifier as a STRING, for post-filtering a store's
        # ranking. Pinecone keys its records `trigger_<pair_id>` while Postgres yields an
        # integer pair_id: without this normalisation every lookup below misses, the pool
        # authorises nothing, and Ask Naren declines every situation -- a total failure that
        # reads as a quality problem rather than a type bug. Pinned by test.
        self._by_pair_id_str = {}
        for pair in pairs:
            self._by_pair_id_str.setdefault(str(pair["pair_id"]), pair)

    def __len__(self) -> int:
        return len(self.pairs)

    def by_pair_id(self, pair_id) -> dict | None:
        """The exchange a thread carried forward, WITHOUT searching for it (ADR 0006).

        This is what makes multi-turn possible under an ADR that forbids history from
        reaching the embedded query: the thread supplies an identifier, and the text comes
        from the pool we already hold. Nothing is embedded and nothing is ranked.

        None when the id is not in the pool -- which is a real case, not a defensive
        nicety: the pool is loaded once at startup, and a re-run of Brain's pipeline between
        restarts can retire a pair a CSM's open thread still refers to. The caller answers
        the message as a new question rather than grounding in nothing.
        """
        return self._by_pair_id.get(pair_id)

    def top1(self, query_vec: np.ndarray) -> Match:
        """The closest pair to this situation, with a real cosine.

        Delegates to topk so there is ONE ranking implementation: two would be a place for
        the shortlist and the shipped rank-1 path to disagree silently about what "closest"
        means, which is the class of bug issue #8 is being run to avoid, not to introduce.
        """
        return self.topk(query_vec, 1)[0]

    def topk(self, query_vec: np.ndarray, k: int) -> list[Match]:
        """The k closest pairs, nearest first, with real cosines.

        The store ranks; this walks that ranking in order and keeps only what the pool
        holds. Rank order is never recomputed -- see top1 on why one implementation.

        THE SKIP IS A CORRECTNESS GATE, not a defensive nicety, and it carries both rules a
        metadata filter cannot express:

          * content dedup -- the corpus holds transcripts ingested twice under two
            `calls.filename` values (32 byte-identical pairs across 15 scenarios).
            dedupe_pairs drops the second copy here, but BOTH pair_ids are in Pinecone
            carrying coachable scenario keys, so the filter admits both and only this skip
            stops them competing as separate neighbours for one situation.
          * authorisation -- Pinecone holds whatever the pipeline shipped, measured at 1.92x
            this pool, including pairs a later run retired.

        Returns fewer than k when the ranking runs out of authorised hits. A caller must not
        assume len(...) == k: padding a shortlist with an absent or repeated candidate would
        put a moment in the prompt that retrieval never chose.
        """
        if not self.pairs:
            raise ValueError("retrieval pool is empty -- refusing to answer from nothing")
        matches: list[Match] = []
        for pair_id, score in self._store.search(query_vec, _overfetch(k)):
            pair = self._by_pair_id_str.get(str(pair_id))
            if pair is None:
                continue
            matches.append(Match(pair=pair, cosine=float(score)))
            if len(matches) == k:
                break
        return matches


def _overfetch(k: int) -> int:
    """How deep a ranking to ask for, to serve k after the skip in topk.

    Asking for exactly k would let a handful of content duplicates or retired pairs at the
    top of the ranking make Ask Naren decline a situation it can answer. The floor of 25 is
    set against the measured shape of the problem rather than guessed: the whole corpus
    holds 32 duplicate pairs across 6,496, and the shipped candidate selection is 1
    (ADR 0005), so 25 is deep enough that exhausting it means a genuinely thin neighbourhood
    rather than a filtering artefact. The filter costs nothing at this depth (218ms).
    """
    return max(OVERFETCH_FLOOR, k * OVERFETCH_FACTOR)


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)


def load_coachable_pairs(conn) -> list[dict]:
    """Every kb_pair filed under a coachable scenario, deduped on content. Read-only."""
    pairs: list[dict] = []
    for key in coachable_scenario_keys(storage.get_scenarios(conn)):
        for p in storage.get_naren_responses_for_scenario(conn, key):
            pairs.append({**p, "scenario_key": key})
    return dedupe_pairs(pairs)
