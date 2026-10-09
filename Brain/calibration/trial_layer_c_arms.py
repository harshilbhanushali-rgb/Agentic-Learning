#!/usr/bin/env python3
"""Four-arm trial of the Layer C rebuild. Writes NOTHING to Postgres.

Run from Brain/ (use ops/run_visible.ps1 so it runs in a window you can watch):
    python calibration/trial_layer_c_arms.py                      # DRY RUN, zero Gemma
    python calibration/trial_layer_c_arms.py --limit 6            # cheap path test
    python calibration/trial_layer_c_arms.py --run                # the real trial
    python calibration/trial_layer_c_arms.py --load artifacts/layer_c_trial.json

Design: docs/superpowers/specs/2026-08-12-layer-c-profile-rebuild-design.md

WHAT IS BEING TESTED

    arm 0  baseline    the rubrics already in the database, unchanged
    arm 3  inputs      situated criteria: the describe step is shown the CLIENT TURNS,
                       its SIBLING moves, the scenario's meaning and its nearest
                       neighbours, and must state a precondition
    arm 14 unit+axes   coverage areas + skills, on the CURRENT blind inputs
    arm 143 full       all three

arm 14 vs arm 143 isolates what the inputs contribute; arm 3 vs baseline isolates them
alone. That attribution is the point -- the last three attempts at this each changed one
thing and measured it on an average that mixed three different problems.

THE GATE, INHERITED RATHER THAN INVENTED

    W(unrelated) < 0.5 x W(matched)

the ceiling spec's own instrument-validity gate. Baseline measured three times:
0.114-0.116 matched vs 0.090-0.095 unrelated, so the null must roughly HALVE to pass.
The gate does not require the matched score to rise -- an arm at 0.114 matched and 0.04
unrelated is a working instrument. Discrimination is the thing.

ALL ARMS SHARE ONE CLUSTERING. Pass 1 runs once per scenario and its clusters are fed to
every generation arm, so the only difference between arms is the describe step. This also
sidesteps Layer C's documented non-reproducibility across process launches (385/398/403/
404 milestones for byte-identical input) -- within one process UMAP is deterministic.

FAITHFULNESS. Clustering composes v2/layer_c's own build_clause_pool, _relevance_filter
and _cluster_milestones rather than reimplementing them, the same precedent
replay_layer_c_admitted.py follows. A Layer B sweep that reimplemented production logic
once disagreed with it by 99.7% vs 14%.

ZERO WRITES, ENFORCED: the connection is opened with
SET SESSION default_transaction_read_only = on, so a stray write fails at Postgres rather
than relying on care.
"""
from __future__ import annotations

import argparse
import json
import random
import sys as _sys
from collections import Counter
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import numpy as np

from calibration import ARTIFACTS_DIR, score_naren_ceiling as snc
from config import load_config
from ego_trap import milestone_scoring
from shared import cluster_evidence, coverage_areas, storage
from shared.gemma import GemmaError
from shared.tuning import get_tuning
from v2.layer_c import _FAST_DESCRIBE_MODEL as _DESCRIBE_MODEL

_DEFAULT_SEED = 20260812
_DEFAULT_PER_SCENARIO = 8
_BATCH_SIZE = 12

# Inherited from the ceiling spec. Not re-derived here on purpose: a gate invented
# alongside the thing it judges is a gate chosen to be passable.
_GATE = 0.5

ARMS = ("arm0_baseline", "arm0r_legacy_regen", "arm0b_no_benchmark", "arm3_inputs",
        "arm14_unit_axes", "arm143_full")

# THE FAIR BASELINE, and the reason arm0_baseline is not one.
#
# arm0_baseline scores the rubrics already in Postgres. Those were written by a DIFFERENT
# Layer C run, over a DIFFERENT clustering of the same corpus -- UMAP is not reproducible
# across process launches (385/398/403/404 milestones for byte-identical input) -- and
# possibly by a different model. Comparing a generated arm against it varies the prompt,
# the clusters and the model at once, so no difference can be attributed to any of them.
#
# arm0r_legacy_regen runs the LEGACY prompt over THIS run's clusters with the same model as
# every other generated arm. Legacy-vs-situated then differs in exactly one thing: the
# prompt. arm0_baseline stays in as a reference point for what production currently has.
_LEGACY_REGEN_ARM = "arm0r_legacy_regen"

# Sampling stratum. NOT a router -- the ceiling spec measured the name shape and found it
# too weak to route on (5 of 15 posture scenarios discriminate fine). It is used here only
# to guarantee BOTH populations appear in a sample, which alphabetical selection does not.
_POSTURE_PREFIX = "client_"

# arm0b differs from arm0 in exactly ONE way: the grader is not shown Naren's reference
# responses. It exists because the benchmark may be turning the judgement into "does this
# RESEMBLE the reference?" rather than "does this SATISFY the criterion?" -- and since the
# benchmark travels with the RUBRIC, that resemblance would inflate the unrelated-rubric
# null, because two competent sales responses resemble each other whatever the topic. If
# that is what is happening, part of the measured 0.090 is an artifact of the benchmark
# rather than evidence the criteria are generic, and the fix is deleting two lines from a
# prompt.
#
# It also removes leak 1 outright instead of managing it: the entire call-level benchmark
# holdout apparatus exists solely because the benchmark can contain the answer.
#
# Needs no generation -- same rubrics as arm0, scored differently.
_NO_BENCHMARK_ARMS = frozenset({"arm0b_no_benchmark"})


# --------------------------------------------------------------------------------------
# Clustering, once, shared by every arm
# --------------------------------------------------------------------------------------

def stratum(scenario_key: str) -> str:
    """Which population a scenario belongs to, for sampling only."""
    return "posture" if scenario_key.startswith(_POSTURE_PREFIX) else "subject"


def stratified_sample(keys: list[str], n: int, seed: int) -> list[str]:
    """A seeded sample that preserves the population's posture/subject mix.

    Proportional rather than 50/50, so the sample looks like the corpus. Returns keys in
    their original order so downstream ordering stays deterministic.

    THE FAILURE THIS REPLACES: taking the first N alphabetically returned eight
    subject-matter scenarios and zero posture ones, i.e. the fix was measured only on the
    half the ceiling run had already found easier.
    """
    if n <= 0 or n >= len(keys):
        return list(keys)
    rng = random.Random(seed)
    by_stratum: dict[str, list[str]] = {}
    for k in keys:
        by_stratum.setdefault(stratum(k), []).append(k)

    chosen: set[str] = set()
    for name, members in sorted(by_stratum.items()):
        share = max(1, round(n * len(members) / len(keys)))
        chosen.update(rng.sample(members, min(share, len(members))))
    # Rounding can over- or under-shoot; correct against the remaining pool.
    pool = [k for k in keys if k not in chosen]
    rng.shuffle(pool)
    while len(chosen) < n and pool:
        chosen.add(pool.pop())
    while len(chosen) > n:
        chosen.discard(sorted(chosen)[-1])
    return [k for k in keys if k in chosen]


def cluster_scenario(responses: list[dict], info: dict, tuning) -> list[dict] | None:
    """Layer C Pass 1 for one scenario, composed from production's own functions.

    Returns milestone-candidate clusters, or None when the scenario would fall back to
    V1. Deliberately does NOT call _pass1_cluster_scenario: that writes rubric_status and
    touches the checkpoint DB, which a read-only trial must not do.
    """
    from v2.layer_c import build_clause_pool, _relevance_filter, _cluster_milestones
    from preprocessing import embedder

    clauses, positions, calls, pairs = build_clause_pool(responses)
    if len(clauses) < 6:
        return None
    vecs = embedder.embed_document_matrix(clauses)
    clauses, vecs, positions, calls, pairs, relevance = _relevance_filter(
        clauses, vecs, positions, calls, pairs, info,
        tuning.milestone_relevance_percentile)
    if len(clauses) < 6:
        return None

    min_size = cluster_evidence.milestone_min_cluster_size(
        len(clauses), tuning.min_cluster_size_fraction,
        tuning.min_cluster_size_floor, tuning.min_cluster_size_ceiling)
    labels = _cluster_milestones(vecs, min_size, tuning.umap_n_components)

    grouped: dict[int, dict] = {}
    for i, label in enumerate(labels):
        if label == -1:
            continue
        g = grouped.setdefault(label, {"clauses": [], "positions": [], "calls": [],
                                       "pairs": []})
        g["clauses"].append(clauses[i])
        g["positions"].append(positions[i])
        g["calls"].append(calls[i])
        g["pairs"].append(pairs[i])
    if not grouped:
        return None

    scenario_calls = len({r["call_filename"] for r in responses})
    floor = cluster_evidence.required_milestone_support(
        scenario_calls, tuning.min_milestone_call_fraction,
        tuning.min_milestone_calls_floor)
    out = []
    for label, g in grouped.items():
        support = len(set(g["calls"]))
        if support < floor:
            continue
        out.append({
            "cluster_id": label,
            "clauses": g["clauses"],
            "support_calls": support,
            "median_position": float(np.median(g["positions"])),
            "position_variance": float(np.var(g["positions"])),
            "relevance_mean": float(np.mean([relevance[c] for c in g["clauses"]])),
            "pair_ids": list(dict.fromkeys(p for p in g["pairs"] if p is not None)),
        })
    out.sort(key=lambda c: c["median_position"])
    return out or None


def describe_items_for(scenario_key: str, info: dict, clusters: list[dict],
                       responses: list[dict], neighbours: list[dict],
                       situated: bool) -> list[dict]:
    """The describe-step items for one scenario.

    `situated` controls only whether the CLIENT TURNS and the scenario's meaning are
    attached. That single switch is what arm 14 vs arm 143 measures, so it must be the
    ONLY difference between them.
    """
    trigger_of = {r.get("pair_id"): (r.get("trigger_text") or "") for r in responses}
    items = []
    for order_idx, cluster in enumerate(clusters):
        items.append({
            "id": f"{scenario_key}::{cluster['cluster_id']}",
            "scenario_key": scenario_key,
            "order": order_idx + 1,
            "total": len(clusters),
            "clauses": cluster["clauses"][:5],
            "cluster": cluster,
            "info": (dict(info, scenario_key=scenario_key) if situated
                     else {"scenario_key": scenario_key}),
            "neighbours": neighbours if situated else [],
            "triggers": ([trigger_of[p] for p in cluster["pair_ids"] if trigger_of.get(p)]
                         if situated else []),
        })
    return items


# --------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------

def score_milestone_arm(items: list[dict], config, batch_size: int, label: str,
                        show_benchmark: bool = True):
    """Milestone scoring, optionally without the benchmark (arm 0b).

    Batching is inlined rather than widening snc._score_arm's signature for a question
    the ceiling harness does not ask.
    """
    records: list[dict] = []
    models: Counter = Counter()
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    shown = "shown" if show_benchmark else "WITHHELD"
    print(f"\n[{label}] scoring {len(items)} item(s) in {len(batches)} batch(es) "
          f"(benchmark {shown})...")
    for b_idx, batch in enumerate(batches, start=1):
        try:
            out = milestone_scoring.score_milestones_batch(
                [{"rubric": it["rubric"], "csm_response_text": it["csm_response_text"],
                  "benchmark_response": it["benchmark_response"]} for it in batch],
                config, show_benchmark=show_benchmark)
        except GemmaError as e:
            print(f"  ! [{label}] batch {b_idx}/{len(batches)} FAILED: {e} - "
                  f"{len(batch)} item(s) unscored (NOT retried, to protect quota)")
            continue
        for it, results in zip(batch, out):
            for r in results:
                models[r.get("scored_by")] += 1
                records.append({**r, "arm": label, "pair_id": it["pair_id"],
                                "scenario_key": it["scenario_key"]})
        print(f"  [{label}] batch {b_idx}/{len(batches)} scored ({len(batch)} item(s))")
    return records, models


def score_coverage_arm(items: list[dict], config, batch_size: int, label: str):
    """Coverage scoring, mirroring _score_arm's batching and failure reporting."""
    records: list[dict] = []
    models: Counter = Counter()
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    print(f"\n[{label}] scoring {len(items)} item(s) in {len(batches)} batch(es)...")
    for b_idx, batch in enumerate(batches, start=1):
        try:
            out = milestone_scoring.score_coverage_batch(
                [{"rubric": it["rubric"], "client_utterance": it.get("client_utterance", ""),
                  "csm_response_text": it["csm_response_text"],
                  "benchmark_response": it["benchmark_response"]} for it in batch],
                config)
        except GemmaError as e:
            print(f"  ! [{label}] batch {b_idx}/{len(batches)} FAILED: {e} — "
                  f"{len(batch)} item(s) unscored (NOT retried, to protect quota)")
            continue
        for it, results in zip(batch, out):
            for r in results:
                models[r.get("scored_by")] += 1
                records.append({**r, "arm": label, "pair_id": it["pair_id"],
                                "scenario_key": it["scenario_key"]})
        print(f"  [{label}] batch {b_idx}/{len(batches)} scored ({len(batch)} item(s))")
    return records, models


def arm_summary(records: list[dict], kind: str) -> dict:
    """Corpus-level score for one arm, in the form its unit allows.

    Coverage arms report BOTH denominators. Reporting only the conditional one would be
    a comparability trap: not_called_for removes observations, so an arm using it
    computes over a different population than one that does not.
    """
    if kind == "coverage":
        s = coverage_areas.score([r["verdict"] for r in records])
        return {"kind": kind, "attempts": s["attempts"],
                "w": s["w_unconditional"], "w_conditional": s["w_conditional"],
                "not_called_for_rate": s["not_called_for_rate"], "counts": s["counts"]}
    t = snc.arm_totals(records)
    return {"kind": kind, "attempts": t["attempts"], "w": t["W"],
            "hits": t["hits"], "partial": t["partial"]}


def _summarise_reps(arm: str, unit: str, reps: list[dict], rubrics: dict) -> dict:
    """Mean across replications, plus the SPREAD, which is what makes a delta readable.

    The spread is reported as half the observed range, so it can be compared directly
    against an arm-to-arm difference: a difference smaller than this is not a result.
    Means are used for the headline rather than a single rep, because picking one rep is
    how a noisy number gets quoted as if it were stable.
    """
    def _mean(path):
        vals = [r[path[0]][path[1]] for r in reps]
        return sum(vals) / len(vals)

    def _spread(path):
        vals = [r[path[0]][path[1]] for r in reps]
        return (max(vals) - min(vals)) / 2 if len(vals) > 1 else 0.0

    matched = dict(reps[0]["matched"], w=_mean(("matched", "w")))
    unrelated = dict(reps[0]["unrelated"], w=_mean(("unrelated", "w")))
    return {
        "unit": unit,
        "n_reps": len(reps),
        "matched": matched,
        "unrelated": unrelated,
        "gate": gate(matched, unrelated),
        "spread": {"matched": _spread(("matched", "w")),
                   "unrelated": _spread(("unrelated", "w"))},
        "reps": [{k: v for k, v in r.items() if k != "records"} for r in reps],
        "rubrics": rubrics,
        "records": reps[0]["records"],
    }


def gate(matched: dict, unrelated: dict) -> dict:
    """W(unrelated) < 0.5 x W(matched). Compared on the UNCONDITIONAL score in both arms."""
    w_m, w_u = matched.get("w", 0.0), unrelated.get("w", 0.0)
    return {"w_matched": w_m, "w_unrelated": w_u,
            "ratio": (w_m / w_u) if w_u else float("inf"),
            "threshold": _GATE * w_m,
            "passes": bool(w_m > 0 and w_u < _GATE * w_m)}


# --------------------------------------------------------------------------------------

def _report(payload: dict) -> None:
    print("\n" + "=" * 96)
    print("LAYER C REBUILD — ARM TRIAL")
    print("=" * 96)
    scen = payload.get("clustered") or []
    if scen:
        mix = Counter(stratum(k) for k in scen)
        print(f"measured on {len(scen)} scenario(s): "
              f"{', '.join(f'{v} {k}' for k, v in sorted(mix.items()))}")
        if mix.get("posture", 0) == 0:
            print("!! NO client-posture scenarios in this sample. The ceiling run found")
            print("!! that population behaves differently (5/15 inverted vs 2/25), so a")
            print("!! result here does NOT generalise to it.")
    print(f"{'arm':<18} {'unit':<10} {'matched W':>10} {'unrelated W':>12} "
          f"{'ratio':>7}  gate")
    print("-" * 96)
    for arm in ARMS:
        a = payload.get("arms", {}).get(arm)
        if not a or not a.get("gate"):
            print(f"{arm:<18} {'-':<10} {'no data':>10}")
            continue
        g = a["gate"]
        verdict = "PASSES" if g["passes"] else f"fails (needs < {g['threshold']:.3f})"
        sp = a.get("spread", {})
        print(f"{arm:<18} {a['unit']:<10} {g['w_matched']:>10.3f} "
              f"{g['w_unrelated']:>12.3f} {g['ratio']:>7.2f}  {verdict}")
        if sp:
            print(f"{'':<18} {'':<10} {'+/-' + format(sp['matched'], '.3f'):>10} "
                  f"{'+/-' + format(sp['unrelated'], '.3f'):>12}   "
                  f"({a.get('n_reps', 1)} rep(s))")

    print("\n" + "-" * 96)
    print("ATTRIBUTION — which lever is doing the work")
    print("-" * 96)
    def _w(a):
        return (payload.get("arms", {}).get(a) or {}).get("gate", {}).get("w_matched")
    # Every comparison is against the REGENERATED legacy arm, never the database
    # rubrics: those came from a different clustering run, so a difference against them
    # cannot be attributed to the prompt.
    pairs = [("inputs alone", _LEGACY_REGEN_ARM, "arm3_inputs"),
             ("unit+axes alone", _LEGACY_REGEN_ARM, "arm14_unit_axes"),
             ("inputs on top of unit+axes", "arm14_unit_axes", "arm143_full"),
             ("db rubrics vs regenerated legacy", "arm0_baseline", _LEGACY_REGEN_ARM)]
    for label, a, b in pairs:
        wa, wb = _w(a), _w(b)
        if wa is None or wb is None:
            print(f"  {label:<30} no data")
        else:
            print(f"  {label:<30} {wa:.3f} -> {wb:.3f}   ({wb - wa:+.3f})")
    print("\n  An arm difference smaller than the replication spread is NOT a result.")
    print("  Measured 2026-08-12: three runs of the same 49 scenarios agreed on a")
    print("  per-scenario verdict only 41-47% of the time.")

    cov = {a: payload["arms"][a] for a in ARMS
           if payload.get("arms", {}).get(a, {}).get("unit") == "coverage"}
    if cov:
        print("\n" + "-" * 96)
        print("COVERAGE ARMS — the fourth verdict")
        print("-" * 96)
        for arm, a in cov.items():
            m = a["matched"]
            print(f"  {arm:<18} not_called_for {m.get('not_called_for_rate', 0):.1%} | "
                  f"W uncond {m['w']:.3f} | W cond {m.get('w_conditional', 0):.3f}")
        print("  A high not_called_for rate is the contingency finding, not a failure:")
        print("  it says the rubric lists moves that most moments do not require.")

    warn = payload.get("generation_warnings") or []
    if warn:
        print("\n" + "-" * 96)
        print(f"GENERATION WARNINGS ({len(warn)}) — read these before any number above")
        print("-" * 96)
        for w in warn[:15]:
            print(f"  {w}")

    print("\n" + "=" * 96)
    print("READ THE CRITERIA BEFORE BELIEVING THE GATE. Showing a move its siblings")
    print("invites the model to INVENT distinctions so they look different, which raises")
    print("discrimination while making the criteria less true -- the one failure mode")
    print("that passes this gate. --samples prints them.")
    print("=" * 96)


def _print_samples(payload: dict, n: int) -> None:
    for arm, a in (payload.get("arms") or {}).items():
        rubrics = a.get("rubrics") or {}
        if not rubrics:
            continue
        print("\n" + "=" * 96)
        print(f"[{arm}] SAMPLE RUBRICS")
        print("=" * 96)
        for key, rubric in list(rubrics.items())[:n]:
            print(f"\n  {key}")
            for unit in (rubric.get("areas") or rubric.get("milestones") or [])[:5]:
                print(f"    - {unit.get('label', '')}: "
                      f"{(unit.get('description') or '')[:150]}")
                if unit.get("precondition"):
                    print(f"      when: {unit['precondition'][:110]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", action="store_true", help="spend Gemma calls; default dry run")
    ap.add_argument("--load")
    ap.add_argument("--limit", type=int, default=0,
                    help="first N scenarios ALPHABETICALLY. Path tests only -- it is not "
                         "a representative sample. Use --sample instead.")
    ap.add_argument("--sample", type=int, default=0,
                    help="seeded STRATIFIED sample of N scenarios, preserving the "
                         "corpus's posture/subject mix. This is the right flag for any "
                         "run whose numbers you intend to believe. 15-20 is the practical "
                         "floor; below that a stratum can end up with one or two members.")
    ap.add_argument("--per-scenario", type=int, default=_DEFAULT_PER_SCENARIO)
    ap.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    ap.add_argument("--batch-size", type=int, default=_BATCH_SIZE)
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--reps", type=int, default=2,
                    help="scoring replications per arm. NON-NEGOTIABLE at 2+ for a real "
                         "trial: measured 2026-08-12, three runs of the same 49 scenarios "
                         "agreed on a per-scenario verdict only 41-47%% of the time, so an "
                         "arm difference smaller than the replication spread is not a "
                         "result. 1 is for path tests only.")
    ap.add_argument("--arms", default="",
                    help="comma-separated subset of " + ",".join(ARMS)
                         + ". Default: all. arm0_baseline and arm0b_no_benchmark need no "
                           "generation, so selecting only those skips it entirely.")
    ap.add_argument("--out", default=str(ARTIFACTS_DIR / "layer_c_trial.json"))
    args = ap.parse_args()

    if args.load:
        payload = json.loads(_Path(args.load).read_text(encoding="utf-8"))
        _report(payload)
        _print_samples(payload, args.samples)
        return

    cfg = load_config()
    tuning = get_tuning()
    selected = [a.strip() for a in args.arms.split(",") if a.strip()] or list(ARMS)
    unknown = [a for a in selected if a not in ARMS]
    if unknown:
        raise SystemExit(f"ERROR: unknown arm(s) {unknown}; choose from {list(ARMS)}")
    print(f"[arms] {', '.join(selected)}")

    conn = snc._connect_read_only(cfg.database_url)
    out_path = _Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial = out_path.with_suffix(".partial.json")
    payload: dict = {"seed": args.seed, "per_scenario": args.per_scenario,
                     "arms": {}, "generation_warnings": []}

    def _flush():
        partial.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT scenario_key FROM rubrics
                           WHERE jsonb_array_length(milestones) > 0
                           ORDER BY scenario_key""")
            keys = [r[0] for r in cur.fetchall()]
        if args.sample and args.limit:
            raise SystemExit("ERROR: pass --sample or --limit, not both.")
        if args.sample:
            keys = stratified_sample(keys, args.sample, args.seed)
        elif args.limit:
            keys = keys[:args.limit]
            print("[!] --limit takes the first N ALPHABETICALLY, which is NOT a "
                  "representative sample: at N=8 it returns only subject-matter "
                  "scenarios and no client-posture ones. Path tests only; use --sample "
                  "for numbers you intend to believe.")
        scen_info = {s["scenario_key"]: s for s in storage.get_scenarios(conn)}
        rubrics_db = {}
        for key in keys:
            r = storage.get_rubric_for_scenario(conn, key)
            if r and (r.get("milestones") or []):
                rubrics_db[key] = r
        keys = [k for k in keys if k in rubrics_db]
        mix = Counter(stratum(k) for k in keys)
        print(f"[scope] {len(keys)} scenario(s)  "
              f"({', '.join(f'{v} {k}' for k, v in sorted(mix.items()))})")
        if len(keys) < 15:
            print("[!] fewer than 15 scenarios: a stratum may hold only one or two "
                  "members, so per-population conclusions from this run are not safe.")

        pools = {k: snc._pools(conn, k) for k in keys}
        responses_by_key = {
            k: storage.get_naren_responses_for_scenario(conn, k) for k in keys}

        texts = []
        for k in keys:
            texts += [r["response_text"] for r in
                      storage.get_responses_for_scenario_multilabel(conn, k)]
            texts.append(snc._scenario_text(scen_info[k]))
        cached, distinct = snc._cache_coverage(texts)
        print(f"[preflight] embed cache {cached}/{distinct} "
              f"({cached / distinct if distinct else 1:.1%})")

        ranked = {k: snc._ranked_benchmark_pool(conn, k, scen_info[k]) for k in keys}
        sim = snc._scenario_sim_matrix(keys, scen_info)
        partner, method = snc.derange(
            keys, sim, tuning.layer_a.merge_cosine_threshold, random.Random(args.seed))
        if partner is None or method != "derangement":
            raise SystemExit(f"ABORT: arm B pairing is {method}; a permutation is "
                             f"required so every rubric receives a null.")

        print("\n[cluster] running Layer C Pass 1 once, shared by every arm "
              "(local compute, zero Gemma)...")
        from v2.layer_c import _nearest_other_scenarios
        neighbours_of = _nearest_other_scenarios(keys, scen_info)
        clusters_by_key, skipped = {}, []
        for i, key in enumerate(keys, start=1):
            got = cluster_scenario(responses_by_key[key], scen_info[key], tuning.layer_c)
            if got:
                clusters_by_key[key] = got
            else:
                skipped.append(key)
            if i % 10 == 0 or i == len(keys):
                print(f"  clustered {i}/{len(keys)}")
        print(f"[cluster] {len(clusters_by_key)} scenario(s) clustered, "
              f"{len(skipped)} would fall back to V1 and are excluded from every arm")
        payload["clustered"] = sorted(clusters_by_key)
        payload["skipped_fallback"] = skipped

        n_units = sum(len(c) for c in clusters_by_key.values())
        gen_arms = [a for a in (_LEGACY_REGEN_ARM, "arm3_inputs", "arm14_unit_axes",
                                "arm143_full") if a in selected]
        gen_calls = len(gen_arms) * len(clusters_by_key)
        # Two scored populations per rep -- matched and unrelated -- each roughly
        # per_scenario items per scenario.
        items_per_pop = len(clusters_by_key) * args.per_scenario
        score_calls = (len(selected) * args.reps * 2
                       * -(-items_per_pop // args.batch_size))
        print(f"\n[plan] {n_units} milestone candidate(s) across "
              f"{len(clusters_by_key)} scenario(s)")
        print(f"[plan] generation ~{gen_calls} Gemma call(s) "
              f"({len(gen_arms)} arm(s) needing it x 1 per scenario"
              f"{': ' + ', '.join(gen_arms) if gen_arms else ' - none selected'})")
        print(f"[plan] scoring ~{score_calls} call(s) "
              f"({len(selected)} arm(s) x {args.reps} replication(s) x matched+unrelated)")
        print(f"[plan] TOTAL ~{gen_calls + score_calls} Gemma call(s)")
        if args.reps < 2:
            print("[plan] ! --reps 1: this is a PATH TEST. Its numbers have no "
                  "replication spread, so no arm comparison from it is a result.")
        print(f"[plan] describe_mode in tuning.yaml stays "
              f"{tuning.layer_c.describe_mode!r}; this harness selects per arm")

        if not args.run:
            print("\n[dry run] no Gemma calls made. Re-run with --run.")
            return

        from v2.layer_c import (_describe_milestones_batch, _describe_situated,
                        describe_coverage_areas)
        needs_generation = [a for a in (_LEGACY_REGEN_ARM, "arm3_inputs",
                                        "arm14_unit_axes", "arm143_full")
                            if a in selected]

        # --- generation ---------------------------------------------------------------
        # Keyed on demand, never from a positional slice of ARMS: adding an arm at any
        # index silently dropped it from this dict and crashed mid-generation, twice.
        generated: dict[str, dict] = {}
        for arm, situated, unit in ((_LEGACY_REGEN_ARM, False, "legacy"),
                                    ("arm3_inputs", True, "milestone"),
                                    ("arm14_unit_axes", False, "coverage"),
                                    ("arm143_full", True, "coverage")):
            if arm not in needs_generation:
                continue
            print(f"\n[generate] {arm} ({unit}, situated={situated})")
            for key, clusters in clusters_by_key.items():
                items = describe_items_for(
                    key, scen_info[key], clusters, responses_by_key[key],
                    neighbours_of.get(key, []), situated)
                try:
                    if unit == "coverage":
                        areas = describe_coverage_areas(
                            items, cfg, model=_DESCRIBE_MODEL).get(key, [])
                        generated.setdefault(arm, {})[key] = {"areas": areas}
                    elif unit == "legacy":
                        desc = _describe_milestones_batch(items, cfg,
                                                          model=_DESCRIBE_MODEL)
                        generated.setdefault(arm, {})[key] = {"milestones": [
                            {"order": i + 1,
                             "label": desc.get(it["id"], {}).get("label", ""),
                             "description": desc.get(it["id"], {}).get("description", ""),
                             "detection_hint": desc.get(it["id"], {}).get("detection_hint", ""),
                             "support_calls": it["cluster"]["support_calls"]}
                            for i, it in enumerate(items)]}
                    else:
                        desc = _describe_situated(items, cfg, model=_DESCRIBE_MODEL)
                        generated.setdefault(arm, {})[key] = {"milestones": [
                            {"order": i + 1,
                             "label": desc.get(it["id"], {}).get("label", ""),
                             "description": desc.get(it["id"], {}).get("description", ""),
                             "detection_hint": desc.get(it["id"], {}).get("detection_hint", ""),
                             "precondition": desc.get(it["id"], {}).get("precondition"),
                             "support_calls": it["cluster"]["support_calls"]}
                            for i, it in enumerate(items)]}
                except GemmaError as e:
                    payload["generation_warnings"].append(f"{arm}/{key}: {e}")
            generated.setdefault(arm, {})
            payload.setdefault("rubrics", {})[arm] = generated[arm]
            _flush()
            print(f"[generate] {arm}: {len(generated[arm])} rubric(s) flushed")

        # --- scoring ------------------------------------------------------------------
        rng = random.Random(args.seed)
        samples = {}
        for key in clusters_by_key:
            primary, secondary, primary_calls = pools[key]
            samples[key] = snc.take_sample(
                snc.a3_eligible(secondary, primary_calls), args.per_scenario, rng)

        def _items(arm_rubrics, key_for_rubric):
            out = []
            for key, rows in samples.items():
                rk = key_for_rubric(key)
                rubric = arm_rubrics.get(rk)
                if not rubric:
                    continue
                for row in rows:
                    bench = snc.pick_benchmark(ranked.get(rk, []), row["call_filename"])
                    out.append({
                        "pair_id": row["pair_id"], "scenario_key": rk,
                        "rubric": rubric, "rubric_id": rk,
                        "client_utterance": row.get("trigger_text") or "",
                        "csm_response_text": row["response_text"],
                        "benchmark_response": "\n\n".join(
                            r["response_text"] for r in bench),
                    })
            return out

        arm_units = {"arm0_baseline": "milestone", "arm0b_no_benchmark": "milestone",
                     _LEGACY_REGEN_ARM: "milestone", "arm3_inputs": "milestone",
                     "arm14_unit_axes": "coverage", "arm143_full": "coverage"}
        arm_rubrics = {"arm0_baseline": rubrics_db,
                       "arm0b_no_benchmark": rubrics_db, **generated}

        for arm in selected:
            unit = arm_units[arm]
            matched = _items(arm_rubrics[arm], lambda k: k)
            unrelated = _items(arm_rubrics[arm], lambda k: partner[k])
            reps = []
            for rep in range(args.reps):
                tag = f"{arm}:rep{rep + 1}"
                if unit == "coverage":
                    m_rec, _ = score_coverage_arm(matched, cfg, args.batch_size,
                                                  f"{tag}:matched")
                    u_rec, _ = score_coverage_arm(unrelated, cfg, args.batch_size,
                                                  f"{tag}:unrelated")
                else:
                    show = arm not in _NO_BENCHMARK_ARMS
                    m_rec, _ = score_milestone_arm(matched, cfg, args.batch_size,
                                                   f"{tag}:matched", show)
                    u_rec, _ = score_milestone_arm(unrelated, cfg, args.batch_size,
                                                   f"{tag}:unrelated", show)
                m, u = arm_summary(m_rec, unit), arm_summary(u_rec, unit)
                reps.append({"matched": m, "unrelated": u, "gate": gate(m, u),
                             "records": {"matched": m_rec, "unrelated": u_rec}})
                # Flush after EVERY replication: a free operation must never be able to
                # destroy an expensive one, and each rep is ~half an arm's spend.
                payload["arms"][arm] = _summarise_reps(arm, unit, reps,
                                                       arm_rubrics[arm])
                _flush()
                print(f"[{tag}] matched W {m['w']:.3f} | unrelated W {u['w']:.3f} "
                      f"- flushed")
            a = payload["arms"][arm]
            print(f"[{arm}] SPREAD across {args.reps} rep(s): "
                  f"matched +/-{a['spread']['matched']:.3f}, "
                  f"unrelated +/-{a['spread']['unrelated']:.3f}")

        out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        partial.unlink(missing_ok=True)
        print(f"\n[artifact] {out_path}")
        _report(payload)
        _print_samples(payload, args.samples)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
