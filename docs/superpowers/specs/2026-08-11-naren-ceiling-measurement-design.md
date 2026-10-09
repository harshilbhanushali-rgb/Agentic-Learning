# Establishing the Layer D ceiling: score Naren against his own rubrics

**Date:** 2026-08-11
**Status:** design approved, not yet implemented. Amended the same day after measuring the
holdout populations — scope corrected 27 → 49 scenarios, the plain secondary-label arm dropped
in favour of the stricter call-level one, cost ~54 → ~95 Gemma calls. The companion noise-floor
number is now measured on clean data (§4): aggregate drift 0.006, per-milestone movement 15.6%.
That confirms the fork is decidable — the thresholds are 30–80× the drift — and it corrected an
earlier claim in §4 that mover *shape* separates signal from noise.
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

### The noise floor governs how finely this may be read — MEASURED CLEAN 2026-08-11

Third attempt, after the first two were void (see below). `measure_scoring_noise.py` now
checks its own precondition first, and **both arms passed as exactly one run each**:

```text
arm3_run1_20260810   clean          public   clean          (zero duplicated signals)
run A   889 attempts | 28 hits (3.1%) | 76 partial | W 0.074
run B   889 attempts | 33 hits (3.7%) | 77 partial | W 0.080

aggregate weighted drift : +0.006
attempt-count drift      :  0.0%      milestones in only one run: 0
MOVEMENT RATE            : 37/237 (15.6%)
   improved 24 (+3.88) | worsened 13 (-1.76) | net +2.12
   |delta| median 0.12, max 1.00; 16% of movers have <=2 attempts
   movers with >=6 attempts on BOTH sides: 15
```

Three rules follow, and the second **corrects an earlier draft of this section**:

1. **Aggregate arm comparisons are safe, and the fork is decidable.** Aggregate drift across
   identical runs is 0.006. §1's thresholds at 0.20 and 0.50 are 30–80× that, so no plausible
   variance explains landing on either side of them.

2. **Shape does NOT cleanly separate signal from noise — an earlier draft claimed it did, and
   the clean floor refutes that.** The claim was that noise moves milestones up and down about
   equally, so the criteria rewrite's lopsided 43-up/17-down was therefore evidence. But the
   clean floor is *also* lopsided:

   | | up : down | net | aggregate W drift |
   | --- | --- | --- | --- |
   | noise floor | 1.85 : 1 | +2.12 | +0.006 |
   | criteria rewrite | 2.53 : 1 | +4.48 | +0.025 |

   The rewrite is ~2× the floor on net and ~4× on aggregate drift — real, but the same order of
   magnitude rather than the decisive gap the earlier wording implied. The floor's own 24/13
   split is not statistically distinguishable from even (binomial p≈0.11), yet it is not tight
   around zero either, so it cannot serve as a sharp null. §6 still reports up/down/net per
   comparison, but as context rather than as a test.

3. **Small hit-rate differences are noise.** Identical config produced 28 vs 33 full hits —
   3.1% vs 3.7%, an 18% relative swing — so the CSM's headline rate carries roughly ±0.6pp at
   this sample size. Only a large `W(A3)` means anything, which is why §1's thresholds are set
   where they are rather than at "better than the CSM".

**Consequence for this design's sampling.** The movement is arithmetic on small denominators,
not diffuse instability: |delta| max is 1.00 (a 1-attempt milestone flipping outright), and
only 15 of 237 milestones have ≥6 attempts on both sides. At 8 items per scenario per arm each
milestone here gets ≤8 attempts, which is thin by the same standard. So:

- The "milestones even the author cannot satisfy" list (§6.4) requires **0 full hits AND 0
  partial hits at ≥6 attempts**.
- Every per-milestone table reports the attempt count beside the score, and milestones at ≤2
  attempts go in a separate block, never mixed into the main body.

#### Why the first attempt was void — kept because the failure mode is the lesson

Two Layer D runs wrote to the same database concurrently. The first run was believed dead
because the harness reported its background task as stopped — but that is the harness's own
bookkeeping, not the OS process state, and the Python process was still alive and still
marking transcripts done in `checkpoints.db`. The Layer D tables were then cleared and a
second run launched, which read the first run's checkpoints and skipped 10 of 19 transcripts
as already complete. The result is a blend, and the run still printed
`Ego Trap batch complete`.

Verified rather than assumed: `public.gap_events` carries **28 duplicate groups** on
`(call_id, scenario_key, signal_turn_index)` — the same signal scored twice — against
**zero** in `arm3_run1_20260810`. Because `upsert_milestone_performance` does
`attempts = attempts + 1` on conflict, that inflated attempts to 905 against the clean run's
889. Both runs used the same model (all verdicts `gemini-3.1-flash-lite`), so the model is not
a confound; the duplication is.

**Nothing this design depends on was affected.** The contamination is confined to Layer D's
four tables, which are wiped before every run by design. `kb_pairs`, `scenarios`, `rubrics`
and `primary_topics` are untouched, so §2's holdout populations, §3's 49-scenario scope and
the `W = 0.074` baseline in `arm3_run1_20260810` all stand — every one of those was read from
a clean source.

**And the floor is recoverable without spending Gemma calls again.** `gap_events` stores
per-signal `milestones_hit` / `milestones_partial_hit` / `milestones_missed`, so
`milestone_performance` can be rebuilt from it by counting array membership. Verified faithful
on the clean arm: the rebuild reproduces `arm3_run1_20260810`'s stored counters exactly
(889 attempts / 28 hits / 76 partial / 237 rows, identical). Deduplicating the blended arm by
`(call_id, scenario_key, signal_turn_index)` returns it to **889 attempts, matching arm3**,
and the choice of which duplicate to keep changes the result by a single partial hit. So a
future floor can be computed from data already on disk.

**One durable fix landed, one still open.** `measure_scoring_noise.py` now counts duplicate
`(call_id, scenario_key, signal_turn_index)` groups in both arms and **refuses to report a
floor** when any exist — it silently reported one, which is the same class of self-inflicted
harness error as the merge-blind `_match_milestones` and `dry_run_ego_trap`'s "no data" band.
It also gained `--dedup`, which rebuilds counters from `gap_events` keeping one verdict per
signal, and self-checks that the *un*deduplicated rebuild reproduces the stored counters
exactly before reporting anything. That check is what makes the salvage defensible rather than
plausible, and it passed on the clean arm at 889/28/76 across 237 rows.

Still open, not built: `ops/run_ego_trap.py` should refuse to start while another process holds
`checkpoints.db`. `ops/run_noisefloor.ps1` and `ops/run_naren_ceiling.ps1` both guard by
scanning command lines, but the guard belongs in the Python entry point too, since a hand-run
`python ops/run_ego_trap.py` bypasses both scripts. **A stopped background task is not a dead
process** — that is the whole lesson, and two `python.exe` PIDs in a parent/child pair are one
run, because the venv shim re-execs the base interpreter. Different parents means two runs.

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

`arm3_run1_20260810` is the CSM baseline for every comparison. **`public` must not be read for
the CSM number, under any circumstances.** It is the working target of whatever Layer D run is
current, so at any moment it may be mid-flight (partial, and indistinguishable from complete),
freshly cleared, or — as of 2026-08-11 — a blend of two concurrent runs with 28 duplicated
signals. Every one of those states looks like a finished run when you `SUM(attempts)` it. Read
the CSM number from a snapshot schema, always.

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
   ≥6 attempts, with `support_calls` and description. The partial-hit condition is not a
   noise-floor concession but a semantic one: a milestone scoring partials is being
   *approached*, so it is gradable and the criterion is reachable — the claim "nobody can
   satisfy this" requires that nobody got near it. This is the highest-value output, a stronger
   and better-evidenced indictment than the 17 already flagged by
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

## 9. RESULT (2026-08-11) — the instrument is invalid, and the criteria are scenario-agnostic

Run: `ops/run_naren_ceiling.ps1`, 49 scenarios, seed 20260811, `skip_uncoachable=True`,
artifact `Brain/artifacts/naren_ceiling.json`, log `logs/naren_ceiling_20260811_*.log`.
One batch of 32 failed on malformed JSON, costing A1 12 of 383 items; nothing else failed.

| arm | attempts | full hits | partials | **W** |
| --- | --- | --- | --- | --- |
| **A1** primary label (leaked) | 1834 | 187 (10.2%) | 215 (11.7%) | **0.161** |
| **A3** call-level holdout (clean) | 1806 | 92 (5.1%) | 228 (12.6%) | **0.114** |
| **B** unrelated rubric (control) | 1833 | 68 (3.7%) | 124 (6.8%) | **0.071** |
| CSM `arm3_run1_20260810` | 889 | 28 (3.1%) | 76 (8.5%) | 0.074 |

### The validity gate trips, and it survives the one confound that could have explained it

`W(B) = 0.071 ≥ 0.5 × W(A3) = 0.057`. **Instrument invalid.** Per §1 this is checked first and
no other number may be cited as a measurement.

Arm B had a real model confound — A1 and A3 were 100% `gemini-3.1-flash-lite`, but B came back
793 verdicts `gemini-3.1-flash-lite` + 1040 `gemini-3.5-flash-lite`, the fallback chain firing
under rate limits. This is exactly what the per-arm `scored_by` reporting exists to catch, and
it had to be resolved before the gate could be believed. Splitting B by scorer **makes the
result worse, not better**:

```text
B | gemini-3.1-flash-lite   793 att | 38 hit (4.8%) | 66 part | W 0.090   <- same model as A1/A3
B | gemini-3.5-flash-lite  1040 att | 30 hit (2.9%) | 58 part | W 0.057   <- stricter
GATE on the same-model subset: 0.090 >= 0.057  -> STILL INVALID
```

So the fallback model was *masking* the problem. On an apples-to-apples comparison the
unrelated-rubric control reaches **W 0.090 against a matched 0.114** — a signal-to-null ratio
of 1.27 : 1. And the CSM's own 0.074 sits **below** what scoring Naren against a deliberately
unrelated rubric produces. The CSM number was never measuring coaching performance; it sits at
or under the instrument's null.

### Why — read from arm B's full hits, not inferred from the numbers

The scorer is not being lazy. The criteria are **genuinely scenario-agnostic**, so a response
from a different scenario legitimately satisfies them. Verbatim from arm B, where a response
about `ai_capability_discovery` was scored against `client_resistance_and_constraints`:

> **M2** *Explain the practical utility of the tool in handling immediate tasks and illustrate
> this value through concrete examples of real-world application.*
> → "The CSM explains the utility of the analytics dashboard and provides concrete examples of
> tracking candidate journeys and drop-offs." **full_hit**
>
> **M9** (`candidate_screening_capability_discovery`, response really about
> `ats_integration_architecture_discovery`) *Use open-ended questions to uncover the functional
> flow and required mechanics of a system or implementation format.*
> → "The CSM uses questions to uncover the mechanics of the integration with Bullhorn."
> **full_hit**

Those verdicts are *correct*. Nothing in either criterion mentions client resistance, or
screening, or anything that distinguishes one scenario from another — they describe generic
consultative behaviour that any competent technical discovery response exhibits.

**This localises the defect to the 2026-08-10 criteria rewrite, which over-corrected.** Before
it, descriptions were narration about one person ("He uses hypothetical numerical examples of
job slots…") — unhittable by anyone else. The rewrite removed names, pronouns and specifics to
make them transferable, and went far enough that they stopped identifying a *situation*. The
milestones moved from **too specific to one person** to **too generic to one scenario**. Both
fail; the second fails less visibly.

It also retroactively explains that rewrite's most-cited signal. Partials doubled (32 → 73)
while full hits barely moved (21 → 29), which was read as "the rubric became gradable". A
simpler reading now fits: generic criteria are easy to partially satisfy with almost anything.

### A quarter of the rubric is unreachable by its own author

Measured in A3, with 8 attempts per milestone:

| | milestones scored | 0 full **and** 0 partial | 0 full |
| --- | --- | --- | --- |
| A1 (leaked) | 232 | 50 (22%) | 121 (52%) |
| A3 (clean) | 235 | **65 (28%)** | **154 (66%)** |

Two thirds of milestones are never fully satisfied by the expert whose corpus produced them,
even in the leaked arm. The 17 already flagged by `ops/flag_uncoachable_milestones.py` were a
severe underestimate.

### What this settles, and what it does not

- **Settled: the primary fork resolves to "broken measurement", not "real coaching gap".** Both
  pre-registered failure conditions fired independently — `W(A3) = 0.114 < 0.20`, and the
  validity gate. Every Layer D hit-rate number produced to date, including the 2.4% → 3.1%
  improvement arc, is uninterpretable as CSM performance.
- **Settled: derivation leakage was not the problem.** `W(A1) − W(A3) = +0.047`, under the 0.20
  overfit threshold — though a 41% relative inflation is not nothing, and it does confirm the
  A3 holdout was worth building.
- **Not settled: whether milestone scoring can be fixed by better criteria, or whether the
  milestone is the wrong unit of feedback.** The result is consistent with both. Deciding needs
  the §7-deferred work, not another threshold pass.
- **Do not tune anything on the strength of these numbers.** The gate forbids citing them as
  measurements. Their value is the diagnosis, which came from reading arm B's verdicts.

### The aggregate hid the real structure: Layer C is BIMODAL, not uniformly broken

The global `W(A3) 0.114` vs `W(B) 0.071` is an average over two populations that behave in
opposite directions. Per scenario, matched minus unrelated, ≥15 attempts on each side (40 of 49
scenarios qualify):

```text
gap      A3 W   B W    scenario
+0.271   0.271  0.000  ats_integration_requirement
+0.250   0.261  0.011  budget_and_spend_disclosure
+0.188   0.188  0.000  url_redirection_configuration
+0.188   0.188  0.009  job_board_ecosystem_discovery
+0.125   0.125  0.000  ai_capability_discovery
+0.125   0.125  0.000  competitor_comparison_appcast
+0.104   0.104  0.000  pixel_implementation_discovery
   ...
-0.089   0.143  0.232  client_segments_requirements
-0.125   0.042  0.167  client_admits_lack_of_familiarity
-0.172   0.156  0.328  client_seeks_process_momentum
-0.229   0.167  0.396  client_reacts_to_anomaly

16 of 40 discriminate clearly (gap > +0.05)
 7 of 40 are INVERTED — the unrelated rubric scores HIGHER than the matched one
```

**What separates the two halves — tested, and the obvious proxy does NOT work well enough to
route on.** The apparent pattern is that scenarios named for *subject matter* (ATS integration,
budget, URL redirection, job boards, pixels, competitors) carry **content**-based milestones,
and content is scenario-specific by construction, while scenarios named for a *client posture*
(reacts to anomaly, seeks momentum, admits unfamiliarity) carry milestones about **universal
conversational moves**. Measured against the name shape:

```text
                   n    mean gap   median   discriminating   inverted
client-posture    15     -0.019    +0.008          5/15         5/15
subject-matter    25     +0.057    +0.045         11/25         2/25
```

The direction is real — inversion runs 33% for posture names against 8% for subject-matter names
— but this is **not a usable router**. Five of fifteen posture scenarios discriminate fine, and
fourteen of twenty-five subject-matter ones do not clearly. Do not build a rule on the name, or
on `cluster_kind` (uniform `scenario` across all 49 coachable rows, so it carries no signal
here either).

**The usable discriminator is the direct measurement, and it is cheap enough that no proxy is
needed.** Seven scenarios have a control score of exactly **0.000** — the unrelated rubric finds
nothing at all — and one of them (`client_expresses_conditional_dependency`) is posture-named,
which is the clearest evidence the name is not the rule:

```text
A3 0.271  B 0.000  ats_integration_requirement
A3 0.188  B 0.000  url_redirection_configuration
A3 0.125  B 0.000  ai_capability_discovery
A3 0.125  B 0.000  competitor_comparison_appcast
A3 0.104  B 0.000  pixel_implementation_discovery
A3 0.056  B 0.000  client_expresses_conditional_dependency
A3 0.031  B 0.000  location_targeting_configuration
```

For the inverted scenarios, no wording change helps, because "acknowledge the concern and probe
for specifics" is genuinely true of every good response — the scenario label carries no
information for those milestones.

**This is why three rounds of prompt tuning each moved the needle slightly and never broke 4%:**
the working half and the inverted half cancel in every global average. Every measurement to date
was taken on the average.

### Recommended next steps, in order

The bimodal result replaces the "rewrite ~10 milestones and re-test" plan that was written here
before the per-scenario split was known. Rewriting criteria globally would keep averaging over
the two populations.

1. **Measure per scenario; do not route on a proxy.** The name-shape and `cluster_kind` proxies
   were both tested above and neither separates the populations well enough to gate on. Arm B
   *is* the discriminator, it costs ~2 Gemma calls per scenario, and it is exact. Adopt
   `W(B) ≥ W(A3)` ⇒ this scenario gets no rubric. That is a property of the data rather than a
   curated list, which is what `tuning.yaml` requires of a knob.

2. **Ship the rubrics that pass.** ~16 scenarios already carry a working instrument, and 7 have a
   control score of exactly zero, at no additional Gemma cost. That is a usable coaching product
   today for the half that works.

3. **Stop retuning one describe prompt for both populations.** It is not wrong for the scenarios
   that pass — it produces what they need. No single prompt can serve both, because one half
   needs content specificity and the other has no content to be specific about. That is why three
   global tuning rounds each moved the average slightly.

4. **Change the unit for the failing half, do not reword it.** The inversion is the evidence:
   when an unrelated rubric outscores the matched one, per-scenario milestones are the wrong
   shape. Candidates are one shared conversational-moves rubric applied once rather than per
   scenario, or the scenario-level "was this handled?" judgement from §7's deferred list.

**A flaw in this harness that inflates the "unreachable" count, and is not yet quantified.** Some
milestones encode call-POSITION moves — introductions, agenda-setting, wrap-ups. One dead
milestone reads *"Define the speaker's professional role and explain the internal hand-off
process between solutions, onboarding, and customer success teams"* (and still says "the
speaker's", so the rewrite missed it). Responses were sampled uniformly, so an opening-move
milestone almost never met an opening response. Some share of the 65 zero-hit milestones is this
artifact rather than an unreachable criterion, and separating them needs turn position — which
`kb_pairs.turn_index` already carries, so the check is free.

### Corrected diagnosis, after three further free analyses the same night

Three offline analyses over `naren_ceiling.json` changed the causal account above. Two of my
own hypotheses died; the replacement is mechanically provable.

**1. The dominant cause of the low rate is CONTINGENCY, not wording.** Reading all 60 dead
pure-behaviour criteria, the shared property is not vagueness — it is an unstated
**precondition**: a call *position* (*"Define the speaker's professional role and explain the
internal hand-off process"* — an opening, and it still says "the speaker"; *"…utilize screen
sharing to visually demonstrate…"*), a client *history* (*"…the logic behind previous spending
decisions and trial processes"*), or an *artifact* (*"Reference internal data analysis…"*,
*"…involving external partners…"*). These are real recurring moves that are **contingent**, and
the rubric emits them as **mandatory**.

The mechanism meant to catch this is dead code:

```text
sequencing_type across 235 milestones:  fixed 234,  conditional 1
position_variance:  p50 0.098   max 0.240
the conditional trigger is > 0.3  ->  fires 0 of 226 times
```

CLAUDE.md records that Layer D deliberately never *acts* on `conditional`. The deeper problem is
that Layer C never *produces* it, so every response is graded against every milestone whether or
not the moment called for it. This is a scoring-model error, which is why rewording the criteria
twice did not help.

**2. Satisfiability and discrimination are INDEPENDENT axes.** Whether a criterion names its own
scenario's subject (measured token-wise against `scenario_key`, no curated list):

```text
subject tokens named   n     full%   dead
0 (pure behaviour)    179     3.8%   60/179 (34%)
1                      31    12.1%    4/31  (13%)
2+                      6    10.4%    1/6

correlation with the per-scenario A3-minus-B discrimination gap:  r = -0.038
```

Naming the subject triples the full-hit rate and cuts deadness by two thirds, yet has **no**
relationship to discrimination. **83% of criteria (179/216) are pure behavioural prose.** Fixing
one axis will not move the other, so a fix must target both deliberately.

**3. Two hypotheses recorded earlier are retracted.**

- *"Frequency may be anti-correlated with coachability"* — **wrong, it is uninformative.**
  `correlation(support_calls, W) r = -0.019`, and the buckets are flat: 3–9 calls W 0.110, 10–24
  W 0.133, 25–59 W 0.115, 60+ W 0.094 (n=4). **A milestone `ubiquity_ceiling` would be wasted
  work** — worth knowing before building it.
- *"Criteria discriminate because they name their subject"* — **wrong**, r = −0.038 as above.

**Revised cause list, in order of expected effect on the rate:**

1. No objective function for rubric quality *(root cause — addressed by the companion spec,
   `2026-08-11-layer-c-objective-function-design.md`)*
2. Contingent moves emitted as mandatory, conditional path firing 0/226 *(dominant proximate
   cause)*
3. The describe prompt is blind to the scenario and its siblings *(cause of the discrimination
   failure)*
4. Clause ≠ move — clustering finds topical proximity, not conversational function
5. For posture scenarios, no discriminating criterion exists to be found

The clustering itself remains sound: `W(A1) − W(A3) = +0.047` says the clusters are not artifacts
of specific calls.

---

## 10. Verification plan

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
