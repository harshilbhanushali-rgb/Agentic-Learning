"""Client-move segmentation -- the production fix for Layer D DEFECT 1.

The old pipeline graded whichever turn happened to be LAST in a run of client turns,
so 98.6% of its "missed signals" were segmentation artifacts (2,449 of 2,484 'none'
outcomes were simply followed by another client turn) and 177 real questions were
discarded because a filler turn spoke last.

The rule here was derived from data, not taste (PROBLEMS_AND_FIXES.md, the anchor
probe over 3,247 answered exchanges): group a block's turns BY SPEAKER, never across
speakers -- within one speaker's run the reply attaches at chance at every block
size, across speakers it tracks the last turn.

Arms, from calibration/trial_client_move_arms.py (its client_blocks/last_speaker_move
are re-homed here verbatim; production must not import calibration):

  today  the block's last turn (the old rule; kept for A/B and rollback)
  e      arm D applied ONLY where today's rule rejects: stitch the last speaker's
         turns whose OWN best match is coachable, and admit if the stitched text is.
         Measured: +81 scored exchanges, 0 lost (arm D alone lost 9; the per-item
         filters of arms B/C lost up to 156 -- the ninth consecutive failure of a
         per-item threshold filter in this project).

Pure: the admit decision is a callable the caller supplies, so this module never
embeds, never reads tuning, and tests drive it with hand-built verdicts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ego_trap.transcript_parser import EgoTrapRole, EgoTrapTurn

ARMS = ("today", "e")

# admit(text) -> the kept scenario keys, or None for "not a signal" (a sink won).
AdmitFn = Callable[[str], "list[str] | None"]


@dataclass(frozen=True)
class MoveSignal:
    """One admitted client move: the unit a moment is built from."""
    trigger_text: str
    scenario_keys: list[str]        # from admit(); [0] is the match
    signal_turn_index: int          # the block's LAST turn -- the reply anchor
    via: str                        # "last_turn" | "stitched"
    block_indices: list[int]        # every turn index in the client block


def client_blocks(turns: list[EgoTrapTurn]) -> list[list[EgoTrapTurn]]:
    """Maximal runs of consecutive CLIENT turns. The boundary is a Joveo speaker."""
    out: list[list[EgoTrapTurn]] = []
    cur: list[EgoTrapTurn] = []
    for t in turns:
        if t.role == EgoTrapRole.CLIENT:
            cur.append(t)
        else:
            if cur:
                out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def last_speaker_move(block: list[EgoTrapTurn]) -> list[EgoTrapTurn]:
    """All turns in the block spoken by whoever spoke LAST, in order.

    By speaker, not by consecutive run: the anchor probe validated exactly this
    grouping (see module docstring).
    """
    last = block[-1].speaker_raw
    return [t for t in block if t.speaker_raw == last]


def stitch_candidates(block: list[EgoTrapTurn], admit: AdmitFn) -> str:
    """Arm D's trigger text: the last speaker's turns whose OWN best match is
    coachable, joined in order. The junk-bin rule prunes filler ("sounds good",
    "one sec") without a threshold -- a turn is dropped only when the taxonomy
    itself files it as a sink."""
    move = last_speaker_move(block)
    kept = [t.text for t in move if admit(t.text) is not None]
    return " ".join(kept)


def segment_moves(
    turns: list[EgoTrapTurn],
    arm: str,
    admit: AdmitFn,
) -> list[MoveSignal]:
    """Every admitted client move in a transcript, under one segmentation arm.

    A block's reply anchor is its LAST turn regardless of which text was admitted:
    the response window starts where the client stopped talking, and that is a fact
    about the transcript, not about the arm.

    Unanswered final blocks are still emitted when admitted -- the caller reads
    response_outcome off the anchor index and decides what an unanswered signal
    means. Segmentation only decides what the trigger IS.
    """
    if arm not in ARMS:
        raise ValueError(f"unknown segmentation arm: {arm!r} (expected one of {ARMS})")

    signals: list[MoveSignal] = []
    for block in client_blocks(turns):
        anchor = block[-1].index
        indices = [t.index for t in block]

        kept = admit(block[-1].text)
        if kept is not None:
            signals.append(MoveSignal(
                trigger_text=block[-1].text,
                scenario_keys=kept,
                signal_turn_index=anchor,
                via="last_turn",
                block_indices=indices,
            ))
            continue

        if arm == "today":
            continue

        stitched = stitch_candidates(block, admit)
        if not stitched or stitched == block[-1].text:
            continue                    # nothing recoverable beyond what just failed
        kept = admit(stitched)
        if kept is None:
            continue
        signals.append(MoveSignal(
            trigger_text=stitched,
            scenario_keys=kept,
            signal_turn_index=anchor,
            via="stitched",
            block_indices=indices,
        ))
    return signals
