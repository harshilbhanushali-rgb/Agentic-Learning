"""
Backfill scenario_key / scenario_id on kb_pairs rows that are currently NULL.

Strategy: per-call assignment.
  1. For each call, collect all trigger texts.
  2. Embed them as queries and take their centroid.
  3. Compare centroid to scenario description embeddings.
  4. Assign the best-matching scenario to ALL null pairs from that call.

This is more robust than per-pair similarity (individual utterances are too
noisy to score reliably against abstract scenario descriptions).

Usage (from Brain/ with venv active):
    python backfill_scenarios.py
"""
from __future__ import annotations
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import psycopg
from shared import storage
from preprocessing import embedder


def main() -> None:
    conn = psycopg.connect(os.environ["DATABASE_URL"])

    # --- load scenarios ---
    scenarios = storage.get_scenarios(conn)
    if not scenarios:
        print("No scenarios in DB. Run Layer A first.")
        return

    scenario_keys  = [s["scenario_key"] for s in scenarios]
    scenario_descs = [
        s["business_description"] + " " + " ".join(s.get("keyphrases") or [])
        for s in scenarios
    ]
    print(f"Loaded {len(scenarios)} scenario(s): {scenario_keys}")

    # embed scenario descriptions once
    print("Embedding scenario descriptions...")
    s_vecs = np.array(embedder.embed_document(scenario_descs))
    s_vecs = s_vecs / (np.linalg.norm(s_vecs, axis=1, keepdims=True) + 1e-10)

    # --- load all calls ---
    with conn.cursor() as cur:
        cur.execute("SELECT call_id, filename FROM calls ORDER BY call_id")
        calls = cur.fetchall()

    total_updated = 0

    for call_id, filename in calls:
        # get ALL trigger texts for this call (assigned + unassigned)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pair_id, trigger_text, scenario_key FROM kb_pairs WHERE call_id = %s",
                (call_id,)
            )
            pairs = cur.fetchall()  # (pair_id, trigger_text, scenario_key)

        null_pairs  = [(pid, txt) for pid, txt, sk in pairs if sk is None]
        known_pairs = [(pid, txt, sk) for pid, txt, sk in pairs if sk is not None]

        if not null_pairs:
            print(f"[{filename}] All pairs already assigned -- skipping.")
            continue

        # pick call-level representative: centroid of ALL triggers
        all_triggers = [txt for _, txt in null_pairs] + [txt for _, txt, _ in known_pairs]
        print(f"[{filename}] Embedding {len(all_triggers)} trigger(s) to find call centroid...")
        t_vecs = np.array(embedder.embed_query(all_triggers))
        t_vecs = t_vecs / (np.linalg.norm(t_vecs, axis=1, keepdims=True) + 1e-10)
        centroid = t_vecs.mean(axis=0)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-10)

        # cosine similarity of centroid vs each scenario
        sims = s_vecs @ centroid
        best_j   = int(np.argmax(sims))
        best_key = scenario_keys[best_j]
        best_id  = scenarios[best_j]["scenario_id"]
        print(f"  Best scenario: {best_key}  (sim={sims[best_j]:.4f})")
        print(f"  Updating {len(null_pairs)} NULL pair(s)...")

        pair_ids = [pid for pid, _ in null_pairs]
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_pairs
                   SET scenario_key = %s, scenario_id = %s
                 WHERE pair_id = ANY(%s)
                """,
                (best_key, best_id, pair_ids)
            )
        conn.commit()
        total_updated += len(null_pairs)
        print(f"  Done.")

    print(f"\nBackfill complete. {total_updated} pair(s) updated.")
    conn.close()


if __name__ == "__main__":
    main()
