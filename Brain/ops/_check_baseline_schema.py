#!/usr/bin/env python3
"""Exit 0 if the named Postgres schema exists, 1 if it does not.

    python ops/_check_baseline_schema.py arm3_run1_20260810

A separate file rather than an inline `python -c` inside the .ps1 that calls it:
PowerShell mangles the quoting of any -c snippet containing SQL string literals, which is
already a documented gotcha in CLAUDE.md and which broke this exact guard on first attempt.
Underscore-prefixed because it is a helper for the .ps1 recipes, not something to run by hand.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config
from shared import storage

if len(sys.argv) != 2:
    print("usage: _check_baseline_schema.py <schema_name>")
    sys.exit(2)

schema = sys.argv[1]
conn = storage.get_connection(load_config().database_url)
try:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (schema,)
        )
        found = cur.fetchone() is not None
finally:
    conn.close()

print(f"{schema}: {'present' if found else 'MISSING'}")
sys.exit(0 if found else 1)
