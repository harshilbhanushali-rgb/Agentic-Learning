"""
Backfill per-meeting speaker rosters from Avoma's insights API for existing
recordings/*.txt files, so the pipeline can classify NAREN / JOVEO_OTHER /
CLIENT roles from Avoma's own calendar-derived `is_rep` field instead of
fuzzy-matching speaker names against the hand-maintained JOVEO_SPEAKER_NAMES
list (which drifts stale and can't distinguish e.g. a client-side contractor
whose talk sounds "internal" from an actual Joveo employee).

Writes recordings/{stem}.speakers.json next to each transcript:
    {"meeting_uuid": "...", "speakers": [{"name":..., "email":..., "is_rep":..., "id":...}, ...]}

recordings/*.txt filenames are Avoma meeting_uuids (see fetch_avoma_recordings.py),
so no separate uuid lookup is needed.

Usage (from Brain/ with venv active):
    python backfill_speaker_roster.py
    python backfill_speaker_roster.py --overwrite
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import httpx

AVOMA_BASE_URL = "https://api.avoma.com"
RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"
RATE_LIMIT_DELAY = 0.5


class AvomaInsightsClient:
    def __init__(self) -> None:
        api_key = os.getenv("AVOMA_API_KEY")
        if not api_key:
            raise ValueError("AVOMA_API_KEY environment variable is required")
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._last_request_time = 0.0

    async def _rate_limit(self) -> None:
        loop = asyncio.get_event_loop()
        elapsed = loop.time() - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            await asyncio.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = loop.time()

    async def get_speakers(self, client: httpx.AsyncClient, meeting_uuid: str) -> tuple[list[dict] | None, str]:
        """Returns (speakers, status_note). speakers is None on failure."""
        url = f"{AVOMA_BASE_URL}/v1/meetings/{meeting_uuid}/insights/"
        max_retries = 5
        retry_count = 0
        while retry_count <= max_retries:
            await self._rate_limit()
            try:
                resp = await client.get(url, headers=self.headers)
            except httpx.HTTPError as e:
                return None, f"request error: {e}"
            if resp.status_code == 200:
                return resp.json().get("speakers", []), "ok"
            if resp.status_code == 429:
                retry_count += 1
                await asyncio.sleep(60)
                continue
            if resp.status_code == 404:
                return None, "404 not found"
            return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
        return None, "exhausted retries (429)"


async def run(overwrite: bool) -> None:
    client_wrapper = AvomaInsightsClient()
    txts = sorted(RECORDINGS_DIR.glob("*.txt"))
    print(f"Found {len(txts)} transcript(s) in {RECORDINGS_DIR}")

    written = skipped = failed = 0
    failures: list[tuple[str, str]] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for i, txt_path in enumerate(txts, 1):
            out_path = RECORDINGS_DIR / f"{txt_path.stem}.speakers.json"
            if out_path.exists() and not overwrite:
                skipped += 1
                continue
            speakers, note = await client_wrapper.get_speakers(client, txt_path.stem)
            if speakers is None:
                print(f"  [{i}/{len(txts)}] [fail] {txt_path.stem} -- {note}")
                failed += 1
                failures.append((txt_path.stem, note))
                continue
            out_path.write_text(
                json.dumps({"meeting_uuid": txt_path.stem, "speakers": speakers}, indent=2),
                encoding="utf-8",
            )
            written += 1
            print(f"  [{i}/{len(txts)}] [ok] {txt_path.stem} -- {len(speakers)} speaker(s)")

    print(f"\nDone. {written} written, {skipped} already present, {failed} failed.")
    if failures:
        print("\nFailures:")
        for stem, note in failures:
            print(f"  {stem}: {note}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.overwrite))


if __name__ == "__main__":
    main()
