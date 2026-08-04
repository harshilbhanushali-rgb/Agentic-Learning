# Layer B Sink-Rescue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build three candidate Layer B matching strategies (`response_only`, `or_rule`, `blended`) that use a pair's *response* embedding, not just its trigger, to decide whether the pair is real coachable content or junk — plus a zero-Gemma harness to measure and read samples of what each strategy does against the real corpus, so a later session can decide whether/how to adopt one.

**Architecture:** A new function `assign_scenarios_with_sink_rescue(pairs, scenario_map, config, strategy)` in `v1/layer_b.py`, sitting alongside the existing `assign_scenarios` (flat, untouched) and `assign_scenarios_two_stage`, selected by a `strategy` argument exactly like the two-stage function already is. A new read-only script `compare_sink_rescue.py` at the `Brain/` root re-runs it against real, already-embedded `kb_pairs` and reports rescue rates plus printed samples for manual reading.

**Tech Stack:** Python 3.11, numpy, pytest, psycopg (read-only), the existing `preprocessing.embedder` disk cache.

## Global Constraints

- `assign_scenarios` (today's production flat matching) must not change — byte-for-byte — per the design spec's explicit scope.
- Every new tuning value goes into `tuning.yaml` under `layer_b:`, marked `UNCALIBRATED placeholder`, following `shared/tuning.py`'s existing fail-loudly validation (unknown/missing keys raise).
- Response text is embedded via `embedder.embed_document` (matches how scenario descriptions and stored `response_text` are already embedded elsewhere) — never `embed_query`.
- No pipeline module (`v1/pipeline.py`, `v2/pipeline.py`) is touched in this plan. Nothing here runs in a real pipeline execution.
- New tests use hand-built orthogonal unit-axis vectors (via the `fake_embeddings` monkeypatch pattern already established in `tests/test_layer_b_assignment.py` and `tests/test_two_stage_matching.py`) so assertions test the rule, not the embedding model.
- Reference spec: `docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md`.

---

### Task 1: Add sink-rescue tuning keys

**Files:**
- Modify: `Brain/tuning.yaml`
- Modify: `Brain/shared/tuning.py:29-37` (`LayerBTuning` dataclass)
- Modify: `Brain/tests/test_tuning.py`

**Interfaces:**
- Produces: `Tuning.layer_b.sink_rescue_strategy: str`, `.sink_rescue_relative_margin: float`, `.sink_rescue_min_similarity: float`, `.sink_rescue_blend_alpha: float` — read by Task 2's new function via `load_tuning().layer_b`.

- [ ] **Step 1: Write the failing test**

Edit `Brain/tests/test_tuning.py`: add the four new keys to the `_GOOD` fixture's `layer_b:` block, and add new assertions to `test_shipped_tuning_yaml_is_valid`.

```python
_GOOD = """
layer_a:
  min_call_support_fraction: 0.02
  min_call_support_floor: 4
  ubiquity_ceiling: 0.4
  merge_cosine_threshold: 0.88
  min_content_words: 5
  grouping_method: post_hoc
  primary_topic_merge_threshold: 0.70
layer_b:
  relative_margin: 0.85
  max_scenarios_per_pair: 3
  matching_strategy: flat
  primary_topic_relative_margin: 0.95
  max_primary_topics_per_pair: 2
  two_stage_fallback_floor: 0.50
  sink_rescue_strategy: none
  sink_rescue_relative_margin: 0.95
  sink_rescue_min_similarity: 0.50
  sink_rescue_blend_alpha: 0.6
layer_c:
  milestone_relevance_percentile: 60
  min_milestone_call_fraction: 0.15
  min_milestone_calls_floor: 3
  milestone_hard_cap: 10
  min_cluster_size_fraction: 0.02
  min_cluster_size_floor: 3
  min_cluster_size_ceiling: 25
  umap_n_components: 5
  milestone_sink_similarity_percentile: 95
embedding:
  cache_enabled: true
  cache_path: embed_cache.db
"""
```

Add to `test_shipped_tuning_yaml_is_valid`:

```python
    assert t.layer_b.sink_rescue_strategy in ("none", "response_only", "or_rule", "blended")
    assert 0.0 < t.layer_b.sink_rescue_relative_margin <= 1.0
    assert 0.0 < t.layer_b.sink_rescue_min_similarity <= 1.0
    assert 0.0 < t.layer_b.sink_rescue_blend_alpha < 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_tuning.py -v`
Expected: FAIL — `test_loads_valid_file` and `test_shipped_tuning_yaml_is_valid` both raise `ValueError: tuning.yaml: unknown key(s) in layer_b: ['sink_rescue_...]` (the `_GOOD` fixture now has keys `LayerBTuning` doesn't declare yet) or `AttributeError` on the new assertions against the real file.

- [ ] **Step 3: Add the fields to `LayerBTuning`**

In `Brain/shared/tuning.py`, replace the `LayerBTuning` dataclass:

```python
@dataclass(frozen=True)
class LayerBTuning:
    relative_margin: float
    max_scenarios_per_pair: int
    matching_strategy: str
    primary_topic_relative_margin: float
    max_primary_topics_per_pair: int
    two_stage_fallback_floor: float
    sink_rescue_strategy: str
    sink_rescue_relative_margin: float
    sink_rescue_min_similarity: float
    sink_rescue_blend_alpha: float
```

- [ ] **Step 4: Add the keys to the real `tuning.yaml`**

In `Brain/tuning.yaml`, insert immediately after the existing `two_stage_fallback_floor: 0.50` line (still inside the `layer_b:` section, before `layer_c:`):

```yaml
  # Layer B sink-rescue (see docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md).
  # Selects which not-yet-wired assign_scenarios_with_sink_rescue strategy a future
  # pipeline wiring decision would use. 'none' means nothing here is live -- mirrors
  # how matching_strategy started at 'flat' before two-stage existed. No pipeline
  # code reads this yet; compare_sink_rescue.py loops over all three strategies
  # directly rather than reading this key.
  sink_rescue_strategy: none

  # Stage cutoff for the response-side rescue check: keep a response's own
  # best-matching non-sink scenario(s) within this fraction of ITS best match,
  # mirroring relative_margin's shape for the response signal instead of the
  # trigger signal.
  #
  # UNCALIBRATED placeholder, mirroring primary_topic_relative_margin's own
  # placeholder rationale: set equal to relative_margin as a starting guess until
  # compare_sink_rescue.py measures the real response-vs-scenario similarity band
  # -- a different, so-far-unmeasured comparison, since response and scenario
  # descriptions are both embedded via embed_document (a document-vs-document
  # band), not the query-vs-document band relative_margin was calibrated against.
  sink_rescue_relative_margin: 0.95

  # Absolute floor: a response-side rescue match must clear this raw cosine
  # similarity, not just the relative margin above. Necessary because a purely
  # relative check could rescue a pair whose response is only relatively-better-
  # matched than the sink, without being an absolutely good match to anything real.
  #
  # UNCALIBRATED placeholder. Set near two_stage_fallback_floor's own starting
  # value (0.50) for the same reason that one was: a principled starting guess
  # near the p25 mark of the already-measured trigger-vs-scenario band, not a
  # measured value for THIS (response-vs-scenario) band -- compare_sink_rescue.py
  # must print that band's real percentiles before this number is trusted.
  sink_rescue_min_similarity: 0.50

  # blended strategy only: weight on the trigger vector when blending
  # trigger+response into one matching vector (1 - this = response's weight).
  #
  # UNCALIBRATED placeholder. 0.6 weights the trigger higher since the rest of
  # this file's thresholds (relative_margin, etc.) are calibrated against
  # trigger-only similarity -- a starting guess that keeps the blend closer to
  # today's known-good behavior by default, not a measured value.
  sink_rescue_blend_alpha: 0.6
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_tuning.py -v`
Expected: PASS (5/5 existing + no count change — the two modified tests now pass with the new keys present in both the fixture and the dataclass).

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/ -v`
Expected: PASS, same count as before plus zero new failures (this task adds no new test functions, only extends existing ones).

- [ ] **Step 7: Commit**

```bash
git add Brain/tuning.yaml Brain/shared/tuning.py Brain/tests/test_tuning.py
git commit -m "Add uncalibrated sink-rescue tuning keys to layer_b"
```

---

### Task 2: `assign_scenarios_with_sink_rescue` — skeleton + `response_only` strategy

**Files:**
- Modify: `Brain/v1/layer_b.py` (add `_flat_pick` helper and `assign_scenarios_with_sink_rescue`, placed after `assign_scenarios_two_stage`, before `embed_and_store_pairs`)
- Create: `Brain/tests/test_sink_rescue.py`

**Interfaces:**
- Consumes: `v1.layer_b._topk_pick(sims, keys, is_sink_arr, cap, margin, restrict_to=None) -> list[str] | None` (existing, unchanged), `shared.scenario_vectors.build_scenario_vecs(scenario_map) -> (keys, vecs)` (existing), `shared.tuning.load_tuning().layer_b` (Task 1's new fields).
- Produces: `v1.layer_b._flat_pick(sims, keys, is_sink_arr, cap, margin) -> list[str]` and `v1.layer_b.assign_scenarios_with_sink_rescue(pairs, scenario_map, config, strategy) -> tuple[list[list[float]], list[list[float]]]` — Tasks 3 and 4 add the `or_rule`/`blended` branches to this same function; Task 5's harness calls it directly.

- [ ] **Step 1: Write the failing tests**

Create `Brain/tests/test_sink_rescue.py`:

```python
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


class TestUnknownSinkRescueStrategy:
    def test_raises_on_unrecognised_strategy(self, fake_embeddings):
        pairs = [_pair("pricing:1.0", "quality:1.0")]
        with pytest.raises(ValueError, match="unknown sink-rescue strategy"):
            layer_b.assign_scenarios_with_sink_rescue(
                pairs, _scenario_map(), config=None, strategy="bogus",
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_sink_rescue.py -v`
Expected: FAIL — `AttributeError: module 'v1.layer_b' has no attribute 'assign_scenarios_with_sink_rescue'`.

- [ ] **Step 3: Implement `_flat_pick` and `assign_scenarios_with_sink_rescue`**

In `Brain/v1/layer_b.py`, add after `assign_scenarios_two_stage` (before `embed_and_store_pairs`):

```python
def _flat_pick(
    sims: np.ndarray,
    keys: list[str],
    is_sink_arr: list[bool],
    cap: int,
    margin: float,
) -> list[str]:
    """Reproduces assign_scenarios's own per-pair sink-short-circuit + relative-margin
    logic on an arbitrary similarity vector, so assign_scenarios_with_sink_rescue can
    apply it to a trigger, response, or blended vector without duplicating the loop
    body per strategy. assign_scenarios itself is left untouched -- this is a new
    helper for the new function, not a refactor of the calibrated one.
    """
    order = np.argsort(sims)[::-1]
    best_j = int(order[0])
    if is_sink_arr[best_j]:
        return [keys[best_j]]
    cutoff = margin * float(sims[best_j])
    kept = [
        keys[int(j)] for j in order[:cap]
        if float(sims[int(j)]) >= cutoff and not is_sink_arr[int(j)]
    ]
    return kept or [keys[best_j]]


def assign_scenarios_with_sink_rescue(
    pairs: list[dict],
    scenario_map: dict[str, dict],
    config: Config,
    strategy: str,
) -> tuple[list[list[float]], list[list[float]]]:
    """Sink-rescue variant of assign_scenarios: response_only / or_rule / blended.

    See docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md for the problem
    this solves (sink absorption discarding real content whose RESPONSE, not trigger,
    carries the value) and why each strategy is shaped this way.

    UNCALIBRATED as of 2026-08-04 -- sink_rescue_relative_margin, sink_rescue_min_similarity,
    and sink_rescue_blend_alpha are all placeholders until compare_sink_rescue.py measures
    real response-vs-scenario similarity. Kept fully separate from assign_scenarios (flat)
    -- that function's own calibration (relative_margin=0.95, etc.) is untouched by this code.

    Returns (trigger_vecs, response_vecs) so a future wired-in caller could reuse both,
    mirroring assign_scenarios's existing trigger_vecs reuse into embed_and_store_pairs.
    """
    if not pairs:
        return [], []

    trigger_texts = [p["trigger_text"] for p in pairs]
    response_texts = [p["response_text"] for p in pairs]
    trigger_vecs = embedder.embed_query(trigger_texts)
    response_vecs = embedder.embed_document(response_texts)

    if not scenario_map:
        return trigger_vecs, response_vecs

    tuning = load_tuning().layer_b
    scenario_keys, scenario_vecs = _build_scenario_vecs(scenario_map)
    is_sink = [not scenario_map[k].get("is_coachable", True) for k in scenario_keys]

    T = np.array(trigger_vecs)
    R = np.array(response_vecs)
    S = np.array(scenario_vecs)
    T_norm = T / (np.linalg.norm(T, axis=1, keepdims=True) + 1e-10)
    R_norm = R / (np.linalg.norm(R, axis=1, keepdims=True) + 1e-10)
    S_norm = S / (np.linalg.norm(S, axis=1, keepdims=True) + 1e-10)
    trigger_sims = T_norm @ S_norm.T
    response_sims = R_norm @ S_norm.T

    def _assign(pair, keys):
        pair["scenario_keys"] = keys
        pair["scenario_key"] = keys[0]
        pair["scenario_id"] = scenario_map[keys[0]]["scenario_id"]

    def _response_rescue(i):
        r_kept = _topk_pick(
            response_sims[i], scenario_keys, is_sink,
            tuning.max_scenarios_per_pair, tuning.sink_rescue_relative_margin,
        )
        if r_kept is None:
            return None
        r_best_sim = float(response_sims[i][scenario_keys.index(r_kept[0])])
        if r_best_sim < tuning.sink_rescue_min_similarity:
            return None
        return r_kept

    for i, pair in enumerate(pairs):
        t_sims = trigger_sims[i]
        t_best_j = int(np.argsort(t_sims)[::-1][0])

        if strategy == "response_only":
            if is_sink[t_best_j]:
                rescued = _response_rescue(i)
                _assign(pair, rescued or [scenario_keys[t_best_j]])
            else:
                _assign(pair, _flat_pick(
                    t_sims, scenario_keys, is_sink,
                    tuning.max_scenarios_per_pair, tuning.relative_margin,
                ))
        else:
            raise ValueError(f"unknown sink-rescue strategy: {strategy!r}")

    return trigger_vecs, response_vecs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_sink_rescue.py -v`
Expected: PASS, 6/6 (5 in `TestResponseOnly` + 1 in `TestUnknownSinkRescueStrategy`).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/ -v`
Expected: PASS, all prior tests unchanged plus the 6 new ones.

- [ ] **Step 6: Commit**

```bash
git add Brain/v1/layer_b.py Brain/tests/test_sink_rescue.py
git commit -m "Add assign_scenarios_with_sink_rescue: response_only strategy"
```

---

### Task 3: `or_rule` strategy

**Files:**
- Modify: `Brain/v1/layer_b.py` (extend `assign_scenarios_with_sink_rescue`'s strategy dispatch)
- Modify: `Brain/tests/test_sink_rescue.py` (add `TestOrRule`)

**Interfaces:**
- Consumes: `_flat_pick`, `_response_rescue` (both defined inside `assign_scenarios_with_sink_rescue` in Task 2 — the `or_rule` branch is added as a sibling `elif` in the same per-pair loop, so it closes over the same locals).
- Produces: no new public names — `strategy="or_rule"` becomes a valid value for the existing function.

- [ ] **Step 1: Write the failing tests**

Add to `Brain/tests/test_sink_rescue.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_sink_rescue.py::TestOrRule -v`
Expected: FAIL — `ValueError: unknown sink-rescue strategy: 'or_rule'`.

- [ ] **Step 3: Add the `or_rule` branch**

In `Brain/v1/layer_b.py`, inside `assign_scenarios_with_sink_rescue`'s per-pair loop, replace the `else: raise ValueError(...)` with:

```python
        elif strategy == "or_rule":
            if float(t_sims[t_best_j]) < tuning.sink_rescue_min_similarity:
                rescued = _response_rescue(i)
                if rescued is not None:
                    _assign(pair, rescued)
                    continue
            _assign(pair, _flat_pick(
                t_sims, scenario_keys, is_sink,
                tuning.max_scenarios_per_pair, tuning.relative_margin,
            ))
        else:
            raise ValueError(f"unknown sink-rescue strategy: {strategy!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_sink_rescue.py -v`
Expected: PASS, 9/9 (6 from Task 2 + 3 new in `TestOrRule`).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/ -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add Brain/v1/layer_b.py Brain/tests/test_sink_rescue.py
git commit -m "Add or_rule strategy to assign_scenarios_with_sink_rescue"
```

---

### Task 4: `blended` strategy

**Files:**
- Modify: `Brain/v1/layer_b.py` (extend `assign_scenarios_with_sink_rescue`'s strategy dispatch)
- Modify: `Brain/tests/test_sink_rescue.py` (add `TestBlended`)

**Interfaces:**
- Consumes: `T_norm`, `R_norm`, `S_norm`, `_flat_pick` (all already local to `assign_scenarios_with_sink_rescue` from Task 2).
- Produces: `strategy="blended"` becomes a valid value for the existing function — all three strategies are now implemented.

- [ ] **Step 1: Write the failing tests**

Add to `Brain/tests/test_sink_rescue.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_sink_rescue.py::TestBlended -v`
Expected: FAIL — `ValueError: unknown sink-rescue strategy: 'blended'`.

- [ ] **Step 3: Add the `blended` branch**

In `Brain/v1/layer_b.py`, inside `assign_scenarios_with_sink_rescue`'s per-pair loop, insert a new `elif` before the final `else: raise ValueError(...)`:

```python
        elif strategy == "blended":
            alpha = tuning.sink_rescue_blend_alpha
            blend = alpha * T_norm[i] + (1.0 - alpha) * R_norm[i]
            blend = blend / (np.linalg.norm(blend) + 1e-10)
            blend_sims = S_norm @ blend
            _assign(pair, _flat_pick(
                blend_sims, scenario_keys, is_sink,
                tuning.max_scenarios_per_pair, tuning.relative_margin,
            ))
        else:
            raise ValueError(f"unknown sink-rescue strategy: {strategy!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_sink_rescue.py -v`
Expected: PASS, 12/12 (9 from Tasks 2-3 + 3 new in `TestBlended`).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/ -v`
Expected: PASS, full suite green.

- [ ] **Step 6: Commit**

```bash
git add Brain/v1/layer_b.py Brain/tests/test_sink_rescue.py
git commit -m "Add blended strategy to assign_scenarios_with_sink_rescue"
```

---

### Task 5: `compare_sink_rescue.py` calibration harness

**Files:**
- Create: `Brain/compare_sink_rescue.py`

**Interfaces:**
- Consumes: `v1.layer_b.assign_scenarios_with_sink_rescue` (Tasks 2-4), `shared.storage.get_connection`/`get_scenarios` (existing), `shared.scenario_vectors.build_scenario_vecs` (existing), `config.load_config` (existing).
- Produces: nothing consumed by other tasks — this is the terminal, manually-run tool Task 6 uses.

No automated test for this file, matching `compare_matching_subset.py`'s own precedent (an ad-hoc, read-only calibration script, not a permanent library module). Verification is Task 6: running it for real and checking its output makes sense.

- [ ] **Step 1: Write the script**

Create `Brain/compare_sink_rescue.py`:

```python
#!/usr/bin/env python3
"""Zero-Gemma comparison of the three sink-rescue strategies (response_only /
or_rule / blended) from docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md
against the real, already-populated corpus.

Read-only against Postgres: trigger_text and response_text are real columns on
kb_pairs, so no Pinecone read is needed. Re-runs assign_scenarios_with_sink_rescue
in memory for each strategy over the same real texts. No DB writes, no Gemma calls
-- embedder calls go through the disk cache, which is warm for this corpus.
"""
from __future__ import annotations
import random
import sys
from collections import Counter

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np

from config import load_config
from preprocessing import embedder
from shared import storage
from shared.scenario_vectors import build_scenario_vecs
from v1 import layer_b


def _load_real_pairs(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pair_id, trigger_text, response_text, scenario_key "
            "FROM kb_pairs ORDER BY pair_id"
        )
        rows = cur.fetchall()
    return [
        {"pair_id": r[0], "trigger_text": r[1], "response_text": r[2], "flat_key": r[3]}
        for r in rows
    ]


def _fresh_pairs(real_pairs: list[dict]) -> list[dict]:
    return [
        {"trigger_text": p["trigger_text"], "response_text": p["response_text"],
         "scenario_key": None, "scenario_id": None}
        for p in real_pairs
    ]


def _print_response_similarity_percentiles(real_pairs: list[dict], scenario_map: dict) -> None:
    scenario_keys, scenario_vecs = build_scenario_vecs(scenario_map)
    is_sink = [not scenario_map[k].get("is_coachable", True) for k in scenario_keys]
    non_sink_cols = [j for j, s in enumerate(is_sink) if not s]

    response_vecs = embedder.embed_document([p["response_text"] for p in real_pairs])
    R = np.array(response_vecs)
    S = np.array(scenario_vecs)
    R_norm = R / (np.linalg.norm(R, axis=1, keepdims=True) + 1e-10)
    S_norm = S / (np.linalg.norm(S, axis=1, keepdims=True) + 1e-10)
    sims = R_norm @ S_norm.T
    best_non_sink = sims[:, non_sink_cols].max(axis=1)

    print("\nResponse-vs-scenario best-match similarity, non-sink candidates only "
          f"({len(real_pairs)} pairs):")
    print("  " + "  ".join(
        f"p{p}={np.percentile(best_non_sink, p):.3f}" for p in (10, 25, 50, 75, 90)
    ))


def _report(strategy: str, real_pairs: list[dict], scenario_map: dict, assigned: list[dict]) -> None:
    is_sink_today = [not scenario_map[p["flat_key"]]["is_coachable"] for p in real_pairs]
    sink_idx = [i for i, s in enumerate(is_sink_today) if s]
    non_sink_idx = [i for i, s in enumerate(is_sink_today) if not s]

    rescued_idx = [i for i in sink_idx if scenario_map[assigned[i]["scenario_key"]]["is_coachable"]]
    non_sink_touched_idx = [
        i for i in non_sink_idx if assigned[i]["scenario_key"] != real_pairs[i]["flat_key"]
    ]

    print(f"\n=== {strategy} ===")
    if sink_idx:
        print(f"  sink-bound pairs today      : {len(sink_idx)}")
        print(f"  rescued to a real scenario  : {len(rescued_idx)} "
              f"({len(rescued_idx)/len(sink_idx):.1%})")
        top = Counter(assigned[i]["scenario_key"] for i in rescued_idx).most_common(10)
        if top:
            print("  top scenarios absorbing rescued pairs:")
            for key, count in top:
                print(f"    {key}: {count}")
    else:
        print("  sink-bound pairs today      : 0 (nothing to rescue)")
    print(f"  non-sink pairs also changed : {len(non_sink_touched_idx)} / {len(non_sink_idx)}")

    rng = random.Random(0)
    if rescued_idx:
        print("\n  20 random rescued pairs:")
        for i in rng.sample(rescued_idx, min(20, len(rescued_idx))):
            p, a = real_pairs[i], assigned[i]
            print(f"    [{p['pair_id']}] trigger : {p['trigger_text'][:100]!r}")
            print(f"        response: {p['response_text'][:150]!r}")
            print(f"        -> {a['scenario_key']} (was sink: {p['flat_key']})")

    still_sink_idx = [i for i in sink_idx if i not in rescued_idx]
    if still_sink_idx:
        print("\n  10 random pairs still in a sink (near-miss check):")
        for i in rng.sample(still_sink_idx, min(10, len(still_sink_idx))):
            p = real_pairs[i]
            print(f"    [{p['pair_id']}] trigger : {p['trigger_text'][:100]!r}")
            print(f"        response: {p['response_text'][:150]!r}")
            print(f"        -> stays in {p['flat_key']}")


def main() -> None:
    config = load_config()
    conn = storage.get_connection(config.database_url)

    scenario_rows = storage.get_scenarios(conn)
    scenario_map = {r["scenario_key"]: r for r in scenario_rows}
    real_pairs = _load_real_pairs(conn)
    conn.close()

    print(f"Loaded {len(scenario_map)} scenario(s), {len(real_pairs)} pair(s).")
    if not scenario_map or not real_pairs:
        print("scenarios or kb_pairs is empty -- nothing to compare. Did a pipeline run finish?")
        sys.exit(1)

    _print_response_similarity_percentiles(real_pairs, scenario_map)

    for strategy in ("response_only", "or_rule", "blended"):
        pairs = _fresh_pairs(real_pairs)
        layer_b.assign_scenarios_with_sink_rescue(pairs, scenario_map, config=None, strategy=strategy)
        _report(strategy, real_pairs, scenario_map, pairs)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity-check it imports and parses cleanly**

Run: `cd Brain && ..\.venv\Scripts\python -c "import ast; ast.parse(open('compare_sink_rescue.py', encoding='utf-8').read())"`
Expected: no output, exit code 0 (confirms no syntax errors before Task 6 runs it against a real database).

- [ ] **Step 3: Commit**

```bash
git add Brain/compare_sink_rescue.py
git commit -m "Add compare_sink_rescue.py calibration harness"
```

---

### Task 6: Run the harness against real data and record findings

**Files:**
- Modify: `docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md` (append a "Status update" section, following the convention already used in `docs/superpowers/specs/2026-07-30-layer-b-two-stage-matching-design.md`)
- Create: `Brain/compare_sink_rescue_20260804.log` (or the actual run date, if this task runs on a different day)

This task needs a live `DATABASE_URL` pointed at a schema with real `scenarios`/`kb_pairs` data (e.g. the `public` schema described in `CLAUDE.md` as holding the latest full-corpus run). It also requires **reading and judging** the printed sample pairs — a judgment call, not a mechanical step, so it should be run directly rather than handed to a subagent with no context on what "looks like real content" means (see `PROBLEMS_AND_FIXES.md`'s repeated finding that every matching-quality decision in this codebase was settled by reading actual pairs, never by a count alone).

- [ ] **Step 1: Run the harness and save its output**

```bash
cd Brain
$env:PYTHONIOENCODING="utf-8"
..\.venv\Scripts\python compare_sink_rescue.py | Out-File -Encoding utf8 compare_sink_rescue_20260804.log
```

(Use `Out-File -Encoding utf8`, not `Tee-Object`, per `CLAUDE.md`'s Gotchas — `Tee-Object` writes UTF-16 and produces an unreadable log.)

- [ ] **Step 2: Read the response-vs-scenario percentile line**

Confirm it printed 5 numbers (p10/p25/p50/p75/p90). Compare them to `sink_rescue_min_similarity: 0.50`'s placeholder — note in the findings whether 0.50 sits meaningfully above or below this band (mirrors how `relative_margin`'s own placeholder was checked against its measured band before being trusted).

- [ ] **Step 3: Read every printed sample pair for all three strategies**

For each of the 3 strategies' "20 random rescued pairs" and "10 random near-miss pairs" sections, judge each rescued pair: does the response actually carry real, coachable content (per the same standard the original audit in `PROBLEMS_AND_FIXES.md` used), or is it still junk that slipped through? Note the rough fraction that reads as genuinely correct per strategy.

- [ ] **Step 4: Append a "Status update" section to the design spec**

Edit `docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md`: add a new section after the "Rollout" section, in the same style as the existing two-stage-matching spec's "Status update" entries — state the measured rescue rate per strategy, the non-sink-touched rate for `or_rule`/`blended`, the measured similarity band, and the qualitative read of the samples (which strategy looks most correct, any specific bad examples worth quoting, and an explicit recommendation on whether any strategy is worth pursuing toward production wiring, or whether this needs another calibration pass first).

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md Brain/compare_sink_rescue_20260804.log
git commit -m "Record compare_sink_rescue.py findings against the real corpus"
```
