from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import json
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


def load_roster(txt_path: str) -> list[dict] | None:
    """Load the {stem}.speakers.json sidecar (see backfill_speaker_roster.py) next to
    a transcript, if one exists. Each entry has name/email/is_rep from Avoma's own
    calendar-derived classification -- authoritative, unlike JOVEO_SPEAKER_NAMES."""
    roster_path = Path(txt_path).with_suffix("").with_suffix(".speakers.json")
    if not roster_path.exists():
        return None
    data = json.loads(roster_path.read_text(encoding="utf-8"))
    return data.get("speakers") or None


def _match_roster_entry(speaker_raw: str, roster: list[dict]) -> dict | None:
    s = speaker_raw.strip().lower()
    for entry in roster:
        name_l = entry["name"].strip().lower()
        if s == name_l or name_l.startswith(s) or s.startswith(name_l):
            return entry
    return None


def _classify(
    speaker_raw: str,
    joveo_lower: frozenset,
    naren_name_lower: str,
    roster: list[dict] | None = None,
) -> SpeakerRole:
    s = speaker_raw.strip().lower()
    if roster:
        entry = _match_roster_entry(speaker_raw, roster)
        if entry is not None:
            name_l = entry["name"].strip().lower()
            if s == name_l and (s == naren_name_lower or naren_name_lower.startswith(s) or s.startswith(naren_name_lower)):
                return SpeakerRole.NAREN
            return SpeakerRole.JOVEO_OTHER if entry.get("is_rep") else SpeakerRole.CLIENT
        # Speaker not on this meeting's roster (e.g. sidecar missing/stale) -- fall
        # through to the name-list heuristic below rather than guessing CLIENT blind.

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
    roster: list[dict] | None = None,
) -> list[Turn]:
    """Parse a .txt transcript into a list of Turn objects.

    If `roster` is given (see load_roster()), speaker roles are resolved from
    Avoma's own per-meeting is_rep/email data first; the joveo_speakers_lower /
    naren_name_lower name-list heuristic is only a fallback for speakers Avoma
    didn't report (or when no roster is available at all).
    """
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
        role = _classify(speaker_raw, joveo_speakers_lower, naren_name_lower, roster)
        turns.append(Turn(
            index=len(turns),
            speaker_raw=speaker_raw,
            role=role,
            text=utterance,
            call_id=call_id,
        ))

    return turns
