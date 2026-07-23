from __future__ import annotations
import sqlite3
from pathlib import Path

_DB = Path(__file__).parent.parent / "checkpoints.db"

def init(run_id: str) -> None:
    with sqlite3.connect(_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                run_id TEXT NOT NULL,
                item   TEXT NOT NULL,
                layer  TEXT NOT NULL,
                PRIMARY KEY (run_id, item, layer)
            )
        """)
        conn.commit()

def is_done(run_id: str, item: str, layer: str) -> bool:
    with sqlite3.connect(_DB) as conn:
        row = conn.execute(
            "SELECT 1 FROM checkpoints WHERE run_id=? AND item=? AND layer=?",
            (run_id, item, layer)
        ).fetchone()
    return row is not None

def mark_done(run_id: str, item: str, layer: str) -> None:
    with sqlite3.connect(_DB) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO checkpoints (run_id, item, layer) VALUES (?,?,?)",
            (run_id, item, layer)
        )
        conn.commit()

def list_done(run_id: str) -> list[tuple]:
    with sqlite3.connect(_DB) as conn:
        rows = conn.execute(
            "SELECT item, layer FROM checkpoints WHERE run_id=?", (run_id,)
        ).fetchall()
    return rows
