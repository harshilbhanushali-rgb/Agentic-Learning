# Layer A Primary-Topic Coachability Split

**Date:** 2026-07-31
**Status:** Approved, validated against real data, not yet implemented
**Depends on:** `docs/superpowers/specs/2026-07-30-layer-a-topic-hierarchy-design.md` (the primary_topic
hierarchy this fixes a contamination problem in).
**Scope:** Layer A only (`shared/topic_grouping.py`, `v2/layer_a.py::_finalize_primary_topics`). No
changes to Layer B or Layer C, no schema migration, no new `tuning.yaml` key.

## Problem

The primary_topic grouping mechanism (either `group_post_hoc` or `group_nested`, both built in the
companion spec) merges subtopic centroids by cosine similarity at a loose threshold
(`primary_topic_merge_threshold: 0.75`). This is pure vector geometry with no semantic check, and it
produces primary_topic groups that fuse genuinely coachable business scenarios together with pure
mechanics/backchannel sinks -- the same "centroid converges toward a generic conversation direction
under averaging" failure the companion spec already documents one level down, at the subtopic-merge
threshold, reappearing one level up the hierarchy.

Confirmed on the real 150-call subset run (`subset150_nested_20260731`, `grouping_method: nested`):
of 28 primary_topic groups, **5 mix coachable and non-coachable members**, the largest being a
22-member group ("Conversational Logistics & Interaction," 141/150 calls) containing 6 real coachable
scenarios (`request_product_demonstration`, `client_signals_value_drivers`, etc.) alongside 16
mechanics sinks (`conversational_fillers`, `conversational_acknowledgments`, etc.). The companion
spec's own follow-up experiment already showed a coverage-based, zero-Gemma proxy filter applied
*before* grouping cannot fully separate this contamination (a known ATS-integration/backchannel case
survived it unchanged), because coverage measures call statistics, not semantic content.

## Why this fix is possible with zero new Gemma calls or thresholds

Reading the shipped code (`v2/layer_a.py::_finalize_primary_topics`, not the companion spec's original
plan) shows primary-topic grouping already runs as **one separate pass after every subtopic finishes
adjudication**, for both `nested` and `post_hoc`. `is_coachable` is therefore already a known, reliable
field on every record by the time `groups` is built -- it does not need to be inferred, proxied, or
estimated. Splitting a group by an already-known boolean is a structural correction, not a data-property
threshold, so there is nothing to calibrate and no risk of the proxy-signal failure mode the companion
spec's follow-up experiment already ran into.

## Design

**New pure function**, `shared/topic_grouping.py::split_by_coachability`:

```python
def split_by_coachability(groups: list[list[dict]]) -> list[list[dict]]:
    """Split any macro-group whose members are not all the same is_coachable
    status into homogeneous coachable-only / non-coachable-only groups.

    Grouping decides membership from centroid geometry alone and can fuse a
    coachable subtopic with a sink subtopic when their centroids converge
    toward a generic "conversation" direction under averaging. is_coachable is
    already known by the time this runs (grouping is a separate pass after
    adjudication finishes), so this is a free, zero-Gemma correction: it can
    only ever split a group, never merge one, so it cannot introduce a new
    failure mode beyond what grouping already decided.

    Returns groups re-sorted largest-first, matching the existing convention.
    """
```

Implementation: partition each group's members into `coachable` / `not_coachable` lists; emit each
non-empty partition as its own group (an already-homogeneous group passes through as a single
partition, unchanged); re-sort the full result largest-first.

**One call site**: `_finalize_primary_topics` (`v2/layer_a.py`), immediately after `groups` is built
(both the `nested` and `post_hoc` branches converge to the same `list[list[dict]]` shape at that
point) and before `_label_primary_topics_batch(groups, config)`:

```python
groups = topic_grouping.split_by_coachability(groups)
labels = _label_primary_topics_batch(groups, config)
```

Everything downstream -- labeling, `primary_topics` row construction, writing `primary_topic_key` back
onto each scenario record -- already operates on whatever `groups` contains. No other line changes.

**Externally visible effects**: a few more (but cleaner) `primary_topics` rows; a few more batched
labeling calls (still batched at `_TOPIC_LABEL_BATCH_SIZE`, not per-item, since batch size is
unaffected by group count). No schema change, no new `tuning.yaml` key.

## Validation against real data (2026-07-31, pre-implementation)

Ran the function above (as a standalone script, not yet committed to the codebase) against the real
`scenarios` table from the 150-call subset run, reconstructing each group by its current
`primary_topic_key` -- this is exactly the raw group membership `_finalize_primary_topics` built
before the labeling call, since that call only ever *adds* a label, never reshapes membership.

- **Before:** 28 primary_topic groups, 5 of them mixed coachable/non-coachable.
- **After:** 33 groups (+5, one extra per split), **zero remaining mixed groups**.
- All 69 scenario memberships preserved exactly (no scenario gained, lost, or duplicated).
- Every already-homogeneous group passed through unchanged (spot-checked all 23 non-mixed groups by
  key-set equality).
- The known blob (22 members) split into exactly a 6-member coachable group and a 16-member sink
  group, as predicted.

This is a complete fix for every contamination case present in the current subset data, achieved with
a pure post-hoc partition and no re-clustering, no re-embedding, and no Gemma calls.

## Testing

- New cases in `tests/test_topic_grouping.py` (mirrors its existing synthetic-record style, no
  embedding model): an all-coachable group is returned unchanged; an all-sink group is returned
  unchanged; a mixed group splits into exactly two homogeneous groups with correct membership; several
  mixed groups in one call all split correctly and the overall result stays sorted largest-first;
  empty input returns empty output.
- One addition to `tests/test_layer_a_v2_primary_topics.py`: `_finalize_primary_topics`'s output groups
  are always coachability-homogeneous, exercised end-to-end (with whatever Gemma-call stub that test
  file already uses for the labeling step).

## Non-goals

- No Gemma-based cohesion/split pass. Every confirmed contamination case in the real data is a
  coachable/non-coachable mix; there is no observed case of two distinct *coachable* scenarios being
  wrongly fused. If that is ever observed at a larger corpus size, it is a separate follow-up (a
  batched Gemma cohesion check mirroring `PROMPT_LAYER_A_V2_TRIAGE`'s pattern one level up) -- not
  built speculatively here.
- No change to `merge_cosine_threshold` or `primary_topic_merge_threshold`. This fix is orthogonal to
  both: it corrects the *output* of grouping, not the grouping thresholds themselves.
- No change to Layer B or Layer C. `primary_topic_key` membership changes for some scenarios, but
  Layer B's two-stage matching (`assign_scenarios_two_stage`) already reads whatever
  `primary_topic_key` is stored -- it needs no code change to benefit from cleaner groups, only a
  future re-run and re-comparison against real data (already deferred to the next full-corpus run per
  the two-stage matching spec's Status update 3).

## Rollout

This changes `primary_topics` group membership for any future run, so it should land before the next
full 416-call production run (already planned per the two-stage matching spec), not against the
existing 150-call subset snapshot. No `clear_data.py` / schema change is required on its own merit --
it only takes effect the next time `run_layer_a_v2` executes.
