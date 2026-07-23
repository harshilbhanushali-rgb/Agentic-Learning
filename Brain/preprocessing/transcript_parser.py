from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re


class SpeakerRole(Enum):
    NAREN = "NAREN"
    JOVEO_OTHER = "JOVEO_OTHER"
    CLIENT = "CLIENT"


@dataclass
class Turn:
    index: int
    speaker_raw: str
    role: SpeakerRole
    text: str
    call_id: str


def _classify(speaker_raw: str, joveo_lower: frozenset, naren_name_lower: str) -> SpeakerRole:
    s = speaker_raw.strip().lower()
    if s == naren_name_lower or naren_name_lower.startswith(s) or s.startswith(naren_name_lower):
        return SpeakerRole.NAREN
    for jname in joveo_lower:
        if s == jname or jname.startswith(s) or s.startswith(jname):
            return SpeakerRole.JOVEO_OTHER
    return SpeakerRole.CLIENT


def parse_transcript(
    path: str,
    joveo_speakers_lower: frozenset,
    naren_name_lower: str,
) -> list[Turn]:
    """Parse a .txt transcript into a list of Turn objects."""
    raw = Path(path).read_text(encoding="utf-8-sig")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    segments = re.split(r"\n{2,}", raw.strip())

    call_id = Path(path).stem
    turns: list[Turn] = []

    for seg in segments:
        lines = [l.strip() for l in seg.strip().splitlines()]
        lines = [l for l in lines if l]
        if not lines:
            continue
        speaker_raw = lines[0]
        utterance = " ".join(lines[1:]).strip()
        if not utterance:
            continue
        role = _classify(speaker_raw, joveo_speakers_lower, naren_name_lower)
        turns.append(Turn(
            index=len(turns),
            speaker_raw=speaker_raw,
            role=role,
            text=utterance,
            call_id=call_id,
        ))

    return turns
