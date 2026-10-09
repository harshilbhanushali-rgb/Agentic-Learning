#!/usr/bin/env python3
"""EXPANDED-POOL STAGE 1: was DATA the constraint? Zero chat calls, zero Postgres writes.

Spec: docs/superpowers/specs/2026-08-17-expanded-pool-stage1-design.md (gates frozen there
BEFORE this file ran). Handoff: Brain/HANDOFF_EXPANDED_POOL_2026-08-17.md.

ONE VARIABLE. The taxonomy (`clean2_base`, 26 coachable + 125 sinks) is FROZEN; segmentation,
admission, routing and Layer C Pass 1 are production functions at production settings. The only
thing that changes against the published control (`layer_bc_s0a0r0_b.json`) is the corpus:
`recordings/` (393 calls) + `recordings_pull_keep/` (690 new calls, 120 new accounts). New
calls can only JOIN existing scenarios — they cannot create one, by construction.

WHY THERE IS NO PLACEBO ARM. The treatment IS the corpus. The rev-4 metric this stage is
decided on was built to be volume-ungameable (the 60%-subsample attack wins 1-of-20 against
it), and the known ~6-milestone UMAP repartition floor is applied at the READING of milestone
counts (G-XP3) rather than bought again with a run.

THE F0-UNION GATE (G-XP0) is what makes the union arm auditable: routing of old pairs is
deterministic and cache-served, so the union arm's per-scenario PREFILTER pools restricted to
old-corpus calls must be LIST-IDENTICAL (content and order) to the published control's
`clause_pool_prefilter`. Any diff is a harness bug and nothing else is reportable.

TWO YARDSTICKS, DELIBERATELY, WITH THE BIAS DIRECTION STATED. `E[N_eff|k]` draws from "the
corpus's own account mix" and the treatment changes the corpus. Control keeps its PUBLISHED
yardstick (`null_draw_weights.json`); the union arm gets a union yardstick built by the same
production-extraction rule. The union pool holds ~120 more accounts, so the union arm faces a
HARDER bar — a primary PASS is conservative. The same-yardstick view (both arms against the
union pool) is reported as a labeled direction check only; it mechanically flatters the union
arm.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/expanded_pool_stage1.py --run
    ..\\.venv\\Scripts\\python.exe calibration/expanded_pool_stage1.py --score
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402

OLD_DIR = "recordings"
NEW_DIR = "recordings_pull_keep"
TAXONOMY = "clean2_base"
CONTROL_ARTIFACT = ARTIFACTS_DIR / "layer_bc_s0a0r0_b.json"          # the published control
FAILING_BASELINE = ARTIFACTS_DIR / "layer_bc_lcfr_real_p40.json"     # F0-proven replication
UNION_ARTIFACT = ARTIFACTS_DIR / "layer_bc_xp_union.json"
UNION_WEIGHTS = ARTIFACTS_DIR / "null_draw_weights_union.json"       # never the published one
PUBLISHED_WEIGHTS = ARTIFACTS_DIR / "null_draw_weights.json"
REPORT = ARTIFACTS_DIR / "xp_stage1_report.json"
WIDTH = 3072
SEED = 42
TRIALS = 20_000

# G-XP1, frozen in the spec: at or above this new-pair sink share the data-effect verdict is
# NOT TESTABLE ON THIS TAXONOMY (the run still completes — it is free).
STOP_SINK_SHARE = 0.75
# Spec 5.4: if the two arms' accounted_frac differ by more than this, the primary is flagged
# as roster-confounded.
ROSTER_CONFOUND_PP = 0.10
# G-XP3 reading floor: perturbing a clause pool at all costs ~this many milestones to UMAP
# repartitioning (published placebo lesson) — counts below it are noise, not signal.
REPARTITION_FLOOR = 6


# ---------------------------------------------------------------------------------------
# pure helpers (unit-tested in tests/test_expanded_pool_stage1.py)
# ---------------------------------------------------------------------------------------

def assert_no_stem_collision(old_stems: set[str], new_stems: set[str]) -> None:
    """A colliding stem would let one dir's roster sidecar or account resolve for the other
    dir's call — a silent cross-corpus join. The pull's overlap filter removed 412 calls for
    exactly this; assert it held."""
    both = old_stems & new_stems
    if both:
        raise SystemExit(f"ABORT: {len(both)} transcript stem(s) exist in BOTH corpus dirs, "
                         f"e.g. {sorted(both)[:3]!r}. The overlap filter did not hold; "
                         f"accounts and F0 restriction would silently cross corpora.")


def restrict_to_old(responses: list[dict], old_calls: set[str]) -> list[dict]:
    """The F0-union restriction: the union scenario pool with new-corpus pairs removed,
    ORDER PRESERVED — old pairs were concatenated first and routing is per-pair, so this
    must reproduce the control's response list exactly."""
    return [r for r in responses if r["call_filename"] in old_calls]


def f0_union_check(union_prefilter: list[str], control_prefilter: list[str]) -> dict:
    """List identity, content AND order. Returns a diff summary rather than a bool so a
    failure names its first divergence instead of just shouting."""
    if union_prefilter == control_prefilter:
        return {"ok": True, "n": len(control_prefilter)}
    first = next((i for i, (a, b) in enumerate(zip(union_prefilter, control_prefilter))
                  if a != b), min(len(union_prefilter), len(control_prefilter)))
    return {"ok": False, "n_union": len(union_prefilter), "n_control": len(control_prefilter),
            "first_divergence_index": first}


def origin_of(call_filename: str, new_calls: set[str]) -> str:
    return "new" if call_filename in new_calls else "old"


def sink_share_by_origin(pairs: list[dict], scenario_map: dict,
                         new_calls: set[str]) -> dict:
    """G-XP1's numbers, with the symmetric-filtering check built in: both origins go through
    the identical predicate, and the counts are reported per origin so the diff IS the list."""
    out = {}
    for origin in ("old", "new"):
        sub = [p for p in pairs if origin_of(p["call_filename"], new_calls) == origin]
        sink = sum(1 for p in sub
                   if not scenario_map[p["scenario_key"]]["is_coachable"])
        out[origin] = {"n_pairs": len(sub), "to_sink": sink,
                       "sink_share": sink / len(sub) if sub else float("nan")}
    return out


def classify_gained(milestone: dict, required_support: int, old_calls: set[str],
                    old_domains: set[str], accounts: dict[str, str]) -> dict:
    """G-XP3's gain classification, per gained milestone.

    `new_data_necessary`: the milestone's old-corpus support alone falls below the union
    arm's own `required_support` — it could not exist without the new data.
    `new_account_backed`: >= 1 supporting call from an account absent from the OLD corpus's
    account map (honest gain vs repeat-account padding).
    """
    files = milestone.get("support_call_files") or []
    old_support = len({f for f in files if f in old_calls})
    new_doms = {accounts.get(Path(f).stem) for f in files if f not in old_calls}
    new_doms.discard(None)
    return {"new_data_necessary": old_support < required_support,
            "new_account_backed": bool(new_doms - old_domains),
            "old_call_support": old_support,
            "new_accounts": sorted(new_doms - old_domains)}


def join_gained_to_milestones(gained: list[dict], arm_ms: list[dict]) -> list[dict]:
    """`match_milestones` returns gained entries carrying only (support_calls, clauses[:3]);
    the classification needs `support_call_files`. Join back on that pair and ASSERT the join
    is unique — a silent double-match would classify the wrong milestone."""
    out = []
    for g in gained:
        hits = [m for m in arm_ms
                if m["support_calls"] == g["support_calls"]
                and m["clauses"][:3] == g["clauses"]]
        if len(hits) != 1:
            raise ValueError(f"gained-milestone join is not unique ({len(hits)} hits for "
                             f"support={g['support_calls']}, clauses={g['clauses'][:1]!r})")
        out.append(hits[0])
    return out


def merge_account_maps(maps: list[dict]) -> dict:
    """Stems are asserted non-colliding upstream, so a plain merge is safe."""
    out: dict[str, str] = {}
    for m in maps:
        for k, v in m.items():
            if k in out and out[k] != v:
                raise ValueError(f"account map collision on stem {k!r}: {out[k]!r} vs {v!r}")
            out[k] = v
    return out


def failing_candidates(per_scenario: dict) -> list[dict]:
    """The pre-gate candidates below their scenario's required support — the '33 failing
    clusters' inventory shape (readout 5.3). Descriptive only; candidate clause lists were
    never persisted so cross-arm identity is by scenario + call-file overlap."""
    out = []
    for key, rec in per_scenario.items():
        req = rec.get("required_support")
        if req is None:
            continue
        for c in rec.get("candidates_pregate") or []:
            if c["support_calls"] < req:
                out.append({"scenario_key": key, "required": req, **c})
    return out


def failing_fate(control_failing: list[dict], union_rec_of: dict,
                 old_calls: set[str]) -> list[dict]:
    """For each control failing candidate: does any union pre-gate candidate in the SAME
    scenario share >= half its support calls (restricted to old corpus) AND clear the union
    arm's own required support?"""
    out = []
    for f in control_failing:
        rec = union_rec_of.get(f["scenario_key"]) or {}
        req = rec.get("required_support")
        base_files = set(f.get("support_call_files") or [])
        best, best_ov = None, 0.0
        for c in rec.get("candidates_pregate") or []:
            arm_old = {x for x in (c.get("support_call_files") or []) if x in old_calls}
            ov = len(base_files & arm_old) / len(base_files) if base_files else 0.0
            if ov > best_ov:
                best, best_ov = c, ov
        out.append({"scenario_key": f["scenario_key"], "base_support": f["support_calls"],
                    "overlap": best_ov,
                    "matched": best is not None and best_ov >= 0.5,
                    "now_clears": bool(best and req is not None
                                       and best_ov >= 0.5
                                       and best["support_calls"] >= req),
                    "union_support": (best or {}).get("support_calls"),
                    "union_required": req})
    return out


# ---------------------------------------------------------------------------------------
# --run: build the union arm
# ---------------------------------------------------------------------------------------

def run_union(overwrite: bool, smoke: bool = False) -> None:
    from calibration.layer_bc_arms import (taxonomy_path, scenario_map_from_rows,
                                           install_embedder_shim, prewarm, build_pairs,
                                           parse_corpus, corpus_sha, taxonomy_sha,
                                           run_identity, routing_stats, top1_top2_margins,
                                           distribution_stats)
    from calibration.lcfr_common import pass1_lcfr, p40_filter
    from calibration.build_null_weights import build as build_weights
    from shared.scenario_vectors import scenario_text
    from shared.tuning import load_tuning
    from v1.layer_b import assign_scenarios
    from v2.layer_c import build_clause_pool
    from preprocessing import embedder

    # --smoke: an end-to-end PATH TEST (two full launches in this repo died mid-generation
    # on defects py_compile cannot catch). Tiny corpus slice, 2 scenarios, SMOKE-named
    # artifact stamped incomplete, F0 reported but not gating (a sliced corpus cannot match
    # the control), no weights written. Never scoreable.
    out_path = (ARTIFACTS_DIR / "layer_bc_xp_union_SMOKE.json") if smoke else UNION_ARTIFACT
    if out_path.exists() and not overwrite:
        raise SystemExit(f"{out_path.name} already exists. Pass --overwrite to replace "
                         f"it. Refusing to clobber a measured artifact.")
    if not CONTROL_ARTIFACT.exists():
        raise SystemExit(f"published control {CONTROL_ARTIFACT.name} not found")
    control = json.loads(CONTROL_ARTIFACT.read_text(encoding="utf-8-sig"))

    tax = taxonomy_path(TAXONOMY)
    tax_art = json.loads(tax.read_text(encoding="utf-8-sig"))
    if tax_art.get("incomplete"):
        raise SystemExit(f"{tax.name} is stamped INCOMPLETE")
    scenario_map, cluster_of_key = scenario_map_from_rows(tax_art["rows"])
    coachable = {k: v for k, v in scenario_map.items() if v["is_coachable"]}
    print(f"[taxonomy] {TAXONOMY}: {len(coachable)} coachable + "
          f"{len(scenario_map) - len(coachable)} sinks (FROZEN)", flush=True)

    # --- corpus: two dirs, old first (F0's order guarantee), stems asserted disjoint ------
    parsed_old = parse_corpus(OLD_DIR)
    parsed_new = parse_corpus(NEW_DIR)
    if smoke:
        parsed_old, parsed_new = parsed_old[:25], parsed_new[:25]
        print("[SMOKE] corpus sliced to 25+25 calls — PATH TEST ONLY", flush=True)
    assert_no_stem_collision({p.stem for _, p, _ in parsed_old},
                             {p.stem for _, p, _ in parsed_new})
    pairs_old = build_pairs(OLD_DIR, "s0", "a0", parsed=parsed_old)
    pairs_new = build_pairs(NEW_DIR, "s0", "a0", parsed=parsed_new)
    new_calls = {p.name for _, p, _ in parsed_new}
    old_calls = {p.name for _, p, _ in parsed_old}
    pairs = pairs_old + pairs_new
    print(f"[corpus] union: {len(pairs_old)} old + {len(pairs_new)} new pairs over "
          f"{len(old_calls)}+{len(new_calls)} calls", flush=True)

    csha = corpus_sha(pairs)
    if not smoke and csha == control["identity"]["corpus_sha"]:
        raise SystemExit("union corpus_sha equals the control's — the new dir contributed "
                         "nothing; check the corpus dirs")

    # --- union null yardstick, BEFORE anything can depend on the run's outcome ------------
    # A stale weights file is a silently wrong yardstick (audit finding 4): the pull dir
    # changed twice this week, so an existing file must PROVE it describes THIS corpus.
    if smoke:
        pass  # a sliced corpus must never write or validate the real yardstick
    elif UNION_WEIGHTS.exists():
        w_have = json.loads(UNION_WEIGHTS.read_text(encoding="utf-8-sig"))
        if w_have.get("n_pairs") != len(pairs):
            raise SystemExit(
                f"{UNION_WEIGHTS.name} is STALE: it records {w_have.get('n_pairs')} pairs, "
                f"this corpus extracts {len(pairs)}. Delete it deliberately and re-run — "
                f"scoring against it would divide the primary metric by the wrong null.")
    if not smoke and not UNION_WEIGHTS.exists():
        w = {"source": "v1.layer_b.extract_pairs (PRODUCTION, s0/a0) over the UNION corpus",
             "recordings": f"{OLD_DIR}+{NEW_DIR}"}
        # pairs are already extracted by production above; reuse them rather than re-parsing.
        import hashlib
        per_call: Counter = Counter()
        for p in pairs:
            per_call[Path(p["call_filename"]).stem] += 1
        weights = {p.stem: per_call.get(p.stem, 0)
                   for _, p, _ in parsed_old + parsed_new}
        h = hashlib.sha256()
        for stem in sorted(weights):
            h.update(f"{stem}.txt|{weights[stem]}\n".encode("utf-8"))
        w.update({"n_calls": len(weights), "n_pairs": len(pairs),
                  "n_zero_pair_calls": sum(1 for v in weights.values() if v == 0),
                  "weights_sha": h.hexdigest()[:16], "weights": weights})
        UNION_WEIGHTS.write_text(json.dumps(w, indent=1), encoding="utf-8")
        print(f"[weights] wrote {UNION_WEIGHTS.name}: {w['n_pairs']} pairs / "
              f"{w['n_calls']} calls, sha {w['weights_sha']}", flush=True)

    # --- embeddings: cache-only after one bounded scenario-text prewarm --------------------
    prewarm([scenario_text(v) for v in scenario_map.values()], 20)
    embed_calls = install_embedder_shim(WIDTH)

    tuning = load_tuning()
    t0 = time.time()
    print(f"\n[layer B] routing {len(pairs)} pairs with production assign_scenarios (r0)...",
          flush=True)
    assign_scenarios(pairs, scenario_map, None)
    trig_vecs = embedder.embed_query_matrix([p["trigger_text"] for p in pairs])
    routing = routing_stats(pairs, scenario_map, top1_top2_margins(trig_vecs, scenario_map))
    del trig_vecs
    by_origin = sink_share_by_origin(pairs, scenario_map, new_calls)
    print(f"[layer B] sink share old={by_origin['old']['sink_share']*100:.1f}% "
          f"new={by_origin['new']['sink_share']*100:.1f}%  (G-XP1 stop bar "
          f"{STOP_SINK_SHARE*100:.0f}%)", flush=True)

    by_key: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        k = p["scenario_key"]
        if k and scenario_map[k]["is_coachable"]:
            by_key[k].append(p)

    # --- G-XP0 + Layer C Pass 1, per scenario ---------------------------------------------
    ctrl_ps = control["per_scenario"]
    missing = sorted(set(ctrl_ps) - set(coachable))
    if missing:
        raise SystemExit(f"control has scenario keys the frozen taxonomy lacks: {missing[:3]}")

    f0_results: dict[str, dict] = {}
    per_scenario: dict[str, dict] = {}
    filt = p40_filter(tuning.layer_c)
    todo = sorted(coachable.items())
    if smoke:
        todo = todo[:2]
        print("[SMOKE] 2 scenarios only; F0 reported but NOT gating on a sliced corpus",
              flush=True)
    print(f"\n[layer C] Pass 1 over {len(todo)} scenarios, Gemma-free...", flush=True)
    for n, (key, info) in enumerate(todo, 1):
        responses = by_key.get(key, [])
        prefilter, _, _, _ = (build_clause_pool(responses) if responses
                              else ([], [], [], []))

        # F0-union: the old-restricted prefilter pool must reproduce the control's.
        # Mirror production's early exit (audit finding 3): the control's pass1 returns
        # clause_pool_prefilter=[] for <2 responses BEFORE build_clause_pool runs, so a
        # scenario with exactly one old pair must compare [] against [], not a real pool.
        old_resp = restrict_to_old(responses, old_calls)
        old_prefilter = (build_clause_pool(old_resp)[0] if len(old_resp) >= 2 else [])
        ctrl_pool = (ctrl_ps.get(key) or {}).get("clause_pool_prefilter", [])
        f0_results[key] = f0_union_check(old_prefilter, ctrl_pool)

        res = pass1_lcfr(info, responses, tuning.layer_c, filt, capture=True)
        cap = res.pop("_capture", None) or {}
        # capture=True attaches _idx/_centroid (an ndarray) to the SAME dicts that become
        # res["milestones"] — json.dumps(default=float) dies on the array (audit finding 1).
        res["milestones"] = [{k: v for k, v in m.items() if not k.startswith("_")}
                             for m in res["milestones"]]
        res["clause_pool"] = list(cap.get("clauses") or [])
        res["clause_pool_prefilter"] = prefilter
        res["cluster_id"] = cluster_of_key.get(key, "")
        res["n_pairs"] = len(responses)
        res["n_pairs_old"] = sum(1 for p in responses if p["call_filename"] in old_calls)
        res["n_pairs_new"] = len(responses) - res["n_pairs_old"]
        res["calls_old"] = len({p["call_filename"] for p in responses
                                if p["call_filename"] in old_calls})
        res["calls_new"] = len({p["call_filename"] for p in responses
                                if p["call_filename"] not in old_calls})
        per_scenario[key] = res
        flag = "" if f0_results[key]["ok"] else "  ** F0 DIVERGED **"
        print(f"  [{n}/{len(todo)}] {key[:42]:<42} {res['n_pairs']:>5}p "
              f"(+{res['n_pairs_new']} new) {res['n_clauses']:>6}cl -> "
              f"{len(res['milestones']):>2} ms ({res['outcome']}){flag}", flush=True)

    f0_pass = all(v["ok"] for v in f0_results.values())
    stats = distribution_stats(per_scenario, tuning.layer_c.min_milestone_calls_floor)
    ident = run_identity(csha, taxonomy_sha(scenario_map), TAXONOMY, scenario_map,
                         tuning, WIDTH, "", tax_art, "s0", "a0", "r0")
    ident.update({"started_at": datetime.datetime.now().isoformat(timespec="seconds"),
                  "pid": os.getpid(), "seed": SEED,
                  "n_pairs_old": len(pairs_old), "n_pairs_new": len(pairs_new),
                  "n_calls_old": len(old_calls), "n_calls_new": len(new_calls),
                  "control_artifact": CONTROL_ARTIFACT.name,
                  "union_weights": UNION_WEIGHTS.name})

    out_path.write_text(json.dumps({
        "arm": "xp_union", "taxonomy_arm": TAXONOMY, "identity": ident,
        "incomplete": bool(smoke), "smoke": bool(smoke),
        "chat_calls": 0, "embed_calls": embed_calls, "seed": SEED,
        "f0_union": {"pass": f0_pass and not smoke, "per_scenario": f0_results},
        "stats": stats, "routing": routing, "routing_by_origin": by_origin,
        "cluster_of_key": cluster_of_key,
        "per_scenario": per_scenario,
    }, indent=1, default=float), encoding="utf-8")
    if smoke:
        print("\n[SMOKE] path test complete — artifact stamped incomplete, never scoreable")
    else:
        print(f"\n[G-XP0] F0-union: {'PASS' if f0_pass else '** FAIL — NOTHING REPORTABLE **'}")
    print(f"wrote {out_path.name}: {stats['n_milestones']} milestones over "
          f"{stats['n_scenarios']} scenarios in {(time.time()-t0)/60:.1f} min")
    print("ZERO chat calls were made. NOTHING was written to Postgres.")


# ---------------------------------------------------------------------------------------
# --score: free re-report from artifacts
# ---------------------------------------------------------------------------------------

def score() -> None:
    from calibration import layer_b_arms as lb
    from calibration.layer_bc_arms import match_milestones
    from calibration.flag_proper_noun_clusters import account_map

    control = json.loads(CONTROL_ARTIFACT.read_text(encoding="utf-8-sig"))
    union = json.loads(UNION_ARTIFACT.read_text(encoding="utf-8-sig"))
    failing_base = json.loads(FAILING_BASELINE.read_text(encoding="utf-8-sig"))
    if union.get("incomplete"):
        raise SystemExit("union artifact is stamped INCOMPLETE (smoke or partial) — "
                         "scoring it would report a path test as a result")
    if not union.get("f0_union", {}).get("pass"):
        raise SystemExit("G-XP0 FAILED on the union artifact — nothing is reportable. "
                         "Fix the harness; do not score.")

    old_calls = {f"{s}.txt" for s in json.loads(
        PUBLISHED_WEIGHTS.read_text(encoding="utf-8-sig"))["weights"]}

    # --- accounts: control in its PUBLISHED frame; union in the union frame ---------------
    acct_old_raw, _ = account_map(OLD_DIR)
    acct_new_raw, _ = account_map(NEW_DIR)
    # account_map returns {} silently on a wrong path/missing sidecars (audit finding 6);
    # an empty NEW map would drag the primary toward NULL while looking like a result.
    if not acct_old_raw or not acct_new_raw:
        raise SystemExit(f"ABORT: account map empty for "
                         f"{'OLD' if not acct_old_raw else 'NEW'} dir — wrong path or "
                         f"missing .speakers.json sidecars; scoring would report a null "
                         f"manufactured by a broken join.")
    acct_old, merges_old = lb.collapse_sibling_domains(acct_old_raw)
    acct_union, merges_union = lb.collapse_sibling_domains(
        merge_account_maps([acct_old_raw, acct_new_raw]))
    # OLD domains expressed in the UNION collapse frame (audit finding 5): a parent domain
    # first observed in the NEW corpus relabels old clients under the union collapse, and
    # comparing across frames would count a repeat client as an "honest gain".
    old_domains = {acct_union[s] for s in acct_old_raw if s in acct_union}

    w_old = json.loads(PUBLISHED_WEIGHTS.read_text(encoding="utf-8-sig"))
    w_union = json.loads(UNION_WEIGHTS.read_text(encoding="utf-8-sig"))

    pool_old = lb.corpus_account_pool(acct_old, w_old["weights"])
    pool_union = lb.corpus_account_pool(acct_union, w_union["weights"])

    # table_old covers ONLY the control's ks in the old frame (audit finding 2): the union
    # arm's clusters can exceed the OLD pool's drawable size, and expected_neff_table
    # correctly raises on k > n — those ks belong to table_union alone.
    ks_old = lb.union_cluster_ks([control["per_scenario"]], acct_old)
    ks_union = lb.union_cluster_ks([control["per_scenario"], union["per_scenario"]],
                                   acct_union)
    table_old = lb.expected_neff_table(pool_old, ks_old, trials=TRIALS, seed=SEED)
    table_union = lb.expected_neff_table(pool_union, ks_union, trials=TRIALS, seed=SEED)

    # PRIMARY frame: each arm against its own corpus yardstick.
    st_ctrl = lb.per_cluster_stats(control["per_scenario"], acct_old, table_old)
    st_union = lb.per_cluster_stats(union["per_scenario"], acct_union, table_union)
    primary = lb.compare_arms(st_ctrl, st_union, "lift")
    primary_neff = lb.compare_arms(st_ctrl, st_union, "neff")

    # SENSITIVITY frame (labeled, mechanically flatters the union arm): one shared yardstick.
    st_ctrl_u = lb.per_cluster_stats(control["per_scenario"], acct_union, table_union)
    sensitivity = lb.compare_arms(st_ctrl_u, st_union, "lift")

    ur_ctrl = lb.unaccounted_rate(control["per_scenario"], acct_old)
    ur_union = lb.unaccounted_rate(union["per_scenario"], acct_union)
    roster_gap = abs((ur_ctrl["accounted_frac"] or 0) - (ur_union["accounted_frac"] or 0))

    dist_ctrl = lb.score_distribution(control["per_scenario"], acct_old, table_old)
    dist_union = lb.score_distribution(union["per_scenario"], acct_union, table_union)

    # --- G-XP3: merge-aware milestone accounting vs the published control -----------------
    outcomes_all, gained_all = [], []
    for key, base_rec in control["per_scenario"].items():
        arm_rec = union["per_scenario"].get(key) or {}
        arm_ms = arm_rec.get("milestones") or []
        outs, gained = match_milestones(
            base_rec.get("milestones") or [], arm_ms,
            base_rec.get("scenario_calls") or 0, arm_rec.get("scenario_calls") or 0,
            arm_pool=set(arm_rec.get("clause_pool") or []),
            arm_pool_prefilter=set(arm_rec.get("clause_pool_prefilter") or []))
        for o in outs:
            o["scenario_key"] = key
        outcomes_all.extend(outs)
        req = arm_rec.get("required_support") or 0
        for m in join_gained_to_milestones(gained, arm_ms):
            g = classify_gained(m, req, old_calls, old_domains, acct_union)
            g.update({"scenario_key": key, "support_calls": m["support_calls"],
                      "clauses": m["clauses"][:2]})
            gained_all.append(g)

    oc = Counter(o["outcome"] for o in outcomes_all)
    gain_dn = sum(1 for g in gained_all if g["new_data_necessary"])
    gain_na = sum(1 for g in gained_all if g["new_account_backed"])

    # --- readout 5.3: the failing clusters' fate -------------------------------------------
    ctrl_failing = failing_candidates(failing_base["per_scenario"])
    fate = failing_fate(ctrl_failing, union["per_scenario"], old_calls)
    now_clears = sum(1 for f in fate if f["now_clears"])
    ctrl_fallback = {k for k, r in failing_base["per_scenario"].items()
                     if r["outcome"] == "fallback_no_support"}
    flipped = [k for k in ctrl_fallback
               if (union["per_scenario"].get(k) or {}).get("outcome") == "clustered"]

    # --- gates -----------------------------------------------------------------------------
    new_sink = union["routing_by_origin"]["new"]["sink_share"]
    gxp1 = new_sink < STOP_SINK_SHARE
    gxp2 = (primary["p"] < 0.05 and primary["net"] > 0
            and sensitivity["up"] > sensitivity["down"])

    print("=" * 100)
    print("EXPANDED-POOL STAGE 1 — the data effect  (spec 2026-08-17-expanded-pool-stage1)")
    print("=" * 100)
    print(f"\n[G-XP0] F0-union: PASS ({len(union['f0_union']['per_scenario'])} scenarios "
          f"byte-identical on old-call restriction)")
    print(f"\n[G-XP1] routing of new pairs (stop bar {STOP_SINK_SHARE:.2f}):")
    for orig, r in union["routing_by_origin"].items():
        print(f"  {orig:>4}: {r['n_pairs']:>6} pairs, {r['to_sink']:>6} to sink "
              f"({r['sink_share']*100:.1f}%)")
    print(f"  -> {'OK — data-effect verdict is testable' if gxp1 else '** STOP: taxonomy mismatch — verdict NOT TESTABLE on this taxonomy **'}")

    print(f"\n[G-XP2 PRIMARY] rev-4 cluster account-diversity lift, paired on cluster_id")
    print(f"  yardsticks: control={w_old['weights_sha']} ({w_old['n_pairs']}p) | "
          f"union={w_union['weights_sha']} ({w_union['n_pairs']}p)")
    print(f"  accounts: old {len(set(acct_old.values()))} | union "
          f"{len(set(acct_union.values()))} (sibling merges old={len(merges_old)} "
          f"union={len(merges_union)})")
    for name, d in (("PRIMARY (own yardsticks)", primary),
                    ("sensitivity (shared union yardstick — flatters union)", sensitivity),
                    ("raw N_eff companion", primary_neff)):
        print(f"  {name:<55} up={d['up']:>3} down={d['down']:>3} tie={d['tie']} "
              f"unscor={d['unscoreable_pairs']} net={d['net']:+.3f} p={d['p']:.4f}")
    print(f"  k: control median {dist_ctrl['k']['median']:.0f} -> union "
          f"{dist_union['k']['median']:.0f}   lift median "
          f"{dist_ctrl['lift']['median']:.3f} -> {dist_union['lift']['median']:.3f}")
    print(f"  accounted_frac: control {ur_ctrl['accounted_frac']*100:.1f}% | union "
          f"{ur_union['accounted_frac']*100:.1f}%"
          + ("  ** ROSTER-CONFOUNDED (>10pp gap) **" if roster_gap > ROSTER_CONFOUND_PP else ""))
    print(f"  -> G-XP2: {'PASS — data was the constraint; promotion justified' if gxp2 else 'NULL — the clusterer eats evidence faster than data supplies it'}")

    print(f"\n[G-XP3] milestones: control {control['stats']['n_milestones']} -> union "
          f"{union['stats']['n_milestones']}  (repartition floor ~{REPARTITION_FLOOR})")
    print(f"  outcomes: {dict(oc)}")
    print(f"  gained: {len(gained_all)} — new_data_necessary {gain_dn}, "
          f"new_account_backed {gain_na}, repeat-account padding "
          f"{len(gained_all) - gain_na}")
    print(f"\n[5.3] failing clusters: baseline {len(ctrl_failing)} failing candidates; "
          f"{sum(1 for f in fate if f['matched'])} matched in union, {now_clears} now clear "
          f"the union support gate; scenario flips no_support->clustered: {flipped or 'none'}")

    REPORT.write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "gates": {"gxp0": True, "gxp1": gxp1, "gxp2": gxp2},
        "new_pair_sink_share": new_sink,
        "primary": primary, "sensitivity": sensitivity, "primary_neff": primary_neff,
        "dist_control": dist_ctrl, "dist_union": dist_union,
        "unaccounted": {"control": ur_ctrl, "union": ur_union},
        "milestone_outcomes": dict(oc),
        "gained": gained_all, "failing_fate": fate,
        "scenario_flips_no_support_to_clustered": flipped,
        "weights_shas": {"control": w_old["weights_sha"], "union": w_union["weights_sha"]},
    }, indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {REPORT.name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", action="store_true", help="build the union arm artifact")
    p.add_argument("--score", action="store_true", help="free re-report from artifacts")
    p.add_argument("--smoke", action="store_true",
                   help="end-to-end PATH TEST: 25+25 calls, 2 scenarios, SMOKE artifact")
    p.add_argument("--overwrite", action="store_true")
    a = p.parse_args()
    if a.smoke and a.score:
        raise SystemExit("--smoke output is never scoreable")
    if a.run or a.smoke:
        run_union(a.overwrite, smoke=a.smoke)
    if a.score:
        score()
    if not (a.run or a.score or a.smoke):
        p.print_help()


if __name__ == "__main__":
    main()
