#!/usr/bin/env python3
"""Persist the null's draw weights ONCE, from PRODUCTION's extraction. Free, zero spend.

Spec: docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md section 4.1

`layer_b_arms.cluster_lift` compares a cluster's account diversity against a size-matched
random draw, and that draw must be COMPOSITION-matched too: a milestone's calls are the calls
that contributed a surviving response clause, so a call contributing many pairs is far likelier
to appear than one contributing a single pair. Rev 3's uniform null was measured to leave a
residual drift (pooled 289-206, p=2.2e-4) that the weighted null removes (247-252, p=0.858).

*** THE WEIGHTS MUST COME FROM PRODUCTION AND NOTHING ELSE. *** They are the yardstick every
arm is measured against. Deriving them per arm would let an arm move the yardstick -- an arm
that routes more pairs into big calls would both raise its own diversity AND raise the
expectation it is compared to, in whatever ratio happened to flatter it. Computing them once
from `v1.layer_b.extract_pairs` makes them a property of the corpus, fixed before any treatment
ran, and identical for every arm including the placebo.

WHY A SEPARATE ARTIFACT RATHER THAN A FIELD ON EACH ARM. Every arm would store its OWN weights,
which is exactly the per-arm yardstick this is written to prevent -- and a reader comparing two
artifacts would have no way to see they had been scored against different nulls. One file, one
provenance record, cited by every scoring run.

Costs one spaCy pass (~4 min). Run once; re-run only if the corpus changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OUT = ARTIFACTS_DIR / "null_draw_weights.json"


def build(recordings: str) -> dict:
    from config import load_config
    from preprocessing.transcript_parser import parse_transcript, load_roster
    from v1.layer_b import extract_pairs
    from calibration.layer_b_arms import call_stem

    cfg = load_config()
    files = sorted(Path(recordings).glob("*.txt"))
    if not files:
        raise SystemExit(f"no transcripts in {recordings}/")

    weights: dict[str, int] = {}
    h = hashlib.sha256()
    n_pairs = 0
    for n, path in enumerate(files, 1):
        turns = parse_transcript(str(path), cfg.joveo_speakers_lower, cfg.naren_name_lower,
                                 roster=load_roster(str(path)))
        got = extract_pairs(turns, n)
        # Every call gets an entry, INCLUDING zero. A call that production never pairs cannot
        # back a milestone, and the audit measured that exactly: the 17 accounted calls with
        # zero production pairs appear in ZERO cluster unions. Omitting them would make
        # `weights.get(stem, 0.0)` silently indistinguishable from "this call is not in the
        # corpus", which is a different fact.
        weights[call_stem(path.name)] = len(got)
        n_pairs += len(got)
        h.update(f"{path.name}|{len(got)}\n".encode("utf-8"))
        if n % 100 == 0 or n == len(files):
            print(f"  {n}/{len(files)} calls, {n_pairs} pairs", flush=True)

    return {
        "source": "v1.layer_b.extract_pairs (PRODUCTION, s0/a0)",
        "recordings": recordings,
        "n_calls": len(files),
        "n_pairs": n_pairs,
        "n_zero_pair_calls": sum(1 for v in weights.values() if v == 0),
        "weights_sha": h.hexdigest()[:16],
        "weights": weights,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--overwrite", action="store_true")
    a = p.parse_args()

    if OUT.exists() and not a.overwrite:
        art = json.loads(OUT.read_text(encoding="utf-8-sig"))
        raise SystemExit(
            f"{OUT.name} already exists ({art['n_calls']} calls, {art['n_pairs']} pairs, "
            f"sha {art['weights_sha']}). Pass --overwrite ONLY if the corpus changed -- "
            f"rebuilding these silently would re-score every published arm against a "
            f"different yardstick.")

    art = build(a.recordings)
    OUT.write_text(json.dumps(art, indent=1), encoding="utf-8")
    print(f"\n{art['n_calls']} calls, {art['n_pairs']} pairs, "
          f"{art['n_zero_pair_calls']} with ZERO pairs (they can never back a milestone)")
    print(f"sha {art['weights_sha']}  ->  {OUT}")


if __name__ == "__main__":
    main()
