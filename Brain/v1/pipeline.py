from __future__ import annotations
from pathlib import Path
import psycopg
from config import Config
from preprocessing.transcript_parser import parse_transcript, load_roster
from shared import storage, checkpoint
from v1 import layer_a, layer_b, layer_c


def run_v1(recordings_dir: str, config: Config, conn: psycopg.Connection, run_id: str) -> None:
    rec_path = Path(recordings_dir)
    txt_files = sorted(rec_path.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"No .txt files found in {recordings_dir}")

    print(f"\n[V1] Found {len(txt_files)} transcript(s).")

    all_turns_by_file: dict[str, tuple] = {}
    for txt_path in txt_files:
        turns = parse_transcript(
            str(txt_path), config.joveo_speakers_lower, config.naren_name_lower,
            roster=load_roster(str(txt_path)),
        )
        call_id = storage.upsert_call(conn, txt_path.name)
        all_turns_by_file[txt_path.stem] = (turns, call_id)
        print(f"  Parsed {txt_path.name}: {len(turns)} turns")

    if not checkpoint.is_done(run_id, "ALL", "layer_a"):
        sections = []
        for stem in all_turns_by_file:
            raw = (rec_path / f"{stem}.txt").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
            sections.append(f"=== CALL: {stem} ===\n{raw}")
        transcripts_text = "\n\n".join(sections)
        conn.close()  # release before the long Gemma call
        scenarios_raw = layer_a.identify_scenarios(transcripts_text, config)
        conn = storage.get_connection(config.database_url)  # fresh connection after Gemma
        scenario_map = layer_a.store_scenarios(scenarios_raw, conn)
        checkpoint.mark_done(run_id, "ALL", "layer_a")
    else:
        print("[Layer A] Already done — loading from DB.")
        scenario_map = _load_scenario_map(conn)

    for stem, (turns, db_call_id) in all_turns_by_file.items():
        if checkpoint.is_done(run_id, stem, "layer_b"):
            print(f"[Layer B] {stem} already done — skipping.")
            continue
        print(f"\n[Layer B] Processing {stem}...")
        pairs = layer_b.extract_pairs(turns, db_call_id)
        print(f"  Extracted {len(pairs)} trigger-response pair(s). Assigning scenarios...")
        trigger_vecs = layer_b.assign_scenarios(pairs, scenario_map, config)
        assigned = sum(1 for p in pairs if p["scenario_key"])
        print(f"  Assigned {assigned}/{len(pairs)} pair(s) to scenarios. Embedding...")
        pair_ids = layer_b.embed_and_store_pairs(pairs, conn, config, trigger_vecs=trigger_vecs)
        checkpoint.mark_done(run_id, stem, "layer_b")
        print(f"  Stored {len(pair_ids)} pair(s).")

    print("\n[Layer C] Generating rubrics...")
    layer_c.run_layer_c(scenario_map, config, conn, run_id)

    print(f"\nV1 pipeline complete. Scenarios: {len(scenario_map)}")


def _load_scenario_map(conn: psycopg.Connection) -> dict[str, dict]:
    rows = storage.get_scenarios(conn)
    return {r["scenario_key"]: r for r in rows}
