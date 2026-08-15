# Layer D scores a call, not a reply — and the customer decides what counts (2026-08-15)

Status: **BUILT, GATED, AND REJECTED BY ITS OWN GATE (2026-08-15).** All three automated
checks failed, decisively. `layer_d.scoring_unit` stays `moment`; the code remains behind the
flag as the record of a measured negative, not as a thing to switch on. **Do not enable it.**
Read "Gate result" at the bottom first — the headline is that the 1-3 turn window was
load-bearing, not a bug. The onboarding review (§5) was never built and is NOT refuted by
this; it is the part of the design still worth doing.

Depends on `2026-08-15-grader-inputs-design.md`, which established that the scorer works.
Read its Confirmation section before this one.

## Why this exists

Today Layer D scores a rep's reply against criteria distilled from an expert's calls, over a
1–3 turn window, at moments a matcher flagged. Measured over the 100-call run:

| | |
| --- | --- |
| weighted score, all attempts | **0.078** |
| criteria never satisfied by anyone, ever (>= 6 attempts) | **87 of 221 = 39%** |
| attempts those consume, returning zero | **994 of 4,181 = 24%** |
| share of a rubric's criteria hit by *somebody* (union), mean | **45%** |
| the same union, aggregate over all criteria | **181 of 395 = 46%** |
| criteria with no `milestone_performance` row at all | **17 of 395** |

> **Both denominators here are conditional on "Layer D reached this rubric".** 84 rubrics are
> live; only **78** appear, because a rubric with zero attempted criteria produces no rows and
> is absent entirely — so its criteria are not among the 395 and the 6 missing rubrics are
> invisible. Every union below is therefore an over-estimate of the union across the rubric
> table. Correcting that needs the rubric table, i.e. a DB read, so it is filed as its own item
> rather than folded in here.
>
> The 17 are "no perf row", which is *mostly* but not provably "never attempted": **13 sit at
> interior positions** (e.g. M1/M5/M11 of 13) that a rubric changing after the run cannot
> explain, and **4 are tail positions** in 3 rubrics where `upsert_rubric` replacing
> `milestones` under a stable `rubric_id` is not excluded (F16).
>
> Union corrected 2026-08-15 (F6/R1). It had been computed over the 378 criteria that carry a
> `milestone_performance` row rather than the 395 in the rubrics; a criterion nobody attempted
> was certainly never hit, so excluding it inflated the union. Mean 46% -> 45%, median 46% ->
> 43%, aggregate 47.9% -> 45.8%. Every change is downward, so it **strengthens** the dead-criteria
> reading below and weakens the denominator-inflation one. Nothing else in this table moved:
> `W`, the 87 dead criteria and the 994 attempts are computed over attempted criteria only and
> are untouched.

Two candidate causes were tested and **both rejected**:

- **Rubric size.** `corr(criteria per rubric, W) = -0.10`. Large rubrics are not
  disproportionately punished, so the score is not simply diluted by long checklists.
- **Once-per-call moves scored against every reply.** Per-reply credit 14.9% vs **per-call
  16.7%** — and of the 87 dead criteria, **zero** were credited anywhere in any call. They are
  not being missed 19 times in 20; they are never performed at all.

Reading the text settles what they are. The criteria that get hit are substantive and
technical (*"clarify technical dependencies"*, *"specify the necessary backend
integrations"*). The dead ones are role and credibility moves — *"define the speaker's
professional role and explain the internal hand-off process"* (63 tries, 0 hits),
*"reassure the client by highlighting internal team expertise"*, *"reference past client
success stories"*. **They are accurate descriptions of what the expert does because of who he
is.** `ops/flag_uncoachable_milestones.py` swept all 405 milestones with an LLM and flagged
**17**; asking the data instead — never credited despite >= 6 attempts — finds **87 among the
221 that were attempted often enough to judge**. The two are not the same denominator, but
they are the same question, and the free method finds roughly five times as many.

**This will recur for every customer.** The product point is to run the pipeline on the
customer's own top performer, and a top performer is by definition unusual. So the fix cannot
be a one-off edit to Naren's rubrics.

## Decisions taken (by the user, in brainstorming)

1. **The standard comes from the customer's own top performer.** The product is the
   machinery, not Joveo's content.
2. **Scoring moves to the whole call**, with 2–3 scenarios per LLM request.
3. **Never-performed criteria are confirmed by the customer at onboarding**, not auto-pruned
   and not auto-gated by a model.

## What does NOT change, and the measured reason

- **Layer A, Layer B, Layer C** — untouched.
- **The criteria writer specifically.** It was tempting to regenerate criteria with
  `describe_mode: situated`. `calibration/trial_layer_c_arms.py` already tested that and it
  lost (1.04 / 0.89 / 1.09 against a 1.30 baseline). That trial was briefly suspected of the
  same population asymmetry that invalidated the ceiling — it does not have it: `matched` and
  `unrelated` are built from the same rows with only the rubric key swapped
  (`trial_layer_c_arms.py:700-701`). Its instrument was sound. **The verdict stands; do not
  regenerate criteria.**
- **The grader's verdict rules**, three-way scale and JSON contract. Changing them would make
  this a wording pass, which stopping condition #1 rules out.

## Design

### 1. Pipeline shape

```text
per rep call:
  step 1  detect candidate scenarios                    free — embeddings, no LLM
  step 2  chunk into groups of 2-3 scenarios
  step 3  one LLM request per chunk:
            FULL transcript (turn-numbered)
            per scenario: key, description, its triggering client turns,
                          its criteria, the expert's benchmark answer
          -> per scenario: did_occur (bool)
             per criterion: verdict, reason, quote, turn_index
  step 4  persist
```

~2–3 requests per transcript against ~6 today, because criteria stop being re-sent per
moment. **Cheaper than the current design, not more expensive.**

### 2. Chunk size is 2–3 scenarios, and the constraint is OUTPUT length

Not request count. `ops/rewrite_milestone_criteria.py` measured the real limit: at 20
milestones per request, one batch in 21 returned truncated JSON and those 20 were silently
left unprocessed. Output is ~60 tokens per criterion (verdict + reason + quote + turn), so
2–3 scenarios ≈ 8–12 criteria ≈ 600 tokens — comfortable. All ~25 criteria of a call at once
would be ~1,500+, which is where truncation already bit.

**A missing id is recorded as a miss**, so truncation manufactures coaching failures silently.
`score_milestones_batch` already reports missing ids loudly; that behaviour must be kept.

### 3. `turn_index` is not cosmetic

With a 1–3 turn window, evidence location is implicit. Across a 60-minute transcript it is
not, and it is the only thing that makes the coaching actionable *and* checkable. See the
gate: it enables a free, model-free hallucination detector.

### 4. Over-include scenarios, and let the model decline them

The top-1 vs top-2 matching margin is **~0.01 cosine** (p50 0.009–0.010) in both the live and
turn-mode taxonomies. Every assignment rests on the winner beating the runner-up by a hair.

Under per-moment scoring that is dangerous — the wrong scenario means the wrong criteria and a
meaningless verdict. Under whole-call scoring it mostly stops mattering: take the top 2–3
candidates per moment and the cost of a false positive falls from "wrong verdict" to "one
extra chunk of context", because the model can see the situation did not arise.

That requires a per-scenario `did_occur` verdict **before** its criteria are scored. Without
it, over-including inflates the denominator with all-miss scenarios and tanks the score.

**Stated honestly: this is a cousin of a question that has failed twice here** — the
standalone applicability judge (0.147 vs 0.120, 1.22:1) and the coverage judge (64.9% matched
vs 65.7% unrelated). Both asked *"did this moment call for this move"*: fine-grained, over 1–3
turns. This asks *"did this topic come up in the last hour"* with the full transcript in view —
coarser and far more answerable. It is not assumed to work; gate check 3 tests it.

### 5. The onboarding review, and the three states it separates

After the first scoring pass over a customer's team, every criterion nobody performed is
presented to the customer as one tick: **"not expected of my reps"** or **"yes, that's a real
gap."**

The data cannot make this call. *"Define the speaker's professional role"* is not something a
rep should do — a bad criterion. *"Reference past client success stories to demonstrate a
proven track record"* is a real, teachable sales skill — the most valuable coaching finding in
the set. Both look identical in the hit data: many attempts, zero hits. Only a human who knows
the team can separate them, and **the customer is the right human** — it is their standard,
and their answer is exactly the human ground truth this project has repeatedly concluded it
needs instead of another model refereeing a model.

Nothing is deleted. Three properties that are currently one thing are separated:

| | never-hit criterion |
| --- | --- |
| stored in the rubric | **always** |
| scored on every call | **always** |
| emits coaching advice | only if confirmed `real_gap` |
| counts in the headline score | only if confirmed `real_gap` |

Keeping them scored is load-bearing, not tidiness:

- a `real_gap` criterion is the product's most valuable output, not waste;
- improvement is only detectable if measurement never stopped;
- a new hire may perform it — deadness is a fact about this team at this time.

`not_expected` criteria leave the denominator, which removes a real distortion: 24% of
grading effort currently returns zero by construction and drags the headline score down for
reasons unrelated to the rep.

The never-hit set is also a report in its own right: *what makes your top performer
distinctive rather than teachable*.

## The gate — pre-registered, before anything is built

All four must pass. A failure is a real result and is reported as one.

1. **Discrimination holds.** Re-run `calibration/trial_grader_inputs.py`'s confirmed
   comparison against the new scorer: matched rubric vs deranged partner, per-scenario paired
   count. **Bar: >= 70% of decided scenarios, p < 0.05, on two independent draws** — identical
   to the bar the current scorer met at 77.4% and 82.3%. If a larger window makes the model
   sloppier, this catches it.

   **The harness needs one adaptation, and it must not be skipped.** Today it samples
   leakage-clean *responses*; a whole-call scorer needs whole *calls*, so the unit of both the
   sample and the leakage holdout changes from a response to a call. A call is leakage-clean
   for a scenario when it contributed no primary pair to it — the call-level condition
   `score_naren_ceiling.a3_eligible` already applies per row. Reusing the response-level
   sampler unchanged would score a whole call while claiming a per-response holdout and the
   comparison would be quietly wrong.

2. **Quote verification — free, mechanical, no model and no human.** Every verdict cites a
   quote and a `turn_index`; the quote must actually appear in the transcript at or near that
   turn. This is the specific new risk a large context window introduces, and it is a string
   match. **Bar: >= 95% of cited quotes verifiable.** Report the failures verbatim.

3. **The `did_occur` null.** Ask it about a deranged scenario that certainly did not occur in
   that call. **Bar: it must answer "no" in >= 90% of cases.** Below that, over-including is
   unsafe and step 1 falls back to top-1 matching.

4. **Read the flips.** Sample criteria that move miss -> hit under the wider window and check
   they are genuinely earned. Aggregates have misled repeatedly in this effort and reading ten
   samples has caught every instance.

## Data model

- `gap_events.gaps` is unconstrained JSONB — `turn_index` and `quote` need no DDL. Same reason
  the Layer D realignment needed zero schema change.
- **One new table** for onboarding answers: criterion status per customer
  (`unreviewed` / `not_expected` / `real_gap`). This is the first tenant-scoped table.
- The per-scenario `did_occur` verdict is stored alongside the gap event.

**Migration hazard, stated loudly.** `milestone_performance.attempts` currently means "times
this criterion was scored against a reply". It becomes "times against a call" — ~25 moments
collapse to ~1. **Old W and new W are not comparable.** Snapshot before switching and never
plot them on one axis. This codebase has been burned by exactly this class of change before.

Behind `layer_d.scoring_unit: moment | call`, defaulting to `moment`, so production is
byte-identical until deliberately switched — the pattern `pool_unit` and `describe_mode`
already follow.

## Explicitly out of scope

**Multi-tenancy.** There is no tenant concept anywhere today: one database, one `public`
schema, one taxonomy, no `customer_id` on `calls`, `scenarios` or `rubrics`. Selling this
needs tenancy across the whole schema, and that is larger than everything above.

It gets its own spec, afterwards, deliberately: the scoring redesign is testable today on data
already in hand, and if it fails its gate nothing has been spent plumbing a product that does
not work yet. Building tenancy around a scoring model that then changes is the expensive
ordering.

## Risks

- **The wider window invites fabrication.** Gate check 2 exists for this and is the reason
  `turn_index` is mandatory rather than nice-to-have.
- **`did_occur` is a relative of a twice-failed question.** Gate check 3, with a fallback to
  top-1 matching that costs only the over-inclusion benefit.
- **Onboarding is human time**, so setup is not zero-touch. Accepted deliberately: it is ~1
  hour, it is the only place the bad-criterion / real-gap ambiguity can be resolved, and the
  answer is per-customer ground truth nothing else supplies.
- **How many expert calls a new customer needs is unmeasured.** 416 calls produced 84 rubrics;
  the floor is unknown. It does not block this work but it blocks a sales conversation.

---

## Gate result (2026-08-15): FAILED all three checks. Do not enable `scoring_unit: call`.

`calibration/trial_call_scoring.py`, 25 leakage-clean calls, 41 (call, scenario) pairs,
`gemini-3.1-flash-lite` pinned, ~75 requests. Artifact `call_scoring_trial.json`.

| check | bar | result | |
| --- | --- | --- | --- |
| 1 discrimination | >= 70%, p<0.05 | **46.4%** (13W/15L/13T), p=0.85 | **FAIL** |
| 2 quote verification | >= 95% | **80.8%** (21/26) | **FAIL** |
| 3 `did_occur` null | >= 90% declined | **20.0%** (5/25) | **FAIL** |

### The finding: the 1-3 turn window was load-bearing, not a defect

**Check 1 is the one that kills it.** Under moment scoring the same comparison — matched
rubric vs a deranged partner's, on identical inputs — wins 77.4% and 82.3% of scenarios.
Under whole-call scoring it is **46.4% with p=0.85: a coin flip.** Widening the window did not
add signal, it destroyed the signal that was there.

The mechanism is coherent and shows up in all three checks at once. Give a model an entire
60-minute transcript and a generic criterion and it will find *something* that loosely
satisfies it — so the wrong rubric scores as well as the right one (check 1), a scenario that
never arose looks like it did (check 3), and when no real evidence exists the model supplies
some (check 2). The narrow window was acting as a **constraint that forced the criteria to be
about this moment**, and removing it removed the only thing making them discriminating.

This also reframes the earlier measurement that motivated the design. Per-call credit 16.7%
vs per-reply 14.9% looked like a small gain for a bigger window. It is not a small gain — it
is a small gain bought at the cost of the instrument.

### Check 2 caught real fabrication on its first run, and it was verified by hand

All 5 failures appear **nowhere in the transcript being scored**, not merely at the wrong
turn. One was checked end to end: `client_requests_operational_visualization` was credited
with *"The solution engineer is attached to a deal from day zero. Right? You're actually in
disco…"* at turn 128 of call `e5ec576d`. That sentence is not in `e5ec576d` at any turn — it
is in a **different** transcript, `027ed51b`, which the model was never shown. It generated
plausible expert-sounding phrasing and attached a turn number to it.

**Keep `verify_quotes` regardless of what happens to call mode.** It is free, needs no model
and no human, and it found a 19% fabrication rate the first time it ran. Any future design
that widens the evidence window must carry it.

### `did_occur` has now failed at every grain tried

Three attempts, three failures: the standalone applicability judge (1.22:1), the coverage
judge (64.9% matched vs 65.7% unrelated), and now the coarsest possible form — *"did this
topic come up anywhere in the last hour"*, with the full transcript in view — at 20%. The
argument that a coarser question would be easier was reasonable and is now **measured wrong**.
Treat any fourth variant as speculative.

### What survives

- **The onboarding review (§5) is untouched by this.** It never depended on call-level
  scoring; it addresses the 39%-dead-criteria problem, which is a content problem. It is the
  part of this design still worth building.
- **`verify_quotes`** — keep and reuse.
- **The gate itself.** Three automated checks, all pre-registered, cost ~75 requests and
  stopped a change that would have silently degraded scoring to chance while producing
  confident, quotable, fabricated coaching advice. That is the cheapest failure in this
  effort's history.

---

## CORRECTION and final result (2026-08-15, third run)

**The v1 and v2 discrimination numbers (46.4% and 35.0%) are RETRACTED. They were confounded
by this harness, not by the design.** A plain derangement gave the matched arm **5.08**
criteria per pair and the unrelated arm **3.64** — because the trial samples calls that are
leakage-clean for a scenario, which requires that scenario to have secondary-label pairs (the
big prominent ones, carrying more milestones), while partners were drawn from all 82. Fewer
criteria scores higher (`corr(n criteria, W) = -0.146`), so the comparison was biased against
the matched arm. Restricting to the 10 accidentally equal-sized pairs reversed the direction
(0.538 vs 0.454).

**The claim built on that — "whole-call scoring destroys discrimination, the 1-3 turn window
was load-bearing" — does not survive.** It was stated as a firm finding and it was not one.

Fixed by `size_matched_partner`: each scenario pairs with a content-dissimilar one carrying
**exactly the same number of criteria**, so both arms' denominators are identical by
construction. All 82 scenarios have such a partner, so nothing is dropped. The report now
computes criteria-per-arm and refuses to print a readable check-1 number if they differ.

### The clean result: 30 calls, 60 pairs, arms matched at 5.12 criteria/pair

| check | bar | result | |
| --- | --- | --- | --- |
| 1 discrimination | >= 70%, p<0.05 | **58.3%** (28W/20L/12T), p=0.31 | **FAIL** |
| 2 evidence verification | >= 95% | **77.2%** (254/329) | **FAIL** |

| | W | verdicts |
| --- | --- | --- |
| matched | **0.523** | 145 full / 31 partial / 131 miss |
| unrelated | **0.443** | 119 full / 34 partial / 154 miss |

**What is now true, stated precisely.** The right rubric does outscore a stranger's — the
direction is correct and the earlier inversion was an artifact. But at **58.3%, p=0.31** it is
neither above the pre-registered bar nor statistically distinguishable from chance, against
moment mode's 77.4% and 82.3% on the same kind of comparison. **Whole-call scoring
discriminates materially worse than the 1-3 turn window. It does not discriminate backwards.**

**Check 2 is the decisive failure, and it is unconfounded** — a mechanical string match with
no arm comparison. **23% of credits cannot be located in the transcript at all, and 30 quotes
appear nowhere in it.** Fabrication persisted through the v2 fixes that were supposed to
remove its cause: allowing `across_turns` evidence (79 of 329 credits used it) did not stop
the model inventing verbatim quotes elsewhere.

**Credit inflation is unfixed.** W 0.523 against moment mode's 0.078. Requiring evidence for
every credit was the anti-inflation mechanism and it did not work, because the model supplies
evidence that does not survive checking.

### Verdict

`layer_d.scoring_unit` stays `moment`. The gate fails on evidence verification, cleanly, and
on discrimination, weakly. **Do not enable call mode and do not attempt a v3 of the prompt** —
three prompt revisions have now failed, and the residual failure is fabrication under a long
context, which is not a wording problem.

**The onboarding review (§5) remains untouched by all of this** and is the part of this design
still worth building.

### Method note worth keeping

The v1/v2 confound is the SYMMETRIC-FILTERING failure this codebase has hit six times, in a
new disguise: the arms were matched on *content* (deranged partners, cosine-checked) and
nobody checked they were matched on *size*. **When two arms are compared, enumerate every
property that differs between them, not just the one under test** — and put the check in the
harness, which is now done.
