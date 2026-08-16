# HANDOFF — Layer C, and finding what nobody has looked for (2026-08-17)

Continue-from-here after the Layer B redesign trial closed as a **null**. Read this, then
`CLAUDE.md`'s "Layer B redesign" section, then
`docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md` §10, then
`Brain/PROBLEMS_AND_FIXES.md`'s last section.

**You are working unattended. The person who would answer a question is asleep.** That changes
what you should do, not how carefully you should do it — see §6.

---

## 1. WHERE THINGS STAND, IN ONE PARAGRAPH

Layer B was suspected of losing most of the pipeline's evidence. It is. Five single-variable arms
were run against two taxonomies with pre-registered gates, and **`r1` — routing a trigger by the
cluster label Layer A already gave that exact turn — genuinely repairs the documented
`+62% → +0.8%` break**: +39% clauses, sink share 57.6% → 37.5%, lookup coverage 45.9% → 72.8%.
Then its **permutation placebo** — the same 1,921 pairs with their destinations randomly shuffled
— produced 112 new milestones to `r1`'s 126 and scored *better* on the primary metric.
**Layer C responds to routing VOLUME, not routing QUALITY.** F10, the pre-registered honest null,
fired. Layer B is not the binding constraint.

---

## 2. WHAT IS ESTABLISHED — do NOT re-derive any of this

Every line is measured. Challenge it if you have evidence; do not spend a run reproducing it.

- **Layer C's relevance filter cannot reject anything.** `milestone_relevance_percentile: 40` is
  a PERCENTILE, so it survives **exactly 60.0%** of whatever it is handed — identical across
  three arms with very different pools. `CLAUDE.md` calls it one of "four aggregate junk
  defences"; against mis-routed content it does nothing.
- **The separation signal is real but in the wrong FRAME.** `probe_relevance_signal.py` over
  13,218 clauses × 3 random draws: own scenario **0.6071**, random **0.5825**. Pooled AUC
  **0.631** (this repo retired a signal at 0.617). But held **per clause, 78.2% prefer their own
  scenario.** Between-clause variation in cosine magnitude is ~6× the own-vs-random gap, and
  Layer C's filter ranks clauses *against each other* — the frame where it drowns.
  `shared/relative_match.py` already does the per-clause shape at Layer B. **Layer C has none.**
- **Layer C discards 45–48% of post-relevance clauses** to HDBSCAN noise + the support gate,
  stable across arms. Layer A's noise rate is ~47% and its diagnostic found the noise pool is
  CLEANER than the kept pool (22% content-free vs 42%). Layer C's noise has never been examined.
- **Layer C's output is not a stable function of its input.** +39% evidence produced a milestone
  set where 126 of 158 were new. The placebo reproduced that at 112 of 143 — so the instability
  is a property of perturbing the pool at all.
- **`support_calls` DOES NOT PREDICT COHERENCE.** Three blind readers (91–99% agreement) rejected
  **10/10** deliberately scrambled items but accepted only **5/10** of the HIGHEST-support
  milestones. **Roughly half of every milestone set is judged incoherent** — placebo 33%, `r1`
  50%, control 50%.
- **Both Layer B admission knobs are redundant with a later stage.** `a4` admits short Naren
  replies the segmenter (`len(sent) < 4`) discards anyway — 0.72 clauses per new pair — while
  dragging in 150 calls that raise `required_milestone_support` in 12 of 25 scenarios. `a1`
  admits short triggers the sink rule rejects anyway (sink share rises to 69%).
- **Layer C Pass 1 is deterministic across processes** with cached embeddings. The floor pair
  gave identical clause sets AND identical `support_call_files`. Any arm difference is signal.
- The corpus is clean: 393 transcripts, 20,788 CLIENT turns, 3,977 pairs, 351 calls, 111 client
  accounts after sibling-domain collapse.

---

## 3. OPEN AND KNOWN — start here, but do not stop here

Ranked by my estimate of value. **You are expected to disagree with this ranking if the evidence
supports it.**

1. **A per-clause RELATIVE relevance test in Layer C.** Use the frame where the 78.2% signal
   lives instead of the pooled frame where it is 0.631. This is the cheapest live idea in the
   pipeline and the harness to test it already exists.
2. **Is Layer C's UNIT wrong the way Layer A's was?** It clusters response SENTENCES.
   `2026-08-14-layer-a-pool-unit-design.md` found sentence-level units manufacture junk clusters
   because a stripped sentence carries stance without subject. Nobody has checked Layer C for the
   same thing. Note the segmenter is SHARED, so changing it in production would move Layer A too
   — shim it in the harness.
3. **Layer C noise-rescue.** `rescue_centroid` is already validated at Layer A (+8/−0 scenarios,
   p=0.008, three seeds, blinded 10/10, placebo collapsed to 3/38) and ports directly: admit a
   noise clause into its nearest surviving milestone iff `cos ≥ p25({cos(member, centroid)})`.
   No new tuning constant. **The one mechanism that could raise a milestone's `support_calls`,
   and therefore its account count** — the metric that never moved all night.
4. **A call whose response contributes ZERO clauses still inflates `scenario_calls`**, which
   raises `required_milestone_support` for every milestone in that scenario. It cannot support
   anything yet raises the bar. Live in `v2/layer_c`, never measured before this trial.
5. **`S2` — teammate speech.** 5,287 turns, **25.4% of the corpus**, discarded at
   `v1/layer_b.py:57` (`j += 1`, no text captured). The largest single measured lever in the
   pipeline. It is NOT a measurement question — it changes what a rubric IS, and `ego_trap/`
   has already taken the opposite position by writing `Deferred_To_Teammate` rather than scoring
   those turns. Needs its own brainstorm and pre-registration, not an arm.
6. Smaller, all recorded in `PROBLEMS_AND_FIXES.md`: the noise floor cannot be PROVEN from
   artifacts (no `started_at`/`pid` in `run_arm`); `r1_lookup_share` overstates the treatment and
   `router_agreement.py` computes the honest number but has never been run; `a3`'s volume-neutral
   targeting is miscalibrated (4,872 pairs vs production's 3,977).

**DO NOT run more Layer B permutations.** `r2_r`, `r3`, `s1` and `a3` would each cost a run to
produce another null against a mechanism that is now understood.

---

## 4. WHAT I WANT FROM YOU THAT I HAVEN'T LISTED

**Find issues nobody has looked for.** The list above is what one night surfaced; it is not a
survey. Every item on it was found by measuring something, not by reasoning about it. Two of the
best findings came from a user asking "what if your test is wrong" — so audit the *instruments*,
not only the pipeline.

Places nobody has looked, offered as starting points and not as a list to work through:

- **Layer C's four "aggregate junk defences" are cited constantly and only one has been
  measured.** I measured the relevance filter and it turned out to reject nothing. Check the
  other three.
- **`_cluster_milestones`' UMAP/HDBSCAN parameters have never been calibrated** the way Layer A's
  were. `min_cluster_size` comes from `cluster_evidence.milestone_min_cluster_size`; nothing has
  swept it.
- **The support gate** `required = max(floor, ceil(fraction × scenario_calls))` has a floor of 3
  and a fraction of 0.10, both chosen in 2026-07-28 against a taxonomy that no longer exists.
- **Nobody has read Layer C's discarded 45%.** Layer A's equivalent diagnostic found the noise
  cleaner than the kept pool, which reversed an assumption.
- **`rubrics.anti_patterns` has never been read by anything.** CLAUDE.md records this.

**THE LITERATURE IS AVAILABLE, NOT MANDATORY.** `WebSearch`/`WebFetch` are there if you want
them. This repo has repeatedly reinvented things that have names and known failure modes —
inverse-Simpson diversity, size-matched Monte-Carlo nulls, Gumbel top-k sampling, HDBSCAN soft
membership — so ten minutes finding out whether something is a solved problem, and what its known
pathologies are, is often the cheapest move available. When you use it, cite what you found in
the code comment, and say plainly where it disagrees with what this repo already does.

**But your own fix is equally welcome, and often better.** The best results in this codebase were
not from the literature: `rescue_centroid`'s per-cluster p25 rule, the permutation placebo, the
"is this ONE coherent move" blind-read question, and the observation that a percentile filter
cannot reject anything were all worked out from the data in front of them. **Do not go looking
for a citation to justify an idea you can simply measure.** Search when you are unsure whether a
wheel exists; build when you can test it faster than you can read about it.

---

## 5. NON-NEGOTIABLE METHODOLOGY

This repo's entire history is plausible ideas failing controlled tests. The ones that survived
did so because the test was built first.

- **Pre-register the gate BEFORE running anything.** Write it in a spec, commit it, then run.
- **A metric that is any arm's objective function cannot rank arms.** Re-score the same
  populations under a rival's objective to detect it.
- **A placebo must match what the arm ADDS, not a proxy for it — and the arm type decides the
  shape.** An ADMISSION arm adds clauses: match count, length and embedding character. A ROUTING
  arm adds nothing: use a PERMUTATION (keep which items moved and the destination multiset,
  shuffle which goes where). The first `a4` placebo matched total clause count and added **6.9×
  the text mass**. Assert the invariants in code — a silently wrong placebo looks exactly like a
  valid result.
- **The metric has already been wrong three times** (a distinct-account count the published
  RTX-98% case passed; `N_eff`, bounded by `k`; a thresholded lift whose pass rate was
  k-dependent enough that subsampling 40% of calls won at p=4.8e-13). **Read §4 of the spec
  before proposing a fourth.**
- **Read real samples before believing any aggregate**, and for a rule that MODIFIES a
  population, the unit of reading is the MODIFICATION.
- **Report the DIRECTION of flips, never a flip rate.**
- **Symmetric filtering.** For every arm, list what was filtered and diff the lists.
- **Import production code; never paraphrase it** — unless you pay for the paraphrase with an
  equivalence proof, as `layer_b_variants.verify_equivalence()` does (byte-identical over all 393
  transcripts at the control setting).
- **Audit every new calibration file with ONE subagent before running it.** Strict bar: only
  defects that change the outcome, produce a silently wrong number, or waste a run. A clean
  report is a valid result. Where a file has mixed authorship, audit it BLIND — do not tell the
  auditor who wrote what.
- **Blind reads work and are cheap.** `blind_read_powered.py` builds them with positive and
  negative controls; three subagent readers agreed 91–99% and rejected 10/10 scrambled items.
  **Always include the controls** — three judges in this repo have failed their own nulls.
  Watch the cost: 3 readers × 80 items ≈ 430k tokens.

---

## 6. WORKING UNATTENDED — what you may and may not do

**May, freely:**
- create and edit anything under `Brain/calibration/`, `Brain/tests/`, `Brain/ops/`, `docs/`
- run any harness that is cache-only and writes no DB
- commit as you go, with messages that explain WHY
- spawn subagents for audits and blind reads

**May, with care:**
- spend on the gateway. Scope it first with `backfill_knob_embeddings.py --scope`; 13,075
  embeddings were spent in total on the last trial and that was considered cheap. **Do not exceed
  ~25k new embeddings without leaving it for the morning.**
- change production — but ONLY behind a `tuning.yaml` flag defaulting to today's behaviour, with
  tests, verified byte-identical when off, and never without a measurement backing it. This
  repo's doctrine is that everything ships OFF.

**Must not:**
- write to Postgres. Ever.
- run more Layer B permutations (§3).
- change `preprocessing/segmenter.py` in production — it is shared with Layer A and would
  silently rewrite that pool. Shim it in the harness.
- delete or overwrite a published artifact. `--arm` names its own file for this reason.
- report a result whose gate was written after the number was seen.

---

## 7. THE ASK

**Work on the 1–5 fixes you judge best. You decide the number, and you decide which.** Fewer,
properly measured, beats more, asserted. If one fix turns out to be worth the whole session, do
that one.

For each, I want to see: the pre-registered gate, the placebo (and why that shape), the audit,
the result including the direction and the p-value, and the honest statement of what it does NOT
show. A null that closes a question is worth as much as a positive — five of them closed the
Layer B question last night.

Update `CLAUDE.md`, the relevant spec, and `PROBLEMS_AND_FIXES.md` as you go, not at the end.

**And leave a handoff of your own.** Say what you found that this document did not anticipate.

---

## 8. WHERE THINGS LIVE

| | |
| --- | --- |
| `calibration/layer_bc_arms.py` | the runner. `--segment/--admit/--router`, one permutation per process |
| `calibration/layer_b_variants.py` | S/A knobs + `verify_equivalence()` |
| `calibration/layer_b_routers.py` | R1/R2/R3 and the `r1p/r2p/r3p` permutation placebos |
| `calibration/layer_b_arms.py` | the metric (rev 4: cluster lift, no threshold) |
| `calibration/score_layer_b_arms.py` | scores any arm from artifacts, free |
| `calibration/build_null_weights.py` | the null's draw weights, built once from production |
| `calibration/probe_relevance_signal.py` | the own-vs-random clause probe |
| `calibration/blind_read_powered.py` | blind reads with built-in controls |
| `calibration/router_agreement.py` | Layer-B-only router diff. **Written, never run** |
| `ops/run_visible.ps1` | runs a script in a real window that stays open |
| `artifacts/layer_bc_*.json` | every arm from last night, with `support_call_files` |

**245 tests across four suites.** Run them file-by-file if the whole suite OOMs — that is a
documented spaCy allocation problem on this box, not a real failure.
