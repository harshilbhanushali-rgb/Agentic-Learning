"""Repertoire coverage: which of Naren's SAY moves has a CSM NEVER used?

Why this aggregation exists (docs/findings/layer-d-say-arm.md §8-§9, §11): the say
arm's Naren benchmark measured that he states a given playbook move on a MEDIAN of
~15% of his own routed calls. The playbook is a repertoire he deploys when a call
warrants it, not a per-call checklist, so a rate-vs-benchmark gap at the shipped
0.50 floor was dead for 84 of 87 cells (G-S4). The question the data CAN carry is
binary and call-pooled: over ALL of a CSM's routed calls on a scenario, does even one
verified instance of the move exist?

Three states per (CSM, in-repertoire move), and only the first two are ever reported
as a finding:

  uses it            >= 1 quote-verified instance (hit or partial) on any call
  never              zero instances AND enough calls that zero is significant
  insufficient data  zero instances, too few calls -- NEVER reported as a gap

plus one refinement of `uses it`, pre-registered in findings §13 (2026-09-07):

  uses it, rarely    she uses it, but on HIGH-VOLUME scenarios only (>= 30 of her
                     routed calls, >= 8 of Naren's, comparable moments-per-call) a
                     one-sided Fisher exact test says her call-level rate is below
                     his (p < 0.05) AND her rate is under half of his. This is a
                     rate comparison, which §9 rejected at 8-20 calls because the
                     error bars swamped the gap; at 30+ calls, with Naren's own
                     uncertainty carried by the exact test, it is a different
                     regime. It never touches `never` or `insufficient data`.

THE POWER RULE. If Naren says a move on a fraction p of his routed calls, the chance
a rep who deploys it at the same rate shows zero instances in n calls is (1-p)^n.
"Never" is reported only when n >= n_needed = ceil(ln(alpha) / ln(1-p)), i.e. when
zero-in-n would happen by chance less than alpha of the time. At the measured median
p ~ 0.15 that is 19 calls; 46 of the 61 in-repertoire moves need <= 20. The rule is
enforced per cell here, pinned by tests/test_layer_d_repertoire.py (gate G-R3).

IN NAREN'S REPERTOIRE = he verifiably said the move on >= MIN_REPERTOIRE_CALLS
distinct calls (say-arm move_performance rows count CALLS; hits + partials = calls
where his best verdict was a verified statement). Moves below that bar are Layer C
over-specification candidates (findings §11 census), not coaching material.

Everything here is pure: rates in, cells and text out. No DB, no spend.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from layer_d.aggregate import MoveRate

ALPHA = 0.05
MIN_REPERTOIRE_CALLS = 2

USES = "uses it"
RARELY = "uses it, rarely"
NEVER = "never"
INSUFFICIENT = "insufficient data"
STATES = (USES, RARELY, NEVER, INSUFFICIENT)

# The rarely tier (findings §13), all frozen before the code ran.
MIN_CSM_CALLS_RATE = 30        # her routed calls on the scenario
MIN_NAREN_CALLS_RATE = 8       # his benchmark calls (= tuning min_attempts_to_rank)
RATE_ALPHA = 0.05              # one-sided Fisher exact
RATE_MAX_RATIO = 0.5           # her rate must be below half of his
OPPORTUNITY_MIN_RATIO = 0.5    # her moments/call must be >= half of his


def n_needed(p_hat: float, alpha: float = ALPHA) -> int:
    """Smallest n with (1 - p_hat)^n < alpha: the calls a zero must span before
    it is reported as a gap. p_hat >= 1 means one call suffices; p_hat <= 0 is
    not in anyone's repertoire and has no finite n (callers filter it out)."""
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if p_hat >= 1.0:
        return 1
    if p_hat <= 0.0:
        return math.inf  # type: ignore[return-value]
    n = max(1, math.ceil(math.log(alpha) / math.log(1.0 - p_hat)))
    # The closed form is the estimate; the strict inequality is the definition.
    # Float error can land the ratio a hair off an integer (pre-spend audit,
    # 2026-09-05: p=0.95 gives 1.0000000000000002), and at an EXACT boundary --
    # p_hat = 19/20 is a value real data can produce -- (1-p)^1 == alpha is not
    # "< alpha", so the answer there is 2, not the closed form's 1. Walk to the
    # smallest n that satisfies the rule as stated.
    q = 1.0 - p_hat
    while n > 1 and q ** (n - 1) < alpha:
        n -= 1
    while q ** n >= alpha:
        n += 1
    return n


@dataclass(frozen=True)
class RepertoireMove:
    playbook_id: int
    move_id: str
    naren_said_calls: int      # distinct calls where his best verdict was hit/partial
    naren_calls: int           # his routed calls with >= 1 scored moment for this move

    @property
    def p_hat(self) -> float:
        return self.naren_said_calls / self.naren_calls if self.naren_calls else 0.0

    @property
    def every_n_calls(self) -> int:
        """'Naren says this every ~N calls' -- the coaching-facing frequency."""
        return max(1, round(1.0 / self.p_hat)) if self.p_hat > 0 else 0

    def calls_needed(self, alpha: float = ALPHA) -> int:
        return n_needed(self.p_hat, alpha)


def naren_repertoire(
    naren_rates: list[MoveRate], min_calls: int = MIN_REPERTOIRE_CALLS,
) -> dict[tuple[int, str], RepertoireMove]:
    """The in-repertoire subset of Naren's say-arm cells, keyed by (playbook, move)."""
    out: dict[tuple[int, str], RepertoireMove] = {}
    for r in naren_rates:
        said = r.hits + r.partials
        if said >= min_calls and r.attempts > 0:
            out[(r.playbook_id, r.move_id)] = RepertoireMove(
                r.playbook_id, r.move_id, said, r.attempts)
    return out


@dataclass(frozen=True)
class RepertoireCell:
    rater_id: str
    move: RepertoireMove
    state: str
    csm_said_calls: int
    csm_calls: int
    rate_p: float | None = None                   # rarely test p-value, when the cell was eligible
    opportunity: tuple[float, float] | None = None  # (her moments/call, his moments/call)

    @property
    def calls_needed(self) -> int:
        return self.move.calls_needed()

    @property
    def csm_rate(self) -> float:
        return self.csm_said_calls / self.csm_calls if self.csm_calls else 0.0


def rate_test_p(csm_said: int, csm_calls: int, naren_said: int, naren_calls: int) -> float:
    """One-sided Fisher exact p-value that her call-level rate is LOWER than his.
    Exact, so Naren's small benchmark n (11 calls on today's eligible scenarios)
    is carried as uncertainty rather than treated as a fixed floor."""
    from scipy.stats import fisher_exact  # lazy: scipy is a calibration dependency
    table = [[csm_said, csm_calls - csm_said], [naren_said, naren_calls - naren_said]]
    return float(fisher_exact(table, alternative="less").pvalue)


def rate_eligible(move: RepertoireMove, csm: MoveRate,
                  opportunity: tuple[float, float] | None) -> bool:
    """§13 eligibility: her n, his n, and opportunity parity. Unknown densities
    (None) are NOT eligible -- the parity check is a precondition, not a nicety."""
    if csm.attempts < MIN_CSM_CALLS_RATE or move.naren_calls < MIN_NAREN_CALLS_RATE:
        return False
    if opportunity is None:
        return False
    hers, his = opportunity
    return his > 0 and hers >= OPPORTUNITY_MIN_RATIO * his


def classify(move: RepertoireMove, csm: MoveRate | None, alpha: float = ALPHA,
             opportunity: tuple[float, float] | None = None) -> tuple[str, float | None]:
    """The rule. Returns (state, rate_p). A missing CSM row means zero routed
    calls, which is insufficient data, never a gap. `rate_p` is set only when the
    rarely test actually ran (eligible `uses it` cells), so a reader can tell
    "tested and not rare" from "not tested"."""
    said = (csm.hits + csm.partials) if csm else 0
    calls = csm.attempts if csm else 0
    if said >= 1:
        if csm is not None and rate_eligible(move, csm, opportunity):
            p = rate_test_p(said, calls, move.naren_said_calls, move.naren_calls)
            her_rate = said / calls
            if p < RATE_ALPHA and her_rate < RATE_MAX_RATIO * move.p_hat:
                return RARELY, p
            return USES, p
        return USES, None
    if calls >= move.calls_needed(alpha):
        return NEVER, None
    return INSUFFICIENT, None


def repertoire_coverage(
    moves: dict[tuple[int, str], RepertoireMove],
    csm_rates_by_rater: dict[str, list[MoveRate]],
    alpha: float = ALPHA,
    densities: dict[tuple[str, int, str], tuple[int, int]] | None = None,
) -> dict[str, list[RepertoireCell]]:
    """Every in-repertoire move classified for every rater that has ANY say-arm
    data. Moves the rater has no row for are included as insufficient (0 calls),
    so the report's counts always sum to the repertoire size.

    `densities` is storage.get_say_densities' output: (population, playbook,
    move) -> (scored moments, calls). It feeds the rarely tier's opportunity
    check; without it no cell is rate-eligible (§13)."""
    out: dict[str, list[RepertoireCell]] = {}
    for rater_id, rates in csm_rates_by_rater.items():
        by_cell = {(r.playbook_id, r.move_id): r for r in rates}
        cells = []
        for cell, move in sorted(moves.items()):
            csm = by_cell.get(cell)
            opp = None
            if densities:
                hers = densities.get(("csm",) + cell)
                his = densities.get(("naren",) + cell)
                if hers and his and hers[1] and his[1]:
                    opp = (hers[0] / hers[1], his[0] / his[1])
            state, p = classify(move, csm, alpha, opportunity=opp)
            cells.append(RepertoireCell(
                rater_id, move, state,
                (csm.hits + csm.partials) if csm else 0,
                csm.attempts if csm else 0, rate_p=p, opportunity=opp))
        out[rater_id] = cells
    return out


def format_repertoire_report(
    csm_name: str,
    cells: list[RepertoireCell],
    move_meta: dict[tuple[int, str], dict],
    csm_quotes: dict[tuple[int, str], list[str]] | None = None,
    max_quotes: int = 3,
    alpha: float = ALPHA,
) -> str:
    """The coaching section. NEVER cells lead, grouped by scenario, ordered by how
    often Naren uses the move (his most-used move she has never used comes first);
    each carries his verbatim deployments (move_meta[cell]['naren_quotes'], the
    playbook's own evidence). USES cells follow with up to max_quotes of HER
    verified instances. INSUFFICIENT cells are listed last as one line each, with
    the call count still needed -- present so nobody reads their absence as
    'fine', never worded as a gap."""
    csm_quotes = csm_quotes or {}
    lines = [f"Repertoire coverage (say-type moves) -- {csm_name}", "=" * 60]
    if not cells:
        lines.append("No in-repertoire moves to report against (no say-arm data).")
        return "\n".join(lines)

    counts = {s: sum(1 for c in cells if c.state == s) for s in STATES}
    total_calls = max((c.csm_calls for c in cells), default=0)
    lines.append(
        f"Naren's repertoire: {len(cells)} moves he has said on >= "
        f"{MIN_REPERTOIRE_CALLS} of his own calls.  Your routed calls per scenario: "
        f"up to {total_calls}.")
    lines.append(
        f"  uses it: {counts[USES]}    uses it, rarely: {counts[RARELY]}    "
        f"never (enough calls to say so): {counts[NEVER]}"
        f"    insufficient data: {counts[INSUFFICIENT]}")

    def meta(c: RepertoireCell) -> dict:
        return move_meta.get((c.move.playbook_id, c.move.move_id), {})

    def scen(c: RepertoireCell) -> str:
        return meta(c).get("scenario_key", f"playbook {c.move.playbook_id}")

    # ---- NEVER --------------------------------------------------------------
    never = [c for c in cells if c.state == NEVER]
    lines += ["", f"NEVER USED -- zero verified instances across all your calls on the "
                  f"scenario, over at least the {int(round((1 - alpha) * 100))}%-confidence "
                  f"call count for that move:"]
    if not never:
        lines.append("  (none)")
    groups: dict[str, list[RepertoireCell]] = {}
    for c in never:
        groups.setdefault(scen(c), []).append(c)
    ordered = sorted(groups.items(),
                     key=lambda kv: -max(c.move.p_hat for c in kv[1]))
    for i, (sk, grp) in enumerate(ordered, start=1):
        lines.append(f"\n#{i}  {sk}")
        for c in sorted(grp, key=lambda c: -c.move.p_hat):
            m = meta(c)
            lines.append(f"    {c.move.move_id}: {m.get('name', '(unnamed move)')}")
            lines.append(
                f"        you: 0 of {c.csm_calls} calls ({c.calls_needed} needed)   "
                f"Naren: says it every ~{c.move.every_n_calls} calls "
                f"({c.move.naren_said_calls}/{c.move.naren_calls})")
            if m.get("criterion"):
                lines.append(f"        the move: {m['criterion']}")
            for q in (m.get("naren_quotes") or [])[:max_quotes]:
                lines.append(f"        Naren, real call: \"{q}\"")

    # ---- USES IT, RARELY ----------------------------------------------------
    rarely = [c for c in cells if c.state == RARELY]
    lines += ["", f"USES IT, BUT RARELY -- on scenarios with >= {MIN_CSM_CALLS_RATE} of your "
                  f"calls, your call-level rate is below half of Naren's (one-sided Fisher "
                  f"exact, p < {RATE_ALPHA:.2f}):"]
    if not rarely:
        lines.append("  (none)")
    for c in sorted(rarely, key=lambda c: c.rate_p or 1.0):
        m = meta(c)
        lines.append(f"    [{scen(c)}] {c.move.move_id}: {m.get('name', '(unnamed move)')}")
        lines.append(
            f"        you: {c.csm_said_calls} of {c.csm_calls} calls ({c.csm_rate:.0%})   "
            f"Naren: {c.move.naren_said_calls} of {c.move.naren_calls} ({c.move.p_hat:.0%})   "
            f"p = {c.rate_p:.3f}")
        if c.opportunity:
            lines.append(f"        opportunity: you {c.opportunity[0]:.1f} moments/call, "
                         f"Naren {c.opportunity[1]:.1f}")
        if m.get("criterion"):
            lines.append(f"        the move: {m['criterion']}")
        for q in (m.get("naren_quotes") or [])[:max_quotes]:
            lines.append(f"        Naren, real call: \"{q}\"")
        for q in csm_quotes.get((c.move.playbook_id, c.move.move_id), [])[:max_quotes]:
            lines.append(f"        your call: \"{q}\"")

    # ---- USES IT ------------------------------------------------------------
    uses = [c for c in cells if c.state == USES]
    lines += ["", "USES IT -- at least one verified instance in your calls:"]
    if not uses:
        lines.append("  (none)")
    for c in sorted(uses, key=lambda c: (scen(c), c.move.move_id)):
        m = meta(c)
        tested = f"; rate tested, p = {c.rate_p:.2f}" if c.rate_p is not None else ""
        lines.append(
            f"    [{scen(c)}] {c.move.move_id}: {m.get('name', '(unnamed move)')} -- "
            f"you: {c.csm_said_calls} of {c.csm_calls} calls; Naren every "
            f"~{c.move.every_n_calls}{tested}")
        for q in csm_quotes.get((c.move.playbook_id, c.move.move_id), [])[:max_quotes]:
            lines.append(f"        your call: \"{q}\"")

    # ---- INSUFFICIENT -------------------------------------------------------
    insufficient = [c for c in cells if c.state == INSUFFICIENT]
    lines += ["", "INSUFFICIENT DATA -- zero instances so far, but too few calls to "
                  "call it a gap (not a finding):"]
    if not insufficient:
        lines.append("  (none)")
    for c in sorted(insufficient, key=lambda c: (scen(c), c.move.move_id)):
        m = meta(c)
        lines.append(
            f"    [{scen(c)}] {c.move.move_id}: {m.get('name', '(unnamed move)')} -- "
            f"0 of {c.csm_calls} calls ({c.calls_needed} needed at Naren's rate of "
            f"every ~{c.move.every_n_calls})")
    return "\n".join(lines)
