# Layer C — Profile Rebuild, Three Changes Shipped OFF (2026-08-12/13)

[Findings index](INDEX.md)

### Layer C rebuild — three changes, all shipped OFF (2026-08-12/13)

Design: `docs/superpowers/specs/2026-08-12-layer-c-profile-rebuild-design.md`. Narrative and
the methodology failures: `Brain/PROBLEMS_AND_FIXES.md`.

**Root cause, and why a fourth wording pass cannot work.** Read from
`v2/layer_c.py::_describe_milestones_batch` — the model writing each criterion sees the
scenario's KEY STRING, its own response clauses, and nothing else. It has never seen a client
turn, so it cannot state a precondition (234 of 235 milestones are labelled `fixed`; the
conditional trigger fires **0 of 226**), and it is told to strip specifics on top. That is a
missing-INPUT problem. Asking a better-worded question of a blind model changes nothing.

| what | where | flag |
| --- | --- | --- |
| situated describe inputs | `PROMPT_LAYER_C_MILESTONE_DESCRIBE_SITUATED`, `v2/layer_c._describe_situated` | `layer_c.describe_mode: legacy` |
| coverage areas + 4th verdict | `shared/coverage_areas.py`, `PROMPT_LAYER_C_COVERAGE_AREAS`, `milestone_scoring.score_coverage_batch` | same key, value `coverage` |
| skills (profile axes) | `shared/skills.py`, `PROMPT_SKILL_ABSTRACT_BATCH` | not wired to production |
| the trial harness | `calibration/trial_layer_c_arms.py` | read-only, artifacts only |

- **`describe_mode` ships `legacy`; production Layer C is byte-identical.** The situated path
  needs `build_clause_pool`'s 4th return value (`clause_pairs`) and `trigger_text` on
  `get_naren_responses_for_scenario` — both additive, both threaded through `_relevance_filter`
  into each cluster's `pair_ids`. Verified live: `client_reacts_to_anomaly` has 34 pairs across
  27 calls, so 7 calls contribute more than one pair and attributing triggers by
  `call_filename` would hand a cluster the trigger of a moment that never produced the move.
- **Half of the 2026-08-10 rule is DROPPED in the situated prompt.** That rewrite banned two
  things in one breath: "never narrate a person" (correct, kept, ~4x the noise band) and "never
  state the specific instance" (**the over-correction** — it is what made criteria
  scenario-agnostic). A criterion may now name its subject matter; it still may not name a
  person.
- **Batching is per SCENARIO in the situated path**, not 5 milestones across all scenarios.
  That is what lets a move see its siblings, which the legacy prompt had to forbid because its
  batches mixed unrelated scenarios. Cost is unchanged: 81 calls vs ~82.
- **`_describe_*` take an optional `model=`, defaulting to None.** The situated/coverage
  prompts pack a whole scenario and cannot fit `gemma-4-31b-it`'s 16k TPM ceiling — measured
  2026-08-13, one call burned 8+ minutes of backoff. Only the trial passes the flash-lite
  chain, so production is unaffected.

**Established by the trial so far (corpus-level, replicated):**

- **Do NOT remove Naren's benchmark response from the scorer.** Hypothesis was that it makes
  the grader match on resemblance and inflates the null. **Refuted, and it goes the other
  way:** removing it moved discrimination 1.30 -> **1.12**, null rising 0.130 -> 0.150. It
  anchors the grader to a scenario-appropriate standard. Valid despite the sampling bug below —
  paired comparison, same rubrics both sides.
- **"Did this moment call for this move" has now failed TWICE, in two different framings.**
  The standalone applicability judge: 0.147 matched vs 0.120 unrelated (1.22:1). The coverage
  judge with the client turn AND response in front of it: **64.9% `not_called_for` matched vs
  65.7% unrelated**. Treat a third attempt as speculative, not routine.
- **Corpus-level is stable, per-scenario is not.** Baseline reproduced at 1.30 / 1.30 / 1.21
  across three separate runs with spreads of +/-0.002-0.018. That is why the gate is
  corpus-level and why arm comparison works at all.
- **`ops/run_visible.ps1`** runs a Brain script in a real window that stays open, with the
  neon DNS bypass built in. Three bugs are documented in the script so they are not
  reintroduced: `-Args` is a PowerShell automatic variable; the inner script must call the venv
  python by full path; and `-ScriptArgs` must be ONE STRING because `-File` does not preserve
  array syntax.
- **Always smoke-test a harness end to end before a full run.** `--sample 2 --per-scenario 2
  --reps 1` costs ~20 calls and exercises every path. Two full launches died mid-generation on
  a missing import and a positional slice (`ARMS[2:]`) — **`py_compile` catches neither**.
  `score_naren_ceiling.py` already had this in `--max-items-per-arm`.

