# Joveo CS Knowledge Platform — Combined Reference
**Version: HLD v2.0 + User Flow v4.0 + Feature Reference v5.0 · June 2026 · Internal — Customer Success**

> This document consolidates all three platform documents into a single reference: high-level design, feature descriptions, interaction flows, and technical architecture. Use this as the primary context file for any conversation about this platform.

---

## Table of Contents
1. [Overview & Problem Statement](#1-overview--problem-statement)
2. [Roles & Terminology](#2-roles--terminology)
3. [Platform Structure (Three Pages)](#3-platform-structure-three-pages)
4. [Feature Map (Kano Model)](#4-feature-map-kano-model)
5. [Page 1 — The Workspace](#5-page-1--the-workspace)
6. [Page 2 — The Library](#6-page-2--the-library)
7. [Page 3 — The Simulator](#7-page-3--the-simulator)
8. [Cross-Page Breadcrumbing Logic](#8-cross-page-breadcrumbing-logic)
9. [Bloom's Taxonomy Learning Framework](#9-blooms-taxonomy-learning-framework)
10. [Data Architecture](#10-data-architecture)
11. [What Is Intentionally Left Flexible](#11-what-is-intentionally-left-flexible)

---

## 1. Overview & Problem Statement

Joveo's Customer Success team carries significant institutional knowledge — locked in the heads of a few experts, scattered across call recordings, shared Google Drive docs, seminar recordings, and internal demos. This knowledge is inaccessible to the broader team. A new Customer Champion learns by osmosis: watching veterans, sitting in on calls, hoping the right person is free.

**This platform changes that.** It centralises all institutional knowledge into a structured repository and delivers it as a personalised, AI-powered learning and assessment system.

**Goal:** Make every Customer Champion as effective as the best Customer Champion, faster — regardless of seniority or geography.

---

## 2. Roles & Terminology

**Customer Champion** is the unified role title for every member of the CS department on this platform. Whether you are a week-old hire or a seven-year veteran, you are a Customer Champion — the name sets the standard, not a hierarchy.

For documentation purposes, two sub-profiles exist:

- **Newbie Customer Champion** — in their first 90 days; subject to the mandatory 3-month track before personalisation begins
- **Experienced Customer Champion (Veteran)** — post-track; fully personalised path, upper Bloom's levels unlocked

---

## 3. Platform Structure (Three Pages)

The platform has three pages. Each has a distinct intent and vibe:

| Page | Name | Intent | Vibe |
|------|------|--------|------|
| 1 | The Workspace | Help me do my job right now | Minimalist, operational — Google Search meets a flight deck |
| 2 | The Library | I have downtime and want to absorb something | Netflix on dark mode — visual, story-driven |
| 3 | The Simulator | I need to practice before I fail for real | High-stakes, instant-loading practice arena — psychologically safe |

---

## 4. Feature Map (Kano Model)

| Kano Tier | Section 1 — Personalised Learning | Section 2 — Tests & Simulations |
|-----------|-----------------------------------|----------------------------------|
| **Basic (Must Have)** | Tailored Courses + Performance Review Integration | MCQ + Written Response after each module |
| | Case Studies as Course Material | |
| | Failure Library | |
| | Chatbot with Full History | |
| | 3-Month Mandatory Newbie Track | |
| **Performance (More = Better)** | Ask Questions on Modules + Deep Research | Scenario Simulation (multi-difficulty) |
| | Ego Trap (Post-Meeting Analysis) | Blind Diagnosis Challenge |
| | | Post-mortem Reconstruction |
| | | QBR Builder & Defense |
| | | New Solution Dissemination |
| **Delighter (Excitement)** | Living Case Studies (existing + new accounts) | Simulation after each Case Study |
| | Contextual Knowledge Drops | Personalised Test Recommendations |

---

## 5. Page 1 — The Workspace

*Pain solved: Walking into a client meeting underprepared, or not knowing the answer mid-call.*

---

### 1.1 Knowledge Oracle `[All Customer Champions]`

**Purpose:** Mid-call answers in under 2 seconds — always on screen, no navigation needed.

A persistent search bar pinned to the top of every page. Taps the full knowledge base — transcripts, modules, case studies, failure stories, expert tips.

**Key interactions:**
- Type a natural language question; results appear in ~2 seconds, no Enter needed
- Short answer (2–3 sentences) inline below bar; process answers as numbered steps; stats shown large with source
- Source clips play inline; breadcrumb to Library for more
- If no result: one-click "Flag this gap" — auto-logged for expert to fill within 48 hours

---

### 1.2 Weekly Radar — Experienced Customer Champion

**Purpose:** Your meeting dashboard — shows prep status for every meeting this week, one click opens the full briefing.

Syncs with calendar. Nearest meeting gets a full hero card. Other meetings this week sit as collapsed cards below.

**Hero card contains:**
- Client name, meeting type, time until meeting
- 2-minute audio clip from a top rep (plays inline)
- AI-extracted account health tip
- Mission Briefing status card (waterfall progress)

**Scenarios:**

| Scenario | Output |
|----------|--------|
| Meeting this week, module unread | Hero card; complete module → card updates to "You're prepped" |
| Meeting this week, module already done | Confidence signal with score; breadcrumb to comparable case study |
| Multiple meetings | Nearest as hero; others as collapsed cards, each expandable |
| No meetings this week | Weekly Radar collapses; Ego Trap takes over as hero (see 1.4) |

---

### 1.3 Mission Briefing — New Account Flow `[All Customer Champions]`

**Purpose:** The full prep view — opens from Weekly Radar, not a separate destination.

Fires when a new CRM account is assigned; also accessed via "Open Briefing" on any Radar meeting card. Applies to all Customer Champions, including experienced ones on a new account type.

**Waterfall pipeline (locked in sequence):** Module → Case Study → Failure Story

**Contents:**
- Account name, industry tag
- 3 relevant call clips (play inline)
- 1 comparable case study
- 1 failure pattern label
- Sequential waterfall — each step unlocks only when the previous is complete

**Scenarios:**

| Scenario | Output |
|----------|--------|
| Experienced CC, new account, nothing done | Waterfall advances to Case Study after module completion |
| Experienced CC, module already done | Auto-advances to Case Study; breadcrumb to Simulator |
| Any CC, all three done | "You're prepared" state; recommended simulation card surfaces |

---

### 1.4 Ego Trap — Post-Meeting Performance Mirror `[All Customer Champions]`

**Purpose:** A post-meeting mirror that shows exactly what you applied from training — and what you didn't.

> **v4.0 redesign:** Previously fired only when calendar was clear. Now fires **every day**, regardless of workload. Always present as a hero card or persistent notification badge.

**How it works:**
- After a recorded meeting is processed by D2, the platform cross-references the transcript against every module, case study, and failure story the Customer Champion has consumed
- Applied moments: specific praise with timestamps (e.g., "At 14:32 you reframed from CPH to brand visibility — this is the exact technique from the FMCG Renewal Playbook")
- Missed moments: flagged with the exact learning that covers it + direct link to practice in Simulator (e.g., "At 22:18 Ankit said he'd been looking at alternatives. You treated it as a vendor comparison. The Failure Library has this exact pattern — Project Atlas, Month 4.")
- Missed moment patterns feed directly into the ModuleGenerationBatchJob — if a champion keeps missing the same signal, a new module targeting that gap is generated automatically

**Inputs:**
- Meeting recordings arrive via Avoma webhook → GCS → D2 processes (no manual upload required for automated flow)
- Manual upload available as fallback
- Cross-referenced against: all modules completed, case studies read, failure stories reviewed

**Scenarios:**

| Scenario | Behaviour |
|----------|-----------|
| Post-meeting (recording processed) | Full applied/missed analysis with timestamped clips |
| No meeting processed / no meeting today | Defaults to Failure Library mode — clip of top rep handling something difficult, framed as challenge |
| Meeting transcript uploaded manually | Same analysis output; breadcrumb to connect call recording tool for automation |

---

### 1.5 Test Recommendations — Experienced Customer Champion

**Purpose:** A personalised test queue that surfaces the right challenge at the right time — meeting-tied or skill-targeted.

Tests unlock in a waterfall: Tier 1 (3 tests) → Tier 2 (3 tests) → Tier 3 (advanced). Tests relevant to an upcoming meeting always float to the top regardless of tier.

Each card shows: test type, skill targeted, estimated time, difficulty, Bloom's level tag (Analyse / Evaluate / Create).

**Scenarios:**

| Scenario | Output |
|----------|--------|
| Upcoming meeting | Meeting-tied test card floats to top; on completion, next card unlocks |
| No upcoming meeting | Waterfall order; skip allowed — test stays in queue |

---

### 1.6 Weekly Radar — Newbie Customer Champion

Same calendar sync as experienced. Key differences during the 3-month mandatory track:
- Module shown is always from the mandatory sequence — not free-floating personalised content
- Module card labelled "Part of your foundational track"
- Mandatory track progress bar updates on completion

---

### 1.7 Newbie — 3-Month Mandatory Track & Account Onboarding

**Purpose:** A fixed, sequenced curriculum for all new Customer Champions — before personalisation begins.

The track is mandatory regardless of prior experience. Not optional, not self-directed, not skippable.

**Rationale:** Personalisation requires signal. A Customer Champion who has been on the platform for one week has no meaningful performance history. The track builds that baseline.

**Track structure (Bloom's Taxonomy):**

| Phase | Bloom's Level | Content |
|-------|---------------|---------|
| Month 1 — Remember | Remember | Joveo terminology, shortforms, product glossary, common CS practices, internal acronyms — micro-modules and flash card assessments |
| Months 1–2 — Understand | Understand | Why each practice exists, what signals mean, how account lifecycle stages work — case studies and annotated call clips |
| Months 2–3 — Apply | Apply | Live simulations tied to case studies — use concepts in controlled account scenarios before first real client interaction |

> **Note on modules during newbie track:** Modules in the mandatory track are pre-seeded from existing source material (initial Avoma recordings, docs). AI-generated personalised modules only activate post-track.

**Key mechanics:**
- Day 1: Cold open — entire page dominated by one real churned account case. "Aryan lost a Rs2Cr account in month 3. You have 10 minutes. Figure out why." No score — just the gap. Track unlocks after submission.
- Real accounts are assigned during the track; platform adapts prep material but mandatory sequence continues in parallel
- Where account module overlaps with mandatory track content, completion counts toward both ("double-credit")
- At Month 3 (or track completion): automatic transition to personalised mode based on accumulated performance data

**Transition trigger:** Automatic at month 3. Platform uses performance data from the mandatory track to determine where in the Veteran taxonomy the Customer Champion begins — it does not ask them to self-assess.

---

### 1.8 Test Recommendations — Newbie Customer Champion

During the 3-month track, test recommendations are fixed to the track curriculum — not free-floating personalised suggestions. Tests unlock in sequence alongside mandatory modules.

**Post-track:** Queue personalises based on track performance data, starting with the biggest identified gap. Bloom's level tag reflects current level (usually Analyse for Month 3+ CCs).

---

## 6. Page 2 — The Library

*Pain solved: Institutional knowledge lives in the heads of two or three veterans. When they leave, it's gone.*

---

### 2.1 Tailored Courses

**Purpose:** No catalogue — an AI-generated, champion-scoped learning path built around each individual's specific skill gaps.

> **v5.0 update:** Modules are no longer shared, human-authored content. Every module is generated by AI specifically for the champion receiving it, based on their personal gap profile, Bloom's level, assigned accounts, and Ego Trap history. No two champions see the same module.

**How module generation works:**

Each night, `ModuleGenerationBatchJob` runs as part of the D2 batch server:

1. Reads each champion's `PersonalisationProfile` — identifies top skill gap topic
2. Runs three checks before generating:
   - **Check 1 (duplicate):** Does an active, incomplete module on this topic already exist for this champion? If yes, skip — let them finish it first
   - **Check 2 (stagnant gap):** Has this champion already completed a module on this topic with a low assessment score? If yes, a `StagnantGapAlert` is written and generation is skipped — AI-generated content alone is not working; expert intervention is flagged
   - **Check 3 (similarity):** Would the generated module be too similar (cosine similarity > 0.85) to a module this champion already has? If yes, skip
3. If all checks pass: pulls the most relevant `KnowledgeChunk` rows from pgvector for that topic, filtered to the champion's context (their accounts, their Bloom's level, their Ego Trap missed moments)
4. Gemini generates the full module: sections, narrative, MCQs, written response prompt
5. Module is embedded and written to Cloud SQL as `status: active` — no human approval required
6. `LearningPathBatchJob` then reorders the champion's playlist, surfacing the new module at the top

**Rate limiting:** The batch job generates a maximum of N modules per run across all champions. Champions with the largest gaps are prioritised. This prevents the nightly cron becoming a Gemini marathon.

**Source material:** Modules are generated from `KnowledgeChunk` rows in pgvector — atomic knowledge units extracted from Avoma recordings, call transcripts, case study chapters, and any ingested documents. The quality of generated modules is directly proportional to the depth and breadth of ingested source material.

**Stagnant gaps:** When Check 2 fires, the expert admin sees this champion in `GET /admin/stagnant-gaps`. This means the champion has gone through AI-generated content on this topic and not improved — a signal for human intervention (coaching, different format, one-on-one).

**Post-track only:** AI-generated personalised modules apply to experienced Customer Champions. The 3-month newbie track uses pre-seeded modules from initial source material.

**Module navigation:** Click to open → scroll sections → click Next Section → sidebar index for jumping → inline MCQ → Mark Complete

---

### 2.2 Living Case Studies

**Purpose:** Ongoing accounts told in chapters — follow a real account as it unfolds, in real time.

> **v4.0 update:** Now covers **all ongoing accounts**, not just newly assigned ones. Any account — whether active for two months or two years — can be set up as a Living Case Study. Existing accounts are retroactively structured with past chapters written from historical recordings and notes.

**How it works:**
- Chapters added at each significant milestone: onboarding completion, first QBR, difficult period, renewal, executive escalation
- Chapters unlock in sequence — must be read in order (one card at a time, continuous scroll)
- Customer Champions can follow accounts they are not managing directly — learning from colleagues' live decisions in real time
- New chapters push in-app notifications
- Social proof: "Three Customer Champions on your team are following this account →"

**Types:**

| Type | Setup |
|------|-------|
| New accounts | Set up as Living Case Study from day one — chapters added in real time |
| Existing ongoing accounts | Retroactively structured — past chapters from historical data, new chapters going forward |

**Chapter format:** Narrative arc with embedded call clips, health metric snapshots, decision annotations from the expert managing the account.

---

### 2.3 The Failure Library

**Purpose:** Raw, unfiltered post-mortems of churned accounts — because losses are more instructive than wins.

Most knowledge bases capture only wins. The Failure Library captures the losses: the QBR that went sideways, the pitch that bombed, the account that churned despite best efforts.

**Format:** One continuous-scroll page per post-mortem.
- Cover: account pseudonym, industry, churn month, root cause tag
- Inline call clips play at flagged moments
- Inline health metric charts — hover for data points
- Expert's view of what went wrong reveals **only at the bottom** — forcing you to form your own read first

**Entry points:**
- Directed from Page 1 breadcrumb
- Directed from Ego Trap (v4.0: Ego Trap now links directly to specific Failure Library stories after post-meeting analysis)
- Free browsing — grid of post-mortem cards, "Similar to your accounts" tag on most relevant

---

## 7. Page 3 — The Simulator

*Pain solved: The only way to get better at hard client conversations is to have them.*

**Bloom's note:** Simulator activities map to Analyse, Evaluate, and Create — the upper levels reserved for post-track Customer Champions (and selectively for newbies in the Apply phase).

---

### 3.1 The Matchmaker Engine

**Purpose:** One AI-recommended scenario surfaces — contextual, explained, instantly loadable.

Customer Champions never scroll a list. The engine reads upcoming meetings, recent Ego Trap gaps, and test history to surface a single recommended scenario with a one-line rationale.

**Entry points:**

| Entry | Pre-load |
|-------|----------|
| Upcoming meeting (from Page 1) | Scenario matched to meeting account type |
| Directed from Ego Trap | Scenario pre-loaded with missed moment as learning objective |
| Directed from Library breadcrumb | Exact scenario from the case study just read |

Clicking Start loads immediately — no setup screen.

---

### 3.2 Live Scenario Simulation & Pitching

**Purpose:** AI-powered roleplay against specific characters — hostile CFO, churning staffing head, mid-escalation exec.

**Bloom's level:** Evaluate (Apply for Newbies in Phase 3)

**Interface:** Chat-style. AI plays a named character and opens with a message.

**Input modes:**
- **Type mode:** Text input at bottom; Enter/Send to submit; AI responds immediately
- **Voice mode:** Mic icon lit, "Listening..." shown; pause 1.5 seconds to signal end of turn; platform transcribes in real time; voice mode adds tone and pacing as additional feedback dimension
- Toggle between modes at any point mid-conversation

**Difficulty dimensions:** Client personality (cooperative → hostile), problem complexity (clear-cut → multi-stakeholder), time pressure (relaxed → urgent escalation), information available (full context → deliberately incomplete)

**Scoring screen (on "End session"):**
- Overall score
- 3 specific moments flagged (good and bad)
- What the top rep would have said at each moment

---

### 3.3 Blind Diagnosis Challenge

**Purpose:** Real anonymised account health data, no context, 15 minutes — what's your diagnosis?

**Bloom's level:** Analyse

**What you see:** Apply rate trend, cost per applicant chart, client engagement score over time. No account name, no industry, no backstory.

**Interaction:** Scroll/hover data points → type or speak diagnosis and action plan → Submit (final, no editing after).

**Output:** Your answer left, expert response right. Gap analysis: what you caught, what you missed, what the expert saw. Breadcrumb to full post-mortem in Failure Library.

**Difficulty variants:**
- Junior CC: clear signals
- Senior CC: noisy, conflicting data — no obvious answer; expert response includes explicit reasoning

---

### 3.4 Post-mortem Reconstruction

**Purpose:** Everything from a real churned account — figure out where it went wrong and when it could have been saved.

**Bloom's level:** Analyse

**Interface:** File browser (left panel) + two text fields. File browser contains: call recordings, health snapshots, QBR notes, email thread.

**Two questions:**
1. Where did this go wrong?
2. When could it have been saved?

Type or speak into each field. Submit reveals: timeline of what actually happened (annotated with save moments) alongside your reconstruction for comparison.

---

### 3.5 QBR Builder & Defense

**Purpose:** Build the deck, then defend it live to a three-person AI panel.

**Bloom's levels:** Phase 1 = Create · Phase 2 = Evaluate

**Phase 1 — Deck Upload:**
- Upload QBR deck built for a dummy account brief (PDF, PPTX, or Google Slides link)
- Processing: 15–20 seconds (D1 calls Gemini directly with `gs://` URI or Slides URL — no D2 involvement)
- Brief AI feedback on narrative and weak sections (e.g., "Your narrative is strong. Your ROI section is thin — expect pushback.")

**Phase 2 — Live Defense:**
- Deck on left (scrollable for reference), AI panel chat on right
- Three simultaneous AI personas send questions as chat bubbles:
  - **Ananya** — skeptical CXO
  - **Rohan** — curious Director
  - **Meera** — passive-aggressive middle manager
- Type or voice to respond; all three personas react to each answer
- Scored on both deck quality (Phase 1) and live defense (Phase 2)

---

### 3.6 MCQ + Written Response (Post-Module Assessment)

**Purpose:** Every module triggers an assessment — situation-based questions, then a short written application.

Launches automatically after "Mark complete." Knowledge without application is useless.

**Bloom's levels:** Remember/Understand for newbie track modules · Apply and above for experienced CCs

**Format:**
- One MCQ at a time; all four options are genuine close calls — no definition questions
- Immediate feedback after each: right/wrong + one-line explanation
- Cannot go back after advancing
- After final MCQ: written response screen — apply what you learned to a real account scenario (50-word minimum)
- AI grades written response against expert rubric; specific feedback given
- Module fully complete only after both parts are done

**Assessment score significance:** Score is written to `AssessmentResult` and feeds into `PersonalisationProfile`. A low score on a completed module keeps the topic flagged as a weak area, which drives both future module generation and potential `StagnantGapAlert` if the pattern persists.

---

## 8. Cross-Page Breadcrumbing Logic

The platform never tells the Customer Champion where to go. Each page creates a natural pull toward the next. Every breadcrumb is a one-line tease with a right-arrow link — one click, you're there.

| Flow | Trigger | Mechanic |
|------|---------|----------|
| **Workspace → Library** | Curiosity | Clip ends. "Sarah has 3 more calls in the Library. Her renewal rate on this type is 94% →". Library opens directly to the relevant item — no homepage, no search. |
| **Library → Simulator** | Ego | After reading how someone else handled something: "Think you could have saved this account? Here's the Simulator scenario →". Simulator pre-loaded with that exact scenario. |
| **Ego Trap → Simulator** *(new v4.0)* | Missed moment | "You missed the executive disengagement signal at 22:18. Practice handling this in the Simulator →". Scenario starts with a character showing early disengagement signals. |
| **Simulator → Workspace** | Readiness | Simulation feedback screen has one CTA: "Back to Workspace". Meeting prep card updates to reflect the practice completed. |
| **Test Waterfall** | Completion | Every test completed on Page 1 updates the learning path on Page 2 and may surface a pre-loaded Simulator scenario on Page 3. All three pages stay in sync automatically. |
| **Free Time Loop** | Curiosity / ego / boredom / Ego Trap | Living Case Studies push notifications on new chapters. Failure Library surfaces "Similar to your accounts" cards. Blind Diagnosis is framed as a puzzle. Ego Trap fires every day regardless. None require setup. |

---

## 9. Bloom's Taxonomy Learning Framework

The platform explicitly maps its curriculum to Bloom's Taxonomy. This determines what content is served at what stage, what assessment format is used, and when a Customer Champion is ready to move to the next tier.

| Cognitive Level | Newbie Track (Months 1–3) | Veteran Path (Post-Track) |
|-----------------|---------------------------|---------------------------|
| **Remember** | Joveo terminology, shortforms, product glossary, internal acronyms, common CS practices — mandatory micro-modules and flash assessments | Revision surfaced contextually via Ego Trap and Knowledge Oracle (not primary focus) |
| **Understand** | Why each practice exists, what health signals mean, how account lifecycle stages differ — case studies and annotated call clips | Deep research questions and post-mortem analysis extend understanding into nuanced, ambiguous situations |
| **Apply** | Live simulations tied to case studies — use concepts in controlled account scenarios before first real client interaction | Surfaces for new product launches (New Solution Dissemination) and new client types |
| **Analyse** | Not in Newbie Track (requires sufficient base knowledge) | Blind Diagnosis Challenge and Post-mortem Reconstruction — read signals, form hypotheses, identify root cause in real anonymised data |
| **Evaluate** | Not in Newbie Track | QBR Defense — defend decisions under pressure from multi-stakeholder AI panel; Scenario Simulation at senior difficulty where there is no clean right answer |
| **Create** | Not in Newbie Track | QBR Builder Phase 1 — construct a complete business review from scratch; New Solution Dissemination pitch — design and deliver a structured pitch with no template |

The transition from Newbie Track to Veteran Path is **automatic at three months**. The platform uses performance data from the mandatory track to determine where in the Veteran taxonomy the Customer Champion begins — it does not ask them to self-assess.

---

## 10. Data Architecture

The platform handles four fundamentally different types of data. The architecture is designed around this from the start rather than treating all content as the same.

### 10.1 Three-Layer Content Model

Content flows through three layers, each serving a distinct purpose.

| Layer | What it is | Used for |
|-------|-----------|----------|
| **Rich Content Layer** | Original source material preserved at full fidelity. Avoma recordings keep transcripts, speaker tags, and moment markers. Case studies keep chapters and narrative arc. Documents keep hierarchy and structure. Stored in GCS (files) + Cloud SQL (metadata). **This is what the Customer Champion sees.** | Knowledge Oracle clips, Ego Trap playback, case study chapters, Failure Library |
| **Atomic Knowledge Chunk Layer** | AI-extracted insights distilled from rich content. Format stripped — only knowledge remains. Each chunk tagged by topic, type (insight / failure pattern / best practice / objection handle), Bloom's level, difficulty, and champion specialisation. Embedded as vectors in pgvector. **This is what powers search, chatbot, Ego Trap cross-reference, and module generation.** | Knowledge Oracle, Chatbot, Ego Trap analysis, ModuleGenerationService |
| **Generated Module Layer** | Champion-scoped learning modules produced by AI from knowledge chunks. Each module is unique to the champion receiving it — generated from chunks most relevant to their specific gap, Bloom's level, and account context. Stored in Cloud SQL with champion_id. **This is the personalised learning surface.** | Tailored Courses, Mission Briefing, Test Recommendations |

---

### 10.2 Database Strategy

| Data Type | What it Stores | Tech |
|-----------|---------------|------|
| Structured + Vector | Champion profiles, modules (with embeddings), knowledge chunks (pgvector), test results, scores, progress, EgoTrapEntries, StagnantGapAlerts, CalendarEvents, AccountBriefs | Cloud SQL (Postgres + pgvector extension) |
| Files | Call recordings, transcripts, case study content, module source files | GCS Bucket |
| Conversation | Chatbot session history per Customer Champion | Firestore |
| LLM / Embeddings | Module generation, Ego Trap cross-reference, MCQ grading, Knowledge Oracle synthesis, voice transcription | Gemini API via Vertex AI (google-generativeai SDK) |

> **v5.0 update:** Pinecone/Weaviate removed. pgvector on Cloud SQL handles all vector storage. MongoDB/DynamoDB removed. Firestore handles chatbot history. Single Postgres instance reduces operational complexity.

---

### 10.3 Core Entities

| Entity | Purpose | Key Fields |
|--------|---------|------------|
| CustomerChampion | Central identity — everything else connects to this | id, seniority, region, specialisation, assigned_accounts[], newbie_track_status, bloom_current_level |
| Account | Real or dummy accounts used in tests and personalisation | id, type (real/dummy), industry, health_status, assigned_csm_id, is_living_case_study |
| RawContent | Source material preserved at full fidelity | id, content_type, source, topic_tags[], moment_markers[], bloom_level_tag, status (indexed/pending) |
| KnowledgeChunk | Atomic unit extracted from raw content for retrieval | id, source_content_id, chunk_type, body, tags[], difficulty, bloom_level, embedding (vector) |
| **Module** *(v5.0 — champion-scoped, AI-generated)* | Personalised learning unit generated per champion | id, **champion_id** (FK), topic, bloom_level, **embedding** (vector), **attempt_count**, **source_chunk_ids[]**, generated_content, mcqs[], written_prompt, status (active/completed/deleted), created_at |
| **StagnantGapAlert** *(new v5.0)* | Flags champions who completed a module on a topic but did not improve — requires expert intervention | id, champion_id, topic, module_ids[], assessment_scores[], detected_at, resolved (bool) |
| EgoTrapEntry | Post-meeting analysis record produced by D2 | id, champion_id, meeting_id, recording_gcs_uri, moments_applied[], moments_missed[], suggestions[], status (pending/done) |
| CalendarEvent | Meetings synced from Google Calendar | id, champion_id, account_id, meeting_time, event_type |
| AccountBrief | Waterfall completion state per champion per account | id, champion_id, account_id, module_done, case_study_done, failure_done |
| PersonalisationProfile | Computed nightly — drives all recommendations and module generation | id, champion_id, skill_levels{topic: score}, weak_areas[], bloom_current_level, updated_at |
| NewbieTrackProgress | Tracks mandatory 3-month curriculum | id, champion_id, started_at, mandatory_modules_done, mandatory_tests_done, transition_ready, personalised_mode_activated_at |
| AssessmentResult | Outcome of every module and test | id, champion_id, module_id, score, qualitative_feedback, completed_at |
| SimSession / SimTurn | Simulator roleplay session and turn log | session: id, champion_id, scenario_id, score; turn: id, session_id, speaker, content |
| QBRSession | QBR deck upload + defense session | id, champion_id, deck_gcs_uri, deck_feedback, defense_score, status |

---

### 10.4 Module Generation Pipeline (end-to-end)

```
Source data (Avoma recordings, docs, transcripts)
    ↓  [GCS storage + content_ingestion_q]
ContentIngestionService (D2)
    → chunk + embed → KnowledgeChunk rows in pgvector
    ↓  [nightly cron]
PersonalisationBatchJob
    → aggregate scores + EgoTrap gaps → PersonalisationProfile
    ↓
ModuleGenerationBatchJob  (per champion, rate-limited)
    CHECK 1: active incomplete module on this topic? → skip
    CHECK 2: completed module + low score?          → StagnantGapAlert → skip
    CHECK 3: cosine similarity > 0.85?              → too similar → skip
    PASS   : publish { champion_id, topic, bloom_level } to module_generation_q
    ↓  [module_generation_q consumer]
ModuleGenerationService (D2)
    → pgvector semantic search: top-K chunks for topic + champion context
    → Gemini: generate module (sections, narrative, MCQs, written_prompt)
    → embed module content
    → write Module { champion_id, embedding, content, mcqs[], status: active }
    ↓
LearningPathBatchJob
    → order champion's active modules by gap score + Bloom's fit
    → champion sees new module at top of their path
```

---

### 10.5 Assessments Tied to Content

Every piece of learning content has an assessment attached. The format matches the nature of the content.

| Content | Assessment Method | Outcome |
|---------|-------------------|---------|
| Module (AI-generated) | MCQ (one at a time, immediate feedback) + Written Response | Score written to AssessmentResult → feeds PersonalisationProfile → drives next module generation |
| Case Study | Live Simulation | Scenario matched to champion's client portfolio and difficulty level |

---

## 11. What Is Intentionally Left Flexible

- **Performance review integration** is optional at launch — PersonalisationProfile can ingest performance data when connected
- **Real account data** depends on CRM availability — dummy accounts provide full coverage at launch
- **Avoma integration** is the primary unlock for module generation quality — more recordings = richer knowledge chunks = better modules. Manual transcript upload is available as fallback.
- **Module generation rate limit (N per run)** is configurable — tune based on Gemini API quota and champion count
- **Stagnant gap threshold** (score below which a StagnantGapAlert fires) is configurable — default suggested at 60%
- **Cosine similarity threshold** for deduplication is configurable — default 0.85
- **3-month Newbie Track threshold** is configurable — default 90 days, adjustable per team or region

---

*Joveo CS Knowledge Platform · Combined Reference · HLD v2.0 + User Flow v4.0 + Feature Reference v5.0 · June 2026 · Internal — Customer Success*
