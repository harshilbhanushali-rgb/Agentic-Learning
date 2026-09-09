#!/usr/bin/env python3
"""How often does `improve_at_move` actually focus on ONE move? (issue #23)

    cd Brain && ../.venv/Scripts/python.exe ../ask-naren/audit/measure_move_match_rate.py

Needs the Joveo VPN: it reads the live playbooks from Postgres. Reads only -- no gateway
call, no generation, no write anywhere.

RECORDED RESULT, 2026-09-09: **26.1%** (69 of 264 ask x playbook pairs), over 33 live
playbooks whose 121 `key_moves` names average 9.4 words.

WHY IT EXISTS AS A SCRIPT RATHER THAN A SENTENCE. The rate is the whole disclosure behind
`improve_at_move` -- it is what says the intent delivers the ONE thing a CSM named only a
quarter of the time and the whole play otherwise. A number that cannot be re-run is a number
that quietly rots as the playbooks change, and this project's rule is that a claim carries
its instrument.

WHAT IT DOES NOT MEASURE: whether the move it picks is the RIGHT one. There is no labelled
set of (ask -> correct move), so this is a rate with no accuracy beside it. A looser matcher
would score higher here and might be worse, which is exactly why the matcher was left
conservative -- see `rendering.improve_at_move`.


The matcher is plain word overlap against the move NAME. Live move names turn out to be long
generated sentences ("Implement standardized campaign parameter structures and tracking
solutions to eliminate attribution gaps"), so a CSM's plain words may rarely overlap one.
If `focused` is almost never true, the intent's core promise -- the ONE thing they asked
about -- is mostly unmet, and that has to be said rather than discovered.
"""
import sys
from pathlib import Path

BRAIN = Path(r"C:\PF\Joveo\CS-platform\Brain")
sys.path.insert(0, str(BRAIN))
sys.path.insert(0, str(BRAIN / "ops"))

from config import load_config                      # noqa: E402
from shared import storage                          # noqa: E402
from ask_naren import rendering                     # noqa: E402
import serve_ask_naren as srv                       # noqa: E402

ASKS = [
    "the bit where i have to justify our numbers against a competitor",
    "i keep fumbling setting expectations on how long integration takes",
    "i want to get sharper at reframing cost per hire on their own baseline",
    "im weak at explaining budget pacing when spend overruns",
    "i never handle publisher exclusions well",
    "i struggle to explain attribution gaps",
    "i want to get better at tracking campaign performance",
    "i come off badly when a client challenges our targeting",
]

config = load_config()
conn = srv._connect_read_only(config.database_url, srv.DEFAULT_HOSTADDR)
try:
    rows = [r for r in storage.get_playbooks(conn, "live") if (r or {}).get("playbook")]
finally:
    conn.close()

print(f"live playbooks: {len(rows)}")
names = [(m.get("name") or "") for r in rows for m in (r["playbook"].get("key_moves") or [])]
print(f"moves: {len(names)}   mean words per move name: "
      f"{sum(len(n.split()) for n in names) / max(len(names), 1):.1f}")

focused = 0
total = 0
for ask in ASKS:
    for r in rows:
        moves = [m for m in (r["playbook"].get("key_moves") or [])
                 if (m.get("name") or "").strip()]
        if not moves:
            continue
        total += 1
        if rendering._best_move(ask, moves) is not None:
            focused += 1
print(f"\nask x playbook pairs: {total}")
print(f"FOCUSED on one move:  {focused} = {100 * focused / max(total, 1):.1f}%")

print("\n-- what a realistic ask does against the playbook it would actually route to --")
for ask in ASKS[:4]:
    best_any = None
    for r in rows:
        moves = [m for m in (r["playbook"].get("key_moves") or [])
                 if (m.get("name") or "").strip()]
        m = rendering._best_move(ask, moves)
        if m:
            best_any = (r["scenario_key"], m["name"][:70])
            break
    print(f"  {ask[:56]!r}")
    print(f"     -> {best_any if best_any else 'NO MOVE MATCHED IN ANY PLAYBOOK'}")
