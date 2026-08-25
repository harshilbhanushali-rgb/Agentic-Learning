#!/usr/bin/env python3
"""SHIP THE `union_base` TAXONOMY TO POSTGRES — snapshot, replace, load.

Handoff: Brain/HANDOFF_SHIP_LAYER_AB_2026-08-19.md
Spec:    docs/superpowers/specs/2026-08-19-routing-playbook-ab-design.md

*** THIS IS NOT AN UPSERT, AND TREATING IT AS ONE PRODUCES AN INCOHERENT DATABASE. ***
Measured against the live DB 2026-08-19: 161 live scenario keys vs 259 new ones, with only
**4** in common. So `upsert_scenario` alone would leave a 416-row Frankenstein taxonomy — 157
dead scenarios from the old map beside 255 new ones — and those 4 "updates" are the worst
case, silently rewriting a key to describe a DIFFERENT cluster from a DIFFERENT corpus.

Everything downstream hangs off `scenarios` and every FK is ON DELETE NO ACTION, so Postgres
REFUSES a parent delete until its children go first:

    gap_events.rubric_id          -> rubrics
    milestone_performance.rubric_id -> rubrics
    rubrics.scenario_id           -> scenarios
    kb_pairs.scenario_id          -> scenarios

Hence the order below. Deleting children first is not tidiness, it is the only order the
constraints permit.

WHAT THIS DELIBERATELY LEAVES EMPTY, on the operator's accepted terms: `rubrics` (84
milestone-era rows), `gap_events` (2,473) and `milestone_performance` (378) are all keyed to
the OLD taxonomy and go with it. Layer C is DARK afterwards until a playbook table exists —
`db/schema.sql` has no such table, so the validated playbooks have nowhere to land yet.
`kb_pairs` is repopulated by re-running Layer B (free, deterministic, ~4 min).

SAFETY, and it deviates from `clear_data.py`'s convention DELIBERATELY (that file has no
__main__ guard so that importing it cannot happen by accident; this one has a guard AND a
required flag, which is strictly safer, not less):
  * DRY RUN IS THE DEFAULT. Nothing is written without --apply.
  * The snapshot is taken FIRST and its row counts VERIFIED against the source before a
    single delete runs. A short snapshot aborts the whole thing.
  * It REFUSES to reuse an existing snapshot schema, so a previous backup can never be
    clobbered by a second attempt.
  * Deletes and the load run in ONE transaction. Any failure rolls the whole thing back.
  * The Neon DNS block is handled with hostaddr (see --hostaddr), keeping `host` in the URL
    because Neon routes by TLS SNI and binds SCRAM to the hostname.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe ops/ship_union_taxonomy.py                    # dry run
    ..\\.venv\\Scripts\\python.exe ops/ship_union_taxonomy.py --apply            # do it
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TAXONOMY_ARTIFACT = "artifacts/adjudication_ab_union_base.json"
SNAPSHOT_SCHEMA = "pre_union_20260819"

# Every public table, snapshotted. Not just the ones being touched: a restore of a partial
# snapshot would silently mix eras, and the whole point of the schema-copy pattern this repo
# already uses 14 times over is that the snapshot is a complete, self-consistent era.
SNAPSHOT_TABLES = ("calls", "csms", "gap_events", "kb_pairs", "milestone_performance",
                   "move_events", "move_performance",
                   "playbooks", "primary_topics", "response_taxonomy_candidates", "rubrics",
                   "scenarios", "signal_recognition_gaps")

# CHILDREN BEFORE PARENTS. Order is forced by ON DELETE NO ACTION, verified against the live
# FK graph; reordering this list makes the migration fail rather than corrupt, but it fails.
#
# `playbooks` was added 2026-08-19 with the Layer C playbook schema, and it is here for a
# reason worth stating: playbooks.scenario_id is a NOT NULL FK to scenarios, chosen
# deliberately (a playbook is an output of ONE taxonomy and dies with it; the JSON artifacts
# on disk are the archive). Omitting it here would not lose data — Postgres would REFUSE the
# scenarios delete partway through the migration instead. Both tables are also in
# SNAPSHOT_TABLES above, so the documents survive in the dated backup schema either way.
# See docs/superpowers/specs/2026-08-19-playbook-schema-design.md (gate G-P7).
# `move_events`/`move_performance` (Layer D redesign, 2026-08-20) key playbook_id NOT NULL,
# so they must go before `playbooks` for the same G-P7 reason playbooks goes before
# `scenarios`. Both are also in SNAPSHOT_TABLES, and `existing()` below keeps this script
# runnable on databases that predate them.
DELETE_ORDER = ("move_events", "move_performance", "gap_events", "milestone_performance",
                "rubrics", "playbooks", "kb_pairs", "scenarios")

# `primary_topic` is NOT NULL and absent from every adjudication row. Production derives it by
# centroid-grouping scenarios and then LLM-LABELLING each group — work the union adjudication
# never did. `matching_strategy: flat` means the only consumer of that hierarchy
# (`assign_scenarios_two_stage`) is OFF, so nothing reads it today. A literal sentinel is
# written rather than the scenario_key, because a key in this column would LOOK like a derived
# hierarchy to the next reader and quietly become load-bearing.
PRIMARY_TOPIC_SENTINEL = "ungrouped"


def connect(hostaddr: str | None):
    import psycopg
    from config import load_config

    url = load_config().database_url
    if not url:
        raise SystemExit("DATABASE_URL is not configured")
    if hostaddr and "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + f"hostaddr={hostaddr}"
        print(f"[dns] hostaddr={hostaddr} (host kept in the URL for SNI/SCRAM)")
    return psycopg.connect(url, connect_timeout=30)


def build_rows() -> list[dict]:
    """The 259 scenario rows to load, from the shipped adjudication artifact.

    Row SELECTION is delegated to `scenario_map_from_rows`, which is the audited
    implementation of the four-kind rule: `scenario`/`mechanics`/`logistics` own a key and
    load; `merged` is RETAINED but folds into its target and contributes NO key; `failed` is
    excluded. 48 merged rows are correctly absent — 43 of them have an empty
    business_description precisely because they were never scenarios, and loading them would
    double-count their targets' evidence.
    """
    from calibration.layer_bc_arms import scenario_map_from_rows

    art = json.loads(Path(TAXONOMY_ARTIFACT).read_text(encoding="utf-8-sig"))
    if art.get("limit"):
        raise SystemExit(f"{TAXONOMY_ARTIFACT} is a --limit path test, not a taxonomy")
    scenario_map, cluster_of_key = scenario_map_from_rows(art["rows"])
    by_cluster = {r.get("cluster_id"): r for r in art["rows"]}

    rows = []
    for key, info in sorted(scenario_map.items()):
        src = by_cluster.get(cluster_of_key.get(key), {})
        rows.append({
            "scenario_key": key,
            "primary_topic": PRIMARY_TOPIC_SENTINEL,
            "business_description": info["business_description"],
            "keyphrases": list(info["keyphrases"]),
            "soft_skills": list(src.get("soft_skills") or []),
            # bloom_level is LLM-generated; `upsert_scenario` already defaults anything
            # outside the CHECK enum to 'understand' with a warning, deliberately, so one bad
            # value cannot strand a batch. 71 rows carry an empty value and take that path.
            "bloom_level": src.get("bloom_level") or "understand",
            "is_coachable": info["is_coachable"],
            "cluster_kind": info["cluster_kind"],
            "support_calls": int(src.get("calls") or 0),
            "support_clauses": int(src.get("n_items") or 0),
            "call_coverage": float(src.get("coverage") or 0.0),
            "triage_verdict": src.get("triage"),
            "adjudication_reason": src.get("reason"),
            "primary_topic_key": None,
        })
    if not rows:
        raise SystemExit("no scenario rows built — refusing to wipe a taxonomy for nothing")
    return rows


def existing(cur, tables: tuple[str, ...]) -> tuple[str, ...]:
    """`tables` filtered to those that actually exist in public, ORDER PRESERVED.

    Needed because this script's table lists move ahead of deployed databases. `playbooks`
    was added 2026-08-19; on any database that predates it, an unfiltered
    `select count(*) from public."playbooks"` raises UndefinedTable during the very first
    read -- BEFORE the dry-run guard -- so adding a table to the lists above would render
    this script unrunnable rather than merely incomplete. Skipping is safe in both roles:
    a table that does not exist has nothing to back up and nothing to delete.
    """
    present = []
    for t in tables:
        cur.execute("select to_regclass(%s)", (f"public.{t}",))
        if cur.fetchone()[0] is not None:
            present.append(t)
    skipped = [t for t in tables if t not in present]
    if skipped:
        print(f"[schema] not present, skipping: {', '.join(skipped)}")
    return tuple(present)


def counts(cur, schema: str, tables) -> dict:
    out = {}
    for t in tables:
        cur.execute(f'select count(*) from {schema}."{t}"')
        out[t] = cur.fetchone()[0]
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true",
                   help="actually write. Without this it is a dry run.")
    p.add_argument("--hostaddr", default="18.138.49.39",
                   help="IP for the Neon host; the system resolver REFUSES *.neon.tech")
    p.add_argument("--snapshot", default=SNAPSHOT_SCHEMA)
    a = p.parse_args()

    rows = build_rows()
    n_coach = sum(1 for r in rows if r["is_coachable"])
    print(f"[artifact] {len(rows)} scenario rows to load "
          f"({n_coach} coachable, {len(rows) - n_coach} sinks) from {TAXONOMY_ARTIFACT}")
    print(f"[artifact] primary_topic := {PRIMARY_TOPIC_SENTINEL!r} for all rows "
          f"(hierarchy NOT derived; matching_strategy is flat so nothing reads it)")

    with connect(a.hostaddr) as conn, conn.cursor() as cur:
        snapshot_tables = existing(cur, SNAPSHOT_TABLES)
        delete_order = existing(cur, DELETE_ORDER)
        before = counts(cur, "public", snapshot_tables)
        cur.execute("select scenario_key from public.scenarios")
        live = {r[0] for r in cur.fetchall()}
        new = {r["scenario_key"] for r in rows}
        print("\n[live] public row counts:")
        for t, n in before.items():
            print(f"   {t:<34} {n:>8,}")
        print(f"\n[diff] live keys {len(live)} | new keys {len(new)} | "
              f"overlap {len(live & new)} | orphaned-if-upserted {len(live - new)}")

        cur.execute("select 1 from pg_namespace where nspname = %s", (a.snapshot,))
        if cur.fetchone():
            raise SystemExit(
                f"snapshot schema {a.snapshot!r} ALREADY EXISTS — refusing to clobber a "
                f"previous backup. Pick another --snapshot name or drop that schema "
                f"deliberately.")

        print("\nPLAN")
        print(f"  1. CREATE SCHEMA {a.snapshot} + copy all {len(snapshot_tables)} tables, "
              f"then VERIFY every row count matches")
        print(f"  2. DELETE FROM (children first, forced by ON DELETE NO ACTION): "
              f"{', '.join(delete_order)}")
        print(f"  3. upsert_scenario x {len(rows)}")
        print("  4. (separate step, not here) re-run Layer B to repopulate kb_pairs")
        print("\n  AFTER THIS, LAYER C IS DARK: rubrics/gap_events/milestone_performance are "
              "keyed to the old taxonomy and are deleted with it, and playbooks have no "
              "table yet.")

        if not a.apply:
            print("\nDRY RUN — nothing written. Re-run with --apply to execute.")
            return

        from shared import storage

        # --- 1. snapshot, then PROVE it before destroying anything --------------------
        cur.execute(f'create schema "{a.snapshot}"')
        for t in snapshot_tables:
            cur.execute(f'create table "{a.snapshot}"."{t}" as '
                        f'select * from public."{t}"')
        snap = counts(cur, f'"{a.snapshot}"', snapshot_tables)
        bad = {t: (before[t], snap[t]) for t in snapshot_tables if before[t] != snap[t]}
        if bad:
            conn.rollback()
            raise SystemExit(f"SNAPSHOT VERIFICATION FAILED {bad} — rolled back, nothing "
                             f"deleted. The backup is not trustworthy, so the migration "
                             f"must not proceed.")
        print(f"\n[1/3] snapshot {a.snapshot} verified: "
              f"{sum(snap.values()):,} rows across {len(snap)} tables")

        # --- 2. delete children before parents ---------------------------------------
        for t in delete_order:
            cur.execute(f'delete from public."{t}"')
            print(f"[2/3] deleted {cur.rowcount:>8,} from {t}")

        # --- 3. load ------------------------------------------------------------------
        for r in rows:
            # commit=False IS LOAD-BEARING. upsert_scenario commits by default, and this
            # connection is deliberately not autocommit, so the first of these calls would
            # otherwise commit step 2's children-first DELETEs -- making them permanent
            # before the post-load verification below has run, and turning its rollback
            # into a no-op that still printed "rolled back". THIS is what makes the
            # single-transaction guarantee in the docstring true rather than aspirational.
            storage.upsert_scenario(conn, r, commit=False)
        after = counts(cur, "public", snapshot_tables)
        print(f"[3/3] loaded {after['scenarios']:,} scenarios")

        cur.execute("select count(*) from public.scenarios where is_coachable")
        got_coach = cur.fetchone()[0]
        if after["scenarios"] != len(rows) or got_coach != n_coach:
            conn.rollback()
            raise SystemExit(f"POST-LOAD MISMATCH: {after['scenarios']} scenarios "
                             f"({got_coach} coachable), expected {len(rows)} ({n_coach}) — "
                             f"rolled back.")
        conn.commit()

        print("\nCOMMITTED. public row counts now:")
        for t, n in after.items():
            print(f"   {t:<34} {n:>8,}  (was {before[t]:,})")
        print(f"\nRestore is a schema swap away: everything is in {a.snapshot}.")
        print("NEXT: re-run Layer B to repopulate kb_pairs (needs the 3072 Pinecone index).")
        print("SHIP TAXONOMY COMPLETE")


if __name__ == "__main__":
    main()
