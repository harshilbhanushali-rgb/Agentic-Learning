#!/usr/bin/env python3
"""Half A of docs/superpowers/specs/2026-08-05-sink-pool-population-diagnostic-design.md.

Characterises the SINK POOL as a population instead of scoring its pairs one at a
time. Eight per-pair signals have now been measured against this problem and all
eight failed (see that spec's Problem section); this changes the unit of decision
to the cluster -- the unit Layer A already adjudicates ~200 of instead of judging
74k clauses individually.

Two things make this more than "cluster it and squint":

  1. A VOLUME-MATCHED CONTROL of pairs currently filed to *coachable* scenarios is
     clustered in the SAME run, and every cluster reports its MIX RATIO. The expert's
     responses are long and topical nearly everywhere, so any random subset of them
     clusters into coherent-looking topics -- coherence alone proves nothing. That is
     exactly the trap response_only fell into at a 95% rescue rate. A cluster that is
     ~all sink-pool members is a distinctive junk family the gate correctly caught; a
     cluster near 50/50 has sink-bound members statistically indistinguishable from
     content already feeding rubrics, which is direct evidence of wrongful exclusion.

  2. The Gemma verdict is THREE-WAY, not the coachable/not-coachable binary every
     prior round used: belongs_to_existing (routing error) / new_coachable_topic
     (taxonomy gap) / genuine_sink (the gate was right). The third option exists
     because v2/layer_a.py builds the taxonomy from CLIENT clauses only, so content
     whose client cues are filler-like has no scenario it could ever be routed to --
     "junk" and "real content with nowhere to go" are indistinguishable to a binary
     judge, and that distinction is the point of this whole pass.

Read-only against Postgres (zero DB writes). Embeddings come from the warm
embed_cache.db. The only cost is the batched Gemma adjudication. Output is persisted
so a later idea against this same data is free -- the discipline the sink-rescue
effort adopted only after having to re-spend Gemma for want of it.

Usage (from Brain/, venv active):
    python diagnose_sink_pool.py
    python diagnose_sink_pool.py --no-gemma          # clusters + stats only, zero cost
    python diagnose_sink_pool.py --load sink_pool_clusters.json
    python diagnose_sink_pool.py --min-cluster-size 12   # exploration only, see below
"""
from __future__ import annotations
import argparse
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np

from config import load_config
from preprocessing import embedder
from shared import cluster_evidence, storage
from shared.gemma import call_gemma
from shared.prompts import PROMPT_SINK_POOL_TRIAGE
from shared.scenario_vectors import build_scenario_vecs
from shared.tuning import load_tuning
from v2.layer_c import _cluster_milestones

_BATCH_SIZE = 5           # clusters per Gemma call -- mirrors label_trigger_quality_sample.py
_GEMMA_CALL_DELAY = 5     # seconds -- matches v2/layer_c.py's free-tier pacing
_SAMPLES_PER_CLUSTER = 4  # verbatim pairs shown to Gemma and printed per cluster
_SAMPLE_CHARS = 300
_DEFAULT_OUTPUT = Path("sink_pool_clusters.json")
_LABELED_SAMPLE = Path("labeled_trigger_quality_sample.json")

# Escape-hatch thresholds, fixed in the spec BEFORE the data existed so they cannot be
# chosen to fit the result. These are stop conditions, not operating points -- nothing
# downstream reads them, so a wrong value costs a judgement call, not a bad rubric.
_NOISE_ESCAPE_HATCH = 0.60      # >60% of the sink pool unclustered => cluster framing is stuck
_MIX_UNINFORMATIVE_BAND = 0.10  # |mix - 0.5| within this => cluster separates nothing


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--load", type=Path, default=None,
                   help="re-report a saved run; zero DB reads, zero Gemma calls")
    p.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    p.add_argument("--no-gemma", action="store_true",
                   help="cluster and report stats only, skipping adjudication")
    p.add_argument("--min-cluster-size", type=int, default=None,
                   help="override the tuning-derived value. EXPLORATION ONLY -- the "
                        "reported run must use the tuning-derived value so the clustering "
                        "geometry matches what Layer C itself would produce")
    p.add_argument("--seed", type=int, default=0,
                   help="control-sample and display-sample seed")
    return p.parse_args()


# --- loading -------------------------------------------------------------------

def _load_pool(conn) -> tuple[list[dict], list[dict], int]:
    """(sink_bound, coachable_control_candidates, total_calls).

    Both populations carry the same fields so they can be clustered as one union
    and told apart afterwards by their `origin`.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT kb.pair_id, kb.trigger_text, kb.response_text, kb.scenario_key,
                   kb.call_id, kb.turn_index, c.filename, s.is_coachable
            FROM kb_pairs kb
            JOIN scenarios s ON s.scenario_key = kb.scenario_key
            JOIN calls c ON c.call_id = kb.call_id
            ORDER BY kb.pair_id
        """)
        rows = cur.fetchall()
        cur.execute("SELECT count(*) FROM calls")
        total_calls = int(cur.fetchone()[0])

    sink_bound, control = [], []
    for r in rows:
        rec = {"pair_id": r[0], "trigger_text": r[1], "response_text": r[2],
               "scenario_key": r[3], "call_id": r[4], "turn_index": r[5],
               "call_filename": r[6]}
        if r[7]:
            rec["origin"] = "control"
            control.append(rec)
        else:
            rec["origin"] = "sink"
            sink_bound.append(rec)
    return sink_bound, control, total_calls


def _volume_matched_control(control: list[dict], n_wanted: int, seed: int) -> list[dict]:
    """Random sample of coachable-filed pairs, matched in count to the sink pool.

    Matched in COUNT rather than clause volume: this half clusters one vector per
    response, so count is the volume that matters here. (Half B, which clusters
    clauses, matches on clause count instead.)
    """
    rng = random.Random(seed)
    if len(control) <= n_wanted:
        return list(control)
    return rng.sample(control, n_wanted)


# --- clustering ----------------------------------------------------------------

def _cluster_union(pool: list[dict], tuning, override: int | None) -> tuple[np.ndarray, int]:
    texts = [p["response_text"] for p in pool]
    print(f"Embedding {len(texts)} response(s) via embed_document (warm cache expected)...")
    vecs = embedder.embed_document_matrix(texts)

    derived = cluster_evidence.milestone_min_cluster_size(
        len(pool), tuning.min_cluster_size_fraction,
        tuning.min_cluster_size_floor, tuning.min_cluster_size_ceiling,
    )
    mcs = override if override is not None else derived
    print(f"min_cluster_size: {mcs}"
          + (f"  (OVERRIDE -- tuning-derived value is {derived}; exploration only)"
             if override is not None else
             f"  (derived from fraction={tuning.min_cluster_size_fraction}, "
             f"floor={tuning.min_cluster_size_floor}, "
             f"ceiling={tuning.min_cluster_size_ceiling} over {len(pool)} items)"))
    print(f"Clustering (UMAP n_components<={tuning.umap_n_components}, cosine -> HDBSCAN)...")
    labels = _cluster_milestones(vecs, mcs, tuning.umap_n_components)
    return vecs, labels, mcs


def _scenario_sides(scenario_map: dict) -> tuple[list, np.ndarray, list, np.ndarray]:
    coachable = {k: v for k, v in scenario_map.items() if v.get("is_coachable", True)}
    sinks = {k: v for k, v in scenario_map.items() if not v.get("is_coachable", True)}

    def _norm(d):
        keys, vecs = build_scenario_vecs(d)
        arr = np.asarray(vecs, dtype=np.float32)
        return keys, arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-10)

    ck, cv = _norm(coachable)
    sk, sv = _norm(sinks)
    return ck, cv, sk, sv


def _build_cluster_records(pool, vecs, labels, scenario_map, total_calls, seed) -> list[dict]:
    ck, cv, sk, sv = _scenario_sides(scenario_map)
    rng = random.Random(seed)
    records = []

    for label in sorted({int(l) for l in labels} - {-1}):
        idx = [i for i, l in enumerate(labels) if int(l) == label]
        members = [pool[i] for i in idx]
        sink_members = [m for m in members if m["origin"] == "sink"]
        ctrl_members = [m for m in members if m["origin"] == "control"]

        centroid = cluster_evidence.milestone_cluster_centroid(vecs[idx])
        centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
        c_sims, s_sims = cv @ centroid, sv @ centroid
        c_best, s_best = int(np.argmax(c_sims)), int(np.argmax(s_sims))

        # Sampled from the SINK members only -- the control exists to compute the mix
        # ratio, not to be adjudicated. Showing control pairs to the judge would ask it
        # about content that is already feeding rubrics.
        sample_src = sink_members or members
        samples = rng.sample(sample_src, min(_SAMPLES_PER_CLUSTER, len(sample_src)))

        records.append({
            "id": f"cluster_{label}",
            "label": label,
            "size": len(members),
            "n_sink": len(sink_members),
            "n_control": len(ctrl_members),
            "mix_ratio": len(sink_members) / len(members),
            "distinct_calls": len({m["call_filename"] for m in members}),
            "call_coverage": len({m["call_filename"] for m in members}) / max(total_calls, 1),
            "nearest_coachable": ck[c_best],
            "nearest_coachable_sim": float(c_sims[c_best]),
            "nearest_coachable_description":
                scenario_map[ck[c_best]].get("business_description", ""),
            "nearest_sink": sk[s_best] if sk else None,
            "nearest_sink_sim": float(s_sims[s_best]) if sk else None,
            "real_minus_sink_margin": float(c_sims[c_best] - s_sims[s_best]) if sk else None,
            "current_sinks_top3": Counter(
                m["scenario_key"] for m in sink_members).most_common(3),
            "member_pair_ids": [m["pair_id"] for m in members],
            "sink_member_pair_ids": [m["pair_id"] for m in sink_members],
            "samples": [
                {"pair_id": s["pair_id"], "trigger_text": s["trigger_text"],
                 "response_text": s["response_text"], "scenario_key": s["scenario_key"]}
                for s in samples
            ],
        })
    return records


# --- adjudication --------------------------------------------------------------

def _adjudicate(records: list[dict], config) -> dict[str, dict]:
    """Batched three-way Gemma verdict per cluster.

    Only clusters containing at least one sink-pool member are adjudicated -- a
    pure-control cluster is already feeding rubrics, so judging it would spend a call
    to answer a question nobody asked.
    """
    targets = [r for r in records if r["n_sink"] > 0]
    skipped = len(records) - len(targets)
    if skipped:
        print(f"  ({skipped} pure-control cluster(s) not adjudicated -- no sink members.)")

    verdicts: dict[str, dict] = {}
    n_calls = math.ceil(len(targets) / _BATCH_SIZE)
    print(f"Adjudicating {len(targets)} cluster(s) in {n_calls} batched Gemma call(s)...")

    for i in range(0, len(targets), _BATCH_SIZE):
        chunk = targets[i:i + _BATCH_SIZE]
        items_block = "\n\n".join(_render_cluster(r) for r in chunk)
        try:
            raw = call_gemma(
                PROMPT_SINK_POOL_TRIAGE.format(items_block=items_block),
                config.gemma_api_keys,
            )
        except Exception as exc:  # noqa: BLE001 -- one bad batch must not lose the run
            print(f"  ! batch {i // _BATCH_SIZE + 1} failed: {exc}")
            time.sleep(_GEMMA_CALL_DELAY)
            continue
        time.sleep(_GEMMA_CALL_DELAY)
        raw_list = raw if isinstance(raw, list) else raw.get("results", [])
        for r in raw_list:
            if isinstance(r, dict) and "id" in r:
                verdicts[r["id"]] = r
        print(f"  batch {i // _BATCH_SIZE + 1}/{n_calls}: "
              f"{len(verdicts)} verdict(s) so far")
    return verdicts


def _render_cluster(r: dict) -> str:
    samples = "\n".join(
        f"    - CLIENT: {s['trigger_text'][:120]!r}\n"
        f"      EXPERT: {s['response_text'][:_SAMPLE_CHARS]!r}"
        for s in r["samples"]
    )
    return (
        f"- id: {r['id']}\n"
        f"  EVIDENCE: {r['n_sink']} discarded pair(s) in this cluster, spanning "
        f"{r['distinct_calls']} distinct call(s) ({r['call_coverage']:.0%} of the corpus)\n"
        f"  NEAREST EXISTING COACHABLE TOPIC: {r['nearest_coachable']} "
        f"(cosine {r['nearest_coachable_sim']:.3f})\n"
        f"    its description: {r['nearest_coachable_description']}\n"
        f"  NEAREST SINK TOPIC: {r['nearest_sink']} "
        f"(cosine {r['nearest_sink_sim']:.3f})\n"
        f"  CURRENTLY FILED UNDER: "
        f"{', '.join(f'{k} x{n}' for k, n in r['current_sinks_top3'])}\n"
        f"  SAMPLE DISCARDED PAIRS:\n{samples}"
    )


# --- cross-check against the existing labeled sample ---------------------------

def _cross_check(records: list[dict], verdicts: dict[str, dict]) -> dict | None:
    """Free validation: the 150-pair Gemma-labeled sample from the sink-rescue effort
    covers this exact population and carries pair_id. If clusters this run judges
    genuine_sink are full of pairs that sample labeled coachable (or vice versa), one
    of the two ground truths is wrong -- and it is much cheaper to learn that here than
    after building on either.
    """
    if not _LABELED_SAMPLE.exists():
        print(f"\n(no {_LABELED_SAMPLE} on disk -- skipping the labeled-sample cross-check)")
        return None

    labeled = {int(r["pair_id"]): bool(r["coachable"])
               for r in json.loads(_LABELED_SAMPLE.read_text(encoding="utf-8-sig"))}
    rows, covered = [], 0
    for r in records:
        hits = [(pid, labeled[pid]) for pid in r["sink_member_pair_ids"] if pid in labeled]
        if not hits:
            continue
        covered += len(hits)
        v = verdicts.get(r["id"], {})
        rows.append({
            "id": r["id"], "verdict": v.get("verdict"), "mix_ratio": r["mix_ratio"],
            "n_labeled": len(hits),
            "labeled_coachable": sum(1 for _, c in hits if c),
        })

    print(f"\n=== Cross-check vs {_LABELED_SAMPLE} ({covered} of {len(labeled)} "
          f"labeled pairs fell inside a cluster) ===")
    if not rows:
        print("  No labeled pair landed in any cluster -- no cross-check possible.")
        return {"covered": 0, "rows": []}

    print(f"  {'cluster':<14}{'verdict':<22}{'mix':>6}{'labeled':>9}{'coachable':>11}")
    for row in sorted(rows, key=lambda x: -x["n_labeled"]):
        print(f"  {row['id']:<14}{str(row['verdict']):<22}{row['mix_ratio']:>6.2f}"
              f"{row['n_labeled']:>9}{row['labeled_coachable']:>11}")

    by_verdict: dict[str, list[int]] = {}
    for row in rows:
        if row["verdict"]:
            b = by_verdict.setdefault(row["verdict"], [0, 0])
            b[0] += row["labeled_coachable"]
            b[1] += row["n_labeled"]
    if by_verdict:
        print("\n  Per-verdict agreement with the per-pair labels:")
        for verdict, (coach, total) in sorted(by_verdict.items()):
            print(f"    {verdict:<22} {coach}/{total} labeled coachable "
                  f"({coach / total:.0%})")
        print("  Expected if both ground truths agree: belongs_to_existing and "
              "new_coachable_topic\n  should run HIGH, genuine_sink should run LOW.")
    return {"covered": covered, "rows": rows}


# --- reporting -----------------------------------------------------------------

def _report(payload: dict) -> None:
    records, verdicts = payload["clusters"], payload.get("verdicts", {})
    n_sink_total = payload["n_sink_total"]
    clustered_sink = sum(r["n_sink"] for r in records)
    noise_sink = n_sink_total - clustered_sink
    noise_rate = noise_sink / max(n_sink_total, 1)

    print("\n" + "=" * 78)
    print("SINK POOL POPULATION REPORT")
    print("=" * 78)
    print(f"  sink-bound pairs                : {n_sink_total}")
    print(f"  volume-matched control pairs     : {payload['n_control_total']}")
    print(f"  clusters found                   : {len(records)}")
    print(f"  sink pairs inside a cluster      : {clustered_sink}")
    print(f"  sink pairs left as HDBSCAN noise : {noise_sink} ({noise_rate:.1%})")

    # --- escape hatch, evaluated before any interpretation of the clusters ---
    uninformative = [r for r in records
                     if abs(r["mix_ratio"] - 0.5) <= _MIX_UNINFORMATIVE_BAND]
    frac_uninformative = len(uninformative) / max(len(records), 1)
    print(f"\n  ESCAPE HATCH (thresholds fixed in the spec before this data existed):")
    print(f"    noise rate {noise_rate:.1%} vs limit {_NOISE_ESCAPE_HATCH:.0%}: "
          f"{'FIRES' if noise_rate > _NOISE_ESCAPE_HATCH else 'ok'}")
    print(f"    clusters with mix ratio in 0.5+/-{_MIX_UNINFORMATIVE_BAND}: "
          f"{len(uninformative)}/{len(records)} ({frac_uninformative:.0%})")
    if noise_rate > _NOISE_ESCAPE_HATCH:
        print("    => Most of the sink pool is un-judgeable even as a population. The "
              "cluster\n       framing is as stuck as the per-pair framing was. Report as a "
              "dead end.")

    mixes = [r["mix_ratio"] for r in records]
    if mixes:
        print("\n  Mix-ratio distribution (1.0 = purely sink-pool, 0.5 = indistinguishable "
              "from\n  content already feeding rubrics):")
        print("    " + "  ".join(f"p{p}={np.percentile(mixes, p):.2f}"
                                 for p in (10, 25, 50, 75, 90)))
        pure = sum(1 for m in mixes if m >= 0.9)
        mixed = sum(1 for m in mixes if 0.35 <= m <= 0.65)
        print(f"    >=0.90 (distinctive junk families) : {pure}/{len(mixes)}")
        print(f"    0.35-0.65 (indistinguishable)      : {mixed}/{len(mixes)}")

    if verdicts:
        tally = Counter(v.get("verdict", "?") for v in verdicts.values())
        print("\n  Three-way verdict tally:")
        for verdict, n in tally.most_common():
            affected = sum(r["n_sink"] for r in records
                           if verdicts.get(r["id"], {}).get("verdict") == verdict)
            print(f"    {verdict:<22} {n:>3} cluster(s), {affected:>5} discarded pair(s)")

    print("\n" + "-" * 78)
    print("PER-CLUSTER DETAIL (largest sink contribution first)")
    print("-" * 78)
    for r in sorted(records, key=lambda x: -x["n_sink"]):
        v = verdicts.get(r["id"], {})
        print(f"\n[{r['id']}] size={r['size']} (sink={r['n_sink']} control={r['n_control']}) "
              f"mix={r['mix_ratio']:.2f} calls={r['distinct_calls']} "
              f"coverage={r['call_coverage']:.0%}")
        print(f"  nearest coachable: {r['nearest_coachable']} "
              f"({r['nearest_coachable_sim']:.3f})")
        print(f"  nearest sink     : {r['nearest_sink']} ({r['nearest_sink_sim']:.3f})"
              if r["nearest_sink"] else "  nearest sink     : n/a")
        if r["real_minus_sink_margin"] is not None:
            direction = ("closer to a REAL scenario" if r["real_minus_sink_margin"] > 0
                         else "closer to a SINK")
            print(f"  real - sink margin: {r['real_minus_sink_margin']:+.3f} ({direction})")
        print(f"  currently filed  : "
              f"{', '.join(f'{k} x{n}' for k, n in r['current_sinks_top3'])}")
        if v:
            print(f"  VERDICT: {v.get('verdict')}"
                  + (f" -> {v.get('target_scenario_key')}"
                     if v.get("target_scenario_key") else "")
                  + (f" -> NEW: {v.get('proposed_label')}"
                     if v.get("proposed_label") else ""))
            print(f"  reason : {v.get('reason', '')}")
        for s in r["samples"]:
            print(f"    - CLIENT: {s['trigger_text'][:110]!r}")
            print(f"      EXPERT: {s['response_text'][:220]!r}")


def main() -> None:
    args = _parse_args()

    if args.load:
        payload = json.loads(args.load.read_text(encoding="utf-8-sig"))
        print(f"Re-reporting {args.load} (zero DB reads, zero Gemma calls).")
        _report(payload)
        _cross_check(payload["clusters"], payload.get("verdicts", {}))
        return

    config = load_config()
    tuning = load_tuning().layer_c
    conn = storage.get_connection(config.database_url)
    scenario_map = {r["scenario_key"]: r for r in storage.get_scenarios(conn)}
    sink_bound, control_all, total_calls = _load_pool(conn)
    conn.close()

    n_coachable = sum(1 for v in scenario_map.values() if v.get("is_coachable", True))
    print(f"Loaded {len(scenario_map)} scenario(s) "
          f"({n_coachable} coachable / {len(scenario_map) - n_coachable} sink), "
          f"{total_calls} call(s).")
    print(f"Sink-bound pairs: {len(sink_bound)}   "
          f"coachable-filed pairs available as control: {len(control_all)}")
    if not sink_bound:
        print("No sink-bound pairs -- nothing to diagnose. Did a pipeline run finish?")
        sys.exit(1)

    control = _volume_matched_control(control_all, len(sink_bound), args.seed)
    pool = sink_bound + control
    print(f"Clustering a union of {len(sink_bound)} sink + {len(control)} control "
          f"= {len(pool)} response(s).")

    vecs, labels, mcs = _cluster_union(pool, tuning, args.min_cluster_size)
    records = _build_cluster_records(pool, vecs, labels, scenario_map, total_calls, args.seed)

    verdicts = {} if args.no_gemma else _adjudicate(records, config)
    if args.no_gemma:
        print("(--no-gemma: skipping adjudication. Mix ratios and margins are still "
              "reported;\n the three-way verdict is not.)")

    payload = {
        "schema": "public",
        "n_sink_total": len(sink_bound),
        "n_control_total": len(control),
        "total_calls": total_calls,
        "min_cluster_size": mcs,
        "min_cluster_size_overridden": args.min_cluster_size is not None,
        "umap_n_components": tuning.umap_n_components,
        "seed": args.seed,
        "clusters": records,
        "verdicts": verdicts,
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nPersisted to {args.output} -- re-report for free with --load {args.output}")

    _report(payload)
    _cross_check(records, verdicts)


if __name__ == "__main__":
    main()
