#!/usr/bin/env python3
"""Shared substrate for the 2026-08-17 Layer C trial (relative filter + noise rescue).

Spec: docs/superpowers/specs/2026-08-17-layer-c-relative-filter-and-rescue-design.md
(gates frozen and committed BEFORE this file existed).

NEW HARNESS by operator instruction this session, but built on the rule this repo keeps
re-earning: import production code, never paraphrase it. Everything that decides an outcome
is either a production function (`build_clause_pool`, `_relevance_filter`,
`_cluster_milestones`, `cluster_evidence.*`, `assign_scenarios`, `extract_pairs` via
`build_pairs`) or a NEW pure function unit-tested in tests/test_layer_c_filter_rescue.py.
The loaders reused from layer_bc_arms (`scenario_map_from_rows`, `install_embedder_shim`,
`prewarm`, `build_pairs`, `taxonomy_path`) are the ones proven by that trial's F1 checks
(controls reproduced their published artifacts field-for-field); the measurement logic here
shares nothing with that runner and validates itself against the published control via F0.

ZERO chat calls. ZERO Postgres. Embeddings are cache-only (the shim ABORTS on a miss).
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402

# The instrument sweep grid -- FROZEN in the spec (section 3.1). Changing a value here after
# any run is gate-tampering; add a new named grid instead if a follow-up is pre-registered.
RULE_GRID: list[tuple[str, float | int]] = (
    [("rank", k) for k in (1, 3, 5, 8)]
    + [("margin", m) for m in (0.90, 0.95, 0.98, 1.00)]
    + [("demean", d) for d in (0.00, 0.01, 0.02, 0.03)]
    + [("csls", k) for k in (1, 3, 5)]
)
CSLS_NEIGHBOURHOOD = 10  # k for both CSLS correction terms, frozen in the spec

# Frozen gate constants (spec section 3.2 / section 4).
GT1A_PASS_PP = 0.25       # survival gap for a PASS
GT1A_NULL_PP = 0.15       # below this at every eligible point -> NULL
GT1A_MIN_REAL_SURVIVAL = 0.50
GT1B_PERM_VOLUME_MAX = 0.75   # permuted volume must fall to <= this share of real, new filter
GT1B_SANITY_BAND = (0.90, 1.10)  # p40 permuted/real volume band that reproduces the blindness
RESCUE_MEMBER_PCTL = 25   # the Layer A rescue_centroid rule, ported unchanged


# ---------------------------------------------------------------------------------------
# pure functions (unit-tested)
# ---------------------------------------------------------------------------------------

def unit_rows(mat: np.ndarray) -> np.ndarray:
    mat = np.asarray(mat, dtype=np.float32)
    return mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-10)


def permute_destinations(keys: list[str], rng) -> list[str]:
    """The r1p-validated mis-routing model: destination multiset preserved, assignment
    shuffled. The assert is the invariant, in code, because a silently wrong placebo looks
    exactly like a valid result."""
    perm = list(keys)
    rng.shuffle(perm)
    assert Counter(perm) == Counter(keys), "permutation changed the destination multiset"
    return perm


def keep_rank(sims: np.ndarray, own: int, k: int) -> np.ndarray:
    """Keep a clause iff its own scenario is within its top-k scenarios by cosine.
    Rank = number of STRICTLY better scenarios, so ties resolve toward keeping."""
    own_s = sims[:, own]
    return (sims > own_s[:, None]).sum(axis=1) < k


def keep_margin(sims: np.ndarray, own: int, m: float) -> np.ndarray:
    """Keep iff cos(own) >= m * max over OTHER scenarios (relative_match's shape)."""
    own_s = sims[:, own]
    others = np.delete(sims, own, axis=1)
    return own_s >= m * others.max(axis=1)


def keep_demean(sims: np.ndarray, own: int, delta: float) -> np.ndarray:
    """One-sided CSLS: keep iff cos(own) minus the clause's mean cosine to the OTHER
    scenarios clears delta. Subtracting the per-clause offset is what moves the decision
    into the frame where the 78.2% signal lives."""
    own_s = sims[:, own]
    others = np.delete(sims, own, axis=1)
    return own_s - others.mean(axis=1) >= delta


def r_neighbourhood(sims: np.ndarray, k: int) -> np.ndarray:
    """Mean of each row's top-k values -- CSLS's r(.) term (Conneau et al. 2018)."""
    k = min(k, sims.shape[1])
    part = np.partition(sims, -k, axis=1)[:, -k:]
    return part.mean(axis=1)


def keep_csls(sims: np.ndarray, own: int, k_keep: int, rx: np.ndarray,
              ry: np.ndarray) -> np.ndarray:
    """Full CSLS rank rule: csls_ij = 2*sims_ij - rx_i - ry_j, keep iff own scenario is in
    the clause's top-k_keep by CSLS score. rx is the clause-side neighbourhood term (this
    pool), ry the scenario-side term (computed ONCE over the union clause population, which
    is identical for the real and permuted arms by construction of the permutation)."""
    c = 2.0 * sims - rx[:, None] - ry[None, :]
    own_c = c[:, own]
    return (c > own_c[:, None]).sum(axis=1) < k_keep


def rule_mask(rule: str, param, sims: np.ndarray, own: int,
              rx: np.ndarray | None = None, ry: np.ndarray | None = None) -> np.ndarray:
    """ONE dispatch for every arm -- the symmetric-filtering guard. Real and permuted pools
    both come through here; there is no second code path to drift."""
    if rule == "rank":
        return keep_rank(sims, own, int(param))
    if rule == "margin":
        return keep_margin(sims, own, float(param))
    if rule == "demean":
        return keep_demean(sims, own, float(param))
    if rule == "csls":
        assert rx is not None and ry is not None, "csls needs both correction terms"
        return keep_csls(sims, own, int(param), rx, ry)
    raise ValueError(f"unknown rule {rule!r}")


def rescue_assign(noise_vecs: np.ndarray, members: dict[int, np.ndarray]) -> tuple[dict, dict]:
    """rescue_centroid, ported: admit a noise clause into its NEAREST cluster c iff
    cos(clause, centroid_c) >= p25 of c's OWN member cosines. Full embedding space --
    the Layer A diagnostic showed the loss happens in the UMAP->HDBSCAN stage, so the
    admission test must not run in the space that caused the loss.

    Returns ({cluster_label: [noise_row_index, ...]}, {cluster_label: threshold}).
    Empty noise pool or no clusters -> empty admissions, never an error.
    """
    labels = sorted(members)
    if not labels or noise_vecs.shape[0] == 0:
        return {l: [] for l in labels}, {}
    cents, thr = [], {}
    for l in labels:
        mem = unit_rows(members[l])
        c = mem.mean(axis=0)
        c = c / (np.linalg.norm(c) + 1e-10)
        cents.append(c)
        thr[l] = float(np.percentile(mem @ c, RESCUE_MEMBER_PCTL))
    C = np.stack(cents)
    sims = unit_rows(noise_vecs) @ C.T
    nearest = sims.argmax(axis=1)
    best = sims.max(axis=1)
    admitted: dict[int, list[int]] = {l: [] for l in labels}
    for i in range(len(best)):
        l = labels[int(nearest[i])]
        if best[i] >= thr[l]:
            admitted[l].append(i)
    return admitted, thr


def placebo_assign(counts: dict[int, int], n_noise: int, rng) -> dict[int, list[int]]:
    """The rescue's placebo: the SAME COUNT of noise clauses per cluster, drawn uniformly
    without replacement from the same scenario's noise pool. Matches what the arm ADDS,
    per destination; content selection is the only difference. Counts asserted equal."""
    total = sum(counts.values())
    assert total <= n_noise, f"placebo cannot draw {total} from {n_noise} noise clauses"
    idx = list(range(n_noise))
    rng.shuffle(idx)
    out: dict[int, list[int]] = {}
    p = 0
    for l in sorted(counts):
        out[l] = idx[p:p + counts[l]]
        p += counts[l]
    assert sum(len(v) for v in out.values()) == total, "placebo volume drifted from the rule's"
    return out


# ---------------------------------------------------------------------------------------
# Layer C Pass 1 with a pluggable relevance filter -- production functions inside
# ---------------------------------------------------------------------------------------

def p40_filter(tuning_layer_c):
    """The production filter, called through the production function."""
    from v2.layer_c import _relevance_filter

    def fn(clauses, vecs, positions, calls, pair_ids, info):
        return _relevance_filter(clauses, vecs, positions, calls, pair_ids, info,
                                 tuning_layer_c.milestone_relevance_percentile)
    return fn


def relative_filter(rule: str, param, scen_keys: list[str], S: np.ndarray,
                    ry: np.ndarray | None = None):
    """A per-clause relative rule as a drop-in for _relevance_filter. Same return shape,
    including the {clause_text: cos_to_own} dict production uses for relevance_mean."""
    pos_of = {k: i for i, k in enumerate(scen_keys)}

    def fn(clauses, vecs, positions, calls, pair_ids, info):
        own = pos_of[info["scenario_key"]]
        normed = unit_rows(vecs)
        sims = normed @ S.T
        rx = r_neighbourhood(sims, CSLS_NEIGHBOURHOOD) if rule == "csls" else None
        keep = np.flatnonzero(rule_mask(rule, param, sims, own, rx, ry))
        rel = sims[:, own]
        return ([clauses[i] for i in keep], vecs[keep],
                [positions[i] for i in keep], [calls[i] for i in keep],
                [pair_ids[i] for i in keep],
                {clauses[i]: float(rel[i]) for i in keep})
    return fn


def pass1_lcfr(info: dict, responses: list[dict], tuning, filter_fn,
               capture: bool = False) -> dict:
    """One scenario's Layer C Pass 1, production functions, pluggable filter.

    Mirrors layer_bc_arms.pass1 (itself mirroring v2/layer_c._pass1_cluster_scenario minus
    DB/checkpoint) so that the p40 setting can be F0-checked against the PUBLISHED control
    artifact -- if this function drifts from production, F0 fails and nothing here may be
    reported. Extras over that function (all additive, none touch the milestone outputs):

      candidates_pregate        every HDBSCAN cluster with its support, BEFORE the gate --
                                what T3's denominator flip-count and D1's flag rates read
      scenario_calls_effective  the T3 defect measurement: distinct calls contributing >=1
                                clause post-segmentation (and post-filter separately)
      _capture (opt-in)         post-filter clauses/vecs/calls/positions/labels + per-
                                candidate centroids, for the rescue and D1. Memory-only;
                                the artifact writer strips anything starting with "_".
    """
    from preprocessing import embedder
    from shared import cluster_evidence
    from v2.layer_c import build_clause_pool, _cluster_milestones

    out = {"n_responses": len(responses), "milestones": [], "outcome": None,
           "scenario_calls": len({r["call_filename"] for r in responses}),
           "n_clauses": 0, "n_clauses_after_relevance": 0,
           "scenario_calls_effective_preflt": None,
           "scenario_calls_effective_postflt": None,
           "candidates_pregate": [], "required_support": None}
    if len(responses) < 2:
        out["outcome"] = "fallback_too_few_responses"
        return out

    clauses, positions, calls, pair_ids = build_clause_pool(responses)
    out["n_clauses"] = len(clauses)
    out["scenario_calls_effective_preflt"] = len(set(calls))
    if len(clauses) < 6:
        out["outcome"] = "fallback_too_few_clauses"
        return out

    scenario_calls = out["scenario_calls"]
    vecs = embedder.embed_document_matrix(clauses)
    clauses, vecs, positions, calls, pair_ids, relevance = filter_fn(
        clauses, vecs, positions, calls, pair_ids, info)
    out["n_clauses_after_relevance"] = len(clauses)
    out["scenario_calls_effective_postflt"] = len(set(calls))
    if len(clauses) < 6:
        out["outcome"] = "fallback_too_few_relevant"
        return out

    mcs = cluster_evidence.milestone_min_cluster_size(
        len(clauses), tuning.min_cluster_size_fraction,
        tuning.min_cluster_size_floor, tuning.min_cluster_size_ceiling)
    labels = _cluster_milestones(vecs, mcs, tuning.umap_n_components)

    groups: dict[int, dict] = {}
    for i, label in enumerate(labels):
        if label == -1:
            continue
        g = groups.setdefault(int(label), {"idx": []})
        g["idx"].append(i)
    if not groups:
        out["outcome"] = "fallback_no_clusters"
        if capture:
            out["_capture"] = {"clauses": clauses, "vecs": vecs, "calls": calls,
                               "positions": positions, "labels": labels,
                               "relevance": relevance}
        return out

    required = cluster_evidence.required_milestone_support(
        scenario_calls, tuning.min_milestone_call_fraction, tuning.min_milestone_calls_floor)
    out["required_support"] = required

    candidates = []
    for label, g in groups.items():
        idx = g["idx"]
        cand_calls = [calls[i] for i in idx]
        cand = {"cluster_id": label,
                "clauses": [clauses[i] for i in idx],
                "support_calls": len(set(cand_calls)),
                "support_clauses": len(idx),
                "support_call_files": sorted(set(cand_calls)),
                "support_frac": len(set(cand_calls)) / max(scenario_calls, 1),
                "median_position": float(np.median([positions[i] for i in idx])),
                "relevance_mean": float(np.mean([relevance[clauses[i]] for i in idx]))}
        if capture:
            cand["_idx"] = idx
            cand["_centroid"] = cluster_evidence.milestone_cluster_centroid(vecs[idx])
        candidates.append(cand)
    out["candidates_pregate"] = [
        {k: v for k, v in c.items() if k != "clauses" and not k.startswith("_")}
        for c in candidates]

    surviving = [c for c in candidates if c["support_calls"] >= required]
    if not surviving:
        out["outcome"] = "fallback_no_support"
        if capture:
            out["_capture"] = {"clauses": clauses, "vecs": vecs, "calls": calls,
                               "positions": positions, "labels": labels,
                               "relevance": relevance, "candidates": candidates}
        return out

    if len(surviving) > tuning.milestone_hard_cap:
        print(f"  !! HARD CAP BOUND: {len(surviving)} > {tuning.milestone_hard_cap} -- "
              f"the support floor is miscalibrated.", flush=True)
        surviving.sort(key=lambda c: (-c["support_calls"], -c["relevance_mean"]))
        surviving = surviving[:tuning.milestone_hard_cap]

    out["outcome"] = "clustered"
    out["milestones"] = sorted(surviving, key=lambda m: m["median_position"])
    if capture:
        out["_capture"] = {"clauses": clauses, "vecs": vecs, "calls": calls,
                           "positions": positions, "labels": labels,
                           "relevance": relevance, "candidates": candidates}
    return out


# ---------------------------------------------------------------------------------------
# substrate
# ---------------------------------------------------------------------------------------

def load_substrate(taxonomy: str = "clean2_base", recordings: str = "recordings",
                   width: int = 3072, workers: int = 20) -> SimpleNamespace:
    """Taxonomy + pairs + production routing, embeddings served cache-only.

    Every arm in this trial shares ONE substrate object built in ONE process, so
    real-vs-permuted comparisons cannot differ in parse, routing or embedding lookups --
    the symmetric-filtering rule applied to the environment rather than to a metric.
    """
    from calibration.layer_bc_arms import (taxonomy_path, scenario_map_from_rows,
                                           install_embedder_shim, prewarm, build_pairs,
                                           corpus_sha, taxonomy_sha)
    from shared.scenario_vectors import scenario_text
    from shared.tuning import load_tuning
    from v1.layer_b import assign_scenarios

    tax = taxonomy_path(taxonomy)
    if not tax.exists():
        raise SystemExit(f"taxonomy artifact {tax.name} not found")
    art = json.loads(tax.read_text(encoding="utf-8-sig"))
    if art.get("incomplete"):
        raise SystemExit(f"{tax.name} is stamped INCOMPLETE -- not a usable substrate")

    scenario_map, cluster_of_key = scenario_map_from_rows(art["rows"])
    coachable = {k: v for k, v in scenario_map.items() if v["is_coachable"]}
    print(f"[substrate] {taxonomy}: {len(coachable)} coachable + "
          f"{len(scenario_map) - len(coachable)} sinks", flush=True)

    prewarm([scenario_text(v) for v in scenario_map.values()], workers)
    embed_calls = install_embedder_shim(width)

    pairs = build_pairs(recordings, "s0", "a0")
    print(f"[substrate] routing {len(pairs)} pairs with production assign_scenarios (r0)...",
          flush=True)
    assign_scenarios(pairs, scenario_map, None)

    by_key: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        k = p["scenario_key"]
        if k and scenario_map[k]["is_coachable"]:
            by_key[k].append(p)

    return SimpleNamespace(
        art=art, scenario_map=scenario_map, cluster_of_key=cluster_of_key,
        coachable=coachable, pairs=pairs, by_key=dict(by_key),
        corpus_sha=corpus_sha(pairs), taxonomy_sha=taxonomy_sha(scenario_map),
        tuning=load_tuning(), embed_calls=embed_calls, width=width,
        taxonomy_arm=taxonomy, recordings=recordings)


def permuted_by_key(sub, rng) -> dict[str, list[dict]]:
    """The mis-routed arm's pools: coachable-routed pairs, destinations permuted.
    Pair dicts are NOT mutated -- pools are separate lists over the same objects."""
    routed = [p for k in sorted(sub.by_key) for p in sub.by_key[k]]
    keys = [p["scenario_key"] for p in routed]
    perm = permute_destinations(keys, rng)
    by: dict[str, list[dict]] = defaultdict(list)
    for p, k in zip(routed, perm):
        by[k].append(p)
    return dict(by)


def coachable_matrix(sub) -> tuple[list[str], np.ndarray]:
    """Unit-row matrix of the coachable scenarios' vectors, in a stable key order."""
    from shared.scenario_vectors import build_scenario_vecs
    keys, vecs = build_scenario_vecs(sub.coachable)
    return keys, unit_rows(np.asarray(vecs, dtype=np.float32))


def provenance(sub, seed: int, extra: dict | None = None) -> dict:
    """The fields the Layer B trial's audit found missing from its own artifacts."""
    import datetime
    import os
    t = sub.tuning.layer_c
    d = {"started_at": datetime.datetime.now().isoformat(timespec="seconds"),
         "pid": os.getpid(), "seed": seed, "width": sub.width,
         "taxonomy_arm": sub.taxonomy_arm, "corpus_sha": sub.corpus_sha,
         "taxonomy_sha": sub.taxonomy_sha,
         "tuning": {"milestone_relevance_percentile": t.milestone_relevance_percentile,
                    "min_milestone_call_fraction": t.min_milestone_call_fraction,
                    "min_milestone_calls_floor": t.min_milestone_calls_floor,
                    "min_cluster_size_fraction": t.min_cluster_size_fraction,
                    "min_cluster_size_floor": t.min_cluster_size_floor,
                    "min_cluster_size_ceiling": t.min_cluster_size_ceiling,
                    "umap_n_components": t.umap_n_components,
                    "milestone_hard_cap": t.milestone_hard_cap,
                    "milestone_sink_similarity_percentile":
                        t.milestone_sink_similarity_percentile}}
    if extra:
        d.update(extra)
    return d


def write_arm_artifact(name: str, sub, per_scenario: dict, ident: dict) -> Path:
    """layer_bc_-prefixed so score_layer_b_arms.py scores it unchanged; lcfr_ infix so no
    published artifact can be clobbered. Underscore-prefixed keys are memory-only."""
    from calibration.layer_bc_arms import distribution_stats
    out_path = ARTIFACTS_DIR / f"layer_bc_lcfr_{name}.json"
    thin = {}
    for k, s in per_scenario.items():
        rec = {kk: vv for kk, vv in s.items() if not kk.startswith("_")}
        rec["milestones"] = [{mk: mv for mk, mv in m.items() if not mk.startswith("_")}
                             for m in rec.get("milestones", [])]
        rec["cluster_id"] = sub.cluster_of_key.get(k, "")
        thin[k] = rec
    stats = distribution_stats(thin, sub.tuning.layer_c.min_milestone_calls_floor)
    out_path.write_text(json.dumps({
        "arm": f"lcfr_{name}", "identity": ident, "chat_calls": 0,
        "stats": stats, "per_scenario": thin,
    }, indent=1, default=float), encoding="utf-8")
    print(f"[artifact] wrote {out_path.name}: {stats['n_milestones']} milestones over "
          f"{stats['n_scenarios']} scenarios", flush=True)
    return out_path
