# Layer B/C downstream validation: does the noise-rescue produce better rubrics?

**Date:** 2026-08-16
**Status:** PRE-REGISTERED — written before any Layer B/C arm has been run.
**Predecessors:** `2026-08-16-layer-a-clustering-method-design.md` (the rescue, and Status
update 2 which records what the corpus cleanup did to it),
`2026-08-14-layer-a-pool-unit-design.md` (turn vs clause).
**Spend:** ~400 chat calls (2 adjudication arms) + a response-clause embedding backfill of
unknown size — **step 0 is to measure that before committing.** Zero Postgres writes.

## 1. The one question

Every Layer A result so far is an INPUT-side claim. `rescue_centroid` was shown to admit
on-topic turns (blinded 10/10), to broaden evidence (96→133 calls per scenario, account
concentration 29%→21%), and — after the corpus cleanup — to produce 34 scenarios against a
26–28 noise band. **None of that is an outcome.** The justification was always a chain:

    more turns per scenario -> more kb_pairs -> more response clauses
      -> more milestone support -> Layer D finally has enough observations

**Not one link has been measured.** This design measures the first three, and nothing else.

> **Scope is deliberately narrow.** An earlier draft also pitted centroid-vector matching
> against description-vector matching in Layer B. That is CUT. Matching stays at production's
> default (`shared/scenario_vectors.scenario_text`, `layer_a.scenario_vector_mode: concat`) in
> every arm, so the rescue is the single variable. The routing question is real but unresolved
> for reasons this trial cannot fix, and folding it in here would mean two variables and no
> clean answer to either.

## 2. Arms

Two Layer B/C runs over one fixed corpus (the cleaned 20,788-turn pool), differing in exactly
one thing — which taxonomy Layer B matches against:

| arm | taxonomy | matching |
| --- | --- | --- |
| `base` | clean base adjudication | description vector (production default) |
| `rescued` | clean rescued adjudication | description vector (production default) |

Same corpus, same embedder, same Layer B/C code, same `tuning.yaml`. Anything else that differs
is a bug.

## 3. Metrics — none of them a coherence score

Coherence is excluded on purpose: it is the rescue's own objective function, and the clustering
trial already established that a gate which is an arm's objective cannot rank that arm.

**Primary (Layer C, Gemma-free Pass 1):**

- milestones per scenario; count of scenarios with ZERO milestones
- `support_calls` per milestone — DISTINCT CALLS, never raw clause counts
- **scenarios that clear `min_milestone_calls_floor: 3`** — below it a scenario gets no
  clustered milestones and falls through to the V1 Gemma free-text fallback. Crossing that line
  is the concrete product win the rescue was supposed to deliver.

**Secondary (Layer B):**

- kb_pairs per scenario; share of pairs whose best match is a SINK
- assignment concentration — does one scenario absorb everything?
- top1−top2 margin distribution. CLAUDE.md records this as ~0.01 cosine in BOTH taxonomies,
  i.e. every assignment rests on a hair. If the rescue widens it, that is a real result
  independent of the milestone counts.

**Mandatory guards, each from a specific past failure in this repo:**

- **Report a `merged` outcome.** `replay_layer_c_admitted._match_milestones` was merge-blind and
  scored N baseline milestones collapsing into ONE arm cluster as N clean matches. Report
  merged, and normalise support by the arm's own call count.
- **A volume-matched placebo.** Perturbing a clause pool at all costs ~6 milestones to
  UMAP/HDBSCAN sensitivity regardless of content quality, so a loss count is uninterpretable
  without one.
- **Read real samples before believing any aggregate.** Non-negotiable — it is what caught the
  interview cluster, the "Exclude from Review" misread and three keyword traps in one session.

## 4. Failure conditions, pre-registered

- **F1** Embedding backfill exceeds the budget agreed at step 0 → stop and re-scope; do not
  half-run it.
- **F2** Two runs of the SAME arm differ by more than the treatment → Layer C's own
  run-to-run instability (documented: 385/398/403-407 milestones for identical input) swamps
  the comparison. Report the floor and stop. **Note this needs a second `base` run to detect,
  and Layer C Pass 1 is Gemma-free, so the floor is cheap here in a way it was not for
  adjudication.**
- **F3** An arm leaves <20 scenarios rankable → unrankable, not comparable.
- **F4** Milestone count falls outside ~[350, 450] scaled to this corpus → the clustering did
  not reproduce; the run is void.
- **F5** If the difference lands inside the floor, that is the published result. **"The rescue
  does not reach the rubrics" closes the question** and is worth as much as a positive.

## 5. What this cannot answer

Whether better rubrics improve Layer D coaching. That needs `milestone_performance` and a
scoring run, and Layer D's grader has its own documented problem — leakage-clean `W(matched)`
is 0.089-0.095, i.e. the criteria are unpassable even by their own author. **A better rubric
fed to a broken grader will not show up.** Do not chain this into Layer D without reading
`2026-08-15-grader-inputs-design.md` first.

Everything here is gemini-embedding-2@3072 in TURN mode; production is local bge@768 in CLAUSE
mode. No production change may cite these numbers alone.

## 6. Loose ends from the 2026-08-16 session, to close alongside this

Small, each independently useful, none blocking the above:

1. **Two roster repairs identified but NOT applied** — `Dan Sapir` (37 turns) and
   `Doug Shonrock`'s remaining 46. Both are exact matches in the 988-name HR export. Doug's
   sidecar gives him a CLIENT's email (`amiller@lumbertonisd.org`), which
   `ops/repair_speaker_rosters.py` deliberately refuses to overwrite — that guard is correct;
   these two need the HR list as the authority instead. 83 turns, 0.4%.
2. **`aggregate_cluster_verdicts.py:83` still contains a RETRACTED bug.**
   `rows[i]["kind"] == "scenario"` collapses a four-valued enum and counts 69 `merged`
   (= RETAINED) clusters as sinks — the exact defect CLAUDE.md records as producing the phantom
   "Gemma over-sinks 14.6%" finding. It also joins on `i`, a rank, while its docstring claims
   `cluster_id`. **Re-running it today regenerates a known-false number.** Two-line fix, or
   delete it. See `Brain/HARNESS_DELETION_PROPOSAL_2026-08-16.md`.
3. **The head-vs-centroid sampling cost is measurable and unmeasured.**
   `trial_adjudicate_gemini.py` now picks representatives by centroid cosine; re-adjudicating
   the same clusters and diffing against `adjudicate_gemini_min16.json` measures exactly what
   head-sampling cost (~245 calls). It decides whether the pool-unit spec's Status update 10
   diagnosis needs rewriting.
4. **`Unknown Speaker` is fixed at the classifier, not at the source.** The real fix is
   reconciling diarized speakers against actual participants at
   `ops/fetch_avoma_recordings.py:107`, where the fallback string is emitted. Until then those
   turns are correctly excluded but not recovered.
5. **One top-5 scenario is still 98% a single client** (RTX). Account-bound rubrics transfer to
   nobody. Unscoped.
