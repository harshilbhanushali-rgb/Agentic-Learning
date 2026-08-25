#!/usr/bin/env python3
"""Run the union-rebuild adjudication arm (`union_rescued`), then its T2 checks.

Spec: docs/superpowers/specs/2026-08-18-union-taxonomy-rebuild-design.md §4 (frozen).
Launch in a visible window so the sequential run can be watched, never polled:

    .\\ops\\run_visible.ps1 -Script ops/run_union_adjudication.py

ONE arm, sequential by construction (the accepted-list duplicate detection is an ordered
dependency). ~1 chat call per cluster, expected ~300-450, HARD STOP 500 — enforced inside
adjudication_ab by --budget (max_retries=1, every attempt persisted BEFORE its POST).
Resumable at zero re-spend: the checkpoint is keyed on a content hash of the memberships.

The clusters come from artifacts/union_clusters.json (--clusters-from), so what is
adjudicated is PROVABLY Stage B's persisted seed-42 clustering, not a second UMAP launch.
The base membership set stays on disk un-adjudicated (the fallback arm — separate,
operator-approved spend).

T2 (integrity, spec §4): failed-row share <= 5% else HALT AND ASK; served_model
uniformity reported, shout on mixture.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent          # ops/ -> Brain/
PY = BRAIN.parent / ".venv" / "Scripts" / "python.exe"
HARNESS = "calibration/adjudication_ab.py"

# Which membership set to adjudicate: "rescued" (the primary arm, spec §4) or "base"
# (the FALLBACK arm — operator-chosen 2026-08-18 after G-R4 failed 8/12 on the rescued
# map; spec §1 pre-registered exactly this choice). Passed as the one CLI arg.
MEMBERSHIP = (sys.argv[1] if len(sys.argv) > 1 else "rescued")
if MEMBERSHIP not in ("rescued", "base"):
    raise SystemExit(f"argument must be rescued|base, got {MEMBERSHIP!r}")
ARM = f"union_{MEMBERSHIP}"
# BUDGET AMENDMENT, operator, 2026-08-18 (on the record): the union pool measured
# 58,002 turns (spec expected ~33k), so the operator REMOVED the 500-call hard stop
# when approving the full-size run ("do it and remove the 500 limit thing"). The
# nominal budget below is functionally uncapped (cluster count cannot approach it);
# it is kept non-zero ONLY so adjudication_ab keeps max_retries=1 and the pre-POST
# attempt accounting — the spend DISCIPLINE stays, the STOP is gone.
ARM_ARGS = ["--arm", ARM,
            "--recordings", "recordings,recordings_pull_keep",
            "--clusters-from", "artifacts/union_clusters.json",
            "--membership", MEMBERSHIP,
            "--budget", "100000"]


def main() -> None:
    if not PY.exists():
        raise SystemExit(f"python not found at {PY}")
    cmd = [str(PY), HARNESS, *ARM_ARGS]
    print(f"{'=' * 78}\n  {' '.join(cmd[1:])}\n{'=' * 78}", flush=True)
    t0 = time.time()
    rc = subprocess.call(cmd, cwd=str(BRAIN))
    print(f"\n[{ARM}] exit={rc} in {(time.time() - t0) / 60:.1f}m", flush=True)
    if rc != 0:
        raise SystemExit(f"ARM {ARM} FAILED (exit {rc}). The checkpoint resumes where it "
                         f"stopped — nothing already paid for is re-spent. Fix the cause "
                         f"and re-run this driver.")

    # ---- T2 -----------------------------------------------------------------------
    sys.path.insert(0, str(BRAIN))
    from calibration.adjudication_ab import paths, t2_verdict

    _, out = paths(ARM)
    art = json.loads(out.read_text(encoding="utf-8-sig"))
    t2 = t2_verdict(art["stats"], art.get("served_models", {}))
    print("\n" + "=" * 78)
    print("T2 INTEGRITY")
    print("=" * 78)
    print(f"  failed rows      : {t2['failed']}/{t2['n']} = {t2['failed_share']*100:.1f}% "
          f"(bar <= {t2['max_failed_share']*100:.0f}%) -> "
          f"{'OK' if t2['failed_ok'] else 'FAIL'}")
    print(f"  served models    : {t2['served_models']}")
    if not t2["served_uniform"]:
        print("  !! MODEL MIXTURE — the gateway fell back for part of the run; downstream "
              "reads are model-confounded. On the record.")
    print(f"  chat attempts    : {art.get('chat_attempts')} (budget {art.get('budget')})")
    if not t2["pass"]:
        raise SystemExit("T2 FAILED (failed-row share above 5%): HALT — ask the operator "
                         "before anything downstream consumes this taxonomy.")
    print("\nNOTHING was written to Postgres.")
    print("UNION ADJUDICATION COMPLETE", flush=True)


if __name__ == "__main__":
    main()
