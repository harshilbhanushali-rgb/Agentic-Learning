from __future__ import annotations
import numpy as np
import psycopg
import spacy
from config import Config
from preprocessing.transcript_parser import Turn, SpeakerRole
from preprocessing import embedder
from shared import storage
from shared import pinecone_store

_SIMILARITY_THRESHOLD = 0.30
_MIN_CONTENT_WORDS = 5

_nlp = spacy.load("en_core_web_lg", disable=["parser", "ner"])


def _is_substantive(text: str) -> bool:
    """Return False if text has fewer than _MIN_CONTENT_WORDS non-stop, alphabetic tokens."""
    doc = _nlp(text)
    content = [t for t in doc if t.is_alpha and not t.is_stop]
    return len(content) >= _MIN_CONTENT_WORDS


def _build_scenario_vecs(scenario_map: dict) -> tuple[list[str], list[list[float]]]:
    keys = list(scenario_map.keys())
    descs = [
        scenario_map[k]["sub_topic"] + " " + " ".join(scenario_map[k].get("keyphrases", []))
        for k in keys
    ]
    vecs = embedder.embed_document(descs)
    return keys, vecs


def extract_pairs(
    turns: list[Turn],
    db_call_id: int,
) -> list[dict]:
    pairs = []
    i = 0
    while i < len(turns):
        turn = turns[i]
        if turn.role != SpeakerRole.CLIENT:
            i += 1
            continue
        if not _is_substantive(turn.text):
            i += 1
            continue
        trigger_turn = turn
        response_parts = []
        j = i + 1
        while j < len(turns):
            t = turns[j]
            if t.role == SpeakerRole.NAREN:
                if _is_substantive(t.text):
                    response_parts.append(t.text)
                j += 1
            elif t.role == SpeakerRole.JOVEO_OTHER:
                j += 1
            else:
                break
        if response_parts:
            pairs.append({
                "call_id": db_call_id,
                "scenario_id": None,
                "scenario_key": None,
                "turn_index": trigger_turn.index,
                "trigger_text": trigger_turn.text,
                "response_text": " ".join(response_parts),
            })
        i = j if response_parts else i + 1
    return pairs


def assign_scenarios(
    pairs: list[dict],
    scenario_map: dict[str, dict],
    config: Config,
) -> list[list[float]]:
    """Assign each pair to one or more scenarios using a two-stage strategy:

    Stage 1 — per-pair multi-match:
      Compute cosine similarity between each trigger and all scenario descriptions.
      Assign the pair to every scenario that crosses _SIMILARITY_THRESHOLD.
      scenario_key = the highest-scoring match; scenario_keys = all matches.

    Stage 2 — centroid fallback:
      For pairs that matched nothing in Stage 1, compute the call centroid
      (mean of all trigger embeddings) and assign the best-matching scenario
      unconditionally. Ensures no pair is left with scenario_key = None.

    Returns trigger vecs so embed_and_store_pairs can reuse them.
    """
    if not pairs:
        return []

    trigger_texts = [p["trigger_text"] for p in pairs]
    trigger_vecs = embedder.embed_query(trigger_texts)

    if not scenario_map:
        return trigger_vecs

    scenario_keys, scenario_vecs = _build_scenario_vecs(scenario_map)

    T = np.array(trigger_vecs)
    S = np.array(scenario_vecs)
    T_norm = T / (np.linalg.norm(T, axis=1, keepdims=True) + 1e-10)
    S_norm = S / (np.linalg.norm(S, axis=1, keepdims=True) + 1e-10)
    sim_matrix = T_norm @ S_norm.T  # (n_pairs, n_scenarios)

    # Stage 1: per-pair multi-match
    unmatched = []
    for i, pair in enumerate(pairs):
        matched = [scenario_keys[j] for j in range(len(scenario_keys))
                   if sim_matrix[i, j] >= _SIMILARITY_THRESHOLD]
        if matched:
            best_j = int(np.argmax(sim_matrix[i]))
            pair["scenario_keys"] = matched
            pair["scenario_key"]  = scenario_keys[best_j]
            pair["scenario_id"]   = scenario_map[scenario_keys[best_j]]["scenario_id"]
        else:
            unmatched.append(i)

    # Stage 2: centroid fallback for unmatched pairs
    if unmatched:
        centroid = T_norm.mean(axis=0)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
        sims = S_norm @ centroid
        best_j = int(np.argmax(sims))
        fallback_key = scenario_keys[best_j]
        fallback_id  = scenario_map[fallback_key]["scenario_id"]
        for i in unmatched:
            pairs[i]["scenario_key"]  = fallback_key
            pairs[i]["scenario_id"]   = fallback_id
            pairs[i]["scenario_keys"] = [fallback_key]

    return trigger_vecs


def embed_and_store_pairs(
    pairs: list[dict],
    conn: psycopg.Connection,
    config: Config,
    trigger_vecs: list[list[float]] | None = None,
) -> list[int]:
    if not pairs:
        return []
    pair_ids = [storage.insert_kb_pair(conn, p) for p in pairs]
    for i, pair in enumerate(pairs):
        pair["pair_id"] = pair_ids[i]
    if trigger_vecs is None:
        trigger_vecs = embedder.embed_query([p["trigger_text"] for p in pairs])
    response_vecs = embedder.embed_document([p["response_text"] for p in pairs])
    for i, pair in enumerate(pairs):
        pair["trigger_vec"] = trigger_vecs[i]
        pair["response_vec"] = response_vecs[i]
    pinecone_store.upsert_pairs(config.pinecone_api_key, config.pinecone_index_name, pairs)
    return pair_ids
