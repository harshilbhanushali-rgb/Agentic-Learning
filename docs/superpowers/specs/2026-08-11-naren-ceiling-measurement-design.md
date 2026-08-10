# Establishing the Layer D ceiling: score Naren against his own rubrics

**Date:** 2026-08-11
**Status:** design approved, not yet implemented. Amended the same day after measuring the
holdout populations — scope corrected 27 → 49 scenarios, the plain secondary-label arm dropped
in favour of the stricter call-level one, cost ~54 → ~95 Gemma calls.
**Deliverable:** `Brain/calibration/score_naren_ceiling.py` — read-only, zero DB writes

---

## 1. Why this exists

Layer D's milestone hit rate for the one measured CSM (Madhumita) has moved three times
this month, and each fix helped a little without changing the regime:

| change | full hits | weighted |
| --- | --- | --- |
| baseline | 2.4% | 0.043 |
| + sinks removed from Step 0 / criteria rewrite / 17 uncoachable milestones flagged | 3.1% | 0.074 |

Three consecutive fixes each moving the needle slightly is the signature of a binding
constraint nobody has looked at. **Nobody has ever measured what a good score looks
like**, so 3.1% is uninterpretable. It is consistent with a real coaching gap and equally
consistent with a rubric or scorer that cannot recognise good work at all.

The measurement that settles it: take Naren's own responses — `kb_pairs.response_text`,
the corpus the rubrics were derived from — and score them through the **same** Step 3 path
against the **same** rubrics.

### The pre-registered fork

Decision rules are fixed here, before any data is seen, so they cannot be moved afterwards.
`W` is the weighted score `(hits + 0.5 × partial_hits) / attempts`, the definition already
used by `gap_output.milestone_miss_rate` and `measure_scoring_noise.py`. The CSM reference
point is `W = 0.074`, full hits 3.1% (snapshot `arm3_run1_20260810`).

| condition | verdict | consequence |
| --- | --- | --- |
| `W(A3) ≥ 0.50` | rubrics and scorer work | the CSM gap is real; coaching content is buildable; resume tuning |
| `W(A3) < 0.20` | rubric or scorer is fundamentally broken | no CSM number means anything; every fix so far treated a symptom |
| `0.20 ≤ W(A3) < 0.50` | inconclusive | do **not** tune; read verdict samples and decide from them |
| `W(A1) − W(A3) ≥ 0.20` | rubrics are overfit to their own source calls | a Layer C problem, not a prompt or scorer problem — see §4 |
| `W(B) ≥ 0.5 × W(A3)` | **the instrument is invalid** | the scorer does not discriminate; no other row above may be cited |

The `W(B)` row is a gate, not a finding: it is checked first, and if it trips, every other
number in the run is discarded.

---

## 2. The two leaks this design exists to close

Scoring an expert against a rubric built from that expert's own corpus is circular by
default. There are two distinct circularities, with two different remedies.

### Leak 1 — the benchmark is the answer key (removable)

`rubric_lookup.get_benchmark_reference` selects the 2 most on-topic responses from **every**
response filed under the scenario and pastes them into the Step 3 prompt as
`NAREN'S BENCHMARK RESPONSE (for reference only)`. The same prompt then asks whether the
`CSM RESPONSE` satisfies the milestone.

If the response under test is one of those 2, the grader is shown the answer and asked
whether the answer matches it. The result would be ~100% regardless of rubric quality.

**Remedy: call-level benchmark holdout.** Drop the response under test *and every other
response from its call* from the pool before ranking. The pools are large enough that this
costs nothing — `implementation_timeline_feasibility` alone has 260 primary + 166 secondary
responses.

### Leak 2 — the marking scheme was written from the papers (not removable, but holdable-out)

Layer C clusters Naren's response clauses and writes each milestone as a description of a
cluster. A real example from `implementation_timeline_feasibility`, whose clause pool is
drawn from 156 calls:

> **[support_calls = 135] Coordinating Implementation Support** — *Offer specific assistance
> for implementation tasks and inquire about the client's timeline to align support efforts.*

That criterion exists **because** Naren did it in 135 of 156 calls. A randomly chosen
primary-label response from that scenario has roughly an 87% chance its own clauses sit
inside the cluster the sentence was written from. Grading it asks "did Naren do the thing
we defined by watching Naren do it?" — a perfect score would prove nothing.

The obvious fix is unavailable: `_finish_rubric` stores the **count** `support_calls`, never
the contributing call or clause list ([`v2/layer_c.py:406-408`](../../../Brain/v2/layer_c.py)).
There is no way to ask "was this response one of the 135?", and recovering it would require
re-running Layer C Pass 1 — which is not reproducible across process launches (385 / 398 /
403-407 milestones for byte-identical input), so the re-run would move the baseline it was
supposed to explain.

**Remedy: a label-level holdout that already exists in the data.** Layer B files each pair
under up to `max_scenarios_per_pair` scenarios — the best in the scalar `scenario_key`, all
of them in `scenario_keys[]`. Layer C's clause pool reads **only the scalar**
(`storage.get_naren_responses_for_scenario`: `WHERE p.scenario_key = %s`). Therefore a
response filed under scenario `S` as a *secondary* label provably never entered `S`'s clause
pool.

A real row, `pair_id 24169`:

```text
scenario_key  : feasibility_and_implementation_request       <- Layer C used it HERE
scenario_keys : [feasibility_and_implementation_request,
                 implementation_timeline_feasibility]        <- Layer B: also about THIS
```

When Layer C built `implementation_timeline_feasibility`'s milestones it selected on the
scalar, so pair 24169 was never in that rubric's pool — yet Layer B independently judged it
relevant to the scenario. That is a held-out, on-topic, genuine expert answer, and there are
**2,549** such pairs across the 82 rubric'd scenarios, at zero cost.

#### The secondary-label holdout is not enough on its own — measured

Selecting on secondary label holds out **the response**, which is the object being graded. It
does **not** hold out the call: call `45ee54f7…` may contain other pairs whose scalar key *is*
`implementation_timeline_feasibility`, and those did feed the cluster.

Measured 2026-08-11, that gap is large enough to matter. For
`implementation_timeline_feasibility`, 115 calls carry a secondary pair but only **60** of
them contributed no primary pair — so a plain secondary-label stratum would have been roughly
half-leaked at the call level for that scenario, silently. The same pattern holds for every
large scenario (`feasibility_and_implementation_request` 174 → 69,
`client_requests_operational_visualization` 183 → 91,
`application_conversion_flow_discovery` 76 → 40).

**So the holdout is tightened one level: a response qualifies only if its label is secondary
AND its call contributed zero primary pairs to that scenario.** That is arm A3 in §3, and it
is the headline stratum. Population measured before adoption, not assumed: **1,406 eligible
pairs, with 43 of the 49 in-scope scenarios clearing 6+ items** — comfortably past the ≥6-in-≥15
gate this arm was made conditional on.

Even A3 is not a novelty holdout: the response is still Naren, still on-topic, and its clauses
may closely resemble primary ones. The claim stays narrow and exact: *nothing from the call
being graded wrote the criterion it is graded against.*

---

## 3. Design: three arms over one sample

| arm | response population | rubric scored against | benchmark | isolates |
| --- | --- | --- | --- | --- |
| **A1** | Naren, **primary** label | the response's own scenario | own scenario, call held out | leaked ceiling — upper bound |
| **A3** | secondary label **and** the call contributed zero primary pairs | that scenario | that scenario, call held out | **clean ceiling — the headline** |
| **B** | the same texts as A1 | an **unrelated** scenario | that scenario, call held out | scorer specificity |

A plain secondary-label stratum (the earlier "A2") is **dropped**: §2 measured it as roughly
half-leaked at the call level on the large scenarios, and A3 is strictly stronger at
comparable cost. The one thing that loses is the ability to say whether call-level holdout
matters *beyond* response-level — scoring A2-minus-A3 would answer that, and is deferred as a
cheap follow-up worth running only if `W(A1) − W(A3)` turns out large and needs localising.

### Why arm B is not optional

If Naren scores 80% and the grader would also have said 75% against an unrelated rubric,
the 80% measures the grader's generosity, not the rubric. This matters concretely here:
Step 3 runs on `gemini-3.1-flash-lite`, deliberately downgraded from `gemma-4-31b-it` for
TPM reasons, and its specificity has never been measured.

Pairing: each scenario is assigned a partner by a seeded derangement, **rejecting any
pairing whose scenario-vector cosine ≥ `layer_a.merge_cosine_threshold` (0.85)**. That
reuses an existing calibrated knob rather than adding a `tuning.yaml` key, satisfying the
file's rule that every knob be a property of the data. The paired cosines are printed so a reader can
confirm the partners are unrelated instead of trusting the derangement.

Arm B's benchmark comes from the **partner** scenario, not the true one: production always
pairs a rubric with its own benchmark, so making the rubric the only difference requires the
benchmark to travel with it.

### Sampling

- **Scope:** the **49** rubrics Madhumita was actually scored on, so every comparison is paired
  per `(rubric_id, milestone_id)` against `arm3_run1_20260810`. Widening to all 82 rubric'd
  scenarios later is a flag change.

  > **Read the scope from `arm3_run1_20260810`, never from `public`.** The first draft of this
  > spec said 27 scenarios, because it counted `public.milestone_performance` while the
  > noise-floor run was mid-flight and had only reached 27 rubrics. `public` is a *partial*
  > run for as long as any Layer D run is in progress, and it looks like a complete one. This
  > understated the sample and the cost by ~1.8×.

- **Size:** up to 8 responses per scenario per arm. Real availability is respected and the
  achieved N is printed per scenario. Six scenarios have fewer than 8 A3-eligible pairs
  (`client_emphasizes_simplicity` 3, `client_shares_subjective_perception` 4,
  `client_data_field_mapping_discovery` 4, `ats_integration_architecture_discovery` 4,
  `testing_environment_and_validation_discovery` 5) and one has none at all
  (`client_value_expectation_discovery` 0, so it drops out of A3 entirely). They contribute
  whatever they have; the arm-level ≥6-in-≥15 gate is what governs whether A3 exists, and it
  passed at 43 of 49.
- **What the sample is drawn from, in calls.** Naren's corpus is 416 calls. The rubrics under
  test were each built from 4–183 calls (183 `feasibility_and_implementation_request`, 156
  `implementation_timeline_feasibility`, down to 4 `ats_integration_architecture_discovery`).
  The union of distinct calls available to draw from is **367** for A1 pools and **344** for
  secondary pools.
- **Selection:** seeded random, `random.Random(20260811)`. **Not** top-scenario-similarity:
  ranking by similarity selects the most prototypical responses and would inflate the
  ceiling. Selected `pair_id`s are persisted so the sample is reproducible exactly.
- **The unit of an item is `(response, scenario)`, not `response`.** Sampling iterates
  scenarios and draws from each scenario's own pool, so a pair carrying two secondary labels
  can legitimately appear twice in A3 — once per scenario it is being scored against. That is
  correct, because the thing under test is a rubric, not a response; but it means item counts
  are not distinct-response counts, and the number of distinct `pair_id`s per arm is reported
  alongside the item count so the two are never confused.

### Fidelity to the path being measured

- `ego_trap.milestone_scoring.score_milestones_batch` is called **unchanged**. No parallel
  scorer is written; that is the whole point of the experiment.
- `_GEMMA_BATCH_SIZE = 12` and `skip_uncoachable=get_tuning().layer_d.skip_uncoachable_milestones`
  (currently `true`) are read from the same places production reads them, so the arms match
  `arm3_run1_20260810` rather than a hand-set variant.
- **Soft-skill scoring is skipped.** It answers a different question and would double the
  call count. `score_soft_skills` stays `true` in `tuning.yaml`; this script simply does not
  call that function.
- `scored_by` is captured per verdict and its distribution printed **per arm**. If
  flash-lite was rate-limited and `gemma-4-31b-it` answered part of one arm, the arms are not
  comparable and that must be visible rather than inferred later.

### Benchmark construction, and its two known failure modes

Implemented in the calibration script as:

```python
pool = storage.get_responses_for_scenario_multilabel(conn, S)
pool = [r for r in pool if r["call_filename"] != held_out_call]
top  = rubric_lookup.rank_benchmark_responses(pool, S_info, 2)
text = "\n\n".join(r["response_text"] for r in top)
```

This reproduces `get_benchmark_reference`'s body while reusing the unchanged ranking
primitive, rather than adding an `exclude_calls` parameter to production code.

Both degenerate cases are **counted and reported**, never absorbed:

1. A pool of ≤2 rows hits `rank_benchmark_responses`'s own `len(responses) <= limit`
   short-circuit, which returns rows unranked and **without** `scenario_similarity`. This is
   the exact self-inflicted harness bug that made `dry_run_ego_trap.py`'s chosen-vs-discarded
   band silently read "no data"; the field is never accessed unconditionally.
2. An empty pool yields `benchmark_response = ""`, changing the prompt's shape. The count of
   such items is printed per arm.

Because the holdout is per-call, the benchmark cache is keyed
`(scenario_key, held_out_call)`, not `scenario_key` as in `pipeline.py`.

---

## 4. What each outcome means, and what it does not

- **A1 high, A3 high** → rubrics are satisfiable and the scorer detects satisfaction. The
  CSM gap is real. Resume tuning.
- **A1 high, A3 low** → the rubrics recognise only the calls they were built from. This is
  *overfitting, not brokenness*, it is absent from the original two-way fork, and its remedy
  is in Layer C (cluster granularity, description generality) — not in the Step 3 prompt or
  the scorer. Running A3 alone cannot distinguish this from the next row, and the two demand
  opposite responses; that is why A1 is scored even though its number is known to be inflated.
- **A1 low, A3 low** → rubric or scorer is fundamentally broken.
- **A1 low, A3 high** → incoherent; treat as a harness bug, not a finding.

### Confounds that favour Naren and are stated, not corrected

A high Naren score is an **upper bound**, for three reasons that this design deliberately
does not remove:

1. **Step 0 is bypassed.** Naren's arm is handed the scenario from `kb_pairs`, so it never
   suffers the Step 0 false positives Madhumita's run did (a URL-configuration exchange
   matched to `contract_renewal_anxiety` and scored against a milestone about "middle person"
   perception). Isolating Step 3 is the goal; the asymmetry is the price.
2. **The response text is built by different code.** `extract_pairs` filters each of Naren's
   turns through `_is_substantive` (≥5 alphabetic non-stop tokens) before joining
   ([`v1/layer_b.py:54`](../../../Brain/v1/layer_b.py)), while `extract_csm_response_window`
   joins every CSM turn verbatim. Naren's text is therefore cleaner than the window
   Madhumita was scored on.
3. **Leak 2 is bounded, not eliminated** — see §2's precision note.

Consequently: `W(A3) ≥ 0.50` licenses "the rubrics are satisfiable", **not** "the entire
3.1%-to-ceiling distance is CSM skill". Attributing that distance requires separately
measuring Step 0 precision and the response-window shape, which are follow-on work.

### The noise floor governs how finely this may be read — MEASURED 2026-08-11

`measure_scoring_noise.py`, two identical 19-transcript Layer D runs, nothing changed between
them (`arm3_run1_20260810` vs `public`):

```text
run A  889 attempts | 28 hits (3.1%) | 76 partial | weighted 0.074
run B  905 attempts | 31 hits (3.4%) | 73 partial | weighted 0.075

aggregate weighted drift : +0.000
attempt-count drift      : +1.8%
MOVEMENT RATE            : 37/237 milestones (15.6%)
   improved 18 (+3.30) | worsened 19 (-2.73) | net +0.56
   |delta| median 0.12, max 0.50; 24% of movers have <=2 attempts
```

The floor is **15.6%**, not the ~25% an earlier partial read suggested. Three rules follow:

1. **Aggregate arm comparisons are safe.** Weighted drift across identical runs is `+0.000`,
   so §1's 0.20 / 0.50 thresholds sit orders of magnitude outside the floor and the fork is
   decidable.
2. **Per-milestone winners and losers remain uncitable individually** — 15.6% against any
   plausible effect size is too close.
3. **Direction of an asymmetric aggregate shift is citable**, which is a stronger conclusion
   than "per-milestone results are noise, so nothing is". The floor moves 18 up / 19 down for
   a net of +0.56 — symmetric, as noise must be. The criteria rewrite moved 43 up / 17 down
   for +4.48. Shape, not just rate, separates signal from variance, and the reporting in §6
   states up/down/net for every arm comparison so the shape is always visible.

**Consequence for this design's sampling.** The movement is not diffuse instability, it is
arithmetic on small denominators: all 12 of the largest moves had ≤4 attempts. At 8 items per
scenario per arm each milestone gets ≤8 attempts, which is thin by the same standard. So:

- The "milestones even the author cannot satisfy" list (§6.4) requires **0 full hits AND 0
  partial hits at ≥6 attempts** — a milestone showing partials is being *approached*, and the
  floor's median |delta| of 0.12 is exactly the size of a partial flip at these denominators.
- Every per-milestone table reports the attempt count beside the score, and milestones at ≤2
  attempts are listed in a separate block, never mixed into the main body.

### Every number is read before it is believed

This session's three largest findings all came from reading transcripts and rubric text, not
from a summary statistic. So before any verdict in §1 is acted on, ≥10 real
`reason` / `quote` / `gap_to_ideal` triples are read per arm, including the highest-scoring
items in arm B (if the mismatched control scores anything, its reasons say why).

---

## 5. Zero-write guarantee — enforced, not promised

The live DB must not change. Four mechanisms, in order of strength:

1. **Session-level read-only transaction.** Immediately after `storage.get_connection`, the
   script issues `SET SESSION default_transaction_read_only = on`. Any `INSERT` / `UPDATE` /
   `CREATE` then fails with an error from Postgres rather than succeeding. This is what
   protects against a *future* edit accidentally introducing a write, which a code-review
   promise does not.
2. **`ego_trap.gap_output` is never imported.** Every write path in Layer D
   (`upsert_milestone_performance`, `insert_gap_event`, `upsert_csm`,
   `upsert_signal_recognition_gap`) is reached through that module. Not importing it means no
   write function is in scope. No `csms` row is created for Naren.
3. **`checkpoint` is never imported.** `checkpoints.db` is not touched, so this run cannot
   mark any transcript done and cannot interfere with a resumed Layer D run.
4. **`--dry-run` is the default.** It makes **zero Gemma calls**: it prints embed-cache
   coverage, the sampling plan with achieved N per scenario, the A3 eligibility count and
   whether the ≥6-in-≥15 gate still passes, the arm-B pairings with their cosines,
   degenerate-benchmark counts, and the Gemma call estimate — then exits. Scoring requires an
   explicit `--run`.

Results are persisted to `Brain/artifacts/naren_ceiling.json` (disk, not DB; the directory
is gitignored) and `--load PATH` re-reports at zero cost — the established pattern from
`labeled_trigger_quality_sample.json` and `layer_c_admitted_replay.json`.

`arm3_run1_20260810` is the CSM baseline for every comparison. **`public` must not be used**
as that baseline: as of 2026-08-11 it holds the *second* arm of the completed noise-floor run
(905 attempts against arm3's 889), so quoting it would silently compare against a different
arm of a variance experiment. Read the CSM number from the snapshot, always.

### CPU and memory safety, given a concurrent run

The embedding work is a warm-cache **SQLite read, not a GPU pass**: `_embed_matrix` reaches
`_get_model()` only inside `if missing:` ([`preprocessing/embedder.py:78`](../../../Brain/preprocessing/embedder.py)),
and every text involved was already `embed_document`-ed at `prefix=""` during the production
run — the responses by `layer_b.embed_and_store_pairs`, the scenario vectors by
`_build_scenario_vecs`, which is the same prefix `scenario_vec` uses. So the 392MiB
`en_core_web_lg`-class model load never happens.

The residual risk is that `import torch` alone costs address space, the documented
`[WinError 1455]` failure mode. Two guards:

- A **torch-free pre-flight check** reads coverage directly via `shared.embed_cache`
  (sqlite3 + hashlib only, no torch import) and **aborts** if coverage is not 100%, so the
  script can never silently begin encoding a corpus while another run holds memory.
- The scoring run is sequenced **after** the noise-floor run completes — which is also the
  better order, since the floor changes how the ceiling number may be read.

---

## 6. Reporting

1. **Headline table** — A1 / A3 / B / Madhumita `arm3_run1_20260810`, each with
   attempts, full hits and rate, partial hits and rate, `W`, and item count. Plus the §1
   verdict rows evaluated explicitly, with the `W(B)` validity gate checked first.
2. **Leak size** — `W(A1) − W(A3)`, and the same per scenario, so a single scenario driving
   the difference is visible.
3. **Paired per-milestone** — for each `(rubric_id, milestone_id)`, Naren's A3 `W` beside
   Madhumita's, joined the way `compare_criteria_ab.py` joins
   (`rubric_id`, `milestone_id`, plus `csm_id` on her side). Flagged, not ranked, when the
   noise floor forbids per-milestone claims.
4. **Milestones even the author cannot satisfy** — 0 full hits **and 0 partial hits** in A3 at
   ≥6 attempts, with `support_calls` and description. The partial-hit condition is required by
   the measured noise floor: a milestone scoring partials is being approached, and a partial
   flip is exactly the size of the floor's median move at these denominators. This is the
   highest-value output — a stronger and better-evidenced indictment than the 17 already
   flagged by `ops/flag_uncoachable_milestones.py`, because it is measured rather than judged.
5. **Provenance** — `scored_by` distribution per arm, id-shortfall warnings from
   `score_milestones_batch`, degenerate-benchmark counts, achieved N per scenario.

---

## 7. Explicit non-goals

- **The text-shape diagnostic is out of scope** (comparing Naren's `_is_substantive`-filtered
  `response_text` against Madhumita's verbatim window, rebuilt from
  `gap_events.call_id` + `signal_turn_index`). It is free and worth doing, and it is
  deliberately not in this deliverable — recorded here so it is not silently reintroduced
  mid-implementation.
- **No Layer C re-run** to recover true clause provenance: not reproducible across process
  launches, and it would move the baseline being explained.
- **No Step 0 measurement.** The ceiling bypasses signal detection by design.
- **No production code change.** No new `tuning.yaml` key, no new column, no signature change
  to `get_benchmark_reference` or anything in `ego_trap/`.
- **No tuning of anything** on the strength of this result until §1's verdict is read against
  the noise floor and the sample verdicts.

---

## 8. Cost

49 scenarios, up to 8 items each per arm.

| arm | items | Gemma calls @ batch 12 |
| --- | --- | --- |
| A1 | ~392 | 33 |
| A3 | ~344 | 29 |
| B | ~392 | 33 |
| **total** | **~1,128** | **~95** |

~19% of one key's 500/day. `--dry-run` costs nothing.

Up from the ~54 quoted in the first draft: 49 scenarios rather than 27 adds ~1.8×, partly
offset by dropping the A2 arm. Output-token headroom stays comfortable — the measured batch-12
budget of ~18,803 tokens assumed a mean of 6.1 milestones per rubric, and these rubrics average
below that. The dry run prints the real per-arm call count before anything is spent.

---

## 9. Verification plan

`score_milestones_batch` is unchanged, so no test covers it here. The new, testable surface
is the sampling and holdout logic, which is pure and separable:

- **Benchmark holdout** — a hand-built pool proves every row from the held-out call is gone
  and that the response under test cannot appear in its own benchmark.
- **Label strata** — hand-built `scenario_key` / `scenario_keys[]` rows prove A1 selects only
  scalar matches, A3 only array-without-scalar matches **whose call contributes no scalar match
  for that scenario**, and that the two strata never intersect. The A3 case that matters most
  is the one §2 measured: a pair with a secondary label whose *sibling* pair in the same call
  holds the scalar label must be excluded.
- **Derangement** — no scenario is paired with itself, and no pairing survives with cosine
  ≥ 0.85, against hand-built vectors (the `test_layer_b_assignment` precedent: test the rule
  with orthogonal unit vectors, not the embedding model).
- **Degenerate benchmarks** — pools of size 0, 1 and 2 are handled without touching
  `scenario_similarity`, pinning the `dry_run_ego_trap` harness bug so it cannot recur.
- **Read-only enforcement** — an attempted write on the configured connection raises. This is
  the one test that touches Postgres; it asserts the failure, so it cannot itself write.

Run file-by-file, per the documented 16GB-Windows spaCy constraint.
