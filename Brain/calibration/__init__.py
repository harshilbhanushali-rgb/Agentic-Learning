"""Calibration and analysis harnesses -- not part of the production pipeline.

Nothing in `v1/`, `v2/`, `shared/` or `preprocessing/` imports this package. These
scripts read the live DB and the embed cache to measure and calibrate thresholds;
they are the tools that produced the numbers recorded in CLAUDE.md.

    python calibration/dry_run_layer_a.py --sweep

Artifact paths (the JSON blobs these scripts write and re-read via `--load`) resolve
through ARTIFACTS_DIR below, which is anchored to `Brain/` via `__file__` rather than
to the current working directory. The old bare `Path("sink_pool_clusters.json")`
defaults resolved against CWD, so they silently wrote to -- or failed to find -- the
wrong place whenever a script was launched from anywhere other than `Brain/`.
"""
from pathlib import Path

BRAIN_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = BRAIN_DIR / "artifacts"
