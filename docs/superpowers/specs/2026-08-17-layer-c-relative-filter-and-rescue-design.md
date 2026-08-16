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

## 7. RESULTS

### 7.1 Instrument (G-T1a): WEAK — every relative rule discriminates, none clears 25pp

Run 2026-08-17, seed 42, clean2_base, 26 coachable + 125 sinks, 3,977 pairs, 12,809 distinct
clause texts, zero spend. Blind audit of the harness returned CLEAN before anything ran.

| rule | param | real | permuted | gap (pp) |
| --- | --- | --- | --- | --- |
| p40 (production) | — | 0.600 | 0.600 | **−0.0** |
| rank | 1 | 0.162 | 0.052 | 11.0 |
| rank | 3 | 0.333 | 0.153 | 18.1 |
| rank | 5 | 0.448 | 0.247 | 20.1 |
| **rank** | **8** | **0.587** | **0.386** | **20.0** |
| margin | 0.90 | 0.814 | 0.669 | 14.6 |
| margin | 0.95 | 0.464 | 0.261 | 20.3 |
| margin | 0.98 | 0.259 | 0.106 | 15.3 |
| demean | 0.00 | 0.744 | 0.581 | 16.2 |
| demean | 0.01 | 0.616 | 0.423 | 19.3 |
| demean | 0.02 | 0.485 | 0.286 | 19.9 |
| demean | 0.03 | 0.371 | 0.183 | 18.9 |
| csls | 1 | 0.120 | 0.038 | 8.3 |
| csls | 3 | 0.255 | 0.112 | 14.2 |
| csls | 5 | 0.350 | 0.176 | 17.5 |

- **The p40 row is the defect, measured symmetrically: 60.0% survival on BOTH arms, gap 0.**
- **Every per-clause relative rule discriminates where the percentile cannot** — gaps 8–20pp.
  The frame claim from the Layer B trial is confirmed.
- **G-T1a = WEAK** (best eligible gap 20.0pp at `rank(8)`, real survival 0.587; PASS needed
  25pp). Per the frozen gate: downstream runs, adoption claims barred.
- **Full CSLS UNDERPERFORMS plain rank here** (8.3–17.5pp vs 11–20.1pp): with only 26 target
  scenarios, the scenario-side hub-correction term costs more than it corrects. The hubness
  diagnosis was right about the FRAME (subtract the per-clause offset / rank within the
  clause); the literature's full correction is tuned for 200k-word vocabularies, not 26
  classes. DEMEAN (the clause-side-only correction) tracks rank closely, as expected.
- Structural reading of the ceiling: a permuted clause still survives rank(8) 38.6% of the
  time — mis-routed content is often topically adjacent to 8-of-26 scenarios, so a
  ~20pp gap may be near the ceiling this taxonomy's granularity allows.

### 7.2 Downstream (G-T1b): PASS — Layer C is routing-quality-sensitive under the rule

F0 PASSED first: the harness's real/p40 arm reproduces the published control exactly
(171 milestones / 26 scenarios, evidence tuples byte-equal), so everything below is
reportable.

| arm | filter | milestones | surviving clauses |
| --- | --- | --- | --- |
| real / p40 | percentile | 171 | 7,929 |
| perm / p40 | percentile | 130 | 7,929 (ratio **1.000**) |
| real / rank(8) | relative | 155 | — |
| perm / rank(8) | relative | 94 | ratio **0.658** |

- **G-T1b PASS**: p40's permuted/real volume is 1.000 (the blindness, reproduced to the
  third decimal); rank(8)'s is 0.658 ≤ 0.75. **A per-clause relative rule makes Layer C's
  intake sensitive to routing quality, which no production defence currently is.**
- Milestone counts (secondary): permuted routing costs 24% of milestones under p40 but 39%
  under the rule.
- **The sample read cuts the other way, and it is the finding that shapes adoption.** Of 20
  clauses REMOVED by rank(8) but kept by p40, most are substantive and on-topic ("we have a
  dedicated partnerships team at Indeed", "rec IDs reposted on Workday need manual
  update") — broadly-relevant clauses that rank home below 8 of 26 overlapping scenarios.
  Of 20 KEPT by rank(8) but removed by p40, most are filler whose weak preference points
  home ("That sounds good.", "So, yeah,"). **The two filters fail on opposite axes: the
  percentile rejects junk and is blind to routing; the relative rule rejects mis-routing
  and is blind to junk.** Neither is a replacement for the other.
- POST-HOC (labelled, not pre-registered, `lcfr_posthoc_conjunction.py`): the conjunction
  p40 AND rank(8) survives real 0.472 / permuted 0.309 — gap 16.3pp with the junk excluded.
  Retention sits below the 50% eligibility floor, so a conjunction (or rank at a looser K)
  needs its own pre-registration; this number is its input, not its result.

### 7.3 T2 (G-T2): the read gate PASSES 12/12 — and the mechanism still cannot do the job

Rescue admitted 1,043 of 3,288 noise clauses (31.7%) into 204 clusters. Placebo counts
matched per cluster by construction (asserted).

- **G-T2 PASS: the independent blinded reader chose the rule's additions 12/12, zero ties**
  (sign test p = 0.0005; gate was ≥10). Replicates Layer A's 10/10 at milestone granularity.
  The p25-of-member-cosines selection rule genuinely admits on-move content.
- **And it does not deliver the outcome it was ranked #3 for.** Gained milestones: rescue 0,
  placebo 1. Per the placebo audit (subagent, hostile, artifact-level recomputation): only
  33 of 204 clusters were base-failing, and the rule routed **7 of 1,043 admissions (0.7%)
  into failing clusters** — nearest-centroid admission structurally favours big, dense,
  already-passing clusters. Exactly ONE cluster in the whole run received adds ≥ its
  deficit; the placebo's 4 uniform draws happened to carry 3 new distinct calls and flipped
  it, the rule's 4 on-topic adds came from calls already in the cluster. "0 vs 1" is a
  coin-flip event, not a treatment difference.
- **Account-diversity lift: null in both arms** (rescue 4↑/8↓/13 tie p=0.39; placebo
  5↑/10↓/10 tie p=0.30; rev-4 metric, weighted null 6d3a2ba9e5894719, reproduced
  independently by the auditor).
- **A claim made mid-session is WITHDRAWN after audit:** the added content is NOT more
  account-concentrated than random. The published medians (rule 0.50 vs placebo 0.33 vs
  originals 0.23, over distinct added CALLS) are a small-n quantization artifact — exactly
  the arithmetic minima for 2 vs 3 distinct calls. Conditioned on distinct-call count the
  arms are identical; pooled N_eff 26.5 vs 25.4 over 82 accounts. The real mechanism is
  **same-call gluing**: 68.6% of the rule's adds land on calls already among the cluster's
  members (41 literal duplicate texts), vs 51.4% for placebo. The rule thickens what is
  already thick — new distinct calls added: rule 243 vs placebo 400 across 89 clusters.

### 7.4 T3 / D1 / D2

- **T3 — honest null at the shipped setting.** Zero scenarios' `required_milestone_support`
  drops under the effective-calls denominator; zero milestones flip. The zero-clause-call
  defect (spec §1) is real arithmetic but does not bind at s0/a0 on this corpus — it goes
  live only when an admission knob (like `a4`) injects near-empty pairs. Handoff item 4 is
  closed for the shipped configuration.
- **D1 — the sink-similarity review flag is the percentile defect, measured.** Within-run
  flag rates: real 5.26%, permuted 5.38% — fixed share by arithmetic, threshold self-adjusts
  (0.7865 vs 0.7880). Cross-applied, fully-random routing raises the flag rate only to
  **9.2%**. Of Layer C's cited "four aggregate junk defences", the two that were measurable
  here are now both measured: the relevance filter rejects nothing (60.0%/60.0%) and the
  sink flag barely notices total mis-routing (5.3% → 9.2%); only the Gemma judge behind the
  flag is absolute.
- **D2 — Layer C's discarded noise is content-equivalent to what it keeps.** Content-free
  shares: HDBSCAN noise 26.3% (n=3,302), clustered-kept 27.3% (n=4,338), gate-failed 26.0%
  (n=289). Sampled noise reads as real expert content ("If it happens to Phenom and Phenom
  to Workday, we're gonna be integrated with both"). Same family as Layer A's diagnostic:
  the loss is in the UMAP→HDBSCAN stage, not in the content. ~42% of the post-relevance
  pool is being discarded at content-parity.

### 7.5 Session verdicts, in one place

| item | gate | verdict |
| --- | --- | --- |
| harness validity | F0 + blind audit | PASS / CLEAN |
| T1 instrument | G-T1a | **WEAK** (20.0pp at rank(8); PASS needed 25) |
| T1 downstream | G-T1b | **PASS** (1.000 → 0.658) |
| T2 selection | G-T2 blinded read | **PASS 12/12** (p=0.0005) |
| T2 outcome | secondary | null — 0.7% of adds reach failing clusters; lift null |
| T3 denominator | none (sizing) | **does not bind** at s0/a0 |
| D1 sink flag | none | near-blind to mis-routing (5.3% → 9.2%) |
| D2 noise pool | none | content-parity with kept (26.3% vs 27.3%) |

Costs: zero chat calls, zero new embeddings, zero Postgres writes. Subagents: 2 audits +
1 blinded reader. Both placebo-anomaly numbers were audited before being believed, and one
interpretation was withdrawn as a result.

## 8. What this cannot answer

- Whether better-filtered or rescued milestones GRADE better (Layer D) — untouched here.
- The Layer C UNIT question (sentences vs whole responses) — deliberately not bundled;
  single-variable discipline.
- `S2` (teammate speech) — needs its own brainstorm, per the handoff.
- Anything at production's bge@768/clause setting: everything here is gemini@3072 turn-mode
  taxonomy. Direction transfers; numbers do not, and no `tuning.yaml` change may cite these
  numbers alone.
