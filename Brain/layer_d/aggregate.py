"""Pure aggregation: rates, shrinkage, dead-check flags, gap ranking, report text.

Everything here is derived from move_events at query/report time and NEVER stored
back per-row -- the same rule as the old weighted score and severity buckets
(db/schema.sql's gap analysis notes): a stored derivative goes stale the moment
attempts increments.

Why empirical-Bayes shrinkage instead of raw rates: per-CSM per-move cells are
sparse (the old run put the MEDIAN milestone at ~25 attempts needed for stability
and 108 of 352 below 5 attempts). A raw 0/3 would outrank a 2/14 gap purely on
sample noise. Shrinking toward the cohort mean with `prior_strength`
pseudo-observations makes sparse cells conservative automatically; as attempts
grow the data dominates. prior_strength is a tuning key, UNCALIBRATED until C2/C3.

Why a dead-check flag keyed to NAREN's rate: the old rubrics spent 24% of all
grading attempts on 87 criteria that nobody -- including the benchmark -- ever
passed. A check the expert's own calls fail more often than
dead_check_naren_floor is evidence about the CHECK, not about any rep, so it is
excluded from gap ranking and surfaced to the operator instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field

NAREN = "naren"          # rater_id sentinel for the benchmark population


@dataclass(frozen=True)
class MoveRate:
    playbook_id: int
    move_id: str
    attempts: int
    hits: int
    partials: int

    @property
    def weighted(self) -> float:
        return self.hits + 0.5 * self.partials

    @property
    def raw_rate(self) -> float:
        return self.weighted / self.attempts if self.attempts else 0.0


@dataclass(frozen=True)
class Gap:
    rater_id: str
    playbook_id: int
    move_id: str
    naren_rate: float
    naren_attempts: int
    csm_rate_raw: float
    csm_rate_shrunk: float
    csm_attempts: int

    @property
    def size(self) -> float:
        return self.naren_rate - self.csm_rate_shrunk


@dataclass
class DeadCheck:
    playbook_id: int
    move_id: str
    naren_rate: float
    naren_attempts: int
    reason: str = field(default="naren_rate_below_floor")


def shrunk_rate(rate: MoveRate, prior_rate: float, prior_strength: float) -> float:
    """(weighted_hits + k * p0) / (attempts + k). At attempts=0 this IS the prior."""
    return (rate.weighted + prior_strength * prior_rate) / (rate.attempts + prior_strength)


def cohort_prior(rates: list[MoveRate]) -> float:
    """Attempt-weighted pooled rate across every rater for ONE (playbook, move).

    Weighted by attempts rather than a mean of rates so a rater with 2 attempts
    does not move the prior as much as one with 40.
    """
    total = sum(r.attempts for r in rates)
    if total == 0:
        return 0.0
    return sum(r.weighted for r in rates) / total


def dead_checks(
    naren_rates: list[MoveRate], floor: float, min_attempts: int
) -> list[DeadCheck]:
    """Checks the benchmark population itself fails: excluded from ranking,
    reported to the operator. A check with fewer than min_attempts Naren attempts
    is NOT flagged -- unmeasured is not the same as dead."""
    return [
        DeadCheck(r.playbook_id, r.move_id, round(r.raw_rate, 4), r.attempts)
        for r in naren_rates
        if r.attempts >= min_attempts and r.raw_rate < floor
    ]


def rank_gaps(
    csm_rates: dict[str, list[MoveRate]],       # rater_id -> rates
    naren_rates: list[MoveRate],
    *,
    prior_strength: float,
    min_attempts: int,
    dead_floor: float,
) -> tuple[dict[str, list[Gap]], list[DeadCheck]]:
    """Per-CSM gaps ranked largest-first, with dead checks excluded and returned.

    A gap is rankable only when BOTH sides are measured: csm attempts and naren
    attempts each >= min_attempts. The shrinkage prior for a (playbook, move) is
    pooled over the CSM cohort for that cell -- deliberately NOT over Naren, whose
    rate is the comparison target, not the prior belief about a junior.
    """
    naren_by_key = {(r.playbook_id, r.move_id): r for r in naren_rates}
    dead = dead_checks(naren_rates, dead_floor, min_attempts)
    dead_keys = {(d.playbook_id, d.move_id) for d in dead}

    by_cell: dict[tuple[int, str], list[MoveRate]] = {}
    for rates in csm_rates.values():
        for r in rates:
            by_cell.setdefault((r.playbook_id, r.move_id), []).append(r)
    priors = {cell: cohort_prior(rs) for cell, rs in by_cell.items()}

    ranked: dict[str, list[Gap]] = {}
    for rater_id, rates in csm_rates.items():
        gaps: list[Gap] = []
        for r in rates:
            key = (r.playbook_id, r.move_id)
            bench = naren_by_key.get(key)
            if bench is None or key in dead_keys:
                continue
            if r.attempts < min_attempts or bench.attempts < min_attempts:
                continue
            gaps.append(Gap(
                rater_id=rater_id,
                playbook_id=r.playbook_id,
                move_id=r.move_id,
                naren_rate=round(bench.raw_rate, 4),
                naren_attempts=bench.attempts,
                csm_rate_raw=round(r.raw_rate, 4),
                csm_rate_shrunk=round(shrunk_rate(r, priors[key], prior_strength), 4),
                csm_attempts=r.attempts,
            ))
        gaps.sort(key=lambda g: g.size, reverse=True)
        ranked[rater_id] = gaps
    return ranked, dead


def rank_pairwise(
    csm_rates: dict[str, list[MoveRate]],
    *,
    prior_strength: float,
    min_attempts: int,
    tie_flag_share: float = 0.8,
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Pairwise-arm ranking: per (csm, playbook, move), the MATCH-OR-BEAT share vs
    the benchmark exemplar -- hit=won both orders, partial=judged equal (counts
    half), miss=lost. No Naren population needed: the benchmark is inside every
    verdict. Gaps rank by the SHRUNKEN loss share, largest first.

    Also returns the blurry-axis flags: cells where >= tie_flag_share of attempts
    were 'equal' -- the judge cannot separate anyone on that move (the pairwise
    analog of a dead check; a rewrite candidate, not a coachable gap).
    """
    by_cell: dict[tuple[int, str], list[MoveRate]] = {}
    for rates in csm_rates.values():
        for r in rates:
            by_cell.setdefault((r.playbook_id, r.move_id), []).append(r)
    priors = {cell: cohort_prior(rs) for cell, rs in by_cell.items()}

    blurry = [
        {"playbook_id": pb, "move_id": mv,
         "tie_share": round(sum(r.partials for r in rs) / max(sum(r.attempts for r in rs), 1), 3),
         "attempts": sum(r.attempts for r in rs)}
        for (pb, mv), rs in sorted(by_cell.items())
        if sum(r.attempts for r in rs) >= min_attempts
        and sum(r.partials for r in rs) / max(sum(r.attempts for r in rs), 1) >= tie_flag_share
    ]
    blurry_keys = {(b["playbook_id"], b["move_id"]) for b in blurry}

    ranked: dict[str, list[dict]] = {}
    for rater_id, rates in csm_rates.items():
        gaps = []
        for r in rates:
            key = (r.playbook_id, r.move_id)
            if r.attempts < min_attempts or key in blurry_keys:
                continue
            shrunk = shrunk_rate(r, priors[key], prior_strength)
            gaps.append({
                "rater_id": rater_id, "playbook_id": r.playbook_id,
                "move_id": r.move_id, "attempts": r.attempts,
                "wins": r.hits, "equals": r.partials,
                "losses": r.attempts - r.hits - r.partials,
                "match_or_beat_raw": round(r.raw_rate, 4),
                "match_or_beat_shrunk": round(shrunk, 4),
                "gap": round(1.0 - shrunk, 4),
            })
        gaps.sort(key=lambda g: g["gap"], reverse=True)
        ranked[rater_id] = gaps
    return ranked, blurry


def group_by_scenario(
    gaps: list[dict],
    move_meta: dict[tuple[int, str], dict],
) -> list[dict]:
    """One entry per SCENARIO, moves within -- the report-grouping fix. Before
    this, the flat top-N list could (and on the first production run, did) show
    the same scenario three times as unrelated-looking rows.

    `gaps` is assumed already sorted by "gap" descending (rank_pairwise's
    contract), so a group's move order -- and therefore its first/worst move --
    falls out of the input order for free, no re-sort needed. Scenarios are
    ordered by their single WORST move's gap: the report's job is to surface the
    sharpest coaching opportunity, and averaging a scenario's moves together
    would let one severe, specific problem hide behind several fine ones."""
    groups: dict[str, list[dict]] = {}
    for g in gaps:
        scenario_key = move_meta.get(
            (g["playbook_id"], g["move_id"]), {}).get("scenario_key", "?")
        groups.setdefault(scenario_key, []).append(g)
    out = [{"scenario_key": sk, "worst_gap": moves[0]["gap"], "moves": moves}
           for sk, moves in groups.items()]
    out.sort(key=lambda o: o["worst_gap"], reverse=True)
    return out


def format_pairwise_priorities(
    csm_name: str,
    gaps: list[dict],
    move_meta: dict[tuple[int, str], dict],
) -> str:
    """Ranked pairwise coaching priorities, grouped one block per scenario
    (moves within), scenarios worst-first. No top-N cutoff: verified 2026-08-26
    that the real scale is small (19 scenarios / 51 rankable cells on the first
    production run) -- a full report reads fine, and hiding a scenario just to
    hit a count would drop real signal for no reason."""
    lines = [f"Coaching priorities -- {csm_name}", "=" * 60]
    if not gaps:
        lines.append("No rankable gaps (every measured move is at or near benchmark, "
                      "or attempts are below the ranking floor).")
        return "\n".join(lines)
    for i, grp in enumerate(group_by_scenario(gaps, move_meta), start=1):
        lines.append(f"\n#{i}  {grp['scenario_key']}  "
                     f"(worst move: {grp['worst_gap']:.0%} gap, "
                     f"{len(grp['moves'])} move(s) measured)")
        for g in grp["moves"]:
            meta = move_meta.get((g["playbook_id"], g["move_id"]), {})
            lines.append(
                f"    {g['move_id']}: {meta.get('name', '(unnamed move)')}"
            )
            lines.append(
                f"        vs benchmark: won {g['wins']}, equal {g['equals']}, "
                f"lost {g['losses']} of {g['attempts']} moments "
                f"(match-or-beat {g['match_or_beat_shrunk']:.0%})"
            )
            if meta.get("criterion"):
                lines.append(f"        the move: {meta['criterion']}")
            if meta.get("naren_quote"):
                lines.append(f"        benchmark example: \"{meta['naren_quote']}\"")
    return "\n".join(lines)


def format_say_priorities(
    csm_name: str,
    gaps: list[Gap],
    move_meta: dict[tuple[int, str], dict],
    csm_by_cell: dict[tuple[int, str], MoveRate],
    naren_by_cell: dict[tuple[int, str], MoveRate],
    evidence: dict[tuple[int, str], list[str]],
    densities: dict[tuple[str, int, str], tuple[int, int]] | None = None,
) -> str:
    """Say-arm coaching priorities. Same rank_gaps output as the checks path, but
    the language matches the arm's semantics: attempts are CALLS, hit means stated
    SPECIFICALLY, partial means stated generically. Grouped one block per scenario,
    scenarios worst-first, no top-N cutoff -- same reasoning as the pairwise report.

    `densities` (storage.get_say_densities) is the pre-registered opportunity-
    asymmetry readout: moments-per-call on both sides of every cell, so a gap
    built from systematically different moment densities is visible, not hidden."""
    lines = [f"Coaching priorities (say-type moves) -- {csm_name}", "=" * 60]
    if not gaps:
        lines.append("No rankable say-move gaps (at or near benchmark everywhere "
                     "measured, or attempts below the ranking floor).")
        return "\n".join(lines)
    as_dicts = [{"playbook_id": g.playbook_id, "move_id": g.move_id,
                 "gap": g.size, "_gap": g} for g in gaps]
    for i, grp in enumerate(group_by_scenario(as_dicts, move_meta), start=1):
        lines.append(f"\n#{i}  {grp['scenario_key']}  "
                     f"(worst move: {grp['worst_gap']:+.0%} gap, "
                     f"{len(grp['moves'])} move(s) measured)")
        for d in grp["moves"]:
            g: Gap = d["_gap"]
            meta = move_meta.get((g.playbook_id, g.move_id), {})
            c = csm_by_cell.get((g.playbook_id, g.move_id))
            n = naren_by_cell.get((g.playbook_id, g.move_id))
            lines.append(f"    {g.move_id}: {meta.get('name', '(unnamed move)')}")
            if c and n:
                c_said = c.hits + c.partials
                n_said = n.hits + n.partials
                lines.append(
                    f"        you: said it on {c_said}/{c.attempts} calls "
                    f"(specific on {c.hits})   benchmark: {n_said}/{n.attempts} "
                    f"calls (specific on {n.hits})   weighted gap: {g.size:+.0%}")
                if densities:
                    cd = densities.get(("csm", g.playbook_id, g.move_id))
                    nd = densities.get(("naren", g.playbook_id, g.move_id))
                    if cd and nd and cd[1] and nd[1]:
                        lines.append(
                            f"        opportunity: you {cd[0] / cd[1]:.1f} "
                            f"moments/call, benchmark {nd[0] / nd[1]:.1f} -- a "
                            f"large imbalance inflates the denser side's rate")
            else:
                lines.append(
                    f"        you: {g.csm_rate_shrunk:.0%} of {g.csm_attempts} calls"
                    f"   benchmark: {g.naren_rate:.0%} of {g.naren_attempts}"
                    f"   gap: {g.size:+.0%}")
            if meta.get("criterion"):
                lines.append(f"        the move: {meta['criterion']}")
            if meta.get("naren_quote"):
                lines.append(f"        benchmark example: \"{meta['naren_quote']}\"")
            for q in evidence.get((g.playbook_id, g.move_id), [])[:2]:
                lines.append(f"        your call: \"{q}\"")
    return "\n".join(lines)


def format_priorities(
    csm_name: str,
    gaps: list[Gap],
    move_meta: dict[tuple[int, str], dict],     # (playbook_id, move_id) -> {scenario_key, name, criterion, naren_quote}
    evidence: dict[tuple[int, str], list[str]],  # verified CSM quotes per cell
    top_n: int,
) -> str:
    """The ranked coaching priorities, as plain text. No headline score, no severity
    buckets -- ONLY gaps large enough and measured enough to rank."""
    lines = [f"Coaching priorities -- {csm_name}", "=" * 60]
    if not gaps:
        lines.append("No rankable gaps (every measured move is at or near benchmark, "
                      "or attempts are below the ranking floor).")
        return "\n".join(lines)
    for i, g in enumerate(gaps[:top_n], start=1):
        meta = move_meta.get((g.playbook_id, g.move_id), {})
        lines.append(
            f"\n#{i}  [{meta.get('scenario_key', '?')}] {g.move_id}: "
            f"{meta.get('name', '(unnamed move)')}"
        )
        lines.append(
            f"    you: {g.csm_rate_shrunk:.0%} of {g.csm_attempts} moments "
            f"(raw {g.csm_rate_raw:.0%})   benchmark: {g.naren_rate:.0%} "
            f"of {g.naren_attempts}   gap: {g.size:+.0%}"
        )
        if meta.get("criterion"):
            lines.append(f"    the move: {meta['criterion']}")
        if meta.get("naren_quote"):
            lines.append(f"    benchmark example: \"{meta['naren_quote']}\"")
        for q in evidence.get((g.playbook_id, g.move_id), [])[:2]:
            lines.append(f"    your call: \"{q}\"")
    return "\n".join(lines)
