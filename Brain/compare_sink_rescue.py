#!/usr/bin/env python3
"""Zero-Gemma comparison of the five sink-rescue strategies (response_only /
or_rule / blended / content_gate_narrow / content_gate_broad) from
docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md against the
real, already-populated corpus.

Read-only against Postgres: trigger_text and response_text are real columns on
kb_pairs, so no Pinecone read is needed. Re-runs assign_scenarios_with_sink_rescue
in memory for each strategy over the same real texts. No DB writes, no Gemma calls
-- embedder calls go through the disk cache, which is warm for this corpus.

The content_gate_narrow/broad strategies additionally need each pair's
preceding_turn_is_question signal, which requires re-parsing the source
transcript (kb_pairs only stores call_id/turn_index, not the turn list) --
see _attach_preceding_turn_is_question. This is a new, real dependency on
recordings/ or csm_recordings/ that the response_only/or_rule/blended-only
version of this script did not have.
"""
from __future__ import annotations
import json
import random
import sys
from collections import Counter
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np

from config import load_config
from preprocessing import embedder
from preprocessing.transcript_parser import parse_transcript, load_roster
from shared import storage, trigger_quality
from shared.scenario_vectors import build_scenario_vecs
from v1 import layer_b


def _load_real_pairs(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.pair_id, p.trigger_text, p.response_text, p.scenario_key, "
            "p.call_id, p.turn_index, c.filename "
            "FROM kb_pairs p JOIN calls c ON c.call_id = p.call_id "
            "ORDER BY p.pair_id"
        )
        rows = cur.fetchall()
    return [
        {"pair_id": r[0], "trigger_text": r[1], "response_text": r[2], "flat_key": r[3],
         "call_id": r[4], "turn_index": r[5], "filename": r[6]}
        for r in rows
    ]


def _locate_transcript(filename: str) -> Path:
    for directory in ("recordings", "csm_recordings"):
        candidate = Path(directory) / filename
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"transcript {filename!r} not found in recordings/ or csm_recordings/ -- "
        "needed to reconstruct turns for preceding_turn_is_question"
    )


def _attach_preceding_turn_is_question(real_pairs: list[dict], config) -> None:
    by_filename: dict[str, list[dict]] = {}
    for p in real_pairs:
        by_filename.setdefault(p["filename"], []).append(p)

    print(f"\nRe-parsing {len(by_filename)} transcript(s) for preceding_turn_is_question...")
    for filename, group in by_filename.items():
        txt_path = _locate_transcript(filename)
        turns = parse_transcript(
            str(txt_path), config.joveo_speakers_lower, config.naren_name_lower,
            roster=load_roster(str(txt_path)),
        )
        for p in group:
            p["preceding_turn_is_question"] = trigger_quality.preceding_turn_is_question(
                turns, p["turn_index"]
            )


def _fresh_pairs(real_pairs: list[dict]) -> list[dict]:
    return [
        {"trigger_text": p["trigger_text"], "response_text": p["response_text"],
         "scenario_key": None, "scenario_id": None,
         "preceding_turn_is_question": p["preceding_turn_is_question"]}
        for p in real_pairs
    ]


def _print_response_similarity_percentiles(real_pairs: list[dict], scenario_map: dict) -> None:
    scenario_keys, scenario_vecs = build_scenario_vecs(scenario_map)
    is_sink = [not scenario_map[k].get("is_coachable", True) for k in scenario_keys]
    non_sink_cols = [j for j, s in enumerate(is_sink) if not s]

    response_vecs = embedder.embed_document([p["response_text"] for p in real_pairs])
    R = np.array(response_vecs)
    S = np.array(scenario_vecs)
    R_norm = R / (np.linalg.norm(R, axis=1, keepdims=True) + 1e-10)
    S_norm = S / (np.linalg.norm(S, axis=1, keepdims=True) + 1e-10)
    sims = R_norm @ S_norm.T
    best_non_sink = sims[:, non_sink_cols].max(axis=1)

    print("\nResponse-vs-scenario best-match similarity, non-sink candidates only "
          f"({len(real_pairs)} pairs):")
    print("  " + "  ".join(
        f"p{p}={np.percentile(best_non_sink, p):.3f}" for p in (10, 25, 50, 75, 90)
    ))


def _report(strategy: str, real_pairs: list[dict], scenario_map: dict, assigned: list[dict]) -> None:
    is_sink_today = [not scenario_map[p["flat_key"]]["is_coachable"] for p in real_pairs]
    sink_idx = [i for i, s in enumerate(is_sink_today) if s]
    non_sink_idx = [i for i, s in enumerate(is_sink_today) if not s]

    rescued_idx = [i for i in sink_idx if scenario_map[assigned[i]["scenario_key"]]["is_coachable"]]
    non_sink_touched_idx = [
        i for i in non_sink_idx if assigned[i]["scenario_key"] != real_pairs[i]["flat_key"]
    ]

    print(f"\n=== {strategy} ===")
    if sink_idx:
        print(f"  sink-bound pairs today      : {len(sink_idx)}")
        print(f"  rescued to a real scenario  : {len(rescued_idx)} "
              f"({len(rescued_idx)/len(sink_idx):.1%})")
        top = Counter(assigned[i]["scenario_key"] for i in rescued_idx).most_common(10)
        if top:
            print("  top scenarios absorbing rescued pairs:")
            for key, count in top:
                print(f"    {key}: {count}")
    else:
        print("  sink-bound pairs today      : 0 (nothing to rescue)")
    print(f"  non-sink pairs also changed : {len(non_sink_touched_idx)} / {len(non_sink_idx)}")

    rng = random.Random(0)
    if rescued_idx:
        print("\n  20 random rescued pairs:")
        for i in rng.sample(rescued_idx, min(20, len(rescued_idx))):
            p, a = real_pairs[i], assigned[i]
            print(f"    [{p['pair_id']}] trigger : {p['trigger_text'][:100]!r}")
            print(f"        response: {p['response_text'][:150]!r}")
            print(f"        -> {a['scenario_key']} (was sink: {p['flat_key']})")

    still_sink_idx = [i for i in sink_idx if i not in rescued_idx]
    if still_sink_idx:
        print("\n  10 random pairs still in a sink (near-miss check):")
        for i in rng.sample(still_sink_idx, min(10, len(still_sink_idx))):
            p = real_pairs[i]
            print(f"    [{p['pair_id']}] trigger : {p['trigger_text'][:100]!r}")
            print(f"        response: {p['response_text'][:150]!r}")
            print(f"        -> stays in {p['flat_key']}")


def main() -> None:
    config = load_config()
    conn = storage.get_connection(config.database_url)

    scenario_rows = storage.get_scenarios(conn)
    scenario_map = {r["scenario_key"]: r for r in scenario_rows}
    real_pairs = _load_real_pairs(conn)
    conn.close()

    print(f"Loaded {len(scenario_map)} scenario(s), {len(real_pairs)} pair(s).")
    if not scenario_map or not real_pairs:
        print("scenarios or kb_pairs is empty -- nothing to compare. Did a pipeline run finish?")
        sys.exit(1)

    _print_response_similarity_percentiles(real_pairs, scenario_map)

    labels_path = Path(__file__).parent / "trigger_quality_labels.json"
    if labels_path.exists():
        labeled = json.loads(labels_path.read_text(encoding="utf-8"))
        coachable = sorted(e["concrete_entity_density"] for e in labeled if e["coachable"])
        junk = sorted(e["concrete_entity_density"] for e in labeled if not e["coachable"])

        def _pct(values, p):
            if not values:
                return float("nan")
            idx = min(len(values) - 1, int(len(values) * p / 100))
            return values[idx]

        print(f"\nconcrete_entity_density(response), labeled coachable (n={len(coachable)}):")
        print("  " + "  ".join(f"p{p}={_pct(coachable, p):.3f}" for p in (10, 25, 50, 75, 90)))
        print(f"concrete_entity_density(response), labeled NOT coachable (n={len(junk)}):")
        print("  " + "  ".join(f"p{p}={_pct(junk, p):.3f}" for p in (10, 25, 50, 75, 90)))
    else:
        print(f"\n({labels_path.name} not found -- run label_trigger_quality_sample.py first "
              "for the label-split density view.)")

    _attach_preceding_turn_is_question(real_pairs, config)

    for strategy in ("response_only", "or_rule", "blended", "content_gate_narrow", "content_gate_broad"):
        pairs = _fresh_pairs(real_pairs)
        layer_b.assign_scenarios_with_sink_rescue(pairs, scenario_map, config=None, strategy=strategy)
        _report(strategy, real_pairs, scenario_map, pairs)


if __name__ == "__main__":
    main()
