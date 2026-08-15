# Audit findings — 2026-08-15 measurement-integrity review

An independent reviewer was pointed at 8 files (6 calibration harnesses + `call_scoring.py` +
`milestone_scoring.py`) and returned 16 numbered findings plus 6 smaller items. The author had
already self-found 6 defects in the same files earlier that day.

**Scope, stated so nobody assumes more:** the pytest suite (35 files) was NOT audited, 36 of 42
calibration harnesses were NOT audited, 53 of 55 production modules were NOT audited, and the
provenance of published numbers was NOT audited. See `AUDIT_PROMPT.md` to run the rest.

**Status key:** `FIXED` · `OPEN` · `LATENT` (real in code, did not fire in the shipped run) ·
`WONTFIX` (understood and accepted)

---

## Affected the 2026-08-15 call-scoring run (45 calls, check1 73.2%, check2 81.3%)

### F1 — `csm_roles` never matched: enum member is `JOVEO_OTHER`, code asked for `OTHER_JOVEO`
`calibration/trial_call_scoring.py:351`. `{"NAREN","CSM","OTHER_JOVEO"} ∩ {NAREN, JOVEO_OTHER,
CLIENT}` = `{"NAREN"}` always. No error, no warning. Of cited turns: NAREN 116 / JOVEO_OTHER 42
/ CLIENT 14 — **24% rejected purely on a misspelling**; 30 of check 2's 49 failures are this.
**Corrupts check 2 downward.** Confidence: certain, verified. **Status: FIXED.**

### F2 — `at_turn` evidence was never role-checked while `across_turns` was
`ego_trap/call_scoring.py:227-233`. The quote only had to appear in the ±2-turn window, which
necessarily sweeps in client turns. **12 passing credits quote the CLIENT**, e.g. *"Would it
help, Naren, if we sync same time tomorrow?"* credited as a CSM milestone. So check 2 pooled an
over-estimate with F1's under-estimate. **"81.3% locatable" is not a single quantity.**
Confidence: certain. **Status: FIXED.**

### F3 — the unrelated arm's benchmark could come from the very call being scored
`calibration/trial_call_scoring.py:258, 333`. A call is leakage-clean for `k`, but the
unrelated arm uses `bench[partner[k]]`, under no such constraint — so the "expert reference
answer" can be text spoken in the transcript being searched. `trial_grader_inputs.py:442`
already applies this exclusion; the two harnesses disagreed. **Inflates the unrelated arm →
depresses check 1**, so fixing can only strengthen the 73.2%. **Status: FIXED.**

### F4 — the leakage-clean holdout was derived from a length-filtered query
`calibration/trial_call_scoring.py:247-259`; `trial_grader_inputs.py:374-384`. `primary_calls`
was built `WHERE length(trim(trigger_text)) > 20`, but `storage.get_naren_responses_for_scenario`
— Layer C's actual clause pool — has no length predicate. A call whose only primary
contribution had a short trigger was misclassified as clean. **Admits leaked calls → inflates
W(matched) → inflates check 1.** **Status: FIXED in trial_call_scoring; OPEN in
trial_grader_inputs.**

### F5 — the sign test treated correlated observations as independent
`calibration/trial_call_scoring.py:132-143`. 45 pairs spanned only **28 distinct scenarios**,
some appearing 4×, sharing both the rubric and the partner rubric. An exact binomial assumed 45
independent trials. **Anti-conservative p; reported p=0.0043 against a p<0.05 gate with a
marginal 73.2% vs a 70% bar.** Note `trial_grader_inputs.sign_test` deliberately aggregates to
one observation per scenario for exactly this reason — same name, different unit.
**Status: FIXED (now collapses by scenario; both figures reported).**

### F7 — `--smoke` overwrote the headline artifact and the report never said so
`trial_call_scoring.py` had no `--tag` at all; both trials store `"smoke"` in the payload and
neither `report()` printed it. A 3-call path test silently replaced a real result and `--load`
rendered it identically. The shipped artifact was verified genuine (`smoke:false, n_calls:45`)
only by opening the JSON. **Status: FIXED (tag + refuses to overwrite a real artifact + prints
run config).**

### F10 — check 2's bar says "in BOTH arms"; the code pooled them
`trial_call_scoring.py:174, 387`. Per-arm rates existed and were summed away. Measured: matched
83.8%, unrelated 78.1%, pooled 81.3%. No verdict flip here, but a pooled 96% could hide an arm
at 88%. **Status: FIXED (gates on the worse arm).**

### Smaller items in the same file
- **NULL `turn_index` became a pointer at turn 1** rather than being omitted — fabricates a
  location. `:332`. **FIXED (omitted).**
- **`criteria_per_arm` guard computed over a different population than check 1 tested** — could
  print a spurious CONFOUNDED banner or a false reassurance. Did not fire (5.511 both sides).
  **FIXED.**
- **`scenarios_per_request=3` hardcoded** while `--per-call` defaults to 2. **FIXED.**
- **Pooled failure dicts carry no call id**, so a flagged credit can't be located. **FIXED.**

---

## Affected other results, not this run

### F6 — union rate used *attempted* criteria, not the rubric's criteria — `OPEN`
`diagnose_rubric_level.py:150-154`. `n_criteria_in_rubric` is computed and never used. 395 true
criteria vs 378 perf rows; aggregate union **0.479 as computed vs 0.458 true**. **Overstates
union → pushes the diagnosis toward "denominator inflation" and away from "dead criteria".**
The conclusion drawn was *dead criteria*, so correcting this **strengthens** it.

### F9 — the moment trial scored both arms of a response in ONE prompt — `OPEN, HIGH PRIORITY`
`trial_grader_inputs.py:441-451`. Items are built matched-then-unrelated per response with
`batch_size=6`, so the grader sees one response twice, against two rubrics, side by side, and
can contrast them. Production never does. **Plausibly inflates D in every condition** — and
this is the 77.4%/82.3% result that everything downstream leans on. Confidence: likely.

### F8 — checkpoint keyed only on `n_items` — `LATENT`
`trial_grader_inputs.py:458-462`. Model, condition subset and `--holdout` are in neither the key
nor the payload; `--holdout` yields the same `n_items`, so it could resume leaky records and
label them clean. Verified not triggered in the shipped artifacts.

### F11 — bootstrap discarded zero-denominator resamples — `OPEN`
`trial_grader_inputs.py:226-233`. Drops exactly the resamples with the largest D, so the CI is
conditional and its coverage is not 95%; the count dropped is not reported. Compounds the known
pooled-vs-per-item estimator mismatch.

### F12 — `null_test_taxonomy`'s null is size-matched but not composition-matched — `OPEN`
`null_test_taxonomy.py:92, 172-182`. Members are turns *selected* for having a coachable best
match; the null draws from the whole pool including 33% content-free turns. The arms accept
different fractions (46.7% vs 35.6%), so the nulls are not equally hard. **Favours whichever
taxonomy accepts fewer turns — i.e. turn mode.**

### F13 — rigged-arm join verifies only cluster COUNT — `LATENT`
`null_test_taxonomy.py:217-220`. Its sibling `flag_proper_noun_clusters.py:331-340` verifies
`n_items`, `calls` and `keywords` position-for-position. Stable sort means equal-`n` ties could
silently misalign.

### F14 — Signals B and C are NaN for every bigram keyword — `OPEN`
`flag_proper_noun_clusters.py:345-349, 365-366`. BERTopic emits bigrams (`ngram_range=(1,2)`)
but `turn_words` holds unigrams only. The motivating example is literally `happy dance`, which
printed `nan%`. **Understates proper-noun rate on exactly the worst cases.** Signal A (the
primary measure, and the one the 6/38 count came from) is unaffected.

### F15 — NaN propagation and unreported multiplicity — `OPEN`
`flag_proper_noun_clusters.py:124-129, 168-172, 181`. A cluster with zero accounted turns turns
a whole summary row into `nan`, makes the sort order undefined, and silently un-flags itself.
Separately: at ~245 clusters tested against a p99 threshold, **2-3 flags are expected by
chance** and the report makes no multiplicity note.

### F16 — milestone join drops rows silently, no staleness guard — `OPEN`
`diagnose_rubric_level.py:104-112`. The `int(str(mid).lstrip("M")) - 1` parse is safe for every
id the code produces, but every failure is discarded with no counter. Larger hazard:
`upsert_rubric` keeps `rubric_id` stable while replacing `milestones`, and `milestone_id` is the
array POSITION — so if Layer C ran after the Layer D run, counters and text describe different
criteria. Verified not active for the shipped artifact (4181 attempts / 378 criteria match).

### Cross-cutting — `OPEN`
- `trial_call_scoring.PIN_MODEL` is `gemini-3.1-flash-lite`, `trial_grader_inputs.PIN_MODEL` is
  `gemini-3.5-flash-lite`. The call-scoring report compares its W to moment mode's 0.078 and
  warns the *unit* differs, not the *model*.
- `audit_null_instrument.py:80` hardcodes `Path("recordings")` while its sibling takes
  `--recordings`; a mismatch would join recomputed memberships against mismatched lifts.

---

## Categories the reviewer found CLEAN

Recorded so they are not re-checked.

- **New kwargs on `milestone_scoring` preserve prior behaviour exactly.** `situated_fields=None`
  routes to the unmodified prompt; `model`/`fallback_models` default to the module constants;
  all three appended after existing params; the sole production caller passes by keyword.
  **Production is byte-identical when the switches are omitted.**
- **No surviving off-by-one in `verify_evidence`.** Window arithmetic correct at both ends,
  `turn` and `turns` consistently 1-based, `Turn.index` genuinely the list position.
- **`size_matched_partner` cannot return the same scenario** and cannot bias which arm wins.
- **`derange` in `trial_grader_inputs` is a permutation**, so the criteria-count confound that
  motivated `size_matched_partner` does not reproduce there in aggregate.
- **Tie handling** in both sign tests matches what the reports claim.
- **Division-by-zero / NaN** guarded everywhere except F15's two paths.


---

## Second audit (2026-08-15): the fixes were themselves audited, and two of my reports were wrong

### CHECK 2's 55.5% IS MY ROLE POLICY, NOT FABRICATION
Same shipped artifact, three role policies, reproduced independently:

| role policy | pooled check 2 |
| --- | --- |
| pre-fix logic (no role check on `at_turn`) | 82.0% |
| **as shipped, `("NAREN",)`** | **55.5%** |
| `("NAREN","JOVEO_OTHER")` | **83.5%** |

Cited-turn mix: **NAREN 161 / JOVEO_OTHER 74 / CLIENT 14** - so 56 of 89 failures are a Joveo
colleague, not the client.

**The cause is a prompt/verifier mismatch of my own making.** `PROMPT_STEP3_CALL_LEVEL_BATCH`
says *"Every turn number you give must be a turn where the CSM is speaking"*, but the
transcript the model sees is labelled `NAREN` / `JOVEO_OTHER` / `CLIENT` - **no turn is
labelled `CSM`**, and nothing tells it only `NAREN` counts. The model is failed for guessing at
a rule never stated. Genuine client-quote fabrication is ~4-6%, not ~45%.

**Check 2 is UNINTERPRETABLE as run, not FAILED.** Neither number is the answer until the
prompt and the verifier enforce the same rule and the run is repeated. `scored_roles` must
become a recorded, printed flag rather than a literal at the call site.

### F2 IS OVER-CORRECTED: 43% of the "fabricated" list is false accusation
Switching from a joined-window match to per-turn matching also rejects quotes spanning a turn
boundary - **8 of 150 `at_turn` credits** - and because `found_elsewhere` is per-turn too, they
print under *"appear NOWHERE in the transcript (fabricated)"*. **9 of the 21 quotes so labelled
are verbatim in the transcript**, independently confirmed. Every fabrication count reported
today is inflated by this.

### F1's RECORDED CONSEQUENCE IS RETRACTED
The old expression was `tuple({roles} & {"NAREN","CSM","OTHER_JOVEO"}) or ("NAREN",)` - the
intersection **already discarded** both bad names, so it always evaluated to `("NAREN",)`. The
misspelling never admitted or rejected anything; the fix is correct as code but a **behavioural
no-op**. "24% rejected purely on a misspelling / 30 of 49 failures" came from the first audit
and was propagated into this file without being checked.

### Other confirmed defects in the fixes
- **Gateway provenance is null and the transport is recorded nowhere.** `scored_by` is `None`
  for every verdict; neither artifact nor report records that `--gateway` was used.
- **`max_output_tokens` is halved on the gateway path** - 8192 vs the 16384 the scorers set.
  Latent here only because the run used `--per-call 1`; output length is the documented
  binding constraint and truncation silently manufactures misses.
- **The gateway forces `response_format=json_object` while all three Step 3 prompts ask for a
  top-level ARRAY.** Worked this run; unverified for the array shape.
- **F9's sort makes every batch single-arm**, so a dropped batch removes items from one arm
  only; `D`'s point estimate then pools unequal populations while its CI uses the paired
  subset. Twin separation also **fails when `n_resp < batch_size`** - exactly the `--smoke`
  path.
- **The `criteria_per_arm` guard was recorded FIXED but never touched** (git-verified
  byte-identical); it still measures a different population than check 1 tests.
- **Chunk-failure tolerance is safe downstream but uncounted**, biased toward long prompts, and
  made permanent by the checkpoint; a bare `except Exception` now swallows quota exhaustion.
- **`trigger_turns` caps `[:4]` before filtering NULLs** - the same filter-vs-cap ordering the
  commit warns about four lines below.

### Verified CORRECT
F3 (benchmark exclusion, both arms, filter-then-cap), F5 (per-scenario collapse, and the gate
reads it), F10 (gates on the worse arm), NULL turn omission, `scenarios_per_request` following
`--per-call`, failures carrying their call id, F9 twin separation for `n_resp >= batch_size`,
F4's holdout widening, and **production byte-identical when `chat` is omitted**. The three new
tests are non-vacuous - all three fail against the pre-fix code - but nothing pins the
span-boundary case, so F2's over-correction is untestable by the suite.


---

# WHAT NEEDS A RERUN

Ordered cheapest-first. `REMEDIATION_PROMPT.md` drives this list one item at a time.

## Free - no LLM, no paid API. Vectors and artifacts are cached.

| # | fix | rerun | why the current number is wrong |
| --- | --- | --- | --- |
| R1 | `diagnose_rubric_level.py` union denominator (F6) | recompute from `rubric_level_diagnosis.json` | uses ATTEMPTED criteria, not the rubric's. 0.479 as computed vs 0.458 true. Conclusion (dead criteria) is UNCHANGED and in fact strengthened. |
| R2 | `flag_proper_noun_clusters.py` bigram keywords (F14) + NaN propagation (F15) | recompute from `proper_noun_clusters.json` | Signals B and C are NaN for every multiword keyword - including `happy dance`, the motivating example. **Signal A and the 6-of-38 headline are unaffected.** |
| R3 | `trial_grader_inputs.py` bootstrap CI (F11) + pooled-vs-per-item estimator | recompute from `grader_inputs_trial_clean_v2.json` | discards zero-denominator resamples, so the CI is conditional; point estimate and CI use different estimators. |
| R4 | `null_test_taxonomy.py` composition-matched null (F12) | rerun the script (~15 min, cached vectors) | the null is size-matched but NOT composition-matched, and the arms accept different turn fractions (46.7% vs 35.6%), so it favours whichever taxonomy accepts fewer turns. **The 20% vs 29% comparison is not readable until this is fixed.** |
| R5 | `null_test_taxonomy.py` position-verified join (F13) | same rerun as R4 | verifies cluster COUNT only; its sibling verifies n_items/calls/keywords position-for-position. |

## Code-only - fix and test, nothing to rerun

| # | fix | why |
| --- | --- | --- |
| R6 | `--tag` + refuse-to-overwrite in `trial_call_scoring.py` (F7) | recorded FIXED and never implemented. A 45-call artifact was already destroyed by a 30-call run under the same filename. |
| R7 | gateway provenance + `max_output_tokens` | `scored_by` is `None` on the gateway path and no artifact records the transport; `chat_json`'s 8192 default halves the 16384 the scorers set. |
| R8 | checkpoint keys (F8) | neither trial's key includes model, transport, `--holdout` or condition subset, so a resume can blend them invisibly. |
| R9 | `criteria_per_arm` guard population | recorded FIXED, git-verified untouched; measures a different population than check 1 tests. |
| R10 | `trigger_turns` `[:4]` before NULL filter | same filter-vs-cap ordering the commit warns about four lines below. |
| R11 | F9 batch balance reporting | single-arm batches mean one dropped batch unbalances the arms; nothing counts failures. Twin separation also fails when `n_resp < batch_size` - the `--smoke` path. |

## Found while auditing the R1 fix (2026-08-15) - needs a DB read, so not free

| # | fix | rerun | why the current number is wrong |
| --- | --- | --- | --- |
| R14 | `diagnose_rubric_level.py` rubric POPULATION, not just the per-rubric denominator | one read-only DB run (`_fetch_rows` already SELECTs the whole `rubrics` table, so no new query) | R1 fixed the denominator *within* a rubric and left the denominator *across* rubrics biased. `unions` is built from the perf rows, so a rubric Layer D never attempted contributes nothing and vanishes: **78 of the 84 live rubrics appear, and the 6 missing ones' criteria are not in the 395.** Every union is conditional on "Layer D reached this rubric" and so is an over-estimate for the rubric table. Direction is the same as R1 - correcting it lowers the union again and further strengthens the dead-criteria reading. The artifact cannot fix this: an unattempted rubric is absent from it by construction. **MEASURED 2026-08-15, read-only: 84 rubrics / 405 criteria; union aggregate 45.8% -> 44.7%, mean 45% -> 43%, median 43% -> 39%. 27 criteria never scored. 23 of 82 non-empty rubrics have not one criterion ever satisfied. Conclusion unchanged and strengthened.** |

Two facts that fell out of the same query and are not defects in this file:

- **Two rubrics hold ZERO criteria** - `operational_burden_expression` and
  `integration_governance_and_constraints_discovery`, both v1. Their union is undefined (0/0)
  and any per-rubric mean must exclude them or silently score them 0.
- **F16 did not fire, at all.** The join's three drop paths were measured over the live tables:
  378 groups in, 378 out, zero unparseable ids, zero positions beyond their rubric, zero
  rubric_ids missing from `rubrics`. No rubric was created after it was scored. The silent-drop
  hazard is real in the code and inactive in this data - so F16 stays open as a guard to add,
  but no published number is affected by it.

| R15 | `flag_proper_noun_clusters.py` lookup tokeniser must be the VECTORISER's tokeniser | rerun the script (free, ~10 min) | Found while fixing F14/R2a. `_WORD` is `[a-z][a-z0-9'\-]*`; the keyword vocabulary comes from sklearn `CountVectorizer`'s `(?u)\b\w\w+\b`. Apostrophes stay inside a token, so the vocabulary's `dont` / `dont know` / `agree dont` / `alright theres` can never match `don't`; and a leading letter is required, so `18` / `2021` / `20 20` never match. **87 distinct keywords are still NaN after R2a; 15 of the 86 absent ones ARE found under sklearn's own pattern.** Same family as F14, but it moves existing non-NaN values too, so it needs its own before/after. |

## Paid - and currently NOT worth it

| # | fix | rerun | verdict |
| --- | --- | --- | --- |
| R12 | align `PROMPT_STEP3_CALL_LEVEL_BATCH` with the verifier's role rule, make `scored_roles` a flag, make quote matching span-aware (F2) | ~60 calls | Check 2 is corrupted, not failed. Fixed it reads ~83.5%, ~88% with the span fix - **still under the 95% bar. The gate fails either way.** Do it for a defensible record, not for a different answer. |

## Explicitly NOT to be rerun

- **Moment trial** - `D = 1.15`, 52.8% over 73 scenarios / 2,976 attempts, clean harness. This is the real result and it confirms the ceiling's original 1.2:1.
- **Call gate check 1** - 81.0%, arms scored in separate requests, unaffected by every finding.
- **87 dead criteria / 24% wasted effort** - derived twice by independent routes.
- **The earlier 77.4% / 82.3%** - an artifact of both arms sharing a prompt. Superseded. Do not rerun, do not cite.
