# Milestone Verdict Tiers — Design Spec

**Date:** 2026-07-13
**Status:** Approved, pending implementation plan
**Scope:** `Brain/ego_trap/milestone_scoring.py`, `Brain/ego_trap/gap_output.py`, `Brain/shared/storage.py`, `Brain/shared/prompts.py`, `Brain/db/schema.sql`, `Ego_trap.md`

## Problem

Milestone scoring (Step 3 of the Ego Trap pipeline) currently returns a binary `hit: true/false` per milestone, with a one-sentence `reason` string. This has two flaws:

1. **No gradation.** A CSM who fully nailed a milestone and one who barely gestured at it both register identically as `hit: true` (or both as `false` if slightly short) — there's no way to distinguish "fully satisfied" from "attempted but weak."
2. **Thin evidence.** The only artifact behind a verdict is a one-sentence `reason`. There's no verbatim quote tying the verdict to the transcript, and no explanation of what a full hit would have looked like — making it hard for a human (or a future coaching UI) to trust or act on a miss.

## Design

### 1. Verdict tiers (replaces `hit: bool`)

Three tiers, replacing the boolean outright — no backward-compatible boolean is retained. This is safe because Ego Trap tables are wiped between tuning runs (`clear_ego_trap_data.py`) and there are no external consumers of the old shape yet.

| Verdict | Meaning |
|---|---|
| `full_hit` | Milestone fully satisfied |
| `partial_hit` | Attempted, but incomplete or weak |
| `miss` | Not addressed |

**Threshold provenance:** these three tiers reuse the entailment-probability boundaries already defined in `Ego_trap.md`'s Step 3 V2 spec (NLI cross-encoder, not yet built): `entailment_score >= 0.80` → full_hit, `0.55–0.79` → partial_hit (currently documented as "borderline, escalate to Gemma"), `< 0.55` → miss. Reusing these boundaries means a `partial_hit` verdict means the same thing regardless of whether Gemma (V1, today) or NLI (V2, future) produced it — no redefinition needed when the scoring engine changes underneath.

**V1 output shape (Gemma, now):** tier only, no fabricated numeric confidence score. An LLM-estimated 0–1 number would imply false precision (LLM scores drift/cluster run-to-run); a real numeric score is only trustworthy once it comes from an actual model (V2's NLI entailment probability), so numeric scoring is deferred to V2.

### 2. Evidence generation (quote + gap-to-ideal)

Gated to `partial_hit` and `miss` only — a `full_hit` produces no evidence, same as today (a `hit: true` milestone currently produces zero evidence downstream in `gap_output.py`; this design just extends that existing gate to cover `partial_hit` too).

Fields, produced by the same Gemma call that already runs for non-hits today (no new call in V1):
- `reason` — unchanged, one-sentence explanation (already exists)
- `quote` — verbatim excerpt of `csm_response_text` that the verdict is based on. Since the full response text is already passed into the prompt, this is an extraction Gemma echoes back, not new external cost.
- `gap_to_ideal` — one sentence naming what a `full_hit` would have included, contrasted against the benchmark response already in the prompt.

**V1→V2 cost note:** V2's stated goal is eliminating LLM calls at scale by using NLI for the tier decision. This does not conflict with evidence generation, because evidence generation is gated on tier outcome (`miss`/`partial_hit`), not on call volume — it scales with *gap count*, which is the metric this whole system is trying to shrink over time. When NLI decides a tier directly (no Gemma involved), a `miss`/`partial_hit` outcome still triggers a small, separate Gemma call purely for evidence generation (reason/quote/gap_to_ideal) — the same scope Gemma already has today, just decoupled from tier-decision.

### 3. Storage — `milestone_performance` aggregation

Current schema only supports a binary hit rate (`hits`/`attempts`). Add one column to carry partial credit:

```sql
ALTER TABLE milestone_performance
  ADD COLUMN partial_hits INTEGER NOT NULL DEFAULT 0;
```

- `hits` now means full_hit count only (unchanged column, redefined meaning)
- `partial_hits` tracks partial_hit count separately
- `attempts` unchanged

Weighting is computed at **read time**, not baked into storage: `weighted_score = (hits + 0.5 * partial_hits) / attempts`. Keeping the 0.5 weight out of storage means retuning what "partial" is worth later is a query change, not a backfill.

### 4. `gap_events.gaps` JSONB shape

Replace `"hit": false` with `"verdict": "miss"` (or `"partial_hit"`). Add `"quote"` and `"gap_to_ideal"` fields alongside the existing `"reason"` for any `Milestone_Omission` gap entry where verdict is `partial_hit` or `miss`.

### 5. Out of scope

- Soft skill scoring (`score_soft_skills`) is unchanged — this design only touches milestone scoring's `hit` boolean, per the original ask.
- V2 (NLI cross-encoder) is not being implemented now — this design only ensures V1's output shape is forward-compatible with it.

## Documentation updates

`Ego_trap.md`'s Step 3 section (V1 prompt shape, Layer D upsert SQL) will be updated to reflect the verdict-tier shape in place of `hit: true/false`, so the spec document stays the accurate reference for future sessions.

## Testing impact

`Brain/tests/test_ego_trap_gap_output.py` currently asserts against the boolean `hit` shape and will need updating to assert against `verdict` tiers instead. No other test files reference milestone `hit` scoring directly.
