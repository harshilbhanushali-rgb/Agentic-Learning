# Layer B redesign: segmentation, admission and routing, measured against rubrics

**Date:** 2026-08-16
**Status:** PRE-REGISTERED — written before any arm has been built or run.
**Revision 1 (same day, before any run):** the arm set was reorganised from "S1 in every
treatment arm" to a promising-first shortlist, and Knob A was promoted from deferred to a
first-class knob. Recorded here rather than silently edited, because a pre-registration amended
after seeing results is not a pre-registration. Nothing had been built or run when this revision
was made. The failure conditions (§5) and metrics (§4) are unchanged from revision 0.
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
| 2 | **Admission** — is this evidence at all | `_is_substantive` :27-31, applied at :45 AND :54 | §2.2 81% loss, §2.8 `Indeed`, §2.9 two knobs |
| 3 | **Routing** — which scenario | `assign_scenarios` :127-144 | §2.5 57.9% to sinks, §2.6 0.01 margin, §2.7 membership discarded |

(§ numbers are `HANDOFF_LAYER_B_REDESIGN.md`.)

**That is the type error's real shape.** The handoff states it as "Layer A's unit is a client
turn, Layer B's is a pair". True, but incomplete: the deeper fault is that one signal answers
three questions, so a change to any one silently moves the other two. It also explains why past
fixes failed — sink-rescue tried to fix **routing** by changing **admission**; the `delta` knob
proposes to fix **admission** with a **routing** threshold.

### 1.1 The funnel, with the losses isolated

```text
20,788 CLIENT turns
   |- gate 1  SEGMENT + ADMIT  ->  3,977 pairs         (-80.9%, 16,811 turns)
   |- gate 2  ROUTE (sink)     ->  1,673 coachable     (-57.9% of pairs)
                                  ~13,218 clauses -> 171 milestones
```

92% of client turns never reach a rubric. **Neither gate has ever been measured against the
output.** Sink-rescue measured gate 2 against per-pair AUC proxies; gate 1 has never been touched.

### 1.2 The gate-1 loss has THREE causes and nobody has split them

| cause | meaning | knob that owns it |
| --- | --- | --- |
| **(a)** | the trigger fails `_is_substantive` | **A** |
| **(b)** | no Naren reply followed (another client spoke, only a teammate answered, call ended) | **S** |
| **(c)** | Naren replied but every one of his turns failed `_is_substantive`, so `response_parts` was empty | **A** |

**This split is a required output of build step 2** (§8) and it gates whether the `S` and `A`
arms are worth running at all. Cause (c) is the one nobody has ever named: it is evidence lost on
the *response* side, which is the only side Layer C consumes.

### 1.3 MEASURED 2026-08-16, and it moves the plan

Run free over the cleaned 393-transcript corpus, importing production `parse_transcript`,
`_is_substantive` and `extract_pairs`. **The per-turn classifier reproduces production's pair
count EXACTLY (3,977 = 3,977)**, so this is a decomposition of `extract_pairs`, not an
approximation of it. Every CLIENT turn is examined exactly once by that loop — `i = j` lands on
the turn that broke the window, which is itself a CLIENT turn — so the turn view is exact rather
than the upper bound its script originally claimed.

| cause | turns | share |
| --- | --- | --- |
| **(b) no Naren reply in the window** | **13,056** | **62.8%** |
| (a) trigger fails the >=5 content-word floor | 7,054 | 33.9% |
| (c) Naren replied, every turn filtered out | 2,053 | 9.9% |

Rescue population per knob, everything else held at production:

| knob | turns | against today's 3,977 pairs |
| --- | --- | --- |
| `A1` alone (trigger floor is the only blocker) | 1,702 | **+43%** |
| `A4` alone (response floor is the only blocker) | 1,312 | **+33%** |
| both needed together | 741 | |

So `A1` + `A4` roughly DOUBLE the pair count. Promoting Knob A was correct.

**Cause (b) splits in two, and the larger half is the deferred knob:**

| | turns | share of all CLIENT turns |
| --- | --- | --- |
| another CLIENT spoke next -> `S1`'s target | ~7,480 | **36.0%** |
| **a teammate answered instead -> `S2`** | **5,287** | **25.4%** |

`S1` is confirmed as a real change rather than a no-op (F2 will not fire), but it changes trigger
TEXT rather than pair COUNT — a block already yields exactly one pair, so merging its turns
enriches the trigger without adding a unit. Its pair-count gain is confined to blocks whose last
turn alone fails the floor while the merged move clears it, i.e. the overlap with cause (a).

---

## 2. The one question

> Does changing what Layer B treats as a unit of evidence, what it admits, or how it picks a
> scenario, produce rubrics backed by evidence from more distinct clients?

Not "more milestones". See §4.

---

## 3. The knobs

Four knobs. Each arm changes exactly ONE from production, except the one deliberate combination
cell (§3.6, arm 9), which is the interaction of the two winners.

### 3.1 `R1` — membership lookup

Layer A already assigned a label to that exact turn. `R1` reads it. It is a lookup, not a
prediction, which is why the withdrawn `routing_bench` ranking does not apply — that bench asked
whether a centroid can *predict* an unseen turn's cluster.

**Member sets.**
- Each adjudication row with `kind` in {`scenario`, `mechanics`, `logistics`} contributes its
  cluster's turn indices.
- Every row with `decision == merge_into` then **adds its indices to the target's set**.
  `merged` means RETAINED. Collapsing that four-valued enum to a boolean produced the phantom
  "Gemma over-sinks 14.6%" retraction and, separately, a broken null-test control. The full
  cross-tab is printed; never a boolean.

**Join.** `build_client_pool(turns, unit="turn")` is CLIENT turns in file order, so pool item `i`
is the i-th CLIENT turn across sorted files. **`texts[i] == turn.text` is asserted for every
item and the run aborts on any mismatch.** Precedent: `flag_proper_noun_clusters`' 245/245
position verification.

**Route.** trigger turn -> pool index -> cluster -> scenario key. `scenario_keys` is that one
key; no ranking, no top-K, no margin. A sink key takes production's short-circuit unchanged. A
turn HDBSCAN left as noise falls back to `R0`.

**Reported:** the lookup / fallback split. If a result is really `R0`'s it must not be credited
to membership. ~47% of the pool is noise, so this arm is a hybrid by construction.

### 3.2 `R2` — centroid, out-of-fold

Same member sets as `R1`, including `merge_into`. **Sinks get centroids too**, so the sink
decision stays inside one space.

```text
centroid(s, excluding call c) = (sum_s - sum_s,c) / (n_s - n_s,c)
```

Per-`(scenario, call)` partial sums, so the exclusion is exact and O(1) per trigger. Triggers ARE
client turns from the pool Layer A clustered, so an in-fold centroid would reproduce membership
having learned nothing — the self-inflation `routing_bench` marked with `*` on `knn_max` /
`medoid` / `probe`. **The in-fold figure is computed as a diagnostic** so the size of the
inflation is visible rather than assumed.

If `n_s - n_s,c == 0` — a scenario's only evidence is this call — it is removed from that
trigger's candidate set. How often this fires is reported.

Routing is then production's: argmax, sink short-circuit, top-K at `relative_margin 0.95`.

**Known risk, recorded not hidden:** `centroid_pooled` accepted 22 of the 24 non-substantive
turns in the 40-turn blind read (McNemar 28-12, p=0.017 against `description`). Its likely
failure mode is admitting junk. F4 and F6 exist for this.

### 3.3 `R3` — blend

`0.75 * cos(trigger, centroid_oof(s)) + 0.25 * cos(trigger, description(s))`, then identical
argmax / sink / top-K. The `blend_a0.75` weighting from the withdrawn bench, included because it
was that bench's top scorer and is ~15 minutes of work once `R2` exists.

### 3.4 `A4` — drop the RESPONSE-side floor

`v1/layer_b.py:54` currently gates each Naren turn:

```python
if t.role == SpeakerRole.NAREN:
    if _is_substantive(t.text):          # A4 removes this test
        response_parts.append(t.text)
```

**Two effects, reported separately:**

| effect | mechanism |
| --- | --- |
| more text per pair | short Naren turns now contribute to `response_text` |
| **more pairs** | `if response_parts:` currently kills a pair whose only Naren reply was short |

**Why the obvious objection is weaker than it looks:** Layer C's segmenter already drops
sentences under 4 tokens, so `"Yeah."` dies there regardless; the p40 relevance filter and the
distinct-call support gate are two further defences. This floor may be doing work three later
stages already do.

**What it recovers:** *"No, that's Indeed's API cost, not ours."* is 4 content words after
stopword removal, and is currently deleted from the evidence.

This half of `_is_substantive` has never been named in any spec or handoff in this repo.

### 3.5 `A1` — drop the TRIGGER floor

`v1/layer_b.py:45`. Every CLIENT turn followed by a Naren reply becomes a pair. Expect a large
pair increase, most of it routing to sinks — which is the question: **is the word floor doing
anything the sink decision does not already do?** Kills the `Indeed` bug by deletion rather than
by a curated whitelist, which this repo forbids. Does not change consecutive-client behaviour;
that is `S1`'s job.

### 3.6 `A3` — corpus-percentile floor

Replaces the rule, not the threshold:

- content token = `is_alpha` **only**, no stoplist, so `indeed` / `ziprecruiter` / `workday` are
  treated identically and the inconsistency disappears at its source;
- floor = the *p*-th percentile of that count over the corpus's own turns, computed **separately
  for CLIENT and NAREN** because the distributions differ.

*p* is chosen so the **admitted fraction exactly matches production's**. `A3` is therefore
volume-neutral by construction — same number of pairs, different selection — so any difference is
purely the stopword dependence, and **it needs no placebo**.

### 3.7 `S1` — client move

A move is a **maximal run of adjacent CLIENT turns**; any non-CLIENT turn ends it, `UNATTRIBUTED`
included (we do not know who spoke, so it cannot join a client move).

```text
turn 5  CLIENT  "We're on Workday for the ATS."             -+ ONE trigger
turn 6  CLIENT  "Does that integrate with what you said?"   -+
turn 7  NAREN   "Yes, we have a direct connector..."           the reply
```

`trigger_text` is the run's texts joined in order; `turn_index` is the run's FIRST turn, which
keeps `pair_id` unique. The reply window is production's, unchanged. Admission applies to the
merged text.

**Stated honestly:** the pair COUNT barely moves — production already emits one pair per block,
from its last turn. The gains are recovered setup text, and blocks whose last turn alone fails
the floor but whose merged text clears it. **F2 covers the no-op case.**

### 3.8 `D` — the accept/reject delta

Not an arm. A sweep applied to whichever router wins.

```text
accept  iff   max(score over coachable)  -  max(score over sinks)  >=  delta
```

`delta = 0` (strict) **is production exactly** — the current rule restated. The output is a CURVE
of (admitted volume -> usable milestones), not a point, so it cannot be miscalibrated the way a
fixed threshold can. Existing evidence: `delta = -0.0117` buys +5.1pp recall for -2.6pp
precision, versus -14.0pp for switching routers — but ground truth is only 80 judged turns, so it
is thin. Runs last.

### 3.9 Deferred, with reasons

- **`S2`** (teammate speech enters `response_text`) — **DEFERRED, AND IT IS THE LARGEST
  MEASURED LEVER ON THE BOARD. OWED ITS OWN DESIGN PASS; DO NOT BOLT IT ON AS AN ARM.**
  §1.3 measured it at **5,287 turns, 25.4% of every CLIENT turn in the corpus** — bigger than
  `A1` and `A4` combined. A quarter of all client turns received a Joveo answer that
  `extract_pairs` steps over at `v1/layer_b.py:57` (`j += 1`, no text captured) and discards
  entirely.

  It is deferred because it is **not a measurement question**. Every rubric in this pipeline
  rests on the premise that a milestone is a move *Naren* makes; admitting a colleague's words
  changes what a rubric IS, and downstream that changes what Layer D is grading a CSM against.
  Running it as an arm would produce a number that cannot be acted on either way.

  The design questions it needs answered first, none of which this trial can settle:
  1. Is the benchmark "the expert's move" or "the Joveo team's move"? Layer D's whole grading
     premise follows from the answer.
  2. Are all teammates equivalent, or does seniority/role matter? A curated roster of "good
     enough" speakers would be the forbidden curated-list anti-pattern.
  3. `ego_trap/` already distinguishes `other_joveo` and writes a `Deferred_To_Teammate`
     gap_event rather than scoring it — so Layer D has ALREADY taken a position on this, and
     admitting teammate speech into `kb_pairs` would contradict it silently.
  4. Does a mixed-voice rubric still transfer, or does it become a Joveo-process document?

  **Next step when it is picked up: a brainstorm, then its own pre-registered spec.** Not an
  arm in this one.
- **`S3`** (previous Naren turn as routing context) — speculative.
- **`A2`** (either-side substantive) — narrow affected population, small expected effect.

### 3.10 One trap that does NOT apply, and why

An earlier draft required a per-arm `relative_margin`, because the routers have different cosine
bands (trigger-vs-trigger p50 0.689; trigger-vs-description p50 0.550).

**Void.** CLAUDE.md records it as measured: `relative_margin` does not feed Layer C — Layer C
keys off the single primary `scenario_key`, while the margin governs only the ADDITIONAL entries
in `scenario_keys[]`. The only routing decisions reaching a rubric are (a) which scenario is
top-1, an argmax, and (b) whether top-1 is a sink, a comparison inside one router's own space.
Both are scale-free. `relative_margin` stays at `0.95` in every arm; margin distributions are
diagnostics and rank nothing.

---

## 4. Metrics

### 4.1 Primary — decides pass/fail

**Usable milestones: those clearing production's support gate AND backed by >= 3 DISTINCT CLIENT
ACCOUNTS.**

- Account = the modal non-`joveo.com` email domain on a call's `.speakers.json` roster. 389 of
  393 transcripts carry one; 112 accounts over 355 accounted calls. The derivation is **imported**
  from `calibration/flag_proper_noun_clusters.py`, never paraphrased.
- **No router, no segmenter and no admission rule can see the account**, so this is nobody's
  objective function — the standing rule that killed the routing ranking.
- It is also the product defect: today's largest scenarios are 95-100% one client (RTX 98%,
  Banfield 100%, Happy Dance 100%). A milestone built from one client transfers to nobody.
- **Calls with no resolvable account contribute ZERO accounts** (~11% of calls). Corrected from
  revision 1's "count each as a distinct unknown" before any run: that variant *asserts* three
  unaccounted calls are three different clients, which is exactly the thing being measured and
  cannot inflate in the safe direction. Pooling them into one shared bucket would be the opposite
  fabrication. Excluding them can only ever make a milestone look LESS transferable, so it cannot
  manufacture a win. The lenient variant is computed as a sensitivity check; **if the two
  disagree on the verdict that is reported, not resolved.**
- **Why 3:** it is the account-level analogue of `layer_c.min_milestone_calls_floor: 3`, so the
  bar is inherited rather than invented. Fixed before any arm runs. The full
  accounts-per-milestone distribution is reported, and a sensitivity check at 2 and 4 is reported
  alongside — **but the verdict is read off 3.**

**Statistic:** per cluster, the usable-milestone count. Paired **sign test** across clusters
shared by both arms, joined on `cluster_id` (never `scenario_key` — Gemma renames every run).
Report **the direction of flips, never a flip rate.**

### 4.2 Veto — can override a significant result

A **blind read** of what each arm ADDS and LOSES versus control. For a rule that MODIFIES a
population the unit of reading is the MODIFICATION; sampling arms independently would compare two
random draws from a mostly-shared set. Samples go to one file and the answer key to a SEPARATE
file; judgments are committed before the key is opened.

**Limitations stated, not buried:** one reader, who designed the arms; small n; the sample is the
disagreement set, so precision and recall are conditional on disagreement and are not global
rates.

### 4.3 Diagnostics — reported, never used to rank

- raw milestone count, milestones/scenario, `support_calls` distribution
- **the funnel, broken down by cause (a)/(b)/(c)** — §1.2
- pair passthrough per stage. **This is every arm's own objective and is never a ranking
  statistic**
- sink share, absorption (coachable-only), top1-top2 margin
- `available_frac_prefilter` vs `available_frac` on lost milestones — separates a **Layer B
  reroute** from a **Layer C relevance shift**
- relevance-filter survival rate. **High is SUSPICIOUS, not good:** an arm routing on response
  similarity is selected for exactly what `_relevance_filter` measures
- `R1`: lookup vs fallback share. `R2`: in-fold vs out-of-fold agreement, and how often a
  scenario is dropped for having no out-of-call evidence

### 4.4 Objective audit

Every arm is re-scored under three objectives: the 3-account count, raw milestone count, and mean
relevance. **If an arm wins only under the objective that mirrors its own mechanism, the ranking
is withdrawn** (F7).

---

## 5. Pre-registered failure conditions

Unchanged from revision 0.

| | Condition | Consequence |
| --- | --- | --- |
| **F1** | a control arm does not reproduce its published artifact on pair count, sink share and milestone count | the harness is wrong. STOP; nothing else is readable |
| **F2** | an arm's funnel is within +/-2% of control at every stage | the arm did not fire. Report as a NO-OP, not a null of the idea |
| **F3** | an arm leaves < 20 clusters rankable | unrankable, not comparable |
| **F4** | an arm's gain over control is not ALSO a gain over its own volume-matched placebo | the gain is volume. REJECT |
| **F5** | paired sign test p >= 0.05 | null. Report as such |
| **F6** | a blind read of the arm's added milestones does not beat chance | **WITHDRAW regardless of p** |
| **F7** | an arm wins under the 3-account metric but loses under raw count AND mean relevance | withdraw the ranking (§4.4) |
| **F8** | milestone total outside the scaled `f4_band` | the clustering did not reproduce. Run VOID |
| **F9** | the two taxonomies disagree on the winner | report both; pick neither |
| **F10** | nothing clears F4 + F5 + F6 | **published result: Layer B's unit, admission rule and router are not the binding constraint on rubric quality.** This CLOSES the question and is worth as much as a positive |

---

## 6. Guards

Each is here because of a specific past failure in this repo.

1. **Controls reproduce published artifacts.** `s0a0r0` on `clean2_base` must reproduce
   `layer_bc_base_1.json`, and on `clean2_rescued` must reproduce `layer_bc_rescued.json`. Two
   independent F1 checks. The control calls `v1.layer_b.extract_pairs` and
   `v1.layer_b.assign_scenarios` **verbatim**.
2. **Identity records the permutation.** `segment`, `admit` and `router` join the `identity`
   dict. Without them two permutations compare as "no drift" — the silent "no effect with zero
   calls" failure this instrument already guards against for the taxonomy.
3. **Volume-matched placebo**, matching clause volume AND call count, for any arm being declared
   a winner. `A3` is exempt by construction (§3.6).
4. **The funnel diff table**, printed per arm before any Layer C run, broken down by cause. This
   is "symmetric filtering: list what was filtered and diff the lists", made mechanical.
5. **One permutation per process, one permutation per build step.** `--segment`, `--admit` and
   `--router` each take exactly one value; no multi-arm loop exists.
6. **Noise floor verified once.** Documented as ZERO with cached embeddings, but measured on a
   code path this design changes. One arm is run twice, in separate processes.
7. **Every new calibration file is audited by one subagent before it runs.** Strict bar: only
   defects that change the outcome or waste a run.

---

## 7. Instrument

| file | status | contents |
| --- | --- | --- |
| `calibration/layer_b_arms.py` | NEW | pure functions only: `segment_moves`, the admission predicates, the four routers, member-set construction, the account map, usable-milestone counting, the sign test. No I/O, no CLI, no globals |
| `calibration/layer_bc_arms.py` | EXTENDED | `--segment {s0,s1} --admit {a0,a1,a3,a4} --router {r0,r1,r2,r3}`, defaulting to production, all recorded in `identity`; `support_call_files` persisted per milestone; the funnel table. Every existing guard preserved |
| `tests/test_layer_b_arms.py` | NEW | hand-built turn lists and orthogonal unit vectors — tests the RULE, not the embedder |
| `tests/test_layer_bc_arms.py` | EXTENDED | new identity fields; the existing 38 tests must still pass |
| `ops/run_layer_b_arms.ps1` | NEW | one arm per process |

**Nothing in `v1/`, `v2/`, `shared/` or `preprocessing/` is modified.** Production behaviour is
byte-identical.

### 7.1 A required change to the artifact schema

`pass1` computes `len(set(g["calls"]))` and discards the list, so account diversity **cannot** be
derived from the artifacts already on disk. `support_call_files` (the distinct call filenames per
milestone) is persisted, and the three published arms are re-run to obtain it. That re-run is
also a free reproduction check: they must return 171 / 123 / 179 milestones exactly.

---

## 8. Arms and build order

Promising-first. Nothing proceeds until the previous step's tests pass, its subagent audit is
clean, and its artifact is written.

| step | build | arm(s) run | ~time |
| --- | --- | --- | --- |
| 1 | account map, 3-account metric, sign test, `support_call_files` | re-run `base_1`, `rescued`, `placebo`; score them | 1 h + 30 m |
| 2 | `--segment/--admit/--router` plumbing, funnel table | `s0a0r0_b` -> **F1**, `s0a0r0_b_2` (floor), `s0a0r0_r` -> **F1** | 1 h + 30 m |
| 3 | `A4` | `s0a4r0_b` | 20 m + 10 m |
| 4 | `A1` | `s0a1r0_b` | 15 m + 10 m |
| 5 | `R1` (member sets + positional join) | `s0a0r1_b`, `s0a0r1_r` | 1.5 h + 20 m |
| 6 | `R2` | `s0a0r2_b`, `s0a0r2_r` | 45 m + 20 m |
| 7 | `R3` | `s0a0r3_b` | 15 m + 10 m |
| 8 | combination | `s0a4rW_r` — the two winners together | 10 m |
| 9 | placebo, `D` sweep, objective audit, blind read | `s0aXrW_?_plc` | 1.5 h |
| 10 | `S1`, **only if the funnel shows cause (b) is material** | `s1a0r0_b`, `s1aXrW_?` | 45 m + 20 m |

**~13 arms, ~2.5 h machine, ~7 h working time.** Steps 3-4 come before the routers because they
are the cheapest builds on the board and `A4` is the strongest untested hunch; step 2's funnel
tells us their expected size before either runs.

`W` denotes the winning router. If §8 produces no winner, step 8 is skipped and step 10 runs
against `r0`.

---

## 9. What this cannot answer

- **Whether better rubrics improve Layer D coaching.** Layer D's grader has its own documented
  problem: leakage-clean `W(matched)` is 0.089-0.095, i.e. the criteria are unpassable even by
  their own author. A better rubric fed to a broken grader will not show up. Do not chain this
  into Layer D without reading `2026-08-15-grader-inputs-design.md`.
- **Whether the result transfers to production.** Everything here is `gemini-embedding-2@3072` in
  TURN mode; production is local `bge@768` in CLAUSE mode. **No production change may cite these
  numbers alone.** A bge transfer pass for the winning arm only is the agreed second step.
- **Whether the taxonomy should be built differently.** Layer A is out of scope by the handoff's
  own boundary; the taxonomy is an input.
- **Interactions other than step 8's.** This is a screening design with one deliberate
  combination cell, not a factorial. An interaction between two knobs that are individually null
  would be missed. That is the stated cost of not running 80 cells.
