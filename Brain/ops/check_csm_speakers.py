#!/usr/bin/env python3
"""Which speakers in csm_recordings/ are not classified by config?

FAILS OPEN IS THE PROBLEM. transcript_parser resolves a speaker to CSM via mapping.csv's
csm_name, to OTHER_JOVEO via JOVEO_SPEAKER_NAMES, and to CLIENT otherwise. So an unlisted
Joveo colleague is treated as THE CLIENT -- their internal chatter becomes client turns,
which become coaching signals, which get scored and written to gap_events as findings about
a CSM. There is no error and nothing looks wrong.

14 such speakers were caught on the first 106-call pull. This makes that check repeatable
and cheap, so it runs before every batch rather than once.

Read-only: no DB, no Gemma, no writes. Prints names only -- never the .env values.

Usage (from Brain/):
    python ops/check_csm_speakers.py
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config  # noqa: E402

_DIR = Path(__file__).resolve().parent.parent / "csm_recordings"


def speakers_in(path: Path) -> Counter:
    """Speaker lines in the blank-line-separated Name/Utterance format.

    A speaker line is a short line followed by a non-blank line, with no trailing
    punctuation -- the same shape transcript_parser keys on.
    """
    text = path.read_text(encoding="utf-8-sig")
    found: Counter = Counter()
    blocks = [b for b in text.split("\n\n") if b.strip()]
    for block in blocks:
        first = block.strip().split("\n")[0].strip()
        if first and len(first) < 60 and not first.endswith((".", "?", "!", ",")):
            found[first] += 1
    return found


def main() -> None:
    cfg = load_config()
    joveo = set(cfg.joveo_speakers_lower)
    naren = cfg.naren_name_lower

    mapping = _DIR / "mapping.csv"
    csm_names = set()
    if mapping.exists():
        with open(mapping, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("csm_name") or "").strip().lower()
                if name:
                    csm_names.add(name)

    files = sorted(_DIR.glob("*.txt"))
    print(f"transcripts        : {len(files)}")
    print(f"JOVEO_SPEAKER_NAMES: {len(joveo)} configured")
    print(f"mapping.csv csm_name: {len(csm_names)} distinct")

    all_speakers: Counter = Counter()
    per_file: dict[str, set] = {}
    for f in files:
        found = speakers_in(f)
        all_speakers.update(found)
        per_file[f.name] = set(k.lower() for k in found)

    known = joveo | csm_names | {naren}
    unknown = {s: n for s, n in all_speakers.items() if s.lower() not in known}

    print(f"\ndistinct speakers   : {len(all_speakers)}")
    print(f"classified          : {len(all_speakers) - len(unknown)}")
    print(f"UNCLASSIFIED        : {len(unknown)}  <- these are treated as THE CLIENT")

    if unknown:
        print("\nUnclassified speakers, by how many turns they hold:")
        print("(a real client is expected here; a Joveo colleague is a data bug)")
        for name, n in sorted(unknown.items(), key=lambda kv: -kv[1])[:40]:
            files_with = sum(1 for s in per_file.values() if name.lower() in s)
            print(f"  {n:>5} turns  in {files_with:>3} files   {name}")

    missing_map = [f.name for f in files
                   if not (per_file[f.name] & csm_names)]
    if missing_map:
        print(f"\n{len(missing_map)} transcripts contain NO mapped csm_name -- Layer D"
              " cannot attribute a CSM in these:")
        for name in missing_map[:15]:
            print(f"  {name}")


if __name__ == "__main__":
    main()
