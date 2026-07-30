# Layer C Rubric Depth — Design Spec

**Date:** 2026-07-28
**Status:** Approved, pending implementation plan
**Scope:** `Brain/tuning.yaml`, `Brain/shared/tuning.py`, new `Brain/dry_run_layer_c_clustering.py`. Possible follow-up to `Brain/v2/layer_c.py` gated on this spec's findings.

## Problem

Rubric depth in the first V2 production run (2026-07-27, `baseline_20260728` vs `v2_alpha_20260728`) is thin: 85 coachable scenarios, median milestone depth 2, 20 scenarios have exactly 1 milestone, 3 have 0. Read-only analysis this session (2026-07-28), verified against the live DB with a reproducibility check (0 mismatches between recomputed and stored milestone counts for all 51 V2-clustered scenarios), found:

- 51/85 scenarios successfully use V2 HDBSCAN clause clustering (evidence-backed milestones, `support_calls` populated).
- 34/85 fall back to V1 Gemma free-text milestones (no clustering evidence — `_fallback_v1` in `v2/layer_c.py` replaces the *whole* rubric, never partially; confirmed 0 mixed rubrics in the DB).
  - **28 of the 34** fall back because HDBSCAN finds **zero clusters** in the relevance-filtered clause pool — the dominant cause (82% of fallbacks).
  - 3 fall back because there are too few Naren responses (<2) or too few clauses (<6) to attempt clustering at all — structurally uncoachable by any clustering approach.
  - 3 fall back because clustering succeeds but every candidate cluster fails the call-support gate (`min_milestone_calls_floor: 3`).
- **Diagnostic on the 28 no-cluster scenarios is the key finding**: HDBSCAN reports 100% noise (zero clusters) at *every* clause pool size observed, from 10 clauses up to 680. Several of the largest scenarios (`implementation_feasibility_requests`: 658 clauses, `niche_industry_role_discovery`: 659, `hypothetical_scenario_validation`: 680) have abundant data and a low `min_cluster_size` (13-14) yet still find nothing. This rules out pure data-sparsity as the explanation for the majority of these 28.
- The leading hypothesis: Layer C's milestone clustering runs HDBSCAN directly on raw 768-dimensional bge embeddings with **no dimensionality reduction**, unlike Layer A's topic clustering (`bertopic` + `umap-learn` + `hdbscan`). Density-based clustering is known to fail in raw high-dimensional space (distance concentration), which is consistent with zero clusters persisting even at hundreds of clauses.
- Separately, lowering `min_milestone_calls_floor` from 3 to 2 was tested against the real cluster candidates (not simulated): it rescues the 3 gate-failure scenarios (1-2 milestones each) and adds exactly +1 milestone to 9 already-clustered scenarios. Net effect: 87 → 101 milestones (+16%) across the 51+3 scenarios it touches. It does **not** affect the 28 no-cluster scenarios, since the gate only evaluates once a candidate cluster exists.

## Design

Two independent tracks. They don't conflict — the call-support gate only fires once a cluster exists, so fixing clustering and loosening the gate address non-overlapping failure populations.

### Track B — adopt the floor change now

Change `Brain/tuning.yaml`:

```yaml
layer_c:
  min_milestone_calls_floor: 2  # was 3
```

Update the surrounding comment block to record this session's measurement in the same style as the existing calibration notes: which scenarios are affected (3 rescued from total V1 fallback, 9 gain +1 milestone each), the net effect (87→101, +16%), and the reproducibility check that validated the recomputation (0 mismatches against the live DB across all 51 V2-clustered scenarios). No code change is needed — `cluster_evidence.required_milestone_support` already takes the floor as a parameter.

This is a pure win for the scenarios it touches: 9 of the 12 affected scenarios strictly gain an additional evidence-backed milestone with no tradeoff. The other 3 (`integration_ecosystem_constraints`, `backend_workflow_conceptualization`, `job_role_specification`) currently have MORE milestones via V1 Gemma free-text (3, 3, 3) than they would via V2 clustering at floor=2 (2, 2, 1) — so this is a quantity-for-auditability tradeoff for those three specifically, worth noting in the comment but not a reason to withhold the change, since evidence-backed milestones are the whole point of V2.

### Track A — diagnose the clustering algorithm

New script `Brain/dry_run_layer_c_clustering.py`, following the existing `dry_run_*` contract (read-only: no Gemma calls, no DB writes, no pipeline mutation — same spirit as `dry_run_layer_a.py` and `dry_run_layer_bc.py`).

**Scope:** the 28 HDBSCAN-no-cluster scenarios, plus a control sample of already-working V2-clustered scenarios (to catch regressions — a variant that "fixes" the 28 by fragmenting the 51 into garbage is not a win).

**Pipeline reuse:** identical segment → embed (cached, no re-embedding cost) → relevance-filter steps already used in this session's diagnostic, stopping short of any Gemma call.

**Variants tested per scenario**, holding the relevance-filtered clause pool and `min_cluster_size` formula fixed:

1. **Baseline** (current production): `metric='euclidean'`, `cluster_selection_method='eom'`, default `min_samples` (= `min_cluster_size`)
2. **Leaf selection**: `cluster_selection_method='leaf'` — trades eom's single-dominant-blob preference for more, smaller clusters
3. **Lower `min_samples`**: `min_samples=2`, `eom` unchanged — decouples core-distance conservatism from `min_cluster_size`
4. **UMAP pre-reduction**: `UMAP(n_components=5, metric='cosine', random_state=42)` → HDBSCAN on the reduced space, `eom`, `min_cluster_size` unchanged. The specific seed value doesn't matter, only that `random_state` is pinned explicitly and documented in the script — UMAP's own stochasticity is a separate concern from the embedding-reproducibility issue already documented in CLAUDE.md (embed_cache.db pins the *inputs*; this pins the *reduction step*).

**Per-(scenario, variant) output:** cluster count, noise fraction, distinct-call support per cluster (same `support_calls` semantics as production).

**Validation, not just counting:** for whichever variant looks most promising, print the actual clause text of the top clusters for a ~10-scenario subsample (mix of previously-no-cluster and control scenarios) so a human reads for semantic coherence before trusting it. This mirrors the existing rule in this codebase that merge/threshold decisions are validated by reading group members (the `--merge-detail` precedent in `dry_run_layer_a.py`), not by cluster counts alone — a variant that turns 100%-noise into incoherent clusters is a false win.

### Decision gate (explicit, not automatic)

Track A produces a **recommendation**, not a code change. If a variant is worth adopting into `v2/layer_c.py`, that requires:

- A new `tuning.yaml` key under `layer_c` (e.g. `cluster_selection_method` or `umap_n_components`)
- A matching field added to `LayerCTuning` in `shared/tuning.py` (the loader raises on unknown/missing keys by design — this is deliberate friction, not an oversight to route around)
- Re-validation that the change doesn't regress the 51 currently-working scenarios

That follow-up implementation is explicitly **out of scope for this spec** — it's gated on what Track A's diagnostic actually shows, which cannot be known until the script runs.

## Track A results (2026-07-28, `dry_run_layer_c_clustering.py`)

**Variant sweep** (28 no-cluster scenarios + 10 controls): baseline and `leaf` rescue 0/28. `min_samples=2` rescues 21/28 but changes 8/10 controls. **`UMAP(n_components=5, metric='cosine', random_state=42) → HDBSCAN`** rescues 26/28 with lower mean noise (37.9% vs 71.4%) — the clear winner, confirming the missing-dimensionality-reduction hypothesis.

**But reading the clauses surfaced a real problem**: UMAP also promotes backchannel to milestone status in the largest scenarios — e.g. `implementation_feasibility_requests` produces a cluster that is just *"That's a good question." / "Does that answer your question?"*, and `advertising_retargeting_strategy_discussion` produces *"Do you have a few moments?"*. Two follow-up knobs were tested to suppress this and **both failed**:

- **`milestone_relevance_percentile` sweep (40/50/60/70/75/80)**: raising it does not remove the junk clusters (they persist as their own dense cluster up to percentile=80) and it actively **destroys good scenarios** — the control `technical_integration_method_discussion` goes from 3 coherent clusters at percentile=40 (including a genuine "what's the job rec ID / URL" milestone) to **zero clusters at percentile≥75**. Backchannel phrases are lexically tight to *each other*, not just weakly related to the scenario, so relevance-to-scenario filtering can't discriminate them.
- **`min_cluster_size_fraction` sweep (0.02/0.04/0.06)** across all 85 coachable scenarios: cluster count drops fast (496→308→233) and noise rises (29.7%→39.9%), but the sink-similarity distribution barely shifts and the *proportion* of junk-flagged clusters actually **rises slightly** (10.1%→16.7%). This knob shrinks yield without improving purity — not an effective lever either.

**Sink-centroid similarity as a review flag (not an auto-filter)**: built sink-scenario description vectors (same space as clause embeddings) and scored each candidate milestone cluster's centroid against them. Across all 496 candidate clusters (current tuning, all 85 scenarios), the similarity band is narrow (p10=0.636 to p95=0.735) — there's no clean separation cliff, so this is a **soft signal, not a hard rule**. At a p95 threshold it correctly flags real junk (*"David's on time off,"* *"Perfect, do you think an hour should suffice, Jim,"* *"Do you have a few moments?"*) but also flags legitimate content (*"When you say default message, would you be able to clarify a little further?"* — a genuine clarifying-question milestone, scores 0.745) and **misses** some junk just under the line (*"That's a good question."* scores 0.733, just below p95). This mirrors Layer A's own `needs_review` precedent: high-signal routes to review, it doesn't auto-delete — the same pattern is the right fit here, implemented as a `review_flag`/`sink_similarity` field stored on the milestone (alongside the existing `support_calls`/`support_clauses`/`relevance_mean` evidence fields), not a rejection filter.

**Full pipeline dry run** (UMAP clustering + current tuning percentile=40/mcs_fraction=0.02 + the Track B floor=2 gate, across all 85 coachable scenarios, review-flag applied but nothing rejected):

- **80/85 scenarios get ≥1 milestone** (up from 51/85 today) — 2 scenarios still produce no surviving milestone, 3 remain structurally uncoachable (too few responses/clauses, unfixable by any clustering approach).
- **Total milestones: 407** (up from 87 today), with 21 (5.2%) flagged for review and 386 clean. Depth distribution: `{0: 5, 1: 7, 2: 14, 3: 10, 4: 8, 5: 4, 6: 8, 7: 10, 8: 9, 9: 4, 10: 3, 11: 2, 12: 1}` — median depth rises from 2 to roughly 4-5.
- **New finding, not previously visible**: 6 scenarios now produce 10-12 raw candidate milestones, at or beyond the existing `milestone_hard_cap: 10` backstop. That cap was calibrated when it "never binds" (0 scenarios hit it under the old algorithm) — under UMAP it would fire regularly. This invalidates the assumption that the cap is a dormant backstop; if UMAP ships, the cap's behavior (rank-by-support-then-truncate) needs to be re-validated as an active mechanism, not just a safety net. **Flagged as an open follow-up, not resolved by this spec.**

**Net assessment**: UMAP is a strong, evidence-backed win for depth (51→80 scenarios, 87→407 milestones). The backchannel-leak problem is real but bounded (~5% by the review-flag proxy) and better solved by flagging for human review than by tuning `percentile` or `min_cluster_size`, both of which were tested and shown ineffective. Shipping UMAP surfaces a second, previously-invisible problem (the hard cap going from dormant to active) that needs its own decision before production adoption.

## Resolving `review_flag`: a batched LLM judge, not a dangling field

A stored flag nobody acts on is not a design, it's a TODO. The resolution mirrors Layer A's existing `NEEDS_REVIEW` precedent exactly: a flagged item isn't left for a human to eventually look at — it gets one Gemma call, in the same pipeline run, and the verdict + one-sentence reason is what's persisted (Layer A's `adjudication_reason`). Layer C's version does the same thing for milestones, with one addition: **batching**, since flagged milestones are sparse (21 of 407 in this run, ~5%) and scattered thinly across scenarios (mostly 0-1 per scenario) — judging them one Gemma call each would be 21 calls for a handful of tokens each, which is exactly the shape `ego_trap/milestone_scoring.py`'s `score_milestones_batch()` already exists to avoid (combining multiple items per call via `GEMMA_BATCH_SIZE`).

**New prompt** `PROMPT_LAYER_C_MILESTONE_TRIAGE_BATCH` (add to `shared/prompts.py`, alongside `PROMPT_LAYER_A_V2_TRIAGE` which it mirrors): takes up to 5 flagged candidates per call. Each candidate carries: `scenario_key`, `sub_topic` (for context), `nearest_sink` (the sink scenario its centroid most resembles — already computed as part of the review-flag score, reused here as a hint rather than recomputed), and its top 3-5 sample clauses. Returns one verdict per candidate: `"genuine_milestone"` or `"mechanics"`, plus a one-sentence reason — same two-value shape as Layer A's `mechanics`/`new_scenario` split, not a third "still unsure" option, so the batch always terminates a candidate rather than deferring it again.

**Control-flow change this requires** (this is the part that pushes past "no code change" — noted here so the eventual implementation plan doesn't rediscover it): flagged-milestone judging must happen **across the whole run, not inside each scenario's per-scenario loop**, or batches of 5 rarely fill (most scenarios contribute 0-1 flagged candidates). That means `run_layer_c_v2` needs a pass split:

1. **Pass 1 (per scenario, no Gemma):** cluster, gate on call-support, compute `review_flag`/`sink_similarity` per surviving milestone — exactly what the dry-run script already does. Flagged candidates go into a run-wide list instead of proceeding straight to `PROMPT_LAYER_C_MILESTONE_DESCRIBE`.
2. **Batch judge (whole run, no DB writes):** chunk the flagged list into groups of 5, one `PROMPT_LAYER_C_MILESTONE_TRIAGE_BATCH` call per group (~5 calls total for 21 flagged milestones, not 21). This mirrors Layer A's own rule of making zero DB calls inside a Gemma loop — the verdicts are held in memory and applied afterward, not written incrementally.
3. **Pass 2 (per scenario):** drop any milestone with a `mechanics` verdict from that scenario's milestone list, then proceed as today — `PROMPT_LAYER_C_MILESTONE_DESCRIBE` runs on the surviving (unflagged + judged-genuine) milestones, rubric gets written.

Unflagged milestones (the ~95% majority) never enter this path at all — they go straight to `PROMPT_LAYER_C_MILESTONE_DESCRIBE` as they do today, so the added Gemma cost is strictly the ~5 batch calls per run, not a cost that scales with total milestone count.

**Storage:** a dropped `mechanics`-verdict milestone doesn't appear in the final rubric, so there's no new column needed on `rubrics.milestones` for the common case. The judge's reasoning for anything it dropped should still be printed loudly during the run (matching this codebase's existing convention for `milestone_hard_cap` binding and V1-fallback triggers) so a reviewer reading the run log can audit what got cut and why, without needing a persisted DB trail for something that affects ~5% of milestones once.

This mechanism is **specified here, not implemented** — same decision-gate boundary as the rest of Track A. Implementing it means: adding the prompt, restructuring `run_layer_c_v2`'s control flow into the three passes above, and adding UMAP + the `min_cluster_size`/`percentile` values (already validated, unchanged) plus the sink-centroid scoring into production code. That's a real, scoped follow-up — worth its own implementation pass rather than folding into this already-large spec.

### Out of scope

- Modifying `v2/layer_c.py`'s production clustering call (deferred to a follow-up spec if Track A recommends a change)
- Any full pipeline re-run, Gemma calls, or DB writes
- Ego Trap (already flagged elsewhere as invalidated by the 148→85 rubric count change; not touched by this work)
- V1 fallback prompt quality (considered and rejected as a primary approach — it doesn't address the 23 of 28 no-cluster scenarios that have substantial clause pools where clustering signal is plausibly being lost to an algorithm limitation, not a data limitation)

## Testing impact

Track A's script is calibration tooling, not production code — same category as `dry_run_layer_a.py`/`dry_run_layer_bc.py`, neither of which is covered by the pytest suite (only the pure functions in `shared/cluster_evidence.py` are unit-tested). No new tests are needed for this spec's deliverables.

If a Track A variant is later adopted into `v2/layer_c.py` (follow-up work, not this spec), and it introduces new pure logic (e.g. a dimensionality-reduction helper), that follow-up should add a corresponding test in `test_cluster_evidence.py`, consistent with existing coverage.

## Amendment (2026-07-28/29): implemented, shipped, then a reproducibility failure surfaced in production

Everything in Track A/B above was implemented: `min_milestone_calls_floor` dropped to 2, `_relevance_filter`/`_cluster_milestones`/the call-support gate landed in `v2/layer_c.py` with UMAP pre-reduction, the sink-similarity review flag was added (`milestone_sink_similarity_percentile: 95` in `tuning.yaml`), and `PROMPT_LAYER_C_MILESTONE_TRIAGE_BATCH` shipped exactly as specified (batched judge, in-memory verdicts, no DB writes inside the loop). 82 pytest tests passed, including 10 new ones covering the pure math (`milestone_cluster_centroid`, `nearest_sink_index`, `review_flag_threshold`).

**The first production run (`run_id=492c7be385c5`) did not reproduce the dry-run prediction.** The dry run above predicted 403-407 milestone candidates with only 21 ever flagged. Production stored only **241 milestones** across the same 85 rubrics — a ~150-160 milestone shortfall the judge mechanism cannot explain (it can only ever remove ≤21). A full investigation (see `CLAUDE.md`'s "Layer C UMAP+HDBSCAN is not reproducible across separate process launches" entry for the complete evidence trail) ruled out config drift, an incomplete/restarted run, and a bug in the kept-list/judge control flow, and instead confirmed: **`umap.UMAP(random_state=42)` does not guarantee byte-identical clustering output across separate process invocations.** Three independent process launches of the identical scenario/code/corpus produced three different milestone counts for `client_availability_and_scheduling_friction` alone (3, then 10, then 8). Two of the three launches (the original dry-run replay and a later full rerun) landed within ~2% of each other (~400 milestones); the first production run was the anomalous outlier, not the other data points.

**Also landed alongside the reproducibility investigation**: milestone-description Gemma calls are now batched (`_DESCRIBE_BATCH_SIZE = 5`, new `PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH` prompt), replacing one `PROMPT_LAYER_C_MILESTONE_DESCRIBE` call per milestone with groups of 5 across the whole run — the same batching pattern as the triage judge, applied to what was the dominant Gemma call count in Layer C. `run_layer_c_v2` is now four passes, not three (cluster → judge → sequence/kept → **batch-describe** → finish). This is a pure performance/cost change; Pass 1 clustering (where the non-determinism lives) is unaffected since it's Gemma-free and runs before any batching decision.

**Still open, deliberately not decided by this spec or its implementation:** what to do about the clustering non-determinism itself. Three options on the table — accept and document the variance, force stricter UMAP determinism (e.g. single-threaded BLAS), or run Pass 1 multiple times per scenario and take a consensus/union of clusters. Snapshots exist for comparison: `baseline_20260728` (pre-rework), `v2_alpha_20260728` (pre-UMAP), `v2_prebatch_20260728` (post-UMAP, pre-batching, 241 milestones — the anomalous run), `v2_postbatch_20260729` (post-batching rerun, 398 milestones).

## Verdict (2026-07-29): overnight full run gives a 4th data point — accept the variance

Per `docs/superpowers/specs/2026-07-29-overnight-full-run-verdict-plan.md`. A full clean Layer A+B+C run was attempted overnight. Three log files exist from the same day (`run_full_pipeline_20260720.log`, `_20260722.log`, `_20260729.log`) — their embedded dates do **not** reflect run order; all three were written 2026-07-29. Only one completed:

- `run_full_pipeline_20260729.log` **crashed** in Layer A: `psycopg.errors.CheckViolation` on `scenarios_bloom_level_check` — Gemma returned `bloom_level="explain"` for `backend_workflow_conceptualization`, not one of the 6 valid enum values, and the upsert had no guard. **Already fixed** (uncommitted, in `shared/storage.py`): `upsert_scenario` now clamps any `bloom_level` not in `_VALID_BLOOM_LEVELS` to `"understand"` and logs a warning instead of raising. The comment in the fix literally cites this exact failure ("Gemma once returned 'explain' instead of 'understand'"), confirming this crash is what triggered the fix. No further action needed beyond committing the pending change.
- `run_full_pipeline_20260720.log` was **interrupted mid-Layer-A** (stops after printing 2 of the adjudication candidates, no traceback, no python.exe process alive afterward). The tail shows a PowerShell `NativeCommandError` from the `2>&1 | Tee-Object` construction — the known PS 5.1 quirk where a native exe's stderr line gets wrapped as an ErrorRecord — plausibly what broke the pipe. Not investigated further; superseded by the successful run below.
- `run_full_pipeline_20260722.log` **completed cleanly** — `RECONCILIATION` block present, 0 unaccounted scenarios, zero `Escalating to next model/key` or rate-limit lines (ran entirely on the primary model). This is the run analyzed below. Verified the live `public` schema matches it exactly, then snapshotted to `v2_overnight_20260729` (416 calls, 158 scenarios, 4605 kb_pairs, 77 rubrics) before any further pipeline runs can overwrite it.

### Headline numbers

- **Scenarios: 158** (78 coachable + 72 mechanics + 8 logistics), same total as every post-rework run to date. `rubric_status`: 77 `rubric_generated`, 1 `skipped_insufficient_responses`, 80 `skipped_not_coachable` — 0 unaccounted.
- **kb_pairs: 4605**, match-width 67% one-scenario / 18% two / 15% three (cap) — close to the previously-recorded production 63%/19%/18%, no red flag.
- **Rubrics: 77, total milestones: 404** (403 clustered via `support_calls`, 1 V1 fallback). Depth distribution: `{0:4, 1:4, 2:10, 3:7, 4:8, 5:7, 6:8, 7:9, 8:8, 9:6, 10:4, 11:1, 12:1}` — median ~5, nothing near the `milestone_hard_cap: 15` backstop (max observed 12).
- 82/82 pytest tests still pass.

### Reproducibility question: answered — 241 was the outlier, accept the variance (option a)

Total milestones across the 4 post-UMAP data points: **241** (original production, `v2_prebatch_20260728`) → **398** (`v2_postbatch_20260729`, batching rerun) → **403-407** (dry-run prediction) → **404** (tonight's independent full run). Three of four land within a 2% band of ~400; 241 is now confirmed the sole low outlier, not a representative sample of the true variance. **Verdict: adopt option (a)** — accept run-to-run milestone-count variance as an intrinsic property of UMAP+HDBSCAN across separate process invocations, and do not invest in forcing determinism. Reasoning:

- The design's actual goal (rubric depth 51→80+ scenarios clustered, ~400 milestones) is met on 3 of 4 independent measurements including this one.
- Forcing single-threaded BLAS has a real, ongoing performance cost for a problem that self-corrects most of the time.
- A consensus/union-of-runs approach (option c) multiplies Gemma + compute cost by N per pipeline run, for a problem that already resolves itself 75% of the time.
- Cheaper mitigation, if desired: log the total milestone count at the end of a run and warn if it falls outside roughly [350, 450] (the observed non-outlier band) — an anomaly flag, not a blocking gate, so a future 241-style run gets noticed without manual DB archaeology.

### New finding: Layer A's clustering geometry reproduced exactly, but its Gemma coachability adjudication did not

Tonight's run and the prior production run (`v2_prebatch_20260728`) both report **"237 raw -> 171 cluster(s)"** at the BERTopic/merge step, and both terminate at 158 final scenarios — the underlying topic clustering is fully reproducible now that `embed_cache.db` is warm (this is a different, better-behaved result than the earlier documented 241→231→226 raw-cluster drift, which happened before the embedding cache was populated).

However, the **coachable/mechanics/logistics split differs**: 85 coachable in the prior run vs 78 tonight. An initial check comparing `scenario_key` string sets found ~76 of 85 "missing" — **this was a false signal**: `scenario_key` is Gemma-generated free text per run (`v2/layer_a.py:269`, `result.get("scenario_key")`), not a stable cluster ID, so the same cluster is routinely renamed between runs (e.g. `stakeholder_role_identification` ↔ `stakeholder_role_mapping`, `candidate_screening_and_prescreening` ↔ `candidate_screening_workflow` — same cluster, different Gemma phrasing). Comparing by `support_calls`/`call_coverage` (a size signature independent of naming) shows the two runs' coachable-cluster size lists are near-identical multisets (e.g. both have clusters of size 319, 309, 268/254, 226, 225, 188, 177...), confirming most of it is the same underlying clustering renamed, not reclassified.

After accounting for the renaming, the real discrepancy is smaller than the naive diff suggested — roughly 7-10 of 158 clusters (~5%) cross the coachable/mechanics boundary between runs, which the prior investigation never measured because it only ever looked at Layer C. **This is a new, previously-undocumented source of run-to-run variance**, distinct from and smaller in magnitude than the Layer C milestone-count issue, but it affects *which topics get a rubric at all* rather than just how deep an existing rubric is. Plausible cause: the per-cluster Gemma adjudication call is run largest-cluster-first and is shown "the top-3 nearest already-accepted scenarios" as context (per `CLAUDE.md`), so early-run stochastic differences can cascade into different accept/reject decisions downstream. **Not root-caused or fixed here — flagged as a follow-up investigation**, out of scope for this run's verdict.

### Quality spot-check: no junk leakage observed

10 rubrics sampled across the full depth range (2-8 milestones) — labels like "Presenting Budget Estimates," "Justifying Source Quality," "Detailing ATS Integration," "Managing Timeline Expectations" — all read as specific, coachable strategic moves with concrete `detection_hint`s tied to actual phrasing, not backchannel or filler. Also checked the edges: the 4 zero-milestone scenarios (one, `client_knowledge_gap`, has a notably large `support_calls=254` for producing nothing — worth a future look, not alarming on its own given the topic's likely content homogeneity) and the two highest-depth scenarios (11, 12 — well under the 15 hard cap). No sign that the higher milestone count vs. the 241-milestone run came from backchannel leaking past the sink-similarity flag / batched judge.

### Concrete next actions

1. **Adopt this run's output (`v2_overnight_20260729` snapshot, now also live in `public`) as the new baseline.** No `tuning.yaml` changes required.
2. **Commit the pending `bloom_level` guard fix** in `shared/storage.py` (currently uncommitted) — it already resolved the crash seen in `run_full_pipeline_20260729.log`.
3. **Optional, cheap**: add a log-line sanity check at the end of `run_layer_c_v2` warning if total milestone count falls outside ~[350, 450], so a future anomalous run is flagged without manual investigation.
4. **New follow-up, not yet scoped**: investigate Layer A's per-cluster Gemma adjudication stability (the ~5-6% coachable/mechanics boundary flips found above) as its own question, separate from the Layer C clustering non-determinism this spec already covers.
5. Do **not** pursue BLAS-pinning or consensus/union UMAP runs (options b/c) — the data doesn't justify the added engineering or compute cost.
