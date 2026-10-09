# Layer A — Pool Unit: Clause vs Turn, Part 2 — Root Cause, Long Turns, Proper Nouns (2026-08-14/15)

[Findings index](INDEX.md) · continues from [layer-a-pool-unit-1.md](layer-a-pool-unit-1.md)

- **Long turns: two probes, two different questions, BOTH true -- and the first one alone reads as
  a false all-clear.** 4,201 turns >= 100 words = 17.5% of turns but **52.4% of all client words**.
  (1) They do NOT damage the cluster they join -- they land in the CLEANEST ones, 5.4% content-free
  at 100-199 words vs **76.8%** at 0-9 words, `r = -0.834`, and noise plateaus at 58-60% above 25
  words so they are no worse-clustered than medium turns. (2) But content INSIDE them IS orphaned:
  splitting assigned turns back into sentences, **59.1% of sentences in a 100-199 word turn fit a
  DIFFERENT cluster better (>=0.05 cosine) against a 21.9% short-turn floor** -- ~37 points from
  length. The turn lands correctly for its DOMINANT topic while its secondary topics go
  unrepresented. **But 72.7% of that 59% is FILLER rejoining backchannel clusters -- which is the fix
  WORKING, not harm** (read samples: `"All was all well."` wants `thats good, good`; `"I'm like,
  okay."` wants `okay okay`). Narrowing to substantive sentences whose preferred AND assigned
  clusters are both subject-bearing gives **genuine subject loss = 2,483 of 31,522 sentences
  (7.88%), monotonic in length: 0.00% at 0-9 words, 8.61% at 50-99, 13.75% at 100-199, 18.70% at
  200+** -- and that is an UPPER bound (one sampled "loss" was scheduling content admitted by the
  `< 30% content-free` filter, the `jovio` false-positive class). The clearest genuine case is a
  sentence about **Indeed Connect** stranded in the `ukg` ATS cluster when it wanted the job-board
  one. **`Approach C` (chunk long turns into topic-bearing pieces, never emitting a stance-only
  fragment) stays live but ranked LOW:** single-digit gains, a new calibrated knob, and the
  `"Indeed"` fix as a prerequisite, versus the ~60%-of-substantive-turns noise problem which is an
  order of magnitude bigger and needs only Concern 6. **The trade is real and not a regression:**
  clause mode has zero orphaning precisely because every sentence is its own item, which is the
  mechanism that manufactures posture clusters. **The concern went CLOSED -> REOPENED -> SETTLED;
  the three reasons matter more than the label.**
- **`~60% of every substantive turn (>25 words) becomes HDBSCAN noise` and never enters the
  taxonomy** -- 11,701 of 23,949. Uniform above 25 words, so not a long-turn issue and not
  chunkable. Same coarse-clustering family as the sink pool's 47.3% noise. Unscoped.
- **Live production for comparison: 161 scenarios, 85 coachable (52.8%), 76 sinks, 84 rubrics --
  but only 31% of rankable scenarios beat a random null.** The `is_coachable` label is materially
  more optimistic than the evidence supports. **(31% corrected to 20% on 2026-08-15 -- see the
  two-corrections block above.)**

**The proper-noun check ran (2026-08-15), and the check this spec PROPOSED would not have found
its own confirmed example.** `calibration/flag_proper_noun_clusters.py`, free, zero writes;
artifact `proper_noun_clusters.json`. The account is recoverable directly -- the modal non-joveo
email domain on each Avoma `.speakers.json` roster -- so "are the top keywords a proper noun" can
be replaced by the question actually at stake: *does this cluster's evidence come from one
client*. 355 of 400 calls carry an account across 112 accounts. Cluster membership was re-attached
by reproducing the adjudication ordering and **verified position-for-position on n_items, calls
and keywords (245/245)**; a size-matched Monte-Carlo null prices in the corpus's own skew
(`uber.com` alone is 19.6% of accounted turns).

- **`corr(proper-noun rate of top keywords, account lift) = 0.047` -- the proposed check is
  nearly unrelated to account-boundness.** It MISSES `implementing_and_maintaining_tracking_pixels`
  and FALSELY flags `navigating_rfp_and_procurement` -- 100% PROPN keywords (`kim`, `rfp`),
  **66 accounts, 120 calls, the most broadly-evidenced coachable scenario there is** -- plus
  `ats_migration_and_ecosystem_complexity` (`workday, isims, taleo`: industry-standard vendors,
  12 accounts). Proper-noun-ness measures whether a word is a NAME, not whether it belongs to
  ONE CLIENT. The signal that works is keyword-account concentration (r=0.587, mean-aggregated):
  `cie`=100%, `veterinarians`=100%, `lexi`=100%, **`happy dance`=100%**, `raytheon`=96%,
  `dance`=96%.
- **CORRECTED 2026-08-15 (F14/R2a) -- every correlation in the bullet above moved, the verdict
  did not.** BERTopic runs `ngram_range=(1,2)` but the harness looked keywords up against a set
  of UNIGRAMS per turn, so **296 of 735 top-3 keyword slots (40%) matched nothing and came out
  NaN in both Signal B and Signal C** -- `happy dance` among them. Matching keywords as token
  SEQUENCES rescues 217 slots across 187 distinct keywords. **Signal A is untouched: 0 of 245
  clusters moved on `top_account_share`, `lift` or `exceeds_null_p99`, so the 21-of-38 headline
  and the 9-of-38 reading below stand.** What moved:

  | | published | corrected |
  | --- | --- | --- |
  | corr(propn rate, lift), coachable | +0.182 | **+0.047** |
  | corr(keyword-account, lift), **max**-aggregated | +0.616 | **+0.393** |
  | corr(keyword-account, lift), **mean**-aggregated | +0.705 | **+0.587** |
  | clusters with a NaN propn rate | 16 | 4 |

  The old parenthetical -- *"`happy dance` is a bigram absent from the unigram POS table"* -- was
  describing a HARNESS BUG as if it were a property of the data. The phrase rates **0.669 PROPN**
  and is **100% one account**, the most account-bound phrase in the corpus. The check still misses
  the cluster (rank 7 of 38 by propn rate, up from 10), so the conclusion survives for a different
  reason than the one recorded.
- **`max` was the wrong aggregator and that is why 0.616 fell so far.** Max over a cluster's top-3
  keyword concentrations can only RISE as more keywords become visible, so fixing F14 saturates it
  toward 1.0 and destroys the variance the correlation needs -- the number was partly measuring how
  many keywords the harness could see. Mean moves far less (0.705 -> 0.587) and is what the bullet
  now quotes. **Neither figure is computed by the script**; both were derived outside it and the
  aggregation was never recorded, which is why pinning `0.616` to `max`-over-coachable took a
  four-way sweep. Any future correlation quoted from this artifact must state its aggregator.
- **Still NaN after the fix: 87 distinct keywords, from a DIFFERENT cause -- filed as R15, not
  fixed here.** `_WORD` (`[a-z][a-z0-9'\-]*`) is not sklearn's `CountVectorizer` pattern
  (`(?u)\b\w\w+\b`), which is what built the keyword vocabulary. It keeps apostrophes inside a
  token, so the vocabulary's `dont` / `dont know` / `alright theres` can never match `don't`, and
  it requires a leading letter, so `18` / `2021` / `20 20` never match. 15 of the 86 absent
  keywords ARE found under sklearn's own pattern. Same defect family as F14 -- the lookup
  tokeniser must be the vectoriser's tokeniser -- but a separate change that moves existing
  non-NaN values, so it needs its own measurement.
- **21 of 38 coachable clusters exceed their own null's p99; by reading, 7 should not be in the
  count.** 6 are account-bound (tracking_pixels = 95% Uber and really vendor coordination;
  experiential_branding = 98% RTX; managing_non_technical_stakeholders = 100% Banfield, glued by
  two colleagues' FIRST NAMES; niche_board_roi = 100% Banfield veterinary vocabulary;
  creative_candidate_engagement; ats_and_middleware_integration_architecture). 11 more are general
  situations with single-account evidence -- a different disease. 3 are statistically over the bar
  but substantively broad (`candidate_application_...` is 29% vs a 19% null across 33 accounts).
- **`compensation_and_variable_structuring` is NOT A CLIENT CONVERSATION AT ALL.** It is job
  interviews across 9 calls -- *"You wanna know how much I was earning at Radiance?"*, *"I'm
  currently at one 55 base"*. Its modal account is `gmail.com` and 14 of 20 sampled turns have no
  client domain, which is the tell. **It also PASSES the null test at rank 3 of 38** -- interviews
  are internally coherent -- so neither instrument catches it alone.
- **Sinks are NOT account-contaminated**: +2.7% mean lift with 11% flagged, against coachable's
  +29.6% and 55%. The contamination is entirely in what Gemma ACCEPTS, consistent with the blind
  judges agreeing 100% on what to discard.
- Sibling domains collapse: `scale.com`/`contractors.scale.com` are one account, so
  `optimizing_cost_per_activation_and_worker_quality` is **100%** one account, not the 74% printed.
- **Net: 9 of 38 survive both the null test and reading.** 38 -> 31 after removing junk, 11 pass
  the null, 2 of those 11 are junk. Quote 9, not 38, and note the null half is length-confounded.

**Measurement lessons, all three earned the hard way this session:**

- **A measurement script must call the production entry point with the production arguments.** Two
  scratchpad scripts each disagreed with production by ~20%: spaCy loaded with
  `tagger`/`attribute_ruler`/`lemmatizer` disabled **moves sentence boundaries** (88,431 clauses vs
  the true 73,771), and `parse_transcript` without the Avoma `roster` argument misclassifies
  speakers (28,905 CLIENT turns vs the true 23,949). Both inflated ~20% and neither was visible
  without a production cross-check. Prefer a harness that imports production code.
- **Coherence-lift-over-a-null is NOT a cluster-quality gate -- it rewards the junk.**
  `corr(lift, content-free fraction) = +0.527` in the clause arm and +0.555 in the turn arm; junk
  clusters average +0.160 lift against real ones' +0.107, because a pile of "that's huge" is
  lexically tighter than a real discussion of markets. At CLUSTER level it asks "did HDBSCAN run",
  not "is this a situation". It remains valid at SCENARIO level, where members are whole turns.
- **The content-free proxy has a false-positive class it cannot see:** a cluster of
  substantive-but-unrelated turns (`jovio`) counts as subject-bearing. So **37.2% is an upper
  bound** and must never be quoted as "71 coherent scenarios". The clause arm's 4.7% carries the
  same flaw, so the comparison holds.
- **Before believing a rate, ask what fraction of it is the behaviour you were TRYING to cause.**
  Both metrics that misled this session failed that question: coherence-lift rewarded junk
  (+0.527 with content-free fraction) and the raw orphan rate was 72.7% filler rejoining filler,
  i.e. the fix working. In both cases reading a handful of real samples exposed it where the
  aggregate could not.
- **A probe answers the question it was built to ask and NO adjacent one.** The long-turn probe
  measured destination quality (clean clusters) and it was read as content retention; a second probe
  showed 59% of the content inside those turns belongs elsewhere. State what a measurement CANNOT
  answer in the same breath as its result.
- **Every quantitative prediction about the pool got the RATIO right and the QUALITY direction
  wrong** (content-free 58.9% vs 59.1% with counts 20% off; long turns 17.6% vs 17.5% with the harm
  inverted). Measure the effect; never infer it from the size of the population.
- The turn pool spans **400 calls, not 416** -- 16 transcripts contribute zero CLIENT turns. Every
  trial computed `call_coverage` and the support floor against 416, so coverage is slightly
  understated and the floor is 9 rather than 8. Too small to move a conclusion; unexamined.

