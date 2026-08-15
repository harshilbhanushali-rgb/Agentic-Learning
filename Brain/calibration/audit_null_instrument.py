#!/usr/bin/env python3
"""Is the coherence-vs-null test measuring situation quality, or just turn shape? (free)

Spec: docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md

WHY THIS EXISTS. The spec already established that coherence-lift-over-a-null is NOT a
cluster-quality gate at CLUSTER level -- `corr(lift, content-free fraction) = +0.527`, junk
clusters averaged +0.160 lift against real ones' +0.107, because a pile of "that's huge" is
lexically tighter than a real discussion of markets. It then asserted the metric "remains
valid at SCENARIO level, where members are whole turns".

THAT ASSERTION WAS NEVER TESTED. It is an argument, not a measurement, and every conclusion
drawn from the scenario-level null test rests on it -- including the 21/68 finding that
started this entire effort and the 16/82 vs 11/38 comparison built on it.

One observation already suggests it is wrong: `compensation_and_variable_structuring` is a
cluster of JOB INTERVIEWS misfiled as a client scenario, and it scores the 3rd highest lift of
all 38. A metric that ranks a non-client conversation near the top is measuring something
other than "is this a coaching situation".

THE TEST. Rebuild both arms' matched memberships exactly as null_test_taxonomy.py does, then
correlate each scenario's lift against two properties of its members that have nothing to do
with whether it is a good coaching scenario:

  content-free share   the same `is_substantive` proxy used throughout this effort
  mean word count      shorter turns embed tighter, mechanically

If lift tracks either one, the metric is measuring turn SHAPE and the scenario-level claim
falls with the cluster-level one. Reported for BOTH taxonomies, since a confound in the
instrument invalidates both arms equally and the comparison between them separately.

Zero chat calls, zero embedding requests (all cached), one read-only DB query.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/audit_null_instrument.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

NULL_ARTIFACT = ARTIFACTS_DIR / "null_test_taxonomy.json"
OUT = ARTIFACTS_DIR / "null_instrument_audit.json"


def _corr(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return float("nan")
    return float(np.corrcoef(a[ok], b[ok])[0, 1])


def main() -> None:
    from config import load_config
    from shared import cluster_evidence
    from preprocessing.transcript_parser import parse_transcript, load_roster
    from v2.layer_a import build_client_pool
    from calibration.trial_pool_unit_gemini import embed_cached
    from calibration.validate_taxonomy_vs_layerd import load_old, load_new, match
    import psycopg

    prior = json.loads(NULL_ARTIFACT.read_text(encoding="utf-8-sig"))
    cfg = load_config()
    url = cfg.database_url + ("&" if "?" in cfg.database_url else "?") + "hostaddr=18.138.49.39"
    with psycopg.connect(url, autocommit=True, connect_timeout=20) as conn:
        old = load_old(conn)
    new = load_new()

    turns = []
    for f in sorted(Path("recordings").glob("*.txt")):
        turns.extend(parse_transcript(str(f), cfg.joveo_speakers_lower,
                                      cfg.naren_name_lower, roster=load_roster(str(f))))
    texts, _ = build_client_pool(turns, unit="turn")
    print(f"{len(texts)} CLIENT turns")

    vecs = embed_cached(texts, workers=20)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    emb = lambda t: embed_cached(t, workers=20)

    thin = np.array([not cluster_evidence.is_substantive(t, 5) for t in texts], dtype=float)
    wc = np.array([len(t.split()) for t in texts], dtype=float)

    payload = {}
    for name, tax in (("old_matched", old), ("new_matched", new)):
        m = match(vecs, tax, emb)
        member: dict[str, list[int]] = {}
        for i, b in enumerate(m["best"]):
            if m["accepted"][i]:
                member.setdefault(m["keys"][b], []).append(i)
        lift_by = {r["key"]: r["lift"] for r in prior[name]["rows"] if r["rankable"]}
        rows = []
        for k, lf in lift_by.items():
            idx = member.get(k, [])
            if not idx:
                continue
            rows.append({"key": k, "lift": lf, "n": len(idx),
                         "thin": float(thin[idx].mean()),
                         "mean_words": float(wc[idx].mean()),
                         "median_words": float(np.median(wc[idx]))})
        lifts = [r["lift"] for r in rows]
        c_thin = _corr(lifts, [r["thin"] for r in rows])
        c_wc = _corr(lifts, [r["mean_words"] for r in rows])
        c_n = _corr(lifts, [r["n"] for r in rows])
        payload[name] = {"rows": rows, "corr_lift_contentfree": c_thin,
                         "corr_lift_meanwords": c_wc, "corr_lift_size": c_n}
        print(f"\n=== {name} ({len(rows)} rankable scenarios) ===")
        print(f"  corr(lift, content-free share) = {c_thin:+.3f}"
              f"   <- cluster level was +0.527")
        print(f"  corr(lift, mean word count)    = {c_wc:+.3f}")
        print(f"  corr(lift, n members)          = {c_n:+.3f}")
        top = sorted(rows, key=lambda r: -r["lift"])[:5]
        bot = sorted(rows, key=lambda r: r["lift"])[:5]
        print("  HIGHEST lift:")
        for r in top:
            print(f"    {r['lift']:+.3f}  content-free {r['thin']:>5.1%}  "
                  f"mean {r['mean_words']:>5.1f}w  median {r['median_words']:>4.0f}w  {r['key'][:44]}")
        print("  LOWEST lift:")
        for r in bot:
            print(f"    {r['lift']:+.3f}  content-free {r['thin']:>5.1%}  "
                  f"mean {r['mean_words']:>5.1f}w  median {r['median_words']:>4.0f}w  {r['key'][:44]}")

    OUT.write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
