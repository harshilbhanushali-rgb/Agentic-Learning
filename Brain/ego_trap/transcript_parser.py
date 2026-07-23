from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re


class EgoTrapRole(Enum):
    CLIENT = "CLIENT"
    CSM = "CSM"
    OTHER_JOVEO = "OTHER_JOVEO"


@dataclass
class EgoTrapTurn:
    index: int
    speaker_raw: str
    role: EgoTrapRole
    text: str
    call_id: str


def _classify(speaker_raw: str, csm_name_lower: str, joveo_lower: frozenset) -> EgoTrapRole:
    s = speaker_raw.strip().lower()
    if s == csm_name_lower or csm_name_lower.startswith(s) or s.startswith(csm_name_lower):
        return EgoTrapRole.CSM
    for jname in joveo_lower:
        if s == jname or jname.startswith(s) or s.startswith(jname):
            return EgoTrapRole.OTHER_JOVEO
    return EgoTrapRole.CLIENT


def parse_transcript(
    path: str,
    csm_name_lower: str,
    joveo_speakers_lower: frozenset,
) -> list[EgoTrapTurn]:
    """Parse a transcript into EgoTrapTurns.

    Real call recordings have no per-line role tags or timestamps — same blank-line-separated
    "Name\\nUtterance" format as preprocessing.transcript_parser (Naren's brain). Role is
    determined the same way: csm_name_lower is *this call's* mapped CSM (from
    csm_recordings/mapping.csv) — matched first so the CSM is distinguished from any other
    Joveo person on the call; joveo_speakers_lower (config.joveo_speakers_lower, shared with
    Naren's pipeline) catches everyone else internal; anyone left is CLIENT.

    There are no timestamps in this data, so turn adjacency (index order) is the only signal
    for "did the CSM respond" — see transcript_parser.turns_until_next_client.
    """
    raw = Path(path).read_text(encoding="utf-8-sig")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    segments = re.split(r"\n{2,}", raw.strip())

    call_id = Path(path).stem
    turns: list[EgoTrapTurn] = []

    for seg in segments:
        lines = [l.strip() for l in seg.strip().splitlines()]
        lines = [l for l in lines if l]
        if not lines:
            continue
        speaker_raw = lines[0]
        utterance = " ".join(lines[1:]).strip()
        if not utterance:
            continue
        role = _classify(speaker_raw, csm_name_lower, joveo_speakers_lower)
        turns.append(EgoTrapTurn(
            index=len(turns),
            speaker_raw=speaker_raw,
            role=role,
            text=utterance,
            call_id=call_id,
        ))

    return turns


def turns_until_next_client(turns: list[EgoTrapTurn], start_index: int) -> list[EgoTrapTurn]:
    """All turns after start_index, stopping before the next CLIENT turn.

    Mirrors v1/layer_b.py's extract_pairs adjacency window — used in place of a time-based
    response window since these transcripts carry no timestamps.
    """
    result = []
    for t in turns[start_index + 1:]:
        if t.role == EgoTrapRole.CLIENT:
            break
        result.append(t)
    return result


def classify_response_outcome(turns: list[EgoTrapTurn], start_index: int) -> str:
    """Who addressed the CLIENT turn at start_index before the next CLIENT turn.

    Returns "csm" if the CSM responded, "other_joveo" if only a teammate did
    (the client's point was answered, just not by the CSM personally — a true
    Signal_Recognition_Failure should NOT fire on this), or "none" if nobody did.
    """
    following = turns_until_next_client(turns, start_index)
    if any(t.role == EgoTrapRole.CSM for t in following):
        return "csm"
    if any(t.role == EgoTrapRole.OTHER_JOVEO for t in following):
        return "other_joveo"
    return "none"
