"""Layer D grader prompts.

Kept in the layer_d package rather than shared/prompts.py on purpose: shared/prompts.py
holds the rubric-era ego_trap prompts, and this package must be deletable/auditable as
one unit while both generations coexist.

Prompt design rules, each one paid for:
  * BINARY per-move questions (CheckEval: binary atomic checks beat Likert on
    agreement). No 1-5 scales anywhere.
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
