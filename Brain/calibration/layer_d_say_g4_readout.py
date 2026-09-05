#!/usr/bin/env python3
"""G-S4 readout: Naren's call-level occurrence rates on SAY moves. ZERO chat spend.

Pre-registration (docs/findings/layer-d-say-arm.md §5): per-cell rates published,
sub-floor cells flagged BEFORE any coaching number is read; >= 50% of SAY cells
must be non-dead at the SHIPPED dead_check_naren_floor for the arm to be worth its
production spend. A floor-sensitivity table (0.50 / 0.30 / 0.10) is reported for
the operator -- the primary verdict is at the shipped floor, the table is context,
and moving the floor afterward is an operator decision to be argued in writing.

Reads move_performance (grader_arm='say', rater_population='naren') -- run
`ops/run_layer_d.py --naren-only` first. Also prints moments-per-call densities
(the §2 opportunity readout) for the benchmark side.

Usage (from Brain/):  python calibration/layer_d_say_g4_readout.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

FLOORS = (0.50, 0.30, 0.10)
MIN_ATTEMPTS = 8   # tuning layer_d.min_attempts_to_rank -- unmeasured is not dead


def main() -> None:
    import psycopg
    from config import load_config
    from shared import storage
    from shared.tuning import get_tuning

    url = load_config().database_url
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + "hostaddr=18.138.49.39"
    conn = psycopg.connect(url, autocommit=True)

    tuning_d = get_tuning().layer_d
    shipped = tuning_d.dead_check_naren_floor
    rows = storage.get_move_rates(conn, "naren", "say").get("naren", [])
    dens = storage.get_say_densities(conn)

    scen_of: dict[tuple[int, str], str] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT playbook_id, scenario_key FROM playbooks WHERE status='live'")
        pid_to_scen = dict(cur.fetchall())
    conn.close()

    if not rows:
        raise SystemExit("no naren/say rows in move_performance -- run "
                         "ops/run_layer_d.py --naren-only first (then this again)")

    print(f"=== G-S4: Naren call-level occurrence on SAY moves "
          f"({len(rows)} cells) ===\n")
    print(f"{'scenario':<44} {'move':<4} {'said/calls':>10} {'rate':>6} "
          f"{'m/call':>7}")
    measured = []
    for r in sorted(rows, key=lambda r: (pid_to_scen.get(r['playbook_id'], '?'),
                                         r['move_id'])):
        cell = (r["playbook_id"], r["move_id"])
        scen = pid_to_scen.get(r["playbook_id"], "?")
        scen_of[cell] = scen
        rate = (r["hits"] + 0.5 * r["partials"]) / r["attempts"] if r["attempts"] else 0.0
        said = r["hits"] + r["partials"]
        d = dens.get(("naren", r["playbook_id"], r["move_id"]))
        mpc = f"{d[0] / d[1]:.1f}" if d and d[1] else "-"
        flag = "" if r["attempts"] >= MIN_ATTEMPTS else "  (below attempts floor)"
        print(f"{scen[:44]:<44} {r['move_id']:<4} {said:>4}/{r['attempts']:<5} "
              f"{rate:>6.2f} {mpc:>7}{flag}")
        if r["attempts"] >= MIN_ATTEMPTS:
            measured.append(rate)

    print(f"\nmeasured cells (attempts >= {MIN_ATTEMPTS}): {len(measured)} "
          f"of {len(rows)}")
    for floor in dict.fromkeys((shipped,) + FLOORS):
        alive = sum(1 for x in measured if x >= floor)
        share = alive / len(measured) if measured else float("nan")
        tag = "  <-- SHIPPED FLOOR, the G-S4 verdict" if floor == shipped else ""
        print(f"  floor {floor:.2f}: {alive}/{len(measured)} non-dead "
              f"({share:.0%}){tag}")
    if measured:
        alive = sum(1 for x in measured if x >= shipped)
        ok = alive / len(measured) >= 0.50
        print(f"\nG-S4 (>=50% of measured SAY cells non-dead at the shipped floor "
              f"{shipped:.2f}): {'PASS' if ok else 'FAIL'}")
    print("\n[Zero chat spend; pure read of move_performance.]")


if __name__ == "__main__":
    main()
