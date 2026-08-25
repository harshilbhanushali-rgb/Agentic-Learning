#!/usr/bin/env python3
"""LAYER C POOLING-UNIT TRIAL: clause vs window vs turn. Zero chat calls, zero Postgres.

Spec: docs/superpowers/specs/2026-08-18-layer-c-pool-unit-design.md (arms and gates V0-V4
frozen there BEFORE this file existed). Predecessors: stage 1 (data null) and the
clustering bench (no winner) — this trial varies the ONE never-varied variable, the unit
Layer C embeds and clusters.

DESIGN INVARIANTS (from the spec):

* `u0` clause is the bench's `c0` ARTIFACT, reused, never re-run. V0 instead checks the
  substrate: this process's production clause path (build_clause_pool -> production
  _relevance_filter) must reproduce the stage-1 artifact's per-scenario `clause_pool`
  list-identically. Any diff -> harness bug, nothing reportable.
* Units change the GEOMETRY the clusterer sees, never the bookkeeping. Every milestone
  RESOLVES to its underlying clause set (canonical-membership rule); support is distinct
  CALLS; all cross-arm accounting and blind-read display run on resolved clause sets.
* Production code, never paraphrased: segmentation (production `build_clause_pool` loop
  via the production segmenter), relevance filter (production `_relevance_filter` called
  with unit texts), granularity + support rules (`cluster_evidence.*`), clustering
  (`_cluster_milestones_seeded` from the bench — constructor-identical paraphrase,
  F0-SEED-proven == production at seed 42 on this same substrate).
* Window rule (frozen): contiguous non-overlapping windows of 3 clauses per response;
  a remainder of 2 stays a window; a remainder of 1 merges into the previous window;
  a response with < 3 clauses is one window.
* Early-exit thresholds mirror production numerically on the arm's own pool:
  < 2 responses / < 6 units prefilter / < 6 units post-filter.
* Bench conventions carried over: no truncation at the hard cap (flagged loudly,
  symmetric), artifacts carry started_at/pid/base_seed/shas/tuning, `--overwrite`
  refuses by default, cache-only embedder shim (aborts on a miss) after one bounded
  `--fetch` (the ONLY gateway spend, run BEFORE anything else).

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/layer_c_pool_unit.py --fetch
    ..\\.venv\\Scripts\\python.exe calibration/layer_c_pool_unit.py --smoke
    ..\\.venv\\Scripts\\python.exe calibration/layer_c_pool_unit.py --run
    ..\\.venv\\Scripts\\python.exe calibration/layer_c_pool_unit.py --score
    # V4 stability (survivors, spec section 3):
    ..\\.venv\\Scripts\\python.exe calibration/layer_c_pool_unit.py --run --base-seed 1
    ..\\.venv\\Scripts\\python.exe calibration/layer_c_pool_unit.py --score --base-seed 1
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402

STAGE1_ARTIFACT = ARTIFACTS_DIR / "layer_bc_xp_union.json"
UNION_WEIGHTS = ARTIFACTS_DIR / "null_draw_weights_union.json"
OLD_DIR = "recordings"
NEW_DIR = "recordings_pull_keep"
TAXONOMY = "clean2_base"
WIDTH = 3072
SEED = 42
WINDOW = 3
TRIALS = 20_000
ARMS = ("u_win", "u_turn")          # u0 = the bench's c0 artifact, reused
V1_FLOOR_FRAC = 0.5                 # spec V1: below half of u0's milestones = support-starved


def c0_path(base_seed: int) -> Path:
    suffix = "" if base_seed == SEED else f"_b{base_seed}"
    return ARTIFACTS_DIR / f"layer_bc_cb_c0{suffix}.json"


def arm_path(arm: str, base_seed: int) -> Path:
    suffix = "" if base_seed == SEED else f"_b{base_seed}"
    return ARTIFACTS_DIR / f"layer_bc_pu_{arm}{suffix}.json"


def report_path(base_seed: int) -> Path:
    suffix = "" if base_seed == SEED else f"_b{base_seed}"
    return ARTIFACTS_DIR / f"layer_c_pu_report{suffix}.json"


# ---------------------------------------------------------------------------------------
# pure functions (unit-tested in tests/test_layer_c_pool_unit.py)
# ---------------------------------------------------------------------------------------

def window_spans(n: int, size: int = WINDOW) -> list[tuple[int, int]]:
    """The frozen window rule as index spans over one response's n clauses.
    Contiguous, non-overlapping, size-3; remainder 2 stays a window; remainder 1 merges
    into the previous window; n < size -> one span."""
    if n <= 0:
        return []
    if n < size:
        return [(0, n)]
    spans = [(i, min(i + size, n)) for i in range(0, n, size)]
    if len(spans) > 1 and spans[-1][1] - spans[-1][0] == 1:
        last = spans.pop()
        spans[-1] = (spans[-1][0], last[1])
    return spans


def units_from_response(clauses: list[str], call: str, mode: str) -> list[dict]:
    """One response's units under `mode`. Positions mirror production build_clause_pool:
    clause i of an m-clause response sits at i / max(m-1, 1); a unit's position is the
    median of its member clauses' positions. Unit text = member clauses joined with a
    single space (the derivable text the --fetch embeds)."""
    m = len(clauses)
    if m == 0:
        return []
    denom = max(m - 1, 1)
    pos = [i / denom for i in range(m)]
    if mode == "u_turn":
        spans = [(0, m)]
    elif mode == "u_win":
        spans = window_spans(m)
    else:
        raise ValueError(f"unknown unit mode {mode!r}")
    out = []
    for a, b in spans:
        member = clauses[a:b]
        out.append({"text": " ".join(member), "clauses": member, "call": call,
                    "position": float(np.median(pos[a:b]))})
    return out


def build_units(responses: list[dict], mode: str, segment_fn) -> list[dict]:
    """All units for one scenario's responses, response order preserved (the same loop
    shape as production build_clause_pool, so unit order is deterministic)."""
    units = []
    for resp in responses:
        clauses = segment_fn(resp["response_text"])
        units.extend(units_from_response(clauses, resp["call_filename"], mode))
    return units


def resolved_milestones(labels, units: list[dict], relevance: dict[str, float],
                        scenario_calls: int, required: int) -> tuple[list[dict], int]:
    """The ONE support gate + canonical-membership resolution. Support = distinct CALLS
    among member units; the milestone's clause list is the concatenation of member units'
    clauses in pool order (deterministic). Returns (surviving, n_candidates_pregate)."""
    groups: dict[int, list[int]] = defaultdict(list)
    for i, label in enumerate(np.asarray(labels)):
        if label == -1:
            continue
        groups[int(label)].append(i)
    surviving = []
    for label in sorted(groups):
        idx = groups[label]
        cand_calls = [units[i]["call"] for i in idx]
        support = len(set(cand_calls))
        if support < required:
            continue
        surviving.append({
            "cluster_id": label,
            "clauses": [cl for i in idx for cl in units[i]["clauses"]],
            "n_units": len(idx),
            "support_calls": support,
            "support_clauses": sum(len(units[i]["clauses"]) for i in idx),
            "support_call_files": sorted(set(cand_calls)),
            "support_frac": support / max(scenario_calls, 1),
            "median_position": float(np.median([units[i]["position"] for i in idx])),
            "relevance_mean": float(np.mean([relevance[units[i]["text"]] for i in idx])),
        })
    surviving.sort(key=lambda m: m["median_position"])
    return surviving, len(groups)


def noise_rate(labels) -> float:
    labels = np.asarray(labels)
    return float((labels == -1).sum() / len(labels)) if len(labels) else float("nan")


# ---------------------------------------------------------------------------------------
# substrate (bench-identical construction; F0 = V0 against the stage-1 artifact)
# ---------------------------------------------------------------------------------------

def build_substrate(smoke: bool = False):
    from calibration.layer_bc_arms import (taxonomy_path, scenario_map_from_rows,
                                           install_embedder_shim, prewarm, build_pairs,
                                           parse_corpus, corpus_sha, taxonomy_sha)
    from calibration.expanded_pool_stage1 import assert_no_stem_collision
    from shared.scenario_vectors import scenario_text
    from shared.tuning import load_tuning
    from v1.layer_b import assign_scenarios

    stage1 = json.loads(STAGE1_ARTIFACT.read_text(encoding="utf-8-sig"))
    if not stage1.get("f0_union", {}).get("pass"):
        raise SystemExit("stage-1 artifact failed its own F0 — no valid reference")

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

    return {"stage1": stage1, "coachable": coachable, "by_key": dict(by_key),
            "cluster_of_key": cluster_of_key, "tuning": load_tuning(),
            "corpus_sha": corpus_sha(pairs), "taxonomy_sha": taxonomy_sha(scenario_map)}


def unit_texts_for_fetch(sub) -> list[str]:
    """Every unit text either arm will ever embed, over the full coachable-routed corpus.
    Uses the production segmenter through the same loop as the run."""
    from preprocessing import segmenter
    texts: set[str] = set()
    for key in sorted(sub["coachable"]):
        responses = sub["by_key"].get(key, [])
        if len(responses) < 2:
            continue
        for mode in ARMS:
            for u in build_units(responses, mode, segmenter.segment_into_clauses):
                texts.add(u["text"])
    return sorted(texts)


def fetch(workers: int = 20) -> None:
    """The ONE bounded gateway spend. Resumable (embed_cached skips cached rows);
    verified by a cache re-read. Needs the Joveo VPN."""
    from calibration.trial_pool_unit_gemini import embed_cached
    from calibration.layer_bc_arms import _load_cached

    sub = build_substrate()
    uniq = unit_texts_for_fetch(sub)
    print(f"[fetch] {len(uniq)} distinct unit texts (u_win + u_turn)", flush=True)
    embed_cached(uniq, workers)
    mat, missing = _load_cached(uniq, WIDTH)
    if mat is None:
        raise SystemExit(f"ABORT: {len(missing)} unit text(s) STILL uncached after the "
                         f"fetch, e.g. {missing[:2]!r}")
    print("[verify] re-read of the cache: 0 unit texts missing")
    print("PU FETCH COMPLETE", flush=True)


# ---------------------------------------------------------------------------------------
# --run
# ---------------------------------------------------------------------------------------

def run_trial(arms: list[str], base_seed: int, overwrite: bool,
              smoke: bool = False) -> None:
    from preprocessing import embedder, segmenter
    from shared import cluster_evidence
    from v2.layer_c import build_clause_pool, _relevance_filter
    from calibration.layer_c_cluster_bench import _cluster_milestones_seeded

    if not smoke:
        for arm in arms:
            p = arm_path(arm, base_seed)
            if p.exists() and not overwrite:
                raise SystemExit(f"{p.name} exists — pass --overwrite or drop the arm")

    sub = build_substrate(smoke)
    tuning = sub["tuning"].layer_c
    pctl = tuning.milestone_relevance_percentile
    stage1_ps = sub["stage1"]["per_scenario"]

    per_arm: dict[str, dict] = {a: {} for a in arms}
    v0_fail: list[str] = []
    t0 = time.time()

    todo = sorted(sub["coachable"].items())
    if smoke:
        todo = todo[:2]
        print("[SMOKE] 2 scenarios only; V0 reported but NOT gating on a sliced corpus; "
              "NO artifacts will be written", flush=True)

    for n, (key, info) in enumerate(todo, 1):
        responses = sub["by_key"].get(key, [])
        scenario_calls = len({r["call_filename"] for r in responses})
        base_rec = {"n_responses": len(responses), "scenario_calls": scenario_calls,
                    "cluster_id": sub["cluster_of_key"].get(key, "")}

        # ---- V0: the production CLAUSE path must reproduce stage 1's post-filter pool.
        # Mirrors pass1_lcfr's exits exactly (clause_pool is [] on every fallback).
        expect = (stage1_ps.get(key) or {}).get("clause_pool", [])
        got: list[str] = []
        if len(responses) >= 2:
            clauses, positions, calls, pair_ids = build_clause_pool(responses)
            if len(clauses) >= 6:
                vecs = embedder.embed_document_matrix(clauses)
                fc, _, _, _, _, _ = _relevance_filter(clauses, vecs, positions, calls,
                                                      pair_ids, info, pctl)
                got = fc if len(fc) >= 6 else []
        if got != expect:
            v0_fail.append(key)

        # ---- the unit arms
        for arm in arms:
            rec = dict(base_rec)
            if len(responses) < 2:
                rec.update({"outcome": "fallback_too_few_responses", "milestones": [],
                            "noise_rate": float("nan")})
                per_arm[arm][key] = rec
                continue
            units = build_units(responses, arm, segmenter.segment_into_clauses)
            rec["n_units"] = len(units)
            if len(units) < 6:
                rec.update({"outcome": "fallback_too_few_clauses", "milestones": [],
                            "noise_rate": float("nan")})
                per_arm[arm][key] = rec
                continue
            texts = [u["text"] for u in units]
            uvecs = embedder.embed_document_matrix(texts)
            f_texts, f_vecs, f_pos, f_calls, f_idx, relevance = _relevance_filter(
                texts, uvecs, [u["position"] for u in units],
                [u["call"] for u in units], list(range(len(units))), info, pctl)
            f_units = [units[i] for i in f_idx]
            rec["n_units_after_relevance"] = len(f_units)
            if len(f_units) < 6:
                rec.update({"outcome": "fallback_too_few_relevant", "milestones": [],
                            "noise_rate": float("nan")})
                per_arm[arm][key] = rec
                continue

            mcs = cluster_evidence.milestone_min_cluster_size(
                len(f_units), tuning.min_cluster_size_fraction,
                tuning.min_cluster_size_floor, tuning.min_cluster_size_ceiling)
            required = cluster_evidence.required_milestone_support(
                scenario_calls, tuning.min_milestone_call_fraction,
                tuning.min_milestone_calls_floor)
            labels = _cluster_milestones_seeded(np.asarray(f_vecs, dtype=np.float32),
                                                mcs, tuning.umap_n_components, base_seed)
            ms, n_cands = resolved_milestones(labels, f_units, relevance,
                                              scenario_calls, required)
            capped = len(ms) > tuning.milestone_hard_cap
            if capped:
                print(f"    !! {arm}/{key}: {len(ms)} milestones EXCEEDS hard cap "
                      f"{tuning.milestone_hard_cap} — flagged, NOT truncated (symmetric).",
                      flush=True)
            rec.update({"outcome": ("clustered" if ms else
                                    "fallback_no_support" if n_cands else
                                    "fallback_no_clusters"),
                        "milestones": ms, "noise_rate": noise_rate(labels),
                        "n_candidates_pregate": n_cands, "mcs_used": mcs,
                        "required_support": required, "hard_cap_exceeded": capped})
            per_arm[arm][key] = rec

        counts = {a: len(per_arm[a][key].get("milestones") or []) for a in arms}
        flag = "" if got == expect else "  ** V0 DIVERGED **"
        print(f"  [{n}/{len(todo)}] {key[:36]:<36} {len(responses):>5}p "
              + " ".join(f"{a}:{v}" for a, v in counts.items()) + flag, flush=True)

    ident = {"started_at": datetime.datetime.now().isoformat(timespec="seconds"),
             "pid": os.getpid(), "base_seed": base_seed, "width": WIDTH,
             "window": WINDOW, "corpus_sha": sub["corpus_sha"],
             "taxonomy_sha": sub["taxonomy_sha"],
             "stage1_artifact": STAGE1_ARTIFACT.name, "v0_fail": v0_fail,
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
            "arm": f"pu_{arm}", "identity": ident, "chat_calls": 0,
            "noise_rate_mean": float(np.mean(nr)) if nr else float("nan"),
            "stats": stats, "per_scenario": ps,
        }, indent=1, default=float), encoding="utf-8")
        print(f"[artifact] {arm_path(arm, base_seed).name}: {stats['n_milestones']} ms, "
              f"noise {float(np.mean(nr))*100 if nr else float('nan'):.1f}%", flush=True)

    print(f"\nV0 (clause path vs stage-1 pools): "
          f"{'PASS' if not v0_fail else f'** FAIL {v0_fail} **'}"
          + ("  (smoke: informational only)" if smoke else ""))
    print(f"done in {(time.time()-t0)/60:.1f} min. ZERO chat calls, ZERO Postgres writes.")


# ---------------------------------------------------------------------------------------
# --score: V1 + V3 + resolved-set accounting vs the bench c0 artifact. Free.
# ---------------------------------------------------------------------------------------

def score(base_seed: int) -> None:
    from collections import Counter
    from calibration import layer_b_arms as lb
    from calibration.layer_bc_arms import match_milestones
    from calibration.expanded_pool_stage1 import merge_account_maps
    from calibration.flag_proper_noun_clusters import account_map

    cp = c0_path(base_seed)
    if not cp.exists():
        raise SystemExit(f"{cp.name} missing — the bench c0 artifact is u0's reference "
                         f"(run the bench at this base seed first)")
    c0 = json.loads(cp.read_text(encoding="utf-8-sig"))
    if c0["identity"].get("f0_bench_fail"):
        raise SystemExit("bench c0 artifact carries an F0 failure — not a valid reference")

    arts = {}
    for arm in ARMS:
        p = arm_path(arm, base_seed)
        if p.exists():
            arts[arm] = json.loads(p.read_text(encoding="utf-8-sig"))
    if not arts:
        raise SystemExit("no pool-unit artifacts at this base seed — run the trial first")

    for name, art in arts.items():
        if art["identity"].get("v0_fail"):
            raise SystemExit(f"V0 FAILED on {art['identity']['v0_fail']} — nothing "
                             f"reportable; fix the harness, do not score.")
        for fld in ("corpus_sha", "taxonomy_sha"):
            if art["identity"].get(fld) != c0["identity"].get(fld):
                raise SystemExit(f"ABORT: {name!r} ran on a different substrate ({fld}).")

    acct_old_raw, _ = account_map(OLD_DIR)
    acct_new_raw, _ = account_map(NEW_DIR)
    if not acct_old_raw or not acct_new_raw:
        raise SystemExit("ABORT: an account map came back empty — missing sidecars would "
                         "manufacture a null.")
    acct_union, _ = lb.collapse_sibling_domains(
        merge_account_maps([acct_old_raw, acct_new_raw]))
    w_union = json.loads(UNION_WEIGHTS.read_text(encoding="utf-8-sig"))
    pool = lb.corpus_account_pool(acct_union, w_union["weights"])
    ks = lb.union_cluster_ks([c0["per_scenario"]]
                             + [a["per_scenario"] for a in arts.values()], acct_union)
    table = lb.expected_neff_table(pool, ks, trials=TRIALS, seed=SEED)
    st_c0 = lb.per_cluster_stats(c0["per_scenario"], acct_union, table)

    c0_ms = c0["stats"]["n_milestones"]
    print("=" * 100)
    print(f"LAYER C POOL-UNIT TRIAL — base seed {base_seed}  "
          f"(spec 2026-08-18-layer-c-pool-unit)")
    print("=" * 100)
    print(f"  u0 (bench c0): {c0_ms} ms, noise {c0['noise_rate_mean']*100:.1f}%")
    print(f"\n  {'arm':<9}{'miles':>7}{'noise%':>8}{'match':>7}{'merged':>7}{'split':>7}"
          f"{'lost':>6}{'gained':>7}{'lift up/dn':>12}{'p':>9}{'V1':>4}{'V3':>4}")

    rows = {}
    for arm, art in arts.items():
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
        d = lb.compare_arms(st_c0, lb.per_cluster_stats(art["per_scenario"],
                                                        acct_union, table), "lift")
        v1 = art["stats"]["n_milestones"] >= V1_FLOOR_FRAC * c0_ms
        v3 = not (d["down"] > d["up"] and d["p"] < 0.05)
        rows[arm] = {"milestones": art["stats"]["n_milestones"],
                     "noise": art["noise_rate_mean"], "matched": oc["matched"],
                     "merged": oc["merged"], "split": oc["split"], "lost": oc["lost"],
                     "gained": gained_n, "lift": d, "v1": v1, "v3": v3}
        print(f"  {arm:<9}{rows[arm]['milestones']:>7}{art['noise_rate_mean']*100:>8.1f}"
              f"{oc['matched']:>7}{oc['merged']:>7}{oc['split']:>7}{oc['lost']:>6}"
              f"{gained_n:>7}{d['up']:>6}/{d['down']:<5}{d['p']:>9.4f}"
              f"{'  Y' if v1 else '  n':>4}{'  Y' if v3 else '  n':>4}")

    print(f"\n  V1 floor = {V1_FLOOR_FRAC} x u0 = {V1_FLOOR_FRAC * c0_ms:.0f} milestones "
          f"(support-starved below it — cannot win)")
    print("  V2 (blind read) runs only for arms clearing V1+V3; V4 = seeds 1 and 7.")

    report_path(base_seed).write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "base_seed": base_seed,
        "u0": {"milestones": c0_ms, "noise": c0["noise_rate_mean"]},
        "arms": rows,
    }, indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {report_path(base_seed).name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fetch", action="store_true",
                   help="bounded gateway fetch of every unit text, then verify (VPN)")
    p.add_argument("--run", action="store_true")
    p.add_argument("--score", action="store_true")
    p.add_argument("--smoke", action="store_true",
                   help="end-to-end PATH TEST: 25+25 calls, 2 scenarios, nothing written")
    p.add_argument("--arms", default=",".join(ARMS))
    p.add_argument("--base-seed", type=int, default=SEED)
    p.add_argument("--overwrite", action="store_true")
    a = p.parse_args()
    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    bad = [x for x in arms if x not in ARMS]
    if bad:
        raise SystemExit(f"unknown arm(s) {bad}; registry: {ARMS}")
    if a.fetch:
        fetch()
    if a.run or a.smoke:
        run_trial(arms, a.base_seed, a.overwrite, smoke=a.smoke)
    if a.score:
        score(a.base_seed)
    if not (a.fetch or a.run or a.score or a.smoke):
        p.print_help()


if __name__ == "__main__":
    main()
