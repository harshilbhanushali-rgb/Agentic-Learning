# Remediation prompt — fix and re-run, one item at a time

Paste the fenced block into a fresh Claude Code session at the repo root. It works through
`AUDIT_FINDINGS_2026-08-15.md`'s "WHAT NEEDS A RERUN" list in order, fixing and re-measuring
one item at a time.

---

```
Work through the "WHAT NEEDS A RERUN" table at the bottom of AUDIT_FINDINGS_2026-08-15.md,
ONE ITEM AT A TIME, in the order given (R1 first). Read that file and AUDIT_PROMPT.md before
starting.

STOP AFTER EACH ITEM AND REPORT. Do not batch. Every defect in this list was created by
someone changing several things at once, and the last remediation pass introduced three new
bugs while fixing seven.

FOR EACH ITEM, IN THIS ORDER:

  1. REPRODUCE THE DEFECT FIRST, on the existing artifact, before touching any code. If you
     cannot make the wrong number appear on demand, you do not understand the bug and must
     not "fix" it. Print the wrong value and the value you expect after the fix.
  2. CHANGE EXACTLY ONE THING. If a fix seems to need two changes, make them two items and
     say so. (Real precedent: removing a `[:2]` cap alongside an unrelated exclusion
     ballooned a prompt until the model returned two JSON documents and the run died.)
  3. ADD A TEST that fails against the pre-fix code. State plainly how you verified it fails
     — a test that passes both ways is worse than none.
  4. RE-RUN only what the table says to re-run. Free items must stay free: no LLM, no paid
     API, no pipeline, no DB writes.
  5. COMPARE old vs new side by side and say WHICH DIRECTION the number moved and whether it
     changes any conclusion in CLAUDE.md or the specs. If a conclusion changes, say so
     loudly; if it does not, say that too.
  6. COMMIT, then report and WAIT before starting the next item.

HARD RULES
  - Zero Postgres writes. Zero pipeline runs. `layer_d.scoring_unit` stays `moment`,
    `layer_a.pool_unit` stays `clause`. Nothing ships.
  - Before every commit, verify no production prompt drifted:
        compare every PROMPT_* constant in shared/prompts.py against `git show HEAD:` —
        the count must match and only the intended one may differ.
  - Any harness that prints a rate must print its DENOMINATOR and the run's configuration.
  - Any comparison of two arms must print every property that differs between them, not just
    the one under test.
  - If a fix makes a check STRICTER, quantify what it newly rejects and read 5 real samples
    before believing the new number. A stricter check that is also wrong looks exactly like a
    stricter check that is right.

THE FOUR MISTAKES THIS LIST EXISTS TO UNDO — do not recreate them
  - A metric computed over a narrower denominator than the claim it supports.
  - A null matched on size but not on composition.
  - A verifier enforcing a rule the prompt never stated. (Check 2 read 55.5% instead of
    83.5% because the verifier demanded NAREN-only turns while the prompt said "the CSM" and
    the transcript labels no turn "CSM".)
  - A consequence claim copied from an audit into a findings file without being re-derived.
    ("24% rejected on a misspelling" was false; the old code already discarded both bad
    names.)

WHEN YOU REACH R12 (the only paid item), STOP AND ASK. Its own row says the gate fails either
way, so it buys a defensible record rather than a different answer. Do not spend calls without
a decision.

FINALLY, when R1-R11 are done: re-read the "Explicitly NOT to be rerun" list and confirm
nothing you changed invalidates any of those four results. Report that check explicitly.
```

---

## Ordering rationale

R1–R3 are pure recomputes from artifacts already on disk — they cannot fail expensively and
they correct three published numbers. R4–R5 share one script run. R6–R11 are code-only guards
that stop the same class of defect recurring. R12 is the only item that costs money and is the
only one whose verdict is already known.


---

# R13 — NEW WORK, only after R1-R11: the anti-pattern forced choice

Not a remediation item. This is the one genuinely new idea to come out of 2026-08-15, and it
is recorded here so it is not lost. **Do not start it until R1-R11 are done and reported.**

## Why it is different from the five approaches that already failed

Every previous attempt asked a model to **grade a response against criteria**, judged alone.
That has now failed five times, and the clean measurement is `D = 1.15` — the grader cannot
judge one playbook in isolation.

It *can* discriminate when given two things to compare (77-82% when both arms shared a
prompt). The reason that was useless is that **production has no second thing** — inventing a
distractor turns the task into topic-matching, which subject matter alone decides.

`rubrics.anti_patterns` removes that objection. Measured 2026-08-15:

- **All 84 rubrics have them; 113 total, ~1.4 per rubric** (v1 avg 1.3, v2 avg 1.4).
- They are **specific**, not generic: *"Over-reliance on generic terminology ('we have a
  process for that') without providing a visual or sequential walkthrough"*; *"Presuming the
  client's value drivers instead of using diagnostic questions to uncover them."*
- Crucially they are **the opposite end of the same axis as a milestone in the same
  situation** — "presuming value drivers" vs "asking diagnostic questions".

So the forced choice — *did they do the good version or the bad version of this move?* — has
**two real options that both exist in production, both on-topic, in one situation.** Topic
cannot decide it, and nothing is invented.

## What must be held loosely

- Every anti-pattern is tagged `[inferred]` with `confidence: "inferred, unverified"`
  (required by `PROMPT_LAYER_C_V1`). They are model guesses, never clustered from evidence
  the way milestones are.
- **Nothing has ever read this column**, so their quality is entirely unmeasured.
- CLAUDE.md dismisses them — but as an *alternative scoring target*, i.e. "score anti-patterns
  instead of milestones". That is a different and weaker use than the forced choice. The
  dismissal does not carry over; say so explicitly rather than quietly contradicting it.
- 113 across 84 rubrics is thin against ~5 milestones each.

## Pre-register BEFORE running. Structural null, which is the whole attraction.

    unit        one (response, scenario) pair
    presentation the milestone and the anti-pattern, in BOTH orders (position swap)
    options     "did the good version" / "did the bad version" / "cannot tell"
    arms        MATCHED   response + its own scenario's (milestone, anti-pattern) pair
                UNRELATED same response + a DIFFERENT scenario's pair  <- the null
    sample      ~60 responses, leakage-clean stratum, seeded and stratified over
                posture vs subject-matter. Never the first N.
    ~240 scorings, ~60-80 calls, zero Postgres writes, model pinned, transport recorded.

    C1  position-swap agreement on MATCHED >= 0.75.
        THIS IS THE FIRST GATE AND THE CHEAPEST KILL. Head-to-head's equivalent came out at
        0.669 and that failure alone ended it. If the judge reverses itself when the two
        options are swapped, nothing downstream is interpretable — stop there.
    C2  matched agreement exceeds unrelated agreement by >= 0.15.
        The unrelated arm is the null: neither option is about this response's topic, so a
        judge that is reading the response should be markedly less consistent there.
    C3  "cannot tell" rate on UNRELATED must be materially higher than on MATCHED.
        A judge that never declines on an unrelated pair is not reading the response, it is
        pattern-matching the options. Report the rate; do not gate on it.

    FAIL on C1, or C2 below 0.15, and the anti-pattern route closes with the other five.
    A FAIL is a real result and must be reported as one.

## Rules carried over

- Both arms must differ in **exactly one thing** — the scenario the pair comes from. Same
  response, same order, same model, same transport. Print every property that differs.
- The 50% baseline is structural, so unlike every criteria trial there is nothing to argue
  about — but only if the "cannot tell" option exists and its rate is reported.
- Read 10 real samples before believing any aggregate.
