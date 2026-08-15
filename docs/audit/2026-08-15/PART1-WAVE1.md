# PART 1 — WAVE 1 consolidation

## Wave 1 — the pytest suite

Six auditors (W1-T1 … W1-T6) covered all **34 files in `Brain/tests/`** (33 `test_*.py` +
`conftest.py`), grouped as: ego_trap scoring (T1, 4 files), parsing/pooling/infra (T2, 7 files),
Layer B matching (T3, 5 files), Layer A clustering/triage/config (T4, 5 files), Layer C
milestone/rubric-validation (T5, 5 files), and tests-of-the-harnesses (T6, 8 files). No pytest run;
one auditor (T2) ran a local spaCy tokenisation to pin token counts, and one (T4) read
`artifacts/sink_pool_clusters.json`.

**45 findings total: 41 certain, 4 likely, 0 purely speculative.** Six of the certain findings carry
an explicitly-scoped "likely" or "speculative" caveat on *magnitude* only (T1#4, T3#1, T4#4, T5#1,
T5#2, T5#7); their code facts are certain. The wave's dominant defect shape is not a wrong
calculation but a **test that cannot fail** — either asserting a tautology, asserting the
implementation against itself, or (twice) asserting that a known production defect is the intended
behaviour.

---

## CANDIDATE TOP FINDINGS

### C1. `flat_pick` and `topk_pick` do NOT agree, and the test that claims they do is built on the one input class where they cannot differ
- **File:line**: `Brain/tests/test_relative_match.py:149`
  (`test_flat_pick_matches_topk_pick_when_the_best_is_not_a_sink`); divergence at
  `Brain/shared/relative_match.py:89` vs `:113`, mirrored in production at
  `Brain/v1/layer_b.py:140-143`.
- **What is wrong**: `topk_pick` removes sinks **first** then applies the cap
  (`candidates = [j … if not is_sink]; candidates[:cap]`). `flat_pick` — and the byte-identical
  inline loop in production `assign_scenarios` — applies the cap **first** and filters sinks after
  (`for j in order[:cap] if … and not is_sink[j]`). A sink ranked inside the top-`cap` consumes a
  slot and a real scenario that clears the cutoff is dropped. The test asserts equality on
  `is_sink = [False, False, False]` — no sinks at all — so the only case where they can differ is
  excluded by construction. Counterexample: `sims=[1.0, 0.99, 0.98]`, `keys=[a,b,c]`,
  `is_sink=[F,T,F]`, `cap=2`, `margin=0.95` → `flat_pick` returns `["a"]`, `topk_pick` returns
  `["a","c"]`.
- **What number it corrupts, and in WHICH DIRECTION**: production `assign_scenarios` runs flat_pick
  semantics against a live map of 161 scenarios of which **76 are sinks**, at
  `max_scenarios_per_pair: 3`. Every pair with a sink at rank 2 or 3 loses a real co-label, so
  `kb_pairs.scenario_keys` width is **deflated** — the reported production match width
  "63% / 19% / 18% (one/two/three scenarios)" is biased toward "one". Downstream this narrows the
  multi-label pool `storage.get_responses_for_scenario_multilabel` reads (measured 2,904 → 5,463
  candidates for Layer D benchmark ranking). It also means `calibration/compare_sink_rescue.py`
  (calls `_flat_pick` as "today's behaviour") and Layer D (calls `topk_pick`) apply **two different
  cap rules** while the suite asserts they are the same rule.
- **Confidence**: certain that the two functions diverge and that the test cannot detect it;
  **likely** on the production magnitude (no DB query was run to count how often a sink lands in the
  top 3).
- **Cheapest way to verify**: the four-line counterexample in a scratch REPL against
  `shared.relative_match`. For magnitude:
  `SELECT array_length(scenario_keys,1), count(*) FROM kb_pairs GROUP BY 1;` against a snapshot,
  compared with a re-run of `assign_scenarios` using `topk_pick` semantics.

### C2. The ONLY test of `classify_response_outcome(...) == "none"` is built from two consecutive CLIENT turns — it enshrines the known 98.6% segmentation artifact as correct behaviour
- **File:line**: `Brain/tests/test_ego_trap_transcript_parser.py:105-108`
  (production: `Brain/ego_trap/transcript_parser.py:78-104`)
- **What is wrong**: the fixture is `"Anna\nSignal.\n\nAnna\nNo one responded before this next client
  turn.\n"` — turn 0 and turn 1 are both CLIENT. `turns_until_next_client(turns, 0)` breaks on the
  first iteration and returns `[]`, so `classify_response_outcome` returns `"none"` *by
  construction*, not because anybody failed to respond. The sibling test one function above
  (`:93-102`) documents `"none"` in its docstring as **"the true-silence 'none'"**, so the suite
  explicitly labels the artifact as true silence. CLAUDE.md measures the live consequence: of 2,484
  `none` outcomes, **2,449 (98.6%) are immediately followed by another CLIENT turn and 0 are genuine
  silence**. The 35 genuinely-silent last-turn-of-call cases are never tested — that fixture would
  have made the difference visible.
- **What number it corrupts, and in WHICH DIRECTION**: `"none"` routes to
  `gap_output.write_signal_recognition_failure` (`gap_output.py:200-230`) →
  `storage.upsert_signal_recognition_gap(..., recognized=False)` + a `Signal_Recognition_Failure`
  gap_event. The **`signal_recognition_gaps` missed count and the `Signal_Recognition_Failure`
  gap_event count are INFLATED by ~98.6%**, and the CSM recognition rate
  (`recognized / (recognized + missed)`) is correspondingly **DEFLATED**. Milestone hit rates are
  unaffected (only `"csm"` outcomes are scored). This test is precisely the mechanism by which the
  defect survived: the suite is green and asserts the wrong thing.
- **Confidence**: certain
- **Cheapest way to verify**: read `ego_trap/transcript_parser.py:84-89` alongside the fixture at
  `test_ego_trap_transcript_parser.py:106` — the second speaker is `Anna`, the same as the first.
  Then `grep -n 'recognized=False' Brain/ego_trap/gap_output.py`.

### C3. The scenario ship/hold/disable thresholds are pinned by a test that certifies them against the ceiling table CLAUDE.md retracted on 2026-08-15
- **File:line**: `Brain/tests/test_rubric_validation.py:165-171`; constants at
  `Brain/shared/rubric_validation.py:155-156`; duplicated at
  `Brain/calibration/validate_rubrics.py:102-103`.
- **What is wrong**: the test asserts `SCENARIO_MIN_ATTEMPTS == 15` and `SCENARIO_BAND == 0.05`, and
  its docstring states they are validated — *"at these values the ceiling run's published table comes
  back exactly — 40 qualifying scenarios, 16 discriminating, 7 zero-control, 7 inverted."* Those two
  numbers were **fitted** to reproduce that table. CLAUDE.md now records the ceiling's arm B as an
  arm-construction artifact: arm B scored `a1_sample` rows (primary-label, the strongest exemplars)
  while A3 drew secondary-label rows, so `W(B)=0.090` is an inflated null. Meanwhile
  `validate_rubrics._items_for` (`:219-246`) deliberately **fixed** that asymmetry — *"All three arms
  use THE SAME A3 responses"* — so `classify_scenario` runs a symmetric comparison through a band
  fitted on an asymmetric one. The test locks the mismatch in and asserts it is calibrated.
- **What number it corrupts, and in WHICH DIRECTION**: `scenario_verdicts` — the harness's own
  headline (`validate_rubrics.py:188`), printed as the SHIP/HOLD/DISABLE table by `_report_scenarios`.
  With a symmetric arm B the null drops (CLAUDE.md's leakage-clean `W(unrelated)` is 0.032–0.042 vs
  the ceiling's 0.090), so `gap = a3_w - b_w` is systematically **larger** than the population the
  band was fitted on. A band tuned to admit ~16 of 40 on deflated gaps admits **more** on inflated
  ones: **the SHIP count is inflated and the DISABLE count deflated.** The per-milestone constants at
  `:25-32` (`T_DISCRIMINATION`, `T_SATISFIABLE`) are pinned by the same test with the same inheritance
  ("Inherited from the ceiling spec's own gate") and carry the same problem. **Aggravating**:
  `_self_check` (`validate_rubrics.py:345-391`), the gate deciding whether verdicts are written to
  `rubrics.milestones` under `--apply` (`:794-806`), replays `artifacts/naren_ceiling.json`'s own
  records — so the instrument's validity proof is "does the symmetric measurement reproduce the
  asymmetric one's labels". `_self_check` has **no test at all**.
- **Confidence**: certain that the thresholds are fitted to the ceiling table and that `_items_for`
  uses a different arm construction than the ceiling; **likely** on the direction and magnitude of the
  SHIP inflation (it depends on the true symmetric `b_w` per scenario, unmeasured at scenario
  resolution).
- **Cheapest way to verify**: `grep -n "a1_sample\|a3_sample" Brain/calibration/score_naren_ceiling.py`
  to confirm arm B's source rows, then diff against `_items_for`'s `for row in sample:` loop. Then
  read `Brain/artifacts/naren_ceiling.json`'s `arms.B.records`.

### C4. `test_ego_trap_signal_check.py`'s tuning fixture is stale by two required fields — 14 of its tests cannot run at all
- **File:line**: `Brain/tests/test_ego_trap_signal_check.py:22-39` (fixture), vs
  `Brain/shared/tuning.py:77-104` (`LayerDTuning`)
- **What is wrong**: `LayerDTuning` is a frozen dataclass with **15 fields and no defaults**. Commit
  `4afa744` added `scoring_unit` and `scenarios_per_request`. The fixture's `base` dict supplies only
  the other 13, so `LayerDTuning(**base)` raises `TypeError: __init__() missing 2 required positional
  arguments`. `tests/test_ego_trap_gap_output.py:11-12` *was* updated in the same commit; this file
  was not (last touch `72dbe93`, earlier). Every test from
  `test_similarity_mode_detects_signal_and_response` (line 52) through
  `test_unknown_detection_mode_raises_rather_than_silently_picking_one` (line 225) calls `_tuning()` —
  14 tests. The pure `find_turn_index` / `resolve_signals` / `shortlist_scenarios` / `select_signal`
  tests below line 232 do not and still run.
- **What number it corrupts, and in WHICH DIRECTION**: nothing today, but it removes every guard on
  the rule that sets **`milestone_performance.attempts`** — the denominator of every weighted score
  this project reports. The 14 dead tests are exactly the ones pinning *"a client turn is a signal iff
  its best match is coachable rather than a sink"*, which `tuning.yaml` documents as the sole
  accept/reject mechanism in the shipped `similarity` mode. A regression admitting sink-matched turns
  would **inflate `attempts`, deflate `W`**, and nothing would fail.
- **Confidence**: certain (proved by field-count comparison and `git log` on both files; no conftest
  or fixture override exists — `grep LayerDTuning` returns only these two test files).
- **Cheapest way to verify**: `git log --oneline -1 -- Brain/tests/test_ego_trap_signal_check.py`
  (→ `72dbe93`) vs `git log --oneline -1 -- Brain/shared/tuning.py` (→ `4afa744`), then diff the 13
  fixture keys against the 15 `LayerDTuning` fields.

### C5. `verify_evidence`'s tests assert against an invented speaker vocabulary that exists in neither production enum — so the role filter could never be tested, and it was wrong
- **File:line**: `Brain/tests/test_call_scoring.py:45-50` (the `TURNS` fixture) and `:231-254`
  (`csm_roles=("CSM",)`), against `Brain/ego_trap/call_scoring.py:190` (default `("NAREN", "CSM")` at
  HEAD) and `Brain/calibration/trial_call_scoring.py:309,351`.
- **What is wrong**: `verify_evidence`'s only production caller builds turns as `(t.role.name, t.text)`
  from **`preprocessing.transcript_parser.SpeakerRole`**, whose members are `NAREN` / `JOVEO_OTHER` /
  `CLIENT` (`preprocessing/transcript_parser.py:9-12`). There is no `CSM` member and no `OTHER_JOVEO`
  member — those belong to the *other*, unrelated `ego_trap.transcript_parser.EgoTrapRole`. The
  fixture uses speaker strings `"Client"` and `"CSM"` and every role-sensitive test passes
  `csm_roles=("CSM",)`, so the suite validates the function against a role space production never
  produces. This is taxonomy #4 with the test **agreeing with the bug rather than catching it**. The
  working tree's new docstring (`call_scoring.py:207-210`) confirms the consequence: *"v1 asked for
  `OTHER_JOVEO` when the member is `JOVEO_OTHER`, and for `CSM`, which does not exist at all — so the
  filter silently admitted only NAREN, rejected 24% of cited turns on a transposition, and raised
  nothing."*
- **What number it corrupts, and in WHICH DIRECTION**: **check 2 of the call-scoring gate**
  (`verified/checked`, bar ≥ 0.95, `trial_call_scoring.py:76,174`). The transposition **deflates** it —
  `across_turns` credits citing genuine `JOVEO_OTHER` turns were scored as unevidenced (24% of cited
  turns). Separately, at HEAD the `at_turn` branch performed **no role check at all**
  (`call_scoring.py:228-233`, HEAD), so a credit quoting the *client* back verified — which
  **inflates** the same rate (12 such credits). Two errors in opposite directions in one pooled rate;
  no test constrains either.
- **Confidence**: certain for the enum mismatch and the absent `at_turn` role check (read directly
  from both modules and from the harness's
  `roles = tuple({r for r,_ in turns} & {"NAREN","CSM","OTHER_JOVEO"})` at
  `trial_call_scoring.py:351`, which can only ever evaluate to `("NAREN",)`). The 24%/12-credit
  magnitudes are quoted from the working-tree docstring, not independently re-measured.
- **Cheapest way to verify**:
  `grep -n "class SpeakerRole" -A4 Brain/preprocessing/transcript_parser.py` and compare with the
  literals at `Brain/calibration/trial_call_scoring.py:351` and the `csm_roles=` calls in the test.

### C6. `test_naren_ceiling.py` does not test arm CONSTRUCTION at all — it could never have caught the asymmetry that forced the 1.2:1 retraction
- **File:line**: `Brain/calibration/score_naren_ceiling.py:367-398` (`_build_items`);
  `Brain/tests/test_naren_ceiling.py` (whole file)
- **What is wrong**: the retracted defect lives in `_build_items`: `a1_sample` feeds **both**
  `items["A1"]` and `items["B"]` (lines 391-395), while `items["A3"]` is fed from a separate
  `a3_sample` drawn from a different pool (lines 396-397). The test file exercises `weighted`,
  `a3_eligible`, `hold_out`, `pick_benchmark`, `take_sample`, `derange`, `aggregate`, `arm_totals`,
  `unhittable` and three module constants. **`_build_items` and `_item` are never imported or
  called.** Nothing asserts which pool each arm draws from, nothing asserts the three arms'
  populations are comparable, and nothing constrains the gate `W(B) >= _T_INSTRUMENT * W(A3)`
  (`score_naren_ceiling.py:508`) which compares across the population boundary. Plainly: this file
  tests helper arithmetic only.
- **What number it corrupts, and in WHICH DIRECTION**: the published signal-to-null ratio **1.2 : 1**
  (A3/B). Because arm B was built from primary-label rows (the strongest exemplars) while A3 drew
  secondary-label rows, the null `W(B)=0.090` is **inflated** and the ratio is therefore **deflated** —
  exactly the direction that produced the false "the scorer cannot discriminate" conclusion later
  retracted at 2.9/2.1 : 1. The test suite offered zero resistance to this and would offer zero
  resistance to a repeat.
- **Confidence**: certain (the absence of coverage is directly checkable)
- **Cheapest way to verify**: `grep -n "_build_items\|_item(" Brain/tests/test_naren_ceiling.py` → no
  matches.

### C7. `usable_item_fraction` does NOT have the property CLAUDE.md credits it with, and the test file demonstrates that side by side without noticing
- **File:line**: `Brain/calibration/trial_skills.py:136-150`; tests
  `Brain/tests/test_trial_skills.py:102-118`
- **What is wrong**: the function's docstring says *"A mega-blob split scores near zero here"*, and
  CLAUDE.md records it as the fix for the median's small-K blind spot (*"a mega-blob split cannot fool
  that"*). It computes `sum(size for g if size >= floor) / total`, so the 394-item blob is itself
  above the floor and **counts as usable**. The test named
  `test_a_mega_blob_split_scores_near_zero_usable_items` asserts `== approx(394/405) = 0.973`, i.e.
  *near ONE* under a name that says *near zero*, and the next test,
  `test_a_healthy_split_puts_most_items_on_usable_axes`, asserts `83/85 = 0.976`. **The pathological
  case and the healthy case score within 0.003 of each other** — the metric cannot separate the two
  situations it was built to separate (taxonomy item 5). The test's only discriminating assertion
  (`sum(g["size"] for g in groups if 12 <= g["size"] < 100) == 0`) is arithmetic performed in the test
  itself over a literal list; it calls nothing in the module.
- **What number it corrupts, and in WHICH DIRECTION**: `usable_item_fraction` is **never called
  anywhere** — grep returns only its definition and its three tests; the report and `evaluate_window`
  use `n_skills` + `median_size` only. So no published number is wrong *today*. What is wrong is the
  recorded claim in CLAUDE.md that the median blind spot is guarded: it is not, by a dead function
  that would have **inflated** the apparent health of a one-blob-plus-singletons split to ~0.97 had it
  been wired in. Any future re-run of `trial_skills` adopting this metric would read the documented
  failure shape as a pass.
- **Confidence**: certain (arithmetic, verifiable by hand from the test's own literals)
- **Cheapest way to verify**: `grep -rn "usable_item_fraction" Brain/ --include=*.py` → 1 definition,
  3 test lines, 0 call sites; then read `trial_skills.py:136-150` against
  `test_trial_skills.py:102-118`.

---

## ALL FINDINGS

Ranked worst first. 37 entries (the `layer_d.scoring_unit` finding was reached independently by two
auditors and is consolidated into one entry).

### 1. `graduate_sink_topics._graduate_one` COMMITS a partial reroute before checking the row count, and its test asserts only that an exception is raised
- **File:line**: `Brain/calibration/graduate_sink_topics.py:196-213`; test
  `Brain/tests/test_graduate_sink_topics.py:130-143`
- **What is wrong**: `conn.commit()` is on line 207, the `rerouted != len(pair_ids)` check on 209, and
  the `RuntimeError` — whose message says *"aborting before Layer C runs on a possibly-wrong pair
  set"* — on 210. The wrong pair set is **already committed** when it raises; no rollback, no
  try/except. The test asserts only `pytest.raises(RuntimeError, match="rerouted 2")`. Its sibling
  `test_response_taxonomy_auto_pass.py:261-284` asserts `conn.rollback.assert_called()` **and**
  `conn.commit.assert_not_called()` against `response_taxonomy_auto_pass.py:300-331`, which genuinely
  does roll back — the correct assertion pair exists in this repo and was simply not applied here.
- **What number it corrupts, and in WHICH DIRECTION**: `kb_pairs.scenario_key` / `scenario_keys[]` for
  an unknown subset of graduated pairs, plus the new scenario's `support_calls` / `support_clauses` /
  `call_coverage` written just above from the *intended* pair list. A short reroute leaves the scenario
  row claiming **more** evidence than the pairs actually filed under it. This script graduated the two
  homeless topics on 2026-08-07/08, so a silent partial would sit in `public` today with no error
  visible after the fact.
- **Confidence**: certain for the code ordering; the blast radius is conditional on a partial reroute
  ever having occurred (untested; stdout would have printed `rerouted N (expected M)` before raising).
- **Cheapest way to verify**: read `graduate_sink_topics.py:207-213`; then
  `grep -n "rollback\|commit" Brain/tests/test_graduate_sink_topics.py`.

### 2. An unrecognised adjudication `decision` string silently becomes a COACHABLE scenario, and nothing tests it
- **File:line**: `Brain/v2/layer_a.py:531-532`
  (`_KIND_BY_DECISION.get(decision, cluster_evidence.KIND_SCENARIO)`), and `:530`
  (`decision = (result.get("decision") or "new_scenario").strip()`)
- **What is wrong**: the prompt's four literals (`merge_into` / `mechanics` / `not_coachable` /
  `new_scenario`, `shared/prompts.py:852-860`) *do* match `_KIND_BY_DECISION`'s keys — no
  name-never-matches bug today. The defect is the **default**: any variant the model emits
  (`"Mechanics"`, `"logistics"`, `"sink"`, a missing field) falls through to `KIND_SCENARIO`, hence
  `is_coachable = True`, hence a rubric is generated. No counter, no warning, no test —
  `_KIND_BY_DECISION` appears nowhere under `tests/`. The safe default is the sink (a wrongly-sunk
  cluster costs one topic; a wrongly-coachable one manufactures a rubric and Layer D coaching output),
  and the code chose the opposite direction, unguarded. The `merge_into` hallucination path one branch
  up (`:508-514`) *does* print a warning — the pattern was recognised there and not here.
- **What number it corrupts, and in WHICH DIRECTION**: **inflates** `n_coachable` (the headline "85
  coachable / 76 sinks") and therefore the rubric count. CLAUDE.md already records that coachability
  adjudication is not reproducible across runs — 78 vs 85 for byte-identical clusters, "not
  root-caused". This silent default is a candidate contributor no test would surface.
- **Confidence**: certain about the code path and its direction; **speculative** about whether it
  actually fires on this corpus (needs the run logs, not run).
- **Cheapest way to verify**: `grep -rn "_KIND_BY_DECISION\|not_coachable" Brain/tests/` → no hits;
  then compare the `+`/`~` marker counts in `Brain/logs/run_full_pipeline_*.log` against the printed
  decision reasons.

### 3. `test_shipped_tuning_yaml_is_valid`'s range whitelist omits the two most load-bearing calibrated knobs while covering six knobs of a strategy that was never adopted
- **File:line**: `Brain/tests/test_tuning.py:88-127`
- **What is wrong**: `load_tuning` validates **keys only, never values** (`shared/tuning.py:125-138`),
  so this test is the entire value-sanity gate on the shipped file — and it is a hand-maintained
  whitelist. It asserts bounds for `sink_rescue_relative_margin`,
  `sink_rescue_response_min_similarity`, `sink_rescue_trigger_weak_floor`, `sink_rescue_blend_alpha`,
  `sink_rescue_density_threshold`, `sink_rescue_density_min_words` (all six belong to
  `sink_rescue_strategy: none`, never adopted) and **omits** `layer_b.relative_margin` (a 0–1
  fraction, the most-swept knob in the file) and `layer_c.milestone_relevance_percentile` /
  `layer_c.milestone_sink_similarity_percentile` (0–100 percentiles sitting next to 0–1 fractions in
  the same section). A decimal-point slip is silent: `relative_margin: 95` makes
  `flat_pick`'s `cutoff = 95 * sims[best]` unreachable, so `kept` is always empty and the
  `kept or [keys[best_j]]` fallback fires for **every** pair — the run completes with no error.
- **What number it corrupts, and in WHICH DIRECTION**: `relative_margin` slip →
  `kb_pairs.scenario_keys[]` collapses to one entry per pair, so the published match-width
  distribution (63%/19%/18%) becomes 100%/0%/0% and multi-label recall **deflates** to zero,
  invisibly. `milestone_relevance_percentile: 0.40` → the relevance filter stops filtering and
  milestone counts **inflate** (partially caught downstream: `milestone_hard_cap` logs loudly, so this
  is the lesser of the two).
- **Confidence**: certain (the omissions and the loader's key-only validation are direct code facts;
  the collapse behaviour read off `shared/relative_match.py:112-117`).
- **Cheapest way to verify**:
  `grep -n "relative_margin\|milestone_relevance_percentile" Brain/tests/test_tuning.py`.

### 4. `test_segmenter.py` pins the `len(sent) < 4` cutoff only from BELOW — it could be raised from 4 to 13 with the whole suite green
- **File:line**: `Brain/tests/test_segmenter.py:4-26` (production: `preprocessing/segmenter.py:23-25`)
- **What is wrong**: measured token counts (spaCy `en_core_web_lg`, run locally): `"K."` 1, `"Yeah."`
  2, `"I mean."` 3 (the ONLY thing pinning the floor); multi-idea sentences 13 / 11 / 16 asserted with
  `>= 2`; normal sentence 15 asserted `== 1`. A cutoff of `< 4` is required from below (at `< 3`,
  `"I mean."` survives and the test fails), but **any value from 4 up to and including 13 leaves every
  assertion true** — `assert >= 2` on a three-sentence input keeps passing while the 11-token sentence
  is silently discarded. No test asserts any sentence at or just above the boundary is KEPT.
  `"That makes sense."` is **exactly 4 tokens** — CLAUDE.md names it as the de-facto posture filter's
  boundary case (630 occurrences, the raw material for `client_expresses_uncertainty`) — and moving the
  cutoff 4 → 5 deletes it from the pool with the suite still green. Secondary:
  `test_multi_idea_utterance` asserts `>= 2` where the correct answer is 3, so a segmenter that fused
  two sentences also passes.
- **What number it corrupts, and in WHICH DIRECTION**: `segment_into_clauses` is shared by
  `v2/layer_a.py:68` and `v2/layer_c.py:77`. An unnoticed upward drift **deflates** the clause-pool
  size (73,771 items), **deflates** the measured content-free share (59.1% — short filler goes first),
  and shifts the Layer C milestone pool, silently changing both the taxonomy and the 385–405 milestone
  baseline.
- **Confidence**: certain (token counts measured, not inferred)
- **Cheapest way to verify**: `python -c "import spacy; n=spacy.load('en_core_web_lg');
  print([(s.text,len(s)) for s in n('That makes sense. Got it.').sents])"` → `4` and `3`.

### 5. The segmenter's 4-token cutoff is claimed to be "pinned by its own test" and is not — the test survives any cutoff from 1 to 6
- **File:line**: `Brain/tests/test_layer_c_clause_pool.py:8-12` (the claim), `:22-28` (the test); real
  filter at `Brain/preprocessing/segmenter.py:23`.
- **What is wrong**: the test asserts only `segment_into_clauses("Sure.") == []` (2 tokens) and
  `len(segment_into_clauses(_ONE_SENTENCE)) == 1` (8 tokens). It never touches the boundary. Token
  counts: `_ONE_SENTENCE` 8; `_THREE_SENTENCES` = 7 / **6** / 7. Changing `< 4` to `< 5` or `< 6`
  leaves **every assertion in the file passing**; the file first breaks at `< 7`, where the 6-token
  middle sentence drops and `test_four_lists_stay_index_aligned` fails.
- **What number it corrupts, and in WHICH DIRECTION**: the Layer C clause pool size, and therefore the
  milestone count (the ~385/398/404 band) and every milestone's `support_clauses`. Raising the cutoff
  **deflates** both, silently. The module docstring's assurance that the filter is *"pinned by its own
  test below rather than left as a trap for the next person"* is the specific thing that is false.
- **Confidence**: certain (token counts are mechanical; spaCy tokenises trailing `.` as its own token).
- **Cheapest way to verify**: read `preprocessing/segmenter.py:23` and count tokens in the three
  fixture sentences at `test_layer_c_clause_pool.py:16-19`.

### 6. `test_drift_across_three_runs_shrinks_to_the_stable_core` calls nothing, and graduation's `stable_pair_ids` read is unpinned — a regression to the latest snapshot would pass
- **File:line**: `Brain/tests/test_response_taxonomy_auto_pass.py:101-107` and `:170-171`; module
  `Brain/response_taxonomy_auto_pass.py:257`
- **What is wrong**: two holes in Decision 2. (a) `test_drift_across_three_runs_shrinks_to_the_stable_core`
  is three lines of set intersection written **in the test body**
  (`stable = {1,2,3} & {2,3,4} & {3,4,5}`) then `assert stable == {3}`. It imports nothing from `rtap`
  and would pass if the entire module were deleted — it tests Python's `&` operator. (b)
  `_attempt_graduation` reads `tracking_row["stable_pair_ids"]` (line 257), never `member_pair_ids` —
  the whole point of Decision 2 — but the fixture `_consensus_row(pair_ids)` sets both fields to the
  **same list** (line 171), so every graduation test is blind to which is read. Changing line 257 to
  `member_pair_ids` passes the entire suite. The *upsert* half IS genuinely pinned by
  `test_match_intersects_stable_pair_ids_not_just_overwrites` (asserts `params[1] == [2, 3]`).
- **What number it corrupts, and in WHICH DIRECTION**: the count of pairs a candidate graduates with,
  and hence the new scenario's `support_calls` / `support_clauses` / `call_coverage`. Regressing to
  `member_pair_ids` **inflates** all three by admitting pairs that appeared in only the most recent
  noisy clustering run — precisely the UMAP instability the intersection exists to filter. Published
  figure at risk: the 2026-08-08 run's "**164 pairs rescued**".
- **Confidence**: certain
- **Cheapest way to verify**: change `stable_pair_ids` to `member_pair_ids` at
  `response_taxonomy_auto_pass.py:257` and observe no test references the two fields differently.

### 7. `classify_scenario` SHIPs on a zero control with no minimum effect size, and the only test of that path uses a case where the band would have passed anyway
- **File:line**: `Brain/shared/rubric_validation.py:179-184`; blessed by
  `Brain/tests/test_rubric_validation.py:173-177`.
- **What is wrong**: `control_is_zero = b_w == 0.0 and a3_w > 0`, then
  `elif control_is_zero or gap > band: SHIP`. `a3_w > 0` is the *only* floor — a single partial hit
  across 48 attempts gives `a3_w = 0.0104` and ships the rubric, bypassing the ±0.05 band.
  `test_a_scenario_whose_control_finds_nothing_ships` exercises it with 48 attempts / 13 hits
  (`a3_w = 0.271`, gap +0.271), which clears the band on its own — the test demonstrates nothing about
  the exception it is named for. No test probes small `a3_w` with a zero control.
- **What number it corrupts, and in WHICH DIRECTION**: the SHIP count in `_report_scenarios`,
  **inflated**. Not hypothetical at the configured floor: `SCENARIO_MIN_ATTEMPTS = 15`, and CLAUDE.md's
  leakage-clean corpus `W(matched)` is 0.089–0.095 with the null lower still, so `b_w == 0.0` at 15–20
  attempts is a routine sampling outcome rather than evidence of a working instrument. Each such
  scenario ships with `verdict == "ship"` while the printed annotation (`mark = verdict + " *"`) tells
  the reader to *"read the verdict column"*, not the asterisk.
- **Confidence**: certain about the code path and the test's non-coverage; **likely** about the
  frequency (exact rate depends on per-scenario `b_w`, unmeasured).
- **Cheapest way to verify**: read `Brain/artifacts/rubric_validation.json`'s `scenario_verdicts` and
  count rows with `control_is_zero: true` whose `gap` is below 0.05.

### 8. `scenario_verdicts` — the headline function — has no test, and the only fixture touching arm-B identity encodes the opposite convention from production
- **File:line**: `Brain/tests/test_validate_rubrics.py:25-28` (`_rec`), used for arm B at `:99, :146,
  :167`; untested production function at `Brain/calibration/validate_rubrics.py:187-205`.
- **What is wrong**: `scenario_verdicts` groups **both** arms by `r["scenario_key"]`, and its
  correctness rests entirely on the invariant in its docstring — *"which in BOTH arms is the scenario
  whose RUBRIC was scored, never the response's own."* That invariant lives one file away in
  `score_naren_ceiling._item` (`:410-412`: `"scenario_key": rubric_key`) and is **not asserted
  anywhere**. The test file's B fixtures do the opposite: `_rec(i, "other", 10, "M1", ...)` pairs
  `rubric_id=10` (scenario `"s"`'s rubric) with `scenario_key="other"`. The drift is invisible because
  `build_verdicts` keys off `(rubric_id, milestone_id)` and overwrites `scenario_key` from the A3
  counter (`:175`).
- **What number it corrupts, and in WHICH DIRECTION**: today, nothing — production is correct. The
  defect is that **the invariant is unprotected while the fixture teaches the wrong one.** If `_item`
  ever recorded the response's own scenario (what the fixture models), every arm-B record would be
  filed under the wrong scenario, each rubric's `b_w` computed from a different rubric's null, and
  every SHIP/HOLD/DISABLE verdict wrong — with no test failing and the report looking normal.
  Direction arbitrary per scenario, i.e. the worst kind.
- **Confidence**: certain (both facts read directly from source).
- **Cheapest way to verify**: `grep -n "scenario_key" Brain/calibration/score_naren_ceiling.py` —
  line 412 is the only assignment; then `grep -n "scenario_verdicts" Brain/tests/` returns nothing.

### 9. `test_matches_the_two_known_graduated_clusters` is a duplicate of the test six lines above it and cannot detect either drift it claims to detect
- **File:line**: `Brain/tests/test_cluster_evidence.py:184-190` (compare `:177-178`)
- **What is wrong**: the test's comment says *"If this ever goes False, something upstream
  (embeddings, merge_cosine_threshold) has drifted … and graduation must not proceed on stale
  confidence."* Both inputs are literals: similarity `0.726` / `0.742` and threshold `0.85`. It never
  reads `artifacts/sink_pool_clusters.json` (where those similarities live) and never reads
  `layer_a.merge_cosine_threshold` from `tuning.yaml` (what the production callers pass —
  `calibration/graduate_sink_topics.py:154`, `response_taxonomy_auto_pass.py:275`).
  `passes_reconciliation_gate` is one `<` expression, so the assertion reduces to `0.726 < 0.85`,
  byte-identical to `test_true_when_comfortably_below_threshold` on line 178. If
  `merge_cosine_threshold` moved to 0.70, or the embedding backend moved (gemini's centroid band p50
  0.810), both clusters would fail the *real* gate in production and this test would still be green.
  Verified the literals correspond to the artifact: `clusters[5].nearest_coachable_sim = 0.72563886…`,
  `clusters[8].nearest_coachable_sim = 0.74154794…` — transcribed once and frozen.
- **What number it corrupts, and in WHICH DIRECTION**: the count of scenarios graduated out of the
  sink pool, and the `kb_pairs` rerouted with them (the real run graduated 4 scenarios / 164 pairs).
  With the guard's only test inert, a threshold or embedding change **inflates** the
  graduated-scenario count and silently re-routes pairs into near-but-wrong scenarios. It also gives
  false assurance in the opposite direction: nothing would flag a threshold change that made the gate
  reject both known-good candidates.
- **Confidence**: certain (that the test cannot fail as documented; the downstream damage is the
  documented purpose of the gate, not observed).
- **Cheapest way to verify**: `python -c "import json;d=json.load(open('Brain/artifacts/sink_pool_clusters.json'));print([round(c['nearest_coachable_sim'],3) for c in d['clusters']])"`
  — then note neither that file nor `shared.tuning.load_tuning` is imported in
  `tests/test_cluster_evidence.py`.

### 10. "High coverage is a review FLAG, never a rejection" is pinned only inside `triage()`; the caller that could reintroduce reject-on-coverage has zero test coverage
- **File:line**: `Brain/tests/test_cluster_evidence.py:86-90` (the good part) vs
  `v2/layer_a.py:489-500` and `:261-269` (untested)
- **What is wrong**: `test_ubiquitous_cluster_is_flagged_for_review_not_condemned` genuinely
  constrains `triage()` — that half is clean. But the *policy* lives in two places the suite never
  touches: (1) `v2/layer_a.py:494` — `if verdict == cluster_evidence.INSUFFICIENT_EVIDENCE: continue`.
  Changing that to `if verdict != SCENARIO_CANDIDATE: continue` reintroduces reject-on-coverage
  exactly and **the entire pytest suite still passes** (`run_layer_a_v2` is called from nowhere in
  `tests/`). (2) `v2/layer_a.py:261-269` — the `NEEDS_REVIEW` → `coverage_note` branch that puts the
  FLAGGED warning into `PROMPT_LAYER_A_V2_TRIAGE`. If the two branches were swapped, every ubiquitous
  cluster would be told *"coverage is within the normal range for a specific scenario"* and the audit
  signal would be gone from the prompt, with no test and no visible symptom.
- **What number it corrupts, and in WHICH DIRECTION**: (1) **deflates** the coachable scenario count
  by dropping the `NEEDS_REVIEW` band before adjudication — `tuning.yaml:44-49` records that band as
  15 of 171 clusters, of which **4 are real business topics** (budget/spend 74%, client/customer 72%,
  API/XML/SFTP 64%, Joveo 63%). (2) inverts the LLM's guidance on precisely those 15, again
  **deflating** the coachable count.
- **Confidence**: certain (coverage gap verifiable by grep; magnitude from `tuning.yaml`'s own
  measured numbers).
- **Cheapest way to verify**: `grep -rn "run_layer_a_v2\|coverage_note" Brain/tests/` → no hits.

### 11. `test_margin_is_inert_at_cap_one` cannot fail, and does not pin the claim its docstring cites
- **File:line**: `Brain/tests/test_relative_match.py:104`
- **What is wrong**: the test hardcodes `cap=1`. At `cap=1`, `candidates[:1]` is always the single
  best non-sink and `sims[best] >= margin * sims[best]` holds for every `margin <= 1` — the assertion
  is a tautology of `topk_pick` holding unconditionally, for any sims, any margin, forever. The claim
  it says it protects is a **configuration** claim: `tuning.yaml:588` "INERT AT
  `max_scenarios_per_signal: 1`". Nothing asserts that config value is 1 — `tests/test_tuning.py:115`
  only asserts `max_scenarios_per_signal >= 1`. Raise `layer_d.max_scenarios_per_signal` to 2 and the
  tuning.yaml note becomes false, Layer D's signal count starts moving with
  `similarity_relative_margin`, and this test plus every other test in the repo still passes.
- **What number it corrupts, and in WHICH DIRECTION**: no number today. The defect is false
  assurance: `topk_pick` via `select_signal` is **live** in shipped Layer D
  (`signal_detection_mode: similarity`, `ego_trap/signal_check.py:326-330`) and produced the reported
  "79 signals at every margin 0.85→0.99", the 60.7% sink-rejection rate and the 4,181-attempt 100-call
  run. The guard the documentation points at would not catch the change that invalidates them.
  Taxonomy item 5.
- **Confidence**: certain.
- **Cheapest way to verify**: `grep -rn "max_scenarios_per_signal" Brain/tests/`.

### 12. Every test in `TestAdjacentRankPair` passes if the adjacency constraint is deleted
- **File:line**: `Brain/tests/test_head_to_head.py:189-209`; function
  `Brain/shared/head_to_head.py:155-175`
- **What is wrong**: `adjacent_rank_pair` exists to require *rank adjacency* as well as closeness, "or
  the control would measure retrieval rank rather than the judge". Replacing the adjacency loop with a
  plain all-pairs-tightest search returns the identical answer on all five test cases:
  `[0.90,0.88,0.60,0.59]`→(2,3); `[0.50,0.71,0.70]`→(1,2); `[0.90,0.50,0.10]`→None;
  `[0.80,0.60,0.79]`→(0,2). `test_only_adjacent_ranks_qualify` has a docstring describing indices 0
  and 2 as "rank 1 and rank 3 … not adjacent" — but the function sorts by **similarity**, so 0.80 and
  0.79 are ranks 1 and 2, i.e. adjacent. The case contains no non-adjacent temptation at all.
- **What number it corrupts, and in WHICH DIRECTION**: control **C2 (expert vs expert), reported at
  0.582 and 0.543** against a validity band of [0.40, 0.60]. If adjacency silently broke, C2 would
  pair a top-ranked expert reply against a much lower-ranked one, giving the higher-ranked side a fit
  advantage and pushing C2 **up**, out of its band — or, worse, keeping it inside the band by luck
  while no longer measuring judge symmetry. C2 is one of the four pre-registered controls the design's
  verdict rests on.
- **Confidence**: certain (checkable by hand on the four literal `sims` lists)
- **Cheapest way to verify**: run all-pairs-tightest over the four `sims` lists at
  `test_head_to_head.py:192, 196, 200, 209`.

### 13. Nothing in `tests/` covers `trial_head_to_head.py`, so the trigger/response filter symmetry is unpinned
- **File:line**: `Brain/calibration/trial_head_to_head.py:180` (trigger side) and `:237, :801`
  (response side); `Brain/tests/test_head_to_head.py` imports only `shared.head_to_head` and
  `shared.prompts`
- **What is wrong**: the recorded bug — `_is_substantive` applied to the CSM's trigger but not the
  CSM's response, while `layer_b.extract_pairs` filters **both** sides — was fixed in the harness, and
  documented at length in `_attach_responses`'s docstring (`:215-226`). It is enforced by two
  independent statements far apart in the file: `s["csm_response_substantive"] = _is_substantive(...)`
  at line 237, and the filter `signals = [s for s in signals if s["csm_response_substantive"]]` at
  line 801 inside `main()`. Deleting line 801 restores the original bug in one line, with no test
  failure — `grep -rn "trial_head_to_head" Brain/tests/` returns nothing. The only defence is a
  printed counter (`dropped, reply not substantive`) a reader must notice.
- **What number it corrupts, and in WHICH DIRECTION**: the headline W3 win rate and controls C1
  (0.669) / C4 (0.835). Losing the response-side filter re-admits ~19.8% of CSM replies as filler
  against structurally-substantive expert replies, **inflating the expert's win rate**, and moves the
  median log length ratio back from −0.34 toward −0.68. The harness is otherwise well guarded here;
  this is a coverage gap, not a live defect.
- **Confidence**: certain that the coverage is absent; the number impact is the already-measured
  19.8% / −0.68-vs-−0.34 figures from CLAUDE.md.
- **Cheapest way to verify**: `grep -rn "trial_head_to_head" Brain/tests/` → no matches.

### 14. The production roster path of `preprocessing/transcript_parser.py` has ZERO test coverage — every test in the batch calls `parse_transcript` with `roster=None`
- **File:line**: `Brain/tests/test_transcript_parser.py:15-55` (production:
  `preprocessing/transcript_parser.py:24-66`, caller `v2/pipeline.py:22-25`)
- **What is wrong**: `v2/pipeline.py` **always** passes `roster=load_roster(str(txt_path))`, and the
  sidecars exist for the live corpus (1,945 speaker entries). All six tests call
  `parse_transcript(txt, JOVEO, NAREN)` with the default `roster=None`, so `load_roster`,
  `_match_roster_entry` and the entire roster branch of `_classify` (lines 51-59) are never executed
  by any test in the repo — `grep -rn roster tests/` returns nothing. What the suite verifies is the
  *fallback* heuristic production does not use for this corpus. A concrete latent bug in that untested
  branch: line 55 requires `s == name_l` (exact string equality with the roster name) before returning
  `NAREN`, while `_match_roster_entry` matches on prefix — so a transcript line reading `"Naren"`
  against a roster entry `"Naren Shankar"` matches the roster, fails the equality, and falls through
  to `SpeakerRole.JOVEO_OTHER` because `is_rep` is true; his responses would never enter `kb_pairs`.
  Checked: `grep -rlx "Naren" recordings/*.txt` returns 0 files, so this is **latent, not currently
  live**.
- **What number it corrupts, and in WHICH DIRECTION**: nothing today. What is corrupt is the
  *assurance*: the CLIENT-turn count (23,949), the clause-pool size and every Layer A coverage figure
  derive from a code path with no test at all, and the known failure mode inflates CLIENT turns by
  ~20% (CLAUDE.md: 28,905 vs the true 23,949).
- **Confidence**: certain (that the path is untested); the NAREN mis-classification is certain as code
  behaviour, latent as impact.
- **Cheapest way to verify**: `grep -rn "roster" Brain/tests/` → no hits;
  `grep -n "roster" Brain/v2/pipeline.py` → line 24.

### 15. The situated-fields treatment can silently degrade to the production prompt, and a test asserts that the degradation is quiet
- **File:line**: `Brain/ego_trap/milestone_scoring.py:299-317` (the `emitted` fallback) and
  `Brain/tests/test_ego_trap_milestone_scoring.py:715-729`
  (`test_missing_situational_values_degrade_quietly`)
- **What is wrong**: `score_milestones_batch` raises on an unknown *field name* but silently omits a
  *field with a missing value* — a v1 rubric has no `label`, an item may carry no `client_utterance`
  or `scenario_key`. If nothing was emitted, the code falls back to
  `PROMPT_STEP3_MILESTONE_SCORE_BATCH`, i.e. the byte-identical production prompt. `emitted` is
  computed and then discarded: never returned, printed or counted. The test pins this as correct and
  asserts only that the fields are absent; nothing reports **how many exchanges actually received the
  treatment**. Taxonomy #10.
- **What number it corrupts, and in WHICH DIRECTION**: the published grader-inputs result —
  *"discrimination 6.00 (blind) → 6.64 (turn) / 4.48 (label) / 5.84 (all three), heavily overlapping
  CIs, no ordering"* — which CLAUDE.md cites as refuting DEFECT 2. A treatment arm whose dose is
  partly zero is biased **toward the null**, precisely the reported result. The fraction of that
  trial's items lacking a `label` was not measured; the point is that the instrument cannot tell you,
  by construction.
- **Confidence**: likely. The code path is certain; whether it fired in the `trial_grader_inputs.py`
  run is unmeasured (that harness is another wave's file).
- **Cheapest way to verify**: read `milestone_scoring.py:299-317` — `emitted` has no consumer outside
  the `if emitted:` branch — then check whether `trial_grader_inputs.py` supplies `label` for
  v1-fallback rubrics.

### 16. `test_ranking_does_not_embed_when_the_pool_already_fits` blesses the silent short-circuit that already destroyed one measurement; no test asserts `scenario_similarity` is always present
- **File:line**: `Brain/tests/test_ego_trap_rubric_lookup.py:61-67` (production:
  `ego_trap/rubric_lookup.py:52-56`)
- **What is wrong**: `rank_benchmark_responses` returns `list(responses)` **unranked and with no
  `scenario_similarity` key** when `len(responses) <= limit`. The test asserts exactly that
  (`== responses`, `embed.assert_not_called()`), locking in a function with two incompatible return
  shapes and no way for a caller to tell them apart. This is the exact bug CLAUDE.md records for
  `calibration/dry_run_ego_trap.py`: it called the function with `limit == len(rows)`, hit this
  branch, and its chosen-vs-discarded cosine band silently measured nothing. There is no test
  asserting the field is present on every returned row, and none that the short-circuit path is
  distinguishable from the ranked path.
- **What number it corrupts, and in WHICH DIRECTION**: it does not corrupt a number by itself; it
  removes the guard that would stop the corruption recurring. When it did recur, it **nulled out** the
  chosen (p50=0.646) vs discarded (p50=0.575) separation check entirely — the check reported "no data"
  and was read as a passing measurement.
- **Confidence**: likely (the defect is in callers; the test is what makes the ambiguity permanent)
- **Cheapest way to verify**: read `ego_trap/rubric_lookup.py:54-56` — the early return is the only
  path that omits `row["scenario_similarity"]`.

### 17. `test_benchmark_reference_caps_at_the_prompt_budget` asserts the implementation against itself — it passes for every value of `_MAX_BENCHMARK_EXAMPLES` from 1 to 5
- **File:line**: `Brain/tests/test_ego_trap_rubric_lookup.py:101-112`
- **What is wrong**: the assertion is
  `len(text.split("\n\n")) == rubric_lookup._MAX_BENCHMARK_EXAMPLES` — the expected value is read from
  the constant under test. With 5 fixture responses: for a cap of 1-4 the ranking truncates and both
  sides move together; for a cap of 5 the `len(responses) <= limit` short-circuit returns all 5 and
  both sides are 5. It only fails for a cap > 5.
- **What number it corrupts, and in WHICH DIRECTION**: `_MAX_BENCHMARK_EXAMPLES` controls how many of
  Naren's responses are pasted into the Step 3 grading prompt. CLAUDE.md's own trial measured that
  **removing the benchmark response moved discrimination 1.30 → 1.12 and the null 0.130 → 0.150** — so
  this constant demonstrably moves `W` and the discrimination ratio. A silent change would move both
  with the suite green; direction depends on the change (more examples anchors the grader harder,
  raising `W(matched)`).
- **Confidence**: certain (about the test's insensitivity); likely (about magnitude)
- **Cheapest way to verify**: mentally set `_MAX_BENCHMARK_EXAMPLES = 4` at `rubric_lookup.py:18` and
  re-trace lines 101-112 — the assertion still holds.

### 18. `test_cross_scenario_coverage_is_zero_when_nothing_generalises` certifies a metric that cannot fail as "the honest-failure signal"
- **File:line**: `Brain/tests/test_skills.py:124-138`; `Brain/shared/skills.py:94-123`
- **What is wrong**: `cross_scenario_coverage = covered / len(labels)` where `covered` counts items in
  any group spanning >1 scenario. As the threshold falls everything merges into one group spanning
  every scenario, so it goes to **1.0 by construction** — CLAUDE.md records this as taxonomy item 5's
  canonical example. The test's docstring nonetheless states the retracted claim verbatim: *"If this
  stays near zero at every threshold, behavioural skills do not exist in this corpus and the approach
  fails rather than being tuned into existence."* Both tests probe the **fine** end (thresholds 0.999
  and 0.8, where the metric can legitimately be low); no test probes the coarse end, so the suite never
  records that the metric's failure mode is unreachable. `sweep` also has no counterweight — the
  merge-validity curve `V(t)` lives in `trial_skills`, not `skills`.
- **What number it corrupts, and in WHICH DIRECTION**: the printed `x-scen` column of the skills sweep
  (`trial_skills.py:554`). Reading it as a pass criterion at any coarse threshold **always inflates**
  confidence — a run that fused all 405 milestones into one group reports
  `cross_scenario_coverage = 1.00`, the maximum score, for the worst outcome. It does not currently
  feed `evaluate_window`, so the published verdict ("no window at any bound") is unaffected; the risk
  is a future reader taking the column at face value, which the test's docstring actively invites.
- **Confidence**: certain
- **Cheapest way to verify**: `skills.sweep(vecs, keys, [0.0])` on any input returns
  `cross_scenario_coverage == 1.0` whenever ≥2 scenarios are present — evident from
  `shared/skills.py:111,121`.

### 19. `layer_d.scoring_unit` is a declared tuning key with no consumer, the flag `call_scoring.py` names as its gate is inert, and neither the shipped-file test nor any wiring test pins it
*(reached independently by W1-T1#4 and W1-T4#6)*
- **File:line**: `Brain/ego_trap/call_scoring.py:4` (docstring: *"Gated by `layer_d.scoring_unit:
  call`"*), `Brain/shared/tuning.py:91`, `Brain/tuning.yaml:530` (`scoring_unit: moment`),
  `Brain/tests/test_tuning.py:88-127` (asserts enums for `grouping_method`, `matching_strategy`,
  `sink_rescue_strategy`, `describe_mode`, `signal_detection_mode`, `turn_match_mode` — but **not**
  `scoring_unit`)
- **What is wrong**: `grep -rn "scoring_unit" Brain/ --include=*.py` returns five hits — the dataclass
  field, the YAML, a `prompts.py` comment, a `call_scoring.py` docstring and one test fixture. **No
  dispatch reads it.** `ego_trap/pipeline.py` never imports `call_scoring` and never reads
  `tuning.layer_d.scoring_unit`; the only caller of `score_call` is
  `calibration/trial_call_scoring.py`, which hardcodes its own settings. The key reads as authoritative
  while doing nothing — the retired `ego_trap/settings.py` failure class. (`embedding.backend` is safe
  by contrast: `preprocessing/embedder.py:76` raises on an unknown value.)
- **What number it corrupts, and in WHICH DIRECTION**: nothing today (shipped value `moment` is also
  the actual behaviour). It becomes a corruption the moment someone sets `scoring_unit: call`
  believing they switched units: Layer D would keep producing **moment-mode** `attempts`/`hits`
  (~25 moments per call) while the operator reads them as call-mode counts (~1 per call).
  `tuning.yaml:527` explicitly warns those two are **not comparable** — the numbers would be
  mislabelled by roughly the moments-per-call factor, in the direction of *understating* per-unit
  credit. The corrupted number is `W`.
- **Confidence**: T1 — certain that nothing reads the key (exhaustive grep of `Brain/**/*.py`);
  speculative only as to whether anyone intends to flip it. T4 — likely (the key may be deliberately
  unwired given the HEAD commit *"Call-level scoring FAILS its own gate on all three checks — do not
  enable it"*, but nothing in code or tests records that).
- **Cheapest way to verify**: `grep -rn "scoring_unit" Brain --include=*.py`.

### 20. The applicability judge's null compares "ids per exchange" across rubrics with unmatched milestone counts
- **File:line**: `Brain/calibration/validate_rubrics.py:208-212` (`applicable_rate_overall`),
  consumed at `:772-780`, gated at `:527`; tested at `Brain/tests/test_validate_rubrics.py:182-185`.
- **What is wrong**: `applicable_rate_overall` returns `(ids returned, exchanges answered)`, and
  `matched_rate`/`null_rate` are that ratio — an unnormalised **count of applicable milestone ids per
  exchange**, bounded above by the rubric's milestone count. The null swaps in `rubrics[pkey]`, and
  `derange` pairs by cosine distance only (`:670`) with **no matching on milestone count**. A partner
  rubric with 3 milestones cannot return more than 3 ids where the matched rubric with 8 could return
  8. Taxonomy item 6: the null controls for topic and nothing for rubric size. The test asserts
  `== (2, 2)` on a hand-built dict and pins neither the normalisation nor the comparability.
- **What number it corrupts, and in WHICH DIRECTION**: `applicability_null.null_rate` and the
  pass/fail line `null_rate <= 0.5 * matched_rate`. If partner rubrics are on average **smaller**,
  `null_rate` is deflated and the judge appears to collapse for a reason that is pure arithmetic —
  the defect makes **passing easier**. This does not explain the recorded 1.22:1 failure (the judge
  failed anyway), but a *pass* on this check would not have been trustworthy. Secondary:
  `--skip-applicability`'s help text (`:591-593`) and CLAUDE.md both describe 0.147/0.120 as an
  *"applicable fraction"*, which this quantity is not.
- **Confidence**: likely (the size confound is certain from the code; whether partner rubrics skew
  small in the live corpus is unmeasured).
- **Cheapest way to verify**: read `plan[key]["milestones"]` in
  `Brain/artifacts/rubric_validation.json` and correlate each scenario's own milestone count with its
  partner's.

### 21. A milestone whose arm-B counter is absent passes the discrimination gate for free, and the test blesses it as "a legitimate zero null"
- **File:line**: `Brain/calibration/validate_rubrics.py:169` (`b.get(key, counter_zero())`); gate at
  `Brain/shared/rubric_validation.py:122`; blessed at `Brain/tests/test_validate_rubrics.py:106-113`.
- **What is wrong**: `_verdict` fires `NOT_DISCRIMINATING` on `a3_w > 0 and b_w >= T_DISCRIMINATION *
  a3_w`. It never consults `b["attempts"]`, so **"the null was measured and came back empty" and "the
  null was never measured" are indistinguishable** — both give `b_w = 0.0`, and discrimination is the
  *first* gate. `main()` guards the whole-rubric case by aborting unless the pairing is a true
  derangement (`:674-681`, with a comment naming exactly this failure), but per-milestone B counters
  can still be empty when a B batch raises `GemmaError` (`_score_arm` `continue`s on the whole batch).
  The test only exercises the safe corner (all-`miss` A3, so `a3_w = 0` and the gate never runs), then
  names the permissive behaviour correct.
- **What number it corrupts, and in WHICH DIRECTION**: the per-milestone verdict counts in `_report` —
  **inflates** `validated` + `contingent` (the "scoreable" line) and **deflates** `not_discriminating`,
  by exactly the number of milestones whose null was lost to a failed batch. The per-milestone
  resolution is already written off, so consequence today is limited to any future re-read of
  `rubric_validation.json`.
- **Confidence**: certain about the code path; **speculative** about how many milestones are actually
  affected in the stored artifact.
- **Cheapest way to verify**: count records in `Brain/artifacts/rubric_validation.json`'s `verdicts`
  with `b_attempts == 0` and a non-`not_discriminating` verdict.

### 22. `test_no_naren_response_no_pair` is vacuous — it passes on the substantive-word filter, not on the property it names
- **File:line**: `Brain/tests/test_layer_b_v1.py:34`
- **What is wrong**: both CLIENT turns are `"Question?"` and `"Another question?"`. `_is_substantive`
  (`v1/layer_b.py:27`) requires `>= _MIN_CONTENT_WORDS = 5` alphabetic non-stop tokens; these have 1
  and 2. Both turns are skipped at `layer_b.py:45` and the response-collection loop is never entered.
  Deleting the `if response_parts:` guard at `layer_b.py:61` — i.e. making the function emit a pair
  with an empty response — would leave this test green.
- **What number it corrupts, and in WHICH DIRECTION**: `extract_pairs` is production
  (`v2/pipeline.py:44`) and its output count IS a reported number (4,605 kb_pairs). The rule "a client
  turn with no Naren reply produces no pair" is the one rule this file claims to cover and is in fact
  unconstrained; a regression would **inflate** the kb_pairs count with empty-response pairs, which
  then flow into `assign_scenarios` and Layer C's response clause pool. Nothing else in the batch
  covers it either.
- **Confidence**: certain (holds regardless of whether spaCy treats "question" as a stopword — the
  count is below 5 either way).
- **Cheapest way to verify**: read `v1/layer_b.py:42-47` alongside the test's turn texts.

### 23. The two warnings that mark a Layer D hit rate as a LOWER BOUND rather than a measurement are untested
- **File:line**: `Brain/ego_trap/milestone_scoring.py:336-347` (missing / unexpected ids) and
  `:551-555` (coverage scoring); no corresponding test anywhere in `Brain/tests/`.
- **What is wrong**: `grep "LOWER BOUND\|Step 3 returned\|never asked for" Brain/tests/` returns
  nothing. The only `capsys` assertions in the batch are for the soft-skill rating clamp. Meanwhile
  `test_batch_matches_by_id_and_defaults_missing_to_miss` *does* pin the silent consequence
  (`results[2][0]["verdict"] == "miss"` for an id the model never returned) — the suite pins the
  failure mode and leaves the alarm unpinned.
- **What number it corrupts, and in WHICH DIRECTION**: **the weighted score and full-hit rate**,
  always **downward**. Output truncation drops the tail of the id array and every dropped milestone is
  stored as a coaching failure. If a refactor removed or broke that print, a truncated run would report
  a deflated `W` with no trace, and the ±0.006-noise-band discipline in CLAUDE.md would be applied to a
  number that is not a measurement. Note the two scorers default in *opposite* directions for a
  dropped unit — `milestone_scoring` → miss, `call_scoring.parse_response` → not scored — and each
  file's tests assert its own, so the asymmetry is pinned but never compared.
- **Confidence**: certain (the coverage gap); likely as to consequence.
- **Cheapest way to verify**: the grep above.

### 24. `required_call_support` — the Layer A support gate — has no test anywhere, while its Layer C twin has four
- **File:line**: `shared/cluster_evidence.py:120-127`; `Brain/tests/test_cluster_evidence.py` has
  `TestMilestoneSupport` (lines 157-173) for `required_milestone_support` and **no equivalent class**
  for `required_call_support`
- **What is wrong**: the two functions are the same `max(floor, ceil(fraction * n))` shape. The Layer C
  one is tested for scaling, floor application, round-up-not-down and the zero case. The Layer A one —
  which produces `min_support` at `v2/layer_a.py:476` and therefore decides how many clusters are
  dropped as `INSUFFICIENT_EVIDENCE` before ever reaching Gemma — has zero tests in the repo. The file
  reads as covering the module, which is what makes the omission hard to notice.
- **What number it corrupts, and in WHICH DIRECTION**: the scenario count, in either direction. A
  floor/ceil swap or a `max`→`min` slip changes how many clusters are dropped with no test to catch it.
  The knob is documented INERT at 416 calls (drops 0–3 of 226), so the *current* blast radius is small
  — but the suite is what would have to catch it becoming live on a different corpus, and it cannot.
- **Confidence**: certain (coverage gap verified by grep across the whole repo).
- **Cheapest way to verify**: `grep -rn "required_call_support" Brain/tests/` → no hits; the same grep
  across `Brain/` shows 7 production/calibration call sites.

### 25. The `_finalize_primary_topics` tests never reach `tighten_coachable_groups`, never reach the `post_hoc` branch, and never cover the silent "Uncategorised" fallback
- **File:line**: `Brain/tests/test_layer_a_v2_primary_topics.py:25-27, 79-81` (the `_Tuning` stub) and
  `v2/layer_a.py:334-350, 392-400`
- **What is wrong**: (a) both `_finalize_primary_topics` tests build groups of exactly one member, so
  `tighten_coachable_groups` short-circuits on `len(group) <= 1`
  (`shared/topic_grouping.py:161`) and its real re-clustering path is never executed through the
  production entry point. Consistently, the fixture records have no `"centroid"` key — the real
  `by_key` records always do (`v2/layer_a.py:559`) — so if `tighten_coachable_groups` ever ran, these
  fixtures would `KeyError`. (b) the `_Tuning` stub carries only `grouping_method` and
  `merge_cosine_threshold`, so the `post_hoc` branch (`:392-393`, needing
  `primary_topic_merge_threshold`) is unreachable; production ships `nested`, so latent rather than
  live. (c) `_label_primary_topics_batch` substitutes `primary_topic_{idx}` / `"Uncategorised"` / `""`
  for any group whose id is missing from Gemma's reply (`:337-350`) — a silent drop with no counter and
  no warning, the same truncation failure mode `ops/rewrite_milestone_criteria.py` already measured
  (1 batch in 21 truncated at size 20). No test covers a short reply.
- **What number it corrupts, and in WHICH DIRECTION**: (c) is the one that moves a number — a
  truncated or partially-parsed label batch **inflates** the count of `primary_topics` rows labelled
  `Uncategorised` with empty descriptions, and those empty descriptions are what
  `shared/scenario_vectors.build_primary_topic_vecs` embeds, so the primary-topic vector population
  degrades silently. (a) and (b) are coverage gaps with no current numeric consequence.
- **Confidence**: certain for the coverage gaps and the fallback's silence; the truncation rate on this
  specific prompt is unmeasured.
- **Cheapest way to verify**: `grep -n "centroid" Brain/tests/test_layer_a_v2_primary_topics.py` → no
  hits; then read `v2/layer_a.py:337` and note nothing counts `results_by_idx` misses against
  `len(groups)`.

### 26. The printed Gemma-call count uses the legacy batch size in situated mode, where batching is per scenario — and no test constrains it
- **File:line**: `Brain/v2/layer_c.py:806-809`; batch constant at `:24`
- **What is wrong**: `n_calls = math.ceil(len(describe_items) / _DESCRIBE_BATCH_SIZE)` is computed
  unconditionally, after the `if tuning.describe_mode == "situated"` branch at `:802`.
  `_describe_situated` and `describe_coverage_areas` both iterate
  `group_describe_items_by_scenario`, i.e. **one call per scenario**, not one per 5 milestones.
  `test_layer_c_describe.py` never imports or references `_DESCRIBE_BATCH_SIZE`, so nothing pins 5,
  nothing pins the per-scenario grouping's call count, and nothing would notice this print going stale.
- **What number it corrupts, and in WHICH DIRECTION**: the
  `[V2 Layer C] ... batched into N Gemma call(s)` line in every run log — the cost figure the design's
  "81 calls vs ~82" claim rests on. It **overstates** when a scenario averages >5 milestones and
  **understates** when it averages fewer; it coincidentally reads about right at the current ~5:1
  ratio, which is why it has gone unnoticed.
- **Confidence**: certain.
- **Cheapest way to verify**: `grep -n "_DESCRIBE_BATCH_SIZE" Brain/v2/layer_c.py Brain/tests/*.py` —
  three production hits, zero test hits.

### 27. The working-tree rename `csm_roles` → `scored_roles` breaks five tests, and the new `at_turn` role check has zero test coverage
*(working-tree caveat: `Brain/ego_trap/call_scoring.py` and `Brain/calibration/trial_call_scoring.py`
are dirty and were edited by another process mid-audit; this finding is stated against the current
working tree, not HEAD.)*
- **File:line**: `Brain/ego_trap/call_scoring.py:190` (working tree, uncommitted) vs
  `Brain/tests/test_call_scoring.py:189-254`
- **What is wrong**: the uncommitted edit renames the kwarg and changes the default to `("NAREN",)`.
  Five tests were not updated: `test_across_turns_needs_two_real_CSM_turns` and
  `test_evidence_kind_is_inferred_when_the_model_omits_it` will raise
  `TypeError: unexpected keyword argument 'csm_roles'`; and
  `test_a_real_quote_at_the_right_turn_verifies`,
  `test_whitespace_and_case_do_not_break_verification`,
  `test_an_adjacent_turn_still_verifies_within_the_window` now use the `("NAREN",)` default against a
  fixture whose speakers are `Client`/`CSM`, so no turn matches and `verified == 1` fails. Nothing
  exercises the change that actually matters — *a quote found in the window but spoken by someone other
  than the person being scored must fail*. The new `by_kind` / `cited_speaker_mix` / `unknown_roles`
  outputs are likewise untested.
- **What number it corrupts, and in WHICH DIRECTION**: the tests will fail loudly, so they corrupt
  nothing directly. The consequence is that the **fix to check 2's verification rate is shipping
  unverified**: `unknown_roles` (the guard against a caller typing a role name that is not an enum
  member — the exact defect being repaired) has no assertion, so the same class of typo could be
  reintroduced with a green suite. Direction: unconstrained in both.
- **Confidence**: certain.
- **Cheapest way to verify**: `git diff Brain/ego_trap/call_scoring.py` and
  `grep -n "csm_roles" Brain/tests/test_call_scoring.py`.

### 28. `TestFallback.test_keeps_strict_pick_when_it_is_strong` cannot distinguish "kept" from "rerouted"
- **File:line**: `Brain/tests/test_two_stage_matching.py:217`
- **What is wrong**: in that setup stage 1 keeps the correct primary topic, so strict picks `sub_a`
  **and** flat picks `sub_a`. The assertion `scenario_keys == ["sub_a"]` holds whether the
  `top1_sim < two_stage_fallback_floor` branch (`v1/layer_b.py:230`) fires or not. Inverting the
  comparison to `>=` leaves the test green. The trailing `assert 1.0 >= floor` is an assertion about
  the test's own setup, not the code. Its sibling `test_reroutes_to_flat_when_strict_pick_is_weak` IS
  discriminating, so only the "keep" direction is unguarded.
- **What number it corrupts, and in WHICH DIRECTION**: nothing in production —
  `matching_strategy: flat`, `assign_scenarios_two_stage` is called only by
  `calibration/compare_matching_subset.py`. But those two tests are the entire guard on
  `two_stage_fallback_floor`, and the floor sweep is a reported comparison (86.6% agreement at floor
  0.50 on the subset, 71.4% at full corpus). A silently-inverted floor would make the whole sweep table
  read backwards with no test failing.
- **Confidence**: certain.
- **Cheapest way to verify**: flip `<` to `>=` at `v1/layer_b.py:230` and note that only
  `test_reroutes_to_flat_when_strict_pick_is_weak` fails.

### 29. `TestStrict.test_sink_short_circuit_ignores_primary_topic_stage` would pass with the short-circuit deleted
- **File:line**: `Brain/tests/test_two_stage_matching.py:130`
- **What is wrong**: with the sink as the sole member of the primary topic that wins stage 1,
  `restrict_to` contains only the sink index; `topk_pick` then finds no non-sink candidate and returns
  `None`, so `strict_kept = ... or [scenario_keys[best_j]]` (`v1/layer_b.py:224`) yields `["sink"]`
  anyway. Removing the `if is_sink[best_j]` short-circuit at `layer_b.py:211` leaves the assertion
  true. (Its `TestSoft` counterpart at `:176` IS discriminating.)
- **What number it corrupts, and in WHICH DIRECTION**: none today (dead code). Reported for
  completeness — a second instance of the same "asserts a weaker property than its name" pattern in the
  same file.
- **Confidence**: certain.
- **Cheapest way to verify**: trace `restrict_to` at `v1/layer_b.py:219` for that two-scenario map.

### 30. `test_falls_back_to_flat_when_response_cannot_rescue_either` asserts something every branch satisfies
- **File:line**: `Brain/tests/test_sink_rescue.py:169`
- **What is wrong**: the only assertion is `pairs[0]["scenario_key"] is not None`. `_assign`
  (`v1/layer_b.py:316-319`) sets `scenario_key` on **every** branch of every strategy, so the
  assertion is unfalsifiable. The test never checks the pair landed on flat's pick (`"quality"` for
  `_WEAK_TRIGGER`), which is the behaviour its name describes.
- **What number it corrupts, and in WHICH DIRECTION**: none today (`sink_rescue_strategy: none`, only
  `calibration/compare_sink_rescue.py` calls this). It does mean the `or_rule` rescue-failure path
  behind the reported "8.5% rescue rate (159/1,865)" has no assertion on where the un-rescued pair
  goes.
- **Confidence**: certain.
- **Cheapest way to verify**: read the assertion; compare with
  `TestResponseOnly.test_stays_in_sink_when_response_is_also_weak:83`, which does assert the
  destination key.

### 31. Latent threshold coupling — one hardcoded near-tie ratio that is only "clearly above the cutoff" at today's `relative_margin`
- **File:line**: `Brain/tests/test_layer_b_assignment.py:96`
  (`test_sinks_never_ride_along_with_a_real_match`, trigger `"pricing:1.0 ack:0.98"`)
- **What is wrong**: this test proves the **sink filter** excludes `ack` only because `ack`'s ratio of
  0.98 clears the cutoff `0.95 × best`. At `relative_margin: 0.95` it is meaningful. Raise the margin
  above 0.98 and `ack` is excluded by the *margin* instead, the assertion still passes, and the test
  silently stops covering the sink filter — exactly the class already burned by
  `test_ambiguous_trigger_keeps_the_near_ties` (fixed to derive from `load_tuning()`; this sibling was
  not). The rest of the hand-built weights in the batch are safe by a wide margin:
  `test_weak_second_match_is_excluded` (0.2 vs 0.95), `TestOrRule._WEAK_TRIGGER` (cos 0.4862, guarded
  by `assert 0.486 < floor < 1.0`), `TestBlended` (guarded by `assert 0.5 < alpha < 1.0`),
  `TestFallback` (guarded by `assert floor > 0.0`). `test_relative_match.py` passes `margin`/`cap` as
  literals and never reads `tuning.yaml`, so it is structurally immune.
- **What number it corrupts, and in WHICH DIRECTION**: none today — latent. Flagged because the brief
  names this defect class and this is the only remaining unguarded instance.
- **Confidence**: certain that the coupling exists; it is dormant at the shipped margin.
- **Cheapest way to verify**: set `layer_b.relative_margin: 0.99` in a scratch copy of `tuning.yaml`
  and note the test still passes while no longer exercising `not is_sink[int(j)]`.

### 32. Two `verify_evidence` window tests cannot fail: the default window spans the entire fixture transcript
- **File:line**: `Brain/tests/test_call_scoring.py:189-191` and `:213-215`, against
  `Brain/ego_trap/call_scoring.py:253` (`lo, hi = max(0, t-1-window), min(len(texts), t+window)`)
- **What is wrong**: `TURNS` has **four** turns and the default `window=2` spans ±2, so for any cited
  turn the window covers the whole transcript. `test_a_real_quote_at_the_right_turn_verifies` and
  `test_an_adjacent_turn_still_verifies_within_the_window` would both pass with any turn number and
  with the window bound removed on the left. Only `test_a_real_quote_cited_at_the_wrong_turn...`
  (which passes `window=0`) constrains localisation at all, and only the right bound.
- **What number it corrupts, and in WHICH DIRECTION**: check 2's verification rate, **upward** if the
  window ever became looser than intended (a mislocated quote would still verify). Low magnitude
  relative to C4/C5 — a coverage hole, not a live error.
- **Confidence**: certain (arithmetic on a 4-element list).
- **Cheapest way to verify**: `TURNS` is 4 entries; at `t=3, window=2` the slice is `texts[0:4]`.

### 33. The model-pinning path in `score_milestones_batch` — the exact mechanism that made ceiling arm B uninterpretable — has no test
- **File:line**: `Brain/ego_trap/milestone_scoring.py:168-169, 318-323`; no test in
  `Brain/tests/test_ego_trap_milestone_scoring.py` ever passes `model=` or `fallback_models=`.
- **What is wrong**: the docstring makes the `fallback_models=()` vs `fallback_enabled=False`
  distinction load-bearing (an empty tuple pins the model while keeping key rotation alive). The
  call-scoring suite *does* pin this (`test_call_scoring.py:270-271` asserts both kwargs reach
  `call_gemma`); the milestone suite does not. Relatedly, `_config()` in both files omits
  `gemma_api_keys`, so it defaults to `()` (`config.py:17`) — every test passes an empty key tuple to a
  mocked `call_gemma`, so no test would notice a change in how keys are threaded.
- **What number it corrupts, and in WHICH DIRECTION**: none today. It leaves unguarded the failure
  CLAUDE.md records as having destroyed a result — *"arm B is also model-split (793 gemini-3.1 + 1040
  gemini-3.5), so the exact ratios move with the subset"* — where a silently blended arm makes a ratio
  attributable to the model rather than the treatment, in an unknown direction.
- **Confidence**: certain (coverage gap); the consequence is a precedent, not a live measurement.
- **Cheapest way to verify**:
  `grep -n "fallback_models\|model=" Brain/tests/test_ego_trap_milestone_scoring.py` — no hits.

### 34. Three tests in the parsing/infra batch cannot fail for the property they are named after
- **File:line**:
  - `Brain/tests/test_gemma_retry.py:61-77` —
    `test_ssl_read_error_still_raises_gemma_error_once_retries_exhausted`. With the
    `isinstance(e, httpx.TransportError)` fix at `shared/gemma.py:105` **reverted**, the first
    `ReadError` is not transient, `escalate=False`, so `_call_once` raises `GemmaError` immediately —
    and the test still passes, because it never asserts `fake_models.calls == 2`. Its sibling at
    `:41-58` *does* assert the call count and is the only real guard on the fix. (Confirmed the message
    `"...(read) (_ssl.c:2580)"` matches none of `_TRANSIENT_MARKERS` or `_LIMIT_MARKERS`, so the
    isinstance branch is genuinely load-bearing for the sibling.)
  - `Brain/tests/test_ego_trap_transcript_parser.py:80-84` —
    `test_turns_until_next_client_no_csm_speaker_present` **never calls
    `turns_until_next_client`**. It asserts `all(t.role != EgoTrapRole.CSM)` on speakers `Anna` and
    `Someone Else` against `CSM = "priya"`, which cannot be anything but true.
  - `Brain/tests/test_ego_trap_scenario_pool.py:24-27` — `test_sink_keys_is_the_complement` asserts
    `sink_keys(pool) == set(pool) - set(coachable_only(pool))`. Both sides derive from the same
    `is_coachable(v)` predicate (`scenario_pool.py:60` and `:65`) — an algebraic identity that would
    hold for any definition of `is_coachable`, including a wrong one.
  - *(Also noted, no number: `test_fetch_rubric_passes_pipeline_version_through` at
    `test_ego_trap_rubric_lookup.py:122-129` mocks `storage.get_rubric_for_scenario` to return a dict
    containing `pipeline_version` and asserts the one-line pass-through returns it. The real
    constraint — that the SQL at `storage.py:373-376` SELECTs the column — is untested. CLAUDE.md says
    `pipeline_version` consumers are observability only, so this one moves no number.)*
- **What number it corrupts, and in WHICH DIRECTION**: none directly. The effective guard count on the
  2026-07-31 gemma retry fix is **1, not 2**, and `scenario_pool`'s sink split has one fewer real test
  than the file's 10-test count suggests.
- **Confidence**: certain
- **Cheapest way to verify**: `shared/gemma.py:103-106` (delete the `or isinstance(...)` term and
  re-trace both gemma tests); read the body of
  `test_turns_until_next_client_no_csm_speaker_present`.

### 35. `test_pick_benchmark_survives_a_degenerate_pool`'s key assertion is vacuous and its fixture is drifted from the real row shape
- **File:line**: `Brain/tests/test_naren_ceiling.py:87-94`; real producer
  `Brain/calibration/score_naren_ceiling.py:334`
- **What is wrong**: the test claims to pin the `dry_run_ego_trap` short-circuit bug, asserting
  `all("scenario_similarity" not in r for r in picked)`. But `pick_benchmark` is a pure
  `hold_out(...)[:limit]` — it neither adds nor removes keys — so the assertion is a property of the
  `_row` fixture, not of the function, and would hold if the body were replaced by `return
  pool[:limit]`. Worse, the fixture is **inverted relative to production**: `_ranked_benchmark_pool`
  builds every row as `dict(r, scenario_similarity=float(sims[i]))` (line 334), so on real data every
  row in `ranked_pools` **does** carry `scenario_similarity`. Only the
  `len(picked) == min(size, _BENCHMARK_EXAMPLES)` half constrains anything.
- **What number it corrupts, and in WHICH DIRECTION**: none directly — `pick_benchmark`'s behaviour is
  correct and is separately pinned by the two `hold_out` tests. Reported because it is a named defence
  against a real, previously-costly bug class (silent short-circuit, taxonomy item 9) that provides no
  defence at all, and because the equivalence check that *does* guard it
  (`_verify_ranking_equivalence`, lines 339-364) is untested.
- **Confidence**: certain
- **Cheapest way to verify**: read `score_naren_ceiling.py:139-142` against
  `tests/test_naren_ceiling.py:94`.

### 36. `test_order_within_a_scenario_is_preserved` is named and documented for a property it cannot protect
- **File:line**: `Brain/tests/test_layer_c_describe.py:44-51`
- **What is wrong**: the docstring claims *"milestone_id is the array POSITION. If grouping reorders a
  scenario's items, every id downstream shifts and existing milestone_performance rows silently
  repoint at a different criterion."* That is false. `group_describe_items_by_scenario` feeds only the
  prompt; the stored `order` is re-derived independently by `_finish_rubric` (`v2/layer_c.py:613`,
  `enumerate(ordered)`), and the description lookup is by content id `f"{scenario_key}::{cluster_id}"`
  (`:614`), not by position. Reordering the describe batch cannot move a single `milestone_id`.
  Separately, the fixture makes `order` numerically equal to position (`_item(scenario, order)` with
  orders 1,2,3), so the test cannot distinguish the `order` **field** from the array **position** —
  the exact conflation taxonomy item 3 warns about.
- **What number it corrupts, and in WHICH DIRECTION**: no number, directly. It is a live false
  assurance: a reader looking for the test that protects `milestone_performance` identity against
  reordering will find this one and stop. That protection does not exist in this batch. What the test
  *does* constrain is the order of moves inside one situated prompt — real, but not what it says.
- **Confidence**: certain.
- **Cheapest way to verify**: read `Brain/v2/layer_c.py:612-619`.

### 37. Minor: the discrimination-boundary test never exercises the quantization blind spot it exists for, and says it does
- **File:line**: `Brain/tests/test_rubric_validation.py:43-51`
- **What is wrong**: no test encodes the 0.0625 quantization. The comment says *"One partial less on
  the control and it survives"*, but the code removes one **hit** (`b=_c(hits=2)` → `b=_c(hits=1)`), a
  step of 0.125, i.e. two quantization steps. The single-partial flip the design says trips the gate
  (`b=_c(hits=1, partial=1)` → 1.5/8 = 0.1875, survives; `b=_c(hits=1, partial=2)` → 2.0/8 = 0.25,
  fires) is never written down. Every discrimination test runs at `_c()`'s default `attempts=8` —
  precisely the n the design records as the reason the per-milestone instrument failed — and none at a
  realistic larger n.
- **What number it corrupts, and in WHICH DIRECTION**: none directly. Reported because the arithmetic
  *is* pinned at the failing n, and the comment misdescribes which step it demonstrates.
- **Confidence**: certain.
- **Cheapest way to verify**: arithmetic on `weighted()` at `rubric_validation.py:61` with attempts=8.

---

## CROSS-FILE RECURRENCE WITHIN THIS WAVE

### R1. The segmenter's `len(sent) < 4` cutoff is unpinned from above — reached independently from two different test files, with a third auditor asserting the opposite
- **W1-T2#2** measured the token counts in `tests/test_segmenter.py` (spaCy run locally): the cutoff
  is required from below by the 3-token `"I mean."` fixture but **free to rise from 4 to 13**.
- **W1-T5#4** measured the token counts in `tests/test_layer_c_clause_pool.py`'s fixtures (8 / 7 / 6 /
  7): the cutoff is **free to rise from 1 to 6** there, and the module docstring's claim that the
  filter is *"pinned by its own test below rather than left as a trap for the next person"* is false.
- **Tension worth flagging to the merge pass**: W1-T4's CLEAN section asserts the opposite —
  *"The segmenter's own `len(sent) < 4` cutoff is independently pinned by
  `test_a_backchannel_only_turn_survives_...` (`build_client_pool(…, "clause") == ([], [])`), so a
  segmenter change does not pass unnoticed."* That test pins the cutoff from **below** only (a
  backchannel turn must still be dropped), which is the same side T2 and T5 both found already
  covered. **Two measured findings beat one asserted clean**: the cutoff has no upper guard anywhere in
  the suite. Combined blast radius: Layer A's clause pool (73,771 items, 59.1% content-free) *and*
  Layer C's milestone pool (the 385–405 band), both deflated by an upward drift, both silent.

### R2. The ceiling's arm-construction asymmetry is unguarded from two directions
- **W1-T6#2** found `test_naren_ceiling.py` never imports `_build_items` or `_item`, so nothing
  constrains which pool each arm draws from — the suite could never have caught the asymmetry that
  produced the retracted 1.2:1.
- **W1-T5#1** found the downstream consequence still shipped: `SCENARIO_MIN_ATTEMPTS = 15` /
  `SCENARIO_BAND = 0.05` in `shared/rubric_validation.py` were **fitted** to reproduce that same
  retracted table, and `test_rubric_validation.py:165-171` asserts them as calibrated — while
  `validate_rubrics._items_for` runs a *symmetric* comparison through the asymmetric band.
- Neither auditor saw the other's file. Together: the retracted measurement has no test that could have
  caught it, and its fitted constants are now load-bearing in a second harness.

### R3. `layer_d.scoring_unit` is a config key with no consumer — reached from ego_trap tests and from tuning tests
- **W1-T1#4** (from `test_call_scoring.py` / `ego_trap/`): `grep -rn "scoring_unit|call_scoring|score_call"
  Brain/ego_trap/` returns only the docstring and the definition; `ego_trap/pipeline.py` never reads it.
- **W1-T4#6** (from `test_tuning.py`): five hits repo-wide, none a dispatch;
  `test_shipped_tuning_yaml_is_valid` enum-checks six other string keys and not this one.
- Same conclusion, two entry points: the `ego_trap/settings.py` failure class ("reads as authoritative
  while doing nothing") has been re-created inside the loader that was supposed to prevent it.
  Consolidated as ALL FINDINGS #19.

### R4. A named defence against the "silent short-circuit" bug class (taxonomy 9) that provides no defence — two instances
- **W1-T2#4**: `test_ranking_does_not_embed_when_the_pool_already_fits` *blesses*
  `rank_benchmark_responses`'s unranked, `scenario_similarity`-less early return — the exact branch
  that nulled out `dry_run_ego_trap`'s chosen-vs-discarded band.
- **W1-T6#8**: `test_pick_benchmark_survives_a_degenerate_pool` is *named* for that same bug class,
  asserts `"scenario_similarity" not in r`, and is a property of its own fixture — which is
  **inverted** relative to production, where every ranked row carries the field.
- One test locks the ambiguity in, the other claims to guard it and asserts the opposite of the real
  row shape. Neither would stop a third recurrence.

### R5. `usable_item_fraction` fails to detect the mega-blob it was written to catch
- **W1-T6#1** only — single-source, verified by hand arithmetic from the test's own literals
  (pathological 0.973 vs healthy 0.976, a 0.003 separation). No other auditor covered `trial_skills`.
  Recorded here because the orchestrator flagged it as a known recurrence candidate: it does **not**
  recur across files in this wave, but it does contradict a published CLAUDE.md claim (see corrections
  X1).

### R6. `flat_pick` / `topk_pick` cap-ordering divergence and the vacuous test guarding it
- **W1-T3#1** only — single-source within this wave. Note W1-T3's CLEAN section independently verified
  the *other* half of the extraction claim (`flat_pick` **is** byte-equivalent to production's inline
  loop in `assign_scenarios`, diffed line by line), which is what isolates the divergence to
  `flat_pick` vs `topk_pick` rather than to the extraction.

### R7. A silent default or drop with no counter — four independent instances
- **W1-T1#5** (`emitted` discarded in `score_milestones_batch`, treatment silently degrades to the
  production prompt), **W1-T1#6** (the two LOWER-BOUND warnings untested), **W1-T4#4**
  (`_KIND_BY_DECISION.get(decision, KIND_SCENARIO)` — an unknown decision becomes coachable),
  **W1-T4#7c** (`"Uncategorised"` substituted for any group missing from Gemma's label reply).
  All four are taxonomy #10; none has a counter, a warning, or a test.

---

## CLEAN CATEGORIES

Grouped by taxonomy item. **MEASURED** = the auditor computed or read something to establish it;
otherwise the clean result is from direct code reading.

**Taxonomy 2 (metric over a biased subset) and 7 (two estimators as one number)**
- **The weighted-score definition is consistent everywhere and its test is not circular** (T1,
  **MEASURED** by grepping every `(hits + 0.5*partial)/attempts` in the repo: `db/schema.sql:193`,
  `gap_output.py:19`, `shared/rubric_validation.py:61`, `shared/coverage_areas.py:175-176`, and five
  `calibration/*.py`). All agree. `test_miss_rate_is_the_exact_complement_of_the_weighted_score`
  re-derives the formula independently rather than calling the function under test.
- **`shared/head_to_head.py`'s rate arithmetic is clean** (T6). `win_rate` excludes ties from the
  denominator and reports `n_total`/`n_decisive`/`tie_share`; `swap_agreement` excludes double-tie
  items and reports `both_tie_share`; both return `None` rather than `0.0` on an empty denominator,
  and both behaviours are pinned by tests. `by_decile` recomputes `win_rate` per stratum with the same
  function, so point estimate and strata are one estimator.
- **The three-state applicability parse is the one place the asymmetric-denominator trap was correctly
  avoided AND correctly tested** (T5). `rv.parse_applicability` distinguishes unanswered (`None`),
  answered-empty (`set()`) and answered-with-ids; `applicability_counters` excludes `None` from
  **both** counters; both sides are pinned.
- **`shared/coverage_areas.py` parse and roll-up logic** (T5, **MEASURED** — all 14 parsing/evidence
  assertions hand-checked against the implementation). `support_calls` really is `max` (`:106`),
  `support_clauses` really is `sum` (`:107`), `normalize_verdict` defaults to `NOT_COVERED` and never
  to `NOT_CALLED_FOR` (`:150`), and `score`'s two denominators (`total`, `total - not_called_for`) are
  both reported.

**Taxonomy 3 (numbering / base mismatch)** — checked end to end in three independent places, no live
instance found anywhere in the wave.
- T1: `classify_response_outcome`'s `start_index` is a list position and `EgoTrapTurn.index` is
  assigned as `len(turns)`, so the two coincide in production and fixtures. The 1-based
  `format_transcript` boundary is correct and pinned by
  `test_transcript_is_one_based_and_numbers_every_turn`.
- T2 (**MEASURED** — traced the full chain): `EgoTrapTurn.index = len(turns)` is assigned *after* the
  empty-utterance skip (`ego_trap/transcript_parser.py:57-73`), so `turns[i].index == i` always holds
  even when segments are dropped; `signal_check.py:338`, `rubric_lookup.py:93`,
  `turns_until_next_client` and `gap_output.py:192/222/258/303` all use the same 0-based value.
- T3: `test_layer_b_v1` passes `Turn.index` 0-based and `extract_pairs` stores `trigger_turn.index`
  verbatim.
- T5 (**MEASURED** — traced the positional-`milestone_id` convention end to end):
  `milestone_scoring.milestone_ids` (`:69-87`) is the single definition, `score_milestones_batch` zips
  it over the **full** unfiltered list (`:245-254`) so skipping never renumbers, `_write_verdicts`
  rebuilds by `enumerate(ids)` position, and `_finish_rubric` writes `order = order_idx + 1` over the
  same list it stores. The only conflation is documentary (ALL FINDINGS #36).

**Taxonomy 4 (name that never matches)** — clean in four of six batches; the one live instance is C5.
- T2 (**MEASURED** — grepped repo-wide for raw-string role comparisons): the two enums use **opposite**
  word order for the same concept (`SpeakerRole.JOVEO_OTHER` vs `EgoTrapRole.OTHER_JOVEO`), but the
  ego_trap test files reference enum *members*, not string literals, so the trap cannot bite inside
  them. The only remaining raw-string comparison is `calibration/read_gap_reasons.py:166`, correctly
  using the ego_trap spelling.
- T4: `_KIND_BY_DECISION`'s three keys match `PROMPT_LAYER_A_V2_TRIAGE`'s literals exactly
  (`shared/prompts.py:852-860`), verified by reading both. `test_layer_a_pool.py` imports
  `SpeakerRole.JOVEO_OTHER` as an enum member, so the string-typo class is structurally impossible.
- T5 (**MEASURED** — every string literal in the batch checked against its module):
  `rv.VALIDATED/CONTINGENT/NOT_SATISFIABLE/NOT_DISCRIMINATING/INSUFFICIENT_EVIDENCE`,
  `rv.SCENARIO_SHIP/HOLD/DISABLE/INSUFFICIENT`,
  `ca.COVERED/PARTLY_COVERED/NOT_COVERED/NOT_CALLED_FOR`, `"full_hit"/"partial_hit"/"miss"`, and all
  seven report keys exist.
- T6: `SpeakerRole.NAREN` / `SpeakerRole.JOVEO_OTHER` in `test_trigger_quality.py` are attribute
  accesses; `trigger_quality.preceding_turn_is_question` compares enum identity, not a string.

**Taxonomy 5 (a metric that cannot fail) — where it does NOT apply**
- T4: `merge_by_similarity`'s degenerate cases are covered (empty → `[]`, singleton → `[[0]]`,
  partition completeness); `group_nested` / `group_post_hoc` / `split_by_coachability` /
  `tighten_coachable_groups` each have an empty-input and a completeness test. The degenerate-case
  question is answered for all of them.
- T5: `_self_check`'s `passes` requires `ok_total > 0` **and** `bad_total > 0`
  (`validate_rubrics.py:389-390`), so an empty ceiling artifact fails closed rather than passing
  vacuously. (Its *baseline* is the problem — C3 — not its degenerate case.)
- T6 (**MEASURED** — all four `POWER_STANDARDS` rows re-derived by hand): `meets_standard` requires
  **both** `n_skills <= max_k` **and** `median_size >= min_members`, with a test for each half failing
  independently; `evaluate_window` treats an absent validity as a fail, pinned by
  `test_an_unjudged_threshold_never_counts_as_a_pass`. **The 2026-08-13 "selected on K alone" hole is
  genuinely closed and genuinely tested.**

**Taxonomy 8 (collapsing a multi-valued enum to a boolean)**
- T1: the `gap_events_enabled` gating test checks both arms *and* that the two aggregate writes still
  fire. `build_gap_record`'s hit/partial/miss partition is exhaustive and tested in all three
  branches, including that `full_hit` produces no `gaps` entry.
- T4: `test_cluster_evidence.py` asserts all three `triage()` verdicts by their module constants and
  pins the precedence between the two non-terminal branches. The `"merged"`-counted-as-sink bug that
  produced the retracted "Gemma over-sinks 14.6%" finding lives in
  `calibration/aggregate_cluster_verdicts.py`, **not** in `v2/layer_a.py` (which handles `merge_into`
  with an explicit `continue` at `:529`, correctly retaining it) and not in any Wave 1 test file.

**Taxonomy 11 (shadowing / overwrite) and import hygiene**
- T2 (**MEASURED** — directory listing checked for a module shadowing a top-level Brain module):
  `tests/conftest.py` only does `sys.path.insert(0, os.path.dirname(__file__))`; `tests/__init__.py`
  exists so pytest's prepend import mode already puts `Brain/` on the path. No shadowing candidate
  exists in `tests/`, only `test_*.py`. No import-order effect on any number.
- T6: **the logging-singleton contamination is FIXED and correctly fixed.**
  `tests/test_response_taxonomy_auto_pass.py:12-18` declares `_disable_real_log_file` as
  `@pytest.fixture(autouse=True)` at **module scope**, so no test can miss it; all six test classes
  verified covered. `calibration/graduate_sink_topics.py` has no logger (print only), so its test file
  needs no equivalent guard.

**Taxonomy 6, 12, 13, 14 (null matching, checkpoint keys, sampling, correlated observations)**
- T3: do not apply to `tests/test_layer_b_*.py`, `test_relative_match.py`,
  `test_two_stage_matching.py`, `test_sink_rescue.py` — pure unit tests with no sampling frame, no
  artifacts, no checkpoints, no statistics and no null arm.
- T6: `derange` (arm B pairings) was checked specifically for taxonomy 1 and is clean — the tests
  constrain no-fixed-point, permutation-ness (so each rubric receives equal attempts in B as in A1),
  cosine rejection at `merge_cosine_threshold`, the honest `no_valid_partner_*` return instead of
  pairing anyway, and seed reproducibility. The `_sim` helper's 1.0 diagonal makes self-pairing
  impossible independently of the fixed-point check. **The ceiling's asymmetry was in `_build_items`,
  not `derange`.**

**Hand-built-vector test construction (the "tests the rule, not the model" pattern) — verified sound**
- T3 (**MEASURED** — arithmetic recomputed for four tests): `_AXES` is the standard 3-D basis; every
  `resolve()` returns `_unit(vec)`; the `raise AssertionError("test text names no known axis")` guard
  is real (confirmed `scenario_vectors.scenario_text` emits the axis token). The arithmetic in
  `test_ambiguous_trigger_keeps_the_near_ties` is correct (`cos` ratio is exactly `w`, and
  `w = margin + (1-margin)/2` sits strictly between the margin and 1.0 for any margin < 1) — the one
  test in the batch that correctly derives its input from the live threshold.
  `TestSoft.test_blended_score_can_outrank_a_better_raw_match` and
  `TestBlended.test_can_flip_the_sink_decision_itself` were both recomputed and are genuinely
  discriminating; `test_topk_pick_margin_is_relative_to_the_best_non_sink` distinguishes the two
  candidate implementations; `is_sink_flags` tests hand-evaluated and genuinely catch a keys/values
  misalignment.
- T4: `test_topic_grouping.py` is the strongest file in its batch — every test is a partition property
  over hand-built angle vectors, thresholds passed in per test, and
  `test_loosely_related_coachable_group_splits_apart` reproduces the real 21-member mega-blob at unit
  scale. `test_threshold_controls_aggressiveness`'s ~0.9507 cosine pair was **recomputed** and sits
  comfortably inside its 0.90/0.99 bracket, so it survives any shipped-threshold change.
- T6: `shared/skills.py::cluster_behaviours` centroid renormalisation — the current vector spread was
  deliberately chosen so the un-normalised running mean falls below the threshold while the true
  cosine stays above it, with the reasoning recorded in the test docstring. `null_pairs` direction is
  genuinely constrained (reversing the sort at `trial_skills.py:268` fails the `< 0.5` assertion).
  `assign_swap_batches`' C1 memory-contamination guarantee is **property-tested over 200 random
  `(n, batch_size, seed)` shapes** — the strongest test in the wave.

**Fixture-shape drift — checked and clean in four batches**
- T1: `_turn()` supplies all five `EgoTrapTurn` fields; `EgoTrapRole` has exactly the three members the
  tests use; `_v2_milestone` carries all ten keys `v2/layer_c._finish_rubric` writes, and
  `_EVIDENCE_FIELDS` is fully covered.
- T2 (**MEASURED** — field-by-field against the producing SQL): `_resp()` produces exactly the four
  keys `storage.get_responses_for_scenario_multilabel` returns (`storage.py:342-345`); the
  `EgoTrapTurn(...)` positional construction matches the dataclass field order; `_scn()` matches
  `get_scenarios`'s row keys.
- T4: `_GOOD` in `test_tuning.py` cannot silently drift — the loader raises on *missing* keys, and
  `_GOOD` was diffed against all five dataclasses including the newest fields (`scoring_unit`,
  `pool_unit`, `describe_mode`, the `gemini_*` block). `Turn(...)` matches
  `preprocessing/transcript_parser.py:16-21` field-for-field.
- T5: `_real_milestone` matches the JSONB `_finish_rubric` stores field-for-field; the only production
  field absent is `precondition` (added by the situated path), and `with_validation` copies unknown
  fields wholesale, so its absence does not weaken the preservation test.
- T6: `test_response_taxonomy.py`'s autouse embedder stub patches `embedder.embed_document`, and
  `shared/scenario_vectors.py:31` and `:37` both call exactly that (not the `_matrix` variant) — the
  stub really does prevent the model loading.

**No mock-returns-X-assert-X anywhere in T1 or T3** (both auditors checked explicitly). Every
`mocker.patch` of `call_gemma` is followed by an assertion on *transformed* output or on the *prompt
that was built*; the embedder is mocked in four Layer B files but every assertion is on the routing
decision, never on the vector that came back.

**Two corpus-scale facts measured in passing, recorded so they are not re-investigated**
- T2 (**MEASURED** — all 1,945 speaker entries checked): only **3** have `is_rep=True` with a
  non-joveo email (2 files, both `"db"` placeholder emails) and **0** have `is_rep=False` with a joveo
  email, so the `entry.get("is_rep")` branch at `preprocessing/transcript_parser.py:57` is currently
  near-exact. Too small to move any reported number.
- T3 (**MEASURED** — line-by-line diff): `shared/relative_match.flat_pick` is byte-equivalent to the
  inline loop in `assign_scenarios` (`v1/layer_b.py:127-144`) — same `argsort[::-1]`, same sink
  short-circuit, same `margin * sims[best]` cutoff, same `order[:cap]` slice, same `kept or [best]`
  fallback. The extraction did not change production behaviour.

**Two cosmetic name/assertion mismatches deliberately NOT reported as findings** (T4): both tests still
constrain real behaviour — `test_orthogonal_to_everything_gives_low_similarity`
(`test_cluster_evidence.py:130`) probes an *anti-parallel* vector and asserts the correct maths
(`-1/√3`); `test_label_primary_topics_batch_deduplicates_colliding_labels` describes a *cross-batch*
collision but the dedup it exercises is batch-agnostic.

**One scope note, not a defect** (T5): `shared/coverage_areas.py`'s docstring says *"Selected by
layer_c.describe_mode == 'coverage'"*, but `run_layer_c_v2` branches only on `"situated"`
(`v2/layer_c.py:802`) and `shared/tuning.py:63` declares `describe_mode: str` with no enum validation.
`tests/test_tuning.py:110` asserts the live value is in `("legacy", "situated")`, which would catch a
`coverage` setting loudly. The coverage path is reachable only from
`calibration/trial_layer_c_arms.py`.

---

## WHICH TESTS CONSTRAIN A REPORTED NUMBER

| test file | constrains a reported number | which number |
| --- | --- | --- |
| `test_call_scoring.py` | **yes** | check 2's verification rate (`verified`/`checked`/`rate`, the literal numerator and denominator of the ≥0.95 gate); `parse_response`'s missing-id defaulting, which sets the per-scenario `W` the sign test consumes. Not `W` itself, not the sign test. Findings C5, #27, #32 all sit inside the one number it does constrain. |
| `test_ego_trap_milestone_scoring.py` | **yes** | the verdict tiers and the `attempts` denominator — missing id → `miss`, unrecognised verdict → `miss`, and the positional-id invariant under both `skip_uncoachable` and `require_validated`; these decide `hits`, `partial_hits` and which `milestone_performance` row a verdict lands on. Not the batch's own shortfall reporting (#23) or model provenance (#33); `score_coverage_batch` untested here. |
| `test_ego_trap_signal_check.py` | **intends to but cannot run** | the 14 tests covering the accept/reject rule that produces the signal count — and therefore `attempts` — all die in the stale fixture (C4). What still runs is string matching and shortlist ordering, which fix no reported figure. |
| `test_ego_trap_gap_output.py` | **yes** — the strongest file in T1 | `milestone_miss_rate` as the exact complement of `(hits + 0.5*partial)/attempts` across four triples; the 0.5 partial weight; severity thresholds read from live `tuning.yaml`; and the `attempts` write path (one `upsert_milestone_performance` per scored milestone regardless of `gap_events_enabled`). |
| `test_ego_trap_scenario_pool.py` | **yes** | `pool_summary` counts (total / coachable / sink-by-kind / no-rubric) and `coachable_only`, which sizes the gemma-mode prompt menu (161→85 scenarios, 32,575→19,778 chars). |
| `test_ego_trap_rubric_lookup.py` | **partly** | the ranking-order tests constrain *which* of Naren's responses reach the Step 3 prompt, which feeds `W`. The cap's *value* is unconstrained (#17); the short-circuit contract is blessed rather than constrained (#16). |
| `test_ego_trap_transcript_parser.py` | **yes — and wrongly** | it constrains `classify_response_outcome` to produce the 98.6% artifact (C2). |
| `test_transcript_parser.py` | **no** | constrains only the roster-free fallback, which is not the production path for the 416-call corpus (#14). |
| `test_segmenter.py` | **only the floor** | the `len(sent) < 4` cutoff, pinned at `>= 4`, free to rise to 13 (#4). |
| `test_gemma_retry.py` | **no number** | guards a crash path; one of its two tests is inert (#34). |
| `conftest.py` | **no** | path setup only. |
| `test_layer_b_assignment.py` | **yes** | `assign_scenarios` is production; two tests read `load_tuning().layer_b`, genuinely constraining `relative_margin` and `max_scenarios_per_pair` behaviour, which produce `kb_pairs.scenario_key(s)` — the 4,605 pairs, the 39.7% sink-absorption rate and Layer C's per-scenario response pool. Caveat: the cap test does not cover a sink inside the cap window (C1). |
| `test_layer_b_v1.py` | **yes, but thinly** | `extract_pairs`'s output count (4,605 kb_pairs). Three of four tests are real; the fourth is vacuous (#22). Nothing exercises `_MIN_CONTENT_WORDS = 5` deliberately. |
| `test_relative_match.py` | **partly** | `topk_pick` is live in Layer D similarity mode and `flat_pick` backs the sink-rescue calibration baseline, so the rule is real — but every test passes `margin` and `cap` as literals, so **no test here constrains any `tuning.yaml` value**, and the one that claims otherwise is #11. |
| `test_two_stage_matching.py` | **no for production** | `matching_strategy: flat`. It backs a *published comparison* — the 79.6/85.9/86.6% agreement figures and the `two_stage_fallback_floor` sweep — via #28 and #29, both of which weaken that backing. |
| `test_sink_rescue.py` | **no for production** | `sink_rescue_strategy: none`. It backs the published 95.2% / 8.5% / 22.4% rescue rates; five tests exercise real threshold-coupled behaviour with explicit range guards, one is unfalsifiable (#30). |
| `test_cluster_evidence.py` | **yes, partially** | `TestMilestoneSupport` pins the arithmetic behind `min_milestone_call_fraction`/`min_milestone_calls_floor` (the 385–404 milestone figure); `test_counts_distinct_calls_not_items` pins `call_coverage = distinct/total`, feeding `ubiquity_ceiling`. But `required_call_support` is untested (#24) and `TestPassesReconciliationGate` constrains nothing beyond a `<` (#9). |
| `test_topic_grouping.py` | **yes, structurally** — strongest in T4 | the *rule* that produces the `primary_topics` count (80 in the 2026-08-02 run), not a frozen count. No hardcoded shipped threshold anywhere. |
| `test_layer_a_v2_primary_topics.py` | **yes, one row** | `support_calls=2`, `support_subtopics=1`, `call_coverage=1.0` — the exact fields written to `primary_topics`; `call_coverage` is computed from the fixture, not copied. Weakened by #25. |
| `test_layer_a_pool.py` | **yes, structurally** | the mechanism behind the 73,771-clause vs 23,949-turn pool sizes and the 12.2% of client turns contributing nothing in clause mode. Pins the shape, not the corpus numbers. |
| `test_tuning.py` | **weakly** | `test_pool_unit_is_present_and_ships_clause` is a genuine constraint on a shipped value. `test_shipped_tuning_yaml_is_valid` constrains ranges for a hand-picked subset that misses the load-bearing knobs (#3). |
| `test_layer_c_clause_pool.py` | **indirectly, and weakly** | the clause pool feeds the milestone count (~[350,450]) and every `support_clauses`, but the assertions are arity/index-alignment/positions, not magnitudes. The one number-bearing constant it claims to pin is loose across [1,6] (#5). The 4-value extraction contract and `pair_id` provenance ARE constrained. |
| `test_layer_c_describe.py` | **no** | eight tests over a five-line `dict.setdefault` group-by; every assertion is a property Python's insertion-ordered dicts guarantee. No batch size, call count, `W` or milestone count constrained. |
| `test_coverage_areas.py` | **yes** | `ca.score` is what `trial_layer_c_arms.arm_summary` reports as the coverage arm's `w`, `w_conditional` and `not_called_for_rate` — the 64.9%-vs-65.7% figures. `WIDE_MERGE_MOVES == 4` pins only a printed flag. |
| `test_rubric_validation.py` | **yes — the file that matters** | the four per-milestone thresholds and both scenario bands, which decide SHIP/HOLD/DISABLE. See C3, #7, #37. |
| `test_validate_rubrics.py` | **partly** | constrains the aggregation feeding `applicable_rate` and discrimination (`build_verdicts`, `applicability_counters`), but leaves the two functions producing and gating the headline — `scenario_verdicts` and `_self_check` — completely untested. See #8, #20, #21. |
| `test_naren_ceiling.py` | **partly** | pins the pre-registered gate constants `_T_WORKS/_T_BROKEN/_T_INSTRUMENT = (0.50, 0.20, 0.5)` and `_MIN_ATTEMPTS_TO_INDICT = 6`, and the `W = (hits + 0.5·partial)/attempts` definition every reported `W` uses. Constrains **nothing** about how A1/A3/B are populated — i.e. nothing about the ratio that was published and retracted (C6). |
| `test_head_to_head.py` | **yes, for the arithmetic** | `swap_agreement` (C1 = 0.669), `win_rate` denominators, `order_average`'s disagreement→tie rule and `length_matched`'s band, including the load-bearing "both-ties are excluded, not counted as agreement" rule. `adjacent_rank_pair`'s adjacency (C2) is the one exception (#12). |
| `test_skills.py` | **no** | every assertion is on hand-built orthogonal vectors; no threshold, count or rate is pinned. It does correctly constrain the *rules* (unit-centroid renormalisation, `scenario_span`, `UNASSIGNED` rather than nearest-forced). |
| `test_trial_skills.py` | **yes — the strongest number-pinning in the wave** | the exact published member floors `{38, 23, 12, 24}`, re-derived by the auditor from `_MEASURED_ATTEMPTS=889`, `_MEASURED_MILESTONES=405`, `_NOISE_BAND=0.006`, `_MEASURABLE_CHANGE=0.020`, `_RANK_DELTA=0.05` — all four correct. `NULL_MIN_REJECT=0.80` and `V_MIN=0.80` pinned through `null_passed`/`evaluate_window`. Offset by C7. |
| `test_trigger_quality.py` | **marginally** | the *direction* of `sink_real_margin` (positive = filler-like) — the fact CLAUDE.md needed to correct its published AUC from "0.437, worse than chance" to "0.563, direction-corrected". No AUC or rate constrained. |
| `test_response_taxonomy.py` | **no** | the purity gate is exercised at exactly its boundary (9/10 = 0.90 = `purity_gate`), pinning `>=` rather than `>`; nothing else. `nearest_coachable_sim` — the value feeding `passes_reconciliation_gate` and therefore graduation — is never asserted, by the fixture's own admission. |
| `test_response_taxonomy_auto_pass.py` | **partly** | `response_taxonomy_candidate_match_overlap = 0.5` is exercised on both sides of the boundary and the intersection *write* is pinned. The graduation *read* is not (#6). |
| `test_graduate_sink_topics.py` | **indirectly, and brittly** | `test_skips_when_reconciliation_gate_fails` (sim 0.90) and `test_writes_expected_insert_and_reroute_sql` (sim 0.726) straddle the live `layer_a.merge_cosine_threshold = 0.85` by reading it at runtime, so the pair genuinely pins that the gate is `sim < threshold` — but both would break if that knob were re-calibrated outside (0.726, 0.90). Worth knowing before touching that key; not itself a defect. |

---

## CLAUDE.md CORRECTIONS FROM THIS WAVE

*(Listed only. No edit to CLAUDE.md was made.)*

**X1. Claim**: *"Use `usable_item_fraction` (share of ITEMS in a group at or above the floor) alongside
it — a mega-blob split cannot fool that."* (skills-vocabulary section, harness-bugs bullet)
**Undermined by**: C7 / W1-T6#1 — the metric scores the pathological split 0.973 and the healthy split
0.976, a 0.003 separation; it is also never called anywhere.
**Suggested correction**: the median's small-K blind spot is **still open**; `usable_item_fraction` as
written does not close it (the mega-blob is itself above the floor and counts as usable), and it is a
dead function with no call sites.

**X2. Claim**: *"`tuning.yaml` keys are validated on load — an unknown or missing key raises rather
than silently falling back to a default."* (Gotchas)
**Undermined by**: #3 / W1-T4#2 — `load_tuning` validates **keys only, never values**; the sole
value-sanity gate is a hand-maintained whitelist in `test_tuning.py` that omits `layer_b.relative_margin`
and both `layer_c` percentiles.
**Suggested correction**: add "keys, not values — a decimal-point slip in any *value* loads silently;
the only value bounds are a partial whitelist in `tests/test_tuning.py`."

**X3. Claim**: *"Every Layer D knob is now a validated `tuning.yaml` key under `layer_d:` … a stale
line there reads as authoritative while doing nothing, which is worse than either state."* (Gotchas)
**Undermined by**: #19 / W1-T1#4 + W1-T4#6 — `layer_d.scoring_unit` has no consumer anywhere in
`Brain/**/*.py`; `ego_trap/pipeline.py` never reads it and `call_scoring.py` is imported only by a
calibration harness.
**Suggested correction**: note the one exception — `layer_d.scoring_unit` is declared, documented as a
gate, and read by nothing; setting it to `call` changes no behaviour.

**X4. Claim**: *"Pinned by `tests/test_relative_match.py::test_margin_is_inert_at_cap_one` so the note
cannot quietly stop being true."* (Layer D margin-inert gotcha)
**Undermined by**: #11 / W1-T3#2 — the test hardcodes `cap=1`, making the assertion a tautology of
`topk_pick`. Nothing asserts `layer_d.max_scenarios_per_signal == 1`; `test_tuning.py:115` only asserts
`>= 1`.
**Suggested correction**: the note **can** quietly stop being true — raising
`max_scenarios_per_signal` to 2 invalidates it with the whole suite green.

**X5. Claim**: *"`shared/relative_match.py` (new) — `_topk_pick`/`_flat_pick` extracted verbatim …
Behaviour-preserving, proven by the 35 pre-existing tests … passing unchanged."*
**Undermined by**: C1 / W1-T3#1 — `flat_pick` *is* byte-equivalent to production's inline loop (T3
verified this separately), but `flat_pick` and `topk_pick` apply the sink filter and the cap in
**opposite orders**, and `test_flat_pick_matches_topk_pick_when_the_best_is_not_a_sink` asserts their
equality on an input with no sinks.
**Suggested correction**: the extraction preserved `assign_scenarios`, but `flat_pick` and `topk_pick`
are **not** the same rule — Layer D (topk) and the sink-rescue baseline (flat) apply different cap
semantics whenever a sink lands inside the top-`cap`.

**X6. Claim (DEFECT 1)**: the segmentation artifact is described as a production defect in
`transcript_parser.turns_until_next_client`.
**Undermined by**: C2 / W1-T2#1 — the artifact is also **asserted as intended behaviour** by the only
test of `classify_response_outcome(...) == "none"`, whose sibling docstring calls it *"the true-silence
'none'"*.
**Suggested correction**: add that fixing it requires changing a test that currently certifies the
defect, and that no test covers the 35 genuinely-silent last-turn-of-call cases.

**X7. Claim**: the ceiling retraction records the arm-construction asymmetry as diagnosed and closed.
**Undermined by**: C3 / W1-T5#1 — `SCENARIO_MIN_ATTEMPTS = 15` and `SCENARIO_BAND = 0.05` in
`shared/rubric_validation.py` were **fitted** to reproduce the retracted table and are still shipped
and still asserted as calibrated; `validate_rubrics._items_for` now runs a symmetric comparison through
that asymmetric band, and `_self_check` validates itself against `artifacts/naren_ceiling.json`.
**Suggested correction**: the retraction invalidates the two scenario bands and `T_DISCRIMINATION` /
`T_SATISFIABLE` downstream; the SHIP count is inflated and the DISABLE count deflated until they are
re-derived on a symmetric arm B.

**X8. Claim**: *"graduation reads `stable_pair_ids`, not the latest snapshot, specifically so a pair
that only appeared in one noisy clustering run drops out automatically."*
**Undermined by**: #6 / W1-T6#4 — the graduation *read* is unpinned: the fixture sets
`member_pair_ids` and `stable_pair_ids` to the same list, so changing line 257 to `member_pair_ids`
passes the entire suite. Only the *upsert* half is genuinely tested.
**Suggested correction**: note that this behaviour is a code fact, not a tested guarantee, and the
"164 pairs rescued" figure would inflate silently if it regressed.

**X9. Claim**: *"SYMMETRIC FILTERING … A guard belongs in the harness (a printed population diff, or an
assert), not in a reviewer's memory."* — cited as fixed in `trial_head_to_head.py`.
**Undermined by**: #13 / W1-T6#7 — the fix is enforced by two statements 564 lines apart, `grep -rn
"trial_head_to_head" Brain/tests/` returns nothing, and deleting line 801 restores the original bug
with no test failure. The only guard is a printed counter.
**Suggested correction**: the guard is a *print*, not an assert; it is exactly "in a reviewer's
memory" by the rule's own standard.

**X10. Claim (DEFECT 2 refutation)**: *"`situated_fields` supplies all three; discrimination went 6.00
(blind) → 6.64 (turn) / 4.48 (label) / 5.84 (all three) with heavily overlapping CIs — no ordering, no
effect."*
**Undermined by**: #15 / W1-T1#5 — `score_milestones_batch` silently falls back to the byte-identical
production prompt when no situated field has a value (a v1 rubric has no `label`), and the `emitted`
counter is computed then discarded, so the trial cannot report what fraction of items received the
treatment. A partly-zero dose biases toward the null, which is the reported result.
**Suggested correction**: mark the refutation as conditional on the treatment dose, which was never
measured; the instrument cannot report it by construction.

**X11. Claim**: *"changing its cutoff would silently rewrite Layer C's milestone pool"* (segmenter,
Layer A pool-unit section).
**Undermined by**: R1 / W1-T2#2 + W1-T5#4 — true, and additionally **no test in the suite constrains
the cutoff from above**: `test_segmenter.py` tolerates 4→13 and `test_layer_c_clause_pool.py` tolerates
1→6, while the latter's module docstring claims the filter is *"pinned by its own test"*.
**Suggested correction**: append "and nothing in `tests/` would catch it — both segmenter test files
pin the cutoff only from below."

**X12. Claim**: *"`parse_transcript` without the `roster` argument misclassifies speakers (28,905
CLIENT turns vs the true 23,949)"* — cited as a measurement-script lesson.
**Undermined by**: #14 / W1-T2#3 — the *production* roster path has zero test coverage; all six tests
in `test_transcript_parser.py` pass `roster=None`, so the ~20%-inflating fallback is the only branch
the suite exercises. A latent bug lives in the untested branch (exact-equality check at
`preprocessing/transcript_parser.py:55` vs `_match_roster_entry`'s prefix match would route a bare
`"Naren"` line to `JOVEO_OTHER`).
**Suggested correction**: add that the roster branch is untested, so the corpus's CLIENT-turn count and
every Layer A coverage figure rest on an unexercised code path.

**X13. Minor bookkeeping**: CLAUDE.md records *"319 tests across 23 files as of 2026-08-10"*. Wave 1
covered **34 files** in `Brain/tests/`.
**Suggested correction**: the file count is stale; the line already advises using
`pytest tests/ --collect-only -q` rather than trusting it — that advice should be strengthened to
cover the file count too.
