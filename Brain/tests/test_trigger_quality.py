"""Unit tests for shared/trigger_quality.py.

concrete_content_density and preceding_turn_is_question operate on real text via
spaCy, so they're tested with real short strings rather than mocks -- exact
expected values were measured against the actual model first (see the
concrete_content_density docstring in both design docs for the noun-chunk
pronoun-exclusion finding this uncovered). sink_real_margin and
trigger_response_coupling are pure vector math, tested with hand-built
orthogonal unit axes so the cosine similarities are exact, same style as
test_cluster_evidence.py / test_layer_b_assignment.py.
"""
import numpy as np
import pytest

from preprocessing.transcript_parser import SpeakerRole, Turn
from shared import trigger_quality as tq


def _vec(*components):
    return np.array(components, dtype=np.float32)


def _turn(index, role, text):
    return Turn(index=index, speaker_raw=role.value, role=role, text=text, call_id="c1")


class TestContentWordCount:
    def test_counts_non_stop_alphabetic_tokens(self):
        assert tq.content_word_count("We segment bids by device type and adjust weekly.") == 6

    def test_all_stopword_text_is_zero(self):
        assert tq.content_word_count("the a is of to") == 0


class TestConcreteContentDensity:
    def test_pure_filler_scores_zero(self):
        assert tq.concrete_content_density("Yeah, I think so. Sounds good to me.") == pytest.approx(0.0)

    def test_specific_but_entity_free_response_scores_above_zero(self):
        text = "We segment bids by device type and adjust weekly based on conversion lag."
        assert tq.concrete_content_density(text) > 0.0

    def test_entity_rich_response_scores_higher_than_entity_free(self):
        entity_rich = "We use 30 languages, but only 3 or 4 primarily, mostly through Broadbean and Aperture."
        entity_free = "We segment bids by device type and adjust weekly based on conversion lag."
        assert tq.concrete_content_density(entity_rich) > tq.concrete_content_density(entity_free)

    def test_entity_free_but_specific_beats_pure_filler(self):
        # This is the exact gap concrete_entity_density alone would have missed --
        # the whole reason the noun-chunk term was added to this design.
        filler = "Yeah, I think so. Sounds good to me."
        entity_free = "We segment bids by device type and adjust weekly based on conversion lag."
        assert tq.concrete_content_density(entity_free) > tq.concrete_content_density(filler)

    def test_all_stopword_text_returns_zero_not_a_crash(self):
        # Zero content words -- the ratio's denominator would be zero.
        assert tq.concrete_content_density("the a is of to") == pytest.approx(0.0)


class TestPrecedingTurnIsQuestion:
    def test_question_mark_is_detected(self):
        turns = [_turn(0, SpeakerRole.NAREN, "What time works best for you?"),
                 _turn(1, SpeakerRole.CLIENT, "Tuesday works.")]
        assert tq.preceding_turn_is_question(turns, 1) is True

    def test_auxiliary_inversion_without_question_mark_is_detected(self):
        # Real transcripts drop terminal punctuation constantly -- the grammatical
        # check must not depend on '?' being present.
        turns = [_turn(0, SpeakerRole.NAREN, "Do you have a preference on that"),
                 _turn(1, SpeakerRole.CLIENT, "Not really.")]
        assert tq.preceding_turn_is_question(turns, 1) is True

    def test_statement_is_not_a_question(self):
        turns = [_turn(0, SpeakerRole.NAREN, "I will send that over after the call."),
                 _turn(1, SpeakerRole.CLIENT, "Great, thanks.")]
        assert tq.preceding_turn_is_question(turns, 1) is False

    def test_imperative_is_not_a_question(self):
        turns = [_turn(0, SpeakerRole.NAREN, "Send that over after the call."),
                 _turn(1, SpeakerRole.CLIENT, "Will do.")]
        assert tq.preceding_turn_is_question(turns, 1) is False

    def test_non_naren_prior_turn_is_never_a_question(self):
        # A JOVEO_OTHER colleague asking a question doesn't count -- the signal
        # describes Naren's own conversational position, not anyone else's.
        turns = [_turn(0, SpeakerRole.JOVEO_OTHER, "What time works best for you?"),
                 _turn(1, SpeakerRole.CLIENT, "Tuesday works.")]
        assert tq.preceding_turn_is_question(turns, 1) is False

    def test_first_turn_has_no_preceding_turn(self):
        turns = [_turn(0, SpeakerRole.CLIENT, "Hey, quick question.")]
        assert tq.preceding_turn_is_question(turns, 0) is False


class TestSinkRealMargin:
    _sinks = _vec(1.0, 0.0, 0.0).reshape(1, 3)
    _reals = _vec(0.0, 1.0, 0.0).reshape(1, 3)

    def test_positive_when_closer_to_sink(self):
        trigger = _vec(0.9, 0.1, 0.0)
        margin = tq.sink_real_margin(trigger, self._sinks, self._reals)
        assert margin > 0.0

    def test_negative_when_closer_to_real(self):
        trigger = _vec(0.1, 0.9, 0.0)
        margin = tq.sink_real_margin(trigger, self._sinks, self._reals)
        assert margin < 0.0

    def test_zero_when_equidistant(self):
        trigger = _vec(1.0, 1.0, 0.0)
        margin = tq.sink_real_margin(trigger, self._sinks, self._reals)
        assert margin == pytest.approx(0.0, abs=1e-5)

    def test_rejects_empty_sink_population(self):
        with pytest.raises(ValueError, match="empty"):
            tq.sink_real_margin(_vec(1.0, 0.0, 0.0), np.empty((0, 3)), self._reals)

    def test_rejects_empty_real_population(self):
        with pytest.raises(ValueError, match="empty"):
            tq.sink_real_margin(_vec(1.0, 0.0, 0.0), self._sinks, np.empty((0, 3)))


class TestTriggerResponseCoupling:
    def test_identical_vectors_couple_perfectly(self):
        v = _vec(1.0, 1.0, 0.0)
        assert tq.trigger_response_coupling(v, v) == pytest.approx(1.0, abs=1e-5)

    def test_orthogonal_vectors_have_zero_coupling(self):
        assert tq.trigger_response_coupling(_vec(1.0, 0.0), _vec(0.0, 1.0)) == pytest.approx(0.0, abs=1e-5)

    def test_opposite_vectors_have_negative_coupling(self):
        assert tq.trigger_response_coupling(_vec(1.0, 0.0), _vec(-1.0, 0.0)) == pytest.approx(-1.0, abs=1e-5)
