"""
Re-run Layer C for scenarios that are missing or broken rubrics.
Targets: school_district_onboarding, high_volume_senior_living_strategy

Run AFTER backfill_scenarios.py so those scenarios have pairs assigned.

Usage (from Brain/ with venv active):
    python rerun_layer_c.py
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import psycopg
from config import load_config
from shared import storage
from v1 import layer_c

TARGET_SCENARIOS = {
    "school_district_onboarding",
    "high_volume_senior_living_strategy",
}


def main() -> None:
    config = load_config()
    conn = psycopg.connect(os.environ["DATABASE_URL"])

    all_scenarios = storage.get_scenarios(conn)
    scenario_map = {s["scenario_key"]: s for s in all_scenarios}

    targeted = {k: v for k, v in scenario_map.items() if k in TARGET_SCENARIOS}
    if not targeted:
        print("Target scenarios not found in DB.")
        return

    for key in targeted:
        pairs = storage.get_naren_responses_for_scenario(conn, key)
        print(f"[{key}] {len(pairs)} Naren response(s) available.")

    # run without run_id so checkpoints don't block re-execution;
    # upsert_rubric will overwrite any existing rubric row
    layer_c.run_layer_c(targeted, config, conn, run_id="")

    print("\nLayer C rerun complete.")
    conn.close()


if __name__ == "__main__":
    main()
