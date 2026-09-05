#!/usr/bin/env python3
"""G-R2 support: dump EVERY `never` cell's moment population for a spot-read. Zero spend.

Pre-registration: docs/findings/layer-d-say-arm.md §11 (G-R2). A "never" is only as
good as the moments it was counted over: if the CSM's scored moments on that playbook
are mis-routed, are deferrals mis-classified as her replies, or are fragments, the
zero is a segmentation artifact, not a repertoire gap. This script writes one packet
per CSM listing, for each never cell, every scored moment (client trigger + her reply
+ the stored say verdicts for that move) so a reader can judge each moment as
  OK        a real client moment on this scenario, with a substantive CSM reply
  MISROUTED the moment is not about this scenario
  NOT_HER   the reply is not the CSM's own substantive answer (fragment, colleague)
The cell survives if >= 80% of its moments are OK (§11 bar applies to CELLS:
>= 80% of never cells must survive).

Reads stored move_events only. Writes artifacts/layer_d_never_cells_<rater>.txt and
artifacts/layer_d_never_cells_key.json (the cell list, for scoring).

Usage (from Brain/, VPN up):  python calibration/layer_d_never_cells_dump.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibration import ARTIFACTS_DIR  # noqa: E402


def main() -> None:
    import psycopg
    from config import load_config
    from layer_d import aggregate, repertoire
    from layer_d.pipeline import live_playbooks_flat
    from shared import storage

    url = load_config().database_url
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + "hostaddr=18.138.49.39"
    conn = psycopg.connect(url, autocommit=True)

    def to_rates(rows):
        return [aggregate.MoveRate(r["playbook_id"], r["move_id"], r["attempts"],
                                   r["hits"], r["partials"]) for r in rows]

    naren = to_rates(storage.get_move_rates(conn, "naren", "say").get(aggregate.NAREN, []))
    csm = {rid: to_rates(rows) for rid, rows in storage.get_move_rates(conn, "csm", "say").items()}
    coverage = repertoire.repertoire_coverage(repertoire.naren_repertoire(naren), csm)
    meta = {}
    for pb in live_playbooks_flat(conn):
        for m in pb["key_moves"]:
            meta[(pb["playbook_id"], m["move_id"])] = {
                "scenario_key": pb["scenario_key"], "name": m.get("name", ""),
                "criterion": m.get("criterion", ""),
                "situation_signature": pb.get("situation_signature", "")}

    key = []
    for rater_id, cells in sorted(coverage.items()):
        never = [c for c in cells if c.state == repertoire.NEVER]
        parts = [f"G-R2 SPOT-READ PACKET -- rater {rater_id} -- {len(never)} never cell(s)\n"
                 f"For EVERY moment below answer OK / MISROUTED / NOT_HER (see script docstring).\n"
                 f"Respond as JSON: [{{\"cell\": 1, \"moments\": [{{\"m\": 1, \"judgement\": \"OK\"}}, ...]}}, ...]\n"]
        for ci, c in enumerate(never, 1):
            cell = (c.move.playbook_id, c.move.move_id)
            mt = meta.get(cell, {})
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT call_id, source_ref, trigger_text, response_text, verdicts
                    FROM move_events
                    WHERE rater_population='csm' AND rater_id=%s AND grader_arm='say'
                      AND playbook_id=%s AND response_outcome='csm' AND verdicts != '[]'::jsonb
                    ORDER BY call_id, move_event_id
                """, (rater_id, c.move.playbook_id))
                rows = cur.fetchall()
            key.append({"cell": ci, "rater_id": rater_id, "playbook_id": cell[0],
                        "move_id": cell[1], "scenario_key": mt.get("scenario_key"),
                        "csm_calls": c.csm_calls, "calls_needed": c.calls_needed,
                        "n_moments": len(rows)})
            block = [f"\n{'=' * 78}\nCELL {ci}  [{mt.get('scenario_key')}] {c.move.move_id}: {mt.get('name')}",
                     f"SCENARIO: {mt.get('situation_signature')}",
                     f"THE MOVE (never credited): {mt.get('criterion')}",
                     f"her calls on this scenario: {c.csm_calls} (needed {c.calls_needed}); "
                     f"scored moments: {len(rows)}"]
            for mi, (call_id, src, trig, resp, verdicts) in enumerate(rows, 1):
                v = next((x for x in verdicts if x.get("move_id") == c.move.move_id), {})
                block.append(f"\n  MOMENT {mi}  (call {call_id}, {src}; stored verdict for "
                             f"{c.move.move_id}: {v.get('verdict', '?')})")
                block.append(f"  CLIENT: {trig.strip()[:700]}")
                block.append(f"  CSM:    {resp.strip()[:700]}")
            parts.append("\n".join(block))
        out = ARTIFACTS_DIR / f"layer_d_never_cells_{rater_id}.txt"
        out.write_text("\n".join(parts), encoding="utf-8")
        print(f"[never cells] {rater_id}: {len(never)} cells, "
              f"{sum(k['n_moments'] for k in key if k['rater_id'] == rater_id)} moments -> {out.name}")
    (ARTIFACTS_DIR / "layer_d_never_cells_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    conn.close()


if __name__ == "__main__":
    main()
