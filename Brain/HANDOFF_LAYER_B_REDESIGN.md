# HANDOFF — Layer B redesign (2026-08-16)

Continue-from-here for a **redesign of Layer B** — the stage that turns transcripts into
`kb_pairs` and routes each client turn to a scenario.

**BE AS CREATIVE AS YOU WANT.** This is explicitly not a bug-fix ticket. The measurement in §1
says the current design has a *type-level* mismatch with the stage above it, and no amount of
threshold tuning fixes a type error. Proposals that restructure what a "pair" is, what routing
means, or where the coachable/junk decision is made are all in scope. What is NOT negotiable is
the measurement discipline in §5 — this repo's entire history is of plausible ideas that failed
a controlled test, and the ones that survived did so because the test was built first.

**Scope boundary:** Layer A (clustering, the noise-rescue, adjudication) is settled elsewhere.
Treat the taxonomy as an input you do not control.

---

## 1. THE RESULT THAT REOPENS THIS — measured 2026-08-16, four arms, zero chat calls

Layer A's noise-rescue admits **+1,288 clean client turns** into coachable clusters — **+62%
more evidence, 0.2% content-free**, verified by reading. The pre-registered chain was:

> more turns per scenario → more `kb_pairs` → more response clauses → more milestone support

**Link one is broken:**

| stage | base | rescued | delta |
| --- | --- | --- | --- |
| Layer A evidence (turns into coachable clusters) | 2,067 | 3,355 | **+62%** |
| **Layer B: pairs reaching those scenarios** | **1,673** | **1,687** | **+0.8%** |
| Layer C clause pool | 13,218 | 14,165 | +7.2% |
| milestones | 171 | 123 | −28% |

**A 62% gain upstream became 0.8% downstream.** The cause is structural, not a tuning miss: a
rescued client turn can only become a pair if it has ≥5 content words **and** Naren replied.
Most don't. Layer A's unit is a *client turn*; Layer B's unit is a *trigger→response pair*.
Adding turns cannot add pairs.

**Both controls were clean, which is what makes this readable:**

- **Noise floor is ZERO.** `base_1` and `base_2` ran in separate processes and matched
  byte-for-byte (171 milestones, 0 lost, 0 gained). This **retires a documented assumption** —
  CLAUDE.md records Layer C as non-reproducible across launches (385/398/403-407). It is not.
  That variance was CUDA **embedding** nondeterminism; with cached vectors and
  `random_state=42` single-threaded, Pass 1 is deterministic. Future Layer C A/Bs need no floor
  arm when embeddings are cached.
- **Volume perturbation is harmless.** A placebo padding the base taxonomy with deliberately
  WRONG content to matched volume **lost 0 milestones and gained 13** (179 total, and MORE
  clauses than rescued: 14,708 vs 14,165). So the rescued arm's −48 cannot be blamed on pool
  size. This also retires the spec's own assumption that "perturbing a clause pool at all costs
  ~6 milestones".

**The damage is a REROUTE, and it is Layer B's.** Of the 81 lost milestones, only **36%** of
their clauses are routed to that scenario at all in the rescued arm. One scenario went from
**29 calls / 11 milestones to 7 calls / 2** — Layer C clustered faithfully; Layer B sent it 22
fewer calls' worth of material.

**Quality did not improve either.** Mean relevance 0.6358 → 0.6340 (flat). Normalised
recurrence rose 0.211 → 0.250, **but the junk placebo scored 0.261** — so that gain is a
pool-size artifact. Milestones backed by ≥10 distinct calls fell **59 → 36** (placebo 63).

**One honest confound:** base and rescued taxonomies are two *adjudication draws*, and that
step measured **18 vs 27 scenarios on byte-identical input**. Part of the −48 is draw noise.
**The +0.8% pair passthrough is not confounded** — it is a direct count, and it is the finding.

Artifacts: `artifacts/layer_bc_{base_1,base_2,rescued,placebo}.json`
Spec: `docs/superpowers/specs/2026-08-16-layer-bc-downstream-validation-design.md`
Harness: `calibration/layer_bc_arms.py` (+ `tests/test_layer_bc_arms.py`, 38 tests) — **free to
re-run, and it is your instrument.** Any Layer B proposal should be measurable through it.

---

## 2. Established defects

Every item is measured. Do not re-derive them; do challenge them.

### 2.1 Unit mismatch (§1) — the headline
Layer A clusters client turns. Layer B needs trigger→response pairs. There is no path by which
more of the former becomes more of the latter.

### 2.2 A pair requires Naren to have replied
**20,788 client turns → 3,977 pairs.** 81% never become a trigger, gated by `_is_substantive`
(≥5 content words) and "Naren must reply". Layer A clusters all 20,788, so **a scenario can be
DEFINED by turns that can never EVIDENCE it.**

### 2.3 Consecutive client turns: only the LAST is paired
`extract_pairs` breaks the response window on any CLIENT turn:

```
turn 5  CLIENT  "We're on Workday for the ATS."           -> NO PAIR, discarded
turn 6  CLIENT  "Does that integrate with what you said?"  -> paired with turn 7
turn 7  NAREN   "Yes, we have a direct connector…"
```

Setup is lost; the question survives without context. Sibling of Layer D's DEFECT 1, where the
same assumption made **98.6% of `Signal_Recognition_Failure` findings an artifact** (2,449 of
2,484). Fixing it changes what counts as a signal, hence every denominator — **pre-register**.

### 2.4 A teammate's answer is silently discarded
`SpeakerRole.JOVEO_OTHER` does `j += 1`: the window does not close, but the colleague's words
never enter `response_text`. Real Joveo content is invisible to the KB.

### 2.5 The sink short-circuit discards 57.9% of pairs
2,304 of 3,977 (measured 2026-08-16). If a trigger's best match is a sink it is filed there
ALONE and never reaches a rubric. Root cause is upstream: **`v2/layer_a.py` builds the taxonomy
from CLIENT turns only**, so responses never vote, and an expert behaviour whose client cue
looks like filler **has no scenario it could ever be routed to**.

### 2.6 Every assignment rests on ~0.01 cosine
top1−top2 margin: `p10=0.0017 p25=0.0043 p50=0.0103 p75=0.0221 p90=0.0366`. A tiny description
change reshuffles routing wholesale — which is exactly what §1's reroute damage is.

### 2.7 Routing discards cluster membership and re-derives it from a paraphrase
A turn HDBSCAN already clustered gets re-embedded and cosined against Gemma prose. A 16-arm
bench measured membership routing beating description routing **12–1, p=0.003**:

| method | score |
| --- | --- |
| control (true membership) | 55.3 |
| `blend_a0.75` (membership centroids) | **61.2** |
| **`description` — WHAT SHIPS** | **31.6** |
| random placebo | 3.3 |

**THAT RANKING IS WITHDRAWN — do not cite it as a reason to switch.** The metric was the
centroid arms' own objective function; re-scored neutrally, `description` went 32% → 97%. A
blind read went the other way: on 40 disagreement turns `description` was **70%** accurate
(P75/R38) vs centroid **30%** (P31/R62, admitting 22 of 24 non-substantive turns), McNemar
28–12, **p=0.017**. For a coaching product the conservative error is correct.

**The one change the evidence positively supports is NOT BUILT:** a `delta` knob —
`accept iff max(coachable) − max(sink) >= delta`. At `delta=0` it IS the shipped rule. The PR
curve shows `delta=-0.0117` buys **+5.1pp recall for −2.6pp precision**, vs switching to
centroid's +4.0pp recall for **−14.0pp**. Ground truth is only 80 judged turns.

### 2.8 The `Indeed` stopword bug is LIVE here
`_is_substantive` counts `is_alpha and not is_stop`, and `'indeed'` IS a spaCy stopword while
`ziprecruiter`, `greenhouse`, `workday`, `linkedin` are NOT. It gates every `kb_pair`. **The
obvious fix is forbidden** — a curated domain whitelist is this repo's "a threshold must never
be a curated list" anti-pattern. It needs a different substantive test.

### 2.9 Two substantive filters, no shared knob
`v1/layer_b._MIN_CONTENT_WORDS = 5` (module constant, LIVE) vs
`shared/cluster_evidence.is_substantive` (reads `tuning.yaml`). **Editing `tuning.yaml` does
not change pair extraction.**

### 2.10 NOT Layer B, but one bad response kills a whole Layer C run
`shared/gemma.py::_call_once` raises `GemmaError` on `json.JSONDecodeError` **immediately — no
retry, no repair, no model escalation** — while every other error class gets retries with
backoff and a model chain. So a single malformed response anywhere in a run is fatal to the
entire pass.

That is not hypothetical: `PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH` on the current default
model sometimes returns a JavaScript object literal with **bare keys** (`id: "x"` not
`"id": "x"`) despite `response_mime_type="application/json"`.

**MEASURED FREQUENCY, and it corrects a stronger claim made earlier the same day: it is
INTERMITTENT, not deterministic.** Two of two attempts on one 3-item batch failed; **0 of 35
calls failed on the full 171-milestone run.** So "the describe step is broken on this model" is
WRONG and was withdrawn. The defect is the missing retry, not the model: at 35+ calls per run,
an occasional formatting glitch becomes a run-ending failure with no recovery and no
checkpoint. A retry-on-parse-failure (the same treatment every transient error already gets)
would absorb it.

`calibration/describe_milestones_arms.py::install_tolerant_gemma` works around it **in the
harness only**, deliberately not in production, and reports how many responses it repaired so
the real rate stays visible.

---

## 3. Settled — do NOT re-litigate

- **Sink-rescue is CLOSED.** Eight signal families all failed. `sink_rescue_strategy` stays
  `none`. A ninth per-pair signal is not the next step — the *unit of decision* was the problem.
- **Two-stage (primary_topic-first) matching REJECTED** — recall fell at full corpus
  (83.6%→77.0% soft, 82.1%→71.4% fallback). `matching_strategy` stays `flat`.
- **`relative_margin: 0.95` is calibrated** against bge's band (p10=0.496 p50=0.550 p90=0.613).
- **`scenario_vector_mode` ships `concat`.** Keyphrases-alone scored 42.1 vs concat's 31.6, but
  n=1, p=0.344, in gemini space only.
- **The noise-rescue does not reach the rubrics** (§1). That question is answered.

---

## 4. What is proven and reusable

- Layer C Pass 1 is **deterministic** with cached embeddings → free, exact A/Bs.
- **Volume perturbation is harmless** → a milestone loss is attributable to routing.
- `calibration/layer_bc_arms.py` measures milestones, `support_calls`, sink share, absorption
  and the top1−top2 margin in one free pass, with a placebo and a floor built in.
- The corpus is clean: 393 transcripts / 20,788 CLIENT turns / 3,977 pairs over 351 calls,
  after removing 13.2% that was not client speech.

---

## 5. Non-negotiable methodology

- **Zero Postgres writes** in any harness.
- **Pre-register the gate before running the arms.** Every result in this repo that survived
  did so because its failure condition was written first.
- **A metric that is any arm's objective function cannot rank arms.** Re-score the same
  populations under a rival's objective to detect it.
- **Volume-matched placebo** for anything that changes pool size, and **match the support
  denominator too** — donors drag in new calls and silently raise `required_milestone_support`.
- **Symmetric filtering.** For every arm, list what was filtered and diff the lists.
- **Read real samples** before believing any aggregate; for a rule that MODIFIES a population,
  the unit of reading is the MODIFICATION.
- **Report the DIRECTION of flips, never a flip rate** — a rate discards direction.
- **`no_cache=True`** on any chat call measuring variance; the gateway caches completions.
- **Never batch the gateway's `/embeddings`** — it silently returns fewer vectors than inputs.
- **Import production code; never paraphrase it.** Scratchpad reimplementations of the parse
  disagreed with production by ~20%, twice.
- **Get any new harness audited by one subagent before running it** — strict bar: only defects
  that change the outcome or waste a paid run. That found a hard blocker and three
  silent-wrong-answer bugs in the last one.
- Everything recent is `gemini-embedding-2@3072` in TURN mode; **production is local bge@768 in
  CLAUSE mode.** No production change may cite gemini numbers alone.

---

## 6. Provocations — none of these is a recommendation

1. If Layer A's unit is a turn and Layer B's is a pair, **should the pair be built from a client
   MOVE (consecutive turns merged) rather than a single turn?** (§2.3)
2. **Should responses vote in the taxonomy at all?** §2.5's root cause is that they don't.
3. **Should routing use membership where it exists and description only for unclustered turns?**
   (§2.7 — contested in both directions.)
4. **Should the sink decision be a threshold at all**, or a separate classifier, or deferred to
   Layer C where four aggregate junk defences already exist?
5. **Build the `delta` knob** and sweep it against a larger judged sample than 80. (§2.7)
6. Should `JOVEO_OTHER` speech enter `response_text` — and what does that do to the "Naren's
   voice" premise every rubric rests on? (§2.4)
7. What replaces `_is_substantive` so it is not inconsistent across domain terms? (§2.8)

---

## 7. Where things live

- `v1/layer_b.py` — `extract_pairs`, `assign_scenarios`, and the unused
  `assign_scenarios_two_stage` / `assign_scenarios_with_sink_rescue` variants
- `shared/relative_match.py` — the top-K rule, extracted so harnesses can apply the real thing
- `shared/scenario_vectors.py` — the one definition of "the scenario vector"
- `v2/layer_c.py` — `build_clause_pool`, `_relevance_filter`, `_cluster_milestones`
- `calibration/layer_bc_arms.py`, `ops/run_layer_bc_arms.py` — the free measurement
- `calibration/describe_milestones_arms.py` — the LLM describe step, offline, no DB
- `CLAUDE.md` "Brain/" section — read the calibration gotchas and measurement lessons
