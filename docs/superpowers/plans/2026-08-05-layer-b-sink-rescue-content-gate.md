# Layer B Sink-Rescue: Content-Signal Gate Implementation Plan

**Goal:** Build the content-signal rescue gate from `docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md`'s Status update 3 — replace the two cosine floors (`sink_rescue_response_min_similarity`, `sink_rescue_trigger_weak_floor`) with `concrete_entity_density(response)` (primary) and `preceding_turn_is_question` (borderline tie-break only), as two new strategies (`content_gate_narrow`, `content_gate_broad`) alongside the existing `response_only`/`or_rule`/`blended`.

**Architecture:** A new pure module `shared/trigger_quality.py` provides the two signals (plus two more, specified for module completeness/future reuse by the sibling trigger-quality-gate design). `v1/layer_b.py::assign_scenarios_with_sink_rescue` gains two new `strategy` branches that call a new `_content_gate` helper instead of the existing floor checks, reusing the existing `_topk_pick`/`_flat_pick` machinery for routing unchanged. A new calibration-only script `label_trigger_quality_sample.py` produces the ground-truth labels needed to set the two new tuning thresholds; `compare_sink_rescue.py` is extended to re-parse source transcripts (for the question signal) and report the two new strategies alongside the existing three.

**Tech Stack:** Python 3.11, spaCy `en_core_web_lg` (NER-enabled pass, new), numpy, pytest, Gemma via `shared/gemma.py::call_gemma`, Postgres via `psycopg`/`shared/storage.py`. No new third-party dependencies.

## Global Constraints

- Every threshold is `UNCALIBRATED placeholder` until a labeled-sample read sets it — never guess a final value (per this codebase's own rule, restated in the design doc's "Global Constraints"-equivalent history section).
- `sink_rescue_response_min_similarity`, `sink_rescue_trigger_weak_floor`, `sink_rescue_blend_alpha` **stay in `tuning.yaml` unchanged** — the `response_only`/`or_rule`/`blended` code paths that read them are kept for historical reproducibility, and `load_tuning()` raises on a missing key.
- Nothing in this plan is wired into `assign_scenarios`, `v1/pipeline.py`, or `v2/pipeline.py`. All new code is reachable only via `assign_scenarios_with_sink_rescue`'s `strategy` parameter and the calibration scripts.
- No DB writes and no Gemma calls anywhere except the one new script `label_trigger_quality_sample.py` (batched, read-only against `kb_pairs`/`scenarios`, writes only to a local JSON file — never to Postgres).
- All `read_text()` calls on transcript files must use `encoding="utf-8-sig"`.
- Follow `tests/test_sink_rescue.py`'s existing fixture style exactly (hand-built axis vectors via `fake_embeddings`, tests the *rule* not the embedding model) — do not introduce a different testing style for the new strategies.

---

### Task 1: `shared/trigger_quality.py` — `concrete_entity_density`

**Files:**
- Create: `Brain/shared/trigger_quality.py`
- Test: `Brain/tests/test_trigger_quality.py`

**Interfaces:**
- Produces: `concrete_entity_density(text: str) -> float` — used by Task 6 (`v1/layer_b.py::_content_gate`) and Task 5 (labeling script).

- [ ] **Step 1: Write the failing test**

```python
# Brain/tests/test_trigger_quality.py
"""shared/trigger_quality.py -- content signals shared by the sink-rescue design
(docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md, Status update 3)
and the trigger-quality-gate design
(docs/superpowers/specs/2026-08-04-layer-b-trigger-quality-gate-design.md).
Real spaCy runs here (these are structural/linguistic properties, not embeddings) --
this tests the signal functions themselves, not their callers.
"""
from shared.trigger_quality import concrete_entity_density


def test_concrete_entity_density_high_for_specific_text():
    text = "We use Workday and Phenom in Chicago with about 30 recruiters."
    assert concrete_entity_density(text) > 0.0


def test_concrete_entity_density_zero_for_generic_filler():
    text = "Yeah, I think that sounds fine to me, whatever works for you guys."
    assert concrete_entity_density(text) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_trigger_quality.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'shared.trigger_quality'`

- [ ] **Step 3: Write minimal implementation**

```python
# Brain/shared/trigger_quality.py
"""Pure, testable signals for judging trigger/response content quality --
shared by the sink-rescue design (docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md,
Status update 3) and the trigger-quality-gate design
(docs/superpowers/specs/2026-08-04-layer-b-trigger-quality-gate-design.md).
No I/O, no Gemma, no DB -- same style as shared/cluster_evidence.py.

Whichever design is implemented first creates this file; the other imports it
unchanged -- do not re-author it a second time.
"""
from __future__ import annotations

import numpy as np
import spacy

# NER-enabled pass -- v1/layer_b.py's own _nlp disables NER for speed in
# _is_substantive; that path is untouched, this is an additional narrow pass.
# Parser stays disabled on cost grounds (noun-chunk detection is out of scope).
_nlp_ner = spacy.load("en_core_web_lg", disable=["parser"])


def concrete_entity_density(text: str) -> float:
    """Named-entity count (spaCy NER) normalized by content-word count.
    Higher = more concrete/specific (names, numbers, tools, places);
    lower = more generic. Returns 0.0 for text with no content words at all."""
    doc = _nlp_ner(text)
    content_words = [t for t in doc if t.is_alpha and not t.is_stop]
    if not content_words:
        return 0.0
    return len(doc.ents) / len(content_words)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_trigger_quality.py -v`
Expected: PASS. If `test_concrete_entity_density_zero_for_generic_filler` fails because spaCy
tags something in that sentence as an entity, print `[(e.text, e.label_) for e in doc.ents]`
for that sentence and swap in a clearer generic example (e.g. remove "you guys" if it gets
tagged) — do not loosen the assertion.

- [ ] **Step 5: Commit**

```bash
git add Brain/shared/trigger_quality.py Brain/tests/test_trigger_quality.py
git commit -m "feat: add concrete_entity_density signal for sink-rescue content gate"
```

---

### Task 2: `shared/trigger_quality.py` — `preceding_turn_is_question`

**Files:**
- Modify: `Brain/shared/trigger_quality.py`
- Modify: `Brain/tests/test_trigger_quality.py`

**Interfaces:**
- Consumes: `preprocessing.transcript_parser.Turn`, `SpeakerRole` (existing — `Turn(index, speaker_raw, role, text, call_id)`, `SpeakerRole.NAREN/.JOVEO_OTHER/.CLIENT`).
- Produces: `preceding_turn_is_question(turns: list[Turn], turn_index: int) -> bool` — used by Task 6/7 (`v1/layer_b.py`, via a precomputed pair field) and Task 8 (harness).

- [ ] **Step 1: Write the failing test**

```python
# append to Brain/tests/test_trigger_quality.py
from preprocessing.transcript_parser import Turn, SpeakerRole
from shared.trigger_quality import preceding_turn_is_question


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_trigger_quality.py -v`
Expected: FAIL with `ImportError: cannot import name 'preceding_turn_is_question'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to Brain/shared/trigger_quality.py
from preprocessing.transcript_parser import SpeakerRole, Turn

_WH_TAGS = {"WDT", "WP", "WP$", "WRB"}


def preceding_turn_is_question(turns: list[Turn], turn_index: int) -> bool:
    """True if the NAREN turn immediately before turn_index ends in '?' or
    opens with a WH-word/auxiliary verb -- grammatical categories via spaCy's
    own tagger, not a curated content word list. False if turn_index is 0 or
    the prior turn isn't NAREN."""
    if turn_index <= 0:
        return False
    prev = turns[turn_index - 1]
    if prev.role != SpeakerRole.NAREN:
        return False
    text = prev.text.strip()
    if not text:
        return False
    if text.endswith("?"):
        return True
    doc = _nlp_ner(text)
    if len(doc) == 0:
        return False
    first = doc[0]
    return first.tag_ in _WH_TAGS or first.pos_ == "AUX"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_trigger_quality.py -v`
Expected: PASS (5 new tests + 2 from Task 1, all green).

- [ ] **Step 5: Commit**

```bash
git add Brain/shared/trigger_quality.py Brain/tests/test_trigger_quality.py
git commit -m "feat: add preceding_turn_is_question signal for sink-rescue content gate"
```

---

### Task 3: `shared/trigger_quality.py` — `sink_real_margin` + `trigger_response_coupling` (module completeness)

**Files:**
- Modify: `Brain/shared/trigger_quality.py`
- Modify: `Brain/tests/test_trigger_quality.py`

**Interfaces:**
- Produces: `sink_real_margin(trigger_vec, sink_centroids, real_centroids) -> float`, `trigger_response_coupling(trigger_vec, response_vec) -> float`. Neither is consumed by this plan's own code (they exist for the sibling trigger-quality-gate design and for module completeness, per the design doc) — no other task in this plan calls them.

- [ ] **Step 1: Write the failing test**

```python
# append to Brain/tests/test_trigger_quality.py
import pytest

from shared.trigger_quality import sink_real_margin, trigger_response_coupling


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_trigger_quality.py -v`
Expected: FAIL with `ImportError: cannot import name 'sink_real_margin'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to Brain/shared/trigger_quality.py
def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-10)


def sink_real_margin(
    trigger_vec: list[float],
    sink_centroids: list[list[float]],
    real_centroids: list[list[float]],
) -> float:
    """max(cos(trigger, sink)) - max(cos(trigger, real)). Higher = more
    filler-like. Not consumed by the sink-rescue gate -- specified here for
    module completeness; the trigger-quality-gate design's drop decision uses it."""
    t = _unit(np.array(trigger_vec))
    sink_sims = [float(t @ _unit(np.array(c))) for c in sink_centroids]
    real_sims = [float(t @ _unit(np.array(c))) for c in real_centroids]
    return max(sink_sims) - max(real_sims)


def trigger_response_coupling(trigger_vec: list[float], response_vec: list[float]) -> float:
    """Plain cosine between a pair's own trigger and response embeddings.
    Not consumed by the sink-rescue gate -- available for the
    trigger-quality-gate design's combining logic."""
    return float(_unit(np.array(trigger_vec)) @ _unit(np.array(response_vec)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_trigger_quality.py -v`
Expected: PASS (all 9 tests green).

- [ ] **Step 5: Commit**

```bash
git add Brain/shared/trigger_quality.py Brain/tests/test_trigger_quality.py
git commit -m "feat: add sink_real_margin and trigger_response_coupling for module completeness"
```

---

### Task 4: `tuning.yaml` + `shared/tuning.py` — new threshold keys

**Files:**
- Modify: `Brain/tuning.yaml`
- Modify: `Brain/shared/tuning.py`
- Test: `Brain/tests/test_tuning.py` (check for a hardcoded full-key fixture and extend it if present)

**Interfaces:**
- Produces: `LayerBTuning.sink_rescue_density_threshold: float`, `LayerBTuning.sink_rescue_density_borderline_floor: float` — consumed by Task 6/7's `_content_gate`.

- [ ] **Step 1: Write the failing test**

```python
# append to Brain/tests/test_tuning.py (or create a small addition if the file
# doesn't already assert individual LayerBTuning fields -- check first)
from shared.tuning import load_tuning


def test_layer_b_tuning_has_density_gate_keys():
    tuning = load_tuning().layer_b
    assert isinstance(tuning.sink_rescue_density_threshold, float)
    assert isinstance(tuning.sink_rescue_density_borderline_floor, float)
    assert tuning.sink_rescue_density_borderline_floor < tuning.sink_rescue_density_threshold
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_tuning.py -v`
Expected: FAIL — `load_tuning()` raises `ValueError: tuning.yaml: missing key(s) in layer_b: [...]`
because `LayerBTuning` doesn't have the new fields yet but the test references them (or the
dataclass instantiation itself fails first if you add the yaml keys before the dataclass fields —
either order fails loudly, which is the point of this loader).

- [ ] **Step 3: Write minimal implementation**

Add two fields to `LayerBTuning` in `Brain/shared/tuning.py`:

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
    sink_rescue_response_min_similarity: float
    sink_rescue_trigger_weak_floor: float
    sink_rescue_blend_alpha: float
    sink_rescue_density_threshold: float
    sink_rescue_density_borderline_floor: float
```

Add the two keys to `Brain/tuning.yaml`'s `layer_b:` section, immediately after
`sink_rescue_blend_alpha` and before the `layer_c:` section:

```yaml
  # Content-signal gate replacing the two floors above for content_gate_narrow/
  # content_gate_broad (see Status update 3 in
  # docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md).
  # concrete_entity_density(response) >= this value -> rescue, regardless of
  # preceding_turn_is_question. UNCALIBRATED placeholder -- set from
  # label_trigger_quality_sample.py's density-vs-label distribution, not guessed.
  sink_rescue_density_threshold: 0.15

  # Below this density, never rescue regardless of preceding_turn_is_question.
  # Between this floor and sink_rescue_density_threshold is the borderline band
  # where preceding_turn_is_question breaks the tie. UNCALIBRATED placeholder.
  sink_rescue_density_borderline_floor: 0.05
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_tuning.py -v`
Expected: PASS. Also run the full suite once here to catch any other test that enumerates
`LayerBTuning`'s fields by name: `..\.venv\Scripts\pytest tests/ -v`. If any other test fails
with a field-count/field-name mismatch, add the two new keys to that test's fixture too.

- [ ] **Step 5: Commit**

```bash
git add Brain/tuning.yaml Brain/shared/tuning.py Brain/tests/test_tuning.py
git commit -m "feat: add sink_rescue_density_threshold and sink_rescue_density_borderline_floor tuning keys"
```

---

### Task 5: `label_trigger_quality_sample.py` — ground-truth labeling script

**Files:**
- Create: `Brain/label_trigger_quality_sample.py`

**Interfaces:**
- Consumes: `shared.storage.get_connection`, `shared.storage.get_scenarios`, `shared.gemma.call_gemma`, `shared.trigger_quality.concrete_entity_density`, `config.load_config`.
- Produces: a local file `Brain/trigger_quality_labels.json` — a list of
  `{"pair_id": int, "trigger_text": str, "response_text": str, "coachable": bool,
  "reason": str, "concrete_entity_density": float}` — consumed by Task 8
  (`compare_sink_rescue.py`'s label-split percentile print) and by whoever sets
  `sink_rescue_density_threshold`/`sink_rescue_density_borderline_floor` afterwards.

This script has no meaningful "failing test" step (it's a one-shot calibration script that
calls Gemma and reads live Postgres, mirroring `compare_sink_rescue.py`'s own style) — it is
verified by running it against the real `public` schema and reading its printed output, the
same verification method every other calibration script in this codebase uses (`compare_sink_rescue.py`,
`compare_matching_subset.py`, `dry_run_layer_a.py`).

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""One-time ground-truth labeling for the sink-rescue content gate (Status
update 3 in docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md)
and the trigger-quality-gate design's own drop decision -- both need the same
"is this sink-bound pair's response actually coachable" label, so this script
is shared rather than duplicated.

Pulls a stratified sample of currently sink-bound pairs (no single sink
dominates), batches them 5-at-a-time to Gemma for a yes/no coachability
judgment, computes concrete_entity_density for each, and writes
trigger_quality_labels.json. No DB writes. Read-only against Postgres.
"""
from __future__ import annotations
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

from config import load_config
from shared import storage, trigger_quality
from shared.gemma import call_gemma

_SAMPLE_SIZE = 150
_PER_SINK_CAP = 15  # no single sink can contribute more than this many pairs
_BATCH_SIZE = 5
_OUTPUT_PATH = Path(__file__).parent / "trigger_quality_labels.json"

_PROMPT_TEMPLATE = """You are judging whether a customer-success call exchange contains real,
coachable content or is just conversational filler (backchannel, small talk, logistics).

For each numbered pair below, read the CLIENT trigger and the NAREN response. Answer whether
the RESPONSE itself is genuinely coachable content (a real answer worth training a coach's
rubric on), not whether the trigger sounds substantive.

Return ONLY a JSON object of the form {{"judgments": [{{"index": 1, "coachable": true, "reason": "..."}}, ...]}},
one entry per pair, in the same order given. "reason" is one sentence.

{pairs_block}
"""


def _load_sink_bound_pairs(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.pair_id, p.trigger_text, p.response_text, p.scenario_key "
            "FROM kb_pairs p JOIN scenarios s ON s.scenario_key = p.scenario_key "
            "WHERE s.is_coachable = FALSE "
            "ORDER BY p.pair_id"
        )
        rows = cur.fetchall()
    return [
        {"pair_id": r[0], "trigger_text": r[1], "response_text": r[2], "sink_key": r[3]}
        for r in rows
    ]


def _stratified_sample(pairs: list[dict], sample_size: int, per_sink_cap: int) -> list[dict]:
    by_sink: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        by_sink[p["sink_key"]].append(p)

    rng = random.Random(0)
    for group in by_sink.values():
        rng.shuffle(group)

    capped = [p for group in by_sink.values() for p in group[:per_sink_cap]]
    rng.shuffle(capped)
    return capped[:sample_size]


def _judge_batch(batch: list[dict], api_keys) -> list[dict]:
    pairs_block = "\n\n".join(
        f"{i + 1}. TRIGGER: {p['trigger_text']!r}\n   RESPONSE: {p['response_text']!r}"
        for i, p in enumerate(batch)
    )
    result = call_gemma(_PROMPT_TEMPLATE.format(pairs_block=pairs_block), api_keys)
    judgments = result if isinstance(result, list) else result.get("judgments", [])
    by_index = {j["index"]: j for j in judgments}
    out = []
    for i, p in enumerate(batch):
        j = by_index.get(i + 1, {"coachable": False, "reason": "no judgment returned"})
        out.append({**p, "coachable": bool(j["coachable"]), "reason": j["reason"]})
    return out


def main() -> None:
    config = load_config()
    conn = storage.get_connection(config.database_url)
    sink_pairs = _load_sink_bound_pairs(conn)
    conn.close()

    print(f"Loaded {len(sink_pairs)} sink-bound pair(s) across "
          f"{len({p['sink_key'] for p in sink_pairs})} sink(s).")

    sample = _stratified_sample(sink_pairs, _SAMPLE_SIZE, _PER_SINK_CAP)
    print(f"Sampled {len(sample)} pair(s) for labeling.")

    labeled = []
    for start in range(0, len(sample), _BATCH_SIZE):
        batch = sample[start:start + _BATCH_SIZE]
        labeled.extend(_judge_batch(batch, config.gemma_api_keys))
        print(f"  Judged {len(labeled)}/{len(sample)}...")

    for entry in labeled:
        entry["concrete_entity_density"] = trigger_quality.concrete_entity_density(
            entry["response_text"]
        )

    coachable_densities = sorted(e["concrete_entity_density"] for e in labeled if e["coachable"])
    junk_densities = sorted(e["concrete_entity_density"] for e in labeled if not e["coachable"])

    def _pct(values, p):
        if not values:
            return float("nan")
        idx = min(len(values) - 1, int(len(values) * p / 100))
        return values[idx]

    print(f"\nconcrete_entity_density(response), coachable (n={len(coachable_densities)}):")
    print("  " + "  ".join(f"p{p}={_pct(coachable_densities, p):.3f}" for p in (10, 25, 50, 75, 90)))
    print(f"\nconcrete_entity_density(response), NOT coachable (n={len(junk_densities)}):")
    print("  " + "  ".join(f"p{p}={_pct(junk_densities, p):.3f}" for p in (10, 25, 50, 75, 90)))

    _OUTPUT_PATH.write_text(json.dumps(labeled, indent=2), encoding="utf-8")
    print(f"\nWrote {len(labeled)} labeled pair(s) to {_OUTPUT_PATH}.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the real schema**

Run (from `Brain/`, venv active, `DATABASE_URL`/`GEMMA_API_KEY` set):
`python label_trigger_quality_sample.py`

Expected: prints sink-bound pair count, sample size, batch progress, then the two density
percentile blocks (coachable vs not), then confirms `trigger_quality_labels.json` was written.

- [ ] **Step 3: Read the output before trusting it**

Per this codebase's own repeated rule, read a sample of `trigger_quality_labels.json` directly —
print 10 random entries (trigger, response, coachable, reason) and manually sanity-check a few
against the Gemma reasons, the same discipline `compare_sink_rescue.py`'s own samples were held to.
Do not proceed to setting `sink_rescue_density_threshold`/`sink_rescue_density_borderline_floor`
from the percentiles alone without this read.

- [ ] **Step 4: Commit**

```bash
git add Brain/label_trigger_quality_sample.py
git commit -m "feat: add ground-truth labeling script for the sink-rescue content gate"
```

Note: `Brain/trigger_quality_labels.json` is a data artifact, not source — do not commit it;
add it to `Brain/.gitignore` if not already covered by an existing pattern.

---

### Task 6: `v1/layer_b.py` — `content_gate_narrow` strategy

**Files:**
- Modify: `Brain/v1/layer_b.py`
- Modify: `Brain/tests/test_sink_rescue.py`

**Interfaces:**
- Consumes: `shared.trigger_quality.concrete_entity_density` (Task 1), `LayerBTuning.sink_rescue_density_threshold`/`sink_rescue_density_borderline_floor` (Task 4).
- Produces: `assign_scenarios_with_sink_rescue(..., strategy="content_gate_narrow")` — a pair dict
  may now carry an optional `preceding_turn_is_question: bool` field (default `False` if absent);
  this is precomputed by the caller (Task 8's harness, or a future pipeline wiring), never
  computed inside `assign_scenarios_with_sink_rescue` itself (which has no access to `turns`).

- [ ] **Step 1: Write the failing test**

```python
# append to Brain/tests/test_sink_rescue.py
from shared.tuning import load_tuning
from v1 import layer_b


@pytest.fixture
def fake_content_signals(monkeypatch):
    """Monkeypatches concrete_entity_density to read a 'density:X' marker out of
    response_text, mirroring fake_embeddings' 'axis:weight' token convention.
    preceding_turn_is_question is set directly on the pair dict by each test --
    _content_gate reads it from the pair, it never calls the real signal function."""
    def density(text):
        for token in text.split():
            name, _, weight = token.partition(":")
            if name == "density":
                return float(weight)
        raise AssertionError(f"test response_text has no density: marker: {text!r}")

    monkeypatch.setattr(layer_b.trigger_quality, "concrete_entity_density", density)


class TestContentGateNarrow:
    def test_rescues_sink_bound_pair_when_response_density_clears_threshold(
        self, fake_embeddings, fake_content_signals,
    ):
        """Trigger alone matches sink 'ack'; response density clears
        sink_rescue_density_threshold -- must rescue regardless of
        preceding_turn_is_question (unset/False here)."""
        threshold = load_tuning().layer_b.sink_rescue_density_threshold
        pairs = [_pair("ack:1.0", f"pricing:1.0 density:{threshold + 0.05}")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_narrow",
        )
        assert pairs[0]["scenario_keys"] == ["pricing"]

    def test_stays_in_sink_when_response_density_is_clearly_low(
        self, fake_embeddings, fake_content_signals,
    ):
        floor = load_tuning().layer_b.sink_rescue_density_borderline_floor
        pairs = [_pair("ack:1.0", f"pricing:1.0 density:{max(floor - 0.02, 0.0)}")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_narrow",
        )
        assert pairs[0]["scenario_keys"] == ["ack"]

    def test_borderline_density_rescues_only_when_preceding_turn_is_question(
        self, fake_embeddings, fake_content_signals,
    ):
        threshold = load_tuning().layer_b.sink_rescue_density_threshold
        floor = load_tuning().layer_b.sink_rescue_density_borderline_floor
        assert floor < threshold, (
            "sink_rescue_density_borderline_floor must stay below "
            "sink_rescue_density_threshold for a real borderline band to exist"
        )
        mid = (threshold + floor) / 2

        with_question = _pair("ack:1.0", f"pricing:1.0 density:{mid}")
        with_question["preceding_turn_is_question"] = True
        without_question = _pair("ack:1.0", f"pricing:1.0 density:{mid}")
        without_question["preceding_turn_is_question"] = False

        pairs = [with_question, without_question]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_narrow",
        )
        assert pairs[0]["scenario_keys"] == ["pricing"]
        assert pairs[1]["scenario_keys"] == ["ack"]

    def test_non_sink_pair_is_unaffected_regardless_of_density(
        self, fake_embeddings, fake_content_signals,
    ):
        pairs = [_pair("pricing:1.0", "quality:1.0 density:0.9")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_narrow",
        )
        assert pairs[0]["scenario_keys"] == ["pricing"]

    def test_every_pair_is_always_assigned(self, fake_embeddings, fake_content_signals):
        pairs = [
            _pair("pricing:1.0", "quality:1.0 density:0.9"),
            _pair("ack:1.0", "pricing:1.0 density:0.9"),
            _pair("ack:1.0", "ack:1.0 density:0.0"),
        ]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_narrow",
        )
        assert all(p["scenario_key"] is not None for p in pairs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_sink_rescue.py -v -k ContentGateNarrow`
Expected: FAIL — `ValueError: unknown sink-rescue strategy: 'content_gate_narrow'` (and
`AttributeError: module 'v1.layer_b' has no attribute 'trigger_quality'` for the fixture, since
the import doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

Add the import near the top of `Brain/v1/layer_b.py` (after the existing `from shared.tuning
import load_tuning` line):

```python
from shared import trigger_quality
```

Add two new helpers right before `assign_scenarios_with_sink_rescue` (after `_flat_pick`):

```python
def _content_gate(pair: dict, tuning) -> bool:
    """Content-signal rescue gate (Status update 3 in
    docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md):
    concrete_entity_density(response) is the primary signal; preceding_turn_is_question
    (precomputed by the caller onto pair["preceding_turn_is_question"] -- this function
    has no access to the transcript's turns list) only breaks ties in the borderline band.
    """
    density = trigger_quality.concrete_entity_density(pair["response_text"])
    if density >= tuning.sink_rescue_density_threshold:
        return True
    if density < tuning.sink_rescue_density_borderline_floor:
        return False
    return bool(pair.get("preceding_turn_is_question", False))


def _content_route(i, response_sims, scenario_keys, is_sink, tuning):
    """Routing is unchanged from response_only/or_rule -- relative top-K on the
    response's own similarity, restricted to non-sink candidates. No absolute
    floor: that job now belongs to _content_gate, not this function."""
    return _topk_pick(
        response_sims[i], scenario_keys, is_sink,
        tuning.max_scenarios_per_pair, tuning.sink_rescue_relative_margin,
    )
```

Add a new `elif` branch inside `assign_scenarios_with_sink_rescue`'s per-pair loop, after the
`elif strategy == "blended":` block and before the final `else: raise ValueError(...)`:

```python
        elif strategy == "content_gate_narrow":
            if is_sink[t_best_j] and _content_gate(pair, tuning):
                rescued = _content_route(i, response_sims, scenario_keys, is_sink, tuning)
                _assign(pair, rescued or [scenario_keys[t_best_j]])
            else:
                _assign(pair, _flat_pick(
                    t_sims, scenario_keys, is_sink,
                    tuning.max_scenarios_per_pair, tuning.relative_margin,
                ))
```

Update the function's docstring to mention the two new strategies and the
`preceding_turn_is_question` pair-field convention (append, don't rewrite, the existing
docstring paragraphs).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_sink_rescue.py -v -k ContentGateNarrow`
Expected: PASS (5 new tests green). Then run the full file to confirm no regression:
`..\.venv\Scripts\pytest tests/test_sink_rescue.py -v`

- [ ] **Step 5: Commit**

```bash
git add Brain/v1/layer_b.py Brain/tests/test_sink_rescue.py
git commit -m "feat: add content_gate_narrow sink-rescue strategy"
```

---

### Task 7: `v1/layer_b.py` — `content_gate_broad` strategy

**Files:**
- Modify: `Brain/v1/layer_b.py`
- Modify: `Brain/tests/test_sink_rescue.py`

**Interfaces:**
- Consumes: `_content_gate`, `_content_route` (Task 6).
- Produces: `assign_scenarios_with_sink_rescue(..., strategy="content_gate_broad")`.

- [ ] **Step 1: Write the failing test**

```python
# append to Brain/tests/test_sink_rescue.py
class TestContentGateBroad:
    def test_overrides_a_non_sink_pair_when_response_density_clears_threshold(
        self, fake_embeddings, fake_content_signals,
    ):
        """Unlike content_gate_narrow, broad reconsiders a pair whose trigger
        already matched a real (non-sink) scenario, if the response's density
        clears the gate and routes somewhere else."""
        threshold = load_tuning().layer_b.sink_rescue_density_threshold
        pairs = [_pair("pricing:1.0", f"quality:1.0 density:{threshold + 0.05}")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_broad",
        )
        assert pairs[0]["scenario_keys"] == ["quality"]

    def test_leaves_non_sink_pair_alone_when_response_density_is_low(
        self, fake_embeddings, fake_content_signals,
    ):
        floor = load_tuning().layer_b.sink_rescue_density_borderline_floor
        pairs = [_pair("pricing:1.0", f"quality:1.0 density:{max(floor - 0.02, 0.0)}")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_broad",
        )
        assert pairs[0]["scenario_keys"] == ["pricing"]

    def test_rescues_sink_bound_pair_same_as_narrow(self, fake_embeddings, fake_content_signals):
        threshold = load_tuning().layer_b.sink_rescue_density_threshold
        pairs = [_pair("ack:1.0", f"pricing:1.0 density:{threshold + 0.05}")]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_broad",
        )
        assert pairs[0]["scenario_keys"] == ["pricing"]

    def test_every_pair_is_always_assigned(self, fake_embeddings, fake_content_signals):
        pairs = [
            _pair("pricing:1.0", "quality:1.0 density:0.9"),
            _pair("ack:1.0", "pricing:1.0 density:0.9"),
            _pair("ack:1.0", "ack:1.0 density:0.0"),
        ]
        layer_b.assign_scenarios_with_sink_rescue(
            pairs, _scenario_map(), config=None, strategy="content_gate_broad",
        )
        assert all(p["scenario_key"] is not None for p in pairs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_sink_rescue.py -v -k ContentGateBroad`
Expected: FAIL with `ValueError: unknown sink-rescue strategy: 'content_gate_broad'`

- [ ] **Step 3: Write minimal implementation**

Add another `elif` branch in `assign_scenarios_with_sink_rescue`, right after the
`content_gate_narrow` branch added in Task 6:

```python
        elif strategy == "content_gate_broad":
            if _content_gate(pair, tuning):
                rescued = _content_route(i, response_sims, scenario_keys, is_sink, tuning)
                _assign(pair, rescued or [scenario_keys[t_best_j]])
            else:
                _assign(pair, _flat_pick(
                    t_sims, scenario_keys, is_sink,
                    tuning.max_scenarios_per_pair, tuning.relative_margin,
                ))
```

Note the only difference from `content_gate_narrow`: no `is_sink[t_best_j] and` guard — the
content gate alone decides eligibility for every pair, sink-bound or not, mirroring `or_rule`'s
broader blast radius but gated on content instead of trigger-weakness.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_sink_rescue.py -v`
Expected: PASS — all tests in the file green (existing `response_only`/`or_rule`/`blended` tests
plus both new classes).

- [ ] **Step 5: Commit**

```bash
git add Brain/v1/layer_b.py Brain/tests/test_sink_rescue.py
git commit -m "feat: add content_gate_broad sink-rescue strategy"
```

---

### Task 8: `compare_sink_rescue.py` — wire in the two new strategies

**Files:**
- Modify: `Brain/compare_sink_rescue.py`

**Interfaces:**
- Consumes: `preprocessing.transcript_parser.parse_transcript`/`load_roster` (existing),
  `shared.trigger_quality.preceding_turn_is_question` (Task 2),
  `Brain/trigger_quality_labels.json` (Task 5, optional — script degrades gracefully if absent).

This is a calibration script, not unit-tested — verified by running it against the real schema
and reading its output, same as Task 5.

- [ ] **Step 1: Add transcript re-parsing to reconstruct `turns`**

`kb_pairs` only stores `call_id`/`turn_index`, not the turn list itself — add a step that joins
back to `calls.filename`, locates the source transcript, and re-parses it once per distinct
transcript (not once per pair). Add near the top of `Brain/compare_sink_rescue.py`:

```python
import json
from pathlib import Path

from preprocessing.transcript_parser import parse_transcript, load_roster
from shared import trigger_quality
```

Replace `_load_real_pairs` to also fetch `call_id`, `turn_index`, and the call's filename:

```python
def _load_real_pairs(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.pair_id, p.trigger_text, p.response_text, p.scenario_key, "
            "p.call_id, p.turn_index, c.filename "
            "FROM kb_pairs p JOIN calls c ON c.call_id = p.call_id "
            "ORDER BY p.pair_id"
        )
        rows = cur.fetchall()
    return [
        {"pair_id": r[0], "trigger_text": r[1], "response_text": r[2], "flat_key": r[3],
         "call_id": r[4], "turn_index": r[5], "filename": r[6]}
        for r in rows
    ]
```

Add a transcript locator and the per-call re-parse pass:

```python
def _locate_transcript(filename: str) -> Path:
    for directory in ("recordings", "csm_recordings"):
        candidate = Path(directory) / filename
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"transcript {filename!r} not found in recordings/ or csm_recordings/ -- "
        "needed to reconstruct turns for preceding_turn_is_question"
    )


def _attach_preceding_turn_is_question(real_pairs: list[dict], config) -> None:
    by_filename: dict[str, list[dict]] = {}
    for p in real_pairs:
        by_filename.setdefault(p["filename"], []).append(p)

    print(f"\nRe-parsing {len(by_filename)} transcript(s) for preceding_turn_is_question...")
    for filename, group in by_filename.items():
        txt_path = _locate_transcript(filename)
        turns = parse_transcript(
            str(txt_path), config.joveo_speakers_lower, config.naren_name_lower,
            roster=load_roster(str(txt_path)),
        )
        for p in group:
            p["preceding_turn_is_question"] = trigger_quality.preceding_turn_is_question(
                turns, p["turn_index"]
            )
```

- [ ] **Step 2: Thread the new field through `_fresh_pairs` and call the new strategies**

```python
def _fresh_pairs(real_pairs: list[dict]) -> list[dict]:
    return [
        {"trigger_text": p["trigger_text"], "response_text": p["response_text"],
         "scenario_key": None, "scenario_id": None,
         "preceding_turn_is_question": p["preceding_turn_is_question"]}
        for p in real_pairs
    ]
```

In `main()`, call `_attach_preceding_turn_is_question(real_pairs, config)` once, right after
`_load_real_pairs`, and add the two new strategies to the loop:

```python
    _attach_preceding_turn_is_question(real_pairs, config)

    for strategy in ("response_only", "or_rule", "blended", "content_gate_narrow", "content_gate_broad"):
        pairs = _fresh_pairs(real_pairs)
        layer_b.assign_scenarios_with_sink_rescue(pairs, scenario_map, config=None, strategy=strategy)
        _report(strategy, real_pairs, scenario_map, pairs)
```

- [ ] **Step 3: Print density percentiles split by ground-truth label, if available**

Add this right after `_print_response_similarity_percentiles(...)` in `main()`:

```python
    labels_path = Path(__file__).parent / "trigger_quality_labels.json"
    if labels_path.exists():
        labeled = json.loads(labels_path.read_text(encoding="utf-8"))
        coachable = sorted(e["concrete_entity_density"] for e in labeled if e["coachable"])
        junk = sorted(e["concrete_entity_density"] for e in labeled if not e["coachable"])

        def _pct(values, p):
            if not values:
                return float("nan")
            idx = min(len(values) - 1, int(len(values) * p / 100))
            return values[idx]

        print(f"\nconcrete_entity_density(response), labeled coachable (n={len(coachable)}):")
        print("  " + "  ".join(f"p{p}={_pct(coachable, p):.3f}" for p in (10, 25, 50, 75, 90)))
        print(f"concrete_entity_density(response), labeled NOT coachable (n={len(junk)}):")
        print("  " + "  ".join(f"p{p}={_pct(junk, p):.3f}" for p in (10, 25, 50, 75, 90)))
    else:
        print(f"\n({labels_path.name} not found -- run label_trigger_quality_sample.py first "
              "for the label-split density view.)")
```

- [ ] **Step 4: Run it against the real schema**

Run (from `Brain/`, venv active, `DATABASE_URL` set):
`python compare_sink_rescue.py`

Expected: same output shape as the round-1/round-2 runs, plus two new `=== content_gate_narrow
===` / `=== content_gate_broad ===` sections with rescue rate, absorbing scenarios, and sample
pairs, and (if Task 5 has been run first) the label-split density percentile block. Save the
full output to `Brain/compare_sink_rescue_round3_<date>.log`, matching the existing
`compare_sink_rescue_20260804.log` / `compare_sink_rescue_round2_20260804.log` naming convention.

- [ ] **Step 5: Read the samples and record a status update**

Per this design's own repeated discipline, read the printed rescued/near-miss samples for both
new strategies before drawing any conclusion from the rescue-rate numbers alone. Append a
"Status update 4" section to `docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md`
recording what was found — this is a follow-up write, not part of this implementation task, but
note it here so it isn't forgotten.

- [ ] **Step 6: Commit**

```bash
git add Brain/compare_sink_rescue.py
git commit -m "feat: add content_gate_narrow/broad to the sink-rescue comparison harness"
```

---

## Self-Review Notes

- **Spec coverage:** All of Status update 3's pieces are covered — the shared module (Tasks 1-3),
  the two new tuning keys (Task 4), the ground-truth labeling reuse (Task 5), both new strategies
  (Tasks 6-7), and the harness updates including the transcript re-parse dependency and the
  label-split percentile print (Task 8).
- **Not in scope, by design:** wiring any strategy into `assign_scenarios`/`v1/pipeline.py`/
  `v2/pipeline.py`, choosing final values for `sink_rescue_density_threshold`/
  `sink_rescue_density_borderline_floor` (that's Task 5 Step 3 + a human read, not a code task),
  and the sibling trigger-quality-gate design's own drop filter (`filter_junk_pairs`) — it imports
  `shared/trigger_quality.py` from this plan but is its own separate plan.
- **Type consistency check:** `_content_gate(pair, tuning)` and `_content_route(i, response_sims,
  scenario_keys, is_sink, tuning)` signatures are identical between Task 6 (definition) and Task 7
  (reuse) — verified no drift between the two tasks' code blocks.
