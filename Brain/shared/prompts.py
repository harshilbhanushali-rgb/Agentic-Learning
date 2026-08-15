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

Each milestone becomes a criterion that a DIFFERENT person's response will be scored
against, so write it as an observable behaviour with NO subject: "Validates the client's
worry before proposing a solution." Never name a person, never use he/she/they, never write
"the speaker". Generalise past the specific wording, numbers, clients or anecdotes in the
responses above -- state the underlying behaviour, not the instance. The same rule applies
to detection_hint.

Respond ONLY with valid JSON:
{{
  "milestones": [
    {{
      "order": 1,
      "label": "Acknowledge concern",
      "description": "Validates the client's stated worry before proposing a solution.",
      "detection_hint": "Present if the concern is restated or named BEFORE any solution is offered; absent if the response opens with the solution.",
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
- description and detection_hint: observable behaviour, no subject, no names, no he/she/they
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
# Writes a COACHING CRITERION, not a description of what Naren did.
#
# The previous version opened "Describe each recurring communicative move in Naren
# Shankar's sales responses" and asked for a description "grounded in the clauses above".
# Measured 2026-08-10: all 405 stored milestone descriptions came out as narration about a
# person (37% naming Naren, 63% "the speaker", 91% using he/she/his/her), e.g. "He uses
# hypothetical numerical examples of job slots to illustrate how the platform can scale."
#
# That breaks Layer D at the root. Those descriptions and detection_hints are what Step 3
# scores a DIFFERENT person's response against, so a CSM can handle a situation well and
# still miss every milestone, because they did not reproduce Naren's specific improvisation.
# It is the dominant cause of the 93.9% miss rate.
#
# The clauses are still the evidence -- the model must generalise FROM them to the
# transferable move, rather than summarise them.
PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH = """\
You are writing coaching criteria for a sales rubric.

Below are clusters of clauses taken from expert sales responses. Each cluster is one
recurring move. For each, write the criterion that a DIFFERENT person's response must
satisfy to count as having made that move.

Each item has a unique "id" and belongs to a specific scenario/milestone-position --
write EACH independently using only its own clauses, do not let one item influence another.

Rules, all of them load-bearing:
- Write the criterion as an OBSERVABLE BEHAVIOUR, in the present tense, with NO subject:
  "Acknowledges the client's existing process before proposing an alternative."
  NOT "Naren acknowledges..." and NOT "The speaker acknowledges...".
- Never name any person. Never use he/she/they/his/her. Never write "the speaker".
- Generalise. The clauses are evidence of a move, not the move itself. If a clause happens
  to mention a specific number, client, tool or anecdote, state the underlying behaviour
  instead ("illustrates the point with a concrete worked example"), never the specific
  instance ("uses hypothetical job-slot numbers").
- The criterion must be satisfiable by someone who has never read these clauses and who
  would naturally use different words.
- detection_hint must say what distinguishes a genuine instance from a near-miss, in the
  same person-free, behavioural terms.

ITEMS:
{items_block}

Respond ONLY with valid JSON -- a single array with exactly one object per item, in this shape:
[
  {{
    "id": "<id>",
    "label": "2-4 word action label",
    "description": "1-2 sentences stating the observable behaviour, no subject, no names",
    "detection_hint": "What separates a genuine instance from a near-miss"
  }}
]
"""

# The SITUATED describe prompt (added 2026-08-12). Selected by layer_c.describe_mode,
# which ships 'legacy' -- see docs/superpowers/specs/2026-08-12-layer-c-profile-rebuild-design.md.
#
# WHAT IS DIFFERENT AND WHY. The legacy prompt above is blind by construction: the model
# sees the scenario as a bare key string, its own response clauses, and nothing else. It
# has never seen a CLIENT TURN, which is why no milestone can state a precondition -- 234
# of 235 are labelled "fixed" and the conditional trigger fires 0 of 226 times. It also
# cannot see its sibling moves, so it cannot write a criterion that distinguishes move 3
# from move 5. Measured 2026-08-11/12: the expert scores 0.114 against his own rubrics and
# 0.090 against deliberately UNRELATED ones -- 1.2:1, reproduced three times.
#
# THE RULE CHANGE THAT MATTERS MOST. The 2026-08-10 rewrite banned two different things in
# one breath. "Never narrate a person" was correct and is kept -- it fixed a real bug worth
# ~4x the noise band. "Never state the specific instance" was an over-correction and is
# DROPPED: it is what made criteria scenario-agnostic. A criterion may name its subject
# matter; it still may not name a person.
PROMPT_LAYER_C_MILESTONE_DESCRIBE_SITUATED = """\
You are writing coaching criteria for a sales rubric.

Everything below belongs to ONE scenario. You are given, for each recurring move: the
expert's own clauses, and the CLIENT TURNS that prompted them. Write the criterion a
DIFFERENT person's response must satisfy to count as having made that move.

THE SCENARIO
{scenario_block}

NEAREST OTHER SCENARIOS — a criterion here must NOT be satisfiable by a good response to
one of these. If what you are about to write would also be true there, it is too generic.
{neighbours_block}

THE MOVES IN THIS SCENARIO'S RUBRIC
{moves_block}

Rules, all of them load-bearing:
- Write the criterion as an OBSERVABLE BEHAVIOUR, in the present tense, with NO subject:
  "Acknowledges the client's existing process before proposing an alternative."
  NOT "Naren acknowledges..." and NOT "The speaker acknowledges...".
- Never name any person. Never use he/she/they/his/her. Never write "the speaker".
- DO name the subject matter. "Explains how job-slot pricing changes at higher volume"
  is right; "illustrates the point with a concrete example" is too generic to identify
  this scenario, and criteria written that way have measurably failed.
- The criterion must be satisfiable by someone who has never read these clauses and who
  would naturally use different words. Generalise past the particular number, client or
  anecdote in a clause — but never past the TOPIC.
- Every move is shown alongside its siblings so you can make them DISTINGUISHABLE. Use
  them for contrast only: each criterion must still be grounded in its own clauses. Do
  NOT invent a distinction the clauses do not support just to make two moves look
  different.
- precondition states WHEN this move is called for, judged from the client turns shown.
  If it applies to essentially any turn in this scenario, say "any turn in this scenario"
  — do not manufacture a condition.
- detection_hint says what separates a genuine instance from a near-miss, in the same
  person-free, behavioural terms.

Respond ONLY with valid JSON -- a single array with exactly one object per move id above:
[
  {{
    "id": "<id>",
    "label": "2-4 word action label",
    "description": "1-2 sentences stating the observable behaviour, no subject, no names",
    "precondition": "the client-side condition that calls for this move",
    "detection_hint": "What separates a genuine instance from a near-miss"
  }}
]
"""

# COVERAGE AREAS (added 2026-08-12). Option 4 of the profile-rebuild design: replace
# ~5 independently-written gradable criteria per scenario with 3-4 things strong handling
# COVERS. Selected by layer_c.describe_mode == 'coverage'.
#
# TWO DELIBERATE INVERSIONS OF THE CRITERIA DESIGN:
#
#   1. Areas KEEP their concrete exemplars. "Strip the specifics" was needed to make a
#      criterion gradable and is destructive for teaching -- "illustrates the point with
#      a concrete worked example" teaches nothing; the worked example teaches everything.
#   2. Each area names the CLUSTERS it covers. That is load-bearing, not bookkeeping: it
#      is what keeps support_calls/support_clauses attached, so an area stays auditable
#      back to "this recurs in 22 calls" instead of becoming unfalsifiable prose. It also
#      makes a 4-clusters-into-1 collapse visible in the artifact -- the merge-blindness
#      that inflated an entire Layer C A/B while the milestone COUNT went up.
PROMPT_LAYER_C_COVERAGE_AREAS = """\
You are writing a coaching playbook for one recurring sales situation.

Below is everything the expert did in this situation across many real calls, grouped into
recurring moves, each shown with the CLIENT TURNS that prompted it.

THE SITUATION
{scenario_block}

NEAREST OTHER SITUATIONS — the playbook must be about THIS situation, not one that would
serve equally well for these:
{neighbours_block}

THE RECURRING MOVES
{moves_block}

Write 3 to 4 COVERAGE AREAS: the things that strong handling of this situation covers
between them. An area is broader than a single move -- several moves usually belong to
one area -- and the areas together should account for every move above.

Rules:
- Name the subject matter. "Explains what drives a cost-per-application swing" is right;
  "provides a clear explanation" could describe any situation and is useless.
- Never name a person. Never use he/she/they/his/her. Never write "the speaker".
- covers_clusters must list the ids of the moves this area accounts for. Every move above
  must appear in exactly one area. Do not invent ids.
- precondition states when this area is called for, judged from the client turns shown.
  If it applies to essentially any turn in this situation, say "any turn in this
  situation" -- do not manufacture a condition.
- exemplars: 2-3 SHORT VERBATIM quotes from the clauses above, copied exactly. These are
  what a person learns from, so keep the specific numbers, tools and examples in them.
- Do NOT force a split to reach 4 areas, and do NOT merge unrelated moves to reach 3. If
  the moves genuinely form 3 areas, write 3.

Respond ONLY with valid JSON:
[
  {{
    "id": "C1",
    "label": "2-5 word name for this area",
    "description": "1-2 sentences on what strong handling covers here",
    "precondition": "when this area is called for",
    "covers_clusters": ["<move id>", "<move id>"],
    "exemplars": ["verbatim quote", "verbatim quote"]
  }}
]
"""

# TOPIC-STRIP for the skill pass (added 2026-08-12). Option 1 of the profile-rebuild
# design, and the step the whole approach depends on.
#
# WHY IT IS NEEDED, MEASURED. Clustering the 405 milestone descriptions as written groups
# them by SUBJECT, not behaviour: 290 of 338 clusters held a single scenario, and "ask
# open questions about budget" landed in a different cluster from "ask open questions
# about screening" purely on the topical object. bge embeddings are dominated by topic,
# so behavioural similarity is invisible until the topic is removed.
#
# The output is NEVER shown to a CSM -- it exists only to be embedded and clustered. That
# is why stripping the subject is right here and wrong everywhere else in this pipeline:
# the 2026-08-10 over-correction did exactly this to CRITERIA, which are read by people
# and graded against, and it is what made them scenario-agnostic.
PROMPT_SKILL_ABSTRACT_BATCH = """\
Restate each coaching item as the underlying BEHAVIOUR, with the subject matter removed.

You are not writing coaching text. These restatements are used only to group items that
describe the same underlying move, so two items about different topics must come out
identical when the behaviour is the same.

Rules:
- Drop every topic, product, tool, metric and client detail. "Ask open questions about
  their ATS integration" and "Ask open questions about their budget" must BOTH become
  "asks open questions to draw out the client's own reasoning".
- Keep what the person is DOING and WHY: probing, quantifying, reframing, conceding,
  explaining a mechanism, proposing a next step, setting an expectation.
- Present tense, no subject, under 15 words.
- Never name a person. Never use he/she/they.
- If an item is pure call mechanics (managing turns, screen sharing, scheduling), say
  exactly "call mechanics" -- that is a real answer and those should group together.

ITEMS:
{items_block}

Respond ONLY with valid JSON -- one object per item id above:
[
  {{"id": "<id>", "behaviour": "the topic-free behaviour, under 15 words"}}
]
"""

# V2, 2026-08-13. The ONLY difference from V1 is that the purpose clause is banned.
#
# WHY. V1 says "Keep what the person is DOING and WHY". Measured on the real 405: that WHY
# splintered ONE behaviour into thirty phrasings -- "explains a mechanism to clarify
# functionality", "...to demonstrate value", "...to justify an approach", "...to demonstrate
# how a goal is achieved" -- 55 items across 30 strings that are plainly one move. The
# purpose is not the behaviour; it is the situation the behaviour was used in, and it varies
# per instance by definition. Keeping it guarantees the thing this pass exists to prevent.
#
# This is the THIRD attempt at the same question (V1 with bge, V1 with gemini, now V2). The
# gate does not move: V_MIN stays 0.80 and the K/median bounds are unchanged. If this fails,
# the question is closed.
PROMPT_SKILL_ABSTRACT_BATCH_V2 = """\
Restate each coaching item as the underlying BEHAVIOUR, with the subject matter removed.

You are not writing coaching text. These restatements are used only to group items that
describe the same underlying move, so two items describing the same move must come out
IDENTICAL even when they were done for different reasons or about different topics.

Rules:
- Drop every topic, product, tool, metric and client detail. "Ask open questions about
  their ATS integration" and "Ask open questions about their budget" must BOTH become
  "asks open questions".
- State ONLY the move itself. Do NOT state its purpose, goal, or effect. Never write "to
  demonstrate value", "to build trust", "to ensure alignment", "to set expectations",
  "to clarify functionality" or anything of that shape. Those describe WHY the move was
  made on one occasion, and the same move is made for different reasons every time.
  "explains a mechanism to demonstrate value" and "explains a mechanism to justify an
  approach" must BOTH become "explains a mechanism".
- Keep the verb and its object-type only: probing, quantifying, reframing, conceding,
  explaining a mechanism, proposing a next step, setting an expectation, building rapport.
- Present tense, no subject, UNDER 8 WORDS. Shorter is better.
- Never name a person. Never use he/she/they.
- If an item is pure call mechanics (managing turns, screen sharing, scheduling), say
  exactly "call mechanics".

ITEMS:
{items_block}

Respond ONLY with valid JSON -- one object per item id above:
[
  {{"id": "<id>", "behaviour": "the topic-free, purpose-free behaviour, under 8 words"}}
]
"""

# The counterweight in the skills-vocabulary test. Pre-registration:
# docs/superpowers/specs/2026-08-13-layer-c-skills-vocabulary-design.md section 3.
#
# WHY THIS EXISTS. skills.sweep's cross_scenario_coverage cannot fail: coarsening the
# threshold merges everything into one group and drives it to 1.0 by construction, so the
# sweep alone always says yes at SOME granularity. This is the only measurement in the test
# that gets WORSE as groups fuse distinct moves. Same defect class as the merge-blind
# _match_milestones, which scored three baseline milestones collapsing into one blob as
# three clean matches because it only counted the good outcome.
#
# EVERY GROUP GETS A VERDICT. Never a returned subset -- that is the generalising lesson
# from the objective function's applicability judge, whose prompt instructed sparsity and
# invited the model to pick a top few and stop.
#
# Some groups shown here are NOT real clusters: they are deliberately mismatched pairs
# mixed in blind, so a rubber-stamp judge fails visibly instead of certifying the run. The
# prompt must therefore never hint that groups are expected to be coherent.
PROMPT_SKILL_MERGE_VALIDITY_BATCH = """\
Each GROUP below holds coaching behaviours that were placed together automatically. The
grouping is unverified -- some groups describe a single coaching move, others have fused
moves a coach would treat as separate things to work on.

Judge each group on the behaviours as written. Do not assume a group is correct because it
was grouped, and do not assume it is wrong because its wordings differ.

Verdicts:
- "same_move" -- a coach could give one piece of feedback covering every item here.
- "fused" -- coaching one item well would leave another unaddressed.

Rules:
- Return a verdict for EVERY group id listed below. Never return only the interesting ones.
- Judge each group independently -- do not let one group influence another.
- A group of one item is "same_move" by definition.
- Wording differences do not make a group "fused"; different underlying moves do.

GROUPS:
{groups_block}

Respond ONLY with valid JSON -- one object per group id above:
[
  {{"id": "<id>", "verdict": "same_move", "reason": "one short sentence"}}
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

# PROMPT_STEP3_MILESTONE_SCORE and PROMPT_STEP3_SOFT_SKILL_SCORE (one call per
# milestone / per skill) were deleted along with their scorers in
# ego_trap/milestone_scoring.py -- nothing but their own tests used them. Two prompts
# stating the same verdict rules, one never exercised, means a rule change lands in
# only one of them. The _BATCH variants below are the only Step 3 prompts.

# Grouped by EXCHANGE, not flat by milestone. The flat shape repeated the benchmark
# response and the CSM response on every milestone line, so a signal with 5 milestones
# sent Naren's two reference responses 5 times -- roughly 4x the tokens for identical
# information. That is what put one batch of 8 at ~30k tokens, above gemma-4-31b-it's
# 16k TPM limit, guaranteeing a 429 on every call.
#
# The ids are unchanged (S<signal>_M<position>), so nothing downstream had to move.
PROMPT_STEP3_MILESTONE_SCORE_BATCH = """\
You are evaluating whether CSM responses satisfy specific coaching milestones.

Below are several INDEPENDENT exchanges. Each exchange has one CSM response and a list of
milestones to score against it. Evaluate each exchange independently — do not let one
exchange influence another, and never score a milestone against a different exchange's
CSM response.

Score every milestone using exactly one of three verdicts:
- "full_hit": the milestone is fully satisfied
- "partial_hit": the CSM attempted this milestone but the response is incomplete or weak
- "miss": the milestone was not addressed at all

EXCHANGES:
{items_block}

Respond ONLY with valid JSON — a single flat array with exactly one object per milestone
id, across all exchanges. Return EVERY id listed above; a missing id is recorded as a
miss, so omitting one silently penalises the CSM.
[
  {{"id": "<id>", "verdict": "full_hit", "confidence": "high", "reason": "one sentence explanation", "quote": "verbatim excerpt (empty string if verdict is full_hit)", "gap_to_ideal": "one sentence (empty string if verdict is full_hit)"}}
]
"""

# SITUATED variant, added 2026-08-15 for calibration/trial_grader_inputs.py.
# Design: docs/superpowers/specs/2026-08-15-grader-inputs-design.md
#
# THE DEFECT IT TESTS. Read from milestone_scoring.score_milestones_batch: the entire
# per-exchange payload is Naren's benchmark, the CSM response, and per milestone only
# `description` + `detection_hint`. The grader never sees the CLIENT TURN, the
# SCENARIO, or the milestone's own `label` -- all three stored and all three discarded
# at grading time. That is the same missing-INPUT defect the Layer C rebuild found in
# the WRITER (PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH cannot state a precondition
# because it has never seen a client turn), one stage later and never diagnosed.
#
# WHY IT MATTERS BEYOND ONE PROMPT. The ceiling run's control arm scores real responses
# against a DELIBERATELY UNRELATED scenario's rubric. A grader that cannot see which
# situation either belongs to has no way to notice the mismatch, and the 2026-08-10
# rewrite stripped the specific instance out of the criteria, so a competent response
# satisfies generic criteria from any scenario. 1.2:1 is what that arrangement predicts
# arithmetically, independent of rubric quality -- and every quality verdict on this
# codebase was measured through it, including trial_layer_c_arms.py, which scores the
# SITUATED-writer arms with this very scorer (line 261). That is circular.
#
# EVERY WORD OF THE ORIGINAL IS PRESERVED. The only additions are {situation_note},
# which describes exactly the fields a given condition supplies, and whatever those
# fields add to each exchange block. Rewording the verdict rules would confound "the
# grader can see the situation" with "the grader was asked differently" -- and a fourth
# wording pass is what stopping condition #1 already ruled out.
#
# THE ONE CONFOUND, STATED RATHER THAN HIDDEN: information cannot be supplied without a
# sentence telling the model the field is there, so the treatment is strictly
# "situational inputs PLUS the minimal instruction to use them". There is no way to
# separate those two and still deliver the information.
#
# IT DELIBERATELY DOES NOT ASK "DID THE MOMENT CALL FOR THIS MOVE." That question has
# failed twice -- the standalone applicability judge at 1.22:1 and the coverage judge at
# 64.9% matched vs 65.7% unrelated. The question here is unchanged from the original:
# did the response satisfy the criterion. Only the visibility of the situation changes.
PROMPT_STEP3_MILESTONE_SCORE_BATCH_SITUATED = """\
You are evaluating whether CSM responses satisfy specific coaching milestones.

Below are several INDEPENDENT exchanges. Each exchange has one CSM response and a list of
milestones to score against it. Evaluate each exchange independently — do not let one
exchange influence another, and never score a milestone against a different exchange's
CSM response.
{situation_note}
Score every milestone using exactly one of three verdicts:
- "full_hit": the milestone is fully satisfied
- "partial_hit": the CSM attempted this milestone but the response is incomplete or weak
- "miss": the milestone was not addressed at all

EXCHANGES:
{items_block}

Respond ONLY with valid JSON — a single flat array with exactly one object per milestone
id, across all exchanges. Return EVERY id listed above; a missing id is recorded as a
miss, so omitting one silently penalises the CSM.
[
  {{"id": "<id>", "verdict": "full_hit", "confidence": "high", "reason": "one sentence explanation", "quote": "verbatim excerpt (empty string if verdict is full_hit)", "gap_to_ideal": "one sentence (empty string if verdict is full_hit)"}}
]
"""

# The applicability pre-check, added 2026-08-11 for Layer C's objective function.
# Design: docs/superpowers/specs/2026-08-11-layer-c-objective-function-design.md
#
# WHY IT ASKS FOR A SUBSET RATHER THAN A PER-MILESTONE VERDICT: one call per batch of
# exchanges instead of one per (milestone, response). Same batching shape and same id
# space (S<exchange>) as PROMPT_STEP3_MILESTONE_SCORE_BATCH.
#
# THE INSTRUCTION THAT CARRIES THE MEASUREMENT is "judge the CLIENT TURN alone". The
# whole question is whether the moment called for the move, and a model shown the
# response would answer "was the move made?" instead -- which is what Step 3 already
# measures, and would make this pre-check a second copy of it rather than a control on
# it. The response is deliberately absent from this prompt.
#
# Measured 2026-08-11: 234 of 235 milestones are labelled sequencing_type "fixed" and
# the conditional trigger (position_variance > 0.3) fires 0 of 226 times, so Layer C
# emits every contingent move as mandatory. This is the missing observation.
PROMPT_MILESTONE_APPLICABILITY_BATCH = """\
You are deciding which coaching milestones a client's turn actually CALLED FOR.

Below are several INDEPENDENT exchanges. Each shows one CLIENT TURN and a list of
milestones from that scenario's rubric. Judge each exchange independently.

For each exchange, return only the ids of milestones the client's turn genuinely called
for at that moment. A milestone is called for when the client's turn creates the opening
or the need for it — a question that invites it, a concern that requires it, or
information that makes it the natural next move.

A milestone is NOT called for when it depends on a precondition this moment does not
supply. Common examples:
- it belongs to a different point in the call (an introduction, an agenda, a wrap-up)
- it needs history this turn does not raise (a past trial, previous spending decisions)
- it needs something specific to point at (an internal analysis, a partner, a document)
- the topic it addresses is simply not what this turn is about

Judge the CLIENT TURN alone. You are not being asked whether anyone performed the
milestone, only whether the moment required it. Do not guess at what the reply said.

Returning every id is almost always wrong: most rubrics contain moves that only some
moments call for. Returning an empty list is a valid and expected answer.

EXCHANGES:
{items_block}

Respond ONLY with valid JSON — a single array with exactly one object per exchange id
listed above. Omitting an exchange makes it unmeasurable, not neutral.
[
  {{"id": "S0", "applicable": ["M1", "M4"], "reason": "one sentence"}}
]
"""

PROMPT_STEP3_SOFT_SKILL_SCORE_BATCH = """\
You are rating CSM execution of specific soft skills, across multiple independent items.
Each item below has a unique "id". Evaluate EACH item independently — do not let one item influence another.

Rate each item using exactly one of three ratings:
- "excellent": the CSM's delivery matches the EXCELLENT EXECUTION description
- "adequate": the skill was executed acceptably, but not notably well
- "failing": the CSM's delivery matches the FAILING EXECUTION description

Use no other rating word. Only "failing" is treated as a coaching gap, so a rating
outside these three is discarded and the gap is lost.

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


# Step 3 scoring against COVERAGE AREAS (added 2026-08-12). The counterpart to
# PROMPT_STEP3_MILESTONE_SCORE_BATCH for the coverage arms of the profile-rebuild trial.
#
# ONE EXPLICIT VERDICT PER AREA, NEVER A RETURNED SUBSET. That is a correction learned
# the expensive way: the applicability judge built on 2026-08-12 asked for a subset and
# failed its own null (0.147 matched vs 0.120 unrelated, 1.22:1). Two defects were in the
# asking -- the prompt instructed sparsity, and "return a subset" invites picking a top
# few and stopping. The scorer that DOES separate signal asks about every id, at the same
# cost per call.
#
# THE CLIENT TURN IS SHOWN. That is what makes not_called_for answerable at all: a judge
# shown only the response cannot tell "she skipped it" from "the moment never asked for
# it", which is the confusion that makes 234 of 235 milestones grade as mandatory.
PROMPT_STEP3_COVERAGE_SCORE_BATCH = """\
You are assessing how well a customer-success rep handled specific moments in real calls.

For each exchange below you are given the CLIENT TURN, the rep's RESPONSE, and the
coverage areas that strong handling of this situation covers. Give a verdict for EVERY
area listed. Do not omit any.

Verdicts:
- covered         the response does this
- partly_covered  the response approaches it but is incomplete or vague
- not_covered     this moment called for it and the response does not do it
- not_called_for  this particular moment did not require it

not_called_for is a real and expected answer. A playbook lists what the situation covers
in general; any single moment usually calls for only some of it. Judge from the CLIENT
TURN whether this moment required the area at all.

EXCHANGES:
{items_block}

Respond ONLY with valid JSON -- one object per id above:
[
  {{
    "id": "<id>",
    "verdict": "covered|partly_covered|not_covered|not_called_for",
    "confidence": "high|medium|low",
    "reason": "one sentence",
    "quote": "the part of the response that covers it, or empty",
    "gap_to_ideal": "what was missing, empty unless not_covered or partly_covered"
  }}
]
"""


# ---------------------------------------------------------------------------------------
# Head-to-head pairwise comparison (docs/superpowers/specs/2026-08-13-head-to-head-
# comparison-design.md). Replaces criteria scoring, which closed at 1.2:1 against an
# unrelated-rubric null across three independent measurements.
#
# THREE INVARIANTS, EACH PINNED BY A TEST IN tests/test_head_to_head.py -- they are the
# instrument, not stylistic choices, and a future edit must not quietly drop one:
#
#   1. BLINDED. No name, no role, no hint which reply came from whom. The whole design
#      rests on the judge comparing quality rather than identifying a person.
#   2. A VERDICT ON EVERY ITEM, never a returned subset. The objective function's
#      applicability judge failed its own null at 1.22:1, and the diagnosis was the asking,
#      not the question: its prompt instructed sparsity, and "return a subset" invites
#      picking a top few and stopping.
#   3. NO INSTRUCTION ABOUT REPLY SIZE. That bias is real -- response_word_count scored
#      AUC 0.853 for "is this coachable" in this repo's own labelled sample -- but it is
#      measured by the length-matched stratum in shared/head_to_head.py, not argued away
#      here. Three wording passes have already failed in this codebase.
#
# Only ONE client turn is shown, the query moment's. The second reply was given at a
# different moment, and revealing that would let the judge mark it down for provenance --
# which is exactly what control C4 measures instead.
PROMPT_HEAD_TO_HEAD_BATCH = """\
You are comparing how two people replied at the same point in a business-to-business sales
conversation about job advertising and recruitment marketing.

Each item below gives one CLIENT TURN and two candidate replies to it, labelled
"Response 1" and "Response 2". Decide which reply handles THIS client turn better.

Weigh, in this order:
  - does it engage what the client actually raised, rather than something adjacent?
  - does it move the conversation toward a decision or a concrete next step?
  - does it leave the client with something they can act on or now understand?

These are speech transcripts, so ignore transcription noise, filler words, false starts
and punctuation. Judge the substance of what was said.

Each item has a unique "id". Judge EACH item independently -- do not let one item
influence another. Return a verdict for every item, including ones you find hard to
separate; "tie" exists for exactly those. Never omit an item.

ITEMS:
{items_block}

Respond ONLY with valid JSON -- a single array with exactly one object per item, in this shape:
[
  {{"id": "<id>", "winner": "1", "reason": "one sentence justifying the decision"}}
]
The "winner" field must be exactly one of "1", "2" or "tie".
"""
