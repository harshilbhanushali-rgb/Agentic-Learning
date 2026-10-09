#!/usr/bin/env python3
"""T1: can a PER-CLAUSE relative rule make Layer C's relevance filter reject mis-routing?

Spec: docs/superpowers/specs/2026-08-17-layer-c-relative-filter-and-rescue-design.md
(gates frozen before this file existed). Also runs T3 (denominator defect sizing), D1
(sink-flag blindness) and writes D2's noise pool for the separate --stage noise-read.

Stages (from Brain/, venv python):
    python calibration/layer_c_relative_filter.py --stage instrument
    python calibration/layer_c_relative_filter.py --stage downstream
    python calibration/layer_c_relative_filter.py --stage noise-read

instrument  deterministic, no clustering: sweeps the frozen rule grid over real vs permuted
            pools, prints the survival table, applies the frozen G-T1a gate and operating-
            point rule, writes lcfr_instrument.json.
downstream  runs pass-1 arms {real, permuted} x {p40, chosen rule} (rule arms skipped on a
            NULL instrument), F0-checks the real/p40 arm against the PUBLISHED control,
            applies G-T1b, runs T3 + D1, writes the D2 noise pool and the T1 read samples.
noise-read  spaCy content-free shares of noise vs clustered vs gate-failed clauses (D2).
            Separate process because it loads a second en_core_web_lg.

ZERO chat calls, cache-only embeddings (abort on miss), ZERO Postgres.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR
from calibration.lcfr_common import (
    RULE_GRID, CSLS_NEIGHBOURHOOD, GT1A_PASS_PP, GT1A_NULL_PP, GT1A_MIN_REAL_SURVIVAL,
    GT1B_PERM_VOLUME_MAX, GT1B_SANITY_BAND,
    load_substrate, permuted_by_key, coachable_matrix, unit_rows, r_neighbourhood,
    rule_mask, p40_filter, relative_filter, pass1_lcfr, provenance, write_arm_artifact)

INSTRUMENT_OUT = ARTIFACTS_DIR / "lcfr_instrument.json"
DIAG_OUT = ARTIFACTS_DIR / "lcfr_diagnostics.json"
NOISE_OUT = ARTIFACTS_DIR / "lcfr_noise_pool.json"
T1_READ_SAMPLES = ARTIFACTS_DIR / "lcfr_t1_read_samples.txt"
T3_FLIP_SAMPLES = ARTIFACTS_DIR / "lcfr_t3_flip_samples.txt"
PUBLISHED_CONTROL = ARTIFACTS_DIR / "layer_bc_s0a0r0_b.json"


# ---------------------------------------------------------------------------------------
# shared pool building
# ---------------------------------------------------------------------------------------

def build_pools(by_key: dict) -> dict[str, dict]:
    """scenario_key -> prefilter clause pool (texts, calls, positions, pair order kept).
    Uses production build_clause_pool, once per scenario."""
    from v2.layer_c import build_clause_pool
    pools = {}
    for k in sorted(by_key):
        clauses, positions, calls, pair_ids = build_clause_pool(by_key[k])
        if clauses:
            pools[k] = {"clauses": clauses, "positions": positions, "calls": calls,
                        "pair_ids": pair_ids}
    return pools


def embed_union(pools_list: list[dict]) -> dict[str, np.ndarray]:
    """One deduplicated embedding lookup for every clause text in every pool.
    The real and permuted arms share one union by construction of the permutation,
    so this also guarantees both arms see byte-identical vectors per text."""
    from preprocessing import embedder
    texts = sorted({c for pools in pools_list for p in pools.values() for c in p["clauses"]})
    print(f"[embed] {len(texts)} distinct clause texts (cache-only)", flush=True)
    U = embedder.embed_document_matrix(texts)
    U = unit_rows(np.asarray(U, dtype=np.float32))
    return {t: U[i] for i, t in enumerate(texts)}


def pool_matrix(pool: dict, vec_of: dict) -> np.ndarray:
    return np.stack([vec_of[c] for c in pool["clauses"]])


# ---------------------------------------------------------------------------------------
# stage: instrument
# ---------------------------------------------------------------------------------------

def stage_instrument(a) -> None:
    from v2.layer_c import _relevance_filter

    sub = load_substrate(a.taxonomy, a.recordings, a.width)
    rng = random.Random(a.seed)
    keys_c, S = coachable_matrix(sub)
    pos_of = {k: i for i, k in enumerate(keys_c)}

    real = build_pools(sub.by_key)
    perm = build_pools(permuted_by_key(sub, rng))
    vec_of = embed_union([real, perm])

    # CSLS scenario-side term over the DEDUPLICATED union population (identical for both
    # arms; multiplicity deliberately not counted, so "Yeah." x600 is one neighbour).
    union_mat = np.stack(list(vec_of.values()))
    ry = r_neighbourhood((union_mat @ S.T).T, CSLS_NEIGHBOURHOOD)

    counts = {("p40", ""): {"real": [0, 0], "perm": [0, 0]}}
    for rule, param in RULE_GRID:
        counts[(rule, param)] = {"real": [0, 0], "perm": [0, 0]}

    pct = sub.tuning.layer_c.milestone_relevance_percentile
    for arm_name, pools in (("real", real), ("perm", perm)):
        for k, pool in sorted(pools.items()):
            C = pool_matrix(pool, vec_of)
            sims = C @ S.T
            own = pos_of[k]
            rx = r_neighbourhood(sims, CSLS_NEIGHBOURHOOD)
            n = len(pool["clauses"])
            kept_p40 = len(_relevance_filter(
                pool["clauses"], C, pool["positions"], pool["calls"], pool["pair_ids"],
                sub.scenario_map[k], pct)[0])
            c = counts[("p40", "")][arm_name]
            c[0] += kept_p40
            c[1] += n
            for rule, param in RULE_GRID:
                mask = rule_mask(rule, param, sims, own,
                                 rx if rule == "csls" else None,
                                 ry if rule == "csls" else None)
                c = counts[(rule, param)][arm_name]
                c[0] += int(mask.sum())
                c[1] += n

    # R0 arithmetic check: a percentile filter keeps >= (100-pct)% of anything, both arms.
    for arm_name in ("real", "perm"):
        kept, tot = counts[("p40", "")][arm_name]
        assert kept / tot >= (100 - pct) / 100 - 0.001, \
            f"p40 baseline survived {kept/tot:.3f} on {arm_name} -- production filter misapplied"

    rows = []
    for (rule, param), c in counts.items():
        sr = c["real"][0] / c["real"][1]
        sp = c["perm"][0] / c["perm"][1]
        rows.append({"rule": rule, "param": param, "survival_real": sr,
                     "survival_perm": sp, "gap": sr - sp})

    print("\n" + "=" * 86)
    print(f"T1 INSTRUMENT -- clause survival, real vs permuted routing ({a.taxonomy})")
    print("=" * 86)
    print(f"  {'rule':<10}{'param':>7}{'real':>10}{'permuted':>10}{'gap(pp)':>10}")
    for r in rows:
        print(f"  {r['rule']:<10}{r['param']:>7}{r['survival_real']:>10.3f}"
              f"{r['survival_perm']:>10.3f}{100*r['gap']:>10.1f}")

    # Frozen operating-point rule: max gap s.t. survival_real >= 0.50; ties -> higher real
    # survival, then simpler rule family (grid order encodes the simplicity ranking).
    order = {"p40": 0, "rank": 1, "margin": 2, "demean": 3, "csls": 4}
    eligible = [r for r in rows if r["rule"] != "p40"
                and r["survival_real"] >= GT1A_MIN_REAL_SURVIVAL]
    chosen = max(eligible, key=lambda r: (r["gap"], r["survival_real"], -order[r["rule"]]),
                 default=None)
    best_gap = chosen["gap"] if chosen else 0.0
    verdict = ("PASS" if best_gap >= GT1A_PASS_PP else
               "WEAK" if best_gap >= GT1A_NULL_PP else "NULL")
    print(f"\n  G-T1a: best eligible gap {100*best_gap:.1f}pp "
          f"(PASS >= {100*GT1A_PASS_PP:.0f}, NULL < {100*GT1A_NULL_PP:.0f}) -> {verdict}")
    if chosen:
        print(f"  operating point: {chosen['rule']}({chosen['param']}) "
              f"real {chosen['survival_real']:.3f} / perm {chosen['survival_perm']:.3f}")

    INSTRUMENT_OUT.write_text(json.dumps({
        "provenance": provenance(sub, a.seed, {"stage": "instrument"}),
        "gate": {"verdict": verdict, "best_gap": best_gap,
                 "pass_pp": GT1A_PASS_PP, "null_pp": GT1A_NULL_PP,
                 "min_real_survival": GT1A_MIN_REAL_SURVIVAL},
        "chosen": chosen, "rows": rows,
        "scen_keys": keys_c, "ry": [float(v) for v in ry],
    }, indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {INSTRUMENT_OUT.name}. ZERO chat calls, cache-only embeddings.")


# ---------------------------------------------------------------------------------------
# stage: downstream
# ---------------------------------------------------------------------------------------

def run_pass1_arm(name: str, sub, by_key: dict, filter_fn, capture: bool) -> dict:
    per_scenario: dict[str, dict] = {}
    todo = sorted(sub.coachable.items())
    print(f"\n[{name}] Pass 1 over {len(todo)} coachable scenario(s)...", flush=True)
    for n, (key, info) in enumerate(todo, 1):
        responses = by_key.get(key, [])
        res = pass1_lcfr(dict(info, scenario_key=key), responses,
                         sub.tuning.layer_c, filter_fn, capture=capture)
        per_scenario[key] = res
        print(f"  [{n}/{len(todo)}] {key[:44]:<44} {res['n_clauses']:>5}cl -> "
              f"{res['n_clauses_after_relevance']:>5} -> {len(res['milestones']):>2} ms "
              f"({res['outcome']})", flush=True)
    return per_scenario


def f0_check(real_p40: dict) -> dict:
    """The harness's own validity gate: the p40/real arm must reproduce the PUBLISHED
    control. Compares per-scenario clause counts and the ordered milestone evidence
    (support_calls, support_clauses, support_call_files). Milestone labels are HDBSCAN
    cluster ids and may renumber; the position-ordered evidence sequence may not."""
    if not PUBLISHED_CONTROL.exists():
        return {"status": "SKIPPED", "reason": f"{PUBLISHED_CONTROL.name} not on disk"}
    pub = json.loads(PUBLISHED_CONTROL.read_text(encoding="utf-8-sig"))["per_scenario"]
    mism = []
    if set(pub) != set(real_p40):
        mism.append(f"scenario sets differ: {sorted(set(pub) ^ set(real_p40))[:4]}")
    for k in sorted(set(pub) & set(real_p40)):
        a, b = pub[k], real_p40[k]
        for field in ("n_clauses", "n_clauses_after_relevance", "outcome"):
            if a.get(field) != b.get(field):
                mism.append(f"{k}.{field}: {a.get(field)} vs {b.get(field)}")
        ev_a = [(m["support_calls"], m["support_clauses"], m.get("support_call_files"))
                for m in a.get("milestones", [])]
        ev_b = [(m["support_calls"], m["support_clauses"], m.get("support_call_files"))
                for m in b.get("milestones", [])]
        if ev_a != ev_b:
            mism.append(f"{k}: milestone evidence differs "
                        f"({len(ev_a)} vs {len(ev_b)} milestones)")
    status = "PASS" if not mism else "FAIL"
    print(f"\n[F0] harness-vs-published control: {status}"
          + (f" -- {len(mism)} mismatch(es); NOTHING from this harness may be reported:"
             if mism else ""))
    for m in mism[:10]:
        print(f"  {m}")
    return {"status": status, "mismatches": mism}


def stage_downstream(a) -> None:
    from shared import cluster_evidence
    from v2.layer_c import _sink_centroids

    inst = json.loads(INSTRUMENT_OUT.read_text(encoding="utf-8-sig"))
    chosen, verdict = inst["chosen"], inst["gate"]["verdict"]
    run_rule_arms = verdict in ("PASS", "WEAK") and chosen is not None
    print(f"[instrument] G-T1a {verdict}"
          + (f", rule {chosen['rule']}({chosen['param']})" if chosen else ""), flush=True)

    sub = load_substrate(a.taxonomy, a.recordings, a.width)
    rng = random.Random(a.seed)
    by_real = sub.by_key
    by_perm = permuted_by_key(sub, rng)  # same seed & order as instrument -> same permutation

    keys_c, S = coachable_matrix(sub)
    if keys_c != inst["scen_keys"]:
        raise SystemExit("scenario key order differs from the instrument run -- ry term "
                         "would be misaligned; rerun --stage instrument first")
    ry = np.asarray(inst["ry"], dtype=np.float32)

    ident_base = provenance(sub, a.seed, {"segment": "s0", "admit": "a0", "router": "r0"})
    arms: dict[str, dict] = {}

    # --- real/p40 (control + capture for rescue/T3/D1/D2) --------------------------------
    arms["real_p40"] = run_pass1_arm("real_p40", sub, by_real,
                                     p40_filter(sub.tuning.layer_c), capture=True)
    f0 = f0_check(arms["real_p40"])
    write_arm_artifact("real_p40", sub, arms["real_p40"],
                       dict(ident_base, filter="p40", routing="real", f0=f0))
    if f0["status"] == "FAIL":
        raise SystemExit("F0 FAILED -- fix the harness before running anything else.")

    # --- rescue (T2) runs here so it reuses the captured state; logic lives in
    # layer_c_noise_rescue and only post-processes real_p40's clustering -----------------
    from calibration.layer_c_noise_rescue import run_rescue
    run_rescue(sub, arms["real_p40"], seed=a.seed, ident_base=ident_base)

    # --- perm/p40 (capture only for D1 centroids) ----------------------------------------
    arms["perm_p40"] = run_pass1_arm("perm_p40", sub, by_perm,
                                     p40_filter(sub.tuning.layer_c), capture=True)
    write_arm_artifact("perm_p40", sub, arms["perm_p40"],
                       dict(ident_base, filter="p40", routing="permuted"))

    # --- D1: is the sink-similarity review flag blind to mis-routing? --------------------
    sink_keys, sink_cents = _sink_centroids(sub.scenario_map)
    diag: dict = {"d1": None}
    if len(sink_cents):
        pctl = sub.tuning.layer_c.milestone_sink_similarity_percentile
        sims_by_arm = {}
        for arm_name in ("real_p40", "perm_p40"):
            sims = []
            for k, res in arms[arm_name].items():
                cap = res.get("_capture")
                if not cap:
                    continue
                surviving_ids = {m["cluster_id"] for m in res["milestones"]}
                for cand in cap.get("candidates", []):
                    if cand["cluster_id"] in surviving_ids:
                        _, sim = cluster_evidence.nearest_sink_index(
                            cand["_centroid"], sink_cents)
                        sims.append(sim)
            sims_by_arm[arm_name] = sims
        d1 = {}
        for arm_name, sims in sims_by_arm.items():
            if sims:
                thr = cluster_evidence.review_flag_threshold(sims, pctl)
                d1[arm_name] = {"n": len(sims), "threshold": thr,
                                "flag_rate_within": float(np.mean(
                                    np.asarray(sims) >= thr))}
        if all(sims_by_arm.get(x) for x in ("real_p40", "perm_p40")):
            thr_r = d1["real_p40"]["threshold"]
            thr_p = d1["perm_p40"]["threshold"]
            d1["cross"] = {
                "perm_flagged_at_real_threshold": float(np.mean(
                    np.asarray(sims_by_arm["perm_p40"]) >= thr_r)),
                "real_flagged_at_perm_threshold": float(np.mean(
                    np.asarray(sims_by_arm["real_p40"]) >= thr_p))}
        diag["d1"] = d1
        print(f"\n[D1] sink-flag rates: {json.dumps(d1, default=float)[:400]}", flush=True)

    # --- D2 noise pool (texts only; the spaCy pass is a separate process) ---------------
    noise_dump = {}
    for k, res in arms["real_p40"].items():
        cap = res.get("_capture")
        if not cap:
            continue
        labels = np.asarray(cap["labels"])
        clustered_ids = {m["cluster_id"] for m in res["milestones"]}
        failed, kept = [], []
        for cand in cap.get("candidates", []):
            (kept if cand["cluster_id"] in clustered_ids else failed).extend(cand["clauses"])
        noise_dump[k] = {
            "noise": [cap["clauses"][i] for i in np.flatnonzero(labels == -1)],
            "clustered_kept": kept, "gate_failed": failed}
    NOISE_OUT.write_text(json.dumps(noise_dump, indent=1), encoding="utf-8")
    print(f"[D2] wrote {NOISE_OUT.name}", flush=True)

    # --- T3: the denominator defect, sized on real/p40 ----------------------------------
    t3_rows, flip_samples = [], []
    t = sub.tuning.layer_c
    for k, res in arms["real_p40"].items():
        if res.get("required_support") is None:
            continue
        req_orig = res["required_support"]
        eff = res["scenario_calls_effective_preflt"]
        req_eff = cluster_evidence.required_milestone_support(
            eff, t.min_milestone_call_fraction, t.min_milestone_calls_floor)
        flips = [c for c in res["candidates_pregate"]
                 if req_eff <= c["support_calls"] < req_orig]
        t3_rows.append({"scenario": k, "scenario_calls": res["scenario_calls"],
                        "effective_preflt": eff,
                        "effective_postflt": res["scenario_calls_effective_postflt"],
                        "required_orig": req_orig, "required_eff": req_eff,
                        "n_flipped": len(flips)})
        cap = res.get("_capture")
        if flips and cap:
            by_id = {c["cluster_id"]: c for c in cap.get("candidates", [])}
            for f in flips:
                cand = by_id.get(f["cluster_id"])
                if cand:
                    flip_samples.append({"scenario": k, **{kk: f[kk] for kk in
                                        ("cluster_id", "support_calls")},
                                        "clauses": cand["clauses"][:6]})
    diag["t3"] = {"rows": t3_rows,
                  "scenarios_required_drops": sum(1 for r in t3_rows
                                                  if r["required_eff"] < r["required_orig"]),
                  "milestones_flipped": sum(r["n_flipped"] for r in t3_rows)}
    rng3 = random.Random(a.seed + 3)
    rng3.shuffle(flip_samples)
    T3_FLIP_SAMPLES.write_text(
        "\n\n".join(f"[{s['scenario']} / cluster {s['cluster_id']} / "
                    f"support {s['support_calls']}]\n" + "\n".join(
                        f"  - {c}" for c in s["clauses"])
                    for s in flip_samples[:5]) or "(no flips)", encoding="utf-8")
    print(f"[T3] required drops in {diag['t3']['scenarios_required_drops']} scenario(s); "
          f"{diag['t3']['milestones_flipped']} milestone(s) flip fail->pass", flush=True)

    # free the heavy captures before the remaining UMAP arms
    for arm_name in ("real_p40", "perm_p40"):
        for res in arms[arm_name].values():
            res.pop("_capture", None)

    # --- rule arms -----------------------------------------------------------------------
    if run_rule_arms:
        filt = relative_filter(chosen["rule"], chosen["param"], keys_c, S,
                               ry if chosen["rule"] == "csls" else None)
        arms["real_rule"] = run_pass1_arm("real_rule", sub, by_real, filt, capture=False)
        write_arm_artifact("real_rule", sub, arms["real_rule"],
                           dict(ident_base, filter=f"{chosen['rule']}({chosen['param']})",
                                routing="real"))
        arms["perm_rule"] = run_pass1_arm("perm_rule", sub, by_perm, filt, capture=False)
        write_arm_artifact("perm_rule", sub, arms["perm_rule"],
                           dict(ident_base, filter=f"{chosen['rule']}({chosen['param']})",
                                routing="permuted"))

        vol = {n: sum(r["n_clauses_after_relevance"] for r in arms[n].values())
               for n in arms}
        r_p40 = vol["perm_p40"] / max(vol["real_p40"], 1)
        r_rule = vol["perm_rule"] / max(vol["real_rule"], 1)
        lo, hi = GT1B_SANITY_BAND
        gt1b = {"vol": vol, "perm_over_real_p40": r_p40, "perm_over_real_rule": r_rule,
                "sanity_pass": lo <= r_p40 <= hi,
                "rule_pass": r_rule <= GT1B_PERM_VOLUME_MAX,
                "pass": lo <= r_p40 <= hi and r_rule <= GT1B_PERM_VOLUME_MAX}
        diag["gt1b"] = gt1b
        print(f"\n[G-T1b] p40 perm/real volume {r_p40:.3f} (band {lo}-{hi}) | "
              f"rule perm/real {r_rule:.3f} (must be <= {GT1B_PERM_VOLUME_MAX}) -> "
              f"{'PASS' if gt1b['pass'] else 'FAIL'}", flush=True)

        # T1 read samples: where the two filters DISAGREE on real pools, sampled without
        # printing any text -- first sight is the samples file.
        from v2.layer_c import _relevance_filter, build_clause_pool
        from preprocessing import embedder
        rmv_by_rule, kept_by_rule = [], []
        pct = sub.tuning.layer_c.milestone_relevance_percentile
        pos_of = {k: i for i, k in enumerate(keys_c)}
        for k in sorted(by_real):
            clauses, positions, calls, pair_ids = build_clause_pool(by_real[k])
            if len(clauses) < 6:
                continue
            C = unit_rows(np.asarray(embedder.embed_document_matrix(clauses), np.float32))
            kept_p40 = set(_relevance_filter(
                list(range(len(clauses))), C, positions, calls, pair_ids,
                sub.scenario_map[k], pct)[0])
            sims = C @ S.T
            rx = r_neighbourhood(sims, CSLS_NEIGHBOURHOOD)
            mask = rule_mask(chosen["rule"], chosen["param"], sims, pos_of[k],
                             rx if chosen["rule"] == "csls" else None,
                             ry if chosen["rule"] == "csls" else None)
            for i, c in enumerate(clauses):
                if i in kept_p40 and not mask[i]:
                    rmv_by_rule.append((k, c))
                elif i not in kept_p40 and mask[i]:
                    kept_by_rule.append((k, c))
        rng2 = random.Random(a.seed + 1)
        rng2.shuffle(rmv_by_rule)
        rng2.shuffle(kept_by_rule)
        lines = ["== REMOVED by rule, KEPT by p40 (20 samples) =="]
        lines += [f"[{k}] {c}" for k, c in rmv_by_rule[:20]]
        lines += ["", "== KEPT by rule, REMOVED by p40 (20 samples) =="]
        lines += [f"[{k}] {c}" for k, c in kept_by_rule[:20]]
        T1_READ_SAMPLES.write_text("\n".join(lines), encoding="utf-8")
        diag["t1_disagreement"] = {"removed_by_rule_kept_by_p40": len(rmv_by_rule),
                                   "kept_by_rule_removed_by_p40": len(kept_by_rule)}
        print(f"[T1 read] wrote {T1_READ_SAMPLES.name} "
              f"({len(rmv_by_rule)} vs {len(kept_by_rule)} disagreements)", flush=True)

    DIAG_OUT.write_text(json.dumps({
        "provenance": provenance(sub, a.seed, {"stage": "downstream"}),
        "instrument_verdict": verdict, "chosen": chosen, **diag,
    }, indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {DIAG_OUT.name}. ZERO chat calls. NOTHING written to Postgres.")


# ---------------------------------------------------------------------------------------
# stage: noise-read (D2)
# ---------------------------------------------------------------------------------------

def stage_noise_read(a) -> None:
    from calibration.diagnose_layer_a_noise import content_free_flags

    dump = json.loads(NOISE_OUT.read_text(encoding="utf-8-sig"))
    cats = {"noise": [], "clustered_kept": [], "gate_failed": []}
    for rec in dump.values():
        for c in cats:
            cats[c].extend(rec.get(c, []))
    print(f"{'category':<16}{'clauses':>9}{'content-free':>14}")
    out = {}
    for c, texts in cats.items():
        if not texts:
            out[c] = None
            continue
        flags = content_free_flags(texts)
        share = sum(flags) / len(flags)
        out[c] = {"n": len(texts), "content_free_share": share}
        print(f"{c:<16}{len(texts):>9}{share:>13.1%}")
    rng = random.Random(a.seed + 2)
    noise = list(cats["noise"])
    rng.shuffle(noise)
    samples = ARTIFACTS_DIR / "lcfr_noise_samples.txt"
    samples.write_text("\n".join(f"- {t}" for t in noise[:15]), encoding="utf-8")
    (ARTIFACTS_DIR / "lcfr_d2.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote lcfr_d2.json and {samples.name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stage", required=True,
                   choices=["instrument", "downstream", "noise-read"])
    p.add_argument("--taxonomy", default="clean2_base")
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--width", type=int, default=3072)
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    {"instrument": stage_instrument, "downstream": stage_downstream,
     "noise-read": stage_noise_read}[a.stage](a)


if __name__ == "__main__":
    main()
