# Layer A — Pool Unit: Clause vs Turn, Part 1 — the Null-Test Finding (2026-08-14/15)

[Findings index](INDEX.md) · continued in [layer-a-pool-unit-2.md](layer-a-pool-unit-2.md)

### Layer A pool unit: the taxonomy was built from sentence fragments (2026-08-14/15)

Spec: `docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md` (Status updates 1-7 and a
**CONCERNS REGISTER** with every concern's verbatim wording and its resolution status). Harnesses
`calibration/trial_pool_unit.py`, `calibration/spot_check_adjudication.py`,
`calibration/scenario_coherence.py`. **Shipped OFF: `layer_a.pool_unit: clause`, production
byte-identical.** ~8 Gemma calls spent in total, zero DB writes.

**The finding that started it: two thirds of the live taxonomy is statistically indistinguishable
from a random pile of client turns.** Against a size-matched random null (which had never been
taken), scenarios score 0.740 vs the null's 0.706 -- a +0.033 lift, below the harness's own 0.05
bar. **Only 21 of 68 rankable scenarios beat their own null, and 20 of those 21 are
subject-matter -- exactly 1 of 24 posture (`client_*`) scenarios clears it.** Independently
reproduces, for free, the population split the paid ceiling run found.

> **TWO CORRECTIONS (2026-08-15), neither of which overturns the headline.**
>
> **(1) The 31% is NOT the fair baseline; 20% is.** That figure was measured in bge on
> clause-formed scenarios scored with *turn* vectors -- cross-embedder AND cross-unit, the
> double-count this spec's own symmetry rule forbids. `calibration/null_test_taxonomy.py`
> re-measures both taxonomies through one embedder, one pool, one assignment rule and one
> null: **production 16/82 = 20%**, turn mode 11/38 = 29%. Note the ABSOLUTE counts go the
> other way -- production yields 16 scenarios that beat their null, turn mode 11.
>
> **(2) The metric is LENGTH-CONFOUNDED at scenario level, which was asserted-not-measured.**
> `calibration/audit_null_instrument.py`: `corr(lift, content-free share)` is **-0.55 / -0.82**
> (so it does NOT reward junk -- the cluster-level failure does not carry over, and that half
> of the assertion survives), but `corr(lift, mean word count)` is **+0.65 / +0.64**. The null
> is size-matched and NOT composition-matched, so a random draw is a *mixture* of 3-word
> backchannel and 100-word explanations -- maximally dispersed -- and any scenario homogeneous
> in turn SHAPE beats it. Proof by one row: **`client_direct_denial`, 98% content-free, mean
> 3.7 words, beats its null at +0.066 = rank 2 of 82.** A scenario of "No." passes. Length
> alone recovers only 6/11 and 7/16 of the passers, so it is a confound rather than the whole
> metric. **FIXED 2026-08-16 (R4, commit `b7d4e94`) -- see the block below.** It
> under-credits real situations expressed in short turns -- the same bias
> `2026-08-05-layer-b-combined-signal-analysis-design.md` found penalises terse expert moves.

> **R4 (2026-08-16): the null is now length-matched, and the corrected answer is 22% / 29%
> -- so the recorded conclusion survives a much better instrument. Every number in the
> TWO CORRECTIONS block above was produced by the pre-R4 null; cite these instead.**
>
> | arm | published (pre-R4) | corrected |
> | --- | --- | --- |
> | production | 16/82 = 20% | **18/82 = 22%** |
> | turn mode | 11/38 = 29% | **11/38 = 29%** |
> | control (HDBSCAN's own clusters) | -- | **20/38 = 53%** |
>
> **The real finding is the GAP, not either share:** groups known to be coherent reach 53%
> where both taxonomies sit at 22-29%. Turn mode staying ahead of production survives the
> correction.
>
> - **The null draws matched to each entry's own word-count profile.** Accepted turns run
>   69.1 / 80.9 words against the pool's 45.7, so the old whole-pool draw handed credit for
>   turn SHAPE. It **reduces** the confound, it does not remove it: `corr(lift, mean words)`
>   goes +0.65 -> **+0.37** (production) and +0.64 -> **+0.25** (turn mode). Read every
>   result as *length-adjusted*, never length-free. `client_direct_denial` still clears,
>   at rank 4 rather than 2 -- a pile of "No." is coherent even against other short turns.
> - **The reference must be SIZE-MATCHED, and this is the trap that ate three headlines.**
>   `lift` FALLS as n rises (corr **-0.510** inside the control) while `z` RISES with n (the
>   null's spread collapses ~1/sqrt(n)), so **no single threshold of either kind is fair
>   across entries spanning n=8 to n=1,326.** A flat control median understated both arms by
>   16-17 points. Each entry is now compared against the median lift of the 7 control
>   entries nearest it in log-size; the control scored under its own rule lands at 53%, the
>   ~50% it must.
> - **Do NOT re-derive the bar as "position within the entry's own null distribution"** --
>   the shape `flag_proper_noun_clusters.py` uses. Tried and refuted: a trivial +0.012
>   excess scores z~15 and nearly everything passes. The approximation is sound (8/8 against
>   a real 400-draw empirical p99); the STATISTIC is wrong for the question. Significance is
>   not effect size.
> - **The positive control had been built by `kind == "scenario"`, discarding the 69
>   `merged` clusters (2,434 turns against the 2,725 it kept).** `merged` means RETAINED --
>   the same collapse-to-boolean that produced the phantom "Gemma over-sinks 14.6%" finding,
>   recurring in a second file. Control membership 2,725 -> 5,159 turns.
> - **`share_eligible` is reported but is NOT arm-comparable** -- that null draws from
>   exactly the union of the entries being scored, so it re-picks ~n^2/N of an entry's own
>   members: 13.9% (turn mode) vs 7.1% (production).
> - **Two intermediate readings taken during this work, "1% vs 0%" and "5% vs 0%", were
>   artifacts of defects in the fix itself and are retracted.** Both were caught by auditing
>   the fix rather than by the fix's own tests, which is the argument for auditing every
>   correction with the same taxonomy used on the original.

**Root cause, same "the unit of decision was the bug" family as the Layer C blind-writer and Layer
D segmentation defects: `v2/layer_a.py` clusters CLAUSES while `layer_b` matches TURNS.** One turn
("Yeah. That makes sense. So for the ATS integration, do we need a pixel?") enters the pool as TWO
items, one carrying no subject. **43,566 of 73,771 clause-pool items (59.1%) are content-free** --
that is the raw material every posture scenario is built from.

- **"Clause" is a misnomer.** `preprocessing/segmenter.py` = spaCy sentences with `len(sent) < 4`
  tokens dropped. A hardcoded token count, and the de facto posture filter: it drops `"No."` (2)
  and `"Got it."` (3) but keeps `"That makes sense."` (4). **The segmenter is SHARED with
  `v2/layer_c.py:77`** (`ARCHITECTURE.md:172`) -- changing its cutoff would silently rewrite Layer
  C's milestone pool. Turn mode does not call it at all, which is what proves Layer C is untouched.

**Measured, full 416-call corpus, each arm at its OWN derived threshold** (clause 0.85, turn 0.92):

| | clause (production) | turn |
| --- | --- | --- |
| pool items | 73,771 | 23,949 |
| content-free | 59.1% | **32.8%** |
| surviving clusters | 171 | 191 |
| **subject-bearing (<30% content-free)** | **8 (4.7%)** | **71 (37.2%)** |
| junk (>=70% content-free) | 98 (57.3%) | 78 (40.8%) |
| corr(negation rate, content-free) | -0.149 | **-0.744** |
| largest cluster (both are `budget, spend, cost`) | 2,209 items / 74% of calls / 45% empty | 568 / 45% / 10% |

- **The gain is the UNIT, not the threshold -- both arms swept 0.85-0.95 and the bands NEVER
  overlap.** Clause peaks at 7.2% and freezes: 0.85->0.95 adds 65 clusters and the subject-bearing
  count stays at **16**, every new one junk, and its 2,209-item blob never splits (merging can fuse,
  never split). Turn plateaus 37.0-37.7%.
- **Turn mode's merge equivalent of 0.85 is 0.92, derived by READING groups, and count-matching
  would have picked 0.90 wrongly** -- at 0.90 six business topics fused into one 560-item blob
  (job boards + RFP + ad stack + programmatic + CRM + employer branding), the same failure
  `merge_cosine_threshold`'s original calibration recorded at clause-level 0.80. At 0.92 they split
  while the 14-raw `yeah/yep` and 8-raw `okay/alright` families still unify -- validated in both
  directions. **Do NOT write 0.92 into `tuning.yaml`: there is one key and 0.85 is correct for the
  shipped `clause` unit.**
- **`fit_topic_model`'s `min_cluster_size = max(3, min(n // 10, 50))` is a hardcoded COUNT of 50
  for any corpus >= 500 items**, so granularity depends on pool SIZE: 0.068% of the clause pool but
  0.209% of the turn pool, a 3x stiffer bar. It now takes an optional override (default `None` =
  legacy). **Any comparison of two pools with different item counts MUST pass a scale-matched
  value** -- the first turn arm ran at 50 and produced 74 raw clusters vs clause's 237, which read
  as "turn mode is coarser". At the matched 16 it produces **246**, slightly MORE. That conclusion
  was withdrawn twice, once for this and once for the merge threshold.
- **Gemma catches camouflaged junk -- the main risk does not reproduce.** `jovio, jovia, jovio team`
  is 563 substantive-looking turns across 50% of the corpus at only 4% content-free, glued by the
  company's own name. Gemma sinks it as `mechanics` ("conversational introductions, participant
  coordination, meeting housekeeping"), on LESS context than production supplies, and without the
  coverage warning (50% sits under `ubiquity_ceiling: 0.60`). `PROMPT_LAYER_A_V2_TRIAGE`'s *"Judge
  the utterances, not the keywords"* is what does it -- a defence that existed but had never been
  tested against junk that looks substantive, because clause mode never produced any. 7/8 on the
  spot-check.
- **The posture x subject grain arrives at ADJUDICATION, not clustering.** 5 of 5 accepted clusters
  produced a description carrying both -- `budget_and_spend_constraints` = *"clients expressing
  hesitation or constraints around marketing spend, budget allocation and ROI justification"*.
  Looking only at clusters (subject-only, mixed stance inside) said the grain was absent; that was
  the wrong place to look. Gemma cannot write stance from fragments -- `"That makes sense."` x630
  offers nothing but the stance, which is precisely how `client_expresses_uncertainty` is produced.
  So the proposed "second pass splitting clusters by stance" is **retracted as unnecessary**. n=5.
