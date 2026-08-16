#!/usr/bin/env python3
"""Scope, then optionally FETCH, the embeddings each Layer B knob setting needs.

Spec: docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md

WHY THIS EXISTS. The `a4` smoke test aborted:

    ABORT: 8 text(s) are not in the gemini cache, e.g. ['So it it was vetted, Neha.']

That abort is `layer_bc_arms.install_embedder_shim` refusing to turn a free measurement into a
paid one, and it is correct. The cache was warmed for PRODUCTION's pair set, and every Knob A
or S setting produces a DIFFERENT one: `a4` admits short Naren replies whose clauses were never
embedded, `a1` admits short triggers, `s1` produces merged trigger strings that have never
existed as a single text. Those are new populations, not new vectors for old texts.

The spec's F1 says measure the backfill BEFORE committing to it, so `--scope` is the default
and `--fetch` is opt-in. Scoping every setting in one pass means the decision is made on one
number instead of being discovered one arm at a time, each costing a smoke test.

*** SEPARATE FILE ON PURPOSE. *** `layer_bc_arms.py` is already ~1,200 lines carrying the
corpus, routing, Layer C, the placebo and the compare. Spending is a different concern with a
different failure mode -- it is the only thing here that costs money -- and it belongs behind
its own flag in its own file where the fetch path can be read in isolation.

WHAT IT DOES NOT DO. It never batches the gateway's `/embeddings`: that endpoint silently
returns FEWER vectors than inputs, intermittently, and hits SHORT text hardest -- which is
precisely the population `a4` adds. Throughput comes from CONCURRENCY via
`trial_pool_unit_gemini.embed_cached`, which cannot reintroduce the collapse. It also fetches
the NATIVE 3072 width and keys the cache on it, so a later `--width 768` run is free.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/backfill_knob_embeddings.py --scope
    ..\\.venv\\Scripts\\python.exe calibration/backfill_knob_embeddings.py --fetch --settings s0/a4
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Every setting the trial can run. `s0/a0` is production and is listed FIRST as a control: it
# should report ~0 missing, and anything else means the cache has drifted from the corpus, which
# would invalidate the already-published arms rather than just this one.
SETTINGS = [("s0", "a0"), ("s0", "a4"), ("s0", "a1"), ("s0", "a3"),
            ("s1", "a0"), ("s1", "a4")]

# Production's own admitted fractions on this corpus, so `a3` is volume-neutral by construction.
A3_TARGET_CLIENT = 0.661
A3_TARGET_NAREN = 0.90


def parse_all(recordings: str):
    from config import load_config
    from preprocessing.transcript_parser import parse_transcript, load_roster

    cfg = load_config()
    files = sorted(Path(recordings).glob("*.txt"))
    if not files:
        raise SystemExit(f"no transcripts in {recordings}/")
    out = []
    for n, path in enumerate(files, 1):
        out.append((n, path, parse_transcript(
            str(path), cfg.joveo_speakers_lower, cfg.naren_name_lower,
            roster=load_roster(str(path)))))
        if n % 100 == 0 or n == len(files):
            print(f"  parsed {n}/{len(files)} calls", flush=True)
    return out


def texts_for(parsed, segment: str, admit: str, floors) -> tuple[list[str], int, int]:
    """Every text one setting will ask the embedder for: triggers AND response clauses.

    BOTH populations, because both are embedded and either can miss. `assign_scenarios` embeds
    `trigger_text` -- and under `s1` a merged move is a string that has never existed before, so
    it is a guaranteed miss even though every one of its component turns is cached. Layer C
    embeds the response clause pool, which is where `a4` adds.

    Returns (distinct texts, n_pairs, n_clauses).
    """
    from v1.layer_b import extract_pairs
    from v2.layer_c import build_clause_pool
    from calibration.layer_b_variants import extract_pairs_variant

    pairs = []
    for n, path, turns in parsed:
        got = (extract_pairs(turns, n) if (segment, admit) == ("s0", "a0")
               else extract_pairs_variant(turns, n, segment, admit, floors))
        for p in got:
            p["call_filename"] = path.name
        pairs.extend(got)
    clauses, _, _, _ = build_clause_pool(pairs)
    texts = sorted(set(clauses) | {p["trigger_text"] for p in pairs})
    return texts, len(pairs), len(clauses)


def missing_from_cache(texts: list[str]) -> list[str]:
    """Which texts have no vector. READ-ONLY -- this function can never spend."""
    from calibration.trial_pool_unit_gemini import CACHE, _key

    conn = sqlite3.connect(f"file:{CACHE.as_posix()}?mode=ro", uri=True)
    have = set()
    try:
        keys = [_key(t) for t in texts]
        for i in range(0, len(keys), 900):
            chunk = keys[i:i + 900]
            q = ",".join("?" * len(chunk))
            for (k,) in conn.execute(f"SELECT k FROM vec WHERE k IN ({q})", chunk):
                have.add(k)
    finally:
        conn.close()
    return [t for t, k in zip(texts, keys) if k not in have]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--scope", action="store_true",
                   help="default. Count what is missing per setting. Zero requests.")
    p.add_argument("--fetch", action="store_true",
                   help="SPENDS. Fetch the missing texts for --settings.")
    p.add_argument("--settings", default="",
                   help="comma-separated 'seg/admit' to fetch, e.g. s0/a4,s0/a1. "
                        "Required with --fetch: there is no 'fetch everything' default, "
                        "because the whole point of scoping first is that the spend is chosen.")
    p.add_argument("--workers", type=int, default=20,
                   help="CONCURRENCY, not batch size. The gateway's /embeddings silently "
                        "returns fewer vectors than inputs when batched.")
    p.add_argument("--max-fetch", type=int, default=40000,
                   help="hard ceiling. Refuses rather than spending past it, so a corpus "
                        "change cannot silently turn a backfill into a much larger one.")
    a = p.parse_args()

    if a.fetch and not a.settings:
        raise SystemExit("--fetch requires --settings. Scope first, then choose.")

    # VALIDATED BEFORE THE PARSE. Every check that can run without the corpus must, or a typo
    # in --settings costs a four-minute spaCy pass before it is rejected.
    wanted = None
    settings = list(SETTINGS)
    if a.settings:
        wanted = {tuple(s.strip().split("/")) for s in a.settings.split(",") if s.strip()}
        unknown = wanted - set(SETTINGS)
        if unknown:
            raise SystemExit(f"unknown setting(s) {sorted(unknown)}; expected from {SETTINGS}")
        # *** ONLY SCOPE WHAT WAS ASKED FOR. *** Scoping ONE setting costs a full spaCy pass
        # over the corpus twice -- the admission predicate on every turn, then the segmenter on
        # every response -- roughly 5 minutes. Looping all six to fetch one would spend 25
        # minutes of wall clock to buy 845 embeddings, and the whole point of
        # `--fetch --settings` is that the spend was already chosen from a scope table.
        settings = [s for s in SETTINGS if s in wanted]

    parsed = parse_all(a.recordings)

    # Derived only when something in scope actually needs it: it is another full spaCy pass.
    floors = None
    if any(adm == "a3" for _, adm in settings):
        from calibration.layer_b_variants import derive_alpha_floors
        floors = derive_alpha_floors([t for _, _, t in parsed],
                                     A3_TARGET_CLIENT, A3_TARGET_NAREN)
        print(f"  a3 corpus-derived floors: {floors}", flush=True)

    print(f"\n{'setting':<10}{'pairs':>8}{'clauses':>10}{'distinct':>10}"
          f"{'cached':>9}{'MISSING':>10}")
    print("-" * 57)
    to_fetch: list[str] = []
    for seg, adm in settings:
        texts, n_pairs, n_clauses = texts_for(parsed, seg, adm, floors)
        miss = missing_from_cache(texts)
        flag = ""
        if (seg, adm) == ("s0", "a0") and miss:
            flag = "  <- !! PRODUCTION SHOULD BE 0. The cache has drifted from the corpus."
        print(f"{seg}/{adm:<7}{n_pairs:>8}{n_clauses:>10}{len(texts):>10}"
              f"{len(texts)-len(miss):>9}{len(miss):>10}{flag}")
        if wanted and (seg, adm) in wanted:
            to_fetch.extend(miss)

    if not a.fetch:
        print("\nMISSING is the number of PAID gateway requests that setting needs.")
        print("Nothing was fetched. Re-run with --fetch --settings <seg/adm,...> to spend.")
        return

    uniq = sorted(set(to_fetch))
    print(f"\n[fetch] {len(uniq)} distinct text(s) for {sorted(wanted)}")
    if len(uniq) > a.max_fetch:
        raise SystemExit(f"REFUSING: {len(uniq)} > --max-fetch {a.max_fetch}. Raise the "
                         f"ceiling deliberately if this is really the intended spend.")
    if not uniq:
        print("nothing to do -- every text is already cached.")
        return

    from calibration.trial_pool_unit_gemini import embed_cached
    mat = embed_cached(uniq, a.workers)
    print(f"[fetch] done: {mat.shape}")

    left = missing_from_cache(uniq)
    if left:
        raise SystemExit(f"!! {len(left)} text(s) STILL missing after the fetch. The gateway "
                         f"returned fewer vectors than inputs -- do not proceed; a partial "
                         f"cache makes an arm abort halfway through instead of at the start.")
    print("verified: every requested text is now cached.")


if __name__ == "__main__":
    main()
