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
    python calibration/dry_run_response_taxonomy.py
    python calibration/dry_run_response_taxonomy.py --no-gemma
    python calibration/dry_run_response_taxonomy.py --load dry_run_response_taxonomy.json
"""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np

# Brain/ is this file's parent -- put it on sys.path so the shared packages
# (config, shared, v1, v2, preprocessing) resolve whether this script is run
# directly (python calibration/x.py) or imported (from calibration import x).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

from config import load_config
from shared import storage
from shared.response_taxonomy import (
    adjudicate_clusters, build_records, cluster_corpus, load_all_pairs,
)
from shared.tuning import load_tuning

_DEFAULT_OUTPUT = ARTIFACTS_DIR / "dry_run_response_taxonomy.json"


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--load", type=Path, default=None)
    p.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    p.add_argument("--no-gemma", action="store_true")
    p.add_argument("--min-cluster-size", type=int, default=None)
    p.add_argument("--seed", type=int, default=0)
    return p.parse_args()


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
    pairs, total_calls = load_all_pairs(conn)
    conn.close()

    print(f"Loaded {len(scenario_map)} scenario(s), {len(pairs)} pair(s), {total_calls} call(s).")
    if not pairs:
        print("No pairs available -- nothing to measure.")
        sys.exit(1)

    vecs, labels, mcs = cluster_corpus(pairs, tuning.layer_c, args.min_cluster_size)
    records = build_records(
        pairs, vecs, labels, scenario_map, total_calls,
        tuning.layer_a.response_taxonomy_purity_gate, args.seed,
    )

    verdicts = {} if args.no_gemma else adjudicate_clusters(records, config)
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
