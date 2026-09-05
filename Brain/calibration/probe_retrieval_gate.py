#!/usr/bin/env python3
"""Does trigger-similarity search actually find a COMPARABLE expert moment?

This is the gate for the head-to-head design. That design retrieves Naren's response to the
client trigger nearest a CSM's trigger and asks a judge which response handled the moment
better. Every number it produces is meaningless if the retrieved moment is not the same kind
of moment -- so retrieval is measured, with a bar, before a single judge call is spent.

Run as leave-one-CALL-out over the real kb_pairs pool: each trigger queries every trigger from
a DIFFERENT call. Holding out the whole call, not just the row, is `score_naren_ceiling.hold_out`'s
rule and it matters more here than there -- adjacent turns of one call are near-duplicates, so a
row-level holdout would score "found a same-scenario neighbour" on a moment two turns away and
report a retrieval quality that does not exist.

This measures Naren-querying-Naren: same speaker, same corpus, same register. It is therefore
the OPTIMISTIC bound on the CSM->Naren retrieval the design actually needs. A failure here is
decisive; a pass is necessary, not sufficient.

Two label-grounded metrics, each against the base rate a random neighbour would achieve, because
a rate without its base rate is unreadable:

  clean_top1      for a COACHABLE query, is the retrieved neighbour coachable rather than a
                  sink-filed pair? A sink neighbour hands the judge backchannel as "the expert's
                  response". Base rate = the coachable share of the candidate pool.
  same_scenario   does the neighbour carry the same scenario_key? Noisier -- scenario_key is
                  layer_b's scalar best match, which the sink-rescue investigation documented as
                  unreliable -- so it is reported as corroboration, never as the gate. Its base
                  rate is computed per query from that scenario's own share of the pool.

Absolute cosine is reported but never compared across embedders: `compare_embedders.py`'s
`spread` criterion already made that mistake, measuring a model's cosine SCALE and reading it as
discrimination. The trigger-vs-trigger band has never been measured in this repo at all, which is
the other reason to print it.

Zero Gemma calls. Zero writes -- the connection is opened read-only at the Postgres level.
Embeddings come from the warm disk cache, so a re-run is free.

    python calibration/probe_retrieval_gate.py --run
    python calibration/probe_retrieval_gate.py --load artifacts/retrieval_gate.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np

# Brain/ is this file's parent -- put it on sys.path so the shared packages
# (config, shared, v1, v2, preprocessing) resolve whether this script is run
# directly (python calibration/x.py) or imported (from calibration import x).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR
from config import load_config
from preprocessing import embedder
from shared import storage

# The bar. Pre-registered here rather than chosen after seeing the numbers.
#
# INVENTED, and deliberately weak: retrieval must beat a random neighbour by a margin whose
# 95% bootstrap interval excludes zero. There is no inherited precedent for a retrieval-quality
# floor in this repo, and inventing a demanding one would be picking a number to fit a hope.
# What makes even a weak bar decisive is the direction of the test: this is Naren-vs-Naren, the
# optimistic bound, so failing it fails the cross-corpus case a fortiori.
_LIFT_CI_MUST_EXCLUDE_ZERO = True
_BOOTSTRAP_ITERS = 10_000
_SEED = 20260813


# --------------------------------------------------------------------------------------
# Pure helpers -- no I/O, no torch, no DB, so the logic a silent bug would invalidate is
# testable. Same split shared/cluster_evidence.py and shared/topic_grouping.py already use.
# --------------------------------------------------------------------------------------

def leave_one_call_out_top1(sims: np.ndarray, call_ids: list) -> np.ndarray:
    """Top-1 neighbour for each row, with every row from the query's own call excluded.

    Mutates nothing: masks a copy. Rows whose call is the entire pool return -1.
    """
    masked = sims.astype(np.float32, copy=True)
    np.fill_diagonal(masked, -np.inf)
    by_call: dict = {}
    for i, c in enumerate(call_ids):
        by_call.setdefault(c, []).append(i)
    for idx in by_call.values():
        if len(idx) > 1:
            rows = np.array(idx)
            masked[np.ix_(rows, rows)] = -np.inf
    best = np.argmax(masked, axis=1)
    dead = ~np.isfinite(masked[np.arange(len(call_ids)), best])
    best[dead] = -1
    return best


def candidate_base_rate(flags: np.ndarray, call_ids: list, query_idx: np.ndarray) -> float:
    """Chance rate for `clean_top1`: the coachable share of each query's own candidate pool.

    Computed per query and averaged, not as a single corpus-wide share -- excluding the query's
    call removes a different slice of the pool for every query, and a call is not a random
    sample of scenarios.
    """
    calls = np.asarray(call_ids)
    rates = []
    for i in query_idx:
        keep = calls != calls[i]
        n = int(keep.sum())
        if n:
            rates.append(float(flags[keep].sum()) / n)
    return float(np.mean(rates)) if rates else float("nan")


def same_scenario_base_rate(scen: list[str], call_ids: list, query_idx: np.ndarray) -> float:
    """Chance rate for `same_scenario@1`: per query, that scenario's share of its candidate pool."""
    calls = np.asarray(call_ids)
    keys = np.asarray(scen)
    rates = []
    for i in query_idx:
        keep = calls != calls[i]
        n = int(keep.sum())
        if n:
            rates.append(float((keys[keep] == keys[i]).sum()) / n)
    return float(np.mean(rates)) if rates else float("nan")


def bootstrap_lift(outcome: np.ndarray, base: float, iters: int = _BOOTSTRAP_ITERS,
                   seed: int = _SEED) -> tuple[float, float, float]:
    """Bootstrap over QUERIES for (mean outcome - base). Returns (lift, lo, hi)."""
    rng = np.random.default_rng(seed)
    n = len(outcome)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    draws = np.empty(iters)
    for i in range(iters):
        draws[i] = outcome[rng.integers(0, n, n)].mean()
    return float(outcome.mean() - base), float(np.percentile(draws, 2.5) - base), \
        float(np.percentile(draws, 97.5) - base)


# --------------------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------------------

def _connect_read_only(database_url: str):
    """A connection Postgres itself will refuse to write through.

    Lifted from score_naren_ceiling._connect_read_only -- stronger than a promise in a docstring,
    and it also protects a future edit that accidentally introduces a write.

    close() is wrapped to RESET the session setting first -- see the identical
    comment in ops/serve_ask_naren.py._connect_read_only for why: left in place,
    this leaks through Neon's pooled endpoint (PgBouncer transaction pooling)
    onto whichever unrelated client gets this backend connection next.
    """
    conn = storage.get_connection(database_url)
    conn.execute("SET SESSION default_transaction_read_only = on")
    ro = conn.execute("SELECT current_setting('default_transaction_read_only')").fetchone()[0]
    if ro != "on":
        raise RuntimeError(f"read-only enforcement failed: setting is {ro!r}")
    _real_close = conn.close
    def _close_and_reset():
        try:
            conn.execute("SET SESSION default_transaction_read_only = off")
        except Exception:
            pass
        _real_close()
    conn.close = _close_and_reset
    return conn


def _load_pool(conn) -> list[dict]:
    """Every kb_pair with its trigger text and its scenario's coachability.

    LEFT JOIN, not JOIN: a pair whose scenario_key is null or dangling must still occupy a row in
    the pool, because it is still a candidate the real retrieval would return. Dropping it here
    would quietly measure a cleaner pool than the one the head-to-head will search.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.pair_id, p.call_id, p.turn_index,
                   COALESCE(p.scenario_key, '') AS scenario_key,
                   p.trigger_text, p.response_text,
                   COALESCE(s.is_coachable, FALSE) AS is_coachable,
                   COALESCE(s.cluster_kind, 'unknown') AS cluster_kind
            FROM kb_pairs p
            LEFT JOIN scenarios s ON s.scenario_key = p.scenario_key
            WHERE p.trigger_text IS NOT NULL AND length(trim(p.trigger_text)) > 0
            ORDER BY p.pair_id
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _report(art: dict) -> None:
    p = art["pool"]
    print(f"\npool: {p['pairs']} pairs / {p['calls']} calls / {p['scenarios']} scenarios")
    print(f"      coachable {p['coachable']} ({p['coachable'] / p['pairs']:.1%})   "
          f"cluster_kind: {p['cluster_kind']}")
    print(f"embedding backend: {art['embedding']['backend']}  dims={art['embedding']['dims']}")
    print(f"queries (coachable, with a valid out-of-call neighbour): {art['n_queries']}")

    print("\ntrigger-vs-trigger cosine band of the retrieved top-1 "
          "(never measured in this repo before):")
    b = art["cosine_band"]
    print("      " + "  ".join(f"p{k}={b[str(k)]:.3f}" for k in (10, 25, 50, 75, 90)))

    print("\n--- the gate -------------------------------------------------------------")
    for name, m in art["metrics"].items():
        gate = "  <- THE GATE" if name == "clean_top1" else "  (corroboration only)"
        print(f"\n{name}{gate}")
        print(f"  observed {m['observed']:.3f}   base rate {m['base']:.3f}   "
              f"lift {m['lift']:+.3f}")
        print(f"  95% CI on lift [{m['lo']:+.3f}, {m['hi']:+.3f}]  -> "
              f"{'ABOVE CHANCE' if m['lo'] > 0 else 'NOT above chance'}")

    g = art["metrics"]["clean_top1"]
    passed = g["lo"] > 0
    print("\n" + "=" * 74)
    print(f"VERDICT: retrieval {'PASSES' if passed else 'FAILS'} the pre-registered gate.")
    if passed:
        print("  Necessary, not sufficient. This is Naren-querying-Naren, the optimistic")
        print("  bound; the CSM->Naren direction is cross-corpus and can only be worse.")
        print(f"  Half of retrieved neighbours are still {'junk' if g['observed'] < 0.75 else 'clean'} "
              f"at {g['observed']:.1%} clean.")
    else:
        print("  Trigger similarity cannot find a comparable expert moment even within one")
        print("  speaker's own corpus. The head-to-head rests on this step, so it is dead")
        print("  here -- before any judge call was spent.")
    print("=" * 74)

    if art.get("samples"):
        print("\n--- read the samples (10 random coachable queries) -----------------------")
        for s in art["samples"]:
            flag = "CLEAN" if s["neighbour_coachable"] else "JUNK "
            print(f"\n[{flag}] cos={s['cos']:.3f}  same_scenario={s['same_scenario']}")
            print(f"  QUERY     ({s['query_scenario']}): {s['query_trigger'][:160]}")
            print(f"  NEIGHBOUR ({s['neighbour_scenario']}): {s['neighbour_trigger'][:160]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true",
                    help="query the DB and embed; default is a no-op so a bare run costs nothing")
    ap.add_argument("--load", help="re-report a persisted artifact, zero cost")
    ap.add_argument("--samples", type=int, default=10)
    ap.add_argument("--seed", type=int, default=_SEED)
    ap.add_argument("--out", default=str(ARTIFACTS_DIR / "retrieval_gate.json"))
    args = ap.parse_args()

    if args.load:
        _report(json.loads(_Path(args.load).read_text(encoding="utf-8-sig")))
        return 0
    if not args.run:
        ap.error("pass --run to spend the query, or --load PATH to re-report")

    config = load_config()
    conn = _connect_read_only(config.database_url)
    try:
        rows = _load_pool(conn)
    finally:
        conn.close()
    if not rows:
        print("ERROR: kb_pairs is empty.")
        return 1

    triggers = [r["trigger_text"] for r in rows]
    calls = [r["call_id"] for r in rows]
    scen = [r["scenario_key"] for r in rows]
    coach = np.array([bool(r["is_coachable"]) for r in rows])

    print(f"embedding {len(triggers)} triggers (warm cache -> free)...")
    # embed_query, matching how CLIENT triggers are embedded everywhere else in this pipeline.
    # The cache is keyed on the prefix, so embed_document here would silently build a DIFFERENT
    # vector population and compare it against nothing that exists elsewhere.
    mat = embedder.embed_query_matrix(triggers)
    mat = np.asarray(mat, dtype=np.float32)
    mat /= np.maximum(np.linalg.norm(mat, axis=1, keepdims=True), 1e-12)

    print("computing leave-one-call-out top-1...")
    sims = mat @ mat.T
    top1 = leave_one_call_out_top1(sims, calls)

    valid = top1 >= 0
    qidx = np.where(coach & valid)[0]
    if len(qidx) == 0:
        print("ERROR: no coachable query has an out-of-call neighbour.")
        return 1

    nb = top1[qidx]
    clean = coach[nb].astype(float)
    same = np.array([scen[i] == scen[j] and scen[i] != "" for i, j in zip(qidx, nb)], dtype=float)
    cos = sims[qidx, nb]

    base_clean = candidate_base_rate(coach.astype(float), calls, qidx)
    base_same = same_scenario_base_rate(scen, calls, qidx)

    metrics = {}
    for name, outcome, base in (("clean_top1", clean, base_clean),
                                ("same_scenario@1", same, base_same)):
        lift, lo, hi = bootstrap_lift(outcome, base, seed=args.seed)
        metrics[name] = {"observed": float(outcome.mean()), "base": base,
                         "lift": lift, "lo": lo, "hi": hi}

    rng = np.random.default_rng(args.seed)
    pick = rng.choice(len(qidx), size=min(args.samples, len(qidx)), replace=False)
    samples = [{
        "cos": float(cos[k]),
        "neighbour_coachable": bool(clean[k]),
        "same_scenario": bool(same[k]),
        "query_scenario": scen[qidx[k]],
        "neighbour_scenario": scen[nb[k]],
        "query_trigger": triggers[qidx[k]],
        "neighbour_trigger": triggers[nb[k]],
    } for k in pick]

    art = {
        "pool": {
            "pairs": len(rows), "calls": len(set(calls)),
            "scenarios": len({s for s in scen if s}),
            "coachable": int(coach.sum()),
            "cluster_kind": dict(Counter(r["cluster_kind"] for r in rows)),
        },
        # Recorded so nobody later compares this against a run in a different vector space.
        # gemma-4-31b-it -> gemini-3.5-flash-lite already confounds every historical figure here.
        "embedding": {"backend": "local_bge", "model": "BAAI/bge-base-en-v1.5",
                      "dims": int(mat.shape[1]), "fn": "embed_query_matrix"},
        "n_queries": int(len(qidx)),
        "cosine_band": {str(k): float(np.percentile(cos, k)) for k in (10, 25, 50, 75, 90)},
        "metrics": metrics,
        "samples": samples,
    }

    out = _Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(art, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    _report(art)
    return 0


if __name__ == "__main__":
    sys.exit(main())
