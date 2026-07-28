# Evidence-Triage Clustering & Milestone Design

**Date:** 2026-07-27
**Status:** Approved, not yet implemented
**Supersedes:** the count-capped clustering behaviour described in `Brain/CLUSTERING_QUALITY_PROBLEM.md`
**Requires:** full re-run of the pipeline against `Brain/recordings/` (user has approved this)

## Problem

A full V2 run over 412 transcripts produced 149 scenarios / 148 rubrics / 4,605 kb_pairs with three
structural defects: a scenario taxonomy over-segmented on backchannel behaviour (9+ near-duplicate
acknowledgment scenarios), rubrics with up to 95 milestones whose count tracks pair volume rather than
distinct strategic content, and 70% of pairs matching all 149 scenarios.

`Brain/CLUSTERING_QUALITY_PROBLEM.md` catalogues the symptoms. Three of its conclusions are corrected here.

### Correction 1 — the brief's proposed filters do not catch the brief's own examples

`"Marriage, right, where you have the highest case, and and you know."` yields five content tokens
(*marriage, right, highest, case, know*), so it clears `_MIN_CONTENT_WORDS` in `_is_substantive()`.
Its embedding is also nowhere near a backchannel reference set. It is neither short nor generic — it is
a garbled mid-thought ASR fragment. Both candidate approaches in the brief leak this entire class,
which is the bulk of the noise. Clause-level filtering cannot be the primary defence.

### Correction 2 — V2 Layer C never enforces "recurring" at all

`PROMPT_LAYER_C_V1` states the rule "only include milestones in 2+ responses", but V2 does not use that
path for milestones. `v2/layer_c.py` flattens every clause from every response into one `all_clauses`
list with **no call or response provenance recorded** (only `clause_positions` runs parallel), then
clusters at `min_cluster_size=2`. Two adjacent near-identical clauses *from a single response in a
single call* therefore qualify as a "recurring strategic move". A large share of the 95-milestone
rubric has a support count of one call, and no current code path can report otherwise.

### Correction 3 — `MAX_CLUSTERS=150` does the opposite of pruning duplicates

`reduce_topics(nr_topics=N)` repeatedly merges the **least frequent** topic into its nearest neighbour
until the count reaches N. Three properties defeat the intent:

1. **It merges the rare tail first.** Acknowledgment clusters are among the *largest* — backchannel is
   the most frequent thing in a call — so they are last in line and never reached.
2. **Similarity is c-TF-IDF keyword overlap, not embeddings.** `"Perfect. Alright then"` /
   `"got it, understood"` / `"yeah that makes sense"` share almost no vocabulary, so the metric cannot
   see they are the same behaviour even if they were merge candidates.
3. **A count is not a correctness criterion.** It halts at N whether duplication remains or not. If the
   true taxonomy is 40 and raw is 300, 110 duplicates survive; if the true taxonomy is 200, it destroys
   50 real distinctions. The number cannot distinguish those cases.

Additionally, the run finished at 149 — one under the threshold — so the branch either never executed
(`149 > 150` is false) or executed to a budget because BERTopic counts the `-1` outlier inside
`nr_topics`. Either way the merge ran to a count, never to a duplication criterion. And even a correct
merge would be insufficient: labelling happens per surviving topic with zero cross-visibility, so two
distinct clusters can still receive near-identical labels. Merging and labelling are separate failure
surfaces; the cap addressed only one.

## Core principle

**Cluster freely, then triage clusters against evidence.** Filtering utterances means judging ~40,000
items and can never be exhaustive. Triaging clusters means judging ~150, which is cheap enough to
afford real evidence — and Layer A already makes one Gemma call per cluster, it is simply asking the
wrong question with no memory of prior clusters.

**Survival rule (no target count).** A cluster becomes a coachable scenario iff it:

- draws clauses from at least `MIN_CALL_SUPPORT` distinct calls, and
- is not a merge-duplicate of an already-accepted scenario, and
- is confirmed by the LLM as a client situation requiring a strategic response.

Coverage above `UBIQUITY_CEILING` does **not** disqualify a cluster — see the amendment below.

Whatever number survives *is* the taxonomy.

**Why this is permanent.** Every threshold is a property of the data distribution — fraction of calls,
cosine distance, relative margin to best match — never a count of outputs and never a curated list.
Adding 200 transcripts re-derives every bound. There is no number to bump and no list to keep current.

## Amendment 2026-07-27 — ubiquity is a review flag, not a verdict

Calibrated against the real corpus (416 transcripts, 73,771 CLIENT clauses, `Brain/sweep.log`). Three
findings change the design as originally approved.

**1. `MIN_CALL_SUPPORT` is inert.** Across the entire sweep grid it dropped 0–3 clusters out of 231.
BERTopic's `min_cluster_size` is already 50 clauses at this corpus size, so every surviving cluster
trivially spans more than a handful of calls. It stays as a safety floor for small corpora; it is not a
working lever and must not be credited as one.

**2. Merge threshold and ubiquity ceiling are not independent.** Merging harder unions the member call
sets, which *raises* each surviving cluster's coverage and pushes it over the ceiling. Measured:

| merge | clusters | mechanics @ ubiq 25% |
|---|---|---|
| 0.70 | 34 | 18 (53%) |
| 0.75 | 60 | 32 (53%) |
| 0.80 | 116 | 61 (53%) |
| 0.85 | 168 | 68 (40%) |
| 0.88 | 198 | 71 (36%) |

**3. ~50% mechanics at every operating point is not plausible.** Coverage was misfiring on core business
topics that genuinely appear in most calls. A signal that condemns half the taxonomy is not measuring
what it claims to measure.

**Resolution.** `triage()` returns `scenario_candidate | needs_review | insufficient_evidence`. Coverage
above `UBIQUITY_CEILING` yields `needs_review`, which routes the cluster to Gemma *with its coverage
stats attached* and lets the LLM decide between mechanics and central-business-topic. Coverage decides
what to scrutinise; it never decides what to discard. `insufficient_evidence` remains the only verdict
reached without an LLM, and it saves a Gemma call rather than spending one.

This keeps the "no curated lists, no target counts" property: `UBIQUITY_CEILING` is still a pure
data fraction, it now selects an *audit set* instead of a reject set.

**Also corrected:** `shared/embed_cache.py` stored float16. The same corpus at the same seed produced
241 raw clusters uncached vs 231 cached — UMAP/HDBSCAN neighbour graphs amplify fp16 tie-breaks upstream
of any cosine threshold. The cache is float32; reproducibility is a precondition for calibration.

## Design

### 1. Provenance (enabling change)

Both clause pools discard the source call today; every evidence check depends on it. The data is
already available and simply thrown away:

- `Turn` already carries `call_id` (the transcript stem) — `v2/layer_a.py:23-26` drops it when building
  `client_clauses`. Change the pool to `list[ClauseRef]` carrying `(call_id, turn_index, text)`.
- `storage.get_naren_responses_for_scenario` already returns `call_filename` — `v2/layer_c.py:39-46`
  drops it. Carry a parallel `clause_calls` array alongside `clause_positions`.

No behaviour change in this step. It lands first.

### 2. New module `Brain/shared/cluster_evidence.py`

Pure functions, no I/O, unit-testable. Layer A and Layer C need identical logic at two granularities
(client clauses to scenarios, response clauses to milestones), so this is one implementation with two
call sites.

```python
@dataclass(frozen=True)
class ClusterStats:
    n_items: int
    distinct_calls: int
    call_coverage: float      # distinct_calls / total_calls_in_corpus
    mean_len: float           # mean token count
    cohesion: float           # mean cosine to centroid
    centroid: np.ndarray

def support_stats(items, vecs, total_calls) -> ClusterStats
def merge_by_similarity(centroids, threshold) -> list[list[int]]  # agglomerative, average linkage, cosine
def triage(stats) -> Literal["scenario_candidate", "needs_review", "insufficient_evidence"]
```

`_is_substantive()` moves here from `v1/layer_b.py` so Layer A can also use it — as cheap pre-filtering
only, explicitly not the primary defence (see Correction 1).

**Calibration constants** live here as the single source of truth, documented as dry-run-calibrated.
Starting values, to be set from the real distribution before the production run:

| Constant | Start | Meaning |
|---|---|---|
| `MIN_CALL_SUPPORT` | 4 | cluster must draw from >= 4 distinct calls |
| `UBIQUITY_CEILING` | 0.40 | present in > 40% of calls => mechanics candidate |
| `MERGE_COSINE_THRESHOLD` | 0.88 | centroid cosine above which two clusters are the same |
| `RELATIVE_MARGIN` | 0.85 | Layer B: keep scenarios scoring >= 0.85 x best |
| `MAX_SCENARIOS_PER_PAIR` | 3 | Layer B hard cap |
| `MILESTONE_RELEVANCE_PERCENTILE` | 60 | keep response clauses above the 60th pct of relevance to the scenario vector |
| `MIN_MILESTONE_CALL_FRACTION` | 0.15 | milestone must appear in >= 15% of that scenario's calls |
| `MIN_MILESTONE_CALLS_FLOOR` | 3 | absolute floor for small scenarios |
| `MILESTONE_HARD_CAP` | 10 | backstop only; logs loudly when it binds |

### 3. Layer A (`v2/layer_a.py`)

1. **Delete `MAX_CLUSTERS` / `reduce_topics`** (lines 57-63).
2. **Similarity merge** — agglomerative merge of topic centroids at `MERGE_COSINE_THRESHOLD`. This is
   what collapses the 9 acknowledgment variants. Similarity-triggered, not count-triggered.
3. **Evidence triage** per merged cluster via `cluster_evidence.triage`. Only `insufficient_evidence`
   is terminal (dropped without a Gemma call). `needs_review` — coverage above `UBIQUITY_CEILING` — is
   a routing flag, not a verdict (see amendment).
4. **LLM adjudication with taxonomy memory** — new `PROMPT_LAYER_A_V2_TRIAGE` replaces
   `PROMPT_LAYER_A_V2_LABEL`. It receives cluster keywords, representative utterances, **its own stats**
   (`distinct_calls`, `call_coverage`), a **high-coverage warning when the cluster is `needs_review`**,
   and **the top-3 nearest already-accepted scenarios** by centroid cosine. Returns:

   ```json
   {"decision": "new_scenario | merge_into | mechanics | not_coachable",
    "merge_into_key": "existing_scenario_key or null",
    "reason": "one sentence",
    "scenario_key": "...", "primary_topic": "...", "sub_topic": "...",
    "keyphrases": [], "soft_skills": [], "bloom_level": "apply"}
   ```

   Same Gemma call count as today (one per cluster) — but it can finally see it is the 9th
   acknowledgment variant. Clusters are processed largest-first so the most-evidenced cluster in a
   family becomes the canonical one and later variants merge into it.
5. **Mechanics clusters are retained as scenarios with `is_coachable = false`, not deleted.** This
   matters more than it appears: Layer B's centroid fallback (`v1/layer_b.py:124-134`) currently
   *guarantees* every unmatched junk pair is forced into some real scenario. A mechanics sink gives junk
   somewhere to go instead of contaminating a real rubric.

### 4. Layer B (`v1/layer_b.py`) — in scope

Deferring this would mean re-running 412 transcripts twice: fixing the taxonomy while 70% of pairs still
match everything leaves Layer C with a near-random response pool.

- Replace the absolute `_SIMILARITY_THRESHOLD = 0.30` multi-match with **relative top-K**: rank
  scenarios per trigger, keep those scoring `>= RELATIVE_MARGIN * best`, cap at
  `MAX_SCENARIOS_PER_PAIR`. Scale-invariant at any taxonomy size.
- Mechanics sinks remain match candidates. If the best match is a sink, assign only the sink and stop.
- The centroid fallback routes to a sink, never to a real scenario.
- **`scenario_key` stays the single best match and remains what Layer C queries.** The `scenario_keys`
  array is retained for retrieval and Ego Trap use. Layer C deliberately trains only on
  highest-confidence matches; `storage.get_naren_responses_for_scenario` is unchanged.

### 5. Layer C (`v2/layer_c.py`)

1. Skip scenarios with `is_coachable = false`; record the skip (see section 6).
2. **Scenario-relevance filter on the response clause pool** — cosine of each clause to its scenario
   vector (reusing `_build_scenario_vecs`, promoted to shared), keeping clauses above
   `MILESTONE_RELEVANCE_PERCENTILE` of *that scenario's own* distribution. This is what removes
   "Expressing Gratitude" and "Offer brief apology" from `job_board_advertising_strategy`. It reuses
   embeddings already computed, so it introduces no hand-maintained artifact.
3. **Milestone support measured in distinct calls.** Required support is
   `max(MIN_MILESTONE_CALLS_FLOOR, ceil(MIN_MILESTONE_CALL_FRACTION * scenario_call_count))`. This is
   self-scaling: a 200-call scenario must clear a proportionally higher bar than a 6-call one, so a
   large scenario cannot accumulate milestones merely by being large — which is exactly the
   `pairs=212 -> milestones=95` pathology. It also finally enforces the "recurring" claim that
   `PROMPT_LAYER_C_V1` asserts and V2 never checked.
4. Raise `min_cluster_size` from `2`, scaled to pool size.
5. **`MILESTONE_HARD_CAP` is a backstop, not the mechanism.** If it binds, the support floor is wrong;
   log loudly with the scenario key so the dry run surfaces it. Ranking is by distinct-call support.
6. Store `support_calls`, `support_clauses`, and `relevance_mean` on each milestone in the JSONB so the
   evidence behind every milestone is inspectable.

**Ordering note:** the cap is safe only because it runs *after* relevance filtering. The brief's
constraint that "capping alone backfires" is correct — the tightest clusters are the generic ones — but
that ordering removes them before ranking, so the concern does not apply here.

### 6. Reconciliation — no silent gaps

Every scenario receives an explicit terminal status, written to the DB:
`rubric_generated` | `skipped_not_coachable` | `skipped_insufficient_responses` | `failed`.

The run ends by printing a status table and asserting
`count(scenarios) == count(scenarios with non-null rubric_status)`. The 149-vs-148 discrepancy becomes
impossible to produce silently.

### 7. Dry-run calibration + embedding cache

Every constant above must come from the observed distribution, not a guess.

- **`Brain/shared/embed_cache.py`** — SQLite at `Brain/embed_cache.db`, key `sha256(text)`, value
  float16 vector bytes. Wraps `embedder.embed_query` / `embed_document`. Roughly 80k clauses x 2048 dims
  x 2 bytes is about 330 MB on disk; acceptable, and it makes threshold iteration free.
- **`--dry-run=layer_a`** — cluster, merge, compute stats, print the keep/merge/drop decision and the
  full distribution for every cluster, with **zero Gemma calls**.
- **`--dry-run=layer_c`** — run relevance filtering and support counting against existing DB pairs,
  printing the resulting milestone-count distribution per candidate threshold, with zero Gemma calls.

This is how the evidence-driven taxonomy size is observed *before* committing to a production run.

### 8. Schema changes

Per the project gotcha, each needs an explicit `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` alongside the
updated `CREATE TABLE IF NOT EXISTS` literal — `db/init_db.py` never alters existing tables.

```sql
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS is_coachable  BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS cluster_kind  TEXT    NOT NULL DEFAULT 'scenario';
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS support_calls INTEGER NOT NULL DEFAULT 0;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS call_coverage REAL    NOT NULL DEFAULT 0;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS rubric_status TEXT;
```

`cluster_kind` is one of `scenario` | `mechanics` | `logistics`. Milestone JSONB gains `support_calls`,
`support_clauses`, `relevance_mean`.

## Acceptance criteria

Measured against a fresh full run:

1. No two `is_coachable = true` scenarios have centroid cosine >= `MERGE_COSINE_THRESHOLD`.
2. Every scenario with `call_coverage > UBIQUITY_CEILING` was adjudicated as `needs_review` and carries
   the LLM's recorded reason for keeping it coachable. (Amended: high coverage is no longer
   disqualifying, so the criterion is that it was *reviewed*, not that it is absent.)
3. Max milestones per rubric <= `MILESTONE_HARD_CAP`; median in single digits; every milestone has
   `support_calls` >= its scenario's required floor.
4. `MILESTONE_HARD_CAP` binds for zero scenarios (if it binds, the floor is recalibrated).
5. No kb_pair matches more than `MAX_SCENARIOS_PER_PAIR` scenarios.
6. `count(scenarios) == count(scenarios with non-null rubric_status)`.
7. Manual spot-check: no acknowledgment/backchannel family among coachable scenarios.

## Implementation order

1. Embedding cache + provenance + dry-run harness — no behaviour change, makes everything else cheap.
2. `cluster_evidence.py` + unit tests against synthetic clusters.
3. Schema migration.
4. Layer A rewrite + `PROMPT_LAYER_A_V2_TRIAGE`.
5. Layer B relative top-K matching.
6. Layer C relevance filter + call-support gating.
7. Reconciliation reporting.
8. Calibrate thresholds via dry run, then `clear_data.py` and full production re-run.

## Out of scope (flagged)

**Layer D scoring denominator.** Even with clean, bounded milestones, `ego_trap/milestone_scoring.py`
scores every milestone against a 1-3 sentence CSM reply, while Naren's own benchmark reply for that
scenario likely hits only a few. Hit rate stays structurally deflated until the denominator becomes
"milestones the benchmark response itself hits". That is a Layer D change with its own spec. It is
recorded here so a still-low hit rate after this work is not misread as a failure of this work.

## Risks

- **Over-filtering at Layer C.** If `MIN_MILESTONE_CALL_FRACTION` is too aggressive, scenarios drop to
  zero milestones. Mitigated by `--dry-run=layer_c`, which reports the milestone-count distribution per
  candidate threshold before any Gemma spend.
- **Merge threshold too aggressive** collapses genuinely distinct scenarios. Mitigated by
  `--dry-run=layer_a` printing every merge group with its member representatives for inspection.
- **LLM adjudication drift** — Gemma may over-merge when shown neighbours. Mitigated by requiring an
  explicit `merge_into_key` that must match an existing key, and logging every merge decision with its
  stated reason for review in the dry run.
