#!/usr/bin/env python3
"""Are JOVEO EMPLOYEES being classified as CLIENT? Ground truth = the HR roster. Free.

WHY THIS BEATS EVERYTHING TRIED SO FAR. `transcript_parser._classify` consults the meeting
roster first, and `is_rep` decides outright -- so a colleague whose Avoma sidecar says
`is_rep: false` becomes CLIENT, and `JOVEO_SPEAKER_NAMES` is never reached. Detecting them
from the sidecars alone only works for people who happen to be resolved on some OTHER meeting
(that found 8). An HR export names every employee outright, including the ones Avoma never
resolved anywhere -- `deepika j`, `kaashvi seth`, `narasimharao tadi` were all unprovable
before and are decidable now.

MATCHING, and why it is layered rather than fuzzy. A single fuzzy score would silently accept
a client who shares a surname with an employee. Instead three tiers are reported SEPARATELY
and only the top two are proposed for repair:
  exact       full name matches an employee, case/punctuation-normalised
  first+last  first and last token both match one employee (handles middle names/initials)
  partial     a single shared token -- REPORTED ONLY, never auto-applied, because "Grace" or
              "Taylor" collides constantly
Employment status is not a filter: someone who has since left was still staff on the call.

PII: reads Full Name only. Employee number, date of birth and dates are never loaded.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/check_employees_as_clients.py
    ..\\.venv\\Scripts\\python.exe calibration/check_employees_as_clients.py --csv "../Original Date of Joining - 16 June 2026 - Sheet1.csv"
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OUT = ARTIFACTS_DIR / "employees_as_clients.json"
DEFAULT_CSV = Path(__file__).resolve().parent.parent.parent / \
    "Original Date of Joining - 16 June 2026 - Sheet1.csv"
# Speaker labels that are not people at all.
NOT_A_PERSON = re.compile(r"notetaker|unknown speaker|^\+?\d[\d\s\-*()]+$|recorder|^db$", re.I)


def norm(s: str) -> str:
    s = re.sub(r"\(.*?\)", " ", str(s or ""))          # drop "(DHL)" style qualifiers
    s = re.sub(r"[^a-z\s]", " ", s.lower())
    return " ".join(s.split())


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", default=str(DEFAULT_CSV))
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--show", type=int, default=30)
    return p.parse_args()


def main() -> None:
    a = _args()
    from config import load_config
    from preprocessing.transcript_parser import parse_transcript, load_roster

    csv_path = Path(a.csv)
    if not csv_path.exists():
        raise SystemExit(f"employee CSV not found: {csv_path}")
    exact: dict[str, str] = {}
    firstlast: dict[tuple[str, str], str] = {}
    token_owner: dict[str, set] = defaultdict(set)
    n_emp = 0
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            full = (row.get("Full Name") or "").strip()
            if not full:
                continue
            n_emp += 1
            nm = norm(full)
            if not nm:
                continue
            exact[nm] = full
            t = nm.split()
            if len(t) >= 2:
                firstlast[(t[0], t[-1])] = full
            for tok in t:
                if len(tok) > 2:
                    token_owner[tok].add(full)
    print(f"employee roster: {n_emp} people ({len(exact)} distinct normalised names)")

    cfg = load_config()
    client_turns: Counter = Counter()
    total = 0
    for f in sorted(Path(a.recordings).glob("*.txt")):
        for t in parse_transcript(str(f), cfg.joveo_speakers_lower, cfg.naren_name_lower,
                                  roster=load_roster(str(f))):
            if str(getattr(t, "role", "")).upper().endswith("CLIENT"):
                total += 1
                client_turns[(t.speaker_raw or "?").strip()] += 1
    print(f"{len(client_turns)} distinct speakers hold {total} CLIENT turns\n")

    tiers = {"exact": [], "first+last": [], "partial": [], "not_a_person": []}
    for spk, n in client_turns.items():
        if NOT_A_PERSON.search(spk):
            tiers["not_a_person"].append((spk, n, ""))
            continue
        nm = norm(spk)
        t = nm.split()
        if nm in exact:
            tiers["exact"].append((spk, n, exact[nm]))
        elif len(t) >= 2 and (t[0], t[-1]) in firstlast:
            tiers["first+last"].append((spk, n, firstlast[(t[0], t[-1])]))
        else:
            owners = set().union(*(token_owner.get(x, set()) for x in t)) if t else set()
            if owners:
                tiers["partial"].append((spk, n, f"{len(owners)} candidate(s)"))

    print(f"  {'tier':<14}{'speakers':>10}{'CLIENT turns':>14}{'% of client':>13}")
    for k in ("exact", "first+last", "partial", "not_a_person"):
        v = tiers[k]
        s = sum(n for _, n, _ in v)
        print(f"  {k:<14}{len(v):>10}{s:>14}{s/max(1,total)*100:>12.1f}%")

    for k in ("exact", "first+last"):
        print(f"\n  --- {k} matches (PROPOSE REPAIR) ---")
        for spk, n, emp in sorted(tiers[k], key=lambda x: -x[1])[:a.show]:
            print(f"    {n:>5} turns  {spk:<30} -> {emp}")
    print(f"\n  --- not a person (exclude, do not 'repair') ---")
    for spk, n, _ in sorted(tiers["not_a_person"], key=lambda x: -x[1])[:10]:
        print(f"    {n:>5} turns  {spk}")
    print(f"\n  --- partial, REVIEW ONLY (a shared token is not identity) ---")
    for spk, n, note in sorted(tiers["partial"], key=lambda x: -x[1])[:10]:
        print(f"    {n:>5} turns  {spk:<30} {note}")

    OUT.write_text(json.dumps(
        {"n_employees": n_emp, "client_turns": total,
         "tiers": {k: [{"speaker": s, "turns": n, "employee": e} for s, n, e in v]
                   for k, v in tiers.items()}}, indent=1), encoding="utf-8")
    print(f"\n  wrote {OUT}")


if __name__ == "__main__":
    main()
