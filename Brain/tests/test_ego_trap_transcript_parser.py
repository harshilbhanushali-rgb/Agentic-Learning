from pathlib import Path
from ego_trap.transcript_parser import (
    EgoTrapRole,
    classify_response_outcome,
    parse_transcript,
    turns_until_next_client,
)

JOVEO = frozenset(["naren shankar", "collin osburn"])
CSM = "priya"


def _txt(content: str, tmp_path: Path) -> str:
    p = tmp_path / "call_test.txt"
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_basic_roles(tmp_path):
    txt = _txt(
        "Priya\nI understand that concern.\n\n"
        "Mary\nWe've had issues.\n\n"
        "Naren Shankar\nHere's context.\n",
        tmp_path,
    )
    turns = parse_transcript(txt, CSM, JOVEO)
    assert len(turns) == 3
    assert turns[0].role == EgoTrapRole.CSM
    assert turns[1].role == EgoTrapRole.CLIENT
    assert turns[2].role == EgoTrapRole.OTHER_JOVEO


def test_call_id_is_filename_stem(tmp_path):
    txt = _txt("Priya\nHello.\n\nAnna\nHi.", tmp_path)
    turns = parse_transcript(txt, CSM, JOVEO)
    assert turns[0].call_id == "call_test"


def test_empty_utterance_skipped(tmp_path):
    txt = _txt("Priya\n\nAnna\nActual utterance.", tmp_path)
    turns = parse_transcript(txt, CSM, JOVEO)
    assert len(turns) == 1
    assert turns[0].role == EgoTrapRole.CLIENT


def test_partial_name_csm_match(tmp_path):
    txt = _txt("Priya Sharma\nI understand.\n\nAnna\nQuestion.", tmp_path)
    turns = parse_transcript(txt, CSM, JOVEO)
    assert turns[0].role == EgoTrapRole.CSM


def test_crlf_line_endings(tmp_path):
    content = "Priya\r\nResponse text.\r\n\r\nAnna\r\nQuestion here."
    p = tmp_path / "call_crlf.txt"
    p.write_bytes(content.encode("utf-8"))
    turns = parse_transcript(str(p), CSM, JOVEO)
    assert len(turns) == 2
    assert turns[0].text == "Response text."


def test_turn_indices_sequential(tmp_path):
    txt = _txt("Priya\nA.\n\nAnna\nB.\n\nPriya\nC.", tmp_path)
    turns = parse_transcript(txt, CSM, JOVEO)
    assert [t.index for t in turns] == [0, 1, 2]


def test_turns_until_next_client_stops_at_next_client_turn(tmp_path):
    txt = _txt(
        "Anna\nSignal.\n\n"
        "Priya\nResponse part one.\n\n"
        "Naren Shankar\nInterjection.\n\n"
        "Anna\nNext client turn.\n",
        tmp_path,
    )
    turns = parse_transcript(txt, CSM, JOVEO)
    following = turns_until_next_client(turns, 0)
    assert [t.text for t in following] == ["Response part one.", "Interjection."]


def test_turns_until_next_client_no_csm_speaker_present(tmp_path):
    """If the mapped CSM never speaks in this transcript, no turn gets EgoTrapRole.CSM."""
    txt = _txt("Anna\nSignal.\n\nSomeone Else\nReply.\n", tmp_path)
    turns = parse_transcript(txt, CSM, JOVEO)
    assert all(t.role != EgoTrapRole.CSM for t in turns)


def test_classify_response_outcome_csm(tmp_path):
    txt = _txt("Anna\nSignal.\n\nPriya\nResponse.\n", tmp_path)
    turns = parse_transcript(txt, CSM, JOVEO)
    assert classify_response_outcome(turns, 0) == "csm"


def test_classify_response_outcome_other_joveo_not_conflated_with_none(tmp_path):
    """A teammate answering must classify as "other_joveo", not the true-silence "none"."""
    txt = _txt(
        "Anna\nSignal.\n\n"
        "Naren Shankar\nA teammate answers instead of the CSM.\n\n"
        "Anna\nNext client turn.\n",
        tmp_path,
    )
    turns = parse_transcript(txt, CSM, JOVEO)
    assert classify_response_outcome(turns, 0) == "other_joveo"


def test_classify_response_outcome_none(tmp_path):
    txt = _txt("Anna\nSignal.\n\nAnna\nNo one responded before this next client turn.\n", tmp_path)
    turns = parse_transcript(txt, CSM, JOVEO)
    assert classify_response_outcome(turns, 0) == "none"
