# Layer A clustering methods: can better clusters raise the ceiling?

**Date:** 2026-08-16
**Status:** PRE-REGISTERED — written before any arm was gated. The noise diagnostic
(`calibration/diagnose_layer_a_noise.py`) runs first and reports STRUCTURE only (noise rates,
geometry, probe noise fractions); no arm sees the gate until this spec is frozen.
**Harness:** `calibration/clustering_bench.py` (+ arm registry in the same file), artifact
`artifacts/clustering_bench.json`.
**Spend:** zero chat calls, zero embedding requests (cache-only, abort on miss), zero Postgres
writes. Local compute only.

## 1. Question

Routing is closed: 16 arms, nothing beat the exemplar centroid, and the positive control —
HDBSCAN's own cluster membership — reaches only 21/38 = 55% on the scenario-level
length-matched-null gate. The clusters are the ceiling. Can a different clustering of the SAME
23,949-turn pool in the SAME gemini-3072 embedding space produce materially better coachable
scenario populations, and/or cut the 47% noise rate without degrading the retained clusters?

## 2. What the objective audit changed about this design

`calibration/routing_objective_audit.py` (run before this spec): **each arm family wins under
its own objective** — `description` scores 97% under the description-aligned objective while
centroid arms score 42–53% there, the mirror image of the centroid gate. The gate cannot rank
across population SHAPES. Consequences here:

- Every arm in this trial produces the SAME population shape — hard cluster memberships in the
  same embedding space, transferred to the same keys. Within-shape comparison is the one thing
  the audit left standing.
- The TF-IDF **lexical objective** (aligned with nobody) is reported beside the primary gate
  for every arm as a cheap hedge. Its bluntness is known — the placebo scores 37% under it —
  so it is a direction check, never a gate.

## 3. The gate (primary, frozen before any arm runs)

**Label-transferred `share_fixed`.** For each arm:

1. Cluster the pool (arm-specific). Output: a hard partition of a subset of the 23,949 turns
   into clusters; unassigned turns are the arm's noise.
2. **Label transfer:** each arm cluster maps to the incumbent key (148 keys, sinks included)
   holding the PLURALITY of its members' incumbent labels (labels = the adjudicated clustering
   incl. merged-folded, via `routing_arms.cluster_labels`/`key_universe`; incumbent-noise turns
   carry no label). Ties break to the lexicographically smallest key (determinism). A cluster
   with zero labeled members is UNMAPPED — its turns join no population; the count is reported.
   No mapped-fraction floor: a floor is a knob, and dilution is the gate's job to punish.
3. Coachable population(key) = union of member turns of arm clusters mapped to that key.
4. Score with `null_test_taxonomy.score_population` (length-matched null = the gate null) and
   `size_matched_reference` against the FROZEN incumbent control rows — computed once from the
   incumbent clustering, identical for every arm.
5. Headline: `share_fixed` over the incumbent control's 38 rankable scenarios (fixed
   denominator; a scenario an arm cannot populate to 8 turns is a failure, not a missing
   observation).

**Significance:** paired exact sign test (McNemar) on the 38 scenarios' clear/not-clear
verdicts, arm vs incumbent. "Beats" requires higher `share_fixed` AND two-sided p < 0.05.
The routing bench's own lesson stands: at n=38 a ~12–1 discordant split is needed for p<0.01,
so most small differences will be unresolvable — that is a result, not a defect.

**Why transfer is fair:** the incumbent passed through the same procedure is the identity map
(every cluster overlaps itself totally), so the incumbent's number IS the published control
(21/38). Asserted, not assumed (F2). An arm that merges two real topics dilutes the mapped
population and loses lift; an arm that discards junk shrinks populations toward cleaner cores
and is graded against the (higher-lift) small-size references — the size-conditional reference
handles the coverage/purity trade symmetrically. Known conservative bias, accepted: an arm that
doubles evidence at slightly lower purity can read as "worse"; after the Layer C replay's
merge lessons, conservative is the correct default.

**Secondary columns, reported never gated:** lexical-objective share (audit machinery);
coverage = share of pool in mapped clusters, overall and for substantive turns; content-free
share of coachable populations; junk/subject-bearing cluster counts (<30% / >=70% content-free);
unmapped-cluster count and sizes; population size ranges vs the control's (the reference
extrapolates outside them).

## 4. Success criteria (from the task brief, made operational)

- **S1 (quality):** some arm beats the incumbent — `share_fixed` > 21/38 with sign-test
  p < 0.05, surviving its placebos (section 6) and the reading check (section 7).
- **S2 (noise):** some arm raises SUBSTANTIVE-turn coverage by >= 15 points (incumbent:
  ~40% of substantive turns are clustered) while quality holds — `share_fixed` >= 20/38 AND
  not significantly worse (sign test p >= 0.05 in the worse direction).
- Neither → verdict "the incumbent clustering is the best available", published as such.

## 5. Arms

All arms run on the same pool (`routing_bench.build_pool`), same cached vectors
(`embed_cache_only`, miss aborts), same transfer, same gate. Stochastic arms are seeded; the
seed is recorded.

**Incumbent (control):** production `fit_topic_model` (UMAP seed 42, n_neighbors=15,
n_components=5, min_dist=0) + HDBSCAN(min_cluster_size=16, min_samples=5, eom) + merge 0.97,
verified position-for-position against `adjudicate_gemini_min16.json`.

**Family P — parameter variants (one primary + at most two exploratory).** The primary P arm
is chosen from the diagnostic's HDBSCAN probes by a rule frozen NOW, before the probe results
are read: *pick the probe setting that most reduces the noise rate subject to the junk-cluster
count (>=70% content-free) not exceeding the production baseline's by more than 25% and the
raw-cluster count staying within [100, 600]*. Structure metrics only; no probe ever sees the
gate. If a UMAP variant is needed (n_neighbors=30 is the documented clustering setting), it is
the named exploratory arm `p_nn30`.

**Family G — graph clustering, primary `leiden_knn`.** Exact brute-force k-NN cosine graph
(k=15, matched to production's UMAP n_neighbors — the same neighbourhood scale, not a tuned
value), edges weighted by cosine, Leiden with CPM, `seed=42`. Communities with < 16 members
(the incumbent's own min_cluster_size) are unassigned — the symmetric size floor. CPM's
resolution γ is scale-matched, not gate-tuned: from a log grid, pick the γ whose count of
>=16-member communities is closest to the incumbent's 245 — granularity matching, the same
discipline as scale-matched min_cluster_size. Other γ values are reported as structure only.
Rationale: deterministic given the seed (exact graph, no UMAP), assigns everything (junk
isolates into communities the transfer files under sinks — the "cluster freely, then triage"
shape this pipeline already uses), and it is the standard at this data shape in adjacent
fields (scRNA-seq; Vec2GC beat HDBSCAN on purity on document embeddings).

**Family R — noise rescue (keep the incumbent clusters, add noise turns).**
- `rescue_centroid` (primary): a noise turn joins the nearest surviving cluster (3072-space
  cosine to centroid) iff its cosine >= that cluster's own members' p25 cosine-to-centroid — a
  per-cluster property of the data, no global constant. Mapped key = the cluster's key.
- `rescue_soft` (exploratory): same shape via HDBSCAN `all_points_membership_vectors`; a noise
  turn joins its argmax raw cluster iff its max membership >= the p10 of ASSIGNED points' own
  max membership. (Safe here: soft clustering's documented bugs are with leaf/epsilon; the
  incumbent uses eom, epsilon 0.)
- `rescue_placebo` (mandatory): volume-matched — the SAME number of rescued turns as
  `rescue_centroid`, drawn uniformly from the noise pool, distributed over clusters in
  `rescue_centroid`'s own per-cluster proportions. If `rescue_centroid` does not clearly beat
  this, its result is the volume, not the selection.

**Placebos / controls (every run):**
- `placebo_shuffle`: incumbent cluster sizes kept, membership randomly permuted among the
  clustered turns, then transferred. The is-the-metric-readable floor (expected near
  `placebo_centroid`'s 3.3% analogue). If it scores near the incumbent, the gate is void (F1).
- `jitter_s1`, `jitter_s7`: the incumbent pipeline at UMAP seeds 1 and 7, transferred. The
  re-partition sensitivity band — any treatment must clear the top of this band, not just the
  seed-42 number (the "perturbing a pool at all costs ~6 milestones" lesson, priced in).

**Stretch (run only if memory allows, failure recorded not fatal):** `agglo_cosine` — average
linkage on raw 3072, scipy condensed matrix (~2.3 GB), cut height scale-matched to ~245
clusters of >=16. Fresh process, no spaCy loaded.

## 6. Pre-registered failure conditions

- **F1 metric void:** `placebo_shuffle` `share_fixed` >= incumbent's. No conclusions may be
  drawn from the run.
- **F2 harness bug:** the incumbent transferred through the pipeline does not reproduce its
  published populations exactly (identity transfer) or its `share_fixed` != the control's.
  Run void.
- **F3 H1 fails:** no arm satisfies S1. Verdict: incumbent stands on quality.
- **F4 junk flood:** an arm placing more than 50% of all CONTENT-FREE turns into coachable
  populations is disqualified regardless of gate score — the content-free proxy is symmetric
  and this is the Layer-D-rejection surface the routing spec's F4 protected.
- **F5 seed instability:** a winning stochastic arm re-run at 2 further seeds must keep
  `share_fixed` above the incumbent in both, else the win is withdrawn as seed noise.
- **F6 thin strata:** an arm leaving < 20 of the 38 scenarios rankable is unrankable, not
  comparable (inherited from routing bench).
- **F7 jitter band:** a treatment whose `share_fixed` does not exceed BOTH jitter seeds' is
  indistinguishable from re-partition noise, whatever its sign test says.

## 7. Reading requirement (before any adoption verdict)

For the best-scoring arm and the incumbent: sample 10 clusters each (seeded), present them
BLINDED (arm identity hashed, order shuffled), verdict each as coherent-situation /
mixed / junk, then unblind. A gate win that reads as keyword-glue or account-glue
(the `happy dance` lesson) does not survive. Account-concentration is checked with keyword-
account concentration, not proper-noun-ness (r=0.047).

## 8. What this trial cannot answer

- Whether a better taxonomy IMPROVES Layer D coaching output — nothing downstream of Layer A
  runs here.
- Whether new topics hide in the noise (the transfer gate only sees the incumbent's 38
  scenarios; the noise-recluster diagnostic reports on that separately, unscored).
- Anything about bge/clause production space — this is all gemini@3072 turn mode, like the
  routing bench. No production change may cite these numbers alone.

## 9. Order of operations

1. `diagnose_layer_a_noise.py --stage main` + `--stage noise-recluster` (structure only). DONE
   before arms.
2. Freeze this spec. Select the P arm by the section-5 rule.
3. Build `calibration/clustering_bench.py` + tests for the pure helpers (transfer, placebo
   construction, partition equality). Smoke-test end to end on a subset before the full run
   (the `--sample 2 --reps 1` lesson: py_compile catches neither a bad slice nor a missing
   import).
4. Run all arms in one process where memory allows; agglo in its own process.
5. Read samples (blinded). Write the verdict here as a status update, then CLAUDE.md.

---

## Status update (2026-08-16) — ALL 11 ARMS RUN. `rescue_centroid` SATISFIES S1 AND S2.

Artifacts `clustering_bench.json`, `clustering_bench_members.json`,
`clustering_objective_audit.json`; logs `logs/clustering_bench_*.log`. Zero chat calls, zero
embedding requests, zero Postgres writes, as designed.

| arm | GATE | lexical | description | subst cov | sign p vs incumbent |
| --- | --- | --- | --- | --- | --- |
| **rescue_centroid** | **28/38 = 74%** | 47% | 47% | 67.6% | **0.008 (+8/−0)** |
| agglo_cosine | 22/38 = 58% | 39% | 50% | 56.2% | 0.774 (+7/−5) |
| **incumbent (control)** | **20/38 = 53%** | **61%** | **61%** | 45.1% | — |
| p_eps050 | 20/38 = 53% | 53% | 39% | 49.8% | 1.000 (+2/−2) |
| p_ms2 | 19/38 = 50% | 50% | 34% | 48.8% | 1.000 (+2/−3) |
| jitter_s1 | 17/38 = 45% | 47% | 34% | 43.8% | 0.508 |
| leiden_knn | 16/38 = 42% | 50% | 45% | **98.4%** | 0.344 |
| jitter_s7 | 15/38 = 39% | 45% | 34% | 45.4% | 0.227 |
| p_eps075 *(frozen rule's pick)* | 9/38 = 24% | 34% | 37% | 67.7% | 0.013 (+3/−14) |
| rescue_soft | 5/38 = 13% | 29% | — | 68.2% | 0.000 (+0/−15) |
| rescue_placebo | 3/38 = 8% | 21% | 47% | 67.2% | 0.000 (+0/−17) |
| placebo_shuffle | 0/38 = 0% | 0% | — | 45.1% | 0.000 (+0/−20) |

**Pre-registered conditions:** F1 clear (placebo 0% vs 53%). F2 PASSED — the incumbent's
transfer is the identity map and reproduces the published control **exactly at 20/38**.
F4 clear (max 23.5%). F5 n/a (`rescue_centroid` has no RNG). F6 fires only for
`placebo_shuffle`, which is the placebo working. F7 clear — 74% exceeds the jitter max of 45%.
**S1 and S2 both satisfied by `rescue_centroid` and by nothing else.**

- **The published control was 20/38 = 53%, not the 21/38 = 55% the handoff carried.** Corrected
  against `null_test_taxonomy.json`'s `new_cluster_upper_bound` and reproduced live by the
  incumbent arm. Nothing downstream depended on the difference.
- **The incumbent's 53% sits at the TOP of its own UMAP-seed band (39–53% across seeds 7/1/42).**
  Re-partitioning costs 3–5 scenarios, so the incumbent number is itself seed-flattered — one
  more reason F7 exists and one more instance of the documented UMAP non-reproducibility.
- **The frozen P-rule picked a loser (`p_eps075`, 24%) and that is the pre-registration
  working.** Its probe row already looked bad; the rule was followed anyway and the gate
  judged it. Two of the three P arms landed at or just under the incumbent.
- **`leiden_knn` breaks the coverage/quality trade every other arm obeys.** It assigns 98.4% of
  substantive turns — no noise class, as predicted — and still scores 42%, far above the other
  high-coverage arms (`rescue_soft` 68.2%/13%, `p_eps075` 67.7%/24%). Not a win, but the only
  arm that buys coverage cheaply. γ was scale-matched to 1e-2 (271 communities vs target 245),
  comfortably inside the grid.
- **`agglo_cosine` ran without the feared MemoryError** (2.3 GB condensed matrix) and has the
  cleanest junk profile of any arm (F4 2.3%), but 58% is not significant (p=0.774) and it
  leaves 5 of 38 scenarios unrankable.

### The objective-shape audit, and why it does NOT void the result

`calibration/clustering_objective_audit.py` (new, free, re-scoring only). The charge was
specific and serious: nine arms produce populations by CLUSTERING, but `rescue_centroid` admits
a turn iff `cos(t, centroid_c) >= p25(members)` — it selects members BY the statistic the gate
then measures. The bench's own numbers carry the signature: gate and lexical track each other
across every arm (53/61, 53/53, 50/50, 45/47, 42/50, 39/45, 24/34, 13/29, 8/21, 0/0) and
diverge for exactly one, `rescue_centroid` at 74 gate / 47 lexical.

- Under the **description** objective `rescue_centroid` and `rescue_placebo` score
  **identically — 47% vs 47%, both (+3/−8)** — i.e. similarity-selection appeared worth nothing
  over random selection.
- **That null is explained by the objective's own pre-stated bias, not by the arm.** Gemma wrote
  each description while looking at samples of the INCUMBENT's cluster, so the description
  anchors to the original content and penalises ANY membership change equally. This asymmetry
  was written into the script's docstring BEFORE it ran: *"if a rescue arm WINS here despite the
  anchoring that is strong; if it loses, the anchoring is a sufficient explanation."* It lost;
  the explanation applies. **The description objective measures how much a population CHANGED,
  not whether it changed well**, and both rescue arms change it by identical volume.
- The **lexical** objective, which has no such anchor, DOES separate them: `rescue_centroid` 47%
  vs `rescue_placebo` 21%. It still trails the incumbent's 61% — consistent with added turns
  being on-topic but lexically varied, which lowers TF-IDF coherence while raising semantic
  coherence.

### The reading (section 7) — the treatment beats random 10 out of 10, blind

**The first reading was confounded and is discarded; the mistake is the lesson.**
`rescue_centroid` KEEPS the incumbent's 245 clusters and only GROWS them, so sampling 10
clusters per arm independently compares two random draws from the SAME cluster set. With ~2/3
of clusters being sinks it measured which draw happened to be junk-heavy, not which arm is
better. **For an arm that modifies populations rather than partitions, the unit of reading must
be the modification.**

`calibration/read_clustering_samples.py --added` therefore shows, per coachable scenario, the
turns `rescue_centroid` adds beside the turns `rescue_placebo` adds — same count, same
destination, A/B coin-flipped per item on a fixed seed, arm identity in a separate key file.
Result: **the more on-topic set was `rescue_centroid`'s in 10 of 10 scenarios** (p≈0.002),
including both items where the coin flip put it in slot A. Examples: `managing_uat_and_testing_
phases` drew *"it's a 3 or 4 week testing, UAT kind of time… put in two or 3 use cases"* against
the placebo's audio dropouts; `job_board_distribution_and_publisher_ecosystem` drew *"Indeed has
$3 cost per API call"* and *"Indeed Connect and the API integration"* against *"I've read a bunch
on g two."* **The selection rule admits real content. It is not dilution.**

### Account-glue check (keyword-ACCOUNT concentration, not proper-noun-ness)

Over all 86 coachable clusters where both arms add >= 4 turns, top-account share of the ADDED
turns: `rescue_centroid` 0.365 mean / 0.294 median, `rescue_placebo` 0.221 / 0.200, the
clusters' OWN ORIGINAL members 0.471 / 0.357.

- `rescue_centroid` is significantly MORE account-concentrated than random (57/86 clusters,
  Wilcoxon p<0.0001) — but significantly LESS than the originals it is added to (only 21/86
  clusters get more concentrated, p<0.0001), and produces 5 clusters whose additions are >=80%
  one account against the originals' 17.
- **So the rescue INHERITS account-glue, it does not create it.** Every >=80% case is a cluster
  already documented as account-bound (`implementing_and_maintaining_tracking_pixels` = Uber at
  0.95–1.00 in its originals, `managing_non_technical_stakeholders` = Banfield at 1.00). On
  average it dilutes concentration. Real caveat, not disqualifying, and not new.

### Status update 2 (2026-08-16) — the taxonomy test ran, and the corpus underneath this whole spec was 13.2% contaminated

Two things happened after the verdict below was written. Both change how it should be read.

**(a) `rescue_centroid` was carried into ADJUDICATION and the taxonomy effect is largely null.**
Harness `calibration/adjudication_ab.py`, spec continuation
`2026-08-16-layer-bc-downstream-validation-design.md`. Three arms, cache bypassed, on the
cleaned corpus:

| arm | scenarios | flips vs base |
| --- | --- | --- |
| base_a | 26 | — |
| base_b | 28 | **29/224 = 12.9% (NOISE FLOOR)** |
| rescued | **34** | 28/224 = 12.5% and 23/224 = 10.3% |

- **The treatment flips FEWER clusters than two identical runs do.** On flip rate it is a null.
- **But the scenario COUNT is 6 outside the 26–28 band, because a flip rate discards
  DIRECTION** — noise flips are symmetric (12 merged→scenario vs 10 back, net +2), the
  treatment's are not (12 vs 6, net +6). Any future adjudication A/B must report the transition
  matrix, not the rate.
- **The direction FLIPPED between corpora** — consolidating on the dirty corpus (47→42),
  expanding on the clean one (26/28→34). A robust property of the rule would not do that. The
  taxonomy-shape claim is UNPROVEN; the evidence-breadth claim (96→133 calls per scenario,
  account concentration 29%→21%) is the part that survives.

**(b) THE CORPUS THIS SPEC MEASURED WAS 13.2% NOT-CLIENT-SPEECH, and one of its 38 gate
scenarios was job interviews.** Found by reading the winning arm's clusters — the largest
coachable scenario, **822 turns and 27% of coachable volume, was candidates narrating their
careers**. Removed since: 1,490 interview turns, 1,127 unattributed (`Unknown Speaker`,
dial-ins, bots), 544 Joveo staff misread as client. 23,949 → 20,788 turns.

Consequences for everything above:

- **The 38-scenario control set includes a fake scenario.** `share_fixed` denominators, the
  20/38 control, the +8/+9/+9 seed lift and the placebo comparisons were all computed against
  it. The RANKINGS are unlikely to move — the contamination was present identically in every
  arm, which is what makes within-run comparison survive — but no absolute number here should
  be quoted without this caveat.
- **`rescue_centroid` was partly rescuing interview content.** Its headline cluster grew
  822→873 turns; that cluster was interviews.
- **Cleaning tightened the adjudication noise floor from ±7 scenarios to ±2**, which is why the
  first A/B was unreadable and the second is not. Contamination was not merely junk — it was a
  dominant source of pipeline INSTABILITY, and it was quietly widening the error bars on every
  comparison in this spec.

**What to do with this spec's verdict:** treat "the rescue improves cluster POPULATIONS" as
standing (it rests on blinded reading and on account/call counts, neither of which the
contamination inverts), and treat every share_fixed figure as measured on a corpus that no
longer exists. A re-run of the 11 arms on the cleaned corpus has NOT been done and is not
proposed — the open question moved downstream, to Layer B/C.

### Seed re-test — the F5 gap, found and closed (2026-08-16)

**F5 as written did not fire for the winning arm, and that was a design error.** It requires a
winning STOCHASTIC arm to hold at two further seeds, and `STOCHASTIC` was coded as
`{"leiden_knn"}` because `rescue_centroid` has no RNG. But the arm is deterministic only GIVEN
ITS INPUT, and its input is a seeded UMAP whose own gate score spans 39–53%. Its 74% was
measured on seed 42 alone — the best of the three. **F5 guarded the arm's own randomness and
missed INHERITED randomness; any future rule that post-processes a stochastic stage needs the
same test.** Costing nothing (the jitter memberships were already persisted), the identical
rescue rule was applied to the seed-1 and seed-7 clusters via arms `rescue_centroid_s{1,7}`.

| UMAP seed | base | + rescue | lift | paired sign test (base → rescue) |
| --- | --- | --- | --- | --- |
| 42 | 20/38 = 53% | **28/38 = 74%** | +8 | +8/−0, p=0.0078 |
| 1 | 17/38 = 45% | **26/38 = 68%** | +9 | +11/−2, p=0.0225 |
| 7 | 15/38 = 39% | **24/38 = 63%** | +9 | +9/−0, p=0.0039 |

- **The lift is stable at +8/+9/+9 and is slightly LARGER at the worse seeds** — the opposite of
  what seed luck would produce.
- **Significant independently at all three seeds**, not merely pooled.
- **The ranges do not overlap: rescued 24–28/38 vs base 15–20/38.** The worst rescued seed (63%)
  beats the best unrescued seed (53%) by 4 scenarios.
- Substantive coverage is equally stable — 67.6 / 68.4 / 68.4% against bases of 45.1 / 43.8 /
  45.4% — and F4 stays 10.2–11.9%, so no seed produces a junk flood.

**Consequence for how this result must be cited: report the LIFT, not the level.** 74% was
seed-42-flattered in its level; the effect (~+8–9 scenarios, ~+23 points of substantive
coverage) is a property of the rule and reproduces on every base tested.

### Verdict

**S1 and S2 are both satisfied by `rescue_centroid`, and the result survives every
pre-registered check plus an objective-shape audit and a blinded reading of the treatment
itself.** What the evidence supports is the DIRECTION and the mechanism: admitting HDBSCAN noise
turns back into the cluster whose centroid they already resemble, at a per-cluster data-derived
floor, recovers genuinely on-topic content (10/10 blind) and lifts substantive-turn coverage
45.1% → 67.6% while the gate rises rather than falls.

**What the evidence does NOT support is the MAGNITUDE.** The gate is partly this arm's own
objective function; +21 points is certainly inflated by that alignment, and the one referee with
no such alignment (lexical) still ranks the incumbent first. Treat "rescue_centroid improves the
clusters" as established and "by 74% vs 53%" as an upper bound.

**No production change may cite any of this.** Everything here is gemini-embedding-2@3072 in
TURN mode; production is local bge@768 in CLAUSE mode, where the noise pool, the centroid band
and `merge_cosine_threshold` are all different. The honest next step is to re-run
`rescue_centroid` against the production embedder/unit before proposing a `tuning.yaml` key —
not to ship a rule calibrated in another space.

**Also still open, unaddressed here:** the 47% noise rate is only half-answered — `rescue_centroid`
recovers noise into EXISTING scenarios and cannot create new ones, so the diagnostic's 268
subject-bearing noise-only clusters remain outside the taxonomy by construction of the transfer
gate (section 8).
