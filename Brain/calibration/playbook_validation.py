#!/usr/bin/env python3
"""UNION TAXONOMY REBUILD — Stage E: playbook validation (PV) on the NEW map.

Spec: docs/superpowers/specs/2026-08-18-union-taxonomy-rebuild-design.md §6 (frozen).

This is the VALIDATED snap-trial pipeline re-run end to end with ONE rebind: the
taxonomy is `union_rescued` and the corpus is the union. Every bar is carried unchanged
from the pilot + snap specs (they are frozen there): pick rule ranks 1/5/10/15/20 by
routed-pair count (ties ascending key); donors count-matched non-pilot without
replacement; 50-pair selection (account floor 8 + greedy max-min on cache-only response
vectors); map-reduce synthesis with the placebo twin; verbatim snap (>= 0.80) with the
collapse rules; PB0 on the SNAPPED documents; counterbalanced read (real on A at odd
rank positions — deterministic, never a coin); 3 fresh blinded sonnet readers; PB3 and
PB1-resized reported, never decisive.

  PV GATE = PB0(snapped) 5/5 real  AND  PB2 real preferred in >= 4/5 scenarios.
  BUDGET  = <= 50 chat attempts (hard stop, every attempt persisted BEFORE its POST).

THE ONE FROZEN PROMPT HARDENING (spec §6): the reduce prompt's key-move instruction
gains "evidence from distinct accounts within each move" as a REQUIREMENT rather than a
preference (targets the standing PB1 per-move flag; PB1 stays non-decisive). Implemented
as a verbatim replacement over the pilot's REDUCE_RULES with a drift assert, so the two
prompts differ in EXACTLY that sentence.

Embedding: selection vectors are cache-only u_turn unit texts; the union map routes
newly-coachable responses whose units were never cached, so ONE bounded top-up fetch is
expected and budgeted as embedding spend (spec §6) — it is counted, printed, and happens
only in --select.

Everything else is imported from the two validated harnesses, never re-implemented:
pure gates/renderers/scorers from `scenario_playbook_trial`, snap/counterbalance/PB1
from `playbook_snap_trial`.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/playbook_validation.py --select
    .\\ops\\run_visible.ps1 -Script calibration/playbook_validation.py -ScriptArgs '--synthesize'
    ..\\.venv\\Scripts\\python.exe calibration/playbook_validation.py --snap
    ..\\.venv\\Scripts\\python.exe calibration/playbook_validation.py --pb0
    ..\\.venv\\Scripts\\python.exe calibration/playbook_validation.py --build-read
    # (3 blinded readers write artifacts/pbv_judgments_r*.json, ONE AT A TIME)
    ..\\.venv\\Scripts\\python.exe calibration/playbook_validation.py --score
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

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402
from calibration.scenario_playbook_trial import (  # noqa: E402
    ACCT_FLOOR, ATTEMPTS_PER_CALL, BATCH_MAX, CALL_BUDGET_HARD, CHAT_TEMPERATURE,
    N_EVIDENCE_MAX, N_NEG, PACKET_HEADER, REDUCE_RULES, SEED,
    assign_donors, build_neg, build_pool, doc_evidence, doc_jobs, map_prompt,
    pb0_doc, pick_pilot, reduce_prompt, render_doc, scenario_header_text, score_read,
    validate_map, validate_playbook,
)
from calibration.playbook_snap_trial import (  # noqa: E402
    counterbalanced_side, pb1_doc_resized, snap_doc,
)

# THE MAP UNDER VALIDATION. Written as "union_rescued" when this harness was authored
# (spec §4's primary arm); rebound to "union_base" on 2026-08-18 after the rescued arm
# FAILED G-R4 (8/12, veto-audited) and the operator-chosen fallback arm PASSED all
# four gates (G-R4 10/12, veto-audited) — §1 says PV runs on the map that cleared the
# gates. The identity stamp in every pbv_* artifact records this value.
TAXONOMY = "union_base"
WIDTH = 3072

EVIDENCE = ARTIFACTS_DIR / "pbv_evidence.json"
PLAYBOOKS = ARTIFACTS_DIR / "pbv_playbooks.json"
SNAPPED = ARTIFACTS_DIR / "pbv_playbooks_snapped.json"
PB0_REPORT = ARTIFACTS_DIR / "pbv_pb0_report.json"
PACKET = ARTIFACTS_DIR / "pbv_read_packet.txt"
KEY = ARTIFACTS_DIR / "pbv_read_KEY.json"
JUDGMENTS_GLOB = "pbv_judgments_*.json"
REPORT = ARTIFACTS_DIR / "pbv_report.json"


# ---------------------------------------------------------------------------------------
# the frozen prompt hardening (unit-tested in tests/test_playbook_validation.py)
# ---------------------------------------------------------------------------------------

# Anchor updated 2026-08-20 with the entry-floor change (2-4 -> 3-4 entries per move) in
# scenario_playbook_trial.REDUCE_RULES. The count assert in pv_reduce_rules() fired on that
# edit exactly as designed and refused to synthesize until reconciled -- which is the only
# reason this was caught rather than shipped as an un-hardened prompt.
_PREFER = ("Each move's evidence\n  MUST come from at least 3 DISTINCT accounts whenever 3 "
           "are available in the candidates.")
# v2 wording (2026-08-18, operator-approved restart). v1 read "citing the same account
# twice while another account's evidence exists is a violated rule" — models complied
# by citing ONE entry on account-thin moves, which violates the 2-4-entries schema
# rule; 9 consecutive reduce rejects on ats_integration::placebo, diagnosis confirmed
# by per-move shape logging. v2 states the precedence explicitly so BOTH frozen
# constraints hold.
_REQUIRE = ("REQUIREMENT: within each move the\n"
            "  evidence entries MUST come from DISTINCT accounts whenever the candidate\n"
            "  evidence offers more than one account for that move. This NEVER overrides\n"
            "  the 3-4 entry rule: a move whose candidates come from fewer than 3 accounts\n"
            "  still cites 3 entries, repeating an account rather than dropping below 3. A\n"
            "  candidate move that cannot reach 3 entries must be MERGED into a\n"
            "  related move or DROPPED entirely -- never emitted with fewer.")


def pv_reduce_rules() -> str:
    """The pilot's REDUCE_RULES with EXACTLY one sentence hardened. The count assert
    means a future edit to the source rules fails loudly here instead of silently
    shipping an un-hardened or doubly-edited prompt."""
    if REDUCE_RULES.count(_PREFER) != 1:
        raise SystemExit("REDUCE_RULES drifted — the frozen hardening no longer applies "
                         "cleanly; do not synthesize until this is reconciled")
    return REDUCE_RULES.replace(_PREFER, _REQUIRE)


def pv_reduce_prompt(header: str, map_outputs: list[dict], triggers: list[str]) -> str:
    base = reduce_prompt(header, map_outputs, triggers)
    out = base.replace(REDUCE_RULES, pv_reduce_rules())
    if out == base:
        raise SystemExit("reduce_prompt no longer embeds REDUCE_RULES verbatim — the "
                         "hardening cannot be applied; reconcile before any spend")
    return out


# ---------------------------------------------------------------------------------------
# substrate: union corpus routed against the NEW map (production concat)
# ---------------------------------------------------------------------------------------

def build_pv_substrate():
    from calibration.layer_bc_arms import (build_pairs, corpus_sha,
                                           install_embedder_shim, parse_corpus,
                                           prewarm, scenario_map_from_rows,
                                           taxonomy_path, taxonomy_sha)
    from calibration.expanded_pool_stage1 import assert_no_stem_collision
    from shared.scenario_vectors import scenario_text
    from shared.tuning import load_tuning
    from v1.layer_b import assign_scenarios

    tax = taxonomy_path(TAXONOMY)
    if not tax.exists():
        raise SystemExit(f"{tax.name} not found — Stage C has not produced the new map")
    tax_art = json.loads(tax.read_text(encoding="utf-8-sig"))
    if tax_art.get("limit"):
        raise SystemExit(f"{tax.name} is a --limit path test, not a taxonomy")
    scenario_map, cluster_of_key = scenario_map_from_rows(tax_art["rows"])
    coachable = {k: v for k, v in scenario_map.items() if v["is_coachable"]}
    if not coachable:
        raise SystemExit("new map has no coachable scenarios")

    parsed_old = parse_corpus("recordings")
    parsed_new = parse_corpus("recordings_pull_keep")
    assert_no_stem_collision({p.stem for _, p, _ in parsed_old},
                             {p.stem for _, p, _ in parsed_new})
    pairs = (build_pairs("recordings", "s0", "a0", parsed=parsed_old)
             + build_pairs("recordings_pull_keep", "s0", "a0", parsed=parsed_new))

    prewarm([scenario_text(v) for v in scenario_map.values()], 20)
    install_embedder_shim(WIDTH)
    print(f"[substrate] routing {len(pairs)} pairs (production r0, concat)...", flush=True)
    assign_scenarios(pairs, scenario_map, None)

    by_key: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        k = p["scenario_key"]
        if k and scenario_map[k]["is_coachable"]:
            by_key[k].append(p)
    return {"coachable": coachable, "by_key": dict(by_key),
            "scenario_map": scenario_map, "cluster_of_key": cluster_of_key,
            "tuning": load_tuning(), "corpus_sha": corpus_sha(pairs),
            "taxonomy_sha": taxonomy_sha(scenario_map)}


def _ident(sub, extra: dict) -> dict:
    return {"started_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "pid": os.getpid(), "seed": SEED, "taxonomy": TAXONOMY,
            "corpus_sha": sub["corpus_sha"], "taxonomy_sha": sub["taxonomy_sha"],
            **extra}


# ---------------------------------------------------------------------------------------
# --select (embedding top-up is the ONLY spend here; counted and bounded)
# ---------------------------------------------------------------------------------------

def stage_select() -> None:
    from calibration import layer_b_arms as lb
    from calibration.expanded_pool_stage1 import merge_account_maps
    from calibration.flag_proper_noun_clusters import account_map
    from calibration.layer_bc_arms import _load_cached
    from calibration.scenario_playbook_trial import select_evidence
    from preprocessing import segmenter

    if EVIDENCE.exists():
        raise SystemExit(f"{EVIDENCE.name} exists — refusing to clobber")

    sub = build_pv_substrate()
    acct_old, _ = account_map("recordings")
    acct_new, _ = account_map("recordings_pull_keep")
    if not acct_old or not acct_new:
        raise SystemExit("ABORT: an account map came back empty — missing sidecars")
    acct, _ = lb.collapse_sibling_domains(merge_account_maps([acct_old, acct_new]))

    counts = {k: len(sub["by_key"].get(k, [])) for k in sub["coachable"]}
    pilot = pick_pilot(counts)
    donors = assign_donors(pilot, counts)
    print("[select] pilot (rank order): "
          + ", ".join(f"{k}({counts[k]}p)" for k in pilot), flush=True)
    for k in pilot:
        print(f"  donor for {k}: {donors[k]} ({counts[donors[k]]}p)", flush=True)

    # Build every pool first, then ONE bounded top-up fetch for whatever the union map
    # routes that the pilot-era cache never saw (spec §6: embedding spend, not chat).
    pools: dict[str, tuple] = {}
    for key in sorted(set(pilot) | set(donors.values())):
        pool, no_acct, no_clause = build_pool(sub["by_key"].get(key, []), acct,
                                              segmenter.segment_into_clauses)
        if not pool:
            raise SystemExit(f"ABORT: empty evidence pool for {key!r}")
        pools[key] = (pool, no_acct, no_clause)

    all_texts = sorted({p["unit_text"] for pool, _, _ in pools.values() for p in pool})
    _, missing = _load_cached(all_texts, WIDTH)
    n_fetched = 0
    if missing:
        from calibration.trial_pool_unit_gemini import embed_cached
        n_fetched = len(missing)
        # Sanity ceiling (audit 9.5 finding 1): the legitimate top-up is the
        # newly-coachable slice of <= 10 scenario pools. Misses beyond this bound mean
        # the cache itself eroded — §8's budget-escalation condition, so HALT and ask
        # rather than silently re-paying texts that were bought long ago.
        TOPUP_CEILING = 10_000
        if n_fetched > TOPUP_CEILING:
            raise SystemExit(f"TOP-UP CEILING: {n_fetched} uncached selection vectors "
                             f"(> {TOPUP_CEILING}) — the embed cache has eroded. HALT; "
                             f"ask the operator before re-paying.")
        print(f"[top-up] {n_fetched} selection vector(s) uncached (newly-coachable "
              f"responses) — the ONE bounded embedding top-up, fetching now...",
              flush=True)
        embed_cached(sorted(missing), 20)
        _, still = _load_cached(all_texts, WIDTH)
        if still:
            raise SystemExit(f"ABORT: {len(still)} unit text(s) STILL uncached after the "
                             f"top-up")

    per_scenario = {}
    for key, (pool, no_acct, no_clause) in sorted(pools.items()):
        mat, missing = _load_cached([p["unit_text"] for p in pool], WIDTH)
        if mat is None:
            raise SystemExit(f"ABORT: cache miss after top-up for {key!r} — bug")
        idx = select_evidence(pool, mat, N_EVIDENCE_MAX,
                              min(ACCT_FLOOR, len({p['account'] for p in pool})))
        sel = [dict(pool[i]) for i in idx]
        per_scenario[key] = {
            "routed_pairs": counts[key], "pool_accounted": len(pool),
            "excluded_no_account": no_acct, "excluded_no_clause": no_clause,
            "accounts_in_pool": len({p["account"] for p in pool}),
            "accounts_selected": len({s["account"] for s in sel}),
            "selected": sel,
        }
        print(f"  [{key[:40]:<40}] pool {len(pool):>4} (excl {no_acct} no-acct, "
              f"{no_clause} no-clause) -> {len(sel)} selected, "
              f"{per_scenario[key]['accounts_selected']} accounts", flush=True)

    EVIDENCE.write_text(json.dumps({
        "identity": _ident(sub, {"topup_fetched": n_fetched}),
        "ranking": counts, "pilot": pilot, "donors": donors,
        "per_scenario": per_scenario,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[artifact] {EVIDENCE.name} written. ZERO chat calls, "
          f"{n_fetched} embedding top-ups, ZERO Postgres writes.")
    print("PV SELECT COMPLETE", flush=True)


# ---------------------------------------------------------------------------------------
# --synthesize (the ONLY chat spend; resumable per document; every attempt counted)
# ---------------------------------------------------------------------------------------

def stage_synthesize() -> None:
    from calibration.trial_gateway import CHAT_MODEL, GatewayClient
    from calibration.layer_bc_arms import scenario_map_from_rows, taxonomy_path

    if not EVIDENCE.exists():
        raise SystemExit("run --select first")
    ev = json.loads(EVIDENCE.read_text(encoding="utf-8-sig"))
    tax = json.loads(taxonomy_path(TAXONOMY).read_text(encoding="utf-8-sig"))
    scenario_map, _ = scenario_map_from_rows(tax["rows"])

    state = (json.loads(PLAYBOOKS.read_text(encoding="utf-8-sig"))
             if PLAYBOOKS.exists() else
             {"identity": {**ev["identity"],
                           "started_at": datetime.datetime.now().isoformat(
                               timespec="seconds"),
                           "pid": os.getpid(), "model": CHAT_MODEL,
                           "temperature": CHAT_TEMPERATURE, "no_cache": True,
                           "reduce_rules": "pilot_original_hardening_dropped_by_operator"},
              "calls_used": 0, "documents": {}})

    def save() -> None:
        PLAYBOOKS.write_text(json.dumps(state, indent=1, ensure_ascii=False),
                             encoding="utf-8")

    # 1 POST per attempt so the count below is exact. timeout raised 120->600s for the
    # reasoning-model amendment: high-effort thinking on a 50-pair map prompt routinely
    # exceeds 120s, and a client-side read timeout burns a counted attempt while the
    # server may still complete (and bill) the generation.
    gw = GatewayClient(max_retries=1, timeout=600.0)

    # BUDGET AMENDMENT (operator, 2026-08-18): abandoned hardened-wording runs spent
    # v1=25, v2=6, v3=7 attempts (all preserved as pbv_playbooks_v*_abandoned.json).
    # Operator ceiling ~85 total → this state's own hard stop was 85-38 = 47.
    # MODEL AMENDMENT (operator, 2026-08-18, "use a better model one with reasoning"):
    # after landing_page::real failed 6 straight reduces under gemini-3.5-flash-lite
    # (the G-R4-incoherent scenario — fragmented candidates), the remaining documents
    # synthesize on gemini-3.5-flash with reasoning_effort=high, pilot prompt first.
    # The 6 flash-lite documents stand; pairs remain internally symmetric (both sides
    # of every remaining pair run on the same model). Budget extended to cover the
    # remaining ~4 documents + retries.
    # Raised 60->75 (2026-08-18, late): reasoning-model transport discovery (truncation,
    # client timeout, gateway 408) burned ~10 counted attempts before the working
    # low-effort configuration; the operator drove each retry and completion is the
    # directive. Running total incl. abandoned states is on the record in spec §10.2.
    PV_BUDGET = 75
    PV_CHAT_MODEL = "gemini-3.5-flash"
    # "high" was operator-requested but is UNREACHABLE through this gateway: LiteLLM
    # enforces a server-side 120s per-request cap (HTTP 408 measured 2026-08-18), and
    # high-effort thinking on a 50-pair map prompt exceeds it every time. Low effort
    # (~hundreds of reasoning tokens, per the gateway's own measurements) fits.
    # Operator-approved downgrade: "something else is the problem try low reasoning".
    PV_REASONING = "low"

    def call(prompt: str, label: str) -> dict:
        last: Exception | None = None
        for attempt in range(1, ATTEMPTS_PER_CALL + 1):
            if state["calls_used"] >= PV_BUDGET:
                save()
                raise SystemExit(f"HARD STOP: {state['calls_used']} chat attempts made "
                                 f"(amended budget {PV_BUDGET}; 25 v1 attempts on "
                                 f"record = 85 total). Ask the operator before any "
                                 f"further spend.")
            state["calls_used"] += 1
            save()                       # persist the count BEFORE the attempt
            t0 = time.time()
            try:
                # Gemini reasoning models spend THINKING tokens from the same
                # max_tokens pool as the answer — 16384 truncated the JSON mid-string
                # after ~14k of thinking (4 attempts burned, on the record). 65536
                # leaves room for both.
                parsed, usage = gw.chat_json(prompt, model=PV_CHAT_MODEL,
                                             temperature=CHAT_TEMPERATURE,
                                             max_tokens=65536, no_cache=True,
                                             reasoning_effort=PV_REASONING)
                state.setdefault("calls", []).append(
                    {"label": label, "attempt": attempt, "ok": True,
                     "model": PV_CHAT_MODEL, "reasoning": PV_REASONING,
                     "seconds": round(time.time() - t0, 1), "usage": usage})
                save()
                return parsed
            except Exception as e:      # noqa: BLE001 — logged, counted, retried
                last = e
                state.setdefault("calls", []).append(
                    {"label": label, "attempt": attempt, "ok": False,
                     "seconds": round(time.time() - t0, 1), "error": str(e)[:300]})
                save()
                print(f"  [{label}] attempt {attempt} failed: {str(e)[:160]}",
                      flush=True)
                time.sleep(4)
        raise SystemExit(f"{label}: {ATTEMPTS_PER_CALL} attempts failed; last: {last}")

    for job in doc_jobs(ev):
        if job["doc_id"] in state["documents"]:
            print(f"[skip] {job['doc_id']} already synthesized", flush=True)
            continue
        info = scenario_map[job["scenario"]]
        header = scenario_header_text(info)
        batches = [job["evidence"][i:i + BATCH_MAX]
                   for i in range(0, len(job["evidence"]), BATCH_MAX)]
        print(f"[synth] {job['doc_id']}: {len(job['evidence'])} pairs, "
              f"{len(batches)} map + 1 reduce (calls used: {state['calls_used']})",
              flush=True)
        maps = []
        for bi, batch in enumerate(batches):
            for attempt in range(1, ATTEMPTS_PER_CALL + 1):
                out = call(map_prompt(header, batch),
                           f"{job['doc_id']}/map{bi}.{attempt}")
                try:
                    validate_map(out)
                    break
                except ValueError as e:
                    print(f"  [{job['doc_id']}/map{bi}] schema reject: {e}", flush=True)
                    if attempt == ATTEMPTS_PER_CALL:
                        raise SystemExit(
                            f"{job['doc_id']}/map{bi}: never met the schema")
            maps.append(out)
        triggers = [e["trigger_text"] for e in job["evidence"]]
        # THE HARDENING IS DROPPED (operator amendment, 2026-08-18, spec §10.2): three
        # wording variants (v1/v2/v3, all on record in the abandoned state files) each
        # destabilized gemini-3.5-flash-lite's schema compliance — persistent 1-citation
        # moves — while the pilot's ORIGINAL prompt synthesized 10/10 documents cleanly.
        # The hardening served only PB1 (reported, never decisive); the PV gate is
        # untouched. This is the pilot's validated reduce prompt VERBATIM.
        for attempt in range(1, ATTEMPTS_PER_CALL + 1):
            doc = call(reduce_prompt(header, maps, triggers),
                       f"{job['doc_id']}/reduce{attempt}")
            try:
                validate_playbook(doc)
                break
            except ValueError as e:
                print(f"  [{job['doc_id']}] schema reject: {e}", flush=True)
                # Diagnostic only (no behavior change): 6 consecutive rejects on one
                # document with the reject naming a move but not the WHY is undebuggable
                # from the log. Show each move's shape so the cause is visible.
                for m in (doc.get("key_moves") or []):
                    ev = m.get("evidence")
                    print(f"    move {str(m.get('name', ''))[:44]!r}: "
                          f"crit={bool(str(m.get('criterion', '')).strip())} "
                          f"n_ev={len(ev) if isinstance(ev, list) else 'MISSING'} "
                          f"accts={[str(x.get('account', ''))[:18] for x in ev][:6] if isinstance(ev, list) else '-'}",
                          flush=True)
                if attempt == ATTEMPTS_PER_CALL:
                    raise SystemExit(f"{job['doc_id']}: reduce never met the schema")
        state["documents"][job["doc_id"]] = {
            "scenario": job["scenario"], "arm": job["arm"],
            "donor": job.get("donor"), "n_evidence": len(job["evidence"]),
            "playbook": doc}
        save()
        print(f"  -> ok ({len(doc['key_moves'])} moves)", flush=True)

    print(f"\nPV SYNTHESIS COMPLETE: {len(state['documents'])} documents, "
          f"{state['calls_used']} chat attempts (budget {PV_BUDGET}; +25 v1 on record).",
          flush=True)


# ---------------------------------------------------------------------------------------
# --snap / --pb0 / --build-read / --score (all free; the snap-trial shapes verbatim)
# ---------------------------------------------------------------------------------------

def _load_ev_pb() -> tuple[dict, dict]:
    if not (EVIDENCE.exists() and PLAYBOOKS.exists()):
        raise SystemExit("need pbv_evidence.json and pbv_playbooks.json")
    ev = json.loads(EVIDENCE.read_text(encoding="utf-8-sig"))
    pb = json.loads(PLAYBOOKS.read_text(encoding="utf-8-sig"))
    # Synthesis-completeness assert (audit 9.5 finding 2): a killed --synthesize leaves
    # a partial documents dict, and PB0 over a subset would print a misleading PASS at
    # n_real < 5. Every consumer of these artifacts requires the full 2-per-pilot set.
    want = 2 * len(ev["pilot"])
    if len(pb.get("documents", {})) != want:
        raise SystemExit(f"pbv_playbooks.json holds {len(pb.get('documents', {}))} "
                         f"documents, expected {want} — synthesis incomplete; resume "
                         f"--synthesize first")
    return ev, pb


def stage_snap() -> None:
    if SNAPPED.exists():
        raise SystemExit(f"{SNAPPED.name} exists — refusing to clobber")
    ev, pb = _load_ev_pb()
    from calibration.playbook_snap_trial import SNAP_MIN_SCORE
    out = {"identity": {"generated_at": datetime.datetime.now().isoformat(
                            timespec="seconds"),
                        "seed": SEED, "snap_min_score": SNAP_MIN_SCORE,
                        "source": PLAYBOOKS.name,
                        "source_calls_used": pb.get("calls_used")},
           "documents": {}}
    for doc_id, rec in sorted(pb["documents"].items()):
        snapped, log = snap_doc(rec["playbook"], doc_evidence(ev, rec))
        out["documents"][doc_id] = {**{k: v for k, v in rec.items() if k != "playbook"},
                                    "playbook": snapped, "snap_log": log}
        print(f"  [{doc_id[:52]:<52}] kept {log['kept']:>2} snapped {log['snapped']} "
              f"dropped {log['dropped']} moves_dropped {len(log['dropped_moves'])}"
              f"{'  ** SCHEMA COLLAPSED **' if log['schema_collapsed'] else ''}",
              flush=True)
    SNAPPED.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[artifact] {SNAPPED.name} written. ZERO chat calls.")
    print("PV SNAP COMPLETE", flush=True)


def stage_pb0() -> None:
    if PB0_REPORT.exists():
        raise SystemExit(f"{PB0_REPORT.name} exists — refusing to clobber")
    ev, _ = _load_ev_pb()
    sn = json.loads(SNAPPED.read_text(encoding="utf-8-sig"))
    report, real_pass = {}, 0
    for doc_id, rec in sorted(sn["documents"].items()):
        res = pb0_doc(rec["playbook"], doc_evidence(ev, rec))
        if rec["snap_log"]["schema_collapsed"]:
            res = {**res, "pass": False,
                   "failures": res["failures"] + [{"reason": "schema_collapsed",
                                                   "path": "key_moves"}]}
        report[doc_id] = {"arm": rec["arm"], **res}
        real_pass += rec["arm"] == "real" and res["pass"]
        print(f"  [{doc_id[:52]:<52}] {'PASS' if res['pass'] else 'FAIL':<5} "
              f"{res['n_quotes']:>3}q {len(res['failures'])}bad", flush=True)
    n_real = sum(1 for r in sn["documents"].values() if r["arm"] == "real")
    verdict = "PASS" if real_pass == n_real else "FAIL"
    print(f"\nPB0(snapped, new map): {real_pass}/{n_real} real -> {verdict}")
    reasons = {f["reason"] for r in report.values() for f in r["failures"]}
    quote_reasons = reasons - {"schema_collapsed", "account mismatch"}
    if quote_reasons:
        print(f"!! quote-level PB0 failures on SNAPPED documents ({quote_reasons}) — "
              f"by design impossible: HARNESS BUG, veto-audit code AND output.")
    PB0_REPORT.write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "verdict": verdict, "real_pass": real_pass, "n_real": n_real,
        "per_document": report}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {PB0_REPORT.name}")
    print("PV PB0 COMPLETE", flush=True)


def stage_build_read() -> None:
    import random
    if PACKET.exists() or KEY.exists():
        raise SystemExit("read packet / KEY already exist — refusing to clobber")
    ev, _ = _load_ev_pb()
    sn = json.loads(SNAPPED.read_text(encoding="utf-8-sig"))
    from calibration.layer_bc_arms import scenario_map_from_rows, taxonomy_path
    tax = json.loads(taxonomy_path(TAXONOMY).read_text(encoding="utf-8-sig"))
    scenario_map, _ = scenario_map_from_rows(tax["rows"])

    rng = random.Random(SEED)
    docs = sn["documents"]
    all_playbooks = [r["playbook"] for _, r in sorted(docs.items())
                     if r["playbook"].get("key_moves")]
    real_side_of = {key: counterbalanced_side(i) for i, key in enumerate(ev["pilot"])}

    used = set(ev["pilot"]) | set(ev["donors"].values())
    neg_headers = [k for k in sorted(ev["ranking"], key=lambda k: (-ev["ranking"][k], k))
                   if k not in used][:N_NEG]
    if len(neg_headers) < N_NEG:
        raise SystemExit("not enough non-pilot non-donor scenarios for NEG headers")
    items = ([("PAIR", key) for key in ev["pilot"]]
             + [("NEG", h) for h in neg_headers])
    rng.shuffle(items)

    lines = list(PACKET_HEADER)
    key_rows = []
    for i, (kind, scen) in enumerate(items, 1):
        info = scenario_map[scen]
        head = f"SCENARIO: {scen}\n  {info.get('business_description', '')}"
        if kind == "PAIR":
            real = docs[f"{scen}::real"]["playbook"]
            plc = docs[f"{scen}::placebo"]["playbook"]
            real_side = real_side_of[scen]        # counterbalanced, not a coin
            a, b = (real, plc) if real_side == "A" else (plc, real)
            lines += [f"--- ITEM {i} (PAIR) ---", head, "DOCUMENT A:"]
            lines += render_doc(a)
            lines.append("DOCUMENT B:")
            lines += render_doc(b)
            key_rows.append({"item": i, "kind": "PAIR", "scenario": scen,
                             "real_side": real_side,
                             "n_moves_real": len(real["key_moves"])})
        else:
            neg = build_neg(all_playbooks, rng)
            lines += [f"--- ITEM {i} (SINGLE) ---", head, "DOCUMENT:"]
            lines += render_doc(neg)
            key_rows.append({"item": i, "kind": "NEG", "header_scenario": scen})
        lines.append("")
    lines += [
        "=" * 96,
        "REQUIRED ANSWER FORMAT — one JSON object, nothing else:",
        '{"1": {"choice": "A", "apply_A": ["APPLY", ...], "apply_B": ["VAGUE", ...]},',
        ' "2": {"answer": "NO"}, ...}',
        "PAIR items take choice/apply_A/apply_B (one rating per KEY MOVE, display",
        "order); SINGLE items take answer. Every item number must appear.",
    ]
    PACKET.write_text("\n".join(lines), encoding="utf-8")
    KEY.write_text(json.dumps({
        "seed": SEED, "generated_at": datetime.datetime.now().isoformat(
            timespec="seconds"),
        "counterbalanced": True,
        "composition": dict(Counter(k for k, _ in items)),
        "items": key_rows}, indent=1), encoding="utf-8")
    print(f"wrote {PACKET.name} ({len(items)} items) and {KEY.name} "
          f"(readers must NEVER see the key)")
    print("real sides (counterbalanced):",
          {k: real_side_of[k] for k in ev["pilot"]})
    print("PV PACKET READY", flush=True)


def stage_score() -> None:
    if REPORT.exists():
        raise SystemExit(f"{REPORT.name} exists — refusing to clobber")
    ev, pb = _load_ev_pb()
    sn = json.loads(SNAPPED.read_text(encoding="utf-8-sig"))
    key = json.loads(KEY.read_text(encoding="utf-8-sig"))
    jd_files = sorted(ARTIFACTS_DIR.glob(JUDGMENTS_GLOB))
    if not jd_files:
        raise SystemExit("no judgment files — dispatch blinded readers first")
    judgments = [json.loads(f.read_text(encoding="utf-8-sig")) for f in jd_files]
    print(f"[score] {len(judgments)} judgment file(s): "
          + ", ".join(f.name for f in jd_files))

    real_moves = {r["scenario"]: len(r["playbook"]["key_moves"])
                  for r in sn["documents"].values() if r["arm"] == "real"}
    read = score_read(key, judgments, real_moves)

    pb1 = {}
    for doc_id, rec in sorted(sn["documents"].items()):
        if rec["arm"] != "real":
            continue
        pb1[rec["scenario"]] = pb1_doc_resized(rec["playbook"], doc_evidence(ev, rec))
    pb1_pass = sum(1 for r in pb1.values() if r["pass"])
    pb0 = (json.loads(PB0_REPORT.read_text(encoding="utf-8-sig"))
           if PB0_REPORT.exists() else {"verdict": "NOT RUN"})

    won = read.get("pb2", {}).get("won", False)
    pv_pass = pb0.get("verdict") == "PASS" and won
    print("=" * 88)
    print(f"PB0(snapped) {pb0.get('verdict')} | PB1(resized) {pb1_pass}/{len(pb1)} "
          f"({'PASS' if pb1_pass >= 4 else 'FLAG'}) | "
          f"PB2 {'WON' if won else read.get('verdict', 'NOT WON')} | "
          f"PB3 {'PASS' if read.get('pb3', {}).get('pass') else 'FLAG/VOID'}")
    print(f"PV GATE {'PASS — THE REBUILT MAP SHIPS AS THE PLAYBOOK SUBSTRATE' if pv_pass else 'NOT PASSED'} "
          f"(decision rule: PB0 PASS and PB2 WON)")
    print("=" * 88)
    REPORT.write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "taxonomy": TAXONOMY,
        "pb0_verdict": pb0.get("verdict"),
        "pb1_resized": {"per_scenario": pb1, "n_pass": pb1_pass,
                        "pass": pb1_pass >= 4},
        "read": read,
        "pv_pass": pv_pass,
        "chat_attempts_used": pb.get("calls_used"),
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {REPORT.name}")
    print("PV SCORED", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--select", action="store_true")
    p.add_argument("--synthesize", action="store_true")
    p.add_argument("--snap", action="store_true")
    p.add_argument("--pb0", action="store_true")
    p.add_argument("--build-read", action="store_true")
    p.add_argument("--score", action="store_true")
    a = p.parse_args()
    if a.select:
        stage_select()
    if a.synthesize:
        stage_synthesize()
    if a.snap:
        stage_snap()
    if a.pb0:
        stage_pb0()
    if a.build_read:
        stage_build_read()
    if a.score:
        stage_score()
    if not any([a.select, a.synthesize, a.snap, a.pb0, a.build_read, a.score]):
        p.print_help()


if __name__ == "__main__":
    main()
