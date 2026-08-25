#!/usr/bin/env python3
"""MEASURE the cosine bands in gemini space, so the bge-fitted thresholds can be FLAGGED
with numbers instead of an assertion.

Handoff: Brain/HANDOFF_SHIP_LAYER_AB_2026-08-19.md §2.5 — "Flag, do not silently re-tune."

WHAT THIS IS FOR. Four `layer_b.sink_rescue_*` thresholds are absolute cosine floors fitted
to bge's bands (trigger p10=0.496 p50=0.550 p90=0.613; response p10=0.552 p50=0.635 p90=0.688).
The taxonomy now lives in gemini-embedding-2@3072, whose floor sits higher. A threshold
calibrated on one band and applied to another is not conservative in a predictable direction
-- it is simply unrelated to the distribution it now filters.

THIS SCRIPT CHANGES NOTHING. It measures and prints. Re-tuning these values needs a labelled
sample (the same rule tuning.yaml states for every one of them), not a percentile swap.

Both populations are read from the live database and served from the gateway cache only, so
this is ZERO SPEND and safe to re-run. Response vectors that are not yet cached are skipped
and reported rather than fetched.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/gemini_cosine_bands.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

PCTS = (10, 25, 50, 75, 90)

# The native width the taxonomy was clustered and adjudicated in.
WIDTH = 3072

# The bge bands these thresholds were fitted against, from tuning.yaml's own comments.
BGE_TRIGGER = {10: 0.496, 50: 0.550, 90: 0.613}
BGE_RESPONSE = {10: 0.552, 25: 0.598, 50: 0.635, 75: 0.664, 90: 0.688}


def band(name: str, sims: np.ndarray) -> dict[int, float]:
    vals = {p: float(np.percentile(sims, p)) for p in PCTS}
    print(f"[{name}] n={len(sims):,}  " + "  ".join(f"p{p}={v:.3f}" for p, v in vals.items()))
    return vals


def main() -> None:
    import psycopg

    from calibration.layer_bc_arms import _load_cached, install_embedder_shim
    from config import load_config
    from shared.relative_match import cosine_sims, is_sink_flags
    from shared.scenario_vectors import build_scenario_vecs
    from shared.tuning import load_tuning

    # *** INSTALL THE SHIM BEFORE BUILDING ANY VECTOR. ***
    # Without this, build_scenario_vecs falls through to tuning.yaml's live backend (`local`,
    # i.e. bge@768) while the triggers come from the gemini cache — and the script then
    # happily reports a cosine band computed ACROSS TWO EMBEDDING SPACES. It did exactly that
    # on the first run here: 259 scenarios at "dim 768" and a trigger p50 of 0.065, which is
    # not a low similarity, it is noise between unrelated spaces. The absurd number is the
    # only thing that gave it away, which is why the width assertion below now exists.
    install_embedder_shim(WIDTH)

    url = load_config().database_url
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + "hostaddr=18.138.49.39"
    with psycopg.connect(url, connect_timeout=30, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT scenario_key, scenario_id, business_description, keyphrases, is_coachable,
                   cluster_kind
            FROM scenarios ORDER BY scenario_key
        """)
        rows = cur.fetchall()
        cur.execute("SELECT trigger_text, response_text FROM kb_pairs ORDER BY pair_id")
        pairs = cur.fetchall()

    scenario_map = {
        r[0]: {"scenario_id": r[1], "business_description": r[2], "keyphrases": r[3],
               "is_coachable": r[4], "cluster_kind": r[5]}
        for r in rows
    }
    keys, svecs = build_scenario_vecs(scenario_map)
    is_sink = np.array(is_sink_flags(scenario_map, keys))
    S = np.asarray(svecs, dtype=np.float32)
    print(f"[taxonomy] {len(keys)} scenarios, {int(is_sink.sum())} sinks, dim {S.shape[1]}")
    if S.shape[1] != WIDTH:
        raise SystemExit(
            f"ABORT: scenario vectors are {S.shape[1]}-dim, expected {WIDTH}. The shim did "
            f"not take, so these are LOCAL bge vectors and every cosine below would be "
            f"measured across two different embedding spaces."
        )

    triggers = [p[0] for p in pairs]
    T, missing = _load_cached(triggers, WIDTH)
    if T is None:
        raise SystemExit(f"{len(missing)} trigger(s) not cached — refusing to spend")
    sims = cosine_sims(T, S)
    print(f"\n=== TRIGGER vs SCENARIO (the band relative_margin and "
          f"sink_rescue_trigger_weak_floor were fitted to) ===")
    trig = band("gemini trigger best-match", sims.max(axis=1))
    print("      bge, for comparison:      " +
          "  ".join(f"p{p}={v:.3f}" for p, v in BGE_TRIGGER.items()))

    # The response band needs response vectors; many may still be in flight.
    responses = [p[1] for p in pairs]
    R, miss_r = _load_cached(responses, WIDTH)
    if R is None:
        uniq = len(set(responses))
        have = uniq - len(set(miss_r))
        print(f"\n=== RESPONSE vs SCENARIO: SKIPPED — {len(set(miss_r)):,} of {uniq:,} "
              f"distinct responses are not cached yet ({have:,} are). ===")
        print("    The paced response fetch is what fills these. Re-run this script when it "
              "finishes; it will then measure the response band too. NOT fetching here.")
        resp = None
    else:
        print(f"\n=== RESPONSE vs SCENARIO (the band sink_rescue_response_min_similarity "
              f"was fitted to) ===")
        resp = band("gemini response best-match", cosine_sims(R, S).max(axis=1))
        print("      bge, for comparison:       " +
              "  ".join(f"p{p}={v:.3f}" for p, v in BGE_RESPONSE.items()))

    t = load_tuning().layer_b
    print(f"\n=== THE FOUR bge-FITTED ABSOLUTE FLOORS, AGAINST THE MEASURED GEMINI BANDS ===")
    print(f"    sink_rescue_strategy = {t.sink_rescue_strategy!r}"
          f"{'   <-- NOTHING BELOW IS IN THE LIVE PATH' if t.sink_rescue_strategy == 'none' else ''}")

    def verdict(val: float, b: dict[int, float] | None, label: str) -> None:
        if b is None:
            print(f"    {label:<38} {val:<7} (band not measurable yet)")
            return
        below = [p for p, v in b.items() if val <= v]
        pos = (f"below p{min(below)}" if below and min(below) == min(b)
               else f"between p{max(p for p, v in b.items() if v < val)} and p{min(below)}"
               if below else f"above p{max(b)}")
        note = ""
        if not below:
            note = "  <-- ABOVE THE WHOLE DISTRIBUTION: would filter everything"
        elif min(below) == min(b):
            note = "  <-- BELOW THE WHOLE DISTRIBUTION: filters nothing"
        print(f"    {label:<38} {val:<7} {pos}{note}")

    verdict(t.sink_rescue_trigger_weak_floor, trig, "sink_rescue_trigger_weak_floor")
    verdict(t.sink_rescue_response_min_similarity, resp, "sink_rescue_response_min_similarity")
    print(f"    {'sink_rescue_relative_margin':<38} {t.sink_rescue_relative_margin:<7} "
          f"(relative, not an absolute floor — unaffected by the band shift)")
    print(f"    {'sink_rescue_blend_alpha':<38} {t.sink_rescue_blend_alpha:<7} "
          f"(a weight, not a cosine — unaffected)")

    print("\nFLAGGED, NOT RE-TUNED. Every one of these keys is documented in tuning.yaml as "
          "needing a LABELLED sample, not a percentile. Moving a floor to the new p50 would "
          "repeat the 2026-08-04 round-2 move that this project already recorded as "
          "insufficient. Nothing here is live while sink_rescue_strategy is 'none'.")


if __name__ == "__main__":
    main()
