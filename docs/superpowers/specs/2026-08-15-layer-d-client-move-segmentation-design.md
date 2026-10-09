# Client-move segmentation — Layer D scores the wrong client turn (2026-08-15)

**Status: PRE-REGISTRATION. No code written, no Gemma call spent.** Every threshold, control,
gate and stopping condition below is fixed before the first run. The evidence base in §2 was
measured first and is reported here as it came out, including the part that contradicted the
brief this work started from.

**Depends on:** `2026-08-13-head-to-head-comparison-design.md` for the pre-registration form and
the length-match band; `2026-08-11-naren-ceiling-measurement-design.md` for the ceiling result
this design explicitly does **not** attempt to move.

---

## 1. The question

`ego_trap/transcript_parser.py::turns_until_next_client` stops at the next CLIENT turn. When a
client speaks several turns in a row — a pause, a continued thought, a transcriber splitting one
utterance, or another client interjecting — **every turn but the last gets an empty response
window**, and `classify_response_outcome` returns `"none"` by construction.

It does not measure whether the CSM responded. It measures whether a turn happened to be last in
its block.

Two consequences, and the second is the one that matters:

1. **The failure count is fiction.** Of 5,731 client turns across the 100 scored transcripts,
   2,484 are classified `"none"`; **2,449 (98.6%) are immediately followed by another CLIENT
   turn**, 35 are the last turn of the call, and **zero are genuine silence**. This retires the
   recorded claim that "36% of gap_events are `Signal_Recognition_Failure` — no CSM response
   existed to score at all", which had been cited as a cause of the low hit rate.
2. **The wrong trigger gets graded.** The block's substantive content is discarded and its last
   turn — often filler — is matched to a scenario and scored.

> ```text
> 1. 'I have another question. How often the information in those
>     dashboards is going to be updated.'
> 2. 'Or expected.'
> 3. 'To be updated?'          <== matched to a scenario and graded
> ```

**This design fixes what counts as a client move. It does not attempt to fix the ruler.**

### 1.1 The honest prior, stated before the run

**This cannot lift the ceiling, and a result that appears to would be evidence of a bug, not a
win.** The ceiling was measured on Naren's own pairs, which `layer_b.extract_pairs`
substantive-gates on both sides, and it still returned 1.2 : 1. The ruler failed on *criteria
discrimination*; this design changes *which text is matched*. Those are different organs.

Success here is: the recognition-failure count stops being a segmentation artifact, and 135
filler triggers stop being graded. **Both are verifiable for free.** The weighted score is
predicted **not** to move (§6.1, G7).

---

## 2. Evidence base — measured before this design existed

All of §2 is zero Gemma, zero Postgres, zero network: transcript parsing, spaCy, and local bge on
a warm cache. Harnesses in §9.

### 2.1 The CSM corpus (the 100 scored transcripts)

| | |
| --- | --- |
| client turns | 5,731 |
| client blocks (maximal runs of consecutive CLIENT turns) | **3,282** |
| turns that collapse away | **2,449** — independently reproducing §1's figure |
| blocks with a Joveo reply | 3,247 |
| blocks with no reply (last turn of call) | 35 |
| genuine silence | **0** |
| block size distribution | `{1: 2502, 2: 446, 3: 133, 4: 69, 5: 38, 6+: 94}` |
| distinct speakers per block | `{1: 2871, 2: 347, 3: 41, 4: 18, 5+: 5}` — **87.5% single-speaker** |
| answered blocks that are multi-turn | 768 (23.7%) |
| **answered blocks where a FILLER is today's trigger** while a substantive turn earlier in the block is discarded | **177 (5.5%)** |
| substantive client turns discarded corpus-wide | **1,343** |
| answered blocks whose trigger is substantive | 2,231 (**68.7%**) |

### 2.2 The same defect exists in `v1/layer_b.extract_pairs` — measured, and NOT fixed here

The brief this work started from asserted the KB inputs "never had this defect". **That is wrong
and the correction is recorded here rather than quietly dropped.** `extract_pairs` uses the same
stopping rule (`else: break` on the next CLIENT turn, `v1/layer_b.py`), so only the last turn of a
block can ever produce a pair. Over Naren's 416 transcripts:

| | |
| --- | --- |
| client blocks | 13,036 |
| blocks answered by a substantive Naren turn | 6,738 |
| pairs emitted | 4,700 |
| **pairs lost entirely** (real question + real answer, last turn is filler) | **443 (6.6%)** |
| **pairs emitted but earlier substantive turns dropped** | **1,316 (28.0%)** — 3,891 turns of context |

**The conclusion survives the correction, for a specific reason.** `extract_pairs` gates the
trigger on `_is_substantive`, so the KB holds *lossy* pairs, never *filler-triggered* ones. The
ceiling's inputs were degraded, not corrupted.

### 2.3 The anchor probe — and the rule it handed us

For the 1,316 mis-anchored pairs: does the stored response answer the stored trigger, or an
earlier turn? Measured by `trigger_response_coupling` (inherited) against every substantive turn
in the block, with a **derangement null** (each response scored against a different block's
candidate set of the same size).

| | |
| --- | --- |
| P(stored trigger wins) — real | **0.432** |
| P(stored trigger wins) — deranged null | 0.353 |
| lift, 95% bootstrap CI | **+0.079 [+0.042, +0.116]** — excludes zero, **gate passed** |
| blocks where an earlier turn wins | 748 (56.8%) |
| margin when it does | p50 **0.063**, p75 0.112, p90 0.178; only **3.8%** exceed 0.20 |

**Confounds reported, not argued.** `P(last candidate is the longest) = 0.323`, and agreement
between "wins" and "longest" is 0.672 — length explains much of it. The k=2 length-matched subset
(|log word ratio| ≤ 0.25, n=149) still gives 0.550.

**Reading the 20 largest-margin cases: 9 of 10 are genuinely mis-anchored** (a Zoom-access issue,
job-specific questions, a technology-lift question, an overspend cap — each answered by an earlier
turn). Note that the stored trigger in the top case is `'Hey, David. Hey, Tony. Hey, Noine.'`,
which passes `_is_substantive` **because proper names count as content words**.

**The decisive split, and it is not a k artifact:**

| k | chance | single-speaker | multi-speaker | diff (95% CI) |
| --- | --- | --- | --- | --- |
| 2 | 0.500 | **0.514** | 0.672 | −0.158 **[−0.238, −0.077]** |
| 3 | 0.333 | **0.353** | 0.440 | −0.087 [−0.200, +0.033] |
| 4 | 0.250 | **0.230** | 0.316 | −0.086 [−0.242, +0.079] |

Within a single speaker's turns the response couples with **no particular turn — at chance at
every k**. That is not a null result; it is positive evidence that the run is **one move** and the
response addresses the whole of it. Across speakers the response couples with the **last** speaker
above chance at every k. Significant at k=2 where n is largest; same sign at k=3 and k=4.

**The same measurement that quantifies the damage supplies the rule for fixing it, with no
invented threshold.**

---

## 3. The design — two arms, one variable each

### 3.1 Arm A — the outcome split (the actual fix for the 2,449)

`classify_response_outcome` gains a fourth value:

```text
"csm" | "other_joveo" | "client_continued" | "none"
```

`"client_continued"` means the next turn is another CLIENT turn: **no reply was due**, so no
`Signal_Recognition_Failure` is written and the event is excluded from the recognized/missed
counters.

**This is not a new idea, it is the existing one applied a second time.** `"other_joveo"` exists
precisely because "a teammate answered" was being conflated with "nobody answered", and it already
routes to `Deferred_To_Teammate` and out of the counters (`ego_trap/pipeline.py`,
`gap_output.write_deferred_to_teammate`). `"none"` is conflating two unrelated things in exactly
the same way.

`"client_continued"` writes **no gap record at all**. `Deferred_To_Teammate` is written because a
teammate answering is a real, coachable event; a client continuing to speak is a non-event, and
inventing a gap type for it would put noise in front of a human.

**Arm A cannot change any scored signal, attempt, or score.** That is what makes it Arm B's
control (§5).

### 3.2 Arm B — the client move (the trigger fix)

> **A client move is all turns by ONE speaker within one client block, joined in order. An
> exchange's trigger is the move of the speaker who spoke LAST before the reply.**

The response window still begins after the **block's** last turn, not the move's —
`extract_csm_response_window` must key off the block boundary or it will capture other clients'
turns as the CSM's answer.

Three candidate rules were measured against the real corpus before choosing:

| rule | trigger text changes | of the 177 filler triggers, fixed | substantive-trigger rate |
| --- | --- | --- | --- |
| today — last turn wins | — | 0 | 2,231 (68.7%) |
| **V1** — maximal same-speaker *runs* | 412 | 78 (44%) | — |
| **V2 — group the block by speaker** ← chosen | **572** | **135 (76%)** | **2,375 (73.1%)** |
| **V3** — merge the whole block | 768 | 177 (100%) | 2,408 (74.2%) |

**V1 is rejected** because an interjection by another client splits one person's question in two
(the dashboards example in §1 is exactly this), and it recovers only 44%.

**V3 is rejected** because it buys **+1.1pp over V2 by fusing distinct people**. §2.3 measured
that multi-speaker blocks have a genuinely privileged last speaker, and this repo has hit
centroid-fusion three times already (`merge_cosine_threshold` at 0.80, the primary-topic
mega-blob, `_match_milestones`' merge blindness). A +1.1pp aggregate is not worth re-entering that
failure mode.

**V2 never spans two speakers** — asserted in code and pinned by a test (§5, C2).

### 3.3 What changes in the stored record

- `signal_turn_index` becomes the **first** turn index of the trigger move (where the move
  begins), not the last. The full index list goes into the signal dict as `move_turn_indices`, and
  the block's last index as `block_end_index`. Both land inside the existing unconstrained
  `gap_events.gaps` JSONB — **zero schema DDL**, same discipline as the 2026-08-10 realignment.
- No `tuning.yaml` key is added. Nothing here is a threshold: the block boundary is unchanged,
  the grouping key is speaker identity, and the attribution is "last speaker". All three are
  properties of the data.

---

## 4. Files touched

| file | change |
| --- | --- |
| `ego_trap/transcript_parser.py` | `client_blocks()` and `client_moves()` (new, pure, side-effect-free — measurable by the harness without a run, the `build_clause_pool` precedent); `classify_response_outcome` gains `"client_continued"`; `turns_until_next_client` is **unchanged** and keeps its current meaning, so `rubric_lookup` keeps working while callers migrate to the block boundary |
| `ego_trap/signal_check.py` | `_check_via_similarity` and `resolve_signals` iterate moves, not raw CLIENT turns |
| `ego_trap/rubric_lookup.py` | `extract_csm_response_window` keys off `block_end_index` |
| `ego_trap/pipeline.py` | route `"client_continued"` to no gap record; print it in the Stage 1/5 line |
| `ego_trap/gap_output.py` | unchanged — deliberately; no new gap type |
| `tests/test_ego_trap_transcript_parser.py`, `tests/test_ego_trap_signal_check.py` | extended |
| `calibration/probe_client_move_segmentation.py` | promoted from scratchpad — reproduces every §2 number, `--load` re-reports free |

**Out of scope, recorded not fixed:** `v1/layer_b.extract_pairs` (§2.2). Repairing it forces a
full A/B/C re-run, which reshuffles UMAP clusters, orphans every `milestone_performance` row
(`milestone_id` is the array position) and moves the 385-milestone baseline — the exact damage the
criteria rewrite was done in-place to avoid. **The 443 lost pairs are the piece worth bundling
into any future re-run that is happening for another reason.**

---

## 5. Controls

**No control, no verdict.** Four judges in this effort have produced publishable-looking numbers
before failing their own nulls.

| # | control | construction | bar |
| --- | --- | --- | --- |
| **C1** | **reading** | 30 exchanges whose trigger changed under V2, read verbatim: is the merged text one coherent client move, or two fused? | **≤ 3 of 30 fused** |
| **C2** | **no cross-speaker fusion** | every emitted move has exactly one distinct `speaker_raw` | asserted in code + a test; **any violation is a bug, not a tuning question** |
| **C3** | **Arm A as a null arm** | Arm A alone, scored end to end | the scored set must be **byte-identical** to baseline |

**C1 is the counterweight, and it is the point.** Every aggregate in §3.2 improves monotonically
as merging gets more aggressive — V3 scores best on all of them. A metric that only counts the
good outcome cannot return a no; that is the defect `skills.sweep`'s `cross_scenario_coverage` had
and the defect `_match_milestones`' merge-blindness had. C1 is the measurement that gets **worse**
when merging over-reaches, and it is the only thing standing between V2 and V3.

**C3 is free and is the strongest guarantee in the design.** Arm A changes only a label on
unscored events. If a single attempt, hit or scenario assignment moves, the implementation is
wrong and the run stops before Arm B is measured.

---

## 6. Gates and stopping conditions

**Free gates — all computable before a single Gemma call:**

| # | gate | bar | predicted |
| --- | --- | --- | --- |
| **G1** | `"none"` outcomes across the 100 transcripts | **≤ 40** | 35 |
| **G2** | answered exchanges with a substantive trigger | **≥ 73%** | 73.1% |
| **G3** | answered-exchange count | **identical (3,247)** — the block boundary is unchanged, so only trigger *text* moves | 3,247 |
| **G4** | C2 cross-speaker fusion | **0** | 0 |

### 6.1 The denominator changes, and a raw before/after is therefore not clean

**G3 governs answered *exchanges*, not *signals*.** A better trigger embeds differently, so it
clears the sink comparison differently: recovering 135 filler triggers should push **more**
exchanges past rejection and **raise** attempts above the 4,181 baseline. That is the design
working, not drifting — but it means the headline weighted score is computed over a different
denominator on each side and **cannot be compared directly**. This is the defect the brief named
in advance, and the codebase has paid for it at least five times (`compare_criteria_ab`'s
attempt-drift refusal, `replay_layer_c_admitted`'s volume-matched placebo, `trial_skills`'
as-written control, the coverage arms' unconditional denominator, and the ceiling harness'
population-asymmetric arms).

**So the comparison is split into two populations, decided now:**

| population | size (predicted) | what it is for |
| --- | --- | --- |
| **UNCHANGED** — trigger text byte-identical under baseline and V2 | ~2,675 of 3,247 | the **matched control**. Same input, same rubric, same grader ⇒ any movement here is noise, and it should sit inside ±0.006 |
| **CHANGED** — trigger text differs | 572 | where the entire effect must live, if there is one |

Reporting the two separately is what makes the run interpretable. A weighted score quoted over the
union is not a result and will not be presented as one.

**Paid gates — the end-to-end re-run:**

| # | gate | bar |
| --- | --- | --- |
| **G5** | weighted score on the **UNCHANGED** population | **≤ ±0.006** movement — this is a *control*, and a breach means the run is contaminated |
| **G6** | attempt drift on the **UNCHANGED** population | **≤ 15%** (inherited from `compare_criteria_ab.py`). Drift on the CHANGED population is *expected* and reported, never gated |
| **G7** | weighted score on the **CHANGED** population | **reported, NOT a success criterion.** No prediction is registered, because §1.1 expects the ruler to be indifferent to trigger quality |

**Stopping conditions, named in advance so a passing aggregate cannot skip them:**

1. **G1 or G2 fails** → the segmentation is not doing what §2 predicts. Stop before the run.
2. **C3 fails** (Arm A moves any score) → implementation bug. Stop; fix; re-verify.
3. **C1 finds > 3 of 30 fused** → V2 over-reaches. Fall back to V1, or ship Arm A alone. **Do not
   respond by re-tuning the grouping rule** — that is how a result gets tuned into existence, and
   it has already failed three times in this codebase.
4. **G5 or G6 breaches on the UNCHANGED population** → the control moved when its inputs did not.
   The run is contaminated; report it and claim nothing about the CHANGED population.
5. **G7 moves by more than ±0.02 on the CHANGED population** → **treat as suspicious, not as
   success.** §1.1 predicts the ruler is indifferent to trigger quality. A large move means either
   something other than segmentation changed, or the ruler is sensitive in a way four prior
   measurements say it is not — and it must be explained before it is reported as a win.

---

## 7. Pre-registered thresholds — inherited vs invented

| value | source |
| --- | --- |
| `_is_substantive` (≥5 content words) | **inherited** — `v1/layer_b` |
| `trigger_response_coupling` | **inherited** — `shared/trigger_quality.py` |
| length-match band \|log ratio\| ≤ 0.25 | **inherited** — head-to-head spec |
| attempt drift ≤ 15% | **inherited** — `calibration/compare_criteria_ab.py` |
| ±0.006 weighted noise band | **inherited** — `calibration/measure_scoring_noise.py`, measured |
| the move rule (group by speaker; last speaker owns the reply) | **derived** from §2.3, not chosen |
| block boundary | **unchanged** from production |
| **G1 ≤ 40** | **derived** — 35 last-turn-of-call blocks, measured, plus headroom |
| **G2 ≥ 73%** | **derived** — V2's measured 73.1% |
| **C1 sample 30, bar ≤3** | **invented** |
| **G7 ±0.02 as suspicious** | **invented**, at ~3× the measured noise band |
| UNCHANGED / CHANGED population split | **derived** — forced by §6.1's denominator change, not chosen |

**No `tuning.yaml` key is added by this design.**

---

## 8. Cost and operating procedure

| stage | cost |
| --- | --- |
| Arm A + all free gates (G1–G4, C1, C2) | **0 Gemma** |
| Arm A end-to-end null run (C3) | ~230 calls / ~70 min |
| Arm B end-to-end | ~230 calls / ~70 min |

**Before any Layer D re-run, in this order:**

1. Snapshot the current baseline: `CREATE SCHEMA baseline_20260813; CREATE TABLE ... AS SELECT ...`
   for `gap_events`, `milestone_performance`, `signal_recognition_gaps`, `csms`.
2. Confirm no live run: `Get-CimInstance Win32_Process -Filter "Name='python.exe'"`. **A harness
   reporting a task as stopped is not evidence the process died** — believing that cost a full run
   and ~80 calls on 2026-08-10. One run shows as two PIDs (the venv shim); two different *start
   times* is the problem. Prefer `ops/run_noisefloor.ps1`, which performs this check and aborts.
3. `python ops/clear_ego_trap_data.py` — `gap_events` has only a SERIAL PK so re-processing
   appends duplicates, and `upsert_milestone_performance` does `attempts = attempts + 1`.
4. Check whether a parallel session is spending the same two Gemma keys.

**Baseline to compare against** (2026-08-13, 100 calls, live in Postgres):
attempts 4,181 · milestones touched 378 · full hits 141 · partial 374 · **weighted 0.0785** ·
obs/milestone mean 11.1, median 7.0.

---

## 9. Reproducibility

Every number in §2 comes from two harnesses, both zero-cost and both to be promoted out of
scratchpad as part of this work:

- block/move structure over both corpora → the §2.1 and §2.2 tables
- the anchor probe → §2.3, persisting `artifacts/layer_b_anchor_probe.json` and re-reporting free
  via `--load`

**The paid artifact is flushed, not just the conclusions drawn from it** — the lesson from
`compare_embedders.py`, which persisted only derived scores and made changing a criterion cost
another 461 requests.

---

## 10. What this design does not claim

- It does not move the ceiling, and §6 G5 treats a large move as suspicious rather than as a win.
- It does not address the grader's missing inputs (the client turn, the scenario, the milestone
  label are all withheld at grading time). That is a separate, measured defect.
- It does not repair `extract_pairs` (§2.2, §4).
- It does not touch wall 2. A better-segmented trigger does not create axes to report on; 405
  milestones at a median of 7 observations is unchanged by anything here.

---

## Status update — the four-arm trial RAN (2026-08-15). Free gates measured; nothing shipped.

Harness `calibration/trial_client_move_arms.py`, artifact `artifacts/client_move_arms.json`,
log `logs/trial_client_move_arms.log`. 3,247 answered exchanges, 161 scenarios (85 coachable /
76 sink). Zero Gemma, Postgres session `SET default_transaction_read_only = on`, no production
file modified. Every admit decision made by production `score_client_turns` + `select_signal`.

**A fifth arm was added after reading samples:** **E** = use the baseline trigger wherever the
baseline already admits, and only intervene where it produces nothing. Precedent is the response-
taxonomy auto-pass's "never disturb an already-homed pair", which held on real data.

| arm | trigger rule | scored | lost | gained | net | of the 177 filler cases, fixed |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | block's last turn | 937 | – | – | – | 0 |
| B | whole move, stitched | 964 | 40 | 67 | +27 | 36 |
| C | `_is_substantive` filter, then stitch | 837 | **156** | 56 | **−100** | 35 |
| D | junk-bin filter per turn, then stitch | 1009 | 9 | 81 | **+72** | 37 |
| E | D, but only where baseline admits nothing | 1018 | **0** | 81 | **+81** | 29 |

**The dilution risk this design worried about is REFUTED.** Coachable-minus-sink margin by turns
merged does not fall — B is flat (+0.038/+0.034/+0.040/+0.035) and D *rises*
(+0.037/+0.043/**+0.048**/+0.041). Admitted-trigger cosine stays inside the calibrated band
(p10 .501 / p50 .581 / p90 .648): baseline p50 0.569, B 0.578, C 0.585, D 0.576. **No threshold
requires recalibration**, which was the main risk to the rest of `tuning.yaml`.

**Arm C is rejected, and it is the ninth consecutive failure of a per-item threshold filter here.**
It deletes more than it saves (−156/+56) and empties 886 moves outright. Its 100% substantive rate
is trivially true — that is the property it filters on. Consistent with the eight sink-rescue
signals and with `response_word_count`'s known bias against terse expert moves.

**NEW AND ARGUABLY LARGER THAN THE DEFECT THIS SPEC ADDRESSES: Layer D's admit/reject rule is a
near-tie for a large share of every run.** |best coachable − best sink| on the baseline arm:
**14.5% of decisions sit within 0.01 of flipping, 28.3% within 0.02, 40.7% within 0.03.** So:

- of arm D's **9 losses, 8 (89%) are coin flips** — its regressions are mostly noise, not damage
- of arm D's **81 gains, 27 (33%) are coin flips** — the firm gain is **~+54, not +72**
- baseline itself admits fragments (`'I think you can have, like, a.'`) for the same reason

**This is unexamined and is recorded as an open finding**, sibling to the measured fact that the
Layer B/D top1-vs-top2 scenario margin is ~0.01 cosine. Any future Layer D number should carry
this fragility, and no arm difference under ~30 exchanges should be read as real.

**Caveat on arm D, stated rather than buried:** D's per-turn filter and D's gate apply the SAME
rule, so D's admission is effectively "does this block contain any coachable-matching turn" — a
**looser gate** than baseline's "is the last turn coachable-matching". Part of D's gain is gate
relaxation, not purely better trigger text. Arm E does not have this property.

**Reading (C1) — the aggregates could not have caught these.** Arm D deletes genuinely real
content when a turn's own best match is a sink (`"we'll definitely forward those as soon as they
come up"`, `"in terms of communications, we can talk with the Jovio team through email"`). All 11
of D's regressions were read: a few are genuine (`'do you guys have a list of which sources would
be easy to apply'` is admitted alone and rejected once stitched), and 8 of 9 scored losses are
coin flips.

**Harness error worth not repeating:** the first report's `subst.trig` column counted arm D's
1,687 empty rows in the denominator and made D look like it destroyed trigger quality (41.2%).
Recomputed on the population that actually matters — the **scored** set — D is 85.8% substantive
against baseline's 85.4%, with a longer median trigger (51 vs 45 words). **A rate is meaningless
without stating its denominator**, the same defect as the ceiling arms' population asymmetry.

**Still unmeasured: the weighted score.** Everything above is free; G5/G6/G7 need the ~230-call
run. §1.1's prediction stands unchanged.

**Nothing is shipped. No production file changed, no `tuning.yaml` key added, no DB row written.**
