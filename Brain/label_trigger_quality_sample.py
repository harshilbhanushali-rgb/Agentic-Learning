#!/usr/bin/env python3
"""One-time calibration script: labels a stratified sample of currently
sink-bound kb_pairs as genuinely coachable or not (Gemma judge), then reports
each shared/trigger_quality.py signal's distribution split by that label.

Consumed by both docs/superpowers/specs/2026-08-04-layer-b-trigger-quality-gate-design.md
("Ground-truth labeling") and 2026-08-04-layer-b-sink-rescue-design.md's Status
update 3 ("Calibration") -- content_gate_narrow's tau_density/tau_low/tau_min_words
are derived from this script's output, not guessed.

Read-only against Postgres except for the Gemma calls themselves (no DB writes).
Also reads the source transcript files to reconstruct each sampled pair's turns,
since preceding_turn_is_question needs the turn immediately before the trigger
and kb_pairs only stores call_id + turn_index, not the turn list itself.

Usage (from Brain/, venv active):
    python label_trigger_quality_sample.py [recordings_dir]
    (recordings_dir defaults to "recordings" -- the directory the live corpus
    was built from, per CLAUDE.md's "First full-corpus production run")
"""
from __future__ import annotations
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np

from config import load_config
from preprocessing.transcript_parser import load_roster, parse_transcript
from shared import storage
from shared import trigger_quality as tq
from shared.gemma import call_gemma
from shared.prompts import PROMPT_TRIGGER_QUALITY_JUDGE

_SAMPLE_TARGET = 150
_BATCH_SIZE = 5
_GEMMA_CALL_DELAY = 5  # seconds -- matches v2/layer_c.py's free-tier pacing


def _load_sink_bound_pairs(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kb.pair_id, kb.trigger_text, kb.response_text, kb.scenario_key, "
            "       kb.call_id, kb.turn_index "
            "FROM kb_pairs kb JOIN scenarios s ON s.scenario_key = kb.scenario_key "
            "WHERE s.is_coachable = false "
            "ORDER BY kb.pair_id"
        )
        rows = cur.fetchall()
    return [
        {"pair_id": r[0], "trigger_text": r[1], "response_text": r[2], "scenario_key": r[3],
         "call_id": r[4], "turn_index": r[5]}
        for r in rows
    ]


def _stratified_sample(pairs: list[dict], target: int, seed: int = 0) -> list[dict]:
    """Round-robins across sink scenarios so no single sink dominates the
    sample -- compare_sink_rescue.py's own findings showed one sink absorbing
    nearly half of response_only's rescues, exactly the imbalance this
    guards against."""
    rng = random.Random(seed)
    by_scenario: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        by_scenario[p["scenario_key"]].append(p)
    for group in by_scenario.values():
        rng.shuffle(group)
    order = list(by_scenario.keys())
    rng.shuffle(order)

    sample = []
    while len(sample) < target and any(by_scenario[k] for k in order):
        for k in order:
            if by_scenario[k] and len(sample) < target:
                sample.append(by_scenario[k].pop())
    return sample


def _reconstruct_turns(conn, config, recordings_dir: Path, call_ids: set[int]) -> dict[int, list]:
    """call_id -> parsed turns, re-running the same transcript_parser used at
    extraction time, restricted to the calls the sample actually touches."""
    with conn.cursor() as cur:
        cur.execute("SELECT call_id, filename FROM calls WHERE call_id = ANY(%s)", (list(call_ids),))
        rows = cur.fetchall()
    turns_by_call: dict[int, list] = {}
    missing = 0
    for call_id, filename in rows:
        txt_path = recordings_dir / filename
        if not txt_path.exists():
            missing += 1
            continue
        turns_by_call[call_id] = parse_transcript(
            str(txt_path), config.joveo_speakers_lower, config.naren_name_lower,
            roster=load_roster(str(txt_path)),
        )
    if missing:
        print(f"WARNING: {missing} call(s) in the sample have no transcript file under "
              f"{recordings_dir} -- their preceding_turn_is_question will be reported as None.")
    return turns_by_call


def _label_batch(pairs: list[dict], config) -> None:
    """Mutates each pair in place, adding 'coachable' (bool | None) and 'reason'."""
    for i in range(0, len(pairs), _BATCH_SIZE):
        chunk = pairs[i:i + _BATCH_SIZE]
        items_block = "\n\n".join(
            f"- id: {j}\n"
            f"  TRIGGER: {p['trigger_text']}\n"
            f"  RESPONSE: {p['response_text']}"
            for j, p in enumerate(chunk)
        )
        raw = call_gemma(
            PROMPT_TRIGGER_QUALITY_JUDGE.format(items_block=items_block),
            config.gemma_api_keys,
        )
        time.sleep(_GEMMA_CALL_DELAY)
        raw_list = raw if isinstance(raw, list) else raw.get("results", [])
        by_id = {str(r["id"]): r for r in raw_list if "id" in r}
        for j, p in enumerate(chunk):
            verdict = by_id.get(str(j))
            p["coachable"] = bool(verdict["coachable"]) if verdict else None
            p["reason"] = verdict.get("reason", "") if verdict else "NO GEMMA VERDICT"


def _percentiles(values: list[float]) -> str:
    if not values:
        return "n/a (empty)"
    return "  ".join(f"p{pct}={np.percentile(values, pct):.3f}" for pct in (10, 25, 50, 75, 90))


def _report(sample: list[dict]) -> None:
    judged = [p for p in sample if p["coachable"] is not None]
    print(f"\nLabeled {len(judged)} of {len(sample)} sampled pairs "
          f"({len(sample) - len(judged)} missing a Gemma verdict).")

    coachable = [p for p in judged if p["coachable"]]
    not_coachable = [p for p in judged if not p["coachable"]]
    print(f"coachable: {len(coachable)}  |  not coachable: {len(not_coachable)}")

    print("\nconcrete_content_density(response) split by label -- the field the drop/rescue "
          "decision depends on most:")
    print("  coachable    :", _percentiles([p["density_response"] for p in coachable]))
    print("  not coachable:", _percentiles([p["density_response"] for p in not_coachable]))

    print("\nconcrete_content_density(trigger) split by label:")
    print("  coachable    :", _percentiles([p["density_trigger"] for p in coachable]))
    print("  not coachable:", _percentiles([p["density_trigger"] for p in not_coachable]))

    print("\nresponse content_word_count split by label (for the minimum-length guard):")
    print("  coachable    :", _percentiles([p["response_word_count"] for p in coachable]))
    print("  not coachable:", _percentiles([p["response_word_count"] for p in not_coachable]))

    q_pairs = [p for p in judged if p["preceding_is_question"] is not None]
    q_coachable = [p for p in q_pairs if p["coachable"]]
    q_not = [p for p in q_pairs if not p["coachable"]]
    rate_c = sum(1 for p in q_coachable if p["preceding_is_question"]) / max(len(q_coachable), 1)
    rate_n = sum(1 for p in q_not if p["preceding_is_question"]) / max(len(q_not), 1)
    print(f"\npreceding_turn_is_question=True rate ({len(q_pairs)} pairs with a reconstructed "
          f"transcript): coachable {rate_c:.1%}  |  not coachable {rate_n:.1%}")

    rng = random.Random(0)
    print("\n10 random disagreement-edge pairs (density and label point different directions):")
    edge = [
        p for p in judged
        if (p["coachable"] and p["density_response"] < 0.2)
        or (not p["coachable"] and p["density_response"] >= 0.5)
    ]
    for p in rng.sample(edge, min(10, len(edge))):
        print(f"  [{p['pair_id']}] coachable={p['coachable']} density={p['density_response']:.2f} "
              f"reason={p['reason']!r}")
        print(f"      trigger : {p['trigger_text'][:100]!r}")
        print(f"      response: {p['response_text'][:150]!r}")


def main() -> None:
    recordings_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("recordings")

    config = load_config()
    conn = storage.get_connection(config.database_url)
    sink_pairs = _load_sink_bound_pairs(conn)

    print(f"Loaded {len(sink_pairs)} sink-bound pair(s) across the live corpus.")
    if not sink_pairs:
        print("No sink-bound pairs found -- did a pipeline run finish?")
        conn.close()
        sys.exit(1)

    sample = _stratified_sample(sink_pairs, _SAMPLE_TARGET)
    print(f"Stratified sample: {len(sample)} pair(s) across "
          f"{len({p['scenario_key'] for p in sample})} sink scenario(s).")

    turns_by_call = _reconstruct_turns(conn, config, recordings_dir, {p["call_id"] for p in sample})
    conn.close()

    _label_batch(sample, config)

    for p in sample:
        p["density_trigger"] = tq.concrete_content_density(p["trigger_text"])
        p["density_response"] = tq.concrete_content_density(p["response_text"])
        p["response_word_count"] = tq.content_word_count(p["response_text"])
        turns = turns_by_call.get(p["call_id"])
        p["preceding_is_question"] = (
            tq.preceding_turn_is_question(turns, p["turn_index"]) if turns is not None else None
        )

    _report(sample)


if __name__ == "__main__":
    main()
