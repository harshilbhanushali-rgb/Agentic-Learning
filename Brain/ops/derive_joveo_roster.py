#!/usr/bin/env python3
"""Derive the Joveo employee roster from Avoma's own data, then audit the CSM speakers.

WHY NOT THE HAND-MAINTAINED LIST. JOVEO_SPEAKER_NAMES drifts stale and fails OPEN: an
unlisted Joveo colleague is classified as THE CLIENT, so their internal chatter becomes
client turns, becomes coaching signals, and gets written to gap_events as findings about a
CSM. Nothing errors. A sweep of csm_recordings/ found 87 speakers unclassified.

WHERE THE TRUTH LIVES. recordings/*.speakers.json carry Avoma's calendar-derived roster for
Naren's 412 calls, with BOTH is_rep and an email address. The email is the stronger signal:
"@joveo.com" is a fact, while is_rep is Avoma's inference and mislabels e.g. a client-side
contractor. csm_recordings/ has no such files -- its filenames are descriptive titles, not
meeting UUIDs, so backfill_speaker_roster.py cannot address them -- but any Joveo employee
who appears in Naren's calls can be recognised in the CSM calls for free.

Read-only. No API, no DB, no writes. Prints names, never .env values.

Usage (from Brain/):
    python ops/derive_joveo_roster.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

# Brain/ for the shared packages, and ops/ itself for the sibling module. Importing the
# sibling as `from ops.x import ...` would require an ops/__init__.py, and ops is
# deliberately NOT a package: clear_data.py and clear_ego_trap_data.py have no __main__
# guard, so making them importable means `import ops.clear_data` silently wipes live data.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config  # noqa: E402
from check_csm_speakers import speakers_in  # noqa: E402

_BRAIN = Path(__file__).resolve().parent.parent


def norm(name: str) -> frozenset:
    """Token set, so "Sadones, Gabbie" and "Gabbie Sadones" compare equal.

    Avoma writes some names surname-first while transcripts write them given-name-first,
    so a string comparison silently misses real matches -- the failure mode this script
    exists to close, reintroduced one level down.
    """
    return frozenset(t for t in re.split(r"[^a-z]+", name.lower()) if len(t) > 1)


def main() -> None:
    # BOTH sides. Naren's rosters alone can only recognise Joveo staff who appear in his
    # calls too, so an implementation engineer who only ever joins CSM calls stays
    # invisible -- and those are exactly the people on a "uat" or "move to production"
    # call. backfill_csm_speaker_roster.py fetches the CSM side; reading it here is what
    # makes that fetch count, because ego_trap/ does NOT read speakers.json at all. It
    # classifies from csm_name plus JOVEO_SPEAKER_NAMES, so the authoritative data has to
    # be fed INTO that list rather than consumed directly.
    naren_rosters = sorted((_BRAIN / "recordings").glob("*.speakers.json"))
    csm_rosters = sorted((_BRAIN / "csm_recordings").glob("*.speakers.json"))
    rosters = naren_rosters + csm_rosters
    print(f"Avoma rosters: {len(naren_rosters)} naren + {len(csm_rosters)} csm"
          f" = {len(rosters)}")
    if not csm_rosters:
        print("  WARNING: no CSM rosters. Run ops/backfill_csm_speaker_roster.py --run"
              " first, or this can only see staff who appear in Naren's calls.")

    by_email: dict[frozenset, set] = {}
    is_rep_only: dict[frozenset, set] = {}
    for f in rosters:
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        for s in data.get("speakers") or []:
            name, email = (s.get("name") or "").strip(), (s.get("email") or "").strip()
            key = norm(name)
            if not key:
                continue
            if email.lower().endswith("@joveo.com"):
                by_email.setdefault(key, set()).add(name)
            elif s.get("is_rep"):
                is_rep_only.setdefault(key, set()).add(name)

    print(f"Joveo staff by @joveo.com email : {len(by_email)}")
    print(f"is_rep=true WITHOUT a joveo email: {len(is_rep_only)}   (weaker evidence)")

    joveo_keys = set(by_email) | set(is_rep_only)

    csm_dir = _BRAIN / "csm_recordings"
    counts: Counter = Counter()
    for f in sorted(csm_dir.glob("*.txt")):
        counts.update(speakers_in(f))

    cfg = load_config()
    configured = set(cfg.joveo_speakers_lower) | {cfg.naren_name_lower}

    matched, unknown = [], []
    for name, turns in counts.items():
        key = norm(name)
        if name.lower() in configured:
            continue
        if key in by_email:
            matched.append((turns, name, "joveo email", sorted(by_email[key])[0]))
        elif key in is_rep_only:
            matched.append((turns, name, "is_rep only", sorted(is_rep_only[key])[0]))
        else:
            unknown.append((turns, name))

    print("\n" + "=" * 74)
    print("JOVEO STAFF FOUND IN CSM CALLS BUT NOT IN JOVEO_SPEAKER_NAMES")
    print("=" * 74)
    if matched:
        print("Every one of these is currently being treated as THE CLIENT.\n")
        for turns, name, why, avoma in sorted(matched, reverse=True):
            print(f"  {turns:>5} turns   {name:<28} [{why}]  avoma: {avoma}")
        print("\nAdd these to JOVEO_SPEAKER_NAMES before running Layer D.")
    else:
        print("  none -- every Joveo speaker in the CSM calls is already configured.")

    print("\n" + "=" * 74)
    print(f"STILL UNIDENTIFIED ({len(unknown)}) -- never appear in Naren's calls")
    print("=" * 74)
    print("Expected to be genuine client contacts. Judge the top ones by eye.\n")
    for turns, name in sorted(unknown, reverse=True)[:20]:
        print(f"  {turns:>5} turns   {name}")


if __name__ == "__main__":
    main()
