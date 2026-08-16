#!/usr/bin/env python3
"""LAYER B REDESIGN -- pure, testable pieces. No I/O, no CLI, no globals, no side effects.

Spec: docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md

This module holds the parts of the Layer B trial that can be tested without a corpus, a
database or an embedder: the account map, the primary metric, and the paired sign test.
`calibration/layer_bc_arms.py` is the runner that imports these; keeping them apart is what
lets `tests/test_layer_b_arms.py` cover the RULE against hand-built inputs rather than
against whatever the embedder happened to produce that day (precedent:
`tests/test_layer_b_assignment.py` and its orthogonal unit vectors).

*** WHY THE PRIMARY METRIC IS NOT A MILESTONE COUNT. *** Every arm in this trial pushes more
of Naren's response text into a scenario's clause pool, and milestone count is monotone in
pool size -- so it IS every arm's own objective function, which this repo's standing rule
disqualifies. It has been paid for once already: the junk placebo GAINED 13 milestones on
volume alone. No router, segmenter or admission rule in this trial can see a client account,
so account breadth is nobody's objective.

===========================================================================================
THE METRIC HAS BEEN WRONG THREE TIMES. EACH REVISION WAS KILLED BY AN AUDIT, BEFORE ANY ARM
RAN, AND EACH FAILURE IS PINNED BY A NAMED TEST. READ THIS BEFORE CHANGING ANYTHING HERE.
===========================================================================================

  rev 1  `>= 3 distinct accounts` per milestone.
         KILLED: the published `experiential_branding` case is 98% RTX over FOUR distinct
         accounts and PASSED; `tracking_pixels` is 95% Uber over FIVE and PASSED. A count
         measures PRESENCE; the defect is DOMINANCE. It was also saturated -- 91% of
         `base_1` AND 91% of the junk placebo cleared it, so it had collapsed back into the
         milestone count it was written to replace.
         -> replaced the count with inverse-Simpson `N_eff`.

  rev 2  `N_eff` per milestone.
         KILLED: `N_eff <= k`. A milestone backed by 3 calls can never exceed 3.0 while one
         backed by 30 can reach 30, so an arm that routes MORE calls into each milestone
         raises the ceiling MECHANICALLY. The volume objective leaked straight back in.
         -> divided by the expectation at the milestone's own k: `lift`.

  rev 3  `count of milestones with lift >= bar`, bar = the control's median lift.
         KILLED by three findings, and the first is the one that matters:

           (a) THE MEAN OF `lift` IS UNBIASED AT EVERY k, BUT A THRESHOLD COUNT OF IT IS
               NOT. Measured over 20k draws: `P(lift >= 1.0)` is 100% at k=1, 95.9% at k=2,
               69.3% at k=5, 39.1% at k=8, ~46% at k=40-60. So an arm that merely SUBSAMPLES
               each milestone's calls to 60% -- preserving the account mixture exactly, i.e.
               changing no content whatsoever -- won at p=4.8e-13. Rev 2 paid an arm for
               routing MORE calls; rev 3 paid it for routing FEWER.
           (b) `E[N_eff | k=1] = 1.0` and one call scores `N_eff = 1.0`, so a milestone from
               ONE call of ONE client -- the least transferable object that can exist --
               scored `lift` EXACTLY 1.0 and passed whenever the control median sat below 1.
           (c) `lift` is a discrete staircase at small k: 64 distinct values over a realistic
               171-milestone control, largest tie block 18 milestones (10.5% of the metric in
               one quantum), 130 of 171 on tied values. "~50% usable by construction" was
               false.

  rev 4  THIS ONE. The statistic moved from the MILESTONE to the CLUSTER, and the threshold
         is DELETED.

           * per cluster: the UNION of `support_call_files` over ALL its milestones;
           * `N_eff` over the accounted calls in that union;
           * `lift = N_eff / E[N_eff | k]`, k = the number of accounted calls in the union;
           * the per-cluster statistic IS that float. There is no bar, no `derive_bar`, no
             `usable_milestones`, no threshold count. The paired sign test compares the two
             arms' per-cluster `lift` directly.

         WHY THAT IS THE FIX RATHER THAN A PATCH. Finding (a) says the MEAN of lift is
         unbiased at every k and the THRESHOLD is what was k-dependent, so deleting the
         threshold removes (a), (b) and (c) BY CONSTRUCTION rather than tuning around them:
         (b) cannot arise because a one-call cluster is a float competing against other
         floats instead of a pass, and (c) cannot arise because the union of many milestones'
         calls is not a staircase. Moving to the union also moves k away from the worst
         region: measured on the live 26-cluster control, milestone k has a median of 7 while
         CLUSTER k has a median of 26 (range 2..114), and 39.1% -- the pass rate that made
         subsampling profitable -- was the figure at k=8.

         WHAT IS NOT FIXED, STATED PLAINLY, TWICE, BECAUSE BOTH ARE MEASURED.

           * `lift(k) -> 1.0` as `k -> 1` for ANY mixture, since `N_eff <= k` bounds both
             halves of the ratio. Shrinking k therefore still drags a cluster's lift toward
             1.0 -- upward for a cluster more concentrated than the corpus, downward for one
             more diverse. THE REV-3 ATTACK IS NOT DEAD IN PRINCIPLE, so it was re-run rather
             than argued about. On the live 26-cluster control, subsampling every milestone's
             calls to 60% over 20 independent runs:

                 rev 3's metric  wins 13-16 of 20 runs at alpha=0.05 (median p=0.013)
                 rev 4, uniform null      0-2 of 20 (median p=0.69), pooled 289-206
                 rev 4, weighted null     1 of 20, pooled 247-252, p=0.858 -- a clean null

             So the threshold was most of it and the composition-matched null is the rest:
             the residual drift survives a uniform null and does not survive the weighted one.
             Pinned by `test_the_rev3_subsample_attack_wins_on_rev3_and_not_on_rev4`.
             A successor metric must re-measure this, not assume it.

             It is NOT fixed in the worst case, and that is measured too: on synthetic
             clusters with DISJOINT milestones and concentration up to 90% -- neither of which
             the live corpus has, where milestones overlap ~2.2x and top-account share tops
             out at 0.50 -- the attack still gains. The fixture was left as it is rather than
             softened until it passed.
           * The union does NOT put every cluster in a comfortable k. 4 of the 25 scoreable
             control clusters sit at k <= 8 (k = 2, 6, 6, 8), where `lift` has only a handful
             of attainable values -- the k=2 cluster scores 1.020 purely because two calls
             from two accounts is what a 2-draw is expected to give. They are still scored,
             as floats, because a k floor would be a new threshold and a filter applied to
             one arm's population is the asymmetric-filtering error this repo re-learns every
             few months. `score_distribution` reports the k distribution alongside lift for
             exactly this reason: an arm that moves k has changed evidence VOLUME, which is
             its own objective, and F4's volume-matched placebo is what adjudicates that.

*** THE NULL IS COMPOSITION-MATCHED, NOT ONLY SIZE-MATCHED. *** A milestone's calls are calls
that contributed a surviving response clause, so a call that yields many pairs is far likelier
to appear than one that yields two. Rev 3 drew all 344 accounted calls uniformly, and the
audit measured the resulting `lift` bias GROWING with k (+0.7% at k=3, +8.7% at k=20, +12.8%
at k=40) using transcript bytes as the proxy. Same defect class as `null_test_taxonomy`'s R4
length confound.

`pairs_per_call` supplies the draw weights instead, and they MUST come from production's own
extraction -- see its docstring for why an arm-derived weight would let an arm move the
yardstick it is measured against. RE-MEASURED HERE WITH PAIRS RATHER THAN BYTES, AND THE
CORRECTION IS LARGER THAN THE AUDIT'S AND POINTS THE OTHER WAY: `E[N_eff|k]` falls 1.9% at
k=2, 13.0% at k=8, 27.9% at k=26 and 35.3% at k=114 against the uniform null, so the uniform
null was UNDER-stating lift, not over-stating it. Byte count and pair count disagree in
direction; pair count is the one on the causal path, since a cluster's calls are calls that
contributed a clause and clauses come from pairs.

The proxy was validated rather than assumed. Over the live control's 25 non-empty cluster
unions, a call's inclusion rate rises monotonically with its pair count across all seven bins
(0.000 / 0.013 / 0.046 / 0.080 / 0.102 / 0.128 / 0.176), `corr = 0.634`, and the 17 accounted
calls with ZERO production pairs appear in ZERO unions -- which is what makes dropping them
correct rather than convenient. The extreme-bin ratio a proportional weight implies (~17x) is
close to the observed inclusion ratio (13.8x), so the weighting is a little strong rather than
wrong. Note also that with the threshold deleted, the null's absolute CALIBRATION decides
nothing: both arms divide by the same table and the sign test reads the difference.
"""
from __future__ import annotations

import math
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, NamedTuple, Sequence

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

NAN = float("nan")

DEFAULT_TRIALS = 20_000
"""Monte-Carlo draws in the null table. Every k comes out of the same draws -- see
`_neff_means_by_prefix` -- so this is the cost of the WHOLE table, not the cost per k.

400 was rev 3's default and it was too few for a quantity that everything is DIVIDED BY: it
gives ~1.3% relative sd on `E[N_eff|k]`, produced **20 non-monotone steps** over k=1..80 on
the real account pool (`E[19]=11.864 > E[20]=11.794`, arithmetically impossible in the truth),
and moved the primary metric by +/-5 milestones purely on the table's seed.

20k is chosen for PRECISION, not for the monotonicity check -- the shared-permutation
estimator is monotone on the live pool from ~2,000 trials up. Measured at 20k: `E[26]` moves
0.37% across four table seeds, so a cluster's lift is stable to well under the width of the
observed lift distribution (live p25-p75 is 0.54-1.01). It costs 0.3s for the whole table,
which is why there is no reason to run it lower.
"""

_TRIAL_CHUNK = 2_000
"""Trials generated per numpy call. A CONSTANT, because the table must be reproducible: the
RNG stream is consumed in chunk-sized blocks, so changing this changes every number in the
table. It exists only to bound peak memory (chunk x pool doubles ~ 5.5 MB at n=344), not to
be tuned."""


# ---------------------------------------------------------------------------------------
# missing values -- one definition, duck-typed
# ---------------------------------------------------------------------------------------

def is_missing(v) -> bool:
    """NaN or None. Imported discipline, not a local convenience.

    `float('nan') >= x` is False, so an unscoreable cluster silently reads as "did not
    improve" and disappears into the tie pile. Every consumer of a possibly-missing value
    must therefore ask this explicitly.

    *** DUCK-TYPED, NOT `isinstance(v, float)`. *** `np.float64` subclasses `float` but
    `np.float32` does NOT, so an isinstance check silently calls a float32 NaN present and
    readmits exactly the row it was written to exclude. Rev 3's `compare_arms` used the
    isinstance form while `flag_proper_noun_clusters.is_missing` -- the function it was
    copied from -- carries that warning in its own docstring. This is a verbatim port of
    that one so the two cannot drift.
    """
    if v is None:
        return True
    try:
        return math.isnan(v)
    except TypeError:                       # not a number at all -- not a missing number
        return False


def quantile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile. THE ONLY quantile implementation in this module.

    Rev 3 shipped two. `derive_bar` interpolated; `_summary` took `s[len(s) // 2]`. On the
    same data they returned 3.0 and 2.5 -- while the docstring of the one that disagreed
    said it existed so the other "can be AUDITED rather than trusted". An audit instrument
    that computes its own subject a second way is not an audit.

    Matches `numpy.percentile`'s default `linear` method exactly; a test pins that, so a
    reader can reason about this in numpy's terms.

    RAISES on a missing value rather than dropping it. Dropping is usually right, but it is
    the CALLER who knows whether a NaN means "unscoreable" (drop, and report the count) or
    "a bug upstream" (stop). Making that decision here would hide both.
    """
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"quantile must be in [0, 1], got {q}")
    vals = list(values)
    if any(is_missing(v) for v in vals):
        raise ValueError("quantile received a missing value -- the caller must decide "
                         "whether to drop it (and report how many) or to stop")
    if not vals:
        return NAN
    vals.sort()
    if len(vals) == 1:
        return vals[0]
    pos = q * (len(vals) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


# ---------------------------------------------------------------------------------------
# accounts -- UNCHANGED from rev 3. The audit verified every function below as correct.
# ---------------------------------------------------------------------------------------

def collapse_sibling_domains(accounts: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Fold a subdomain into its parent when BOTH are observed in this corpus.

    `contractors.scale.com` and `scale.com` are one client. CLAUDE.md already records the
    consequence ("optimizing_cost_per_activation_and_worker_quality is 100% one account, not
    the 74% printed"), and neither `account_map` nor anything downstream collapses them.
    Leaving them split inflates the metric in the unsafe direction -- a cluster resting on
    Scale plus ONE other client would read as three clients.

    THE RULE IS DERIVED FROM THE DATA, NOT CURATED. `A` folds into `B` iff `A` ends with
    `.B` AND `B` is itself an observed account in this corpus. Adding transcripts re-derives
    it; a hand-maintained sibling list would be the "a threshold must never be a curated
    list" anti-pattern this repo forbids.

    A public-suffix approach was rejected: it needs a shipped suffix list (a curated list by
    another name, and a stale one) and it would wrongly fuse two unrelated clients who merely
    share a TLD. Requiring the parent to be PRESENT means the corpus itself supplies the
    evidence that the two are one organisation.

    Chains resolve in one step by taking the SHORTEST observed ancestor, so `a.b.c.com` folds
    straight to `c.com` when `c.com` is present, and the function is idempotent.

    Returns (rewritten map, {child domain: parent domain}) -- the merge log is returned
    rather than logged so a caller can print it and a test can assert on it.
    """
    doms = set(accounts.values())
    merges: dict[str, str] = {}
    for a in doms:
        ancestors = [b for b in doms if b != a and a.endswith("." + b)]
        if ancestors:
            merges[a] = min(ancestors, key=len)
    if not merges:
        return dict(accounts), {}
    return {k: merges.get(v, v) for k, v in accounts.items()}, merges


def load_account_map(recordings: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """call stem -> account domain, IMPORTED from the harness that already derives it.

    Not reimplemented. `calibration/flag_proper_noun_clusters.py::account_map` is the one
    definition of "which client is this call", it has produced published findings, and this
    repo's rule is to import measurement code rather than paraphrase it -- two scratchpad
    reimplementations of the transcript parse disagreed with the real thing by ~20%.

    *** RAISES ON AN EMPTY MAP, AND THAT GUARD IS THE POINT. *** `account_map` globs
    `*.speakers.json` and returns `({}, {})` for a missing or wrong directory, without an
    exception. Every account then resolves to nothing, every cluster scores NaN, every
    arm ties, and `sign_test` returns p=1.0 -- a broken join that reads as "the metric found
    no difference between the arms". Calibration scripts here are CWD-relative and must run
    from `Brain/`, and `--recordings` is free text on the runner, so this is the likely
    operational failure, not an exotic one.

    Returns (stem -> domain, stem -> why-missing, child -> parent merge log).
    """
    from calibration.flag_proper_noun_clusters import account_map

    acct, reason = account_map(recordings)
    if not acct:
        raise SystemExit(
            f"ABORT: no account resolved for ANY call under {recordings!r}. Either the path "
            f"is wrong (run calibration scripts from Brain/) or the .speakers.json sidecars "
            f"are missing. Continuing would score every cluster at zero accounts, which is "
            f"indistinguishable from 'the arms do not differ'.")
    acct, merges = collapse_sibling_domains(acct)
    return acct, reason, merges


def call_stem(call_filename: str) -> str:
    """`foo.txt` -> `foo`, matching the key `account_map` builds.

    `account_map` keys on `f.name[:-len(".speakers.json")]` for `foo.speakers.json`, i.e.
    `foo`; `layer_bc_arms.build_pairs` stamps `call_filename = path.name`, i.e. `foo.txt`;
    `v2/layer_c.build_clause_pool` carries that same value through to each milestone. Joining
    those directly would match NOTHING. Verified live: 343/343 account_map keys match a
    transcript stem, zero orphans in either direction.
    """
    return Path(call_filename).stem


def account_shares(call_filenames, accounts: dict[str, str]) -> tuple[Counter, int]:
    """(account -> distinct accounted calls, count of calls with no resolvable account).

    *** UNACCOUNTED CALLS CONTRIBUTE NOTHING, AND THE DIRECTION IS THE POINT. *** 12.7% of
    this corpus's calls carry no client email on their Avoma roster. Three options existed:

      pool as one shared account  -> asserts they are the SAME client: fabricates
                                     concentration, i.e. manufactures a failure.
      each as its own account     -> asserts they are DIFFERENT clients: fabricates breadth,
                                     i.e. manufactures a WIN. Breadth is the quantity being
                                     measured, so this is the unsafe direction.
      contribute nothing (this)   -> asserts neither. Can only ever make a cluster look
                                     LESS transferable than it is.

    Only the third cannot produce a false positive, which is what a pass/fail statistic needs.

    The unaccounted count is RETURNED, not discarded. An earlier version computed it and
    every caller threw it away, so a cluster suppressed by missing rosters was
    indistinguishable from one that is genuinely single-client.
    """
    stems = {call_stem(c) for c in call_filenames}
    doms: Counter = Counter()
    unaccounted = 0
    for s in stems:
        dom = accounts.get(s)
        if dom is None:
            unaccounted += 1
        else:
            doms[dom] += 1
    return doms, unaccounted


def effective_accounts(call_filenames, accounts: dict[str, str]) -> tuple[float, int, int]:
    """(N_eff, distinct accounts, unaccounted calls) for one set of calls.

    N_eff = 1 / sum(p_i^2), the inverse-Simpson diversity of the ACCOUNTED calls. It answers
    "how many clients is this evidence effectively spread over", which is the question a
    distinct count cannot answer: 98% one client plus three strays is 4 distinct accounts and
    N_eff 1.04.

    Bounds, both worth knowing when reading a report: N_eff is 1.0 when one account holds
    every call, and equals the distinct count exactly when the calls are evenly split. So
    `N_eff <= distinct` always, and the gap between them IS the dominance.

    *** RETURNS NaN, NOT 0.0, WHEN NO CALL HAS AN ACCOUNT. *** 0.0 would read as more
    concentrated than the most concentrated real cluster, i.e. it would silently rank an
    unmeasurable cluster as the worst one. NaN forces every consumer to decide explicitly,
    which is what `flag_proper_noun_clusters.concentration` already does for the same reason
    ("np.mean over one NaN returns NaN and poisons an entire summary row").
    """
    doms, unaccounted = account_shares(call_filenames, accounts)
    if not doms:
        return NAN, 0, unaccounted
    total = sum(doms.values())
    simpson = sum((n / total) ** 2 for n in doms.values())
    return 1.0 / simpson, len(doms), unaccounted


# ---------------------------------------------------------------------------------------
# the null -- size-matched AND composition-matched
# ---------------------------------------------------------------------------------------

def pairs_per_call(pairs: Iterable[dict]) -> dict[str, int]:
    """call stem -> number of trigger/response pairs extracted from that call.

    These are the DRAW WEIGHTS for the null. A cluster's calls are calls that contributed a
    surviving response clause, so a call yielding 40 pairs is far likelier to appear in a
    union than one yielding 2. Rev 3's null drew every accounted call uniformly and therefore
    over-represented near-empty transcripts -- seven of them can essentially never back a
    milestone -- which biased `lift` upward by an amount that GROWS with k (+0.7% at k=3,
    +8.7% at k=20, +12.8% at k=40, measured with transcript bytes as the proxy).

    *** THE WEIGHTS MUST BE COMPUTED ONCE, FROM PRODUCTION'S OWN EXTRACTION, AND REUSED
    UNCHANGED FOR EVERY ARM. *** This is the arm-independence rule that killed the routing
    ranking, applied to the null instead of to the objective. Every arm in this trial changes
    how many pairs a call yields -- that is what `A1`/`A4`/`S1` DO -- so weights derived from
    an arm's own pairs would let that arm move the yardstick it is measured against: an arm
    that concentrated its pairs on a few clients would also make those clients likelier in
    the null, cancelling its own effect. Build them from the `s0a0r0` control's `build_pairs`
    output and pass the SAME dict to every arm's `corpus_account_pool` call.

    Still a proxy, stated rather than buried: the exact weight would be "surviving clauses
    from this call in this scenario's pool", which is both arm-dependent and scenario-
    dependent, i.e. disqualified twice over. Pair count is the closest arm-independent
    quantity on the same causal path.
    """
    c: Counter = Counter()
    for p in pairs:
        c[call_stem(p["call_filename"])] += 1
    return dict(c)


class AccountPool(NamedTuple):
    """The universe the null draws from: one entry per DRAWABLE accounted call.

    `weights` is a parallel array, not a dict, because the sampler needs it aligned to
    `labels`. `n_zero_weight` is carried so a runner can print how many accounted calls were
    excluded for contributing no pair -- an unreported drop is how a pool silently stops
    being the population it claims to be.
    """
    labels: tuple[str, ...]
    weights: tuple[float, ...]
    n_zero_weight: int


def corpus_account_pool(accounts: dict[str, str],
                        weights: dict[str, float] | None = None) -> AccountPool:
    """One entry per ACCOUNTED CALL, in deterministic stem order, with its draw weight.

    Sorted by call stem rather than by dict order so the table below is reproducible across
    processes -- the same discipline that made Layer C Pass 1 an exact A/B once embeddings
    were cached.

    `weights=None` gives the UNIFORM null, which is rev 3's behaviour and is retained only
    because it is the right reference for a test that is about the sampler rather than about
    the composition. Real runs pass `pairs_per_call(control_pairs)`; see F7's arm-independence
    requirement there.

    *** A CALL WITH WEIGHT 0 IS REMOVED FROM THE POOL, NOT KEPT AT PROBABILITY 0. *** A call
    that contributed no pair cannot appear in any cluster's union, so it is not part of the
    population being modelled; leaving it in would only inflate the effective pool size for
    the `k >= n` exact branch. The count is returned so the drop is reportable.
    """
    labels: list[str] = []
    ws: list[float] = []
    zero = 0
    for stem in sorted(accounts):
        w = 1.0 if weights is None else float(weights.get(stem, 0.0))
        if w < 0:
            raise ValueError(f"negative draw weight {w} for call {stem!r}")
        if w == 0.0:
            zero += 1
            continue
        labels.append(accounts[stem])
        ws.append(w)
    if not labels:
        raise ValueError(
            "empty account pool -- no accounted call has a positive draw weight "
            f"({len(accounts)} accounted calls in, {zero} dropped for zero weight). If the "
            f"weights are non-empty, they are keyed on the call STEM: weights built from "
            f"`call_filename` (`foo.txt`) without `call_stem` match nothing at all.")
    return AccountPool(tuple(labels), tuple(ws), zero)


def _as_pool(pool) -> AccountPool:
    """Accept an `AccountPool` or a bare sequence of labels (uniform weights).

    The bare form exists so a test about the SAMPLER can be written without also asserting a
    weighting scheme; a real run always goes through `corpus_account_pool`.
    """
    if isinstance(pool, AccountPool):
        return pool
    labels = tuple(pool)
    if not labels:
        raise ValueError("empty account pool -- the null cannot be built")
    return AccountPool(labels, (1.0,) * len(labels), 0)


def _neff_means_by_prefix(pool: AccountPool, max_k: int, wanted: set[int],
                          trials: int, seed: int) -> dict[int, float]:
    """E[N_eff | k] for EVERY wanted k <= max_k, from one pass over weighted permutations.

    *** THE GUMBEL TOP-k TRICK, TAKEN TO ITS FULL SORT. *** Draw `log(w_i) + Gumbel_i` and
    keep the k largest: that is provably identical in distribution to sequential sampling
    with probability proportional to weight, WITHOUT replacement (Efraimidis-Spirakis /
    Gumbel top-k). Sorting all n keys instead of partitioning at one k gives the whole
    sequential sampling ORDER, so the length-k prefix of one permutation is a valid weighted
    k-sample for every k at once. Sampling is without replacement because a cluster's calls
    are distinct by construction.

    *** WHY NOT ONE `argpartition` PER k, SEEDED PER k -- MEASURED, NOT PREFERRED. *** That
    is the obvious implementation and it CANNOT SATISFY THE MONOTONICITY REQUIREMENT on this
    corpus. Independent seeds per k make the estimates independent, so the noise in
    `E[k+1] - E[k]` is `sqrt(2)` times the noise in either, while the true step above k~70 is
    smaller than that: measured on the live 344-call pool at 20,000 trials it produced
    **16 non-monotone steps over k=1..140** (`E[86]=20.4802 > E[87]=20.4575`), i.e. the
    mandated check would fire on a real run. Prefixes of ONE permutation are common random
    numbers across k -- the two estimates share every draw -- which collapses the noise in
    the DIFFERENCE while leaving each estimate unbiased. Same pool, same 20,000 trials, same
    k range: **0 non-monotone steps**, and 0.3s instead of 31.9s.

    Determinism is strictly stronger than per-k seeding, not weaker. The RNG is consumed only
    by `rng.gumbel(size=(chunk, n))`, whose shape depends on the POOL and the chunk constant
    and on nothing else -- so `E[k]` is byte-identical whether k was requested alone, with
    other ks, or in any order. Verified live: a table built to max_k=140 and one built to
    max_k=60 agree exactly on every shared k.

    The running sum of squares is updated in place -- adding one more call of an account
    already seen `c` times moves `sum(n_i^2)` by exactly `2c + 1` -- so the whole prefix walk
    is O(max_k) vectorised steps rather than a recount per k.
    """
    n = len(pool.labels)
    uniq = sorted(set(pool.labels))
    code_of = {lab: i for i, lab in enumerate(uniq)}
    codes = np.array([code_of[lab] for lab in pool.labels], dtype=np.int64)
    logw = np.log(np.asarray(pool.weights, dtype=np.float64))
    m = len(uniq)

    totals = np.zeros(max_k + 1, dtype=np.float64)
    rng = np.random.default_rng(seed)
    done = 0
    while done < trials:
        t = min(_TRIAL_CHUNK, trials - done)
        # ALWAYS the full (t, n) draw, never truncated to max_k: the stream must not depend
        # on which ks were asked for, or two arms could be scored against different tables.
        keys = logw + rng.gumbel(size=(t, n))
        perm = codes[np.argsort(-keys, axis=1)]
        counts = np.zeros((t, m), dtype=np.int64)
        sumsq = np.zeros(t, dtype=np.float64)
        rows = np.arange(t)
        for j in range(max_k):
            acct = perm[:, j]
            c = counts[rows, acct]
            sumsq += 2.0 * c + 1.0
            counts[rows, acct] = c + 1
            if (j + 1) in wanted:
                totals[j + 1] += (float(j + 1) ** 2 / sumsq).sum()
        done += t
    return {k: totals[k] / trials for k in sorted(wanted)}


def _verify_monotone(table: dict[int, float]) -> None:
    """`E[N_eff | k]` must not fall as k rises. Raise if it does.

    In the truth it is non-decreasing over the k range this metric uses, so a fall is
    Monte-Carlo noise in a quantity that everything downstream is DIVIDED BY. At rev 3's 400
    trials there were 20 such steps over k=1..80 on the real pool, which is why the default
    is now 20k -- and 20k alone was NOT enough (16 steps) until the estimator moved to shared
    permutations. This check is what makes both of those claims falsifiable rather than
    asserted; it is also what would catch a weights array silently misaligned to its labels.

    ONE MATHEMATICAL EXCEPTION, documented so a future reader does not hunt for a sampler
    bug: dropping a single item from a pool can RAISE its N_eff (pool {A,A,B} scores 1.8;
    {A,B} scores 2.0), so `E[N_eff|n-1]` can legitimately exceed the exact `N_eff(n)` at the
    very top of the range. The live cluster unions reach k=114 against a pool of 344, so that
    region is never touched; if a future corpus does touch it, this is the place to
    special-case, not the sampler.
    """
    ks = sorted(table)
    for a, b in zip(ks, ks[1:]):
        if table[b] < table[a]:
            raise ValueError(
                f"null table is NOT monotone in k: E[{a}]={table[a]:.6f} > E[{b}]={table[b]:.6f}. "
                f"E[N_eff|k] cannot fall as k rises, so this is Monte-Carlo noise in the "
                f"denominator of the primary metric. Raise `trials` (the default is "
                f"{DEFAULT_TRIALS}); do NOT relax this check.")


def expected_neff_table(pool, ks, trials: int = DEFAULT_TRIALS,
                        seed: int = 42) -> dict[int, float]:
    """k -> E[N_eff] for k calls drawn from the corpus's own account mix at its own weights.

    *** THIS IS WHAT REMOVED THE SIZE CONFOUND THAT KILLED REVISION 2. *** `N_eff <= k`, so a
    cluster backed by 20 calls can never exceed 20.0 while one backed by 120 can reach 120.
    An arm that puts MORE calls into each cluster therefore raises the N_eff ceiling
    mechanically -- the volume objective leaking back into the metric written to escape it.
    Dividing by the expectation at the cluster's OWN k removes that.

    It also prices in the corpus's real skew rather than punishing every cluster that touches
    the largest client: measured live, uber.com is 55 of the 344 accounted calls (16.0%), so a
    general move backed by 9 calls is EXPECTED to draw one or two Uber calls. Nine of nine is
    not. (The spec's "343 accounted calls" predates the roster repairs; it is 344 today, over
    111 accounts after the sibling collapse.)

    THE DRAW IS FROM THE WHOLE CORPUS, NOT FROM THE CLUSTER'S OWN CALLS, and the choice
    matters. A within-cluster null would ask "given that this cluster only involves two
    clients, is it concentrated?" -- and would score an account-bound cluster as perfectly
    fine, which is the exact defect being hunted. A corpus-level null is also arm-INDEPENDENT:
    a fixed reference every arm is measured against, so an arm cannot move the yardstick by
    changing what it routes.

    The table is byte-identical across processes and INDEPENDENT OF THE ORDER AND THE SET of
    ks it is asked for -- see `_neff_means_by_prefix` for the mechanism and for the measured
    reason it is not one seeded `argpartition` per k. Two arms scored against tables that
    differed at all would be scored against different yardsticks.

    Build it over the UNION of every arm's ks (`union_cluster_ks`). Rev 3 built it from the
    control alone and it `KeyError`s on a treatment: `rescued` carries 10 support-call values
    absent from `base_1`.

    `k > n` RAISES rather than clamping. It means a cluster's union contains more accounted
    calls than the pool has drawable entries, which can only happen if the draw weights
    excluded calls the arm actually routes -- a real inconsistency between the null's
    population and the scored one, and one that would silently flatter or punish that
    cluster. Stop and fix the weights.
    """
    if trials < 1:
        raise ValueError(f"trials must be >= 1, got {trials}")
    p = _as_pool(pool)
    n = len(p.labels)
    ints = sorted({int(x) for x in ks if int(x) > 0})
    if not ints:
        return {}
    if ints[-1] > n:
        raise ValueError(
            f"k={ints[-1]} exceeds the drawable pool size {n}. A cluster cannot contain more "
            f"accounted calls than the null can draw; {p.n_zero_weight} accounted call(s) "
            f"were dropped from the pool for zero draw weight, so check that the weights "
            f"come from an extraction that covers every call the arms route.")

    exact_full = None
    if ints[-1] == n:
        # Drawing the whole pool has no variance, so it is computed rather than sampled.
        c = Counter(p.labels)
        exact_full = 1.0 / sum((v / n) ** 2 for v in c.values())

    sampled = {k for k in ints if k < n}
    out: dict[int, float] = {}
    if sampled:
        out.update(_neff_means_by_prefix(p, max(sampled), sampled, trials, seed))
    if exact_full is not None:
        out[n] = exact_full
    _verify_monotone(out)
    return out


# ---------------------------------------------------------------------------------------
# from stored milestones to a cluster's call union
# ---------------------------------------------------------------------------------------

def milestone_calls(milestone: dict) -> list[str]:
    """The distinct call filenames behind one stored milestone.

    *** `support_call_files` DOES NOT EXIST IN ANY ARTIFACT WRITTEN BEFORE THIS TRIAL. ***
    `layer_bc_arms.pass1` computed `len(set(g["calls"]))` and dropped the list, so account
    breadth is NOT derivable from anything written before 2026-08-16; persisting it is part
    of build step 1 and the three published arms had to be re-run to obtain it.

    A milestone lacking the field RAISES rather than returning []. A silent empty list would
    shrink the cluster's union without shrinking its milestone count -- so a stale artifact
    would produce a clean-looking report over partial data.
    """
    files = milestone.get("support_call_files")
    if files is None:
        raise KeyError(
            "milestone has no `support_call_files`. It was written before this field "
            "existed, so account breadth CANNOT be computed from it -- re-run the arm "
            "rather than scoring it as empty.")
    return list(files)


def cluster_calls(rec: dict) -> list[str]:
    """The UNION of `support_call_files` over every milestone of one scenario record.

    *** THE UNION IS THE UNIT OF DECISION, AND THAT IS THE WHOLE OF REVISION 4. *** Scoring
    each milestone and then counting how many cleared a bar made the metric depend on
    milestone-level k, where `lift` is a coarse staircase (64 distinct values over 171
    milestones) and a threshold on it swings from 100% at k=1 to 39% at k=8. The union lifts
    the median k from 7 to 26 on the live control and makes the statistic a float rather than
    a count -- so it cannot be won by producing more of anything, which is the standing
    objection to every count in this pipeline.

    It also blunts the specific rev-3 attack: a call appearing in 3 of a cluster's milestones
    survives an independent 60% subsample of each with probability 1 - 0.4^3 = 0.936, so the
    union barely moves where the individual milestones move a lot.

    Sorted so the value is stable across runs; deduplicated because support is DISTINCT
    calls. A scenario with no milestones yields [] -- which scores NaN, i.e. unscoreable and
    reported, never 0.
    """
    seen: set[str] = set()
    for m in rec.get("milestones") or []:
        seen.update(milestone_calls(m))
    return sorted(seen)


# ---------------------------------------------------------------------------------------
# the primary statistic -- per cluster, a float, no bar
# ---------------------------------------------------------------------------------------

def cluster_lift(call_filenames, accounts: dict[str, str],
                 table: dict[int, float]) -> dict:
    """THE PRIMARY STATISTIC: a cluster's N_eff over its size-matched expectation.

    lift ~ 1.0  as diverse as a random draw of the same size from the corpus's own mix
    lift << 1.0 concentrated on fewer clients than chance would give
    lift > 1.0  spread wider than chance (possible: the corpus is skewed, so a cluster that
                avoids the large accounts scores above 1)

    *** THERE IS NO BAR. *** The returned `lift` IS the per-cluster score and the sign test
    compares two arms' floats directly. Revision 3 counted milestones whose lift cleared a
    derived bar, and `P(lift >= bar)` is violently k-dependent (100% at k=1, 39.1% at k=8)
    even though `E[lift]` is not -- so a pure subsampling arm won at p=4.8e-13. A threshold
    on an unbiased statistic is not an unbiased statistic.

    Returns every component, not just the ratio, because the ratio alone hides which half
    moved -- an arm can raise lift by reaching more accounts OR by shrinking k, and those are
    different findings. `top_share` rides along as the coarse diagnostic view of the same
    thing (spec 4.1: raw N_eff and top-account share are reported, never ranked on).

    NaN when the cluster has no accounted call. NOT 0.0: zero reads as more concentrated than
    the most concentrated real cluster, i.e. it would silently rank an unmeasurable cluster
    as the worst one.
    """
    doms, unaccounted = account_shares(call_filenames, accounts)
    k = sum(doms.values())
    if not doms:
        return {"lift": NAN, "neff": NAN, "expected": NAN, "k": 0, "distinct": 0,
                "unaccounted": unaccounted, "top_share": NAN}
    neff, distinct, _ = effective_accounts(call_filenames, accounts)
    exp = table.get(k)
    if exp is None:
        raise KeyError(
            f"no null expectation for k={k}. Build the table over the UNION of every arm's "
            f"ks (`union_cluster_ks`) -- a table built from the control alone KeyErrors on a "
            f"treatment, which is how a run dies 40 minutes in.")
    return {"lift": neff / exp if exp else NAN, "neff": neff, "expected": exp,
            "k": k, "distinct": distinct, "unaccounted": unaccounted,
            # same expression as `top_account_share`, which takes a milestone dict rather
            # than a call list; a test pins the two to agree on identical input.
            "top_share": doms.most_common(1)[0][1] / k}


def cluster_ks(per_scenario: dict, accounts: dict[str, str]) -> set[int]:
    """Every accounted-call count the null table must cover for ONE arm.

    *** k IS THE ACCOUNTED-CALL COUNT, NOT `support_calls` SUMMED. *** N_eff is computed over
    accounted calls only, so the null must draw that many. Using a raw support count would
    compare a cluster's diversity against the expectation for a LARGER sample, and every
    cluster with unaccounted calls would score an artificially low lift -- an error
    proportional to roster coverage, which is exactly the asymmetry `unaccounted_rate` exists
    to surface.

    Rows without a `cluster_id` are INCLUDED even though `per_cluster_stats` drops them: a
    table with a k nothing uses costs one Monte-Carlo batch, a table missing a k raises.
    """
    ks: set[int] = set()
    for rec in per_scenario.values():
        doms, _ = account_shares(cluster_calls(rec), accounts)
        n = sum(doms.values())
        if n:
            ks.add(n)
    return ks


def union_cluster_ks(arms: Iterable[dict], accounts: dict[str, str]) -> set[int]:
    """The ks of EVERY arm, so one table scores all of them.

    Rev 3 built the table from the control alone and it raises on a treatment -- `rescued`
    carries 10 support-call values `base_1` never produces. Two tables would be worse than
    the crash: each arm would then be measured against a yardstick fitted to itself.
    """
    out: set[int] = set()
    for arm in arms:
        out |= cluster_ks(arm, accounts)
    return out


def per_cluster_stats(per_scenario: dict, accounts: dict[str, str],
                      table: dict[int, float]) -> dict[str, dict]:
    """cluster_id -> the row the sign test is run over.

    `lift` is the ONLY ranking statistic. `neff` rides along as the RAW, size-confounded view
    (`N_eff <= k`) so that spec F12's requirement -- report a disagreement between the
    corrected and raw views rather than smoothing it over -- is checkable by running
    `compare_arms(..., field="neff")`. F12 was written against rev 3's `mean_lift`, which no
    longer exists: at cluster level there is one value per cluster, so a count-independent
    companion to a count is not needed and the surviving companion is the raw view.

    Both are NaN on exactly the same clusters, by construction -- both are NaN iff the union
    has no accounted call. That matters: rev 3's `usable` was an int that could never be NaN
    while its `mean_lift` could, so `compare_arms` silently compared its two fields over
    DIFFERENT cluster populations (an all-unscoreable cluster scored 0 on one and was
    excluded from the other). A test pins the agreement.

    KEYED ON `cluster_id`, NEVER `scenario_key`. Gemma invents a fresh name for the same
    cluster every adjudication run (`stakeholder_role_identification` vs
    `stakeholder_role_mapping` are one cluster renamed), so a name join would report the
    entire taxonomy as changed.
    """
    out: dict[str, dict] = {}
    for rec in per_scenario.values():
        cid = rec.get("cluster_id")
        if not cid:
            continue
        if cid in out:
            raise ValueError(
                f"duplicate cluster_id {cid!r} within one arm -- the join key is not unique, "
                f"so a paired comparison against it would be meaningless")
        calls = cluster_calls(rec)
        row = cluster_lift(calls, accounts, table)
        row["n_milestones"] = len(rec.get("milestones") or [])
        row["n_calls"] = len({call_stem(c) for c in calls})
        out[cid] = row
    return out


# ---------------------------------------------------------------------------------------
# the paired test -- UNCHANGED from rev 3 except for the NaN check
# ---------------------------------------------------------------------------------------

def sign_test(up: int, down: int) -> float:
    """Two-sided exact binomial p for `up` increases against `down` decreases.

    Exact rather than normal-approximated because n here is the number of SHARED CLUSTERS --
    26 to 38 -- where the approximation is poor exactly in the tail the verdict is read from.
    `math.comb` rather than scipy: it is six lines, and this module must import cleanly in a
    cache-only run. Audited byte-identical to `scipy.stats.binomtest(up, up+down, 0.5)` over
    the whole 0..39 x 0..39 grid.

    Ties contribute nothing -- that is the definition of the sign test.

    Anchors: `rescue_centroid` +8/-0 -> 0.0078, published.
    """
    if up < 0 or down < 0:
        raise ValueError(f"counts must be non-negative, got up={up} down={down}")
    n = up + down
    if n == 0:
        return 1.0
    k = min(up, down)
    tail = sum(math.comb(n, i) for i in range(k + 1))
    return min(1.0, 2.0 * tail / (2 ** n))


def compare_arms(control: dict[str, dict], arm: dict[str, dict],
                 field: str = "lift") -> dict:
    """Paired comparison of two arms' per-cluster statistics on ONE field.

    *** REPORTS THE DIRECTION OF FLIPS, NEVER A FLIP RATE. *** A rate discards direction, and
    this repo has published an unreadable adjudication A/B for exactly that reason: the noise
    floor's flips were symmetric (12 one way, 10 the other, net +2) while the treatment's
    were asymmetric (12 vs 6, net +6), and a rate made them look identical.

    `only_control` / `only_arm` are counted separately and never imputed as zero. A cluster
    present in one arm and absent from the other cannot be paired, and scoring an absence as
    a decrease would attribute a taxonomy fact to Layer B.

    Missing-valued clusters are excluded and counted as `unscoreable_pairs`, never treated as
    0.0 -- 0.0 would rank an unmeasurable cluster below every real one. The check is
    `is_missing`, DUCK-TYPED: rev 3 used `isinstance(x, float) and math.isnan(x)`, and
    `np.float32` is not a `float` instance, so a float32 NaN arriving from any numpy-touching
    caller would have been readmitted as a real score.

    `field` defaults to the primary statistic. Running it a second time with `field="neff"`
    is the F12 companion check; both fields are missing on exactly the same clusters, so the
    two comparisons cover the same population -- which rev 3's `usable`/`mean_lift` pair did
    not.
    """
    shared = sorted(set(control) & set(arm))
    up = down = tie = unscoreable = 0
    deltas = []
    for c in shared:
        a, b = control[c][field], arm[c][field]
        if is_missing(a) or is_missing(b):
            unscoreable += 1
            continue
        deltas.append(b - a)
        if b > a:
            up += 1
        elif b < a:
            down += 1
        else:
            tie += 1
    return {
        "field": field,
        "n_shared": len(shared),
        "only_control": len(set(control) - set(arm)),
        "only_arm": len(set(arm) - set(control)),
        "unscoreable_pairs": unscoreable,
        "up": up, "down": down, "tie": tie,
        "net": sum(deltas),
        "p": sign_test(up, down),
    }


def multiplicity_note(n_arms: int, alpha: float = 0.05) -> dict:
    """How many of `n_arms` are expected to clear `alpha` by chance alone.

    With ~13 arms read at p < 0.05 the chance that AT LEAST ONE passes spuriously is ~49%.
    Reported next to the observed count so a single winner among many arms is read for what
    it is. The precedent is `flag_proper_noun_clusters.multiplicity_note`, which exists for
    this and is cited in CLAUDE.md.

    This is a REPORTING aid, not a correction: Bonferroni at 13 arms moves the bar to
    p < 0.0038, which on ~26 clusters needs ~10 clusters flipping unanimously against the 8
    that gave `rescue_centroid` its published result -- i.e. it would hide a real, moderate
    effect. Stating the expected-by-chance count lets a reader weigh that themselves rather
    than having it decided by a correction they cannot see.
    """
    if n_arms < 0:
        raise ValueError(f"n_arms must be non-negative, got {n_arms}")
    return {
        "n_arms": n_arms,
        "alpha": alpha,
        "expected_false_passes": n_arms * alpha,
        "p_at_least_one": 1.0 - (1.0 - alpha) ** n_arms,
        "bonferroni_alpha": (alpha / n_arms) if n_arms else alpha,
    }


# ---------------------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------------------

def _bucket(v: float, edges) -> str:
    if v < edges[0]:
        return f"<{edges[0]}"
    for lo, hi in zip(edges, edges[1:]):
        if lo <= v < hi:
            return f"{lo}-{hi}"
    return f">={edges[-1]}"


def _summary(vals: list[float], edges) -> dict:
    """Histogram plus quantiles, over the values that HAVE one.

    Missing values are dropped and COUNTED (`n_missing`), the `mean_scoreable` pattern from
    `flag_proper_noun_clusters`: `np.mean` over one NaN returns NaN and poisons an entire
    summary row. Quantiles go through `quantile`, the module's single implementation -- rev 3
    had `median = s[len(s)//2]` here disagreeing with its own bar's interpolated quantile
    (3.0 vs 2.5) while claiming to be the audit of it.
    """
    ok = [v for v in vals if not is_missing(v)]
    ok.sort()
    return {"hist": dict(Counter(_bucket(v, edges) for v in ok)),
            "n": len(ok), "n_missing": len(vals) - len(ok),
            "min": (ok[0] if ok else NAN), "max": (ok[-1] if ok else NAN),
            "p25": quantile(ok, 0.25) if ok else NAN,
            "median": quantile(ok, 0.5) if ok else NAN,
            "p75": quantile(ok, 0.75) if ok else NAN,
            "mean": (sum(ok) / len(ok)) if ok else NAN}


def score_distribution(per_scenario: dict, accounts: dict[str, str],
                       table: dict[int, float],
                       lift_edges=(0.25, 0.5, 0.75, 1.0, 1.25),
                       neff_edges=(1.0, 1.5, 2.0, 3.0, 5.0, 8.0),
                       k_edges=(5, 10, 20, 40, 80)) -> dict:
    """Per-CLUSTER distributions of lift, raw N_eff and k, plus the unscoreable count.

    All three, because the ratio hides which half moved and because k is what rev 3's
    threshold turned out to be measuring. An arm whose k distribution shifts has changed the
    evidence volume, which is its own objective -- so a lift gain accompanied by a large k
    shift needs the volume-matched placebo (F4) before it means anything.

    Reported so the METRIC can be audited rather than trusted. Rev 1's bar was saturated (91%
    of milestones over it, including 91% of the junk placebo's) and nothing in the report
    could have shown that; rev 3's staircase was invisible for the same reason. A lift
    distribution piled into one bucket says the statistic is not discriminating, whatever the
    p value says.
    """
    lifts, neffs, ks = [], [], []
    unscoreable = 0
    for rec in per_scenario.values():
        r = cluster_lift(cluster_calls(rec), accounts, table)
        if is_missing(r["lift"]):
            unscoreable += 1
            continue
        lifts.append(r["lift"])
        neffs.append(r["neff"])
        ks.append(float(r["k"]))
    return {"lift": _summary(lifts, lift_edges),
            "neff": _summary(neffs, neff_edges),
            "k": _summary(ks, k_edges),
            "unscoreable": unscoreable}


def top_account_share(milestone: dict, accounts: dict[str, str]) -> float:
    """Share of a milestone's ACCOUNTED calls belonging to its single largest account.

    The complement of N_eff and a coarser view of the same thing: N_eff answers "over how
    many clients", this answers "how much does one dominate". Reported as a diagnostic; it
    ranks nothing.

    Returns NaN when no call has an account -- NOT 0.0. 0.0 reads as maximally diverse, the
    flattering direction, and would bias any per-arm mean toward "less concentrated than
    reality". `flag_proper_noun_clusters.concentration` returns NaN for the same reason.

    NOTE, because the names collide: this has a DISTINCT-CALLS denominator, while the
    published "RTX 98% / Banfield 100%" figures are PER-TURN shares. Same name, different
    statistic; they are not comparable.
    """
    doms, _ = account_shares(milestone_calls(milestone), accounts)
    if not doms:
        return NAN
    return doms.most_common(1)[0][1] / sum(doms.values())


def pool_coverage(per_scenario: dict, accounts: dict[str, str],
                  weights: dict[str, float] | None) -> dict:
    """How many of THIS arm's cluster-union calls the null is actually able to draw.

    The composition-matched null takes its weights from production's extraction, so a call
    production got no pair from has weight 0 and leaves the pool. An arm that recovers pairs
    from such a call -- which is precisely what `A1` and `A4` DO -- can then reach an account
    the null does not price in, and its `lift` numerator would count evidence the denominator
    treats as impossible. That is a one-directional flattery, and it is invisible in the lift
    values themselves.

    So it is measured per arm and reported. On the live control it is zero by construction:
    all 17 accounted calls with no production pair appear in ZERO cluster unions -- which is
    also the empirical evidence that dropping them is right rather than convenient. If a
    treatment arm makes this non-zero, say so next to its result.
    """
    used: set[str] = set()
    for rec in per_scenario.values():
        used.update(call_stem(c) for c in cluster_calls(rec))
    accounted = {s for s in used if s in accounts}
    if weights is None:
        outside: set[str] = set()
    else:
        outside = {s for s in accounted if float(weights.get(s, 0.0)) <= 0.0}
    return {
        "union_calls": len(used),
        "accounted": len(accounted),
        "zero_weight_in_use": len(outside),
        "share_drawable": ((len(accounted) - len(outside)) / len(accounted))
                          if accounted else NAN,
    }


def unaccounted_rate(per_scenario: dict, accounts: dict[str, str]) -> dict:
    """Corpus-level exposure to missing rosters, surfaced instead of silently absorbed.

    Every score is suppressed in proportion to how many of its calls have no account. If that
    rate differs materially between two arms, the comparison is measuring roster coverage
    rather than routing -- the asymmetric-filtering error this repo has a standing rule
    against. It cannot be seen from the lift values alone.
    """
    total_calls = accounted = 0
    ms = unscoreable = 0
    for rec in per_scenario.values():
        for m in rec.get("milestones") or []:
            doms, unacc = account_shares(milestone_calls(m), accounts)
            n_acc = sum(doms.values())
            total_calls += n_acc + unacc
            accounted += n_acc
            ms += 1
            if not doms:
                unscoreable += 1
    return {
        "milestones": ms,
        "unscoreable_milestones": unscoreable,
        "calls": total_calls,
        "accounted_calls": accounted,
        "accounted_frac": (accounted / total_calls) if total_calls else NAN,
    }
