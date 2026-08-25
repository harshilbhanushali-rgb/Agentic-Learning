#!/usr/bin/env python3
"""SCENARIO-PLAYBOOK TRIAL: 5-scenario pilot of evidence-cited per-scenario synthesis.

Spec: docs/superpowers/specs/2026-08-18-scenario-playbook-trial-design.md (gates PB0-PB3,
pick rule, placebo construction, and reader protocol FROZEN there before this file
existed). Handoff: Brain/HANDOFF_PLAYBOOK_TRIAL_2026-08-18.md.

DESIGN INVARIANTS (from the spec):

* Substrate is the pool-unit trial's, byte-for-byte: `layer_c_pool_unit.build_substrate`
  (production parse -> pairs -> routing, cache-only embeddings, stage-1 F0 asserted).
  PB-F0 reuses the pool-unit V0 check verbatim: the production clause path must
  reproduce the stage-1 artifact's per-scenario clause pools list-identically, or the
  harness is buggy and nothing downstream is reportable.
* Pilot pick rule: ranks 1, 5, 10, 15, 20 of the 26 coachable scenarios by routed-pair
  count (ties: ascending scenario_key). Computed, recorded, never substituted.
* Evidence pool: routed pairs whose call has an account domain AND whose response yields
  >= 1 production-segmenter clause (its u_turn unit text is what the pool-unit fetch
  cached, so the selection vector exists; a response with no segmentable clause has no
  quotable content anyway). Exclusions are counted and printed.
* Selection vectors are CACHE-ONLY gemini@3072 vectors of each response's u_turn unit
  text (clauses joined with one space, exactly `units_from_response(mode="u_turn")`).
  Any cache miss ABORTS -- zero embedding spend; chat is this trial's only spend.
* Placebo twin: identical prompt template, identical map-reduce shape, identical
  selection algorithm -- evidence swapped for a single DONOR scenario's (non-pilot,
  matched by routed-pair count, without replacement). Donors are single scenarios so the
  placebo is internally coherent (the strongest placebo), and non-pilot so no content
  appears twice in a reader packet.
* Every chat call goes through GatewayClient.chat_json with no_cache=True (the gateway
  response cache silently echoes identical prompts -- fatal for an A/B), model pinned,
  max_retries=1 so the harness counts EVERY attempt against the frozen 50-call hard
  stop. Gateway needs the Joveo VPN.
* Bench conventions: artifacts under Brain/artifacts/ with started_at/pid/seed/shas,
  every stage refuses to clobber existing outputs, seeded RNG throughout, judgments are
  committed to files before the KEY is opened (the key is written at --build-read and
  read only by --score).

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/scenario_playbook_trial.py --smoke
    ..\\.venv\\Scripts\\python.exe calibration/scenario_playbook_trial.py --select
    ..\\.venv\\Scripts\\python.exe calibration/scenario_playbook_trial.py --synthesize
    ..\\.venv\\Scripts\\python.exe calibration/scenario_playbook_trial.py --pb0
    ..\\.venv\\Scripts\\python.exe calibration/scenario_playbook_trial.py --build-read
    # (blinded readers write artifacts/pb_judgments_r*.json, one at a time)
    ..\\.venv\\Scripts\\python.exe calibration/scenario_playbook_trial.py --score
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402

SEED = 42
PILOT_RANKS = (1, 5, 10, 15, 20)
N_EVIDENCE_MAX = 50
ACCT_FLOOR = 8
BATCH_MAX = 25
CALL_BUDGET_HARD = 50          # frozen: at 50 total chat attempts the harness halts
ATTEMPTS_PER_CALL = 3          # per logical map/reduce call; every attempt counted
CHAT_TEMPERATURE = 0.2
N_NEG = 5
NEG_REJECT_MIN = 4             # reader VALID iff >= 4/5 NEG rejected (and every item answered)
N_VALID_READERS = 3
PB2_WIN_SCENARIOS = 4          # real preferred in >= 4/5 scenarios
# Quotes the prompt demands per move. WAS 2 (as "2-4 entries"), which made PB1 arithmetically
# UNREACHABLE: PB1 needs 3 distinct accounts per move and 2 quotes reach at most 2. Measured
# 2026-08-20 over all 16 real documents: 89% of moves (59/66) took the minimum 2 quotes, so
# PB1 failed 0/11 documents before quality was ever assessed. The model is not the problem --
# it already maximises account spread subject to quote count (50/59 two-quote moves cite 2
# distinct accounts; 5/7 three-quote moves cite 3).
# The published pilot/trial artifacts were generated at 2 and are frozen on disk; they are not
# regenerated, so raising this does not invalidate them.
MIN_EVIDENCE_PER_MOVE = 3
MAX_EVIDENCE_PER_MOVE = 4

PB1_MOVE_ACCTS = 3
PB1_SPAN = 0.60
PB3_APPLY_MEDIAN = 0.5
SHORT_QUOTE_WARN = 15          # reported, never gating (PB0 is frozen without a length bar)

EVIDENCE = ARTIFACTS_DIR / "pb_evidence.json"
PLAYBOOKS = ARTIFACTS_DIR / "pb_playbooks.json"
PB0_REPORT = ARTIFACTS_DIR / "pb_pb0_report.json"
PACKET = ARTIFACTS_DIR / "pb_read_packet.txt"
KEY = ARTIFACTS_DIR / "pb_read_KEY.json"
JUDGMENTS_GLOB = "pb_judgments_*.json"
REPORT = ARTIFACTS_DIR / "pb_report.json"


# ---------------------------------------------------------------------------------------
# pure functions (unit-tested in tests/test_scenario_playbook_trial.py)
# ---------------------------------------------------------------------------------------

def pick_pilot(counts: dict[str, int], ranks: tuple[int, ...] = PILOT_RANKS) -> list[str]:
    """Frozen pick rule: rank all coachable scenarios by routed-pair count descending,
    ties broken by ascending scenario_key; return the scenarios at `ranks` (1-based),
    in rank order."""
    order = sorted(counts, key=lambda k: (-counts[k], k))
    if len(order) < max(ranks):
        raise SystemExit(f"only {len(order)} scenarios ranked; pick rule needs "
                         f"rank {max(ranks)}")
    return [order[r - 1] for r in ranks]


def assign_donors(pilot: list[str], counts: dict[str, int]) -> dict[str, str]:
    """Frozen donor rule: walking the pilot in rank order, each gets the unassigned
    NON-pilot scenario with the closest routed-pair count (ties: ascending key),
    without replacement."""
    remaining = sorted(k for k in counts if k not in pilot)
    donors: dict[str, str] = {}
    for key in pilot:
        if not remaining:
            raise SystemExit("ran out of donor scenarios")
        best = min(remaining, key=lambda k: (abs(counts[k] - counts[key]), k))
        donors[key] = best
        remaining.remove(best)
    return donors


_QUOTE_TRANS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-",
})


def norm_quote(s: str) -> str:
    """The frozen PB0 normalization: NFKC; curly quotes -> straight; en/em dashes ->
    hyphen; whitespace runs -> one space; strip. Case-SENSITIVE beyond that."""
    s = unicodedata.normalize("NFKC", s).translate(_QUOTE_TRANS)
    return re.sub(r"\s+", " ", s).strip()


def iter_cited(doc: dict):
    """Every {quote, call, account} citation in a playbook, with its section path.
    PB0 walks all of them; PB1's per-move breadth walks key_moves only."""
    for mi, m in enumerate(doc.get("key_moves") or []):
        for e in m.get("evidence") or []:
            yield f"key_moves[{mi}]", e
    for si, e in enumerate(doc.get("signature_language") or []):
        yield f"signature_language[{si}]", e
    for pi, p in enumerate(doc.get("pitfalls_and_variants") or []):
        for e in p.get("evidence") or []:
            yield f"pitfalls_and_variants[{pi}]", e


def pb0_doc(doc: dict, evidence: list[dict]) -> dict:
    """PB0 for ONE document against ITS OWN evidence set (real -> real, placebo -> donor:
    fidelity is honesty of quoting, not truth of routing). One fabricated / altered /
    misattributed quote, or one account mismatch, fails the document."""
    by_call: dict[str, list[str]] = defaultdict(list)
    acct_of: dict[str, str] = {}
    for ev in evidence:
        by_call[ev["call"]].append(norm_quote(ev["trigger_text"]))
        by_call[ev["call"]].append(norm_quote(ev["response_text"]))
        acct_of[ev["call"]] = ev["account"]
    failures, n_quotes, n_short = [], 0, 0
    for path, e in iter_cited(doc):
        n_quotes += 1
        q = norm_quote(str(e.get("quote") or ""))
        call = str(e.get("call") or "")
        acct = str(e.get("account") or "")
        if not q:
            failures.append({"path": path, "reason": "empty quote", "call": call})
            continue
        if len(q) < SHORT_QUOTE_WARN:
            n_short += 1
        if call not in by_call:
            failures.append({"path": path, "reason": "cited call not in evidence set",
                             "call": call, "quote": q[:80]})
            continue
        if not any(q in text for text in by_call[call]):
            found_elsewhere = any(q in t for c, ts in by_call.items() if c != call
                                  for t in ts)
            failures.append({"path": path,
                             "reason": ("misattributed" if found_elsewhere
                                        else "not verbatim in cited call"),
                             "call": call, "quote": q[:80]})
            continue
        if acct != acct_of[call]:
            failures.append({"path": path, "reason": "account mismatch", "call": call,
                             "cited_account": acct, "true_account": acct_of[call]})
    return {"pass": not failures, "n_quotes": n_quotes,
            "n_short_quotes_warn": n_short, "failures": failures}


def pb1_doc(doc: dict, evidence: list[dict]) -> dict:
    """PB1 for one REAL playbook: (a) every key move cites >= min(3, available accounts)
    distinct accounts; (b) the full citation set spans >= 60% of available accounts."""
    available = sorted({ev["account"] for ev in evidence})
    need = min(PB1_MOVE_ACCTS, len(available))
    moves = []
    for m in doc.get("key_moves") or []:
        cites = m.get("evidence") or []
        accts = {str(e.get("account") or "") for e in cites}
        # `need` is NOT capped by the move's own quote count, deliberately. Capping was tried
        # on 2026-08-20 and reverted: it makes a 2-quote move pass by lowering the bar to
        # meet it, which forgives exactly the documents that should be flagged. The
        # arithmetic problem (a 2-quote move cannot cite 3 accounts, and 89% of moves carried
        # 2 quotes, so PB1 failed 0/11 documents before quality was assessed) is real, but it
        # belongs to the PROMPT: MIN_EVIDENCE_PER_MOVE is now 3, so 3 accounts is reachable.
        # `quotes` is reported so a failure is diagnosable as "too few quotes" vs "narrow".
        moves.append({"name": m.get("name", ""), "accounts": len(accts),
                      "quotes": len(cites), "need": need,
                      "ok": len(accts) >= need})
    cited = {str(e.get("account") or "") for _, e in iter_cited(doc)}
    span = len(cited & set(available)) / max(len(available), 1)
    pass_a = all(m["ok"] for m in moves) and bool(moves)
    pass_b = span >= PB1_SPAN
    return {"pass": pass_a and pass_b, "per_move": moves, "need_per_move": need,
            "accounts_available": len(available), "span": span,
            "pass_moves": pass_a, "pass_span": pass_b}


def select_evidence(pool: list[dict], mat: np.ndarray, n_max: int,
                    floor: int) -> list[int]:
    """The frozen two-phase selection over one scenario's evidence pool (pool must be in
    deterministic order; `mat` row i is pool[i]'s selection vector).

    Phase 1 (account floor): accounts in descending pair-count order (ties: ascending
    domain); from each, the pair nearest the pool centroid (ties: lowest pool index);
    stop once min(floor, #accounts) accounts are covered.
    Phase 2 (diversity fill): greedy max-min on cosine distance to the selected set
    (ties: lowest pool index) until n_max."""
    if not pool:
        return []
    n_max = min(n_max, len(pool))
    unit = mat / np.maximum(np.linalg.norm(mat, axis=1, keepdims=True), 1e-12)
    centroid = unit.mean(axis=0)
    centroid /= max(np.linalg.norm(centroid), 1e-12)
    cen_sim = unit @ centroid

    by_acct: dict[str, list[int]] = defaultdict(list)
    for i, rec in enumerate(pool):
        by_acct[rec["account"]].append(i)
    acct_order = sorted(by_acct, key=lambda a: (-len(by_acct[a]), a))
    target = min(floor, len(by_acct))

    selected: list[int] = []
    for acct in acct_order:
        if len(selected) >= target or len(selected) >= n_max:
            break
        best = min(by_acct[acct], key=lambda i: (-cen_sim[i], i))
        selected.append(best)

    chosen = set(selected)
    if selected:
        # min cosine distance from every pool row to the selected set, kept incremental
        min_dist = np.min(1.0 - unit @ unit[selected].T, axis=1)
    else:
        min_dist = np.full(len(pool), np.inf)
    while len(selected) < n_max:
        best, best_d = -1, -1.0
        for i in range(len(pool)):
            if i in chosen:
                continue
            if min_dist[i] > best_d + 1e-12:
                best, best_d = i, min_dist[i]
        if best < 0:
            break
        selected.append(best)
        chosen.add(best)
        min_dist = np.minimum(min_dist, 1.0 - unit @ unit[best])
    return selected


def sign_test_two_sided(up: int, down: int) -> float:
    from math import comb
    n = up + down
    if n == 0:
        return 1.0
    k = min(up, down)
    return min(1.0, sum(comb(n, i) for i in range(0, k + 1)) / 2 ** n * 2)


def reader_valid(items: dict, key_items: list[dict]) -> tuple[bool, str]:
    """Frozen validity bar: answered every item AND rejected >= 4/5 NEG controls."""
    rejected = total_neg = 0
    for row in key_items:
        it = items.get(str(row["item"])) or {}
        if row["kind"] == "NEG":
            total_neg += 1
            ans = str(it.get("answer", "")).upper()
            if not ans:
                return False, f"item {row['item']} unanswered"
            rejected += ans == "NO"
        else:
            if str(it.get("choice", "")).upper() not in ("A", "B"):
                return False, f"item {row['item']} has no A/B choice"
    if rejected < NEG_REJECT_MIN:
        return False, f"rejected only {rejected}/{total_neg} NEG controls"
    return True, f"rejected {rejected}/{total_neg} NEG controls"


def score_read(key: dict, judgments: list[dict],
               real_move_counts: dict[str, int]) -> dict:
    """PB2 + PB3 from the sealed key and the committed judgment files.

    Valid readers are taken in file order until N_VALID_READERS; a scenario is
    REAL-PREFERRED iff >= 2 of the 3 valid readers picked the real side. PB2 WON =
    real preferred in >= 4/5 scenarios. PB3: a key move counts APPLY iff >= 2/3 valid
    readers rated it APPLY (a missing/short rating list reads as VAGUE, conservatively);
    PASS = median APPLY share across the 5 real playbooks >= 0.5."""
    # Audit finding 1 (2026-08-18): a duplicated judgment file (same reader saved twice)
    # would cast 2 of 3 votes and could flip PB2 across the 4/5 line. Readers must be
    # pairwise-distinct in identity AND payload before any vote is counted.
    names = [jd["reader"] for jd in judgments]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate reader identity among judgment files: {names}")
    payloads = [json.dumps(jd["items"], sort_keys=True) for jd in judgments]
    if len(set(payloads)) != len(payloads):
        raise ValueError("two judgment files carry byte-identical answers — a "
                         "duplicated dispatch, not two readers")
    validity = {}
    valid: list[dict] = []
    for jd in judgments:
        ok, why = reader_valid(jd["items"], key["items"])
        validity[jd["reader"]] = {"valid": ok, "why": why}
        if ok and len(valid) < N_VALID_READERS:
            valid.append(jd)
    if len(valid) < N_VALID_READERS:
        return {"verdict": "VOID",
                "reason": f"only {len(valid)} valid readers (< {N_VALID_READERS})",
                "validity": validity}

    per_scenario, pooled_real, pooled_plc = {}, 0, 0
    apply_share = {}
    for row in key["items"]:
        if row["kind"] != "PAIR":
            continue
        scen, real_side = row["scenario"], row["real_side"]
        votes_real = 0
        applies = []
        for jd in valid:
            it = jd["items"].get(str(row["item"])) or {}
            choice = str(it.get("choice", "")).upper()
            votes_real += choice == real_side
            ratings = it.get(f"apply_{real_side}") or []
            applies.append([str(r).upper() == "APPLY" for r in ratings])
        pooled_real += votes_real
        pooled_plc += len(valid) - votes_real
        preferred = votes_real >= 2
        n_moves = real_move_counts.get(scen, 0)
        move_apply = []
        for mi in range(n_moves):
            yes = sum(1 for a in applies if mi < len(a) and a[mi])
            move_apply.append(yes >= 2)
        share = sum(move_apply) / n_moves if n_moves else 0.0
        apply_share[scen] = share
        per_scenario[scen] = {"votes_real": votes_real, "n_valid": len(valid),
                              "real_preferred": preferred,
                              "apply_share_real": share}
    n_pref = sum(1 for r in per_scenario.values() if r["real_preferred"])
    shares = sorted(apply_share.values())
    median_share = float(np.median(shares)) if shares else 0.0
    return {
        "validity": validity,
        "valid_readers": [jd["reader"] for jd in valid],
        "per_scenario": per_scenario,
        "pb2": {"scenarios_real_preferred": n_pref, "n_scenarios": len(per_scenario),
                "won": n_pref >= PB2_WIN_SCENARIOS,
                "pooled_votes": {"real": pooled_real, "placebo": pooled_plc,
                                 "sign_p_descriptive": sign_test_two_sided(
                                     pooled_real, pooled_plc)},
                "unanimous_scenarios": sum(1 for r in per_scenario.values()
                                           if r["votes_real"] in (0, len(valid)))},
        "pb3": {"apply_share_per_scenario": apply_share,
                "median_apply_share": median_share,
                "pass": median_share >= PB3_APPLY_MEDIAN},
    }


# ---------------------------------------------------------------------------------------
# rendering (ONE renderer for real, placebo and NEG docs -- symmetry is the blinding)
# ---------------------------------------------------------------------------------------

def render_doc(doc: dict) -> list[str]:
    lines = ["  SITUATION:"]
    lines += [f"    {doc.get('situation_signature', '').strip()}"]
    lines.append("  ARC (move sequence):")
    for step in doc.get("arc") or []:
        lines.append(f"    -> {step}")
    lines.append("  KEY MOVES:")
    for i, m in enumerate(doc.get("key_moves") or [], 1):
        lines.append(f"    MOVE {i}: {m.get('name', '')}")
        lines.append(f"      criterion: {m.get('criterion', '')}")
        for e in m.get("evidence") or []:
            lines.append(f"      \"{e.get('quote', '')}\"")
            lines.append(f"        [{e.get('call', '')} | {e.get('account', '')}]")
    if doc.get("signature_language"):
        lines.append("  SIGNATURE LANGUAGE:")
        for e in doc["signature_language"]:
            lines.append(f"    - {e.get('phrase', '')}: \"{e.get('quote', '')}\" "
                         f"[{e.get('call', '')} | {e.get('account', '')}]")
    if doc.get("pitfalls_and_variants"):
        lines.append("  PITFALLS / VARIANTS:")
        for p in doc["pitfalls_and_variants"]:
            lines.append(f"    - {p.get('text', '')}")
            for e in p.get("evidence") or []:
                lines.append(f"      \"{e.get('quote', '')}\" "
                             f"[{e.get('call', '')} | {e.get('account', '')}]")
    lines.append("  SCORABLE CHECKS:")
    for c in doc.get("layer_d_checks") or []:
        lines.append(f"    [ ] {c}")
    return lines


def build_neg(docs: list[dict], rng) -> dict:
    """A fake playbook assembled from sections of >= 3 different synthesized documents
    (the W4 scrambled-negative shape). Rendered by the same renderer as everything else.
    Section reuse from paired documents is on the record in the spec (precedent: W4's
    NEG clauses also came from displayed milestones)."""
    srcs = rng.sample(docs, min(4, len(docs)))
    moves = [rng.choice(s["key_moves"]) for s in srcs[:3]]
    sig_src = (srcs[3] if len(srcs) > 3 else srcs[0]).get("signature_language") or []
    return {
        "situation_signature": srcs[0].get("situation_signature", ""),
        "arc": [m.get("name", "") for m in moves],
        "key_moves": moves,
        "signature_language": sig_src[:2],
        "pitfalls_and_variants": (srcs[1].get("pitfalls_and_variants") or [])[:1],
        "layer_d_checks": (srcs[2].get("layer_d_checks") or [])[:3],
    }


PACKET_HEADER = [
    "BLIND READ -- scenario coaching playbooks (PB2)",
    "",
    "Each PAIR item names one client-conversation SCENARIO and shows two candidate",
    "coaching playbooks, A and B. Exactly one is the genuine playbook synthesized from",
    "real evidence of that scenario; judge ONLY what is written.",
    "",
    "For every PAIR item answer, in JSON (see the required format at the end):",
    '  "choice": "A" or "B" -- which document is the genuine, usable coaching playbook',
    "  for the named scenario. You MUST pick one; there is no EQUAL.",
    '  "apply_A" / "apply_B": one rating per KEY MOVE, in display order, each either',
    '  "APPLY" (concrete enough for a new account manager to attempt on their next call',
    '  in this scenario) or "VAGUE".',
    "",
    "SINGLE items show one document and name a scenario. Answer:",
    '  "answer": "YES" if it is one coherent, usable coaching document for that',
    '  scenario, "NO" otherwise.',
    "",
    "Do not try to infer where an item came from, and do not assume any particular",
    "share of answers. Answer EVERY item.",
    "=" * 96, ""]


# ---------------------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------------------

def scenario_header_text(info: dict) -> str:
    return (f"scenario_key: {info['scenario_key']}\n"
            f"description: {info.get('business_description', '')}\n"
            f"keyphrases: {', '.join(info.get('keyphrases') or [])}")

MAP_RULES = """\
RULES (each violated rule invalidates the output):
- A move's "criterion" states what a DIFFERENT account manager's response must satisfy.
  NEVER name any person; never use he/she/his/her/"the speaker". Generalize past
  specific numbers, client names and anecdotes -- the quotes carry the specifics.
- *** A CRITERION MUST BE GRADABLE FROM A TRANSCRIPT. *** It will be used to score a real
  call yes/no, so it must name something CONCRETE that is either present or absent: a
  specific artifact, a number, a named mechanism, or a structure the response must contain.
  BANNED: evaluative adjectives describing an effect on the listener -- "clear", "clearly",
  "effective", "scientific", "aligned", "proactive", "appropriate", "comprehensive",
  "robust", "meaningful". You cannot grade "was it clear?" from a transcript.
    BAD  "clearly explain the business impact"
    BAD  "ensure media plans are as scientific as possible"
    BAD  "demonstrate operational relief and proactive partnership value"
    GOOD "state a specific turnaround time in days for the request"
    GOOD "name the management fee and the pass-through media spend as separate amounts"
    GOOD "give a numeric radius or ZIP-level boundary for the targeting change"
  If you cannot state what must be PRESENT in the response, the move is not gradable --
  DROP it rather than describe it with an adjective.
- Every move carries 2-4 "evidence" entries. Each entry's "quote" is copied
  CHARACTER-FOR-CHARACTER from the "response" (or "client_trigger") text of ONE evidence
  item; "call" and "account" are copied exactly from that same item. Never paraphrase
  inside a quote, never stitch two passages, never invent a call or account.
- Prefer quotes long enough to be checkable (a full sentence or clause).
- *** A QUOTE MUST DEMONSTRATE THE MOVE, NOT REACT TO IT. *** Before citing a passage, ask:
  does this passage SHOW the account manager doing what the criterion describes? If it only
  shows someone agreeing that it matters, reject it and find the passage where the work
  actually happens. NEVER cite:
    * a bare acknowledgement -- "Got it.", "Understood.", "That makes sense.", "Okay, yeah."
    * a greeting or rapport line -- "Hi, good to be connected."
    * a passage whose SUBSTANCE is the account manager ASKING for information rather than
      providing it -- asking about a thing is not doing it. This includes turns that open
      declaratively and then ask ("Great, so just a couple of clarifications -- when we say
      pixel fire, do you mean ...?"). Judge what the passage is FOR, not how it starts.
    * a truncated or garbled fragment that cannot be understood on its own
    * an announcement of intent with no substance -- "my suggestion would be we take two
      approaches" (which two? the quote must contain them)
  A move with no passage that truly demonstrates it should be DROPPED, not propped up with
  a weak citation.
- signature_language: short verbatim expressions or benchmark numbers the expert
  repeatedly uses, each with quote/call/account under the same copying rule.
- pitfalls: only if the evidence shows one (a client type needing different handling, a
  visible failure mode); each with >= 1 evidence entry under the same copying rule.
Return ONLY JSON:
{"moves": [{"name": str, "criterion": str,
            "evidence": [{"quote": str, "call": str, "account": str}]}],
 "signature_language": [{"phrase": str, "quote": str, "call": str, "account": str}],
 "pitfalls": [{"text": str, "evidence": [{"quote": str, "call": str, "account": str}]}]}"""


def map_prompt(header: str, batch: list[dict]) -> str:
    items = [{"call": e["call"], "account": e["account"],
              "client_trigger": e["trigger_text"], "response": e["response_text"]}
             for e in batch]
    return (f"You are building a sales-coaching playbook for one recurring client\n"
            f"scenario, from real call evidence.\n\nSCENARIO:\n{header}\n\n"
            f"EVIDENCE ({len(items)} real client-trigger -> expert-response exchanges):\n"
            f"{json.dumps(items, ensure_ascii=False, indent=1)}\n\n"
            f"TASK: extract every distinct coaching MOVE these responses demonstrate for\n"
            f"this scenario.\n\n{MAP_RULES}")


REDUCE_RULES = """\
RULES (each violated rule invalidates the output):
- "situation_signature": 2-4 sentences: how an account manager recognizes being IN this
  scenario, built from the description, keyphrases and the sample client triggers. No
  person names, no he/she/his/her/"the speaker" anywhere in the document's prose.
- "key_moves": EXACTLY 3 to 6 moves, merged and deduplicated from the candidates. Each
  has "name", "criterion" (what a different account manager's response must satisfy),
  and "evidence" with 3-4 entries. Copy quote/call/account VERBATIM from the candidate
  evidence -- never edit a quote, never invent a call or account. Each move's evidence
  MUST come from at least 3 DISTINCT accounts whenever 3 are available in the candidates.
  EVERY quote must DEMONSTRATE the move, not react to it: discard any candidate quote that
  is a bare acknowledgement ("Got it.", "Understood.", "That makes sense."), a greeting, a
  garbled fragment, an announcement of intent with no substance, or a passage whose
  SUBSTANCE is the account manager ASKING for information rather than providing it (judge
  what it is FOR, not how it starts). If a candidate move has no quote that truly shows the
  behaviour, DROP the move rather than keep it on weak evidence.
  EVERY "criterion" MUST BE GRADABLE FROM A TRANSCRIPT -- it is used to score a real call
  yes/no. Name something concrete that is present or absent: an artifact, a number, a named
  mechanism, a required structure. NEVER use evaluative adjectives ("clear", "effective",
  "scientific", "aligned", "proactive", "appropriate", "comprehensive"). "Clearly explain
  the business impact" is NOT gradable; "state a specific turnaround time in days" is. If a
  move cannot be expressed that way, DROP it.
- "arc": the key move names in the order the expert typically sequences them.
- "signature_language": up to 5 entries, same verbatim rule.
- "pitfalls_and_variants": 0-4 entries, each {"text", "evidence": [>=1 entry]}.
- "layer_d_checks": EXACTLY 3 to 5 coarse yes/no checks a grader could score a
  transcript against for this scenario (derived from the key moves; no names).
Return ONLY JSON:
{"situation_signature": str, "arc": [str],
 "key_moves": [{"name": str, "criterion": str,
                "evidence": [{"quote": str, "call": str, "account": str}]}],
 "signature_language": [{"phrase": str, "quote": str, "call": str, "account": str}],
 "pitfalls_and_variants": [{"text": str,
                            "evidence": [{"quote": str, "call": str, "account": str}]}],
 "layer_d_checks": [str]}"""


def reduce_prompt(header: str, map_outputs: list[dict], triggers: list[str]) -> str:
    trig = [t[:200] for t in triggers[:12]]
    return (f"You are assembling the FINAL coaching playbook for one recurring client\n"
            f"scenario from candidate moves extracted in prior passes.\n\n"
            f"SCENARIO:\n{header}\n\nSAMPLE CLIENT TRIGGERS:\n"
            f"{json.dumps(trig, ensure_ascii=False, indent=1)}\n\n"
            f"CANDIDATE MOVES (one JSON object per prior pass):\n"
            f"{json.dumps(map_outputs, ensure_ascii=False, indent=1)}\n\n"
            f"{REDUCE_RULES}")


def _cit_ok(e) -> bool:
    return (isinstance(e, dict) and str(e.get("quote", "")).strip()
            and str(e.get("call", "")).strip() and str(e.get("account", "")).strip())


def validate_map(out: dict) -> None:
    if not isinstance(out.get("moves"), list) or not out["moves"]:
        raise ValueError("map output: no moves list")
    for m in out["moves"]:
        ev = m.get("evidence")
        if not (isinstance(ev, list) and 1 <= len(ev) <= 6 and all(map(_cit_ok, ev))):
            raise ValueError(f"map output: bad evidence on move {m.get('name')!r}")


def validate_playbook(doc: dict) -> None:
    if not str(doc.get("situation_signature", "")).strip():
        raise ValueError("playbook: empty situation_signature")
    km = doc.get("key_moves")
    if not (isinstance(km, list) and 3 <= len(km) <= 6):
        raise ValueError(f"playbook: {len(km) if isinstance(km, list) else 'no'} "
                         f"key_moves (need 3-6)")
    for m in km:
        ev = m.get("evidence")
        if not (str(m.get("name", "")).strip() and str(m.get("criterion", "")).strip()
                and isinstance(ev, list) and 2 <= len(ev) <= 4
                and all(map(_cit_ok, ev))):
            raise ValueError(f"playbook: bad key move {m.get('name')!r}")
    if not (isinstance(doc.get("arc"), list) and doc["arc"]):
        raise ValueError("playbook: empty arc")
    ldc = doc.get("layer_d_checks")
    if not (isinstance(ldc, list) and 3 <= len(ldc) <= 5):
        raise ValueError("playbook: layer_d_checks must have 3-5 items")
    for e in doc.get("signature_language") or []:
        if not _cit_ok(e):
            raise ValueError("playbook: bad signature_language entry")
    for p in doc.get("pitfalls_and_variants") or []:
        ev = p.get("evidence")
        if not (isinstance(ev, list) and ev and all(map(_cit_ok, ev))):
            raise ValueError("playbook: pitfall without evidence")


# ---------------------------------------------------------------------------------------
# --select
# ---------------------------------------------------------------------------------------

def _ident(sub, extra: dict) -> dict:
    return {"started_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "pid": os.getpid(), "seed": SEED, "corpus_sha": sub["corpus_sha"],
            "taxonomy_sha": sub["taxonomy_sha"], **extra}


def pb_f0(sub) -> list[str]:
    """The pool-unit V0 check, reused: production clause path vs the stage-1 artifact's
    per-scenario clause pools, list-identical for all coachable scenarios."""
    from preprocessing import embedder
    from v2.layer_c import build_clause_pool, _relevance_filter

    pctl = sub["tuning"].layer_c.milestone_relevance_percentile
    stage1_ps = sub["stage1"]["per_scenario"]
    fails = []
    for key, info in sorted(sub["coachable"].items()):
        responses = sub["by_key"].get(key, [])
        expect = (stage1_ps.get(key) or {}).get("clause_pool", [])
        got: list[str] = []
        if len(responses) >= 2:
            clauses, positions, calls, pair_ids = build_clause_pool(responses)
            if len(clauses) >= 6:
                vecs = embedder.embed_document_matrix(clauses)
                fc, _, _, _, _, _ = _relevance_filter(clauses, vecs, positions, calls,
                                                      pair_ids, info, pctl)
                got = fc if len(fc) >= 6 else []
        if got != expect:
            fails.append(key)
    return fails


def build_pool(responses: list[dict], acct: dict[str, str], segment_fn):
    """One scenario's evidence pool in deterministic order, with each pair's u_turn unit
    text (the cached selection-vector source). Returns (pool, n_no_account, n_no_clause)."""
    from calibration.layer_c_pool_unit import units_from_response

    pool, no_acct, no_clause = [], 0, 0
    for r in sorted(responses, key=lambda r: (r["call_filename"], r["turn_index"])):
        stem = Path(r["call_filename"]).stem
        account = acct.get(stem)
        if not account:
            no_acct += 1
            continue
        clauses = segment_fn(r["response_text"])
        units = units_from_response(clauses, r["call_filename"], "u_turn")
        if not units:
            no_clause += 1
            continue
        pool.append({"call": stem, "account": account,
                     "turn_index": r["turn_index"],
                     "trigger_text": r["trigger_text"],
                     "response_text": r["response_text"],
                     "unit_text": units[0]["text"]})
    return pool, no_acct, no_clause


def stage_select(smoke: bool = False) -> None:
    from calibration import layer_b_arms as lb
    from calibration.expanded_pool_stage1 import merge_account_maps
    from calibration.flag_proper_noun_clusters import account_map
    from calibration.layer_c_pool_unit import OLD_DIR, NEW_DIR, build_substrate
    from calibration.layer_bc_arms import _load_cached
    from preprocessing import segmenter

    if not smoke and EVIDENCE.exists():
        raise SystemExit(f"{EVIDENCE.name} exists — refusing to clobber")

    sub = build_substrate(smoke)
    print("[select] PB-F0: production clause path vs stage-1 pools...", flush=True)
    f0_fails = pb_f0(sub)
    if f0_fails and not smoke:
        raise SystemExit(f"PB-F0 FAILED on {f0_fails} — harness bug; nothing reportable")
    if smoke and f0_fails:
        print(f"[SMOKE] PB-F0 diverged on {len(f0_fails)} scenarios — informational "
              f"only on a sliced corpus", flush=True)

    acct_old, _ = account_map(OLD_DIR)
    acct_new, _ = account_map(NEW_DIR)
    if not acct_old or not acct_new:
        raise SystemExit("ABORT: an account map came back empty — missing sidecars")
    acct, _ = lb.collapse_sibling_domains(merge_account_maps([acct_old, acct_new]))

    counts = {k: len(sub["by_key"].get(k, [])) for k in sub["coachable"]}
    if smoke:
        ranked = sorted(counts, key=lambda k: (-counts[k], k))
        pilot = ranked[:min(5, len(ranked))]
        # one populated donor is enough to exercise the placebo path on a sliced corpus
        donors = ({k: ranked[5] for k in pilot}
                  if len(ranked) > 5 and counts[ranked[5]] > 0 else {})
        print(f"[SMOKE] pick rule bypassed on sliced corpus; exercising "
              f"{len(pilot)} scenarios", flush=True)
    else:
        pilot = pick_pilot(counts)
        donors = assign_donors(pilot, counts)
    print("[select] pilot (rank order): "
          + ", ".join(f"{k}({counts[k]}p)" for k in pilot), flush=True)
    for k in pilot:
        if donors:
            print(f"  donor for {k}: {donors[k]} ({counts[donors[k]]}p)", flush=True)

    per_scenario = {}
    for key in sorted(set(pilot) | set(donors.values())):
        pool, no_acct, no_clause = build_pool(sub["by_key"].get(key, []), acct,
                                              segmenter.segment_into_clauses)
        if not pool:
            if smoke:
                print(f"  [{key[:40]:<40}] empty pool on sliced corpus — skipped",
                      flush=True)
                continue
            raise SystemExit(f"ABORT: empty evidence pool for {key!r}")
        mat, missing = _load_cached([p["unit_text"] for p in pool], 3072)
        if mat is None:
            raise SystemExit(f"ABORT: {len(missing)} selection vector(s) uncached for "
                             f"{key!r}, e.g. {missing[:1]!r} — zero embedding spend is "
                             f"a design invariant; do not fetch")
        idx = select_evidence(pool, mat, N_EVIDENCE_MAX,
                              min(ACCT_FLOOR, len({p['account'] for p in pool})))
        # audit N2: keep unit_text — the spec records the vectors' source texts
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

    if smoke:
        print("[SMOKE] nothing written; path OK")
        return
    EVIDENCE.write_text(json.dumps({
        "identity": _ident(sub, {"stage1_artifact": "layer_bc_xp_union.json",
                                 "pb_f0": "PASS"}),
        "ranking": counts, "pilot": pilot, "donors": donors,
        "per_scenario": per_scenario,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[artifact] {EVIDENCE.name} written. ZERO chat calls, ZERO Postgres writes.")


# ---------------------------------------------------------------------------------------
# --synthesize (the ONLY chat spend; resumable per document; every attempt counted)
# ---------------------------------------------------------------------------------------

def doc_jobs(ev: dict) -> list[dict]:
    """The 10 synthesis jobs in frozen order: pilot rank order, real then placebo.
    The placebo's evidence is its DONOR's selection, capped to the real N (volume
    match); its header is the PILOT scenario's."""
    jobs = []
    for key in ev["pilot"]:
        real = ev["per_scenario"][key]["selected"]
        donor = ev["donors"][key]
        plc = ev["per_scenario"][donor]["selected"][:len(real)]
        if len(plc) < len(real):
            print(f"  !! volume mismatch on {key}: real {len(real)} vs placebo "
                  f"{len(plc)} (donor pool smaller) — recorded", flush=True)
        jobs.append({"doc_id": f"{key}::real", "scenario": key, "arm": "real",
                     "evidence": real})
        jobs.append({"doc_id": f"{key}::placebo", "scenario": key, "arm": "placebo",
                     "donor": donor, "evidence": plc})
    return jobs


def stage_synthesize() -> None:
    from calibration.trial_gateway import CHAT_MODEL, GatewayClient
    from calibration.layer_bc_arms import taxonomy_path, scenario_map_from_rows
    from calibration.layer_c_pool_unit import TAXONOMY

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
                           "temperature": CHAT_TEMPERATURE, "no_cache": True},
              "calls_used": 0, "documents": {}})

    def save() -> None:
        PLAYBOOKS.write_text(json.dumps(state, indent=1, ensure_ascii=False),
                             encoding="utf-8")

    gw = GatewayClient(max_retries=1)   # 1 POST per attempt so the count below is exact

    def call(prompt: str, label: str) -> dict:
        last: Exception | None = None
        for attempt in range(1, ATTEMPTS_PER_CALL + 1):
            if state["calls_used"] >= CALL_BUDGET_HARD:
                save()
                raise SystemExit(f"HARD STOP: {state['calls_used']} chat attempts made "
                                 f"(frozen budget {CALL_BUDGET_HARD}). Ask the operator "
                                 f"before any further spend.")
            state["calls_used"] += 1
            save()                       # persist the count BEFORE the attempt
            t0 = time.time()
            try:
                parsed, usage = gw.chat_json(prompt, temperature=CHAT_TEMPERATURE,
                                             no_cache=True)
                state.setdefault("calls", []).append(
                    {"label": label, "attempt": attempt, "ok": True,
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
            # audit N3: schema rejects retry like the reduce loop instead of crashing
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
        for attempt in range(1, ATTEMPTS_PER_CALL + 1):
            doc = call(reduce_prompt(header, maps, triggers),
                       f"{job['doc_id']}/reduce{attempt}")
            try:
                validate_playbook(doc)
                break
            except ValueError as e:
                print(f"  [{job['doc_id']}] schema reject: {e}", flush=True)
                if attempt == ATTEMPTS_PER_CALL:
                    raise SystemExit(f"{job['doc_id']}: reduce never met the schema")
        state["documents"][job["doc_id"]] = {
            "scenario": job["scenario"], "arm": job["arm"],
            "donor": job.get("donor"), "n_evidence": len(job["evidence"]),
            "playbook": doc}
        save()
        print(f"  -> ok ({len(doc['key_moves'])} moves)", flush=True)

    print(f"\nSYNTHESIS COMPLETE: {len(state['documents'])} documents, "
          f"{state['calls_used']} chat attempts (budget {CALL_BUDGET_HARD}).")


# ---------------------------------------------------------------------------------------
# --pb0 / --build-read / --score
# ---------------------------------------------------------------------------------------

def _load_docs() -> tuple[dict, dict]:
    if not (EVIDENCE.exists() and PLAYBOOKS.exists()):
        raise SystemExit("need pb_evidence.json and pb_playbooks.json")
    return (json.loads(EVIDENCE.read_text(encoding="utf-8-sig")),
            json.loads(PLAYBOOKS.read_text(encoding="utf-8-sig")))


def doc_evidence(ev: dict, rec: dict) -> list[dict]:
    """A document's OWN evidence set (real -> its scenario's; placebo -> its donor's,
    capped to the real volume exactly as synthesized)."""
    if rec["arm"] == "real":
        return ev["per_scenario"][rec["scenario"]]["selected"]
    return ev["per_scenario"][rec["donor"]]["selected"][:rec["n_evidence"]]


def stage_pb0() -> None:
    if PB0_REPORT.exists():
        raise SystemExit(f"{PB0_REPORT.name} exists — refusing to clobber")
    ev, pb = _load_docs()
    report, real_pass = {}, 0
    for doc_id, rec in sorted(pb["documents"].items()):
        res = pb0_doc(rec["playbook"], doc_evidence(ev, rec))
        report[doc_id] = {"arm": rec["arm"], **res}
        real_pass += rec["arm"] == "real" and res["pass"]
        print(f"  [{doc_id[:52]:<52}] {'PASS' if res['pass'] else 'FAIL':<5} "
              f"{res['n_quotes']:>3}q {res['n_short_quotes_warn']}short "
              f"{len(res['failures'])}bad", flush=True)
    n_real = sum(1 for r in pb["documents"].values() if r["arm"] == "real")
    verdict = "PASS" if real_pass == n_real else "FAIL"
    plc = {d: r["pass"] for d, r in report.items() if r["arm"] == "placebo"}
    print(f"\nPB0: {real_pass}/{n_real} real playbooks pass -> {verdict}"
          f"   (placebo, symmetric: {sum(plc.values())}/{len(plc)} pass)")
    # audit N1: the spec calls an asymmetry in EITHER direction unexpected
    if (real_pass == n_real) != (sum(plc.values()) == len(plc)):
        print("!! real/placebo PB0 asymmetry — unexpected result: veto-audit code AND "
              "output before believing anything downstream.")
    PB0_REPORT.write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "verdict": verdict, "real_pass": real_pass, "n_real": n_real,
        "per_document": report}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {PB0_REPORT.name}")


def stage_build_read() -> None:
    import random
    if PACKET.exists() or KEY.exists():
        raise SystemExit("read packet / KEY already exist — a read packet is a measured "
                         "instrument; refusing to clobber")
    ev, pb = _load_docs()
    from calibration.layer_bc_arms import taxonomy_path, scenario_map_from_rows
    from calibration.layer_c_pool_unit import TAXONOMY
    tax = json.loads(taxonomy_path(TAXONOMY).read_text(encoding="utf-8-sig"))
    scenario_map, _ = scenario_map_from_rows(tax["rows"])

    rng = random.Random(SEED)
    docs = pb["documents"]
    all_playbooks = [r["playbook"] for _, r in sorted(docs.items())]

    # NEG headers: non-pilot, non-donor coachable scenarios in rank order
    used = set(ev["pilot"]) | set(ev["donors"].values())
    neg_headers = [k for k in sorted(ev["ranking"], key=lambda k: (-ev["ranking"][k], k))
                   if k not in used and scenario_map.get(k, {}).get("is_coachable",
                                                                    True)][:N_NEG]
    if len(neg_headers) < N_NEG:
        raise SystemExit("not enough non-pilot non-donor scenarios for NEG headers")

    items = ([("PAIR", key) for key in ev["pilot"]]
             + [("NEG", h) for h in neg_headers])
    rng.shuffle(items)

    lines = list(PACKET_HEADER)
    key_rows = []
    for i, (kind, scen) in enumerate(items, 1):
        info = scenario_map[scen]
        head = (f"SCENARIO: {scen}\n  {info.get('business_description', '')}")
        if kind == "PAIR":
            real = docs[f"{scen}::real"]["playbook"]
            plc = docs[f"{scen}::placebo"]["playbook"]
            real_side = rng.choice("AB")
            a, b = (real, plc) if real_side == "A" else (plc, real)
            lines.append(f"--- ITEM {i} (PAIR) ---")
            lines.append(head)
            lines.append("DOCUMENT A:")
            lines += render_doc(a)
            lines.append("DOCUMENT B:")
            lines += render_doc(b)
            key_rows.append({"item": i, "kind": "PAIR", "scenario": scen,
                             "real_side": real_side,
                             "n_moves_real": len(real["key_moves"])})
        else:
            neg = build_neg(all_playbooks, rng)
            lines.append(f"--- ITEM {i} (SINGLE) ---")
            lines.append(head)
            lines.append("DOCUMENT:")
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
        "composition": dict(Counter(k for k, _ in items)),
        "items": key_rows}, indent=1), encoding="utf-8")
    print(f"wrote {PACKET.name} ({len(items)} items) and {KEY.name} "
          f"(readers must NEVER see the key)")


def stage_score() -> None:
    if REPORT.exists():
        raise SystemExit(f"{REPORT.name} exists — refusing to clobber")
    ev, pb = _load_docs()
    key = json.loads(KEY.read_text(encoding="utf-8-sig"))
    jd_files = sorted(ARTIFACTS_DIR.glob(JUDGMENTS_GLOB))
    if not jd_files:
        raise SystemExit("no judgment files — dispatch blinded readers first")
    judgments = [json.loads(f.read_text(encoding="utf-8-sig")) for f in jd_files]
    print(f"[score] {len(judgments)} judgment file(s): "
          + ", ".join(f.name for f in jd_files))

    real_moves = {r["scenario"]: len(r["playbook"]["key_moves"])
                  for r in pb["documents"].values() if r["arm"] == "real"}
    read = score_read(key, judgments, real_moves)

    pb1 = {}
    for doc_id, rec in sorted(pb["documents"].items()):
        if rec["arm"] != "real":
            continue
        pb1[rec["scenario"]] = pb1_doc(rec["playbook"], doc_evidence(ev, rec))
    pb1_pass = sum(1 for r in pb1.values() if r["pass"])
    pb0 = (json.loads(PB0_REPORT.read_text(encoding="utf-8-sig"))
           if PB0_REPORT.exists() else {"verdict": "NOT RUN"})

    won = read.get("pb2", {}).get("won", False)
    validated = pb0.get("verdict") == "PASS" and won
    print("=" * 88)
    print(f"PB0 {pb0.get('verdict')} | PB1 {pb1_pass}/{len(pb1)} pass "
          f"({'PASS' if pb1_pass >= 4 else 'FLAG'}) | "
          f"PB2 {'WON' if won else read.get('verdict', 'NOT WON')} | "
          f"PB3 {'PASS' if read.get('pb3', {}).get('pass') else 'FLAG/VOID'}")
    print(f"METHOD {'VALIDATED' if validated else 'NOT VALIDATED'} "
          f"(decision rule: PB0 PASS and PB2 WON)")
    print("=" * 88)
    REPORT.write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "pb0_verdict": pb0.get("verdict"),
        "pb1": {"per_scenario": pb1, "n_pass": pb1_pass,
                "pass": pb1_pass >= 4},
        "read": read,
        "method_validated": validated,
        "chat_attempts_used": pb.get("calls_used"),
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {REPORT.name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--smoke", action="store_true",
                   help="path test on 25+25 calls; zero chat, nothing written")
    p.add_argument("--select", action="store_true")
    p.add_argument("--synthesize", action="store_true")
    p.add_argument("--pb0", action="store_true")
    p.add_argument("--build-read", action="store_true")
    p.add_argument("--score", action="store_true")
    a = p.parse_args()
    if a.smoke:
        stage_select(smoke=True)
    if a.select:
        stage_select()
    if a.synthesize:
        stage_synthesize()
    if a.pb0:
        stage_pb0()
    if a.build_read:
        stage_build_read()
    if a.score:
        stage_score()
    if not any([a.smoke, a.select, a.synthesize, a.pb0, a.build_read, a.score]):
        p.print_help()


if __name__ == "__main__":
    main()
