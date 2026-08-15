# Measurement-integrity audit — reusable prompt

Paste the block below into a fresh Claude Code session at the repo root. It runs a
subagent-driven audit of everything in `Brain/` that produces or verifies a number.

**Why this exists.** On 2026-08-15 a single independent reviewer was pointed at 8 files and
returned **16 findings, at least 4 material** — after the author had already self-found 6 in
the same files that day. Every harness in this repo that has been carefully audited has turned
out to contain a defect that moved a number. The audit rate is far below 100%; the find rate
when audited is close to it.

**The structural reason, which the prompt leans on.** A bug in production code crashes or
renders something visibly wrong. A bug in measurement code produces a *plausible number* and
nothing else happens. There is no feedback signal, so these are found only by deliberate
inspection — and they concentrate in *comparisons* rather than *counts*, because a ratio has
two chances to be wrong and one is usually invisible.

---

## THE PROMPT

```
Audit every part of Brain/ that produces or verifies a number, for bugs that would make a
result WRONG while still printing something plausible. This is a correctness-of-the-science
audit, not a style review.

HARD RULES — apply to you and to every subagent you spawn:
  - Do NOT fix anything. Do NOT edit, refactor or "clean up" any file.
  - Do NOT run the pipeline, any calibration script, or any test that hits the network.
  - Do NOT connect to Postgres, Pinecone, or any LLM API. Reading artifacts/*.json is fine.
  - Do NOT commit.
  - Report only. A wrong fix is worse than a reported bug.

RUN IT AS A FAN-OUT. Spawn subagents in waves, batched 4-6 files each so every agent can read
its files properly. Give each subagent the BUG TAXONOMY below verbatim — it is the highest-
value part of this prompt, because every entry is a real defect found in this repo.

ALREADY AUDITED 2026-08-15 — EXCLUDE THESE, they are done:
    ego_trap/call_scoring.py
    ego_trap/milestone_scoring.py
    calibration/trial_call_scoring.py
    calibration/trial_grader_inputs.py
    calibration/null_test_taxonomy.py
    calibration/audit_null_instrument.py
    calibration/flag_proper_noun_clusters.py
    calibration/diagnose_rubric_level.py

WAVE 1 — the pytest suite (Brain/tests/, ~35 files). NEVER AUDITED.
  Different failure mode from the harnesses, and invisible: a unit test that cannot fail looks
  identical to one that passes. Look for:
    - tests that assert the implementation back to itself (mock returns X, assert X)
    - tests whose assertion would hold even if the function body were deleted or returned a
      constant
    - hardcoded expected values that encode a threshold which has since moved. Precedent:
      test_ambiguous_trigger_keeps_the_near_ties baked in a 0.95 weight that silently meant
      "comfortably above the cutoff" only while relative_margin was 0.85
    - tests that pin CURRENT behaviour without establishing it is CORRECT behaviour
    - fixtures that drifted from the real object's shape (a dataclass gained a field, the
      fixture did not, and the test now exercises a shape production never sees)
    - a test named for one property that asserts another
  Also report, per file: does any test here actually constrain a NUMBER this project reports?

WAVE 2 — the remaining calibration harnesses (Brain/calibration/, ~36 files after exclusions).
  These produce the numbers in CLAUDE.md and the specs. Apply the full BUG TAXONOMY.

WAVE 3 — production code that computes or filters what gets measured:
  shared/storage.py (every WHERE clause — a predicate IS a population choice),
  shared/relative_match.py, shared/cluster_evidence.py, shared/scenario_vectors.py,
  shared/tuning.py, v1/layer_b.py, v2/layer_a.py, v2/layer_c.py,
  preprocessing/embedder.py, preprocessing/transcript_parser.py, preprocessing/segmenter.py,
  ego_trap/pipeline.py, ego_trap/signal_check.py, ego_trap/gap_output.py,
  ego_trap/rubric_lookup.py, response_taxonomy_auto_pass.py
  Focus on anything that silently narrows a population, and on numbering/base conventions
  crossing module boundaries.

WAVE 4 — PROVENANCE. Take the 15 most load-bearing numbers asserted in CLAUDE.md,
  OPEN_PROBLEMS.md and docs/superpowers/specs/*.md, and for each ask: which script produced
  it, does that script still compute it that way, and does the claim the prose makes match
  what the code measures? Several numbers in CLAUDE.md have already been retracted this way
  (the ceiling's "1.2:1", the taxonomy's "31%", a "trial_layer_c_arms was circular" claim).
  Report any number whose prose overstates what its code supports.

BUG TAXONOMY — every one of these is a REAL defect found in this repo. Hunt siblings.

 1. ASYMMETRIC ARMS. Two arms of a comparison differ in more than the variable under test.
    Real: matched arm had 5.08 criteria/pair vs unrelated 3.64 (matched on content, nobody
    checked size). Real: the ceiling compared A3 against B across DIFFERENT response
    populations. Real: trial_head_to_head applied a substantive-text filter to one side only.
    CHECK: for each arm, enumerate EVERY property — population, size, length, model, prompt,
    sampling frame, leakage exposure — and diff the lists.

 2. A METRIC OVER A BIASED SUBSET. The denominator is narrower than the claim it supports.
    Real: full-hit quotes were blanked, so a "verification rate" covered 26 of 239 credits and
    was reported as if it covered all. Real: a union rate used ATTEMPTED criteria, not the
    rubric's actual criteria.
    CHECK: for every printed rate, state its true denominator and compare it to the sentence
    printed above it.

 3. NUMBERING / BASE MISMATCH ACROSS A BOUNDARY. Real: Turn.index is 0-based and
    kb_pairs.turn_index stores it verbatim, while a harness labelled turns 1-based, so every
    pointer sent to the model was one turn early.
    CHECK: every place an index crosses between storage, display and a model's reply.

 4. NAME THAT NEVER MATCHES. Real: code filtered for role "OTHER_JOVEO" when the enum member
    is "JOVEO_OTHER", so the filter silently admitted nothing and no error was raised.
    CHECK: every string compared against an enum, a DB value or a dict key — does the literal
    actually exist? Grep the definition, do not trust the spelling.

 5. A METRIC THAT CANNOT FAIL, or that rewards the thing being removed. Real:
    cross_scenario_coverage goes to 1.0 by construction as a threshold falls. Real:
    coherence-lift correlates +0.527 with content-free share, so it scores junk HIGHEST.
    CHECK: ask what value this metric takes in the degenerate case, and whether a known-bad
    input scores well.

 6. A NULL THAT IS NOT MATCHED ON WHAT MATTERS. Real: a size-matched null was not
    composition-matched, so "beats the null" partly meant "has longer turns" (corr +0.65).
    CHECK: what does the null control for, and what does it leave free?

 7. TWO ESTIMATORS REPORTED AS ONE NUMBER. Real: a point estimate was pooled while its
    bootstrap CI was over per-item means, so a CI could exclude its own point estimate.
    Real: a bootstrap silently discarded resamples with a zero denominator, truncating the CI.
    CHECK: is the point estimate computed the same way as its uncertainty?

 8. COLLAPSING A MULTI-VALUED ENUM TO A BOOLEAN. Real: testing kind == "scenario" against a
    four-valued enum counted "merged" (retained) as a sink and invented a
    "Gemma over-sinks 14.6% of the corpus" finding that cost a whole prompt-fix cycle.
    CHECK: print the full cross-tab instead of a boolean.

 9. SILENT SHORT-CIRCUIT. Real: a ranking function returns rows UNRANKED and without the
    score field when limit >= len(rows), so the one check that proved the ranking worked was
    measuring nothing.
    CHECK: every early return — does the caller distinguish it from the normal path?

10. SILENT DROP. Rows skipped by a try/except, a bounds check or a join miss, with no counter
    and no warning. CHECK: does anything report how many inputs did not make it to the output?

11. SHADOWING / OVERWRITE. Real: an artifact Path was shadowed by a loop variable; a --tag
    applied to the checkpoint path but not the output path, so a control run overwrote a
    headline artifact; a --smoke run overwrites the real artifact and the report never says
    it was smoke.
    CHECK: can a cheap run destroy an expensive one? Is the run's configuration recorded IN
    the artifact and PRINTED in the report?

12. CHECKPOINT KEY TOO WEAK. Real: a resume guard keyed only on item count would silently
    reuse records produced by a different model or a different holdout setting.
    CHECK: does the key include every flag that changes what the records mean?

13. SAMPLING THAT IS NOT A SAMPLE. Real: --limit N took the first N alphabetically, which
    returned only subject-matter scenarios because every posture key starts with "client_".
    CHECK: every subset selector — what does it systematically EXCLUDE?

14. CORRELATED OBSERVATIONS TREATED AS INDEPENDENT. Real: 45 (call, scenario) pairs spanned
    only 28 scenarios sharing rubrics, then an exact binomial assumed 45 independent trials.
    CHECK: what is the true effective n?

15. HARDCODED COUNT DRESSED AS A FORMULA. Real: min_cluster_size = max(3, min(n//10, 50)) is
    a hardcoded 50 for any corpus >= 500, so granularity depends on pool SIZE.
    CHECK: does this knob scale with the data, or does it freeze?

OUTPUT. One consolidated report at repo root: AUDIT_FINDINGS.md, grouped by wave, each finding:
  - **File:line**
  - **What is wrong** (1-2 sentences)
  - **What number it corrupts, and in WHICH DIRECTION** — a finding with no consequence is
    noise; say so and drop it
  - **Confidence**: certain / likely / speculative
  - **Cheapest way to verify**
Rank within each wave by how badly the result is distorted. State explicitly where you found
NOTHING — a clean category is a real result and stops the next person re-checking it.

Being right matters more than being thorough. Mark speculation as speculation.
```

---

## What the 2026-08-15 audit actually covered

Recorded so the next audit does not assume more was done than was.

| area | files | audited |
| --- | --- | --- |
| `Brain/tests/` pytest suite | 35 | **0** |
| `Brain/calibration/` harnesses | 42 | 6 |
| production modules | 55 | 2 |
| recorded numbers in CLAUDE.md / specs | — | **0** |

It was **not** an audit of "the tests". It was an audit of six measurement harnesses plus
`ego_trap/call_scoring.py` and `ego_trap/milestone_scoring.py`. The pytest suite, the other 36
harnesses, the rest of the pipeline, and the provenance of every published number were all
untouched.
