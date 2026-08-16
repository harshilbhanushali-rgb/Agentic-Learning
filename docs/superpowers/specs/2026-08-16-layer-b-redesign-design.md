# Layer B redesign: segmentation and routing, measured against rubrics

**Date:** 2026-08-16
**Status:** PRE-REGISTERED — written before any arm has been built or run.
**Predecessors:** `2026-08-16-layer-bc-downstream-validation-design.md` (the instrument, and the
result that reopens this), `2026-08-16-layer-a-routing-method-design.md` (the withdrawn routing
ranking), `2026-08-04-layer-b-sink-rescue-design.md` (closed, do not re-litigate).
**Handoff:** `Brain/HANDOFF_LAYER_B_REDESIGN.md`.
**Spend:** ZERO chat calls. ZERO paid embedding requests (cache-only, hard abort on a miss).
ZERO Postgres writes. ZERO production code changes.

---

## 1. The problem, restated from the code

`v2/layer_c.py`'s Pass 1 consumes `response_text` split into clauses, plus `call_filename` for
distinct-call support. It never reads the client turn. (`describe_mode: situated` would read
`trigger_text`, but it ships `legacy` and is off.)

**So Layer B's product is: for each scenario, a pool of Naren-response clauses with call
provenance.** The client turn is a routing key and nothing else.

But in `v1/layer_b.py` that one signal — the client trigger's text — answers three independent
questions:

| # | Decision | Where | Defects it owns |
| --- | --- | --- | --- |
| 1 | **Segmentation** — what is one unit of evidence | `extract_pairs` :40-70 | §2.3 consecutive client turns, §2.4 teammate discarded |
| 2 | **Admission** — is this evidence at all | `_is_substantive` :27-31 | §2.2 81% loss, §2.8 `Indeed`, §2.9 two knobs |
| 3 | **Routing** — which scenario | `assign_scenarios` :127-144 | §2.5 57.9% to sinks, §2.6 0.01 margin, §2.7 membership discarded |

(§ numbers are `HANDOFF_LAYER_B_REDESIGN.md`.)

**That is the type error's real shape.** The handoff states it as "Layer A's unit is a client
turn, Layer B's is a pair". True, but incomplete: the deeper fault is that one signal answers
three questions, so a change to any one silently moves the other two. It also explains why past
fixes failed — sink-rescue tried to fix **routing** by changing **admission**; the `delta` knob
proposes to fix **admission** with a **routing** threshold.

### 1.1 The funnel, with the two losses isolated

```
20,788 CLIENT turns
   |- gate 1  SEGMENT + ADMIT  ->  3,977 pairs         (-80.9%, 16,811 turns)
   |- gate 2  ROUTE (sink)     ->  1,673 coachable     (-57.9% of pairs)
                                  ~13,218 clauses -> 171 milestones
```

92% of client turns never reach a rubric. **Neither gate has ever been measured against the
output.** Sink-rescue measured gate 2 against per-pair AUC proxies; gate 1 has never been
touched at all.

---

## 2. The one question

> Does changing what Layer B treats as a unit of evidence, or how it picks a scenario, produce
> rubrics backed by evidence from more distinct clients?

Not "more milestones". See §4.

---

## 3. Arms

Five arms, each an explicit `(segment, router)` permutation, each run in its own process against
each of two taxonomies.

| arm | segment | router | isolates |
| --- | --- | --- | --- |
| `s0r0` | production | production | **control** — must reproduce `layer_bc_base_1.json` |
| `s1r0` | client move | production | **segmentation alone** |
| `s1r1` | client move | membership lookup | routing: pure lookup |
| `s1r2` | client move | centroid, out-of-fold | routing: centroid generalisation |
| `s1r3` | client move | 0.75·centroid + 0.25·description | routing: the old top scorer |

`s0r0 -> s1r0` isolates segmentation. `s1r0 -> s1r{1,2,3}` isolates routing. **The two variables
never move inside one comparison**, which is what keeps a combined trial attributable.

Taxonomies: `clean2_base` and `clean2_rescued`, every arm. Plus per-arm volume-matched placebos
and one noise-floor repeat. ~15 runs total.

### 3.1 `S1` — the client move

- Consecutive `CLIENT` turns merge into ONE trigger; their texts are joined in order.
- A `NAREN`, `JOVEO_OTHER` or `UNATTRIBUTED` turn ends the move. `UNATTRIBUTED` ends it because
  we do not know who spoke; it can never be part of a client move, exactly as it can never be a
  trigger today.
- The reply window is production's, unchanged: `NAREN` turns accumulate, `JOVEO_OTHER` is
  stepped over without contributing text, anything else breaks.
- Admission (`_is_substantive`) is production's, unchanged, applied to the merged move.

**Stated honestly up front: `S1` may barely move the pair COUNT.** In a block `c1,c2,c3` followed
by Naren, production already emits exactly one pair (from `c3`); `S1` emits one pair too. The
gain is (a) recovered setup text in the trigger, and (b) blocks whose last turn alone fails the
word floor but whose merged text clears it. The funnel table (§6.4) measures this BEFORE any
Layer C run. If it does not move, F2 fires and the arm is reported as a no-op — not as a null of
the idea.

`S2` (teammate speech enters `response_text`) is DEFERRED. It breaks the "Naren's voice" premise
every rubric rests on, which is a product decision, not a measurement one.

### 3.2 `R1` — membership lookup

Not a prediction. Layer A already assigned a label to that exact turn; `R1` reads it.

- The Layer A pool (`build_client_pool(turns, unit="turn")`) is CLIENT turns in file order, so
  the join to trigger turns is **positional**. It is asserted member-for-member
  (`texts[i] == turn.text` for all items) and aborts on any mismatch. Precedent:
  `flag_proper_noun_clusters.py`'s 245/245 position verification.
- A move spanning several turns can span several clusters: **majority vote** across its member
  turns; tie broken by the turn with the most content words; all-noise falls back to `R0`.
- **A scenario's member set is its own cluster PLUS every cluster whose `decision == merge_into`
  points at it.** `kind` is four-valued (`scenario` / `mechanics` / `logistics` / `merged`) and
  `merged` means RETAINED. Collapsing that enum to a boolean has already produced two phantom
  findings in this repo (the "Gemma over-sinks 14.6%" retraction, and again in the null-test
  control). Handled explicitly, and the full cross-tab is printed rather than a boolean.
- Turns Layer A left as HDBSCAN noise (~47% of the pool) fall back to `R0`. **The share of
  triggers resolved by lookup versus fallback is reported**, because `R1` is a hybrid and a
  result that is really `R0`'s must not be attributed to membership.

### 3.3 `R2` — centroid, out-of-fold

- A scenario's centroid is the mean of its member turn vectors (same member set as `R1`,
  including `merge_into` clusters).
- **Excluding every turn from the trigger's own call.** Triggers ARE client turns from the pool
  Layer A clustered, so an in-fold centroid would reproduce membership having learned nothing —
  the self-inflation `routing_bench` marked with `*` on `knn_max` / `medoid` / `probe`.
  Implemented as per-`(scenario, call)` partial sums so the exclusion is exact and O(1) per
  trigger. The in-fold figure is also reported, as a diagnostic, so the size of the inflation is
  visible rather than assumed.
- **Sinks get centroids too**, so the sink decision stays inside one space.

### 3.4 `R3` — blend

`0.75 * cos(trigger, centroid) + 0.25 * cos(trigger, description)`, the `blend_a0.75` weighting
from the withdrawn bench, on out-of-fold centroids. Included because it was that bench's top
scorer and dropping it would leave the strongest prior candidate untested.

### 3.5 Why the withdrawn ranking does not settle this, and why this instrument can

`routing_bench` ranked arms by `coherence(P)` = mean cosine of a population to its own centroid.
That IS the centroid arms' objective function, which is why the ranking was withdrawn. The
counter-evidence (blind read, 40 disagreement turns: `description` 70% vs `centroid_pooled` 30%,
McNemar 28-12, p=0.017) is a per-turn precision reading, not an outcome.

`layer_bc_arms` scores **milestones and their evidence breadth**. Neither centroid routing nor
description routing optimises that. It is arm-neutral for both, has a volume placebo, and a
blind read. It is the first instrument that can rank these two methods.

**The standing evidence against centroid is recorded here, not hidden:** its likely failure mode
is admitting junk (`centroid_pooled` accepted 22 of the 24 non-substantive turns in that blind
read). That is precisely what F4 (placebo) and F6 (blind read) exist to catch.

### 3.6 One trap that does NOT apply here, and why

An earlier draft required a per-arm `relative_margin`, on the grounds that the routers have
different cosine bands (trigger-vs-trigger p50 0.689; trigger-vs-description p50 0.550) so one
margin means different things.

**That is void for this trial.** CLAUDE.md records it as measured: `relative_margin` does not
feed Layer C — Layer C keys off the single primary `scenario_key`, while the margin governs only
the ADDITIONAL entries in `scenario_keys[]`. The only routing decisions reaching a rubric are
(a) which scenario is top-1, an argmax, and (b) whether top-1 is a sink, a comparison inside one
router's own space. Both are scale-free.

`relative_margin` stays at production's `0.95` in every arm. Margin distributions are reported as
diagnostics only and rank nothing.

---

## 4. Metrics

### 4.1 Primary, and it decides pass/fail

**Usable milestones: those clearing production's support gate AND backed by >= 3 DISTINCT CLIENT
ACCOUNTS.**

- Account = the modal non-`joveo.com` email domain on a call's `.speakers.json` roster. 389 of
  393 transcripts carry one; 112 accounts over 355 accounted calls. The derivation is
  **imported** from `calibration/flag_proper_noun_clusters.py`, never paraphrased.
- **No router can see the account**, so this is nobody's objective function — the standing rule
  that killed the routing ranking.
- It is also the product defect: today's largest scenarios are 95-100% one client (RTX 98%,
  Banfield 100%, Happy Dance 100%). A milestone built from one client teaches a CSM nothing
  transferable.
- Calls with no resolvable account are counted as **distinct unknowns**, never merged into one
  bucket — merging them would manufacture single-account concentration.
- **Why 3 and not another number:** it is the account-level analogue of `layer_c`'s existing
  `min_milestone_calls_floor: 3`, so the bar is inherited rather than invented for this trial. It
  is pre-registered here and is not tuned afterwards. The full distribution of accounts-per-
  milestone is reported so the choice can be audited, and a sensitivity check at 2 and 4 is
  reported alongside — **but the verdict is read off 3**, fixed before any arm runs.

**Statistic:** per cluster, the usable-milestone count. Paired **sign test** across clusters
shared by both arms, joined on `cluster_id` (never `scenario_key` — Gemma renames every run).
Report **the direction of flips, never a flip rate**; a rate discards direction, which is the
error that made an earlier adjudication A/B unreadable.

### 4.2 Veto, and it can override a significant result

A **blind read** of what each arm ADDS and LOSES versus control. For a rule that MODIFIES a
population, the unit of reading is the MODIFICATION — sampling arms independently would compare
two random draws from a mostly-shared set. Samples are written to one file and the answer key to
a SEPARATE file; judgments are committed before the key is opened. Precedent:
`read_routed_samples.py`, and `clustering_bench --added`.

**Limitations stated, not buried:** one reader, who designed the arms; small n; the sample is the
disagreement set, so precision and recall are conditional on disagreement and are not global
rates.

### 4.3 Diagnostics — reported, never used to rank

- raw milestone count, milestones/scenario, `support_calls` distribution
- pair passthrough per stage (**this is every arm's own objective — never a ranking statistic**)
- sink share, absorption (coachable-only), top1-top2 margin
- `available_frac_prefilter` vs `available_frac` on lost milestones — separates a **Layer B
  reroute** from a **Layer C relevance shift**
- relevance-filter survival rate. **A high value is SUSPICIOUS, not good**: an arm routing on
  response similarity is selected for exactly what `_relevance_filter` measures.
- for `R1`: share of triggers resolved by lookup vs `R0` fallback
- for `R2`: in-fold vs out-of-fold agreement, i.e. the size of the self-inflation

### 4.4 Objective audit

Every arm is re-scored under three objectives: the 3-account count, raw milestone count, and mean
relevance. **If an arm wins only under the objective that mirrors its own mechanism, the ranking
is withdrawn** (F7). This is the check `routing_bench` lacked and `routing_objective_audit.py`
retro-fitted.

---

## 5. Pre-registered failure conditions

| | Condition | Consequence |
| --- | --- | --- |
| **F1** | `s0r0` does not reproduce `layer_bc_base_1.json` on pair count, sink share and milestone count | the harness is wrong. STOP; nothing else is readable |
| **F2** | an arm's funnel is within +/-2% of control at every stage | the arm did not fire. Report as a NO-OP, not as a null of the idea |
| **F3** | an arm leaves < 20 clusters rankable | unrankable, not comparable |
| **F4** | an arm's gain over control is not ALSO a gain over its own volume-matched placebo | the gain is volume. REJECT |
| **F5** | paired sign test p >= 0.05 | null. Report as such |
| **F6** | a blind read of the arm's added milestones does not beat chance | **WITHDRAW regardless of p** |
| **F7** | an arm wins under the 3-account metric but loses under raw count AND mean relevance | withdraw the ranking (§4.4) |
| **F8** | milestone total outside the scaled `f4_band` | the clustering did not reproduce. Run VOID |
| **F9** | the two taxonomies disagree on the winner | report both; pick neither |
| **F10** | nothing clears F4 + F5 + F6 | **published result: Layer B's unit and router are not the binding constraint on rubric quality.** This CLOSES the question and is worth as much as a positive |

---

## 6. Guards

Each is here because of a specific past failure in this repo.

### 6.1 The control must reproduce a published artifact
`s0r0` calls `v1.layer_b.extract_pairs` and `v1.layer_b.assign_scenarios` **verbatim** and must
reproduce `layer_bc_base_1.json`. This is the free self-check that catches harness bugs before
any treatment is believed — the same shape as `routing_bench` asserting `description`'s
out-of-fold and full-corpus assignments are identical on all 23,949 turns.

### 6.2 Identity records the permutation
`segment` and `router` join the `identity` dict. Without them two permutations would compare as
"identical corpus, identical taxonomy, no drift" — the silent "no effect with zero calls" failure
this instrument already carries a guard against for the taxonomy.

### 6.3 Volume-matched placebo, matching clauses AND calls
Per arm being declared a winner. `pass1`'s `scenario_calls_override` exists for this: donors drag
in new distinct calls and silently raise `required_milestone_support`, biasing the read IN FAVOUR
of the treatment.

### 6.4 The funnel diff table
Printed side by side per arm, before any Layer C run:

```
turns -> moves -> admitted -> routed(coachable) -> clauses -> post-relevance
```

This is "**symmetric filtering: for every arm, list what was filtered and diff the lists**", made
mechanical rather than left to a reviewer's memory.

### 6.5 One permutation per process, one permutation per build step
`--segment` and `--router` are required and take exactly one value each. No multi-arm loop
exists, so two arms can never share a process, a random state, or an artifact.

### 6.6 Noise floor, verified once
The floor is documented as ZERO with cached embeddings, but that was measured on a code path this
design changes. One arm is run twice, in separate processes, to confirm it before any treatment
is read.

### 6.7 Every new calibration file is audited by a subagent before it runs
Strict bar: only defects that change the outcome or waste a run. Precedent: the last audit found
a hard blocker and three silent-wrong-answer bugs.

---

## 7. Instrument

| file | status | contents |
| --- | --- | --- |
| `calibration/layer_b_arms.py` | NEW | pure functions only: `segment_moves`, the four routers, the account map, usable-milestone counting, the sign test. No I/O, no CLI, no globals. |
| `calibration/layer_bc_arms.py` | EXTENDED | `--segment {s0,s1} --router {r0,r1,r2,r3}`, defaulting to production, recorded in `identity`. Every existing guard preserved. |
| `tests/test_layer_b_arms.py` | NEW | hand-built turn lists and orthogonal unit vectors — tests the RULE, not the embedder (the `test_layer_b_assignment.py` precedent). |
| `tests/test_layer_bc_arms.py` | EXTENDED | new identity fields; the existing 38 tests must still pass. |
| `ops/run_layer_b_arms.ps1` | NEW | one arm per process, with the neon DNS bypass. |

**Nothing in `v1/`, `v2/`, `shared/` or `preprocessing/` is modified.** Production behaviour is
byte-identical.

---

## 8. Build order

One permutation at a time. Nothing proceeds until the previous step's tests pass, its subagent
audit is clean, and its artifact is written.

| step | build | verify |
| --- | --- | --- |
| 1 | account map, 3-account metric, sign test | **re-score the EXISTING `base_1` / `rescued` / `placebo` artifacts.** Free, no new runs. If the metric cannot separate `rescued` from `placebo` on data already on disk, the metric is wrong and we learn it before building anything |
| 2 | `--segment/--router` plumbing, `s0`/`r0` only | run `s0r0` -> F1 |
| 3 | `S1` | tests, then `s1r0` |
| 4 | `R1` | tests, then `s1r1` |
| 5 | `R2` | tests, then `s1r2` |
| 6 | `R3` | tests, then `s1r3` |
| 7 | placebos, second taxonomy, noise-floor repeat, objective audit, blind read | F2-F10 |

**Estimated cost:** ~6-10 min machine time per arm (measured: 2.2-4.2 min of Layer C plus the
393-transcript parse), ~15 arms, so ~1.5-2.5 h unattended. Working time ~7-10 h including audits.

---

## 9. What this cannot answer

- **Whether better rubrics improve Layer D coaching.** Layer D's grader has its own documented
  problem: leakage-clean `W(matched)` is 0.089-0.095, i.e. the criteria are unpassable even by
  their own author. A better rubric fed to a broken grader will not show up. Do not chain this
  into Layer D without reading `2026-08-15-grader-inputs-design.md`.
- **Whether the result transfers to production.** Everything here is `gemini-embedding-2@3072` in
  TURN mode; production is local `bge@768` in CLAUSE mode. **No production change may cite these
  numbers alone.** A bge transfer pass for the winning arm only is the agreed second step.
- **Admission (Knob A).** `_is_substantive` stays at production in every arm, so the `Indeed`
  stopword bug (§2.8) and the two-filters problem (§2.9) are untouched by this trial. They are
  real and they are deferred, deliberately, to keep this trial to two variables.
- **Whether the taxonomy should be built differently.** Layer A is out of scope by the handoff's
  own boundary; the taxonomy is an input.
