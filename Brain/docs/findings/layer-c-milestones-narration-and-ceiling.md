# Layer C — Milestones Were Narration, Not Criteria; the Naren-Ceiling Saga (2026-08-10/15)

[Findings index](INDEX.md)

### Layer C milestones were narration, not criteria — found and fixed (2026-08-10)

**The single most important Layer D finding to date, and it was never a Layer D bug.** All
405 stored milestone descriptions were *descriptions of what one expert did* rather than
*criteria a different person could satisfy*: 37% named Naren, 63% said "the speaker", 91%
used he/she/his/her — **100% used narrative-about-a-person phrasing.** Example:
`"He uses hypothetical numerical examples of job slots to illustrate how the platform can
scale."` Layer D scores a CSM's response against those descriptions and `detection_hint`s,
so a CSM could handle a call correctly and still miss every milestone by not reproducing
one person's improvisation.

Root cause was two prompts, both now fixed:

- `PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH` opened `"Describe each recurring communicative
  move in Naren Shankar's sales responses"` and asked for prose `"grounded in the clauses
  above"` — an instruction to summarise a transcript. Now asks for the criterion a
  DIFFERENT person's response must satisfy, forbids names/pronouns/"the speaker", and
  requires generalising past specific numbers, clients and anecdotes.

- `PROMPT_LAYER_C_V1` was worse: the flaw was in its **few-shot example**
  (`"description": "Naren explicitly validates the client worry..."`), priming the model to
  copy that shape. Example and rules block both fixed.

**Repaired the 405 existing descriptions in place rather than re-running Layer C.** New
`ops/rewrite_milestone_criteria.py` (`--dry-run` / `--apply`). Re-running Layer C would
change the milestone SET, not just its wording — UMAP+HDBSCAN is not reproducible across
process launches (385/398/403-407 for identical input), which reshuffles clusters, orphans
every `milestone_performance` row (`milestone_id` is the array POSITION) and moves the
baseline, all to fix prose. The clusters are well evidenced (support up to 112 calls / 337
clauses); only the text was wrong. Result: **405/405 rewritten, 41/41 batches clean,
person language 100% → 3%** (and all 13 residuals are regex false positives — generic
*their/they*), **0 rubrics changed milestone count**, all 391 `support_calls` preserved
byte-for-byte. Each rewritten milestone carries `criteria_rewritten: true`.

- Batch size is **10, not 20**: at 20, one batch in 21 returned truncated JSON and those 20
  milestones were left unrewritten. 41 calls is nothing against 500/day; truncation is the
  binding constraint here, not requests.

**Controlled A/B (rare in this codebase — identical transcripts, taxonomy, clusters, ids and
evidence fields; only wording differed), snapshot `pre_criteria_20260810`:**

| | before | after |
| --- | --- | --- |
| attempts | 864 | 963 |
| full hits | 21 (2.4%) | 29 (3.0%) |
| partial hits | 32 (3.7%) | **73 (7.6%)** |
| weighted | 0.043 | **0.068 (x1.6)** |

43 milestones improved, 17 worsened, 189 unchanged. **Verdict: wording was a real cause but
NOT the whole cause** — 3.0% full hits is still very low, so do not treat this as closed.
Partials doubled while full hits barely moved: a narration milestone is effectively binary
(you reproduced the improvisation or you didn't) so it collapses to `miss`, whereas a
behavioural criterion admits partial credit — the rewrite made the rubric **gradable**, which
matters more for coaching than the headline rate. The +11.5% attempt drift is benign — the
baseline arm lost ~99 attempts to 2 Gemma batch failures; the after arm had zero.

**MEASURED AGAINST THE NOISE FLOOR (2026-08-11) — read this before citing any number above.**
Two runs of arm 3 with *nothing whatsoever changed* (identical transcripts, code, config,
rubrics; both arms verified as exactly one run each) gave `889 att / 28 hits (3.1%) / weighted
0.074` and `889 att / 33 hits (3.7%) / weighted 0.080`. So:

- **The noise band is ±0.006 weighted, and 15.6% of milestones (37/237) move on their own.**
- **The criteria rewrite's +0.025 is ~4.1x that band — it is real.** That claim survives.
- **The uncoachable-skip's +0.006 is EXACTLY 1.0x the band — it is not measurable.** It was
  previously written up here as 3.0% -> 3.1%; that is retracted. Keep the change anyway, but on
  the grounds that never depended on the metric: it stopped 74 pieces of coaching advice
  instructing a CSM to do something impossible.
- **No per-milestone winner or loser from any A/B is citable** — 24.6% observed movement against
  a 15.6% floor.
- **A single hit-rate figure needs the band attached.** Pure variance moved the headline 3.1% ->
  3.7%, a 19% relative swing, so every "3.x%" in this file means 3.x% ± 0.6pp.
- **An earlier argument here was wrong and is withdrawn.** It claimed noise would be *symmetric*,
  so the rewrite's lopsided 43-up/17-down must be signal. The floor is itself lopsided (24 up /
  13 down, net +2.12) because at a ~3% hit rate almost every milestone sits at 0 and a random
  flip can only move UP — variance is structurally upward-biased against a floor. Compare
  magnitude (rewrite net +4.48 vs floor net +2.12, ~2x), never shape.
- **Consequence for future work: at this sample size any change below ~+0.02 weighted is
  unmeasurable.** Two of this session's three changes landed inside the noise. Do not tune
  against this metric until the ceiling is established (see the open question below).

Baselines: `arm3_run1_20260810` and `arm3_run2_noisefloor_20260811`.
`calibration/measure_scoring_noise.py` runs the comparison and **refuses** to report a floor
unless each arm is provably a single run — a guard added after an earlier attempt silently
reported a floor computed from two concurrent runs blended together (see the concurrency
gotcha below).

**Still suppressing the rate (all confirmed by reading real samples, none of them wording):**

- **Step 0 false positives.** A URL-configuration exchange (`"did you already make changes to
  the URL?"` / `"For the older job or the new job?"`) was matched to
  `contract_renewal_anxiety` and scored against a milestone about reframing "middle person"
  perception. The verdict was technically correct and the question was meaningless.

- **36% of `gap_events` are `Signal_Recognition_Failure`** — no CSM response existed to score
  at all. And `extract_csm_response_window` sometimes captures scheduling chatter instead of
  the substantive answer (seen in `rec6` @ turn 135).

- **17 of 405 milestones are unhittable by construction** — found by
  `ops/flag_uncoachable_milestones.py` sweeping all 405 (the rewriter had volunteered 4 of them
  incidentally). 5 require seniority or personal relationships a CSM does not have
  (`"leverage professional relationships"`, support 15 calls; `"establish authority"`, 18), 4
  have no observable criterion (`"share a vulnerable personal story"`), and 8 are call mechanics
  that leaked past `milestone_sink_similarity_percentile` triage (`"offer screen-sharing"`,
  `"manage speaking turns"`). All are well-evidenced clusters — the clustering found something
  real that simply is not coachable. **The proof they are impossible rather than merely hard:
  74 attempts, 0 hits, across 12 distinct milestones.** Flagged and skipped via
  `layer_d.skip_uncoachable_milestones`; that change is NOT justified by its metric effect
  (which is inside the noise band) but by removing 74 fabricated coaching instructions.

**The level, not the improvements, is the finding.** After all three fixes the rate is
3.1-3.7%. A working CSM is being told she fails ~96% of the standard. Two readings, and the
data cannot separate them: either she genuinely performs that badly against Naren's bar
(implausible for someone doing the job), or **the measurement is still fundamentally broken and
the narration bug was one layer of something deeper.** Weight the second: a defect as severe as
"100% of rubrics were narration" bought only +0.025 on a 0-1 scale, so the binding constraint
is elsewhere.

**THAT EXPERIMENT HAS BEEN RUN (2026-08-11/12) AND IT INVALIDATES EVERY NUMBER ABOVE. READ THIS
BEFORE CITING ANY HIT RATE ON THIS PAGE.** Naren was scored against his own rubrics with both
circularities closed (call-level benchmark holdout, plus a secondary-label-AND-zero-primary-call
holdout), against a control arm scoring the same responses on a deliberately UNRELATED scenario's
rubric.

| arm | W | |
| --- | --- | --- |
| A1 primary label (leaked) | 0.161 | |
| **A3 call-level holdout (clean)** | **0.114** | the ceiling |
| **B unrelated rubric (control)** | **0.090** | same-model subset |
| CSM reference | 0.074 | **below the control** |

**Signal-to-null is 1.2 : 1, reproduced three independent times** (0.114/0.090, 0.116/0.095).

> **RETRACTED 2026-08-15 — the 1.2:1 is an ARM-CONSTRUCTION ARTIFACT, not a property of the
> grader.** Measured by `calibration/trial_grader_inputs.py` on the same live rubrics: with
> matched and unrelated scored on **identical responses** (and those responses drawn from the
> leakage-clean secondary-label stratum), the grader discriminates **77.4% and 82.3% of
> scenarios** across two independent response draws (48-14-7 and 51-11-7 of 69 scenarios,
> p=1.7e-5 and 2.8e-7, 3,540 gradings each, `gemini-3.1-flash-lite` pinned). Pooled ratio
> 2.92 / 2.11 against this page's 1.27. **The cause is the ceiling's own documented
> asymmetry**: arm B scored `a1_sample` rows — PRIMARY-label responses, the strongest
> exemplars of their scenario — against a partner rubric, while A3 drew secondary-label rows.
> A strong substantive response satisfies generic criteria from anywhere, so the null was
> inflated by how it was sampled. `W(B)=0.090` vs this trial's `W(unrelated)=0.032-0.042` on
> the same kind of comparison. The AMENDED note below already suspected this and named the
> missing arm "B3"; that arm now exists. **Do not cite 1.2:1 as evidence the scorer cannot
> discriminate.**
>
> **What does NOT change: the LEVEL.** Leakage-clean `W(matched)` is **0.089-0.095** — Naren
> satisfies ~9% of criteria written from his own calls. The binding constraint is that the
> criteria are unpassable, not that the grader is blind to which rubric it holds. That is a
> different problem and it is untouched.
>
> **Also refuted, and cheap to not repeat: DEFECT 2 (the grader never sees the client turn,
> scenario or milestone `label`) is REAL as a code fact but is NOT the binding constraint.**
> `situated_fields` supplies all three; discrimination went 6.00 (blind) -> 6.64 (turn) /
> 4.48 (label) / 5.84 (all three) with heavily overlapping CIs — no ordering, no effect.
> Spec: `docs/superpowers/specs/2026-08-15-grader-inputs-design.md`.
Both pre-registered failure conditions fired.

**AMENDED 2026-08-13 — that ratio compares two arms that do NOT share a response population, and
the validity verdict flips on the pair you pick.** Read from `_build_items` and confirmed against
`artifacts/naren_ceiling.json`: **A1 and B are built from the same sampled rows** (`for row in
a1_sample:` appends to both), so they are population-symmetric, while **A3 draws from a different
pool entirely** — secondary-label rows. Measured overlap: `A1 ∩ A3` is **45 pair_ids** out of
371 / 346, with B at 383. The gate is applied as `W(B) >= 0.5 * W(A3)`, i.e. across that boundary:

| comparison | ratio | B as a share of matched | `_T_INSTRUMENT` |
| --- | --- | --- | --- |
| A3 / B — the cited figure, **crosses populations** | 1.61 : 1 | 62% | **fails** |
| A1 / B — **same responses both sides** | 2.26 : 1 | 44% | **passes** |

**No arm pair is both leakage-clean AND population-symmetric.** A1 is leaked, so 2.26 is inflated
by exactly what A3 removes; the clean symmetric figure is *unmeasured* because the arm that would
give it — `a3_sample` scored against the partner rubric, call it **B3** — was never built (~94
calls). Arm B is also model-split (793 `gemini-3.1` + 1040 `gemini-3.5`), so the exact ratios move
with the subset: full-arm B is W=0.0709 against the 0.090 same-model subset quoted above.
**The overall verdict still stands**, on the four-arm trial's independent failure (1.04 / 0.89 /
1.09 against a fair same-model, same-clustering baseline, whose arms DO share a population) — but
cite that trial, not this ratio, and treat "1.2 : 1" as softer than it reads.

Leakage was NOT the cause — clean vs leaked is 0.114 vs 0.161. The cause is
that the criteria are scenario-agnostic: the 2026-08-10 rewrite conflated "never narrate a person"
(correct) with "never state the specific instance" (an over-correction), so criteria stopped
identifying a situation.

**Do not treat the per-scenario decomposition as established.** `PROBLEMS_AND_FIXES.md` records a
bimodal split (16 of 40 discriminating, 7 inverted, 7 with a zero control). That labelling failed
replication on 2026-08-12: three independent measurements of the same 49 scenarios agreed on the
verdict only **41–47%** of the time, with SHIP<->DISABLE sign flips on the most extreme cases, and
the per-scenario gap moves a median of **0.138** against a ±0.05 band. Only the CORPUS-level result
above survives. Nothing may be shipped, disabled or gated per scenario on those numbers.

**Also measured and closed 2026-08-12:** the per-milestone objective function
(`shared/rubric_validation.py`, `calibration/validate_rubrics.py`,
`layer_d.require_validated_milestones`) was built and run. At 8 attempts per arm W quantizes to
steps of 0.0625, so its discrimination gate trips on one stray partial hit — the 7 known-good
scenarios produced 0 of 33 scoreable milestones. Its applicability judge failed its own null
(0.147 matched vs 0.120 unrelated, 1.22 : 1) despite demonstrably varying with the client turn.
Both gates fired, nothing was written to the DB, and the flag stays `false`.

**Next step is the four-arm Layer C rebuild trial**, which writes nothing to Postgres:
`docs/superpowers/specs/2026-08-12-layer-c-profile-rebuild-design.md`. Original ceiling design:
`docs/superpowers/specs/2026-08-11-naren-ceiling-measurement-design.md`.

`calibration/compare_criteria_ab.py` runs this comparison against any snapshot schema, joins
on `(rubric_id, milestone_id, csm_id)`, lists per-milestone winners/losers, and **checks
attempt-count drift** — refusing to call it a clean wording-only comparison above 15%.


