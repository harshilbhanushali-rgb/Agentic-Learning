# Continue the measurement-integrity remediation — prompt for a fresh session

Paste the fenced block into a new Claude Code session at the repo root.

State as of 2026-08-15: **R1, R14, R2a, R2b, R2c, R3a, R3b are DONE and committed.**
**R15 is open** (found while fixing R2a). **R4–R12 have not been started.** R13 is new work,
gated behind R1–R11.

---

```
Continue the remediation in AUDIT_FINDINGS_2026-08-15.md. Read that file first, then
AUDIT_PROMPT.md and this file's "state" note.

DONE ALREADY -- do not redo: R1, R14, R2a, R2b, R2c, R3a, R3b. Their status, the numbers
that moved, and every observation from them are in AUDIT_FINDINGS_2026-08-15.md under
"REMEDIATION LOG". The generalisable engineering facts are in CLAUDE.md under
"Measurement-harness remediation, R1-R3". Read both before touching anything -- several of
them will save you a wrong fix or a paid mistake.

NEXT: R4 and R5 (they share one script run), then R6-R11, then STOP AND ASK before R12
(the only paid item; its own row says the gate fails either way). R13 only after R1-R11.
R15 is open and free -- slot it wherever you like, but do it as its own item.

WORK ONE ITEM AT A TIME. STOP AFTER EACH AND REPORT. Do not batch.

FOR EACH ITEM, IN THIS ORDER:
  1. REPRODUCE THE DEFECT FIRST, on the existing artifact, before touching code. Print the
     wrong value and the value you expect after. If you cannot make the wrong number appear
     on demand, you do not understand the bug and must not "fix" it.
     Then CLASSIFY it: every finding in this list so far has turned out to be either more
     than one defect sharing a branch, or latent, or already-fixed. Say which.
  2. CHANGE EXACTLY ONE THING. If a fix needs two, make them two items and say so.
  3. ADD A TEST THAT FAILS AGAINST THE PRE-FIX CODE, and prove it: reimplement the old
     behaviour, monkeypatch it in, re-run the same assertions, and report how many fail.
     State plainly which tests pass BOTH ways and why they are still worth having.
  4. RE-RUN only what the table says. Free items stay free: no LLM, no paid API, no
     pipeline, no DB writes. DB READS are allowed.
  5. COMPARE old vs new field by field. Back up the artifact first and diff EVERYTHING,
     not just the number under test -- that is what proves containment and what catches the
     change you did not predict. Say WHICH DIRECTION each number moved and whether any
     conclusion in CLAUDE.md or the specs changes. If none does, say that too.
  6. AUDIT YOUR OWN FIX before committing, with the same taxonomy. In this effort that step
     found a real defect in 3 of 4 fixes. Then commit and WAIT.

HARD RULES
  - Zero Postgres writes. Zero pipeline runs. `layer_d.scoring_unit` stays `moment`,
    `layer_a.pool_unit` stays `clause`. Nothing ships.
  - NEVER `git add -A`. Stage explicit paths. Untracked files from other sessions appear in
    this repo mid-task and one got swept into a commit here.
  - Before every commit, verify no production prompt drifted: compare every PROMPT_*
    constant in shared/prompts.py against `git show HEAD:` -- the count must match and only
    an intended one may differ.
  - Any harness that prints a rate must print its DENOMINATOR and the run's configuration.
  - Any comparison of two arms must print every property that differs, not just the one
    under test.
  - If a fix makes a check STRICTER, quantify what it newly rejects and read 5 real samples.

TRAPS THAT HAVE ALREADY COST TIME OR MONEY HERE
  - `trial_grader_inputs.py`: a plain re-run rebuilds items before reading the checkpoint,
    resumes only on an exact n_items match, and the flags that shape items are not in the
    artifact -- so a wrong guess starts SCORING (~180 paid calls). Use --recompute.
  - `np.percentile` returns NaN if one sample is +inf (it interpolates inf - inf).
  - A stable sort leaves TIES in input order; that, not NaN, is what usually makes a printed
    ranking irreproducible.
  - Aggregating by a non-unique key: 33 scenario_keys are duplicated across clusters, so a
    set of keys is not a count of rows.
  - `calibration/flag_proper_noun_clusters.py`'s own sys.path bootstrap does
    `sys.path[0] = ""`, clobbering anything you inserted at position 0 before importing it.

WHEN R4-R11 ARE DONE: re-read the "Explicitly NOT to be rerun" list and confirm nothing you
changed invalidates those four results. Report that check explicitly.
```

---

## Where each remaining item stands

| item | file | free? | what it is |
| --- | --- | --- | --- |
| **R4** | `null_test_taxonomy.py` | yes, ~15 min | composition-matched null (F12). **The 20% vs 29% comparison is unreadable until this is fixed** — the arms accept different turn fractions (46.7% vs 35.6%), so the null favours whichever accepts fewer. A real number-mover, not a guard. |
| **R5** | `null_test_taxonomy.py` | same run as R4 | position-verified join (F13) — verifies cluster COUNT only; its sibling verifies n_items/calls/keywords position-for-position. |
| **R6** | `trial_call_scoring.py` | code only | `--tag` + refuse-to-overwrite (F7). Recorded FIXED and never implemented; a 45-call artifact was already destroyed once. |
| **R7** | gateway path | code only | `scored_by` is `None` and no artifact records the transport; `chat_json`'s 8192 default halves the 16384 the scorers set. |
| **R8** | both trials | code only | checkpoint keys (F8) — no model, transport, `--holdout` or condition subset. **This is why R3's re-run was dangerous.** |
| **R9** | `trial_call_scoring.py` | code only | `criteria_per_arm` guard measures a different population than check 1 tests. Recorded FIXED, git-verified untouched. |
| **R10** | `trial_call_scoring.py` | code only | `trigger_turns` caps `[:4]` before filtering NULLs. |
| **R11** | `trial_grader_inputs.py` | code only | F9 batch balance — single-arm batches mean one dropped batch unbalances the arms; nothing counts failures. |
| **R15** | `flag_proper_noun_clusters.py` | yes, ~10 min | lookup tokeniser must be the vectoriser's. 87 keywords still unmeasured; `dont` / `2021` can never match. Moves existing non-NaN values, so it needs its own before/after. |
| **R12** | prompt + verifier | **PAID ~60 calls** | STOP AND ASK. Gate fails either way; buys a defensible record, not a different answer. |
| **R13** | new harness | **PAID ~60-80 calls** | anti-pattern forced choice. Only after R1–R11. Pre-registration is in `REMEDIATION_PROMPT.md`. |

## Two documentation gaps found, deliberately not silently fixed

- **`docs/superpowers/specs/2026-08-15-grader-inputs-design.md` never records the live result.**
  It still ends *"CONCLUSION: the criteria scorer discriminates"* on the confirmA/B runs, which
  `AUDIT_FINDINGS` lists as **superseded, "do not cite"** (F9: both arms shared a prompt). The
  real result — `clean_v2`, D=1.15, 52.8% over 73 scenarios / 2,976 attempts — appears nowhere
  in the spec. Someone reading only the spec gets the retracted conclusion.
- **`diagnose_rubric_level.py` still reports a rubric population of 78**, because a rubric Layer
  D never reached produces no rows. R14 measured the true figures (84 rubrics / 405 criteria)
  read-only and wrote them into the spec, but the script itself cannot recover them from its
  artifact — it needs the rubric table.
