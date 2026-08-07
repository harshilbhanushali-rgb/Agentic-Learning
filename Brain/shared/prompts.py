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

# Batched milestone-description prompt. Same rationale as
# PROMPT_LAYER_C_MILESTONE_TRIAGE_BATCH: describing one milestone at a time was
# the dominant Gemma call count in Layer C (up to milestone_hard_cap calls per
# scenario, ~241-403 total across a full run), each carrying only a handful of
# short clauses -- exactly the shape ego_trap/milestone_scoring.py's *_batch
# functions exist to avoid.
PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH = """\
Describe each recurring communicative move in Naren Shankar's sales responses below.
Each item below has a unique "id" and belongs to a specific scenario/milestone-position --
describe EACH independently using only its own clauses, do not let one item influence another.

ITEMS:
{items_block}

Respond ONLY with valid JSON -- a single array with exactly one object per item, in this shape:
[
  {{
    "id": "<id>",
    "label": "2-4 word action label",
    "description": "2-3 sentences grounded in the clauses above",
    "detection_hint": "How to tell this milestone is present vs a near-miss"
  }}
]
"""

# Batched review-flag judge for V2 Layer C milestone candidates. Mirrors
# PROMPT_LAYER_A_V2_TRIAGE's precedent: a flagged item is not left dangling, it
# gets resolved with one Gemma call in the same run. Batched (up to 5 per call)
# because flagged candidates are sparse (~5% of clusters) and scattered thinly
# across scenarios -- judging one at a time would be one call for a handful of
# tokens each, the same shape ego_trap/milestone_scoring.py's *_batch functions
# already exist to avoid.
PROMPT_LAYER_C_MILESTONE_TRIAGE_BATCH = """\
You are auditing candidate rubric milestones for Naren Shankar's sales coaching taxonomy.
Each candidate below is a cluster of clauses from Naren's responses that recurred across
multiple calls and was proposed as a milestone -- a strategic move worth coaching a junior
rep to repeat. Some of these are genuine strategic milestones; others are conversational
mechanics (backchannel, acknowledgment, scheduling chatter) that clustered densely because
they recur verbatim, not because they carry a coaching-worthy strategic move. Each was
flagged because its embedding centroid is unusually similar to a known non-coachable
scenario (the NEAREST SINK below) -- that is a hint, not a verdict; judge the clauses.

Each item below has a unique "id". Judge EACH item independently -- do not let one item
influence another.

ITEMS:
{items_block}

For each item, decide exactly one of:
- "genuine_milestone"  a real strategic move a rep should be coached to repeat.
- "mechanics"          backchannel, acknowledgment, scheduling, or other conversational
                       plumbing with no strategic content to coach.

Respond ONLY with valid JSON -- a single array with exactly one object per item, in this shape:
[
  {{"id": "<id>", "verdict": "genuine_milestone", "reason": "one sentence justifying the decision"}}
]
"""

# Ground-truth labeling for shared/trigger_quality.py's calibration
# (label_trigger_quality_sample.py). Judges a sink-bound pair's RESPONSE for
# genuine coachability regardless of how filler-like its trigger sounds --
# the exact judgment call assign_scenarios's trigger-only sink decision
# cannot make. See docs/superpowers/specs/2026-08-04-layer-b-trigger-quality-gate-design.md
# ("Ground-truth labeling") and the sink-rescue design's Status update 3
# ("Calibration"), which both consume this script's output. Batched (5 per
# call) mirroring PROMPT_LAYER_C_MILESTONE_TRIAGE_BATCH's rationale for
# small, numerous items.
PROMPT_TRIGGER_QUALITY_JUDGE = """\
You are auditing trigger-response pairs from Naren Shankar's sales coaching knowledge base.
Each pair below was discarded by the pipeline's scenario-matching step because the CLIENT's
trigger utterance embedded closest to a non-coachable "sink" scenario (mechanics, backchannel,
or logistics chatter) -- but that decision only ever looked at the trigger, never the response
that followed. Some of these responses are genuinely substantive coaching content that was
wrongly discarded; others are correctly discarded junk.

Each item below has a unique "id". Judge EACH item independently using only its own trigger and
response -- do not let one item influence another.

ITEMS:
{items_block}

For each item, decide: is the RESPONSE genuinely coachable content -- specific, strategic, or
substantive enough that a rep should be coached on how Naren handled it -- regardless of how
generic or filler-like the trigger sounds?

Respond ONLY with valid JSON -- a single array with exactly one object per item, in this shape:
[
  {{"id": "<id>", "coachable": true, "reason": "one sentence justifying the decision"}}
]
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

# Layer A V2 triage. Replaces PROMPT_LAYER_A_V2_LABEL, which asked only "what is
# this cluster?" with no memory of prior clusters -- so nothing stopped it from
# minting a 9th near-identical acknowledgment scenario.
#
# Two additions carry the whole fix:
#   nearest_scenarios  lets the model SEE it is looking at a duplicate.
#   coverage_note      tells it when a cluster is broad enough to be suspicious,
#                      without pre-judging the answer. Coverage alone cannot
#                      separate backchannel from a core business topic that
#                      genuinely comes up in most calls, so the model decides.
PROMPT_LAYER_A_V2_TRIAGE = """\
You are curating a taxonomy of coachable CLIENT scenarios from Joveo sales call transcripts.
A junior colleague will be trained against this taxonomy, so every entry must be a distinct
client situation that demands a deliberate strategic response.

CLUSTER KEYWORDS (c-TF-IDF): {keywords}

REPRESENTATIVE CLIENT UTTERANCES:
{representative_utterances}

EVIDENCE:
- appears in {distinct_calls} of {total_calls} distinct calls ({call_coverage:.0%} of the corpus)
- {n_clauses} clauses total, merged from {n_merged} raw cluster(s)
{coverage_note}

NEAREST SCENARIOS ALREADY ACCEPTED (by embedding similarity):
{nearest_scenarios}

Choose exactly one decision:

- "merge_into"    this cluster is the same client situation as one of the accepted scenarios
                  above, only worded differently. Set merge_into_key to its exact key.
                  Prefer this over creating a near-duplicate.
- "mechanics"     this is conversational machinery, not a scenario: acknowledgment,
                  backchannel, greetings, thanks, filler, scheduling chatter, audio checks.
                  There is no strategic choice to coach here.
- "not_coachable" real content, but it carries no client need to respond to: pleasantries,
                  off-topic small talk, or garbled fragments with no recoverable meaning.
- "new_scenario"  a genuine client situation not already in the list above.

Judge the utterances, not the keywords. High corpus coverage is a reason to look harder,
NOT a reason to reject: a central business topic can legitimately appear in most calls.

**Bloom levels** — for "new_scenario" only, assign the level that best reflects the cognitive
demand placed on the CS rep to handle this scenario effectively. `bloom_level` MUST be exactly
one of these six words:
- **remember**: Rep must recall specific facts — product names, pricing tiers, contract terms,
  past conversation details, or SLA commitments
- **understand**: Rep must explain or translate — restate the client's concern in Joveo terms,
  or clarify a feature's value in plain language to a skeptical stakeholder
- **apply**: Rep must deploy a skill in the moment — use an objection-handling move, pivot the
  conversation, or match a specific product capability to a stated need
- **analyze**: Rep must diagnose — identify the root cause of dissatisfaction, parse conflicting
  signals from multiple stakeholders, or map a client's workflow to Joveo's data model
- **evaluate**: Rep must judge and justify — decide whether to escalate vs. hold, negotiate
  pricing vs. stand firm, or weigh which product is the right fit given client constraints
- **create**: Rep must construct something novel — build a custom ROI narrative, design a
  multi-product proposal, or synthesize patterns across multiple calls into a new client-facing
  framing

Respond ONLY with valid JSON:
{{
  "decision": "new_scenario",
  "merge_into_key": null,
  "reason": "one sentence justifying the decision",
  "scenario_key": "snake_case_identifier",
  "sub_topic": "Specific client situation (1 sentence)",
  "keyphrases": ["2-4 word phrase", "another phrase"],
  "soft_skills": ["empathy"],
  "bloom_level": "apply"
}}

For "merge_into", set merge_into_key and reason; the remaining fields may be null.
For "mechanics" and "not_coachable", still supply scenario_key and sub_topic so the
cluster can be recorded and used as a sink for unmatched pairs.

Note: this prompt does NOT ask for a primary_topic. Grouping into primary topics is a
separate, structural step run once over the whole taxonomy after adjudication (see
shared/topic_grouping.py) -- inventing one per cluster here is exactly what produced three
different primary_topic strings ("Discovery", "Discovery & Qualification", "Client
Environment") for scenarios that are clearly siblings under one umbrella.
"""

# Batched adjudication of clusters drawn from the SINK POOL -- pairs Layer B filed to a
# non-coachable scenario and thereby excluded from every rubric. See
# docs/superpowers/specs/2026-08-05-sink-pool-population-diagnostic-design.md.
#
# Deliberately three-way, not the coachable/not-coachable binary that eight prior per-pair
# signals were measured against. The third option (new_coachable_topic) exists because Layer A
# builds its taxonomy from CLIENT clauses only -- a coaching behaviour whose client-side cues are
# consistently short or filler-like has no scenario it could ever be routed to, so "junk" and
# "real content with nowhere to go" are indistinguishable to any binary judge. That distinction
# is the whole reason this prompt exists.
#
# Judges the EXPERT'S RESPONSES, not the triggers. Every trigger in this pool already
# best-matched a sink; asking about them again would just re-run the decision that lost the
# content in the first place.
PROMPT_SINK_POOL_TRIAGE = """\
You are auditing content that an automated pipeline DISCARDED, to find out whether discarding it
was correct.

Background: a senior Customer Success expert's call transcripts were mined for
(client trigger -> expert response) pairs. Each pair was routed to a topic by matching the
CLIENT's words only. Pairs whose client trigger looked like conversational machinery
(acknowledgment, filler, scheduling, greetings) were filed to a "sink" and excluded from every
coaching rubric -- regardless of what the expert actually said in reply. Roughly 40% of all pairs
ended up there.

Below are CLUSTERS of those discarded pairs, grouped by the similarity of the EXPERT'S RESPONSE.
For each cluster, judge the responses.

{items_block}

For each cluster choose exactly one verdict:

- "belongs_to_existing"   The responses carry real coachable expertise, and the nearest existing
                          coachable topic shown for that cluster is a genuinely good home for it.
                          Set target_scenario_key to that exact key. This means the pipeline made
                          a ROUTING error: the content had somewhere to go and was dropped anyway.

- "new_coachable_topic"   The responses carry real coachable expertise, but the nearest existing
                          coachable topic is NOT a good home -- the behaviour shown here is a
                          distinct thing the taxonomy simply has no entry for. Set proposed_label
                          and proposed_description. Choose this over forcing a bad fit: a wrong
                          home is worse than an admitted gap.

- "genuine_sink"          There is no coachable expertise here. The responses are conversational
                          machinery in their own right: backchannel, acknowledgment, greetings,
                          sign-offs, audio checks, pure scheduling logistics, or small talk. The
                          pipeline was RIGHT to discard these.

How to judge:

- Judge what the EXPERT'S RESPONSES demonstrate, not what the client's trigger looked like. A
  filler trigger followed by a substantive strategic answer is exactly the failure being audited.
- "Coachable" means a junior colleague could learn a deliberate move from it: a diagnostic
  question, a reframe, an expectation-setting caveat, a specific recommendation, a tradeoff
  explained. Length is NOT the test -- a sharp ten-word strategic pivot is coachable; a long
  rambling non-answer or a detailed scheduling negotiation is not.
- Judge the cluster as a whole. If the responses are mixed, decide by what the majority
  demonstrate and say so in the reason.
- Distinct-call support is evidence of a RECURRING move rather than a one-off. Low support is a
  reason to look harder, not an automatic rejection.

Respond ONLY with valid JSON, one object per cluster, echoing each id exactly:
{{
  "results": [
    {{
      "id": "cluster_7",
      "verdict": "belongs_to_existing",
      "target_scenario_key": "ats_compatibility_and_migration_discovery",
      "proposed_label": null,
      "proposed_description": null,
      "reason": "one sentence justifying the verdict, citing what the responses actually do"
    }}
  ]
}}

For "new_coachable_topic", set proposed_label (a short human-readable name) and
proposed_description (one sentence naming the client situation and the expert move), and leave
target_scenario_key null.
For "genuine_sink", leave target_scenario_key, proposed_label and proposed_description null.
"""

# Writes the permanent scenario record for a cluster diagnose_sink_pool.py already
# verdicted "new_coachable_topic". Deliberately NOT a reuse of PROMPT_LAYER_A_V2_TRIAGE:
# that prompt is written to interpret CLIENT clauses and ask a coachability question
# this prompt's caller has already answered (see
# docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md). This
# prompt's only job is to write up an already-confirmed gap in the same output shape
# every other scenario in the taxonomy uses.
PROMPT_GRADUATE_SINK_TOPIC = """\
You are writing the permanent scenario record for a coaching topic that this taxonomy never
had an entry for. A prior audit already reviewed real call pairs and confirmed a genuine,
recurring expert behaviour exists here -- your job is only to write it up in the same shape as
every other scenario in the taxonomy, not to re-judge whether it is real.

PROPOSED LABEL: {proposed_label}
PROPOSED DESCRIPTION: {proposed_description}
WHY THIS IS A GAP, NOT A DUPLICATE OF AN EXISTING SCENARIO: {reason}

SAMPLE PAIRS (CLIENT trigger -> EXPERT response) THAT DEMONSTRATE THIS BEHAVIOUR:
{samples_block}

Write the scenario record a junior CS colleague would be coached against. Use the same
bloom_level rubric used everywhere else in this taxonomy:
- remember: recall facts -- pricing tiers, contract terms, SLA commitments
- understand: explain or restate a concern in Joveo terms
- apply: deploy a specific move in the moment -- objection handling, a conversational pivot
- analyze: diagnose a root cause, parse conflicting signals from multiple stakeholders
- evaluate: judge and justify a tradeoff -- escalate vs. hold, negotiate vs. stand firm
- create: construct something novel -- a custom ROI narrative, a multi-product proposal

Respond ONLY with valid JSON:
{{
  "scenario_key": "snake_case_identifier",
  "business_description": "one sentence naming the client situation and the expert move",
  "keyphrases": ["2-4 word phrase", "another phrase"],
  "soft_skills": ["skill_name"],
  "bloom_level": "apply"
}}
"""

# Batched primary-topic labelling. Runs once per macro-group AFTER the per-subtopic
# adjudication loop above finishes and shared/topic_grouping.py has decided which
# subtopics belong together -- this prompt only names the umbrella category a group of
# already-adjudicated (or already-clustered, for the nested mechanism) subtopics share.
# Batched (up to 5 groups per call) because macro-groups are few -- ~15-25 expected, per
# the 0.70-threshold raw-topic measurement on record above for merge_cosine_threshold --
# mirroring PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH's rationale for small, numerous items.
PROMPT_LAYER_A_PRIMARY_TOPIC_LABEL_BATCH = """\
You are naming broad primary-topic categories that group related client scenarios from
Joveo sales call transcripts. Each group below already contains several related subtopic
clusters -- your job is to name the UMBRELLA category they share, not re-describe any one
member.

Each item below has a unique "id". Name EACH group independently -- do not let one group's
members influence another's label.

GROUPS:
{items_block}

Respond ONLY with valid JSON -- a single array with exactly one object per group, in this
shape:
[
  {{
    "id": "<id>",
    "primary_topic_key": "snake_case_identifier",
    "label": "2-4 word category name",
    "description": "1 sentence describing what unifies this group's members",
    "keyphrases": ["2-4 word phrase", "another phrase"]
  }}
]
"""
