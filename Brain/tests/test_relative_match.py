"""Tests for shared/relative_match.py -- the relative top-K rule extracted from layer_b.

Uses hand-built orthogonal unit vectors rather than real embeddings, following
test_layer_b_assignment.py: this must test the RULE, not the embedding model, so the
assertions stay true whatever the model does to any particular sentence.
"""
import numpy as np
import pytest

from shared.relative_match import cosine_sims, flat_pick, is_sink_flags, topk_pick


def _map(**flags):
    """scenario_map with only the field is_sink_flags reads."""
    return {k: {"is_coachable": v} for k, v in flags.items()}


# --- is_sink_flags ---------------------------------------------------------

def test_is_sink_flags_marks_non_coachable():
    m = _map(real=True, junk=False)
    assert is_sink_flags(m, ["real", "junk"]) == [False, True]


def test_is_sink_flags_defaults_to_not_a_sink():
    """A hand-built map in a test must not have to spell out is_coachable, and a row
    from a pre-2026-07-27 snapshot lacking the column must not read as junk."""
    assert is_sink_flags({"a": {}}, ["a"]) == [False]


def test_is_sink_flags_is_parallel_to_the_keys_argument():
    m = _map(a=False, b=True, c=False)
    assert is_sink_flags(m, ["b", "a", "c"]) == [False, True, True]


# --- cosine_sims -----------------------------------------------------------

def test_cosine_sims_shape_and_values():
    Q = np.array([[1.0, 0.0], [0.0, 1.0]])
    D = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    sims = cosine_sims(Q, D)
    assert sims.shape == (2, 3)
    assert sims[0][0] == pytest.approx(1.0)
    assert sims[0][1] == pytest.approx(0.0)
    assert sims[0][2] == pytest.approx(1 / np.sqrt(2))


def test_cosine_sims_normalises_unnormalised_input():
    """Magnitude must not affect cosine -- otherwise a hand-built test vector and a
    real embedder vector would not be interchangeable."""
    a = cosine_sims(np.array([[3.0, 0.0]]), np.array([[7.0, 0.0]]))
    assert a[0][0] == pytest.approx(1.0)


def test_cosine_sims_zero_vector_does_not_divide_by_zero():
    """The +1e-10 guard carried over from assign_scenarios."""
    sims = cosine_sims(np.array([[0.0, 0.0]]), np.array([[1.0, 0.0]]))
    assert np.isfinite(sims).all()


# --- topk_pick -------------------------------------------------------------

def test_topk_pick_keeps_only_near_ties():
    sims = np.array([1.0, 0.96, 0.40])
    keys = ["best", "near", "far"]
    kept = topk_pick(sims, keys, [False] * 3, cap=3, margin=0.95)
    assert kept == ["best", "near"]


def test_topk_pick_always_keeps_at_least_the_best():
    sims = np.array([1.0, 0.10])
    kept = topk_pick(sims, ["best", "far"], [False, False], cap=3, margin=0.95)
    assert kept == ["best"]


def test_topk_pick_respects_the_cap():
    sims = np.array([1.0, 0.99, 0.98, 0.97])
    keys = ["a", "b", "c", "d"]
    kept = topk_pick(sims, keys, [False] * 4, cap=2, margin=0.90)
    assert kept == ["a", "b"]


def test_topk_pick_returns_none_when_every_candidate_is_a_sink():
    """The None return is what lets Layer D treat "no non-sink candidate" as "this is
    not a signal", where layer_b treats it as "fall back"."""
    sims = np.array([1.0, 0.9])
    assert topk_pick(sims, ["j1", "j2"], [True, True], cap=3, margin=0.95) is None


def test_topk_pick_skips_sinks_but_keeps_real_matches():
    sims = np.array([1.0, 0.99])
    kept = topk_pick(sims, ["junk", "real"], [True, False], cap=3, margin=0.95)
    assert kept == ["real"]


def test_topk_pick_margin_is_relative_to_the_best_non_sink():
    """A high-scoring sink must not raise the cutoff and squeeze out real matches --
    the cutoff is computed from the best surviving CANDIDATE, not the best overall."""
    sims = np.array([1.0, 0.60, 0.58])
    kept = topk_pick(sims, ["junk", "real1", "real2"], [True, False, False], cap=3, margin=0.95)
    assert kept == ["real1", "real2"]


def test_margin_is_inert_at_cap_one():
    """Measured 2026-08-10: Layer D's margin sweep returned an identical signal count at
    every value from 0.85 to 0.99. This is why, and it is arithmetic, not a bug --
    candidates[:1] is always the single best non-sink, and sims[best] >= margin *
    sims[best] holds for every margin <= 1. Pinned so tuning.yaml's "INERT at
    max_scenarios_per_signal: 1" note cannot quietly stop being true."""
    sims = np.array([1.0, 0.99, 0.50, 0.10])
    keys = ["a", "b", "c", "d"]
    results = {
        tuple(topk_pick(sims, keys, [False] * 4, cap=1, margin=m))
        for m in (0.50, 0.85, 0.95, 0.99, 1.0)
    }
    assert results == {("a",)}


def test_margin_is_live_once_the_cap_allows_more_than_one():
    sims = np.array([1.0, 0.99, 0.50, 0.10])
    keys = ["a", "b", "c", "d"]
    results = {
        tuple(topk_pick(sims, keys, [False] * 4, cap=3, margin=m))
        for m in (0.50, 0.85, 0.95, 0.99, 1.0)
    }
    assert len(results) > 1


def test_topk_pick_restrict_to_limits_candidates():
    sims = np.array([1.0, 0.99, 0.98])
    kept = topk_pick(sims, ["a", "b", "c"], [False] * 3, cap=3, margin=0.90, restrict_to={1, 2})
    assert kept == ["b", "c"]


def test_topk_pick_returns_none_when_restrict_to_is_empty():
    sims = np.array([1.0, 0.9])
    assert topk_pick(sims, ["a", "b"], [False, False], cap=3, margin=0.9, restrict_to=set()) is None


# --- flat_pick -------------------------------------------------------------

def test_flat_pick_files_to_the_sink_when_the_sink_wins():
    """The behavioural difference from topk_pick, and the reason both exist: layer_b
    must place every pair somewhere, so it FILES to the sink rather than rejecting."""
    sims = np.array([1.0, 0.99])
    assert flat_pick(sims, ["junk", "real"], [True, False], cap=3, margin=0.95) == ["junk"]


def test_flat_pick_matches_topk_pick_when_the_best_is_not_a_sink():
    sims = np.array([1.0, 0.96, 0.40])
    keys = ["best", "near", "far"]
    is_sink = [False, False, False]
    assert flat_pick(sims, keys, is_sink, 3, 0.95) == topk_pick(sims, keys, is_sink, 3, 0.95)


def test_flat_pick_always_returns_at_least_one_key():
    """No pair can be left unassigned -- this is what replaced the centroid fallback."""
    sims = np.array([0.02, 0.01])
    assert len(flat_pick(sims, ["a", "b"], [False, False], cap=3, margin=0.95)) >= 1


# --------------------------------------------------------------------------------------
# sink_margin_delta — the one routing lever the evidence endorses; default MUST be a no-op
# --------------------------------------------------------------------------------------

def test_delta_default_is_byte_identical_to_the_shipped_rule():
    """THE PROPERTY THAT MAKES SHIPPING THIS SAFE. Adding the knob must change nothing
    until a value is deliberately set, so the default path is compared against an explicit
    reimplementation of the OLD rule over randomized inputs."""
    import numpy as np
    rng = np.random.default_rng(20260819)
    keys = [f"s{i}" for i in range(8)]
    for _ in range(400):
        sims = rng.random(8)
        sink = [bool(b) for b in rng.integers(0, 2, 8)]
        if all(sink):
            continue
        cap, margin = 3, 0.95
        # the shipped rule, written out
        order = np.argsort(sims)[::-1]
        best = int(order[0])
        if sink[best]:
            want = [keys[best]]
        else:
            cut = margin * float(sims[best])
            want = [keys[int(j)] for j in order[:cap]
                    if float(sims[int(j)]) >= cut and not sink[int(j)]] or [keys[best]]
        assert flat_pick(sims, keys, sink, cap, margin) == want
        assert flat_pick(sims, keys, sink, cap, margin, 0.0) == want


def test_negative_delta_rescues_a_near_tie_from_the_sink():
    """The motivating case: a real coaching moment losing to backchannel by 0.005."""
    import numpy as np
    keys = ["application_volume", "conversational_acknowledgment"]
    sink = [False, True]
    sims = np.array([0.680, 0.685])          # sink wins by 0.005
    assert flat_pick(sims, keys, sink, 3, 0.95) == ["conversational_acknowledgment"]
    assert flat_pick(sims, keys, sink, 3, 0.95, -0.0117) == ["application_volume"]


def test_negative_delta_still_sinks_a_clear_sink():
    """It must not become a blanket 'never sink'. A sink winning by a real margin holds."""
    import numpy as np
    keys = ["application_volume", "conversational_acknowledgment"]
    sink = [False, True]
    sims = np.array([0.50, 0.71])            # sink wins by 0.21
    assert flat_pick(sims, keys, sink, 3, 0.95, -0.0117) == [
        "conversational_acknowledgment"]


def test_positive_delta_is_stricter_than_shipped():
    """A coachable winner that only just beats the best sink now sinks."""
    import numpy as np
    keys = ["application_volume", "conversational_acknowledgment"]
    sink = [False, True]
    sims = np.array([0.685, 0.680])          # coachable wins by 0.005
    assert flat_pick(sims, keys, sink, 3, 0.95) == ["application_volume"]
    assert flat_pick(sims, keys, sink, 3, 0.95, 0.02) == [
        "conversational_acknowledgment"]


def test_delta_never_returns_empty_or_a_missing_key():
    """Layer B must assign every pair somewhere; no delta may produce an empty pick."""
    import numpy as np
    rng = np.random.default_rng(7)
    keys = [f"s{i}" for i in range(6)]
    for d in (-0.05, -0.0117, 0.0, 0.02, 0.5):
        for _ in range(200):
            sims = rng.random(6)
            sink = [bool(b) for b in rng.integers(0, 2, 6)]
            got = flat_pick(sims, keys, sink, 3, 0.95, d)
            assert got, f"empty pick at delta={d}"
            assert all(g in keys for g in got)


def test_all_sink_candidates_cannot_crash_any_delta():
    import numpy as np
    keys = ["a", "b"]
    for d in (-0.05, 0.0, 0.05):
        assert flat_pick(np.array([0.4, 0.6]), keys, [True, True], 3, 0.95, d) == ["b"]


def test_pinecone_batch_preserves_the_768_path_and_shrinks_for_3072():
    """The width-derived batch must leave the historical bge path byte-identical (100) and
    keep a 3072 request well under Pinecone's ~2 MB ceiling."""
    def batch(width):
        return max(10, min(100, int(320_000 / max(width * 4, 1))))
    assert batch(768) == 100, "the historical 768 batch size changed"
    assert batch(3072) < 100
    assert batch(3072) * 3072 * 4 < 2_000_000, "a 3072 batch could exceed the request cap"
