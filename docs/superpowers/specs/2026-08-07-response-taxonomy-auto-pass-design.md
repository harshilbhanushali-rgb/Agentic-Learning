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
    stable_pair_ids INTEGER[] NOT NULL,
    consensus_count INTEGER NOT NULL DEFAULT 1,
    first_seen_run_id TEXT NOT NULL,
    last_seen_run_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'tracking',  -- tracking | graduated | discarded
    graduated_scenario_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`stable_pair_ids` added by the amendment below (see "Decision: candidate identity drift") —
`member_pair_ids` is the latest run's raw snapshot (kept for observability/debugging),
`stable_pair_ids` is the running intersection across every run this candidate has been seen
in, and is what actually gets graduated.

Lives in `db/schema.sql` alongside the existing `CREATE TABLE IF NOT EXISTS` /
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern this file already uses for incremental
additions.

Matching rule: for each cluster this run's clustering step judges a real candidate
(`purity_gate_verdict` doesn't skip it, and Gemma's `PROMPT_SINK_POOL_TRIAGE` verdict is
`new_coachable_topic`), compute its `member_pair_ids` and compare against every existing
`status = 'tracking'` row's `member_pair_ids` via Jaccard similarity. A similarity
`>= response_taxonomy_candidate_match_overlap` counts as the same candidate reappearing:
update that row's `member_pair_ids` to this run's set, intersect `stable_pair_ids` with this
run's set (see amendment below), increment `consensus_count`, update `last_seen_run_id`. No
match inserts a new `tracking` row at `consensus_count = 1` with `stable_pair_ids` seeded to
this run's `member_pair_ids`.

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
   - Take the write candidate set from **`stable_pair_ids`** (the intersection across every
     run this candidate has been seen in), not the latest `member_pair_ids` snapshot — see
     "Decision: candidate identity drift" below for why.
   - Re-query each pair-id-in-`stable_pair_ids`'s *current* scenario via
     `kb_pairs.scenario_id -> scenarios.is_coachable`. Drop any pair that is not currently
     sink-bound (`is_coachable = true` means it's already correctly homed — leave it alone).
   - If no pairs survive filtering, set `status = 'discarded'`, log why, stop.
   - Recompute support stats for the surviving pair set (live `COUNT(DISTINCT call_id)`
     scoped to exactly those pairs — the same pair-scoped recomputation
     `graduate_sink_topics.py` already does, not the mixed-population figures from any
     earlier measurement).
   - Run `passes_reconciliation_gate` against the surviving set. Fail → `status = 'discarded'`,
     log why, stop.
   - Pass → generate scenario metadata via `PROMPT_GRADUATE_SINK_TOPIC` (reused verbatim).
   - **Assign `primary_topic_key`** (fixes the gap below) before writing: embed the new
     scenario's `business_description + keyphrases` the same way
     `shared/scenario_vectors.scenario_vec` does, compare it against every existing
     `primary_topics` row's vector (`shared/scenario_vectors.build_primary_topic_vecs`) via
     the new `shared/topic_grouping.match_existing_primary_topic` helper at
     `layer_a.merge_cosine_threshold` (reusing the existing tight-cohesion threshold, same
     precedent as `passes_reconciliation_gate` reusing it rather than inventing a new knob —
     `primary_topics` rows are already tight-cohesion groups post
     `tighten_coachable_groups`, so the tight threshold, not the loose
     `primary_topic_merge_threshold`, is the comparable one). A match reuses that
     `primary_topic_key` (its own aggregate `support_calls`/`support_subtopics`/
     `call_coverage` are left as-is — those fields are display-only, read nowhere else in
     the codebase, so leaving them slightly stale is a documented, low-risk simplification
     rather than a correctness issue). No match creates a new singleton `primary_topics` row
     with zero extra Gemma calls: `label`/`description`/`keyphrases` mirror the new
     scenario's own Gemma-generated metadata, `grouping_method = 'graduated_singleton'` (a
     new tag, distinguishing it from `post_hoc_merge`/`nested_cluster` in an audit trail),
     `support_subtopics = 1`, `support_calls`/`call_coverage` copied from the scenario's own
     just-computed support stats.
   - Write, wrapped in **one explicit transaction** (autocommit temporarily off for
     this block): `INSERT` the new scenario (with its resolved `primary_topic_key`), upsert
     the primary_topics row (existing-match: no-op per above; new: the singleton insert),
     `UPDATE kb_pairs` for the surviving pair set, verify the update rowcount matches the
     surviving pair count, and only then commit; any mismatch or exception rolls back instead
     of committing first and raising after (fixing the non-atomic gap flagged in
     `graduate_sink_topics.py`'s final review — there is no human left here to notice a
     partial write).
   - On success: `status = 'graduated'`, `graduated_scenario_key` set, then call
     `v2.layer_c.run_layer_c_v2` scoped to the new scenario so it gets a rubric immediately
     (mirrors `graduate_sink_topics.py`'s existing behavior).
5. **Log every event** — candidate found, consensus state change, graduation, discard (with
   reason), error — to `Brain/response_taxonomy_auto_pass.log`, one structured record per
   event.

## Fix: `primary_topic_key` orphaning (confirmed gap, not in the original design)

`graduate_sink_topics.py:145` writes `"primary_topic_key": None` for every scenario it
graduates. That is a real, permanent orphan: `primary_topics` is only ever populated once,
inside `v2/layer_a.py::_finalize_primary_topics`, during the main Layer A grouping pass — a
scenario graduated afterward (by either the manual script or this design's auto-pass) has no
later grouping step to go through, so `primary_topic_key` stays `NULL` forever unless
something explicitly assigns it at graduation time. This design's auto-pass must not
reproduce that bug, and `graduate_sink_topics.py` itself gets the same fix applied
retroactively (both call the shared `match_existing_primary_topic` helper — see step 4 above
for the exact mechanism). Any already-graduated scenario from a prior manual run of
`graduate_sink_topics.py` (currently none have been written for real — see the design's own
"Status update" sections; the real write is still pending) would need a one-off backfill if
this fix lands after a real write already happened; as of this writing that backfill is moot
since no real write has occurred yet.

## Decisions on five follow-up risks (raised after the original design was written)

1. **Ambiguous multi-match** (a new candidate's `member_pair_ids` overlaps
   `response_taxonomy_candidate_match_overlap` against two or more existing `tracking` rows
   at once). **Fixed, not deferred.** Match to the single row with the highest Jaccard score
   (`argmax`), never merge two tracking rows into one — this codebase has repeatedly rejected
   speculative-merge behavior (`by_cluster`'s destructive collapses, `blended`'s instability)
   in favor of the more conservative choice every time a similar fork came up, and an
   autonomous, unsupervised pass is exactly the wrong place to introduce a new merge
   mechanism. If a second row's overlap is within `0.05` of the winner, log it at WARNING
   (visibility only, not a blocker) so a human can notice if this starts happening often. Tie
   ties (exactly equal overlap, vanishingly unlikely on real data) break toward the
   lower `candidate_id` for determinism.

2. **Candidate identity drift across the 3 qualifying runs** (each match previously replaced
   `member_pair_ids` with only the latest snapshot, with no check that the "same" candidate
   stayed coherent run to run — a real risk given this codebase's own documented
   UMAP+HDBSCAN run-to-run instability, e.g. 241→403→398→404 milestones for one identical
   corpus). **Fixed, not deferred.** Added `stable_pair_ids`: the running intersection of
   every `member_pair_ids` snapshot seen since `first_seen_run_id`. Each match sets
   `stable_pair_ids = stable_pair_ids ∩ this_run_pair_ids` (first sighting seeds it to that
   run's full set). Graduation uses `stable_pair_ids`, not the latest raw snapshot — so a
   pair that only appeared in one noisy run drops out of the write set automatically, and
   whatever *does* get graduated is guaranteed to have been part of this candidate in every
   single one of its qualifying appearances. If `stable_pair_ids` ever empties out before
   reaching consensus, discard immediately (`status = 'discarded'`, reason "stable core
   emptied") rather than waiting for `consensus_count` to reach the threshold on a
   candidate that has already provably lost coherence.

3. **No retroactive re-match of stray pairs elsewhere in the sink pool that would also fit a
   newly graduated scenario.** **Explicitly deferred as a named risk, not fixed.** A pair
   that would fit a just-graduated scenario but didn't land in the winning HDBSCAN cluster
   this run is not swept in — it has to independently cluster with (or near) the same content
   in some future run to ever be considered. Building an active re-match pass now would mean
   re-scanning the sink pool against the new scenario via some similarity cutoff, which is
   precisely the shape of the eight per-pair signal-search rounds and three Layer-B/C
   routing variants this whole investigation already tried and rejected (`response_only`,
   `or_rule`, `blended`, `by_response`, `by_trigger_nonsink`, `by_cluster` among them) — every
   one either over-rescued junk or produced destructive merges. Re-clustering naturally
   re-considers this content on the next run anyway (nothing is deleted, sink-filing is one
   SQL predicate — see the sink-pool-population-diagnostic design's own finding), so stray
   pairs are not permanently lost, only not swept in immediately. Revisit only if a future
   measurement shows a large, persistent population of stray-but-fitting pairs — not
   speculatively now.

4. **The ~47% HDBSCAN-noise ceiling inherited from `_cluster_milestones`** (roughly half the
   sink pool can never even be clustered into a candidate, because `min_cluster_size`
   resolves to 25 by hitting `min_cluster_size_ceiling` at this corpus size — an
   already-documented, still-open finding from the sink-pool-population-diagnostic design).
   **Explicitly deferred as a named risk, not fixed** — this design's own scope boundary
   already calls this "orthogonal to this design" (see Out of Scope in the sibling gap-design
   doc), and fixing it would mean a separate clustering-parameter calibration effort with its
   own risk of introducing new instability, unrelated to building the graduation mechanism
   itself. The auto-pass simply inherits whatever candidate population the existing
   clustering step produces, noise and all.

5. **No cleanup/expiry policy for `tracking` rows that never reach consensus.**
   **Explicitly deferred as a named risk, not fixed.** A `tracking` row that never matches
   again just sits at its last `consensus_count` forever. This is judged low-risk and
   low-cost to leave alone: rows are cheap (one row per distinct never-matching candidate per
   run, in a table with no downstream reads outside this module), pose no risk to
   `scenarios`/`kb_pairs` (a stale `tracking` row can be at worst mis-matched by
   `Decision 1`'s Jaccard check, which only ever *joins* an existing row, never *acts* on one
   below consensus), and are trivially prunable by hand with a one-off `DELETE` later if this
   ever becomes real clutter. A correct time/run-based expiry policy would need a notion of
   "how many pipeline runs have passed," which does not exist in this codebase today —
   `run_id` is a content hash of the transcript set, not a sequence counter — and inventing
   one solely for this would be exactly the kind of anticipatory infrastructure this
   project's own conventions reject ("don't design for hypothetical future requirements").
   Matches this design's own existing precedent of deferring "any cadence throttle beyond the
   single enabled/disabled boolean" for the same reason: solve it later if it's ever actually
   a problem, not now on spec.

## Status update (2026-08-08): implemented, tested, wired in — not yet run for real

All of the above (the `primary_topic_key` fix and both Decision-1/Decision-2 fixes) is
implemented, mocked-DB tested, and committed:

- `shared/topic_grouping.py::match_existing_primary_topic` (nearest-neighbor primary_topic
  match/no-match).
- `shared/response_taxonomy.py` (new module) extracted from `dry_run_response_taxonomy.py`,
  which now imports from it — CLI behavior unchanged, verified by re-running its own sanity
  checks.
- Three new `tuning.yaml` keys under `layer_a`, all pre-registered starting points, auto-pass
  `false` by default.
- `response_taxonomy_candidates` table (with `stable_pair_ids`) added to `db/schema.sql`.
- `response_taxonomy_auto_pass.py` (new module): Jaccard matching with best-match-only
  resolution (Decision 1), `stable_pair_ids` intersection tracking (Decision 2),
  `primary_topic_key` resolution reused by both this module and `graduate_sink_topics.py`
  (the confirmed gap fix), and the transactional graduation write (rollback on any rowcount
  mismatch, never commit-then-raise).
- `graduate_sink_topics.py:145`'s `primary_topic_key = None` replaced with a call to the
  same resolution helper — the dry-run code path is untouched (the fix only activates on a
  real, non-dry-run write, since dry-run returns before the `row` dict exists).
- Wired into `v2/pipeline.py`, immediately after `run_layer_c_v2`, inside a try/except that
  logs and does not propagate.

219 tests pass (up from 168 at the start of this work), including new coverage for: the
`primary_topic_key` fix (both in `response_taxonomy_auto_pass.py` and retroactively in
`graduate_sink_topics.py`), ambiguous multi-match resolution, `stable_pair_ids` drift across
3 simulated runs, the idempotency guard, all three discard paths (zero survivors,
reconciliation-gate failure, stable-core emptying), the transactional rollback on a rowcount
mismatch, and the disabled-flag no-op. No test in this pass opens a real database connection
or makes a real Gemma call — all mocked, per the stated constraint.

`response_taxonomy_auto_pass_enabled` remains `false` in the real `tuning.yaml`. The real
run against the live `public` schema — preceded by a `baseline_<date>` schema snapshot, run
in the foreground with logs captured, and followed by a before/after analysis — is a
separate step gated on the human partner's explicit go-ahead, not part of this
implementation pass.

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
- **New candidate overlaps two existing `tracking` rows above the overlap threshold** →
  matches the higher-Jaccard row only; the other row is untouched (Decision 1).
- **`stable_pair_ids` intersection across 3 runs with a drifting member set** (run 1:
  `{1,2,3}`, run 2 matches with `{2,3,4}`, run 3 matches with `{3,4,5}`) → the row's
  `stable_pair_ids` ends at `{3}` and that is the exact set graduation is attempted on, not
  the run-3 raw snapshot `{3,4,5}` (Decision 2).
- **`stable_pair_ids` empties out before consensus is reached** → `status = 'discarded'`
  immediately, without waiting for `consensus_count` to reach the threshold.
- **`primary_topic_key` resolution**: a new scenario whose embedding matches an existing
  `primary_topics` row above `merge_cosine_threshold` reuses that key and does not insert a
  new `primary_topics` row; a new scenario with no close match gets a fresh singleton
  `primary_topics` row (`grouping_method = 'graduated_singleton'`) and that key.

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
