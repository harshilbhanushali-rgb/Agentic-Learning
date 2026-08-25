#!/usr/bin/env python3
"""LAYER C BACKFILL — synthesize playbooks for scenarios that do not have one.

Handoff: Brain/HANDOFF_LAYER_C_BACKFILL_2026-08-20.md
Config licensed by the quote-floor A/B (docs/superpowers/specs/2026-08-20-quote-floor-ab-design.md
and docs/findings/layer-c-playbook-schema-and-gateway.md §10/§10b):

    model  gemini-3.6-flash        reasoning  medium
    prompt MIN_EVIDENCE_PER_MOVE=3, hardened _REQUIRE, quote-relevance rule

Measured on 5 scenarios against that config: PB0 5/5, ZERO failing quotes on a blind read,
95% of quotes judged to demonstrate their move (vs 63% for the shipped playbooks).

*** RUN THE THREE THIN SCENARIOS FIRST. *** The A/B was measured only on RICH scenarios
(104-771 routed pairs, all hitting the 50-pair selection cap). Three of the 29 have 16-21
pairs total, so the model sees roughly a third of the evidence. The relevance rule tells it to
"DROP the move rather than keep it on weak evidence", which on a thin pool can cascade below
the 3-move floor and collapse the document. That is the pre-registered exclusion rule firing
correctly, not a bug -- but it is UNTESTED at this pool size, so it costs ~9 calls to learn
rather than discovering it 80 calls into a 90-call run.

Everything here is the validated pipeline's own machinery, imported, never paraphrased: the
substrate + routing (`playbook_validation.build_pv_substrate`), the account map, the frozen
selection (`scenario_playbook_trial.select_evidence`), map/reduce prompts, the hardened reduce
rules, the verbatim snap, PB0 and PB1.

SAFETY
  * Its own `pbf_*` artifact prefix. Touches no published artifact and no `pbq_*` A/B output.
  * Writes NOTHING to Postgres. Loading is a separate, later step via ops/load_playbooks.py.
  * Dry run by default; --synthesize is required to spend.
  * Every attempt counted and persisted BEFORE use; resumable, and a resume cannot double-pay
    for a document already finished.
  * Hard stop at --ceiling attempts.
  * Selection vectors are served cache-only and a miss ABORTS -- this harness must never
    silently start paying for embeddings.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/playbook_backfill.py --band thin           # plan
    ..\\.venv\\Scripts\\python.exe calibration/playbook_backfill.py --band thin --synthesize
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402
from calibration.playbook_snap_trial import snap_doc  # noqa: E402
from calibration.playbook_validation import pv_reduce_prompt  # noqa: E402
from calibration.scenario_playbook_trial import (  # noqa: E402
    ACCT_FLOOR,
    ATTEMPTS_PER_CALL,
    BATCH_MAX,
    CHAT_TEMPERATURE,
    MIN_EVIDENCE_PER_MOVE,
    N_EVIDENCE_MAX,
    SEED,
    build_pool,
    map_prompt,
    pb0_doc,
    pb1_doc,
    scenario_header_text,
    select_evidence,
    validate_map,
    validate_playbook,
)

WIDTH = 3072
CHAT_MODEL = "gemini-3.6-flash"
REASONING = "medium"

# The three scenarios the licensed config was NOT measured on. 16-21 routed pairs each,
# against 104-771 for every scenario in the A/B.
THIN = ["non_technical_stakeholder_translation",
        "geographic_targeting_and_location_mapping",
        "multi_language_copy_and_translation"]


def arts(tag: str) -> dict:
    return {k: ARTIFACTS_DIR / f"pbf_{tag}_{k}.json"
            for k in ("evidence", "state", "playbooks", "snapped", "report")}


def _no_clobber(p: Path) -> None:
    if p.exists():
        raise SystemExit(f"{p.name} exists — refusing to overwrite. Move it aside "
                         f"deliberately if a re-run is intended.")


def scenarios_without_live_playbook(exclude: list[str]) -> list[str]:
    """Every coachable scenario with no live playbook, minus `exclude`.

    Derived from Postgres rather than hardcoded: the list must follow what is actually
    loaded, or a re-run after a partial load re-synthesizes documents already paid for.
    """
    import psycopg

    from config import load_config

    url = load_config().database_url
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + "hostaddr=18.138.49.39"
    with psycopg.connect(url, connect_timeout=30, autocommit=True) as c, c.cursor() as cur:
        cur.execute("""
            SELECT s.scenario_key FROM scenarios s
            WHERE s.is_coachable
              AND NOT EXISTS (SELECT 1 FROM playbooks p
                              WHERE p.scenario_key = s.scenario_key AND p.status = 'live')
            ORDER BY s.scenario_key
        """)
        keys = [r[0] for r in cur.fetchall()]
    return [k for k in keys if k not in set(exclude)]


def build_evidence(scenarios: list[str], TOPUP_CEILING: int = 500) -> dict:
    """Frozen selection for each scenario. Cache-only; a miss ABORTS rather than spending."""
    from calibration import layer_b_arms as lb
    from calibration.expanded_pool_stage1 import merge_account_maps
    from calibration.flag_proper_noun_clusters import account_map
    from calibration.layer_bc_arms import _load_cached
    from calibration.playbook_validation import build_pv_substrate
    from preprocessing import segmenter

    sub = build_pv_substrate()
    acct_old, _ = account_map("recordings")
    acct_new, _ = account_map("recordings_pull_keep")
    if not acct_old or not acct_new:
        raise SystemExit("ABORT: an account map came back empty — missing sidecars")
    acct, _ = lb.collapse_sibling_domains(merge_account_maps([acct_old, acct_new]))

    missing_keys = [k for k in scenarios if k not in sub["by_key"]]
    if missing_keys:
        raise SystemExit(f"ABORT: no routed pairs for {missing_keys}")

    out = {"identity": {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                        "seed": SEED, "corpus_sha": sub["corpus_sha"],
                        "taxonomy_sha": sub["taxonomy_sha"],
                        "n_evidence_max": N_EVIDENCE_MAX, "acct_floor": ACCT_FLOOR},
           "per_scenario": {}}
    pools = {}
    for key in scenarios:
        pool, no_acct, no_clause = build_pool(sub["by_key"][key], acct,
                                              segmenter.segment_into_clauses)
        if not pool:
            raise SystemExit(f"ABORT: empty evidence pool for {key!r}")
        pools[key] = (pool, no_acct, no_clause)

    texts = sorted({p["unit_text"] for pool, _, _ in pools.values() for p in pool})
    mat, missing = _load_cached(texts, WIDTH)
    if mat is None:
        # A BOUNDED top-up, mirroring playbook_validation.stage_select. The first version of
        # this aborted outright, which was stricter than the validated pipeline it copies and
        # cost a 20-minute substrate rebuild to learn that 19 vectors were missing.
        #
        # Why any are missing at all: ship_layer_b embedded `response_text`, but the SELECTION
        # vector is `unit_text` -- the u_turn unit from the clause segmenter -- a related but
        # distinct population. A scenario never included in a prior selection has never had
        # its unit texts bought.
        #
        # The ceiling is what keeps this honest. A handful of misses is a legitimate top-up;
        # thousands would mean the cache eroded, which is a HALT-and-ask condition, not
        # something to pay for silently.
        if len(missing) > TOPUP_CEILING:
            raise SystemExit(
                f"TOP-UP CEILING: {len(missing)} uncached selection vectors "
                f"(> {TOPUP_CEILING}). That is not a top-up, it is an eroded cache. HALT and "
                f"ask before re-paying. e.g. {missing[:2]!r}")
        from calibration.trial_pool_unit_gemini import embed_cached
        print(f"[top-up] {len(missing)} selection vector(s) uncached — fetching (bounded, "
              f"ceiling {TOPUP_CEILING})", flush=True)
        embed_cached(sorted(missing), 6)
        mat, still = _load_cached(texts, WIDTH)
        if still:
            raise SystemExit(f"ABORT: {len(still)} text(s) STILL uncached after the top-up")
    idx = {t: i for i, t in enumerate(texts)}

    for key, (pool, no_acct, no_clause) in pools.items():
        sub_mat = mat[[idx[p["unit_text"]] for p in pool]]
        chosen = select_evidence(pool, sub_mat, N_EVIDENCE_MAX,
                                 min(ACCT_FLOOR, len({p["account"] for p in pool})))
        sel = [pool[i] for i in chosen]
        out["per_scenario"][key] = {
            "routed_pairs": len(sub["by_key"][key]), "pool_accounted": len(pool),
            "excluded_no_account": no_acct, "excluded_no_clause": no_clause,
            "accounts_in_pool": len({p["account"] for p in pool}),
            "accounts_selected": len({p["account"] for p in sel}), "selected": sel}
        n_pool_accts = len({p["account"] for p in pool})
        n_sel_accts = len({p["account"] for p in sel})
        print(f"[select] {key:<48} pool={len(pool):>4} accts={n_pool_accts:>3} "
              f"selected={len(sel):>3} sel_accts={n_sel_accts:>3}", flush=True)
    return out


def synthesize(ev: dict, A: dict, ceiling: int) -> None:
    from shared.gateway import GatewayClient

    from calibration.quote_floor_ab import scenario_map_from_db

    _no_clobber(A["playbooks"])
    _no_clobber(A["snapped"])
    smap = scenario_map_from_db()

    state = (json.loads(A["state"].read_text(encoding="utf-8-sig"))
             if A["state"].exists() else
             {"calls_used": 0, "documents": {}, "calls": [],
              "identity": {"started_at": datetime.datetime.now().isoformat(timespec="seconds"),
                           "seed": SEED, "model": CHAT_MODEL, "reasoning": REASONING,
                           "temperature": CHAT_TEMPERATURE, "no_cache": True,
                           "min_evidence_per_move": MIN_EVIDENCE_PER_MOVE,
                           "reduce_rules": "hardened_3entry_plus_quote_relevance",
                           "licensed_by": "pbq A/B, 2026-08-20"}})

    def save() -> None:
        A["state"].write_text(json.dumps(state, indent=1, ensure_ascii=False),
                              encoding="utf-8")

    with GatewayClient() as gw:
        def call(prompt: str, label: str) -> dict:
            last = None
            for attempt in range(1, ATTEMPTS_PER_CALL + 1):
                if state["calls_used"] >= ceiling:
                    save()
                    raise SystemExit(f"HARD STOP: {state['calls_used']} attempts against a "
                                     f"ceiling of {ceiling}. Ask before more spend.")
                state["calls_used"] += 1
                save()
                t0 = time.time()
                try:
                    parsed, usage = gw.chat_json(prompt, model=CHAT_MODEL,
                                                 temperature=CHAT_TEMPERATURE,
                                                 max_tokens=65536, no_cache=True,
                                                 reasoning_effort=REASONING)
                    state["calls"].append({"label": label, "attempt": attempt, "ok": True,
                                           "seconds": round(time.time() - t0, 1),
                                           "usage": usage})
                    save()
                    return parsed
                except Exception as e:                      # noqa: BLE001 — counted
                    last = e
                    state["calls"].append({"label": label, "attempt": attempt, "ok": False,
                                           "seconds": round(time.time() - t0, 1),
                                           "error": str(e)[:300]})
                    save()
                    print(f"  [{label}] attempt {attempt} failed: {str(e)[:150]}", flush=True)
                    time.sleep(4)
            raise SystemExit(f"{label}: {ATTEMPTS_PER_CALL} attempts failed; last: {last}")

        for scen in sorted(ev["per_scenario"]):
            if scen in state["documents"]:
                print(f"[skip] {scen} already synthesized", flush=True)
                continue
            sel = ev["per_scenario"][scen]["selected"]
            header = scenario_header_text(smap[scen])
            batches = [sel[i:i + BATCH_MAX] for i in range(0, len(sel), BATCH_MAX)]
            print(f"[synth] {scen}: {len(sel)} pairs, {len(batches)} map + 1 reduce "
                  f"(used {state['calls_used']}/{ceiling})", flush=True)
            maps = []
            for bi, b in enumerate(batches):
                for attempt in range(1, ATTEMPTS_PER_CALL + 1):
                    out = call(map_prompt(header, b), f"{scen}/map{bi}.{attempt}")
                    try:
                        validate_map(out)
                        break
                    except ValueError as e:
                        print(f"  [{scen}/map{bi}] schema reject: {e}", flush=True)
                        if attempt == ATTEMPTS_PER_CALL:
                            raise SystemExit(f"{scen}/map{bi}: never met the schema")
                maps.append(out)
            trig = [e["trigger_text"] for e in sel]
            for attempt in range(1, ATTEMPTS_PER_CALL + 1):
                doc = call(pv_reduce_prompt(header, maps, trig), f"{scen}/reduce.{attempt}")
                try:
                    validate_playbook(doc)
                    break
                except ValueError as e:
                    print(f"  [{scen}/reduce] schema reject: {e}", flush=True)
                    if attempt == ATTEMPTS_PER_CALL:
                        raise SystemExit(f"{scen}/reduce: never met the schema")
            state["documents"][scen] = {"scenario": scen, "arm": "real",
                                        "n_evidence": len(sel), "playbook": doc}
            save()
            print(f"  [{scen}] done, {len(doc.get('key_moves') or [])} moves", flush=True)

    A["playbooks"].write_text(json.dumps(
        {"identity": state["identity"], "calls_used": state["calls_used"],
         "documents": state["documents"]}, indent=1, ensure_ascii=False), encoding="utf-8")

    out = {"identity": state["identity"], "documents": {}}
    for scen, rec in sorted(state["documents"].items()):
        sel = ev["per_scenario"][scen]["selected"]
        snapped, log = snap_doc(rec["playbook"], sel)
        out["documents"][f"{scen}::real"] = {**{k: v for k, v in rec.items()
                                                if k != "playbook"},
                                             "playbook": snapped, "snap_log": log}
        print(f"  [snap {scen}] kept {log['kept']} snapped {log['snapped']} "
              f"dropped {log['dropped']}"
              f"{'  ** SCHEMA COLLAPSED **' if log['schema_collapsed'] else ''}", flush=True)
    A["snapped"].write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")


def report(ev: dict, A: dict) -> None:
    snap = json.loads(A["snapped"].read_text(encoding="utf-8-sig"))
    rows, collapsed = [], []
    print(f"\n{'scenario':<48} {'pairs':>6} {'moves':>6} {'quotes':>7} "
          f"{'PB1':>7} {'1-acct':>7} {'PB0':>5}")
    print("-" * 96)
    tot_m = tot_ok = tot_single = 0
    for k, d in sorted(snap["documents"].items()):
        scen = d["scenario"]; sel = ev["per_scenario"][scen]["selected"]
        pb = d["playbook"]; moves = pb.get("key_moves") or []
        r = pb1_doc(pb, sel); ok = sum(1 for m in r["per_move"] if m["ok"])
        nq = sum(len(m.get("evidence") or []) for m in moves)
        single = sum(1 for m in moves
                     if len({e.get("account") for e in (m.get("evidence") or [])}) == 1)
        p0 = bool(pb0_doc(pb, sel).get("pass"))
        if d.get("snap_log", {}).get("schema_collapsed"):
            collapsed.append(scen)
        tot_m += len(moves); tot_ok += ok; tot_single += single
        print(f"{scen:<48} {len(sel):>6} {len(moves):>6} {nq:>7} "
              f"{ok}/{len(moves):<5} {single:>7} {str(p0):>5}")
        rows.append({"scenario": scen, "moves": len(moves), "quotes": nq,
                     "pb1_ok": ok, "single_account": single, "pb0": p0})
    print("-" * 96)
    print(f"moves {tot_m}   PB1 per-move {tot_ok}/{tot_m} = "
          f"{100 * tot_ok / max(tot_m, 1):.0f}%   "
          f"single-account moves {tot_single}/{tot_m} = "
          f"{100 * tot_single / max(tot_m, 1):.0f}%")
    if collapsed:
        print(f"\nSCHEMA COLLAPSED (excluded per the pre-registered rule): {collapsed}")
    A["report"].write_text(json.dumps({"rows": rows, "collapsed": collapsed}, indent=1),
                           encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--band", choices=("thin", "rest"),
                   help="thin = the 3 evidence-poor scenarios; rest = every coachable "
                        "scenario with no live playbook, EXCLUDING those 3")
    p.add_argument("--topup-ceiling", type=int, default=500,
                   help="max uncached selection vectors to buy. Above this it HALTS: that "
                        "many misses means an eroded cache, not a top-up.")
    p.add_argument("--scenarios", help="comma-separated scenario keys")
    p.add_argument("--tag", help="artifact tag (defaults to the band name)")
    p.add_argument("--synthesize", action="store_true", help="SPENDS chat calls")
    p.add_argument("--report", action="store_true", help="free: re-report")
    p.add_argument("--ceiling", type=int, default=15, help="hard stop on chat attempts")
    a = p.parse_args()

    if a.band == "thin":
        scenarios = THIN
    elif a.band == "rest":
        scenarios = scenarios_without_live_playbook(THIN)
    else:
        scenarios = [s.strip() for s in a.scenarios.split(",")] if a.scenarios else None
    if not scenarios:
        raise SystemExit("give --band or --scenarios")
    tag = a.tag or a.band or "custom"
    A = arts(tag)
    print(f"[run] {len(scenarios)} scenario(s), model={CHAT_MODEL} reasoning={REASONING}, "
          f"artifacts=pbf_{tag}_*")

    if A["evidence"].exists():
        ev = json.loads(A["evidence"].read_text(encoding="utf-8-sig"))
        print(f"[select] reusing {A['evidence'].name}")
    else:
        ev = build_evidence(scenarios, a.topup_ceiling)
        A["evidence"].write_text(json.dumps(ev, indent=1, ensure_ascii=False),
                                 encoding="utf-8")
        print(f"[write] {A['evidence'].name}")

    if a.report:
        report(ev, A)
        return
    if not a.synthesize:
        n = sum((len(v["selected"]) + BATCH_MAX - 1) // BATCH_MAX + 1
                for v in ev["per_scenario"].values())
        print(f"\n[budget] {n} calls if nothing retries, ceiling {a.ceiling}")
        print("DRY — nothing spent. Re-run with --synthesize.")
        return
    synthesize(ev, A, a.ceiling)
    report(ev, A)


if __name__ == "__main__":
    main()
