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
NEVER = "never"
INSUFFICIENT = "insufficient data"
STATES = (USES, NEVER, INSUFFICIENT)


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

    @property
    def calls_needed(self) -> int:
        return self.move.calls_needed()


def classify(move: RepertoireMove, csm: MoveRate | None, alpha: float = ALPHA) -> str:
    """The three-way rule. A missing CSM row means zero routed calls, which is
    insufficient data, never a gap."""
    said = (csm.hits + csm.partials) if csm else 0
    calls = csm.attempts if csm else 0
    if said >= 1:
        return USES
    if calls >= move.calls_needed(alpha):
        return NEVER
    return INSUFFICIENT


def repertoire_coverage(
    moves: dict[tuple[int, str], RepertoireMove],
    csm_rates_by_rater: dict[str, list[MoveRate]],
    alpha: float = ALPHA,
) -> dict[str, list[RepertoireCell]]:
    """Every in-repertoire move classified for every rater that has ANY say-arm
    data. Moves the rater has no row for are included as insufficient (0 calls),
    so the report's counts always sum to the repertoire size."""
    out: dict[str, list[RepertoireCell]] = {}
    for rater_id, rates in csm_rates_by_rater.items():
        by_cell = {(r.playbook_id, r.move_id): r for r in rates}
        cells = []
        for cell, move in sorted(moves.items()):
            csm = by_cell.get(cell)
            cells.append(RepertoireCell(
                rater_id, move, classify(move, csm, alpha),
                (csm.hits + csm.partials) if csm else 0,
                csm.attempts if csm else 0))
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
        f"  uses it: {counts[USES]}    never (enough calls to say so): {counts[NEVER]}"
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

    # ---- USES IT ------------------------------------------------------------
    uses = [c for c in cells if c.state == USES]
    lines += ["", "USES IT -- at least one verified instance in your calls:"]
    if not uses:
        lines.append("  (none)")
    for c in sorted(uses, key=lambda c: (scen(c), c.move.move_id)):
        m = meta(c)
        lines.append(
            f"    [{scen(c)}] {c.move.move_id}: {m.get('name', '(unnamed move)')} -- "
            f"you: {c.csm_said_calls} of {c.csm_calls} calls; Naren every "
            f"~{c.move.every_n_calls}")
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
