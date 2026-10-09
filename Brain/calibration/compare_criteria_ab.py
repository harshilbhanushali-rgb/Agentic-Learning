#!/usr/bin/env python3
"""A/B the milestone-criteria rewrite: narration-worded rubrics vs criterion-worded ones.

Run from Brain/:  python calibration/compare_criteria_ab.py

Zero Gemma, zero writes. Compares the live `public` Layer D tables against a snapshot
schema captured before the rewrite.

This is a CONTROLLED comparison, which is rare in this codebase: the transcripts, the
scenario taxonomy, the milestone clusters, their order, their ids and every evidence field
are byte-identical between the two arms. Only `description`, `label` and `detection_hint`
changed. So a movement in the hit rate is attributable to the WORDING and nothing else.

Background: all 405 stored milestone descriptions were narration about a person (37%
naming Naren, 63% "the speaker", 91% he/she/his/her) because
PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH asked Gemma to "describe" what Naren did. Layer D
scores a DIFFERENT person against those, so a CSM could handle a call well and still miss
every milestone by not reproducing one expert's improvisation.
"""
from __future__ import annotations

import argparse

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from config import load_config
from shared import storage

_DEFAULT_BASELINE = "pre_criteria_20260810"


def _totals(cur, schema: str) -> tuple[int, int, int, int]:
    cur.execute(f"""
        SELECT COALESCE(SUM(attempts),0), COALESCE(SUM(hits),0),
               COALESCE(SUM(partial_hits),0), COUNT(*)
        FROM {schema}.milestone_performance
    """)
    return cur.fetchone()


def _rate_line(label: str, a: int, h: int, p: int, rows: int) -> str:
    if not a:
        return f"  {label:<26} no data"
    return (f"  {label:<26} {a:>5} attempts | {h:>4} hit ({h/a:>5.1%}) | "
            f"{p:>4} partial ({p/a:>5.1%}) | weighted {(h+0.5*p)/a:.3f} | {rows} rows")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--baseline", default=_DEFAULT_BASELINE,
                    help="snapshot schema captured before the rewrite")
    ap.add_argument("--show", type=int, default=10, help="per-milestone movers to print")
    args = ap.parse_args()

    cfg = load_config()
    conn = storage.get_connection(cfg.database_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                        (args.baseline,))
            if cur.fetchone() is None:
                print(f"ERROR: baseline schema {args.baseline!r} does not exist.")
                return

            print("=" * 84)
            print("MILESTONE HIT RATE: narration-worded (before) vs criterion-worded (after)")
            print("=" * 84)
            b = _totals(cur, args.baseline)
            a = _totals(cur, "public")
            print(_rate_line("BEFORE (narration)", *b))
            print(_rate_line("AFTER  (criteria)", *a))
            if b[0] and a[0]:
                bw, aw = (b[1] + 0.5 * b[2]) / b[0], (a[1] + 0.5 * a[2]) / a[0]
                print(f"\n  weighted score {bw:.3f} -> {aw:.3f}"
                      f"   ({'+' if aw >= bw else ''}{(aw - bw):.3f}, "
                      f"{'x%.1f' % (aw / bw) if bw else 'n/a'})")
                print(f"  full-hit rate  {b[1]/b[0]:.1%} -> {a[1]/a[0]:.1%}")
                # Attempt counts should be close. A large gap means Step 0 detected a
                # different signal set, which would break the controlled comparison.
                drift = abs(a[0] - b[0]) / b[0]
                print(f"\n  attempt-count drift: {b[0]} -> {a[0]} ({drift:+.1%})")
                if drift > 0.15:
                    print("  ! >15% drift means the two arms did not score the same population,")
                    print("    so this is no longer a clean wording-only comparison.")
                else:
                    print("  same signal population, so the delta is attributable to wording.")

            # --- which milestones moved ----------------------------------------
            cur.execute(f"""
                SELECT COALESCE(n.scenario_key, o.scenario_key) AS skey,
                       COALESCE(n.milestone_id, o.milestone_id) AS mid,
                       COALESCE(o.attempts,0), COALESCE(o.hits,0), COALESCE(o.partial_hits,0),
                       COALESCE(n.attempts,0), COALESCE(n.hits,0), COALESCE(n.partial_hits,0)
                FROM {args.baseline}.milestone_performance o
                FULL OUTER JOIN public.milestone_performance n
                  ON n.rubric_id = o.rubric_id AND n.milestone_id = o.milestone_id
                     AND n.csm_id = o.csm_id
            """)
            rows = cur.fetchall()
            movers = []
            for skey, mid, oa, oh, op, na, nh, np_ in rows:
                ow = (oh + 0.5 * op) / oa if oa else 0.0
                nw = (nh + 0.5 * np_) / na if na else 0.0
                movers.append((nw - ow, skey, mid, oa, oh, op, na, nh, np_))
            gained = sorted((m for m in movers if m[0] > 0), key=lambda x: -x[0])
            lost = sorted((m for m in movers if m[0] < 0), key=lambda x: x[0])
            print(f"\n  milestones improved: {len(gained)} | worsened: {len(lost)} | "
                  f"unchanged: {len(movers) - len(gained) - len(lost)}")

            for title, group in (("IMPROVED", gained), ("WORSENED", lost)):
                if not group:
                    continue
                print(f"\n  --- {title} (top {min(args.show, len(group))}) ---")
                print(f"    {'delta':>7}  {'before a/h/p':>13}  {'after a/h/p':>12}  milestone")
                for d, skey, mid, oa, oh, op, na, nh, np_ in group[:args.show]:
                    print(f"    {d:>+7.2f}  {f'{oa}/{oh}/{op}':>13}  {f'{na}/{nh}/{np_}':>12}  "
                          f"{skey} :: {mid}")

            # --- milestones the rewrite itself flagged --------------------------
            cur.execute("""
                SELECT r.scenario_key, m->>'label', m->>'description'
                FROM public.rubrics r, jsonb_array_elements(r.milestones) m
                WHERE (m->>'not_coachable_flag')::bool IS TRUE
            """)
            flagged = cur.fetchall()
            if flagged:
                print(f"\n{'=' * 84}\nFLAGGED not_coachable BY THE REWRITE ({len(flagged)})")
                print("The rewriter judged these to be accounts of what someone said once,")
                print("not transferable moves. They cannot be 'hit' by anyone -- candidates")
                print(f"for removal from the rubrics.\n{'=' * 84}")
                for skey, label, desc in flagged:
                    print(f"  {skey} :: {label}")
                    print(f"    {desc}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
