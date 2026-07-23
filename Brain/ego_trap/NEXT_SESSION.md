# Ego Trap — Session Handoff (2026-07-06)

Context for picking this back up fresh. Read this before touching `ego_trap/` again.

## Fixes applied this session (all live in code)

1. **Missing CSM mapping no longer crashes the batch** — `pipeline.py`: a transcript with no row in `mapping.csv` is skipped with a log line instead of raising `KeyError`.
2. **Persistent Gemma errors no longer crash the batch** — `pipeline.py` wraps the Gemma scoring calls in `try/except GemmaError`; a failing batch is logged and skipped instead of killing the whole run.
3. **`IdleInTransactionSessionTimeout` fixed** — `storage.get_connection()` now opens with `autocommit=True`. Root cause: `get_scenarios()` (a bare read, no `.commit()`) left a transaction open across slow Pinecone/Gemma calls until Neon killed it.
4. **`SSL connection has been closed unexpectedly` fixed** — `storage.reconnect_if_closed(conn)` (existed but was unused anywhere) is now called at each pipeline stage boundary in `pipeline.py`.
5. **Pinecone client/index no longer rebuilt per call** — `shared/pinecone_store.py` now caches the `Pinecone` client and `Index` object at module level (was rebuilding both on every single `query_triggers()` call — once per CLIENT turn, serially).
6. **Gemma call volume reduced via batching** — discovered `score_milestones()`/`score_soft_skills()` were making one Gemma call *per milestone* / *per soft-skill name*, not per signal. Added `score_milestones_batch()` / `score_soft_skills_batch()` in `milestone_scoring.py` plus new prompt templates in `shared/prompts.py`, controlled by `ego_trap.settings.GEMMA_BATCH_SIZE` (env `EGO_TRAP_GEMMA_BATCH_SIZE`, default `4`).
7. **`pipeline.py` restructured into 5 staged passes** per transcript (each stage processes *all* signals before the next starts): response-check → rubric lookup → batch-pull response/benchmark text → Gemma batch-score → build+write gap records. Stage-progress logging added throughout.
8. **`CLAUDE.md` updated** with 8 new gotchas/architecture notes covering all of the above (search for "EGO_TRAP_SIMILARITY_THRESHOLD", "GEMMA_BATCH_SIZE", "reconnect_if_closed").

## Current pipeline configuration (`Brain/.env`)

```
STEP_0_MODE=similarity
EGO_TRAP_SIMILARITY_THRESHOLD=0.35
EGO_TRAP_GEMMA_BATCH_SIZE=4   # (settings.py default, not currently in .env — add if you want to override)
```

## Key observations from this session's runs

- **Signal volume is threshold-sensitive but not in the way expected**: 0.75/0.6 → 0 signals, 0.50 → 1 signal, 0.35 → **61 signal occurrences** across the same 3 calls (rec3/rec5/rec6, CSM Madhumita Katta). This similarity check compares CLIENT utterances against other real stored trigger utterances (not abstract scenario descriptions like `layer_b.py` does), so higher raw scores than the documented ~0.14 ceiling are plausible — but **the 0.35 volume hasn't been validated against ground truth**. Nobody has manually checked whether these 61 matches are actually correct scenario assignments.
- **Milestone hit rate has been 0% (or effectively 0%) in every single run this session** — gemma-mode detection, similarity at 0.50, similarity at 0.35, old per-call scoring, new batched scoring. Dozens of milestones, zero exceptions bar one (`brand_asset_collection` M1, 1/2 hits). That consistency is suspicious enough to be worth investigating rather than accepting at face value (see Research Q2 below).
- **`OTHER_JOVEO` mislabeling confirmed** — manually inspected `rec3` turn 54 (`high_volume_recruitment_optimization`): the client's point was answered by a teammate (`OTHER_JOVEO` role), not the CSM, but `turns_until_next_client()` only checks for `role == CSM`, so it's logged as a `Signal_Recognition_Failure` identical to true silence. Given `signal_recognition_gaps` shows 39/61 (64%) "missed" at threshold 0.35, some unknown fraction of that 64% is likely this mislabeling, not real CSM misses.
- **Batched Gemma scoring verified correct** — spot-checked `gap_events.gaps` JSONB for several batched calls; reasons are distinct and specific per milestone, no cross-contamination between items in the same batch.

## What to research / fix next

1. **Fix `OTHER_JOVEO` mislabeling** (highest priority, already scoped). Replace the boolean `csm_responded` with a 3-way outcome (`csm` / `other_joveo` / `none`) in `signal_check.py`'s similarity and gemma paths. True `Signal_Recognition_Failure` should only fire on `none`. Add a new gap category (e.g. `Deferred_To_Teammate`) for the `other_joveo` case so the data isn't discarded, just reclassified. Touches: `ego_trap/signal_check.py`, `ego_trap/gap_output.py`, possibly `db/schema.sql` if a new gap type needs a column/enum.
2. **Investigate the 0% milestone hit rate.** Rubric milestone descriptions are literally worded "Naren explicitly acknowledges...", "Naren explains...", "Naren references..." — authored from Naren's own benchmark calls, never genericized to "the CSM." Read the actual reasons Gemma gives (they look like legitimate content critiques, not name-matching), but with *zero* exceptions across 3 runs and dozens of milestones, rule out prompt bias before treating this as a real finding. Consider: reword a handful of rubric milestones to be CSM-generic and re-score the same signals to see if hit rate changes.
3. **Validate the 0.35 similarity threshold.** No ground truth check has been done — manually review a sample of the 61 matched signals to see how many are genuinely on-topic vs. false positive scenario matches.
4. **Re-run and update `Brain/ego_trap/RUN_NOTES.md`** once #1 and #2 are resolved — the current numbers (64% miss rate, 0% milestone hits) should not be treated as final/trustworthy until those two issues are addressed.
