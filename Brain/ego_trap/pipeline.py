from __future__ import annotations
from pathlib import Path
import psycopg
from config import Config
from ego_trap import csm_registry, gap_output, milestone_scoring, rubric_lookup, settings, signal_check
from ego_trap.transcript_parser import parse_transcript
from shared import checkpoint, storage
from shared.gemma import GemmaError


def _load_scenario_map(conn: psycopg.Connection) -> dict[str, dict]:
    rows = storage.get_scenarios(conn)
    return {r["scenario_key"]: r for r in rows}


def run_ego_trap_batch(
    recordings_dir: str,
    mapping_path: str,
    config: Config,
    conn: psycopg.Connection,
    run_id: str,
) -> None:
    rec_path = Path(recordings_dir)
    txt_files = sorted(rec_path.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"No .txt files found in {recordings_dir}")

    mapping = csm_registry.load_mapping(mapping_path)
    scenario_map = _load_scenario_map(conn)

    print(f"\n[Ego Trap] Found {len(txt_files)} CSM call transcript(s).")

    for txt_path in txt_files:
        stem = txt_path.stem
        layer = f"ego_trap_{settings.STEP_0_MODE}"
        if checkpoint.is_done(run_id, stem, layer):
            print(f"[Ego Trap] {stem} already done — skipping.")
            continue
        if stem not in mapping:
            print(
                f"[Ego Trap] {stem} has no CSM mapping in {mapping_path} — skipping."
            )
            continue
        csm_id, csm_name = mapping[stem]
        print(f"\n[Ego Trap] Processing {txt_path.name} (CSM: {csm_name})...")

        turns = parse_transcript(str(txt_path), csm_name.strip().lower(), config.joveo_speakers_lower)
        transcript_text = txt_path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")

        signals = signal_check.check_signals(turns, transcript_text, scenario_map, config)
        print(f"  Detected {len(signals)} signal(s).")

        for s in signals:
            if s["scenario_key"] not in scenario_map:
                print(f"  ! Unknown scenario_key '{s['scenario_key']}' returned — skipping.")
        responded = [s for s in signals if s["scenario_key"] in scenario_map and s["response_outcome"] == "csm"]
        deferred = [s for s in signals if s["scenario_key"] in scenario_map and s["response_outcome"] == "other_joveo"]
        not_responded = [s for s in signals if s["scenario_key"] in scenario_map and s["response_outcome"] == "none"]

        # Stage 1/5: response check for every signal, done up front.
        print(
            f"  [Stage 1/5] Response check: {len(responded)} responded by CSM, "
            f"{len(deferred)} deferred to teammate, {len(not_responded)} not responded."
        )
        for signal in deferred:
            conn = storage.reconnect_if_closed(conn)
            print(f"  ~ Deferred_To_Teammate: {signal['scenario_key']} @ turn {signal['turn_index']}")
            gap_output.write_deferred_to_teammate(
                conn, csm_id, csm_name, stem, signal["scenario_key"], signal
            )
        for signal in not_responded:
            conn = storage.reconnect_if_closed(conn)
            print(f"  x Signal_Recognition_Failure: {signal['scenario_key']} @ turn {signal['turn_index']}")
            gap_output.write_signal_recognition_failure(
                conn, csm_id, csm_name, stem, signal["scenario_key"], signal
            )

        # Stage 2/5: rubric lookup for every responded signal.
        conn = storage.reconnect_if_closed(conn)
        scoreable = []
        for signal in responded:
            scenario_key = signal["scenario_key"]
            rubric = rubric_lookup.fetch_rubric(conn, scenario_key)
            if rubric is None:
                print(f"  ? UNMAPPED_SCENARIO: no rubric for '{scenario_key}' — skipping scoring.")
                continue
            scoreable.append({"signal": signal, "scenario_key": scenario_key, "rubric": rubric})
        print(f"  [Stage 2/5] Rubric lookup: {len(scoreable)}/{len(responded)} responded signal(s) have a rubric.")

        # Stage 3/5: batch-pull CSM response text + benchmark reference for every scoreable signal.
        benchmark_cache: dict[str, str] = {}
        for item in scoreable:
            scenario_key = item["scenario_key"]
            item["csm_response_text"] = rubric_lookup.extract_csm_response_window(turns, item["signal"])
            if scenario_key not in benchmark_cache:
                benchmark_cache[scenario_key] = rubric_lookup.get_benchmark_reference(conn, scenario_key)
            item["benchmark_response"] = benchmark_cache[scenario_key]
        print(f"  [Stage 3/5] Pulled response text + benchmark reference for {len(scoreable)} signal(s).")

        # Stage 4/5: score with Gemma, batched GEMMA_BATCH_SIZE signals per call.
        batch_size = settings.GEMMA_BATCH_SIZE
        batches = [scoreable[i:i + batch_size] for i in range(0, len(scoreable), batch_size)]
        print(f"  [Stage 4/5] Scoring {len(scoreable)} signal(s) with Gemma in {len(batches)} batch(es) of up to {batch_size}...")
        for b_idx, batch in enumerate(batches, start=1):
            try:
                milestone_batches = milestone_scoring.score_milestones_batch(
                    [{"rubric": it["rubric"], "csm_response_text": it["csm_response_text"],
                      "benchmark_response": it["benchmark_response"]} for it in batch],
                    config,
                )
                soft_skill_batches = milestone_scoring.score_soft_skills_batch(
                    [{"rubric": it["rubric"], "csm_response_text": it["csm_response_text"],
                      "skill_names": scenario_map[it["scenario_key"]].get("soft_skills", [])} for it in batch],
                    config,
                )
            except GemmaError as e:
                print(f"  ! Gemma batch {b_idx}/{len(batches)} failed: {e} — skipping {len(batch)} signal(s).")
                continue
            for it, milestone_results, soft_skill_results in zip(batch, milestone_batches, soft_skill_batches):
                it["milestone_results"] = milestone_results
                it["soft_skill_results"] = soft_skill_results
            print(f"  [Stage 4/5] Batch {b_idx}/{len(batches)} scored ({len(batch)} signal(s)).")

        # Stage 5/5: build and write gap records for everything successfully scored.
        conn = storage.reconnect_if_closed(conn)
        written = 0
        for item in scoreable:
            if "milestone_results" not in item:
                continue
            signal = item["signal"]
            gap_record = gap_output.build_gap_record(
                stem, csm_id, item["scenario_key"], item["rubric"]["rubric_id"], signal,
                item["milestone_results"], item["soft_skill_results"],
            )
            gap_output.write_gap_record(conn, csm_id, csm_name, item["rubric"]["rubric_id"], gap_record)
            written += 1
            print(f"  v Gap record written: {len(gap_record['milestones_missed'])} milestone(s) missed.")
        print(f"  [Stage 5/5] {written}/{len(scoreable)} gap record(s) written.")

        checkpoint.mark_done(run_id, stem, layer)

    print("\nEgo Trap batch complete.")
