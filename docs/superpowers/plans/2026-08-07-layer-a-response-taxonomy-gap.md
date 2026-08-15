# Layer A Response-Taxonomy Gap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two independent milestones. Milestone 1 (`graduate_sink_topics.py`) writes the two
already-verdicted homeless topics (`strategic_performance_consulting`,
`technical_operational_alignment`) into the real taxonomy as scenarios, reroutes their exact
known pair IDs, and generates real rubrics for them — the first script in this whole
investigation that writes to production DB state. Milestone 2
(`dry_run_response_taxonomy.py`) is a zero-DB-write dry run generalizing the same
response-clustering technique to the whole corpus, to measure whether the gap is bigger than
these two known instances. Milestone 2 does not depend on Milestone 1 landing first.

**Architecture:**

- `Brain/graduate_sink_topics.py` — one-time backfill script.
- `Brain/dry_run_response_taxonomy.py` — read-only corpus-wide measurement script, structurally
  a sibling of `diagnose_sink_pool.py`.
- `PROMPT_GRADUATE_SINK_TOPIC` — new prompt in `shared/prompts.py`.
- `shared/cluster_evidence.py` gains two new pure, tested helpers: `passes_reconciliation_gate`
  (Milestone 1) and `purity_gate_verdict` (Milestone 2).
- `tuning.yaml` / `shared/tuning.py` gain one new key: `layer_a.response_taxonomy_purity_gate`
  (Milestone 2 only).

**Tech Stack:** Python 3.11, numpy, psycopg (read-write for Milestone 1, read-only for
Milestone 2), pytest, the existing `preprocessing.embedder` disk cache, Gemma via
`shared.gemma.call_gemma`.

**Reference spec:** `docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md`.

## Global Constraints

- Nothing in Milestone 2 writes to the DB or touches `tuning.yaml`'s Layer B keys
  (`matching_strategy`, `sink_rescue_strategy`) — per the spec's explicit scope boundary, this
  is a dry run only, full stop, regardless of what it finds.
- Milestone 1's reconciliation gate (`nearest_coachable_sim < merge_cosine_threshold`) is a
  hard gate. A cluster that fails it must be **skipped**, never force-routed into the
  near-neighbor scenario — that is the exact `by_cluster` failure mode already rejected in the
  sink-pool diagnostic (destructive merges).
- Milestone 1 requires a schema snapshot (`baseline_pre_graduation_20260807`) before any write,
  same pattern as the existing `baseline_20260728`.
- The production `public` schema was populated by the **V2** pipeline (`v2/layer_a.py`,
  `v2/layer_c.py::run_layer_c_v2`) — Milestone 1 must call `run_layer_c_v2`, not V1's
  `layer_c.run_layer_c`. `rerun_layer_c.py`'s own precedent script imports `v1.layer_c` and
  would target the wrong Layer C implementation if copied literally; that is a real trap, not a
  style choice.
- Every new tuning value goes into `tuning.yaml` under the right section, with a matching
  dataclass field in `shared/tuning.py` — unknown/missing keys must raise, per this codebase's
  existing rule.
- New pure-function tests use the same hand-built-data style as `tests/test_cluster_evidence.py`
  — no DB, no Gemma, no embeddings.
- **Amended after plan approval, per explicit human-partner instruction: READS against the real
  production `public` schema (Neon) are fine; WRITES are not, during this implementation/testing
  pass.** Consequences:
  - Milestone 2 (`dry_run_response_taxonomy.py`) is already zero-write by design — it runs
    directly against real production data with no change needed. Task 9 executes for real.
  - Milestone 1 (`graduate_sink_topics.py`) does write (the scenario insert + pair reroute).
    Its write path (`_graduate_one`'s INSERT/UPDATE calls) is verified with a mocked
    connection/cursor (`unittest.mock`) asserting the exact SQL and parameters — never executed
    against any real database, prod or otherwise. Its read path (loading real scenarios,
    computing real support stats, generating real Gemma metadata) is exercised for real via the
    script's existing `--dry-run` flag, which already reads real data and skips every write —
    this is Task 6 below.
  - Actually running `graduate_sink_topics.py` WITHOUT `--dry-run` against production (the real
    write) is a separate, explicit step the human partner triggers later — not part of this
    plan's execution. The original Task 1 (prod schema snapshot, needed only right before that
    real write) is deferred to that later step and dropped from this plan's task list; Task 1
    below is now the mocked-write test instead.

---

## Milestone 1 — `Brain/graduate_sink_topics.py`

### Task 1: (deferred) Schema snapshot — moved out of this pass

**Not executed in this implementation/testing pass.** Per the amended Global Constraints above,
no write against production happens here at all, so there is nothing yet to snapshot against.
This step (`CREATE SCHEMA baseline_pre_graduation_20260807 ...`, exactly as originally
specified two paragraphs below in the design spec) becomes the first step of the separate,
explicit "run the real write" session the human partner triggers later — immediately before
`graduate_sink_topics.py` is run without `--dry-run`. Proceed directly to Task 2.

---

### Task 2: `passes_reconciliation_gate` — pure, tested helper

**Files:**

- Modify: `Brain/shared/cluster_evidence.py`
- Modify: `Brain/tests/test_cluster_evidence.py`

**Interfaces:**

- Produces: `cluster_evidence.passes_reconciliation_gate(nearest_coachable_sim: float, merge_cosine_threshold: float) -> bool` — consumed by Task 5's script.

- [ ] **Step 1: Write the failing tests**

Add to `Brain/tests/test_cluster_evidence.py`:

```python
class TestPassesReconciliationGate:
    def test_true_when_comfortably_below_threshold(self):
        assert ce.passes_reconciliation_gate(0.726, 0.85) is True

    def test_false_when_at_or_above_threshold(self):
        assert ce.passes_reconciliation_gate(0.85, 0.85) is False
        assert ce.passes_reconciliation_gate(0.90, 0.85) is False

    def test_matches_the_two_known_graduated_clusters(self):
        # cluster_5 and cluster_8 from sink_pool_clusters.json -- the two candidates
        # this milestone actually graduates. If this ever goes False, something
        # upstream (embeddings, merge_cosine_threshold) has drifted since the design
        # spec was written, and graduation must not proceed on stale confidence.
        assert ce.passes_reconciliation_gate(0.726, 0.85) is True
        assert ce.passes_reconciliation_gate(0.742, 0.85) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_cluster_evidence.py::TestPassesReconciliationGate -v`
Expected: FAIL — `AttributeError: module 'shared.cluster_evidence' has no attribute 'passes_reconciliation_gate'`.

- [ ] **Step 3: Implement it**

Add to `Brain/shared/cluster_evidence.py` (near `triage`, `required_call_support`):

```python
def passes_reconciliation_gate(nearest_coachable_sim: float, merge_cosine_threshold: float) -> bool:
    """True iff a candidate homeless-topic cluster is genuinely distinct from its
    nearest existing coachable scenario, using the SAME threshold this codebase
    already uses to decide "duplicate or genuinely distinct" for subtopic dedup
    (merge_cosine_threshold). No new threshold -- the existing one already draws
    the right line here.

    A cluster that fails this must be SKIPPED by its caller, never force-routed
    into the near-neighbor scenario -- that is the exact failure mode the
    sink-pool diagnostic's by_cluster variant was rejected for (destructive
    milestone merges from routing content into a near-but-wrong scenario).
    """
    return nearest_coachable_sim < merge_cosine_threshold
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_cluster_evidence.py -v`
Expected: PASS, all prior tests plus 3 new ones.

- [ ] **Step 5: Commit**

```bash
git add Brain/shared/cluster_evidence.py Brain/tests/test_cluster_evidence.py
git commit -m "Add passes_reconciliation_gate helper for sink-topic graduation"
```

---

### Task 3: `PROMPT_GRADUATE_SINK_TOPIC`

**Files:**

- Modify: `Brain/shared/prompts.py`

No dedicated test — this codebase has no precedent for unit-testing prompt strings (every
other `PROMPT_*` in this file is exercised only by the script that calls it), so Task 5's
script is where this gets its first real exercise.

- [ ] **Step 1: Add the prompt**

Add to `Brain/shared/prompts.py`, after `PROMPT_SINK_POOL_TRIAGE`:

```python
# Writes the permanent scenario record for a cluster diagnose_sink_pool.py already
# verdicted "new_coachable_topic". Deliberately NOT a reuse of PROMPT_LAYER_A_V2_TRIAGE:
# that prompt is written to interpret CLIENT clauses and ask a coachability question
# this prompt's caller has already answered (see
# docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md). This
# prompt's only job is to write up an already-confirmed gap in the same output shape
# every other scenario in the taxonomy uses.
PROMPT_GRADUATE_SINK_TOPIC = """\
You are writing the permanent scenario record for a coaching topic that this taxonomy never
had an entry for. A prior audit already reviewed real call pairs and confirmed a genuine,
recurring expert behaviour exists here -- your job is only to write it up in the same shape as
every other scenario in the taxonomy, not to re-judge whether it is real.

PROPOSED LABEL: {proposed_label}
PROPOSED DESCRIPTION: {proposed_description}
WHY THIS IS A GAP, NOT A DUPLICATE OF AN EXISTING SCENARIO: {reason}

SAMPLE PAIRS (CLIENT trigger -> EXPERT response) THAT DEMONSTRATE THIS BEHAVIOUR:
{samples_block}

Write the scenario record a junior CS colleague would be coached against. Use the same
bloom_level rubric used everywhere else in this taxonomy:
- remember: recall facts -- pricing tiers, contract terms, SLA commitments
- understand: explain or restate a concern in Joveo terms
- apply: deploy a specific move in the moment -- objection handling, a conversational pivot
- analyze: diagnose a root cause, parse conflicting signals from multiple stakeholders
- evaluate: judge and justify a tradeoff -- escalate vs. hold, negotiate vs. stand firm
- create: construct something novel -- a custom ROI narrative, a multi-product proposal

Respond ONLY with valid JSON:
{{
  "scenario_key": "snake_case_identifier",
  "business_description": "one sentence naming the client situation and the expert move",
  "keyphrases": ["2-4 word phrase", "another phrase"],
  "soft_skills": ["skill_name"],
  "bloom_level": "apply"
}}
"""
```

- [ ] **Step 2: Sanity-check the format placeholders**

Run: `cd Brain && ..\.venv\Scripts\python -c "from shared.prompts import PROMPT_GRADUATE_SINK_TOPIC as p; print(p.format(proposed_label='x', proposed_description='y', reason='z', samples_block='s'))"`
Expected: prints the filled-in prompt with no `KeyError`/`IndexError` (catches a placeholder-name typo before Task 5 ever calls it for real).

- [ ] **Step 3: Commit**

```bash
git add Brain/shared/prompts.py
git commit -m "Add PROMPT_GRADUATE_SINK_TOPIC"
```

---

### Task 4: `response_taxonomy_purity_gate` tuning key

Belongs to Milestone 2 logically, but doing it now means Task 5 (Milestone 1) and Task 7
(Milestone 2) never block on tuning.yaml edits landing in the other order.

**Files:**

- Modify: `Brain/tuning.yaml`
- Modify: `Brain/shared/tuning.py` (`LayerATuning`)
- Modify: `Brain/tests/test_tuning.py`

- [ ] **Step 1: Write the failing test**

In `Brain/tests/test_tuning.py`, add to `_GOOD`'s `layer_a:` block (after
`primary_topic_merge_threshold: 0.70`):

```yaml
  response_taxonomy_purity_gate: 0.90
```

Add to `test_shipped_tuning_yaml_is_valid`:

```python
    assert 0.0 < t.layer_a.response_taxonomy_purity_gate <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_tuning.py -v`
Expected: FAIL — `ValueError: tuning.yaml: unknown key(s) in layer_a: ['response_taxonomy_purity_gate']`.

- [ ] **Step 3: Add the field to `LayerATuning`**

In `Brain/shared/tuning.py`:

```python
@dataclass(frozen=True)
class LayerATuning:
    min_call_support_fraction: float
    min_call_support_floor: int
    ubiquity_ceiling: float
    merge_cosine_threshold: float
    min_content_words: int
    grouping_method: str
    primary_topic_merge_threshold: float
    response_taxonomy_purity_gate: float
```

- [ ] **Step 4: Add the key to the real `tuning.yaml`**

In `Brain/tuning.yaml`, insert after `primary_topic_merge_threshold: 0.75` (still inside
`layer_a:`, before `layer_b:`):

```yaml
  # Corpus-wide response-taxonomy dry run (see
  # docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md). A response
  # cluster is skipped from three-way Gemma adjudication when one existing COACHABLE
  # scenario already accounts for at least this fraction of the cluster's members --
  # client-side and response-side taxonomies already agree there, so adjudicating it
  # would spend a Gemma call answering a question nobody asked. A cluster dominated by a
  # SINK scenario at this same fraction is NOT skipped -- that is exactly the case this
  # dry run exists to examine.
  #
  # PRE-REGISTERED STARTING POINT, not a fitted value -- fixed before dry_run_response_
  # taxonomy.py's own purity distribution exists, the same discipline diagnose_sink_pool.py's
  # _NOISE_ESCAPE_HATCH/_MIX_UNINFORMATIVE_BAND were held to. The dry run's own report is
  # what validates or corrects this number.
  response_taxonomy_purity_gate: 0.90
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_tuning.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/ -v`
Expected: PASS, same count plus the new tuning assertions folded into existing tests (no new
test functions here).

- [ ] **Step 7: Commit**

```bash
git add Brain/tuning.yaml Brain/shared/tuning.py Brain/tests/test_tuning.py
git commit -m "Add pre-registered response_taxonomy_purity_gate tuning key"
```

---

### Task 5: `Brain/graduate_sink_topics.py`

**Files:**

- Create: `Brain/graduate_sink_topics.py`

**Interfaces:**

- Consumes: `cluster_evidence.passes_reconciliation_gate` (Task 2), `PROMPT_GRADUATE_SINK_TOPIC`
  (Task 3), `storage.get_connection`, `storage.get_scenarios`, `storage.upsert_scenario`,
  `storage.get_rubric_for_scenario` (all existing), `v2.layer_c.run_layer_c_v2` (existing).
- Reads: `Brain/sink_pool_clusters.json` (already on disk, produced by `diagnose_sink_pool.py`).

**Amended: this task now includes one automated test**, added because writes against any real
database are off-limits during this pass (see Global Constraints). `_graduate_one`'s write path
(the `storage.upsert_scenario` call and the `UPDATE kb_pairs ... array_append(...)` reroute) is
verified with a mocked connection/cursor (`unittest.mock.MagicMock`) asserting the exact SQL text
and bound parameters are correct — no real database involved, so this is safe to run anywhere.
The read path (`_support_stats_for_pairs`, real Gemma metadata generation) is instead exercised
for real, safely, via the script's own `--dry-run` flag against the real read-only production
DB in Task 6 — reads are permitted, only writes are not.

- [ ] **Step 1: Write the script**

Create `Brain/graduate_sink_topics.py`:

```python
#!/usr/bin/env python3
"""Phase 1 of docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md.

Graduates already-verdicted "new_coachable_topic" clusters from sink_pool_clusters.json
(produced by diagnose_sink_pool.py) into real scenarios: inserts the scenario row, reroutes
its exact known sink_member_pair_ids, and runs Layer C for just the new scenario(s).

This is the FIRST script in this investigation that writes to production DB state -- every
prior script (diagnose_sink_pool.py, replay_layer_c_admitted.py, all eight rejected per-pair
signal rounds) was read-only. Take the schema snapshot in this plan's Task 1 before running
this for real.

No re-embedding, no re-clustering, no re-deriving cluster membership: every number and pair ID
used here was already computed and stored by diagnose_sink_pool.py.

Usage (from Brain/, venv active):
    python graduate_sink_topics.py --dry-run           # Gemma call + prints, zero DB writes
    python graduate_sink_topics.py                      # writes for real
    python graduate_sink_topics.py --clusters cluster_5  # graduate just one
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

from config import load_config
from shared import cluster_evidence, storage
from shared.gemma import call_gemma
from shared.prompts import PROMPT_GRADUATE_SINK_TOPIC
from shared.tuning import load_tuning
from v2.layer_c import run_layer_c_v2

_CLUSTERS_FILE = Path("sink_pool_clusters.json")
_TARGET_CLUSTER_IDS = ["cluster_5", "cluster_8"]
_GEMMA_CALL_DELAY = 5


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--clusters", default=",".join(_TARGET_CLUSTER_IDS),
                   help="comma-separated cluster ids from sink_pool_clusters.json to graduate")
    p.add_argument("--clusters-file", type=Path, default=_CLUSTERS_FILE)
    p.add_argument("--dry-run", action="store_true",
                   help="run the Gemma call and print the would-be scenario row; no DB writes")
    return p.parse_args()


def _render_samples(samples: list[dict]) -> str:
    return "\n".join(
        f"  - CLIENT: {s['trigger_text'][:150]!r}\n"
        f"    EXPERT: {s['response_text'][:400]!r}"
        for s in samples
    )


def _generate_metadata(record: dict, verdict: dict, config) -> dict:
    prompt = PROMPT_GRADUATE_SINK_TOPIC.format(
        proposed_label=verdict["proposed_label"],
        proposed_description=verdict["proposed_description"],
        reason=verdict["reason"],
        samples_block=_render_samples(record["samples"]),
    )
    result = call_gemma(prompt, config.gemma_api_keys)
    time.sleep(_GEMMA_CALL_DELAY)
    return result


def _support_stats_for_pairs(conn, pair_ids: list[int]) -> tuple[int, int, float]:
    """Recompute support_calls/support_clauses/call_coverage from the EXACT pairs being
    graduated, not diagnose_sink_pool.py's stored distinct_calls/call_coverage fields.

    Those stored fields were computed over the cluster's full union of sink-pool members
    AND its volume-matched coachable-control sample (mix_ratio's own denominator) -- e.g.
    cluster_5 stores distinct_calls=115 over 209 total members (94 sink + 115 control), not
    over the 94 sink pairs actually being rerouted here. Reusing that number verbatim would
    overstate this scenario's real evidence with calls it doesn't actually have any pairs
    in. support_clauses is set to len(pair_ids) rather than a real clause count --
    diagnose_sink_pool.py clusters at RESPONSE granularity, not Layer C's clause granularity,
    so there is no clause count to report; this is the count of graduated responses.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM calls")
        total_calls = int(cur.fetchone()[0])
        cur.execute(
            "SELECT COUNT(DISTINCT call_id) FROM kb_pairs WHERE pair_id = ANY(%s)",
            (pair_ids,),
        )
        distinct_calls = int(cur.fetchone()[0])
    call_coverage = distinct_calls / max(total_calls, 1)
    return distinct_calls, len(pair_ids), call_coverage


def _graduate_one(cluster_id: str, record: dict, verdict: dict, config, conn,
                   dry_run: bool) -> str | None:
    tuning = load_tuning().layer_a
    if verdict.get("verdict") != "new_coachable_topic":
        print(f"[{cluster_id}] verdict is {verdict.get('verdict')!r}, not "
              f"'new_coachable_topic' -- skipping.")
        return None

    if not cluster_evidence.passes_reconciliation_gate(
        record["nearest_coachable_sim"], tuning.merge_cosine_threshold
    ):
        print(f"[{cluster_id}] FAILS reconciliation gate: nearest_coachable_sim="
              f"{record['nearest_coachable_sim']:.3f} >= merge_cosine_threshold="
              f"{tuning.merge_cosine_threshold:.3f} -- SKIPPING. Do not force-route into "
              f"{record['nearest_coachable']!r}; that is the by_cluster failure mode this "
              f"design explicitly rejects.")
        return None

    print(f"[{cluster_id}] reconciliation gate OK ({record['nearest_coachable_sim']:.3f} < "
          f"{tuning.merge_cosine_threshold:.3f}). Generating scenario metadata via Gemma...")
    meta = _generate_metadata(record, verdict, config)
    print(f"  -> scenario_key={meta['scenario_key']!r}")
    print(f"  -> business_description={meta['business_description']!r}")

    pair_ids = record["sink_member_pair_ids"]
    if dry_run:
        distinct_calls, n_pairs, call_coverage = _support_stats_for_pairs(conn, pair_ids)
        print(f"  [DRY RUN] would insert scenario, reroute {n_pairs} pair(s) spanning "
              f"{distinct_calls} distinct call(s) ({call_coverage:.1%} coverage). No writes made.")
        return None

    distinct_calls, n_pairs, call_coverage = _support_stats_for_pairs(conn, pair_ids)
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
        "primary_topic_key": None,
    }
    scenario_id = storage.upsert_scenario(conn, row)
    print(f"  -> scenario_id={scenario_id}")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE kb_pairs
               SET scenario_key = %s, scenario_id = %s,
                   scenario_keys = array_append(scenario_keys, %s)
             WHERE pair_id = ANY(%s)
            """,
            (row["scenario_key"], scenario_id, row["scenario_key"], pair_ids),
        )
        rerouted = cur.rowcount
    conn.commit()
    print(f"  -> rerouted {rerouted} pair(s) (expected {len(pair_ids)})")
    if rerouted != len(pair_ids):
        raise RuntimeError(
            f"[{cluster_id}] rerouted {rerouted} pair(s), expected exactly {len(pair_ids)} -- "
            f"aborting before Layer C runs on a possibly-wrong pair set."
        )
    return row["scenario_key"]


def main() -> None:
    args = _parse_args()
    target_ids = [c.strip() for c in args.clusters.split(",") if c.strip()]

    config = load_config()
    payload = json.loads(args.clusters_file.read_text(encoding="utf-8-sig"))
    clusters_by_id = {r["id"]: r for r in payload["clusters"]}
    verdicts = payload.get("verdicts", {})

    conn = storage.get_connection(config.database_url)
    before_count = len(storage.get_scenarios(conn))

    graduated_keys: list[str] = []
    for cluster_id in target_ids:
        record = clusters_by_id.get(cluster_id)
        verdict = verdicts.get(cluster_id)
        if record is None or verdict is None:
            print(f"[{cluster_id}] not found in {args.clusters_file} -- skipping.")
            continue
        key = _graduate_one(cluster_id, record, verdict, config, conn, args.dry_run)
        if key:
            graduated_keys.append(key)

    if args.dry_run:
        print("\n[DRY RUN] complete -- no scenarios inserted, no pairs rerouted, Layer C not run.")
        conn.close()
        return

    if not graduated_keys:
        print("\nNothing graduated -- nothing to run Layer C for.")
        conn.close()
        return

    after_count = len(storage.get_scenarios(conn))
    print(f"\nScenario count: {before_count} -> {after_count} "
          f"(+{after_count - before_count}, expected +{len(graduated_keys)})")
    if after_count - before_count != len(graduated_keys):
        raise RuntimeError(
            f"scenario count increased by {after_count - before_count}, expected exactly "
            f"{len(graduated_keys)} -- investigate before trusting anything downstream."
        )

    print(f"\nRunning Layer C (V2) for: {graduated_keys}")
    all_scenarios = {s["scenario_key"]: s for s in storage.get_scenarios(conn)}
    targeted = {k: all_scenarios[k] for k in graduated_keys}
    run_layer_c_v2(targeted, config, conn, run_id="")

    print("\n=== Generated rubrics (READ THESE BEFORE CALLING THIS DONE) ===")
    for key in graduated_keys:
        rubric = storage.get_rubric_for_scenario(conn, key)
        print(f"\n--- {key} ---")
        print(json.dumps(rubric, indent=2, default=str) if rubric else "  NO RUBRIC GENERATED")

    conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the mocked-write test**

Create `Brain/tests/test_graduate_sink_topics.py`. Mocks `storage.get_connection` and Gemma
entirely — no real DB, no real network, safe to run anywhere:

```python
"""graduate_sink_topics.py's write path, verified against a mocked connection/cursor -- no
real database, per this plan's Global Constraints (reads against prod are fine, writes are not
during this pass). Asserts the exact SQL and bound parameters _graduate_one would send.
"""
from unittest.mock import MagicMock, call

import graduate_sink_topics as gst
from shared import cluster_evidence


def _record(sim=0.726):
    return {
        "nearest_coachable_sim": sim,
        "nearest_coachable": "client_requests_operational_visualization",
        "sink_member_pair_ids": [101, 102, 103],
        "samples": [{"pair_id": 101, "trigger_text": "t", "response_text": "r"}],
    }


def _verdict():
    return {
        "verdict": "new_coachable_topic",
        "proposed_label": "strategic_performance_consulting",
        "proposed_description": "desc",
        "reason": "reason text",
    }


def _mock_conn(distinct_calls=2, total_calls=10, rowcount=3):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    # _support_stats_for_pairs issues COUNT(*) FROM calls then COUNT(DISTINCT call_id) ...
    cur.fetchone.side_effect = [(total_calls,), (distinct_calls,)]
    cur.rowcount = rowcount
    return conn, cur


class TestGraduateOne:
    def test_skips_when_verdict_is_not_new_coachable_topic(self, monkeypatch):
        conn, cur = _mock_conn()
        result = gst._graduate_one(
            "cluster_5", _record(), {"verdict": "genuine_sink"}, config=None, conn=conn,
            dry_run=False,
        )
        assert result is None
        cur.execute.assert_not_called()

    def test_skips_when_reconciliation_gate_fails(self, monkeypatch):
        conn, cur = _mock_conn()
        result = gst._graduate_one(
            "cluster_5", _record(sim=0.90), _verdict(), config=None, conn=conn, dry_run=False,
        )
        assert result is None
        cur.execute.assert_not_called()

    def test_writes_expected_insert_and_reroute_sql(self, monkeypatch):
        monkeypatch.setattr(gst, "_generate_metadata", lambda record, verdict, config: {
            "scenario_key": "strategic_performance_consulting",
            "business_description": "desc",
            "keyphrases": ["kp"],
            "soft_skills": ["skill"],
            "bloom_level": "apply",
        })
        conn, cur = _mock_conn(distinct_calls=2, total_calls=10, rowcount=3)
        monkeypatch.setattr(gst.storage, "upsert_scenario", lambda c, row: 999)

        result = gst._graduate_one(
            "cluster_5", _record(), _verdict(), config=None, conn=conn, dry_run=False,
        )

        assert result == "strategic_performance_consulting"
        reroute_call = cur.execute.call_args
        sql, params = reroute_call.args
        assert "UPDATE kb_pairs" in sql
        assert "array_append(scenario_keys" in sql
        assert params == (
            "strategic_performance_consulting", 999, "strategic_performance_consulting",
            [101, 102, 103],
        )
        conn.commit.assert_called()

    def test_raises_when_rerouted_count_does_not_match(self, monkeypatch):
        monkeypatch.setattr(gst, "_generate_metadata", lambda record, verdict, config: {
            "scenario_key": "x", "business_description": "d", "keyphrases": [],
            "soft_skills": [], "bloom_level": "apply",
        })
        conn, cur = _mock_conn(rowcount=2)  # expects 3, mock returns 2
        monkeypatch.setattr(gst.storage, "upsert_scenario", lambda c, row: 999)

        import pytest
        with pytest.raises(RuntimeError, match="rerouted 2"):
            gst._graduate_one(
                "cluster_5", _record(), _verdict(), config=None, conn=conn, dry_run=False,
            )

    def test_dry_run_makes_no_writes(self, monkeypatch):
        monkeypatch.setattr(gst, "_generate_metadata", lambda record, verdict, config: {
            "scenario_key": "x", "business_description": "d", "keyphrases": [],
            "soft_skills": [], "bloom_level": "apply",
        })
        conn, cur = _mock_conn()
        result = gst._graduate_one(
            "cluster_5", _record(), _verdict(), config=None, conn=conn, dry_run=True,
        )
        assert result is None
        cur.execute.assert_not_called()
        conn.commit.assert_not_called()
```

- [ ] **Step 3: Run the tests**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_graduate_sink_topics.py -v`
Expected: PASS, 5/5. No database connection is opened anywhere in this run.

- [ ] **Step 4: Run the full suite to confirm no regressions**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/ -v`
Expected: PASS.

- [ ] **Step 5: Sanity-check the script itself imports and parses cleanly**

Run: `cd Brain && ..\.venv\Scripts\python -c "import ast; ast.parse(open('graduate_sink_topics.py', encoding='utf-8').read())"`
Expected: no output, exit code 0.

- [ ] **Step 6: Commit**

```bash
git add Brain/graduate_sink_topics.py Brain/tests/test_graduate_sink_topics.py
git commit -m "Add graduate_sink_topics.py Phase 1 backfill script, with a mocked-write test"
```

---

### Task 6: Dry-run it against real (read-only) production data

Reads against the real `public` schema are fine; this task never calls `graduate_sink_topics.py`
without `--dry-run`, so nothing is written. Requires reading real Gemma output and judging it —
run directly, not via a subagent with no context on what "a plausible scenario record" looks
like.

**Explicitly out of scope for this task:** actually running `graduate_sink_topics.py` without
`--dry-run` (the real insert + reroute + Layer C run) and reading the resulting real rubrics.
That is the separate, explicit later step named in the Global Constraints — it needs its own
schema snapshot (the original Task 1, deferred) taken immediately beforehand, and the human
partner's direct go-ahead at that time.

- [ ] **Step 1: Run the dry run against real production data**

```bash
cd Brain
$env:PYTHONIOENCODING="utf-8"
..\.venv\Scripts\python graduate_sink_topics.py --dry-run | Out-File -Encoding utf8 graduate_sink_topics_dry_run_20260807.log
```

(`Out-File -Encoding utf8`, not `Tee-Object` — `Tee-Object` writes UTF-16, per `CLAUDE.md`'s
Gotchas.)

- [ ] **Step 2: Read the output**

Confirm: both clusters pass the reconciliation gate, Gemma returns a plausible
`scenario_key`/`business_description`/`keyphrases`/`soft_skills`/`bloom_level`, and the printed
would-be support stats (distinct calls, coverage) look sane for ~94 and ~81 pairs respectively
(materially smaller than the 115-call/27.6% figures in the design doc's evidence table, which
counted the volume-matched control sample too — expect that mismatch, it's
`_support_stats_for_pairs`'s whole point). No database write occurred — confirm the log says so.

- [ ] **Step 3: Record findings in the design spec**

Edit `docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md`: append a
"Status update" section (matching the convention in e.g.
`2026-07-30-layer-b-two-stage-matching-design.md`) with the dry-run's Gemma-generated metadata
for both clusters, the real computed support stats, and an explicit note that the real write is
deferred to a separate session pending the human partner's go-ahead.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md Brain/graduate_sink_topics_dry_run_20260807.log
git commit -m "Dry-run graduate_sink_topics.py against real production data (no writes)"
```

---

## Milestone 2 — `Brain/dry_run_response_taxonomy.py`

Does not depend on Milestone 1 landing. Task 4 (the tuning key) is a shared prerequisite and
is already done above.

### Task 7: `purity_gate_verdict` — pure, tested helper

**Files:**

- Modify: `Brain/shared/cluster_evidence.py`
- Modify: `Brain/tests/test_cluster_evidence.py`

**Interfaces:**

- Produces: `cluster_evidence.purity_gate_verdict(scenario_key_counts: dict[str, int], is_coachable: dict[str, bool], dominance_fraction: float) -> tuple[bool, str | None]` — `(skip, dominant_key)`. Consumed by Task 9's script.

- [ ] **Step 1: Write the failing tests**

Add to `Brain/tests/test_cluster_evidence.py`:

```python
class TestPurityGateVerdict:
    def test_skips_when_one_coachable_scenario_dominates(self):
        counts = {"pricing_discussion": 92, "quality_signal": 8}
        is_coachable = {"pricing_discussion": True, "quality_signal": True}
        skip, dominant = ce.purity_gate_verdict(counts, is_coachable, dominance_fraction=0.90)
        assert skip is True
        assert dominant == "pricing_discussion"

    def test_does_not_skip_when_a_sink_dominates(self):
        # A cluster overwhelmingly filed to a SINK is exactly the case this dry run
        # exists to examine -- purity-skipping it would defeat the whole point.
        counts = {"conversational_confirmation_and_fillers": 95, "pricing_discussion": 5}
        is_coachable = {"conversational_confirmation_and_fillers": False, "pricing_discussion": True}
        skip, dominant = ce.purity_gate_verdict(counts, is_coachable, dominance_fraction=0.90)
        assert skip is False

    def test_does_not_skip_when_scattered_across_several_coachable_scenarios(self):
        counts = {"a": 40, "b": 35, "c": 25}
        is_coachable = {"a": True, "b": True, "c": True}
        skip, dominant = ce.purity_gate_verdict(counts, is_coachable, dominance_fraction=0.90)
        assert skip is False

    def test_dominance_exactly_at_threshold_skips(self):
        counts = {"a": 90, "b": 10}
        is_coachable = {"a": True, "b": True}
        skip, dominant = ce.purity_gate_verdict(counts, is_coachable, dominance_fraction=0.90)
        assert skip is True

    def test_empty_counts_never_skips(self):
        skip, dominant = ce.purity_gate_verdict({}, {}, dominance_fraction=0.90)
        assert skip is False
        assert dominant is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_cluster_evidence.py::TestPurityGateVerdict -v`
Expected: FAIL — `AttributeError: module 'shared.cluster_evidence' has no attribute 'purity_gate_verdict'`.

- [ ] **Step 3: Implement it**

Add to `Brain/shared/cluster_evidence.py`:

```python
def purity_gate_verdict(
    scenario_key_counts: dict[str, int],
    is_coachable: dict[str, bool],
    dominance_fraction: float,
) -> tuple[bool, str | None]:
    """Generalizes diagnose_sink_pool.py's "skip pure-control clusters" optimization from a
    binary sink/control split to an arbitrary current scenario_key composition.

    Skips (returns skip=True) ONLY when one existing COACHABLE scenario already accounts for
    at least dominance_fraction of the cluster's members -- client-side and response-side
    taxonomies already agree there, so adjudicating would spend a Gemma call answering a
    question nobody asked.

    A cluster dominated by a SINK scenario at the same fraction is NOT skipped -- that is
    exactly the population this dry run exists to examine, and skipping it would silently
    reproduce the sink pool's own blind spot one level up.
    """
    total = sum(scenario_key_counts.values())
    if total == 0:
        return False, None
    dominant_key, dominant_count = max(scenario_key_counts.items(), key=lambda kv: kv[1])
    dominant_fraction = dominant_count / total
    if dominant_fraction >= dominance_fraction and is_coachable.get(dominant_key, False):
        return True, dominant_key
    return False, dominant_key
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/test_cluster_evidence.py -v`
Expected: PASS, all prior tests plus 5 new ones.

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `cd Brain && ..\.venv\Scripts\pytest tests/ -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add Brain/shared/cluster_evidence.py Brain/tests/test_cluster_evidence.py
git commit -m "Add purity_gate_verdict helper for the response-taxonomy dry run"
```

---

### Task 8: `Brain/dry_run_response_taxonomy.py`

**Files:**

- Create: `Brain/dry_run_response_taxonomy.py`

**Interfaces:**

- Consumes: `cluster_evidence.purity_gate_verdict` (Task 7),
  `cluster_evidence.milestone_min_cluster_size` (existing), `v2.layer_c._cluster_milestones`
  (existing, same import `diagnose_sink_pool.py` already uses),
  `shared.scenario_vectors.build_scenario_vecs` (existing), `PROMPT_SINK_POOL_TRIAGE`
  (existing — reused verbatim, no new adjudication prompt per the spec).

No automated test, matching `diagnose_sink_pool.py`'s own precedent — an ad-hoc, read-only
measurement script. Verified in Task 9 by running it for real.

- [ ] **Step 1: Write the script**

Create `Brain/dry_run_response_taxonomy.py`, structured as a direct sibling of
`diagnose_sink_pool.py` (same CLI shape, same `--load`/`--no-gemma` flags, same persisted-JSON
discipline) but over the WHOLE corpus instead of sink pool + a volume-matched control:

```python
#!/usr/bin/env python3
"""Phase 2 of docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md.

Generalizes diagnose_sink_pool.py's response-clustering technique from "sink pool + a
volume-matched control sample" to EVERY response in the corpus (~4,605 kb_pairs rows), to
measure whether the response-taxonomy gap is bigger than the two clusters already graduated
by graduate_sink_topics.py.

Zero DB writes. Same clustering call (v2.layer_c._cluster_milestones,
cluster_evidence.milestone_min_cluster_size) and the same three-way verdict prompt
(PROMPT_SINK_POOL_TRIAGE) diagnose_sink_pool.py already validated -- no new clustering
machinery, no new adjudication prompt.

Key difference from diagnose_sink_pool.py: instead of a binary sink/control mix_ratio, each
cluster reports its CURRENT scenario_key composition (which may span several coachable
scenarios, several sinks, or both). A cluster is skipped from adjudication only when one
coachable scenario already dominates it above response_taxonomy_purity_gate -- a cluster
dominated by a SINK is deliberately NOT skipped; see cluster_evidence.purity_gate_verdict.

Does NOT decide whether to build a permanent recurring pass -- that is a distinct follow-up
design, contingent on what this run finds.

Usage (from Brain/, venv active):
    python dry_run_response_taxonomy.py
    python dry_run_response_taxonomy.py --no-gemma
    python dry_run_response_taxonomy.py --load dry_run_response_taxonomy.json
"""
from __future__ import annotations
import argparse
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np

from config import load_config
from preprocessing import embedder
from shared import cluster_evidence, storage
from shared.gemma import call_gemma
from shared.prompts import PROMPT_SINK_POOL_TRIAGE
from shared.scenario_vectors import build_scenario_vecs
from shared.tuning import load_tuning
from v2.layer_c import _cluster_milestones

_BATCH_SIZE = 5
_GEMMA_CALL_DELAY = 5
_SAMPLES_PER_CLUSTER = 4
_SAMPLE_CHARS = 300
_DEFAULT_OUTPUT = Path("dry_run_response_taxonomy.json")


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--load", type=Path, default=None)
    p.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    p.add_argument("--no-gemma", action="store_true")
    p.add_argument("--min-cluster-size", type=int, default=None)
    p.add_argument("--seed", type=int, default=0)
    return p.parse_args()


def _load_all_pairs(conn) -> tuple[list[dict], int]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT kb.pair_id, kb.trigger_text, kb.response_text, kb.scenario_key,
                   c.filename
            FROM kb_pairs kb JOIN calls c ON c.call_id = kb.call_id
            WHERE kb.scenario_key IS NOT NULL
            ORDER BY kb.pair_id
        """)
        rows = cur.fetchall()
        cur.execute("SELECT count(*) FROM calls")
        total_calls = int(cur.fetchone()[0])
    pairs = [
        {"pair_id": r[0], "trigger_text": r[1], "response_text": r[2],
         "scenario_key": r[3], "call_filename": r[4]}
        for r in rows
    ]
    return pairs, total_calls


def _cluster_corpus(pairs: list[dict], tuning, override: int | None):
    texts = [p["response_text"] for p in pairs]
    print(f"Embedding {len(texts)} response(s) via embed_document (warm cache expected)...")
    vecs = embedder.embed_document_matrix(texts)
    derived = cluster_evidence.milestone_min_cluster_size(
        len(pairs), tuning.min_cluster_size_fraction,
        tuning.min_cluster_size_floor, tuning.min_cluster_size_ceiling,
    )
    mcs = override if override is not None else derived
    print(f"min_cluster_size: {mcs}")
    print(f"Clustering (UMAP n_components<={tuning.umap_n_components}, cosine -> HDBSCAN)...")
    labels = _cluster_milestones(vecs, mcs, tuning.umap_n_components)
    return vecs, labels, mcs


def _scenario_sides(scenario_map: dict):
    coachable = {k: v for k, v in scenario_map.items() if v.get("is_coachable", True)}
    sinks = {k: v for k, v in scenario_map.items() if not v.get("is_coachable", True)}

    def _norm(d):
        keys, vecs = build_scenario_vecs(d)
        arr = np.asarray(vecs, dtype=np.float32)
        return keys, arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-10)

    ck, cv = _norm(coachable)
    sk, sv = _norm(sinks)
    return ck, cv, sk, sv


def _build_records(pairs, vecs, labels, scenario_map, total_calls, purity_gate, seed) -> list[dict]:
    ck, cv, sk, sv = _scenario_sides(scenario_map)
    is_coachable = {k: True for k in ck} | {k: False for k in sk}
    rng = random.Random(seed)
    records = []

    for label in sorted({int(l) for l in labels} - {-1}):
        idx = [i for i, l in enumerate(labels) if int(l) == label]
        members = [pairs[i] for i in idx]
        composition = Counter(m["scenario_key"] for m in members)

        skip, dominant_key = cluster_evidence.purity_gate_verdict(
            dict(composition), is_coachable, purity_gate,
        )

        centroid = cluster_evidence.milestone_cluster_centroid(vecs[idx])
        centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
        c_sims, s_sims = cv @ centroid, sv @ centroid
        c_best = int(np.argmax(c_sims))
        s_best = int(np.argmax(s_sims)) if sk else None

        samples = rng.sample(members, min(_SAMPLES_PER_CLUSTER, len(members)))
        records.append({
            "id": f"cluster_{label}",
            "size": len(members),
            "distinct_calls": len({m["call_filename"] for m in members}),
            "call_coverage": len({m["call_filename"] for m in members}) / max(total_calls, 1),
            "current_composition_top5": composition.most_common(5),
            "purity_gated": skip,
            "dominant_key": dominant_key,
            "nearest_coachable": ck[c_best],
            "nearest_coachable_sim": float(c_sims[c_best]),
            "nearest_coachable_description":
                scenario_map[ck[c_best]].get("business_description", ""),
            "nearest_sink": sk[s_best] if sk and s_best is not None else None,
            "nearest_sink_sim": float(s_sims[s_best]) if sk and s_best is not None else None,
            "member_pair_ids": [m["pair_id"] for m in members],
            "samples": [
                {"pair_id": s["pair_id"], "trigger_text": s["trigger_text"],
                 "response_text": s["response_text"], "scenario_key": s["scenario_key"]}
                for s in samples
            ],
        })
    return records


def _render_cluster(r: dict) -> str:
    samples = "\n".join(
        f"    - CLIENT: {s['trigger_text'][:120]!r}\n"
        f"      EXPERT: {s['response_text'][:_SAMPLE_CHARS]!r}"
        for s in r["samples"]
    )
    composition = ", ".join(f"{k} x{n}" for k, n in r["current_composition_top5"])
    return (
        f"- id: {r['id']}\n"
        f"  EVIDENCE: {r['size']} pair(s) in this cluster, spanning "
        f"{r['distinct_calls']} distinct call(s) ({r['call_coverage']:.0%} of the corpus)\n"
        f"  NEAREST EXISTING COACHABLE TOPIC: {r['nearest_coachable']} "
        f"(cosine {r['nearest_coachable_sim']:.3f})\n"
        f"    its description: {r['nearest_coachable_description']}\n"
        f"  NEAREST SINK TOPIC: {r['nearest_sink']} (cosine {r['nearest_sink_sim']:.3f})\n"
        f"  CURRENTLY FILED UNDER: {composition}\n"
        f"  SAMPLE PAIRS:\n{samples}"
    )


def _adjudicate(records: list[dict], config) -> dict[str, dict]:
    targets = [r for r in records if not r["purity_gated"]]
    skipped = len(records) - len(targets)
    print(f"  ({skipped} cluster(s) skipped by the purity gate -- one coachable scenario "
          f"already dominates.)")

    verdicts: dict[str, dict] = {}
    n_calls = math.ceil(len(targets) / _BATCH_SIZE)
    print(f"Adjudicating {len(targets)} cluster(s) in {n_calls} batched Gemma call(s)...")
    for i in range(0, len(targets), _BATCH_SIZE):
        chunk = targets[i:i + _BATCH_SIZE]
        items_block = "\n\n".join(_render_cluster(r) for r in chunk)
        try:
            raw = call_gemma(
                PROMPT_SINK_POOL_TRIAGE.format(items_block=items_block),
                config.gemma_api_keys,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ! batch {i // _BATCH_SIZE + 1} failed: {exc}")
            time.sleep(_GEMMA_CALL_DELAY)
            continue
        time.sleep(_GEMMA_CALL_DELAY)
        raw_list = raw if isinstance(raw, list) else raw.get("results", [])
        for r in raw_list:
            if isinstance(r, dict) and "id" in r:
                verdicts[r["id"]] = r
        print(f"  batch {i // _BATCH_SIZE + 1}/{n_calls}: {len(verdicts)} verdict(s) so far")
    return verdicts


def _report(payload: dict) -> None:
    records, verdicts = payload["clusters"], payload.get("verdicts", {})
    gated = sum(1 for r in records if r["purity_gated"])
    print("\n" + "=" * 78)
    print("CORPUS-WIDE RESPONSE TAXONOMY REPORT")
    print("=" * 78)
    print(f"  total pairs clustered            : {payload['n_pairs_total']}")
    print(f"  clusters found                    : {len(records)}")
    print(f"  purity-gated (skipped)            : {gated}")
    print(f"  sent to adjudication               : {len(records) - gated}")

    sims = [r["nearest_coachable_sim"] for r in records]
    print(f"\n  nearest_coachable_sim distribution (validates merge_cosine_threshold=0.85):")
    print("    " + "  ".join(f"p{p}={np.percentile(sims, p):.3f}" for p in (10, 25, 50, 75, 90)))

    if verdicts:
        tally = Counter(v.get("verdict", "?") for v in verdicts.values())
        print("\n  Three-way verdict tally:")
        for verdict, n in tally.most_common():
            print(f"    {verdict:<22} {n:>3} cluster(s)")
        new_topics = [rid for rid, v in verdicts.items() if v.get("verdict") == "new_coachable_topic"]
        print(f"\n  new_coachable_topic clusters (compare against the 2 already known -- "
              f"strategic_performance_consulting, technical_operational_alignment): "
              f"{len(new_topics)}")
        for rid in new_topics:
            print(f"    {rid}: {verdicts[rid].get('proposed_label')}")


def main() -> None:
    args = _parse_args()

    if args.load:
        payload = json.loads(args.load.read_text(encoding="utf-8-sig"))
        print(f"Re-reporting {args.load} (zero DB reads, zero Gemma calls).")
        _report(payload)
        return

    config = load_config()
    tuning = load_tuning()
    conn = storage.get_connection(config.database_url)
    scenario_map = {r["scenario_key"]: r for r in storage.get_scenarios(conn)}
    pairs, total_calls = _load_all_pairs(conn)
    conn.close()

    print(f"Loaded {len(scenario_map)} scenario(s), {len(pairs)} pair(s), {total_calls} call(s).")
    if not pairs:
        print("No pairs available -- nothing to measure.")
        sys.exit(1)

    vecs, labels, mcs = _cluster_corpus(pairs, tuning.layer_c, args.min_cluster_size)
    records = _build_records(
        pairs, vecs, labels, scenario_map, total_calls,
        tuning.layer_a.response_taxonomy_purity_gate, args.seed,
    )

    verdicts = {} if args.no_gemma else _adjudicate(records, config)
    payload = {
        "schema": "public",
        "n_pairs_total": len(pairs),
        "min_cluster_size": mcs,
        "purity_gate": tuning.layer_a.response_taxonomy_purity_gate,
        "seed": args.seed,
        "clusters": records,
        "verdicts": verdicts,
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nPersisted to {args.output} -- re-report for free with --load {args.output}")
    _report(payload)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity-check it imports and parses cleanly**

Run: `cd Brain && ..\.venv\Scripts\python -c "import ast; ast.parse(open('dry_run_response_taxonomy.py', encoding='utf-8').read())"`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add Brain/dry_run_response_taxonomy.py
git commit -m "Add dry_run_response_taxonomy.py Phase 2 corpus-wide measurement script"
```

---

### Task 9: Run the dry run and record findings

Requires a live `DATABASE_URL` against `public`. Zero DB writes regardless of outcome. Requires
reading real cluster samples and verdicts — run directly, same reasoning as Task 6.

- [ ] **Step 1: Free pass first**

```bash
cd Brain
$env:PYTHONIOENCODING="utf-8"
..\.venv\Scripts\python dry_run_response_taxonomy.py --no-gemma | Out-File -Encoding utf8 dry_run_response_taxonomy_no_gemma_20260807.log
```

Read the purity-gate breakdown and the `nearest_coachable_sim` percentile line before spending
any Gemma budget on the full run.

- [ ] **Step 2: Full run**

```bash
cd Brain
$env:PYTHONIOENCODING="utf-8"
..\.venv\Scripts\python dry_run_response_taxonomy.py | Out-File -Encoding utf8 dry_run_response_taxonomy_20260807.log
```

- [ ] **Step 3: Read the verdict tally and every `new_coachable_topic` cluster's samples**

Confirm whether `strategic_performance_consulting` and `technical_operational_alignment`
reappear (expected — the corpus-wide pass should rediscover them) and how many additional
`new_coachable_topic` clusters exist beyond those two. Read the verbatim samples for any new
one before trusting it as real.

- [ ] **Step 4: Check the purity-gate starting value against the real distribution**

Look at how many clusters landed near the 0.90 boundary. Note in the findings whether 0.90
should be revisited, per the design's own framing of it as a pre-registered starting point, not
a fitted value — but do not change `tuning.yaml` as part of this task; that is a separate,
deliberate follow-up if warranted.

- [ ] **Step 5: Append a "Status update" section to the design spec**

Edit `docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md` with: total
clusters, purity-gated vs. adjudicated counts, the verdict tally, the count of
`new_coachable_topic` clusters beyond the two known ones, the `nearest_coachable_sim`
percentile line, and an explicit statement of whether the gap looks bigger than what's already
been graduated — and, per the spec's own scope boundary, an explicit non-decision on whether to
build a permanent recurring pass.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md Brain/dry_run_response_taxonomy_20260807.log Brain/dry_run_response_taxonomy_no_gemma_20260807.log Brain/dry_run_response_taxonomy.json
git commit -m "Record dry_run_response_taxonomy.py corpus-wide findings"
```
