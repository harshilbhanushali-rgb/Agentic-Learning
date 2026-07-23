import pytest
from pathlib import Path
from preprocessing.transcript_parser import parse_transcript, SpeakerRole

JOVEO = frozenset(["naren shankar", "collin osburn"])
NAREN = "naren shankar"


def _txt(content: str, tmp_path: Path) -> str:
    p = tmp_path / "call_test.txt"
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_basic_roles(tmp_path):
    txt = _txt("Naren Shankar\nHere is my response.\n\nAnna\nI have a concern.\n\nCollin Osburn\nGood point.", tmp_path)
    turns = parse_transcript(txt, JOVEO, NAREN)
    assert len(turns) == 3
    assert turns[0].role == SpeakerRole.NAREN
    assert turns[1].role == SpeakerRole.CLIENT
    assert turns[2].role == SpeakerRole.JOVEO_OTHER


def test_call_id_is_filename_stem(tmp_path):
    txt = _txt("Naren Shankar\nHello.\n\nAnna\nHi.", tmp_path)
    turns = parse_transcript(txt, JOVEO, NAREN)
    assert turns[0].call_id == "call_test"


def test_empty_utterance_skipped(tmp_path):
    txt = _txt("Naren Shankar\n\nAnna\nActual utterance.", tmp_path)
    turns = parse_transcript(txt, JOVEO, NAREN)
    assert len(turns) == 1
    assert turns[0].role == SpeakerRole.CLIENT


def test_partial_name_joveo(tmp_path):
    txt = _txt("Collin\nInterjects here.\n\nAnna\nQuestion.", tmp_path)
    turns = parse_transcript(txt, JOVEO, NAREN)
    assert turns[0].role == SpeakerRole.JOVEO_OTHER


def test_crlf_line_endings(tmp_path):
    content = "Naren Shankar\r\nResponse text.\r\n\r\nAnna\r\nQuestion here."
    p = tmp_path / "call_crlf.txt"
    p.write_bytes(content.encode("utf-8"))
    turns = parse_transcript(str(p), JOVEO, NAREN)
    assert len(turns) == 2
    assert turns[0].text == "Response text."


def test_turn_indices_sequential(tmp_path):
    txt = _txt("Naren Shankar\nA.\n\nAnna\nB.\n\nNaren Shankar\nC.", tmp_path)
    turns = parse_transcript(txt, JOVEO, NAREN)
    assert [t.index for t in turns] == [0, 1, 2]
