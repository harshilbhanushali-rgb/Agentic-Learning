# Layer C Rubric Depth — Design Spec

**Date:** 2026-07-28
**Status:** Approved, pending implementation plan
**Scope:** `Brain/tuning.yaml`, `Brain/shared/tuning.py`, new `Brain/dry_run_layer_c_clustering.py`. Possible follow-up to `Brain/v2/layer_c.py` gated on this spec's findings.

## Problem

Rubric depth in the first V2 production run (2026-07-27, `baseline_20260728` vs `v2_alpha_20260728`) is thin: 85 coachable scenarios, median milestone depth 2, 20 scenarios have exactly 1 milestone, 3 have 0. Read-only analysis this session (2026-07-28), verified against the live DB with a reproducibility check (0 mismatches between recomputed and stored milestone counts for all 51 V2-clustered scenarios), found:

- 51/85 scenarios successfully use V2 HDBSCAN clause clustering (evidence-backed milestones, `support_calls` populated).
- 34/85 fall back to V1 Gemma free-text milestones (no clustering evidence — `_fallback_v1` in `v2/layer_c.py` replaces the *whole* rubric, never partially; confirmed 0 mixed rubrics in the DB).
  - **28 of the 34** fall back because HDBSCAN finds **zero clusters** in the relevance-filtered clause pool — the dominant cause (82% of fallbacks).
  - 3 fall back because there are too few Naren responses (<2) or too few clauses (<6) to attempt clustering at all — structurally uncoachable by any clustering approach.
  - 3 fall back because clustering succeeds but every candidate cluster fails the call-support gate (`min_milestone_calls_floor: 3`).
- **Diagnostic on the 28 no-cluster scenarios is the key finding**: HDBSCAN reports 100% noise (zero clusters) at *every* clause pool size observed, from 10 clauses up to 680. Several of the largest scenarios (`implementation_feasibility_requests`: 658 clauses, `niche_industry_role_discovery`: 659, `hypothetical_scenario_validation`: 680) have abundant data and a low `min_cluster_size` (13-14) yet still find nothing. This rules out pure data-sparsity as the explanation for the majority of these 28.
- The leading hypothesis: Layer C's milestone clustering runs HDBSCAN directly on raw 768-dimensional bge embeddings with **no dimensionality reduction**, unlike Layer A's topic clustering (`bertopic` + `umap-learn` + `hdbscan`). Density-based clustering is known to fail in raw high-dimensional space (distance concentration), which is consistent with zero clusters persisting even at hundreds of clauses.
- Separately, lowering `min_milestone_calls_floor` from 3 to 2 was tested against the real cluster candidates (not simulated): it rescues the 3 gate-failure scenarios (1-2 milestones each) and adds exactly +1 milestone to 9 already-clustered scenarios. Net effect: 87 → 101 milestones (+16%) across the 51+3 scenarios it touches. It does **not** affect the 28 no-cluster scenarios, since the gate only evaluates once a candidate cluster exists.

## Design

Two independent tracks. They don't conflict — the call-support gate only fires once a cluster exists, so fixing clustering and loosening the gate address non-overlapping failure populations.

### Track B — adopt the floor change now

Change `Brain/tuning.yaml`:

```yaml
layer_c:
  min_milestone_calls_floor: 2  # was 3
```

Update the surrounding comment block to record this session's measurement in the same style as the existing calibration notes: which scenarios are affected (3 rescued from total V1 fallback, 9 gain +1 milestone each), the net effect (87→101, +16%), and the reproducibility check that validated the recomputation (0 mismatches against the live DB across all 51 V2-clustered scenarios). No code change is needed — `cluster_evidence.required_milestone_support` already takes the floor as a parameter.

This is a pure win for the scenarios it touches: 9 of the 12 affected scenarios strictly gain an additional evidence-backed milestone with no tradeoff. The other 3 (`integration_ecosystem_constraints`, `backend_workflow_conceptualization`, `job_role_specification`) currently have MORE milestones via V1 Gemma free-text (3, 3, 3) than they would via V2 clustering at floor=2 (2, 2, 1) — so this is a quantity-for-auditability tradeoff for those three specifically, worth noting in the comment but not a reason to withhold the change, since evidence-backed milestones are the whole point of V2.

### Track A — diagnose the clustering algorithm

New script `Brain/dry_run_layer_c_clustering.py`, following the existing `dry_run_*` contract (read-only: no Gemma calls, no DB writes, no pipeline mutation — same spirit as `dry_run_layer_a.py` and `dry_run_layer_bc.py`).

**Scope:** the 28 HDBSCAN-no-cluster scenarios, plus a control sample of already-working V2-clustered scenarios (to catch regressions — a variant that "fixes" the 28 by fragmenting the 51 into garbage is not a win).

**Pipeline reuse:** identical segment → embed (cached, no re-embedding cost) → relevance-filter steps already used in this session's diagnostic, stopping short of any Gemma call.

**Variants tested per scenario**, holding the relevance-filtered clause pool and `min_cluster_size` formula fixed:

1. **Baseline** (current production): `metric='euclidean'`, `cluster_selection_method='eom'`, default `min_samples` (= `min_cluster_size`)
2. **Leaf selection**: `cluster_selection_method='leaf'` — trades eom's single-dominant-blob preference for more, smaller clusters
3. **Lower `min_samples`**: `min_samples=2`, `eom` unchanged — decouples core-distance conservatism from `min_cluster_size`
4. **UMAP pre-reduction**: `UMAP(n_components=5, metric='cosine', random_state=42)` → HDBSCAN on the reduced space, `eom`, `min_cluster_size` unchanged. The specific seed value doesn't matter, only that `random_state` is pinned explicitly and documented in the script — UMAP's own stochasticity is a separate concern from the embedding-reproducibility issue already documented in CLAUDE.md (embed_cache.db pins the *inputs*; this pins the *reduction step*).

**Per-(scenario, variant) output:** cluster count, noise fraction, distinct-call support per cluster (same `support_calls` semantics as production).

**Validation, not just counting:** for whichever variant looks most promising, print the actual clause text of the top clusters for a ~10-scenario subsample (mix of previously-no-cluster and control scenarios) so a human reads for semantic coherence before trusting it. This mirrors the existing rule in this codebase that merge/threshold decisions are validated by reading group members (the `--merge-detail` precedent in `dry_run_layer_a.py`), not by cluster counts alone — a variant that turns 100%-noise into incoherent clusters is a false win.

### Decision gate (explicit, not automatic)

Track A produces a **recommendation**, not a code change. If a variant is worth adopting into `v2/layer_c.py`, that requires:

- A new `tuning.yaml` key under `layer_c` (e.g. `cluster_selection_method` or `umap_n_components`)
- A matching field added to `LayerCTuning` in `shared/tuning.py` (the loader raises on unknown/missing keys by design — this is deliberate friction, not an oversight to route around)
- Re-validation that the change doesn't regress the 51 currently-working scenarios

That follow-up implementation is explicitly **out of scope for this spec** — it's gated on what Track A's diagnostic actually shows, which cannot be known until the script runs.

### Out of scope

- Modifying `v2/layer_c.py`'s production clustering call (deferred to a follow-up spec if Track A recommends a change)
- Any full pipeline re-run, Gemma calls, or DB writes
- Ego Trap (already flagged elsewhere as invalidated by the 148→85 rubric count change; not touched by this work)
- V1 fallback prompt quality (considered and rejected as a primary approach — it doesn't address the 23 of 28 no-cluster scenarios that have substantial clause pools where clustering signal is plausibly being lost to an algorithm limitation, not a data limitation)

## Testing impact

Track A's script is calibration tooling, not production code — same category as `dry_run_layer_a.py`/`dry_run_layer_bc.py`, neither of which is covered by the pytest suite (only the pure functions in `shared/cluster_evidence.py` are unit-tested). No new tests are needed for this spec's deliverables.

If a Track A variant is later adopted into `v2/layer_c.py` (follow-up work, not this spec), and it introduces new pure logic (e.g. a dimensionality-reduction helper), that follow-up should add a corresponding test in `test_cluster_evidence.py`, consistent with existing coverage.
