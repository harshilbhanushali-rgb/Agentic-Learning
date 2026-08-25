#!/usr/bin/env python3
"""SCOPE the Layer C playbook backfill BEFORE spending a single chat call.

Handoff: Brain/HANDOFF_LAYER_C_SHIPPED_2026-08-19.md §3.1

5 of 34 coachable scenarios have a live playbook. This measures what the other 29 actually
have to work with, so the exclusion rule and the budget are chosen from the evidence
distribution rather than guessed -- which is what the handoff requires BEFORE any spend
("pre-register an exclusion rule and cap attempts at 2 BEFORE spending").

READ-ONLY AND FREE. Postgres reads plus the cached response vectors. No chat calls, no
embeddings, no writes.

The numbers that matter, from the frozen synthesis constants:
    N_EVIDENCE_MAX = 50   pairs fed to synthesis (selection degrades gracefully below this)
    ACCT_FLOOR     = 8    accounts phase 1 tries to cover (also degrades)
    MIN_MOVES      = 3    a document below this is schema_collapsed and FAILS PB0

Neither of the first two hard-fails on a thin pool. MIN_MOVES does, and no retry budget can
rescue a scenario whose evidence cannot support three distinct moves -- so the exclusion rule
has to be a pre-spend judgement about pool depth.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/playbook_backfill_scope.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

N_EVIDENCE_MAX = 50
ACCT_FLOOR = 8
CALLS_PER_DOC = 3.9          # measured average incl. retries (handoff §3.1)


def main() -> None:
    import psycopg

    from config import load_config

    url = load_config().database_url
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + "hostaddr=18.138.49.39"

    with psycopg.connect(url, connect_timeout=30, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT s.scenario_key,
                   count(*)                             AS pairs,
                   count(DISTINCT p.call_id)            AS calls,
                   (SELECT count(*) FROM playbooks pb
                     WHERE pb.scenario_key = s.scenario_key AND pb.status = 'live') AS has_live
            FROM scenarios s
            JOIN kb_pairs p ON p.scenario_key = s.scenario_key
            WHERE s.is_coachable
            GROUP BY s.scenario_key
            ORDER BY pairs DESC
        """)
        rows = cur.fetchall()
        cur.execute("SELECT count(*) FROM scenarios WHERE is_coachable")
        n_coachable = cur.fetchone()[0]

    routed = {r[0] for r in rows}
    print(f"[taxonomy] {n_coachable} coachable scenarios; {len(routed)} have at least one "
          f"routed pair")
    unrouted = n_coachable - len(routed)
    if unrouted:
        print(f"[taxonomy] {unrouted} coachable scenario(s) have ZERO routed pairs — no "
              f"evidence exists, so no playbook is possible at any budget")

    done = [r for r in rows if r[3]]
    todo = [r for r in rows if not r[3]]
    print(f"[state] {len(done)} live playbooks, {len(todo)} scenarios to backfill\n")

    print(f"{'scenario_key':<52} {'pairs':>6} {'calls':>6}  band")
    print("-" * 82)
    bands = {"full": [], "partial": [], "thin": [], "excluded": []}
    for key, pairs, calls, _ in todo:
        if pairs >= N_EVIDENCE_MAX and calls >= ACCT_FLOOR:
            band = "full"
        elif pairs >= 25 and calls >= 4:
            band = "partial"
        elif pairs >= 12:
            band = "thin"
        else:
            band = "excluded"
        bands[band].append((key, pairs, calls))
        print(f"{key:<52} {pairs:>6} {calls:>6}  {band}")

    print()
    print("BANDS")
    print(f"  full     >= {N_EVIDENCE_MAX} pairs AND >= {ACCT_FLOOR} calls : "
          f"{len(bands['full']):>3}  — the pilot's own conditions, expect a normal document")
    print(f"  partial  >= 25 pairs AND >= 4 calls        : {len(bands['partial']):>3}  "
          f"— under-fed but plausibly reaches 3 moves")
    print(f"  thin     >= 12 pairs                       : {len(bands['thin']):>3}  "
          f"— at real risk of schema_collapse; the tail the handoff warns about")
    print(f"  excluded  < 12 pairs                       : {len(bands['excluded']):>3}  "
          f"— cannot plausibly support 3 distinct evidenced moves")

    for label in ("full", "partial", "thin"):
        n = len(bands[label])
        cum = sum(len(bands[x]) for x in ("full", "partial", "thin")[:
                  ("full", "partial", "thin").index(label) + 1])
        print(f"\n  through '{label}': {cum} document(s) ≈ {cum * CALLS_PER_DOC:.0f} chat calls "
              f"at {CALLS_PER_DOC}/doc")

    print("\nNOTE: pairs/calls are the SUPPLY, not a guarantee. MIN_MOVES=3 is judged on the "
          "synthesised document, so a thin-but-varied pool can pass where a large but "
          "repetitive one fails. This bounds the spend; it does not predict PB0.")


if __name__ == "__main__":
    main()
