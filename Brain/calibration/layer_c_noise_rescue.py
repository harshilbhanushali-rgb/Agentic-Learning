#!/usr/bin/env python3
"""T2: does rescue_centroid port to Layer C milestone clusters?

Spec: docs/superpowers/specs/2026-08-17-layer-c-relative-filter-and-rescue-design.md §4
(gate G-T2 frozen before this file existed).

The rule, ported unchanged from the Layer-A-validated arm: admit an HDBSCAN noise clause
into its NEAREST surviving cluster iff cos(clause, centroid) >= p25 of that cluster's own
member cosines, in the FULL embedding space. Placebo: the same COUNT per cluster, drawn
uniformly from the same scenario's noise pool (counts asserted equal in lcfr_common).

`run_rescue` is invoked by layer_c_relative_filter --stage downstream so it can reuse the
real/p40 arm's captured clustering (labels fixed -- the rescue is post-processing, no new
UMAP, which is also what makes rescue-vs-base differences pure signal given the documented
Pass-1 determinism). This module's own CLI only builds and scores the blinded read:

    python calibration/layer_c_noise_rescue.py --build-read
    python calibration/layer_c_noise_rescue.py --score-read path/to/judgments.json

The read: 12 clusters where BOTH arms added >=2 clauses; each item shows 5 original member
clauses plus slots A/B = {rule additions, placebo additions}, order coin-flipped per item;
the key is written to a SEPARATE file at build time and never printed. G-T2 PASS iff the
rule wins >= 10 of 12 (sign test p = 0.019), judged by an independent reader.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR
from calibration.lcfr_common import (rescue_assign, placebo_assign, provenance,
                                     write_arm_artifact)

DETAIL_OUT = ARTIFACTS_DIR / "lcfr_rescue_detail.json"
READ_SAMPLES = ARTIFACTS_DIR / "lcfr_rescue_read_samples.txt"
READ_KEY = ARTIFACTS_DIR / "lcfr_rescue_read_KEY.json"
READ_ITEMS = 12
GATE_WINS = 10


def run_rescue(sub, real_p40: dict, seed: int, ident_base: dict) -> None:
    """Build the rescue and placebo arms from the captured real/p40 state and write their
    artifacts (scoreable by score_layer_b_arms.py) plus the read/detail file."""
    from calibration.layer_b_arms import load_account_map, account_shares

    rng = random.Random(seed + 7)
    accounts, _, _ = load_account_map(sub.recordings)

    per_arm: dict[str, dict] = {"rescue": {}, "rescue_placebo": {}}
    detail: dict[str, dict] = {}
    tot = {"noise": 0, "admitted": 0, "clusters": 0, "gained_rescue": 0,
           "gained_placebo": 0}
    glue = {"rule": [], "placebo": [], "orig": []}

    for k, res in sorted(real_p40.items()):
        cap = res.get("_capture")
        cands = (cap or {}).get("candidates") or []
        if not cap or not cands or res.get("required_support") is None:
            # nothing was clustered -- the rescue has no destinations here; both arms
            # inherit the base outcome unchanged (symmetric by construction)
            for arm in per_arm:
                per_arm[arm][k] = {kk: vv for kk, vv in res.items()
                                   if not kk.startswith("_")}
            continue

        labels = np.asarray(cap["labels"])
        vecs, clauses = cap["vecs"], cap["clauses"]
        calls, positions = cap["calls"], cap["positions"]
        relevance = cap["relevance"]
        noise_idx = np.flatnonzero(labels == -1)
        members = {c["cluster_id"]: vecs[c["_idx"]] for c in cands}

        admitted, thr = rescue_assign(vecs[noise_idx], members)
        counts = {l: len(v) for l, v in admitted.items()}
        plac = placebo_assign(counts, len(noise_idx), rng)
        assert {l: len(v) for l, v in plac.items()} == counts, \
            "placebo per-cluster counts drifted from the rule's"

        tot["noise"] += len(noise_idx)
        tot["admitted"] += sum(counts.values())
        tot["clusters"] += len(cands)

        base_pass = {c["cluster_id"] for c in cands
                     if c["support_calls"] >= res["required_support"]}
        det_clusters = {}
        for arm, adds in (("rescue", admitted), ("rescue_placebo", plac)):
            ms = []
            for c in cands:
                l = c["cluster_id"]
                add_rows = [int(noise_idx[i]) for i in adds.get(l, [])]
                mem_rows = c["_idx"]
                all_calls = [calls[i] for i in mem_rows] + [calls[i] for i in add_rows]
                sup_files = sorted(set(all_calls))
                sup = len(sup_files)
                if sup < res["required_support"]:
                    continue
                pos = [positions[i] for i in mem_rows] + [positions[i] for i in add_rows]
                rel = [relevance[clauses[i]] for i in mem_rows + add_rows]
                ms.append({"cluster_id": l, "support_calls": sup,
                           "support_clauses": len(mem_rows) + len(add_rows),
                           "support_call_files": sup_files,
                           "support_frac": sup / max(res["scenario_calls"], 1),
                           "median_position": float(np.median(pos)),
                           "relevance_mean": float(np.mean(rel)),
                           "n_added": len(add_rows),
                           "gained": l not in base_pass})
                if l not in base_pass:
                    tot["gained_rescue" if arm == "rescue" else "gained_placebo"] += 1
            rec = {"n_responses": res["n_responses"],
                   "scenario_calls": res["scenario_calls"],
                   "n_clauses": res["n_clauses"],
                   "n_clauses_after_relevance": res["n_clauses_after_relevance"],
                   "required_support": res["required_support"],
                   "outcome": "clustered" if ms else res["outcome"],
                   "milestones": sorted(ms, key=lambda m: m["median_position"])}
            per_arm[arm][k] = rec

        # detail for the blinded read + the account-glue check, per cluster with adds
        mem_rng = random.Random(seed + 11)
        for c in cands:
            l = c["cluster_id"]
            rule_rows = [int(noise_idx[i]) for i in admitted.get(l, [])]
            plac_rows = [int(noise_idx[i]) for i in plac.get(l, [])]
            if not rule_rows and not plac_rows:
                continue
            mem_texts = list(c["clauses"])
            mem_rng.shuffle(mem_texts)
            det_clusters[str(l)] = {
                "member_sample": mem_texts[:5],
                "added_rule": [clauses[i] for i in rule_rows],
                "added_placebo": [clauses[i] for i in plac_rows],
                "threshold": thr.get(l)}
            if rule_rows:
                doms, _ = account_shares([calls[i] for i in rule_rows], accounts)
                if doms:
                    glue["rule"].append(doms.most_common(1)[0][1] / sum(doms.values()))
            if plac_rows:
                doms, _ = account_shares([calls[i] for i in plac_rows], accounts)
                if doms:
                    glue["placebo"].append(doms.most_common(1)[0][1] / sum(doms.values()))
            doms, _ = account_shares([calls[i] for i in c["_idx"]], accounts)
            if doms:
                glue["orig"].append(doms.most_common(1)[0][1] / sum(doms.values()))
        if det_clusters:
            detail[k] = det_clusters

    for arm in per_arm:
        write_arm_artifact(arm, sub, per_arm[arm],
                           dict(ident_base, filter="p40", routing="real",
                                treatment=arm, base_arm="lcfr_real_p40"))

    def med(v):
        return float(np.median(v)) if v else None
    summary = {**tot,
               "admit_rate": tot["admitted"] / max(tot["noise"], 1),
               "top_account_share_added_rule_med": med(glue["rule"]),
               "top_account_share_added_placebo_med": med(glue["placebo"]),
               "top_account_share_originals_med": med(glue["orig"])}
    DETAIL_OUT.write_text(json.dumps({
        "provenance": provenance(sub, seed, {"stage": "rescue"}),
        "summary": summary, "clusters": detail,
    }, indent=1, default=float), encoding="utf-8")
    print(f"[T2] rescue admitted {tot['admitted']}/{tot['noise']} noise clauses "
          f"({100*summary['admit_rate']:.1f}%) into {tot['clusters']} clusters; "
          f"gained milestones rescue={tot['gained_rescue']} "
          f"placebo={tot['gained_placebo']}", flush=True)
    print(f"[T2] top-account share of ADDED clauses (median): "
          f"rule {summary['top_account_share_added_rule_med']} vs placebo "
          f"{summary['top_account_share_added_placebo_med']} vs originals "
          f"{summary['top_account_share_originals_med']}", flush=True)
    print(f"[T2] wrote {DETAIL_OUT.name}", flush=True)


# ---------------------------------------------------------------------------------------
# the blinded read
# ---------------------------------------------------------------------------------------

def build_read(seed: int) -> None:
    detail = json.loads(DETAIL_OUT.read_text(encoding="utf-8-sig"))["clusters"]
    eligible = [(sk, cl, rec) for sk, clusters in detail.items()
                for cl, rec in clusters.items()
                if len(rec["added_rule"]) >= 2 and len(rec["added_placebo"]) >= 2]
    rng = random.Random(seed + 13)
    rng.shuffle(eligible)
    items = eligible[:READ_ITEMS]
    if len(items) < READ_ITEMS:
        print(f"WARNING: only {len(items)} eligible clusters (spec asks for {READ_ITEMS}) "
              f"-- the gate win-count applies to what exists; say so in the report.")
    lines = ["Each item: a cluster's original member clauses, then two candidate sets of",
             "ADDED clauses (A and B). Question per item: which set's additions belong to",
             "this cluster's move? Answer A, B, or tie.", ""]
    key = {}
    for n, (sk, cl, rec) in enumerate(items, 1):
        rule_first = rng.random() < 0.5
        a_set = rec["added_rule"] if rule_first else rec["added_placebo"]
        b_set = rec["added_placebo"] if rule_first else rec["added_rule"]
        key[str(n)] = {"scenario": sk, "cluster": cl,
                       "A": "rule" if rule_first else "placebo",
                       "B": "placebo" if rule_first else "rule"}
        lines.append(f"### ITEM {n}")
        lines.append("ORIGINAL MEMBERS (sample):")
        lines += [f"  - {t}" for t in rec["member_sample"]]
        lines.append("SET A additions:")
        lines += [f"  - {t}" for t in a_set[:6]]
        lines.append("SET B additions:")
        lines += [f"  - {t}" for t in b_set[:6]]
        lines.append("")
    READ_SAMPLES.write_text("\n".join(lines), encoding="utf-8")
    READ_KEY.write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"wrote {READ_SAMPLES.name} ({len(items)} items) and {READ_KEY.name}. "
          f"Judge from the samples file ONLY; open the key only through --score-read.")


def score_read(judgments_path: str) -> None:
    key = json.loads(READ_KEY.read_text(encoding="utf-8-sig"))
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
    verdict = "PASS" if wins >= GATE_WINS else "FAIL"
    print(f"G-T2 blinded read: rule wins {wins}, placebo wins {losses}, ties {ties} "
          f"of {n} -> {verdict} (gate: wins >= {GATE_WINS})")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--build-read", action="store_true")
    p.add_argument("--score-read", metavar="JUDGMENTS_JSON")
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    if a.build_read:
        build_read(a.seed)
    elif a.score_read:
        score_read(a.score_read)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
