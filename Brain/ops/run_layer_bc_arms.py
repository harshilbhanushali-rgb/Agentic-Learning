#!/usr/bin/env python3
"""Run the four Layer B/C arms sequentially, then compare. ZERO chat calls, ZERO DB writes.

Launch it in a visible window:

    .\\ops\\run_visible.ps1 -Script ops/run_layer_bc_arms.py

    base_1    clean2_base taxonomy
    base_2    clean2_base taxonomy AGAIN  -- the pair (base_1, base_2) IS the noise floor
    rescued   clean2_rescued taxonomy     -- the treatment
    placebo   clean2_base + topically WRONG padding matched to rescued's clause volume
              AND to its support denominator

*** ORDER IS LOAD-BEARING. *** `placebo` reads rescued's per-cluster clause volume and call
count, so it MUST run after `rescued`. It refuses with a clear error otherwise rather than
silently matching nothing.

*** ONE PROCESS PER ARM, AND THAT IS THE WHOLE POINT OF THE DRIVER. *** UMAP+HDBSCAN is
documented non-reproducible ACROSS process launches (385/398/403-407 milestones for identical
input) and deterministic WITHIN one. Running base_1 and base_2 in a single process would report
a floor of exactly zero -- which reads as perfect determinism and is nothing of the kind, the
same shape as the gateway-cache incident. Separate processes are what make the floor real.

COST. Nothing measurable. Layer C Pass 1 is Gemma-free and every corpus vector is served from
the gemini cache with a hard abort on a miss. The only spend is each arm's ~150 scenario-
description embeddings, and the three arms sharing the clean2_base taxonomy hit cache after the
first, so the true total is ~300 requests for the whole run.

Re-running is safe: each arm writes its own artifact and refuses to clobber one without
--overwrite, so a completed arm is not silently replaced.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent          # ops/ -> Brain/
PY = BRAIN.parent / ".venv" / "Scripts" / "python.exe"
HARNESS = "calibration/layer_bc_arms.py"

BASE_TAX = "clean2_base"
RESCUED_TAX = "clean2_rescued"

ARMS = [
    ("base_1", ["--taxonomy", BASE_TAX]),
    ("base_2", ["--taxonomy", BASE_TAX]),
    ("rescued", ["--taxonomy", RESCUED_TAX]),
    ("placebo", ["--taxonomy", BASE_TAX, "--placebo", "--volume-from", "rescued"]),
]
COMPARE_WITH = [a for a, _ in ARMS]


def run(args: list[str]) -> int:
    cmd = [str(PY), HARNESS, *args]
    print(f"\n{'=' * 78}\n  {' '.join(cmd[1:])}\n{'=' * 78}", flush=True)
    return subprocess.call(cmd, cwd=str(BRAIN))


def main() -> None:
    if not PY.exists():
        raise SystemExit(f"python not found at {PY}")
    t0 = time.time()
    for arm, extra in ARMS:
        started = time.time()
        rc = run(["--arm", arm, *extra, "--overwrite"])
        print(f"\n[{arm}] exit={rc} in {(time.time() - started) / 60:.1f}m", flush=True)
        if rc != 0:
            raise SystemExit(
                f"\nARM {arm} FAILED (exit {rc}). Stopping rather than running the rest: a "
                f"comparison missing an arm is not a comparison, the noise floor needs BOTH "
                f"base arms, and the placebo needs `rescued` to have finished. Nothing here "
                f"is paid, so fixing the cause and re-running this driver costs only time.")
    print(f"\nall arms done in {(time.time() - t0) / 60:.1f}m", flush=True)
    rc = run(["--compare", ",".join(COMPARE_WITH)])
    print(f"\n[compare] exit={rc}", flush=True)
    print("\nZERO chat calls. NOTHING was written to Postgres.", flush=True)
    sys.exit(rc)


if __name__ == "__main__":
    main()
