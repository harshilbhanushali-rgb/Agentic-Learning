# Proposal: what to do with the adjudication-family harnesses (2026-08-16)

**Decision requested.** Nothing has been deleted. This is a recommendation with the evidence
attached; the call is yours.

## Scope

Three calibration scripts built the Gemini turn-mode adjudication work behind
`docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md` Status update 10:

| script | role | state |
| --- | --- | --- |
| `calibration/trial_adjudicate_gemini.py` | adjudicates clusters -> taxonomy | 7 defects found; patched today |
| `calibration/export_cluster_batches.py` | exports clusters for blind judges | sound in itself |
| `calibration/aggregate_cluster_verdicts.py` | joins judge verdicts to Gemma's | **still contains a retracted bug** |

A fourth file is new and replaces the first for comparison work:
`calibration/adjudication_ab.py` (+ `tests/test_adjudication_ab.py`, 20 passing).

**Load-bearing fact: none of the three is imported by anything.** Every apparent reference is
prose in a docstring — verified with `grep -rnE "^\s*(from|import).*<module>"`. Deleting any of
them breaks no code, no test and no pipeline.

## What is actually wrong with each

### `trial_adjudicate_gemini.py` — 7 defects, 4 fatal to any paired comparison

Found by audit today, all verified in code:

1. **Checkpoint keyed on cluster COUNT alone.** For a rescue A/B the count is held fixed by
   construction, so the guard *cannot* fire: arm 2 resumes arm 1's finished checkpoint, runs
   `range(245,245)` = nothing, and writes arm 1's verdicts as its own. A perfect "no effect"
   with zero chat calls, detectable only by wall-clock.
2. **`OUT` defaults to the published baseline and is written unconditionally** — the
   documented `--limit 5` path test would replace 245 rows with 5.
3. **Representatives were `texts[:6]`** — the first six by corpus file order. See the
   asymmetry section below; this is the one with consequences beyond the harness.
4. **`i` used as an identity** when it is a rank the treatment reorders.
5. A failed call was synthesised as `new_scenario`: counted coachable **and** entered the
   sequential accepted-list with an empty description, perturbing duplicate detection for
   every later cluster.
6. `served_model` fetched and discarded, so the artifact records what was *asked for*.
7. Coachable % divided by a denominator including `merged` (which means RETAINED).

Verified **not** to have corrupted the artifact on disk: 0 failed rows, 245 distinct `i`,
245 distinct keywords, 0 orphaned merges.

### `aggregate_cluster_verdicts.py` — regenerates a claim the docs retract

```python
:44   rows = {r["i"]: r for r in ...}                      # joins on RANK
:83   g_coach = {i: rows[i]["kind"] == "scenario" ...}     # `merged` == RETAINED, counted as sunk
```

CLAUDE.md already records this exact collapse as the cause of the phantom *"Gemma over-sinks
14.6% of the corpus"* finding, and retracts it. **The retraction reached the documentation and
never reached the code.** The script still prints `"Gemma may be over-sinking"` and computes the
lost-turn total, so anyone re-running it today reproduces the false finding verbatim. Its
docstring also claims it joins "by cluster_id", a field the artifact does not contain.

This is worse than a missing script: it is a trap that yields a confident, quotable, wrong
number.

### `export_cluster_batches.py` — not buggy, but half of a broken comparison

```python
:89  # Spread the samples across the cluster rather than taking the head: the first N
:90  # members are whatever order HDBSCAN emitted, which can be one call's worth.
```

Its stride is the **better** rule. The problem is that the adjudicator kept the head, so the
published Gemma-vs-blind-judges comparison showed the two judges **different views of the same
clusters** — a symmetric-filtering violation in the comparison the spec's headline rests on.
This file is the half that got it right.

## Recommendation

**Delete one, keep two, and fix the one that lies.**

| script | recommendation | why |
| --- | --- | --- |
| `aggregate_cluster_verdicts.py` | **FIX (preferred) or DELETE** | It manufactures a retracted finding. Leaving it as-is is the only genuinely bad option. The fix is two lines: count `scenario` **and** `merged` as retained, and join on a stable id rather than `i`. |
| `export_cluster_batches.py` | **KEEP unchanged** | Sound, and required if the blind-judge comparison is re-run symmetrically — which is now an open question. |
| `trial_adjudicate_gemini.py` | **KEEP, marked superseded** | See the caveat below; deleting it costs more than it saves. |

### Why not delete `trial_adjudicate_gemini.py`, despite being superseded

`adjudication_ab.py` replaces it for **comparison** work and is the file to use for the A/B.
But `adjudicate_gemini_min16.json` is the frozen control for **8 scripts across 4 experiments**
(routing bench, null test/R4, proper-noun check, Layer D coverage, and the clustering trial).
Deleting the only script that documents how that artifact was constructed makes those
experiments unauditable — in a repo whose entire discipline is that a number without a
reproducible producer is not a number.

**Honest caveat that weakens my own recommendation:** after today's patch the script no longer
reproduces the artifact byte-for-byte, because the representative-selection rule changed. So
"keep it for reproducibility" is only half true — it preserves the *method of record*, not
bit-reproducibility. If you would rather have one path than two, deleting it is defensible; I
lean keep because Status update 10 may need re-auditing and this is the only description of how
it was built.

### Not proposed for deletion

`adjudication_ab.py` and `clustering_bench.py` are new, tested (20 and 22 tests) and audited.
Nothing in `v1/`, `v2/`, `shared/`, `preprocessing/` or `ops/` is in scope — no production file
was touched by any of this work.

## If you accept

1. Fix `aggregate_cluster_verdicts.py`'s two lines, or delete it.
2. Add a one-line banner to `trial_adjudicate_gemini.py`: superseded by `adjudication_ab.py`
   for any comparison; single-taxonomy production only.
3. Record in CLAUDE.md that the head-vs-stride asymmetry existed, since it bears on Status
   update 10's diagnosis.

No file is deleted without your explicit go-ahead.
