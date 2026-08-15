"""Steps 1-3: fetch the rubric to score against, and Naren's benchmark response."""
from __future__ import annotations

import numpy as np
import psycopg

from ego_trap.transcript_parser import EgoTrapRole, EgoTrapTurn, turns_until_next_client
from preprocessing import embedder
from shared import relative_match, storage
from shared.scenario_vectors import scenario_vec

# How many of Naren's responses go into the Step 3 prompt as reference material.
# A PROMPT-LENGTH cap, not a threshold on the data -- the same kind of constant as
# v2/layer_c._MAX_RUBRIC_RESPONSES, and a module constant for the same reason. It
# stays out of tuning.yaml deliberately: every knob in that file is a property of the
# data (a fraction, a cosine, a percentile) so that adding transcripts re-derives it,
# and a token budget is not that.
_MAX_BENCHMARK_EXAMPLES = 2


def fetch_rubric(conn: psycopg.Connection, scenario_key: str) -> dict | None:
    """Steps 1-2: the Layer C rubric for a detected scenario, or None if unmapped.

    Carries pipeline_version, so a caller can tell an evidence-backed v2 rubric from
    a v1 Gemma-written fallback. Scoring against the two is not the same measurement.
    """
    return storage.get_rubric_for_scenario(conn, scenario_key)


def rank_benchmark_responses(
    responses: list[dict], scenario_info: dict, limit: int
) -> list[dict]:
    """Naren's responses for one scenario, most on-topic first.

    Replaces "ORDER BY pair_id, take the first two", which picked the two OLDEST
    rows by insertion order -- an arbitrary choice that had nothing to do with how
    well a response represents the scenario.

    Reuses the pipeline's only two scoring primitives and invents nothing:
    scenario_vectors.scenario_vec is the one definition of "the scenario vector"
    (business_description + keyphrases), and responses are embedded with
    embed_document everywhere else in the codebase, so the same vectors come back out
    of the cache. This is a RANKING, not a gate: it needs no calibrated cutoff, which
    is why it can land without a sweep first.

    Cost is effectively zero on the machine that ran the pipeline. Every
    response_text was already embed_document-ed by layer_b.embed_and_store_pairs and
    every scenario vector by build_scenario_vecs, and embed_cache.db is keyed on
    (model, prefix, text) -- identical on all three -- so this is a SQLite read, not
    a GPU pass and never an API call.
    """
    if not responses:
        return []
    if len(responses) <= limit:
        return list(responses)

    texts = [r["response_text"] for r in responses]
    sims = relative_match.cosine_sims(
        embedder.embed_document_matrix(texts),
        np.asarray([scenario_vec(scenario_info)]),
    )[:, 0]
    order = np.argsort(sims)[::-1][:limit]
    ranked = []
    for j in order:
        row = dict(responses[int(j)])
        row["scenario_similarity"] = float(sims[int(j)])
        ranked.append(row)
    return ranked


def get_benchmark_reference(
    conn: psycopg.Connection, scenario_key: str, scenario_info: dict
) -> str:
    """Naren's benchmark response(s), passed to Step 3 as reference only.

    Reads the MULTI-LABEL population: Layer B files each pair under up to
    max_scenarios_per_pair scenarios, keeping the best in the scalar scenario_key and
    all of them in scenario_keys[]. Measured production width is 63% one / 19% two /
    18% three, so reading only the scalar column made roughly a third of the pairs
    judged relevant to a scenario invisible here.

    (kb_pairs.benchmark_response exists and is deliberately left alone -- it is a
    per-PAIR column, while a benchmark reference is a per-SCENARIO concept. Writing
    it would be a schema-shape mistake dressed up as a fix. Nothing reads it today.)
    """
    responses = storage.get_responses_for_scenario_multilabel(conn, scenario_key)
    top = rank_benchmark_responses(responses, scenario_info, _MAX_BENCHMARK_EXAMPLES)
    return "\n\n".join(r["response_text"] for r in top)


def extract_csm_response_window(turns: list[EgoTrapTurn], signal: dict) -> str:
    """All CSM turns after the signal's CLIENT turn, up to (not including) the next."""
    following = turns_until_next_client(turns, signal["turn_index"])
    return " ".join(t.text for t in following if t.role == EgoTrapRole.CSM)
