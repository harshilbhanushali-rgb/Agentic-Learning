# Expanded-pool stage 1 — was DATA the constraint? (2026-08-17, evening)

**Status: PRE-REGISTERED. Gates frozen in this file BEFORE any arm ran.**
Handoff: `Brain/HANDOFF_EXPANDED_POOL_2026-08-17.md`. Harness:
`calibration/expanded_pool_stage1.py` (new, per operator preference). Tests:
`tests/test_expanded_pool_stage1.py`. Zero chat calls, zero Postgres writes, embeddings
cache-only (shim aborts on a miss). `recordings/` is never written to; `recordings_pull_keep/`
is read-only input.

## 1. Question

Every Layer B/C mechanism tried this week closed with pre-registered nulls or capped gains,
and the standing hypothesis is that **data, not method, was the constraint**. 690 new KEEP
calls (120 new client accounts, +36,978 client turns) are staged. Does adding them — with
NOTHING else changed — move the one metric nothing has ever moved: the rev-4 cluster
account-diversity lift?

## 2. Arms

- **Control** = the PUBLISHED `layer_bc_s0a0r0_b.json` (171 milestones / 26 scenarios,
  taxonomy `clean2_base`, corpus_sha `870b46b3b6d10ad6`, seed 42). Not re-run.
- **Union** = one new arm `layer_bc_xp_union.json`: taxonomy `clean2_base` FROZEN (26
  coachable + 125 sinks; new calls may only JOIN existing scenarios, never create any);
  pairs = production `extract_pairs` (s0/a0) over `recordings/` + `recordings_pull_keep/`
  (each dir parsed with `parse_corpus`, pairs concatenated; stems verified non-colliding);
  routing = production `assign_scenarios` (r0); Layer C Pass 1 = `lcfr_common.pass1_lcfr`
  with the production p40 filter (`describe/judge` stages are Gemma and out of scope, as in
  every arm of this series).

No placebo arm: the treatment is the corpus itself, and the rev-4 metric was built to be
volume-ungameable (the 60%-subsample attack scores 1-of-20 against it). The known ~6-milestone
UMAP repartition floor is applied at the READING of milestone counts instead (G-XP3).

## 3. The null yardstick (decided BEFORE running, because it decides the verdict)

`E[N_eff|k]` must draw from "the corpus's own account mix". The treatment changes the corpus,
so:

- **Control is scored against the PUBLISHED yardstick** `null_draw_weights.json`
  (sha `6d3a2ba9e5894719`, 3,977 pairs / 393 calls) — its published frame.
- **Union is scored against a UNION yardstick** `null_draw_weights_union.json`, built by the
  same production-extraction rule (`build_null_weights.build`) over both dirs, sha recorded.
  This is arm-independent in the sense that matters: it is a property of the fixed union
  corpus, not of any routing choice.
- **Bias direction, stated now:** the union pool has ~120 more accounts, so
  `E[N_eff|k]_union >= E[N_eff|k]_old` at fixed k — the union arm faces a HARDER bar. A
  cluster that gained no genuinely new evidence scores LOWER lift than it did in control.
  A primary PASS is therefore conservative w.r.t. the hypothesis.
- **Sensitivity view (labeled, never the verdict):** both arms scored against the ONE union
  yardstick. This view mechanically flatters the union arm (control cannot reach accounts
  that did not exist in its corpus); it is reported only as a direction check.

Account map = sidecar-derived for BOTH dirs (`flag_proper_noun_clusters.account_map` on each,
merged, then ONE `collapse_sibling_domains` over the union — collapsing per-dir would be an
asymmetric filter). Null tables at `trials=20_000`, `seed=42`, built over the union of both
arms' ks, monotonicity-verified.

## 4. Gates (frozen)

- **G-XP0 — validity (mandatory).** For every coachable scenario, the union arm's PREFILTER
  clause pool restricted to old-corpus calls must be **list-identical (content AND order)**
  to the published control's `clause_pool_prefilter`. Routing of old pairs is deterministic
  and cache-served, so ANY diff is a harness bug. FAIL → nothing else is reportable.
- **G-XP1 — interpretability / stop rule.** New-pair sink share must be **< 0.75** (control
  corpus published 57.9%). At >= 0.75 the new corpus is talking about things this taxonomy
  does not know; stage 1's data-effect verdict becomes NOT TESTABLE ON THIS TAXONOMY (the
  run still completes — it is free — and the routing readout becomes the finding).
- **G-XP2 — PRIMARY (the decision gate).** Rev-4 paired sign test on per-cluster
  account-diversity lift, joined on `cluster_id`, control-vs-union, each arm against its own
  yardstick (section 3):
  **PASS = p < 0.05 AND net > 0 AND the same-yardstick sensitivity view agrees in direction
  (up > down).** Anything else = NULL. One primary test; no multiplicity to correct.
  Per the handoff: a PASS means data was the constraint and promotion of the 690 into
  production is justified; a NULL is a real result — the clusterer eats evidence faster than
  data can supply it, raising stage 2's stakes.
- **G-XP3 — milestone accounting (secondary, directional, no pass/fail).**
  `layer_bc_arms.match_milestones` (merge-aware, both available_frac channels) vs the
  published control. Counts read against the ~6-milestone repartition floor; DIRECTION of
  flips reported, never a rate. Gains classified:
    * `new_data_necessary` — support falls below `required_support` when new-corpus calls
      are removed (the milestone could not exist without the new data);
    * `new_account_backed` — >= 1 supporting call from an account absent from the old
      corpus's account map (honest gain) vs repeat-account-only (padding).

## 5. Readouts (descriptive, pre-registered so they cannot be cherry-picked later)

1. **Routing of new pairs**: sink share old-vs-new (diff the filtered lists — symmetric
   filtering check), absorption top-5 coachable, distinct new calls and NEW accounts reaching
   each scenario, match-width distribution, top1-top2 margins.
2. **support_frac distributions** control vs union (support as a fraction of each arm's own
   scenario call count — raw counts are not comparable across arms).
3. **The 33 failing clusters' fate.** Baseline inventory = `layer_bc_lcfr_real_p40.json`'s
   `candidates_pregate` with `support_calls < required_support` (that artifact is the
   F0-proven byte-identical replication of the control). Identity across arms is by
   same-scenario + overlap of `support_call_files∩old-corpus` (candidate clause lists were
   never persisted — stated caveat, this readout is descriptive only). Report: how many
   failing candidates now clear the (larger) union `required_support`, how many scenarios
   flip `fallback_no_support` → `clustered`, and the direction of pre-gate candidate counts.
4. **k / N_eff / lift distributions** per arm (`score_distribution`), plus
   `compare_arms(field="neff")` as the raw companion view, plus `pool_coverage` and
   `unaccounted_rate` per arm (roster-coverage asymmetry check: new-corpus sidecars may
   resolve accounts at a different rate than old — reported, and if accounted_frac differs
   by > 10pp between arms the primary is flagged as roster-confounded).

## 6. Provenance

Artifact carries started_at / pid / seed / width / corpus_sha (union) / taxonomy_sha /
full layer_c tuning block / both weights_shas / origin split (n old pairs, n new pairs).
No published artifact is overwritten; `--overwrite` exists only for the union artifact
itself with the standard refusal.

## 7. What this CANNOT answer (stated now)

- Whether a REBUILT taxonomy on the union corpus would be better (that is the operator's
  post-stage-2 decision; this stage freezes the taxonomy by design).
- Whether milestone-level gains are coherent moves (blind read is stage 2's instrument).
- Anything about production bge@768/clause-mode: everything here is gemini@3072 turn-mode
  taxonomy + response-clause Layer C; directions transfer, numbers do not.

## Pre-run blind audit (2026-08-17, before any run)

One subagent audit, strict bar, 6 findings — ALL FIXED before the run: (1) CRASH: capture
mode leaked `_centroid` ndarrays into milestone dicts, killing the artifact write at the
last step; (2) CRASH: `table_old` was built over union-frame ks that can exceed the old
pool's drawable size (`expected_neff_table` correctly raises on k>n) — now control-frame ks
only; (3) false G-XP0 FAIL: a scenario with exactly one old pair compared a real pool
against the control's early-exit `[]` — production's <2-responses exit now mirrored;
(4) stale `null_draw_weights_union.json` silently reused — now n_pairs-checked with a hard
abort; (5) `new_account_backed` compared domains across two different sibling collapses,
one-directionally inflating "honest gains" — old domains now mapped through the union
collapse; (6) `score()` bypassed the empty-account-map guard, so missing NEW sidecars would
have manufactured a NULL — now aborts. Clean on: join symmetry, F0 order guarantee, weights
keying, published-artifact safety, yardstick bias direction.

## RESULTS

Run 2026-08-17 night, unattended. `--run` 11.1 min (embed cache fully warm: 58,618 new
clauses + 8,467-pair trigger set verified 0-missing pre-run), zero chat calls, zero
Postgres. Corpus: 3,977 old + 8,467 new = 12,444 pairs over 393+690 calls. Union yardstick
written: `null_draw_weights_union.json` sha `b6bae0af6e245678` (12,444p); published
yardstick untouched. Account map: 111 old → 231 union domains (sibling merges 1 old /
2 union). Report: `artifacts/xp_stage1_report.json`.

- **G-XP0 PASS** — all 26 scenarios' old-restricted prefilter pools byte-identical
  (content and order) to the published control. The union arm is auditable.
- **G-XP1 OK (testable)** — new-pair sink share **64.3%** (5,443/8,467), under the 0.75
  stop bar; old pairs re-sank at their published 57.9% in the same run. 3,024 new pairs
  (35.7%) reached coachable scenarios. Top-5 new-pair absorption:
  `multi_channel_spend_and_board_optimization` 682, `candidate_sourcing_and_data_privacy`
  232, `analytics_and_conversion_funnel` 221, `vip_and_role_segmentation` 214,
  `creative_approval_and_budget_phasing` 203. Match width over the union: 1→9,043,
  2→1,993, 3→1,408. The new corpus routes like the old one, ~6pp more sink-prone.
- **G-XP2 PRIMARY: NULL.** Own-yardstick paired sign test: **up=12 down=13 tie=0
  unscoreable=1, net=+0.913, p=1.0000.** Sensitivity view (shared union yardstick, the
  frame that mechanically flatters union): up=12 down=13, net=+1.869, p=1.0000 — even
  the flattering frame's direction check fails (down > up). Raw N_eff companion:
  **up=20 down=5, net=+89.1, p=0.0041** — clusters really do reach ~3x more accounts
  (k median 26 → 71, accounted_frac 92.8% → 97.4%, gap 4.6pp < the 10pp
  roster-confound bar), but no faster than random draws from the richer 231-account
  pool: lift median actually fell 1.097 → 0.941. Observation for the record: the
  primary and sensitivity frames produced the identical 12/13 split — rescoring control
  on the union yardstick flipped no pair; per-pair gaps dwarf the yardstick shift.
  **Reading: data was NOT the constraint. Doubling the corpus (and doubling its account
  base) moved account reach exactly as much as chance predicts and no more. Promotion
  of the 690 is not supported by this gate (operator's decision). The clusterer eats
  evidence faster than data supplies it — the clustering bench's stakes are raised,
  exactly as pre-registered.**
- **G-XP3 (directional):** milestones **171 → 128** — net DOWN 43, ~7x the ~6-milestone
  repartition floor, so the direction is real, not UMAP noise. Outcomes vs control:
  merged 64, matched 49, lost 45, split 13; gained 60. The gains are honest: 45/60
  `new_data_necessary`, 50/60 `new_account_backed`, only 10 repeat-account padding.
  Per-scenario: 18 down / 2 flat / 6 up; the collapses concentrate where pools grew
  most (`ad_creative_and_keyword_review` 10→3, `budget_timing_and_integration_review`
  11→4) — consistent with fraction-scaled `min_cluster_size` coarsening as pools grow —
  while previously thin scenarios gained (`contract_and_legal_compliance` 0→5,
  `job_feed_data_inconsistencies` 3→10). Added data CONSOLIDATES existing structure
  (merged dominates) rather than revealing new parallel structure.
- **Readout 5.3 (failing clusters):** all 33 baseline failing candidates matched in the
  union arm (≥0.5 old-call overlap); **30 of 33 now clear the union support gate** —
  candidate-level evidence deepening is real — yet **zero** scenarios flipped
  `fallback_no_support` → `clustered` (their scenarios were not the fallback ones).
  Gains at the candidate level, absorbed at the scenario level.

Sample reads done before believing aggregates: gained-milestone clauses are real
Naren-register content backed by genuinely new account domains (appvault.com,
angi.com, cielotalent.com, …) — not join artifacts. Cluster coherence is deliberately
NOT judged here; that is the bench's W4 instrument.
