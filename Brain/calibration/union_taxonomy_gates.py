#!/usr/bin/env python3
"""UNION TAXONOMY REBUILD — Stage D: the four frozen taxonomy gates. ALL FREE of chat.

Spec: docs/superpowers/specs/2026-08-18-union-taxonomy-rebuild-design.md §5 (frozen — the
bars below were fixed before any Stage A byte moved and are never adjusted after a
result):

  G-R1  cohesion vs random null (PRIMARY, comparative). Per coachable scenario: mean
        pairwise cosine of member turns vs 200 size-matched random draws from the UNION
        pool; a scenario passes iff its cohesion exceeds the draws' p95. The IDENTICAL
        procedure runs on the new map and on clean2_base (same pool, same seed rule).
        GATE: pass-rate(new) >= pass-rate(clean2_base).
  G-R2  sink rate. Union pairs routed with production assign_scenarios (concat) against
        the new map. GATE: new-corpus pair sink share <= 59.3%; companion: old-corpus
        sink share <= 62.9%.
  G-R3  stranding. GATE: >= 90% of coachable scenarios have >= 10 routed pairs spanning
        >= 3 account domains (merged + sibling-collapsed account map).
  G-R4  blinded scenario-coherence read. 12 coachable scenarios (seeded, stratified by
        routed pairs 4/4/4), 8 member turns each, + 6 scrambled negatives (>= 4 source
        scenarios each). 3 blinded sonnet readers, one at a time; reader VALID iff
        >= 5/6 negatives rejected; scenario coherent iff >= 2/3 valid readers YES.
        GATE: >= 9/12 coherent.

CLEAN2_BASE MEMBERSHIPS WERE NEVER PERSISTED (its arms ran after the pool moved under
the bench sidecar), so G-R1's reference side needs `--stage base-members` first: a
seed-42 refit of the old 20,788-turn pool, verified POSITION-FOR-POSITION against the
published `adjudication_ab_clean2_base.json` rows (cluster_id, n_items, calls, keywords —
the roster-repair verification precedent). A mismatch VOIDS G-R1 as designed; stop and
bring the operator the options, never substitute a different reference.

Index identity: the union pool's old block leads (union index i == old-pool index i for
i < 20,788), asserted here via the T0 artifact's `old_prefix_sha` before any clean2_base
membership is mapped onto union vectors.

Processes: `--stage base-members` owns one UMAP fit; everything else fits nothing.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/union_taxonomy_gates.py --stage base-members
    ..\\.venv\\Scripts\\python.exe calibration/union_taxonomy_gates.py --g1
    ..\\.venv\\Scripts\\python.exe calibration/union_taxonomy_gates.py --g2g3
    ..\\.venv\\Scripts\\python.exe calibration/union_taxonomy_gates.py --g4-build
    # (3 blinded sonnet readers write artifacts/union_gates_judgments_r*.json, ONE AT A TIME)
    ..\\.venv\\Scripts\\python.exe calibration/union_taxonomy_gates.py --g4-score
    ..\\.venv\\Scripts\\python.exe calibration/union_taxonomy_gates.py --report
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

SEED = 42
NEW_TAXONOMY = "union_rescued"
BASE_TAXONOMY = "clean2_base"
UNION_CLUSTERS = ARTIFACTS_DIR / "union_clusters.json"

N_DRAWS = 200                  # G-R1 null draws per scenario (frozen)
G1_PCTL = 95                   # pass iff cohesion > this percentile of the draws
G2_NEW_MAX = 0.593             # frozen: 64.3% measured under clean2_base, minus 5pp
G2_OLD_MAX = 0.629             # frozen: published 57.9% + 5pp collapse guard
G3_MIN_PAIRS = 10
G3_MIN_DOMAINS = 3
G3_SHARE = 0.90
G4_N_SCENARIOS = 12            # 4 per routed-pair tercile
G4_PER_STRATUM = 4
G4_TURNS_SHOWN = 8
G4_N_NEG = 6
G4_NEG_MIN_SOURCES = 4
G4_NEG_REJECT_MIN = 5          # reader VALID iff >= 5/6 negatives rejected
G4_N_VALID_READERS = 3
G4_COHERENT_MIN = 9            # gate: >= 9/12 scenarios coherent

BASE_MEMBERS_OUT = ARTIFACTS_DIR / "union_gates_base_members.json"
G1_OUT = ARTIFACTS_DIR / "union_gates_g1.json"
G23_OUT = ARTIFACTS_DIR / "union_gates_g2g3.json"
G4_PACKET = ARTIFACTS_DIR / "union_gates_read_packet.txt"
G4_KEY = ARTIFACTS_DIR / "union_gates_read_KEY.json"
G4_JUDGMENTS_GLOB = "union_gates_judgments_*.json"
G4_OUT = ARTIFACTS_DIR / "union_gates_g4.json"
REPORT_OUT = ARTIFACTS_DIR / "union_gates_report.json"

# Which arm's map these gates score. "rescued" is the primary (spec §4); "base" is the
# operator-chosen fallback arm (2026-08-18, after G-R4 failed 8/12 on rescued — the
# exact choice §1 pre-registered). The membership key, the taxonomy artifact, and
# EVERY output path swing together so a base run can never clobber or read a rescued
# artifact. `union_gates_base_members.json` (the clean2_base reference reconstruction)
# is shared deliberately — the G-R1 reference side is arm-independent.
MEMBERSHIP = "rescued"


def set_arm(arm: str) -> None:
    global MEMBERSHIP, NEW_TAXONOMY, G1_OUT, G23_OUT, G4_PACKET, G4_KEY, \
        G4_JUDGMENTS_GLOB, G4_OUT, REPORT_OUT
    if arm not in ("rescued", "base"):
        raise SystemExit(f"--arm must be rescued|base, got {arm!r}")
    MEMBERSHIP = arm
    NEW_TAXONOMY = f"union_{arm}"
    pre = "" if arm == "rescued" else "fallback_"
    G1_OUT = ARTIFACTS_DIR / f"union_gates_{pre}g1.json"
    G23_OUT = ARTIFACTS_DIR / f"union_gates_{pre}g2g3.json"
    G4_PACKET = ARTIFACTS_DIR / f"union_gates_{pre}read_packet.txt"
    G4_KEY = ARTIFACTS_DIR / f"union_gates_{pre}read_KEY.json"
    G4_JUDGMENTS_GLOB = f"union_gates_{pre}judgments_*.json"
    G4_OUT = ARTIFACTS_DIR / f"union_gates_{pre}g4.json"
    REPORT_OUT = ARTIFACTS_DIR / f"union_gates_{pre}report.json"


# ---------------------------------------------------------------------------------------
# pure helpers (covered by tests/test_union_taxonomy_gates.py)
# ---------------------------------------------------------------------------------------

def mean_pairwise_cosine(unit_rows: np.ndarray) -> float:
    """Mean pairwise cosine over all DISTINCT pairs (diagonal excluded), via the
    sum-vector identity: for unit rows, sum_{i!=j} v_i.v_j = ||sum||^2 - n. Exact, and
    O(n*d) instead of O(n^2*d) — G-R1 runs this on clusters of thousands of turns."""
    n = len(unit_rows)
    if n < 2:
        return float("nan")
    s = unit_rows.sum(axis=0)
    return float((s @ s - n) / (n * (n - 1)))


def g1_scenario(member_vecs: np.ndarray, pool_vecs: np.ndarray,
                n_draws: int = N_DRAWS, seed: int = SEED) -> dict:
    """One scenario's cohesion-vs-null row. The rng is seeded on (seed, n) so the null
    draws depend only on the scenario's SIZE — identical for equal sizes across both
    maps and independent of processing order, which is what 'the identical procedure on
    both maps' requires."""
    n = len(member_vecs)
    rng = np.random.default_rng(np.random.SeedSequence([seed, n]))
    obs = mean_pairwise_cosine(member_vecs)
    draws = np.empty(n_draws)
    for d in range(n_draws):
        idx = rng.choice(len(pool_vecs), size=n, replace=False)
        draws[d] = mean_pairwise_cosine(pool_vecs[idx])
    p95 = float(np.percentile(draws, G1_PCTL))
    return {"n": n, "cohesion": obs, "null_p95": p95, "null_mean": float(draws.mean()),
            "pass": bool(obs > p95)}


def g1_gate(rows_new: dict, rows_base: dict) -> dict:
    """GATE: pass-rate(new map) >= pass-rate(clean2_base)."""
    def rate(rows):
        return (sum(1 for r in rows.values() if r["pass"]) / len(rows)) if rows else float("nan")
    rn, rb = rate(rows_new), rate(rows_base)
    return {"pass_rate_new": rn, "pass_rate_base": rb,
            "n_new": len(rows_new), "n_base": len(rows_base),
            "pass": bool(rn >= rb)}


def g2_verdict(shares: dict) -> dict:
    """`shares` is sink_share_by_origin's output over the union routing."""
    new_share = shares["new"]["sink_share"]
    old_share = shares["old"]["sink_share"]
    return {"new_sink_share": new_share, "new_max": G2_NEW_MAX,
            "new_ok": bool(new_share <= G2_NEW_MAX),
            "old_sink_share": old_share, "old_max": G2_OLD_MAX,
            "old_ok": bool(old_share <= G2_OLD_MAX),
            "pass": bool(new_share <= G2_NEW_MAX and old_share <= G2_OLD_MAX)}


def g3_rows(pair_counts: dict[str, int], domain_sets: dict[str, set]) -> list[dict]:
    """Per coachable scenario: routed-pair count and distinct account domains. The
    domain count runs over the ACCOUNTED subset (calls with no roster account are
    excluded from every concentration denominator in this repo, never pooled)."""
    return [{"scenario": k, "routed_pairs": pair_counts.get(k, 0),
             "domains": len(domain_sets.get(k, set())),
             "ok": bool(pair_counts.get(k, 0) >= G3_MIN_PAIRS
                        and len(domain_sets.get(k, set())) >= G3_MIN_DOMAINS)}
            for k in sorted(pair_counts)]


def g3_verdict(rows: list[dict]) -> dict:
    ok = sum(1 for r in rows if r["ok"])
    share = ok / len(rows) if rows else float("nan")
    return {"n_scenarios": len(rows), "n_ok": ok, "share": share,
            "below_floor": [r["scenario"] for r in rows if not r["ok"]],
            "pass": bool(rows) and bool(share >= G3_SHARE)}


def stratified_pick(counts: dict[str, int], rng: random.Random,
                    per_stratum: int = G4_PER_STRATUM) -> list[str]:
    """G-R4's sample: scenarios ranked by routed pairs (desc, ties ascending key),
    split into terciles by np.array_split (the remainder goes to the FIRST strata in
    rank order — np.array_split semantics), `per_stratum` sampled from each with the
    seeded rng."""
    order = sorted(counts, key=lambda k: (-counts[k], k))
    if len(order) < 3 * per_stratum:
        raise SystemExit(f"only {len(order)} coachable scenarios — the 4/4/4 stratified "
                         f"sample needs at least {3 * per_stratum}")
    strata = [list(s) for s in np.array_split(np.array(order, dtype=object), 3)]
    picked: list[str] = []
    for s in strata:
        picked.extend(rng.sample(list(s), per_stratum))
    return picked


def build_scramble(memberships: dict[str, list[int]], rng: random.Random,
                   n_turns: int = G4_TURNS_SHOWN,
                   min_sources: int = G4_NEG_MIN_SOURCES) -> list[int]:
    """One scrambled negative: `n_turns` member turns drawn round-robin from
    `min_sources` DIFFERENT scenarios. The negative's whole job is to be rejectable by a
    reader who is actually reading, so the sources are forced distinct."""
    keys = sorted(k for k, v in memberships.items() if len(v) >= 2)
    if len(keys) < min_sources:
        raise SystemExit(f"only {len(keys)} scenarios with >= 2 member turns — cannot "
                         f"build a {min_sources}-source negative")
    srcs = rng.sample(keys, min_sources)
    out: list[int] = []
    si = 0
    while len(out) < n_turns:
        pool = [i for i in memberships[srcs[si % len(srcs)]] if i not in out]
        if pool:
            out.append(rng.choice(pool))
        si += 1
        if si > 10 * n_turns:                    # all sources exhausted
            break
    if len(out) < n_turns:
        raise SystemExit(f"scramble came up short ({len(out)}/{n_turns} turns) — source "
                         f"scenarios too thin; a short negative would be trivially "
                         f"rejectable and bias reader validity")
    return out


def g4_reader_valid(items: dict, key_items: list[dict]) -> tuple[bool, str]:
    """VALID iff every item is answered YES/NO AND >= 5/6 negatives answered NO."""
    rejected = total_neg = 0
    for row in key_items:
        ans = str(items.get(str(row["item"]), "")).upper()
        if ans not in ("YES", "NO"):
            return False, f"item {row['item']} unanswered or not YES/NO"
        if row["kind"] == "NEG":
            total_neg += 1
            rejected += ans == "NO"
    if rejected < G4_NEG_REJECT_MIN:
        return False, f"rejected only {rejected}/{total_neg} negatives"
    return True, f"rejected {rejected}/{total_neg} negatives"


def g4_score(key: dict, judgments: list[dict]) -> dict:
    """Duplicate-reader guard + validity + the coherence tally (valid readers in file
    order until 3, the snap-trial discipline).

    Identity duplication is a HARD error. Payload identity is a recorded FLAG rather
    than an error, deliberately deviating from the snap trial's guard: these payloads
    are 18 binary YES/NO answers, and two honest strict readers can plausibly agree on
    all 18 (the snap trial's payloads carried choices + per-move rating lists, where a
    byte collision really did mean a duplicated dispatch). The flag keeps the tell on
    the record for the outcome audit without voiding a legitimate run.
    """
    names = [jd["reader"] for jd in judgments]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate reader identity among judgment files: {names}")
    payloads = [json.dumps(jd["items"], sort_keys=True) for jd in judgments]
    payload_dup = len(set(payloads)) != len(payloads)
    if payload_dup:
        print("!! two judgment files carry byte-identical answers — plausible for 18 "
              "binary items, but ON THE RECORD for the outcome audit.")
    validity, valid = {}, []
    for jd in judgments:
        ok, why = g4_reader_valid(jd["items"], key["items"])
        validity[jd["reader"]] = {"valid": ok, "why": why}
        if ok and len(valid) < G4_N_VALID_READERS:
            valid.append(jd)
    if len(valid) < G4_N_VALID_READERS:
        return {"verdict": "VOID",
                "reason": f"only {len(valid)} valid readers (< {G4_N_VALID_READERS})",
                "payload_duplicate_flag": payload_dup,
                "validity": validity}
    per_scenario = {}
    for row in key["items"]:
        if row["kind"] != "REAL":
            continue
        yes = sum(1 for jd in valid
                  if str(jd["items"].get(str(row["item"]), "")).upper() == "YES")
        per_scenario[row["scenario"]] = {"yes_votes": yes, "coherent": yes >= 2}
    n_coh = sum(1 for r in per_scenario.values() if r["coherent"])
    return {"validity": validity,
            "payload_duplicate_flag": payload_dup,
            "valid_readers": [jd["reader"] for jd in valid],
            "per_scenario": per_scenario,
            "n_coherent": n_coh, "n_scenarios": len(per_scenario),
            "gate_min": G4_COHERENT_MIN,
            "pass": bool(n_coh >= G4_COHERENT_MIN)}


def scenario_memberships(scenario_map: dict, cluster_of_key: dict[str, str],
                         clusters_by_id: dict[str, list[int]],
                         coachable_only: bool = True) -> dict[str, list[int]]:
    """scenario_key -> member turn indices, joined on the STABLE cluster_id (never the
    loop index — Gemma renames keys per run, sizes reorder ranks). Every coachable
    scenario must resolve; a silent drop would shrink the very population a gate scores."""
    out: dict[str, list[int]] = {}
    for key, info in scenario_map.items():
        if coachable_only and not info["is_coachable"]:
            continue
        cid = cluster_of_key.get(key, "")
        if cid not in clusters_by_id:
            raise SystemExit(f"scenario {key!r}: cluster_id {cid!r} not in the persisted "
                             f"clustering — join broken; nothing reportable")
        out[key] = clusters_by_id[cid]
    return out


# ---------------------------------------------------------------------------------------
# shared loaders
# ---------------------------------------------------------------------------------------

def _refuse(p: Path) -> None:
    if p.exists():
        raise SystemExit(f"{p.name} already exists — refusing to clobber a measured "
                         f"artifact")


def _ident(extra: dict) -> dict:
    return {"started_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "pid": os.getpid(), "seed": SEED, **extra}


def _union_pool_and_vecs():
    from calibration.union_pool_fetch import load_t0, _rebuild_and_check
    from calibration.routing_bench import embed_cache_only

    man = load_t0()
    texts, call_ids, old_stems = _rebuild_and_check(man)
    vecs = embed_cache_only(texts)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    return man, texts, call_ids, old_stems, vecs


def _tax_rows(name: str) -> dict:
    from calibration.layer_bc_arms import taxonomy_path

    p = taxonomy_path(name)
    if not p.exists():
        raise SystemExit(f"taxonomy artifact {p.name} not found")
    art = json.loads(p.read_text(encoding="utf-8-sig"))
    if art.get("limit"):
        raise SystemExit(f"{p.name} was a --limit path test; not a taxonomy")
    return art


def _new_map_memberships() -> tuple[dict, dict, dict[str, list[int]]]:
    """(scenario_map, cluster_of_key, coachable memberships) for the map under test —
    the arm's own membership set, i.e. the set that arm's adjudication ran on."""
    from calibration.layer_bc_arms import scenario_map_from_rows

    art = _tax_rows(NEW_TAXONOMY)
    uc = json.loads(UNION_CLUSTERS.read_text(encoding="utf-8-sig"))
    clusters_by_id = {c["cluster_id"]: [int(i) for i in c[f"idxs_{MEMBERSHIP}"]]
                      for c in uc["clusters"]}
    scenario_map, cluster_of_key = scenario_map_from_rows(art["rows"])
    members = scenario_memberships(scenario_map, cluster_of_key, clusters_by_id)
    return scenario_map, cluster_of_key, members


# ---------------------------------------------------------------------------------------
# --stage base-members: the ONE fit in this harness
# ---------------------------------------------------------------------------------------

def stage_base_members() -> None:
    _refuse(BASE_MEMBERS_OUT)
    from shared.tuning import load_tuning
    from v2.layer_a import fit_topic_model
    from calibration.routing_bench import build_pool, embed_cache_only
    from calibration.adjudication_ab import derive_clusters, pool_sha
    from calibration.union_pool_fetch import T0_EXPECTED_OLD_TURNS

    texts, call_ids = build_pool("recordings")
    if len(texts) != T0_EXPECTED_OLD_TURNS:
        raise SystemExit(f"old pool is {len(texts)} turns, not the audited "
                         f"{T0_EXPECTED_OLD_TURNS} — parse regression; VOID")
    vecs = embed_cache_only(texts)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    ta = load_tuning().layer_a
    print("[fit] reconstructing clean2_base's clustering (seed-42, ONE fit)...", flush=True)
    tm, topics = fit_topic_model(texts, vecs, min_cluster_size=16)
    clusters = derive_clusters(texts, call_ids, vecs, len(set(call_ids)),
                               tm, np.array(topics), ta)

    rows = _tax_rows(BASE_TAXONOMY)["rows"]
    if len(clusters) != len(rows):
        raise SystemExit(f"REFIT MISMATCH: {len(clusters)} clusters vs clean2_base's "
                         f"{len(rows)} rows. The seed-42 refit did not reproduce the "
                         f"published clustering; G-R1 is VOID as designed — stop and "
                         f"bring the operator the fallback options.")
    bad = []
    for i, (c, r) in enumerate(zip(clusters, rows)):
        if (c["cluster_id"] != r["cluster_id"] or c["stats"].n_items != r["n_items"]
                or c["stats"].distinct_calls != r["calls"]
                or c["keywords"] != r["keywords"]):
            bad.append(i)
    if bad:
        raise SystemExit(f"REFIT MISMATCH at positions {bad[:10]} (of {len(bad)}): the "
                         f"refit is not the published clean2_base clustering "
                         f"position-for-position. G-R1 VOID — operator decision needed.")
    print(f"[verify] {len(clusters)}/{len(rows)} clusters identical to clean2_base "
          f"(cluster_id, n_items, calls, keywords)")

    BASE_MEMBERS_OUT.write_text(json.dumps({
        "identity": _ident({"taxonomy": BASE_TAXONOMY,
                            "pool_sha_old": pool_sha(texts),
                            "n_turns": len(texts),
                            "verified_positions": len(clusters)}),
        "clusters": [{"cluster_id": c["cluster_id"],
                      "idxs": sorted(map(int, c["idxs"]))} for c in clusters],
    }, indent=1), encoding="utf-8")
    print(f"wrote {BASE_MEMBERS_OUT.name}")
    print("UNION BASE-MEMBERS COMPLETE", flush=True)


# ---------------------------------------------------------------------------------------
# --g1
# ---------------------------------------------------------------------------------------

def stage_g1() -> None:
    _refuse(G1_OUT)
    from calibration.layer_bc_arms import scenario_map_from_rows

    man, texts, call_ids, old_stems, vecs = _union_pool_and_vecs()

    # New map, rescued memberships (indices are union-pool indices already).
    _, _, members_new = _new_map_memberships()

    # clean2_base memberships live in old-pool indices; the old block leads the union
    # pool, so index i maps to i — PROVED via the prefix sha, not assumed.
    if not BASE_MEMBERS_OUT.exists():
        raise SystemExit("run --stage base-members first")
    bm = json.loads(BASE_MEMBERS_OUT.read_text(encoding="utf-8-sig"))
    if bm["identity"]["pool_sha_old"] != man["old_prefix_sha"]:
        raise SystemExit("old-pool sha != union old-prefix sha — the old block does not "
                         "lead the union pool byte-identically; index mapping VOID")
    base_by_id = {c["cluster_id"]: c["idxs"] for c in bm["clusters"]}
    base_map, base_cok = scenario_map_from_rows(_tax_rows(BASE_TAXONOMY)["rows"])
    members_base = scenario_memberships(base_map, base_cok, base_by_id)

    out = {}
    for tag, members in (("new", members_new), ("base", members_base)):
        rows = {}
        for n, (key, idxs) in enumerate(sorted(members.items()), 1):
            rows[key] = g1_scenario(vecs[idxs], vecs)
            print(f"  [{tag} {n}/{len(members)}] {key[:44]:<44} n={rows[key]['n']:>5} "
                  f"coh {rows[key]['cohesion']:.4f} vs p95 {rows[key]['null_p95']:.4f} "
                  f"-> {'PASS' if rows[key]['pass'] else 'fail'}", flush=True)
        out[tag] = rows

    gate = g1_gate(out["new"], out["base"])
    print(f"\nG-R1: new {gate['pass_rate_new']*100:.1f}% "
          f"({sum(1 for r in out['new'].values() if r['pass'])}/{gate['n_new']}) vs "
          f"clean2_base {gate['pass_rate_base']*100:.1f}% "
          f"({sum(1 for r in out['base'].values() if r['pass'])}/{gate['n_base']}) -> "
          f"{'PASS' if gate['pass'] else 'FAIL'}")
    G1_OUT.write_text(json.dumps({
        "identity": _ident({"n_draws": N_DRAWS, "pctl": G1_PCTL,
                            "pool_sha": man["pool_sha"]}),
        "gate": gate, "per_scenario": out}, indent=1, default=float), encoding="utf-8")
    print(f"wrote {G1_OUT.name}")
    print("UNION G1 COMPLETE", flush=True)


# ---------------------------------------------------------------------------------------
# --g2g3 (production routing; the ONLY embedding spend here is the scenario-text prewarm)
# ---------------------------------------------------------------------------------------

def stage_g2g3() -> None:
    _refuse(G23_OUT)
    from calibration.layer_bc_arms import (build_pairs, install_embedder_shim,
                                           parse_corpus, prewarm,
                                           scenario_map_from_rows)
    from calibration.expanded_pool_stage1 import (assert_no_stem_collision,
                                                  merge_account_maps,
                                                  sink_share_by_origin)
    from calibration.flag_proper_noun_clusters import account_map
    from calibration import layer_b_arms as lb
    from shared.scenario_vectors import scenario_text
    from v1.layer_b import assign_scenarios

    art = _tax_rows(NEW_TAXONOMY)
    t2_failed = art.get("stats", {}).get("failed", 0)
    if art.get("incomplete") and t2_failed:
        print(f"[note] taxonomy has {t2_failed} failed rows (T2 gate already ruled on the "
              f"share); failed rows are excluded from the map by construction.")
    scenario_map, _ = scenario_map_from_rows(art["rows"])
    coach_keys = sorted(k for k, v in scenario_map.items() if v["is_coachable"])
    print(f"[taxonomy] {NEW_TAXONOMY}: {len(coach_keys)} coachable + "
          f"{len(scenario_map) - len(coach_keys)} sinks")

    parsed_old = parse_corpus("recordings")
    parsed_new = parse_corpus("recordings_pull_keep")
    assert_no_stem_collision({p.stem for _, p, _ in parsed_old},
                             {p.stem for _, p, _ in parsed_new})
    pairs = (build_pairs("recordings", "s0", "a0", parsed=parsed_old)
             + build_pairs("recordings_pull_keep", "s0", "a0", parsed=parsed_new))
    new_calls = {p.name for _, p, _ in parsed_new}

    # Fresh descriptions are cache misses by definition — the ONE bounded spend here.
    prewarm([scenario_text(v) for v in scenario_map.values()], 20)
    install_embedder_shim(3072)
    print(f"[route] {len(pairs)} pairs, production assign_scenarios (concat)...",
          flush=True)
    assign_scenarios(pairs, scenario_map, None)

    shares = sink_share_by_origin(pairs, scenario_map, new_calls)
    g2 = g2_verdict(shares)
    print(f"\nG-R2: new-corpus sink {g2['new_sink_share']*100:.1f}% "
          f"(bar <= {G2_NEW_MAX*100:.1f}%) -> {'ok' if g2['new_ok'] else 'FAIL'};  "
          f"old-corpus sink {g2['old_sink_share']*100:.1f}% "
          f"(bar <= {G2_OLD_MAX*100:.1f}%) -> {'ok' if g2['old_ok'] else 'FAIL'}"
          f"   => {'PASS' if g2['pass'] else 'FAIL'}")

    acct_old, _ = account_map("recordings")
    acct_new, _ = account_map("recordings_pull_keep")
    if not acct_old or not acct_new:
        raise SystemExit("an account map came back empty — missing roster sidecars")
    acct, _ = lb.collapse_sibling_domains(merge_account_maps([acct_old, acct_new]))

    pair_counts: dict[str, int] = {k: 0 for k in coach_keys}
    domain_sets: dict[str, set] = {k: set() for k in coach_keys}
    for p in pairs:
        k = p["scenario_key"]
        if k in pair_counts:
            pair_counts[k] += 1
            dom = acct.get(Path(p["call_filename"]).stem)
            if dom:
                domain_sets[k].add(dom)
    rows = g3_rows(pair_counts, domain_sets)
    g3 = g3_verdict(rows)
    print(f"\nG-R3: {g3['n_ok']}/{g3['n_scenarios']} scenarios clear "
          f">= {G3_MIN_PAIRS} pairs over >= {G3_MIN_DOMAINS} domains "
          f"({g3['share']*100:.1f}%, bar {G3_SHARE*100:.0f}%) -> "
          f"{'PASS' if g3['pass'] else 'FAIL'}")
    if g3["below_floor"]:
        print("  below floor: " + ", ".join(g3["below_floor"]))

    G23_OUT.write_text(json.dumps({
        "identity": _ident({"taxonomy": NEW_TAXONOMY, "router": "production concat"}),
        "sink_by_origin": shares, "g2": g2,
        "g3": g3, "g3_rows": rows,
        "routed_pair_counts": pair_counts,
    }, indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {G23_OUT.name}")
    print("UNION G2G3 COMPLETE", flush=True)


# ---------------------------------------------------------------------------------------
# --g4-build / --g4-score
# ---------------------------------------------------------------------------------------

def stage_g4_build() -> None:
    if G4_PACKET.exists() or G4_KEY.exists():
        raise SystemExit("G4 packet / KEY already exist — a read packet is a measured "
                         "instrument; refusing to clobber")
    if not G23_OUT.exists():
        raise SystemExit("run --g2g3 first (G-R4 stratifies by routed-pair count)")

    man, texts, call_ids, old_stems, _ = _union_pool_and_vecs()
    _, _, members = _new_map_memberships()
    counts = json.loads(G23_OUT.read_text(encoding="utf-8-sig"))["routed_pair_counts"]
    if set(counts) != set(members):
        raise SystemExit("routed-count keys != membership keys — taxonomy drifted "
                         "between --g2g3 and now")

    rng = random.Random(SEED)
    picked = stratified_pick(counts, rng)
    items = [("REAL", k) for k in picked]
    for _ in range(G4_N_NEG):
        items.append(("NEG", None))
    rng.shuffle(items)

    lines = [
        "BLIND SCENARIO-COHERENCE READ.",
        "Each GROUP below is a set of client utterances from sales/CS calls that a",
        "pipeline claims belong to ONE recurring client situation.",
        "For each group answer YES if the turns hang together as one recognizable",
        "client situation a coach could train against, NO otherwise (unrelated",
        "situations fused, or glue by a name/account rather than a situation).",
        "Do not assume any particular share of YES answers. Answer EVERY group.",
        "=" * 78, ""]
    key_rows = []
    for i, (kind, scen) in enumerate(items, 1):
        if kind == "REAL":
            idxs = rng.sample(members[scen], min(G4_TURNS_SHOWN, len(members[scen])))
            key_rows.append({"item": i, "kind": "REAL", "scenario": scen,
                             "n_members": len(members[scen])})
        else:
            idxs = build_scramble(members, rng)
            key_rows.append({"item": i, "kind": "NEG"})
        lines.append(f"GROUP {i:02d}")
        for t in idxs:
            txt = " ".join(texts[t].split())
            lines.append(f"   - {txt[:300]}{'...' if len(txt) > 300 else ''}")
        lines.append("")
    lines += [
        "=" * 78,
        "REQUIRED ANSWER FORMAT — one JSON object, nothing else:",
        '{"1": "YES", "2": "NO", ...}   (every group number must appear)',
    ]
    G4_PACKET.write_text("\n".join(lines), encoding="utf-8")
    G4_KEY.write_text(json.dumps({
        "identity": _ident({"stratified_by": "routed_pair_counts (g2g3)",
                            "composition": dict(Counter(k for k, _ in items))}),
        "items": key_rows}, indent=1), encoding="utf-8")
    print(f"wrote {G4_PACKET.name} ({len(items)} groups) and {G4_KEY.name} "
          f"(readers must NEVER see the key)")
    print("UNION G4 PACKET READY", flush=True)


def stage_g4_score() -> None:
    _refuse(G4_OUT)
    key = json.loads(G4_KEY.read_text(encoding="utf-8-sig"))
    jd_files = sorted(ARTIFACTS_DIR.glob(G4_JUDGMENTS_GLOB))
    if not jd_files:
        raise SystemExit("no judgment files — dispatch blinded readers first")
    judgments = [json.loads(f.read_text(encoding="utf-8-sig")) for f in jd_files]
    print(f"[score] {len(judgments)} judgment file(s): "
          + ", ".join(f.name for f in jd_files))
    res = g4_score(key, judgments)
    if res.get("verdict") == "VOID":
        print(f"G-R4 VOID: {res['reason']}")
    else:
        print(f"G-R4: {res['n_coherent']}/{res['n_scenarios']} coherent "
              f"(gate >= {G4_COHERENT_MIN}) -> {'PASS' if res['pass'] else 'FAIL'}")
    G4_OUT.write_text(json.dumps({
        "identity": _ident({}), **res}, indent=1), encoding="utf-8")
    print(f"wrote {G4_OUT.name}")
    print("UNION G4 SCORED", flush=True)


# ---------------------------------------------------------------------------------------
# --report
# ---------------------------------------------------------------------------------------

def stage_report() -> None:
    parts = {}
    for name, p, picker in (
            ("G-R1", G1_OUT, lambda a: a["gate"]),
            ("G-R2", G23_OUT, lambda a: a["g2"]),
            ("G-R3", G23_OUT, lambda a: a["g3"]),
            ("G-R4", G4_OUT, lambda a: a)):
        if not p.exists():
            parts[name] = {"pass": None, "note": f"{p.name} missing — not run"}
            continue
        parts[name] = picker(json.loads(p.read_text(encoding="utf-8-sig")))
    print("\n" + "=" * 78)
    print("STAGE D — FROZEN TAXONOMY GATES")
    print("=" * 78)
    all_pass = True
    for name, v in parts.items():
        state = v.get("pass")
        all_pass = all_pass and bool(state)
        if v.get("verdict") == "VOID":
            label = "VOID"
        elif state is None:
            label = "NOT RUN"
        else:
            label = "PASS" if state else "FAIL"
        print(f"  {name}: {label}")
    print(f"\n  ALL GATES: {'PASS — Stage E (PV) may run' if all_pass else 'NOT PASSED'}")
    if not all_pass:
        print("  A gate failure means STOP: veto-audit if unexpected, then bring the "
              "operator the fallback options (base-clustering arm vs closing).")
    REPORT_OUT.write_text(json.dumps({
        "identity": _ident({}), "gates": parts, "all_pass": all_pass},
        indent=1, default=float), encoding="utf-8")
    print(f"wrote {REPORT_OUT.name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stage", default="", choices=("", "base-members"))
    p.add_argument("--arm", default="rescued", choices=("rescued", "base"),
                   help="which union arm's map to gate; 'base' is the operator-chosen "
                        "fallback and writes union_gates_fallback_* artifacts")
    p.add_argument("--g1", action="store_true")
    p.add_argument("--g2g3", action="store_true")
    p.add_argument("--g4-build", action="store_true")
    p.add_argument("--g4-score", action="store_true")
    p.add_argument("--report", action="store_true")
    a = p.parse_args()
    set_arm(a.arm)
    if a.stage == "base-members":
        stage_base_members()
    elif a.g1:
        stage_g1()
    elif a.g2g3:
        stage_g2g3()
    elif a.g4_build:
        stage_g4_build()
    elif a.g4_score:
        stage_g4_score()
    elif a.report:
        stage_report()
    else:
        p.print_help()


if __name__ == "__main__":
    main()
