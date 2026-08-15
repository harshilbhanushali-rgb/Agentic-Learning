# Layer A pool unit: the taxonomy is built from sentence fragments (2026-08-14)

Status: **pre-registered, nothing implemented, nothing run.** Ships OFF.

## The finding that started this

Two thirds of the scenario taxonomy is statistically indistinguishable from a random pile
of client turns.

`calibration/scenario_coherence.py` (untracked before this work) measured mean cosine of each
member to its scenario centroid over the live `public` schema: 84 coachable scenarios with
pairs, 68 rankable at >= 8 triggers, 16 too thin to rank.

| population | n | trigger coherence |
| --- | --- | --- |
| all rankable | 68 | min 0.674 p25 0.721 **med 0.747** p75 0.758 max 0.797 |
| posture (`client_*`) | 24 | mean **0.719** |
| subject-matter | 44 | mean **0.751** |

The band is narrow and the prior run's tight-vs-loose separation was **0.0444**, below its own
pre-registered 0.05 bar -- recorded verdict NO-GO. Read that correctly: it means the halves
cannot be A/B'd against each other, **not** that the scenarios are sound.

**A size-matched random null had never been taken, and it is the number that decides
everything.** Drawing random sets of the same sizes from the same 2,904 coachable-filed
trigger texts (20 draws per size, seed 42):

| | trigger coherence |
| --- | --- |
| random size-matched null | **0.706** |
| real scenarios | **0.740** |
| lift | **+0.033** |
| scenarios beating their own null by >= 0.05 | **21 / 68** |

+0.033 is below the 0.05 bar the harness itself set for "a difference in this metric is real".

**The split is near-total: of the 21 that clear their null, 20 are subject-matter. Exactly 1 of
24 posture scenarios clears it.** Top lifts are all subject-matter --
`landing_page_strategy_discovery` +0.094, `tracking_tag_implementation_friction` +0.071,
`programmatic_maturity_and_intent_discovery` +0.069, `pixel_implementation_discovery` +0.068,
`job_board_ecosystem_discovery` +0.066, `crm_workflow_discovery` +0.064.

This independently reproduces, for free, the population split the paid ceiling run found
(subject-matter mean gap +0.057 with 2/25 inverted; posture -0.019 with 5/15 inverted).

What the good third carries -- the same 21 scenarios, now against the full population of 84
rather than the 68 rankable: 21/84 scenarios (25%), 844/2,904 trigger pairs (29%),
136/405 milestones (34%), **1,374/4,181 Layer D attempts (33%)**.

**Secondary read, and a trap.** Response coherence is uniformly higher (med 0.807) and nearly
uncorrelated with trigger coherence (r=0.195). `platform_capability_and_technical_guidance` is
0.676 trigger / **0.856** response. Responses look uniform because one person's phrasing is
uniform, so **any Layer C-internal metric will look healthy on a scenario that is not one
situation.** Do not use response coherence as evidence the taxonomy is sound.

## Root cause: Layer A clusters CLAUSES, Layer B matches TURNS

Same "the unit of decision was the bug" family as the Layer C blind-writer and Layer D
segmentation defects.

`v2/layer_a.py:36` segments every CLIENT turn into clauses and each clause becomes an
independent embedding. One turn:

> "Yeah. That makes sense. So for the ATS integration, do we need a separate pixel on the
> apply page?"

enters the pool as **two items** -- `"That makes sense."` (stance, no subject) and the ATS
question (subject). Thousands of the first kind cluster together because they genuinely are
near-identical, and that is `client_validates_proposed_scenario` (n=86),
`client_expresses_uncertainty` (n=30), `client_direct_denial` (n=35).

`kb_pairs.trigger_text` is a whole **turn**. So the taxonomy is built from fragments and then
matched against whole turns -- which is also why the coherence measurement above had to come
out near random: it scored turns against centroids made of fragments.

### What "clause" actually means

Not a grammatical clause. `preprocessing/segmenter.py:14-26` does two things: split into
sentences with spaCy's dependency parser, then **drop any sentence under 4 tokens**
(punctuation counts). The cutoff lands mid-backchannel:

| dropped | kept, enters the pool |
| --- | --- |
| `"No."` (2) `"Yeah."` (2) `"Got it."` (3) | `"That makes sense."` (4) `"I don't know."` (5) `"Okay, sounds good."` (5) |

`len(sent) < 4` is a hardcoded token count -- exactly the "a threshold must never be a count"
anti-pattern CLAUDE.md forbids -- and it is the de facto posture filter.

The boundaries are also **guessed twice**: the speech-to-text engine invented the periods,
then spaCy predicted sentence boundaries partly from them. Measured on real transcript text,
spaCy splits with no punctuation at all, and cut `'I'` out as its own one-token sentence from
the stutter `"I I I don't know"`. A turn boundary, by contrast, is recorded fact about who was
speaking.

### Measured supply and loss (416 transcripts, free)

| | |
| --- | --- |
| CLIENT turns | **23,949** over **400** calls (corrected -- see Status update 7) |
| words per turn | p10 3, p25 8, med 25, p75 70, p90 129, p99 177, max **314** |
| turns 0-9 words | 7,004 (29.2%) |
| turns >= 100 words | **4,201 (17.5%)** -- holding **52.4% of all client words** |
| **clause pool** (production `build_client_pool`) | **73,771** |
| **pool clauses that are content-free** (<5 content words) | **43,566 of 73,771 (59.1%)** |

**CORRECTED 2026-08-14, and the correction matters more than the numbers.** An earlier
version of this table reported 88,431 clauses, 128,060 sentences, 39,629 discarded, 3.5% of
words lost and 3,519 zero-contribution turns. Those came from a scratchpad script that loaded
spaCy with `tagger`, `attribute_ruler` and `lemmatizer` disabled for speed -- **which moves
where sentence boundaries fall**, so the pool count was inflated by ~20%. The production
segmenter loads the full pipeline. The figures above now come from the harness itself, running
production `build_client_pool`, and 73,771 matches the "74k-clause pool" CLAUDE.md already
recorded -- so CLAUDE.md was right and the scratchpad was wrong.

The content-free *ratio* survived almost exactly (58.9% -> 59.1%), which is why the
qualitative finding stands: nearly 6 in 10 pool items carry no subject. **The lesson is to
never disable spaCy components in a measurement script whose output will be compared against
production**, and to prefer a harness that imports production code over a convenience script.

Still to re-measure with the full pipeline (all previously quoted values are withdrawn):
sentence count, discarded-sentence count, share of client words lost, and the number of CLIENT
turns contributing nothing at all. The last of these is the one that matters, because it sizes
how much *extra* evidence turn mode hands the backchannel sink.

The most repeated content-free clauses are the posture cluster members -- `'how are you?'`,
`"i don't know."`, `'oh, yeah.'`, `'that sounds good.'`, `'that makes sense.'`. (Per-string
counts are withheld pending the full-pipeline re-measurement; the strings themselves are not in
doubt, the tallies came from the degraded script.)

Discarded turns are not all noise: `'Yeah. About 15.'` (a quantity answer) and `'In Toronto?'`
(a market question) are dropped before the taxonomy is built.

**Ranking the two defects honestly: separation is the cause, dropping is secondary.** Only a
few percent of client words are lost outright, and the posture piles come from tearing stance
away from subject in the large majority that IS kept. The exact loss share is pending
re-measurement, but it cannot change this ranking: the fix's value is in keeping stance and
subject together, not in recovering discarded text.

## The goal is niche posture, NOT no posture

Posture is coaching-relevant -- handling a denial differs from handling a question. The defect
is that posture arrives **with the subject stripped off**: `client_direct_denial` is too
coarse, not too niche, holding a Thanksgiving aside beside a knockout-question requirement.

Target grain: `"client denies having budget this quarter"`, not `"client denies"` and not
`"budget"`. A turn carries stance and subject together, which is what makes that grain
reachable.

**Splitting is what makes posture coarse. Not splitting is what makes it niche.** The intuition
runs the other way round and it is worth stating explicitly.

## Design

### 1. What changes

New tuning key **`layer_a.pool_unit: clause | turn`**, shipped **`clause`** so production is
byte-identical until flipped -- the established pattern (`describe_mode: legacy`,
`sink_rescue_strategy: none`, `embedding.backend: local`).

`build_client_clause_pool` -> `build_client_pool(all_turns, unit, min_content_words=0)`. In
`turn` mode it emits one item per CLIENT turn (`turn.text`) with the identical
`(texts, call_ids)` contract, so every distinct-call evidence check keeps working. Production's
call site passes `tuning.pool_unit`.

Everything downstream of the pool is **untouched**: `fit_topic_model`, `_raw_topic_data`, the
merge, `triage`, adjudication, `_finalize_primary_topics`. The pool is the only variable.

**`preprocessing/segmenter.py` is not modified.** It is shared -- `v2/layer_a.py:36` and
`v2/layer_c.py:77`, documented at `ARCHITECTURE.md:172`. Changing the `< 4` cutoff would
silently rewrite Layer C's milestone clause pool and move the 385-milestone baseline. In `turn`
mode Layer A stops calling it, so Layer C's caller has a zero diff. `tests/test_segmenter.py`
passing unchanged is the proof.

### 2. Threshold re-derivation is mandatory

`merge_cosine_threshold: 0.85` and `ubiquity_ceiling: 0.60` were calibrated against clause
centroids and they interact (merging unions call sets, raising coverage). Turn-level cosines
live in a different band, and CLAUDE.md forbids borrowing a floor across bands. Re-derive with
`--sweep`, and validate by **reading the groups** via `--merge-detail`, never by cluster count
(at 0.80 it once fused campaigns + sales team + brand + markets).

`min_cluster_size` needs no change: `max(3, min(n // 10, 50))` = **50** at both units
(n//10 = 2,890, still capped). Measured, not assumed.

### 3. Validation and the gate

Four arms, **all free** -- zero Gemma, zero writes: `clause`, `clause+prefilter`, `turn`,
`turn+prefilter`. `--prefilter` already exists.

**Symmetry rule.** Today's 21/68 scored clause-formed scenarios using *turn* vectors from
`kb_pairs.trigger_text`. Comparing that directly to a turn arm counts the unit change twice --
the asymmetric-comparison bug this codebase has hit four times. Each arm is scored on its
**own native members** against a null drawn from **that same unit population**, so
lift-over-null is unit-normalised. Consequence accepted up front: **the clause arm's native
baseline will not be 31%**, and the 31% figure is retired as a cross-unit artifact rather than
treated as the bar to beat.

The coherence + null test moves into the harness as a reusable function, not a scratchpad
one-off.

#### The gate -- four checks, ALL required

1. **>= 50% of coachable clusters holding >= 8 members** clear their size-matched null by
   >= 0.05. The denominator is the **rankable** population, matching the 21/68 baseline --
   clusters below 8 members have no stable centroid and are reported separately, never folded
   silently into either half.
2. **The backchannel sink still forms**, so Layer D's rejection survives. Pre-checked as
   likely: 3,961 client turns are <= 3 words, and a re-measurement of how many turns currently
   contribute nothing at all is pending (see the corrected supply table) -- turn mode gives
   the sink *more* evidence than today either way, since a backchannel-only turn produces no
   clause but is always one turn-mode item.
3. **10 sampled clusters read as situations.** Sampling is **seeded and stratified over the
   coherence range, never the first N** -- an alphabetical prefix once returned nothing but
   subject-matter scenarios because every posture key begins `client_`, silently testing a fix
   on the half that already worked.
4. **Stance distinguishability** (added after check 1 was shown insufficient -- see below).

**Abandon if** the sinks vanish, or the samples read badly, **regardless of the number**.

#### Why check 4 exists

Under turn-level clustering the topic words may outweigh the stance words, so
*"No, we don't have budget"* and *"Tell me more about budget options"* collapse into one budget
cluster. That is the same "rubric is an average" failure rotated 90 degrees: today we average
across topics within one posture; pure-topic clustering would average across postures within
one topic.

**Checks 1-3 cannot catch it -- check 1 rewards it.** A pure-topic cluster is maximally
homogeneous and scores *better* on coherence. Same defect class as the skills sweep, where
`cross_scenario_coverage` could only ever say yes and needed merge-validity as a counterweight.
A metric that only counts the good outcome is not a gate.

Check 4, free and quantitative. Mark each turn as negated using spaCy's **`neg` dependency
label** -- a parser output, not a hand-written word list, so it stays clear of the "never a
curated list" rule. Verified against real phrasing: `"No, we don't have budget for that this
quarter."` -> True (`n't`), `"That's not going to work for us."` -> True (`not`),
`"Tell me more about the budget options."` -> False, `"Yeah, that works for us."` -> False.

Then test whether negated turns are **concentrated** in some clusters (stance captured -- the
goal) or **spread evenly** across them (stance ignored -- collapsed to pure topic), against a
**shuffled baseline** so "evenly spread" has a real null.

**Stated limit: `neg` detects syntactic negation, which is a subset of pushback.**
`"We already have an ATS in place."` is a refusal in substance and carries no `neg`. That is
acceptable here because the check is distributional -- it asks whether *some* stance signal
survives clustering, not whether every instance is caught -- and because it is a measurement
instrument rather than a production threshold. A curated marker list would be forbidden as a
shipped knob; a parser-derived proxy used once, to read a distribution, is not.

The sample read in check 3 additionally asks per cluster: *does this mix a flat refusal and an
eager question about the same topic?*

### 4. Cost and blast radius

Free: all four arms, both nulls, the merge re-derivation, the sample reads. ~24k of the 28,905
turns are cold in `embed_cache.db` (only ~4,605 exist as `kb_pairs` triggers) -- GPU minutes,
no API cost. **The whole decision is reachable for nothing.**

Paid only after the gate, order-of-magnitude against documented runs: Layer A adjudication
~160 calls (first V2 run: 158), primary-topic labelling ~16-30, Layer C ~100-200, Layer D
re-score ~230 over 100 transcripts. Several hundred total.

What dies:

1. **Every `scenario_key` changes** -- Gemma renames per run. Compare by size signature
   (`support_calls` / `call_coverage`), never by key.
2. **The 385-milestone Layer C baseline is invalidated** -- new scenario vectors, new
   relevance-filtered pools, different clusters.
3. **Every `milestone_performance` row is orphaned** -- `milestone_id` is the array position.
4. **`gap_events` must be cleared** -- SERIAL PK appends duplicates, and
   `upsert_milestone_performance` increments `attempts` on conflict.

Mandatory order before any paid run:

```text
1. Check the OS for live runs   Get-CimInstance Win32_Process ... -match 'run_ego_trap'
                                (a harness "stopped" report is NOT evidence)
2. Snapshot public/             CREATE SCHEMA turn_pool_before_20260814;
                                CREATE TABLE <s>.<t> AS SELECT * FROM <t>;
                                calls / scenarios / kb_pairs / rubrics
3. python ops/clear_data.py     Postgres + checkpoints. NOT optional -- run_id hashes the
                                transcript stems, so skipping it yields a no-op run
4. python ops/clear_ego_trap_data.py
5. KEEP embed_cache.db          deleting it re-embeds and changes cluster counts
```

**Interpretation limit:** Layer A geometry is reproducible on a warm cache but its coachability
adjudication is not -- 78 vs 85 coachable for identical clusters, ~5-6% flipping, never
root-caused. Read the comparison at the size-signature level; small per-scenario differences
are not attributable to the unit change.

### 5. Tests

TDD -- tests first.

`tests/test_layer_a_pool.py` (new), hand-built `Turn` fixtures:

| test | pins |
| --- | --- |
| turn mode emits one item per CLIENT turn, in order, correct `call_id` | the core contract |
| non-CLIENT turns skipped in both modes | role filtering |
| clause mode output unchanged from today | **the default path is provably byte-identical** |
| a turn of only `"Yeah."` yields an item in turn mode, nothing in clause mode | **sink preservation** |
| `min_content_words` still applies when passed | the `--prefilter` path |
| unknown `unit` value raises | loud failure, matching the loader's contract |

`tests/test_tuning.py` -- extend for `layer_a.pool_unit`: present in both `tuning.yaml` and the
`LayerATuning` dataclass, unknown value raises at load.

Coherence + null as **pure functions** on hand-built orthogonal unit vectors, the way
`test_layer_b_assignment.py` does, so they test the rule not the embedder: identical vectors ->
1.0; orthogonal -> ~0; a tight set beats a random set; the null shifts with `n`.

Run **file-by-file** -- four test files load spaCy's 392MiB vector table and the suite dies on
16GB Windows from address-space fragmentation, not free memory:

```bash
for f in tests/test_*.py; do ../.venv/Scripts/python.exe -m pytest "$f" -q; done
```

Beyond unit tests: `py_compile` the changed files (never verify by importing); smoke the
harness end to end on a tiny sample first (two prior full launches died mid-generation on a
missing import and a positional slice, and `py_compile` catches neither); and **regression
check with teeth** -- run the dry run at `pool_unit: clause` on a warm cache and confirm it
reproduces the documented **237 raw -> 171 -> 158**. If that does not reproduce, the turn arm's
numbers mean nothing.

## Explicitly out of scope

Kept out to preserve single-variable attribution:

- `v1/layer_b.extract_pairs` -- has the same stopping-rule bug (443 pairs lost outright,
  earlier substantive turns dropped from 1,316 more).
- Layer D signal segmentation -- the 98.6% artifact.
- Promoting `client_blocks` / `last_speaker_move` from
  `calibration/trial_client_move_arms.py` into `shared/`. The client-move definition is already
  derived and measured; if turn-level works, move-level is the natural follow-up.
- Enabling `layer_a.min_content_words` -- would move a second variable.
- The `"Indeed"` stopword bug -- and note it **blocks** calibrating any content-word floor,
  therefore blocks Approach C below.
- **Approach C** (chunk long turns into topic-bearing pieces that each keep their stance).
  Likely the real answer given the niche-posture goal, but it needs a calibrated floor and the
  stopword fix first. Its trigger is check 4 or the 5,099 long turns measuring badly.

## Findings recorded elsewhere, not fixed here

- `'indeed' in spacy.Defaults.stop_words` is `True` (both cased forms), while `ZipRecruiter`
  and `Greenhouse` are not -- so both substantive filters delete a major job board's name, and
  `layer_b._is_substantive` is **live** and gates every pair into `kb_pairs`. Recorded in
  CLAUDE.md. The obvious fix (whitelist domain terms) is the "never a curated list"
  anti-pattern, so it needs a different substantive test.
- `layer_a.min_content_words: 5` is **inert** in production -- the call site passes no
  argument, so the `0` default wins; only `dry_run_layer_a.py --prefilter` honours it. Recorded
  in CLAUDE.md.
- **Discrepancy RESOLVED 2026-08-14, in CLAUDE.md's favour.** An earlier draft of this spec
  measured 88,431 clauses against CLAUDE.md's recorded "74k-clause pool". The harness, running
  production code, gives **73,771** -- CLAUDE.md was correct. The 88,431 came from a scratchpad
  script with spaCy components disabled, which shifts sentence boundaries. See the corrected
  supply table above.

---

## Status update (2026-08-14): first run. Two gate checks were WRONG, and the run found them

Harness `calibration/trial_pool_unit.py`. Artifacts `artifacts/pool_unit_clause.json`,
`pool_unit_turn.json`. Logs `logs/trial_pool_unit_{clause,turn}.log`.
**Zero Gemma calls, zero DB writes.** Implementation ships OFF (`pool_unit: clause`).

### The regression check passed exactly

The clause arm reproduced **237 raw -> 171 merged**, byte-identical to the documented
production geometry (237 -> 171 -> 158). So `build_client_pool` is behaviour-preserving in
clause mode against production's own recorded numbers, not merely against unit tests, and the
harness reproduces the production clustering path.

### Measured

| | clause (control) | turn (treatment) |
| --- | --- | --- |
| pool items | 73,771 | 23,949 |
| **content-free items** | **43,566 (59.1%)** | **7,856 (32.8%)** |
| raw clusters | 237 | 74 |
| HDBSCAN noise | 45.2% | 51.0% |
| surviving clusters | 171 | 38 |
| clusters >= 70% content-free | 98 of 171 (57%) | 19 of 38 (50%) |
| negated items | 15.4% | 31.6% |
| **stance ratio (check 4)** | **63.86** | **66.75** |

**The design's core prediction holds, at the pool level, and it is the one result here that no
threshold artifact can touch:** content-free items fall **82% in absolute terms**, 43,566 ->
7,856. This is computed before any clustering or merging, so it is independent of every knob
below.

**Check 4 passed and the risk it was added for did not materialise.** Stance ratio 66.75 vs
63.86 -- turn mode captures stance slightly BETTER than clause mode, so turn-level clustering
did not collapse into pure-topic groups. The 90-degree-rotated "rubric is an average" failure
this check was invented to catch is not happening.

### CHECK 1 IS RETIRED. It rewards exactly the clusters we are trying to remove

Measured across the control arm's 171 clusters:

    corr(lift-over-null, content-free fraction) = +0.527

| | clusters | mean lift |
| --- | --- | --- |
| >= 70% content-free (junk) | 98 | **+0.160** |
| < 70% content-free (real) | 73 | **+0.107** |

The junk clusters score **50% higher on the gate metric**. Reading them makes the mechanism
obvious -- the clause taxonomy is largely piles of ONE WORD: `forward, moving forward` (540
items, 72% content-free, lift +0.074), `look, looking, seen` (517, 80%, +0.108), `big, huge,
biggest` (76, 82%, +0.123), `helpful, really helpful` (309, 73%, +0.140), and a 98%
content-free cluster at **+0.195** -- while the genuine `city, country, state, location`
cluster scores the LOWEST of the ten sampled, +0.055.

A pile of "that's huge" is lexically tighter than a real discussion of markets. Lift-over-null
measures lexical homogeneity, which is what HDBSCAN optimises for, so at CLUSTER level it
asks "did the clustering algorithm run" rather than "is this a situation". **It is the same
defect the spec above warns about in check 1's own justification -- a metric that can only say
yes -- and it was in the gate anyway.**

**This does NOT retire the scenario-level 21/68.** There the members are whole TURNS, which are
lexically diverse; posture scenarios failed to clear their null DESPITE the metric favouring
lexically-tight groups, so the bias runs against that finding rather than producing it.

### The cluster counts are NOT interpretable: two asymmetries, both mine

**1. `merge_cosine_threshold: 0.85` was not re-derived**, though Section 2 above says it is
mandatory. Clause collapsed 237 -> 171 (-28%); turn collapsed 74 -> 38 (-49%) at the same
threshold, because turn-level cosines sit in a higher, tighter band (trigger-vs-trigger
p50=0.689 vs trigger-vs-scenario p50=0.550).

**2. `min_cluster_size` differed by 3x in RELATIVE terms, which is worse.**

| arm | pool | min_cluster_size | as a share of the pool |
| --- | --- | --- | --- |
| clause | 73,771 | 50 | **0.068%** |
| turn | 23,949 | 50 | **0.209%** |

`fit_topic_model`'s formula is `max(3, min(n // 10, 50))`, and the `n // 10` term is capped at
50 for any corpus of >= 500 items -- **so in production it is a hardcoded COUNT of 50**, the
"a threshold must never be a count of outputs" anti-pattern, sitting in the clustering call
itself. The consequence for this trial is that "turn mode finds only 74 clusters" substantially
measures the bar, not the pool. Scale-matched value: 50 x 23,949/73,771 = **16**.

`fit_topic_model` now takes an optional `min_cluster_size` (default `None` = legacy formula, so
production is unchanged) and the harness takes `--min-cluster-size`. A scale-matched turn arm
at 16 is running; until it lands, treat every cluster-count row above as provisional.

### Corrections to this spec's own earlier numbers

Two scratchpad scripts disagreed with production, both by omitting something the production
path uses:

- spaCy loaded with `tagger`/`attribute_ruler`/`lemmatizer` disabled **moves sentence
  boundaries**: 88,431 clauses vs the true 73,771 (+20%).
- `parse_transcript` called without the Avoma **roster** argument misclassifies speakers:
  28,905 CLIENT turns vs the true 23,949 (+21%). The roster resolves roles from real
  per-meeting `is_rep`/email data; the name-list is only a fallback.

Everything derived from those two scripts is withdrawn (sentence counts, discarded-sentence
counts, share of words lost, turns contributing nothing, per-string tallies, the words-per-turn
distribution, and the 3,961 / 5,099 turn-length counts). **The rule this yields: a measurement
script must call the production entry point with the production arguments, or its numbers are
not comparable to production's.** Both errors inflated by ~20% and neither was visible without
a production-code cross-check.

---

## Status update 2 (2026-08-14): the scale-matched run. Turn mode wins on the measure that matters

Artifact `artifacts/pool_unit_turn_scaled.json`, log `logs/trial_pool_unit_turn_scaled.log`.
Turn arm re-run at `--min-cluster-size 16` (0.067% of its pool, matching the clause arm's
0.068%). Still zero Gemma, zero DB writes.

### The "turn mode finds fewer clusters" result is WITHDRAWN -- it was my asymmetry

| | clause | turn @50 (unfair) | turn @16 (matched) |
| --- | --- | --- | --- |
| raw clusters | 237 | 74 | **246** |
| HDBSCAN noise | 45.2% | 51.0% | 48.9% |
| after merge @0.85 | 171 | 38 | 114 |

At matched relative granularity turn mode finds **slightly MORE** raw clusters than clause mode
(246 vs 237), not a third as many. The taxonomy is not coarser. The remaining post-merge gap
(114 vs 171) is attributable to `merge_cosine_threshold: 0.85` collapsing turn centroids nearly
twice as hard (-52% vs -28%) because turn-level cosines sit in a higher, tighter band -- the
re-derivation Section 2 already flagged as mandatory and which is still pending. **114 is
therefore a lower bound, with 246 as the ceiling.**

### The measure that matters, and it is not any of the four original checks

| | clause | turn |
| --- | --- | --- |
| **subject-bearing clusters** (<30% content-free) | **8 of 171 (5%)** | **37 of 114 (32%)** |
| items those clusters cover | 2,181 | 5,626 |
| their mean negation rate | 17.7% | **40.3%** |
| junk clusters (>=70% content-free) | 98 (57%) | 50 (44%) |
| **corr(negation rate, content-free fraction)** | **-0.149** | **-0.744** |

**Subject-bearing clusters go from 8 to 37 -- 6.4x more.** Reading them is what makes the
result legible. The clause taxonomy's clusters are piles of one word (`forward, moving
forward`; `look, looking, seen`; `big, huge, biggest`; `helpful, really helpful`). The turn
taxonomy's are named subject matter:

| turn cluster | items | content-free | negation |
| --- | --- | --- | --- |
| `field, fields, mapping, application fields` | 172 | 7% | 44% |
| `ats, atss, ats integration, isims` | 40 | 15% | 32% |
| `ukg, pro, recruiting module, unify` | 17 | 12% | **53%** |

**`corr(negation, content-free) = -0.744` is the design's stated goal expressed as a number.**
In turn mode the subject-bearing clusters are precisely the ones carrying stance -- subject and
posture travel together, which is the `"client denies having budget this quarter"` grain this
spec set as the target. In clause mode the same correlation is -0.149: stance and subject are
divorced, which is the defect.

### Gate verdict against the four pre-registered checks

| check | result |
| --- | --- |
| 1 -- share clearing the null | **RETIRED, not failed.** Broken in BOTH arms (corr with content-free +0.527 clause, +0.555 turn) |
| 2 -- backchannel sink still forms | **PASS.** 50 sinkish clusters, largest 667 items. Layer D's rejection mechanism survives |
| 3 -- samples read as situations | **PASS**, and it is the strongest evidence here. See the named clusters above |
| 4 -- stance distinguishability | **PASS.** Both arms far above 1 (63.86 / 26.15), so no collapse to pure topic |

**Caveat on check 4's cross-arm comparison:** the ratio's null depends on the cluster-size
distribution, which differs between arms, so the two ratios are not cleanly comparable to each
other. What is sound is that both are far above 1. The clean cross-arm stance number is the
negation/content-free correlation above, which needs no null.

**Recommendation: turn mode is supported by the evidence, and it is still NOT adopted.**
`pool_unit` stays `clause`. Two things must happen first -- re-derive `merge_cosine_threshold`
for the turn band (free, in progress), and note that everything measured here is PRE-Gemma.
Whether these clusters become better SCENARIOS depends on adjudication, which costs ~160 calls
and a full re-run. The 5% -> 32% subject-bearing shift is the strongest pre-Gemma signal this
effort has produced, but it is not the same thing as a better rubric.

---

## Status update 3 (2026-08-14): merge threshold re-derived. 0.92 is turn's equivalent of 0.85

Log `logs/merge_detail_turn.log`. Run as
`dry_run_layer_a.py --pool-unit turn --min-cluster-size 16 --merge-detail 0.85,0.88,0.90,0.92`.
Zero Gemma, zero writes. `--min-cluster-size` was added to `dry_run_layer_a.py` too, because the
first attempt swept thresholds on the UNFAIR 74-cluster clustering and had to be killed.

| threshold | groups from 246 raw | collapse | clause arm for reference |
| --- | --- | --- | --- |
| 0.85 | 118 | -52% | 237 -> 171 = -28% |
| 0.88 | 148 | -40% | |
| 0.90 | 174 | **-29%** | closest match on COUNT |
| **0.92** | **198** | -20% | **the answer, by READING** |

**Count-matching picked 0.90 and reading proved it wrong -- a direct vindication of this
codebase's "validate a merge threshold by reading the groups, never by counting" rule.**

At 0.90 one group fused 6 raw clusters / 560 items spanning `sales, role, team` +
`linkedin, ziprecruiter` + `discovery, kickoff, rfp` + `advertising, social, ads` +
`programmatic, crm` + `employer branding, audience` -- six distinct business topics in one
blob. That is precisely the failure `merge_cosine_threshold`'s original calibration recorded at
clause-level 0.80 ("fused campaigns + sales team + brand + markets + vendors"), reappearing one
band up.

At 0.92 that blob splits correctly while the backchannel families still unify:

| merge | members | verdict |
| --- | --- | --- |
| 14 -> 1 | `yeah / yep / correct` (540 items) | correct -- the family this mechanism exists for |
| 8 -> 1 | `okay / alright` (315 items) | correct |
| 2 -> 1 | `api, integration` + `custom apis, endpoints` (256) | correct, one topic |
| 3 -> 1 | `linkedin, ziprecruiter` + `advertising, social, ads` + `employer branding` (243) | coherent: paid media and branding |
| 3 -> 1 | `sales, role, team` + `discovery, kickoff, rfp` + `programmatic, crm` (317) | coherent: stakeholder and process discovery |

**So the turn-band value is 0.92, and it must NOT be written into `tuning.yaml` yet** -- there is
one `merge_cosine_threshold` key and it is correct at 0.85 for the shipped `clause` unit.
Changing it would break production while `pool_unit: clause` is live. If turn mode is ever
adopted, the two move together, and that coupling should be enforced rather than remembered.

**Revised turn-mode taxonomy size: 198 groups pre-triage** (vs the clause arm's 171), from 246
raw clusters. The earlier 114 was the artifact of an un-re-derived threshold, and "turn mode
produces a coarser taxonomy" is now withdrawn twice over -- once for `min_cluster_size` and once
for this.

---

## Pre-registration for the 0.92 re-run (written BEFORE the result)

The turn arm's trial numbers were produced at `merge_cosine_threshold: 0.85`, the value derived
by reading CLAUSE-level merge groups. Status update 3 derived turn's own equivalent as **0.92**.
Re-running at 0.92 with the result already known for 0.85 is the shape of a tuned result, so the
expectations and the stopping condition are fixed here first.

**Why this is not threshold-shopping.** 0.92 was selected by reading merge groups -- the same
method that produced 0.85 for clause mode -- and BEFORE any trial was run at it. Each arm at its
own independently derived value is the SYMMETRIC comparison; running both at 0.85 was the
asymmetric one. The mechanism at 0.85 is documented and specific: a single group fused **15 raw
clusters / 965 turns / 225 calls (54% coverage)** spanning healthcare nursing, Raytheon
engineering, campus ambassadors, employer branding, RFP process, LinkedIn/ZipRecruiter, CRM,
programmatic, conversion rate and specialty sites. At 0.92 that same group is 3 raw / 317 items.

**Expected to improve:**

- subject-bearing clusters (<30% content-free), currently **37 of 114 = 32.5%**
- the largest cluster no longer containing 15 topics
- per-cluster "empty" percentages generally, since the blob averaged filler into clean topics

**Expected to possibly WORSEN, and will be reported if so:**

- more, smaller clusters means some may now fail the distinct-call support gate (118 merged ->
  114 surviving at 0.85)
- the junk SHARE (44%) may hold or rise -- splitting a blob does not remove backchannel clusters

**Stopping condition.** If subject-bearing share comes out lower at 0.92, that is the finding and
it gets reported as such. **No third threshold will be swept.** One independently derived value,
one run.

**Caveats that survive either outcome:** everything here is PRE-Gemma and measures the material
rather than the rubrics; and the content-free proxy still contains the `"Indeed"` stopword bug,
which overstates emptiness equally in both arms.

**Comparison baseline, so the right numbers are contrasted:**

| measure | live production | turn mode |
| --- | --- | --- |
| Gemma calls it coachable | 85 of 161 = 52.8% | pre-Gemma, N/A |
| beats a random null (scenario level) | 21 of 68 = 31% | pre-Gemma, N/A |
| **subject-bearing clusters (pre-Gemma, like-for-like)** | **8 of 171 = 4.7%** | **37 of 114 = 32.5% @0.85** |

Note the first two rows disagree by design: Gemma labels 52.8% coachable while only 31% of the
rankable ones beat a random pile of client turns, so the coachable label is materially more
optimistic than the evidence supports.

---

## Status update 4 (2026-08-14): the 0.92 run. Every pre-registered expectation met

Artifact `artifacts/pool_unit_turn_092.json`, log `logs/trial_pool_unit_turn_092.log`.
Turn arm at its own derived threshold (0.92) and scale-matched granularity
(`--min-cluster-size 16`). Zero Gemma, zero writes.

| | clause @0.85 | turn @0.85 | **turn @0.92** |
| --- | --- | --- | --- |
| surviving clusters | 171 | 114 | **191** |
| **subject-bearing (<30% content-free)** | **8 (4.7%)** | 37 (32.5%) | **71 (37.2%)** |
| junk (>=70% content-free) | 98 (57.3%) | 50 (43.9%) | **78 (40.8%)** |
| subject clusters' mean negation | 17.7% | 40.3% | **43.2%** |
| largest cluster | 2,209 items | 965 items | **568 items** |

**Against the pre-registration, which was written before this ran:**

| pre-registered | expected | actual |
| --- | --- | --- |
| subject-bearing share | improve on 32.5% | **37.2%** PASS |
| largest cluster no longer 15 topics | | 568 items, ONE topic PASS |
| support-gate losses may worsen | risk | 7 of 198 dropped vs 4 of 118 -- proportionally flat, no |
| junk share may hold or rise | risk | 43.9% -> **40.8%**, improved, no |

Both flagged downside risks failed to materialise. Nothing here was selected after the fact.

**The single clearest row in this whole effort** is the two arms' largest clusters, which are the
SAME SUBJECT:

| arm | largest cluster | items | calls | content-free |
| --- | --- | --- | --- | --- |
| clause | `budget, spend, cost, money` | 2,209 | 309 (74% of corpus) | **45%** |
| turn @0.92 | `spend, budget, cost, month` | 568 | 189 (45%) | **10%** |

Same topic. Clause mode's version is 4x bigger, nearly half filler, and appears in three quarters
of all calls -- a bucket that broad cannot support a specific coaching criterion. Turn mode's is
a quarter the size, a tenth filler, and appears in a plausible minority of calls.

**Check 4's ratio fell (63.86 clause vs 16.22 turn@0.92) and that is NOT a regression.** The
null rises as clusters get smaller and more numerous, so the ratio is not comparable across
arms with different cluster-size distributions -- stated in Status update 2 and still true. Both
remain an order of magnitude above 1, so stance survives clustering in both. The clean cross-arm
stance measure is the negation/content-free correlation (-0.149 clause vs -0.744 turn), which
needs no null.

### Outstanding: is this the UNIT or just the THRESHOLD?

0.92 improved the turn arm. If raising the threshold also improves the CLAUSE arm by a similar
amount, then the result is about the merge threshold and not about the pool unit at all. That
control is running now -- both arms swept across 0.85/0.88/0.90/0.92/0.94/0.95 via a new
`--merge-sweep` (one clustering pass, many thresholds; skips the retired null so it is cheap).

**The sweep is DESCRIPTIVE.** 0.92 remains the adopted value because it was derived by reading
merge groups before any trial ran at it. Picking the best-looking row from a sweep is the
tuned-result failure this spec's pre-registration exists to prevent, and the user's permission to
"run more thresholds" does not change that -- it buys a robustness curve, not a new headline.

---

## Status update 5 (2026-08-14): the control sweep. The gain is the UNIT, not the threshold

Artifacts `artifacts/sweep_clause.json`, `artifacts/sweep_turn.json`. Logs
`logs/sweep_{clause,turn}.log`. One clustering pass per arm, six merge thresholds each, via the
new `--merge-sweep`. Zero Gemma, zero writes.

**The question this answers:** 0.92 improved the turn arm. If raising the threshold improves the
CLAUSE arm equally, the result is about the threshold and turn mode contributes nothing.

| merge | clause surviving | clause subject-bearing | turn surviving | turn subject-bearing |
| --- | --- | --- | --- | --- |
| 0.85 | 171 | 8 (**4.7%**) | 114 | 37 (**32.5%**) |
| 0.88 | 205 | 14 (6.8%) | 142 | 51 (35.9%) |
| 0.90 | 221 | 16 (**7.2%** peak) | 167 | 63 (**37.7%** peak) |
| 0.92 | 231 | 16 (6.9%) | 191 | 71 (37.2%) |
| 0.94 | 235 | 16 (6.8%) | 206 | 77 (37.4%) |
| 0.95 | 236 | 16 (6.8%) | 208 | 77 (37.0%) |

**The bands never overlap at any threshold.** Clause peaks at 7.2% and never exceeds it; turn
never drops below 32.5%. At the IDENTICAL threshold 0.92 the gap is 6.9% vs 37.2% -- **5.4x**.
The gain is attributable to the pool unit, not to the merge threshold.

**Clause mode's ceiling is structural.** From 0.85 to 0.95 it gains 65 clusters (171 -> 236) and
the subject-bearing count freezes at **16**. Every new cluster is junk, its junk share never
leaves 57-59%, and its 2,209-item `budget, spend, cost` cluster is unchanged at every threshold
-- merging can fuse, it can never split, so no threshold can repair an over-broad cluster.

**Turn mode plateaus 0.90-0.94 (37.7 / 37.2 / 37.4).** The conclusion is not knife-edge on
hitting 0.92 exactly. Turn's junk share is best at 0.88-0.90 (40.1%) and drifts up slightly
after, so 0.92 is not even this sweep's optimum -- which is the point: it was derived by reading
merge groups beforehand, not selected from this table.

**Reproducibility note:** the 0.92 sweep row (191 surviving / 71 subject-bearing / 78 junk)
reproduces the independent headline run exactly. At 0.85 the largest merge group held 18 raw
clusters here vs 15 in the earlier `--merge-detail` run -- the documented UMAP cross-process
variance, worth about +/-3 on cluster-composition counts.

### A false positive in the subject-bearing metric, found by reading

`jovio, jovia, jovio team` -- **563 items across 208 calls (50% of the corpus), only 4%
content-free, 45% negation** -- survives at 0.92 and is counted as SUBJECT-BEARING. Reading it
shows it is not one situation: intros at Travis Perkins, payment terms, a general performance
review. It is a lexical cluster on **the company's own name**.

**This is a real limitation of the content-free proxy: it cannot detect a cluster of
substantive-but-unrelated turns.** Every "subject-bearing" count in this spec therefore contains
some unknown number of these. The turn arm's 37.2% is an upper bound on genuinely coherent
clusters, exactly as the clause arm's 4.7% is. It does not change the comparison -- both arms are
measured with the same flawed proxy -- but it does mean the absolute figures should not be quoted
as "N coherent scenarios".

A corpus-ubiquitous proper noun gathering its own cluster is a DIFFERENT failure from the
posture problem this spec addresses, and it is not fixed by the unit change.

---

## Status update 6 (2026-08-14): adjudication spot-check. The main risk does NOT reproduce

Harness `calibration/spot_check_adjudication.py`, artifact `artifacts/spot_check_adjudication.json`.
**~8 Gemma calls, zero DB writes.** Calls production `layer_a._adjudicate` directly.

**The risk tested.** Turn mode reduces obvious junk but may create INVISIBLE junk. In clause mode
a junk cluster is 98% "yeah yeah" and Gemma rejects it trivially. `jovio, jovia, jovio team` is
563 substantive-looking turns across 50% of the corpus at only **4% content-free**, glued together
by the company's own name. If Gemma accepts that as coachable, turn mode has traded obvious junk
for camouflaged junk.

Eight clusters, hand-picked, with the expected verdict written down BEFORE the call. Controls in
both directions, so an all-sink or all-accept outcome would report itself as uninformative.

| cluster | expected | Gemma's decision | agree |
| --- | --- | --- | --- |
| `spend, budget, cost` | scenario | `new_scenario` -> `budget_and_spend_constraints` | yes |
| `pixel, javascript` | scenario | `new_scenario` -> `pixel_and_s2s_integration_requirements` | yes |
| `landing, landing page` | scenario | `new_scenario` -> `landing_page_microsite_management` | yes |
| `chatbot, ai` | scenario | `new_scenario` -> `chatbot_capabilities_and_integration` | yes |
| **`jovio, jovia`** | **sink** | **`mechanics`** -> `joveo_team_introductions_and_housekeeping` | **yes** |
| `yeah yeah` | sink | `mechanics` | yes |
| `okay okay` | sink | `mechanics` | yes |
| `sales, years, role` | sink | `new_scenario` -> `enterprise_stakeholder_and_role_context` | no |

**7/8, and the probe passed.** Gemma's reason for sinking `jovio`: *"These utterances primarily
consist of conversational introductions, participant coordination, meeting housekeeping, and casual
references to Joveo team members."* Correct and specific.

**Why it worked, and it was already designed for:** `PROMPT_LAYER_A_V2_TRIAGE` says *"Judge the
utterances, not the keywords."* The keywords (`jovio, jovia, jovio team`) read like a topic; the
utterances reveal housekeeping. It also caught this WITHOUT the coverage warning -- at 50% coverage
`jovio` sits below `ubiquity_ceiling: 0.60`, so it was never flagged. The defence existed; it had
never been tested against junk that looks substantive, because clause mode never produced any.

**The one disagreement is probably MY label, not Gemma's error.** I expected `sales, years, role`
sunk because at 0.85 it fused careers + RFP + programmatic. At 0.92 it is a tighter 317-item
cluster and Gemma read it as *"enterprise clients defining their internal organizational structure,
stakeholder responsibilities, and long-term tenure"* -- defensible, and `stakeholder_role_*` is a
real scenario from earlier production runs.

### Unplanned finding: the posture x subject grain arrives at ADJUDICATION, not clustering

The scenario descriptions Gemma wrote carry stance AND subject together:

- `budget_and_spend_constraints` -- *"clients expressing **hesitation or constraints** around
  marketing spend, budget allocation, and ROI justification"*
- `chatbot_capabilities_and_integration` -- *"clients **asking about** the technical capabilities,
  customization options, and ATS integration limits"*
- `enterprise_stakeholder_and_role_context` -- *"enterprise clients **defining** their internal
  organizational structure"*

**5 of 5 accepted clusters produced a definition combining posture and subject.** This spec earlier
concluded the grain was NOT achieved, having looked only at clusters (subject-only, mixed stance
inside). That was the wrong place to look: given whole turns, Gemma writes the stance into the
description itself. It cannot do that from fragments -- `"That makes sense."` x630 offers nothing to
describe but the stance alone, which is exactly how `client_expresses_uncertainty` is produced.

n=5, hand-picked. Encouraging evidence, not proof.

**Deviation from production, stated:** `accepted` was empty throughout, so no nearest-neighbour
context was supplied. Production gives MORE context, which makes a sink verdict here strong
evidence and an accept verdict partly confounded.

---

## CONCERNS REGISTER (wordings preserved verbatim from the 2026-08-14 verdict)

Status as of 2026-08-14, after the spot-check and before the long-turn probe completed.

### Resolved

| concern (verbatim) | status |
| --- | --- |
| Posture clusters are near-random | **Resolved.** Real clusters 4.7% -> 37.2%; junk 57% -> 41% |
| Would we lose the client's attitude? | **Resolved.** Stance couples *more* tightly to subject (-0.744 vs -0.149) |
| Would Layer D lose its junk bin? | **Resolved.** 78 sink clusters, largest 540 items |
| Would the taxonomy get coarser? | **Resolved.** 246 vs 237 raw; 191 vs 171 final |
| Is it just the threshold? | **Resolved.** Bands never overlap at any threshold |
| The 15-topic blob | **Mostly.** 965 -> 568 items, now one coherent topic |
| Did I break anything? | **Resolved.** Old path reproduced 237->171 exactly; 9 tests pass |
| My scoring check | **Resolved by retiring it** -- it scored junk *highest* (+0.53 correlation) |

### NOT resolved, and how to fix each

**1. Everything is pre-AI.** I measured the raw material, not the rubrics. Whether better clusters
make better coaching is untested.
-> *Fix:* the paid run. ~few hundred AI calls, database snapshot first, resets scenario names and
CSM score history.
-> **STATUS: still open, de-risked at the Layer A level.** 8 real adjudication calls show the two
specific ways Layer A could have failed under turn mode (camouflaged junk accepted; stance lost)
both came out favourable. Says nothing about Layer C rubrics or Layer D scores.

**2. Posture x subject isn't achieved.** You get `budget` with the denials inside it, not "client
denies budget". Nothing splits pushback from questions on the same topic.
-> *Fix:* a second pass splitting subject clusters by stance. The signal is measurably there now
(it wasn't before), but this needs its own pre-registration.
-> **STATUS: likely resolved, and the FIX IS RETRACTED.** The grain arrives at adjudication, not
clustering -- 5 of 5 definitions carry both. No second pass, no new pre-registration needed. Needs
the full 191-cluster pass to confirm (n=5, hand-picked).

**3. A cluster of your own company name.** `jovio` -- 563 items across half the corpus, only 4%
filler, so **my metric counts it as a real subject cluster.** It isn't: it's intros, payment terms
and performance reviews glued together by the word "Joveo".
-> *Fix:* this is a *different* disease from the posture one and the unit change doesn't touch it.
Needs a corpus-ubiquity rule for proper nouns. **It also means 37.2% is an upper bound** -- some
unknown fraction are false positives like this. The comparison holds (same flawed metric both
sides); the absolute number shouldn't be quoted as "71 good scenarios".
-> **STATUS: splits in two. Pipeline half RESOLVED, metric half STANDS.** Gemma sinks it correctly
as `mechanics`, so the pipeline does not mishandle it and **the proposed corpus-ubiquity rule is
RETRACTED as unnecessary**. The metric half is unchanged: 37.2% remains an upper bound and must not
be quoted as "71 good scenarios".

**4. Two config values must move together.** Turn mode needs `merge_cosine_threshold` 0.92 *and*
`min_cluster_size` 16, but there's one shared key for each and the current values are correct for
clause mode.
-> *Fix:* make them derived from the pool unit in code, so they can't drift apart. Flipping the
unit without both is a silent breakage.
-> **STATUS: NOT TOUCHED.**

**5. The "Indeed" bug.** A live filter deletes the word "Indeed" as a stopword, rejecting real
content today.
-> *Fix:* needs a different substance test -- a whitelist is the curated-list anti-pattern.
-> **STATUS: NOT TOUCHED.** Recorded in CLAUDE.md only. Independent of the pool unit, and must not
land in the same run as it (it changes which pairs Layer B extracts = a second variable).

**6. `min_cluster_size` is a hardcoded 50** dressed as a formula, so granularity silently depends
on corpus size.
-> *Fix:* make it a fraction of the pool.
-> **STATUS: not fixed, now OVERRIDABLE.** `fit_topic_model` takes an optional `min_cluster_size`
(default `None` = legacy formula), so the fix needs no restructuring. The default path is still the
hardcoded 50.

**7. Long turns (100+ words)** -- parked at your request.
-> **STATUS: SETTLED (Status update 9). Real, length-driven, ~8-14% -- NOT the 59% of Update 8.**
Went CLOSED (update 7, wrong question) -> REOPENED at 59% (update 8, metric penalised the intended
behaviour) -> SETTLED. Long turns do NOT damage the cluster they join (cleanest clusters,
r=-0.834). Content inside them IS misplaced, but **72.7% of the raw 59% was filler rejoining
backchannel clusters, which is the fix WORKING.** Genuine subject loss is 2,483 of 31,522 sentences
= **7.88% overall, monotonic in length: 0.00% at 0-9 words -> 8.61% at 50-99 -> 13.75% at 100-199
-> 18.70% at 200+**, and that is an UPPER bound (some samples are scheduling content, the `jovio`
false-positive class). **Approach C stays live but ranked LOW** -- single-digit gains, a new
calibrated knob, and the `"Indeed"` fix as a prerequisite, against the ~60%-of-substantive-turns
noise problem which is an order of magnitude bigger and needs only Concern 6. Corrected size: 4,201
turns >= 100 words = 17.5% of turns holding 52.4% of all client words.

### Applies to all of the above

**Nothing is committed.** The pool switch, the harness, the spot-check script, 9 tests, two
CLAUDE.md entries and this spec are all uncommitted in the working tree.

### Two incidental findings from the long-turn probe's step 1

- **The turn pool spans 400 calls, not 416** -- 16 transcripts contribute zero CLIENT turns
  (genuinely internal, or roster misclassification). Unexamined.
- Consequently every trial run computed `call_coverage` and the support floor against **416** while
  only 400 calls contribute, understating coverage slightly and setting the floor at 9 rather
  than 8. Too small to move any conclusion, but the quoted numbers carry it.

---

## Status update 7 (2026-08-15): the long-turn spike. The premise was WRONG -- do not build a chunker

Throwaway probe (scratchpad, not kept), log `logs/longturn_probe.log`. Production path with the
Avoma roster, `min_cluster_size=16`, merge 0.92. Zero Gemma, zero writes.

**Concern 7 was:** a 100+ word turn spanning several topics becomes one averaged embedding and
"may not land cleanly anywhere". Approach C (chunk long turns, never emitting a stance-only
fragment) was the proposed fix, parked because its content-word floor depends on the buggy
stopword count.

### Step 1 -- the size of it, corrected

| | |
| --- | --- |
| CLIENT turns | 23,949 over **400** calls |
| words/turn | p10 3, p25 8, med 25, p75 70, p90 129, p99 177, max **314** |
| turns >= 50 words | 8,028 (33.5%) -- holding **77.0%** of all client words |
| turns >= 100 words | **4,201 (17.5%)** -- holding **52.4%** of all client words |
| turns >= 150 words | 984 (4.1%) |

The withdrawn figure was 5,099 / 17.6%; corrected 4,201 / 17.5% -- **the percentage was right, the
count inflated ~21% by the roster error**, the same pattern as the content-free ratio. Max length
was also wrong (314, not 492 -- the 492-word turn was Joveo staff).

**Reframing that matters: long turns are a sixth of the ITEMS but over half the CONTENT.**

### Step 2 -- the damage, and it runs the other way

| words | turns | became noise | content-free % of the cluster it landed in | cluster size |
| --- | --- | --- | --- | --- |
| 0-9 | 7,004 | **27.7%** | **76.8%** | 143 |
| 10-24 | 4,876 | 52.9% | 40.9% | 127 |
| 25-49 | 4,041 | 58.7% | 19.0% | 176 |
| 50-99 | 3,827 | 60.3% | 8.8% | 218 |
| 100-199 | 4,133 | 59.8% | **5.4%** | 254 |
| 200+ | 68 | 52.9% | **4.0%** | 303 |

    corr(log word count, cluster content-free fraction) = -0.834
    corr(log word count, cluster size)                  = +0.161
    corr(log word count, is_noise)                      = +0.276

**LONG TURNS LAND IN THE CLEANEST CLUSTERS, BY A LARGE MARGIN.** A 100-199 word turn ends up in a
cluster that is 5.4% content-free; a 0-9 word turn ends up in one that is 76.8% content-free. The
correlation is **-0.834** -- long turns are not being smeared into mush, they ARE the signal that
produces the subject-bearing clusters this whole spec is about.

**And they are not disproportionately unclustered.** Noise plateaus at 58-60% for everything above
25 words: 58.7% / 60.3% / 59.8% / 52.9%. Long turns are no worse than medium ones. The +0.276
correlation with noise is driven entirely by SHORT turns being unusually easy to cluster (27.7%),
because backchannel groups readily.

Cluster size does grow with length (143 -> 303, r=+0.161), so long turns land in somewhat broader
clusters. Real but mild, and it is the merge threshold's business, not a chunker's.

### RECOMMENDATION: do not build the chunker. Concern 7 is CLOSED as a non-problem

The premise -- "a long turn becomes one muddy embedding and lands nowhere useful" -- is measurably
false, and it was MY prediction, stated in this spec as the trade-off of Approach A. Measured, the
opposite holds. Approach C is withdrawn, and with it the dependency on fixing the `"Indeed"`
stopword bug first. That removes a design, a pre-registration and a blocker from the plan.

**A generalisable lesson, and the third instance this session:** every quantitative prediction I
made about the pool got the ratio roughly right and the direction of the *quality* effect wrong.
The content-free ratio held (58.9% vs 59.1%) while the counts were 20% off; here the size estimate
held (17.6% vs 17.5%) while the predicted harm was inverted. Measure the effect, never infer it
from the size of the population.

### The finding this probe surfaced instead, which is bigger

**~60% of every substantive turn (>25 words) becomes HDBSCAN noise and never enters the taxonomy
at all.** That is 11,701 of 23,949 turns, and because the loss is concentrated in longer turns by
word volume, it discards the majority of what clients actually said.

This is NOT a long-turn problem -- it is uniform above 25 words -- so a chunker cannot address it.
It is the same coarse-clustering issue already recorded for the sink pool (47.3% noise there,
45.2% in the clause arm here, 48.9% in the turn arm). `min_cluster_size` is the obvious lever and
it is Concern 6, still unfixed and still a hardcoded count.

**Unscoped and unmeasured: whether recovering any of that 60% is possible or worthwhile.** Noted
so it is not rediscovered, not proposed as work.

---

## Status update 8 (2026-08-15): concern 7 REOPENED. Update 7 closed it on the wrong question

Throwaway probe (scratchpad, not kept), log `logs/orphan_probe.log`. Production path with roster,
`min_cluster_size=16`, merge 0.92. Zero Gemma, zero writes.

**Status update 7 above closed concern 7 as a non-problem. That was premature and is CORRECTED
here.** It answered *"do long turns damage the cluster they join?"* (no -- they land in the
cleanest clusters, r=-0.834) and treated that as answering *"is content inside them lost?"*, which
is a different question. It was not tested. The user pushed back and was right.

**Method.** Cluster turns, then split each assigned turn back into sentences and compare, per
sentence, `sim(sentence, centroid of the cluster its TURN landed in)` against
`sim(sentence, its own best-matching centroid)`. A sentence whose best centroid is a DIFFERENT
cluster by >= 0.05 cosine is **orphaned**: it had a home in the taxonomy and its turn took it
elsewhere. Sentence embeddings are the same population as the clause arm, so they were already
cached and cost no new encoding.

**Control, and the reason the numbers are interpretable:** short turns get the identical measure.
A 1.14-sentence turn cannot orphan much by construction, so its rate is this metric's noise floor.

| turn words | turns | sentences | sents/turn | orphaned sentence % | mean margin | turns with >=1 |
| --- | --- | --- | --- | --- | --- | --- |
| **0-9 (CONTROL)** | 2,572 | 2,936 | 1.14 | **21.9%** | 0.157 | 23.2% |
| 10-24 | 2,296 | 4,307 | 1.88 | 42.6% | 0.163 | 55.2% |
| 25-49 | 1,668 | 4,878 | 2.92 | 52.2% | 0.160 | 75.5% |
| 50-99 | 1,521 | 7,133 | 4.69 | 59.0% | 0.154 | 90.7% |
| **100-199** | 1,663 | 12,038 | 7.24 | **59.1%** | 0.139 | 95.8% |
| 200+ | 32 | 230 | 7.19 | 51.3% | 0.136 | 90.6% |

Overall 52.2%. `corr(log turn words, sentence is orphaned) = +0.216`.

**59.1% of sentences inside a 100-199 word turn would fit a different cluster better, against a
21.9% floor -- roughly 37 points attributable to length.** Real content is being taken somewhere
other than where it belongs.

### Both probes are correct; they measure different things

| probe | question | answer |
| --- | --- | --- |
| Update 7 | do long turns damage the cluster they JOIN? | **No** -- cleanest clusters, r=-0.834 |
| Update 8 | is content INSIDE them lost? | **Yes** -- 59% of sentences belong elsewhere |

Both hold simultaneously: **the turn lands correctly for its DOMINANT topic while its secondary
topics go unrepresented.** Conflating the two is what produced the premature close.

### Two things that temper the number, neither of which rescues the close

- **The metric carries a structural confound.** HDBSCAN assigns by density in UMAP space, not by
  nearest cosine centroid, so some sentence-vs-assignment disagreement is inherent. That is what
  the 21.9% control floor measures. **The length effect is the rise ABOVE the floor, not the raw
  59%.**
- **"95.8% of long turns contain >= 1 orphan" is nearly arithmetic**, not evidence: at 7.24
  sentences and a 59% per-sentence rate, P(>=1) is ~99% under independence. The per-sentence rate
  is the honest figure; the per-turn column is dominated by sentence count.
- Severity does NOT grow with length -- the mean margin FALLS (0.157 -> 0.139), so orphaned
  sentences in long turns prefer their alternative slightly less strongly.

### The trade-off, stated precisely

| | orphaning | stance-subject pairing |
| --- | --- | --- |
| clause mode | **none by construction** | **destroyed** (59.1% of the pool content-free) |
| turn mode | **real, ~37 points above floor** | **preserved** (corr -0.744) |

Clause mode has no orphaning precisely BECAUSE every sentence is its own item -- which is the
mechanism that manufactures posture clusters. So this is a genuine trade, not a regression.

### Corrections to this spec

- **Concern 7 is REOPENED.** Its "CLOSED as a non-problem" status in the register above is wrong.
- **Approach C is UN-WITHDRAWN.** Chunking long turns into topic-bearing pieces that never emit a
  stance-only fragment is exactly the design that gets both properties. It is now an **additive
  gain on top of turn mode**, not a fix for something broken -- a materially different
  justification from the original one.
- **Consequently the `"Indeed"` stopword bug matters again**, because C's chunking floor depends on
  the content-word count that bug corrupts. Update 7's claim that C's dependency on it was
  withdrawn is also wrong.

**Not changed by any of this:** the headline. Turn mode still beats clause mode on every measured
axis (4.7% -> 37.2% subject-bearing, junk 57.3% -> 40.8%, stance coupling -0.149 -> -0.744, bands
never overlapping across six thresholds). Orphaning is a residual cost inside a clear win, not a
reason to prefer clause mode.

**Methodological lesson, and it is the fourth of this session:** a probe answers the question it
was built to ask and no adjacent one. Update 7 measured destination quality and I read it as
content retention. State the question a measurement CANNOT answer, in the same breath as its
result.

---

## Status update 9 (2026-08-15): concern 7 SETTLED. Real, length-driven, ~14% not 59%

Throwaway probes 3 and 4 (scratchpad, not kept), logs `logs/orphan_disambig.log`,
`logs/orphan_genuine.log`. Zero Gemma, zero writes.

**Update 8 reported a 59% orphan rate. That number was 73% an artifact of the metric penalising
the very behaviour turn mode exists to produce.**

### Probe 3: the distributional test was ambiguous, and READING settled it

`cos(assigned centroid, preferred centroid)` for orphan pairs vs a null of all pairwise centroid
cosines:

| | p10 | p25 | p50 | p75 | p90 | mean |
| --- | --- | --- | --- | --- | --- | --- |
| ORPHAN pairs | 0.631 | 0.675 | **0.724** | 0.791 | 0.846 | 0.732 |
| NULL random pairs | 0.554 | 0.602 | **0.660** | 0.725 | 0.786 | 0.665 |

Only **+0.064** above the null median -- not clearly near-siblings (which would mean a harmless
near-miss), not clearly random (which would mean genuine topic loss). Inconclusive.

**Reading the samples was decisive: 7 of 8 orphaned sentences were FILLER wanting to join a
BACKCHANNEL cluster.** `"All was all well."` -> wants `thats good, good, okay`.
`"That's that's that's amazing."` -> wants `thats awesome, thats great`. `"I'm like, okay."` ->
wants `okay okay`. `"So I probably rushed through that, but you get the concept"` -> wants
`got got, awesome got`.

**That migration is exactly what turn mode exists to PREVENT** -- it is the mechanism by which
clause mode manufactures posture clusters. So the raw orphan metric substantially measures the fix
working, viewed from the wrong side. **Second metric this session that penalised the intended
behaviour**, after the coherence-lift gate that rewarded junk (+0.527 with content-free fraction).

### Probe 4: narrowing to genuine subject loss

Genuine harm requires the sentence to be substantive AND its preferred cluster to be
subject-bearing AND its assigned cluster to be subject-bearing too (if the turn went to junk, that
is a different defect).

| | sentences | share of orphans |
| --- | --- | --- |
| orphaned (raw metric) | 16,462 | 100% |
| ... AND sentence is substantive | 4,498 | 27.3% |
| ... AND preferred cluster subject-bearing | 2,589 | 15.7% |
| **... AND assigned cluster too = GENUINE** | **2,483** | **15.1%** |
| *filler rejoining filler -- the fix working* | *11,964* | ***72.7%*** |
| *substantive but prefers a JUNK cluster* | *1,909* | *11.6%* |

2,483 of 31,522 sentences = **7.88% overall**. And unlike the raw metric, genuine loss **scales
monotonically with length and does not saturate**:

| turn words | genuine subject loss |
| --- | --- |
| 0-9 | **0.00%** |
| 10-24 | 0.35% |
| 25-49 | 3.20% |
| 50-99 | 8.61% |
| 100-199 | **13.75%** |
| 200+ | **18.70%** |

0% at one sentence rising cleanly to 18.7% is a far more convincing shape than the raw curve's
plateau, and it confirms the effect is genuinely length-driven rather than a sentence-count
artifact.

### ~14% is an UPPER BOUND -- the samples say so

One case is unambiguous:

> *"This **Indeed Connect**, that's being rolled out by Indeed almost seems like a bit of
> inevitability"* -- landed in `ukg, pro, recruiting module` (thin 12%), wants
> `linkedin, slots, ziprecruiter, job` (thin 9%)

A job-board sentence stranded in an ATS cluster. Real loss. (The clearest example of lost subject
matter in the corpus is a sentence about **Indeed** -- the same word both substantive filters
delete as a stopword.)

But at least one is a false positive of the `jovio` class:

> *"If you could send me all of that, I'll review it tomorrow to be on my calendar"* -- landed in
> `chatbot, ai` (thin 3%), wants `week, wednesday, monday, tuesday` (thin **0%**)

That is **scheduling** content. The `< 30% content-free` filter admitted the scheduling cluster
because scheduling talk uses real words -- the same limitation already recorded for `jovio`. So the
14% contains an unmeasured share of logistics-not-subject cases, and several other samples read as
genuinely ambiguous.

### FINAL STATUS OF CONCERN 7: real, length-driven, modest. Approach C ranked LOW

- **Real:** 0% -> 18.7% monotonic in turn length, with at least one unambiguous read sample.
- **Modest:** ~8% of all sentences, ~14% in the 100-199 band, and that is an upper bound.
- **NOT 59%:** that figure was 72.7% filler migration, i.e. the fix working.

**Approach C (chunk long turns into topic-bearing pieces, never emitting a stance-only fragment)
remains live but is ranked LOW.** It buys back single-digit percentages of misplaced sentences at
the cost of a new calibrated knob plus the `"Indeed"` fix as a prerequisite. Compare
**~60% of substantive turns (>25 words) becoming HDBSCAN noise and never entering the taxonomy at
all** -- an order of magnitude larger, measured by the same free probe, and needing no new knob,
only `min_cluster_size` expressed as a fraction of the pool (which is Concern 6).

**Unchanged by any of this:** the headline. 4.7% -> 37.2% subject-bearing, junk 57.3% -> 40.8%,
stance coupling -0.149 -> -0.744, bands never overlapping across six thresholds.

### The concern went CLOSED -> REOPENED -> SETTLED, and the reasons matter more than the label

1. Update 7 measured *destination quality* and closed it. Wrong question.
2. Update 8 measured *content retention* and reopened it at 59%. Right question, metric that
   penalised the intended behaviour.
3. Update 9 separated filler migration from subject loss and settled it at ~8-14%.

**Methodological lesson, the fifth of this session: before believing a rate, ask what fraction of
it is the behaviour you were trying to cause.** Both metrics that misled here (coherence lift,
raw orphan rate) failed that question, and in both cases reading a handful of real samples
exposed it where the aggregate number could not.

---

## Status update 10 (2026-08-15): the Gemini backend. Turn mode survives, and the ADJUDICATOR is the bottleneck

Harnesses `calibration/trial_pool_unit_gemini.py`, `calibration/trial_adjudicate_gemini.py`,
`calibration/export_cluster_batches.py`, `calibration/aggregate_cluster_verdicts.py`.
Backend: the Joveo LLM gateway (`calibration/trial_gateway.py`) -- `gemini-embedding-2` for
vectors, `gemini-3.5-flash-lite` for chat. **Zero Postgres writes throughout; the live 161
scenarios are untouched.**

### The embedding run

24,000 requests, ONE TEXT PER REQUEST, 20 concurrent workers, ~46 req/s, ~8 minutes.
Batching was deliberately NOT used: `trial_gateway.py` measured the gateway's `/embeddings`
endpoint silently returning FEWER vectors than inputs, intermittently -- the same request
batches or collapses depending on when it is sent, and it hits SHORT text hardest, which is
29% of this corpus. Concurrency is a throughput knob that cannot reintroduce that; batching
is not. Vectors cached to SQLite keyed on the NATIVE width so a width change never re-pays.

**Measured against bge, full 416-transcript corpus:**

| | bge (local) | Gemini 3072 |
| --- | --- | --- |
| content-free share of pool | 32.8% | **32.8%** (identical -- it is text-only) |
| turn-vs-turn cosine | p50 0.558, spread 0.141 | p50 0.625, **spread 0.130** |
| centroid-vs-centroid | -- | p10 0.722 **p50 0.810** p90 0.886 |
| raw clusters | 246 | **292** |
| HDBSCAN noise | 48.9% | **43.5%** |

The compressed-space worry did NOT materialise: spread 0.130 vs bge's 0.141, not the 0.082
`compare_embedders.py` reported. Gemini also clusters MORE and leaves LESS noise.

**`merge_cosine_threshold` for this backend is 0.97, not bge's 0.92** -- derived by READING
groups, and the centroid band (p50 0.810) is why: at 0.92 only 136 clusters survive with a
1,790-item blob. At 0.97 the backchannel families still merge 8-into-1 and 6-into-1 while
every business topic stays at 1 raw. Two backends, two values, ONE config key -- Concern 4 is
now concrete rather than hypothetical.

**Clustering REPRODUCED EXACTLY across four separate processes** (292 raw -> 245 merged every
time; the batch export re-clustered and matched position-for-position on turn count). That is
the deterministic-embedding benefit CLAUDE.md predicted, and it removes one of the two
sources of the run-to-run variance documented for bge.

### Width: 3072 BEATS 768, contradicting the earlier recorded finding

Matryoshka validated at corpus scale first: `cos(api_768, renormalised first-768-of-3072)`
over **11,977 real turns -- min 1.000000, none below 0.999.** So the width comparison measures
width, not truncation error. (Those 11,977 vectors were the stranded output of a killed
768-width run; they paid for this validation instead of being wasted.)

| merge | 3072 subject-bearing | 768 subject-bearing |
| --- | --- | --- |
| 0.94 | 31.7% | 29.7% |
| 0.96 | 38.7% | 33.5% |
| **0.97** | **39.6%** | 36.0% |
| 0.98 | 39.4% | 36.8% |

3072 wins at every threshold from 0.92 up, and on junk share at every threshold without
exception. **`compare_embedders.py` recorded `gemini_768` BEATING `gemini_3072` (0.686 vs
0.672 on `sink_real_margin`) and that does NOT transfer** -- that metric measured per-trigger
centroid margins; this measures cluster quality after UMAP+HDBSCAN. Requesting 768 directly
would have shipped the worse configuration with no way to notice, since the comparison would
have cost another 24k requests. **Fetch the native width and truncate locally.**

### The adjudication runs -- the first REAL scenarios this effort has produced

Production's `PROMPT_LAYER_A_V2_TRIAGE`, unmodified, one call per surviving cluster,
SEQUENTIALLY (the accepted-list is the duplicate-detection mechanism; parallelising it would
collapse that).

| | turn @ min 16 | turn @ min 50 | clause @ min 50 (production) |
| --- | --- | --- | --- |
| clusters judged | 245 | 76 | 171 |
| **coachable** | **38 (15.5%)** | **17 (22.4%)** | **85 (49.7%)** |
| mechanics | 129 | 45 | 66 |
| merged as duplicates | 69 | 11 | -- |

The 17 at min 50 read very well -- `funnel_conversion_optimization` (247 turns, *"rising
application volumes but declining downstream onboarding and activation rates"*),
`linkedin_and_job_board_transition_to_programmatic` (322/104 calls),
`ats_integration_and_data_mapping` (274/44). Keyphrases came out VERBATIM without any prompt
change (`'launching this RFP'`, `'cost per activation'`, `'radius search'`) against
production's analyst-speak (`'platform nuances'`, `'feature capabilities'`) -- whole turns
give the model real client language to quote.

### Nine BLIND judges, and they overturn the adjudication

245 + 76 clusters exported with ONLY keywords, sample turns, size and coverage -- no verdict,
key, description or reason -- and judged in batches by nine independent subagents. Blinding
matters: a judge shown the verdict grades the label, not the cluster.

| | min 16 | min 50 |
| --- | --- | --- |
| **coherent** (judge) | **207 (84%)** | 57 (75%) |
| **coachable** (judge) | **92 (38%)** | 25 (33%) |
| coachable by TURN VOLUME | **35.1%** | 31.0% |
| coachable (Gemma) | 38 (16%) | 17 (22%) |
| judge-vs-Gemma agreement | 76% | 84% |

**min 16 beats min 50 on every independent measure** -- more coherent, more coachable, more
coachable turn volume. Finer granularity is better, which is the opposite of the intuition
that sent me looking at min 50.

**GEMMA IS SYSTEMATICALLY OVER-SINKING, AND THE DISAGREEMENT IS ONE-DIRECTIONAL:**

| | min 16 | min 50 |
| --- | --- | --- |
| Gemma coachable, judge says NOT | **2** | **2** |
| Gemma sank it, judge says COACHABLE | **56** | 10 |
| turns discarded that a judge would keep | **1,831 (14.6%)** | 788 (6.6%) |

Gemma is precise and under-recalls. The discarded material is plainly coachable: *"Source-of-
hire attribution, UTM/tracking discrepancies and duplicate applications"* (80 turns),
*"Middleware/Junction/Aperture integration path, added cost and complexity"* (72),
*"location/city/state/country feed mapping and radius"* (121).

### THE CONTENT-FREE PROXY IS VINDICATED -- my "directionally wrong" verdict is RETRACTED

| | proxy | blind judges | Gemma |
| --- | --- | --- | --- |
| min 16 coachable share | **39.6%** | **38%** | 15.5% |
| clusters >=70% content-free -> coachable | ~0% | **1%** | 1% |
| clusters <30% content-free -> coachable | -- | **84%** | 33% |

A mechanical text measure and nine blind readers agree within TWO POINTS. **Gemma is the
outlier.** Status update earlier in this session concluded "my proxy was directionally wrong"
on the strength of the adjudication alone; that conclusion is withdrawn. The proxy is a good
junk detector AND a reasonable quality measure; the ADJUDICATOR was miscalibrated for this
input.

### Root cause, and the fix now running

`PROMPT_LAYER_A_V2_TRIAGE` defines mechanics as *"acknowledgment, backchannel, greetings,
thanks, filler, scheduling chatter"*. That worked on CLAUSE input, where a cluster was purely
filler or purely substance. **A whole TURN routinely OPENS with acknowledgement before its
real content** -- *"Yeah. Okay. So on the ATS integration, do we need a separate pixel?"* --
so the representative utterances visibly contain filler and the cluster gets sunk. The prompt
predates the pool-unit change and was written for a different unit. It also explains why
agreement is better at min 50 (84%) than min 16 (76%): coarser clusters show more substance
per sample.

`--turn-aware` appends `TURN_AWARE_NOTE`, which tells the judge WHERE in a turn to look and
changes no decision option and no standard. Verified before spending: model pinned to
`gemini-3.5-flash-lite` at the call site, no unfilled placeholders, base prompt byte-identical
under the append, separate artifact path, and a 5-cluster path test in which career-history
rambling, backchannel, acknowledgements and meeting-attendance ALL still sink -- i.e. it
corrects where the judge looks without lowering the bar.


---

## Status update 11 (2026-08-15): CORRECTION -- update 10's "over-sinking" finding was MY BUG

**Status update 10 above reports that Gemma over-sinks by 2.4x, discarding 56 clusters /
1,831 turns (14.6% of the corpus) that blind judges would keep. THAT IS WRONG. It is an
artifact of `aggregate_cluster_verdicts.py` counting `merge_into` as a sink.**

`_KIND_BY_DECISION` maps a `merge_into` decision to `kind="merged"`, and the aggregator tested
`kind == "scenario"` for "Gemma says coachable". A merged cluster is NOT discarded -- it is
recognised as a duplicate and folded into an existing coachable scenario, so its content is
retained. Counting those as sinks manufactured the entire disagreement.

**The correct cross-tabulation, 245 min-16 clusters against nine blind judges:**

| Gemma decision | judge YES | judge NO | total | turns |
| --- | --- | --- | --- | --- |
| scenario | 36 | 2 | 38 | 2,725 |
| **merged** (retained, folded in) | **56** | 13 | 69 | 2,434 |
| mechanics | **0** | 129 | 129 | 6,134 |
| logistics | **0** | 9 | 9 | 1,289 |

**Of the 138 clusters Gemma genuinely sank, the judges want ZERO. Agreement on what to
discard is 100%.** The only real disagreement runs the other way: 15 clusters (13 merged +
2 scenario) that Gemma RETAINED and the judges would drop, i.e. Gemma is marginally
permissive, not aggressive.

Retention: **107 of 245 clusters, 5,159 of 12,582 turns (41.0%)**, as 38 distinct scenarios
enriched by 69 merged duplicates.

### The prompt fix was built for a problem that does not exist, and its null result is what caught this

`--turn-aware` / `TURN_AWARE_NOTE` was written to stop the mechanics definition sinking turns
that merely OPEN with filler. Measured over the same 245 clusters:

| | baseline | turn-aware |
| --- | --- | --- |
| coachable | 38 | **43** |
| flipped INTO coachable | -- | 12 (judges endorse 9) |
| flipped OUT of coachable | -- | 7 |
| agreement with blind judges | **76%** | **76%** |

Net +5 with 12-in/7-out churn and agreement unchanged to the point. **A fix aimed at a real
defect does not leave the metric it targets exactly where it started.** That null result is
what prompted the re-check that found the bug. `--turn-aware` stays in the harness, flagged
and OFF; it is not justified by anything measured.

### What survives update 10, and what does not

**SURVIVES** (none of it depends on the aggregator): the embedding-batching hazard and the
concurrency answer; native-width fetch plus cache-key discipline; **3072 beating 768**;
**merge 0.97** for this backend; exact cross-process cluster reproduction; the blind-judging
method; sequential adjudication; and the finer-granularity result (min 16 beats min 50 on
coherence 84% vs 75% and judge-coachability 38% vs 33%).

**WITHDRAWN**: "Gemma is systematically over-sinking", "1,831 turns discarded", "the
adjudicator, not the clustering, is the bottleneck", and the claim that the prompt is
miscalibrated for turn input. Gemma and nine independent readers agree completely on what to
throw away.

**PARTLY RESTATED -- the content-free proxy.** Update 10 vindicated it against Gemma. With
merges counted correctly, Gemma's retention (107/245 = 43.7%) sits close to the proxy's 39.6%
subject-bearing and the judges' 38% coachable. All three agree; the apparent conflict was the
bug. The proxy remains an excellent junk detector (>=70% content-free -> judges call 1%
coachable) and a serviceable quality measure.

**METHODOLOGICAL LESSON, the sixth this session and the most expensive: an analysis script is
as capable of manufacturing a finding as a measurement script is.** Four checks existed on the
DATA path (blind judging, position-verified joins, path tests, a pre-registered gate) and none
on the ANALYSIS path. The bug was a single equality test on an enum with four values, two of
which mean "retained". **When a category has more than two outcomes, enumerate them in the
report rather than collapsing to a boolean** -- the cross-tab above makes the error impossible
to miss, and it is what should have been printed first.

---

## Status update 12 (2026-08-15): validating the taxonomy against LAYER D, not against itself

Harness `calibration/validate_taxonomy_vs_layerd.py`. Zero chat calls, zero DB writes.
Both taxonomies embedded with the SAME model (Gemini via the gateway) so only the taxonomy
differs -- embedding each with its own production embedder would confound taxonomy against
embedder, the asymmetric-comparison trap this codebase keeps hitting.

Every earlier measurement (coherence, content-free share, blind judges) is UPSTREAM of what
matters. These three tests are the cheapest things that speak to Layer D itself.

### Test 1 -- rubric lookup over 6,468 real CSM client turns

Layer D's first action is matching a client turn against `business_description + keyphrases`;
a turn whose best match is a SINK is rejected as "not a signal". That rejection is the only
thing stopping "Thank you." being scored as coaching.

| | OLD (production, 161 entries) | NEW (turn mode, 176 entries) |
| --- | --- | --- |
| accepted as signal | 46.7% | **35.6%** |
| rejected to a sink | 53.3% | **64.4%** |
| best-match cosine p50 | 0.680 | 0.681 |
| top1-top2 margin (mean) | 0.0164 | 0.0147 |
| agree on accept/reject | \-- | **78.0%** |
| NEW accepts, OLD rejects | \-- | 355 |
| OLD accepts, NEW rejects | \-- | 1,071 |

**The extra rejection is mostly CORRECT, by reading.** Of six sampled turns OLD accepts and
NEW sinks, four are plainly not coaching moments:

| turn | OLD routes to | NEW | verdict |
| --- | --- | --- | --- |
| "It's nice to meet everyone. Pretty big turnout..." | `stakeholder_role_identification` | sink | NEW right |
| "If." | `client_validates_proposed_scenario` | sink | NEW right |
| "I'm not sure." | `client_expresses_uncertainty` | sink | NEW right |
| "Hi. It's Jenny from integrations. No questions." | `stakeholder_role_identification` | sink | borderline |
| "If that's possible. We can do that. Yeah..." | `client_requests_configuration_change` | sink | borderline |
| "the open text at the end, is that gonna be like Knockery" | `job_board_ecosystem_discovery` | sink | **NEW WRONG** |

Production routes **"If."** and **"I'm not sure."** to coachable scenarios -- and to exactly
the posture scenarios (`client_validates_proposed_scenario`,
`client_expresses_uncertainty`) that fail the random-null test. That is the pathology this
whole effort diagnosed, visible end to end in Layer D's own input.

Margin is marginally WORSE for NEW (0.0147 vs 0.0164). Both are tiny -- p50 of 0.009-0.010
means the winning scenario beats the runner-up by a hair, in BOTH taxonomies. That is worth
its own look: a matching decision resting on a 0.01 cosine gap is close to arbitrary.

### Test 2 -- coverage of moments Layer D already called coachable, AND WHY IT IS BIASED

600 real client turns drawn from the 84 scenarios `gap_events` actually produced findings
against (2,473 rows).

| | keeps |
| --- | --- |
| OLD (production) | **512/600 (85.3%)** |
| NEW (turn mode) | 444/600 (74.0%) |

**Read as-is this favours OLD by 11.3 points. It should NOT be read as-is.** The "known
coachable moments" are defined BY the old taxonomy -- `gap_events` carry old scenario keys and
the turns are sampled from those scenarios' own pairs. The test asks "does NEW keep what OLD
kept", which OLD wins by construction.

And the top sources make the bias concrete: `client_requests_operational_visualization` (184
events) and `client_validates_proposed_scenario` (131) are **posture scenarios that fail the
random-null test**. So a material share of what NEW "loses" are moments OLD only found through
scenarios that do not hold together. **This test cannot separate "NEW misses real coaching"
from "NEW correctly declines OLD's noise", and no version of it can while the ground truth is
the old taxonomy's own output.**

An unbiased version needs moments labelled independently of either taxonomy -- human labels,
or the h2h `artifacts/h2h_moments.json` set (589 verified moments built from client turns
directly, needing no rubric and no scenario assignment). Not run.

### Test 3 -- scenarios that would get no rubric

| | OLD | NEW |
| --- | --- | --- |
| coachable scenarios | 85 | 38 |
| rubrics generated | 84 | \-- |
| **stranded, no rubric possible** | **1** (`rfp_process_disclosure`) | **0** |
| distinct-call support | \-- | min 8, p25 14, med 19, max 120 |

Every NEW scenario clears `min_milestone_calls_floor: 3` comfortably; the weakest has 8
distinct calls. NEW is narrower but nothing in it is stranded.

### The caveat that qualifies the 38: PROPER-NOUN CLUSTERS PERSIST

`implementing_and_maintaining_tracking_pixels` (87 turns / 14 calls) is really *"the Happy
Dance account"*. Its c-TF-IDF keywords are `happy dance, dance, happy, pixel, carriers...` --
the top three are a product/client name. Reading its 12 sampled turns, ~5 are genuinely about
pixel implementation; the rest are timelines ("realistic to expect happy dance, mojo apply
turned on for Jan one"), field changes, banter ("Are you scared? Are you happy?") and a
tangent about Oracle and Workday enrollments.

Gemma named it for the pixels because pixels appeared in the six samples it saw; the actual
binding is the client name. **Same failure as the `jovio` cluster, and it means the "38
coachable" count is soft** -- an unknown fraction are account-specific rather than general
coaching situations, and a rubric written for "Happy Dance" transfers to no other client.
Both Gemma and the blind judges accept these, because the visible samples look substantive.

Cheap unrun check: flag any cluster whose top c-TF-IDF keywords are dominated by a proper
noun, and count how many of the 38 that removes.

### Verdict

NEW is **cleaner** -- it rejects junk Layer D currently accepts, strands nothing, and every
scenario is well evidenced. NEW is **narrower** -- 38 against 85, though only ~21 of the 85
beat a random null.

**None of these three tests proves better coaching.** Test 2's apparent loss is confounded
beyond repair by its ground truth, Test 1's headline is a rate whose correctness only sample
reading establishes, and Test 3 measures structure rather than quality. The honest summary is
that the new taxonomy is better-formed on every structural axis measured and unproven on the
one axis that matters.
