"""
Fetch Naren's call transcripts from Avoma and write them into recordings/ as
plain Name/Utterance .txt files for the v1/v2 pipeline (preprocessing/parser.py
expects this format: blank-line-separated "SpeakerName\\nUtterance" turns, no
timestamps or role tags).

Usage (from Brain/ with venv active):
    python fetch_avoma_recordings.py
    python fetch_avoma_recordings.py --from-date 2026-04-01 --to-date 2026-07-23
    python fetch_avoma_recordings.py --attendee-email naren@joveo.com --overwrite
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

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

AVOMA_BASE_URL = "https://api.avoma.com"
AVOMA_TIMEOUT = float(os.getenv("AVOMA_TIMEOUT", "30"))
RECORDINGS_DIR = Path(__file__).parent / "recordings"


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


async def run(from_date: str, to_date: str, attendee_email: str, overwrite: bool) -> None:
    client = AvomaClient()
    RECORDINGS_DIR.mkdir(exist_ok=True)

    print(f"Fetching meetings from {from_date} to {to_date} for attendee {attendee_email}...")
    meetings = await client.get_meetings(from_date, to_date, attendee_emails=attendee_email)
    print(f"  {len(meetings)} meeting(s) returned")

    naren_meetings = [m for m in meetings if m.transcript_ready and m.transcription_uuid]
    print(f"  {len(naren_meetings)} with a ready transcript")

    if not naren_meetings and meetings:
        seen = sorted({a.get("email", "<none>") for m in meetings for a in (m.attendees or [])})
        print(f"  attendee email values actually present ({len(seen)} distinct):")
        for email in seen[:30]:
            print(f"    {email}")

    written = 0
    skipped = 0
    skipped_no_speaker = 0
    for meeting in naren_meetings:
        out_path = RECORDINGS_DIR / f"{meeting.uuid}.txt"
        if out_path.exists() and not overwrite:
            skipped += 1
            continue

        transcription = await client.get_transcription(meeting.transcription_uuid)
        if transcription is None:
            print(f"  [skip] {meeting.uuid} ({meeting.subject}) -- transcription fetch failed")
            continue

        if not any(s.email.lower() == attendee_email.lower() for s in transcription.speakers):
            skipped_no_speaker += 1
            print(f"  [skip] {meeting.uuid} ({meeting.subject}) -- {attendee_email} never speaks")
            continue

        out_path.write_text(transcription.to_plain_transcript(), encoding="utf-8")
        written += 1
        print(f"  [ok] {meeting.start_at} {meeting.subject} -> {out_path.name}")

    print(
        f"\nDone. {written} written, {skipped} already present, "
        f"{skipped_no_speaker} skipped ({attendee_email} never speaks) "
        "(use --overwrite to refetch)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date", default=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"))
    parser.add_argument("--to-date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--attendee-email", default="naren@joveo.com")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    asyncio.run(run(args.from_date, args.to_date, args.attendee_email, args.overwrite))


if __name__ == "__main__":
    main()
