#!/usr/bin/env python3
"""Run the adjudication A/B arms sequentially, then compare. ~450 chat calls, ZERO DB.

Launch it in a visible window so the run can be watched rather than tailed:

    .\\ops\\run_visible.ps1 -Script ops/run_adjudication_ab.py

WHY A DRIVER RATHER THAN THREE LAUNCHES. The arms must not overlap. Each does its own UMAP
fit (two in one process is this machine's documented memory failure), and three concurrent
gateway streams invite the rate-limit fallback that makes two arms judged by different
models -- the exact confound `adjudication_ab.compare` now shouts about. Sequential is the
requirement, not a preference.

RESUMING IS SAFE AND COSTS NOTHING. Each arm checkpoints after every cluster under an
identity keyed on a content hash of its memberships, so re-running this driver picks up
where it stopped and a completed arm is skipped entirely. Kill the window whenever; nothing
already paid for is lost.

    clean2_base      the surviving clusters of the 20,788-turn corpus
    clean2_rescued   the SAME clusters grown by rescue_centroid's admitted turns

Both feed calibration/layer_bc_arms.py as `--taxonomy`. See the ARMS comment below for why
there is no second base arm this time.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent          # ops/ -> Brain/
PY = BRAIN.parent / ".venv" / "Scripts" / "python.exe"
HARNESS = "calibration/adjudication_ab.py"

# `nc_` = run with the gateway cache BYPASSED. The first attempt at this comparison used the
# gateway's default, which CACHES chat completions: base_b sent 245 prompts byte-identical to
# base_a's, hit the cache 245 times, and echoed base_a's answers back -- 245/245 identical
# verdicts, keys, reasons AND descriptions, which reads as perfect determinism and is nothing
# of the kind. Measured directly: same prompt 1741ms -> 249ms -> 236ms with byte-identical
# text; one trailing space changed, 806ms and different text. `cache: {"no-cache": true}`
# bypasses it and the model then genuinely varies.
#
# All three arms re-run under the SAME policy, because a cache bypassed on one arm and not the
# other is exactly the asymmetric-filtering error this repo keeps re-learning. The old
# cache-contaminated artifacts are kept under their original names as the record.
# base_a is NOT re-run. It went first, so its 245 prompts were novel and the cache was cold --
# every verdict in it is a genuine generation. (Checked the one thing that would break that:
# whether cache-enabled requests get a pinned seed. They do not -- a cold cache-enabled call
# and two no-cache calls all returned different text, so all three are samples from the same
# distribution.) Re-running it would buy nothing.
#
# base_b IS re-run: it was a pure cache echo and carries no information.
# rescued IS re-run: 211/245 of its prompts were novel, but the 34 non-grown clusters could
# have inherited base_a's cached verdicts before the accepted-list diverged. That understates
# the treatment rather than inflating it -- but a cache bypassed on one arm and not the other
# is the asymmetric-filtering error this repo keeps re-learning, so remove the doubt.
# CLEANED CORPUS. All three arms re-run from scratch because the pool itself changed:
#   -544 turns  Joveo staff misclassified as CLIENT (ops/repair_speaker_rosters.py)
#   -1,490      23 job-interview calls quarantined (Avoma subject/purpose + text heuristic)
#   23,949 -> 21,915 CLIENT turns over 393 transcripts
# The earlier base_a/nc_base_b/nc_rescued artifacts describe a corpus that no longer exists,
# so nothing from them may be compared against these. The rescue is computed IN PROCESS
# (--rescue centroid) rather than loaded from clustering_bench_members.json, which is keyed
# to the old pool and would align rescued turns to clusters that are gone.
#
# ---------------------------------------------------------------------------------------
# 2026-08-16, SECOND CLEANUP. THE POOL MOVED AGAIN and the `clean_*` artifacts above are now
# themselves stale: `SpeakerRole.UNATTRIBUTED` removed a further 1,127 turns that Avoma's
# diarization could not attribute to anyone (`Unknown Speaker`, dial-in numbers, notetaker
# bots) and which `_classify` had been failing OPEN into CLIENT.
#
#   21,915 -> 20,788 CLIENT turns over the same 393 transcripts
#
# TWO ARMS, NOT THREE, and the reason is that these arms are no longer the experiment -- they
# are the INPUT to one. The adjudication question ("does the rescue change the taxonomy?") was
# answered on the `clean_*` arms: flip rate 12.5%/10.3% against a 12.9% noise floor, i.e. NULL
# on rate, while scenario COUNT moved 26/28 -> 34. What is unmeasured is whether any of that
# reaches a RUBRIC, which is what calibration/layer_bc_arms.py measures next and which needs
# exactly one taxonomy per arm. A second base arm here would re-price adjudication noise that
# has already been priced, at ~224 paid calls; the Layer B/C noise floor it would inform is
# instead measured downstream, where Pass 1 is Gemma-free and a repeat run costs NOTHING.
#
# `clean2_` prefix, deliberately: reusing `clean_base_a` would silently RESUME its checkpoint,
# and adjudication_ab's identity guard hard-fails on a members_sha mismatch -- so the run would
# abort rather than blend, but only after the arm name had already been overloaded to mean two
# different corpora.
ARMS = [
    ("clean2_base", []),
    ("clean2_rescued", ["--rescue", "centroid"]),
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
        rc = run(["--arm", arm, *extra])
        mins = (time.time() - started) / 60
        print(f"\n[{arm}] exit={rc} in {mins:.1f}m", flush=True)
        if rc != 0:
            raise SystemExit(
                f"\nARM {arm} FAILED (exit {rc}). Stopping rather than running the remaining "
                f"arms: a comparison missing an arm is not a comparison, and the noise floor "
                f"needs BOTH base arms. Fix the cause and re-run this driver -- the checkpoint "
                f"resumes {arm} where it stopped, so nothing already paid for is re-spent.")
    print(f"\nall arms done in {(time.time() - t0) / 60:.1f}m", flush=True)
    rc = run(["--compare", ",".join(COMPARE_WITH)])
    print(f"\n[compare] exit={rc}", flush=True)
    print("\nNOTHING was written to Postgres.", flush=True)
    sys.exit(rc)


if __name__ == "__main__":
    main()
