#!/usr/bin/env python3
"""LAYER B/C DOWNSTREAM VALIDATION: does the noise-rescue reach a RUBRIC? Zero chat calls.

Spec: docs/superpowers/specs/2026-08-16-layer-bc-downstream-validation-design.md

THE ONE QUESTION. Every Layer A result so far is an INPUT-side claim: `rescue_centroid` admits
on-topic turns (blinded 10/10), broadens evidence (96->133 calls per scenario), and yields 34
scenarios against a 26-28 noise band. None of that is an OUTCOME. The justification was always
a chain -- more turns per scenario -> more kb_pairs -> more response clauses -> more milestone
support -- and not one link had been measured. This measures the first three.

ONE VARIABLE. Two arms over one fixed corpus, differing only in which taxonomy Layer B matches
against. Matching stays at production's default (`layer_a.scenario_vector_mode: concat`) in
BOTH arms; an earlier draft also pitted centroid matching against description matching and that
is CUT, because two variables would give a clean answer to neither.

*** THE CHANNEL IS NARROW, AND KNOWING THAT IS WHAT MAKES A NULL READABLE. *** The rescued
client turns NEVER reach Layer C -- Layer C clusters NAREN'S RESPONSE clauses. The rescue can
only reach a rubric through the description Gemma wrote after seeing different representative
utterances:

    more client turns -> different representatives -> different description + keyphrases
      -> different scenario VECTOR -> (a) different triggers routed in (layer_b.assign_scenarios)
                                     (b) different p40 relevance cutoff (layer_c._relevance_filter)
      -> different milestone clusters

So a null result has two distinct causes that must not be conflated: the rescue did nothing, or
the DESCRIPTION did not move enough to reroute anything. This harness reports description drift
and routing drift alongside the milestone counts, so the two can be told apart.

WHAT IT COSTS. Nothing. Layer C Pass 1 is Gemma-free and every vector is served from the gemini
cache with a hard abort on a miss. That is also why the noise floor is affordable here in a way
it was not for adjudication: run the same arm twice and the pair IS the floor.

*** RUN EACH ARM IN ITS OWN PROCESS. *** UMAP+HDBSCAN is documented non-reproducible ACROSS
process launches (385/398/403-407 milestones for identical input) and deterministic WITHIN one.
Running two arms in one process would hide exactly the variance the floor exists to price, and
running the floor pair in one process would report a fake zero -- the same shape as last
session's gateway-cache "perfect determinism".

GUARDS, each from a specific past failure in this repo
------------------------------------------------------
1. `--arm` IS REQUIRED and names its own artifact. No default can overwrite a baseline.
2. IDENTITY IS A CONTENT HASH of the corpus, the taxonomy memberships and every threshold that
   moves the answer -- recorded per artifact and diffed at --compare. A count-based key cannot
   distinguish two arms that differ only in membership, which produced a silent "no effect with
   zero calls" result last session.
3. ARMS ARE JOINED ON `cluster_id`, NEVER on scenario_key. Gemma invents a fresh name per run
   (`stakeholder_role_identification` vs `stakeholder_role_mapping` are the same cluster
   renamed), so a name join would report the entire taxonomy as changed. The adjudication A/B
   holds cluster identity fixed, which is what makes a matched comparison possible at all.
4. A `merged` OUTCOME IS REPORTED. `replay_layer_c_admitted._match_milestones` was merge-blind
   and scored N baseline milestones collapsing into ONE arm cluster as N clean matches --
   inflating a whole Layer C A/B while the milestone count went up.
5. SUPPORT IS NORMALISED by each arm's own scenario call count. A raw 112 -> 133 jump was 73%
   -> 72% once the arm's extra calls were counted.
6. A VOLUME-MATCHED PLACEBO (`--placebo --volume-from ARM`). Perturbing a clause pool AT ALL
   costs ~6 milestones to UMAP/HDBSCAN sensitivity regardless of content quality, so a loss
   count is uninterpretable without one.
7. `available_frac` IS REPORTED per lost milestone. Unlike the sink-admission replay, neither
   arm's clause pool is a superset of the other's -- a base milestone can vanish because its
   pairs were REROUTED to another scenario, which is a different finding from being reclustered
   away. Conflating them would misattribute a routing change to clustering noise.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/layer_bc_arms.py --arm base_1  --taxonomy clean2_base_a
    ..\\.venv\\Scripts\\python.exe calibration/layer_bc_arms.py --arm base_2  --taxonomy clean2_base_a
    ..\\.venv\\Scripts\\python.exe calibration/layer_bc_arms.py --arm rescued --taxonomy clean2_rescued
    ..\\.venv\\Scripts\\python.exe calibration/layer_bc_arms.py --arm placebo --taxonomy clean2_base_a \\
        --placebo --volume-from rescued
    ..\\.venv\\Scripts\\python.exe calibration/layer_bc_arms.py --arm r2 --taxonomy clean2_base \\
        --router r2
    ..\\.venv\\Scripts\\python.exe calibration/layer_bc_arms.py --compare base_1,base_2,rescued,placebo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

EMBED_WIDTH = 3072          # native; the clustering trial measured 3072 > 768 for clustering
MATCH_MAJORITY = 0.5        # a base milestone is "matched" when >half its clauses land together
# Production reference for the F4 sanity band: 404 milestones over 85 coachable scenarios.
# Stated PER SCENARIO because this taxonomy has ~30 scenarios, not 85 -- a raw [350,450] band
# copied across would void every run for the wrong reason.
PROD_MILESTONES_PER_SCENARIO = 404 / 85
# a3's floors are chosen so it admits the SAME FRACTION production's stopword rule does, making
# it volume-neutral by construction -- same number of pairs, different selection, so any
# difference is the stoplist dependence alone and a3 needs no placebo. Measured on this corpus:
# 20,788 CLIENT turns -> 7,054 fail the trigger floor (33.9%), so 66.1% are admitted; and of the
# NAREN side, cause (c) is 2,053 of the turns whose trigger passed. Both are re-derived per run
# from the corpus rather than hardcoded here as counts.
A3_TARGET_CLIENT = 0.661
A3_TARGET_NAREN = 0.90


def paths(arm: str) -> Path:
    """One artifact per arm. `--arm` is required precisely so no default can collide with a
    published baseline."""
    if not arm or not arm.replace("_", "").replace("-", "").isalnum():
        raise SystemExit(f"--arm must be a non-empty alphanumeric name, got {arm!r}")
    return ARTIFACTS_DIR / f"layer_bc_{arm}.json"


def taxonomy_path(name: str) -> Path:
    return ARTIFACTS_DIR / f"adjudication_ab_{name}.json"


# ---------------------------------------------------------------------------------------
# pure helpers (covered by tests/test_layer_bc_arms.py)
# ---------------------------------------------------------------------------------------

def scenario_map_from_rows(rows: list[dict]) -> tuple[dict, dict]:
    """Turn an adjudication artifact's rows into the scenario_map Layer B/C consume.

    Returns (scenario_map, cluster_of_key).

    FOUR KINDS, and collapsing them is the defect this repo has now hit twice (the phantom
    "Gemma over-sinks 14.6%" finding, and again in the null-test control):

      scenario   -> a coachable scenario. Gets a rubric.
      mechanics  } -> a SINK. is_coachable=False. MUST be in the map: layer_b's short-circuit
      logistics  }    files a junk trigger to its sink ALONE, and deleting sinks would make
                      every trigger match a real scenario by construction.
      merged     -> RETAINED, folded into an existing scenario. Contributes NO new key, so it
                    is absent from the map -- but it is NOT a sink and must never be counted
                    as one.
      failed     -> a transport failure. Excluded entirely; synthesising it as a scenario both
                    inflates the coachable count and poisons downstream matching.

    Duplicate keys are SUFFIXED, not deduped -- see the comment at the collision site; it is
    the difference between a symmetric and an asymmetric filter across arms.

    `scenario_id` is a synthetic index. Nothing here touches Postgres; assign_scenarios only
    ever copies the value into the pair dict.
    """
    scenario_map: dict[str, dict] = {}
    cluster_of_key: dict[str, str] = {}
    for i, r in enumerate(rows):
        kind = r.get("kind")
        if r.get("failed") or kind in (None, "failed", "merged"):
            continue
        if kind not in ("scenario", "mechanics", "logistics"):
            raise ValueError(f"unknown adjudication kind {kind!r} on row {i}")
        # *** DUPLICATE KEYS ARE NORMAL HERE AND MUST BE SUFFIXED, NEVER DEDUPED. ***
        # An earlier version of this function raised on a collision, on the false premise that
        # `adjudication_ab.py` already suffixes. It does not -- it writes Gemma's raw key
        # verbatim (:455); the suffix loop lives in production `v2/layer_a.py:534-539`. Gemma
        # independently invents `conversational_acknowledgment` for up to 26 different sink
        # clusters in one run, so the collision rate is large and, critically, DIFFERENT PER
        # ARM: 37 / 29 / 36 rows on the three clean_* artifacts. Dropping duplicates would
        # therefore remove a different number of SINKS from each arm -- fewer sinks means
        # fewer sink short-circuits in layer_b and different routing for one arm only, which
        # is the asymmetric-filtering error this repo has a standing rule against.
        # Suffixing keeps every cluster's evidence and is applied identically in every arm.
        base_key = r["scenario_key"] or f"cluster_{i}"
        key, suffix = base_key, 1
        while key in scenario_map:
            key = f"{base_key}_{suffix}"
            suffix += 1
        scenario_map[key] = {
            "scenario_id": i,
            "scenario_key": key,
            "business_description": r.get("business_description") or "",
            "keyphrases": r.get("keyphrases") or [],
            "primary_topic": r.get("scenario_key") or "",
            "is_coachable": kind == "scenario",
            "cluster_kind": kind,
        }
        cluster_of_key[key] = r.get("cluster_id") or ""
    return scenario_map, cluster_of_key


def corpus_sha(pairs: list[dict]) -> str:
    """Content hash of the extracted pairs -- the corpus as Layer B actually sees it.

    Hashing the transcript FILENAMES would not notice a re-parse that changed speaker roles,
    which is exactly what the UNATTRIBUTED fix did to this corpus.
    """
    h = hashlib.sha256()
    for p in pairs:
        h.update(f"{p['call_filename']}|{p['turn_index']}|{p['trigger_text']}|"
                 f"{p['response_text']}\n".encode("utf-8"))
    return h.hexdigest()[:16]


def taxonomy_sha(scenario_map: dict) -> str:
    """Hash of the TEXT each scenario is matched by, not just its key.

    Gemma renames a cluster every run, so a key-only hash would report two genuinely identical
    taxonomies as different; conversely two runs can share every key while the descriptions --
    the only channel the rescue has -- moved completely.
    """
    from shared.scenario_vectors import scenario_text
    h = hashlib.sha256()
    for k in sorted(scenario_map):
        info = scenario_map[k]
        h.update(f"{k}|{int(bool(info['is_coachable']))}|{scenario_text(info)}\n"
                 .encode("utf-8"))
    return h.hexdigest()[:16]


def taxonomy_provenance(tax_art: dict) -> dict:
    """The adjudication run's OWN settings, carried forward so --compare can see them.

    Without this, two arms built from taxonomies fitted on DIFFERENT CORPORA compare cleanly:
    `corpus_sha` covers only the Layer B/C corpus, and the four fields that would differ
    (`taxonomy_sha`, `taxonomy_arm`, `n_scenarios`, `n_sinks`) are exactly the ones a treatment
    is EXPECTED to move, so they are whitelisted out of the drift check. A stale
    `adjudication_ab_clean_base_a.json` -- fitted on the 21,915-turn pool that no longer
    exists, and sitting in artifacts/ right now -- versus a freshly-run rescued arm would then
    read as a treatment effect while being a corpus diff. These fields are NOT whitelisted,
    so that comparison shouts.

    `members_sha` and `rescue` are deliberately excluded: those are the treatment.
    """
    ident = (tax_art.get("identity") or {})
    return {f"tax_{k}": v for k, v in ident.items()
            if k not in ("members_sha", "rescue")}


def run_identity(corpus: str, taxonomy: str, tax_arm: str, scenario_map: dict,
                 tuning, width: int, placebo_from: str, tax_art: dict | None = None,
                 segment: str = "s0", admit: str = "a0", router: str = "r0") -> dict:
    """Everything that must match for two artifacts to be comparable at all.

    Thresholds are recorded, not assumed: edit `milestone_relevance_percentile` between two
    arms and every count moves while both corpus and taxonomy hashes stay byte-identical.

    *** `segment` / `admit` / `router` ARE RECORDED FOR THE SAME REASON THE TAXONOMY IS. ***
    Without them two Layer B permutations over one taxonomy would compare as "identical
    corpus, identical taxonomy, no drift" -- the silent "no effect with zero calls" failure
    this instrument already carries a guard against. `corpus_sha` cannot catch it either:
    it hashes the EXTRACTED PAIRS, so it does move when S or A moves, but it is identical
    for two arms that differ only in the router.
    """
    lb, lc = tuning.layer_b, tuning.layer_c
    return {
        **taxonomy_provenance(tax_art or {}),
        "corpus_sha": corpus, "taxonomy_sha": taxonomy, "taxonomy_arm": tax_arm,
        "segment": segment, "admit": admit, "router": router,
        "n_scenarios": sum(1 for v in scenario_map.values() if v["is_coachable"]),
        "n_sinks": sum(1 for v in scenario_map.values() if not v["is_coachable"]),
        "embed": f"gemini-embedding-2@{width}", "placebo_volume_from": placebo_from or "",
        "scenario_vector_mode": tuning.layer_a.scenario_vector_mode,
        "relative_margin": lb.relative_margin,
        "max_scenarios_per_pair": lb.max_scenarios_per_pair,
        "milestone_relevance_percentile": lc.milestone_relevance_percentile,
        "min_milestone_call_fraction": lc.min_milestone_call_fraction,
        "min_milestone_calls_floor": lc.min_milestone_calls_floor,
        "min_cluster_size_fraction": lc.min_cluster_size_fraction,
        "min_cluster_size_floor": lc.min_cluster_size_floor,
        "min_cluster_size_ceiling": lc.min_cluster_size_ceiling,
        "umap_n_components": lc.umap_n_components,
        "milestone_hard_cap": lc.milestone_hard_cap,
    }


def match_milestones(base_ms: list[dict], arm_ms: list[dict], base_calls: int,
                     arm_calls: int, arm_pool: set[str] | None = None,
                     arm_pool_prefilter: set[str] | None = None) -> tuple[list, list]:
    """Clause-set overlap matching between two arms' milestones for the SAME cluster.

    FOUR OUTCOMES. `split` is separated from `lost` because fragmented evidence still survives,
    and `merged` is separated from `matched` because mapping each base milestone to its best arm
    cluster INDEPENDENTLY is blind to several base milestones landing in the SAME arm cluster --
    a destructive collapse of N distinct moves into one, even though each individually clears
    the majority-overlap bar.

    `available_frac` IS THE ADDITION THIS HARNESS NEEDS AND THE SINK REPLAY DID NOT. There,
    the arm's pool was a strict SUPERSET of baseline's, so every base clause existed in the arm
    and a miss could only mean reclustering. Here the taxonomies differ, so a base clause may
    not be in this scenario's arm pool AT ALL -- its pair was routed elsewhere. Reporting a
    reroute as clustering damage would blame the wrong stage.

    IT IS MEASURED AGAINST BOTH POOLS, because "not here" has TWO causes and the docstring at
    the top of this file says they must not be conflated:
      `available_frac_prefilter` -- against every clause Layer B routed to this scenario.
          LOW means the pair went somewhere else entirely: a LAYER B reroute.
      `available_frac`           -- against the pool that survived the p40 relevance cut.
          HIGH prefilter but LOW post means the clause WAS routed here and this arm's own
          cutoff dropped it: a LAYER C relevance change, caused by the description moving.
    Measuring only against the post-filter pool cannot separate the two, and the pre-filter
    list is not recoverable from the artifact afterwards, so it is persisted.

    Support is a FRACTION of each arm's own scenario call count. An arm whose scenario gained
    calls has a larger denominator, so raw support is not comparable across arms.
    """
    arm_sets = [set(m["clauses"]) for m in arm_ms]

    per_base = []
    claims: dict[int, list[int]] = {}
    for bi, b in enumerate(base_ms):
        bset = set(b["clauses"])
        if not bset:
            per_base.append(None)
            continue
        overlaps = [len(bset & a) for a in arm_sets]
        best = int(np.argmax(overlaps)) if overlaps else -1
        best_frac = (overlaps[best] / len(bset)) if overlaps else 0.0
        total_frac = (sum(overlaps) / len(bset)) if overlaps else 0.0
        avail = (len(bset & arm_pool) / len(bset)) if arm_pool is not None else None
        avail_pre = (len(bset & arm_pool_prefilter) / len(bset)
                     if arm_pool_prefilter is not None else None)
        per_base.append((bset, overlaps, best, best_frac, total_frac, avail, avail_pre))
        if best_frac > MATCH_MAJORITY:
            claims.setdefault(best, []).append(bi)

    merged_arm_idx = {idx for idx, bis in claims.items() if len(bis) > 1}

    outcomes = []
    for bi, b in enumerate(base_ms):
        entry = per_base[bi]
        if entry is None:
            continue
        bset, overlaps, best, best_frac, total_frac, avail, avail_pre = entry
        base_frac = (b["support_calls"] / base_calls) if base_calls else None
        row = {"base_support": b["support_calls"], "base_support_frac": base_frac,
               "available_frac": avail, "available_frac_prefilter": avail_pre,
               "clauses": b["clauses"][:3]}
        if best_frac > MATCH_MAJORITY:
            row.update({
                "outcome": "merged" if best in merged_arm_idx else "matched",
                "arm_support": arm_ms[best]["support_calls"],
                "arm_support_frac": (arm_ms[best]["support_calls"] / arm_calls
                                     if arm_calls else None),
                "n_base_in_same_cluster": len(claims[best])})
        elif total_frac > MATCH_MAJORITY:
            row.update({"outcome": "split",
                        "n_fragments": sum(1 for o in overlaps if o > 0)})
        else:
            row.update({"outcome": "lost"})
        outcomes.append(row)

    claimed = set(claims)
    gained = [{"support_calls": m["support_calls"],
               "support_frac": (m["support_calls"] / arm_calls) if arm_calls else None,
               "clauses": m["clauses"][:3]}
              for i, m in enumerate(arm_ms) if i not in claimed]
    return outcomes, gained


def distribution_stats(per_scenario: dict, floor: int) -> dict:
    """The PRIMARY metrics, computed over one arm alone -- no cross-arm join required.

    *** "SCENARIOS CLEARING THE FLOOR" IS ONE OBSERVATION, NOT THREE, AND IS REPORTED AS ONE.
    *** The spec asks for three things -- scenarios with zero milestones, scenarios that fall
    through to the V1 fallback, and scenarios clearing `min_milestone_calls_floor`. On real
    data these are IDENTICALLY THE SAME NUMBER, and printing them as three columns would look
    like three corroborating results from one measurement: the "a metric that only counts the
    good outcome" defect this repo has already paid for twice.

    The proof is in `pass1`: a candidate survives iff `support_calls >= required`, and
    `required = max(floor, ceil(fraction * calls)) >= floor`, so EVERY surviving milestone
    clears the floor by construction; and `outcome == "clustered"` iff at least one survived.
    Hence cleared == n_scenarios - zero == n_scenarios - fell_back, always.

    That does not make the metric wrong -- it is exactly what the spec means by the product
    win ("below that floor a scenario gets no clustered milestones and falls through to the V1
    Gemma free-text fallback"). It makes it ONE number, so `scenarios_with_clustered_rubric`
    is the name it is reported under, with the fallback reasons broken out for diagnosis.
    """
    ms_counts, supports, zero = [], [], 0
    reasons: Counter = Counter()
    for s in per_scenario.values():
        n = len(s["milestones"])
        ms_counts.append(n)
        if n == 0:
            zero += 1
        if s["outcome"] != "clustered":
            reasons[s["outcome"]] += 1
        supports.extend(m["support_calls"] for m in s["milestones"])

    def pct(v, q):
        return float(np.percentile(v, q)) if v else float("nan")

    return {
        "n_scenarios": len(per_scenario), "n_milestones": int(sum(ms_counts)),
        "milestones_per_scenario_mean": float(np.mean(ms_counts)) if ms_counts else 0.0,
        "milestones_per_scenario_median": float(np.median(ms_counts)) if ms_counts else 0.0,
        "scenarios_with_clustered_rubric": len(per_scenario) - zero,
        "scenarios_no_clustered_rubric": zero,
        "fallback_reasons": dict(reasons), "floor": floor,
        "support_calls_mean": float(np.mean(supports)) if supports else 0.0,
        "support_calls_median": float(np.median(supports)) if supports else 0.0,
        "support_calls_p25": pct(supports, 25), "support_calls_p75": pct(supports, 75),
        "support_calls_min": int(min(supports)) if supports else 0,
        "support_calls_max": int(max(supports)) if supports else 0,
    }


def routing_stats(pairs: list[dict], scenario_map: dict,
                  margins: list[float] | None = None) -> dict:
    """Layer B secondary metrics. Reported because they say WHETHER the treatment reached
    Layer C at all -- a null milestone result with identical routing means the description
    never moved, which is a different finding from "the rescue does not help".

    ABSORPTION IS REPORTED TWICE, and the coachable-only figure is the one that answers the
    spec's question. The largest SINK absorbs an order of magnitude more pairs than any real
    scenario (the cleaned rescued arm's biggest sink holds 819 turns), so a whole-map "max
    absorption" is a fact about the junk bucket, not about whether one real scenario is
    swallowing the corpus.

    `margins` is the top1-top2 cosine gap per pair -- the spec's third secondary metric.
    CLAUDE.md records it as ~0.01 in BOTH taxonomies, i.e. every assignment in this pipeline
    rests on the winner beating the runner-up by a hair. If the rescue widens that, it is a
    real result independent of any milestone count, which is why it must be captured in the
    SAME run rather than added later: Layer C's cross-process UMAP nondeterminism means a
    re-run to add one column would move every milestone number alongside it.
    """
    by_key = Counter(p["scenario_key"] for p in pairs)
    sink = sum(n for k, n in by_key.items() if not scenario_map[k]["is_coachable"])
    widths = Counter(len(p.get("scenario_keys") or []) for p in pairs)
    coach = Counter({k: v for k, v in by_key.items()
                     if scenario_map[k]["is_coachable"]})
    top, top_c = by_key.most_common(5), coach.most_common(5)
    n = len(pairs) or 1
    nc = sum(coach.values()) or 1
    out = {"n_pairs": len(pairs), "pairs_to_sink": sink, "sink_share": sink / n,
           "distinct_scenarios_used": len(by_key),
           "match_width": {str(k): v for k, v in sorted(widths.items())},
           "top5_absorption": [(k, c, c / n) for k, c in top],
           "max_absorption_share": (top[0][1] / n) if top else 0.0,
           "top5_absorption_coachable": [(k, c, c / nc) for k, c in top_c],
           "max_absorption_coachable": (top_c[0][1] / nc) if top_c else 0.0}
    if margins:
        m = np.asarray(margins, dtype=np.float64)
        out["margin_mean"] = float(m.mean())
        out.update({f"margin_p{q}": float(np.percentile(m, q))
                    for q in (10, 25, 50, 75, 90)})
    return out


def top1_top2_margins(trigger_vecs, scenario_map: dict) -> list[float]:
    """Per-pair cosine gap between the best and second-best scenario.

    Recomputed here rather than returned from `assign_scenarios`, deliberately: touching a
    production signature to instrument it is how a measurement changes the thing it measures.
    The vectors are the same ones assign_scenarios used (both come from the shimmed, cache-only
    embedder and `build_scenario_vecs` resolves the same `scenario_vector_mode`), so this is
    free and cannot diverge in content -- only in that it is read-only.
    """
    from shared.scenario_vectors import build_scenario_vecs

    if len(scenario_map) < 2:
        return []
    _, svecs = build_scenario_vecs(scenario_map)
    T = np.asarray(trigger_vecs, dtype=np.float32)
    S = np.asarray(svecs, dtype=np.float32)
    T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-10
    S /= np.linalg.norm(S, axis=1, keepdims=True) + 1e-10
    sims = T @ S.T
    part = np.partition(sims, -2, axis=1)
    return (part[:, -1] - part[:, -2]).tolist()


def f4_band(n_scenarios: int) -> tuple[float, float]:
    """Pre-registered sanity band, SCALED to this taxonomy's scenario count.

    F4 was written as ~[350, 450] milestones, which is production's 404 over 85 coachable
    scenarios. This taxonomy has ~30, so the raw band would void every run for a reason that
    has nothing to do with the clustering reproducing. Scaled per scenario, and deliberately
    wide (0.5x-2x) because turn-mode scenarios are far larger than production's and may well
    carry more milestones each -- a band tight enough to be exciting would be a guess.
    """
    mid = PROD_MILESTONES_PER_SCENARIO * n_scenarios
    return 0.5 * mid, 2.0 * mid


# ---------------------------------------------------------------------------------------
# embedding: the gemini gateway cache, read-only, with ONE bounded prewarm
# ---------------------------------------------------------------------------------------

def _load_cached(texts: list[str], width: int):
    from calibration.trial_pool_unit_gemini import CACHE, _key
    import sqlite3

    if not texts:
        return np.empty((0, width), dtype=np.float32), []
    conn = sqlite3.connect(f"file:{CACHE.as_posix()}?mode=ro", uri=True)
    have: dict[str, np.ndarray] = {}
    try:
        keys = [_key(t) for t in texts]
        for i in range(0, len(keys), 900):
            chunk = keys[i:i + 900]
            q = ",".join("?" * len(chunk))
            for k, blob in conn.execute(f"SELECT k, v FROM vec WHERE k IN ({q})", chunk):
                have[k] = np.frombuffer(blob, dtype=np.float32)
    finally:
        conn.close()
    missing = [t for t, k in zip(texts, keys) if k not in have]
    if missing:
        return None, missing
    mat = np.stack([have[k] for k in keys])
    if width != mat.shape[1]:
        # Matryoshka truncation, then RENORMALISE -- cutting a unit vector's tail leaves
        # ||v|| < 1 and every downstream dot product silently stops being a cosine.
        mat = mat[:, :width]
    n = np.linalg.norm(mat, axis=1, keepdims=True)
    return (mat / (n + 1e-10)).astype(np.float32), []


def prewarm(texts: list[str], workers: int) -> None:
    """The ONE place this harness is allowed to spend, and it is bounded by construction.

    Scenario descriptions are freshly written by each adjudication run, so they are misses by
    definition -- ~250 per arm. Everything else (triggers, response clauses) was backfilled
    deliberately by scope_layer_bc_embeddings.py --fetch and is served cache-only, so an
    unexpected miss ABORTS rather than quietly turning a free run into a paid one.
    """
    from calibration.trial_pool_unit_gemini import embed_cached
    uniq = sorted(set(texts))
    print(f"[prewarm] {len(uniq)} distinct scenario text(s)", flush=True)
    embed_cached(uniq, workers)


def install_embedder_shim(width: int) -> dict:
    """Serve every production embedder call from the gemini gateway cache.

    WHY A SHIM RATHER THAN `embedder.set_backend("gemini")`. That switch exists and is the
    right tool for comparing backends -- but its gemini path is the DIRECT Google AI Studio
    API (1k requests/day) writing into production's `embed_cache.db` under a different key
    scheme. This trial's 28,697 response-clause vectors were paid for through the JOVEO
    GATEWAY into `gemini_embed_cache.db`. Pointing production at the other backend would
    re-pay for all of them at 1k/day.

    WHY ONE VECTOR SERVES BOTH embed_query AND embed_document. On gemini-embedding-2 the
    task_type is INERT -- all four values return byte-identical vectors, cosine 1.0000
    (measured 2026-08-13, recorded in preprocessing/embedder.py). That is exactly why the
    gateway cache is keyed without a prefix. *** THIS WOULD BE WRONG ON bge ***, whose
    embed_query genuinely prepends an instruction prefix and returns a different vector, so
    this shim must never be reused for a local-backend run.
    """
    from preprocessing import embedder

    calls = {"query": 0, "document": 0, "texts": 0}

    def _matrix(texts: list[str]) -> np.ndarray:
        calls["texts"] += len(texts)
        mat, missing = _load_cached(list(texts), width)
        if mat is None:
            raise SystemExit(
                f"ABORT: {len(missing)} text(s) are not in the gemini cache, e.g. "
                f"{missing[:2]!r}. This run would have SPENT. Warm the cache deliberately "
                f"with calibration/scope_layer_bc_embeddings.py --fetch, never as a side "
                f"effect of a measurement.")
        return mat

    def embed_query_matrix(texts):
        calls["query"] += 1
        return _matrix(texts)

    def embed_document_matrix(texts):
        calls["document"] += 1
        return _matrix(texts)

    embedder.embed_query_matrix = embed_query_matrix
    embedder.embed_document_matrix = embed_document_matrix
    embedder.embed_query = lambda t: embed_query_matrix(t).tolist()
    embedder.embed_document = lambda t: embed_document_matrix(t).tolist()
    return calls


# ---------------------------------------------------------------------------------------
# corpus
# ---------------------------------------------------------------------------------------

def parse_corpus(recordings: str) -> list:
    """[(n, path, turns)] over the sorted corpus, using production's parser and arguments.

    Split out of `build_pairs` so the membership routers can be handed the SAME parse the
    pairs were built from instead of re-deriving one. That matters beyond speed: R1's pool
    join is (call_filename, turn.index) -> pool index, and a second parse that classified one
    speaker differently would shift every later turn index. Passing the object through makes
    the two provably the same object rather than provably the same code.

    `build_pairs` still parses for itself when nothing is passed, so the r0 path is exactly
    what it was.
    """
    from config import load_config
    from preprocessing.transcript_parser import parse_transcript, load_roster

    cfg = load_config()
    files = sorted(Path(recordings).glob("*.txt"))
    if not files:
        raise SystemExit(f"no transcripts in {recordings}/")
    parsed = []
    for n, path in enumerate(files, 1):
        parsed.append((n, path, parse_transcript(
            str(path), cfg.joveo_speakers_lower, cfg.naren_name_lower,
            roster=load_roster(str(path)))))
        if n % 100 == 0 or n == len(files):
            print(f"  parsed {n}/{len(files)} calls", flush=True)
    return parsed


def build_pairs(recordings: str, segment: str = "s0", admit: str = "a0",
                parsed: list | None = None) -> list[dict]:
    """Production entry points, production arguments, PER CALL.

    Concatenating transcripts pairs a trigger at the end of one call with a response at the
    start of the next; a scratchpad re-implementation of the parse disagreed with production
    by ~20% twice (spaCy component set moves sentence boundaries; a missing Avoma roster
    misclassifies speakers). Import production code; never paraphrase it.

    *** AT THE CONTROL SETTING THIS CALLS PRODUCTION ITSELF, NOT THE VARIANT. *** The S and A
    knobs vary the interior of `extract_pairs`, so a knob arm has to go through
    `layer_b_variants.extract_pairs_variant`. But the CONTROL must not: routing the control
    through a paraphrase would mean the whole trial rests on that paraphrase being right,
    with no independent check. Calling production directly at (s0, a0) makes the control an
    external reference, and `layer_b_variants.verify_equivalence()` -- 393 transcripts,
    field-for-field, 0 mismatches -- is what connects the two.
    """
    from v1.layer_b import extract_pairs

    control = (segment == "s0" and admit == "a0")
    if not control:
        from calibration.layer_b_variants import extract_pairs_variant, derive_alpha_floors

    if parsed is None:
        parsed = parse_corpus(recordings)

    floors = None
    if admit == "a3":
        # Derived from THIS corpus so a3 admits the same fraction production does -- volume
        # neutrality by construction, which is why a3 alone needs no placebo.
        floors = derive_alpha_floors([t for _, _, t in parsed],
                                     target_client=A3_TARGET_CLIENT,
                                     target_naren=A3_TARGET_NAREN)
        print(f"  [a3] corpus-derived alphabetic-token floors: {floors}", flush=True)

    pairs: list[dict] = []
    for n, path, turns in parsed:
        got = (extract_pairs(turns, n) if control
               else extract_pairs_variant(turns, n, segment, admit, floors))
        for p in got:
            p["call_filename"] = path.name
            p["pair_id"] = f"{path.stem}:{p['turn_index']}"
        pairs.extend(got)
    print(f"  extracted {len(pairs)} pairs (segment={segment} admit={admit}"
          f"{' -- PRODUCTION extract_pairs' if control else ''})", flush=True)
    return pairs


# ---------------------------------------------------------------------------------------
# Layer C Pass 1 -- production functions, never reimplemented
# ---------------------------------------------------------------------------------------

def pass1(info: dict, responses: list[dict], tuning,
          scenario_calls_override: int | None = None) -> dict:
    """One scenario's Layer C Pass 1, importing v2/layer_c's own functions.

    Mirrors `_pass1_cluster_scenario` minus its DB writes and checkpoint, which are the only
    parts that cannot run here. The early-exit thresholds (<2 responses, <6 clauses) are
    production's and are reproduced as OUTCOMES rather than silently returning empty -- a
    scenario that falls through to the V1 Gemma fallback is a different finding from one that
    clustered zero milestones, and the spec asks for both.

    *** THESE ARE PRE-JUDGE COUNTS. *** Production computes each candidate's `sink_similarity`
    here and then drops the flagged ones in Pass 2 via a Gemma call. That judge cannot run in a
    Gemma-free harness, so counts here are an upper bound on production's final milestone set.
    `replay_layer_c_admitted` has the same property; it is harmless for an A/B because the
    omission is identical in every arm, but it means a count from this harness must never be
    compared against a number produced by a full pipeline run.

    *** `scenario_calls_override` EXISTS FOR THE PLACEBO AND NOTHING ELSE. *** The support gate
    is `required = max(floor, ceil(fraction * scenario_calls))`, and `scenario_calls` is derived
    from the responses. Placebo donors are drawn one pair at a time from ~2,400 pairs spread
    over 351 calls, so almost every donor contributes a NEW distinct call: padding a 60-call
    scenario with ~60 donor pairs pushes it to ~115 calls and DOUBLES `required` from 6 to 12.
    The treatment reaches the same clause volume through genuine rerouting, which grows calls
    far less (measured base->rescued: 96 -> 133, +39%), so it faces a much lower bar. The
    placebo would then lose milestones for a reason that is neither volume nor content -- and
    the bias runs IN FAVOUR OF THE TREATMENT, i.e. it would flatter the very thing the placebo
    exists to check. Forcing the placebo's denominator to the treatment's makes clause volume
    AND the support gate identical, leaving content as the only difference. That is what a
    placebo is.
    """
    from preprocessing import embedder
    from shared import cluster_evidence
    from v2.layer_c import build_clause_pool, _relevance_filter, _cluster_milestones

    out = {"n_responses": len(responses), "milestones": [], "outcome": None,
           "scenario_calls": len({r["call_filename"] for r in responses}),
           "scenario_calls_used": None,
           "n_clauses": 0, "n_clauses_after_relevance": 0,
           "clause_pool": [], "clause_pool_prefilter": []}
    if len(responses) < 2:
        out["outcome"] = "fallback_too_few_responses"
        return out

    clauses, positions, calls, pair_ids = build_clause_pool(responses)
    out["n_clauses"] = len(clauses)
    # PRE-filter, so --compare can tell a Layer B REROUTE (the clause is not in this
    # scenario's pool at all) from a Layer C RELEVANCE CUT (it is, but this arm's own p40
    # cutoff dropped it -- a different description means a different cutoff). Comparing only
    # against the post-filter pool conflates the two channels the module docstring says must
    # be kept apart, and the pre-filter list cannot be recovered from the artifact afterwards.
    out["clause_pool_prefilter"] = list(clauses)
    if len(clauses) < 6:
        out["outcome"] = "fallback_too_few_clauses"
        return out

    scenario_calls = (out["scenario_calls"] if scenario_calls_override is None
                      else scenario_calls_override)
    out["scenario_calls_used"] = scenario_calls
    vecs = embedder.embed_document_matrix(clauses)
    clauses, vecs, positions, calls, pair_ids, relevance = _relevance_filter(
        clauses, vecs, positions, calls, pair_ids, info,
        tuning.milestone_relevance_percentile)
    out["n_clauses_after_relevance"] = len(clauses)
    out["clause_pool"] = clauses
    if len(clauses) < 6:
        out["outcome"] = "fallback_too_few_relevant"
        return out

    mcs = cluster_evidence.milestone_min_cluster_size(
        len(clauses), tuning.min_cluster_size_fraction,
        tuning.min_cluster_size_floor, tuning.min_cluster_size_ceiling)
    labels = _cluster_milestones(vecs, mcs, tuning.umap_n_components)

    groups: dict[int, dict] = {}
    for i, label in enumerate(labels):
        if label == -1:
            continue
        g = groups.setdefault(int(label), {"clauses": [], "positions": [], "calls": []})
        g["clauses"].append(clauses[i])
        g["positions"].append(positions[i])
        g["calls"].append(calls[i])
    if not groups:
        out["outcome"] = "fallback_no_clusters"
        return out

    required = cluster_evidence.required_milestone_support(
        scenario_calls, tuning.min_milestone_call_fraction, tuning.min_milestone_calls_floor)
    out["required_support"] = required

    # `support_call_files` is WHICH calls, not just how many. Added 2026-08-16 for the Layer B
    # trial's account-diversity metric: `support_calls` is a COUNT, and 9 calls from nine
    # different clients and 9 calls from one client are the same number. That difference is the
    # documented product defect (RTX 98%, Banfield 100%), and it is not recoverable from any
    # artifact written before this field existed -- hence the three published arms being re-run.
    # Sorted so the artifact is byte-stable across runs; deduplicated because support is
    # DISTINCT calls, matching `support_calls` exactly.
    surviving = [
        {"cluster_id": label, "clauses": g["clauses"],
         "support_calls": len(set(g["calls"])), "support_clauses": len(g["clauses"]),
         "support_call_files": sorted(set(g["calls"])),
         "support_frac": len(set(g["calls"])) / max(scenario_calls, 1),
         "median_position": float(np.median(g["positions"])),
         "relevance_mean": float(np.mean([relevance[c] for c in g["clauses"]]))}
        for label, g in groups.items() if len(set(g["calls"])) >= required
    ]
    if not surviving:
        out["outcome"] = "fallback_no_support"
        return out

    if len(surviving) > tuning.milestone_hard_cap:
        print(f"  !! HARD CAP BOUND: {len(surviving)} > {tuning.milestone_hard_cap}. The "
              f"support floor is miscalibrated; the cap is not meant to fire.", flush=True)
        surviving.sort(key=lambda c: (-c["support_calls"], -c["relevance_mean"]))
        surviving = surviving[:tuning.milestone_hard_cap]

    out["outcome"] = "clustered"
    out["milestones"] = sorted(surviving, key=lambda m: m["median_position"])
    return out


def placebo_pad(scenario_key: str, wanted: int, by_key: dict[str, list[dict]],
                rng: random.Random) -> list[dict]:
    """Clause-count-matched donor responses drawn from OTHER coachable scenarios.

    Real responses from real calls, so the distinct-call support gate behaves normally -- the
    only thing deliberately wrong about them is the topic. This is what separates "the rescue
    found better content" from "a bigger pool reclusters differently", and without it a loss
    count cannot be read at all.
    """
    from v2.layer_c import build_clause_pool

    if wanted <= 0:
        return []
    donors = [p for k, ps in by_key.items() if k != scenario_key for p in ps]
    if not donors:
        return []
    rng.shuffle(donors)
    picked, total = [], 0
    for p in donors:
        picked.append(p)
        total += len(build_clause_pool([p])[0])
        if total >= wanted:
            break
    return picked


# ---------------------------------------------------------------------------------------
# run one arm
# ---------------------------------------------------------------------------------------

def run_arm(a) -> None:
    from shared.tuning import load_tuning
    from shared.scenario_vectors import scenario_text
    from calibration.layer_b_routers import (assign_scenarios_router, build_router_context,
                                             report_router)

    out_path = paths(a.arm)
    if out_path.exists() and not a.overwrite:
        raise SystemExit(f"{out_path.name} already exists. Pass --overwrite to replace it, or "
                         f"choose a different --arm. Refusing to clobber a measured artifact.")

    tax = taxonomy_path(a.taxonomy)
    if not tax.exists():
        raise SystemExit(f"taxonomy artifact {tax.name} not found -- run "
                         f"calibration/adjudication_ab.py --arm {a.taxonomy} first")
    tax_art = json.loads(tax.read_text(encoding="utf-8-sig"))
    if tax_art.get("incomplete"):
        raise SystemExit(f"{tax.name} is stamped INCOMPLETE (failures or --limit). An arm "
                         f"built on a partial taxonomy is not comparable to one that is not.")

    scenario_map, cluster_of_key = scenario_map_from_rows(tax_art["rows"])
    coachable = {k: v for k, v in scenario_map.items() if v["is_coachable"]}
    print(f"[taxonomy] {a.taxonomy}: {len(coachable)} coachable + "
          f"{len(scenario_map) - len(coachable)} sink(s)", flush=True)
    if not coachable:
        raise SystemExit("taxonomy has no coachable scenarios -- nothing to measure")

    tuning = load_tuning()
    # r0 takes EXACTLY the path it took before the routers existed -- no pre-parse, no
    # clustering rebuild -- so the control arm is byte-identical to the published one.
    parsed = None if a.router == "r0" else parse_corpus(a.recordings)
    pairs = build_pairs(a.recordings, a.segment, a.admit, parsed=parsed)
    print(f"[corpus] {len(pairs)} pairs over "
          f"{len({p['call_filename'] for p in pairs})} calls", flush=True)

    # BEFORE the prewarm, deliberately: the context build verifies the pool join and the
    # membership hash, and a failure there must abort while the run is still free.
    ctx = build_router_context(a.router, tax_art["rows"], parsed, scenario_map,
                               recordings=a.recordings,
                               taxonomy_identity=tax_art.get("identity") or {},
                               segment=a.segment, width=a.width)

    # Spend FIRST, deliberately and visibly, then make every later lookup cache-only.
    if not a.no_prewarm:
        prewarm([scenario_text(v) for v in scenario_map.values()], a.workers)
    calls = install_embedder_shim(a.width)

    ident = run_identity(corpus_sha(pairs), taxonomy_sha(scenario_map), a.taxonomy,
                         scenario_map, tuning, a.width,
                         a.volume_from if a.placebo else "", tax_art,
                         a.segment, a.admit, a.router)

    t0 = time.time()
    print(f"\n[layer B] routing {len(pairs)} pairs with {a.router} "
          f"(scenario_vector_mode={tuning.layer_a.scenario_vector_mode})...", flush=True)
    trigger_vecs = assign_scenarios_router(pairs, scenario_map, a.router, ctx)
    report_router(ctx.diag)
    # The margin stays measured in the DESCRIPTION space for every arm. It is a diagnostic
    # (spec §3.10: margins rank nothing), and holding the space fixed is what keeps the
    # number comparable across routers -- a per-router space would report four incomparable
    # columns under one heading. It is unchanged for r0.
    routing = routing_stats(pairs, scenario_map,
                            top1_top2_margins(trigger_vecs, scenario_map))
    print(f"[layer B] {routing['pairs_to_sink']}/{routing['n_pairs']} pairs to a sink "
          f"({routing['sink_share']*100:.1f}%), {routing['distinct_scenarios_used']} scenarios "
          f"used, max coachable absorption "
          f"{routing['max_absorption_coachable']*100:.1f}%", flush=True)
    print(f"[layer B] top1-top2 margin: "
          + "  ".join(f"p{q}={routing.get(f'margin_p{q}', float('nan')):.4f}"
                      for q in (10, 25, 50, 75, 90)), flush=True)

    by_key: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        if p["scenario_key"] and scenario_map[p["scenario_key"]]["is_coachable"]:
            by_key[p["scenario_key"]].append(p)

    volume_target: dict[str, int] = {}
    if a.placebo:
        volume_target = _placebo_targets(a.volume_from, cluster_of_key)
        print(f"[placebo] volume targets loaded for {len(volume_target)} cluster(s) from "
              f"{a.volume_from}", flush=True)

    rng = random.Random(a.seed)
    per_scenario: dict[str, dict] = {}
    todo = sorted(coachable.items())
    if a.limit:
        todo = todo[:a.limit]
        print(f"--limit {a.limit}: PATH TEST ONLY -- alphabetical prefix, not a sample; "
              f"artifact stamped incomplete", flush=True)
    print(f"\n[layer C] Pass 1 over {len(todo)} coachable scenario(s), Gemma-free...",
          flush=True)
    for n, (key, info) in enumerate(todo, 1):
        responses = by_key.get(key, [])
        padded, override = 0, None
        if a.placebo:
            tgt = volume_target.get(cluster_of_key.get(key, "")) or {}
            have = sum(len(_clauses_of(p)) for p in responses)
            extra = placebo_pad(key, tgt.get("clauses", 0) - have, by_key, rng)
            padded = len(extra)
            responses = responses + extra
            # Match the treatment's support DENOMINATOR too, not just its clause volume.
            override = tgt.get("scenario_calls") or None
        res = pass1(info, responses, tuning.layer_c, scenario_calls_override=override)
        # The pools are what --compare's available_frac reads. Truncating them (an earlier
        # version capped the post-filter pool at 4000) silently turns "clause not stored" into
        # "clause was rerouted", and it would bite hardest on the largest scenarios -- exactly
        # the ones the rescue moves most. Assert completeness rather than trusting it.
        assert len(res["clause_pool"]) == res["n_clauses_after_relevance"], (
            f"{key}: clause_pool truncated ({len(res['clause_pool'])} vs "
            f"{res['n_clauses_after_relevance']}) -- available_frac would be wrong")
        assert len(res["clause_pool_prefilter"]) == res["n_clauses"], (
            f"{key}: prefilter pool truncated -- the Layer B/Layer C attribution would be wrong")
        res["n_padded_responses"] = padded
        res["cluster_id"] = cluster_of_key.get(key, "")
        res["n_pairs"] = len(by_key.get(key, []))
        per_scenario[key] = res
        print(f"  [{n}/{len(todo)}] {key[:44]:<44} {res['n_pairs']:>4}p "
              f"{res['n_clauses']:>5}cl -> {len(res['milestones']):>2} ms  "
              f"({res['outcome']})", flush=True)

    stats = distribution_stats(per_scenario, tuning.layer_c.min_milestone_calls_floor)
    lo, hi = f4_band(stats["n_scenarios"])
    report_arm(a.arm, stats, routing, (lo, hi), time.time() - t0, calls)

    out_path.write_text(json.dumps({
        "arm": a.arm, "taxonomy_arm": a.taxonomy, "placebo": bool(a.placebo),
        "limit": a.limit or None, "incomplete": bool(a.limit),
        "volume_from": a.volume_from or None, "identity": ident,
        "chat_calls": 0, "embed_calls": calls, "seed": a.seed,
        "f4_band": [lo, hi], "f4_pass": lo <= stats["n_milestones"] <= hi,
        "stats": stats, "routing": routing, "router_diag": ctx.diag,
        "cluster_of_key": cluster_of_key,
        "per_scenario": {k: _thin(v) for k, v in per_scenario.items()},
    }, indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {out_path}")
    print("ZERO chat calls were made. NOTHING was written to Postgres.")


def _clauses_of(pair: dict) -> list[str]:
    from v2.layer_c import build_clause_pool
    return build_clause_pool([pair])[0]


def _placebo_targets(volume_from: str, cluster_of_key: dict) -> dict[str, dict]:
    """Per-CLUSTER clause volume AND call count from the arm being matched, by cluster_id.

    BOTH are needed. Matching only the clause volume leaves the support gate free to move,
    because donors drag in new distinct calls and `required` scales with them -- see pass1's
    `scenario_calls_override` note. A placebo that faces a harder gate than the treatment
    controls for nothing and biases the read toward the treatment.

    Keyed on cluster_id and not scenario_key for the reason every join here is: Gemma renames
    a cluster per run, so the treatment's key for a cluster is usually not this arm's key.
    """
    src = paths(volume_from)
    if not src.exists():
        raise SystemExit(f"--placebo needs --volume-from an arm that has already run; "
                         f"{src.name} does not exist")
    art = json.loads(src.read_text(encoding="utf-8-sig"))
    if art.get("placebo"):
        raise SystemExit(f"--volume-from {volume_from!r} is itself a placebo; matching a "
                         f"placebo's volume controls for nothing.")
    out: dict[str, dict] = {}
    for key, s in art["per_scenario"].items():
        cid = s.get("cluster_id") or art.get("cluster_of_key", {}).get(key, "")
        if cid:
            out[cid] = {"clauses": int(s.get("n_clauses", 0)),
                        "scenario_calls": int(s.get("scenario_calls", 0))}
    return out


def _thin(s: dict) -> dict:
    """The per-scenario record as it goes to disk. The clause pool is kept IN FULL.

    An earlier version truncated it to the first 4000 clauses to keep artifacts small. That is
    a correctness bug, not a size optimisation: `available_frac` asks whether a base
    milestone's clauses exist ANYWHERE in the other arm's pool, so a clause sitting at index
    4001 would read as ABSENT -- and absent means REROUTED, the one conclusion this field
    exists to support. The largest scenarios here carry several thousand post-relevance
    clauses, so the truncation would have fired on exactly the scenarios that matter most.
    Whole-pool artifacts run a few MB; the adjudication checkpoints in this same directory are
    16MB, so this is not the place to economise.
    """
    return dict(s)


def report_arm(arm, s, routing, band, secs, calls) -> None:
    lo, hi = band
    print("\n" + "=" * 80)
    print(f"ARM {arm}")
    print("=" * 80)
    print(f"  coachable scenarios          {s['n_scenarios']}")
    print(f"  TOTAL milestones             {s['n_milestones']}")
    print(f"  milestones/scenario mean|med {s['milestones_per_scenario_mean']:.2f} | "
          f"{s['milestones_per_scenario_median']:.1f}")
    print(f"  scenarios WITH a clustered rubric  {s['scenarios_with_clustered_rubric']}"
          f"   <- the product win. Identical to 'clears the floor {s['floor']}' and to "
          f"'did not fall back', by construction -- ONE number, not three.")
    print(f"  scenarios with NONE (-> V1 fallback){s['scenarios_no_clustered_rubric']:>4}")
    for reason, n in sorted(s["fallback_reasons"].items(), key=lambda x: -x[1]):
        print(f"      {reason:<34}{n:>4}")
    print(f"  support_calls med|p25|p75    {s['support_calls_median']:.1f} | "
          f"{s['support_calls_p25']:.1f} | {s['support_calls_p75']:.1f}"
          f"   (min {s['support_calls_min']}, max {s['support_calls_max']})")
    print(f"  layer B: sink share          {routing['sink_share']*100:.1f}%   "
          f"max absorption {routing['max_absorption_share']*100:.1f}%")
    if not (lo <= s["n_milestones"] <= hi):
        print(f"\n  !! F4: {s['n_milestones']} milestones is OUTSIDE the scaled band "
              f"[{lo:.0f}, {hi:.0f}] (production's {PROD_MILESTONES_PER_SCENARIO:.2f}/scenario "
              f"x {s['n_scenarios']}, 0.5x-2x). The clustering may not have reproduced.")
    if s["n_scenarios"] < 20:
        print(f"\n  !! F3: only {s['n_scenarios']} scenarios -- the spec's floor is 20. "
              f"Unrankable, not comparable.")
    print(f"\n  {secs/60:.1f} min, {calls['texts']} texts embedded (all cache hits), "
          f"0 chat calls")


# ---------------------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------------------

def compare(names: list[str]) -> None:
    arts = {}
    for n in names:
        p = paths(n)
        if not p.exists():
            raise SystemExit(f"missing artifact for arm {n!r} ({p.name})")
        arts[n] = json.loads(p.read_text(encoding="utf-8-sig"))

    # `run_arm` refuses an incomplete TAXONOMY but nothing refused an incomplete ARM, and
    # --limit arms are exactly what a router smoke test leaves lying in artifacts/. An
    # alphabetical prefix is not a sample (CLAUDE.md), so every per-scenario number below is
    # drawn from one end of the alphabet. Warned rather than refused: comparing two path tests
    # to check the plumbing is legitimate, believing them is not.
    incomplete = [n for n in names if arts[n].get("incomplete")]
    if incomplete:
        print(f"\n  !! {incomplete} are stamped INCOMPLETE (--limit). Their Layer C columns "
              f"cover an ALPHABETICAL PREFIX, not a sample. Routing columns are full-corpus "
              f"and readable; nothing per-scenario is.")

    print("\n" + "=" * 104)
    print("LAYER B/C ARMS -- DOES THE RESCUE REACH A RUBRIC?")
    print("=" * 104)
    # ONE column for the product win, not three. `zero`, `fallback` and `clears floor` are
    # provably the same number (see distribution_stats), and three columns of one observation
    # read as three corroborating results.
    # S/A/R IS PRINTED, because it is the treatment. Two arms differing only in the router
    # have the same taxonomy name and the same corpus hash, so without this column the table
    # reads as one arm run twice -- and the drift check stays silent by design, `segment` /
    # `admit` / `router` being exactly the fields a treatment is allowed to move.
    print(f"  {'arm':<12}{'taxonomy':<18}{'S/A/R':<10}{'scen':>6}{'miles':>7}{'per-scen':>10}"
          f"{'w/ rubric':>11}{'none':>6}{'supp med':>10}{'top1-2 p50':>12}"
          f"{'sink%':>8}{'maxabs%':>9}")
    for n in names:
        s, r = arts[n]["stats"], arts[n]["routing"]
        i = arts[n]["identity"]
        sar = f"{i.get('segment') or '?'}/{i.get('admit') or '?'}/{i.get('router') or '?'}"
        print(f"  {n:<12}{arts[n]['taxonomy_arm']:<18}{sar:<10}{s['n_scenarios']:>6}"
              f"{s['n_milestones']:>7}{s['milestones_per_scenario_mean']:>10.2f}"
              f"{s['scenarios_with_clustered_rubric']:>11}"
              f"{s['scenarios_no_clustered_rubric']:>6}{s['support_calls_median']:>10.1f}"
              f"{r.get('margin_p50', float('nan')):>12.4f}"
              f"{r['sink_share']*100:>7.1f}%"
              f"{r.get('max_absorption_coachable', float('nan'))*100:>8.1f}%")

    # Identity drift, on EVERY field. corpus_sha alone would not notice a threshold edit
    # between two arms, and taxonomy_sha alone would not notice a corpus change.
    ref_name = names[0]
    ref = arts[ref_name]["identity"]
    print(f"\n  identity of {ref_name}: corpus={ref['corpus_sha']} taxonomy={ref['taxonomy_sha']}")
    for n in names[1:]:
        other = arts[n]["identity"]
        drift = {k: (ref.get(k), other.get(k)) for k in set(ref) | set(other)
                 if ref.get(k) != other.get(k)}
        # ONLY what the treatment is allowed to move. Everything else -- including every
        # `tax_*` field describing the adjudication run the taxonomy came from -- must match,
        # or the arms are not comparable. `tax_n_clusters` differing means the two taxonomies
        # were fitted on different pools, which no amount of downstream care can repair.
        # ONLY what a treatment is allowed to move. `segment`/`admit`/`router` join the list
        # because the Layer B trial's treatment IS one of them -- but `corpus_sha` stays OUT,
        # so an arm that changes S or A still declares the pair population it produced and two
        # arms cannot silently disagree about the corpus underneath.
        expected = {"taxonomy_sha", "taxonomy_arm", "n_scenarios", "n_sinks",
                    "placebo_volume_from", "segment", "admit", "router"}
        unexpected = {k: v for k, v in drift.items() if k not in expected}
        if unexpected:
            print(f"  !! {ref_name} vs {n}: IDENTITY DIFFERS BEYOND THE TREATMENT -> "
                  f"{unexpected}\n     These arms are NOT comparable; something other than "
                  f"the taxonomy moved.")
        # A DIFFERENT corpus_sha IS THE TREATMENT when S or A moved -- those knobs change which
        # pairs exist, so the hash MUST differ and saying "nothing below is readable" would be
        # false. It is still fatal when the extraction settings match, because then the two
        # arms disagree about a corpus they were supposed to share.
        same_extraction = (ref.get("segment") == other.get("segment")
                           and ref.get("admit") == other.get("admit"))
        if drift.get("corpus_sha"):
            if same_extraction:
                print(f"  !! {n} ran over a DIFFERENT CORPUS with the SAME extraction "
                      f"settings. Nothing below is readable.")
            else:
                print(f"  -- {n}: pair population differs, as expected for "
                      f"segment={other.get('segment')} admit={other.get('admit')}.")

    # *** A NOISE-FLOOR PAIR MUST SHARE THE TREATMENT TOO, NOT JUST THE TAXONOMY. ***
    # This originally tested `taxonomy_sha` alone, which was right while the taxonomy was the
    # only knob. With S/A/R it is not: two arms over ONE taxonomy differing only in the router
    # share the taxonomy hash exactly, so they were being labelled NOISE FLOOR and the router's
    # entire effect would have been read as UMAP re-launch variance -- the same shape as
    # `measure_scoring_noise` reporting a floor computed from two blended runs.
    def _same_arm(a, b):
        ia, ib = arts[a]["identity"], arts[b]["identity"]
        return (all(ia.get(k) == ib.get(k)
                    for k in ("taxonomy_sha", "segment", "admit", "router"))
                and not arts[a]["placebo"] and not arts[b]["placebo"])

    floor_pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]
                   if _same_arm(a, b)]
    print(f"\n  NOISE-FLOOR pairs (same taxonomy AND same S/A/R, so any difference is UMAP "
          f"re-launch variance): {floor_pairs or 'NONE -- the treatment cannot be read'}")

    print("\n  PER-CLUSTER MILESTONE OUTCOMES (joined on cluster_id, never scenario_key)")
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            tag = ("NOISE FLOOR" if _same_arm(a, b) else
                   "PLACEBO" if arts[a]["placebo"] or arts[b]["placebo"] else "TREATMENT")
            d = compare_arms(arts[a], arts[b])
            print(f"\n  {a} -> {b}   [{tag}]")
            print(f"    clusters coachable in BOTH {d['n_shared']}   "
                  f"only-{a} {d['n_only_a']}   only-{b} {d['n_only_b']}")
            print(f"    matched {d['matched']}  merged {d['merged']}  split {d['split']}  "
                  f"lost {d['lost']}  gained {d['gained']}")
            print(f"    of the LOST, share of clauses {b} still has:")
            print(f"       routed to this scenario at all (pre-filter): "
                  f"{d['lost_available_prefilter_mean']:.0%}"
                  f"   <- LOW = LAYER B REROUTE")
            print(f"       surviving its own p40 relevance cut       : "
                  f"{d['lost_available_mean']:.0%}"
                  f"   <- high pre / low here = LAYER C relevance shift;"
                  f" both high = RECLUSTERED")
            print(f"    support frac delta, MATCHED only {d['support_frac_delta_mean']:+.3f}  "
                  f"(thickened {d['thickened']} / thinned {d['thinned']})")
            if d["merged"]:
                print(f"    support frac delta, MERGED only  "
                      f"{d['merged_support_frac_delta_mean']:+.3f}   <- reported SEPARATELY: a "
                      f"fusion has the largest support by construction, so mixing it into the "
                      f"line above manufactures 'evidence thickening'")
            if d["merged"]:
                print(f"    !! {d['merged']} base milestone(s) collapsed into a shared arm "
                      f"cluster -- READ THEM; distinct coaching moves may have been fused.")

    print("\n  A TREATMENT row must be read against the NOISE FLOOR row above it, and a gain "
          "\n  against the PLACEBO. If the treatment sits inside either, the rescue does not "
          "\n  reach the rubrics -- which the spec pre-registered as a publishable result.")


def compare_arms(a_art: dict, b_art: dict) -> dict:
    """Join two arms on cluster_id and run merge-aware milestone matching per shared cluster."""
    a_by_cid = {s["cluster_id"]: (k, s) for k, s in a_art["per_scenario"].items()
                if s.get("cluster_id")}
    b_by_cid = {s["cluster_id"]: (k, s) for k, s in b_art["per_scenario"].items()
                if s.get("cluster_id")}
    shared = sorted(set(a_by_cid) & set(b_by_cid))

    tally = Counter()
    # SEPARATE populations, deliberately. A destructive N->1 fusion has, by construction, the
    # largest support of any cluster, so folding `merged` rows into the support delta puts
    # every merge in the "thickened" column -- which reproduces the exact "evidence
    # thickening" reading that check_milestone_thickening.py falsified. Keep them apart.
    deltas, merged_deltas, gained = [], [], 0
    avail_post, avail_pre = [], []
    for cid in shared:
        _, sa = a_by_cid[cid]
        _, sb = b_by_cid[cid]
        outcomes, new = match_milestones(
            sa["milestones"], sb["milestones"],
            sa.get("scenario_calls", 0), sb.get("scenario_calls", 0),
            arm_pool=set(sb.get("clause_pool") or []),
            arm_pool_prefilter=set(sb.get("clause_pool_prefilter") or []))
        gained += len(new)
        for o in outcomes:
            tally[o["outcome"]] += 1
            if o["outcome"] == "lost":
                if o.get("available_frac") is not None:
                    avail_post.append(o["available_frac"])
                if o.get("available_frac_prefilter") is not None:
                    avail_pre.append(o["available_frac_prefilter"])
            d = (None if o.get("arm_support_frac") is None
                 or o.get("base_support_frac") is None
                 else o["arm_support_frac"] - o["base_support_frac"])
            if d is not None:
                (merged_deltas if o["outcome"] == "merged" else deltas).append(d)

    return {"n_shared": len(shared),
            "n_only_a": len(set(a_by_cid) - set(b_by_cid)),
            "n_only_b": len(set(b_by_cid) - set(a_by_cid)),
            "matched": tally["matched"], "merged": tally["merged"],
            "split": tally["split"], "lost": tally["lost"], "gained": gained,
            "lost_available_mean": float(np.mean(avail_post)) if avail_post else float("nan"),
            "lost_available_prefilter_mean": (float(np.mean(avail_pre)) if avail_pre
                                              else float("nan")),
            "support_frac_delta_mean": float(np.mean(deltas)) if deltas else 0.0,
            "merged_support_frac_delta_mean": (float(np.mean(merged_deltas))
                                               if merged_deltas else 0.0),
            "thickened": sum(1 for d in deltas if d > 0),
            "thinned": sum(1 for d in deltas if d < 0)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arm", default="", help="arm name; required to run. Names its own file.")
    p.add_argument("--taxonomy", default="",
                   help="adjudication_ab_<name>.json to take the scenario map from")
    p.add_argument("--recordings", default="recordings")
    # ONE value each, and no multi-arm loop exists: two permutations can never share a
    # process, a random state, or an artifact. Defaults ARE production, so omitting them
    # reproduces the published behaviour exactly.
    p.add_argument("--segment", default="s0", choices=("s0", "s1"),
                   help="s0 production (one client turn) | s1 client MOVE (merged run)")
    p.add_argument("--admit", default="a0", choices=("a0", "a1", "a3", "a4"),
                   help="a0 production | a1 no trigger floor | a4 no RESPONSE floor | "
                        "a3 corpus-percentile floor, no stoplist")
    p.add_argument("--router", default="r0",
                   choices=("r0", "r1", "r2", "r3", "r1p", "r2p", "r3p"),
                   help="r0 production description matching | r1 Layer A membership lookup "
                        "(HYBRID: ~47%% of the pool is HDBSCAN noise and falls back to r0, "
                        "and the split is printed) | r2 out-of-fold scenario centroid | "
                        "r3 0.75*centroid + 0.25*description. r1/r2/r3 rebuild the "
                        "taxonomy's own clustering cache-only and refuse to run unless it "
                        "hashes to the taxonomy artifact's members_sha.")
    p.add_argument("--width", type=int, default=EMBED_WIDTH,
                   help="analysis width, truncated+renormalised from the cached 3072")
    p.add_argument("--workers", type=int, default=20, help="prewarm concurrency")
    p.add_argument("--no-prewarm", action="store_true",
                   help="skip the scenario-text fetch; every lookup then aborts on a miss")
    p.add_argument("--placebo", action="store_true",
                   help="pad each scenario's response pool with topically WRONG donors to "
                        "match --volume-from's clause volume")
    p.add_argument("--volume-from", default="", help="arm whose per-cluster clause volume the "
                                                     "placebo matches")
    p.add_argument("--seed", type=int, default=42, help="placebo donor shuffle seed")
    p.add_argument("--limit", type=int, default=0,
                   help="PATH TEST ONLY: cap the coachable scenarios processed. Marks the "
                        "artifact incomplete so it can never be compared. Alphabetical order "
                        "is not a sample -- see CLAUDE.md.")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--compare", default="", help="comma-separated arm names to compare")
    a = p.parse_args()

    if a.compare:
        compare([s.strip() for s in a.compare.split(",") if s.strip()])
    elif a.arm:
        if not a.taxonomy:
            raise SystemExit("--taxonomy is required: an arm IS a taxonomy, and defaulting it "
                             "would let two arms silently share one.")
        if a.placebo and not a.volume_from:
            raise SystemExit("--placebo requires --volume-from; a placebo that matches no "
                             "arm's volume controls for nothing.")
        run_arm(a)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
