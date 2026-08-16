# Layer C: per-clause relative relevance, milestone noise rescue, and the denominator defect

**Date:** 2026-08-17 (unattended session, continuing `Brain/HANDOFF_LAYER_C_2026-08-17.md`)
**Status:** PRE-REGISTERED. Every gate in §5 is frozen before any harness code exists or runs.
**Cost budget:** zero chat calls, zero new embeddings (cache-only shim, abort on miss), zero
Postgres. Subagents: 1 blind audit of the new harness + 1 independent blind reader for G-T2.

## 1. What this answers

The Layer B redesign closed with F10: Layer C responds to routing VOLUME, not routing QUALITY
— its relevance filter is a percentile and survives exactly 60.0% of anything, and the
separation signal (own-scenario 0.6071 vs random 0.5825, pooled AUC 0.631) drowns in the pooled
frame while being real per clause (78.2% prefer their own scenario). This session tests the two
live Layer C directions the handoff ranks first and third, sizes one known defect, and takes
two free diagnostics nobody has looked at:

- **T1** — a per-clause RELATIVE relevance rule replacing the pooled percentile. The
  literature names the pooled-frame failure: **hubness** — some vectors are near everything,
  so raw cosine ranks are dominated by per-item offsets. The standard correction is **CSLS**
  (Conneau et al. 2018, "Word Translation Without Parallel Data"):
  `csls(x,y) = 2·cos(x,y) − r(x) − r(y)`, subtracting each side's mean similarity to its
  neighbourhood. The rule family below includes rank-based, margin-based, demeaned (one-sided
  CSLS) and full CSLS shapes.
- **T2** — port `rescue_centroid` (validated at Layer A: +8/−0 scenarios, p=0.008, stable at
  3 seeds, blinded read 10/10, placebo collapsed) to milestone clusters: admit an HDBSCAN
  noise clause into its nearest surviving milestone iff
  `cos(clause, centroid) ≥ p25({cos(member, centroid)})`, in the FULL embedding space (the
  Layer A diagnostic showed the loss is in the UMAP→HDBSCAN stage; a full-space rule recovers
  what a UMAP-space rule cannot). The one mechanism that can raise `support_calls`.
- **T3** — size the defect: a call whose response contributes ZERO clauses still inflates
  `scenario_calls` and therefore `required_milestone_support`. Measurement only, no gate.
- **D1** — the sink-similarity review flag is `review_flag_threshold` = a percentile of the
  run's OWN candidate population, so it flags a fixed share of any run by arithmetic (same
  class as the relevance percentile; the Gemma judge behind it is the absolute part). Measure
  whether randomly-routed milestones are flagged at a higher rate than real ones. Report only.
- **D2** — read Layer C's discarded ~45-48% (HDBSCAN noise + support-gate losses): content-free
  share of noise vs clustered clauses (same `is_substantive` proxy as the Layer A diagnostic),
  plus samples. Report only.

## 2. Substrate — one process, production code, free

- Taxonomy `clean2_base` (the Layer B trial's control taxonomy). Corpus `Brain/recordings/`
  (393 transcripts). Pairs via production `extract_pairs` (s0/a0), routing via production
  `assign_scenarios` (r0). Embeddings from the gemini gateway cache at width 3072 through the
  cache-only shim; any miss ABORTS.
- **New harness file** `Brain/calibration/layer_c_relative_filter.py` (T1 + T3 + D1 + D2) and
  `Brain/calibration/layer_c_noise_rescue.py` (T2), per the operator's standing instruction
  this session to prefer new harnesses. They import production functions
  (`build_clause_pool`, `_relevance_filter`, `_cluster_milestones`,
  `cluster_evidence.*`) and the already-equivalence-proven loaders from `layer_bc_arms`
  (`scenario_map_from_rows`, `taxonomy_path`, `install_embedder_shim`, `prewarm`,
  `build_pairs`, `parse_corpus`) — never paraphrases of them. All measurement logic is new.
- **Self-validation (F0):** the harness's `real/p40` arm must reproduce the published
  `layer_bc_s0a0r0_b.json` control per-scenario milestone counts and clause pools exactly.
  If F0 fails, nothing else from the harness may be reported.
- Seed 42 everywhere. One artifact per arm, new filenames (`lcfr_*.json`), never overwriting
  published artifacts.

## 3. T1 design

### 3.1 Instrument stage (no clustering, deterministic)

Mis-routing model: a seeded permutation of `scenario_key` over all coachable-routed PAIRS
(destination multiset preserved — the `r1p`-validated shape; invariants asserted in code).
Each coachable scenario then has a REAL pool and a PERMUTED pool of clauses
(pre-relevance-filter, via production `build_clause_pool`).

Every candidate rule is applied by ONE code path to both pools (symmetric filtering). Reference
set for relative rules: the coachable scenario vectors (`scenario_text`, `concat` mode — the
shipped setting). Rules and sweep grid:

| rule | keep clause iff | grid |
| --- | --- | --- |
| R0 baseline | production pooled percentile (p40) | — (survives 60%/60% by arithmetic; asserted) |
| RANK(K) | own scenario in the clause's top-K by cosine over coachable scenarios | K ∈ {1, 3, 5, 8} |
| MARGIN(m) | `cos(own) ≥ m · max_other` | m ∈ {0.90, 0.95, 0.98, 1.00} |
| DEMEAN(δ) | `cos(own) − mean_j cos(clause, s_j) ≥ δ` (one-sided CSLS, clause side only) | δ ∈ {0.00, 0.01, 0.02, 0.03} |
| CSLS(K) | own scenario in the clause's top-K by full CSLS score (both correction terms, k=10 neighbourhoods) | K ∈ {1, 3, 5} |

### 3.2 Gates (frozen)

- **G-T1a (instrument):** PASS iff some grid point with `survival(real) ≥ 0.50` has
  `survival(real) − survival(permuted) ≥ 25 percentage points`.
  **NULL** iff no grid point with `survival(real) ≥ 0.50` reaches 15 pp. Between 15 and 25 pp:
  reported as weak, downstream stage still runs but any adoption claim is barred.
- **Operating point selection rule:** the grid point maximizing the survival gap subject to
  `survival(real) ≥ 0.50`; ties broken toward higher real survival, then simpler rule
  (R0 < RANK < MARGIN < DEMEAN < CSLS).

### 3.3 Downstream stage (only if G-T1a ≥ 15 pp)

Four arms through identical pass-1 code (cluster → support gate), differing ONLY in
{routing: real | permuted} × {filter: p40 | chosen rule}:

- **G-T1b:** under p40, permuted/real total surviving clause volume ∈ [0.90, 1.10]
  (reproduces the known blindness — a sanity check, its failure voids the stage); under the
  chosen rule, permuted volume ≤ 0.75 × real volume. PASS = both.
- Milestone counts and matched-milestone accounting (`match_milestones`, with the `merged`
  outcome) reported as SECONDARY — UMAP re-partitioning makes counts noisy and the placebo
  lesson says a perturbed pool loses ~6 milestones for free.
- **Read (no numeric gate):** 20 sampled clauses removed by the rule from REAL pools but kept
  by p40, and 20 kept by the rule but removed by p40 — judged on-topic/substantive, reported
  with direction. The harness must not print clause text before sampling (first sight is the
  samples file).

## 4. T2 design

On the real/p40 arm's clustering (labels fixed — the rescue is post-processing; no new UMAP):

1. For each scenario: noise clauses (label −1, post-relevance pool) are candidates. Admit
   clause into its nearest surviving cluster c iff
   `cos(clause, centroid_c) ≥ p25({cos(member, centroid_c)})`, full 3072-space, centroids =
   unit-normalized member means (`milestone_cluster_centroid`).
2. Recompute `support_calls` / `support_call_files` / `support_frac`, then re-apply the
   support gate — so clusters that previously failed can be GAINED.
3. **Placebo:** per cluster, admit the SAME COUNT of noise clauses drawn uniformly (seeded)
   from the same scenario's noise pool. Counts asserted equal in code — the placebo matches
   what the arm ADDS, per-destination.

**G-T2 (frozen):** paired blinded read over 12 sampled clusters where both the rule and the
placebo added ≥2 clauses: each item shows the cluster's original member sample plus slot A/B =
{rule additions, placebo additions}, slot order coin-flipped per item, key written to a
separate file at generation time. Judged by ONE independent subagent reader who has seen none
of this session's code or outputs; question: *which slot's additions belong to this cluster's
move?* **PASS iff the rule wins ≥ 10 of 12** (sign test p = 0.019). My own self-blind read of
the same items is reported as replication, never as the gate.

Secondary (reported, not gated): per-cluster Δ`support_frac` rule vs placebo (sign test);
per-cluster account-diversity lift (the rev-4 metric functions from `layer_b_arms`, unchanged)
rule vs control and placebo vs control, direction + sign test; count and identity of GAINED
milestones per arm; top-account share of added clauses (rule vs placebo vs originals — the
Layer A account-glue check).

**Failure statement (pre-registered):** if G-T2 fails, `rescue_centroid` does not port to
milestone granularity, and the Layer A result is unaffected (different unit, different pools).

## 5. T3 / D1 / D2 (no gates — measurements)

- **T3:** on the real/p40 arm: per scenario, `scenario_calls_effective` = distinct calls
  contributing ≥1 clause post-segmentation (and, reported separately, post-relevance).
  Recompute `required_milestone_support` under each; count candidate clusters that flip
  fail→pass on the SAME clusters (no re-clustering). Read 5 sampled flipped milestones.
- **D1:** compute each arm's milestone-candidate sink similarities against the taxonomy's sink
  centroids; report flag rates within-arm (arithmetic says ~fixed) and CROSS-arm (real arm's
  threshold applied to permuted arm's candidates) — the informative asymmetry.
- **D2:** content-free share (`is_substantive` proxy, min 5 content words) of noise vs
  clustered clauses on the real/p40 arm; 15 sampled noise clauses read; support-gate losses
  counted separately from HDBSCAN noise.

## 6. Guards

- Symmetric filtering: one code path per rule for both arms; permutation multiset and placebo
  counts ASSERTED, not checked afterwards.
- No metric invention: T2's aggregate metric is the existing rev-4 cluster-lift functions.
  The gates here are survival gaps and blinded-read win counts — neither is any arm's
  objective function (the rules select on cosine-to-scenario / cosine-to-centroid; the gates
  are routed-vs-permuted asymmetry and human-judged topical fit).
- Two gated treatments ⇒ any p-value cited for adoption must clear 0.025 (Bonferroni at 2).
- Pure-rule unit tests with SKEWED fixtures (a wrong implementation must fail them) in
  `Brain/tests/test_layer_c_filter_rescue.py`, run before any arm.
- One blind subagent audit of both harness files before the first full run; strict bar
  (outcome-changing, silently-wrong-number, or wasted-run defects only).
- Artifacts carry `started_at`, `pid`, seed, tuning snapshot, and taxonomy/corpus shas —
  the provenance fields the Layer B trial's audit found missing.

## 7. What this cannot answer

- Whether better-filtered or rescued milestones GRADE better (Layer D) — untouched here.
- The Layer C UNIT question (sentences vs whole responses) — deliberately not bundled;
  single-variable discipline.
- `S2` (teammate speech) — needs its own brainstorm, per the handoff.
- Anything at production's bge@768/clause setting: everything here is gemini@3072 turn-mode
  taxonomy. Direction transfers; numbers do not, and no `tuning.yaml` change may cite these
  numbers alone.
