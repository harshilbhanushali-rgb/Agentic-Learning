# HANDOFF — Layer A clustering trial (2026-08-16) — **CLOSED**

The trial this document was written to hand off is **DONE**. All 11 arms ran, the gate and every
pre-registered failure condition were evaluated in code, the objective-shape audit ran, and the
blinded reading ran. **Verdict, artifacts and caveats live in two places, both of which supersede
this file:**

- `docs/superpowers/specs/2026-08-16-layer-a-clustering-method-design.md` → "Status update
  (2026-08-16)" — the full result, per-arm table, and everything the evidence does NOT support.
- `CLAUDE.md` → "Layer A clustering: 11 arms, and the ONE that beat the incumbent is a
  noise-rescue (2026-08-16)".

## One-paragraph result

**`rescue_centroid` satisfies both S1 and S2; nothing else does.** Admitting an HDBSCAN-noise
turn into its nearest surviving cluster iff `cos(t, centroid_c) >= p25({cos(m, centroid_c)})`
scores **28/38 = 74%** against the incumbent's **20/38 = 53%** (sign test **p=0.008, +8/−0**),
lifts substantive-turn coverage **45.1% → 67.6%**, clears the UMAP-seed band (jitter max 45%),
and beats its mandatory volume-matched placebo (8%) — so the gain is the SELECTION, not the
volume. Its added turns beat random **10 of 10** in a blinded reading, and a **seed re-test**
(closing a real gap in F5) reproduces the lift on two other UMAP bases: **+8/+9/+9 scenarios at
seeds 42/1/7**, significant at each, with rescued (24–28/38) and unrescued (15–20/38) ranges
that do not overlap. **But the gate is partly this arm's own objective function** (it is the
only arm whose gate and lexical columns diverge), so **cite the LIFT (~+8–9 scenarios, ~+23
coverage points), never the 74% level** — that level is seed-42-flattered. **Everything is gemini@3072 turn mode;
production is bge@768 clause mode, so no production change may cite these numbers alone.**

## What changed on disk

New, all read-only and free:
- `Brain/calibration/clustering_bench.py` — the 11-arm harness (was written-but-never-run at
  handoff; five review items fixed, a `--stage mirror` split out so no process does two UMAP
  fits, a members sidecar added, the CPM γ grid widened with an endpoint warning).
- `Brain/tests/test_clustering_bench.py` — 22 tests over the pure helpers. All pass.
- `Brain/calibration/clustering_objective_audit.py` — the three-objective re-scoring.
- `Brain/calibration/read_clustering_samples.py` — blinded reading, incl. `--added` mode.
- Artifacts: `clustering_bench.json`, `clustering_bench_members.json`,
  `clustering_objective_audit.json`, `turn_content_free.json`, `clustering_bench_umap42.npy`,
  `clustering_samples_{blind.txt,key.json}`. Logs `logs/clustering_bench_*.log`.

Nothing in `v1/`, `v2/`, `shared/`, `preprocessing/` or `tuning.yaml` was touched.

## If you pick this up next

The two live threads, in priority order:

1. **Re-run `rescue_centroid` in the PRODUCTION space (bge@768, clause unit)** before proposing
   any `tuning.yaml` key. The rule is a per-cluster percentile so it transfers in form, but the
   noise pool and the centroid band are both different there, and every threshold in this repo
   that moved between spaces moved a lot.
2. **The 47% noise is only half-answered.** `rescue_centroid` recovers noise into EXISTING
   scenarios and cannot create new ones — the transfer gate makes that true by construction. The
   diagnostic found **268 subject-bearing noise-only clusters** that no arm in this trial could
   admit. Reaching them needs new scenarios, which needs adjudication, which costs chat calls.

Reusable regardless of direction: the `--added` reading mode (for any arm that modifies rather
than re-partitions), and `clustering_objective_audit.py`'s pattern of re-scoring the SAME
populations under a rival's objective — run it before believing any future arm comparison here.
