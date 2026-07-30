# Layer B Two-Stage (Primary-Topic-First) Matching Design

**Date:** 2026-07-30
**Status:** Approved, not yet implemented
**Depends on:** `docs/superpowers/specs/2026-07-30-layer-a-topic-hierarchy-design.md` — this spec
cannot be calibrated or shipped until that one runs and produces real `primary_topics` rows to
match against. Written now at the user's request, ahead of that dependency landing.
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

## Production wiring

Keep a `layer_b.matching_strategy: flat | strict | soft | fallback` selector in `tuning.yaml` even
after a winner is picked, rather than deleting the losing implementations. This project's own
precedent is that thresholds get re-swept as the corpus grows (416 calls today, more later), so
keeping every variant selectable is cheap insurance against needing this exact comparison again
at a larger corpus size, rather than re-deriving it from scratch.
