#!/usr/bin/env python3
"""Clears Ego Trap Layer D data: Postgres tables + its SQLite checkpoints.
Does NOT touch Naren's brain data (scenarios/rubrics/kb_pairs/calls) — Ego Trap
reads those, it doesn't own them. Run from Brain/ with the venv active:
python clear_ego_trap_data.py
"""
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import psycopg
from config import load_config

config = load_config()

pg = psycopg.connect(config.database_url)
pg.execute("DELETE FROM gap_events")
pg.execute("DELETE FROM milestone_performance")
pg.execute("DELETE FROM signal_recognition_gaps")
pg.execute("DELETE FROM csms")
pg.commit()
pg.close()
print("Postgres cleared: gap_events, milestone_performance, signal_recognition_gaps, csms")

db_path = Path(__file__).parent / "checkpoints.db"
if db_path.exists():
    c = sqlite3.connect(db_path)
    c.execute("DELETE FROM checkpoints WHERE layer LIKE 'ego_trap%'")
    c.commit()
    c.close()
    print("Ego Trap checkpoints cleared (layer_a/b/c checkpoints untouched)")
else:
    print("No checkpoints.db found — skipping")
