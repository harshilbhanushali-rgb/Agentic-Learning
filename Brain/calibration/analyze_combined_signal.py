#!/usr/bin/env python3
"""Zero-cost calibration script (Approach A of
docs/superpowers/specs/2026-08-05-layer-b-combined-signal-analysis-design.md): checks whether
combining signals already measured against the labeled sink-bound sample beats any single one.

No DB connection, no Gemma call -- reads label_trigger_quality_sample.py's persisted output
(labeled_trigger_quality_sample.json) directly. Every signal so far (concrete_content_density,
sink_real_margin, trigger_response_coupling, response_word_count) was evaluated alone; this script
adds one new derived feature (length_ratio) and checks whether the three strongest carry
complementary or redundant information, then fits a combined score to see whether stacking them
clears a materially higher bar than response_word_count's own AUC (0.853, the best single signal
found so far).

Usage (from Brain/, venv active):
    python calibration/analyze_combined_signal.py [labeled_sample.json]
    (defaults to labeled_trigger_quality_sample.json, the file label_trigger_quality_sample.py
    already wrote)
"""
from __future__ import annotations
import json
import random
import sys
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np
from scipy.stats import pearsonr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, recall_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

# Brain/ is this file's parent -- put it on sys.path so the shared packages
# (config, shared, v1, v2, preprocessing) resolve whether this script is run
# directly (python calibration/x.py) or imported (from calibration import x).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

from shared import trigger_quality as tq

_CANDIDATE_THRESHOLDS = (0.3, 0.5, 0.7)


def _load_judged(path: Path) -> list[dict]:
    sample = json.loads(path.read_text(encoding="utf-8"))
    return [p for p in sample if p["coachable"] is not None]


def _add_length_ratio(judged: list[dict]) -> None:
    """Mutates each pair in place, adding trigger_word_count and length_ratio."""
    for p in judged:
        trigger_words = tq.content_word_count(p["trigger_text"])
        p["trigger_word_count"] = trigger_words
        p["length_ratio"] = p["response_word_count"] / max(trigger_words, 1)


def _auc(judged: list[dict], field: str) -> float:
    y = [1 if p["coachable"] else 0 for p in judged]
    scores = [p[field] for p in judged]
    return roc_auc_score(y, scores)


def _print_correlation(judged: list[dict]) -> None:
    coachable = [p for p in judged if p["coachable"]]
    not_coachable = [p for p in judged if not p["coachable"]]

    def corr(group: list[dict]) -> tuple[float, float]:
        if len(group) < 3:
            return float("nan"), float("nan")
        r, pval = pearsonr(
            [p["response_word_count"] for p in group],
            [p["trigger_response_coupling"] for p in group],
        )
        return r, pval

    r_all, p_all = corr(judged)
    r_c, p_c = corr(coachable)
    r_n, p_n = corr(not_coachable)
    print("\nPearson correlation, response_word_count vs trigger_response_coupling "
          "(checked before combining -- tightly correlated signals buy little, weakly "
          "correlated signals may catch different slices of junk):")
    print(f"  overall       : r={r_all:.3f} (p={p_all:.3f}, n={len(judged)})")
    print(f"  coachable     : r={r_c:.3f} (p={p_c:.3f}, n={len(coachable)})")
    print(f"  not coachable : r={r_n:.3f} (p={p_n:.3f}, n={len(not_coachable)})")


def _percentiles(values: list[float]) -> str:
    return "  ".join(f"p{pct}={np.percentile(values, pct):.3f}" for pct in (10, 25, 50, 75, 90))


def _print_length_ratio(judged: list[dict]) -> None:
    coachable = [p["length_ratio"] for p in judged if p["coachable"]]
    not_coachable = [p["length_ratio"] for p in judged if not p["coachable"]]
    print("\nlength_ratio = content_word_count(response) / max(content_word_count(trigger), 1) "
          "split by label -- targets the short-filler-trigger/long-substantive-response case "
          "directly, unlike raw response length:")
    print("  coachable    :", _percentiles(coachable))
    print("  not coachable:", _percentiles(not_coachable))
    print(f"  AUC = {_auc(judged, 'length_ratio'):.3f}")


def _fit_combined(judged: list[dict]) -> tuple[LogisticRegression, StandardScaler, np.ndarray, np.ndarray]:
    features = ["response_word_count", "trigger_response_coupling", "length_ratio"]
    X = np.array([[p[f] for f in features] for p in judged], dtype=float)
    y = np.array([1 if p["coachable"] else 0 for p in judged])
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    model = LogisticRegression()
    model.fit(X_scaled, y)
    return model, scaler, X_scaled, y


def _print_combined(judged: list[dict]) -> None:
    print("\nCombined score: logistic regression over "
          "{response_word_count, trigger_response_coupling, length_ratio} "
          "(fixed formula once fit, deterministic -- fit on the full 150-pair sample, in-sample "
          "AUC, NOT a claim of held-out generalization; too small to split meaningfully):")

    model, scaler, X_scaled, y = _fit_combined(judged)
    scores = model.predict_proba(X_scaled)[:, 1]
    combined_auc = roc_auc_score(y, scores)

    print(f"  response_word_count alone      AUC = {_auc(judged, 'response_word_count'):.3f}")
    print(f"  trigger_response_coupling alone AUC = {_auc(judged, 'trigger_response_coupling'):.3f}")
    print(f"  length_ratio alone              AUC = {_auc(judged, 'length_ratio'):.3f}")
    print(f"  COMBINED                        AUC = {combined_auc:.3f}")

    print("\n  Precision/recall at candidate probability thresholds:")
    for t in _CANDIDATE_THRESHOLDS:
        pred = (scores >= t).astype(int)
        prec = precision_score(y, pred, zero_division=0)
        rec = recall_score(y, pred, zero_division=0)
        n_flagged = int(pred.sum())
        print(f"    threshold={t:.1f}: precision={prec:.3f} recall={rec:.3f} "
              f"(flags {n_flagged}/{len(y)} as coachable)")

    for p, score in zip(judged, scores):
        p["combined_score"] = float(score)

    rng = random.Random(0)
    print("\n  10 random disagreement pairs (combined_score and label point different "
          "directions at threshold 0.5):")
    disagree = [
        p for p in judged
        if (p["coachable"] and p["combined_score"] < 0.5)
        or (not p["coachable"] and p["combined_score"] >= 0.5)
    ]
    for p in rng.sample(disagree, min(10, len(disagree))):
        print(f"    [{p['pair_id']}] coachable={p['coachable']} score={p['combined_score']:.2f} "
              f"words={p['response_word_count']} coupling={p['trigger_response_coupling']:.2f} "
              f"ratio={p['length_ratio']:.1f}")
        print(f"        trigger : {p['trigger_text'][:100]!r}")
        print(f"        response: {p['response_text'][:150]!r}")


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ARTIFACTS_DIR / "labeled_trigger_quality_sample.json"
    judged = _load_judged(path)
    print(f"Loaded {len(judged)} judged pair(s) from {path} -- no DB or Gemma calls made.")

    _add_length_ratio(judged)
    _print_correlation(judged)
    _print_length_ratio(judged)
    _print_combined(judged)


if __name__ == "__main__":
    main()
