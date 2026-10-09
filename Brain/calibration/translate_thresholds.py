#!/usr/bin/env python3
"""What would each cosine threshold have to become under a different embedder?

Zero API calls. Reads the Gemini vectors already paid for in
artifacts/embedder_compare_vectors.npz and recomputes the bge side locally.

WHY MOST OF tuning.yaml NEEDS NOTHING. The standing rule -- "every knob is a property of
the data (fraction of calls, cosine distance, relative margin, percentile)" -- means most
keys are RANK based. A percentile or a fraction-of-calls does not care that Gemini's cosine
band sits at p50 0.686 where bge's sits at 0.558. Those are scale-invariant and are left
alone here deliberately, not overlooked.

WHAT DOES NEED WORK is the handful of keys expressed as an ABSOLUTE cosine, plus the ratio
tests, which are sensitive to how COMPRESSED the band is rather than where it sits:

    merge_cosine_threshold        0.85   absolute
    primary_topic_merge_threshold 0.75   absolute
    relative_margin               0.95   ratio, band-compression sensitive
    primary_topic_relative_margin 0.95   ratio

THE TRANSLATION METHOD. A threshold's meaning is not its number, it is how SELECTIVE it is
against the distribution it is applied to. So: find the percentile the current value sits
at in the bge distribution, and read off the value at that same percentile in the Gemini
distribution. That preserves selectivity across a change of scale.

relative_margin is derived instead of translated, because its original calibration is on
record: 0.95 x p50 = 0.522 landed near p25 of the best-match distribution. The rule is
margin ~= p25/p50, so it is recomputed directly.

WHAT THIS CANNOT DO. merge_cosine_threshold was never chosen by a formula -- it was chosen
by READING what each threshold fused ("at 0.80 it fused campaigns + sales team + brand +
markets + vendors"). This gives a defensible starting value, not a validated one, and the
scenario-vector population here is only a proxy for Layer A's raw topic centroids. It IS
the exact population for tighten_coachable_groups and match_existing_primary_topic, which
reuse the same key.

Usage (from Brain/, venv active -- needs the DB for scenario TEXT, read-only):
    python calibration/translate_thresholds.py
"""
from __future__ import annotations

import sys

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

_VECS = ARTIFACTS_DIR / "embedder_compare_vectors.npz"

# key -> (current value, which population it is applied to)
ABSOLUTE = {
    "layer_a.merge_cosine_threshold": (0.85, "scenario-vector pairs"),
    "layer_a.primary_topic_merge_threshold": (0.75, "scenario-vector pairs"),
}


def _norm(m: np.ndarray) -> np.ndarray:
    return m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-10)


def pairwise_upper(vecs: np.ndarray) -> np.ndarray:
    """Every distinct pair's cosine, which is the population a merge threshold cuts."""
    sims = _norm(vecs) @ _norm(vecs).T
    iu = np.triu_indices(len(vecs), k=1)
    return sims[iu]


def percentile_of(value: float, dist: np.ndarray) -> float:
    """Where a threshold sits in its own distribution -- its actual selectivity."""
    return float((dist < value).mean() * 100)


def band(x: np.ndarray) -> dict:
    return {p: float(np.percentile(x, p)) for p in (10, 25, 50, 75, 90)}


def _fmt(b: dict) -> str:
    return "  ".join(f"p{p}={v:.3f}" for p, v in b.items())


def main() -> None:
    if not _VECS.exists():
        print(f"missing {_VECS} -- run calibration/compare_embedders.py --run first")
        return

    z = np.load(_VECS)
    g_scen, g_trig = z["scenario"], z["trigger_query"]
    print(f"loaded gemini vectors: {g_scen.shape[0]} scenarios, {g_trig.shape[0]} triggers"
          f", dim {g_scen.shape[1]}")

    from calibration import compare_embedders as ce
    from preprocessing import embedder

    scen_texts, _ = ce._scenarios()
    if len(scen_texts) != g_scen.shape[0]:
        print(f"WARNING: {len(scen_texts)} scenarios now vs {g_scen.shape[0]} when the"
              " vectors were saved -- the taxonomy changed, translation is approximate.")
    b_scen = embedder.embed_document_matrix(scen_texts)      # local, cached, free

    print("\n" + "=" * 78)
    print("ABSOLUTE COSINE KEYS -- translated by matching SELECTIVITY, not the number")
    print("=" * 78)
    b_pairs, g_pairs = pairwise_upper(b_scen), pairwise_upper(g_scen)
    print(f"\npairwise scenario cosine")
    print(f"  bge    {_fmt(band(b_pairs))}")
    print(f"  gemini {_fmt(band(g_pairs))}")

    for key, (current, population) in ABSOLUTE.items():
        pct = percentile_of(current, b_pairs)
        translated = float(np.percentile(g_pairs, pct))
        print(f"\n  {key}")
        print(f"    applied to        : {population}")
        print(f"    current (bge)     : {current:.3f}  = p{pct:.1f} of the bge distribution")
        print(f"    same selectivity  : {translated:.3f}  under gemini")
        print(f"    -> would move {current:.3f} -> {translated:.3f}")

    print("\n" + "=" * 78)
    print("RATIO KEYS -- re-derived from the rule that produced the original value")
    print("=" * 78)
    # layer_b matches a trigger against every scenario; relative_margin keeps everything
    # within margin x best. Its calibration is on record as margin x p50 ~= p25.
    for label, trig, scen in (("bge", _norm(np.asarray(embedder.embed_query_matrix(
                                   [t for t in _trigger_texts()]))), _norm(b_scen)),
                              ("gemini", _norm(g_trig), _norm(g_scen))):
        best = (scen @ trig.T).max(axis=0)
        bd = band(best)
        derived = bd[25] / bd[50]
        print(f"\n  {label:<7} best-match band  {_fmt(bd)}"
              f"   spread={bd[90] - bd[10]:.3f}")
        print(f"          margin = p25/p50 = {derived:.3f}")

    print("\nNOTE: merge_cosine_threshold was originally chosen by READING what each value"
          "\nfused, never by a formula. The number above is a defensible starting point,"
          "\nnot a validated one -- confirm it by reading groups before shipping it.")


def _trigger_texts() -> list[str]:
    import json
    rows = json.loads((ARTIFACTS_DIR / "labeled_trigger_quality_sample.json")
                      .read_text(encoding="utf-8-sig"))
    return [r["trigger_text"] for r in rows]


if __name__ == "__main__":
    main()
