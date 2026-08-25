#!/usr/bin/env python3
"""QUOTE-FLOOR A/B (PBQ) — does the 3-entry floor make PB1 reachable, and does the output
change for the better?

Spec: docs/superpowers/specs/2026-08-20-quote-floor-ab-design.md (gates G-Q1..G-Q6 FROZEN
there before this file existed). Finding that motivated it:
docs/findings/layer-c-playbook-schema-and-gateway.md §9.

*** G-Q1 WAS DELIBERATELY UNFROZEN ON 2026-08-24, BY OPERATOR DECISION. ***
This is the one exception to "gates are frozen before code", and it is recorded here rather
than quietly applied, because a changed bar that still calls itself frozen is worse than
either state. G-Q1 was per-move PB1 >= 70%; it is now single-account moves <= 10%. PB1 is
still computed and reported, and is now NON-DECISIVE. The reason is in full at
G_Q1_SINGLE_ACCOUNT_MAX below: PB1 rejected a real improvement twice (§11.1, §12), because it
measures evidence breadth at a granularity where breadth and specificity genuinely trade off.
Every arm measured before this date was scored against the OLD bar -- when comparing this
run's verdict to a historical one, compare `new_rate` (PB1, still in the report) not the
G-Q1 verdict.

WHAT THIS IS. `MIN_EVIDENCE_PER_MOVE` was raised 2 -> 3 and the diversity instruction
hardened, because PB1 (>= 3 distinct accounts per move) was ARITHMETICALLY UNREACHABLE while
the prompt permitted 2-quote moves. That change has ZERO model evidence behind it. This spends
~15-25 chat calls on 5 documents to test it before ~90 are spent on 29.

  OLD arm  the 5 LIVE playbooks exactly as shipped        cost 0, they already exist
  NEW arm  the same 5 scenarios, re-synthesized           cost ~15-25 calls

PAIRED ON EVIDENCE, AND THAT PART IS EXACT. The NEW arm reuses the OLD arm's selected 50 pairs
verbatim from `pbv_evidence.json` -- same scenarios, same pairs, same order. No re-selection,
no embedding, no routing. G-Q5 asserts it rather than trusting it.

*** NOT SINGLE-VARIABLE ON THE PROMPT, AND THAT IS STATED RATHER THAN HIDDEN. *** The OLD arm's
identity records `reduce_rules: "pilot_original_hardening_dropped_by_operator"`, i.e. it ran the
SOFT "Prefer ... DISTINCT accounts" wording. The NEW arm runs the 3-entry floor AND the hardened
_REQUIRE. So this is a CONFIG-level comparison -- "old shipped config vs new shipped config" --
not an attribution of any effect to one of the two changes. Attribution needs a third arm.

*** MODEL CONFOUND, RECORDED. *** `pbv_playbooks.json` identity says `gemini-3.5-flash-lite`,
but `playbook_validation.PV_CHAT_MODEL` is `gemini-3.5-flash` with a note that 6 flash-lite
documents stand and later ones ran on flash. There is NO per-document model provenance, so the
OLD arm may be mixed. NEW runs entirely on flash-lite (what the artifact records). A narrow gate
failure must name this as a candidate explanation.

SAFETY:
  * Writes ONLY to `pbq_*`. NO `pbv_*` file is touched -- those are published and are the
    source of the 5 live playbooks.
  * Writes NOTHING to Postgres. The `playbooks` table is untouched; promoting anything is a
    separate operator decision.
  * `no_cache=True` on every call -- the gateway caches completions and an echo would fake
    agreement between the arms.
  * Every attempt is counted and persisted BEFORE its result is used, so a crash cannot lose
    paid work and a resume cannot double-spend.
  * HARD STOP at CALL_CEILING attempts (G-Q6).

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/quote_floor_ab.py --plan       # free, no calls
    ..\\.venv\\Scripts\\python.exe calibration/quote_floor_ab.py --synthesize # SPENDS
    ..\\.venv\\Scripts\\python.exe calibration/quote_floor_ab.py --report     # free
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
    ATTEMPTS_PER_CALL,
    BATCH_MAX,
    CHAT_TEMPERATURE,
    MIN_EVIDENCE_PER_MOVE,
    SEED,
    map_prompt,
    pb0_doc,
    pb1_doc,
    scenario_header_text,
    validate_map,
    validate_playbook,
)

# The OLD arm's inputs. READ ONLY -- never written by this harness.
PBV_EVIDENCE = ARTIFACTS_DIR / "pbv_evidence.json"
PBV_SNAPPED = ARTIFACTS_DIR / "pbv_playbooks_snapped.json"

CHAT_MODEL = "gemini-3.5-flash-lite"     # what the OLD arm's identity records

# Reasoning effort is a RUN VARIABLE, and each level gets its own artifact set so one run can
# never overwrite another's. `low` keeps the bare `pbq_` names it already wrote under.
#
# *** high IS UNREACHABLE THROUGH THIS GATEWAY *** — LiteLLM enforces a server-side ~120s
# per-request cap and high-effort thinking on a 50-pair map prompt exceeds it every time
# (HTTP 408, measured 2026-08-18). `medium` is UNTESTED; the low-effort run already took one
# 408 on a map call, so medium may burn retries on timeouts. Every timeout is a counted
# attempt against CALL_CEILING, which is what bounds the damage.
REASONING = "low"

STATE = PLAYBOOKS = SNAPPED = REPORT = None      # set by _bind_artifacts()


_DEFAULT_MODEL = "gemini-3.5-flash-lite"


def _short(model: str) -> str:
    """gemini-3.5-flash-lite -> 35lite ; gemini-3.6-flash -> 36flash"""
    s = model.replace("gemini-", "").replace("-preview", "")
    return s.replace(".", "").replace("-flash-lite", "lite").replace("-flash", "flash")


def _bind_artifacts(effort: str, model: str = _DEFAULT_MODEL, tag_suffix: str = "") -> None:
    global REASONING, CHAT_MODEL, STATE, PLAYBOOKS, SNAPPED, REPORT
    REASONING = effort
    CHAT_MODEL = model
    # The baseline run (default model, low effort) keeps the bare `pbq_` names it already
    # wrote under. Every other combination gets its own set, so no run can overwrite another
    # and all of them stay comparable side by side.
    tag = ("pbq" if (effort == "low" and model == _DEFAULT_MODEL)
           else f"pbq_{_short(model)}_{effort}")
    # A prompt change needs its own artifact set too, or it silently overwrites the run it
    # is meant to be compared against.
    if tag_suffix:
        tag = f"{tag}_{tag_suffix}"
    STATE = ARTIFACTS_DIR / f"{tag}_state.json"
    PLAYBOOKS = ARTIFACTS_DIR / f"{tag}_playbooks.json"
    SNAPPED = ARTIFACTS_DIR / f"{tag}_snapped.json"
    REPORT = ARTIFACTS_DIR / f"{tag}_report.json"


_bind_artifacts("low")
CALL_CEILING = 25                        # G-Q6, hard stop

# PB1 IS NO LONGER A GATE (operator decision, 2026-08-24). It is REPORTED, never decisive.
#
# Why it was retired: PB1 (>=3 quotes AND >=3 distinct accounts per move) rejected a genuine
# improvement TWICE. The relevance rule drove failing quotes to zero and PB1 77%->67%, because
# the moves it dropped were disproportionately PB1-passers (findings §11.1). The gradability
# rule drove banned adjectives to zero and PB1 67%->56% (§12). Holding the bar would have
# rejected the only configs that improved what a reader actually gets. §10b already recorded
# the underlying reason: "PB1 is an evidence-breadth check, not a quality judgement", and a
# move specific enough to be actionable tends to be demonstrated in depth by one or two
# clients -- so breadth and specificity are in genuine tension at MOVE granularity.
#
# What replaces it, and why this bar is not arbitrary: SINGLE-ACCOUNT MOVES <= 10%. It targets
# the actual risk PB1 was a proxy for -- a move that is really one client's quirk -- without
# punishing a well-evidenced move for citing two accounts instead of three. Measured over the
# 33 live documents (calibration/playbook_gradability_census.py, 2026-08-24) it separates the
# cohorts the qualitative read already distrusted from the one it did not:
#     backfill-25 (licensed config)   7%  PASS
#     original-5  (old config)       15%  FAIL
#     thin-3      (16-21 pairs)      22%  FAIL
# A gate that agrees with the independent read is worth more than one that fights it.
G_Q1_SINGLE_ACCOUNT_MAX = 0.10           # G-Q1, replaces the retired PB1 bar
G_Q4_FLOOR_RATE = 0.90                   # G-Q4, DIAGNOSTIC since 2026-08-24 (see below)

# *** G-Q1 IS A CENSUS-SCALE BAR AND IS COARSE ON A 5-DOCUMENT PROBE. ***
# 10% was calibrated on the 123-move census of live documents, where the resolution is 0.8pp.
# A 5-document probe carries ~18-22 moves, so the achievable values are 0%, 5.6%, 11.1%,
# 16.7% -- there is NOTHING between 5.6% and 11.1%, and "11% vs a 10% bar" is one move, not a
# real distinction. The bar is NOT lowered to accommodate that (capping a bar to meet the
# result is the anti-pattern §9 already reverted). Instead G-Q7 below asks the question a
# probe can actually answer.
#
# *** G-Q4 WAS DEMOTED TO DIAGNOSTIC ON 2026-08-24. ***
# It asks "did the 3-entry floor take?" -- a TREATMENT-VERIFICATION check, not a quality one.
# It served that purpose: the floor took at 100% on the 3.6-flash medium and +relevance arms
# (§10b). But the relevance and gradability rules both instruct the model to DROP a move or
# quote it cannot justify, so on those arms G-Q4 no longer measures whether the floor applied
# -- it measures whether a LATER rule reduced entry counts, which is the intended behaviour.
# Holding it would reject the gradability arm (83%) even though that arm has ZERO failing
# quotes and beat the relevance arm 89% vs 78% on a within-packet counterbalanced blind read.
# This is the THIRD time a frozen Layer C gate has rejected a real improvement (PB1 twice:
# §11.1, §12). The pattern is that these gates count evidence entries, and the rules that
# improve quality remove weak ones.

# G-Q7, the REPLACEMENT gate (added 2026-08-24). A probe re-synthesizes the SAME scenarios
# that are already live, so the decision it informs is "replace the incumbent or not" -- a
# RELATIVE question, which a small n can answer even when an absolute rate bar cannot. NEW
# must be no worse than OLD on both measurable risks. Kept separate from G-Q1 rather than
# folded into it, so a census-scale failure stays visible instead of being laundered by a
# relative pass.
G_Q7_REQUIRE_NO_WORSE = True


def _no_clobber(path: Path) -> None:
    if path.exists():
        raise SystemExit(
            f"{path.name} already exists — refusing to overwrite a published artifact. "
            f"Move it aside deliberately if a re-run is intended."
        )


def load_old() -> tuple[dict, dict]:
    """(evidence_by_scenario, old_documents_by_scenario) for the 5 REAL live documents."""
    ev = json.loads(PBV_EVIDENCE.read_text(encoding="utf-8-sig"))
    snap = json.loads(PBV_SNAPPED.read_text(encoding="utf-8-sig"))
    old = {d["scenario"]: d for d in snap["documents"].values() if d.get("arm") == "real"}
    if len(old) != 5:
        raise SystemExit(f"expected 5 real live documents, found {len(old)}")
    evidence = {}
    for scen in old:
        per = ev["per_scenario"].get(scen)
        if not per or not per.get("selected"):
            raise SystemExit(f"no selected evidence recorded for {scen}")
        evidence[scen] = per["selected"]
    return evidence, old


def scenario_map_from_db() -> dict:
    import psycopg

    from config import load_config

    url = load_config().database_url
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + "hostaddr=18.138.49.39"
    with psycopg.connect(url, connect_timeout=30, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT scenario_key, business_description, keyphrases, is_coachable, cluster_kind
            FROM scenarios
        """)
        # `scenario_key` must be INSIDE the dict, not only its key: scenario_header_text
        # reads info['scenario_key'] directly. Omitting it crashed the first run at the
        # first header build (before any chat call, so zero spend) -- the dict shape here
        # comes from a DB query rather than from the original scenario_map builder, and the
        # two must agree.
        return {r[0]: {"scenario_key": r[0], "business_description": r[1],
                       "keyphrases": r[2], "is_coachable": r[3], "cluster_kind": r[4]}
                for r in cur.fetchall()}


def move_stats(doc: dict) -> dict:
    moves = doc.get("key_moves") or []
    q = [len(m.get("evidence") or []) for m in moves]
    a = [len({e.get("account") for e in (m.get("evidence") or [])}) for m in moves]
    return {"n_moves": len(moves), "quotes": q, "accounts": a,
            "single_account_moves": sum(1 for x in a if x == 1)}


def pb1_move_rate(doc: dict, evidence: list[dict]) -> tuple[int, int]:
    r = pb1_doc(doc, evidence)
    ok = sum(1 for m in r["per_move"] if m["ok"])
    return ok, len(r["per_move"])


def cmd_plan() -> None:
    evidence, old = load_old()
    print(f"[arms] OLD = {len(old)} live documents (cost 0)   "
          f"NEW = same {len(old)} scenarios, re-synthesized")
    print(f"[model] NEW on {CHAT_MODEL} (reasoning={REASONING}), temp {CHAT_TEMPERATURE}, "
          f"no_cache=True, seed {SEED}")
    print(f"[prompt] MIN_EVIDENCE_PER_MOVE={MIN_EVIDENCE_PER_MOVE} + hardened _REQUIRE")
    total = 0
    print(f"\n{'scenario':<50} {'pairs':>6} {'maps':>5} {'calls':>6}")
    for scen, ev in sorted(evidence.items()):
        maps = (len(ev) + BATCH_MAX - 1) // BATCH_MAX
        total += maps + 1
        print(f"{scen:<50} {len(ev):>6} {maps:>5} {maps + 1:>6}")
    # Worst case is NOT total + headroom. ATTEMPTS_PER_CALL applies TWICE on each unit: an
    # outer schema-retry loop calls `call()`, which itself retries the transport up to
    # ATTEMPTS_PER_CALL times. So one map or reduce unit can cost up to 3x3 = 9 attempts and
    # the theoretical worst case is 9x the base. The ceiling is what actually bounds spend --
    # it is checked BEFORE the counter increments, so 25 is a true cap, not a target. If it
    # trips, the run HALTS part-finished and a re-run RESUMES from pbq_state.json (completed
    # documents are skipped), so a hard stop costs nothing already paid for.
    print(f"\n[budget] {total} calls if nothing retries. Worst case "
          f"{total * ATTEMPTS_PER_CALL * ATTEMPTS_PER_CALL} (retries nest 3x3 per unit), "
          f"HARD-CAPPED at {CALL_CEILING} — a trip halts mid-run and resumes on re-run.")

    ok, tot = 0, 0
    for scen, d in sorted(old.items()):
        o, t = pb1_move_rate(d["playbook"], evidence[scen])
        ok, tot = ok + o, tot + t
        st = move_stats(d["playbook"])
        print(f"  OLD {scen:<46} moves={st['n_moves']} quotes={st['quotes']} "
              f"accts={st['accounts']}")
    print(f"\n[OLD baseline] PB1 per-move: {ok}/{tot} = {100 * ok / max(tot, 1):.0f}%   "
          f"(G-Q1 needs NEW >= {G_Q1_MOVE_RATE:.0%})")
    print("\nDRY — nothing spent. Re-run with --synthesize.")


def cmd_synthesize() -> None:
    from shared.gateway import GatewayClient

    _no_clobber(PLAYBOOKS)
    _no_clobber(SNAPPED)
    evidence, old = load_old()
    scenario_map = scenario_map_from_db()

    # G-Q5: the evidence handed to the NEW arm must be the SAME evidence the OLD arm was
    # built from.
    #
    # The first version of this compared `evidence` against pbv_evidence.json -- the very
    # file `load_old()` had just read it from. That is a tautology: it proves only that one
    # file did not change between two reads in the same process, while reading as a pairing
    # proof. Caught by audit before it ran.
    #
    # This is the real check, and it runs in the other direction: every quote the OLD
    # documents actually CITE must be findable in the evidence pool being handed to the NEW
    # arm. If pbv_evidence.json were the wrong selection, or a different run's, the OLD
    # documents' citations would not be inside it. Post-snap quotes are exact substrings of
    # real evidence text (that is what the snap guarantees), so substring containment is the
    # correct test rather than equality.
    for scen, ev in evidence.items():
        if not ev:
            raise SystemExit(f"G-Q5 FAIL: empty evidence for {scen}")
        pool = "\n".join(f"{e.get('trigger_text', '')}\n{e.get('response_text', '')}"
                         for e in ev)
        cited = [c.get("quote", "") for m in old[scen]["playbook"].get("key_moves") or []
                 for c in m.get("evidence") or []]
        missing = [q for q in cited if q and q not in pool]
        if missing:
            raise SystemExit(
                f"G-Q5 FAIL: {len(missing)}/{len(cited)} quotes cited by the OLD document "
                f"for {scen} are NOT in the evidence pool being given to the NEW arm — the "
                f"two arms would not be paired. e.g. {missing[0][:80]!r}"
            )
        print(f"  [G-Q5] {scen}: all {len(cited)} OLD citations found in the "
              f"{len(ev)}-pair pool")
    print(f"[G-Q5] PASS — the NEW arm's evidence provably IS what the OLD arm was built "
          f"from, for all {len(evidence)} scenarios")

    state = json.loads(STATE.read_text(encoding="utf-8-sig")) if STATE.exists() else {
        "calls_used": 0, "documents": {}, "calls": [],
        "identity": {"started_at": datetime.datetime.now().isoformat(timespec="seconds"),
                     "seed": SEED, "model": CHAT_MODEL, "reasoning": REASONING,
                     "temperature": CHAT_TEMPERATURE, "no_cache": True,
                     "min_evidence_per_move": MIN_EVIDENCE_PER_MOVE,
                     "reduce_rules": "pilot_plus_pv_hardening_at_3_entry_floor",
                     "evidence_source": PBV_EVIDENCE.name,
                     "spec": "2026-08-20-quote-floor-ab-design.md"}}

    def save() -> None:
        STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")

    with GatewayClient() as gw:
        def call(prompt: str, label: str) -> dict:
            last: Exception | None = None
            for attempt in range(1, ATTEMPTS_PER_CALL + 1):
                if state["calls_used"] >= CALL_CEILING:
                    save()
                    raise SystemExit(
                        f"G-Q6 HARD STOP: {state['calls_used']} attempts made against a "
                        f"ceiling of {CALL_CEILING}. Ask the operator before more spend.")
                state["calls_used"] += 1
                save()                                   # count BEFORE the attempt
                t0 = time.time()
                try:
                    parsed, usage = gw.chat_json(
                        prompt, model=CHAT_MODEL, temperature=CHAT_TEMPERATURE,
                        max_tokens=65536, no_cache=True, reasoning_effort=REASONING)
                    state["calls"].append({"label": label, "attempt": attempt, "ok": True,
                                           "seconds": round(time.time() - t0, 1),
                                           "usage": usage})
                    save()
                    return parsed
                except Exception as e:                   # noqa: BLE001 — counted, retried
                    last = e
                    state["calls"].append({"label": label, "attempt": attempt, "ok": False,
                                           "seconds": round(time.time() - t0, 1),
                                           "error": str(e)[:300]})
                    save()
                    print(f"  [{label}] attempt {attempt} failed: {str(e)[:160]}", flush=True)
                    time.sleep(4)
            raise SystemExit(f"{label}: {ATTEMPTS_PER_CALL} attempts failed; last: {last}")

        for scen in sorted(evidence):
            if scen in state["documents"]:
                print(f"[skip] {scen} already synthesized", flush=True)
                continue
            ev = evidence[scen]
            header = scenario_header_text(scenario_map[scen])
            batches = [ev[i:i + BATCH_MAX] for i in range(0, len(ev), BATCH_MAX)]
            print(f"[synth] {scen}: {len(ev)} pairs, {len(batches)} map + 1 reduce "
                  f"(used {state['calls_used']}/{CALL_CEILING})", flush=True)
            maps = []
            for bi, batch in enumerate(batches):
                for attempt in range(1, ATTEMPTS_PER_CALL + 1):
                    out = call(map_prompt(header, batch), f"{scen}/map{bi}.{attempt}")
                    try:
                        validate_map(out)
                        break
                    except ValueError as e:
                        print(f"  [{scen}/map{bi}] schema reject: {e}", flush=True)
                        if attempt == ATTEMPTS_PER_CALL:
                            raise SystemExit(f"{scen}/map{bi}: never met the schema")
                maps.append(out)
            triggers = [e["trigger_text"] for e in ev]
            for attempt in range(1, ATTEMPTS_PER_CALL + 1):
                doc = call(pv_reduce_prompt(header, maps, triggers),
                           f"{scen}/reduce.{attempt}")
                try:
                    validate_playbook(doc)
                    break
                except ValueError as e:
                    print(f"  [{scen}/reduce] schema reject: {e}", flush=True)
                    if attempt == ATTEMPTS_PER_CALL:
                        raise SystemExit(f"{scen}/reduce: never met the schema")
            state["documents"][scen] = {"scenario": scen, "arm": "real",
                                        "n_evidence": len(ev), "playbook": doc}
            save()
            print(f"  [{scen}] done, {len(doc.get('key_moves') or [])} moves", flush=True)

    PLAYBOOKS.write_text(json.dumps(
        {"identity": state["identity"], "calls_used": state["calls_used"],
         "documents": state["documents"]}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n[write] {PLAYBOOKS.name} ({state['calls_used']} chat attempts)")

    out = {"identity": {**state["identity"], "snapped_at":
                        datetime.datetime.now().isoformat(timespec="seconds")},
           "documents": {}}
    for scen, rec in sorted(state["documents"].items()):
        snapped, log = snap_doc(rec["playbook"], evidence[scen])
        out["documents"][f"{scen}::real"] = {**{k: v for k, v in rec.items()
                                                if k != "playbook"},
                                             "playbook": snapped, "snap_log": log}
        print(f"  [snap {scen}] kept {log['kept']} snapped {log['snapped']} "
              f"dropped {log['dropped']}"
              f"{'  ** SCHEMA COLLAPSED **' if log['schema_collapsed'] else ''}")
    SNAPPED.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[write] {SNAPPED.name}\n")
    cmd_report()


def cmd_report() -> None:
    evidence, old = load_old()
    if not SNAPPED.exists():
        raise SystemExit(f"{SNAPPED.name} does not exist — run --synthesize first")
    new = {d["scenario"]: d
           for d in json.loads(SNAPPED.read_text(encoding="utf-8-sig"))["documents"].values()}

    rows, gates = [], {}
    n_ok = n_tot = o_ok = o_tot = 0
    floor_ok = floor_tot = 0
    collapsed, pb0_pass = [], 0
    for scen in sorted(evidence):
        nd, od = new.get(scen), old[scen]
        if nd is None:
            raise SystemExit(f"G-Q3 FAIL: {scen} missing from the NEW arm")
        no, nt = pb1_move_rate(nd["playbook"], evidence[scen])
        oo, ot = pb1_move_rate(od["playbook"], evidence[scen])
        n_ok, n_tot, o_ok, o_tot = n_ok + no, n_tot + nt, o_ok + oo, o_tot + ot
        ns, os_ = move_stats(nd["playbook"]), move_stats(od["playbook"])
        floor_ok += sum(1 for q in ns["quotes"] if q >= MIN_EVIDENCE_PER_MOVE)
        floor_tot += len(ns["quotes"])
        if nd.get("snap_log", {}).get("schema_collapsed"):
            collapsed.append(scen)
        pb0 = pb0_doc(nd["playbook"], evidence[scen])
        pb0_pass += bool(pb0.get("pass"))
        rows.append({"scenario": scen, "old": os_, "new": ns,
                     "old_pb1": [oo, ot], "new_pb1": [no, nt],
                     "pb0_new": bool(pb0.get("pass"))})

    print(f"{'scenario':<46} {'OLD moves/quotes':<24} {'NEW moves/quotes':<24} "
          f"{'PB1 old':>8} {'PB1 new':>8}")
    print("-" * 116)
    for r in rows:
        o, n = r["old"], r["new"]
        print(f"{r['scenario']:<46} "
              f"{str(o['n_moves']) + ' / ' + str(o['quotes']):<24} "
              f"{str(n['n_moves']) + ' / ' + str(n['quotes']):<24} "
              f"{r['old_pb1'][0]}/{r['old_pb1'][1]:<6} {r['new_pb1'][0]}/{r['new_pb1'][1]:<6}")

    new_rate = n_ok / max(n_tot, 1)
    old_rate = o_ok / max(o_tot, 1)
    floor_rate = floor_ok / max(floor_tot, 1)
    single_new = sum(r["new"]["single_account_moves"] for r in rows)
    single_old = sum(r["old"]["single_account_moves"] for r in rows)

    single_rate_new = single_new / max(n_tot, 1)
    single_rate_old = single_old / max(o_tot, 1)

    print(f"\n[diagnostic] PB1 per-move   OLD {o_ok}/{o_tot} = {old_rate:.0%}    "
          f"NEW {n_ok}/{n_tot} = {new_rate:.0%}   (REPORTED, NOT A GATE)")
    print(f"quotes>=3      NEW {floor_ok}/{floor_tot} = {floor_rate:.0%}")
    print(f"single-account moves   OLD {single_old}/{o_tot} = {single_rate_old:.0%}   "
          f"NEW {single_new}/{n_tot} = {single_rate_new:.0%}")

    gates["G-Q1"] = ("PASS" if single_rate_new <= G_Q1_SINGLE_ACCOUNT_MAX else "FAIL",
                     f"NEW single-account moves {single_rate_new:.0%} "
                     f"({single_new}/{n_tot}) vs ceiling "
                     f"{G_Q1_SINGLE_ACCOUNT_MAX:.0%} — PB1 {new_rate:.0%} is diagnostic only")
    gates["G-Q2"] = ("PASS" if pb0_pass == len(rows) else "FAIL",
                     f"PB0 {pb0_pass}/{len(rows)}")
    gates["G-Q3"] = ("PASS" if not collapsed and all(3 <= r["new"]["n_moves"] <= 6
                                                     for r in rows) else "FAIL",
                     f"collapsed={collapsed or 'none'}, "
                     f"moves={[r['new']['n_moves'] for r in rows]}")
    # G-Q4 is computed and printed, but deliberately NOT added to `gates` — see the block at
    # G_Q4_FLOOR_RATE. Reported as a diagnostic so every arm stays comparable to the arms
    # already measured against it.
    print(f"[diagnostic] quotes>={MIN_EVIDENCE_PER_MOVE} {floor_rate:.0%} vs the retired "
          f"G-Q4 bar {G_Q4_FLOOR_RATE:.0%}   (REPORTED, NOT A GATE)")

    # G-Q7: the relative test. Ties count as no-worse — a replacement that holds a risk flat
    # while improving something else is not blocked by that risk.
    no_worse = single_rate_new <= single_rate_old
    gates["G-Q7"] = ("PASS" if no_worse else "FAIL",
                     f"single-account NEW {single_rate_new:.0%} vs incumbent OLD "
                     f"{single_rate_old:.0%} — replacement must not be worse")
    print()
    for g, (v, why) in gates.items():
        print(f"[{g}] {v} — {why}")

    REPORT.write_text(json.dumps({"rows": rows, "gates": gates,
                                  "new_rate": new_rate, "old_rate": old_rate,
                                  "floor_rate": floor_rate,
                                  # PB1 (new_rate/old_rate) stays in the report as a
                                  # diagnostic so the retired bar remains comparable across
                                  # every arm already measured; single_rate_* is what gates.
                                  "single_rate_new": single_rate_new,
                                  "single_rate_old": single_rate_old,
                                  "pb1_is_a_gate": False}, indent=1), encoding="utf-8")
    print(f"\n[write] {REPORT.name}")
    failed = [g for g, (v, _) in gates.items() if v == "FAIL"]
    # The two questions are reported SEPARATELY on purpose. An arm can be unfit to roll out
    # across the whole taxonomy (G-Q1, census scale) while still being a clear improvement on
    # the specific documents it would replace (G-Q7). Collapsing them into one verdict is how
    # a census-scale caveat gets lost.
    absolute = [g for g in failed if g != "G-Q7"]
    if "G-Q7" in failed:
        print("\nG-Q7 FAIL — this arm is WORSE than the incumbent it would replace. "
              "Do not promote it.")
    elif absolute:
        print(f"\nMIXED VERDICT. Absolute gates failing: {absolute} — so this arm is NOT "
              f"licensed for a taxonomy-wide rollout at census scale. But G-Q7 PASSES: on "
              f"the 5 scenarios measured it is better than what is live, so promoting THESE "
              f"documents is defensible. Two different decisions; carry the caveat forward.")
    else:
        print("\nALL GATES PASS for this arm. NOTE: G-Q1 is now single-account <= 10%, not "
              "PB1, and G-Q4 is diagnostic — a pass here is NOT comparable to a "
              "pre-2026-08-24 pass.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--plan", action="store_true", help="free: arms, budget, OLD baseline")
    p.add_argument("--synthesize", action="store_true", help="SPENDS chat calls")
    p.add_argument("--report", action="store_true", help="free: re-report from artifacts")
    p.add_argument("--reasoning", default="low", choices=("low", "medium"),
                   help="reasoning effort. Each level writes its OWN artifact set, so runs "
                        "never overwrite each other. 'high' is deliberately not offered: it "
                        "exceeds the gateway's ~120s per-request cap on a 50-pair prompt.")
    p.add_argument("--model", default=_DEFAULT_MODEL,
                   help="chat model. Changing it changes the artifact set too, so runs stay "
                        "side by side. NOTE: the OLD arm was built on the default, so a "
                        "non-default model varies model AND prompt against the baseline.")
    p.add_argument("--tag", default="",
                   help="suffix for the artifact set, e.g. a prompt revision id")
    a = p.parse_args()
    _bind_artifacts(a.reasoning, a.model, a.tag)
    print(f"[run] model={CHAT_MODEL} reasoning={REASONING}  "
          f"artifacts={PLAYBOOKS.name}, {SNAPPED.name}")
    if a.synthesize:
        cmd_synthesize()
    elif a.report:
        cmd_report()
    else:
        cmd_plan()


if __name__ == "__main__":
    main()
