#!/usr/bin/env python3
"""Do the turn-mode coachable scenarios beat a size-matched random null? (free, read-only)

Spec: docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md

THE QUESTION. The finding that started this whole effort is that two thirds of the LIVE
taxonomy is statistically indistinguishable from a random pile of client turns -- 21 of 68
rankable scenarios beat their own size-matched null, and just 1 of 24 posture scenarios did.
The new turn-mode taxonomy has never faced that bar. Everything measured about it so far
(content-free share, blind judges, coherence, account concentration, the Layer D comparison)
is upstream of it.

*** THE SYMMETRY RULE, AND WHY THE OBVIOUS VERSION OF THIS SCRIPT IS WRONG. ***
The obvious run -- score each new scenario on its own HDBSCAN cluster members -- is rigged.
Cluster membership is CHOSEN to be coherent, so it would beat any null by construction, while
production's scenarios are populated by MATCHING (layer_b assigns a turn to its best scenario).
Comparing the two would measure "clustering vs matching", not "taxonomy vs taxonomy" -- the
asymmetric-comparison bug this codebase has hit five times and grown a separate defence for
each time.

The spec pre-registered against this: it retires the 21/68 = 31% figure as a CROSS-UNIT
ARTIFACT and forbids treating it as the bar to beat, because it scored clause-formed
scenarios using turn vectors.

So both arms here are built identically and only the taxonomy differs:
  same turn pool          the 23,949 Naren CLIENT turns (production entry point, Avoma roster)
  same embedder           gemini-embedding-2 @ 3072, cached -- neither side gets its native one
  same assignment         top-1 cosine against `business_description + keyphrases`, which is
                          what layer_b's primary scenario_key and Layer D's rubric lookup both
                          resolve to
  same nulls              all three, computed for every entry (see below)
  same bar                lift >= 0.05, and rankable means >= 8 assigned turns

*** THE NULL WAS SIZE-MATCHED BUT NOT COMPOSITION-MATCHED (audit F12, fixed 2026-08-15). ***
A scenario's members are turns SELECTED for having a coachable best match, and those run far
longer than the pool at large -- 69.1 words (production) and 80.9 (turn mode) against 45.7.
The size-matched null drew from the whole pool, which is maximally dispersed in turn SHAPE, so
an entry merely homogeneous in length beat it without being a situation at all. Worse for a
COMPARISON: the two arms accept different fractions (51.5% vs 39.8%) of different composition,
so one shared null was not equally hard for both, and it favoured turn mode.

All three nulls are reported per entry so the correction is visible rather than silently
replacing the old number:
  whole      size-matched over the whole pool          -- WHAT SHIPPED, kept for continuity
  eligible   drawn from this arm's own accepted turns  -- F12 read literally
  length     matched to each entry's own word-count profile -- THE GATE

`length` is the one pre-registered in OPEN_PROBLEMS.md. It REDUCES the confound it was aimed
at; it does NOT remove it. Measured corr(lift, mean words) per arm, whole -> length:
production +0.651 -> +0.371, turn mode +0.638 -> +0.254, control +0.737 -> -0.016. Quoting
only the control's -0.016 (as an earlier version of this docstring did) is cherry-picking the
one arm where the fix looks best, and the control's figure is a CANCELLATION rather than a
removal -- partialling out n leaves +0.152 there. Treat a length-matched result as
"length-adjusted", never as "length-free".

`eligible` is REPORTED, NOT COMPARABLE ARM-TO-ARM. It draws from exactly the union of the
entries being scored, so a draw of n from N re-picks ~n^2/N of the entry's OWN members --
13.9% for turn mode against 7.1% for production. That self-contamination differs by arm,
which is the one thing a cross-arm column must not do.

THE POSITIVE CONTROL DECIDES WHETHER ANY OF THIS IS READABLE. `new_cluster` is HDBSCAN's own
membership, chosen to be coherent. If a harder null collapses IT too, the null is simply too
hard and proves nothing -- a metric that can never pass is as useless as one that cannot fail.
It clears 74% / 21% / 32% under the three nulls while both matched arms fall to 0-4%, so the
collapse is a property of the taxonomies, not of the instrument.

ARM 3 IS REPORTED AND IS NOT THE ANSWER. The rigged cluster-membership version is computed
too, explicitly labelled an upper bound, so the gap between "HDBSCAN's own clusters" and
"what matching actually gathers" is visible rather than hidden. Printing it is the honest
move; quoting it as the result would not be.

WHAT THIS CANNOT ANSWER. Beating a random null means a scenario is more than a random pile of
turns. It does not mean the scenario produces a usable rubric, and nothing downstream of Layer
A is exercised here.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/null_test_taxonomy.py
    ..\\.venv\\Scripts\\python.exe calibration/null_test_taxonomy.py --load
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OUT = ARTIFACTS_DIR / "null_test_taxonomy.json"
MIN_MEMBERS = 8          # scenario_coherence.py's MIN_TRIGGERS -- below this no stable centroid
LIFT_BAR = 0.05          # trial_pool_unit.NULL_LIFT_BAR -- REPORTED, no longer the gate
SEED = 42

# z IS REPORTED AND IS DELIBERATELY NOT THE GATE. Re-deriving the bar as "position within
# the entry's own null distribution" -- the shape flag_proper_noun_clusters.py uses -- was
# tried and REFUTED. The null's spread collapses as the group grows (sd 0.0072 at n=10 to
# 0.0008 at n=870, ~1/sqrt(n)), so z = lift/sd inflates with SIZE: measured z of 1.82, 3.44,
# 14.80, 18.56, 32.20 across the size range, and a trivial +0.012 excess scores z~15. Two
# entries with identical lift score differently purely because one is bigger. That is a
# significance test, and at n in the hundreds everything is significant; the question here
# needs an EFFECT SIZE. (The approximation itself is fine -- validated 8/8 against a real
# 400-draw empirical p99 -- it is the statistic that is wrong for the job.)
Z_BAR = 2.326            # reported only, for "is the excess distinguishable from noise"

# THE REFERENCE, derived from data rather than chosen, and SIZE-CONDITIONAL.
# `lift >= 0.05` is an effect size -- the right SHAPE of statistic -- but the constant was
# inherited from the size-matched null and never re-derived. Rather than invent a second
# constant, compare against the positive control: HDBSCAN's own clusters are groups known
# to be coherent, so the lift THEY achieve is what a real group looks like on this scale.
#
# *** WHY IT MUST BE CONDITIONAL ON SIZE. *** Every statistic here moves with n, in BOTH
# directions: z RISES with n (the null's spread shrinks ~1/sqrt(n)) while lift FALLS with n
# (bigger groups are more diverse) -- measured corr(lift, n) = -0.510 inside the control.
# So NO single threshold of either kind is fair across entries spanning n=8 to n=1,326.
# A single control median was tried and was itself confounded: the control's entries are
# far smaller than the arms it judges (median n 47 vs 172 and 94), so it graded big groups
# against a bar set by small ones and understated both arms by 16-17 points.
# Each entry is therefore compared against the median lift of the CONTROL_NEIGHBOURS
# control entries nearest it in log-size.
CONTROL_ARM = "new_cluster_upper_bound"
CONTROL_NEIGHBOURS = 7


def size_matched_reference(n: int, control_rows: list[dict], k: int = CONTROL_NEIGHBOURS,
                           field: str = "lift_length") -> float:
    """Median lift of the k control entries closest to `n` in log-size."""
    usable = [r for r in control_rows if r.get("rankable") and r.get("n", 0) > 0
              and r.get(field) == r.get(field)]
    if not usable:
        return float("nan")
    near = sorted(usable, key=lambda r: abs(np.log(r["n"]) - np.log(max(n, 1))))[:k]
    return float(np.median([r[field] for r in near]))
# Half-width of the length-matched draw's window, as a SHARE of the pool -- never an
# absolute count. A fixed 500 reads fine against 23,949 turns (2%) and silently spans the
# ENTIRE pool of a smaller one, turning the length-matched null back into the whole-pool
# null with nothing printed to say so. Caught by tests/test_null_test_taxonomy.py.
LENGTH_BAND_FRACTION = 0.02

# The three nulls, weakest first. `whole` is what shipped; `length` is what the gate reads.
NULLS = ("whole", "eligible", "length")
GATE_NULL = "length"


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--load", action="store_true", help="re-report the artifact, free")
    p.add_argument("--force", action="store_true",
                   help="allow overwriting an artifact built from MORE turns than this run")
    return p.parse_args()


def verify_join(clusters: list[dict], adj_rows: list[dict]) -> None:
    """POSITION-VERIFIED JOIN. Raises unless every position agrees on n_items/calls/keywords.

    The adjudication artifact stores only `i`, so membership can be re-attached ONLY by
    reproducing the identical ordering -- verify that rather than assume it. Checking the
    COUNT alone (`len(clusters) != len(adj)`) is blind exactly where misalignment happens:
    `clusters.sort(key=n, reverse=True)` is a STABLE sort, so ties keep input order, and on
    the live artifact **200 of 245 rows share n_items with another row, 23 of the 38
    coachable ones included** -- three coachable pairs are directly swappable. A swap
    attributes one cluster's turns to another scenario's name and every downstream number
    becomes fiction, silently.

    n_items alone leaves 200 rows ambiguous and n_items+calls still leaves 76; all three
    together leave **0**. Mirrors flag_proper_noun_clusters.py, which has always done this.
    """
    if len(clusters) != len(adj_rows):
        raise SystemExit(f"JOIN FAILED: {len(clusters)} clusters vs {len(adj_rows)} rows. "
                         "Clustering did not reproduce; do not trust any downstream number.")
    bad = [i for i, (c, r) in enumerate(zip(clusters, adj_rows))
           if c["n"] != r["n_items"] or c["calls"] != r["calls"]
           or c["keywords"] != r["keywords"]]
    if bad:
        raise SystemExit(f"JOIN FAILED at {len(bad)} positions (first {bad[:5]}): "
                         "n_items/calls/keywords disagree with the adjudication artifact.")
    print(f"[join] verified position-for-position on n_items, calls and keywords "
          f"({len(clusters)}/{len(clusters)})")


def fold_merged_clusters(clusters: list[dict], adj_rows: list[dict]
                         ) -> tuple[dict[str, list[int]], int, int]:
    """Control membership per scenario: its own cluster PLUS every cluster merged into it.

    `kind` is four-valued (`scenario` / `merged` / `mechanics` / `logistics`) and `merged`
    means RETAINED -- the cluster is folded into an existing scenario. Testing
    `kind == "scenario"` treats a retained duplicate as a discard, which is the exact
    collapse that produced the phantom "Gemma over-sinks 14.6% of the corpus" finding.
    Returns (membership, folded, orphaned); orphans are COUNTED so a merge target that is
    not a kept scenario can never vanish silently.
    """
    cl_idx: dict[str, list[int]] = {}
    for c, r in zip(clusters, adj_rows):
        if r["kind"] == "scenario":
            cl_idx.setdefault(r["scenario_key"], []).extend(c["idxs"])
    folded = orphaned = 0
    for c, r in zip(clusters, adj_rows):
        if r["kind"] != "merged":
            continue
        if r.get("merge_into_key") in cl_idx:
            cl_idx[r["merge_into_key"]].extend(c["idxs"])
            folded += 1
        else:
            orphaned += 1
    return cl_idx, folded, orphaned


def length_band(n_members: int, n_pool: int) -> int:
    """Half-width of the length window, in ranks. Scales with the pool AND with the group.

    The `n_members` term is not cosmetic: a window narrower than the group cannot supply it
    without replacement, and duplicate vectors would inflate the null's coherence -- making
    the null harder for exactly the largest entries. The cost is that matching is necessarily
    looser for a big entry, which is why the realized band is recorded per row rather than
    assumed.
    """
    return max(int(round(LENGTH_BAND_FRACTION * n_pool)), n_members)


def length_matched_null(vecs: np.ndarray, member_idx: list[int], order_by_wc: list[int],
                        rank_of: dict[int, int], rng: random.Random,
                        band: int | None = None, draws: int | None = None,
                        stats: dict | None = None) -> float:
    """Mean coherence of random subsets drawn to match this entry's own LENGTH profile.

    One replacement per member, sampled from the turns of most similar word count (a
    +/-`band` window in the pool's word-count ranking). The size-matched null is drawn
    from the whole pool, which is maximally dispersed in turn SHAPE -- so any entry that
    is merely homogeneous in length beats it without being a situation at all. That is
    not a hypothetical: `client_direct_denial` is 98% content-free at a mean of 3.7 words
    and cleared the size-matched null at rank 2 of 82.
    """
    from calibration.trial_pool_unit import coherence, NULL_DRAWS

    draws = NULL_DRAWS if draws is None else draws
    n_pool = len(order_by_wc)
    band = length_band(len(member_idx), n_pool) if band is None else band
    vals, drawn_ranks = [], []
    for _ in range(draws):
        chosen: list[int] = []
        seen: set[int] = set()
        for m in member_idx:
            r = rank_of[m]
            lo, hi = max(0, r - band), min(n_pool, r + band)
            for _attempt in range(30):          # without replacement, bounded retry
                cand = order_by_wc[rng.randrange(lo, hi)]
                if cand not in seen:
                    seen.add(cand)
                    chosen.append(cand)
                    break
        if len(chosen) >= 2:
            vals.append(coherence(vecs[chosen]))
            drawn_ranks.extend(rank_of[c] for c in chosen)
    if stats is not None:
        stats["band"] = band
        stats["band_share_of_pool"] = band / n_pool
        stats["mean_drawn_rank"] = float(np.mean(drawn_ranks)) if drawn_ranks else float("nan")
        stats["mean_member_rank"] = float(np.mean([rank_of[m] for m in member_idx]))
        stats["draws"] = len(vals)
        # SD of the null's OWN distribution -- what the z gate is measured against. A fixed
        # lift bar cannot be right for every entry because this spread varies with n.
        stats["sd"] = float(np.std(vals, ddof=1)) if len(vals) > 1 else float("nan")
        stats["max"] = float(np.max(vals)) if vals else float("nan")
        # NEAREST-RANK p99, never np.percentile: linear interpolation turns a single +inf
        # into NaN (the R3a defect). Meaningful only at high `draws` -- at the default 20
        # it IS the maximum, which is why the gate reads z and this is the cross-check.
        if vals:
            sv = sorted(vals)
            stats["p99"] = float(sv[min(len(sv) - 1, int(np.ceil(0.99 * len(sv))) - 1)])
    return float(np.mean(vals)) if vals else float("nan")


def score_population(vecs: np.ndarray, label: str, keys: list[str],
                     member_idx: dict[str, list[int]], order_by_wc: list[int],
                     rank_of: dict[int, int], word_count: np.ndarray):
    """Coherence vs THREE nulls for every entry, using the SHARED implementations.

    `whole`     size-matched, drawn from the whole pool -- what shipped, kept so the
                correction is visible rather than silently replacing the old number.
    `eligible`  drawn from the population this arm's members can actually come from
                (turns whose top-1 is coachable). Addresses the audit's F12 literally:
                the arms accept different FRACTIONS of the pool, so a shared null is not
                equally hard for both.
    `length`    drawn matched to each entry's own word-count profile. THE GATE.

    Each null gets its OWN rng, consumed in `keys` order, so `whole` reproduces the
    pre-fix artifact bit-for-bit and the other two cannot perturb it.
    """
    from calibration.trial_pool_unit import coherence, size_matched_null

    eligible = sorted({i for v in member_idx.values() for i in v})
    pool_eligible = vecs[eligible]
    rngs = {n: random.Random(SEED) for n in NULLS}

    rows = []
    for k in keys:
        idx = member_idx.get(k, [])
        row = {"key": k, "n": len(idx), "coh": float("nan"), "rankable": False,
               "mean_words": float("nan")}
        if len(idx) < 2:
            for n in NULLS:
                row[f"null_{n}"] = row[f"lift_{n}"] = float("nan")
            rows.append(row)
            continue
        coh = coherence(vecs[idx])
        row.update({"coh": coh, "rankable": len(idx) >= MIN_MEMBERS,
                    "mean_words": float(word_count[idx].mean())})
        st: dict = {}
        row["null_whole"] = size_matched_null(vecs, len(idx), rngs["whole"])
        row["null_eligible"] = size_matched_null(pool_eligible, len(idx), rngs["eligible"])
        row["null_length"] = length_matched_null(vecs, idx, order_by_wc, rank_of,
                                                 rngs["length"], stats=st)
        row.update({f"length_{k}": v for k, v in st.items()})
        for n in NULLS:
            row[f"lift_{n}"] = coh - row[f"null_{n}"]
        sd = row.get("length_sd", float("nan"))
        row["z_length"] = (coh - row["null_length"]) / sd if sd and sd == sd and sd > 0 \
            else float("nan")
        row["exceeds_null_max"] = bool(coh > row.get("length_max", float("inf")))
        rows.append(row)

    rankable = [r for r in rows if r["rankable"]]
    out = {"rows": rows, "n_rankable": len(rankable), "n_eligible_turns": len(eligible),
           "mean_words_eligible": float(word_count[eligible].mean()) if eligible else float("nan")}
    print(f"\n  {label}: {len(rows)} coachable entries, {len(rankable)} rankable "
          f"(>= {MIN_MEMBERS} turns)")
    for n in NULLS:
        clears = [r for r in rankable if r[f"lift_{n}"] >= LIFT_BAR]
        out[f"n_clear_{n}"] = len(clears)
        out[f"share_{n}"] = len(clears) / len(rankable) if rankable else float("nan")
        if rankable:
            corr = float(np.corrcoef([r[f"lift_{n}"] for r in rankable],
                                     [r["mean_words"] for r in rankable])[0, 1])
            out[f"corr_lift_words_{n}"] = corr
            gate = "  <- GATE" if n == GATE_NULL else ""
            print(f"    null={n:<9} mean {np.mean([r[f'null_{n}'] for r in rankable]):.4f}"
                  f"  lift {np.mean([r[f'lift_{n}'] for r in rankable]):+.4f}"
                  f"  clear {len(clears)}/{len(rankable)} = "
                  f"{len(clears)/len(rankable)*100:.0f}%"
                  f"  corr(lift,words) {corr:+.2f}{gate}")
    # z: REPORTED, never gated on -- it scales with n (see the note beside Z_BAR).
    zc = [r for r in rankable if r["z_length"] == r["z_length"] and r["z_length"] >= Z_BAR]
    out["n_clear_z"] = len(zc)
    out["share_z"] = len(zc) / len(rankable) if rankable else float("nan")
    out["n_exceeds_null_max"] = sum(1 for r in rankable if r["exceeds_null_max"])
    # nanmean, not mean: one unmeasurable entry (zero-spread null) must not turn a whole
    # arm's printed mean into nan while n_clear_z correctly ignores it.
    out["mean_z"] = (float(np.nanmean([r["z_length"] for r in rankable]))
                     if rankable else float("nan"))
    out["n_z_unmeasurable"] = sum(1 for r in rankable if r["z_length"] != r["z_length"])
    lifts = [r[f"lift_{GATE_NULL}"] for r in rankable]
    out["median_lift"] = float(np.median(lifts)) if lifts else float("nan")
    if rankable:
        print(f"    z vs own null (NOT the gate -- inflates with n): "
              f"{len(zc)}/{len(rankable)} at z>={Z_BAR}, mean z {out['mean_z']:+.2f}")
    # `n_clear`/`share` keep the pre-fix names AND the pre-fix statistic, so the retracted
    # number stays directly comparable. The recommended headline is `share_ctrl`, added in
    # main() once the control arm exists.
    out["n_clear"], out["share"] = out[f"n_clear_{GATE_NULL}"], out[f"share_{GATE_NULL}"]
    return out


def report(p: dict) -> None:
    print("\n" + "=" * 96)
    print("RANDOM NULL -- BOTH TAXONOMIES, SAME POOL / EMBEDDER / RULE / NULLS")
    print("=" * 96)
    print(f"  pool: {p['n_turns']} Naren CLIENT turns   embedder: {p['embedder']}")
    print(f"  gate reads null={GATE_NULL!r}; `whole` is the pre-fix null, kept for continuity")

    arms = [("old_matched", "production"), ("new_matched", "turn mode"),
            ("new_cluster_upper_bound", "new_cluster RIGGED")]
    print(f"\n  LIFT >= {LIFT_BAR} -- REPORTED FOR CONTINUITY, NOT THE GATE (the bar was "
          f"calibrated\n  against the size-matched null and does not transfer to a harder one)")
    print(f"\n  {'arm':<22}{'rankable':>9}" + "".join(f"{'null=' + n:>18}" for n in NULLS))
    for key, pretty in arms:
        a = p.get(key)
        if not a:
            continue
        cells = ""
        for n in NULLS:
            cell = f"{a[f'n_clear_{n}']}/{a['n_rankable']} = {a[f'share_{n}']*100:.0f}%"
            cells += f"{cell:>18}"
        print(f"  {pretty:<22}{a['n_rankable']:>9}{cells}")

    if "control_neighbours" in p:
        print(f"\n  RECOMMENDED HEADLINE -- share reaching a SIZE-MATCHED control reference:"
              f"\n  each entry is compared against the median lift of the "
              f"{p['control_neighbours']} control entries nearest it\n  in log-size. lift "
              f"falls as n rises (corr -0.51 inside the control), so one flat reference "
              f"grades\n  big groups against a bar set by small ones. The control scored "
              f"under its own rule must\n  land near 50% -- it is the population the medians "
              f"come from.")
        print(f"  {'arm':<22}{'rankable':>9}{'reach ref':>14}{'median lift':>14}"
              f"{'median ref':>13}{'mean z':>9}")
        for key, pretty in arms:
            a = p.get(key)
            if not a or "share_ctrl" not in a:
                continue
            cell = f"{a['n_clear_ctrl']}/{a['n_rankable']} = {a['share_ctrl']*100:.0f}%"
            print(f"  {pretty:<22}{a['n_rankable']:>9}{cell:>14}"
                  f"{a['median_lift']:>+14.4f}{a.get('median_ref', float('nan')):>+13.4f}"
                  f"{a['mean_z']:>+9.2f}")
        print(f"\n  flat reference (the control's single median lift, "
              f"{p.get('control_ref_lift_flat', float('nan')):+.4f}) is retained in the "
              f"artifact\n  for continuity ONLY -- it understated both matched arms by 16-17 "
              f"points.")
        print(f"\n  z is shown ONLY to say the excess is not noise. It is NOT a gate: the "
              f"null's spread\n  collapses as a group grows (~1/sqrt(n)), so z rewards SIZE "
              f"-- identical lifts at\n  different n score wildly differently. Use lift.")
        print(f"\n  RESIDUAL CONFOUND -- corr(lift, mean words) under the gate null, by arm:"
              + "".join(f"  {pp}={p[k]['corr_lift_words_length']:+.2f}"
                        for k, pp in arms if k in p))
        print(f"  The length null REDUCES this, it does not remove it. Read a result as "
              f"length-adjusted.")
    for key, pretty in arms:
        a = p.get(key)
        if a and "corr_lift_words_whole" in a:
            print(f"  {pretty:<22}{'corr(lift,words)':>9}"
                  + "".join(f"{a[f'corr_lift_words_{n}']:>18.2f}" for n in NULLS))
    print(f"\n  new_cluster is HDBSCAN's OWN membership -- the positive control. It must stay "
          f"clearly\n  above the matched arms or the null is too hard and nothing may be "
          f"concluded from it.")

    for key, pretty in (("new_matched", "turn-mode"), ("old_matched", "production")):
        a = p.get(key)
        if not a:
            continue
        print(f"\n--- {pretty} coachable scenarios, by z against null={GATE_NULL} ---")
        print(f"  {'':4} {'z':>6} {'lift':>7}  {'coh':>5}  "
              + "  ".join(f"{'null=' + n:>11}" for n in NULLS)
              + f"  {'n':>5}  {'words':>5}  key")
        rows = sorted([r for r in a["rows"] if r["rankable"]],
                      key=lambda r: -(r["z_length"] if r["z_length"] == r["z_length"] else -9e9))
        for r in rows:
            mark = "PASS" if r["z_length"] >= Z_BAR else "    "
            print(f"  {mark} {r['z_length']:>6.2f} {r[f'lift_{GATE_NULL}']:+7.3f}  "
                  f"{r['coh']:.3f}  "
                  + "  ".join(f"{r[f'null_{n}']:>11.3f}" for n in NULLS)
                  + f"  {r['n']:>5}  {r['mean_words']:>5.0f}  {r['key'][:44]}")
        thin = [r for r in a["rows"] if not r["rankable"]]
        if thin:
            print(f"  too thin to rank ({len(thin)}): "
                  + ", ".join(f"{r['key'][:34]}(n={r['n']})" for r in thin))


def main() -> None:
    a = _args()
    if a.load:
        report(json.loads(OUT.read_text(encoding="utf-8-sig")))
        return

    from config import load_config
    from preprocessing.transcript_parser import parse_transcript, load_roster
    from v2.layer_a import build_client_pool
    from calibration.trial_pool_unit_gemini import embed_cached
    from calibration.validate_taxonomy_vs_layerd import load_old, load_new, match
    import psycopg

    cfg = load_config()

    # DB FIRST, CLOSED BEFORE ANY EMBEDDING. Holding a Neon connection across slow work is
    # the documented way this fails; validate_taxonomy_vs_layerd.py carries the same rule.
    url = cfg.database_url + ("&" if "?" in cfg.database_url else "?") + "hostaddr=18.138.49.39"
    with psycopg.connect(url, autocommit=True, connect_timeout=20) as conn:
        old = load_old(conn)
    new = load_new()
    print(f"OLD taxonomy: {len(old)} entries ({sum(t['coachable'] for t in old)} coachable)")
    print(f"NEW taxonomy: {len(new)} entries ({sum(t['coachable'] for t in new)} coachable)")

    turns = []
    for f in sorted(Path(a.recordings).glob("*.txt")):
        turns.extend(parse_transcript(str(f), cfg.joveo_speakers_lower,
                                      cfg.naren_name_lower, roster=load_roster(str(f))))
    texts, call_ids = build_client_pool(turns, unit="turn")
    print(f"{len(texts)} CLIENT turns over {len(set(call_ids))} calls")

    vecs = embed_cached(texts, workers=20)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    emb = lambda t: embed_cached(t, workers=20)

    # Word-count ranking, built ONCE: the length-matched null draws a replacement of
    # comparable length for every member, so it needs the pool ordered by word count and
    # each turn's rank in that order.
    word_count = np.array([len(t.split()) for t in texts])
    order_by_wc = [int(i) for i in np.argsort(word_count, kind="stable")]
    rank_of = {t: i for i, t in enumerate(order_by_wc)}

    # EVERY knob that changes what a number MEANS is recorded and printed. NULL_DRAWS in
    # particular determines length_sd / length_p99 and therefore every z, and it lives in
    # another module -- unrecorded, the z column is uninterpretable from the artifact alone.
    from calibration.trial_pool_unit import NULL_DRAWS
    payload = {"n_turns": len(texts), "embedder": "gemini-embedding-2@3072",
               "min_members": MIN_MEMBERS, "lift_bar": LIFT_BAR, "seed": SEED,
               "nulls": list(NULLS), "gate_null": GATE_NULL,
               "length_band_fraction": LENGTH_BAND_FRACTION,
               "mean_words_pool": float(word_count.mean()),
               "null_draws": NULL_DRAWS, "z_bar": Z_BAR,
               "recordings": a.recordings, "n_calls": len(set(call_ids))}

    for name, tax in (("old_matched", old), ("new_matched", new)):
        m = match(vecs, tax, emb)
        coach_keys = [t["key"] for t in tax if t["coachable"]]
        member_idx: dict[str, list[int]] = {}
        for i, b in enumerate(m["best"]):
            if m["accepted"][i]:
                member_idx.setdefault(m["keys"][b], []).append(i)
        assigned = sum(len(v) for v in member_idx.values())
        print(f"\n[{name}] {assigned}/{len(texts)} turns ({assigned/len(texts)*100:.1f}%) "
              f"matched a COACHABLE entry")
        payload[name] = score_population(vecs, name, coach_keys, member_idx,
                                         order_by_wc, rank_of, word_count)
        payload[name]["accepted_turns"] = assigned
        payload[name]["accepted_share"] = assigned / len(texts)

    # --- the rigged arm, computed on purpose so the inflation is visible ------------------
    from collections import defaultdict
    from shared import cluster_evidence
    from shared.tuning import load_tuning
    from v2.layer_a import fit_topic_model
    adj_name = "adjudicate_gemini_min16.json"
    adj_payload = json.loads((ARTIFACTS_DIR / adj_name).read_text(encoding="utf-8-sig"))
    adj = adj_payload["rows"]
    # The clustering knobs below are literals here but are RECORDED in the artifact being
    # joined against -- so assert rather than assume. A silent mismatch would re-cluster
    # the pool differently from the adjudication whose verdicts are about to be attached.
    for k, v in (("min_cluster_size", 16), ("merge", 0.97)):
        if adj_payload.get(k) is not None and adj_payload[k] != v:
            raise SystemExit(f"CONFIG MISMATCH: {adj_name} was built with {k}="
                             f"{adj_payload[k]}, this run uses {v}.")
    payload["control_source"] = adj_name
    payload["control_min_cluster_size"] = 16
    payload["control_merge"] = 0.97
    ta = load_tuning().layer_a
    total_calls = len(set(call_ids))
    print("\n[new_cluster] re-clustering for the rigged upper bound ...", flush=True)
    tm, topics = fit_topic_model(texts, vecs, min_cluster_size=16)
    topics = np.array(topics)
    members = defaultdict(list)
    for i, t in enumerate(topics):
        if t != -1:
            members[int(t)].append(i)
    raw_ids = sorted(members)
    cent = np.stack([cluster_evidence.support_stats(
        [call_ids[i] for i in members[t]], vecs[members[t]], total_calls).centroid
        for t in raw_ids])
    groups = cluster_evidence.merge_by_similarity(cent, 0.97)
    min_support = cluster_evidence.required_call_support(
        total_calls, ta.min_call_support_fraction, ta.min_call_support_floor)
    clusters = []
    for g in groups:
        tids = [raw_ids[x] for x in g]
        idxs = [i for t in tids for i in members[t]]
        st = cluster_evidence.support_stats([call_ids[i] for i in idxs], vecs[idxs],
                                            total_calls, texts=[texts[i] for i in idxs])
        if cluster_evidence.triage(st, min_support, ta.ubiquity_ceiling) == \
                cluster_evidence.INSUFFICIENT_EVIDENCE:
            continue
        lead = max(tids, key=lambda z: len(members[z]))
        clusters.append({"idxs": idxs, "n": st.n_items, "calls": st.distinct_calls,
                         "keywords": ", ".join(w for w, _ in tm.get_topic(lead)[:10])})
    clusters.sort(key=lambda c: c["n"], reverse=True)       # adjudication's own order
    verify_join(clusters, adj)

    # `kind` is FOUR-valued and `merged` means RETAINED -- the cluster is folded into an
    # existing scenario, not discarded (validate_taxonomy_vs_layerd.load_new says so, and
    # collapsing this enum to `kind == "scenario"` is what produced the phantom "Gemma
    # over-sinks 14.6% of the corpus" finding). Taking only the seed cluster gave a control
    # of 2,725 turns while the 69 merged clusters hold 2,434 more -- so the control was
    # PURER and SMALLER than the entity it stands for, which inflated the reference derived
    # from it and pushed both matched arms down.
    cl_idx, folded, orphaned = fold_merged_clusters(clusters, adj)
    print(f"[control] {len(cl_idx)} scenarios, {folded} merged clusters folded in, "
          f"{orphaned} orphaned (merge target not a kept scenario), "
          f"{sum(len(v) for v in cl_idx.values())} turns")
    payload["new_cluster_upper_bound"] = score_population(
        vecs, "new_cluster", list(cl_idx), cl_idx, order_by_wc, rank_of, word_count)

    # --- the data-derived reference, computed once the control exists ---------------------
    ctl_rows = payload[CONTROL_ARM]["rows"]
    payload["control_ref_lift_flat"] = payload[CONTROL_ARM]["median_lift"]   # reported only
    payload["control_neighbours"] = CONTROL_NEIGHBOURS
    for name in ("old_matched", "new_matched", CONTROL_ARM):
        rk = [r for r in payload[name]["rows"] if r["rankable"]]
        for r in rk:
            r["ref_lift"] = size_matched_reference(r["n"], ctl_rows)
            r["reaches_ref"] = bool(r[f"lift_{GATE_NULL}"] >= r["ref_lift"])
        payload[name]["n_clear_ctrl"] = sum(r["reaches_ref"] for r in rk)
        payload[name]["share_ctrl"] = (payload[name]["n_clear_ctrl"] / len(rk)
                                       if rk else float("nan"))
        # The control scored under its OWN rule must land near 50% -- it is the population
        # the medians come from. Materially off means the neighbourhood is too small.
        payload[name]["median_ref"] = (float(np.median([r["ref_lift"] for r in rk]))
                                       if rk else float("nan"))

    # A CHEAP RUN MUST NOT DESTROY AN EXPENSIVE ONE. `--recordings somewhere_small` writes
    # to the same fixed path, and `--load` then re-reports it as though it were the full
    # corpus. Refuse, rather than trust whoever runs it next to remember.
    if OUT.exists() and not a.force:
        prev = json.loads(OUT.read_text(encoding="utf-8-sig"))
        if prev.get("n_turns", 0) > len(texts):
            raise SystemExit(
                f"REFUSING TO OVERWRITE: {OUT.name} holds a {prev['n_turns']}-turn run "
                f"(recordings={prev.get('recordings', '?')}); this run has only "
                f"{len(texts)}. Re-run with --force if that is genuinely intended.")

    OUT.write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    report(payload)
    print(f"\nwrote {OUT}")
    print("Zero chat calls, zero embedding requests, zero Postgres writes.")


if __name__ == "__main__":
    main()
