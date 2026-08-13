#!/usr/bin/env python3
"""Is a hosted embedder actually better than local bge, on THIS corpus?

Pre-registered 2026-08-13, before any call was spent.

WHY THIS AND NOT A VIBE CHECK. Embeddings decide which topics exist, which client
sentence is filed under which topic, and which coaching moves count as the same move.
Swapping them is not a config change: Pinecone narens-brain is a 768-dim index, and every
threshold in tuning.yaml was calibrated against bge's cosine bands. So the swap has to
earn itself against ground truth that already exists, not against an impression.

THE GROUND TRUTH. artifacts/labeled_trigger_quality_sample.json -- 150 real pairs a Gemma
pass labelled coachable / not-coachable, with the bge vectors and signal values persisted.
Two of its signals are purely embedding-derived and have published numbers to beat:

  sink_real_margin           AUC 0.437 raw. NOT "worse than chance" -- the signal is
                             inverted by construction (higher = more filler-like), so it
                             is direction-correct and worth 0.563 corrected. The recorded
                             diagnosis is explicitly an embedding-space failure: real and
                             sink centroids "sit too close together in embedding space
                             relative to any one trigger to leave a usable margin".
  trigger_response_coupling  AUC 0.617. Plain cosine between a pair's own two vectors.

PRE-REGISTERED PASS MARKS. sink_real_margin corrected >= 0.65, coupling >= 0.70, and the
trigger-vs-scenario cosine spread wider than bge's 0.117. TWO of the three = the space
improved. Fixed here so they cannot be revised after seeing numbers.

MATRYOSHKA. Gemini's vector is Matryoshka-trained, so 1536 and 768 are truncations of the
same 3072 -- ONE call scores every width. That turns "is 3072 worth a new Pinecone index
and a 867 MiB Layer A matrix" into a measurement instead of an assumption.

Zero writes to Postgres: the connection is read-only. Zero Gemma. Only the embedding API
is spent, ~5 requests.

Usage (from Brain/, venv active):
    python calibration/compare_embedders.py --probe    # 1 request: does the API take
                                                       # output_dimensionality, and what
                                                       # width comes back?
    python calibration/compare_embedders.py --run      # ~5 requests, the full comparison
    python calibration/compare_embedders.py --load artifacts/embedder_compare.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

_SAMPLE = ARTIFACTS_DIR / "labeled_trigger_quality_sample.json"

# Published, measured against this exact sample with bge-base.
BASELINE = {"sink_real_margin_corrected": 0.563,
            "trigger_response_coupling": 0.617,
            "band_spread": 0.117}
PASS = {"sink_real_margin_corrected": 0.65,
        "trigger_response_coupling": 0.70}

WIDTHS = (3072, 1536, 768)


# --- pure helpers (unit-tested) ---------------------------------------------------------

def auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Mann-Whitney AUC with average ranks for ties.

    Written out rather than imported so the number cannot change under us with a library
    version -- the whole point is comparing against a figure recorded weeks ago.
    """
    scores, labels = np.asarray(scores, float), np.asarray(labels, bool)
    n_pos, n_neg = int(labels.sum()), int((~labels).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), float)
    ranks[order] = np.arange(1, len(scores) + 1)
    # Average ranks within tied groups, or ties silently bias the statistic.
    s_sorted = scores[order]
    i = 0
    while i < len(s_sorted):
        j = i
        while j + 1 < len(s_sorted) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = ranks[order[i:j + 1]].mean()
        i = j + 1
    return float((ranks[labels].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def corrected(value: float) -> float:
    """An inverted signal is informative, not useless. 0.437 and 0.563 carry equal
    separating power; only the sign of the relationship differs."""
    return float(max(value, 1 - value))


def truncate(mat: np.ndarray, width: int) -> np.ndarray:
    """Matryoshka truncation: slice, then RENORMALISE.

    Renormalising is not optional. Gemini normalises only its full-width output, and every
    cosine in this codebase is a bare dot product -- skipping this would not raise, it
    would quietly shift every similarity."""
    out = np.asarray(mat, np.float32)[:, :width]
    return out / (np.linalg.norm(out, axis=1, keepdims=True) + 1e-10)


def band(sims: np.ndarray) -> dict:
    """Best-match cosine distribution. The spread is the number that matters: a squashed
    band is why relative_margin was so fiddly and why so much gets filed as junk."""
    p10, p50, p90 = (float(np.percentile(sims, q)) for q in (10, 50, 90))
    return {"p10": p10, "p50": p50, "p90": p90, "spread": p90 - p10}


def score_space(trig: np.ndarray, resp: np.ndarray, sinks: np.ndarray,
                reals: np.ndarray, labels: np.ndarray) -> dict:
    """Every published signal, recomputed in one embedding space."""
    coupling = np.einsum("ij,ij->i", trig, resp)
    margin = (sinks @ trig.T).max(axis=0) - (reals @ trig.T).max(axis=0)
    best = np.vstack([sinks, reals]) @ trig.T
    raw_margin_auc = auc(margin, labels)
    return {
        "trigger_response_coupling": auc(coupling, labels),
        "sink_real_margin_raw": raw_margin_auc,
        "sink_real_margin_corrected": corrected(raw_margin_auc),
        "band": band(best.max(axis=0)),
    }


# --- impure ------------------------------------------------------------------------------

def _probe(dims: int) -> dict:
    """Does the API accept output_dimensionality, and what width comes back?

    Runs TWICE -- with the parameter and without -- because one call cannot tell
    "the parameter was rejected" from "the request failed for an unrelated reason".
    The first version of this printed a confident "will truncate client-side" when the
    real fault was a garbage-collected client in our own code: a local bug reported as an
    API capability. Only a parameter-specific error may be read as a rejection.
    """
    from config import load_config
    from preprocessing.embedder import _gemini_client
    from shared.tuning import load_tuning

    cfg, keys = load_tuning().embedding, load_config().gemma_api_keys
    client = _gemini_client(keys[0])

    def call(config: dict) -> tuple[int | None, str | None]:
        try:
            resp = client.models.embed_content(
                model=cfg.gemini_model, contents=["a short probe sentence"], config=config)
            return len(resp.embeddings[0].values), None
        except Exception as e:                                # noqa: BLE001
            return None, str(e)

    print(f"probe 1: {cfg.gemini_model} WITHOUT output_dimensionality ...", flush=True)
    native, native_err = call({"task_type": "RETRIEVAL_DOCUMENT"})
    print(f"  {'native width = ' + str(native) if native else 'FAILED: ' + str(native_err)}")

    print(f"probe 2: same model WITH output_dimensionality={dims} ...", flush=True)
    got, err = call({"task_type": "RETRIEVAL_DOCUMENT", "output_dimensionality": dims})
    print(f"  {'returned width = ' + str(got) if got else 'FAILED: ' + str(err)}")

    if native is None and got is None:
        print("\n  Both calls failed -- this is NOT evidence about the parameter."
              "\n  Fix the error above before concluding anything.")
        verdict = "inconclusive"
    elif got is not None:
        verdict = "accepted"
        print(f"\n  output_dimensionality ACCEPTED. Native is {native}; "
              f"request any width directly.")
    else:
        verdict = "rejected"
        print(f"\n  Parameter rejected but the plain call worked -- request the native "
              f"{native} and truncate client-side.")
    return {"verdict": verdict, "native_width": native, "requested": dims,
            "returned_width": got, "native_error": native_err, "param_error": err}


def _embed_gemini(texts: list[str], prefix: str) -> np.ndarray:
    from preprocessing import embedder
    return np.asarray(embedder._encode_gemini(texts, prefix), dtype=np.float32)


def _scenarios() -> tuple[list[str], list[bool]]:
    """Scenario texts plus their coachable flag, over a read-only connection."""
    from config import load_config
    from calibration import score_naren_ceiling as snc
    from shared import scenario_vectors, storage

    conn = snc._connect_read_only(load_config().database_url)
    try:
        rows = storage.get_scenarios(conn)
    finally:
        conn.close()
    return ([scenario_vectors.scenario_text(s) for s in rows],
            [bool(s.get("is_coachable")) for s in rows])


def run() -> dict:
    rows = json.loads(_SAMPLE.read_text(encoding="utf-8-sig"))
    labels = np.array([bool(r["coachable"]) for r in rows])
    print(f"labelled sample: {len(rows)} pairs, {int(labels.sum())} coachable /"
          f" {int((~labels).sum())} not", flush=True)

    scen_texts, scen_coachable = _scenarios()
    is_real = np.array(scen_coachable)
    print(f"scenarios: {len(scen_texts)} ({int(is_real.sum())} real /"
          f" {int((~is_real).sum())} sink)", flush=True)

    out = {"n_pairs": len(rows), "n_scenarios": len(scen_texts), "baseline_published": BASELINE}

    # --- bge baseline, from the vectors stored in the artifact (exact reproduction) ---
    bge_t = np.asarray([r["trigger_vec"] for r in rows], dtype=np.float32)
    bge_r = np.asarray([r["response_vec"] for r in rows], dtype=np.float32)
    from preprocessing import embedder
    bge_s = embedder.embed_document_matrix(scen_texts)      # local, cached, free
    norm = lambda m: m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-10)
    out["bge_768"] = score_space(norm(bge_t), norm(bge_r), norm(bge_s[~is_real]),
                                 norm(bge_s[is_real]), labels)

    # --- gemini, one call per population, every width off the same vectors ---
    n_texts = len(rows) * 2 + len(scen_texts)
    print(f"\nembedding {n_texts} texts with gemini "
          f"(~{-(-n_texts // 100)} requests) ...", flush=True)
    # Triggers go in query-side, responses and scenarios document-side -- the same
    # asymmetry production uses. Gemini expresses it as a task type rather than a text
    # prefix, and _encode_gemini does that translation.
    from preprocessing.embedder import _QUERY_PREFIX
    g_t = _embed_gemini([r["trigger_text"] for r in rows], _QUERY_PREFIX)
    g_r = _embed_gemini([r["response_text"] for r in rows], "")
    g_s = _embed_gemini(scen_texts, "")
    out["gemini_native_width"] = int(g_t.shape[1])

    for w in WIDTHS:
        if w > g_t.shape[1]:
            continue
        out[f"gemini_{w}"] = score_space(truncate(g_t, w), truncate(g_r, w),
                                         truncate(g_s[~is_real], w),
                                         truncate(g_s[is_real], w), labels)
    return out


def report(p: dict) -> None:
    print("\n" + "=" * 76)
    print(f"EMBEDDER COMPARISON -- {p['n_pairs']} labelled pairs, "
          f"{p['n_scenarios']} scenarios")
    print("=" * 76)
    print(f"\n{'space':<14} {'margin(corr)':>13} {'coupling':>10} "
          f"{'p10':>7} {'p50':>7} {'p90':>7} {'spread':>8}")
    for key in ["bge_768"] + [f"gemini_{w}" for w in WIDTHS]:
        s = p.get(key)
        if not s:
            continue
        b = s["band"]
        print(f"{key:<14} {s['sink_real_margin_corrected']:>13.3f}"
              f" {s['trigger_response_coupling']:>10.3f}"
              f" {b['p10']:>7.3f} {b['p50']:>7.3f} {b['p90']:>7.3f} {b['spread']:>8.3f}")

    print(f"\nPUBLISHED bge baseline: margin(corr) {BASELINE['sink_real_margin_corrected']}"
          f"  coupling {BASELINE['trigger_response_coupling']}"
          f"  spread {BASELINE['band_spread']}")

    print("\nPRE-REGISTERED VERDICT (2 of 3 required)")
    for key in [f"gemini_{w}" for w in WIDTHS]:
        s = p.get(key)
        if not s:
            continue
        checks = {
            "margin>=0.65": s["sink_real_margin_corrected"] >= PASS["sink_real_margin_corrected"],
            "coupling>=0.70": s["trigger_response_coupling"] >= PASS["trigger_response_coupling"],
            "spread wider": s["band"]["spread"] > BASELINE["band_spread"],
        }
        n = sum(checks.values())
        marks = "  ".join(f"{k}:{'Y' if v else 'n'}" for k, v in checks.items())
        print(f"  {key:<13} {n}/3  {marks}   -> {'PASS' if n >= 2 else 'no'}")

    print("\nDIMENSION DECISION: ship 768 unless a wider vector wins by more than 0.02")
    base = p.get("gemini_768")
    top = p.get(f"gemini_{p.get('gemini_native_width', 3072)}")
    if base and top:
        d = top["sink_real_margin_corrected"] - base["sink_real_margin_corrected"]
        print(f"  native minus 768 on margin(corr) = {d:+.3f}"
              f"  -> {'wider width earns its cost' if d > 0.02 else 'ship 768'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--load")
    ap.add_argument("--out", default=str(ARTIFACTS_DIR / "embedder_compare.json"))
    a = ap.parse_args()

    if a.load:
        report(json.loads(Path(a.load).read_text(encoding="utf-8-sig")))
        return
    if a.probe:
        from shared.tuning import load_tuning
        _probe(load_tuning().embedding.gemini_dimensions)
        return
    if not a.run:
        print("Pass --probe (1 request), --run (~5 requests), or --load.")
        return

    payload = run()
    Path(a.out).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nwrote {a.out}")
    report(payload)


if __name__ == "__main__":
    main()
