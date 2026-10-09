#!/usr/bin/env python3
"""Pull ~4 years of Naren's Avoma calls into a QUARANTINE directory, with rosters.

*** NEVER writes into recordings/. *** That directory is the curated 393-call corpus behind
every artifact's corpus_sha; mixing an unvetted pull into it would silently invalidate every
checkpoint and comparison. This pull lands in recordings_pull_4yr/ and stays there until
calibration/audit_naren_pull.py has run the full contamination funnel over it and a human
has looked at the report. Overlap with the existing corpus is EXPECTED and fine -- the audit
counts it via meeting_uuid, so duplicates cost nothing but disk.

Differences from ops/fetch_avoma_recordings.py (which this reuses via import, never copies):
  * writes the {stem}.speakers.json roster sidecar AT FETCH TIME. The original fetcher
    downloads the roster inside the transcription payload and DISCARDS it; every
    contamination filter this repo built in the last week (UNATTRIBUTED classification,
    staff-as-client repair, interview structural signal, account identification) reads that
    sidecar, so a pull without it is unauditable.
  * fetches in 6-month windows over the whole range -- kinder to pagination, and a crash
    loses one window, not the pull. Re-runnable: existing stems are skipped.
  * writes _manifest.json (uuid, subject, start_at, organizer, stem) -- the audit's join key
    and the only place the SUBJECT survives, which the interview screen needs.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe ops/fetch_naren_4yr.py
    ..\\.venv\\Scripts\\python.exe ops/fetch_naren_4yr.py --from-date 2022-08-17
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BRAIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRAIN))

# ops/ is deliberately not a package (importing clear_data would wipe live data), so the
# existing fetcher is loaded by file path. It has no import-time side effects beyond
# load_dotenv, which is exactly what we want here too.
_spec = importlib.util.spec_from_file_location(
    "fetch_avoma_recordings", BRAIN / "ops" / "fetch_avoma_recordings.py")
_fetcher = importlib.util.module_from_spec(_spec)
# sys.modules registration BEFORE exec: the fetcher uses postponed annotations, and
# pydantic resolves them through sys.modules[cls.__module__] -- without this line every
# model_validate raises "`AvomaMeeting` is not fully defined".
sys.modules["fetch_avoma_recordings"] = _fetcher
_spec.loader.exec_module(_fetcher)

OUT_DIR = BRAIN / "recordings_pull_4yr"
MANIFEST = OUT_DIR / "_manifest.json"


async def _net_retry(coro_factory, what: str, tries: int = 5):
    """This box's DNS intermittently fails (documented; run_visible.ps1 ships a bypass for
    the same reason), and the production client retries only 429s -- a ConnectError killed
    the first 4-year pull three windows in. Transport errors get a patient backoff here."""
    for i in range(tries):
        try:
            return await coro_factory()
        except Exception as e:
            if i == tries - 1:
                raise
            wait = 20 * (i + 1)
            print(f"  [net] {what}: {type(e).__name__} -- retry {i+1}/{tries-1} "
                  f"in {wait}s", flush=True)
            await asyncio.sleep(wait)


async def get_transcription_lenient(client, tuuid: str):
    """The fetcher's get_transcription, with old-data sanitation. Four-year-old
    transcriptions carry speakers with name/email = None, which the strict production
    model rejects (measured: crashed the first pull two files in). Nulls become the same
    sentinels the pipeline already understands; everything else is unchanged."""
    import httpx
    url = f"{_fetcher.AVOMA_BASE_URL}/v1/transcriptions/{tuuid}/"
    async with client.semaphore:
        async with httpx.AsyncClient(timeout=_fetcher.AVOMA_TIMEOUT) as http:
            data = await client._get_with_retry(http, url, None)
    if not data:
        return None
    for s in data.get("speakers", []):
        if s.get("name") is None:
            s["name"] = "Unknown Speaker"
        if s.get("email") is None:
            s["email"] = ""
    return _fetcher.AvomaTranscription.model_validate(data)


def _windows(from_date: str, to_date: str) -> list[tuple[str, str]]:
    """Half-year [start, end) windows. The Avoma meetings window is end-EXCLUSIVE
    (measured, recorded in CLAUDE.md), so consecutive windows share a boundary date
    without double-counting."""
    start = datetime.strptime(from_date, "%Y-%m-%d")
    stop = datetime.strptime(to_date, "%Y-%m-%d")
    out = []
    while start < stop:
        end = min(start + timedelta(days=183), stop)
        out.append((start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
        start = end
    return out


async def run(from_date: str, to_date: str, attendee: str) -> None:
    client = _fetcher.AvomaClient()
    OUT_DIR.mkdir(exist_ok=True)
    manifest: dict[str, dict] = {}
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))

    total_meetings = total_ready = written = skipped = no_speak = failed = 0
    for w_from, w_to in _windows(from_date, to_date):
        print(f"\n[window] {w_from} -> {w_to}", flush=True)
        meetings = await _net_retry(
            lambda: client.get_meetings(w_from, w_to, attendee_emails=attendee),
            f"meetings {w_from}")
        ready = [m for m in meetings if m.transcript_ready and m.transcription_uuid]
        total_meetings += len(meetings)
        total_ready += len(ready)
        print(f"  {len(meetings)} meetings, {len(ready)} with a ready transcript", flush=True)

        for m in ready:
            stamp = m.start_at.strftime("%Y%m%d") if m.start_at else "nodate"
            stem = f"{stamp}_{_fetcher._slug(m.subject)}_{m.uuid[:8]}"
            txt = OUT_DIR / f"{stem}.txt"
            if txt.exists():
                skipped += 1
                # A crash between manifest flushes leaves files without a manifest row;
                # the audit needs the SUBJECT (interview screen), so backfill it here --
                # this makes a final no-op rerun repair the manifest for free.
                if stem not in manifest:
                    manifest[stem] = {
                        "meeting_uuid": m.uuid, "subject": m.subject,
                        "start_at": m.start_at.isoformat() if m.start_at else None,
                        "organizer_email": m.organizer_email}
                continue
            try:
                tr = await _net_retry(
                    lambda: get_transcription_lenient(client, m.transcription_uuid),
                    f"transcription {m.uuid[:8]}", tries=3)
            except Exception as e:  # one bad old meeting must not kill a 4-year pull
                tr = None
                print(f"  [fail] {m.uuid[:8]} {type(e).__name__}: {str(e)[:90]}", flush=True)
            if tr is None:
                failed += 1
                continue
            if not any((s.email or "").lower() == attendee.lower() for s in tr.speakers):
                no_speak += 1
                continue
            txt.write_text(tr.to_plain_transcript(), encoding="utf-8")
            # Same sidecar shape as recordings/*.speakers.json -- load_roster and every
            # contamination filter read this format.
            (OUT_DIR / f"{stem}.speakers.json").write_text(json.dumps({
                "meeting_uuid": m.uuid,
                "speakers": [s.model_dump() for s in tr.speakers],
            }, indent=2), encoding="utf-8")
            manifest[stem] = {"meeting_uuid": m.uuid, "subject": m.subject,
                              "start_at": m.start_at.isoformat() if m.start_at else None,
                              "organizer_email": m.organizer_email}
            written += 1
            if written % 25 == 0:
                MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
                print(f"  ... {written} written so far", flush=True)

    MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"\nDone. meetings={total_meetings} ready={total_ready} written={written} "
          f"already-present={skipped} naren-never-speaks={no_speak} fetch-failed={failed}")
    print(f"Manifest: {MANIFEST} ({len(manifest)} entries). "
          f"recordings/ was NOT touched.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from-date", default="2022-08-17")
    p.add_argument("--to-date",
                   default=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
                   help="end-EXCLUSIVE, so the default (tomorrow) includes today")
    p.add_argument("--attendee-email", default="naren@joveo.com")
    a = p.parse_args()
    asyncio.run(run(a.from_date, a.to_date, a.attendee_email))


if __name__ == "__main__":
    main()
