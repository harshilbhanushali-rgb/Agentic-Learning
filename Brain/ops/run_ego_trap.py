#!/usr/bin/env python3
"""Batch-runs the Ego Trap gap-analysis pipeline over Brain/csm_recordings/.

Run from Brain/ with the venv active:
    python ops/run_ego_trap.py               # every mapped transcript
    python ops/run_ego_trap.py --limit 20    # the 20 most recent, for calibration

Non-interactive (unlike main.py) — see Ego_trap.md section 7, pre-launch profile building.
Step 0 mode comes from tuning.yaml's layer_d.signal_detection_mode ('gemma' costs one
Gemma call per transcript; 'similarity' is local and free). Step 3 scoring always uses
Gemma either way.
"""
from __future__ import annotations
import argparse
import hashlib
import os
import sys
from pathlib import Path

# Brain/ is this file's grandparent -- on sys.path so config/shared/db resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config
from shared import checkpoint, pinecone_store, storage
import db.init_db as init_module

# Layer D knobs that used to be read from .env by the now-deleted
# ego_trap/settings.py, mapped to where they live today.
_RETIRED_ENV = {
    "STEP_0_MODE": "tuning.yaml -> layer_d.signal_detection_mode",
    "ENABLE_GAP_EVENTS": "tuning.yaml -> layer_d.gap_events_enabled",
    "EGO_TRAP_SIMILARITY_THRESHOLD": "tuning.yaml -> layer_d.similarity_relative_margin",
    "EGO_TRAP_GEMMA_BATCH_SIZE": "ego_trap/pipeline.py -> _GEMMA_BATCH_SIZE",
}


def _reject_retired_env() -> None:
    """Refuse to run while a retired Layer D var is still set in .env.

    Brain/.env is gitignored, so this repo cannot clean up the user's file. A stale
    line there would sit looking authoritative while doing nothing -- exactly the
    silent-revert failure shared/tuning.py's raise-on-unknown-key rule exists to
    prevent, and the failure that already produced a live 0.75-vs-0.35 divergence. So
    the only safe option is to stop and say so.

    Must be called from main(), not at import: `from config import load_config` above
    runs config.py's load_dotenv() on import, which is what puts .env into os.environ
    in the first place.
    """
    stale = [k for k in _RETIRED_ENV if os.environ.get(k) is not None]
    if not stale:
        return
    print("\nERROR: these Ego Trap settings moved out of .env and no longer do anything:")
    for key in stale:
        print(f"  {key}  ->  now set via {_RETIRED_ENV[key]}")
    print("\nRemove them from Brain/.env, then re-run.")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-run Ego Trap gap analysis.")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="score only the last N transcripts in filename order. For a calibration "
             "subset -- the subset gets its own run_id, so its checkpoints never collide "
             "with a full run's. NOTE: this is filename order, not strictly chronological "
             "-- Avoma-fetched files are date-prefixed (20260807_...) but legacy ones are "
             "not (rec3.txt), and letters sort after digits, so legacy files land at the "
             "end and are always included.",
    )
    parser.add_argument(
        "--exclude", default="",
        help="comma-separated stems to skip. Use for transcripts whose SPEAKER ROLES "
             "cannot be trusted -- role classification fails OPEN, so an unidentified "
             "speaker is scored as the client and their turns become coaching findings "
             "about a CSM. Excluding is cheaper than discovering that afterwards. Applied "
             "BEFORE run_id is derived, so an excluded run gets its own checkpoints.",
    )
    args = parser.parse_args()

    print("\n=== Ego Trap Batch Runner ===")
    _reject_retired_env()
    config = load_config()

    recordings_dir = Path(__file__).resolve().parent.parent / "csm_recordings"
    mapping_path = recordings_dir / "mapping.csv"
    txts = sorted(recordings_dir.glob("*.txt"))
    if not txts:
        print(f"ERROR: No .txt transcript files found in {recordings_dir}")
        sys.exit(1)
    if not mapping_path.exists():
        print(f"ERROR: No mapping.csv found at {mapping_path}")
        sys.exit(1)

    # Select FIRST, then derive run_id from the selection. run_id is a sha1 of the stem
    # list, so it must describe exactly what is about to be scored -- deriving it from
    # the full directory while running a subset would give the subset a run_id claiming
    # 106 transcripts, and its checkpoints would then be read by a later full run as if
    # that work were already done.
    excluded = {s.strip() for s in args.exclude.split(",") if s.strip()}
    if excluded:
        present = {t.stem for t in txts}
        missing = excluded - present
        if missing:
            # A typo'd stem would silently exclude nothing, and the run would quietly
            # include the transcripts it was meant to leave out.
            print(f"ERROR: --exclude names {len(missing)} stem(s) not in "
                  f"csm_recordings/: {sorted(missing)}")
            sys.exit(1)
        txts = [t for t in txts if t.stem not in excluded]
        print(f"\nEXCLUDED {len(excluded)} transcript(s) by request:")
        for stem in sorted(excluded):
            print(f"  - {stem}")

    selected = txts[-args.limit:] if args.limit else txts
    only_stems = {t.stem for t in selected} if (args.limit or excluded) else None
    run_id = hashlib.sha1("|".join(t.stem for t in selected).encode()).hexdigest()[:12]

    if args.limit:
        print(f"\nSUBSET: scoring the {len(selected)} most recent of "
              f"{len(txts)} transcript(s) in csm_recordings/:")
    else:
        print(f"\nFound {len(txts)} transcript(s) in csm_recordings/:")
    for t in selected:
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
        # Rebind: reconnect_if_closed returns a NEW connection object, so the handle
        # created above is dead after the first swap inside the batch. Closing the
        # returned one is what stops a live Neon connection leaking per swap.
        conn = run_ego_trap_batch(
            str(recordings_dir), str(mapping_path), config, conn, run_id,
            only_stems=only_stems,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
