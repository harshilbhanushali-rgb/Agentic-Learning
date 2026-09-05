# Layer D redesign: gap analysis against playbooks (2026-08-20)

[Back to the index](INDEX.md)

**Status: DESIGNED AND BUILT, ZERO MEASUREMENTS.** This file currently records the design
decisions, the literature sweep they rest on, and the pre-registered gates. The C-stage
results get appended here as they run — until C0–C3 have passed, nothing in
`Brain/layer_d/` produces numbers anyone should trust.

Spec: `docs/superpowers/specs/2026-08-20-layer-d-redesign-design.md`.
Handoff: `Brain/HANDOFF_LAYER_D_REDESIGN_2026-08-20.md`.

## 1. Why a redesign instead of repair

The rubric-era Layer D (`ego_trap/`) accumulated a failure record that is criterion-level,
not bug-level, and its substrate died: `rubrics` is empty since the union taxonomy
replacement, and every `layer_d` threshold was fitted to bge@768 bands that gemini@3072
inverts. The operator decisions (2026-08-20): score against **live playbooks**
(`key_moves` M1..Mn — the artifact whose positional ids were designed for exactly this);
run on whatever playbooks are live; deliver **ranked coaching priorities** (no headline
score, no severity buckets — the old ones were never fitted); stage all spend behind
pre-registered gates; and **build both grader arms**, letting a head-to-head choose.

## 2. The five inherited failure modes and their fixes

| Measured failure (see layer-d-realignment.md, layer-d-100-calls.md, the 2026-08-15 specs) | Redesign answer |
| --- | --- |
| Criteria unpassable: W(matched) ≈ 0.09; 87 dead criteria ate 24% of 4,181 attempts; 23/82 rubrics never satisfied once | Playbook moves as criteria + a **dead-check flag keyed to Naren's own rate** (a check the expert fails > floor is a bad check, excluded from ranking, surfaced to the operator) |
| 15.6% of milestone scores flip between identical runs (±0.006 W noise floor) | Binary atomic checks + optional k-run majority consensus (`grader_k_runs`), unscored on disagreement; noise floor re-measured at C2 |
| Call-level scoring fabricated evidence: 23% of credits unlocatable, quotes traced to transcripts the model never saw — REJECTED by its own gate | Moment-level only; **mandatory verbatim quote per credit, verified programmatically** (`verify_quotes.py`, containment + best_span ≥ 0.80); unverified credit → `unscored`, never counted |
| Absolute floors failed every time (0.35 floor admitted 100% of turns); sink-relative comparison works (57.3% rejection) | Sink-relative admit unchanged at the signal layer; **relative interpretation at the score layer too** — a gap is `naren_rate − shrunken_csm_rate`, never an absolute number |
| Median criterion needs ~350+ calls for stable estimates; 108/352 milestones below 5 attempts | Rates over moments (not per-call scores), **empirical-Bayes shrinkage** toward the attempt-weighted CSM-cohort prior, and a `min_attempts_to_rank` floor on BOTH sides of every ranked gap |

Plus four operational defects fixed by construction: the 98.6% segmentation artifact
(client-move arm E, pre-registered at +81 scored / 0 lost), checkpoint-marks-failed-batches
(checkpoint-on-success-only), gap_events double-counting (natural-key upsert + full-recompute
`move_performance`), and fail-open speaker classification (roster-gated, fail-closed).

## 3. The literature sweep (2026-08-20, web research; input to the design)

Searched: LLM-as-judge reliability, evidence-grounded scoring, industry call-scoring
practice, IRT/psychometrics for LLM grading, noisy-grader statistics, checklist vs holistic
evaluation. The findings mapped 1:1 onto the failure table above — none of the design is
novel mechanism, all of it is published remedy.

**Checklist vs holistic.** CheckEval (EMNLP 2025, arxiv.org/abs/2403.18771): decomposing
criteria into atomic BINARY questions raised inter-evaluator agreement by +0.45 and reached
Fleiss' κ 0.72; Likert conflates sub-criteria and is unstable. → `layer_d_checks` /
per-move criteria stay binary. Caveat (The Stability Trap, arxiv 2601.11783): binary checks
reduce ambiguity variance, not sampling variance — repeats/consensus still needed.

**Evidence grounding.** Rulers (arxiv 2601.08654) names the failure triad (rubric execution
drift, unverifiable score attribution, human-scale misalignment) and prescribes structured
checklists with typed evidence + extractive quote verification. EGS-style verification
(fuzzy token overlap at ~80%, via ViDR arxiv 2605.13034) is a drop-in programmatic gate;
FActScore/VeriFastScore-style extraction-then-verify pipelines audit at ~0 hallucinated
claims (401/401 clean in VeriFastScore's manual audit). → `quote_verify_min_overlap: 0.80`,
credit refused on failure.

**Relative vs absolute judging.** Reference-Anchored Elo Estimation (RAEE,
openreview.net/forum?id=Q88mQBuPjB): anchoring every comparison to a fixed reference cuts
per-run standard error ~44% and cross-judge coefficient of variation ~72% vs direct
scoring. Position bias is systematic and worst between close candidates (arxiv 2406.07791,
15 judges / 150k instances); JudgeLM's swap augmentation is the standard control. →
the pairwise arm is order-swapped with position-consistent verdicts only; the checks arm
gets its relative interpretation at aggregation (rate vs measured Naren rate).

**Verdict instability is general.** Rating Roulette (EMNLP 2025 Findings): LLM judges have
low intra-rater test-retest reliability across runs — our 15.6% flip rate is the documented
norm, not a prompt bug. G-Eval's probability-weighted aggregation and k-run consensus are
the standard remedies; G-theory D-studies (arxiv 2507.19980) say how many repeats buy a
target reliability. → `grader_k_runs` + majority-of-scored consensus; C2 measures the
residual floor. **Warning that frames all of it** — Reliability without Validity (arxiv
2606.19544): judges can agree with each other and be consistently wrong, so C4 keeps a
small human-judged gold set in the ladder.

**Psychometrics / dead items.** IRT diagnosis of LLM judges (arxiv 2602.00521): criterion
unreliability is criterion-INTRINSIC and detectable (some criteria unreliable across every
judge model, marginal reliability ρ 0.34–0.53); LLMs over-discriminate 1.0–4.4× vs humans;
don't ask an LLM which items discriminate (arxiv 2606.18709) — measure it. Adaptive testing
(arxiv 2511.04689) and ability pooling cut required n severalfold. → classical item stats
(pass rate + discrimination) in the first run's report; full IRT deferred until volume
justifies it.

**Industry practice (Gong / Observe.AI / Cresta).** The stable unit everywhere is the
**behavior occurrence rate vs a benchmark**, not an absolute per-call score: Gong Smart
Trackers are sentence-level semantic classifiers (50–100 tagged examples per tracker,
500+ calls minimum, heavy false-positive maintenance — the same per-item-threshold
pathology this project refuted nine times); Observe.AI/Cresta LLM Auto-QA scores
scorecards of 12–14 binary questions at ~88–91% human agreement and compares reps via
rate dashboards. → "you do X in 12% of relevant moments; the benchmark does it in 60%"
is the product primitive, which is exactly the dual-population design.

**Sparse cells.** Empirical-Bayes shrinkage toward a cohort mean weighted by observation
count is the standard remedy for per-rep per-skill estimates at n<10 (arxiv 1906.01611
lineage). → `shrinkage_prior_strength`, attempt-weighted cohort priors, and raw + shrunk
rates both reported so nobody mistakes the prior for data.

**BARS / coaching output.** Behaviorally-anchored rating scales work because levels are
anchored in observed incidents; LLM-coaching studies that ground feedback in expert
exemplars (surgeon NTS coaching, npj Health Systems 2025; peer-counselor feedback,
arxiv 2403.15482) measurably land. → every ranked gap carries the playbook's verbatim
Naren evidence (the standard) plus up to two transcript-verified CSM quotes (what
happened).

## 4. What was built (2026-08-20, zero spend)

`Brain/layer_d/` (segmentation / signals / verify_quotes / graders / aggregate / pipeline /
prompts), `move_events` + `move_performance` DDL (natural-key upsert; full-recompute
materialization; both in `ship_union_taxonomy.py`'s snapshot and delete chains), five
storage helpers, seven `tuning.yaml layer_d` keys (rubric-era keys retained until
`ego_trap/` retires), `ops/run_layer_d.py` / `ops/clear_layer_d_data.py`, the C0 harness
`calibration/layer_d_bands.py` (bill-only without `--spend`), 99 tests in 6 files, and the
AST no-calibration-imports guard extended to `layer_d/`. Full suite green file-by-file.

The four-state verdict vocabulary (`hit/partial/miss/unscored`) is the one structural
novelty worth restating: **`unscored` is an instrument failure and never counts as an
attempt** — id missing from the response, quote unverified, swap-inconsistent, run
disagreement. The old pipeline normalized all of these to `miss`, so output truncation
manufactured coaching failures.

## 5. Pre-registered gates (frozen before any spend)

| Stage | Spend | Gate |
| --- | --- | --- |
| C0 bands (`layer_d_bands.py --spend`) | ~6.5k embeddings, zero chat | report-only; operator reads before C2 may spend |
| C1 segmentation replay (free after C0) | zero | arm E lost=0 reproduced in gemini space; real-minus-sink margin does not fall |
| C2 grader head-to-head (~60 moments, both arms, k=3) | ~400–600 chat calls | per arm: quote verification ≥95%; discrimination ≥70% per-scenario paired win share, p<0.05; noise floor reported. Highest-discriminating arm passing both hard gates ships `grader_arm`; tie → checks |
| C3 Naren ceiling (benchmark pass, 5 live playbooks) | ~150–400 chat calls | per-check Naren rates published; sub-`dead_check_naren_floor` checks flagged BEFORE production |
| C4 reader panel (~15 moments) | ~zero | agreement bar set with the operator before reading |

Any gate failure ⇒ stop, bring the operator fallback options. C2/C3 harnesses are not yet
written; each gets one blind code audit before it spends.

## 6. Results

### C3 first — the Naren benchmark pass ran BEFORE C0/C1/C2 (2026-08-23, operator-sequenced)

The operator chose to test the instrument on Naren first, which needs no CSM embeddings
and no client roster. Spend: ~30 chat requests total (a 6-sample smoke, then the full 30
moments × 5 live playbooks, checks arm, k=1, gemini-3.5-flash-lite via gateway).
Run: `ops/run_layer_d.py --naren-only --naren-sample 30` (run_id 1096ccdc14ab), after
`move_events`/`move_performance` were created on the live DB (targeted DDL, not full
schema.sql).

**The blind audit before the run caught a run-killing defect the green test suite hid:**
the pipeline read playbook rows FLAT while `storage._playbook_row_to_dict` nests content
under `"playbook"` — every scenario would have KeyError'd before the first chat call, and
`situation_signature` would have silently vanished from every prompt via a `.get` default.
The test fixture had monkeypatched `get_playbooks` with the flat shape (a false green).
Fixed via `pipeline.live_playbooks_flat` (the single flatten point), fixture corrected to
the real nested shape, plus a dict-wrapped-JSON unwrap in both parsers (`_as_entry_list`)
for the one silent-waste path the audit flagged.

**Instrument health: works end to end.** 150 moments graded, 0 failures, 0 checkpoint
anomalies, re-run converged (natural-key upserts). Unscored: 19/~720 verdicts (2.6%) —
18 `missing_from_response` (ONE batch on playbook 10 dropped 6 moments × 3 moves; the
old pipeline would have recorded those as 18 manufactured misses) and exactly 1
`quote_unverified`. Sampled hit quotes read as REAL move performances (substantive,
verified verbatim).

**The substantive finding: Naren passes his own playbook's checks at 0.00–0.20 per
moment (overall ~11%), and widening to per-call occurrence (free reframe over stored
events, `bool_or` per call) only lifts it to 0.00–0.29.** This REPRODUCES the rubric-era
ceiling finding (per-reply 14.9% vs per-call 16.7%; "the criteria are unpassable") in the
new instrument at similar magnitude: playbook moves are distilled from ~50 curated
best-evidence items and describe his HIGHLIGHTS, not his routine per-moment behavior.
Consequences, exactly as the design anticipated:

- **Gaps stay meaningful as rate DIFFERENCES** against these measured rates (a CSM at
  0.00 vs Naren at 0.24–0.29 on a well-measured check is a real, coachable gap), but
  nobody should ever read these rates as absolute quality scores.
- **`dead_check_naren_floor: 0.50` is wildly mis-set for a per-moment unit** — at 0.50
  it flags all 20/20 checks. The measured distribution suggests ~0.10: that flags 5–6 of
  20 checks (pb2-M1 0.03, pb8-M1 0.00, pb8-M2 0.03, pb8-M3 0.00, pb10-M3 0.04) — an
  echo of the old 24%-dead-criteria rate. Playbook 8 is the outlier (2 of 4 moves at
  0.00 over ~18 calls). VALUE NOT YET CHANGED — operator decision.
- The absolute level does NOT decide instrument quality — discrimination does, and that
  is C2's question (the old scorer discriminated 77–82% despite W≈0.09).

Per-check table (playbook_id, move, hits/attempts, per-moment rate → per-call rate):
pb2 M1 1/30 .03→.05 | M2 6/30 .20→.24 | M3 3/30 .10→.14 | M4 4/30 .13→.19 ·
pb4 M1 5/30 .17→.28 | M2 6/30 .20→.28 | M3 2/30 .07→.11 | M4 2/30 .07→.11 ·
pb6 M1 4/30 .13→.24 | M2 5/30 .17→.29 | M3 4/30 .13→.18 | M4 4/30 .13→.18 | M5 5/30 .17→.29 ·
pb8 M1 0/30 .00→.00 | M2 1/30 .03→.06 | M3 0/29 .00→.00 | M4 2/30 .07→.11 ·
pb10 M1 4/24 .17→.17 | M2 3/24 .12→.13 | M3 1/24 .04→.04

Open after this: set `dead_check_naren_floor` from this distribution (or make it a
per-call criterion); decide whether the benchmark denominator should also be published
per-call; then C0 (CSM-turn embeddings) → C1 → C2 as pre-registered.

### C3 full 33-playbook benchmark, gemini-3.6-flash @ medium reasoning (2026-08-23)

Operator switched the grader to the reasoning family (`grader_model: gemini-3.6-flash`,
`grader_reasoning_effort: medium`; provenance now stored per row in
`move_events.grader_model`, and model+effort are part of the checkpoint identity).
986 Naren moments across all 33 live playbooks, ~165 requests, ZERO failures, ZERO
malformed generations (the flash-lite run had 1/33 scenarios die on non-JSON; a bounded
resample now exists in `pipeline.gateway_chat` and never fired under 3.6).

**Result: the reasoning grader is roughly 2x STRICTER on the same moments.** Overall
Naren rate 0.057 (vs 0.11 under flash-lite on the 5-playbook subset; partial flash-lite
baseline preserved in `artifacts/layer_d_naren_flashlite_baseline.json`). Median check
rate 0.03; p90 0.13; **92 of 123 checks sit below 0.10**, including four whole scenarios
at or near zero (budget_allocation 0/90, regional_talent 0/120, gig_economy 1/150,
landing_page 1/120). Unscored: 124, all `missing_from_response`, concentrated as exactly
ONE dropped 6-moment batch in each of 5 scenarios — the reasoning model sometimes
returns valid JSON covering only some requested moments (a completeness re-ask for the
missing moment_ids is the obvious cheap fix; NOT built yet).

**What this establishes:**
1. **Absolute rates are grader-relative** (0.11 vs 0.057 for the same behavior) — which
   confirms the core design decision: only within-instrument comparisons (Naren vs CSM
   under the SAME model/prompt/arm) are meaningful. Nobody should ever quote a Layer D
   rate without its instrument identity.
2. **The per-moment unit + arc-level checks = denominator inflation.** A move like
   "map the end-to-end workflow" cannot be performed in every reply within a scenario,
   so most sampled moments are structurally ineligible and the expert's measured rate
   is pushed toward 0. This is the same shape as the rubric-era "criteria unpassable"
   finding, now isolated to the UNIT/CHECK-WORDING interaction rather than the scorer.
3. At base rate ~0.06, CSM-vs-Naren rate differences lose statistical power — the
   gap product thins out unless the base rate is raised (better-worded per-moment
   checks, a partial tier) or the comparison goes relative per moment (pairwise arm).

Options tabled to the operator (2026-08-23): add a `partial` tier to the checks arm
(measured precedent: the criteria-rewrite A/B moved partials 3.7%→7.6%, a real ×1.6
signal gain); rewrite `layer_d_checks`/criteria into per-moment-observable form (the
"improve playbook" branch, ~35 chat calls); lean on the pairwise arm at C2 (absolute
rates cancel by construction); per-call occurrence as the published benchmark unit;
evidence-adjacent conditioning of the denominator (risky — per-item filters have failed
nine times; would need its own gate).

### Cross-session convergence with the playbook-quality audit (2026-08-23)

A parallel session's blinded reader audit of a 28-document playbook backfill (NOT yet
loaded to Postgres; quote-usability 73% vs the live batch's 63%) independently found:
**roughly half of the ~80 criteria cannot be graded yes/no from a transcript** — the
gradable ones name a specific artifact/number/structure ("state an SLA turnaround
number"), the ungradable ones use evaluative adjectives ("clearly explain business
impact"). Same defect as this file's C3 diagnosis, reached from the reading side.

**A quantitative cross-check on the C3 data was INCONCLUSIVE**: classifying the 123
live checks by keyword regex (evaluative-adjective vs artifact-naming) shows NO rate
separation (mean 0.064 vs 0.052). Either the crude classifier fails to reproduce the
reader's judgment (likely), or the two problems STACK — wording ungradability AND
per-moment applicability (a gradable "state the SLA number" is still only applicable
in a few moments per conversation). Do not treat the wording rewrite as guaranteed to
fix the benchmark rates.

**The coordination this sets up (pre-registered expectation):** the other session's
next iteration bakes a gradability rule into synthesis ("a criterion must name
something present or absent in a transcript; no evaluative adjectives") plus a
mechanical question-filter at snap. When that batch loads as the live playbooks, the
Naren benchmark re-run (~165 calls, same instrument: gemini-3.6-flash @ medium) is the
NUMERIC pre/post measurement their 5-document probe cannot provide (their probe
overestimated 95%→73% on the last batch):

- rates jump toward 0.2–0.4 → wording was the dominant driver; checks arm viable
- rates stay ≈0.06 → per-moment applicability dominates → the unit/arm must change
  (partial tier, per-call occurrence, or the pairwise arm at C2)

Current C3 table (this file, above) is the frozen "pre" baseline.

### THE PRE/POST RESULT: wording was NOT the driver — the UNIT is (2026-08-24)

The pbq gradability remakes of the OG-5 (loaded via `ops/load_playbooks.py --apply`,
all seven gates PASS, pbv originals → `superseded`, playbook_ids 429–433) were
benchmarked on the same 150 moments with the same instrument (3.6-flash @ medium,
run_id 1096ccdc14ab restricted via the new `--scenarios` flag; checkpoint items now
carry the playbook_id so a remade document regrades instead of reusing the superseded
one's marker). Zero failures, zero unscored.

**Naren's per-moment rate went DOWN: 0.050 (old documents) → 0.031 (gradability
remakes), same moments, same grader.** Per-call occurrence doesn't rescue it either:
0.00–0.24, with landing_page at 0 across all 18 calls under BOTH document generations.
The pre-registered decision rule therefore fires on its second branch, decisively:

**The check wording was never the binding constraint on the benchmark rate — the
per-moment unit is.** The mechanism is now legible: the gradability rule makes
criteria MORE specific (concrete artifacts, often conjunctions — "detail login
friction mechanisms AND offer a no-login/chatbot option"), and specificity NARROWS
per-moment applicability. The reader audit and this benchmark are both right about
the same documents: 89% usable quotes / zero vague criteria (excellent DESCRIPTIONS
of highlight behavior) and a 3% per-moment pass rate (impossible per-moment
EXPECTATIONS). A playbook move is a whole-arc accomplishment; no wording fixes that.

Consequences:
1. **Do NOT iterate playbook wording further for Layer D's sake.** The gradability
   rule stays (it is better content) but it cannot move the benchmark rate.
2. **The checks arm's absolute per-moment verdict is structurally mismatched** to
   playbook moves. Its remaining chance inside C2 is the `partial` tier (conjunctive
   criteria make partial credit meaningful).
3. **The pairwise arm is now the a-priori favourite for C2**: "which reply handles
   this move better" is answerable even when neither reply fully performs the move —
   it never needs the absolute per-moment event that Naren himself produces at 3%.
4. landing_page_and_conversion_setup is 0 under every unit and both generations —
   likely a scenario whose moves simply do not recur in routine moments; candidate
   for exclusion from any benchmark denominator.

### C0 + C2 RAN AND DECIDED THE ARM: `grader_arm: pairwise` (2026-08-24)

**C0** (`layer_d_bands.py --spend`): 6,503 CSM client turns embedded (cached
forever). Sink rejection 65.6% (bge reference 57.3%); best-coachable band p50 0.641
vs best-sink p50 0.668. **Arm e admits 1,231 moments, 1,230 on live playbooks over
32 scenarios** (arm today: 1,130) — the CSM-side population is rich, not sparse.
**C1 closed by construction + C0 evidence**: production arm e can only ADD moments
where the last-turn rule rejects (cannot lose one), and C0 shows +101 with a sane
margin band; the full replay was deemed redundant.

**Prerequisite built: the verified client roster.** `ops/build_client_roster.py`
derives `csm_recordings/client_speakers.txt` from the 103 Avoma `.speakers.json`
rosters (232 verified client identities + name variants; email domain + is_rep are
the ground truth). Gate result: 100/106 transcripts pass; all 6 exclusions are
Avoma's "Unknown Speaker" — the unattributed-diarization contamination the corpus
audit flagged, correctly refused.

**The C2 harness's blind audit found 3 HIGH defects before spend, all fixed:**
the checks arm was unbatched (6× the approved bill AND a non-production instrument
variant); no partial persistence (one crash = every no_cache verdict re-paid; now
flushes per moment + `--resume`); and the population skipped the speaker gate in an
ARM-ASYMMETRIC way (junk moments deflate checks' decided-N while pairwise, which
never reads the CSM reply, sails through — the arm decision could have gone to
pairwise for a population reason).

**C2 verdict (58 moments, 5 pbq scenarios, k=3, 3.6-flash @ medium, ~410 requests):**

| arm | win / loss / tie | win share (decided) | p | G-C2a |
| --- | --- | --- | --- | --- |
| checks (v2, partial tier) | 7 / 6 / 45 | 53.9% (13) | 0.50 | **FAIL** |
| **pairwise** | 27 / 8 / 23 | **77.1% (35)** | **0.00094** | **PASS** |

G-C2b (checks quote gate): 63/63 claims verified, 100% — the fabrication defence is
airtight even while the arm itself fails. G-C2c: ZERO moments flipped across k=3 in
EITHER arm (run-to-run noise at this temperature/model is negligible; k can drop to
1 in production without a measured penalty).

Readings: (1) the checks arm failed exactly as C3 predicted — 45 of 58 moments tied
(mostly 0–0: nothing credited against either playbook), so the absolute per-moment
verdict has no discrimination power at a 3–6% base rate, even with the partial tier.
(2) Pairwise at 77.1% lands inside the old scorer's 77–82% discrimination band —
the third independent confirmation that relative judgments are the signal-bearing
form in this pipeline. (3) The pre-registered decision rule ships
`grader_arm: pairwise` (set in tuning.yaml, same commit as this entry).

**Open after C2:** C4 reader panel on ~15 PRODUCTION-SHAPED pairwise judgments
(CSM reply vs matched Naren exemplar — note C2's construction was exemplar-vs-
exemplar with known truth; C4 must read the shape production actually runs).
Production cost note: pairwise ≈ 2 requests/moment (both orders), so the 1,230-
moment corpus ≈ 2.5k requests at k=1 — sample or stage accordingly.

### C4 PASSED: the human seal on production-shaped judgments (2026-08-24)

Harness `calibration/layer_d_c4_read.py` (~30 chat calls): 15 moments sampled from
the C2 population (3/scenario), each judged in the PRODUCTION shape — the CSM's
actual reply vs Naren's top-cosine exemplar, per move, order-swapped, k=1. Its
blind code audit (the FOURTH consecutive audit to catch an outcome-changing
defect) fixed a validity/blinding gap before spend: the draft packet showed the
reader only the CSM's client moment, while the model saw each reply with ITS OWN
trigger — both a different task and a soft unblinding (the "native" reply is
identifiable). The packet now mirrors the model's task exactly, with per-item
artifact flush + resume, and a routing-drift assert that fires before spend.

**Read:** one blinded Sonnet reader, packet file only (never the KEY or the
model's verdicts), 54 move-level verdicts over the 15 items. **Gate (frozen at
≥70% agreement on mutually decisive verdicts): 11/11 = 100%. PASS.**

Distributions, for honesty about the n: the model called 40/54 verdicts
equal(partial), 11 miss, 1 hit, 2 unscored; the reader called 34 equal, 20
decisive. The 11 mutually-decisive overlaps all agreed — including direction:
this sample says Madhumita's replies mostly tie the benchmark's exemplar move-by-
move, occasionally lose, rarely win, and the human sees the same thing the model
sees. n=11 is small; the gate bar was set before the read and is met with zero
disagreements.

**THE LADDER IS COMPLETE: C0 ✓ C1 ✓(by construction) C2 ✓ (pairwise 77.1%)
C3 ✓ (ran first, redirected the design) C4 ✓ (100%). The production run over all
32 scenarios is licensed on the pairwise instrument.** The first attempt (stopped
by the operator to run C4 first — correctly, in hindsight) wrote zero rows;
checkpoints make the relaunch clean.

### THE FIRST PRODUCTION RUN (2026-08-24→25, run_id 137706da74c6)

Instrument: `layer_d_e_pairwise_gemini-3.6-flash_medium_noswap_v2`. The order swap
was dropped before launch on a measurement (both orders agree 95.2%/96.3% of
verdicts; operator's call at their own >90% threshold), with the CSM's side
RANDOMIZED per moment so residual position bias cancels — `pairwise_swap: false`,
in the checkpoint identity, caveat recorded in tuning.yaml.

**Numbers:** 100 transcripts processed, 6 excluded (all Avoma "Unknown Speaker"),
ZERO failures. 1,206 moments detected; **807 graded** (~807 requests — the halved
bill, on estimate); 395 deferrals + 3 silences stored ungraded (a 33% deferral
rate is itself a coaching-relevant, no-LLM finding); 1,205 move_events; 251
move_performance rows; 2,897 move-verdicts (274 win / 2,134 equal / 489 loss —
she loses ~1.8x as often as she wins when the judge is decisive).

**Coverage shape:** 110 (scenario, move) cells for Madhumita; 77 reach the ≥8
ranking floor; **26 of those 77 are BLURRY (≥80% tie)** and are excluded from
coaching + listed as the targeted playbook-rewrite shortlist — notably the three
biggest-volume cells (application_volume M1/M2/M3 at 151 attempts, 85–95% tie)
and ats_integration M3 (100% tie over 60). That leaves ~51 rankable cells.

**The report itself reads as intended** — e.g. priority #1: attribution_and_
funnel_tracking M2 (diagnose tracking discrepancies): won 1 / equal 3 / lost 7 of
11, match-or-beat 23%, with the criterion and Naren's verbatim benchmark example
attached. Remaining before this is handed to anyone: the operator reads the top
priorities against raw transcripts (spec verification step 5, still owed).

### THE OUTPUT AUDIT: 40 production moments, blinded, 97.9% agreement (2026-08-25)

`calibration/layer_d_output_audit.py` (zero chat spend — verdicts stored, exemplars
reconstruct deterministically from cache): a stratified 40-moment sample of the
production run (75% with ≥1 decisive verdict, round-robin across scenarios, plus
all-equal moments so the ties get checked too), rebuilt into two blinded 20-item
packets (C4 pattern: per-item randomized sides, KEY and model verdicts kept out).
Two independent Sonnet readers, one at a time, 144 verdicts answered.

**Result: 46/47 mutually-decisive verdicts agree = 97.9% (gate ≥70%, PASS).**
Direction detail: both said equal on 76; the reader was decisive where the model
said equal on 19 (the model is the MORE conservative of the two — its ties are not
hiding wins/losses so much as reflecting caution); the model was decisive where
the reader ticked equal on only 6; exactly ONE true disagreement.

**This also retroactively answers the swap question:** the audited verdicts came
from the noswap/randomized-side production instrument, and an independent blinded
reader reproduces them at 97.9% — dropping the order swap (half cost) produced no
measurable degradation. The read-through packet for the operator's human read
(spec step 5) is `artifacts/layer_d_readthrough.md`: 33 moments behind the top 3
priorities, unblinded, with the CSM reply and the reconstructed benchmark exemplar
side by side.

### SPEC STEP 5 — THE READ: passes with notes (2026-08-25)

All 33 read-through moments were read against the transcript texts (reader: the
building session — critical-adversarial, not independent; the independent check is
the 97.9% blind audit above). Verdict on the headline finding: **TRUE.** The
pattern is visible on the page: in attribution/funnel-tracking moments Naren
interrogates and structures (pixel tests, day-wise breakdowns, a conversion-event
definitions matrix) where Madhumita acknowledges and moves on ("Sounds good.
Sounds good. Okay."; "Yeah. Yeah. Yeah. I I hear.") or asks one clarifying
question and stops. The judge also credits her when deserved (moment 9's
two-workstream diagnostic reply WON). Direction and ranking: right.

**Two production defects the read exposed (instrument tells the truth about the
page; the page sometimes shows the wrong thing):**

1. **Fragment replies get graded.** Moment 6's captured "reply" is "So the last."
   — an interruption artifact scored as a loss; moment 5's "Yeah I hear" is
   likely mid-monologue backchannel. ~2 of 11 losses in the top cell are
   segmentation artifacts: priority #1's honest record is ~5 of 11 lost, not 7.
   Fix: an INTERJECTION GUARD — a response window below a structural
   substantiveness bar is classified like a deferral (recorded, not graded).
   Structural rule, not a cosine threshold.
2. **Exemplar selection sometimes misfires.** Top-cosine can return the same
   exemplar for different moments (fine) but also a topically-adjacent,
   non-responsive one (moment 8: her sharp source-attribution question ruled a
   loss against an exemplar answering a different question — the ONE verdict the
   read disputes outright) or Naren FILLER as the benchmark (moment 1: she "won"
   M5 against "Yep. Absolutely. Perfect."). Fix: filter exemplar candidates
   through the existing `_is_substantive` before top-cosine.
3. **Report shape:** the top-3 priorities are three moves of ONE scenario judged
   over the SAME 11 moments — one coaching conversation presented as three rows.
   Fix: group the report by scenario, moves within.

None of the three changes the direction of any finding; #1 shaves magnitudes.
All three are small, named, and pre-production for any run whose numbers get
shown to a CSM.

## THE THREE P0 FIXES SHIPPED, THE REGRADE COMPLETED, AND THE OUTPUT AUDIT RE-PASSED (2026-08-26/27)

**Interjection guard** (`layer_d/signals.py::detect_moments`): a `"csm"` response window
whose joined text fails `v1.layer_b._is_substantive` (the same ≥5-content-word bar used
project-wide for "is this a real utterance or noise", lazy-imported to avoid paying spaCy's
load cost on every process that touches `layer_d.signals`) is reclassified to a new
`response_outcome` value, `"interjection"` — recorded like a deferral (ungraded), but kept in
its own bucket rather than folded into `"other_joveo"`, so the already-reported 33% deferral
rate doesn't silently move. Required a schema change: `move_events.response_outcome`'s CHECK
constraint gained `'interjection'` as a fourth allowed value (idempotent `DROP
CONSTRAINT`/`ADD CONSTRAINT` in `db/schema.sql`, since Postgres can't alter a CHECK condition
in place). Checkpoint identity bumped `_v2` → `_v3` (the guard changes which moments get
graded at all, so cached `_v2` verdicts can't be reused).

**Exemplar-substantive filter** (`layer_d/pipeline.py::make_exemplar_picker`): candidates are
now filtered through `_is_substantive` before the top-cosine pick, so a CSM reply can no
longer be benchmarked against Naren filler. Falls back to the unfiltered pool (with a printed
warning) if filtering would empty it for a scenario — failing that scenario's whole grading
batch would be worse than grading against an imperfect benchmark for once, per the C3
"landing_page is ~0 under every unit" precedent that a thin scenario is itself a finding, not
grounds to crash.

**Report grouping** (`layer_d/aggregate.py::group_by_scenario` + rewritten
`format_pairwise_priorities`): the report now shows ONE block per scenario (moves nested
inside), ordered by each scenario's WORST move's gap (max, not average — a scenario with one
severe, specific problem must not be diluted by fine moves in the same scenario). The old
`_REPORT_TOP_N = 5` cutoff was dropped for the pairwise arm entirely: verified against the
first production run's own data that the real scale is ~19 scenarios / ~51 rankable cells for
one CSM, not hundreds, so a full report reads fine and a cutoff was only ever hiding real
findings for no reason.

All three fixes passed audit #5 (general-purpose agent, blind, zero findings) before the
regrade spent anything.

### The regrade took eight attempts, and the failures taught more than the fixes did

Two DISTINCT operational bugs, neither in the three P0 fixes' own code, surfaced only once
real spend was on the line — both fixed, both now part of the standing toolkit:

**Bug 1 — a dropped connection cascaded into every remaining transcript's write failing.**
`run_layer_d_batch` (and the sibling `run_naren_benchmark`) held one long-lived `psycopg`
connection for the whole batch with no health check. A WiFi drop mid-run killed it once; every
subsequent transcript then failed identically on write, its grading spend wasted for nothing,
because nothing ever re-established the connection. Audit #6 found the SAME gap in
`run_naren_benchmark` (skipped for `pairwise`, the shipped arm, but reachable via
`--naren-only` regardless of arm). Fixed with `storage.reconnect_if_closed` — already the
established pattern everywhere else in this project (`ego_trap/pipeline.py`, `v2/layer_c.py`,
several `ops/*.py` scripts) — wired into both functions' per-item loops for the first time.
Both functions now return `(result, conn)` so the caller rebinds to the live connection
(reconnecting swaps in a new object; the caller's original handle can be dead by the time the
function returns) — same contract as `ego_trap.pipeline.run_ego_trap_batch`.

**Bug 2 — the real one: a leaked session GUC through Neon's connection pooler.** Even after
Bug 1's fix, the regrade kept hitting `cannot execute INSERT in a read-only transaction`,
recurring across attempts with no `ALTER DATABASE`/`ALTER ROLE` setting it and no replica
involved. Systematic root-cause investigation (not a guess): four scripts
(`ops/serve_ask_naren.py`, `calibration/probe_retrieval_gate.py`,
`calibration/score_naren_ceiling.py`, `calibration/layer_d_output_audit.py`) each open a
"safety" read-only connection via `SET SESSION default_transaction_read_only = on` and close
it WITHOUT resetting first. Neon's pooled endpoint reuses the same backend across unrelated
clients (PgBouncer transaction pooling), so the leftover session setting poisons whichever
client gets that backend next. Directly reproduced (poison → fresh connection inherits
read-only) and directly disproved as a real restriction (`SET SESSION ... = off` cleared it
instantly, every single time it was tried, including live mid-incident — a genuine
Neon-enforced restriction could not be overridden that way). Full writeup:
`docs/GOTCHAS.md` §"`SET SESSION default_transaction_read_only = on` leaks across clients
through Neon's pooler".

Two layers of fix, because the source kept recurring from outside this codebase's visibility
even after the four known scripts were patched (confirmed via `pg_stat_activity`: no
`serve_ask_naren` process was running, so an unidentified fifth source — plausibly a separate
concurrent application sharing the database — was still doing the same thing):

1. All four scripts fixed at the source: `.close()` wrapped to reset the session setting first.
2. Layer D made self-healing regardless of source: `shared/storage.py::clear_read_only(conn)`
   actively resets a possibly-leaked setting and only reports "still read-only" (triggering the
   existing abort path) if the reset genuinely doesn't take. Wired into `run_layer_d_batch`'s
   per-transcript check, its final-aggregate check (audit #7 found this second site was
   unguarded — a read-only flip at the very last step, after every transcript had already
   succeeded, would have crashed with a raw traceback and lost the printed report for a run
   that had, in substance, completed), and `run_naren_benchmark`'s per-scenario check. Audit #8
   confirmed clean, including tracing that a dead connection can never reach
   `clear_read_only` (reconnect_if_closed always runs first) and that the reset cannot produce
   a false "cleared" against a genuine restriction (Postgres session GUCs aren't gated by
   recovery state; the one theoretical blind spot — a real hot-standby connection — already
   existed identically under the old code and isn't a regression).

**Result: attempt 7 (self-healing fix) pushed through THREE separate re-poisoning events in
one run** rather than aborting on the first one, losing only the one transcript that happened
to be mid-flight each time instead of every remaining transcript. Attempt 8 (a 3-transcript
mop-up) completed clean. Eight audits total across this arc's full lifetime (this session added
audits 5 through 8), all clean or promptly fixed.

### Final regrade: 100 of 106 mapped transcripts, zero failures, output audit re-passed

Same instrument identity except version (`layer_d_e_pairwise_gemini-3.6-flash_medium_noswap_v3`
— the `_v3` suffix IS the interjection-guard/exemplar-filter boundary). 6 transcripts excluded
(Avoma "Unknown Speaker", same fail-closed gate as the first run). 807→ a fresh grade of every
moment under the new instrument; `move_performance` fully rebuilt (251 rows).

**The numbers barely moved — which is the right result, not a null one.** Same top cell,
before vs after: 11 attempts/1-3-7/23% match-or-beat → 9 attempts/1-2-6/22%. Other cells:
publisher_management M1 15→11 attempts, 33%→32%; specialty_and_niche M3 19→16 attempts, 34%→34%
unchanged. Attempt counts dropped by exactly what the interjection guard removing fragment
moments predicts; the rates themselves held within 1-2 points everywhere checked. This confirms
the original numbers were mostly real signal with only the small artifact-driven distortion the
read-through had already estimated (~2 of 11 top-cell losses) — not an instrument that was
quietly reporting noise the whole time.

**`calibration/layer_d_output_audit.py --audit` / `--score` re-run on the fresh data: 92.7%
agreement (38/41 mutually decisive) between two independent blind readers and the model's own
verdicts, gate ≥70% PASSED** — consistent with the original run's 97.9%. `connect_ro()` in this
script carried the SAME leaked-session-GUC bug as the other three (a fourth instance, found and
fixed the same way, before this re-run).

**Verdict, updated:** still SHIPPABLE AS COACH-FACING DRAFT. The P0 gap to CSM-facing is
closed (all three named fixes shipped, regraded, and re-validated). What's NOT closed by this
work, and shouldn't be read as closed: this is still one CSM (Madhumita), still ~a third of
playbook moves are blurry/unmeasured, and rates are still relative/shrunk rather than precise
— none of that was in scope for P0, all of it is P1/P2 (report the deferral finding, targeted
playbook rewrites on the blurry cells, more CSMs, frontend wiring).
