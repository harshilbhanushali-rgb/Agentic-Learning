#!/usr/bin/env python3
"""Phase 2 of docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md.

Generalizes diagnose_sink_pool.py's response-clustering technique from "sink pool + a
volume-matched control sample" to EVERY response in the corpus (~4,605 kb_pairs rows), to
measure whether the response-taxonomy gap is bigger than the two clusters already graduated
by graduate_sink_topics.py.

Zero DB writes. Same clustering call (v2.layer_c._cluster_milestones,
cluster_evidence.milestone_min_cluster_size) and the same three-way verdict prompt
(PROMPT_SINK_POOL_TRIAGE) diagnose_sink_pool.py already validated -- no new clustering
machinery, no new adjudication prompt.

Key difference from diagnose_sink_pool.py: instead of a binary sink/control mix_ratio, each
cluster reports its CURRENT scenario_key composition (which may span several coachable
scenarios, several sinks, or both). A cluster is skipped from adjudication only when one
coachable scenario already dominates it above response_taxonomy_purity_gate -- a cluster
dominated by a SINK is deliberately NOT skipped; see cluster_evidence.purity_gate_verdict.

Does NOT decide whether to build a permanent recurring pass -- that is a distinct follow-up
design, contingent on what this run finds.

Usage (from Brain/, venv active):
    python dry_run_response_taxonomy.py
    python dry_run_response_taxonomy.py --no-gemma
    python dry_run_response_taxonomy.py --load dry_run_response_taxonomy.json
"""
from __future__ import annotations
import argparse
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np

from config import load_config
from preprocessing import embedder
from shared import cluster_evidence, storage
from shared.gemma import call_gemma
from shared.prompts import PROMPT_SINK_POOL_TRIAGE
from shared.scenario_vectors import build_scenario_vecs
from shared.tuning import load_tuning
from v2.layer_c import _cluster_milestones

_BATCH_SIZE = 5
_GEMMA_CALL_DELAY = 5
_SAMPLES_PER_CLUSTER = 4
_SAMPLE_CHARS = 300
_DEFAULT_OUTPUT = Path("dry_run_response_taxonomy.json")


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--load", type=Path, default=None)
    p.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    p.add_argument("--no-gemma", action="store_true")
    p.add_argument("--min-cluster-size", type=int, default=None)
    p.add_argument("--seed", type=int, default=0)
    return p.parse_args()


def _load_all_pairs(conn) -> tuple[list[dict], int]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT kb.pair_id, kb.trigger_text, kb.response_text, kb.scenario_key,
                   c.filename
            FROM kb_pairs kb JOIN calls c ON c.call_id = kb.call_id
            WHERE kb.scenario_key IS NOT NULL
            ORDER BY kb.pair_id
        """)
        rows = cur.fetchall()
        cur.execute("SELECT count(*) FROM calls")
        total_calls = int(cur.fetchone()[0])
    pairs = [
        {"pair_id": r[0], "trigger_text": r[1], "response_text": r[2],
         "scenario_key": r[3], "call_filename": r[4]}
        for r in rows
    ]
    return pairs, total_calls


def _cluster_corpus(pairs: list[dict], tuning, override: int | None):
    texts = [p["response_text"] for p in pairs]
    print(f"Embedding {len(texts)} response(s) via embed_document (warm cache expected)...")
    vecs = embedder.embed_document_matrix(texts)
    derived = cluster_evidence.milestone_min_cluster_size(
        len(pairs), tuning.min_cluster_size_fraction,
        tuning.min_cluster_size_floor, tuning.min_cluster_size_ceiling,
    )
    mcs = override if override is not None else derived
    print(f"min_cluster_size: {mcs}")
    print(f"Clustering (UMAP n_components<={tuning.umap_n_components}, cosine -> HDBSCAN)...")
    labels = _cluster_milestones(vecs, mcs, tuning.umap_n_components)
    return vecs, labels, mcs


def _scenario_sides(scenario_map: dict):
    coachable = {k: v for k, v in scenario_map.items() if v.get("is_coachable", True)}
    sinks = {k: v for k, v in scenario_map.items() if not v.get("is_coachable", True)}

    def _norm(d):
        keys, vecs = build_scenario_vecs(d)
        arr = np.asarray(vecs, dtype=np.float32)
        return keys, arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-10)

    ck, cv = _norm(coachable)
    sk, sv = _norm(sinks)
    return ck, cv, sk, sv


def _build_records(pairs, vecs, labels, scenario_map, total_calls, purity_gate, seed) -> list[dict]:
    ck, cv, sk, sv = _scenario_sides(scenario_map)
    is_coachable = {k: True for k in ck} | {k: False for k in sk}
    rng = random.Random(seed)
    records = []

    for label in sorted({int(l) for l in labels} - {-1}):
        idx = [i for i, l in enumerate(labels) if int(l) == label]
        members = [pairs[i] for i in idx]
        composition = Counter(m["scenario_key"] for m in members)

        skip, dominant_key = cluster_evidence.purity_gate_verdict(
            dict(composition), is_coachable, purity_gate,
        )

        centroid = cluster_evidence.milestone_cluster_centroid(vecs[idx])
        centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
        c_sims, s_sims = cv @ centroid, sv @ centroid
        c_best = int(np.argmax(c_sims))
        s_best = int(np.argmax(s_sims)) if sk else None

        samples = rng.sample(members, min(_SAMPLES_PER_CLUSTER, len(members)))
        records.append({
            "id": f"cluster_{label}",
            "size": len(members),
            "distinct_calls": len({m["call_filename"] for m in members}),
            "call_coverage": len({m["call_filename"] for m in members}) / max(total_calls, 1),
            "current_composition_top5": composition.most_common(5),
            "purity_gated": skip,
            "dominant_key": dominant_key,
            "nearest_coachable": ck[c_best],
            "nearest_coachable_sim": float(c_sims[c_best]),
            "nearest_coachable_description":
                scenario_map[ck[c_best]].get("business_description", ""),
            "nearest_sink": sk[s_best] if sk and s_best is not None else None,
            "nearest_sink_sim": float(s_sims[s_best]) if sk and s_best is not None else None,
            "member_pair_ids": [m["pair_id"] for m in members],
            "samples": [
                {"pair_id": s["pair_id"], "trigger_text": s["trigger_text"],
                 "response_text": s["response_text"], "scenario_key": s["scenario_key"]}
                for s in samples
            ],
        })
    return records


def _render_cluster(r: dict) -> str:
    samples = "\n".join(
        f"    - CLIENT: {s['trigger_text'][:120]!r}\n"
        f"      EXPERT: {s['response_text'][:_SAMPLE_CHARS]!r}"
        for s in r["samples"]
    )
    composition = ", ".join(f"{k} x{n}" for k, n in r["current_composition_top5"])
    return (
        f"- id: {r['id']}\n"
        f"  EVIDENCE: {r['size']} pair(s) in this cluster, spanning "
        f"{r['distinct_calls']} distinct call(s) ({r['call_coverage']:.0%} of the corpus)\n"
        f"  NEAREST EXISTING COACHABLE TOPIC: {r['nearest_coachable']} "
        f"(cosine {r['nearest_coachable_sim']:.3f})\n"
        f"    its description: {r['nearest_coachable_description']}\n"
        f"  NEAREST SINK TOPIC: {r['nearest_sink']} (cosine {r['nearest_sink_sim']:.3f})\n"
        f"  CURRENTLY FILED UNDER: {composition}\n"
        f"  SAMPLE PAIRS:\n{samples}"
    )


def _adjudicate(records: list[dict], config) -> dict[str, dict]:
    targets = [r for r in records if not r["purity_gated"]]
    skipped = len(records) - len(targets)
    print(f"  ({skipped} cluster(s) skipped by the purity gate -- one coachable scenario "
          f"already dominates.)")

    verdicts: dict[str, dict] = {}
    n_calls = math.ceil(len(targets) / _BATCH_SIZE)
    print(f"Adjudicating {len(targets)} cluster(s) in {n_calls} batched Gemma call(s)...")
    for i in range(0, len(targets), _BATCH_SIZE):
        chunk = targets[i:i + _BATCH_SIZE]
        items_block = "\n\n".join(_render_cluster(r) for r in chunk)
        try:
            raw = call_gemma(
                PROMPT_SINK_POOL_TRIAGE.format(items_block=items_block),
                config.gemma_api_keys,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ! batch {i // _BATCH_SIZE + 1} failed: {exc}")
            time.sleep(_GEMMA_CALL_DELAY)
            continue
        time.sleep(_GEMMA_CALL_DELAY)
        raw_list = raw if isinstance(raw, list) else raw.get("results", [])
        for r in raw_list:
            if isinstance(r, dict) and "id" in r:
                verdicts[r["id"]] = r
        print(f"  batch {i // _BATCH_SIZE + 1}/{n_calls}: {len(verdicts)} verdict(s) so far")
    return verdicts


def _report(payload: dict) -> None:
    records, verdicts = payload["clusters"], payload.get("verdicts", {})
    gated = sum(1 for r in records if r["purity_gated"])
    print("\n" + "=" * 78)
    print("CORPUS-WIDE RESPONSE TAXONOMY REPORT")
    print("=" * 78)
    print(f"  total pairs clustered            : {payload['n_pairs_total']}")
    print(f"  clusters found                    : {len(records)}")
    print(f"  purity-gated (skipped)            : {gated}")
    print(f"  sent to adjudication               : {len(records) - gated}")

    sims = [r["nearest_coachable_sim"] for r in records]
    print(f"\n  nearest_coachable_sim distribution (validates merge_cosine_threshold=0.85):")
    print("    " + "  ".join(f"p{p}={np.percentile(sims, p):.3f}" for p in (10, 25, 50, 75, 90)))

    if verdicts:
        tally = Counter(v.get("verdict", "?") for v in verdicts.values())
        print("\n  Three-way verdict tally:")
        for verdict, n in tally.most_common():
            print(f"    {verdict:<22} {n:>3} cluster(s)")
        new_topics = [rid for rid, v in verdicts.items() if v.get("verdict") == "new_coachable_topic"]
        print(f"\n  new_coachable_topic clusters (compare against the 2 already known -- "
              f"strategic_performance_consulting, technical_operational_alignment): "
              f"{len(new_topics)}")
        for rid in new_topics:
            print(f"    {rid}: {verdicts[rid].get('proposed_label')}")


def main() -> None:
    args = _parse_args()

    if args.load:
        payload = json.loads(args.load.read_text(encoding="utf-8-sig"))
        print(f"Re-reporting {args.load} (zero DB reads, zero Gemma calls).")
        _report(payload)
        return

    config = load_config()
    tuning = load_tuning()
    conn = storage.get_connection(config.database_url)
    scenario_map = {r["scenario_key"]: r for r in storage.get_scenarios(conn)}
    pairs, total_calls = _load_all_pairs(conn)
    conn.close()

    print(f"Loaded {len(scenario_map)} scenario(s), {len(pairs)} pair(s), {total_calls} call(s).")
    if not pairs:
        print("No pairs available -- nothing to measure.")
        sys.exit(1)

    vecs, labels, mcs = _cluster_corpus(pairs, tuning.layer_c, args.min_cluster_size)
    records = _build_records(
        pairs, vecs, labels, scenario_map, total_calls,
        tuning.layer_a.response_taxonomy_purity_gate, args.seed,
    )

    verdicts = {} if args.no_gemma else _adjudicate(records, config)
    payload = {
        "schema": "public",
        "n_pairs_total": len(pairs),
        "min_cluster_size": mcs,
        "purity_gate": tuning.layer_a.response_taxonomy_purity_gate,
        "seed": args.seed,
        "clusters": records,
        "verdicts": verdicts,
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nPersisted to {args.output} -- re-report for free with --load {args.output}")
    _report(payload)


if __name__ == "__main__":
    main()
