# Establishing the Layer D ceiling: score Naren against his own rubrics

**Date:** 2026-08-11
**Status:** design approved, not yet implemented
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
| `W(A2) ≥ 0.50` | rubrics and scorer work | the CSM gap is real; coaching content is buildable; resume tuning |
| `W(A2) < 0.20` | rubric or scorer is fundamentally broken | no CSM number means anything; every fix so far treated a symptom |
| `0.20 ≤ W(A2) < 0.50` | inconclusive | do **not** tune; read verdict samples and decide from them |
| `W(A1) − W(A2) ≥ 0.20` | rubrics are overfit to their own source calls | a Layer C problem, not a prompt or scorer problem — see §4 |
| `W(B) ≥ 0.5 × W(A2)` | **the instrument is invalid** | the scorer does not discriminate; no other row above may be cited |

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

#### Precision about what this holdout does and does not claim

It holds out **the response**, which is the object being graded. It does **not** hold out the
call: call `45ee54f7…` may contain other pairs whose scalar key *is*
`implementation_timeline_feasibility`, and those did feed the cluster. Nor is it a novelty
holdout — a secondary response is still Naren, still on-topic, and its clauses may closely
resemble primary ones. The claim is narrow and exact: *the words being graded did not write
the criterion.*

A stricter stratum is possible (§3, arm A3) and its population will be counted before it is
used.

---

## 3. Design: three arms over one sample, plus one conditional arm

| arm | response population | rubric scored against | benchmark | isolates |
| --- | --- | --- | --- | --- |
| **A1** | Naren, **primary** label | the response's own scenario | own scenario, call held out | leaked ceiling — upper bound |
| **A2** | Naren, **secondary** label | the scenario it is secondary to | that scenario, call held out | **clean ceiling — the headline** |
| **B** | the same texts as A1 | an **unrelated** scenario | that scenario, call held out | scorer specificity |
| **A3** | secondary label **and** zero primary pairs from the same call | that scenario | same | call-level derivation holdout |

**A3 is conditional and pre-committed:** it is included only if the population supports ≥6
items for ≥15 of the 27 scenarios. Otherwise its count is printed and the arm is dropped —
a stratum with 2 samples in it is worse than an absent one, because it will be quoted.

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

- **Scope:** the 27 rubrics Madhumita was actually scored on, so every comparison is paired
  per `(rubric_id, milestone_id)` against `arm3_run1_20260810`. All 27 have both primary and
  secondary pairs available. Widening to all 82 rubric'd scenarios later is a flag change.
- **Size:** up to 8 responses per scenario per arm. Real availability is respected and the
  achieved N is printed per scenario — `client_shares_subjective_perception` has only 4
  secondary pairs, so A2 lands near 212 items against A1/B's 216.
- **Selection:** seeded random, `random.Random(20260811)`. **Not** top-scenario-similarity:
  ranking by similarity selects the most prototypical responses and would inflate the
  ceiling. Selected `pair_id`s are persisted so the sample is reproducible exactly.
- **The unit of an item is `(response, scenario)`, not `response`.** Sampling iterates
  scenarios and draws from each scenario's own pool, so a pair carrying two secondary labels
  can legitimately appear twice in A2 — once per scenario it is being scored against. That is
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

- **A1 high, A2 high** → rubrics are satisfiable and the scorer detects satisfaction. The
  CSM gap is real. Resume tuning.
- **A1 high, A2 low** → the rubrics recognise only the calls they were built from. This is
  *overfitting, not brokenness*, it is absent from the original two-way fork, and its remedy
  is in Layer C (cluster granularity, description generality) — not in the Step 3 prompt or
  the scorer. Running A2 alone cannot distinguish this from the next row, and the two demand
  opposite responses.
- **A1 low, A2 low** → rubric or scorer is fundamentally broken.
- **A1 low, A2 high** → incoherent; treat as a harness bug, not a finding.

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

Consequently: `W(A2) ≥ 0.50` licenses "the rubrics are satisfiable", **not** "the entire
3.1%-to-ceiling distance is CSM skill". Attributing that distance requires separately
measuring Step 0 precision and the response-window shape, which are follow-on work.

### The noise floor governs how finely this may be read

A companion run (`measure_scoring_noise.py`, two identical Layer D runs) is measuring how
much Layer D moves when nothing changes; early partial data suggested a ~25% per-milestone
movement rate. Whatever it reports:

- Aggregate arm comparisons are only citable if the gap exceeds the floor's net drift.
- **Per-milestone winners and losers are not citable at all** if the floor's movement rate
  approaches the effect size, which for a ~25% floor it does.
- Milestones with ≤2 attempts are reported separately, since one verdict flip moves their
  score by 0.5 or 1.0.

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
   coverage, the sampling plan with achieved N per scenario, the A3 population count, the
   arm-B pairings with their cosines, degenerate-benchmark counts, and the Gemma call
   estimate — then exits. Scoring requires an explicit `--run`.

Results are persisted to `Brain/artifacts/naren_ceiling.json` (disk, not DB; the directory
is gitignored) and `--load PATH` re-reports at zero cost — the established pattern from
`labeled_trigger_quality_sample.json` and `layer_c_admitted_replay.json`.

`arm3_run1_20260810` is the CSM baseline for every comparison. **`public` must not be used**
— the noise-floor run is currently mid-flight rewriting it (258 attempts and climbing
against the completed run's 889).

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

1. **Headline table** — A1 / A2 / B / (A3) / Madhumita `arm3_run1_20260810`, each with
   attempts, full hits and rate, partial hits and rate, `W`, and item count. Plus the §1
   verdict rows evaluated explicitly, with the `W(B)` validity gate checked first.
2. **Leak size** — `W(A1) − W(A2)`, and the same per scenario, so a single scenario driving
   the difference is visible.
3. **Paired per-milestone** — for each `(rubric_id, milestone_id)`, Naren's A2 `W` beside
   Madhumita's, joined the way `compare_criteria_ab.py` joins
   (`rubric_id`, `milestone_id`, plus `csm_id` on her side). Flagged, not ranked, when the
   noise floor forbids per-milestone claims.
4. **Milestones even the author cannot satisfy** — 0 full hits in A2 at ≥6 attempts, with
   `support_calls` and description. This is the highest-value output: a stronger and
   better-evidenced indictment than the 17 already flagged by
   `ops/flag_uncoachable_milestones.py`, because it is measured rather than judged.
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

| arm | items | Gemma calls @ batch 12 |
| --- | --- | --- |
| A1 | ~216 | 18 |
| A2 | ~212 | 18 |
| B | ~216 | 18 |
| A3 (conditional) | TBD by dry run | ≤18 |
| **total** | **~644** | **~54, ~72 with A3** |

~11% of one key's 500/day. `--dry-run` costs nothing. Output-token headroom is comfortable:
the measured batch-12 budget of ~18,803 tokens assumed a mean of 6.1 milestones per rubric,
and these 27 rubrics average ~4.8.

---

## 9. Verification plan

`score_milestones_batch` is unchanged, so no test covers it here. The new, testable surface
is the sampling and holdout logic, which is pure and separable:

- **Benchmark holdout** — a hand-built pool proves every row from the held-out call is gone
  and that the response under test cannot appear in its own benchmark.
- **Label strata** — hand-built `scenario_key` / `scenario_keys[]` rows prove A1 selects only
  scalar matches, A2 only array-without-scalar matches, and that the two strata never
  intersect.
- **Derangement** — no scenario is paired with itself, and no pairing survives with cosine
  ≥ 0.85, against hand-built vectors (the `test_layer_b_assignment` precedent: test the rule
  with orthogonal unit vectors, not the embedding model).
- **Degenerate benchmarks** — pools of size 0, 1 and 2 are handled without touching
  `scenario_similarity`, pinning the `dry_run_ego_trap` harness bug so it cannot recur.
- **Read-only enforcement** — an attempted write on the configured connection raises. This is
  the one test that touches Postgres; it asserts the failure, so it cannot itself write.

Run file-by-file, per the documented 16GB-Windows spaCy constraint.
