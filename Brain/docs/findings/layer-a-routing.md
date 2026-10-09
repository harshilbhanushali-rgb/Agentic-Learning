# Layer A — Routing Methods, 16 Arms (2026-08-16)

[Findings index](INDEX.md)

### Routing methods: 16 arms searched, the incumbent exemplar centroid was NOT beaten (2026-08-16)

> **THE RANKING BELOW IS WITHDRAWN — both checks ran and both went against it (2026-08-16).**
>
> **(1) The gate IS self-serving** (`calibration/routing_objective_audit.py`, free, both
> self-checks passed: draws reproduce `nt.length_matched_null` to 1e-9 and the `centroid`
> column reproduces `routing_bench`'s `share_fixed` exactly). Same populations, three
> objectives: **`description` goes from 32% under the centroid objective to 97% (37 of 38)
> under its own**, with nothing changed but the ruler. **And the neutral `lexical` column is
> unusable too — `placebo_centroid` scores 37% there, BEATING `description` (29%).** A referee
> a random partition can beat is not a referee.
> **NEVER propose "mean pairwise cosine" as the neutral measure**: `coherence(P) ==
> sqrt(mean pairwise cosine incl. diagonal)`, verified identical to 1e-6 at n=10/50/300. It is
> the same statistic renamed, and it was nearly used to audit itself.
>
> **(2) BLIND reading of real turns contradicts the aggregate**
> (`calibration/read_routed_samples.py` writes the samples and the answer key to SEPARATE
> files; judgments committed before the key was opened). Destination (both accept, different
> scenario, n=20): **`description` 11-8**, and 7-3 on confident calls — the OPPOSITE direction
> to the aggregate's 61% vs 32%. Accept-vs-reject (n=12): `centroid_pooled` 8-4. Nothing
> significant (p=0.648 / 0.344 / 0.388). Both arms' sinks caught genuine junk.
> **Reading suggests a split the aggregate never showed: prose is at least as good at choosing
> WHERE a turn goes; member turns are better at choosing WHETHER to take it.**
>
> **(3) BLIND READ v2 REVERSES v1 AND IS SIGNIFICANT — `calibration/read_routed_samples_v2.py`.**
> v1 asked "which arm's call is right" and showed the reader both answers (n=12, p=0.388). v2
> shows ONLY the turn — no arm, no candidate scenario, no accept/reject hint — and asks one
> arm-independent question, "is this substantive?", then scores every arm against that single
> judgment. On the 40 turns where the routers disagree: **`description` 70% accurate (precision
> 75%, recall 38%) vs `centroid_pooled` 30% (precision 31%, recall 62%), McNemar 28-12,
> p=0.017.** `centroid_pooled` accepts **22 of the 24 non-substantive turns**.
> **So description is CONSERVATIVE (misses real moments) and member-centroids OVER-ACCEPT
> (admit junk).** For this pipeline the conservative error is the right one: a false positive
> puts fabricated coaching in front of a human, which is the failure mode the Step-0
> false-positive investigation already identified.
> **THE SPLIT-ROUTER HYPOTHESIS IS REFUTED.** `arm_split_member_accept_desc_dest` was built on
> v1's n=12 reading (members better at accept); v2 shows members are the WORSE side, and the
> arm scores identically to `centroid_pooled` because it inherits that decision. Kept in the
> registry as a recorded negative, not a candidate.
> **Limitations, stated not buried:** the sample is the DISAGREEMENT set, so precision/recall
> are conditional on disagreement and are NOT global rates; one reader, who designed the arms;
> and the reader's substantiveness bar (16/40 = 40% substantive) sits close to `description`'s
> own global accept rate (41.4%), so a stricter or looser bar would move the result.
>
> **(4) THE RECALL ARGUMENT DISSOLVES ON A PR CURVE — `calibration/routing_pr_curve.py`.**
> Comparing two arms at ONE operating point each is not comparing two methods. Both share a
> knob nobody had swept: `accept iff max(coachable score) - max(sink score) >= delta`, which at
> `delta=0` IS the shipped rule, so both curves pass through their published point.
> Ground truth is the 80 blind-judged turns, reweighted by stratum
> (8,851 / 10,275 / 3,749 / 1,074 — a raw average over the 80 is badly biased).
> **Global, stratum-weighted: `description` P 79.5% / R 87.1%; `centroid_pooled`
> P 65.5% / R 91.1%. Estimated 9,058 substantive turns (38% of the pool).**
> **At MATCHED recall, `description` @ delta=-0.0117 gets P 76.9% / R 92.2% — HIGHER recall
> than centroid and 11pp more precision.** Its curve sits above centroid's across the whole
> high-recall region. Neither dominates everywhere: near delta=+0.018 centroid trades better
> (P 75.7 / R 70.0 vs P 83.0 / R 54.8), but Layer D does not operate there.
> **So more recall is bought with the KNOB, not a method swap:** delta=-0.0117 buys +5.1pp
> recall for -2.6pp precision, against switching to centroid's +4.0pp recall for **-14.0pp**
> precision — one fifth the cost. Centroid's extra accepts run **1 real moment : 6.3 junk**.
> **Bootstrap CIs on 80 judgments are WIDE and overlapping** (76.9% [61-90] vs 65.5% [52-78]),
> so the curve comparison alone is not significant; it is consistent with the paired McNemar
> at delta=0 (28-12, p=0.017), which is the powerful test because it scores both arms on
> identical turns. Do not cite the curve as independent confirmation.
>
> **NO ROUTING CHANGE MAY SHIP, including `scenario_vector_mode` (stays `concat`), until an
> instrument exists that can rank methods ACROSS population shapes.** The `delta` knob is the
> one change the evidence positively supports, and it is NOT built — it would be a new
> `layer_b` tuning key defaulting to 0.0 (byte-identical), swept against a larger judged
> sample than 80 before any value is chosen. The durable result is
> methodological: **an evaluation metric that is any arm's objective function cannot rank arms,
> and the cheap way to detect it is to re-score the SAME populations under a rival's
> objective.** Run that before any future arm comparison in this repo.
>
> Original caveat, now confirmed rather than suspected: `coherence(P)` is mean cosine of a
> population to its OWN centroid, and the centroid arms assign by maximising cosine to a
> centroid, so **the gate is those arms' own objective function**; an arm optimising anything
> else is graded on their loss. `placebo_centroid` does NOT control for this — random-partition
> centroids collapse toward the global mean (margin p50 0.0023 vs 0.0145, degenerate), so it
> tests "is the centroid informative", not "is the metric centroid-shaped".
> **Corroborated from an independent direction by the cross-encoder run:** grouped by
> population SHAPE rather than method, every Voronoi-cell arm scores 50-61% while
> `description` (LLM prose + bi-encoder) and `xenc_member` (neural cross-encoder over member
> turns) — two methods sharing no mechanism — land on the SAME 32%.
> **Cheap falsification, NOT YET RUN:** re-score every arm under an arm-neutral objective
> (mean cosine to the key's description vector; and/or mean PAIRWISE cosine within the
> population instead of cosine to its own centroid). If each arm wins under its own objective,
> the ranking must be withdrawn. Within-shape comparisons are unaffected and were already null.
>
> **Also standing, unaddressed:** nothing was READ — zero routed or rejected turns inspected,
> against this repo's own repeated lesson; the CLUSTERING saw every test turn so "out-of-fold"
> folds only the centroid computation; routing accuracy is near-tautological (ground truth is
> HDBSCAN membership, the centroid is that cluster's mean); the control grades 5,159 turns
> against the arms' ~12,000 with barely overlapping size ranges; and `desc_keyphrases` may be a
> scenario-TEXT-length artifact since the null is length-matched over turns, not over
> scenario text.

**Cross-encoder re-ranking was the strongest untested idea. Pre-registered, run, FAILED (F8).**
`centroid_pooled` proposes top-5, a local `ms-marco-MiniLM-L-6-v2` re-scores each turn against
the 3 most central member TURNS of each candidate. Out-of-fold: proposer **61%** ->
`xenc_member` **32%** -> `rerank_random` placebo **18%**. **Re-ranking HALVES its own candidate
generator.** It beats its placebo, so it is genuinely reading the pairs — **weak signal that
OVERRIDES strong signal is worse than no signal**, which is the transferable lesson. Not a
verdict on cross-encoding in general: ms-marco was probed as out-of-domain first (saturates at
its irrelevant floor on prose, spread 0.57; separates on turn-vs-turn, spread 4.61 — which is
why the arm pairs turns with turns).
**The Joveo gateway has NO reranker**: `/rerank` exists and forwards to AWS Bedrock, but the
gateway validates `model` against its own list and `GET /model/info` reports modes
`{chat:116, embedding:12, image_generation:9, realtime:1, responses:2, unlabelled:8}` — **no
`rerank` mode**, and all 8 unlabelled are chat/image. Enabling `cohere.rerank-v3-5:0` on the key
would make this cheap to retest. Do not re-probe the ARN forms; all are rejected at the gateway
before reaching Bedrock.

Spec `docs/superpowers/specs/2026-08-16-layer-a-routing-method-design.md` (pre-registered
before any arm was written). Harness `calibration/routing_bench.py` + `calibration/routing_arms.py`
(21 tests), artifact `artifacts/routing_bench.json`, per-seed `routing_bench_s{42,1,7,2026}.json`.
**Zero chat calls. 754 embedding requests, once, for the description variants. Zero DB writes.**
Promotes three scratchpad scripts (round trip / held-out routing / coherence-vs-null) into ONE
process, because three processes would grade arms against three separately-fitted clusterings.

- **Verdict: "the obvious fix is also the best available."** 16 arms — prototypes, medoid, k-NN,
  multi-modal sub-centroids, a SetFit-style linear probe, blends, four description registers —
  and **no arm beats the exemplar centroid at a defensible level.** The whole centroid family
  (`centroid` 50.7, `centroid_pooled` 59.2, `submeans` 54.6, `blend_a0.75` 61.2) is mutually
  indistinguishable: `blend_a0.75` vs `centroid` is 6-3 discordant, **p=0.508**.
- **The ONE significant result: membership-based routing beats description routing**,
  `blend_a0.75` vs `description` 12-1, **p=0.003**, replicated in 4 independent fold splits.
  The shipped `description` arm scores 31.6 against the placebo's 3.3 and the control's 55.3.
- **`share_fixed` is over the CONTROL's rankable set, never an all-arm intersection.** The
  intersection SHRINKS when any one arm starves scenarios (`probe` alone dragged it 35 -> 21),
  which degrades every other comparison in the run AND excuses the starving arm by removing the
  scenarios it failed on from its own denominator.
- **A fold-seed band is NOT a significance test, and for some arms it is not even a band.**
  `description` / `desc_prose` / `desc_keyphrases` / `desc_maxpool` / `desc_kp_each` do no
  fitting, so they produce byte-identical assignments at every seed: their range-0 column is
  INVARIANCE, and "leads in 4/4 seeds" among them is **one observation reported four times**.
  The pre-registered gate (F3) read the band and would have declared a winner the paired
  McNemar test does not support. Print fold-dependence per arm in any future harness.
- **The binding constraint is 38 scenarios.** McNemar needs ~12-1 discordant for p<0.01, so a
  method better on 4 more scenarios is unresolvable. **More evidence, not another method.**
- **The single 75/25 holdout was under-powered and was replaced by 4-fold CV over CALLS** —
  it left 14 rankable scenarios against the spec's own floor of 20, and the arm ordering
  inverted against full-corpus. CV also makes out-of-fold and full-corpus differ in exactly one
  respect (did the router see the turn's call), sharing one control and one reference.
- **`knn_max` / `knn_topk_mean` / `medoid` / `probe` are self-inflating on the full corpus** —
  a member is its own nearest neighbour at cosine 1.0, reproducing membership having learned
  nothing. Marked `*` in the report; only the out-of-fold column is interpretable.
- **Free self-check that catches fold-machinery bugs: `description` does no fitting, so its
  out-of-fold and full-corpus assignments must be identical turn for turn.** Asserted on all
  23,949 turns.
- **The placebo (`placebo_centroid`, centroids of a size-matched random partition) scored 3.3
  and is what makes the metric readable.** Coherence is mean cosine to a population's own
  centroid, so any router aiming at an in-manifold point could have scored well for that reason
  alone. It did not.

**`layer_a.scenario_vector_mode` added, shipping `concat` = byte-identical (verified against all
245 real scenario rows, 0 differing).** `shared/scenario_vectors.py::scenario_text` concatenates
`business_description` (analyst prose) with `keyphrases` (verbatim client language) into ONE
vector; its docstring asserted keyphrases are "what triggers actually resemble" and that was
never tested. Measured: keyphrases alone **42.1**, prose alone **34.2**, the shipped
concatenation **31.6 — below either component**. Mixing two registers in one averaged vector is
worse than picking either. **But it is 7-3 on 38 scenarios, p=0.344, and a SINGLE observation
(this arm does no fitting) — do NOT flip it on that.** The flag exists so the question is cheap
to settle. `concat` | `keyphrases` | `prose`; an empty target field falls back to concat with a
logged WARNING, never silently to an empty-string vector.

- **`desc_kp_each` — every keyphrase as its own retrieval point, the free HyDE/HyPE analogue —
  is the WORST non-placebo arm at 18.4, while the same words joined into one vector score 42.1.**
  Multi-point retrieval per class is what fails, not the content. **This is why the paid
  `desc_synthetic_utterances` arm was never run** — same many-short-points shape, ~80 chat calls
  to re-confirm a free result. `desc_maxpool` (26.3) is likewise worse than both its components.
- **EVERYTHING HERE IS gemini-embedding-2@3072 WHILE PRODUCTION EMBEDS WITH LOCAL bge@768.**
  The transfer check was explicitly declined, not overlooked. It matters most for `blend_a0.75`
  (α is cosine-scale-dependent) and least for `scenario_vector_mode` (selects text, not a
  threshold). No routing change may ship to production citing these numbers alone.

