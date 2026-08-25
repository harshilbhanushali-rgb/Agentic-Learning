# Layer B — Redesign: Five Arms, All Null (2026-08-16/17)

[Findings index](INDEX.md)

### Layer B redesign: five arms, all null, and the constraint is downstream (2026-08-16/17)

Spec `docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md` (pre-registered; revised
twice BEFORE any arm ran, both revisions recorded in it). Harnesses
`calibration/layer_b_variants.py` (S/A knobs), `layer_b_routers.py` (R1/R2/R3 + permutation
placebos), `layer_b_arms.py` (the metric), `layer_bc_arms.py` (runner),
`build_null_weights.py`, `score_layer_b_arms.py`, `probe_relevance_signal.py`,
`blind_read_powered.py`, `backfill_knob_embeddings.py`, `router_agreement.py`.
**245 tests. Zero production changes, zero Postgres writes, zero chat calls, 13,075 embeddings.**

**THE HEADLINE: Layer B is NOT the binding constraint — F10, the pre-registered honest null,
arriving from five independent directions.**

| arm | what it actually did | lift vs control | verdict |
| --- | --- | --- | --- |
| `a4` drop RESPONSE floor | +419 pairs but only **+302 clauses** | p=0.383 | redundant with the segmenter |
| `a1` drop TRIGGER floor | sink share **57.9% -> 69.0%**, milestones 171 = control exactly | p=0.152 | redundant with the sink rule |
| `r1` membership, base | **+27.5% clauses**, sink 57.9 -> 45.4% | p=0.152 | null |
| `r1` membership, rescued | **+39% clauses, +35 milestones**, lookup 72.8% | p=0.108 | **rejected at F4** |
| `r2` centroid, base | sink share **halved** to 28.6%, support med 7 -> 10 | **p=0.043** | worse |

- **`r1` REPAIRS the documented `+62% -> +0.8%` break.** Reading Layer A's own cluster labels
  instead of cosining a trigger against Gemma prose recovers +39% clauses on the rescued
  taxonomy, and lookup coverage rises 45.9% -> 72.8% precisely BECAUSE the rescue grew cluster
  memberships. The type error is real and this is the fix for it.
- **AND IT DOES NOT MATTER.** The permutation placebo — the SAME 1,921 pairs (48.3% of the
  corpus), the SAME destination multiset, randomly permuted — produced **112 new milestones to
  `r1`'s 126** and scored BETTER on the primary metric (−1.70 vs −2.80). **Layer C responds to
  routing VOLUME, not routing QUALITY.**
- **BOTH ADMISSION KNOBS TURNED OUT REDUNDANT WITH A LATER STAGE, and that is the
  generalisable finding.** `a4` admits short Naren replies that Layer C's `len(sent) < 4`
  segmenter discards anyway — 0.72 clauses per new pair — while dragging in 150 calls that raise
  `required_milestone_support` in 12 of 25 scenarios, so it raises the bar more than it adds
  evidence. `a1` admits short triggers that the sink rule rejects anyway (sink share rises to
  69%, milestone count lands on 171, identical to control). **Before adding or removing a filter
  in Layer B, check whether a later stage already removes that population.**
- **`r2` is worse and the mechanism is understood:** centroids are the mean of member turns,
  member sets are already account-concentrated (RTX 98%, Banfield 100%, Happy Dance 100%), so
  centroid routing pulls in MORE turns from the accounts that already dominate. Description
  routing is account-BLIND, which may be the real reason it survived the earlier 16-arm bench
  despite losing on every membership-shaped metric. **p=0.043 does NOT clear Bonferroni at 5
  arms (0.010) — suggestive, not established.**

**WHY NOTHING REACHED THE RUBRICS — two measurements, both cheap, both new.**

- **`milestone_relevance_percentile: 40` IS A PERCENTILE, so it survives EXACTLY 60.0% of
  whatever it is handed.** Measured identically across three arms with very different pools
  (7,929/13,218 · 11,826/19,707 · 11,577/19,296). It cannot reject mis-routed content in
  absolute terms, and this file previously described it as one of Layer C's "four aggregate junk
  defences". Against mis-routing it does nothing at all.
- **`calibration/probe_relevance_signal.py`, 13,218 clauses x 3 random draws each: own scenario
  0.6071, random scenario 0.5825.** A +0.0245 gap against a between-clause spread of ~0.14, so
  pooled **AUC is 0.631** — barely above the 0.617 this repo has already retired as unusable.
- **BUT THE SIGNAL IS NOT ABSENT, IT IS IN THE WRONG FRAME. Held PER CLAUSE, 78.2% prefer their
  own scenario to a random one.** Between-clause variation in overall cosine magnitude is ~6x
  the own-vs-random difference, so pooling drowns it — and Layer C's filter ranks a scenario's
  clauses AGAINST EACH OTHER, which is the pooled frame. `shared/relative_match.py` already does
  the per-clause shape at Layer B; **Layer C has no equivalent.** Cheapest live idea in the
  pipeline.

**THE BLIND READ IS THE FIRST JUDGE IN THIS EFFORT TO PASS ITS OWN NULL — and it produced a
finding bigger than the arm it was judging.** Three independent subagent readers, 80 items,
authorship undisclosed, samples and answer key in SEPARATE files, judgments committed first.

- **NEGATIVE control 10/10 rejected by all three readers.** Those items were real Naren clauses
  from unrelated milestones glued together — only COHERENCE was destroyed, so fluency, register
  and vocabulary could not be the tell. Inter-rater agreement 91–99%, unanimous on 73/80. For
  comparison, the applicability judge managed 1.22:1 and the coverage judge 64.9% vs 65.7%.
- **POSITIVE control FAILED at 5/10 — and that IS the finding. `support_calls` DOES NOT PREDICT
  COHERENCE.** The positive set was the HIGHEST-support milestones the pipeline produces; half
  do not hold together as a move. Reading confirms it — the two largest clusters in the pilot
  (67 and 37 calls) were both rejected as generic affirmation ("we can certainly help with
  that", "I'll send you the collateral").
- **Roughly HALF of every milestone set is judged incoherent**: placebo 33%, `r1` 50%,
  best-supported control 50%. Independent of routing, of arm, and of how the `r1` question
  resolves.
- `r1`-gained vs placebo-gained: **50% vs 33%, same direction in all three readers, p~0.30.**
  Underpowered. A 268-item powered read was built and deliberately NOT bought (~1.2M subagent
  tokens); one reader over the full set would cost a third of that if it is ever wanted.

**THE TWO INSTRUMENTS DISAGREE BECAUSE THEY MEASURE DIFFERENT AXES.** Account-diversity lift
asks "is this evidence spread across CLIENTS"; the blind read asks "is this ONE COHERENT MOVE".
`r1` moves the second and not the first, which is consistent — nothing in `r1` looks at
accounts, which is exactly why that metric was chosen (ungameable) and exactly why no arm could
move it. **Do NOT retroactively promote coherence to the primary metric because it favours
`r1`.** The pre-registered metric says `r1` fails; switching axes after seeing the result is how
a threshold gets tuned into a finding. Resolve it with power or leave it open.

**THE METRIC WAS WRONG THREE TIMES, each caught before it decided anything. Read this before
proposing a fourth.**

| rev | statistic | killed by |
| --- | --- | --- |
| 1 | `>= 3 distinct accounts` | the published RTX-98% case has FOUR distinct accounts and PASSED. Also saturated — 91% of `base_1` AND 91% of the junk placebo cleared it |
| 2 | `N_eff` (inverse Simpson) | `N_eff <= k`, so an arm routing more calls into each milestone raises the ceiling MECHANICALLY |
| 3 | `N_eff` / size-matched null, THRESHOLDED | `P(lift >= bar)` is violently k-dependent (100% at k=1, 96% at k=2, 39% at k=8, 46% at k=60), so a treatment that merely SUBSAMPLES 40% of each milestone's calls — content held constant — "won" at **p=4.8e-13** |
| **4** | **cluster-level lift, NO THRESHOLD** | resists that attack 0–2/20 where rev 3 won 13–16/20 |

Rev 4 needed a **composition-matched** null as well: the draw is weighted by pairs-per-call from
PRODUCTION's own extraction (`artifacts/null_draw_weights.json`; **42 calls contribute zero
pairs** and can never back a milestone, yet a uniform null treats them as equally drawable).
Uniform vs weighted moved a residual drift from p=2.2e-4 to **p=0.858**.

**A PLACEBO MUST MATCH WHAT THE ARM ADDS, NOT A PROXY FOR IT — AND THE TWO ARM TYPES NEED
DIFFERENT PLACEBOS.** The first `a4` placebo padded with donor PAIRS until total clause count
matched, and ended up adding **2x the clauses at 3.4x the length = 6.9x the text mass** it
claimed to match. An ADMISSION arm adds clauses, so its placebo must match count, length and
embedding character. A ROUTING arm adds NOTHING — the same pairs exist either way — so its
placebo is a PERMUTATION: keep which pairs moved and the destination multiset, shuffle which
pair gets which. `layer_b_routers.py` implements `r1p`/`r2p`/`r3p` with the invariants ASSERTED
in code rather than checked afterwards, because a silently-wrong placebo looks exactly like a
valid result.

**Reusable, and free:**

- `layer_b_variants.py` is the ONE place this trial paraphrases production, and it is paid for
  by `verify_equivalence()` — **byte-identical pairs, field for field, over all 393 transcripts**
  at the control setting `(s0, a0)`. A paraphrase proven equal at the control is not a
  paraphrase risk; an unproven one is.
- **Layer C Pass 1 is deterministic across processes**: the floor pair produced identical clause
  sets AND identical `support_call_files`, 0 up / 0 down / 26 ties. Any arm difference is signal.
  (An audit correctly noted the artifacts carry no `started_at`/`pid`, so the floor cannot be
  PROVEN to be two runs from the files alone — worth adding.)
- `support_call_files` is now persisted per milestone (WHICH calls, not just how many); account
  breadth is not derivable from any artifact written before this trial.
- `score_layer_b_arms.py` and `probe_relevance_signal.py` re-report from artifacts at zero cost,
  which is why three metric revisions cost no re-runs.

**NEXT STEP IS NOT MORE PERMUTATIONS.** `r2_r`, `r3`, `s1` and `a3` would each cost a run to
produce another null against a mechanism that is now understood. The live directions are
(1) a per-clause RELATIVE relevance test in Layer C, operating in the frame where the 78.2%
signal actually lives, and (2) whether Layer C's UNIT is wrong the way Layer A's was — it
clusters response SENTENCES, and the pool-unit work found sentence-level units manufacture junk
clusters because a stripped sentence carries stance without subject. Both are testable with the
harness that already exists, and both are downstream of everything Layer B can do.

