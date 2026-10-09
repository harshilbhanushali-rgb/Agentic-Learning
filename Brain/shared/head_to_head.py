"""Pure logic for the head-to-head pairwise comparison harness.

No Gemma, no Postgres, no embeddings -- everything here is arithmetic, so the parts a silent
bug would render meaningless are unit-testable without spending anything. Same split
shared/cluster_evidence.py and shared/topic_grouping.py already follow.

Design spec: docs/superpowers/specs/2026-08-13-head-to-head-comparison-design.md

Vocabulary used throughout:
  side     "A" / "B" -- the two things being compared, fixed per item by the caller.
           A is the CSM in the headline stage, and whichever role the control defines
           elsewhere. This module never learns which side is which; blinding is the
           instrument.
  order    "AB" / "BA" -- which side occupied slot 1 in the prompt.
  winner   "1" / "2" / "tie" -- what the judge returned, in SLOT terms.
  outcome  "A" / "B" / "tie" -- a whole item, after both orders are combined.
"""
from __future__ import annotations

import hashlib
import json
import math
import random

_ORDERS = ("AB", "BA")
_SLOT_TO_SIDE = {"AB": {"1": "A", "2": "B"}, "BA": {"1": "B", "2": "A"}}


# ---------------------------------------------------------------------------------------
# Batch assignment
# ---------------------------------------------------------------------------------------

def assign_swap_batches(item_ids: list[str], batch_size: int,
                        seed: int) -> list[list[tuple[str, str]]]:
    """Lay every item out twice -- once per order -- so no batch ever holds both.

    THE GUARANTEE THAT MATTERS: a judge shown the same pair twice inside one call answers the
    second one from memory, and the position-swap control would then report that memory as
    reliability. The guarantee is structural rather than checked after the fact: the two
    orders are batched from two SEPARATE passes, so a batch is drawn wholly from one of them
    and cannot contain a duplicate id.

    The passes are then interleaved rather than run back to back, so a drift in model
    behaviour over the run cannot land entirely on one order.
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    if len(set(item_ids)) != len(item_ids):
        raise ValueError("duplicate item_id: it would silently double that item's weight")
    if not item_ids:
        return []

    rng = random.Random(seed)
    passes = []
    for order in _ORDERS:
        entries = [(i, order) for i in item_ids]
        rng.shuffle(entries)
        passes.append([entries[k:k + batch_size] for k in range(0, len(entries), batch_size)])

    out: list[list[tuple[str, str]]] = []
    for k in range(max(len(p) for p in passes)):
        for p in passes:
            if k < len(p):
                out.append(p[k])
    return out


# ---------------------------------------------------------------------------------------
# Verdict normalisation
# ---------------------------------------------------------------------------------------

def normalize_winner(order: str, winner: str) -> str:
    """Slot verdict ("1"/"2"/"tie") -> side ("A"/"B"/"tie"), undoing the swap.

    Raises on anything else rather than defaulting. A model that returns "3" or
    "Response 1" is a parse failure, and coercing it to a tie would bury that failure
    inside the tie share where nobody would find it.
    """
    if order not in _SLOT_TO_SIDE:
        raise ValueError(f"unknown order {order!r}, expected one of {_ORDERS}")
    token = str(winner).strip().lower()
    if token == "tie":
        return "tie"
    mapped = _SLOT_TO_SIDE[order].get(token)
    if mapped is None:
        raise ValueError(f"unparseable winner {winner!r} for order {order!r}")
    return mapped


def order_average(ab_side: str, ba_side: str) -> str:
    """Combine one item's two orders into a single outcome.

    Disagreement is a TIE, not a coin flip: a judge that reverses when the layout reverses
    has told us nothing about this item, and picking either answer would launder position
    noise into the win rate. One decisive order alongside one tie is not a contradiction --
    the judge was simply less decisive once -- so the decisive side carries the item.
    """
    if ab_side == ba_side:
        return ab_side
    if ab_side == "tie":
        return ba_side
    if ba_side == "tie":
        return ab_side
    return "tie"


# ---------------------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------------------

def win_rate(outcomes: list[str], side: str = "A") -> dict:
    """Win rate for `side`, with ties excluded from the denominator and reported alongside.

    `rate` is None rather than 0.0 when nothing was decisive: 0.0 asserts "lost every
    comparison", which is a different claim from "never produced a comparison".
    """
    n_total = len(outcomes)
    ties = sum(1 for o in outcomes if o == "tie")
    n_decisive = n_total - ties
    return {
        "rate": (sum(1 for o in outcomes if o == side) / n_decisive) if n_decisive else None,
        "n_total": n_total,
        "n_decisive": n_decisive,
        "tie_share": (ties / n_total) if n_total else 0.0,
    }


def swap_agreement(pairs: list[tuple[str, str]]) -> dict:
    """C1: how often the two orders of one item give the same answer.

    Scored over items where AT LEAST ONE order was decisive. Items both orders called a tie
    are excluded and reported separately -- two ties agree trivially, so counting them would
    let a maximally indecisive judge pass the control.

    `agreement` is strict equality, so one-decisive-one-tie counts against it. `flip_rate`
    is reported separately for the harder failure -- both orders decisive and opposite --
    because "less decisive once" and "reversed itself" are different defects.
    """
    both_tie = sum(1 for a, b in pairs if a == "tie" and b == "tie")
    scored = [(a, b) for a, b in pairs if not (a == "tie" and b == "tie")]
    n = len(scored)
    flips = sum(1 for a, b in scored if a != "tie" and b != "tie" and a != b)
    return {
        "agreement": (sum(1 for a, b in scored if a == b) / n) if n else None,
        "flip_rate": (flips / n) if n else None,
        "n_scored": n,
        "both_tie_share": (both_tie / len(pairs)) if pairs else 0.0,
    }


# ---------------------------------------------------------------------------------------
# C2 pair selection
# ---------------------------------------------------------------------------------------

def adjacent_rank_pair(sims: list[float], tolerance: float) -> tuple[int, int] | None:
    """Two candidates at ADJACENT ranks whose similarities differ by <= tolerance.

    C2 needs two expert responses neither of which has a fit advantage, or the control would
    measure retrieval rank rather than the judge. Adjacency is required as well as closeness:
    two far-apart ranks that happen to sit within tolerance would hand the judge a candidate
    the retrieval never ranked as a runner-up.

    Returns (higher-similarity index, lower-similarity index), or None if no adjacent pair
    qualifies.
    """
    if len(sims) < 2:
        return None
    order = sorted(range(len(sims)), key=lambda i: -sims[i])
    best = None
    for k in range(len(order) - 1):
        hi, lo = order[k], order[k + 1]
        gap = sims[hi] - sims[lo]
        if gap <= tolerance and (best is None or gap < best[0]):
            best = (gap, hi, lo)
    return (best[1], best[2]) if best else None


# ---------------------------------------------------------------------------------------
# Stratifiers -- confounds this design reports rather than controls
# ---------------------------------------------------------------------------------------

def by_decile(outcomes: list[str], values: list[float], side: str = "A",
              bins: int = 10) -> list[dict]:
    """Win rate within each stratum of `values`, ranked ascending.

    Judging everything above the floor and stratifying afterwards is what lets ONE run
    measure the whole floor grid -- the same property as Layer C's (percentile, fraction)
    grid, where selecting a row afterwards needs no re-run.
    """
    if len(outcomes) != len(values):
        raise ValueError(f"length mismatch: {len(outcomes)} outcomes vs {len(values)} values")
    if bins < 1:
        raise ValueError(f"bins must be >= 1, got {bins}")
    order = sorted(range(len(values)), key=lambda i: values[i])

    n = len(order)
    sizes = [n // bins + (1 if k < n % bins else 0) for k in range(bins)]
    out, cursor = [], 0
    for k, size in enumerate(sizes):
        idx = order[cursor:cursor + size]
        cursor += size
        stats = win_rate([outcomes[i] for i in idx], side)
        out.append({
            "bin": k,
            "n": len(idx),
            "lo": values[idx[0]] if idx else None,
            "hi": values[idx[-1]] if idx else None,
            **stats,
        })
    return out


def length_matched(len_a: list[int], len_b: list[int], band: float = 0.25) -> list[int]:
    """Indices whose two sides are within `band` on |log(len_a / len_b)|.

    Length is a real confound here, not a hypothetical: response_word_count scored AUC 0.853
    for "is this coachable" in this repo's own labelled sample, so a judge that simply
    prefers the longer answer would reproduce that as a fake win. It is handled by measuring
    the win rate on this subset, NOT by instructing the judge -- three wording passes have
    already failed in this codebase.

    A zero-length side is excluded rather than matched: log(0) is undefined, and treating an
    empty response as "same length" would quietly admit the one case the band exists to catch.
    """
    if len(len_a) != len(len_b):
        raise ValueError(f"length mismatch: {len(len_a)} vs {len(len_b)}")
    return [i for i, (a, b) in enumerate(zip(len_a, len_b))
            if a > 0 and b > 0 and abs(math.log(a / b)) <= band]


# ---------------------------------------------------------------------------------------
# Freezing the moment set
# ---------------------------------------------------------------------------------------

def moments_sha(moments: list[dict]) -> str:
    """Stable content hash of the frozen moment set.

    Every paid stage records this and refuses to run against a mismatch. Without it two
    sessions judge different moment sets and their results cannot be combined -- the defect
    that made `arm0_baseline` incomparable to the arms it was measured against, because it
    had been scored over a different clustering run.

    Insensitive to list order and to key order, so re-serialising the artifact cannot
    invalidate it; sensitive to any change of content, which is the point.
    """
    encoded = sorted(json.dumps(m, sort_keys=True, ensure_ascii=False, default=str)
                     for m in moments)
    return hashlib.sha256("\n".join(encoded).encode("utf-8")).hexdigest()
