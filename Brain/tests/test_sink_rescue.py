"""Layer B sink-rescue: response_only / or_rule / blended.

See docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md.
UNCALIBRATED as of 2026-08-04 -- sink_rescue_relative_margin, sink_rescue_response_min_similarity,
sink_rescue_trigger_weak_floor, and sink_rescue_blend_alpha are all placeholders. Like
test_layer_b_assignment.py, vectors here are hand-built orthogonal unit axes so cosine
similarities are exact and the assertions test the RULE, not the embedding model.

Unlike test_layer_b_assignment.py's _pair(), every pair here needs a real response_text
because assign_scenarios_with_sink_rescue embeds and matches on it -- there is no harmless
placeholder string.
"""
import numpy as np
import pytest

from preprocessing import embedder
from preprocessing.transcript_parser import SpeakerRole, Turn
from shared.tuning import load_tuning
from v1 import layer_b

# "noise" has no corresponding scenario -- it exists purely so a trigger/response
# can be diluted (weak absolute similarity to every real axis) without its
# argmax accidentally landing on "ack" just because "ack" is one of only 3
# scenario-bearing axes. Task 3's or_rule tests need this to build a trigger
# whose own best match is non-sink but weak.
_AXIS_INDEX = {name: i for i, name in enumerate(["pricing", "quality", "ack", "noise"])}


def _unit(v):
    a = np.asarray(v, dtype=np.float32)
    return (a / np.linalg.norm(a)).tolist()


@pytest.fixture
def fake_embeddings(monkeypatch):
    def resolve(text):
        vec = np.zeros(len(_AXIS_INDEX), dtype=np.float32)
        found = False
        for token in text.split():
            name, _, weight = token.partition(":")
            if name in _AXIS_INDEX:
                vec[_AXIS_INDEX[name]] += float(weight or 1.0)
                found = True
        if not found:
            raise AssertionError(f"test text names no known axis: {text!r}")
        return _unit(vec)

    monkeypatch.setattr(embedder, "embed_query", lambda texts: [resolve(t) for t in texts])
    monkeypatch.setattr(embedder, "embed_document", lambda texts: [resolve(t) for t in texts])


def _scenario_map():
    return {
        "pricing": {"scenario_id": 1, "business_description": "pricing", "keyphrases": [],
                    "is_coachable": True},
        "quality": {"scenario_id": 2, "business_description": "quality", "keyphrases": [],
                    "is_coachable": True},
        "ack": {"scenario_id": 3, "business_description": "ack", "keyphrases": [],
                "is_coachable": False},
    }


def _pair(trigger, response, turn_index=1):
    return {"trigger_text": trigger, "response_text": response,
            "scenario_key": None, "scenario_id": None, "turn_index": turn_index}


def _turn(index, role, text):
    return Turn(index=index, speaker_raw=role.value, role=role, text=text, call_id="c1")


class TestResponseOnly:
    def test_rescues_when_response_clears_margin_and_floor(self, fake_embeddings):
        """Trigger alone would sink (matches 'ack'); response clearly matches a
        real scenario -- the pair must be rescued there instead."""
        pairs = [_pair("ack:1.0", "pricing:1.0")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="response_only",
        )
        assert pairs[0]["scenario_keys"] == ["pricing"]
        assert pairs[0]["scenario_id"] == 1

    def test_stays_in_sink_when_response_is_also_weak(self, fake_embeddings):
        """Trigger matches 'ack'; response's own best non-sink match ('pricing')
        is far too weak to clear sink_rescue_response_min_similarity -- must stay in the sink."""
        pairs = [_pair("ack:1.0", "ack:1.0 pricing:0.05")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="response_only",
        )
        assert pairs[0]["scenario_keys"] == ["ack"]
        assert pairs[0]["scenario_id"] == 3

    def test_non_sink_pair_is_unaffected_by_response(self, fake_embeddings):
        """Trigger already matches a real scenario -- response_only must not
        second-guess it, no matter what the response says."""
        pairs = [_pair("pricing:1.0", "quality:1.0")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="response_only",
        )
        assert pairs[0]["scenario_keys"] == ["pricing"]

    def test_every_pair_is_always_assigned(self, fake_embeddings):
        pairs = [
            _pair("pricing:1.0", "quality:1.0"),
            _pair("ack:1.0", "pricing:1.0"),
            _pair("ack:1.0", "ack:1.0"),
        ]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="response_only",
        )
        assert all(p["scenario_key"] is not None for p in pairs)
        assert all(p["scenario_id"] is not None for p in pairs)

    def test_returns_trigger_and_response_vecs_for_reuse(self, fake_embeddings):
        pairs = [_pair("pricing:1.0", "quality:1.0"), _pair("ack:1.0", "pricing:1.0")]
        trigger_vecs, response_vecs = layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="response_only",
        )
        assert len(trigger_vecs) == 2
        assert len(response_vecs) == 2


class TestOrRule:
    _WEAK_TRIGGER = "quality:1.0 pricing:0.99 noise:1.5"
    # "noise" dilutes the vector's norm without corresponding to any scenario, so
    # the trigger's own best match (quality, cosine ~0.486) stays non-sink but
    # lands below the 0.50 floor -- unlike a plain "ack:1.5" component, which
    # would just make the sink itself the argmax and test a different case.

    def test_overrides_a_weak_non_sink_trigger_with_a_confident_response(self, fake_embeddings):
        """Trigger's own top1 ('quality', by a hair over 'pricing') sits below
        sink_rescue_trigger_weak_floor even though it's non-sink -- or_rule must let
        the response's confident, different pick ('pricing') override it."""
        floor = load_tuning().layer_b.sink_rescue_trigger_weak_floor
        # This fixture's fixed _WEAK_TRIGGER vector cosines to ~0.486 against its own
        # best-matching scenario ("quality") -- hand-verified, see _WEAK_TRIGGER's own
        # comment above. The floor must stay strictly above that value for this test to
        # demonstrate an override at all; a retune outside this range needs the fixed
        # vectors re-checked (mirrors TestBlended.test_can_flip_the_sink_decision_itself's
        # own alpha-range guard below).
        assert 0.486 < floor < 1.0, (
            "sink_rescue_trigger_weak_floor moved outside the range this test's fixed "
            "_WEAK_TRIGGER vector (cosine ~0.486 to its own best match) was verified against"
        )

        from v1.layer_b import assign_scenarios
        flat_pairs = [{"trigger_text": self._WEAK_TRIGGER, "response_text": "r",
                       "scenario_key": None, "scenario_id": None}]
        assign_scenarios(flat_pairs, _scenario_map(), config=None)
        assert flat_pairs[0]["scenario_key"] == "quality", (
            "sanity check: flat matching's own top-1 pick for this trigger is 'quality'"
        )

        pairs = [_pair(self._WEAK_TRIGGER, "pricing:1.0")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="or_rule",
        )
        assert pairs[0]["scenario_keys"] == ["pricing"]

    def test_leaves_a_confident_trigger_pick_unchanged(self, fake_embeddings):
        """Trigger's top1 ('pricing') is a clean, confident match -- or_rule must
        not second-guess it even though the response disagrees."""
        pairs = [_pair("pricing:1.0", "quality:1.0")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="or_rule",
        )
        assert pairs[0]["scenario_keys"] == ["pricing"]

    def test_falls_back_to_flat_when_response_cannot_rescue_either(self, fake_embeddings):
        """Trigger's top1 is weak AND the response's own best match is also weak
        -- or_rule must fall back to today's flat behaviour rather than leaving
        the pair unassigned."""
        pairs = [_pair(self._WEAK_TRIGGER, "ack:1.0 pricing:0.05")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="or_rule",
        )
        assert pairs[0]["scenario_key"] is not None


class TestBlended:
    def test_can_flip_the_sink_decision_itself(self, fake_embeddings):
        """Trigger alone ('ack' 1.0, 'pricing' 0.6) would flat-match the sink
        'ack' -- sanity-checked below via the real assign_scenarios. A strongly
        agreeing response ('pricing' 1.0) blended in at sink_rescue_blend_alpha's
        current placeholder (0.6) is enough to flip the best match to 'pricing'.
        This is the one behaviour unique to 'blended': the other two strategies
        can only ever move a pair OUT of a sink after the fact, never change
        which scenario the trigger alone would have picked."""
        alpha = load_tuning().layer_b.sink_rescue_blend_alpha
        assert 0.5 < alpha < 1.0, (
            "this test's fixed vectors were hand-verified to flip at alpha=0.6; "
            "a retune outside this range needs the vectors re-checked"
        )
        trigger = "ack:1.0 pricing:0.6"

        from v1.layer_b import assign_scenarios
        flat_pairs = [{"trigger_text": trigger, "response_text": "r",
                       "scenario_key": None, "scenario_id": None}]
        assign_scenarios(flat_pairs, _scenario_map(), config=None)
        assert flat_pairs[0]["scenario_keys"] == ["ack"], (
            "sanity check: trigger alone must flat-match the sink"
        )

        pairs = [_pair(trigger, "pricing:1.0")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="blended",
        )
        assert pairs[0]["scenario_keys"] == ["pricing"]

    def test_does_not_flip_when_response_is_irrelevant(self, fake_embeddings):
        """Same trigger as above, but the response doesn't reinforce a real
        scenario -- the blend must still land on the sink."""
        pairs = [_pair("ack:1.0 pricing:0.6", "quality:1.0")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="blended",
        )
        assert pairs[0]["scenario_keys"] == ["ack"]

    def test_every_pair_is_always_assigned(self, fake_embeddings):
        pairs = [
            _pair("pricing:1.0", "quality:1.0"),
            _pair("ack:1.0 pricing:0.6", "pricing:1.0"),
            _pair("ack:1.0", "ack:1.0"),
        ]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="blended",
        )
        assert all(p["scenario_key"] is not None for p in pairs)


class TestContentGateNarrow:
    """Status update 3's pivot: the gate deciding whether to look at the
    response is concrete_content_density (+ preceding_turn_is_question as a
    borderline tie-break only), not a cosine floor. Routing once gated in is
    untouched -- still _topk_pick on the response embedding.

    The three signal functions are monkeypatched to fixed values so these
    tests check the GATE's rule, not shared/trigger_quality.py's own NLP
    behaviour (that module has its own tests) or today's UNCALIBRATED
    placeholder threshold values -- mirrors how test_layer_b_assignment.py
    mocks the embedder instead of testing a real embedding model.
    """

    def _patch(self, monkeypatch, *, word_count, density, is_question=None):
        def _boom(*a, **k):
            raise AssertionError("preceding_turn_is_question must not be called here")

        monkeypatch.setattr(layer_b.tq, "content_word_count", lambda text: word_count)
        monkeypatch.setattr(layer_b.tq, "concrete_content_density", lambda text: density)
        monkeypatch.setattr(
            layer_b.tq, "preceding_turn_is_question",
            (lambda turns, idx: is_question) if is_question is not None else _boom,
        )

    def test_high_density_rescues_without_consulting_question_signal(self, fake_embeddings, monkeypatch):
        tuning = load_tuning().layer_b
        self._patch(monkeypatch, word_count=tuning.sink_rescue_density_min_words + 5,
                    density=tuning.sink_rescue_density_threshold + 0.1)
        pairs = [_pair("ack:1.0", "pricing:1.0")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_narrow", turns=None,
        )
        assert pairs[0]["scenario_keys"] == ["pricing"]

    def test_low_density_never_rescues_without_consulting_question_signal(self, fake_embeddings, monkeypatch):
        tuning = load_tuning().layer_b
        self._patch(monkeypatch, word_count=tuning.sink_rescue_density_min_words + 5,
                    density=tuning.sink_rescue_density_borderline_floor - 0.05)
        pairs = [_pair("ack:1.0", "pricing:1.0")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_narrow", turns=None,
        )
        assert pairs[0]["scenario_keys"] == ["ack"]

    def test_borderline_density_rescues_only_when_preceding_turn_is_a_question(self, fake_embeddings, monkeypatch):
        tuning = load_tuning().layer_b
        midpoint = (tuning.sink_rescue_density_threshold + tuning.sink_rescue_density_borderline_floor) / 2.0
        turns = [_turn(0, SpeakerRole.NAREN, "What do you think?"), _turn(1, SpeakerRole.CLIENT, "ack")]

        self._patch(monkeypatch, word_count=tuning.sink_rescue_density_min_words + 5,
                    density=midpoint, is_question=True)
        pairs = [_pair("ack:1.0", "pricing:1.0", turn_index=1)]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_narrow", turns=turns,
        )
        assert pairs[0]["scenario_keys"] == ["pricing"]

        self._patch(monkeypatch, word_count=tuning.sink_rescue_density_min_words + 5,
                    density=midpoint, is_question=False)
        pairs = [_pair("ack:1.0", "pricing:1.0", turn_index=1)]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_narrow", turns=turns,
        )
        assert pairs[0]["scenario_keys"] == ["ack"]

    def test_too_short_a_response_never_rescues_regardless_of_density(self, fake_embeddings, monkeypatch):
        tuning = load_tuning().layer_b
        # density is set to a clearly-rescuing value on purpose -- the length
        # guard must short-circuit before density is ever consulted.
        self._patch(monkeypatch, word_count=max(tuning.sink_rescue_density_min_words - 1, 0),
                    density=tuning.sink_rescue_density_threshold + 0.5, is_question=True)
        pairs = [_pair("ack:1.0", "pricing:1.0")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_narrow", turns=None,
        )
        assert pairs[0]["scenario_keys"] == ["ack"]

    def test_non_sink_pair_is_unaffected(self, fake_embeddings, monkeypatch):
        tuning = load_tuning().layer_b
        self._patch(monkeypatch, word_count=0, density=0.0)
        pairs = [_pair("pricing:1.0", "quality:1.0")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_narrow", turns=None,
        )
        assert pairs[0]["scenario_keys"] == ["pricing"]

    def test_every_pair_is_always_assigned(self, fake_embeddings, monkeypatch):
        tuning = load_tuning().layer_b
        self._patch(monkeypatch, word_count=tuning.sink_rescue_density_min_words + 5,
                    density=tuning.sink_rescue_density_threshold + 0.1)
        pairs = [
            _pair("pricing:1.0", "quality:1.0"),
            _pair("ack:1.0", "pricing:1.0"),
            _pair("ack:1.0", "ack:1.0"),
        ]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_narrow", turns=None,
        )
        assert all(p["scenario_key"] is not None for p in pairs)


class TestUnknownSinkRescueStrategy:
    def test_raises_on_unrecognised_strategy(self, fake_embeddings):
        pairs = [_pair("pricing:1.0", "quality:1.0")]
        with pytest.raises(ValueError, match="unknown sink-rescue strategy"):
            layer_b.assign_scenarios_with_sink_rescue(
                pairs, _scenario_map(), config=None, strategy="bogus",
            )
