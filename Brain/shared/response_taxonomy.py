"""Shared response-clustering machinery: cluster every kb_pairs response by embedding
similarity, judge each cluster's current scenario_key composition, and adjudicate survivors
via the three-way PROMPT_SINK_POOL_TRIAGE verdict.

Extracted from dry_run_response_taxonomy.py (2026-08-07) so the dry-run script and the
permanent response_taxonomy_auto_pass.py module share one implementation instead of
duplicating it -- same precedent as v2/layer_c.py::build_clause_pool's extraction during the
sink-pool diagnostic work.
"""
from __future__ import annotations
import math
import time
from collections import Counter

import numpy as np

from preprocessing import embedder
from shared import cluster_evidence
from shared.gemma import call_gemma
from shared.prompts import PROMPT_SINK_POOL_TRIAGE
from shared.scenario_vectors import build_scenario_vecs
from v2.layer_c import _cluster_milestones

_BATCH_SIZE = 5
_GEMMA_CALL_DELAY = 5
_SAMPLES_PER_CLUSTER = 4
_SAMPLE_CHARS = 300


def load_all_pairs(conn) -> tuple[list[dict], int]:
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


def cluster_corpus(pairs: list[dict], tuning, override: int | None):
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


def scenario_sides(scenario_map: dict):
    coachable = {k: v for k, v in scenario_map.items() if v.get("is_coachable", True)}
    sinks = {k: v for k, v in scenario_map.items() if not v.get("is_coachable", True)}

    def _norm(d):
        keys, vecs = build_scenario_vecs(d)
        if not keys:
            return keys, np.empty((0, 0), dtype=np.float32)
        arr = np.asarray(vecs, dtype=np.float32)
        return keys, arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-10)

    ck, cv = _norm(coachable)
    sk, sv = _norm(sinks)
    return ck, cv, sk, sv


def build_records(pairs, vecs, labels, scenario_map, total_calls, purity_gate, seed) -> list[dict]:
    import random

    ck, cv, sk, sv = scenario_sides(scenario_map)
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
        c_sims = cv @ centroid if len(cv) else np.array([])
        s_sims = sv @ centroid if len(sv) else np.array([])
        c_best = int(np.argmax(c_sims)) if len(c_sims) else None
        s_best = int(np.argmax(s_sims)) if len(s_sims) else None

        samples = rng.sample(members, min(_SAMPLES_PER_CLUSTER, len(members)))
        records.append({
            "id": f"cluster_{label}",
            "size": len(members),
            "distinct_calls": len({m["call_filename"] for m in members}),
            "call_coverage": len({m["call_filename"] for m in members}) / max(total_calls, 1),
            "current_composition_top5": composition.most_common(5),
            "purity_gated": skip,
            "dominant_key": dominant_key,
            "nearest_coachable": ck[c_best] if c_best is not None else None,
            "nearest_coachable_sim": float(c_sims[c_best]) if c_best is not None else None,
            "nearest_coachable_description":
                scenario_map[ck[c_best]].get("business_description", "") if c_best is not None else "",
            "nearest_sink": sk[s_best] if s_best is not None else None,
            "nearest_sink_sim": float(s_sims[s_best]) if s_best is not None else None,
            "member_pair_ids": [m["pair_id"] for m in members],
            "samples": [
                {"pair_id": s["pair_id"], "trigger_text": s["trigger_text"],
                 "response_text": s["response_text"], "scenario_key": s["scenario_key"]}
                for s in samples
            ],
        })
    return records


def render_cluster(r: dict) -> str:
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


def adjudicate_clusters(records: list[dict], config) -> dict[str, dict]:
    targets = [r for r in records if not r["purity_gated"]]
    skipped = len(records) - len(targets)
    print(f"  ({skipped} cluster(s) skipped by the purity gate -- one coachable scenario "
          f"already dominates.)")

    verdicts: dict[str, dict] = {}
    n_calls = math.ceil(len(targets) / _BATCH_SIZE)
    print(f"Adjudicating {len(targets)} cluster(s) in {n_calls} batched Gemma call(s)...")
    for i in range(0, len(targets), _BATCH_SIZE):
        chunk = targets[i:i + _BATCH_SIZE]
        items_block = "\n\n".join(render_cluster(r) for r in chunk)
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
