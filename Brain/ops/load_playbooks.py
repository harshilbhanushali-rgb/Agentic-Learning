#!/usr/bin/env python3
"""LOAD THE SCENARIO PLAYBOOKS INTO POSTGRES — this is what ships Layer C.

Handoff: Brain/HANDOFF_SHIP_LAYER_AB_2026-08-19.md §2.2 (the highest-value remaining item)
Spec:    docs/superpowers/specs/2026-08-19-playbook-schema-design.md (FROZEN GATES in §5)

Layer C is *validated* but was not *shippable*: `db/schema.sql` had no playbook table, so the
5 validated documents (PB0 5/5, PB2 4/5 pooled 11-4 — the first Layer C output ever to beat
its placebo), their 5 placebo twins, and the 22 routing-trial documents had nowhere to land.
This loads all 32 into `playbooks`.

ZERO SPEND. Every document already exists on disk. No chat calls, no embeddings, no Pinecone.

WHAT LANDS AS WHAT (frozen in spec §4, and the distinction is the whole safety story):
    pbv_playbooks_snapped.json  arm=real     -> status='live'      PRODUCTION CONTENT
    pbv_playbooks_snapped.json  arm=placebo  -> status='placebo'   NEVER production
    rt_*/rte_*                  arm=concat   -> status='trial'     control arm, evidence only
    rt_*/rte_*                  arm=r1       -> status='trial'     UNRESOLVED, not shipped
Placebo twins and UNRESOLVED r1 documents live in the SAME table as production content and
are indistinguishable without the status filter. `storage.get_playbook_for_scenario` defaults
to status='live' for exactly that reason.

SAFETY:
  * DRY RUN IS THE DEFAULT. Nothing is written without --apply.
  * G-P1 runs BEFORE any write: every scenario_key must resolve to a live scenarios row, read
    from Postgres, not from the artifact. One miss refuses the entire load.
  * Writes are per-row upserts rather than one transaction, DELIBERATELY and unlike
    ship_union_taxonomy.py: that script deletes, so atomicity is survival there. This one only
    inserts new rows into a table nothing reads yet, and it is idempotent by
    ON CONFLICT (scenario_key, arm, source_artifact), so a partial load is fixed by running it
    again rather than by a rollback.
  * Every frozen gate is re-verified AFTER the write, by reading back from Postgres.
  * Neon DNS is handled with hostaddr, keeping `host` in the URL (Neon routes by TLS SNI and
    binds SCRAM to the hostname).

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe ops/load_playbooks.py            # dry run + gates
    ..\\.venv\\Scripts\\python.exe ops/load_playbooks.py --apply    # load, then verify
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# (artifact filename, status for each arm). An arm absent from the map is a hard error rather
# than a default: a new arm appearing in an artifact is exactly the case where guessing
# 'trial' could silently promote or bury something.
#
# *** EVERY ENTRY MUST BE A SNAPPED ARTIFACT. *** The verbatim snap is not a polish step, it
# is what VALIDATED this method: the pilot FAILED PB0 pre-snap on model quote-smoothing
# (~1.4% per quote) and passed 10/10 after. A pre-snap document contains quotes that do not
# exactly match any real evidence text.
#
# This list originally named `rt_playbooks_*` / `rte_playbooks_*` — the PRE-SNAP outputs —
# because those are the files the synthesis stage writes and the snapped ones live under a
# different prefix (`rt_snapped_*`). 22 unsnapped documents were loaded before it was caught.
# The difference is not cosmetic: across the four artifacts the snap repaired 17 quotes,
# dropped 6 that could not be tied to real text, and dropped 2 whole MOVES.
#
# Note the asymmetry that made it easy to miss: the pbv entry was already correct, because
# there the snapped file is the obvious one (`pbv_playbooks_snapped.json`). `assert_snapped()`
# below now refuses any artifact with a snapped sibling, so the naming cannot mislead again.
#
# *** ORDER IS LOAD-BEARING FOR A PROMOTION. ***
# Documents are built AND written in this order, and `idx_playbooks_one_live` is a partial
# unique index that refuses a second live row per scenario. So an entry that DEMOTES an
# incumbent must sit before the entry that replaces it. pbv (-> superseded) precedes the pbq
# grad arm (-> live) for exactly that reason; swapping them breaks the load.
# Note also that the demotion is DECLARATIVE -- `upsert_playbook` is
# ON CONFLICT (scenario_key, arm, source_artifact) DO UPDATE SET status = EXCLUDED.status, so
# flipping a status here demotes on the next load and is idempotent. No hand-written UPDATE.
ARTIFACT_PLAN: tuple[tuple[str, dict[str, str]], ...] = (
    # DEMOTED 2026-08-24: these 5 were the original flash-lite/2-entry documents. They are
    # superseded by the pbq gradability arm below, which beats them on every measure: 11% vs
    # 15% single-account, 100% vs 15% quotes>=3, and — on a within-packet counterbalanced
    # blind read — 89% usable quotes with ZERO failing quotes and zero vague criteria. Kept
    # at 'superseded' rather than deleted, for traceability. The placebo twins are unaffected:
    # they are the placebo arm of this same artifact and stay placebo.
    ("pbv_playbooks_snapped.json", {"real": "superseded", "placebo": "placebo"}),
    ("rt_snapped_concat.json", {"concat": "trial"}),
    ("rt_snapped_r1.json", {"r1": "trial"}),
    ("rte_snapped_concat.json", {"concat": "trial"}),
    ("rte_snapped_r1.json", {"r1": "trial"}),
    # The 2026-08-20 backfill. Config licensed by the quote-floor A/B: gemini-3.6-flash,
    # reasoning=medium, 3-entry floor, hardened diversity + quote-relevance rules.
    # A blind read put these at 73% of quotes clearly demonstrating their move, against 63%
    # for the original five — better, but well short of the 95% a 5-document probe predicted.
    # Loaded LIVE for testing on the operator's instruction, with that caveat on the record.
    ("pbf_rest_snapped.json", {"real": "live"}),
    ("pbf_thin_snapped.json", {"real": "live"}),
    # PROMOTED 2026-08-24, replacing the pbv originals above. Config: gemini-3.6-flash,
    # reasoning=medium, 3-entry floor, hardened diversity, quote-relevance rule, PLUS the
    # gradability rule (criteria must name a concrete artifact/number/mechanism, never an
    # evaluative adjective) — the property Layer D requires to score a transcript yes/no.
    #
    # THE CAVEAT THAT MUST TRAVEL WITH THIS ENTRY: this arm FAILS G-Q1 at census scale (11%
    # single-account against a 10% ceiling, though that is 2 moves out of 18, where the bar
    # has 5.6pp resolution). It passes G-Q7, the replacement gate — it is better than what it
    # supersedes. Promoting THESE 5 documents is licensed; a taxonomy-wide rollout of this
    # config is NOT. Do not read this entry as licensing the latter.
    ("pbq_36flash_medium_grad_snapped.json", {"real": "live"}),
)

# Pre-snap artifacts that must NEVER be loaded, mapped to what should be loaded instead.
# Kept as an explicit table rather than a name-mangling rule so a future artifact that
# genuinely has no snapped form fails loudly instead of being silently rewritten.
SUPERSEDED_BY_SNAP = {
    "rt_playbooks_concat.json": "rt_snapped_concat.json",
    "rt_playbooks_r1.json": "rt_snapped_r1.json",
    "rte_playbooks_concat.json": "rte_snapped_concat.json",
    "rte_playbooks_r1.json": "rte_snapped_r1.json",
    "pbv_playbooks.json": "pbv_playbooks_snapped.json",
    # The pbq arms (added 2026-08-24) are the case this table was kept explicit FOR.
    # assert_snapped's fallback derives a sibling by rewriting "_playbooks_" -> "_snapped_",
    # and these files are named `..._grad_playbooks.json` -- "_playbooks." with a DOT, not an
    # underscore -- so the rewrite produces the same name and the fallback silently does
    # nothing. This explicit entry is the ONLY thing that refuses the pre-snap pbq file.
    "pbq_36flash_medium_grad_playbooks.json": "pbq_36flash_medium_grad_snapped.json",
}

# G-P3: the exact document count expected from each artifact. A silently-dropped document is
# the failure this exists to catch, so the numbers are frozen here rather than counted at run
# time from the same file that would be wrong.
EXPECTED_COUNTS = {
    "pbv_playbooks_snapped.json": 10,
    "rt_snapped_concat.json": 5,
    "rt_snapped_r1.json": 5,
    "rte_snapped_concat.json": 6,
    "rte_snapped_r1.json": 6,
    # RAW document counts as they appear in the artifact, BEFORE the collapse filter below.
    "pbf_rest_snapped.json": 26,
    "pbf_thin_snapped.json": 3,
    # The pbq gradability arm: the 5 OG scenarios remade (2026-08-24).
    "pbq_36flash_medium_grad_snapped.json": 5,
}
# 32 originals + 25 backfill (26 raw minus 1 schema-collapsed) + 3 thin + 5 pbq remakes.
EXPECTED_TOTAL = 65

# What must actually LAND per artifact, i.e. EXPECTED_COUNTS minus anything the collapse
# exclusion drops. These are two different numbers and conflating them broke G-P3 on the
# first run: the raw check needs 26 for pbf_rest (the artifact really does hold 26), while
# the post-write DB check needs 25 (one was excluded). One constant cannot mean both.
EXPECTED_LOADED = {**EXPECTED_COUNTS, "pbf_rest_snapped.json": 25}

# The playbook body keys, frozen from the trial spec §5. A document missing one is refused;
# an EXTRA key is also refused, because it would be silently dropped by the column mapping.
BODY_KEYS = frozenset({
    "situation_signature", "arc", "key_moves",
    "signature_language", "pitfalls_and_variants", "layer_d_checks",
})

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"
SCHEMA_SQL = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
DDL_BEGIN = "-- >>> PLAYBOOKS DDL BEGIN"
DDL_END = "-- <<< PLAYBOOKS DDL END"

# The status histogram this load must produce, frozen. Printing it is not a gate; asserting
# it is. Without this a run in which nothing landed as 'live' still reports success.
#
# 'live' STAYS AT 33 ACROSS THE 2026-08-24 PROMOTION, and that is the point: 5 pbv originals
# moved to 'superseded' and 5 pbq remakes took their place, so coverage is unchanged at 33 of
# 34 coachable scenarios while the CONTENT of those 5 improved. If this number moves, the
# promotion dropped or duplicated a scenario.
EXPECTED_STATUSES = {"live": 33, "placebo": 5, "trial": 22, "superseded": 5}


def playbooks_ddl() -> str:
    """The `playbooks` DDL, extracted from db/schema.sql between its marker comments.

    Extracted rather than duplicated so there is exactly ONE definition, and executed rather
    than delegated to db/init_db.py for two measured reasons: init_db opens its own connection
    from the raw DATABASE_URL, which skips this script's hostaddr DNS workaround and simply
    fails on this network; and it runs the entire schema, whose dozen
    `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements each take ACCESS EXCLUSIVE on a
    live table BEFORE the IF NOT EXISTS is evaluated -- enough to stall a concurrent run.
    """
    text = SCHEMA_SQL.read_text(encoding="utf-8-sig")
    if DDL_BEGIN not in text or DDL_END not in text:
        raise SystemExit(
            f"could not find the playbooks DDL markers in {SCHEMA_SQL} — the schema and this "
            f"loader have drifted apart; refusing to guess the table definition"
        )
    return text.split(DDL_BEGIN, 1)[1].split(DDL_END, 1)[0]


def connect(hostaddr: str | None):
    import psycopg
    from config import load_config

    url = load_config().database_url
    if not url:
        raise SystemExit("DATABASE_URL is not configured")
    if hostaddr and "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + f"hostaddr={hostaddr}"
        print(f"[dns] hostaddr={hostaddr} (host kept in the URL for SNI/SCRAM)")
    return psycopg.connect(url, connect_timeout=30, autocommit=True)


def assert_snapped(filename: str) -> None:
    """Refuse a pre-snap artifact. Selection errors are invisible to the fidelity gates.

    G-P2 proves the database matches the artifact it was pointed at, byte for byte. It cannot
    notice that the WRONG artifact was chosen -- that is selection, not fidelity, and every
    gate passed while 22 unsnapped documents sat in the table. This is the check that would
    have caught it: a pre-snap file is refused outright, and separately, any artifact with a
    `_snapped_` sibling on disk is refused even if it is not on the known list.
    """
    if filename in SUPERSEDED_BY_SNAP:
        raise SystemExit(
            f"REFUSING {filename}: it is the PRE-SNAP output. Load "
            f"{SUPERSEDED_BY_SNAP[filename]} instead. The verbatim snap is what validated "
            f"this method -- pre-snap documents carry quotes that match no real evidence."
        )
    if "_snapped" not in filename:
        sibling = filename.replace("_playbooks_", "_snapped_")
        if sibling != filename and (ARTIFACTS_DIR / sibling).exists():
            raise SystemExit(
                f"REFUSING {filename}: {sibling} exists on disk and is the snapped form."
            )


def build_documents() -> list[dict]:
    """Every playbook document to load, from the published artifacts.

    Reads only. Never writes an artifact — `pbv_*`, `rt_*` and `rte_*` are published and the
    house rule is that a published artifact is never overwritten.
    """
    docs: list[dict] = []
    for filename, arm_status in ARTIFACT_PLAN:
        assert_snapped(filename)
        path = ARTIFACTS_DIR / filename
        if not path.exists():
            raise SystemExit(f"missing artifact {path} — refusing a partial load")
        art = json.loads(path.read_text(encoding="utf-8-sig"))
        identity = art.get("identity", {})
        found = art["documents"]
        if len(found) != EXPECTED_COUNTS[filename]:
            raise SystemExit(
                f"G-P3 FAIL: {filename} has {len(found)} documents, "
                f"expected {EXPECTED_COUNTS[filename]}"
            )
        n_collapsed = 0
        for doc_key, doc in found.items():
            # THE PRE-REGISTERED EXCLUSION RULE, enforced here rather than by hand.
            # A document the snap reports as schema_collapsed has fewer than MIN_MOVES=3
            # surviving evidenced moves. That is a null result, not a document: the evidence
            # could not support three distinct evidenced moves and no retry budget changes
            # it. Loading one would put a 2-move playbook in front of a CSM as if it were
            # finished. Skipped, counted, and reported.
            if doc.get("snap_log", {}).get("schema_collapsed"):
                n_collapsed += 1
                print(f"  [excluded] {doc_key} — schema_collapsed "
                      f"({len(doc['playbook'].get('key_moves') or [])} moves, floor is 3)")
                continue
            arm = doc["arm"]
            if arm not in arm_status:
                raise SystemExit(
                    f"unmapped arm {arm!r} in {filename} ({doc_key}) — refusing to guess a "
                    f"status; add it to ARTIFACT_PLAN deliberately"
                )
            body = doc["playbook"]
            extra = set(body) - BODY_KEYS
            missing = BODY_KEYS - set(body)
            if extra or missing:
                raise SystemExit(
                    f"body shape mismatch in {filename} ({doc_key}): "
                    f"missing={sorted(missing)} unexpected={sorted(extra)}"
                )
            docs.append({
                "scenario_key": doc["scenario"],
                "arm": arm,
                "status": arm_status[arm],
                "source_artifact": filename,
                "donor_scenario_key": doc.get("donor"),
                "n_evidence": doc["n_evidence"],
                "playbook": body,
                "snap_log": doc.get("snap_log"),
                "identity": identity,
            })
    if len(docs) != EXPECTED_TOTAL:
        raise SystemExit(f"G-P3 FAIL: built {len(docs)} documents, expected {EXPECTED_TOTAL}")
    return docs


def check_move_ids(docs: list[dict]) -> None:
    """G-P5, run BEFORE any write: move_id is dense, 1-based, M1..Mn, per document."""
    from shared.storage import assign_move_ids

    for d in docs:
        moves = d["playbook"]["key_moves"]
        # Snapshot BEFORE the call. Testing `"move_id" in m` afterwards cannot tell loader
        # mutation apart from an artifact that legitimately carries model-supplied ids, and
        # would abort a future load pointing the operator at the wrong file. A model-supplied
        # id is meant to be silently overwritten, not to be an error.
        before = [dict(m) for m in moves]
        ids = [m["move_id"] for m in assign_move_ids(moves)]
        if ids != [f"M{i}" for i in range(1, len(moves) + 1)]:
            raise SystemExit(
                f"G-P5 FAIL: {d['scenario_key']}/{d['arm']} produced move ids {ids}"
            )
        if moves != before:
            raise SystemExit(
                f"G-P5 FAIL: {d['scenario_key']}/{d['arm']} — assign_move_ids MUTATED the "
                f"caller's moves; the artifact object must be left untouched"
            )


def resolve_scenarios(conn, docs: list[dict]) -> dict[str, int]:
    """G-P1: map every scenario_key to a LIVE scenarios.scenario_id, or refuse.

    Reads the ids from Postgres rather than trusting the artifact, because the artifact's
    scenario_id (where it has one) is a synthetic row index — the trap recorded in GOTCHAS
    that attaches rows to whichever scenario happens to hold that serial.
    """
    keys = sorted({d["scenario_key"] for d in docs} | {
        d["donor_scenario_key"] for d in docs if d.get("donor_scenario_key")
    })
    with conn.cursor() as cur:
        cur.execute(
            "SELECT scenario_key, scenario_id FROM scenarios WHERE scenario_key = ANY(%s)",
            (keys,),
        )
        live = dict(cur.fetchall())
    missing = [k for k in keys if k not in live]
    if missing:
        raise SystemExit(
            "G-P1 FAIL: these scenario_keys do not exist in the live taxonomy, so the NOT "
            "NULL FK cannot be satisfied. NOTHING WAS WRITTEN.\n  " + "\n  ".join(missing)
        )
    print(f"[G-P1] PASS — all {len(keys)} scenario/donor keys resolve to live scenario_ids")
    return live


def verify(conn, docs: list[dict], live_ids: dict[str, int]) -> None:
    """Re-verify every frozen gate by reading back from Postgres."""
    from shared.storage import get_playbooks, strip_move_ids

    rows = get_playbooks(conn)
    by_key = {(r["scenario_key"], r["arm"], r["source_artifact"]): r for r in rows}

    # G-P3 — exact counts, overall and per artifact.
    if len(rows) != EXPECTED_TOTAL:
        raise SystemExit(f"G-P3 FAIL: {len(rows)} rows in playbooks, expected {EXPECTED_TOTAL}")
    per_artifact: dict[str, int] = {}
    for r in rows:
        per_artifact[r["source_artifact"]] = per_artifact.get(r["source_artifact"], 0) + 1
    if per_artifact != EXPECTED_LOADED:
        raise SystemExit(f"G-P3 FAIL: per-artifact counts {per_artifact} != {EXPECTED_LOADED}")
    print(f"[G-P3] PASS — {len(rows)} rows, per-artifact {per_artifact}")

    # G-P2 — round-trip fidelity against the artifact, byte-identical after stripping move_id.
    for d in docs:
        k = (d["scenario_key"], d["arm"], d["source_artifact"])
        row = by_key.get(k)
        if row is None:
            raise SystemExit(f"G-P2 FAIL: {k} is not in the database")
        got = dict(row["playbook"])
        got["key_moves"] = strip_move_ids(got["key_moves"])
        want = d["playbook"]
        if json.dumps(got, sort_keys=True) != json.dumps(want, sort_keys=True):
            raise SystemExit(
                f"G-P2 FAIL: {k} does not round-trip.\n"
                f"  db  : {json.dumps(got, sort_keys=True)[:400]}\n"
                f"  file: {json.dumps(want, sort_keys=True)[:400]}"
            )
        # The body round-tripping is not enough. scenario_id is the field this whole design
        # turns on, and the artifact-vs-database trap recorded in GOTCHAS is precisely a row
        # attaching to whichever scenario happens to hold a given serial. Read it back.
        if row["scenario_id"] != live_ids[d["scenario_key"]]:
            raise SystemExit(
                f"G-P2 FAIL: {k} stored scenario_id={row['scenario_id']} but "
                f"{d['scenario_key']} is scenario_id={live_ids[d['scenario_key']]}"
            )
        for field in ("status", "arm", "n_evidence", "donor_scenario_key"):
            if row[field] != d.get(field):
                raise SystemExit(
                    f"G-P2 FAIL: {k} stored {field}={row[field]!r}, expected {d.get(field)!r}"
                )
    print(f"[G-P2] PASS — all {len(docs)} documents round-trip byte-identically, "
          f"with scenario_id/status/arm/n_evidence/donor verified against the load plan")

    # G-P5 — move ids as stored.
    for r in rows:
        moves = r["playbook"]["key_moves"]
        ids = [m.get("move_id") for m in moves]
        if ids != [f"M{i}" for i in range(1, len(moves) + 1)]:
            raise SystemExit(f"G-P5 FAIL: stored move ids {ids} for {r['scenario_key']}")
    print("[G-P5] PASS — every stored move_id is its array position")

    # G-P4 — one live per scenario, and the DATABASE is what enforces it.
    # The status histogram is ASSERTED, not merely printed: "len(live) == len(set(live))" is
    # trivially true at zero live rows, so without this a run that landed nothing as live
    # would print PASS and go on to report success.
    statuses: dict[str, int] = {}
    for r in rows:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    if statuses != EXPECTED_STATUSES:
        raise SystemExit(f"G-P4 FAIL: status histogram {statuses} != {EXPECTED_STATUSES}")
    live = [r for r in rows if r["status"] == "live"]
    live_keys = {r["scenario_key"] for r in live}
    if len(live) != len(live_keys):
        raise SystemExit(f"G-P4 FAIL: {len(live)} live rows over {len(live_keys)} scenarios")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_indexes WHERE schemaname = 'public' "
            "AND indexname = 'idx_playbooks_one_live'"
        )
        if cur.fetchone() is None:
            raise SystemExit(
                "G-P4 FAIL: idx_playbooks_one_live does not exist, so 'one live playbook per "
                "scenario' is an application convention rather than a constraint"
            )
    print(f"[G-P4] PASS — {len(live)} live playbooks over {len(live_keys)} scenarios, "
          f"status histogram {statuses}, enforced by idx_playbooks_one_live")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true",
                   help="actually write. Without it this is a dry run plus G-P1/G-P3/G-P5.")
    p.add_argument("--hostaddr", default="18.138.49.39",
                   help="Neon DNS workaround; host stays in the URL for SNI/SCRAM")
    p.add_argument("--skip-init", action="store_true",
                   help="do not run db/init_db.py first (assume `playbooks` already exists)")
    args = p.parse_args()

    docs = build_documents()
    print(f"[artifacts] {len(docs)} documents from {len(ARTIFACT_PLAN)} artifacts")
    check_move_ids(docs)
    print("[G-P5] PASS (pre-write) — positional move ids for every document")

    conn = connect(args.hostaddr)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.playbooks')")
            exists = cur.fetchone()[0] is not None
        if not exists:
            if args.skip_init and args.apply:
                raise SystemExit(
                    "`playbooks` does not exist and --skip-init was given — nothing would "
                    "land. Drop --skip-init, or create the table first."
                )
            if not args.apply:
                print("[schema] `playbooks` does not exist yet; --apply creates it from the "
                      "marked block in db/schema.sql")
            else:
                print("[schema] creating `playbooks` from db/schema.sql (marked block only)")
                with conn.cursor() as cur:
                    # A short lock_timeout so this can never sit behind, or in front of, a
                    # long concurrent run. The FK to `scenarios` needs a lock on that table;
                    # failing fast is strictly better than queueing an exclusive request that
                    # then blocks every reader behind it.
                    cur.execute("SET lock_timeout = '5s'")
                    cur.execute(playbooks_ddl())
                with conn.cursor() as cur:
                    cur.execute("SELECT to_regclass('public.playbooks')")
                    if cur.fetchone()[0] is None:
                        raise SystemExit("`playbooks` still does not exist after the DDL ran")

        live_ids = resolve_scenarios(conn, docs)

        plan: dict[str, int] = {}
        for d in docs:
            plan[d["status"]] = plan.get(d["status"], 0) + 1
        print(f"\nPLAN  {len(docs)} documents -> playbooks")
        # Iterate what is actually PRESENT, not a hardcoded status list. The list used to be
        # ("live", "placebo", "trial"), so when the 2026-08-24 promotion introduced
        # 'superseded' the summary printed 60 counted rows under a "65 documents" header —
        # five documents invisible in the plan a human approves. The assert below is the real
        # fix: any status the display cannot account for now fails loudly.
        for status, n in sorted(plan.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {n:3d}  status={status}")
        shown = sum(plan.values())
        if shown != len(docs):
            raise SystemExit(
                f"PLAN DISPLAY BUG: summarised {shown} documents but there are {len(docs)}")

        demoted = [d for d in docs if d["status"] == "superseded"]
        if demoted:
            print(f"\n  DEMOTING {len(demoted)} incumbent(s) to 'superseded' — retained for "
                  f"traceability, invisible to production reads:")
            for d in sorted(demoted, key=lambda x: x["scenario_key"]):
                print(f"       superseded  {d['scenario_key']}  ({d['source_artifact']})")

        for d in sorted(docs, key=lambda x: (x["status"] != "live", x["scenario_key"])):
            if d["status"] == "live":
                print(f"       LIVE  {d['scenario_key']}  "
                      f"({len(d['playbook']['key_moves'])} moves, n_evidence={d['n_evidence']}, "
                      f"{d['source_artifact']})")

        if not args.apply:
            print("\nDRY RUN — nothing written. Re-run with --apply.")
            return

        from shared.storage import upsert_playbook

        # Purge rows loaded from a PRE-SNAP artifact. `source_artifact` is part of the
        # uniqueness key, so switching the plan to the snapped files would otherwise leave the
        # unsnapped rows sitting alongside the correct ones as stale duplicates of the same
        # scenario+arm -- 22 documents that G-P3 would then count as extra rather than
        # replace. Deleting by source_artifact is exact: it removes only what this loader put
        # there under a name now known to be wrong.
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM playbooks WHERE source_artifact = ANY(%s)",
                (sorted(SUPERSEDED_BY_SNAP),),
            )
            if cur.rowcount:
                print(f"[purge] removed {cur.rowcount} row(s) loaded from PRE-SNAP artifacts "
                      f"— they carried unsnapped quotes")

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM playbooks")
            before = cur.fetchone()[0]

        written = 0
        for d in docs:
            row = dict(d)
            row["scenario_id"] = live_ids[d["scenario_key"]]
            upsert_playbook(conn, row)
            written += 1
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM playbooks")
            after = cur.fetchone()[0]
        print(f"\n[write] upserted {written} documents; playbooks {before} -> {after}")

        # G-P6 — idempotence, EXERCISED rather than narrated. The previous version only
        # compared this run against whatever happened to be in the table beforehand, so on a
        # first load (before == 0) the gate produced no verdict at all. Replaying the same 32
        # upserts and requiring the row count to be unchanged makes it a real gate of one
        # invocation. It is safe to replay: every write is ON CONFLICT DO UPDATE with
        # identical values.
        for d in docs:
            row = dict(d)
            row["scenario_id"] = live_ids[d["scenario_key"]]
            upsert_playbook(conn, row)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM playbooks")
            replayed = cur.fetchone()[0]
        if replayed != after:
            raise SystemExit(
                f"G-P6 FAIL: replaying the same {len(docs)} documents changed the row count "
                f"{after} -> {replayed}; the upsert is not idempotent"
            )
        print(f"[G-P6] PASS — replaying all {len(docs)} upserts left the count at {replayed}")

        print()
        verify(conn, docs, live_ids)
        print("\nLAYER C IS SHIPPED: the validated playbooks are in Postgres.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
