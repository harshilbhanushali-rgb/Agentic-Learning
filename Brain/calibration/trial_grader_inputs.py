#!/usr/bin/env python3
"""Does the Layer D grader discriminate once it can SEE the situation? ~80-160 chat calls.

Spec: docs/superpowers/specs/2026-08-15-grader-inputs-design.md
ZERO Postgres writes. Reads scenarios/rubrics/kb_pairs; writes only an artifact.

THE DEFECT, READ FROM SOURCE NOT INFERRED. ego_trap/milestone_scoring.py builds each
exchange out of Naren's benchmark, the CSM response, and per milestone `description` +
`detection_hint`. The CLIENT TURN, the SCENARIO and the milestone's own `label` are all
stored and all discarded at grading time.

WHY THAT COULD INVALIDATE FOUR VERDICTS. The ceiling's control arm scores real responses
against a DELIBERATELY UNRELATED scenario's rubric. A grader blind to which situation
either belongs to cannot notice the mismatch, and the 2026-08-10 rewrite stripped the
specific instance out of the criteria, so a competent sales response satisfies generic
criteria from any scenario. **1.2:1 is what that arrangement predicts arithmetically,
whatever the rubrics are worth.** And trial_layer_c_arms.py scores its SITUATED-WRITER
arms with this same blind scorer (line 261) -- so "situating the writer did not help" was
measured by an instrument that discards situation. That is circular, and this trial is the
non-circular version.

NOT A FOURTH WORDING PASS (stopping condition #1). The verdict rules, the three-way scale
and the JSON contract are byte-identical; only the fields in each exchange change. This
repairs a missing INPUT -- the same defect already root-caused in the Layer C WRITER, one
stage later.

*** DESIGN: POPULATION-SYMMETRIC BY CONSTRUCTION, WHICH THE CEILING RUN WAS NOT. ***
CLAUDE.md records that the ceiling's cited 1.61:1 compares A3 against B across DIFFERENT
response populations (A3 draws secondary-label rows, B draws A1's), and that no arm pair
there is both leakage-clean and symmetric. Here every condition scores THE SAME responses
against BOTH its own rubric and a deranged partner's, so:
  - matched and unrelated share one population exactly -- no B3 arm is missing;
  - leakage inflates both conditions equally, because the treatment is the PROMPT and the
    data is held fixed, so no holdout machinery is needed and only the RATIO is read;
  - the four conditions score identical items, so a difference between them cannot come
    from sampling.
Absolute W is therefore NOT comparable to the ceiling run's W. Only ratios are.

ONE FIELD AT A TIME, per the CLAUDE.md note that named this test:
  blind    production, nothing added                                      (control)
  label    + milestone `label`   -- where the rewrite's stripped subject matter still lives
  turn     + the CLIENT TURN     -- the situation itself
  full     + scenario + turn + label

PRE-REGISTERED BEFORE ANY DATA WAS SEEN (movable only by editing this file in a diff):
  metric        W = (full_hit + 0.5*partial_hit)/attempts, the definition
                gap_output.milestone_miss_rate and measure_scoring_noise.py already use.
  primary       discrimination D = W(matched)/W(unrelated), per condition.
  PASS          any situated condition reaches D >= 2.0. That is not a new bar: the
                ceiling's own gate is _T_INSTRUMENT = 0.5, "W(B) >= 0.5 x W(A3) => the
                instrument is invalid, discard everything", and D >= 2.0 is its inverse.
  FAIL          no condition reaches 2.0 => the grader's blindness is NOT the binding
                constraint, Wall 1 stands, and this line of attack closes with the other
                four. A FAIL is a real result and must be reported as one.
  uncertainty   D's 95% CI by bootstrap over ITEMS (not milestones -- milestones within an
                item share a response and are not independent). Overlapping CIs between
                blind and a situated arm mean the move is not established, whatever the
                point estimates do.
  sampling      seeded and STRATIFIED over posture (`client_*`) vs subject-matter. Never
                the first N: --limit on trial_layer_c_arms.py once returned nothing but
                subject-matter scenarios because every posture key sorts after `budget`,
                silently testing a fix on the half that already worked.
  provenance    `judged_by` per verdict and a model histogram per arm. Run 2 of the
                head-to-head still blended 8-18% of batches under rate limits even when
                pinned; without this field a verdict has unknown provenance.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/trial_grader_inputs.py --smoke
    ..\\.venv\\Scripts\\python.exe calibration/trial_grader_inputs.py
    ..\\.venv\\Scripts\\python.exe calibration/trial_grader_inputs.py --load
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OUT = ARTIFACTS_DIR / "grader_inputs_trial.json"
CKPT = ARTIFACTS_DIR / "grader_inputs_trial_ckpt.json"

CONDITIONS = {
    "blind": frozenset(),
    "label": frozenset({"label"}),
    "turn": frozenset({"client_turn"}),
    "full": frozenset({"scenario", "client_turn", "label"}),
}
PIN_MODEL = "gemini-3.5-flash-lite"
D_PASS = 2.0                      # inverse of score_naren_ceiling._T_INSTRUMENT = 0.5
BOOTSTRAP = 2000
# Stamped into every condition so an artifact says which estimator produced its interval.
# An artifact written before 2026-08-15 carries per-item-mean CIs and no such field, and the
# two are not comparable -- see bootstrap_d.
CI_ESTIMATOR = "pooled_w_over_resampled_items"
# PRE-REGISTERED FOR THE CONFIRMATION RUN, before it was launched. The pooled ratio D is
# NOT the bar -- its denominator is near zero and its CI came out [1.59, 10.02]. The bar is
# the per-scenario paired count, which divides by nothing: the right rubric must beat the
# wrong one in >= 70% of decided scenarios, at p < 0.05, on BOTH independent response draws.
# Anything less is reported as unconfirmed.
SIGN_BAR = 0.70


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sample", type=int, default=20, help="scenarios, stratified + seeded")
    p.add_argument("--per-scenario", type=int, default=3, help="responses per scenario")
    p.add_argument("--batch-size", type=int, default=6, help="exchanges per chat call")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--smoke", action="store_true",
                   help="3 scenarios x 1 response, ~8 calls. ALWAYS run this first -- two "
                        "full launches in this codebase died mid-generation on faults "
                        "py_compile cannot catch. Numbers are NOT interpretable.")
    p.add_argument("--model", default=PIN_MODEL,
                   help="pin the scoring model. The headline run used gemini-3.5-flash-lite; "
                        "PRODUCTION's _SCORING_MODEL is gemini-3.1-flash-lite and the ceiling "
                        "run's control arm was a 793/1040 blend of the two. Re-running one "
                        "condition on 3.1 is what separates 'the ceiling's arms were built "
                        "differently' from 'the model changed underneath it'.")
    p.add_argument("--conditions", default="",
                   help="comma-separated subset of " + ",".join(CONDITIONS)
                        + " (default: all). Used for the single-condition model control.")
    p.add_argument("--tag", default="", help="artifact suffix, so a control run does not "
                                             "overwrite the headline")
    p.add_argument("--holdout", action="store_true",
                   help="draw the responses from the LEAKAGE-CLEAN stratum: rows carrying "
                        "the scenario as a secondary label whose call contributed no primary "
                        "pair, so the rubric cannot have been written from them. Combined "
                        "with this trial's symmetric matched/unrelated pairing this is the "
                        "arm CLAUDE.md records as never built -- leakage-clean AND "
                        "population-symmetric at the same time.")
    p.add_argument("--gateway", action="store_true",
                   help="route chat through the Joveo gateway instead of AI Studio.")
    p.add_argument("--fresh", action="store_true", help="ignore the checkpoint")
    p.add_argument("--load", action="store_true", help="re-report the artifact, free")
    return p.parse_args()


def _gateway_chat(model: str):
    """A `chat` callable backed by the Joveo gateway instead of Google AI Studio.

    WHY: AI Studio's per-key quota stalls these runs -- observed repeatedly as
    "hit a rate/quota limit ... Rotating to key #2", with gemma.py's backoff adding up to
    62s per call. The gateway is the transport the Layer A Gemini work already used for
    ~245 sequential adjudication calls. Only the transport differs: both force JSON and
    both parse with json.loads, so the contract is identical -- the equivalence
    trial_adjudicate_gemini.py already relies on.
    """
    from calibration.trial_gateway import GatewayClient
    gw = GatewayClient()

    def _chat(prompt: str):
        parsed, _ = gw.chat_json(prompt, model=model, temperature=0.2)
        return parsed
    return _chat


def weighted(hits: int, partial: int, attempts: int) -> float:
    return (hits + 0.5 * partial) / attempts if attempts else 0.0


def stratified_sample(keys: list[str], n: int, rng: random.Random) -> list[str]:
    """Seeded, proportional over posture vs subject-matter. See the sampling note above."""
    posture = sorted(k for k in keys if k.startswith("client_"))
    subject = sorted(k for k in keys if not k.startswith("client_"))
    if n >= len(keys):
        return sorted(keys)
    n_post = min(len(posture), max(1, round(n * len(posture) / len(keys)))) if posture else 0
    n_subj = min(len(subject), n - n_post)
    out = rng.sample(posture, n_post) + rng.sample(subject, n_subj)
    return sorted(out)


def sign_test(recs: list[dict]) -> dict:
    """Per-SCENARIO paired comparison: does the right rubric beat the wrong one?

    THIS IS THE STATISTIC TO TRUST, not the pooled ratio D. D divides by W(unrelated),
    which is near zero -- a couple of stray ticks move it from 3 to 9, which is exactly why
    its bootstrap CI came out [1.59, 10.02]. Counting scenario-level wins does not divide by
    anything, so it cannot be destabilised that way, and one loud scenario cannot carry it.

    Pairing is on `source_scenario` -- the RESPONSE's own scenario -- so a matched item and
    the unrelated item built from the SAME response land in the same bucket. Pairing on the
    rubric's key instead would compare different responses and quietly answer another
    question.

    Ties (both sides identical, usually both zero) carry no information and are excluded
    from the test, but are reported: if most scenarios tie at zero, nothing here is
    interpretable however the surviving ones fall.
    """
    # Records written before source_scenario existed cannot be paired: falling back to
    # scenario_key would bucket an unrelated item under its PARTNER's name, pairing two
    # different responses and answering a question nobody asked. Refuse instead.
    if any("source_scenario" not in r for r in recs):
        return {"unavailable": "records predate source_scenario; re-run with --fresh",
                "wins": 0, "losses": 0, "ties": 0, "decided": 0,
                "win_share": float("nan"), "p_value": float("nan"), "scenarios": []}
    by_scen: dict[str, dict[str, list]] = defaultdict(lambda: {"matched": [], "unrelated": []})
    for r in recs:
        by_scen[r["source_scenario"]][r["kind"]].append(r)
    wins = losses = ties = 0
    detail = []
    for k, sides in sorted(by_scen.items()):
        if not sides["matched"] or not sides["unrelated"]:
            continue
        wm, wu = item_w(sides["matched"]), item_w(sides["unrelated"])
        if wm > wu:
            wins += 1
        elif wm < wu:
            losses += 1
        else:
            ties += 1
        detail.append({"scenario": k, "w_matched": wm, "w_unrelated": wu,
                       "n_matched": len(sides["matched"]), "n_unrelated": len(sides["unrelated"])})
    decided = wins + losses
    share = wins / decided if decided else float("nan")
    # Two-sided exact binomial against p=0.5, computed without scipy.
    p = float("nan")
    if decided:
        from math import comb
        tail = sum(comb(decided, i) for i in range(min(wins, losses) + 1)) / 2 ** decided
        p = min(1.0, 2 * tail)
    return {"wins": wins, "losses": losses, "ties": ties, "decided": decided,
            "win_share": share, "p_value": p, "scenarios": detail}


def item_w(records: list[dict]) -> float:
    h = sum(1 for r in records if r["verdict"] == "full_hit")
    p = sum(1 for r in records if r["verdict"] == "partial_hit")
    return weighted(h, p, len(records))


def item_counts(records: list[dict]) -> tuple[int, int, int]:
    """(full_hits, partial_hits, attempts) for one item -- the terms W is built from."""
    h = sum(1 for r in records if r["verdict"] == "full_hit")
    p = sum(1 for r in records if r["verdict"] == "partial_hit")
    return h, p, len(records)


def bootstrap_d(by_item_matched: dict, by_item_unrelated: dict, rng: np.random.Generator):
    """95% CI for D, resampling ITEMS. Milestones inside an item share a response.

    THE RESAMPLED W IS POOLED, exactly as the point estimate is. Each item contributes its
    (hits, partial, attempts) and W is recomputed from the summed counts, so an item holding
    six milestones weighs six times an item holding one -- which is what
    `W = (full + 0.5*partial)/attempts` means and what the pre-registration fixed.

    It previously averaged per-item W values unweighted, a DIFFERENT estimator from the
    point estimate it was quantifying. Measured on the shipped artifacts the two disagree by
    -0.02 to +1.9, and in `confirmB` the resulting interval [2.116, 3.645] excluded its own
    point estimate of 2.114.

    Takes (hits, partial, attempts) triples, not pre-divided W values: the division has to
    happen AFTER the resampled counts are summed, so a per-item W cannot be un-averaged.
    """
    keys = sorted(set(by_item_matched) & set(by_item_unrelated))
    if not keys:
        return float("nan"), float("nan")
    m = np.array([by_item_matched[k] for k in keys], dtype=float)      # (K, 3)
    u = np.array([by_item_unrelated[k] for k in keys], dtype=float)
    ds = []
    for _ in range(BOOTSTRAP):
        pick = rng.integers(0, len(keys), size=len(keys))
        mh, mp, mn = m[pick].sum(axis=0)
        uh, up, un = u[pick].sum(axis=0)
        wu = weighted(uh, up, un)
        if wu > 0:
            ds.append(weighted(mh, mp, mn) / wu)
    if not ds:
        return float("nan"), float("nan")
    return float(np.percentile(ds, 2.5)), float(np.percentile(ds, 97.5))


def report(p: dict) -> None:
    print("\n" + "=" * 90)
    print("DOES SHOWING THE GRADER THE SITUATION MAKE IT DISCRIMINATE?")
    print("=" * 90)
    print(f"  {p['n_scenarios']} scenarios, {p['n_responses']} responses, "
          f"{p['n_items']} items/condition (matched + unrelated on IDENTICAL responses)")
    print(f"  model pinned: {p['pin_model']}   bar: D >= {D_PASS}")
    print(f"\n{'condition':<10}{'W matched':>11}{'W unrelated':>13}{'D':>8}"
          f"{'95% CI':>18}{'attempts':>10}  models")
    for name in CONDITIONS:
        a = p["conditions"].get(name)
        if not a:
            continue
        ci = f"[{a['ci_lo']:.2f}, {a['ci_hi']:.2f}]"
        if a.get("ci_estimator", "") != CI_ESTIMATOR:
            ci += " !"          # pre-2026-08-15 per-item-mean interval; not comparable
        models = ", ".join(f"{k.split('-')[-2] if k else '?'}:{v}"
                           for k, v in sorted(a["models"].items(), key=lambda x: -x[1])[:2])
        flag = "  PASS" if a["D"] >= D_PASS else ""
        print(f"{name:<10}{a['w_matched']:>11.3f}{a['w_unrelated']:>13.3f}{a['D']:>8.2f}"
              f"{ci:>18}{a['attempts']:>10}  {models}{flag}")

    # THE HEADLINE. D is printed above because it is what the ceiling run reported, but it
    # divides by a near-zero denominator and swung 4.90 -> 2.92 between a 20-scenario and a
    # 69-scenario sample. The paired count below divides by nothing and cannot be carried by
    # one loud scenario, so it is the number to read.
    any_st = any("sign_test" in v for v in p["conditions"].values())
    if any_st:
        print("\n--- PER-SCENARIO PAIRED TEST (the statistic to trust) ---")
        print("  Per scenario, does the RIGHT rubric outscore the WRONG one on the SAME "
              "responses?")
        print(f"  {'condition':<10}{'wins':>6}{'losses':>8}{'ties':>6}{'win share':>12}"
              f"{'p':>12}   vs bar {SIGN_BAR:.0%}")
        for name in CONDITIONS:
            c = p["conditions"].get(name)
            if not c or "sign_test" not in c:
                continue
            st = c["sign_test"]
            if st.get("unavailable"):
                print(f"  {name:<10}  -- {st['unavailable']}")
                continue
            v = ("CONFIRMS" if st["win_share"] >= SIGN_BAR and st["p_value"] < 0.05
                 else "not confirmed")
            print(f"  {name:<10}{st['wins']:>6}{st['losses']:>8}{st['ties']:>6}"
                  f"{st['win_share']:>11.1%}{st['p_value']:>12.2g}   {v}")
            # If nearly everything ties at zero, the decided scenarios are a small
            # unrepresentative residue and the win share says nothing about the corpus.
            if st["ties"] >= st["decided"]:
                print("    ! TIES >= DECIDED -- most scenarios score identically (usually "
                      "zero) on\n      both sides, so this run is uninformative however the "
                      "rest fall.")

    # A condition whose unrelated arm scores exactly 0 has D = inf. At full scale that is a
    # real perfect separation; at smoke scale it is just too few attempts. Flag it rather
    # than letting a degenerate divide-by-zero read as the strongest possible result.
    degen = [k for k, v in p["conditions"].items() if v["w_unrelated"] <= 0]
    if degen:
        print(f"\n  ! DEGENERATE (W unrelated = 0, D undefined): {', '.join(degen)}."
              "\n    Real only if the unrelated arm has enough attempts; at smoke scale it "
              "is not.")

    base = p["conditions"].get("blind", {})
    if base:
        print(f"\n  blind (control) D = {base['D']:.2f}")
    # THE PRE-REGISTRATION WAS MIS-SPECIFIED, AND THIS SAYS SO RATHER THAN MOVING IT.
    # D >= 2.0 was imported from the ceiling's _T_INSTRUMENT gate, which was calibrated on
    # the ceiling's own ASYMMETRIC arms. Under this trial's symmetric design the CONTROL
    # already clears it, so the bar cannot separate treatment from control here and a
    # printed "PASS" below means nothing about the hypothesis. The bar is left exactly as
    # registered -- rewriting it after seeing the result is how a finding gets tuned into
    # existence -- and the comparison that does carry the hypothesis is treatment vs
    # control, reported underneath.
    if base and base.get("D", 0) >= D_PASS:
        print("\n  ! PRE-REGISTRATION DEFECT: the CONTROL arm clears the pre-registered\n"
              f"    D >= {D_PASS} bar on its own. That bar was inherited from the ceiling's\n"
              "    asymmetric arms and does not discriminate under this design. The bar is\n"
              "    NOT being moved; read treatment-vs-control below instead.")
    situated = {k: v for k, v in p["conditions"].items() if k != "blind"}
    if not situated:
        return
    bname, bv = max(situated.items(), key=lambda kv: kv[1]["D"])
    print(f"  best situated     = {bname} at D = {bv['D']:.2f}")
    if base:
        delta = bv["D"] - base["D"]
        print(f"\n  TREATMENT vs CONTROL (the hypothesis): {bname} {bv['D']:.2f} "
              f"vs blind {base['D']:.2f}  =  {delta:+.2f}")
        if bv["ci_lo"] > base["ci_hi"]:
            print("  => situating the grader IMPROVES discrimination (CIs separated).")
        else:
            print("  => NOT ESTABLISHED. The CIs overlap, so no situational field is shown\n"
                  "     to improve discrimination. Grader blindness is not the binding\n"
                  "     constraint on this measurement.")
    if bv["D"] >= D_PASS:
        print(f"\n  (pre-registered bar, reported as registered: {bname} D >= {D_PASS}.)")
    else:
        print(f"\n  (pre-registered bar, reported as registered: nothing reaches D >= {D_PASS}.)")
    # Pre-registered as the uncertainty check, not the bar -- reported alongside, never
    # substituted for the bar after the fact.
    if bv["ci_lo"] == bv["ci_lo"]:
        print(f"  CI check: {bname}'s 95% CI lower bound is {bv['ci_lo']:.2f} "
              f"({'clears' if bv['ci_lo'] >= D_PASS else 'does NOT clear'} {D_PASS})")
    if base and base.get("ci_hi") == base.get("ci_hi") and bv["ci_lo"] == bv["ci_lo"]:
        sep = ("separated" if bv["ci_lo"] > base["ci_hi"]
               else "OVERLAPPING -- the move over blind is not established")
        print(f"  CI vs blind: {sep}")


def main() -> None:
    a = _args()
    out = OUT if not a.tag else OUT.with_name(f"grader_inputs_trial_{a.tag}.json")
    ckpt = CKPT if not a.tag else CKPT.with_name(f"grader_inputs_trial_{a.tag}_ckpt.json")
    if a.load:
        report(json.loads(out.read_text(encoding="utf-8-sig")))
        return
    conds = ({c: CONDITIONS[c] for c in a.conditions.split(",")} if a.conditions
             else dict(CONDITIONS))

    from config import load_config
    from ego_trap import milestone_scoring
    from shared.scenario_vectors import scenario_text
    from shared.tuning import load_tuning
    from calibration.score_naren_ceiling import derange
    from preprocessing import embedder
    import psycopg

    cfg = load_config()
    n_scen = 3 if a.smoke else a.sample
    per_s = 1 if a.smoke else a.per_scenario
    if a.smoke:
        print("SMOKE -- 3 scenarios x 1 response. Path test only, numbers NOT interpretable.\n")

    url = cfg.database_url + ("&" if "?" in cfg.database_url else "?") + "hostaddr=18.138.49.39"
    with psycopg.connect(url, autocommit=True, connect_timeout=20) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT s.scenario_key, s.business_description, s.keyphrases, r.milestones "
                "FROM public.scenarios s JOIN public.rubrics r ON r.scenario_id = s.scenario_id "
                "WHERE s.is_coachable AND jsonb_array_length(r.milestones) > 0")
            scen = {k: {"business_description": bd or "", "keyphrases": kp or [],
                        "milestones": ms} for k, bd, kp, ms in cur.fetchall()}
            cur.execute(
                "SELECT p.scenario_key, p.pair_id, p.trigger_text, p.response_text, "
                "c.filename, p.call_id "
                "FROM public.kb_pairs p JOIN public.calls c ON c.call_id = p.call_id "
                # F4: NO LENGTH FILTER. This query defines primary_calls, and Layer C's real
                # clause pool filters on scenario_key alone -- a call whose only primary
                # contribution had a short trigger IS leaked and must not be called clean.
                "WHERE p.scenario_key = ANY(%s)", (list(scen),))
            pool: dict[str, list[dict]] = defaultdict(list)
            primary_calls: dict[str, set] = defaultdict(set)
            for k, pid, trg, rsp, fn, cid in cur.fetchall():
                pool[k].append({"pair_id": pid, "trigger_text": trg,
                                "response_text": rsp, "call_filename": fn, "call_id": cid})
                primary_calls[k].add(cid)
            # THE LEAKAGE-CLEAN POPULATION, i.e. score_naren_ceiling's A3 stratum: rows that
            # carry this scenario as a SECONDARY label while their PRIMARY key is another
            # scenario, and whose CALL contributed no primary pair here. Those responses
            # cannot have entered this scenario's Layer C clause pool, so the rubric was not
            # written from them. Scoring THIS population against both its own rubric and a
            # partner's is the arm CLAUDE.md records as never built ("B3") -- the only
            # comparison that is leakage-clean AND population-symmetric at once.
            clean: dict[str, list[dict]] = defaultdict(list)
            if a.holdout:
                cur.execute(
                    "SELECT p.scenario_keys, p.pair_id, p.trigger_text, p.response_text, "
                    "c.filename, p.call_id, p.scenario_key "
                    "FROM public.kb_pairs p JOIN public.calls c ON c.call_id = p.call_id "
                    "WHERE p.scenario_keys && %s AND length(trim(p.trigger_text)) > 20 "
                    "AND length(trim(p.response_text)) > 20", (list(scen),))
                for sks, pid, trg, rsp, fn, cid, pk in cur.fetchall():
                    for k in (sks or []):
                        if k in scen and k != pk and cid not in primary_calls[k]:
                            clean[k].append({"pair_id": pid, "trigger_text": trg,
                                             "response_text": rsp, "call_filename": fn,
                                             "call_id": cid})
    print(f"{len(scen)} coachable scenarios with rubrics; "
          f"{sum(len(v) for v in pool.values())} usable pairs")

    src = clean if a.holdout else pool
    if a.holdout:
        print(f"HOLDOUT: leakage-clean stratum has {sum(len(v) for v in src.values())} rows "
              f"across {sum(1 for v in src.values() if v)} scenarios")
    keys = sorted(k for k in scen if len(src.get(k, [])) >= per_s)
    rng = random.Random(a.seed)
    sample_keys = stratified_sample(keys, n_scen, rng)
    n_post = sum(1 for k in sample_keys if k.startswith("client_"))
    print(f"sampled {len(sample_keys)} scenarios: {n_post} posture / "
          f"{len(sample_keys)-n_post} subject-matter")
    if n_post == 0:
        print("  ! WARNING: no posture scenario in the sample -- the two populations behave\n"
              "    differently and a subject-matter-only result must not be generalised.")

    # Partner mapping. Threshold is layer_a.merge_cosine_threshold, an already-calibrated
    # knob, so no new tuning key -- and the vectors are bge, the space it was calibrated in.
    vecs = embedder.embed_document_matrix([scenario_text(scen[k]) for k in sample_keys])
    vecs = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)
    partner, method = derange(sample_keys, vecs @ vecs.T,
                              load_tuning().layer_a.merge_cosine_threshold,
                              random.Random(a.seed))
    if partner is None:
        raise SystemExit(f"no valid partner mapping: {method}")
    print(f"partner mapping: {method}")

    items = []
    for k in sample_keys:
        for row in rng.sample(src[k], min(per_s, len(src[k]))):
            pk = partner[k]
            # The benchmark travels with the RUBRIC, never the response's own scenario --
            # otherwise the unrelated arm would differ from matched in two ways, not one.
            for kind, rk in (("matched", k), ("unrelated", pk)):
                bench = [r for r in pool[rk] if r["call_filename"] != row["call_filename"]]
                items.append({
                    "item_id": f"{row['pair_id']}_{kind}", "kind": kind,
                    "source_scenario": k, "scenario_key": rk,
                    "rubric": {"milestones": scen[rk]["milestones"]},
                    "client_utterance": row["trigger_text"],
                    "csm_response_text": row["response_text"],
                    "benchmark_response": "\n\n".join(
                        r["response_text"] for r in bench[:2]),
                })
    # F9: SEPARATE THE ARMS INTO DIFFERENT REQUESTS. items was built matched-then-unrelated
    # per response and batch_size is even, so both arms of every response landed in ONE
    # prompt -- the grader saw the same response twice, against two rubrics, side by side,
    # and could contrast them. Production never does that, so it inflates D. Ordering by kind
    # first guarantees a matched item and its unrelated twin are never in the same batch.
    items.sort(key=lambda it: (it["kind"], it["item_id"]))
    n_resp = len(items) // 2
    print(f"{n_resp} responses -> {len(items)} items per condition "
          f"({len(items)*len(conds)} scorings, "
          f"~{-(-len(items)//a.batch_size)*len(CONDITIONS)} calls)\n")

    chat = _gateway_chat(a.model) if a.gateway else None
    if a.gateway:
        print(f'[transport] Joveo gateway, model {a.model}')
    done: dict[str, list] = {}
    if ckpt.exists() and not a.fresh:
        ck = json.loads(ckpt.read_text(encoding="utf-8-sig"))
        if ck.get("n_items") == len(items):
            done = ck["records"]
            print(f"[resume] {list(done)} already scored\n")

    for cname, fields in conds.items():
        if cname in done:
            continue
        recs = []
        batches = [items[i:i + a.batch_size] for i in range(0, len(items), a.batch_size)]
        print(f"[{cname}] {len(items)} items in {len(batches)} calls "
              f"(fields: {sorted(fields) or 'none -- production'})", flush=True)
        for bi, batch in enumerate(batches, 1):
            try:
                scored = milestone_scoring.score_milestones_batch(
                    batch, cfg, situated_fields=fields or None,
                    model=a.model, fallback_models=(), chat=chat)
            except Exception as e:                                   # noqa: BLE001
                print(f"  ! [{cname}] batch {bi}/{len(batches)} FAILED: {str(e)[:140]}",
                      flush=True)
                continue
            for it, results in zip(batch, scored):
                for r in results:
                    recs.append({"item_id": it["item_id"], "kind": it["kind"],
                                 "scenario_key": it["scenario_key"],
                                 "source_scenario": it["source_scenario"],
                                 "verdict": r.get("verdict"),
                                 "judged_by": r.get("scored_by")})
            print(f"  [{cname}] {bi}/{len(batches)}", flush=True)
        done[cname] = recs
        ckpt.write_text(json.dumps({"n_items": len(items), "records": done}, default=str),
                        encoding="utf-8")

    boot = np.random.default_rng(a.seed)
    payload = {"n_scenarios": len(sample_keys), "n_responses": n_resp,
               "n_items": len(items), "pin_model": a.model, "seed": a.seed,
               "smoke": bool(a.smoke), "d_pass": D_PASS,
               "partner_method": method, "sample_keys": sample_keys,
               "conditions": {}}
    for cname, recs in done.items():
        by_kind = defaultdict(list)
        per_item = defaultdict(list)
        for r in recs:
            by_kind[r["kind"]].append(r)
            per_item[(r["kind"], r["item_id"])].append(r)
        wm = item_w(by_kind["matched"])
        wu = item_w(by_kind["unrelated"])
        im = {k[1].rsplit("_", 1)[0]: item_w(v) for k, v in per_item.items()
              if k[0] == "matched"}
        iu = {k[1].rsplit("_", 1)[0]: item_w(v) for k, v in per_item.items()
              if k[0] == "unrelated"}
        # The CI resamples COUNTS, not the per-item W values above -- W has to be recomputed
        # from summed counts to stay the same (pooled) estimator as `D`. The per-item W maps
        # are still reported, because the sign test and the per-scenario detail read them.
        cm = {k[1].rsplit("_", 1)[0]: item_counts(v) for k, v in per_item.items()
              if k[0] == "matched"}
        cu = {k[1].rsplit("_", 1)[0]: item_counts(v) for k, v in per_item.items()
              if k[0] == "unrelated"}
        lo, hi = bootstrap_d(cm, cu, boot)
        payload["conditions"][cname] = {
            "w_matched": wm, "w_unrelated": wu,
            "D": (wm / wu) if wu > 0 else float("inf"),
            "ci_lo": lo, "ci_hi": hi, "ci_estimator": CI_ESTIMATOR,
            "attempts": len(recs),
            "models": dict(Counter(r["judged_by"] for r in recs)),
            "sign_test": sign_test(recs),
            "per_item_matched": im, "per_item_unrelated": iu,
        }
    out.write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    report(payload)
    print(f"\nwrote {out}")
    print("NOTHING was written to Postgres.")


if __name__ == "__main__":
    main()
