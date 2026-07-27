# Clustering & Milestone Quality Problem Brief

Handoff doc for continuing the design discussion in a fresh chat. Written after a
full V2 pipeline run against 412 real transcripts (`Brain/recordings/`), with the
resulting DB state analyzed directly (149 scenarios, 148 rubrics, 4,605 kb_pairs).

The user wants a **long-term, structural fix in the pipeline code** — they are
willing to re-run the entire 412-transcript pipeline from scratch for a durable
fix, not a one-off manual cleanup of the existing DB rows.

## System context

V2 pipeline stages, in order:
- **Layer A** (`v2/layer_a.py`) — BERTopic (UMAP + HDBSCAN) clusters all CLIENT
  clauses across the whole corpus into a scenario taxonomy. Each surviving
  cluster gets labeled independently by Gemma into a `scenario_key`.
- **Layer B** (`v1/layer_b.py`) — extracts CLIENT-trigger → Naren-response pairs
  per transcript, assigns each pair to every scenario whose description clears a
  cosine-similarity threshold (`assign_scenarios`).
- **Layer C** (`v2/layer_c.py`) — for each scenario, clusters all matched Naren
  responses' clauses (HDBSCAN) into "milestones" (distinct strategic moves), and
  asks Gemma to describe each one plus generate soft-skill/anti-pattern rubric.
- **Layer D / Ego Trap** — scores real CSM calls against these rubrics,
  milestone-by-milestone.

## Problems found, with concrete examples

### 1. Milestone count is uncapped and scales with pair volume, not real content

Distribution across 148 rubrics: `min=0 max=95 avg=9.7 median=4.0`.

```
  0 milestones:    7 rubrics
  1-5:            86 rubrics  (58%)
  6-10:           25 rubrics
  11-20:          11 rubrics
  21-50:          13 rubrics
  50+:             6 rubrics
```

Worst offenders correlate almost linearly with `kb_pairs` volume for that
scenario — not with how many genuinely distinct strategic moves exist:

```
milestones=95  pairs=212  job_board_advertising_strategy
milestones=91  pairs=157  client_request_for_information
milestones=77  pairs=129  hiring_volume_scale
milestones=76  pairs=135  deferred_follow_up
milestones=68  pairs=108  funnel_tracking_and_attribution
milestones=60  pairs=166  giving_floor_to_speaker
```

**Root cause:** `v2/layer_c.py` builds its clause pool from *every* matched
Naren response with no cap (`for resp in responses:` over the full list), then
runs HDBSCAN with `min_cluster_size=2` — about as permissive as clustering
gets. The only existing cap, `_MAX_RUBRIC_RESPONSES=12`, limits a *different*
prompt (soft-skill/anti-pattern generation), not the clause pool that produces
milestones.

**Why it matters beyond "too many rows":** `ego_trap/milestone_scoring.py`
scores *every* milestone independently against a single CSM response that's
typically 1-3 sentences. A rubric with 95 milestones structurally guarantees
a near-zero hit rate regardless of actual CSM skill — this exact pattern
(0/8, then 0/61 hits) is already documented in `Brain/ego_trap/RUN_NOTES.md`.

### 2. Milestone *content* is contaminated with generic, cross-topic phrases

Real milestone labels stored for `job_board_advertising_strategy` (95 total):

```
"Offer brief apology", "Clarifying Operational Details", "Expressing Gratitude",
"Asserting Platform Integration", "Validating the question", "Absolute Agreement",
"Validating Client Logic", "Synthesizing Multiple Options"
```

None of these are specific to job board advertising strategy — they're generic
conversational moves.

**Root cause:** HDBSCAN clusters clause embeddings with no topic-relevance
filter. Phrases like "thank you," "I understand," "sorry about that" appear in
every response regardless of topic and form dense, easy-to-find clusters right
alongside genuinely topic-specific content, because they're common and
low-variance across the whole corpus.

### 3. Scenario taxonomy is over-segmented on generic/backchannel behavior

At least 9 near-duplicate scenarios exist for one underlying behavior (brief
client acknowledgment):

```
client_acknowledgment, client_acknowledgment_1, client_acknowledgment_and_awareness,
client_affirmation_acknowledgment, client_agreement, client_agreement_confirmation,
client_confirmation, client_apologies, client_appreciation
```

Real `trigger_text` captured under this family:

```
"Perfect. Alright then Perfect, and thank you. I think law Yes."
"Marriage, right, where you have the highest case, and and you know."
"After our sync every day if we get new ones? Great. Perfect."
```

**Root cause chain:**
a. `v2/layer_a.py` builds its CLIENT-clause pool with **no substantive/relevance
   filter at all** — every clause from every CLIENT turn goes straight into
   BERTopic clustering, backchannel or not.
b. Backchannel phrases are extremely frequent in real calls — frequency + tight
   semantic clustering is exactly what HDBSCAN is built to find and promote
   into a topic, so this content is *not* discarded as statistical noise; being
   common is precisely why it survives.
c. Despite being semantically the same behavior, lexical variety ("okay" vs
   "got it" vs "right, understood") causes these clauses to splinter into
   several nearby-but-distinct density islands instead of merging into one.
d. Each surviving cluster is labeled independently by Gemma with **zero
   visibility into scenario keys already created** — it has no way to notice
   "this is the 9th acknowledgment variant" and mints a plausible-sounding new
   label each time. Only exact string collisions get a numeric suffix; there is
   no semantic dedup step.
e. The one merge mechanism that exists, `MAX_CLUSTERS=150` triggering
   `topic_model.reduce_topics()`, is **count-triggered, not similarity-
   triggered** — this run landed at 149 scenarios (just under the 150 cap), so
   this merge barely engaged even though real semantic duplication existed.

### 4. The one existing anti-generic-text filter doesn't reach the layer that needs it

`_is_substantive()` in `v1/layer_b.py` (requires >=5 non-stopword alphabetic
tokens via spaCy) is the **only** filter of this kind anywhere in the pipeline,
and it **only runs during Layer B pair extraction — never during Layer A
scenario clustering**, which is where the over-segmentation in problem 3
actually happens.

Even where it does run, it's a pure word-count heuristic blind to semantic
function. Both real examples above ("Perfect. Alright then Perfect, and thank
you. I think law Yes." / "Marriage, right, where you have the highest case,
and and you know.") clear the 5-content-word bar despite being functionally
acknowledgment noise, not decision-relevant client statements.

### 5. 7 rubrics have zero milestones — a correct downstream symptom of #3

```
conversational_fillers, client_affirmation_acknowledgment, client_reactive_interjections,
client_confirmation, client_referencing_and_segmentation, conversational_filler_and_transitions,
rfp_process_transparency
```

These aren't rubric-authoring gaps — Layer C correctly found nothing scoreable
to build a rubric from. The real bug is upstream: these scenario clusters
should never have been promoted to "needs a rubric" status in the first place.

### 6. Layer B's scenario-matching threshold is miscalibrated at this scale (related, may be separate scope)

`3,234 of 4,605 pairs (70%) matched ALL 149 scenarios`; 82% matched 145+. Not
meaningful multi-topic matching — a systematic threshold failure.

**Root cause:** `v1/layer_b.py`'s `assign_scenarios` computes cosine similarity
between each trigger embedding and each of 149 short, generically-worded
scenario-description embeddings (`sub_topic + keyphrases`), assigning a pair to
*every* scenario that independently clears an absolute `0.30` threshold, with
no relative ranking or top-K cutoff. At 149 candidates, a fixed absolute
threshold doesn't scale — most triggers clear the low bar against nearly all
descriptions simultaneously. This interacts with problem 3: near-duplicate
generic scenario descriptions (the acknowledgment family) sit close together in
embedding space, making it even easier for any vaguely-related trigger to clear
the bar against several of them at once.

### 7. One scenario silently has no rubric at all

149 scenarios vs. 148 rubrics — some scenario cluster hit the `if not
responses: skip` branch in `v1/layer_c.py`'s fallback path with no end-of-run
reconciliation warning that a scenario has zero rubric coverage.

## Goal for the long-term fix

1. The scenario taxonomy should represent genuinely distinct, strategically
   meaningful client scenarios. Generic backchannel/acknowledgment behavior
   should be excluded or consolidated into at most 1-2 clusters — not
   fragmented into 9+.
2. Milestone count per rubric should reflect genuine, distinct, repeated
   strategic moves specific to that scenario, bounded to a coachable range
   (single digits, not tens or nineties) — and every milestone must be
   verifiably relevant to its own scenario's topic, not a generic cross-topic
   phrase.
3. The fix must be **structural/generative** — fixed in the pipeline code
   itself so a fresh run produces clean data, not a manual one-time cleanup
   pass on the existing 149-scenario/148-rubric dataset.
4. Any new filtering/classification mechanism should be self-maintaining
   (reuse existing embeddings/scenario vectors, or a small one-time reference
   set) — avoid reintroducing a hand-maintained list that drifts stale, the
   same anti-pattern already eliminated this session when `JOVEO_SPEAKER_NAMES`
   was replaced with Avoma's own `is_rep` roster data.
5. Every scenario that receives a rubric should be genuinely scoreable — the
   pipeline should distinguish "this needs milestones" from "this doesn't"
   rather than silently producing empty or near-empty rubrics.
6. No silent gaps: every scenario should get an explicit rubric attempt (or an
   explicit, logged decision not to attempt one) — not a silent skip.
7. (Open scope question) Whether the Layer B multi-match threshold problem
   (#6 above) should be fixed as part of this same effort, since it compounds
   with the scenario-taxonomy fix, or tracked as a separate follow-up.

## Not yet decided (for the next chat to pick up)

Three candidate approaches were discussed but not finalized:

- **Structural-only**: reuse `_is_substantive()` at Layer A, replace the
  count-triggered topic merge with a similarity-threshold-triggered merge, cap
  Layer C milestones by cluster tightness/distinct-call-coverage, and filter
  milestone candidates by relevance to the scenario's own existing topic vector
  (reusing `_build_scenario_vecs`-style embeddings already computed in Layer B).
- **Add a dedicated semantic genericness filter**: a small (~20-30 example),
  one-time-curated reference set of generic/backchannel phrases, embedded once,
  used to reject clauses at both Layer A and Layer C by similarity — catches
  wordy-but-generic phrasing that word-count filtering misses, at the cost of
  one new small component to maintain.
- Some combination of the above, plus whether to also address problem #6.

Key constraint surfaced during discussion: **capping milestone count alone,
without a relevance/genericness filter, can backfire** — the most frequent,
tightest clusters are often exactly the generic ones, so naive "top-N by
cluster size" would concentrate junk rather than remove it.
