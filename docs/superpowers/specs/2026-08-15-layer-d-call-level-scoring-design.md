# Layer D scores a call, not a reply — and the customer decides what counts (2026-08-15)

Status: **approved in brainstorming, not implemented.** Nothing below is built.

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
| share of a rubric's criteria hit by *somebody* (union), mean | **46%** |

Two candidate causes were tested and **both rejected**:

- **Rubric size.** `corr(criteria per rubric, W) = -0.09`. Large rubrics are not
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
