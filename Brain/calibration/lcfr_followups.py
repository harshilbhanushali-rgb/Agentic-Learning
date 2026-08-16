#!/usr/bin/env python3
"""F1 (support-targeted rescue) and F2 (conjunction sweep) — the re-aimed follow-ups.

Spec: docs/superpowers/specs/2026-08-17-layer-c-retargeted-followups-design.md
(gates frozen and committed before this file existed).

    python calibration/lcfr_followups.py --f2          # conjunction sweep, no clustering
    python calibration/lcfr_followups.py --f1          # support-targeted rescue (re-runs
                                                       # the real/p40 pass-1 with capture)
    python calibration/lcfr_followups.py --f1-build-read
    python calibration/lcfr_followups.py --f1-score-read judgments.json

Zero chat calls, cache-only embeddings (abort on miss), zero Postgres.
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
    GT1A_PASS_PP, GT1A_NULL_PP, GT1A_MIN_REAL_SURVIVAL,
    load_substrate, permuted_by_key, coachable_matrix, keep_rank,
    rescue_assign, placebo_assign, p40_filter, pass1_lcfr, provenance)

F1_OUT = ARTIFACTS_DIR / "lcfr_f1_targeted_rescue.json"
F1_READ_SAMPLES = ARTIFACTS_DIR / "lcfr_f1_read_samples.txt"
F1_READ_KEY = ARTIFACTS_DIR / "lcfr_f1_read_KEY.json"
F2_OUT = ARTIFACTS_DIR / "lcfr_f2_conjunction.json"
F2_READ_SAMPLES = ARTIFACTS_DIR / "lcfr_f2_read_samples.txt"
CONJ_KS = (8, 9, 10, 11, 12, 13, 14)   # frozen in the spec
UNDERPOWERED_FLOOR = 5                 # both arms below this many flips -> UNDERPOWERED-NULL


# ---------------------------------------------------------------------------------------
# pure helpers (unit-tested in tests/test_lcfr_followups.py)
# ---------------------------------------------------------------------------------------

def failing_members(candidates: list[dict], required: int, vecs) -> dict[int, "np.ndarray"]:
    """Destination set for F1: ONLY the clusters that fail the support gate today.
    A passing cluster must never appear -- that is the whole re-aim."""
    return {c["cluster_id"]: vecs[c["_idx"]] for c in candidates
            if c["support_calls"] < required}


def flips(candidates: list[dict], required: int, calls: list[str],
          adds: dict[int, list[int]], noise_rows: list[int]) -> set[int]:
    """Which failing clusters pass the gate once their additions' calls join the union."""
    out = set()
    for c in candidates:
        if c["support_calls"] >= required:
            continue
        add_calls = [calls[noise_rows[i]] for i in adds.get(c["cluster_id"], [])]
        support = len(set(c["support_call_files"]) | set(add_calls))
        if support >= required:
            out.add(c["cluster_id"])
    return out


def paired_flip_counts(failing_ids: list[int], rule_flips: set[int],
                       placebo_flips: set[int]) -> tuple[int, int, int]:
    """(up, down, tie) over failing clusters: up = rule flipped it and placebo did not."""
    up = down = tie = 0
    for cid in failing_ids:
        r, p = cid in rule_flips, cid in placebo_flips
        if r and not p:
            up += 1
        elif p and not r:
            down += 1
        else:
            tie += 1
    return up, down, tie


# ---------------------------------------------------------------------------------------
# F2 — conjunction sweep
# ---------------------------------------------------------------------------------------

def run_f2(a) -> None:
    from calibration.layer_c_relative_filter import build_pools, embed_union, pool_matrix
    from v2.layer_c import _relevance_filter

    sub = load_substrate(a.taxonomy, a.recordings, a.width)
    rng = random.Random(a.seed)
    keys_c, S = coachable_matrix(sub)
    pos_of = {k: i for i, k in enumerate(keys_c)}
    real = build_pools(sub.by_key)
    perm = build_pools(permuted_by_key(sub, rng))
    vec_of = embed_union([real, perm])
    pct = sub.tuning.layer_c.milestone_relevance_percentile

    counts = {k: {"real": [0, 0], "perm": [0, 0]} for k in CONJ_KS}
    # kept for the chosen-K disagreement read, real pools only
    per_pool_masks: dict[str, dict] = {}
    for arm, pools in (("real", real), ("perm", perm)):
        for key, pool in sorted(pools.items()):
            C = pool_matrix(pool, vec_of)
            n = len(pool["clauses"])
            kept_p40 = set(_relevance_filter(
                list(range(n)), C, pool["positions"], pool["calls"], pool["pair_ids"],
                sub.scenario_map[key], pct)[0])
            sims = C @ S.T
            masks = {k: keep_rank(sims, pos_of[key], k) for k in CONJ_KS}
            for k in CONJ_KS:
                c = counts[k][arm]
                c[0] += sum(1 for i in range(n) if i in kept_p40 and masks[k][i])
                c[1] += n
            if arm == "real":
                per_pool_masks[key] = {"kept_p40": kept_p40, "masks": masks,
                                       "clauses": pool["clauses"]}

    rows = []
    for k in CONJ_KS:
        sr = counts[k]["real"][0] / counts[k]["real"][1]
        sp = counts[k]["perm"][0] / counts[k]["perm"][1]
        rows.append({"k": k, "survival_real": sr, "survival_perm": sp, "gap": sr - sp})
    print(f"\n  {'K':>4}{'real':>10}{'permuted':>10}{'gap(pp)':>10}")
    for r in rows:
        print(f"  {r['k']:>4}{r['survival_real']:>10.3f}{r['survival_perm']:>10.3f}"
              f"{100*r['gap']:>10.1f}")

    eligible = [r for r in rows if r["survival_real"] >= GT1A_MIN_REAL_SURVIVAL]
    chosen = max(eligible, key=lambda r: (r["gap"], r["survival_real"], -r["k"]),
                 default=None)
    best_gap = chosen["gap"] if chosen else 0.0
    verdict = ("PASS" if best_gap >= GT1A_PASS_PP else
               "WEAK" if best_gap >= GT1A_NULL_PP else "NULL")
    print(f"\n  G-F2: best eligible gap {100*best_gap:.1f}pp -> {verdict}"
          + (f" at K={chosen['k']}" if chosen else " (no K meets the retention floor)"))

    if chosen:
        # disagreement read vs p40 alone, chosen K, real pools; no text printed here
        rmv, kept = [], []
        for key, rec in per_pool_masks.items():
            m = rec["masks"][chosen["k"]]
            for i, cl in enumerate(rec["clauses"]):
                if i in rec["kept_p40"] and not m[i]:
                    rmv.append((key, cl))
                # conjunction can only remove relative to p40; nothing is kept that p40
                # dropped, so the second direction is empty by construction -- say so.
        rng2 = random.Random(a.seed + 21)
        rng2.shuffle(rmv)
        lines = [f"== REMOVED by conjunction(p40 AND rank({chosen['k']})), KEPT by p40 "
                 f"(20 samples; the reverse direction is empty by construction) =="]
        lines += [f"[{k}] {c}" for k, c in rmv[:20]]
        F2_READ_SAMPLES.write_text("\n".join(lines), encoding="utf-8")
        print(f"  wrote {F2_READ_SAMPLES.name} ({len(rmv)} disagreements)")

    F2_OUT.write_text(json.dumps({
        "provenance": provenance(sub, a.seed, {"stage": "f2"}),
        "gate": {"verdict": verdict, "best_gap": best_gap,
                 "pass_pp": GT1A_PASS_PP, "null_pp": GT1A_NULL_PP,
                 "min_real_survival": GT1A_MIN_REAL_SURVIVAL},
        "chosen": chosen, "rows": rows,
    }, indent=1, default=float), encoding="utf-8")
    print(f"  wrote {F2_OUT.name}. ZERO chat calls.")


# ---------------------------------------------------------------------------------------
# F1 — support-targeted rescue
# ---------------------------------------------------------------------------------------

def run_f1(a) -> None:
    from calibration.layer_b_arms import sign_test

    sub = load_substrate(a.taxonomy, a.recordings, a.width)
    rng = random.Random(a.seed + 31)
    filt = p40_filter(sub.tuning.layer_c)

    per_scenario_detail: dict[str, dict] = {}
    all_failing, rule_all, plac_all = [], set(), set()
    scenario_of: dict[tuple, str] = {}
    todo = sorted(sub.coachable.items())
    print(f"\n[F1] real/p40 pass 1 with capture over {len(todo)} scenario(s)...", flush=True)
    for n, (key, info) in enumerate(todo, 1):
        res = pass1_lcfr(dict(info, scenario_key=key), sub.by_key.get(key, []),
                         sub.tuning.layer_c, filt, capture=True)
        cap = res.get("_capture")
        cands = (cap or {}).get("candidates") or []
        req = res.get("required_support")
        print(f"  [{n}/{len(todo)}] {key[:44]:<44} "
              f"{len(cands):>3} clusters ({res['outcome']})", flush=True)
        if not cap or not cands or req is None:
            continue
        labels = np.asarray(cap["labels"])
        noise_rows = [int(i) for i in np.flatnonzero(labels == -1)]
        members = failing_members(cands, req, cap["vecs"])
        if not members or not noise_rows:
            continue
        noise_vecs = cap["vecs"][noise_rows]
        admitted, thr = rescue_assign(noise_vecs, members)
        counts = {l: len(v) for l, v in admitted.items()}
        plac = placebo_assign(counts, len(noise_rows), rng)

        r_flips = flips(cands, req, cap["calls"], admitted, noise_rows)
        p_flips = flips(cands, req, cap["calls"], plac, noise_rows)
        failing_ids = [c["cluster_id"] for c in cands if c["support_calls"] < req]
        for cid in failing_ids:
            all_failing.append((key, cid))
            scenario_of[(key, cid)] = key
        rule_all |= {(key, c) for c in r_flips}
        plac_all |= {(key, c) for c in p_flips}

        by_id = {c["cluster_id"]: c for c in cands}
        det = {}
        for cid in failing_ids:
            c = by_id[cid]
            r_rows = [noise_rows[i] for i in admitted.get(cid, [])]
            p_rows = [noise_rows[i] for i in plac.get(cid, [])]
            det[str(cid)] = {
                "deficit": req - c["support_calls"],
                "support_calls": c["support_calls"], "required": req,
                "adds": len(r_rows),
                "new_calls_rule": len(set(cap["calls"][i] for i in r_rows)
                                      - set(c["support_call_files"])),
                "new_calls_placebo": len(set(cap["calls"][i] for i in p_rows)
                                         - set(c["support_call_files"])),
                "flipped_rule": cid in r_flips, "flipped_placebo": cid in p_flips,
                "member_sample": c["clauses"][:5],
                "added_rule": [cap["clauses"][i] for i in r_rows],
                "added_placebo": [cap["clauses"][i] for i in p_rows],
                "threshold": thr.get(cid)}
        per_scenario_detail[key] = det

    up, down, tie = paired_flip_counts(
        all_failing, rule_all, plac_all)
    p = sign_test(up, down)
    n_rule, n_plac = len(rule_all), len(plac_all)
    underpowered = n_rule < UNDERPOWERED_FLOOR and n_plac < UNDERPOWERED_FLOOR
    verdict = ("UNDERPOWERED-NULL" if underpowered else
               "PASS" if (n_rule > n_plac and p < 0.05) else "FAIL")

    print(f"\n[G-F1] failing clusters: {len(all_failing)} | flips: rule {n_rule}, "
          f"placebo {n_plac} | paired {up} up / {down} down / {tie} tie | "
          f"sign p={p:.4f} -> {verdict}", flush=True)

    F1_OUT.write_text(json.dumps({
        "provenance": provenance(sub, a.seed, {"stage": "f1"}),
        "gate": {"verdict": verdict, "underpowered_floor": UNDERPOWERED_FLOOR,
                 "flips_rule": n_rule, "flips_placebo": n_plac,
                 "paired": {"up": up, "down": down, "tie": tie, "p": p}},
        "n_failing": len(all_failing),
        "per_scenario": per_scenario_detail,
    }, indent=1, default=float), encoding="utf-8")
    print(f"wrote {F1_OUT.name}. ZERO chat calls. NOTHING written to Postgres.")


def f1_build_read(seed: int) -> None:
    art = json.loads(F1_OUT.read_text(encoding="utf-8-sig"))
    eligible = []
    for sk, det in art["per_scenario"].items():
        for cid, rec in det.items():
            if len(rec["added_rule"]) >= 2 and len(rec["added_placebo"]) >= 2:
                eligible.append((rec["flipped_rule"] or rec["flipped_placebo"],
                                 sk, cid, rec))
    rng = random.Random(seed + 37)
    rng.shuffle(eligible)
    eligible.sort(key=lambda t: -int(t[0]))  # flipped clusters first, stable post-shuffle
    items = eligible[:12]
    if len(items) < 12:
        print(f"NOTE: only {len(items)} readable item(s); the win bar scales as ceil(5n/6) "
              f"and must be reported with n.")
    lines = ["Each item: a cluster's original member clauses, then two candidate sets of",
             "ADDED clauses (A and B). Question: which set's additions belong to this",
             "cluster's move? Answer A, B, or tie.", ""]
    key = {}
    for n, (_, sk, cid, rec) in enumerate(items, 1):
        rule_first = rng.random() < 0.5
        a_set = rec["added_rule"] if rule_first else rec["added_placebo"]
        b_set = rec["added_placebo"] if rule_first else rec["added_rule"]
        key[str(n)] = {"scenario": sk, "cluster": cid,
                       "A": "rule" if rule_first else "placebo",
                       "B": "placebo" if rule_first else "rule"}
        lines += [f"### ITEM {n}", "ORIGINAL MEMBERS (sample):"]
        lines += [f"  - {t}" for t in rec["member_sample"]]
        lines.append("SET A additions:")
        lines += [f"  - {t}" for t in a_set[:6]]
        lines.append("SET B additions:")
        lines += [f"  - {t}" for t in b_set[:6]]
        lines.append("")
    F1_READ_SAMPLES.write_text("\n".join(lines), encoding="utf-8")
    F1_READ_KEY.write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"wrote {F1_READ_SAMPLES.name} ({len(items)} items) and {F1_READ_KEY.name}")


def f1_score_read(judgments_path: str) -> None:
    key = json.loads(F1_READ_KEY.read_text(encoding="utf-8-sig"))
    j = json.loads(Path(judgments_path).read_text(encoding="utf-8-sig"))
    wins = losses = ties = 0
    for item, rec in key.items():
        v = str(j.get(item, "")).strip().upper()
        if v not in ("A", "B", "TIE"):
            raise SystemExit(f"item {item}: judgment {v!r} is not A/B/tie")
        if v == "TIE":
            ties += 1
        elif rec[v] == "rule":
            wins += 1
        else:
            losses += 1
    n = len(key)
    bar = -(-5 * n // 6)  # ceil(5n/6): 10-of-12 scaled to smaller item counts
    print(f"F1 blinded read: rule {wins}, placebo {losses}, ties {ties} of {n} "
          f"-> {'PASS' if wins >= bar else 'FAIL'} (bar {bar}/{n})")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--f1", action="store_true")
    p.add_argument("--f2", action="store_true")
    p.add_argument("--f1-build-read", action="store_true")
    p.add_argument("--f1-score-read", metavar="JUDGMENTS_JSON")
    p.add_argument("--taxonomy", default="clean2_base")
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--width", type=int, default=3072)
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    if a.f2:
        run_f2(a)
    elif a.f1:
        run_f1(a)
    elif a.f1_build_read:
        f1_build_read(a.seed)
    elif a.f1_score_read:
        f1_score_read(a.f1_score_read)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
