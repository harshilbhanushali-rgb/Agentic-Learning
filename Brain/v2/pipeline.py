from __future__ import annotations
from pathlib import Path
import psycopg
import response_taxonomy_auto_pass
from config import Config
from preprocessing.transcript_parser import parse_transcript, load_roster
from shared import storage, checkpoint
from v2 import layer_a, layer_b, layer_c


def run_v2(recordings_dir: str, config: Config, conn: psycopg.Connection, run_id: str) -> None:
    rec_path = Path(recordings_dir)
    txt_files = sorted(rec_path.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"No .txt files found in {recordings_dir}")

    print(f"\n[V2] Found {len(txt_files)} transcript(s).")

    all_turns = []
    all_turns_by_file: dict[str, tuple] = {}
    for txt_path in txt_files:
        turns = parse_transcript(
            str(txt_path), config.joveo_speakers_lower, config.naren_name_lower,
            roster=load_roster(str(txt_path)),
        )
        call_id = storage.upsert_call(conn, txt_path.name)
        all_turns.extend(turns)
        all_turns_by_file[txt_path.stem] = (turns, call_id)
        print(f"  Parsed {txt_path.name}: {len(turns)} turns")

    if not checkpoint.is_done(run_id, "ALL", "layer_a"):
        scenario_map, conn = layer_a.run_layer_a_v2(all_turns, config, conn)
        checkpoint.mark_done(run_id, "ALL", "layer_a")
    else:
        print("[Layer A] Already done — loading from DB.")
        from v1.pipeline import _load_scenario_map
        scenario_map = _load_scenario_map(conn)

    for stem, (turns, db_call_id) in all_turns_by_file.items():
        if checkpoint.is_done(run_id, stem, "layer_b"):
            print(f"[Layer B] {stem} already done — skipping.")
            continue
        print(f"\n[Layer B] Processing {stem}...")
        pairs = layer_b.extract_pairs(turns, db_call_id)
        print(f"  Extracted {len(pairs)} pair(s). Assigning scenarios...")
        trigger_vecs = layer_b.assign_scenarios(pairs, scenario_map, config)
        assigned = sum(1 for p in pairs if p["scenario_key"])
        print(f"  Assigned {assigned}/{len(pairs)} pair(s) to scenarios. Embedding...")
        pair_ids = layer_b.embed_and_store_pairs(pairs, conn, config, trigger_vecs=trigger_vecs)
        checkpoint.mark_done(run_id, stem, "layer_b")
        print(f"  Stored {len(pair_ids)} pair(s).")

    print("\n[V2 Layer C] Generating rubrics...")
    layer_c.run_layer_c_v2(scenario_map, config, conn, run_id)

    print("\n[Response-taxonomy auto-pass] Checking for homeless topics to graduate...")
    try:
        response_taxonomy_auto_pass.run_auto_pass(config, conn, run_id)
    except Exception as exc:  # noqa: BLE001 -- must never fail the overall pipeline run
        print(f"  ! response_taxonomy_auto_pass failed (logged, not fatal): {exc}")

    _reconcile(conn, len(scenario_map))


def _reconcile(conn: psycopg.Connection, n_scenarios: int) -> None:
    """Account for every scenario, then fail loudly if any is unaccounted for.

    The previous run reported 149 scenarios and 148 rubrics and gave no way to
    learn which one was missing or why: Layer C skipped silently on an empty
    response pool. Requiring a terminal status per scenario makes that class of
    gap impossible to produce without noticing.
    """
    conn = storage.reconnect_if_closed(conn)
    print("\n" + "=" * 62)
    print("RECONCILIATION")
    print("=" * 62)
    print(f"  {'cluster_kind':<14} {'rubric_status':<34} count")
    for kind, status, count in storage.get_rubric_status_report(conn):
        print(f"  {kind:<14} {status:<34} {count}")

    missing = storage.count_scenarios_without_status(conn)
    print(f"\n  scenarios in this run : {n_scenarios}")
    print(f"  without a status      : {missing}")
    if missing:
        raise AssertionError(
            f"{missing} scenario(s) finished with no rubric_status. Every scenario "
            f"must end as rubric_generated, skipped_not_coachable, "
            f"skipped_insufficient_responses or failed -- an unset status means a "
            f"code path returns without recording what it decided."
        )
    print("  All scenarios accounted for.")
