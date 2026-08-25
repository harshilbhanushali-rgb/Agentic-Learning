#!/usr/bin/env python3
"""PROVE `flat_pick(delta=0.0)` IS BYTE-IDENTICAL TO assign_scenarios' INLINE PICK LOOP,
against REAL scenario rows and REAL trigger vectors.

Handoff: Brain/HANDOFF_SHIP_LAYER_AB_2026-08-19.md §2.3
Spec:    docs/superpowers/specs/2026-08-19-playbook-schema-design.md (§9, appended)

WHY THIS EXISTS. `sink_margin_delta` was added to `shared/relative_match.flat_pick` and
`tuning.yaml` at 0.0, with 400 randomized synthetic cases proving delta=0.0 is a no-op. But
`v1.layer_b.assign_scenarios` never calls `flat_pick` -- it carries its own inline copy of the
pick logic -- so the knob is INERT ON THE PRIMARY PATH. Wiring it is only safe if the
substitution provably changes nothing at the shipped value, and the existing proof is over
synthetic unit vectors. This runs the same comparison over the live corpus:

  * REAL scenario rows: all 259 from Postgres, with their real `is_coachable` flags, so the
    sink/coachable split is the production one rather than a hand-built one.
  * REAL triggers: the 12,444 `kb_pairs.trigger_text` values already in the database.
  * REAL vectors: served from the gemini gateway cache only. ZERO SPEND -- the shim ABORTS on
    a cache miss rather than quietly paying for an embed.

The two implementations are compared per pair on the FULL ordered key list, not just the
top-1: `scenario_keys` is what lands in Postgres and drives multi-label routing, so an
agreement on `scenario_key` alone would be a weaker claim than the one being made.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/sink_margin_delta_identity.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402


def inline_pick_as_shipped(sims, keys, is_sink_arr, cap, margin) -> list[str]:
    """The pick loop EXACTLY as it stands in v1/layer_b.assign_scenarios today.

    Copied deliberately rather than imported: the whole point is to compare the incumbent
    against its replacement, so this must keep working after assign_scenarios is rewired.
    Any future divergence between this and the shipped loop makes the proof stale, which is
    why the test suite pins the shipped loop to flat_pick as well.
    """
    order = np.argsort(sims)[::-1]
    best_j = int(order[0])
    if is_sink_arr[best_j]:
        return [keys[best_j]]
    cutoff = margin * float(sims[best_j])
    kept = [
        keys[int(j)] for j in order[:cap]
        if float(sims[int(j)]) >= cutoff and not is_sink_arr[int(j)]
    ]
    return kept or [keys[best_j]]


def main() -> None:
    from calibration.layer_bc_arms import install_embedder_shim
    from config import load_config
    from shared.relative_match import cosine_sims, flat_pick, is_sink_flags
    from shared.scenario_vectors import build_scenario_vecs
    from shared.tuning import load_tuning

    import psycopg

    tuning = load_tuning().layer_b
    cap, margin = tuning.max_scenarios_per_pair, tuning.relative_margin
    delta = tuning.sink_margin_delta
    print(f"[tuning] cap={cap} margin={margin} sink_margin_delta={delta}")
    if delta != 0.0:
        raise SystemExit(
            f"sink_margin_delta is {delta}, not 0.0 — this harness proves the NO-OP case. "
            f"A non-zero value is a behaviour change and needs a judged sample, not this."
        )

    url = load_config().database_url
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + "hostaddr=18.138.49.39"

    with psycopg.connect(url, connect_timeout=30, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT scenario_key, scenario_id, business_description, keyphrases,
                       is_coachable, cluster_kind
                FROM scenarios ORDER BY scenario_key
            """)
            rows = cur.fetchall()
            cur.execute("SELECT trigger_text FROM kb_pairs ORDER BY pair_id")
            triggers = [r[0] for r in cur.fetchall()]

    scenario_map = {
        r[0]: {
            "scenario_id": r[1], "business_description": r[2], "keyphrases": r[3],
            "is_coachable": r[4], "cluster_kind": r[5],
        }
        for r in rows
    }
    print(f"[db] {len(scenario_map)} scenarios "
          f"({sum(1 for v in scenario_map.values() if v['is_coachable'])} coachable), "
          f"{len(triggers)} triggers")
    if not scenario_map or not triggers:
        raise SystemExit("empty taxonomy or empty kb_pairs — nothing to prove")

    install_embedder_shim(3072)
    from preprocessing import embedder

    keys, svecs = build_scenario_vecs(scenario_map)
    is_sink = is_sink_flags(scenario_map, keys)
    print(f"[vectors] {len(keys)} scenario vectors, {sum(is_sink)} sinks")

    T = embedder.embed_query_matrix(triggers)
    print(f"[vectors] {T.shape[0]} trigger vectors from cache (zero spend)")

    S = np.asarray(svecs, dtype=float)
    sims = cosine_sims(T, S)

    mismatches = []
    for i in range(sims.shape[0]):
        old = inline_pick_as_shipped(sims[i], keys, is_sink, cap, margin)
        new = flat_pick(sims[i], keys, is_sink, cap, margin, delta)
        if old != new:
            mismatches.append((i, triggers[i][:80], old, new))

    n = sims.shape[0]
    print()
    if mismatches:
        print(f"MISMATCH on {len(mismatches)}/{n} pairs — flat_pick is NOT a drop-in "
              f"replacement at delta={delta}. NOT WIRING IT.")
        for i, text, old, new in mismatches[:10]:
            print(f"  pair {i}: {text!r}\n    inline: {old}\n    flat  : {new}")
        raise SystemExit(1)

    print(f"IDENTICAL on {n}/{n} pairs — full ordered scenario_keys list, not just top-1.")
    print(f"flat_pick(delta={delta}) is a byte-identical drop-in for the inline loop against "
          f"REAL scenario rows and REAL trigger vectors.")


if __name__ == "__main__":
    main()
