#!/usr/bin/env python3
"""Can Layer C be changed to make Layer D's two repertoire methods more powerful? ZERO spend.

Operator question (2026-09-07): for BOTH aggregations -- "ever/never" (findings §11) and
"how often, per scenario" (§13) -- is there a Layer C lever, yes or no, and how big?

Measurements, all from stored data (say-arm move_performance, playbooks, kb_pairs):
  1. Does criterion BUNDLING predict a low Naren call-level rate? If bundled criteria
     (several things joined by and/or/commas) are credited less often per reply, then
     "one statable thing per move" would raise p_hat, which lowers n_needed (ever) and
     widens detectable gaps (rarely). Spearman rank correlation of rate vs. features.
  2. Move-count dilution: do playbooks with more moves have lower per-move rates?
  3. Naren's AVAILABLE calls per scenario in kb_pairs vs. the calls the benchmark used
     (11-26). A larger benchmark is a Layer D spend lever, not a Layer C one -- but it
     bounds what "rarely" can ever detect, so it is measured here for the write-up.
  4. Her calls per scenario vs n_needed: how many cells are decidable at n, and how
     many would be at 1.5x / 2x her current call volume (the ingest lever).
  5. What the eligible "rarely" set becomes if Naren's benchmark were maxed per scenario
     (min detectable rate ratio at alpha .05 for her n and his n_max).

Writes artifacts/layer_c_levers_for_layer_d.json and prints the tables.
Usage (from Brain/, VPN up):  python calibration/layer_c_levers_for_layer_d.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibration import ARTIFACTS_DIR  # noqa: E402

CONJ = re.compile(r"\b(and|or)\b|,|;| such as | including ", re.I)


def features(criterion: str) -> dict:
    words = re.findall(r"[A-Za-z']+", criterion)
    return {
        "words": len(words),
        "conjunctions": len(CONJ.findall(criterion)),
        "clauses": 1 + len(re.findall(r"\b(and|or)\b", criterion, re.I)),
    }


def spearman(x, y) -> tuple[float, float]:
    from scipy.stats import spearmanr
    r = spearmanr(x, y)
    return float(r.statistic), float(r.pvalue)


def main() -> None:
    import psycopg
    from config import load_config
    from layer_d import move_classes, repertoire
    from layer_d.pipeline import live_playbooks_flat
    from shared import storage

    url = load_config().database_url
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + "hostaddr=18.138.49.39"
    conn = psycopg.connect(url, autocommit=True)

    classes = move_classes.load_move_classes()
    pbs = live_playbooks_flat(conn)
    naren = {(r["playbook_id"], r["move_id"]): r
             for r in storage.get_move_rates(conn, "naren", "say").get("naren", [])}
    csm_rows = storage.get_move_rates(conn, "csm", "say")
    csm = {(r["playbook_id"], r["move_id"]): r for rows in csm_rows.values() for r in rows}

    # ---- 1 & 2: bundling and dilution vs Naren's call-level rate -------------
    rows = []
    for pb in pbs:
        say_moves = [m for m in pb["key_moves"]
                     if classes.get(f"{pb['scenario_key']}:{m['move_id']}", {}).get("route") == "say"]
        for m in say_moves:
            r = naren.get((pb["playbook_id"], m["move_id"]))
            if not r or not r["attempts"]:
                continue
            f = features(m.get("criterion") or "")
            ev = m.get("evidence") or []
            rows.append({
                "scenario": pb["scenario_key"], "move": m["move_id"], "name": m.get("name", ""),
                "rate": (r["hits"] + r["partials"]) / r["attempts"], "said": r["hits"] + r["partials"],
                "calls": r["attempts"], "in_repertoire": (r["hits"] + r["partials"]) >= 2,
                "words": f["words"], "conjunctions": f["conjunctions"], "clauses": f["clauses"],
                "evidence_quotes": len(ev), "evidence_calls": len({e.get("call") for e in ev if e.get("call")}),
                "moves_in_playbook": len(pb["key_moves"]), "say_moves_in_playbook": len(say_moves),
            })
    rates = [x["rate"] for x in rows]
    print(f"=== 1. Does criterion shape predict Naren's call-level rate? ({len(rows)} SAY moves) ===")
    corr = {}
    for k in ("words", "conjunctions", "clauses", "evidence_quotes", "evidence_calls",
              "moves_in_playbook", "say_moves_in_playbook"):
        rho, p = spearman([x[k] for x in rows], rates)
        corr[k] = {"spearman_rho": rho, "p": p}
        print(f"  rate vs {k:<22} rho={rho:+.2f}  p={p:.3f}")
    # tertiles of conjunction count
    conj = np.array([x["conjunctions"] for x in rows]); rt = np.array(rates)
    q1, q2 = np.percentile(conj, [33, 67])
    bands = {"few (<= %d)" % q1: rt[conj <= q1], "mid": rt[(conj > q1) & (conj <= q2)], "many (> %d)" % q2: rt[conj > q2]}
    print("  median Naren rate by conjunction band:",
          {k: (round(float(np.median(v)), 3), len(v)) for k, v in bands.items()})

    # ---- 3: Naren's available calls per scenario --------------------------------
    print("\n=== 3. Naren's available calls per scenario vs the benchmark's ===")
    # Same routed population the benchmark samples from (primary OR secondary label).
    avail = {pb["scenario_key"]: len({p["call_filename"] for p in
                                       storage.get_pairs_for_scenario_multilabel(conn, pb["scenario_key"])})
             for pb in pbs}
    bench_calls = {}
    for pb in pbs:
        cells = [naren[(pb["playbook_id"], m["move_id"])] for m in pb["key_moves"]
                 if (pb["playbook_id"], m["move_id"]) in naren]
        if cells:
            bench_calls[pb["scenario_key"]] = max(c["attempts"] for c in cells)
    avail_rows = []
    for sk, used in sorted(bench_calls.items(), key=lambda kv: -avail.get(kv[0], 0)):
        a = avail.get(sk, 0)
        avail_rows.append({"scenario": sk, "benchmark_calls": used, "available_calls": a})
    print(f"  {'scenario':<48} {'bench':>5} {'avail':>5}")
    for r in avail_rows:
        print(f"  {r['scenario'][:48]:<48} {r['benchmark_calls']:>5} {r['available_calls']:>5}")
    print(f"  median available {int(np.median([r['available_calls'] for r in avail_rows]))}, "
          f"median used {int(np.median([r['benchmark_calls'] for r in avail_rows]))}")

    # ---- 4: her calls vs n_needed, and at 1.5x / 2x ---------------------------
    print("\n=== 4. Ever/never decidability vs her call volume ===")
    rep = repertoire.naren_repertoire([
        __import__("layer_d.aggregate", fromlist=["MoveRate"]).MoveRate(
            r["playbook_id"], r["move_id"], r["attempts"], r["hits"], r["partials"]) for r in naren.values()])
    decid = defaultdict(int)
    for cell, mv in rep.items():
        c = csm.get(cell)
        n = c["attempts"] if c else 0
        need = mv.calls_needed()
        for mult in (1.0, 1.5, 2.0, 3.0):
            if n * mult >= need:
                decid[mult] += 1
    print(f"  in-repertoire cells: {len(rep)}; decidable (enough of her calls for a never to count) at "
          f"1x: {decid[1.0]}, 1.5x: {decid[1.5]}, 2x: {decid[2.0]}, 3x: {decid[3.0]} of her current calls")
    # if p_hat rose (moves split so he states each part more often): n_needed at p*1.5, p*2
    for mult in (1.5, 2.0):
        dec = sum(1 for cell, mv in rep.items()
                  if (csm.get(cell, {}).get("attempts", 0)) >= repertoire.n_needed(min(0.99, mv.p_hat * mult)))
        print(f"  if Naren's rates were {mult}x higher (moves split into statable parts): decidable today = {dec}")

    # ---- 5: rarely detectability bound from Naren's n ----------------------------
    print("\n=== 5. What 'rarely' can detect, by Naren's benchmark size ===")
    from scipy.stats import fisher_exact
    def min_detectable_ratio(her_n, his_n, his_rate):
        his_said = round(his_rate * his_n)
        for her_said in range(0, her_n + 1):
            p = fisher_exact([[her_said, her_n - her_said], [his_said, his_n - his_said]], alternative="less").pvalue
            if p >= 0.05:
                return (her_said - 1) / her_n / his_rate if her_said > 0 else 0.0
        return 1.0
    for his_n in (11, 20, 30, 50):
        print(f"  his n={his_n:>2}, his rate .36, her n=53: largest her/his rate ratio still flagged = "
              f"{min_detectable_ratio(53, his_n, 0.36):.2f}")

    out = {"criterion_features_vs_rate": corr, "rows": rows, "naren_available_calls": avail_rows,
           "decidable_by_call_multiple": {str(k): v for k, v in decid.items()}}
    (ARTIFACTS_DIR / "layer_c_levers_for_layer_d.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    conn.close()


if __name__ == "__main__":
    main()
