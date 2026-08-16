#!/usr/bin/env python3
"""Pluggable routing methods: turn -> scenario. Pure, no I/O, no DB, no chat calls.

Spec: docs/superpowers/specs/2026-08-16-layer-a-routing-method-design.md

Every arm reduces to the same shape -- produce a (n_turns, n_keys) score matrix, take the
argmax, and read `coachable` off the winning key. Rejection is NOT a separate mechanism: a
turn is rejected exactly when a SINK key wins, which is why sink clusters must carry points
in every arm. Dropping them would abolish the only junk filter the pipeline has (failure
condition F4 in the spec).

TWO FAMILIES, one interface:
  point-based   each key contributes >= 1 vector; key score = max cosine over its points.
                `description` (1 prose vector), `centroid` (1 mean), `medoid` (1 real turn),
                `submeans` (m k-means sub-centroids), `knn_max` (EVERY member is a point).
  pooled        `knn_topk_mean` (mean of the k best member cosines) and `probe` (a linear
                head) need a reduction that is not a max, so they build the matrix directly.

*** SELF-INFLATION. *** `knn_max`, `knn_topk_mean`, `medoid` and `probe` are marked
`self_inflating`: scored over the SAME turns their points/labels come from, a member is its
own nearest neighbour at cosine 1.0 and the arm reproduces cluster membership exactly while
having learned nothing. They are only interpretable in held-out mode. `SELF_INFLATING` is
consumed by the harness to label the full-corpus column, so the inflation is printed rather
than discovered later.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SEED = 42
KNN_K = 5                  # knn_topk_mean: how many member similarities to average
SUBMEANS_PER = 60          # submeans: roughly one sub-centroid per this many members
SUBMEANS_MAX = 8
BLEND_ALPHAS = (0.25, 0.50, 0.75)
MIN_TRAIN_MEMBERS = 3      # a cluster with fewer train members contributes no points
PROBE_MAX_ITER = 300       # lbfgs cap; whether it BINDS is recorded in the arm's note
CHUNK = 2048               # turns per similarity chunk; caps peak memory, not a result knob

# Arms whose score for a turn is inflated when that turn is inside their own fitting set.
SELF_INFLATING = frozenset({"knn_max", "knn_topk_mean", "medoid", "probe"})

# Arms that need cluster membership at match time. A winner here is an architecture change
# (member turns must be stored beside every scenario forever), not a prompt change -- see
# hypothesis H2 in the spec.
NEEDS_MEMBERSHIP = frozenset({"centroid", "centroid_pooled", "medoid", "knn_max",
                              "knn_topk_mean", "submeans", "probe", "placebo_centroid"})


@dataclass
class Routing:
    """Per-turn assignment. `accepted` is `coachable(argmax)`, never a separate threshold."""
    keys: list[str]            # winning key per turn
    accepted: np.ndarray       # bool per turn
    margin: np.ndarray         # top1 - top2 over keys (nan when < 2 keys have a score)
    best_sim: np.ndarray       # the winning score
    n_points: int              # how many vectors the arm routed against
    note: str = ""


def cluster_labels(adj_rows: list[dict]) -> tuple[list[str], list[bool], dict]:
    """Map each adjudicated cluster to the key it belongs to, and whether that key is coachable.

    `kind` is FOUR-valued and `merged` means RETAINED -- the cluster is folded into an existing
    scenario. Testing `kind == "scenario"` treats a retained duplicate as a discard, the exact
    collapse that produced the phantom "Gemma over-sinks 14.6% of the corpus" finding and then
    recurred in the positive control of `null_test_taxonomy.py`. Mirrors that module's
    `fold_merged_clusters`; the harness cross-checks the two agree.

    A `merged` row whose target is not a kept scenario is ORPHANED: it becomes a sink under its
    own key rather than vanishing, and the count is returned so it can never do so silently.
    """
    seed_keys = {r["scenario_key"] for r in adj_rows if r["kind"] == "scenario"}
    keys, coach = [], []
    stats = {"scenario": 0, "merged_folded": 0, "merged_orphaned": 0, "sink": 0}
    for r in adj_rows:
        if r["kind"] == "scenario":
            keys.append(r["scenario_key"])
            coach.append(True)
            stats["scenario"] += 1
        elif r["kind"] == "merged" and r.get("merge_into_key") in seed_keys:
            keys.append(r["merge_into_key"])
            coach.append(True)
            stats["merged_folded"] += 1
        else:
            keys.append(r["scenario_key"])
            coach.append(False)
            stats["merged_orphaned" if r["kind"] == "merged" else "sink"] += 1
    return keys, coach, stats


def key_universe(cluster_keys: list[str], cluster_coach: list[bool]
                 ) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Collapse per-cluster labels to the distinct key set. Returns (keys, coachable, owner).

    `owner[c]` is the key index of cluster c -- several clusters share one key when merges
    were folded in, which is the whole point of folding them.
    """
    uniq: list[str] = []
    seen: dict[str, int] = {}
    coach: list[bool] = []
    for k, c in zip(cluster_keys, cluster_coach):
        if k not in seen:
            seen[k] = len(uniq)
            uniq.append(k)
            coach.append(bool(c))
        elif coach[seen[k]] != bool(c):
            raise ValueError(f"key {k!r} appears as both coachable and sink")
    owner = np.array([seen[k] for k in cluster_keys], dtype=np.int32)
    return uniq, np.array(coach, dtype=bool), owner


def _pool_max(turn_vecs: np.ndarray, point_vecs: np.ndarray, point_key: np.ndarray,
              n_keys: int) -> np.ndarray:
    """(n_turns, n_keys) of max cosine to any of that key's points. Chunked over turns.

    Points are grouped by key ONCE and reduced with a slice-max per key, rather than
    `np.maximum.at` (which is an unbuffered ufunc call per element and orders of magnitude
    slower at this size).
    """
    order = np.argsort(point_key, kind="stable")
    pv = np.ascontiguousarray(point_vecs[order])
    pk = point_key[order]
    bounds = np.searchsorted(pk, np.arange(n_keys + 1))
    out = np.full((len(turn_vecs), n_keys), -np.inf, dtype=np.float32)
    for s in range(0, len(turn_vecs), CHUNK):
        sims = turn_vecs[s:s + CHUNK] @ pv.T
        for k in range(n_keys):
            lo, hi = bounds[k], bounds[k + 1]
            if hi > lo:
                out[s:s + CHUNK, k] = sims[:, lo:hi].max(axis=1)
    return out


def _pool_topk_mean(turn_vecs: np.ndarray, point_vecs: np.ndarray, point_key: np.ndarray,
                    n_keys: int, k: int = KNN_K) -> np.ndarray:
    """Mean of the k highest member cosines per key -- the Prototype-Neighbor hybrid shape.

    A key with fewer than k points averages all of them, so a small cluster is not penalised
    for being small (which would make this arm a size filter wearing a similarity costume).
    """
    order = np.argsort(point_key, kind="stable")
    pv = np.ascontiguousarray(point_vecs[order])
    pk = point_key[order]
    bounds = np.searchsorted(pk, np.arange(n_keys + 1))
    out = np.full((len(turn_vecs), n_keys), -np.inf, dtype=np.float32)
    for s in range(0, len(turn_vecs), CHUNK):
        sims = turn_vecs[s:s + CHUNK] @ pv.T
        for j in range(n_keys):
            lo, hi = bounds[j], bounds[j + 1]
            if hi <= lo:
                continue
            block = sims[:, lo:hi]
            kk = min(k, hi - lo)
            if kk == hi - lo:
                out[s:s + CHUNK, j] = block.mean(axis=1)
            else:
                part = np.partition(block, -kk, axis=1)[:, -kk:]
                out[s:s + CHUNK, j] = part.mean(axis=1)
    return out


def routing_from_scores(scores: np.ndarray, keys: list[str], coach: np.ndarray,
                        n_points: int, note: str = "") -> Routing:
    """argmax + margin. `-inf` columns (a key with no points) are ignored by construction."""
    best = np.argmax(scores, axis=1)
    rows = np.arange(len(scores))
    bs = scores[rows, best]
    if scores.shape[1] >= 2:
        part = np.partition(scores, -2, axis=1)
        second = part[:, -2]
        margin = (bs - second).astype(np.float32)
    else:
        margin = np.full(len(scores), np.nan, dtype=np.float32)
    return Routing(keys=[keys[b] for b in best], accepted=coach[best],
                   margin=margin, best_sim=bs.astype(np.float32),
                   n_points=n_points, note=note)


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-10)


# -- arm builders ------------------------------------------------------------------------
# Each takes the shared context and returns a Routing over `ctx.eval_vecs`. `fit_idx` is the
# set of turn indices an arm may learn from -- train-call turns in held-out mode, everything
# in full mode. No arm may look at eval turns except through its own score function.

@dataclass
class ArmContext:
    vecs: np.ndarray                     # (n_turns, dim), L2-normalised
    eval_idx: np.ndarray                 # indices of turns to route
    fit_mask: np.ndarray                 # bool per turn: may this turn be learned from
    cluster_members: list[list[int]]     # turn indices per adjudicated cluster
    cluster_keys: list[str]
    cluster_coach: list[bool]
    desc_vecs: np.ndarray | None         # (n_keys, dim) aligned to `keys`, nan-free rows only
    desc_have: np.ndarray | None         # bool per key: a description vector exists
    keys: list[str]
    coach: np.ndarray
    owner: np.ndarray                    # cluster -> key index
    seed: int = SEED
    texts: list[str] | None = None       # raw turn text; only the rerank arms need it

    @property
    def eval_vecs(self) -> np.ndarray:
        return self.vecs[self.eval_idx]

    def fit_members(self) -> list[list[int]]:
        """Cluster membership restricted to fittable turns, with the size floor applied."""
        out = []
        for m in self.cluster_members:
            f = [i for i in m if self.fit_mask[i]]
            out.append(f if len(f) >= MIN_TRAIN_MEMBERS else [])
        return out


def arm_description(ctx: ArmContext) -> Routing:
    """THE INCUMBENT FLOOR -- what ships. Uses no cluster membership at all."""
    if ctx.desc_vecs is None:
        raise ValueError("description arm needs desc_vecs")
    scores = np.full((len(ctx.eval_idx), len(ctx.keys)), -np.inf, dtype=np.float32)
    have = np.flatnonzero(ctx.desc_have)
    scores[:, have] = ctx.eval_vecs @ ctx.desc_vecs[have].T
    return routing_from_scores(scores, ctx.keys, ctx.coach, len(have),
                               "business_description + keyphrases, top-1 cosine")


def _key_points_from_members(ctx: ArmContext, reducer):
    """Collect (vectors, key_index) by applying `reducer` to each cluster's fittable members."""
    pv, pk = [], []
    for c, mem in enumerate(ctx.fit_members()):
        if not mem:
            continue
        for v in reducer(ctx.vecs[mem]):
            pv.append(v)
            pk.append(ctx.owner[c])
    if not pv:
        raise ValueError("no cluster retained enough fittable members")
    return _unit(np.stack(pv).astype(np.float32)), np.array(pk, dtype=np.int32)


def arm_centroid(ctx: ArmContext) -> Routing:
    """THE INCUMBENT TO BEAT -- one mean vector per cluster."""
    pv, pk = _key_points_from_members(ctx, lambda m: [m.mean(axis=0)])
    scores = _pool_max(ctx.eval_vecs, pv, pk, len(ctx.keys))
    return routing_from_scores(scores, ctx.keys, ctx.coach, len(pv),
                               "mean of member vectors")


def pooled_key_members(ctx: ArmContext) -> dict[int, list[int]]:
    """key index -> every fittable member turn of every cluster folded into that key."""
    acc: dict[int, list[int]] = {}
    for c, mem in enumerate(ctx.fit_members()):
        if mem:
            acc.setdefault(int(ctx.owner[c]), []).extend(mem)
    return acc


def pooled_centroid_scores(ctx: ArmContext) -> tuple[np.ndarray, dict[int, list[int]]]:
    """The `centroid_pooled` score matrix, shared with the rerank arms as their proposer."""
    acc = pooled_key_members(ctx)
    if not acc:
        raise ValueError("no cluster retained enough fittable members")
    pv = _unit(np.stack([ctx.vecs[m].mean(axis=0) for m in acc.values()]).astype(np.float32))
    pk = np.array(list(acc), dtype=np.int32)
    return _pool_max(ctx.eval_vecs, pv, pk, len(ctx.keys)), acc


def representative_members(ctx: ArmContext, acc: dict[int, list[int]], n: int
                           ) -> dict[int, list[int]]:
    """The `n` most central member turns per key -- medoids, deterministic, no RNG.

    A cross-encoder cannot read a centroid; it needs TEXT. These stand in for the key, and
    they are real client utterances, which is the whole point: the probe showed this model
    separates on turn-vs-turn (spread 4.61) and saturates on turn-vs-prose (0.57).
    """
    out: dict[int, list[int]] = {}
    for k, mem in acc.items():
        v = ctx.vecs[mem]
        c = _unit(v.mean(axis=0))
        order = np.argsort(-(v @ c))[:n]
        out[k] = [mem[int(i)] for i in order]
    return out


def _topk_candidates(scores: np.ndarray, k: int) -> np.ndarray:
    """Indices of the k highest-scoring keys per row. `-inf` columns can only be picked
    when fewer than k keys have any score at all, which argpartition handles naturally."""
    k = min(k, scores.shape[1])
    part = np.argpartition(-scores, k - 1, axis=1)[:, :k]
    rows = np.arange(len(scores))[:, None]
    return part[rows, np.argsort(-scores[rows, part], axis=1)]


def make_rerank_arm(pair_scorer, k: int = 5, n_members: int = 3, note: str = "rerank"):
    """Propose top-k with `centroid_pooled`, then re-score those candidates with `pair_scorer`.

    `pair_scorer(list[(turn_text, member_text)]) -> np.ndarray` is INJECTED rather than
    imported, so this is testable with a stub and carries no model dependency of its own.

    Sinks are ordinary candidates. Rejection therefore still happens exactly one way -- a sink
    key wins -- and re-ranking can both create and remove rejections rather than being bolted
    on beside them.
    """
    def arm(ctx: ArmContext) -> Routing:
        if ctx.texts is None:
            raise ValueError("rerank arms need ctx.texts")
        base, acc = pooled_centroid_scores(ctx)
        cand = _topk_candidates(base, k)
        reps = representative_members(ctx, acc, n_members)

        pairs, where = [], []
        for r, i in enumerate(ctx.eval_idx):
            qt = ctx.texts[i]
            for kj in cand[r]:
                for m in reps.get(int(kj), ()):
                    pairs.append((qt, ctx.texts[m]))
                    where.append((r, int(kj)))
        if not pairs:
            raise ValueError("rerank produced no candidate pairs")
        flat = np.asarray(pair_scorer(pairs), dtype=np.float32)
        if len(flat) != len(pairs):
            raise ValueError(f"pair_scorer returned {len(flat)} scores for {len(pairs)} pairs")

        scores = np.full((len(ctx.eval_idx), len(ctx.keys)), -np.inf, dtype=np.float32)
        for (r, kj), s in zip(where, flat):
            if s > scores[r, kj]:
                scores[r, kj] = s                       # max-pool over that key's members
        return routing_from_scores(scores, ctx.keys, ctx.coach, len(reps),
                                   f"{note} (top-{k} x {n_members} members)")
    return arm


def make_random_rerank_arm(k: int = 5, note: str = "PLACEBO rerank"):
    """*** THE RERANK PLACEBO (spec F7). *** Pick uniformly among the same top-k candidates.

    Restricting to 5 candidates is itself an intervention -- it discards every far-fetched key
    the argmax might otherwise have reached. If a real re-ranker does not clearly beat this,
    whatever gain appears came from the shortlist, not from reading the pair.
    """
    def arm(ctx: ArmContext) -> Routing:
        base, _ = pooled_centroid_scores(ctx)
        cand = _topk_candidates(base, k)
        rng = np.random.default_rng(ctx.seed)
        pick = rng.integers(0, cand.shape[1], size=len(cand))
        scores = np.full((len(ctx.eval_idx), len(ctx.keys)), -np.inf, dtype=np.float32)
        scores[np.arange(len(cand)), cand[np.arange(len(cand)), pick]] = 1.0
        return routing_from_scores(scores, ctx.keys, ctx.coach, cand.shape[1],
                                   f"{note}: uniform among top-{k}")
    return arm


def arm_centroid_pooled(ctx: ArmContext) -> Routing:
    """ONE centroid per KEY, pooling every cluster folded into it.

    *** THIS EXISTS TO REMOVE A CONFOUND IN `blend`. *** `arm_centroid` gives each adjudicated
    CLUSTER its own centroid and max-pools per key, so a scenario with three merged duplicates
    already routes against three prototypes -- it is quietly a multi-prototype method (245
    points over 148 keys). `blend` averages a key's members into a single vector before mixing
    in the description. Comparing `blend` against `centroid` therefore varies TWO things at
    once: whether the description is added, and whether merged clusters keep separate
    prototypes. This arm is `blend`'s true alpha=1 endpoint, so the alpha sweep interpolates
    between two arms that differ in exactly one respect.
    """
    scores, acc = pooled_centroid_scores(ctx)
    return routing_from_scores(scores, ctx.keys, ctx.coach, len(acc),
                               "ONE mean vector per key (merged clusters pooled)")


def arm_medoid(ctx: ArmContext) -> Routing:
    """The single most central REAL member turn -- a prototype that is an actual utterance."""
    def pick(m):
        c = _unit(m.mean(axis=0))
        return [m[int(np.argmax(m @ c))]]
    pv, pk = _key_points_from_members(ctx, pick)
    scores = _pool_max(ctx.eval_vecs, pv, pk, len(ctx.keys))
    return routing_from_scores(scores, ctx.keys, ctx.coach, len(pv),
                               "most central real member turn")


def arm_submeans(ctx: ArmContext) -> Routing:
    """m k-means sub-centroids per cluster -- a multi-modal class needs more than one mode."""
    from sklearn.cluster import KMeans

    def pick(m):
        k = int(np.clip(round(len(m) / SUBMEANS_PER), 1, SUBMEANS_MAX))
        if k <= 1 or len(m) < 2 * k:
            return [m.mean(axis=0)]
        km = KMeans(n_clusters=k, n_init=3, random_state=ctx.seed).fit(m)
        return list(km.cluster_centers_)
    pv, pk = _key_points_from_members(ctx, pick)
    scores = _pool_max(ctx.eval_vecs, pv, pk, len(ctx.keys))
    return routing_from_scores(scores, ctx.keys, ctx.coach, len(pv),
                               f"<= {SUBMEANS_MAX} k-means sub-centroids per cluster")


def arm_knn_max(ctx: ArmContext) -> Routing:
    """1-NN: every member turn is a point. Self-inflating unless eval is disjoint from fit."""
    pv, pk = _key_points_from_members(ctx, lambda m: list(m))
    scores = _pool_max(ctx.eval_vecs, pv, pk, len(ctx.keys))
    return routing_from_scores(scores, ctx.keys, ctx.coach, len(pv),
                               "max cosine to any member turn")


def arm_knn_topk_mean(ctx: ArmContext) -> Routing:
    pv, pk = _key_points_from_members(ctx, lambda m: list(m))
    scores = _pool_topk_mean(ctx.eval_vecs, pv, pk, len(ctx.keys))
    return routing_from_scores(scores, ctx.keys, ctx.coach, len(pv),
                               f"mean of the {KNN_K} best member cosines")


def arm_probe(ctx: ArmContext) -> Routing:
    """Linear probe over frozen embeddings -- the SetFit head shape without the fine-tune.

    ONE in-process multinomial lbfgs fit, deliberately NOT `OneVsRestClassifier(n_jobs=-1)`.
    That version died with `OSError [WinError 1450] Insufficient system resources`: joblib
    forks a worker per core and pickles the whole 13k x 3072 float32 design matrix into each,
    ~1.3GB of copies on a 16GB box. Same address-space failure this repo already documents for
    running the test suite in one process. lbfgs keeps one copy and lets BLAS do the work.
    """
    from sklearn.linear_model import LogisticRegression

    X, y = [], []
    for c, mem in enumerate(ctx.fit_members()):
        for i in mem:
            X.append(ctx.vecs[i])
            y.append(int(ctx.owner[c]))
    if not X:
        raise ValueError("probe has no training rows")
    X = np.stack(X)
    y = np.array(y)
    present = np.unique(y)
    clf = LogisticRegression(solver="lbfgs", C=1.0, max_iter=PROBE_MAX_ITER)
    clf.fit(X, y)
    df = clf.decision_function(ctx.eval_vecs)
    if df.ndim == 1:                       # degenerate: a single class survived
        df = df[:, None]
    scores = np.full((len(ctx.eval_idx), len(ctx.keys)), -np.inf, dtype=np.float32)
    scores[:, present] = df.astype(np.float32)
    # Convergence is RECORDED, not assumed: a probe that stopped at the iteration cap is a
    # weaker arm than one that converged, and reading its number as "a linear head cannot do
    # better" would be wrong.
    it = int(np.max(clf.n_iter_)) if np.ndim(clf.n_iter_) else int(clf.n_iter_)
    return routing_from_scores(scores, ctx.keys, ctx.coach, len(present),
                               f"multinomial logistic probe ({len(X)} rows, {it} lbfgs iters"
                               f"{', HIT CAP' if it >= PROBE_MAX_ITER else ''})")


def arm_placebo_centroid(ctx: ArmContext) -> Routing:
    """*** THE PLACEBO (spec F1). ***

    Same mechanism as `centroid` -- route to the nearest in-manifold point -- with the cluster
    CONTENT randomised away. Members are pooled and re-dealt into groups of exactly the real
    sizes, preserving the number of groups, the size distribution, the coachable/sink split and
    the total membership. Only which turn sits in which group is destroyed.

    Coherence is mean cosine to a population's own centroid, so ANY router aiming at a point
    inside the data cloud carves a compact cell and scores for that reason alone, while a
    description vector sits off the turn manifold. If this arm reaches the exemplar arm's
    share, the metric is measuring in-manifold routing rather than correct routing.
    """
    rng = np.random.default_rng(ctx.seed)
    fit = ctx.fit_members()
    pool = [i for m in fit for i in m]
    rng.shuffle(pool)
    pv, pk, at = [], [], 0
    for c, mem in enumerate(fit):
        if not mem:
            continue
        take = pool[at:at + len(mem)]
        at += len(mem)
        if len(take) < MIN_TRAIN_MEMBERS:
            continue
        pv.append(ctx.vecs[take].mean(axis=0))
        pk.append(ctx.owner[c])
    pv = _unit(np.stack(pv).astype(np.float32))
    scores = _pool_max(ctx.eval_vecs, pv, np.array(pk, dtype=np.int32), len(ctx.keys))
    return routing_from_scores(scores, ctx.keys, ctx.coach, len(pv),
                               "PLACEBO: centroids of a size-matched random partition")


def make_blend(alpha: float):
    """`a * centroid + (1-a) * description`, renormalised. Cheap fusion of the two families."""
    def arm(ctx: ArmContext) -> Routing:
        if ctx.desc_vecs is None:
            raise ValueError("blend needs desc_vecs")
        cen = np.zeros((len(ctx.keys), ctx.vecs.shape[1]), dtype=np.float32)
        got = np.zeros(len(ctx.keys), dtype=bool)
        acc: dict[int, list[int]] = {}
        for c, mem in enumerate(ctx.fit_members()):
            if mem:
                acc.setdefault(int(ctx.owner[c]), []).extend(mem)
        for k, mem in acc.items():
            cen[k] = ctx.vecs[mem].mean(axis=0)
            got[k] = True
        use = got & ctx.desc_have
        mix = _unit(alpha * _unit(cen[use]) + (1.0 - alpha) * ctx.desc_vecs[use])
        scores = np.full((len(ctx.eval_idx), len(ctx.keys)), -np.inf, dtype=np.float32)
        scores[:, np.flatnonzero(use)] = ctx.eval_vecs @ mix.T
        return routing_from_scores(scores, ctx.keys, ctx.coach, int(use.sum()),
                                   f"{alpha:.2f}*centroid + {1 - alpha:.2f}*description")
    return arm


def make_text_arm(vectors_by_key: dict[str, np.ndarray], note: str):
    """Arm from externally supplied per-key text vectors (LLM rewrites, synthetic utterances).

    Several vectors per key are allowed and max-pooled, so `desc_synthetic_utterances` scores
    a turn against its closest generated utterance rather than against their average -- the
    average of k utterances drifts back toward exactly the generic prose centroid this arm
    exists to escape.
    """
    def arm(ctx: ArmContext) -> Routing:
        pv, pk = [], []
        for ki, k in enumerate(ctx.keys):
            v = vectors_by_key.get(k)
            if v is None:
                continue
            v = np.atleast_2d(np.asarray(v, dtype=np.float32))
            for row in v:
                pv.append(row)
                pk.append(ki)
        if not pv:
            raise ValueError(f"text arm {note!r} produced no vectors")
        pv = _unit(np.stack(pv))
        scores = _pool_max(ctx.eval_vecs, pv, np.array(pk, dtype=np.int32), len(ctx.keys))
        return routing_from_scores(scores, ctx.keys, ctx.coach, len(pv), note)
    return arm


FREE_ARMS: dict = {
    "description": arm_description,
    "centroid": arm_centroid,
    "centroid_pooled": arm_centroid_pooled,
    "medoid": arm_medoid,
    "submeans": arm_submeans,
    "knn_max": arm_knn_max,
    "knn_topk_mean": arm_knn_topk_mean,
    "probe": arm_probe,
    "placebo_centroid": arm_placebo_centroid,
}
for _a in BLEND_ALPHAS:
    FREE_ARMS[f"blend_a{_a:.2f}"] = make_blend(_a)


def abstain(routing: Routing, margin_floor: float) -> np.ndarray:
    """Accept only when the arm also beat the runner-up by `margin_floor`.

    The orthogonal decision rule, kept out of the arms on purpose: it composes with any of
    them and its threshold must be DERIVED from the measured margin distribution rather than
    chosen, which the harness does by sweeping percentiles of that arm's own margins.
    """
    return routing.accepted & (routing.margin >= margin_floor)


def arm_split_member_accept_desc_dest(ctx: ArmContext) -> Routing:
    """*** THE SPLIT ROUTER: member turns decide WHETHER, prose decides WHERE. ***

    Every one of the 16 arms benchmarked on 2026-08-16 used a SINGLE scoring function for two
    different decisions, and blinded reading of real turns says those decisions have different
    winners: `description` chose the better destination (11-8, and 7-3 on confident calls)
    while `centroid_pooled` made the better accept/reject call (8-4). Neither significant on
    n=20/n=12, so this arm is a HYPOTHESIS, not a finding.

    The mechanism is plausible rather than post-hoc: a sink's `business_description` is prose
    written to describe filler ("Client providing routine backchannels"), which is a poor
    template to match a real utterance against, whereas a sink cluster's own member turns ARE
    filler and match it directly. Conversely a coachable scenario's prose names its subject
    matter explicitly, which is what a destination choice needs.

    Rejection still happens exactly one way -- a sink key wins the accept vote -- so the junk
    filter is unchanged in kind.
    """
    acc_scores, _ = pooled_centroid_scores(ctx)
    acc_best = np.argmax(acc_scores, axis=1)
    accepted = ctx.coach[acc_best]

    if ctx.desc_vecs is None:
        raise ValueError("split arm needs desc_vecs")
    dest = np.full((len(ctx.eval_idx), len(ctx.keys)), -np.inf, dtype=np.float32)
    have = np.flatnonzero(ctx.desc_have & ctx.coach)          # coachable destinations only
    dest[:, have] = ctx.eval_vecs @ ctx.desc_vecs[have].T
    dest_best = np.argmax(dest, axis=1)

    rows = np.arange(len(acc_best))
    final = np.where(accepted, dest_best, acc_best)
    # Margin comes from whichever signal actually DECIDED that turn, so the reported spread
    # means the same thing it does for the single-signal arms.
    src = np.where(accepted[:, None], dest, acc_scores)
    part = np.partition(src, -2, axis=1)
    margin = (src[rows, final] - part[:, -2]).astype(np.float32)
    return Routing(keys=[ctx.keys[i] for i in final], accepted=ctx.coach[final],
                   margin=margin, best_sim=src[rows, final].astype(np.float32),
                   n_points=len(have),
                   note="SPLIT: member centroids accept/reject, description destination")


FREE_ARMS["split_member_accept"] = arm_split_member_accept_desc_dest
NEEDS_MEMBERSHIP = NEEDS_MEMBERSHIP | {"split_member_accept"}
