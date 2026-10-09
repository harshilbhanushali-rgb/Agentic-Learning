#!/usr/bin/env python3
"""Benchmark alternative Layer A clusterings on ONE scale. Free, read-only, no writes.

Spec: docs/superpowers/specs/2026-08-16-layer-a-clustering-method-design.md (PRE-REGISTERED
before any arm ran; the P-arm selection rule was frozen before the diagnostic probes were
read). Diagnostic that motivated the arms: calibration/diagnose_layer_a_noise.py.

THE GATE: label-transferred `share_fixed`. Every arm's clusters are mapped to the incumbent's
148 keys (sinks included) by PLURALITY of their members' incumbent labels; coachable
populations are scored with null_test_taxonomy's length-matched null and graded against the
FROZEN incumbent control reference (size-conditional). The incumbent passed through the same
pipeline is the identity map, asserted (F2). Verdicts F1-F7 are evaluated in code in
--report, never by eye.

Processes (one heavy fit per process -- two UMAP fits in one process is the documented
memory failure on this machine):
    --stage flags                          spaCy-only: persist content-free flags
    --arms incumbent,placebo_shuffle,rescue_soft     1 UMAP fit; persists control + sidecars
    --arms p_eps075,p_ms2,p_eps050         0 fits (loads the persisted UMAP-42 space)
    --arms leiden_knn,rescue_centroid,rescue_placebo 0 fits
    --stage mirror                         1 fit: seed-42 mirror == production (gates jitters)
    --arms jitter_s1                       1 fit
    --arms jitter_s7                       1 fit
    --arms agglo_cosine                    own process, ~2.3 GB condensed matrix
    --report                               verdicts + tables, free

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/clustering_bench.py --stage flags
    ..\\.venv\\Scripts\\python.exe calibration/clustering_bench.py --arms incumbent,placebo_shuffle,rescue_soft
    ..\\.venv\\Scripts\\python.exe calibration/clustering_bench.py --report
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OUT = ARTIFACTS_DIR / "clustering_bench.json"
# Cluster MEMBERSHIPS live in their own sidecar, not in OUT: the spec's reading requirement
# needs them for whichever arm wins, and re-running a heavy arm just to read it would be both
# expensive and a different fit. Kept separate so OUT stays small enough to diff by eye.
MEMBERS_OUT = ARTIFACTS_DIR / "clustering_bench_members.json"
FLAGS_OUT = ARTIFACTS_DIR / "turn_content_free.json"
UMAP42_NPY = ARTIFACTS_DIR / "clustering_bench_umap42.npy"
ADJ_NAME = "adjudicate_gemini_min16.json"
SEED = 42
MIN_CLUSTER_SIZE = 16
MIN_SAMPLES = max(2, MIN_CLUSTER_SIZE // 3)          # production formula = 5
MERGE = 0.97
K_GRAPH = 15                 # kNN graph degree, matched to production's UMAP n_neighbors
SIZE_FLOOR = 16              # community size floor = the incumbent's own min_cluster_size
# CPM's gamma is compared against INTRA-COMMUNITY EDGE WEIGHT DENSITY, so the useful range
# depends on the cosine scale of the graph's weights and cannot be guessed. A 500-vector probe
# shattered from 2 communities to 0 across one decade, so the grid spans seven and the run
# WARNS if the selection rule lands on an endpoint -- a rule applied to a truncated domain
# silently returns the edge of the grid instead of the point it was asked for. The RULE
# (count closest to TARGET_GRANULARITY) is what the spec froze; the domain must merely contain
# the point it selects.
GAMMA_GRID = [float(g) for g in np.logspace(-6, 1, 29)]
TARGET_GRANULARITY = 245     # incumbent surviving-cluster count, for CPM scale-matching
CHUNK = 2048

# The three P arms. `p_eps075` is what the frozen selection rule picked (max noise reduction
# s.t. junk clusters <= baseline+25% and raw count in [100, 600]); ms2/eps050 are the named
# exploratory arms. Epsilon values are the diagnostic's own data-derived core-distance
# percentiles, recorded here as literals and re-asserted against its artifact at run time.
P_ARMS = {
    "p_eps075": {"min_samples": MIN_SAMPLES, "method": "eom", "eps_key": "core_p75"},
    "p_eps050": {"min_samples": MIN_SAMPLES, "method": "eom", "eps_key": "core_p50"},
    "p_ms2": {"min_samples": 2, "method": "eom", "eps_key": None},
}

STOCHASTIC = frozenset({"leiden_knn"})   # F5 applies; UMAP jitters ARE the seed probes


# ---------------------------------------------------------------------------------------
# pure helpers (covered by tests/test_clustering_bench.py)
# ---------------------------------------------------------------------------------------

def plurality_transfer(arm_clusters: list[list[int]], truth_key: dict[int, str]
                       ) -> list[str | None]:
    """Map each arm cluster to the incumbent key holding the plurality of its labeled
    members. Ties break to the lexicographically smallest key (determinism). A cluster with
    zero labeled members maps to None. No mapped-fraction floor -- dilution is the gate's
    job to punish, not this function's."""
    out: list[str | None] = []
    for idxs in arm_clusters:
        counts = Counter(truth_key[i] for i in idxs if i in truth_key)
        if not counts:
            out.append(None)
            continue
        best = max(counts.values())
        out.append(min(k for k, v in counts.items() if v == best))
    return out


def populations(arm_clusters: list[list[int]], mapped: list[str | None],
                coach_of_key: dict[str, bool]) -> dict[str, list[int]]:
    """Coachable population per key = union of member turns of clusters mapped to it."""
    pops: dict[str, list[int]] = defaultdict(list)
    for idxs, key in zip(arm_clusters, mapped):
        if key is not None and coach_of_key.get(key, False):
            pops[key].extend(idxs)
    return dict(pops)


def shuffle_partition(sizes: list[int], member_pool: list[int],
                      rng: random.Random) -> list[list[int]]:
    """Random partition of `member_pool` into groups of the given sizes (F1 placebo)."""
    if sum(sizes) != len(member_pool):
        raise ValueError(f"sizes sum {sum(sizes)} != pool {len(member_pool)}")
    pool = list(member_pool)
    rng.shuffle(pool)
    out, at = [], 0
    for s in sizes:
        out.append(pool[at:at + s])
        at += s
    return out


def volume_matched_rescue(counts: list[int], noise_pool: list[int],
                          rng: random.Random) -> list[list[int]]:
    """Rescue placebo: the SAME number of additions per cluster as the treatment, drawn
    uniformly from the noise pool without replacement."""
    total = sum(counts)
    if total > len(noise_pool):
        raise ValueError(f"cannot draw {total} from {len(noise_pool)} noise turns")
    drawn = rng.sample(list(noise_pool), total)
    out, at = [], 0
    for c in counts:
        out.append(drawn[at:at + c])
        at += c
    return out


def sign_test(b: int, c: int) -> float:
    """Two-sided exact binomial p for the discordant pair counts of a paired comparison."""
    from scipy.stats import binomtest
    if b + c == 0:
        return 1.0
    return float(binomtest(b, b + c, 0.5).pvalue)


def scale_match(counts_by_param: dict[float, int], target: int) -> float:
    """The parameter whose >=floor cluster count is closest to `target` (granularity
    matching, the same discipline as scale-matched min_cluster_size). Ties -> smaller."""
    return min(counts_by_param, key=lambda g: (abs(counts_by_param[g] - target), g))


# ---------------------------------------------------------------------------------------
# shared setup
# ---------------------------------------------------------------------------------------

def texts_hash(texts: list[str]) -> str:
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()[:16]


def load_artifact() -> dict:
    return json.loads(OUT.read_text(encoding="utf-8-sig")) if OUT.exists() else {}


def save_artifact(p: dict) -> None:
    OUT.write_text(json.dumps(p, indent=1, default=float), encoding="utf-8")


def save_members(name: str, arm_clusters: list[list[int]], mapped: list[str | None],
                 texts_sha: str) -> None:
    """Persist one arm's cluster memberships + their transferred keys for the reading step."""
    cur = {}
    if MEMBERS_OUT.exists():
        cur = json.loads(MEMBERS_OUT.read_text(encoding="utf-8-sig"))
    if cur.get("texts_sha") not in (None, texts_sha):
        raise SystemExit("members sidecar was built from a DIFFERENT pool; delete it")
    cur["texts_sha"] = texts_sha
    cur.setdefault("arms", {})[name] = {
        "clusters": [[int(i) for i in c] for c in arm_clusters],
        "mapped": list(mapped),
    }
    MEMBERS_OUT.write_text(json.dumps(cur, default=int), encoding="utf-8")


class Ctx:
    """Everything every arm needs, built once per process."""

    def __init__(self, recordings: str):
        from calibration import routing_bench as rb
        from calibration import routing_arms as ra

        self.adj_payload = json.loads((ARTIFACTS_DIR / ADJ_NAME).read_text(encoding="utf-8-sig"))
        for k, v in (("min_cluster_size", MIN_CLUSTER_SIZE), ("merge", MERGE)):
            if self.adj_payload.get(k) is not None and self.adj_payload[k] != v:
                raise SystemExit(f"CONFIG MISMATCH: {ADJ_NAME} built with {k}="
                                 f"{self.adj_payload[k]}, this run uses {v}.")
        self.adj = self.adj_payload["rows"]
        self.texts, self.call_ids = rb.build_pool(recordings)
        self.sha = texts_hash(self.texts)
        self.total_calls = len(set(self.call_ids))
        vecs = rb.embed_cache_only(self.texts)
        self.vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)
                     ).astype(np.float32)
        self.cl_keys, self.cl_coach, self.label_stats = ra.cluster_labels(self.adj)
        self.keys, self.coach, self.owner = ra.key_universe(self.cl_keys, self.cl_coach)
        self.coach_of_key = {k: bool(c) for k, c in zip(self.keys, self.coach)}
        self.coach_keys = [k for k, c in zip(self.keys, self.coach) if c]
        self.word_count = np.array([len(t.split()) for t in self.texts])
        self.order_by_wc = [int(i) for i in np.argsort(self.word_count, kind="stable")]
        self.rank_of = {t: i for i, t in enumerate(self.order_by_wc)}
        if not FLAGS_OUT.exists():
            raise SystemExit("run --stage flags first")
        fl = json.loads(FLAGS_OUT.read_text(encoding="utf-8-sig"))
        if fl["texts_sha"] != self.sha:
            raise SystemExit("flags artifact was built from a DIFFERENT pool; rebuild it")
        self.cfree = [bool(x) for x in fl["flags"]]
        self.n_cfree_total = sum(self.cfree)
        self._lex = None

    # --- incumbent clustering: fit fresh (incumbent arm) or load from the artifact -------
    def incumbent_clusters(self, art: dict, allow_fit: bool) -> list[dict]:
        from calibration import null_test_taxonomy as nt

        inc = art.get("incumbent_clusters")
        if inc is not None:
            if art.get("texts_sha") != self.sha:
                raise SystemExit("artifact pool sha mismatch; incumbent must be re-run")
            clusters = [{"idxs": c["idxs"], "n": c["n"], "calls": c["calls"],
                         "keywords": c["keywords"]} for c in inc]
            nt.verify_join(clusters, self.adj)
            return clusters
        if not allow_fit:
            raise SystemExit("no incumbent in the artifact -- run --arms incumbent first")
        from v2.layer_a import fit_topic_model
        print("fitting production clustering (1 UMAP fit) ...", flush=True)
        tm, topics = fit_topic_model(self.texts, self.vecs,
                                     min_cluster_size=MIN_CLUSTER_SIZE)
        topics = np.array(topics)
        raw_members = defaultdict(list)
        for i, t in enumerate(topics):
            if t != -1:
                raw_members[int(t)].append(i)
        clusters = merge_and_triage(self, raw_members, tm=tm)
        nt.verify_join(clusters, self.adj)
        self._tm, self._topics = tm, topics                      # sidecars for this process
        return clusters

    def truth_maps(self, clusters: list[dict]) -> tuple[dict[int, str], dict[int, bool]]:
        truth_key: dict[int, str] = {}
        truth_coach: dict[int, bool] = {}
        for c, ki, co in zip(clusters, self.owner, self.cl_coach):
            for i in c["idxs"]:
                truth_key[i] = self.keys[ki]
                truth_coach[i] = bool(co)
        return truth_key, truth_coach

    def lex(self):
        """TF-IDF space for the aligned-with-nobody secondary objective (audit machinery)."""
        if self._lex is None:
            from sklearn.feature_extraction.text import TfidfVectorizer
            tfv = TfidfVectorizer(min_df=2, sublinear_tf=True, stop_words=None, norm="l2")
            self._lex = tfv.fit_transform(self.texts).astype(np.float32)
        return self._lex


def merge_and_triage(ctx: Ctx, raw_members: dict[int, list[int]], tm=None) -> list[dict]:
    """Production post-processing, applied IDENTICALLY to every arm: centroid merge at 0.97
    plus the evidence triage's insufficient-evidence drop. Symmetric filtering -- an arm may
    not skip the filter its rival ran under."""
    from shared import cluster_evidence
    from shared.tuning import load_tuning

    ta = load_tuning().layer_a
    raw_ids = sorted(raw_members)
    if not raw_ids:
        return []
    cent = np.stack([cluster_evidence.support_stats(
        [ctx.call_ids[i] for i in raw_members[t]], ctx.vecs[raw_members[t]],
        ctx.total_calls).centroid for t in raw_ids])
    groups = cluster_evidence.merge_by_similarity(cent, MERGE)
    min_support = cluster_evidence.required_call_support(
        ctx.total_calls, ta.min_call_support_fraction, ta.min_call_support_floor)
    clusters = []
    for g in groups:
        tids = [raw_ids[x] for x in g]
        idxs = [i for t in tids for i in raw_members[t]]
        st = cluster_evidence.support_stats([ctx.call_ids[i] for i in idxs], ctx.vecs[idxs],
                                            ctx.total_calls,
                                            texts=[ctx.texts[i] for i in idxs])
        if cluster_evidence.triage(st, min_support, ta.ubiquity_ceiling) == \
                cluster_evidence.INSUFFICIENT_EVIDENCE:
            continue
        kw = ""
        if tm is not None:
            lead = max(tids, key=lambda z: len(raw_members[z]))
            kw = ", ".join(w for w, _ in tm.get_topic(lead)[:10])
        clusters.append({"idxs": idxs, "n": st.n_items, "calls": st.distinct_calls,
                         "keywords": kw})
    clusters.sort(key=lambda c: c["n"], reverse=True)
    return clusters


# ---------------------------------------------------------------------------------------
# scoring: one code path for every arm
# ---------------------------------------------------------------------------------------

def score_arm(ctx: Ctx, name: str, arm_clusters: list[list[int]], truth_key, note: str,
              ctl_rows: list[dict] | None, ctl_rows_lex: list[dict] | None,
              params: dict | None = None) -> dict:
    from calibration import null_test_taxonomy as nt
    from calibration.routing_objective_audit import draw_length_matched, coherence_sparse

    t0 = time.time()
    mapped = plurality_transfer(arm_clusters, truth_key)
    pops = populations(arm_clusters, mapped, ctx.coach_of_key)
    save_members(name, arm_clusters, mapped, ctx.sha)

    scored = nt.score_population(ctx.vecs, name, ctx.coach_keys, pops,
                                 ctx.order_by_wc, ctx.rank_of, ctx.word_count)
    rk = [r for r in scored["rows"] if r["rankable"]]
    ref_rows = ctl_rows if ctl_rows is not None else rk
    for r in rk:
        r["ref_lift"] = nt.size_matched_reference(r["n"], ref_rows)
        r["reaches_ref"] = bool(r[f"lift_{nt.GATE_NULL}"] >= r["ref_lift"])
    ctl_rank = {r["key"] for r in ref_rows}
    won = {r["key"] for r in rk if r.get("reaches_ref")}
    scored["n_fixed"] = len(ctl_rank)
    scored["n_clear_fixed"] = len(won & ctl_rank)
    scored["share_fixed"] = len(won & ctl_rank) / len(ctl_rank) if ctl_rank else float("nan")
    scored["n_unrankable_vs_ctl"] = len(ctl_rank - {r["key"] for r in rk})
    scored["reaches_by_key"] = {r["key"]: bool(r.get("reaches_ref")) for r in rk}

    # --- lexical objective (aligned with nobody), reported never gated --------------------
    # NOTE, recorded in the artifact: this consumes ONE rng in row order, and the rows differ
    # per arm (population sizes differ), so lexical null draws are NOT draw-identical across
    # arms the way the gate's are -- `score_population` gives each null its own rng consumed
    # in `keys` order, which is fixed. The lexical column is a direction check, never a gate,
    # so the looser reproducibility is accepted rather than engineered away; it is stated
    # here so nobody later reads the column as arm-to-arm paired.
    lex = ctx.lex()
    rng = random.Random(SEED)
    lex_rows = []
    for r in scored["rows"]:
        idx = pops.get(r["key"], [])
        row = {"key": r["key"], "n": len(idx), "rankable": r["rankable"]}
        if len(idx) >= 2:
            drawn = draw_length_matched(idx, ctx.order_by_wc, ctx.rank_of, rng)
            obs = coherence_sparse(lex[idx])
            null = float(np.mean([coherence_sparse(lex[d]) for d in drawn]))
            row["lift_lex"] = obs - null
        else:
            row["lift_lex"] = float("nan")
        lex_rows.append(row)
    lrk = [r for r in lex_rows if r["rankable"]]
    lref = ctl_rows_lex if ctl_rows_lex is not None else lrk
    for r in lrk:
        r["ref"] = nt.size_matched_reference(r["n"], lref, field="lift_lex")
        r["reaches"] = bool(r["lift_lex"] >= r["ref"])
    lwon = {r["key"] for r in lrk if r.get("reaches")}
    scored["lex_rows"] = lex_rows
    scored["n_clear_lex"] = len(lwon & ctl_rank)
    scored["share_lex"] = len(lwon & ctl_rank) / len(ctl_rank) if ctl_rank else float("nan")

    # --- coverage / composition / F4 ------------------------------------------------------
    all_members = [i for c in arm_clusters for i in c]
    coach_members = [i for v in pops.values() for i in v]
    subst = [i for i in range(len(ctx.texts)) if not ctx.cfree[i]]
    scored.update({
        "arm": name, "note": note, "params": params or {},
        "n_clusters": len(arm_clusters),
        "n_unmapped_clusters": sum(1 for m in mapped if m is None),
        "n_unmapped_turns": sum(len(c) for c, m in zip(arm_clusters, mapped) if m is None),
        "coverage": len(all_members) / len(ctx.texts),
        "coverage_substantive": (len([i for i in all_members if not ctx.cfree[i]])
                                 / max(1, len(subst))),
        "coach_turns": len(coach_members),
        "coach_cfree_share": (sum(ctx.cfree[i] for i in coach_members)
                              / max(1, len(coach_members))),
        "f4_cfree_in_coach": (sum(ctx.cfree[i] for i in coach_members)
                              / max(1, ctx.n_cfree_total)),
        "cluster_sizes_p": {q: int(np.percentile([len(c) for c in arm_clusters], q))
                            for q in (10, 50, 90)} if arm_clusters else {},
        "seconds": round(time.time() - t0, 1),
    })
    print(f"  [{name}] share_fixed {scored['n_clear_fixed']}/{scored['n_fixed']}"
          f" = {scored['share_fixed'] * 100:.0f}%   lex {scored['share_lex'] * 100:.0f}%"
          f"   coverage {scored['coverage'] * 100:.1f}%"
          f" (subst {scored['coverage_substantive'] * 100:.1f}%)"
          f"   F4 {scored['f4_cfree_in_coach'] * 100:.1f}%", flush=True)
    return scored


# ---------------------------------------------------------------------------------------
# arms
# ---------------------------------------------------------------------------------------

def mirror_umap_hdbscan(vecs: np.ndarray, seed: int, n_neighbors: int = 15,
                        min_samples: int = MIN_SAMPLES, method: str = "eom",
                        eps: float = 0.0) -> np.ndarray:
    """The production UMAP+HDBSCAN pair OUTSIDE BERTopic, for seed/param variants.
    Must be validated once against fit_topic_model's partition at seed 42 (F2 sibling) --
    the jitter arm does that before any other seed is trusted."""
    from umap import UMAP
    from hdbscan import HDBSCAN

    u = UMAP(n_components=5, n_neighbors=n_neighbors, min_dist=0.0, metric="cosine",
             random_state=seed)
    X5 = u.fit_transform(vecs)
    h = HDBSCAN(min_cluster_size=MIN_CLUSTER_SIZE, min_samples=min_samples,
                metric="euclidean", cluster_selection_method=method,
                cluster_selection_epsilon=eps)
    return np.asarray(h.fit_predict(np.asarray(X5, dtype=np.float64)))


def labels_to_members(labels: np.ndarray) -> dict[int, list[int]]:
    members: dict[int, list[int]] = defaultdict(list)
    for i, t in enumerate(labels):
        if t != -1:
            members[int(t)].append(i)
    return dict(members)


def knn_edges(vecs: np.ndarray, k: int) -> tuple[list[tuple[int, int]], list[float]]:
    """Exact brute-force kNN cosine graph (union of directed top-k), edge weight = cosine."""
    n = len(vecs)
    w: dict[tuple[int, int], float] = {}
    for s in range(0, n, CHUNK):
        sims = vecs[s:s + CHUNK] @ vecs.T
        for r in range(sims.shape[0]):
            i = s + r
            sims[r, i] = -np.inf
            top = np.argpartition(sims[r], -k)[-k:]
            for j in top:
                j = int(j)
                e = (i, j) if i < j else (j, i)
                w[e] = max(w.get(e, -1.0), float(sims[r, j]))
    edges = sorted(w)
    return edges, [w[e] for e in edges]


def arm_leiden(ctx: Ctx) -> tuple[list[list[int]], str, dict]:
    import igraph as ig
    import leidenalg as la

    print("building exact kNN cosine graph ...", flush=True)
    edges, weights = knn_edges(ctx.vecs, K_GRAPH)
    g = ig.Graph(n=len(ctx.texts), edges=edges)
    print(f"graph: {len(edges)} edges", flush=True)
    counts: dict[float, int] = {}
    parts: dict[float, list[list[int]]] = {}
    for gamma in GAMMA_GRID:
        part = la.find_partition(g, la.CPMVertexPartition, weights=weights,
                                 resolution_parameter=gamma, seed=SEED, n_iterations=2)
        comms = [list(map(int, c)) for c in part if len(c) >= SIZE_FLOOR]
        counts[gamma] = len(comms)
        parts[gamma] = comms
        print(f"  gamma {gamma:.2e}: {len(part)} communities, {len(comms)} >= {SIZE_FLOOR}",
              flush=True)
    gamma = scale_match(counts, TARGET_GRANULARITY)
    truncated = gamma in (GAMMA_GRID[0], GAMMA_GRID[-1])
    if truncated:
        print(f"  WARNING: scale-match landed on a GRID ENDPOINT (gamma={gamma:.2e}, "
              f"{counts[gamma]} communities vs target {TARGET_GRANULARITY}). The domain did "
              f"not contain the target granularity -- read this arm as 'the closest "
              f"granularity reachable', not as scale-matched.", flush=True)
    print(f"  selected gamma {gamma:.2e}: {counts[gamma]} communities >= {SIZE_FLOOR} "
          f"(target {TARGET_GRANULARITY})", flush=True)
    raw = {i: c for i, c in enumerate(parts[gamma])}
    clusters = merge_and_triage(ctx, raw)
    note = (f"Leiden CPM on exact kNN(k={K_GRAPH}) cosine graph, gamma={gamma:.2e} "
            f"({counts[gamma]} communities vs target {TARGET_GRANULARITY}"
            f"{', GRID ENDPOINT' if truncated else ''}), floor {SIZE_FLOOR}, then merge+triage")
    return [c["idxs"] for c in clusters], note, {
        "gamma": gamma, "gamma_counts": {f"{g:.2e}": c for g, c in counts.items()},
        "gamma_at_grid_endpoint": truncated, "n_communities_selected": counts[gamma],
        "edges": len(edges)}


def rescue_centroid_additions(ctx: Ctx, clusters: list[dict],
                              noise_idx: list[int]) -> list[list[int]]:
    """Noise turn joins its nearest cluster iff cosine >= that cluster's own members' p25
    cosine-to-centroid -- a per-cluster property of the data, no global constant."""
    cents, p25 = [], []
    for c in clusters:
        v = ctx.vecs[c["idxs"]]
        cen = v.mean(axis=0)
        cen /= np.linalg.norm(cen) + 1e-10
        cents.append(cen)
        p25.append(float(np.percentile(v @ cen, 25)))
    cents = np.stack(cents)
    p25 = np.array(p25)
    adds: list[list[int]] = [[] for _ in clusters]
    ni = np.array(noise_idx)
    for s in range(0, len(ni), CHUNK):
        block = ctx.vecs[ni[s:s + CHUNK]] @ cents.T
        best = block.argmax(axis=1)
        ok = block[np.arange(len(best)), best] >= p25[best]
        for t, b, o in zip(ni[s:s + CHUNK], best, ok):
            if o:
                adds[int(b)].append(int(t))
    return adds


# ---------------------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------------------

def stage_flags(recordings: str) -> None:
    from calibration import routing_bench as rb
    from calibration.diagnose_layer_a_noise import content_free_flags

    texts, _ = rb.build_pool(recordings)
    flags = content_free_flags(texts)
    FLAGS_OUT.write_text(json.dumps(
        {"texts_sha": texts_hash(texts), "n": len(texts),
         "flags": [int(f) for f in flags]}), encoding="utf-8")
    print(f"wrote {FLAGS_OUT}: {sum(flags)}/{len(flags)} content-free")


def stage_mirror(recordings: str) -> None:
    """Validate that mirror_umap_hdbscan at seed 42 reproduces production's partition.

    Its own process (ONE UMAP fit) so the jitter arms are one fit each. Without this the
    jitter band would be measured with an instrument never shown to agree with the thing
    it is a band around -- the same class of error as a harness whose 'control' is a
    different code path from the treatment.
    """
    from calibration.diagnose_layer_a_noise import partition_equal

    ctx = Ctx(recordings)
    art = load_artifact()
    raw = art.get("raw_topics")
    if raw is None:
        raise SystemExit("no raw_topics in the artifact -- run --arms incumbent first")
    if art.get("texts_sha") != ctx.sha:
        raise SystemExit("artifact pool sha mismatch")
    print("fitting the UMAP mirror at seed 42 (1 fit) ...", flush=True)
    lab42 = mirror_umap_hdbscan(ctx.vecs, 42)
    if not partition_equal(lab42, np.array(raw)):
        n_a, n_b = int((lab42 == -1).sum()), int((np.array(raw) == -1).sum())
        raise SystemExit(f"MIRROR INVALID: the seed-42 mirror does not reproduce production "
                         f"(noise {n_a} vs {n_b}). The jitter arms are void -- do NOT run "
                         "them, and do not report a jitter band.")
    art["mirror_validated"] = True
    save_artifact(art)
    print("mirror validated: seed-42 partition identical to production. Jitter arms are live.")


def run_arms(names: list[str], recordings: str) -> None:
    ctx = Ctx(recordings)
    art = load_artifact()
    art.setdefault("arms", {})
    art["texts_sha"] = art.get("texts_sha") or ctx.sha
    if art["texts_sha"] != ctx.sha:
        raise SystemExit("artifact pool sha mismatch")
    art.update({"n_turns": len(ctx.texts), "n_calls": ctx.total_calls, "seed": SEED,
                "min_cluster_size": MIN_CLUSTER_SIZE, "merge": MERGE,
                "control_source": ADJ_NAME, "embedder": "gemini-embedding-2@3072"})

    inc = ctx.incumbent_clusters(art, allow_fit="incumbent" in names)
    truth_key, truth_coach = ctx.truth_maps(inc)
    noise_idx = sorted(set(range(len(ctx.texts))) - set(truth_key))
    ctl_rows = art.get("ctl_rows")
    ctl_rows_lex = art.get("ctl_rows_lex")

    for name in names:
        print(f"\n=== arm {name} ===", flush=True)
        if name == "incumbent":
            # F2: transfer of the incumbent must be the identity map onto the folded control
            from calibration import null_test_taxonomy as nt
            arm_clusters = [c["idxs"] for c in inc]
            mapped = plurality_transfer(arm_clusters, truth_key)
            pops = populations(arm_clusters, mapped, ctx.coach_of_key)
            folded, _, _ = nt.fold_merged_clusters(inc, ctx.adj)
            if {k: sorted(v) for k, v in pops.items()} != \
                    {k: sorted(v) for k, v in folded.items()}:
                raise SystemExit("F2 FIRED: incumbent transfer is not the identity map. "
                                 "Harness bug; run void.")
            print("F2 self-check OK: incumbent transfer == folded control populations")
            res = score_arm(ctx, name, arm_clusters, truth_key,
                            "INCUMBENT (control) -- UMAP42+HDBSCAN16+merge0.97", None, None)
            ctl_rows = [r for r in res["rows"] if r["rankable"]]
            ctl_rows_lex = [r for r in res["lex_rows"] if r["rankable"]]
            art["ctl_rows"] = ctl_rows
            art["ctl_rows_lex"] = ctl_rows_lex
            art["incumbent_clusters"] = inc
            # sidecars for the P arms and rescue_soft
            if hasattr(ctx, "_tm"):
                np.save(UMAP42_NPY, np.asarray(ctx._tm.umap_model.embedding_,
                                               dtype=np.float64))
                art["raw_topics"] = [int(t) for t in ctx._topics]
                print(f"persisted UMAP-42 space -> {UMAP42_NPY.name}")
        elif name == "placebo_shuffle":
            member_pool = [i for c in inc for i in c["idxs"]]
            arm_clusters = shuffle_partition([c["n"] for c in inc], member_pool,
                                             random.Random(SEED))
            res = score_arm(ctx, name, arm_clusters, truth_key,
                            "PLACEBO -- incumbent sizes, membership shuffled",
                            ctl_rows, ctl_rows_lex)
        elif name == "rescue_soft":
            if not hasattr(ctx, "_tm"):
                raise SystemExit("rescue_soft must run in the incumbent-fitting process")
            import hdbscan as hdb
            mv = hdb.all_points_membership_vectors(ctx._tm.hdbscan_model)
            assigned = np.array([t != -1 for t in ctx._topics])
            own_max = mv[assigned].max(axis=1)
            thr = float(np.percentile(own_max, 10))
            raw_members = labels_to_members(np.array(ctx._topics))
            # raw topic -> surviving cluster. Merge groups keep WHOLE topics and triage drops
            # WHOLE groups, so a topic's members are all in one surviving cluster or all in
            # none -- asserted rather than trusted, because a partial mapping would silently
            # rescue turns into a cluster their own topic only half belongs to.
            raw_to_cluster: dict[int, int] = {}
            pos = {}
            for ci, c in enumerate(inc):
                for i in c["idxs"]:
                    pos[i] = ci
            for t, m in raw_members.items():
                owners = {pos.get(i) for i in m}
                if len(owners) != 1:
                    raise SystemExit(f"rescue_soft: raw topic {t} splits across surviving "
                                     f"clusters {sorted(o for o in owners if o is not None)} "
                                     "-- the all-or-nothing assumption is false; arm void.")
                (only,) = owners
                if only is not None:
                    raw_to_cluster[t] = only
            raw_ids_sorted = sorted(raw_members)
            # hdbscan's soft-membership COLUMN j is cluster label j, so column order equals
            # `raw_ids_sorted` only if the labels are contiguous from 0. They are, for
            # hdbscan -- assert it once rather than let an off-by-one misfile every rescue.
            if raw_ids_sorted != list(range(len(raw_ids_sorted))):
                raise SystemExit("rescue_soft: hdbscan labels are not contiguous from 0, so "
                                 "membership columns do not align with sorted topic ids.")
            if mv.shape[1] != len(raw_ids_sorted):
                raise SystemExit(f"rescue_soft: membership matrix has {mv.shape[1]} columns "
                                 f"for {len(raw_ids_sorted)} raw topics.")
            adds: list[list[int]] = [[] for _ in inc]
            n_res = 0
            for i in noise_idx:
                j = int(mv[i].argmax())          # == the raw topic id, asserted above
                if mv[i][j] >= thr and j in raw_to_cluster:
                    adds[raw_to_cluster[j]].append(i)
                    n_res += 1
            arm_clusters = [c["idxs"] + a for c, a in zip(inc, adds)]
            res = score_arm(ctx, name, arm_clusters, truth_key,
                            f"soft-membership rescue, thr=p10(assigned)={thr:.3f}, "
                            f"rescued {n_res}", ctl_rows, ctl_rows_lex,
                            {"threshold": thr, "rescued": n_res})
        elif name == "rescue_centroid":
            adds = rescue_centroid_additions(ctx, inc, noise_idx)
            n_res = sum(len(a) for a in adds)
            art["rescue_centroid_counts"] = [len(a) for a in adds]
            arm_clusters = [c["idxs"] + a for c, a in zip(inc, adds)]
            res = score_arm(ctx, name, arm_clusters, truth_key,
                            f"centroid rescue at per-cluster member p25, rescued {n_res}",
                            ctl_rows, ctl_rows_lex, {"rescued": n_res})
        elif name.startswith("rescue_centroid_s"):
            # F5 GAP, closed here. F5 was written for an arm with its own RNG, and
            # `rescue_centroid` has none -- so it never triggered. But the arm is only
            # deterministic GIVEN ITS INPUT, and its input is a seeded UMAP whose gate score
            # spans 39-53% across seeds. Measuring the rescue on seed 42 alone cannot separate
            # "the rule adds ~+21 to any base" from "seed 42 happened to split well".
            # Costs no UMAP fit: the jitter arms' memberships are already persisted.
            seed = name.split("_s")[-1]
            base_name = f"jitter_s{seed}"
            side = json.loads(MEMBERS_OUT.read_text(encoding="utf-8-sig"))
            if base_name not in side.get("arms", {}):
                raise SystemExit(f"run --arms {base_name} first (its memberships are the base)")
            base = [{"idxs": [int(i) for i in c]}
                    for c in side["arms"][base_name]["clusters"]]
            base_noise = sorted(set(range(len(ctx.texts)))
                                - {i for c in base for i in c["idxs"]})
            adds = rescue_centroid_additions(ctx, base, base_noise)
            n_res = sum(len(a) for a in adds)
            arm_clusters = [c["idxs"] + a for c, a in zip(base, adds)]
            res = score_arm(ctx, name, arm_clusters, truth_key,
                            f"centroid rescue (member p25) applied to {base_name}'s clusters "
                            f"-- seed re-test of the rescue rule, rescued {n_res}",
                            ctl_rows, ctl_rows_lex, {"base": base_name, "rescued": n_res})
        elif name == "rescue_placebo":
            counts = art.get("rescue_centroid_counts")
            if counts is None:
                raise SystemExit("run rescue_centroid before rescue_placebo")
            adds = volume_matched_rescue(counts, noise_idx, random.Random(SEED))
            arm_clusters = [c["idxs"] + a for c, a in zip(inc, adds)]
            res = score_arm(ctx, name, arm_clusters, truth_key,
                            f"PLACEBO -- volume-matched random rescue ({sum(counts)})",
                            ctl_rows, ctl_rows_lex)
        elif name == "leiden_knn":
            arm_clusters, note, params = arm_leiden(ctx)
            res = score_arm(ctx, name, arm_clusters, truth_key, note,
                            ctl_rows, ctl_rows_lex, params)
        elif name in P_ARMS:
            if not UMAP42_NPY.exists():
                raise SystemExit("run --arms incumbent first (persists the UMAP-42 space)")
            import hdbscan as hdb
            spec = P_ARMS[name]
            eps = 0.0
            if spec["eps_key"]:
                diag = json.loads((ARTIFACTS_DIR / "layer_a_noise_diagnostic.json")
                                  .read_text(encoding="utf-8-sig"))
                eps = float(diag["stage_main"]["eps_candidates"][spec["eps_key"]])
            X5 = np.load(UMAP42_NPY)
            h = hdb.HDBSCAN(min_cluster_size=MIN_CLUSTER_SIZE,
                            min_samples=spec["min_samples"], metric="euclidean",
                            cluster_selection_method=spec["method"],
                            cluster_selection_epsilon=eps)
            labels = np.asarray(h.fit_predict(X5))
            clusters = merge_and_triage(ctx, labels_to_members(labels))
            res = score_arm(ctx, name, [c["idxs"] for c in clusters], truth_key,
                            f"HDBSCAN ms={spec['min_samples']} {spec['method']} "
                            f"eps={eps:.4f} on the UMAP-42 space, merge+triage",
                            ctl_rows, ctl_rows_lex,
                            {**{k: v for k, v in spec.items()}, "eps": eps,
                             "noise_rate": float((labels == -1).mean())})
        elif name.startswith("jitter_s"):
            seed = int(name.split("_s")[1])
            if not art.get("mirror_validated"):
                raise SystemExit(
                    "run `--stage mirror` first. The seed-42 mirror check is its own process "
                    "deliberately: doing it here would put TWO UMAP fits in one process, "
                    "which is the memory failure this harness is split up to avoid.")
            labels = mirror_umap_hdbscan(ctx.vecs, seed)
            clusters = merge_and_triage(ctx, labels_to_members(labels))
            res = score_arm(ctx, name, [c["idxs"] for c in clusters], truth_key,
                            f"incumbent pipeline at UMAP seed {seed} (jitter control)",
                            ctl_rows, ctl_rows_lex,
                            {"noise_rate": float((labels == -1).mean())})
        elif name == "agglo_cosine":
            from scipy.cluster.hierarchy import fcluster, linkage
            from scipy.spatial.distance import pdist
            print("condensed cosine distances (~2.3 GB) ...", flush=True)
            d = pdist(ctx.vecs.astype(np.float64), metric="cosine")
            print("average linkage ...", flush=True)
            Z = linkage(d, method="average")
            del d
            heights = np.quantile(Z[:, 2], np.linspace(0.5, 0.999, 40))
            counts = {}
            for h in heights:
                lab = fcluster(Z, t=h, criterion="distance")
                counts[float(h)] = int(sum(1 for _, c in Counter(lab).items()
                                           if c >= SIZE_FLOOR))
            h = scale_match(counts, TARGET_GRANULARITY)
            lab = fcluster(Z, t=h, criterion="distance")
            keep = {t for t, c in Counter(lab).items() if c >= SIZE_FLOOR}
            raw = defaultdict(list)
            for i, t in enumerate(lab):
                if t in keep:
                    raw[int(t)].append(i)
            clusters = merge_and_triage(ctx, dict(raw))
            res = score_arm(ctx, name, [c["idxs"] for c in clusters], truth_key,
                            f"average-linkage cosine, cut h={h:.4f} (scale-matched), "
                            f"floor {SIZE_FLOOR}, merge+triage",
                            ctl_rows, ctl_rows_lex, {"cut": float(h)})
        else:
            raise SystemExit(f"unknown arm {name!r}")
        art["arms"][name] = res
        save_artifact(art)
    print(f"\nwrote {OUT}")


# ---------------------------------------------------------------------------------------
# report + verdicts
# ---------------------------------------------------------------------------------------

def report() -> None:
    art = load_artifact()
    arms = art.get("arms", {})
    inc = arms.get("incumbent")
    if not inc:
        raise SystemExit("no incumbent in the artifact")
    print("\n" + "=" * 104)
    print("CLUSTERING BENCH -- every arm, same pool / embedder / transfer / null / reference")
    print("=" * 104)
    print(f"  pool {art['n_turns']} turns / {art['n_calls']} calls   {art['embedder']}   "
          f"seed {art['seed']}   reference frozen from the incumbent control")
    print(f"\n  {'arm':<18}{'FIXED':>12}{'lex':>7}{'coverage':>10}{'subst cov':>11}"
          f"{'coachN':>8}{'F4%':>7}{'clusters':>9}{'unrank':>7}{'sign p':>9}")
    order = sorted(arms, key=lambda a: -(arms[a].get("share_fixed") or 0))
    inc_reach = inc.get("reaches_by_key", {})
    ctl_keys = sorted({r["key"] for r in art.get("ctl_rows", [])})
    for name in order:
        a = arms[name]
        b = sum(1 for k in ctl_keys
                if a.get("reaches_by_key", {}).get(k, False) and not inc_reach.get(k, False))
        c = sum(1 for k in ctl_keys
                if not a.get("reaches_by_key", {}).get(k, False) and inc_reach.get(k, False))
        p = sign_test(b, c) if name != "incumbent" else float("nan")
        a["sign_b"], a["sign_c"], a["sign_p"] = b, c, p
        # Built in a variable, never inline: the previous form ended
        # `... + suffix if name != "incumbent" else ""`, and the ternary binds the WHOLE
        # concatenation, so the control row printed as an empty string.
        fixed = f"{a['n_clear_fixed']}/{a['n_fixed']}={a['share_fixed'] * 100:.0f}%"
        line = (f"  {name:<18}{fixed:>12}"
                f"{a['share_lex'] * 100:>6.0f}%"
                f"{a['coverage'] * 100:>9.1f}%"
                f"{a['coverage_substantive'] * 100:>10.1f}%"
                f"{a['coach_turns']:>8}"
                f"{a['f4_cfree_in_coach'] * 100:>6.1f}%"
                f"{a['n_clusters']:>9}"
                f"{a['n_unrankable_vs_ctl']:>7}"
                + (f"{p:>9.3f}" if p == p else f"{'--':>9}"))
        if name != "incumbent":
            line += f"  (+{b}/-{c})"
        print(line)

    # --- pre-registered verdicts, in code --------------------------------------------------
    S = lambda n: arms.get(n, {}).get("share_fixed", float("nan"))
    v = {}
    if "placebo_shuffle" in arms:
        v["F1 metric void (placebo_shuffle >= incumbent)"] = (
            f"{'FIRED' if S('placebo_shuffle') >= S('incumbent') else 'clear'} -- "
            f"placebo {S('placebo_shuffle') * 100:.0f}% vs incumbent {S('incumbent') * 100:.0f}%")
    v["F2 identity transfer"] = "asserted in the incumbent run (run aborts on failure)"
    beat = [n for n, a in arms.items()
            if n not in ("incumbent", "placebo_shuffle", "rescue_placebo",
                         "jitter_s1", "jitter_s7")
            and (a.get("share_fixed") or 0) > (S("incumbent") or 0)
            and a.get("sign_p", 1.0) < 0.05]
    v["F3 H1 (S1 quality win)"] = (f"clear -- {beat}" if beat else
                                   "FIRED -- nothing beats the incumbent at p<0.05")
    flooded = [n for n, a in arms.items() if (a.get("f4_cfree_in_coach") or 0) > 0.5]
    v["F4 junk flood (>50% of content-free turns in coachable pops)"] = \
        f"{'FIRED for ' + str(flooded) if flooded else 'clear'}"
    thin = [n for n, a in arms.items()
            if a.get("n_fixed", 0) - a.get("n_unrankable_vs_ctl", 0) < 20]
    v["F6 thin strata (< 20 of the control set rankable)"] = f"{thin or 'clear'}"
    jmax = max((S(j) for j in ("jitter_s1", "jitter_s7") if j in arms), default=float("nan"))
    if jmax == jmax:
        over = [n for n, a in arms.items()
                if n not in ("incumbent", "placebo_shuffle", "rescue_placebo",
                             "jitter_s1", "jitter_s7")
                and (a.get("share_fixed") or 0) > jmax]
        v["F7 jitter band"] = (f"jitter max {jmax * 100:.0f}%; above it: {over or 'none'}")
    # S2: noise falls materially with quality holding
    s2 = [n for n, a in arms.items()
          if n not in ("incumbent", "placebo_shuffle", "rescue_placebo")
          and (a.get("coverage_substantive") or 0)
          >= (inc.get("coverage_substantive") or 0) + 0.15
          and a.get("n_clear_fixed", 0) >= inc.get("n_clear_fixed", 0) - 1
          and not (a.get("sign_p", 1.0) < 0.05
                   and a.get("sign_c", 0) > a.get("sign_b", 0))]
    v["S2 noise win (subst coverage +15pts, quality holds)"] = f"{s2 or 'none'}"

    print("\n" + "=" * 104)
    print("  PRE-REGISTERED VERDICTS")
    print("=" * 104)
    for k in v:
        print(f"  {k}: {v[k]}")
    art["verdicts"] = v
    save_artifact(art)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stage", default="", choices=("", "flags", "mirror"))
    p.add_argument("--arms", default="")
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--report", action="store_true")
    a = p.parse_args()
    if a.stage == "flags":
        stage_flags(a.recordings)
    elif a.stage == "mirror":
        stage_mirror(a.recordings)
    elif a.report:
        report()
    elif a.arms:
        run_arms([s.strip() for s in a.arms.split(",") if s.strip()], a.recordings)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
