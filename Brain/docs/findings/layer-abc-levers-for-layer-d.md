# Layers A, B, C, and what each can do for Layer D's two methods (2026-09-07, zero spend)

[Back to the index](INDEX.md)

**Operator question.** Layer D now has two coaching methods: the **pairwise** method (which
reply better performs a DO-type move, CSM vs Naren's exemplar -- the method built first, which the
operator wants to work) and the **repertoire** method (ever/never and, on high-volume scenarios,
how-often -- `layer-d-say-arm.md` §11/§13). Half of Naren's data goes to the sink in Layer B; a
stronger LLM is available for Layer A now; Layer C was just measured (§14). For each layer: is
there a lever, for which method, how big, and what else should be considered?

**Method.** Every number below is either a fresh zero-spend measurement over the stored data
(this doc names the query) or a citation of a measured finding in this directory. Nothing was
re-derived that the index already answers; where an idea has been tried and refuted, it is
listed as such rather than re-proposed.

## 0. The funnel, both sides, in one table

| stage | Naren (Layer B, kb_pairs) | Madhumita (Layer D, run 137706da74c6) |
| --- | --- | --- |
| client turns | 58,002 union-corpus turns / 1,059 calls (taxonomy substrate) | 5,731 client turns in 100 transcripts; 3,784 substantive; **3,282 client blocks** after segmentation |
| routed to a coachable scenario | **6,528 of 12,444 pairs (52.5%)**; 5,916 (47.5%) to the 225 sink scenarios | **1,205 moments (36.7% of blocks)** route to a coachable scenario with a live playbook |
| gradeable | benchmark: 11-28 calls per scenario sampled (median 17) of a median 212 available | 601 (49.9%) she answered; 395 (32.8%) a colleague answered; 206 (17.1%) fragments; 3 silence |
| decided (pairwise) | -- | 645 decided verdicts across 110 cells; **median 3 per cell** |

So "half the data goes away in Layer B" is true on Naren's side (47.5%) and truer on hers (63%
of client blocks never become a coachable moment), and then her side halves again because a
colleague answered or she only interjected. **18% of her client-side content reaches a grader.**
Which of those losses is recoverable is the question below, layer by layer.

## 1. Layer B (routing): the sink is mostly not coachable content, and the knobs were null

**What was measured before.** Five Layer B redesign arms (admission knobs and routers) were null
(`layer-b-redesign.md`: "Layer B is not the binding constraint"); 16 Layer A routing arms
including a cross-encoder did not beat the exemplar centroid (`layer-a-routing.md`); three
sink-rescue strategies were rejected and the rescue was closed a fourth time on the playbook
yardstick (`union-taxonomy-rebuild.md`); `keyphrases` routing starves the map (sink 47.5% ->
60.9%). **47.3% of the sink pool is HDBSCAN noise** -- turns no cluster claims -- which caps any
cluster-based fix at about half the sink (`layer-a-sink-pool-rescue.md`).

**What the sink actually holds.** The three largest sink scenarios are
`affirmative_acknowledgment` (291 pairs), `document_and_artifact_exchange` (259) and
`joveo_brand_references_and_administrative_pause` (252): acknowledgements, "I'll send the
deck", scheduling. Sink is where chatter goes. The recoverable part -- substantive turns about
topics no coachable scenario covers -- is the part the rescue arms kept promoting and the blinded
coherence readers kept rejecting (8/12 vs 10/12 on the same corpus).

**The one endorsed knob.** `layer_b.sink_margin_delta` exists at 0.0; the evidence supports
about +5 points recall for -2.6 points precision at -0.0117 (`layer-b-routing-playbook-ab.md`).
For Layer D that is roughly +165 of her 3,282 blocks becoming moments, spread over 32 scenarios:
about +5 moments per scenario, or half a call's worth. It needs a judged sample of >80 turns
before it can be set. **Real, small, and not where the power is.**

**Verdict for Layer B: no for both methods.** The 47.5% is not coachable content waiting to be
routed; it is the corpus's conversational filler plus a residue that four attempts could not
route coherently. The 63% on her side has the same composition (her transcripts have the same
"sounds good" density as his). The only Layer B lever the evidence endorses is worth about half
a call per scenario.

## 2. Layer A (taxonomy): a stronger LLM helps the part that is prose, not the part that is geometry

**How Layer A is built.** Turns are embedded (gemini-embedding-2 @ 3072), clustered
(UMAP + HDBSCAN on the 58k-turn union corpus, 600 raw -> 511 merged at 0.97 -> 307 clusters),
then each cluster is **adjudicated by an LLM**: named, described, keyphrased, and marked
coachable or sink. The adjudicator is `shared/gemma.py`'s default, **`gemini-3.5-flash-lite`**
(fallback `gemini-3.1-flash-lite`, `gemma-4-31b-it`). Routing (Layer B) then uses the
description + keyphrases vector as the scenario's centroid.

**Where a better LLM can act.** Only in the adjudication step. The cluster boundaries are set by
the embedding geometry and HDBSCAN; no LLM sees them being drawn. So a stronger model changes
(a) which clusters are called coachable, (b) how sharply each is described (which IS the
routing vector), and (c) whether an umbrella cluster gets recognised as one. It cannot merge or
split what the clustering produced -- unless it is given that job explicitly as a second pass.

**Why this is plausible rather than hopeful.** Layer C's own 4-arm A/B found **the model was the
lever, not the prompt**: flash-lite ignored the account-diversity instruction (11%), 3.6-flash
followed it (77%) (`layer-c-playbook-schema-and-gateway.md` §10b). Layer A's adjudication has
never been re-run with the stronger model; the live map's descriptions are flash-lite prose.

**Where Layer D actually hurts from Layer A today: catch-all scenarios.** `application_volume_and_prioritization`
carries 771 of 6,528 coachable Naren pairs (11.8%), 590 of his calls, and 246 of her 1,205
moments (20%). The G-R4b read (`layer-d-say-arm.md` §13b) found **16% of her moments there are
about jobs, not applications** (feed refreshes, promote buttons, job budgets) and 10% are
non-replies. 13 of 34 scenarios carry 80% of her moments. Umbrella scenarios pollute BOTH
methods' denominators: the repertoire rates and the pairwise attempts alike.

**The concrete Layer A experiment (offline, no ship, ~300-350 requests):**
1. Re-adjudicate the 307 `union_base` clusters with `gemini-3.6-flash` at `reasoning_effort=medium`
   (the licensed Layer C config), same prompt, same artifact format -> `adjudication_36flash.json`.
2. Compare to the live map: coachable set (34 today), and description quality on the frozen
   G-R4 blinded-coherence read (12 sampled scenarios, bar >= 9/12; the base arm scored 10/12).
3. Add ONE new step the stronger model is good for: on the three largest coachable clusters
   (application volume, campaign tracking, job-board budget) ask it to propose a split into
   2-4 sub-scenarios with member turns; run the SAME coherence read on the proposals.
4. Decide only then. **Any taxonomy change is a REPLACEMENT** (`docs/GOTCHAS.md`): it deletes the
   33 playbooks, the routing map, every `move_events` row and both Layer D runs. That is
   ~1,000 grading requests and two blind audits to rebuild, plus Layer C regeneration. The
   experiment is cheap; acting on it is not, so the gate must be worth it: the split must
   remove most of the 16% misrouting AND the sub-scenarios must each keep >= 30 of her calls,
   or the power lost to fragmentation exceeds the noise removed.

**Verdict for Layer A: yes, worth one offline experiment, for both methods -- mainly through the
catch-all scenarios.** Expected effect on the repertoire method: cleaner denominators on the
3 scenarios where "how often" is even eligible (the one flagged rarely cell died on exactly this
noise). On the pairwise method: fewer exemplars that answer a different question (the
read-through's named defect). Neither is a power gain; both are a precision gain. The power
gains are elsewhere (§4).

## 3. Layer C (playbooks): measured in `layer-d-say-arm.md` §14; summary and one addition

- Bundled criteria are credited MORE often (rho +0.35, p=0.001): **do not split moves**; the
  §12 "one statable thing" rule is withdrawn.
- Evidence from >= 3 distinct calls predicts a move Naren actually uses (rho +0.35): a small
  next-generation rule. It removes never-decidable cells; it adds no power.
- Criterion wording does not predict pairwise ties (five blind nulls, `layer-d-redesign.md`).
- **Addition, for the pairwise method:** only **34 of 121 moves are DO/MIXED-routed** (32 cells
  have data). The pairwise method's ceiling is set by how many DO-type moves the playbooks
  contain, and that is a Layer C property. A next-generation prompt that asks for "what Naren
  DOES" moves (walk-throughs, artefacts produced, actions taken) alongside "what he SAYS" would
  widen the pairwise method's territory. Untested; cheap to probe on 3 scenarios; carries the
  same replacement cost as any live playbook change, so next generation only.

**Verdict for Layer C: no for the repertoire method; a possible next-generation lever for the
pairwise method (more DO moves), untested.**

## 4. Layer D itself: where the power actually is, for each method

### 4.1 The pairwise method ("I want this to work") -- what limits it, measured

| fact | value |
| --- | --- |
| DO/MIXED-routed cells with data | 32 (of 110 pairwise cells graded) |
| of those with >= 8 attempts (rankable) | 21 |
| tie share on DO/MIXED cells | **59.6%** (70.1% across all 110 cells) |
| cells with >= 10 decided verdicts | **10** |
| median decided verdicts per cell, all cells | **3** |

A ranking built on three decided verdicts per cell is noise, and shrinkage only hides that.
The method's two problems are (a) most comparisons tie and (b) there are too few of them.

**Lever P1 -- tie decomposition (a regrade of DO cells only, ~150-200 requests).** Today a tie
means either "both performed the move comparably" or "neither performed it". At Naren's measured
15% call-level deployment, most ties are the second kind, and those are uninformative: a moment
where neither rep did the move says nothing about who does it better. Ask the judge a 4-way
question -- A better / B better / both comparably / neither -- and report the win share among
moments where at least one did it. Gate: a blind read of 40 verdicts at >= 70% 4-way agreement,
plus the "neither" share published before any ranking is read. If "neither" is 30-40% of ties,
the decided denominator roughly doubles without a single new call. This is the one change to
the pairwise instrument the evidence points at, and it has never been tried.

**Lever P2 -- multi-exemplar (same regrade).** The read-through's named defect: top-cosine picks
an exemplar that answers a different question, and she "loses" to it. Show the judge Naren's
top-3 exemplars and let it pick the most comparable before judging. Untested; folds into the
same regrade as P1; gate is the same blind read.

**Lever P3 -- her call volume, again.** Decided verdicts scale with attempts. To put 20 decided
verdicts behind each of the 21 rankable cells at the current 40% decided rate needs ~50
attempts per cell: about 2.5x her current calls, or P1 plus 1.3x.

**Not levers:** a stronger judge (the say arm's 89.6% audit agreement says the judge is not the
bottleneck; ties are structural), prompt wording (refuted six times), the order swap (95%
order-agreement measured), lowering the ranking floor.

### 4.2 The repertoire method -- restated from §14

- Ever/never: her call volume (19 of 61 cells decidable; 27 at 2x). No Layer A/B/C lever.
- How often: Naren's benchmark size (11-28 calls used vs 212 available per scenario; enlarging
  to 50 on the three high-volume scenarios doubles detectable gaps, ~100-150 requests).
- Both: catch-all precision (§2).

## 5. Factors outside A/B/C that move more than any of them

1. **Who else is on the call.** 32.8% of her moments were answered by a colleague; 22 of 84
   calls had half or more deferred. Ingesting calls where she is the only Joveo voice roughly
   doubles graded moments per call. This is a data-selection choice, free, and larger than every
   routing lever combined (`layer-d-deferral-rate.md`).
2. **Naren's benchmark size** (§4.2) -- the cheapest purchase of power in the system.
3. **A second CSM.** Pairwise shrinkage pools across the cohort; today the "cohort" is one
   person, so the prior is her own mean. Repertoire rates need no cohort but the report becomes
   comparative only with two.
4. **Transcript quality.** 6 of 106 transcripts are excluded by the fail-closed speaker gate
   ("Unknown Speaker"). Fixing the Avoma roster for those recovers 6% of calls at zero model
   spend.
5. **Segmentation density.** She gets 2.1 scored moments per call on application volume against
   Naren's 2.7 (the report prints this). Not a knob to turn -- it is calibrated -- but a reason
   the opportunity-parity check exists, and a reminder that her denominators are systematically
   a little thinner.

## 6. The answer, in one table

| layer | pairwise method | repertoire method | what to do |
| --- | --- | --- | --- |
| A (taxonomy) | **precision, yes** -- fewer wrong-question exemplars | **precision, yes** -- cleaner denominators on catch-alls | one offline re-adjudication with 3.6-flash + a split proposal on the 3 largest scenarios; measure on the frozen coherence read before deciding about a (costly) replacement |
| B (routing) | no | no | leave; the sink is filler plus a residue four attempts could not route; `sink_margin_delta` is worth half a call per scenario |
| C (playbooks) | **maybe, next generation** -- more DO moves | no (do not split moves; evidence-diversity rule is small) | probe a "what he DOES" prompt on 3 scenarios, next generation only |
| D (instrument) | **yes** -- tie decomposition + multi-exemplar regrade of 32 DO cells (~150-200 requests, gated by a blind read) | **yes** -- enlarge Naren's benchmark on 3 scenarios (~100-150 requests) | pre-register both; run the cheap one first |
| data | **yes** -- solo-CSM calls, 2.5x volume | **yes** -- her volume decides 19 -> 27 -> 37 cells | prefer calls where she is the only Joveo speaker; fix 6 rosters; second CSM |

**Order of operations if all of it is approved:** (1) Naren benchmark enlargement (cheap, helps
repertoire now); (2) pairwise tie-decomposition regrade (cheap, the only untested instrument
change for the method the operator wants to work); (3) the Layer A offline re-adjudication
(cheap to run, expensive to act on -- so run it to learn, decide separately); (4) data: solo
calls, rosters, second CSM (free, slow, largest). Nothing in Layer B.
