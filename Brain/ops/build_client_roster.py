#!/usr/bin/env python3
"""Derive csm_recordings/client_speakers.txt from the Avoma .speakers.json rosters.

The fail-closed speaker gate (layer_d/signals.unverified_speakers) needs a list of
VERIFIED client speaker names: transcript_parser fails OPEN (anyone unrecognized
becomes CLIENT), and on the 100-call run that scored unlisted Joveo colleagues'
chatter as client turns. The Avoma rosters are the ground truth: a speaker is a
verified CLIENT iff their email domain is not joveo.com AND is_rep is false.

Name-format hedge: transcripts render names differently from Avoma ("Puiu, Irina"
vs "Irina"), and the gate prefix-matches both directions on lowercase. So every
verified client contributes several variants: the full name, the comma-swapped
form, the first name token, and the email local-part. All variants come FROM the
verified identity, so the allowlist never widens beyond Avoma's roster.

Deterministic and rerunnable:  python ops/build_client_roster.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_DIR = Path(__file__).resolve().parent.parent / "csm_recordings"
_OUT = _DIR / "client_speakers.txt"


def variants(name: str, email: str) -> set[str]:
    out: set[str] = set()
    name = (name or "").strip()
    if name:
        out.add(name)
        if "," in name:                       # "Puiu, Irina" -> "Irina Puiu"
            last, _, first = name.partition(",")
            swapped = f"{first.strip()} {last.strip()}".strip()
            if swapped:
                out.add(swapped)
        first_token = name.replace(",", " ").split()
        if first_token:
            out.add(first_token[0])
    local = (email or "").split("@")[0].strip()
    if local:
        out.add(local)
        out.add(local.replace(".", " "))
    return {v for v in out if len(v) >= 3}    # 1-2 char tokens match everything


def main() -> None:
    names: set[str] = set()
    n_files = n_clients = 0
    for f in sorted(_DIR.glob("*.speakers.json")):
        n_files += 1
        data = json.loads(f.read_text(encoding="utf-8-sig"))
        for s in data.get("speakers", []):
            email = (s.get("email") or "").lower()
            if s.get("is_rep") or email.endswith("@joveo.com"):
                continue
            n_clients += 1
            names |= variants(s.get("name", ""), email)
    _OUT.write_text("\n".join(sorted(names, key=str.lower)) + "\n", encoding="utf-8")
    print(f"{n_files} roster file(s), {n_clients} client speaker entries, "
          f"{len(names)} name variants -> {_OUT}")


if __name__ == "__main__":
    main()
