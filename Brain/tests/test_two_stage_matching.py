"""Unit tests for Layer B's two-stage (primary-topic-first) matching.

UNCALIBRATED as of 2026-07-30 -- see
docs/superpowers/specs/2026-07-30-layer-b-two-stage-matching-design.md. Like
test_layer_b_assignment.py, vectors here are hand-built orthogonal unit axes so
cosine similarities are exact and the assertions test the RULE, not the
embedding model.
"""
import numpy as np
import pytest

from preprocessing import embedder
from shared.tuning import load_tuning
from v1 import layer_b


def _unit(v):
    a = np.asarray(v, dtype=np.float32)
    return (a / np.linalg.norm(a)).tolist()


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Resolve any text to a vector by summing the named axis weights in it.

    Axis names are arbitrary strings (not a fixed set), so each test can
    define its own axes for the scenario/primary-topic space it needs.
    """
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


# Global axis registry: assigns each named axis a fixed dimension index, shared
# across all tests in this module (unused axes for a given test just get zero
# weight, which is harmless since every real vector here is sparse anyway).
_AXIS_INDEX = {
    name: i for i, name in enumerate([
        "a", "b", "x_content", "y_content", "x_parent", "y_parent",
        "sink_axis", "other_axis",
    ])
}


def _scenario(scenario_id, business_description, primary_topic_key, is_coachable=True):
    return {
        "scenario_id": scenario_id,
        "business_description": business_description,
        "keyphrases": [],
        "is_coachable": is_coachable,
        "primary_topic_key": primary_topic_key,
    }


def _primary_topic(description):
    return {"label": description, "description": description, "keyphrases": []}


def _pair(trigger):
    return {"trigger_text": trigger, "response_text": "r",
            "scenario_key": None, "scenario_id": None}


class TestStrict:
    def _recall_loss_setup(self):
        # sub_a's own vector is axis "a" and it is the RAW best match for a
        # pure-"a" trigger. But sub_a's parent primary_topic (pt_y) is labeled
        # with text "b" -- a plausible Gemma-generated label that does not
        # resemble its own member's content -- while sub_b's parent (pt_x) is
        # labeled "a" and so wins stage 1 despite sub_b's own vector (axis "b")
        # having zero similarity to the trigger. Strict must follow stage 1
        # into pt_x and can therefore lose sub_a entirely.
        scenario_map = {
            "sub_a": _scenario(1, "a", primary_topic_key="pt_y"),
            "sub_b": _scenario(2, "b", primary_topic_key="pt_x"),
        }
        primary_topic_map = {
            "pt_x": _primary_topic("a"),
            "pt_y": _primary_topic("b"),
        }
        return scenario_map, primary_topic_map

    def test_flat_raw_best_match_is_sub_a(self, fake_embeddings):
        """Sanity check: flat matching (today's production behaviour) picks the
        true best subtopic, sub_a, for a pure-"a" trigger."""
        scenario_map, _ = self._recall_loss_setup()
        pairs = [_pair("a")]
        layer_b.assign_scenarios(pairs, scenario_map, config=None)
        assert pairs[0]["scenario_keys"] == ["sub_a"]

    def test_strict_can_lose_the_correct_subtopic(self, fake_embeddings):
        """Concrete demonstration of the design's central risk: when the wrong
        primary_topic wins stage 1, strict's hard filter loses the correct
        subtopic entirely -- it is never a candidate in stage 2."""
        scenario_map, primary_topic_map = self._recall_loss_setup()
        pairs = [_pair("a")]
        layer_b.assign_scenarios_two_stage(
            pairs, scenario_map, primary_topic_map, config=None, strategy="strict",
        )
        assert pairs[0]["scenario_keys"] == ["sub_b"]
        assert pairs[0]["scenario_keys"] != ["sub_a"]

    def test_strict_restricts_within_the_correctly_kept_primary_topic(self, fake_embeddings):
        """When stage 1 keeps the RIGHT primary_topic, strict matches flat."""
        scenario_map = {
            "sub_a": _scenario(1, "a", primary_topic_key="pt_x"),
            "sub_b": _scenario(2, "b", primary_topic_key="pt_y"),
        }
        primary_topic_map = {
            "pt_x": _primary_topic("a"),
            "pt_y": _primary_topic("b"),
        }
        pairs = [_pair("a")]
        layer_b.assign_scenarios_two_stage(
            pairs, scenario_map, primary_topic_map, config=None, strategy="strict",
        )
        assert pairs[0]["scenario_keys"] == ["sub_a"]

    def test_sink_short_circuit_ignores_primary_topic_stage(self, fake_embeddings):
        """A junk trigger whose raw best match is a sink must still file there
        alone, exactly like flat -- the primary_topic stage never runs for it."""
        scenario_map = {
            "sink": _scenario(1, "a", primary_topic_key="pt_x", is_coachable=False),
            "real": _scenario(2, "b", primary_topic_key="pt_y"),
        }
        primary_topic_map = {
            "pt_x": _primary_topic("a"),
            "pt_y": _primary_topic("b"),
        }
        pairs = [_pair("a")]
        layer_b.assign_scenarios_two_stage(
            pairs, scenario_map, primary_topic_map, config=None, strategy="strict",
        )
        assert pairs[0]["scenario_keys"] == ["sink"]


class TestSoft:
    def test_blended_score_can_outrank_a_better_raw_match(self, fake_embeddings):
        # sub_x: own vector = x_content, parent pt_x = x_parent (strong match).
        # sub_y: own vector = y_content, parent pt_y = y_parent (weak match).
        # Trigger weights are chosen so sub_y's OWN cosine is slightly better
        # than sub_x's, but pt_x's parent match is strong enough that the
        # blended score (own x parent) flips the ranking.
        scenario_map = {
            "sub_x": _scenario(1, "x_content", primary_topic_key="pt_x"),
            "sub_y": _scenario(2, "y_content", primary_topic_key="pt_y"),
        }
        primary_topic_map = {
            "pt_x": _primary_topic("x_parent"),
            "pt_y": _primary_topic("y_parent"),
        }
        trigger = "x_content:0.8 y_content:0.9 x_parent:0.9 y_parent:0.3"
        pairs = [_pair(trigger)]

        # Sanity check: flat (raw similarity only) ranks sub_y above sub_x.
        flat_pairs = [_pair(trigger)]
        layer_b.assign_scenarios(flat_pairs, scenario_map, config=None)
        assert flat_pairs[0]["scenario_key"] == "sub_y"

        layer_b.assign_scenarios_two_stage(
            pairs, scenario_map, primary_topic_map, config=None, strategy="soft",
        )
        assert pairs[0]["scenario_key"] == "sub_x"

    def test_sink_short_circuit_uses_raw_similarity_not_blended_score(self, fake_embeddings):
        scenario_map = {
            "junk": _scenario(1, "sink_axis", primary_topic_key="pt_j", is_coachable=False),
            "real": _scenario(2, "other_axis", primary_topic_key="pt_r"),
        }
        primary_topic_map = {
            "pt_j": _primary_topic("other_axis"),  # deliberately mismatched
            "pt_r": _primary_topic("sink_axis"),   # would win stage 1 if it ran
        }
        pairs = [_pair("sink_axis:1.0 other_axis:0.01")]
        layer_b.assign_scenarios_two_stage(
            pairs, scenario_map, primary_topic_map, config=None, strategy="soft",
        )
        assert pairs[0]["scenario_keys"] == ["junk"]


class TestFallback:
    def _recall_loss_setup(self):
        scenario_map = {
            "sub_a": _scenario(1, "a", primary_topic_key="pt_y"),
            "sub_b": _scenario(2, "b", primary_topic_key="pt_x"),
        }
        primary_topic_map = {
            "pt_x": _primary_topic("a"),
            "pt_y": _primary_topic("b"),
        }
        return scenario_map, primary_topic_map

    def test_reroutes_to_flat_when_strict_pick_is_weak(self, fake_embeddings):
        """Strict's pick (sub_b) has raw cosine 0.0 to a pure-"a" trigger --
        comfortably below two_stage_fallback_floor -- so fallback must discard
        it and use flat's pick (sub_a) instead."""
        floor = load_tuning().layer_b.two_stage_fallback_floor
        assert floor > 0.0, "test assumes a positive floor to demonstrate a reroute"
        scenario_map, primary_topic_map = self._recall_loss_setup()
        pairs = [_pair("a")]
        layer_b.assign_scenarios_two_stage(
            pairs, scenario_map, primary_topic_map, config=None, strategy="fallback",
        )
        assert pairs[0]["scenario_keys"] == ["sub_a"]

    def test_keeps_strict_pick_when_it_is_strong(self, fake_embeddings):
        """When stage 1 keeps the right primary_topic, strict's pick has a
        strong raw match and fallback must not reroute it."""
        floor = load_tuning().layer_b.two_stage_fallback_floor
        scenario_map = {
            "sub_a": _scenario(1, "a", primary_topic_key="pt_x"),
            "sub_b": _scenario(2, "b", primary_topic_key="pt_y"),
        }
        primary_topic_map = {
            "pt_x": _primary_topic("a"),
            "pt_y": _primary_topic("b"),
        }
        pairs = [_pair("a")]
        layer_b.assign_scenarios_two_stage(
            pairs, scenario_map, primary_topic_map, config=None, strategy="fallback",
        )
        assert pairs[0]["scenario_keys"] == ["sub_a"]
        # sub_a's raw cosine to a pure "a" trigger is 1.0, comfortably above
        # any sane floor -- pin that assumption explicitly.
        assert 1.0 >= floor


class TestUnknownStrategy:
    def test_raises_on_unrecognised_strategy(self, fake_embeddings):
        scenario_map = {"sub_a": _scenario(1, "a", primary_topic_key="pt_x")}
        primary_topic_map = {"pt_x": _primary_topic("a")}
        pairs = [_pair("a")]
        with pytest.raises(ValueError, match="unknown matching strategy"):
            layer_b.assign_scenarios_two_stage(
                pairs, scenario_map, primary_topic_map, config=None, strategy="bogus",
            )
