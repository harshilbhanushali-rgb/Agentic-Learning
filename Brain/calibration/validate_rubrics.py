#!/usr/bin/env python3
"""Give Layer C an objective function: validate every milestone before scoring anyone.

Run from Brain/:
    python calibration/validate_rubrics.py                  # DRY RUN -- zero Gemma calls
    python calibration/validate_rubrics.py --run            # measure (~105 Gemma calls)
    python calibration/validate_rubrics.py --run --apply    # measure AND store verdicts
    python calibration/validate_rubrics.py --load artifacts/rubric_validation.json

Design: docs/superpowers/specs/2026-08-11-layer-c-objective-function-design.md

WHY THIS EXISTS

Layer C admits a milestone on three gates -- distinct-call support (does it recur?),
relevance percentile (is it on-topic?), the review-flag judge (is it plausible?). Nothing
measures the two properties the 2026-08-11 ceiling run proved decisive:

    discrimination   can this criterion tell its own scenario apart from another?
    satisfiability   can anyone satisfy it when the moment calls for it?

Layer C is working as specified; the specification was incomplete. That is the root cause
behind four consecutive fixes each nudging the hit rate and none breaking 4%.

WHAT IT MEASURES, PER MILESTONE

    A3    the call-level-holdout responses scored against their OWN rubric
    B     the SAME responses scored against an UNRELATED rubric (the null)
    APPL  which milestones the CLIENT TURN actually called for

Discrimination is W(A3) - W(B), both UNCONDITIONAL: filtering arm B by applicability
would shrink its denominator and inflate the null. Satisfiability is W(A3) over
applicable instances only -- "did you do it when it was needed" rather than "did you do
it". applicable_rate is the contingency measurement Layer C cannot currently produce at
all: 234 of 235 milestones are labelled sequencing_type "fixed" and the conditional
trigger fires 0 of 226 times, so every contingent move is emitted as mandatory.

THE QUESTION THIS RUN ANSWERS. Of the 66% of milestones the expert never fully satisfies,
how many are UNREACHABLE versus merely CONDITIONAL? Mostly conditional means the rubrics
are largely fine and the grading model was the bug -- a much cheaper world. Mostly
unreachable means the milestone is the wrong unit of feedback. No amount of further
reasoning decides this; only the run does.

IT VALIDATES ITSELF BEFORE ITS VERDICTS COUNT. The ceiling run already produced a
labelled set, so --self-check replays it: the 7 scenarios whose control scored exactly
0.000 must come out validated-heavy, and the 7 INVERTED ones not_discriminating-heavy. If
it cannot reproduce that split the instrument is wrong and nothing it says counts. Same
discipline as the ceiling harness proving its hoisted benchmark ranking matched
production's before spending a single Gemma call.

THE APPLICABILITY JUDGE HAS ITS OWN NULL. It is a new, unvalidated Gemma judgement, so it
is also asked about milestones from an UNRELATED rubric, where the applicable rate must
collapse. ~6 calls, built in from the start rather than promised later.

CIRCULARITY THAT REMAINS, STATED RATHER THAN HIDDEN. Validation uses the expert's own
held-out responses, so a milestone describing something only he does still passes. This
measures "satisfiable by the author on unseen calls", NOT "satisfiable by a competent
CSM". That is a strictly weaker claim and must travel with every verdict.

WRITES: only with --apply, and only rubrics.milestones[i].validation. No DDL, no other
table, no checkpoint. Without --apply the connection is read-only at the Postgres level.
"""
from __future__ import annotations

import argparse
import json
import random
import sys as _sys
from collections import Counter
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR, score_naren_ceiling as snc
from config import load_config
from ego_trap import milestone_scoring
from shared import rubric_validation as rv
from shared import storage
from shared.gemma import GemmaError
from shared.tuning import get_tuning

# Deliberately matching score_naren_ceiling's defaults so the A3 sample is the SAME
# sample. That is what makes this run's per-milestone numbers directly comparable with
# the corpus-level ceiling result, and what lets --self-check mean anything.
_DEFAULT_BASELINE = "arm3_run1_20260810"
_DEFAULT_SEED = 20260811
_DEFAULT_PER_SCENARIO = 8
_BATCH_SIZE = 12

# Enough to see the applicable rate collapse, cheap enough to always run. Request
# packing, not a threshold, so a module constant -- same precedent as
# v2/layer_c._DESCRIBE_BATCH_SIZE.
_NULL_CHECK_ITEMS = 72

_CEILING_ARTIFACT = ARTIFACTS_DIR / "naren_ceiling.json"

# The ceiling run's own per-scenario labelling rule, reproduced so --self-check compares
# against its PUBLISHED split rather than a re-derivation. Verified against
# naren_ceiling.json 2026-08-12: at these values the reconstruction yields 40 qualifying
# scenarios, 16 discriminating and 7 zero-control -- matching the spec exactly. The band
# matters: reading "inverted" as merely gap < 0 gives 15, not the published 7, because the
# spec applies the same +/-0.05 band to both directions.
_CEILING_MIN_ATTEMPTS = 15
_CEILING_BAND = 0.05

_VERDICT_ORDER = (rv.VALIDATED, rv.CONTINGENT, rv.NOT_SATISFIABLE,
                  rv.NOT_DISCRIMINATING, rv.INSUFFICIENT_EVIDENCE)


# --------------------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------------------

def counter_zero() -> dict:
    return {"attempts": 0, "hits": 0, "partial": 0}


def tally(counter: dict, verdict: str) -> None:
    counter["attempts"] += 1
    if verdict == "full_hit":
        counter["hits"] += 1
    elif verdict == "partial_hit":
        counter["partial"] += 1


def applicability_counters(records: list[dict], applicable: dict) -> tuple[dict, dict]:
    """(applicable counters, judged counters) per (rubric_id, milestone_id).

    `applicable` maps (pair_id, scenario_key) -> the set of ids the client's turn called
    for, or None where the judge was silent. It is keyed PER RESPONSE, not per scenario:
    two responses in one scenario legitimately call for different milestones, and that is
    precisely the quantity being measured.

    An unanswered exchange is excluded from BOTH counters, and an exchange missing from
    the dict entirely (a batch that raised) behaves identically. Counting silence as "not
    applicable" manufactures contingency out of a dropped batch; counting it as
    "applicable" manufactures unsatisfiability. Both would be findings invented by a
    failure.
    """
    appl: dict[tuple, dict] = {}
    judged: dict[tuple, dict] = {}
    for r in records:
        answer = applicable.get((r["pair_id"], r["scenario_key"]))
        if answer is None:
            continue
        key = (r["rubric_id"], r["milestone_id"])
        tally(judged.setdefault(key, counter_zero()), r["verdict"])
        if r["milestone_id"] in answer:
            tally(appl.setdefault(key, counter_zero()), r["verdict"])
    return appl, judged


def build_verdicts(a3_records: list[dict], b_records: list[dict],
                   applicable: dict) -> dict[str, dict]:
    """One classified record per (rubric_id, milestone_id), keyed "<rubric_id>::<id>".

    Keyed off A3, so a milestone that only ever appeared in arm B produces nothing: with
    no matched-arm measurement, a discrimination gap would be computed from one arm. An
    absent B counter, by contrast, is a legitimate zero null -- the partner scenario's A3
    pool is a different size, so the two arms are comparable but not equal in length.
    """
    a3 = snc.aggregate(a3_records)
    b = snc.aggregate(b_records)
    appl, judged = applicability_counters(a3_records, applicable)

    out = {}
    for key, a3_counts in a3.items():
        record = rv.classify(
            a3=a3_counts,
            b=b.get(key, counter_zero()),
            applicable=appl.get(key, counter_zero()),
            applicability_scored=judged.get(key, counter_zero()),
        )
        record["rubric_id"] = key[0]
        record["milestone_id"] = key[1]
        record["scenario_key"] = a3_counts["scenario_key"]
        out[f"{key[0]}::{key[1]}"] = record
    return out


def scenario_rollup(verdicts: dict[str, dict]) -> dict[str, Counter]:
    rollup: dict[str, Counter] = {}
    for record in verdicts.values():
        rollup.setdefault(record["scenario_key"], Counter())[record["verdict"]] += 1
    return rollup


def scenario_verdicts(a3_records: list[dict], b_records: list[dict]) -> dict[str, dict]:
    """Ship / hold / disable per SCENARIO, aggregating every milestone of its rubric.

    This is the headline output. The per-milestone verdicts are computed too, but they
    failed both of their own validity gates on 2026-08-12 -- see rubric_validation's
    SCENARIO-level section for the measured reason -- whereas this resolution reproduced
    the ceiling run's published table exactly.

    Records are grouped by `scenario_key`, which in BOTH arms is the scenario whose
    RUBRIC was scored, never the response's own. That is what makes the two arms
    comparable: each rubric's own attempts against each rubric's null.
    """
    arms: dict[str, dict] = {}
    for arm, records in (("A3", a3_records), ("B", b_records)):
        for r in records:
            slot = arms.setdefault(r["scenario_key"],
                                   {"A3": counter_zero(), "B": counter_zero()})
            tally(slot[arm], r["verdict"])
    return {key: rv.classify_scenario(v["A3"], v["B"]) for key, v in arms.items()}


def applicable_rate_overall(applicable: dict) -> tuple[int, int]:
    """(applicable ids returned, ids that could have been returned) across all answers."""
    returned = sum(len(v) for v in applicable.values() if v is not None)
    answered = sum(1 for v in applicable.values() if v is not None)
    return returned, answered


# --------------------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------------------

def _items_for(keys, rng_pools, ranked_pools, rubrics, partner, per_scenario, seed):
    """A3 items (own rubric), B items (partner's rubric) and applicability items.

    All three arms use THE SAME A3 responses. The ceiling run drew arm B from the primary
    (leaked) sample because it was comparing whole corpora; here the comparison is
    per milestone, so both arms must be the same population or the difference is partly a
    difference of sample.
    """
    rng = random.Random(seed)
    a3_items, b_items, appl_items, plan = [], [], [], {}
    for key in keys:
        primary, secondary, primary_calls = rng_pools[key]
        pool = snc.a3_eligible(secondary, primary_calls)
        sample = snc.take_sample(pool, per_scenario, rng)
        plan[key] = {"a3_available": len(pool), "a3_n": len(sample),
                     "partner": partner.get(key),
                     "milestones": len(rubrics[key].get("milestones") or [])}
        for row in sample:
            a3_items.append(snc._item(row, key, key, rubrics, ranked_pools))
            appl_items.append({
                "pair_id": row["pair_id"], "scenario_key": key,
                "rubric": rubrics[key],
                "client_utterance": row.get("trigger_text") or "",
            })
            pkey = partner.get(key)
            if pkey:
                b_items.append(snc._item(row, key, pkey, rubrics, ranked_pools))
    return a3_items, b_items, appl_items, plan


def _judge_applicability(items: list[dict], config, batch_size: int,
                         label: str) -> dict:
    """(pair_id, scenario_key) -> applicable id set, or None where the judge was silent.

    `include` asks about EVERY milestone, not just contingent ones: at validation time no
    milestone carries a verdict, so the production default would select nothing and this
    whole measurement would come back silently empty.
    """
    out = {}
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    print(f"\n[{label}] judging {len(items)} exchange(s) in {len(batches)} batch(es)...")
    for b_idx, batch in enumerate(batches, start=1):
        try:
            answers = milestone_scoring.judge_applicability_batch(
                [{"rubric": it["rubric"], "client_utterance": it["client_utterance"]}
                 for it in batch],
                config, include=lambda m: True,
            )
        except GemmaError as e:
            print(f"  ! [{label}] batch {b_idx}/{len(batches)} FAILED: {e} — "
                  f"{len(batch)} exchange(s) left unjudged (NOT retried, to protect quota)")
            answers = [None] * len(batch)
        for it, answer in zip(batch, answers):
            out[(it["pair_id"], it["scenario_key"])] = answer
        print(f"  [{label}] batch {b_idx}/{len(batches)} judged ({len(batch)})")
    return out


def _null_check(appl_items, rubrics, partner, config, batch_size, limit) -> dict:
    """The applicability judge's own control: ask it about an UNRELATED rubric.

    The judge is a brand-new Gemma judgement with nothing behind it, and this design's
    conclusions rest on it. If it returns the same applicable rate for a rubric drawn
    from a deliberately unrelated scenario, it is not reading the client turn at all --
    the identical failure mode arm B caught in the scorer, and the reason arm B was not
    optional there either.
    """
    swapped = []
    for it in appl_items[:limit]:
        pkey = partner.get(it["scenario_key"])
        if pkey:
            swapped.append(dict(it, rubric=rubrics[pkey],
                                scenario_key=f"NULL::{it['scenario_key']}"))
    if not swapped:
        return {}
    return _judge_applicability(swapped, config, batch_size, "APPL-null")


def _write_verdicts(conn, rubrics: dict, verdicts: dict, run_id: str,
                    scored_by: str | None) -> tuple[int, int]:
    """Merge each verdict onto its milestone, in place, preserving everything else.

    Rebuilds the array by POSITION and writes only the milestones column, exactly as
    ops/rewrite_milestone_criteria.py does. rv.with_validation is what guarantees the
    support evidence, criteria_rewritten and not_coachable_flag survive -- upsert_rubric
    replaces this column wholesale, so anything dropped here is gone permanently.
    """
    conn = storage.reconnect_if_closed(conn)
    written = rubrics_touched = 0
    with conn.cursor() as cur:
        for scenario_key, rubric in rubrics.items():
            rubric_id = rubric["rubric_id"]
            cur.execute("SELECT milestones FROM rubrics WHERE rubric_id = %s",
                        (rubric_id,))
            row = cur.fetchone()
            if row is None:
                continue
            milestones = row[0] or []
            ids = milestone_scoring.milestone_ids(milestones)
            touched = False
            for position, milestone_id in enumerate(ids):
                record = verdicts.get(f"{rubric_id}::{milestone_id}")
                if record is None or not isinstance(milestones[position], dict):
                    continue
                milestones[position] = rv.with_validation(
                    milestones[position], _storable(record), run_id, scored_by)
                touched = True
                written += 1
            if touched:
                cur.execute(
                    "UPDATE rubrics SET milestones = %s::jsonb WHERE rubric_id = %s",
                    (json.dumps(milestones), rubric_id))
                rubrics_touched += 1
    return written, rubrics_touched


def _storable(record: dict) -> dict:
    """The verdict without the identifiers the milestone already carries positionally."""
    return {k: v for k, v in record.items()
            if k not in ("scenario_key", "milestone_id", "rubric_id")}


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------

def _self_check(verdicts: dict, ceiling_path: _Path) -> dict:
    """Replay the ceiling run's own labelled split. If this fails, nothing here counts.

    Two populations were measured there and are not up for reinterpretation: 7 scenarios
    whose unrelated-rubric control scored exactly 0.000 (real working instruments), and 7
    that INVERTED (the wrong rubric scored higher). A validator that cannot tell them
    apart is measuring something else.
    """
    if not ceiling_path.exists():
        return {"status": "skipped", "reason": f"{ceiling_path.name} not found"}
    payload = json.loads(ceiling_path.read_text(encoding="utf-8"))
    per_scenario: dict[str, dict] = {}
    for arm in ("A3", "B"):
        for r in payload.get("arms", {}).get(arm, {}).get("records", []):
            c = per_scenario.setdefault(r["scenario_key"], {"A3": counter_zero(),
                                                            "B": counter_zero()})
            tally(c[arm], r["verdict"])

    zero_control, inverted = [], []
    for key, c in per_scenario.items():
        if c["A3"]["attempts"] < _CEILING_MIN_ATTEMPTS or c["B"]["attempts"] < _CEILING_MIN_ATTEMPTS:
            continue
        w_a3 = rv.weighted(c["A3"]["hits"], c["A3"]["partial"], c["A3"]["attempts"])
        w_b = rv.weighted(c["B"]["hits"], c["B"]["partial"], c["B"]["attempts"])
        if w_b == 0.0 and w_a3 > 0:
            zero_control.append(key)
        elif w_a3 - w_b < -_CEILING_BAND:
            inverted.append(key)

    rollup = scenario_rollup(verdicts)

    def _share(keys, wanted):
        total = sum(sum(rollup.get(k, Counter()).values()) for k in keys)
        hit = sum(sum(rollup.get(k, Counter())[w] for w in wanted) for k in keys)
        return hit, total

    ok_hit, ok_total = _share(zero_control, (rv.VALIDATED, rv.CONTINGENT))
    bad_hit, bad_total = _share(inverted, (rv.NOT_DISCRIMINATING,))
    return {
        "status": "ran",
        "zero_control_scenarios": sorted(zero_control),
        "inverted_scenarios": sorted(inverted),
        "zero_control_scoreable": [ok_hit, ok_total],
        "inverted_not_discriminating": [bad_hit, bad_total],
        "passes": (ok_total > 0 and ok_hit / ok_total >= 0.5
                   and bad_total > 0 and bad_hit / bad_total >= 0.5),
    }


def _dead_milestone_split(verdicts: dict, ceiling_path: _Path) -> dict:
    """THE HEADLINE. Of the milestones the author never fully satisfies, how many are
    unreachable and how many were simply never called for?"""
    dead = [r for r in verdicts.values() if r["a3_w"] == 0.0]
    split = Counter(r["verdict"] for r in dead)
    return {"n_dead": len(dead), "split": dict(split),
            "median_applicable_rate": _median([r["applicable_rate"] for r in dead])}


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


_SCENARIO_ORDER = (rv.SCENARIO_SHIP, rv.SCENARIO_HOLD, rv.SCENARIO_DISABLE,
                   rv.SCENARIO_INSUFFICIENT)


def _report_scenarios(payload: dict) -> None:
    """The headline: which rubrics are production-ready and which must be turned off."""
    verdicts = payload.get("scenario_verdicts") or {}
    if not verdicts:
        return
    print("\n" + "=" * 108)
    print("SCENARIO VERDICTS — is this rubric a working instrument?")
    print("=" * 108)
    print(f"{'gap':>7} {'A3 W':>6} {'B W':>6} {'A3n':>5} {'Bn':>5}  {'verdict':<18} scenario")
    print("-" * 108)
    for key, v in sorted(verdicts.items(), key=lambda kv: -kv[1]["gap"]):
        # The zero-control note ANNOTATES the verdict, it never replaces it. Printing
        # "ship (control 0.000)" on a row whose verdict is insufficient_data -- which
        # happens whenever the control arm is empty, since 0 attempts scores 0.000 --
        # labelled unmeasured rubrics as shippable in this table's first outing.
        mark = v["verdict"] + (" *" if v["control_is_zero"] else "")
        print(f"{v['gap']:+7.3f} {v['a3_w']:6.3f} {v['b_w']:6.3f} "
              f"{v['a3_attempts']:5d} {v['b_attempts']:5d}  {mark:<18} {key}")
    print("  * control scored exactly 0.000 (note only; read the verdict column)")

    counts = Counter(v["verdict"] for v in verdicts.values())
    zero = sum(1 for v in verdicts.values() if v["control_is_zero"])
    print("\n" + "-" * 108)
    for verdict in _SCENARIO_ORDER:
        n = counts.get(verdict, 0)
        print(f"  {verdict:<20} {n:>4}  ({n / len(verdicts):>5.1%})")
    print(f"  {'of which control=0.000':<20} {zero:>4}")
    print(f"  {'TOTAL':<20} {len(verdicts):>4}")

    print("\n  DISABLING THE INVERTED SET WILL LOWER THE REPORTED HIT RATE, and that is")
    print("  the measurement improving, not a regression. Measured 2026-08-12 against the")
    print("  real CSM run: the CSM scores HIGHEST on exactly the scenarios that should be")
    print("  turned off (W 0.114 there vs 0.064 on the ones that ship), because generic")
    print("  criteria are satisfied by almost anything. Say so before anyone sees it.")


def _report(payload: dict) -> None:
    verdicts = payload.get("verdicts") or {}
    _report_scenarios(payload)
    print("\n" + "=" * 92)
    print("LAYER C OBJECTIVE FUNCTION — per-milestone discrimination, satisfiability, "
          "applicability")
    print("=" * 92)

    for arm in ("A3", "B"):
        t = payload.get("arm_totals", {}).get(arm)
        if not t or not t["attempts"]:
            print(f"  {arm:<4} no data")
            continue
        print(f"  {arm:<4} {t['attempts']:>5} att | {t['hits']:>4} hit "
              f"({t['hits'] / t['attempts']:>5.1%}) | {t['partial']:>4} part | "
              f"W {t['W']:.3f}")

    if not verdicts:
        print("\n  (no verdicts — this was a dry run or the scoring arms are empty)")
        return

    print("\n" + "-" * 92)
    print(f"VERDICTS across {len(verdicts)} milestone(s)")
    print("-" * 92)
    counts = Counter(r["verdict"] for r in verdicts.values())
    for verdict in _VERDICT_ORDER:
        n = counts.get(verdict, 0)
        print(f"  {verdict:<22} {n:>4}  ({n / len(verdicts):>5.1%})")
    scoreable = counts.get(rv.VALIDATED, 0) + counts.get(rv.CONTINGENT, 0)
    print(f"  {'-> scoreable':<22} {scoreable:>4}  ({scoreable / len(verdicts):>5.1%})")

    # THE ANSWER TO §7. Read this before anything else in the report.
    dead = payload.get("dead_split", {})
    if dead:
        print("\n" + "-" * 92)
        print(f"THE QUESTION THIS RUN ANSWERS — {dead['n_dead']} milestone(s) the author "
              f"never fully satisfies")
        print("-" * 92)
        for verdict, n in sorted(dead["split"].items(), key=lambda kv: -kv[1]):
            print(f"  {verdict:<22} {n:>4}")
        print(f"  median applicable_rate among them: {dead['median_applicable_rate']:.2f}")
        print("  Mostly CONTINGENT/INSUFFICIENT at a low rate  -> the rubrics are largely")
        print("  fine and the GRADING MODEL was the bug (the cheap world).")
        print("  Mostly NOT_SATISFIABLE                        -> the criteria genuinely")
        print("  cannot be met, and the milestone is the wrong unit of feedback.")

    check = payload.get("self_check", {})
    print("\n" + "-" * 92)
    print("SELF-VALIDATION against the ceiling run's own labelled split")
    print("-" * 92)
    if check.get("status") != "ran":
        print(f"  SKIPPED: {check.get('reason', 'unknown')} — verdicts above are "
              f"UNVALIDATED and must not be acted on.")
    else:
        ok_hit, ok_total = check["zero_control_scoreable"]
        bad_hit, bad_total = check["inverted_not_discriminating"]
        print(f"  {len(check['zero_control_scenarios'])} zero-control scenario(s): "
              f"{ok_hit}/{ok_total} milestones scoreable "
              f"({(ok_hit / ok_total if ok_total else 0):.1%}, want >= 50%)")
        print(f"  {len(check['inverted_scenarios'])} inverted scenario(s): "
              f"{bad_hit}/{bad_total} not_discriminating "
              f"({(bad_hit / bad_total if bad_total else 0):.1%}, want >= 50%)")
        print("  -> " + ("PASSES — verdicts are citable" if check["passes"] else
                         "*** FAILS — the instrument is wrong and NOTHING above "
                         "counts ***"))

    null = payload.get("applicability_null", {})
    if null:
        print("\n" + "-" * 92)
        print("APPLICABILITY JUDGE'S OWN NULL (it is a new, otherwise unvalidated "
              "judgement)")
        print("-" * 92)
        print(f"  matched rubric   {null['matched_rate']:.2f} ids per exchange "
              f"({null['matched_answered']} answered)")
        print(f"  unrelated rubric {null['null_rate']:.2f} ids per exchange "
              f"({null['null_answered']} answered)")
        collapsed = null["null_rate"] <= 0.5 * null["matched_rate"]
        print("  -> " + ("collapses as required" if collapsed else
                         "*** DOES NOT COLLAPSE — the judge is not reading the client "
                         "turn, so applicable_rate and every satisfiability figure are "
                         "void ***"))

    print("\n" + "-" * 92)
    print("SCENARIOS WITH NO SCOREABLE MILESTONE LEFT")
    print("-" * 92)
    rollup = scenario_rollup(verdicts)
    empty = sorted(k for k, c in rollup.items()
                   if not (c[rv.VALIDATED] + c[rv.CONTINGENT]))
    print(f"  {len(empty)} of {len(rollup)}")
    for key in empty[:20]:
        print(f"    {key}  ({dict(rollup[key])})")

    print("\n" + "=" * 92)
    print("SCOPE OF THE CLAIM: these verdicts say a milestone is satisfiable BY ITS OWN")
    print("AUTHOR ON UNSEEN CALLS. That is strictly weaker than 'satisfiable by a")
    print("competent CSM', and it must be quoted that way wherever it is used.")
    print("=" * 92)


def _print_samples(payload: dict, n: int) -> None:
    """Real criteria behind each verdict. Every large finding in this pipeline came from
    reading samples, never from a summary statistic."""
    verdicts = payload.get("verdicts") or {}
    text = payload.get("milestone_text", {})
    for verdict in _VERDICT_ORDER:
        rows = [r for r in verdicts.values() if r["verdict"] == verdict]
        rows.sort(key=lambda r: -r["a3_attempts"])
        print("\n" + "=" * 92)
        print(f"[{verdict}] {len(rows)} milestone(s)")
        print("=" * 92)
        for r in rows[:n]:
            print(f"\n  {r['scenario_key']} :: {r['milestone_id']}")
            print(f"    A3 W {r['a3_w']:.3f} ({r['a3_attempts']} att) | "
                  f"B W {r['b_w']:.3f} ({r['b_attempts']} att) | "
                  f"gap {r['discrimination']:+.3f}")
            print(f"    applicable {r['a3_applicable']}/{r['a3_applicability_scored']} "
                  f"(rate {r['applicable_rate']:.2f}) | "
                  f"W|applicable {r['a3_w_applicable']:.3f}")
            criterion = text.get(f"{r['rubric_id']}::{r['milestone_id']}", "")
            if criterion:
                print(f"    criterion : {criterion[:190]}")


# --------------------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", action="store_true",
                    help="actually measure (spends Gemma calls). Default is a dry run.")
    ap.add_argument("--apply", action="store_true",
                    help="store the verdicts onto rubrics.milestones. Requires --run.")
    ap.add_argument("--load", help="re-report a persisted artifact, zero cost")
    ap.add_argument("--baseline", default=_DEFAULT_BASELINE)
    ap.add_argument("--scope", choices=("baseline", "all"), default="baseline",
                    help="'baseline' = the scenarios one Layer D run happened to touch "
                         "(49). 'all' = every rubric carrying a milestone (82), so the "
                         "33 never exercised by any CSM transcript also get a verdict. "
                         "'all' needs no CSM data at all -- it is Naren against himself.")
    ap.add_argument("--skip-applicability", action="store_true",
                    help="omit the APPL and APPL-null arms. Measured 2026-08-12 the "
                         "applicability judge FAILED its own null (0.147 vs 0.120 "
                         "applicable fraction, 1.22:1), so its numbers are void and "
                         "paying ~55 calls for them is waste. Skipping leaves the "
                         "scenario-level ship/hold/disable verdict, which held.")
    ap.add_argument("--per-scenario", type=int, default=_DEFAULT_PER_SCENARIO)
    ap.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    ap.add_argument("--batch-size", type=int, default=_BATCH_SIZE)
    ap.add_argument("--samples", type=int, default=6,
                    help="milestones to print per verdict")
    ap.add_argument("--max-items-per-arm", type=int, default=0,
                    help="cap items per arm (0 = no cap). A small value gives a cheap "
                         "end-to-end path test whose NUMBERS ARE NOT A MEASUREMENT.")
    ap.add_argument("--run-id", default="",
                    help="provenance label stored as validated_at_run. Defaults to "
                         "validate:<baseline>:<seed>.")
    ap.add_argument("--ceiling", default=str(_CEILING_ARTIFACT),
                    help="the ceiling artifact --self-check replays")
    ap.add_argument("--out", default=str(ARTIFACTS_DIR / "rubric_validation.json"))
    args = ap.parse_args()

    if args.load:
        payload = json.loads(_Path(args.load).read_text(encoding="utf-8"))
        _report(payload)
        _print_samples(payload, args.samples)
        return
    if args.apply and not args.run:
        raise SystemExit("ERROR: --apply requires --run; there is nothing to store yet.")

    cfg = load_config()
    tuning = get_tuning().layer_d
    run_id = args.run_id or f"validate:{args.baseline}:{args.seed}"

    # Read-only at the Postgres level unless a write was explicitly asked for. Stronger
    # than a code-review promise: it also protects against a future edit accidentally
    # introducing a write.
    conn = (storage.get_connection(cfg.database_url) if args.apply
            else snc._connect_read_only(cfg.database_url))
    try:
        if args.scope == "all":
            with conn.cursor() as cur:
                cur.execute("""SELECT scenario_key FROM rubrics
                               WHERE jsonb_array_length(milestones) > 0
                               ORDER BY scenario_key""")
                keys = [r[0] for r in cur.fetchall()]
        else:
            keys = snc._scope(conn, args.baseline)
        scen_info = {s["scenario_key"]: s for s in storage.get_scenarios(conn)}
        rubrics = {}
        for key in keys:
            rubric = storage.get_rubric_for_scenario(conn, key)
            if rubric and (rubric.get("milestones") or []):
                rubrics[key] = rubric
        keys = [k for k in keys if k in rubrics]
        print(f"[scope] {len(keys)} scenario(s) with rubrics from {args.baseline}")

        pools = {k: snc._pools(conn, k) for k in keys}

        # Pre-flight: refuse to encode anything. _embed_matrix reaches the model only
        # inside `if missing:`, so 100% coverage means the 400MB sentence-transformer
        # never loads -- which is what stops this silently starting a GPU pass on a box
        # where a torch allocation can fail outright with [WinError 1455].
        texts = []
        for key in keys:
            texts += [r["response_text"] for r in
                      storage.get_responses_for_scenario_multilabel(conn, key)]
            texts.append(snc._scenario_text(scen_info[key]))
        cached, distinct = snc._cache_coverage(texts)
        print(f"[preflight] embed cache {cached}/{distinct} "
              f"({cached / distinct if distinct else 1:.1%}) of distinct texts")
        if cached < distinct:
            raise SystemExit(
                f"ABORT: {distinct - cached} text(s) are not cached, so running would "
                f"load the sentence-transformer and encode on this machine. Warm the "
                f"cache deliberately first.")

        ranked_pools = {k: snc._ranked_benchmark_pool(conn, k, scen_info[k]) for k in keys}

        sim = snc._scenario_sim_matrix(keys, scen_info)
        threshold = get_tuning().layer_a.merge_cosine_threshold
        partner, method = snc.derange(keys, sim, threshold, random.Random(args.seed))
        if partner is None:
            raise SystemExit(f"ABORT: could not build arm B pairings ({method}).")
        if method != "derangement":
            # The greedy fallback is not a permutation, so two scenarios can be scored
            # against one rubric while another receives no arm-B attempts at all -- its
            # milestones would then be classified against an EMPTY null and pass
            # discrimination for free.
            raise SystemExit(
                f"ABORT: arm B pairing fell back to {method}. Per-milestone "
                f"discrimination needs a permutation so every rubric receives a null; "
                f"without one some milestones would be judged against no control.")
        print(f"[arm B] pairing method: {method} (cosine < {threshold})")

        a3_items, b_items, appl_items, plan = _items_for(
            keys, pools, ranked_pools, rubrics, partner, args.per_scenario, args.seed)
        if args.max_items_per_arm:
            cap = args.max_items_per_arm
            a3_items, b_items, appl_items = a3_items[:cap], b_items[:cap], appl_items[:cap]
            print(f"[smoke] capped to {cap} item(s) per arm — this is a PATH test, its "
                  f"numbers are not a measurement")

        print(f"\n{'scenario':<46} {'ms':>3} {'a3':>5} {'A3n':>4}  partner")
        print("-" * 110)
        for key in keys:
            p = plan[key]
            print(f"{key:<46} {p['milestones']:>3} {p['a3_available']:>5} "
                  f"{p['a3_n']:>4}  {p['partner']}")

        def _calls(items):
            return -(-len(items) // args.batch_size)

        null_n = 0 if args.skip_applicability else min(len(appl_items), _NULL_CHECK_ITEMS)
        est = _calls(a3_items) + _calls(b_items)
        if not args.skip_applicability:
            est += _calls(appl_items) + _calls(appl_items[:null_n])
        print(f"\n[plan] scope={args.scope}  items  A3={len(a3_items)}  B={len(b_items)}  "
              f"APPL={0 if args.skip_applicability else len(appl_items)}  "
              f"APPL-null={null_n}")
        print(f"[plan] Gemma calls ~{est}")
        print(f"[plan] skip_uncoachable_milestones = {tuning.skip_uncoachable_milestones}")
        print(f"[plan] validated_at_run = {run_id!r}")
        print(f"[plan] write verdicts = {args.apply}")

        if not args.run:
            print("\n[dry run] no Gemma calls made. Re-run with --run to measure.")
            return

        # Every paid result is flushed the moment its arm finishes. The first version of
        # the ceiling harness assembled a payload containing one small DB lookup and
        # wrote it afterwards; the connection had gone idle across ~55 minutes of Gemma
        # calls, that free lookup raised, and 95 calls' worth of verdicts died in memory.
        # A free operation must never be able to destroy an expensive one.
        out = _Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        partial = out.with_suffix(".partial.json")

        payload = {
            "baseline_schema": args.baseline, "seed": args.seed,
            "per_scenario": args.per_scenario, "batch_size": args.batch_size,
            "max_items_per_arm": args.max_items_per_arm,
            "scenarios": keys, "plan": plan, "partner": partner,
            "pairing_method": method, "run_id": run_id,
            "skip_uncoachable": tuning.skip_uncoachable_milestones,
            "arm_totals": {}, "records": {}, "applicability": {},
            "verdicts": {}, "milestone_text": {},
        }

        def _flush():
            partial.write_text(json.dumps(payload, indent=2, default=str),
                               encoding="utf-8")

        arm_records = {}
        for arm, items in (("A3", a3_items), ("B", b_items)):
            records, models = snc._score_arm(arm, items, cfg,
                                             tuning.skip_uncoachable_milestones,
                                             args.batch_size)
            arm_records[arm] = records
            payload["arm_totals"][arm] = snc.arm_totals(records)
            payload["arm_totals"][arm]["models"] = dict(models)
            payload["records"][arm] = records
            _flush()
            print(f"  [{arm}] {len(records)} verdict(s) flushed to {partial.name}")

        # The SCENARIO verdict needs neither arm beyond A3 and B, so it is computed and
        # flushed before anything else is attempted. It is the headline result and the
        # only resolution that has passed every validity check.
        payload["scenario_verdicts"] = scenario_verdicts(arm_records["A3"],
                                                         arm_records["B"])
        _flush()

        if args.skip_applicability:
            applicable = {}
            print("\n[APPL] skipped (--skip-applicability). Per-milestone satisfiability "
                  "and applicable_rate are NOT measured in this run.")
        else:
            applicable = _judge_applicability(appl_items, cfg, args.batch_size, "APPL")
            payload["applicability"] = {
                f"{k[0]}::{k[1]}": (sorted(v) if v is not None else None)
                for k, v in applicable.items()}
            _flush()

            null = _null_check(appl_items, rubrics, partner, cfg, args.batch_size, null_n)
            m_returned, m_answered = applicable_rate_overall(applicable)
            n_returned, n_answered = applicable_rate_overall(null)
            payload["applicability_null"] = {
                "matched_rate": m_returned / m_answered if m_answered else 0.0,
                "matched_answered": m_answered,
                "null_rate": n_returned / n_answered if n_answered else 0.0,
                "null_answered": n_answered,
            }
            _flush()

        payload["verdicts"] = build_verdicts(arm_records["A3"], arm_records["B"],
                                             applicable)
        payload["milestone_text"] = {
            f"{r['rubric_id']}::{r['milestone_id']}": r["milestone_description"]
            for r in arm_records["A3"]
        }
        payload["dead_split"] = _dead_milestone_split(payload["verdicts"],
                                                      _Path(args.ceiling))
        payload["self_check"] = _self_check(payload["verdicts"], _Path(args.ceiling))
        _flush()

        if args.apply:
            check = payload["self_check"]
            if check.get("status") == "ran" and not check.get("passes"):
                print("\n  ! SELF-VALIDATION FAILED — verdicts NOT written. The "
                      "instrument could not reproduce the ceiling run's own labelled "
                      "split, so nothing it says counts.")
            else:
                try:
                    written, touched = _write_verdicts(
                        conn, rubrics, payload["verdicts"], run_id,
                        payload["arm_totals"]["A3"].get("models", {}) and
                        next(iter(payload["arm_totals"]["A3"]["models"]), None))
                    payload["written"] = {"milestones": written, "rubrics": touched}
                    print(f"\n[applied] {written} verdict(s) across {touched} rubric(s).")
                except Exception as e:  # noqa: BLE001 -- a written artifact beats a crash
                    print(f"\n  ! writing verdicts failed: {e}")
                    print("  ! every measured verdict is still in the artifact; re-run "
                          "--load and apply separately.")

        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        partial.unlink(missing_ok=True)
        print(f"\n[artifact] {out}")

        _report(payload)
        _print_samples(payload, args.samples)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
