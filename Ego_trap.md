# Ego Trap Pipeline — Implementation Plan
### Gap Analysis Engine · Full Technical Specification
**Version 1.0 · June 2026 · Engineering · Internal**

---

## 0. What We Are Building & Why

The **Ego Trap pipeline** is the gap analysis engine. It takes a CSM's call transcript, runs it against Naren's benchmark brain (Layers A, B, C), and produces a structured gap report for that CSM.

It is called "Ego Trap" as the product name — technically it is the gap analysis pipeline. Same thing, two names.

### Why we are building this now

**We are not building this to power a live app yet.**

We are building it to **create pre-launch user profiles** for every CSM on the team. The plan:

1. Run the Ego Trap pipeline over every existing CSM call recording
2. For each CSM, accumulate gap results into Layer D (LearnerProfile)
3. By the time the app launches, every CSM already has a populated gap profile — personalised course recommendations, simulator pre-loading, and learning priorities are ready on day one
4. No CSM opens the app to a blank slate

The recommendation engine (Step 5) and the app UI are downstream of this — they consume the profiles this pipeline produces. We spec Step 5 fully here so it is ready to build, but it is not built as part of this phase.

### What the pipeline does per call

```
TRANSCRIPT IN (Ego Trap Pipeline)
        │
        ▼
┌───────────────────┐
│  STEP 0           │
│  Signal           │──── MISS ──→ GAP: Signal_Recognition_Failure
│  Recognition      │              → Layer D updated
│  Check            │              → stop pipeline for this scenario
└────────┬──────────┘
         │ HIT
         ▼
┌───────────────────┐
│  STEP 1–2         │
│  Scenario ID      │
│  + Layer C rubric │
│  fetch            │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  STEP 3           │
│  Milestone        │
│  scoring          │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  STEP 4           │──→ Gap output (typed, timestamped, specific)
│  Gap output       │──→ Layer D LearnerProfile updated (cumulative)
│  + Layer D update │
└───────────────────┘
         │
         ▼ (DEFERRED — specced below, not built in this phase)
┌───────────────────┐
│  STEP 5           │──→ Tailored Courses reordered
│  Recommendation   │──→ Simulator Matchmaker pre-loaded
│  Engine           │──→ Re-evaluation scheduled
└───────────────────┘
```

### Scope of this document

- **Build now (v1):** Steps 0 → 4 + Layer D population
- **Specced, not built yet:** Step 5 (Recommendation Engine)
- **Not in scope:** App UI, course content generation, simulator logic

---

## 1. Input

**Format:** Clean call transcript with speaker name tags — same format as Naren's calls.

```
[00:00:12] Mary (CLIENT): We've been running programmatic through another agency and honestly the results weren't great.
[00:00:18] James (CLIENT): Yeah we spent a lot and saw very little return.
[00:00:25] Priya (CSM): I completely understand that — programmatic has a reputation problem for exactly that reason...
[00:00:41] Naren (JOVEO): What typically happens in those setups is the agency layers their margin on top...
```

**Speaker classification (same as Naren's brain pipeline):**
- `CLIENT` — all non-Joveo speakers regardless of how many people
- `CSM` — the Joveo CSM whose performance is being evaluated (the subject of the gap analysis)
- `OTHER_JOVEO` — any other Joveo speaker on the call (passed as context, not scored)

**Pre-launch batch mode:** Pipeline runs over all existing CSM call recordings. One script, one run per CSM, accumulates into Layer D. Not real-time.

---

## 2. Step 0 — Signal Recognition Check

### What it does

Before checking response quality, the pipeline checks whether the CSM even **noticed** a critical moment was happening. If the client said something that maps to a known scenario from Layer A and the CSM did not respond to it, that is a Signal_Recognition_Failure — more severe than responding poorly, because no amount of technique helps if you do not notice the signal.

**Two outcomes:**
- Signal noticed → proceed to Steps 1-2
- Signal missed → log Signal_Recognition_Failure, update Layer D, stop pipeline for this scenario

### V1 — Switchable approach (test both, pick winner)

V1 includes a **config switch** so both options can be tested against the same transcripts and compared before committing to one.

```python
STEP_0_MODE = "gemma"  # switch to "similarity" to test Option B
```

---

**Option A — Gemma 4 31B (Google AI Studio)**

Gemma reads the full transcript and determines:
1. Which client utterances map to known scenarios from Layer A
2. Whether the CSM acknowledged or responded to each one

Input to Gemma:
- Full transcript
- List of known scenario descriptions + keyphrases from Layer A

Output:
```json
{
  "signals_detected": [
    {
      "scenario_key": "competitive_objection:appcast",
      "client_utterance": "We've been running programmatic through another agency...",
      "timestamp": "00:00:12",
      "csm_responded": true,
      "csm_response_timestamp": "00:00:25"
    },
    {
      "scenario_key": "budget_concern",
      "client_utterance": "We spent a lot and saw very little return",
      "timestamp": "00:00:18",
      "csm_responded": false,
      "csm_response_timestamp": null
    }
  ]
}
```

Pros: Understands nuance, handles novel phrasings, consistent with rest of pipeline.
Cons: API cost per call, slower.

---

**Option B — BGE-M3 cosine similarity against Layer B trigger vectors**

Embed each client utterance with BGE-M3 and compare against stored trigger vectors in Layer B. If similarity crosses a confidence threshold, signal detected. Then check whether any CSM turn follows within a time window.

```python
SIMILARITY_THRESHOLD = 0.75   # tune during testing
RESPONSE_WINDOW_SECONDS = 120  # how long after signal to look for CSM response
```

Input: client utterance embeddings vs Layer B trigger vector index
Output: matched scenario_key + similarity score

Pros: Fast, cheap, no API cost, reuses existing Layer B infra.
Cons: Only matches signals semantically similar to Naren's calls — novel signal types get missed. Requires threshold tuning.

---

**How to decide between A and B after testing:**

Run both on the same 5-10 CSM transcripts. Compare:
- How many signals does each detect?
- Are there false positives (flagged as signal when it wasn't)?
- Are there false negatives (real signal missed)?

If Option B catches ≥90% of what Gemma catches with acceptable false positive rate → switch to B permanently for cost/speed. Otherwise keep A.

---

### V2 — Fine-tuned classifier

Once enough labelled signal examples exist (from v1 runs), train a lightweight classifier on BGE-M3 embeddings using Layer A scenario assignments as labels. Fast, deterministic, no API cost. Replaces both Options A and B as the primary detector.

> **See:** Section 6, Runtime Scenario Classifier (from Naren's Brain spec) — same model, reused here.

---

## 3. Steps 1–2 — Scenario Identification + Rubric Fetch

### Step 1 — Confirm scenario key

From Step 0 output, extract the `scenario_key` for each detected signal (e.g. `competitive_objection:appcast`).

### Step 2 — Fetch Layer C rubric

```sql
SELECT rubric_id, strategic_milestones, soft_skill_rubric, anti_patterns
FROM rubrics
WHERE scenario_key = $1
LIMIT 1;
```

Also extract the CSM's response text — all CSM turns from the signal timestamp until the next client utterance.

**If no rubric exists for a detected scenario:** log as `UNMAPPED_SCENARIO`, skip milestone scoring, flag for manual rubric creation. Do not fail the pipeline.

---

## 4. Step 3 — Milestone Scoring

### What it does

For each milestone in the Layer C rubric, score whether the CSM's response covered it. Each milestone is scored independently — a response can hit milestone 1 and 3 but miss milestone 2.

### V1 — Gemma 4 31B (Google AI Studio)

One LLM call per milestone. Gemma receives:
- The milestone description
- The detection hint (what distinguishes a hit from a near-miss)
- The CSM's full response text
- The Naren benchmark response from Layer B (as reference, not as the answer key)

**Prompt structure:**

```
You are evaluating whether a CSM's response satisfies a specific milestone.

MILESTONE: {milestone_description}
DETECTION HINT: {detection_hint}
NAREN'S BENCHMARK RESPONSE (for reference only): {benchmark_response}

CSM RESPONSE:
"{csm_response}"

Did the CSM's response satisfy this milestone?
Respond with a JSON object using exactly one of three verdicts:
{
  "verdict": "full_hit" | "partial_hit" | "miss",
  "confidence": "high"/"medium"/"low",
  "reason": "one sentence explanation",
  "quote": "verbatim excerpt this verdict is based on (empty string if verdict is full_hit)",
  "gap_to_ideal": "what a full_hit response would have included (empty string if verdict is full_hit)"
}
```

**Verdict tiers:** `full_hit` (milestone fully satisfied), `partial_hit` (attempted but incomplete/weak), `miss` (not addressed). These three tiers are the same boundaries the V2 NLI scorer below uses (`entailment_score >= 0.80` / `0.55-0.79` / `< 0.55`), so a `partial_hit` means the same thing regardless of which scorer produced it.

**Evidence gating:** `quote` and `gap_to_ideal` are only populated for `partial_hit`/`miss` — a `full_hit` never needs evidence, since nothing is surfaced to a coach for it.

**Soft skill rubric scoring** — separate Gemma call after milestone scoring:

```
SOFT SKILL: {skill_name}
EXCELLENT EXECUTION: {excellent_execution_description}
FAILING EXECUTION: {failing_execution_description}

CSM RESPONSE:
"{csm_response}"

How did the CSM execute on this soft skill?
{
  "rating": "excellent"/"adequate"/"failing",
  "confidence": "high"/"medium"/"low",
  "reason": "one sentence explanation"
}
```

---

### V2 — NLI model as primary, Gemma as fallback

**Primary scorer:** `cross-encoder/nli-deberta-v3-base` (self-hosted)

NLI (Natural Language Inference) checks: does the CSM response *entail* the milestone description? Purpose-built for exactly this task. Fast, self-hosted, no per-call API cost.

```python
from sentence_transformers import CrossEncoder

nli_model = CrossEncoder("cross-encoder/nli-deberta-v3-base")

def score_milestone_nli(csm_response: str, milestone_description: str) -> dict:
    # NLI labels: contradiction, neutral, entailment
    score = nli_model.predict([(csm_response, milestone_description)])
    entailment_score = score[0][2]  # entailment probability

    if entailment_score >= 0.80:
        return {"verdict": "full_hit", "confidence": "high", "method": "nli"}
    elif entailment_score >= 0.55:
        # Borderline — escalate to Gemma, which decides full_hit vs partial_hit vs miss
        return score_milestone_gemma(csm_response, milestone_description)
    else:
        # Confident miss — still needs evidence (quote + gap_to_ideal), so a
        # separate small Gemma call generates that even though NLI decided the tier.
        return score_milestone_evidence_only(csm_response, milestone_description, verdict="miss")
```

**Gemma fallback:** fires when NLI confidence is borderline (0.55-0.80) to decide the tier, and always for soft skill rubric scoring where tone and delivery judgment is needed — NLI cannot evaluate those reliably. A separate, narrower Gemma call (`score_milestone_evidence_only`) also fires whenever NLI confidently decides `miss` on its own, purely to generate `quote`/`gap_to_ideal` evidence — this scales with gap count, not call count, so it doesn't undermine V2's cost-reduction goal.

**V2 cost saving:** ~80% of milestone scores resolved by NLI locally. Gemma only called for ambiguous cases and soft skills.

---

## 5. Step 4 — Gap Output + Layer D Update

### Gap output structure

One gap record per missed milestone or failed soft skill:

```json
{
  "call_id": "CALL_CSM_PRIYA_2025_Q3_007",
  "csm_id": "CSM_PRIYA_001",
  "scenario_key": "competitive_objection:appcast",
  "rubric_id": "RUB_NRN_APPCAST_001",
  "timestamp": "00:00:12",
  "gaps": [
    {
      "gap_type": "Milestone_Omission",
      "milestone_id": "M3",
      "milestone_description": "Deliver security by introducing immediate structural auditing capabilities",
      "verdict": "miss",
      "confidence": "high",
      "reason": "CSM explained the product difference but never introduced a concrete auditing or transparency guardrail",
      "quote": "We're definitely more affordable than Appcast for this volume.",
      "gap_to_ideal": "Should have named a specific auditing or transparency capability, not just a cost comparison",
      "severity": "critical",
      "bloom_level": "Evaluate",
      "naren_example_chunk_id": "CHK_NRN_APPCAST_001"
    },
    {
      "gap_type": "Soft_Skill_Failure",
      "skill": "Confidence Under Pushback",
      "rating": "failing",
      "reason": "CSM became defensive and validated the client's negative premise without reframing",
      "severity": "high"
    }
  ],
  "milestones_hit": ["M1", "M2"],
  "milestones_partial_hit": [],
  "milestones_missed": ["M3"]
}
```

### Gap type taxonomy

| Gap Type | Definition | Bloom Level | Trigger |
|---|---|---|---|
| `Signal_Recognition_Failure` | CSM did not notice the trigger signal at all | Remember | Step 0 miss |
| `Milestone_Omission` | CSM responded but missed one or more strategic milestones | Apply / Evaluate | Step 3 miss |
| `Soft_Skill_Failure` | All milestones present but delivery was defensive, weak, or off-tone | Evaluate | Step 3 soft skill score = failing |
| `Knowledge_Gap` | CSM stated something factually incorrect about the product | Remember / Understand | Deferred — requires product knowledge base |

### Layer D update

After every call, upsert into milestone_performance and signal_recognition_gaps tables:

```sql
-- Milestone performance upsert
-- hits = full_hit count only; partial_hits tracks partial_hit count separately.
-- Weighted score computed at query time: (hits + 0.5 * partial_hits) / attempts.
INSERT INTO milestone_performance
  (csm_id, rubric_id, milestone_id, scenario_key, attempts, hits, partial_hits, last_attempted)
VALUES ($1, $2, $3, $4, 1, $5, $6, NOW())
ON CONFLICT (csm_id, rubric_id, milestone_id)
DO UPDATE SET
  attempts = milestone_performance.attempts + 1,
  hits = milestone_performance.hits + EXCLUDED.hits,
  partial_hits = milestone_performance.partial_hits + EXCLUDED.partial_hits,
  last_attempted = NOW();

-- Signal recognition upsert
INSERT INTO signal_recognition_gaps
  (csm_id, scenario_key, occurrences, recognized, missed)
VALUES ($1, $2, 1, $3, $4)
ON CONFLICT (csm_id, scenario_key)
DO UPDATE SET
  occurrences = signal_recognition_gaps.occurrences + 1,
  recognized = signal_recognition_gaps.recognized + EXCLUDED.recognized,
  missed = signal_recognition_gaps.missed + EXCLUDED.missed;
```

Gap severity thresholds:

| Miss rate | Severity |
|---|---|
| ≥ 60% | Critical |
| 35–59% | High |
| 15–34% | Moderate |
| < 15% | Low |

---

## 6. Step 5 — Recommendation Engine (Specced, Not Built Yet)

**Trigger:** fires after Layer D is updated. Reads the CSM's updated gap profile and reorders their learning experience accordingly.

### What it does

```python
def trigger_recommendation_engine(csm_id: str):
    # Fetch top critical/high gaps
    gaps = db.execute("""
        SELECT scenario_key, milestone_id, miss_rate, gap_severity
        FROM milestone_performance
        WHERE csm_id = $1
          AND attempts >= 3
          AND gap_severity IN ('critical', 'high')
        ORDER BY miss_rate DESC
        LIMIT 3;
    """, [csm_id])

    for gap in gaps:
        # 1. Push relevant module to top of learning playlist
        push_to_top_of_playlist(
            csm_id=csm_id,
            scenario_key=gap["scenario_key"],
            milestone_id=gap["milestone_id"],
            reason=f"Miss rate {gap['miss_rate']:.0%} — your most-missed moment"
        )

        # 2. Pre-load Simulator Matchmaker
        queue_simulator_scenario(
            csm_id=csm_id,
            scenario_key=gap["scenario_key"],
            difficulty="hostile",
            bloom_level=get_csm_bloom_level(csm_id)
        )

        # 3. Schedule re-evaluation
        schedule_rubric_recheck(
            csm_id=csm_id,
            rubric_id=gap["rubric_id"],
            milestone_id=gap["milestone_id"]
        )
```

### Bloom level progression

The recommendation engine uses the CSM's current Bloom level (stored in Layer D) to calibrate what gets assigned:

| Bloom Level | Track | What gets assigned |
|---|---|---|
| Remember | Newbie | Signal recognition drills, Layer B flashcards |
| Understand | Newbie | Scenario explanation modules, worked examples |
| Apply | Newbie → Veteran | Simulator with guided scaffolding |
| Analyse | Veteran | Simulator with hostile client, no hints |
| Evaluate | Veteran | Multi-scenario compound calls |
| Create | Veteran | CSM coaches another CSM (peer teaching) |

**Build trigger:** build Step 5 when app UI, course content system, and simulator are ready to consume its output. Layer D profiles will already be populated by then from the pre-launch batch run.

---

## 7. Pre-Launch Profile Building Plan

### Goal

Run the Ego Trap pipeline (Steps 0–4) over all existing CSM call recordings before the app launches. Every CSM has a populated Layer D profile on day one.

### Process

```
For each CSM:
  For each existing call recording:
    1. Transcribe (if not already clean text)
    2. Run Ego Trap pipeline (Steps 0–4)
    3. Accumulate gap results into Layer D
  End
  Compute gap severity ratings across all calls
  CSM profile is ready
End
```

### Output per CSM

After batch run, each CSM's Layer D profile contains:
- Hit/miss rates per milestone across all their calls
- Signal recognition rates per scenario
- Weakest milestone (highest miss rate with ≥3 attempts)
- Current Bloom level estimate
- Gap severity map — ready for recommendation engine to consume on launch day

---

## 8. Full Tech Stack

| Component | Tool | Notes |
|---|---|---|
| Transcript input | Clean text with speaker name tags | Same format as Naren's calls |
| Step 0 (v1) | Gemma 4 31B (Google AI Studio) + BGE-M3 similarity (switchable) | Config switch to test both |
| Step 0 (v2) | Fine-tuned classifier on BGE-M3 embeddings | Replaces both v1 options |
| Steps 1-2 | PostgreSQL lookup (Layer A + Layer C) | Standard SQL fetch |
| Step 3 (v1) | Gemma 4 31B (Google AI Studio) | Per-milestone + soft skill scoring |
| Step 3 (v2) | NLI deberta-v3-base (self-hosted) + Gemma fallback | NLI for milestones, Gemma for soft skills + borderline cases |
| Step 4 | PostgreSQL upsert (Layer D) | milestone_performance + signal_recognition_gaps tables |
| Step 5 | Specced — not built yet | Fires when app is ready |
| Execution (pre-launch) | Batch script — one run per CSM over existing recordings | Not real-time |
| Execution (post-launch) | Per-call trigger after each new recording | Real-time or near-real-time |

---

## 9. What to Build Now vs. Later

### Build now (v1)

| Component | Detail |
|---|---|
| Step 0 — signal detection | Both Option A (Gemma) and Option B (BGE-M3 similarity) with config switch |
| Steps 1-2 — rubric fetch | PostgreSQL lookup against Layer A + Layer C |
| Step 3 — milestone scoring | Gemma 4 31B via Google AI Studio |
| Step 4 — gap output + Layer D | Gap record generation + milestone_performance upsert |
| Pre-launch batch run | Run over all existing CSM recordings, populate Layer D profiles |

### Do not build yet — specced, build when ready

| Component | Trigger to build |
|---|---|
| Step 0 v2 — fine-tuned classifier | When enough labelled signal examples exist from v1 runs |
| Step 3 v2 — NLI model | When API cost becomes a concern at scale |
| Step 5 — recommendation engine | When app UI, course system, and simulator are ready |
| Real-time pipeline trigger | When app is live and processing new CSM calls |
| Knowledge Gap detection | When product knowledge base is built (deferred from Naren's brain spec) |

---

## 10. Explicitly Out of Scope (this document)

- **App UI / Ego Trap feedback screen** — consumes Step 4 output, not built here
- **Course content generation** — what goes into the modules Step 5 recommends
- **Simulator logic** — the actual roleplay engine Step 5 pre-loads
- **Knowledge Gap detection** — requires product knowledge base, deferred
- **Anti-pattern v2** — real contrastive failure examples from non-Naren calls
- **Naren's brain pipeline** — already specced separately; this pipeline depends on it being complete first

---

*Ego Trap Pipeline — Implementation Plan v1 · June 2026 · Engineering · Internal*