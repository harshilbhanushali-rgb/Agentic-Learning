# The Layer D grader cannot see the situation it is grading (2026-08-15)

Status: **COMPLETE. Hypothesis REFUTED; the control overturned the premise instead.**
Everything above the "Result" heading was written before any result was seen.
Read the Result and Confirmation sections at the bottom first.

Harness `calibration/trial_grader_inputs.py`. Zero Postgres writes. ~80 chat calls.

## The defect, read from source rather than inferred

`ego_trap/milestone_scoring.py::score_milestones_batch` builds each exchange out of exactly
three things:

- Naren's benchmark response (unless `show_benchmark=False`)
- the CSM response
- per milestone, `description` + `detection_hint`

`PROMPT_STEP3_MILESTONE_SCORE_BATCH` adds nothing else. **The client turn, the scenario, and
the milestone's own `label` are all stored and all discarded at grading time.**

`label` is the sharpest of the three. The 2026-08-10 criteria rewrite deliberately stripped
subject matter out of `description` — *"List relevant software platforms to establish the
scope…"* — while `label` kept it — *"Identifying ATS Options"*. The situational anchoring
that the ceiling run later identified as missing is sitting in a field that has never been
sent to the grader.

This is the same **missing-INPUT** defect the Layer C profile rebuild found in the WRITER
(`_describe_milestones_batch` has never seen a client turn, so it cannot state a
precondition), one stage later and never diagnosed. It is recorded in CLAUDE.md as DEFECT 2
of the 100-call Layer D run, with the note "cheap to test against the ceiling run's own
null" — and never tested.

## Why it could invalidate four verdicts rather than one prompt

The ceiling run's control arm scores real responses against a **deliberately unrelated**
scenario's rubric. A grader that cannot see which situation either belongs to has no way to
notice the mismatch. Combine that with criteria the rewrite made scenario-agnostic, and a
competent sales response satisfies generic criteria — *"explain the mechanism"*, *"ask an
open question to establish scope"* — drawn from any scenario at all.

**1.2:1 is what that arrangement predicts arithmetically, independent of what the rubrics
are worth.**

And the circularity is concrete, not hypothetical: `calibration/trial_layer_c_arms.py:261`
scores its arms — including the **situated-writer** arms the whole rebuild was built to test
— with this same blind scorer. *Situating the writer was evaluated by an instrument that
discards situation.* That trial is one of the four failures that closed Wall 1.

## What this is NOT

- **Not a fourth wording pass.** Stopping condition #1 ruled those out. The verdict rules,
  the three-way scale and the JSON contract are byte-identical; only the fields present in
  each exchange change.
- **Not the applicability question.** *"Did this moment call for this move"* has failed
  twice — the standalone judge at 1.22:1 and the coverage judge at 64.9% matched vs 65.7%
  unrelated. The question here is unchanged from production's: *did the response satisfy the
  criterion*. Only the visibility of the situation changes.

**The one confound, stated rather than hidden:** information cannot be supplied without a
sentence telling the model the field exists, so the treatment is strictly *"situational
inputs PLUS the minimal instruction to use them"*. There is no way to separate those and
still deliver the information.

## Design

`situated_fields` on `score_milestones_batch`, defaulting to `None` — production is
byte-identical, verified by asserting the blind prompt contains no `LABEL:`, `CLIENT TURN`,
`SCENARIO:` or situation note. An unknown field name raises rather than silently no-opping.

| condition | fields added |
| --- | --- |
| `blind` | none — production control |
| `label` | milestone `label` |
| `turn` | the client turn |
| `full` | scenario + client turn + label |

### Population symmetry, which the ceiling run did not have

CLAUDE.md's own amendment records that the ceiling's cited 1.61:1 compares **A3 against B
across different response populations** (A3 draws secondary-label rows, B draws A1's), that
the gate is applied across that boundary, and that **no arm pair there is both leakage-clean
and population-symmetric** — the arm that would give it, "B3", was never built.

This trial sidesteps that entirely. Every condition scores **the same responses** against
both their own rubric and a deranged partner's. Therefore:

- matched and unrelated share one population exactly — no missing arm;
- leakage inflates both conditions equally, because the treatment is the PROMPT and the data
  is held fixed, so no holdout machinery is required;
- the four conditions score identical items, so a difference between them cannot come from
  sampling.

**Consequence accepted up front: absolute W is NOT comparable to the ceiling run's W. Only
ratios are.** The benchmark travels with the *rubric*, never the response's own scenario, or
the unrelated arm would differ from matched in two ways instead of one.

The partner mapping is a derangement rejecting any pair whose scenario-vector cosine is
`>= layer_a.merge_cosine_threshold` — an already-calibrated knob, in bge, the space it was
calibrated in. No new `tuning.yaml` key.

## Pre-registration

| | |
| --- | --- |
| metric | `W = (full_hit + 0.5*partial_hit)/attempts` — the definition `gap_output.milestone_miss_rate` and `measure_scoring_noise.py` already use |
| primary | discrimination `D = W(matched) / W(unrelated)`, per condition |
| **PASS** | any situated condition reaches **D >= 2.0** |
| **FAIL** | no condition reaches 2.0 |
| uncertainty | 95% CI for D by bootstrap over **items**, not milestones — milestones inside an item share a response and are not independent. Overlapping CIs between `blind` and a situated arm mean the move is not established, whatever the point estimates do |
| sampling | seeded, **stratified** over posture (`client_*`) vs subject-matter. Never the first N — `--limit` once returned nothing but subject-matter scenarios because every posture key sorts after `budget` |
| provenance | `judged_by` per verdict, model histogram per arm. Model pinned with `fallback_models=()` — an empty tuple, **not** `fallback_enabled=False`, which would also disable key rotation |

**D >= 2.0 is not a new bar.** It is the inverse of `score_naren_ceiling._T_INSTRUMENT = 0.5`
("W(B) >= 0.5 × W(A3) ⇒ the instrument is invalid, discard everything"), already
pre-registered in the ceiling design and unmoved here.

### What each outcome means

- **PASS** — the grader's blindness was a binding constraint. Every verdict measured through
  the blind scorer needs re-reading: the ceiling's 1.2:1, the criteria A/B, and the four-arm
  rebuild. Wall 1 reopens.
- **FAIL** — situational blindness is not the binding constraint. Wall 1 stands and this line
  of attack closes alongside the other four. **A FAIL is a real result and must be reported
  as one**, not softened into "inconclusive".

### Evidence already on the record that argues AGAINST the hypothesis

Recorded here so a PASS is not read as inevitable and a FAIL is not read as surprising:

- the coverage judge **did** see the client turn and the response and still could not
  separate matched from unrelated (64.9% vs 65.7%);
- the head-to-head judge had full situational context and still failed self-consistency
  under position swap (0.669 against a 0.75 bar).

Both were asking a *different* question — applicability, and fine-grained preference between
two good replies. The scoring question with the situation supplied has never been run. That
is the whole of the case for spending these calls.

## Cost and blast radius

~80 chat calls. Zero Postgres writes; the live 161 scenarios, 84 rubrics and every
`milestone_performance` row are untouched. `situated_fields` defaults to `None`, so no
production path changes until someone deliberately passes it.

---

## Result (2026-08-15): hypothesis REFUTED, and the control overturned the premise

`gemini-3.5-flash-lite` pinned, 20 scenarios x 3 responses, 120 items per condition, 546
gradings each. Same items across all four conditions.

| condition | W matched | W unrelated | D | 95% CI |
| --- | --- | --- | --- | --- |
| `blind` (control) | 0.176 | 0.029 | **6.00** | [3.26, 24.31] |
| `label` | 0.172 | 0.038 | 4.48 | [2.92, 13.48] |
| `turn` | 0.170 | 0.026 | 6.64 | [3.03, 22.26] |
| `full` | 0.203 | 0.035 | 5.84 | [4.17, 22.51] |

**Situating the grader does nothing.** No ordering, CIs heavily overlapping. DEFECT 2 is a
real code fact and is NOT the binding constraint. Do not spend on it again.

### The pre-registration was mis-specified, and it is recorded rather than moved

`D >= 2.0` was inherited from the ceiling's `_T_INSTRUMENT`, which was calibrated on the
ceiling's ASYMMETRIC arms. Under this design the **control clears it unaided**, so the bar
cannot separate treatment from control and a printed PASS says nothing about the hypothesis.
The bar is left exactly as registered and the report prints a `PRE-REGISTRATION DEFECT` line;
rewriting it after seeing the result is how a finding gets tuned into existence. The
comparison that carries the hypothesis is treatment-vs-control, which is null.

### The control is the finding: 1.2:1 was an arm-construction artifact

| run | population | model | W matched | W unrelated | D |
| --- | --- | --- | --- | --- | --- |
| headline | leaked | 3.5-flash-lite | 0.176 | 0.029 | 6.00 |
| model control | leaked | **3.1** (production) | 0.176 | 0.042 | 4.17 |
| clean + symmetric | **leakage-clean** | 3.1 | 0.090 | 0.018 | 4.90 |

The model accounts for part of the spread and nowhere near the gap to 1.27. The difference is
**entirely in the control arm**: this trial's `W(unrelated)` is 0.018-0.042 against the
ceiling's `W(B)=0.090`, while `W(matched)`=0.090 sits right beside the ceiling's
`W(A3)=0.114`. Arm B scored `a1_sample` rows — PRIMARY-label responses, the strongest
exemplars of their scenario — against a partner rubric, and a strong substantive response
satisfies generic criteria from anywhere. **The null was inflated by how it was sampled.**
This is the symmetric-filtering failure this codebase has hit five times, and the ceiling's
own amendment already suspected it and named the missing arm "B3".

## Confirmation (2026-08-15): replicated at scale, on the statistic that cannot be destabilised

The pooled ratio D is fragile — its denominator is near zero, and it moved 4.90 -> 2.92 purely
by going from 20 scenarios to 69. So the headline moved to a **per-scenario paired count**,
pre-registered at `SIGN_BAR = 0.70` with p < 0.05 on BOTH independent response draws before
either was launched. Pairing is on the RESPONSE's own scenario, and the harness **refuses** to
run the test on records lacking `source_scenario` rather than pairing an unrelated item under
its partner's name.

69 scenarios (26 posture / 43 subject-matter), 345 responses, 690 items, 3,540 gradings per
run, leakage-clean stratum, `gemini-3.1-flash-lite` pinned, ~230 calls total.

| run | wins | losses | ties | win share | p | pooled D |
| --- | --- | --- | --- | --- | --- | --- |
| A (seed 42) | 48 | 14 | 7 | **77.4%** | 1.7e-05 | 2.92 [2.05, 3.68] |
| B (seed 7) | 51 | 11 | 7 | **82.3%** | 2.8e-07 | 2.11 [2.12, 3.64] |

**Both clear the pre-registered bar. Only 7 of 69 ties**, so the "everything scores zero on
both sides" degenerate case did not occur and the test is genuinely informative.

**CONCLUSION: the criteria scorer discriminates.** Wall 1's "the ruler cannot tell good from
better" rests on the retracted 1.2:1 and falls with it. Wall 2 (no skills vocabulary) and the
head-to-head failures (C1 0.669, C4 0.835 replicated) are untouched — neither depended on the
ceiling.

**WHAT DOES NOT CHANGE, and is now the binding constraint: `W(matched)` is 0.089-0.095.**
Naren satisfies ~9% of criteria written from his own calls. The grader can tell which rubric
it is holding and still fails almost everything. **The criteria are unpassable.** That is a
different problem, and the instrument to test fixes against now exists.

### Limits of this result, stated

- It establishes that verdicts RESPOND to the right rubric. It does not establish that the
  verdicts are CORRECT — a grader can discriminate and still be wrong about quality. Only
  human labels settle that.
- All of it is the OLD taxonomy and OLD rubrics. The turn-mode 38 have no rubrics, so nothing
  here speaks to them.
- Known harness inconsistency, unfixed: printed `D` is pooled (total hits / total attempts)
  while the bootstrap CI is over per-item means. Run B is 2.11 pooled vs 2.75 mean-of-items,
  which is why its CI appears to exclude its own point estimate. The sign test is unaffected.

### Harness bugs found and fixed during the run, all recoverable only because of checkpoints

- `--tag` applied to the checkpoint but not the final write, so a control overwrote the
  headline artifact. Recovered free from the intact checkpoint.
- `out` (the artifact path) was shadowed by the batch result inside the scoring loop —
  crashed after all 20 calls had been spent. Recovered free from the checkpoint.
- The call estimate multiplied by all four conditions even when `--conditions` selected one,
  advertising 4x the true cost.
- The situation note announced fields that no exchange contained when a v1 rubric had no
  `label`; it is now built from what was actually emitted.
