# Layer D (Ego Trap) Realigned With the Main Pipeline (2026-08-10)

[Findings index](INDEX.md)

### Layer D (Ego Trap) realigned with the main pipeline (2026-08-10)

`ego_trap/` was written before the V2 evidence-triage rework and had absorbed none of three
later changes: `kb_pairs.scenario_keys[]` (2026-06-29), sinks making `scenarios` a
two-population table (2026-07-27), and layer_b replacing its absolute cosine floor with
relative top-K. All of it is now aligned. Zero schema DDL — every new record fits inside the
existing unconstrained `gap_events.gaps` JSONB, and severity is derived at query time.

**The design decision that shapes the rest: the sink filter is PER-MODE, not global.** The two
Step 0 modes need sinks for opposite reasons, and conflating them breaks one of them:

- **gemma mode gets the coachable-only map.** Listing `conversational_confirmation_and_fillers`
  in `PROMPT_STEP0_SIGNAL_CHECK` is an *invitation* to report backchannel as coachable — the
  root cause the 2026-07-06 zero-hit-rate investigation already landed on. Measured: the prompt
  menu drops from 32,575 chars / 161 scenarios to 19,778 / 85 (39% smaller).

- **similarity mode gets the FULL map, sinks included**, because a sink winning the match is the
  *only* mechanism that says "this turn is not a signal". Remove sinks and the best match is a
  non-sink by construction, so every client turn becomes a signal — the old 0.35-floor pathology
  wearing a relative margin.

So **never filter inside `storage.get_scenarios` or `pipeline._load_scenario_map`** — a filter at
either point destroys similarity mode's rejection mechanism. `ego_trap/scenario_pool.py` holds the
split as pure functions, keyed on `is_coachable` (what `relative_match.is_sink_flags` and
`assign_scenarios` use — Layer D must not invent a second definition of "sink") and **not** on
`rubric_status`, because a `skipped_insufficient_responses` scenario is a genuinely coachable
topic whose signals are the most useful thing Layer D produces.

- `shared/relative_match.py` (new) — `_topk_pick`/`_flat_pick` extracted verbatim from
  `v1/layer_b.py` plus `is_sink_flags` (replacing the comprehension that was triplicated at
  layer_b :107/:203/:350) and `cosine_sims`. `layer_b` re-imports them under the old private
  names so `from v1.layer_b import _topk_pick` still works. Behaviour-preserving, proven by the
  35 pre-existing tests in `test_layer_b_assignment`/`test_two_stage_matching`/`test_sink_rescue`
  passing unchanged. The extraction is also what lets the harness measure the real rule.

- **`milestone_id` is now the 1-based ARRAY POSITION, not the `order` field.** `milestone['order']`
  was bracket-accessed, and v1-fallback rubrics (a normal part of the population — 31 of 82
  scenarios in one measured snapshot) store Gemma's raw array with zero validation, so a real
  rubric could `KeyError` the whole run; a *duplicate* `order` was worse, silently merging two
  distinct milestones into one `milestone_performance` row under its
  `(csm_id, rubric_id, milestone_id)` PK. **Migration guarantee:** v2 writes `order = index + 1`
  over the same list it stores, so for every v2 rubric the positional id is byte-identical to the
  old `f"M{order}"` — no existing row is orphaned. Not content-hashed: Gemma rewords descriptions
  every Layer C run, so a hashed id would fragment a CSM's history per run.

- **`sequencing_type == "conditional"` is RECORDED but deliberately never acted on.** Three
  reasons, in force order: `PROMPT_LAYER_C_V2_ORDER` defines it as *ordering* variance, not
  optionality; the producing path (`v2/layer_c._sequence_milestones`, :322-341) only fires for
  `position_variance > 0.3` and only assigns a verdict when a 2-4 word Gemma label appears as a
  **substring of two raw clauses**, so it is rarely populated at all; and excluding conditional
  misses from `attempts` would shrink the score denominator and flatter CSMs with no audit trail.
  Any future rule belongs at query time over `gap_events.gaps`, never in a new column.

- **Evidence is persisted, never used to weight.** `support_calls`/`support_clauses`/
  `relevance_mean`/`position_variance`/`sequencing_type`/`source_v` are copied into each
  `Milestone_Omission` gap, defaulting to **`None`, not `0`** (`0` would assert "recurs in zero
  calls", which is false; `None` says "never measured"). A copy rather than a join back to
  `rubrics.milestones` because `upsert_rubric` replaces that column in place under the same
  `rubric_id`, so the next Layer C run destroys the evidence a past gap_event was graded against.
  Weighting a score by support strength was **rejected** — it conflates CSM performance with
  rubric confidence and no validated support→weight mapping exists.

- `get_rubric_for_scenario` now selects `pipeline_version`; consumers are observability only, no
  behavioural branch. A run whose gap records come mostly from v1-fallback rubrics is measuring
  Gemma free-text, not clustering evidence, and `RUN_NOTES.md` numbers are uninterpretable
  without that split.

- **New `Rubric_Coverage_Gap` gap_event.** A recognized, coachable signal on a rubric-less
  scenario used to produce **no DB row anywhere** — printed as `UNMAPPED_SCENARIO` and dropped.
  It deliberately does *not* touch `signal_recognition_gaps`: the CSM recognized and answered, so
  `recognized=True` would inflate the recognition rate with un-scored events and `missed=True`
  would be a lie. Live surface today is small (1 of 85 coachable scenarios: `rfp_process_disclosure`).

- **Benchmark references now read `scenario_keys[]` and rank by cosine, not `pair_id` order.**
  New `storage.get_responses_for_scenario_multilabel` — a *separate* function, because
  `get_naren_responses_for_scenario`'s `WHERE` is Layer C's clause-pool predicate and widening it
  would silently rewrite the pool for all 148 rubrics and invalidate the 385-milestone replay
  baseline. Measured gain: candidate pool 2,904 → 5,463 responses, 81 of 85 scenarios gained
  candidates, the chosen top-2 changed for **85/85**, and 70 chosen responses are secondary-label
  only (previously invisible). Cosine separation confirms the ranking works: chosen
  `p50=0.646` vs discarded `p50=0.575`, with chosen p10 above the discarded median. Free on a warm
  cache — the same texts were already `embed_document`-ed by Layer B.

- Fixed a real connection leak: `ops/run_ego_trap.py` closed the handle *it* created, but every
  `reconnect_if_closed` swap rebinds the local inside `run_ego_trap_batch`, so the runner closed a
  dead handle and leaked one live Neon connection per swap. `run_ego_trap_batch` now returns the
  live conn. Also added the missing `reconnect_if_closed` at Stage 3.

- Soft-skill ratings: the prompt now enumerates `excellent`/`adequate`/`failing` and
  `_normalize_rating` clamps anything else to **`adequate`** with a warning (never to `failing` —
  that would put a fabricated coaching finding in front of a human). Previously a returned
  `"poor"` produced no gap and no trace. A synonym map was rejected as a curated list.

- `calibration/dry_run_ego_trap.py` (new) — zero-Gemma / zero-write / zero-Pinecone by default,
  imports production code rather than reimplementing it. `--step0-gemma` (1 call per transcript,
  once) and `--pinecone-compare` are opt-in; `--load` replays the persisted artifact for free.
  **Harness bug worth remembering:** its chosen-vs-discarded band initially read "no data" because
  it called `rank_benchmark_responses` with `limit == len(rows)`, hitting that function's own
  `<= limit` short-circuit which returns rows *unranked and without* `scenario_similarity`. The
  one check that proves the ranking separates anything was silently measuring nothing — the same
  class of self-inflicted harness error as the merge-blind `_match_milestones`.

- **Pinecone `query_triggers` is NOT used for matching** (kept only as a `--pinecone-compare`
  measurement). Three reasons: ~40% of the `"triggers"` namespace is itself sink-filed and its
  metadata carries no `is_coachable`, so **the sink-rejection rule is not expressible against it**
  without a per-match DB round trip; the exemplar's `scenario_key` is layer_b's scalar best match,
  i.e. exactly the assignments the sink-rescue investigation documented as unreliable; and the
  margin is calibrated against the trigger-vs-scenario band, whereas Pinecone's
  utterance-vs-utterance band has never been measured here.

- **NEVER clear Layer D data while another pipeline run might still be alive — and "the task was
  reported stopped" is NOT evidence that it is dead.** Cost a full run and ~80 Gemma calls on
  2026-08-10. A background Layer D run was reported as stopped by the agent harness; that is the
  harness's own bookkeeping, not the OS process state. The process kept running, so when the
  tables and checkpoints were cleared and a replacement launched, **two runs shared one database
  and one `checkpoints.db`**: the survivor kept marking transcripts done, the new run skipped 10
  of 19 as `already done`, and `upsert_milestone_performance`'s `attempts = attempts + 1` inflated
  attempts 889 -> 905 across 28 doubly-scored signals. **The log still printed
  `Ego Trap batch complete`** and `calibration/measure_scoring_noise.py` still reported a
  plausible-looking floor. Check the OS, not the harness:
  `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'run_ego_trap' }`.
  Note the venv's `python.exe` is a shim that re-execs the base interpreter, so **one run always
  shows as two PIDs in a parent/child pair** — two PIDs is normal, two different start times is
  not. `ops/run_noisefloor.ps1` now performs this check automatically and aborts before clearing;
  prefer it over doing the clear by hand.
- **Operational rule:** run `ops/clear_ego_trap_data.py` before any real re-run, and after any
  Layer C re-run. `gap_events` has only a SERIAL PK so re-processing **appends duplicates**, and
  `upsert_milestone_performance` does `attempts = attempts + 1` on conflict so it **double-counts**.
  Separately, `upsert_rubric`'s `ON CONFLICT (scenario_id)` keeps `rubric_id` stable while
  replacing `milestones`, so a Layer C re-run can make `M2` mean a different milestone while rows
  keep accumulating under it.

- Still open, noted not fixed: `pipeline.py`'s Gemma-failure path skips a batch but still marks the
  transcript checkpoint done, so those signals are permanently lost on resume while a forced
  re-run double-counts instead.

