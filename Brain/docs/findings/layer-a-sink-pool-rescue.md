# Layer A — Sink-Pool Population Diagnostic & Response-Taxonomy Auto-Pass (2026-08-05/08)

[Findings index](INDEX.md)

### Sink-pool population diagnostic — the unit of decision was the bug (2026-08-05)

Design: `docs/superpowers/specs/2026-08-05-sink-pool-population-diagnostic-design.md`. Stopped
searching for a ninth per-pair signal and changed the **unit of decision** to the cluster — the unit
Layer A already adjudicates ~200 of instead of judging 74k clauses. Two new read-only scripts
(`calibration/diagnose_sink_pool.py`, `calibration/replay_layer_c_admitted.py`), plus
`v2/layer_c.build_clause_pool` extracted (behaviour-preserving, `tests/test_layer_c_clause_pool.py`)
so the replay reproduces Pass 1 by **importing** production code rather than copying it.
**Nothing wired into production**: `sink_rescue_strategy` stays `none`, `matching_strategy` stays
`flat`, no `tuning.yaml` change, no scenario added, no pair rerouted.

- **Three facts read out of the code reframed the problem, and two of them point away from Layer B.**
  (1) Sink-filing is *one SQL predicate* — `storage.get_naren_responses_for_scenario`'s
  `WHERE p.scenario_key = %s`; nothing is deleted, Layer C just never queries those rows, and it never
  reads the `scenario_keys` array at all. (2) Layer C already has four aggregate junk defenses, and
  `_relevance_filter`'s own docstring names the exact contamination the sink gate is justified by —
  the justification is pre-rework, from the `min_cluster_size=2` 95-milestone era. (3) **`v2/layer_a.py`
  builds the taxonomy from CLIENT clauses only** (line 34 skips every non-CLIENT turn) — responses never
  vote, so an expert behaviour whose client cues are filler-like has *no scenario it could ever be
  routed to*. Fact 3 is why all eight signals were asked an unanswerable question.

- **Half A (cluster the sink pool, three-way Gemma verdict per cluster) separated what eight per-pair
  signals could not.** 1,865 sink-bound pairs clustered against a **volume-matched control of 1,865
  coachable-filed pairs**; 9 clusters, 47.3% HDBSCAN noise. `genuine_sink` 2 clusters/609 pairs,
  `belongs_to_existing` 5/199, `new_coachable_topic` 2/175. Cross-checked against the *independent*
  150-pair per-pair labeled sample the two verdict families agree in the predicted direction —
  21% / 71% / 80% labeled-coachable respectively. Junk concentrates: one cluster holds 535 pairs at 9%.
  Two homeless topics found with real support: `strategic_performance_consulting` (94 pairs/115 calls)
  and `technical_operational_alignment` (81/113) — **direct confirmation of fact 3**.

- **`real_minus_sink_margin` has no relationship to the verdict even at CLUSTER level** (best margin
  +0.036 is `genuine_sink`; −0.015 is `belongs_to_existing`). Cluster-level averaging was the strongest
  remaining embedding idea. **The embedding-signal search is closed, not merely paused.**

- **Half B (three-arm Layer C Pass-1 replay, zero Gemma, all arms in ONE process) is the first time
  this problem was measured against rubrics instead of a per-pair AUC proxy — and it rejected the
  cheapest fix outright.** Baseline reproduced 385 milestones (inside the documented ~[350,450] band,
  so the replay is faithful). **Deleting the sink short-circuit destroys 82 of 385 milestones (21%) and
  its placebo gained MORE than it did (98 vs 84)** — the entire apparent gain is a pool-size clustering
  artifact. `by_response`: 87 lost. `by_cluster` (route only clusters judged `belongs_to_existing`)
  *appeared* to be the only viable method — 383/385 matched, 1 lost vs its placebo's 6 lost / 0 gained,
  with large support jumps read as "evidence thickening". **That reading was FALSIFIED the same day by
  `calibration/check_milestone_thickening.py` — see the next bullet. `by_cluster` is NOT validated and NOT
  recommended.**

- **`replay_layer_c_admitted._match_milestones` is MERGE-BLIND, and it inflated `by_cluster`'s result.**
  It maps each baseline milestone to its best-overlapping arm cluster *independently*, so when N
  baseline milestones collapse into ONE arm cluster it scores N clean "matched + thickened" milestones
  instead of one destructive merge. Measured in `client_requests_operational_visualization`: three
  baseline milestones (45, 54 and 337 clauses; support 22, 28, 112) all matched the *same* 532-clause
  treatment cluster at support 133 — byte-identical clause lists, i.e. three distinct coaching moves
  fused into one blob. **The admitted content was only 15% of that cluster**, so the merge was driven by
  the clause pool growing (2,315 → 3,239) and UMAP re-partitioning — the same mechanism that destroyed
  82 milestones in `by_trigger_nonsink`, just silent. Milestone count went 6 → 7, which is exactly how
  it hid. Two further traps: **support as a raw count is not comparable across arms** (the 112 → 133 jump
  is 73% → 72% *as a fraction of the scenario's calls*, since 31 new calls arrive with the admitted
  pairs), and the dilution indicator that *was* coded (`support >= 90% of all calls`) reported 0/7 and
  missed it entirely — the correct indicator is "do multiple baseline milestones map to the same arm
  cluster". **Any future Layer C A/B must report a `merged` outcome and normalise support by call count.**
  **Fixed and re-run 2026-08-06/07** — see the next bullet for the corrected result.

- **A placebo arm is mandatory for any future Layer C A/B, and "zero milestones lost" is an
  unachievable bar.** Perturbing a clause pool *at all* costs ~6 milestones to UMAP/HDBSCAN sensitivity
  regardless of content quality — so a loss count is only interpretable against a volume-matched
  placebo. The bar as originally written would have rejected a fix that beats the noise floor.

- **`_match_milestones` merge-blindness fixed and Half B re-run against live data (2026-08-06/07) —
  `by_cluster` is far cleaner than the other two arms but still not a clean win, and no method is
  recommended for production.** Fix: a fourth outcome `merged` (2+ baseline milestones claiming the
  same arm cluster mark all of them `merged`, not `matched`), plus support reported as a fraction of
  each arm's own scenario call count. Sanity-tested against synthetic cases (including the exact
  45/54/337→532-clause example above) before the real re-run. **The fix reproduces the prior update's
  own prediction exactly**: `matched + merged` equals the old inflated `matched` count in both rejected
  arms (`by_trigger_nonsink` 172+83=255, `by_response` 172+92=264) — strong evidence the fix measures
  the right thing. Corrected per-arm counts (of 385 baseline milestones): `by_trigger_nonsink` 172
  matched / 83 merged / 48 split / 82 lost; `by_response` 172/92/34/87; `by_cluster` 375/8/1/1.
  `by_trigger_nonsink` and `by_response` are now rejected *more* decisively — roughly a third of their
  apparent matches were destructive merges, some absorbing up to **10 baseline milestones into one
  cluster** (worse than anything in `by_cluster`), confirmed by reading samples (e.g. `by_response`'s
  `budget_and_spend_disclosure` fuses literal filler — "What are you trialing?", "Does that answer your
  question?" — into a real spend-strategy cluster). `by_cluster` beats its own placebo on lost (1 vs 6)
  and gained (4 genuine new milestones — Scale AI partnership, LinkedIn CPC/CPA, landing-page
  follow-up — vs 0), but **not** on merged (8 vs placebo's 0) — its worst case is a previously
  undetected **5-into-1** collapse in `media_channel_and_retargeting_discovery` fusing genuinely
  distinct sub-topics (which job boards, ATS integration, a pricing model, a generic optimization
  claim). **Verdict, unsoftened: no rescue method is validated for production.** `by_cluster` is the
  least damaging by a wide margin and wins its placebo comparison on every axis except merge count, but
  1 lost + 8 merged is nonzero real damage, not proof of a clean fix. Full detail, including the
  multiplicity distributions and verbatim merged/gained samples: design spec's "Status update
  (2026-08-06/07)" section; raw output `Brain/logs/replay_layer_c_admitted_postfix.log` /
  `Brain/artifacts/layer_c_admitted_replay_postfix.json`.

- **The two proposed scenarios are necessary but NOT sufficient, and Half B could not test them.**
  Routing can only place content into scenarios that exist. And adding them alone captures nothing —
  Layer B matches on the CLIENT trigger, and these pairs were sunk *because* their triggers look like
  filler, so a new scenario attracts nothing. They must be paired with cluster-verdict routing, which
  does not depend on trigger matching at all.

- **New open finding, unrelated to sinks: Layer C's relevance filter barely discriminates by topic.**
  Deliberately wrong placebo clauses survived the p40 cut at 53.9-57.2% vs 57.7-63.0% for real rescued
  content — a ~6-point gap on a filter the pipeline leans on to keep off-topic clauses out of rubrics.

- Also open: **47.3% of the sink pool is HDBSCAN noise**, capping any cluster-based fix at ~53% of the
  problem. `min_cluster_size` resolved to 25 **by hitting the `min_cluster_size_ceiling`** (0.02 × 3730
  = 74.6, clamped), so the clustering is coarse — a finer rerun would likely split the 535-pair junk
  cluster and cut noise. Untested.


---

### Response-taxonomy auto-pass: closing the sink-pool gap permanently (2026-08-07/08)

Designs: `docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md`,
`docs/superpowers/specs/2026-08-07-response-taxonomy-auto-pass-design.md`. Full narrative
(problems found, fixes, real-run result) in `Brain/PROBLEMS_AND_FIXES.md`.

Two manual, one-time scripts proved the fix first: `calibration/graduate_sink_topics.py` (graduated
2 known homeless topics from `Brain/artifacts/sink_pool_clusters.json`) and `calibration/dry_run_response_taxonomy.py`
(zero-write corpus-wide measurement, found a 3rd candidate blocked on a field-name mismatch
and non-sink-only membership). This session built the permanent version.

- New module `Brain/response_taxonomy_auto_pass.py` — entry point
  `run_auto_pass(config, conn, run_id)`, called from `v2/pipeline.py` immediately after
  `run_layer_c_v2`, wrapped in try/except that logs and swallows (must never fail the
  overall pipeline run). Gated by `tuning.yaml`'s `layer_a.response_taxonomy_auto_pass_enabled`
  (default `false`, currently `false` in the live file — pending further review after the
  first real run below).

- `Brain/shared/response_taxonomy.py` (new) extracted from `calibration/dry_run_response_taxonomy.py`
  (which now imports from it) — clustering/pair-loading/adjudication shared between the
  dry-run script and the permanent pass, same precedent as `build_clause_pool`'s extraction.

- **Fixed a real orphaning bug, retroactively too:** `calibration/graduate_sink_topics.py` used to write
  `primary_topic_key = None` for every scenario it created — a real, permanent orphan, since
  `primary_topics` is only ever built once, during Layer A's main pass. New pure helper
  `shared/topic_grouping.py::match_existing_primary_topic` (nearest-neighbor match against
  the existing `primary_topics` population) resolves a real key at graduation time instead —
  reuses `merge_cosine_threshold` (existing tight threshold), not `primary_topic_merge_threshold`
  (the loose one), since stored `primary_topics` rows are already tight-cohesion groups.
  Both `calibration/graduate_sink_topics.py` and the new auto-pass call it.

- New table `response_taxonomy_candidates` (`db/schema.sql`): `status`
  tracking/graduated/discarded; `member_pair_ids` is the latest raw cluster snapshot,
  `stable_pair_ids` is the running **intersection** across every run a candidate has been
  seen in — graduation reads `stable_pair_ids`, not the latest snapshot, specifically so a
  pair that only appeared in one noisy clustering run drops out automatically instead of
  riding along. A candidate must reappear (Jaccard overlap of `member_pair_ids`, **not**
  embedding similarity — this Postgres never stores vectors) across
  `response_taxonomy_consensus_runs` (3, pre-registered) consecutive runs before it
  graduates — the same UMAP/HDBSCAN run-to-run instability this file already documents
  elsewhere is exactly why a single run's cluster can't be trusted on its own.

- **The real run (2026-08-08), snapshotted first to `baseline_20260808`:** 3 manual
  invocations against the live `public` schema (no re-clustering of Layer A/C, no re-running
  Layer B — just this pass, standalone). Result: **4 scenarios graduated, 164 pairs rescued
  from the sink pool, `kb_pairs` total unchanged (4,605→4,605), and every one of the 164
  rerouted pairs confirmed `is_coachable=false` before this ran** — i.e. the "never disturb an
  already-homed pair" protection held, verified directly against the snapshot, not assumed.
  Flag reverted to `false` afterward pending further review before letting it run unattended.

- **Hit `IdleInTransactionSessionTimeout`'s sibling bug again, in two new places.** The very
  first real invocation crashed with `SSL connection has been closed unexpectedly` —
  the connection sat idle across the batched Gemma adjudication calls and Neon killed it.
  This is the *exact* existing `storage.reconnect_if_closed` gotcha below, just missed in two
  new call sites (right after `adjudicate_clusters`, and again after `_generate_metadata`
  inside the graduation path) — **any new code path that does a slow Gemma call before
  touching the DB again needs this called explicitly, it is never automatic.**

- **New gotcha, specific to this module:** it's the first Brain script to use a persistent
  `logging` file handler instead of `print()`. That handler is a module-level singleton, so
  pytest runs against the same module silently wrote fake `candidate_id`/`scenario_key`
  entries into the real production log file, unless a test explicitly disables it
  (`monkeypatch.setattr(module._logger, "disabled", True)`).

