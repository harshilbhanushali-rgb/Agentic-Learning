#!/usr/bin/env python3
"""GOLD-PAIR PROBE: does the embedding space encode SAME-MOVE similarity at all?

Run 2026-08-18 on operator instruction WITHOUT a standalone spec ("just do it and run") —
the design is frozen in this docstring instead, before any labeling or scoring ran.

QUESTION. Seven pipeline-internal closures point at one untested assumption: that clauses
instantiating the same coaching MOVE sit nearer each other in gemini@3072 space than
clauses about the same TOPIC doing different moves. If they do not, no clustering method
on these vectors can ever recover moves, and the representation must change. This probe
measures exactly that, with human-free but blinded-and-controlled LLM labelers building
the gold standard by READING, never by seeing a vector.

DESIGN (frozen before any label was collected):

* SOURCE: the stage-1 union substrate (production parse -> pairs -> routing -> production
  p40 filter), cache-only embeddings. The 10 largest coachable scenarios by post-filter
  pool size; ONE batch of 18 clauses per scenario, sampled seeded (rng 42) with a
  distinct-call constraint (max 2 clauses per call, >= 8 distinct calls per batch).
  Candidate selection NEVER touches the embedding space (no cosine, no lexical
  enrichment) — random within scenario, so the probe cannot be circular.
* ATTENTION CONTROL: each batch plants ONE verbatim duplicate of a sampled clause
  (Naren-repeats exist naturally; the plant is literal). A labeler who does not group
  the two identical texts together on >= 80% of batches is VOID.
* LABELING: 3 independent blinded labelers (small model, sequential, one at a time per
  operator limits rule). Each sees ONLY the batch texts (no calls, no scenario names, no
  counts) and partitions each batch into groups of "the same specific coaching move",
  singletons allowed. Labelers never see cosines; the key (clause -> call map, plant
  positions) lives in a separate file.
* GOLD PAIRS (unanimity rule): same-move gold = a clause pair ALL valid labelers placed
  in the same group; different-move gold = a pair ALL valid labelers separated. Plant
  pairs are excluded from gold. Pairs sharing a call are excluded from the PRIMARY
  (clustering needs cross-call recurrence; same-call pairs answer an easier question).
* PRIMARY METRIC — the per-anchor relative frame (the repo's own lesson: pooled AUC
  drowned a real 78.2% per-clause signal): every triplet (anchor a, same-move s,
  different-move d) with a,s,d from THREE distinct calls, same scenario. Score
  cos(a,s) > cos(a,d). Frozen bars, stated now:
    - SIGNAL PRESENT  = preference rate >= 0.70 AND two-sided sign test p < 0.05
    - MOVE-BLIND      = rate < 0.60, OR p >= 0.05
    - WEAK            = rate in [0.60, 0.70) with p < 0.05 (a signal too weak to
      cluster on — the 0.617/0.631 AUC precedents both live here)
  Ties (exact cosine equality) count against SIGNAL (conservative).
* SECONDARY: pooled AUC of cosine over same-move vs different-move gold pairs (for
  comparability with the retired 0.617 and the probe's 0.631 precedents); distribution
  summaries; per-scenario triplet breakdown; gold-pair counts and labeler agreement.
* NO gate is adjusted after seeing a result; a null (MOVE-BLIND) is a real result and
  redirects the program to representation change.

MATH COMPANION (--math, added on operator request BEFORE any labeling ran; label-free,
deterministic, judgment-free — the two instruments triangulate: math tests cannot see
"moves", the labeled probe can but rests on reader judgment):

  M1 Hopkins clusterability per pool vs a column-shuffled null (does ANY cluster
     tendency exist in these vectors?).
  M2 variance decomposition: share of embedding variance explained by CALL identity
     (eta^2) vs a call-label-permutation null — if vectors encode "which meeting" more
     than content, clusters form around sessions (the same-call-gluing mechanism).
  M3 lexical anchors: cross-call clause pairs with token-Jaccard >= 0.5 are same-move
     BY CONSTRUCTION (Naren's verbatim signature lines); their cosine separation (AUC)
     from random cross-call same-scenario pairs is a reader-free lower bound. Stated
     bias: covers only lexically-similar moves — exactly the labeled probe's complement.
  M4 kNN-graph (k=15, cosine) modularity via Leiden vs the same graph on
     column-shuffled vectors (structure destroyed, marginals kept), 3 null draws.

ROUND 2 AMENDMENT (recorded 2026-08-18 BEFORE any round-2 data existed). Round 1's
random-batch design produced exactly ONE cross-call unanimity gold pair — the labelers
were valid (10/10 attention checks each) but random 18-clause samples almost never
contain two instances of the same move. Round 1's printed verdict is therefore VOID FOR
POWER (26 triplets sharing one pair = pseudo-replication; effective n=1, directionally
positive). Round 2 fixes SAMPLING, not the metric's spirit:

  * NOMINATION (non-circular enrichment): one blinded agent reads 60-clause seeded
    samples per scenario (call-blind, embedding-blind) and NOMINATES candidate same-move
    pairs by reading alone. Nomination uses judgment, never vectors — so the probe still
    cannot inherit the embedding's own structure.
  * VERIFICATION: independent blinded verifiers judge each nominated pair YES/NO ("same
    specific move?") mixed 1:1 with random same-scenario cross-call distractor pairs and
    planted identical pairs (attention control, >= 80% YES required). Verifiers never
    see which pairs were nominated.
  * GOLD: same-move = nominated AND unanimous YES; different-move = distractor AND
    unanimous NO. Cross-call only. Pairs are the independent units.
  * ROUND-2 METRIC (frozen now): Mann-Whitney AUC of cosine over gold same vs gold diff
    pairs. SIGNAL PRESENT = AUC >= 0.70 AND MW p < 0.05 AND n_gold_same >= 10;
    MOVE-BLIND = AUC < 0.60 or p >= 0.05 (with n_gold_same >= 10);
    UNDERPOWERED = n_gold_same < 10 (report, do not verdict). WEAK between.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/gold_pair_probe.py --build
    ..\\.venv\\Scripts\\python.exe calibration/gold_pair_probe.py --math
    ..\\.venv\\Scripts\\python.exe calibration/gold_pair_probe.py --score
    ..\\.venv\\Scripts\\python.exe calibration/gold_pair_probe.py --nominate-build
    ..\\.venv\\Scripts\\python.exe calibration/gold_pair_probe.py --verify-build
    ..\\.venv\\Scripts\\python.exe calibration/gold_pair_probe.py --score2
"""
from __future__ import annotations

import argparse
import datetime
import json
import random
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402

STAGE1_ARTIFACT = ARTIFACTS_DIR / "layer_bc_xp_union.json"
BATCHES_TXT = ARTIFACTS_DIR / "gp_batches.txt"
BATCHES_KEY = ARTIFACTS_DIR / "gp_batches_KEY.json"
LABELS_TMPL = "gp_labels_{name}.json"          # in ARTIFACTS_DIR
REPORT = ARTIFACTS_DIR / "gp_report.json"
OLD_DIR = "recordings"
NEW_DIR = "recordings_pull_keep"
TAXONOMY = "clean2_base"
WIDTH = 3072
SEED = 42
N_SCEN = 10
BATCH = 18
MAX_PER_CALL = 2
MIN_CALLS = 8
DUP_ATTENTION_BAR = 0.8


# ---------------------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------------------

def sample_batch(clauses: list[str], calls: list[str], rng: random.Random,
                 batch: int = BATCH, max_per_call: int = MAX_PER_CALL,
                 min_calls: int = MIN_CALLS) -> list[int] | None:
    """Seeded random batch with the distinct-call constraint. Returns pool indices or
    None if the pool cannot satisfy the constraint. Never looks at a vector."""
    order = list(range(len(clauses)))
    rng.shuffle(order)
    taken: list[int] = []
    per_call: dict[str, int] = defaultdict(int)
    seen_texts: set[str] = set()
    for i in order:
        if len(taken) == batch:
            break
        if per_call[calls[i]] >= max_per_call:
            continue
        if clauses[i] in seen_texts:          # natural duplicates excluded; the plant is ours
            continue
        taken.append(i)
        per_call[calls[i]] += 1
        seen_texts.add(clauses[i])
    if len(taken) < batch or len({calls[i] for i in taken}) < min_calls:
        return None
    return taken


def groups_to_pairs(groups: list[list[int]]) -> tuple[set, set]:
    """A labeler's partition of item numbers -> (same-group pairs, cross-group pairs)."""
    same, items = set(), []
    for g in groups:
        items.extend(g)
        for a, b in combinations(sorted(g), 2):
            same.add((a, b))
    allp = {(a, b) for a, b in combinations(sorted(items), 2)}
    return same, allp - same


def sign_test_two_sided(up: int, down: int) -> float:
    from math import comb
    n = up + down
    if n == 0:
        return 1.0
    k = min(up, down)
    return min(1.0, sum(comb(n, i) for i in range(0, k + 1)) / 2 ** n * 2)


def auc(pos: list[float], neg: list[float]) -> float:
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


# ---------------------------------------------------------------------------------------
# --build
# ---------------------------------------------------------------------------------------

def build() -> None:
    from calibration.layer_bc_arms import (taxonomy_path, scenario_map_from_rows,
                                           install_embedder_shim, prewarm, build_pairs,
                                           parse_corpus)
    from calibration.expanded_pool_stage1 import assert_no_stem_collision
    from shared.scenario_vectors import scenario_text
    from shared.tuning import load_tuning
    from v1.layer_b import assign_scenarios
    from v2.layer_c import build_clause_pool, _relevance_filter
    from preprocessing import embedder

    if BATCHES_TXT.exists() or BATCHES_KEY.exists():
        raise SystemExit(f"{BATCHES_TXT.name} / its KEY already exist — refusing to "
                         f"clobber a labeling instrument; delete both deliberately.")

    tax_art = json.loads(taxonomy_path(TAXONOMY).read_text(encoding="utf-8-sig"))
    scenario_map, _ = scenario_map_from_rows(tax_art["rows"])
    coachable = {k: v for k, v in scenario_map.items() if v["is_coachable"]}

    parsed_old = parse_corpus(OLD_DIR)
    parsed_new = parse_corpus(NEW_DIR)
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

    pctl = load_tuning().layer_c.milestone_relevance_percentile
    pools = {}
    for key, info in coachable.items():
        responses = by_key.get(key, [])
        if len(responses) < 2:
            continue
        clauses, positions, calls, pair_ids = build_clause_pool(responses)
        if len(clauses) < 6:
            continue
        vecs = embedder.embed_document_matrix(clauses)
        fc, _, _, fcalls, _, _ = _relevance_filter(clauses, vecs, positions, calls,
                                                   pair_ids, info, pctl)
        pools[key] = (fc, fcalls)
    top = sorted(pools, key=lambda k: -len(pools[k][0]))[:N_SCEN]

    rng = random.Random(SEED)
    lines = [
        "MOVE-GROUPING TASK",
        "",
        "Each BATCH below is a set of sentences spoken by one sales expert across several",
        "different client calls on ONE broad topic. Your job: group the ITEM NUMBERS so",
        "that two items share a group ONLY if they are instances of THE SAME SPECIFIC",
        "COACHING MOVE — the same concrete thing the expert is doing (e.g. anchoring on a",
        "benchmark number, reframing cost as pipeline quality, proposing a specific test).",
        "Being about the same topic is NOT enough; a question and a recommendation about",
        "the same thing are DIFFERENT moves. Generic filler (greetings, thanks, scheduling)",
        "goes in its own group or singletons.",
        "",
        "Singletons are expected — most items will not have a same-move partner. Do not",
        "force groups. Use every item number exactly once per batch.",
        "=" * 96, ""]
    key_rows = {}
    for b, key in enumerate(top, 1):
        fc, fcalls = pools[key]
        idx = sample_batch(fc, fcalls, rng)
        if idx is None:
            print(f"  !! {key}: cannot satisfy the batch constraint — skipped", flush=True)
            continue
        items = [(fc[i], fcalls[i]) for i in idx]
        # plant the verbatim duplicate (attention control)
        dup_of = rng.randrange(len(items))
        items.append((items[dup_of][0], items[dup_of][1]))
        order = list(range(len(items)))
        rng.shuffle(order)
        lines.append(f"### BATCH {b}  ({len(items)} items)")
        num_of = {}
        for n, oi in enumerate(order, 1):
            num_of[oi] = n
            lines.append(f"  {n:>2}. {items[oi][0].strip()[:240]}")
        lines.append("")
        key_rows[str(b)] = {
            "scenario": key,
            "calls": {str(num_of[oi]): items[oi][1] for oi in order},
            "dup_pair": sorted([num_of[dup_of], num_of[len(items) - 1]]),
            "texts": {str(num_of[oi]): items[oi][0] for oi in order},
        }
    lines += [
        "=" * 96, "",
        "ANSWER FORMAT — return ONLY a JSON object, no prose:",
        '{"1": [[3,7],[2,11,14],[1],[4],...], "2": [...], ...}',
        "one key per batch number; each value is a list of groups; each group is a list",
        "of item numbers; every item number appears exactly once.",
    ]
    BATCHES_TXT.write_text("\n".join(lines), encoding="utf-8")
    BATCHES_KEY.write_text(json.dumps({
        "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "seed": SEED, "batches": key_rows,
    }, indent=1), encoding="utf-8")
    print(f"[build] {len(key_rows)} batches -> {BATCHES_TXT.name} "
          f"(KEY: {BATCHES_KEY.name} — labelers must never see it)")


# ---------------------------------------------------------------------------------------
# --math: label-free geometry battery over the same pools. Free, deterministic.
# ---------------------------------------------------------------------------------------

MATH_REPORT = ARTIFACTS_DIR / "gp_math_report.json"
LEX_JACCARD = 0.5
KNN_K = 15


def hopkins(X: np.ndarray, rng: np.random.Generator, m: int = 50) -> float:
    """Hopkins statistic on unit rows (cosine distance = monotone in euclidean on the
    sphere). ~0.5 = random; -> 1 = clusterable."""
    n = X.shape[0]
    m = min(m, n // 2)
    idx = rng.choice(n, size=m, replace=False)
    sample = X[idx]
    rest = np.delete(X, idx, axis=0)
    # nearest real neighbor distances for real points
    d_real = np.array([np.min(np.linalg.norm(rest - s, axis=1)) for s in sample])
    # uniform points on the data's bounding box, projected back to unit norm
    lo, hi = X.min(axis=0), X.max(axis=0)
    U = rng.uniform(lo, hi, size=(m, X.shape[1])).astype(np.float32)
    U /= (np.linalg.norm(U, axis=1, keepdims=True) + 1e-10)
    d_unif = np.array([np.min(np.linalg.norm(X - u, axis=1)) for u in U])
    return float(d_unif.sum() / (d_unif.sum() + d_real.sum() + 1e-12))


def eta_sq(X: np.ndarray, groups: list[str]) -> float:
    """Share of total variance explained by the grouping (multivariate eta^2)."""
    mu = X.mean(axis=0)
    sst = float(((X - mu) ** 2).sum())
    ssb = 0.0
    by: dict[str, list[int]] = defaultdict(list)
    for i, g in enumerate(groups):
        by[g].append(i)
    for idx in by.values():
        gm = X[idx].mean(axis=0)
        ssb += len(idx) * float(((gm - mu) ** 2).sum())
    return ssb / (sst + 1e-12)


def token_jaccard(a: str, b: str) -> float:
    ta, tb = set(a.lower().split()), set(b.lower().split())
    return len(ta & tb) / len(ta | tb) if ta | tb else 1.0


def knn_modularity(X: np.ndarray, seed: int, k: int = KNN_K) -> float:
    """Leiden modularity of the cosine kNN graph (the bench's graph construction)."""
    import igraph
    import leidenalg
    n = X.shape[0]
    k = min(k, n - 1)
    sims = X @ X.T
    np.fill_diagonal(sims, -np.inf)
    nbr = np.argpartition(-sims, k - 1, axis=1)[:, :k]
    edges, weights, seen = [], [], set()
    for i in range(n):
        for j in nbr[i]:
            key = (min(i, int(j)), max(i, int(j)))
            if key in seen:
                continue
            seen.add(key)
            edges.append(key)
            weights.append(max(float(sims[key[0], key[1]]), 1e-6))
    g = igraph.Graph(n=n, edges=edges)
    part = leidenalg.find_partition(g, leidenalg.ModularityVertexPartition,
                                    weights=weights, seed=seed, n_iterations=2)
    return float(g.modularity(part.membership, weights=weights))


def column_shuffled(X: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Structure-destroyed null: each dimension permuted independently across rows,
    then re-normalized. Marginals kept, joint structure gone."""
    Y = X.copy()
    for d in range(Y.shape[1]):
        rng.shuffle(Y[:, d])
    return Y / (np.linalg.norm(Y, axis=1, keepdims=True) + 1e-10)


def math_battery() -> None:
    from calibration.layer_bc_arms import _load_cached

    key = json.loads(BATCHES_KEY.read_text(encoding="utf-8-sig"))["batches"]
    # pools are rebuilt from the KEY's scenarios via the stage-1 artifact clause pools
    # (texts only) + the key's call maps are batch-level; for pool-level tests we use the
    # stage-1 artifact directly.
    stage1 = json.loads(STAGE1_ARTIFACT.read_text(encoding="utf-8-sig"))["per_scenario"]
    scens = [rows["scenario"] for rows in key.values()]

    out = {}
    rng = np.random.default_rng(SEED)
    print("=" * 90)
    print("GOLD-PAIR PROBE — math battery (label-free), pools = stage-1 post-p40")
    print("=" * 90)
    for scen in scens:
        pool = stage1[scen].get("clause_pool") or []
        calls_ms = stage1[scen].get("milestones") or []
        if len(pool) < 60:
            continue
        uniq = sorted(set(pool))
        mat, missing = _load_cached(uniq, WIDTH)
        if mat is None:
            raise SystemExit(f"{scen}: {len(missing)} clauses uncached")
        mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-10)

        h = hopkins(mat, rng)
        h0 = hopkins(column_shuffled(mat, rng), rng)
        q = knn_modularity(mat, SEED)
        q0 = float(np.mean([knn_modularity(column_shuffled(mat, rng), SEED + i)
                            for i in range(3)]))
        out[scen] = {"n": len(uniq), "hopkins": h, "hopkins_null": h0,
                     "modularity": q, "modularity_null": q0}
        print(f"  {scen[:42]:<42} n={len(uniq):>5}  H={h:.3f} (null {h0:.3f})  "
              f"Q={q:.3f} (null {q0:.3f})", flush=True)

    # M2 + M3 need call attribution -> use the batches' key maps (18x10 clauses) for M2's
    # spirit is pool-level; rebuild call maps from the union artifact milestones is not
    # possible per-clause, so M2/M3 run over the KEY batches' clauses (180 texts, call-
    # attributed, sampled without embedding involvement) plus ALL cross-call lexical
    # anchors minable from the batch texts.
    texts, calls, scens_of = [], [], []
    for b, rows in key.items():
        for n_, t in rows["texts"].items():
            texts.append(t)
            calls.append(rows["calls"][n_])
            scens_of.append(rows["scenario"])
    uniq = sorted(set(texts))
    mat, _ = _load_cached(uniq, WIDTH)
    mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-10)
    vec_of = {t: mat[i] for i, t in enumerate(uniq)}
    X = np.stack([vec_of[t] for t in texts])

    e_call = eta_sq(X, calls)
    e_scen = eta_sq(X, scens_of)
    null_e = []
    for i in range(20):
        perm = list(calls)
        rng.shuffle(perm)
        null_e.append(eta_sq(X, perm))
    e_null = float(np.mean(null_e))
    print(f"\n  M2 variance by CALL identity: eta2={e_call:.3f} "
          f"(perm null {e_null:.3f}) | by SCENARIO: {e_scen:.3f}")

    # M3 over the FULL pools (batches are far too small to contain verbatim repeats):
    # seeded 400-clause subsample per scenario, cross-call pairs only, EXACT duplicates
    # excluded (identical text -> identical vector -> cosine 1.0 tests nothing about the
    # space; the informative anchors are 0.5 <= jaccard < 1 near-repeats). Call
    # attribution comes from the milestone support maps we lack per clause, so M3
    # rebuilds per-pool call maps from the batches' scenarios via the union artifact's
    # per-scenario pools + a fresh substrate-free approximation: the stage-1 artifact
    # does not store per-clause calls, so M3 uses text identity across the KEY's batch
    # clauses where available and otherwise treats REPEATED IDENTICAL TEXT as the only
    # call-crossing evidence it cannot verify — therefore M3 drops the cross-call
    # REQUIREMENT and instead EXCLUDES pairs whose texts are identical; a near-repeat at
    # jaccard >= 0.5 with different surface text almost never comes from one utterance.
    pos, neg = [], []
    rnd = random.Random(SEED)
    for scen in scens:
        pool = list(dict.fromkeys(stage1[scen].get("clause_pool") or []))
        if len(pool) < 60:
            continue
        rnd.shuffle(pool)
        sub = pool[:400]
        toks = [set(t.lower().split()) for t in sub]
        submat, _ = _load_cached(sorted(set(sub)), WIDTH)
        submat = submat / (np.linalg.norm(submat, axis=1, keepdims=True) + 1e-10)
        v = {t: submat[i] for i, t in enumerate(sorted(set(sub)))}
        scen_neg = []
        for i, j in combinations(range(len(sub)), 2):
            if sub[i] == sub[j]:
                continue
            ta, tb = toks[i], toks[j]
            jac = len(ta & tb) / len(ta | tb) if ta | tb else 1.0
            c = float(v[sub[i]] @ v[sub[j]])
            if jac >= LEX_JACCARD:
                pos.append(c)
            else:
                scen_neg.append(c)
        rnd.shuffle(scen_neg)
        neg += scen_neg[:2000]
    a_lex = auc(pos, neg)
    print(f"  M3 lexical anchors (near-repeats, jaccard>={LEX_JACCARD}, exact dupes "
          f"excluded): n={len(pos)} anchors vs {len(neg)} random  AUC={a_lex:.3f}  "
          f"medians {np.median(pos) if pos else float('nan'):.4f} vs "
          f"{np.median(neg) if neg else float('nan'):.4f}")

    MATH_REPORT.write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "per_scenario": out,
        "m2": {"eta2_call": e_call, "eta2_call_null": e_null, "eta2_scenario": e_scen},
        "m3": {"n_anchors": len(pos), "n_random": len(neg), "auc": a_lex,
               "median_anchor": float(np.median(pos)) if pos else None,
               "median_random": float(np.median(neg)) if neg else None},
    }, indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {MATH_REPORT.name}")


# ---------------------------------------------------------------------------------------
# --score
# ---------------------------------------------------------------------------------------

def score() -> None:
    from calibration.layer_bc_arms import _load_cached

    key = json.loads(BATCHES_KEY.read_text(encoding="utf-8-sig"))["batches"]
    labelers = {}
    for p in sorted(ARTIFACTS_DIR.glob(LABELS_TMPL.format(name="*"))):
        name = p.stem.replace("gp_labels_", "")
        labelers[name] = json.loads(p.read_text(encoding="utf-8-sig"))
    if len(labelers) < 2:
        raise SystemExit("need >= 2 labeler files (artifacts/gp_labels_<name>.json)")

    # validity: the planted duplicate must be same-group on >= 80% of batches
    valid = {}
    for name, lab in labelers.items():
        ok = 0
        for b, rows in key.items():
            groups = lab.get(b) or []
            same, _ = groups_to_pairs(groups)
            if tuple(rows["dup_pair"]) in same:
                ok += 1
        frac = ok / len(key)
        print(f"[labeler {name}] duplicate-pair grouped in {ok}/{len(key)} batches "
              f"-> {'VALID' if frac >= DUP_ATTENTION_BAR else 'VOID'}")
        if frac >= DUP_ATTENTION_BAR:
            valid[name] = lab
    if len(valid) < 2:
        raise SystemExit("fewer than 2 valid labelers — the probe is void, relabel")

    trip_up = trip_down = trip_tie = 0
    pos_cos, neg_cos = [], []
    per_scen = defaultdict(lambda: [0, 0])
    n_gold_same = n_gold_diff = 0
    agree_same = []
    for b, rows in key.items():
        dup = set(rows["dup_pair"])
        nums = [n for n in rows["texts"] if int(n) not in dup or int(n) == rows["dup_pair"][0]]
        # unanimity gold over valid labelers, plant excluded
        sames, diffs = [], []
        for lab in valid.values():
            s, d = groups_to_pairs(lab.get(b) or [])
            sames.append(s)
            diffs.append(d)
        gold_same = set.intersection(*sames)
        gold_diff = set.intersection(*diffs)
        gold_same = {p for p in gold_same if not set(p) & dup}
        gold_diff = {p for p in gold_diff if not set(p) & dup}
        union_same = set.union(*sames)
        agree_same.append(len(gold_same) / len(union_same) if union_same else 1.0)

        texts = rows["texts"]
        calls = rows["calls"]
        uniq = sorted({texts[n] for n in texts})
        mat, missing = _load_cached(uniq, WIDTH)
        if mat is None:
            raise SystemExit(f"batch {b}: {len(missing)} clause(s) uncached — impossible "
                             f"(stage-1 pools are cached); wrong text mangling?")
        mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-10)
        vec = {t: mat[i] for i, t in enumerate(uniq)}
        cos = lambda a, b_: float(vec[texts[str(a)]] @ vec[texts[str(b_)]])

        cross_same = [p for p in gold_same if calls[str(p[0])] != calls[str(p[1])]]
        cross_diff = [p for p in gold_diff if calls[str(p[0])] != calls[str(p[1])]]
        n_gold_same += len(cross_same)
        n_gold_diff += len(cross_diff)
        pos_cos += [cos(*p) for p in cross_same]
        neg_cos += [cos(*p) for p in cross_diff]

        # triplets: anchor in a cross-call same pair + a cross-call diff partner,
        # all three from three distinct calls
        diff_of = defaultdict(list)
        for p in cross_diff:
            diff_of[p[0]].append(p[1])
            diff_of[p[1]].append(p[0])
        for a, s in cross_same + [(y, x) for x, y in cross_same]:
            for d in diff_of.get(a, []):
                if calls[str(d)] in (calls[str(a)], calls[str(s)]):
                    continue
                cs, cd = cos(a, s), cos(a, d)
                scen = rows["scenario"]
                if cs > cd:
                    trip_up += 1
                    per_scen[scen][0] += 1
                elif cd > cs:
                    trip_down += 1
                    per_scen[scen][1] += 1
                else:
                    trip_tie += 1

    n = trip_up + trip_down + trip_tie
    rate = trip_up / n if n else float("nan")
    p = sign_test_two_sided(trip_up, trip_down)
    a = auc(pos_cos, neg_cos)
    verdict = ("SIGNAL PRESENT" if n and rate >= 0.70 and p < 0.05 else
               "WEAK" if n and rate >= 0.60 and p < 0.05 else "MOVE-BLIND")

    print("=" * 90)
    print("GOLD-PAIR PROBE — does gemini@3072 encode same-move similarity?")
    print("=" * 90)
    print(f"  valid labelers: {sorted(valid)}  (unanimity gold; "
          f"mean same-pair agreement {np.mean(agree_same)*100:.0f}%)")
    print(f"  gold pairs (cross-call): same-move {n_gold_same}, different-move {n_gold_diff}")
    print(f"  cosine medians: same-move {np.median(pos_cos) if pos_cos else float('nan'):.4f} "
          f"| different-move {np.median(neg_cos) if neg_cos else float('nan'):.4f}")
    print(f"  secondary pooled AUC: {a:.3f}  (retired precedents: 0.617, 0.631)")
    print(f"\n  PRIMARY (per-anchor relative frame): {trip_up}/{n} triplets prefer the "
          f"same-move partner  (down={trip_down}, tie={trip_tie}, rate={rate:.3f}, "
          f"p={p:.5f})")
    print(f"  -> {verdict}   (bars frozen pre-labeling: >=0.70&p<.05 signal; "
          f"<0.60 or p>=.05 move-blind; between = weak)")
    for scen, (u, d) in sorted(per_scen.items(), key=lambda kv: -(kv[1][0] + kv[1][1])):
        print(f"     {scen[:44]:<44} {u:>3}up {d:>3}dn")

    REPORT.write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "valid_labelers": sorted(valid), "n_gold_same": n_gold_same,
        "n_gold_diff": n_gold_diff, "triplets": {"up": trip_up, "down": trip_down,
                                                 "tie": trip_tie},
        "preference_rate": rate, "p": p, "auc": a, "verdict": verdict,
        "cos_median_same": float(np.median(pos_cos)) if pos_cos else None,
        "cos_median_diff": float(np.median(neg_cos)) if neg_cos else None,
        "per_scenario": {k: {"up": v[0], "down": v[1]} for k, v in per_scen.items()},
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {REPORT.name}")


# ---------------------------------------------------------------------------------------
# ROUND 2: nominate (by reading) -> verify (blind) -> score2 (pair-level, independent)
# ---------------------------------------------------------------------------------------

NOM_TXT = ARTIFACTS_DIR / "gp_nominate.txt"
NOM_KEY = ARTIFACTS_DIR / "gp_nominate_KEY.json"
NOMINATIONS = ARTIFACTS_DIR / "gp_nominations.json"
VERIFY_TXT = ARTIFACTS_DIR / "gp_verify.txt"
VERIFY_KEY = ARTIFACTS_DIR / "gp_verify_KEY.json"
VERDICTS_TMPL = "gp_verdicts_{name}.json"
REPORT2 = ARTIFACTS_DIR / "gp_report2.json"
NOM_SAMPLE = 60
MAX_NOMS_PER_SCEN = 8
N_PLANT_IDENTICAL = 6
VERIFY_ATTENTION_BAR = 0.8


def nominate_build() -> None:
    """60-clause seeded samples per scenario for the nominator. Reuses --build's
    substrate work via the round-1 KEY? No — the KEY holds only 19-item batches, so this
    rebuilds pools the same way --build did (production path, cache-only)."""
    from calibration.layer_bc_arms import (taxonomy_path, scenario_map_from_rows,
                                           install_embedder_shim, prewarm, build_pairs,
                                           parse_corpus)
    from calibration.expanded_pool_stage1 import assert_no_stem_collision
    from shared.scenario_vectors import scenario_text
    from shared.tuning import load_tuning
    from v1.layer_b import assign_scenarios
    from v2.layer_c import build_clause_pool, _relevance_filter
    from preprocessing import embedder

    if NOM_TXT.exists() or NOM_KEY.exists():
        raise SystemExit(f"{NOM_TXT.name} / KEY exist — refusing to clobber")

    tax_art = json.loads(taxonomy_path(TAXONOMY).read_text(encoding="utf-8-sig"))
    scenario_map, _ = scenario_map_from_rows(tax_art["rows"])
    coachable = {k: v for k, v in scenario_map.items() if v["is_coachable"]}
    parsed_old = parse_corpus(OLD_DIR)
    parsed_new = parse_corpus(NEW_DIR)
    assert_no_stem_collision({p.stem for _, p, _ in parsed_old},
                             {p.stem for _, p, _ in parsed_new})
    pairs = (build_pairs(OLD_DIR, "s0", "a0", parsed=parsed_old)
             + build_pairs(NEW_DIR, "s0", "a0", parsed=parsed_new))
    prewarm([scenario_text(v) for v in scenario_map.values()], 20)
    install_embedder_shim(WIDTH)
    print(f"[substrate] routing {len(pairs)} pairs (production r0)...", flush=True)
    assign_scenarios(pairs, scenario_map, None)
    by_key = defaultdict(list)
    for p in pairs:
        k = p["scenario_key"]
        if k and scenario_map[k]["is_coachable"]:
            by_key[k].append(p)
    pctl = load_tuning().layer_c.milestone_relevance_percentile
    pools = {}
    for key, info in coachable.items():
        responses = by_key.get(key, [])
        if len(responses) < 2:
            continue
        clauses, positions, calls, pair_ids = build_clause_pool(responses)
        if len(clauses) < 6:
            continue
        vecs = embedder.embed_document_matrix(clauses)
        fc, _, _, fcalls, _, _ = _relevance_filter(clauses, vecs, positions, calls,
                                                   pair_ids, info, pctl)
        pools[key] = (fc, fcalls)
    top = sorted(pools, key=lambda k: -len(pools[k][0]))[:N_SCEN]

    rng = random.Random(SEED + 1)
    lines = [
        "SAME-MOVE NOMINATION TASK",
        "",
        "Each SECTION below is a sample of sentences by one sales expert across many",
        "client calls on one broad topic. NOMINATE pairs (or small sets) of item numbers",
        "that are instances of THE SAME SPECIFIC COACHING MOVE — the same concrete thing",
        "the expert does, said to different clients. Same topic is NOT enough; a question",
        "and a recommendation about the same thing are different moves. Only nominate",
        "pairs you are confident about; quality over quantity; up to 8 nominations per",
        "section; none is a valid answer for a section.",
        "=" * 96, ""]
    key_rows = {}
    for sec, key in enumerate(top, 1):
        fc, fcalls = pools[key]
        idx = sample_batch(fc, fcalls, rng, batch=min(NOM_SAMPLE, len(fc)),
                           max_per_call=3, min_calls=10)
        if idx is None:
            continue
        lines.append(f"### SECTION {sec}  ({len(idx)} items)")
        num_map = {}
        for n, i in enumerate(idx, 1):
            num_map[str(n)] = {"text": fc[i], "call": fcalls[i]}
            lines.append(f"  {n:>2}. {fc[i].strip()[:240]}")
        lines.append("")
        key_rows[str(sec)] = {"scenario": key, "items": num_map}
    lines += [
        "=" * 96, "",
        "ANSWER FORMAT — return ONLY a JSON object, no prose:",
        '{"1": [[3,17],[5,22,41]], "2": [], ...}',
        "one key per section number; each value is a list of nominated same-move sets",
        "(each set = 2+ item numbers). Sections with no confident nomination get [].",
    ]
    NOM_TXT.write_text("\n".join(lines), encoding="utf-8")
    NOM_KEY.write_text(json.dumps({"seed": SEED + 1, "sections": key_rows},
                                  indent=1), encoding="utf-8")
    print(f"[nominate-build] {len(key_rows)} sections -> {NOM_TXT.name}")


def verify_build() -> None:
    """Nominated pairs (cross-call only) + 1:1 random distractors + planted identicals,
    shuffled, YES/NO. Verifiers never learn which came from the nominator."""
    if VERIFY_TXT.exists() or VERIFY_KEY.exists():
        raise SystemExit(f"{VERIFY_TXT.name} / KEY exist — refusing to clobber")
    key = json.loads(NOM_KEY.read_text(encoding="utf-8-sig"))["sections"]
    noms = json.loads(NOMINATIONS.read_text(encoding="utf-8-sig"))
    rng = random.Random(SEED + 2)

    cand = []          # (scenario, textA, callA, textB, callB, source)
    for sec, sets in noms.items():
        rows = key.get(sec)
        if not rows:
            continue
        items = rows["items"]
        taken = 0
        for s in sets:
            for a, b in combinations(sorted(int(x) for x in s), 2):
                ia, ib = items.get(str(a)), items.get(str(b))
                if not ia or not ib or ia["call"] == ib["call"] or ia["text"] == ib["text"]:
                    continue
                if taken >= MAX_NOMS_PER_SCEN:
                    break
                cand.append((rows["scenario"], ia["text"], ia["call"],
                             ib["text"], ib["call"], "nominated"))
                taken += 1
    # distractors: random cross-call pairs from the same sections, 1:1
    per_scen = defaultdict(list)
    for sec, rows in key.items():
        items = list(rows["items"].values())
        per_scen[rows["scenario"]] += items
    n_by_scen = defaultdict(int)
    for c in cand:
        n_by_scen[c[0]] += 1
    for scen, n_ in n_by_scen.items():
        items = per_scen[scen]
        made = 0
        tries = 0
        while made < n_ and tries < 500:
            tries += 1
            ia, ib = rng.sample(items, 2)
            if ia["call"] == ib["call"] or ia["text"] == ib["text"]:
                continue
            cand.append((scen, ia["text"], ia["call"], ib["text"], ib["call"], "random"))
            made += 1
    # planted identicals
    all_items = [i for v in per_scen.values() for i in v]
    for i in rng.sample(all_items, N_PLANT_IDENTICAL):
        cand.append(("plant", i["text"], i["call"], i["text"], i["call"], "identical"))

    rng.shuffle(cand)
    lines = [
        "SAME-MOVE PAIR VERIFICATION",
        "",
        "Each ITEM shows two sentences by one sales expert, from different client calls",
        "on the same broad topic. Answer YES if they are instances of THE SAME SPECIFIC",
        "COACHING MOVE (the same concrete thing, said to different clients); NO otherwise.",
        "Same topic alone is NO. A question vs a recommendation about the same thing is NO.",
        "Answer every item:   <n>: YES   or   <n>: NO",
        "=" * 96, ""]
    key_rows = []
    for n, (scen, ta, ca, tb, cb, src) in enumerate(cand, 1):
        lines += [f"--- ITEM {n} ---", f"  X: {ta.strip()[:240]}",
                  f"  Y: {tb.strip()[:240]}", ""]
        key_rows.append({"item": n, "scenario": scen, "source": src,
                         "text_a": ta, "text_b": tb, "call_a": ca, "call_b": cb})
    VERIFY_TXT.write_text("\n".join(lines), encoding="utf-8")
    VERIFY_KEY.write_text(json.dumps({"pairs": key_rows}, indent=1), encoding="utf-8")
    from collections import Counter
    print(f"[verify-build] {Counter(r['source'] for r in key_rows)} -> {VERIFY_TXT.name}")


def score2() -> None:
    from calibration.layer_bc_arms import _load_cached

    key = json.loads(VERIFY_KEY.read_text(encoding="utf-8-sig"))["pairs"]
    verifiers = {}
    for p in sorted(ARTIFACTS_DIR.glob(VERDICTS_TMPL.format(name="*"))):
        verifiers[p.stem.replace("gp_verdicts_", "")] = json.loads(
            p.read_text(encoding="utf-8-sig"))
    if len(verifiers) < 2:
        raise SystemExit("need >= 2 verifier files (artifacts/gp_verdicts_<name>.json)")

    plants = [r["item"] for r in key if r["source"] == "identical"]
    valid = {}
    for name, v in verifiers.items():
        yes = sum(1 for i in plants if str(v.get(str(i), "")).upper() == "YES")
        ok = yes / len(plants) >= VERIFY_ATTENTION_BAR
        print(f"[verifier {name}] identical plants YES {yes}/{len(plants)} "
              f"-> {'VALID' if ok else 'VOID'}")
        if ok:
            valid[name] = v
    if len(valid) < 2:
        raise SystemExit("fewer than 2 valid verifiers — round 2 void")

    def unanimous(item, ans):
        return all(str(v.get(str(item), "")).upper() == ans for v in valid.values())

    gold_same = [r for r in key if r["source"] == "nominated" and unanimous(r["item"], "YES")]
    gold_diff = [r for r in key if r["source"] == "random" and unanimous(r["item"], "NO")]
    texts = sorted({t for r in key for t in (r["text_a"], r["text_b"])})
    mat, missing = _load_cached(texts, WIDTH)
    if mat is None:
        raise SystemExit(f"{len(missing)} verify text(s) uncached")
    mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-10)
    vec = {t: mat[i] for i, t in enumerate(texts)}
    pos = [float(vec[r["text_a"]] @ vec[r["text_b"]]) for r in gold_same]
    neg = [float(vec[r["text_a"]] @ vec[r["text_b"]]) for r in gold_diff]

    a = auc(pos, neg)
    # Mann-Whitney via normal approximation (n small -> also report exact-ish via AUC)
    n1, n2 = len(pos), len(neg)
    if n1 and n2:
        u = a * n1 * n2
        mu, sd = n1 * n2 / 2, (n1 * n2 * (n1 + n2 + 1) / 12) ** 0.5
        from math import erf
        z = (u - mu) / sd if sd else 0.0
        p = 2 * (1 - 0.5 * (1 + erf(abs(z) / 2 ** 0.5)))
    else:
        p = float("nan")
    verdict = ("UNDERPOWERED" if n1 < 10 else
               "SIGNAL PRESENT" if a >= 0.70 and p < 0.05 else
               "WEAK" if a >= 0.60 and p < 0.05 else "MOVE-BLIND")

    print("=" * 90)
    print("GOLD-PAIR PROBE ROUND 2 — pair-level, independent units")
    print("=" * 90)
    print(f"  gold same-move (nominated + unanimous YES): {n1}")
    print(f"  gold different (random + unanimous NO):     {n2}")
    print(f"  cosine medians: same {np.median(pos) if pos else float('nan'):.4f} | "
          f"diff {np.median(neg) if neg else float('nan'):.4f}")
    print(f"  AUC={a:.3f}  MW p={p:.5f}  -> {verdict}")
    print(f"  (bars frozen pre-data: >=0.70&p<.05 signal | <0.60 move-blind | "
          f"n_same<10 underpowered)")
    REPORT2.write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "valid_verifiers": sorted(valid), "n_gold_same": n1, "n_gold_diff": n2,
        "auc": a, "p": p, "verdict": verdict,
        "cos_median_same": float(np.median(pos)) if pos else None,
        "cos_median_diff": float(np.median(neg)) if neg else None,
        "gold_same_pairs": [{"scenario": r["scenario"], "a": r["text_a"][:120],
                             "b": r["text_b"][:120]} for r in gold_same],
    }, indent=1, default=float), encoding="utf-8")
    print(f"wrote {REPORT2.name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--build", action="store_true")
    p.add_argument("--math", action="store_true")
    p.add_argument("--score", action="store_true")
    p.add_argument("--nominate-build", action="store_true")
    p.add_argument("--verify-build", action="store_true")
    p.add_argument("--score2", action="store_true")
    a = p.parse_args()
    if a.build:
        build()
    if a.math:
        math_battery()
    if a.score:
        score()
    if a.nominate_build:
        nominate_build()
    if a.verify_build:
        verify_build()
    if a.score2:
        score2()
    if not (a.build or a.math or a.score or a.nominate_build or a.verify_build
            or a.score2):
        p.print_help()


if __name__ == "__main__":
    main()
