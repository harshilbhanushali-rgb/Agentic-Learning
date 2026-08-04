"""shared/trigger_quality.py -- content signals shared by the sink-rescue design
(docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md, Status update 3)
and the trigger-quality-gate design
(docs/superpowers/specs/2026-08-04-layer-b-trigger-quality-gate-design.md).
Real spaCy runs here (these are structural/linguistic properties, not embeddings) --
this tests the signal functions themselves, not their callers.
"""
import pytest

from preprocessing.transcript_parser import Turn, SpeakerRole
from shared.trigger_quality import (
    concrete_entity_density,
    preceding_turn_is_question,
    sink_real_margin,
    trigger_response_coupling,
)


def test_concrete_entity_density_high_for_specific_text():
    text = "We use Workday and Phenom in Chicago with about 30 recruiters."
    assert concrete_entity_density(text) > 0.0


def test_concrete_entity_density_zero_for_generic_filler():
    text = "Yeah, I think that sounds fine to me, whatever works for you guys."
    assert concrete_entity_density(text) == 0.0


def _turn(index, role, text):
    return Turn(index=index, speaker_raw=role.value, role=role, text=text, call_id="test")


def test_preceding_turn_is_question_true_for_question_mark():
    turns = [
        _turn(0, SpeakerRole.NAREN, "Which ATS are you currently using?"),
        _turn(1, SpeakerRole.CLIENT, "We use Workday."),
    ]
    assert preceding_turn_is_question(turns, 1) is True


def test_preceding_turn_is_question_true_for_wh_word_without_mark():
    turns = [
        _turn(0, SpeakerRole.NAREN, "What tools you use day to day"),
        _turn(1, SpeakerRole.CLIENT, "We use Workday."),
    ]
    assert preceding_turn_is_question(turns, 1) is True


def test_preceding_turn_is_question_false_for_statement():
    turns = [
        _turn(0, SpeakerRole.NAREN, "That makes sense, thanks for confirming."),
        _turn(1, SpeakerRole.CLIENT, "Yeah, no problem."),
    ]
    assert preceding_turn_is_question(turns, 1) is False


def test_preceding_turn_is_question_false_when_prior_turn_is_not_naren():
    turns = [
        _turn(0, SpeakerRole.CLIENT, "What do you think?"),
        _turn(1, SpeakerRole.CLIENT, "Anyway, moving on."),
    ]
    assert preceding_turn_is_question(turns, 1) is False


def test_preceding_turn_is_question_false_at_index_zero():
    turns = [_turn(0, SpeakerRole.CLIENT, "Hello")]
    assert preceding_turn_is_question(turns, 0) is False


def test_sink_real_margin_identical_to_sink_orthogonal_to_real():
    trigger = [1.0, 0.0, 0.0]
    sink_centroids = [[1.0, 0.0, 0.0]]      # cos == 1.0
    real_centroids = [[0.0, 1.0, 0.0]]      # cos == 0.0
    assert sink_real_margin(trigger, sink_centroids, real_centroids) == pytest.approx(1.0)


def test_sink_real_margin_negative_when_real_dominates():
    trigger = [0.0, 1.0, 0.0]
    sink_centroids = [[1.0, 0.0, 0.0]]      # cos == 0.0
    real_centroids = [[0.0, 1.0, 0.0]]      # cos == 1.0
    assert sink_real_margin(trigger, sink_centroids, real_centroids) == pytest.approx(-1.0)


def test_trigger_response_coupling_identical_vectors():
    v = [1.0, 2.0, 3.0]
    assert trigger_response_coupling(v, v) == pytest.approx(1.0)


def test_trigger_response_coupling_orthogonal_vectors():
    assert trigger_response_coupling([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
