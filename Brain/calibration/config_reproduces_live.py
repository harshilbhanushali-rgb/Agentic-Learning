#!/usr/bin/env python3
"""PROVE tuning.yaml AS SHIPPED reproduces the LIVE Layer B routing, end to end.

Written 2026-08-19 alongside the config-reality repair (pool_unit clause->turn,
merge_cosine_threshold 0.85->0.97, embedding.backend local->gateway).

WHAT THIS ANSWERS. Those three values were changed so that main.py describes the system that
is actually in Postgres rather than a different one. That claim is only worth anything if it
is checked, and the checkable half is Layer B: production `assign_scenarios`, driven ONLY by
tuning.yaml with no calibration shim installed, must assign every one of the 12,444 live pairs
the same `scenario_key` that is stored in `kb_pairs`.

THE SHIM IS DELIBERATELY NOT INSTALLED. Every other harness in this directory reaches the
gemini vectors through `layer_bc_arms.install_embedder_shim`. This one must not: the entire
point is to exercise the path a real run takes -- config -> embedder -> backend -> cache. If
this passes only with a shim, production is still misconfigured and the shim is hiding it.

ZERO SPEND, ENFORCED. The gateway transport is monkeypatched to raise, so a cache miss fails
the run instead of quietly buying vectors. Layer A is NOT re-clustered here (that is a
multi-hour job and would rewrite the taxonomy); this verifies the routing half, which is the
half that has a stored ground truth to compare against.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/config_reproduces_live.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    import psycopg

    from config import load_config
    from shared import gateway
    from shared.tuning import load_tuning

    t = load_tuning()
    print(f"[config] pool_unit={t.layer_a.pool_unit}  "
          f"merge={t.layer_a.merge_cosine_threshold}  backend={t.embedding.backend}  "
          f"dims={t.embedding.gemini_dimensions}")
    print(f"[config] relative_margin={t.layer_b.relative_margin}  "
          f"cap={t.layer_b.max_scenarios_per_pair}  "
          f"sink_margin_delta={t.layer_b.sink_margin_delta}")
    if t.embedding.backend == "local":
        raise SystemExit(
            "backend is 'local' — this harness exists to verify the HOSTED config against "
            "the live database, and the live vectors are gemini@3072."
        )

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
        cur.execute("SELECT pair_id, trigger_text, scenario_key FROM kb_pairs ORDER BY pair_id")
        stored = cur.fetchall()

    scenario_map = {
        r[0]: {"scenario_id": r[1], "business_description": r[2], "keyphrases": r[3],
               "is_coachable": r[4], "cluster_kind": r[5]}
        for r in rows
    }
    print(f"[db] {len(scenario_map)} scenarios, {len(stored):,} stored pairs")

    pairs = [{"trigger_text": s[1], "response_text": "", "scenario_key": None,
              "scenario_id": None} for s in stored]

    # Fail rather than spend. A miss here would mean the shipped config cannot serve this
    # corpus from cache, which is itself the finding.
    real_client = gateway.GatewayClient

    def _explode(*a, **k):
        raise AssertionError(
            "THE SHIPPED CONFIG TRIED TO EMBED. Something in this corpus is not in the "
            "gateway cache, so a real run would have spent."
        )

    gateway.GatewayClient = _explode
    try:
        from v1 import layer_b
        layer_b.assign_scenarios(pairs, scenario_map, config=None)
    finally:
        gateway.GatewayClient = real_client

    mismatched = [
        (s[0], s[1][:70], s[2], p["scenario_key"])
        for s, p in zip(stored, pairs) if s[2] != p["scenario_key"]
    ]
    n = len(stored)
    sinks = sum(1 for p in pairs if not scenario_map[p["scenario_key"]]["is_coachable"])
    print(f"[route] sink share {100.0 * sinks / n:.1f}%  "
          f"(the live ship recorded 47.5%; G-R2 measured 47.3% / 48.1%)")

    if mismatched:
        print(f"\nMISMATCH on {len(mismatched):,}/{n:,} pairs — tuning.yaml as shipped does "
              f"NOT reproduce the live routing.")
        for pid, text, want, got in mismatched[:10]:
            print(f"  pair {pid}: {text!r}\n    stored: {want}\n    config: {got}")
        raise SystemExit(1)

    print(f"\nIDENTICAL on {n:,}/{n:,} pairs. tuning.yaml AS SHIPPED — no shim, no override — "
          f"reproduces the live Layer B routing exactly, and spent nothing doing it.")


if __name__ == "__main__":
    main()
