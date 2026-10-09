# Measurement-integrity audit — shared brief

You are auditing part of `c:\PF\Joveo\CS-platform\Brain\` for bugs that would make a result
WRONG while still printing something plausible. This is a correctness-of-the-science audit,
not a style review.

## HARD RULES — non-negotiable

- Do NOT fix anything. Do NOT edit, refactor or "clean up" any file.
- Do NOT run the pipeline, any calibration script, or any test that hits the network.
- Do NOT connect to Postgres, Pinecone, or any LLM API. Reading `Brain/artifacts/*.json` is fine.
- Do NOT commit. Do NOT run `git` write commands.
- Report only. A wrong fix is worse than a reported bug.
- Being right matters more than being thorough. Mark speculation as speculation.
- Do NOT report style, typing, naming, or performance issues. Only defects that move a NUMBER.

## The structural reason this audit exists

A bug in production code crashes or renders something visibly wrong. A bug in measurement code
produces a *plausible number* and nothing else happens. There is no feedback signal, so these are
found only by deliberate inspection — and they concentrate in *comparisons* rather than *counts*,
because a ratio has two chances to be wrong and one is usually invisible.

Every harness in this repo that has been carefully audited turned out to contain a defect that
moved a number. Assume yours does too, and look until you can say specifically why it does not.

## BUG TAXONOMY — every one of these is a REAL defect found in this repo. Hunt siblings.

1. **ASYMMETRIC ARMS.** Two arms of a comparison differ in more than the variable under test.
   Real: matched arm had 5.08 criteria/pair vs unrelated 3.64 (matched on content, nobody checked
   size). Real: the ceiling compared A3 against B across DIFFERENT response populations. Real:
   trial_head_to_head applied a substantive-text filter to one side only.
   CHECK: for each arm, enumerate EVERY property — population, size, length, model, prompt,
   sampling frame, leakage exposure — and diff the lists.

2. **A METRIC OVER A BIASED SUBSET.** The denominator is narrower than the claim it supports.
   Real: full-hit quotes were blanked, so a "verification rate" covered 26 of 239 credits and was
   reported as if it covered all. Real: a union rate used ATTEMPTED criteria, not the rubric's
   actual criteria.
   CHECK: for every printed rate, state its true denominator and compare it to the sentence
   printed above it.

3. **NUMBERING / BASE MISMATCH ACROSS A BOUNDARY.** Real: `Turn.index` is 0-based and
   `kb_pairs.turn_index` stores it verbatim, while a harness labelled turns 1-based, so every
   pointer sent to the model was one turn early.
   CHECK: every place an index crosses between storage, display and a model's reply.

4. **NAME THAT NEVER MATCHES.** Real: code filtered for role `"OTHER_JOVEO"` when the enum member
   is `"JOVEO_OTHER"`, so the filter silently admitted nothing and no error was raised.
   CHECK: every string compared against an enum, a DB value or a dict key — does the literal
   actually exist? Grep the definition, do not trust the spelling.

5. **A METRIC THAT CANNOT FAIL, or that rewards the thing being removed.** Real:
   `cross_scenario_coverage` goes to 1.0 by construction as a threshold falls. Real: coherence-lift
   correlates +0.527 with content-free share, so it scores junk HIGHEST.
   CHECK: ask what value this metric takes in the degenerate case, and whether a known-bad input
   scores well.

6. **A NULL THAT IS NOT MATCHED ON WHAT MATTERS.** Real: a size-matched null was not
   composition-matched, so "beats the null" partly meant "has longer turns" (corr +0.65).
   CHECK: what does the null control for, and what does it leave free?

7. **TWO ESTIMATORS REPORTED AS ONE NUMBER.** Real: a point estimate was pooled while its bootstrap
   CI was over per-item means, so a CI could exclude its own point estimate. Real: a bootstrap
   silently discarded resamples with a zero denominator, truncating the CI.
   CHECK: is the point estimate computed the same way as its uncertainty?

8. **COLLAPSING A MULTI-VALUED ENUM TO A BOOLEAN.** Real: testing `kind == "scenario"` against a
   four-valued enum counted `"merged"` (retained) as a sink and invented a "Gemma over-sinks 14.6%
   of the corpus" finding that cost a whole prompt-fix cycle.
   CHECK: print the full cross-tab instead of a boolean.

9. **SILENT SHORT-CIRCUIT.** Real: a ranking function returns rows UNRANKED and without the score
   field when `limit >= len(rows)`, so the one check that proved the ranking worked was measuring
   nothing.
   CHECK: every early return — does the caller distinguish it from the normal path?

10. **SILENT DROP.** Rows skipped by a try/except, a bounds check or a join miss, with no counter
    and no warning.
    CHECK: does anything report how many inputs did not make it to the output?

11. **SHADOWING / OVERWRITE.** Real: an artifact `Path` was shadowed by a loop variable; a `--tag`
    applied to the checkpoint path but not the output path, so a control run overwrote a headline
    artifact; a `--smoke` run overwrites the real artifact and the report never says it was smoke.
    CHECK: can a cheap run destroy an expensive one? Is the run's configuration recorded IN the
    artifact and PRINTED in the report?

12. **CHECKPOINT KEY TOO WEAK.** Real: a resume guard keyed only on item count would silently reuse
    records produced by a different model or a different holdout setting.
    CHECK: does the key include every flag that changes what the records mean?

13. **SAMPLING THAT IS NOT A SAMPLE.** Real: `--limit N` took the first N alphabetically, which
    returned only subject-matter scenarios because every posture key starts with `client_`.
    CHECK: every subset selector — what does it systematically EXCLUDE?

14. **CORRELATED OBSERVATIONS TREATED AS INDEPENDENT.** Real: 45 (call, scenario) pairs spanned
    only 28 scenarios sharing rubrics, then an exact binomial assumed 45 independent trials.
    CHECK: what is the true effective n?

15. **HARDCODED COUNT DRESSED AS A FORMULA.** Real: `min_cluster_size = max(3, min(n//10, 50))` is
    a hardcoded 50 for any corpus >= 500, so granularity depends on pool SIZE.
    CHECK: does this knob scale with the data, or does it freeze?

## OUTPUT — this is mandatory and exact

Write your findings to the file path given in your task prompt, as Markdown. Structure:

```
## <your batch name>

Files audited: <list>

### FINDINGS

#### 1. <one-line title>
- **File:line**: `path:NN`
- **What is wrong**: 1-2 sentences.
- **What number it corrupts, and in WHICH DIRECTION**: a finding with no consequence is noise —
  say so and drop it. Name the number, and whether the defect inflates or deflates it.
- **Confidence**: certain / likely / speculative
- **Cheapest way to verify**: a specific command, grep, or file to read.

### CLEAN
State explicitly where you found NOTHING. A clean category is a real result and stops the next
person re-checking it. Be specific: "I checked X for taxonomy item N and it is correct because Y."
```

Rank findings by how badly the result is distorted, worst first. Do not pad. Three real findings
beat twelve speculative ones. If a file is genuinely clean, say so and move on.

Then return to the orchestrator ONLY a compact summary: the count of findings by confidence, and
a one-line title for each finding worth surfacing. Do not paste the full report back.
