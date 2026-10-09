#!/usr/bin/env python3
"""STEP 0 GATE: how many response-clause embeddings must be PAID FOR before the Layer B/C
arms can run? Read-only -- zero gateway requests, zero Postgres, zero writes of any kind.

Spec: docs/superpowers/specs/2026-08-16-layer-bc-downstream-validation-design.md (F1).

WHY THIS EXISTS. The gemini cache was warmed for CLIENT TURNS only -- that is what Layer A
clusters and what `trial_pool_unit_gemini.py` paid for. Layer C does not cluster client turns;
it clusters NAREN'S RESPONSE CLAUSES (`v2/layer_c.build_clause_pool` -> `segment_into_clauses`
over `kb_pairs.response_text`). Those texts have never been embedded on this backend. Running
the arms without knowing that number is how a trial discovers mid-run that it needs 74k paid
requests against a rate limit.

THREE THINGS THIS GETS RIGHT ON PURPOSE, each because getting them wrong changes the answer:

  1. `extract_pairs` IS CALLED PER CALL, exactly as `v2/pipeline.py:39-44` does. Concatenating
     every transcript into one turn list pairs a CLIENT trigger at the end of call A with
     NAREN's response at the start of call B -- a pair that exists in no conversation. It also
     inflates the count.
  2. The PRODUCTION segmenter is used, not a reimplementation. `preprocessing/segmenter.py` is
     shared with `v2/layer_c.py:77`; sentence boundaries move when spaCy is loaded with
     different components disabled, and that has already produced a ~20% disagreement in this
     repo (73,771 true clauses vs 88,431 from a scratchpad copy).
  3. The cache key is IMPORTED from `trial_pool_unit_gemini`, never retyped. It is
     sha256(model|NATIVE_dims|text) and the native width is load-bearing -- keying on an
     analysis width misses every row and silently reports a 100% miss rate.

The cache is opened `mode=ro`. `_cache_open()` issues CREATE TABLE IF NOT EXISTS, which is a
write; a scoping script must not be able to touch the artifact it is measuring.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/scope_layer_bc_embeddings.py
    ..\\.venv\\Scripts\\python.exe calibration/scope_layer_bc_embeddings.py --limit 30
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

# Observed gateway throughput at 20 concurrent workers, measured 2026-08-16 over the 24k-turn
# backfill. Used only to turn a request count into a wall-clock estimate for the spend decision.
REQ_PER_SEC = 46.0


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--limit", type=int, default=0,
                   help="scope only the first N transcripts (path test; NOT a sample -- "
                        "alphabetical order is not random, see CLAUDE.md)")
    p.add_argument("--out", default=str(ARTIFACTS_DIR / "layer_bc_embed_scope.json"))
    p.add_argument("--fetch", action="store_true",
                   help="AFTER reporting, actually SPEND: fetch the missing response-clause "
                        "vectors into the gemini cache. Off by default so the gate cannot be "
                        "passed by accident -- the report is the decision, this is the act.")
    p.add_argument("--workers", type=int, default=20,
                   help="gateway concurrency for --fetch. One text per request ALWAYS; "
                        "throughput comes from concurrency, never from batching (the "
                        "endpoint silently returns fewer vectors than inputs when batched).")
    return p.parse_args()


def cached_keys(keys: list[str], cache_path: Path, table: str = "vec",
                col: str = "k") -> set[str]:
    """Which of `keys` are already in the gemini vector cache. READ-ONLY connection.

    NOTE `gemini_embed_cache.db` (the gateway trial cache, keyed sha256(model|dims|text)) is a
    different file AND a different key scheme from production's `embed_cache.db` (keyed
    sha256(model|prefix|text), see shared/embed_cache.py). Pointing this at the wrong one
    reports a 100% miss rate on a warm cache.
    """
    if not cache_path.exists():
        print(f"  ! cache {cache_path} does not exist -- everything is a miss")
        return set()
    conn = sqlite3.connect(f"file:{cache_path.as_posix()}?mode=ro", uri=True)
    try:
        found: set[str] = set()
        for i in range(0, len(keys), 900):          # SQLite host-parameter limit
            chunk = keys[i:i + 900]
            q = ",".join("?" * len(chunk))
            for (k,) in conn.execute(
                    f"SELECT {col} FROM {table} WHERE {col} IN ({q})", chunk):
                found.add(k)
        return found
    finally:
        conn.close()


def main() -> None:
    a = _args()
    t0 = time.time()

    from config import load_config
    from preprocessing import segmenter
    from preprocessing.transcript_parser import parse_transcript, load_roster, SpeakerRole
    from v1.layer_b import extract_pairs
    from v2.layer_a import build_client_pool
    from calibration.trial_pool_unit_gemini import CACHE, EMBED_MODEL, EMBED_DIMS, _key

    cfg = load_config()
    files = sorted(Path(a.recordings).glob("*.txt"))
    if not files:
        raise SystemExit(f"no transcripts in {a.recordings}/")
    if a.limit:
        files = files[:a.limit]
        print(f"LIMIT MODE -- {len(files)} transcripts. Path test only; counts do NOT "
              f"extrapolate.\n")

    print(f"Parsing {len(files)} transcript(s) and extracting pairs PER CALL...", flush=True)

    all_turns = []
    pairs_all: list[dict] = []
    per_call: list[dict] = []
    for n, path in enumerate(files, 1):
        turns = parse_transcript(str(path), cfg.joveo_speakers_lower, cfg.naren_name_lower,
                                 roster=load_roster(str(path)))
        all_turns.extend(turns)
        # db_call_id is a synthetic index: nothing here touches Postgres, and extract_pairs
        # only ever copies it into the pair dict.
        pairs = extract_pairs(turns, n)
        for p in pairs:
            p["call_filename"] = path.name
        pairs_all.extend(pairs)
        per_call.append({"call": path.name, "turns": len(turns), "pairs": len(pairs)})
        if n % 50 == 0 or n == len(files):
            print(f"  {n}/{len(files)} calls  {len(pairs_all)} pairs so far "
                  f"({time.time()-t0:.0f}s)", flush=True)

    client_turns = sum(1 for t in all_turns if t.role == SpeakerRole.CLIENT)
    calls_with_pairs = len({p["call_filename"] for p in pairs_all})

    print(f"\nSegmenting {len(pairs_all)} response(s) with the PRODUCTION segmenter...",
          flush=True)
    clauses: list[str] = []
    for i, p in enumerate(pairs_all, 1):
        clauses.extend(segmenter.segment_into_clauses(p["response_text"]))
        if i % 1000 == 0:
            print(f"  {i}/{len(pairs_all)} responses  {len(clauses)} clauses "
                  f"({time.time()-t0:.0f}s)", flush=True)

    triggers = [p["trigger_text"] for p in pairs_all]
    # The Layer A pool, to prove the premise "triggers are already cached" rather than assume
    # it. build_client_pool(unit="turn") is what was paid for, and it emits turn.text verbatim.
    pool_texts, _ = build_client_pool(all_turns, unit="turn")

    uniq_clauses = sorted(set(clauses))
    uniq_triggers = sorted(set(triggers))
    uniq_pool = sorted(set(pool_texts))

    print(f"\nChecking the gemini cache (READ-ONLY): {CACHE}", flush=True)
    print(f"  key = sha256({EMBED_MODEL}|{EMBED_DIMS}|text)")
    hit_clause = cached_keys([_key(t) for t in uniq_clauses], CACHE)
    hit_trigger = cached_keys([_key(t) for t in uniq_triggers], CACHE)
    hit_pool = cached_keys([_key(t) for t in uniq_pool], CACHE)

    miss_clauses = len(uniq_clauses) - len(hit_clause)
    miss_triggers = len(uniq_triggers) - len(hit_trigger)
    miss_pool = len(uniq_pool) - len(hit_pool)

    w = 44
    print("\n" + "=" * 74)
    print("STEP 0 -- EMBEDDING SCOPE")
    print("=" * 74)
    print(f"{'transcripts parsed':<{w}} {len(files)}")
    print(f"{'turns parsed':<{w}} {len(all_turns)}")
    print(f"{'CLIENT turns':<{w}} {client_turns}")
    print(f"{'kb_pairs (per-call extract_pairs)':<{w}} {len(pairs_all)}")
    print(f"{'calls contributing >=1 pair':<{w}} {calls_with_pairs} of {len(files)}")
    print("-" * 74)
    print(f"{'response clauses (with duplicates)':<{w}} {len(clauses)}")
    print(f"{'response clauses, DISTINCT text':<{w}} {len(uniq_clauses)}")
    print(f"{'  already cached':<{w}} {len(hit_clause)}")
    print(f"{'  TO FETCH (paid)':<{w}} {miss_clauses}")
    print("-" * 74)
    print(f"{'trigger texts, DISTINCT':<{w}} {len(uniq_triggers)}")
    print(f"{'  already cached':<{w}} {len(hit_trigger)}")
    print(f"{'  TO FETCH (paid)':<{w}} {miss_triggers}")
    print("-" * 74)
    print(f"{'Layer A turn pool, DISTINCT':<{w}} {len(uniq_pool)}")
    print(f"{'  already cached':<{w}} {len(hit_pool)}")
    print(f"{'  TO FETCH (paid)':<{w}} {miss_pool}")
    print("-" * 74)
    total_paid = miss_clauses + miss_triggers + miss_pool
    print(f"{'TOTAL PAID REQUESTS NEEDED':<{w}} {total_paid}")
    print(f"{f'  at ~{REQ_PER_SEC:.0f} req/s (20 workers)':<{w}} "
          f"{total_paid / REQ_PER_SEC / 60:.1f} min")
    print("=" * 74)

    if miss_pool:
        print("\n! The Layer A turn pool is NOT fully cached. The premise 'triggers are")
        print("  cached' comes from that backfill, so a nonzero miss here means the pool")
        print("  changed (the corpus cleanup did change it) -- re-read before spending.")
    if miss_triggers:
        print(f"\n! {miss_triggers} trigger text(s) are uncached. extract_pairs emits whole")
        print("  CLIENT turns, so these should be a subset of the Layer A pool; a nonzero")
        print("  count that is NOT explained by miss_pool means the two disagree.")

    payload = {
        "recordings_dir": a.recordings, "limit": a.limit, "transcripts": len(files),
        "embed_model": EMBED_MODEL, "embed_dims": EMBED_DIMS, "cache": str(CACHE),
        "turns": len(all_turns), "client_turns": client_turns,
        "pairs": len(pairs_all), "calls_with_pairs": calls_with_pairs,
        "response_clauses_total": len(clauses),
        "response_clauses_distinct": len(uniq_clauses),
        "response_clauses_cached": len(hit_clause),
        "response_clauses_to_fetch": miss_clauses,
        "triggers_distinct": len(uniq_triggers),
        "triggers_cached": len(hit_trigger),
        "triggers_to_fetch": miss_triggers,
        "layer_a_pool_distinct": len(uniq_pool),
        "layer_a_pool_cached": len(hit_pool),
        "layer_a_pool_to_fetch": miss_pool,
        "total_paid_requests": total_paid,
        "est_minutes_at_46rps": total_paid / REQ_PER_SEC / 60,
        "elapsed_s": time.time() - t0,
        "per_call": per_call,
    }
    Path(a.out).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nwrote {a.out}  ({time.time()-t0:.0f}s total)")

    if not a.fetch:
        print("\nNOTHING WAS SPENT. Re-run with --fetch once the number above is agreed.")
        return

    if a.limit:
        raise SystemExit("--fetch with --limit would warm only an alphabetical prefix of the "
                         "corpus and leave the arms to abort on the rest. Refusing.")

    # embed_cached (not a private re-implementation) so the vectors land under exactly the key
    # every downstream reader looks them up by, and so a crash resumes instead of restarting.
    from calibration.trial_pool_unit_gemini import embed_cached

    print(f"\n--fetch: embedding {miss_clauses} missing response clause(s) at "
          f"{a.workers} workers...", flush=True)
    mat = embed_cached(uniq_clauses, a.workers)
    print(f"[fetch] done: {mat.shape} ({time.time()-t0:.0f}s total)")

    # Prove it, rather than trust the return value. The gateway has silently returned fewer
    # vectors than inputs before; a re-read of the cache is the check that cannot be fooled
    # by an in-memory dict that was filled from a short response.
    still = len(uniq_clauses) - len(cached_keys([_key(t) for t in uniq_clauses], CACHE))
    print(f"[verify] re-read of the cache: {still} clause(s) still missing")
    if still:
        raise SystemExit(f"ABORT: {still} clause(s) are STILL uncached after --fetch. Do not "
                         f"run the arms -- they would abort mid-run or, worse, spend.")


if __name__ == "__main__":
    main()
