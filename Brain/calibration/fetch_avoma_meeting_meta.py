#!/usr/bin/env python3
"""GROUND TRUTH for what each recording actually IS. Read-only; caches; no corpus writes.

WHY. The taxonomy's largest coachable scenario (822 turns, 27% of coachable volume) turned out
to be JOB INTERVIEWS -- candidates narrating their careers, admitted because
`transcript_parser` classifies any non-Joveo speaker as CLIENT and so fails OPEN on a
candidate. Detecting them from transcript TEXT reached ~19 calls with an estimated +/-2 and a
partly circular recall check.

Avoma already knows. `GET /v1/meetings/{uuid}/` returns:
    subject  "Joveo - Solutions Consultant - Kyle Power - Discussion 1"
    purpose  {"label": "Exclude from Review", ...}
    is_internal, type, outcome, organizer_email
So the org has ALREADY tagged these, and the export dropped the field. Scheduling-system
ground truth beats any lexical heuristic, and where both exist the overlap MEASURES the
heuristic instead of leaving it at "+/-2".

TWO API FACTS, both measured, both cost a request to learn:
  * `/v1/meetings/{uuid}` 301-redirects; the TRAILING SLASH is required.
  * `/v1/meeting_types/` is 404 on this account -- `purpose` arrives inline on the meeting, so
    no separate lookup is needed. (A date-range scan is also the wrong shape here: we already
    know the exact UUIDs, and CLAUDE.md records Avoma's meetings window as end-EXCLUSIVE, so
    a range query silently drops its boundary day.)

Auth mirrors ops/fetch_avoma_recordings.py (Bearer + AVOMA_API_KEY). Deliberately NOT imported
from it: ops/ has no __init__.py by design, so importing across that boundary is exactly what
the layout is meant to prevent.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/fetch_avoma_meeting_meta.py
    ..\\.venv\\Scripts\\python.exe calibration/fetch_avoma_meeting_meta.py --load
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OUT = ARTIFACTS_DIR / "avoma_meeting_meta.json"
BASE = "https://api.avoma.com/v1/meetings"
DELAY = 0.25

# Subject patterns for a hiring conversation. Used ONLY where `purpose` is absent, and
# reported separately so the two are never silently blended.
# MEASURED, not guessed. A bare `hiring` flags "RTX <> Joveo || 'Engineers in Their Element'
# US Hiring Discussion" -- a CLIENT call about the client's own hiring. In a recruitment
# business `hiring`, `recruit` and `candidate` are the subject matter, not a meeting type;
# this is the same domain-vocabulary trap that made `your_resume`/`hiring_for` useless in the
# transcript-text detector. What survives is language about OUR OWN hiring process:
# "interview"/"screen", and the "<Role Title> - <Person> - Discussion N" shape Avoma subjects
# use for interview loops (the real one read: "Joveo - Solutions Consultant - Kyle Power -
# Discussion 1").
SUBJECT_HIRE = re.compile(
    r"\binterview\b|\bscreen(?:ing)?\s+call\b"
    r"|\b(?:discussion|round|stage)\s*[1-9]\b", re.I)


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--load", action="store_true", help="re-report the cache, no requests")
    p.add_argument("--limit", type=int, default=0)
    return p.parse_args()


def fetch_all(stems: list[str], cache: dict) -> dict:
    import os
    import httpx
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    key = os.getenv("AVOMA_API_KEY")
    if not key:
        raise SystemExit("AVOMA_API_KEY not set")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    todo = [s for s in stems if s not in cache]
    print(f"{len(cache)} cached, {len(todo)} to fetch", flush=True)
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        for n, stem in enumerate(todo, 1):
            for attempt in range(5):
                r = c.get(f"{BASE}/{stem}/", headers=headers)
                if r.status_code == 200:
                    d = r.json()
                    cache[stem] = {k: d.get(k) for k in
                                   ("subject", "purpose", "outcome", "type", "is_internal",
                                    "is_private", "organizer_email", "duration", "state")}
                    break
                if r.status_code == 429:
                    wait = int(re.search(r"(\d+) seconds", r.text).group(1)) + 2 \
                        if re.search(r"(\d+) seconds", r.text) else 30
                    print(f"  429, waiting {wait}s", flush=True)
                    time.sleep(wait)
                    continue
                cache[stem] = {"_error": r.status_code}
                break
            if n % 40 == 0:
                print(f"  {n}/{len(todo)}", flush=True)
            time.sleep(DELAY)
    return cache


def main() -> None:
    a = _args()
    stems = sorted(p.stem for p in Path(a.recordings).glob("*.txt"))
    if a.limit:
        stems = stems[:a.limit]
    cache = json.loads(OUT.read_text(encoding="utf-8-sig")) if OUT.exists() else {}
    if not a.load:
        cache = fetch_all(stems, cache)
        OUT.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        print(f"wrote {OUT}")

    have = {s: cache[s] for s in stems if s in cache and "_error" not in cache[s]}
    err = [s for s in stems if s in cache and "_error" in cache[s]]
    print("\n" + "=" * 84)
    print(f"  AVOMA METADATA: {len(have)}/{len(stems)} resolved"
          + (f", {len(err)} errors" if err else ""))
    print("=" * 84)

    purposes = Counter((v.get("purpose") or {}).get("label") or "(none)" for v in have.values())
    print("\n  purpose.label distribution:")
    for lab, n in purposes.most_common():
        print(f"    {n:>4}  {lab}")
    print(f"\n  is_internal: {Counter(v.get('is_internal') for v in have.values())}")
    print(f"  type       : {Counter(str(v.get('type')) for v in have.values()).most_common(5)}")

    subj_hits = [s for s, v in have.items() if SUBJECT_HIRE.search(v.get("subject") or "")]
    print(f"\n  subjects matching a hiring pattern: {len(subj_hits)}")
    for s in subj_hits[:15]:
        print(f"    {have[s].get('subject')}")

    # --- cross-tab against the transcript-text heuristic -------------------------------
    hpath = ARTIFACTS_DIR / "interview_transcripts.json"
    if hpath.exists():
        h = {r["stem"]: r for r in json.loads(hpath.read_text(encoding="utf-8-sig"))["rows"]}
        heur = {s for s in have if h.get(s, {}).get("is_interview")}
        for label, truth in (("subject pattern", set(subj_hits)),
                             ("purpose=Exclude from Review",
                              {s for s, v in have.items()
                               if (v.get("purpose") or {}).get("label") == "Exclude from Review"})):
            tp, fp, fn = len(heur & truth), len(heur - truth), len(truth - heur)
            if not truth:
                continue
            print(f"\n  HEURISTIC vs {label}  (truth n={len(truth)}, heuristic n={len(heur)})")
            print(f"    both {tp}   heuristic-only {fp}   truth-only {fn}")
            print(f"    precision {tp/max(1,tp+fp)*100:.0f}%   recall {tp/max(1,tp+fn)*100:.0f}%")
            for s in sorted(truth - heur)[:8]:
                print(f"      MISSED: {have[s].get('subject')}")


if __name__ == "__main__":
    main()
