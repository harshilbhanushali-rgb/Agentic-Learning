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
from shared.scenario_vectors import build_primary_topic_vecs as _build_primary_topic_vecs
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


def _topk_pick(
    sims: np.ndarray,
    keys: list[str],
    is_sink_arr: list[bool],
    cap: int,
    margin: float,
    restrict_to: set[int] | None = None,
) -> list[str] | None:
    """Shared relative top-K rule: rank `keys` by `sims`, keep entries within
    `margin` of the best among the (optionally restricted) non-sink candidates,
    capped at `cap`. Always keeps at least the best. Returns None if no
    candidate survives the sink/restrict filter -- the caller decides the
    fallback in that case.
    """
    order = np.argsort(sims)[::-1]
    candidates = [
        int(j) for j in order
        if not is_sink_arr[int(j)] and (restrict_to is None or int(j) in restrict_to)
    ]
    if not candidates:
        return None
    best_j = candidates[0]
    cutoff = margin * float(sims[best_j])
    kept = [keys[j] for j in candidates[:cap] if float(sims[j]) >= cutoff]
    return kept or [keys[best_j]]


def assign_scenarios_two_stage(
    pairs: list[dict],
    scenario_map: dict[str, dict],
    primary_topic_map: dict[str, dict],
    config: Config,
    strategy: str,
) -> list[list[float]]:
    """Primary-topic-first variant of assign_scenarios: strict / soft / fallback.

    See docs/superpowers/specs/2026-07-30-layer-b-two-stage-matching-design.md.
    UNCALIBRATED as of 2026-07-30 -- primary_topics is empty until a real
    pipeline run happens, so this has only been exercised against synthetic
    vectors in tests/test_two_stage_matching.py, never dry-run-compared
    against flat matching on real data. Kept fully separate from
    assign_scenarios (flat) rather than folded in, so that already-calibrated
    function stays untouched.

    Stage 1 (shared by all three strategies): narrow to the trigger's own
    primary_topic(s) within primary_topic_relative_margin of its best match.
    The sink short-circuit is untouched -- exactly like flat matching, it is
    decided from the raw subtopic best match BEFORE stage 1 ever runs, so a
    junk trigger still files to its sink alone regardless of strategy.
    """
    if not pairs:
        return []

    trigger_texts = [p["trigger_text"] for p in pairs]
    trigger_vecs = embedder.embed_query(trigger_texts)

    if not scenario_map or not primary_topic_map:
        return trigger_vecs

    tuning = load_tuning().layer_b
    scenario_keys, scenario_vecs = _build_scenario_vecs(scenario_map)
    is_sink = [not scenario_map[k].get("is_coachable", True) for k in scenario_keys]
    pt_of = [scenario_map[k].get("primary_topic_key") for k in scenario_keys]

    pt_keys, pt_vecs = _build_primary_topic_vecs(primary_topic_map)
    pt_index = {k: i for i, k in enumerate(pt_keys)}

    T = np.array(trigger_vecs)
    S = np.array(scenario_vecs)
    PT = np.array(pt_vecs)
    T_norm = T / (np.linalg.norm(T, axis=1, keepdims=True) + 1e-10)
    S_norm = S / (np.linalg.norm(S, axis=1, keepdims=True) + 1e-10)
    PT_norm = PT / (np.linalg.norm(PT, axis=1, keepdims=True) + 1e-10)
    sim_matrix = T_norm @ S_norm.T        # (n_pairs, n_scenarios)
    pt_sim_matrix = T_norm @ PT_norm.T    # (n_pairs, n_primary_topics)
    no_sink = [False] * len(pt_keys)

    def _assign(pair, keys):
        pair["scenario_keys"] = keys
        pair["scenario_key"] = keys[0]
        pair["scenario_id"] = scenario_map[keys[0]]["scenario_id"]

    for i, pair in enumerate(pairs):
        sims = sim_matrix[i]
        order = np.argsort(sims)[::-1]
        best_j = int(order[0])

        # Same rule as flat: a junk trigger belongs to its sink alone, decided
        # from the raw subtopic match, ignoring the primary_topic stage.
        if is_sink[best_j]:
            _assign(pair, [scenario_keys[best_j]])
            continue

        kept_pt = set(_topk_pick(
            pt_sim_matrix[i], pt_keys, no_sink,
            tuning.max_primary_topics_per_pair, tuning.primary_topic_relative_margin,
        ) or [])
        restrict_to = {j for j, pt in enumerate(pt_of) if pt in kept_pt}

        strict_kept = _topk_pick(
            sims, scenario_keys, is_sink, tuning.max_scenarios_per_pair,
            tuning.relative_margin, restrict_to=restrict_to,
        ) or [scenario_keys[best_j]]

        if strategy == "strict":
            _assign(pair, strict_kept)
        elif strategy == "fallback":
            top1_sim = float(sims[scenario_keys.index(strict_kept[0])])
            if top1_sim < tuning.two_stage_fallback_floor:
                flat_kept = _topk_pick(
                    sims, scenario_keys, is_sink, tuning.max_scenarios_per_pair,
                    tuning.relative_margin,
                ) or [scenario_keys[best_j]]
                _assign(pair, flat_kept)
            else:
                _assign(pair, strict_kept)
        elif strategy == "soft":
            blended = np.array([
                float(sims[j]) * float(pt_sim_matrix[i][pt_index[pt_of[j]]])
                if pt_of[j] in pt_index else 0.0
                for j in range(len(scenario_keys))
            ])
            soft_kept = _topk_pick(
                blended, scenario_keys, is_sink, tuning.max_scenarios_per_pair,
                tuning.relative_margin,
            ) or [scenario_keys[best_j]]
            _assign(pair, soft_kept)
        else:
            raise ValueError(f"unknown matching strategy: {strategy!r}")

    return trigger_vecs


def _flat_pick(
    sims: np.ndarray,
    keys: list[str],
    is_sink_arr: list[bool],
    cap: int,
    margin: float,
) -> list[str]:
    """Reproduces assign_scenarios's own per-pair sink-short-circuit + relative-margin
    logic on an arbitrary similarity vector, so assign_scenarios_with_sink_rescue can
    apply it to a trigger, response, or blended vector without duplicating the loop
    body per strategy. assign_scenarios itself is left untouched -- this is a new
    helper for the new function, not a refactor of the calibrated one.
    """
    order = np.argsort(sims)[::-1]
    best_j = int(order[0])
    if is_sink_arr[best_j]:
        return [keys[best_j]]
    cutoff = margin * float(sims[best_j])
    kept = [
        keys[int(j)] for j in order[:cap]
        if float(sims[int(j)]) >= cutoff and not is_sink_arr[int(j)]
    ]
    return kept or [keys[best_j]]


def assign_scenarios_with_sink_rescue(
    pairs: list[dict],
    scenario_map: dict[str, dict],
    config: Config,
    strategy: str,
) -> tuple[list[list[float]], list[list[float]]]:
    """Sink-rescue variant of assign_scenarios: response_only / or_rule / blended.

    See docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md for the problem
    this solves (sink absorption discarding real content whose RESPONSE, not trigger,
    carries the value) and why each strategy is shaped this way.

    UNCALIBRATED as of 2026-08-04 -- sink_rescue_relative_margin, sink_rescue_min_similarity,
    and sink_rescue_blend_alpha are all placeholders until compare_sink_rescue.py measures
    real response-vs-scenario similarity. Kept fully separate from assign_scenarios (flat)
    -- that function's own calibration (relative_margin=0.95, etc.) is untouched by this code.

    Returns (trigger_vecs, response_vecs) so a future wired-in caller could reuse both,
    mirroring assign_scenarios's existing trigger_vecs reuse into embed_and_store_pairs.
    """
    if not pairs:
        return [], []

    trigger_texts = [p["trigger_text"] for p in pairs]
    response_texts = [p["response_text"] for p in pairs]
    trigger_vecs = embedder.embed_query(trigger_texts)
    response_vecs = embedder.embed_document(response_texts)

    if not scenario_map:
        return trigger_vecs, response_vecs

    tuning = load_tuning().layer_b
    scenario_keys, scenario_vecs = _build_scenario_vecs(scenario_map)
    is_sink = [not scenario_map[k].get("is_coachable", True) for k in scenario_keys]

    T = np.array(trigger_vecs)
    R = np.array(response_vecs)
    S = np.array(scenario_vecs)
    T_norm = T / (np.linalg.norm(T, axis=1, keepdims=True) + 1e-10)
    R_norm = R / (np.linalg.norm(R, axis=1, keepdims=True) + 1e-10)
    S_norm = S / (np.linalg.norm(S, axis=1, keepdims=True) + 1e-10)
    trigger_sims = T_norm @ S_norm.T
    response_sims = R_norm @ S_norm.T

    def _assign(pair, keys):
        pair["scenario_keys"] = keys
        pair["scenario_key"] = keys[0]
        pair["scenario_id"] = scenario_map[keys[0]]["scenario_id"]

    def _response_rescue(i):
        r_kept = _topk_pick(
            response_sims[i], scenario_keys, is_sink,
            tuning.max_scenarios_per_pair, tuning.sink_rescue_relative_margin,
        )
        if r_kept is None:
            return None
        r_best_sim = float(response_sims[i][scenario_keys.index(r_kept[0])])
        if r_best_sim < tuning.sink_rescue_min_similarity:
            return None
        return r_kept

    for i, pair in enumerate(pairs):
        t_sims = trigger_sims[i]
        t_best_j = int(np.argsort(t_sims)[::-1][0])

        if strategy == "response_only":
            if is_sink[t_best_j]:
                rescued = _response_rescue(i)
                _assign(pair, rescued or [scenario_keys[t_best_j]])
            else:
                _assign(pair, _flat_pick(
                    t_sims, scenario_keys, is_sink,
                    tuning.max_scenarios_per_pair, tuning.relative_margin,
                ))
        elif strategy == "or_rule":
            if float(t_sims[t_best_j]) < tuning.sink_rescue_min_similarity:
                rescued = _response_rescue(i)
                if rescued is not None:
                    _assign(pair, rescued)
                    continue
            _assign(pair, _flat_pick(
                t_sims, scenario_keys, is_sink,
                tuning.max_scenarios_per_pair, tuning.relative_margin,
            ))
        elif strategy == "blended":
            alpha = tuning.sink_rescue_blend_alpha
            blend = alpha * T_norm[i] + (1.0 - alpha) * R_norm[i]
            blend = blend / (np.linalg.norm(blend) + 1e-10)
            blend_sims = S_norm @ blend
            _assign(pair, _flat_pick(
                blend_sims, scenario_keys, is_sink,
                tuning.max_scenarios_per_pair, tuning.relative_margin,
            ))
        else:
            raise ValueError(f"unknown sink-rescue strategy: {strategy!r}")

    return trigger_vecs, response_vecs


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
