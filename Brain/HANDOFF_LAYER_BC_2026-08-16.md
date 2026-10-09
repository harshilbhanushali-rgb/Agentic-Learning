# HANDOFF — Layer B/C downstream validation (2026-08-16)

Continue-from-here for the question every Layer A result so far has dodged: **does any of it
reach a rubric?** Read this top to bottom, then the spec, then start at step 0.

Spec: `docs/superpowers/specs/2026-08-16-layer-bc-downstream-validation-design.md`
Prior session's narrative: `Brain/PROBLEMS_AND_FIXES.md` (last section) and the three new
CLAUDE.md sections dated 2026-08-16.

## 0. State of the world

**Corpus was cleaned this session — 13.2% of it was not client speech.**

| | |
| --- | --- |
| transcripts | 416 → **393** (23 job-interview calls quarantined to `recordings_excluded_interviews/`) |
| CLIENT turns | 23,949 → **20,788** |
| removed | 1,490 interviews + 1,127 unattributed + 544 Joveo-staff-as-client |

**One PRODUCTION file changed:** `preprocessing/transcript_parser.py` gained
`SpeakerRole.UNATTRIBUTED`. 18 existing tests pass. Layer A/B skip it; layer_b's response
window behaves identically; `ego_trap/` has its own enum and is untouched.

**Everything keyed to the OLD pool is STALE** — `clustering_bench.json`,
`clustering_bench_members.json`, `adjudicate_gemini_min16.json`, and the
`adjudication_ab_{base_a,nc_base_b,nc_rescued,clean_*}` artifacts. The `clean_*` arms were run
on a 21,915-turn pool that no longer exists (they predate the unattributed fix). **Do not
compare anything old to anything new.**

## 1. STEP 0 — scope the embedding cost BEFORE spending

This is the gate. Triggers are cached; **Naren's response clauses are NOT** — the gemini cache
was only ever warmed for CLIENT turns, and Layer C clusters responses.

Write a read-only scoping script that:
1. parses the 393 transcripts, calling `v1.layer_b.extract_pairs(turns, db_call_id)`
   **PER CALL** (production does this at `v2/pipeline.py:39-44`; concatenating calls pairs a
   trigger in one call with a response in the next — I made exactly that mistake),
2. splits responses with the PRODUCTION segmenter (`preprocessing/segmenter.py`, the same one
   `v2/layer_c.py:77` uses — do not re-implement it, sentence boundaries move when spaCy is
   loaded with different components and that has already caused a ~20% disagreement here),
3. counts how many of those clause texts are missing from the gemini cache
   (`calibration.trial_pool_unit_gemini._cache_open` / `_key`).

**Report the number and agree the spend before fetching anything.** If it is ~20-40k, that is
~10-15 min of gateway concurrency; if it is far larger, re-scope.

When you do fetch: **NEVER batch the gateway's `/embeddings`** — it silently returns FEWER
vectors than inputs, worst on short text. Throughput comes from CONCURRENCY, one text per
request. Fetch NATIVE 3072 and truncate locally; key the cache on the native width.

## 2. Then: two adjudication arms on the current corpus (~400 calls)

The `clean_*` arms are stale. Re-run with the driver, which already has the right guards:

```
.\ops\run_visible.ps1 -Script ops/run_adjudication_ab.py
```

Edit its `ARMS` to two arms — one base, one `["--rescue", "centroid"]`. **A third base arm was
considered and rejected as unnecessary** (it tightens the floor around the weakest part of the
case; the solid evidence does not use the floor). The harness computes the rescue IN PROCESS
via `--rescue centroid` rather than loading the stale sidecar.

## 3. Then: the two Layer B/C arms

See the spec for metrics and guards. Two arms over the cleaned corpus, differing in ONE thing --
which taxonomy Layer B matches against:

    base      clean base adjudication
    rescued   clean rescued adjudication

**Matching stays at production's default in BOTH arms** (`scenario_vector_mode: concat`, i.e.
description + keyphrases). An earlier draft of the spec also pitted centroid-vector matching
against description matching; that is CUT, so the rescue is the single variable. Do not
reintroduce it -- two variables here would give a clean answer to neither.

Compare on: milestones per scenario, `support_calls` per milestone (distinct CALLS, not clause
counts), and how many scenarios clear `min_milestone_calls_floor: 3` -- below that floor a
scenario gets no clustered milestones at all and falls through to the V1 Gemma free-text
fallback, so crossing it is the concrete product win the rescue was supposed to deliver.

**Layer C Pass 1 is Gemma-free**, so unlike the adjudication A/B a noise floor is cheap here:
run `base` twice. Do it -- the whole reason the adjudication result was readable at all was
having a floor to read it against.

## 4. Build NEW harness files; do not extend the old ones

`calibration/dry_run_layer_bc.py` is the closest precedent (production `assign_scenarios` +
`layer_c._relevance_filter`, zero Gemma/Postgres/Pinecone) but it substitutes c-TF-IDF pseudo
descriptions — you need the REAL adjudicated ones per arm. `calibration/replay_layer_c_admitted.py`
is the precedent for a Gemma-free Layer C Pass-1 replay.

Suggested: `calibration/layer_bc_arms.py` + `tests/test_layer_bc_arms.py`.

**Guards that are not optional, each earned the hard way:**
- checkpoint identity = a CONTENT HASH of the inputs, hard-fail on mismatch (a count-based key
  cannot distinguish two arms that differ only in membership — this produced a silent
  "no effect with zero calls" result this session)
- every arm writes to its OWN path; `--arm` required, no default that can hit a baseline
- `no_cache=True` on every chat call, and the SAME cache policy on every arm
- report a `merged` outcome and normalise support by each arm's own call count
- a volume-matched placebo (perturbing a clause pool at all costs ~6 milestones)
- record `served_model` per row and shout if arms differ

Get the new harness AUDITED by one subagent before running it, with a strict bar: only report
bugs that would change the outcome or waste a paid run. That found 7 real defects in the old
adjudication harness and 3 in the new one this session, four of them fatal.

## 5. Traps that fired this session — do not re-discover them

- **THE GATEWAY CACHES CHAT COMPLETIONS.** Identical prompt → byte-identical text in 249ms vs
  1741ms. A "run it twice for a noise floor" design silently returns run 1's answers. The tell
  was identical FREE TEXT across 245 prompts, not identical labels. Always set `no_cache=True`
  when measuring variance.
- **A flip RATE discards DIRECTION.** Treatment and noise both flipped ~13% of clusters; noise
  flips were symmetric and the treatment's were not. Report the transition matrix.
- **In this business, `hiring` / `resume` / `candidate` / `prep` / `quick connect` are the
  SUBJECT MATTER, not signals.** Three separate rules were fooled this session. Same class as
  `Indeed` being a spaCy stopword.
- **Avoma's `purpose = "Exclude from Review"` is a HOUSEKEEPING tag, not a quality judgment** —
  110 calls, 28% of the pool, dominated by recurring CLIENT meetings. Nearly excluded on a
  misread; reading the subjects caught it.
- Avoma detail endpoint needs a **trailing slash** (301 without); `/v1/meeting_types/` is 404.

## 6. Loose ends from this session -- close these alongside

Each is small, independently useful, and none blocks the main run. Full detail in the spec's
section 6.

1. **Two roster repairs identified but NOT applied** -- `Dan Sapir` (37 turns) and
   `Doug Shonrock`'s remaining 46, both exact matches in the 988-name HR export. Doug's sidecar
   gives him a CLIENT's email, which `ops/repair_speaker_rosters.py` rightly refuses to
   overwrite; use the HR list as the authority for these two. 83 turns, 0.4%.
2. **`aggregate_cluster_verdicts.py:83` still regenerates a RETRACTED finding** --
   `rows[i]["kind"] == "scenario"` collapses a four-valued enum and counts 69 `merged`
   (= RETAINED) clusters as sinks. Two-line fix or delete; see
   `Brain/HARNESS_DELETION_PROPOSAL_2026-08-16.md`, still awaiting a decision.
3. **The head-vs-centroid sampling cost is measurable and unmeasured** (~245 calls). It decides
   whether the pool-unit spec's Status update 10 diagnosis needs rewriting.
4. **`Unknown Speaker` is fixed at the classifier, not the source** --
   `ops/fetch_avoma_recordings.py:107` is where the fallback string is emitted.
5. **One top-5 scenario is still 98% one client** (RTX). Account-bound rubrics transfer to
   nobody. Unscoped.
6. The live Postgres taxonomy was built on the UNCLEANED corpus, so a future production run
   will differ from what is in the DB.
