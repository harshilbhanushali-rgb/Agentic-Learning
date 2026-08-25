#!/usr/bin/env python3
"""UNION TAXONOMY REBUILD — Stage A: pool fidelity (T0) + the new-turn embedding fetch.

Spec: docs/superpowers/specs/2026-08-18-union-taxonomy-rebuild-design.md §2 (frozen).

WHAT THIS IS. The rebuild clusters the UNION corpus (`recordings/` + `recordings_pull_keep/`)
in turn mode. This harness owns the two Stage A obligations and NOTHING downstream:

  T0 (pool fidelity, HARD ABORT): the old-corpus CLIENT-turn count must equal 20,788
     exactly — the audited clean figure `clean2_base` was built on. Any other number is a
     parse/roster regression and nothing downstream is reportable.
  FETCH: gemini-embedding-2 @ native 3072 through the gateway, ONE text per request at
     N concurrent workers — never batched (`trial_gateway.py` measured the /embeddings
     endpoint silently returning fewer vectors than inputs when batched). Old turns are
     already cached; the new-corpus turns are the ~28-minute spend. Verified 0-missing by
     a cache re-read afterwards.

*** THE OLD BLOCK LEADS, AND THAT ORDER IS LOAD-BEARING. *** `build_union_pool` parses the
old corpus first (sorted) then the new corpus (sorted), so union pool index i for
i < 20,788 IS old-pool index i. Stage D's G-R1 maps `clean2_base`'s member turns onto the
union pool through exactly that identity; reordering the blocks would silently score the
wrong turns. T0 pins the boundary; `--verify` re-asserts the prefix sha every later stage
run can check against.

Everything here is production machinery imported, never paraphrased: the transcript
parser + Avoma rosters + speaker classification (`preprocessing.transcript_parser`), the
turn-mode pool (`v2.layer_a.build_client_pool`), the stem-collision assert
(`expanded_pool_stage1.assert_no_stem_collision`), the fetch
(`trial_pool_unit_gemini.embed_cached`) and the cache-only re-read
(`layer_bc_arms._load_cached`).

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/union_pool_fetch.py --t0
    .\\ops\\run_visible.ps1 -Script calibration/union_pool_fetch.py -ScriptArgs '--fetch'
    ..\\.venv\\Scripts\\python.exe calibration/union_pool_fetch.py --verify
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OLD_DIR = "recordings"
NEW_DIR = "recordings_pull_keep"
# Frozen in spec §2. clean2_base was adjudicated on exactly this many CLIENT turns; any
# other count here means the parse or a roster changed underneath the reference map.
T0_EXPECTED_OLD_TURNS = 20_788
WIDTH = 3072
WORKERS = 20
T0_OUT = ARTIFACTS_DIR / "union_pool_t0.json"


# ---------------------------------------------------------------------------------------
# pure helpers (covered by tests/test_union_pool_fetch.py)
# ---------------------------------------------------------------------------------------

def count_by_origin(call_ids: list[str], old_stems: set[str]) -> tuple[int, int]:
    """(old_turns, new_turns) for a pool whose call ids are transcript stems. The stems
    are asserted non-colliding upstream, so membership in `old_stems` is unambiguous."""
    old = sum(1 for c in call_ids if c in old_stems)
    return old, len(call_ids) - old


def t0_verdict(old_turns: int, expected: int = T0_EXPECTED_OLD_TURNS) -> dict:
    """The frozen T0 rule: exact equality, nothing softer. A regression that loses 3
    turns is the same finding as one that loses 3,000 — the reference map no longer
    describes this parse."""
    return {"expected_old_turns": expected, "old_turns": old_turns,
            "pass": old_turns == expected}


# ---------------------------------------------------------------------------------------
# the one union pool builder — every rebuild stage imports THIS, no stage re-derives it
# ---------------------------------------------------------------------------------------

def build_union_pool(old_dir: str = OLD_DIR, new_dir: str = NEW_DIR):
    """[(texts, call_ids, old_stems, n_old_files, n_new_files)] — old block FIRST.

    Production parse per file (roster sidecars, interview/staff/UNATTRIBUTED handling all
    live inside `parse_transcript` + config), production turn pool. A scratchpad re-parse
    disagreed with production by ~20% twice in this repo's history; import, never
    paraphrase.
    """
    from config import load_config
    from preprocessing.transcript_parser import parse_transcript, load_roster
    from v2.layer_a import build_client_pool
    from calibration.expanded_pool_stage1 import assert_no_stem_collision

    cfg = load_config()
    old_files = sorted(Path(old_dir).glob("*.txt"))
    new_files = sorted(Path(new_dir).glob("*.txt"))
    if not old_files:
        raise SystemExit(f"no transcripts in {old_dir}/")
    if not new_files:
        raise SystemExit(f"no transcripts in {new_dir}/")
    assert_no_stem_collision({f.stem for f in old_files}, {f.stem for f in new_files})

    turns = []
    files = old_files + new_files
    for n, f in enumerate(files, 1):
        turns.extend(parse_transcript(str(f), cfg.joveo_speakers_lower,
                                      cfg.naren_name_lower, roster=load_roster(str(f))))
        if n % 200 == 0 or n == len(files):
            print(f"  parsed {n}/{len(files)} calls", flush=True)
    texts, call_ids = build_client_pool(turns, unit="turn")
    return texts, call_ids, {f.stem for f in old_files}, len(old_files), len(new_files)


def pool_manifest(texts: list[str], call_ids: list[str], old_stems: set[str],
                  n_old_files: int, n_new_files: int) -> dict:
    """Everything T0 records; the sha fields are what every later stage joins on."""
    from calibration.adjudication_ab import pool_sha

    old_turns, new_turns = count_by_origin(call_ids, old_stems)
    # Self-verify block contiguity at record time (pre-run audit finding 3): the
    # old_prefix_sha anchor is only meaningful if the first `old_turns` items really
    # are the old block, not just the same count.
    if not all(c in old_stems for c in call_ids[:old_turns]):
        raise SystemExit("BLOCK CONTIGUITY BROKEN: a new-corpus turn precedes the old "
                         "block's end — the index-identity invariant is void.")
    return {
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "pid": os.getpid(),
        "old_dir": OLD_DIR, "new_dir": NEW_DIR,
        "n_old_files": n_old_files, "n_new_files": n_new_files,
        "n_turns_union": len(texts),
        "n_calls_union": len(set(call_ids)),
        "t0": t0_verdict(old_turns),
        "new_turns": new_turns,
        "pool_sha": pool_sha(texts),
        # The G-R1 block-identity anchor: sha of the leading old block alone. Stage D
        # asserts this equals the sha of a fresh old-corpus pool before mapping
        # clean2_base member indices onto the union.
        "old_prefix_sha": pool_sha(texts[:old_turns]),
        "embedder": f"gemini-embedding-2@{WIDTH}",
    }


# ---------------------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------------------

def load_t0(require_pass: bool = True) -> dict:
    if not T0_OUT.exists():
        raise SystemExit(f"{T0_OUT.name} not found — run --t0 first")
    man = json.loads(T0_OUT.read_text(encoding="utf-8-sig"))
    if require_pass and not man["t0"]["pass"]:
        raise SystemExit(f"T0 FAILED in {T0_OUT.name} ({man['t0']}) — the pool is not the "
                         f"audited one; nothing downstream is reportable.")
    return man


def _rebuild_and_check(man: dict):
    """Re-parse and assert the pool is byte-identical to what T0 recorded. Every stage
    that consumes the pool goes through this, so a transcript edited between stages
    aborts instead of silently shifting every index."""
    from calibration.adjudication_ab import pool_sha

    texts, call_ids, old_stems, *_ = build_union_pool()
    sha = pool_sha(texts)
    if sha != man["pool_sha"]:
        raise SystemExit(f"POOL DRIFT: sha {sha} vs T0's {man['pool_sha']}. The corpus "
                         f"changed since --t0; re-run --t0 deliberately if that was "
                         f"intended.")
    return texts, call_ids, old_stems


def stage_t0() -> None:
    if T0_OUT.exists():
        raise SystemExit(f"{T0_OUT.name} already exists — refusing to clobber a recorded "
                         f"T0. Delete it deliberately if the corpus is MEANT to have "
                         f"changed.")
    texts, call_ids, old_stems, n_old, n_new = build_union_pool()
    man = pool_manifest(texts, call_ids, old_stems, n_old, n_new)
    t0 = man["t0"]
    print(f"\n[T0] old-corpus CLIENT turns: {t0['old_turns']} "
          f"(expected {t0['expected_old_turns']}) -> "
          f"{'PASS' if t0['pass'] else 'FAIL'}")
    print(f"[T0] new-corpus CLIENT turns: {man['new_turns']}   "
          f"union {man['n_turns_union']} over {man['n_calls_union']} calls")
    T0_OUT.write_text(json.dumps(man, indent=1), encoding="utf-8")
    print(f"wrote {T0_OUT.name}")
    if not t0["pass"]:
        raise SystemExit("T0 HARD ABORT: the old corpus is not the audited 20,788-turn "
                         "pool. Parse/roster regression — nothing downstream may run.")
    print("UNION T0 PASS", flush=True)


def stage_fetch() -> None:
    """The ~28-minute spend. Resumable: embed_cached skips every cached row, so a crash
    or VPN drop re-runs for the cost of the misses only."""
    from calibration.trial_pool_unit_gemini import embed_cached
    from calibration.layer_bc_arms import _load_cached

    man = load_t0()
    texts, _, _ = _rebuild_and_check(man)
    uniq = sorted(set(texts))
    print(f"[fetch] {len(texts)} turns, {len(uniq)} distinct texts", flush=True)
    # SPEND CEILING (pre-run audit finding 1). The budgeted spend is the NEW corpus
    # only — the old block was paid for long ago. If the cache reports more misses than
    # the manifest's new-turn count, the old-block cache has eroded (moved/cleared DB)
    # and this run would silently re-pay ~21k requests: that is §8's budget-escalation
    # condition, so ABORT and ask the operator instead of discovering the bill.
    _, missing = _load_cached(uniq, WIDTH)
    n_missing = len(missing) if missing else 0
    if n_missing > man["new_turns"]:
        raise SystemExit(
            f"SPEND CEILING: {n_missing} uncached texts exceeds the manifest's "
            f"{man['new_turns']} new-corpus turns — the old-block cache has eroded. "
            f"HALT; ask the operator before re-paying the old corpus.")
    print(f"[fetch] {n_missing} uncached (ceiling {man['new_turns']} = new turns)",
          flush=True)
    embed_cached(uniq, WORKERS)
    mat, missing = _load_cached(uniq, WIDTH)
    if mat is None:
        raise SystemExit(f"ABORT: {len(missing)} text(s) STILL uncached after the fetch, "
                         f"e.g. {missing[:2]!r} — do not proceed to clustering.")
    print("[verify] cache re-read: 0 texts missing")
    print("UNION FETCH COMPLETE", flush=True)


def stage_verify() -> None:
    """Free re-assertion: pool unchanged, cache complete. Run before any later stage."""
    from calibration.layer_bc_arms import _load_cached

    man = load_t0()
    texts, _, _ = _rebuild_and_check(man)
    mat, missing = _load_cached(sorted(set(texts)), WIDTH)
    if mat is None:
        raise SystemExit(f"{len(missing)} text(s) uncached — run --fetch")
    print(f"[verify] pool sha {man['pool_sha']} OK; {len(set(texts))} distinct texts all "
          f"cached at {WIDTH}d")
    print("UNION VERIFY OK", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--t0", action="store_true", help="pool fidelity check (free)")
    p.add_argument("--fetch", action="store_true",
                   help="embed the union pool (old cached, new is the spend); VPN needed")
    p.add_argument("--verify", action="store_true", help="free pool+cache re-assertion")
    a = p.parse_args()
    if a.t0:
        stage_t0()
    elif a.fetch:
        stage_fetch()
    elif a.verify:
        stage_verify()
    else:
        p.print_help()


if __name__ == "__main__":
    main()
