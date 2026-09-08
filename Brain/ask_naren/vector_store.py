"""Where Ask Naren's nearest-neighbour search actually runs (ADR 0008).

Every vector operation is behind ONE method -- `search(query_vec, top_k)` returning
`(pair_id, cosine)` nearest first -- with two implementations:

  * `PineconeTriggerStore` is what ships. The vectors already exist in the pipeline's
    `narens-brain-3072` index and the stored values are exact (cos = 1.000000 on 24/24
    pairs). The process holds NO VECTORS at all -- 79.8 MB -> 0, measured -- and never
    embeds the corpus. Startup time itself is dominated by the Postgres read either way and
    is NOT the win on a machine whose local embed cache is warm; see ADR 0008's corrected
    startup section before quoting a speedup.

    ITS SEARCH IS APPROXIMATE, THOUGH, AND THAT IS NOT A BUG TO FIX. Querying the index
    with one of its own stored unit vectors scores that record between 0.999321 and
    1.00135 -- above 1 is not a cosine, so the scores come from a quantized ANN
    representation. Measured over 47 real situations: same top-ranked kb_pair 47/47,
    cosine |delta| max 1.62e-3, and 3/47 situations whose rank-1 margin is NARROWER than
    that error, i.e. where the approximation could pick the other exchange. Accepted
    because ADR 0005 measured that cosine does not separate right answers from wrong ones,
    so choosing between two exchanges 1e-3 apart is not a quality-relevant decision. Full
    numbers in ask-naren/audit/equivalence_vector_store.py.

  * `InMemoryTriggerStore` is the numpy path Ask Naren shipped with. It is not legacy
    baggage: it is what lets the whole test suite run with no network, and it is what
    `ops/serve_ask_naren.py`'s rollback constant switches back to in one line.

BOTH return BARE string identifiers, deliberately. Pinecone keys its records
`trigger_<pair_id>` while Postgres yields an integer `pair_id`; if the two stores disagreed
about that shape, a rollback would swap in a store the pool cannot post-filter, and the
symptom would be Ask Naren declining every situation -- which reads as a quality problem
rather than a type bug. One contract, asserted in tests on both implementations.

WHAT THIS MODULE DOES NOT DO: it does not decide which pairs are answerable. A ranking is
just a ranking; `RetrievalPool` post-filters it, because neither of the two correctness
gates -- content dedup and the coachable restriction -- is fully expressible in a metadata
filter. See retrieval.py.
"""
from __future__ import annotations

from typing import Protocol, Sequence

import numpy as np

# The namespace Layer B's ship populates with trigger vectors, and the one
# shared/pinecone_store.query_triggers already reads. Response vectors live in a sibling
# namespace and are not what a situation is matched against.
TRIGGERS_NAMESPACE = "triggers"

# Pinecone's record id for a trigger vector, as ops/ship_layer_b.py writes it.
_ID_PREFIX = "trigger_"


class TriggerVectorStore(Protocol):
    """The one seam this design has (ADR 0008).

    `search` returns at most `top_k` `(pair_id, cosine)` tuples, NEAREST FIRST, where
    `pair_id` is the bare identifier as a string. Ordering is the store's and is not
    recomputed by the caller -- two ranking implementations would be a place for the
    shortlist and the shipped rank-1 path to disagree silently about what "closest" means.
    """

    def search(self, query_vec, top_k: int) -> list[tuple[str, float]]:
        ...


class InMemoryTriggerStore:
    """The pre-ADR-0008 numpy search, kept for tests and for rollback.

    Holds the pool's own identifiers, so every ranking it returns is authorised by
    construction and the pool's post-filter is a no-op over it. That is what makes the two
    stores substitutable rather than merely similar.
    """

    def __init__(self, pair_ids: Sequence, vectors: np.ndarray):
        vectors = np.asarray(vectors, dtype=np.float32)
        if len(pair_ids) != len(vectors):
            raise ValueError(
                f"{len(pair_ids)} pair_ids but {len(vectors)} vectors -- a store whose rows "
                f"and vectors disagree would answer from the wrong kb_pair silently")
        self.pair_ids = [str(p) for p in pair_ids]
        self.vectors = _unit_rows(vectors)

    def search(self, query_vec, top_k: int) -> list[tuple[str, float]]:
        if not self.pair_ids:
            return []
        # Both sides unit-normalized, so the returned numbers ARE cosines. Normalizing the
        # query cannot change the ranking (a positive scalar does not reorder a sort) but it
        # is what makes the reported figures mean what a caller reads them as.
        q = _unit_rows(np.asarray([query_vec], dtype=np.float32))[0]
        sims = self.vectors @ q
        order = np.argsort(-sims)[:top_k]
        return [(self.pair_ids[int(i)], float(sims[int(i)])) for i in order]


class PineconeTriggerStore:
    """The shipped store: the pipeline's `narens-brain-3072` index, read-only.

    `scenario_keys` is the coachable restriction, expressed as a metadata filter. The
    retrieval module's docstring used to say this restriction "cannot be expressed there at
    all" because `is_coachable` is not in Pinecone's metadata. True of that field, and the
    conclusion does not follow: coachability is a property of a SCENARIO and `scenario_key`
    IS in the metadata. Measured free -- 218ms filtered against 221ms unfiltered.

    The keys are passed IN rather than derived here, because they come from
    shared.relative_match.is_sink_flags -- Brain's one definition of "sink" -- read from
    Postgres at startup. Deriving them here would write a second definition into a metadata
    filter, which is the specific latent bug retrieval.coachable_scenario_keys warns about.

    Holds no database handle and cannot write: this class only ever queries.
    """

    def __init__(self, api_key: str, index_name: str, scenario_keys: Sequence[str],
                 namespace: str = TRIGGERS_NAMESPACE):
        if not scenario_keys:
            raise ValueError(
                "no coachable scenario keys -- an unrestricted filter would let Ask Naren "
                "answer from scenarios it is not allowed to coach")
        self._api_key = api_key
        self._index_name = index_name
        self._namespace = namespace
        self._scenario_keys = sorted(set(scenario_keys))

    def search(self, query_vec, top_k: int) -> list[tuple[str, float]]:
        from shared import pinecone_store
        matches = pinecone_store.query_trigger_vectors(
            self._api_key, self._index_name, _as_floats(query_vec), top_k=top_k,
            namespace=self._namespace, scenario_keys=self._scenario_keys)
        return [(_bare_id(m_id), _clamp_cosine(score)) for m_id, score in matches]

    def unretrievable(self, pairs: Sequence[dict]) -> tuple[list[tuple[str, str]],
                                                            list[tuple[str, str]]]:
        """(fatal, stale) for these pool pairs -- the startup guard (ADR 0008).

        Retrieval depends on the index holding a trigger vector for every coachable pair,
        AND on that vector being admitted by the search's `scenario_key` filter. A pool pair
        failing either test is PERMANENTLY UNRETRIEVABLE: nothing errors, nothing logs, and a
        CSM simply never sees those exchanges. That is the worst failure shape available
        here, which is why it is worth a couple of seconds at every start.

        TWO FAILURE MODES, and an audit found that checking only the first is not enough:

          * `absent`    -- no record for that pair_id. The obvious case: a pipeline run
                           wrote kb_pairs to Postgres before upserting their vectors.
          * `key drift` -- the record exists, but the `scenario_key` in its metadata is NOT
                           one the filter admits, so the search can never return it. The
                           pool's key is read LIVE from Postgres while the index's was
                           written at vector-ship time, and `response_taxonomy_auto_pass.py`
                           and `calibration/graduate_sink_topics.py` both UPDATE
                           `kb_pairs.scenario_key` with NO re-upsert -- graduating a sink
                           into a coachable scenario, which is exactly the case
                           `retrieval.coachable_scenario_keys` warns moves between runs.
                           A presence-only guard reports full coverage while every pair in
                           the graduated scenario is invisible. Measured 0 drifted of 6,496
                           on 2026-09-08, so this is latent today, not live.

        Returns them separately because they are not equally serious. `fatal` cannot be
        retrieved at all. `stale` is a record whose key differs from Postgres but is still
        inside the filter, so it IS retrievable -- the pool decides the scenario an answer
        reports anyway. Worth surfacing, not worth refusing to serve over.

        Absence is confirmed with an exact `fetch` before being called fatal, because the
        cheap check is an ANN query and a false alarm must not refuse a healthy index. A key
        that came BACK needs no confirmation -- the metadata is the authority on itself.
        """
        from shared import pinecone_store
        expected = {str(p["pair_id"]): p["scenario_key"] for p in pairs}
        indexed = pinecone_store.present_trigger_pair_ids(
            self._api_key, self._index_name, list(expected), namespace=self._namespace)

        admitted = set(self._scenario_keys)
        fatal: list[tuple[str, str]] = []
        stale: list[tuple[str, str]] = []
        for pair_id, index_key in indexed.items():
            if index_key == expected[pair_id]:
                continue
            if index_key in admitted:
                stale.append((pair_id, f"index has {index_key!r}, pool has "
                                       f"{expected[pair_id]!r} -- still searchable"))
            else:
                fatal.append((pair_id, f"scenario_key drift: index has {index_key!r}, "
                                       f"which the filter does not admit; pool has "
                                       f"{expected[pair_id]!r}"))

        provisional = [p for p in expected if p not in indexed]
        if provisional:
            confirmed = pinecone_store.fetch_trigger_ids(
                self._api_key, self._index_name,
                [f"{_ID_PREFIX}{p}" for p in provisional], namespace=self._namespace)
            found = {_bare_id(i) for i in confirmed}
            fatal.extend((p, "absent from the index") for p in provisional if p not in found)
        return fatal, stale


def _clamp_cosine(score) -> float:
    """Pinecone's score, forced back into the range a cosine can actually occupy.

    MEASURED, not defensive: querying the index with a stored unit vector returns its OWN
    record at scores between 0.999321 and 1.00135. A cosine of a unit vector with itself is
    exactly 1, and nothing above 1 is a cosine at all -- so those scores are coming from a
    quantized ANN representation, not from exact arithmetic. (The stored VALUES are exact:
    fetched vectors have norm 1.00000 and reproduce cos = 1.00000000 against themselves.)

    `Match.cosine` is documented as a real cosine and is read against ADR 0005's measured
    bands, so handing a caller 1.00135 would be handing them a number that cannot exist.
    Clamping reports the nearest value that can. The ~1.5e-3 of approximation error is real
    and is characterised in ask-naren/audit/equivalence_vector_store.py; it is not hidden by
    this, only kept inside the range.
    """
    return max(-1.0, min(1.0, float(score)))


def _bare_id(record_id: str) -> str:
    """`trigger_1234` -> `1234`. The pool keys on the pair_id, not on Pinecone's record id."""
    text = str(record_id)
    return text[len(_ID_PREFIX):] if text.startswith(_ID_PREFIX) else text


def _as_floats(query_vec) -> list[float]:
    return [float(x) for x in np.asarray(query_vec, dtype=np.float32).ravel()]


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
