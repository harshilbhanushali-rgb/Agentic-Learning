"""The relative top-K matching rule, in one place.

Extracted from v1/layer_b.py so Layer D (ego_trap) and the calibration harnesses
can apply the SAME rule without importing v1/ and without reimplementing it.
Same precedent as v2/layer_c.build_clause_pool and shared/response_taxonomy.py:
when a second consumer needs a rule, the rule moves to shared/ and the original
caller imports it back, rather than the rule being copied.

Why relative and not absolute, since this is the whole point of the module:
an absolute cosine floor does not scale with taxonomy size. At 149 scenarios,
70% of pairs cleared the old 0.30 floor against nearly all of them at once. These
embeddings put short conversational text in a narrow band (measured over 416
transcripts: trigger-vs-scenario p10=0.496 p50=0.550 p90=0.613), so the number
that works at one corpus size is wrong at the next. Ranking against a trigger's
OWN best match is scale-invariant.

Nothing here does I/O, embeds anything, or reads tuning.yaml -- callers pass
`margin` and `cap` in, so the same functions serve layer_b's relative_margin and
layer_d's similarity_relative_margin without the two knobs leaking into each
other.
"""
from __future__ import annotations

import numpy as np


def is_sink_flags(scenario_map: dict[str, dict], keys: list[str]) -> list[bool]:
    """The one definition of "this scenario is a sink", parallel to `keys`.

    A sink is a cluster Layer A judged non-coachable (mechanics, logistics,
    backchannel). It is kept in the taxonomy on purpose as landfill for junk
    matches, so `is_coachable` is a real routing signal, not a data-quality flag.

    Defaults to True (not a sink) on a missing key so a hand-built scenario_map in
    a test does not have to spell out `is_coachable` for every entry -- matching
    the behaviour of the three inline comprehensions this replaces.

    Keys off `is_coachable`, never `cluster_kind`: they are equivalent on today's
    live data (66 mechanics + 10 logistics == the 76 is_coachable=false rows), but
    `is_coachable` is the column Layer C branches on to skip rubric generation, so
    it is the load-bearing one. Two definitions of "sink" that agree today is a
    latent bug, not redundancy.
    """
    return [not scenario_map[k].get("is_coachable", True) for k in keys]


def cosine_sims(Q: np.ndarray, D: np.ndarray) -> np.ndarray:
    """(n_q, n_d) cosine similarity matrix.

    Renormalises both sides even though preprocessing.embedder already returns
    L2-normalised vectors. That is deliberate: it keeps the +1e-10 guard from
    layer_b.assign_scenarios, so results stay bit-identical to the calibrated
    path, and it makes the function safe on hand-built test vectors that are not
    normalised.
    """
    Q = np.asarray(Q, dtype=float)
    D = np.asarray(D, dtype=float)
    Q_norm = Q / (np.linalg.norm(Q, axis=1, keepdims=True) + 1e-10)
    D_norm = D / (np.linalg.norm(D, axis=1, keepdims=True) + 1e-10)
    return Q_norm @ D_norm.T


def topk_pick(
    sims: np.ndarray,
    keys: list[str],
    is_sink_arr: list[bool],
    cap: int,
    margin: float,
    restrict_to: set[int] | None = None,
) -> list[str] | None:
    """Rank `keys` by `sims`, keep entries within `margin` of the best among the
    (optionally restricted) non-sink candidates, capped at `cap`. Always keeps at
    least the best. Returns None if no candidate survives the sink/restrict
    filter -- the caller decides what that means.

    Moved verbatim from v1/layer_b._topk_pick. The None return is why Layer D can
    reuse this: layer_b treats None as "fall back", Layer D treats it as "this is
    not a signal at all".
    """
    order = np.argsort(sims)[::-1]
    candidates = [
        int(j) for j in order
        if not is_sink_arr[int(j)] and (restrict_to is None or int(j) in restrict_to)
    ]
    if not candidates:
        return None
    best_j = candidates[0]
    cutoff = margin * float(sims[best_j])
    kept = [keys[j] for j in candidates[:cap] if float(sims[j]) >= cutoff]
    return kept or [keys[best_j]]


def flat_pick(
    sims: np.ndarray,
    keys: list[str],
    is_sink_arr: list[bool],
    cap: int,
    margin: float,
) -> list[str]:
    """assign_scenarios's own per-pair rule on an arbitrary similarity vector:
    sink short-circuit first, then relative margin.

    Moved verbatim from v1/layer_b._flat_pick. Note the short-circuit FILES to the
    sink (returns it as the sole match) rather than rejecting. That is correct for
    Layer B, which must assign every pair somewhere; a consumer that is allowed to
    reject should use topk_pick and handle None instead.
    """
    order = np.argsort(sims)[::-1]
    best_j = int(order[0])
    if is_sink_arr[best_j]:
        return [keys[best_j]]
    cutoff = margin * float(sims[best_j])
    kept = [
        keys[int(j)] for j in order[:cap]
        if float(sims[int(j)]) >= cutoff and not is_sink_arr[int(j)]
    ]
    return kept or [keys[best_j]]
