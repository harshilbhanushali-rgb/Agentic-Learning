# Layer B Sink-Rescue Design — recovering real content discarded by trigger-only matching

**Date:** 2026-08-04
**Status:** Approved, not yet implemented
**Scope:** Layer B matching only (`v1/layer_b.py`), plus a new standalone comparison harness. No
changes to Layer A, Layer C, storage schema, Pinecone usage, or the production pipeline call site.
Nothing here is wired into `assign_scenarios` or any pipeline module in this pass — see Rollout.

## Problem

`assign_scenarios` decides whether a trigger-response pair is junk using **only the trigger's
embedding**: if the trigger's single best-matching scenario is a non-coachable sink (mechanics,
backchannel, logistics), the pair is filed there alone and permanently excluded from every rubric
— by design, so junk doesn't contaminate real scenarios (see `Brain/PROBLEMS_AND_FIXES.md`'s
"Layer B audit" section for the full history).

Reading real sink-filed pairs found this is discarding real content at a materially high rate —
39.7% of pairs on the first production run, 45.8% on the overnight rerun, with roughly half of a
30-pair manual sample judged genuinely coachable, not junk. Two distinct failure shapes were
observed:

1. A filler-sounding trigger ("I'm fine with whatever you guys think") correctly best-matches a
   sink on its own — but the response that follows is long, substantive, and strategic (an entire
   analytics-dashboard walkthrough). The matching decision never looks at the response, so it has
   no way to notice.
2. A substantive trigger (disclosing real localization scope, debugging a real URL-redirect bug)
   still lands in a sink purely because its own embedding happened to sit closest to that sink's
   centroid.

Both shapes share one root cause: the decision is made from a single embedding (the trigger's)
when a second, already-computed signal (the response's embedding) is available and ignored.

## Non-goals

- The separate, smaller finding from the same audit — a weak match *within* a coachable scenario
  (e.g. banter matched to `client_hedged_agreement`) — is a different failure mode (a poor best
  match accepted at face value, not a real match discarded) and is out of scope here.
- Picking a winner on paper. All three strategies below get built and measured against the real
  corpus; this design does not presuppose which one, if any, is worth adopting.
- Wiring anything into the real pipeline. See Rollout.

## The three strategies

All three reuse the existing `_topk_pick` relative-margin helper unchanged — no new matching
*rule*, only a new *input* to the existing rule (the response's own similarity to each scenario,
computed the same way the trigger's already is). Response text is embedded via `embed_document`
(the same call `embed_and_store_pairs` already makes later in the pipeline — a response is not a
query, it should be embedded the same way scenario descriptions are, for an apples-to-apples
comparison; the disk cache means this is a cache hit whenever the same corpus has already been
processed once, not a second embedding cost).

Implemented as one new function, mirroring how `assign_scenarios_two_stage` sits alongside
`assign_scenarios` without altering it:

```python
def assign_scenarios_with_sink_rescue(
    pairs: list[dict],
    scenario_map: dict[str, dict],
    config: Config,
    strategy: str,  # "response_only" | "blended" | "or_rule"
) -> tuple[list[list[float]], list[list[float]]]:  # (trigger_vecs, response_vecs) for reuse
```

Returning both vector lists mirrors `assign_scenarios`'s existing `trigger_vecs` return — a future
production call site could pass them straight into `embed_and_store_pairs` instead of re-embedding.

### response_only

Leaves the trigger-based sink decision exactly as it is today for every pair. **Only** for a pair
whose trigger-best match is a sink: additionally run `_topk_pick` on the response's similarities
against scenario vectors, restricted to non-sink candidates, using a new `sink_rescue_relative_margin`.
If a candidate survives **and** its raw similarity clears a new absolute floor,
`sink_rescue_min_similarity`, reassign the pair there. Otherwise the pair stays in the sink,
byte-identical to today.

The absolute floor is required, not optional: `relative_margin: 0.95` was calibrated against the
trigger(query)-vs-scenario(document) similarity band (p10=0.496, p50=0.550, p90=0.613). Response
vs. scenario is a **document-vs-document** comparison — an unmeasured, likely different band —
so a purely relative check could rescue a pair whose response is only relatively-better-matched
than the sink, without being an absolutely good match to anything. The harness (below) measures
this band before the floor is set, the same discipline `relative_margin` itself went through.

Smallest blast radius of the three: can only ever change pairs that are sink-bound today.

### or_rule

Same rescue mechanism as `response_only`, but the trigger side no longer gets an automatic pass
just for landing on a non-sink scenario. If the trigger's own top1 similarity — sink or not — falls
below `sink_rescue_min_similarity`, the response gets a chance to override it, using the same
restricted `_topk_pick` check as above. When the trigger's top1 is already at or above the floor,
its result is kept unchanged (trigger wins ties, per the original framing of "prefer trigger when
both qualify").

This can change pairs **outside** today's sink-bound population — a currently-non-sink pair whose
trigger match is weak in absolute terms can also be reconsidered. That is deliberately broader than
`response_only`, and is the strategy's main risk surface: the harness reports exactly how many
non-sink pairs it touches, separately from the sink-rescue rate, so that number is visible before
any decision is made. (Side note: because the override condition is about absolute weakness, not
sink-ness specifically, this strategy would also happen to touch the smaller "weak match within a
coachable scenario" finding called out as a non-goal above — that is an incidental side effect of
the mechanism, not a goal, and the harness should report it separately if it shows up.)

### blended

Replace the matching vector for **every** pair — not just sink-bound ones — with
`normalize(alpha * trigger_unit + (1 - alpha) * response_unit)`, a new `sink_rescue_blend_alpha`
(placeholder `0.6`, weighting the trigger higher since it is the signal the rest of the pipeline is
calibrated against). Re-run the existing flat logic completely unmodified — including the sink
short-circuit itself — on this blended vector in place of the trigger vector alone.

Largest blast radius: this is the only strategy where the sink decision *itself* can move for a
pair whose trigger alone would have matched a real scenario just fine, and it introduces a second
uncalibrated number (`alpha`) on top of the floor the other two strategies also need.

## Calibration harness

New script `compare_sink_rescue.py` at the `Brain/` root, mirroring `compare_matching_subset.py`'s
existing shape exactly: read-only against whichever Postgres schema is live (`trigger_text` /
`response_text` are real columns on `kb_pairs`, no Pinecone read needed), zero Gemma calls, zero
DB writes, embeddings served from the warm disk cache (`embed_cache.db`) since this exact corpus
has already been through a real run.

For each of the three strategies, reports:

- **Rescue rate**: how many of today's sink-filed pairs (`scenario_map[scenario_key].is_coachable
  == False`) move to a non-sink scenario, and which scenarios absorb them (top 10 by count).
- **Non-sink pairs touched** (relevant to `or_rule` and `blended` only): how many pairs that are
  *not* sink-bound today get reassigned to a different scenario.
- **Response-vs-scenario similarity percentiles** (p10/p25/p50/p75/p90 of each pair's best
  response-side match) — printed before any rescue-rate number, to calibrate
  `sink_rescue_min_similarity` off the real distribution rather than guessing it, the same way
  `relative_margin`'s value came from measuring its own band first.
- **20 random rescued pairs** (trigger + response + the scenario it was rescued into) and **10
  random near-miss pairs** (sink-bound, close to the floor, not rescued) printed verbatim for
  manual reading.

The printed samples are the deciding artifact, not the rate. Every prior finding in this file's
history that involved matching quality — the merge-threshold calibration, the two-stage
strict/soft/fallback comparison, the original sink-absorption audit itself — was settled by
reading actual pairs, never by a count alone; this harness is built to make that possible cheaply,
not to replace it with a number.

## Testing

New `tests/test_sink_rescue.py`, following `test_layer_b_assignment.py`'s existing style exactly:
hand-built orthogonal unit-axis vectors so cosine similarities are exact, testing the *rule*, not
the embedding model. At minimum:

- `response_only` rescues a pair whose trigger best-matches a sink but whose response
  clearly best-matches a real scenario above both the margin and the floor.
- `response_only` leaves a pair in its sink when the response's best match is itself a sink, or a
  real scenario below the floor.
- `or_rule` reconsiders a non-sink pair whose trigger's own top1 similarity sits below the floor,
  and leaves alone a non-sink pair whose trigger's top1 is at or above it.
- `blended` moves the sink decision itself for a pair whose response dominates the blend enough to
  flip the best match away from the sink that the trigger alone would have chosen.
- All three strategies still guarantee every pair ends up with a non-null `scenario_key` (mirrors
  the existing `test_every_pair_is_always_assigned` invariant — no strategy may introduce an
  unassigned pair).

## Rollout

Nothing in this pass changes `assign_scenarios`, any pipeline module, or `tuning.yaml`'s live
defaults. New tuning keys (`sink_rescue_strategy`, `sink_rescue_relative_margin`,
`sink_rescue_min_similarity`, `sink_rescue_blend_alpha`) are added under `layer_b:`, each marked
`UNCALIBRATED placeholder` exactly like `primary_topic_relative_margin` was — present so the new
function has somewhere to read its numbers from, not because any value here is trusted yet.

Whether to adopt a strategy, which one, what its calibrated numbers should be, whether existing
`kb_pairs` get backfilled via `backfill_scenarios.py`, and how it gets wired into
`v1/pipeline.py` / `v2/pipeline.py` are all explicit follow-up decisions made **after** the harness
runs and its samples are read — not part of this deliverable.

## Status update (2026-08-04): harness run against the real `public` schema — none of the three strategies is ready as configured

`compare_sink_rescue.py` ran against the live corpus (157 scenarios, 4,605 pairs, 1,865 of them
sink-bound today). Full output: `Brain/compare_sink_rescue_20260804.log`.

**The response-vs-scenario similarity band sits higher than the trigger-vs-scenario band, as
predicted, and today's `sink_rescue_min_similarity: 0.50` placeholder is far too loose for it.**
Measured: p10=0.552, p25=0.598, p50=0.635, p75=0.664, p90=0.688 — every percentile clears 0.50, so
that floor currently filters nothing at all. (For comparison, `relative_margin`'s own trigger-vs-
scenario band was p10=0.496, p50=0.550, p90=0.613 — confirming these are genuinely different,
higher-baseline comparisons, exactly as the design predicted.)

**`response_only` over-rescues badly at these placeholders.** 95.2% of sink-bound pairs (1,775 of
1,865) get rescued — implausibly high, and reading the 20 printed samples confirms it: a clear
majority are wrong matches, not real content. Goodbyes get filed as `client_direct_denial`; a
"can you hear me?" connection check gets filed as `feasibility_and_implementation_request`; a name
clarification plus a self-introduction gets filed as `client_requests_operational_visualization`.
Absorption concentrates hard in a handful of scenarios — `client_requests_operational_visualization`
(278), `implementation_timeline_feasibility` (262), and `feasibility_and_implementation_request`
(258) alone take over half of all 1,775 rescues — the same "gravity well" category-collapse pattern
already documented at other levels of this pipeline (the primary-topic mega-blob, duplicate-scenario
families), now reappearing at the rescue-matching level. The 10 near-miss samples (still correctly
in a sink) do look like genuine filler (weekend well-wishes, movie small talk, greetings), so the
floor isn't broken in principle — it's just calibrated at essentially zero effect. **Not usable as
configured; needs the floor raised toward the measured band (p50/p75, not p10) before this rate
means anything, and the gravity-well absorption needs a fresh look even after that.**

**`or_rule` is the most promising of the three, but still noisy.** Only 8.5% of sink-bound pairs
(159/1,865) get rescued, and it also touches 130 of 2,740 (4.7%) already-non-sink pairs — the risk
surface the design called out by name. Reading the 20 samples: roughly 8-9 read as genuinely
correct — including recovering the *exact* case the original sink-absorption audit in
`PROBLEMS_AND_FIXES.md` flagged as real lost content ("we only have, like, 30 languages... but we
only use 3 or 4" rescued to `ai_capability_discovery`) — while the rest are weak or wrong (small
talk about snow rescued to `client_reacts_to_anomaly`; a name-origin chat rescued to
`timezone_operational_alignment`). **Worth a further calibration pass (a properly-measured floor,
possibly a tighter margin) before it's a real candidate — not ready to wire in today, but the only
one of the three that isn't obviously broken.**

**`blended` is not viable at `alpha=0.6` — it destabilizes matches that already work.** It rescues
22.4% of sink-bound pairs (418/1,865), but at the cost of also changing 1,305 of 2,740 (47.6%!)
pairs that were **already matching a real, non-sink scenario correctly under flat matching**. This
is the design's own stated biggest risk for this strategy, now confirmed at the worst possible
magnitude — nearly half of all previously-good matches get churned, with no evidence the new
answers are better. Some rescued samples read fine (an ATS-integration discussion correctly landing
on `ats_compatibility_and_migration_discovery`), but the collateral damage to the untouched-by-design
non-sink population makes this strategy a net risk, not a net improvement, at this alpha.

**Recommendation: do not wire any of the three into production yet.** `or_rule` is the only
candidate worth a second calibration round — its floor and margin need to be re-measured against
the real band above (not the current placeholders) before it's evaluated again. `response_only`
and `blended` both have a structural failure mode, not just a mistuned number: `response_only`'s
floor needs to move by roughly half the observed range, and `blended` may need `alpha` pushed much
closer to 1.0 (trusting the trigger far more) or abandoning outright, since even a well-chosen floor
doesn't address 47.6% collateral churn on pairs the strategy was never supposed to touch.
`matching_strategy` and `sink_rescue_strategy` both stay at their non-adopting defaults (`flat` /
`none`) in `tuning.yaml` — nothing here changes production behavior.
