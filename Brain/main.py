#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import sys
from pathlib import Path
from config import load_config
from shared import storage, checkpoint
from shared import pinecone_store
import db.init_db as init_module


def main() -> None:
    print("\n=== Naren's Brain Builder ===")
    config = load_config()

    recordings_dir = Path(__file__).parent / "recordings"
    txts = sorted(recordings_dir.glob("*.txt"))
    if not txts:
        print(f"ERROR: No .txt transcript files found in {recordings_dir}")
        sys.exit(1)

    stems = "|".join(t.stem for t in txts)
    run_id = hashlib.sha1(stems.encode()).hexdigest()[:12]

    print(f"\nFound {len(txts)} transcript(s) in recordings/:")
    for t in txts:
        print(f"  - {t.name}")

    print("\nChoose pipeline version:")
    print("  [1] V1 -- Gemma-direct  (recommended for <=5 calls)")
    print("  [2] V2 -- Statistical clustering  (requires 30+ calls for Layer A)")
    choice = input("\nEnter 1 or 2: ").strip()

    print("\nInitializing database...")
    init_module.init_db(config.database_url)

    print("Initializing Pinecone index...")
    pinecone_store.init_index(config.pinecone_api_key, config.pinecone_index_name)

    print("Initializing checkpoint store...")
    checkpoint.init(run_id)
    print(f"  Run ID: {run_id}")

    conn = storage.get_connection(config.database_url)
    try:
        if choice == "1":
            from v1.pipeline import run_v1
            run_v1(str(recordings_dir), config, conn, run_id)
        elif choice == "2":
            from v2.pipeline import run_v2
            run_v2(str(recordings_dir), config, conn, run_id)
        else:
            print(f"Invalid choice '{choice}'. Enter 1 or 2.")
            sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
