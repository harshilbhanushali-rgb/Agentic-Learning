#!/usr/bin/env python3
"""Repair Avoma roster sidecars where a KNOWN Joveo person is marked as an outsider.

THE BUG. `transcript_parser._classify` consults the roster FIRST, and when a roster entry
exists `is_rep` decides outright -- `JOVEO_SPEAKER_NAMES` is never reached:

    entry = _match_roster_entry(speaker_raw, roster)
    if entry is not None:
        ...
        return SpeakerRole.JOVEO_OTHER if entry.get("is_rep") else SpeakerRole.CLIENT

So a Joveo colleague whose sidecar says `is_rep: false` is classified CLIENT, and adding their
name to the env var CANNOT fix it. The env-var remedy that worked for the CSM corpus does not
apply here; the data has to be corrected.

WHY THE DATA IS WRONG, not merely inconvenient. The affected entries have an `email` that is
not an email at all -- literally the string `"db"` or `"gm"`, a failed lookup leaking into the
field. Measured over recordings/ + csm_recordings/: 553 distinct speakers, 66 ever resolved to
@joveo.com, 163 ever unresolved, and 8 names appear BOTH ways. Those 8 are Joveo staff by
their own other meetings.

Cost of leaving it: ~818 CLIENT turns (3.4% of the pool) are Joveo employees talking, with
`kj` alone contributing 422 -- the 11th-largest "client" voice in the corpus.

TWO GUARDS, both deliberate:
  * only names PROVEN Joveo elsewhere (an @joveo.com address on some other meeting) are
    touched. `deepika j`, `kaashvi seth` and `narasimharao tadi` are never resolved anywhere,
    so they are left alone rather than guessed -- they may be clients.
  * only entries whose email is NOT an email are rewritten. `doug shonrock` appears once with
    `amiller@lumbertonisd.org`; a real address, even a client one, is evidence and is never
    overwritten.

Every change is backed up and reversible with --restore.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe ops/repair_speaker_rosters.py --dry-run
    ..\\.venv\\Scripts\\python.exe ops/repair_speaker_rosters.py --apply
    ..\\.venv\\Scripts\\python.exe ops/repair_speaker_rosters.py --restore
"""
from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent          # ops/ -> Brain/
DIRS = [BRAIN / "recordings", BRAIN / "csm_recordings"]
BACKUP = BRAIN / "artifacts" / "roster_backup"

# Speakers observed with an @joveo.com address on SOME meeting, and unresolved on others.
# `kj` is included on separate evidence: it appears as ('db', is_rep=True) in at least one
# roster, i.e. already marked a rep elsewhere, and `kj@joveo.com` belongs to Kshitij Jain.
EXTRA_PROVEN = {"kj"}


def survey() -> tuple[dict[str, set], set[str]]:
    obs: dict[str, set] = defaultdict(set)
    for d in DIRS:
        if not d.exists():
            continue
        for f in d.glob("*.speakers.json"):
            for s in json.loads(f.read_text(encoding="utf-8-sig")).get("speakers", []):
                nm = (s.get("name") or "").strip().lower()
                if nm:
                    obs[nm].add((str(s.get("email") or "").lower(), bool(s.get("is_rep"))))
    joveo = {n for n, v in obs.items() if any("@joveo.com" in e for e, _ in v)}
    return obs, joveo | EXTRA_PROVEN


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--restore", action="store_true")
    a = p.parse_args()

    if a.restore:
        if not BACKUP.exists():
            raise SystemExit("no backup to restore from")
        n = 0
        for f in BACKUP.glob("*.speakers.json"):
            for d in DIRS:
                if (d / f.name).exists():
                    shutil.copy2(f, d / f.name)
                    n += 1
        print(f"restored {n} roster files from {BACKUP}")
        return

    obs, joveo = survey()
    print(f"{len(obs)} distinct speakers; {len(joveo)} provably Joveo")

    edits, per_name = [], defaultdict(int)
    for d in DIRS:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.speakers.json")):
            data = json.loads(f.read_text(encoding="utf-8-sig"))
            changed = False
            for s in data.get("speakers", []):
                nm = (s.get("name") or "").strip().lower()
                em = str(s.get("email") or "")
                if nm in joveo and not s.get("is_rep") and "@" not in em:
                    s["is_rep"] = True
                    s["_repaired_from"] = em
                    per_name[nm] += 1
                    changed = True
            if changed:
                edits.append((f, data))

    print(f"\n{len(edits)} roster files need repair; per speaker:")
    for nm, n in sorted(per_name.items(), key=lambda x: -x[1]):
        print(f"   {nm:<26} {n:>3} meeting(s)")

    if a.dry_run:
        print("\n--dry-run: nothing written. Re-run with --apply.")
        return

    BACKUP.mkdir(parents=True, exist_ok=True)
    for f, data in edits:
        if not (BACKUP / f.name).exists():
            shutil.copy2(f, BACKUP / f.name)
        f.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"\nrepaired {len(edits)} files; originals backed up to {BACKUP}")
    print("Reverse with: ops/repair_speaker_rosters.py --restore")
    print("EVERY artifact keyed to the old pool is now stale -- the CLIENT turn set changed.")


if __name__ == "__main__":
    main()
