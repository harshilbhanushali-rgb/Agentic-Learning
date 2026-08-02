#!/usr/bin/env python3
"""Non-interactive V2 pipeline runner against an arbitrary recordings directory.

main.py hardcodes recordings/ and prompts interactively for V1/V2 -- this
mirrors its V2 path exactly (init_db, Pinecone index, checkpoint store) but
takes the directory as an argument, for the 50-60 call calibration subset
described in docs/superpowers/specs/2026-07-30-layer-b-two-stage-matching-design.md.

Usage (from Brain/, venv active):
    python run_v2_subset.py recordings_subset60
"""
from __future__ import annotations
import hashlib
import sys
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

from config import load_config
from shared import storage, checkpoint
from shared import pinecone_store
import db.init_db as init_module


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python run_v2_subset.py <recordings_dir>")
        sys.exit(1)

    recordings_dir = Path(sys.argv[1])
    txts = sorted(recordings_dir.glob("*.txt"))
    if not txts:
        print(f"ERROR: No .txt transcript files found in {recordings_dir}")
        sys.exit(1)

    stems = "|".join(t.stem for t in txts)
    run_id = hashlib.sha1(stems.encode()).hexdigest()[:12]

    print(f"\n=== V2 subset run: {len(txts)} transcript(s) from {recordings_dir} ===")
    print(f"  Run ID: {run_id}")

    config = load_config()

    print("\nInitializing database...")
    init_module.init_db(config.database_url)

    print("Initializing Pinecone index...")
    pinecone_store.init_index(config.pinecone_api_key, config.pinecone_index_name)

    print("Initializing checkpoint store...")
    checkpoint.init(run_id)

    conn = storage.get_connection(config.database_url)
    try:
        from v2.pipeline import run_v2
        run_v2(str(recordings_dir), config, conn, run_id)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
