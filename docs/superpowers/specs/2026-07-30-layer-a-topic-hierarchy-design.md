# Layer A Primary-Topic / Subtopic Hierarchy Design

**Date:** 2026-07-30
**Status:** Implemented and calibrated 2026-07-30 (code + schema migration shipped; see
Calibration results below). Not yet exercised by a real production run — `primary_topics`
is empty until the next full pipeline run against `Brain/recordings/`.
**Scope:** Layer A only (clustering, adjudication, schema). Layer B two-stage matching is a
**separate follow-up spec**, written after this one ships and produces real `primary_topics` data
to design and calibrate against.
**Requires:** a schema migration and a full re-run of the pipeline against `Brain/recordings/`
(user has approved this; existing 158-scenario data in `public.scenarios` is not retrofitted).

## Problem

`scenarios.primary_topic` today is not a real grouping. It is a free-text string independently
invented by Gemma once per subtopic cluster, with no dedup or shared identity across clusters.
The live corpus shows this concretely: `"Discovery"`, `"Discovery & Qualification"`, and
`"Client Environment"` are three different `primary_topic` strings on scenarios that are clearly
siblings under one umbrella (`current_state_workflow_description`, `client_claims_familiarity`,
`organizational_strategic_shift`). There is no queryable answer today to "what subtopics exist
under this primary topic" — there is no shared parent row to join against.

Separately, `scenarios.sub_topic` is overloaded: it holds a one-sentence *business description*
of the subtopic (used as embedding text and pasted into rubric prompts), which is a different
concept from the subtopic's *identity*. The two need separate columns.

The intended shape is a real two-level taxonomy: one `primary_topic` (a broad, deduplicated
category) can have multiple `subtopic` clusters nested under it, each with its own business
description, evidence, and coaching rubric — matching how `scenarios` already behaves today,
just without a real parent.

## Goals

- A `primary_topics` table that is a genuine, deduplicated parent entity, not a repeated string.
- `scenarios.sub_topic` renamed to `business_description`, keeping today's content and downstream
  behavior (embedding text, rubric prompts) unchanged in meaning.
- Two independent, calibratable mechanisms for producing the grouping (see below), because the
  user wants both built and compared rather than picking one on paper.
- Zero changes to the per-subtopic adjudication behavior that has already been extensively
  calibrated (dedup via `merge_into`, coachable/mechanics/logistics triage, `needs_review`
  routing) — this design adds a layer on top, it does not touch that loop's decision logic.

## Non-goals

- Retrofitting the existing 158 scenarios in `public.scenarios` into the new hierarchy. This
  applies to the next full pipeline run only.
- Any change to Layer B (`assign_scenarios`) or Layer C (`_relevance_filter`, rubric generation)
  matching behavior. They keep reading `business_description`/`keyphrases` exactly as they read
  `sub_topic`/`keyphrases` today — a rename, not a behavior change. Using `primary_topic` in
  matching is Spec 2's subject, not this one.
- Grouping the non-coachable sinks (`mechanics`/`logistics`) under primary topics is in-scope
  structurally (they get a `primary_topic_key` like everything else, so the taxonomy stays
  uniform to browse) but is not a design risk area — sinks already have descriptions and
  keyphrases, they group the same way coachable subtopics do.

## Data model

### New table: `primary_topics`

```sql
CREATE TABLE IF NOT EXISTS primary_topics (
    id                SERIAL PRIMARY KEY,
    primary_topic_key TEXT NOT NULL UNIQUE,
    label             TEXT NOT NULL,
    description       TEXT NOT NULL,
    keyphrases        TEXT[] NOT NULL DEFAULT '{}',
    grouping_method   TEXT NOT NULL,   -- 'post_hoc_merge' | 'nested_cluster'
    support_calls     INTEGER NOT NULL,
    support_subtopics INTEGER NOT NULL,
    call_coverage     REAL NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);
```

Matches the existing `scenarios` table convention (`SERIAL` surrogate key + a separate `UNIQUE`
business key, `created_at` on every table).

- `primary_topic_key`: snake_case identifier, same convention as `scenario_key`.
- `label` / `description` / `keyphrases`: Gemma-generated once per macro-group (see Layer A flow
  below). `keyphrases` exists now specifically so Spec 2 can build an embeddable primary-topic
  vector later without a schema change.
- `grouping_method`: records which of the two mechanisms produced this row. Needed for the
  comparison phase, and afterward as an audit trail — not meant to vary within one run.
- `support_calls` / `support_subtopics` / `call_coverage`: evidence rollup, computed as the union
  of member subtopics' call sets, mirroring the evidence columns `scenarios` already has.

### Changes to `scenarios`

```sql
ALTER TABLE scenarios RENAME COLUMN sub_topic TO business_description;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS primary_topic_key TEXT
    REFERENCES primary_topics(primary_topic_key);
```

- `primary_topic` (existing `TEXT NOT NULL` column) is kept, but becomes a denormalized copy of
  the parent's `label`, written at the same time as `primary_topic_key`. This means existing
  simple readers — `ego_trap/signal_check.py`'s `info.get('primary_topic', '')`, for example —
  keep working with zero code change, while `primary_topic_key` is the real FK used for grouping
  and joins.
- `business_description` keeps exactly the role `sub_topic` has today. Every current reader needs
  a rename, not a rewrite: `shared/scenario_vectors.py::scenario_text()`,
  `v2/layer_c.py::_finish_rubric()` and `_relevance_filter()`'s call into `scenario_vectors`,
  and `ego_trap/signal_check.py`'s `scenarios_text` block.

### Migration approach

Since this only applies to the next full run and `db/init_db.py` only creates missing tables
(never alters existing ones), the migration is: snapshot the current `public` schema to
`pre_hierarchy_20260730` (same pattern as the existing `baseline_20260728` /
`v2_overnight_20260729` snapshots), apply the `ALTER`/`CREATE` statements above directly to
`schema.sql`, then run `clear_data.py` before the next full pipeline run. No live-migration path
for in-place data is needed.

## Layer A clustering flow

Both mechanisms are pure functions in a new module, `shared/topic_grouping.py`, mirroring
`cluster_evidence.py`'s style: no I/O, thresholds passed in by the caller from `tuning.yaml`.

### Approach A — post-hoc meta-clustering (`group_post_hoc`)

Runs *after* today's `run_layer_a_v2` loop finishes producing its subtopic clusters exactly as it
does now — adjudication, `merge_into` dedup, coachable/mechanics/logistics triage, all unchanged.
Takes the resulting subtopic centroids (still in memory, before they are stripped for the DB
write in the existing `row = {k: v for k, v in record.items() if k not in (...)}` step) and calls
the existing `cluster_evidence.merge_by_similarity()` a second time, at a looser threshold than
the 0.85 used for subtopic dedup. This is a pure addition: zero changes to the adjudication loop.

```python
def group_post_hoc(subtopic_records: list[dict], threshold: float) -> list[list[str]]:
    """Group subtopic scenario_keys into primary_topic groups by centroid similarity.

    Reuses merge_by_similarity at a looser threshold than subtopic dedup. Returns groups of
    scenario_key, largest-first, matching _merged_clusters' existing ordering convention.
    """
```

### Approach B — nested two-level clustering (`group_nested`)

Runs `merge_by_similarity()` at a loose threshold over the *raw* BERTopic topic centroids first
(before today's single 0.85 merge happens at all) to get macro-groups, then within each
macro-group's member topics, merges again at the tight (0.85) threshold to get subtopic clusters.
This requires `run_layer_a_v2`'s main loop to iterate macro-group by macro-group rather than one
flat cluster list — a real restructure of `_merged_clusters` and the loop that calls
`_adjudicate`. It lives behind a `tuning.yaml` flag (`layer_a.grouping_method: post_hoc | nested`)
so Approach A's path is completely untouched when B is selected, and vice versa — the two do not
share a code path, only the `merge_by_similarity` primitive.

### Labeling macro-groups

Either approach produces the same shape once grouping is done: a list of macro-groups, each a
list of member subtopics. One **batched** Gemma call per group of 5 macro-groups (mirroring the
existing `PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH` batching pattern — macro-groups are few,
~15-25 expected based on the 0.70-threshold measurement already on record in `tuning.yaml`, so a
handful of batched calls is enough) generates `label`, `description`, and `keyphrases` from each
group's members' keywords and `business_description`s. New prompt:
`PROMPT_LAYER_A_PRIMARY_TOPIC_LABEL_BATCH`.

Per-subtopic adjudication (`_adjudicate` / `PROMPT_LAYER_A_V2_TRIAGE`) drops `primary_topic` from
its own response schema entirely — that field is now assigned structurally from the macro-group,
not invented per-cluster. This also shrinks the triage prompt's output surface.

## Calibration tooling

Extend `dry_run_layer_a.py` with a `--grouping-compare` flag. Consistent with every other dry run
in this codebase, it makes **zero Gemma calls**: grouping quality is judged the same way
`--merge-detail` already judges the existing subtopic merge threshold — by reading the actual
c-TF-IDF keywords of each macro-group's members and checking coherence by eye, not by counting
groups. It runs both `group_post_hoc` and `group_nested` (each swept across a small set of
candidate loose-thresholds) over the same cached embeddings, and prints per method/threshold:
group count, size distribution, and each group's member keyword lists side by side.

The winner (method + threshold) gets hardcoded into `tuning.yaml`'s new `layer_a.grouping_method`
key once judged — same convention as every other threshold in that file. There is no runtime
switch needed in production after that decision is made; the flag exists for the comparison
phase only.

## Calibration results (2026-07-30)

Ran `python dry_run_layer_a.py --grouping-compare` over the full 416-call corpus (zero Gemma
calls), sweeping loose thresholds 0.55-0.80 for both mechanisms:

| loose | post_hoc groups (top size) | nested groups (top size) |
|---|---|---|
| 0.55 | 2 (170) | 3 (168) |
| 0.60 | 6 (153) | 8 (147) |
| 0.65 | 13 (125) | 17 (121) |
| 0.70 | 29 (93) | 31 (92) |
| 0.75 | 56 (26) | 68 (21) |
| 0.80 | 101 (13) | 118 (5) |

Below ~0.70 both mechanisms collapse into one indiscriminate mega-group fusing budget/spend,
Joveo-brand mentions, sales-role mentions, and calendar dates -- the same
centroids-converge-toward-a-generic-direction failure `merge_cosine_threshold` calibration
already documents below 0.85, reappearing one level up the hierarchy. Above ~0.80 both
fragment families that clearly belong together (backchannel/affirmation splits into isolated
2-member pairs). **0.75 is the sweet spot for both.** `nested` was chosen over `post_hoc` at
that threshold: smaller residual blob (21 vs 26 members), and it recovers real distinctions
post_hoc's two-step process misses (a clean 5-member scheduling/timezone group; an
AI+automation group that captures "programmatic advertising," a real Joveo product term,
where post_hoc's version doesn't). Set in `tuning.yaml`: `grouping_method: nested`,
`primary_topic_merge_threshold: 0.75`.

**Follow-up experiment -- does sink contamination explain the residual blob?** Extended
`dry_run_layer_a.py --grouping-compare` with an `--exclude-sinks` flag: a zero-Gemma
coachability proxy (`cluster_evidence.triage` at the subtopic level, the same rule production
applies before ever calling Gemma) excludes likely-sink subtopics before grouping, for both
methods, so the comparison stays apples-to-apples. Result over the same corpus: 15/171
subtopics (35/237 raw topics) excluded as sink-proxy; the residual top blob at loose=0.75
shrank from 26->19 (post_hoc) and 21->15 (nested) members -- confirms sinks were part of the
glue, but the blob didn't disappear: what's left still fuses candidate-management,
job-boards, programmatic-advertising, and landing-page content into one group. Separately, a
known contamination case (`answer/aperture` ATS-integration mentions glued to
`yeah-yeah/yep` backchannel) survived the exclusion unchanged in both methods -- the
evidence-only proxy can't catch it because it only measures call-coverage, not semantic
content, and this particular backchannel doesn't trip the ubiquity threshold as a single raw
topic. Confirms the design's own caveat: coverage-based signals can flag, but only the real
Gemma per-subtopic read (already in production, unrelated to this feature) can actually tell
mechanics apart from a real topic that happens to sit nearby in embedding space. No further
tuning-knob change is expected to close this gap; it needs the real pipeline run's
adjudication, not more threshold sweeping.

## Testing

- New `Brain/tests/test_topic_grouping.py`, mirroring `test_cluster_evidence.py`'s style: pure
  unit tests against hand-built synthetic centroids (not the real embedding model), covering both
  `group_post_hoc` and `group_nested` at known thresholds, plus edge cases (single subtopic,
  all-identical centroids, no valid grouping above threshold).
- `test_tuning.py` gets cases for the new `tuning.yaml` keys (`grouping_method`, and the loose
  threshold(s) each approach needs).
- No change to `test_cluster_evidence.py` — `merge_by_similarity` is reused unmodified.
- No change to Layer B tests (`test_layer_b_assignment.py` etc.) — this spec does not touch
  Layer B.

## Follow-up (out of scope here)

Once this ships and a production run produces real `primary_topics` rows, a second spec covers
Layer B two-stage matching: primary_topic-first, then subtopic-within, compared against today's
flat matching via an extension to `dry_run_layer_bc.py`, following the same
build-both-then-calibrate approach used here.
