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
   `support_calls`/`support_clauses`/`call_coverage` taken directly from Half A's stored
   cluster stats, `adjudication_reason` = Half A's stored `reason`.
4. **Reroute pairs.** Update exactly the pairs in the cluster's stored
   `sink_member_pair_ids` (94 for `cluster_5`, 81 for `cluster_8`) — no re-deriving
   membership, no similarity re-computation. Mirrors `backfill_scenarios.py`'s
   `UPDATE kb_pairs SET scenario_key = %s, scenario_id = %s WHERE pair_id = ANY(%s)`
   pattern, and also appends the new `scenario_key` into each row's `scenario_keys` array
   (the multi-scenario column) rather than overwriting it, since these pairs may already
   carry other matches from Layer B's normal multi-match behavior.
5. **Generate rubrics.** Run Layer C for just these two new scenarios, reusing
   `rerun_layer_c.py`'s existing pattern (`storage.get_naren_responses_for_scenario` per
   target key, then `layer_c.run_layer_c(targeted, config, conn, run_id="")`).

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
