"""layer_d/segmentation.py -- the arm rules, driven by hand-built admit verdicts.

Same testing philosophy as test_layer_b_assignment.py: the admit callable is
hand-built, so these tests pin the RULE, not the embedding model.
"""
import pytest

from ego_trap.transcript_parser import EgoTrapRole, EgoTrapTurn
from layer_d.segmentation import (
    MoveSignal, client_blocks, last_speaker_move, segment_moves, stitch_candidates,
)


def t(i, role, text, speaker=None):
    return EgoTrapTurn(index=i, speaker_raw=speaker or role.value, role=role,
                       text=text, call_id="call1")


C, S, J = EgoTrapRole.CLIENT, EgoTrapRole.CSM, EgoTrapRole.OTHER_JOVEO


def admit_map(admitted: dict[str, list[str]]):
    """admit() driven by an explicit table; anything unlisted is rejected."""
    return lambda text: admitted.get(text)


# --------------------------------------------------------------------- blocks

def test_client_blocks_split_on_any_joveo_speaker():
    turns = [t(0, C, "a"), t(1, C, "b"), t(2, S, "reply"), t(3, C, "c"), t(4, J, "x")]
    blocks = client_blocks(turns)
    assert [[x.text for x in b] for b in blocks] == [["a", "b"], ["c"]]


def test_trailing_client_block_is_kept():
    turns = [t(0, S, "hi"), t(1, C, "bye")]
    assert [[x.text for x in b] for b in client_blocks(turns)] == [["bye"]]


def test_last_speaker_move_groups_by_speaker_not_by_run():
    # Alexa speaks, Sam interjects, Alexa resumes: Alexa spoke last, so her move is
    # BOTH her turns -- the by-speaker rule the anchor probe validated.
    block = [t(0, C, "q1", "Alexa"), t(1, C, "hmm", "Sam"), t(2, C, "q2", "Alexa")]
    assert [x.text for x in last_speaker_move(block)] == ["q1", "q2"]


# ----------------------------------------------------------------- arm: today

def test_arm_today_admits_only_the_last_turn():
    turns = [t(0, C, "real question"), t(1, C, "sounds good"), t(2, S, "reply")]
    admit = admit_map({"real question": ["scen_a"]})
    # last turn "sounds good" rejected -> arm today produces nothing
    assert segment_moves(turns, "today", admit) == []


def test_arm_today_signal_carries_anchor_and_via():
    turns = [t(0, C, "real question"), t(1, S, "reply")]
    admit = admit_map({"real question": ["scen_a"]})
    [sig] = segment_moves(turns, "today", admit)
    assert sig == MoveSignal(
        trigger_text="real question", scenario_keys=["scen_a"],
        signal_turn_index=0, via="last_turn", block_indices=[0],
    )


# --------------------------------------------------------------------- arm: e

def test_arm_e_recovers_a_block_the_last_turn_rule_rejects():
    turns = [t(0, C, "real question", "Alexa"), t(1, C, "sounds good", "Alexa"),
             t(2, S, "reply")]
    admit = admit_map({
        "real question": ["scen_a"],
        "real question sounds good": ["scen_a"],   # stitched admits too
    })
    [sig] = segment_moves(turns, "e", admit)
    # "sounds good" is dropped by the junk-bin rule; only the admitted turn stitches
    assert sig.trigger_text == "real question"
    assert sig.via == "stitched"
    assert sig.signal_turn_index == 1          # anchor stays the block's LAST turn


def test_arm_e_never_overrides_an_admitted_last_turn():
    turns = [t(0, C, "filler", "Alexa"), t(1, C, "real question", "Alexa"), t(2, S, "r")]
    admit = admit_map({"real question": ["scen_a"], "filler": ["scen_b"]})
    [sig] = segment_moves(turns, "e", admit)
    assert sig.via == "last_turn" and sig.trigger_text == "real question"


def test_arm_e_rejects_when_stitched_text_is_also_a_sink():
    turns = [t(0, C, "blah", "Alexa"), t(1, C, "more blah", "Alexa"), t(2, S, "r")]
    assert segment_moves(turns, "e", admit_map({})) == []


def test_arm_e_only_stitches_the_last_speakers_turns():
    turns = [t(0, C, "sam question", "Sam"), t(1, C, "alexa filler", "Alexa"), t(2, S, "r")]
    admit = admit_map({"sam question": ["scen_a"]})
    # Alexa spoke last; her only turn is rejected, so Sam's admitted turn must NOT
    # leak into the stitched move (across-speaker stitching is the refuted arm B).
    assert segment_moves(turns, "e", admit) == []


def test_stitch_candidates_preserves_order():
    block = [t(0, C, "q1", "A"), t(1, C, "junk", "A"), t(2, C, "q2", "A")]
    admit = admit_map({"q1": ["s"], "q2": ["s"]})
    assert stitch_candidates(block, admit) == "q1 q2"


def test_unknown_arm_raises():
    with pytest.raises(ValueError, match="unknown segmentation arm"):
        segment_moves([], "b", admit_map({}))


def test_unanswered_final_block_is_still_emitted():
    # Segmentation only decides the trigger; the caller reads response_outcome.
    turns = [t(0, S, "hi"), t(1, C, "real question")]
    [sig] = segment_moves(turns, "today", admit_map({"real question": ["s"]}))
    assert sig.signal_turn_index == 1
