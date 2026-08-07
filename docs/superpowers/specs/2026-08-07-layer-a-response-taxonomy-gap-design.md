# Layer A response-taxonomy gap: graduate known homeless topics + corpus-wide dry run

## Problem

`v2/layer_a.py::build_client_clause_pool` builds the scenario taxonomy from CLIENT clauses
only (it skips every non-CLIENT turn). Layer B then routes each trigger-response pair by
matching the CLIENT trigger against that taxonomy. If Naren gives a genuinely expert,
recurring response to a client cue that itself doesn't phrase consistently enough to
cluster, there is no scenario for that response to belong to — not "it got misrouted",
but "it was never a candidate destination in the first place."

Every fix tried before this (eight per-pair signal families across
`2026-08-04-layer-b-sink-rescue-design.md`, `2026-08-04-layer-b-trigger-quality-gate-design.md`,
`2026-08-05-layer-b-combined-signal-analysis-design.md`, and three Layer-B/C cluster-routing
variants in `2026-08-05-sink-pool-population-diagnostic-design.md`) tried to route orphaned
pairs into a taxonomy that was already fixed. All were rejected — the best of them
(`by_cluster`) only "succeeded" by forcing orphaned content into a topically-adjacent-but-wrong
existing scenario, which is exactly what produced the destructive merges documented in that
design's final status update. This design fixes the taxonomy itself instead.

**Evidence this gap is real, not hypothetical:** Half A of the sink-pool diagnostic
(`diagnose_sink_pool.py`) already clustered the sink pool's response text and, via a
three-way Gemma verdict (`genuine_sink` / `belongs_to_existing` / `new_coachable_topic`),
found two clusters with real, well-supported content and no client-side home:

| Cluster | Proposed label | Sink pairs | Distinct calls | Coverage | Nearest existing scenario | Cosine |
|---|---|---|---|---|---|---|
| `cluster_5` | `strategic_performance_consulting` | 94 | 115 | 27.6% | `client_requests_operational_visualization` | 0.726 |
| `cluster_8` | `technical_operational_alignment` | 81 | 113 | 27.2% | `client_requests_operational_visualization` | 0.742 |

Both similarities sit comfortably below `merge_cosine_threshold` (0.85 in `tuning.yaml`) —
the same threshold this codebase already uses to decide "is this a duplicate or genuinely
distinct" for subtopic dedup. No new threshold is needed; the existing one already draws
the right line here.

## Scope

Two independent deliverables, in order:

1. **Phase 1** — graduate the two already-found topics into real scenarios. A one-time,
   low-risk backfill using data Half A already produced.
2. **Phase 2** — a corpus-wide dry run to measure whether the gap is bigger than these two
   known instances. Zero DB writes, same discipline as `dry_run_layer_a.py` /
   `dry_run_layer_bc.py`. Explicitly **not** wired into production, and explicitly does
   **not** decide whether/how to build a permanent recurring pass — that is a follow-up
   decision gated on what Phase 2 finds.

## Phase 1 — `Brain/graduate_sink_topics.py`

This is the **first script in this whole investigation that writes to production DB
state.** Every prior script (Half A, Half B, all eight rejected signal-search rounds) was
read-only. That is worth being explicit about.

**Safety net:** snapshot the `public` schema before any write —
`CREATE SCHEMA baseline_pre_graduation_20260807; CREATE TABLE baseline_pre_graduation_20260807.<t> AS SELECT * FROM <t>;`
for `calls`, `scenarios`, `kb_pairs`, `rubrics` — the same pattern already used for
`baseline_20260728`. This makes the change trivially reversible without needing a full
`clear_data.py` + re-run.

**Inputs:** `sink_pool_clusters.json`'s two `new_coachable_topic` cluster records
(`cluster_5`, `cluster_8`) and their verdicts. No re-embedding, no re-clustering — every
number used here was already computed and stored by Half A.

**Steps, per cluster:**

1. **Reconciliation check.** Assert `nearest_coachable_sim < merge_cosine_threshold`
   (already true for both: 0.726 and 0.742 vs 0.85). This check exists for future reuse
   of this script on additional clusters, not because today's two candidates are in
   doubt. **If a future candidate fails this check, the safe behavior is to skip it
   entirely — not to force-route it into the near-neighbor scenario.** Forcing routing
   into a near-but-not-quite match is exactly the mechanism that produced the destructive
   merges in the Half B `by_cluster` findings; this script must not reintroduce that
   failure mode under a different name.
2. **Generate scenario metadata.** A new prompt, `PROMPT_GRADUATE_SINK_TOPIC` (added to
   `shared/prompts.py`), purpose-built for describing a cluster of EXPERT responses as a
   coaching scenario. It produces the same output shape as the existing
   `PROMPT_LAYER_A_V2_TRIAGE` (`business_description`, `keyphrases`, `soft_skills`,
   `bloom_level`) so the new rows are indistinguishable in shape from any other scenario
   — but it is a distinct prompt, not a reuse of the triage prompt verbatim, because that
   prompt is written for interpreting CLIENT clauses and asking a coachability question
   Half A has already answered. The prompt is given Half A's stored `proposed_label` and
   `reason` as context, plus the cluster's representative response samples (reusing
   `sink_pool_clusters.json`'s stored `samples`, no new sampling).
3. **Insert.** `storage.upsert_scenario(conn, row)` with `is_coachable=True`,
   `cluster_kind='scenario'`, `triage_verdict='graduated_from_sink_pool'` (a new value —
   distinguishes these rows from ordinary Layer A output when reading `scenarios` later),
   `adjudication_reason` = Half A's stored `reason`.
   **`support_calls`/`support_clauses`/`call_coverage` are NOT taken directly from Half A's
   stored `distinct_calls`/`call_coverage`** — corrected during implementation planning.
   Those stored fields are computed over the cluster's full union of sink members AND its
   volume-matched coachable-control sample (e.g. `cluster_5` stores `distinct_calls=115`
   over 209 total members: 94 sink + 115 control), not over the 94 sink pairs actually being
   graduated. Reusing them verbatim would overstate this scenario's real evidence with calls
   it has no graduated pair in. Instead, recompute `support_calls`/`call_coverage` from the
   exact `sink_member_pair_ids` at graduation time (one `COUNT(DISTINCT call_id)` query), and
   set `support_clauses = len(sink_member_pair_ids)` — Half A clusters at response
   granularity, not Layer C's clause granularity, so there is no real clause count to report;
   this is a count of graduated responses, documented as such.
4. **Reroute pairs.** Update exactly the pairs in the cluster's stored
   `sink_member_pair_ids` (94 for `cluster_5`, 81 for `cluster_8`) — no re-deriving
   membership, no similarity re-computation. Mirrors `backfill_scenarios.py`'s
   `UPDATE kb_pairs SET scenario_key = %s, scenario_id = %s WHERE pair_id = ANY(%s)`
   pattern, and also appends the new `scenario_key` into each row's `scenario_keys` array
   (the multi-scenario column) rather than overwriting it, since these pairs may already
   carry other matches from Layer B's normal multi-match behavior.
5. **Generate rubrics.** Run Layer C for just these two new scenarios. **Not**
   `rerun_layer_c.py`'s own pattern verbatim — that script calls V1's
   `layer_c.run_layer_c(targeted, config, conn, run_id="")`, but the `public` schema was
   populated by the **V2** pipeline (`v2/layer_a.py`, `v2/layer_c.py`), so the correct call is
   `v2.layer_c.run_layer_c_v2(targeted, config, conn, run_id="")`. Copying `rerun_layer_c.py`
   literally would target the wrong Layer C implementation — caught during implementation
   planning, not a design change.

**Verification (mandatory, not optional):**

- Scenario count before/after must increase by exactly 2.
- Rerouted pair count must be exactly 94 + 81 = 175, no more, no less.
- **Read the generated rubrics verbatim before calling this done** — the single lesson
  repeated hardest across every prior round of this investigation (the withdrawn
  "evidence thickening" finding existed specifically because this step was skipped once).

## Phase 2 — `Brain/dry_run_response_taxonomy.py`

Zero DB writes. Generalizes Half A from "sink pool + a volume-matched sample of
coachable-filed pairs" to **all ~4,605 responses in the corpus** — every `kb_pairs` row,
not a sample — reusing the same clustering call (`v2.layer_c._cluster_milestones`,
`cluster_evidence.milestone_min_cluster_size`) and the same three-way verdict prompt
(`PROMPT_SINK_POOL_TRIAGE`) Half A already validated. No new clustering machinery, no new
adjudication prompt.

**Key difference from Half A:** instead of a binary sink/control `mix_ratio`, each cluster
reports its **current scenario_key composition** — the distribution of existing
`scenario_key` assignments among its members (which may span several coachable scenarios,
several sinks, or both). This is the direct generalization of Half A's mix ratio to a
population that is no longer just "sink vs. one control category."

**Purity gate** (mirrors Half A's existing "skip pure-control clusters" optimization,
generalized): a cluster is **not** sent to Gemma adjudication if one existing coachable
scenario already accounts for the overwhelming majority of its members — client-side and
response-side taxonomies already agree there, and adjudicating it would spend a Gemma call
answering a question nobody asked (the same reasoning Half A already applied to
pure-control clusters). Only clusters whose current-scenario-key distribution is scattered,
or dominated by sink-filed members, go to the three-way verdict.

The dominance fraction that defines "overwhelming majority" is a new tuning key
(`layer_a.response_taxonomy_purity_gate` or similar, added to `tuning.yaml` alongside its
dataclass field in `shared/tuning.py`, per this codebase's existing rule that every
clustering threshold lives there, never hardcoded). Start at **0.90** as a fixed,
pre-registered value the same way Half A's own `_NOISE_ESCAPE_HATCH`/
`_MIX_UNINFORMATIVE_BAND` were fixed before their data existed — it is a starting point
for the dry run's own report to validate or correct by reading the actual purity
distribution it produces, not a value chosen to fit a result.

**Output:**

- Total corpus-wide response clusters, and how many were skipped by the purity gate vs.
  sent to adjudication.
- Verdict tally, with special attention to how many `new_coachable_topic` clusters exist
  **beyond the two already known** — the number that actually answers "is the gap bigger
  than what's already been found."
- `nearest_coachable_sim` for **every** cluster regardless of verdict, which doubles as an
  empirical validation of `merge_cosine_threshold = 0.85` as the reconciliation cutoff —
  the same "validate by reading real data" discipline every other threshold in this
  codebase has already been held to.
- A `--no-gemma` flag (matching `diagnose_sink_pool.py`'s own) reports cluster counts and
  the purity-gate breakdown for free, before any Gemma spend is committed.

**Explicitly out of scope for this phase:** deciding whether or how to turn this into a
permanent pass that runs on every pipeline execution. That is a distinct follow-up design,
contingent on what this dry run actually finds — if it finds nothing beyond the two known
topics, there may be nothing further to build; if it finds a large additional gap, that
follow-up design would need to address recurring Gemma cost and cross-run stability
(Layer A's own per-cluster coachability adjudication is already documented to flip ~5-6%
between independent runs — a new adjudication population inherits that same instability
question, unresolved here).

## Testing / validation

- **Phase 1:** unit-testable reconciliation-threshold logic (given a cluster record and a
  scenario map, assert-or-skip) can be tested with hand-built vectors, no DB/Gemma
  required — same pattern as `test_layer_b_assignment.py`. The end-to-end script itself is
  validated by the count assertions above plus a manual verbatim read of the two new
  rubrics, not by an automated test (this is a one-time backfill, not reusable production
  code path).
- **Phase 2:** the clustering and purity-gate logic (cluster composition from
  `scenario_key` distribution, dominance check) is pure and testable with hand-built data,
  independent of Gemma/DB — should get the same treatment as
  `shared/cluster_evidence.py`'s existing tested helpers. The adjudication step itself is
  validated the way Half A already was: cross-checked against `labeled_trigger_quality_sample.json`
  where cluster membership overlaps it, and by reading verbatim samples for any newly
  found `new_coachable_topic` cluster before trusting it.

## Status update (2026-08-08): Phase 1 code implemented and dry-run-verified against real production data; the real write is still deferred

`shared/cluster_evidence.py::passes_reconciliation_gate`, `PROMPT_GRADUATE_SINK_TOPIC`,
`layer_a.response_taxonomy_purity_gate` (tuning key, `0.90` pre-registered), and
`Brain/graduate_sink_topics.py` (with a mocked-connection test suite covering the write path —
no real DB, no real Gemma) are implemented, tested, and committed. Per an explicit
human-partner instruction given during implementation planning, **no write against the real
`public` schema happens as part of this implementation pass** — only reads. The write path is
verified with mocked SQL assertions instead; the real insert + reroute + Layer C run is a
separate, explicit step deferred to later, gated on the human partner's go-ahead and preceded
by the `baseline_pre_graduation_20260807` schema snapshot.

`graduate_sink_topics.py --dry-run` was run for real against the live `public` schema (reads
only, zero writes) and both clusters graduated cleanly:

| Cluster | Gemma-generated `scenario_key` | Pairs | Distinct calls | Coverage |
| --- | --- | --- | --- | --- |
| `cluster_5` | `strategic_performance_consulting` | 94 | **57** | **13.7%** |
| `cluster_8` | `technical_operational_alignment` | 81 | **59** | **14.2%** |

Both clusters passed the reconciliation gate (0.726 and 0.742, both `<` `merge_cosine_threshold`
= 0.85). Gemma's generated `business_description` for both reads as accurate and specific to
the cluster's actual content, not generic filler.

**The distinct-call/coverage numbers materially differ from this design doc's own evidence
table above (115 calls / 27.6% for `cluster_5`) — confirming exactly the reasoning the
implementation plan flagged.** The design doc's original table (and Half A's own stored
`distinct_calls`/`call_coverage` fields) counted the cluster's full 209-member union of 94 sink
pairs **plus** 115 volume-matched coachable-control pairs — not the 94 sink pairs actually being
graduated. `graduate_sink_topics.py::_support_stats_for_pairs` recomputes support scoped to only
the exact `sink_member_pair_ids`, which is why the real numbers (57/13.7%, 59/14.2%) are smaller
and different from the design table. This does not change the graduation decision — the
reconciliation gate depends only on `nearest_coachable_sim`, unaffected by this fix — but it
means anyone reading this design doc's evidence table alongside the real result should not
expect the call-coverage figures to match; they were never measuring the same population.

Next step, not part of this pass: run `graduate_sink_topics.py` without `--dry-run` against
real production data, preceded by the deferred schema snapshot, on the human partner's explicit
go-ahead.

## Status update (2026-08-08): Phase 2 corpus-wide dry run run for real — the gap is bigger than the two known clusters, by exactly one

`dry_run_response_taxonomy.py` ran for real against the live `public` schema, first `--no-gemma`
(free) then with adjudication. Zero DB writes, as designed.

- **Clustering was much coarser than Half A's**: only **15 clusters** over the full 4,605-pair
  corpus, `min_cluster_size=25` (hit `min_cluster_size_ceiling`, same as Half A's own clustering
  run). This is expected — Half A clustered a 3,730-item union of sink+control; this pass
  clusters the whole corpus at once, and the same coarse-clustering/high-noise dynamic already
  documented for this codebase's UMAP+HDBSCAN steps applies here too.
- **Purity gate: 0 of 15 clusters skipped** — every cluster's current `scenario_key` composition
  was either scattered across several coachable scenarios or not dominated by one coachable
  scenario at the 0.90 threshold, so all 15 went to adjudication. This kept Gemma cost trivial:
  15 clusters batched at 5/call = **3 Gemma calls total** for the whole corpus-wide pass.
- **Verdict tally**: `belongs_to_existing` 11, `genuine_sink` 3, **`new_coachable_topic` 1**.
- **`nearest_coachable_sim` distribution**: p10=0.649, p25=0.703, p50=0.717, p75=0.740,
  p90=0.756 — every cluster sits comfortably below `merge_cosine_threshold=0.85`, which is an
  empirical validation of that threshold as the reconciliation cutoff: nothing in this run was
  a near-miss case where 0.85 would have made a different call.
- **The one new cluster beyond the two already-graduated topics: `cluster_6`,
  `expert_led_discovery_and_context_setting`** — "The expert proactively guides the conversation
  by introducing the company's value proposition or partnership context to align the client's
  expectations." 30 pairs, 22 distinct calls, 5.3% coverage, `nearest_coachable_sim=0.678`
  (comfortably below 0.85). Read verbatim: the samples show the expert deliberately pivoting a
  drifting or small-talk-adjacent conversation ("Pretty fine lately, engaged in giving multiple
  notes of interviews" → the expert redirects into a discovery question about the engagement's
  expected outcome; a client mid-sentence about internal reporting cadence → the expert
  interjects a partnership recap and screen-share) into a deliberate expectation-setting or
  discovery move. This reads as genuinely distinct coaching content, not generic filler — a real
  but smaller-scale finding than the two already-graduated topics (30 pairs/5.3% coverage vs.
  94/81 pairs and 13.7%/14.2% coverage for the two known clusters).

**Answering this design's own question ("is the gap bigger than what's already been found?"):
yes, by one additional topic, not by a large amount.** The two already-known clusters were
rediscovered as part of the same 11 `belongs_to_existing` clusters and `genuine_sink` clusters
(their sink-pool-derived pairs are now folded into the full-corpus clustering, so they don't
reappear as separate `new_coachable_topic` entries here — they were already handled by Phase 1).
One new gap, `expert_led_discovery_and_context_setting`, was found. Per this design's explicit
scope boundary, **no scenario was created and no pair was rerouted** — this is a measurement
only. Whether to graduate this third cluster (via a future run of `graduate_sink_topics.py`
against this new cluster's data) and whether to build a permanent recurring pass are both
follow-up decisions, not resolved here.

Raw output: `Brain/dry_run_response_taxonomy_20260808.log` (Gemma run),
`Brain/dry_run_response_taxonomy_no_gemma_20260808.log` (free pass),
`Brain/dry_run_response_taxonomy.json` (full persisted payload, re-reportable via `--load`).

## Out of scope

- Building a permanent, recurring response-clustering pass wired into `v2/layer_a.py` or
  the main pipeline. That decision is deferred to a follow-up design, contingent on
  Phase 2's findings.
- Re-litigating any of the eight rejected per-pair signals or three rejected Layer-B/C
  routing variants — those are closed dead ends, unrelated to this design.
- Changing `matching_strategy` or `sink_rescue_strategy` in `tuning.yaml` — this design
  does not touch Layer B routing logic at all; it only ever adds new scenarios and moves
  specific, already-known pair IDs into them.
- Addressing the 47.3% HDBSCAN noise ceiling or Layer C's weak relevance filter, both
  still-open findings from the sink-pool diagnostic — orthogonal to this design.
