#!/usr/bin/env python3
"""Describe both arms' milestones sequentially. ~60 Gemma calls, ZERO DB writes.

Sequential, not concurrent: two streams against the same key invite the rate-limit fallback
that makes two arms judged by different models -- the confound this whole effort keeps
guarding against.
"""
from __future__ import annotations
import subprocess, sys, time
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent
PY = BRAIN.parent / ".venv" / "Scripts" / "python.exe"
ARMS = ["base_1", "rescued"]

t0 = time.time()
for arm in ARMS:
    print(f"\n{'='*78}\n  describing {arm}\n{'='*78}", flush=True)
    rc = subprocess.call([str(PY), "calibration/describe_milestones_arms.py",
                          "--arm", arm, "--overwrite"], cwd=str(BRAIN))
    print(f"[{arm}] exit={rc}", flush=True)
    if rc != 0:
        raise SystemExit(f"arm {arm} failed; a one-armed comparison is not a comparison")
print(f"\nboth arms described in {(time.time()-t0)/60:.1f}m", flush=True)
subprocess.call([str(PY), "calibration/describe_milestones_arms.py",
                 "--read", ",".join(ARMS)], cwd=str(BRAIN))
