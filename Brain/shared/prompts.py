PROMPT_LAYER_A_V1 = """\
You are an expert sales coach analyzing customer success call transcripts for Joveo.

**About Joveo:**
Joveo is an AI-powered recruitment marketing platform that helps employers and staffing firms attract and hire qualified candidates efficiently. While rooted in programmatic job advertising — distributing job listings across thousands of publisher sources with AI-driven budget optimization — Joveo has expanded into a full suite of AI products:
- **Programmatic Job Advertising** — precision spend across publishers, continuously optimized for cost-per-apply and cost-per-hire
- **AI Career Site Builder** — generates high-converting career sites and landing pages from simple prompts, with ATS/CRM integration and a conversational apply flow
- **Jo (AI Recruitment Agent)** — conversational AI that screens candidates, schedules interviews 24/7, fine-tunes ad campaigns, and surfaces performance insights
- **AI Staffing Advisor** — predictive analytics platform purpose-built for staffing firms, delivering demand forecasting and placement intelligence
- **Workday Integration** — Workday Design Approved integration that brings Joveo's advertising and impression-to-hire analytics into existing Workday workflows

Naren Shankar leads Joveo's Customer Success function. The calls below are his conversations with enterprise clients and staffing firm contacts across this full product portfolio.

Below are complete transcripts of customer success calls. Identify ALL distinct CLIENT scenarios.

TRANSCRIPTS:
{transcripts_text}

**Bloom levels** — assign the level that best reflects the cognitive demand placed on the CS rep to handle this scenario effectively:
- **remember**: Rep must recall specific facts — product names, pricing tiers, contract terms, past conversation details, or SLA commitments
- **understand**: Rep must explain or translate — restate the client's concern in Joveo terms, or clarify a feature's value in plain language to a skeptical stakeholder
- **apply**: Rep must deploy a skill in the moment — use an objection-handling move, pivot the conversation, or match a specific product capability to a stated need
- **analyze**: Rep must diagnose — identify the root cause of dissatisfaction, parse conflicting signals from multiple stakeholders, or map a client's workflow to Joveo's data model
- **evaluate**: Rep must judge and justify — decide whether to escalate vs. hold, negotiate pricing vs. stand firm, or weigh which product is the right fit given client constraints
- **create**: Rep must construct something novel — build a custom ROI narrative, design a multi-product proposal, or synthesize patterns across multiple calls into a new client-facing framing

Identify 2–5 `soft_skills` labels (your own words, not a fixed list) that a rep must exercise to handle this scenario well.

Respond ONLY with valid JSON:
{{
  "scenarios": [
    {{
      "scenario_key": "budget_objection",
      "primary_topic": "Objection Handling",
      "sub_topic": "Budget Constraints",
      "keyphrases": ["budget concern", "cost too high"],
      "soft_skills": ["empathy", "reframing"],
      "bloom_level": "apply",
      "call_ids": ["call_stem"]
    }}
  ]
}}
"""

PROMPT_LAYER_A_V2_LABEL = """\
You are labelling a semantic cluster of CLIENT utterances from Joveo sales call transcripts.

CLUSTER ID: {cluster_id}
CLUSTER KEYWORDS (c-TF-IDF): {keywords}

REPRESENTATIVE UTTERANCES:
{representative_utterances}

Respond ONLY with valid JSON:
{{
  "scenario_key": "snake_case_identifier",
  "primary_topic": "High-level category",
  "sub_topic": "Specific scenario (1 sentence)",
  "keyphrases": ["2-4 word phrase", "another phrase"],
  "soft_skills": ["empathy"],
  "bloom_level": "apply"
}}
"""

PROMPT_LAYER_C_V1 = """\
You are analyzing how Naren Shankar responds to a specific client scenario.

SCENARIO KEY: {scenario_key}
SCENARIO: {sub_topic} ({primary_topic})

Naren's responses across {n_instances} call(s):
{responses_text}

Identify recurring strategic milestones (distinct communicative moves appearing in 2+ responses).

Respond ONLY with valid JSON:
{{
  "milestones": [
    {{
      "order": 1,
      "label": "Acknowledge concern",
      "description": "Naren explicitly validates the client worry before solving it.",
      "detection_hint": "Present if Naren restates concern BEFORE any Joveo solution.",
      "sequencing_type": "fixed",
      "source_v": "v1_gemma"
    }}
  ],
  "soft_skill_rubric": {{
    "excellent_execution": "2-3 observable behaviors from the real examples",
    "failing_execution": "[inferred, unverified] What a poor response looks like",
    "confidence": "inferred"
  }},
  "anti_patterns": [
    {{
      "pattern": "[inferred] Jumping to product features without acknowledging concern",
      "confidence": "inferred, unverified"
    }}
  ]
}}

Rules:
- Only include milestones in 2+ responses
- Order by position (first = order 1)
- failing_execution MUST include prefix "[inferred, unverified]"
- anti_patterns MUST include "[inferred]" prefix
"""

PROMPT_LAYER_C_V2_ORDER = """\
Review milestone ordering for scenario: {scenario_key}
Based on {n_instances} instances. High-variance milestones:

{milestones_text}

For each: determine "conditional" (position depends on context) or "fixed" (statistical noise).

Respond ONLY with valid JSON:
{{
  "milestone_sequencing": [
    {{
      "label": "milestone label",
      "sequencing_type": "fixed",
      "sequencing_rationale": "1-2 sentence explanation"
    }}
  ]
}}
"""

PROMPT_LAYER_C_MILESTONE_DESCRIBE = """\
Describe one recurring communicative move in Naren Shankar's sales responses.

SCENARIO: {scenario_key}
MILESTONE: {order} of {total}

Clauses grouped into this cluster:
{cluster_clauses}

Respond ONLY with valid JSON:
{{
  "label": "2-4 word action label",
  "description": "2-3 sentences grounded in the clauses above",
  "detection_hint": "How to tell this milestone is present vs a near-miss"
}}
"""

PROMPT_LAYER_B_CLEAN = """\
Clean the following transcript excerpt. Remove disfluencies (um, uh, filler like/you know/I mean) while preserving content and voice.

ORIGINAL:
{raw_text}

Respond ONLY with valid JSON:
{{"cleaned": "cleaned text here"}}
"""

PROMPT_STEP0_SIGNAL_CHECK = """\
You are auditing a CSM's call transcript for the Ego Trap gap-analysis pipeline.

Below is the full transcript, followed by the list of known client scenarios from Naren's benchmark brain.

TRANSCRIPT:
{transcript_text}

KNOWN SCENARIOS:
{scenarios_text}

Identify every CLIENT utterance in the transcript that maps to one of the known scenarios above (by meaning, not exact wording).

Respond ONLY with valid JSON:
{{
  "signals_detected": [
    {{
      "scenario_key": "known_scenario_key",
      "client_utterance": "the exact CLIENT sentence, copied verbatim from the transcript"
    }}
  ]
}}

Rules:
- Only use scenario_key values from KNOWN SCENARIOS above.
- client_utterance must be copied verbatim (word-for-word) so it can be matched back to the transcript.
"""

PROMPT_STEP3_MILESTONE_SCORE = """\
You are evaluating whether a CSM's response satisfies a specific milestone.

MILESTONE: {milestone_description}
DETECTION HINT: {detection_hint}
NAREN'S BENCHMARK RESPONSE (for reference only): {benchmark_response}

CSM RESPONSE:
"{csm_response}"

Score how well the CSM's response satisfies this milestone, using exactly one of three verdicts:
- "full_hit": the milestone is fully satisfied
- "partial_hit": the CSM attempted this milestone but the response is incomplete or weak
- "miss": the milestone was not addressed at all

Respond ONLY with valid JSON:
{{
  "verdict": "full_hit",
  "confidence": "high",
  "reason": "one sentence explanation",
  "quote": "verbatim excerpt from the CSM response this verdict is based on (empty string if verdict is full_hit)",
  "gap_to_ideal": "one sentence on what a full_hit response would have included (empty string if verdict is full_hit)"
}}
"""

PROMPT_STEP3_SOFT_SKILL_SCORE = """\
SOFT SKILL: {skill_name}
EXCELLENT EXECUTION: {excellent_execution}
FAILING EXECUTION: {failing_execution}

CSM RESPONSE:
"{csm_response}"

How did the CSM execute on this soft skill?
Respond ONLY with valid JSON:
{{
  "rating": "excellent",
  "confidence": "high",
  "reason": "one sentence explanation"
}}
"""

PROMPT_STEP3_MILESTONE_SCORE_BATCH = """\
You are evaluating whether CSM responses satisfy specific milestones, across multiple independent items.
Each item below has a unique "id". Evaluate EACH item independently — do not let one item influence another.

Score each item using exactly one of three verdicts:
- "full_hit": the milestone is fully satisfied
- "partial_hit": the CSM attempted this milestone but the response is incomplete or weak
- "miss": the milestone was not addressed at all

ITEMS:
{items_block}

Respond ONLY with valid JSON — a single array with exactly one object per item, in this shape:
[
  {{"id": "<id>", "verdict": "full_hit", "confidence": "high", "reason": "one sentence explanation", "quote": "verbatim excerpt (empty string if verdict is full_hit)", "gap_to_ideal": "one sentence (empty string if verdict is full_hit)"}}
]
"""

PROMPT_STEP3_SOFT_SKILL_SCORE_BATCH = """\
You are rating CSM execution of specific soft skills, across multiple independent items.
Each item below has a unique "id". Evaluate EACH item independently — do not let one item influence another.

ITEMS:
{items_block}

Respond ONLY with valid JSON — a single array with exactly one object per item, in this shape:
[
  {{"id": "<id>", "rating": "excellent", "confidence": "high", "reason": "one sentence explanation"}}
]
"""
