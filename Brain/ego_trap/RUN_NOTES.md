# Ego Trap Run Comparison Notes

Tracks gap-analysis results across pipeline runs so V1 (Gemma-direct) and V2
(statistical clustering) scenario/rubric sets can be compared on the same
CSM transcripts.

> **The "Layer D itself doesn't change between runs" assumption that used to head this
> file no longer holds.** Layer D was realigned with the main pipeline on 2026-08-10
> (see CLAUDE.md's "Layer D (Ego Trap) realigned with the main pipeline" section):
> sinks are now excluded from the gemma-mode prompt, the absolute similarity floor was
> replaced by the sink-comparison rule, `milestone_id` is positional rather than
> `order`-derived, and benchmark references read `scenario_keys[]` ranked by cosine.
> **Runs 1 / 1b below therefore compare against a DIFFERENT Layer D than any run after
> that date** — treat the boundary as a hard break, not a continuous series.
>
> Config in the dated entries below is written as `STEP_0_MODE=...` / `EGO_TRAP_*` env
> vars, which is accurate for when those runs happened. Those vars are retired:
> every Layer D knob now lives in `Brain/tuning.yaml` under `layer_d:`, and
> `ops/run_ego_trap.py` refuses to start if one is still set in `.env`.
>
> The Layer D tables were empty as of 2026-08-10 (`gap_events` = 0 rows), so no run
> below is still reproducible from the DB — only from these notes.

## Run 1 — V1 pipeline (Gemma-direct)

- **Date:** 2026-07-06
- **run_id:** `c85b92080d71`
- **Transcripts:** `rec3.txt`, `rec5.txt`, `rec6.txt` (all CSM: Madhumita Katta / `CSM_MADHUMITA`)
- **Skipped:** `sample_call_priya_001.txt` — no row in `mapping.csv`

### Results

- **Signal recognition:** perfect. 7 occurrences across 3 scenario types, 0 missed
  (`signal_recognition_gaps`: `conversion_mapping_complexity` 3/3,
  `high_volume_recruitment_optimization` 3/3, `managed_service_vs_direct_access` 1/1).
- **Milestone execution:** 0/8 hits. Every milestone attempt on the two scenarios
  with real rubrics came back a miss:
  - rubric 35 `high_volume_recruitment_optimization` — 3 attempts, 0 hits (M1-M4)
  - rubric 34 `managed_service_vs_direct_access` — 1 attempt, 0 hits (M1-M4)
- **`conversion_mapping_complexity` (rubric 33) unscoreable:** 0 milestones defined
  in the rubric, so its 3 `gap_events` (rec5, rec6×2) show empty hit/miss lists —
  not a CSM performance signal, a rubric authoring gap.
- **3 scenario keys with zero rubric coverage** — repeatedly triggered
  `UNMAPPED_SCENARIO` across all 3 calls, and every one of those signal
  detections was dropped entirely (not persisted to `gap_events` or anywhere else):
  - `ats_integration_friction`
  - `dynamic_budgeting_and_capping`
  - `multi_entity_budget_management`

## Observations to work on

1. **Milestone rubrics for `high_volume_recruitment_optimization` and
   `managed_service_vs_direct_access` may be too strict, or Madhumita's calls
   genuinely have a milestone-execution gap** — 0/8 across two scenarios is a
   pattern worth a manual transcript read before treating it as ground truth.
2. **Author milestones for `conversion_mapping_complexity` (rubric 33)** — it's
   currently a silent no-op in scoring.
3. **Author rubrics for the 3 unmapped scenario keys** (`ats_integration_friction`,
   `dynamic_budgeting_and_capping`, `multi_entity_budget_management`) — these
   fired often enough across just 3 calls to suggest real coverage gaps in the
   knowledge base, not edge cases.
4. **`sample_call_priya_001.txt` has no CSM mapping** — add a row to
   `csm_recordings/mapping.csv` if that call should be included in future runs.

## Run 1b — similarity mode @ threshold 0.35 (pre-fix, superseded)

- **Date:** 2026-07-06
- **Transcripts:** `rec3.txt`, `rec5.txt`, `rec6.txt` (CSM: Madhumita Katta)
- **Config:** `STEP_0_MODE=similarity`, `EGO_TRAP_SIMILARITY_THRESHOLD=0.35`
- **Results:** 61 `gap_events`, 0/61 `Milestone_Omission` scoring came back a hit.

### Root cause finding: 0% milestone hit rate is NOT a prompt-bias bug

Investigated whether Gemma was rejecting milestones because rubric descriptions are
worded around "Naren" specifically (e.g. "Naren explicitly acknowledges...") rather
than "the CSM" generically. **Ruled out** — pulled all 61 stored `Milestone_Omission`
reasons from `gap_events.gaps` and every single one is a legitimate content critique
("the response discusses the CSM's camera status", "the response is a simple
scheduling confirmation", "the response does not reference a product roadmap"). None
reject on the responder's identity/name.

**Actual root cause, confirmed by reading `rec3.txt` at the real `signal_turn_index`
values:** the 0.35 similarity threshold is matching topic-irrelevant small talk to
real scenarios. Concretely:

- Turn 1 (`"I'm good. Thank you."` — opening pleasantries) matched
  `managed_service_vs_direct_access` at ≥0.35. The paired CSM turn is about being
  off-camera — Gemma correctly scored every milestone a miss because there's
  genuinely nothing on-topic there.
- Turns 175/179 (calendar/scheduling chatter — "I think my last call on my calendar
  is Thursday", "I was able to get into the project plan") matched
  `workday_technical_onboarding` / `managed_service_vs_direct_access` — again
  content-unrelated false positives.

So the milestone scorer is working correctly on what it's given; what it's given is
frequently a false-positive Step 0 signal. This confirms the "Validate the 0.35
similarity threshold" item from the prior session's notes — it wasn't just
unvalidated, it demonstrably produces false positives on non-substantive utterances.
**No milestone_scoring.py or rubric wording change was made** — that hypothesis is
refuted by evidence. Decision (2026-07-06): leave the threshold as-is for this next
run and use the post-run manual validation pass to empirically ground a future
threshold change, rather than tuning blind.

### OTHER_JOVEO mislabeling — fixed

`csm_responded` (boolean) replaced with `response_outcome` (`"csm"` / `"other_joveo"`
/ `"none"`), computed in code from actual turn roles via
`transcript_parser.classify_response_outcome` — not asked of the LLM anymore, even in
`STEP_0_MODE=gemma`. A teammate (`OTHER_JOVEO`) answering a client point now writes a
`Deferred_To_Teammate` gap_event (`gap_output.write_deferred_to_teammate`) instead of
a `Signal_Recognition_Failure`, and is excluded from `signal_recognition_gaps`
recognized/missed counters entirely (it's neither a CSM hit nor a CSM miss). True
`Signal_Recognition_Failure` now only fires on `response_outcome == "none"`. This data
(Run 1b above) was scored under the old boolean logic, so its 64% "missed" signal
recognition rate is stale and will be superseded by the next run.

## Run 2 — V2 pipeline (statistical clustering)

- **Date:**
- **run_id:**
- **Transcripts:**
- **Results:**
- **Diff vs Run 1:**
