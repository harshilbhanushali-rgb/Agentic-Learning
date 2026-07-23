# Ego Trap — Gemma-Mode Signal Detection: Approach & Run Analysis

**Date:** 2026-07-07
**Run ID:** `c85b92080d71`
**Transcripts scored:** `rec3.txt`, `rec5.txt`, `rec6.txt` (CSM: Madhumita Katta)

---

## 1. Why we switched to Gemma mode

Ego Trap's Step 0 ("did the client raise a known topic?") can run two ways:

- **Similarity mode** — embed the client's sentence, do a nearest-neighbor lookup against real example sentences stored in Pinecone, fire a match if the similarity score clears a threshold (`EGO_TRAP_SIMILARITY_THRESHOLD`, was `0.35`).
- **Gemma mode** — hand the whole transcript to the Gemma LLM along with the list of known scenarios, and ask it directly: "does anything in here match one of these topics?"

We had already found (see `RUN_NOTES.md`, Run 1b) that similarity mode at threshold 0.35 was matching pure small talk — e.g. the client saying *"I'm good. Thank you."* — to real business scenarios, because with only 3 real transcripts on file, the library of stored example sentences is too sparse for a nearest-neighbor lookup to be reliable. Whatever example happens to be geometrically "closest" wins, even if it's not actually relevant.

**The reasoning for switching:** similarity mode needs a *dense* library of real examples to be accurate, and we don't have one yet. Gemma mode doesn't have that problem — it judges relevance from the scenario's written description (topic name + keyphrases), not from nearest-neighbor distance to a handful of stored examples. It should be more accurate right now, at the cost of being slower and more expensive (a full LLM call per transcript instead of a cheap vector lookup).

---

## 2. How Gemma mode actually works, step by step

Ego Trap always runs the same 5 stages per transcript; only **Stage 0** (signal detection) differs by mode.

### Step 0 — Signal detection
One Gemma call, given the **entire transcript** plus the list of **known scenarios** (scenario key + topic + keyphrases — this list comes from Naren's Brain, see Section 3). Gemma is asked to return every client sentence that matches one of those known topics, copied out word-for-word.

Each returned sentence is then matched back to its exact turn in the transcript (`_find_turn_index`), so we know *where* in the call it happened. If Gemma's returned text doesn't match anything in the transcript closely enough, that signal is silently dropped (this happened twice in last night's run — see Section 6).

### Response outcome check (applies to both modes, fixed this session)
For each signal found, the code looks at who spoke next in the transcript before the client spoke again, and classifies it as:
- **`csm`** — the CSM personally responded
- **`other_joveo`** — a teammate answered instead of the CSM
- **`none`** — nobody responded

This is worked out from the actual transcript roles in code — Gemma is **not** asked to judge this anymore (that used to be the source of the "teammate answers get blamed on the CSM" bug we fixed earlier this session).

### Stage 2 — Rubric lookup
For every signal where the CSM personally responded, look up whether that scenario has a scored rubric in Naren's Brain. If it doesn't (`UNMAPPED_SCENARIO`), that signal is dropped — Gemma correctly recognized a real topic, but there's nothing to grade it against yet.

### Stage 3 — Pull comparison text
For each remaining signal, pull two things: the CSM's actual response text from the transcript, and Naren's own past response(s) to that same scenario (from Naren's Brain) as a reference example.

### Stage 4 — Score with Gemma
Batch-score the CSM's response against the rubric's milestones and soft-skill criteria (multiple signals per Gemma call, to save on API calls).

### Stage 5 — Write results
Every signal becomes one row in the database, tagged as one of:
- **Milestone-scored** (CSM responded + rubric existed) — records which milestones were hit/missed
- **`Deferred_To_Teammate`** (a teammate answered) — logged, but not counted as a CSM failure
- **`Signal_Recognition_Failure`** (nobody responded) — a genuine miss

---

## 3. What comes from Naren's Brain vs. what Gemma judges fresh

| Data used | Comes from | Naren's Brain table | Role in the pipeline |
|---|---|---|---|
| List of known scenario topics | Naren's own calls, identified earlier by Layer A | `scenarios` | Given to Gemma as the menu of "things to look for" in Step 0 |
| Milestones + soft-skill rubric | Authored earlier from patterns across Naren's real responses (Layer C) | `rubrics` | The actual grading criteria used in Stage 4 |
| Naren's real response text | Naren's real calls | `kb_pairs` | Shown to Gemma as a reference example only — it is **not** itself graded, just context for "here's roughly what a good answer looks like" |
| The CSM's response text | The real CSM call transcript being analyzed | n/a (not Naren's data) | What actually gets graded |

In plain terms: **Naren's Brain supplies the questions and the answer key; the CSM transcript supplies the answer being graded.** Gemma is only judging fresh, in real time, whether a given client sentence matches a known topic (Step 0) and whether the CSM's specific wording clears the rubric bar (Stage 4).

---

## 4. A bug we hit and fixed along the way

The first gemma-mode run crashed on the very first transcript with a Gemma API timeout. The retry code in `shared/gemma.py` was supposed to retry on timeouts, but it checked for the substring `"timeout"` in the error message — and the actual error text was `"The read operation timed out"`, which doesn't contain that substring (it's "timed out", not "timeout"). So the retry never fired and the whole run died on one slow response. Fixed by adding `"timed out"` to the list of retryable error phrases. Confirmed working on the re-run — the retry fired and recovered cleanly on `rec6.txt`.

---

## 5. Last night's run — exact output

```
=== Ego Trap Batch Runner ===

Found 4 transcript(s) in csm_recordings/:
  - rec3.txt
  - rec5.txt
  - rec6.txt
  - sample_call_priya_001.txt

[Ego Trap] Processing rec3.txt (CSM: Madhumita Katta)...
[Step 0] Calling Gemma for signal recognition check...
  Detected 5 signal(s).
  [Stage 1/5] Response check: 4 responded by CSM, 1 deferred to teammate, 0 not responded.
  ~ Deferred_To_Teammate: multi_entity_budget_management @ turn 135
  ? UNMAPPED_SCENARIO: no rubric for 'multi_entity_budget_management' — skipping scoring.
  ? UNMAPPED_SCENARIO: no rubric for 'multi_entity_budget_management' — skipping scoring.
  [Stage 2/5] Rubric lookup: 2/4 responded signal(s) have a rubric.
  [Stage 4/5] Scoring 2 signal(s) with Gemma in 1 batch(es) of up to 4...
  v Gap record written: 4 milestone(s) missed.
  v Gap record written: 4 milestone(s) missed.
  [Stage 5/5] 2/2 gap record(s) written.

[Ego Trap] Processing rec5.txt (CSM: Madhumita Katta)...
[Step 0] Calling Gemma for signal recognition check...
  Detected 6 signal(s).
  [Stage 1/5] Response check: 1 responded by CSM, 4 deferred to teammate, 1 not responded.
  ~ Deferred_To_Teammate: conversion_mapping_complexity @ turn 45
  ~ Deferred_To_Teammate: dynamic_budgeting_and_capping @ turn 76
  ~ Deferred_To_Teammate: high_volume_recruitment_optimization @ turn 125
  ~ Deferred_To_Teammate: managed_service_vs_direct_access @ turn 144
  x Signal_Recognition_Failure: managed_service_vs_direct_access @ turn 129
  ? UNMAPPED_SCENARIO: no rubric for 'ats_integration_friction' — skipping scoring.
  [Stage 2/5] Rubric lookup: 0/1 responded signal(s) have a rubric.
  [Stage 5/5] 0/0 gap record(s) written.

[Ego Trap] Processing rec6.txt (CSM: Madhumita Katta)...
[Step 0] Calling Gemma for signal recognition check...
[gemma] Transient error (attempt 1). Waiting 2s...
  ! Could not locate client_utterance in transcript, skipping: "But, there's also a general apply piece. So if they get to our microsite and the"
  ! Could not locate client_utterance in transcript, skipping: "A general apply is not tied to a job at all. There's no job posting. It is just "
  Detected 2 signal(s).
  [Stage 1/5] Response check: 0 responded by CSM, 1 deferred to teammate, 1 not responded.
  ~ Deferred_To_Teammate: high_volume_recruitment_optimization @ turn 66
  x Signal_Recognition_Failure: multi_entity_budget_management @ turn 134
  [Stage 5/5] 0/0 gap record(s) written.

[Ego Trap] sample_call_priya_001 has no CSM mapping — skipping.

Ego Trap batch complete.
```

---

## 6. Analysis — what this run actually tells us, in plain words

### The headline number: 61 → 13

Similarity mode (previous run, same 3 transcripts, no code changes in between) found **61** "signals." Gemma mode found **13**. That's a massive drop, and it's the expected, good outcome — it confirms our theory that similarity mode's threshold was overcounting.

**How we know the 13 are more trustworthy, not just fewer:** we pulled the actual client sentence behind every signal gemma mode kept and read them by hand. Every one of them is a real, substantive business statement — talk about contracts, budgets, vendor management, application volume, apply-flow mechanics. None of them are small talk. That's a direct contrast to similarity mode, where we caught it matching *"I'm good. Thank you."* to a real scenario. Concretely:

| Call | Turn | Scenario | What the client actually said |
|---|---|---|---|
| rec3 | 135 | multi_entity_budget_management | "Typically, though, I can say that because the offices will have kind of individual contracts..." |
| rec5 | 45 | conversion_mapping_complexity | "To clarify on the general apply, I don't think that'll be something that we'll have Jovio do..." |
| rec5 | 76 | dynamic_budgeting_and_capping | "I don't think that they have a strategy for that, the current state..." |
| rec5 | 125 | high_volume_recruitment_optimization | "So because they are gonna have clients just like any other staffing agency that come in on a Friday..." |
| rec5 | 129 | managed_service_vs_direct_access | "Let me get with the office and see who's doing the programmatic spend vendor management..." |
| rec5 | 144 | managed_service_vs_direct_access | "I did get an answer on users managing budgets and things..." |
| rec6 | 66 | high_volume_recruitment_optimization | "Your office services, you get hundreds versus a welder, you get a few." |
| rec6 | 134 | multi_entity_budget_management | "The paid ones, like the Indeed's of the world, we have to have a corporate contract set up with Avionte..." |
| rec3 | 69, 93 | high_volume_recruitment_optimization | (2 more, scored against milestones — see below) |

All genuinely on-topic. Zero small-talk false positives found in this sample — a real, visible quality improvement over similarity mode.

### Where signals still get lost, and why

Of the 13 signals Gemma detected, only **10** made it into the database:

- **2 were dropped** because Gemma's returned sentence didn't match the transcript closely enough for the code to find it (`_find_turn_index` requires a close-to-exact quote). This is a real, known limitation — Gemma sometimes paraphrases slightly instead of quoting verbatim, and the current matching logic isn't forgiving of that.
- **3 more never became gap records** even though they were correctly detected, because Naren's Brain has **no rubric authored yet** for those scenario keys (`multi_entity_budget_management` ×2, `ats_integration_friction` ×1). Gemma did its job correctly here — it found a real topic; there's just nothing to grade it against yet. This matches a gap already known from earlier runs.

Neither of these is a Gemma accuracy problem — one is a text-matching brittleness issue, the other is a content-coverage gap in the rubric library.

### Milestone scoring: still 0%, but now on far too little data to mean anything

Only 2 signals this run were both CSM-responded *and* had a rubric to score against (both `high_volume_recruitment_optimization`, at turns 69 and 93 in rec3). Both came back 0/4 milestones hit. That continues the 0% pattern we've seen all along — but with only 2 data points, this run genuinely can't tell us whether that's real or not. Gemma mode's much stricter signal detection means far fewer signals reach the scoring stage at all (2 this run vs. 22 under the old similarity-mode run), so this specific question needs more transcripts before it can be answered either way.

### Bottom line

- Gemma-mode's topic-matching looks meaningfully more accurate than similarity mode on this data, based on manual read-through of every signal it kept.
- The 3-signal "no rubric" drop and 2-signal "couldn't match verbatim" drop are both fixable follow-ups, not fundamental flaws.
- We don't yet have enough scored signals to say anything new about actual milestone/soft-skill performance — that needs either more transcripts or authoring the missing rubrics so today's already-detected signals stop going to waste.

---

## 7. Recommended next steps

1. **Author rubrics** for `multi_entity_budget_management` and `ats_integration_friction` (and `dynamic_budgeting_and_capping`, previously flagged) — these keep getting detected as real client topics across multiple calls but have no scoring criteria, so real signal is being thrown away.
2. **Loosen the verbatim-match step** (`_find_turn_index` in `signal_check.py`) to tolerate minor paraphrasing from Gemma, so fewer real signals get silently dropped.
3. **Feed more real transcripts through gemma mode** before drawing any conclusion about milestone/soft-skill hit rates — 2 data points isn't enough either way.
4. Once more real CSM calls accumulate, revisit similarity mode — it should become viable again once the trigger library is dense enough for nearest-neighbor matching to be meaningful.
