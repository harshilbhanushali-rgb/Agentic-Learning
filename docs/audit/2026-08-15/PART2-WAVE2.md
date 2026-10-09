# Wave 2 — the calibration harnesses

Covers the 24 files under `Brain/calibration/` audited by C1-C5: the Layer A pool-unit trials
(`trial_pool_unit.py`, `trial_pool_unit_gemini.py`, `scenario_coherence.py`,
`spot_check_adjudication.py`, `validate_taxonomy_vs_layerd.py`); the ceiling / noise-floor /
criteria-A/B / four-arm cluster (`score_naren_ceiling.py`, `measure_scoring_noise.py`,
`compare_criteria_ab.py`, `trial_layer_c_arms.py`); head-to-head, skills and embedder
(`trial_head_to_head.py`, `probe_retrieval_gate.py`, `trial_skills.py`, `compare_embedders.py`);
the sink-pool diagnostic and Layer C replay (`diagnose_sink_pool.py`,
`replay_layer_c_admitted.py`, `check_milestone_thickening.py`); and the Gemini gateway /
blind-judge chain (`trial_gateway.py`, `trial_adjudicate_gemini.py`,
`export_cluster_batches.py`, `aggregate_cluster_verdicts.py`).

**69 findings.** 60 labelled **certain**, 4 **likely**, 1 **certain-on-the-code / speculative-on-
occurrence**, plus 4 flagged MINOR by C2. Several auditors wrote free recomputations against the
persisted artifacts; those recomputed figures are preserved verbatim throughout.

---

## CANDIDATE TOP FINDINGS

### T1. The `kind == "scenario"` enum collapse is STILL LIVE in code and in the shipped artifact — the retraction exists only in CLAUDE.md prose

- **File:line**: `Brain/calibration/aggregate_cluster_verdicts.py:83`
  (`g_coach = {i: rows[i]["kind"] == "scenario" ...}`), consumed at `:85-97` and `:115`; stale
  output at `Brain/artifacts/cluster_verdict_summary.json`. Producer is four-valued:
  `trial_adjudicate_gemini.py:301-304` (`scenario` / `mechanics` / `logistics` / **`merged`**), and
  `merged` means RETAINED (`v2/layer_a.py:504-529` folds a `merge_into` cluster into its target).
- **What is wrong**: nothing was corrected after the retraction. Re-running the script today
  reproduces the withdrawn finding verbatim, including the printed lines
  `"Gemma sank it, judge says COACHABLE: 56 (Gemma may be over-sinking)"` and
  `"-> 1831 turns (14.6%) the judge would keep"`. There is no cross-tab anywhere in the file — the
  fix the incident's own lesson demanded ("print the full cross-tab instead of a boolean") was
  never applied. `flag_proper_noun_clusters.py:164` does print a 4-way cross-tab; this file does not.
- **What number it corrupts, and in WHICH DIRECTION**: judge-vs-Gemma agreement is **deflated**
  76.3% → true **93.9%** at min 16 (84.2% → **96.1%** at min 50); the "Gemma over-sinks" count is
  **inflated** from 0 to 56 clusters / 1,831 turns / 14.6% of the clustered pool; the disagreement's
  direction is inverted (true: 15 clusters Gemma kept that judges would drop, 0 the other way).
  Verified cross-tab at min 16: scenario 36 yes / 2 no; **merged 56 yes / 13 no**;
  mechanics 0 yes / 129 no; logistics 0 yes / 9 no.
- **Confidence**: certain (computed directly from the artifacts).
- **Cheapest way to verify**: `grep -n 'kind"\] == "scenario"' calibration/aggregate_cluster_verdicts.py`
  and `cat artifacts/cluster_verdict_summary.json` — both still show the collapsed form.

### T2. `sink_routing_balanced_acc` is a constant 0.500 for bge BY CONSTRUCTION, and it flips the embedder verdict from DOES NOT PASS to PASS at every width

- **File:line**: `Brain/calibration/compare_embedders.py:147` (`top_is_real = ...`), `:60` (`_SAMPLE`),
  `:303-305` (`_CRITERIA`); ground truth built by
  `Brain/calibration/label_trigger_quality_sample.py:69-79` (`_load_sink_bound_pairs`,
  `WHERE s.is_coachable = false`).
- **What is wrong**: the 150-pair labelled sample is drawn **exclusively from kb_pairs production
  already filed to a sink**, and production files to a sink precisely when the bge top-1 match is a
  sink. So `top_is_real` is False for all 150 rows in the bge arm by definition of how the sample
  was selected. `embedder_compare_v2.json` confirms exactly: `bge_768.sink_routing_kept_frac = 0.0`,
  `sink_routing_balanced_acc = 0.5` — an all-negative constant predictor. Gemini is not selected on
  its own decision boundary, so it varies freely (0.587-0.613). Taxonomy item 5 and item 1 at once.
- **What number it corrupts, and in WHICH DIRECTION**: the headline verdict. `_CRITERIA` +
  `_MIN_DELTA = 0.03` grades "beat bge on >= 2 of 3". From `embedder_compare_v2.json`:
  gemini_768 = margin **+0.125 ✓**, coupling **−0.048 ✗**, routing **+0.113 ✓** → **2/3 = PASS**;
  same for gemini_1536 (+0.104/+0.087) and gemini_3072 (+0.111/+0.103). The shipped harness would
  print **PASS for every width**, against CLAUDE.md's recorded "1 of 3 pre-registered criteria —
  DOES NOT PASS". The flip is carried entirely by a criterion whose baseline cannot be anything but 0.5.
- **Confidence**: certain (the 0.0 kept-fraction in the artifact is the proof; the SQL is the mechanism).
- **Cheapest way to verify**: `grep -n "is_coachable = false" Brain/calibration/label_trigger_quality_sample.py`
  and `python -c "import json;d=json.load(open(r'Brain/artifacts/embedder_compare_v2.json'));print(d['bge_768'])"`.

### T3. The published coverage result "64.9% not_called_for matched vs 65.7% unrelated" is a REP-1-ONLY number whose sign reverses in rep 2 of the same run

- **File:line**: `Brain/calibration/trial_layer_c_arms.py:337-338` and `:423-426`.
- **What is wrong**: `_summarise_reps` builds the published per-side dict as
  `matched = dict(reps[0]["matched"], w=_mean(("matched","w")))`. Only `w` is replaced by the
  across-rep mean; `attempts`, `counts`, `w_conditional` and `not_called_for_rate` are all carried
  over from **rep 1 alone**. `_report` then prints all three on one line as if from one estimator.
  Taxonomy item 7.
- **What number it corrupts, and in WHICH DIRECTION**: the `not_called_for` comparison CLAUDE.md
  cites as the second, independent failure of "did this moment call for this move". Verified in
  `artifacts/trial_t3_coverage.json`, arm `arm14_unit_axes`: rep 1 = matched 0.6486 / unrelated
  0.6571 (matched **lower** by 0.8 pt — the published claim); rep 2 = matched 0.6689 / unrelated
  0.6000 (matched **higher** by 6.9 pt). The 2-rep mean is 0.659 vs 0.629 — matched is *higher*, the
  opposite of what was published. The same defect makes `arm143_full`'s printed `w_conditional`
  (matched 0.637 vs unrelated 0.936) a single-rep figure sitting beside a 2-rep `w`.
- **Confidence**: certain (both reps are stored under `reps`).
- **Cheapest way to verify**:
  `python -c "import json;p=json.load(open('artifacts/trial_t3_coverage.json'));a=p['arms']['arm14_unit_axes'];print([(r['matched']['not_called_for_rate'],r['unrelated']['not_called_for_rate']) for r in a['reps']])"`

### T4. The sink-pool Gemma judge is told the sink pairs span the UNION population's distinct calls — arithmetically impossible for 5 of 9 clusters, and all 5 got non-sink verdicts

- **File:line**: `Brain/calibration/diagnose_sink_pool.py:288-290` (`_render_cluster`), built at
  `:218-219` (`_build_cluster_records`).
- **What is wrong**: `distinct_calls` / `call_coverage` are computed over `members` — sink members
  **plus** the volume-matched control members — then rendered as
  `EVIDENCE: {n_sink} discarded pair(s) ... spanning {distinct_calls} distinct call(s) ({call_coverage:.0%} of the corpus)`.
  A pair belongs to exactly one call, so distinct calls over sink members can never exceed `n_sink`.
  From the committed artifact: cluster_2 `n_sink=10` → "28 distinct calls"; cluster_7 `22` → `28`;
  cluster_6 `31` → `53`; cluster_3 `61` → `85`; cluster_8 `81` → `113`. The control was introduced
  precisely so it would not be shown to the judge (`:205-208` samples from sink members only) — and
  its call coverage is fed in anyway, wearing the sink pool's label.
  `PROMPT_SINK_POOL_TRIAGE` (`shared/prompts.py:963`) names distinct-call support as a judging criterion.
- **What number it corrupts, and in WHICH DIRECTION**: **inflates** recurrence evidence for every
  mixed cluster, biasing the three-way verdict away from `genuine_sink` toward
  `belongs_to_existing` / `new_coachable_topic`. The artifact matches: the two clusters where
  inflation is impossible or negligible (cluster_1 535 sink / 287 calls; cluster_4 74 / 78) are the
  **only two** `genuine_sink` verdicts; all five arithmetically-impossible ones are non-sink.
  It corrupts (a) the headline `genuine_sink 2/609, belongs_to_existing 5/199, new_coachable_topic
  2/175` split, (b) the two homeless-topic support figures quoted verbatim in CLAUDE.md —
  `strategic_performance_consulting (94 pairs / 115 calls)` and `technical_operational_alignment
  (81/113)`, where the call counts are union counts and the true sink-only ceilings are 94 and 81 —
  and (c) downstream, `replay_layer_c_admitted.py`'s `by_cluster` arm, which routes exactly the
  `belongs_to_existing` clusters. **This is the chain that already ran in production**: the same
  `sink_pool_clusters.json` verdicts fed `graduate_sink_topics.py`, which graduated 4 scenarios and
  rerouted 164 pairs against the live `public` schema.
- **Confidence**: **certain** for the code defect and the arithmetic impossibility; **likely** for
  the verdict-direction consequence (the correlation with verdict is 5/5 but n=9).
- **Cheapest way to verify**: free —
  `python -c "import json;p=json.load(open('Brain/artifacts/sink_pool_clusters.json',encoding='utf-8-sig'));[print(c['id'],c['n_sink'],c['distinct_calls'],p['verdicts'][c['id']]['verdict']) for c in p['clusters']]"`

### T5. The "content-free" proxy is an ITEM-LENGTH proxy, so the headline 4.7% → 37.2% subject-bearing measures string length, not subject matter

- **File:line**: `Brain/calibration/trial_pool_unit.py:187`, `:246`, `:353`;
  `Brain/calibration/trial_pool_unit_gemini.py:225`, `:290` — all call
  `cluster_evidence.is_substantive(text, 5)` (`Brain/shared/cluster_evidence.py:200-213`).
- **What is wrong**: `is_substantive` is an **absolute** count of ≥5 non-stop alphabetic tokens in
  ONE pool item. Clause-arm items are single sentences; turn-arm items are whole turns (~3 clauses
  concatenated), and concatenation SUMS content words. The proxy therefore cannot report a higher
  content-free rate for turns than for clauses on the same text — a metric that can only move one
  way when the unit changes (item 5), with the two arms differing on exactly the property the
  threshold is sensitive to (item 1). `thin_fraction < 0.30` ("subject-bearing") and `>= 0.70`
  ("junk") inherit this directly.
- **Measured from the artifacts**: mean words per sampled cluster member 11.5 (clause) vs 28.7
  (turn), a 2.5x gap. `corr(thin_fraction, mean sample words)` = **-0.787** (clause), **-0.839**
  (turn). Binned by mean item length the two arms are the same metric:

  | mean sample words | clause: n, subject-share, mean thin | turn: n, subject-share, mean thin |
  | --- | --- | --- |
  | 0–8    | 60, 0.0%, 0.91 | 67, 0.0%, 0.86 |
  | 8–12   | 41, 0.0%, 0.73 | 29, 0.0%, 0.69 |
  | 12–18  | 47, 0.0%, 0.56 | 18, 11.1%, 0.54 |
  | 18–26  | 16, 31.2%, 0.43 | 13, 53.8%, 0.31 |
  | 26–40  | 6, 33.3%, 0.32 | 11, 81.8%, 0.17 |
  | 40+    | 1, 100%, 0.28 | **53**, 100%, 0.06 |

  Within every band the arms are close; the entire gap comes from the turn arm having 53 clusters
  with mean item length ≥40 words against the clause arm's 1. The turn arm also has **more**
  ≤8-word clusters than the clause arm (67 vs 60) — turn mode did not remove the backchannel
  families, it added long clusters beside them.
- **What number it corrupts, and in WHICH DIRECTION**: inflates the turn arm's
  `subject_bearing`/`subject_share`, deflates the clause arm's. Corrupts the two most-cited numbers
  of this effort — "subject-bearing 8 (4.7%) clause vs 71 (37.2%) turn" and "content-free 59.1% vs
  32.8%" — and the "71 coherent scenarios" reading. The direction of the underlying conclusion may
  still be right; the magnitude is unsupported.
- **Confidence**: certain (mechanism is a code fact; the length-matched table is arithmetic from
  the shipped artifacts).
- **Cheapest way to verify**: recompute over `artifacts/pool_unit_clause.json` and
  `artifacts/pool_unit_turn_092.json`; no pipeline run needed.

### T6. Arm B of the ceiling is 57% scored by a DIFFERENT model than arms A1 and A3, and nothing in the harness gates on it

- **File:line**: `Brain/calibration/score_naren_ceiling.py:435-438` (no `model=` / `fallback_models=`
  passed), `Brain/ego_trap/milestone_scoring.py:40-41, 318-323`.
- **What is wrong**: `_score_arm` calls `score_milestones_batch` without pinning a model, so the
  `_SCORING_MODEL` → `_SCORING_FALLBACKS` chain is live and each arm silently escalates under rate
  limits. `milestone_scoring` documents the fix (`fallback_models=()` pins hard while keeping key
  rotation) and the ceiling does not use it. `_report` prints the `scored_by` counter with the
  correct warning ("an arm scored by a different model is not comparable") but there is **no gate** —
  the pre-registered verdicts print regardless.
- **What number it corrupts, and in WHICH DIRECTION**: `W(B)` = 0.0709, the null in the headline
  signal-to-null claim. `artifacts/naren_ceiling.json`: A1 = `{gemini-3.1-flash-lite: 1834}`,
  A3 = `{gemini-3.1-flash-lite: 1806}`, **B = `{gemini-3.1-flash-lite: 793, gemini-3.5-flash-lite:
  1040}`**. The control is the only model-blended arm, 57% a model neither treatment arm ever saw.
  Direction is not determinable from the artifact (per-record `scored_by` is stored, so it is
  recoverable, but the script never splits on it) — which is the point: the most load-bearing number
  in the project has an uncontrolled variable sitting only in its null. The "0.090 same-model subset"
  quoted in CLAUDE.md is **not produced by this script at all**; the script's own report prints 0.071.
- **Confidence**: certain.
- **Cheapest way to verify**:
  `python -c "import json,collections;p=json.load(open('artifacts/naren_ceiling.json'));print({a:p['arms'][a]['models'] for a in ('A1','A3','B')})"`

### T7. Head-to-head C4's "FATAL 0.835" is a bare point estimate whose interval straddles its own bar, and its "replication" is the same 100 items re-judged

- **File:line**: `Brain/calibration/trial_head_to_head.py:646`
  (`lambda r: r < _BARS["c4_native_fatal"]`), `:650`; `shared/head_to_head.py:111-125` (`win_rate`
  returns a bare fraction, no interval).
- **What is wrong**: no confidence interval is computed anywhere in the gate. Recomputed from
  `h2h_control_c4.json`: 99 items with both orders, 14 ties, **85 decisive, A wins 71 → 0.835,
  Wilson 95% CI [0.742, 0.899]** — the lower bound is **below the 0.75 fatal bar**. Those 85 items
  span only **62 calls and 41 scenarios** (589 moments span 98 calls / 68 scenarios; 175 of 589
  moments share their expert reply with another moment — 414 distinct `naren_pair_id`), so effective
  n is materially below 85 and the real interval is wider (item 14). "Replicated to 0.008" is run-1
  0.843 vs run-2 0.835 — but both use the default `--seed 20260813` and the same `--max-items`, so
  `_run_stage:444` draws the **identical 100 item ids**. That reproduces judge stochasticity, not
  sampling error.
- **What number it corrupts, and in WHICH DIRECTION**: the C4 verdict itself. Stated precision is
  overstated toward certainty; "FATAL, replicated to 0.008" reads as settled when the interval
  reaches the bar.
- **Confidence**: certain (arithmetic on the persisted artifact).
- **Cheapest way to verify**: recompute a Wilson interval on 71/85 from `artifacts/h2h_control_c4.json`;
  `grep -n "default=20260813" Brain/calibration/trial_head_to_head.py`.

### T8. `usable_item_fraction` — the fix CLAUDE.md prescribes for the median's blind spot — scores the mega-blob it was written to catch at 0.973, and its own unit test asserts that as correct

- **File:line**: `Brain/calibration/trial_skills.py:136-150`; `Brain/tests/test_trial_skills.py:102-112`.
- **What is wrong**: the docstring says "A mega-blob split scores near zero here because the two
  scraps hold almost no items and the blob is one axis, not many." It does the opposite: the blob is
  one group of 394 which **clears** `floor=12`, so the fraction is 394/405 = **0.973**. The unit
  test — named `test_a_mega_blob_split_scores_near_zero_usable_items` — asserts exactly `394/405`
  and passes. The healthy comparison case (`[30, 28, 25, 2]`) scores 83/85 = **0.976**: essentially
  zero discriminating power between the pathology and the healthy case, the same defect class
  (`cross_scenario_coverage` → 1.0 by construction) it was introduced to fix.
- **What number it corrupts, and in WHICH DIRECTION**: nothing today — `usable_item_fraction` is
  **never called** by `run()`, `meets_standard()`, `evaluate_window()` or `report()`. But CLAUDE.md
  prescribes it as the fix for the median's small-K blind spot ("a mega-blob split cannot fool
  that"). Adopting it would **admit** the degenerate `[1, 10, 394]` split the median currently
  rejects — converting a correct FAIL into a PASS.
- **Confidence**: certain.
- **Cheapest way to verify**: read `tests/test_trial_skills.py:110` against the docstring at
  `trial_skills.py:145-149`.

---

## ALL FINDINGS

Ranked worst first. Every item traces to one of W2-C1..C5; recomputed figures preserved.

### A1. Every "% of turns" in the Gemini adjudication chain silently excludes HDBSCAN noise and triage-dropped clusters — inflating each share ~1.9x
- **File:line**: `aggregate_cluster_verdicts.py:71` (`tot_turns = sum(rows[i]["n_items"] for i in common)`), used at `:79-80`, `:94`, `:132-134`.
- `tot_turns` is 12,582 — turns surviving both HDBSCAN (noise_share 0.435, from `pool_unit_gemini_full_3072d.json`) and the `INSUFFICIENT_EVIDENCE` triage drop (275 merged groups → 245 judged, `trial_adjudicate_gemini.py:233`). The real pool is **23,949**. The script never prints 23,949 at all, so its "% of turns" figures are unlabelled shares of a 52.5% subset (item 2).
- **Corrupts, direction**: **inflates every turn-share ~1.9x**. "Retention 41.0% of turns" is 5,159/12,582 → **21.5%** of corpus. "coachable turn volume 35.1%" is 4,422/12,582 → **18.5%**. "35.1% vs 31.0%" also compares two different denominators (12,582 vs 12,000).
- **Confidence**: certain. **Verify**: `sum(r["n_items"] for r in rows)` = 12,582 vs `"turns": 23949`.

### A2. The turn-mode coachable rate uses a denominator production never has, printed next to a production reference
- **File:line**: `trial_adjudicate_gemini.py:136-144` (`coach = kinds["scenario"]` … `f"coachable: {coach}/{len(rows)}   [live production for reference: 85/161 = 52.8%]"`).
- Two errors on one line. (a) numerator excludes merged clusters (the T1 collapse). (b) denominator `len(rows)` counts all 245 adjudicated clusters including 69 merged — but production emits **no row** for a `merge_into` cluster (`v2/layer_a.py:529 continue`), so production's 161 is the analogue of 245 − 69 = 176.
- **Corrupts, direction**: **deflates** turn mode's coachable rate against the reference on the same line. Printed 38/245 = **15.5%**; production-comparable is 38/176 = **21.6%** (turn-aware run: 17.6% printed vs 23.9% comparable). The 52.8% reference is separately confounded on five axes — embedder, pool unit, `min_cluster_size` (50-of-73,771 vs 16-of-23,949), merge threshold (0.85 vs 0.97), adjudicating model (`gemma-4-31b-it` vs `gemini-3.5-flash-lite`). The file's own `--min-cluster-size` help text warns against one of the five and prints the comparison anyway.
- **Confidence**: certain for (a) and (b). **Verify**: count `kind` values in `adjudicate_gemini_min16.json` — 38 scenario / 69 merged / 129 mechanics / 9 logistics.

### A3. The same collapse corrupts the "proxy vs reality" verdict — by 2.6x, in the opposite direction
- **File:line**: `trial_adjudicate_gemini.py:167`, `:174` (`s = sum(1 for r in thin_lo if r["kind"] == "scenario")`).
- The subject-bearing band (`thin < 0.30`) is scored against `kind == "scenario"` only, so the 52 merged clusters in that band count as Gemma rejections. This is the line that generated the (withdrawn) "the content-free proxy is directionally wrong" verdict.
- **Corrupts, direction**: **deflates** the proxy's agreement with Gemma. Printed: "97 clusters <30% content-free, of which Gemma called **32** coachable (33%)". Correct (scenario+merged): **84 (87%)**. min 50 prints 16/32 = 50%; correct is 26/32 = 81%. The `>=0.70` junk band is barely affected (1 → 9 of 101, 1% → 9%), which is why the proxy's junk-detector half survived and its quality-measure half did not.
- **Confidence**: certain. **Verify**: `python calibration/trial_adjudicate_gemini.py --load` (free) vs a recount including `kind == "merged"`.

### A4. `merged` was split out of the outcome enum but is still pooled into the support-thickening statistic — the exact metric the merge-blindness bug manufactured
- **File:line**: `replay_layer_c_admitted.py:354-357`, reported `:374-377`, printed `:403-409`.
- `_match_milestones` correctly emits four outcomes, but `_summarise_arm` collects `support_frac_deltas` for `o["outcome"] in ("matched", "merged")` — a two-way collapse — and `support_thickened`/`support_thinned`/`support_frac_delta_mean` are computed over that pooled list. A `merged` row's `arm_support` is by construction the support of a cluster that absorbed 2+ baseline milestones, so it is guaranteed larger.
- **Recomputed from `layer_c_admitted_replay_postfix.json`**:

  | arm | matched rows | merged rows |
  |---|---|---|
  | `by_cluster` | n=375, thick=6, mean **+0.0007** | n=8, thick=7, mean **+0.4587** |
  | `by_trigger_nonsink` | n=172, thick=59, mean **−0.0170** | n=83, thick=78, mean **+0.3825** |

- **Corrupts, direction**: **inflates** `support_thickened` and `support_frac_delta_mean`. The published `by_cluster` figure `support_thickened=13, mean=+0.0102` is essentially *entirely* the 8 merges; the 375 genuinely matched milestones move by +0.0007, i.e. nothing. In `by_trigger_nonsink` the pooling **reverses the sign** — cleanly matched milestones thin by −0.017 while the printed arm mean is +0.113.
- **Confidence**: certain (recomputed). **Verify**: split `payload["detail"][arm][key]["outcomes"]` by `o["outcome"]`.

### A5. "Baseline discrimination reproduced at 1.30 / 1.30 / 1.21 across three runs" is three re-scorings of the SAME eight alphabetical scenarios; the same arm gives 1.58 on a stratified sample
- **File:line**: `trial_layer_c_arms.py:329-336` (`_spread` is the range across scoring reps only), `:413` ("An arm difference smaller than the replication spread is NOT a result").
- The spread offered as the significance yardstick measures **scoring replication on a fixed item set** and nothing else. `trial_t1/t2/t3` all carry the identical 8-key `clustered` list (`ai_capability_discovery` … `budget_and_performance_strategy_optimization`, **0 posture scenarios**) — the documented `--limit 8` alphabetical bias. `trial_final` uses 18 stratified scenarios (7 posture) and the same `arm0_baseline` returns **1.580**.
- **Corrupts, direction**: the claimed ±0.002-0.018 stability **understates real uncertainty by roughly 20x** — changing the sample moved the same arm by 0.37 (1.21 → 1.58). Arm-vs-arm deltas *within* one run share the sample and survive; quoting 1.30 as "the baseline" or a 0.02 spread as the bar for a cross-run claim does not.
- **Confidence**: certain (verified from the `clustered` lists in four artifacts). **Verify**: print `clustered` for `trial_t1_benchmark`, `trial_t3_coverage`, `trial_final`.

### A6. The Layer C replay placebo is matched on CLAUSE volume but the support gate is keyed on DISTINCT CALLS — and in the arm the conclusion turns on, the placebo perturbs calls 2.3x harder
- **File:line**: `replay_layer_c_admitted.py:163-179` (`_placebo_pool`), consumed `:566-569`; gate `:239-240` via `cluster_evidence.required_milestone_support`.
- `_placebo_pool` draws donors until `total_clauses >= n_clauses_wanted`. The gate is `max(floor, ceil(0.10 × scenario_calls))` where `scenario_calls` (`:207`) counts **distinct calls** in the combined pool. Admitted sink pairs concentrate in calls the scenario already contains; placebo donors are drawn uniformly across the corpus, so nearly every donor brings a *new* call.
- **Recomputed** (arm `scenario_calls` recovered as `support / support_frac`):

  | arm | extra clauses T / P | new distinct calls T / P |
  |---|---|---|
  | `by_trigger_nonsink` | 9,339 / 9,701 | 802 / 805 — matched |
  | `by_response` | 11,538 / 11,920 | 822 / 823 — matched |
  | **`by_cluster`** | **1,952 / 1,991** | **63 / 144 — 2.3×** |

  Per scenario: `ai_capability_discovery` 55 → **76** calls under treatment, 55 → **134** under placebo on an identical 853 admitted clauses (required support 8 vs 14). `media_channel_and_retargeting_discovery` also overshoots on clauses (79 vs 108, +37%).
- **Corrupts, direction**: **inflates the placebo's `lost` count** for `by_cluster` specifically — the load-bearing published comparison ("beats its own placebo on lost, 1 vs 6"). The placebo's 6 losses are spread 1/1/2/2 across exactly the four scenarios facing the stiffer gate. The two rejected arms are unaffected, so their rejection stands.
- **Confidence**: **certain** for the volume mismatch (recomputed); **likely** for how much of the 6-vs-1 gap it explains.

### A7. `validate_taxonomy_vs_layerd` TEST 1 compares two taxonomies whose coachable-entry share differs 2.4x, with no base-rate null
- **File:line**: `validate_taxonomy_vs_layerd.py:60-83` (`load_old`/`load_new`), `:109-119` (`match`), `:163-177`.
- Acceptance is `argmax over all taxonomy entries → is that entry coachable?`. OLD is 161 entries / 85 coachable = **52.8%**; NEW, read from `adjudicate_gemini_min16.json`, is 176 non-merged / 38 coachable = **21.6%** (245 rows: 129 mechanics, 69 merged, 38 scenario, 9 logistics). The arms differ in the single property that most directly drives the statistic, with no composition-matched or base-rate null (items 1 and 6).
- **Corrupts, direction**: the headline "production accepts 46.7% of 6,468 CSM client turns vs turn mode's 35.6%", and the reading that turn mode "correctly rejects more". Against each taxonomy's own base rate the comparison **inverts**: OLD 46.7% against 52.8% (ratio 0.89), NEW 35.6% against 21.6% (ratio **1.65**) — a composition-matched read says NEW is the *more* permissive taxonomy per coachable entry. "Agree on 78% of turns" is affected the same way. Uncontrolled secondary confounds: the two taxonomies' descriptions were written by **different chat models** (`gemma-4-31b-it` vs `gemini-3.5-flash-lite`), and turn-mode descriptions carry *verbatim* client keyphrases while production's are analyst-speak — a direct lexical advantage when matching real client turns.
- **Confidence**: certain that the arms are unmatched on coachable share; likely that it dominates the reported difference.

### A8. `compare_criteria_ab.py` has NO duplicate-run guard on its `public` arm — the exact precondition `measure_scoring_noise.py` refuses to proceed without
- **File:line**: `compare_criteria_ab.py:70-88` vs `measure_scoring_noise.py:73-89, 168-195`.
- `measure_scoring_noise` grew `duplicate_groups()` and a hard refusal after it once reported a floor computed from a `public` schema holding two concurrent runs blended together. `compare_criteria_ab` reads the same `public.milestone_performance` with no such check; its only guard is attempt-count drift at `:82-88`, firing above 15%.
- **Corrupts, direction**: the headline `weighted 0.043 → 0.068 (x1.6)`. A partially double-scored `public` inflates both `attempts` and (for re-scored signals) `hits`/`partial_hits`, and the observed **+11.5% attempt drift sits just under the 15% gate** — the same order as the 889 → 905 inflation the concurrency incident produced. CLAUDE.md attributes the +11.5% to "2 Gemma batch failures in the baseline arm"; that is asserted, never measured by this script. If the drift is contamination rather than baseline loss, the x1.6 is inflated.
- **Confidence**: certain that the guard is absent; **speculative** that this run was contaminated.
- **Verify**: `SELECT count(*) FROM (SELECT call_id, scenario_key, signal_turn_index FROM public.gap_events GROUP BY 1,2,3 HAVING count(*)>1) d;`

### A9. "43 improved / 17 worsened" counts milestones that exist in only ONE arm, with no counter and no warning
- **File:line**: `compare_criteria_ab.py:91-110`.
- The per-milestone query is a `FULL OUTER JOIN` and the loop computes `ow = (oh+0.5*op)/oa if oa else 0.0`, so a milestone present only in `public` gets `ow = 0.0`, a positive delta, and counts as **improved**; baseline-only counts as **worsened**. Nothing counts or prints how many of the 249 rows are one-sided (`measure_scoring_noise.py:271-272` at least prints its equivalent).
- **Corrupts, direction**: the 43/17 *shape* statistic — the entire argument that the rewrite's effect is real rather than noise. The arm with more attempts (`public`, +11.5%) touches more milestones, so one-sided rows are systematically `public`-only → they land in **improved**. **Inflates the "improved" count and the net +4.48**.
- **Confidence**: certain for the mechanism; magnitude unverifiable without the DB.

### A10. The noise floor's `MOVEMENT RATE` denominator includes milestones never attempted in one of the two runs
- **File:line**: `measure_scoring_noise.py:215-236, 259-272`.
- `keys = set(a_side) | set(b_side)`; `recs` is built over that union with `empty = {"a":0,...}`. `moved = [r for r in recs if r["delta"] != 0]` and the headline is `len(moved)/len(recs)` labelled `<-- THIS IS THE FLOOR`. A milestone attempted only in run B contributes `delta = W_B − 0`: it enters the denominator always and the numerator whenever `W_B > 0`. Those are coverage differences, not scoring variance. `only_one_side` is computed (`:229`) and its count printed (`:271-272`) but never excluded, and the intersection rate is never reported.
- **Corrupts, direction**: the "15.6% (37/237)" floor, the "|delta| median/max" line, and the `24 up / 13 down, net +2.12` shape used to argue the rewrite's lopsidedness is signal. One-sided rows are signed by which arm has them, contributing a **systematic** skew rather than variance. CLAUDE.md explains the lopsidedness as "at a ~3% hit rate a random flip can only move UP"; part of it is more likely B-only milestones. The rate itself moves ambiguously (zero-W one-sided rows dilute it down, non-zero push it up), which is why it should not be quoted as "the floor" without the intersection figure beside it.
- **Confidence**: certain for the mechanism; net sign on the rate is data-dependent and unmeasured (no saved log exists in `Brain/logs/`).

### A11. The min-16-vs-min-50 head-to-head conclusions do not survive a naive two-proportion test
- **File:line**: `aggregate_cluster_verdicts.py:119-135` (the HEAD TO HEAD table).
- Bare percentages, no interval, no test. Computed: coherent 207/245 vs 57/76 → +9.5pp, SE 5.5pp, **z = 1.73**; coachable 92/245 vs 25/76 → +4.7pp, SE 6.2pp, **z = 0.75**. Neither clears p<0.05 *before* accounting for the arms partitioning the **same corpus** (min-50 clusters are near-unions of min-16 ones), so effective n is smaller than 245/76 (item 14). Separately `judge_coherent` is `coh["yes"]` only (`:114`), binning the 24 min-16 / 12 min-50 `partial` verdicts as failures — a third enum collapse; scoring partial as 0.5 gives 89.4% vs 82.9%, same direction, smaller gap.
- **Corrupts, direction**: converts two null results into a stated finding. Point-estimate direction preserved; **significance is fabricated by omission**.
- **Confidence**: certain for the arithmetic; likely that dependence shrinks it further.

### A12. Every persisted skills result predates the `select_judge_thresholds` fix, and nothing in the artifact records that
- **File:line**: `trial_skills.py:191-218` (fixed selector), `:517-534` (payload — no selector/version field).
- The fix (select on the FULL standard, not the K bound alone) is in the code; all three full-corpus artifacts were produced by the **old K-only** rule. The judged set is byte-for-byte the K-only prediction and **omits every threshold satisfying a full standard**: `skills_trial.json` (bge) judged `[0.675, 0.7, 0.725, 0.95]`, full-standard points are t ≤ 0.625 (K=1–2, median 202–405) — none judged; `skills_trial_gemini.json` judged `[0.725, 0.75, 0.95]`, full-standard point t = 0.70 (K=2, median 202.5) — not judged; `skills_trial_v2.json` judged `[0.675, 0.7, 0.725, 0.95]`, full-standard point t = 0.55 (K=1, median 405) — not judged.
- **Corrupts, direction**: the published validity figures (0.50 / 0.667 / 0.50) are not measurements at any threshold satisfying the gate they are read against. The conclusion survives — the unjudged points are degenerate K=1–2 blobs — but that is the "harmless by luck" the fix was written to end, and it is still true of every published number. Payload records `seed`, `model`, `abstract_prompt`, `embed_backend` but no selector marker (item 12).
- **Confidence**: certain (judged sets match the K-only prediction exactly in all three runs).

### A13. Merge validity `V(t)` is stored as a bare fraction with no denominator, and the denominators are 3–5 groups
- **File:line**: `trial_skills.py:502-507`, `:524` (`"validity": {str(k): v ...}`), `:485-490`.
- `validity[t]` is `same_move / len(real)` and only the float is persisted; real-group verdicts are **discarded** (only `null.verdicts` survives). Denominators are knowable from `n_skills`: at bge t=0.675 there are only **6 groups**, so V=0.20 must be **1 of 5**; gemini's best V=0.6667 at t=0.725 has **K=6**, so **2 of 3 or 4 of 6**. 95% interval on 2/3 ≈ [0.09, 0.99], on 4/6 ≈ [0.22, 0.96] — both contain the V_MIN = 0.80 bar.
- **Corrupts, direction**: "best validity 0.667 … short of the 0.80 bar" and "0.20 against a bar of 0.80 — off by 4x, not a near miss" both read as precise. The 0.20 = 1/5 case survives an exact binomial (P(X≤1 | p=0.8, n=5) = 0.007); **the 0.667 case does not** — it is statistically indistinguishable from a pass. Reported precision is overstated; the gemini arm's failure is not established.
- **Confidence**: certain that the denominator is unrecorded and ≤ 6; likely on the exact value.

### A14. `judge_groups` coerces any unrecognised verdict to `"fused"`, biasing the validity curve DOWN and the null-rejection rate UP simultaneously
- **File:line**: `trial_skills.py:399-403` (`out[...] = verdict if verdict in ("same_move","fused") else "fused"`).
- No lower-casing, no counter, no warning: `"Same_move"`, `"same move"`, `"SAME_MOVE"` or empty all become `"fused"`. `"fused"` is simultaneously (a) the verdict that **lowers** `V(t)` and (b) the verdict counting as a **rejection** in `null_passed`. A group id the model omits never enters `out` at all — silently shrinking the denominator with no counter, contradicting the function's own docstring ("Every group gets a verdict; never a returned subset").
- **Corrupts, direction**: both curves, **both toward the published conclusion** — `V(t)` deflated (→ "no window") and the null pass inflated (→ "the judge is sound"). The reported **12/12 fused** null is *indistinguishable from 12/12 unparseable*, so the one control certifying this judge cannot rule out that the judge said nothing. Magnitude unrecoverable (real-group verdicts not persisted, A13).
- **Confidence**: certain as a code fact; magnitude unknown.

### A15. The 47.3% sink-pool noise rate is one-sided — the volume-matched control clustered in the same run is noisier still (54.6%)
- **File:line**: `diagnose_sink_pool.py:361-363`, `:379-386`.
- `noise_rate = noise_sink / n_sink_total` is computed for the sink population only. The control's noise rate is never computed, printed or compared, even though the entire justification for clustering a 1,865-pair control in the same run (`:15-19`) is that a property of the sink pool means nothing without the control's value for it. `_NOISE_ESCAPE_HATCH` is then tested against the one-sided number. From the artifact: `sum(n_sink) = 983` of 1,865 → 47.3%; `sum(n_control) = 847` of 1,865 → **54.6%**.
- **Corrupts, direction**: makes 47.3% read as a **property of the sink pool** when it is a property of the clustering. "47.3% of the sink pool is HDBSCAN noise, capping any cluster-based fix at ~53%" attributes a limitation to discarded content that content already feeding rubrics exhibits *more strongly*. Also: among clustered items the neutral mix ratio is 983/1830 = **0.537**, not the 0.50 the report prints as "indistinguishable" (`:390-391`) and that `_MIX_UNINFORMATIVE_BAND` centres on — every mix ratio reads ~0.04 too sink-enriched.
- **Confidence**: certain (both recomputed).

### A16. The replay's adoption verdict and adoption bar are two-valued decisions over a four-valued outcome enum, and "beats placebo" fires on a margin below the harness's own noise floor
- **File:line**: `replay_layer_c_admitted.py:424-433`.
- (a) `verdict` turns only on `gained_majority_admitted`, `bar` only on `lost`. **`merged` — the outcome the fix was built to expose — enters neither**; it is appended as a parenthetical `merge_note`. An arm with 0 lost and 83 destructive merges would print "adoption bar: no baseline milestone lost" as its headline. (b) `t["gained"] <= p["gained"]` is a bare integer comparison with no band: for `by_cluster` that is **4 vs 0** → "beats placebo", while the design's own recorded result is that perturbing a clause pool at all costs ~6 milestones to UMAP/HDBSCAN sensitivity.
- **Corrupts, direction**: **inflates** confidence in `by_cluster`. The two printed conclusions ("beats placebo", "adoption bar FAILS — 1 lost") are the whole verdict surface, and neither is sensitive to the 8 merges — including the 5-into-1 collapse in `media_channel_and_retargeting_discovery` that had to be found by reading verbatim samples.
- **Confidence**: certain.

### A17. The pool-unit harness's printed VERDICT is built on the check its own code says was retired for rewarding junk — and that check favours the CLAUSE arm
- **File:line**: `trial_pool_unit.py:400-403`, `:429-444` (report/VERDICT) vs `:322-328` (`merge_sweep` docstring: *"check 1 was RETIRED (it correlates +0.53 with content-free fraction, i.e. it rewards the junk)"*).
- Check 1 (share of clusters whose coherence beats a size-matched null by ≥0.05) is still computed, still printed as the first gate, and is the **only quantitative line in the VERDICT block**. The null is size-matched but not composition- or length-matched (item 6), which is why it rewards homogeneous junk (item 5).
- **Corrupts, direction**: `check1_share_clearing_null` is **0.988 clause / 0.958 turn**, so the VERDICT block prints `clause 98.8% -> turn 95.8% (-3.0 points)` — the harness's own headline gate says the **treatment arm is WORSE**, while the published result cites a different, unprinted metric. Reproduced the documented defect on both artifacts: `corr(lift, thin_fraction)` = **+0.527** (clause), **+0.605** (turn). Anyone re-running `--load` today gets a verdict contradicting the published conclusion, with no note that check 1 was retired.
- **Confidence**: certain. **Verify**: `python calibration/trial_pool_unit.py --load artifacts/pool_unit_clause.json,artifacts/pool_unit_turn_092.json` (free).

### A18. "3072 beats 768 for clustering" compares `subject_share` at equal merge threshold, not equal cluster count — and `subject_share` rises steeply with cluster count
- **File:line**: `trial_pool_unit_gemini.py:266-302` (sweep loop, `subject_share = len(sb)/d`).
- `subject_share` is a share of *surviving clusters*, and finer clustering makes each cluster more homogeneous, so it increases monotonically with cluster count within a width. At a fixed merge threshold the two widths do not produce the same number of surviving clusters (item 1).
- **Corrupts, direction**: **inflates 3072's apparent advantage**. Within 3072 the curve is surviving → subject_share: 90→0.200, 136→0.265, 183→0.317, 217→0.369, 230→0.387, 245→0.396 (≈ +0.0013/cluster). At *matched surviving counts*: 183 vs 193 → 0.317 vs 0.321 (**768 ahead**); 217 vs 209 → 0.369 vs 0.335; 230 vs 225 → 0.387 vs 0.360; 245 vs 234 → 0.396 vs 0.368. Interpolating 3072's curve to 768's counts, the gap at 0.92 (0.265 vs 0.229) **vanishes entirely** and the top-end gap shrinks from ~3.6pt to ~2.2pt. Honest statement: "3072 wins at the coarse end only after controlling for cluster count, and ties or loses at the fine end".
- **Confidence**: certain (pure arithmetic from the two gemini artifacts).

### A19. C4 and the headline W3 carry OPPOSITE length asymmetries, and the cell that would neutralise them holds 8 comparisons
- **File:line**: `trial_head_to_head.py:369-375` (`_pair_for` c4 vs w3), `:538-542` (`length_matched`), `:109` (`_LENGTH_BAND = 0.25`).
- In C4, side A (native) is systematically the **longer** reply — median `log(len_a/len_b) = +0.361` over 100 judged pairs. In W3, side A (the CSM) is systematically the **shorter** — median **−0.344** over all 589 moments. Response length has a published AUC of 0.853 for "is this coachable" in this repo's own labelled sample, so a length-preferring judge produces a **high** A-win in C4 and a **low** A-win in W3. C4 is therefore not a bound on W3's artifact: the two differ in a second variable of comparable magnitude and **opposite sign**. The length-matched stratum covers only **10 of 100 C4 items (8 decisive)**, 12 of 100 in C2, 15 in C3 — the median |log ratio| (0.34–0.36) sits outside the ±0.25 band. "Not length (C4's length-matched cell is 0.875, higher)" is **7 of 8 comparisons** (Wilson 95% ≈ [0.47, 0.99]). Only 12.4% of W3 moments would ever have been length-matched.
- **Corrupts, direction**: C4's 0.835 is inflated by A being 43% longer, and the refutation of that explanation is unpowered. Residual bias in the "spectacular false positive" argument is **unknown**, not ruled out.
- **Confidence**: certain for the measured ratios and cell sizes; causal share not separable.

### A20. C4's cosine stratification is computed on a cosine that does not describe the pair being judged, and the claimed call holdout does not exist
- **File:line**: `trial_head_to_head.py:369-373` (`"cos": cands[0]["cosine"]`), `:537` (`by_decile(...)`).
- In C4 the displayed trigger is `naren_trigger` (= `candidates[0]`'s trigger) and the transplant is `candidates[1]`. The recorded `cos` is `cosine(CSM_trigger, candidates[1].trigger)` — the retrieval score against a **third** text not shown to the judge. The quantity that matters, `cosine(naren_trigger, candidates[1].trigger)`, is never computed. C4's docstring also claims "his whole call held out"; **no call holdout is implemented** anywhere in `_retrieve` or `_pair_for` (unlike `probe_retrieval_gate.leave_one_call_out_top1`).
- **Corrupts, direction**: voids CLAUDE.md's refutation "not retrieval quality — by cosine quartile 0.90/0.82/0.83/0.79" for C4, since that table stratifies on the wrong axis. On the 0.835 headline: the transplant is on average a worse match to the shown trigger than W3's would be, which **inflates** the native premium; the absent call holdout pushes the other way. Neither controlled. (Measured: median `|pair_id(A) − pair_id(B)|` is 1155, only 4/100 within 30, so same-call transplants are rare in practice.)
- **Confidence**: certain on the stratification axis; likely on the retrieval-quality bias direction.

### A21. Coverage arms and milestone arms are scored by prompts that differ in THREE things, not one — and the harness already measured the size of one of them
- **File:line**: `trial_layer_c_arms.py:278-301` (`score_coverage_arm`), `ego_trap/milestone_scoring.py:500-546`, `shared/prompts.py:1071-1102`.
- `score_coverage_arm` builds `{"benchmark_response": ...}` but `score_coverage_batch` never reads that key and `PROMPT_STEP3_COVERAGE_SCORE_BATCH` has no benchmark slot — it emits only `CLIENT TURN`, `REP RESPONSE`, `COVERAGE AREAS`. The milestone path is the mirror image: it shows the benchmark and (with `situated_fields` unset, as here) **no** client turn. So arm14/arm143 vs arm0r/arm3 varies (a) the unit, (b) benchmark shown → withheld, (c) client turn withheld → shown. The docstring at `:21-24` claims the arms isolate one lever.
- **Corrupts, direction**: the cross-unit rows and the `ATTRIBUTION` line `"unit+axes alone"` (`:404`). Direction is measurable from the harness's own arm 0b, which changes *only* the benchmark: ratio 1.304 → 1.118. Withholding the benchmark **depresses discrimination**, so the coverage arms' ratios (arm14 1.081, arm143 1.092) are **understated** relative to the milestone arms, by roughly the 0.19 arm0b measured, plus whatever the client turn adds.
- **Confidence**: certain for the code fact; likely for the magnitude.

### A22. Only the GENERATED arms silently drop null items whose partner scenario was skipped — `arm0_baseline` keeps them
- **File:line**: `trial_layer_c_arms.py:561-565` (derangement over all `keys`), `:572-582`, `:673-690` (`if not rubric: continue`), `:700-701`.
- `partner` is computed **before** clustering, over the full `keys` list, so `partner[k]` can point at a scenario that later falls back to V1 and is excluded from every arm. For `arm0_baseline`/`arm0b` the rubric source is `rubrics_db`, which still contains those scenarios, so their rows survive into the null. For generated arms the source is `generated[arm]`, so `arm_rubrics.get(rk)` is `None` and those rows are **silently dropped from the unrelated arm only**. Nothing counts the drop; `_report` never prints matched vs unrelated attempts.
- **Corrupts, direction**: the per-arm `ratio` and the `ATTRIBUTION` row "db rubrics vs regenerated legacy". Measured in `trial_final.json`: unrelated attempts are **616** for `arm0_baseline` but **598** for `arm0r_legacy_regen` and `arm3_inputs` over the identical 18-scenario matched population — an 18-attempt (3%) null-population difference between arms whose ratios (1.580 vs 1.038) are then compared head to head.
- **Confidence**: certain.

### A23. `arm0_baseline`/`arm0b` are scored against provably-unhittable milestones; the generated arms cannot be
- **File:line**: `trial_layer_c_arms.py:261-264` (no `skip_uncoachable=`), vs `score_naren_ceiling.py:437` (which passes it).
- `score_milestone_arm` omits `skip_uncoachable`, defaulting to `False` (`milestone_scoring.py:163`). `rubrics_db` carries `not_coachable_flag` from `ops/flag_uncoachable_milestones.py` — the 17 milestones measured at 74 attempts / 0 hits. Freshly generated rubrics have no such field by construction.
- **Corrupts, direction**: `W(matched)` for `arm0_baseline`/`arm0b`, **deflated**. Verified: `arm0_baseline` has **7 of 91** stored milestones flagged; `arm0r_legacy_regen` **0 of 89**. 7.7% of arm0_baseline's denominator is guaranteed misses. Correcting moves `arm0_baseline` W(matched) 0.1032 → ≈**0.112**, erasing essentially the whole `+0.012` printed on the ATTRIBUTION line "db rubrics vs regenerated legacy 0.103 -> 0.115" (and reconciling it with the ceiling's A3 = 0.114, which *was* run with `skip_uncoachable=True`). The per-arm *ratio* is largely protected — both sides use flagged db rubrics.
- **Confidence**: certain.

### A24. Arm 3's treatment strength depends on the calibration SUBSET, because its neighbour context is drawn only from the sampled scenarios
- **File:line**: `trial_layer_c_arms.py:569-570`; `v2/layer_c.py:410-436` (`_nearest_other_scenarios` filters `k2 in keys`).
- The situated prompt's "nearest OTHER scenarios" block — the "what this scenario is NOT" information arm 3 exists to add — is computed over the **sampled** key list, not the corpus. On an 8-scenario alphabetical sample every neighbour is an adjacent ATS/discovery scenario; on 18 stratified it is a looser set; production would be all 85 coachable. `arm0r_legacy_regen` passes `neighbours=[]`, so the **treatment varies with the sample while the control does not**.
- **Corrupts, direction**: arm 3's ratio, and it explains an otherwise unexplained reversal: `trial_t2_situated.json` (8 alphabetical) gives `arm3_inputs` **1.712** against a baseline of 1.297 — a large apparent *win*; `trial_final.json` (18 stratified) gives **0.889** against `arm0r` 1.038 — the published *loss*. Only the loss is recorded in CLAUDE.md. Arm 3's result is not portable to a different scenario count, and no run measures it with a production-sized neighbour pool.
- **Confidence**: certain for the code fact; likely that it is a material part of the reversal.

### A25. `permutation_counts` measures the group COUNT, never group membership, so the stability control cannot fail at fine thresholds
- **File:line**: `trial_skills.py:313-334` (`counts.append(len(set(cluster_behaviours(vectors[order], threshold))))`).
- Two shuffles producing the same number of groups with entirely different membership score drift = 0. At t=0.95 (K=316–340, mostly singletons) drift is **0.000 in all three runs by arithmetic, not by stability**. `cluster_behaviours` is greedy and order-dependent by its own docstring — a membership property, not a count property.
- **Corrupts, direction**: **understates drift everywhere**; the vocabulary reads as more stable than it is. This backs CLAUDE.md's "V2 did improve stability (drift 0.09–0.17)". Secondary: `evaluate_window` never consults `stability` at all, so a threshold failing `ORDER_DRIFT_MAX` (gemini t=0.725, drift 0.333) remains eligible to pass the window — stopping condition #3 is reported but not enforced.
- **Confidence**: certain.

### A26. Judged skill groups are truncated to the first 8 members in index order, so `V(t)` under-detects fusion in exactly the blobs it exists to catch
- **File:line**: `trial_skills.py:489` (`"behaviours": [b_texts[i] for i in g["members"]][:8]`).
- `summarise_groups` builds `members` in original item order and items are loaded sorted by `scenario_key`, so a 202-member group is judged on its **8 alphabetically-earliest-scenario members**. The judge never sees a mega-blob's real heterogeneity, and `V(t)` — the counterweight whose job is to get *worse* as distinct moves fuse — is systematically softened at coarse thresholds (item 13).
- **Corrupts, direction**: **inflates `V(t)` at coarse thresholds**, biasing the window toward PASS. The published negative therefore survives this defect — but any future PASS from this harness would not be trustworthy.
- **Confidence**: certain as a code fact; magnitude not measurable (real-group verdicts not persisted).

### A27. `compare_embedders`' stated pre-registered bars are not the bars the code applies, and `_MIN_DELTA` sits below the noise of an AUC at n=150
- **File:line**: `compare_embedders.py:24-26` (docstring: "sink_real_margin corrected >= 0.65, coupling >= 0.70, and the … spread wider than bge's 0.117. TWO of the three … Fixed here so they cannot be revised after seeing numbers") vs `:303-306`/`:328-340` (implemented: `sink_routing_balanced_acc` replaces `spread`, and all three become **relative deltas >= 0.03** against a recomputed bge baseline).
- The bar was changed after the numbers were seen — a criterion swapped out and absolute thresholds made relative — while the docstring still asserts the original marks are immutable. No uncertainty is computed on any AUC: with 63 coachable / 87 not, the SE of a single AUC is roughly **0.047**, so `_MIN_DELTA = 0.03` declares differences smaller than one standard error. The coupling "loss" of −0.048 is ~1 SE; the margin gain of +0.125 is ~2.7 SE.
- **Corrupts, direction**: the "wins/3" tally. Combined with T2, the tally is decided by one tautological criterion and one sub-noise criterion — toward declaring a difference where none is established.
- **Confidence**: certain on the docstring/code divergence; likely on the SE magnitude.

### A28. The sink-pool cross-check's per-verdict agreement pools clusters of wildly unequal size, hiding the one cluster that contradicts its verdict
- **File:line**: `diagnose_sink_pool.py:340-352`.
- `by_verdict` sums `labeled_coachable` and `n_labeled` across all clusters sharing a verdict and prints one percentage. Recomputed (this reproduces the published 21% / 71% / 80% exactly):

  | verdict | pooled | per cluster |
  |---|---|---|
  | `genuine_sink` | 12/57 (21%) | cluster_1 **4/46 (9%)**, cluster_4 **8/11 (73%)** |
  | `belongs_to_existing` | 12/17 (71%) | 6/8, 4/5, 2/2, 0/2 |
  | `new_coachable_topic` | 8/10 (80%) | 4/5, 4/5 |

  cluster_4 — a `genuine_sink` verdict covering 74 discarded pairs — has 73% of its labeled members marked coachable by the independent per-pair ground truth, i.e. it **contradicts** its verdict.
- **Corrupts, direction**: "the two verdict families agree in the predicted direction — 21% / 71% / 80%" is really "cluster_1 agrees strongly, and everything else rests on 2–8 labeled pairs". **Inflates** apparent agreement and suppresses the strongest disagreement. Effective n is 9 clusters, not 84 pairs (item 14).
- **Confidence**: certain (recomputed).

### A29. `check_milestone_thickening.py` prints only support INCREASES, and its automated dilution indicator has a denominator that grows with the treatment — so it structurally cannot fire
- **File:line**: `check_milestone_thickening.py:112-116`, `:123`, `:57-67`.
- (a) `if match is None or match["support_calls"] <= bm["support_calls"]: continue` — every milestone whose support **fell** or stayed flat is skipped silently, in a script titled "THICKENING vs DILUTION". (b) `saturated = sum(1 for s in t_supports if s >= 0.9 * t_calls)` uses the **treatment's own** `t_calls`, which grows precisely because admitted pairs bring new calls: the mechanism the indicator should catch inflates its own denominator. Treatment-only, no baseline comparison. (c) `_best_match` maps each baseline milestone to its best arm cluster **independently** — merge-blind by the same rule fixed in the replay, with no `claims` bookkeeping.
- **Corrupts, direction**: this is the script whose printed `>=90% of all calls: 0/7` was read as evidence against dilution while three baseline milestones were being fused into one 532-clause cluster. (a) and (b) both **deflate** the appearance of harm; (c) means real harm is representable only as "three THICKENED blocks whose AFTER clause lists happen to be identical".
- **Confidence**: certain for the code; historical consequence already recorded in CLAUDE.md.

### A30. The replay placebo is a *dispersed* null, while the metric it controls is "did the injected content form a cluster" — the treatment's content is coherent by construction
- **File:line**: `replay_layer_c_admitted.py:169` (donors drawn from every other coachable scenario, then shuffled).
- Stated design is "topically wrong content at the right volume". But under `by_cluster` the treatment's admitted pairs are literally the members of a single HDBSCAN cluster of response embeddings, i.e. mutually coherent by selection; placebo donors are maximally dispersed. `gained_majority_admitted` counts new arm clusters whose clauses are >50% injected — a coherence test. The null controls volume and leaves coherence free, on the one axis the metric measures (item 6).
- **Corrupts, direction**: **inflates** the treatment/placebo gain gap. In `by_cluster` the placebo scores 0 majority-admitted gains while producing **15** `gained_other` clusters against the treatment's 6 — the placebo *did* re-partition the pool, its donors just never formed a majority-donor cluster. Honest counter-evidence: `ai_capability_discovery` received the largest coherent injection (853 clauses, one whole cluster) and gained **0**; and in `by_trigger_nonsink` the placebo out-gains the treatment 98 vs 84. Real but not deterministic.
- **Confidence**: **likely**. **Verify**: compare `gained_other` (computed `:359-362`, stored, **never printed**) between each treatment and its placebo.

### A31. `_MIX_UNINFORMATIVE_BAND` is a pre-registered escape hatch with no `if` behind it — and 5 of 9 clusters sit inside it
- **File:line**: `diagnose_sink_pool.py:84`, `:375-386`.
- The module header declares `_MIX_UNINFORMATIVE_BAND = 0.10  # |mix - 0.5| within this => cluster separates nothing` as one of two stop conditions "fixed in the spec BEFORE the data existed". `frac_uninformative` is computed and printed — and then nothing. The sibling `_NOISE_ESCAPE_HATCH` has a real `if`; the mix hatch has none (item 5).
- **Corrupts, direction**: mix ratios are `[0.59, 0.67, 0.28, 0.41, 0.48, 0.45, 0.42, 0.34, 0.36]` → **5 of 9 (56%)** are within ±0.10 of neutral, i.e. by the harness's own pre-registered criterion the majority of clusters separate the sink pool from content already feeding rubrics *not at all*. Those 5 include cluster_0, cluster_3 and cluster_6 — three of the five `belongs_to_existing` clusters the `by_cluster` arm routes. The report prints "5/9 (56%)" as a neutral statistic with no consequence attached.
- **Confidence**: certain.

### A32. `min_cluster_size` is frozen at the ceiling 25 for any pool ≥ 1,250 items, and the harness prints it as "derived from" the fraction
- **File:line**: `diagnose_sink_pool.py:159-169`; `shared/cluster_evidence.py:193-197`; `tuning.yaml` `layer_c.min_cluster_size_ceiling: 25`.
- `max(floor, min(ceiling, round(fraction × pool_size)))` with `fraction=0.02, ceiling=25` clamps above 1,250 items. This pool is 3,730 → 74.6 → **25**. The ceiling was calibrated for Layer C's *per-scenario* clause pools (hundreds of clauses, fraction live); reusing it on a 3,730-item cross-scenario pool freezes granularity (item 15). The print at `:164-169` says `(derived from fraction=0.02, floor=3, ceiling=25 over 3730 items)`, which reads as scaled and never says the ceiling bound.
- **Corrupts, direction**: the cluster count (9), the noise rate (47.3%) and every per-cluster verdict are consequences of a fixed count, not of the data. A finer size would split the 794-member cluster_1 (which alone holds 535 of the 983 clustered sink pairs and carries the `genuine_sink` verdict covering 535 pairs). `_NOISE_ESCAPE_HATCH = 0.60` is evaluated against a rate the clamp largely sets, and does not fire at 47.3% — a slightly coarser clamp would have fired it.
- **Confidence**: **certain** for the clamp; **speculative** for how much finer clustering would move the verdicts.

### A33. `spot_check_adjudication` hardcodes `n_merged=1` and substitutes random samples for production's first-6 — and its single disagreement is exactly the cluster those two changes affect
- **File:line**: `spot_check_adjudication.py:113-118` (`"texts": c["samples"], "n_merged": 1`).
- `PROMPT_LAYER_A_V2_TRIAGE` contains `- {n_clauses} clauses total, merged from {n_merged} raw cluster(s)`. The probe always sends `n_merged=1`, telling the model each cluster is a single unmerged topic; `pool_unit_turn_092.json` cluster records do not store `n_merged`, so the value was invented, not read. Separately, production `layer_a._adjudicate` sends `cluster["texts"][:6]` — the **first six members in pool order**, near-adjacent turns from alphabetically-first transcripts — whereas the probe sends a seeded **random** six spread across the corpus.
- **Corrupts, direction**: the reported 7/8 agreement and the conclusion "Gemma CAUGHT the camouflaged junk … strong evidence because the probe gave it LESS context than production would". Both deviations run the opposite way. (a) Hiding the merge count removes the one piece of evidence justifying sinking an over-merged cluster — and the **only** disagreement is `sales, years, customer, role, team, marketing`, whose pre-written expectation was literally *"over-merged remnant: careers + RFP + programmatic"*, returned as `new_scenario`; so the harness may have manufactured its own miss (7/8 could be 8/8), or destroyed the probe's incoherence signal. (b) Random samples make an incoherent cluster (`jovio`, 563 items, 50% of corpus) look *more* incoherent than production's six same-call turns would, so the `jovio` sink verdict is **weaker** evidence than claimed, not stronger.
- **Confidence**: certain on the code facts and on which item disagreed; likely on the causal link for the `sales, years` miss. **Verify**: `--dry-run` prints the `merged from 1 raw cluster(s)` line with no API call.

### A34. `trial_pool_unit.py` uses `total_calls = len(files)` (416) where production uses `len(set(call_ids))` (400)
- **File:line**: `trial_pool_unit.py:146`, consumed `:208`, `:217`, `:240`; production `v2/layer_a.py:457`. The sibling `trial_pool_unit_gemini.py:205` gets this right.
- 16 transcripts contribute zero CLIENT turns, so the correct denominator is 400. Every `pool_unit_*.json` records `total_calls: 416`; `adjudicate_gemini_min16.json` records `400` (item 2).
- **Corrupts, direction**: (a) `required_call_support` becomes `max(4, ceil(0.02*416)) = 9` instead of `8`, one call stricter than production — the turn arm dropped 7 of 198 merged groups on this gate (198 → 191 surviving), so `surviving_clusters` is **deflated** and the `subject_share` denominator with it. (b) every `call_coverage` in these artifacts is **deflated by 3.8%**, pushing borderline clusters below `ubiquity_ceiling: 0.60` and **under-producing `needs_review` verdicts**.
- **Confidence**: certain.

### A35. `csm_client_turns` silently drops every turn of an unmapped transcript, and includes 417 turns Layer D itself excludes
- **File:line**: `validate_taxonomy_vs_layerd.py:96-105`, via `ego_trap/transcript_parser.py:23-30`.
- (a) `csm = mapping.get(f.stem, "").strip().lower()` yields `""` for an unmapped file, and `_classify` evaluates `s.startswith("")` which is **True for every speaker** — so every turn in that file is labelled CSM and the file contributes **zero** client turns, with no warning and no counter (item 10). Verified: exactly one file affected, `sample_call_priya_001` (106 mapping rows for 107 `.txt` files), which coincides with a Layer D exclusion — harmless today, a silent whole-file drop waiting on the next unmapped transcript. (b) The loop iterates all 107 transcripts; the 100-call Layer D run this test validates against excluded 7, including **6 files carrying 417 `Unknown Speaker` turns** (verified by grep: 46+58+162+99+16+36). `_classify` fails open, so all 417 are labelled CLIENT and enter the 6,468-turn population (item 13).
- **Corrupts, direction**: ~6.4% of TEST 1's turn population is unattributable text Layer D refuses to score. Both taxonomies see the same turns so the *comparison* is symmetric, but the absolute accept rates (46.7% / 35.6%) and the 78% agreement figure are computed over a population that is not Layer D's. Direction depends on how each taxonomy routes junk.
- **Confidence**: certain on both mechanisms and both counts.

### A36. Check 4's permutation null is drawn from the WHOLE pool, but the observed statistic is over the CLUSTERED subset only
- **File:line**: `trial_pool_unit.py:280-292`.
- 33,321 of 73,771 clause items and 11,701 of 23,949 turn items are HDBSCAN noise and excluded from every cluster, but their negation flags stay in the permutation pool. HDBSCAN noise is markedly more negation-heavy, so the null is centred on the wrong base rate (item 6).
- **Corrupts, direction**: `check4_stance_null` is inflated → `check4_ratio` **deflated**, in both arms and unequally. Measured: pool negation rate 0.1535 (clause) / 0.3165 (turn) vs clustered-population 0.1168 / 0.2463. Reported nulls (0.000550 / 0.003419) match the *pool*-rate binomial prediction (0.000549 / 0.003413) rather than the clustered-rate one (0.000436 / 0.002929) — confirming the mechanism exactly. Corrected: clause ratio 63.9 → **80.6** (×1.26), turn 16.2 → **18.9** (×1.17). Both still clear "ratio >> 1", so no conclusion flips; the correction widens the clause arm's already-larger stance ratio.
- **Confidence**: certain (numeric match exact to 3 s.f.).

### A37. TEST 3 compares two different estimators of "would get no rubric" and reports them as one number
- **File:line**: `validate_taxonomy_vs_layerd.py:200-209`.
- For OLD it prints the DB's `scenarios.rubric_status` counts — `skipped_insufficient_responses` is decided by Layer C from the count of **Naren RESPONSE clauses**. For NEW it prints `sum(1 for r in co if r["calls"] < MIN_MILESTONE_CALLS_FLOOR)`, where `r["calls"]` is the turn-mode cluster's distinct **CLIENT-turn** call count. Different populations through different gates (item 7).
- **Corrupts, direction**: the claim "turn mode strands **0** scenarios with no rubric (production strands 1)". Client-call support cannot predict response-clause support, so the NEW figure is a **lower bound presented as a count**, biased toward 0. Not evidence that turn mode strands fewer scenarios.
- **Confidence**: certain on the code; the true NEW number is unknown without running Layer C.

### A38. TEST 2's sample is unseeded and length-filtered
- **File:line**: `validate_taxonomy_vs_layerd.py:142-145` (`... AND length(trim(trigger_text)) > 20 ORDER BY random() LIMIT 600`).
- `ORDER BY random()` with no `setseed`, so the 600 turns differ every run and the printed rates are not reproducible; `length > 20` is a **character** filter removing short client turns — precisely the population where the sink-rejection mechanism decides the outcome (items 13 and 2). Both taxonomies see the same 600, so the comparison stays symmetric.
- **Corrupts, direction**: **inflates both** keep rates ("85.3% vs 74.0%") — longer turns are more likely to match a coachable entry, so these are not coverage estimates over Layer D's real moments. The 11.3-point gap is the only defensible part of TEST 2, and it still carries the ground-truth circularity the docstring admits.
- **Confidence**: certain.

### A39. `scenario_coherence`'s GO/NO-GO gate tests that the distribution has spread, not that the split is meaningful — and coherence is uncontrolled for scenario size
- **File:line**: `scenario_coherence.py:61-73` (`coherence`), `:120-131` (median split, half means, `separation`), `:149-155` (the gate).
- (a) Mean-cosine-to-centroid falls systematically as member count rises and nothing size-normalises it — the sibling `trial_pool_unit.py` builds an explicit size-matched null for exactly this reason and this file does not, so "loose half" is partly "large scenarios" (item 6). (b) The gate splits a continuous distribution at its own median and asks whether the half-means differ by ≥0.05; for any distribution with an IQR above ~0.05 that is satisfied by construction (item 5) — a pure-noise coherence distribution with the observed spread also passes.
- **Corrupts, direction**: the `separation` figure and the GO verdict that licenses spending the paid discrimination half. Inflates apparent separation by the amount attributable to scenario size; the gate cannot return NO-GO for a spread-but-meaningless split.
- **Confidence**: likely on (a) (not measured — needs a DB read); certain on (b) as a property of a median split. **Verify**: `artifacts/scenario_coherence.json` stores `n_triggers` and `trigger_coherence` per row — `np.corrcoef` settles (a) free.

### A40. The gemini merge threshold 0.97 was chosen by reading the six LARGEST clusters, showing their first three members in corpus order
- **File:line**: `trial_pool_unit_gemini.py:287-288` (`"sample": [... for i in idxs[:3]]`), `:305-312` (`sorted(..., key=lambda c: -c["n"])[:a.show]`).
- The stated method for choosing the threshold is "judged by reading", and what it prints is (a) the largest clusters only, (b) whose members are the first three by pool index, i.e. from alphabetically-first transcripts. Its own sibling names both traps explicitly (`trial_pool_unit.py:371-382`: "NEVER the first N … The same trap applies to 'the biggest N clusters'") and uses a seeded stratified sample instead (item 13).
- **Corrupts, direction**: the adopted `merge_cosine_threshold: 0.97` for the gemini backend and the "the groups read as coherent themes" judgement. The largest clusters are systematically the *over-merged* ones, so reading only them makes over-merging maximally visible and under-merging invisible — biasing the chosen threshold **upward** (finer). It also cannot detect the mid-sized account-bound / proper-noun clusters the later `flag_proper_noun_clusters` work found.
- **Confidence**: certain on the code; likely on the direction of the bias. **Verify**: `clusters_at["0.97"]` in `pool_unit_gemini_full_3072d.json` holds every surviving cluster with samples — a stratified read is free.

### A41. The merged pool-unit report never prints each arm's `min_cluster_size`/`merge_threshold`, and `--load` silently keeps only the first payload's overrides
- **File:line**: `trial_pool_unit.py:385-444` (`report` prints neither), `:452-453` (`merged = dict(payloads[0])`), `:457-459` (guard checks `total_calls` and nothing else), `main():481-483`.
- The two arms MUST run in separate processes at different thresholds, but a single process applies whichever values were passed to BOTH arms, and the merged report gives a reader no way to tell which happened (items 11 and 12).
- **Corrupts, direction**: no number is wrong *in the shipped artifacts* — the headline pair is correctly scale-matched (`pool_unit_clause.json` at the legacy 50 = 0.0678% of 73,771; `pool_unit_turn_092.json` at the override 16 = 0.0668% of 23,949; merge 0.85 vs 0.92). The defect is that this is **unverifiable from the report**, and `pool_unit_clause.json` predates the payload fields entirely — so a `--load` of clause,turn_092 produces a merged payload recording `min_cluster_size_override: 0, merge_threshold_override: 0` while printing a verdict about an arm that ran at 16/0.92. An artifact that actively misdescribes its own run; a conclusion has already been withdrawn twice for exactly this variable.
- **Confidence**: certain.

### A42. `trial_pool_unit_gemini` compares its turn-vs-turn cosine band against a bge **trigger-vs-scenario** band
- **File:line**: `trial_pool_unit_gemini.py:239` (`(bge turn-level reference: spread ~0.141, p50 ~0.558)`), also the docstring at `:15`.
- 0.141 / 0.558 is bge's best-match cosine between a **trigger and a scenario description** (`compare_embedders.py`'s `bge_768` row); the number beside it is gemini's **turn-vs-turn** band. This repo's own rule — "never borrow a floor between the two bands" — is violated by the label. The real bge turn-vs-turn measurement exists (h2h trigger-vs-trigger: p10 0.630, p50 0.689, p90 0.746, spread **0.116**).
- **Corrupts, direction**: the claim "turn-vs-turn spread is 0.130 vs bge's 0.141 — the compressed-space worry did NOT materialise". Against the correct bge turn-vs-turn reference, gemini's band (p50 0.625, spread 0.130) is **wider and lower**, not tighter. The conclusion survives, but the printed evidence points the opposite way to the one quoted. (Caveat: the two bge bands come from different corpora, so the defect is the mislabelled reference, not a specific corrected value.)
- **Confidence**: likely.

### A43. `--load` on a ceiling smoke artifact prints the full pre-registered verdicts with no indication it was smoke, and `--max-items-per-arm` is an unannounced alphabetical selector
- **File:line**: `score_naren_ceiling.py:601-605, 662-665, 489-561`.
- `--max-items-per-arm` truncates with `v[:args.max_items_per_arm]`, and `_build_items` iterates `keys` in `ORDER BY 1` (alphabetical), so the cap keeps the first N items of the alphabetically-first scenario — both a smoke cap *and* a selector (item 13). The `[smoke]` warning prints only on the live path at `:664`; `_report` never reads `payload["max_items_per_arm"]`, so `--load` prints `MAIN`, `LEAK` and `GATE` verdicts identically for a 2-item smoke run and a 383-item real one. Default `--out` is the same file for both.
- **Corrupts, direction**: `artifacts/naren_ceiling_smoke.json` records `max_items_per_arm: 2` but `scenarios: 49`, and yields `W(A3) = 0.375` / `W(B) = 0.083` — which `_report` renders as "INCONCLUSIVE, do NOT tune" with the gate **passing**, the opposite of the real run's verdict, printed with no caveat. Only a manually chosen `--out` saved the real number. `trial_layer_c_arms.py` has the milder version: it records neither `--limit`/`--sample` nor `--reps` at payload top level (only per-arm `n_reps`).
- **Confidence**: certain.

### A44. The ceiling's instrument gate is applied across a population boundary, and the symmetric arm ("B3") is genuinely absent from the code
- **File:line**: `score_naren_ceiling.py:391-397`, `:508`.
- `_build_items` appends to `A1` and `B` inside the same `for row in a1_sample:` loop, and to `A3` in a separate loop over `a3_eligible(secondary, primary_calls)`. There is **no code path anywhere in the file that scores an `a3_sample` row against a partner rubric** — grep for `a3_sample` returns two hits, both in that second loop. The gate at `:508` is `w_b >= _T_INSTRUMENT * w_a3`, comparing a null built from *primary-label* responses against a matched arm of *secondary-label* responses.
- **Corrupts, direction**: the "1.2 : 1" ratio, already retracted. Two details not in the retraction: (a) `distinct_pairs` are A1 383 / A3 346 / B 383, so B is population-identical to A1 and *not* to A3, confirming the retraction's direction; (b) even A1↔B symmetry is imperfect — A1 has `unscored: 12` (one whole 12-item batch failed on a `GemmaError` at `:439-443`) while B has `unscored: 0`, so A1's ratio is over 371 items and B's over 383. `_score_arm` never retries and never re-balances, so a batch failure permanently desymmetrises a pair of arms.
- **Confidence**: certain.

### A45. C2 shows a NATIVE reply as side A in 12 of 100 items — i.e. 12% of the "expert vs expert" control is actually C4
- **File:line**: `trial_head_to_head.py:352-359` (`_pair_for` c2); `shared/head_to_head.py:155-175` (`adjacent_rank_pair` may return `hi = 0`).
- C2 shows `m["naren_trigger"]`, which **is** `candidates[0]["trigger_text"]`. When `adjacent_rank_pair` picks the (rank0, rank1) pair, side A is the expert's **real reply to the exact trigger displayed** — A native, B transplant, i.e. C4's construction. Measured against `h2h_moments.json`: **12 of 100 C2 items have `cos == candidates[0].cosine`**.
- **Corrupts, direction**: **inflates** C2's A-win rate. Using C4's own 0.835 as the native premium, the contamination contributes roughly **+0.04**, so the measured 0.543 corresponds to ≈ 0.50 uncontaminated. The verdict survives (band [0.40, 0.60] either way), but C2 is quoted as a passing control and its number is biased.
- **Confidence**: certain (measured directly from the artifacts).

### A46. The head-to-head M5 gate never checks `moments_sha`, the model, or the model blend of the artifacts it pools
- **File:line**: `trial_head_to_head.py:615-626` (`_verdict`).
- `_run_paid:691-695` recomputes and asserts `moments_sha` before spending a call, and `_flush:500-503` writes `moments_sha`, `requested_model`, `fallback_models` and `models` into every control artifact. `_verdict` reads only `raw["raw"]` and `raw["pairs"]` and **ignores all four**. M5 will pool three controls judged on three different moment sets by three different models and print one gate verdict. The three real artifacts do carry different model blends (c2 165/35, c3 170/30, c4 184/15 primary/fallback = 17.5% / 15% / 7.5% downgraded), never surfaced.
- **Corrupts, direction**: the pooled C1 (0.669) and every per-stage rate, whenever artifacts diverge. In the runs on disk they do **not** diverge on sha, so no published number is currently wrong — the guard is absent and the blend is invisible.
- **Confidence**: certain.

### A47. The retrieval-gate bootstrap treats correlated rows as independent, and `clean_top1` answers a narrower question than the file's title
- **File:line**: `probe_retrieval_gate.py:132-143` (`bootstrap_lift`), `:291-295`; `trial_head_to_head.py:304` (same function, cross-corpus).
- (a) The bootstrap resamples **individual rows** — 2,904 coachable kb_pairs spanning **385 calls** (Naren→Naren) and 676 client turns spanning **98 calls** (cross-corpus). The file's own docstring states why this is wrong ("adjacent turns of one call are near-duplicates") and then uses a row-level bootstrap and a row-level leave-one-**call**-out in the same function. A cluster bootstrap over calls is the matching estimator (item 14). (b) `clean_top1` measures "is the top-1 neighbour **not sink-filed**", while the file is titled "Does trigger-similarity search actually find a **COMPARABLE** expert moment?" (item 2). The metric that answers the titular question, `same_scenario@1`, is **0.258** (74% of retrieved neighbours carry a different scenario key) and is demoted to "corroboration only".
- **Corrupts, direction**: the published intervals ([+0.168, +0.196] and [+0.130, +0.190]) are **too narrow**. Both lifts (+0.182, +0.161) are large relative to any plausible design effect, so the PASS verdicts are robust — a precision claim, not a verdict flip. The `clean_top1`-vs-title gap makes the gate's PASS read as stronger evidence of comparability than it is.
- **Confidence**: certain on both mechanics; verdicts unaffected.

### A48. C3's null partner is one fixed reply per scenario, reused up to 13 times
- **File:line**: `trial_head_to_head.py:492-493` (`by_scen[mapping[k]][0]["naren_response"]`).
- The deranged partner is the **first** moment of the partner scenario, not a random one, and every moment in a scenario receives the same B text. Measured: the 100 C3 pairs contain only **41 distinct B texts**, the most common used **13 times**.
- **Corrupts, direction**: C3's effective n is closer to ~41 than to its 72 decisive items. C3 = 0.750 lands exactly on its 0.75 bar; even the naive Wilson interval is **[0.639, 0.836]**, and the clustered one is wider. "Marginal, lands ON the bar" is correct but understates how indeterminate it is — C3 neither passes nor fails on this evidence. (No `a == b` collisions found, so the derangement itself is intact.)
- **Confidence**: certain.

### A49. (minor) Two residual asymmetries and one misreported denominator in `trial_head_to_head`
- **File:line**: `trial_head_to_head.py:232-237` vs `v1/layer_b.py:51-68`; `:444-447`; `_flush:499-507`.
- (a) `extract_pairs` applies `_is_substantive` **per Naren turn** and joins the survivors, whereas `_attach_responses` joins **all** CSM turns then filters the joined text — so the CSM's reply can carry backchannel turns the expert's structurally cannot, a residual of exactly the asymmetry the headline fix addressed. Affects only W3 (never run) and the 177 `dropped_thin_response` count. (b) `_run_stage:446` prints `f"SAMPLED {max_items} of {len(pairs) + skipped}"` **after** `pairs` has been reassigned to the sampled dict, reporting the frame as `100 + skipped` instead of `589 − skipped`. (c) `_flush` records `batch_size`, `seed`, `model` and `n_keys` but **not `max_items`** — nothing in the control artifacts says only 100 of 589 moments were judged.
- **Corrupts, direction**: (a) would depress the CSM side of a headline never computed; (b) and (c) misstate the sampling frame in the log and artifact — no measured value moves.
- **Confidence**: certain.

### A50. A cheap or exploratory `diagnose_sink_pool` run silently destroys the committed input artifact, and the replay's `by_cluster` arm then reports a perfect clean result over zero routed pairs
- **File:line**: `diagnose_sink_pool.py:92` (`--output` defaults to the committed `sink_pool_clusters.json`), `:472` (`verdicts = {} if args.no_gemma`), `:489` (unconditional write); consumed at `replay_layer_c_admitted.py:121-143`.
- `--no-gemma` and `--min-cluster-size N` (documented "EXPLORATION ONLY") both write to the same default path as the real run. `--no-gemma` writes `"verdicts": {}`, overwriting the only copy of the adjudication that `graduate_sink_topics.py` and `replay_layer_c_admitted.py` both read. `_route("by_cluster", …)` with empty verdicts does **not** return `None` (that path is only for a missing file at `:122`) — it returns `{}`, so the arm runs, treatment ≡ baseline, and the report prints `matched=385, lost=0, gained=0` → *"INDISTINGUISHABLE FROM PLACEBO"* + *"adoption bar: no baseline milestone lost"*. `min_cluster_size_overridden` **is** recorded in the payload but no reader checks it.
- **Corrupts, direction**: converts the `by_cluster` arm into a no-op that scores as the cleanest possible result — the strongest possible false positive. `n_adm` is printed at `:547-549`, so `routed 0 sink-bound pair(s)` would appear — recoverable by a careful reader, not by the report's verdict lines.
- **Confidence**: **certain** for the overwrite and for `{}` not short-circuiting; **speculative** that it has already happened (the committed artifact currently has all 9 verdicts intact).

### A51. The replay's `--limit` takes the first N rows of an unordered `SELECT` and overwrites the default artifact with no provenance recorded
- **File:line**: `replay_layer_c_admitted.py:80-81`, `:509-511`, `:581-593`.
- `coachable_keys[:args.limit]` slices a list whose order comes from `storage.get_scenarios`, which has **no `ORDER BY`** (`shared/storage.py:252-256`) — so it is Postgres physical order, in practice insertion order, and Layer A inserts largest-cluster-first. `--limit N` therefore systematically selects the *N largest* scenarios (item 13). The payload records `schema`, `percentile`, `variants` but **not** `limit`, **not** `seed`, and **not** which `sink_pool_clusters.json` (or its hash) fed `by_cluster` — and writes to the same default path as a full run.
- **Corrupts, direction**: a `--limit` run **inflates** `baseline_summary.n_milestones` per scenario and shifts every outcome distribution toward large, well-supported scenarios; being provenance-free, a `--load` re-report is indistinguishable from a full run except by eyeballing `n_scenarios`.
- **Confidence**: certain for the missing provenance and missing `ORDER BY`; likely for "insertion order ≈ largest-first".

### A52. `check_milestone_thickening.py` recomputes the replay's clusters in a SEPARATE process, where UMAP is documented non-reproducible
- **File:line**: `check_milestone_thickening.py:92-93` (`_pass1` re-run), header claim `:20-22`.
- The header argues faithfulness from importing `_pass1`/`_route` rather than reimplementing them — same *code*, different *process*. `replay_layer_c_admitted.py`'s own docstring (`:17-24`) states the opposite constraint: "which is why all arms run in ONE process: UMAP is deterministic on identical input within a process". This script exists to explain specific replay numbers (6→36, 22→133 in its own header) and recomputes them under the condition the replay was built to avoid.
- **Corrupts, direction**: undirected — the before/after supports, clause counts and cluster contents it prints are not guaranteed to be the ones the replay reported, so any figure read out of it and cited alongside a replay figure is a cross-run comparison. Magnitude unknown; the repo's measured spread on identical input is 385/398/403–407 milestones at corpus scale.
- **Confidence**: **likely** (non-reproducibility is measured and documented; whether it bit this 4-scenario run is unmeasured).

### A53. Gemma and the blind judges were shown different evidence, so their agreement rate is not a clean measure of either
- **File:line**: `trial_adjudicate_gemini.py:285` (`c["texts"][:REPRESENTATIVE_SHOWN]`, the first **6**, untruncated) vs `export_cluster_batches.py:91-93` (**12** samples, strided, each hard-truncated to **260 characters**).
- Item 1: three properties differ besides the judge — sample count (6 vs 12), selection rule (head vs stride; for the 78 of 245 clusters with `n_items < 24` the stride is 1, so those judges also got the head, contrary to the comment), and truncation. **632 of 2,940 judge samples (21.5%) were cut at 260 chars**, keeping the *opening* of the turn — precisely the part the `--turn-aware` note says is filler.
- **Corrupts, direction**: the judge-vs-Gemma agreement rate (T1's number) and the standalone judge coachability rate. Truncation biases judges toward "not coachable", **deflating** judge-coachable (92/245); the extra 6 samples push the other way. Net direction unresolved — which is the problem: the agreement number blends a granularity effect with an evidence-presentation effect.
- **Confidence**: certain that the arms differ; likely on net magnitude.

### A54. The "verified position-for-position" join guard has power over only 18% of rows
- **File:line**: `export_cluster_batches.py:124-132`.
- The guard compares `n_items` at each position and claims a silent mismatch is impossible. **200 of 245 rows share their `n_items` value with at least one other row** (largest tie: 15 clusters at 18 turns; 12 at 16; 11 at 21), so any permutation *within* a size tie passes and attaches one cluster's utterances to another's verdict — the exact failure the comment says it prevents. **188 of 245 rows sit in a tie group containing more than one `kind`**, so such a swap would move the agreement number. `st.distinct_calls` is already computed at `:84` and would cut the tied population from 200 to **76** at zero cost.
- **Corrupts, direction**: latent. If ordering ever diverges, every judge-derived number is corrupted unpredictably with no error raised. No evidence it diverged (gemini embeddings are deterministic) — a guard-strength defect, not a demonstrated miscount.
- **Confidence**: certain about the weakness; speculative that it has ever bitten.

### A55. A `--limit` path-test run of `trial_adjudicate_gemini` overwrites the real artifact, records no `limit`, and downstream analysis silently reports over the truncated subset
- **File:line**: `trial_adjudicate_gemini.py:102-105` (`_paths` tags on `mcs` and `turn_aware` only), `:244-246`, `:337-341` (records `merge`, `min_cluster_size`, `turn_aware`, `chat_model`, `embed`, `total_calls` — **not `limit`**).
- Item 11. The docstring's own recommended first command is `--limit 5   # cheap path test`, writing to the same `adjudicate_gemini_min16.json` the 245-cluster run wrote, with no distinguishing field. Worse, `aggregate_cluster_verdicts.py:69` computes `common = [i for i in rows if i in ver]`, so with a 5-row artifact and 245 verdicts it does **not** abort — `missing` is empty, it prints `"245 judged of 5 clusters"` and reports every rate over the 5 largest clusters. (`export_cluster_batches.py:124` *does* abort on the length mismatch — the guard exists in one consumer and not the other.)
- **Corrupts, direction**: all of them, toward the largest clusters — which are systematically more coachable (batch 00, the 41 largest, is 51.2% Gemma-retained vs ~29-49% for the rest), so the distortion **inflates** every coachable/retention rate.
- **Confidence**: certain (code path); recorded artifacts are all full 245/76-row runs, so it has not bitten yet.

### A56. The adjudication harness's merge handling diverges from the production code it claims to be a transport-only copy of
- **File:line**: `trial_adjudicate_gemini.py:300-319` vs `v2/layer_a.py:504-529`.
- The docstring says "TRANSPORT ONLY … Only the transport differs". Two behavioural differences. (a) On `merge_into`, production re-centres the target's centroid on the **union** (`layer_a.py:523-527`) and grows its `support_calls`/`support_clauses`; the harness does neither — merged evidence never reaches the accepted list, so the "NEAREST SCENARIOS ALREADY ACCEPTED" block the whole sequential design exists to feed is built from unblended first-member centroids. (b) Production validates `merge_into_key` against `by_key` and demotes an unmatchable key to `new_scenario` with a warning (`layer_a.py:507-514`); the harness accepts any string, so a hallucinated target would count as a retained duplicate.
- **Corrupts, direction**: (a) biases the merge count — production's wider union basins should attract *more* merges, so the harness likely **under-counts** duplicate detection (69/245), and every "38 distinct scenarios" support figure (`n_items`/`calls`/`coverage`) is reported **without** its merged evidence, understating support. (b) has **zero effect in the recorded runs**: all 69 (min 16), 65 (turn-aware) and 11 (min 50) `merge_into_key` values resolve to an accepted `scenario_key`. Also: the 69 merges land on only **22 distinct targets**, so "38 distinct scenarios enriched by 69 merged duplicates" is loose — 16 of the 38 received nothing.
- **Confidence**: certain that the code diverges; speculative on the magnitude of (a).

### A57. Blind-judge batches are contiguous size bands, with no interleaving and no double-judged cluster
- **File:line**: `export_cluster_batches.py:146-148` (`chunk = blind[start:start + a.batch]` over a list already sorted largest-first at `:95`).
- Batch 00 is the 41 largest clusters (69-822 turns), batch 05 the 40 smallest (16-19 turns). Each batch went to a different subagent, so **judge identity is perfectly confounded with cluster size**, and the stated rationale for batching ("see them RELATIVE to each other") means each judge calibrated against a size-homogeneous band. Zero clusters appear in two batches, so there is **no inter-rater reliability measurement at all** — this repo's other judge harnesses (head-to-head C1 position-swap, skills judge null) all carry one.
- **Corrupts, direction**: the judge coachability rate (92/245) and therefore the agreement rate. Per-batch judge-yes ranges 26.8%-43.9%, but Gemma-retained moves with it (29.3%-51.2%) in the same bands, so there is **no evidence of a large judge-leniency effect** — the design flaw is real, its measured impact small. Direction unknown.
- **Confidence**: certain about the design; likely that impact is minor.

### A58. (minor) `gate()` passes when the null is exactly zero
- `trial_layer_c_arms.py:353-359`: `passes = w_m > 0 and w_u < 0.5*w_m`, `ratio = inf` when `w_u == 0`. No minimum-attempts guard, so a tiny run trivially passes the headline gate — `artifacts/trial_smoke.json` has `arm0_baseline` at ratio `inf`, `passes: True` on 16 attempts. Item 5. **Confidence**: certain.

### A59. (minor) `trial_layer_c_arms` collects model provenance and throws it away
- `:706-715` — every call site is `m_rec, _ = score_milestone_arm(...)`; the `models` Counter is discarded and never reaches `payload` or `_report`. The ceiling harness records and prints exactly this (and T6 shows why it matters). Per-record `scored_by` survives, but only for rep 1: `_summarise_reps` keeps `"records": reps[0]["records"]` and strips `records` from every other rep, so **half of each arm's paid verdicts are not persisted at all**. **Confidence**: certain.

### A60. (minor) `compare_criteria_ab.py:82-83` prints an unsigned drift with a `+` format
- `drift = abs(a[0]-b[0])/b[0]` then `f"({drift:+.1%})"` — a *drop* in attempts prints as `+x%`. Correct for the published run (864 → 963) but the displayed sign is not derived from the data. **Confidence**: certain.

### A61. (minor) `stratified_sample`'s overshoot trim is alphabetical, not random
- `trial_layer_c_arms.py:149-150`: `chosen.discard(sorted(chosen)[-1])`. Rounding can overshoot by 1-2, and the correction always removes the alphabetically-last key — a deterministic, non-random exclusion inside a function whose docstring promises a seeded sample. Effect bounded at 1-2 scenarios. **Confidence**: certain.

---

## VERDICTS THAT MOVE

**9 flip, 9 weaken, 6 survive.** Each of the eight verdicts named in the task brief was checked
against the inputs; two of them do not move the way the brief anticipated and are corrected below.

### FLIPS (9)

1. **"Embedder comparison: 1 of 3 pre-registered criteria — DOES NOT PASS."** T2: one criterion
   (`sink_routing_balanced_acc`) is a constant 0.500 for bge by construction of the sample.
   Recomputing `_CRITERIA` from `embedder_compare_v2.json` gives **2/3 = PASS at every gemini
   width**. → **FLIPS to PASS as the code grades it**, but the PASS is worthless: it rests on a
   tautological criterion plus a coupling criterion measured below one standard error (A27). The
   honest statement is *no verdict is established*, not "passes" and not "1 of 3".
2. **"The coverage judge failed: not_called_for 64.9% matched vs 65.7% unrelated."** T3: rep-1-only
   number; rep 2 is 0.6689 vs 0.6000 and the 2-rep mean is 0.659 vs 0.629 — **matched is HIGHER**.
   → **FLIPS.** The "second, independent failure of *did this moment call for this move*" is not
   supported by the artifact it cites. (The applicability judge's separate 1.22:1 failure is
   untouched.)
3. **"Gemma over-sinks 14.6% of the corpus / 56 clusters."** T1: retracted in CLAUDE.md prose only;
   the code and `cluster_verdict_summary.json` still produce it. True value **0 clusters**;
   agreement 76.3% → **93.9%**. → **FLIPS** (and is still live).
4. **"The content-free proxy is directionally wrong."** A3: the printed 32/97 = 33% is 84/97 =
   **87%** once `merged` is counted. → **FLIPS** (already withdrawn in prose; still reproduced by
   `trial_adjudicate_gemini.py --load`).
5. **"Finer granularity is BETTER: min 16 beats min 50 (coherence 84% vs 75%, coachability 38% vs
   33%)."** A11: coherence z = **1.73**, coachability z = **0.75** — neither clears p<0.05 before
   accounting for the two arms partitioning the same corpus; and `partial` verdicts are binned as
   failures (89.4% vs 82.9% if scored 0.5). → **FLIPS to not established.** Point-estimate direction
   survives; the finding does not.
6. **"Production accepts 46.7% of CSM client turns vs turn mode's 35.6% — turn mode correctly
   rejects more."** A7: the arms differ 2.4x in coachable-entry share (52.8% vs 21.6%) with no
   base-rate null. Per coachable entry the ratio is OLD 0.89 vs NEW **1.65** — turn mode is the
   *more* permissive taxonomy. → **INVERTS.**
7. **"The four-arm baseline reproduced at 1.30 / 1.30 / 1.21 — corpus-level is stable (±0.002-0.018),
   which is why the gate is corpus-level."** A5: those three runs re-score the **same eight
   alphabetical scenarios**; the same arm returns **1.580** on the 18-scenario stratified sample.
   → **FLIPS as a stability claim** (uncertainty understated ~20x). **SURVIVES as a within-run
   claim**: arm-vs-arm deltas inside one run share the sample and remain comparable (subject to
   A22/A23).
8. **"Turn mode strands 0 scenarios with no rubric (production strands 1)."** A37: the two arms use
   different estimators — response-clause support vs client-turn call count — so the NEW figure is a
   lower bound presented as a count. → **FLIPS to unsupported.**
9. **"3072 BEATS 768 for clustering — 3072 wins at every merge threshold from 0.92 up."** A18:
   `subject_share` rises with cluster count and the widths were compared at equal *threshold*, not
   equal *surviving clusters*. At matched counts 768 is ahead at 183 vs 193 (0.317 vs 0.321) and the
   0.92 gap vanishes entirely. → **FLIPS at the coarse end / not established overall.** Note this
   also removes the stated contradiction with `compare_embedders.py`'s `gemini_768 > gemini_3072`.

### WEAKENS (9)

10. **Head-to-head control C4, "FATAL 0.835, replicated to 0.008."** T7: Wilson 95% CI
    **[0.742, 0.899]** straddles the 0.75 bar; effective n is below 85 (62 calls, 41 scenarios,
    414 distinct expert replies for 589 moments); and the "replication" re-judges the identical 100
    seeded items. A19: C4 and W3 carry **opposite** length asymmetries (+0.361 vs −0.344 median log
    ratio) and the length-matched refutation is **7 of 8 comparisons**. A20: the cosine
    stratification that "rules out retrieval quality" is computed against a text the judge never
    sees, and the docstring's call holdout **does not exist in the code**. → **WEAKENS**; the point
    estimate stands but "FATAL" is not established at the stated precision, and the sub-claim *"not
    retrieval quality — 0.90/0.82/0.83/0.79 by quartile"* **flips to void** (wrong axis).
11. **Head-to-head control C3, "0.750, marginal, lands ON the bar."** A48: only **41 distinct** B
    texts across 100 pairs (one reused 13 times), so effective n ≈ 41; naive Wilson **[0.639,
    0.836]**. → **WEAKENS to indeterminate** — C3 neither passes nor fails on this evidence.
12. **Pool-unit "subject-bearing 8 (4.7%) clause vs 71 (37.2%) turn."** T5: the proxy is an
    item-length proxy (`corr(thin_fraction, mean words)` = −0.787 / −0.839); within every
    length band the arms are close and the whole gap is 53 turn clusters ≥40 words vs 1.
    A34: the clause/turn denominators also ran at 416 calls instead of 400, deflating
    `surviving_clusters` and every `call_coverage` by 3.8%. → **WEAKENS heavily.** The direction
    (whole turns carry more subject matter) may survive; the magnitude does not, and "71 coherent
    scenarios" is not a statement about content. A17 adds that the harness's own printed VERDICT
    line says the turn arm is **worse** (98.8% → 95.8%) on the retired check 1.
13. **Sink-pool replay: "`by_cluster` is the least damaging by a wide margin and beats its own
    placebo on lost (1 vs 6) and gained (4 vs 0)."** A6: the placebo perturbs **2.3x more distinct
    calls** in `by_cluster` specifically (63 vs 144 new calls on matched clause volume), and the
    survival gate is keyed on distinct calls — the placebo's 6 losses fall in exactly the four
    scenarios facing the stiffer gate. A30: the placebo is a *dispersed* null while the metric is a
    coherence test and the treatment is coherent by selection (placebo produced 15 `gained_other`
    clusters vs the treatment's 6, never printed). A16: "beats placebo" fires on 4 vs 0, below the
    ~6-milestone noise floor the same document establishes, and neither the verdict nor the
    adoption bar reads `merged` at all. → **WEAKENS.** "Least damaging of the three arms" survives
    (the other two arms' 802/805 and 822/823 call matching is clean, so their rejection stands);
    "beats its own placebo" does not.
14. **"47.3% of the sink pool is HDBSCAN noise, capping any cluster-based fix at ~53%."** A15: the
    volume-matched control clustered in the same run is **54.6%** noise — noisier. A32:
    `min_cluster_size` was clamped to the ceiling 25 (0.02 × 3,730 = 74.6), so the rate is largely
    set by the clamp. → **WEAKENS/reframes**: it is a property of the clustering, not of the sink
    pool.
15. **Criteria rewrite "weighted 0.043 → 0.068 (x1.6); 43 improved / 17 worsened."** A8: no
    duplicate-run guard on the `public` arm, and the +11.5% attempt drift sits just under the 15%
    gate. A9: one-sided `FULL OUTER JOIN` rows land systematically in **improved**, inflating both
    the 43/17 shape and the net +4.48. → **WEAKENS.** (The rewrite's +0.025 vs a ±0.006 band is not
    overturned; its supporting shape statistic is.)
16. **Noise floor "±0.006 weighted; 15.6% (37/237) of milestones move on their own; 24 up / 13 down,
    net +2.12."** A10: the denominator is the **union** of both runs' milestones, so coverage
    differences enter as signed movement. → **WEAKENS**; the floor should be quoted with the
    intersection figure beside it, and the lopsidedness explanation ("a random flip can only move
    UP") is partly B-only milestones.
17. **"The two verdict families agree in the predicted direction — 21% / 71% / 80%."** A28: pooled
    over clusters of wildly unequal size; cluster_4, a `genuine_sink` verdict covering 74 pairs, has
    **73% of its labeled members marked coachable** and is invisible in the pooled number. Effective
    n is 9 clusters, not 84 pairs. → **WEAKENS.**
18. **"Arm 3 (situated inputs) failed at 0.889 against arm0r's 1.038."** A24: the treatment's
    neighbour context is drawn from the **sampled** scenarios only, so the treatment strength varies
    with sample size while the control (`neighbours=[]`) does not — the same arm scored **1.712** on
    the 8-scenario run. → **WEAKENS**; no run measures arm 3 with a production-sized neighbour pool.
19. **CLAUDE.md's homeless-topic support "strategic_performance_consulting (94 pairs / 115 calls)"
    and "technical_operational_alignment (81/113)."** T4: the call counts are union
    (sink + control) counts; the true sink-only ceilings are 94 and 81. → **WEAKENS** the evidence
    behind the two topics that were subsequently graduated in production.

### SURVIVES (6)

20. **Head-to-head control C1, "0.669 pooled, FAIL against the ≥0.75 bar."** W2-C3 reproduced it
    exactly (0.669, flip 0.201, n_scored 284, 15 both-tie) and its Wilson interval **[0.612, 0.721]
    lies entirely below the bar**. The order-handling machinery is clean (`normalize_winner` raises
    rather than coercing, both-tie items excluded from the denominator so an indecisive judge cannot
    pass). → **SURVIVES robustly.** A46 (M5 ignores `moments_sha`/model blend) is a missing guard,
    not a realised error in these artifacts.
21. **Skills trial, "no window at any bound."** Every defect found pushes toward PASS or is
    degenerate: A26 (8-member truncation) **inflates** `V(t)` at coarse thresholds; A25 makes drift
    read lower than it is; A12 shows the published validity was never measured where the power gate
    passes, but the unjudged points are degenerate K=1–2 blobs; A14's coercion deflates `V` and
    inflates the null pass. → **SURVIVES**, with two caveats: A13 shows the gemini arm's V=0.667 has
    a denominator ≤6 and is **statistically indistinguishable from a pass**, and A14 means the 12/12
    null rejection is indistinguishable from 12/12 unparseable. T8 additionally means the fix
    CLAUDE.md prescribes for the next attempt would convert a correct FAIL into a PASS.
22. **The ceiling's "1.2 : 1 is an arm-construction artifact" retraction.** A44 confirms it from the
    code — there is **no code path** scoring an `a3_sample` row against a partner rubric, and
    `distinct_pairs` are A1 383 / A3 346 / B 383. → **SURVIVES / strengthened.** Two additions: the
    missing "B3" arm was never written, and A1 lost a whole 12-item batch (`unscored: 12`) that B
    did not, so even A1↔B is 371 vs 383. T6 adds that `W(B)` is 57% a different model.
23. **Head-to-head control C2, "0.543, within [0.40, 0.60], PASS."** A45: 12 of 100 items are
    structurally C4 (native A), contributing ≈ +0.04, so the uncontaminated value is ≈0.50.
    → **SURVIVES** (the band holds either way) but the quoted number is biased upward.
24. **Retrieval gate PASS in both directions (0.812 vs 0.631; 0.791 vs 0.631).** A47: the bootstrap
    is row-level over correlated within-call rows, so the published intervals are too narrow, and
    `clean_top1` answers a narrower question than the file's title (`same_scenario@1` = 0.258).
    → **SURVIVES**; both lifts are large relative to any plausible design effect. A precision claim,
    not a verdict flip.
25. **"Gemini's turn-vs-turn spread 0.130 — the compressed-space worry did NOT materialise."**
    A42: the printed bge reference (0.141 / 0.558) is a **trigger-vs-scenario** band, not
    turn-vs-turn; against the correct reference (h2h trigger-vs-trigger spread 0.116) gemini's band
    is wider and lower. → **Conclusion SURVIVES; its printed evidence points the opposite way.**
26. **`merge_cosine_threshold: 0.97` for the gemini backend and `min_cluster_size` scale-matching.**
    W2-C1 and W2-C5 independently verified the scale match is real (16/23,949 = 0.067% vs
    50/73,771 = 0.068%), and W2-C1 verified the headline clause/turn pair is correctly matched.
    → **SURVIVES**, with A40 noting the threshold itself was chosen by reading only the six largest
    clusters' first three members, biasing it upward (finer).

---

## CROSS-FILE RECURRENCE WITHIN THIS WAVE

**Confirmed — the `kind == "scenario"` enum collapse over a four-valued enum (W2-C4 + W2-C5).**
W2-C5 found it live in `aggregate_cluster_verdicts.py:83` and `trial_adjudicate_gemini.py:167/174`
(T1, A2, A3), plus a third instance at `aggregate_cluster_verdicts.py:114` where `partial` coherence
verdicts are binned as failures (A11). W2-C4 found the *same shape* independently in
`replay_layer_c_admitted.py:354-357` (A4: `merged` pooled with `matched` for the thickening
statistic) and `:424-433` (A16: the adoption verdict and bar are two-valued over a four-valued
outcome enum, with `merged` in neither). Four files, two auditors, one failure mode: a category with
more than two outcomes collapsed to a boolean at the *analysis* layer while the data layer got it
right. W2-C4 verified the producer (`_match_milestones`) emits all four correctly and `_summarise_arm`
tallies all four — the collapse is always downstream of a correct cross-tab.

**Confirmed, and broader than stated — LENGTH as an uncontrolled confound.** The brief named this for
the pool-unit instruments (W2-C1) and it is confirmed there three times over: T5 (the content-free
proxy is an item-length proxy, `corr` −0.787/−0.839), A39 (coherence falls with member count, not
size-normalised), A38 (a `length > 20` character filter on the coverage sample). But it **also recurs
in W2-C3**: A19 measures opposite length asymmetries in C4 (+0.361) and W3 (−0.344) against a signal
whose published AUC for "is this coachable" is 0.853, with only 8 decisive length-matched
comparisons to control it. Two independent auditors, four harnesses, same uncontrolled variable.

**Correction to the brief — `usable_item_fraction` scoring the mega-blob at ~0.97 does NOT recur
across two inputs.** It is a single finding from W2-C3 (T8), and the recurrence is against
**CLAUDE.md's own prescription** rather than another auditor: the file prescribes it as the fix for
the median's small-K blind spot, its docstring claims it scores a mega-blob near zero, and its unit
test asserts 394/405 = 0.973 as correct. Recorded here so the merge pass does not double-count it as
cross-file evidence.

**Additional recurrences found across the wave, none pre-briefed:**

- **A cheap/exploratory run overwrites an expensive or committed artifact, with no provenance in the
  payload (item 11/12) — 4 of 5 inputs.** W2-C1 A41 (`--load` keeps payload[0]'s overrides; the
  clause artifact records `min_cluster_size_override: 0` while the report describes a 16/0.92 arm),
  W2-C2 A43 (`--load` on a smoke artifact prints full pre-registered verdicts with no "smoke"
  marker), W2-C4 A50 (`--no-gemma` overwrites the committed `sink_pool_clusters.json` and the
  `by_cluster` arm then scores perfectly over zero routed pairs) and A51 (`--limit` records neither
  limit, seed, nor which cluster artifact fed it), W2-C5 A55 (`--limit 5` path test writes the same
  path and the aggregator reports 245 verdicts over 5 clusters without aborting).
- **A prefix, a size-rank, or an unordered `LIMIT` used as a sample (item 13) — 5 of 5 inputs.**
  W2-C1 A40 (six largest clusters, first three members), W2-C2 A5 / A43 (`--limit 8` alphabetical;
  `--max-items-per-arm` alphabetical), W2-C3 A26 (first 8 members of a 202-member group), W2-C4 A51
  (`--limit` over a `SELECT` with no `ORDER BY` = largest-first), W2-C5 A55/A57 (largest-cluster
  truncation; contiguous size-band judge batches). W2-C1 and W2-C2 each verified the *correct*
  implementation exists in a sibling file (`_stratified_sample`, `take_sample`) — the trap is that
  both patterns live in the same repo.
- **A point estimate published with no interval, on an effective n far below the nominal one
  (items 7/14) — 3 of 5 inputs.** W2-C3 T7/A13/A47/A48/A27, W2-C5 A11, W2-C4 A16/A28.
- **A null matched on volume but not on the property the metric actually reads (item 6) — 2 of 5
  inputs, 6 findings.** W2-C1 T5, A36 (permutation null drawn from the whole pool while the
  statistic is over the clustered subset — reported nulls match the pool-rate binomial prediction to
  3 s.f.), A39, A7; W2-C4 A6 (clause-matched placebo against a call-keyed gate), A30 (dispersed
  placebo against a coherence metric).
- **Model provenance recorded but not gated, or not recorded at all — 3 of 5 inputs.** W2-C2 T6 (arm
  B 57% a different model, printed with a warning and no gate) and A59 (the four-arm trial discards
  its `models` Counter entirely and persists only rep 1's records), W2-C3 A46 (M5 pools three
  differently-blended artifacts), W2-C5 (no judge prompt, model id or `judged_by` recorded anywhere
  in `cluster_batches/`, against CLAUDE.md's own rule).

---

## CLEAN CATEGORIES

Verified-clean ground, grouped by taxonomy item. **MEASURED** marks a result an auditor established
by recomputation or a targeted read rather than by absence of evidence.

**Item 1 (asymmetric arms) — clean where checked:**
- **MEASURED.** `trial_head_to_head`'s named substantive-filter asymmetry **is fixed**: `_is_substantive`
  is applied to the CSM's trigger (`:180`) *and* response (`:237`, filtered `:801`, reported
  `dropped_thin_response = 177`), and the artifact confirms the median W3 log length ratio is
  **−0.344**, matching the recorded −0.68 → −0.34 improvement. Only the per-turn-vs-joined nuance
  (A49a) remains.
- **MEASURED.** `trial_layer_c_arms`'s matched/unrelated populations are drawn from the **same rows** —
  `_items(arm_rubrics[arm], lambda k: k)` vs `... lambda k: partner[k]` iterate the identical
  `samples` dict, both from the leakage-clean `a3_eligible` stratum. This is the symmetry the ceiling
  lacked; correct apart from A22's skipped-partner drop.
- **MEASURED.** `_volume_matched_control` samples exactly `len(sink_bound)` control pairs
  (`n_sink_total = n_control_total = 1865`), so the 50/50 mix base rate is not a class-imbalance
  artifact. The control's blinding is correct: verbatim samples shown to Gemma come from
  `sink_members` only and `_render_cluster` never exposes `mix_ratio`, `n_control` or the split
  (T4 is a leak of the control's *call statistics*, not its identity or text).

**Item 3 (numbering / base mismatch) — clean in every batch that touches it.**
- W2-C2: `milestone_ids` produces `f"M{i+1}"` from array position, `v2/layer_c` writes `order = i+1`
  over the same list, `describe_items_for` uses `order_idx + 1`, and the ceiling's `aggregate`
  round-trips `f"{rubric_id}::{milestone_id}"` without collision.
- **MEASURED.** W2-C5 traced `cluster_id` end to end: `r["i"]` (0-based) written at
  `trial_adjudicate_gemini.py:303`, exported unchanged at `export_cluster_batches.py:137`, joined at
  `aggregate_cluster_verdicts.py:44/51`; the six min-16 batch files span ids **0-244 contiguously,
  no gaps or duplicates, all 245 judged**.
- W2-C3: not applicable — no turn index is displayed to a model in those four files.
- W2-C4: no index crosses a display/model/storage boundary; `pair_id` is an opaque key
  (`int(pid)` guards a JSON-stringified id) and `turn_index` is loaded but never rendered.

**Item 4 (name that never matches) — checked against real definitions in three batches, no dead
literals.** `_ARMS`/`ARMS`/`arm_units`/`_NO_BENCHMARK_ARMS`/`_LEGACY_REGEN_ARM` all agree and
`--arms` raises on an unknown name; `_VALID_VERDICTS` matches what the prompts enumerate;
`EgoTrapRole.CLIENT`/`CSM`, `SpeakerRole.NAREN`/`JOVEO_OTHER`, `_GEMINI_TASK`'s keys and
`not_coachable_category == "mechanics"` all resolve; `_KIND_BY_DECISION`'s keys are exactly the
strings `PROMPT_LAYER_A_V2_TRIAGE` instructs the model to emit, with `merge_into` intentionally
special-cased — **MEASURED: all 245/76/245 rows carry one of the four decisions, zero fell through
to the default.** `replay_layer_c_admitted._route`'s three literals match `PROMPT_SINK_POOL_TRIAGE`
byte for byte. One latent residual: `ver[i]["coachable"] == "yes"` has no guard, so a future `"Yes"`
would bin silently as not-coachable (zero occurrences today).

**Item 9 (silent short-circuit) — explicitly handled where it previously burned this repo.**
`score_naren_ceiling._verify_ranking_equivalence` (`:339-364`) knows about
`rank_benchmark_responses`'s `<= limit` early return and compares sets rather than order in that
case; it runs before any Gemma spend and aborts on mismatch.

**Item 10 (silent drop) — the headline hazard on the gateway is MEASURED clean.** Every path to
`/embeddings` is count-checked: `embed_one` (`trial_gateway.py:271-283`) asserts exactly one vector
for one text *and* the returned width; `embed()` (`:296-312`) calls only `embed_one`, pre-allocates a
positional `out` list (never `zip`s two lists) and raises if any slot is unfilled; `embed_batched`
(`:325-334`) compares `len(got) != len(texts)` and falls back per-text with a `batch_worked` flag.
The self-test at `:466-478` verifies batched output **positionally** against independently embedded
references — stronger than the count check that failed silently in the native-SDK incident. No
`zip()` exists in any of those four files that could truncate a length mismatch.
Separately, `GatewayClient.embed` in `trial_pool_unit_gemini`'s path fails loudly on a short return
(`np.stack([have[k] for k in keys])` raises `KeyError`) rather than misaligning; and
`aggregate_cluster_verdicts.py:62-65` computes and prints `missing`, with coverage verified at
**245/245 and 76/76 with no duplicate `cluster_id` across all nine verdict files**.

**Item 11/12 (overwrite, weak checkpoint key) — two verified-safe cases against five defects.**
`trial_pool_unit --smoke` writes `pool_unit_trial_smoke.json`, stamps `"smoke": true` into the
payload and prints a NOT-INTERPRETABLE banner. `trial_gateway`'s batch-collapse check (`:451-456`)
was deliberately converted from an assertion to a `note`, because asserting that a bug reproduces is
itself a defect — correct as written. **MEASURED: the Matryoshka cache-key trap is avoided** —
`trial_pool_unit_gemini.py:122-123` keys on `sha256(model | NATIVE 3072 | text)`, truncation happens
after the cache read with an explicit renormalise, and `content_free_share` is byte-identical
(0.3280303979289323) across the 3072 and 768 artifacts, proving no vector leaked into that statistic.
No cheap run can poison the cache with wrong-width vectors — the width is inside the key.

**Item 15 (hardcoded count dressed as a formula) — the pool-unit arms ARE scale-matched, MEASURED
from the artifacts rather than from the flags.** `pool_unit_clause.json` ran the legacy formula = 50
of 73,771 items (0.0678%); `pool_unit_turn_092.json` records `min_cluster_size: 16` of 23,949
(0.0668%); the gemini harness hardcodes the same 16. The unmatched arm (`pool_unit_turn.json`, mcs
50, 74 raw clusters) is the one whose conclusion was already withdrawn and is not the source of any
published number. `NEAREST_SHOWN=3`, `REPRESENTATIVE_SHOWN=6`, `SAMPLES_PER_CLUSTER=12` are
prompt-layout constants, not thresholds.

**Production parity — the two documented ~20% mistakes do NOT reproduce in the pool-unit harnesses.
MEASURED.** (a) spaCy component disabling: both `trial_pool_unit.py:181` and
`trial_pool_unit_gemini.py:204` call production `v2.layer_a.build_client_pool` → production
`preprocessing.segmenter.segment_into_clauses`, which loads `en_core_web_lg` with **nothing
disabled**. The only disabled-component load is `_negation_flags:163`
(`disable=["ner","lemmatizer","attribute_ruler"]`), all three downstream of the dependency parser,
so `t.dep_ == "neg"` is unaffected and no pool item comes from that model. (b) `parse_transcript`
without the Avoma roster: both harnesses pass `load_roster(str(f))`; 412 of 416 transcripts have a
`.speakers.json` sidecar and the 4 without fall through to the same heuristic production uses.
Likewise `replay_layer_c_admitted._pass1` **imports** `build_clause_pool`, `_relevance_filter` and
`_cluster_milestones` from `v2/layer_c.py` rather than copying them, and its five fallback
thresholds match `_pass1_cluster_scenario:200-285` one for one.

**Zero-write enforcement is real.** `_connect_read_only` issues
`SET SESSION default_transaction_read_only = on` *and verifies the setting took* before returning;
`trial_layer_c_arms` reuses it; `ego_trap.gap_output` and `shared.checkpoint` are never imported by
either file (grep confirmed).

**Other specific clean results.**
- **MEASURED.** The `merged` fix in `_match_milestones` (`replay_layer_c_admitted.py:289-341`) is
  genuinely correct: `claims` accumulates every baseline index with `best_frac > 0.5` per arm
  cluster, `merged_arm_idx` is the >1 set, `outcome_name` branches before the outcome is appended,
  and `matched + merged` post-fix equals the pre-fix `matched` in all three arms
  (172+83 = 255, 172+92 = 264, 375+8 = 383). Support **is** normalised against each arm's own
  `scenario_calls`, and no printed *rate* uses a raw count. A4/A16 are about downstream re-collapse,
  not this function.
- **MEASURED.** `_pass1` handles the degenerate arm: with zero milestones, `arm_sets` is empty,
  `overlaps` is `[]`, and `:299` guards `np.argmax` with `if overlaps else -1`, so every baseline
  milestone is scored `lost` rather than crashing.
- `measure_scoring_noise.py`'s `--dedup` path is sound: `_assert_faithful` proves the `gap_events`
  rebuild reproduces the stored counters on the same schema before any deduplicated number is
  reported and refuses otherwise; `DISTINCT ON … ORDER BY …, gap_event_id` deterministically keeps
  the earliest verdict; the duplicate-run precondition is correctly keyed on
  `(call_id, scenario_key, signal_turn_index)`.
- `take_sample` is honest random, not similarity-ranked, and `a3_eligible`/`hold_out` filter on
  `call_id`/`call_filename` rather than `pair_id` — the stricter and correct choice for both leaks.
  The A3 stratum construction is the one part of the ceiling with no defect found.
- Head-to-head position/order handling is not a source of bias: `assign_swap_batches` builds the two
  orders in separate passes so a batch cannot hold both orders of one item and raises on duplicate
  ids; `normalize_winner` **raises** on an unparseable winner rather than coercing to `"tie"`;
  `order_average` maps disagreement to `"tie"`; `win_rate` returns `None` (not 0.0) when nothing is
  decisive; `swap_agreement` excludes both-tie items so a maximally indecisive judge cannot pass C1.
- **MEASURED.** C4's transplant is not contaminated by same-call neighbours in practice: median
  `|pair_id(native) − pair_id(transplant)|` = 1155, only 4 of 100 within 30. `leave_one_call_out_top1`
  is correct — copies before masking, masks the full within-call block, marks rows with no valid
  neighbour as `-1`.
- **MEASURED.** `probe_retrieval_gate`'s point estimate and its bootstrap are the **same estimator**
  (`outcome.mean() - base` vs `percentile(resampled means) - base`, same `base`, same n); no resample
  is discarded and `n == 0` is guarded, so there is no zero-denominator truncation.
- `compare_embedders`' sign handling and vector mechanics are correct: `score_space` is called in
  signature order, `truncate` slices *then* renormalises, `auc` uses average ranks within ties,
  `corrected()` is applied consistently with the raw AUC persisted — and **MEASURED**, the raws
  confirm bge (0.439) and gemini (0.314) point the *same* way, so the corrected comparison is not
  comparing an inverted signal against a direct one. The `spread` criterion is genuinely retired from
  `_CRITERIA` (only the docstring is stale — A27).
- `trial_skills` batching and null construction are sound where it counts: `null_groups`
  size-matches each null so the judge cannot identify nulls by size; `null_passed` returns **False**
  on an empty verdict set rather than passing vacuously via `all()`; `abstract_behaviours` reports
  items that got no behaviour back — **MEASURED: all three full runs abstracted 405/405**.
- **MEASURED.** `load_new`'s exclusion of `merged` rows in `validate_taxonomy_vs_layerd.py:69-83`
  is *correct*, not the enum-collapse bug — a `merge_into` cluster has no separate matchable
  description in either arm. Item 8 is clean in that file.
- **MEASURED.** The 416-vs-400 denominator does not flip any verdict in `spot_check_adjudication`:
  all 8 probed clusters sit at coverage ≤0.54 against `ubiquity_ceiling: 0.60` and at ≥9 distinct
  calls, so the hardcoded `--total-calls 416` and hardcoded `min_support=9` produce the same
  `scenario_candidate` triage verdict the correct 400/8 would.
- `_stratified_sample` (`trial_pool_unit.py:371-382`) is a real seeded stratified sample and
  explicitly not the first/biggest N; `--limit` vs `--sample` defaults in `trial_layer_c_arms` are
  safe (both default to 0 = all, `--limit` prints a loud warning, passing both raises, and `_report`
  shouts when a sample contains zero posture scenarios).
- `sink_pool_clusters.json` is confirmed tracked in git and both readers
  (`replay_layer_c_admitted.py`, `graduate_sink_topics.py`) agree with its actual shape on all 9
  clusters — no key-name drift.
- **Published counts verified CORRECT** by W2-C5: 245 min-16 clusters; retention 107/245 = 43.7% of
  clusters and 5,159/12,582 = 41.0% of *clustered* turns (denominator caveat in A1); 69 `merge_into`
  decisions; "of 138 genuinely sunk clusters judges want ZERO" (129 mechanics + 9 logistics, all
  judged `coachable: no`); "15 clusters Gemma kept that judges would drop" (2 scenario + 13 merged);
  the three-way agreement — proxy 97/245 = 39.6%, blind judges 92/245 = 37.6%, Gemma retention
  43.7%. W2-C4 verified every published replay number reproduces exactly from the artifacts (385
  baseline; 172/83/48/82, 172/92/34/87, 375/8/1/1; 2/609, 5/199, 2/175; 47.3% noise;
  `min_cluster_size` 25).

**Explicitly NOT verifiable, flagged rather than cleared:** whether the nine judging subagents in the
blind-judge experiment were distinct or shared, and what prompt they were given — no judge prompt,
model id or `judged_by` field is recorded anywhere in `cluster_batches/`.

---

## CLAUDE.md CORRECTIONS FROM THIS WAVE

Claims in CLAUDE.md that these findings contradict or weaken. **No edit was made.**

| # | Published claim | Finding | Suggested correction (one line) |
|---|---|---|---|
| 1 | "GEMMA AND NINE BLIND JUDGES AGREE 100% ON WHAT TO DISCARD … an earlier claim that Gemma over-sinks 14.6% was MY ANALYSIS BUG, now retracted" | T1 | Add: the bug is **still live** in `aggregate_cluster_verdicts.py:83` and in `artifacts/cluster_verdict_summary.json` — re-running reproduces the retracted claim verbatim; the retraction is prose-only. |
| 2 | "Embedding backend … 1 of 3 pre-registered criteria — DOES NOT PASS" | T2, A27 | The shipped `_CRITERIA` grades 2/3 = PASS at every gemini width; one criterion is a constant 0.5 for bge by sample construction and another is below one SE. Record as *no verdict established*, and note the docstring's bars are not the code's bars. |
| 3 | "The coverage judge with the client turn AND response in front of it: 64.9% `not_called_for` matched vs 65.7% unrelated" | T3 | Rep-1-only figure; rep 2 is 0.669 vs 0.600 and the 2-rep mean is 0.659 vs 0.629 — matched **higher**. Withdraw this as the second failure of "did this moment call for this move". |
| 4 | "Baseline reproduced at 1.30 / 1.30 / 1.21 across three separate runs with spreads of +/-0.002-0.018. That is why the gate is corpus-level" | A5 | Those are three re-scorings of the same 8 alphabetical scenarios; the same arm returns 1.580 on 18 stratified. The spread covers scoring replication only, not sampling. |
| 5 | "subject-bearing 8 (4.7%) clause vs 71 (37.2%) turn"; "content-free 59.1% vs 32.8%" | T5, A34 | The proxy is an item-length proxy (`corr` −0.787/−0.839); within each length band the arms are equal. Direction may hold, magnitude does not. Also: these artifacts used 416 calls where production uses 400. |
| 6 | "the ceiling's W(B) = 0.090 same-model subset" | T6 | Not produced by `score_naren_ceiling.py` — the script prints 0.0709, and arm B is 57% `gemini-3.5-flash-lite` while A1/A3 are 100% `gemini-3.1-flash-lite`, with no gate on the split. |
| 7 | "C4 transplant penalty 0.843 / 0.835 … FATAL, replicated to 0.008"; "Not length (C4's length-matched cell is 0.875, higher) … not retrieval quality — by cosine quartile 0.90/0.82/0.83/0.79" | T7, A19, A20 | Wilson CI [0.742, 0.899] straddles the 0.75 bar; the "replication" re-judges the identical seeded 100 items; the length-matched cell is 7 of 8 comparisons; the quartile table stratifies on a cosine against a text the judge never sees, and the docstring's call holdout is not implemented. |
| 8 | "Use `usable_item_fraction` … a mega-blob split cannot fool that" | T8 | It scores the `[1, 10, 394]` blob at **0.973** and the healthy case at 0.976 — no discriminating power. Adopting it would convert the current correct FAIL into a PASS. |
| 9 | "Retention is 107/245 clusters, **41.0% of turns**"; "coachable turn volume (35.1% vs 31.0%)" | A1 | Those are shares of the 12,582 *clustered* turns, not the 23,949-turn pool: 21.5% and 18.5% of the corpus. The 35.1%-vs-31.0% pair also uses two different denominators. |
| 10 | "the turn-mode taxonomy … 38 coachable" quoted against "live production 85/161 = 52.8%" | A2 | Production emits no row for a merged cluster, so the comparable denominator is 176, not 245: 21.6%, not 15.5%. The comparison is additionally confounded on embedder, pool unit, `min_cluster_size`, merge threshold and adjudicating model. |
| 11 | "An earlier 'the proxy was directionally wrong' verdict … is withdrawn" | A3 | Quantify: the printed 32/97 = 33% is 84/97 = **87%** correct, and the script still prints the wrong number today. |
| 12 | "Over 6,468 real CSM client turns: production accepts 46.7% as signals, the turn-mode taxonomy 35.6% … the two agree on 78% of turns" | A7, A35 | Against each taxonomy's own coachable base rate (52.8% vs 21.6%) the comparison inverts — turn mode is the more permissive taxonomy per entry. The turn population also includes 417 `Unknown Speaker` turns Layer D excludes. |
| 13 | "Turn mode strands **0** scenarios with no rubric (production strands 1)" | A37 | The two figures are different estimators (response-clause support vs client-turn call count); the NEW figure is a lower bound, not a count. |
| 14 | "3072 BEATS 768 for clustering … 3072 wins at every merge threshold from 0.92 up" | A18 | Compared at equal threshold, not equal cluster count; at matched surviving counts 768 leads at 183-vs-193 and the 0.92 gap disappears. |
| 15 | "`by_cluster` … beats its own placebo on lost (1 vs 6) and gained (4 genuine new milestones vs 0)" | A6, A30, A16 | The placebo perturbs 2.3x more distinct calls in this arm on matched clause volume, and the gate is call-keyed; the null is dispersed while the metric is a coherence test; "beats placebo" fires at 4-vs-0, below the ~6 noise floor. |
| 16 | "support jumps read as 'evidence thickening'" / `by_cluster` `support_thickened` | A4 | The thickening statistic still pools `merged` with `matched`: the 375 genuinely matched milestones move **+0.0007**; the printed +0.0102 is essentially the 8 merges. In `by_trigger_nonsink` pooling reverses the sign (matched −0.017 vs printed +0.113). |
| 17 | "47.3% of the sink pool is HDBSCAN noise, capping any cluster-based fix at ~53% of the problem" | A15, A32 | The volume-matched control clustered in the same run is 54.6% noise, and `min_cluster_size` was clamped to the ceiling 25 — the rate is a property of the clustering, not of the sink pool. |
| 18 | "two homeless topics with real support: `strategic_performance_consulting` (94 pairs/115 calls) and `technical_operational_alignment` (81/113)" | T4 | The call counts are union (sink + control) counts fed to the judge as sink evidence; sink-only ceilings are 94 and 81. This is the artifact that fed the production graduation of 4 scenarios / 164 pairs. |
| 19 | "cross-checked against the independent 150-pair labeled sample the two verdict families agree in the predicted direction — 21% / 71% / 80%" | A28 | Pooled across clusters of unequal size; cluster_4 (`genuine_sink`, 74 pairs) is 73% labeled-coachable and contradicts its verdict. Effective n is 9 clusters, not 84 pairs. |
| 20 | "the criteria rewrite's +0.025 is ~4.1x that band — it is real … 43 milestones improved, 17 worsened" | A8, A9 | The 43/17 shape is inflated by one-sided `FULL OUTER JOIN` rows landing in *improved*, and the arm has no duplicate-run guard while its +11.5% attempt drift sits just under the 15% gate. |
| 21 | "The noise band is ±0.006 weighted, and 15.6% of milestones (37/237) move on their own … 24 up / 13 down, net +2.12" | A10 | The denominator is the union of both runs' milestones, so coverage differences enter as signed movement; quote the intersection figure alongside. |
| 22 | "Finer granularity is BETTER … min 16 beats min 50 on coherence (84% vs 75%), coachability (38% vs 33%)" | A11 | z = 1.73 and z = 0.75; neither is significant, and the arms partition the same corpus. `partial` coherence verdicts are also scored as failures. |
| 23 | "`min_call_support_fraction`… `merge_cosine_threshold` on this backend is 0.97 … derived by READING groups" | A40 | The reading covered only the six largest clusters' first three members — a selection that makes over-merging maximally visible and under-merging invisible, biasing the threshold upward. |
| 24 | "Gemini's … turn-vs-turn spread is 0.130 vs bge's 0.141 — the compressed-space worry did NOT materialise" | A42 | 0.141 is bge's *trigger-vs-scenario* band; the correct bge turn-vs-turn reference is spread 0.116, against which gemini is wider and lower. Conclusion may stand, cited evidence does not. |
| 25 | "the four-arm trial's independent failure (1.04 / 0.89 / 1.09 against a fair same-model, same-clustering baseline, whose arms DO share a population)" | A22, A23, A24 | The arms do **not** fully share a population: generated arms silently drop null rows for skipped partners (616 vs 598 unrelated attempts), `arm0_baseline` alone is scored against 7 flagged-unhittable milestones (deflating its W by ~0.009), and arm 3's neighbour context is drawn from the sample (1.712 on 8 scenarios vs 0.889 on 18). |
| 26 | "Model provenance is recorded per verdict (`judged_by`) and per artifact (`models`) — do this in any future judge harness" | A46, A59, W2-C5 CLEAN note | Recorded but not gated: `_verdict` ignores `moments_sha`, model and blend when pooling M5; `trial_layer_c_arms` discards its `models` Counter and persists only rep 1's records; the blind-judge experiment records no judge prompt, model id or `judged_by` at all. |
| 27 | "`Brain/artifacts/sink_pool_clusters.json` … is a real *input*" | A50 | A `--no-gemma` or `--min-cluster-size` exploration run overwrites it in place, and the replay's `by_cluster` arm then runs as a no-op that reports the cleanest possible result. |
