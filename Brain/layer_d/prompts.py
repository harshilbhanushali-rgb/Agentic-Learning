"""Layer D grader prompts.

Kept in the layer_d package rather than shared/prompts.py on purpose: shared/prompts.py
holds the rubric-era ego_trap prompts, and this package must be deletable/auditable as
one unit while both generations coexist.

Prompt design rules, each one paid for:
  * BINARY per-move questions (CheckEval: binary atomic checks beat Likert on
    agreement). No 1-5 scales anywhere. The say arm's no/generic/specific is a
    3-level ANCHORED tier (each level defined by concrete behavior + a benchmark
    example quote), not a Likert scale -- the OSCE/BARS-grounded exception, see
    docs/findings/layer-d-say-arm.md §2.
  * A credited move MUST carry a VERBATIM quote from the rep's reply. The quote is
    verified programmatically after parsing (layer_d/verify_quotes.py) -- the
    call-level trial measured 23% fabricated credits without this.
  * The rep's reply is the ONLY scorable text. The client turn is context.
  * JSON only, ids echoed back -- a missing id is recorded as UNSCORED, never as a
    miss (the old pipeline's truncation-manufactures-misses defect).
"""

PROMPT_CHECKS_BATCH = """You are auditing how a Customer Success rep handled specific moments on client calls, against a playbook distilled from a top performer.

SCENARIO: {scenario_key}
{situation_signature}

THE PLAYBOOK'S KEY MOVES:
{moves_block}

For each MOMENT below, decide FOR EACH MOVE how far the rep's reply goes toward performing that move. Rules:
- Judge ONLY the rep's reply text. The client turn is context, not evidence.
- performed="full": the reply genuinely performs the move. REQUIRES a verbatim quote copied EXACTLY from the rep's reply (the specific words that perform it).
- performed="partial": the reply makes a real, substantive start on the move (one concrete element of it) without completing it. ALSO requires a verbatim quote of that element. Merely mentioning the topic is NOT partial.
- performed="no": the reply does not attempt the move. No quote.
- If you cannot quote it exactly, it is "no".
- Answer every move for every moment.

MOMENTS:
{moments_block}

Respond with ONLY a JSON array, one object per moment:
[{{"moment_id": "<id>", "verdicts": [{{"move_id": "M1", "performed": "full", "quote": "<verbatim from the rep's reply, or empty string when no>"}}, ...]}}, ...]"""


# CONTRACT v1 ("say_v1_no_generic_specific") -- MEASURED, do not loosen (2026-08-28):
# a v2 variant crediting "a concrete element of" a bundled criterion was tried as
# the one pre-registered revision and FAILED the matched-vs-unrelated gate that v1
# passes (v2: 71% over 14 decided calls, p=0.09; v1: 100% over 7, p=0.008; quote
# gate 100% both) -- element-level credit leaks onto topically-adjacent scenarios.
# Full record: docs/findings/layer-d-say-arm.md §8.
PROMPT_SAY_BATCH = """You are auditing how a Customer Success rep handled specific moments on client calls, against a playbook distilled from a top performer. Each move below is something the top performer SAYS in this scenario.

SCENARIO: {scenario_key}
{situation_signature}

THE PLAYBOOK'S KEY MOVES:
{moves_block}

For each MOMENT below, decide FOR EACH MOVE whether the rep's reply RAISES that move's content, and how specifically. Rules:
- Judge ONLY the rep's reply text. The client turn is context, not evidence.
- raised="specific": the reply states the move's content anchored to THIS client's concrete situation -- their names, numbers, tools, campaigns, dates, or an exact next step. REQUIRES a verbatim quote copied EXACTLY from the rep's reply (the words that state it).
- raised="generic": the reply states the move's content, but in words that could be said to any client. ALSO requires a verbatim quote.
- raised="no": the reply does not state the move's content. No quote.
- Specificity means CLIENT-ANCHORED DETAIL, not length or polish. A long generic answer is still "generic".
- If you cannot quote it exactly, it is "no".
- Answer every move for every moment.

MOMENTS:
{moments_block}

Respond with ONLY a JSON array, one object per moment:
[{{"moment_id": "<id>", "verdicts": [{{"move_id": "M1", "raised": "specific", "quote": "<verbatim from the rep's reply, or empty string when no>"}}, ...]}}, ...]"""


PROMPT_PAIRWISE = """You are comparing two Customer Success reps' replies to similar client moments in the same scenario, against a playbook distilled from a top performer.

SCENARIO: {scenario_key}
{situation_signature}

THE PLAYBOOK'S KEY MOVES:
{moves_block}

CLIENT MOMENT (context for reply A):
{trigger_a}

REPLY A:
{reply_a}

CLIENT MOMENT (context for reply B):
{trigger_b}

REPLY B:
{reply_b}

For each move, which reply performs it better? Rules:
- Judge execution of the specific move, not overall polish or length.
- "equal" means both perform it comparably OR neither performs it.
- Answer every move.

Respond with ONLY a JSON array:
[{{"move_id": "M1", "better": "A"}}, ...]   // "A", "B", or "equal" """
