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

*** WHY IT IS N_eff AND NOT A COUNT OF DISTINCT ACCOUNTS -- THIS METRIC WAS ALREADY WRONG
ONCE. *** Revision 1 of the spec gated on ">= 3 distinct accounts". An audit killed it
against the very cases it was written to catch:

    experiential_branding  (the published "RTX 98%" case)   -> 4 distinct accounts, PASSES
    tracking_pixels        (the published "Uber 95%" case)   -> 5 distinct accounts, PASSES

A count measures PRESENCE; the defect is DOMINANCE. A milestone that is 95% one client with
three stray calls elsewhere scored 3 and counted as transferable. Worse, the bar was
saturated -- simulating each milestone's own support_calls drawn at random put 91% of
base_1 AND 91% of the junk placebo over it, so the statistic collapsed back into the
milestone count it was meant to replace.

The replacement is the inverse-Simpson effective number of accounts:

    N_eff = 1 / sum(p_i^2),   p_i = share of the milestone's ACCOUNTED calls from account i

RTX at 98% over 4 accounts gives N_eff = 1.04 -- it collapses to one client, correctly. Four
balanced accounts give exactly 4.0. It is a standard diversity index, a property of the
data, and it needs no curated list.

Step 1 of the build order. Segmentation, admission predicates and the routers land in later
steps, each after the previous step's tests pass and its audit is clean.
"""
from __future__ import annotations

import math
import sys
from collections import Counter
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

NAN = float("nan")


# ---------------------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------------------

def collapse_sibling_domains(accounts: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Fold a subdomain into its parent when BOTH are observed in this corpus.

    `contractors.scale.com` and `scale.com` are one client. CLAUDE.md already records the
    consequence ("optimizing_cost_per_activation_and_worker_quality is 100% one account, not
    the 74% printed"), and neither `account_map` nor anything downstream collapses them. At
    a bar of 3 a milestone resting on Scale plus ONE other client would score 3 -- inflating
    the metric in the unsafe direction, the exact direction the unaccounted-calls rule was
    designed to avoid.

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
    exception. Every account then resolves to nothing, every milestone scores zero, every
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
            f"are missing. Continuing would score every milestone at zero accounts, which is "
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
      contribute nothing (this)   -> asserts neither. Can only ever make a milestone look
                                     LESS transferable than it is.

    Only the third cannot produce a false positive, which is what a pass/fail statistic needs.

    The unaccounted count is RETURNED, not discarded. An earlier version computed it and
    every caller threw it away, so a milestone suppressed by missing rosters was
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
    concentrated than the most concentrated real milestone, i.e. it would silently rank an
    unmeasurable milestone as the worst one. NaN forces every consumer to decide explicitly,
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
# per-milestone
# ---------------------------------------------------------------------------------------

def milestone_calls(milestone: dict) -> list[str]:
    """The distinct call filenames behind one stored milestone.

    *** `support_call_files` DOES NOT EXIST IN ANY ARTIFACT WRITTEN BEFORE THIS TRIAL. ***
    `layer_bc_arms.pass1` computed `len(set(g["calls"]))` and dropped the list, so account
    breadth is NOT derivable from anything currently on disk; persisting it is part of build
    step 1 and the three published arms must be re-run to obtain it.

    A milestone lacking the field RAISES rather than returning []. A silent empty list would
    become NaN, be excluded from every mean as "unscoreable", and quietly shrink the
    denominator -- so a stale artifact would produce a clean-looking report over no data.
    """
    files = milestone.get("support_call_files")
    if files is None:
        raise KeyError(
            "milestone has no `support_call_files`. It was written before this field "
            "existed, so account breadth CANNOT be computed from it -- re-run the arm "
            "rather than scoring it as empty.")
    return list(files)


def milestone_neff(milestone: dict, accounts: dict[str, str]) -> tuple[float, int, int]:
    """(N_eff, distinct accounts, unaccounted calls) for one stored milestone."""
    return effective_accounts(milestone_calls(milestone), accounts)


def usable_milestones(milestones, accounts: dict[str, str],
                      bar: float) -> tuple[int, int, int]:
    """(usable, scoreable, unscoreable) at an N_eff bar.

    A milestone is USABLE when `N_eff >= bar`. Unscoreable milestones -- no accounted call at
    all -- are counted separately and are NEVER usable; they are reported so an arm cannot
    win by producing milestones the metric cannot see.

    *** THE SUPPORT GATE IS NOT RE-APPLIED HERE, DELIBERATELY. *** Every milestone reaching
    an artifact has already cleared it: `pass1` keeps only clusters with
    `support_calls >= required`. Testing it again always passes, and reporting it as a second
    criterion would present ONE observation as two corroborating ones -- the defect
    `distribution_stats` already carries a docstring about.
    """
    usable = scoreable = unscoreable = 0
    for m in milestones:
        neff, _, _ = milestone_neff(m, accounts)
        if math.isnan(neff):
            unscoreable += 1
            continue
        scoreable += 1
        if neff >= bar:
            usable += 1
    return usable, scoreable, unscoreable


def derive_bar(per_scenario: dict, accounts: dict[str, str],
               quantile: float = 0.5) -> float:
    """The N_eff bar, DERIVED from the control arm and frozen before any treatment runs.

    *** WHY THE BAR IS A RULE AND NOT A NUMBER. *** Revision 1 guessed 3 and the audit showed
    91% of milestones cleared it -- including 91% of the junk placebo's -- so the statistic
    was saturated and reproduced the milestone count it replaced. A guessed bar cannot be
    known to bite until the distribution is measured, and measuring it AFTER seeing treatment
    results is how a threshold gets tuned into a finding.

    The pre-registered rule is: the bar is the `quantile` of the CONTROL arm's scoreable
    N_eff distribution, computed on the control alone, frozen, then applied unchanged to
    every arm. At the default median, ~50% of control milestones are usable by construction
    -- maximally non-saturated, and maximally sensitive in both directions.

    This is legitimate because the control is a property of the corpus, not of any treatment:
    no treatment arm has run when it is computed. It would NOT be legitimate to re-derive it
    per arm, which is why callers pass a float from here on.
    """
    vals = []
    for rec in per_scenario.values():
        for m in rec.get("milestones") or []:
            neff, _, _ = milestone_neff(m, accounts)
            if not math.isnan(neff):
                vals.append(neff)
    if not vals:
        raise ValueError(
            "no scoreable milestone in the control arm -- the bar cannot be derived, and a "
            "default would be a guess of exactly the kind that already failed once")
    vals.sort()
    if len(vals) == 1:
        return vals[0]
    pos = quantile * (len(vals) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


# ---------------------------------------------------------------------------------------
# per-cluster
# ---------------------------------------------------------------------------------------

def per_cluster_stats(per_scenario: dict, accounts: dict[str, str],
                      bar: float) -> dict[str, dict]:
    """cluster_id -> {usable, mean_neff, n_milestones, scoreable, unscoreable}.

    TWO STATISTICS, deliberately, because they fail in opposite directions:

      `usable`    a COUNT, so it still rises with pool size. The volume-matched placebo (F4)
                  is what controls that.
      `mean_neff` count-INDEPENDENT: adding a junk single-client milestone LOWERS it. It
                  cannot be won by producing more of anything, but it can be won by producing
                  fewer and better, which is not the product win either.

    Neither alone is sufficient, which is why the spec requires them to agree in direction.

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
        ms = rec.get("milestones") or []
        neffs = [milestone_neff(m, accounts)[0] for m in ms]
        good = [v for v in neffs if not math.isnan(v)]
        usable, scoreable, unscoreable = usable_milestones(ms, accounts, bar)
        out[cid] = {
            "usable": usable,
            "mean_neff": (sum(good) / len(good)) if good else NAN,
            "n_milestones": len(ms),
            "scoreable": scoreable,
            "unscoreable": unscoreable,
        }
    return out


# ---------------------------------------------------------------------------------------
# the paired test
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
                 field: str = "usable") -> dict:
    """Paired comparison of two arms' per-cluster statistics on ONE field.

    *** REPORTS THE DIRECTION OF FLIPS, NEVER A FLIP RATE. *** A rate discards direction, and
    this repo has published an unreadable adjudication A/B for exactly that reason: the noise
    floor's flips were symmetric (12 one way, 10 the other, net +2) while the treatment's
    were asymmetric (12 vs 6, net +6), and a rate made them look identical.

    `only_control` / `only_arm` are counted separately and never imputed as zero. A cluster
    present in one arm and absent from the other cannot be paired, and scoring an absence as
    a decrease would attribute a taxonomy fact to Layer B.

    NaN-valued clusters (no scoreable milestone) are excluded from the comparison and counted
    as `unscoreable_pairs`, never treated as 0.0 -- 0.0 is the worst possible score and would
    rank an unmeasurable cluster below every real one.
    """
    shared = sorted(set(control) & set(arm))
    up = down = tie = unscoreable = 0
    deltas = []
    for c in shared:
        a, b = control[c][field], arm[c][field]
        if (isinstance(a, float) and math.isnan(a)) or \
           (isinstance(b, float) and math.isnan(b)):
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

def neff_distribution(per_scenario: dict, accounts: dict[str, str],
                      edges=(1.0, 1.5, 2.0, 3.0, 5.0, 8.0)) -> dict:
    """Histogram of N_eff across one arm, plus the unscoreable count.

    Reported so the derived bar can be AUDITED rather than trusted. Revision 1's bar of 3 was
    saturated and nobody could see it from the report; this makes that visible by
    construction.
    """
    hist: Counter = Counter()
    unscoreable = 0
    vals = []
    for rec in per_scenario.values():
        for m in rec.get("milestones") or []:
            neff, _, _ = milestone_neff(m, accounts)
            if math.isnan(neff):
                unscoreable += 1
                continue
            vals.append(neff)
            label = f"<{edges[0]}"
            for lo, hi in zip(edges, edges[1:]):
                if lo <= neff < hi:
                    label = f"{lo}-{hi}"
                    break
            else:
                if neff >= edges[-1]:
                    label = f">={edges[-1]}"
            hist[label] += 1
    vals.sort()
    return {
        "hist": dict(hist),
        "unscoreable": unscoreable,
        "n": len(vals),
        "median": (vals[len(vals) // 2] if vals else NAN),
        "min": (vals[0] if vals else NAN),
        "max": (vals[-1] if vals else NAN),
    }


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


def unaccounted_rate(per_scenario: dict, accounts: dict[str, str]) -> dict:
    """Corpus-level exposure to missing rosters, surfaced instead of silently absorbed.

    Every milestone's score is suppressed in proportion to how many of its calls have no
    account. If that rate differs materially between two arms, the comparison is measuring
    roster coverage rather than routing -- the asymmetric-filtering error this repo has a
    standing rule against. It cannot be seen from the usable counts alone.
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
