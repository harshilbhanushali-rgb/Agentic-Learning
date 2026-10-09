#!/usr/bin/env python3
"""Do scenarios differ enough in internal coherence to be worth testing? (free)

THE HYPOTHESIS THIS SERVES. Every Layer C attempt assumed the SCENARIOS were sound and the
CRITERIA were the problem. Nobody tested the scenarios. If a scenario actually contains
several distinct situations, its rubric describes an AVERAGE of them: a response to
situation 1 satisfies the situation-1 milestones and misses the imported ones, and an
unrelated rubric scores nearly as well because both are vague averages. That would produce
the measured 0.114-vs-0.090 directly, and Layer A -- not Layer C -- would be the lever.

A suggestive fingerprint exists in the 100-call run: 141 full hits against 374 PARTIAL
hits, 2.7 partials per full. That is what you would expect if rubrics carry milestones
belonging to situations other than the one being scored.

Precedent that the failure mode is real at a level up: a client_discovery_and_requirements
primary topic once fused 21 of 81 coachable scenarios -- budget, ATS integration, job
boards, URL config, market landscape -- and tighten_coachable_groups fixed it. That fix
operated on PRIMARY TOPICS. Nobody has looked inside the scenarios themselves.

PINNED BEFORE LOOKING AT ANY NUMBER (no spec file, so it is pinned here):

  metric        mean cosine of each member vector to its scenario centroid. Higher = tighter.
                Reported for BOTH populations, because they answer different questions:
                  triggers  -- does this scenario cover ONE client situation?
                  responses -- does Layer C build the rubric from ONE kind of answer?
                The hypothesis is about situations, so TRIGGERS is the primary metric and
                responses is the secondary read.
  split         median of the primary metric, over coachable scenarios with >= 8 triggers.
                Scenarios below that are too thin for a stable centroid and are reported
                separately rather than silently dropped into a half.
  GO / NO-GO    proceed to the paid discrimination half ONLY if the tight and loose halves
                differ by >= 0.05 mean cosine. Below that the split is not a split, and
                spending ~400 calls to compare two halves that are the same thing is the
                mistake this script exists to prevent.

Zero Gemma, zero writes, read-only connection. Embeddings are local and cached.

Usage (from Brain/, venv active):
    python calibration/scenario_coherence.py
"""
from __future__ import annotations

import json
import sys

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

MIN_TRIGGERS = 8          # below this a centroid is not stable enough to rank on
GO_NO_GO_GAP = 0.05       # required separation between halves to justify the paid half


def coherence(vectors: np.ndarray) -> float:
    """Mean cosine of each member to the centroid. 1.0 = identical, 0 = unrelated.

    Distance-to-centroid rather than mean PAIRWISE cosine: both measure spread, but the
    centroid is the thing Layer B actually matches against and Layer C actually clusters
    around, so it is the dispersion the pipeline experiences.
    """
    if len(vectors) < 2:
        return float("nan")
    v = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10)
    c = v.mean(axis=0)
    c /= np.linalg.norm(c) + 1e-10
    return float((v @ c).mean())


def main() -> None:
    from config import load_config
    from calibration import score_naren_ceiling as snc
    from calibration.probe_retrieval_gate import _load_pool
    from preprocessing import embedder

    conn = snc._connect_read_only(load_config().database_url)
    try:
        # _load_pool gives trigger AND response text plus is_coachable in one query.
        # storage.get_responses_for_scenario_multilabel does NOT return trigger_text, which
        # is the population the hypothesis is actually about.
        pool = _load_pool(conn)
    finally:
        conn.close()

    by_scenario: dict[str, list[dict]] = {}
    for p in pool:
        if p["is_coachable"] and p["scenario_key"]:
            by_scenario.setdefault(p["scenario_key"], []).append(p)
    print(f"coachable scenarios with pairs: {len(by_scenario)}"
          f"   ({sum(len(v) for v in by_scenario.values())} pairs)")

    rows = []
    for i, (key, pairs) in enumerate(sorted(by_scenario.items()), 1):
        triggers = [p["trigger_text"] for p in pairs if (p.get("trigger_text") or "").strip()]
        responses = [p["response_text"] for p in pairs if (p.get("response_text") or "").strip()]
        if i % 20 == 0:
            print(f"  ...{i}/{len(by_scenario)}", flush=True)
        rows.append({
            "scenario_key": key,
            "n_triggers": len(triggers),
            "n_responses": len(responses),
            "trigger_coherence": coherence(embedder.embed_query_matrix(triggers))
            if len(triggers) >= 2 else float("nan"),
            "response_coherence": coherence(embedder.embed_document_matrix(responses))
            if len(responses) >= 2 else float("nan"),
        })

    scored = [r for r in rows if r["n_triggers"] >= MIN_TRIGGERS
              and not np.isnan(r["trigger_coherence"])]
    thin = [r for r in rows if r not in scored]
    print(f"\nrankable (>= {MIN_TRIGGERS} triggers): {len(scored)}"
          f"   too thin, reported separately: {len(thin)}")

    scored.sort(key=lambda r: r["trigger_coherence"])
    tc = np.array([r["trigger_coherence"] for r in scored])
    med = float(np.median(tc))
    loose, tight = scored[:len(scored) // 2], scored[len(scored) // 2:]
    lo = float(np.mean([r["trigger_coherence"] for r in loose]))
    hi = float(np.mean([r["trigger_coherence"] for r in tight]))

    print(f"\ntrigger coherence  min {tc.min():.3f}  p25 {np.percentile(tc,25):.3f}"
          f"  median {med:.3f}  p75 {np.percentile(tc,75):.3f}  max {tc.max():.3f}")
    print(f"  LOOSE half mean {lo:.3f}  ({len(loose)} scenarios)")
    print(f"  TIGHT half mean {hi:.3f}  ({len(tight)} scenarios)")
    print(f"  separation      {hi - lo:.3f}   (need >= {GO_NO_GO_GAP} to proceed)")

    print("\n5 LOOSEST -- read these, a low number should look like a mixed scenario")
    for r in loose[:5]:
        print(f"  {r['trigger_coherence']:.3f}  n={r['n_triggers']:<4} {r['scenario_key']}")
    print("\n5 TIGHTEST")
    for r in tight[-5:]:
        print(f"  {r['trigger_coherence']:.3f}  n={r['n_triggers']:<4} {r['scenario_key']}")

    out = ARTIFACTS_DIR / "scenario_coherence.json"
    out.write_text(json.dumps({
        "min_triggers": MIN_TRIGGERS, "median": med, "separation": hi - lo,
        "loose": [r["scenario_key"] for r in loose],
        "tight": [r["scenario_key"] for r in tight],
        "rows": rows,
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")

    if hi - lo >= GO_NO_GO_GAP:
        print(f"\nGO: separation {hi - lo:.3f} >= {GO_NO_GO_GAP}. The halves are genuinely"
              "\ndifferent, so comparing their discrimination is a real comparison.")
    else:
        print(f"\nNO-GO: separation {hi - lo:.3f} < {GO_NO_GO_GAP}. The halves are the same"
              "\nthing. Do NOT spend the paid half -- it would compare a split that is not"
              "\na split, and any difference it found would be noise.")


if __name__ == "__main__":
    main()
