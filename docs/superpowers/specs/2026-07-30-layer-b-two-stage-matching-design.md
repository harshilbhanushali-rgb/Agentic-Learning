# Layer B Two-Stage (Primary-Topic-First) Matching Design

**Date:** 2026-07-30
**Status:** Approved, not yet implemented
**Depends on:** `docs/superpowers/specs/2026-07-30-layer-a-topic-hierarchy-design.md` — this spec
cannot be calibrated or shipped until that one runs and produces real `primary_topics` rows to
match against. Written now at the user's request, ahead of that dependency landing.
**Status update (2026-07-30):** the companion spec's code and schema migration have shipped and
its grouping mechanism/threshold are calibrated (`grouping_method: nested`,
`primary_topic_merge_threshold: 0.75` in `tuning.yaml`) -- but `primary_topics` is still EMPTY.
That calibration ran the grouping mechanism standalone via `dry_run_layer_a.py`, zero Gemma
calls, never against real adjudicated data. Real rows only appear after a full production
pipeline run (`main.py`) against `Brain/recordings/`, which has not happened yet. This spec's
dependency is therefore still open in the sense that matters: there is no real
`primary_topics` data to calibrate `--matching-compare` against until that run happens.

**Status update 2 (2026-07-30):** presented with the sequencing choice this spec's dependency
implied -- build uncalibrated now against synthetic vectors, or run the real pipeline first and
build+calibrate in one pass -- the user chose to build now. Shipped: `primary_topic_relative_margin`,
`max_primary_topics_per_pair`, `two_stage_fallback_floor`, and `matching_strategy` (all in
`tuning.yaml`'s `layer_b` section, each explicitly commented UNCALIBRATED with a documented
starting-guess rationale, not a measured one); `shared/scenario_vectors.py::primary_topic_text` /
`build_primary_topic_vecs`; `shared/storage.py::get_primary_topics`; and
`v1/layer_b.py::assign_scenarios_two_stage`, implementing all three strategies (strict / soft /
fallback) behind one function selected by its `strategy` argument. It is a standalone function,
not folded into `assign_scenarios` -- the existing flat implementation is untouched byte-for-byte,
so its own calibration (`relative_margin: 0.95`, etc.) stays exactly as measured. `tests/
test_two_stage_matching.py` (9 tests, hand-built orthogonal-axis vectors mirroring
`test_layer_b_assignment.py`'s style) covers all three cases this design called out: a
constructed recall-loss case proving Strict can lose the correct subtopic when the wrong
primary_topic wins stage 1; a constructed case proving Soft's blended score can rank a
mediocre-own-similarity/strong-parent subtopic above a better-own-similarity/weak-parent one,
plus a separate case confirming sink short-circuiting always uses raw similarity, never the
blended score, under either strategy; and both directions of Fallback's floor (reroute when weak,
keep when strong). Full suite: 105/105 passing (96 prior + 9 new), zero regressions.

**Not built in this pass, deliberately deferred:** the `--matching-compare` extension to
`dry_run_layer_bc.py` (the "Calibration tool" section below), and any production wiring that
would let `matching_strategy` actually select `assign_scenarios_two_stage` from `v1/pipeline.py`
or `v2/pipeline.py` (the "Production wiring" section below). Both need real `primary_topics` data
to be worth building -- there is no dry-run substitute the way Spec 1 had c-TF-IDF pseudo-labels,
because a primary_topic's *label text* (which its embedding vector depends on) only exists after
a real Gemma call, not from clustering alone. `matching_strategy: flat` in the shipped
`tuning.yaml` means none of this is reachable from production yet; flipping it is future work
gated on a real pipeline run.
**Scope:** Layer B matching only (`assign_scenarios`). No changes to Layer A, Layer C, storage
schema, or Pinecone usage.

## Problem

Today's `assign_scenarios` (`v1/layer_b.py`) matches every CLIENT trigger clause against every
subtopic's vector directly — a flat search over ~150-160 candidates. With the primary_topic
hierarchy from the companion spec now giving each subtopic a real parent, matching could instead
narrow to a primary_topic first, then search only its members. This spec designs, builds, and
calibrates that narrowing against today's flat approach, rather than assuming it is better.

## The central risk

This corpus already sits in a narrow, low-margin cosine-similarity band — that is exactly why
`relative_margin` had to be calibrated to 0.95 for flat matching (`tuning.yaml`, `layer_b`
section); anything looser cleared nearly every scenario for nearly every trigger. Averaging many
subtopic vectors into one primary_topic vector blurs that already-thin signal further. If a
coarse first stage picks the wrong primary_topic for a trigger, no second stage can recover the
correct subtopic, because it was never a candidate. This is the standard hierarchical-
classification failure mode (coarse-stage errors are unrecoverable downstream), and it is the
single biggest open question this spec's calibration tool must answer before any two-stage
approach can be trusted.

## Non-goals

- Changing Layer C, `kb_pairs` storage, or Pinecone namespaces. Only which `scenario_key`s a pair
  is assigned to can change; how they're stored and used afterward is unaffected.
- Picking a winner on paper. All three variants below get built and measured; the design does not
  presuppose which one (if any) beats flat matching.

## Primary-topic vectors

Extend `shared/scenario_vectors.py` — its own docstring already states there is exactly one
definition of "the scenario vector" and it lives in that file, so the primary-topic vector
belongs alongside it rather than in a new parallel module:

```python
def primary_topic_text(info: dict) -> str:
    """Canonical text for a primary_topic, mirroring scenario_text()."""
    return info.get("description", "") + " " + " ".join(info.get("keyphrases", []) or [])

def build_primary_topic_vecs(primary_topic_map: dict) -> tuple[list[str], list[list[float]]]:
    """Parallel (keys, vectors) over a primary_topic map, mirroring build_scenario_vecs()."""
```

`primary_topic_map` is loaded via a new `storage.get_primary_topics()`, analogous to the existing
`storage.get_scenarios()`.

## Three matching algorithms

All three share **stage 1**: compute `T_norm @ PT_norm.T` (triggers vs. primary_topic vectors),
keep each trigger's primary_topic(s) within `layer_b.primary_topic_relative_margin` of its own
best match, capped at `layer_b.max_primary_topics_per_pair`. All three also keep today's sink
short-circuit rule completely unchanged: if a trigger's raw best-match *subtopic* (evaluated the
same way as today, ignoring the primary_topic stage) is a sink, it is filed there alone — sinks
are grouped under primary_topics too (per the companion spec), so this check does not need to
change to accommodate the hierarchy.

### Strict (hard filter)
Stage 2 restricts the candidate subtopic set to only the members of the kept primary_topic(s),
then runs today's existing `relative_margin`/`max_scenarios_per_pair` logic (unmodified) within
that restricted set. The purest test of whether narrowing helps, and the baseline the other two
variants are compared against.

### Soft re-rank
No hard restriction. Every non-sink subtopic gets
`blended_score = subtopic_sim × primary_topic_sim(its parent)`, and today's relative-margin/cap
logic runs over `blended_score` in place of raw cosine, globally (same shape as flat matching,
just re-weighted). This isolates exactly one variable — the ranking signal — rather than changing
which subtopics are reachable at all, so it cannot suffer Strict's recall-loss failure mode by
construction.

### Fallback
Runs Strict. If the resulting top-1 subtopic's *raw* cosine similarity to the trigger falls below
a new `layer_b.two_stage_fallback_floor`, the two-stage result for that pair is discarded and flat
matching is computed for that pair instead. Directly patches Strict's recall-loss risk with a
per-pair safety net.

New `tuning.yaml` keys under `layer_b`: `primary_topic_relative_margin`,
`max_primary_topics_per_pair`, `two_stage_fallback_floor` (Fallback only).

## Calibration tool

Extends `dry_run_layer_bc.py` with a `--matching-compare` flag, run over the same real pair set
the script already builds from the corpus. Zero Gemma calls, zero DB writes — consistent with
every dry run in this codebase, and it exercises the actual production `assign_scenarios` code
paths, not a simulation. Reports, side by side:

- **Flat** — today's existing metrics (mean matches, % single match, % at cap), unchanged.
- **Strict** — primary_topic match distribution, subtopic match distribution within the narrowed
  pool, and the critical number: **recall-loss rate** — the % of pairs where flat's chosen top-1
  subtopic's parent primary_topic was *not* among Strict's kept primary_topic(s) for that pair.
  This single number determines whether hierarchical matching is viable for this corpus at all.
- **Soft re-rank** — match distribution, plus agreement rate (Jaccard overlap of assigned
  `scenario_keys` against Flat's assignment for the same pair). Soft re-ranking never hard-excludes
  a subtopic, so "recall loss" isn't a meaningful concept for it; the relevant question is how much
  it actually changes assignments relative to Flat.
- **Fallback** — composed from Strict's numbers plus the fallback-trigger rate, swept across a
  small set of candidate floor values.

The threshold/algorithm combination judged best from this report gets set in `tuning.yaml` — same
"measure, then commit" convention as every other threshold in this file.

## Testing

New `Brain/tests/test_two_stage_matching.py`, matching `test_layer_b_assignment.py`'s existing
style: hand-built orthogonal unit vectors rather than the real embedding model, so it tests the
matching *rule*, not the model.

- A constructed case proving Strict can lose the correct subtopic when the wrong primary_topic
  wins stage 1 — makes the recall-loss risk concrete and regression-testable, not just a
  documented concern.
- A case verifying Soft's blended-score ordering combines both signals as intended (a subtopic
  with a mediocre own-similarity under a strong-matching primary_topic can outrank one with a
  slightly better own-similarity under a weak-matching primary_topic, for specific constructed
  numbers), and that sink short-circuiting still uses raw similarity, never the blended score.
- A case verifying Fallback's floor triggers reroute-to-flat when Strict's best match is weak, and
  does not trigger when it's strong.

**Status update 3 (2026-07-31):** first real data now exists -- a 150-call subset pipeline run
(nested grouping) snapshotted to Postgres schema `subset150_nested_20260731`: 69 scenarios (33
coachable + 36 sinks), 28 primary_topics, 1642 kb_pairs. `Brain/compare_matching_subset.py` (the
one-off stand-in for `--matching-compare` described above) was run against it:

| strategy | top-1 agreement w/ flat | recall-loss proxy (flat top-1 recovered anywhere) | mean Jaccard | mean matches | 1-match % |
|---|---|---|---|---|---|
| Strict   | 69.9% | 69.9% | 0.684 | 1.13 | 88.6% |
| Soft     | 77.4% | 83.6% | 0.764 | 1.30 | 78.4% |
| Fallback (floor 0.50) | 82.1% | 82.1% | 0.798 | 1.20 | 85.3% |

This confirms the central risk on real data, not just synthetic tests: Strict genuinely loses
flat's chosen scenario for ~30% of pairs when the wrong primary_topic wins stage 1 -- narrowing is
not free at this corpus's cosine-similarity band. Soft, which never hard-excludes by construction,
recovers the most (83.6%) while still meaningfully re-ranking (mean Jaccard 0.764, not ~1.0).

**Caveat that governs all of the above:** this only measures divergence from flat, not accuracy.
There is no ground truth for which scenario_key a trigger "should" get, so none of these numbers
say a strategy is more *correct* -- only how much it changes assignments and how much of flat's own
signal it risks losing.

`compare_matching_subset.py --sweep-floor` then swept `two_stage_fallback_floor` against the same
data (835 non-sink pairs; Strict top1_sim percentiles: p10=0.462, p25=0.496, p50=0.537, p75=0.578,
p90=0.615) by capturing each pair's Strict pick and top1 similarity once, then recomputing the
Fallback reroute decision per floor value against the pair's own real flat assignment -- no
re-embedding, no repeated tuning.yaml edits:

| floor | reroute % | agreement | recall-loss proxy | mean Jaccard |
|---|---|---|---|---|
| 0.30 | 0.1% | 70.0% | 70.0% | 0.685 |
| 0.40 | 0.8% | 70.6% | 70.6% | 0.691 |
| 0.50 (current placeholder) | 14.3% | 82.1% | 82.1% | 0.808 |
| 0.55 | 29.5% | 92.4% | 92.4% | 0.915 |
| 0.60 | 42.9% | 99.3% | 99.3% | 0.989 |
| 0.65 | 49.5% | 100.0% | 100.0% | 1.000 |

**Finding: this sweep does not locate a "better" floor, and should not be read as one.** Raising
the floor mechanically raises every agreement/recall number, because a rerouted pair is scored
against its *own real flat assignment* -- reroute is not "the two-stage result turned out
accurate," it is "the two-stage result was discarded and flat's own answer substituted," which
trivially agrees with flat. By floor 0.65, half of all non-sink pairs revert to flat outright, at
which point Fallback is barely distinguishable from flat for most of the corpus -- the opposite of
what a hierarchical-narrowing strategy is for. Unlike `relative_margin`'s percentile-pinning (which
anchored a threshold to an *independent* measured distribution), there is no independent accuracy
signal here to anchor a floor to; the metric being "optimized" is gamed by the floor's own
mechanism. Do not re-run this sweep expecting it to converge on a value -- it structurally can't,
for any corpus size, because the pathology is in what the metric measures, not in insufficient
data.

**Conclusion from 150-call data:** Soft is the more promising strategy to calibrate toward --
it already posts a comparable-or-better recall-loss proxy than Fallback (83.6% vs 82.1%) without
Fallback's reroute mechanism or its floor-calibration dead end, and it changes assignments through
a single continuous re-ranking signal rather than a discrete discard-and-revert gate. If Fallback
is still wanted as a safety net later, treat the floor as a policy/risk-tolerance choice (how much
reroute-to-flat is acceptable), not a value to be swept to convergence.

**Not done in this pass, deliberately deferred:** production wiring (`matching_strategy` stays
`flat`) and the full `--matching-compare` extension to `dry_run_layer_bc.py`. Both were judged
premature at 150 calls -- this corpus is a subset, not the 416-call corpus every other threshold in
`tuning.yaml` was calibrated against, and BERTopic/UMAP clustering geometry (and therefore
`primary_topics` membership and label text) is already documented elsewhere in this codebase as
sensitive to corpus size and re-embedding run-to-run. Building the permanent calibration tool now
against subset data risks calibrating it against geometry that shifts once the full corpus runs.
Re-run this same comparison (and extend it into `dry_run_layer_bc.py --matching-compare` at that
point, not before) once a full 416-call run populates `primary_topics` for real.

## Production wiring

Keep a `layer_b.matching_strategy: flat | strict | soft | fallback` selector in `tuning.yaml` even
after a winner is picked, rather than deleting the losing implementations. This project's own
precedent is that thresholds get re-swept as the corpus grows (416 calls today, more later), so
keeping every variant selectable is cheap insurance against needing this exact comparison again
at a larger corpus size, rather than re-deriving it from scratch.
