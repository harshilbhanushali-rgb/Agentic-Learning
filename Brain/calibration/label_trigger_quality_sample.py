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

The labeled sample (text, label, reason, every computed signal, and the raw
trigger/response embeddings) is persisted to --output as JSON after each real
run -- the original version of this script printed a report and discarded the
per-pair data, so testing a new signal idea meant re-spending the Gemma cost.
Pass --load to re-report against a previously saved file with zero DB and zero
Gemma calls -- this is the intended way to try a new shared/trigger_quality.py
signal against this same ground truth later.

Usage (from Brain/, venv active):
    python calibration/label_trigger_quality_sample.py [recordings_dir] [--output PATH]
    python calibration/label_trigger_quality_sample.py --load PATH
    (recordings_dir defaults to "recordings" -- the directory the live corpus
    was built from, per CLAUDE.md's "First full-corpus production run";
    --output defaults to "labeled_trigger_quality_sample.json")
"""
from __future__ import annotations
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np

# Brain/ is this file's parent -- put it on sys.path so the shared packages
# (config, shared, v1, v2, preprocessing) resolve whether this script is run
# directly (python calibration/x.py) or imported (from calibration import x).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

from config import load_config
from preprocessing import embedder
from preprocessing.transcript_parser import load_roster, parse_transcript
from shared import storage
from shared import trigger_quality as tq
from shared.gemma import call_gemma
from shared.prompts import PROMPT_TRIGGER_QUALITY_JUDGE
from shared.scenario_vectors import build_scenario_vecs

_SAMPLE_TARGET = 150
_BATCH_SIZE = 5
_GEMMA_CALL_DELAY = 5  # seconds -- matches v2/layer_c.py's free-tier pacing
_DEFAULT_OUTPUT = ARTIFACTS_DIR / "labeled_trigger_quality_sample.json"


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


def _save_sample(sample: list[dict], path: Path) -> None:
    path.write_text(json.dumps(sample, indent=2), encoding="utf-8")


def _load_sample(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sink_real_centroids(scenario_map: dict) -> tuple[np.ndarray, np.ndarray]:
    """(sink_centroids, real_centroids) arrays for sink_real_margin -- scenario
    description vectors standing in for centroids, same convention
    compare_sink_rescue.py already uses for the response-similarity read."""
    keys, vecs = build_scenario_vecs(scenario_map)
    S = np.array(vecs)
    is_coachable = np.array([bool(scenario_map[k].get("is_coachable", True)) for k in keys])
    return S[~is_coachable], S[is_coachable]


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

    print("\nsink_real_margin(trigger) split by label -- max(cos(trigger,sink)) - "
          "max(cos(trigger,real)); higher = more filler-like. A relative margin "
          "(mirrors relative_margin's own shape), unlike the absolute floors rounds "
          "1-2 already failed with:")
    print("  coachable    :", _percentiles([p["sink_real_margin"] for p in coachable]))
    print("  not coachable:", _percentiles([p["sink_real_margin"] for p in not_coachable]))

    print("\ntrigger_response_coupling split by label -- cosine(trigger, response) "
          "directly, a signal shape distinct from either text's similarity to a "
          "scenario centroid (which is what density and the response-similarity "
          "floor both measured, and both failed to separate on):")
    print("  coachable    :", _percentiles([p["trigger_response_coupling"] for p in coachable]))
    print("  not coachable:", _percentiles([p["trigger_response_coupling"] for p in not_coachable]))

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
    args = sys.argv[1:]
    if "--load" in args:
        idx = args.index("--load")
        load_path = Path(args[idx + 1])
        sample = _load_sample(load_path)
        print(f"Loaded {len(sample)} previously-labeled pair(s) from {load_path} "
              f"-- no DB or Gemma calls made.")
        _report(sample)
        return

    output_path = _DEFAULT_OUTPUT
    if "--output" in args:
        idx = args.index("--output")
        output_path = Path(args[idx + 1])
        del args[idx:idx + 2]
    recordings_dir = Path(args[0]) if args else Path("recordings")

    config = load_config()
    conn = storage.get_connection(config.database_url)
    scenario_rows = storage.get_scenarios(conn)
    scenario_map = {r["scenario_key"]: r for r in scenario_rows}
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

    trigger_vecs = embedder.embed_query([p["trigger_text"] for p in sample])
    response_vecs = embedder.embed_document([p["response_text"] for p in sample])
    sink_centroids, real_centroids = _sink_real_centroids(scenario_map)

    for p, trigger_vec, response_vec in zip(sample, trigger_vecs, response_vecs):
        p["density_trigger"] = tq.concrete_content_density(p["trigger_text"])
        p["density_response"] = tq.concrete_content_density(p["response_text"])
        p["response_word_count"] = tq.content_word_count(p["response_text"])
        turns = turns_by_call.get(p["call_id"])
        p["preceding_is_question"] = (
            tq.preceding_turn_is_question(turns, p["turn_index"]) if turns is not None else None
        )
        p["trigger_vec"] = trigger_vec
        p["response_vec"] = response_vec
        p["sink_real_margin"] = tq.sink_real_margin(
            np.array(trigger_vec), sink_centroids, real_centroids
        )
        p["trigger_response_coupling"] = tq.trigger_response_coupling(
            np.array(trigger_vec), np.array(response_vec)
        )

    _save_sample(sample, output_path)
    print(f"Saved {len(sample)} labeled pair(s) (incl. raw embeddings) to {output_path}")

    _report(sample)


if __name__ == "__main__":
    main()
