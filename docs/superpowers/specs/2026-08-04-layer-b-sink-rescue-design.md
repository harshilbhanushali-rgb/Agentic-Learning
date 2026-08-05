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

> **Superseded by [Status update 3](#status-update-3-2026-08-05-pivot-to-content-signal-gating) below.** All three are cosine-floor-gated, and round 2 (see that status update's predecessor) found the floor-based gate — not any one strategy's specific mechanics — is what can't be tuned to separate real content from wrong-but-similar content. `response_only` and `or_rule` are kept below for the historical record (the round-1/round-2 measurements are real and instructive); `blended` is retired outright, not carried forward — see Status update 3 for why. Do not treat any of the three as a live candidate.

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
sink-bound today). This is the Postgres `public` schema — the current live schema, confirmed by
these counts matching `CLAUDE.md`'s documented "First full-corpus production run" numbers (157
scenarios, 4605 kb_pairs). Full output: `Brain/compare_sink_rescue_20260804.log`.

**The response-vs-scenario similarity band sits higher than the trigger-vs-scenario band, as
predicted, and today's `sink_rescue_response_min_similarity: 0.50` placeholder is far too loose for it.**
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
(258) — 798 pairs, nearly half (45.0%) of all 1,775 rescues — the same "gravity well" category-collapse pattern
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

**Caveat: `or_rule`'s low 8.5% rescue rate is largely a gating artifact, not evidence of better
precision.** Of the 1,865 sink-bound pairs, roughly 1,616 never reach the response check at all —
their trigger's own top-1 similarity to the sink is already ≥ `sink_rescue_trigger_weak_floor`
(0.50), so `or_rule`'s trigger-weak gate excludes them before the response is even looked at. That
means `or_rule` is being measured against a much narrower, easier population than `response_only`
(which checks every sink-bound pair's response, no gate). As a direct consequence, `or_rule`
structurally cannot address the design's own headline motivating failure — Problem section's
failure shape #1: a filler-sounding trigger that CONFIDENTLY matches a sink while its response
carries real content (e.g. "I'm fine with whatever you guys think" / an entire dashboard
walkthrough). A confident sink match, by definition, has a high trigger-vs-sink similarity, so it
never clears the weak-floor gate and `or_rule` never even considers rescuing it. `or_rule` only
ever helps failure shape #2 (a trigger that is itself weak) — a narrower, different population than
what motivated this design in the first place.

**`blended` is not viable at `alpha=0.6` — it destabilizes matches that already work.** It rescues
22.4% of sink-bound pairs (418/1,865), but at the cost of also changing 1,305 of 2,740 (47.6%!)
pairs that were **already matching a real, non-sink scenario correctly under flat matching**. This
is the design's own stated biggest risk for this strategy, now confirmed at the worst possible
magnitude — nearly half of all previously-good matches get churned, with no evidence the new
answers are better. Some rescued samples read fine (an ATS-integration discussion correctly landing
on `ats_compatibility_and_migration_discovery`), but the collateral damage to the untouched-by-design
non-sink population makes this strategy a net risk, not a net improvement, at this alpha.

**Recommendation: do not wire any of the three into production yet.** `or_rule` is the only
candidate worth a second calibration round, and the two floors it depends on need to move in
different directions for different reasons, not as one number: `sink_rescue_response_min_similarity`
(the RESPONSE-side floor `_response_rescue` applies) should move toward the response band measured
above (p50=0.635 / p75=0.664, not the current 0.50 placeholder), while `sink_rescue_trigger_weak_floor`
(the gate deciding whether `or_rule` even looks at the response) is a different knob entirely,
against the trigger band (p10=0.496, p50=0.550) `relative_margin` itself was calibrated against.
**Correction:** the sentence in the original version of this paragraph said raising
`sink_rescue_trigger_weak_floor` would "shrink" `or_rule`'s qualifying population — that was
backwards. The gate is `t_sims[best] < floor`, so *raising* the floor makes *more* pairs count as
weak and reach the response check; it grows the population, it does not shrink it. `response_only`
and `blended` both have a structural failure mode, not just a mistuned number: `response_only`'s
response floor needs to move by roughly half the observed range, and `blended` may need `alpha`
pushed much closer to 1.0 (trusting the trigger far more) or abandoning outright, since even a
well-chosen floor doesn't address 47.6% collateral churn on pairs the strategy was never supposed
to touch. `matching_strategy` and `sink_rescue_strategy` both stay at their non-adopting defaults
(`flat` / `none`) in `tuning.yaml` — nothing here changes production behavior.

## Status update 2 (2026-08-04): or_rule recalibration round 2 — reproduces blended's exact fatal flaw

Acting on the recommendation above, `sink_rescue_response_min_similarity` was raised to the
measured p50 (0.635) and `sink_rescue_trigger_weak_floor` was raised to 0.65 (comfortably above the
trigger band's own p90 of 0.613) specifically to pull in the confidently-sink-matched pairs that
round 1's 0.50 floor structurally excluded — i.e., to finally let `or_rule` reach failure shape #1,
the design's original motivating case. Full output: `Brain/compare_sink_rescue_round2_20260804.log`.

**It worked, in the sense that it moved the population — and that's exactly the problem.**
`or_rule`'s rescue rate rose from 8.5% (159/1,865) to 39.5% (736/1,865), confirming the population
really was gated by trigger confidence, not precision. But `or_rule`'s non-sink collateral damage
rose from 4.7% (130/2,740) to **41.9% (1,147/2,740)** — reproducing `blended`'s round-1 fatal flaw
(47.6% churn) almost exactly, for the same underlying reason: once the trigger-side gate is loosened
enough to reach genuinely confident matches, it can no longer distinguish "confidently matches a
sink" from "confidently matches a real scenario weakly relative to some other candidate," and starts
overriding good matches too. Reading the newly-rescued samples found the same quality ceiling as
round 1 — personal small talk ("my daughter's literally named Lennon"), a 2.5-months-on-the-job
self-introduction, and note-taking asides all get filed into the same handful of generic scenarios
(`feasibility_and_implementation_request`, `client_requests_operational_visualization`) — no
meaningfully better than round 1's already-poor precision. `response_only` alone also moved (raising
just its response floor to 0.635 cut its over-rescue from 95.2% to 41.0%), but the same gravity-well
absorption and wrong-match pattern persisted at the new rate too.

**Revised bottom line: this isn't a threshold-tuning problem, it's a signal problem.** Three
different strategies, at multiple tested settings, all converge on the same trade: any setting loose
enough to catch real rescued content is also loose enough to catch wrong content in comparable
volume, because trigger/response embedding similarity alone doesn't cleanly separate "real content
phrased in generic business language" from "junk that happens to phrase itself similarly." Further
sweeps of these same two floors are unlikely to find a clean operating point — a real next step would
need a different signal entirely (e.g. response length/substantiveness as a cheap pre-filter, or a
small hand-labeled validation set to actually measure precision/recall instead of reading unlabeled
samples). Not attempted in this session. `sink_rescue_response_min_similarity` and
`sink_rescue_trigger_weak_floor` are left at their round-2 values (0.635 / 0.65) in `tuning.yaml` as
the most-recently-measured data point, not because they're recommended for adoption —
`sink_rescue_strategy` and `matching_strategy` remain at their non-adopting defaults throughout.

## Status update 3 (2026-08-05): pivot to content-signal gating

Acting on status update 2's own conclusion — this is a signal problem, not a threshold-tuning
problem — the gate deciding *whether* to rescue a sink-bound pair is replaced with two non-embedding
signals, both drawn from `shared/trigger_quality.py` (a new module, shared with the sibling
[trigger-quality-gate design](2026-08-04-layer-b-trigger-quality-gate-design.md), which independently
needs the same two functions for an unrelated decision — see "Shared module" below for how the two
designs stay in sync without duplicating the implementation). **Routing is not touched**: once a pair
is gated in for rescue, the existing `_topk_pick` restricted to non-sink candidates, on the response's
own embedding, still decides which real scenario absorbs it — nothing about status updates 1-2
showed that part was broken, only the gate deciding whether to look was.

### Why an embedding floor can't do this job, restated precisely

Status update 2's finding, restated as the actual mechanism: a response's cosine similarity to a
scenario centroid measures *topical resemblance*, not *content specificity*. "My daughter's literally
named Lennon" and a real analytics-dashboard walkthrough can sit at comparable similarity to the same
generic business-adjacent scenario, because centroid similarity has no way to distinguish a sentence
that carries specific, checkable content from one that merely uses similar vocabulary. Raising the
floor moves the operating point along a curve where precision and recall trade off in lockstep — it
never finds a corner where one improves without the other degrading, because the measurement itself
can't see the property that actually distinguishes the two cases. A signal has to look at *what's
literally in the text* (concrete entities, numbers, names — content a topic-similarity score is blind
to) or at *conversational structure* (was this actually answering something) to make that distinction.

### Shared module: `shared/trigger_quality.py`

Respecified here for standalone readability, using the exact signatures already committed to in the
trigger-quality-gate design — **whichever design is implemented first creates the real module; the
second imports it, it does not re-author it.** This design consumes only the first two functions
directly; the other two are specified for module completeness and because the sibling design depends
on them.

```python
def content_word_count(text: str) -> int:
    """Non-stop, alphabetic token count -- the same content-word definition
    concrete_content_density divides by. Named but never actually declared
    in this design's original function list despite the gate pseudocode
    below calling it directly -- added here as a fifth small utility,
    closing that gap, found during implementation."""

def concrete_content_density(text: str) -> float:
    """(named_entity_count + noun_chunk_count) / content_word_count, where
    noun_chunk_count EXCLUDES chunks whose root is a bare pronoun (e.g. "I",
    "that", "me") -- spaCy counts these as noun chunks, but measured directly
    against real filler text ("Yeah, I think so. Sounds good to me.") they
    inflated density to 0.5, comparable to genuinely specific content, which
    would have defeated the whole point of adding this term. Excluding them
    separates cleanly: that same filler -> 0.0, a specific-but-entity-free
    response ("We segment bids by device type...") -> 0.33, an entity-rich
    response -> 1.4+. Requires both NER and the dependency parser enabled --
    layer_b.py's _nlp disables both for speed in _is_substantive; that path
    stays untouched, this is an additional narrow pass run only over
    already-extracted candidate pairs' text, not the corpus-wide clause pool
    Layer A/C process, so the added parser cost is bounded and known upfront.
    Renamed from concrete_entity_density (2026-08-05 revision) after
    named-entity-only density was found likely to miss specific-but-entity-free
    content -- noun-chunk density is a second term meant to catch that slice."""

def preceding_turn_is_question(turns: list[dict], turn_index: int) -> bool:
    """True if turns[turn_index - 1] is a NAREN turn ending in '?' or opening
    with a closed-class interrogative word (a grammatical category, not a
    curated content list). False/neutral if the prior turn isn't NAREN.
    Trigger-side only -- irrelevant to the response."""

def sink_real_margin(trigger_vec, sink_centroids, real_centroids) -> float:
    """max(cos(trigger, sink)) - max(cos(trigger, real)). Not consumed by
    this design's gate -- specified here for module completeness; the
    trigger-quality-gate design's own drop decision depends on it."""

def trigger_response_coupling(trigger_vec, response_vec) -> float:
    """Plain cosine between the pair's own two embeddings. Not consumed by
    this design's gate -- available for the trigger-quality-gate design's
    combining logic."""
```

### The gate: density is primary, question is a borderline tie-break only, length gets a floor

```python
if content_word_count(response) < τ_min_words:
    rescue = False                                    # too short to trust the ratio -- stay in sink
elif concrete_content_density(response) >= τ_density:
    rescue = True                                    # response clearly carries content
elif concrete_content_density(response) < τ_low:
    rescue = False                                    # response clearly doesn't
else:
    rescue = preceding_turn_is_question(turns, trigger_turn_index)   # borderline: tie-break
```

The length check runs first and is deliberately conservative in the same direction the rest of this
gate already leans: `concrete_content_density` is a ratio, and for a response only a handful of
words long, one incidental named entity or noun chunk swings that ratio hard enough to be noise, not
signal. `τ_min_words` is a new tuning key (`sink_rescue_density_min_words`), measured from the
labeled sample's own response-length distribution, not guessed.

`preceding_turn_is_question` is deliberately **not** a hard AND-gate. A hard AND would risk
reproducing `or_rule` round 1's exact trap — the design's own headline motivating case ("I'm fine
with whatever you guys think" followed by a full dashboard walkthrough) has no guarantee the prior
Naren turn was phrased as a question, and a hard gate that happens to exclude it would silently fail
the one case this whole effort exists to fix. Question-context is real but weaker evidence than
"the response itself demonstrably contains concrete content" — it describes the trigger's
conversational position, not what the response actually says — so it only breaks ties inside a
measured borderline band, never overrides a clear density read in either direction.

**Neither `τ_density` nor `τ_low` nor `τ_min_words` is chosen here.** Per this codebase's own
repeated rule (a threshold is only trustworthy after you've seen what it separates —
`relative_margin`, `merge_cosine_threshold`, and the Layer C percentile/fraction grid were all
calibrated this way, never guessed), all three come from reading `concrete_content_density(response)`'s
distribution split by ground-truth label, per the next section.

**Escape hatch, stated explicitly, not left implicit.** Status update 2's own conclusion was
"measure before trusting a signal" — that discipline applies to this signal too, not just the cosine
floors it replaces. If the labeled-sample read (next section) shows `concrete_content_density` does
not separate coachable from junk any more cleanly than cosine similarity did in rounds 1-2, this
pivot is abandoned and reported as a dead end, exactly like any other measured-not-guessed threshold
in this codebase's history. It is not assumed to work just because it's a different kind of signal —
it still has to earn that by measurement.

### Two variants, same gate, different eligible population — sequenced, not parallel

- **`content_gate_narrow`** — only pairs that are sink-bound *today* are eligible for the gate,
  mirroring `response_only`'s blast radius. Smallest-risk variant: can only ever change a pair that
  is currently discarded. **Builds and calibrates first** — its calibration data is already planned
  (see "Calibration" below) and its risk surface is bounded to pairs already being discarded, so
  there's nothing to lose by shipping it ahead of `content_gate_broad`.
- **`content_gate_broad`** — any pair is eligible, sink-bound or not, mirroring `or_rule`'s blast
  radius. The harness reports sink-rescue-rate and non-sink-pairs-touched as two separate numbers,
  exactly as it does today for `or_rule` — so the collateral-damage number that broke `or_rule` round
  2 (41.9% of already-correct non-sink pairs touched) is visible again here, against a genuinely
  different gating mechanism, not assumed away. **Not built in this pass.** `content_gate_broad`
  mirrors `or_rule`'s exact failure-prone population, and it needs its own labeled sample that isn't
  planned yet (see "Calibration" below) — whether it's worth that second labeling pass is a decision
  made *after* `content_gate_narrow`'s results are read, not committed to now.

`blended` is **not** carried forward as a third variant. Its defect — replacing the matching vector
for every pair, which is what let it move the sink decision itself and also what caused 47.6%
collateral churn — is orthogonal to what gates a decision; it is a "redefine the matching vector"
design, not a "gate" design, and status update 1 already showed it's a net-negative mechanism on its
own terms regardless of what triggers it. Swapping its trigger for a content signal doesn't address
why it caused damage, so it's dropped rather than re-tested a third time.

### Calibration: reuse the trigger-quality-gate design's labeled sample — a real dependency, not just a convenience

The trigger-quality-gate design's `label_trigger_quality_sample.py` already plans a stratified
~120-150 sample of **currently sink-bound pairs**, Gemma-judged coachable yes/no — which is exactly
the population `content_gate_narrow` needs to derive `τ_density`/`τ_low`/`τ_min_words` against. This
design reuses that labeled sample rather than commissioning a second Gemma-labeling pass over the
same pairs.

**Stated plainly, correcting this design's own earlier framing:** this is a real build-order
dependency, not parallel/independent work. `content_gate_narrow` cannot be calibrated until
`label_trigger_quality_sample.py` exists and has been run — the two designs no longer produce their
calibration data independently, even though *whether to adopt* each one remains a separate decision
(a labeled sample existing doesn't obligate adopting either gate). See the trigger-quality-gate
design's own "Relationship to the sink-rescue design" section, updated to match.

`content_gate_broad`'s extra population — pairs already matched to a real scenario whose trigger is
weak — is **not** covered by that sample and needs its own smaller stratified labeled set before its
threshold can be trusted; this is why it is not built in this pass (see above), not merely a cost
"to be weighed" in the abstract.

**A harness change this pivot requires, not previously needed:** `compare_sink_rescue.py` today reads
only `trigger_text`/`response_text`/`scenario_key` off `kb_pairs` — it never needed the surrounding
transcript. `preceding_turn_is_question` needs `turns[turn_index - 1]`, and `kb_pairs` only stores
`call_id` + `turn_index` (see `db/schema.sql`), not the turn list itself. The harness must additionally
join `kb_pairs.call_id -> calls.filename`, locate the source transcript file, and re-run the same
`transcript_parser` used at extraction time to reconstruct `turns` for that call — a real, new
dependency (filesystem + parser, not pure-DB) the harness didn't carry before. Call this out plainly
in the implementation plan; it is not a one-line addition to the existing DB-only script.

`compare_sink_rescue.py` gets updated to print `concrete_content_density(response)` percentiles split
by ground-truth label (coachable vs not) from the labeled sample, in the same place and style the
existing response-similarity percentile print appears — before any rescue-rate number, per this
design's own inherited discipline that the printed samples, not the rate, are the deciding artifact.

### Testing updates for this pivot

`tests/test_sink_rescue.py` is updated, not replaced, with cases for both new variants (hand-built
inputs, same style as the existing suite): a response with density clearly above `τ_density` rescues
regardless of `preceding_turn_is_question`; a response in the borderline band rescues only when the
preceding turn is a question; a response with density clearly below `τ_low` never rescues regardless
of question status; a response below `τ_min_words` never rescues regardless of density or question
status. `tests/test_trigger_quality.py` (net-new, shared with the trigger-quality-gate design) covers
the two consumed functions directly — this design adds its own call-site test cases on top, it does
not duplicate the module's own unit tests.

### Rollout updates for this pivot

Unchanged posture: nothing wired into `assign_scenarios` or any pipeline module in this pass.
`sink_rescue_strategy` gains two new enum values, `content_gate_narrow` / `content_gate_broad`;
`response_only`/`or_rule`/`blended` remain valid enum values for historical reproducibility of the
round-1/round-2 runs but are marked superseded, not deleted. Because their code paths stay,
`sink_rescue_response_min_similarity`, `sink_rescue_trigger_weak_floor`, and `sink_rescue_blend_alpha`
**stay in `tuning.yaml` unchanged** — `load_tuning()` raises on a missing key, so removing them would
break the very code this design keeps around for reproducibility. "Retired" means: no longer read by
the new gate, not deleted from the file. New keys `sink_rescue_density_threshold` (`τ_density`), `sink_rescue_density_borderline_floor`
(`τ_low`), and `sink_rescue_density_min_words` (`τ_min_words`), all `UNCALIBRATED placeholder` until
the labeled-sample read happens — present so the gate has somewhere to read its numbers from, not
because any value here is trusted yet. If that read shows `concrete_content_density` doesn't
separate coachable from junk (the escape hatch above), none of the three ever get a real value and
this pivot is reported as a dead end instead.
`sink_rescue_relative_margin` is unaffected and stays live — it governs routing (`_topk_pick` picking
*where* a rescued pair lands), which this pivot does not change. `sink_rescue_blend_alpha` becomes
purely historical alongside `blended`. `matching_strategy` and `sink_rescue_strategy` both remain at
their non-adopting defaults (`flat` / `none`) in `tuning.yaml` — nothing in this status update changes
production behavior.
