from __future__ import annotations
from config import Config
from ego_trap import settings
from ego_trap.transcript_parser import EgoTrapRole, EgoTrapTurn, classify_response_outcome
from preprocessing import embedder
from shared import pinecone_store
from shared.gemma import call_gemma
from shared.prompts import PROMPT_STEP0_SIGNAL_CHECK


def _find_turn_index(turns: list[EgoTrapTurn], client_utterance: str) -> int | None:
    """Locate the CLIENT turn Gemma is referring to by matching its verbatim text back."""
    target = client_utterance.strip()
    for t in turns:
        if t.role == EgoTrapRole.CLIENT and t.text.strip() == target:
            return t.index
    for t in turns:
        if t.role == EgoTrapRole.CLIENT and target in t.text.strip():
            return t.index
    return None


def check_signals(
    turns: list[EgoTrapTurn],
    transcript_text: str,
    scenario_map: dict[str, dict],
    config: Config,
) -> list[dict]:
    """Step 0: detect CLIENT signals mapping to known scenarios and who responded.

    Dispatches on settings.STEP_0_MODE ("gemma" = Option A, "similarity" = Option B).
    Both paths return the same shape: {scenario_key, client_utterance, turn_index, response_outcome}.
    response_outcome is one of "csm" / "other_joveo" / "none" — computed from turn roles
    (classify_response_outcome), not asked of the LLM, so a teammate answering on the CSM's
    behalf isn't conflated with true silence. There are no timestamps in these transcripts,
    so this is turn-adjacency based (turns_until_next_client), not time-window based.
    """
    if settings.STEP_0_MODE == "similarity":
        return _check_via_similarity(turns, config)
    return _check_via_gemma(turns, transcript_text, scenario_map, config)


def _check_via_gemma(
    turns: list[EgoTrapTurn],
    transcript_text: str,
    scenario_map: dict[str, dict],
    config: Config,
) -> list[dict]:
    scenarios_text = "\n".join(
        f"- {key}: {info.get('sub_topic', '')} (keyphrases: {', '.join(info.get('keyphrases', []))})"
        for key, info in scenario_map.items()
    )
    prompt = PROMPT_STEP0_SIGNAL_CHECK.format(
        transcript_text=transcript_text,
        scenarios_text=scenarios_text,
    )
    print("[Step 0] Calling Gemma for signal recognition check...")
    result = call_gemma(prompt, config.gemma_api_keys)
    raw_signals = result if isinstance(result, list) else result.get("signals_detected", [])

    signals = []
    for s in raw_signals:
        turn_index = _find_turn_index(turns, s["client_utterance"])
        if turn_index is None:
            print(f"  ! Could not locate client_utterance in transcript, skipping: {s['client_utterance'][:80]!r}")
            continue
        signals.append({
            "scenario_key": s["scenario_key"],
            "client_utterance": s["client_utterance"],
            "turn_index": turn_index,
            "response_outcome": classify_response_outcome(turns, turn_index),
        })
    return signals


def _check_via_similarity(turns: list[EgoTrapTurn], config: Config) -> list[dict]:
    client_turns = [t for t in turns if t.role == EgoTrapRole.CLIENT]
    if not client_turns:
        return []

    vecs = embedder.embed_query([t.text for t in client_turns])

    signals = []
    for turn, vec in zip(client_turns, vecs):
        matches = pinecone_store.query_triggers(
            config.pinecone_api_key, config.pinecone_index_name, vec, top_k=1
        )
        if not matches:
            continue
        top = matches[0]
        score = top.get("score", 0.0) if isinstance(top, dict) else getattr(top, "score", 0.0)
        if score < settings.SIMILARITY_THRESHOLD:
            continue
        metadata = top.get("metadata", {}) if isinstance(top, dict) else getattr(top, "metadata", {})
        scenario_key = metadata.get("scenario_key") or None
        if not scenario_key:
            continue

        signals.append({
            "scenario_key": scenario_key,
            "client_utterance": turn.text,
            "turn_index": turn.index,
            "response_outcome": classify_response_outcome(turns, turn.index),
        })
    return signals
