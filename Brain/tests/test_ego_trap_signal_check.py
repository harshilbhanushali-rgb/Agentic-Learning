from ego_trap import settings, signal_check
from ego_trap.transcript_parser import EgoTrapRole, EgoTrapTurn


def _turn(idx, role, text, call_id="c1"):
    return EgoTrapTurn(index=idx, speaker_raw="X", role=role, text=text, call_id=call_id)


def test_similarity_mode_detects_signal_and_response(mocker):
    mocker.patch.object(settings, "STEP_0_MODE", "similarity")
    mocker.patch.object(settings, "SIMILARITY_THRESHOLD", 0.75)
    turns = [
        _turn(0, EgoTrapRole.CLIENT, "We've been running programmatic elsewhere."),
        _turn(1, EgoTrapRole.CSM, "I understand that concern."),
    ]
    mocker.patch("ego_trap.signal_check.embedder.embed_query", return_value=[[0.1, 0.2]])
    mocker.patch(
        "ego_trap.signal_check.pinecone_store.query_triggers",
        return_value=[{"score": 0.9, "metadata": {"scenario_key": "competitive_objection"}}],
    )
    config = mocker.Mock(pinecone_api_key="k", pinecone_index_name="i")

    signals = signal_check.check_signals(turns, "raw text", {}, config)

    assert len(signals) == 1
    assert signals[0]["scenario_key"] == "competitive_objection"
    assert signals[0]["turn_index"] == 0
    assert signals[0]["response_outcome"] == "csm"


def test_similarity_mode_below_threshold_no_signal(mocker):
    mocker.patch.object(settings, "STEP_0_MODE", "similarity")
    mocker.patch.object(settings, "SIMILARITY_THRESHOLD", 0.75)
    turns = [_turn(0, EgoTrapRole.CLIENT, "Small talk.")]
    mocker.patch("ego_trap.signal_check.embedder.embed_query", return_value=[[0.1, 0.2]])
    mocker.patch(
        "ego_trap.signal_check.pinecone_store.query_triggers",
        return_value=[{"score": 0.2, "metadata": {"scenario_key": "competitive_objection"}}],
    )
    config = mocker.Mock(pinecone_api_key="k", pinecone_index_name="i")

    signals = signal_check.check_signals(turns, "raw text", {}, config)

    assert signals == []


def test_similarity_mode_no_response_before_next_client(mocker):
    mocker.patch.object(settings, "STEP_0_MODE", "similarity")
    mocker.patch.object(settings, "SIMILARITY_THRESHOLD", 0.75)
    turns = [
        _turn(0, EgoTrapRole.CLIENT, "We've been running programmatic elsewhere."),
        _turn(1, EgoTrapRole.CLIENT, "Another client turn before anyone responds."),
    ]
    mocker.patch("ego_trap.signal_check.embedder.embed_query", return_value=[[0.1, 0.2]])
    mocker.patch(
        "ego_trap.signal_check.pinecone_store.query_triggers",
        return_value=[{"score": 0.9, "metadata": {"scenario_key": "competitive_objection"}}],
    )
    config = mocker.Mock(pinecone_api_key="k", pinecone_index_name="i")

    signals = signal_check.check_signals(turns, "raw text", {}, config)

    assert signals[0]["response_outcome"] == "none"


def test_similarity_mode_other_joveo_response_is_not_csm_failure(mocker):
    """Regression test: a teammate answering must not be conflated with true CSM silence."""
    mocker.patch.object(settings, "STEP_0_MODE", "similarity")
    mocker.patch.object(settings, "SIMILARITY_THRESHOLD", 0.75)
    turns = [
        _turn(0, EgoTrapRole.CLIENT, "We've been running programmatic elsewhere."),
        _turn(1, EgoTrapRole.OTHER_JOVEO, "Let me answer that — here's how it works."),
        _turn(2, EgoTrapRole.CLIENT, "Another client turn."),
    ]
    mocker.patch("ego_trap.signal_check.embedder.embed_query", return_value=[[0.1, 0.2]])
    mocker.patch(
        "ego_trap.signal_check.pinecone_store.query_triggers",
        return_value=[{"score": 0.9, "metadata": {"scenario_key": "competitive_objection"}}],
    )
    config = mocker.Mock(pinecone_api_key="k", pinecone_index_name="i")

    signals = signal_check.check_signals(turns, "raw text", {}, config)

    assert signals[0]["response_outcome"] == "other_joveo"


def test_gemma_mode_resolves_turn_index_from_utterance(mocker):
    mocker.patch.object(settings, "STEP_0_MODE", "gemma")
    turns = [
        _turn(0, EgoTrapRole.CLIENT, "We spent a lot."),
        _turn(1, EgoTrapRole.CSM, "Understood."),
    ]
    mocker.patch(
        "ego_trap.signal_check.call_gemma",
        return_value={
            "signals_detected": [
                {
                    "scenario_key": "budget_concern",
                    "client_utterance": "We spent a lot.",
                }
            ]
        },
    )
    config = mocker.Mock(gemma_api_key="k")

    signals = signal_check.check_signals(turns, "raw text", {}, config)

    assert signals[0]["scenario_key"] == "budget_concern"
    assert signals[0]["turn_index"] == 0
    assert signals[0]["response_outcome"] == "csm"


def test_gemma_mode_response_outcome_derived_from_turns_not_llm(mocker):
    """response_outcome must come from actual turn roles, not any LLM-provided field."""
    mocker.patch.object(settings, "STEP_0_MODE", "gemma")
    turns = [
        _turn(0, EgoTrapRole.CLIENT, "We spent a lot."),
        _turn(1, EgoTrapRole.OTHER_JOVEO, "Let me take that one."),
    ]
    mocker.patch(
        "ego_trap.signal_check.call_gemma",
        return_value={
            "signals_detected": [
                {"scenario_key": "budget_concern", "client_utterance": "We spent a lot."}
            ]
        },
    )
    config = mocker.Mock(gemma_api_key="k")

    signals = signal_check.check_signals(turns, "raw text", {}, config)

    assert signals[0]["response_outcome"] == "other_joveo"


def test_gemma_mode_skips_unmatched_utterance(mocker):
    mocker.patch.object(settings, "STEP_0_MODE", "gemma")
    turns = [_turn(0, EgoTrapRole.CLIENT, "Something else entirely.")]
    mocker.patch(
        "ego_trap.signal_check.call_gemma",
        return_value={
            "signals_detected": [
                {"scenario_key": "budget_concern", "client_utterance": "Not in the transcript."}
            ]
        },
    )
    config = mocker.Mock(gemma_api_key="k")

    signals = signal_check.check_signals(turns, "raw text", {}, config)

    assert signals == []
