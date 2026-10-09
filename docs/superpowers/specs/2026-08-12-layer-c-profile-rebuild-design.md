# Rebuilding Layer C so the CSM profile measures something

**Date:** 2026-08-12
**Status:** design approved, nothing implemented
**Deliverable:** a four-arm trial that writes NOTHING to Postgres, plus the Layer C changes it
evaluates
**Depends on:** `2026-08-11-naren-ceiling-measurement-design.md` (the ceiling result and its
pre-registered gate), `2026-08-11-layer-c-objective-function-design.md` (built and measured
2026-08-12; both of its validity gates fired — see §7)

---

## 1. The problem, stated precisely

The purpose of the gap analysis is to **build a profile of where each CS person stands and teach
to it.** That profile today has **405 axes** — one per milestone — and two independent defects
make it unusable.

**The axes are too thin.** 20–50 calls per person yields roughly 8 observations per axis. No
criterion quality fixes that; it is arithmetic.

**The axes carry no signal.** Measured three times on 2026-08-12: the expert scores `0.114–0.116`
against his own rubrics and `0.090–0.095` against deliberately unrelated ones. At **1.2 : 1** the
criteria cannot tell one situation from another, so a per-scenario axis is not measuring the
scenario.

Both trace to one root cause, and it is not a wording problem. Read from
`v2/layer_c.py::_describe_milestones_batch` (:359-366), the model writing each criterion sees:

```text
SCENARIO: client_reacts_to_anomaly      <- the key string, nothing more
MILESTONE: 3 of 6                        <- position only
Clauses grouped into this cluster:       <- the expert's RESPONSE sentences
```

and is instructed to *"write EACH independently … do not let one item influence another"* and to
*"Generalise … never the specific instance"*.

So it never sees the client trigger, never sees its sibling moves, and never sees what the
scenario means. **It is blind by construction**, and then told to strip out the specifics that
would have identified the situation anyway. A fourth wording pass cannot work: it would ask a
model to encode information it was never given.

## 2. Scope

Three changes, adopted together, each operating on a different part of Layer C:

| | changes | Layer C stage |
| --- | --- | --- |
| **Inputs** | what the model is **shown** | before |
| **Unit** | what it **emits** | output |
| **Skills** | what we **do with** what it emits | a new pass on top |

Build order is forced — each consumes the one before it.

**Unchanged:** Layer A's clustering and adjudication; all of Layer B; the embed cache; Layer C's
own within-scenario clustering. That clustering is well evidenced — holding out the calls a
cluster was built from costs only `W(A1) − W(A3) = +0.047` — so the clusters are real. This design
changes what gets *written about* them.

**Explicit non-goal.** This does not fix Step 0's false positives, the 36% of gap events that are
recognition failures, or the response-window extractor. A coverage verdict on the wrong moment is
still garbage. Those belong to a separate path (probing via the simulator), and a perfect Layer C
leaves them in place.

## 3. Inputs — what Layer C gets shown

Five additions to the describe step:

1. **The client triggers** that prompted this cluster's response clauses (up to ~6, most central).
   The single most important one: a precondition cannot be written truthfully by a model that has
   never seen a client turn.
2. **The sibling moves in the same rubric**, so move 3 can be written to be distinguishable from
   move 5. This reverses *"do not let one item influence another"*, which was there to stop
   contamination between unrelated scenarios and is the wrong rule inside one rubric.
3. **The scenario's `business_description` and keyphrases**, not the bare key string. Already
   stored, simply never passed.
4. **The three nearest OTHER scenarios**, so a criterion can be written to exclude them.
   Precedent: `PROMPT_LAYER_A_V2_TRIAGE` already shows each cluster its nearest accepted
   neighbours for exactly this reason.
5. **A required precondition field**, grounded in the triggers shown.

### 3.1 The rule change that matters most

The 2026-08-10 rewrite banned two different things in one breath:

- *"Never name any person, never use he/she/they"* — **correct, keep.** This fixed the narration
  bug and the gain was ~4x the measured noise band.
- *"Never state the specific instance"* — **the over-correction, drop.** A criterion may name its
  subject matter. It still may not name a person.

Conflating them is what made the criteria scenario-agnostic.

### 3.2 Structural consequences

**Batching becomes per-scenario.** Siblings can only be shown if a rubric's milestones share a
call. Cost is unchanged: 405 / 5 = 81 calls today vs ~82 with one call per scenario.

**Provenance plumbing.** `build_clause_pool` gains a fourth return value mapping each clause to its
`pair_id`; `get_naren_responses_for_scenario` selects `trigger_text`. Both additive. Existing
callers and `tests/test_layer_c_clause_pool.py` are updated in the same change — the harness must
NOT reimplement the pool, per the Layer B sweep that disagreed with production 99.7% vs 14%.

### 3.3 Risk

Showing siblings invites the model to **invent** distinctions to look different. A manufactured
distinction inflates discrimination while making the criteria less true — the worst outcome,
because it passes the gate. Mitigated by labelling siblings as context-for-contrast, requiring the
criterion to stay grounded in its own clauses, and reading samples (§6).

## 4. Unit — coverage areas replace criteria

Per scenario, Layer C emits **3–4 coverage areas** instead of ~5 independently-written criteria.
The per-scenario batching from §3 already puts all of a scenario's clusters in one call; the model
sees every cluster, its triggers and the scenario description, and writes areas that between them
account for the clusters.

Each area carries:

- the behaviour, allowed to name its subject matter (§3.1)
- the precondition — when it is called for
- **which clusters it covers** — load-bearing, so `support_calls` / `support_clauses` survive and
  an area remains auditable back to "recurs in 22 calls" rather than becoming unfalsifiable prose
- 2–3 **verbatim** expert responses as exemplars — the teaching payload, and the deliberate
  reversal of "strip the specifics"

The 405 milestones are not deleted; they become the evidence layer beneath the areas.

### 4.1 Scoring: one explicit verdict per area, never a returned subset

**This is a correction learned the expensive way.** The obvious design — ask which areas the
response covered and take back a subset — is structurally identical to the applicability judge
built on 2026-08-12, which failed its own null (0.147 matched vs 0.120 unrelated, **1.22 : 1**,
indistinguishable from the broken scorer it was meant to fix). Diagnosis found two defects in the
asking, not the question:

1. The prompt *instructed* sparsity (*"returning every id is almost always wrong"*). The 36.5%
   empty answers and flat ~15% yes-rate may have been the instruction, not the data.
2. "Return a subset" invites picking a top few and stopping. The scorer that *does* separate signal
   asks for an explicit verdict on **every** id, at identical cost per call.

So: an explicit verdict per area.

### 4.2 The fourth verdict

Rather than a separate applicability pre-check — the question that failed — applicability becomes a
verdict the coverage judge can return:

| verdict | meaning |
| --- | --- |
| `covered` | did it |
| `partly_covered` | approached it |
| `not_covered` | the moment called for it and she did not |
| `not_called_for` | this moment did not require it |

One call, one judgement, and the judge sees the **trigger and the response** — so it can tell the
difference, which the trigger-only applicability judge structurally could not. `not_called_for`
drops out of the denominator, giving the contingency correction without the judgement that failed.

Weighting stays `(covered + 0.5 x partly) / attempts`, so numbers remain comparable to every
historical figure.

### 4.3 Identity and risk

Coverage areas get **positional ids** (`C1`, `C2`, …) for the same reason milestones do: a content
hash fragments a person's history every time Layer C rewords something.

Risk: collapsing 5 clusters into 3 areas can quietly **merge distinct moves** — the merge-blindness
that inflated an entire Layer C A/B while the milestone count went *up*. Because every area
declares its source clusters, a 4-into-1 collapse is visible in the artifact.

## 5. Skills — the profile's axes

```text
coverage areas  ->  abstract to topic-free behaviour  ->  embed  ->  cluster  ->  name
                          (one LLM pass, batched)                      (the skills)
```

The strip step is the trick. Measured 2026-08-12: clustering the 405 descriptions as written groups
them by **subject**, not behaviour — 290 of 338 clusters held a single scenario, and *"ask open
questions about budget"* separated from *"ask open questions about screening"* purely on the
topical object. Stripping the object is what makes behavioural similarity visible to the embedding.

### 5.1 The granularity is measured, never chosen

**No target count.** A threshold in this codebase is never a count of outputs — `MAX_CLUSTERS=150`
is the cautionary tale. The skill count is an output.

Sweep the clustering threshold and measure the whole curve in one pass (same shape as Layer C's
`(percentile, fraction)` grid, where one run evaluates every combination). Per candidate
granularity, measure four things:

1. **Discrimination per skill** — score responses against skill D vs an unrelated skill D'. This is
   the loop closing: the objective function chooses the granularity instead of a guess.
2. **Observations per skill** — the statistical power actually available.
3. **Stability** — re-derive on a resampled corpus; a vocabulary that reshuffles cannot carry a
   profile however well it discriminates once.
4. **Read the groups** — non-negotiable. `merge_cosine_threshold` was chosen by reading what each
   threshold fused, not by counting: at 0.80 it merged campaigns, sales teams, brands, markets and
   vendors while the count looked reasonable.

**The tension the curve exposes:** coarser gives more observations but risks skills so generic they
stop discriminating (the current failure in a new form); finer gives sharper skills but returns
toward thin axes. The sweep shows where they cross, if they cross.

### 5.2 The grid's columns

Rows are skills; columns are topic families. Columns cannot come from `primary_topic` as it stands
— measured 2026-08-12: **31 of 43 primary topics contain exactly one coachable scenario** and one
holds 21, so there is nothing to pool. For the trial, derive columns by clustering scenario vectors
and **report how they compare to `primary_topic`**; that comparison tells you whether the existing
hierarchy needs repair or replacement, which is currently unknown. Keeping it separate also means
the trial does not depend on a Layer A change.

### 5.3 Surviving the reshuffle

Layer C's clustering yields 385 / 398 / 403 / 404 milestones for byte-identical input, and the
standing verdict is to accept that variance. So **cluster identity is not stable**, and a skill
defined by cluster membership would be reshuffled — orphaning every profile — on each run.

**Skills are therefore defined by their text, not their membership.** Derive the vocabulary once;
subsequent runs *assign* new coverage areas into it by nearest-neighbour match rather than
re-deriving. Direct precedent: `shared/topic_grouping.py::match_existing_primary_topic`, which
exists because `graduate_sink_topics.py` was writing `primary_topic_key = None` and permanently
orphaning rows.

With one addition: an explicit **unassigned** bucket. Behaviour the vocabulary does not cover is
the signal to re-derive, not something to force into the nearest existing skill.

## 6. Validation

Every threshold below is fixed before any call is spent.

### 6.1 The primary gate, inherited rather than invented

**`W(unrelated) < 0.5 x W(matched)`** — the ceiling spec's own instrument-validity gate, so this
trial is judged against a bar that already exists.

| | matched | unrelated | passes |
| --- | --- | --- | --- |
| baseline (measured 3x) | 0.114–0.116 | 0.090–0.095 | **no** — needs < 0.057 |

The null must roughly halve. The gate does **not** require the matched score to rise: an arm at
0.114 matched and 0.04 unrelated is a working instrument. Discrimination is the thing.

### 6.2 Four arms

Arm names use the option numbers from the options review that produced this design: **3** =
inputs (§3), **4** = coverage-area unit (§4), **1** = skills (§5).

| arm | what it is | what it isolates |
| --- | --- | --- |
| **0 · baseline** | current Layer C, unchanged | the reference |
| **3** | new inputs (§3) only; still emits per-cluster criteria | do better inputs alone fix the criteria? |
| **1+4** | coverage areas (§4) + skills (§5), on the CURRENT blind inputs | do the new unit and axes carry the weight alone? |
| **1+4+3** | all three | the ceiling of this design |

`1+4` vs `1+4+3` isolates the inputs' contribution; `3` vs baseline isolates it alone.

**Arm 0 is re-run, not quoted from memory.** The ceiling run's arm B silently fell through to a
stricter model under rate limits and that confound nearly hid the real result. All arms run in one
session so they share model availability and quota conditions, and `scored_by` is reported per arm.

### 6.3 The comparability trap

`not_called_for` removes observations from the denominator, so coverage arms compute `W` over a
different population than arm 3. Coverage arms therefore report **both**: unconditional `W` (all
observations) for cross-arm comparison, and conditional `W` as an additional finding. Same
discipline as the ceiling design keeping discrimination unconditional on both arms — filtering one
side inflates the null.

### 6.4 Every arm runs twice

Measured 2026-08-12: three measurements of the same 49 scenarios agreed on the verdict **41–47%**
of the time, and the per-scenario gap moved a **median of 0.138** against a ±0.05 band. **An arm
difference smaller than the replication spread is not a result.**

### 6.5 Read the samples, at three named places

- **§3.3** — are criteria manufacturing distinctions to look different from siblings?
- **§4.3** — did any coverage area fuse genuinely distinct moves?
- **§5.1** — do the skill groups read as coherent at the chosen granularity?

### 6.6 Pre-registered stopping conditions

1. **No arm reaches the gate** -> criteria-based scoring is not achievable on this corpus. Stop;
   head-to-head comparison against the expert's real response becomes the primary approach.
2. **Arm differences inside the replication spread** -> the levers cannot be attributed. Report
   that; do not pick a winner.
3. **Skills fail the stability check** -> no vocabulary, so no grid. The skills and coverage
   changes lose their footing independently of whether the criteria improved.

### 6.7 Honest prior

Roughly **even odds** that any arm clears the gate. Three wording passes have failed and the
applicability judge failed. What differs in kind is that this changes the inputs and the unit
rather than the instructions — but "different in kind" is an argument, and arguments have lost to
measurements repeatedly here. Recorded now so it cannot be revised afterwards.

**The consolation is real:** the four-arm design reports which lever matters even if none clears
the bar. The last three attempts never produced that, because each changed one thing and measured
it on an average mixing three problems.

## 7. Zero writes — enforced, not promised

- Each arm generates its rubrics into a **JSON artifact**; scoring reads the artifact, never the
  database.
- The connection is opened with `SET SESSION default_transaction_read_only = on`, so a stray write
  fails at Postgres rather than relying on care. Reuses `score_naren_ceiling._connect_read_only`.
- The only file written outside `artifacts/` is `embed_cache.db`, a hash-keyed cache that cannot
  corrupt anything.
- Adoption into real rubrics is a separate, later, explicit step, gated on §6.

### 7.1 What the companion objective-function work leaves behind

`shared/rubric_validation.py`, `calibration/validate_rubrics.py`, the applicability prompt and
`layer_d.require_validated_milestones` were built and measured on 2026-08-12. Both validity gates
fired; no verdict was written. Under this design the applicability pre-check is **deleted** — folded
into §4.2's fourth verdict — because keeping a second, broken path alongside a working one is how a
rule change lands in only one of two places.

What stays and is load-bearing here: the three-arm scoring harness (call-level benchmark holdout,
secondary-label-and-zero-primary-call holdout, seeded derangement for the null) and the replication
comparison — they are how §6.1 and §6.4 are measured at all. `classify_scenario` stays available
for per-scenario reporting, but it is NOT the gate: §6.1 is corpus-level, because corpus-level is
the only resolution that reproduced.

## 8. Verification plan

Pure, testable surfaces, tested before any Gemma spend:

- **clause -> pair provenance** — every clause maps to the pair it came from, and a cluster's
  triggers are exactly the triggers of its member pairs
- **per-scenario batching** — a rubric's milestones always share a batch; exchange indices do not
  shift when a scenario contributes no lines
- **coverage-area parsing** — an area referencing a cluster that is not in the scenario, or omitting
  cluster references, is rejected rather than silently accepted
- **the fourth verdict** — `not_called_for` is excluded from the conditional denominator and
  included in the unconditional one, proven against hand-built counters
- **skill assignment** — a coverage area matching nothing above threshold lands in `unassigned`,
  never in the nearest skill
- **read-only enforcement** — an attempted write on the configured connection raises

Run file-by-file, per the documented 16GB-Windows spaCy constraint.

## 9. Cost

| | calls | basis |
| --- | --- | --- |
| generate arm 3's rubrics | ~82 | one call per scenario (§3.2) |
| generate arm 1+4's coverage areas | ~82 | one call per scenario |
| generate arm 1+4+3's coverage areas | ~82 | one call per scenario |
| skill pass x 2 arms (strip + name) | ~50 | batched over ~250 areas each |
| score 4 arms x 2 replications | ~752 | 94 per arm-run, measured 2026-08-12 on the all-82 scope |
| skill-granularity sweep | ~40 | discrimination probes across the threshold grid |
| **total** | **~1,090** | |

Arm 0 needs no generation — it scores the rubrics already in the database, read-only.

Full corpus, not a subset: every threshold in this codebase calibrated on a subset shifted when it
met the full 416 calls (`relative_margin`, `merge_cosine_threshold`, and the two-stage matching
strategies, which reversed).
