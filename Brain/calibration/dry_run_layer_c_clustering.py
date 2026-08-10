"""Diagnose Layer C milestone clustering: why do 28/85 coachable scenarios hit
100% HDBSCAN noise (zero clusters found) regardless of clause pool size, from
10 clauses up to 680? That range rules out pure data-sparsity as the cause for
the larger ones.

Tests 4 HDBSCAN variants against the REAL clause pools of those 28 scenarios
plus a control sample of already-working (V2-clustered) scenarios, reusing the
exact segment -> embed -> relevance-filter pipeline v2/layer_c.py uses. The
control sample exists to catch regressions: a variant that "fixes" the 28 by
fragmenting already-good clusters into garbage is not a win.

Read-only: no Gemma calls, no DB writes, no pipeline mutation. Connects to
Postgres only to read scenarios and kb_pairs. Embeddings hit embed_cache.db
(already warm from the production run), so this does not re-encode the corpus.

See docs/superpowers/specs/2026-07-28-layer-c-rubric-depth-design.md.

Usage (from Brain/, venv active):
    python dry_run_layer_c_clustering.py                  # full report, all variants
    python dry_run_layer_c_clustering.py --detail 10       # also print clause text
                                                            # for the best variant,
                                                            # for 10 scenarios
    python dry_run_layer_c_clustering.py --controls 10     # control sample size

    # UMAP found real signal but also promoted backchannel to milestone status
    # in the largest scenarios (the relevance filter at percentile=40 wasn't
    # strict enough). Sweep stricter percentiles, UMAP variant only:
    python dry_run_layer_c_clustering.py --sweep-percentile 40,50,60,70,75,80
"""
from __future__ import annotations

import argparse

import numpy as np
from hdbscan import HDBSCAN

from config import load_config
from preprocessing import embedder, segmenter
from shared import cluster_evidence, scenario_vectors, storage
from shared.tuning import load_tuning

_BAR = "=" * 90

_VARIANTS = ["baseline", "leaf", "min_samples_2", "umap"]


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--controls", type=int, default=10,
                    help="how many already-working V2-clustered scenarios to include "
                         "as a regression control (default 10)")
    p.add_argument("--detail", type=int, default=0,
                    help="print clause text of resulting clusters for this many "
                         "scenarios, using whichever variant rescues the most "
                         "no-cluster scenarios (default 0 = off)")
    p.add_argument("--sweep-percentile", default="",
                    help="comma-separated relevance percentiles to test with the "
                         "umap variant only, e.g. 40,50,60,70,75,80. Prints the "
                         "rescue-count table plus clause detail for the two "
                         "scenarios where the default percentile=40 was seen "
                         "promoting backchannel to milestone status "
                         "(implementation_feasibility_requests, "
                         "advertising_retargeting_strategy_discussion) and one "
                         "control that was already coherent "
                         "(technical_integration_method_discussion).")
    p.add_argument("--sink-analysis", action="store_true",
                    help="test rejecting milestone clusters whose centroid is too "
                         "similar to a known sink scenario (Layer A/B mechanics "
                         "centroids), plus a min_cluster_size_fraction sweep "
                         "across all 85 coachable scenarios")
    p.add_argument("--mcs-fractions", default="0.02,0.04,0.06",
                    help="comma-separated min_cluster_size_fraction values for "
                         "--sink-analysis's sweep (default: 0.02 current, 0.04, 0.06)")
    p.add_argument("--full-pipeline", action="store_true",
                    help="run the full would-be Layer C pipeline (UMAP clustering, "
                         "current tuning.yaml percentile/min_cluster_size/floor) "
                         "across all 85 coachable scenarios, tag surviving "
                         "milestones with a review_flag (p95 sink-similarity) "
                         "instead of rejecting them, and report the result")
    return p.parse_args()


def _clause_pool(responses):
    """Segment every response's text into clauses, tracking position and source call."""
    all_clauses, clause_positions, clause_calls = [], [], []
    for resp in responses:
        clauses = segmenter.segment_into_clauses(resp["response_text"])
        n = max(len(clauses) - 1, 1)
        for pos_idx, clause in enumerate(clauses):
            all_clauses.append(clause)
            clause_positions.append(pos_idx / n)
            clause_calls.append(resp["call_filename"])
    return all_clauses, clause_positions, clause_calls


def _relevance_filter(clauses, vecs, calls, info, percentile):
    svec = np.asarray(scenario_vectors.scenario_vec(info), dtype=np.float32)
    svec = svec / (np.linalg.norm(svec) + 1e-10)
    normed = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)
    relevance = normed @ svec
    cutoff = float(np.percentile(relevance, percentile))
    keep = [i for i in range(len(clauses)) if relevance[i] >= cutoff]
    return [clauses[i] for i in keep], vecs[keep], [calls[i] for i in keep]


def _cluster(vecs, min_cluster_size, variant):
    """Run one HDBSCAN variant. Returns (labels, note) where note explains the variant."""
    if variant == "baseline":
        model = HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean",
                         cluster_selection_method="eom")
        return model.fit_predict(vecs)
    if variant == "leaf":
        model = HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean",
                         cluster_selection_method="leaf")
        return model.fit_predict(vecs)
    if variant == "min_samples_2":
        model = HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean",
                         cluster_selection_method="eom", min_samples=2)
        return model.fit_predict(vecs)
    if variant == "umap":
        import umap
        n_components = min(5, max(2, vecs.shape[0] - 2))
        reducer = umap.UMAP(n_components=n_components, metric="cosine", random_state=42)
        reduced = reducer.fit_transform(vecs)
        model = HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean",
                         cluster_selection_method="eom")
        return model.fit_predict(reduced)
    raise ValueError(f"unknown variant: {variant}")


_raw_pool_cache = {}


def _get_raw_pool(info):
    """Segment + embed once per scenario, independent of percentile.

    Cached at module level so a percentile sweep does not re-run spaCy
    segmentation (the actual bottleneck for scenarios with 100+ responses)
    once per percentile value -- only the cheap relevance-cutoff step below
    depends on percentile.
    """
    skey = info["scenario_key"]
    if skey in _raw_pool_cache:
        return _raw_pool_cache[skey]
    responses = storage.get_naren_responses_for_scenario(_conn, skey)
    if not responses or len(responses) < 2:
        _raw_pool_cache[skey] = None
        return None
    all_clauses, _positions, clause_calls = _clause_pool(responses)
    if len(all_clauses) < 6:
        _raw_pool_cache[skey] = None
        return None
    scenario_calls = len({r["call_filename"] for r in responses})
    vecs = embedder.embed_document_matrix(all_clauses)
    result = (all_clauses, vecs, clause_calls, scenario_calls)
    _raw_pool_cache[skey] = result
    return result


def _load_scenario_clause_pool(info, tuning, percentile=None):
    """Reproduce v2/layer_c.py's pipeline up to (but not including) clustering.

    percentile overrides tuning.milestone_relevance_percentile, for sweeping.

    Returns None if the scenario is structurally uncoachable by ANY clustering
    approach (too few responses/clauses) -- those are out of scope for this
    diagnostic, since no HDBSCAN variant can rescue them.
    """
    raw = _get_raw_pool(info)
    if raw is None:
        return None
    all_clauses, vecs, clause_calls, scenario_calls = raw
    all_clauses, vecs, clause_calls = _relevance_filter(
        all_clauses, vecs, clause_calls, info,
        percentile if percentile is not None else tuning.milestone_relevance_percentile,
    )
    if len(all_clauses) < 6:
        return None

    min_cluster_size = cluster_evidence.milestone_min_cluster_size(
        len(all_clauses), tuning.min_cluster_size_fraction,
        tuning.min_cluster_size_floor, tuning.min_cluster_size_ceiling,
    )
    return {
        "scenario_key": info["scenario_key"], "clauses": all_clauses, "vecs": vecs,
        "calls": clause_calls, "scenario_calls": scenario_calls,
        "min_cluster_size": min_cluster_size,
    }


def _summarize(labels, calls):
    n_clusters = len(set(labels) - {-1})
    noise_frac = float(np.mean(labels == -1)) if len(labels) else 1.0
    support_calls = []
    for label in set(labels) - {-1}:
        member_calls = {calls[i] for i in range(len(labels)) if labels[i] == label}
        support_calls.append(len(member_calls))
    return n_clusters, noise_frac, sorted(support_calls, reverse=True)


_KNOWN_JUNK_AT_P40 = ["implementation_feasibility_requests",
                      "advertising_retargeting_strategy_discussion"]
_KNOWN_GOOD_AT_P40 = "technical_integration_method_discussion"


def _sweep_percentile(coachable, tuning, percentiles):
    """Re-run relevance-filter + umap clustering at each percentile.

    Only the umap variant is tested here (it was the best rescuer at
    percentile=40, and the thing being fixed is umap surfacing backchannel in
    the largest scenarios at that percentile) -- baseline/leaf/min_samples_2
    are not re-swept since they were already outperformed at percentile=40.
    """
    watch_keys = _KNOWN_JUNK_AT_P40 + [_KNOWN_GOOD_AT_P40]
    info_by_key = {s["scenario_key"]: s for s in coachable}

    print(f"\n{_BAR}\nPERCENTILE SWEEP (umap variant only)\n{_BAR}")
    print(f"{'percentile':>10} {'rescued (of 28)':>16} {'mean noise%':>13} "
          f"{'clauses kept (3 watch scenarios)':>36}")

    for pct in percentiles:
        pools = {}
        no_cluster_28 = []
        for info in coachable:
            pool = _load_scenario_clause_pool(info, tuning, percentile=pct)
            if pool is None:
                continue
            pools[info["scenario_key"]] = pool
            base_labels = _cluster(pool["vecs"], pool["min_cluster_size"], "baseline")
            if len(set(base_labels) - {-1}) == 0:
                no_cluster_28.append(info["scenario_key"])

        rescued, noise_vals = 0, []
        watch_clause_counts = []
        for skey in no_cluster_28:
            pool = pools[skey]
            labels = _cluster(pool["vecs"], pool["min_cluster_size"], "umap")
            n_clusters, noise, _support = _summarize(labels, pool["calls"])
            noise_vals.append(noise)
            if n_clusters > 0:
                rescued += 1
        for skey in watch_keys:
            watch_clause_counts.append(
                len(pools[skey]["clauses"]) if skey in pools else 0
            )
        mean_noise = 100 * np.mean(noise_vals) if noise_vals else 0.0
        print(f"{pct:>10} {rescued:>16} {mean_noise:>12.1f}% "
              f"{str(watch_clause_counts):>36}")

        print(f"\n  --- clause detail at percentile={pct} ---")
        for skey in watch_keys:
            if skey not in pools:
                print(f"  {skey}: dropped below 6 relevant clauses at this percentile")
                continue
            pool = pools[skey]
            labels = _cluster(pool["vecs"], pool["min_cluster_size"], "umap")
            n_clusters = len(set(labels) - {-1})
            tag = "JUNK-AT-P40" if skey in _KNOWN_JUNK_AT_P40 else "GOOD-AT-P40"
            print(f"  [{tag}] {skey} ({len(pool['clauses'])} clauses, "
                  f"{n_clusters} cluster(s)):")
            if n_clusters == 0:
                print("    (no clusters)")
                continue
            for label in sorted(set(labels) - {-1}):
                members = [pool["clauses"][i] for i in range(len(labels)) if labels[i] == label]
                print(f"    cluster {label} ({len(members)} clauses): "
                      f"{members[0][:100]}")


def _sink_centroids():
    """Sink scenario description vectors, normalized. Same vector space as clause
    embeddings (bge document embeddings), so cosine similarity against a
    milestone-cluster centroid is directly meaningful."""
    scenarios = storage.get_scenarios(_conn)
    sinks = {s["scenario_key"]: s for s in scenarios if not s.get("is_coachable", True)}
    keys, vecs = scenario_vectors.build_scenario_vecs(sinks)
    arr = np.asarray(vecs, dtype=np.float32)
    normed = arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-10)
    return keys, normed


def _cluster_records(pool, labels, sink_keys, sink_centroids):
    """One record per cluster: its own centroid's max cosine similarity to any
    sink scenario, plus which sink it's nearest to. High similarity = suspect
    backchannel/mechanics leaking into a milestone candidate."""
    records = []
    for label in sorted(set(labels) - {-1}):
        idx = [i for i in range(len(labels)) if labels[i] == label]
        member_vecs = pool["vecs"][idx]
        centroid = member_vecs.mean(axis=0)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
        sims = sink_centroids @ centroid
        best_j = int(np.argmax(sims))
        support_calls = len({pool["calls"][i] for i in idx})
        records.append({
            "scenario_key": pool["scenario_key"], "cluster_id": int(label),
            "n_clauses": len(idx), "support_calls": support_calls,
            "max_sink_sim": float(sims[best_j]), "nearest_sink": sink_keys[best_j],
            "sample_clause": pool["clauses"][idx[0]][:90],
        })
    return records


def _sink_analysis(coachable, tuning, mcs_fractions):
    sink_keys, sink_centroids = _sink_centroids()
    print(f"\n{_BAR}\nSINK-CENTROID CHECK: {len(sink_keys)} sink scenarios loaded\n{_BAR}")

    # Part 1: full report at CURRENT tuning (percentile=40, mcs_fraction=0.02),
    # across all 85 coachable scenarios, to calibrate a rejection threshold.
    all_records = []
    for info in coachable:
        pool = _load_scenario_clause_pool(info, tuning)  # tuning defaults
        if pool is None:
            continue
        labels = _cluster(pool["vecs"], pool["min_cluster_size"], "umap")
        all_records.extend(_cluster_records(pool, labels, sink_keys, sink_centroids))

    sims = np.array([r["max_sink_sim"] for r in all_records])
    print(f"\nTotal milestone-candidate clusters across all 85 scenarios: {len(all_records)}")
    pctiles = [10, 25, 50, 75, 90, 95]
    print("max_sink_sim distribution: " +
          " ".join(f"p{p}={np.percentile(sims, p):.3f}" for p in pctiles))

    threshold = float(np.percentile(sims, 90))
    print(f"\nCandidate rejection threshold (p90 of full distribution): {threshold:.3f}")

    ranked = sorted(all_records, key=lambda r: -r["max_sink_sim"])
    print(f"\nTop 15 most sink-like clusters (highest max_sink_sim -- suspects):")
    for r in ranked[:15]:
        print(f"  sim={r['max_sink_sim']:.3f} nearest_sink={r['nearest_sink']:<40} "
              f"{r['scenario_key']}/cluster{r['cluster_id']} "
              f"({r['n_clauses']}cl, {r['support_calls']}calls): {r['sample_clause']}")
    print(f"\nBottom 10 least sink-like clusters (lowest max_sink_sim -- confidently real):")
    for r in ranked[-10:]:
        print(f"  sim={r['max_sink_sim']:.3f} nearest_sink={r['nearest_sink']:<40} "
              f"{r['scenario_key']}/cluster{r['cluster_id']} "
              f"({r['n_clauses']}cl, {r['support_calls']}calls): {r['sample_clause']}")

    rejected = [r for r in all_records if r["max_sink_sim"] >= threshold]
    print(f"\nAt threshold={threshold:.3f}: {len(rejected)}/{len(all_records)} clusters "
          f"would be rejected as sink-like. Scenarios losing >=1 cluster to this filter:")
    from collections import Counter
    by_scenario = Counter(r["scenario_key"] for r in rejected)
    for skey, n in by_scenario.most_common(20):
        print(f"  {skey}: {n} cluster(s) rejected")

    # Part 2: min_cluster_size_fraction sweep, percentile held at tuning default,
    # reporting how the sink-similarity distribution shifts.
    print(f"\n{_BAR}\nmin_cluster_size_fraction SWEEP (percentile held at "
          f"{tuning.milestone_relevance_percentile})\n{_BAR}")
    print(f"{'fraction':>10} {'scenarios w/cluster (of 85)':>28} {'total clusters':>15} "
          f"{'mean noise%':>12} {'sim p50/p75/p90':>25} {'>= threshold':>13}")
    for frac in mcs_fractions:
        records = []
        n_with_cluster = 0
        noise_vals = []
        for info in coachable:
            raw = _get_raw_pool(info)
            if raw is None:
                continue
            all_clauses, vecs, clause_calls, scenario_calls = raw
            all_clauses, vecs, clause_calls = _relevance_filter(
                all_clauses, vecs, clause_calls, info, tuning.milestone_relevance_percentile,
            )
            if len(all_clauses) < 6:
                continue
            mcs = cluster_evidence.milestone_min_cluster_size(
                len(all_clauses), frac,
                tuning.min_cluster_size_floor, tuning.min_cluster_size_ceiling,
            )
            pool = {"scenario_key": info["scenario_key"], "clauses": all_clauses,
                    "vecs": vecs, "calls": clause_calls}
            labels = _cluster(vecs, mcs, "umap")
            n_clusters, noise, _support = _summarize(labels, clause_calls)
            noise_vals.append(noise)
            if n_clusters > 0:
                n_with_cluster += 1
            records.extend(_cluster_records(pool, labels, sink_keys, sink_centroids))
        frac_sims = np.array([r["max_sink_sim"] for r in records]) if records else np.array([0.0])
        above = int(np.sum(frac_sims >= threshold))
        mean_noise = 100 * np.mean(noise_vals) if noise_vals else 0.0
        sim_str = (f"{np.percentile(frac_sims,50):.3f}/"
                   f"{np.percentile(frac_sims,75):.3f}/"
                   f"{np.percentile(frac_sims,90):.3f}")
        print(f"{frac:>10} {n_with_cluster:>28} {len(records):>15} {mean_noise:>11.1f}% "
              f"{sim_str:>25} {above:>13}")


def _full_pipeline_with_review_flag(coachable, tuning):
    """Full would-be Layer C run: UMAP clustering + the floor=2 call-support gate
    (already adopted in tuning.yaml) + a review_flag on each surviving milestone
    instead of an auto-reject filter -- mirroring Layer A's needs_review pattern
    (high-signal routes to review, it doesn't auto-delete)."""
    sink_keys, sink_centroids = _sink_centroids()

    all_records = []
    scenario_results = {}
    for info in coachable:
        skey = info["scenario_key"]
        pool = _load_scenario_clause_pool(info, tuning)
        if pool is None:
            scenario_results[skey] = {"status": "structurally_uncoachable", "milestones": []}
            continue
        labels = _cluster(pool["vecs"], pool["min_cluster_size"], "umap")
        records = _cluster_records(pool, labels, sink_keys, sink_centroids)
        required = cluster_evidence.required_milestone_support(
            pool["scenario_calls"], tuning.min_milestone_call_fraction,
            tuning.min_milestone_calls_floor,
        )
        surviving = [r for r in records if r["support_calls"] >= required]
        if not surviving:
            scenario_results[skey] = {"status": "no_surviving_milestone", "milestones": []}
            continue
        scenario_results[skey] = {"status": "v2_clustered", "milestones": surviving}
        all_records.extend(surviving)

    sims = np.array([r["max_sink_sim"] for r in all_records])
    threshold = float(np.percentile(sims, 95))
    for r in all_records:
        r["review_flag"] = r["max_sink_sim"] >= threshold

    print(f"\n{_BAR}\nFULL PIPELINE: UMAP + floor=2 gate + review_flag "
          f"(threshold=p95={threshold:.3f})\n{_BAR}")
    n_clustered = sum(1 for v in scenario_results.values() if v["status"] == "v2_clustered")
    n_no_surviving = sum(1 for v in scenario_results.values() if v["status"] == "no_surviving_milestone")
    n_uncoachable = sum(1 for v in scenario_results.values() if v["status"] == "structurally_uncoachable")
    total_milestones = len(all_records)
    flagged = sum(1 for r in all_records if r["review_flag"])
    print(f"Scenarios: {len(coachable)} coachable total")
    print(f"  v2_clustered (>=1 milestone survives): {n_clustered}")
    print(f"  no_surviving_milestone (would fall back to V1): {n_no_surviving}")
    print(f"  structurally_uncoachable (too few responses/clauses): {n_uncoachable}")
    print(f"Total milestones: {total_milestones} ({flagged} flagged for review, "
          f"{total_milestones - flagged} clean)")

    from collections import Counter
    depth_hist = Counter(len(v["milestones"]) for v in scenario_results.values())
    print(f"\nDepth distribution (milestones per scenario, including 0 for "
          f"fallback/uncoachable): {dict(sorted(depth_hist.items()))}")

    print(f"\n--- Sample of FLAGGED milestones (read for false-positive risk) ---")
    flagged_records = sorted([r for r in all_records if r["review_flag"]],
                              key=lambda r: -r["max_sink_sim"])
    for r in flagged_records[:10]:
        print(f"  sim={r['max_sink_sim']:.3f} {r['scenario_key']}/cluster{r['cluster_id']} "
              f"({r['n_clauses']}cl, {r['support_calls']}calls): {r['sample_clause']}")

    print(f"\n--- Sample of CLEAN milestones just below threshold (read for missed junk) ---")
    clean_near_threshold = sorted(
        [r for r in all_records if not r["review_flag"]], key=lambda r: -r["max_sink_sim"]
    )
    for r in clean_near_threshold[:10]:
        print(f"  sim={r['max_sink_sim']:.3f} {r['scenario_key']}/cluster{r['cluster_id']} "
              f"({r['n_clauses']}cl, {r['support_calls']}calls): {r['sample_clause']}")


def main():
    global _conn
    args = _parse_args()
    cfg = load_config()
    _conn = storage.get_connection(cfg.database_url)
    tuning = load_tuning().layer_c

    scenarios = storage.get_scenarios(_conn)
    coachable = [s for s in scenarios if s.get("is_coachable", True)]

    if args.full_pipeline:
        _full_pipeline_with_review_flag(coachable, tuning)
        _conn.close()
        return

    if args.sink_analysis:
        mcs_fractions = [float(f.strip()) for f in args.mcs_fractions.split(",")]
        _sink_analysis(coachable, tuning, mcs_fractions)
        _conn.close()
        return

    if args.sweep_percentile:
        percentiles = [int(p.strip()) for p in args.sweep_percentile.split(",")]
        _sweep_percentile(coachable, tuning, percentiles)
        _conn.close()
        return

    pools = {}
    no_cluster_28 = []
    working = []
    for info in coachable:
        pool = _load_scenario_clause_pool(info, tuning)
        if pool is None:
            continue
        pools[info["scenario_key"]] = pool
        labels = _cluster(pool["vecs"], pool["min_cluster_size"], "baseline")
        n_clusters, _noise, _support = _summarize(labels, pool["calls"])
        if n_clusters == 0:
            no_cluster_28.append(info["scenario_key"])
        else:
            working.append(info["scenario_key"])

    controls = sorted(working)[:args.controls]

    print(_BAR)
    print(f"Baseline-no-cluster scenarios found: {len(no_cluster_28)} "
          f"(expected 28 from the prior session's diagnostic)")
    print(f"Control sample (already-working, baseline variant): {len(controls)}")
    print(_BAR)

    results = {}  # (scenario_key, variant) -> (n_clusters, noise_frac, support_calls)
    for skey in no_cluster_28 + controls:
        pool = pools[skey]
        for variant in _VARIANTS:
            labels = _cluster(pool["vecs"], pool["min_cluster_size"], variant)
            results[(skey, variant)] = _summarize(labels, pool["calls"])

    controls_header = f"controls unchanged (of {len(controls)})"
    print(f"\n{'VARIANT':<15} {'rescued (of 28)':>16} {controls_header:>28} "
          f"{'mean n_clusters (28)':>22} {'mean noise% (28)':>18}")
    print("-" * 100)
    best_variant, best_rescued = None, -1
    for variant in _VARIANTS:
        rescued = sum(1 for skey in no_cluster_28 if results[(skey, variant)][0] > 0)
        unchanged = sum(
            1 for skey in controls
            if results[(skey, variant)][0] == results[(skey, "baseline")][0]
        )
        mean_clusters = np.mean([results[(skey, variant)][0] for skey in no_cluster_28])
        mean_noise = np.mean([results[(skey, variant)][1] for skey in no_cluster_28]) * 100
        print(f"{variant:<15} {rescued:>16} {unchanged:>28} {mean_clusters:>22.2f} "
              f"{mean_noise:>17.1f}%")
        if variant != "baseline" and rescued > best_rescued:
            best_variant, best_rescued = variant, rescued

    print(f"\nBest-performing variant by rescue count: {best_variant} "
          f"({best_rescued}/{len(no_cluster_28)} of the no-cluster scenarios gained "
          f"at least 1 cluster)")

    print(f"\n{_BAR}\nPER-SCENARIO DETAIL (no-cluster population, all variants)\n{_BAR}")
    print(f"{'scenario_key':<45} {'clauses':>8} " +
          " ".join(f"{v:>14}" for v in _VARIANTS))
    for skey in no_cluster_28:
        row = f"{skey:<45} {len(pools[skey]['clauses']):>8} "
        row += " ".join(
            f"{results[(skey, v)][0]}cl/{results[(skey, v)][1]*100:.0f}%n".rjust(14)
            for v in _VARIANTS
        )
        print(row)

    if args.detail and best_variant:
        print(f"\n{_BAR}\nCLAUSE-LEVEL DETAIL for '{best_variant}' "
              f"(read these for coherence -- counts alone don't prove a fix)\n{_BAR}")
        sample = (no_cluster_28 + controls)[:args.detail]
        for skey in sample:
            pool = pools[skey]
            labels = _cluster(pool["vecs"], pool["min_cluster_size"], best_variant)
            print(f"\n--- {skey} ({'was no-cluster' if skey in no_cluster_28 else 'control'}) ---")
            n_clusters = len(set(labels) - {-1})
            if n_clusters == 0:
                print("  (still no clusters under this variant)")
                continue
            for label in sorted(set(labels) - {-1}):
                members = [pool["clauses"][i] for i in range(len(labels)) if labels[i] == label]
                print(f"  cluster {label} ({len(members)} clauses):")
                for clause in members[:3]:
                    print(f"    - {clause}")

    _conn.close()


_conn = None

if __name__ == "__main__":
    main()
