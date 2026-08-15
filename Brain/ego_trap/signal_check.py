"""Step 0: detect CLIENT signals that map to a known coachable scenario.

Two modes, selected by tuning.yaml's layer_d.signal_detection_mode. They take
DIFFERENT scenario populations on purpose -- see ego_trap/scenario_pool.py for why
gemma mode must not see sinks and similarity mode must.

Every scoring/resolution step is a public function here rather than inline in a
mode, so calibration/dry_run_ego_trap.py can measure the real rule with zero Gemma
calls instead of reimplementing it. Same precedent as v2/layer_c.build_clause_pool
and shared/response_taxonomy.py.
"""
from __future__ import annotations

import difflib
import re

import numpy as np

from config import Config
from ego_trap.transcript_parser import EgoTrapRole, EgoTrapTurn, classify_response_outcome
from preprocessing import embedder
from shared import relative_match
from shared.gemma import call_gemma
from shared.prompts import PROMPT_STEP0_SIGNAL_CHECK
from shared.scenario_vectors import build_scenario_vecs
from shared.tuning import LayerDTuning

_TURN_MATCH_MODES = ("exact", "normalized", "ratio")


def _norm(text: str) -> str:
    """Case/punctuation/whitespace-insensitive form for quote matching.

    Deliberately not a stemmer or a synonym map -- it only removes the ways a quote
    can differ from its source WITHOUT differing in content (a smart quote, a
    trailing period, a doubled space). Anything beyond that needs a threshold, which
    is what 'ratio' mode is for.
    """
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def format_scenarios_block(scenario_map: dict[str, dict]) -> str:
    """The scenario menu handed to PROMPT_STEP0_SIGNAL_CHECK.

    Public so the harness can measure prompt size at different pool sizes with zero
    Gemma calls. Pass the COACHABLE map -- listing a sink here invites Gemma to
    report backchannel as a coachable signal.
    """
    return "\n".join(
        f"- {key}: {info.get('business_description', '')} "
        f"(keyphrases: {', '.join(info.get('keyphrases', []) or [])})"
        for key, info in scenario_map.items()
    )


def shortlist_scenarios(
    scenario_map: dict[str, dict], client_texts: list[str], k: int
) -> dict[str, dict]:
    """The k scenarios most similar to any client turn in this transcript.

    k <= 0 returns scenario_map unchanged, which is the shipped default: the sink
    filter alone already halves the menu and that half is validated, whereas any
    shortlist additionally trades recall for precision. Raise k only after reading
    dry_run_ego_trap.py --shortlist-sweep, which reports what fraction of the keys
    Gemma actually returned survive each k.

    Ranks by MAX similarity over turns, not mean: a scenario raised once, sharply,
    in a long call is exactly what Layer D exists to catch, and a mean would bury it.
    """
    if k <= 0 or len(scenario_map) <= k or not client_texts:
        return scenario_map
    keys, sims = _score(client_texts, scenario_map)
    best_per_scenario = sims.max(axis=0)
    top = np.argsort(best_per_scenario)[::-1][:k]
    chosen = {keys[int(j)] for j in top}
    return {key: info for key, info in scenario_map.items() if key in chosen}


def _score(
    client_texts: list[str], scenario_map: dict[str, dict]
) -> tuple[list[str], np.ndarray]:
    keys, vecs = build_scenario_vecs(scenario_map)
    sims = relative_match.cosine_sims(
        embedder.embed_query_matrix(client_texts), np.asarray(vecs)
    )
    return keys, sims


def score_client_turns(
    client_texts: list[str], scenario_map: dict[str, dict]
) -> tuple[list[str], list[bool], np.ndarray]:
    """Cosine-score every client turn against every scenario vector.

    Returns (scenario_keys, is_sink, sims) where sims is (n_turns, n_scenarios).

    Zero Gemma, zero Pinecone, zero DB, and zero network on a warm embed_cache --
    which is what lets the calibration harness sweep margins for free.

    Uses embed_query_matrix, not embed_query: the list-returning variant
    materialises millions of Python floats for corpus-sized work, which made a cache
    HIT slower than re-embedding on the GPU.

    Matches against SCENARIO vectors (business_description + keyphrases), the same
    population production layer_b.assign_scenarios matches against -- not against
    Pinecone's "triggers" namespace of stored client utterances. Those answer
    different questions, and the exemplar route has two disqualifying problems here:
    ~40% of stored triggers are themselves sink-filed, and their Pinecone metadata
    carries no is_coachable, so the sink-rejection rule below is not even expressible
    against it without a per-match DB round trip. The relative margin is also
    calibrated against the trigger-vs-scenario band that this function reproduces
    exactly; Pinecone's utterance-vs-utterance band is a third band nothing here has
    ever measured.
    """
    if not client_texts or not scenario_map:
        return [], [], np.empty((0, 0))
    keys, sims = _score(client_texts, scenario_map)
    return keys, relative_match.is_sink_flags(scenario_map, keys), sims


def select_signal(
    sims_row: np.ndarray,
    scenario_keys: list[str],
    is_sink: list[bool],
    *,
    margin: float,
    cap: int,
) -> list[str] | None:
    """The scenarios one client turn is a signal for, or None for "not a signal".

    This is layer_b's relative-margin rule with its sink short-circuit read as a
    REJECTION rather than a filing. layer_b must place every pair somewhere, so
    flat_pick returns [best] when the best match is a sink; Layer D is allowed to
    conclude a turn is nothing, which is the entire reason sinks stay in the pool.
    Take them out and the best match is a non-sink by construction, so every turn
    becomes a signal -- the old absolute-floor pathology wearing a relative margin.
    """
    if len(sims_row) == 0:
        return None
    best_j = int(np.argmax(sims_row))
    if is_sink[best_j]:
        return None
    return relative_match.topk_pick(sims_row, scenario_keys, is_sink, cap, margin)


def find_turn_index(
    turns: list[EgoTrapTurn], client_utterance: str, *, mode: str, min_ratio: float
) -> tuple[int | None, str]:
    """Locate the CLIENT turn a quoted utterance came from.

    Returns (turn_index, reason). reason is "" on success, otherwise why it failed --
    returned rather than printed so the harness can A/B modes and so
    "quoted_non_client_turn" is distinguishable from a genuine paraphrase. Today both
    look identical in the log, and the log truncates at 80 chars, which is why the
    dropped signals on record cannot be diagnosed at all.

    Only forward containment (quote inside turn) is used, never the reverse: a
    two-word turn like "Yeah." is contained in almost any long paraphrase, so the
    reverse direction needs a minimum-length guard, and that is an uncalibrated
    number. 'ratio' mode is the honest place for a number, and it is off by default.
    """
    if mode not in _TURN_MATCH_MODES:
        raise ValueError(f"unknown turn_match_mode: {mode!r}")

    target = client_utterance.strip()
    client_turns = [t for t in turns if t.role == EgoTrapRole.CLIENT]

    for t in client_turns:
        if t.text.strip() == target:
            return t.index, ""
    for t in client_turns:
        if target and target in t.text.strip():
            return t.index, ""

    if mode != "exact":
        n_target = _norm(target)
        if n_target:
            for t in client_turns:
                if _norm(t.text) == n_target:
                    return t.index, ""
            for t in client_turns:
                if n_target in _norm(t.text):
                    return t.index, ""

    if mode == "ratio":
        n_target = _norm(target)
        scored = [
            (difflib.SequenceMatcher(None, n_target, _norm(t.text)).ratio(), t.index)
            for t in client_turns
        ]
        if scored:
            ratio, index = max(scored)
            if ratio >= min_ratio:
                return index, ""

    # Free diagnostic: a quote lifted from a Joveo speaker is a different failure
    # from a paraphrase of a client, and needs no matcher to detect.
    n_target = _norm(target)
    for t in turns:
        if t.role != EgoTrapRole.CLIENT and n_target and n_target in _norm(t.text):
            return None, "quoted_non_client_turn"
    return None, "no_matching_client_turn"


def resolve_signals(
    turns: list[EgoTrapTurn],
    raw_signals: list[dict],
    *,
    mode: str,
    min_ratio: float,
) -> tuple[list[dict], list[dict]]:
    """Turn Gemma's raw signal list into located signals plus a rejection list.

    Public and side-effect-free so the harness can replay a PERSISTED Gemma response
    through this exact function under every turn_match_mode -- making the matcher
    choice measurable without spending a single new Gemma call.
    """
    resolved: list[dict] = []
    unresolved: list[dict] = []
    for s in raw_signals:
        utterance = s.get("client_utterance") or ""
        key = s.get("scenario_key")
        if not utterance or not key:
            unresolved.append({
                "scenario_key": key, "client_utterance": utterance,
                "reason": "malformed_signal",
            })
            continue
        turn_index, reason = find_turn_index(
            turns, utterance, mode=mode, min_ratio=min_ratio
        )
        if turn_index is None:
            unresolved.append({
                "scenario_key": key, "client_utterance": utterance, "reason": reason,
            })
            continue
        resolved.append({
            "scenario_key": key,
            "client_utterance": utterance,
            "turn_index": turn_index,
            "response_outcome": classify_response_outcome(turns, turn_index),
        })
    return resolved, unresolved


def check_signals(
    turns: list[EgoTrapTurn],
    transcript_text: str,
    scenario_map: dict[str, dict],
    coachable_map: dict[str, dict],
    config: Config,
    tuning: LayerDTuning,
) -> list[dict]:
    """Detect CLIENT signals and who responded to each.

    Both paths return {scenario_key, client_utterance, turn_index,
    response_outcome}; similarity mode adds candidate_scenario_keys.
    response_outcome is one of "csm" / "other_joveo" / "none", computed from turn
    roles (classify_response_outcome) and never asked of the LLM, so a teammate
    answering on the CSM's behalf is not conflated with true silence. These
    transcripts carry no timestamps, so it is turn-adjacency based, not time-window
    based.

    Takes BOTH scenario populations because the two modes need opposite things:
    gemma mode is given coachable_map (a sink in the prompt invites a false signal),
    similarity mode is given the full scenario_map (a sink winning is how a turn gets
    rejected). See ego_trap/scenario_pool.py.
    """
    if tuning.signal_detection_mode == "similarity":
        return _check_via_similarity(turns, scenario_map, tuning)
    if tuning.signal_detection_mode != "gemma":
        raise ValueError(
            f"unknown signal_detection_mode: {tuning.signal_detection_mode!r}"
        )
    return _check_via_gemma(turns, transcript_text, coachable_map, config, tuning)


def _check_via_gemma(
    turns: list[EgoTrapTurn],
    transcript_text: str,
    coachable_map: dict[str, dict],
    config: Config,
    tuning: LayerDTuning,
) -> list[dict]:
    client_texts = [t.text for t in turns if t.role == EgoTrapRole.CLIENT]
    listed = shortlist_scenarios(
        coachable_map, client_texts, tuning.gemma_scenario_shortlist_k
    )
    prompt = PROMPT_STEP0_SIGNAL_CHECK.format(
        transcript_text=transcript_text,
        scenarios_text=format_scenarios_block(listed),
    )
    print(f"[Step 0] Calling Gemma for signal recognition ({len(listed)} scenario(s) listed)...")
    result = call_gemma(prompt, config.gemma_api_keys)
    raw_signals = result if isinstance(result, list) else result.get("signals_detected", [])

    resolved, unresolved = resolve_signals(
        turns, raw_signals,
        mode=tuning.turn_match_mode, min_ratio=tuning.turn_match_min_ratio,
    )
    for u in unresolved:
        print(
            f"  ! Dropped signal ({u['reason']}): "
            f"{u['client_utterance'][:120]!r} -> {u['scenario_key']!r}"
        )
    return resolved


def _check_via_similarity(
    turns: list[EgoTrapTurn],
    scenario_map: dict[str, dict],
    tuning: LayerDTuning,
) -> list[dict]:
    client_turns = [t for t in turns if t.role == EgoTrapRole.CLIENT]
    if not client_turns:
        return []

    keys, is_sink, sims = score_client_turns(
        [t.text for t in client_turns], scenario_map
    )
    if not keys:
        return []

    signals: list[dict] = []
    sink_dropped = 0
    for i, turn in enumerate(client_turns):
        kept = select_signal(
            sims[i], keys, is_sink,
            margin=tuning.similarity_relative_margin,
            cap=tuning.max_scenarios_per_signal,
        )
        if kept is None:
            sink_dropped += 1
            continue
        signals.append({
            "scenario_key": kept[0],
            "candidate_scenario_keys": kept,
            "client_utterance": turn.text,
            "turn_index": turn.index,
            "response_outcome": classify_response_outcome(turns, turn.index),
        })
    print(
        f"[Step 0] {len(client_turns)} client turn(s): "
        f"{sink_dropped} rejected (best match was a sink), {len(signals)} signal(s)."
    )
    return signals
