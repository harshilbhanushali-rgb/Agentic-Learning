#!/usr/bin/env python3
"""PLAYBOOK SNAP TRIAL: verbatim-repair successor to the scenario-playbook pilot.

Spec: docs/superpowers/specs/2026-08-18-playbook-snap-trial-design.md (snap algorithm,
counterbalancing rule, resized PB1, and the decision rule frozen there BEFORE this file
existed). Predecessor: calibration/scenario_playbook_trial.py — NOT VALIDATED solely on
PB0 (model quote-smoothing at ~1.4%/quote); PB2 won and survived a side-flip veto audit.

ONE pipeline variable changes: a deterministic post-synthesis snap stage that repairs
near-miss quotes onto exact evidence text (score >= 0.80) and drops what cannot be
tied to real text, with collapse rules so a hollowed document FAILS rather than passes.
Everything else is reused from the predecessor — its frozen artifacts as inputs (zero
Gemma spend), its pure gate/render/score functions as code (never re-implemented).

Instrument fixes carried in (both earned by the predecessor, on its record):
* PB2 sides are COUNTERBALANCED deterministically — real on A at odd pilot-rank
  positions, B at even — never an independent coin per item (the predecessor drew
  all-A at 1/32 and needed a veto-audit read to untangle it).
* PB1's span denominator is min(available accounts, total citations) — the old bar
  measured document length, not padding.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/playbook_snap_trial.py --snap
    ..\\.venv\\Scripts\\python.exe calibration/playbook_snap_trial.py --pb0
    ..\\.venv\\Scripts\\python.exe calibration/playbook_snap_trial.py --build-read
    # (blinded readers write artifacts/pbs_judgments_r*.json, one at a time)
    ..\\.venv\\Scripts\\python.exe calibration/playbook_snap_trial.py --score
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402
from calibration.scenario_playbook_trial import (  # noqa: E402
    EVIDENCE, PACKET_HEADER, PB1_MOVE_ACCTS, PB1_SPAN, PLAYBOOKS, SEED, N_NEG,
    build_neg, doc_evidence, iter_cited, norm_quote, pb0_doc, render_doc, score_read,
)

SNAP_MIN_SCORE = 0.80          # frozen: below this a citation is dropped, never bent
MIN_CITES_PER_MOVE = 2         # a move below this after drops is removed
MIN_MOVES = 3                  # a document below this is schema_collapsed -> FAILS PB0

SNAPPED = ARTIFACTS_DIR / "pbs_playbooks.json"
PB0_REPORT = ARTIFACTS_DIR / "pbs_pb0_report.json"
PACKET = ARTIFACTS_DIR / "pbs_read_packet.txt"
KEY = ARTIFACTS_DIR / "pbs_read_KEY.json"
JUDGMENTS_GLOB = "pbs_judgments_*.json"
REPORT = ARTIFACTS_DIR / "pbs_report.json"


# ---------------------------------------------------------------------------------------
# pure functions (unit-tested in tests/test_playbook_snap_trial.py)
# ---------------------------------------------------------------------------------------

def best_span(quote: str, text: str) -> tuple[float, str]:
    """The frozen alignment: minimal span of `text` covering every non-empty matching
    block against `quote`, scored by SequenceMatcher ratio. Deterministic."""
    sm = difflib.SequenceMatcher(None, quote, text, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    if not blocks:
        return 0.0, ""
    span = text[blocks[0].b: blocks[-1].b + blocks[-1].size]
    return difflib.SequenceMatcher(None, quote, span).ratio(), span


def snap_citation(e: dict, cand_texts: list[str]) -> tuple[str, dict | None, float]:
    """One citation against its cited call's candidate texts (already normalized, in
    frozen scan order). Returns (outcome, new_citation_or_None, score)."""
    q = norm_quote(str(e.get("quote") or ""))
    if not q:
        return "dropped", None, 0.0
    for t in cand_texts:
        if q in t:
            return "kept", dict(e), 1.0
    best_score, best_text = 0.0, ""
    for t in cand_texts:
        score, span = best_span(q, t)
        if score > best_score + 1e-12:          # ties -> earlier candidate wins
            best_score, best_text = score, span
    best_text = best_text.strip()
    if best_score >= SNAP_MIN_SCORE and best_text:
        return "snapped", {**e, "quote": best_text}, best_score
    return "dropped", None, best_score


def snap_doc(doc: dict, evidence: list[dict]) -> tuple[dict, dict]:
    """Snap every citation in a document against its OWN evidence set (spec §3).
    call/account are never altered; drops cascade: move < 2 cites -> move dropped
    (and removed from arc); document < 3 moves -> schema_collapsed."""
    by_call: dict[str, list[str]] = {}
    for ev in evidence:
        by_call.setdefault(ev["call"], []).extend(
            [norm_quote(ev["response_text"]), norm_quote(ev["trigger_text"])])

    log = {"kept": 0, "snapped": 0, "dropped": 0, "citations": [],
           "dropped_moves": []}

    def run(entries: list[dict], path: str) -> list[dict]:
        out = []
        for e in entries:
            outcome, new_e, score = snap_citation(e, by_call.get(str(e.get("call") or ""), []))
            log[outcome] += 1
            log["citations"].append({"path": path, "outcome": outcome,
                                     "score": round(score, 4),
                                     "call": e.get("call", "")})
            if new_e is not None:
                out.append(new_e)
        return out

    new = {k: v for k, v in doc.items()}
    moves = []
    for mi, m in enumerate(doc.get("key_moves") or []):
        ev2 = run(m.get("evidence") or [], f"key_moves[{mi}]")
        if len(ev2) >= MIN_CITES_PER_MOVE:
            moves.append({**m, "evidence": ev2})
        else:
            log["dropped_moves"].append(m.get("name", ""))
    new["key_moves"] = moves
    dropped_names = set(log["dropped_moves"])
    new["arc"] = [s for s in doc.get("arc") or [] if s not in dropped_names]
    new["signature_language"] = run(doc.get("signature_language") or [],
                                    "signature_language")
    pits = []
    for pi, p in enumerate(doc.get("pitfalls_and_variants") or []):
        ev2 = run(p.get("evidence") or [], f"pitfalls_and_variants[{pi}]")
        if ev2:
            pits.append({**p, "evidence": ev2})
    new["pitfalls_and_variants"] = pits
    log["schema_collapsed"] = len(moves) < MIN_MOVES
    return new, log


def counterbalanced_side(rank_position: int) -> str:
    """Frozen: real takes A at odd pilot-rank positions (1st, 3rd, 5th -> index 0,2,4),
    B at even. Deterministic — a degenerate all-one-side draw is impossible."""
    return "A" if rank_position % 2 == 0 else "B"


def pb1_doc_resized(doc: dict, evidence: list[dict]) -> dict:
    """Spec §5: per-move breadth unchanged; span denominator becomes
    min(available accounts, total citations in the document)."""
    available = sorted({ev["account"] for ev in evidence})
    need = min(PB1_MOVE_ACCTS, len(available))
    moves = []
    for m in doc.get("key_moves") or []:
        accts = {str(e.get("account") or "") for e in m.get("evidence") or []}
        moves.append({"name": m.get("name", ""), "accounts": len(accts),
                      "ok": len(accts) >= need})
    cites = list(iter_cited(doc))
    cited = {str(e.get("account") or "") for _, e in cites}
    denom = min(len(available), len(cites))
    span = len(cited & set(available)) / max(denom, 1)
    pass_a = all(m["ok"] for m in moves) and bool(moves)
    pass_b = span >= PB1_SPAN
    return {"pass": pass_a and pass_b, "per_move": moves, "need_per_move": need,
            "accounts_available": len(available), "n_citations": len(cites),
            "span": span, "span_denominator": denom,
            "pass_moves": pass_a, "pass_span": pass_b}


# ---------------------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------------------

def _load_inputs() -> tuple[dict, dict]:
    if not (EVIDENCE.exists() and PLAYBOOKS.exists()):
        raise SystemExit("predecessor artifacts pb_evidence.json / pb_playbooks.json "
                         "missing — this trial reuses them by design")
    return (json.loads(EVIDENCE.read_text(encoding="utf-8-sig")),
            json.loads(PLAYBOOKS.read_text(encoding="utf-8-sig")))


def stage_snap() -> None:
    if SNAPPED.exists():
        raise SystemExit(f"{SNAPPED.name} exists — refusing to clobber")
    ev, pb = _load_inputs()
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


def stage_pb0() -> None:
    if PB0_REPORT.exists():
        raise SystemExit(f"{PB0_REPORT.name} exists — refusing to clobber")
    ev, _ = _load_inputs()
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
    print(f"\nPB0(snapped): {real_pass}/{n_real} real -> {verdict}")
    # audit F1: only a QUOTE failure on a snapped document indicates a harness bug —
    # schema_collapsed is a legitimate result (spec §1) and an account mismatch is a
    # data defect snap never touches. Label each precisely.
    reasons = {f["reason"] for r in report.values() for f in r["failures"]}
    quote_reasons = reasons - {"schema_collapsed", "account mismatch"}
    if quote_reasons:
        print(f"!! quote-level PB0 failures on SNAPPED documents ({quote_reasons}) — "
              f"by design impossible: HARNESS BUG, veto-audit code AND output.")
    elif "account mismatch" in reasons:
        print("!! account-mismatch failures: a data defect in the synthesized "
              "citations, not a snap bug (snap never alters call/account).")
    PB0_REPORT.write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "verdict": verdict, "real_pass": real_pass, "n_real": n_real,
        "per_document": report}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {PB0_REPORT.name}")


def stage_build_read() -> None:
    import random
    if PACKET.exists() or KEY.exists():
        raise SystemExit("read packet / KEY already exist — refusing to clobber")
    ev, _ = _load_inputs()
    sn = json.loads(SNAPPED.read_text(encoding="utf-8-sig"))
    from calibration.layer_bc_arms import taxonomy_path, scenario_map_from_rows
    from calibration.layer_c_pool_unit import TAXONOMY
    tax = json.loads(taxonomy_path(TAXONOMY).read_text(encoding="utf-8-sig"))
    scenario_map, _ = scenario_map_from_rows(tax["rows"])

    rng = random.Random(SEED)
    docs = sn["documents"]
    # audit F2: a schema-collapsed document can end with zero key moves, which
    # build_neg cannot sample from — exclude empty docs from the NEG source pool
    all_playbooks = [r["playbook"] for _, r in sorted(docs.items())
                     if r["playbook"].get("key_moves")]
    real_side_of = {key: counterbalanced_side(i) for i, key in enumerate(ev["pilot"])}

    used = set(ev["pilot"]) | set(ev["donors"].values())
    neg_headers = [k for k in sorted(ev["ranking"], key=lambda k: (-ev["ranking"][k], k))
                   if k not in used][:N_NEG]
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


def stage_score() -> None:
    if REPORT.exists():
        raise SystemExit(f"{REPORT.name} exists — refusing to clobber")
    ev, _ = _load_inputs()
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
    validated = pb0.get("verdict") == "PASS" and won
    print("=" * 88)
    print(f"PB0(snapped) {pb0.get('verdict')} | PB1(resized) {pb1_pass}/{len(pb1)} "
          f"({'PASS' if pb1_pass >= 4 else 'FLAG'}) | "
          f"PB2 {'WON' if won else read.get('verdict', 'NOT WON')} | "
          f"PB3 {'PASS' if read.get('pb3', {}).get('pass') else 'FLAG/VOID'}")
    print(f"METHOD {'VALIDATED' if validated else 'NOT VALIDATED'} "
          f"(decision rule: PB0 PASS and PB2 WON)")
    print("=" * 88)
    REPORT.write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "pb0_verdict": pb0.get("verdict"),
        "pb1_resized": {"per_scenario": pb1, "n_pass": pb1_pass,
                        "pass": pb1_pass >= 4},
        "read": read,
        "method_validated": validated,
        "gemma_spend": 0,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {REPORT.name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--snap", action="store_true")
    p.add_argument("--pb0", action="store_true")
    p.add_argument("--build-read", action="store_true")
    p.add_argument("--score", action="store_true")
    a = p.parse_args()
    if a.snap:
        stage_snap()
    if a.pb0:
        stage_pb0()
    if a.build_read:
        stage_build_read()
    if a.score:
        stage_score()
    if not any([a.snap, a.pb0, a.build_read, a.score]):
        p.print_help()


if __name__ == "__main__":
    main()
