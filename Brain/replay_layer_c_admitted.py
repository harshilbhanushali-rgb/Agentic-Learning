#!/usr/bin/env python3
"""Half B of docs/superpowers/specs/2026-08-05-sink-pool-population-diagnostic-design.md.

Measures what admitting the sink pool does to RUBRICS -- the objective all eight
prior per-pair signal rounds substituted an AUC proxy for. Layer C's Pass 1 is
Gemma-free, so this costs zero LLM calls; the only compute is local embedding and
UMAP.

Three arms per coachable scenario:

  baseline   exactly what production pulls today (WHERE scenario_key = ...)
  treatment  baseline + sink-bound pairs routed in by one of the routing variants
  placebo    baseline + a CLAUSE-COUNT-MATCHED pool drawn at random from OTHER
             coachable scenarios' responses -- i.e. topically wrong content at the
             right volume

The placebo is load-bearing, not decoration. Layer C's UMAP+HDBSCAN is documented
non-reproducible across separate process launches (241 vs ~400 milestones on an
identical corpus), which is why all arms run in ONE process: UMAP is deterministic
on identical input within a process, so the only remaining variance source is that
treatment's input differs from baseline's IN VOLUME. The placebo perturbs volume by
the same amount with content known to be wrong. If treatment's gain is
indistinguishable from placebo's, the gain is a clustering artifact of pool size,
not content -- and no delta here should be believed without that comparison.

Faithfulness: this imports v2/layer_c's own build_clause_pool, _relevance_filter and
_cluster_milestones rather than reimplementing them. dry_run_layer_c_clustering.py
keeps a private copy of the relevance filter, and a Layer B sweep that reimplemented
the sink short-circuit once disagreed with production by 99.7% vs 14%. Reimplementation
is the failure mode to avoid here.

Usage (from Brain/, venv active):
    python replay_layer_c_admitted.py
    python replay_layer_c_admitted.py --variants by_trigger_nonsink
    python replay_layer_c_admitted.py --limit 20        # first N coachable scenarios
    python replay_layer_c_admitted.py --load layer_c_admitted_replay.json
"""
from __future__ import annotations
import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np

from config import load_config
from preprocessing import embedder
from shared import cluster_evidence, storage
from shared.tuning import load_tuning
from v2.layer_c import build_clause_pool, _relevance_filter, _cluster_milestones

_DEFAULT_OUTPUT = Path("layer_c_admitted_replay.json")
_CLUSTER_FILE = Path("sink_pool_clusters.json")
_ALL_VARIANTS = ("by_trigger_nonsink", "by_response", "by_cluster")
_MATCH_MAJORITY = 0.5  # a baseline milestone is "matched" when >half its clauses land together


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--load", type=Path, default=None)
    p.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    p.add_argument("--variants", type=str, default=None,
                   help="comma-separated subset of " + ",".join(_ALL_VARIANTS)
                        + " (by_cluster needs sink_pool_clusters.json)")
    p.add_argument("--limit", type=int, default=None,
                   help="only replay the first N coachable scenarios (smoke test)")
    p.add_argument("--seed", type=int, default=0)
    return p.parse_args()


# --- loading -------------------------------------------------------------------

def _load_everything(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT kb.pair_id, kb.trigger_text, kb.response_text, kb.scenario_key,
                   c.filename, s.is_coachable
            FROM kb_pairs kb
            JOIN scenarios s ON s.scenario_key = kb.scenario_key
            JOIN calls c ON c.call_id = kb.call_id
            ORDER BY kb.pair_id
        """)
        rows = cur.fetchall()
    pairs = [
        {"pair_id": r[0], "trigger_text": r[1], "response_text": r[2],
         "scenario_key": r[3], "call_filename": r[4], "is_sink": not r[5]}
        for r in rows
    ]
    return pairs


# --- routing -------------------------------------------------------------------

def _coachable_vecs(scenario_map):
    from shared.scenario_vectors import build_scenario_vecs
    coachable = {k: v for k, v in scenario_map.items() if v.get("is_coachable", True)}
    keys, vecs = build_scenario_vecs(coachable)
    arr = np.asarray(vecs, dtype=np.float32)
    return keys, arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-10)


def _route(variant, sink_pairs, scenario_map):
    """-> {scenario_key: [pair, ...]} of sink-bound pairs admitted to each scenario."""
    admitted: dict[str, list[dict]] = {}

    if variant == "by_cluster":
        if not _CLUSTER_FILE.exists():
            print(f"  ! {_CLUSTER_FILE} missing -- run diagnose_sink_pool.py first. Skipping.")
            return None
        payload = json.loads(_CLUSTER_FILE.read_text(encoding="utf-8-sig"))
        verdicts = payload.get("verdicts", {})
        by_id = {c["id"]: c for c in payload["clusters"]}
        target_of: dict[int, str] = {}
        for cid, v in verdicts.items():
            if v.get("verdict") != "belongs_to_existing":
                continue
            target = v.get("target_scenario_key")
            if not target or target not in scenario_map:
                continue
            if not scenario_map[target].get("is_coachable", True):
                continue  # never route into a sink; that is the bug being fixed
            for pid in by_id.get(cid, {}).get("sink_member_pair_ids", []):
                target_of[int(pid)] = target
        for p in sink_pairs:
            key = target_of.get(p["pair_id"])
            if key:
                admitted.setdefault(key, []).append(p)
        return admitted

    keys, vecs = _coachable_vecs(scenario_map)
    if variant == "by_trigger_nonsink":
        # Exactly today's assign_scenarios with the sink short-circuit deleted: the
        # trigger's best COACHABLE match. embed_query, because a trigger is a query.
        mat = np.asarray(embedder.embed_query_matrix([p["trigger_text"] for p in sink_pairs]))
    elif variant == "by_response":
        mat = np.asarray(
            embedder.embed_document_matrix([p["response_text"] for p in sink_pairs]))
    else:
        raise ValueError(f"unknown variant {variant}")

    mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-10)
    best = np.argmax(mat @ vecs.T, axis=1)
    for p, j in zip(sink_pairs, best):
        admitted.setdefault(keys[int(j)], []).append(p)
    return admitted


def _placebo_pool(scenario_key, n_clauses_wanted, coachable_pairs_by_key, rng):
    """Clause-count-matched responses drawn from OTHER coachable scenarios.

    Real responses from real calls, so the distinct-call support gate behaves
    normally -- the only thing deliberately wrong about them is the topic.
    """
    donors = [p for k, ps in coachable_pairs_by_key.items() if k != scenario_key for p in ps]
    if not donors or n_clauses_wanted <= 0:
        return []
    rng.shuffle(donors)
    picked, total = [], 0
    for p in donors:
        picked.append(p)
        total += len(build_clause_pool([p])[0])
        if total >= n_clauses_wanted:
            break
    return picked


# --- one arm of one scenario ---------------------------------------------------

def _pass1(info, base_responses, extra_responses, tuning):
    """Layer C Pass 1 over baseline + extra, tracking clause origin throughout.

    Origin is carried by packing it into the `calls` argument _relevance_filter
    already passes through opaquely (it only ever indexes and returns that list), so
    no production function is modified or reimplemented to get it.
    """
    b_cl, b_pos, b_calls = build_clause_pool(base_responses)
    e_cl, e_pos, e_calls = build_clause_pool(extra_responses)

    clauses = b_cl + e_cl
    positions = b_pos + e_pos
    packed = ([(c, "base") for c in b_calls] + [(c, "extra") for c in e_calls])

    result = {"n_clauses_base": len(b_cl), "n_clauses_extra": len(e_cl),
              "n_clauses_total": len(clauses), "milestones": [],
              "outcome": None, "extra_surviving_relevance": 0}

    if len(base_responses) + len(extra_responses) < 2 or len(clauses) < 6:
        result["outcome"] = "fallback_too_few_clauses"
        return result

    vecs = embedder.embed_document_matrix(clauses)
    scenario_calls = len({c for c, _ in packed})

    clauses, vecs, positions, packed, relevance = _relevance_filter(
        clauses, vecs, positions, packed, info, tuning.milestone_relevance_percentile)
    result["n_clauses_after_relevance"] = len(clauses)
    result["extra_surviving_relevance"] = sum(1 for _, o in packed if o == "extra")

    if len(clauses) < 6:
        result["outcome"] = "fallback_too_few_relevant"
        return result

    mcs = cluster_evidence.milestone_min_cluster_size(
        len(clauses), tuning.min_cluster_size_fraction,
        tuning.min_cluster_size_floor, tuning.min_cluster_size_ceiling)
    labels = _cluster_milestones(vecs, mcs, tuning.umap_n_components)

    groups: dict[int, dict] = {}
    for i, label in enumerate(labels):
        if label == -1:
            continue
        g = groups.setdefault(int(label), {"clauses": [], "positions": [], "calls": [],
                                          "origins": []})
        g["clauses"].append(clauses[i])
        g["positions"].append(positions[i])
        g["calls"].append(packed[i][0])
        g["origins"].append(packed[i][1])

    if not groups:
        result["outcome"] = "fallback_no_clusters"
        return result

    required = cluster_evidence.required_milestone_support(
        scenario_calls, tuning.min_milestone_call_fraction, tuning.min_milestone_calls_floor)

    surviving = []
    for label, g in groups.items():
        support = len(set(g["calls"]))
        if support < required:
            continue
        n_extra = sum(1 for o in g["origins"] if o == "extra")
        surviving.append({
            "cluster_id": label,
            "clauses": g["clauses"],
            "support_calls": support,
            "support_clauses": len(g["clauses"]),
            "median_position": float(np.median(g["positions"])),
            "n_from_extra": n_extra,
            "extra_fraction": n_extra / len(g["clauses"]),
            "relevance_mean": float(np.mean([relevance[c] for c in g["clauses"]])),
        })

    result["required_support"] = required
    result["scenario_calls"] = scenario_calls
    if not surviving:
        result["outcome"] = "fallback_no_support"
        return result

    result["outcome"] = "clustered"
    result["milestones"] = sorted(surviving, key=lambda m: m["median_position"])
    return result


# --- milestone matching --------------------------------------------------------

def _match_milestones(base_ms, arm_ms, base_scenario_calls=None, arm_scenario_calls=None):
    """Clause-set overlap matching. The arm's pool is a strict superset of baseline's,
    so every baseline clause exists in the arm and overlap is exact -- no similarity
    threshold has to be invented.

    Four outcomes, deliberately distinguished: conflating `split` with `lost` would
    over-report regression, because fragmented evidence still survives. `merged` is
    split out from `matched` because mapping each baseline milestone to its best arm
    cluster INDEPENDENTLY is blind to several baseline milestones landing in the same
    arm cluster -- that is a destructive collapse (N distinct moves fused into one),
    not N clean matches, even though each one individually clears the majority-overlap
    bar (see design doc's "Correction" section, 2026-08-05).

    Support is reported as a FRACTION of each arm's own scenario call count, not a raw
    delta -- an arm's scenario_calls grows when admitted pairs bring new calls, so raw
    support is not comparable across arms.
    """
    arm_sets = [set(m["clauses"]) for m in arm_ms]

    per_base = []  # (bset, overlaps, best, best_frac, total_frac) or None for empty
    claims: dict[int, list[int]] = {}
    for bi, b in enumerate(base_ms):
        bset = set(b["clauses"])
        if not bset:
            per_base.append(None)
            continue
        overlaps = [len(bset & a) for a in arm_sets]
        best = int(np.argmax(overlaps)) if overlaps else -1
        best_frac = (overlaps[best] / len(bset)) if overlaps else 0.0
        total_frac = (sum(overlaps) / len(bset)) if overlaps else 0.0
        per_base.append((bset, overlaps, best, best_frac, total_frac))
        if best_frac > _MATCH_MAJORITY:
            claims.setdefault(best, []).append(bi)

    merged_arm_idx = {idx for idx, bis in claims.items() if len(bis) > 1}

    outcomes = []
    for bi, b in enumerate(base_ms):
        entry = per_base[bi]
        if entry is None:
            continue
        bset, overlaps, best, best_frac, total_frac = entry
        base_frac = (b["support_calls"] / base_scenario_calls) if base_scenario_calls else None

        if best_frac > _MATCH_MAJORITY:
            arm_support = arm_ms[best]["support_calls"]
            arm_frac = (arm_support / arm_scenario_calls) if arm_scenario_calls else None
            outcome_name = "merged" if best in merged_arm_idx else "matched"
            outcomes.append({"outcome": outcome_name, "base_support": b["support_calls"],
                             "arm_support": arm_support,
                             "base_support_frac": base_frac, "arm_support_frac": arm_frac,
                             "n_baseline_in_same_cluster": len(claims[best]),
                             "clauses": b["clauses"][:3]})
        elif total_frac > _MATCH_MAJORITY:
            outcomes.append({"outcome": "split", "base_support": b["support_calls"],
                             "base_support_frac": base_frac,
                             "n_fragments": sum(1 for o in overlaps if o > 0),
                             "clauses": b["clauses"][:3]})
        else:
            outcomes.append({"outcome": "lost", "base_support": b["support_calls"],
                             "base_support_frac": base_frac,
                             "clauses": b["clauses"][:3]})

    claimed_arm_idx = set(claims.keys())
    new_ms = [
        {"support_calls": m["support_calls"], "extra_fraction": m["extra_fraction"],
         "n_from_extra": m["n_from_extra"], "clauses": m["clauses"][:3]}
        for i, m in enumerate(arm_ms) if i not in claimed_arm_idx
    ]
    return outcomes, new_ms


# --- reporting -----------------------------------------------------------------

def _summarise_arm(name, per_scenario):
    tally = Counter()
    gained_from_extra = gained_other = 0
    support_frac_deltas, extra_admitted, extra_surviving = [], 0, 0

    for s in per_scenario.values():
        for o in s["outcomes"]:
            tally[o["outcome"]] += 1
            if (o["outcome"] in ("matched", "merged")
                    and o.get("base_support_frac") is not None
                    and o.get("arm_support_frac") is not None):
                support_frac_deltas.append(o["arm_support_frac"] - o["base_support_frac"])
        for n in s["new_milestones"]:
            if n["extra_fraction"] > 0.5:
                gained_from_extra += 1
            else:
                gained_other += 1
        extra_admitted += s["n_clauses_extra"]
        extra_surviving += s["extra_surviving_relevance"]

    return {
        "arm": name,
        "matched": tally["matched"], "merged": tally["merged"],
        "split": tally["split"], "lost": tally["lost"],
        "gained_majority_admitted": gained_from_extra,
        "gained_other": gained_other,
        "admitted_clauses": extra_admitted,
        "admitted_surviving_relevance": extra_surviving,
        "support_frac_delta_mean": (float(np.mean(support_frac_deltas))
                                    if support_frac_deltas else 0.0),
        "support_thickened": sum(1 for d in support_frac_deltas if d > 0),
        "support_thinned": sum(1 for d in support_frac_deltas if d < 0),
    }


def _report(payload):
    print("\n" + "=" * 78)
    print("LAYER C PASS-1 REPLAY -- RUBRIC CONSEQUENCE OF ADMITTING THE SINK POOL")
    print("=" * 78)
    b = payload["baseline_summary"]
    print(f"  coachable scenarios replayed : {b['n_scenarios']}")
    print(f"  baseline candidate milestones: {b['n_milestones']}")
    print(f"  baseline clustered / fallback: {b['n_clustered']} / {b['n_fallback']}")

    print("\n  --- Relevance-filter pre-check (the cheap early tell) ---")
    print("  If Layer C's own p{} relevance cut already discards the admitted clauses,"
          .format(payload["percentile"]))
    print("  ungating is a no-op and the question moves entirely to taxonomy.")
    for s in payload["arms"]:
        adm, surv = s["admitted_clauses"], s["admitted_surviving_relevance"]
        rate = (surv / adm) if adm else 0.0
        print(f"    {s['arm']:<28} {surv:>6}/{adm:<6} admitted clauses survive ({rate:.1%})")

    print("\n  --- Milestone outcomes vs baseline ---")
    print("  ('merged' = 2+ baseline milestones collapsed into the same arm cluster --")
    print("   a destructive merge, NOT a clean match; support thick/thin is now a")
    print("   fraction-of-scenario-calls delta, not a raw call-count delta)")
    hdr = (f"    {'arm':<28}{'matched':>8}{'merged':>7}{'split':>7}{'lost':>6}"
           f"{'gained':>8}{'thick':>7}{'thin':>6}")
    print(hdr)
    for s in payload["arms"]:
        print(f"    {s['arm']:<28}{s['matched']:>8}{s['merged']:>7}{s['split']:>7}{s['lost']:>6}"
              f"{s['gained_majority_admitted']:>8}{s['support_thickened']:>7}"
              f"{s['support_thinned']:>6}")

    print("\n  --- Treatment vs its own placebo (the control that decides) ---")
    for variant in payload["variants"]:
        t = next((a for a in payload["arms"] if a["arm"] == variant), None)
        p = next((a for a in payload["arms"] if a["arm"] == f"placebo:{variant}"), None)
        if not t or not p:
            continue
        print(f"    {variant}:")
        print(f"      gained (majority admitted) : treatment {t['gained_majority_admitted']:>4}"
              f"   placebo {p['gained_majority_admitted']:>4}")
        print(f"      lost                       : treatment {t['lost']:>4}"
              f"   placebo {p['lost']:>4}")
        print(f"      merged (destructive collapse): treatment {t['merged']:>4}"
              f"   placebo {p['merged']:>4}")
        verdict = ("INDISTINGUISHABLE FROM PLACEBO -- gain is a pool-size artifact"
                   if t["gained_majority_admitted"] <= p["gained_majority_admitted"]
                   else "beats placebo")
        bar = ("ADOPTION BAR FAILS -- baseline milestones lost"
               if t["lost"] > 0 else "adoption bar: no baseline milestone lost")
        merge_note = (f" (note: {t['merged']} additional baseline milestone(s) were "
                      f"MERGED -- not lost, but not clean matches either)"
                      if t["merged"] > 0 else "")
        print(f"      => {verdict}")
        print(f"      => {bar}{merge_note}")

    print("\n" + "-" * 78)
    print("VERBATIM: every LOST baseline milestone (what the adoption bar turns on)")
    print("-" * 78)
    any_lost = False
    for arm_name, per_scenario in payload["detail"].items():
        for key, s in per_scenario.items():
            for o in s["outcomes"]:
                if o["outcome"] != "lost":
                    continue
                any_lost = True
                print(f"\n  [{arm_name}] {key} (baseline support={o['base_support']} calls)")
                for c in o["clauses"]:
                    print(f"      - {c[:160]!r}")
    if not any_lost:
        print("  None. No baseline milestone was lost in any arm.")

    print("\n" + "-" * 78)
    print("VERBATIM: every MERGED baseline milestone (N baseline milestones collapsed")
    print("into the SAME arm cluster -- a destructive merge the old code scored as")
    print("N clean matches)")
    print("-" * 78)
    any_merged = False
    for arm_name, per_scenario in payload["detail"].items():
        for key, s in per_scenario.items():
            for o in s["outcomes"]:
                if o["outcome"] != "merged":
                    continue
                any_merged = True
                bf = o.get("base_support_frac")
                af = o.get("arm_support_frac")
                frac_str = (f"{bf:.0%} -> {af:.0%} of scenario calls"
                           if bf is not None and af is not None else "n/a")
                print(f"\n  [{arm_name}] {key} ({o['n_baseline_in_same_cluster']} baseline "
                      f"milestones -> 1 arm cluster; support {o['base_support']} -> "
                      f"{o['arm_support']} calls, {frac_str})")
                for c in o["clauses"]:
                    print(f"      ~ {c[:160]!r}")
    if not any_merged:
        print("  None. No arm cluster claimed more than one baseline milestone.")

    print("\n" + "-" * 78)
    print("VERBATIM: sample GAINED milestones built mostly from admitted clauses")
    print("-" * 78)
    shown = 0
    for arm_name, per_scenario in payload["detail"].items():
        if arm_name.startswith("placebo:"):
            continue
        for key, s in per_scenario.items():
            for n in s["new_milestones"]:
                if n["extra_fraction"] <= 0.5 or shown >= 25:
                    continue
                shown += 1
                print(f"\n  [{arm_name}] {key} (support={n['support_calls']} calls, "
                      f"{n['extra_fraction']:.0%} admitted)")
                for c in n["clauses"]:
                    print(f"      + {c[:160]!r}")
    if not shown:
        print("  None. No arm produced a milestone built mostly from admitted clauses.")


def main() -> None:
    args = _parse_args()

    if args.load:
        _report(json.loads(args.load.read_text(encoding="utf-8-sig")))
        return

    config = load_config()
    tuning = load_tuning().layer_c
    conn = storage.get_connection(config.database_url)
    scenario_map = {r["scenario_key"]: r for r in storage.get_scenarios(conn)}
    pairs = _load_everything(conn)
    conn.close()

    coachable_keys = [k for k, v in scenario_map.items() if v.get("is_coachable", True)]
    if args.limit:
        coachable_keys = coachable_keys[:args.limit]
    sink_pairs = [p for p in pairs if p["is_sink"]]
    by_key: dict[str, list[dict]] = {}
    for p in pairs:
        if not p["is_sink"]:
            by_key.setdefault(p["scenario_key"], []).append(p)

    variants = ([v.strip() for v in args.variants.split(",")] if args.variants
                else [v for v in _ALL_VARIANTS
                      if v != "by_cluster" or _CLUSTER_FILE.exists()])
    print(f"{len(scenario_map)} scenario(s), {len(coachable_keys)} coachable replayed, "
          f"{len(sink_pairs)} sink-bound pair(s).")
    print(f"Variants: {', '.join(variants)}")
    print("All arms run in ONE process -- UMAP is only deterministic within a launch.")

    print("\nBaseline arm...")
    baseline: dict[str, dict] = {}
    for key in coachable_keys:
        baseline[key] = _pass1(scenario_map[key], by_key.get(key, []), [], tuning)
    n_clustered = sum(1 for r in baseline.values() if r["outcome"] == "clustered")
    baseline_summary = {
        "n_scenarios": len(coachable_keys),
        "n_milestones": sum(len(r["milestones"]) for r in baseline.values()),
        "n_clustered": n_clustered,
        "n_fallback": len(coachable_keys) - n_clustered,
    }
    print(f"  baseline: {baseline_summary['n_milestones']} candidate milestone(s) "
          f"across {n_clustered} clustered scenario(s)")

    arms, detail = [], {}
    rng = random.Random(args.seed)

    for variant in variants:
        admitted = _route(variant, sink_pairs, scenario_map)
        if admitted is None:
            continue
        n_adm = sum(len(v) for v in admitted.values())
        print(f"\n{variant}: routed {n_adm} sink-bound pair(s) into "
              f"{len(admitted)} scenario(s)...")

        per_scenario, placebo_scenario = {}, {}
        for key in coachable_keys:
            base_resp = by_key.get(key, [])
            extra = admitted.get(key, [])

            arm = _pass1(scenario_map[key], base_resp, extra, tuning)
            base_calls = baseline[key].get("scenario_calls")
            outcomes, new_ms = _match_milestones(baseline[key]["milestones"],
                                                arm["milestones"],
                                                base_calls, arm.get("scenario_calls"))
            per_scenario[key] = {**{k: arm[k] for k in
                                   ("n_clauses_base", "n_clauses_extra", "n_clauses_total",
                                    "outcome", "extra_surviving_relevance")},
                                 "outcomes": outcomes, "new_milestones": new_ms}

            placebo_extra = _placebo_pool(key, arm["n_clauses_extra"], by_key, rng)
            pl = _pass1(scenario_map[key], base_resp, placebo_extra, tuning)
            pl_out, pl_new = _match_milestones(baseline[key]["milestones"], pl["milestones"],
                                              base_calls, pl.get("scenario_calls"))
            placebo_scenario[key] = {**{k: pl[k] for k in
                                       ("n_clauses_base", "n_clauses_extra",
                                        "n_clauses_total", "outcome",
                                        "extra_surviving_relevance")},
                                     "outcomes": pl_out, "new_milestones": pl_new}

        arms.append(_summarise_arm(variant, per_scenario))
        arms.append(_summarise_arm(f"placebo:{variant}", placebo_scenario))
        detail[variant] = per_scenario
        detail[f"placebo:{variant}"] = placebo_scenario

    payload = {
        "schema": "public",
        "percentile": tuning.milestone_relevance_percentile,
        "variants": variants,
        "baseline_summary": baseline_summary,
        "baseline_detail": {k: {"milestones": [
            {"support_calls": m["support_calls"], "clauses": m["clauses"][:3]}
            for m in v["milestones"]], "outcome": v["outcome"]}
            for k, v in baseline.items()},
        "arms": arms,
        "detail": detail,
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nPersisted to {args.output} -- re-report for free with --load {args.output}")
    _report(payload)


if __name__ == "__main__":
    main()
