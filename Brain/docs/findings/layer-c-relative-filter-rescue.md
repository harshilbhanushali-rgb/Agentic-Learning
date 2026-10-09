# Layer C — Relative Filter & Noise-Rescue, F1/F2 Follow-ups (2026-08-17)

[Findings index](INDEX.md)

### Layer C: the two live directions ran, one gate passed each way (2026-08-17)

Spec `docs/superpowers/specs/2026-08-17-layer-c-relative-filter-and-rescue-design.md`
(gates frozen before code). Harnesses `calibration/lcfr_common.py` /
`layer_c_relative_filter.py` / `layer_c_noise_rescue.py` (new; production functions
imported, F0-validated against the published control 171/171, pre-run blind audit CLEAN).
Artifacts `layer_bc_lcfr_*.json` are scoreable by `score_layer_b_arms.py` unchanged.
**Zero chat, zero new embeddings, zero Postgres.**

- **A PER-CLAUSE RELATIVE RULE MAKES LAYER C ROUTING-QUALITY SENSITIVE -- the property F10
  said nothing downstream had.** Measured real vs destination-permuted routing: p40
  survives 60.0%/60.0% (gap 0.0pp); every relative rule (rank/margin/demean/CSLS) gaps
  8-20pp; downstream, permuted intake falls to 0.658x under rank(8) where p40 sits at
  1.000 (G-T1b PASS). But G-T1a = **WEAK** (best 20.0pp < the 25pp bar at >=50%
  retention) -- no adoption on tonight's numbers.
- **The relative rule and the percentile fail on OPPOSITE axes -- found by reading, not
  by the aggregate.** rank(8) drops substantive broadly-relevant clauses (own scenario
  ranks below 8 of 26 topically-overlapping ones) while keeping filler whose weak
  preference points home; p40 does the reverse. Post-hoc conjunction (labelled, not
  pre-registered): gap 16.3pp at 47.2% retention with the junk excluded -- the follow-up
  to pre-register, not a result.
- **Full CSLS LOST to plain rank (8.3-17.5pp vs 11-20.1pp).** The hubness FRAME from the
  literature transferred; the both-side correction formula did not at 26 classes. Take
  frames from the literature, re-derive formulas at your own scale.
- **rescue_centroid ports at SELECTION and fails at DELIVERY.** Blinded independent read:
  **12/12 for the rule over its volume-matched placebo, zero ties, p=0.0005** -- the first
  unanimous instrument in the whole Layer C effort. But 99.3% of its 1,043 admissions
  (31.7% of noise) went to already-passing clusters -- only 33 of 204 clusters were
  base-failing and exactly ONE was flippable at the delivered volume. Gained milestones:
  rescue 0 vs placebo 1 (a coin-flip event, audited before being believed).
  Account-diversity lift null in BOTH arms (4up/8down p=0.39; 5up/10down p=0.30).
  Nearest-centroid admission structurally aims at big dense clusters -- the milestones
  needing help least. A SUPPORT-TARGETED variant (aim at failing clusters) is the
  pre-registration-worthy follow-up.
- **WITHDRAWN after a placebo-veto audit: "rescue additions are account-concentrated,
  opposite of Layer A."** The medians (0.50 vs 0.33) are quantization minima for 2-vs-3
  distinct calls; conditioned on distinct-call count the arms are identical (pooled N_eff
  26.5 vs 25.4 over 82 accounts). Real mechanism: **same-call gluing** -- 68.6% of the
  rule's adds land on calls already among the cluster's members, 41 literal duplicate
  texts. Never compare per-cluster medians of top-account share at 1-4 adds.
- **Two more of Layer C's cited "aggregate junk defences" measured, both near-blind:**
  the sink-similarity review flag is a within-run percentile (flag rate 5.3% real / 5.4%
  permuted by arithmetic, threshold self-adjusts) and, cross-applied, flags fully-random
  routing at only **9.2%**. With the relevance filter's 60/60, two of the four are now
  measured as unable to scale with contamination; only the Gemma judge behind the flag is
  absolute.
- **Layer C discards ~42% of its post-relevance pool at CONTENT PARITY** -- noise 26.3%
  content-free vs clustered-kept 27.3% vs gate-failed 26.0% (n = 3,302 / 4,338 / 289);
  sampled noise reads as real expert content. Layer A's "the loss is in UMAP->HDBSCAN,
  not the content" now holds at Layer C, measured.
- **The zero-clause-call denominator defect does NOT bind at the shipped setting** -- 0
  required-support drops, 0 flips at s0/a0. Live only under admission knobs (a4) that
  inject near-empty pairs; closed for the shipped configuration.
- Everything here is gemini@3072 on the clean2_base turn-mode taxonomy: directions
  transfer, numbers do not; no `tuning.yaml` change may cite them alone.


---

### Layer C follow-ups F1/F2: both CLOSED same-day (2026-08-17)

Spec `docs/superpowers/specs/2026-08-17-layer-c-retargeted-followups-design.md` (gates
frozen before code; harness `calibration/lcfr_followups.py`, audit CLEAN, 5 tests).

- **G-F2 NULL: ~20pp is the CEILING for any Layer C intake filter on this taxonomy.**
  The p40-AND-rank(K) conjunction's gap decays monotonically K=8->14 (16.3 -> 9.6pp); the
  first K clearing the 50% retention floor lands at 13.8pp, under the 15pp NULL bar.
  Retention and discrimination trade one-for-one. **Filter-shape search at Layer C is
  over** -- the constraint is the 26 topically-overlapping scenarios or the clustering,
  not the filter.
- **G-F1 UNDERPOWERED-NULL, and the rescue direction closes ENTIRELY: the noise pool does
  not contain the failing clusters' content.** Aimed exclusively at the 33 base-failing
  clusters, the p25 rule admitted 15 clauses corpus-wide -- **28 of 33 failing clusters
  got ZERO admissions as the only eligible destinations**. Flips: rule 2, placebo 4
  (p=0.50; both under the floor of 5), the direction the placebo-veto audit predicted
  (same-call gluing: 8 adds -> 2 new calls vs placebo's 5). Selection was never the
  problem (12/12); delivery cannot be re-aimed into content that is not there. The noise
  pool's remaining value is RE-CLUSTERING, not rescue.
- Net for the whole 2026-08-17 effort: Layer C's intake CAN see routing quality (a first),
  but nothing tried tonight moves evidence breadth per milestone. The live levers left, in
  order: a Layer C clustering-method bench over the content-parity noise pool (42%
  discarded at 26.3%-vs-27.3% content-free), the Layer C UNIT question, and S2 -- which
  still needs a human brainstorm.
