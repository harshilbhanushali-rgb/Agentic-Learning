#!/usr/bin/env python3
"""Does the vector index hold a trigger vector for EVERY coachable kb_pair? (ADR 0008)

Run from Brain/ after shipping a layer:

    python ops/check_vector_coverage.py

Ask Naren's retrieval now depends on `narens-brain-3072` holding a trigger vector for every
pair in the coachable pool. The failure this catches is silent: a pipeline run that writes
kb_pairs to Postgres before upserting their vectors leaves those pairs in the pool and
absent from every ranking, so they can never be retrieved. Nothing errors and no log line
appears -- it would surface as an unexplained quality complaint months later.

ops/serve_ask_naren.py samples 1,000 identifiers at startup. This is the exhaustive version:
it checks all ~6,496, in batches, transferring no vectors.

READ-ONLY on both stores. Postgres is read through a connection Postgres refuses to write
through and closed before the check runs; Pinecone is only fetched from. Needs the VPN only
if the DNS workaround does not apply -- no embedding and no generation happens here.

Exit code 0 when coverage is complete, 1 when it is not, so this is usable as a gate.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ask_naren import retrieval, vector_store            # noqa: E402
from config import load_config                           # noqa: E402
from ops.serve_ask_naren import (DEFAULT_HOSTADDR,       # noqa: E402
                                 VECTOR_INDEX_NAME, _connect_read_only)


def main() -> int:
    config = load_config()
    conn = _connect_read_only(config.database_url, DEFAULT_HOSTADDR)
    try:
        pairs = retrieval.load_coachable_pairs(conn)
    finally:
        conn.close()
    if not pairs:
        print("ERROR: no coachable kb_pairs found -- nothing to check.")
        return 1

    scenario_keys = sorted({p["scenario_key"] for p in pairs})
    print(f"[pool] {len(pairs)} coachable kb_pairs after content dedup, "
          f"{len(scenario_keys)} scenarios")

    store = vector_store.PineconeTriggerStore(
        config.pinecone_api_key, VECTOR_INDEX_NAME, scenario_keys)
    print(f"[vectors] checking every pair against {VECTOR_INDEX_NAME}...", flush=True)
    t0 = time.time()
    missing = store.covers([p["pair_id"] for p in pairs])
    elapsed = time.time() - t0

    present = len(pairs) - len(missing)
    print(f"[vectors] {present}/{len(pairs)} present  ({elapsed:.1f}s)")
    if not missing:
        print("PASS: every coachable kb_pair has a trigger vector.")
        return 0

    by_scenario: dict[str, int] = {}
    holder = {str(p["pair_id"]): p["scenario_key"] for p in pairs}
    for pair_id in missing:
        key = holder.get(pair_id, "?")
        by_scenario[key] = by_scenario.get(key, 0) + 1
    print(f"FAIL: {len(missing)} coachable kb_pairs have NO trigger vector and can never "
          f"be retrieved.")
    for key, count in sorted(by_scenario.items(), key=lambda kv: -kv[1]):
        print(f"  {count:5d}  {key}")
    print(f"  example pair_ids: {missing[:10]}")
    print("Fix: ops/ship_layer_b.py --vectors triggers, then re-run this.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
