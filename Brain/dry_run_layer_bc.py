"""Calibrate Layer B matching and Layer C milestone thresholds with zero Gemma spend.

Layer C's inputs come from Layer B's assignments, which come from Layer A's
LABELLED taxonomy -- and the labels are the part that needs Gemma. So a fully
faithful dry run is unreachable without paying for Layer A first. Two moves get
around that:

  1. Pseudo-scenarios. A cluster's top c-TF-IDF keywords stand in for the
     LLM-written "sub_topic + keyphrases", embedded through the SAME
     shared.scenario_vectors path production uses. Structurally identical, same
     embedding space -- so relative similarity behaviour is representative even
     though the wording is not what Gemma would write.
  2. Production code, not reimplementations. This script calls
     layer_a._merged_clusters, layer_b.extract_pairs, layer_b.assign_scenarios
     and layer_c._relevance_filter directly. A threshold that looks good here is
     good for the code that will actually run.

What it measures, and why each matters:

  Layer B -- sink absorption (are mechanics sinks actually catching junk?),
    assignment concentration (does one scenario hoover up everything, which is
    the "70% of pairs match all scenarios" pathology in a new form), and a sweep
    of relative_margin against the real similarity distribution.

  Layer C -- the milestone-count distribution per scenario and, critically, HOW
    MANY SCENARIOS DROP TO ZERO MILESTONES. The design doc names over-filtering
    as the main risk: min_milestone_call_fraction and milestone_relevance_percentile
    are currently reasoned guesses, exactly the state merge_cosine_threshold=0.80
    was in before inspection proved it wrong.

Nothing is written to Postgres or Pinecone and no LLM is called.

Usage (from Brain/, venv active):
    python dry_run_layer_bc.py --limit 30      # fast smoke test
    python dry_run_layer_bc.py                 # full corpus
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from config import load_config
from preprocessing import embedder, segmenter
from preprocessing.transcript_parser import parse_transcript, load_roster
from shared import cluster_evidence, scenario_vectors
from shared.tuning import load_tuning
from v1 import layer_b
from v2 import layer_a, layer_c

_BAR = "=" * 78

# Swept locally; the value in tuning.yaml is only the default reported alongside.
_SWEEP_MARGIN = [0.70, 0.80, 0.85, 0.90, 0.95]
_SWEEP_PERCENTILE = [40, 60, 75]
_SWEEP_FRACTION = [0.05, 0.10, 0.15, 0.25]

_KEYWORDS_PER_SCENARIO = 8


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--limit", type=int, default=0, help="only read the first N transcripts")
    p.add_argument("--review-as", choices=["sink", "scenario"], default="sink",
                   help="treat needs_review clusters as sinks (default) or as coachable")
    p.add_argument("--show", type=int, default=15)
    return p.parse_args()


def _load_calls(recordings: str, limit: int, config):
    """Return [(stem, turns)] plus the flat turn list Layer A clusters over."""
    files = sorted(Path(recordings).glob("*.txt"))
    if not files:
        raise FileNotFoundError(f"No .txt transcripts found in {recordings}")
    if limit:
        files = files[:limit]
    calls, all_turns = [], []
    for path in files:
        turns = parse_transcript(
            str(path), config.joveo_speakers_lower, config.naren_name_lower,
            roster=load_roster(str(path)),
        )
        calls.append((path.stem, turns))
        all_turns.extend(turns)
    return calls, all_turns


def _build_pseudo_taxonomy(clusters, total_calls, tuning_a, review_as):
    """Turn merged clusters into a scenario_map shaped exactly like Layer A's output.

    The keyword string plays the role of sub_topic + keyphrases. It goes through
    shared.scenario_vectors like a real description, so Layer B sees the same
    geometry it will see in production.
    """
    min_support = cluster_evidence.required_call_support(
        total_calls, tuning_a.min_call_support_fraction, tuning_a.min_call_support_floor
    )
    scenario_map, verdicts, dropped = {}, {}, 0
    for i, cluster in enumerate(clusters):
        verdict = cluster_evidence.triage(
            cluster["stats"], min_support, tuning_a.ubiquity_ceiling
        )
        if verdict == cluster_evidence.INSUFFICIENT_EVIDENCE:
            dropped += 1
            continue
        words = [w.strip() for w in cluster["keywords"].split(",")][:_KEYWORDS_PER_SCENARIO]
        key = f"c{i:03d}_{words[0].replace(' ', '_')}" if words else f"c{i:03d}"
        coachable = verdict == cluster_evidence.SCENARIO_CANDIDATE or review_as == "scenario"
        scenario_map[key] = {
            "scenario_id": i + 1,
            "sub_topic": " ".join(words),
            "primary_topic": words[0] if words else "unknown",
            "keyphrases": words,
            "soft_skills": [],
            "is_coachable": coachable,
            "cluster_kind": (cluster_evidence.KIND_SCENARIO if coachable
                             else cluster_evidence.KIND_MECHANICS),
        }
        verdicts[key] = verdict
    return scenario_map, verdicts, dropped, min_support


def _report_layer_b(pairs, scenario_map, verdicts, sim_matrix, keys, show, tuning_b):
    print(f"\n{_BAR}\nLAYER B -- ASSIGNMENT QUALITY\n{_BAR}")
    is_sink = {k: not scenario_map[k]["is_coachable"] for k in keys}

    n = len(pairs)
    sink_pairs = sum(1 for p in pairs if is_sink[p["scenario_key"]])
    print(f"  pairs extracted            : {n}")
    print(f"  filed to a mechanics sink  : {sink_pairs} ({sink_pairs / n:.1%})")
    print(f"  filed to a real scenario   : {n - sink_pairs} ({(n - sink_pairs) / n:.1%})")

    widths = Counter(len(p["scenario_keys"]) for p in pairs)
    print("\n  scenarios matched per pair (cap "
          f"{tuning_b.max_scenarios_per_pair}, margin {tuning_b.relative_margin}):")
    for k in sorted(widths):
        print(f"    {k} scenario(s): {widths[k]:>6} pair(s) ({widths[k] / n:.1%})")

    # Concentration is the pathology to watch: a taxonomy where one scenario
    # absorbs a large share of pairs is not discriminating, whatever its size.
    counts = Counter(p["scenario_key"] for p in pairs)
    print(f"\n  top {show} scenarios by pair volume (of {len(scenario_map)} scenarios):")
    print(f"    {'pairs':>7} {'share':>7}  verdict            key")
    for key, count in counts.most_common(show):
        tag = "SINK" if is_sink[key] else verdicts.get(key, "")
        print(f"    {count:>7} {count / n:>6.1%}  {tag:<18} {key}")
    top10 = sum(c for _, c in counts.most_common(10))
    print(f"    top-10 share of all pairs: {top10 / n:.1%}")
    print(f"    scenarios with zero pairs: {len(scenario_map) - len(counts)}")

    best = sim_matrix.max(axis=1)
    print("\n  best-match cosine distribution (is the margin selective at all?):")
    print("    " + "  ".join(f"p{p}={np.percentile(best, p):.3f}"
                             for p in (10, 25, 50, 75, 90)))
    print(f"    spread p90-p10 = {np.percentile(best, 90) - np.percentile(best, 10):.3f} "
          f"-- a narrow band means relative_margin has little room to discriminate")

    # The sweep must mirror assign_scenarios exactly, including the sink
    # short-circuit: a pair whose BEST match is a sink is filed there alone and
    # never reaches the margin logic. Sweeping without that rule reports a
    # match width production would never produce.
    sink_mask = np.array([not scenario_map[k]["is_coachable"] for k in keys])
    best_j = sim_matrix.argmax(axis=1)
    real_best = ~sink_mask[best_j]
    n_real = int(real_best.sum())
    print(f"\n  relative_margin sweep over the {n_real} pair(s) whose best match is a real")
    print(f"  scenario ({n - n_real} short-circuit to a sink and ignore the margin):")
    if not n_real:
        print("    (none -- nothing to sweep)")
        return
    cap = tuning_b.max_scenarios_per_pair
    sub = sim_matrix[real_best]
    order = np.argsort(-sub, axis=1)[:, :cap]
    top_sims = np.take_along_axis(sub, order, axis=1)
    top_is_sink = sink_mask[order]
    print(f"    {'margin':>7} {'mean':>7} {'1 match':>9} {'at cap':>8}")
    for margin in _SWEEP_MARGIN:
        keep = (top_sims >= margin * top_sims[:, :1]) & ~top_is_sink
        kept = np.maximum(keep.sum(axis=1), 1)
        single = int((kept == 1).sum())
        capped = int((kept == cap).sum())
        print(f"    {margin:>7.2f} {kept.mean():>7.2f} {single / n_real:>8.0%} "
              f"{capped / n_real:>7.0%}")


def _milestone_counts(responses, info, percentile, tuning_c):
    """Cluster one scenario's response clauses and return per-cluster call support.

    Mirrors run_layer_c_v2's numeric path exactly, minus the Gemma description
    calls -- which is the whole point: milestone COUNT is decided before any
    prose is generated.
    """
    from hdbscan import HDBSCAN

    all_clauses, positions, calls = [], [], []
    for resp in responses:
        clauses = segmenter.segment_into_clauses(resp["response_text"])
        denom = max(len(clauses) - 1, 1)
        for pos_idx, clause in enumerate(clauses):
            all_clauses.append(clause)
            positions.append(pos_idx / denom)
            calls.append(resp["call_filename"])

    if len(all_clauses) < 6:
        return None
    vecs = embedder.embed_document_matrix(all_clauses)
    kept_clauses, kept_vecs, _pos, kept_calls, _rel = layer_c._relevance_filter(
        all_clauses, vecs, positions, calls, info, percentile
    )
    if len(kept_clauses) < 6:
        return None

    min_cluster_size = cluster_evidence.milestone_min_cluster_size(
        len(kept_clauses), tuning_c.min_cluster_size_fraction,
        tuning_c.min_cluster_size_floor, tuning_c.min_cluster_size_ceiling,
    )
    labels = HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean",
                     cluster_selection_method="eom").fit_predict(kept_vecs)

    per_cluster: dict[int, set] = defaultdict(set)
    for i, label in enumerate(labels):
        if label != -1:
            per_cluster[int(label)].add(kept_calls[i])
    return sorted((len(v) for v in per_cluster.values()), reverse=True)


def _report_layer_c(by_scenario, scenario_map, tuning_c, show):
    print(f"\n{_BAR}\nLAYER C -- MILESTONE THRESHOLD SWEEP\n{_BAR}")
    coachable = [k for k, info in scenario_map.items()
                 if info["is_coachable"] and k in by_scenario]
    print(f"  coachable scenarios with responses: {len(coachable)}")
    print(f"  clustering once per relevance percentile, then evaluating support gates.\n")

    print(f"  {'pct':>4} {'frac':>6} {'floor':>6} | {'zero':>5} {'median':>7} "
          f"{'p90':>5} {'max':>5} {'capped':>7}")
    print("  " + "-" * 62)

    for percentile in _SWEEP_PERCENTILE:
        supports = {}
        for key in coachable:
            result = _milestone_counts(
                by_scenario[key], scenario_map[key], percentile, tuning_c
            )
            if result is not None:
                supports[key] = result
        for fraction in _SWEEP_FRACTION:
            counts, capped = [], 0
            for key, cluster_supports in supports.items():
                scenario_calls = len({r["call_filename"] for r in by_scenario[key]})
                required = cluster_evidence.required_milestone_support(
                    scenario_calls, fraction, tuning_c.min_milestone_calls_floor
                )
                surviving = sum(1 for s in cluster_supports if s >= required)
                counts.append(surviving)
                if surviving > tuning_c.milestone_hard_cap:
                    capped += 1
            if not counts:
                continue
            arr = np.array(counts)
            print(f"  {percentile:>4} {fraction:>6.2f} "
                  f"{tuning_c.min_milestone_calls_floor:>6} | "
                  f"{int((arr == 0).sum()):>5} {np.median(arr):>7.1f} "
                  f"{np.percentile(arr, 90):>5.1f} {arr.max():>5} {capped:>7}")

    print("\n  zero   = scenarios left with NO milestone (over-filtering -- the key risk)")
    print("  capped = scenarios exceeding milestone_hard_cap "
          f"({tuning_c.milestone_hard_cap}); should be 0")
    print(f"  current tuning.yaml: percentile={tuning_c.milestone_relevance_percentile} "
          f"fraction={tuning_c.min_milestone_call_fraction} "
          f"floor={tuning_c.min_milestone_calls_floor}")


def main() -> None:
    args = _parse_args()
    tuning = load_tuning()
    config = load_config()

    calls, all_turns = _load_calls(args.recordings, args.limit, config)
    total_calls = len(calls)
    print(f"Parsed {total_calls} transcript(s), {len(all_turns)} turns.")

    clauses, call_ids = layer_a.build_client_clause_pool(all_turns)
    print(f"CLIENT clause pool: {len(clauses)} clauses. Embedding...")
    vecs = embedder.embed_query_matrix(clauses)
    topic_model, topics = layer_a.fit_topic_model(clauses, vecs)

    clusters = layer_a._merged_clusters(
        clauses, call_ids, vecs, topics, topic_model,
        total_calls, tuning.layer_a.merge_cosine_threshold,
    )
    scenario_map, verdicts, dropped, min_support = _build_pseudo_taxonomy(
        clusters, total_calls, tuning.layer_a, args.review_as
    )
    n_coachable = sum(1 for v in scenario_map.values() if v["is_coachable"])
    print(f"\nPseudo-taxonomy: {len(scenario_map)} scenario(s) "
          f"({n_coachable} coachable, {len(scenario_map) - n_coachable} sink), "
          f"{dropped} dropped below {min_support} calls.")
    print(f"ASSUMPTION: needs_review clusters treated as "
          f"{'SINKS' if args.review_as == 'sink' else 'COACHABLE'}. "
          f"Gemma decides this for real -- of 15 flagged at merge 0.85, 11 were junk "
          f"and 4 were real business topics.")
    print("Scenario descriptions are c-TF-IDF keywords, not Gemma prose: relative "
          "similarity is representative, exact wording is not.")

    pairs = []
    for idx, (stem, turns) in enumerate(calls):
        for pair in layer_b.extract_pairs(turns, db_call_id=idx + 1):
            pair["call_filename"] = stem
            pairs.append(pair)
    if not pairs:
        raise SystemExit("No trigger-response pairs extracted.")
    print(f"\nLayer B: extracted {len(pairs)} pair(s). Assigning via production code...")

    layer_b.assign_scenarios(pairs, scenario_map, config)

    keys, scenario_vecs = scenario_vectors.build_scenario_vecs(scenario_map)
    trigger_vecs = embedder.embed_query_matrix([p["trigger_text"] for p in pairs])
    S = np.asarray(scenario_vecs, dtype=np.float32)
    T = trigger_vecs / (np.linalg.norm(trigger_vecs, axis=1, keepdims=True) + 1e-10)
    S = S / (np.linalg.norm(S, axis=1, keepdims=True) + 1e-10)
    sim_matrix = T @ S.T

    _report_layer_b(pairs, scenario_map, verdicts, sim_matrix, keys, args.show, tuning.layer_b)

    by_scenario: dict[str, list[dict]] = defaultdict(list)
    for pair in pairs:
        by_scenario[pair["scenario_key"]].append({
            "response_text": pair["response_text"],
            "call_filename": pair["call_filename"],
        })
    _report_layer_c(by_scenario, scenario_map, tuning.layer_c, args.show)

    print(f"\n{_BAR}\nNo Gemma calls made. No Postgres or Pinecone writes.\n{_BAR}")


if __name__ == "__main__":
    main()
