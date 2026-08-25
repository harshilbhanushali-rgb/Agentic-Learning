"""Relative top-K scenario assignment.

The vectors here are hand-built unit axes so the cosine similarities are exact and
the assertions test the RULE, not the embedding model. Both embed functions are
patched on preprocessing.embedder, which is the single module object that
v1.layer_b and shared.scenario_vectors both import.
"""
import numpy as np
import pytest

from preprocessing import embedder
from shared.tuning import load_tuning
from v1 import layer_b

# Scenario descriptions map to orthogonal axes; triggers are built from them.
_AXES = {
    "pricing": [1.0, 0.0, 0.0],
    "quality": [0.0, 1.0, 0.0],
    "ack": [0.0, 0.0, 1.0],
}


def _unit(v):
    a = np.asarray(v, dtype=np.float32)
    return (a / np.linalg.norm(a)).tolist()


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Resolve any text to a vector by summing the axis weights named in it."""
    def resolve(text):
        vec = np.zeros(3, dtype=np.float32)
        for token in text.split():
            name, _, weight = token.partition(":")
            if name in _AXES:
                vec += np.asarray(_AXES[name], dtype=np.float32) * float(weight or 1.0)
        if not vec.any():
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


def _pair(trigger):
    return {"trigger_text": trigger, "response_text": "r",
            "scenario_key": None, "scenario_id": None}


def test_unambiguous_trigger_gets_exactly_one_scenario(fake_embeddings):
    pairs = [_pair("pricing")]
    layer_b.assign_scenarios(pairs, _scenario_map(), config=None)
    assert pairs[0]["scenario_keys"] == ["pricing"]
    assert pairs[0]["scenario_id"] == 1


def test_ambiguous_trigger_keeps_the_near_ties(fake_embeddings):
    # For a two-axis mixture weighted 1.0 and w, the weaker match's cosine is
    # exactly w times the stronger one's -- so w is directly comparable to
    # relative_margin. Sit halfway between the margin and a perfect tie, so this
    # tests the RULE and does not need re-editing whenever the margin is retuned.
    margin = load_tuning().layer_b.relative_margin
    pairs = [_pair(f"pricing:1.0 quality:{margin + (1.0 - margin) / 2.0}")]
    layer_b.assign_scenarios(pairs, _scenario_map(), config=None)
    assert set(pairs[0]["scenario_keys"]) == {"pricing", "quality"}
    # scenario_key stays the single best match -- Layer C trains only on these.
    assert pairs[0]["scenario_key"] == "pricing"


def test_weak_second_match_is_excluded(fake_embeddings):
    # quality at 0.2 falls below relative_margin x best, so it must not ride along.
    pairs = [_pair("pricing:1.0 quality:0.2")]
    layer_b.assign_scenarios(pairs, _scenario_map(), config=None)
    assert pairs[0]["scenario_keys"] == ["pricing"]


def test_junk_trigger_goes_to_the_sink_alone(fake_embeddings):
    """A trigger closest to a mechanics sink must not also contaminate real rubrics."""
    pairs = [_pair("ack:1.0 pricing:0.9")]
    layer_b.assign_scenarios(pairs, _scenario_map(), config=None)
    assert pairs[0]["scenario_keys"] == ["ack"]
    assert pairs[0]["scenario_id"] == 3


def test_sinks_never_ride_along_with_a_real_match(fake_embeddings):
    """Sink close behind a real best match is still excluded from scenario_keys."""
    pairs = [_pair("pricing:1.0 ack:0.98")]
    layer_b.assign_scenarios(pairs, _scenario_map(), config=None)
    assert pairs[0]["scenario_keys"] == ["pricing"]


def test_assignment_never_exceeds_the_cap(fake_embeddings):
    """Even with everything tied, no pair may match more than the configured cap."""
    cap = load_tuning().layer_b.max_scenarios_per_pair
    smap = {
        f"s{i}": {"scenario_id": i, "business_description": "pricing", "keyphrases": [],
                  "is_coachable": True}
        for i in range(cap + 3)
    }
    pairs = [_pair("pricing")]
    layer_b.assign_scenarios(pairs, smap, config=None)
    assert len(pairs[0]["scenario_keys"]) == cap


def test_every_pair_is_always_assigned(fake_embeddings):
    """No pair may be left with scenario_key None -- the centroid fallback is gone,
    so the relative rule itself has to guarantee this."""
    pairs = [_pair("pricing"), _pair("quality"), _pair("ack")]
    layer_b.assign_scenarios(pairs, _scenario_map(), config=None)
    assert all(p["scenario_key"] is not None for p in pairs)
    assert all(p["scenario_id"] is not None for p in pairs)


def test_empty_scenario_map_leaves_pairs_unassigned(fake_embeddings):
    pairs = [_pair("pricing")]
    layer_b.assign_scenarios(pairs, {}, config=None)
    assert pairs[0]["scenario_key"] is None


# --- sink_margin_delta is LIVE on the primary path (2026-08-19) -------------
# assign_scenarios used to carry its own inline copy of the pick rule, so the knob existed
# in tuning.yaml and in flat_pick while doing nothing in production -- the same failure class
# as the retired ego_trap/settings.py and the inert layer_a.min_content_words. These tests
# fail if the inline copy ever comes back.


def _tune_delta(monkeypatch, delta):
    """Point layer_b's tuning at a copy with sink_margin_delta overridden."""
    import dataclasses
    from shared import tuning as tuning_mod

    real = tuning_mod.load_tuning()
    patched_b = dataclasses.replace(real.layer_b, sink_margin_delta=delta)
    patched = dataclasses.replace(real, layer_b=patched_b)
    monkeypatch.setattr(layer_b, "load_tuning", lambda: patched)


def test_assign_scenarios_delegates_to_flat_pick(fake_embeddings, monkeypatch):
    """The rule must be CALLED, not reimplemented. Proven by reachability: a flat_pick that
    raises must take the whole call down."""
    def explode(*a, **k):
        raise AssertionError("reached flat_pick")

    monkeypatch.setattr(layer_b, "_flat_pick", explode)
    with pytest.raises(AssertionError, match="reached flat_pick"):
        layer_b.assign_scenarios([_pair("pricing")], _scenario_map(), config=None)


def test_delta_zero_is_the_shipped_behaviour(fake_embeddings, monkeypatch):
    """The value in tuning.yaml today. A sink winner still takes the pair alone."""
    _tune_delta(monkeypatch, 0.0)
    pairs = [_pair("ack:1.0 pricing:0.9")]
    layer_b.assign_scenarios(pairs, _scenario_map(), config=None)
    assert pairs[0]["scenario_keys"] == ["ack"]


def test_a_negative_delta_rescues_a_near_tie_from_the_sink(fake_embeddings, monkeypatch):
    """The measured effect the knob exists for: near-ties currently all resolve to the junk
    bin, and a negative delta lets a coachable scenario lose narrowly and still take the pair.

    This asserts the knob is WIRED, not that this value should be shipped -- it must not be
    set non-zero without a judged sample larger than the 80 turns that exist.
    """
    _tune_delta(monkeypatch, -0.5)
    pairs = [_pair("ack:1.0 pricing:0.9")]
    layer_b.assign_scenarios(pairs, _scenario_map(), config=None)
    assert pairs[0]["scenario_key"] == "pricing", "a negative delta did not reach production"
    assert "ack" not in pairs[0]["scenario_keys"]


def test_a_positive_delta_sinks_a_narrow_coachable_winner(fake_embeddings, monkeypatch):
    """The other direction: a coachable winner must beat the best sink by the margin."""
    _tune_delta(monkeypatch, 0.5)
    pairs = [_pair("pricing:1.0 ack:0.99")]
    layer_b.assign_scenarios(pairs, _scenario_map(), config=None)
    assert pairs[0]["scenario_keys"] == ["ack"]


def test_the_shipped_value_is_still_a_no_op():
    """A tripwire on tuning.yaml itself. Changing this value is a behaviour change that needs
    a judged sample; it must not happen as a side effect of some other edit."""
    assert load_tuning().layer_b.sink_margin_delta == 0.0
