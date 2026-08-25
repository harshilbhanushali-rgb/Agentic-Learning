"""Wipe ONLY the redesigned Layer D's own tables and checkpoints.

    python ops/clear_layer_d_data.py

Deliberately NO __main__ guard, same as clear_data.py / clear_ego_trap_data.py:
importing this module wipes data, and with no ops/__init__.py there is no
`ops.clear_layer_d_data` to import by accident. Verify with py_compile, never
by importing.

Unlike the old clear_ego_trap_data.py this is NOT a prerequisite for a re-run:
move_events upserts on its natural key and move_performance is a full recompute,
so re-running converges instead of double-counting. Use this only for a deliberate
from-scratch wipe (e.g. after a taxonomy replacement already deleted the playbooks
these rows reference).

Touches: move_events, move_performance, and checkpoints WHERE layer LIKE 'layer_d_%'.
Does NOT touch csms (shared with ego_trap until that package retires), gap_events,
or anything upstream.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config  # noqa: E402
from shared import storage  # noqa: E402

_CHECKPOINT_DB = Path(__file__).resolve().parent.parent / "checkpoints.db"

config = load_config()
conn = storage.get_connection(config.database_url)
with conn.cursor() as cur:
    cur.execute("DELETE FROM move_performance")
    n_perf = cur.rowcount
    cur.execute("DELETE FROM move_events")
    n_events = cur.rowcount
conn.commit()
conn.close()
print(f"Deleted {n_events} move_events row(s), {n_perf} move_performance row(s).")

if _CHECKPOINT_DB.exists():
    with sqlite3.connect(_CHECKPOINT_DB) as ck:
        cur = ck.execute("DELETE FROM checkpoints WHERE layer LIKE 'layer_d_%'")
        print(f"Deleted {cur.rowcount} layer_d checkpoint row(s).")
else:
    print("No checkpoints.db found; nothing to clear there.")
