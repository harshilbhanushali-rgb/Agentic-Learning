# Head-to-head — can comparison against the expert's real response replace criteria? (2026-08-13)

**Status: RUN AND CLOSED — 2026-08-13. Stopping conditions 2 and 5 both fired; the headline (§7's
W3) was never computed.** Everything below is the pre-registration as it stood before any judge
call. It is deliberately NOT edited to match the outcome — a design rewritten after its result is
no longer a pre-registration. The result is recorded once, here:

| control | run 1 | run 2 (model pinned, both keys) | bar | |
| --- | --- | --- | --- | --- |
| C1 swap agreement, pooled | 0.694 | **0.669** | >= 0.75 | **FAIL** both |
| C2 expert vs expert | 0.582 | 0.543 | [0.40, 0.60] | pass both |
| C3 sensitivity | 0.713 | 0.750 | >= 0.75 | lands ON the bar |
| **C4 transplant penalty** | **0.843** | **0.835** | < 0.75 | **FATAL**, replicated to 0.008 |

**§15's honest prior named C4 as the likeliest failure, and it was right.** Native beats
transplant 83.5% with the same person on both sides, so the headline would have reported "the CSM
outperforms the expert" as a pure retrieval artifact. C1's failure is independent and deeper: the
judge reverses itself on ~20% of swapped items, which is a property of the judge that no pairing
design repairs. Full write-up: `CLAUDE.md` and `Brain/PROBLEMS_AND_FIXES.md`.

**What survives:** `artifacts/h2h_moments.json` (589 moments, 98 calls, content-hashed) and the
retrieval gate of §4, which passes in both directions. Retrieval was never the problem.

---

*(Original pre-registration follows, unedited.)*

Every threshold, control and stopping condition below is
fixed before a single judge call is spent. One stage — the retrieval gate (§4) — has already run,
and its result is recorded here rather than promised.

**Depends on:** `2026-08-12-layer-c-profile-rebuild-design.md` §6.6, whose stopping condition #1
fired and named this design as the successor; `2026-08-11-naren-ceiling-measurement-design.md`
for the holdout machinery and the derangement null; `2026-08-13-layer-c-skills-vocabulary-design.md`
for the pre-registration form.

---

## 1. The question

**Drop criteria entirely. Given a client moment, is the CSM's response better or worse than the
expert's — judged directly, one against the other?**

Criteria-based scoring is closed. The expert scores 0.114 against his own rubrics and 0.090
against deliberately unrelated ones — **1.2 : 1, reproduced three times** — and the four-arm
rebuild trial then failed its pre-registered gate at 1.04 / 0.89 / 1.09 against a fair
same-model, same-clustering baseline. Three wording passes, one input pass and one unit pass have
now failed. This design does not attempt a fourth.

### 1.1 Why the null is structural, and why that is the whole point

Every failed attempt above argued about what the null *should* be. A criterion scored 0.147 on
the matched rubric and 0.120 on an unrelated one, and the argument became whether 1.22 : 1 is
evidence of anything.

**A pairwise comparison has no such argument available.** Two responses, one moment, pick one.
A judge with no ability whatsoever lands at 50%. The bar is arithmetic, not a matter of
interpretation, and it cannot be talked upward after the fact.

That is the single reason this approach is worth building rather than a sixth signal search.

### 1.2 What this does NOT fix

The two walls are independent. This design attacks **wall 1 only** — the ruler.

**Wall 2 is untouched.** A win rate says the CSM is behind; it does not say *at what*. 405
milestone axes at ~3.75 observations each do not fold into a behavioural vocabulary (78% of them
abstract to a phrase occurring exactly once; merge validity 0.20 against a 0.80 bar), and nothing
here changes that. **A working head-to-head produces a score, not a profile.** Stating this now so
a passing result is not later read as more than it is.

Also unchanged and explicitly out of scope: Step 0's false positives, the 36% of gap events that
are recognition failures, and `extract_csm_response_window`'s habit of capturing scheduling
chatter instead of the substantive answer (seen in `rec6` @ turn 135). §5.3 records how that last
one is bounded rather than fixed.

---

## 2. The mechanism

```text
CSM transcript
  |
  |-- client turn T ---[selection: FULL pool, sink rule]--> is this a signal at all?
  |                                                              |
  |-- CSM's answer R_csm                                         v
                          [retrieval: COACHABLE-ONLY pool]--> nearest Naren trigger
                                                                 |
                                                                 v
                                                            his answer R_naren

        judge sees:  T  +  {R_csm, R_naren}  blinded, both orders
```

**Two stages, two different vector populations, deliberately.** They do opposite jobs, they match
against different objects, and collapsing them breaks one:

| stage | T is matched against | filtering | why |
| --- | --- | --- | --- |
| **selection** — is T a coachable moment at all? | **scenario vectors** (`shared/scenario_vectors`) | **full map, sinks included** | a sink winning the match is the *only* mechanism that can reject a turn. Layer D's rule verbatim — `relative_match.is_sink_flags` over `ego_trap/scenario_pool`'s full map — measured there at 60.7% rejection, and it costs zero Gemma calls. Filtering sinks out here would make every turn a signal by construction |
| **retrieval** — which expert moment to compare against? | **`kb_pairs` trigger vectors** | **coachable-filed pairs only** | §4 measured 18.8% of unfiltered neighbours as sink-filed: 1 in 5 comparisons would hand the judge backchannel as "the expert's response". One SQL predicate takes that to zero by construction |

Each stage therefore uses the mechanism that was actually measured for it — Layer D's 60.7%
rejection is a scenario-vector figure, §4's 81.2% is a trigger-vector figure, and neither number
transfers to the other stage.

That second row is also what settles Pinecone. `is_coachable` is not in the `"triggers"`
namespace metadata, so **the filter that fixes retrieval's largest defect is not expressible
against Pinecone** without a per-match DB round trip — which is the Postgres work anyway, plus a
network dependency and a `text` field truncated to 500 chars ([`pinecone_store.py:41`](../../../Brain/shared/pinecone_store.py)).
Pinecone stays a `--pinecone-compare` measurement, the precedent `dry_run_ego_trap.py` set.

### 2.1 Symmetry rules, each closing a specific asymmetry

- **Both sides get exactly one trigger and one response.** The judge sees the CSM's trigger and
  two candidate responses; **Naren's own trigger is not shown.** Showing it would let the judge
  see which response is transplanted and penalise provenance directly. §5 measures that cost
  instead of leaking it into the prompt.
- **Naren's context is one turn, so the CSM's is one turn.** `kb_pairs` stores only
  `trigger_text`; the CSM transcript could supply preceding turns. Handing one side more context
  is a confound, so richness loses to symmetry.
- **The same substantive-text filter applies to both.** `kb_pairs` was built through
  `v1/layer_b._is_substantive` (≥5 alphabetic non-stop tokens). CSM client turns pass the same
  function, or the CSM side would admit filler the expert side structurally cannot.

### 2.2 Population

**All 106 `csm_recordings/` transcripts**, not the ~19 that Layer D scored. The unit here is a
*moment*, not a milestone, so this needs no rubric, no `milestone_performance` row and no Layer D
run — which is also why every uninterpretable Layer D figure is irrelevant to it. All 106 map to
`CSM_MADHUMITA`, so this measures one person; the design generalises to a roster without change,
but says nothing about between-CSM variance.

---

## 3. The confound this design exists to handle

The CSM's response is **native** to the trigger. Naren's is **transplanted** from a different call
answering a nearby question. His answer may name an ATS, a spend figure or a person that do not
exist in this moment, and be marked down for a retrieval artifact rather than for quality.

**This biases systematically against the expert, and an uncorrected win rate would be worthless.**

Three framings were considered:

| | framing | verdict |
| --- | --- | --- |
| F1 | one trigger, two responses, pick one | clean 50% null, but carries the asymmetry untreated |
| F2 | show both `(trigger, response)` pairs, ask who handled their own moment better | removes the asymmetry, but "better" becomes confounded by which situation was easier, and the null stops being a coin flip |
| **F3** | **F1, plus measure the asymmetry directly** | **adopted** |

F3 is F1 with control **C4** (§5): take a *Naren* moment, hold out its call, and pit **his real
response (native) against a retrieved neighbour of his own (transplant)**. Both sides are the same
expert, so any win for the native side **is** the transplant penalty — measured in the same units,
on the same judge, as the headline. F2 was rejected for trading a measurable confound for an
unmeasurable one.

---

## 4. Retrieval — already measured, gate already passed

Retrieval is the load-bearing input: if it hands the judge a moment that is not the same kind of
moment, every downstream number is meaningless regardless of judge quality. So it was gated first.

`calibration/probe_retrieval_gate.py`, leave-one-**call**-out over the real 4,605-pair pool
(385 calls, 154 scenarios, 63.1% coachable). Holding out the whole call rather than the row is
`score_naren_ceiling.hold_out`'s rule, and it matters more here: adjacent turns of one call are
near-duplicates, so a row-level holdout would score a moment two turns away as a successful
retrieval.

| metric | observed | base rate | lift, 95% CI | |
| --- | --- | --- | --- | --- |
| **neighbour is coachable, not sink-filed** | **0.812** | 0.631 | **+0.182 [+0.168, +0.196]** | the gate — **passed** |
| neighbour shares `scenario_key` | 0.258 | 0.023 | +0.235 [+0.219, +0.251] | corroboration, **11× chance** |

**First measurement of the trigger-vs-trigger cosine band in this repo:** p10=0.630, p25=0.659,
p50=0.689, p75=0.717, p90=0.746. Higher and tighter than the trigger-vs-scenario band
(p10=0.496, p50=0.550, p90=0.613) that `relative_margin` was calibrated against — so a retrieval
floor is expressible in this band and must never borrow a value from that one.

Three cautions recorded with the pass:

- **`same_scenario@1` understates quality.** Reading the samples, several `False` rows are good
  matches — a budget query retrieving a spend-disclosure moment, a Reddit brand-safety concern
  retrieving a Reddit brand-regulations concern. `scenario_key` is layer_b's scalar best match,
  documented as unreliable. It is corroboration, never the gate.
- **This is Naren-querying-Naren** — same speaker, same corpus, same register. It is the
  **optimistic bound** on the cross-corpus CSM→Naren retrieval the design needs. A pass is
  necessary, not sufficient; W0 re-measures the same metrics on the real cross-corpus direction
  and §9 stops on that number, not this one.
- **A 150-item probe on the same question returned a coin flip** (clean top-1 0.492 against a
  0.416 base, CI spanning zero). The pool was 74 scenarios over 150 items — a comparable neighbour
  was frequently absent. **Pool density, not signal, was the finding**, and it is why no retrieval
  conclusion may be drawn from a subset here.

### 4.1 The embedder question — bge is adopted, but the comparison is NOT closed

Measured on 150 pairs held in **both** spaces already on disk
(`labeled_trigger_quality_sample.json` bge vectors, `embedder_compare_vectors.npz` gemini
`trigger_sym`), aligned by cross-checking the npz `labels` array against the JSON `coachable`
sequence — the npz carries no `pair_id`, so positional alignment is otherwise unverifiable and the
arm is refused rather than assumed:

| | bge_768 | gemini_3072 | gemini_768 |
| --- | --- | --- | --- |
| clean top-1, coachable query | 0.492 | 0.556 | 0.556 |
| **paired, gemini − bge** | — | **+0.064 [−0.095, +0.222]** | same |

**Parameters were verified, not assumed.** `trigger_sym` was embedded as
**`SEMANTIC_SIMILARITY`** ([`embedder.py:125`](../../../Brain/preprocessing/embedder.py)), the
correct symmetric task type — not the `RETRIEVAL_QUERY` / `RETRIEVAL_DOCUMENT` split that already
confounded the `coupling` criterion once. Truncation to 768 is re-normalised, as Matryoshka
requires. bge carries the same prefix on both sides, so each space is internally symmetric and the
comparison is fair to both.

**But the comparison is UNDERPOWERED, and this is stated rather than glossed.** Both spaces were
measured on a 150-item pool spanning 74 scenarios — roughly 2 items per scenario — where **bge
scored *not above chance* and gemini barely above it.** A difference between two models cannot be
detected in a regime where both sit at the floor. The full-pool run proves how much that sparsity
mattered: bge went from a coin flip at 150 items to 0.812 clean and 11× chance at 4,605. So the
honest claim is *"no measurable difference in a pool too sparse for either to show one"*, which is
much weaker than *"no difference"*.

**Adopted anyway, on the second reason rather than the first.** Settling it properly means
re-running §4's gate in gemini space: 4,605 embeddings, one request per text, ~5 days against a
1,000/day cap. That is **blocked on the async batch endpoint**, not decidable now — and bge has
already cleared the gate outright, so nothing waits on it. Recorded as an open item, not a verdict.

**The harness pins its backend explicitly rather than inheriting `tuning.yaml`'s
`embedding.backend`.** If that key flips to `gemini` mid-run, the harness would either fire
thousands of paid requests or, far worse, compare a bge vector against a gemini vector in one
cosine matrix — meaningless, and it would produce confident numbers. Every artifact records its
backend, the same discipline as `scored_by`. Because W0 persists raw retrieval candidates and
similarities, re-running that free stage in a different space later costs one stage, not a redesign.

Two traps avoided, both from `compare_embedders.py`'s own recorded post-mortem: absolute cosine is
never compared across models (that measures scale, not discrimination — gemini's median top-1 is
0.738 against bge's 0.602 on identical texts), and `sink_real_margin`'s "AUC 0.437" is
direction-inverted and worth 0.563.

---

## 5. Controls — four, all pre-registered, all before the headline exists

**No control, no headline.** Two judges in this effort have already failed their own nulls: the
applicability judge at 1.22 : 1, and the coverage judge at 64.9% vs 65.7% — and both had produced
publishable-looking numbers first.

| # | control | construction | bar | protects against |
| --- | --- | --- | --- | --- |
| **C1** | **position swap** | every item judged in **both** orders, **in different batches** | agreement **≥ 0.75** | a judge whose answer is its prompt's layout |
| **C2** | **expert vs expert** | two Naren responses retrieved for one query trigger at adjacent ranks with cosine within 0.01, so neither has a fit advantage | **the higher-ranked neighbour's** win rate within **[0.40, 0.60]** | a judge reading something other than quality |
| **C3** | **sensitivity** | matched response vs one from a **deranged unrelated scenario** | **the matched response's** win rate **≥ 0.75** | a judge that cannot tell relevant from irrelevant — the criteria failure in a new form |
| **C4** | **transplant penalty** | Naren native vs Naren transplanted, his call held out | **the native response's** win rate, **reported**; ≥ 0.75 is fatal (§9) | §3's asymmetry |

**Every rate above is computed after order-averaging**: an item contributes one outcome, taken
across its two orders. An item whose orders disagree contributes a **tie**. Ties are excluded from
every win-rate denominator and their share is reported separately — a rate quoted without its tie
share is unreadable, and burying disagreement inside a denominator would let C1's failure hide
inside C2's pass.

**C1's bar is derived, not picked.** Agreement `a` is measured over items where **at least one**
order returned a decisive verdict; items both orders called a tie are excluded and reported. If
agreement is `a`, the share of decisions driven by signal rather than position noise is about
`2a − 1`. At `a = 0.75` that is half. Below half the headline is mostly layout.

**C3 reuses `derange()` and `merge_cosine_threshold`** from the ceiling harness — **inherited**,
so this design adds no `tuning.yaml` key. Every knob in that file must be a property of the data.

**C1 costs nothing extra**, since C2, C3 and C4 all judge every item in both orders. It is computed
over the **pooled** items of all three, so it is finalised only once all three control artifacts
exist — W2a reports its own slice as a running figure, never as the verdict. W3 re-reports C1 on
its own items as a consistency check.

### 5.1 Batching, and the one rule that batching can break

Batch size **5**, not 10: each item carries a trigger plus two full responses, several times the
payload of a milestone description, and truncation is the binding constraint (measured at batch 20
for the far smaller rewrite payload in `ops/rewrite_milestone_criteria.py`).

**The two orders of one item must never share a batch, or a call.** A judge shown the same pair
twice will be consistent for the wrong reason, and C1 would report the judge's memory as its
reliability. Orders are assigned to disjoint batch sets and the harness asserts it.

**An explicit verdict on every item, never a returned subset.** This is the generalising lesson
from the objective function's failure: its prompt instructed sparsity, and "return a subset"
invites picking a top few and stopping.

### 5.2 Confounds reported, not controlled

Three biases cannot be designed out, so they are measured and reported beside the headline.
**None is addressed by prompt instruction** — three wording passes have already failed here, so
instructing the judge not to be biased is not treated as a control.

- **Length.** `response_word_count` scored AUC 0.853 for "is this coachable" in this repo's own
  labelled sample. A judge preferring the longer answer would reproduce that as a fake win.
  Reported: correlation between length ratio and outcome, plus the win rate restricted to a
  length-matched subset (|log length ratio| ≤ 0.25).
- **Retrieval quality.** Win rate stratified by top-1 cosine decile. Judging everything above the
  p10 floor and stratifying afterwards means **one run measures the whole floor grid** — the same
  property as Layer C's `(percentile, fraction)` grid, where selecting a row afterwards needs no
  re-run.
- **Position.** The raw rate at which slot 1 wins, across all stages.

### 5.3 A bounded known defect

`extract_csm_response_window` sometimes captures scheduling chatter rather than the substantive
answer. Not fixed here (§1.2). Bounded instead: a random 30-item sample of extracted CSM windows
is read at the §8 checkpoint and the mis-extraction rate is reported, so the headline carries a
stated contamination bound rather than an unknown one.

---

## 6. Pre-registered thresholds — inherited vs invented

Stating which is which, because a design earns credibility by inheriting its gates rather than
inventing them.

| value | source |
| --- | --- |
| sink-rejection rule (best match is a sink ⇒ not a signal) | **inherited** — `relative_match.is_sink_flags`, Layer D, 60.7% measured |
| `merge_cosine_threshold` for C3's derangement | **inherited** — already-calibrated knob |
| call-level holdout | **inherited** — `score_naren_ceiling.hold_out` |
| `_is_substantive` (≥5 content words) | **inherited** — `v1/layer_b` |
| trigger-vs-trigger band p10=0.630 … p90=0.746 | **measured** — §4, this design |
| retrieval floor = p10 of that band (0.630) | **derived** from the measured band; swept post hoc for free (§5.2) |
| batch size 5 | **invented**, by analogy to `_DESCRIBE_BATCH_SIZE` and the batch-20 truncation measurement |
| **C1 agreement ≥ 0.75** | **invented**, with the `2a − 1` derivation in §5 |
| **C2 within [0.40, 0.60]** | **invented** |
| **C3 matched ≥ 0.75** | **invented** — the one number with no precedent |
| **C4 native ≥ 0.75 is fatal** | **invented** |
| length-match band \|log ratio\| ≤ 0.25 | **invented** |
| headline sample 300 moments | **invented**, sized in §10 |

---

## 7. Workstreams — how this splits across parallel sessions

**Why this design can parallelise and Layer D cannot.** Every stage here is read-only against
Postgres, enforced by `SET SESSION default_transaction_read_only = on`. Nothing touches
`gap_events` (SERIAL PK, re-processing appends duplicates) or `milestone_performance`
(`attempts = attempts + 1` on conflict). Two concurrent Layer D runs corrupt each other silently
and did, on 2026-08-10; two concurrent stages here cannot.

| stream | what it does | cost | needs | may run beside |
| --- | --- | --- | --- | --- |
| **W0** | build and **freeze** the moment set: parse 106 transcripts, apply `_is_substantive`, select signals against the full pool, retrieve partners from the coachable-only pool, re-measure §4's metrics **cross-corpus**, warm the embed cache → `h2h_moments.json` | **free** | §4 (done) | nothing — it is the only cache writer |
| **W1** | pure helpers + tests (pairing, swap assignment, derangement wiring, win-rate maths) | **free**, no DB | — | anything, from day one |
| **W2a** | **C2** (and C1's first slice) → `h2h_control_c2.json` | ~40 calls | W0 | W2b, W2c |
| **W2b** | **C3** → `h2h_control_c3.json` | ~40 calls | W0 | W2a, W2c |
| **W2c** | **C4** → `h2h_control_c4.json` | ~40 calls | W0 | W2a, W2b |
| **W3** | headline CSM-vs-Naren → `h2h_headline.json` | ~120 calls | **all of W2 passing** | — |
| **WB** | Track B: more CSM calls (§11) | free | — | everything, always |

**Default run order is sequential:** W0 → W1 → W2a/W2b/W2c → W3. The structure above is what makes
splitting *possible*, not mandatory.

### 7.1 The handoff contract, which is what makes a split safe

Any stream can be handed to another session because each declares exactly three things:

1. **Input artifact, frozen and content-hashed.** W0 writes `moments_sha`; **every downstream
   artifact records it**, and a stage refuses to run against a mismatched hash. Without this, two
   sessions judge different moment sets and the results cannot be combined — the same defect as
   `arm0_baseline` being scored against a different clustering run than the arms it was compared to.
2. **Its own output artifact and its own log file.** No stage appends to another's file.
3. **Its exact command**, including the `-HostAddr` bypass.

### 7.2 Three constraints on running streams at the same time

- **One API key per concurrent paid stream.** `gemma.py` accepts an ordered key list and rotates
  ([`gemma.py:149`](../../../Brain/shared/gemma.py)). Streams sharing one key will 429 each other
  into backoff — the measured ceiling is **tokens, not requests** (34.66K/30K TPM while requests
  sat at 6/100). With one key, the paid streams serialise.
- **`embed_cache.db` gets exactly one writer.** W0 warms it; every later stage is a read-hit.
  Concurrent SQLite writers are the one shared-mutable-file hazard in an otherwise read-only design.
- **Flush the paid artifact before anything free can block it.** Every batch is written on
  completion. One prior run finished all 95 LLM calls and lost every result because a free DB
  lookup gated the persistence of expensive work.

---

## 8. Read the samples — at three named checkpoints

Non-negotiable, and named in advance so they cannot be skipped by a passing aggregate.
`merge_cosine_threshold` was chosen by reading what each threshold fused, not by counting: at 0.80
the count still looked reasonable while it was fusing campaigns, sales teams, brands, markets and
vendors.

| checkpoint | question |
| --- | --- |
| after **W0** | are the retrieved Naren moments genuinely the same *kind* of moment? 20 pairs, read verbatim |
| after **W0** | §5.3 — 30 extracted CSM response windows: how many are scheduling chatter rather than the answer? |
| after **W2** | read the judge's `reason` on 20 items where the two orders **disagreed**. A judge that flips on layout should look incoherent there; one that flips on genuine ties should not |

---

## 9. Stopping conditions

1. **W0's cross-corpus retrieval fails §4's gate** — the same bar, unchanged: the 95% bootstrap
   interval on `clean_top1`'s lift over its base rate must exclude zero. The CSM→Naren direction
   failing where Naren→Naren passed means retrieval does not cross corpora. **Stop before any
   judge call.**
2. **C1 agreement < 0.75** → the judge is answering its layout. Report; claim no win rate.
3. **C2 outside [0.40, 0.60]** → the judge reads something other than quality. Report; claim no
   win rate.
4. **C3 matched < 0.75** → the judge cannot separate a relevant response from an irrelevant one.
   **This is the criteria failure in a new form and it kills the approach**, not just the run.
5. **C4 native ≥ 0.75** → provenance dominates quality. The headline is uninterpretable as a
   comparison; report the transplant penalty as the finding.
6. **All controls pass, but the headline sits inside C1's noise band** → report the band; do not
   pick a winner. An effect smaller than the instrument's own inconsistency is not a result.

Conditions 2–5 each mean **the instrument is broken, not underpowered**. More data does not
rescue any of them, and none should be retried with a reworded prompt — that is how a result gets
tuned into existence, and it has already failed three times here.

---

## 10. Cost

| stage | calls | basis |
| --- | --- | --- |
| smoke test, all paths | ~20 | §12 |
| W2a — C2 | ~40 | 100 items × 2 orders ÷ 5 |
| W2b — C3 | ~40 | 100 items × 2 orders ÷ 5 |
| W2c — C4 | ~40 | 100 items × 2 orders ÷ 5 |
| W3 — headline | ~120 | 300 items × 2 orders ÷ 5 |
| **total** | **~260** | against the arms trial's ~1,090 |

The 300-moment headline sample is drawn **seeded and stratified**, never `--limit N`. An
alphabetical prefix returned every subject-matter scenario and not one client-posture scenario,
and four arm comparisons ran that way before it was noticed. Composition is printed in the report
header and the report shouts if a stratum is empty.

Expected supply: ~1,100 client turns across 106 transcripts (scaled from 201 turns over 19), of
which Layer D's sink rule rejected 60.7%, leaving roughly 430 candidate moments before the
retrieval floor. If W0 yields materially fewer than 300, the headline sample shrinks and the
report says so rather than quietly sampling with replacement.

---

## 11. Track B — more CSM calls, independent of everything above

Stated here because it is the other live lever and it blocks nothing.

At ~47 attempts per call over 237 milestones:

| calls | observations per milestone | |
| --- | --- | --- |
| 19 (today's Layer D scope) | 3.75 | unusable |
| ~130 | 25 | loosest usable standard, quantization step 0.020 |
| ~420 | 83 | matches the ±0.006 noise floor |

**106 transcripts are already on disk** in `csm_recordings/`, all `CSM_MADHUMITA` — so the ~130
row is nearly met by data that has already been fetched, and the bottleneck was never fetching.

**`JOVEO_SPEAKER_NAMES` fails OPEN and must be checked on every new batch.** An unlisted Joveo
colleague is classified as the CLIENT, which invents coaching signals out of internal chatter. 14
were caught on the first 106-call pull. `ops/fetch_avoma_recordings.py` now refuses to stay quiet
about an unconfigured internal speaker; that warning is not optional reading.

**The caveat that matters:** more calls make the *profile* better-powered, not the *scoring*
valid. Until this design's controls pass, more data yields more confident numbers from an
instrument already known not to discriminate.

---

## 12. Verification

- **Smoke-test end to end before any full run**, ~20 calls across every stage. `py_compile`
  catches neither a missing import nor a positional slice over a reordered tuple, and two launches
  died mid-generation on exactly those. `score_naren_ceiling.py` already had this in
  `--max-items-per-arm`.
- **Pure helpers get tests before any spend** — swap assignment (the two orders land in disjoint
  batches), pairing, derangement wiring, win-rate maths under ties. Same split
  `shared/cluster_evidence.py` and `shared/topic_grouping.py` already follow. `probe_retrieval_gate`'s
  helpers were checked this way against hand-built matrices before its run.
- **`--load PATH` replays every artifact at zero cost**, so every number is re-derivable and a
  changed criterion does not cost the budget again. Raw judge output is persisted, not only the
  derived win rates — correcting a criterion on the embedder comparison cost 461 requests a second
  time because only the scores were kept.
- Run tests **file-by-file**: four test files each load spaCy's 392 MiB contiguous vector table and
  the suite is unreliable in one process on 16 GB Windows.

## 13. Zero writes — enforced, not promised

- Connections open through `_connect_read_only`, which issues
  `SET SESSION default_transaction_read_only = on` and verifies it, so a stray write fails at
  Postgres rather than relying on care.
- No Layer D table is touched. `ops/clear_ego_trap_data.py` is **not** required before a run, and
  running this design cannot corrupt a Layer D baseline.
- The only file written outside `artifacts/` is `embed_cache.db`, a hash-keyed cache that cannot
  corrupt anything.
- **No scenario, rubric, milestone or verdict is written.** Adoption is a separate, later,
  explicit step gated on §9.

## 14. Files

| file | change |
| --- | --- |
| `calibration/probe_retrieval_gate.py` | **already built and run** — §4's gate |
| `calibration/trial_head_to_head.py` | new — W0/W2/W3, one `--stage` per workstream |
| `shared/head_to_head.py` | new — pure helpers (pairing, swap assignment, win-rate maths) |
| `shared/prompts.py` | add `PROMPT_HEAD_TO_HEAD_BATCH` |
| `tests/test_head_to_head.py` | new |
| `tuning.yaml` | **unchanged** — every threshold here is inherited, measured or harness-local |

## 15. Honest prior

**Better than even — call it 60–65%** that the controls pass, which is higher than the arms' even
odds for one reason: the judge's question is far easier. "Which of these two answers handled this
better" is a comparison a competent reader makes routinely; "does this abstract criterion apply to
this response" is one that failed three times. And the null is structural, so a pass cannot be
manufactured by argument.

**The most likely failure is C4, not C3.** The judge probably *can* tell a better answer from a
worse one; what it may not survive is the transplant asymmetry — Naren's response answering a
neighbouring question and reading as slightly off-topic in every single comparison. If C4 comes
back at 0.75+, this design produces a clean measurement of its own invalidity, which is a real
answer and a cheap one at ~40 calls.

**A speculative follow-on, recorded but NOT pre-registered.** The judge emits a `reason` per item.
Aggregated over a few hundred losses, those reasons are a **bottom-up** source of profile axes
that owes nothing to the 405 milestones and therefore sidesteps wall 2's folding problem entirely.
That is an idea, not a plan: it needs its own pre-registration, its own null, and its own judge
check. Writing it down now so it is not later presented as something this design established.

Recorded before the first call, so it cannot be revised afterwards.
