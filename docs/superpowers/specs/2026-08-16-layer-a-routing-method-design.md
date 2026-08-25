# Layer A/B routing: can anything beat an exemplar centroid?

**Status:** PRE-REGISTERED 2026-08-16, before any arm was written or run.
**Harness:** `calibration/routing_bench.py` (+ `calibration/routing_arms.py`, `tests/test_routing_arms.py`)
**Artifact:** `Brain/artifacts/routing_bench.json`
**Shipped:** nothing. Any winner lands behind a `tuning.yaml` key defaulting to the current behaviour.

---

## 1. The problem, restated so the method follows from it

A scenario is induced by clustering client turns. Gemma then writes it a
`business_description` + `keyphrases`. **Every downstream consumer — `layer_b`'s primary
`scenario_key`, Layer D's rubric lookup — then throws the cluster away and matches turns
against that prose.** The cluster's own member turns are never used at match time.

Three measurements from 2026-08-15/16 say that hand-off is where the taxonomy leaks:

| measurement | value | source |
| --- | --- | --- |
| round-trip: a cluster's own turns returning to its own scenario | **27.0%** | `roundtrip.log` |
| held-out-by-call routing agreement with cluster membership, description | **25.9%** | `heldout.log` |
| held-out, exemplar centroid | **84.1%** | same |
| coherence-vs-null, share reaching the size-matched control reference | 29% desc / 47% exemplar / **53% cluster** | `null_exemplar.log` |

Of the 3,768 turns that do NOT return to their own scenario, 2,201 go to a *different
coachable* scenario and 1,567 are rejected to a sink. And the top1–top2 margin is ~0.01
cosine in both taxonomies, so winner-take-all is decided by a hair.

**The reframing that picks the candidate list: this is not a zero-shot problem and it has
been solved with zero-shot tools.** Zero-shot classification from class descriptions is what
you do when you have no labelled examples. We have thousands — every cluster member is a weak
label. The literature calls the description route "embedding-based zero-shot", and its
documented failure modes are exactly the three symptoms above: sensitivity to *definition
quality*, *inter-class confusion*, and *data grounding* (the description lives in analyst
register, the turns live in client register). Asymmetric-retrieval work names the same thing
as the **query–document register gap**, and reports the gap collapses when the two sides have
similar length and register — which is the mechanism an exemplar arm exploits.

So the honest statement of the incumbent is not "exemplar routing is a clever trick"; it is
"the shipped method discards the labels it already has." Exemplar centroids are the *first*
and *crudest* way to use them. Prototype-vs-kNN work reports that a single unimodal prototype
under-represents a multi-modal class and that neighbour-based and prototype-based scoring are
complementary. SetFit reports that a plain logistic head over frozen embeddings is a strong
baseline when labels exist. Both say the centroid is unlikely to be the ceiling.

## 2. Hypothesis

**H1.** At least one routing method beats the exemplar centroid's 47% on coherence-vs-null,
without collapsing the reject rate.

**H2 (mechanism, tested separately).** The description arm's deficit is a *register* problem,
not an *information* problem — the description names the right situation but in the wrong
register. If so, closing the register gap while keeping the description's information (mutually
discriminative rewrites; synthetic exemplar utterances, the mirror of HyDE/HyPE) should recover
most of the exemplar gain **without needing cluster membership at match time**, which is what
production would actually have to ship.

**CORRECTION to an earlier version of this paragraph (2026-08-16).** It claimed "an exemplar
router requires storing member turns alongside every scenario forever", and used that to argue
H2 matters more than H1 for shipping. **That is wrong for the arms that actually lead.** The
storage cost differs sharply by arm and was never checked before being asserted:

| arm | what production would have to persist |
| --- | --- |
| `centroid`, `blend_*` | **one 3072-dim vector per scenario** — a column, computed once at Layer A time from data Layer A already holds |
| `submeans` | ≤ 8 vectors per scenario |
| `knn_max`, `knn_topk_mean` | every member turn — genuinely heavy |
| `probe` | a 148 × 3072 weight matrix, refitted every pipeline run |

So a centroid-class winner is cheap to ship. What H2 still buys, and it is not nothing, is
**auditability**: a human can read a description and disagree with it; nobody can read a
centroid. A taxonomy whose routing rests on an opaque vector cannot be reviewed the way
`adjudication_reason` made the coachability call reviewable.

## 3. Arms

Free (cached embeddings, zero spend) unless marked. `desc` = the shipped
`business_description + keyphrases` vector.

| arm | what it routes against | provenance |
| --- | --- | --- |
| `description` | desc vector | **the incumbent floor**, shipped |
| `centroid` | mean of member vectors | **the incumbent to beat** |
| `medoid` | the single most central *real member turn* | prototype selection |
| `knn_max` | max cosine to any member (1-NN) | neighbour-based |
| `knn_topk_mean` | mean of the k=5 highest member cosines | Prototype-Neighbor hybrid |
| `submeans` | max over m k-means sub-centroids within the cluster | multi-modal prototypes |
| `probe` | multinomial logistic head over frozen embeddings | SetFit head, no fine-tune |
| `centroid_desc_blend` | `a·centroid + (1−a)·desc`, a swept | cheap fusion |
| **`placebo_centroid`** | centroids of a RANDOM size-matched partition | **the placebo, see §5** |
| `desc_discriminative` *(costs LLM)* | desc rewritten against its nearest neighbours | contrastive label–embedding alignment |
| `desc_synthetic_utterances` *(costs LLM)* | k generated *client utterances* per scenario | HyDE/HyPE mirror |

Not testable here, recorded so it is not re-proposed: **matched embedding task types.**
`task_type` is inert on the Joveo gateway backend, so both sides already get one symmetric
encoding and there is no asymmetric split to correct.

Orthogonal decision rule, applied on top of the winner rather than as its own arm:
**abstain when the top1–top2 margin is below a derived threshold** (multi-label / reject),
motivated by the measured ~0.01 margin.

## 4. Metrics — all three reported for every arm, none of them alone deciding

1. **Held-out-by-call routing accuracy.** Routers built from TRAIN calls only; scored on
   test-call turns belonging to a coachable cluster. Ground truth is cluster membership.
2. **Coherence vs a length-matched random null**, reported as *share of scenarios reaching
   the size-matched control reference*, using `null_test_taxonomy.py`'s exact machinery
   (`length_matched_null`, `size_matched_reference`, `CONTROL_NEIGHBOURS=7`). Never
   references membership.
3. **Reject rate** — share of turns whose best match is a sink.

**Metric 2 is the gate.** Metric 1's ground truth *is* cluster membership and every
membership-derived arm is built from it, so metric 1 favours those arms by construction. That
is stated here, before the run, so a large metric-1 gap is not later read as a large result.

**Primary mode is HELD-OUT for all three metrics.** Routers are built on train calls, all
three metrics are computed on test-call turns. This is a departure from the scratchpad runs,
which measured coherence full-corpus, and it is deliberate: a `knn_max` arm scored on the full
corpus finds *itself* as its own nearest neighbour and reproduces cluster membership exactly,
scoring the control's 53% while having learned nothing. Full-corpus numbers are also reported,
for continuity with the published 29 / 47 / 53, and must be read as inflated for
`knn_*`/`probe`/`medoid`.

## 5. Controls and nulls — what makes a number readable

- **`placebo_centroid` is the pre-registered placebo and the most important control here.**
  Coherence is *mean cosine to the population's own centroid*. Any router that aims at a point
  lying INSIDE the data cloud carves a compact Voronoi cell and scores well for that reason
  alone, whereas a description vector sits off the turn manifold. So part of the exemplar
  arm's 47% may be "routed to an in-manifold point", not "routed correctly". The placebo
  partitions turns into 38 random size-matched groups and routes to *their* centroids. It has
  no cluster information whatsoever.
- **Positive control** is cluster membership itself (53% full-corpus), carried through
  unchanged from `null_test_taxonomy.py`.
- **The reject rate is a falsifier, not a diagnostic.** It already fired once: a router that
  wins accuracy by accepting everything has destroyed the only junk filter the pipeline has.
- Symmetry: every arm sees the same pool, the same embedder, the same clustering, the same
  train/test split, the same null, the same reference. The one asymmetry is deliberate and
  favours the incumbent — descriptions were written by Gemma from the full corpus, test calls
  included, so the description arm keeps a leakage advantage and the test is conservative.

## 6. Pre-registered failure conditions

Written before any arm ran. Any of these fires ⇒ the stated conclusion is taken, not argued
around.

- **F1 — the metric is void.** `placebo_centroid` reaches ≥ the exemplar arm's share on
  metric 2. Then coherence-vs-null is measuring in-manifold routing, not correct routing, and
  **no arm comparison on metric 2 may be reported at all**, including the already-published
  47%.
- **F2 — the instrument is too hard.** The cluster-membership positive control does not stay
  clearly above every matched arm. Then the null is too hard and nothing may be concluded.
- **F3 — H1 fails.** No arm exceeds `centroid` by more than the run-to-run band on metric 2.
  Then the reported result is *"the obvious fix is also the best available"* and no new
  method ships. This is an acceptable outcome and will be reported as the headline.
- **F4 — a winner destroys rejection.** An arm whose reject rate falls below **half** the
  description arm's is rejected regardless of its other numbers.
- **F5 — H2 fails.** If the two LLM-rewrite arms do not close at least half the
  description→centroid gap, then the deficit is not a register problem, description routing
  cannot be repaired in place, and any exemplar winner must ship as a genuine architecture
  change (storing member turns) or not at all.
- **F6 — thin strata.** Any arm with fewer than 20 rankable scenarios on the held-out gate is
  reported as unrankable rather than compared.

## 7. What is deliberately NOT claimed

- Beating a random null means a population is more than a random pile of turns. It does not
  mean it yields a usable rubric. Nothing downstream of Layer A is exercised.
- Cluster membership is the only ground truth available and the clustering saw the test
  turns. The residual circularity is noted, not removed.
- The length-matched null *reduces* the length confound and does not remove it
  (`corr(lift, mean words)` +0.65 → +0.25/+0.37 by arm). Every result here is
  **length-adjusted**, never length-free.
- Run-to-run band: gemini embeddings are deterministic and the clustering reproduced exactly
  across four process launches, so the join assert (`n_clusters == n_adj_rows`) is the
  reproducibility check. A failure there voids the run rather than being worked around.

## 8. AMENDMENTS after the first run (2026-08-16) — method only, recorded before results

Three changes to the *instrument*. None touches an arm definition, a metric, a null or a
failure condition, and each was forced by something visible in the denominator rather than by
which arm won. Recorded here so the transition is auditable.

**A1 — the single 75/25 holdout was replaced by 4-fold cross-validation over calls, because
F6 fired on the gate itself.** Only **14** scenarios stayed rankable under every arm, against
this spec's own floor of 20: a quarter-size population runs straight into `MIN_MEMBERS=8`. At
n=14 one scenario is 7 points, and the arm ordering *inverted* against the full-corpus
ordering — i.e. noise. CV scores every turn exactly once by a router blind to its own call, so
the out-of-fold population is the whole 23,949 turns. The pre-registered response to F6 firing
was "report as unrankable rather than compare", and that is what the single-split numbers are:
kept in `logs/routing_bench_split.log`, not quoted. Fixing a denominator is not arm selection.

A side benefit that matters more than the power: out-of-fold and full-corpus now evaluate the
**same turns against one shared control and one shared reference**, so the two modes differ in
exactly one respect — whether the router saw the turn's call.

**A2 — a symmetric `COMMON` column was added, and every failure condition now reads it.**
`share_ctrl` is a share over each arm's *own* rankable set, and those differ (38 for most arms,
21 for `probe`) because a concentrating arm leaves more scenarios above the 8-member floor.
Two shares over two denominators is exactly the asymmetric comparison this codebase has grown
four separate defences against. `COMMON` is the intersection of every arm's rankable set;
`own set` is still printed beside it so the denominator drift stays visible.

**A3 — a fold-machinery self-check was added and passes.** `description` does no fitting, so
its out-of-fold and full-corpus assignments must be identical turn for turn. Asserted on all
23,949 turns. Any index misalignment, dropped turn or fold mix-up would break it.

### F2 fired, and its literal form was mis-specified — read this before any later reuse

F2 was written as "the cluster-membership positive control does not stay clearly above every
matched arm ⇒ the null is too hard". It fired: four arms exceed the control. **But its stated
rationale — a collapsing control — is not what happened.** The control sits at 52%, and it
sits there *by construction*: the reference is the median lift of the control entries nearest
in log-size, so the control scored under its own rule must land near 50%. It is a calibration
point, not a ceiling. F2 as written encoded "the control is an upper bound", which is false
for a self-derived median.

**That reinterpretation is NOT used to rescue any result.** F2 firing is instead treated as
notice that the pre-registration lacked a check, and the missing check was run:

- *Could an arm exceed the control by tightening populations — buying lift with coverage?*
  **No.** The leading arm accepts 51.8% of turns against `centroid`'s 53.8% and the control's
  21.5%, with mean population 327 vs 339. It is not accepting fewer or closer turns.
- *Is the size-matched reference extrapolating past the control's support?* **Partly, and not
  in a way that favours the leader.** The control's sizes (median 76, max 655) sit below the
  arms' (median ~180–280), but the median entry-to-neighbour size ratio is 1.07–1.11, so the
  typical entry is graded against genuinely comparable control entries. Only 6–7 of 38 entries
  per arm exceed the largest control entry, and that count is the same for `centroid` (7) as
  for the leader (6).

**Consequence for future work: the control is a calibration point at ~50%, not a ceiling.** A
condition of the form "no arm may exceed the control" must not be re-registered.

### A4 — significance and a noise band were added, because the lead is small

The leading arm beats `centroid` on **5 scenarios and loses on 1** out of 21 common —
**exact McNemar two-sided p = 0.219**. That is not a significant difference, and a share
computed on 21 scenarios moves by ~5 points per scenario. A fold-seed sweep (seeds 1, 7, 2026
beside the pre-registered 42) is therefore run to establish the band, and **no arm may be
declared a winner on a margin inside it.** This is the same discipline the Layer D noise-floor
measurement imposed: a single headline without its band is not a result.

**A5 — `centroid_pooled` was added because `blend` vs `centroid` was a TWO-variable comparison.**
`arm_centroid` gives every adjudicated *cluster* its own centroid and max-pools per key, so a
scenario with three merged duplicates already routes against three prototypes — it is quietly
a multi-prototype method (245 points over 148 keys). `blend` averages a key's members into one
vector before mixing in the description. Comparing them varied *both* "is the description
added" and "do merged clusters keep separate prototypes". `centroid_pooled` (one mean per key,
148 points) is `blend`'s true α=1 endpoint, so the α sweep now interpolates between two arms
differing in exactly one respect.

**The test that should have caught this passed by luck and has been rewritten.** It asserted
`blend(1.0) == centroid` and went green only because the fixture's two `sc_a` clusters sat on
the same axis, so pooling them changed no decision. It now asserts against `centroid_pooled`
*and* on point counts, which no fixture geometry can mask.

**A6 — the headline statistic is `share_fixed`, over the CONTROL's rankable set, not
`share_common`.** The all-arm intersection has a defect that only appears once the arm list
varies: it SHRINKS when any single arm starves scenarios below the 8-member floor. `probe`
alone dragged it from 35 to 21, so adding one weak arm degrades the resolution of every other
comparison in the run, and two runs with different arm lists stop being comparable. Worse, it
*excuses* the starving arm — the scenarios it failed to populate leave its own denominator
too. The control's rankable set is a fixed population of scenarios known to be rankable at
all. An arm that cannot gather 8 turns for one of them has **failed** on it, which is a
result, not a missing observation. `miss` (how many it could not rank) is printed beside it.

**A7 — four description-REGISTER arms were added, at a cost of ~875 short embeddings and no
LLM calls.** `shared/scenario_vectors.py::scenario_text` concatenates `business_description`
(analyst prose, written *about* clients) with `keyphrases` (verbatim client language) and
embeds the result as ONE vector. That is an averaging of two registers, and the register gap
is the literature's named failure mode for description-based routing. Its own docstring
already asserts the hypothesis — *"keyphrases pull in the client's own wording, which is what
triggers actually resemble"* — and it was never tested. New arms: `desc_prose`,
`desc_keyphrases`, `desc_maxpool` (both as two points), `desc_kp_each` (every keyphrase its
own point — the free HyPE analogue, using real client language instead of generated text).

This matters disproportionately for shipping: `scenario_text` is a single choke point feeding
Layer B (3 call sites), Layer C (3), Layer D (`signal_check`, `rubric_lookup`) and the
response-taxonomy auto-pass. Changing *which text is embedded* needs no new stored artifact,
no schema change and no membership at match time.

## 9. RESULTS (2026-08-16) — the incumbent was NOT beaten

16 arms, 4-fold CV over calls, 4 fold seeds, 23,949 turns, gemini-embedding-2@3072.
`share_fixed` = share of the 38 control-rankable scenarios cleared. Artifacts
`routing_bench_s{42,1,7,2026}.json`, logs `logs/routing_bench_s*.log`.

| arm | mean | range | reject | miss |
| --- | --- | --- | --- | --- |
| `blend_a0.75` | **61.2** | 3 | 48.2% | 0 |
| `centroid_pooled` | 59.2 | 11 | 47.2% | 0 |
| *cluster membership (control)* | *55.3* | 0 | — | 0 |
| `submeans` | 54.6 | 3 | 47.5% | 0 |
| `centroid` — **the incumbent** | 50.7 | 5 | 46.1% | 0 |
| `blend_a0.50` | 50.0 | 8 | 49.4% | 0 |
| `knn_topk_mean` | 44.7 | 5 | 50.8% | 0 |
| `desc_keyphrases` | 42.1 | 0 | 59.3% | 2 |
| `desc_prose` | 34.2 | 0 | 57.5% | 0 |
| `probe` | 31.6 | 5 | 42.3% | **16.2** |
| `description` — **what ships** | 31.6 | 0 | 58.6% | 0 |
| `knn_max` | 29.6 | 5 | 50.6% | 0 |
| `desc_maxpool` | 26.3 | 0 | 59.3% | 0 |
| `medoid` | 21.7 | 5 | 46.7% | 0 |
| `desc_kp_each` | 18.4 | 0 | 64.4% | 1 |
| **`placebo_centroid`** | **3.3** | 3 | 57.1% | 0 |

Fold-seed band: median 2.6pp, max 10.5pp. **F1 clear** (placebo 3.3% vs centroid 50.7% — the
metric measures routing, not in-manifold geometry). **F4 clear** (no arm's reject rate fell
below half the description arm's). **F6 clear.** **F2 fired** — see §8.

### The only significant result: membership beats description

Exact McNemar over the 38 paired scenarios:

| comparison | discordant | p |
| --- | --- | --- |
| `blend_a0.75` vs `description` | 12–1 | **0.003** (all 4 seeds) |
| `centroid` vs `description` | 11–3 | 0.057 |
| `desc_keyphrases` vs `description` | 7–3 | 0.344 |
| `blend_a0.75` vs `centroid` | 6–3 | 0.508 |
| `blend_a0.75` vs `centroid_pooled` | — | 0.453–1.000 |
| `desc_keyphrases` vs `placebo` | — | **<0.001** |

**H1 IS NOT SUPPORTED, and the pre-registered F3 rule was too weak to see that.** F3 asked
whether an arm exceeds `centroid` by more than the run-to-run band. `blend_a0.75` does — +10.5pp
median against a 2.6pp band, leading in 4/4 seeds — so F3 does not fire on its own terms. But
the band measures **fold sensitivity**, not sampling uncertainty over the 38 scenarios, and the
paired test says 6–3, p=0.508. Every member of the centroid family (`centroid`,
`centroid_pooled`, `submeans`, `blend_*`) is statistically indistinguishable from every other.

**The honest headline is the one this effort was told to be willing to report: the obvious fix
is also the best available.** Exemplar routing was the first alternative anyone tried and
nothing in a 16-arm search — spanning prototypes, medoids, k-NN, multi-modal sub-centroids, a
linear probe, blends, and four description registers — beat it at a defensible level.

### The "4/4 seeds" statistic is worthless for arms that do no fitting

`description`, `desc_prose`, `desc_keyphrases`, `desc_maxpool` and `desc_kp_each` produce
**byte-identical assignments at every fold seed** — they never look at `fit_mask`. Their range-0
column is not stability, it is *invariance*, and "leads in 4/4 seeds" for any comparison among
them is **one observation reported four times**. Only `centroid`, `centroid_pooled`, `submeans`,
`blend_*`, `knn_*`, `probe`, `medoid` and `placebo` genuinely vary. A future harness should
print fold-dependence per arm so this cannot be misread.

### The binding constraint is 38 scenarios, not the method

With 38 paired scenarios, McNemar needs roughly a 12–1 discordant split to reach p<0.01. A
method that is better on **4 more scenarios** cannot be distinguished from noise here. That is
why the top of the table is unresolvable, and it means **the next useful move is more evidence,
not another method** — the same conclusion the skills-vocabulary work reached from the opposite
direction ("the fix for thin axes is MORE CSM CALLS").

### What did NOT work, and why it is worth knowing

- **`desc_kp_each` (18.4) — the free HyDE/HyPE analogue — is the worst non-placebo arm.** The
  *same words* joined into one vector score 42.1. So multi-point retrieval per class is what
  fails, not the content. **This is the reason the paid `desc_synthetic_utterances` arm was
  never run**: it is the same many-short-points shape, and ~80 chat calls would have bought a
  result already visible for free. H2's generation half is closed on that basis.
- **`desc_maxpool` (26.3) is worse than either of its two components** (42.1 / 34.2). Adding a
  bad retrieval point hurts even under a max, because it wins for some turns.
- **`probe` (31.6) fails to rank 16 of 38 scenarios.** A linear head over ~148 unbalanced
  classes collapses onto the big ones. SetFit's setting is few, balanced classes.
- **`submeans` (54.6) < `centroid_pooled` (59.2)**: more prototypes hurt. And `medoid` (21.7)
  — a single genuine member turn — is far worse than the average of them, so the mean is doing
  real denoising rather than merely summarising.
- **`knn_max` (29.6) < `knn_topk_mean` (44.7) < centroid family.** The ordering is monotone in
  how much averaging is applied. Prototype-Neighbor work reports hybrids beating prototypes;
  that result assumes a *learned* metric space, and does not transfer to a frozen encoder.

### The register finding: directionally clean, statistically underpowered

`desc_keyphrases` 42.1 vs `description` 31.6 vs `desc_prose` 34.2 — the shipped concatenation
scores **below either of its own components**, which is what the register-gap literature
predicts and is a genuinely surprising shape. But it is 7–3 on 38 scenarios, **p=0.344, and it
is a single observation**. `layer_a.scenario_vector_mode` was implemented so the question is
cheap to settle later, and **ships `concat` — production byte-identical, verified against all
245 real scenario rows, 0 differing.** It must not be flipped on p=0.344.

### Untested and deliberately so

**Everything here is gemini-embedding-2@3072; production embeds with local bge@768.** The
transfer check was explicitly declined by the user and is NOT an oversight — it is an open risk
recorded here. It matters most for `blend_a0.75`, whose α is a cosine-scale-dependent quantity,
and least for `scenario_vector_mode`, which selects text rather than a threshold.

## 10. FOLLOW-UP, pre-registered 2026-08-16 before running: cross-encoder re-ranking

Named in §3 as a candidate and not built in the first pass. It is the strongest untested idea
because it attacks the *measured* defect directly: the top1–top2 margin is **~0.01 cosine**, so
the bi-encoder is near-undecided among its leading candidates, which is exactly the situation a
re-ranker exists for.

**The gateway cannot supply one.** `/rerank` exists on the Joveo gateway and forwards to AWS
Bedrock, but the gateway validates `model` against its own list first and **`GET /model/info`
reports no `rerank` mode at all** — 116 chat, 12 embedding, 9 image, 1 realtime, 2 responses,
8 unlabelled (all chat/image). Enabling `cohere.rerank-v3-5:0` would make this testable.

**So the arm uses the local `cross-encoder/ms-marco-MiniLM-L-6-v2`, REGISTER-MATCHED.** Probed
before building, and the configuration is not a free choice:

| pairing | spread | correct top-1 |
| --- | --- | --- |
| canonical MS MARCO query/passage (does the model work at all?) | 19.9 | yes |
| turn vs scenario **description** | 0.57 | yes, barely |
| turn vs **keyphrases** | 1.75 | **NO — ranks backchannel first** |
| turn vs a real **member turn** | **4.61** | yes |

The model is a *does-this-passage-answer-this-query* ranker and is out of domain for prose
descriptions — everything saturates near its "irrelevant" floor. Against a real client turn it
separates. That is the same register-matching effect §9 already measured for the bi-encoder,
reappearing in a different model, and it is why the arm pairs turns with turns.

**Arms.** `xenc_member`: `centroid_pooled` proposes the top-5 candidate keys, then each turn is
cross-encoded against the 3 most central member turns of each candidate, max-pooled per key,
argmax. Sinks stay in the candidate set, so rejection still happens by a sink winning.
Candidate members come from the FIT folds only.

**Two controls, both required.**
- `rerank_random` — pick uniformly at random among the same top-5. **If `xenc_member` does not
  clearly beat this, the cross-encoder contributes nothing and any gain came from restricting
  to 5 candidates.** This is the placebo, and it is the one that matters.
- `centroid_pooled` itself is the base. If `xenc_member` ≈ base, re-ranking is inert.

**Pre-registered failure conditions.**
- **F7** — `xenc_member` does not beat `rerank_random` by more than the fold band ⇒ the
  re-ranker is inert; report it and do not pursue a better cross-encoder on this pairing.
- **F8** — `xenc_member` does not beat `centroid_pooled` ⇒ re-ranking loses to its own
  candidate generator; abandon.
- **F9** — reject rate falls below half `description`'s ⇒ rejected on §6's F4 grounds
  regardless of accuracy.

Cost: zero downloads (model already on disk from the probe), zero chat calls, ~700k GPU pair
scorings ≈ 1–2 minutes.

### Result (2026-08-16, 2-fold, `logs`/artifact `routing_bench.json`): F8 FIRED

| arm (out-of-fold) | gate | routing acc | reject |
| --- | --- | --- | --- |
| `centroid_pooled` — the proposer | **61%** | 66.8% | 47.1% |
| *cluster membership (control)* | 55% | — | — |
| `xenc_member` | **32%** | 33.6% | 46.5% |
| `description` | 32% | 27.5% | 58.6% |
| `rerank_random` (placebo) | 18% | 19.1% | 45.0% |

- **F8 fired decisively: re-ranking HALVES its own candidate generator** (61% → 32%). Abandoned.
- **F7 clear** — `xenc_member` beats `rerank_random` 32% vs 18%, so the cross-encoder is
  genuinely reading the pairs. It is doing real work and doing it badly enough to destroy a
  better ordering. **Weak signal that overrides strong signal is worse than no signal**, which
  is the general lesson worth keeping. **F9 clear** (46.5% vs 58.6%).
- Not run at 4 seeds: the gap is 29 points against a 2.6pp band, so this is not marginal.
- **This is a negative for THIS cross-encoder, not for cross-encoding.** `ms-marco` was probed
  as out-of-domain before the run (saturated at its irrelevant floor on prose). A purpose-built
  reranker was not reachable: the Joveo gateway's `/rerank` forwards to Bedrock but
  `GET /model/info` declares **no `rerank` mode among 135 models**. Enabling
  `cohere.rerank-v3-5:0` on the key would make this cheap to retest.

### *** THE RESULT ALSO CORROBORATES A THREAT TO THE WHOLE GATE. READ THIS. ***

Group the arms by the SHAPE of the population they produce rather than by method:

| population shape | arms | gate |
| --- | --- | --- |
| Voronoi cell around a centroid | `centroid_pooled`, `centroid`, `blend_*`, `submeans`, control | 50–61% |
| anything else | `description` **32%**, `xenc_member` **32%** | **32%** |

`description` (LLM prose, bi-encoder) and `xenc_member` (a neural cross-encoder over real
member turns) share no mechanism whatsoever and land on the SAME number, ~29 points below every
centroid-shaped arm.

**That is exactly what the following objection predicts.** `coherence(P)` is the mean cosine of
population `P` to `P`'s own centroid, and the centroid arm assigns by maximising cosine to a
centroid — **so the gate is the centroid arm's own objective function.** Every arm optimising a
different objective is graded on the centroid arm's loss. `placebo_centroid` does NOT control
for this: random-partition centroids all collapse toward the global mean (margin p50 0.0023 vs
0.0145, i.e. degenerate), so it tests "is the centroid informative", not "is the metric shaped
like a centroid".

**Consequence: the gate may be able to rank arms only WITHIN a population shape, not across
shapes.** Every cross-shape comparison in §9 — including the headline "membership beats
description" — is therefore suspect until this is tested. The within-shape comparisons
(`centroid` vs `centroid_pooled` vs `blend`) are unaffected, and they were already null.

**The cheap falsification, NOT YET RUN:** re-score every arm's populations under a second,
arm-neutral objective — e.g. mean cosine to that key's DESCRIPTION vector, and/or a
shape-agnostic measure such as mean pairwise cosine within the population rather than cosine to
its own centroid. If each arm wins under its own objective, the gate adjudicates nothing and
§9's ranking must be withdrawn.

### Other standing objections to §9, recorded rather than defended

- **Nothing was read.** Zero routed turns, zero rejected turns were inspected. Every conclusion
  is aggregate, against this repo's own repeated lesson that the aggregate misled it and
  reading samples exposed it.
- **"Out-of-fold" is weaker than it sounds.** The CLUSTERING saw every test turn; only the
  centroid computation is folded. A turn is in its cluster partly *because of itself*.
- **Routing accuracy is near-tautological** — ground truth is HDBSCAN membership and the
  centroid is that cluster's mean. "Favours those arms" was too soft.
- **The control grades a different population**: 5,159 turns (21.5%) vs the arms' ~12,000, with
  sizes median 76 / max 655 against the arms' median ~180–280 up to ~1,300. For the largest arm
  entries the same 7 control groups set the bar.
- **`desc_keyphrases` may be a scenario-TEXT-LENGTH artifact.** The null is length-matched over
  turns, not over scenario text; keyphrase strings are far shorter than prose. Untested, and a
  mechanistic story was offered anyway.
- **The one "solid" result rests on 13 discordant scenarios of 38**, which are not independent
  (one corpus, one clustering, one embedder, one client mix).

## 11. THE RANKING IN SECTION 9 IS WITHDRAWN. Two independent checks, both run 2026-08-16.

### 11a. The gate IS self-serving — `calibration/routing_objective_audit.py`

Same populations, full corpus, three objectives, denominator = the 38 control-rankable
scenarios. Both self-checks passed: the extracted draws reproduce `nt.length_matched_null` to
1e-9, and the `centroid` column reproduces `routing_bench`'s `share_fixed` exactly.

| arm | centroid *(favours centroid arms)* | description *(favours prose)* | **lexical *(favours nobody)*** |
| --- | --- | --- | --- |
| `centroid_pooled` | 61% | 53% | 55% |
| `blend_a0.75` | 61% | 71% | 53% |
| *cluster membership* | 55% | 53% | **58%** |
| `centroid` | 50% | 42% | 45% |
| `desc_keyphrases` | 42% | 71% | 34% |
| `description` | **32%** | **97%** | 29% |
| `placebo_centroid` | 21% | 0% | 37% |

**`description` moves from dead last (32%) to 37-of-38 (97%) with nothing changed but the
ruler.** The charge is proven: these objectives grade their own arm.

**AND THE NEUTRAL COLUMN IS NOT USABLE EITHER — `placebo_centroid` scores 37% under `lexical`,
beating `description` (29%) and `desc_keyphrases` (34%).** A referee a random partition can
beat is not a referee. Two readings, not separable from this data: `lexical` is too blunt (one
of the three pre-registered outcomes), or description routing genuinely is worse than random
because its failure mode is gravity wells that a size-matched random partition cannot produce
— the round trip shows one scenario absorbing **1,392 turns at 29x dilution**.

**Do NOT propose "mean pairwise cosine" as the neutral measure.** It was nearly used here and
it is fake: `coherence(P) == sqrt(mean pairwise cosine incl. the diagonal)`, verified identical
to 1e-6 at n = 10 / 50 / 300, with the off-diagonal form reconstructing as
`(n*coh^2 - 1)/(n-1)`. A monotone transform cannot audit its own source.

### 11b. Reading real turns contradicts the aggregate — `calibration/read_routed_samples.py`

**BLINDED**: the script writes `routed_samples_blind.txt` (arm identity stripped, A/B order
coin-flipped per item on a fixed seed) and `routed_samples_key.json` separately. Judgments were
committed before the key was opened.

| sample | verdict | exact binomial p |
| --- | --- | --- |
| **destination** — both accept, different scenario (n=20) | **`description` 11 – 8 `centroid_pooled`** | 0.648 |
| destination, confident calls only (n=10) | **`description` 7 – 3** | 0.344 |
| **accept-vs-reject** — one sinks it, the other accepts (n=12) | **`centroid_pooled` 8 – 4** | 0.388 |
| both rejected (n=5 read) | all genuine junk — **the sink works** | — |

**Nothing is significant, and the destination point-estimate runs OPPOSITE to the aggregate**,
which had `centroid_pooled` at nearly twice `description` (61% vs 32%). Reading suggests a
split the aggregate never showed: **`description` is at least as good at choosing WHERE a turn
goes; `centroid_pooled` is better at choosing WHETHER to take it at all.** That is a coherent
mechanism — sink keys have prose descriptions written to describe filler, and a turn's own
neighbours are a better evidence base for "is this substantive" than a paraphrase is.

Limits, stated rather than buried: one reader, who designed the arms; n=20 and n=12; blinding
mitigates but does not remove that. This does **not** establish `description` is better — it
establishes the 2x gap is not real.

### 11c. What survives, and what does not

- **WITHDRAWN:** the section 9 ranking, the "≈2x" gap, and the claim that membership-based
  routing beats description routing. It held on the centroid gate, inverted on the description
  gate, and did not reproduce on reading.
- **SURVIVES:** the sink genuinely filters junk under both arms; `description` has a real
  concentration pathology (29x dilution, one scenario absorbing 1,392 turns) that reading did
  not contradict; and `placebo_centroid` is decisively worst under two of three objectives.
- **UNRESOLVED, and now the blocking question:** there is no validated instrument for ranking
  routing methods across population shapes. Until one exists, no routing change should ship —
  including `scenario_vector_mode`, which stays `concat`.
- **The methodological result is the durable one:** an evaluation metric that is any arm's
  objective function cannot rank arms, and the way to detect it is to re-score the SAME
  populations under a rival's objective. That test is cheap, it fired here, and it should be
  standard before any future arm comparison in this repo.

## 12. THE INSTRUMENT: blinded arm-free adjudication, and its validity gates

The blocking gap was "no validated instrument for ranking routing methods across population
shapes". One now exists in pieces; this section names it, states what makes it valid, and
records which gates are MET and which are NOT. It is not a new metric — every coherence-style
metric tried was either an arm's own objective (`centroid`, `description`) or was beaten by a
placebo (`lexical`). The instrument is a PROTOCOL.

**The four properties that make it cross-shape valid**

1. **The judgment is about the ITEM, never the arms.** Accept/reject asks "is this turn
   substantive?" with no arm, no candidate scenario and no hint shown. Destination asks "which
   of these two fits?" with order coin-flipped and identity in a SEPARATE file. A metric
   computed from an arm's own geometry can favour that geometry; a judgment about the turn
   cannot.
2. **Stratified sampling with reweighting.** Two arms differ on only ~20% of the corpus, so a
   naive random sample spends 80% of the judging effort where the arms are identical, and a
   naive average over a disagreement-weighted sample is badly biased. Strata are the arms'
   own accept/reject cross-tab; every estimate is reweighted by `N_stratum / n_sampled`.
3. **Paired scoring.** Both arms are scored on the SAME judged items, so the comparison is
   McNemar on discordant pairs rather than two independent proportions. That is what gave
   p=0.017 at n=40 where overlapping CIs on the PR curve could not resolve the same gap.
4. **Operating points are swept, not assumed.** Arms are compared along a curve via the
   `delta` knob, never at one point each.

**The validity gates, and their status**

| gate | requirement | status |
| --- | --- | --- |
| G1 positive control | known-easy strata must separate | **MET** — both-reject 0/20 substantive, both-accept 16/20 |
| G2 negative control | a placebo must not beat a real arm | **MET** for the judgment protocol; **FAILED** for `lexical`, which is why no coherence metric is used |
| G3 second judge | independent rater agreement | **NOT MET** — one reader, who designed the arms |
| G4 plumbing integrity | judged TEXT must match the key's index | **MET** — audited 70/70 exact matches, and both strata verified correctly assigned |
| G5 power | enough discordant pairs to resolve the effect | **MET at n=40** for accept/reject (28-12, p=0.017); **NOT MET** for destination (11-8, p=0.648) |

**So the instrument is validated for the accept/reject decision and NOT for destination.**
That is the honest state: the half that gates Layer D is measurable; the half that picks which
rubric is used is not, and needs either a much larger sample or a null-tested second judge.

**G3 is the one worth buying, and there is a template for it.** Four LLM judges in this repo
failed their pre-registered nulls (applicability 1.22:1, coverage 64.9 vs 65.7, head-to-head
C1 0.669 / C4 0.835) and exactly ONE passed (the skills merge-validity judge, 12/12 rejected
on blinded size-matched disguised pairs). A second judge here must clear the same bar BEFORE
its verdicts count: position-swap agreement >= 0.75, separation of matched from deliberately
unrelated scenarios, and >= 80% agreement with the existing human judgments on the 70 already
adjudicated items. Only then may it be used to scale destination judging past n=30.

### Audit of every harness built this session

Checked for the bug classes that would tamper with numbers. Findings:

- **CLEAN — blind-sample plumbing.** All 70 judged items' turn indices reproduce the exact text
  shown in the blind file, and the A/B flip mapping is correct in both v1 and v2 (verified by
  re-deriving from source, not by re-reading the same code). Both strata contain only turns
  that genuinely belong to them. The p=0.017 result rests on sound plumbing.
- **CLEAN — the PR-curve estimator.** Stratum weights reproduce the published totals exactly
  (7,080.8 + 0 + 805.5 + 1,171.6 = 9,058 substantive; accepts 9,925 and 12,600 match the arms'
  own counts), and `margin >= 0` is provably equivalent to "the argmax is coachable".
- **CLEAN — no inf/NaN leakage** into any reported figure across all arms and objectives.
- **CLEAN — `_topk_candidates` handles `-inf`.** Negating for `argpartition` maps `-inf` to
  `+inf`, which sorts LAST, so a point-less key can never enter a shortlist. Worth recording
  because the opposite would have been silent.
- **NOT A BUG, but STILL UNEXPLAINED — the `lexical` placebo anomaly.** The bar is not
  degenerate (control lift p50 +0.0400 against a reference of +0.0378, only 1 of 38 entries
  near zero), so `placebo_centroid` genuinely out-lifts `description` there
  (p50 +0.0227 vs +0.0171). The leading explanation is the size mismatch that this spec already
  documents: the control's populations (p50 76) are far smaller than the arms' (122-184), so
  large arm entries are graded against the control's largest and least representative entries.
  **Open.** It is the reason `lexical` is not used as a gate.
- **Two design defects found and fixed DURING the session, both recorded above rather than
  here:** `blend` vs `centroid` was a two-variable comparison until `centroid_pooled` was added
  (§8 A5), and `share_common` let one starving arm shrink everyone's denominator (§8 A6). A
  test that passed by luck of the fixture was rewritten to assert on point counts.

## 13. Spend

Arms 1–9 are free — cached embeddings, no Postgres, no chat calls. Only
`desc_discriminative` and `desc_synthetic_utterances` cost anything (~80 chat calls each, one
per coachable scenario, batched). **They are run only if the free arms leave H2 live**, and
their cost is recorded in the artifact.
