#!/usr/bin/env python3
"""One-off comparison of Layer B's flat vs. two-stage (strict/soft/fallback)
matching against the real 60-call subset run's committed data.

Read-only against Postgres: pulls the already-stored flat scenario_key/
scenario_keys per kb_pair (production always writes flat -- matching_strategy
stays 'flat'), then re-runs assign_scenarios_two_stage in memory for each
strategy over the same real trigger texts and compares. No DB writes, no
Gemma calls (embedder calls go through the disk cache).

This is a smaller, ad-hoc stand-in for the design's future
--matching-compare extension to dry_run_layer_bc.py, scoped to the one-time
question this 60-call subset run exists to answer, not a permanent tool.
"""
from __future__ import annotations
import sys
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

# Brain/ is this file's parent -- put it on sys.path so the shared packages
# (config, shared, v1, v2, preprocessing) resolve whether this script is run
# directly (python calibration/x.py) or imported (from calibration import x).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import load_config
from shared import storage
from v1 import layer_b


def _load_real_pairs(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pair_id, trigger_text, scenario_key, scenario_keys FROM kb_pairs ORDER BY pair_id"
        )
        rows = cur.fetchall()
    return [
        {"pair_id": r[0], "trigger_text": r[1], "flat_key": r[2], "flat_keys": r[3]}
        for r in rows
    ]


def _fresh_pairs(real_pairs: list[dict]) -> list[dict]:
    return [
        {"trigger_text": p["trigger_text"], "response_text": "", "scenario_key": None, "scenario_id": None}
        for p in real_pairs
    ]


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def _report(strategy: str, real_pairs: list[dict], assigned: list[dict]) -> None:
    n = len(real_pairs)
    agree_top1 = sum(1 for r, a in zip(real_pairs, assigned) if r["flat_key"] == a["scenario_key"])
    jaccards = [_jaccard(r["flat_keys"], a["scenario_keys"]) for r, a in zip(real_pairs, assigned)]
    mean_jaccard = sum(jaccards) / n if n else 0.0
    flat_top1_recovered = sum(
        1 for r, a in zip(real_pairs, assigned) if r["flat_key"] in a["scenario_keys"]
    )
    match_counts = [len(a["scenario_keys"]) for a in assigned]
    mean_matches = sum(match_counts) / n if n else 0.0
    one_match = sum(1 for c in match_counts if c == 1) / n if n else 0.0

    print(f"\n=== {strategy} vs flat ({n} pairs) ===")
    print(f"  top-1 agreement with flat      : {agree_top1}/{n} ({agree_top1/n:.1%})")
    print(f"  flat's top-1 recovered anywhere: {flat_top1_recovered}/{n} ({flat_top1_recovered/n:.1%})"
          f"  <- proxy for recall loss (lower = more loss)")
    print(f"  mean Jaccard(scenario_keys)    : {mean_jaccard:.3f}")
    print(f"  mean match count               : {mean_matches:.2f}")
    print(f"  1-match pairs                  : {one_match:.1%}")


def _sweep_fallback_floor(real_pairs: list[dict], scenario_map: dict, primary_topic_map: dict) -> None:
    """Sweep two_stage_fallback_floor without touching tuning.yaml.

    Runs Strict's stage-1/stage-2 logic once to capture each pair's
    (strict_kept, top1_sim), then recomputes the Fallback reroute decision in
    plain Python for each candidate floor against the pair's REAL flat
    assignment (no re-embedding, no repeated tuning.yaml edits).

    IMPORTANT caveat proven by this sweep's own output (see design doc's
    Status update 3): raising the floor mechanically raises the recall-proxy
    number because a rerouted pair is scored against its own real flat
    assignment, which trivially "recovers" it. This is not evidence a higher
    floor is more ACCURATE -- it is evidence more pairs stopped using the
    two-stage result at all. Do not pick a floor by maximizing this number.
    """
    import numpy as np
    from shared.scenario_vectors import build_scenario_vecs, build_primary_topic_vecs
    from shared.tuning import load_tuning
    from preprocessing import embedder
    from v1.layer_b import _topk_pick

    tuning = load_tuning().layer_b
    trigger_texts = [p["trigger_text"] for p in real_pairs]
    trigger_vecs = embedder.embed_query(trigger_texts)

    scenario_keys, scenario_vecs = build_scenario_vecs(scenario_map)
    is_sink = [not scenario_map[k].get("is_coachable", True) for k in scenario_keys]
    pt_of = [scenario_map[k].get("primary_topic_key") for k in scenario_keys]
    pt_keys, pt_vecs = build_primary_topic_vecs(primary_topic_map)
    no_sink = [False] * len(pt_keys)

    T_norm = np.array(trigger_vecs)
    T_norm = T_norm / (np.linalg.norm(T_norm, axis=1, keepdims=True) + 1e-10)
    S_norm = np.array(scenario_vecs)
    S_norm = S_norm / (np.linalg.norm(S_norm, axis=1, keepdims=True) + 1e-10)
    PT_norm = np.array(pt_vecs)
    PT_norm = PT_norm / (np.linalg.norm(PT_norm, axis=1, keepdims=True) + 1e-10)
    sim_matrix = T_norm @ S_norm.T
    pt_sim_matrix = T_norm @ PT_norm.T

    n = len(real_pairs)
    strict_kept_list, top1_sim_list, is_sink_pair = [], [], []
    for i in range(n):
        sims = sim_matrix[i]
        best_j = int(np.argsort(sims)[::-1][0])
        if is_sink[best_j]:
            strict_kept_list.append([scenario_keys[best_j]])
            top1_sim_list.append(float(sims[best_j]))
            is_sink_pair.append(True)
            continue
        is_sink_pair.append(False)
        kept_pt = set(_topk_pick(
            pt_sim_matrix[i], pt_keys, no_sink,
            tuning.max_primary_topics_per_pair, tuning.primary_topic_relative_margin,
        ) or [])
        restrict_to = {j for j, pt in enumerate(pt_of) if pt in kept_pt}
        strict_kept = _topk_pick(
            sims, scenario_keys, is_sink, tuning.max_scenarios_per_pair,
            tuning.relative_margin, restrict_to=restrict_to,
        ) or [scenario_keys[best_j]]
        strict_kept_list.append(strict_kept)
        top1_sim_list.append(float(sims[scenario_keys.index(strict_kept[0])]))

    non_sink_top1 = np.array(top1_sim_list)[~np.array(is_sink_pair)]
    print(f"\n=== two_stage_fallback_floor sweep ({n} pairs, {non_sink_top1.size} non-sink) ===")
    print("Strict top1_sim percentiles (non-sink pairs only):")
    print("  " + "  ".join(f"p{p}={np.percentile(non_sink_top1, p):.3f}" for p in (10, 25, 40, 50, 75, 90)))
    print(f"\n{'floor':>6}  {'reroute%':>9}  {'agree1':>8}  {'recall_proxy':>13}  {'mean_jac':>9}")
    for floor in (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70):
        agree = recall_ok = reroute = 0
        jaccards = []
        for i, r in enumerate(real_pairs):
            if is_sink_pair[i]:
                kept = strict_kept_list[i]
            elif top1_sim_list[i] < floor:
                kept = r["flat_keys"]
                reroute += 1
            else:
                kept = strict_kept_list[i]
            if kept and kept[0] == r["flat_key"]:
                agree += 1
            if r["flat_key"] in kept:
                recall_ok += 1
            jaccards.append(_jaccard(r["flat_keys"], kept))
        print(f"{floor:>6.2f}  {reroute/n:>8.1%}  {agree/n:>7.1%}  {recall_ok/n:>12.1%}  {sum(jaccards)/n:>9.3f}")


def main() -> None:
    config = load_config()
    conn = storage.get_connection(config.database_url)

    scenario_rows = storage.get_scenarios(conn)
    scenario_map = {r["scenario_key"]: r for r in scenario_rows}
    pt_rows = storage.get_primary_topics(conn)
    primary_topic_map = {r["primary_topic_key"]: r for r in pt_rows}
    real_pairs = _load_real_pairs(conn)
    conn.close()

    print(f"Loaded {len(scenario_map)} scenario(s), {len(primary_topic_map)} primary_topic(s), "
          f"{len(real_pairs)} pair(s).")
    if not primary_topic_map:
        print("primary_topics is empty -- nothing to compare. Did the subset pipeline run finish?")
        sys.exit(1)

    for strategy in ("strict", "soft", "fallback"):
        pairs = _fresh_pairs(real_pairs)
        layer_b.assign_scenarios_two_stage(pairs, scenario_map, primary_topic_map, config=None, strategy=strategy)
        _report(strategy, real_pairs, pairs)

    if "--sweep-floor" in sys.argv:
        _sweep_fallback_floor(real_pairs, scenario_map, primary_topic_map)


if __name__ == "__main__":
    main()
