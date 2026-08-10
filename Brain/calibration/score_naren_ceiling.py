#!/usr/bin/env python3
"""Establish the Layer D CEILING: score Naren's own responses against his own rubrics.

Run from Brain/:
    python calibration/score_naren_ceiling.py                 # DRY RUN -- zero Gemma calls
    python calibration/score_naren_ceiling.py --run           # scores (~95 Gemma calls)
    python calibration/score_naren_ceiling.py --load artifacts/naren_ceiling.json

Design: docs/superpowers/specs/2026-08-11-naren-ceiling-measurement-design.md

WHY THIS EXISTS

Layer D's milestone hit rate for the one measured CSM is 3.1% full hits / weighted 0.074,
and three consecutive fixes each moved it slightly without changing the regime. Nobody has
ever measured what a GOOD score looks like, so 3.1% is uninterpretable: it is equally
consistent with a real coaching gap and with a rubric or scorer that cannot recognise good
work at all. This scores the corpus the rubrics were DERIVED from, through the same
score_milestones_batch, against the same rubrics.

THE TWO CIRCULARITIES THIS CLOSES

Leak 1 -- the benchmark is the answer key. get_benchmark_reference picks the 2 most
on-topic responses from every response filed under the scenario and pastes them into the
prompt as reference. If the response under test is one of them, the grader is shown the
answer and asked whether the answer matches it. Closed by a CALL-level holdout.

Leak 2 -- the criteria were written FROM the responses. Layer C clusters Naren's clauses
and describes the cluster, and one milestone has support_calls=135 of 156 calls, so a
random primary-label response probably helped write the criterion it is graded against.
_finish_rubric stores only the COUNT, never which calls, so it cannot be subtracted.
Closed by exploiting the fact that Layer C's clause pool selects on the SCALAR
scenario_key only (storage.get_naren_responses_for_scenario) -- so a response filed under
a scenario as a SECONDARY label never entered that scenario's pool.

Secondary label alone is not enough: it holds out the response but not the call. Measured
2026-08-11, implementation_timeline_feasibility has 115 calls carrying a secondary pair but
only 60 that contributed no primary pair, so a plain secondary stratum is roughly
half-leaked at call level. Hence arm A3 requires BOTH.

THE ARMS

    A1  primary label          -> own scenario's rubric        leaked upper bound
    A3  secondary label AND
        call has zero primary
        pairs for the scenario -> that scenario's rubric       THE HEADLINE
    B   same texts as A1       -> an UNRELATED scenario        scorer specificity

B is not optional. If Naren scores 80% and the grader would also pass an unrelated rubric,
the 80% measures generosity, not the rubric. Step 3 runs on gemini-3.1-flash-lite,
downgraded from gemma-4-31b-it for TPM reasons, and its specificity has never been measured.

ZERO DB WRITES, ENFORCED RATHER THAN PROMISED
  * SET SESSION default_transaction_read_only = on, so a write fails at Postgres.
  * ego_trap.gap_output is never imported -- every Layer D write path is reached through
    it, so no write function is in scope and no csms row is created for Naren.
  * shared.checkpoint is never imported -- checkpoints.db cannot be touched, so this
    cannot interfere with a resumed Layer D run.
  * --dry-run is the DEFAULT and makes zero Gemma calls.
"""
from __future__ import annotations

import argparse
import json
import random
import sys as _sys
from collections import Counter
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import numpy as np

from calibration import ARTIFACTS_DIR, BRAIN_DIR
from config import load_config
from ego_trap import milestone_scoring
from shared import storage
from shared.gemma import GemmaError
from shared.tuning import get_tuning

# DELIBERATELY NOT IMPORTED: ego_trap.gap_output, shared.checkpoint. See module docstring.
#
# preprocessing.embedder, shared.scenario_vectors and ego_trap.rubric_lookup are imported
# LAZILY inside the functions that need them, because each pulls in torch at module import.
# Keeping them out of the module body is what lets tests/test_naren_ceiling.py import the
# pure helpers below without torch -- which matters on this 16GB box, where a torch import
# can fail outright with [WinError 1455].

_DEFAULT_BASELINE = "arm3_run1_20260810"
_DEFAULT_SEED = 20260811
_DEFAULT_PER_SCENARIO = 8
_BENCHMARK_EXAMPLES = 2

# Matches ego_trap/pipeline.py::_GEMMA_BATCH_SIZE. Request packing, not a threshold, so a
# module constant rather than a tuning.yaml key -- same precedent as
# v2/layer_c._DESCRIBE_BATCH_SIZE.
_BATCH_SIZE = 12

# Pre-registered in the design spec BEFORE any data was seen, so they cannot be moved
# afterwards. W is (hits + 0.5*partial)/attempts, the definition gap_output.
# milestone_miss_rate and measure_scoring_noise.py already use.
_T_WORKS = 0.50           # W(A3) >= this  -> rubrics and scorer work
_T_BROKEN = 0.20          # W(A3) <  this  -> rubric or scorer fundamentally broken
_T_INSTRUMENT = 0.5       # W(B) >= this * W(A3) -> instrument invalid, discard everything
_MIN_ATTEMPTS_TO_INDICT = 6

_ARMS = ("A1", "A3", "B")


# --------------------------------------------------------------------------------------
# Pure helpers. No I/O, no torch, no DB -- all of the sampling and holdout logic that a
# silent bug would render the overnight run meaningless lives here so it can be tested.
# --------------------------------------------------------------------------------------

def weighted(hits: int, partial: int, attempts: int) -> float:
    return (hits + 0.5 * partial) / attempts if attempts else 0.0


def a3_eligible(secondary_rows: list[dict], primary_call_ids: set) -> list[dict]:
    """Secondary-label rows whose CALL contributed no primary pair to this scenario.

    The stricter half of leak 2. A row passes only if nothing from its call entered the
    scenario's Layer C clause pool -- not merely the row itself. Measured on real data, the
    difference is large: dropping this filter leaves the stratum roughly half-leaked at call
    level on every large scenario.
    """
    return [r for r in secondary_rows if r["call_id"] not in primary_call_ids]


def hold_out(pool: list[dict], call_filename: str) -> list[dict]:
    """Every row from the response-under-test's call, gone. Closes leak 1.

    Filters on the CALL, not the pair_id: two responses from the same call to the same
    scenario are near-duplicates, so excluding only the row under test would leave its
    sibling in the benchmark and hand the grader the answer anyway.
    """
    return [r for r in pool if r["call_filename"] != call_filename]


def pick_benchmark(ranked_pool: list[dict], call_filename: str,
                   limit: int = _BENCHMARK_EXAMPLES) -> list[dict]:
    """Top-`limit` most on-topic responses, after holding out the call under test."""
    return hold_out(ranked_pool, call_filename)[:limit]


def take_sample(pool: list[dict], n: int, rng: random.Random) -> list[dict]:
    """Up to n rows, seeded-random.

    NOT the n most scenario-similar: ranking by similarity selects the most prototypical
    responses and would inflate the ceiling. Random is the honest estimate.
    """
    if len(pool) <= n:
        return list(pool)
    return rng.sample(pool, n)


def derange(keys: list[str], sim: np.ndarray, threshold: float,
            rng: random.Random, max_tries: int = 5000) -> tuple[dict[str, str] | None, str]:
    """Pair every scenario with an UNRELATED one, for arm B.

    A derangement (permutation with no fixed point) is preferred over independent random
    picks so each rubric receives about the same number of attempts in B as in A1, keeping
    the comparison symmetric. Any pairing whose scenario-vector cosine is >= threshold is
    rejected: threshold is layer_a.merge_cosine_threshold, an already-calibrated knob, so
    this adds no tuning.yaml key -- every knob in that file must be a property of the data.

    Falls back to per-scenario random choice (valid partners, but not a permutation) if no
    derangement is found, and reports which happened rather than hiding it.
    """
    n = len(keys)
    order = list(range(n))
    for _ in range(max_tries):
        shuffled = order[:]
        rng.shuffle(shuffled)
        if all(shuffled[i] != i and sim[i][shuffled[i]] < threshold for i in range(n)):
            return {keys[i]: keys[shuffled[i]] for i in range(n)}, "derangement"
    mapping = {}
    for i in range(n):
        cands = [j for j in order if j != i and sim[i][j] < threshold]
        if not cands:
            return None, f"no_valid_partner_for_{keys[i]}"
        mapping[keys[i]] = keys[rng.choice(cands)]
    return mapping, "greedy_not_a_permutation"


def aggregate(records: list[dict]) -> dict[tuple, dict]:
    """Per-(rubric_id, milestone_id) counters, the shape milestone_performance stores.

    Rebuilt here rather than written to the DB -- this harness never writes.
    """
    out: dict[tuple, dict] = {}
    for r in records:
        key = (r["rubric_id"], r["milestone_id"])
        c = out.setdefault(key, {"attempts": 0, "hits": 0, "partial": 0,
                                 "scenario_key": r["scenario_key"]})
        c["attempts"] += 1
        if r["verdict"] == "full_hit":
            c["hits"] += 1
        elif r["verdict"] == "partial_hit":
            c["partial"] += 1
    return out


def arm_totals(records: list[dict]) -> dict:
    v = Counter(r["verdict"] for r in records)
    attempts = len(records)
    return {"attempts": attempts, "hits": v["full_hit"], "partial": v["partial_hit"],
            "miss": v["miss"], "W": weighted(v["full_hit"], v["partial_hit"], attempts)}


def unhittable(counters: dict[tuple, dict], min_attempts: int = _MIN_ATTEMPTS_TO_INDICT
               ) -> list[tuple]:
    """Milestones with zero full AND zero partial hits at >= min_attempts.

    Zero PARTIALS is required, and the reason is semantic rather than statistical: a
    milestone scoring partials is being approached, so the criterion is reachable and the
    claim "nobody can satisfy this" is not available.
    """
    return sorted(
        (k for k, c in counters.items()
         if c["attempts"] >= min_attempts and c["hits"] == 0 and c["partial"] == 0),
        key=lambda k: -counters[k]["attempts"],
    )


# --------------------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------------------

def _connect_read_only(database_url: str):
    """A connection Postgres itself will refuse to write through.

    Stronger than a code-review promise: this also protects against a FUTURE edit
    accidentally introducing a write, which review does not.
    """
    conn = storage.get_connection(database_url)
    conn.execute("SET SESSION default_transaction_read_only = on")
    ro = conn.execute("SELECT current_setting('default_transaction_read_only')").fetchone()[0]
    if ro != "on":
        raise RuntimeError(f"read-only enforcement failed: setting is {ro!r}")
    return conn


def _scope(conn, baseline_schema: str) -> list[str]:
    """The scenarios the CSM was actually scored on, read from the SNAPSHOT.

    Never from public: a Layer D run in progress leaves public partial, and a partial run
    sums exactly like a complete one. Reading public here is what first understated this
    scope as 27 scenarios when the real figure is 49.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                    (baseline_schema,))
        if cur.fetchone() is None:
            raise SystemExit(f"ERROR: baseline schema {baseline_schema!r} does not exist.")
        cur.execute(f"""
            SELECT DISTINCT r.scenario_key
            FROM {baseline_schema}.milestone_performance mp
            JOIN rubrics r ON r.rubric_id = mp.rubric_id
            ORDER BY 1
        """)
        return [r[0] for r in cur.fetchall()]


def _pools(conn, scenario_key: str) -> tuple[list[dict], list[dict], set]:
    """(primary rows, secondary rows, primary call_ids) for one scenario."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.pair_id, p.response_text, c.filename, p.call_id
            FROM kb_pairs p JOIN calls c ON c.call_id = p.call_id
            WHERE p.scenario_key = %(k)s
            ORDER BY p.pair_id
        """, {"k": scenario_key})
        primary = [{"pair_id": r[0], "response_text": r[1], "call_filename": r[2],
                    "call_id": r[3]} for r in cur.fetchall()]
        cur.execute("""
            SELECT p.pair_id, p.response_text, c.filename, p.call_id
            FROM kb_pairs p JOIN calls c ON c.call_id = p.call_id
            WHERE %(k)s = ANY(p.scenario_keys)
              AND p.scenario_key IS DISTINCT FROM %(k)s
            ORDER BY p.pair_id
        """, {"k": scenario_key})
        secondary = [{"pair_id": r[0], "response_text": r[1], "call_filename": r[2],
                      "call_id": r[3]} for r in cur.fetchall()]
    return primary, secondary, {r["call_id"] for r in primary}


def _cache_coverage(texts: list[str]) -> tuple[int, int]:
    """(cached, distinct) for document-prefix embeddings, WITHOUT loading the model.

    _embed_matrix reaches _get_model() only inside `if missing:`, so 100% coverage means
    the 400MB sentence-transformer never loads and nothing is encoded. Aborting on
    anything less is what stops this harness silently starting a GPU pass.

    This is model-load-free, NOT torch-free: _MODEL_NAME lives only in embedder, and
    duplicating the literal here would let the two drift, which is a worse failure than
    importing torch a few seconds early.
    """
    from preprocessing.embedder import _MODEL_NAME
    from shared import embed_cache
    cfg = get_tuning().embedding
    uniq = list(dict.fromkeys(texts))
    if not cfg.cache_enabled:
        return 0, len(uniq)
    cache = embed_cache.get_cache(BRAIN_DIR / cfg.cache_path)
    return len(cache.get_many(_MODEL_NAME, "", uniq)), len(uniq)


def _ranked_benchmark_pool(conn, scenario_key: str, info: dict) -> list[dict]:
    """Every benchmark candidate for one scenario, most on-topic first.

    This is the same computation rubric_lookup.rank_benchmark_responses performs
    internally -- embed_document over the pool, cosine against
    scenario_vectors.scenario_vec -- but hoisted to run ONCE per scenario instead of once
    per held-out call. Calling that function per holdout would re-embed a ~400-row pool up
    to 8 times per scenario per arm. Equivalence is CHECKED, not asserted: see
    _verify_ranking_equivalence.
    """
    from preprocessing import embedder
    from shared import relative_match
    from shared.scenario_vectors import scenario_vec

    rows = storage.get_responses_for_scenario_multilabel(conn, scenario_key)
    if not rows:
        return []
    sims = relative_match.cosine_sims(
        embedder.embed_document_matrix([r["response_text"] for r in rows]),
        np.asarray([scenario_vec(info)]),
    )[:, 0]
    ranked = [dict(r, scenario_similarity=float(sims[i])) for i, r in enumerate(rows)]
    ranked.sort(key=lambda r: -r["scenario_similarity"])
    return ranked


def _verify_ranking_equivalence(conn, samples: list[tuple], scen_info: dict,
                                ranked_pools: dict) -> list[str]:
    """Prove the hoisted ranking picks the same benchmark text as production's function.

    The precedent for bothering: dry_run_ego_trap.py's chosen-vs-discarded band silently
    read "no data" because it called rank_benchmark_responses in a way that hit its own
    `<= limit` short-circuit. A harness that reimplements a production computation for
    speed must demonstrate it, or the whole overnight run rests on an assumption.
    """
    from ego_trap import rubric_lookup
    problems = []
    for scenario_key, call_filename in samples:
        mine = [r["response_text"] for r in
                pick_benchmark(ranked_pools[scenario_key], call_filename)]
        raw = hold_out(storage.get_responses_for_scenario_multilabel(conn, scenario_key),
                       call_filename)
        theirs = [r["response_text"] for r in rubric_lookup.rank_benchmark_responses(
            raw, scen_info[scenario_key], _BENCHMARK_EXAMPLES)]
        if len(raw) <= _BENCHMARK_EXAMPLES:
            # rank_benchmark_responses short-circuits here and returns rows UNRANKED, so
            # only the set is comparable, not the order.
            if set(mine) != set(theirs):
                problems.append(f"{scenario_key}/{call_filename}: set mismatch on tiny pool")
        elif mine != theirs:
            problems.append(f"{scenario_key}/{call_filename}: ranked text mismatch")
    return problems


def _build_items(conn, keys: list[str], per_scenario: int, seed: int,
                 rng_pools: dict, ranked_pools: dict, scen_info: dict,
                 rubrics: dict, partner: dict) -> tuple[dict, dict]:
    """One item per (response, scenario) to be scored, per arm, plus the sampling report.

    The unit is (response, scenario), NOT response: sampling iterates scenarios and draws
    from each scenario's own pool, so a pair carrying two secondary labels legitimately
    appears twice in A3 -- once per rubric it is tested against. The rubric is what is
    under test, not the response.
    """
    rng = random.Random(seed)
    items: dict[str, list] = {a: [] for a in _ARMS}
    plan = {}
    for key in keys:
        primary, secondary, primary_calls = rng_pools[key]
        a3_pool = a3_eligible(secondary, primary_calls)
        a1_sample = take_sample(primary, per_scenario, rng)
        a3_sample = take_sample(a3_pool, per_scenario, rng)
        plan[key] = {
            "primary_available": len(primary), "secondary_available": len(secondary),
            "a3_available": len(a3_pool), "a1_n": len(a1_sample), "a3_n": len(a3_sample),
            "partner": partner.get(key),
            "milestones": len(rubrics[key].get("milestones") or []),
        }
        for row in a1_sample:
            items["A1"].append(_item(row, key, key, rubrics, ranked_pools))
            pkey = partner.get(key)
            if pkey:
                items["B"].append(_item(row, key, pkey, rubrics, ranked_pools))
        for row in a3_sample:
            items["A3"].append(_item(row, key, key, rubrics, ranked_pools))
    return items, plan


def _item(row: dict, source_key: str, rubric_key: str, rubrics: dict,
          ranked_pools: dict) -> dict:
    """One scoreable exchange.

    The benchmark always comes from the SCORED rubric's scenario, never the response's own.
    Production pairs a rubric with its own benchmark, so in arm B the benchmark must travel
    with the rubric -- otherwise the arm differs from A1 in two ways instead of one.
    """
    bench = pick_benchmark(ranked_pools.get(rubric_key, []), row["call_filename"])
    return {
        "pair_id": row["pair_id"], "source_scenario": source_key,
        "scenario_key": rubric_key, "call_filename": row["call_filename"],
        "rubric": rubrics[rubric_key], "rubric_id": rubrics[rubric_key]["rubric_id"],
        "csm_response_text": row["response_text"],
        "benchmark_response": "\n\n".join(r["response_text"] for r in bench),
        "benchmark_n": len(bench),
    }


def _score_arm(arm: str, items: list[dict], config, skip_uncoachable: bool,
               batch_size: int) -> tuple[list[dict], Counter]:
    """Score one arm through the UNCHANGED production scorer.

    Arms are batched SEPARATELY on purpose. Mixing them would put the same response text in
    one prompt twice under two different milestone lists, which is an invitation for the
    model to notice and cross-contaminate the very contrast arm B exists to measure.
    """
    records: list[dict] = []
    models: Counter = Counter()
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    print(f"\n[{arm}] scoring {len(items)} item(s) in {len(batches)} batch(es) of "
          f"up to {batch_size}...")
    for b_idx, batch in enumerate(batches, start=1):
        try:
            out = milestone_scoring.score_milestones_batch(
                [{"rubric": it["rubric"], "csm_response_text": it["csm_response_text"],
                  "benchmark_response": it["benchmark_response"]} for it in batch],
                config, skip_uncoachable=skip_uncoachable,
            )
        except GemmaError as e:
            print(f"  ! [{arm}] batch {b_idx}/{len(batches)} FAILED: {e} — "
                  f"{len(batch)} item(s) left unscored (NOT retried, to protect quota)")
            continue
        for it, results in zip(batch, out):
            for m in results:
                models[m.get("scored_by")] += 1
                records.append({
                    "arm": arm, "pair_id": it["pair_id"],
                    "scenario_key": it["scenario_key"],
                    "source_scenario": it["source_scenario"],
                    "rubric_id": it["rubric_id"], "milestone_id": m["milestone_id"],
                    "milestone_description": m["milestone_description"],
                    "verdict": m["verdict"], "confidence": m["confidence"],
                    "reason": m["reason"], "quote": m["quote"],
                    "gap_to_ideal": m["gap_to_ideal"], "scored_by": m.get("scored_by"),
                    "evidence": m.get("evidence", {}),
                })
        print(f"  [{arm}] batch {b_idx}/{len(batches)} scored ({len(batch)} item(s))")
    return records, models


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------

def _baseline_totals(conn, schema: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(f"""SELECT COALESCE(SUM(attempts),0), COALESCE(SUM(hits),0),
                               COALESCE(SUM(partial_hits),0)
                        FROM {schema}.milestone_performance""")
        a, h, p = (int(x) for x in cur.fetchone())
    return {"attempts": a, "hits": h, "partial": p, "W": weighted(h, p, a)}


def _line(label: str, t: dict, items: int | str = "-") -> str:
    a = t["attempts"]
    if not a:
        return f"  {label:<34} no data"
    return (f"  {label:<34} {a:>5} att | {t['hits']:>4} hit ({t['hits']/a:>5.1%}) | "
            f"{t['partial']:>4} part ({t['partial']/a:>5.1%}) | W {t['W']:.3f} | "
            f"items {items}")


def _report(payload: dict) -> None:
    arms = payload["arms"]
    base = payload["baseline"]
    print("\n" + "=" * 92)
    print("LAYER D CEILING — Naren scored against his own rubrics")
    print("=" * 92)
    print(_line("A1  primary label (LEAKED)", arms["A1"]["totals"], arms["A1"]["items"]))
    print(_line("A3  call-level holdout (CLEAN)", arms["A3"]["totals"], arms["A3"]["items"]))
    print(_line("B   unrelated rubric (CONTROL)", arms["B"]["totals"], arms["B"]["items"]))
    print(_line(f"CSM {payload['baseline_schema']}", base))

    w_a1, w_a3, w_b = arms["A1"]["totals"]["W"], arms["A3"]["totals"]["W"], arms["B"]["totals"]["W"]
    print("\n" + "-" * 92)
    print("PRE-REGISTERED VERDICTS (fixed in the design spec before any data was seen)")
    print("-" * 92)

    invalid = w_a3 > 0 and w_b >= _T_INSTRUMENT * w_a3
    print(f"  GATE  W(B) >= {_T_INSTRUMENT} x W(A3)?   "
          f"{w_b:.3f} vs {_T_INSTRUMENT * w_a3:.3f}   -> "
          f"{'*** INSTRUMENT INVALID ***' if invalid else 'passes, arms are citable'}")
    if invalid:
        print("        The scorer does not discriminate between a matched and an unrelated")
        print("        rubric. NO number below may be cited. Fix the scorer or the prompt.")

    if w_a3 >= _T_WORKS:
        verdict = f"W(A3) {w_a3:.3f} >= {_T_WORKS} -> RUBRICS AND SCORER WORK; the CSM gap is real"
    elif w_a3 < _T_BROKEN:
        verdict = f"W(A3) {w_a3:.3f} < {_T_BROKEN} -> RUBRIC OR SCORER FUNDAMENTALLY BROKEN"
    else:
        verdict = (f"W(A3) {w_a3:.3f} in [{_T_BROKEN}, {_T_WORKS}) -> INCONCLUSIVE; "
                   f"do NOT tune, read samples")
    print(f"  MAIN  {verdict}")
    leak = w_a1 - w_a3
    print(f"  LEAK  W(A1) - W(A3) = {leak:+.3f}   -> "
          f"{'RUBRICS OVERFIT to their own source calls' if leak >= 0.20 else 'no large derivation leak'}")

    print("\n  Reference: the CSM baseline is W "
          f"{base['W']:.3f} / {base['hits']}/{base['attempts']} full hits "
          f"({base['hits']/max(base['attempts'],1):.1%}).")

    print("\n" + "-" * 92)
    print("PROVENANCE (an arm scored by a different model is not comparable)")
    print("-" * 92)
    for arm in _ARMS:
        a = arms[arm]
        print(f"  {arm:<3} scored_by {dict(a['models'])} | unscored items "
              f"{a['unscored']} | empty benchmarks {a['empty_benchmarks']} | "
              f"distinct pair_ids {a['distinct_pairs']}")

    for arm in ("A3", "A1"):
        counters = {tuple(k.split("::")): v for k, v in arms[arm]["counters"].items()}
        bad = unhittable(counters)
        print("\n" + "-" * 92)
        print(f"[{arm}] MILESTONES EVEN THE AUTHOR CANNOT SATISFY "
              f"(0 full AND 0 partial at >= {_MIN_ATTEMPTS_TO_INDICT} attempts): {len(bad)}")
        print("-" * 92)
        for k in bad[:20]:
            c = counters[k]
            print(f"  {c['attempts']:>3} att  0 hit  0 part   {c['scenario_key']} :: {k[1]}")

    print("\n" + "=" * 92)
    print("NOTE: a high A3 licenses \"the rubrics are satisfiable\", NOT \"the whole")
    print("3.1%-to-ceiling distance is CSM skill\". Step 0 is bypassed here and Naren's")
    print("response text is _is_substantive-filtered while the CSM window is not — both")
    print("favour Naren. See the design spec's confounds section.")
    print("=" * 92)


def _print_samples(payload: dict, n: int) -> None:
    """Real verdicts, read before any aggregate is believed.

    Every large finding in this pipeline's history came from reading samples, never from a
    summary statistic. Arm B's highest-confidence PASSES matter most: if the control scores
    anything, its reasons say why.
    """
    for arm in _ARMS:
        recs = payload["arms"][arm]["records"]
        wins = [r for r in recs if r["verdict"] in ("full_hit", "partial_hit")]
        print("\n" + "=" * 92)
        print(f"[{arm}] SAMPLE VERDICTS — {len(wins)} non-miss of {len(recs)}")
        print("=" * 92)
        for r in wins[:n]:
            print(f"\n  {r['verdict'].upper()} ({r['confidence']}) "
                  f"{r['scenario_key']} :: {r['milestone_id']}  pair {r['pair_id']}")
            print(f"    criterion : {r['milestone_description'][:170]}")
            print(f"    reason    : {r['reason'][:300]}")
            if r["quote"]:
                print(f"    quote     : {r['quote'][:200]}")
        if not wins:
            print("  (no non-miss verdicts in this arm)")


# --------------------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", action="store_true",
                    help="actually score (spends Gemma calls). Default is a dry run.")
    ap.add_argument("--load", help="re-report a persisted artifact, zero cost")
    ap.add_argument("--baseline", default=_DEFAULT_BASELINE)
    ap.add_argument("--per-scenario", type=int, default=_DEFAULT_PER_SCENARIO)
    ap.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    ap.add_argument("--batch-size", type=int, default=_BATCH_SIZE)
    ap.add_argument("--samples", type=int, default=12,
                    help="non-miss verdicts to print per arm")
    ap.add_argument("--out", default=str(ARTIFACTS_DIR / "naren_ceiling.json"))
    args = ap.parse_args()

    if args.load:
        payload = json.loads(_Path(args.load).read_text(encoding="utf-8"))
        _report(payload)
        _print_samples(payload, args.samples)
        return

    cfg = load_config()
    tuning = get_tuning().layer_d
    conn = _connect_read_only(cfg.database_url)
    try:
        keys = _scope(conn, args.baseline)
        scen_info = {s["scenario_key"]: s for s in storage.get_scenarios(conn)}
        rubrics, missing = {}, []
        for k in keys:
            r = storage.get_rubric_for_scenario(conn, k)
            if r is None or not (r.get("milestones") or []):
                missing.append(k)
            else:
                rubrics[k] = r
        keys = [k for k in keys if k in rubrics]
        print(f"[scope] {len(keys)} scenario(s) from {args.baseline}"
              f"{f' ({len(missing)} dropped: no rubric/milestones)' if missing else ''}")

        pools = {k: _pools(conn, k) for k in keys}

        # --- pre-flight: refuse to encode anything -----------------------------------
        all_texts = []
        for k in keys:
            all_texts += [r["response_text"] for r in
                          storage.get_responses_for_scenario_multilabel(conn, k)]
            all_texts.append(_scenario_text(scen_info[k]))
        cached, distinct = _cache_coverage(all_texts)
        pct = cached / distinct if distinct else 1.0
        print(f"[preflight] embed cache {cached}/{distinct} ({pct:.1%}) of distinct texts")
        if cached < distinct:
            raise SystemExit(
                f"ABORT: {distinct - cached} text(s) are not cached, so running would load "
                f"the sentence-transformer and encode on this machine. That is exactly what "
                f"the [WinError 1455] guard exists to prevent. Warm the cache deliberately "
                f"first, or re-run when nothing else is holding memory."
            )

        ranked_pools = {k: _ranked_benchmark_pool(conn, k, scen_info[k]) for k in keys}

        # --- arm B pairings ----------------------------------------------------------
        sim = _scenario_sim_matrix(keys, scen_info)
        threshold = get_tuning().layer_a.merge_cosine_threshold
        partner, method = derange(keys, sim, threshold, random.Random(args.seed))
        if partner is None:
            raise SystemExit(f"ABORT: could not build arm B pairings ({method}).")
        print(f"[arm B] pairing method: {method} (cosine < {threshold})")

        items, plan = _build_items(conn, keys, args.per_scenario, args.seed,
                                   pools, ranked_pools, scen_info, rubrics, partner)

        # --- dry run ------------------------------------------------------------------
        print(f"\n{'scenario':<46} {'ms':>3} {'prim':>5} {'sec':>5} {'a3':>5} "
              f"{'A1n':>4} {'A3n':>4}  partner")
        print("-" * 118)
        for k in keys:
            p = plan[k]
            print(f"{k:<46} {p['milestones']:>3} {p['primary_available']:>5} "
                  f"{p['secondary_available']:>5} {p['a3_available']:>5} "
                  f"{p['a1_n']:>4} {p['a3_n']:>4}  {p['partner']}")

        est = sum(-(-len(items[a]) // args.batch_size) for a in _ARMS)
        print(f"\n[plan] items  " + "  ".join(f"{a}={len(items[a])}" for a in _ARMS))
        print(f"[plan] Gemma calls ~{est} "
              f"({', '.join(f'{a}={-(-len(items[a]) // args.batch_size)}' for a in _ARMS)})")
        print(f"[plan] empty benchmarks  " +
              "  ".join(f"{a}={sum(1 for i in items[a] if not i['benchmark_response'])}"
                        for a in _ARMS))
        print(f"[plan] skip_uncoachable_milestones = {tuning.skip_uncoachable_milestones}")

        checks = _verify_ranking_equivalence(
            conn, [(i["scenario_key"], i["call_filename"]) for i in items["A1"][:8]],
            scen_info, ranked_pools)
        print(f"[check] hoisted-ranking equivalence vs rank_benchmark_responses: "
              f"{'OK on 8 samples' if not checks else 'MISMATCH ' + str(checks)}")
        if checks:
            raise SystemExit("ABORT: the hoisted benchmark ranking does not match "
                             "production's. Fix before spending Gemma calls.")

        if not args.run:
            print("\n[dry run] no Gemma calls made. Re-run with --run to score.")
            return

        # --- score --------------------------------------------------------------------
        arms_out = {}
        for arm in _ARMS:
            records, models = _score_arm(arm, items[arm], cfg,
                                         tuning.skip_uncoachable_milestones,
                                         args.batch_size)
            scored_pairs = {(r["pair_id"], r["scenario_key"]) for r in records}
            arms_out[arm] = {
                "items": len(items[arm]),
                "unscored": len(items[arm]) - len(scored_pairs),
                "distinct_pairs": len({i["pair_id"] for i in items[arm]}),
                "empty_benchmarks": sum(1 for i in items[arm] if not i["benchmark_response"]),
                "models": dict(models),
                "totals": arm_totals(records),
                "counters": {f"{k[0]}::{k[1]}": v for k, v in aggregate(records).items()},
                "records": records,
            }

        payload = {
            "baseline_schema": args.baseline, "seed": args.seed,
            "per_scenario": args.per_scenario, "batch_size": args.batch_size,
            "scenarios": keys, "plan": plan, "partner": partner,
            "pairing_method": method,
            "skip_uncoachable": tuning.skip_uncoachable_milestones,
            "baseline": _baseline_totals(conn, args.baseline),
            "arms": arms_out,
        }
        out = _Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"\n[artifact] {out}")

        _report(payload)
        _print_samples(payload, args.samples)
    finally:
        conn.close()


def _scenario_text(info: dict) -> str:
    from shared.scenario_vectors import scenario_text
    return scenario_text(info)


def _scenario_sim_matrix(keys: list[str], scen_info: dict) -> np.ndarray:
    from preprocessing import embedder
    from shared import relative_match
    from shared.scenario_vectors import scenario_text
    mat = embedder.embed_document_matrix([scenario_text(scen_info[k]) for k in keys])
    return relative_match.cosine_sims(mat, mat)


if __name__ == "__main__":
    main()
