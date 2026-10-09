# Layer D Redesign — Gap Analysis Against Playbooks (2026-08-20)

Operator decisions (2026-08-20): standard = live playbooks; run on what's live; deliverable =
ranked coaching priorities (no headline score); spend = whatever the gates justify, staged;
**build BOTH graders** and let a pre-registered head-to-head choose the production arm.

## 1. Context

The old Layer D (`Brain/ego_trap/`) is dark: `rubrics`/`gap_events`/`milestone_performance`
are empty (keyed to the pre-union taxonomy) and its thresholds were fitted to bge@768 bands
that the shipped `gateway` (gemini@3072) backend inverts. Meanwhile Layer A is `union_base`
(259 scenarios: 34 coachable + 225 sinks), Layer B is complete (12,444 routed kb_pairs), and
Layer C shipped **playbooks**: per scenario 3–6 ordered `key_moves` (positional `move_id`
M1..Mn) each with a criterion + verbatim Naren evidence, plus one binary `layer_d_check` per
move. 5 of 34 coachable scenarios have a `live` playbook; the scale-up is a separate task.

## 2. Settled facts the design must not violate

| Fact | Consequence |
|---|---|
| Absolute cosine floors failed every time; sink-relative rejection works (57–61%) | Signal detection stays sink-relative over the FULL map |
| Per-item embedding threshold filters failed 9 consecutive times | No embedding-only occurrence scorer |
| Call-level LLM scoring fabricated 23% of credited quotes — REJECTED by its own gate | Moment-level grading; programmatic quote verification is a hard gate |
| The criteria scorer discriminates (77–82% paired win share); the old criteria were unpassable (W≈0.09) | Keep per-criterion grading; fix the criteria (playbook moves) + item analysis |
| `Signal_Recognition_Failure` was 98.6% segmentation artifact | Client-move segmentation (arm E) ships first; that gap type is retired |
| Arm E: +81 scored exchanges, 0 lost (pre-registered) | `segmentation_arm: e`, C1 must reproduce lost=0 in gemini space |
| Speaker classification fails OPEN (87/113 unclassified) | Pipeline fails CLOSED: client roster required, or explicit override |
| Failed Gemma batches were checkpointed, losing signals permanently | Checkpoint marked ONLY after every batch of a transcript succeeds |
| `gap_events` had no uniqueness; a double run double-counted 28 signals | `move_events` upserts on a natural key; `move_performance` is a full recompute |
| gemini space: trigger/response bands collapsed; bge floors inverted | Every number re-measured (C0) before anything runs |

## 3. Literature grounding (Aug 2026 sweep)

Binary atomic checks beat Likert (CheckEval: +0.45 agreement); extraction-first judging with
mandatory verbatim spans verified at ~80% token overlap drives fabrication to ~0 (Rulers,
FActScore/VeriFastScore); relative-to-anchor beats absolute at the judge layer (RAEE −44% SE;
industry ships behavior RATES vs benchmark, never absolute call scores); single-run verdict
flips are a documented general phenomenon (Rating Roulette) remedied by k-run consensus; dead
criteria are detectable from data (IRT judge diagnosis — criterion-intrinsic); sparse per-rep
cells need empirical-Bayes shrinkage before ranking; and self-consistent judges can be
consistently wrong, so a small human-judged gold set (C4) stays in the ladder.

## 4. Design

**The central mechanism — dual-population move rates.** The same instrument scores Naren's
own routed moments (from kb_pairs, routing already paid for) and CSM moments. A gap is a
shrunken rate difference per (csm, playbook_id, move_id): "Naren does M3 in 8/9 comparable
moments; you do it in 1/12." Verdicts are absolute; interpretation is relative. A check
Naren himself fails below `dead_check_naren_floor` is flagged as a bad check and excluded
from ranking — the data-driven answer to the old 24%-dead-criteria waste.

**Package `Brain/layer_d/`** (ego_trap untouched until parity; its parser/registry/signal
machinery imported, not copied):

| module | role |
|---|---|
| `segmentation.py` | client blocks, by-speaker moves, arms today/e (re-homed from the trial) |
| `signals.py` | `SignalScorer` (memoized sink-relative admit), `detect_moments`, fail-closed `unverified_speakers` |
| `verify_quotes.py` | containment + `best_span` alignment ≥ `quote_verify_min_overlap`; empty quote never verifies |
| `graders.py` | **checks** arm (binary, evidence-gated, batched ≤6/request) and **pairwise** arm (3-way vs exemplar, order-swapped, position-consistent only); 4-state verdicts (`hit/partial/miss/unscored`); k-run majority consensus |
| `aggregate.py` | rates, attempt-weighted cohort priors, EB shrinkage, dead checks, gap ranking, report text |
| `pipeline.py` | orchestration; checkpoint-on-success-only; naren benchmark pass; `build_reports` |
| `prompts.py` | the two grader prompts |

**Unscored is not a miss.** Instrument failures (id missing from the response, quote failed
verification, swap-inconsistent, run disagreement) are counted in their own column and
excluded from every rate. The old pipeline normalized parse failures to "miss", so
truncation manufactured coaching failures.

**DB:** `move_events` (natural unique key `(rater_population, call_id, source_ref,
playbook_id, grader_arm)`; verdicts JSONB) and `move_performance` (PK per rater/playbook/
move/arm; materialized by `storage.refresh_move_performance`, a DELETE+INSERT recompute).
Both key `playbook_id` NOT NULL and are in `ship_union_taxonomy.py`'s SNAPSHOT_TABLES and
DELETE_ORDER (children before `playbooks`). Old empty gap tables retire with ego_trap.

**tuning.yaml `layer_d` additions** (rubric-era keys kept until ego_trap retires):
`segmentation_arm: e`, `grader_arm: checks` (PROVISIONAL — C2 decides), `grader_k_runs: 1`,
`quote_verify_min_overlap: 0.80`, `shrinkage_prior_strength: 5.0` (UNCALIBRATED),
`dead_check_naren_floor: 0.50`, `min_attempts_to_rank: 8` (UNCALIBRATED). The redesign also
reads `similarity_relative_margin` and `max_scenarios_per_signal` (same meaning both
generations).

**Retired gap types:** `Signal_Recognition_Failure` (artifact), `Milestone_Omission` /
`Rubric_Coverage_Gap` (superseded by move rates / the run report's coverage-gap counts).
Deferrals survive as ungraded `move_events` rows (`response_outcome='other_joveo'`),
queryable with no LLM. Soft-skill scoring is dropped (never validated).

## 5. Calibration ladder (pre-registered; any gate failure ⇒ stop, bring operator options)

| Stage | What | Spend | Gate |
|---|---|---|---|
| **C0** | `calibration/layer_d_bands.py --spend`: gemini-space bands for CSM turns, sink-rejection rate, admitted/gradable counts per arm | ~6.5k embeddings (paced, cached forever); zero chat | Report-only; operator reads before C2 |
| **C1** | re-run `calibration/trial_client_move_arms.py` (free after C0 warms the cache) | zero | arm E lost=0 reproduced; real-minus-sink margin does not fall |
| **C2** | grader head-to-head: ~60 CSM moments on the 5 live playbooks, matched/unrelated pairs, both arms, k=3 | ~400–600 chat calls | per arm: quote verification ≥95%; discrimination ≥70% per-scenario paired win share, p<0.05; noise floor reported. Highest-discriminating arm passing both hard gates ships; tie → checks |
| **C3** | Naren ceiling: benchmark pass over the 5 live playbooks, winning arm, k=3 | ~150–400 chat calls | per-check Naren rates published; sub-floor checks flagged BEFORE production |
| **C4** | human gold: reader panel on ~15 moments (house pattern) | ~zero | agreement bar set with operator before reading |

C2/C3 harnesses are not yet written; each gets ONE blind code audit before it spends
(house rule). Then the first production run (`ops/run_layer_d.py`), whose report carries
coverage gaps, dead-check flags, unscored rates, and the first classical item-analysis pass.

## 6. Non-goals

Multi-tenancy; the §5 onboarding review (phase 2, after the first run produces the
never-performed list); full IRT / adaptive item selection; playbook scale-up; within-call
arc/sequencing analysis; account-journey tracking; anything keyed to `rubrics`.

## 7. Verification

1. `pytest tests/` file-by-file — new `test_layer_d_*.py` suites green, zero regressions.
2. C0–C4 in order, artifacts in `Brain/artifacts/`, findings in
   `Brain/docs/findings/layer-d-redesign.md` + INDEX.
3. Replay property: re-running `refresh_move_performance` from stored events reproduces the
   table exactly (it IS the recompute; `ops/run_layer_d.py --report-only` exercises it).
4. Idempotency: a forced second pass over a processed transcript leaves row counts unchanged
   (natural-key upsert), verified on the first production run.
5. The operator reads the first ranked-priorities report against 2–3 raw transcripts before
   the output is called real.
