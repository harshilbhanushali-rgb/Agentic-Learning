#!/usr/bin/env python3
"""One-time ground-truth labeling for the sink-rescue content gate (Status
update 3 in docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md)
and the trigger-quality-gate design's own drop decision -- both need the same
"is this sink-bound pair's response actually coachable" label, so this script
is shared rather than duplicated.

Pulls a stratified sample of currently sink-bound pairs (no single sink
dominates), batches them 5-at-a-time to Gemma for a yes/no coachability
judgment, computes concrete_entity_density for each, and writes
trigger_quality_labels.json. No DB writes. Read-only against Postgres.
"""
from __future__ import annotations
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

from config import load_config
from shared import storage, trigger_quality
from shared.gemma import call_gemma

_SAMPLE_SIZE = 150
_PER_SINK_CAP = 15  # no single sink can contribute more than this many pairs
_BATCH_SIZE = 5
_OUTPUT_PATH = Path(__file__).parent / "trigger_quality_labels.json"

_PROMPT_TEMPLATE = """You are judging whether a customer-success call exchange contains real,
coachable content or is just conversational filler (backchannel, small talk, logistics).

For each numbered pair below, read the CLIENT trigger and the NAREN response. Answer whether
the RESPONSE itself is genuinely coachable content (a real answer worth training a coach's
rubric on), not whether the trigger sounds substantive.

Return ONLY a JSON object of the form {{"judgments": [{{"index": 1, "coachable": true, "reason": "..."}}, ...]}},
one entry per pair, in the same order given. "reason" is one sentence.

{pairs_block}
"""


def _load_sink_bound_pairs(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.pair_id, p.trigger_text, p.response_text, p.scenario_key "
            "FROM kb_pairs p JOIN scenarios s ON s.scenario_key = p.scenario_key "
            "WHERE s.is_coachable = FALSE "
            "ORDER BY p.pair_id"
        )
        rows = cur.fetchall()
    return [
        {"pair_id": r[0], "trigger_text": r[1], "response_text": r[2], "sink_key": r[3]}
        for r in rows
    ]


def _stratified_sample(pairs: list[dict], sample_size: int, per_sink_cap: int) -> list[dict]:
    by_sink: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        by_sink[p["sink_key"]].append(p)

    rng = random.Random(0)
    for group in by_sink.values():
        rng.shuffle(group)

    capped = [p for group in by_sink.values() for p in group[:per_sink_cap]]
    rng.shuffle(capped)
    return capped[:sample_size]


def _judge_batch(batch: list[dict], api_keys) -> list[dict]:
    pairs_block = "\n\n".join(
        f"{i + 1}. TRIGGER: {p['trigger_text']!r}\n   RESPONSE: {p['response_text']!r}"
        for i, p in enumerate(batch)
    )
    result = call_gemma(_PROMPT_TEMPLATE.format(pairs_block=pairs_block), api_keys)
    judgments = result if isinstance(result, list) else result.get("judgments", [])
    by_index = {j["index"]: j for j in judgments}
    out = []
    for i, p in enumerate(batch):
        j = by_index.get(i + 1, {"coachable": False, "reason": "no judgment returned"})
        out.append({**p, "coachable": bool(j["coachable"]), "reason": j["reason"]})
    return out


def main() -> None:
    config = load_config()
    conn = storage.get_connection(config.database_url)
    sink_pairs = _load_sink_bound_pairs(conn)
    conn.close()

    print(f"Loaded {len(sink_pairs)} sink-bound pair(s) across "
          f"{len({p['sink_key'] for p in sink_pairs})} sink(s).")

    sample = _stratified_sample(sink_pairs, _SAMPLE_SIZE, _PER_SINK_CAP)
    print(f"Sampled {len(sample)} pair(s) for labeling.")

    labeled = []
    for start in range(0, len(sample), _BATCH_SIZE):
        batch = sample[start:start + _BATCH_SIZE]
        labeled.extend(_judge_batch(batch, config.gemma_api_keys))
        print(f"  Judged {len(labeled)}/{len(sample)}...")

    for entry in labeled:
        entry["concrete_entity_density"] = trigger_quality.concrete_entity_density(
            entry["response_text"]
        )

    coachable_densities = sorted(e["concrete_entity_density"] for e in labeled if e["coachable"])
    junk_densities = sorted(e["concrete_entity_density"] for e in labeled if not e["coachable"])

    def _pct(values, p):
        if not values:
            return float("nan")
        idx = min(len(values) - 1, int(len(values) * p / 100))
        return values[idx]

    print(f"\nconcrete_entity_density(response), coachable (n={len(coachable_densities)}):")
    print("  " + "  ".join(f"p{p}={_pct(coachable_densities, p):.3f}" for p in (10, 25, 50, 75, 90)))
    print(f"\nconcrete_entity_density(response), NOT coachable (n={len(junk_densities)}):")
    print("  " + "  ".join(f"p{p}={_pct(junk_densities, p):.3f}" for p in (10, 25, 50, 75, 90)))

    _OUTPUT_PATH.write_text(json.dumps(labeled, indent=2), encoding="utf-8")
    print(f"\nWrote {len(labeled)} labeled pair(s) to {_OUTPUT_PATH}.")


if __name__ == "__main__":
    main()
