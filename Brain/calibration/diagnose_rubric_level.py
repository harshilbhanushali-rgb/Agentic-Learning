#!/usr/bin/env python3
"""WHY is the milestone hit rate ~9%? Splits two causes with opposite fixes. FREE, read-only.

Spec: docs/superpowers/specs/2026-08-15-grader-inputs-design.md (the "level" it names as the
binding constraint once discrimination was confirmed).

THE QUESTION. calibration/trial_grader_inputs.py established that the scorer DISCRIMINATES
(right rubric beats a stranger's in 77-82% of scenarios, two draws). What it also established
is that W(matched) is 0.089-0.095 leakage-clean: **Naren satisfies ~9% of criteria written
from his own calls.** That level, not the ruler, is now the binding constraint.

TWO CAUSES THAT LOOK IDENTICAL IN THE HEADLINE AND NEED OPPOSITE FIXES:

  A  DENOMINATOR INFLATION. A rubric is the union of every recurring move Naren made in that
     scenario across many calls. Any single reply naturally performs one or two of them. If a
     rubric has 5 criteria and a reply does 1, the ceiling is 20% however good the reply is --
     and every unperformed criterion is recorded as a coaching failure. This is arithmetic,
     not quality. Fix: change what an ATTEMPT means (score coverage across a call, or make
     criteria conditional), NOT the criteria text.
     Fingerprint: high UNION (most criteria get hit by somebody) + low PER-REPLY.

  B  DEAD CRITERIA. Some criteria are never satisfied by anyone, because they ask for
     something unobservable, impossible for a CSM, or so specific it never recurs. Fix:
     rewrite or drop them. Precedent: ops/flag_uncoachable_milestones.py already found 17 of
     405 unhittable by construction -- 74 attempts, 0 hits, across 12 distinct milestones.
     Fingerprint: criteria with many attempts and ZERO hits, ever, by anyone.

Both can be true at once; the point is the SPLIT, because A is a scoring-design bug and B is a
content bug and doing the wrong one wastes a Layer C run.

DATA. `milestone_performance` from the 100-call Layer D run -- 4,181 attempts over 378
milestones, already paid for. Per (csm, rubric, milestone) it stores attempts / hits /
partial_hits, so "did anyone EVER hit this criterion" is answerable directly.

WHAT THIS CANNOT ANSWER. milestone_performance aggregates counters per CSM, so it cannot say
whether TWO criteria were hit by the SAME reply -- only whether each was ever hit at all. The
true per-reply distribution needs milestone_id captured at scoring time, which
trial_grader_inputs.py does not currently record. That is the paid follow-up, and it is the
one that would confirm A rather than merely make it likely.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/diagnose_rubric_level.py
    ..\\.venv\\Scripts\\python.exe calibration/diagnose_rubric_level.py --show 15
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OUT = ARTIFACTS_DIR / "rubric_level_diagnosis.json"
MIN_ATTEMPTS_TO_CALL_DEAD = 6      # score_naren_ceiling._MIN_ATTEMPTS_TO_INDICT, reused


def union_rows(rows: list[dict]) -> list[dict]:
    """Per rubric: what share of its criteria does SOMEBODY satisfy at least once?

    THE DENOMINATOR IS THE RUBRIC'S CRITERIA COUNT (`n`), not the number of criteria that
    happen to carry a milestone_performance row (`n_attempted`). Layer D never attempts
    every criterion -- 17 of 395 in the shipped artifact -- and a criterion nobody attempted
    was certainly never hit, so dropping it from the denominator inflates the union (0.479
    vs the true 0.458 in aggregate) and pushes the diagnosis toward cause A when the
    evidence is for cause B.
    """
    by_rubric: dict[int, list] = defaultdict(list)
    for r in rows:
        by_rubric[r["rubric_id"]].append(r)
    unions = []
    for rid, ms in by_rubric.items():
        alive = sum(1 for m in ms if m["ever_hit"])
        w = (sum(m["hits"] for m in ms) + 0.5 * sum(m["partial"] for m in ms)) / max(
            sum(m["attempts"] for m in ms), 1)
        # max() so a malformed row can never yield a union above 1.
        n = max(int(ms[0].get("n_criteria_in_rubric") or 0), len(ms))
        unions.append({"rubric_id": rid, "scenario_key": ms[0]["scenario_key"],
                       "n": n, "n_attempted": len(ms), "alive": alive,
                       "union": alive / n, "w": w})
    return unions


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--show", type=int, default=10, help="criteria printed per category")
    p.add_argument("--load", action="store_true",
                   help="recompute the whole report from the artifact's stored per-criterion "
                        "rows -- free, no DB. Rewrites only the DERIVED summary fields; the "
                        "paid `milestones` rows are carried through verbatim.")
    return p.parse_args()


def _fetch_rows() -> list[dict]:
    """Per-criterion rows straight from Postgres. The only non-free path."""
    from config import load_config
    import psycopg

    cfg = load_config()
    url = cfg.database_url + ("&" if "?" in cfg.database_url else "?") + "hostaddr=18.138.49.39"
    with psycopg.connect(url, autocommit=True, connect_timeout=20) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT mp.rubric_id, mp.milestone_id, sum(mp.attempts), sum(mp.hits), "
                "       sum(mp.partial_hits) "
                "FROM public.milestone_performance mp GROUP BY 1, 2")
            perf = {(r, m): {"attempts": int(at), "hits": int(h), "partial": int(p)}
                    for r, m, at, h, p in cur.fetchall()}
            cur.execute("SELECT rubric_id, scenario_key, milestones FROM public.rubrics")
            rubrics = {rid: {"key": k, "milestones": ms} for rid, k, ms in cur.fetchall()}

    if not perf:
        raise SystemExit("milestone_performance is empty -- run Layer D first")

    rows = []
    for (rid, mid), c in perf.items():
        r = rubrics.get(rid)
        if not r:
            continue
        # milestone_id is the 1-based ARRAY POSITION (see ego_trap/milestone_scoring).
        try:
            idx = int(str(mid).lstrip("M")) - 1
        except ValueError:
            continue
        ms = r["milestones"]
        if not (0 <= idx < len(ms)):
            continue
        m = ms[idx]
        w = (c["hits"] + 0.5 * c["partial"]) / c["attempts"] if c["attempts"] else 0.0
        rows.append({
            "rubric_id": rid, "scenario_key": r["key"], "milestone_id": mid,
            "label": m.get("label", ""), "description": m.get("description", ""),
            "n_criteria_in_rubric": len(ms),
            "attempts": c["attempts"], "hits": c["hits"], "partial": c["partial"], "w": w,
            "ever_hit": (c["hits"] + c["partial"]) > 0,
        })
    return rows


def report(rows: list[dict], show: int, source: str) -> dict:
    """Print the diagnosis and return the summary payload. Pure apart from stdout."""
    unions = union_rows(rows)
    tot_att = sum(r["attempts"] for r in rows)
    tot_h = sum(r["hits"] for r in rows)
    tot_p = sum(r["partial"] for r in rows)
    tot_crit = sum(x["n"] for x in unions)
    tot_attempted = sum(x["n_attempted"] for x in unions)
    print("=" * 86)
    print("WHY IS THE HIT RATE ~9%?  splitting denominator inflation from dead criteria")
    print("=" * 86)
    print(f"  source: {source}")
    print(f"  DENOMINATORS: {len(unions)} rubrics that Layer D ATTEMPTED AT LEAST ONE "
          f"criterion of, holding {tot_crit} criteria;")
    print(f"                {tot_attempted} of those ({tot_attempted/max(tot_crit,1):.1%}) "
          f"carry a milestone_performance row, so {tot_crit - tot_attempted} were never "
          f"attempted and")
    print(f"                therefore never hit. NOT the rubric table: a rubric Layer D "
          f"never touched contributes no")
    print(f"                rows, so it is absent here entirely and its criteria are not in "
          f"the {tot_crit}. The live count")
    print(f"                is 84 rubrics, so {84 - len(unions)} are missing from this "
          f"denominator and every union below")
    print(f"                is conditional on 'Layer D reached this rubric'.")
    print(f"  {len(rows)} criteria scored, {tot_att} attempts, "
          f"{tot_h} full + {tot_p} partial  ->  W = {(tot_h + 0.5*tot_p)/tot_att:.3f}")

    # --- CAUSE B: criteria nobody ever satisfies -------------------------------------
    scoreable = [r for r in rows if r["attempts"] >= MIN_ATTEMPTS_TO_CALL_DEAD]
    dead = [r for r in scoreable if not r["ever_hit"]]
    print(f"\n--- CAUSE B: DEAD CRITERIA (>= {MIN_ATTEMPTS_TO_CALL_DEAD} attempts, NEVER hit "
          f"by anyone, not even partially) ---")
    print(f"  {len(dead)} of {len(scoreable)} well-attempted criteria = "
          f"{len(dead)/max(len(scoreable),1)*100:.0f}%")
    print(f"  they consume {sum(r['attempts'] for r in dead)} of {tot_att} attempts "
          f"({sum(r['attempts'] for r in dead)/tot_att*100:.0f}%) and return zero")
    for r in sorted(dead, key=lambda x: -x["attempts"])[:show]:
        print(f"    {r['attempts']:>4} tries, 0 hits | [{r['label'][:34]}] "
              f"{r['description'][:96]}")

    # --- CAUSE A: is the rubric a union scored as a checklist? -------------------------
    u = np.array([x["union"] for x in unions])
    print(f"\n--- CAUSE A: UNION vs PER-REPLY ---")
    print(f"  Per rubric, what share of its criteria are hit by SOMEBODY at least once?")
    print(f"    aggregate {sum(x['alive'] for x in unions)}/{tot_crit} = "
          f"{sum(x['alive'] for x in unions)/max(tot_crit,1):.1%}")
    print(f"    mean {u.mean():.0%}   median {np.median(u):.0%}   "
          f"p25 {np.percentile(u,25):.0%}   p75 {np.percentile(u,75):.0%}")
    print(f"    rubrics where EVERY criterion is reachable: "
          f"{sum(1 for x in unions if x['union'] == 1.0)}/{len(unions)}")
    print(f"    rubrics where NO criterion is ever hit:     "
          f"{sum(1 for x in unions if x['alive'] == 0)}/{len(unions)}")
    print("\n  READ: a HIGH union with a LOW W is cause A -- every criterion is reachable, but")
    print("  no single reply reaches many of them, so the rubric is a union of moves being")
    print("  scored as a checklist. A LOW union is cause B -- criteria that are simply dead.")

    # Does having more criteria depress the rate? The signature of denominator inflation.
    n = np.array([x["n"] for x in unions], dtype=float)
    w = np.array([x["w"] for x in unions], dtype=float)
    ok = np.isfinite(n) & np.isfinite(w)
    if ok.sum() > 3:
        print(f"\n  corr(criteria per rubric, W) = {np.corrcoef(n[ok], w[ok])[0,1]:+.3f}"
              "   <- negative supports cause A")

    print(f"\n--- the criteria that DO get hit (top {show}) ---")
    for r in sorted(scoreable, key=lambda x: -x["w"])[:show]:
        print(f"    W={r['w']:.2f} ({r['attempts']:>3} tries) [{r['label'][:30]}] "
              f"{r['description'][:88]}")

    return {
        "total_attempts": tot_att, "W": (tot_h + 0.5 * tot_p) / tot_att,
        "n_criteria": len(rows), "n_criteria_in_rubrics": tot_crit,
        "n_criteria_never_attempted": tot_crit - tot_attempted,
        "n_scoreable": len(scoreable), "n_dead": len(dead),
        "dead_share": len(dead) / max(len(scoreable), 1),
        "dead_attempts": sum(r["attempts"] for r in dead),
        "union_aggregate": sum(x["alive"] for x in unions) / max(tot_crit, 1),
        "union_mean": float(u.mean()), "union_median": float(np.median(u)),
        "milestones": rows, "rubrics": unions,
    }


def main() -> None:
    a = _args()
    if a.load:
        prev = json.loads(OUT.read_text(encoding="utf-8-sig"))
        rows = prev["milestones"]
        payload = report(rows, a.show, f"{OUT.name} (recomputed offline, no DB)")
        # The paid per-criterion rows are carried through untouched; only the derived
        # summary is recomputed, so this can never destroy an expensive run.
        assert payload["milestones"] == rows
        payload["derived_recomputed_from_artifact"] = True
    else:
        rows = _fetch_rows()
        payload = report(rows, a.show, "public.milestone_performance + public.rubrics")

    OUT.write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
