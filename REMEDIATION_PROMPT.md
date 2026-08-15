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
