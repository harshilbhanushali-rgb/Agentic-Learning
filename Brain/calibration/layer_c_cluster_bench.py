#!/usr/bin/env python3
"""LAYER C CLUSTERING-METHOD BENCH on the union corpus. Zero chat calls, zero Postgres.

Spec: docs/superpowers/specs/2026-08-17-layer-c-clustering-bench-design.md (arms and gates
frozen there BEFORE this ran). Stage 1: calibration/expanded_pool_stage1.py, whose artifact
is this bench's F0 reference AND its control arm.

ONE SUBSTRATE, EVERY ARM. Each scenario's post-p40 pool (clauses, vecs, calls, positions,
relevance) is built ONCE with production functions and handed to every arm's labeler; the
support gate and milestone construction are ONE shared function. An arm can differ from the
incumbent only in the labels array it returns — symmetric filtering by construction.

F0-BENCH: the substrate's per-scenario post-filter clause pools must be list-identical to
`layer_bc_xp_union.json`'s `clause_pool` (stage 1 ran in a different process; Layer C Pass 1
is documented deterministic across processes on cached embeddings, so any diff is a harness
bug). F0-SEED: the seed-parameterised paraphrase `_cluster_milestones_seeded` must reproduce
production `_cluster_milestones`' labels EXACTLY at seed 42 — checked per scenario, and the
seed-jitter arms are VOID if it ever fails, while `c0` (which calls production itself) stands.

W5 PROCEDURE (frozen pre-run, per the audit): a stability re-run at base seed b needs c0
itself at that base (the comparison reference), the surviving treatment arms, AND rescue_plc
if rescue survived. The PARTITIONER W2 floor at a non-42 base is THE BASE-42 SEED-JITTER
FLOOR, loaded from the base-42 report — the floor is a property of the incumbent's seed
sensitivity, defined once; jitter arms exist only at base 42 by construction. Leiden has no
UMAP dependence, so its W5 variant re-runs with PARTITION seed = --base-seed.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/layer_c_cluster_bench.py --run
    ..\\.venv\\Scripts\\python.exe calibration/layer_c_cluster_bench.py --score
    # W5 for survivors (example: hdb_half and rescue survived W1-W3):
    ..\\.venv\\Scripts\\python.exe calibration/layer_c_cluster_bench.py --run --base-seed 1 \
        --arms c0,hdb_half,rescue,rescue_plc
    ..\\.venv\\Scripts\\python.exe calibration/layer_c_cluster_bench.py --score --base-seed 1
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402
from calibration.lcfr_common import unit_rows, rescue_assign, placebo_assign  # noqa: E402

STAGE1_ARTIFACT = ARTIFACTS_DIR / "layer_bc_xp_union.json"


def report_path(base_seed: int) -> Path:
    suffix = "" if base_seed == SEED else f"_b{base_seed}"
    return ARTIFACTS_DIR / f"layer_c_bench_report{suffix}.json"
WIDTH = 3072
SEED = 42
JITTER_SEEDS = (1, 7)
LEIDEN_KNN = 15
LEIDEN_GRID = tuple(10.0 ** e for e in range(-6, 2))   # 1e-6 .. 1e1, frozen in the spec
ALL_ARMS = ("c0", "c0_s1", "c0_s7", "agglo", "leiden", "hdb_half", "hdb_dbl",
            "hdb_raw", "rescue", "rescue_plc")


def arm_path(arm: str, base_seed: int) -> Path:
    suffix = "" if base_seed == SEED else f"_b{base_seed}"
    return ARTIFACTS_DIR / f"layer_bc_cb_{arm}{suffix}.json"


# ---------------------------------------------------------------------------------------
# pure functions (unit-tested in tests/test_layer_c_cluster_bench.py)
# ---------------------------------------------------------------------------------------

def noise_rate(labels: np.ndarray) -> float:
    """Share of the pool assigned to no cluster. 0.0 for no-noise-class arms — W1 is then
    trivially true and the spec says the arm's case rests on W2-W5."""
    labels = np.asarray(labels)
    return float((labels == -1).sum() / len(labels)) if len(labels) else float("nan")


def milestones_from_labels(labels, clauses: list[str], calls: list[str],
                           positions: list, relevance: dict[str, float],
                           scenario_calls: int, required: int) -> tuple[list[dict], list[dict]]:
    """THE ONE support gate for every arm. Returns (surviving, candidates_pregate).

    Mirrors production's candidate construction (pass1_lcfr's loop) field-for-field so the
    bench's milestone records are comparable to stage 1's — same keys, same definitions,
    support as DISTINCT calls, support_frac over the scenario's own call count.
    """
    groups: dict[int, list[int]] = defaultdict(list)
    for i, label in enumerate(np.asarray(labels)):
        if label == -1:
            continue
        groups[int(label)].append(i)
    candidates = []
    for label in sorted(groups):
        idx = groups[label]
        cand_calls = [calls[i] for i in idx]
        candidates.append({
            "cluster_id": label,
            "clauses": [clauses[i] for i in idx],
            "support_calls": len(set(cand_calls)),
            "support_clauses": len(idx),
            "support_call_files": sorted(set(cand_calls)),
            "support_frac": len(set(cand_calls)) / max(scenario_calls, 1),
            "median_position": float(np.median([positions[i] for i in idx])),
            "relevance_mean": float(np.mean([relevance[clauses[i]] for i in idx])),
        })
    surviving = sorted((c for c in candidates if c["support_calls"] >= required),
                       key=lambda m: m["median_position"])
    return surviving, candidates


def pick_gamma(counts_by_gamma: dict[float, int], target: int) -> tuple[float, bool]:
    """The frozen leiden granularity rule: the SMALLEST gamma whose community count reaches
    the incumbent's cluster count. Returns (gamma, endpoint_flag) — the Layer A lesson: a
    rule applied to a truncated domain silently returns the edge of the grid, so landing on
    an endpoint is WARNED, never silent."""
    gammas = sorted(counts_by_gamma)
    for g in gammas:
        if counts_by_gamma[g] >= target:
            return g, g == gammas[0]
    return gammas[-1], True


def rescue_labels(base_labels: np.ndarray, admitted: dict[int, list[int]],
                  noise_idx: list[int]) -> np.ndarray:
    """Apply a rescue/placebo admission map to a labels array. `admitted` maps cluster label
    -> row indices INTO THE NOISE SUBSET (rescue_assign's contract); translate and assert no
    admitted row was already clustered."""
    out = np.asarray(base_labels).copy()
    for label, rows in admitted.items():
        for r in rows:
            i = noise_idx[r]
            assert out[i] == -1, f"admission targeted a non-noise row {i}"
            out[i] = label
    return out


# ---------------------------------------------------------------------------------------
# labelers — each returns (labels, diag). Everything else is shared.
# ---------------------------------------------------------------------------------------

def _cluster_milestones_seeded(vecs: np.ndarray, min_cluster_size: int,
                               n_components_ceiling: int, seed: int) -> np.ndarray:
    """Seed-parameterised paraphrase of production `_cluster_milestones` — SAME constructors,
    same arguments, only `random_state` varies. F0-SEED (run_bench) proves it reproduces
    production exactly at seed 42 before any jitter arm is trusted."""
    import umap
    from hdbscan import HDBSCAN

    n_components = min(n_components_ceiling, max(2, vecs.shape[0] - 2))
    reducer = umap.UMAP(n_components=n_components, metric="cosine", random_state=seed)
    reduced = reducer.fit_transform(vecs)
    clusterer = HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean",
                        cluster_selection_method="eom")
    return clusterer.fit_predict(reduced)


def agglo_labels(vecs: np.ndarray, n_clusters: int) -> np.ndarray:
    from sklearn.cluster import AgglomerativeClustering
    n_clusters = max(1, min(n_clusters, vecs.shape[0]))
    model = AgglomerativeClustering(n_clusters=n_clusters, metric="cosine",
                                    linkage="average")
    return model.fit_predict(unit_rows(vecs))


def leiden_communities(vecs: np.ndarray, gamma: float, seed: int,
                       knn_k: int = LEIDEN_KNN) -> np.ndarray:
    import igraph
    import leidenalg

    V = unit_rows(vecs)
    n = V.shape[0]
    k = min(knn_k, n - 1)
    sims = V @ V.T
    np.fill_diagonal(sims, -np.inf)
    nbr = np.argpartition(-sims, k - 1, axis=1)[:, :k]
    edges, weights = [], []
    seen = set()
    for i in range(n):
        for j in nbr[i]:
            j = int(j)
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            edges.append(key)
            weights.append(max(float(sims[i, j]), 1e-6))  # CPM needs positive weights
    g = igraph.Graph(n=n, edges=edges)
    part = leidenalg.find_partition(g, leidenalg.CPMVertexPartition,
                                    resolution_parameter=gamma, weights=weights,
                                    seed=seed, n_iterations=2)
    return np.asarray(part.membership)


def hdb_raw_labels(vecs: np.ndarray, mcs: int) -> np.ndarray:
    from hdbscan import HDBSCAN
    clusterer = HDBSCAN(min_cluster_size=mcs, metric="euclidean",
                        cluster_selection_method="eom")
    return clusterer.fit_predict(unit_rows(vecs).astype(np.float64))


# ---------------------------------------------------------------------------------------
# the bench
# ---------------------------------------------------------------------------------------

def build_substrate(smoke: bool = False):
    """Stage 1's substrate, rebuilt in-process with the same production functions, plus the
    per-clause capture every arm needs. F0-bench asserts it against the stage-1 artifact."""
    from calibration.layer_bc_arms import (taxonomy_path, scenario_map_from_rows,
                                           install_embedder_shim, prewarm, build_pairs,
                                           parse_corpus, corpus_sha, taxonomy_sha)
    from calibration.expanded_pool_stage1 import (OLD_DIR, NEW_DIR, TAXONOMY,
                                                  assert_no_stem_collision)
    from calibration.lcfr_common import pass1_lcfr, p40_filter
    from shared.scenario_vectors import scenario_text
    from shared.tuning import load_tuning
    from v1.layer_b import assign_scenarios

    stage1 = json.loads(STAGE1_ARTIFACT.read_text(encoding="utf-8-sig"))
    if not stage1.get("f0_union", {}).get("pass"):
        raise SystemExit("stage-1 artifact failed its own F0 — the bench has no valid "
                         "reference; fix stage 1 first")

    tax_art = json.loads(taxonomy_path(TAXONOMY).read_text(encoding="utf-8-sig"))
    scenario_map, cluster_of_key = scenario_map_from_rows(tax_art["rows"])
    coachable = {k: v for k, v in scenario_map.items() if v["is_coachable"]}

    parsed_old = parse_corpus(OLD_DIR)
    parsed_new = parse_corpus(NEW_DIR)
    if smoke:
        parsed_old, parsed_new = parsed_old[:25], parsed_new[:25]
        print("[SMOKE] corpus sliced to 25+25 calls — PATH TEST ONLY", flush=True)
    assert_no_stem_collision({p.stem for _, p, _ in parsed_old},
                             {p.stem for _, p, _ in parsed_new})
    pairs = (build_pairs(OLD_DIR, "s0", "a0", parsed=parsed_old)
             + build_pairs(NEW_DIR, "s0", "a0", parsed=parsed_new))

    prewarm([scenario_text(v) for v in scenario_map.values()], 20)
    install_embedder_shim(WIDTH)
    print(f"[substrate] routing {len(pairs)} pairs (production r0)...", flush=True)
    assign_scenarios(pairs, scenario_map, None)

    by_key: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        k = p["scenario_key"]
        if k and scenario_map[k]["is_coachable"]:
            by_key[k].append(p)

    tuning = load_tuning()
    return {"stage1": stage1, "coachable": coachable, "by_key": dict(by_key),
            "cluster_of_key": cluster_of_key, "tuning": tuning,
            "corpus_sha": corpus_sha(pairs), "taxonomy_sha": taxonomy_sha(scenario_map),
            "pass1_lcfr": pass1_lcfr, "p40_filter": p40_filter}


def run_bench(arms: list[str], base_seed: int, overwrite: bool,
              smoke: bool = False) -> None:
    from shared import cluster_evidence

    if not smoke:
        for arm in arms:
            p = arm_path(arm, base_seed)
            if p.exists() and not overwrite:
                raise SystemExit(f"{p.name} exists — pass --overwrite or drop the arm")

    sub = build_substrate(smoke)
    tuning = sub["tuning"].layer_c
    filt = sub["p40_filter"](tuning)
    stage1_ps = sub["stage1"]["per_scenario"]

    per_arm: dict[str, dict] = {a: {} for a in arms}
    diags: dict[str, dict] = {a: {} for a in arms}
    f0_bench_fail, f0_seed_fail = [], []
    rng = np.random.default_rng(SEED)
    t0 = time.time()

    todo = sorted(sub["coachable"].items())
    if smoke:
        todo = todo[:2]
        print("[SMOKE] 2 scenarios only; F0-bench reported but NOT gating on a sliced "
              "corpus; NO artifacts will be written", flush=True)
    for n, (key, info) in enumerate(todo, 1):
        responses = sub["by_key"].get(key, [])
        res = sub["pass1_lcfr"](info, responses, tuning, filt, capture=True)
        cap = res.pop("_capture", None)
        base_rec = {k: v for k, v in res.items()
                    if k in ("n_responses", "scenario_calls", "n_clauses",
                             "n_clauses_after_relevance", "required_support", "outcome")}
        base_rec["cluster_id"] = sub["cluster_of_key"].get(key, "")

        # F0-bench: this process's post-filter pool must equal stage 1's.
        s1_pool = (stage1_ps.get(key) or {}).get("clause_pool", [])
        cap_clauses = list(cap["clauses"]) if cap else []
        if cap_clauses != s1_pool:
            f0_bench_fail.append(key)

        if not cap or res["outcome"] in ("fallback_too_few_responses",
                                         "fallback_too_few_clauses",
                                         "fallback_too_few_relevant"):
            for a in arms:
                per_arm[a][key] = {**base_rec, "milestones": [],
                                   "noise_rate": float("nan")}
            print(f"  [{n}/{len(todo)}] {key[:40]:<40} ({res['outcome']}) — skipped",
                  flush=True)
            continue

        clauses, vecs = cap["clauses"], np.asarray(cap["vecs"], dtype=np.float32)
        calls, positions, relevance = cap["calls"], cap["positions"], cap["relevance"]
        scenario_calls = res["scenario_calls"]
        required = cluster_evidence.required_milestone_support(
            scenario_calls, tuning.min_milestone_call_fraction,
            tuning.min_milestone_calls_floor)
        mcs = cluster_evidence.milestone_min_cluster_size(
            len(clauses), tuning.min_cluster_size_fraction,
            tuning.min_cluster_size_floor, tuning.min_cluster_size_ceiling)

        # Base labels for this base seed. At base 42 they are PRODUCTION'S OWN OUTPUT —
        # pass1_lcfr's capture carries the labels array its internal production
        # `_cluster_milestones` call produced, so c0 is production verbatim with no second
        # UMAP run to drift from it.
        base_labels = (np.asarray(cap["labels"])
                       if base_seed == SEED else
                       _cluster_milestones_seeded(vecs, mcs, tuning.umap_n_components,
                                                  base_seed))
        c0_count = len(set(int(x) for x in base_labels) - {-1})

        def emit(arm: str, labels, extra: dict | None = None):
            ms, cands = milestones_from_labels(labels, clauses, calls, positions,
                                               relevance, scenario_calls, required)
            # Production caps surviving milestones (never bound historically); the bench
            # does not truncate — symmetric across arms — but a bind must be LOUD, because
            # hdb_half doubles cluster counts by design (audit finding 6).
            capped = len(ms) > tuning.milestone_hard_cap
            if capped:
                print(f"    !! {arm}/{key}: {len(ms)} milestones EXCEEDS hard cap "
                      f"{tuning.milestone_hard_cap} — production would truncate; bench "
                      f"does not (symmetric). Flagged.", flush=True)
            rec = {**base_rec,
                   "outcome": ("clustered" if ms else
                               "fallback_no_support" if cands else "fallback_no_clusters"),
                   "milestones": ms, "noise_rate": noise_rate(labels),
                   "n_candidates_pregate": len(cands), "hard_cap_exceeded": capped}
            if extra:
                rec.update(extra)
            per_arm[arm][key] = rec

        def emit_skipped(arm: str, why: str):
            per_arm[arm][key] = {**base_rec, "outcome": why, "milestones": [],
                                 "noise_rate": float("nan"), "skipped": True}

        for arm in arms:
            if arm == "c0":
                emit("c0", base_labels)
            elif arm in ("c0_s1", "c0_s7"):
                seed = int(arm.rsplit("_s", 1)[1])
                lab = _cluster_milestones_seeded(vecs, mcs, tuning.umap_n_components, seed)
                emit(arm, lab)
            elif arm == "agglo":
                # The frozen rule is n_clusters = c0's count; a clamp 0->1 would hand agglo
                # one whole-pool cluster exactly where the incumbent failed (audit finding
                # 5) — a gained milestone manufactured by the clamp, not the method.
                if c0_count == 0:
                    emit_skipped("agglo", "skipped_c0_zero_clusters")
                else:
                    emit("agglo", agglo_labels(vecs, c0_count),
                         {"n_clusters_used": max(1, min(c0_count, len(clauses)))})
            elif arm == "leiden":
                if c0_count == 0:
                    emit_skipped("leiden", "skipped_c0_zero_clusters")
                    continue
                counts = {}
                labs = {}
                for g in LEIDEN_GRID:
                    # partition seed = base_seed so leiden's W5 variant is runnable via the
                    # same flag (leiden has no UMAP dependence; audit finding 4)
                    lab = leiden_communities(vecs, g, base_seed)
                    labs[g] = lab
                    counts[g] = len(set(lab.tolist()))
                g, endpoint = pick_gamma(counts, c0_count)
                if endpoint:
                    print(f"    !! leiden gamma landed on a GRID ENDPOINT ({g}) for {key}",
                          flush=True)
                emit("leiden", labs[g], {"gamma": g, "gamma_endpoint": endpoint})
            elif arm == "hdb_half":
                emit("hdb_half", _cluster_milestones_seeded(
                    vecs, max(3, mcs // 2), tuning.umap_n_components, base_seed),
                    {"mcs_used": max(3, mcs // 2)})
            elif arm == "hdb_dbl":
                emit("hdb_dbl", _cluster_milestones_seeded(
                    vecs, mcs * 2, tuning.umap_n_components, base_seed),
                    {"mcs_used": mcs * 2})
            elif arm == "hdb_raw":
                emit("hdb_raw", hdb_raw_labels(vecs, mcs), {"mcs_used": mcs})
            elif arm in ("rescue", "rescue_plc"):
                noise_idx = [i for i, l in enumerate(base_labels) if l == -1]
                members = {int(l): vecs[[i for i, x in enumerate(base_labels) if x == l]]
                           for l in set(int(x) for x in base_labels) if l != -1}
                if arm == "rescue":
                    admitted, _thr = rescue_assign(vecs[noise_idx], members)
                else:
                    real_adm, _ = rescue_assign(vecs[noise_idx], members)
                    admitted = placebo_assign({l: len(v) for l, v in real_adm.items()},
                                              len(noise_idx),
                                              np.random.default_rng(SEED + 1))
                emit(arm, rescue_labels(base_labels, admitted, noise_idx),
                     {"n_admitted": sum(len(v) for v in admitted.values())})
            else:
                raise SystemExit(f"unknown arm {arm!r}")

        # F0-SEED: the paraphrase must reproduce production at seed 42, this scenario.
        if base_seed == SEED:
            para = _cluster_milestones_seeded(vecs, mcs, tuning.umap_n_components, SEED)
            if not np.array_equal(para, base_labels):
                f0_seed_fail.append(key)

        got = {a: len(per_arm[a][key]["milestones"]) for a in arms}
        print(f"  [{n}/{len(todo)}] {key[:36]:<36} {len(clauses):>5}cl req={required} "
              + " ".join(f"{a}:{v}" for a, v in got.items()), flush=True)

    ident = {"started_at": datetime.datetime.now().isoformat(timespec="seconds"),
             "pid": os.getpid(), "base_seed": base_seed, "width": WIDTH,
             "corpus_sha": sub["corpus_sha"], "taxonomy_sha": sub["taxonomy_sha"],
             "stage1_artifact": STAGE1_ARTIFACT.name,
             "f0_bench_fail": f0_bench_fail, "f0_seed_fail": f0_seed_fail,
             "tuning": {k: getattr(tuning, k) for k in
                        ("milestone_relevance_percentile", "min_milestone_call_fraction",
                         "min_milestone_calls_floor", "min_cluster_size_fraction",
                         "min_cluster_size_floor", "min_cluster_size_ceiling",
                         "umap_n_components", "milestone_hard_cap")}}

    from calibration.layer_bc_arms import distribution_stats
    for arm in arms:
        ps = per_arm[arm]
        stats = distribution_stats(ps, tuning.min_milestone_calls_floor)
        nr = [r["noise_rate"] for r in ps.values() if r["noise_rate"] == r["noise_rate"]]
        if smoke:
            print(f"[SMOKE] arm {arm}: {stats['n_milestones']} ms — not written", flush=True)
            continue
        arm_path(arm, base_seed).write_text(json.dumps({
            "arm": f"cb_{arm}", "identity": ident, "chat_calls": 0,
            "noise_rate_mean": float(np.mean(nr)) if nr else float("nan"),
            "stats": stats, "per_scenario": ps,
        }, indent=1, default=float), encoding="utf-8")
        print(f"[artifact] {arm_path(arm, base_seed).name}: {stats['n_milestones']} ms, "
              f"noise {float(np.mean(nr))*100 if nr else float('nan'):.1f}%", flush=True)

    print(f"\nF0-bench: {'PASS' if not f0_bench_fail else f'** FAIL {f0_bench_fail} **'}"
          + ("  (smoke: informational only)" if smoke else ""))
    print(f"F0-seed:  {'PASS' if not f0_seed_fail else f'** FAIL {f0_seed_fail} — jitter arms VOID **'}")
    print(f"done in {(time.time()-t0)/60:.1f} min. ZERO chat calls, ZERO Postgres writes.")


# ---------------------------------------------------------------------------------------
# --score: gates W1-W3 from artifacts, free
# ---------------------------------------------------------------------------------------

def score(base_seed: int) -> None:
    from calibration import layer_b_arms as lb
    from calibration.layer_bc_arms import match_milestones
    from calibration.expanded_pool_stage1 import (merge_account_maps, OLD_DIR, NEW_DIR,
                                                  UNION_WEIGHTS)
    from calibration.flag_proper_noun_clusters import account_map

    arts = {}
    for arm in ALL_ARMS:
        p = arm_path(arm, base_seed)
        if p.exists():
            arts[arm] = json.loads(p.read_text(encoding="utf-8-sig"))
    if "c0" not in arts:
        raise SystemExit("no c0 artifact at this base seed — run the bench first "
                         "(a W5 re-run must include c0 in --arms: it is the reference)")
    c0 = arts["c0"]
    ident = c0["identity"]
    if ident["f0_bench_fail"]:
        raise SystemExit(f"F0-bench failed on {ident['f0_bench_fail']} — nothing reportable")

    # F0-SEED voids the jitter arms (audit finding 1): if the seeded paraphrase drifted from
    # production, c0_s1/c0_s7 measure paraphrase drift, not seed jitter, and must not set
    # the W2 floor every partitioner arm is judged against.
    if ident.get("f0_seed_fail"):
        print(f"  !! F0-SEED failed on {ident['f0_seed_fail']} — jitter arms are VOID; "
              f"the partitioner W2 floor is unavailable this run", flush=True)
        arts.pop("c0_s1", None)
        arts.pop("c0_s7", None)

    # Artifacts from different substrates must never be paired (audit finding 2): the pull
    # dir changed twice in one week, and --arms/--overwrite make partial re-runs a designed
    # workflow, so a mixed-corpus score is a live hazard, not a hypothetical.
    for name, art in arts.items():
        for fld in ("corpus_sha", "taxonomy_sha"):
            if art["identity"].get(fld) != ident.get(fld):
                raise SystemExit(
                    f"ABORT: arm {name!r} was run on a different substrate "
                    f"({fld} {art['identity'].get(fld)} vs c0's {ident.get(fld)}). "
                    f"Re-run the stale arm; scoring across corpora would report a corpus "
                    f"diff as an arm effect.")

    acct_old_raw, _ = account_map(OLD_DIR)
    acct_new_raw, _ = account_map(NEW_DIR)
    if not acct_old_raw or not acct_new_raw:
        raise SystemExit("ABORT: an account map came back empty — wrong path or missing "
                         ".speakers.json sidecars; every cluster would score NaN and the "
                         "sign test would report a manufactured null.")
    acct_union, _ = lb.collapse_sibling_domains(
        merge_account_maps([acct_old_raw, acct_new_raw]))
    w_union = json.loads(UNION_WEIGHTS.read_text(encoding="utf-8-sig"))
    pool = lb.corpus_account_pool(acct_union, w_union["weights"])
    ks = lb.union_cluster_ks([a["per_scenario"] for a in arts.values()], acct_union)
    table = lb.expected_neff_table(pool, ks, trials=20_000, seed=SEED)

    st = {a: lb.per_cluster_stats(arts[a]["per_scenario"], acct_union, table)
          for a in arts}

    # the seed-jitter merge floor for partitioner arms (W2). At a non-42 base the jitter
    # arms do not exist by construction; the floor is THE BASE-42 FLOOR, loaded from the
    # base-42 report — frozen pre-run (see module docstring, W5 PROCEDURE).
    jitter_merged = []
    for j in ("c0_s1", "c0_s7"):
        if j in arts:
            m = 0
            for key, brec in c0["per_scenario"].items():
                arec = arts[j]["per_scenario"].get(key) or {}
                outs, _ = match_milestones(brec.get("milestones") or [],
                                           arec.get("milestones") or [],
                                           brec.get("scenario_calls") or 0,
                                           arec.get("scenario_calls") or 0)
                m += sum(1 for o in outs if o["outcome"] == "merged")
            jitter_merged.append(m)
    merge_floor = max(jitter_merged) if jitter_merged else None
    if merge_floor is None and base_seed != SEED:
        base_report = report_path(SEED)
        if not base_report.exists():
            raise SystemExit("W5 scoring needs the base-42 report for the jitter merge "
                             "floor — run --score at base 42 first")
        merge_floor = json.loads(base_report.read_text(
            encoding="utf-8-sig")).get("merge_floor_jitter")
        print(f"  W2 floor loaded from base-42 report: {merge_floor}", flush=True)

    print("=" * 110)
    print(f"LAYER C CLUSTERING BENCH — base seed {base_seed}  "
          f"(spec 2026-08-17-layer-c-clustering-bench)")
    print("=" * 110)
    print(f"  c0: {c0['stats']['n_milestones']} ms, noise {c0['noise_rate_mean']*100:.1f}%   "
          f"seed-jitter merge floor: {merge_floor}")
    print(f"\n  {'arm':<12}{'miles':>7}{'noise%':>8}{'match':>7}{'merged':>7}{'split':>7}"
          f"{'lost':>6}{'gained':>7}{'lift up/dn':>12}{'p':>9}{'W1':>4}{'W2':>4}{'W3':>4}")

    # Pass 1: accounting for every arm (so rescue's W2 floor — its placebo's merged count —
    # exists before rescue's gate is evaluated, regardless of registry order).
    rows = {}
    for arm in [a for a in ALL_ARMS if a in arts and a != "c0"]:
        art = arts[arm]
        oc = Counter()
        gained_n = 0
        for key, brec in c0["per_scenario"].items():
            arec = art["per_scenario"].get(key) or {}
            outs, gained = match_milestones(brec.get("milestones") or [],
                                            arec.get("milestones") or [],
                                            brec.get("scenario_calls") or 0,
                                            arec.get("scenario_calls") or 0)
            for o in outs:
                oc[o["outcome"]] += 1
            gained_n += len(gained)
        d = lb.compare_arms(st["c0"], st[arm], "lift")
        rows[arm] = {"merged": oc["merged"], "matched": oc["matched"],
                     "split": oc["split"], "lost": oc["lost"], "gained": gained_n,
                     "lift": d, "noise": art["noise_rate_mean"],
                     "milestones": art["stats"]["n_milestones"]}

    # Pass 2: gates, now that every floor exists.
    for arm, r in rows.items():
        d = r["lift"]
        r["w1"] = r["noise"] < c0["noise_rate_mean"]
        floor = (rows.get("rescue_plc", {}).get("merged") if arm == "rescue"
                 else merge_floor)
        r["w2"] = (r["merged"] <= floor) if floor is not None else None
        r["w3"] = not (d["down"] > d["up"] and d["p"] < 0.05)
        print(f"  {arm:<12}{r['milestones']:>7}{r['noise']*100:>8.1f}{r['matched']:>7}"
              f"{r['merged']:>7}{r['split']:>7}{r['lost']:>6}{r['gained']:>7}"
              f"{d['up']:>6}/{d['down']:<5}{d['p']:>9.4f}"
              f"{'  Y' if r['w1'] else '  n':>4}"
              f"{('  Y' if r['w2'] else '  n') if r['w2'] is not None else '  ?':>4}"
              f"{'  Y' if r['w3'] else '  n':>4}")

    print(f"\n  W2 floors: partitioners <= seed-jitter max ({merge_floor}); "
          f"rescue <= its placebo ({rows.get('rescue_plc', {}).get('merged')})")
    print("  W4 (blind read) runs only for arms clearing W1-W3; W5 = re-run survivors "
          f"at base seeds {JITTER_SEEDS}.")

    rp = report_path(base_seed)
    rp.write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "base_seed": base_seed, "merge_floor_jitter": merge_floor,
        "c0": {"milestones": c0["stats"]["n_milestones"],
               "noise": c0["noise_rate_mean"]},
        "arms": rows,
    }, indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {rp.name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", action="store_true")
    p.add_argument("--score", action="store_true")
    p.add_argument("--smoke", action="store_true",
                   help="end-to-end PATH TEST: 25+25 calls, 2 scenarios, nothing written")
    p.add_argument("--arms", default=",".join(ALL_ARMS))
    p.add_argument("--base-seed", type=int, default=SEED)
    p.add_argument("--overwrite", action="store_true")
    a = p.parse_args()
    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    bad = [x for x in arms if x not in ALL_ARMS]
    if bad:
        raise SystemExit(f"unknown arm(s) {bad}; registry: {ALL_ARMS}")
    if a.base_seed != SEED:
        drop = [x for x in arms if x in ("c0_s1", "c0_s7")]
        if drop:
            raise SystemExit("jitter arms are defined relative to base 42 only")
    if a.run or a.smoke:
        run_bench(arms, a.base_seed, a.overwrite, smoke=a.smoke)
    if a.score:
        score(a.base_seed)
    if not (a.run or a.score or a.smoke):
        p.print_help()


if __name__ == "__main__":
    main()
