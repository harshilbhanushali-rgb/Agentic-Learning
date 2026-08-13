#!/usr/bin/env python3
"""Per-meeting speaker rosters for csm_recordings/, from Avoma's own calendar data.

WHY THIS EXISTS SEPARATELY FROM backfill_speaker_roster.py. That script assumes the
transcript filename IS the Avoma meeting_uuid, which holds for recordings/ but not here:
fetch_avoma_recordings.py names CSM files "{YYYYMMDD}_{slug}_{uuid[:8]}" so they stay
readable, keeping only the first 8 hex of the uuid. The insights endpoint needs the full
one, so the prefix is resolved against the meetings list first.

WHAT IT FIXES. Speaker classification currently falls back to matching names against
JOVEO_SPEAKER_NAMES, and that fallback FAILS OPEN: an unlisted Joveo colleague is scored as
THE CLIENT, so their internal chatter becomes client turns, becomes coaching signals, and
lands in gap_events as findings about a CSM. Nothing errors.

Deriving the roster from Naren's 412 existing rosters closes part of the gap -- it found
one unconfigured Joveo speaker -- but only recognises staff who appear on BOTH sides. A
Joveo engineer who only ever joins CSM calls stays invisible, and those are exactly the
people on a "uat" or "move to production" call. 417 turns in 6 files are attributed to an
"Unknown Speaker" the transcript could not name; Avoma's roster may well name them.

Writes csm_recordings/{stem}.speakers.json, the same shape backfill_speaker_roster.py
produces, so anything reading one can read the other.

Costs Avoma API calls only -- no Gemma, no embeddings, no DB.

Usage (from Brain/, venv active):
    python ops/backfill_csm_speaker_roster.py                 # dry run: resolve only
    python ops/backfill_csm_speaker_roster.py --run           # fetch + write
    python ops/backfill_csm_speaker_roster.py --run --overwrite
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import httpx  # noqa: E402

AVOMA_BASE_URL = "https://api.avoma.com"
CSM_DIR = Path(__file__).resolve().parent.parent / "csm_recordings"
RATE_LIMIT_DELAY = 0.5

# "20260511_fw_joveo_kick_off_call_f5d39fe1" -> ("20260511", "f5d39fe1")
_STEM_RE = re.compile(r"^(\d{8})_.*_([0-9a-f]{8})$")

_AUTO = "auto"


def parse_stem(stem: str) -> tuple[str, str] | None:
    m = _STEM_RE.match(stem)
    return (m.group(1), m.group(2)) if m else None


class AvomaClient:
    def __init__(self) -> None:
        api_key = os.getenv("AVOMA_API_KEY")
        if not api_key:
            raise ValueError("AVOMA_API_KEY environment variable is required")
        self.headers = {"Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"}
        self._last = 0.0

    async def _rate_limit(self) -> None:
        loop = asyncio.get_event_loop()
        elapsed = loop.time() - self._last
        if elapsed < RATE_LIMIT_DELAY:
            await asyncio.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last = loop.time()

    async def list_meeting_uuids(self, client: httpx.AsyncClient,
                                 from_date: str, to_date: str) -> list[str]:
        """Every meeting uuid in the window, following pagination."""
        url: str | None = f"{AVOMA_BASE_URL}/v1/meetings/"
        params: dict | None = {"page_size": 100, "from_date": from_date,
                               "to_date": to_date, "o": "-start_at"}
        uuids: list[str] = []
        while url:
            await self._rate_limit()
            resp = await client.get(url, headers=self.headers, params=params)
            if resp.status_code == 429:
                await asyncio.sleep(60)
                continue
            if resp.status_code != 200:
                print(f"  meetings list HTTP {resp.status_code}: {resp.text[:160]}")
                break
            data = resp.json()
            results = data.get("results", []) if isinstance(data, dict) else data
            uuids.extend(m["uuid"] for m in results if m.get("uuid"))
            url = data.get("next") if isinstance(data, dict) else None
            params = None       # `next` already carries the query string
        return uuids

    async def get_speakers(self, client: httpx.AsyncClient,
                           meeting_uuid: str) -> tuple[list[dict] | None, str]:
        url = f"{AVOMA_BASE_URL}/v1/meetings/{meeting_uuid}/insights/"
        for _ in range(6):
            await self._rate_limit()
            try:
                resp = await client.get(url, headers=self.headers)
            except httpx.HTTPError as e:
                return None, f"request error: {e}"
            if resp.status_code == 200:
                return resp.json().get("speakers", []), "ok"
            if resp.status_code == 429:
                await asyncio.sleep(60)
                continue
            if resp.status_code == 404:
                return None, "404 not found"
            return None, f"HTTP {resp.status_code}: {resp.text[:160]}"
        return None, "exhausted retries (429)"


async def run(do_write: bool, overwrite: bool, from_date: str, to_date: str) -> None:
    txts = sorted(CSM_DIR.glob("*.txt"))
    parsed = {t.stem: parse_stem(t.stem) for t in txts}
    unparsed = [s for s, p in parsed.items() if p is None]
    print(f"transcripts            : {len(txts)}")
    if unparsed:
        print(f"stems without a uuid tail: {len(unparsed)} (cannot be resolved)")
        for s in unparsed[:10]:
            print(f"  - {s}")

    # Derive the window from the filenames rather than guessing a year. A too-wide window
    # makes the meetings list slow enough to time out; a too-narrow one silently fails to
    # resolve transcripts, which reads identically to "Avoma does not have them".
    stamps = sorted(p[0] for p in parsed.values() if p)
    if stamps and from_date == _AUTO:
        from_date = f"{stamps[0][:4]}-{stamps[0][4:6]}-{stamps[0][6:]}"
    if stamps and to_date == _AUTO:
        # +1 day: the meetings window behaves as end-EXCLUSIVE. Measured -- the single
        # transcript dated on the boundary resolved to 0 matches until the end moved.
        last = datetime.strptime(stamps[-1], "%Y%m%d") + timedelta(days=1)
        to_date = last.strftime("%Y-%m-%d")
    print(f"date window            : {from_date} .. {to_date} (from filenames)")

    api = AvomaClient()
    async with httpx.AsyncClient(timeout=90) as client:
        print(f"\nlisting Avoma meetings {from_date} .. {to_date} ...")
        uuids = await api.list_meeting_uuids(client, from_date, to_date)
        print(f"meetings returned      : {len(uuids)}")

        by_prefix: dict[str, list[str]] = {}
        for u in uuids:
            by_prefix.setdefault(u[:8], []).append(u)
        ambiguous = {p: v for p, v in by_prefix.items() if len(v) > 1}

        resolved, unresolved = {}, []
        for stem, p in parsed.items():
            if p is None:
                continue
            hits = by_prefix.get(p[1], [])
            if len(hits) == 1:
                resolved[stem] = hits[0]
            else:
                unresolved.append((stem, len(hits)))

        print(f"resolved to a full uuid: {len(resolved)}")
        print(f"UNRESOLVED             : {len(unresolved)}")
        if ambiguous:
            # 8 hex is 4 billion values; a collision means the window is wrong, not that
            # two meetings really share a prefix.
            print(f"ambiguous prefixes     : {len(ambiguous)}")
        for stem, n in unresolved[:12]:
            print(f"  - {stem}  ({n} matches)")

        if not do_write:
            print("\nDRY RUN -- nothing fetched or written. Re-run with --run.")
            if unresolved:
                print("Widen --from-date/--to-date until UNRESOLVED reaches 0 first;"
                      "\na transcript with no roster keeps the fail-open behaviour.")
            return

        written = skipped = failed = 0
        roles: Counter = Counter()
        for i, (stem, uuid) in enumerate(sorted(resolved.items()), 1):
            out = CSM_DIR / f"{stem}.speakers.json"
            if out.exists() and not overwrite:
                skipped += 1
                continue
            speakers, note = await api.get_speakers(client, uuid)
            if speakers is None:
                print(f"  [{i}/{len(resolved)}] [fail] {stem} -- {note}")
                failed += 1
                continue
            out.write_text(json.dumps({"meeting_uuid": uuid, "stem": stem,
                                       "speakers": speakers}, indent=2), encoding="utf-8")
            for s in speakers:
                email = (s.get("email") or "").lower()
                roles["joveo" if email.endswith("@joveo.com") else "external"] += 1
            written += 1
            print(f"  [{i}/{len(resolved)}] [ok] {stem} -- {len(speakers)} speaker(s)")

        print(f"\nDone. {written} written, {skipped} already present, {failed} failed.")
        print(f"speaker rows: {roles['joveo']} joveo-email, {roles['external']} external")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="fetch and write (default: dry run)")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--from-date", default=_AUTO,
                    help="default: earliest date in the transcript filenames")
    ap.add_argument("--to-date", default=_AUTO,
                    help="default: latest date in the transcript filenames")
    a = ap.parse_args()
    asyncio.run(run(a.run, a.overwrite, a.from_date, a.to_date))


if __name__ == "__main__":
    main()
