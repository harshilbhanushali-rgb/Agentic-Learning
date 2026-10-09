"""The two Layer D graders: binary evidence-gated checks, and pairwise-vs-exemplar.

Both are built; tuning.yaml's layer_d.grader_arm selects which one production runs,
and the C2 head-to-head (pre-registered) chooses the value. Everything except the
actual chat call is a pure function, so the whole verdict path is unit-tested with
hand-built responses and the harness can replay persisted responses for free.

Verdict vocabulary -- FOUR states, not three, and the fourth is the point:
    hit / partial / miss   -- scored outcomes; only these count as an attempt
    unscored               -- the INSTRUMENT failed (id missing from the response,
                              quote failed verification, swap-inconsistent verdict).
The old pipeline normalized every parse failure to "miss", so output truncation
MANUFACTURED coaching failures. Unscored rows are counted, reported, and excluded
from every rate.

The chat callable contract: chat(prompt) -> parsed JSON (list or dict). Production
wires shared.gateway.GatewayClient.chat_json with no_cache=True; tests inject fakes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from layer_d.prompts import PROMPT_CHECKS_BATCH, PROMPT_PAIRWISE, PROMPT_SAY_BATCH
from layer_d.verify_quotes import verify_quote

# One request covers this many moments of the SAME playbook (the criteria block is
# shared, which is what keeps the prompt linear rather than quadratic -- the old
# pipeline's 77% token reduction came from exactly this regrouping). Output length is
# the binding constraint (truncation is silent), so this stays small. Module constant,
# not a tuning key: request packing is not a property of the data.
CHECKS_BATCH_SIZE = 6

VALID_VERDICTS = ("hit", "partial", "miss", "unscored")


@dataclass(frozen=True)
class MoveVerdict:
    move_id: str
    verdict: str                    # hit | partial | miss | unscored
    quote: str = ""                 # verified verbatim evidence ("" unless hit)
    quote_score: float = 0.0
    reason: str = ""                # why unscored ("" otherwise)


@dataclass
class GradedMoment:
    moment_id: str
    verdicts: list[MoveVerdict] = field(default_factory=list)


def _as_entry_list(raw: Any) -> list:
    """Tolerate the one benign shape drift a JSON-forced model produces: the
    requested array wrapped in a single-key object ({"results": [...]}). The
    gateway sends response_format json_object, and some models satisfy it by
    wrapping. Without this, a whole PAID batch parses to zero entries and every
    verdict lands unscored (flagged by the first blind audit, 2026-08-23).
    Anything that is not a list, or a dict containing exactly one list, stays [] --
    guessing further would credit structure the model never produced."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        lists = [v for v in raw.values() if isinstance(v, list)]
        if len(lists) == 1:
            return lists[0]
    return []


def moves_block(moves: list[dict]) -> str:
    """The shared criteria block. `moves` carry move_id (M1..Mn, positional --
    storage.assign_move_ids), name, criterion."""
    return "\n".join(
        f"- {m['move_id']} ({m.get('name', '')}): {m.get('criterion', '')}"
        for m in moves
    )


# ------------------------------------------------------------------ checks arm

def build_checks_prompt(
    scenario_key: str,
    situation_signature: str,
    moves: list[dict],
    moments: list[dict],            # each: {moment_id, trigger_text, response_text}
) -> str:
    block = "\n\n".join(
        f"MOMENT {m['moment_id']}\nCLIENT: {m['trigger_text']}\nREP REPLY: {m['response_text']}"
        for m in moments
    )
    return PROMPT_CHECKS_BATCH.format(
        scenario_key=scenario_key,
        situation_signature=situation_signature,
        moves_block=moves_block(moves),
        moments_block=block,
    )


def parse_checks_response(
    raw: Any,
    moments: list[dict],
    moves: list[dict],
    min_overlap: float,
) -> list[GradedMoment]:
    """Normalize one checks response against what was ASKED, not what came back.

    Every (moment, move) pair the prompt asked about gets exactly one MoveVerdict:
      * performed="full" + quote verified against THAT moment's response_text -> hit
      * performed="partial" + quote verified -> partial. Added 2026-08-24 after the
        C3 pre/post proved the binary contract structurally mismatched to arc-level
        moves (expert base rate 3-6%); conjunctive gradability criteria make
        half-credit meaningful, and the one grading change that ever produced a real
        measured gain (the criteria-rewrite A/B, x1.6) did it through partials.
      * full/partial with quote missing/unverifiable -> unscored (quote_unverified);
        the judge's claim is untrustworthy, and it must not be converted into a
        miss either -- that would punish the rep for the instrument's failure
      * performed="no" -> miss (absence needs no quote; you cannot quote a silence)
      * anything else (id missing, malformed, legacy booleans) -> unscored
    """
    move_ids = [m["move_id"] for m in moves]
    by_moment: dict[str, dict[str, dict]] = {}
    for entry in _as_entry_list(raw):
        if not isinstance(entry, dict):
            continue
        mid = str(entry.get("moment_id", ""))
        verdicts = entry.get("verdicts")
        if not isinstance(verdicts, list):
            continue
        slot = by_moment.setdefault(mid, {})
        for v in verdicts:
            if isinstance(v, dict) and v.get("move_id"):
                slot[str(v["move_id"])] = v

    graded: list[GradedMoment] = []
    for moment in moments:
        mid = str(moment["moment_id"])
        response_text = moment.get("response_text", "")
        out = GradedMoment(moment_id=mid)
        returned = by_moment.get(mid, {})
        for move_id in move_ids:
            v = returned.get(move_id)
            performed = v.get("performed") if v is not None else None
            if isinstance(performed, str):
                performed = performed.strip().lower()
            if performed not in ("full", "partial", "no"):
                out.verdicts.append(MoveVerdict(
                    move_id, "unscored", reason="missing_from_response"))
                continue
            if performed == "no":
                out.verdicts.append(MoveVerdict(move_id, "miss"))
                continue
            check = verify_quote(str(v.get("quote") or ""), response_text, min_overlap)
            if check.verified:
                out.verdicts.append(MoveVerdict(
                    move_id, "hit" if performed == "full" else "partial",
                    quote=str(v.get("quote", "")).strip(),
                    quote_score=round(check.score, 4)))
            else:
                out.verdicts.append(MoveVerdict(
                    move_id, "unscored", quote_score=round(check.score, 4),
                    reason="quote_unverified"))
        graded.append(out)
    return graded


def grade_checks_batch(
    chat: Callable[[str], Any],
    scenario_key: str,
    situation_signature: str,
    moves: list[dict],
    moments: list[dict],
    min_overlap: float,
) -> list[GradedMoment]:
    """One request per CHECKS_BATCH_SIZE moments of one playbook. A raised chat error
    propagates -- the caller must NOT checkpoint the transcript (the old pipeline
    marked failed batches done and lost their signals permanently)."""
    graded: list[GradedMoment] = []
    for i in range(0, len(moments), CHECKS_BATCH_SIZE):
        batch = moments[i:i + CHECKS_BATCH_SIZE]
        prompt = build_checks_prompt(scenario_key, situation_signature, moves, batch)
        raw = chat(prompt)
        graded.extend(parse_checks_response(raw, batch, moves, min_overlap))
    return graded


# --------------------------------------------------------------------- say arm

def say_moves_block(moves: list[dict]) -> str:
    """Criteria block for SAY moves: each carries its benchmark example quote as
    the specificity anchor (BARS-style -- the level is defined by a concrete
    example, not an adjective). Moves come from move_classes.say_moves."""
    lines = []
    for m in moves:
        lines.append(f"- {m['move_id']} ({m.get('name', '')}): {m.get('criterion', '')}")
        if m.get("anchor"):
            lines.append(f'  WHAT "SPECIFIC" LOOKS LIKE (top performer, real call): '
                         f'"{m["anchor"]}"')
    return "\n".join(lines)


def build_say_prompt(
    scenario_key: str,
    situation_signature: str,
    moves: list[dict],              # SAY-routed specs: {move_id, name, criterion, anchor}
    moments: list[dict],            # each: {moment_id, trigger_text, response_text}
) -> str:
    block = "\n\n".join(
        f"MOMENT {m['moment_id']}\nCLIENT: {m['trigger_text']}\nREP REPLY: {m['response_text']}"
        for m in moments
    )
    return PROMPT_SAY_BATCH.format(
        scenario_key=scenario_key,
        situation_signature=situation_signature,
        moves_block=say_moves_block(moves),
        moments_block=block,
    )


def parse_say_response(
    raw: Any,
    moments: list[dict],
    moves: list[dict],
    min_overlap: float,
) -> list[GradedMoment]:
    """Normalize one say response against what was ASKED, not what came back.

    Verdict mapping (docs/findings/layer-d-say-arm.md §2):
      * raised="specific" + quote verified against THAT moment's reply -> hit
      * raised="generic"  + quote verified -> partial
      * specific/generic with a missing/unverifiable quote -> unscored
        (quote_unverified -- the judge's claim is untrustworthy, and it must not
        become a miss either: that would punish the rep for the instrument)
      * raised="no" -> miss (absence needs no quote)
      * anything else (id missing, malformed) -> unscored
    Same skeleton as parse_checks_response on purpose: the quote gate and the
    asked-not-answered normalization are the load-bearing parts.
    """
    move_ids = [m["move_id"] for m in moves]
    by_moment: dict[str, dict[str, dict]] = {}
    for entry in _as_entry_list(raw):
        if not isinstance(entry, dict):
            continue
        mid = str(entry.get("moment_id", ""))
        verdicts = entry.get("verdicts")
        if not isinstance(verdicts, list):
            continue
        slot = by_moment.setdefault(mid, {})
        for v in verdicts:
            if isinstance(v, dict) and v.get("move_id"):
                slot[str(v["move_id"])] = v

    graded: list[GradedMoment] = []
    for moment in moments:
        mid = str(moment["moment_id"])
        response_text = moment.get("response_text", "")
        out = GradedMoment(moment_id=mid)
        returned = by_moment.get(mid, {})
        for move_id in move_ids:
            v = returned.get(move_id)
            raised = v.get("raised") if v is not None else None
            if isinstance(raised, str):
                raised = raised.strip().lower()
            if raised not in ("specific", "generic", "no"):
                out.verdicts.append(MoveVerdict(
                    move_id, "unscored", reason="missing_from_response"))
                continue
            if raised == "no":
                out.verdicts.append(MoveVerdict(move_id, "miss"))
                continue
            check = verify_quote(str(v.get("quote") or ""), response_text, min_overlap)
            if check.verified:
                out.verdicts.append(MoveVerdict(
                    move_id, "hit" if raised == "specific" else "partial",
                    quote=str(v.get("quote", "")).strip(),
                    quote_score=round(check.score, 4)))
            else:
                out.verdicts.append(MoveVerdict(
                    move_id, "unscored", quote_score=round(check.score, 4),
                    reason="quote_unverified"))
        graded.append(out)
    return graded


def grade_say_batch(
    chat: Callable[[str], Any],
    scenario_key: str,
    situation_signature: str,
    moves: list[dict],
    moments: list[dict],
    min_overlap: float,
) -> list[GradedMoment]:
    """One request per CHECKS_BATCH_SIZE moments of one playbook's SAY moves. A
    raised chat error propagates -- the caller must NOT checkpoint the transcript."""
    graded: list[GradedMoment] = []
    for i in range(0, len(moments), CHECKS_BATCH_SIZE):
        batch = moments[i:i + CHECKS_BATCH_SIZE]
        prompt = build_say_prompt(scenario_key, situation_signature, moves, batch)
        raw = chat(prompt)
        graded.extend(parse_say_response(raw, batch, moves, min_overlap))
    return graded


# ---------------------------------------------------------------- pairwise arm

def build_pairwise_prompt(
    scenario_key: str,
    situation_signature: str,
    moves: list[dict],
    *,
    trigger_a: str, reply_a: str,
    trigger_b: str, reply_b: str,
) -> str:
    return PROMPT_PAIRWISE.format(
        scenario_key=scenario_key,
        situation_signature=situation_signature,
        moves_block=moves_block(moves),
        trigger_a=trigger_a, reply_a=reply_a,
        trigger_b=trigger_b, reply_b=reply_b,
    )


def parse_pairwise_response(raw: Any, moves: list[dict]) -> dict[str, str]:
    """{move_id: "A"|"B"|"equal"}; anything malformed or missing is simply absent,
    and the swap merge below turns absence into unscored."""
    out: dict[str, str] = {}
    valid = {"A", "B", "equal"}
    for entry in _as_entry_list(raw):
        if not isinstance(entry, dict):
            continue
        move_id = str(entry.get("move_id", ""))
        better = entry.get("better")
        if isinstance(better, str):
            better = better.strip()
            if better in ("a", "b"):
                better = better.upper()
        if move_id and better in valid:
            out[move_id] = better
    return {m["move_id"]: out[m["move_id"]] for m in moves if m["move_id"] in out}


def merge_swapped(
    csm_first: dict[str, str],      # verdicts with the CSM as reply A
    csm_second: dict[str, str],     # verdicts with the CSM as reply B
    moves: list[dict],
) -> list[MoveVerdict]:
    """Position-bias control: keep a verdict only when both orderings agree.

    JudgeLM-style swap augmentation. After unswapping, csm_first's "A" and
    csm_second's "B" both mean "the CSM performed it better".
      csm wins both orders  -> hit      (performed at least as well as the exemplar)
      equal both orders     -> partial
      loses both orders     -> miss
      any disagreement      -> unscored (swap_inconsistent)
      missing either order  -> unscored (missing_from_response)
    """
    def unswap(verdict: str, csm_was: str) -> str:
        if verdict == "equal":
            return "equal"
        return "csm" if verdict == csm_was else "exemplar"

    out: list[MoveVerdict] = []
    for m in moves:
        move_id = m["move_id"]
        v1, v2 = csm_first.get(move_id), csm_second.get(move_id)
        if v1 is None or v2 is None:
            out.append(MoveVerdict(move_id, "unscored", reason="missing_from_response"))
            continue
        u1, u2 = unswap(v1, "A"), unswap(v2, "B")
        if u1 != u2:
            out.append(MoveVerdict(move_id, "unscored", reason="swap_inconsistent"))
        elif u1 == "csm":
            out.append(MoveVerdict(move_id, "hit"))
        elif u1 == "equal":
            out.append(MoveVerdict(move_id, "partial"))
        else:
            out.append(MoveVerdict(move_id, "miss"))
    return out


def single_order_verdicts(
    picks: dict[str, str], moves: list[dict], csm_side: str
) -> list[MoveVerdict]:
    """One-order verdict mapping: the pick relative to which side the CSM took.
    No consistency filter -- callers MUST randomize csm_side per moment so residual
    position bias cancels in aggregates instead of accumulating (measured 2026-08-24:
    the two orders agree on 95.2% of verdicts (600/630, C2) and 96.3% (C4), so the
    swap's per-verdict filter buys ~5% cleanliness for 2x cost; the operator chose
    single-order + randomized sides for production)."""
    out: list[MoveVerdict] = []
    for m in moves:
        pick = picks.get(m["move_id"])
        if pick is None:
            out.append(MoveVerdict(m["move_id"], "unscored",
                                   reason="missing_from_response"))
        elif pick == "equal":
            out.append(MoveVerdict(m["move_id"], "partial"))
        elif pick == csm_side:
            out.append(MoveVerdict(m["move_id"], "hit"))
        else:
            out.append(MoveVerdict(m["move_id"], "miss"))
    return out


def grade_pairwise(
    chat: Callable[[str], Any],
    scenario_key: str,
    situation_signature: str,
    moves: list[dict],
    moment: dict,                   # {moment_id, trigger_text, response_text}
    exemplar: dict,                 # {trigger_text, response_text} -- a Naren pair
    *,
    swap: bool = True,
    csm_side: str = "A",            # single-order only: which side the CSM takes
) -> GradedMoment:
    """swap=True: two requests (both orderings), verdicts kept only when consistent
    -- the C2/C4-validated instrument. swap=False: ONE request with the CSM on
    csm_side (callers randomize the side per moment); half the cost, ~5% of
    verdicts carry unfiltered position noise that cancels under randomization."""
    if not swap and csm_side not in ("A", "B"):
        raise ValueError(f"csm_side must be 'A' or 'B', got {csm_side!r}")

    def prompt(csm_first: bool) -> str:
        a, b = (moment, exemplar) if csm_first else (exemplar, moment)
        return build_pairwise_prompt(
            scenario_key, situation_signature, moves,
            trigger_a=a["trigger_text"], reply_a=a["response_text"],
            trigger_b=b["trigger_text"], reply_b=b["response_text"])

    if swap:
        first = parse_pairwise_response(chat(prompt(csm_first=True)), moves)
        second = parse_pairwise_response(chat(prompt(csm_first=False)), moves)
        return GradedMoment(
            moment_id=str(moment["moment_id"]),
            verdicts=merge_swapped(first, second, moves),
        )
    picks = parse_pairwise_response(chat(prompt(csm_first=(csm_side == "A"))), moves)
    return GradedMoment(
        moment_id=str(moment["moment_id"]),
        verdicts=single_order_verdicts(picks, moves, csm_side),
    )


# ------------------------------------------------------------- k-run consensus

def aggregate_runs(runs: list[list[MoveVerdict]], moves: list[dict]) -> list[MoveVerdict]:
    """Majority verdict per move across k independent runs of the SAME grading.

    Only scored verdicts vote; a strict majority of the scored votes is required
    (Rating Roulette: single-run LLM verdicts have low test-retest reliability;
    The Stability Trap: consensus over repeats is the remedy). No majority -> unscored
    (run_disagreement). k=1 degenerates to the single run, verbatim, so production at
    grader_k_runs=1 costs nothing extra.
    """
    if len(runs) == 1:
        return runs[0]
    by_move: dict[str, list[MoveVerdict]] = {}
    for run in runs:
        for v in run:
            by_move.setdefault(v.move_id, []).append(v)
    out: list[MoveVerdict] = []
    for m in moves:
        votes = by_move.get(m["move_id"], [])
        scored = [v for v in votes if v.verdict != "unscored"]
        if not scored:
            out.append(MoveVerdict(m["move_id"], "unscored", reason="all_runs_unscored"))
            continue
        counts: dict[str, int] = {}
        for v in scored:
            counts[v.verdict] = counts.get(v.verdict, 0) + 1
        top_verdict, top_n = max(counts.items(), key=lambda kv: kv[1])
        if top_n * 2 <= len(scored):
            out.append(MoveVerdict(m["move_id"], "unscored", reason="run_disagreement"))
            continue
        winner = next(v for v in scored if v.verdict == top_verdict)
        out.append(winner)
    return out
