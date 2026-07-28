from __future__ import annotations
import numpy as np
import psycopg
import spacy
from config import Config
from preprocessing.transcript_parser import Turn, SpeakerRole
from preprocessing import embedder
from shared import storage
from shared import pinecone_store
from shared.scenario_vectors import build_scenario_vecs as _build_scenario_vecs
from shared.tuning import load_tuning

_MIN_CONTENT_WORDS = 5

_nlp = spacy.load("en_core_web_lg", disable=["parser", "ner"])


def _is_substantive(text: str) -> bool:
    """Return False if text has fewer than _MIN_CONTENT_WORDS non-stop, alphabetic tokens."""
    doc = _nlp(text)
    content = [t for t in doc if t.is_alpha and not t.is_stop]
    return len(content) >= _MIN_CONTENT_WORDS


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
    """Assign each pair to its best-matching scenarios by RELATIVE similarity.

    The old rule was an absolute cosine floor of 0.30 against every scenario. That
    does not scale with taxonomy size: at 149 scenarios, 70% of pairs cleared it
    against nearly all of them at once, which left Layer C training on a
    near-random response pool. An absolute threshold also has no defensible value
    -- these embeddings put short conversational text in a narrow similarity band,
    so the number that works at one corpus size is wrong at the next.

    Relative top-K is scale-invariant instead: rank scenarios per trigger, keep
    those within RELATIVE_MARGIN of the trigger's OWN best match, cap the count.
    A trigger that genuinely fits one scenario keeps one; an ambiguous trigger
    keeps a few; nothing keeps 149.

    Sinks (is_coachable=false clusters -- mechanics, pleasantries) stay match
    candidates on purpose. If a junk trigger's best match is a sink, it is filed
    there ALONE and stops. That sink is what replaces the old centroid fallback:
    because a relative cutoff always keeps at least the best match, no pair can
    be left unassigned, so the fallback stage is gone entirely rather than
    rerouted. Previously it guaranteed every unmatched junk pair was forced into
    some real scenario's rubric.

    Returns trigger vecs so embed_and_store_pairs can reuse them.
    """
    if not pairs:
        return []

    trigger_texts = [p["trigger_text"] for p in pairs]
    trigger_vecs = embedder.embed_query(trigger_texts)

    if not scenario_map:
        return trigger_vecs

    tuning = load_tuning().layer_b
    scenario_keys, scenario_vecs = _build_scenario_vecs(scenario_map)
    is_sink = [not scenario_map[k].get("is_coachable", True) for k in scenario_keys]

    T = np.array(trigger_vecs)
    S = np.array(scenario_vecs)
    T_norm = T / (np.linalg.norm(T, axis=1, keepdims=True) + 1e-10)
    S_norm = S / (np.linalg.norm(S, axis=1, keepdims=True) + 1e-10)
    sim_matrix = T_norm @ S_norm.T  # (n_pairs, n_scenarios)

    def _assign(pair, keys):
        pair["scenario_keys"] = keys
        pair["scenario_key"] = keys[0]
        pair["scenario_id"] = scenario_map[keys[0]]["scenario_id"]

    for i, pair in enumerate(pairs):
        sims = sim_matrix[i]
        order = np.argsort(sims)[::-1]
        best_j = int(order[0])

        # A junk trigger whose closest match is machinery belongs only there.
        # Letting it also match real scenarios is exactly how backchannel ended up
        # in strategic rubrics.
        if is_sink[best_j]:
            _assign(pair, [scenario_keys[best_j]])
            continue

        cutoff = tuning.relative_margin * float(sims[best_j])
        kept = [
            scenario_keys[int(j)] for j in order[:tuning.max_scenarios_per_pair]
            if float(sims[int(j)]) >= cutoff and not is_sink[int(j)]
        ]
        _assign(pair, kept or [scenario_keys[best_j]])

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
