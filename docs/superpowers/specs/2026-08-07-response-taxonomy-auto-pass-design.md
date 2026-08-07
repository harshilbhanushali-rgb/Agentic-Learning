# Response-taxonomy auto-pass: permanent, automatic homeless-topic graduation

## Problem

`v2/layer_a.py` builds the scenario taxonomy from CLIENT clauses only — expert (Naren)
responses to filler-sounding client cues have no scenario they could ever be routed to.
Two prior scripts addressed pieces of this manually:

- `graduate_sink_topics.py` — one-time, hand-run, hardcoded to graduate 2 already-identified
  "homeless" clusters (`strategic_performance_consulting`, `technical_operational_alignment`)
  into real scenarios.
- `dry_run_response_taxonomy.py` — zero-write, corpus-wide measurement of how far this gap
  extends. Found a 3rd candidate (`cluster_6` / `expert_led_discovery_and_context_setting`),
  and flagged it as unsafe to graduate blindly: its own docstring/status notes name two
  blockers — a field-name mismatch, and no guarantee its member pairs are all still
  sink-bound (some could already be correctly homed to a real scenario).

Both scripts are explicitly documented as **not** a permanent mechanism. This design covers
that deliberately-deferred follow-up: a pass that runs automatically after every pipeline
execution, finds homeless topics, and graduates them — with zero human step.

## Decisions

1. **Fully autonomous.** No human approval gate before a write. This is what "permanent,
   automatic" means — it has to be callable from the pipeline itself, not something a person
   triggers by hand.
2. **Cross-run consensus before acting**, to absorb UMAP+HDBSCAN's documented run-to-run
   instability (241→403→398→404 milestone variance measured previously on this same
   clustering step). A candidate must reappear across `response_taxonomy_consensus_runs`
   consecutive pipeline runs before it is graduated — not acted on the first time it's seen.
3. **Runs every pipeline execution**, gated by a single enabled/disabled boolean in
   `tuning.yaml`. No separate cadence throttle (e.g. "every Kth run") — if cost becomes a
   real problem later, that's a follow-up change to the config, not solved now.
4. **Observability: structured log file only.** No Slack/email integration (none is
   authenticated in this environment anyway). A bug in this pass logs and is swallowed at
   the pipeline call site — it must never fail the overall pipeline run.
5. **Sink-only filtering at write time.** Right before writing, each candidate's member
   pairs are re-checked against their *current* `scenarios.is_coachable` state. Any pair
   already homed to a real coachable scenario is dropped from the write set, never
   disturbed — this is the direct fix for the `cluster_6` destructive-reroute risk.
6. **Cross-run candidate matching uses pair-set overlap, not embedding similarity.**
   Postgres in this codebase never stores vectors (this project's own architecture notes are
   explicit: "no vector columns" in Postgres, vectors live in Pinecone only). So candidates
   are matched across runs by Jaccard overlap of their `member_pair_ids`, reusing the same
   overlap-matching technique `replay_layer_c_admitted.py::_match_milestones` already
   validated for this exact "did this cluster reappear under a different ID" problem — not
   by storing or comparing centroid vectors.

## New state: `response_taxonomy_candidates`

```sql
CREATE TABLE IF NOT EXISTS response_taxonomy_candidates (
    candidate_id SERIAL PRIMARY KEY,
    label TEXT NOT NULL,
    description TEXT NOT NULL,
    member_pair_ids INTEGER[] NOT NULL,
    consensus_count INTEGER NOT NULL DEFAULT 1,
    first_seen_run_id TEXT NOT NULL,
    last_seen_run_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'tracking',  -- tracking | graduated | discarded
    graduated_scenario_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Lives in `db/schema.sql` alongside the existing `CREATE TABLE IF NOT EXISTS` /
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern this file already uses for incremental
additions.

Matching rule: for each cluster this run's clustering step judges a real candidate
(`purity_gate_verdict` doesn't skip it, and Gemma's `PROMPT_SINK_POOL_TRIAGE` verdict is
`new_coachable_topic`), compute its `member_pair_ids` and compare against every existing
`status = 'tracking'` row's `member_pair_ids` via Jaccard similarity. A similarity
`>= response_taxonomy_candidate_match_overlap` counts as the same candidate reappearing:
update that row's `member_pair_ids` to this run's set, increment `consensus_count`, update
`last_seen_run_id`. No match inserts a new `tracking` row at `consensus_count = 1`.

**Idempotency guard:** if a row's `last_seen_run_id` already equals the current run's
`run_id`, do not increment again (protects against a no-op re-run of the same transcript
set, which reuses the same `run_id` and would otherwise double-count).

## Per-run algorithm

New module `Brain/response_taxonomy_auto_pass.py`, with a single entry point
`run_auto_pass(config, conn, run_id)`. Called from `v2/pipeline.py` immediately after
`run_layer_c_v2` completes, wrapped in a try/except at the call site that logs and swallows
any exception — this pass must never fail the overall pipeline run.

If `config.layer_a.response_taxonomy_auto_pass_enabled` is `false` (the default), log
"disabled" and return immediately — no clustering, no Gemma calls, no DB reads beyond the
config check.

Otherwise, each run:

1. **Cluster the sink pool.** Reuses the clustering/pair-loading logic already built for
   `dry_run_response_taxonomy.py` (`_load_all_pairs` / `_cluster_corpus` / `_build_records`),
   extracted into `shared/response_taxonomy.py` so the dry-run script and this auto-pass
   share one implementation instead of duplicating it (same precedent as extracting
   `build_clause_pool` during the earlier sink-pool diagnostic work). The dry-run script is
   updated to import from the new shared module; its own CLI behavior is unchanged.
2. **Filter to real candidates.** `purity_gate_verdict` per cluster, then the same batched
   `PROMPT_SINK_POOL_TRIAGE` Gemma call (reused verbatim) on survivors. Only
   `new_coachable_topic` verdicts become candidates for tracking.
3. **Match/track** each candidate against `response_taxonomy_candidates` as described above.
4. **For any row whose `consensus_count` just reached or exceeded
   `response_taxonomy_consensus_runs`** and whose `status` is still `tracking`:
   - Re-query each `member_pair_id`'s *current* scenario via
     `kb_pairs.scenario_id -> scenarios.is_coachable`. Drop any pair that is not currently
     sink-bound (`is_coachable = true` means it's already correctly homed — leave it alone).
   - If no pairs survive filtering, set `status = 'discarded'`, log why, stop.
   - Recompute support stats for the surviving pair set (live `COUNT(DISTINCT call_id)`
     scoped to exactly those pairs — the same pair-scoped recomputation
     `graduate_sink_topics.py` already does, not the mixed-population figures from any
     earlier measurement).
   - Run `passes_reconciliation_gate` against the surviving set. Fail → `status = 'discarded'`,
     log why, stop.
   - Pass → generate scenario metadata via `PROMPT_GRADUATE_SINK_TOPIC` (reused verbatim),
     then write, wrapped in **one explicit transaction** (autocommit temporarily off for
     this block): `INSERT` the new scenario, `UPDATE kb_pairs` for the surviving pair set,
     verify the update rowcount matches the surviving pair count, and only then commit;
     any mismatch or exception rolls back instead of committing first and raising after
     (fixing the non-atomic gap flagged in `graduate_sink_topics.py`'s final review — there
     is no human left here to notice a partial write).
   - On success: `status = 'graduated'`, `graduated_scenario_key` set, then call
     `v2.layer_c.run_layer_c_v2` scoped to the new scenario so it gets a rubric immediately
     (mirrors `graduate_sink_topics.py`'s existing behavior).
5. **Log every event** — candidate found, consensus state change, graduation, discard (with
   reason), error — to `Brain/response_taxonomy_auto_pass.log`, one structured record per
   event.

## New `tuning.yaml` keys

All three are pre-registered starting points, documented as such — not fitted values, same
discipline as `response_taxonomy_purity_gate`'s own comment.

```yaml
layer_a:
  response_taxonomy_auto_pass_enabled: false      # off until explicitly turned on
  response_taxonomy_consensus_runs: 3             # consecutive appearances required to graduate
  response_taxonomy_candidate_match_overlap: 0.5  # Jaccard threshold for "same candidate reappeared"
```

## Testing

Same mocked-connection discipline as `test_graduate_sink_topics.py` — `unittest.mock.MagicMock`
throughout, no real DB writes in tests. New file `test_response_taxonomy_auto_pass.py`:

- Disabled flag → no-op; nothing read beyond config, nothing logged as an event.
- New candidate, no existing match → inserts a `tracking` row at `consensus_count = 1`.
- Matching candidate (overlap ≥ threshold) → increments the existing row, does not insert
  a duplicate.
- Same `run_id` seen twice for the same row → does not double-increment.
- Consensus threshold reached, all member pairs still sink-bound → proceeds through the
  reconciliation gate to a write.
- Consensus threshold reached, some member pairs already re-homed elsewhere → those pairs
  are excluded from the write set; the write only touches the sink-bound survivors.
- Consensus threshold reached, zero pairs survive filtering → `status = 'discarded'`, no
  write attempted.
- Reconciliation gate fails on the surviving set → `status = 'discarded'`, no write.
- Simulated write failure (rowcount mismatch) → transaction rolls back; row remains
  `tracking`, is never incorrectly marked `graduated`.
- Exception raised anywhere inside `run_auto_pass` → caught and logged at the (simulated)
  pipeline call site; does not propagate.

## Explicitly out of scope

- Any cadence throttle beyond the single enabled/disabled boolean (e.g. "every Kth run").
- Slack/email/any external notification — none is authenticated in this environment.
- Retroactively re-evaluating already-`discarded` candidates (a discard is terminal; if the
  same underlying content resurfaces as a fresh cluster later, it starts a new tracking row).
- Backfilling `response_taxonomy_candidates` from the manual runs already performed by
  `graduate_sink_topics.py` or `dry_run_response_taxonomy.py` — this table only starts
  accumulating state once the auto-pass is enabled and a pipeline run actually executes.
- Tuning the three new config values against real measured data — they are starting points
  only, exactly like `response_taxonomy_purity_gate` was when first introduced.
