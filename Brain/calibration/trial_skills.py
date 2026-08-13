#!/usr/bin/env python3
"""Do the 405 milestone axes fold into a behavioural skill vocabulary?

Pre-registration: docs/superpowers/specs/2026-08-13-layer-c-skills-vocabulary-design.md
Every threshold, control and stopping condition below was fixed before any call was spent.

THE QUESTION. The profile today has 405 axes at roughly 8 observations each. That is
arithmetic, not a wording problem, and no scoring fix repairs it. Grouping milestones into
recurring BEHAVIOURS pools their observations -- but only if the groups are real.

WHY THERE ARE TWO CURVES. skills.sweep's cross_scenario_coverage cannot fail: coarsening the
threshold merges everything into one group and drives it to 1.0 by construction, so the sweep
alone always says yes at SOME granularity. Nothing in it gets worse as distinct moves fuse.
That is the merge-blind _match_milestones defect, which scored three baseline milestones
collapsing into one blob as three clean matches because it only counted the good outcome.

So the test is a WINDOW between two curves that constrain from opposite sides:

    K(t)  skills produced        -> lower bound on coarseness (statistical power)
    V(t)  merge validity         -> upper bound on coarseness (a Gemma judge)

    PASS at bound B  iff  some judged t has  K(t) <= B  and  V(t) >= V_MIN

It fails in two distinguishable ways, and both are real answers: validity collapses before
the window opens (behaviours do not generalise), or the window is empty from the other side
(they generalise but not enough to pool).

ZERO WRITES. Reads an artifact or a read-only DB connection; writes only artifacts/.

Usage (from Brain/, venv active):
    python calibration/trial_skills.py --smoke                 # ~4 calls, every path
    python calibration/trial_skills.py --run                   # stage 1 pilot, 91 items
    python calibration/trial_skills.py --run --from-db         # stage 2, all 405
    python calibration/trial_skills.py --load artifacts/skills_trial.json   # free re-report
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

# Brain/ is this file's parent's parent -- put it on sys.path so the shared packages resolve
# whether this script is run directly (python calibration/x.py) or imported by a test
# (from calibration import trial_skills). Same bootstrap every script in this package carries.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

from shared import skills

# Heavy imports (config, gemma, embedder, storage) are deliberately LAZY, inside the
# functions that need them. Importing the embedder pulls in torch and sentence-transformers,
# and the test suite is already unreliable in one process on 16GB Windows because four files
# each load spaCy's 392MiB contiguous vector table. The pure helpers below must stay cheap to
# import or the tests inherit that problem for no reason.

# --- pre-registered constants ---------------------------------------------------------------

# Measured, not chosen. One CSM's Layer D run over 19 transcripts.
_MEASURED_ATTEMPTS = 889
_MEASURED_MILESTONES = 405
# The noise floor from two identical runs (arm3_run1_20260810 vs arm3_run2_noisefloor_20260811).
_NOISE_BAND = 0.006
# The smallest change measurable at this sample size.
_MEASURABLE_CHANGE = 0.020
# A plausible coaching difference worth ranking two skills apart on.
_RANK_DELTA = 0.05

V_MIN = 0.80              # invented -- the one threshold with no precedent in this repo
NULL_MIN_REJECT = 0.80    # invented
ORDER_DRIFT_MAX = 0.20    # invented
SWEEP_THRESHOLDS = [round(0.50 + 0.025 * i, 3) for i in range(19)]   # 0.50 .. 0.95

_ABSTRACT_BATCH = 10      # inherited -- rewrite_milestone_criteria measured truncation at 20
_JUDGE_BATCH = 4
_GEMMA_CALL_DELAY = 5     # seconds; free-tier quota is 16k input tokens/minute
_N_JUDGE_GROUPS = 12      # real groups sampled per judged threshold
_N_NULL_PAIRS = 12
_N_SHUFFLES = 5


def _quantization_floor(step: float) -> int:
    """W = (hits + 0.5*partials)/attempts moves in steps of 1/(2n)."""
    return round(1 / (2 * step))


def _rank_floor(delta: float) -> int:
    """Ranking resolves a difference between two noisy estimates, not one estimate.

    Grounded in the EMPIRICAL band rather than a theoretical standard error -- mixing the
    two would be apples-to-oranges. Noise scales as 1/sqrt(n), so a per-axis band at n
    observations is _NOISE_BAND * sqrt(_MEASURED_ATTEMPTS / n); require it <= delta/2.
    """
    return round(_MEASURED_ATTEMPTS / ((delta / 2) / _NOISE_BAND) ** 2)


# max_k is the pre-registered value from the design's tables, equal to
# _MEASURED_ATTEMPTS / min_obs rounded to the figure recorded there. min_members is derived
# rather than stated, because it is the operative gate (see min_members below).
POWER_STANDARDS = (
    {"key": "noise_band", "min_obs": _quantization_floor(_NOISE_BAND), "max_k": 11,
     "label": "step <= the measured noise band (0.006)"},
    {"key": "half_change", "min_obs": _quantization_floor(_MEASURABLE_CHANGE / 2), "max_k": 18,
     "label": "step <= half a measurable change (0.010)"},
    {"key": "full_change", "min_obs": _quantization_floor(_MEASURABLE_CHANGE), "max_k": 35,
     "label": "step <= a measurable change (0.020)"},
    {"key": "rank_d05", "min_obs": _rank_floor(_RANK_DELTA), "max_k": 17,
     "label": "rank two skills apart at delta = 0.05"},
)


def min_members(standard: dict) -> int:
    """How many member milestones the MEDIAN skill needs to satisfy this standard.

    K is an optimistic bound because it assumes observations spread evenly across skills.
    They will not: a skill absorbing 40 milestones and one absorbing 2 both count toward K
    while only the first can carry an axis. Attempts distribute over milestones at roughly
    _MEASURED_ATTEMPTS/_MEASURED_MILESTONES each, so this converts an observation floor into
    a member-count floor. This is the gate; K is the headline.
    """
    return math.ceil(standard["min_obs"] * _MEASURED_MILESTONES / _MEASURED_ATTEMPTS)


def meets_standard(row: dict, standard: dict) -> bool:
    """A sweep row satisfies a standard only if BOTH the count and the median hold."""
    return (row["n_skills"] <= standard["max_k"]
            and row["median_size"] >= min_members(standard))


# --- reading the population --------------------------------------------------------------

def extract_descriptions(payload: dict, arm: str) -> list[dict]:
    """Pull (scenario_key, description) pairs out of a trial artifact.

    scenario_key must survive: it is what scenario_span is computed from, and losing it
    would make every group look confined to one scenario -- the exact failure this test
    exists to detect.
    """
    rubrics = ((payload.get("arms") or {}).get(arm) or {}).get("rubrics") or {}
    out = []
    for scenario_key in sorted(rubrics):
        for i, m in enumerate(rubrics[scenario_key].get("milestones") or []):
            text = (m.get("description") or "").strip()
            if not text:
                # A blank embeds to a real vector and would join some group on noise.
                continue
            out.append({
                "id": f"{scenario_key}#{i}",
                "scenario_key": scenario_key,
                "description": text,
                "is_mechanics": m.get("not_coachable_category") == "mechanics",
            })
    return out


# --- choosing where to spend judge calls ---------------------------------------------------

def select_judge_thresholds(rows: list[dict]) -> list[float]:
    """The judged points: each bound's best shot, plus a positive control.

    K falls as the threshold falls, so a bound K <= B holds for every t below some point.
    The LARGEST such t is that bound's best shot -- finer clustering means higher validity,
    so judging a coarser one would understate the bound. The finest threshold overall is
    always judged as a positive control: validity should be near 1.0 where almost nothing
    merged, and if it is not, the judge is broken and no other point can be believed.
    """
    if not rows:
        return []
    picked = {max(r["threshold"] for r in rows)}
    for standard in POWER_STANDARDS:
        ok = [r["threshold"] for r in rows if r["n_skills"] <= standard["max_k"]]
        if ok:
            picked.add(max(ok))
    return sorted(picked)


# --- the window -----------------------------------------------------------------------------

def evaluate_window(rows: list[dict], validity: dict, v_min: float = V_MIN) -> dict:
    """Per standard: does any JUDGED threshold clear both curves?

    An unjudged threshold never counts as a pass -- absent validity means unmeasured, never
    assumed good.
    """
    result = {}
    for standard in POWER_STANDARDS:
        best = None
        for row in sorted(rows, key=lambda r: -r["threshold"]):
            v = validity.get(row["threshold"])
            if v is None or not meets_standard(row, standard):
                continue
            if v >= v_min:
                best = (row, v)
                break
        result[standard["key"]] = {
            "label": standard["label"],
            "max_k": standard["max_k"],
            "min_members": min_members(standard),
            "passed": best is not None,
            "threshold": best[0]["threshold"] if best else None,
            "n_skills": best[0]["n_skills"] if best else None,
            "median_size": best[0]["median_size"] if best else None,
            "validity": best[1] if best else None,
        }
    return result


# --- the judge's blinded null -----------------------------------------------------------------

def null_pairs(vectors: np.ndarray, n: int, seed: int) -> list[tuple[int, int]]:
    """Maximally dissimilar behaviour pairs, to be disguised as groups and mixed in blind.

    Two judges have already failed their own nulls here (the applicability judge at 1.22:1,
    the coverage judge at 64.9% vs 65.7%), so this one is nulled before it is trusted. The
    pairs are drawn from the least-similar decile deliberately: anything less extreme would
    be genuinely ambiguous and so could not falsify anything.
    """
    if len(vectors) < 2 or n <= 0:
        return []
    normed = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10)
    sims = normed @ normed.T
    pairs = [(float(sims[i][j]), i, j)
             for i in range(len(normed)) for j in range(i + 1, len(normed))]
    pairs.sort(key=lambda p: (p[0], p[1], p[2]))
    pool_size = min(len(pairs), max(n, max(1, int(0.1 * len(pairs)))))
    pool = [(i, j) for _, i, j in pairs[:pool_size]]
    rng = random.Random(seed)
    return rng.sample(pool, min(n, len(pool)))


def null_groups(vectors: np.ndarray, sizes: list[int], seed: int) -> list[tuple[int, ...]]:
    """Mutually-dissimilar groups whose SIZES match the real groups shown alongside them.

    Blinding is the point. An earlier version emitted every null as a 2-item pair while real
    groups carried up to 8, so the judge could have identified the nulls by size alone and
    the null would have measured nothing -- exactly the self-inflicted harness error that
    made dry_run_ego_trap's chosen-vs-discarded band read "no data".
    """
    if len(vectors) < 2 or not sizes:
        return []
    normed = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10)
    sims = normed @ normed.T
    rng = random.Random(seed)
    out = []
    for want in sizes:
        k = max(2, min(want, len(vectors)))
        chosen = [rng.randrange(len(vectors))]
        while len(chosen) < k:
            worst = np.max(sims[chosen], axis=0)
            worst[chosen] = 2.0
            chosen.append(int(np.argmin(worst)))
        out.append(tuple(chosen))
    return out


def null_passed(verdicts: dict, min_reject: float = NULL_MIN_REJECT) -> bool:
    """An empty null FAILS rather than passing vacuously.

    all() over nothing is True, which would silently certify a judge that was never tested.
    """
    if not verdicts:
        return False
    rejected = sum(1 for v in verdicts.values() if v == "fused")
    return rejected / len(verdicts) >= min_reject


# --- order permutation --------------------------------------------------------------------------

def permutation_counts(vectors: np.ndarray, threshold: float,
                       n_shuffles: int, seed: int) -> list[int]:
    """Skill counts under reshuffled input order.

    cluster_behaviours is greedy nearest-centroid and order-dependent by its own docstring.
    A vocabulary that reshuffles between runs cannot carry a profile however well it groups
    once -- that is stopping condition #3 of the parent design, measured rather than assumed.
    """
    rng = random.Random(seed)
    counts = []
    for _ in range(n_shuffles):
        order = list(range(len(vectors)))
        rng.shuffle(order)
        counts.append(len(set(skills.cluster_behaviours(vectors[order], threshold))))
    return counts


def permutation_drift(counts: list[int], baseline: int) -> float:
    """Median relative movement in the skill count. Zero for an empty run, not a crash."""
    if not counts or not baseline:
        return 0.0
    return statistics.median(abs(c - baseline) / baseline for c in counts)


# --- Gemma paths (impure) ---------------------------------------------------------------------

def _model_kwargs(model: str | None) -> dict:
    return {"model": model} if model else {}


def _as_list(raw, key: str) -> list:
    """Gemma sometimes returns a bare JSON array instead of the wrapped object."""
    return raw if isinstance(raw, list) else (raw.get(key) or raw.get("results") or [])


def abstract_behaviours(items: list[dict], config, model: str | None = None,
                        prompt_version: str = "v1") -> dict:
    """One Gemma pass stripping the topic off each description. Batched at 10.

    The strip is the whole trick. Clustering the descriptions as written groups them by
    SUBJECT, not behaviour, because bge embeddings are topic-dominated -- "ask open
    questions about budget" separates from "ask open questions about screening" purely on
    the topical object.
    """
    from shared.gemma import call_gemma
    from shared import prompts as _p

    prompt = (_p.PROMPT_SKILL_ABSTRACT_BATCH_V2 if prompt_version == "v2"
              else _p.PROMPT_SKILL_ABSTRACT_BATCH)
    out: dict[str, str] = {}
    batches = [items[i:i + _ABSTRACT_BATCH] for i in range(0, len(items), _ABSTRACT_BATCH)]
    for n, batch in enumerate(batches, 1):
        block = "\n".join(f'{it["id"]} | {it["description"]}' for it in batch)
        print(f"  [abstract:{prompt_version}] batch {n}/{len(batches)} "
              f"({len(batch)} items)", flush=True)
        raw = call_gemma(prompt.format(items_block=block),
                         config.gemma_api_keys, **_model_kwargs(model))
        time.sleep(_GEMMA_CALL_DELAY)
        for rec in _as_list(raw, "items"):
            if isinstance(rec, dict) and rec.get("id") and rec.get("behaviour"):
                out[str(rec["id"])] = str(rec["behaviour"]).strip()
    missing = [it["id"] for it in items if it["id"] not in out]
    if missing:
        print(f"  [abstract] WARNING: {len(missing)} items got no behaviour back", flush=True)
    return out


def judge_groups(groups: list[dict], config, model: str | None = None) -> dict:
    """Merge validity. Every group gets a verdict; never a returned subset.

    `groups` mixes real clusters with disguised null pairs in one shuffled stream, so the
    judge cannot tell which is which.
    """
    from shared.gemma import call_gemma
    from shared.prompts import PROMPT_SKILL_MERGE_VALIDITY_BATCH

    out: dict[str, str] = {}
    batches = [groups[i:i + _JUDGE_BATCH] for i in range(0, len(groups), _JUDGE_BATCH)]
    for n, batch in enumerate(batches, 1):
        block = "\n\n".join(
            f'GROUP {g["id"]}:\n' + "\n".join(f"  - {b}" for b in g["behaviours"])
            for g in batch)
        print(f"  [judge] batch {n}/{len(batches)} ({len(batch)} groups)", flush=True)
        raw = call_gemma(PROMPT_SKILL_MERGE_VALIDITY_BATCH.format(groups_block=block),
                         config.gemma_api_keys, **_model_kwargs(model))
        time.sleep(_GEMMA_CALL_DELAY)
        for rec in _as_list(raw, "groups"):
            if isinstance(rec, dict) and rec.get("id"):
                verdict = str(rec.get("verdict", "")).strip()
                out[str(rec["id"])] = verdict if verdict in ("same_move", "fused") else "fused"
    return out


def _embed(texts: list[str]) -> np.ndarray:
    """Document-side embedding: this is a symmetric behaviour-to-behaviour comparison, the
    same convention scenario_vectors uses. The cache is keyed on the prefix, so picking
    embed_query here would silently build a different vector population."""
    from preprocessing import embedder
    return embedder.embed_document_matrix(texts)


# --- orchestration ------------------------------------------------------------------------------

def _sweep_with_groups(vectors: np.ndarray, scenario_keys: list[str]) -> tuple[list, dict]:
    rows = skills.sweep(vectors, scenario_keys, SWEEP_THRESHOLDS)
    per_threshold = {}
    for t in SWEEP_THRESHOLDS:
        labels = skills.cluster_behaviours(vectors, t)
        per_threshold[t] = skills.summarise_groups(labels, scenario_keys)
    return rows, per_threshold


def _mechanics_control(groups: list[dict], items: list[dict]) -> dict:
    """Mechanics items have an explicit "call mechanics" escape hatch in the abstraction
    prompt, so they SHOULD collapse into one group. Free, and it catches a pass that is not
    abstracting at all."""
    idx = [i for i, it in enumerate(items) if it["is_mechanics"]]
    if not idx:
        return {"n_mechanics": 0, "n_groups": 0, "collapsed": None}
    holding = {g["group"] for g in groups if set(g["members"]) & set(idx)}
    return {"n_mechanics": len(idx), "n_groups": len(holding),
            "collapsed": len(holding) == 1}


def run(items: list[dict], config, model: str | None, seed: int,
        n_judge_groups: int = _N_JUDGE_GROUPS, n_null: int = _N_NULL_PAIRS,
        reuse_behaviours: dict | None = None, skip_control: bool = False,
        prompt_version: str = "v1") -> dict:
    """The whole measurement. Flushes nothing itself -- the caller writes as stages land."""
    texts = [it["description"] for it in items]
    scenario_keys = [it["scenario_key"] for it in items]

    if skip_control:
        # The control answers "is the abstraction pass inert" and already answered it
        # decisively (56 groups as-written vs 14 abstracted at t=0.7). Re-running it in a
        # new vector space costs a full second embedding of the corpus for no new
        # information, and on a metered backend that is half the budget.
        print("[1/5] control sweep SKIPPED (already established; saves "
              f"{len(items)} requests)", flush=True)
        control_rows = []
    else:
        print(f"[1/5] control sweep on {len(items)} descriptions AS WRITTEN", flush=True)
        control_rows, _ = _sweep_with_groups(_embed(texts), scenario_keys)

    if reuse_behaviours:
        # CHANGE EXACTLY ONE THING. Re-using the saved abstraction means the embedder is
        # the only difference from the run this is being compared against -- re-abstracting
        # would vary the LLM's wording and the vector space at once, and neither could then
        # be credited. Same reason arm0r_legacy_regen had to exist.
        behaviours = {it["id"]: reuse_behaviours[it["id"]]
                      for it in items if it["id"] in reuse_behaviours}
        print(f"[2/5] REUSING {len(behaviours)} saved behaviours "
              f"(no abstraction calls; embedder is the only variable)", flush=True)
    else:
        print(f"[2/5] abstracting {len(items)} descriptions "
              f"(prompt {prompt_version})", flush=True)
        behaviours = abstract_behaviours(items, config, model, prompt_version)
    kept = [it for it in items if it["id"] in behaviours]
    if not kept:
        return {"error": "the abstraction pass returned nothing"}
    b_texts = [behaviours[it["id"]] for it in kept]
    b_keys = [it["scenario_key"] for it in kept]
    vectors = _embed(b_texts)

    print(f"[3/5] sweeping {len(SWEEP_THRESHOLDS)} thresholds", flush=True)
    rows, per_threshold = _sweep_with_groups(vectors, b_keys)

    judged = select_judge_thresholds(rows)
    print(f"[4/5] judging merge validity at {judged}", flush=True)
    rng = random.Random(seed)
    payload_groups, provenance = [], {}
    for t in judged:
        multi = [g for g in per_threshold[t] if g["size"] >= 2]
        for g in rng.sample(multi, min(n_judge_groups, len(multi))):
            gid = f"g{len(payload_groups)}"
            payload_groups.append({"id": gid,
                                   "behaviours": [b_texts[i] for i in g["members"]][:8]})
            provenance[gid] = {"kind": "real", "threshold": t}
    # Nulls take their sizes from the real groups already queued, so size carries no signal.
    real_sizes = [len(g["behaviours"]) for g in payload_groups] or [2]
    sizes = [real_sizes[i % len(real_sizes)] for i in range(n_null)]
    for members in null_groups(vectors, sizes, seed):
        gid = f"g{len(payload_groups)}"
        payload_groups.append({"id": gid, "behaviours": [b_texts[i] for i in members]})
        provenance[gid] = {"kind": "null", "threshold": None}
    rng.shuffle(payload_groups)

    verdicts = judge_groups(payload_groups, config, model) if payload_groups else {}
    null_verdicts = {k: v for k, v in verdicts.items() if provenance.get(k, {}).get("kind") == "null"}
    validity = {}
    for t in judged:
        real = [v for k, v in verdicts.items()
                if provenance.get(k, {}).get("threshold") == t]
        if real:
            validity[t] = sum(1 for v in real if v == "same_move") / len(real)

    print("[5/5] order permutation + window", flush=True)
    stability = {}
    for t in judged:
        baseline = next(r["n_skills"] for r in rows if r["threshold"] == t)
        counts = permutation_counts(vectors, t, _N_SHUFFLES, seed)
        stability[t] = {"baseline": baseline, "counts": counts,
                        "drift": permutation_drift(counts, baseline)}

    return {
        "n_items": len(items), "n_abstracted": len(kept), "seed": seed, "model": model,
        "v_min": V_MIN,
        "behaviours": {it["id"]: behaviours[it["id"]] for it in kept},
        "control_rows": control_rows,
        "rows": rows,
        "judged_thresholds": judged,
        "validity": {str(k): v for k, v in validity.items()},
        "null": {"verdicts": null_verdicts, "passed": null_passed(null_verdicts)},
        "mechanics_control": {
            str(t): _mechanics_control(per_threshold[t], kept) for t in judged},
        "stability": {str(k): v for k, v in stability.items()},
        "window": evaluate_window(rows, validity),
        "sample_groups": {
            str(t): [[b_texts[i] for i in g["members"]][:6]
                     for g in sorted(per_threshold[t], key=lambda g: -g["size"])[:5]]
            for t in judged},
    }


# --- reporting -------------------------------------------------------------------------------------

def report(payload: dict) -> None:
    if payload.get("error"):
        print(f"\nRUN FAILED: {payload['error']}")
        return
    print("\n" + "=" * 78)
    print(f"SKILLS VOCABULARY -- {payload['n_abstracted']}/{payload['n_items']} abstracted"
          f"  seed={payload['seed']}  model={payload['model'] or 'default'}")
    print("=" * 78)

    print("\nCONTROL -- as written vs abstracted (if these match, the pass is inert)")
    print(f"  {'thresh':>7} {'K written':>10} {'K abstract':>11} {'median':>7} {'x-scen':>7}")
    ctrl = {r["threshold"]: r for r in payload["control_rows"]}
    for r in payload["rows"]:
        c = ctrl.get(r["threshold"], {})
        print(f"  {r['threshold']:>7} {c.get('n_skills', 0):>10} {r['n_skills']:>11}"
              f" {r['median_size']:>7.1f} {r['cross_scenario_coverage']:>7.2f}")

    null = payload["null"]
    n_rej = sum(1 for v in null["verdicts"].values() if v == "fused")
    print(f"\nJUDGE NULL -- rejected {n_rej}/{len(null['verdicts'])} disguised pairs"
          f"  -> {'PASS' if null['passed'] else 'FAIL'}")
    if not null["passed"]:
        print("  The counterweight is VOID. No granularity may be claimed from this run.")

    print("\nMECHANICS POSITIVE CONTROL (should collapse to 1 group)")
    for t, m in payload["mechanics_control"].items():
        print(f"  t={t}: {m['n_mechanics']} mechanics items in {m['n_groups']} groups"
              f"  -> {m['collapsed']}")

    print("\nORDER PERMUTATION (drift must stay <= %.2f)" % ORDER_DRIFT_MAX)
    for t, s in payload["stability"].items():
        flag = "" if s["drift"] <= ORDER_DRIFT_MAX else "   <-- UNSTABLE"
        print(f"  t={t}: K={s['baseline']} counts={s['counts']} drift={s['drift']:.2f}{flag}")

    print(f"\nWINDOW (V_MIN={payload['v_min']})")
    if payload["n_items"] < _MEASURED_MILESTONES:
        frac = payload["n_items"] / _MEASURED_MILESTONES
        print(f"  NOT EVALUABLE: this population is {payload['n_items']} milestones"
              f" ({frac:.0%} of the corpus), so it carries about {frac:.0%} of the 889"
              "\n  attempts the member floors were derived from. The floors are"
              " pre-registered for the\n  FULL 405 and are deliberately not rescaled here"
              " -- a bound moved to fit the run it is\n  judging is not a bound. Read the"
              " control, null, mechanics and stability rows; the\n  window verdict below"
              " means nothing until stage 2.")
    for key, w in payload["window"].items():
        verdict = "PASS" if w["passed"] else "no window"
        detail = (f" at t={w['threshold']} K={w['n_skills']} median={w['median_size']:.1f}"
                  f" V={w['validity']:.2f}" if w["passed"] else "")
        print(f"  {key:<12} K<={w['max_k']:<3} median>={w['min_members']:<3} {verdict}{detail}")
        print(f"               {w['label']}")

    print("\nLARGEST GROUPS -- read these, the count never decides anything")
    for t, groups in payload["sample_groups"].items():
        print(f"  --- t={t} ---")
        for g in groups:
            print(f"    [{len(g)}] " + " | ".join(g))

    # Only a full-corpus run may draw this conclusion. A subsample cannot reach the member
    # floors whatever the behaviours look like, so printing the verdict there would state a
    # negative the run is structurally incapable of earning -- the same error as reading a
    # window out of numbers the caveat above just said mean nothing.
    if (not any(w["passed"] for w in payload["window"].values())
            and payload["n_items"] >= _MEASURED_MILESTONES):
        print("\nSTOPPING CONDITION 3: no window at any bound. On this evidence a"
              "\nbehavioural skill vocabulary is not buildable from this corpus.")


# --- entry point --------------------------------------------------------------------------------------

def _load_items_from_artifact(path: Path, arm: str) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return extract_descriptions(payload, arm)


def _load_items_from_db() -> list[dict]:
    """Stage 2: all 405, over a read-only connection so a stray write fails at Postgres.

    There is no storage.get_rubrics -- rubrics are fetched one scenario at a time via
    get_rubric_for_scenario, which returns None for the ~half of `scenarios` that are
    non-coachable sinks and therefore never had a rubric generated.
    """
    from config import load_config
    from calibration import score_naren_ceiling as snc
    from shared import storage

    cfg = load_config()
    conn = snc._connect_read_only(cfg.database_url)
    try:
        out = []
        for s in sorted(storage.get_scenarios(conn), key=lambda s: s["scenario_key"]):
            rubric = storage.get_rubric_for_scenario(conn, s["scenario_key"])
            if not rubric:
                continue
            for i, m in enumerate(rubric.get("milestones") or []):
                text = (m.get("description") or "").strip()
                if text:
                    out.append({"id": f"{s['scenario_key']}#{i}",
                                "scenario_key": s["scenario_key"], "description": text,
                                "is_mechanics": m.get("not_coachable_category") == "mechanics"})
        return out
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="spend Gemma calls")
    ap.add_argument("--smoke", action="store_true",
                    help="~4 calls over 12 items: exercises every path end to end")
    ap.add_argument("--load", help="re-report a saved artifact for free")
    ap.add_argument("--from-db", action="store_true", help="stage 2: all 405 from Postgres")
    ap.add_argument("--artifact", default=str(ARTIFACTS_DIR / "trial_final.json"))
    ap.add_argument("--arm", default="arm0_baseline")
    ap.add_argument("--model", default=None, help="override the describe model")
    ap.add_argument("--seed", type=int, default=20260813)
    ap.add_argument("--out", default=str(ARTIFACTS_DIR / "skills_trial.json"))
    ap.add_argument("--embed-backend", choices=("local", "gemini"), default=None,
                    help="override tuning.yaml for this process only")
    ap.add_argument("--abstract-prompt", choices=("v1", "v2"), default="v1",
                    help="v2 bans the purpose clause that splintered one behaviour into "
                         "30 phrasings")
    ap.add_argument("--reverse-keys", action="store_true",
                    help="try the last configured API key first")
    ap.add_argument("--skip-control", action="store_true",
                    help="skip the as-written sweep (already established; halves cost "
                         "on a metered backend)")
    ap.add_argument("--reuse-behaviours",
                    help="load the abstraction from a prior artifact instead of "
                         "re-running it, so the embedder is the only variable")
    args = ap.parse_args()

    if args.load:
        report(json.loads(Path(args.load).read_text(encoding="utf-8-sig")))
        return
    if not (args.run or args.smoke):
        print("Nothing to do. Pass --smoke (cheap) or --run, or --load to re-report.")
        return

    items = _load_items_from_db() if args.from_db else _load_items_from_artifact(
        Path(args.artifact), args.arm)
    if not items:
        print("No descriptions found -- check --artifact/--arm.")
        return

    posture = sum(1 for it in items if it["scenario_key"].startswith("client_"))
    scenarios = {it["scenario_key"] for it in items}
    print(f"POPULATION: {len(items)} milestones over {len(scenarios)} scenarios"
          f"  ({posture} posture / {len(items) - posture} subject-matter)")
    if posture == 0 or posture == len(items):
        print("  WARNING: one stratum is EMPTY. An alphabetical prefix returns exactly this"
              " and it silently tests a fix on the half that already worked.")

    if args.smoke:
        items = items[:12]
        print(f"SMOKE TEST: {len(items)} items, ~4 calls. Numbers are a path test, not a result.")

    if args.embed_backend:
        from preprocessing import embedder
        embedder.set_backend(args.embed_backend)
        print(f"EMBEDDER: {args.embed_backend} (process-only override; "
              f"tuning.yaml is unchanged)")
        if args.reverse_keys:
            embedder.set_key_order(reverse=True)
            print("KEY ORDER: reversed -- the last configured key goes first")

    reuse = None
    if args.reuse_behaviours:
        prior = json.loads(Path(args.reuse_behaviours).read_text(encoding="utf-8-sig"))
        reuse = prior.get("behaviours") or {}
        if not reuse:
            print(f"No 'behaviours' in {args.reuse_behaviours} -- cannot reuse.")
            return
        print(f"REUSING {len(reuse)} behaviours from {args.reuse_behaviours}")
        print("THE GATE IS UNCHANGED: V_MIN=%.2f and the same K/median bounds as the run"
              "\nthis is compared against. A second attempt at a question that returned"
              "\nno is exactly where a bar gets quietly moved." % V_MIN)

    from config import load_config
    payload = run(items, load_config(), args.model, args.seed,
                  n_judge_groups=3 if args.smoke else _N_JUDGE_GROUPS,
                  n_null=3 if args.smoke else _N_NULL_PAIRS,
                  reuse_behaviours=reuse, skip_control=args.skip_control,
                  prompt_version=args.abstract_prompt)
    payload["smoke"] = args.smoke
    payload["abstract_prompt"] = args.abstract_prompt
    payload["embed_backend"] = args.embed_backend or "tuning.yaml default"
    payload["reused_behaviours_from"] = args.reuse_behaviours

    # Flush the paid results BEFORE reporting. One scored run lost all 95 LLM results
    # because a free lookup gated the persistence of expensive work.
    Path(args.out).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")
    report(payload)


if __name__ == "__main__":
    main()
