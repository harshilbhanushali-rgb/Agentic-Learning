#!/usr/bin/env python3
"""W4 BLIND-READ BUILDER + SCORER for the Layer C clustering bench. Free, no embeddings.

Spec: docs/superpowers/specs/2026-08-17-layer-c-clustering-bench-design.md gate W4.
Precedent: calibration/blind_read_powered.py (separate samples/key files, judgments
committed before the key is opened, scrambled negatives as the instrument check,
positive controls EXPECTED ~half-imperfect).

DESIGN, FROZEN BEFORE ANY READING:

* Partition arms (leiden, hdb_half): each paired item is ONE arm milestone vs ONE c0
  milestone at MATCHED SUPPORT (|support_calls diff| <= max(2, 25% of the larger)),
  paired within the same scenario when possible, nearest-support across scenarios
  otherwise, sampled without replacement, sides randomized per item. Question: which
  group is more coherent as ONE coaching move (A / B / EQUAL).
* rescue: the unit of reading for a modifying rule is the MODIFICATION. Each paired
  item is one c0 cluster's CONTEXT (sampled original member clauses) plus the
  rescue-ADMITTED clauses vs the placebo-ADMITTED clauses for that same cluster
  (volume-matched by the placebo's construction), sides randomized. Question: which
  added set belongs to the group (A / B / EQUAL).
* Instrument check per packet: NEG scrambled items (real clauses from >=4 unrelated c0
  milestones glued; SINGLE items display no support metadata — audit F2) — a reader
  rejecting < 80% of them is VOID. POS items (highest-support c0 milestones) are
  recorded, not gating (published blind read: ~half imperfect is EXPECTED).
* Scoring, frozen: reader-majority per pair among VALID readers; ties (EQUAL majority
  or no majority) count AGAINST the arm in the 2/3 fraction and are dropped from the
  sign test. WON = arm preferred in >= 2/3 of paired items AND n >= 12 pairs AND
  two-sided sign test p < 0.05.

PRE-RUN BLIND AUDIT (2026-08-17, before --build ran): 4 outcome-bearing findings, all
fixed: (F1) identical-twin pairing — count-matched arms reproduce c0 clusters exactly and
the nearest-support rule PREFERRED the twin, forcing EQUAL ties that count against the
arm; twins are now excluded at Jaccard >= 0.5 (frozen). (F2) NEG/POS singles were
separable by displayed support metadata (POS = top-support milestones, NEG sampled from
the paired range; plus an impossible bullets>sentences marker) — SINGLE items now display
no support metadata at all. (F3) the rescue read joins against SURVIVING c0 milestones
only, silently excluding gate-crossing clusters (the ones rescue's W1/W2 case rests on);
full fix needs pregate persistence the artifacts don't have — the excluded share is now
counted and printed loudly (estimand restriction ON THE RECORD: prior F1 measured 99.3%
of admissions land on already-passing clusters, so the read covers the dominant mass).
(F4) partition pairs displayed unequal bullet counts (hdb_half's clusters are
systematically smaller — an identity marker AND a coherence advantage); both sides of a
pair now display the same number of clauses. Verified clean by the audit: sign test
(hand-checked values), frozen tie rule, key/sample separation, RNG discipline,
without-replacement pairing.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/layer_c_bench_w4_build.py --build
    ..\\.venv\\Scripts\\python.exe calibration/layer_c_bench_w4_build.py --score
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402

SEED = 17
N_PAIRS = 15          # target pairs per arm (gate needs >= 12)
N_NEG = 8
N_POS = 8
CLAUSES_SHOWN = 5
SUPPORT_TOL_FRAC = 0.25
PARTITION_ARMS = ("leiden", "hdb_half")
NEG_REJECT_BAR = 0.80

# Registered arms. Bench arms read layer_bc_cb_*; pool-unit arms (u_*) read layer_bc_pu_*
# (2026-08-18 extension for the pool-unit trial's V2 — paths/registry only, the pairing,
# controls and scoring logic below are unchanged from the audited bench instrument).
PAIRED_ARMS = (*PARTITION_ARMS, "u_win")   # arm-vs-c0 milestone pairs
ALL_READ_ARMS = (*PAIRED_ARMS, "rescue")

SAMPLES = {arm: ARTIFACTS_DIR / f"w4_read_{arm}.txt" for arm in ALL_READ_ARMS}
KEYS = {arm: ARTIFACTS_DIR / f"w4_read_{arm}_KEY.json" for arm in ALL_READ_ARMS}
JUDGMENTS = {arm: ARTIFACTS_DIR / f"w4_judgments_{arm}.json" for arm in ALL_READ_ARMS}
REPORT = ARTIFACTS_DIR / "w4_report.json"
PU_REPORT = ARTIFACTS_DIR / "w4_report_pu.json"


def load_arm(arm: str) -> dict:
    prefix = "layer_bc_pu_" if arm.startswith("u_") else "layer_bc_cb_"
    p = ARTIFACTS_DIR / f"{prefix}{arm}.json"
    if not p.exists():
        raise SystemExit(f"missing artifact {p.name}")
    return json.loads(p.read_text(encoding="utf-8-sig"))


def all_milestones(art: dict) -> list[dict]:
    out = []
    for key, rec in art["per_scenario"].items():
        for m in rec.get("milestones") or []:
            out.append({**m, "scenario_key": key})
    return out


def support_matched(a: dict, b: dict) -> bool:
    hi = max(a["support_calls"], b["support_calls"])
    return abs(a["support_calls"] - b["support_calls"]) <= max(2, int(SUPPORT_TOL_FRAC * hi))


TWIN_JACCARD = 0.5   # audit F1, frozen: a c0 milestone this similar is the same cluster


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 1.0


def build_pairs_partition(arm_ms: list[dict], c0_ms: list[dict],
                          rng: random.Random) -> list[dict]:
    """Same-scenario support-matched pairs first, then cross-scenario nearest-support.
    Sampling without replacement on both sides. Identical-twin candidates (audit F1) are
    excluded — an arm milestone paired with its own c0 twin can only be judged EQUAL,
    which the frozen tie rule counts against the arm."""
    arm_pool = arm_ms[:]
    c0_pool = c0_ms[:]
    rng.shuffle(arm_pool)
    pairs = []
    for a in arm_pool:
        if len(pairs) >= N_PAIRS:
            break
        ok = [c for c in c0_pool
              if support_matched(a, c) and jaccard(a["clauses"], c["clauses"]) < TWIN_JACCARD]
        same = [c for c in ok if c["scenario_key"] == a["scenario_key"]]
        cand = same or ok
        if not cand:
            continue
        c = min(cand, key=lambda c: abs(c["support_calls"] - a["support_calls"]))
        c0_pool.remove(c)
        pairs.append({"arm_ms": a, "c0_ms": c, "same_scenario": bool(same)})
    return pairs


def admitted_clauses(mod_art: dict, c0_art: dict) -> tuple[dict[tuple, dict], dict]:
    """(scenario_key, cluster_id) -> {'added': [...], 'context': [...]} for every cluster
    the modifying arm enlarged. rescue/placebo preserve c0's labels, so identity is exact.

    Audit F3, ON THE RECORD: the artifacts persist only support-SURVIVING milestones, so a
    c0 cluster that was below the gate and crossed it via admissions has no c0 counterpart
    here and is EXCLUDED from the read. The excluded share is returned and printed — the
    estimand is 'modifications to already-supported clusters' (prior F1 measurement: 99.3%
    of admissions land there)."""
    out = {}
    excluded = {"clusters": 0, "clauses_upper_bound": 0}
    for key, rec in mod_art["per_scenario"].items():
        c0_rec = c0_art["per_scenario"].get(key) or {}
        c0_by_label = {m["cluster_id"]: m for m in c0_rec.get("milestones") or []}
        for m in rec.get("milestones") or []:
            base = c0_by_label.get(m["cluster_id"])
            if base is None:
                excluded["clusters"] += 1
                excluded["clauses_upper_bound"] += len(m["clauses"])
                continue
            added = [cl for cl in m["clauses"] if cl not in set(base["clauses"])]
            if added:
                out[(key, m["cluster_id"])] = {"added": added,
                                               "context": base["clauses"]}
    return out, excluded


def build_pairs_rescue(resc: dict, plc: dict, c0: dict, rng: random.Random) -> list[dict]:
    ra, excl_r = admitted_clauses(resc, c0)
    pa, excl_p = admitted_clauses(plc, c0)
    print(f"[rescue] F3 estimand restriction: gate-crossing clusters EXCLUDED from the "
          f"read — rescue {excl_r['clusters']} clusters (<= {excl_r['clauses_upper_bound']} "
          f"clauses), placebo {excl_p['clusters']} (<= {excl_p['clauses_upper_bound']})")
    both = sorted(set(ra) & set(pa))
    rng.shuffle(both)
    pairs = []
    for k in both:
        if len(pairs) >= N_PAIRS:
            break
        if len(ra[k]["added"]) < 2 or len(pa[k]["added"]) < 2:
            continue
        pairs.append({"cluster": k, "context": ra[k]["context"],
                      "rescue_added": ra[k]["added"], "placebo_added": pa[k]["added"]})
    return pairs


def scrambled(pool: list[dict], n: int, rng: random.Random) -> list[dict]:
    """NEGATIVE control: real clauses from >=4 unrelated milestones glued together.
    No support metadata is carried — SINGLE items display none (audit F2), so there is
    no metadata channel to grade by."""
    out = []
    for _ in range(n):
        srcs = rng.sample(pool, min(5, len(pool)))
        out.append({"clauses": [rng.choice(s["clauses"]) for s in srcs]})
    return out


def show(clauses: list[str], rng: random.Random, k: int = CLAUSES_SHOWN) -> list[str]:
    """Seeded sample of up to k clauses — both sides of a pair are shown the SAME number
    of clauses (audit F4: unequal bullet counts are an identity marker and a coherence
    advantage for the smaller cluster)."""
    cl = list(clauses)
    if len(cl) > k:
        cl = rng.sample(cl, k)
    return [c.strip()[:220] for c in cl]


HEADER = [
    "BLIND READ -- coaching-milestone coherence (W4)",
    "",
    "A 'group' below is a set of sentences taken from one sales expert's replies across",
    "several real client calls. A GOOD group is ONE coherent coaching move: the sentences",
    "are different instances of the same specific thing the expert does, which another",
    "account manager could learn and apply to a DIFFERENT client. Generic filler",
    "(agreeing, thanking, offering to follow up) is NOT a move.",
    "",
    "There are two item formats, shuffled together:",
    "",
    "  PAIR items show GROUP A and GROUP B. Answer which group is more coherent as one",
    "  move:      <n>: A      or   <n>: B      or   <n>: EQUAL",
    "  Some PAIR items instead show a CONTEXT group plus two candidate ADDITIONS; answer",
    "  which addition belongs to the context group (A / B / EQUAL).",
    "",
    "  SINGLE items show one group. Answer whether it is one coherent move:",
    "             <n>: YES     or   <n>: NO",
    "",
    "Judge ONLY what is written. Do not try to infer where an item came from, and do not",
    "assume any particular share of answers. Answer EVERY item, one line each.",
    "=" * 96, ""]


def emit_packet(arm: str, pairs: list[dict], c0_ms: list[dict],
                rng: random.Random) -> None:
    """Write the samples file (readers see this) and the key (readers never do)."""
    pos = sorted(c0_ms, key=lambda m: -m["support_calls"])[:N_POS]
    neg = scrambled(c0_ms, N_NEG, rng)

    items = ([("PAIR", p) for p in pairs]
             + [("POS", m) for m in pos]
             + [("NEG", m) for m in neg])
    rng.shuffle(items)

    lines = list(HEADER)
    key_rows = []
    for i, (kind, obj) in enumerate(items, 1):
        if kind == "PAIR" and "arm_ms" in obj:
            arm_side = rng.choice("AB")
            a_ms = obj["arm_ms"] if arm_side == "A" else obj["c0_ms"]
            b_ms = obj["c0_ms"] if arm_side == "A" else obj["arm_ms"]
            # audit F4: both sides show the same number of clauses
            k = min(CLAUSES_SHOWN, len(a_ms["clauses"]), len(b_ms["clauses"]))
            lines.append(f"--- ITEM {i} (PAIR) ---")
            lines.append(f"  GROUP A  ({a_ms['support_calls']} calls):")
            lines += [f"    - {c}" for c in show(a_ms["clauses"], rng, k)]
            lines.append(f"  GROUP B  ({b_ms['support_calls']} calls):")
            lines += [f"    - {c}" for c in show(b_ms["clauses"], rng, k)]
            key_rows.append({"item": i, "kind": "PAIR", "arm_side": arm_side,
                             "scenario": obj["arm_ms"]["scenario_key"],
                             "same_scenario": obj["same_scenario"]})
        elif kind == "PAIR":
            arm_side = rng.choice("AB")
            a_add = obj["rescue_added"] if arm_side == "A" else obj["placebo_added"]
            b_add = obj["placebo_added"] if arm_side == "A" else obj["rescue_added"]
            k = min(CLAUSES_SHOWN, len(a_add), len(b_add))
            lines.append(f"--- ITEM {i} (PAIR: context + two candidate additions) ---")
            lines.append("  CONTEXT group:")
            lines += [f"    - {c}" for c in show(obj["context"], rng)]
            lines.append("  ADDITION A:")
            lines += [f"    - {c}" for c in show(a_add, rng, k)]
            lines.append("  ADDITION B:")
            lines += [f"    - {c}" for c in show(b_add, rng, k)]
            key_rows.append({"item": i, "kind": "PAIR", "arm_side": arm_side,
                             "cluster": list(obj["cluster"])})
        else:
            lines.append(f"--- ITEM {i} (SINGLE) ---")
            lines += [f"    - {c}" for c in show(obj["clauses"], rng)]
            key_rows.append({"item": i, "kind": kind})
        lines.append("")

    SAMPLES[arm].write_text("\n".join(lines), encoding="utf-8")
    KEYS[arm].write_text(json.dumps({
        "arm": arm, "seed": SEED, "n_pairs": len(pairs),
        "composition": dict(Counter(k for k, _ in items)),
        "answers": key_rows,
    }, indent=1), encoding="utf-8")
    print(f"[{arm}] {len(pairs)} pairs + {N_POS} pos + {N_NEG} neg -> "
          f"{SAMPLES[arm].name} (KEY: {KEYS[arm].name} — readers must never see it)")


def build(arms: list[str]) -> None:
    c0 = load_arm("c0")
    c0_ms = all_milestones(c0)
    for arm in arms:
        if SAMPLES[arm].exists() or KEYS[arm].exists():
            raise SystemExit(f"{SAMPLES[arm].name} / its KEY already exist — a read "
                             f"packet is a measured instrument; refusing to clobber it")
        rng = random.Random(SEED)
        if arm in PAIRED_ARMS:
            pairs = build_pairs_partition(all_milestones(load_arm(arm)), c0_ms, rng)
        else:
            pairs = build_pairs_rescue(load_arm("rescue"), load_arm("rescue_plc"),
                                       c0, rng)
        if len(pairs) < 12:
            print(f"[{arm}] only {len(pairs)} pairs — W4/V2 UNDERPOWERED")
        emit_packet(arm, pairs, c0_ms, rng)


# ---------------------------------------------------------------------------------------
# --score: judgments + key -> W4 verdicts. Run ONLY after judgments files exist.
# ---------------------------------------------------------------------------------------

def sign_test_two_sided(up: int, down: int) -> float:
    from math import comb
    n = up + down
    if n == 0:
        return 1.0
    k = min(up, down)
    p = sum(comb(n, i) for i in range(0, k + 1)) / 2 ** n * 2
    return min(1.0, p)


def score(arms: list[str]) -> None:
    report = {}
    for arm in arms:
        if not JUDGMENTS[arm].exists():
            print(f"[{arm}] no judgments file — skipped")
            continue
        key = json.loads(KEYS[arm].read_text(encoding="utf-8-sig"))
        jd = json.loads(JUDGMENTS[arm].read_text(encoding="utf-8-sig"))
        readers = jd["readers"]          # {name: {item_number(str): answer}}
        rows = {r["item"]: r for r in key["answers"]}

        valid = {}
        for name, ans in readers.items():
            negs = [i for i, r in rows.items() if r["kind"] == "NEG"]
            rej = sum(1 for i in negs if str(ans.get(str(i), "")).upper() == "NO")
            ok = rej / len(negs) >= NEG_REJECT_BAR if negs else False
            print(f"[{arm}] reader {name}: rejected {rej}/{len(negs)} negatives "
                  f"-> {'VALID' if ok else 'VOID'}")
            if ok:
                valid[name] = ans
        if not valid:
            report[arm] = {"verdict": "VOID", "reason": "no valid reader"}
            continue

        pos_yes = Counter()
        for name, ans in valid.items():
            for i, r in rows.items():
                if r["kind"] == "POS":
                    pos_yes[name] += str(ans.get(str(i), "")).upper() == "YES"

        up = down = tie = 0
        for i, r in rows.items():
            if r["kind"] != "PAIR":
                continue
            votes = Counter()
            for ans in valid.values():
                v = str(ans.get(str(i), "")).upper()
                if v in ("A", "B"):
                    votes["arm" if v == r["arm_side"] else "other"] += 1
                elif v == "EQUAL":
                    votes["tie"] += 1
            if votes["arm"] > max(votes["other"], votes["tie"]):
                up += 1
            elif votes["other"] > max(votes["arm"], votes["tie"]):
                down += 1
            else:
                tie += 1
        n_pairs = up + down + tie
        frac = up / n_pairs if n_pairs else 0.0
        p = sign_test_two_sided(up, down)
        won = n_pairs >= 12 and frac >= 2 / 3 and p < 0.05
        report[arm] = {"n_pairs": n_pairs, "arm_preferred": up, "c0_preferred": down,
                       "ties": tie, "fraction": frac, "p": p, "won": won,
                       "valid_readers": sorted(valid),
                       "pos_yes_per_reader": dict(pos_yes)}
        print(f"[{arm}] pairs={n_pairs} arm={up} other={down} tie={tie} "
              f"frac={frac:.2f} p={p:.4f} -> {'WON' if won else 'NOT WON'}")

    # pool-unit reads report separately so the bench's closed w4_report is never rewritten
    out = PU_REPORT if all(a.startswith("u_") for a in report) and report else REPORT
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"wrote {out.name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--build", action="store_true")
    p.add_argument("--score", action="store_true")
    p.add_argument("--arms", default=",".join(ALL_READ_ARMS))
    a = p.parse_args()
    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    bad = [x for x in arms if x not in ALL_READ_ARMS]
    if bad:
        raise SystemExit(f"unknown arm(s) {bad}; registry: {ALL_READ_ARMS}")
    if a.build:
        build(arms)
    if a.score:
        score(arms)
    if not (a.build or a.score):
        p.print_help()


if __name__ == "__main__":
    main()
