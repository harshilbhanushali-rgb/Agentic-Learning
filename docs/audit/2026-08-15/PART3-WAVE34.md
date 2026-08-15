# PART 3 — Waves 3 & 4 consolidated

Sources: `W3-P1.md`, `W3-P2.md`, `W3-P3.md`, `W4-PROV.md`, against the shared taxonomy in
`BRIEF.md`. Synthesis only — no new auditing, no fixes. Every line traces to an input file.

---

## Wave 3 — production code

Three auditors covered the production path that computes or filters what gets measured:
**P1** the storage layer and shared numeric helpers (`shared/storage.py`, `relative_match.py`,
`cluster_evidence.py`, `scenario_vectors.py`, `tuning.py`); **P2** the input path and Layer D
(`preprocessing/{transcript_parser,segmenter,embedder}.py`,
`ego_trap/{pipeline,signal_check,gap_output,rubric_lookup}.py`); **P3** the pipeline layers
themselves (`v2/layer_a.py`, `v2/layer_c.py`, `v1/layer_b.py`, `response_taxonomy_auto_pass.py`).
**28 findings total** (P1 6, P2 8, P3 14). Confidence: **27 rest on a mechanism the auditor marked
`certain`** (read line-by-line from code, and in P2's case measured with read-only probes over
`csm_recordings/`); **1 is `likely`** (P1 #5, a threshold-band transfer whose mis-assignment is
unverified). Eight findings carry an explicitly weaker *magnitude* rider marked `likely`
(P1 #1, #3, #6; P2 #8b; P3 #1, #4, #11, #12) and two carry a rider marked `speculative`
(P2 #7's punctuation-driven admission rate; P3 #7 as the explanation for the coachable drift).
Two auditors independently found the same `flat_pick`/`topk_pick` cap divergence (P1 #1 = P3 #4),
which is consolidated below.

---

### CANDIDATE TOP FINDINGS (WAVE 3)

#### T1. Layer C's "relevance filter" is a fixed 60% quota, not a filter — it can never reject anything and never fails
- **File:line**: `Brain/v2/layer_c.py:108-109`
- **What is wrong**: `cutoff = np.percentile(relevance, percentile)` then `keep = relevance >= cutoff`.
  A percentile *of the population being filtered* always keeps exactly `100 − percentile` percent of
  it (ties aside). At the calibrated `milestone_relevance_percentile: 40` this drops the bottom 40%
  of clauses from **every** scenario regardless of whether any clause is off-topic, and keeps 60%
  even if every clause is off-topic. The docstring frames it as "drop response clauses that are not
  about the scenario", and the printed line `Relevance filter (>40th pct): 2315 -> 1389 clause(s)`
  reads as though the ratio were informative — it is 0.60 by construction in every run.
- **What number it corrupts, and in WHICH DIRECTION**: Taxonomy item 5. For a clean scenario it
  **deflates** the milestone clause pool by 40% for nothing; for a contaminated one it **cannot**
  remove the contamination. It also invalidates any reading of the percentile sweep as a *quality*
  knob — the sweep was measuring pool size. Mechanically explains the recorded open finding
  "deliberately wrong placebo clauses survived the p40 cut at 53.9–57.2% vs 57.7–63.0% for real
  content"; a quota cannot separate them and the ~6-point gap is only the residual ordering effect.
- **Confidence**: certain
- **Cheapest verification**: read the two lines; or `grep "Relevance filter" Brain/logs/*.log` and
  confirm every `N -> M` line has `M/N ≈ 0.60`.

#### T2. A mixed CSM/teammate response window is graded as if the CSM said all of it — while the CSM is handed only their own fragment
- **File:line**: `ego_trap/rubric_lookup.py:91-94` (`extract_csm_response_window`), against
  `ego_trap/transcript_parser.py:100-103`
- **What is wrong**: `classify_response_outcome` returns `"csm"` if **any** CSM turn appears in the
  window, but `extract_csm_response_window` then joins **only** the CSM turns, dropping every
  `OTHER_JOVEO` turn. When a teammate gives the substantive answer and the CSM says "yeah, exactly",
  the exchange is *not* reclassified as `Deferred_To_Teammate` (that fires only when there is **no**
  CSM turn at all), and the CSM's fragment is scored against the full rubric. The
  `Deferred_To_Teammate` protection has a hole exactly where it is most needed.
- **Measured over the 2,351 scored (`csm`) windows across 106 mapped CSM transcripts**:
  **408 (17.4%) are mixed** CSM + teammate; in **158** of those the CSM contributed **<34% of the
  words**; **384 windows (16.3% of all scored windows) contain ≤5 CSM words in total** and are
  graded against a rubric averaging ~6 milestones. Median CSM word share inside a mixed window 0.51;
  median CSM words in a scored window 39.
- **What number it corrupts, and in WHICH DIRECTION**: `milestone_performance.hits` /
  `partial_hits` are **deflated** and `milestones_missed` **inflated**, unambiguously — a 5-word
  acknowledgement cannot satisfy a criterion. A direct, unexamined contributor to the ~9%
  `W(matched)` level the whole profile effort has been trying to explain, and unlike wording it is a
  *population* defect, so no prompt change touches it.
- **Confidence**: certain (mechanism), certain (rates; measured on real transcripts)
- **Cheapest verification**: read `ego_trap/rubric_lookup.py:94` (the `if t.role ==
  EgoTrapRole.CSM` filter) next to `ego_trap/transcript_parser.py:100`, which does not require the
  CSM to be the *only* responder.

#### T3. DEFECT 1 confirmed and quantified — 45.8% of client turns are structurally unscoreable, and 98.7% of `Signal_Recognition_Failure` is the segmenter, not a CSM
- **File:line**: `ego_trap/transcript_parser.py:78-89` (`turns_until_next_client`), `:92-104`
  (`classify_response_outcome`), consumed at `ego_trap/signal_check.py:240` and `:339`
- **What is wrong**: `turns_until_next_client` iterates `turns[start_index + 1:]` and `break`s on the
  first `CLIENT` turn. When `turns[start_index + 1]` is itself CLIENT the window is `[]` and
  `classify_response_outcome` returns `"none"` **before any evidence is consulted**. No counter, no
  warning distinguishing this from real silence.
- **Measured over all 106 mapped CSM transcripts (6,468 CLIENT turns)**: `csm` 2,351 /
  `other_joveo` 1,117 / `none` **3,000**. Of the 3,000 `none`, **2,962 (98.7%) are immediately
  followed by another CLIENT turn**, 38 are the last turn of the call, and **0 are genuine silence**.
  Reproduces the recorded 98.6% on a slightly larger corpus.
- **What number it corrupts, and in WHICH DIRECTION**: `signal_recognition_gaps.missed` /
  `.occurrences` **inflated by ~98.7% of their `missed` mass** — the `39/61 (64%) missed` figure in
  `ego_trap/RUN_NOTES.md:34` is this artifact; nothing in the codebase READS this table, so the
  corruption reaches humans only through hand-written SQL, which is why it survived. Every
  `gap_events` row with `gap_type = "Signal_Recognition_Failure"` inflated by the same factor.
  **A second consequence not in the recorded write-up: the SCORED population is a biased subset** —
  only a client turn *last in its contiguous block* can ever reach `outcome == "csm"`, so **45.8% of
  client turns can never be scored at all, by construction** (taxonomy items 2 and 13). Direction
  measured rather than assumed: excluded turns are **shorter** (median 17 words vs 25, mean 32.6 vs
  39.4), so the bias is mild and runs *toward* excluding filler — but
  `milestone_performance.attempts` is drawn from a non-random half of the corpus and is
  **understated by roughly a factor of two** relative to "moments a client raised something".
- **Confidence**: certain (mechanism read from code; counts measured)
- **Cheapest verification**: `ego_trap/transcript_parser.py:85-88` — `if t.role == CLIENT: break`
  executes on the first iteration whenever the next turn is CLIENT, so `result` is `[]` and both
  `any(...)` tests at `:100`/`:102` are False.

#### T4. `extract_pairs` silently discards every CLIENT turn in a consecutive client block except the last — and discards the WHOLE block if the last turn is filler
- **File:line**: `Brain/v1/layer_b.py:51-70` (the `else: break` at `:59-60` and
  `i = j if response_parts else i + 1` at `:70`)
- **What is wrong**: The inner loop walks forward from a client turn and **breaks on the first turn
  that is neither NAREN nor JOVEO_OTHER** — i.e. on the next CLIENT turn. For `[C1, C2, NAREN]`, C1
  breaks immediately with `response_parts == []`, is dropped, and only `(C2 -> NAREN)` becomes a
  pair; C1's text never enters `kb_pairs` as a trigger or a response. Worse, if the *last* turn of
  the block fails `_is_substantive` (`[C1(substantive), C2("Yeah."), NAREN(substantive)]`), C1 breaks
  out, C2 is filtered, and the block yields **zero pairs** — both the real client question and
  Naren's substantive answer are lost. Nothing counts any of this.
- **What number it corrupts, and in WHICH DIRECTION**: Deflates `kb_pairs` (the input population for
  Layer B, Layer C's clause pool and every rubric), and — more damagingly — **systematically biases
  `trigger_text` toward the last fragment of each client speech block**, the fragment most likely to
  be a trailing "so yeah, anyway". Layer B's sink decision is made on `trigger_text` alone, so this
  **inflates the sink-filing rate**. Same defect class as the recorded Layer D
  `turns_until_next_client` DEFECT 1 (measured there: 2,449 of 5,731 client turns — 43% — are
  immediately followed by another CLIENT turn), one layer earlier and, as far as the auditor could
  find, never diagnosed for Layer B. If the Naren corpus has a comparable rate, ~40% of client turns
  cannot become a trigger by construction — a plausible mechanical cause of the 39.7–45.8% sink
  absorption that eight signals and four design docs searched for a *scoring* explanation for.
- **Confidence**: certain for the mechanism (traced line by line); **likely** for the magnitude,
  which is inferred from the measured CSM-corpus rate rather than measured on `recordings/`
- **Cheapest verification**: free, no DB — parse the 416 transcripts with
  `preprocessing.transcript_parser.parse_transcript`, count client turns whose next turn is also
  CLIENT, compare to `len(extract_pairs(turns, 0))` per file.

#### T5. `flat_pick` and `topk_pick` apply `cap` to DIFFERENT populations — production Layer B is stricter than every harness that measures it (found independently by P1 and P3)
- **File:line**: `Brain/shared/relative_match.py:81-89` vs `:108-116` (P1 cites `:89` vs `:114`), and
  the production inline copy at `Brain/v1/layer_b.py:140-143` (P1 cites `:141`)
- **What is wrong**: `flat_pick` — and the byte-identical inline rule production `assign_scenarios`
  runs — takes `order[:cap]` **first** and discards sinks afterwards, so a sink at rank 2 consumes
  one of the 3 slots and evicts a qualifying real match. `topk_pick` builds the non-sink candidate
  list **first** and then slices `candidates[:cap]`. Worked example at `cap=3, margin=0.95`
  (cutoff 0.855), `sims = [realA 0.90, sink 0.89, sink 0.88, realB 0.87]` → `flat_pick` returns
  `[realA]`, `topk_pick` returns `[realA, realB]`. 76 of 161 live scenarios (47%) are sinks, so this
  is routine. The module docstring says the rule lives "in one place" and that `flat_pick` was
  "moved verbatim"; `topk_pick`'s own docstring states the rule `flat_pick` does **not** implement.
  The guard that should have caught it is vacuous: `tests/test_relative_match.py:149
  test_flat_pick_matches_topk_pick_when_the_best_is_not_a_sink` passes `is_sink = [False, False,
  False]`, a case in which they cannot differ.
- **What number it corrupts, and in WHICH DIRECTION**: **Deflates** the width of
  `kb_pairs.scenario_keys[]` in production — the measured "63% one / 19% two / 18% three" is partly
  sinks eating cap slots, a *second* narrowing beyond the documented sink short-circuit, and one
  that also hits pairs whose best match is a real scenario. **Deflates** the candidate pool of
  `get_responses_for_scenario_multilabel` (Layer D's benchmark-reference pool), so the "2,904 →
  5,463 responses" gain is smaller than the rule alone would give. **Taxonomy item 1** in the
  comparison harnesses: `topk_pick` is what Layer D uses, what `assign_scenarios_two_stage` uses for
  **all three** strategies (including `fallback`'s supposedly-flat branch at `v1/layer_b.py:231`),
  and what `calibration/compare_matching_subset.py` imports as `_topk_pick` — so the two-stage-vs-
  flat comparison (86.6% subset / 61.3–77.0% full-corpus recall-proxy) has a **second uncontrolled
  variable**, and the direction favours the two-stage arms. Any "match width" figure derived from
  `topk_pick` **inflates** the multi-label rate relative to what production writes.
- **Related (P1 #4, certain code fact, no live number): production `assign_scenarios` does not call
  the shared helper at all** — it imports `is_sink_flags` but keeps its own inline copy of the
  short-circuit and the `order[:cap]` loop (`v1/layer_b.py:127-144`). The two copies are currently
  byte-equivalent, so nothing moves today; it is the mechanism by which T5 could be "fixed" in
  `shared/relative_match.py`, verified by the tests, and leave **production unchanged** while every
  harness then measures a rule production does not run.
- **Confidence**: certain that the two functions differ (worked example); **likely** on the size of
  the width effect and on how much it moved the two-stage numbers — both unmeasured
- **Cheapest verification**: zero cost — add a sink between the ranks in the existing equivalence
  test: `flat_pick(np.array([0.90,0.89,0.88,0.87]), keys, [False,True,True,False], 3, 0.95)` vs
  `topk_pick(...)`. Production sizing: `SELECT array_length(scenario_keys,1), count(*) FROM kb_pairs
  GROUP BY 1;`

#### T6. Layer A's adjudication decision fails OPEN to "coachable", and no counter records it
- **File:line**: `Brain/v2/layer_a.py:505` and `:531-532`
- **What is wrong**: `decision = (result.get("decision") or "new_scenario").strip()` — a Gemma
  response that omits `decision` becomes a new coachable scenario. Then
  `_KIND_BY_DECISION.get(decision, cluster_evidence.KIND_SCENARIO)` — any value outside
  `{new_scenario, mechanics, not_coachable, merge_into}` (a typo, a synonym, `"logistics"`, `"sink"`)
  silently becomes `KIND_SCENARIO` / `is_coachable=True`. The three literals **do** match
  `PROMPT_LAYER_A_V2_TRIAGE` (`shared/prompts.py:852-860`), so this is not an item-4 name mismatch —
  it is an item-8/10 fail-open on a four-valued enum, with the default on the permissive side and no
  counter or warning.
- **What number it corrupts, and in WHICH DIRECTION**: **Inflates the coachable-scenario count** and,
  downstream, the rubric count and the `is_coachable` sink-routing signal Layer B and Layer D both
  key off. A live candidate cause of the recorded, un-root-caused "~5-6% of clusters (7-10 of 158)
  flip across the coachable/mechanics boundary between independent runs on identical clusters".
- **Confidence**: certain that the code fails open; **speculative** that it explains the run-to-run
  flips
- **Cheapest verification**: free — `SELECT cluster_kind, triage_verdict, count(*) FROM scenarios
  GROUP BY 1,2` and look for coachable rows whose `adjudication_reason` is empty.

#### T7. `min_cluster_size_ceiling` freezes Layer C's granularity at a hardcoded 25 — and it demonstrably binds (P1 #3 = P3 #9)
- **File:line**: `Brain/shared/cluster_evidence.py:193-197`, called from `Brain/v2/layer_c.py:232-235`;
  values at `tuning.yaml:435-437` (`fraction 0.02, floor 3, ceiling 25`); the Layer A sibling is
  `Brain/v2/layer_a.py:96-98`
- **What is wrong**: `int(max(floor, min(ceiling, round(fraction * pool_size))))` is a genuine
  fraction only while `0.02 * pool_size < 25`, i.e. below **1,250 clauses**; above that it is the
  literal 25 forever. A 3,000-clause scenario clusters at a 0.83% bar while a 600-clause one
  clusters at 2%. Exactly the shape taxonomy item 15 names (`max(3, min(n//10, 50))`), and a
  violation of this project's own "a threshold must never be a count" rule. It demonstrably fires:
  the recorded sink-pool diagnostic logged `0.02 × 3730 = 74.6` clamped to 25, and CLAUDE.md records
  clause pools of 2,315 and 3,239 for `client_requests_operational_visualization` alone.
- **What number it corrupts, and in WHICH DIRECTION**: **Inflates** the milestone-candidate count
  for large scenarios relative to small ones (a proportionally *looser* bar), directly contradicting
  the sibling docstring at `cluster_evidence.py:181-190` ("a 200-call scenario cannot accumulate
  milestones merely by being large"). Per-scenario milestone counts are therefore not comparable
  across the corpus, and the total milestone count (the 385/398/404 band used as the run-health
  indicator) is partly a function of pool size rather than of content — it is not invariant to
  corpus growth the way the formula suggests. The recorded sink-pool diagnostic attributed the
  resulting **47.3% HDBSCAN noise** to "coarse clustering"; the ceiling is why.
- **Confidence**: certain on the arithmetic and the mechanism; the recorded clamp measurement
  confirms it binds. **Likely** on the size of the effect (the downstream
  `required_milestone_support` gate absorbs some of it, and `tuning.yaml`'s claim that these were
  "swept and shown NOT to matter" predates the pools growing).
- **Cheapest verification**: no run needed —
  `python -c "from shared.cluster_evidence import milestone_min_cluster_size as f;
  print([f(n,0.02,3,25) for n in (500,1000,1250,2000,3239)])"` → `[10, 20, 25, 25, 25]`. Or read
  `_mcs` in the `sink_pool_clusters.json` artifact.

#### T8. `describe_mode: coverage` is documented in three places and does nothing; `rubric_status = 'failed'` can never be written
- **File:line**: `Brain/v2/layer_c.py:802-805` and `:37`; docs claiming otherwise at
  `shared/coverage_areas.py:4`, `shared/prompts.py:263`
- **What is wrong**: Two dead-config defects. (a) `run_layer_c_v2` branches
  `if tuning.describe_mode == "situated": … else: legacy`. There is **no `coverage` branch** —
  `describe_coverage_areas` is called only from `calibration/trial_layer_c_arms.py`. `tuning.py`
  types `describe_mode: str` with no allowed-value validation, so setting `coverage` (or a typo)
  silently runs the legacy path and prints nothing. This is the exact failure class the retired
  `ego_trap/settings.py` was deleted for: a config value that reads as authoritative while doing
  nothing. (b) `STATUS_FAILED = "failed"` is defined and **never assigned anywhere in the
  repository** (grep across `v1/ v2/ shared/ ops/` returns nothing), yet `_reconcile`'s error
  message lists it as one of four terminal states.
- **What number it corrupts, and in WHICH DIRECTION**: (a) An arm switched to `coverage` would
  silently produce legacy criteria and be reported under the coverage label — a **wrong-arm result**,
  not merely a no-op. (b) The reconciliation table can never show a failure, so the
  `rubric_generated` count **absorbs** every partially-failed rubric, including the empty-milestone
  case: `run_layer_c_v2:746/764` writes `STATUS_GENERATED` unconditionally after `_fallback_v1`, and
  `v1/layer_c.py:41` does `result.get("milestones", [])`, so a Gemma response missing the key stores
  a **zero-milestone rubric marked `rubric_generated`**.
- **Confidence**: certain (both verified by grep)
- **Cheapest verification**: `grep -rn "STATUS_FAILED\|describe_coverage_areas" Brain/ --include=*.py`
  and `SELECT count(*) FROM rubrics WHERE jsonb_array_length(milestones) = 0`.

---

### ALL WAVE 3 FINDINGS

Ranked worst first. T1–T8 above are not repeated.

#### 1. In the PRODUCTION describe path, a milestone the model failed to return is stored with an empty description and no warning *(near-miss for the top list)*
- **File:line**: `Brain/v2/layer_c.py:590-593` (legacy batch) vs `:549-556` (situated batch), consumed
  at `:613-619`
- `_describe_situated` diffs returned ids against the batch and prints `"describe returned N/M …
  left undescribed"`. `_describe_milestones_batch` — **the path production runs**, since
  `tuning.yaml` ships `describe_mode: legacy` — does no such check. `_finish_rubric` then does
  `desc.get("label", f"Milestone {n}")` and `desc.get("description", "")`, so a missing id becomes a
  stored milestone titled "Milestone 3" with an **empty** `description` and `detection_hint`,
  carrying full `support_calls`/`support_clauses` evidence as if it were real.
- **Direction**: an empty-criterion milestone is unhittable by construction, so it enters
  `milestone_performance.attempts` and contributes only misses — **deflating the weighted hit rate**
  (the 0.068–0.080 figure) with no trace, and **inflating** the milestone count. Nothing reports how
  many milestones ended undescribed, so the ceiling measurement cannot distinguish "Naren failed
  this criterion" from "this criterion is the empty string".
- **Confidence**: certain for the code path; the number of affected milestones is unmeasured.
- **Verify**: `SELECT count(*) FROM rubrics, jsonb_array_elements(milestones) m WHERE
  m->>'description' = '' OR m->>'label' LIKE 'Milestone %'`

#### 2. Soft-skill scoring has none of the truncation guards milestone scoring has, clamps silently, and runs on a different model
- **File:line**: `ego_trap/milestone_scoring.py:452-497` (`score_soft_skills_batch`), `:122-147`
  (`_normalize_rating`), consumed at `ego_trap/gap_output.py:141-148`. Live:
  `tuning.yaml layer_d.score_soft_skills: true`.
- Four defects in one function, each of which the milestone path explicitly defends against:
  (1) **no missing-id report** — `score_milestones_batch:333-347` computes `expected - set(by_id)`
  and shouts; this does not, so a truncated JSON array is invisible. (2) **the clamp is silent in
  the case that actually happens** — `_normalize_rating` warns only `if rating is not None`; a
  missing id yields `r = {}` → `raw.get("rating")` is `None` → **returns `"adequate"` with no
  print**. The documented behaviour ("warns rather than silently clamping") holds for a *wrong*
  value and fails for a *missing* one. (3) **default output cap** — `call_gemma(prompt,
  config.gemma_api_keys)` at `:485` takes the 8192 default, not the `_SCORING_MAX_OUTPUT_TOKENS =
  16384` the milestone call passes, so the more truncation-prone path is the one with no truncation
  detector. (4) **different model** — `:485` takes `gemma.py`'s `_DEFAULT_MODEL =
  "gemini-3.5-flash-lite"` with the default fallback chain while milestones are pinned to
  `_SCORING_MODEL = "gemini-3.1-flash-lite"`, so within a single scored exchange the two halves are
  graded by two different models, and `scored_by` is recorded on milestone results but **not** on
  soft-skill results.
- **Direction**: `gap_events` `Soft_Skill_Failure` counts **deflated**, because the clamp target
  (`"adequate"`) is the one value that emits no gap (`gap_output.py:142`). A truncated batch converts
  every failure in the dropped tail into a pass, and **the clamped rows are not distinguishable in
  the output at all** — no field, no gap row, no log line — so the deflation is unmeasurable after
  the fact. Exact inverse of the milestone path, where a dropped id becomes a `miss` and therefore
  *over*-reports failure: the two halves of the same batch fail in opposite directions.
- **Confidence**: certain (code), certain (flag is on).
- **Verify**: diff `score_milestones_batch:318-347` against `score_soft_skills_batch:484-496` — the
  `missing`/`unexpected` block and the `model=` / `max_output_tokens=` arguments are simply absent.

#### 3. Every "sample" fed to a Gemma prompt in Layer C is an alphabetical head slice, while the evidence count reported alongside it covers the whole population
- **File:line**: `Brain/v2/layer_c.py:635` (`responses[:_MAX_RUBRIC_RESPONSES]`), `:793`
  (`cluster["clauses"][:5]`), `:728` (`cand["clauses"][:5]`), `:796` (`pair_ids` order); ordering
  from `shared/storage.py:306` `ORDER BY p.pair_id`
- `pair_id` is a SERIAL assigned during Layer B, which processes calls in
  `sorted(rec_path.glob("*.txt"))` order (`v2/pipeline.py:13`) — **alphabetical by filename**. So
  `responses[:12]` is "the 12 responses from the alphabetically earliest calls". Taxonomy item 13 —
  the exact `--limit N` failure the calibration section documents — sitting in production code.
  `_finish_rubric` then stores `support_clauses: len(cluster["clauses"])` (the full count, up to 337
  in a measured case) next to a description written from 5 of them.
- **Direction**: a *bias*, not an inflation — every rubric's `anti_patterns`, `soft_skill_rubric`,
  and every milestone `label`/`description`/`detection_hint` is written from the earliest-named
  accounts. Given the separately-measured finding that clusters are often account-bound (`happy
  dance`, `uber.com` 19.6% of turns), an alphabetical head slice is close to a worst case.
- **Confidence**: certain for the mechanism; the size of the bias is unmeasured.
- **Verify**: `SELECT call_filename FROM ... ORDER BY pair_id LIMIT 12` for two large scenarios;
  check whether the 12 come from ≤3 distinct accounts.

#### 4. A failed Gemma batch marks the transcript checkpoint DONE — permanent, unrecoverable loss
- **File:line**: `ego_trap/pipeline.py:249-251` (`except GemmaError: … continue`) and `:276`
  (`checkpoint.mark_done(run_id, stem, layer)`), unconditional
- The `continue` skips the batch loop iteration, not the transcript. The transcript falls through
  Stage 5 (which correctly skips items lacking `milestone_results`) and reaches `mark_done`
  regardless; on resume `checkpoint.is_done(...)` at `:108` returns True and the lost signals are
  never revisited.
- **Direction**: `milestone_performance.attempts` **deflated** by exactly batch size × milestones
  per rubric, silently and permanently. `signal_recognition_gaps.recognized` **deflated**; `missed`
  untouched, so the recognition rate moves down. `gap_events` rows simply absent, with no marker.
  On a **forced re-run without `ops/clear_ego_trap_data.py`** the direction inverts for the
  successful signals: `attempts = attempts + 1` double-counts them while the previously failed ones
  are counted once, so `W = (hits + 0.5·partial)/attempts` is distorted by a **non-uniform**
  denominator — worse than a uniform doubling, because it cannot be corrected by dividing by two.
  The printed `[Stage 5/5] {written}/{len(scoreable)}` line does surface the shortfall in the log,
  so this is not undetectable — but nothing in the DB records it.
- **Confidence**: certain.
- **Verify**: `ego_trap/pipeline.py` — there is no `try/except` around the per-transcript body and no
  flag threaded from the batch loop to line 276.

#### 5. `signal_recognition_gaps` counts `recognized` and `missed` over DIFFERENT populations
- **File:line**: `ego_trap/gap_output.py:184` (`recognized=True`) vs `:214` (`recognized=False`),
  gated by `ego_trap/pipeline.py:260-261` and `:176-185`
- `recognized=True` is written **only** from `write_gap_record`, reached only for a signal that
  (a) had a `csm` outcome, (b) had a rubric in `rubrics`, and (c) survived a successful Gemma batch
  (`if "milestone_results" not in item: continue`). `recognized=False` is written from
  `write_signal_recognition_failure`, called for **every** coachable `none` signal with **no rubric
  requirement and no Gemma dependency**. Only the *recognized* side carries the rubric filter.
- **Direction**: the recognition rate `recognized / occurrences` is **deflated** on two independent
  axes. A coachable scenario with `rubric_status = 'skipped_insufficient_responses'` (kept in
  `coachable_map` deliberately — `ego_trap/scenario_pool.py:37-42`) can only ever accumulate
  `missed`, so its row reads **100% missed no matter how well the CSM performed**. Stacked on top of
  the segmentation defect, the published "64% missed" is doubly wrong.
- **Confidence**: certain.
- **Verify**: grep `upsert_signal_recognition_gap` — two call sites, only one behind the rubric lookup.

#### 6. `review_flag_threshold` flags a fixed fraction of milestone candidates by construction — it cannot report "no contamination"
- **File:line**: `Brain/shared/cluster_evidence.py:171`, consumed at `Brain/v2/layer_c.py:713-728`
- The threshold is the `milestone_sink_similarity_percentile` (95, `tuning.yaml:468`) of *the run's
  own* candidate population, and candidates are flagged with `sink_similarity >= threshold` — a rank
  statistic over the set being judged, so ~5% are flagged **always**, in a corpus with zero
  backchannel contamination and in one that is half backchannel alike. The docstring calls this
  "self-scaling … consistent with every other threshold in this file", but the siblings
  (`required_call_support`, `required_milestone_support`, `passes_reconciliation_gate`) are absolute
  properties of the data. Taxonomy item 5: the metric cannot fail and its degenerate value is a
  constant.
- **Direction**: the count sent to `_judge_flagged_milestones` and therefore dropped as `mechanics`
  is **capped at ~5% regardless of the true contamination rate** (so if contamination is higher,
  milestone counts are **inflated** with junk never examined) and **floored at ~5%** (so on a clean
  run ~5% of legitimate clusters go before a judge that can drop them, **deflating** the count).
  CLAUDE.md's "only 21 [of ~400] ever flagged for the batch judge" is arithmetic, not evidence that
  contamination was low.
- **Confidence**: certain (the mechanism); the direction of the net effect depends on the unknown
  true contamination rate, which is the point.
- **Verify**: `v2/layer_c.py:705-728` — `all_sims` is the full candidate population and `threshold`
  is its p95, so `len(flagged) ≈ 0.05 * len(all_sims)` identically. Any run log line
  `"Review-flag threshold (p95 over N milestone candidate(s))"` followed by `"M … flagged"` will
  show `M/N ≈ 0.05`.

#### 7. `insert_kb_pair` silently discards a conflicting pair and reports it as stored
- **File:line**: `Brain/shared/storage.py:176-203`
- `ON CONFLICT (call_id, turn_index) DO NOTHING` followed by a re-SELECT of the existing `pair_id`.
  On conflict the function returns the **pre-existing** row's id and the newly computed
  `scenario_key` / `scenario_keys` / `trigger_text` / `response_text` are thrown away. No counter, no
  return-value difference, no log line distinguishing "inserted" from "already there" — taxonomy
  items 9 and 10 in one function.
- **Direction**: `v2/pipeline.py:51` prints `"Stored {len(pair_ids)} pair(s)"`, counting silent
  no-ops as stores — **inflates** the reported store count to exactly the extracted-pair count no
  matter how many writes landed. More consequentially, a Layer B re-assignment run over a DB whose
  `checkpoints.db` was cleared but whose `kb_pairs` was not (the precise state CLAUDE.md warns
  about) reports full success while leaving every `scenario_key` at its OLD value — a downstream
  Layer C/D measurement would be attributed to the new taxonomy while running on the old assignments.
- **Confidence**: certain on the code; **likely** on it having occurred (requires the
  checkpoints-cleared-but-data-kept state).
- **Verify**: read the function — `row is None` after `RETURNING` is the conflict branch and it is
  indistinguishable to the caller.

#### 8. `_sequence_milestones`'s substring test can essentially never match, and nothing counts the misses
- **File:line**: `Brain/v2/layer_c.py:370-373`
- A milestone is reclassified `conditional` only if `position_variance > 0.3` AND
  `len(responses) >= 3` AND `item["label"].lower() in " ".join(m["clauses"][:2]).lower()` — a raw
  substring test of a Gemma-authored 2-4 word label against two verbatim transcript clauses. Gemma
  is asked to *name* the move, so the label is a paraphrase; an exact substring hit requires it to
  quote. Every non-match falls through silently and `sequencing_map.get(cluster_id, "fixed")`
  (`:625`) writes `"fixed"`. Two further defects in the same three lines: the inner loop has no
  `break`, so one label can claim multiple clusters; and `item["label"]` / `hv_result.get(...)` are
  unguarded (a bracket access and a `.get` on a possibly-list response).
- **Direction**: `milestones[].sequencing_type` pinned at `"fixed"` — this **is** the recorded "234
  of 235 labelled `fixed`, conditional fires 0 of 226". The field reads as a measured property of
  the data when it is really "the substring test failed". Deflates the conditional count to ~0.
- **Confidence**: certain for the mechanism; the 0-of-226 rate is already recorded independently.
- **Verify**: `SELECT jsonb_array_elements(milestones)->>'sequencing_type', count(*) FROM rubrics
  GROUP BY 1` — a single-valued result confirms it.

#### 9. `Unknown Speaker` turns are classified as CLIENT; only an operator flag keeps them out
- **File:line**: `ego_trap/transcript_parser.py:23-30` (`_classify` falls through to
  `EgoTrapRole.CLIENT`), `ego_trap/pipeline.py:120` (no roster argument)
- Layer D's classifier is fail-open, and **`ego_trap/` never reads the `.speakers.json` sidecars at
  all** — 103 of them sit next to the CSM transcripts and are used by `v1/pipeline.py`,
  `v2/pipeline.py` and eight calibration harnesses, but `ego_trap/transcript_parser.parse_transcript`
  has no `roster` parameter.
- **Measured**: with the current 32-name `JOVEO_SPEAKER_NAMES`, **0 of 254 `@joveo.com` speaker
  slots across the 103 sidecars fall through to CLIENT**. What remains is **417 turns labelled
  `Unknown Speaker`, all classified CLIENT**, plus one transcript with no `mapping.csv` row.
- **Direction**: signal count and therefore `attempts` / `occurrences` **inflated** by up to 417
  unattributable turns. Currently suppressed only by `ops/run_ego_trap.py --exclude` being passed by
  hand; nothing in the code refuses an unattributable speaker, so the next unattended run
  reintroduces it.
- **Confidence**: certain (mechanism and counts). The 417 is the exposure, not the realised error,
  since the last run excluded those files.
- **Verify**: `grep -c "^Unknown Speaker$" csm_recordings/*.txt`, and `grep -rn "load_roster"
  ego_trap/` → no hits.

#### 10. `scenarios.support_clauses` and `scenarios.call_coverage` hold two different units / two different denominators depending on which code path wrote the row
- **File:line**: `Brain/v2/layer_a.py:457` + `:554-555` + `:420` vs
  `Brain/response_taxonomy_auto_pass.py:201` + `:293-294`
- Layer A sets `total_calls = len(set(call_ids))` — calls contributing at least one CLIENT item,
  **400** on the live corpus, not 416 — and writes `support_clauses = stats.n_items`, a count of pool
  ITEMS. The auto-pass computes `SELECT COUNT(*) FROM calls` (**416**) and writes `support_clauses =
  n_pairs`, a count of **kb_pairs**. Same two columns, two denominators, two units.
- **Direction**: a graduated scenario's `call_coverage` is **deflated ~4%** relative to a Layer-A
  scenario's, and its `support_clauses` is on a completely different scale (a pair ≈ several
  clauses), so any ranking, filter or threshold applied across the `scenarios` table compares
  incomparable numbers. **Note the production Layer A path is internally self-consistent and 400 is
  the defensible denominator** — the recorded "`call_coverage` computed against 416" applies to the
  calibration trials, not to `v2/layer_a.py`. That recorded fact should be narrowed.
- **Confidence**: certain.
- **Verify**: `SELECT triage_verdict, min(call_coverage), max(call_coverage), avg(support_clauses)
  FROM scenarios GROUP BY 1` — `graduated_from_sink_pool_auto_pass` rows sit on a different scale.

#### 11. The auto-pass consensus counter cannot advance when the corpus is unchanged, because the guard is keyed on `run_id`
- **File:line**: `Brain/response_taxonomy_auto_pass.py:128-129`, consumed at `:393`
- `if matched_row["last_seen_run_id"] == run_id: return` is an idempotency guard, but `run_id` is a
  **sha1 of the sorted transcript stems** — identical across every re-run of the same corpus. The
  second and third pipeline runs over an unchanged `recordings/` match the tracking row, hit the
  guard, and never increment `consensus_count`; the candidate then fails `consensus_count <
  response_taxonomy_consensus_runs` at `:393` and `continue`s with no log line. The consensus
  mechanism only advances when the transcript set changes — the opposite of the stated intent, since
  the instability it defends against is exercised by re-clustering the *same* corpus. Taxonomy item
  12: the key omits what makes the record meaningful (the clustering outcome) and includes something
  that makes repetition impossible (the corpus hash).
- **Direction**: **deflates the graduation count to zero** on a stable corpus (fail-safe, so a
  stalled feature rather than a wrong number), and it means the 2026-08-08 result of "4 scenarios
  graduated after 3 manual invocations" was only reachable because those invocations supplied
  differing `run_id`s — the consensus actually satisfied is not the one the design describes.
- **Confidence**: certain for the code path; **likely** for the interpretation of the recorded run
  (the auditor did not inspect how those three invocations were launched).
- **Verify**: `SELECT candidate_id, consensus_count, first_seen_run_id, last_seen_run_id FROM
  response_taxonomy_candidates` — equal first/last run ids with `consensus_count = 1` confirms it.

#### 12. `segmenter`'s `len(sent) < 4` is a hardcoded token count that is decided by PUNCTUATION
- **File:line**: `preprocessing/segmenter.py:23`
- `len(sent)` is spaCy's **token** count, which includes punctuation. So the de-facto posture filter
  is: `"That makes sense."` → 4 tokens → **kept**; `"Got it."` → 3 → dropped; `"No."` → 2 → dropped;
  but **`"Yeah, sure."` → `Yeah / , / sure / .` → 4 → kept** and `"Right."` → 2 → dropped. Two
  two-word backchannels get opposite verdicts purely on whether the transcriber wrote a comma. Also
  a hardcoded count (taxonomy item 15) that freezes at 4 for any corpus.
- **Direction**: the Layer A clause pool's content-free share (measured at 59.1%) and every count
  derived from it, **inflated** by the comma-bearing backchannel that survives. Shared with
  `v2/layer_c.py:77`, so the same cutoff silently governs the milestone clause pool.
- **Confidence**: certain for the mechanism; the *magnitude* of the punctuation-driven admission is
  unmeasured (**speculative** as a quantity).
- **Verify**: `nlp("Yeah, sure.")` vs `nlp("Got it.")` and compare `len(...)`.

#### 13. Three independent implementations of "content words", none sharing a knob; `layer_a.min_content_words` confirmed inert
- **File:line**: `Brain/v1/layer_b.py:22,27-31,45,54`; `Brain/shared/cluster_evidence.py:200-213`;
  `Brain/shared/trigger_quality.py:25-32`; the inert call site is `Brain/v2/layer_a.py:452`
- (a) **`min_content_words` is inert**: `run_layer_a_v2` calls `build_client_pool(all_turns,
  unit=tuning.pool_unit)` with no `min_content_words`, so the signature default `0` wins and the
  `if min_content_words and …` guard at `:70` never fires. The function was renamed
  (`build_client_clause_pool` → `build_client_pool`) but the defect is unchanged. (b) **Two filters,
  two knobs**: `layer_b._MIN_CONTENT_WORDS = 5` is a module constant while
  `cluster_evidence.is_substantive` takes its threshold from the caller — editing `tuning.yaml` does
  not touch Layer B. (c) **A third**: `trigger_quality.content_word_count` is the same `is_alpha and
  not is_stop` count with a *third* knob (`sink_rescue_density_min_words`), and it loads spaCy with a
  different disabled-component set than `layer_b._is_substantive` — which, per this repo's own
  measurement, moves token/sentence analysis. (d) **A fourth, unrelated rule**: the
  `segmenter.py:23` cutoff above. (e) **"Indeed"**: `layer_b._is_substantive` is ACTIVE and gates
  **both** the trigger (`:45`) and each Naren response turn (`:54`).
- **Direction**: (a) deflates nothing today but any future reader who sets `min_content_words` gets
  no effect and no error — a knob that reads as authoritative while doing nothing. (e) **deflates the
  `kb_pairs` count** — every sentence naming a major job board loses a content word toward the floor
  of 5, so genuinely substantive recruitment-advertising content falls below the bar; that in turn
  deflates every scenario's `support_clauses` and Layer C's clause pool for exactly the job-board
  scenarios where it matters most.
- **Confidence**: certain for (a)–(d); (e)'s mechanism is certain, its stoplist membership is taken
  from the recorded 2026-08-14 measurement (the auditor did not run spaCy).
- **Verify**: `python -c "import spacy; print('indeed' in
  spacy.load('en_core_web_lg').Defaults.stop_words)"`

#### 14. A scenario vector and a primary-topic vector are compared using a threshold calibrated on neither band (P1 #5 = P3 #12)
- **File:line**: `Brain/shared/scenario_vectors.py:35` + `:45`, consumed at
  `Brain/response_taxonomy_auto_pass.py:177-181` (called with `a.merge_cosine_threshold` from
  `:298`/`:398`) and `calibration/graduate_sink_topics.py:125-128`
- Both graduation paths embed the new scenario with `scenario_vec()` (`business_description +
  keyphrases`) and the existing parents with `build_primary_topic_vecs()` (`description +
  keyphrases`), then decide the FK with `topic_grouping.match_existing_primary_topic(...,
  merge_cosine_threshold)`. The prefix is right — both are `embed_document`, so this is *not* the
  query/document cache-key bug — but `merge_cosine_threshold` (0.85) was calibrated on
  **cluster-centroid vs cluster-centroid of clause embeddings**, a third population, and validated by
  reading merge groups at that level. The scenario-description-vs-primary-topic-description band has
  never been measured. This repo's own rule is "never borrow a floor between two bands".
- **Direction**: `scenarios.primary_topic_key` for every auto-pass-graduated scenario. **P1**: if the
  description band sits *higher* than the centroid band (the pattern everywhere else — richer,
  longer text scores higher), 0.85 is too permissive and graduated scenarios are **over-attached** to
  a near-but-wrong parent; if lower, they are orphaned to `None`, the exact bug
  `match_existing_primary_topic` was written to fix. **P3** judges the second branch more likely: if
  the band sits below 0.85, the match returns `None` essentially always and every graduated scenario
  creates its own `grouping_method: 'graduated_singleton'` row — **inflating the `primary_topics`
  count** and defeating the purpose of the fix. Nothing logs which branch was taken. Affects the 4
  scenarios graduated in the 2026-08-08 run and every future one; does not touch Layer B/C/D matching.
- **Confidence**: P1 **likely** (threshold-transfer certain; current mis-assignment unmeasured —
  mark as unverified, not demonstrated). P3: certain that the bands differ and are unmeasured;
  **likely** for the direction.
- **Verify**: `SELECT grouping_method, count(*) FROM primary_topics GROUP BY 1` — if the 4 known
  graduated scenarios are all `graduated_singleton`, the match never fired. Or, offline against a
  warm cache, embed the 161 `scenario_text()` and 80 `primary_topic_text()` strings and print the
  best-match cosine percentiles.

#### 15. Silent-drop guards with no counters (three sites, low individual impact)
- **File:line**: `Brain/v2/layer_a.py:328-350`, `Brain/v2/layer_c.py:339-342`, `:591-593`,
  `Brain/v2/pipeline.py:57-60`
- (a) `_label_primary_topics_batch` does `raw if isinstance(raw, list) else raw.get("results", [])`
  and then, for any group whose id did not come back, silently substitutes `primary_topic_key =
  f"primary_topic_{idx}"` and `label = "Uncategorised"` — a real `primary_topics` row
  indistinguishable from a deliberate one, with no warning and no count. (b)
  `_judge_flagged_milestones` and `_describe_milestones_batch` use the same guard with no missing-id
  report. (c) `pipeline.py`'s try/except around `run_auto_pass` prints one line to stdout; the
  module's own `_logger.info("%d candidate(s) graduated")` is on the success path only, so a mid-loop
  failure leaves **no record at all** of how many candidates were tracked — and the graduation
  transaction commits at `:331` *before* `run_layer_c_v2` runs at `:338`, so a failure there leaves a
  committed, rubric-less scenario (caught loudly, but only later, by `_reconcile`).
- **Direction**: (a) inflates the `primary_topics` count with placeholder rows and pollutes
  `scenarios.primary_topic` with "Uncategorised". (c) makes the auto-pass's own effect uncountable
  from outside the log file.
- **Confidence**: certain.
- **Verify**: `SELECT count(*) FROM primary_topics WHERE label = 'Uncategorised' OR
  primary_topic_key LIKE 'primary_topic_%'`

#### 16. Minor: `get_milestone_gap_profile`'s INNER JOIN silently drops rows, and the label cache is keyed wrong
- **File:line**: `shared/storage.py:410-411` (`JOIN rubrics r ON r.rubric_id = mp.rubric_id`),
  `ego_trap/pipeline.py:285-288`, `ego_trap/gap_output.py:60-66`
- (a) the join is inner, so any `milestone_performance` row whose `rubric_id` no longer exists after
  a Layer C re-run **vanishes from the gap profile with no counter** (taxonomy item 10).
  (b) `pipeline.py:287` fetches the rubric by `r["scenario_key"]` but caches it under
  `r["rubric_id"]`; if two rows share a `rubric_id` with different `scenario_key` payloads, the first
  seen wins and every later row is labelled from the wrong rubric's milestone array.
- **Direction**: (a) the printed profile row count is **deflated**; the underlying counters are
  untouched. (b) only the human-readable `label` column of the printed report, not any number.
- **Confidence**: certain for (a) as a mechanism; (b) is **likely** but no live case was found.
- **Verify**: `SELECT count(*) FROM milestone_performance mp LEFT JOIN rubrics r USING (rubric_id)
  WHERE r.rubric_id IS NULL;` — noted for whoever fixes it; the auditor deliberately did not run it.

#### 17. Production Layer B does not call the shared rule it was extracted into
Full detail folded into **T5** above (P1 #4). Certain code fact, **no live number moves today** —
flagged as a prospective confounded-arm hazard, not counted as a live defect.

---

### OPEN PROBLEMS THESE FINDINGS MAY EXPLAIN

Standalone. Each entry pairs an open, never-root-caused question as CLAUDE.md records it with the
Wave 3 finding that may explain it, and separates the **certain code fact** from the **speculative
magnitude**.

**1. The ~3% Layer D milestone hit rate that survived three fixes (and its leakage-clean successor,
`W(matched)` 0.089–0.095).**
- **T2 — mixed CSM/teammate windows.** Certain code fact + **measured** rates: 17.4% of scored
  windows are mixed, 16.3% carry ≤5 CSM words against a ~6-milestone rubric. Deflates hits, inflates
  misses. The auditor calls it "a direct, unexamined contributor … a *population* defect, so no
  prompt change touches it" — which is consistent with why three wording fixes did not move it. The
  *share* of the ~3% it accounts for is unquantified.
- **ALL #1 — empty-description milestones in the legacy (production) describe path.** Certain code
  path; **count unmeasured**. Unhittable by construction, enters `attempts`, contributes only misses.
- **T3 — the scored population is a biased half.** Certain + measured: 45.8% of client turns can
  never be scored. Direction of the composition bias measured (excluded turns shorter), so this
  distorts *what* is scored more than it biases the rate; it makes `attempts` understated ~2×.
- **ALL #4 — failed Gemma batches marked done.** Certain; deflates `attempts` and `recognized`
  silently, and on a forced re-run produces a *non-uniform* denominator.
- Adjacent but a different metric: **ALL #2** (soft-skill silent clamp) deflates
  `Soft_Skill_Failure`, not milestone hits — do not fold it into the ~3%.

**2. The 39.7–45.8% Layer B sink absorption that eight signal shapes failed to explain.**
- **T4 — `extract_pairs` drops all but the last CLIENT turn of a block.** Mechanism **certain**
  (traced line by line); magnitude **likely**, inferred from the measured CSM-corpus rate (43% of
  client turns immediately followed by another CLIENT turn) rather than measured on `recordings/`.
  The auditor's framing: this "systematically biases `trigger_text` toward the last fragment of each
  client speech block", and Layer B's sink decision is made on `trigger_text` alone — "a plausible
  mechanical cause of the … sink absorption that the whole sink-rescue effort was searching for a
  *scoring* explanation for."
- Compounding, already recorded and re-confirmed CLEAN by P3: `v2/layer_a.py:65` builds the taxonomy
  from CLIENT turns only, so an expert behaviour whose client cues are filler-like has no scenario to
  be routed to. T4 further narrows which client turns even reach that pool.
- **T5** is a *second, separate* narrowing of `scenario_keys[]` width (certain mechanism, unmeasured
  magnitude) but acts on pairs whose best match is real — it is not itself a sink-absorption cause.

**3. "Layer C's relevance filter barely discriminates by topic" (placebo 53.9–57.2% vs real
57.7–63.0%).**
- **T1 — the filter is a fixed 60% quota.** **Certain**, and the auditor states it *mechanically
  explains* the observation rather than merely correlating with it: "a quota cannot separate them,
  and the ~6-point gap is only the residual ordering effect." This is the strongest
  finding→open-problem link in the wave.
- Reinforced from Wave 4 (**W4 #10, OVERSTATED**): the shipped `percentile: 40` was selected at the
  **edge of its search grid** by an objective (`zero` = scenarios with no milestone) that counts
  over-filtering only and is minimised by filtering less — so the sweep cannot distinguish "40 is
  optimal" from "the objective is monotone and the grid stopped at 40".

**4. The unexplained 78-vs-85 coachable drift between two runs of identical clusters (~5-6% of
clusters, 7-10 of 158, flipping the coachable/mechanics boundary).**
- **T6 — Layer A adjudication fails OPEN to coachable.** The auditor is explicit about the split:
  **certain that the code fails open** (a missing `decision`, or any value outside the four-member
  map, becomes `KIND_SCENARIO` / `is_coachable=True`, with no counter and no warning);
  **speculative that it explains the run-to-run flips.** Do not upgrade this. CLAUDE.md's own
  standing hypothesis (largest-cluster-first ordering cascading through the "top-3 nearest accepted"
  context) is untouched by this audit and remains a live alternative.

**5. 47.3% HDBSCAN noise in the sink pool ("coarse clustering", cap on any cluster-based fix).**
- **T7 — `min_cluster_size_ceiling` freezes granularity at a hardcoded 25.** **Certain** mechanism,
  and the recorded diagnostic (`0.02 × 3730 = 74.6`, clamped to 25) **confirms it binds on exactly
  the run that produced the 47.3%**. The auditor's phrasing: the sink-pool diagnostic "attributed the
  resulting 47.3% HDBSCAN noise to 'coarse clustering' — the ceiling is why." The magnitude of the
  noise reduction a scale-matched value would achieve is **untested** (CLAUDE.md already records "a
  finer rerun would likely split the 535-pair junk cluster and cut noise. Untested").

**Also newly explained, not on the orchestrator's candidate list:**
- **"234 of 235 milestones labelled `fixed`; the conditional trigger fires 0 of 226"** → **ALL #8**,
  certain: `_sequence_milestones`'s substring test requires a Gemma paraphrase to literally quote the
  transcript. The field records "the substring test failed", not "this move has no ordering variance".
- **"`Signal_Recognition_Failure` is 98.6% a segmentation artifact"** (recorded as measured) →
  **T3** reproduces it at **98.7% (2,962 of 3,000)** on a larger corpus, and adds the *second*
  consequence — the biased scored population — which the original write-up did not contain.
- **"the auto-pass graduated 4 scenarios after 3 manual invocations"** → **ALL #11**, certain code
  path: the consensus counter cannot advance on an unchanged corpus, so the consensus actually
  satisfied is not the one the design describes (interpretation of the run marked **likely**).

---

## Wave 4 — provenance of published numbers

One auditor traced **17 load-bearing numbers** — every one where a knob shipped, an approach was
declared CLOSED, or a wall was declared standing — back to the script and artifact that produced
them, reading `calibration/` code plus `artifacts/*.json` and `logs/` read-only. Result: **5
SUPPORTED, 9 OVERSTATED, 1 CONTRADICTED, 2 UNVERIFIABLE FROM CODE.** Several OVERSTATED verdicts
are recomputations from committed artifacts (C1 per-stage, the skills one-off rate, the C4 control),
so they are checkable without spending anything. Two numbers were dropped as low value because no
decision rests on them: the `~[350,450]` milestone band (nothing consumes it) and "dry run predicted
74/154 zero-milestone vs production 3/85" (already self-retracted in CLAUDE.md).

### VERDICT TABLE

| # | number as published | producing script | verdict | reason |
| --- | --- | --- | --- | --- |
| 1 | pool unit: **8 (4.7%) vs 71 (37.2%) subject-bearing clusters** | `trial_pool_unit.py:353` | **OVERSTATED** | `is_substantive(text, 5)` is an absolute content-word count applied to a *clause* in one arm and a whole *turn* in the other; `corr(mean sample word count, thin_fraction)` = **−0.839** (turn) / **−0.787** (clause) — the test is very largely a length test, and the arms differ in length by construction. Inflates the turn arm. |
| 2 | pool unit: **corr(negation, content-free) −0.149 → −0.744** | `trial_pool_unit.py:149-167` | **OVERSTATED** | Both terms rise with item length: turn arm `corr(words, neg_rate)=+0.772`, `corr(words, thin)=−0.839`. Partialling out mean item length collapses it to about **−0.35**. Roughly half the magnitude is length. |
| 3 | h2h: **C1 pooled swap agreement 0.669 ⇒ "signal share 0.34"** | `trial_head_to_head.py:_verdict` (`:614-637`) | **OVERSTATED** | Pools C2, whose own docstring says a coin flip is the correct answer; per stage **c2 0.570, c3 0.581, c4 0.847** — on C4, the stage that produced the fatal result, the judge clears the 0.75 bar. `swap_agreement` also charges one-decisive-one-tie as reversal (flip rate 0.201, tie-mismatch 0.130); reversal-only gives signal share **0.60**. |
| 4 | criteria rewrite: **43 up / 17 down, net +4.48, "~2× the floor"** | `compare_criteria_ab.py:91-110` | **OVERSTATED** | `FULL OUTER JOIN` + `COALESCE(...,0)` scores a milestone present in only one arm as `0.0` in the other. The baseline arm lost ~99 attempts to 2 Gemma batch failures (864 vs 963, +11.5%); those rows count as the rewrite improving. No only-one-arm counter (contrast `measure_scoring_noise.py:271`), and the 15% drift gate is looser than that script's own 5% warning. |
| 5 | Layer D: **"~350+ calls for a median of 25"** | *no script* (prose arithmetic) | **CONTRADICTED** | It is exactly `100 × 25/7` — the linear extrapolation the same paragraph forbids. Fitting the measured sub-linear exponent (per-milestone ∝ calls^0.64) gives **≈750 calls**. Understates the requirement ~2×. |
| 6 | noise floor: **±0.006 weighted, 15.6% of milestones move** | `measure_scoring_noise.py` | **UNVERIFIABLE FROM CODE** | The script's own docstring (`:30-38`) attributes 15.6% to the **contaminated blended-runs** comparison its duplicate guard now refuses to make, and gives drift as +0.000 vs the prose's +0.006. `grep -r "MOVEMENT RATE" Brain/logs/` returns nothing — no run was ever captured. |
| 7 | derived rule: **"below ~+0.02 weighted is unmeasurable"** / "+0.025 is ~4.1× the band" | derived from #6; hardcoded at `trial_skills.py:65` | **OVERSTATED** | ±0.006 is the range of **two** observations — one difference. It estimates σ, not a 95% interval (~±0.015). The floor runs had identical attempts (889/889) while the treatment had 864/963, so the treatment carries a variance source the floor does not. |
| 8 | skills: **best validity 0.667 vs the 0.80 bar** | `trial_skills.py:502-507` | **OVERSTATED** | `judge_groups:399-403` coerces every unparseable verdict to the FAILING value and silently drops missing groups, biasing `V(t)` down. Denominators back out to n ≈ 3–9; at n = 9, observing 6/9 when true validity is 0.80 has p ≈ 0.26 — 0.667 is **not distinguishable from the bar**. |
| 9 | h2h: **"Not length — C4's length-matched cell is 0.875"** | `trial_head_to_head.py:538-541` | **OVERSTATED** | The band admits **8 of 100** decisive C4 items. A binomial 95% CI on 7/8 spans ≈[0.47, 1.00] and excludes nothing, including values below the 0.75 bar. |
| 10 | Layer C: **percentile 40 / fraction 0.10 "calibrated"** | `dry_run_layer_bc.py:64-65`, `:277` | **OVERSTATED** | 40 is the lowest value in `_SWEEP_PERCENTILE = [40, 60, 75]` and it won; the objective (`zero` = scenarios with no milestone) counts over-filtering only, is minimised by filtering less, and has no on-topic counterweight. The grid never brackets a minimum. Fraction was a tie (74/74) resolved by argument, not by the metric. |
| 11 | **"top1−top2 margin ~0.01 in BOTH taxonomies"** | `validate_taxonomy_vs_layerd.py:109-119` | **OVERSTATED** | The margin is to the runner-up *anywhere in the taxonomy*, but the decision the same script makes is `accepted = coach[best]` — **sink vs non-sink**. When ranks 1 and 2 agree on coachability a 0.01 gap changes nothing. The supporting statistic (best-coachable minus best-sink) is never computed. For Layer B, a tiny gap is the *designed* behaviour of `relative_margin: 0.95`. |
| 12 | **17 of 405 unhittable: 74 attempts, 0 hits, 12 milestones** | *no script* | **UNVERIFIABLE FROM CODE** | `ops/flag_uncoachable_milestones.py` queries `rubrics` only and never touches `milestone_performance`. 17 flagged but only 12 have any attempts — 5 have zero evidence. If "0 hits" means 0 *full* hits, at a ~3% full-hit rate P(0 in 74) ≈ 0.10, not proof. |
| 13 | h2h: **C4 native win 0.835** (the fatal control) | `trial_head_to_head.py` | **SUPPORTED** | Recomputed from `artifacts/h2h_control_c4.json` with the module's own tie rules: **0.835, n = 85/99 decisive, tie share 0.141** — byte-matching `logs/h2h_m5.log`. C2 (0.543) and C3 (0.750) also reproduce exactly. `_pair_for:365-373` shows Naren's own trigger, so "native" really is native. |
| 14 | grader inputs: **77.4% / 82.3%, p=1.7e−5 / 2.8e−7; W(matched) 0.089–0.095** | `trial_grader_inputs.py` | **SUPPORTED** (provenance gap) | Reproduced exactly: `W(matched) 0.0949/0.0890`, `W(unrelated) 0.0325/0.0421`, `D 2.92/2.11`, sign tests `48-14-7` and `51-11-7` of 69, 3,540 gradings each, `judged_by` 100% `gemini-3.1-flash-lite`. Matched and unrelated built from the **same row**, only `rk` changes. **The retraction of "1.2:1" is well-founded.** |
| 15 | skills: **78% of milestones abstract to a one-off (315/405, 342 distinct)** | `trial_skills.py` | **SUPPORTED** (exact) | Recomputed: v1 **315/405 = 77.8%, 342 distinct**; v2 **299/405 = 73.8%, 323 distinct**; v2 `explains a mechanism` = 29 members. Every figure in the three-attempt table matches to the decimal; the gemini arm's `reused_behaviours_from` makes "embedder is the only variable" verifiable and true. |
| 16 | retrieval gate: **0.812 vs 0.631 base, CI [+0.168, +0.196]** | `probe_retrieval_gate.py` | **SUPPORTED** | `bootstrap_lift:132-143` computes point estimate and CI from the same estimator (taxonomy #7 does not apply); `candidate_base_rate:102-116` excludes each query's own call *per query*; the probe runs against the **full** pool, so `clean_top1` is not 1.0 by construction. |
| 17 | criteria rewrite: **person language 100% → 3%** | `ops/rewrite_milestone_criteria.py:104` | **SUPPORTED** (but see note) | `_PERSON` is applied identically to both arms. Its `they\|their` alternatives are false positives only in the *after* direction, and the before figure is 100% and cannot inflate — so the measured drop is if anything conservative. |

### NUMBERS WHOSE PROSE OVERSTATES THE CODE

Worst first. OVERSTATED and CONTRADICTED rows only.

**#5 — "~350+ calls for a median of 25" (CONTRADICTED).** The only row where the published number is
arithmetically wrong rather than under-evidenced, and it is load-bearing:
`OPEN_PROBLEMS.md:699` raises the feasibility question against 107 available CSM transcripts, and at
~750 the answer changes from "hard" to "not available". Suggested wording: *"Reaching a median of 25
observations per milestone requires roughly **750** calls, not 350 — fitting the measured sub-linear
growth (per-milestone ∝ calls^0.64) rather than extrapolating linearly. Against 107 available CSM
transcripts this is not obtainable."*

**#1 — pool unit "8 (4.7%) vs 71 (37.2%) subject-bearing".** This is the primary quantitative
evidence for the pool-unit change, and the measuring instrument is itself unit-dependent: the same
absolute 5-content-word bar is applied to a clause in one arm and a concatenated multi-sentence turn
in the other, and concatenation can only raise the count. The spec's own defences (the `jovio`
false-positive class, the gemini/blind-judge cross-check) validate the proxy *within* the turn arm;
none validates it **across** the unit boundary, which is the only comparison the headline makes. Also
inflates `pool content-free 59.1% → 32.8%` and `junk 98 → 78`. Suggested wording: *"Subject-bearing
clusters 4.7% → 37.2%, **but the `thin` test is an absolute content-word count and is dominated by
item length (corr −0.84 turn / −0.79 clause), so it is not unit-invariant** — the arms differ in item
length by construction and an unknown share of the gain is the instrument. Re-report with a
length-normalised rule before quoting."*

**#3 — h2h C1 0.669 ⇒ "signal share 0.34".** The claim it supports — *"C1 is the deeper failure and
no pairing design fixes it … a property of the judge, not of the comparison"* — is not supported by a
pooled figure dominated by a stage designed to be undecidable. The **overall CLOSED verdict survives
on C4**, which is independent (#13, SUPPORTED). Suggested wording: *"C1 pooled 0.669, but read per
stage: c2 0.570 (its ground truth is indifference, so ~0.50 is correct), c3 0.581, **c4 0.847 —
above the 0.75 bar on the stage that produced the fatal result**. `swap_agreement` also charges
one-decisive-one-tie as reversal; reversal-only agreement is 0.799, giving a signal share of 0.60,
not 0.34. Head-to-head is closed by C4, not by C1."*

**#4 — criteria rewrite "43 up / 17 down, net +4.48, ~2× the floor".** This is the surviving
evidence for the rewrite *after* the shape argument was withdrawn, and it is contaminated by the
baseline arm's ~99 lost attempts being scored as `0.0` rather than "not measured" — ≈11% of baseline
attempts against a 60-mover total. The **headline `weighted 0.043 → 0.068` uses pooled `_totals` and
is much less affected — that part stands.** Suggested wording: *"43 improved / 17 worsened, net
+4.48 — **but milestones present in only one arm are scored 0.0 in the other, and the baseline arm
lost ~99 attempts (11.5% drift) to two Gemma batch failures, so an unknown share of the 43 is
missing-row contamination.** The pooled `weighted 0.043 → 0.068` is not affected. Re-report with an
only-one-arm counter before citing the per-milestone tally."*

**#7 — "±0.006 band" and "+0.025 is ~4.1× the band".** With n = 2 runs you observe exactly one
difference; 0.006 estimates σ of the run-to-run difference (expected range of two normal draws =
1.128σ), not a 95% interval, which would be roughly ±0.015. So 4.1× reads as ~4σ when the honest
reading is ~1.7 half-widths. Note this makes the *skills* bounds derived from `_NOISE_BAND = 0.006`
**stricter**, so the skills FAIL verdict is not endangered. Suggested wording: *"One observed
run-to-run difference of 0.006 weighted (n = 2 runs; a 95% band is nearer ±0.015). The criteria
rewrite's +0.025 clears it, but not at 4×."*

**#8 — skills "best validity 0.667 vs the 0.80 bar".** `judge_groups` coerces unparseable verdicts to
the FAILING value and silently drops missing groups, so `V(t)` is biased **toward the published
FAIL**, and the denominators (n ≈ 3–9) cannot distinguish 0.667 from 0.80 (p ≈ 0.26). The overall
closure survives on the `V = 0.20` at t ≤ 0.675 point (1/5 against a 0.80 bar, p ≈ 0.007). Suggested
wording: *"Best validity 0.667 at n ≈ 9 — **not statistically distinguishable from the 0.80 bar**.
The point that decides the closure is `V = 0.20` at t ≤ 0.675, where power is satisfiable; 'off by
4×, not a near miss' describes that point only, not the gemini run's 0.667."*

**#9 — "Not length — C4's length-matched cell is 0.875".** Ruled out on **n = 8** (7/8), 95% CI
≈[0.47, 1.00]. Matters because length is the one confound that would make C4 an artifact of the
*harness* rather than of cross-corpus comparison. The same sentence rules out position (n ≈ 200 per
stage — fine) and retrieval quality (n = 25 per quartile — thin but defensible), presenting three
rule-outs at three wildly different power levels as one list. Suggested wording: *"Position is ruled
out (n ≈ 200/stage) and retrieval quality is thin-but-defensible (n = 25/quartile); **length is
ruled out only on n = 8 (7/8, CI ≈[0.47, 1.00]) and is therefore not ruled out.**"*

**#2 — pool unit "corr(negation, content-free) −0.149 → −0.744".** Cited uncaveated in both
CLAUDE.md and `OPEN_PROBLEMS.md:192` as the clean evidence that stance survives in turn mode; roughly
half the magnitude is item length. Direct sibling of `audit_null_instrument.py`'s already-recorded
`corr(lift, mean word count) = +0.65`, which was run on the null instrument and never on this one.
Suggested wording: *"corr(negation, content-free) −0.149 → −0.744, **length-confounded: partialling
out mean item length collapses it to about −0.35.**"*

**#10 — Layer C "calibrated to percentile=40, fraction=0.10".** A shipped production knob feeding
every rubric's clause pool, selected at the edge of a one-sided grid by an objective minimised by not
filtering. CLAUDE.md's own later finding (placebo clauses surviving at 53.9–57.2% vs 57.7–63.0%) is
exactly what a permissiveness-rewarding objective predicts — and Wave 3's **T1** shows the knob
cannot filter at all. Suggested wording: *"`percentile: 40` is the **lowest value in the swept grid
`[40, 60, 75]`**, chosen by an objective (`zero`-milestone count) that only penalises over-filtering
and has no on-topic counterweight — the grid never brackets a minimum, so this is a lower-bound pick,
not a calibrated optimum. See also: the filter is a fixed 60% quota (`v2/layer_c.py:108-109`)."*

**#11 — "top1−top2 margin ~0.01 in BOTH taxonomies … arguably a bigger problem than which taxonomy
is used".** No computed number is wrong; the interpretation is. The margin measured is to the
runner-up anywhere in the taxonomy, while the decision the same script makes is sink vs non-sink.
Suggested wording: *"Top1−top2 margin is ~0.01 in both taxonomies. **This is not the margin the
sink/non-sink decision rests on** — that would be best-coachable minus best-sink, which the script
does not compute, and it does not report how often ranks 1 and 2 disagree on coachability. For Layer
B a tiny top1/top2 gap is the designed behaviour of `relative_margin: 0.95`."*

---

## CLEAN CATEGORIES (BOTH WAVES)

Load-bearing negative results, grouped by taxonomy item where the auditors mapped them. Anything
**MEASURED** rather than reasoned is marked as such.

**Taxonomy item 3 — numbering / base mismatch. Clean at every boundary in scope, checked three
times independently.**
- P1: `kb_pairs.turn_index` written verbatim from `Turn.index` and read back only for the unique
  index. `milestone_id` is the 1-based array position from `milestone_scoring.milestone_ids:69-86`,
  which zips over the FULL milestone list (`:247`, `:408`) so filtering cannot renumber it;
  `storage` treats it as an opaque TEXT PK and never parses it. Only cosmetic residue:
  `get_milestone_gap_profile`'s `ORDER BY mp.milestone_id` sorts TEXT so `M10` precedes `M2` — no
  rate or denominator depends on it.
- P2: `EgoTrapTurn.index` is 0-based end to end (`index=len(turns)` at `:70`), passed unmodified
  into `turns_until_next_client`, `extract_csm_response_window` and `gap_events.signal_turn_index`,
  and the pipeline's `@ turn N` print uses the same 0-based value. The one 1-based numbering
  (`f"M{i+1}"`) is correctly reversed at `format_gap_profile:61` — **verified for `M3` → 2 and
  `M10` → 9.**
- P3: `_finish_rubric`'s `order: order_idx + 1` is written over the same list it stores, so the
  `order` field and the array position Layer D uses cannot diverge.

**Taxonomy item 4 — name that never matches. Checked exhaustively in all three P-batches; no live
`OTHER_JOVEO`-class bug anywhere in production code.** Every string literal compared against an
enum, a DB value or a dict key was grepped against its definition:
`"full_hit"/"partial_hit"/"miss"` vs `_VALID_VERDICTS`; `"csm"/"other_joveo"/"none"` vs the three
returns of `classify_response_outcome:100-104`; `_VALID_BLOOM_LEVELS` vs the
`scenarios_bloom_level_check` constraint element for element; `cluster_evidence`'s triage/kind
constants vs `db/schema.sql:39-44`; the three `rubric_status` literals defined once at
`v2/layer_c.py:34-36` and spelled identically by every reader; `_KIND_BY_DECISION`'s three keys vs
`PROMPT_LAYER_A_V2_TRIAGE:852-860`; `"failing"` vs `_VALID_RATINGS`; `turn_match_mode: normalized`
vs `_TURN_MATCH_MODES`; the `f"{scenario_key}::{cluster_id}"` id constructed identically at all four
producer/consumer sites. `SpeakerRole.JOVEO_OTHER` is attribute access against the real member, not
the `"OTHER_JOVEO"` string that caused the original bug — **the known instance is confined to
`ego_trap/call_scoring.py`, which ships OFF and is outside these batches.** Also clean: no straggler
`sub_topic` — the two live reads are of *Gemma's JSON key* (still `sub_topic` per
`shared/prompts.py:58,888`) and both immediately rename to `business_description`.
*Recorded near-miss, not a defect*: `graduate_sink_topics.py:189` and
`response_taxonomy_auto_pass.py:295` write `triage_verdict` values outside the documented two-valued
enum; there is no CHECK constraint and nothing filters on it today, but a future
`WHERE triage_verdict IN (...)` would silently drop every graduated scenario.

**Taxonomy item 8 — multi-valued enum collapsed to a boolean. No conflation found.**
`get_rubric_status_report` (`storage.py:158-167`) already returns the **full cross-tab**
`(cluster_kind, rubric_status, count)` — the pattern the taxonomy asks for. There is exactly **one
definition of "sink"** in the codebase: `relative_match.is_sink_flags` keys on `is_coachable` only
(never `cluster_kind`), and `ego_trap/scenario_pool.is_coachable` uses the identical rule with the
identical missing-key default, pinned by `tests/test_ego_trap_scenario_pool.py:31`.
`cluster_evidence.triage` matches its contract precisely — `INSUFFICIENT_EVIDENCE` is the only
terminal verdict, high coverage returns `NEEDS_REVIEW` (a routing flag), and `triage()` never assigns
`MECHANICS`/`LOGISTICS`; only the LLM does. *(The one enum-shaped defect found is the fail-OPEN
default at `v2/layer_a.py:531`, T6 — a different failure.)*

**Taxonomy item 9 — silent short-circuit. `rank_benchmark_responses`'s `len(responses) <= limit`
branch is harmless in production.** It returns rows unranked and without `scenario_similarity` — the
defect that broke the dry-run harness's chosen-vs-discarded band — but the only production caller
(`get_benchmark_reference:88`) joins `response_text` only and never reads the score, and when the
branch fires it is returning *all* the rows anyway, so no ranking decision is skipped.

**Taxonomy item 15 — `required_call_support` and `required_milestone_support` DO scale.**
`max(floor, ceil(fraction * n))` (`cluster_evidence.py:120-127`, `:181-190`) re-derives from
corpus/scenario size on every run with **no cap** (416 calls → `ceil(0.02×416)=9` vs a floor of 4).
The documented inertness of `min_call_support_fraction` is a property of corpus size relative to
BERTopic's `min_cluster_size`, **not** of the formula. The only frozen knob in this family is
`milestone_min_cluster_size` (T7).

**Embedding prefix discipline — clean at every call site in the repo, traced twice.** All four
`scenario_vectors` functions use `embed_document`, and every comparison they participate in is
prefix-consistent: Layer B triggers `embed_query` vs scenario vectors `embed_document`; Layer C
relevance filter and sink centroids both `embed_document`; Layer D similarity mode client turns
`embed_query_matrix` vs `build_scenario_vecs` (same regime as Layer B, which is what makes the two
bands comparable); `rank_benchmark_responses` document-vs-document on both sides; Layer A centroids
only ever compared to other Layer A centroids. **`_matrix` and list variants provably agree** —
`embed_query` is literally `_embed_matrix(texts, _QUERY_PREFIX).tolist()`: one code path, one cache
key, no possibility of divergence (`embedder.py:409-420`). *Carry-forward if the hosted backend is
ever enabled*: `embedder.py:120-131` records that `task_type` is **inert** on `gemini-embedding-2`,
so `embed_query` and `embed_document` would return **identical** vectors and the query/document
asymmetry every threshold was calibrated against disappears entirely rather than merely shifting.

**Speaker fail-open is real but currently NOT firing for Joveo staff — MEASURED, not assumed. This is
the strongest clean result in the wave.** Across all 103 `csm_recordings/*.speakers.json`, **254 of
254 speaker slots carrying a `@joveo.com` email** are matched either by the mapped `csm_name` or by
one of the 32 names in `JOVEO_SPEAKER_NAMES`; **zero fall through to CLIENT.** Resulting split over
106 mapped transcripts: 6,468 CLIENT / 3,563 CSM / 2,573 OTHER_JOVEO turns. Separately,
`preprocessing/transcript_parser._classify:55` requires an **exact** string match before returning
`SpeakerRole.NAREN` (every other role is prefix-matched), so a spelling divergence would silently
demote Naren to `JOVEO_OTHER` and zero out `layer_b.extract_pairs` for that call — **checked:
13,222 of 13,222 Naren speaker lines across `recordings/` are the exact string `Naren Shankar`.**
So the "internal chatter becomes coaching findings" risk is **closed for the current roster**: it is
a maintenance hazard (a new colleague not added to the env var), not a live corruption. The only
residue is the 417 `Unknown Speaker` turns (ALL #9), and the exact-match rule is a latent trap worth
not loosening rather than a defect worth spending on.

**`shared/tuning.py` — both loader guarantees verified.** Raises on unknown keys
(`_build_section:132-134`, `load_tuning:153-155`) and on missing keys (`:135-137`, `:156-158`).
**No dataclass field carries a default** — all five dataclasses checked field by field (`LayerA` 12,
`LayerB` 14, `LayerC` 10, `LayerD` 15, `Embedding` 6), every one a bare annotation, so even without
the `missing` check `cls(**raw)` would `TypeError`. `raw` read with `encoding="utf-8-sig"`; a `None`
section caught by the `isinstance` check at `:126`; all `tuning.yaml` values are unambiguous YAML
scalars. *Not a defect, noted so it is not re-found*: `get_tuning()` caches process-wide while
`load_tuning()` reads `BRAIN_TUNING_PATH` per call, so setting that env var after the first
`get_tuning()` has no effect — no production code does that.

**`get_scenarios` — all three properties the brief names are correct, and the resume path is
complete.** It selects `is_coachable` and `cluster_kind` (`storage.py:253-254`); it takes **no
filter argument** and returns every row, with both `_load_scenario_map` implementations being
predicate-free dict comprehensions — so similarity mode's rejection mechanism is intact and the
per-mode split lives only in `ego_trap/scenario_pool.py` as designed. All six fields `v2/layer_c.py`
reads from the map are in the SELECT, and `scenario_calls` (the milestone support denominator) is
derived from the responses at `v2/layer_c.py:214`, **not** from the map — so omitting evidence
columns cannot move the support gate on a resumed run.

**The two response-pool queries have not drifted.** `get_naren_responses_for_scenario` (scalar
`scenario_key` only) has exactly three production callers, all Layer C clause-pool;
`get_responses_for_scenario_multilabel` (`scenario_key = %s OR %s = ANY(scenario_keys)`) has exactly
one, `ego_trap/rubric_lookup.py:86`. No caller uses the wrong one, and
`tests/test_ego_trap_rubric_lookup.py:86-92` asserts that boundary explicitly.

**Remaining `storage.py` queries — each enumerated with its admitted/excluded population and found
correct or inherently unscoped**: `get_primary_topics` (no predicate); `get_rubric_for_scenario`
(nondeterministic only if duplicate `scenario_key`s existed, which the UNIQUE constraints prevent);
`get_milestone_gap_profile`'s FK join cannot drop rows under normal operation and `min_attempts`
defaults to 1; `count_scenarios_without_status` / `get_rubric_status_report` count the whole table
because there is no `run_id` column — the already-documented one-run-at-a-time constraint, not a new
defect. The three documented accumulation hazards (`attempts = attempts + 1`, `gap_events` SERIAL
PK, `upsert_rubric`'s stable `rubric_id`) are all confirmed present and working as designed;
**no additional accumulation path was found.**

**`cluster_evidence.merge_by_similarity` — the distance/similarity conversion is correct.**
`distance_threshold = 1.0 - threshold` with `metric="cosine"`, `linkage="average"`: average-linkage
over cosine *distances* equals `1 −` the average of the corresponding similarities, so
`mean_distance < 1 − t` is exactly `mean_similarity > t`, matching the docstring. Degenerate inputs
handled, result deterministic. `support_stats` raises on non-parallel inputs and on
`total_calls <= 0`; `nearest_sink_index` and `review_flag_threshold` raise on an empty population
rather than returning a sentinel.

**Pipeline-structure invariants (P3).** `v2/pipeline.py:81-90` `_reconcile` genuinely **raises**
(`AssertionError`, unguarded at the call site, outside the auto-pass try/except). **No DB calls
inside the Layer A Gemma loop** — traced `run_layer_a_v2:489-571`; the first `storage.*` call is
`reconnect_if_closed` at `:577`, after the loop. Auto-pass graduation **reads `stable_pair_ids`**
(`_attempt_graduation:257`), with `member_pair_ids` used only for Jaccard matching and the raw
snapshot; the intersection is maintained correctly and an emptied intersection discards immediately.
`_resolve_primary_topic_key` does receive the **tight** `merge_cosine_threshold`, as documented (the
separate band problem is ALL #14). `_relevance_filter`'s clause-TEXT-keyed dict looks like a
duplicate-collapse bug but is not — identical texts have identical embeddings and therefore identical
relevance. The merge-into-a-sink hole is theoretically open (`by_key.get(target_key)` searches all
records) but no realistic path to it could be constructed, since sink keys are never shown to the
model and `_adjudicate` is stateless.

**Wave 4 clean results (each recomputed from committed artifacts, not taken on trust).**
- **C4 = 0.835 reproduces byte-for-byte** against `logs/h2h_m5.log`, along with C2 (0.543) and C3
  (0.750); the pair construction shows Naren's own trigger, so the control measures what it claims,
  and the structural analogy to W3 holds by inspection. **The head-to-head CLOSED verdict is sound.**
- **The grader-inputs headline reproduces exactly**, and the population-symmetry argument holds on
  inspection: matched and unrelated are built from the **same row**, only `rk` changes; `sign_test`
  pairs on the response's own scenario; `bootstrap_d` resamples items, not milestones, which is the
  right unit. **The retraction of "1.2:1" is well-founded.**
- **The skills one-off rate is exact** to the decimal across all three attempts, and the gemini
  arm's `reused_behaviours_from` makes "the embedder is the only variable" verifiable and true.
- **The retrieval gate is sound**: point estimate and CI from the same estimator, per-query base-rate
  exclusion (the non-obvious right choice), and the probe deliberately runs against the full pool so
  `clean_top1` is not 1.0 by construction.
- **`relative_margin: 0.95`** — the derivation is arithmetically sound, the sweep models the sink
  short-circuit (`dry_run_layer_bc.py:168-176`), and the prediction-vs-production discrepancy is
  already recorded with its correct mechanical explanation. Nothing to add.
- **`null_test_taxonomy.py`** — the symmetry discipline is genuinely correct and unusually well
  argued in its own docstring (same pool, embedder, assignment rule and null), and it prints the
  rigged cluster-membership arm explicitly labelled as an upper bound. Its length confound is real
  but **already documented** in CLAUDE.md with the fix named and not yet applied; the caveat as
  written is accurate.
- **`person language 100% → 3%`** is a fair before/after (the regex is applied identically to both
  arms, and its false positives can only make the drop conservative).

---

## CLAUDE.md CORRECTIONS FROM THESE WAVES

Claims these findings contradict or weaken. **No edit was made to CLAUDE.md.**

| published claim | finding that undermines it | suggested correction |
| --- | --- | --- |
| "Production match width was 63% / 19% / 18% … Both follow mechanically from 73 sinks instead of 15 … Not a margin miscalibration." | T5 (P1 #1) | Add: "…and from a **second** narrowing: `flat_pick` slices `order[:cap]` before discarding sinks, so a sink in the top 3 evicts a qualifying real match. The width is partly a cap artifact, unmeasured." |
| "`shared/relative_match.py` — `_topk_pick`/`_flat_pick` extracted **verbatim** … the rule in one place" | T5 + P1 #4 | "Extracted, but `flat_pick` and `topk_pick` apply `cap` to different populations, and production `assign_scenarios` still runs its own inline copy — the shared module is not what production executes." |
| "only 21 [of ~400] ever flagged for the batch judge — a gap the judge mechanism cannot explain" | ALL #6 | "…21 is ~5% of candidates **by construction** (`review_flag_threshold` is a p95 rank statistic over the run's own candidates). Not evidence that contamination was low." |
| "`min_cluster_size` … a 200-call scenario cannot accumulate milestones merely by being large" (`cluster_evidence.py:181-190`) | T7 | "Above ~1,250 clauses the ceiling binds and `min_cluster_size` is a hardcoded 25 — large scenarios are held to a *proportionally looser* bar, not a stricter one." |
| "47.3% of the sink pool is HDBSCAN noise … `min_cluster_size` resolved to 25 by hitting the ceiling, so the clustering is coarse" | T7 | Strengthen from observation to cause: "the ceiling **is why** it is coarse; the fraction is inert above 1,250 items. Same taxonomy-15 shape as `max(3, min(n//10, 50))`." |
| "Layer C is calibrated to `percentile=40`, `fraction=0.10`" | T1 + W4 #10 | "`percentile: 40` is the lowest value in the swept grid, chosen by an objective minimised by not filtering — and the filter is a **fixed 60% quota** that cannot reject anything. Not a calibrated optimum." |
| "Layer C's relevance filter barely discriminates by topic … a ~6-point gap" (open finding) | T1 | Close it: "explained — the filter is a percentile of the population being filtered, i.e. a fixed 60% quota. A quota cannot separate placebo from real; the 6 points are residual ordering." |
| "~5-6% of clusters (7-10 of 158) actually flipping across the coachable/mechanics boundary between independent runs. **Not root-caused**" | T6 | Add as a candidate cause (not a conclusion): "`v2/layer_a.py:505/531` fails OPEN — a missing or unrecognised `decision` becomes a coachable scenario with no counter. Certain code fact; **speculative** as the explanation." |
| "39.7%–45.8% of pairs [sink-filed] … eight signal shapes measured, all failed" | T4 | Add: "`extract_pairs` drops every CLIENT turn in a block but the last, biasing `trigger_text` toward trailing fragments — a *population* cause upstream of every signal tried. Mechanism certain; magnitude inferred, not measured on `recordings/`." |
| "`sequencing_type == conditional` … the producing path only fires for `position_variance > 0.3` and only when a label appears as a substring of two raw clauses, so it is rarely populated" | ALL #8 | Sharpen: "the substring test requires a Gemma **paraphrase** to literally quote the transcript, so it can essentially never match; `fixed` is a default, not a measurement. The loop also lacks a `break`, so one label can claim multiple clusters." |
| "`_normalize_rating` clamps anything else to `adequate` with a warning (never silently)" | ALL #2 | "It warns only when a *wrong* value is returned. A **missing** id yields `{}` → `None` → `adequate` with **no warning**, and the clamped rows are invisible in the output." |
| "the batch size is the module constant `_GEMMA_BATCH_SIZE` … use `score_milestones_batch()`/`score_soft_skills_batch()`" | ALL #2 | Add: "the two batch scorers are not equivalent — soft skills has no missing-id report, takes the 8192 default output cap instead of 16384, and runs on `_DEFAULT_MODEL` rather than the pinned `_SCORING_MODEL`, so the two halves of one exchange are graded by two models." |
| "Still open, noted not fixed: `pipeline.py`'s Gemma-failure path skips a batch but still marks the transcript checkpoint done" | ALL #4 | Keep, and add the direction: "a forced re-run then double-counts the *successful* signals while the lost ones stay at one, producing a **non-uniform** denominator that cannot be corrected by halving." |
| "36% of `gap_events` are `Signal_Recognition_Failure`" (already retired) / RUN_NOTES "39/61 (64%) missed" | T3 + ALL #5 | RUN_NOTES' 64% is doubly wrong: 98.7% of `missed` mass is the segmenter, and `recognized` alone carries a rubric filter that `missed` does not, so a `skipped_insufficient_responses` scenario reads 100% missed regardless of performance. |
| "It does not measure whether the CSM responded; it measures whether a client turn happened to be last in its block. **Scored milestones are UNAFFECTED**" | T3 | Narrow: scored *verdicts* are unaffected, but the scored *population* is not — **45.8% of client turns can never be scored by construction**, so `attempts` is drawn from a non-random half. |
| "`Deferred_To_Teammate` … `other_joveo` (a teammate answered, not the CSM)" | T2 | Add the hole: "it fires only when there is **no** CSM turn. 17.4% of scored windows are mixed and 16.3% carry ≤5 CSM words — those are graded against the full rubric as if the CSM said everything." |
| "the segmenter … drops `No.` (2) and `Got it.` (3) but keeps `That makes sense.` (4)" | ALL #12 | Add: "`len(sent)` counts punctuation, so `Yeah, sure.` (4 tokens) is **kept** while `Right.` (2) is dropped — the cutoff is decided by whether the transcriber wrote a comma." |
| "`layer_a.min_content_words: 5` is INERT … `build_client_clause_pool`" | ALL #13 | Still inert; the function is now `build_client_pool` and `run_layer_a_v2` still calls it with no `min_content_words`. Update the name so the check remains greppable. |
| "Every scenario ends with a non-null `rubric_status`; `_reconcile` … raises" | T8 | True, but `STATUS_FAILED` is **never assigned anywhere in the repo**, and `run_layer_c_v2` writes `STATUS_GENERATED` unconditionally after `_fallback_v1` — a zero-milestone rubric is reported as `rubric_generated`. |
| "`describe_mode` ships `legacy`; the coverage arm is behind the same key, value `coverage`" | T8 | There is **no `coverage` branch** in `run_layer_c_v2`; setting it silently runs legacy and prints nothing. `describe_coverage_areas` is called only from `trial_layer_c_arms.py`. |
| "the situated path … `_describe_situated` diffs returned ids" (implying the describe path is guarded) | ALL #1 | The **legacy** path — the one production runs — has no such check; a missing id stores a milestone titled "Milestone N" with an empty description and full evidence fields. |
| "A candidate must reappear … across `response_taxonomy_consensus_runs` (3) consecutive runs before it graduates" | ALL #11 | The counter is guarded on `run_id`, which is a hash of the corpus — it cannot advance on an unchanged corpus, which is exactly the case the consensus defends against. |
| "`match_existing_primary_topic` … reuses `merge_cosine_threshold` (existing tight threshold) … since stored `primary_topics` rows are already tight-cohesion groups" | ALL #14 | The threshold was calibrated on **centroid-vs-centroid of clause embeddings**; this compares two short description vectors, a band never measured here. Same "never borrow a floor between two bands" rule the file states elsewhere. |
| "Every trial computed `call_coverage` … against 416, so coverage is slightly understated" | ALL #10 | Narrow to the trials: **production `v2/layer_a.py` uses 400** (calls contributing ≥1 CLIENT item) and is internally consistent. The mismatch is between Layer A (400, items) and the auto-pass (416, pairs) writing the same two columns. |
| "`v2/pipeline.py:51` Stored N pair(s)" (implicitly a write count) | ALL #7 | `insert_kb_pair`'s `ON CONFLICT DO NOTHING` returns the pre-existing id, so the printed count equals the extracted-pair count regardless of how many writes landed. |
| "the noise band is ±0.006 weighted, and 15.6% of milestones (37/237) move on their own" | W4 #6, #7 | No run of `measure_scoring_noise.py` was ever captured; the script's own docstring attributes 15.6% to the **contaminated** comparison it now refuses to make, and gives drift as +0.000. Re-run and capture before citing. |
| "the criteria rewrite's +0.025 is ~4.1x that band — it is real" | W4 #7 | "…clears one observed run-to-run difference of 0.006 (n = 2). Not 4σ." |
| "rewrite net +4.48 vs floor net +2.12, ~2x" | W4 #4 | Milestones present in only one arm score 0.0 in the other, and the baseline lost ~99 attempts to batch failures — the per-milestone tally is contaminated. The pooled 0.043 → 0.068 stands. |
| "C1 position-swap agreement 0.669 … the deeper failure … a property of the judge" | W4 #3 | Per stage c2 0.570 / c3 0.581 / **c4 0.847**; C2's correct answer is a coin flip. Head-to-head is closed by C4, not C1. |
| "Not length (C4's length-matched cell is 0.875, *higher*)" | W4 #9 | n = 8. Length is not ruled out. |
| "17 of 405 milestones are unhittable … 74 attempts, 0 hits, across 12 distinct milestones. **The proof they are impossible**" | W4 #12 | No script computes this; 5 of the 17 have zero attempts; at ~3% full-hit rate P(0 in 74) ≈ 0.10. The shipping decision stands on its non-metric justification. |
| "Reaching a median of 25 needs ~350+ calls, not the ~130 first quoted" | W4 #5 | ≈750 on the paragraph's own measured sub-linear exponent. Changes the feasibility answer against 107 available transcripts. |
| skills three-attempt table ("best validity 0.667 … off by 4x, not a near miss") | W4 #8 | 0.667 at n ≈ 9 is not distinguishable from the 0.80 bar; "off by 4x" describes the `V = 0.20` point only. The closure survives on that point. |
| pool-unit "8 (4.7%) vs 71 (37.2%)" and "corr(negation, content-free) −0.149 → −0.744" | W4 #1, #2 | Both length-confounded; the `thin` test is not unit-invariant and the correlation halves under a length partial. |
| "The top1-top2 matching margin is ~0.01 in BOTH taxonomies … arguably a bigger problem than which taxonomy is used" | W4 #11 | The statistic does not measure the sink/non-sink decision it is said to endanger. |
| "9 of 38 survive both the null test and reading" | W4 documentation hazard | Not reproducible from any artifact — assembled by hand from two scripts that use "beats its own null" with **opposite polarity** (good for coherence, bad for account concentration). |
| "replicated to 0.008 (0.843 → 0.835)" | W4 #13 note | `_flush` writes to an untagged `h2h_control_{stage}.json`, so run 2 overwrote run 1 — the replication is not checkable, and two runs over the same seeded item set measure LLM sampling noise, not sampling replication. |

---

## WHAT WAS NOT AUDITED

Built by diffing directory listings against what the four input files record as audited. Directory
listings only were run; no file inside them was opened.

**Excluded by instruction — already audited on 2026-08-15 (8 files):**
`ego_trap/call_scoring.py`, `ego_trap/milestone_scoring.py`, `calibration/trial_call_scoring.py`,
`calibration/trial_grader_inputs.py`, `calibration/null_test_taxonomy.py`,
`calibration/audit_null_instrument.py`, `calibration/flag_proper_noun_clusters.py`,
`calibration/diagnose_rubric_level.py`.
*Note: three of these (`trial_grader_inputs.py`, `null_test_taxonomy.py`,
`flag_proper_noun_clusters.py`) were nevertheless re-read by Wave 4 for provenance, so they have
two passes. `ego_trap/milestone_scoring.py` was read by P2 as supporting evidence and produced
ALL #2 — it is not untouched either.*

**`calibration/` harnesses no Wave-3 or Wave-4 input reports auditing (27 of 42 files).** The input
files do not themselves record a skip rationale, so the framing "deliberately skipped as backing
closed or withdrawn conclusions" is not confirmable from them — what is confirmable is the list:
`aggregate_cluster_verdicts.py`, `analyze_combined_signal.py`, `analyze_turn_position.py`,
`check_milestone_thickening.py`, `compare_embedders.py`, `compare_matching_subset.py`,
`compare_sink_rescue.py`, `diagnose_sink_pool.py`, `dry_run_ego_trap.py`, `dry_run_layer_a.py`,
`dry_run_layer_c_clustering.py`, `dry_run_response_taxonomy.py`, `export_cluster_batches.py`,
`graduate_sink_topics.py`, `label_trigger_quality_sample.py`, `read_gap_reasons.py`,
`replay_layer_c_admitted.py`, `scenario_coherence.py`, `score_naren_ceiling.py`,
`spot_check_adjudication.py`, `translate_thresholds.py`, `trial_adjudicate_gemini.py`,
`trial_client_move_arms.py`, `trial_gateway.py`, `trial_layer_c_arms.py`,
`trial_pool_unit_gemini.py`, `validate_rubrics.py`.
Three of those — `compare_matching_subset.py`, `dry_run_ego_trap.py`, `graduate_sink_topics.py` —
were *cross-referenced* by P1/P3 as consumers of an audited helper, not audited in their own right.
**`score_naren_ceiling.py` is the notable gap**: the retracted 1.2:1 ratio and the AMENDED
population-asymmetry note both originate there, and no auditor opened it.

**`calibration/` files that WERE audited (Wave 4):** `trial_grader_inputs.py`,
`measure_scoring_noise.py`, `compare_criteria_ab.py`, `trial_head_to_head.py`,
`probe_retrieval_gate.py`, `trial_skills.py`, `trial_pool_unit.py`, `null_test_taxonomy.py`,
`flag_proper_noun_clusters.py`, `validate_taxonomy_vs_layerd.py`, `dry_run_layer_bc.py`.

**Production modules nobody looked at in either pass:**
- `shared/`: `checkpoint.py`, `embed_cache.py`, `gemma.py`, `pinecone_store.py`,
  `rubric_validation.py`, `skills.py`, `coverage_areas.py` (only a docstring line cited in T8),
  `trigger_quality.py` (only its content-word counter, in ALL #13), `topic_grouping.py`,
  `response_taxonomy.py` and `prompts.py` (read as supporting evidence by P3, not audited),
  `head_to_head.py` (audited by W4 for the swap-agreement statistic only).
- `v1/`: `layer_a.py`, `layer_c.py`, `pipeline.py` — all cross-referenced, none audited.
- `v2/`: `layer_b.py` (the 247-byte re-export), `pipeline.py` (supporting evidence only, though it
  produced two CLEAN entries and part of ALL #7/#15).
- `ego_trap/`: `csm_registry.py`, `scenario_pool.py` (supporting evidence only).
- `preprocessing/`: none missed — all three modules audited by P2.
- Repo root: `config.py`, `main.py`, `run_v2_subset.py`.
- `db/`: `schema.sql` cross-checked by P1; **`db/init_db.py` not audited.**

**`ops/` scripts nobody looked at in either pass (14 of 19 entries):**
`_check_baseline_schema.py`, `backfill_csm_speaker_roster.py`, `backfill_scenarios.py`,
`backfill_speaker_roster.py`, `check_csm_speakers.py`, `clear_data.py`, `clear_ego_trap_data.py`,
`derive_joveo_roster.py`, `fetch_avoma_recordings.py`, `rerun_layer_c.py` (cross-referenced by P1
as a caller only), `run_ego_trap.py` (referenced by P2 for `--exclude` only), plus all five
PowerShell recipes: `run_full_pipeline_postfix.ps1`, `run_naren_ceiling.ps1`, `run_noisefloor.ps1`,
`run_subset150_postfix.ps1`, `run_visible.ps1`.
Audited: `ops/flag_uncoachable_milestones.py` and `ops/rewrite_milestone_criteria.py` (Wave 4).

**`tests/` — no test file was audited in either wave.** 34 files present. Only two were examined at
all, both as guards on a production finding: `tests/test_relative_match.py:149` (found vacuous, T5)
and `tests/test_ego_trap_rubric_lookup.py:86-92` / `tests/test_ego_trap_scenario_pool.py:31` (cited
as correctly pinning a boundary). Everything else is untouched — including
`test_ego_trap_milestone_scoring.py` (32.1K), `test_rubric_validation.py` (24.1K),
`test_sink_rescue.py`, `test_naren_ceiling.py`, `test_trial_skills.py` and
`test_two_stage_matching.py`. Given that the one test examined turned out to be a vacuous guard on a
live defect, the test suite is the largest single unexamined surface in this audit.

**Artifacts/logs**: Wave 4 read `grader_inputs_trial*.json`, `h2h_control_c{2,3,4}.json`,
`logs/h2h_m5.log`, `skills_trial*.json`, `pool_unit_clause.json`, `pool_unit_turn_092.json`,
`null_test_taxonomy.json`. Every other file in `Brain/artifacts/` and `Brain/logs/` is unread.
