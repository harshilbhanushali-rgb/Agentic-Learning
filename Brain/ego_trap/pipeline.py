from __future__ import annotations
from pathlib import Path
import psycopg
from config import Config
from ego_trap import (
    csm_registry, gap_output, milestone_scoring, rubric_lookup, scenario_pool, signal_check,
)
from ego_trap.transcript_parser import parse_transcript
from shared import checkpoint, storage
from shared.gemma import GemmaError
from shared.tuning import get_tuning

# Signals scored together in one milestone/soft-skill Gemma call. Request packing,
# not a threshold -- the precedent for this kind of constant is
# v2/layer_c._DESCRIBE_BATCH_SIZE / _TRIAGE_BATCH_SIZE, a module constant rather than
# a tuning.yaml key, because it changes cost and latency but no verdict.
#
# Raised 4 -> 12 on 2026-08-10, after PROMPT_STEP3_MILESTONE_SCORE_BATCH was regrouped
# by exchange so the benchmark and CSM response are stated once per signal instead of
# once per milestone. Requests per day is the binding constraint (flash-lite allows 500),
# and each batch costs one call with layer_d.score_soft_skills off.
#
# MEASURED on real rubrics (mean 6.1 milestones each), old flat shape vs new grouped:
#     batch  4:  24,970 -> 6,170 tokens
#     batch  8:  60,184 -> 13,608
#     batch 12:  76,550 -> 18,803   <- here
#     batch 16: 101,256 -> 24,651
#     batch 24: 133,923 -> 34,956   (output would exceed the 16,384 cap: TRUNCATES)
#
# 12 is chosen over 16 because both need the same 2 batches at the observed ~17.8
# scoreable signals per transcript, and 12 leaves far more output headroom (~8,750 of
# 16,384) against the failure mode below.
#
# THE CEILING IS OUTPUT TRUNCATION, NOT INPUT SIZE. Each verdict carries reason + quote +
# gap_to_ideal, so output grows with the id count; overflow silently drops the tail of the
# JSON array, and every dropped id is stored as a "miss" -- manufacturing exactly the ~0%
# hit rate this pipeline has been trying to explain. score_milestones_batch now reports
# any id shortfall explicitly, so raise this only while that report stays silent.
_GEMMA_BATCH_SIZE = 12


def _load_scenario_map(conn: psycopg.Connection) -> dict[str, dict]:
    """EVERY scenario, sinks included. Do not filter here.

    similarity mode needs the sinks in its vector pool -- a sink winning the match is
    the only mechanism that rejects a client turn. The coachable-only subset is
    derived separately for the Gemma prompt. See ego_trap/scenario_pool.py.
    """
    rows = storage.get_scenarios(conn)
    return {r["scenario_key"]: r for r in rows}


def run_ego_trap_batch(
    recordings_dir: str,
    mapping_path: str,
    config: Config,
    conn: psycopg.Connection,
    run_id: str,
    only_stems: set[str] | None = None,
) -> psycopg.Connection:
    """Score every CSM transcript against Naren's rubrics.

    only_stems restricts the run to those transcript stems (for a calibration subset).
    The caller passes the SAME set it derived run_id from -- run_id is a sha1 of the
    stem list, so a subset selected independently here would silently get a run_id that
    does not describe it, and its checkpoints would collide with the full run's.

    Returns the LIVE connection. storage.reconnect_if_closed returns a new object, so
    every swap below rebinds this function's local -- meaning the caller's original
    handle is dead by the time this returns. Returning the live one is what lets
    ops/run_ego_trap.py close the connection it actually still has open, instead of
    closing a dead handle and leaking one Neon connection per swap.

    RE-RUN WARNING: a genuine re-run requires `python ops/clear_ego_trap_data.py`
    first. gap_events has only a SERIAL primary key, so re-processing a transcript
    APPENDS duplicate rows, and upsert_milestone_performance does
    attempts = attempts + 1 on conflict, so it double-counts every attempt. The
    checkpoint layer name carries the Step 0 mode and a version suffix so an
    accidental clear-less re-run is at least visible as reprocessing rather than
    silently mixing two generations of Step 0 semantics in one dataset.
    """
    tuning = get_tuning().layer_d
    rec_path = Path(recordings_dir)
    txt_files = sorted(rec_path.glob("*.txt"))
    if only_stems is not None:
        txt_files = [p for p in txt_files if p.stem in only_stems]
    if not txt_files:
        raise FileNotFoundError(f"No .txt files found in {recordings_dir}")

    mapping = csm_registry.load_mapping(mapping_path)
    scenario_map = _load_scenario_map(conn)
    coachable_map = scenario_pool.coachable_only(scenario_map)

    # Benchmark references are per-scenario, not per-transcript, so this is hoisted
    # above the loop -- it used to be rebuilt per transcript, re-querying and
    # re-ranking the same scenario once per call that mentioned it. Lazily populated:
    # most scenarios never fire.
    benchmark_cache: dict[str, str] = {}
    seen_csms: dict[str, str] = {}

    print(f"\n[Ego Trap] Found {len(txt_files)} CSM call transcript(s).")
    print(f"[Ego Trap] {scenario_pool.pool_summary(scenario_map)}")
    print(f"[Ego Trap] Step 0 mode: {tuning.signal_detection_mode}")

    for txt_path in txt_files:
        stem = txt_path.stem
        layer = f"ego_trap_{tuning.signal_detection_mode}_v2"
        if checkpoint.is_done(run_id, stem, layer):
            print(f"[Ego Trap] {stem} already done — skipping.")
            continue
        if stem not in mapping:
            print(
                f"[Ego Trap] {stem} has no CSM mapping in {mapping_path} — skipping."
            )
            continue
        csm_id, csm_name = mapping[stem]
        seen_csms[csm_id] = csm_name
        print(f"\n[Ego Trap] Processing {txt_path.name} (CSM: {csm_name})...")

        turns = parse_transcript(str(txt_path), csm_name.strip().lower(), config.joveo_speakers_lower)
        transcript_text = txt_path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")

        signals = signal_check.check_signals(
            turns, transcript_text, scenario_map, coachable_map, config, tuning
        )
        print(f"  Detected {len(signals)} signal(s).")

        # Two distinct failures, counted separately rather than collapsed into one
        # print. UNKNOWN means Gemma invented a key; SINK_MATCHED means it returned a
        # non-coachable one despite the prompt listing only coachable scenarios --
        # which should be zero now, and is worth seeing loudly if it is not.
        unknown = [s for s in signals if s["scenario_key"] not in scenario_map]
        sink_matched = [
            s for s in signals
            if s["scenario_key"] in scenario_map and s["scenario_key"] not in coachable_map
        ]
        for s in unknown:
            print(f"  ! UNKNOWN_SCENARIO '{s['scenario_key']}' (not in taxonomy) — dropping.")
        for s in sink_matched:
            print(f"  ! SINK_MATCHED '{s['scenario_key']}' (non-coachable) — dropping.")
        if sink_matched:
            print(
                f"  ! {len(sink_matched)} signal(s) matched a sink. In gemma mode this "
                f"means the prompt's coachable-only menu was ignored."
            )

        usable = [s for s in signals if s["scenario_key"] in coachable_map]
        responded = [s for s in usable if s["response_outcome"] == "csm"]
        deferred = [s for s in usable if s["response_outcome"] == "other_joveo"]
        not_responded = [s for s in usable if s["response_outcome"] == "none"]

        # Stage 1/5: response check for every signal, done up front.
        print(
            f"  [Stage 1/5] Response check: {len(responded)} responded by CSM, "
            f"{len(deferred)} deferred to teammate, {len(not_responded)} not responded."
        )
        for signal in deferred:
            conn = storage.reconnect_if_closed(conn)
            print(f"  ~ Deferred_To_Teammate: {signal['scenario_key']} @ turn {signal['turn_index']}")
            gap_output.write_deferred_to_teammate(
                conn, csm_id, csm_name, stem, signal["scenario_key"], signal, tuning
            )
        for signal in not_responded:
            conn = storage.reconnect_if_closed(conn)
            print(f"  x Signal_Recognition_Failure: {signal['scenario_key']} @ turn {signal['turn_index']}")
            gap_output.write_signal_recognition_failure(
                conn, csm_id, csm_name, stem, signal["scenario_key"], signal, tuning
            )

        # Stage 2/5: rubric lookup for every responded signal.
        conn = storage.reconnect_if_closed(conn)
        scoreable = []
        version_counts: dict[str, int] = {}
        for signal in responded:
            scenario_key = signal["scenario_key"]
            rubric = rubric_lookup.fetch_rubric(conn, scenario_key)
            if rubric is None:
                # No longer silent: a recognized coachable signal with no rubric is a
                # knowledge-base gap worth recording, not a nothing.
                print(f"  ? Rubric_Coverage_Gap: no rubric for '{scenario_key}' — recording gap.")
                gap_output.write_rubric_coverage_gap(
                    conn, csm_id, csm_name, stem, scenario_key, signal,
                    coachable_map[scenario_key].get("rubric_status"), tuning,
                )
                continue
            version = rubric.get("pipeline_version") or "?"
            version_counts[version] = version_counts.get(version, 0) + 1
            scoreable.append({"signal": signal, "scenario_key": scenario_key, "rubric": rubric})
        version_text = ", ".join(f"{n} {v}" for v, n in sorted(version_counts.items())) or "none"
        print(
            f"  [Stage 2/5] Rubric lookup: {len(scoreable)}/{len(responded)} responded "
            f"signal(s) have a rubric ({version_text})."
        )

        # Stage 3/5: batch-pull CSM response text + benchmark reference for every scoreable signal.
        conn = storage.reconnect_if_closed(conn)
        for item in scoreable:
            scenario_key = item["scenario_key"]
            item["csm_response_text"] = rubric_lookup.extract_csm_response_window(turns, item["signal"])
            if scenario_key not in benchmark_cache:
                benchmark_cache[scenario_key] = rubric_lookup.get_benchmark_reference(
                    conn, scenario_key, coachable_map[scenario_key]
                )
            item["benchmark_response"] = benchmark_cache[scenario_key]
        print(f"  [Stage 3/5] Pulled response text + benchmark reference for {len(scoreable)} signal(s).")

        # Stage 4/5: score with Gemma, batched _GEMMA_BATCH_SIZE signals per call.
        batches = [
            scoreable[i:i + _GEMMA_BATCH_SIZE]
            for i in range(0, len(scoreable), _GEMMA_BATCH_SIZE)
        ]
        print(
            f"  [Stage 4/5] Scoring {len(scoreable)} signal(s) with Gemma in "
            f"{len(batches)} batch(es) of up to {_GEMMA_BATCH_SIZE}..."
        )
        for b_idx, batch in enumerate(batches, start=1):
            try:
                # The applicability pre-check runs FIRST and only when gating is on, so
                # it costs nothing at the shipped default. It answers "did this moment
                # call for the move" for contingent milestones only -- the correction for
                # Layer C emitting contingent moves as mandatory. A batch with no
                # contingent milestone makes no call.
                if tuning.require_validated_milestones:
                    applicable_by_item = milestone_scoring.judge_applicability_batch(
                        [{"rubric": it["rubric"],
                          "client_utterance": it["signal"].get("client_utterance", "")}
                         for it in batch],
                        config,
                    )
                else:
                    applicable_by_item = None
                milestone_batches = milestone_scoring.score_milestones_batch(
                    [{"rubric": it["rubric"], "csm_response_text": it["csm_response_text"],
                      "benchmark_response": it["benchmark_response"]} for it in batch],
                    config,
                    skip_uncoachable=tuning.skip_uncoachable_milestones,
                    require_validated=tuning.require_validated_milestones,
                    applicable_by_item=applicable_by_item,
                )
                if tuning.score_soft_skills:
                    soft_skill_batches = milestone_scoring.score_soft_skills_batch(
                        [{"rubric": it["rubric"], "csm_response_text": it["csm_response_text"],
                          "skill_names": coachable_map[it["scenario_key"]].get("soft_skills", [])} for it in batch],
                        config,
                    )
                else:
                    # Halves the Gemma call count -- see layer_d.score_soft_skills.
                    soft_skill_batches = [[] for _ in batch]
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
                item["rubric"].get("pipeline_version"),
            )
            gap_output.write_gap_record(
                conn, csm_id, csm_name, item["rubric"]["rubric_id"], gap_record, tuning
            )
            written += 1
            print(f"  v Gap record written: {len(gap_record['milestones_missed'])} milestone(s) missed.")
        print(f"  [Stage 5/5] {written}/{len(scoreable)} gap record(s) written.")

        checkpoint.mark_done(run_id, stem, layer)

    # Accumulated gap profile per CSM. Derived here rather than stored, for the same
    # reason the weighted score is not stored -- it changes on every new attempt.
    if seen_csms:
        conn = storage.reconnect_if_closed(conn)
        rubric_cache: dict[int, list[dict]] = {}
        for csm_id, csm_name in sorted(seen_csms.items()):
            rows = storage.get_milestone_gap_profile(conn, csm_id)
            for r in rows:
                if r["rubric_id"] not in rubric_cache:
                    rubric = storage.get_rubric_for_scenario(conn, r["scenario_key"])
                    rubric_cache[r["rubric_id"]] = (rubric or {}).get("milestones") or []
            print(f"\n[Ego Trap] Accumulated gap profile — {csm_name} ({csm_id}):")
            print(gap_output.format_gap_profile(rows, rubric_cache, tuning))

    print("\nEgo Trap batch complete.")
    return conn
