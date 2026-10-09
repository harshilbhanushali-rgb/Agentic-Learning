#!/usr/bin/env python3
"""Apply the _v4 interjection guard to the stored _v3 Layer D events. ZERO spend.

Why this is exact and not a shortcut (docs/findings/layer-d-say-arm.md §11c): the _v4
rule (layer_d.signals.is_substantive_reply) is strictly stricter than _v3's. It never
turns an interjection into a graded reply; it only turns some graded replies into
interjections. A graded reply that becomes an interjection is stored with
response_outcome='interjection' and verdicts='[]' -- no grader is involved. So the
_v4 events are the _v3 events with those rows relabelled, and this script produces
exactly what a fresh _v4 run would, minus ~700 paid grading requests.

What it does, per affected (call_id, source_ref, playbook_id) moment, for BOTH arms
(pairwise run 137706da74c6 and say run 137706da74c6):
  1. UPDATE move_events SET response_outcome='interjection', verdicts='[]'
  2. copy the _v3 checkpoint rows to their _v4 layer strings (CSM layers for both
     arms; the say _naren layers, whose pass does not use the guard at all), so the
     next batch run resumes instead of re-grading;
  3. storage.refresh_move_performance.

Dry-run by default (prints every affected moment). --apply backs up, then relabels
inside ONE transaction, then copies checkpoints, then rebuilds. Re-runnable: a second
--apply finds nothing to relabel and refuses to overwrite the backup (audit 2026-09-06:
the backup is the only copy of the _v3 verdicts and must never be clobbered).

Usage (from Brain/, VPN up):
    python ops/reclassify_interjections_v4.py            # list
    python ops/reclassify_interjections_v4.py --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RUN_ID = "137706da74c6"
LAYER_COPIES = [
    # (run_id, v3 layer, v4 layer)
    (RUN_ID, "layer_d_e_pairwise_gemini-3.6-flash_medium_noswap_v3",
     "layer_d_e_pairwise_gemini-3.6-flash_medium_noswap_v4"),
    (RUN_ID, "layer_d_e_say_gemini-3.6-flash_medium_noswap_clsceace4b9_v3",
     "layer_d_e_say_gemini-3.6-flash_medium_noswap_clsceace4b9_v4"),
    (RUN_ID, "layer_d_e_say_gemini-3.6-flash_medium_noswap_clsceace4b9_v3_naren",
     "layer_d_e_say_gemini-3.6-flash_medium_noswap_clsceace4b9_v4_naren"),
    ("695837c37614", "layer_d_e_say_gemini-3.6-flash_medium_noswap_clsceace4b9_v3_naren",
     "layer_d_e_say_gemini-3.6-flash_medium_noswap_clsceace4b9_v4_naren"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--hostaddr", default="18.138.49.39")
    a = ap.parse_args()

    from config import load_config
    from layer_d import pipeline
    from layer_d.signals import is_substantive_reply
    from shared import checkpoint, storage
    from shared.tuning import get_tuning

    # The layer strings above must be what the code now derives -- fail loudly if not.
    t = get_tuning().layer_d
    from types import SimpleNamespace
    from layer_d import move_classes
    fp = move_classes.classes_fingerprint(move_classes.load_move_classes())
    derived = {
        pipeline.checkpoint_layer(SimpleNamespace(**{**vars(t), "grader_arm": "pairwise"})),
        pipeline.checkpoint_layer(SimpleNamespace(**{**vars(t), "grader_arm": "say"}), classes_fp=fp),
        pipeline.checkpoint_layer(SimpleNamespace(**{**vars(t), "grader_arm": "say"}), classes_fp=fp) + "_naren",
    }
    assert {v4 for _, _, v4 in LAYER_COPIES} == derived, (derived, LAYER_COPIES)

    url = load_config().database_url
    if a.hostaddr and "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + f"hostaddr={a.hostaddr}"
    conn = storage.get_connection(url)
    if storage.clear_read_only(conn):
        raise SystemExit("database is read-only and the reset did not clear it")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT call_id, source_ref, playbook_id, response_text
            FROM move_events
            WHERE rater_population='csm' AND run_id=%s AND response_outcome='csm'
            ORDER BY call_id, source_ref, playbook_id
        """, (RUN_ID,))
        moments = cur.fetchall()
    affected = [(c, s, p, txt) for c, s, p, txt in moments if not is_substantive_reply(txt)]
    print(f"graded CSM moments (distinct): {len(moments)}; reclassified under _v4: {len(affected)}")
    for c, s, p, txt in affected:
        print(f"  {c} {s} pb{p}: {txt[:100]!r}")

    keys = [(c, s, p) for c, s, p, _ in affected]
    if not a.apply:
        print("\n[dry run] pass --apply to relabel these rows in both arms, copy checkpoints, "
              "and rebuild move_performance")
        conn.close()
        return

    # Full-row backup of every row about to change, BEFORE the update: a fresh _v4
    # run would produce verdicts='[]' for these too, but the _v3 verdicts are
    # information and information is not deleted without a copy.
    backup = []
    with conn.cursor() as cur:
        for c, s, p in keys:
            cur.execute("""
                SELECT move_event_id, grader_arm, call_id, source_ref, playbook_id,
                       response_outcome, response_text, verdicts
                FROM move_events
                WHERE rater_population='csm' AND run_id=%s AND response_outcome='csm'
                  AND call_id=%s AND source_ref=%s AND playbook_id=%s
            """, (RUN_ID, c, s, p))
            for r in cur.fetchall():
                backup.append(dict(zip(
                    ("move_event_id", "grader_arm", "call_id", "source_ref", "playbook_id",
                     "response_outcome", "response_text", "verdicts"), r)))
    bpath = Path(__file__).resolve().parent.parent / "artifacts" / "layer_d_v4_reclassified_backup.json"
    if bpath.exists():
        raise SystemExit(f"{bpath.name} already exists -- refusing to overwrite the only copy "
                         f"of the _v3 verdicts. Move it aside deliberately if this is a new relabel.")
    bpath.write_text(json.dumps(backup, indent=1, default=str), encoding="utf-8")
    print(f"backed up {len(backup)} rows (both arms) to {bpath.name}")
    assert len(backup) == 2 * len(keys), (len(backup), len(keys))   # one row per arm per moment

    # get_connection is autocommit; the explicit transaction block is what makes the
    # relabel all-or-nothing (a crash mid-loop otherwise leaves half the moments done).
    n_rows = 0
    with conn.transaction():
        with conn.cursor() as cur:
            for c, s, p in keys:
                cur.execute("""
                    UPDATE move_events SET response_outcome='interjection', verdicts='[]'::jsonb
                    WHERE rater_population='csm' AND run_id=%s AND response_outcome='csm'
                      AND call_id=%s AND source_ref=%s AND playbook_id=%s
                """, (RUN_ID, c, s, p))
                n_rows += cur.rowcount
    assert n_rows == 2 * len(keys), (n_rows, len(keys))
    print(f"\nrelabelled {n_rows} move_events rows across both arms")

    db = sqlite3.connect(checkpoint._DB)
    for run_id, v3, v4 in LAYER_COPIES:
        rows = db.execute("SELECT item FROM checkpoints WHERE run_id=? AND layer=?", (run_id, v3)).fetchall()
        assert rows, f"no _v3 checkpoint rows under {run_id} / {v3} -- layer string typo?"
        for (item,) in rows:
            db.execute("INSERT OR IGNORE INTO checkpoints (run_id, item, layer) VALUES (?,?,?)", (run_id, item, v4))
        db.commit()
        have = db.execute("SELECT COUNT(*) FROM checkpoints WHERE run_id=? AND layer=?", (run_id, v4)).fetchone()[0]
        print(f"checkpoints {run_id} {v4}: {have} (from {len(rows)} _v3 rows)")
    db.close()

    rows = storage.refresh_move_performance(conn)
    print(f"move_performance rebuilt: {rows} rows")
    (Path(__file__).resolve().parent.parent / "artifacts" / "layer_d_v4_reclassified.json").write_text(
        json.dumps([{"call_id": c, "source_ref": s, "playbook_id": p, "response_text": txt}
                    for c, s, p, txt in affected], indent=1), encoding="utf-8")
    conn.close()


if __name__ == "__main__":
    main()
