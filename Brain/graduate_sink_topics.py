#!/usr/bin/env python3
"""Phase 1 of docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md.

Graduates already-verdicted "new_coachable_topic" clusters from sink_pool_clusters.json
(produced by diagnose_sink_pool.py) into real scenarios: inserts the scenario row, reroutes
its exact known sink_member_pair_ids, and runs Layer C for just the new scenario(s).

This is the FIRST script in this investigation that writes to production DB state -- every
prior script (diagnose_sink_pool.py, replay_layer_c_admitted.py, all eight rejected per-pair
signal rounds) was read-only. Take the schema snapshot in this plan's Task 1 before running
this for real.

No re-embedding, no re-clustering, no re-deriving cluster membership: every number and pair ID
used here was already computed and stored by diagnose_sink_pool.py.

Usage (from Brain/, venv active):
    python graduate_sink_topics.py --dry-run           # Gemma call + prints, zero DB writes
    python graduate_sink_topics.py                      # writes for real
    python graduate_sink_topics.py --clusters cluster_5  # graduate just one
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

from config import load_config
from shared import cluster_evidence, scenario_vectors, storage, topic_grouping
from shared.gemma import call_gemma
from shared.prompts import PROMPT_GRADUATE_SINK_TOPIC
from shared.tuning import load_tuning
from v2.layer_c import run_layer_c_v2

_CLUSTERS_FILE = Path("sink_pool_clusters.json")
_TARGET_CLUSTER_IDS = ["cluster_5", "cluster_8"]
_GEMMA_CALL_DELAY = 5


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--clusters", default=",".join(_TARGET_CLUSTER_IDS),
                   help="comma-separated cluster ids from sink_pool_clusters.json to graduate")
    p.add_argument("--clusters-file", type=Path, default=_CLUSTERS_FILE)
    p.add_argument("--dry-run", action="store_true",
                   help="run the Gemma call and print the would-be scenario row; no DB writes")
    return p.parse_args()


def _render_samples(samples: list[dict]) -> str:
    return "\n".join(
        f"  - CLIENT: {s['trigger_text'][:150]!r}\n"
        f"    EXPERT: {s['response_text'][:400]!r}"
        for s in samples
    )


def _generate_metadata(record: dict, verdict: dict, config) -> dict:
    prompt = PROMPT_GRADUATE_SINK_TOPIC.format(
        proposed_label=verdict["proposed_label"],
        proposed_description=verdict["proposed_description"],
        reason=verdict["reason"],
        samples_block=_render_samples(record["samples"]),
    )
    result = call_gemma(prompt, config.gemma_api_keys)
    time.sleep(_GEMMA_CALL_DELAY)
    return result


def _support_stats_for_pairs(conn, pair_ids: list[int]) -> tuple[int, int, float]:
    """Recompute support_calls/support_clauses/call_coverage from the EXACT pairs being
    graduated, not diagnose_sink_pool.py's stored distinct_calls/call_coverage fields.

    Those stored fields were computed over the cluster's full union of sink-pool members
    AND its volume-matched coachable-control sample (mix_ratio's own denominator) -- e.g.
    cluster_5 stores distinct_calls=115 over 209 total members (94 sink + 115 control), not
    over the 94 sink pairs actually being rerouted here. Reusing that number verbatim would
    overstate this scenario's real evidence with calls it doesn't actually have any pairs
    in. support_clauses is set to len(pair_ids) rather than a real clause count --
    diagnose_sink_pool.py clusters at RESPONSE granularity, not Layer C's clause granularity,
    so there is no clause count to report; this is the count of graduated responses.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM calls")
        total_calls = int(cur.fetchone()[0])
        cur.execute(
            "SELECT COUNT(DISTINCT call_id) FROM kb_pairs WHERE pair_id = ANY(%s)",
            (pair_ids,),
        )
        distinct_calls = int(cur.fetchone()[0])
    call_coverage = distinct_calls / max(total_calls, 1)
    return distinct_calls, len(pair_ids), call_coverage


def _resolve_primary_topic_key(conn, row: dict) -> str:
    """Fixes the primary_topic_key=None orphaning bug: primary_topics is only ever
    populated once, during Layer A's main grouping pass -- a scenario graduated afterward
    (by this script, or by response_taxonomy_auto_pass.py) has no later grouping step to go
    through, so this resolves a real key instead of leaving the FK null forever. See
    docs/superpowers/specs/2026-08-07-response-taxonomy-auto-pass-design.md's "Fix:
    primary_topic_key orphaning" section -- response_taxonomy_auto_pass.py's own
    _resolve_primary_topic_key is the sibling of this function, both built together.

    Reuses merge_cosine_threshold (the tight, subtopic-dedup threshold), not the looser
    primary_topic_merge_threshold used for INITIAL macro-grouping -- primary_topics rows are
    already tight-cohesion groups by the time they're stored (post tighten_coachable_groups),
    so the tight threshold is the comparable one.
    """
    tuning_a = load_tuning().layer_a
    existing = storage.get_primary_topics(conn)
    by_key = {t["primary_topic_key"]: t for t in existing}
    keys, vecs = scenario_vectors.build_primary_topic_vecs(by_key)
    new_vec = scenario_vectors.scenario_vec(row)

    match = topic_grouping.match_existing_primary_topic(new_vec, keys, vecs, tuning_a.merge_cosine_threshold)
    if match is not None:
        return match

    storage.upsert_primary_topic(conn, {
        "primary_topic_key": row["scenario_key"],
        "label": row["scenario_key"].replace("_", " ").title(),
        "description": row["business_description"],
        "keyphrases": row["keyphrases"],
        "grouping_method": "graduated_singleton",
        "support_calls": row["support_calls"],
        "support_subtopics": 1,
        "call_coverage": row["call_coverage"],
    })
    return row["scenario_key"]


def _graduate_one(cluster_id: str, record: dict, verdict: dict, config, conn,
                   dry_run: bool) -> str | None:
    tuning = load_tuning().layer_a
    if verdict.get("verdict") != "new_coachable_topic":
        print(f"[{cluster_id}] verdict is {verdict.get('verdict')!r}, not "
              f"'new_coachable_topic' -- skipping.")
        return None

    if not cluster_evidence.passes_reconciliation_gate(
        record["nearest_coachable_sim"], tuning.merge_cosine_threshold
    ):
        print(f"[{cluster_id}] FAILS reconciliation gate: nearest_coachable_sim="
              f"{record['nearest_coachable_sim']:.3f} >= merge_cosine_threshold="
              f"{tuning.merge_cosine_threshold:.3f} -- SKIPPING. Do not force-route into "
              f"{record['nearest_coachable']!r}; that is the by_cluster failure mode this "
              f"design explicitly rejects.")
        return None

    print(f"[{cluster_id}] reconciliation gate OK ({record['nearest_coachable_sim']:.3f} < "
          f"{tuning.merge_cosine_threshold:.3f}). Generating scenario metadata via Gemma...")
    meta = _generate_metadata(record, verdict, config)
    print(f"  -> scenario_key={meta['scenario_key']!r}")
    print(f"  -> business_description={meta['business_description']!r}")

    pair_ids = record["sink_member_pair_ids"]
    if dry_run:
        distinct_calls, n_pairs, call_coverage = _support_stats_for_pairs(conn, pair_ids)
        print(f"  [DRY RUN] would insert scenario, reroute {n_pairs} pair(s) spanning "
              f"{distinct_calls} distinct call(s) ({call_coverage:.1%} coverage). No writes made.")
        return None

    distinct_calls, n_pairs, call_coverage = _support_stats_for_pairs(conn, pair_ids)
    row = {
        "scenario_key": meta["scenario_key"],
        "business_description": meta["business_description"],
        "primary_topic": verdict["proposed_label"],
        "keyphrases": meta.get("keyphrases") or [],
        "soft_skills": meta.get("soft_skills") or [],
        "bloom_level": meta.get("bloom_level") or "understand",
        "is_coachable": True,
        "cluster_kind": "scenario",
        "support_calls": distinct_calls,
        "support_clauses": n_pairs,
        "call_coverage": call_coverage,
        "triage_verdict": "graduated_from_sink_pool",
        "adjudication_reason": verdict["reason"],
    }
    row["primary_topic_key"] = _resolve_primary_topic_key(conn, row)
    scenario_id = storage.upsert_scenario(conn, row)
    print(f"  -> scenario_id={scenario_id}")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE kb_pairs
               SET scenario_key = %s, scenario_id = %s,
                   scenario_keys = array_append(scenario_keys, %s)
             WHERE pair_id = ANY(%s)
            """,
            (row["scenario_key"], scenario_id, row["scenario_key"], pair_ids),
        )
        rerouted = cur.rowcount
    conn.commit()
    print(f"  -> rerouted {rerouted} pair(s) (expected {len(pair_ids)})")
    if rerouted != len(pair_ids):
        raise RuntimeError(
            f"[{cluster_id}] rerouted {rerouted} pair(s), expected exactly {len(pair_ids)} -- "
            f"aborting before Layer C runs on a possibly-wrong pair set."
        )
    return row["scenario_key"]


def main() -> None:
    args = _parse_args()
    target_ids = [c.strip() for c in args.clusters.split(",") if c.strip()]

    config = load_config()
    payload = json.loads(args.clusters_file.read_text(encoding="utf-8-sig"))
    clusters_by_id = {r["id"]: r for r in payload["clusters"]}
    verdicts = payload.get("verdicts", {})

    conn = storage.get_connection(config.database_url)
    before_count = len(storage.get_scenarios(conn))

    graduated_keys: list[str] = []
    for cluster_id in target_ids:
        record = clusters_by_id.get(cluster_id)
        verdict = verdicts.get(cluster_id)
        if record is None or verdict is None:
            print(f"[{cluster_id}] not found in {args.clusters_file} -- skipping.")
            continue
        key = _graduate_one(cluster_id, record, verdict, config, conn, args.dry_run)
        if key:
            graduated_keys.append(key)

    if args.dry_run:
        print("\n[DRY RUN] complete -- no scenarios inserted, no pairs rerouted, Layer C not run.")
        conn.close()
        return

    if not graduated_keys:
        print("\nNothing graduated -- nothing to run Layer C for.")
        conn.close()
        return

    after_count = len(storage.get_scenarios(conn))
    print(f"\nScenario count: {before_count} -> {after_count} "
          f"(+{after_count - before_count}, expected +{len(graduated_keys)})")
    if after_count - before_count != len(graduated_keys):
        raise RuntimeError(
            f"scenario count increased by {after_count - before_count}, expected exactly "
            f"{len(graduated_keys)} -- investigate before trusting anything downstream."
        )

    print(f"\nRunning Layer C (V2) for: {graduated_keys}")
    all_scenarios = {s["scenario_key"]: s for s in storage.get_scenarios(conn)}
    targeted = {k: all_scenarios[k] for k in graduated_keys}
    run_layer_c_v2(targeted, config, conn, run_id="")

    print("\n=== Generated rubrics (READ THESE BEFORE CALLING THIS DONE) ===")
    for key in graduated_keys:
        rubric = storage.get_rubric_for_scenario(conn, key)
        print(f"\n--- {key} ---")
        print(json.dumps(rubric, indent=2, default=str) if rubric else "  NO RUBRIC GENERATED")

    conn.close()


if __name__ == "__main__":
    main()
