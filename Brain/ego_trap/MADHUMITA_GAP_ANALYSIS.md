# Madhumita Katta — Ego Trap Gap Analysis

**Date:** 2026-07-07
**Run ID:** `c85b92080d71` (gemma-mode)
**Source:** `gap_events` table, joined to `csms` on `csm_name = 'Madhumita Katta'` — 10 records total across `rec3.txt`, `rec5.txt`, `rec6.txt`

This walks through every record the pipeline has for Madhumita and explains, in plain terms, why each one landed where it did.

---

## The 2 scenarios that got actually scored (CSM responded + a rubric existed)

### rec3, turn 69 — `high_volume_recruitment_optimization`
The client raised a point on this topic, Madhumita personally responded, and Naren's Brain has a 4-milestone rubric for it, so Gemma graded her answer. **0/4 milestones hit:**

| Milestone | Missed because |
|---|---|
| M1 — validate the pain point as common/critical before solving | Her response was a clarifying *question*, not a validation |
| M2 — reference a specific client/case study | No client names or examples cited |
| M3 — describe how tech/AI removes manual effort | No automation/technology described |
| M4 — expand to a broader strategic goal (e.g. ROI) | Stayed narrow, no ROI framing |

Soft skills also failed: **strategic thinking**, **confidence**, **industry expertise** — all for the same root reason, the response was too brief to demonstrate any of them.

### rec3, turn 93 — same scenario, later in the same call
Same rubric, same result: **0/4 milestones**. The actual CSM response here was literally **"Got it"** — a passive acknowledgment with nothing to grade favorably against any of the 4 criteria. Same 3 soft-skill fails, same underlying reason (nothing substantive to evaluate).

**Why this scenario specifically is the only one that got scored twice:** it's the only topic where all three conditions lined up — Naren has an authored rubric for it, *and* Madhumita answered personally (not a teammate), *and* Gemma could match the client's exact wording back to the transcript. Every other detected topic below failed at least one of those three conditions.

---

## The 6 records marked "Deferred to Teammate" (not counted against her)

These are cases where Gemma correctly caught a real client topic, but a Joveo teammate — not Madhumita — answered it, so the fix applied earlier this session excludes them from her personal miss count:

| Call | Turn | Scenario | What the client said |
|---|---|---|---|
| rec3 | 135 | `multi_entity_budget_management` | "Typically, though, I can say that because the offices will have kind of individual contracts..." |
| rec5 | 45 | `conversion_mapping_complexity` | "To clarify on the general apply, I don't think that'll be something that we'll have Jovio do specifically for this pilot..." |
| rec5 | 76 | `dynamic_budgeting_and_capping` | "I don't think that they have a strategy for that, the current state..." |
| rec5 | 125 | `high_volume_recruitment_optimization` | "So because they are gonna have clients just like any other staffing agency that come in on a Friday..." |
| rec5 | 144 | `managed_service_vs_direct_access` | "I did get an answer on users managing budgets and things..." |
| rec6 | 66 | `high_volume_recruitment_optimization` | "Your office services, you get hundreds versus a welder, you get a few." |

---

## The 2 true misses — `Signal_Recognition_Failure`

Nobody responded to these before the client moved on. These are the only unambiguous personal gaps in this dataset:

| Call | Turn | Scenario | What the client said |
|---|---|---|---|
| rec5 | 129 | `managed_service_vs_direct_access` | "Let me get with the office and see who's doing the programmatic spend vendor management right now because I don't think..." |
| rec6 | 134 | `multi_entity_budget_management` | "The paid ones, like the Indeed's of the world, we have to have a corporate contract set up with Avionte from an integration standpoint..." |

---

## The bottom line — why this scenario, why that

Every record traces back to three independent, sequential facts about that moment in the call:

1. **Did the topic match something in Naren's Brain's known-scenario list?** (Gemma's Step 0 judgment)
2. **Who spoke next** — Madhumita herself, a teammate, or nobody? (computed from actual transcript roles, not asked of the LLM)
3. **If it was her, does a rubric exist** in Naren's Brain to grade it against?

Only 2 of Madhumita's 10 tracked signals cleared all three gates. That's why the "milestones missed" picture is so thin right now — it's not that she's failing constantly across every interaction; it's that most of her tracked moments never reach the grading stage at all, either because a teammate handled it or because no rubric exists yet for that topic.

**What would change this picture:** authoring rubrics for `multi_entity_budget_management`, `conversion_mapping_complexity`, `dynamic_budgeting_and_capping`, and `managed_service_vs_direct_access` (all recurring topics with zero or partial rubric coverage) would let far more of these already-detected signals actually get scored instead of being dropped after detection.
