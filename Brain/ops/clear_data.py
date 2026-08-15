#!/usr/bin/env python3
"""Clears all pipeline data: Postgres tables + SQLite checkpoints.
Run from Brain/ with the venv active: python ops/clear_data.py

NOTE: this module has no `if __name__ == "__main__"` guard -- importing it WIPES the
database. Never import it to test or inspect it; run it deliberately or not at all.
"""
import sqlite3
import sys
from pathlib import Path
from dotenv import load_dotenv

# Brain/ is this file's grandparent -- on sys.path so `config` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

import psycopg
from config import load_config

config = load_config()

pg = psycopg.connect(config.database_url)
pg.execute("DELETE FROM rubrics")
pg.execute("DELETE FROM kb_pairs")
pg.execute("DELETE FROM scenarios")
pg.execute("DELETE FROM primary_topics")
pg.execute("DELETE FROM calls")
pg.commit()
pg.close()
print("Postgres cleared: rubrics, kb_pairs, scenarios, primary_topics, calls")

db_path = Path(__file__).resolve().parent.parent / "checkpoints.db"
if db_path.exists():
    c = sqlite3.connect(db_path)
    c.execute("DELETE FROM checkpoints")
    c.commit()
    c.close()
    print("Checkpoints cleared")
else:
    print("No checkpoints.db found — skipping")
