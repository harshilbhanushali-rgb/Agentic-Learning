# Response-Taxonomy Auto-Pass — Implementation Plan

**Goal:** Build the permanent, automatic homeless-topic graduation pass described in
`docs/superpowers/specs/2026-08-07-response-taxonomy-auto-pass-design.md` (including the
`primary_topic_key` fix and the five follow-up-risk decisions folded into that spec during
this planning pass), wire it into the V2 pipeline, then — on explicit go-ahead, in a separate
later step — snapshot the production schema and run it for real.

**Architecture:**

- `Brain/shared/topic_grouping.py` gains `match_existing_primary_topic` — a pure helper that
  finds (or signals "no match for") the nearest existing `primary_topics` centroid for a new
  scenario's embedding.
- `Brain/shared/response_taxonomy.py` — **new** shared module. Extracts
  `dry_run_response_taxonomy.py`'s clustering/pair-loading/adjudication logic
  (`_load_all_pairs`, `_cluster_corpus`, `_scenario_sides`, `_build_records`,
  `_render_cluster`, `_adjudicate`) so the dry-run script and the new auto-pass both call one
  implementation instead of duplicating it — same precedent as extracting
  `v2/layer_c.py::build_clause_pool` during the sink-pool diagnostic work.
  `dry_run_response_taxonomy.py` is updated to import from here; its own CLI is unchanged.
- `Brain/response_taxonomy_auto_pass.py` — **new**. `run_auto_pass(config, conn, run_id)`
  entry point: cluster → filter → match/track (Jaccard, with the two fixes below) → graduate
  consensus-reaching candidates (with the `primary_topic_key` fix) → log.
- `Brain/db/schema.sql` gains `response_taxonomy_candidates` (with `stable_pair_ids`).
- `Brain/tuning.yaml` / `Brain/shared/tuning.py` gain three new `layer_a` keys:
  `response_taxonomy_auto_pass_enabled` (default `false`), `response_taxonomy_consensus_runs`
  (default `3`), `response_taxonomy_candidate_match_overlap` (default `0.5`).
- `Brain/v2/pipeline.py` calls `response_taxonomy_auto_pass.run_auto_pass` immediately after
  `layer_c.run_layer_c_v2`, wrapped in try/except that logs and swallows.

**Tech Stack:** Python 3.11, numpy, psycopg (mocked in every test in this plan — no real DB
write happens during implementation), pytest, `unittest.mock.MagicMock`, the existing
`preprocessing.embedder` disk cache, Gemma via `shared.gemma.call_gemma`.

**Reference spec:** `docs/superpowers/specs/2026-08-07-response-taxonomy-auto-pass-design.md`
(read the "Fix: `primary_topic_key` orphaning" and "Decisions on five follow-up risks"
sections — those are what several tasks below implement).

## Global Constraints

- **No write against any real database anywhere in this plan.** Every test uses
  `unittest.mock.MagicMock` for the connection/cursor, matching
  `tests/test_graduate_sink_topics.py`'s existing discipline. Reads against the real `public`
  schema are fine and are how Task 8 exercises `shared/response_taxonomy.py`'s DB-touching
  pieces informally (rerunning `dry_run_response_taxonomy.py` unchanged), but that is a
  read-only sanity check, not a test.
- `tuning.yaml`'s `response_taxonomy_auto_pass_enabled` stays `false` through every task in
  this plan — it only flips to `true` in the later, separate "run it for real" session, on
  explicit go-ahead, immediately preceded by the production schema snapshot.
- Graduation must call `v2.layer_c.run_layer_c_v2`, never V1's `layer_c.run_layer_c` — same
  trap already flagged in the prior plan for `graduate_sink_topics.py`.
- A candidate that fails `passes_reconciliation_gate` must be **discarded**, never
  force-routed into its nearest coachable scenario — the `by_cluster` failure mode this whole
  investigation has repeatedly rejected.
- Every new tuning value goes into `tuning.yaml` under `layer_a`, with a matching dataclass
  field in `shared/tuning.py` — unknown/missing keys must raise, per this codebase's existing
  rule.
- The auto-pass must never raise out of `run_auto_pass` in a way that fails the overall
  pipeline run — the call site in `v2/pipeline.py` wraps it in try/except, but `run_auto_pass`
  itself should also be defensive about a single bad candidate not aborting the whole pass.

---

### Task 1: `topic_grouping.match_existing_primary_topic` — pure, tested helper

**Files:**

- Modify: `Brain/shared/topic_grouping.py`
- Modify: `Brain/tests/test_topic_grouping.py`

**Interfaces:**

- Produces: `topic_grouping.match_existing_primary_topic(centroid: np.ndarray, candidate_keys: list[str], candidate_vecs: np.ndarray, threshold: float) -> str | None` — consumed by Task 7's module.

- [ ] **Step 1: Write the failing tests**

Add to `Brain/tests/test_topic_grouping.py` (reuse the existing `_angle_vec` helper):

```python
class TestMatchExistingPrimaryTopic:
    def test_no_candidates_returns_none(self):
        assert tg.match_existing_primary_topic(_angle_vec(0), [], np.empty((0, 2)), 0.85) is None

    def test_close_match_returns_its_key(self):
        keys = ["a", "b"]
        vecs = np.stack([_angle_vec(0), _angle_vec(90)])
        assert tg.match_existing_primary_topic(_angle_vec(1), keys, vecs, 0.85) == "a"

    def test_no_candidate_clears_threshold_returns_none(self):
        keys = ["a", "b"]
        vecs = np.stack([_angle_vec(0), _angle_vec(90)])
        # 45 degrees from both -- cosine ~0.707, below a strict 0.85 threshold.
        assert tg.match_existing_primary_topic(_angle_vec(45), keys, vecs, 0.85) is None

    def test_picks_the_single_best_match_when_multiple_clear_threshold(self):
        keys = ["far_but_ok", "closest"]
        vecs = np.stack([_angle_vec(20), _angle_vec(2)])
        assert tg.match_existing_primary_topic(_angle_vec(0), keys, vecs, 0.80) == "closest"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_topic_grouping.py::TestMatchExistingPrimaryTopic -v`
Expected: FAIL — `AttributeError: module 'shared.topic_grouping' has no attribute 'match_existing_primary_topic'`.

- [ ] **Step 3: Implement it**

Add to `Brain/shared/topic_grouping.py`:

```python
def match_existing_primary_topic(
    centroid: np.ndarray, candidate_keys: list[str], candidate_vecs: np.ndarray, threshold: float,
) -> str | None:
    """Nearest-neighbor match of a single new embedding against an existing primary_topics
    population, for assigning a graduated scenario's primary_topic_key.

    Reuses the one-vs-population cosine-argmax-plus-threshold shape this module and
    cluster_evidence.py already use elsewhere (cluster_evidence.nearest_sink_index is the
    closest existing analogue) rather than reaching for merge_by_similarity, which groups a
    whole population pairwise -- overkill for matching one new item against an already-fixed
    set of candidates.

    Returns None when there are no candidates, or when the best match does not clear
    threshold -- both cases mean the caller should create a new primary_topics row instead
    of reusing one.
    """
    if len(candidate_keys) == 0:
        return None
    c = centroid / (np.linalg.norm(centroid) + 1e-10)
    arr = np.asarray(candidate_vecs, dtype=np.float32)
    normed = arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-10)
    sims = normed @ c
    best = int(np.argmax(sims))
    if float(sims[best]) < threshold:
        return None
    return candidate_keys[best]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_topic_grouping.py -v`
Expected: PASS, all prior tests plus 4 new ones.

- [ ] **Step 5: Commit**

```bash
git add Brain/shared/topic_grouping.py Brain/tests/test_topic_grouping.py
git commit -m "Add match_existing_primary_topic helper for graduated-scenario primary_topic_key assignment"
```

---

### Task 2: Three new `tuning.yaml` keys

**Files:**

- Modify: `Brain/tuning.yaml`
- Modify: `Brain/shared/tuning.py` (`LayerATuning`)
- Modify: `Brain/tests/test_tuning.py`

- [ ] **Step 1: Write the failing test**

In `Brain/tests/test_tuning.py`, add to `_GOOD`'s `layer_a:` block (after
`response_taxonomy_purity_gate: 0.90`):

```yaml
  response_taxonomy_auto_pass_enabled: false
  response_taxonomy_consensus_runs: 3
  response_taxonomy_candidate_match_overlap: 0.5
```

Add to `test_shipped_tuning_yaml_is_valid`:

```python
    assert t.layer_a.response_taxonomy_auto_pass_enabled in (True, False)
    assert t.layer_a.response_taxonomy_consensus_runs >= 1
    assert 0.0 < t.layer_a.response_taxonomy_candidate_match_overlap <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_tuning.py -v`
Expected: FAIL — `ValueError: tuning.yaml: unknown key(s) in layer_a: [...]`.

- [ ] **Step 3: Add the fields to `LayerATuning`**

In `Brain/shared/tuning.py`, append to `LayerATuning` (after `response_taxonomy_purity_gate`):

```python
    response_taxonomy_auto_pass_enabled: bool
    response_taxonomy_consensus_runs: int
    response_taxonomy_candidate_match_overlap: float
```

- [ ] **Step 4: Add the keys to the real `tuning.yaml`**

In `Brain/tuning.yaml`, insert after `response_taxonomy_purity_gate: 0.90` (still inside
`layer_a:`, before `layer_b:`):

```yaml
  # Permanent auto-pass (see docs/superpowers/specs/2026-08-07-response-taxonomy-auto-pass-
  # design.md): runs after every pipeline execution, clusters the sink pool, and graduates
  # any candidate that reappears across response_taxonomy_consensus_runs consecutive runs
  # into a real scenario -- zero human step. Off by default; flip to true only for the
  # explicit, separately-gated real run.
  response_taxonomy_auto_pass_enabled: false

  # Consecutive pipeline runs a candidate must reappear in (via Jaccard overlap of its
  # member pairs, not embedding similarity -- Postgres never stores vectors in this
  # codebase) before it graduates. Absorbs the documented UMAP+HDBSCAN run-to-run
  # instability (241->403->398->404 milestones for one identical corpus) by requiring
  # cross-run agreement instead of acting on a single run's clustering.
  #
  # PRE-REGISTERED STARTING POINT, not a fitted value -- there is no real run history to
  # calibrate against yet, same discipline response_taxonomy_purity_gate was held to.
  response_taxonomy_consensus_runs: 3

  # Jaccard overlap of member_pair_ids that counts as "the same candidate reappeared"
  # across two runs.
  #
  # PRE-REGISTERED STARTING POINT, not a fitted value, same discipline as the two keys
  # above.
  response_taxonomy_candidate_match_overlap: 0.5
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_tuning.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/ -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add Brain/tuning.yaml Brain/shared/tuning.py Brain/tests/test_tuning.py
git commit -m "Add response_taxonomy auto-pass tuning keys (disabled by default)"
```

---

### Task 3: `response_taxonomy_candidates` table migration

**Files:**

- Modify: `Brain/db/schema.sql`

No dedicated test — this file has no precedent for testing DDL directly; Task 6's mocked
tests exercise the SQL the module sends against this shape, and `db/init_db.py` running
clean against a scratch database (not attempted here — no real DB touched in this plan) would
be the real-world check, deferred to the "run it for real" session.

- [ ] **Step 1: Add the table**

In `Brain/db/schema.sql`, add after the `rubrics` table (before the Layer D section), with a
comment explaining the two pair-id columns:

```sql
-- Response-taxonomy auto-pass (added 2026-08-07): tracks candidate "homeless topic" clusters
-- across pipeline runs so a genuinely recurring gap in the CLIENT-clause-only taxonomy can be
-- graduated into a real scenario automatically, once it survives response_taxonomy_
-- consensus_runs consecutive runs. See docs/superpowers/specs/2026-08-07-response-taxonomy-
-- auto-pass-design.md.
--   member_pair_ids  latest run's raw cluster snapshot -- kept for observability/debugging.
--   stable_pair_ids  running intersection of every member_pair_ids snapshot seen since
--                    first_seen_run_id. THIS is what gets graduated, not member_pair_ids --
--                    a pair that only appeared in one noisy run drops out automatically
--                    instead of riding along on the latest snapshot alone.
--   status           tracking | graduated | discarded
CREATE TABLE IF NOT EXISTS response_taxonomy_candidates (
    candidate_id            SERIAL PRIMARY KEY,
    label                   TEXT NOT NULL,
    description             TEXT NOT NULL,
    member_pair_ids         INTEGER[] NOT NULL,
    stable_pair_ids         INTEGER[] NOT NULL,
    consensus_count         INTEGER NOT NULL DEFAULT 1,
    first_seen_run_id       TEXT NOT NULL,
    last_seen_run_id        TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'tracking',
    graduated_scenario_key  TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- init_db.py only creates missing tables, it never alters existing ones.
ALTER TABLE response_taxonomy_candidates ADD COLUMN IF NOT EXISTS stable_pair_ids INTEGER[] NOT NULL DEFAULT '{}';
```

- [ ] **Step 2: Sanity-check the file still parses as valid SQL syntax**

Run: `cd Brain && ..\.venv\Scripts\python -c "import sqlparse; sqlparse.parse(open('db/schema.sql', encoding='utf-8-sig').read())" 2>nul || echo "sqlparse not installed, skip"`

(Best-effort only — if `sqlparse` isn't installed, skip; the real validation is `init_db.py`
against a live database in the later "run it for real" session, out of scope here.)

- [ ] **Step 3: Commit**

```bash
git add Brain/db/schema.sql
git commit -m "Add response_taxonomy_candidates table migration"
```

---

### Task 4: Extract `Brain/shared/response_taxonomy.py`

**Files:**

- Create: `Brain/shared/response_taxonomy.py`
- Modify: `Brain/dry_run_response_taxonomy.py`
- Create: `Brain/tests/test_response_taxonomy.py`

**Interfaces:**

- Produces: `load_all_pairs(conn)`, `cluster_corpus(pairs, tuning, override)`,
  `scenario_sides(scenario_map)`, `build_records(...)`, `render_cluster(r)`,
  `adjudicate_clusters(records, config)` — all lifted verbatim (renamed to drop the leading
  underscore, since they are now a public shared module) from
  `dry_run_response_taxonomy.py`. Consumed by Task 7's `response_taxonomy_auto_pass.py` and
  by the updated `dry_run_response_taxonomy.py`.

- [ ] **Step 1: Write the failing test for the one genuinely pure piece**

`build_records` is the only one of these functions that's pure enough to unit-test without a
DB/Gemma/real embeddings (same reasoning `test_layer_c_clause_pool.py` used for
`build_clause_pool`) — it takes already-computed `vecs`/`labels` and hand-built
`scenario_map`. Create `Brain/tests/test_response_taxonomy.py`:

```python
"""build_records is response_taxonomy.py's one purely-testable piece -- everything else in
the module touches the DB, Gemma, or the real embedding model. Hand-built vecs/labels/
scenario_map, no DB, no Gemma, no real embeddings -- mirrors test_layer_c_clause_pool.py's
style for the analogous build_clause_pool extraction.
"""
import numpy as np

from shared import response_taxonomy as rt


def _pair(pair_id, scenario_key, call_filename="call1.txt"):
    return {
        "pair_id": pair_id, "trigger_text": "t", "response_text": "r",
        "scenario_key": scenario_key, "call_filename": call_filename,
    }


def _scenario(key, coachable, description="desc"):
    return {"scenario_key": key, "business_description": description, "keyphrases": [],
            "is_coachable": coachable}


class TestBuildRecords:
    def test_one_cluster_one_record(self):
        pairs = [_pair(1, "sink_a"), _pair(2, "sink_a")]
        vecs = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
        labels = [0, 0]
        scenario_map = {"sink_a": _scenario("sink_a", False),
                         "coachable_a": _scenario("coachable_a", True)}
        records = rt.build_records(pairs, vecs, labels, scenario_map, total_calls=10,
                                    purity_gate=0.90, seed=0)
        assert len(records) == 1
        assert records[0]["member_pair_ids"] == [1, 2]
        assert records[0]["nearest_coachable"] == "coachable_a"

    def test_noise_label_minus_one_is_excluded(self):
        pairs = [_pair(1, "sink_a"), _pair(2, "sink_a")]
        vecs = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
        labels = [-1, 0]
        scenario_map = {"sink_a": _scenario("sink_a", False)}
        records = rt.build_records(pairs, vecs, labels, scenario_map, total_calls=10,
                                    purity_gate=0.90, seed=0)
        assert len(records) == 1
        assert records[0]["member_pair_ids"] == [2]

    def test_purity_gate_skips_when_one_coachable_scenario_dominates(self):
        pairs = [_pair(i, "coachable_a") for i in range(9)] + [_pair(9, "coachable_b")]
        vecs = np.ones((10, 2), dtype=np.float32)
        labels = [0] * 10
        scenario_map = {"coachable_a": _scenario("coachable_a", True),
                         "coachable_b": _scenario("coachable_b", True)}
        records = rt.build_records(pairs, vecs, labels, scenario_map, total_calls=10,
                                    purity_gate=0.90, seed=0)
        assert records[0]["purity_gated"] is True

    def test_distinct_calls_counts_unique_call_filenames(self):
        pairs = [_pair(1, "sink_a", "call1.txt"), _pair(2, "sink_a", "call1.txt"),
                  _pair(3, "sink_a", "call2.txt")]
        vecs = np.ones((3, 2), dtype=np.float32)
        labels = [0, 0, 0]
        scenario_map = {"sink_a": _scenario("sink_a", False)}
        records = rt.build_records(pairs, vecs, labels, scenario_map, total_calls=10,
                                    purity_gate=0.90, seed=0)
        assert records[0]["distinct_calls"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_response_taxonomy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.response_taxonomy'`.

- [ ] **Step 3: Create the module**

Create `Brain/shared/response_taxonomy.py` by moving `_load_all_pairs`, `_cluster_corpus`,
`_scenario_sides`, `_build_records`, `_render_cluster`, `_adjudicate` out of
`dry_run_response_taxonomy.py` verbatim, dropping the leading underscore from each name and
updating their internal cross-calls to match (e.g. `_build_records` calling
`_scenario_sides` becomes `build_records` calling `scenario_sides`). Keep every docstring and
the module-level constants (`_BATCH_SIZE`, `_GEMMA_CALL_DELAY`, `_SAMPLES_PER_CLUSTER`,
`_SAMPLE_CHARS`) that these functions reference. Add a short module docstring:

```python
"""Shared response-clustering machinery: cluster every kb_pairs response by embedding
similarity, judge each cluster's current scenario_key composition, and adjudicate survivors
via the three-way PROMPT_SINK_POOL_TRIAGE verdict.

Extracted from dry_run_response_taxonomy.py (2026-08-07) so the dry-run script and the
permanent response_taxonomy_auto_pass.py module share one implementation instead of
duplicating it -- same precedent as v2/layer_c.py::build_clause_pool's extraction during the
sink-pool diagnostic work.
"""
```

- [ ] **Step 4: Update `dry_run_response_taxonomy.py` to import from the new module**

Replace its own function definitions with:

```python
from shared.response_taxonomy import (
    adjudicate_clusters, build_records, cluster_corpus, load_all_pairs,
)
```

and update every call site in `main()`/`_report()` (`_load_all_pairs` → `load_all_pairs`,
`_cluster_corpus` → `cluster_corpus`, `_build_records` → `build_records`, `_adjudicate` →
`adjudicate_clusters`). `_report()` itself stays in the script (CLI-output formatting, not
shared logic). Remove the now-dead `_scenario_sides`/`_render_cluster` imports if unused
directly (they're called internally by `build_records`/`adjudicate_clusters` now, not by the
script).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_response_taxonomy.py -v`
Expected: PASS, 4/4.

- [ ] **Step 6: Sanity-check both files still import and parse cleanly**

Run:
```bash
cd Brain
..\.venv\Scripts\python -c "import ast; ast.parse(open('shared/response_taxonomy.py', encoding='utf-8').read())"
..\.venv\Scripts\python -c "import ast; ast.parse(open('dry_run_response_taxonomy.py', encoding='utf-8').read())"
```
Expected: no output, exit code 0 for both.

- [ ] **Step 7: Run the full suite to confirm no regressions**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/ -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add Brain/shared/response_taxonomy.py Brain/dry_run_response_taxonomy.py Brain/tests/test_response_taxonomy.py
git commit -m "Extract shared/response_taxonomy.py from dry_run_response_taxonomy.py"
```

---

### Task 5: `Brain/response_taxonomy_auto_pass.py` — candidate matching/tracking

Split into two tasks (this one: matching/tracking; Task 6: graduation) because they are
independently testable and graduation depends on matching already being correct.

**Files:**

- Create: `Brain/response_taxonomy_auto_pass.py`
- Create: `Brain/tests/test_response_taxonomy_auto_pass.py`

**Interfaces:**

- Produces: `_jaccard(a: set, b: set) -> float`, `_match_tracking_row(new_pair_ids, tracking_rows, overlap_threshold) -> dict | None`, `_upsert_tracking_row(conn, run_id, candidate, matched_row, consensus_runs) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `Brain/tests/test_response_taxonomy_auto_pass.py`:

```python
"""response_taxonomy_auto_pass.py's matching/tracking/graduation logic, verified against a
mocked connection/cursor -- no real database, matching test_graduate_sink_topics.py's
existing discipline.
"""
from unittest.mock import MagicMock

import pytest

import response_taxonomy_auto_pass as rtap


class TestJaccard:
    def test_identical_sets_is_one(self):
        assert rtap._jaccard({1, 2, 3}, {1, 2, 3}) == 1.0

    def test_disjoint_sets_is_zero(self):
        assert rtap._jaccard({1, 2}, {3, 4}) == 0.0

    def test_partial_overlap(self):
        assert rtap._jaccard({1, 2, 3}, {2, 3, 4}) == pytest.approx(2 / 4)

    def test_both_empty_is_zero_not_a_divide_by_zero(self):
        assert rtap._jaccard(set(), set()) == 0.0


def _row(candidate_id, member_pair_ids, stable_pair_ids=None, last_seen="run_a", consensus=1):
    return {
        "candidate_id": candidate_id,
        "member_pair_ids": member_pair_ids,
        "stable_pair_ids": stable_pair_ids if stable_pair_ids is not None else list(member_pair_ids),
        "last_seen_run_id": last_seen,
        "consensus_count": consensus,
        "status": "tracking",
    }


class TestMatchTrackingRow:
    def test_no_rows_returns_none(self):
        assert rtap._match_tracking_row({1, 2, 3}, [], overlap_threshold=0.5) is None

    def test_matches_row_above_threshold(self):
        rows = [_row(1, [1, 2, 3, 4])]
        assert rtap._match_tracking_row({2, 3, 4, 5}, rows, overlap_threshold=0.5) is rows[0]

    def test_no_match_below_threshold(self):
        rows = [_row(1, [1, 2, 3, 4, 5, 6, 7, 8])]
        assert rtap._match_tracking_row({1, 9, 10, 11}, rows, overlap_threshold=0.5) is None

    def test_ambiguous_multi_match_picks_the_single_best_row(self):
        # Both clear the 0.5 floor; row 2 overlaps more (Decision 1 in the design spec).
        rows = [_row(1, [1, 2, 3, 4]), _row(2, [1, 2, 3, 4, 5])]
        new_ids = {1, 2, 3, 4, 5}
        best = rtap._match_tracking_row(new_ids, rows, overlap_threshold=0.5)
        assert best["candidate_id"] == 2

    def test_exact_tie_breaks_toward_lower_candidate_id(self):
        rows = [_row(2, [1, 2, 3, 4]), _row(1, [1, 2, 3, 4])]
        best = rtap._match_tracking_row({1, 2, 3, 4}, rows, overlap_threshold=0.5)
        assert best["candidate_id"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_response_taxonomy_auto_pass.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'response_taxonomy_auto_pass'`.

- [ ] **Step 3: Implement `_jaccard` and `_match_tracking_row`**

Create `Brain/response_taxonomy_auto_pass.py`:

```python
#!/usr/bin/env python3
"""Permanent, automatic homeless-topic graduation pass. See
docs/superpowers/specs/2026-08-07-response-taxonomy-auto-pass-design.md.

Runs after every V2 pipeline execution (called from v2/pipeline.py, wrapped in try/except at
that call site so a bug here can never fail the overall run). Clusters the sink pool exactly
the way dry_run_response_taxonomy.py does (via shared/response_taxonomy.py), tracks candidates
across runs by pair-id Jaccard overlap (never embedding similarity -- this codebase's Postgres
never stores vectors), and graduates any candidate that survives
response_taxonomy_consensus_runs consecutive runs into a real scenario.

Entry point: run_auto_pass(config, conn, run_id).
"""
from __future__ import annotations
import json
import logging
import sys
import time
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

from config import Config
from shared import cluster_evidence, response_taxonomy, scenario_vectors, storage, topic_grouping
from shared.gemma import call_gemma
from shared.prompts import PROMPT_GRADUATE_SINK_TOPIC
from v2.layer_c import run_layer_c_v2

_LOG_PATH = Path(__file__).parent / "response_taxonomy_auto_pass.log"
_GEMMA_CALL_DELAY = 5
_NEAR_MISS_MARGIN = 0.05  # Decision 1: log (don't block) a second-best match within this band.

_logger = logging.getLogger("response_taxonomy_auto_pass")
if not _logger.handlers:
    handler = logging.FileHandler(_LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _match_tracking_row(new_pair_ids: set, tracking_rows: list[dict], overlap_threshold: float) -> dict | None:
    """Best-match a candidate's pair-id set against existing tracking rows.

    Decision 1 (design spec): ambiguous multi-match is resolved by always taking the
    single highest-Jaccard row, never merging two rows. A second-best match within
    _NEAR_MISS_MARGIN of the winner is logged for visibility, not blocked on. Ties break
    toward the lower candidate_id for determinism.
    """
    scored = [
        (_jaccard(new_pair_ids, set(row["member_pair_ids"])), row)
        for row in tracking_rows
    ]
    qualifying = [(score, row) for score, row in scored if score >= overlap_threshold]
    if not qualifying:
        return None
    qualifying.sort(key=lambda sr: (-sr[0], sr[1]["candidate_id"]))
    best_score, best_row = qualifying[0]
    if len(qualifying) > 1 and qualifying[1][0] >= best_score - _NEAR_MISS_MARGIN:
        _logger.warning(
            "candidate matched multiple tracking rows within %.2f of the best score "
            "(best=%s score=%.3f, runner_up=%s score=%.3f) -- took the best match only",
            _NEAR_MISS_MARGIN, best_row["candidate_id"], best_score,
            qualifying[1][1]["candidate_id"], qualifying[1][0],
        )
    return best_row
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_response_taxonomy_auto_pass.py -v`
Expected: PASS, 9/9 so far.

- [ ] **Step 5: Commit**

```bash
git add Brain/response_taxonomy_auto_pass.py Brain/tests/test_response_taxonomy_auto_pass.py
git commit -m "Add response_taxonomy_auto_pass.py Jaccard matching (Decision 1: best-match, not merge)"
```

---

### Task 6: `stable_pair_ids` intersection + tracking-row upsert

**Files:**

- Modify: `Brain/response_taxonomy_auto_pass.py`
- Modify: `Brain/tests/test_response_taxonomy_auto_pass.py`

**Interfaces:**

- Produces: `_load_tracking_rows(conn) -> list[dict]`, `_upsert_tracking_row(conn, run_id, new_pair_ids, matched_row, label, description) -> None`.

- [ ] **Step 1: Write the failing tests**

Add to `Brain/tests/test_response_taxonomy_auto_pass.py`:

```python
def _mock_conn_with_row(row=None):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [] if row is None else [row]
    return conn, cur


class TestUpsertTrackingRow:
    def test_no_match_inserts_new_row_seeding_stable_pair_ids(self):
        conn, cur = _mock_conn_with_row()
        rtap._upsert_tracking_row(conn, "run_1", {1, 2, 3}, None, "label", "desc")
        insert_call = cur.execute.call_args
        sql, params = insert_call.args
        assert "INSERT INTO response_taxonomy_candidates" in sql
        assert sorted(params[2]) == [1, 2, 3]   # member_pair_ids
        assert sorted(params[3]) == [1, 2, 3]   # stable_pair_ids seeded to the full set

    def test_match_intersects_stable_pair_ids_not_just_overwrites(self):
        conn, cur = _mock_conn_with_row()
        matched = _row(5, member_pair_ids=[2, 3, 4], stable_pair_ids=[1, 2, 3], last_seen="run_1")
        rtap._upsert_tracking_row(conn, "run_2", {2, 3, 4, 5}, matched, "label", "desc")
        update_call = cur.execute.call_args
        sql, params = update_call.args
        assert "UPDATE response_taxonomy_candidates" in sql
        # stable_pair_ids = {1,2,3} ∩ {2,3,4,5} = {2,3}
        assert sorted(params[1]) == [2, 3]
        assert params[-1] == 5  # candidate_id in WHERE clause

    def test_drift_across_three_runs_shrinks_to_the_stable_core(self):
        # Simulates the exact Decision 2 scenario from the design spec: run 1 {1,2,3},
        # run 2 matches with {2,3,4}, run 3 matches with {3,4,5} -- stable core ends at {3}.
        stable = {1, 2, 3}
        stable = stable & {2, 3, 4}
        stable = stable & {3, 4, 5}
        assert stable == {3}

    def test_idempotency_guard_same_run_id_does_not_double_increment(self):
        conn, cur = _mock_conn_with_row()
        matched = _row(5, member_pair_ids=[1, 2, 3], last_seen="run_1", consensus=2)
        rtap._upsert_tracking_row(conn, "run_1", {1, 2, 3}, matched, "label", "desc")
        cur.execute.assert_not_called()

    def test_stable_pair_ids_emptying_out_marks_discarded(self):
        conn, cur = _mock_conn_with_row()
        matched = _row(5, member_pair_ids=[2, 3], stable_pair_ids=[1, 2], last_seen="run_1")
        rtap._upsert_tracking_row(conn, "run_2", {3, 4}, matched, "label", "desc")
        sql, params = cur.execute.call_args.args
        assert "status" in sql and "discarded" in params
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_response_taxonomy_auto_pass.py::TestUpsertTrackingRow -v`
Expected: FAIL — `AttributeError`.

- [ ] **Step 3: Implement `_load_tracking_rows` and `_upsert_tracking_row`**

Add to `Brain/response_taxonomy_auto_pass.py`:

```python
def _load_tracking_rows(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT candidate_id, member_pair_ids, stable_pair_ids, consensus_count,
                   first_seen_run_id, last_seen_run_id, status
            FROM response_taxonomy_candidates
            WHERE status = 'tracking'
        """)
        rows = cur.fetchall()
    return [
        {"candidate_id": r[0], "member_pair_ids": r[1], "stable_pair_ids": r[2],
         "consensus_count": r[3], "first_seen_run_id": r[4], "last_seen_run_id": r[5],
         "status": r[6]}
        for r in rows
    ]


def _upsert_tracking_row(
    conn, run_id: str, new_pair_ids: set, matched_row: dict | None, label: str, description: str,
) -> None:
    """Insert a brand-new tracking row, or advance an existing one.

    Decision 2 (design spec): stable_pair_ids is the running intersection across every run a
    candidate has been seen in -- graduation reads from this, not the latest raw snapshot, so
    a pair that only appeared once drops out instead of riding along forever. If the
    intersection empties out, the candidate has already provably lost coherence and is
    discarded immediately rather than waiting for consensus_count to reach the threshold.
    """
    if matched_row is None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO response_taxonomy_candidates
                  (label, description, member_pair_ids, stable_pair_ids, consensus_count,
                   first_seen_run_id, last_seen_run_id, status)
                VALUES (%s, %s, %s, %s, 1, %s, %s, 'tracking')
                """,
                (label, description, sorted(new_pair_ids), sorted(new_pair_ids), run_id, run_id),
            )
        conn.commit()
        return

    if matched_row["last_seen_run_id"] == run_id:
        return  # idempotency guard: a no-op re-run of the same transcript set

    new_stable = set(matched_row["stable_pair_ids"]) & new_pair_ids
    with conn.cursor() as cur:
        if not new_stable:
            cur.execute(
                """
                UPDATE response_taxonomy_candidates
                   SET member_pair_ids = %s, stable_pair_ids = %s, status = %s,
                       last_seen_run_id = %s, updated_at = now()
                 WHERE candidate_id = %s
                """,
                (sorted(new_pair_ids), [], "discarded", run_id, matched_row["candidate_id"]),
            )
            _logger.info(
                "candidate_id=%s discarded: stable_pair_ids emptied out (drift)",
                matched_row["candidate_id"],
            )
        else:
            cur.execute(
                """
                UPDATE response_taxonomy_candidates
                   SET member_pair_ids = %s, stable_pair_ids = %s,
                       consensus_count = consensus_count + 1, last_seen_run_id = %s,
                       updated_at = now()
                 WHERE candidate_id = %s
                """,
                (sorted(new_pair_ids), sorted(new_stable), run_id, matched_row["candidate_id"]),
            )
    conn.commit()
```

Note the test `test_stable_pair_ids_emptying_out_marks_discarded` checks
`"status" in sql and "discarded" in params` — matches the discard branch's SQL/params shape
above (params is a tuple ending in `matched_row["candidate_id"]`, with `"discarded"` present
earlier in the tuple).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_response_taxonomy_auto_pass.py -v`
Expected: PASS, all so far.

- [ ] **Step 5: Commit**

```bash
git add Brain/response_taxonomy_auto_pass.py Brain/tests/test_response_taxonomy_auto_pass.py
git commit -m "Add stable_pair_ids intersection tracking (Decision 2: drift-resistant candidate identity)"
```

---

### Task 7: Graduation path — reconciliation gate, `primary_topic_key` fix, transactional write

**Files:**

- Modify: `Brain/response_taxonomy_auto_pass.py`
- Modify: `Brain/tests/test_response_taxonomy_auto_pass.py`
- Modify: `Brain/graduate_sink_topics.py` (retroactive `primary_topic_key` fix — see Step 6)
- Modify: `Brain/tests/test_graduate_sink_topics.py`

**Interfaces:**

- Produces: `_resolve_primary_topic_key(conn, config, row) -> str`, `_attempt_graduation(conn, config, run_id, tracking_row) -> str | None`.
- Consumes: `cluster_evidence.passes_reconciliation_gate` (existing), `topic_grouping.match_existing_primary_topic` (Task 1), `storage.get_primary_topics`/`get_scenarios`/`upsert_scenario`/`upsert_primary_topic` (existing), `PROMPT_GRADUATE_SINK_TOPIC` (existing), `run_layer_c_v2` (existing).

- [ ] **Step 1: Write the failing tests for `_resolve_primary_topic_key`**

Add to `Brain/tests/test_response_taxonomy_auto_pass.py`:

```python
class TestResolvePrimaryTopicKey:
    def test_close_match_reuses_existing_key(self, monkeypatch):
        conn = MagicMock()
        monkeypatch.setattr(rtap.storage, "get_primary_topics", lambda c: [
            {"primary_topic_key": "pt_existing", "label": "L", "description": "D", "keyphrases": []},
        ])
        monkeypatch.setattr(rtap.scenario_vectors, "build_primary_topic_vecs",
                             lambda m: (["pt_existing"], [[1.0, 0.0]]))
        monkeypatch.setattr(rtap.scenario_vectors, "scenario_vec", lambda row: [1.0, 0.0])
        monkeypatch.setattr(rtap.topic_grouping, "match_existing_primary_topic",
                             lambda centroid, keys, vecs, threshold: "pt_existing")
        key = rtap._resolve_primary_topic_key(
            conn, merge_cosine_threshold=0.85,
            row={"business_description": "d", "keyphrases": [], "scenario_key": "new_s",
                 "support_calls": 5, "call_coverage": 0.1},
        )
        assert key == "pt_existing"
        conn.cursor.assert_not_called()  # no new primary_topics row written

    def test_no_match_creates_singleton_primary_topic(self, monkeypatch):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        monkeypatch.setattr(rtap.storage, "get_primary_topics", lambda c: [])
        monkeypatch.setattr(rtap.scenario_vectors, "build_primary_topic_vecs", lambda m: ([], []))
        monkeypatch.setattr(rtap.scenario_vectors, "scenario_vec", lambda row: [1.0, 0.0])
        monkeypatch.setattr(rtap.storage, "upsert_primary_topic", lambda c, topic: 1)
        row = {"business_description": "d", "keyphrases": ["kp"], "scenario_key": "new_s",
               "support_calls": 5, "call_coverage": 0.1}
        key = rtap._resolve_primary_topic_key(conn, merge_cosine_threshold=0.85, row=row)
        assert key == "new_s"  # singleton key derived from the scenario_key
        upsert_calls = rtap.storage.upsert_primary_topic.__self__  # sanity: it was patched
```

(Simplify the second test's final assertion to just checking the return value if
`upsert_primary_topic` patched as a plain function makes `__self__` introspection awkward —
use `monkeypatch.setattr` with a `MagicMock()` instead and assert `.called` if that reads
cleaner during implementation; the exact assertion mechanics are an implementation detail,
the behavior being tested is not.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_response_taxonomy_auto_pass.py::TestResolvePrimaryTopicKey -v`
Expected: FAIL — `AttributeError`.

- [ ] **Step 3: Implement `_resolve_primary_topic_key`**

Add to `Brain/response_taxonomy_auto_pass.py`:

```python
def _resolve_primary_topic_key(conn, merge_cosine_threshold: float, row: dict) -> str:
    """Fixes the primary_topic_key=None orphaning bug (graduate_sink_topics.py:145):
    primary_topics is only ever populated once, during Layer A's main grouping pass -- a
    scenario graduated afterward has no later grouping step to go through, so this resolves
    a real key instead of leaving the FK null forever.

    Reuses merge_cosine_threshold (the tight, subtopic-dedup threshold), not the looser
    primary_topic_merge_threshold used for INITIAL macro-grouping -- primary_topics rows are
    already tight-cohesion groups by the time they're stored (post tighten_coachable_groups),
    so the tight threshold is the comparable one, same reasoning
    passes_reconciliation_gate already applies to reusing an existing threshold rather than
    inventing a new one.
    """
    existing = storage.get_primary_topics(conn)
    by_key = {t["primary_topic_key"]: t for t in existing}
    keys, vecs = scenario_vectors.build_primary_topic_vecs(by_key)
    new_vec = scenario_vectors.scenario_vec(row)

    match = topic_grouping.match_existing_primary_topic(new_vec, keys, vecs, merge_cosine_threshold)
    if match is not None:
        return match

    storage.upsert_primary_topic(conn, {
        "primary_topic_key": row["scenario_key"],
        "label": row["scenario_key"].replace("_", " ").title(),
        "description": row["business_description"],
        "keyphrases": row["keyphrases"],
        "grouping_method": "graduated_singleton",
        "support_calls": row["support_calls"],
        "support_subtopics": 1,
        "call_coverage": row["call_coverage"],
    })
    return row["scenario_key"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_response_taxonomy_auto_pass.py -v`
Expected: PASS, all so far.

- [ ] **Step 5: Write failing tests for `_attempt_graduation`**

Add to `Brain/tests/test_response_taxonomy_auto_pass.py`:

```python
def _consensus_row(pair_ids, consensus=3):
    return _row(7, member_pair_ids=pair_ids, stable_pair_ids=pair_ids, consensus=consensus)


class TestAttemptGraduation:
    def test_all_pairs_still_sink_bound_proceeds_to_write(self, monkeypatch):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [(1, True), (2, True), (3, True)]  # all currently sink-bound
        monkeypatch.setattr(rtap, "_support_stats_for_pairs", lambda c, ids: (2, len(ids), 0.2))
        monkeypatch.setattr(rtap.cluster_evidence, "passes_reconciliation_gate", lambda sim, thr: True)
        monkeypatch.setattr(rtap, "_generate_metadata", lambda *a, **k: {
            "scenario_key": "new_scenario", "business_description": "d",
            "keyphrases": [], "soft_skills": [], "bloom_level": "apply",
        })
        monkeypatch.setattr(rtap, "_resolve_primary_topic_key", lambda *a, **k: "pt_key")
        monkeypatch.setattr(rtap.storage, "upsert_scenario", lambda c, row: 42)
        cur.rowcount = 3
        monkeypatch.setattr(rtap, "run_layer_c_v2", lambda *a, **k: None)

        result = rtap._attempt_graduation(
            conn, config=None, run_id="run_1",
            tracking_row=_consensus_row([1, 2, 3]),
            nearest_coachable_sim=0.70, merge_cosine_threshold=0.85, proposed_label="l",
            proposed_description="d", reason="r", samples=[],
        )
        assert result == "new_scenario"

    def test_pairs_already_rehomed_are_excluded_from_write_set(self, monkeypatch):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        # pair 2 is now homed to a coachable scenario -- must be dropped from the write set.
        cur.fetchall.return_value = [(1, True), (2, False), (3, True)]
        captured = {}

        def _fake_support_stats(c, ids):
            captured["ids"] = ids
            return (2, len(ids), 0.2)

        monkeypatch.setattr(rtap, "_support_stats_for_pairs", _fake_support_stats)
        monkeypatch.setattr(rtap.cluster_evidence, "passes_reconciliation_gate", lambda sim, thr: True)
        monkeypatch.setattr(rtap, "_generate_metadata", lambda *a, **k: {
            "scenario_key": "new_scenario", "business_description": "d",
            "keyphrases": [], "soft_skills": [], "bloom_level": "apply",
        })
        monkeypatch.setattr(rtap, "_resolve_primary_topic_key", lambda *a, **k: "pt_key")
        monkeypatch.setattr(rtap.storage, "upsert_scenario", lambda c, row: 42)
        cur.rowcount = 2
        monkeypatch.setattr(rtap, "run_layer_c_v2", lambda *a, **k: None)

        rtap._attempt_graduation(
            conn, config=None, run_id="run_1",
            tracking_row=_consensus_row([1, 2, 3]),
            nearest_coachable_sim=0.70, merge_cosine_threshold=0.85, proposed_label="l",
            proposed_description="d", reason="r", samples=[],
        )
        assert sorted(captured["ids"]) == [1, 3]

    def test_zero_surviving_pairs_discards_without_writing(self, monkeypatch):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [(1, False), (2, False)]  # all already re-homed
        result = rtap._attempt_graduation(
            conn, config=None, run_id="run_1",
            tracking_row=_consensus_row([1, 2]),
            nearest_coachable_sim=0.70, merge_cosine_threshold=0.85, proposed_label="l",
            proposed_description="d", reason="r", samples=[],
        )
        assert result is None
        update_sql, update_params = cur.execute.call_args.args
        assert "discarded" in update_params

    def test_reconciliation_gate_failure_discards_without_writing(self, monkeypatch):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [(1, True), (2, True)]
        monkeypatch.setattr(rtap, "_support_stats_for_pairs", lambda c, ids: (2, len(ids), 0.2))
        monkeypatch.setattr(rtap.cluster_evidence, "passes_reconciliation_gate", lambda sim, thr: False)
        result = rtap._attempt_graduation(
            conn, config=None, run_id="run_1",
            tracking_row=_consensus_row([1, 2]),
            nearest_coachable_sim=0.90, merge_cosine_threshold=0.85, proposed_label="l",
            proposed_description="d", reason="r", samples=[],
        )
        assert result is None
        update_sql, update_params = cur.execute.call_args.args
        assert "discarded" in update_params

    def test_write_failure_rowcount_mismatch_rolls_back(self, monkeypatch):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [(1, True), (2, True)]
        monkeypatch.setattr(rtap, "_support_stats_for_pairs", lambda c, ids: (2, len(ids), 0.2))
        monkeypatch.setattr(rtap.cluster_evidence, "passes_reconciliation_gate", lambda sim, thr: True)
        monkeypatch.setattr(rtap, "_generate_metadata", lambda *a, **k: {
            "scenario_key": "new_scenario", "business_description": "d",
            "keyphrases": [], "soft_skills": [], "bloom_level": "apply",
        })
        monkeypatch.setattr(rtap, "_resolve_primary_topic_key", lambda *a, **k: "pt_key")
        monkeypatch.setattr(rtap.storage, "upsert_scenario", lambda c, row: 42)
        cur.rowcount = 1  # expected 2, got 1 -- must roll back, not commit-then-raise
        monkeypatch.setattr(rtap, "run_layer_c_v2", lambda *a, **k: None)

        with pytest.raises(RuntimeError, match="rerouted 1"):
            rtap._attempt_graduation(
                conn, config=None, run_id="run_1",
                tracking_row=_consensus_row([1, 2]),
                nearest_coachable_sim=0.70, merge_cosine_threshold=0.85, proposed_label="l",
                proposed_description="d", reason="r", samples=[],
            )
        conn.rollback.assert_called()
        conn.commit.assert_not_called()
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_response_taxonomy_auto_pass.py::TestAttemptGraduation -v`
Expected: FAIL — `AttributeError`.

- [ ] **Step 7: Implement `_support_stats_for_pairs`, `_generate_metadata`, `_attempt_graduation`**

Add to `Brain/response_taxonomy_auto_pass.py` (the first two mirror
`graduate_sink_topics.py`'s existing functions of the same name/shape — reused conceptually,
not imported, since this module must not depend on a script-shaped sibling):

```python
def _support_stats_for_pairs(conn, pair_ids: list[int]) -> tuple[int, int, float]:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM calls")
        total_calls = int(cur.fetchone()[0])
        cur.execute(
            "SELECT COUNT(DISTINCT call_id) FROM kb_pairs WHERE pair_id = ANY(%s)",
            (pair_ids,),
        )
        distinct_calls = int(cur.fetchone()[0])
    return distinct_calls, len(pair_ids), distinct_calls / max(total_calls, 1)


def _generate_metadata(config: Config, proposed_label, proposed_description, reason, samples) -> dict:
    samples_block = "\n".join(
        f"  - CLIENT: {s['trigger_text'][:150]!r}\n    EXPERT: {s['response_text'][:400]!r}"
        for s in samples
    )
    prompt = PROMPT_GRADUATE_SINK_TOPIC.format(
        proposed_label=proposed_label, proposed_description=proposed_description,
        reason=reason, samples_block=samples_block,
    )
    result = call_gemma(prompt, config.gemma_api_keys)
    time.sleep(_GEMMA_CALL_DELAY)
    return result


def _discard(conn, candidate_id: int, reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE response_taxonomy_candidates SET status = %s, updated_at = now() WHERE candidate_id = %s",
            ("discarded", candidate_id),
        )
    conn.commit()
    _logger.info("candidate_id=%s discarded: %s", candidate_id, reason)


def _attempt_graduation(
    conn, config: Config, run_id: str, tracking_row: dict, nearest_coachable_sim: float,
    merge_cosine_threshold: float, proposed_label: str, proposed_description: str,
    reason: str, samples: list[dict],
) -> str | None:
    candidate_id = tracking_row["candidate_id"]
    stable_ids = list(tracking_row["stable_pair_ids"])

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT kb.pair_id, s.is_coachable
            FROM kb_pairs kb JOIN scenarios s ON s.scenario_id = kb.scenario_id
            WHERE kb.pair_id = ANY(%s)
            """,
            (stable_ids,),
        )
        rows = cur.fetchall()
    surviving = [pair_id for pair_id, is_coachable in rows if not is_coachable]

    if not surviving:
        _discard(conn, candidate_id, "zero pairs survived is_coachable re-check")
        return None

    if not cluster_evidence.passes_reconciliation_gate(nearest_coachable_sim, merge_cosine_threshold):
        _discard(conn, candidate_id, f"failed reconciliation gate ({nearest_coachable_sim:.3f})")
        return None

    meta = _generate_metadata(config, proposed_label, proposed_description, reason, samples)
    distinct_calls, n_pairs, call_coverage = _support_stats_for_pairs(conn, surviving)

    row = {
        "scenario_key": meta["scenario_key"],
        "business_description": meta["business_description"],
        "primary_topic": proposed_label,
        "keyphrases": meta.get("keyphrases") or [],
        "soft_skills": meta.get("soft_skills") or [],
        "bloom_level": meta.get("bloom_level") or "understand",
        "is_coachable": True,
        "cluster_kind": "scenario",
        "support_calls": distinct_calls,
        "support_clauses": n_pairs,
        "call_coverage": call_coverage,
        "triage_verdict": "graduated_from_sink_pool_auto_pass",
        "adjudication_reason": reason,
    }
    row["primary_topic_key"] = _resolve_primary_topic_key(conn, merge_cosine_threshold, row)

    try:
        scenario_id = storage.upsert_scenario(conn, row)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_pairs
                   SET scenario_key = %s, scenario_id = %s,
                       scenario_keys = array_append(scenario_keys, %s)
                 WHERE pair_id = ANY(%s)
                """,
                (row["scenario_key"], scenario_id, row["scenario_key"], surviving),
            )
            rerouted = cur.rowcount
        if rerouted != len(surviving):
            raise RuntimeError(
                f"candidate_id={candidate_id} rerouted {rerouted} pair(s), expected "
                f"exactly {len(surviving)} -- rolling back before Layer C ever sees a "
                f"possibly-wrong pair set."
            )
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE response_taxonomy_candidates
                   SET status = 'graduated', graduated_scenario_key = %s, updated_at = now()
                 WHERE candidate_id = %s
                """,
                (row["scenario_key"], candidate_id),
            )
    except Exception:
        conn.rollback()
        raise
    conn.commit()

    _logger.info(
        "candidate_id=%s graduated as scenario_key=%s (%s pairs, %s calls, %.1f%% coverage)",
        candidate_id, row["scenario_key"], n_pairs, distinct_calls, call_coverage * 100,
    )
    all_scenarios = {s["scenario_key"]: s for s in storage.get_scenarios(conn)}
    run_layer_c_v2({row["scenario_key"]: all_scenarios[row["scenario_key"]]}, config, conn, run_id="")
    return row["scenario_key"]
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_response_taxonomy_auto_pass.py -v`
Expected: PASS, all so far.

- [ ] **Step 9: Retroactively fix `graduate_sink_topics.py`'s own `primary_topic_key = None`**

In `Brain/graduate_sink_topics.py`, import the new helper and replace the hardcoded `None`:

```python
from shared import cluster_evidence, storage, topic_grouping  # add topic_grouping
from shared import scenario_vectors  # new import
```

In `_graduate_one`, after computing `distinct_calls, n_pairs, call_coverage` and before
building `row` for the real (non-dry-run) write, resolve the key the same way:

```python
    row = {
        "scenario_key": meta["scenario_key"],
        "business_description": meta["business_description"],
        "primary_topic": verdict["proposed_label"],
        "keyphrases": meta.get("keyphrases") or [],
        "soft_skills": meta.get("soft_skills") or [],
        "bloom_level": meta.get("bloom_level") or "understand",
        "is_coachable": True,
        "cluster_kind": "scenario",
        "support_calls": distinct_calls,
        "support_clauses": n_pairs,
        "call_coverage": call_coverage,
        "triage_verdict": "graduated_from_sink_pool",
        "adjudication_reason": verdict["reason"],
    }
    tuning_a = load_tuning().layer_a
    existing = storage.get_primary_topics(conn)
    by_key = {t["primary_topic_key"]: t for t in existing}
    keys, vecs = scenario_vectors.build_primary_topic_vecs(by_key)
    match = topic_grouping.match_existing_primary_topic(
        scenario_vectors.scenario_vec(row), keys, vecs, tuning_a.merge_cosine_threshold,
    )
    if match is not None:
        row["primary_topic_key"] = match
    else:
        storage.upsert_primary_topic(conn, {
            "primary_topic_key": row["scenario_key"],
            "label": row["scenario_key"].replace("_", " ").title(),
            "description": row["business_description"],
            "keyphrases": row["keyphrases"],
            "grouping_method": "graduated_singleton",
            "support_calls": distinct_calls,
            "support_subtopics": 1,
            "call_coverage": call_coverage,
        })
        row["primary_topic_key"] = row["scenario_key"]
```

(`load_tuning` is already imported at module level in `graduate_sink_topics.py`.)

- [ ] **Step 10: Update `test_graduate_sink_topics.py` for the new behavior**

`test_writes_expected_insert_and_reroute_sql` and `test_raises_when_rerouted_count_does_not_match`
now also call `storage.get_primary_topics`/`scenario_vectors.build_primary_topic_vecs`/
`scenario_vectors.scenario_vec`/`topic_grouping.match_existing_primary_topic`. Add
`monkeypatch.setattr` calls mirroring Task 7's `_resolve_primary_topic_key` tests (patch
`gst.storage.get_primary_topics` to return `[]`, `gst.scenario_vectors.build_primary_topic_vecs`
to return `([], [])`, `gst.scenario_vectors.scenario_vec` to return `[1.0, 0.0]`) to the two
existing tests that reach the write path, so `_graduate_one` doesn't try to call the real
embedder. `test_dry_run_makes_no_writes` and the two skip-path tests are unaffected (they
return before reaching the new code).

- [ ] **Step 11: Run the full suite to confirm no regressions**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/ -v`
Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add Brain/response_taxonomy_auto_pass.py Brain/tests/test_response_taxonomy_auto_pass.py Brain/graduate_sink_topics.py Brain/tests/test_graduate_sink_topics.py
git commit -m "Add graduation path with primary_topic_key fix (applies to both auto-pass and graduate_sink_topics.py)"
```

---

### Task 8: `run_auto_pass` entry point — clustering, filtering, disabled-flag no-op

**Files:**

- Modify: `Brain/response_taxonomy_auto_pass.py`
- Modify: `Brain/tests/test_response_taxonomy_auto_pass.py`

**Interfaces:**

- Produces: `run_auto_pass(config: Config, conn, run_id: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Add to `Brain/tests/test_response_taxonomy_auto_pass.py`:

```python
class _FakeLayerATuning:
    response_taxonomy_auto_pass_enabled = False
    response_taxonomy_consensus_runs = 3
    response_taxonomy_candidate_match_overlap = 0.5
    response_taxonomy_purity_gate = 0.90
    merge_cosine_threshold = 0.85


class _FakeTuning:
    layer_a = _FakeLayerATuning()
    layer_c = None


class TestRunAutoPass:
    def test_disabled_is_a_pure_noop(self, monkeypatch):
        monkeypatch.setattr(rtap, "load_tuning", lambda: _FakeTuning())
        conn = MagicMock()
        rtap.run_auto_pass(config=None, conn=conn, run_id="run_1")
        conn.cursor.assert_not_called()

    def test_exception_inside_does_not_propagate_when_caught_by_caller(self, monkeypatch):
        tuning = _FakeTuning()
        tuning.layer_a.response_taxonomy_auto_pass_enabled = True
        monkeypatch.setattr(rtap, "load_tuning", lambda: tuning)
        monkeypatch.setattr(rtap.response_taxonomy, "load_all_pairs",
                             lambda conn: (_ for _ in ()).throw(RuntimeError("boom")))
        conn = MagicMock()
        with pytest.raises(RuntimeError):
            rtap.run_auto_pass(config=None, conn=conn, run_id="run_1")
        # the design requires the CALL SITE (v2/pipeline.py) to catch this -- run_auto_pass
        # itself is allowed to raise; Task 9 verifies the call site swallows it.
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_response_taxonomy_auto_pass.py::TestRunAutoPass -v`
Expected: FAIL — `AttributeError: module 'response_taxonomy_auto_pass' has no attribute 'run_auto_pass'`.

- [ ] **Step 3: Implement `run_auto_pass`**

Add to `Brain/response_taxonomy_auto_pass.py` (import `load_tuning` at module level):

```python
from shared.tuning import load_tuning


def run_auto_pass(config: Config, conn, run_id: str) -> None:
    tuning = load_tuning()
    a = tuning.layer_a
    if not a.response_taxonomy_auto_pass_enabled:
        _logger.info("disabled -- skipping (run_id=%s)", run_id)
        return

    scenario_map = {r["scenario_key"]: r for r in storage.get_scenarios(conn)}
    pairs, total_calls = response_taxonomy.load_all_pairs(conn)
    if not pairs:
        _logger.info("no pairs available -- nothing to cluster (run_id=%s)", run_id)
        return

    vecs, labels, _mcs = response_taxonomy.cluster_corpus(pairs, tuning.layer_c, override=None)
    records = response_taxonomy.build_records(
        pairs, vecs, labels, scenario_map, total_calls, a.response_taxonomy_purity_gate, seed=0,
    )
    verdicts = response_taxonomy.adjudicate_clusters(records, config)

    new_candidates = [
        r for r in records
        if not r["purity_gated"] and verdicts.get(r["id"], {}).get("verdict") == "new_coachable_topic"
    ]
    _logger.info("run_id=%s: %d new_coachable_topic candidate(s) found", run_id, len(new_candidates))

    tracking_rows = _load_tracking_rows(conn)
    graduated = []
    for record in new_candidates:
        verdict = verdicts[record["id"]]
        new_pair_ids = set(record["member_pair_ids"])
        matched = _match_tracking_row(new_pair_ids, tracking_rows, a.response_taxonomy_candidate_match_overlap)
        _upsert_tracking_row(
            conn, run_id, new_pair_ids, matched,
            verdict.get("proposed_label", record["id"]), verdict.get("proposed_description", ""),
        )
        # Re-read this row's fresh state (insert or update above may have changed it).
        refreshed = next(
            (r for r in _load_tracking_rows(conn)
             if matched and r["candidate_id"] == matched["candidate_id"]),
            None,
        ) if matched else _load_tracking_rows(conn)[-1]
        if refreshed is None or refreshed["status"] != "tracking":
            continue
        if refreshed["consensus_count"] < a.response_taxonomy_consensus_runs:
            continue
        key = _attempt_graduation(
            conn, config, run_id, refreshed, record["nearest_coachable_sim"],
            a.merge_cosine_threshold, verdict.get("proposed_label", record["id"]),
            verdict.get("proposed_description", ""), verdict.get("reason", ""),
            record["samples"],
        )
        if key:
            graduated.append(key)

    _logger.info("run_id=%s: %d candidate(s) graduated: %s", run_id, len(graduated), graduated)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_response_taxonomy_auto_pass.py -v`
Expected: PASS, all so far.

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/ -v`
Expected: PASS.

- [ ] **Step 6: Sanity-check the script imports and parses cleanly**

Run: `cd Brain && ..\.venv\Scripts\python -c "import ast; ast.parse(open('response_taxonomy_auto_pass.py', encoding='utf-8').read())"`
Expected: no output, exit code 0.

- [ ] **Step 7: Commit**

```bash
git add Brain/response_taxonomy_auto_pass.py Brain/tests/test_response_taxonomy_auto_pass.py
git commit -m "Add run_auto_pass entry point: cluster, filter, track, graduate"
```

---

### Task 9: Wire into `v2/pipeline.py`

**Files:**

- Modify: `Brain/v2/pipeline.py`

- [ ] **Step 1: Add the call, wrapped in try/except**

In `Brain/v2/pipeline.py`, after the existing `layer_c.run_layer_c_v2(scenario_map, config, conn, run_id)` line and before `_reconcile(conn, len(scenario_map))`:

```python
    print("\n[Response-taxonomy auto-pass] Checking for homeless topics to graduate...")
    try:
        response_taxonomy_auto_pass.run_auto_pass(config, conn, run_id)
    except Exception as exc:  # noqa: BLE001 -- must never fail the overall pipeline run
        print(f"  ! response_taxonomy_auto_pass failed (logged, not fatal): {exc}")
```

Add the import at the top of the file:

```python
import response_taxonomy_auto_pass
```

(`Brain/` is on `sys.path` for every pipeline entry point already — same style as
`graduate_sink_topics.py` importing `v2.layer_c` and vice versa being unnecessary here since
this is a same-level module, not a package-qualified one; confirm this resolves during Step 2
rather than assuming.)

- [ ] **Step 2: Sanity-check the import resolves**

Run: `cd Brain && ..\.venv\Scripts\python -c "import v2.pipeline"`
Expected: no output, exit code 0. If it raises `ModuleNotFoundError`, add
`from Brain import response_taxonomy_auto_pass` or an equivalent `sys.path` adjustment
matching how `v2/pipeline.py` already resolves its other same-level imports — inspect
`v2/pipeline.py`'s existing import block first rather than guessing.

- [ ] **Step 3: Run the full suite to confirm no regressions**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/ -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add Brain/v2/pipeline.py
git commit -m "Wire response_taxonomy_auto_pass into the V2 pipeline (disabled by default)"
```

---

### Task 10: Final full-suite check and summary

- [ ] **Step 1: Run everything once more**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/ -v`
Expected: PASS, previous count plus every new test added across Tasks 1–9.

- [ ] **Step 2: Confirm `response_taxonomy_auto_pass_enabled` is still `false` in the real `tuning.yaml`**

Run: `cd Brain && grep response_taxonomy_auto_pass_enabled tuning.yaml`
Expected: `response_taxonomy_auto_pass_enabled: false` — this plan never flips it. Flipping it
to `true` and actually running the pass against production is a separate, later step gated
on the human partner's explicit go-ahead, preceded by the production schema snapshot named
in the design spec.

- [ ] **Step 3: Report to the human partner**

Summarize: what was built, the two fixes applied to the design during planning
(`primary_topic_key` resolution; the five follow-up-risk decisions — 2 fixed, 3 explicitly
deferred with named rationale), test count, and that the real run against production is
ready whenever go-ahead is given.
