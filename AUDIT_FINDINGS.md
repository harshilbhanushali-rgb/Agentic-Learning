# Measurement-integrity audit — findings

**Date:** 2026-08-15
**Scope:** 70 files under `Brain/` + 17 published numbers, across 15 subagents in 4 waves.
**Standing rules observed:** nothing was fixed, edited, run, committed, or connected to Postgres /
Pinecone / any LLM API. Artifacts under `Brain/artifacts/` were read; several auditors wrote
throwaway probe scripts to recompute figures from them, and those recomputations are preserved.

**Result: ~154 findings.** Wave 1 (pytest suite) 45 · Wave 2 (calibration) 69 · Wave 3
(production) 28 · Wave 4 (provenance) 12. Of 17 load-bearing published numbers traced:
**5 SUPPORTED, 9 OVERSTATED, 1 CONTRADICTED, 2 UNVERIFIABLE FROM CODE.**

**The one-line summary: the pipeline is in better shape than the instruments.** Production carries
four real defects; almost nothing that *measures* something is trustworthy as written.

Full detail lives in the per-wave files, which this document does not replace:

| file | contents |
| --- | --- |
| `PART1-WAVE1.md` | 45 test-suite findings, + a 34-row table of which tests constrain a reported number |
| `PART2-WAVE2.md` | 69 calibration findings, + the verdicts-that-move table |
| `PART3-WAVE34.md` | 28 production findings + the 17-number provenance table |
| `W1-T*.md`, `W2-C*.md`, `W3-P*.md`, `W4-PROV.md` | the 15 raw auditor reports |
| `BRIEF.md` | the shared 15-item bug taxonomy every auditor worked from |

---

## TOP FINDINGS

Ranked across all waves by how badly a result is distorted. Weighted upward: still live and
reproduces on the next run; already contaminated a shipped decision; a CLAUDE.md number the code
does not support.

### 1. The `kind == "scenario"` enum collapse was never fixed in code — the retraction exists only in CLAUDE.md prose

- **File:line**: `calibration/aggregate_cluster_verdicts.py:83`, consumed `:85-97`, `:115`; stale
  output at `artifacts/cluster_verdict_summary.json`. Producer is four-valued
  (`trial_adjudicate_gemini.py:301-304`), and `merged` means **RETAINED** (`v2/layer_a.py:504-529`).
- **What is wrong**: re-running the script today reproduces the withdrawn finding verbatim,
  including the printed `"Gemma sank it, judge says COACHABLE: 56 (Gemma may be over-sinking)"` and
  `"-> 1831 turns (14.6%)"`. No cross-tab anywhere in the file — the fix the incident's own lesson
  demanded was never applied. `flag_proper_noun_clusters.py:164` does print a 4-way cross-tab; this
  file does not.
- **Corrupts, direction**: agreement **deflated** 76.3% → true **93.9%** (min 16); "over-sinks"
  **inflated** 0 → 56 clusters / 1,831 turns; disagreement direction inverted. Verified cross-tab:
  scenario 36/2, **merged 56/13**, mechanics 0/129, logistics 0/9.
- **Confidence**: certain. **Verify**: `grep -n 'kind"\] == "scenario"' calibration/aggregate_cluster_verdicts.py`

### 2. The sink-pool judge was told the sink pairs span the UNION population's calls — and that artifact already shipped to production

- **File:line**: `calibration/diagnose_sink_pool.py:288-290` (`_render_cluster`), built `:218-219`.
- **What is wrong**: `distinct_calls` / `call_coverage` are computed over sink members **plus** the
  volume-matched control, then rendered as `"{n_sink} discarded pair(s) ... spanning
  {distinct_calls} distinct call(s)"`. A pair belongs to one call, so this is arithmetically
  impossible: cluster_2 `n_sink=10` → "28 calls"; cluster_7 22 → 28; cluster_6 31 → 53; cluster_3
  61 → 85; cluster_8 81 → 113. The control was introduced *precisely* so it would not be shown to
  the judge (`:205-208`), and its call coverage is fed in anyway wearing the sink pool's label.
  `PROMPT_SINK_POOL_TRIAGE` names distinct-call support as a judging criterion.
- **Corrupts, direction**: **inflates** recurrence evidence for every mixed cluster, biasing the
  verdict away from `genuine_sink`. All five arithmetically-impossible clusters got non-sink
  verdicts; the only two `genuine_sink` verdicts are the two where inflation is impossible.
  Corrupts the headline 2/609 – 5/199 – 2/175 split and both homeless-topic figures quoted in
  CLAUDE.md. **This chain already ran against the live `public` schema** — the same
  `sink_pool_clusters.json` verdicts fed `graduate_sink_topics.py`, which graduated 4 scenarios and
  rerouted 164 pairs.
- **Confidence**: certain (defect + arithmetic); likely (verdict-direction consequence, 5/5 but n=9).
- **Verify**: free — read `n_sink` vs `distinct_calls` per cluster in `artifacts/sink_pool_clusters.json`.

### 3. Layer C's "relevance filter" is a fixed 60% quota — it can never reject anything

- **File:line**: `v2/layer_c.py:108-109`
- **What is wrong**: `cutoff = np.percentile(relevance, percentile)` then `keep = relevance >= cutoff`.
  A percentile *of the population being filtered* always keeps exactly `100 − percentile` percent.
  At the calibrated `percentile: 40` it drops the bottom 40% of every scenario's clauses regardless
  of whether any are off-topic, and keeps 60% even if all are.
- **Corrupts, direction**: taxonomy item 5. **Deflates** a clean scenario's clause pool by 40% for
  nothing; **cannot** remove contamination from a dirty one. Invalidates reading the percentile
  sweep as a quality knob — it measured pool size. **Mechanically explains** the recorded open
  finding that placebo clauses survived p40 at 53.9–57.2% vs real content's 57.7–63.0%: a quota
  cannot separate them, and the ~6-point gap is the residual ordering effect.
- **Confidence**: certain. **Verify**: `grep "Relevance filter" Brain/logs/*.log` — every `N -> M`
  line has `M/N ≈ 0.60`.

### 4. A mixed CSM/teammate window is graded as if the CSM said all of it, while the CSM is handed only their fragment

- **File:line**: `ego_trap/rubric_lookup.py:91-94` against `ego_trap/transcript_parser.py:100-103`
- **What is wrong**: `classify_response_outcome` returns `"csm"` if **any** CSM turn appears in the
  window, but `extract_csm_response_window` joins **only** the CSM turns, dropping every
  `OTHER_JOVEO` turn. When a teammate gives the substantive answer and the CSM says "yeah, exactly",
  it is not reclassified as `Deferred_To_Teammate` (that fires only when there is *no* CSM turn),
  and the fragment is scored against the full rubric. The protection has a hole exactly where it is
  most needed.
- **Measured over 2,351 scored windows / 106 transcripts**: **408 (17.4%) mixed**; **158** have the
  CSM under 34% of the words; **384 (16.3% of all scored windows) contain ≤5 CSM words** against a
  ~6-milestone rubric.
- **Corrupts, direction**: `milestone_performance.hits` / `partial_hits` **deflated**,
  `milestones_missed` **inflated**, unambiguously. A direct, unexamined contributor to the ~9%
  `W(matched)` level — and a *population* defect, so no prompt change touches it.
- **Confidence**: certain (mechanism and rates).

### 5. The pool-unit headline measures string length, not subject matter

- **File:line**: `calibration/trial_pool_unit.py:187/246/353`, `trial_pool_unit_gemini.py:225/290` —
  all call `cluster_evidence.is_substantive(text, 5)` (`shared/cluster_evidence.py:200-213`).
- **What is wrong**: `is_substantive` is an **absolute** count of ≥5 non-stop tokens in ONE pool
  item. Clause-arm items are sentences; turn-arm items are whole turns, and concatenation SUMS
  content words. The proxy cannot report a higher content-free rate for turns than clauses on the
  same text — a metric that can only move one way when the unit changes (item 5), with the arms
  differing on exactly the property the threshold is sensitive to (item 1).
- **Measured**: mean words/member 11.5 (clause) vs 28.7 (turn). `corr(thin_fraction, mean words)` =
  **−0.787** / **−0.839**. Binned by length the arms are **indistinguishable**; the entire gap is 53
  turn clusters at ≥40 mean words vs the clause arm's 1. The turn arm also has *more* ≤8-word
  clusters (67 vs 60) — turn mode did not remove backchannel families, it added long clusters beside
  them.
- **Corrupts, direction**: **inflates** the turn arm, **deflates** the clause arm. Corrupts
  "subject-bearing 8 (4.7%) vs 71 (37.2%)" and "content-free 59.1% vs 32.8%". The direction of the
  conclusion may still be right; the magnitude is unsupported.
- **Aggravating**: CLAUDE.md already records the *same* length confound in the null test
  (`corr(lift, mean word count) = +0.65`). Both instruments used to argue the pool-unit case are
  confounded by one variable, and were treated as independent corroboration.
- **Confidence**: certain. **Verify**: recompute over the two shipped artifacts; no run needed.

### 6. `extract_pairs` discards every CLIENT turn in a block except the last — and the whole block if the last is filler

- **File:line**: `v1/layer_b.py:51-70` (`else: break` at `:59-60`, `i = j if response_parts else i+1`)
- **What is wrong**: the inner loop breaks on the first turn that is neither NAREN nor JOVEO_OTHER —
  i.e. the next CLIENT turn. For `[C1, C2, NAREN]`, C1 breaks with `response_parts == []` and is
  dropped. Worse, for `[C1(substantive), C2("Yeah."), NAREN(substantive)]` the block yields **zero
  pairs** — both the real client question and Naren's substantive answer are lost. Nothing counts it.
- **Corrupts, direction**: deflates `kb_pairs` (the input population for Layer B, Layer C's clause
  pool, and every rubric) and — more damagingly — **systematically biases `trigger_text` toward the
  last fragment of each client speech block**, the fragment most likely to be a trailing "so yeah,
  anyway". Layer B's sink decision is made on `trigger_text` alone, so this **inflates sink-filing**.
- **Same defect class as the Layer D segmentation artifact, one layer earlier, never diagnosed for
  Layer B.** Measured there: 43% of client turns are immediately followed by another CLIENT turn. A
  plausible mechanical cause of the 39.7–45.8% sink absorption that eight signal shapes and four
  design docs searched for a *scoring* explanation for.
- **Confidence**: certain (mechanism, traced line by line); likely (magnitude — inferred from the
  CSM corpus, not measured on `recordings/`).
- **Verify**: free, no DB — count client turns whose next turn is also CLIENT, compare to
  `len(extract_pairs(turns, 0))` per file.

### 7. `sink_routing_balanced_acc` is a constant 0.500 for bge by construction — and it flips the embedder verdict to PASS

- **File:line**: `calibration/compare_embedders.py:147`, `:60`, `:303-305`; ground truth built by
  `label_trigger_quality_sample.py:69-79` (`WHERE s.is_coachable = false`).
- **What is wrong**: the 150-pair labelled sample is drawn **exclusively from pairs production
  already filed to a sink**, and production files to a sink precisely when the bge top-1 match is a
  sink. `top_is_real` is therefore False for all 150 bge rows by definition of the sample.
  `embedder_compare_v2.json` confirms: `bge_768.sink_routing_kept_frac = 0.0`, `balanced_acc = 0.5`
  — an all-negative constant predictor. Gemini is not selected on its own decision boundary, so it
  varies freely (0.587–0.613). Items 5 and 1 at once.
- **Corrupts, direction**: **the headline verdict**. gemini_768 = margin +0.125 ✓, coupling −0.048 ✗,
  routing +0.113 ✓ → **2/3 = PASS**, same at 1536 and 3072. The shipped harness prints **PASS for
  every width**, against CLAUDE.md's "1 of 3 — DOES NOT PASS". The flip is carried entirely by a
  criterion whose baseline cannot be anything but 0.5.
- **Confidence**: certain.

### 8. The coverage-judge result is rep-1-only, and its sign reverses in rep 2 of the same run

- **File:line**: `calibration/trial_layer_c_arms.py:337-338`, `:423-426`
- **What is wrong**: `_summarise_reps` builds the published dict as `dict(reps[0]["matched"],
  w=_mean(...))`. Only `w` is replaced by the across-rep mean; `attempts`, `counts`,
  `w_conditional` and `not_called_for_rate` all come from **rep 1 alone**. `_report` prints them on
  one line as if from one estimator (item 7).
- **Corrupts, direction**: the `not_called_for` comparison CLAUDE.md cites as the second,
  independent failure of "did this moment call for this move". Verified in
  `artifacts/trial_t3_coverage.json`: rep 1 = 0.6486 matched / 0.6571 unrelated (the published
  claim); **rep 2 = 0.6689 / 0.6000 — matched higher by 6.9pt.** The 2-rep mean is 0.659 vs 0.629,
  the opposite of what was published.
- **Confidence**: certain (both reps are stored).

### 9. `flat_pick` and `topk_pick` apply the cap to different populations, the test guarding it is vacuous, and production inlines its own copy

*Found independently by three auditors (W1-T3, W3-P1, W3-P3).*

- **File:line**: `shared/relative_match.py:81-89` vs `:108-116`; production inline copy at
  `v1/layer_b.py:127-144`; vacuous guard at `tests/test_relative_match.py:149`.
- **What is wrong**: `flat_pick` takes `order[:cap]` **first** and discards sinks after, so a sink at
  rank 2 consumes a slot and evicts a qualifying real match. `topk_pick` filters sinks first, then
  slices. Worked example at `cap=3, margin=0.95`: `sims=[realA 0.90, sink 0.89, sink 0.88, realB
  0.87]` → `flat_pick` returns `[realA]`, `topk_pick` returns `[realA, realB]`. **76 of 161 live
  scenarios (47%) are sinks**, so this is routine. The equivalence test passes
  `is_sink=[False,False,False]` — the one case where they cannot differ.
- **Corrupts, direction**: **deflates** `kb_pairs.scenario_keys[]` width — the published
  "63% / 19% / 18%" is biased toward "one", a *second* narrowing beyond the documented sink
  short-circuit. **Deflates** `get_responses_for_scenario_multilabel`'s pool (Layer D benchmarks).
  And item 1 in the harnesses: `topk_pick` is what Layer D, all three two-stage strategies, and
  `compare_matching_subset.py` use — so the two-stage-vs-flat comparison had a **second
  uncontrolled variable**, favouring the two-stage arms.
- **Trap for the fix**: production does not call the shared helper. Fixing `shared/relative_match.py`
  would satisfy the tests, move every harness, and **leave production unchanged**.
- **Confidence**: certain (divergence + vacuous test); likely (production magnitude).
- **Verify**: zero cost — add a sink to the existing equivalence test's `is_sink` list.

### 10. 45.8% of client turns are structurally unscoreable, and 98.7% of `Signal_Recognition_Failure` is the segmenter

- **File:line**: `ego_trap/transcript_parser.py:78-89`, `:92-104`; consumed at `signal_check.py:240`, `:339`
- **What is wrong**: `turns_until_next_client` breaks on the first CLIENT turn, so when the next turn
  is itself CLIENT the window is `[]` and `classify_response_outcome` returns `"none"` **before any
  evidence is consulted**. No counter, no warning distinguishing it from real silence.
- **Measured over 6,468 CLIENT turns / 106 transcripts**: `csm` 2,351 / `other_joveo` 1,117 /
  `none` **3,000**. Of the 3,000, **2,962 (98.7%) are immediately followed by another CLIENT turn**,
  38 are last-turn-of-call, **0 are genuine silence**.
- **Corrupts, direction**: `signal_recognition_gaps.missed` **inflated by ~98.7% of its mass**; the
  `39/61 (64%) missed` in `RUN_NOTES.md:34` is this artifact. **Second consequence not previously
  recorded**: only a client turn *last in its contiguous block* can reach `outcome == "csm"`, so
  **45.8% of client turns can never be scored at all**. Direction measured rather than assumed —
  excluded turns are shorter (median 17 vs 25 words), so the bias is mild and runs toward excluding
  filler, but `attempts` is drawn from a non-random half of the corpus.
- **Confidence**: certain.

### 11. `merged` was split out of the outcome enum but is still pooled into the support-thickening statistic — reversing its sign

- **File:line**: `calibration/replay_layer_c_admitted.py:354-357`, reported `:374-377`, printed `:403-409`
- **What is wrong**: `_match_milestones` correctly emits four outcomes, but `_summarise_arm` collects
  `support_frac_deltas` for `o["outcome"] in ("matched", "merged")` — a two-way collapse. A `merged`
  row's support is by construction that of a cluster which absorbed 2+ baseline milestones, so it is
  guaranteed larger.
- **Recomputed**: `by_cluster` matched n=375 mean **+0.0007**, merged n=8 mean **+0.4587**;
  `by_trigger_nonsink` matched n=172 mean **−0.0170** against a printed arm mean of **+0.113**.
- **Corrupts, direction**: **inflates** `support_thickened` and the mean. The published `by_cluster`
  "+0.0102" is *entirely* the 8 merges — the 375 genuinely matched milestones move by nothing. In
  `by_trigger_nonsink` the pooling **reverses the sign**.
- **Confidence**: certain (recomputed).

### 12. The ship/hold/disable thresholds are fitted to the ceiling table CLAUDE.md retracted, and the gate that writes to the DB replays it

- **File:line**: `tests/test_rubric_validation.py:165-171`; constants `shared/rubric_validation.py:155-156`,
  duplicated `calibration/validate_rubrics.py:102-103`; `_self_check` at `:345-391`, gating `--apply`
  writes at `:794-806`.
- **What is wrong**: the test asserts `SCENARIO_MIN_ATTEMPTS == 15` and `SCENARIO_BAND == 0.05` and
  states they reproduce "the ceiling run's published table exactly". Those values were **fitted** to
  a table whose arm B is now recorded as an arm-construction artifact — while
  `validate_rubrics._items_for` deliberately **fixed** that asymmetry ("All three arms use THE SAME
  A3 responses"). So `classify_scenario` runs a symmetric comparison through a band fitted on an
  asymmetric one.
- **Corrupts, direction**: with a symmetric arm B the null drops (leakage-clean `W(unrelated)` is
  0.032–0.042 vs the ceiling's 0.090), so `gap` is systematically **larger** than the population the
  band was fitted on: **SHIP inflated, DISABLE deflated.** `_self_check` — the gate deciding whether
  verdicts are written to `rubrics.milestones` — replays `artifacts/naren_ceiling.json`, i.e. its
  validity proof is "does the symmetric measurement reproduce the asymmetric one's labels". It has
  **no test at all**.
- **Aggravating**: `classify_scenario` also ships on `control_is_zero` with **no minimum effect
  size** — one partial hit in 48 attempts bypasses the ±0.05 band.
- **Confidence**: certain (fitting + arm mismatch); likely (direction and magnitude of SHIP inflation).

### 13. "Baseline reproduced at 1.30 / 1.30 / 1.21 across three runs" is three re-scorings of the same 8 alphabetical scenarios

- **File:line**: `calibration/trial_layer_c_arms.py:329-336`, `:413`
- **What is wrong**: `_spread` measures **scoring replication on a fixed item set** and nothing else,
  yet `:413` offers it as the significance yardstick ("An arm difference smaller than the replication
  spread is NOT a result"). `trial_t1/t2/t3` all carry the identical 8-key list
  (`ai_capability_discovery` … `budget_and_performance_strategy_optimization`, **0 posture
  scenarios**) — the documented `--limit 8` alphabetical bias. `trial_final` uses 18 stratified
  scenarios and the same `arm0_baseline` returns **1.580**.
- **Corrupts, direction**: the claimed ±0.002–0.018 stability **understates real uncertainty by
  ~20×** — changing the sample moved the same arm by 0.37. Arm-vs-arm deltas *within* one run share
  the sample and survive; quoting 1.30 as "the baseline", or 0.02 as a cross-run bar, does not.
- **Confidence**: certain (verified from the `clustered` lists in four artifacts).

### 14. Ceiling arm B is 57% scored by a different model than arms A1 and A3, and nothing gates on it

- **File:line**: `calibration/score_naren_ceiling.py:435-438`; `ego_trap/milestone_scoring.py:40-41, 318-323`
- **What is wrong**: `_score_arm` calls `score_milestones_batch` without pinning a model, so the
  fallback chain is live and each arm silently escalates under rate limits. `milestone_scoring`
  documents the fix (`fallback_models=()` pins hard while keeping key rotation); the ceiling does not
  use it. `_report` prints the `scored_by` counter with the correct warning but there is **no gate**.
- **Corrupts, direction**: `W(B)` — the null in the headline claim. `artifacts/naren_ceiling.json`:
  A1 `{gemini-3.1: 1834}`, A3 `{gemini-3.1: 1806}`, **B `{gemini-3.1: 793, gemini-3.5: 1040}`**. The
  control is the only model-blended arm, 57% a model neither treatment arm saw. Direction not
  determinable from the artifact — which is the point: the most load-bearing number in the project
  has an uncontrolled variable sitting **only in its null**. This is a *third* asymmetry in an arm
  pair already retracted for a population asymmetry. The "0.090 same-model subset" quoted in
  CLAUDE.md is **not produced by this script at all**; it prints 0.071.
- **Confidence**: certain.

### 15. Every "% of turns" in the Gemini adjudication chain excludes HDBSCAN noise and triage drops — inflating each share ~1.9×

- **File:line**: `calibration/aggregate_cluster_verdicts.py:71`, used `:79-80`, `:94`, `:132-134`
- **What is wrong**: `tot_turns` is 12,582 — turns surviving both HDBSCAN (noise share 0.435) and the
  `INSUFFICIENT_EVIDENCE` triage drop. The real pool is **23,949**, which the script never prints.
  Unlabelled shares of a 52.5% subset (item 2).
- **Corrupts, direction**: **inflates every turn-share ~1.9×**. "Retention 41.0% of turns" is
  **21.5%** of corpus. "Coachable turn volume 35.1%" is **18.5%**. "35.1% vs 31.0%" also compares two
  different denominators (12,582 vs 12,000).
- **Confidence**: certain.

**Immediately below the top 15**, and each carrying a live consequence: `graduate_sink_topics._graduate_one`
**commits a partial reroute before the rowcount check** (its auto-pass sibling does not — W1);
`test_ego_trap_signal_check.py`'s tuning fixture is stale by two fields so **14 tests cannot run**,
leaving the rule that sets `attempts` unguarded (W1); Layer A's adjudication **fails open to
coachable** on any unrecognised decision with no counter (W3); `compare_criteria_ab.py` scores a
milestone present in only one arm as `0.0`, so ~99 attempts the baseline lost to Gemma failures
count as **improvements** (W2/W4); and the noise floor's movement-rate denominator includes
milestones never attempted in one run (W2).

---

## CROSS-AGENT CORROBORATION

Independent agents reaching the same conclusion from different directions. These are the
highest-confidence items in the report.

| finding | reached by | from |
| --- | --- | --- |
| `flat_pick`/`topk_pick` cap divergence + vacuous guard | **3 agents** — W1-T3, W3-P1, W3-P3 | the test, the shared helper, the layer |
| the segmenter's `len(sent) < 4` cutoff is unpinned by its tests | **2 agents** — W1-T2, W1-T5 | token counts in `test_segmenter.py`; token counts in the Layer C fixtures |
| the content-free / length confound in the pool-unit instruments | **2 agents** — W2-C1, W4-PROV | length-binned recomputation; `corr(words, thin)` |
| the `kind == "scenario"` enum collapse | **2 agents** — W2-C4, W2-C5 | the replay's outcome enum; the adjudication cross-tab |
| the Layer D segmentation artifact | **2 corpora** — CLAUDE.md's 98.6%, W3-P2's 98.7% | 5,731 turns; 6,468 turns |
| `layer_d.scoring_unit` is a declared key with no consumer | **2 agents** — W1-T1, W1-T4 | the call-scoring docstring; the shipped-tuning test |

**Not corroboration, corrected:** `usable_item_fraction` was reported by two agents (W1-T6, W2-C3)
but is a **single-input finding** — it recurs against CLAUDE.md's prescription, not against a second
independent measurement. Both agents computed the same 0.973 from the same test literals.

---

## CONFLICTS BETWEEN AGENTS

Recorded, not resolved. Both sides verified their own arithmetic.

### 1. Head-to-head control C1 — is the pooled 0.669 the right statistic? *(RESOLVED in favour of C3)*

- **W2-C3**: pooled C1 reproduces at **0.669** with Wilson **[0.612, 0.721]**, entirely below the
  0.75 bar. The FAIL is robust.
- **W4-PROV**: pooling is the **wrong operation** — it pools C2, whose own docstring says a coin
  flip is the correct answer. Per stage: **c2 0.570, c3 0.581, c4 0.847**. On C4, the stage that
  produced the fatal result, the judge *clears* the bar. `swap_agreement` also charges
  one-decisive-one-tie as a reversal (flip rate 0.201, tie-mismatch 0.130); reversal-only gives
  signal share **0.60**, not 0.34.
- **Resolution**: the Wave 2 consolidation, seeing both, concluded C1 **survives robustly** — but
  note it survives on the *pooled* statistic that PROV disputes. **What would settle it**: report
  C1 per stage with intervals, and decide explicitly whether C2's coin-flip stage belongs in a
  judge-reliability pool. The published "signal share 0.34" should be treated as unsupported
  regardless of which side wins.

### 2. The segmenter's 4-token cutoff — clean or unpinned?

- **W1-T4** recorded it as CLEAN.
- **W1-T2 and W1-T5** each **measured** it unpinned, from different fixtures: T2 found the cutoff
  can rise to 13 with the suite green; T5 found fixture token counts of 8/7/6/7, so any cutoff from
  1 to 6 leaves every assertion green.
- **What would settle it**: trivially, two measurements from different files beat one assertion —
  but the disagreement is recorded because T4's CLEAN entry would otherwise stop the next auditor
  re-checking it.

### 3. Scope-induced error in `PART3`'s "what was not audited" *(corrected below)*

`PART3-WAVE34.md` was given only the W3/W4 inputs, so it reports that **no test file was audited**
and that `score_naren_ceiling.py` "is the notable gap — no auditor opened it". Both are false:
Wave 1 audited 34 test files and Wave 2 audited `score_naren_ceiling.py`. Its 27-file calibration
skip list likewise includes 13 files Wave 2 covered. **Use the corrected inventory below, not that
section.** The error itself is a clean instance of the audit's own lesson: a report is only as wide
as the inputs it was handed, and it will state a confident negative about everything outside them.

---

## VERDICTS THAT MOVE

From the Wave 2 consolidation: **9 flip, 9 weaken, 6 survive.** Headlines:

| published verdict | now |
| --- | --- |
| embedder comparison "1 of 3 criteria — DOES NOT PASS" | **FLIPS to PASS at every width** (top #7) |
| coverage judge "not_called_for failed twice" | **FLIPS** — rep 2 reverses the sign (top #8) |
| "finer granularity is BETTER: min 16 beats min 50" | **FLIPS to null** — coherence z=1.73, coachability z=0.75 |
| "3072 beats 768 for clustering" | **WEAKENS** — at matched cluster counts 768 leads at the coarse end |
| pool unit "8 (4.7%) vs 71 (37.2%)" | **WEAKENS** — magnitude unsupported, direction may hold |
| "by_cluster is the least damaging by a wide margin" | **WEAKENS** — placebo perturbs calls 2.3× harder in that arm |
| ceiling "signal-to-null 1.2:1" (already retracted) | **WEAKENS further** — a third asymmetry (model) |
| head-to-head C1 "0.669 FAIL" | **SURVIVES** (pooled; see conflict 1) |
| head-to-head C4 "0.835" | **SURVIVES as a number**, weakens as a verdict — Wilson [0.742, 0.899] straddles its bar |
| skills "no window at any bound" | **SURVIVES** — every defect found pushes toward PASS |
| grader-inputs retraction of 1.2:1 | **SURVIVES** — reproduced exactly, well-founded |

---

## OPEN PROBLEMS THESE FINDINGS MAY EXPLAIN

Each pairs a question CLAUDE.md records as open and never root-caused with the finding that may
explain it. **Certain code fact and speculative magnitude are kept separate — do not upgrade.**

| open problem | candidate cause | strength |
| --- | --- | --- |
| the ~3% hit rate / `W(matched)` 0.089–0.095 that survived three fixes | **top #4** mixed CSM/teammate windows; plus empty-description milestones, the biased scored population (#10), and failed batches marked done | mechanism certain, rates **measured**; share of the ~3% unquantified |
| the 39.7–45.8% Layer B sink absorption | **top #6** `extract_pairs` drops all but the last client turn of a block | mechanism **certain**; magnitude likely (inferred from the CSM corpus) |
| "Layer C's relevance filter barely discriminates by topic" | **top #3** the filter is a 60% quota | **certain, and mechanically explanatory** — the strongest link in the audit |
| the unexplained 78-vs-85 coachable drift | Layer A adjudication fails open to coachable | certain code fact, **speculative** as the cause; the ordering-cascade hypothesis remains live |
| 47.3% HDBSCAN noise in the sink pool | `min_cluster_size_ceiling` freezes granularity at a hardcoded 25 | certain, and the recorded `0.02 × 3730 = 74.6 → 25` clamp confirms it bound on that exact run |

**Newly explained, not previously on any list:** the "234 of 235 milestones labelled `fixed`, the
conditional trigger fires 0 of 226" result is `_sequence_milestones`'s substring test requiring a
Gemma paraphrase to literally quote the transcript — the field records "the substring test failed",
not "this move has no ordering variance". And the auto-pass consensus counter **cannot advance on an
unchanged corpus**, because its guard keys on `run_id`, a hash of transcript stems.

---

## PROVENANCE OF PUBLISHED NUMBERS

17 numbers where a knob shipped, an approach was declared CLOSED, or a wall was declared standing.
**5 SUPPORTED · 9 OVERSTATED · 1 CONTRADICTED · 2 UNVERIFIABLE.** Full table with reasons in
`PART3-WAVE34.md`.

**CONTRADICTED (1):**
- **"~350+ calls for a median of 25 observations per milestone."** Produced by no script — it is
  prose arithmetic, exactly `100 × 25/7`, the **linear extrapolation the same paragraph forbids**.
  Fitting the measured sub-linear exponent (per-milestone ∝ calls^0.64) gives **≈750**. This is
  load-bearing: `OPEN_PROBLEMS.md:699` raises feasibility against 107 available CSM transcripts, and
  at ~750 the answer changes from "hard" to "not obtainable".

**UNVERIFIABLE FROM CODE (2):**
- **The noise floor "±0.006, 15.6% of milestones move".** The script's own docstring attributes
  15.6% to the **contaminated blended-runs comparison its duplicate guard now refuses to make**, and
  `grep -r "MOVEMENT RATE" Brain/logs/` returns nothing — **no run was ever captured.** Every Layer D
  A/B verdict is graded against this.
- **"17 of 405 unhittable: 74 attempts, 0 hits, 12 milestones".** `ops/flag_uncoachable_milestones.py`
  queries `rubrics` only and never touches `milestone_performance`. 17 flagged, only 12 have any
  attempts. If "0 hits" means 0 *full* hits, at a ~3% full-hit rate P(0 in 74) ≈ 0.10 — not proof.

**SUPPORTED (5), reproduced exactly:** C4 = 0.835 (byte-matching `logs/h2h_m5.log`); the
grader-inputs numbers and p-values, confirming **the retraction of 1.2:1 is well-founded**; skills'
78% one-off rate (315/405, 342 distinct — every figure in the three-attempt table matches to the
decimal); the retrieval gate 0.812 vs 0.631 with point estimate and CI from the same estimator; and
"person language 100% → 3%", where the regex is applied identically to both arms and the measured
drop is if anything conservative.

**Also OVERSTATED and worth knowing:** the derived rule "below ~+0.02 weighted is unmeasurable" —
±0.006 is the range of **two observations**, i.e. one difference; it estimates σ, not a 95% interval
(~±0.015). And `percentile: 40` "calibrated" — 40 is the **lowest value in its own search grid**
`[40, 60, 75]`, selected by an objective that counts over-filtering only and is minimised by
filtering less. The grid never brackets a minimum.

---

## CLEAN CATEGORIES

A verified-clean category is what stops the next audit re-checking the same ground. Grouped by
taxonomy item. **Measured** means the auditor computed it, not that they read the code and inferred.

**Item 4 — name that never matches: CLEAN across production.** Every enum literal, prompt field, DB
value and `::`-joined id in `shared/storage.py`, `relative_match.py`, `cluster_evidence.py`,
`scenario_vectors.py`, `tuning.py`, `v1/layer_b.py`, `v2/layer_a.py`, `v2/layer_c.py` and
`response_taxonomy_auto_pass.py` was checked against its definition. Verdict strings, bloom levels,
cluster kinds, rubric statuses, the three adjudication decision literals, and the
`sub_topic`→`business_description` rename all match. The known instance is confined to
**test fixtures** (`verify_evidence`'s invented `"CSM"` vocabulary) and to `ego_trap/call_scoring.py`.

**Item 3 — numbering / base: CLEAN end to end.** `Turn.index` is 0-based and stored verbatim; the
positional `milestone_id` convention holds at every storage/display/model boundary; `cluster_id` is
0-based with 245/245 and 76/76 coverage and no duplicates.

**Embedding discipline: CLEAN, repo-wide.** Every `embed_query` / `embed_document` prefix pairing is
consistent; the `_matrix` and list variants are one code path; the gateway's one-vector-per-request
discipline is airtight (every `/embeddings` path count-checked, **no `zip` anywhere that could
truncate**); the cache is correctly keyed on model + **native** width + text, avoiding the
Matryoshka trap.

**MEASURED clean — the speaker fail-open is not currently firing.** 254 of 254 `@joveo.com` speaker
slots covered across 103 sidecars, **0 falling through to CLIENT**, and 13,222 of 13,222 Naren
speaker lines are exact string matches. The roster backfill work held.

**MEASURED clean — the production-parity mistakes do not reproduce.** Both pool-unit harnesses call
`build_client_pool` with the **undisabled** production segmenter and pass `load_roster(...)`.
`min_cluster_size` **is** correctly scale-matched between the two headline artifacts (50/73,771 vs
16/23,949); the unmatched arm is the one already withdrawn. The lesson stuck.

**Other verified-clean:** `tuning.py` raises on both unknown *and* missing keys, with no dataclass
field defaulting silently; `get_scenarios` selects `is_coachable`/`cluster_kind`, takes no filter,
and is complete for the resume path; the scalar and multilabel response queries have not drifted;
`_reconcile` genuinely raises rather than warns; no DB calls crept into the Layer A Gemma loop;
auto-pass graduation genuinely reads `stable_pair_ids` and `match_existing_primary_topic` genuinely
uses the tight threshold; the `merged` fix in `_match_milestones` is correct and its consistency
check reproduces exactly (172+83=255, 172+92=264, 375+8=383); support **is** normalised per arm
wherever a rate is printed; the blind judges are properly blinded; `bootstrap_lift`'s point estimate
and CI are the same estimator with no discarded resamples; model provenance **is** recorded per
verdict and per artifact; the log-file contamination risk in `test_response_taxonomy_auto_pass.py`
is covered by an `autouse` fixture; and `tests/test_topic_grouping.py` is the strongest file in the
suite — every test a partition property with thresholds passed in, no frozen counts.

---

## WHAT WAS NOT AUDITED

Corrected against all four waves. **58 of 136 Python files under `Brain/` have never been audited.**

| directory | total | audited | left |
| --- | --- | --- | --- |
| `calibration/` | 42 | 27 | **15** |
| `ops/` | 13 | 2 | **11** |
| `shared/` | 18 | 5 | **13** |
| `ego_trap/` | 10 | 6 | 4 |
| `v1/` | 5 | 1 | 4 |
| `v2/` | 5 | 2 | 3 |
| repo root | 4 | 1 | 3 |
| `preprocessing/` | 4 | 3 | 1 |
| `tests/` | 35 | 34 | 1 (`__init__.py`) |

**`calibration/` not audited (15):** `analyze_combined_signal.py`, `analyze_turn_position.py`,
`compare_matching_subset.py`, `compare_sink_rescue.py`, `dry_run_ego_trap.py`, `dry_run_layer_a.py`,
`dry_run_layer_c_clustering.py`, `dry_run_response_taxonomy.py`, `graduate_sink_topics.py`,
`label_trigger_quality_sample.py`, `read_gap_reasons.py`, `translate_thresholds.py`,
`trial_client_move_arms.py`, `validate_rubrics.py`, `__init__.py`.
These were **deliberately skipped** as backing closed or withdrawn conclusions. Two are riskier than
that rationale implies: **`graduate_sink_topics.py` wrote to production** (4 scenarios, 164 pairs)
and Wave 1 found a commit-before-rowcount-check bug in it from the test side only; and
**`label_trigger_quality_sample.py`** builds the labelled sample whose `WHERE is_coachable = false`
predicate causes top finding #7.

**`shared/` not audited (13):** `checkpoint.py`, `embed_cache.py`, `gemma.py`, `pinecone_store.py`,
`rubric_validation.py`, `skills.py`, `coverage_areas.py`, `trigger_quality.py`, `topic_grouping.py`,
`response_taxonomy.py`, `prompts.py`, `head_to_head.py`, `relative_match.py`'s siblings. Several
were *read as supporting evidence* by an auditor but not audited in their own right.

**`ops/` — 11 of 13 never audited, the largest untouched surface by risk.** Includes
`clear_data.py` and `clear_ego_trap_data.py`, which wipe live Postgres and have no `__main__` guard,
plus `backfill_*.py`, `check_csm_speakers.py`, `derive_joveo_roster.py`, `fetch_avoma_recordings.py`,
`rerun_layer_c.py`, `run_ego_trap.py`, and all five `.ps1` run recipes. Audited: only
`flag_uncoachable_milestones.py` and `rewrite_milestone_criteria.py`, both via Wave 4.

**Also untouched:** `v1/layer_a.py`, `v1/layer_c.py`, `v1/pipeline.py`, `v2/pipeline.py`,
`ego_trap/csm_registry.py`, `ego_trap/scenario_pool.py`, `config.py`, `main.py`,
`run_v2_subset.py`, `db/init_db.py`. Every file in `Brain/artifacts/` and `Brain/logs/` other than
the ~10 read for cross-checking is unread.

**Excluded as already audited on 2026-08-15 (8):** `ego_trap/call_scoring.py`,
`ego_trap/milestone_scoring.py`, `calibration/trial_call_scoring.py`, `trial_grader_inputs.py`,
`null_test_taxonomy.py`, `audit_null_instrument.py`, `flag_proper_noun_clusters.py`,
`diagnose_rubric_level.py`. Three of these were re-read by Wave 4 for provenance, so they have two
passes.

---

## CLAUDE.md CORRECTIONS

Every published claim these findings contradict or weaken. **This is a checklist, not an edit** —
CLAUDE.md was not modified.

| claim as published | undermined by | suggested correction |
| --- | --- | --- |
| "Gemma over-sinks 14.6%" was retracted | top #1 | Add: the retraction is **prose only** — `aggregate_cluster_verdicts.py:83` still computes it and the artifact still stores it. |
| sink pool "genuine_sink 2/609, belongs_to_existing 5/199, new_coachable 2/175"; homeless topics "94 pairs/115 calls" and "81/113" | top #2 | Call counts are **union** counts; sink-only ceilings are 94 and 81. Verdicts biased away from `genuine_sink`. The 4 graduated scenarios rest on this. |
| "Layer C's relevance filter barely discriminates by topic" | top #3 | Not "barely" — a percentile over the filtered population is a **fixed 60% quota** and cannot discriminate at all. |
| "the criteria are unpassable even by their own author" (`W(matched)` 0.089–0.095) | top #4 | Add mixed CSM/teammate windows as a measured contributor: 17.4% of scored windows, 16.3% with ≤5 CSM words. |
| pool unit "8 (4.7%) vs 71 (37.2%) subject-bearing"; "content-free 59.1% vs 32.8%" | top #5 | The proxy is length-dependent and unit-dependent; length-binned, the arms are indistinguishable. Direction may hold, magnitude unsupported. |
| "the embedding-signal search is closed"; sink absorption unexplained after eight signal shapes | top #6 | Add `extract_pairs`'s consecutive-client-turn drop as a mechanical candidate never tested. |
| embedder comparison "1 of 3 — DOES NOT PASS" | top #7 | The routing criterion is tautologically 0.500 for bge; the shipped rule prints **PASS at every width**. |
| "'did this moment call for this move' has failed TWICE" | top #8 | The second failure is rep-1-only and reverses in rep 2. Treat as **one** failure. |
| production match width "63% / 19% / 18%" | top #9 | Biased toward "one" by the cap-ordering divergence, independently of the sink short-circuit. |
| "36% of gap_events are Signal_Recognition_Failure" (already retired) | top #10 | Add the **second** consequence: 45.8% of client turns are structurally unscoreable, so `attempts` covers a non-random half of the corpus. |
| replay "by_cluster … support jumps read as evidence thickening" | top #11 | The thickening is entirely the 8 merges; genuinely matched milestones move +0.0007. Sign reverses in `by_trigger_nonsink`. |
| "corpus-level is stable — 1.30/1.30/1.21, spread ±0.002–0.018" | top #13 | Three re-scorings of the same 8 alphabetical scenarios; stratified gives 1.58. Understates uncertainty ~20×. |
| ceiling arm B and the "0.090 same-model subset" | top #14 | Arm B is 57% a different model, ungated; 0.090 is not produced by that script, which prints 0.071. |
| gemini chain "retention 41.0% of turns", "coachable turn volume 35.1%" | top #15 | Denominator excludes noise and triage drops: **21.5%** and **18.5%** of corpus. |
| "finer granularity is BETTER: min 16 beats min 50" | W2-A11 | Null result — z=1.73 and z=0.75, before accounting for the arms partitioning one corpus. |
| "3072 beats 768 for clustering" | W2-A18 | Compared at equal merge threshold, not equal cluster count; at matched counts 768 leads at the coarse end. |
| "~350+ calls for a median of 25" | W4 #5 | ≈**750**, fitting the measured sub-linear exponent. Not obtainable from 107 transcripts. |
| noise floor "±0.006, 15.6% move"; "below +0.02 is unmeasurable" | W4 #6, #7 | No run was ever logged; the figure traces to the contaminated comparison the script now refuses. ±0.006 is the range of two observations. |
| skills "best validity 0.667 vs the 0.80 bar" | W4 #8 | n ≈ 3–9; 0.667 is **not statistically distinguishable** from the bar. The closure rests on the n=5, V=0.20 point. |
| Layer C "calibrated to percentile 40 / fraction 0.10" | W4 #10 | 40 is the lowest value in its own grid, chosen by an objective minimised by filtering less. The grid never brackets a minimum. |
| "top1−top2 margin ~0.01 in BOTH taxonomies" | W4 #11 | Measured to the runner-up anywhere, not across the sink/non-sink boundary the decision turns on. |
| "17 of 405 unhittable: 74 attempts, 0 hits" | W4 #12 | Computed by no script; 5 of 17 have zero attempts; P(0 in 74) ≈ 0.10 at a 3% rate. |
| `usable_item_fraction` is the fix for the median's blind spot | W1-C7 / W2-T8 | It scores the mega-blob at **0.973** and the healthy case at 0.976. It is also dead code. |
| `layer_d.scoring_unit` gates call-level scoring | W1-T1, W1-T4 | Read by nothing. Setting it to `call` changes nothing. |
| `describe_mode: coverage` | W3-T8 | No `coverage` branch exists; setting it silently runs legacy and reports under the coverage label. |

---

## METHOD NOTE

The audit's own structure produced one error worth recording, because it is the same failure class
it was hunting. `PART3-WAVE34.md` was handed four of the fifteen input reports and, asked what had
not been audited, confidently stated that no test file was audited and that `score_naren_ceiling.py`
was untouched — both false, and both unfalsifiable from inside its own scope. A measurement is only
as wide as the population it was given, and it will report a confident negative about everything
outside it. That is taxonomy item 2, committed by the audit rather than found by it.
