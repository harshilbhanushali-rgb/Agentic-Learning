#!/usr/bin/env python3
"""Batch-runs the Ego Trap gap-analysis pipeline over Brain/csm_recordings/.
Run from Brain/ with the venv active: python run_ego_trap.py
Non-interactive (unlike main.py) — see Ego_trap.md section 7, pre-launch profile building.
"""
from __future__ import annotations
import hashlib
import sys
from pathlib import Path
from config import load_config
from shared import checkpoint, pinecone_store, storage
import db.init_db as init_module


def main() -> None:
    print("\n=== Ego Trap Batch Runner ===")
    config = load_config()

    recordings_dir = Path(__file__).parent / "csm_recordings"
    mapping_path = recordings_dir / "mapping.csv"
    txts = sorted(recordings_dir.glob("*.txt"))
    if not txts:
        print(f"ERROR: No .txt transcript files found in {recordings_dir}")
        sys.exit(1)
    if not mapping_path.exists():
        print(f"ERROR: No mapping.csv found at {mapping_path}")
        sys.exit(1)

    stems = "|".join(t.stem for t in txts)
    run_id = hashlib.sha1(stems.encode()).hexdigest()[:12]

    print(f"\nFound {len(txts)} transcript(s) in csm_recordings/:")
    for t in txts:
        print(f"  - {t.name}")

    print("\nInitializing database...")
    init_module.init_db(config.database_url)

    print("Initializing Pinecone index...")
    pinecone_store.init_index(config.pinecone_api_key, config.pinecone_index_name)

    print("Initializing checkpoint store...")
    checkpoint.init(run_id)
    print(f"  Run ID: {run_id}")

    conn = storage.get_connection(config.database_url)
    try:
        from ego_trap.pipeline import run_ego_trap_batch
        run_ego_trap_batch(str(recordings_dir), str(mapping_path), config, conn, run_id)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
