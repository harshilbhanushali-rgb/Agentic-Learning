# W4 — PROVENANCE

Claims audited against the code that produced them. 17 load-bearing numbers traced; every
one where a knob shipped, an approach was declared CLOSED, or a wall was declared standing.

Files audited (code):
`calibration/trial_grader_inputs.py`, `calibration/measure_scoring_noise.py`,
`calibration/compare_criteria_ab.py`, `calibration/trial_head_to_head.py`,
`shared/head_to_head.py`, `calibration/probe_retrieval_gate.py`,
`calibration/trial_skills.py`, `calibration/trial_pool_unit.py`,
`shared/cluster_evidence.py`, `calibration/null_test_taxonomy.py`,
`calibration/flag_proper_noun_clusters.py`, `calibration/validate_taxonomy_vs_layerd.py`,
`calibration/dry_run_layer_bc.py`, `ops/flag_uncoachable_milestones.py`,
`ops/rewrite_milestone_criteria.py`.

Files audited (artifacts/logs, read-only): `artifacts/grader_inputs_trial*.json`,
`artifacts/h2h_control_c{2,3,4}.json`, `logs/h2h_m5.log`, `artifacts/skills_trial*.json`,
`artifacts/pool_unit_clause.json`, `artifacts/pool_unit_turn_092.json`,
`artifacts/null_test_taxonomy.json`, `logs/` (grep for a noise-floor run — none exists).

---

## VERDICT TABLE (the 15+ numbers, worst first)

| # | number | producing script | verdict |
| --- | --- | --- | --- |
| 1 | pool unit: **8 (4.7%) vs 71 (37.2%) subject-bearing clusters** | `trial_pool_unit.py:353` | **OVERSTATED** |
| 2 | pool unit: **corr(negation, content-free) −0.149 → −0.744** | `trial_pool_unit.py` | **OVERSTATED** |
| 3 | h2h: **C1 pooled swap agreement 0.669 ⇒ "signal share 0.34"** | `trial_head_to_head.py:_verdict` | **OVERSTATED** |
| 4 | criteria rewrite: **43 up / 17 down, net +4.48, "~2× the floor"** | `compare_criteria_ab.py:91-110` | **OVERSTATED** |
| 5 | Layer D: **"~350+ calls for a median of 25"** | *no script* (prose arithmetic) | **CONTRADICTED** |
| 6 | noise floor: **±0.006 weighted, 15.6% of milestones move** | `measure_scoring_noise.py` | **UNVERIFIABLE FROM CODE** |
| 7 | derived rule: **"below ~+0.02 weighted is unmeasurable"** | derived from #6 | **OVERSTATED** |
| 8 | skills: **best validity 0.667 vs the 0.80 bar** | `trial_skills.py:502-507` | **OVERSTATED** |
| 9 | h2h: **"Not length — C4's length-matched cell is 0.875"** | `trial_head_to_head.py:538` | **OVERSTATED** |
| 10 | Layer C: **percentile 40 / fraction 0.10 "calibrated"** | `dry_run_layer_bc.py:64-65` | **OVERSTATED** |
| 11 | **"top1−top2 margin ~0.01 in BOTH taxonomies"** | `validate_taxonomy_vs_layerd.py:118` | **OVERSTATED** |
| 12 | **17 of 405 unhittable: 74 attempts, 0 hits, 12 milestones** | *no script* | **UNVERIFIABLE FROM CODE** |
| 13 | h2h: **C4 native win 0.835** (the fatal control) | `trial_head_to_head.py` | **SUPPORTED** |
| 14 | grader inputs: **77.4% / 82.3%, p=1.7e−5 / 2.8e−7; W(matched) 0.089–0.095** | `trial_grader_inputs.py` | **SUPPORTED** (provenance gap) |
| 15 | skills: **78% of milestones abstract to a one-off (315/405, 342 distinct)** | `trial_skills.py` | **SUPPORTED** (exact) |
| 16 | retrieval gate: **0.812 vs 0.631 base, CI [+0.168, +0.196]** | `probe_retrieval_gate.py` | **SUPPORTED** |
| 17 | criteria rewrite: **person language 100% → 3%** | `ops/rewrite_milestone_criteria.py:104` | **SUPPORTED** (but see note) |

Dropped as low value — reported but no decision rests on them: the `~[350,450]` milestone
band (OPEN_PROBLEMS §"Not implemented" — nothing consumes it); "dry run predicted 74/154
zero-milestone vs production 3/85" (already self-retracted in CLAUDE.md as "the dry run
cannot predict Layer C yield").

---

### FINDINGS

#### 1. `thin_fraction` is ~70% explained by item LENGTH, so "subject-bearing" mostly means "long" — and the 4.7%-vs-37.2% headline compares two arms whose items differ in length by construction

- **File:line**: `calibration/trial_pool_unit.py:187` (`thin = ... not cluster_evidence.is_substantive(t, 5)`), `:353` (`subj = [c for c in surviving if c["thin"] < 0.30]`), `shared/cluster_evidence.py:200-213`.
- **What is wrong**: `is_substantive(text, 5)` is an **absolute** count of ≥5 non-stopword alphabetic tokens. It is applied unchanged to a single spaCy *clause* in one arm and to a whole multi-sentence *turn* in the other. A turn is content-free only if **every** sentence in it is; concatenation can only increase the count. So the treatment arm's `content_free` rate, and every cluster metric derived from it, is mechanically lower before any question of unit quality arises. Computed from the artifacts, `corr(mean sample word count, thin_fraction)` is **−0.839** (turn arm) and **−0.787** (clause arm) — the "subject-bearing" test is very largely a length test in both arms. The spec's own defences (the `jovio` false-positive class, the gemini cross-check against blind judges) address the proxy *within* the turn arm; none of them validates it **across** the unit boundary, which is the only comparison the headline makes.
- **What number it corrupts, and in which direction**: **INFLATES the turn arm** in `subject-bearing clusters 8 (4.7%) → 71 (37.2%)` and in `pool content-free 59.1% → 32.8%`, i.e. inflates the whole case for the pool-unit change. Also inflates `junk (≥70% content-free) 98 → 78`. This is the primary quantitative evidence in the pool-unit design; the design says "the gain is the UNIT, not the threshold", and part of the gain is the *measuring instrument* being unit-dependent.
- **Confidence**: certain that the test is not unit-invariant and that length dominates it; **likely** on the size of the residual real effect (the length proxy I could compute is the ≤6 stored `samples` per cluster, not full membership).
- **Cheapest way to verify**: recompute `thin` with a length-normalised rule (e.g. ≥5 content words *per sentence*, or "any sentence is substantive") for the turn arm and re-report `subject_share`. Free, artifacts only. Or just read `corr(samplewords, thin)` off `artifacts/pool_unit_{clause,turn_092}.json`.

#### 2. The stance measure that replaced the retired null test is confounded by the same variable — cluster item length

- **File:line**: `calibration/trial_pool_unit.py:149-167` (`_negation_flags`) and the per-cluster `neg_rate` / `thin_fraction` pair; spec `2026-08-14-layer-a-pool-unit-design.md:513` ("`corr(negation, content-free) = −0.744` is the design's stated goal expressed as a correlation"), `:523-531` (the null-based check 1 is RETIRED and this correlation is elevated in its place because it "needs no null").
- **What is wrong**: both terms of the correlation rise/fall with item length. A longer turn is more likely to contain a spaCy `neg` dependency **and** more likely to clear the 5-content-word bar. Measured off the artifacts: turn arm `corr(words, neg_rate) = +0.772`, `corr(words, thin_fraction) = −0.839`, `corr(neg, thin) = −0.768`. Partialling out mean item length collapses the correlation to about **−0.35**. The clause arm's weak −0.149 is weak for the same reason in reverse: clause lengths are compressed, so there is little length variance to drive either term. This is a direct sibling of `audit_null_instrument.py`'s already-recorded `corr(lift, mean word count) = +0.65`; that audit was run on the *null* instrument and never on this one.
- **What number it corrupts, and in which direction**: **INFLATES** the clause-vs-turn contrast `−0.149 → −0.744`, which OPEN_PROBLEMS.md:192 and CLAUDE.md both cite uncaveated as the clean evidence that stance survives in turn mode. Roughly half the magnitude is length.
- **Confidence**: likely (same sample-based length proxy caveat as #1; the direction and rough magnitude are robust).
- **Cheapest way to verify**: compute per-cluster mean word count over full membership and report the partial correlation of `neg_rate` and `thin_fraction` controlling for it. Free.

#### 3. C1 pools a control whose correct answer is a coin flip, and counts indecision as reversal — the number that closed head-to-head is the wrong statistic

- **File:line**: `calibration/trial_head_to_head.py:614-637` (`_verdict`, "C1 is pooled across all three controls"), `shared/head_to_head.py:126-146` (`swap_agreement`, strict equality).
- **What is wrong**: two independent problems in one figure.
  (a) **C2's ground truth is indifference** — its own docstring says "Both expert, both transplanted → a coin flip is the correct answer". A judge that correctly recognises two adjacent-rank replies as equally good *must* answer near-randomly on swap, so C2's swap agreement is pinned near 0.50 no matter how good the judge is. Pooling it into C1 cannot distinguish "the judge is unreliable" from "the items are genuinely tied". Recomputed per stage from the artifacts: **c2 = 0.570, c3 = 0.581, c4 = 0.847** (pooled 0.669, matching `logs/h2h_m5.log`). **On C4 — the stage that produced the fatal result — the judge clears the 0.75 bar comfortably.**
  (b) `swap_agreement` uses strict equality, so an item that is decisive one way and a *tie* the other counts as disagreement. Recomputed pooled: flip rate **0.201**, one-decisive-one-tie **0.130**. The prose derives "signal share = 2a−1 = 0.34" from a = 0.669, i.e. from a number that charges indecision as reversal. Using reversal-only agreement (1 − 0.201 = 0.799) the same formula gives **0.60**.
- **What number it corrupts, and in which direction**: **DEFLATES** C1 and therefore the derived "signal share 0.34". CLAUDE.md's "C1 is the deeper failure and no pairing design fixes it — that is a property of the judge, not of the comparison" is not supported by a pooled figure dominated by a stage designed to be undecidable. (The *overall* CLOSED verdict survives on C4, which is independent — see #13. What does not survive is the specific claim about the judge's reliability.)
- **Confidence**: certain (recomputed directly from `artifacts/h2h_control_c{2,3,4}.json`; per-stage figures match the committed log exactly).
- **Cheapest way to verify**: `logs/h2h_m5.log` already prints `per stage: c2=0.570 c3=0.581 c4=0.847`. Read that line against the pooled 0.669 above it.

#### 4. `compare_criteria_ab.py` scores a milestone that exists in only one arm as `0.0` in the other, so ~99 attempts the baseline arm lost to Gemma failures are counted as the rewrite improving

- **File:line**: `calibration/compare_criteria_ab.py:91-110` (`FULL OUTER JOIN` + `COALESCE(...,0)` then `ow = (oh+0.5*op)/oa if oa else 0.0`).
- **What is wrong**: a row missing from the baseline arm yields `oa = 0 ⇒ ow = 0.0`, which asserts "scored and scored zero" rather than "not measured". CLAUDE.md records that the baseline arm **lost ~99 attempts to 2 Gemma batch failures** (864 vs 963, +11.5% drift). Every milestone whose baseline row vanished with those batches, and which scored anything at all after, is counted as `improved`. The script prints the drift and passes it against its own 15% gate, but — unlike `measure_scoring_noise.py:271`, which prints `milestones present in only one run` — it **has no such counter**, so the size of the contamination is invisible in the output. Note also that `measure_scoring_noise.py:256` warns at **>5%** drift on exactly this concern; the rewrite comparison sits at 11.5% and passes only because `compare_criteria_ab.py` chose a looser 15%.
- **What number it corrupts, and in which direction**: **INFLATES** `43 improved / 17 worsened` and the derived `net +4.48`, in favour of the rewrite. CLAUDE.md and PROBLEMS_AND_FIXES both cite `rewrite net +4.48 vs floor net +2.12, ~2×` as the surviving evidence that the rewrite is real *after* the shape argument was withdrawn. The headline `weighted 0.043 → 0.068` uses pooled `_totals` and is much less affected — that part stands.
- **Confidence**: certain about the mechanism; **likely** about it being large enough to matter (99/864 ≈ 11% of baseline attempts, against a 60-mover total).
- **Cheapest way to verify**: add one line to the existing query — `COUNT(*) WHERE o.rubric_id IS NULL OR n.rubric_id IS NULL` — and re-run against `pre_criteria_20260810`. Zero Gemma, zero writes.

#### 5. "~350+ calls for a median of 25 observations" is a LINEAR projection made in the same paragraph that declares linear projections wrong

- **File:line**: no script — CLAUDE.md "Layer D over 100 CSM calls" section; OPEN_PROBLEMS.md:151 and :696 repeat it as fact.
- **What is wrong**: the paragraph's own measurement is that observations per milestone grow **sub-linearly** — 5.3× the calls gave 4.7× the attempts but only 2.9× the per-milestone mean, because the milestone denominator also grew 237 → 378. It then states the requirement as ~350 calls, which is exactly `100 × 25/7` — the linear extrapolation it just forbade. Fitting the measured exponent (per-milestone ∝ calls^0.64, from 2.9× over 5.3×) gives `100 × (25/7)^(1/0.64) ≈ **750 calls**`.
- **What number it corrupts, and in which direction**: **UNDERSTATES the data requirement by roughly 2×**. This is load-bearing: OPEN_PROBLEMS.md:699 raises the feasibility question "whether 350+ CSM calls exist or can be obtained. Only 107 CSM transcripts are [available]" — at ~750 the answer changes from "hard" to "not available".
- **Confidence**: certain (pure arithmetic on numbers stated in the same paragraph).
- **Cheapest way to verify**: recompute `100 * (25/7)**(1/0.64)`. No data needed.

#### 6. No run of `measure_scoring_noise.py` was ever captured, and the script's own docstring attributes "15.6%" to the CONTAMINATED comparison it now refuses to make

- **File:line**: `calibration/measure_scoring_noise.py:30-38` — *"This script then reported 15.6% movement and +0.000 drift as a noise floor. Nothing in its output hinted that the comparison was meaningless."*
- **What is wrong**: CLAUDE.md and PROBLEMS_AND_FIXES:618-628 both state the clean floor as **"±0.006 weighted, and 15.6% of milestones (37/237) move on their own"**. The script's docstring says 15.6% is what the *blended two-runs-in-one-schema* comparison produced — the one the duplicate guard was written to reject. The two accounts also disagree on the drift (+0.000 in the docstring, +0.006 in the prose). `grep -r "MOVEMENT RATE" Brain/logs/` returns **nothing**: no run of this script was ever redirected to a log, so neither account can be checked. Either the clean re-run reproduced the contaminated number to three significant figures (possible but a striking coincidence), or the retracted figure was carried into the prose.
- **What number it corrupts, and in which direction**: unknown direction — the floor could be higher or lower than 15.6%. It matters because **every A/B verdict in the Layer D work is graded against it**: the uncoachable-skip retraction, the "no per-milestone winner is citable" rule, and the ±0.006 band attached to every "3.x%" figure on the page.
- **Confidence**: certain that the two accounts conflict and that no artifact or log exists; speculative as to which is right.
- **Cheapest way to verify**: re-run `python calibration/measure_scoring_noise.py --a arm3_run1_20260810 --b arm3_run2_noisefloor_20260811 > logs/noisefloor.log`. Zero Gemma, zero writes, DB read only — and it should have been captured the first time.

#### 7. "±0.006" is the range of **two** observations reported as if it were a band, and "+0.025 is ~4.1× the band" inherits that

- **File:line**: derived from #6; hardcoded into `calibration/trial_skills.py:65` as `_NOISE_BAND = 0.006` and `_MEASURABLE_CHANGE = 0.020`, where it sets the entire power gate.
- **What is wrong**: with n = 2 runs you observe exactly one difference. The expected range of two normal draws is 1.128σ, so 0.006 estimates σ of the run-to-run difference, not a 95% interval — that would be roughly ±0.015. `+0.025 / 0.006 = 4.1×` therefore reads as ~4σ when the honest reading is closer to ~1.7 half-widths. Separately, the two floor runs had **identical attempt counts (889/889)** while the criteria A/B had 864/963 — so the treatment measurement carries a source of variance (batch failures dropping whole signals) that the floor measurement by construction does not.
- **What number it corrupts, and in which direction**: **OVERSTATES the confidence** in "the criteria rewrite's +0.025 is real" and, via `trial_skills.py`, hard-codes an over-tight `_NOISE_BAND` into the derivation of the skills power bounds (`K ≤ 11/17/18/35`, median member floors `38/24/23/12`). A wider true band makes those bounds *stricter*, so the skills FAIL verdict is not endangered — but the "4.1× the band" claim is.
- **Confidence**: certain about the estimator; the effect on the rewrite verdict is likely (it probably still clears, just not at 4×).
- **Cheapest way to verify**: a third identical run would give a real SD. Or state the claim as "one observed difference of 0.006" rather than "±0.006".

#### 8. `judge_groups` coerces every unparseable verdict to the FAILING value and silently drops missing ones, and the validity denominators are never persisted

- **File:line**: `calibration/trial_skills.py:399-403` — `out[...] = verdict if verdict in ("same_move","fused") else "fused"`; groups absent from the model's reply are simply never added to `out` (contrast `abstract_behaviours:374-376`, which does warn). `:517-529` — the artifact stores `validity` as a bare ratio; `verdicts` and `provenance` are not written.
- **What is wrong**: `V(t)` is the numerator of the gate that closed Wall 2. A malformed or truncated batch reply pushes it **down**, toward the "no window" conclusion, with no counter. And the denominators are tiny: `_N_JUDGE_GROUPS = 12` real groups per threshold, sampled only from groups of size ≥ 2, and the stored ratios back out to n ≈ 3–9 (`0.5555… = 5/9`, `0.6666… = 6/9`, `0.20 = 1/5`). At n = 9, observing 6/9 when the true validity is exactly 0.80 has probability ≈ 0.26 — so **"best validity 0.667, still short of the 0.80 bar" is not distinguishable from the bar**. The positive control `V = 1.00 at t = 0.95` rests on a similarly small n.
- **What number it corrupts, and in which direction**: **DEFLATES `V(t)` at every threshold**, i.e. biases toward the published FAIL. The published headline "best validity 0.667 vs the 0.80 bar" is **OVERSTATED as a rejection**. *The overall closure survives*: the point that actually decides it is `V = 0.20` at t ≤ 0.675, and 1/5 against a 0.80 bar is significant (p ≈ 0.007). But "off by 4×, not a near miss" describes that one point, not the gemini run's 0.667, and CLAUDE.md's three-attempt table reads as if all three are equally decisive.
- **Confidence**: certain on the coercion and the missing counter; certain that denominators are unrecoverable from the artifact; likely on the exact n per threshold.
- **Cheapest way to verify**: persist `verdicts` + `provenance` in the payload and re-report. Free — but it needs a re-run to recover the past denominators, which no longer exist.

#### 9. "Not length" is ruled out on n = 8

- **File:line**: `calibration/trial_head_to_head.py:538-541` (`length_matched(..., _LENGTH_BAND)`), output in `logs/h2h_m5.log`.
- **What is wrong**: the length band admits **8 of 100** decisive C4 items (and 6 of 100 for C2, 10 for C3). CLAUDE.md states flatly *"Not length (C4's length-matched cell is 0.875, **higher**)"*. A binomial 95% CI on 7/8 spans roughly [0.47, 1.00] — it excludes nothing, including a value below the 0.75 bar. The same sentence rules out position (slot-1 rates 0.485–0.520, n ≈ 200 per stage — that one is fine) and retrieval quality (cosine quartiles, n = 25 each — thin but defensible), so a reader gets three confound rule-outs at three wildly different power levels presented as one list.
- **What number it corrupts, and in which direction**: does not change C4's 0.835. It **overstates the certainty** that C4's result is not a length artifact — which matters, because length is the one confound that would make C4 an artifact of the *harness* rather than of cross-corpus comparison.
- **Confidence**: certain (n is printed in the committed log).
- **Cheapest way to verify**: `grep "length-matched" Brain/logs/h2h_m5.log` — the n is on the line.

#### 10. Layer C's shipped `milestone_relevance_percentile: 40` was selected at the edge of its search grid, by an objective that is monotone in the direction of not filtering

- **File:line**: `calibration/dry_run_layer_bc.py:64-65` — `_SWEEP_PERCENTILE = [40, 60, 75]`, `_SWEEP_FRACTION = [0.05, 0.10, 0.15, 0.25]`; `:277` — the reported objective is `zero = scenarios left with NO milestone`.
- **What is wrong**: the objective counts over-filtering only. It is minimised by filtering less, and has **no counterweight** measuring whether the surviving clauses are on-topic. 40 is the lowest percentile in the grid and it won; the grid never brackets a minimum, so the run cannot distinguish "40 is optimal" from "the objective is monotone and the sweep stopped at 40". This is the taxonomy-#5 shape (a metric whose degenerate case scores best). The fraction was a **tie** at 0.05 and 0.10 (74 each) and was resolved by argument, not by the metric. CLAUDE.md's own later finding is exactly what a permissiveness-rewarding objective predicts: *"deliberately wrong placebo clauses survived the p40 cut at 53.9–57.2% vs 57.7–63.0% for real rescued content — a ~6-point gap"* (also OPEN_PROBLEMS.md:534).
- **What number it corrupts, and in which direction**: **p40 is systematically too permissive** — it is a shipped production knob feeding every rubric's clause pool. "Layer C is calibrated to percentile=40" overstates what a one-sided grid establishes.
- **Confidence**: certain about the grid edge and the one-sided objective; likely that a lower percentile would also have "won", which is the diagnostic.
- **Cheapest way to verify**: extend `_SWEEP_PERCENTILE` to `[10, 20, 40, 60, 75]` and re-run — zero Gemma, zero writes. If 10 also minimises `zero`, the objective is confirmed monotone.

#### 11. The "~0.01 top1−top2 margin" is measured globally, not across the decision boundary it is said to endanger

- **File:line**: `calibration/validate_taxonomy_vs_layerd.py:109-119` — `margin = bs - ss` where `second = order[:,1]`, i.e. the runner-up anywhere in the taxonomy.
- **What is wrong**: CLAUDE.md concludes *"Every Layer B/D scenario assignment rests on the winner beating the runner-up by a hair. Unexamined, and arguably a bigger problem than which taxonomy is used."* But the decision Layer D actually makes in the same script is `accepted = coach[best]` — **sink vs non-sink**. When ranks 1 and 2 are both coachable (or both sinks), a 0.01 gap changes nothing about acceptance. The margin that would support the claim is *best-coachable minus best-sink*, and the script never computes it, nor does it report how often ranks 1 and 2 disagree on `coachable`. For Layer B, a tiny top1/top2 gap is the **designed** behaviour — `relative_margin: 0.95` exists precisely to keep near-ties as multi-labels in `scenario_keys[]`.
- **What number it corrupts, and in which direction**: no computed number is wrong; the **interpretation is overstated**. A conclusion flagged as "arguably a bigger problem than which taxonomy is used" rests on a statistic that does not measure the decision.
- **Confidence**: certain (read from source).
- **Cheapest way to verify**: add `coach[best] != coach[second]` to the same function and report the margin conditioned on it. Free, same run.

#### 12. "74 attempts, 0 hits, across 12 distinct milestones" is produced by no script in the repo, and covers only 12 of the 17 flagged

- **File:line**: `ops/flag_uncoachable_milestones.py` — it queries `rubrics` only (`:108`, `:216`); it never touches `milestone_performance`. `grep -rn "milestone_performance" ops/flag_uncoachable_milestones.py` returns nothing.
- **What is wrong**: the figure was computed ad hoc and is not reproducible from the repo. It is also cited as *"the proof they are impossible rather than merely hard"* — but 17 milestones were flagged and only 12 have any attempts, so 5 have **zero evidence**. And if "0 hits" means 0 *full* hits, then at the corpus full-hit rate of ~3% the probability of 0 in 74 draws is ≈ 0.10 — a 1-in-10 outcome, not proof. (If it means 0 full **and** 0 partial, against the ~10.6% non-miss rate, it would be strong; the prose does not say which.)
- **What number it corrupts, and in which direction**: **overstates the evidence** for `layer_d.skip_uncoachable_milestones`, which ships ON and removes 17 milestones from every rubric denominator. Mitigating: the change is explicitly justified on non-metric grounds ("it stopped 74 pieces of coaching advice instructing a CSM to do something impossible"), which is sound and independent — so the shipping decision does not fall.
- **Confidence**: certain that no script computes it and that 17 ≠ 12; likely on the significance arithmetic.
- **Cheapest way to verify**: one SQL query joining `rubrics` milestones with `not_coachable_flag` to `milestone_performance`; report attempts, hits, partials **and the count with zero attempts**.

---

### CLEAN — checked and found sound

- **#13 C4 = 0.835 (the control that closed head-to-head).** I recomputed it from `artifacts/h2h_control_c4.json` using the module's own `order_average` / tie rules: **0.835, n = 85/99 decisive, tie share 0.141** — byte-matching `logs/h2h_m5.log`. C2 (0.543) and C3 (0.750) also reproduce exactly. The C4 pair construction (`_pair_for:365-373`) is correct on the point that matters: it shows **Naren's own trigger**, so the "native" side really is native and the control is not measuring the wrong thing. The structural analogy to W3 (CSM always native, expert always transplanted) holds by inspection of `_pair_for:374-375`. The overall CLOSED verdict is sound. *One provenance defect worth knowing but not a number defect*: `_flush` writes to an untagged `h2h_control_{stage}.json`, so **run 2 overwrote run 1** — the "replicated to 0.008 (0.843 → 0.835)" claim is not checkable, and two runs over the same seeded item set are in any case a measure of LLM sampling noise, not of sampling replication.
- **#14 grader-inputs headline.** Reproduced exactly from `artifacts/grader_inputs_trial_confirm{A,B}.json`: `W(matched) 0.0949 / 0.0890`, `W(unrelated) 0.0325 / 0.0421`, `D 2.92 / 2.11`, sign test `48-14-7` and `51-11-7` of 69 scenarios, `p = 1.743e−5` and `2.776e−7`, 3,540 gradings each, `judged_by` 100% `gemini-3.1-flash-lite` on both. The population-symmetry argument holds on inspection of `main:441-451`: matched and unrelated are built from **the same `row`**, only `rk` changes, and `sign_test` pairs on `source_scenario` (the response's own scenario) so the two sides of every bucket are the same responses. The benchmark travels with the rubric, which keeps the arms differing in exactly one thing. `bootstrap_d` resamples items, not milestones, which is the right unit. **The retraction of "1.2:1" is well-founded.** Two provenance gaps that are not number defects but should be fixed: (a) the payload records `pin_model`, `seed`, `smoke` and `sample_keys` but **not `--holdout` and not `--conditions`** — that the confirmation runs were leakage-clean is inferable only from `W(matched) ≈ 0.09` matching the known holdout run, not from the artifact; (b) the checkpoint key is `n_items` alone (`:460`), so re-running the same tag with a different `--model` or `--holdout` silently resumes the previous records — the exact scenario the `--model` help text invites.
- **#15 skills one-off rate.** Recomputed from `artifacts/skills_trial*.json`: v1 **315/405 = 77.8% one-offs, 342 distinct**; v2 **299/405 = 73.8%, 323 distinct**; v2's `explains a mechanism` = 29 members. Every figure in CLAUDE.md's three-attempt table matches to the decimal. The gemini arm's `reused_behaviours_from` is recorded in the artifact, so the "embedder is the only variable" claim is verifiable and true. Order-permutation drift 0.333 at t = 0.725 also matches.
- **#16 retrieval gate.** `bootstrap_lift:132-143` computes the point estimate and the CI from the same estimator (mean over queries, minus a base held fixed), so taxonomy-#7 does not apply; the base is a per-query average over a ~4,600-pair pool so its own SE is negligible. `candidate_base_rate:102-116` correctly excludes each query's own call *per query* rather than corpus-wide, which is the non-obvious right choice. The probe deliberately runs against the **full** pool rather than the coachable-only pool the h2h searches (`:169`), so `clean_top1` is not 1.0 by construction. **0.812 vs 0.631, CI [+0.168, +0.196] is sound.**
- **#17 person language 100% → 3%.** `_PERSON` at `ops/rewrite_milestone_criteria.py:104` is applied identically to both arms, so it is a fair before/after. Its `they|their` alternatives are false positives, but only in the *after* direction — the before figure is 100% and cannot be inflated further, so the measured drop is if anything conservative. *Note, not a defect*: it is a **prompt-compliance check** (the rewrite prompt at `:77` literally says "Never use he/she/they"), not an outcome measure. It is cited in CLAUDE.md alongside the +0.025 weighted delta as if the two were independent evidence for the same claim; they are not.
- **`relative_margin: 0.95`.** The derivation (`0.95 × p50 = 0.5225`, landing near p25 of the measured p10 = 0.496 / p50 = 0.550 / p90 = 0.613 band over 416 transcripts) is arithmetically sound, the sweep models the sink short-circuit (`dry_run_layer_bc.py:168-176`), and the prediction-vs-production discrepancy (63/19/18 actual vs 47/25/27 predicted) is already recorded **with** its correct mechanical explanation (73 sinks instead of 15). Nothing to add.
- **`null_test_taxonomy.py` (production 16/82 = 20%, turn 11/38 = 29%).** The script's symmetry discipline is genuinely correct and unusually well argued in its own docstring: same pool, same embedder, same top-1 assignment rule, same null, and it prints the rigged cluster-membership arm explicitly labelled as an upper bound rather than hiding it. The length confound in `size_matched_null` is real but **already documented** in CLAUDE.md's TWO CORRECTIONS block and OPEN_PROBLEMS.md:165-182, with the fix named ("draw the null matched to each scenario's own length distribution") and the fix **not yet applied** (`:100-131` still imports `size_matched_null` from `trial_pool_unit`). No new finding; the caveat as written is accurate.

### Documentation hazard (no number affected)

CLAUDE.md's pool-unit section uses "beats/exceeds its own null" with **opposite polarity** in two adjacent paragraphs: in `null_test_taxonomy.py` beating the null is *good* (coherence), while in `flag_proper_noun_clusters.py:379-380` exceeding the null's p99 is *bad* (account concentration). The composite "**9 of 38 survive both the null test and reading**" is assembled by hand from both plus a manual read (11 pass the coherence null − 2 judged junk); no script computes 9. Worth one clarifying word each, and worth knowing that "9" is not reproducible from any artifact.
