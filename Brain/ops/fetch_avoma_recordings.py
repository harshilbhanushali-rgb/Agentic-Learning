"""
Fetch call transcripts from Avoma as plain Name/Utterance .txt files
(blank-line-separated "SpeakerName\\nUtterance" turns, no timestamps or role tags --
the format both preprocessing/transcript_parser.py and ego_trap/transcript_parser.py
expect).

TWO DESTINATIONS, AND THEY MUST NOT BE MIXED:

  recordings/      Naren's KB corpus. Layers A/B/C cluster these into the scenario
                   taxonomy and rubrics -- the "answer key".
  csm_recordings/  CSM calls that Layer D (Ego Trap) SCORES against that answer key.

Dropping a CSM call into recordings/ would put the person being evaluated into the
corpus that defines correct behaviour, and would also change the main pipeline's
run_id (a sha1 of the sorted transcript stems), silently invalidating every Layer A/B/C
checkpoint and forcing a full re-run. --csm-id is therefore REQUIRED for a
csm_recordings/ fetch and REFUSED for a recordings/ fetch.

Usage (from Brain/ with venv active):
    # Naren's KB corpus (unchanged default behaviour)
    python ops/fetch_avoma_recordings.py
    python ops/fetch_avoma_recordings.py --from-date 2026-04-01 --to-date 2026-07-23

    # A CSM's calls for gap analysis -- also appends to csm_recordings/mapping.csv,
    # without which ego_trap/pipeline.py silently skips every transcript.
    python ops/fetch_avoma_recordings.py \\
        --attendee-email madhumita.katta@joveo.com \\
        --csm-id CSM_MADHUMITA --csm-name "Madhumita Katta" \\
        --out-dir csm_recordings --from-date 2026-05-10

    # See who is actually on the meetings without writing anything
    python ops/fetch_avoma_recordings.py --list-attendees --from-date 2026-05-10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

AVOMA_BASE_URL = "https://api.avoma.com"
AVOMA_TIMEOUT = float(os.getenv("AVOMA_TIMEOUT", "30"))
BRAIN_DIR = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = BRAIN_DIR / "recordings"


def _joveo_speaker_names() -> set[str]:
    """The configured Joveo roster, lowercased, as ego_trap sees it."""
    return {
        n.strip().lower()
        for n in os.getenv("JOVEO_SPEAKER_NAMES", "").split(",")
        if n.strip()
    }


def _slug(text: str, limit: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:limit] or "call"


class AvomaSpeaker(BaseModel):
    email: str
    id: int
    is_rep: bool
    name: str


class AvomaTranscriptSegment(BaseModel):
    speaker_id: int
    timestamps: list[float]
    transcript: str


class AvomaTranscription(BaseModel):
    meeting_uuid: str
    speakers: list[AvomaSpeaker]
    transcript: list[AvomaTranscriptSegment]
    transcription_vtt_url: str
    uuid: str

    def to_plain_transcript(self) -> str:
        speaker_map = {s.id: s.name for s in self.speakers}
        lines: list[str] = []
        for segment in self.transcript:
            text = segment.transcript.strip()
            if not text:
                continue
            lines.append(speaker_map.get(segment.speaker_id, "Unknown Speaker"))
            lines.append(text)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


class AvomaMeeting(BaseModel):
    uuid: str
    subject: Optional[str] = None
    start_at: Optional[datetime] = None
    organizer_email: Optional[str] = None
    transcription_uuid: Optional[str] = None
    transcript_ready: Optional[bool] = None
    attendees: Optional[list[dict[str, Any]]] = None


class AvomaClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("AVOMA_API_KEY")
        if not self.api_key:
            raise ValueError("AVOMA_API_KEY environment variable is required")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.rate_limit_delay = 0.5
        self.last_request_time = 0.0
        self.semaphore = asyncio.Semaphore(5)

    async def _rate_limit(self) -> None:
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = time.time()

    async def _handle_429_retry(self, response_text: str) -> int:
        try:
            data = json.loads(response_text)
            detail = data.get("detail") or ""
            m = re.search(r"Expected available in (\d+) seconds", detail)
            if m:
                return int(m.group(1)) + 2
        except Exception:
            pass
        return 60

    async def get_meetings(
        self, from_date: str, to_date: str, attendee_emails: Optional[str] = None
    ) -> list[AvomaMeeting]:
        url = f"{AVOMA_BASE_URL}/v1/meetings/"
        params: Optional[dict[str, Any]] = {
            "page_size": 100,
            "from_date": from_date,
            "to_date": to_date,
            "o": "-start_at",
        }
        if attendee_emails:
            params["attendee_emails"] = attendee_emails
        meetings: list[AvomaMeeting] = []
        async with httpx.AsyncClient(timeout=AVOMA_TIMEOUT) as client:
            while url:
                data = await self._get_with_retry(client, url, params)
                if data is None:
                    break
                results = data.get("results", []) if isinstance(data, dict) else data
                meetings.extend(AvomaMeeting.model_validate(m) for m in results)
                url = data.get("next") if isinstance(data, dict) else None
                params = None  # `next` already carries the full query string
        return meetings

    async def _get_with_retry(
        self, client: httpx.AsyncClient, url: str, params: Optional[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        max_retries = 5
        retry_count = 0
        while retry_count <= max_retries:
            await self._rate_limit()
            response = await client.get(url, headers=self.headers, params=params)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:
                retry_count += 1
                wait_time = await self._handle_429_retry(response.text)
                logger.warning("Avoma rate limited, waiting %ss", wait_time)
                await asyncio.sleep(wait_time)
                continue
            response.raise_for_status()
        return None

    async def get_transcription(self, transcription_uuid: str) -> Optional[AvomaTranscription]:
        url = f"{AVOMA_BASE_URL}/v1/transcriptions/{transcription_uuid}/"
        async with self.semaphore:
            async with httpx.AsyncClient(timeout=AVOMA_TIMEOUT) as client:
                data = await self._get_with_retry(client, url, None)
        return AvomaTranscription.model_validate(data) if data else None


def _append_mapping(mapping_path: Path, rows: list[tuple[str, str, str]]) -> int:
    """Add `filename,csm_id,csm_name` rows, skipping any filename already present.

    Without a mapping row ego_trap/pipeline.py prints "has no CSM mapping -- skipping"
    and never scores the transcript, so a fetch that does not update this file looks
    like it worked and analyses nothing.
    """
    header = "filename,csm_id,csm_name"
    existing: set[str] = set()
    lines: list[str] = []
    if mapping_path.exists():
        # utf-8-sig: Windows editors save this file with a BOM, which would otherwise
        # end up inside the first column name.
        lines = mapping_path.read_text(encoding="utf-8-sig").splitlines()
        for line in lines[1:]:
            if line.strip():
                existing.add(line.split(",", 1)[0].strip())
    else:
        lines = [header]

    added = 0
    for filename, csm_id, csm_name in rows:
        if filename in existing:
            continue
        lines.append(f"{filename},{csm_id},{csm_name}")
        existing.add(filename)
        added += 1

    if added:
        # No BOM -- PowerShell's Set-Content -Encoding utf8 writes one and it breaks
        # readers downstream.
        mapping_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return added


def _audit_roster(speakers_seen: dict[str, str], csm_name: str | None) -> None:
    """Report Joveo speakers missing from JOVEO_SPEAKER_NAMES.

    This is the quietest correctness failure in the whole Layer D path.
    ego_trap/transcript_parser._classify defaults ANY unrecognised speaker to CLIENT, so
    a Joveo colleague who is not on the roster has their utterances treated as client
    signals -- manufacturing false positives -- and also corrupts
    classify_response_outcome, which decides whether the CSM answered or a teammate did.
    Avoma already tells us who is internal (is_rep / an @joveo.com address), so the
    check is free.
    """
    roster = _joveo_speaker_names()
    if csm_name:
        roster.add(csm_name.strip().lower())
    missing = sorted(
        f"{name}  <{email}>"
        for name, email in speakers_seen.items()
        if name.strip().lower() not in roster
    )
    if not missing:
        print("\n[roster] Every internal speaker in these transcripts is on JOVEO_SPEAKER_NAMES.")
        return
    print(
        f"\n[roster] WARNING: {len(missing)} internal (Joveo) speaker(s) are NOT in "
        f"JOVEO_SPEAKER_NAMES.\n"
        f"         They will be classified CLIENT, so their turns become fake 'client\n"
        f"         signals' and the CSM-vs-teammate response check breaks. Add them to\n"
        f"         JOVEO_SPEAKER_NAMES in Brain/.env before running the analysis:"
    )
    for entry in missing:
        print(f"           - {entry}")


async def run(
    from_date: str,
    to_date: str,
    attendee_email: str,
    overwrite: bool,
    out_dir: Path,
    csm_id: str | None,
    csm_name: str | None,
    mapping_path: Path | None,
    list_attendees: bool,
) -> None:
    client = AvomaClient()

    print(f"Fetching meetings from {from_date} to {to_date} for attendee {attendee_email}...")
    meetings = await client.get_meetings(from_date, to_date, attendee_emails=attendee_email)
    print(f"  {len(meetings)} meeting(s) returned")

    ready = [m for m in meetings if m.transcript_ready and m.transcription_uuid]
    print(f"  {len(ready)} with a ready transcript")

    if list_attendees or (not ready and meetings):
        seen = sorted({a.get("email", "<none>") for m in meetings for a in (m.attendees or [])})
        print(f"\n  attendee email values actually present ({len(seen)} distinct):")
        for email in seen[:60]:
            print(f"    {email}")
    if list_attendees:
        print("\n  --list-attendees: nothing written.")
        for m in ready[:40]:
            print(f"    {m.start_at}  ready={m.transcript_ready}  {m.subject}")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    written = skipped = skipped_no_speaker = 0
    new_rows: list[tuple[str, str, str]] = []
    speakers_seen: dict[str, str] = {}

    for meeting in ready:
        # Date-prefixed rather than a bare UUID: the stem becomes the call_id in
        # mapping.csv, gap_events and the checkpoint store, so it wants to be readable.
        # The uuid tail keeps it unique and traceable back to Avoma.
        stamp = meeting.start_at.strftime("%Y%m%d") if meeting.start_at else "nodate"
        stem = f"{stamp}_{_slug(meeting.subject)}_{meeting.uuid[:8]}"
        out_path = out_dir / f"{stem}.txt"
        if out_path.exists() and not overwrite:
            skipped += 1
            if csm_id:
                new_rows.append((out_path.name, csm_id, csm_name or ""))
            continue

        transcription = await client.get_transcription(meeting.transcription_uuid)
        if transcription is None:
            print(f"  [skip] {meeting.uuid} ({meeting.subject}) -- transcription fetch failed")
            continue

        if not any(s.email.lower() == attendee_email.lower() for s in transcription.speakers):
            skipped_no_speaker += 1
            print(f"  [skip] {meeting.subject} -- {attendee_email} never speaks")
            continue

        for s in transcription.speakers:
            if s.is_rep or (s.email or "").lower().endswith("@joveo.com"):
                speakers_seen[s.name] = s.email

        out_path.write_text(transcription.to_plain_transcript(), encoding="utf-8")
        written += 1
        if csm_id:
            new_rows.append((out_path.name, csm_id, csm_name or ""))
        print(f"  [ok] {meeting.start_at} {meeting.subject} -> {out_path.name}")

    print(
        f"\nDone. {written} written to {out_dir}, {skipped} already present, "
        f"{skipped_no_speaker} skipped ({attendee_email} never speaks) "
        "(use --overwrite to refetch)."
    )

    if csm_id and mapping_path is not None:
        added = _append_mapping(mapping_path, new_rows)
        print(f"[mapping] {added} new row(s) added to {mapping_path}.")
        if added:
            print(
                "[mapping] NOTE: the Ego Trap run_id is a sha1 of the sorted transcript\n"
                "          stems, so adding files mints a NEW run_id and every existing\n"
                "          transcript is re-processed. gap_events has no unique constraint\n"
                "          and milestone_performance.attempts increments on conflict, so run\n"
                "          `python ops/clear_ego_trap_data.py` first unless those tables are\n"
                "          already empty."
            )
        _audit_roster(speakers_seen, csm_name)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--from-date", default=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"))
    parser.add_argument("--to-date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--attendee-email", default="naren@joveo.com")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--out-dir", default="recordings",
        help="relative to Brain/. 'recordings' = Naren's KB corpus; "
             "'csm_recordings' = calls to be SCORED by Layer D (requires --csm-id).",
    )
    parser.add_argument("--csm-id", default=None,
                        help="e.g. CSM_MADHUMITA. Required for a csm_recordings/ fetch; "
                             "also appends to mapping.csv.")
    parser.add_argument("--csm-name", default=None,
                        help="display name; MUST match the speaker line in the transcript "
                             "exactly, or ego_trap cannot identify the CSM's own turns.")
    parser.add_argument("--mapping", default=None, help="defaults to <out-dir>/mapping.csv")
    parser.add_argument("--list-attendees", action="store_true",
                        help="print the attendee emails and meetings found, write nothing")
    args = parser.parse_args()

    out_dir = (BRAIN_DIR / args.out_dir).resolve()
    is_csm_dir = out_dir.name == "csm_recordings"

    # Guard both directions. Mixing the two corpora is silent and expensive: a CSM call
    # in recordings/ makes the person being evaluated part of the answer key AND changes
    # the main pipeline's run_id; a CSM call in csm_recordings/ with no --csm-id is
    # skipped by ego_trap without ever being scored.
    if is_csm_dir and not args.csm_id:
        parser.error(
            "--csm-id is required when --out-dir is csm_recordings: without a mapping.csv "
            "row, ego_trap/pipeline.py skips the transcript entirely."
        )
    if args.csm_id and not is_csm_dir:
        parser.error(
            f"--csm-id given but --out-dir is {out_dir.name!r}. CSM calls belong in "
            "csm_recordings/ -- putting them in recordings/ would add the person being "
            "evaluated to the corpus that defines correct behaviour, and would change the "
            "Layer A/B/C run_id, invalidating every checkpoint."
        )
    if args.csm_id and not args.csm_name:
        parser.error("--csm-name is required with --csm-id (it must match the transcript "
                     "speaker line for CSM turns to be recognised).")

    mapping_path = Path(args.mapping) if args.mapping else out_dir / "mapping.csv"

    asyncio.run(run(
        args.from_date, args.to_date, args.attendee_email, args.overwrite,
        out_dir, args.csm_id, args.csm_name, mapping_path, args.list_attendees,
    ))


if __name__ == "__main__":
    main()
