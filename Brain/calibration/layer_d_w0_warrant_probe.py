#!/usr/bin/env python3
"""W0: is the warrant for a SAY move legible in the client trigger text? ZERO spend.

Pre-registration: docs/findings/layer-d-say-arm.md §10, frozen 2026-09-05 BEFORE this
script ran. Read that section first; nothing here is a knob.

The construction, in one paragraph: Naren deploys a given playbook move on ~1 routed
call in 7 (G-S4). For every in-repertoire SAY move, take the client trigger texts of
the moments where he DID deploy it as that move's "deployment triggers". Score every
scored moment of the same scenario by its max cosine to those triggers, leaving out
deployments from the SAME CALL as the moment being scored (a W1 detector would score
a CSM moment against Naren's OTHER calls; same-call similarity is shared client, not
warrant). Pool the (moment, move) pairs, bucket by similarity decile, and ask whether
the top decile is enriched for deployment. A permutation null (labels shuffled within
move, references recomputed) gives the p-value.

Decision rule (frozen): LEGIBLE iff top-decile deployment rate >= 3x base AND
>= 0.50 absolute AND permutation p < 0.05 on the leave-one-call-out curve.

Embeddings: gemini-embedding-2 @ 3072 from the gateway cache ONLY, via
calibration.layer_bc_arms._load_cached. Any miss aborts; width is asserted. This
script never calls the embedder and never writes to Postgres.

Usage (from Brain/, VPN up):
    python calibration/layer_d_w0_warrant_probe.py
    python calibration/layer_d_w0_warrant_probe.py --permutations 500 --seed 7
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibration import ARTIFACTS_DIR  # noqa: E402

WIDTH = 3072
NAREN_SAY_RUN = "695837c37614"
MIN_DEPLOY_CALLS = 2          # in-repertoire rule (findings §9): said on >= 2 distinct calls
DEPLOYED = ("hit", "partial")
OUT = ARTIFACTS_DIR / "layer_d_w0_warrant_probe.json"

# The frozen rule.
ENRICHMENT_X = 3.0
ABSOLUTE_FLOOR = 0.50
ALPHA = 0.05


def load_events(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT move_event_id, call_id, playbook_id, scenario_key, trigger_text, verdicts
            FROM move_events
            WHERE rater_population = 'naren' AND grader_arm = 'say'
              AND run_id = %s AND verdicts != '[]'::jsonb
            ORDER BY move_event_id
        """, (NAREN_SAY_RUN,))
        rows = cur.fetchall()
    return [{"id": r[0], "call_id": r[1], "playbook_id": r[2], "scenario_key": r[3],
             "trigger_text": r[4], "verdicts": r[5]} for r in rows]


def build_cells(events: list[dict]) -> dict[tuple[int, str], list[dict]]:
    """(playbook_id, move_id) -> [{event_idx, call_id, deployed: bool}] over SCORED
    verdicts only (unscored dropped)."""
    cells: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for i, e in enumerate(events):
        for v in e["verdicts"]:
            verdict = v.get("verdict")
            if verdict not in ("hit", "partial", "miss"):
                continue
            cells[(e["playbook_id"], v["move_id"])].append(
                {"idx": i, "call_id": e["call_id"], "deployed": verdict in DEPLOYED})
    return cells


def in_repertoire(moments: list[dict]) -> bool:
    return len({m["call_id"] for m in moments if m["deployed"]}) >= MIN_DEPLOY_CALLS


def score_cell(moments: list[dict], labels: np.ndarray, sims: np.ndarray,
               leave_call_out: bool) -> list[tuple[float, bool]]:
    """One move's (max-sim, deployed) pairs. `labels` is the deployed vector actually
    used as the reference set (real or permuted); `sims` is the moment x moment cosine
    matrix for THIS cell's moments. Leave-one-out is always at least the moment
    itself; leave_call_out also drops every reference from the same call."""
    n = len(moments)
    calls = np.array([m["call_id"] for m in moments])
    out: list[tuple[float, bool]] = []
    for i in range(n):
        mask = labels.copy()
        mask[i] = False
        if leave_call_out:
            mask &= calls != calls[i]
        if not mask.any():
            continue
        out.append((float(sims[i, mask].max()), bool(labels[i])))
    return out


def decile_curve(pairs: list[tuple[float, bool]]) -> dict:
    """Deciles by similarity RANK (equal-count bands), highest similarity = decile 10."""
    if not pairs:
        return {"n": 0, "base_rate": float("nan"), "deciles": [], "top_decile_rate": float("nan"),
                "top20_rate": float("nan")}
    arr = np.array(pairs, dtype=[("sim", "f8"), ("dep", "?")])
    order = np.argsort(-arr["sim"], kind="stable")
    arr = arr[order]
    n = len(arr)
    base = float(arr["dep"].mean())
    bounds = np.linspace(0, n, 11).round().astype(int)
    deciles = []
    for d in range(10):
        chunk = arr[bounds[d]:bounds[d + 1]]
        deciles.append({
            "decile": 10 - d,                       # 10 = most similar
            "n": int(len(chunk)),
            "sim_min": float(chunk["sim"].min()) if len(chunk) else float("nan"),
            "sim_max": float(chunk["sim"].max()) if len(chunk) else float("nan"),
            "deployment_rate": float(chunk["dep"].mean()) if len(chunk) else float("nan"),
        })
    top = arr[:bounds[1]]
    top20 = arr[:bounds[2]]
    return {"n": n, "base_rate": base, "deciles": deciles,
            "top_decile_rate": float(top["dep"].mean()) if len(top) else float("nan"),
            "top20_rate": float(top20["dep"].mean()) if len(top20) else float("nan")}


def auc(pairs: list[tuple[float, bool]]) -> float:
    """Rank AUC of similarity as a predictor of deployment (ties split)."""
    sims = np.array([p[0] for p in pairs]); dep = np.array([p[1] for p in pairs])
    pos, neg = sims[dep], sims[~dep]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    from scipy.stats import rankdata
    r = rankdata(np.concatenate([pos, neg]))
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def run_probe(events: list[dict], vecs: np.ndarray, *, permutations: int, seed: int) -> dict:
    cells = build_cells(events)
    scope = {cell: ms for cell, ms in cells.items() if in_repertoire(ms)}
    rng = np.random.default_rng(seed)

    # Per-cell cosine matrices (moments of one cell share a playbook -> same scenario).
    per_cell = {}
    for cell, ms in scope.items():
        idx = np.array([m["idx"] for m in ms])
        v = vecs[idx]
        per_cell[cell] = (ms, np.array([m["deployed"] for m in ms], dtype=bool), v @ v.T)

    def pooled(leave_call_out: bool, label_override=None) -> list[tuple[float, bool]]:
        pairs: list[tuple[float, bool]] = []
        for cell, (ms, labels, sims) in per_cell.items():
            lab = labels if label_override is None else label_override[cell]
            pairs.extend(score_cell(ms, lab, sims, leave_call_out))
        return pairs

    primary_pairs = pooled(True)
    loo_pairs = pooled(False)
    primary = decile_curve(primary_pairs)
    loo = decile_curve(loo_pairs)

    # Permutation null on the PRIMARY construction: shuffle deployed labels within
    # each cell, references move with the labels.
    null_top, null_top20 = [], []
    for _ in range(permutations):
        perm = {cell: rng.permutation(labels) for cell, (_, labels, _) in per_cell.items()}
        curve = decile_curve(pooled(True, perm))
        null_top.append(curve["top_decile_rate"]); null_top20.append(curve["top20_rate"])
    null_top = np.array(null_top); null_top20 = np.array(null_top20)
    p_top = float((null_top >= primary["top_decile_rate"]).mean()) if permutations else float("nan")
    p_top20 = float((null_top20 >= primary["top20_rate"]).mean()) if permutations else float("nan")

    # Diagnostics: per-move top-band rate (primary construction), and how often a
    # deployed moment's nearest deployment sits in the SAME call (why LOCO matters).
    per_move = []
    same_call_nearest = 0; deployed_with_other = 0
    for cell, (ms, labels, sims) in per_cell.items():
        pairs = score_cell(ms, labels, sims, True)
        c = decile_curve(pairs) if len(pairs) >= 10 else None
        per_move.append({"playbook_id": cell[0], "move_id": cell[1],
                         "moments": len(ms), "deployed": int(labels.sum()),
                         "deployed_calls": len({m["call_id"] for m in ms if m["deployed"]}),
                         "pairs_scored": len(pairs),
                         "auc": auc(pairs) if pairs else float("nan"),
                         "top_decile_rate": c["top_decile_rate"] if c else None})
        calls = np.array([m["call_id"] for m in ms])
        for i in np.flatnonzero(labels):
            others = labels.copy(); others[i] = False
            if not others.any():
                continue
            j = int(np.argmax(np.where(others, sims[i], -np.inf)))
            deployed_with_other += 1
            same_call_nearest += int(calls[j] == calls[i])

    legible = (primary["top_decile_rate"] >= ENRICHMENT_X * primary["base_rate"]
               and primary["top_decile_rate"] >= ABSOLUTE_FLOOR
               and p_top < ALPHA)
    return {
        "pre_registration": "docs/findings/layer-d-say-arm.md §10 (2026-09-05)",
        "run_id": NAREN_SAY_RUN, "width": WIDTH,
        "events_with_verdicts": len(events),
        "cells_total": len(cells), "cells_in_repertoire": len(scope),
        "moments_dropped_no_reference": {
            "primary": sum(len(ms) for ms in scope.values()) - primary["n"],
            "loo": sum(len(ms) for ms in scope.values()) - loo["n"]},
        "primary_leave_one_call_out": primary,
        "diagnostic_leave_one_moment_out": loo,
        "auc_primary": auc(primary_pairs), "auc_loo": auc(loo_pairs),
        "permutations": permutations, "seed": seed,
        "null_top_decile_mean": float(null_top.mean()) if permutations else None,
        "null_top_decile_p95": float(np.percentile(null_top, 95)) if permutations else None,
        "p_top_decile": p_top, "p_top20": p_top20,
        "same_call_nearest_share": (same_call_nearest / deployed_with_other
                                    if deployed_with_other else float("nan")),
        "rule": {"enrichment_x": ENRICHMENT_X, "absolute_floor": ABSOLUTE_FLOOR, "alpha": ALPHA},
        "verdict": "LEGIBLE" if legible else "NOT LEGIBLE",
        "per_move": sorted(per_move, key=lambda r: (r["playbook_id"], r["move_id"])),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--permutations", type=int, default=500)
    ap.add_argument("--seed", type=int, default=20260905)
    ap.add_argument("--hostaddr", default="18.138.49.39")
    a = ap.parse_args()

    import psycopg
    from config import load_config
    from calibration.layer_bc_arms import _load_cached

    url = load_config().database_url
    if a.hostaddr and "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + f"hostaddr={a.hostaddr}"
    conn = psycopg.connect(url, autocommit=True)
    try:
        events = load_events(conn)
    finally:
        conn.close()
    if not events:
        raise SystemExit(f"no naren/say events for run {NAREN_SAY_RUN}")

    texts = sorted({e["trigger_text"] for e in events})
    mat, missing = _load_cached(texts, WIDTH)
    if mat is None:
        raise SystemExit(f"ABORT: {len(missing)} trigger text(s) not in the gemini cache; "
                         f"this probe is cache-only by pre-registration. e.g. {missing[:2]!r}")
    assert mat.shape == (len(texts), WIDTH), mat.shape
    row_of = {t: i for i, t in enumerate(texts)}
    vecs = mat[[row_of[e["trigger_text"]] for e in events]]

    res = run_probe(events, vecs, permutations=a.permutations, seed=a.seed)
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")

    pr = res["primary_leave_one_call_out"]
    print(f"=== W0 warrant-legibility probe (run {NAREN_SAY_RUN}, {res['events_with_verdicts']} "
          f"events, {res['cells_in_repertoire']}/{res['cells_total']} in-repertoire cells) ===")
    print(f"pairs scored (leave-one-call-out): {pr['n']}   base deployment rate: {pr['base_rate']:.3f}")
    print(f"{'decile':>6} {'n':>5} {'sim range':>17} {'deploy rate':>12}")
    for d in pr["deciles"]:
        print(f"{d['decile']:>6} {d['n']:>5} {d['sim_min']:>8.3f}-{d['sim_max']:<8.3f} {d['deployment_rate']:>12.3f}")
    print(f"\ntop decile: {pr['top_decile_rate']:.3f}  ({pr['top_decile_rate'] / pr['base_rate']:.2f}x base; "
          f"rule needs >= {ENRICHMENT_X:.0f}x AND >= {ABSOLUTE_FLOOR:.2f})")
    print(f"top 20%:    {pr['top20_rate']:.3f}")
    print(f"permutation null ({res['permutations']}): top-decile mean {res['null_top_decile_mean']:.3f}, "
          f"p95 {res['null_top_decile_p95']:.3f}; p(top decile) = {res['p_top_decile']:.3f}, "
          f"p(top 20%) = {res['p_top20']:.3f}")
    print(f"AUC(sim -> deployed): primary {res['auc_primary']:.3f}, leave-one-moment-out {res['auc_loo']:.3f}")
    lo = res["diagnostic_leave_one_moment_out"]
    print(f"diagnostic leave-one-moment-out: top decile {lo['top_decile_rate']:.3f} vs base {lo['base_rate']:.3f}")
    print(f"share of deployed moments whose nearest other deployment is in the SAME call: "
          f"{res['same_call_nearest_share']:.2f}")
    print(f"\nW0 VERDICT (frozen rule): {res['verdict']}")
    print(f"[zero chat spend; cache-only embeddings; artifact {OUT.name}]")


if __name__ == "__main__":
    main()
