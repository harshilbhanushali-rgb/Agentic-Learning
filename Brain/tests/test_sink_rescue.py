"""Layer B sink-rescue: response_only / or_rule / blended.

See docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md.
UNCALIBRATED as of 2026-08-04 -- sink_rescue_relative_margin, sink_rescue_min_similarity,
and sink_rescue_blend_alpha are all placeholders. Like test_layer_b_assignment.py, vectors
here are hand-built orthogonal unit axes so cosine similarities are exact and the assertions
test the RULE, not the embedding model.

Unlike test_layer_b_assignment.py's _pair(), every pair here needs a real response_text
because assign_scenarios_with_sink_rescue embeds and matches on it -- there is no harmless
placeholder string.
"""
import numpy as np
import pytest

from preprocessing import embedder
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


def _pair(trigger, response):
    return {"trigger_text": trigger, "response_text": response,
            "scenario_key": None, "scenario_id": None}


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
        is far too weak to clear sink_rescue_min_similarity -- must stay in the sink."""
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
        sink_rescue_min_similarity even though it's non-sink -- or_rule must let
        the response's confident, different pick ('pricing') override it."""
        floor = load_tuning().layer_b.sink_rescue_min_similarity
        assert floor > 0.0, "test assumes a positive floor to demonstrate an override"

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


class TestUnknownSinkRescueStrategy:
    def test_raises_on_unrecognised_strategy(self, fake_embeddings):
        pairs = [_pair("pricing:1.0", "quality:1.0")]
        with pytest.raises(ValueError, match="unknown sink-rescue strategy"):
            layer_b.assign_scenarios_with_sink_rescue(
                pairs, _scenario_map(), config=None, strategy="bogus",
            )
