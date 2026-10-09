#!/usr/bin/env python3
"""POST-HOC, NOT PRE-REGISTERED: survival of the CONJUNCTION filter (p40 AND rank(8)).

Motivated by reading lcfr_t1_read_samples.txt AFTER the pre-registered stages ran: the two
filters fail on opposite axes -- rank(8) rejects mis-routing but admits filler whose weak
preference points home; p40 rejects filler but is blind to routing. If that reading is
right, the conjunction should discriminate routing (rank's property) while its kept-set
carries p40's junk rejection. This script measures ONLY the survival table for the
conjunction, labelled post-hoc; it feeds a follow-up pre-registration, never an adoption.

Zero chat, cache-only embeddings, zero Postgres. Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/lcfr_posthoc_conjunction.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR
from calibration.lcfr_common import (load_substrate, permuted_by_key, coachable_matrix,
                                     keep_rank)
from calibration.layer_c_relative_filter import build_pools, embed_union, pool_matrix

RANK_K = 8  # the instrument's chosen operating point


def main() -> None:
    from v2.layer_c import _relevance_filter

    sub = load_substrate()
    rng = random.Random(42)
    keys_c, S = coachable_matrix(sub)
    pos_of = {k: i for i, k in enumerate(keys_c)}
    real = build_pools(sub.by_key)
    perm = build_pools(permuted_by_key(sub, rng))
    vec_of = embed_union([real, perm])
    pct = sub.tuning.layer_c.milestone_relevance_percentile

    out = {}
    for arm, pools in (("real", real), ("perm", perm)):
        kept = tot = 0
        for k, pool in sorted(pools.items()):
            C = pool_matrix(pool, vec_of)
            n = len(pool["clauses"])
            kept_p40 = set(_relevance_filter(
                list(range(n)), C, pool["positions"], pool["calls"], pool["pair_ids"],
                sub.scenario_map[k], pct)[0])
            mask = keep_rank(C @ S.T, pos_of[k], RANK_K)
            kept += sum(1 for i in range(n) if i in kept_p40 and mask[i])
            tot += n
        out[arm] = {"kept": kept, "total": tot, "survival": kept / tot}
        print(f"  {arm}: {kept}/{tot} = {kept/tot:.3f}")
    gap = out["real"]["survival"] - out["perm"]["survival"]
    print(f"  conjunction gap: {100*gap:.1f}pp (rank(8) alone was 20.0; p40 alone 0.0)")
    (ARTIFACTS_DIR / "lcfr_posthoc_conjunction.json").write_text(
        json.dumps({"rank_k": RANK_K, "post_hoc": True, **out, "gap": gap}, indent=1),
        encoding="utf-8")


if __name__ == "__main__":
    main()
