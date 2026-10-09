# Open problems and concerns

A single consolidated register of every open problem, unresolved concern and known-unmeasured
thing in the Naren's Brain pipeline (`Brain/`), as of **2026-08-15**.

This is a **register, not a plan**. Nothing here is prioritised, scheduled or proposed as work.
Each entry states three things and stops: **what we know** (measured, with the real numbers),
**what we don't** (the specific unanswered question), and **what it would cost to find out**.
Where a source retracted or corrected an earlier figure, the corrected figure is used and the
retraction is noted in one clause.

Two distinctions run through the whole file and are stated explicitly in each entry:

- **Live pipeline** vs **shipped-off code**. Several rebuilds exist in the tree behind a
  `tuning.yaml` flag defaulting to the old behaviour (`layer_a.pool_unit: clause`,
  `layer_c.describe_mode: legacy`, `layer_d.scoring_unit: moment`,
  `layer_b.matching_strategy: flat`, `layer_b.sink_rescue_strategy: none`,
  `layer_a.response_taxonomy_auto_pass_enabled: false`,
  `layer_d.require_validated_milestones: false`, `embedding.backend: local`). A problem in an
  off-by-default path is not a problem in production.
- **Current pipeline** vs the **proposed** 2026-08-15 call-level scoring design, which is
  approved in brainstorming, partially built (`Brain/ego_trap/call_scoring.py`, untracked) and
  has passed none of its four pre-registered gate checks.

---

## 1. Blocking a sellable product

### No multi-tenancy anywhere in the system
- **What we know:** There is no tenant concept at any layer. One database, one `public` schema,
  one taxonomy. `Brain/db/schema.sql` contains **zero** occurrences of `customer_id` or
  `tenant` — no tenant column on `calls`, `scenarios`, `kb_pairs` or `rubrics`. Multi-run
  isolation today is done by copying four tables into a dated Postgres schema
  (`baseline_20260728`, `v2_overnight_20260729`, `baseline_20260808`, …), which is a snapshot
  mechanism, not tenancy. The product premise agreed today is to run the pipeline on **each
  customer's own top performer** — the machinery is the product, not Joveo's content — which
  makes tenancy the real gap between this and something sellable. The call-level scoring design
  names it in its "Explicitly out of scope" section and defers it deliberately: its one new
  table (criterion status per customer) would be "the first tenant-scoped table", and building
  tenancy around a scoring model that then changes is the expensive ordering.
- **What we don't:** Everything about the shape — whether tenancy is a column, a schema per
  customer, or a database per customer; what is shared across tenants (nothing, the prompts, the
  taxonomy machinery?); how `run_id`, `checkpoints.db` and the embedding cache partition; what
  it does to the calibration harnesses, all of which assume one live `public` schema.
- **Cost to resolve:** Expensive — a schema-wide migration plus every reader and every
  calibration script. Deliberately given its own future spec, after the call-level scoring
  design proves out.
- **Where it's recorded:** `docs/superpowers/specs/2026-08-15-layer-d-call-level-scoring-design.md`
  ("Explicitly out of scope"); confirmed directly against `Brain/db/schema.sql`.

### Nobody knows how many expert calls a new customer needs
- **What we know:** 416 Naren transcripts produced 161 scenarios, 85 coachable, 84 rubrics. The
  turn pool actually spans **400** of those 416 calls (16 contribute zero CLIENT turns). Below
  that, nothing: the minimum viable corpus size has never been measured. One adjacent number
  exists and points the wrong way — Layer D observations grow **sub-linearly**: 5.3x the CSM
  calls (19 → 100) gave 4.7x the attempts (889 → 4,181) but only 2.9x the per-milestone mean
  (3.75 → 11.1, median 7.0), because more calls also drag previously-untouched milestones into
  play (237 → 378). Also relevant: `layer_c.min_milestone_calls_floor: 3` means a scenario whose
  responses span fewer than 3 calls can never satisfy the support gate and always falls through
  to the V1 Gemma fallback, so small corpora silently produce un-clustered rubrics.
- **What we don't:** How many expert calls are needed before the taxonomy stabilises and the
  rubrics are evidenced — and whether the answer is 50, 150 or 400. Also unmeasured: how
  scenario count, coachable share and rubric support degrade as the corpus shrinks.
- **Cost to resolve:** Cheap to measure by subsampling the existing corpus —
  `Brain/recordings_subset60/`, `recordings_subset150/` and `recordings_subset250/` already
  exist from earlier subset work, and `run_v2_subset.py` runs the pipeline non-interactively
  against an arbitrary directory. The clustering half is free; each subset's Layer A
  adjudication costs roughly one call per surviving cluster. Does not block the build; it blocks
  a sales conversation.
- **Where it's recorded:** `docs/superpowers/specs/2026-08-15-layer-d-call-level-scoring-design.md`
  ("Risks"); CLAUDE.md, "Layer D over 100 CSM calls".

### The criteria are unpassable — even by the expert who generated them
- **What we know:** This is the binding constraint, and it is what survived the 2026-08-15
  retraction of the ceiling's "1.2:1". Scored leakage-clean and population-symmetric,
  `W(matched)` is **0.089–0.095**: Naren satisfies ~9% of criteria written from his own calls.
  The live CSM reference figure is `W = 0.0785` over the 100-call run. Of criteria attempted at
  least 6 times, **87 of 221 (39%) have never been satisfied by anyone, ever**, consuming
  **994 of 4,181 attempts (24%)** that return zero by construction. Two candidate causes were
  tested and both rejected: rubric size (`corr(criteria per rubric, W) = -0.09`) and
  once-per-call moves scored against every reply (per-reply credit 14.9% vs per-call 16.7%, and
  of the 87 dead criteria **zero** were credited anywhere in any call). The mean share of a
  rubric's criteria hit by *somebody* is 46%.
- **What we don't:** Whether the level is fixable at all by any change to the pipeline, or
  whether it is an irreducible fact about distilling one unusual person's behaviour into
  criteria for other people. The proposed onboarding review reclassifies the dead criteria but
  does not make the live ones more passable.
- **Cost to resolve:** Unknown — no approach with a measured path currently exists. The
  instrument to test candidate fixes against now does exist
  (`calibration/trial_grader_inputs.py`'s per-scenario paired sign test, ~230 calls per run).
- **Where it's recorded:** `docs/superpowers/specs/2026-08-15-grader-inputs-design.md`
  ("Confirmation"); `docs/superpowers/specs/2026-08-15-layer-d-call-level-scoring-design.md`
  ("Why this exists"); CLAUDE.md, RETRACTED block in the ceiling section.

### The customer onboarding review is the only mechanism that separates a bad criterion from a real gap — and it does not exist
- **What we know:** *"Define the speaker's professional role and explain the internal hand-off
  process"* (63 tries, 0 hits) is not something a rep should do. *"Reference past client success
  stories to demonstrate a proven track record"* is a real, teachable sales skill and would be
  the most valuable coaching finding in the set. **Both look identical in the hit data** — many
  attempts, zero hits — and the design states plainly that the data cannot make this call. The
  chosen mechanism is a human tick per never-hit criterion at onboarding
  (`unreviewed` / `not_expected` / `real_gap`), estimated at ~1 hour per customer. Nothing is
  deleted: `not_expected` criteria stay stored and stay scored, and only leave the headline
  denominator and the coaching output. Note the LLM sweep already tried to answer this
  automatically and under-counted by ~5x: `ops/flag_uncoachable_milestones.py` flagged **17** of
  405 milestones, while asking the data (>= 6 attempts, never credited) finds **87 of 221** —
  different denominators, same question.
- **What we don't:** Whether customers will actually do it; what the real time cost is on a full
  rubric set; how it is re-run when Layer C regenerates milestones (`milestone_id` is the array
  position, so a Layer C re-run can silently re-point every answer).
- **Cost to resolve:** Needs human time, per customer, and one new tenant-scoped table that has
  not been written — `Brain/db/schema.sql` contains no criterion-status table today.
- **Where it's recorded:** `docs/superpowers/specs/2026-08-15-layer-d-call-level-scoring-design.md`
  (sections 5 and "Data model").

### No ground truth that is not another model's opinion
- **What we know:** Every quality verdict this project has produced was rendered by an LLM
  judging an LLM. The referee is what keeps failing: the standalone applicability judge
  (0.147 matched vs 0.120 unrelated, 1.22:1), the coverage judge (64.9% `not_called_for` matched
  vs 65.7% unrelated), the head-to-head judge (position-swap self-agreement 0.669 against a 0.75
  bar; native-vs-transplanted 0.835 against a < 0.75 bar). The skills judge is the one instrument
  that passed its own null (12/12 disguised pairs rejected, positive control V=1.00). CLAUDE.md's
  standing conclusion: *"a fifth variant of 'get a model to referee' is not the next step"* —
  what would be different in kind is a unit of evidence whose ground truth is not another model's
  opinion: real outcomes (deal progression, churn) or human labels from the CS team.
- **What we don't:** Whether the CS team would supply labels, at what volume, and whether outcome
  data (deal progression, churn) is even joinable to individual calls. Neither has been scoped.
  Note also the confirmed limit of the 2026-08-15 result: it establishes that verdicts **respond
  to the right rubric**, not that they are **correct**. Only human labels settle that.
- **Cost to resolve:** Needs human time (CS team labelling) or a data-integration effort; no
  estimate exists.
- **Where it's recorded:** CLAUDE.md, "Head-to-head comparison" closing paragraph;
  `docs/superpowers/specs/2026-08-15-grader-inputs-design.md` ("Limits of this result").

### Wall 2 stands: there is no skills vocabulary, so a per-person profile has no axes
- **What we know:** This did NOT fall with the 1.2:1 retraction — CLAUDE.md is explicit that Wall
  2 and the head-to-head failures never depended on the ceiling. Three attempts, each varying
  exactly one thing: V1 prompt + bge (best merge validity 0.50), V1 prompt + Gemini embeddings
  (0.667), V2 prompt + Gemini (0.50) — against a pre-registered bar of 0.80, with no threshold
  anywhere satisfying both merge validity and statistical power. The cause is distributional and
  was found by re-reading the sweeps: **the behaviour distribution has no middle.** At every
  non-degenerate threshold mean group size vastly exceeds median (bge t=0.65: K=3, median 12,
  **mean 135**), i.e. one enormous blob plus a tail of singletons. 299 of 405 behaviours (74%,
  down from 78%) still occur exactly once after both a better embedder and a prompt written
  specifically to collapse them. What survives is a **partial** vocabulary: ~6–27 genuinely
  recurring skills — `explains a mechanism` (29), `asks open questions` (10), `call mechanics`
  (8), `builds rapport` (4), `proposes a next step` (3) — covering roughly 11–25% of milestones,
  with the rest in `skills.UNASSIGNED`.
- **What we don't:** Whether more CSM calls fixes it. The recorded position is that the fix for
  thin axes is more observations, not fewer axes — and the 100-call run's sub-linear growth says
  a median of 25 observations per milestone needs **~350+ calls**, not the ~130 first quoted.
  Untested. One identified-but-deliberately-unpulled lever: the abstraction prompt asks the model
  to keep the *why*, which splinters *explains a mechanism* into 30 strings over 55 items;
  dropping the WHY clause would materially move the curve but needs a fresh pre-registration, not
  a retry.
- **Cost to resolve:** More expert/CSM calls (expensive, needs data). A fourth wording or
  embedder pass is explicitly ruled out by the stopping condition.
- **Where it's recorded:** CLAUDE.md, "Skills vocabulary — can a per-person profile be built at
  all? No"; `Brain/PROBLEMS_AND_FIXES.md`, "The profile has no axes".

---

## 2. Layer A — the taxonomy

### Only 22% of live production scenarios beat a random null (31% -> 20% -> 22%, now on a fixed instrument)
- **What we know:** Against a size-matched random null — which had never been taken before
  2026-08-14 — most of the live taxonomy is statistically indistinguishable from a random pile of
  client turns. **The originally published "21 of 68 rankable = 31%" was corrected on 2026-08-15
  to 20%**: that figure was measured in bge on clause-formed scenarios scored with *turn*
  vectors, i.e. cross-embedder AND cross-unit, the double-count the spec's own symmetry rule
  forbids. Re-measured through one embedder, one pool, one assignment rule and one null
  (`calibration/null_test_taxonomy.py`): **production 16/82 = 20%**, turn mode 11/38 = 29% — note
  the absolute counts go the other way (16 vs 11). The population split holds: of the original
  21 passers, 20 were subject-matter and **exactly 1 of 24 posture (`client_*`) scenarios**
  cleared it. Live production is 161 scenarios / 85 coachable (52.8%) / 76 sinks / 84 rubrics, so
  the `is_coachable` label is materially more optimistic than the evidence supports.
- **RESOLVED 2026-08-16 (R4, commit `b7d4e94`) — the null is length-matched and the corrected
  answer is production 18/82 = 22%, turn mode 11/38 = 29%, against a positive control
  (HDBSCAN's own clusters, merges included) at 20/38 = 53%.** The recorded conclusion did not
  reverse; the instrument behind it did. **The real finding is the GAP** — groups known to be
  coherent reach 53% where both taxonomies sit at 22–29%.
- **What we still don't:** the confound is REDUCED, not removed — `corr(lift, mean words)`
  falls +0.65 → **+0.37** (production) and +0.64 → **+0.25** (turn mode), so every result here
  is *length-adjusted*, not length-free. `client_direct_denial` still clears, at rank 4 rather
  than 2: a pile of "No." is coherent even against other short turns. And the whole measure is
  of the population MATCHING gathers, so a low score cannot distinguish "not a real topic"
  from "real topic, wrong turns routed into it" — see the routing item below.
- **Two traps recorded so they are not re-entered:** (1) `lift` FALLS with n (corr −0.510
  inside the control) while `z` RISES with n, so **no single threshold of either kind is fair**
  across entries spanning n=8 to n=1,326 — the reference must be size-matched, and a flat one
  understated both arms by 16–17 points. (2) Do **not** re-derive the bar as position within
  the entry's own null distribution; a trivial +0.012 excess scores z≈15. Significance is not
  effect size.
- **Where it's recorded:** CLAUDE.md, "Layer A pool unit" + its TWO CORRECTIONS block;
  `docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md` ("The finding that started
  this").

### The turn-mode rebuild is measured only up to the raw material — nothing downstream (Concern 1)
- **What we know:** Turn mode is shipped OFF (`layer_a.pool_unit: clause`; production
  byte-identical, regression-verified at 237 raw → 171 merged). Measured on the full corpus at
  each arm's own derived threshold (clause 0.85, turn 0.92): pool items 73,771 → 23,949;
  content-free 59.1% → 32.8%; subject-bearing clusters 8 (4.7%) → 71 (37.2%); junk 98 (57.3%) →
  78 (40.8%); `corr(negation rate, content-free)` -0.149 → -0.744. The gain is the **unit**, not
  the threshold — both arms were swept 0.85–0.95 and the bands never overlap. 8 real adjudication
  calls de-risked the two specific Layer A failure modes (camouflaged junk accepted; stance lost)
  and both came out favourable, plus the posture x subject grain was found to arrive at
  adjudication rather than clustering (5 of 5), which **retracted** the proposed stance-splitting
  second pass as unnecessary.
- **What we don't:** Whether better clusters make better rubrics or better coaching. Everything
  measured is pre-AI and upstream. The 5-of-5 grain finding is n=5, hand-picked, and needs the
  full 191-cluster pass to confirm.
- **Cost to resolve:** Expensive-ish — the paid run: a few hundred LLM calls, a database snapshot
  first, and it resets scenario names and the CSM score history.
- **Where it's recorded:** `docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md`,
  CONCERNS REGISTER items 1 and 2, and Status updates 2–6.

### Turn mode needs two config values to move together, and there is one key for each (Concern 4)
- **What we know:** Turn mode requires `merge_cosine_threshold` 0.92 **and** `min_cluster_size`
  16, while the shipped values (0.85 / the legacy formula) are correct for clause mode. Flipping
  `pool_unit` without both is a silent breakage. Status: **NOT TOUCHED.** The proposed fix is to
  derive both from the pool unit in code so they cannot drift apart. Compounding it: on the
  Gemini backend the merge threshold is **0.97**, not bge's 0.92 — two backends, two values, one
  config key.
- **What we don't:** Nothing measurement-wise; this is unbuilt work, not an unanswered question.
- **Cost to resolve:** Free (code change), but it must not land in the same run as any other Layer
  A variable.
- **Where it's recorded:** Pool-unit spec CONCERNS REGISTER item 4; CLAUDE.md, "Gemini backend
  via the Joveo gateway".

### `min_cluster_size` is a hardcoded count of 50 dressed as a formula (Concern 6)
- **What we know:** `fit_topic_model`'s `min_cluster_size = max(3, min(n // 10, 50))` resolves to
  a flat **50** for any corpus >= 500 items, so granularity silently depends on pool size:
  0.068% of the clause pool but 0.209% of the turn pool, a 3x stiffer bar. This violates the
  codebase's own rule that a threshold must never be a count. It is the reason the first turn arm
  read as "coarser" (74 raw clusters vs clause's 237) — at the scale-matched 16 it produces
  **246**, slightly more, and that conclusion was withdrawn. Status: not fixed, now
  **overridable** — the function takes an optional `min_cluster_size` (default `None` = legacy
  formula), and the default path is still the hardcoded 50. Related: the sink pool's own
  `min_cluster_size` resolved to 25 **by hitting the `min_cluster_size_ceiling`** (0.02 × 3730 =
  74.6, clamped).
- **What we don't:** What fraction of the pool it should be, and what a finer setting does to the
  live taxonomy — untested at production scale.
- **Cost to resolve:** Free to change; a re-derivation sweep is free (zero LLM, zero DB) but a
  new taxonomy needs the paid adjudication run.
- **Where it's recorded:** Pool-unit spec CONCERNS REGISTER item 6 and Status update 2.

### ~60% of every substantive client turn becomes HDBSCAN noise and never enters the taxonomy
- **What we know:** **11,701 of 23,949** turns are dropped as noise. The rate is uniform above 25
  words (58.7% / 60.3% / 59.8% / 52.9% across the 25-49 / 50-99 / 100-199 / 200+ bands), so it is
  not a long-turn problem and a chunker cannot address it. Because loss is concentrated in longer
  turns by word volume, it discards the majority of what clients actually said. Same family as
  the sink pool's 47.3% noise (45.2% clause arm, 48.9% turn arm here). `min_cluster_size` is the
  obvious lever and it is Concern 6, unfixed.
- **What we don't:** Whether recovering any of that 60% is possible or worthwhile. Explicitly
  **unscoped and unmeasured**, recorded so it is not rediscovered.
- **Cost to resolve:** Free to probe (clustering is zero-LLM, zero-write); acting on it needs a
  paid re-adjudication.
- **Where it's recorded:** Pool-unit spec Status update 7 ("The finding this probe surfaced
  instead, which is bigger"); CLAUDE.md.

### Account-bound clusters: only 9 of the 38 turn-mode coachable scenarios survive both the null test and reading
- **What we know:** The proper-noun check ran on 2026-08-15
  (`calibration/flag_proper_noun_clusters.py`, free) and **the check the spec proposed would not
  have found its own confirmed example**: `corr(proper-noun rate of top keywords, account lift)
  = 0.182`. It misses `implementing_and_maintaining_tracking_pixels` (`happy dance` is a bigram)
  and falsely flags `navigating_rfp_and_procurement` — 66 accounts, 120 calls, the most broadly
  evidenced coachable scenario there is. The signal that works is keyword-account concentration
  (r=0.616). Of 38 coachable clusters, 21 exceed their own null's p99; by reading, **7 should not
  be in the count** — 6 account-bound (tracking_pixels = 95% Uber; experiential_branding = 98%
  RTX; managing_non_technical_stakeholders = 100% Banfield, glued by two colleagues' first names;
  niche_board_roi = 100% Banfield; creative_candidate_engagement;
  ats_and_middleware_integration_architecture) — plus `compensation_and_variable_structuring`,
  which is **not a client conversation at all** (job interviews across 9 calls; modal account
  `gmail.com`; 14 of 20 sampled turns have no client domain) and yet **passes the null test at
  rank 3 of 38**. Sinks are not contaminated (+2.7% mean lift, 11% flagged, vs coachable's +29.6%
  and 55%) — the contamination is entirely in what Gemma **accepts**. Net: **quote 9, not 38.**
- **What we don't:** How to detect account-boundness automatically at production scale (the
  concentration signal exists at r=0.616 but no rule has been built or calibrated), and whether
  the same 7-in-38 rate applies to the live 85-coachable clause taxonomy — the check was run on
  turn mode only.
- **Cost to resolve:** Free to extend the same script to production's clusters; building a
  production rule is a design task.
- **Where it's recorded:** CLAUDE.md, Layer A pool-unit section (proper-noun check bullets);
  pool-unit spec Status update 12 ("The caveat that qualifies the 38").

### Layer A's Gemma coachability adjudication is not reproducible across runs
- **What we know:** With a warm `embed_cache.db`, the BERTopic clustering geometry reproduces
  exactly (237 raw → 171 clusters → 158 scenarios, identical across runs), but the per-cluster
  coachability verdict does not: **78 coachable one run vs 85 previously, for the same underlying
  clusters.** Comparing by `scenario_key` is a trap (Gemma renames every run); comparing by
  `support_calls` / `call_coverage` size-signature shows most of the diff is renaming, with a
  real **~5–6% of clusters (roughly 7–10 of 158)** genuinely flipping across the
  coachable/mechanics boundary between independent runs. Plausible cause: the largest-cluster-first
  adjudication order cascading through the "top-3 nearest already-accepted scenarios" context each
  cluster sees. On the Gemini backend, clustering itself is now exactly reproducible (292 raw →
  245 merged across four separate runs), which removes one of the two variance sources but not
  this one.
- **What we don't:** Not root-caused. **Open follow-up, unscoped.**
- **Cost to resolve:** Each replication is a full adjudication pass (~150–250 LLM calls), so
  confirming the cause is moderately expensive.
- **Where it's recorded:** CLAUDE.md, V2 evidence-triage clustering section (2026-07-29 verdict
  block).

### The Layer D coverage test of the new taxonomy is confounded beyond repair, and the unbiased version was never run
- **What we know:** Sampling 600 real client turns from the 84 scenarios `gap_events` actually
  fired against, production keeps **512/600 (85.3%)** and turn mode **444/600 (74.0%)**. Read
  as-is that favours production by 11.3 points, and it should **not** be read as-is: the moments
  are defined BY the old taxonomy, and the top two sources
  (`client_requests_operational_visualization`, 184 events;
  `client_validates_proposed_scenario`, 131) are posture scenarios that fail the random-null
  test. The test cannot separate "misses real coaching" from "correctly declines the old
  taxonomy's noise", and no version of it can while the ground truth is the old taxonomy's own
  output.
- **What we don't:** The unbiased answer. The stated unbiased design — score both taxonomies
  against the 589 verified moments in `artifacts/h2h_moments.json`, which need no rubric and no
  scenario assignment — is **NOT RUN**.
- **Cost to resolve:** Free — the moments artifact exists, is content-hashed, and both taxonomies
  are already embedded.
- **Where it's recorded:** Pool-unit spec Status update 12, Test 2; CLAUDE.md.

### Long-turn content orphaning is real, length-driven and modest — the fix is designed but ranked low (Concern 7)
- **What we know:** The concern went CLOSED → REOPENED → SETTLED across three probes. Long turns
  (>= 100 words) are **4,201 turns = 17.5% of turns holding 52.4% of all client words**. They do
  **not** damage the cluster they join — they land in the cleanest ones (5.4% content-free at
  100-199 words vs 76.8% at 0-9 words, `r = -0.834`). But content **inside** them is orphaned:
  the raw rate is 59.1% of sentences preferring a different cluster, of which **72.7% is filler
  rejoining backchannel clusters — the fix working, not harm.** Narrowed to genuine subject loss:
  **2,483 of 31,522 sentences = 7.88%**, monotonic in length (0.00% at 0-9 words, 8.61% at 50-99,
  13.75% at 100-199, 18.70% at 200+), and that is an **upper bound**. Approach C (chunk long turns
  into topic-bearing pieces, never emitting a stance-only fragment) stays live but ranked LOW —
  single-digit gains, a new calibrated knob, and the `"Indeed"` stopword fix as a prerequisite.
- **What we don't:** Whether chunking actually recovers the ~8-14%, and what it costs in new
  posture fragments. Untested — the knob does not exist.
- **Cost to resolve:** Blocked on the `"Indeed"` fix (see §3); the probe itself was free.
- **Where it's recorded:** Pool-unit spec Status updates 7, 8 and 9; CONCERNS REGISTER item 7.

### 16 transcripts contribute zero CLIENT turns, and every coverage figure was computed against 416
- **What we know:** The turn pool spans **400 calls, not 416**. Every trial computed
  `call_coverage` and the support floor against 416, so coverage is slightly understated and the
  support floor is 9 rather than 8. Too small to move any conclusion, but every quoted number
  carries it.
- **What we don't:** Whether the 16 are genuinely internal calls or roster misclassification.
  **Unexamined.**
- **Cost to resolve:** Free — read the 16 transcripts.
- **Where it's recorded:** Pool-unit spec, "Two incidental findings from the long-turn probe's
  step 1"; CLAUDE.md.

### `layer_a.min_content_words: 5` is configured, authoritative-looking, and inert
- **What we know:** `v2/layer_a.py::run_layer_a_v2` calls `build_client_clause_pool(all_turns)`
  with **no argument**, so the signature default `min_content_words: int = 0` wins and no
  pre-filter runs on the CLIENT clause pool. The tuning value is honoured only by
  `calibration/dry_run_layer_a.py --prefilter`. Same failure class as the retired
  `ego_trap/settings.py`. Left off deliberately: enabling it would move a second variable in any
  Layer A pool experiment.
- **What we don't:** What enabling it would do to the taxonomy. Never measured in production.
- **Cost to resolve:** Free to enable; measuring the effect needs a paid re-adjudication.
- **Where it's recorded:** CLAUDE.md, Gotchas.

---

## 3. Layer B — matching

### Every scenario assignment rests on a ~0.01 cosine margin
- **What we know:** The top1-minus-top2 matching margin is **p50 0.009–0.010** (mean 0.0147 turn
  mode vs 0.0164 production) — in **both** taxonomies, measured over 6,468 real CSM client turns.
  Every Layer B and Layer D scenario assignment rests on the winner beating the runner-up by a
  hair. CLAUDE.md's own note: *"Unexamined, and arguably a bigger problem than which taxonomy is
  used."* The call-level scoring design is the first thing to respond to it — it over-includes
  the top 2–3 candidates per moment so that a false positive costs "one extra chunk of context"
  instead of "a wrong verdict".
- **What we don't:** How often the top-1 choice is actually wrong, and what the correct decision
  rule is when two scenarios are within 0.01. No harness measures assignment correctness against
  anything.
- **Cost to resolve:** Free to measure the distribution (already done); establishing correctness
  needs labels.
- **Where it's recorded:** CLAUDE.md, Gemini-gateway section; pool-unit spec Status update 12,
  Test 1; call-level scoring design §4.

### The `"Indeed"` stopword bug — live, gating every pair into `kb_pairs`, NOT FIXED
- **What we know:** `'indeed' in spacy.Defaults.stop_words` is `True` for both cased forms, while
  `ZipRecruiter` and `Greenhouse` are not — so the substantive filter deletes a major job board's
  name from every sentence it appears in, inconsistently across competitors in the same domain.
  Measured: `"So right now we post everything manually to Indeed and ZipRecruiter."` keeps only
  `['right','post','manually','ZipRecruiter']` = **4, below the floor of 5**. This is not
  hypothetical — **`v1/layer_b._is_substantive` is ACTIVE and gates every trigger/response pair
  entering `kb_pairs`.** Note the trap in the obvious fix: whitelisting domain terms is exactly
  the "a threshold must never be a curated list" anti-pattern this codebase forbids. Also note
  there are TWO substantive filters and they do not share a knob — `layer_b._is_substantive` uses
  its own module constant `_MIN_CONTENT_WORDS = 5`; `shared/cluster_evidence.is_substantive`
  reads `tuning.yaml`'s `layer_a.min_content_words`.
- **What we don't:** What a correct substance test looks like, and how many pairs are actually
  lost corpus-wide. Neither designed nor measured.
- **Cost to resolve:** Free to measure the loss; the fix needs a new design. It **blocks**
  calibrating any new content-word floor, and therefore blocks Approach C. It must not land in
  the same run as a pool-unit change (it moves a second variable).
- **Where it's recorded:** CLAUDE.md, Gotchas; pool-unit spec CONCERNS REGISTER item 5 and
  "Findings recorded elsewhere, not fixed here".

### `extract_pairs` has the same stopping-rule bug as Layer D's segmenter
- **What we know:** **443 pairs are lost outright**, and earlier substantive turns are dropped
  from **1,316 more**. Explicitly kept out of the pool-unit work to preserve single-variable
  attribution.
- **What we don't:** Whether the lost pairs are substantive, and what fixing it does to the KB.
  Unmeasured beyond the counts.
- **Cost to resolve:** Free to characterise (read the 443); fixing it changes what enters
  `kb_pairs` and therefore needs a full re-run to evaluate.
- **Where it's recorded:** Pool-unit spec, "Explicitly out of scope".

### Sink absorption discards real content, and eight signal families failed to fix it
- **What we know:** A pair whose *trigger's* best match is a sink is filed there alone and
  permanently excluded from every rubric — **1,827 of 4,605 pairs (39.7%)** in the first
  production run, **2,110 of 4,605 (45.8%)** in the overnight run. Reading 30 sampled pairs by
  hand found roughly **half genuinely coachable**, and a second audit found the trigger itself
  can be substantive and still land in a sink. Eight signal shapes were then measured and all
  failed: absolute cosine floors (two rounds), `concrete_content_density` (AUC 0.523,
  indistinguishable from chance), `sink_real_margin` (0.437 as published, **0.563** corrected for
  its inverted direction), `trigger_response_coupling` (0.617), `response_word_count` (0.853 but
  systematically flags long admin chatter and discards terse strategic pivots), a logistic
  combination (0.845, *below* length alone), `edge_distance` (0.636) and length+position (0.876,
  same false negatives). Cluster-level averaging also failed (`real_minus_sink_margin` has no
  relationship to the verdict even at cluster level). The three-arm Layer C replay then rejected
  the cheapest fixes outright — deleting the sink short-circuit destroys **82 of 385 milestones
  (21%)** and its placebo gained more than it did. `by_cluster` is the least damaging by a wide
  margin (375 matched / 8 merged / 1 split / 1 lost, beating its placebo on lost 1-vs-6 and gained
  4-vs-0) but its worst case is a 5-into-1 collapse, so **no rescue method is validated for
  production**. `matching_strategy` stays `flat`, `sink_rescue_strategy` stays `none`.
- **What we don't:** Whether any of the lost content matters to rubric quality. The partial fix
  that did ship — the response-taxonomy auto-pass — graduated 4 scenarios and rescued 164 pairs
  in its one real run, and its flag was then reverted to `false` pending review, so the structural
  gap is open. 47.3% of the sink pool is HDBSCAN noise, capping any cluster-based fix at ~53% of
  the problem.
- **Cost to resolve:** The embedding-signal search is explicitly **closed, not paused**. Any
  further attempt is free against `artifacts/labeled_trigger_quality_sample.json` (150 labelled
  pairs with raw embeddings persisted, `--load` replays at zero cost).
- **Where it's recorded:** CLAUDE.md, "Layer B sink-rescue" + "Sink-pool population diagnostic";
  `Brain/PROBLEMS_AND_FIXES.md`, "Layer B audit"; specs
  `2026-08-04-layer-b-sink-rescue-design.md`, `2026-08-05-layer-b-combined-signal-analysis-design.md`.

### `response_taxonomy_auto_pass_enabled` is `false` after one successful real run
- **What we know:** The permanent fix for the sink gap works: 3 manual invocations against the
  live `public` schema graduated **4 scenarios**, rescued **164 pairs**, left `kb_pairs` total
  unchanged (4,605 → 4,605), and **every one of the 164 rerouted pairs was verified
  `is_coachable=false` beforehand** against the `baseline_20260808` snapshot — the "never disturb
  an already-homed pair" protection held. The flag was then reverted to `false` "pending further
  review before letting it run unattended".
- **What we don't:** What the outstanding review is, and what the pass does across many
  consecutive automated runs (graduation requires a candidate to survive
  `response_taxonomy_consensus_runs: 3` via `stable_pair_ids` intersection — never exercised
  unattended).
- **Cost to resolve:** Cheap — the pass is a small number of adjudication calls per run.
- **Where it's recorded:** CLAUDE.md, "Response-taxonomy auto-pass"; `Brain/PROBLEMS_AND_FIXES.md`.

### Duplicate coachable scenarios survive the merge threshold
- **What we know:** Reading the overnight run's 78 coachable scenarios found real duplicate pairs
  that `merge_cosine_threshold: 0.85` did not catch: `current_tech_stack_disclosure` (25 calls)
  vs `current_tech_stack_disclosure_1` (34 calls); `third_party_vendor_coordination` (18) vs
  `_1` (28); and a four-way ATS family (101 / 61 / 19 / 12 calls). The same under-merging appears
  on the sink side (three separate ~265-call backchannel clusters). Estimated at roughly **4–5%
  of the 78 coachable scenarios**, and unlike the sink-duplicate case, merging these *would*
  improve rubric quality — two thin rubrics for one behaviour instead of one well-evidenced one.
  **Not fixed.** The related sink-only merge experiment was tested and shelved: at 0.85 only 6 of
  73 sinks merge, and a bigger reduction needs 0.75–0.80, already proven to fuse unrelated
  concepts.
- **What we don't:** Whether a `_1`-suffix-triggered secondary merge pass works, and against what
  vectors — Layer A's raw clause centroids are not persisted, so a post-hoc merge can only use
  description text, in which the specific duplicate pair never merges at any tested threshold.
- **Cost to resolve:** Cheap to prototype against description vectors; a proper fix needs the
  centroids persisted, i.e. a pipeline change.
- **Where it's recorded:** `Brain/PROBLEMS_AND_FIXES.md`, "A higher-stakes version of the same
  gap".

### The relative margin has no absolute floor, so a weak best match still wins
- **What we know:** One sampled pair was assigned cleanly (not as a sink) to the coachable
  scenario `client_hedged_agreement` with trigger text *"He's gonna hydrate in preparation for
  that. Yeah. No pressure."* — banter, not a hedged agreement. The scenario's own description is
  fine; this is the relative-margin rule (`relative_margin: 0.95`, calibrated against the
  *distribution* of best-match similarities) accepting a poor best match in absolute terms.
- **What we don't:** How often this happens. **Not investigated further** — noted as a smaller,
  separate finding from sink-discarding.
- **Cost to resolve:** Free to measure (the similarity band is already recorded: trigger-vs-scenario
  p10 0.496 / p50 0.550 / p90 0.613); adding a floor would need its own calibration and would
  reintroduce the absolute-threshold pattern this pipeline moved away from.
- **Where it's recorded:** `Brain/PROBLEMS_AND_FIXES.md`, "Layer B audit".

### Two-stage (category-first) matching got worse at full scale and is dead code in the tree
- **What we know:** `assign_scenarios_two_stage`'s strict/soft/fallback strategies are NOT called
  by production. Validated at 150 calls they looked promising (fallback 86.6% agreement, Jaccard
  0.824); at the full 416 calls **every strategy got worse** — strict 69.9% → 61.3%, soft 83.6% →
  77.0%, fallback(0.50) 82.1% → 71.4% — mechanically consistent with the first stage having far
  more ways to pick the wrong parent (28 → 80 primary topics). The floor sweep games itself: at
  0.70, 59.3% reroute and 100% agreement, i.e. it has simply reverted to flat matching.
  **Verdict: full-scale data argues against adopting it.**
- **What we don't:** Nothing outstanding — this is recorded as closed. It remains in the tree as
  an uncalibrated code path, which is a maintenance surface.
- **Cost to resolve:** N/A (closed).
- **Where it's recorded:** CLAUDE.md, "Layer A primary_topic hierarchy + Layer B two-stage
  matching".

---

## 4. Layer C — the criteria

### The criteria writer is blind to the client turn, and the situated fix lost its trial
- **What we know:** `v2/layer_c.py::_describe_milestones_batch` shows the model the scenario's
  key string, its own response clauses, and nothing else — it has never seen a client turn, so it
  cannot state a precondition. The evidence: **234 of 235 milestones are labelled `fixed`**, and
  the conditional trigger fires **0 times out of 226**. That is a missing-INPUT problem, so a
  fourth wording pass cannot fix it. The situated rewrite was built
  (`PROMPT_LAYER_C_MILESTONE_DESCRIBE_SITUATED`, `_describe_situated`) and **lost its own trial**:
  1.04 / 0.89 / 1.09 against a 1.30 baseline. It ships OFF (`layer_c.describe_mode: legacy`;
  production byte-identical). **That trial was briefly suspected of circularity and the suspicion
  was RETRACTED the same day, before implementation** — `trial_layer_c_arms.py` is
  population-symmetric (`matched` and `unrelated` are built from the same rows with only the
  rubric key swapped, `trial_layer_c_arms.py:700-701`), and supplying the situation to the grader
  was separately measured to change nothing (blind D=6.00 vs full D=5.84). Its instrument was
  sound. **The verdict stands: do not regenerate criteria on circularity grounds.**
- **What we don't:** Why situating the writer lost. Nothing explains the direction, and it was
  not re-run. Also unmeasured: whether the "conditional" mechanism could be made to fire at all.
- **Cost to resolve:** Re-running the four-arm trial is ~hundreds of calls and is explicitly
  discouraged; the underlying dead-code question is free to inspect.
- **Where it's recorded:** CLAUDE.md, "Layer C rebuild — three changes, all shipped OFF";
  `docs/superpowers/specs/2026-08-12-layer-c-profile-rebuild-design.md`;
  `docs/superpowers/specs/2026-08-15-grader-inputs-design.md` (the retraction block).

### Contingent moves are graded as mandatory, and the mechanism meant to catch that is dead code
- **What we know:** Reading all 60 dead criteria from an earlier count, what they share is not
  vagueness but an unstated **precondition** — they require a specific moment (introducing
  yourself, setting an agenda, offering to screen-share), a specific client history, or a specific
  thing to point at. These are real recurring moves presented as required, and every response is
  graded against every milestone regardless of whether the moment called for it. The mechanism
  that would mark one conditional is the `sequencing_type` field, and it is dead: 234 of 235
  fixed, trigger fires 0 of 226. Separately, `sequencing_type == "conditional"` is **recorded but
  deliberately never acted on** in Layer D, for three stated reasons.
- **What we don't:** Whether fixing applicability helps at all — *"did this moment call for this
  move"* has now failed **twice** in two different framings (standalone judge 0.147 matched vs
  0.120 unrelated = 1.22:1; coverage judge **64.9% `not_called_for` matched vs 65.7%
  unrelated**). A third attempt is explicitly "speculative, not routine". The proposed
  `did_occur` check in the call-level design is a coarser cousin of the same question and is
  gated (see §5).
- **Cost to resolve:** Cheap per attempt (~tens of calls), but two attempts have already failed.
- **Where it's recorded:** `Brain/PROBLEMS_AND_FIXES.md`, "The dominant cause of the low rate";
  CLAUDE.md, Layer C rebuild + Layer D realignment sections.

### Layer C's relevance filter barely discriminates by topic
- **What we know:** Deliberately wrong placebo clauses survived the p40 relevance cut at
  **53.9–57.2%**, against **57.7–63.0%** for real rescued content — a ~6-point gap on a filter
  the pipeline leans on to keep off-topic clauses out of rubrics. Found incidentally during the
  sink-pool diagnostic and recorded as a new open finding, unrelated to sinks.
- **What we don't:** Whether the filter is worth anything at all, and what percentile (if any)
  actually separates. Untouched since it was found.
- **Cost to resolve:** Free — the replay harness (`calibration/replay_layer_c_admitted.py`) runs
  Pass 1 with zero LLM calls and zero writes.
- **Where it's recorded:** CLAUDE.md, "Sink-pool population diagnostic".

### Layer C clustering is not reproducible across process launches, and the cheap mitigation was never implemented
- **What we know:** Identical code, config and corpus produce different milestone counts across
  separate process launches: 241 (the anomalous low outlier), 385, 398, 403–407 predicted, 404.
  `umap.UMAP(random_state=42)` pins the RNG but does not guarantee byte-identical output across
  process invocations. Per-scenario proof: `client_availability_and_scheduling_friction`'s stored
  rubric had 3 milestones (`support_calls=[8,4,4]`) while a replay found 10 candidates in which
  **8 does not appear at all**, and a third launch produced 8 milestones. Verdict rendered
  2026-07-29: **accept the variance, do not engineer determinism** — three of four post-UMAP
  measurements land within ~2% of ~400. Recommended mitigation: log-warn if a run's total
  milestone count falls outside ~[350, 450]. **Not implemented.**
- **What we don't:** Nothing measurement-wise — the decision is made. What is unknown is whether
  the band still holds under the Gemini backend (Gemini embeddings are deterministic and remove
  one of the two variance sources, but Layer C has not been re-measured there).
- **Cost to resolve:** Free (a log line).
- **Where it's recorded:** CLAUDE.md, V2 evidence-triage clustering, verdict block.

### `rubrics.anti_patterns` has never been read by anything
- **What we know:** Layer D scores `milestones` and `soft_skills`; `anti_patterns` sits in every
  rubric untouched. It asks a genuinely different question — *"did they do this specific bad
  thing"* rather than *"did they reproduce this specific good move"* — which is a real reason it
  might discriminate where milestones do not. Counter-evidence: `PROMPT_LAYER_C_V1` requires them
  to carry `"[inferred]"` and `"confidence": "inferred, unverified"`, so they are model guesses
  rather than clustered evidence.
- **What we don't:** Whether they discriminate at all. Never null-tested.
- **Cost to resolve:** Cheap — null-testable against the data the 100-call run already produced.
- **Where it's recorded:** CLAUDE.md, "Layer D over 100 CSM calls".

### Milestone fallback provenance is whole-scenario and unvalidated
- **What we know:** A scenario's milestones are either entirely clustered or entirely
  Gemma-written, never mixed — measured against both post-rework snapshots:
  `v2_alpha_20260728` (82 rubrics: 87 clustered + 88 fallback → 51 all-clustered / 31
  all-fallback / **0 mixed**) and `v2_overnight_20260729` (73 rubrics: 403 + 1 → 72 / 1 / **0
  mixed**). `get_rubric_for_scenario` now selects `pipeline_version` so this is observable, and
  a run whose gap records come mostly from v1-fallback rubrics is measuring Gemma free-text, not
  clustering evidence.
- **What we don't:** Whether fallback rubrics score differently from clustered ones. No run has
  ever split its results by `pipeline_version`, so every headline number silently mixes both
  populations.
- **Cost to resolve:** Free — it is a `GROUP BY` over data already stored.
- **Where it's recorded:** CLAUDE.md, calibration gotchas + Layer D realignment.

### The skills abstraction prompt's WHY clause was identified as the lever and deliberately not pulled
- **What we know:** The prompt asks the model to keep the *why* ("Keep what the person is DOING
  and WHY"), which splinters *explains a mechanism* into 30 phrasings over 55 items. Dropping the
  clause would materially move the curve. Left alone deliberately — "re-running after a negative
  with a tweaked prompt is how a result gets tuned into existence", and three wording passes have
  already failed.
- **What we don't:** Whether it would move the curve far enough (validity needs 0.50/0.667 →
  0.80). Untested by design.
- **Cost to resolve:** Cheap in calls; expensive in credibility — it needs a fresh
  pre-registration, not a retry.
- **Where it's recorded:** CLAUDE.md, Skills vocabulary section.

---

## 5. Layer D — scoring

### DEFECT 1 — `Signal_Recognition_Failure` is 98.6% a segmentation artifact, NOT FIXED
- **What we know:** `transcript_parser.turns_until_next_client` stops at the NEXT CLIENT turn, so
  when a client speaks several turns in a row every turn but the last gets an **empty** response
  window and `classify_response_outcome` returns `"none"` by construction. Of 5,731 client turns
  over 100 transcripts: 2,144 `csm` / 1,103 `other_joveo` / **2,484 `none`**. Of those 2,484,
  **2,449 (98.6%) are immediately followed by ANOTHER CLIENT TURN**, 35 are the last turn of the
  call, and **0 are genuine silence.** It does not measure whether the CSM responded; it measures
  whether a client turn happened to be last in its block. This **retires** the previously recorded
  claim that "36% of gap_events are `Signal_Recognition_Failure` — no CSM response existed to
  score at all", which had been cited as a real cause of the low hit rate. Scored milestones are
  UNAFFECTED (only `csm` outcomes are scored); what is corrupted is the failure count and any
  coaching output derived from it.
- **What we don't:** What the true recognition-failure rate is. The fix — treating consecutive
  client turns as ONE client move — changes what counts as a signal and therefore the
  denominator, so it must be pre-registered before it is run.
- **Cost to resolve:** The measurement was free. The fix is cheap in code and expensive in
  interpretation (it moves the denominator, so old and new recognition rates are not comparable).
  `calibration/trial_client_move_arms.py` already derives and measures a client-move definition;
  promoting `client_blocks` / `last_speaker_move` into `shared/` is named as the natural follow-up.
- **Where it's recorded:** CLAUDE.md, "Layer D over 100 CSM calls" DEFECT 1; pool-unit spec,
  "Explicitly out of scope".

### DEFECT 2 — the grader is blind to the situation. Real code fact, measured NOT to be the constraint
- **What we know:** `score_milestones_batch` builds each exchange out of exactly three things —
  Naren's benchmark response, the CSM response, and per milestone `description` +
  `detection_hint`. The **client turn**, the **`scenario_key`** and the milestone **`label`** are
  all stored and all discarded. This was tested on 2026-08-15 and **refuted as the binding
  constraint**: discrimination went `blind` 6.00 → `turn` 6.64 / `label` 4.48 / `full` 5.84, with
  heavily overlapping CIs and no ordering, over 120 items and 546 gradings per condition. **Do
  not spend on it again.**
- **What we don't:** Nothing about whether it matters — that is settled. The code fact remains
  (the fields are still discarded in production, `situated_fields` defaults to `None`), so it is
  recorded here so it is not re-diagnosed as a fresh finding.
- **Cost to resolve:** N/A — closed by measurement, ~80 calls spent.
- **Where it's recorded:** `docs/superpowers/specs/2026-08-15-grader-inputs-design.md` (Result);
  CLAUDE.md RETRACTED block.

### The Gemma-failure path marks a transcript done, so failed signals are permanently lost on resume
- **What we know:** `ego_trap/pipeline.py`'s Gemma-failure path skips a batch but still marks the
  transcript checkpoint done. On resume, those signals are permanently lost; on a forced re-run
  they double-count instead (`upsert_milestone_performance` does `attempts = attempts + 1` on
  conflict, and `gap_events` has only a SERIAL PK so re-processing appends duplicates). Recorded
  as **"Still open, noted not fixed."** Real precedent for the cost: the criteria A/B's baseline
  arm lost ~99 attempts to 2 Gemma batch failures, producing an +11.5% attempt drift between arms.
- **What we don't:** How often it fires in a normal run — never counted.
- **Cost to resolve:** Free to instrument; cheap to fix.
- **Where it's recorded:** CLAUDE.md, "Layer D (Ego Trap) realigned with the main pipeline",
  closing bullet.

### Soft skills are scored and have never been validated
- **What we know:** Layer D scores `soft_skills` on every exchange and writes gap events from
  them, but every validation run to date — the ceiling measurement, the criteria A/B, the
  grader-inputs trial — was **milestones only**. The rating scale was hardened (the prompt
  enumerates `excellent`/`adequate`/`failing`, and `_normalize_rating` clamps anything else to
  `adequate` with a warning, never to `failing`), but that is a robustness fix, not evidence the
  ratings mean anything.
- **What we don't:** Whether soft-skill ratings discriminate at all.
- **Cost to resolve:** Cheap — null-testable against the data the 100-call run already produced,
  same shape as the milestone null.
- **Where it's recorded:** CLAUDE.md, "Layer D over 100 CSM calls".

### The scoring metric has a noise floor that swallows most changes
- **What we know:** Two runs with **nothing whatsoever changed** gave `889 att / 28 hits (3.1%) /
  weighted 0.074` and `889 att / 33 hits (3.7%) / weighted 0.080`. So the band is **±0.006
  weighted** and **15.6% of milestones (37/237) move on their own**. Consequences, all recorded:
  the criteria rewrite's +0.025 is ~4.1x the band and is real; the uncoachable-skip's +0.006 is
  exactly 1.0x the band and its metric claim is **retracted** (the change was kept for a reason
  that never depended on the metric — it stopped 74 pieces of coaching advice instructing a CSM
  to do something impossible); **no per-milestone winner or loser from any A/B is citable**
  (24.6% observed movement against a 15.6% floor); and the variance is **upward-biased, not
  symmetric**, because at a ~3% hit rate almost everything sits at zero and a random flip can only
  go up. At this sample size **any change below ~+0.02 weighted is unmeasurable.**
- **What we don't:** What the floor is at 100 calls / 4,181 attempts — the floor was measured at
  19 calls / 889 attempts and has not been re-measured at the larger volume.
- **Cost to resolve:** Cheap-ish — one extra identical Layer D run (~230 calls, ~70 min), plus a
  mandatory `ops/clear_ego_trap_data.py` between arms.
- **Where it's recorded:** CLAUDE.md, "Layer C milestones were narration" (noise-floor block);
  `Brain/PROBLEMS_AND_FIXES.md`, "Part 5 — How much of this was real?".

### Step 0 false positives and a response window that grabs the wrong text
- **What we know:** Confirmed by reading real samples: a URL-configuration exchange
  (*"did you already make changes to the URL?"* / *"For the older job or the new job?"*) was
  matched to `contract_renewal_anxiety` and scored against a milestone about reframing "middle
  person" perception — the verdict was technically correct and the question was meaningless.
  Separately, `extract_csm_response_window` sometimes captures scheduling chatter instead of the
  substantive answer (seen in `rec6` @ turn 135).
- **What we don't:** The rate of either. Both were found by reading, never counted.
- **Cost to resolve:** Free to count against stored `gap_events` (`signal_turn_index` is a
  transcript turn number, so every event is traceable back to its source text).
- **Where it's recorded:** CLAUDE.md, "Still suppressing the rate" bullets.

### Only a minority of milestones are statistically powered, and closing that needs ~350+ calls
- **What we know:** Over 100 calls: 4,181 attempts across 378 milestones touched, mean 11.1,
  **median 7.0**. The distribution is 108 milestones at 0–4 attempts, 155 at 5–11, 89 at 12–22;
  **26 clear 23 attempts and 3 clear 83** (the strictest standard). Reaching a median of 25 needs
  **~350+ calls**, not the ~130 first quoted — because more calls also drag previously-untouched
  milestones into play, so any "how many calls do we need" estimate must model the milestone count
  growing too.
- **What we don't:** Whether 350+ CSM calls exist or can be obtained. Only 107 CSM transcripts are
  in hand, 100 of which were used.
- **Cost to resolve:** Needs data (more recorded calls), then a proportionally longer run.
- **Where it's recorded:** CLAUDE.md, "Layer D over 100 CSM calls".

### 7 CSM transcripts are excluded and cannot be scored
- **What we know:** 7 of 107 transcripts were excluded from the 100-call run via
  `run_ego_trap.py --exclude` (applied BEFORE `run_id` is derived): 6 whose **417 `Unknown
  Speaker` turns** cannot be attributed, plus `sample_call_priya_001`, which has no mapped CSM.
  Roster quality on the other 100 is now good — `ops/check_csm_speakers.py` had found **87 of 113
  speakers unclassified**, and classification **fails OPEN** (an unlisted Joveo colleague is
  scored as THE CLIENT, so internal chatter becomes coaching findings); this was fixed by deriving
  the roster from Avoma (103/103 per-meeting rosters fetched, 66 Joveo staff identified by
  `@joveo.com` email).
- **What we don't:** Whether the 417 `Unknown Speaker` turns are recoverable from Avoma, and what
  the 7 calls would contribute. Unexamined.
- **Cost to resolve:** Cheap — the Avoma fetch machinery already exists
  (`ops/backfill_csm_speaker_roster.py`, `ops/derive_joveo_roster.py`).
- **Where it's recorded:** CLAUDE.md, "Data quality before the run".

### PROPOSED DESIGN — call-level scoring has passed none of its four pre-registered gates
- **What we know:** The design is approved in brainstorming and partially built:
  `Brain/ego_trap/call_scoring.py` exists (untracked), `PROMPT_STEP3_CALL_LEVEL_BATCH` is in
  `shared/prompts.py`, and `layer_d.scoring_unit` / `layer_d.scenarios_per_request` are in
  `tuning.yaml` at `moment` / `3` — so **nothing runs until the key is deliberately changed**.
  Four gate checks are pre-registered and **all four are unrun**: (1) discrimination holds at
  **>= 70% of decided scenarios, p < 0.05, on two independent draws** — the bar the current scorer
  met at 77.4% and 82.3%; (2) **>= 95% of cited quotes verifiable** by string match against the
  transcript; (3) the `did_occur` null must answer "no" in **>= 90%** of deranged cases;
  (4) read the flips. Shape: ~2–3 requests per transcript against ~6 today, i.e. **cheaper**, with
  chunks of 2–3 scenarios because the binding constraint is **output** length (~60 tokens per
  criterion; at 20 milestones per request one batch in 21 already returned truncated JSON, and a
  missing id is recorded as a **miss**, so truncation manufactures coaching failures silently).
- **What we don't:** Whether any of the four gates pass. Named risks: the wider window invites
  fabrication (gate 2 exists for this, which is why `turn_index` is mandatory); `did_occur` is a
  coarser cousin of a question that has failed twice (1.22:1 and 64.9% vs 65.7%), with a fallback
  to top-1 matching if gate 3 fails. Gate 1 also requires a harness adaptation that **must not be
  skipped**: the unit of both the sample and the leakage holdout changes from a response to a
  call, and reusing the response-level sampler unchanged would score a whole call while claiming a
  per-response holdout.
- **Cost to resolve:** Cheap in calls (the trial harness pattern is ~230 calls per draw; gate 2 is
  free and model-free; gate 4 is reading ten samples).
- **Where it's recorded:** `docs/superpowers/specs/2026-08-15-layer-d-call-level-scoring-design.md`
  ("The gate", "Risks").

### PROPOSED DESIGN — switching `scoring_unit` silently redefines `attempts`, and old and new W are not comparable
- **What we know:** `milestone_performance.attempts` currently means "times this criterion was
  scored against a reply"; under call mode it becomes "times against a call" — **~25 moments
  collapse to ~1**. The design states this loudly: snapshot before switching and never plot the
  two on one axis. This codebase has been burned by exactly this class of change before.
- **What we don't:** Nothing unknown — it is a known hazard with a known mitigation that has not
  yet been executed because the switch has not been made.
- **Cost to resolve:** Free (a schema snapshot), but it must actually happen.
- **Where it's recorded:** Same spec, "Data model".

---

## 6. Measurement and methodology

### The random-null instrument is length-confounded, and the fix is unbuilt
- **What we know:** `calibration/audit_null_instrument.py` measured what had previously only been
  asserted. Good news first: `corr(lift, content-free share)` is **-0.55 / -0.82**, so at
  *scenario* level the metric does NOT reward junk — the cluster-level failure does not carry
  over. But `corr(lift, mean word count)` is **+0.65 / +0.64**. The null is size-matched and NOT
  composition-matched, so a random draw is a *mixture* of 3-word backchannel and 100-word
  explanations — maximally dispersed — and any scenario homogeneous in turn **shape** beats it.
  Proof by one row: **`client_direct_denial`, 98% content-free, mean 3.7 words, beats its null at
  +0.066 = rank 2 of 82.** A scenario of "No." passes. Length alone recovers only 6/11 and 7/16 of
  the passers, so it is a confound rather than the whole metric. Note the separate, related fact
  that at **cluster** level the same lift metric is actively perverse: `corr(lift, content-free
  fraction) = +0.527` clause / +0.555 turn, junk clusters averaging +0.160 lift against real ones'
  +0.107 — which is why check 1 was retired.
- **What we don't:** The true pass rate under a length-matched null. Until then, "beats a random
  null" must be read as "is homogeneous in shape", and the metric under-credits real situations
  expressed in short turns — the same bias that penalises terse expert moves in
  `2026-08-05-layer-b-combined-signal-analysis-design.md`.
- **Cost to resolve:** Free — draw the null matched to each scenario's own length distribution.
- **Where it's recorded:** CLAUDE.md, TWO CORRECTIONS block in the Layer A pool-unit section.

### The ceiling run has no arm pair that is both leakage-clean and population-symmetric
- **What we know:** `score_naren_ceiling.py`'s A1 and B are built from the same sampled rows, but
  A3 draws from a different pool entirely (secondary-label rows) — measured overlap `A1 ∩ A3` is
  **45 pair_ids** out of 371 / 346, with B at 383 — and the instrument gate `W(B) >= 0.5 × W(A3)`
  is applied across that boundary. The validity verdict flips on the pair chosen: A3/B = **1.61:1
  (fails)**, A1/B = **2.26:1 (passes)**. The missing arm — `a3_sample` scored against the partner
  rubric, named "B3" — was never built (~94 calls). Arm B is also model-split (793
  `gemini-3.1` + 1040 `gemini-3.5`), so full-arm B is W=0.0709 against the 0.090 same-model subset.
  **The consequence of that asymmetry was confirmed on 2026-08-15 and the headline "1.2:1" is
  RETRACTED**: measured symmetrically and leakage-clean, the grader discriminates on **77.4% and
  82.3%** of 69 scenarios across two independent draws (48-14-7 and 51-11-7, p=1.7e-5 and 2.8e-7,
  3,540 gradings each), pooled D 2.92 / 2.11. The cause is exactly the suspected one: arm B scored
  PRIMARY-label responses — the strongest exemplars of their scenario — against a partner rubric,
  and a strong substantive response satisfies generic criteria from anywhere, so **the null was
  inflated by how it was sampled** (`W(B)=0.090` vs the symmetric trial's `W(unrelated)=0.018–0.042`).
- **What we don't:** Nothing outstanding on the ratio — it is superseded. B3 remains unbuilt, and
  the ceiling's other numbers are still produced by asymmetric arms, so they should not be revived.
- **Cost to resolve:** N/A (superseded). Building B3 would be ~94 calls if ever wanted.
- **Where it's recorded:** CLAUDE.md, ceiling section (AMENDED 2026-08-13 + RETRACTED 2026-08-15);
  `docs/superpowers/specs/2026-08-15-grader-inputs-design.md`.

### Symmetric filtering — the rule this codebase has re-learned at least five times
- **What we know:** Any filter applied to one arm must apply to the other, or the comparison
  measures the filter. Five instances and four separate ad-hoc defences:
  `compare_criteria_ab.py`'s attempt-drift check (refuses above 15%),
  `replay_layer_c_admitted.py`'s volume-matched placebo, `trial_skills.py`'s as-written control,
  and the profile-rebuild spec's unconditional-`W` rule. Live examples: `score_naren_ceiling.py`
  (above) and `compare_embedders.py`'s `coupling` criterion (triggers sent as `RETRIEVAL_QUERY`,
  responses as `RETRIEVAL_DOCUMENT`, while bge had no task split at all — confounded). One caught
  before it cost anything: `trial_head_to_head.py` initially filtered the CSM's trigger but not
  the CSM's response, admitting 19.8% of replies as `"Yeah."`; fixing it also halved the length
  confound (median log length ratio −0.68 → −0.34).
- **What we don't:** Nothing — the rule is known. What does not exist is the enforcement: the
  stated check ("for every arm, list what was filtered, and diff the lists") belongs in the
  harness as a printed population diff or an assert, and **is not implemented anywhere**.
- **Cost to resolve:** Free (a shared helper).
- **Where it's recorded:** CLAUDE.md, Calibration gotchas; `Brain/PROBLEMS_AND_FIXES.md`, "The
  rule this project kept re-learning".

### Every threshold in `tuning.yaml` was calibrated against bge, and the Gemini path is now live in harnesses
- **What we know:** `embedding.backend` ships `local` (bge), and every knob — `relative_margin`
  0.95, `merge_cosine_threshold` 0.85, Layer C's p40 relevance percentile, Layer D's sink
  comparison — was derived from bge's cosine bands. Gemini's bands are different and measured:
  best-match p50 **0.686 vs bge's 0.558**; centroid band p10 0.722 / p50 0.810 / p90 0.886 giving
  a merge threshold of **0.97 vs 0.92**. Gemini also **wins** where it was tested
  (`sink_real_margin` 0.561 → 0.686) and **768 beats 3072** on that criterion (0.686 vs 0.672)
  while **3072 beats 768** for clustering after UMAP+HDBSCAN — the two findings do not transfer,
  and requesting 768 directly would have shipped the worse config with no way to notice.
- **What we don't:** What every threshold becomes under Gemini. The re-calibration, not the model,
  is the cost of the swap, and it has not been done. Also unmeasured at production scale: the
  gateway path's cost — `embed_content` does NOT batch (N texts = N requests; a 74k-clause
  backfill at the 1k/day cap is 74 days, making `client.batches.create_embeddings` mandatory
  rather than an optimisation).
- **Cost to resolve:** Expensive — every calibration sweep re-run in the new space.
- **Where it's recorded:** CLAUDE.md, "Embedding backend: local bge vs hosted Gemini" and "Gemini
  backend via the Joveo gateway".

### `compare_embedders.py` measured two of its three criteria wrongly, and did not persist what it paid for
- **What we know:** The `spread` criterion (p10–p90 of best-match cosine) measures the model's
  cosine **scale**, not its discrimination — the right measure is top-1 minus top-2 per trigger,
  which was never taken. The `coupling` criterion is confounded by asymmetric task types (above).
  And `sink_real_margin`'s published AUC of **0.437 is not "worse than chance"** — the signal is
  inverted by construction, so it is direction-correct and worth **0.563** corrected; a pass mark
  set at ">= 0.55" would have passed on zero improvement. Separately, the harness persisted only
  the derived scores, not the raw vectors, so changing a criterion costs another **461 requests**.
- **What we don't:** What the correct top1-minus-top2 comparison says. Never run.
- **Cost to resolve:** ~461 requests to re-embed, or free if the vectors are captured on the next
  run.
- **Where it's recorded:** CLAUDE.md, "Embedding backend" section.

### The default chat model changed, so every historical number is model-confounded
- **What we know:** `shared/gemma.py::_DEFAULT_MODEL` is now `gemini-3.5-flash-lite`, was
  `gemma-4-31b-it` (which stays last in the fallback chain because its 16k TPM ceiling could not
  hold this pipeline's prompts — one situated describe call burned 8+ minutes of backoff).
  **Every number recorded before 2026-08-13 was produced under `gemma-4-31b-it`.** The already-known
  instance: `arm0_baseline` (1.58) vs `arm0r_legacy_regen` (1.04). Model provenance is now
  recorded per verdict (`judged_by`) and per artifact (`models`), and it matters — run 2 of the
  head-to-head pinned 3.5-flash-lite and still blended 8–18% of batches under rate limits. Pinning
  correctly requires `fallback_enabled=True, fallback_models=()`; `fallback_enabled=False` also
  disables **key rotation**.
- **What we don't:** Which historical comparisons are actually invalidated. Nothing has been
  re-run to find out.
- **Cost to resolve:** Expensive to re-run anything historical; free to stop citing cross-model
  comparisons.
- **Where it's recorded:** CLAUDE.md, "Default Gemma model is now `gemini-3.5-flash-lite`".

### Known harness inconsistencies and pre-registration defects, left visible rather than corrected
- **What we know:** Three, all deliberately not rewritten after the fact. (1)
  `trial_grader_inputs.py` prints a **pooled** D (total hits / total attempts) while its bootstrap
  CI is over **per-item means** — run B is 2.11 pooled vs 2.75 mean-of-items, which is why its CI
  appears to exclude its own point estimate; the sign test is unaffected. (2) The same trial's
  pre-registered `D >= 2.0` bar was **mis-specified** — inherited from the ceiling's
  `_T_INSTRUMENT`, which was calibrated on the ceiling's asymmetric arms, so under a symmetric
  design the **control clears it unaided** and a printed PASS says nothing; the bar was left
  exactly as registered and the report prints a `PRE-REGISTRATION DEFECT` line. (3)
  `replay_layer_c_admitted._match_milestones` was **merge-blind** and inflated `by_cluster`'s
  result; fixed by adding a fourth `merged` outcome and normalising support by call count — and
  the fix reproduced its own prediction exactly (`matched + merged` equals the old inflated
  `matched` in both rejected arms: 172+83=255, 172+92=264).
- **What we don't:** Whether other harnesses carry the same class of defect. The stated general
  rule — when a category has more than two outcomes, print the full cross-tab instead of
  collapsing to a boolean — is not enforced anywhere.
- **Cost to resolve:** Free per harness; nobody has audited the set.
- **Where it's recorded:** `docs/superpowers/specs/2026-08-15-grader-inputs-design.md` ("Limits of
  this result"); CLAUDE.md, sink-pool diagnostic + Gemini-gateway sections.

### Sampling traps that have already produced wrong answers
- **What we know:** Two, both measured. (1) **Alphabetical is not a sample.** `--limit 8` on
  `trial_layer_c_arms.py` returned `ai_capability_discovery` … `budget_and_performance_strategy_optimization`
  — **every one subject-matter, not a single posture scenario**, because those all begin `client_`
  and sort after `budget`. The ceiling run measured those populations behaving differently
  (subject-matter mean gap +0.057, 2/25 inverted; posture −0.019, **5/15 inverted**), so an
  alphabetical prefix tests a fix on the half that already worked. **Four arm comparisons were run
  that way before the bias was noticed.** The floor is 15–20 scenarios via seeded stratified
  `--sample N`. (2) **An analysis script manufactures findings as readily as a measurement
  script** — one equality test against a four-valued enum turned 69 `merge_into` decisions (which
  mean RETAINED) into apparent sinks and produced a phantom "Gemma over-sinks 14.6% of the corpus"
  finding, now retracted; the true picture is that Gemma and nine blind judges agree **100% on
  what to discard** (of 138 genuinely sunk clusters, judges want **zero** back).
- **What we don't:** Whether every subset selector in `calibration/` has been checked for what it
  *excludes*. The stated generalisation says they should be; it has not been done.
- **Cost to resolve:** Free.
- **Where it's recorded:** CLAUDE.md, Calibration gotchas + Gemini-gateway section; pool-unit spec
  Status update 11.

### The content-free proxy has a false-positive class it cannot see
- **What we know:** A cluster of substantive-but-unrelated turns counts as subject-bearing — the
  `jovio` cluster is 563 turns across 50% of the corpus at only 4% content-free, glued by the
  company's own name. So the turn arm's **37.2% subject-bearing is an upper bound and must never
  be quoted as "71 coherent scenarios"**; the clause arm's 4.7% carries the same flaw, which is
  what keeps the comparison valid. Where it was cross-checked the proxy holds up: at min-16 the
  proxy says 39.6% subject-bearing, blind judges 38% coachable, Gemma retention 43.7%, and at
  >= 70% content-free the judges call **1%** coachable. (An earlier "the proxy was directionally
  wrong" verdict is **withdrawn** — that comparison excluded the 69 merged clusters.)
- **What we don't:** What fraction of the subject-bearing count is this false-positive class.
  Unmeasured; the account-concentration work (§2) is the closest proxy for it.
- **Cost to resolve:** Free to bound with the account data already fetched.
- **Where it's recorded:** Pool-unit spec CONCERNS REGISTER item 3 and Status updates 10–11.

### bge embeddings are not reproducible across runs unless cached
- **What we know:** CUDA matmul reduction order varies, so the same corpus re-embedded from
  scratch yields slightly different vectors, and UMAP/HDBSCAN amplify that into different cluster
  counts — **241 → 231 → 226 raw clusters** observed for one identical corpus. The float32
  `embed_cache.db` is what pins results. Gemini embeddings are deterministic and reproduce exactly
  (292 raw → 245 merged across four separate process launches, verified position-for-position),
  which removes one of the two variance sources — but the backend ships `local`.
- **What we don't:** Nothing outstanding; the mitigation (keep the cache) is known and followed.
  Recorded because deleting the cache silently invalidates every calibration comparison.
- **Cost to resolve:** N/A.
- **Where it's recorded:** CLAUDE.md, Embedding API section.

---

## 7. Operational / infrastructure

### There is no `run_id` on the data tables, so two pipeline runs cannot coexist
- **What we know:** `calls`, `scenarios`, `kb_pairs` and `rubrics` have no run column and each has
  a UNIQUE constraint (`calls.filename`, `scenarios.scenario_key`, `rubrics.scenario_id`, a unique
  index on `kb_pairs(call, turn)`), so a second run collides rather than coexisting. The
  workaround is a server-side schema copy (`CREATE SCHEMA baseline_<date>; CREATE TABLE … AS
  SELECT * FROM …`), which copies rows only, no constraints. And **skipping `ops/clear_data.py`
  does not preserve a run, it produces a no-op run** — `run_id` is a hash of the sorted transcript
  stems, so re-running the same 416 transcripts yields the same `run_id` and `checkpoints.db`
  reports the work as already done.
- **What we don't:** Nothing unknown. It is the same structural gap as multi-tenancy (§1), one
  level down, and any tenancy design has to solve both.
- **Cost to resolve:** Expensive — schema change plus every reader.
- **Where it's recorded:** CLAUDE.md, Gotchas.

### Layer D re-runs double-count unless data is cleared first, and a re-run can silently re-point `milestone_id`
- **What we know:** `gap_events` has only a SERIAL PK so re-processing **appends duplicates**, and
  `upsert_milestone_performance` does `attempts = attempts + 1` on conflict so it **double-counts**.
  Separately, `upsert_rubric`'s `ON CONFLICT (scenario_id)` keeps `rubric_id` stable while
  replacing `milestones`, and `milestone_id` is the **1-based array position** — so a Layer C
  re-run can make `M2` mean a different milestone while rows keep accumulating under it. The
  operational rule is to run `ops/clear_ego_trap_data.py` before any real re-run and after any
  Layer C re-run.
- **What we don't:** Nothing unknown — it is a live footgun with a known procedure, not an open
  question.
- **Cost to resolve:** Free to follow the procedure; a constraint-level fix is a schema change.
- **Where it's recorded:** CLAUDE.md, Layer D realignment, "Operational rule".

### "The background task was reported stopped" is not evidence a process died — it cost a full run
- **What we know:** On 2026-08-10 a Layer D run reported as stopped by the agent harness kept
  running. The tables and checkpoints were cleared and a replacement launched, so **two runs shared
  one database and one `checkpoints.db`**: the survivor kept marking transcripts done, the new run
  skipped 10 of 19 as `already done`, and `attempts` inflated **889 → 905** across 28 doubly-scored
  signals. **The log still printed `Ego Trap batch complete`** and the noise-floor script still
  reported a plausible-looking number. Check the OS process list, not the harness — and note the
  venv `python.exe` is a shim that re-execs the base interpreter, so **one run always shows as two
  PIDs**; two PIDs is normal, two different start times is not. `ops/run_noisefloor.ps1` now
  performs this check automatically and aborts before clearing, and
  `calibration/measure_scoring_noise.py` **refuses** to report a floor unless each arm is provably
  a single run.
- **What we don't:** Nothing — fully diagnosed. Recorded because the guard exists only in two
  scripts, not in every clear/run path.
- **Cost to resolve:** Free to extend the guard.
- **Where it's recorded:** CLAUDE.md, Layer D realignment; `Brain/PROBLEMS_AND_FIXES.md`, "A
  run-destroying operational trap".

### `reconnect_if_closed` is required before DB writes in any slow loop and is never automatic
- **What we know:** `storage.get_connection()` must use `autocommit=True` (a bare read left
  uncommitted holds a transaction open across slow Pinecone/Gemma calls until Neon kills it with
  `IdleInTransactionSessionTimeout`) and uses TCP keepalives (idle=30s, interval=10s, count=5).
  But `reconnect_if_closed(conn)` must be called **explicitly** before any DB write in a loop with
  slow work between iterations. The same missing call has recurred at least three times
  independently: V2 Layer A's adjudication loop (fixed by making no DB calls at all inside the
  Gemma loop), and twice in the response-taxonomy auto-pass (after `adjudicate_clusters` and
  after `_generate_metadata`). A related, more expensive variant: one scored run finished all 95
  LLM calls and then lost every result, because the results were assembled into a structure
  containing one small database lookup and written to disk only afterwards. The rule learned:
  **never let a free operation gate the persistence of an expensive one** — flush paid results
  first.
- **What we don't:** Whether any remaining call site is missing it. Never audited.
- **Cost to resolve:** Free to audit.
- **Where it's recorded:** CLAUDE.md, Gotchas; `Brain/PROBLEMS_AND_FIXES.md`, "Reliability and
  infrastructure fixes".

### The test suite cannot be run in one process on this machine
- **What we know:** spaCy `en_core_web_lg` needs a **contiguous 392MiB** vector table and four
  test files load it. Collection dies with `_ArrayMemoryError` / `MemoryError` /
  `ValueError: Could not reserve memory` / `OSError [WinError 1455]`. **Free memory is not the
  predictor** — it failed at 2.1GB free *and* at 2.7GB free, with a 20GB pagefile and 4.7GB commit
  free; killing 4 stale python processes freed only ~76MB and changed nothing. It is
  address-space fragmentation, not exhaustion. One file per process always works and yields the
  same result.
- **What we don't:** Nothing further — root-caused and worked around. Recorded because it means
  there is no single command that proves the suite green.
- **Cost to resolve:** Free (the per-file loop); a real fix would mean not loading the large model
  in tests.
- **Where it's recorded:** CLAUDE.md, Gotchas.

### The gateway's `/embeddings` silently returns fewer vectors than inputs when batched
- **What we know:** It collapses **intermittently** — the same request batches or collapses
  depending on when it is sent — and it hits SHORT text hardest, which is **29% of this corpus**.
  It first surfaced as an `IndexError` several lines downstream because 161 scenarios in 2 batches
  produced 2 vectors; **had the count been 2 it would have run clean and produced fabricated
  numbers.** The rule is: never batch, get throughput from **concurrency** (one text per request,
  N workers — measured 24k requests at ~46 req/s with 20 workers, ~8 minutes), and assert one
  vector per text. Related: fetch the native 3072 width and truncate locally, keying the cache on
  the **native** width (Matryoshka validated over 11,977 real turns, min cosine 1.000000) —
  keying on the analysis width would make `--width 768` miss every row and re-pay 24k requests.
  And `genai.Client` must be cached at module level or it is garbage-collected mid-request.
- **What we don't:** Whether the gateway defect is fixed upstream. Never re-tested.
- **Cost to resolve:** Free to re-test; the workaround is already in the harnesses.
- **Where it's recorded:** CLAUDE.md, "Gemini backend via the Joveo gateway".

### Layer A adjudication must stay sequential, and it is now the throughput bottleneck
- **What we know:** The adjudication prompt carries "NEAREST SCENARIOS ALREADY ACCEPTED", and that
  accumulating list **is** the duplicate-detection mechanism — 69 merges fired at min 16.
  Concurrency was right for embeddings (independent requests) and is wrong here: it is an ordered
  dependency, not a throughput problem. With embeddings now at ~46 req/s, adjudication is what
  bounds a full taxonomy rebuild.
- **What we don't:** How long a full 245-cluster sequential adjudication actually takes end to
  end, and whether any partial parallelisation preserves the dependency. Unexplored.
- **Cost to resolve:** Free to time; any restructuring is a design task.
- **Where it's recorded:** CLAUDE.md, "Gemini backend via the Joveo gateway".

### `run_ego_trap.py` fires Gemma calls back-to-back with no pacing
- **What we know:** There is no rate limiting across transcripts. `STEP_0_MODE=gemma` doubles call
  volume (Step 0 + Step 3 per transcript) and increases 429/503 retry-backoff stalls —
  `gemma.py`'s backoff can add **up to 62s per call**. `gemma.py` retries max 5 with exponential
  backoff on 429/500/503/504/internal/deadline errors, with a 3-minute HTTP timeout, and now
  retries `httpx.TransportError` **by type** rather than by string-matching error text (the
  string-marker check could not keep up with how many ways a socket layer phrases a drop).
- **What we don't:** What the optimal pacing is; never measured.
- **Cost to resolve:** Free to add pacing; free to measure from existing logs.
- **Where it's recorded:** CLAUDE.md, Gotchas + Brain Architecture Notes.

### Test runs write into the production log file
- **What we know:** `response_taxonomy_auto_pass.py` is the first Brain module to use a persistent
  `logging` file handler instead of `print()`, and that handler is a module-level singleton — so
  pytest runs against the module silently wrote fake `candidate_id` / `scenario_key` entries into
  the real production log unless a test explicitly disables it
  (`monkeypatch.setattr(module._logger, "disabled", True)`).
- **What we don't:** Whether existing production logs already contain test-injected rows. Never
  audited.
- **Cost to resolve:** Free.
- **Where it's recorded:** CLAUDE.md, "Response-taxonomy auto-pass", "New gotcha".

### A large body of work is uncommitted, including fixes for real crashes
- **What we know:** The pool-unit switch, its harness, the spot-check script, 9 tests, two
  CLAUDE.md entries and the pool-unit spec were all uncommitted at the time of that verdict;
  `Brain/ego_trap/call_scoring.py` is untracked today, with `shared/prompts.py` and `tuning.yaml`
  modified alongside it. Two crash fixes were also recorded as sitting uncommitted in the working
  tree when they were written: the `httpx.TransportError` retry fix, and the
  `shared/storage.py::upsert_scenario` bloom-level guard that clamps an invalid Gemma enum value
  (a run had already crashed on `bloom_level="explain"`). Related discipline note: **`.gitignore`
  never applies to already-tracked files** — `Brain/*.log` sat in `.gitignore` while 19 logs
  stayed tracked, carrying 5.2MB of run output into git; the fix is `git rm --cached`.
- **What we don't:** Whether every one of those fixes has since landed. Not verified here.
- **Cost to resolve:** Free.
- **Where it's recorded:** Pool-unit spec, "Applies to all of the above"; CLAUDE.md, V2 clustering
  verdict block and Gotchas; verified against `git status`.

### Pinecone cannot express the sink filter, so retrieval runs against Postgres
- **What we know:** ~40% of the `"triggers"` namespace is itself sink-filed and its metadata
  carries **no `is_coachable`**, so the sink-rejection rule is not expressible against Pinecone
  without a per-match DB round trip. The stored exemplar's `scenario_key` is also layer_b's scalar
  best match — exactly the assignments the sink-rescue investigation documented as unreliable —
  and the utterance-vs-utterance cosine band has never been calibrated here. Consequently
  `query_triggers` is **not used for matching** (kept only as a `--pinecone-compare` measurement),
  and head-to-head retrieval runs against Postgres for the same reason.
- **What we don't:** Whether Pinecone earns its place at all in the current architecture — it is
  storage/retrieval only (it does no embedding) and the two paths that would use it both bypass
  it. Never asked.
- **Cost to resolve:** Free to answer by reading; removing it would be a design change.
- **Where it's recorded:** CLAUDE.md, Layer D realignment and head-to-head sections.

### Design specs cite pre-2026-08-08 script paths, deliberately
- **What we know:** Specs under `docs/superpowers/specs/` still reference `dry_run_layer_a.py`
  rather than `calibration/dry_run_layer_a.py`, from before the `ops/` and `calibration/` moves.
  Left alone as dated historical records; CLAUDE.md and each script's own docstring carry the live
  paths.
- **What we don't:** Nothing. Recorded so a stale path in a spec is not read as a bug.
- **Cost to resolve:** N/A — deliberate.
- **Where it's recorded:** CLAUDE.md, Gotchas.
