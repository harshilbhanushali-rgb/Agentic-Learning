# HANDOFF — run the repertoire pass (Task A) and the warrant-legibility probe W0 (Task B)

Written 2026-09-05. Continues from `HANDOFF_LAYER_D_SAY_ARM_2026-08-28.md` (the say-arm
build/gate session) — that handoff's state is still accurate; this one turns its open
decision into two concrete tasks, now operator-approved in intent. Full evidence trail:
`docs/findings/layer-d-say-arm.md`. Everything in §0 is measured and settled — do not
re-derive any of it.

## 0. CONTEXT FOR A COLD READER (settled facts, with pointers)

**What Layer D is.** The Brain pipeline distilled 33 live playbooks (121 moves total)
from Naren's calls; Layer D grades CSM calls (currently one CSM, Madhumita, 100
transcripts) against them. The production instrument for comparison-style grading is
the **pairwise arm** (run `137706da74c6`, still live, untouched).

**The say-arm arc (2026-08-28/29).** Pairwise tied on ~68% of cells because ~84% of
moves are speech acts ("state X, warn about Y"). A third `grader_arm: say` was built:
occurrence verdicts per moment (no/generic/specific → miss/partial/hit), verbatim
quote verified programmatically, ROLLED UP TO THE CALL in
`storage.refresh_move_performance` (say-arm `attempts` counts CALLS). Moves were
routed by a two-reader blind classification, hash-pinned fail-closed:
**87 say / 34 pairwise** (`artifacts/layer_d_move_classes.json`,
`layer_d/move_classes.py`).

**Gate results (pre-registered, all in the findings doc §5/§8):**

- G-S1b discrimination: **PASS** under the strict v1 prompt contract — 7-0 decided
  calls, p=0.0078. The looser "element credit" v2 contract **FAILED** (71%, p=0.09,
  credit leaks onto adjacent scenarios) — v1 is shipped; do NOT loosen it (comment in
  `layer_d/prompts.py`).
- G-S2 quotes: **PASS twice**, 126/126 verified.
- G-S3 specificity spread: **FAIL both contracts** — the generic/specific tier is
  DIAGNOSTIC ONLY; no coaching claim rests on it.
- **G-S4: FAIL at the shipped floor, and it is the finding of the arc**: the Naren
  benchmark (run `695837c37614`, 910 naren/say `move_events` over all 33 playbooks,
  11-26 calls per cell, zero failures) measured **Naren's own call-level occurrence
  at median 14.3%** (3/87 cells ≥0.50; 12/87 ≥0.30; 58/87 ≥0.10). The playbook is a
  REPERTOIRE he deploys ~1-call-in-7, not a per-call checklist. This one mechanism
  explains the checks arm's death (3-6% per-moment, C3) AND the pairwise tie flood.
- Consequence: the CSM production say run was NOT launched; `tuning.yaml
  layer_d.grader_arm` is back on `pairwise`. **Setting it to `say` is what launches
  the say run** — that is now Task A's first switch, deliberately.

**The operator direction (from the 2026-08-29/09-05 discussion):** coaching should be
(1) repertoire gaps — "you have NEVER used move X; Naren uses it every ~7th call;
here are his verbatim deployments" — statistically solid because P(zero in n calls)
is small at his measured rates; and (2) if and only if W0 says the transcript carries
the warrant signal, a later per-moment "missed chance" detector. Per-moment claims
are NOT allowed to ship on topical relevance alone — even Naren skips 6 of 7
"chances", so that would convict everyone.

**Numbers Task A's power rule needs (already computed, re-derivable from the DB):**
61/87 say moves are in Naren's repertoire (said on ≥2 distinct calls). A "never"
verdict is significant at p<0.05 within n = ln(0.05)/ln(1-p̂) calls: median 13,
46/61 moves need ≤20. Madhumita has ≥8 graded calls on 18/30 playbooks (median 11,
max 55 — counted from pairwise events, `COUNT(DISTINCT call_id)` per playbook,
response_outcome='csm', verdicts != '[]').

## 1. TASK A — the repertoire pass (the main deliverable)

**Goal:** the coaching report section "moves you have never used", per
(CSM, in-repertoire move), three states: `uses it` (≥1 verified instance) /
`never` (zero instances AND enough applicable calls per the power rule) /
`insufficient data` (zero instances, too few calls — NEVER reported as a gap).

Steps, in order:

1. **Write the repertoire aggregation + report (pure code, no spend).** It does NOT
   exist yet. Input: say-arm `move_events` (CSM side, once graded) + the naren
   benchmark events already in the DB. Per move: p̂ = Naren's call-level rate
   (hits+partials over attempts from `move_performance` naren/say rows);
   in-repertoire = said on ≥2 distinct calls; n_needed = ln(.05)/ln(1-p̂); CSM state
   per the three-way rule above. Report language: move + Naren's deployment
   frequency ("every ~N calls") + his verbatim evidence quotes (playbook
   `key_moves[].evidence`) + up to 3 of HER quote-verified instances when state is
   `uses it`. Extend the combined report (`pipeline.build_combined_reports`) with
   this section. Tests mirror `tests/test_layer_d_say.py`. Blind code audit before
   the spend step, house rule.
2. **Run the production say grade** (~300-400 gateway requests, VPN up):
   set `tuning.yaml layer_d.grader_arm: say`, then
   `python ops/run_layer_d.py --hostaddr 18.138.49.39`. Checkpointed per transcript
   (layer string carries the classes fingerprint); re-runs safe; naren pass will
   skip via checkpoints (same run only — note the run_id derives from the transcript
   selection, so the naren benchmark re-runs under a new run_id unless `--naren-only`
   checkpoints are reused; the events upsert on their natural key either way, so a
   re-benchmark is idempotent, only spend).
3. **Gates before anyone sees the report (pre-registered, findings doc §9):**
   - G-R1: blind output audit — `calibration/layer_d_output_audit.py --audit-say`
     (built, unused), two reader subagents (Sonnet, packet-only), `--score-say`,
     bar ≥70% exact 3-way agreement.
   - G-R2: spot-read EVERY `never` cell's moment population (a "never" built on
     mis-routed moments must die in review). Zero spend, read stored events.
   - G-R3: the power rule enforced per cell in code, pinned by a test.
4. **Flip `grader_arm` back to `pairwise` after the run** (fail-safe convention),
   regenerate the combined report (`ops/run_layer_d.py --report-combined`), write
   results into `docs/findings/layer-d-say-arm.md` (append, same file), update the
   INDEX line, hand the operator the report.

**If G-R1/R2 fail:** stop, write it up, fall back to do-type-only coaching (the 34
pairwise cells) — pre-listed in findings §7/§9. No prompt iteration; that lever is
refuted 6x.

## 2. TASK B — W0, the warrant-legibility probe (zero chat spend, run alongside A)

**The question:** is the thing that makes Naren deploy move X at one moment and not
another VISIBLE in the client trigger text? If yes, a per-moment "you missed the
chance HERE" detector (W1) is buildable; if no, it is impossible from transcripts in
principle, and that closes the operator's request with evidence.

**Data (already in the DB):** the 910 naren/say events of run `695837c37614` carry
`trigger_text` and per-move verdicts — for each of Naren's benchmark moments we know
deployed (hit/partial) vs not (miss), per move.

**Method (freeze the decision rule in the findings doc BEFORE running):**

1. Per in-repertoire move: deployment triggers = trigger_texts of moments where he
   deployed. For every moment of his in that scenario, compute max cosine similarity
   to the move's deployment triggers, **leave-one-out for the deployed moments
   themselves** (a deployed moment must not match itself).
2. Embeddings: gateway/gemini@3072 space, CACHE-ONLY via the calibration shim
   (`layer_bc_arms.install_embedder_shim` or equivalent) — abort on miss, assert
   vector width. The 2026-08-19 GOTCHA: a script that forgets the shim silently
   compares across two embedding spaces and produces a garbage cosine table.
3. Pool across moves for the primary curve (per-move n is 2-8 deployments — too thin
   alone): bucket all (moment, move) pairs by similarity decile, plot deployment
   rate per decile against the ~15% base rate. Per-move curves as diagnostics only.
4. **Suggested decision rule to freeze (adjust wording before running, not after):**
   warrant is LEGIBLE if some top similarity band covering ≥10% of moment-move pairs
   has deployment rate ≥3x base rate AND ≥50% absolute. Otherwise NOT LEGIBLE.
5. Either outcome is a finding. LEGIBLE → design the W1 ladder (detector calibrated
   on Naren's own conditional rates, validated on held-out Naren calls, blind read of
   flagged CSM moments; W1 is a PER-ITEM CLASSIFIER — the shape that has failed 9x
   here, so its gates must be merciless and it must never be validated against an
   LLM's opinion of "warranted", only against Naren's measured behavior). NOT
   LEGIBLE → append the negative to the findings doc; per-moment missed-chance
   claims are permanently off the table from transcript data.

**Caution to carry in:** Ask Naren's ADR 0005 already found retrieval cosine alone
couldn't separate right from wrong answers in a neighboring problem. Similarity may
well not carry warrant. That is exactly why W0 is a probe and costs nothing.

## 3. THE REST OF THE QUEUE (agreed order, after/alongside A+B)

1. **COMMIT FIRST — before anything else.** THREE sessions of work now sit
   uncommitted on `layer-c-profile-rebuild` (the P0 arc + the entire say arm + docs).
   Cut into clean commits; nothing has ever been pushed.
2. **Deferral-rate write-up** (free): the 33% deferral finding, measured in the P0
   session, still unreported to any human. Zero spend, just writing.
3. **Frontend wiring** (after Task A resolves): surface the combined coaching report
   in `frontend/` — the actual usage bottleneck; nothing outside a terminal can see
   any Layer D output today. Shape depends on whether the repertoire section exists,
   hence the ordering.
4. **Second CSM** (only after Task A's gates pass): scaling was deliberately held
   until the instrument question was settled. Needs transcripts + Avoma rosters +
   `mapping.csv` + `ops/build_client_roster.py` regeneration.
5. **Layer C census of the 26 out-of-repertoire moves** (free): the say moves Naren
   himself said on <2 of his benchmark calls are over-specification candidates.
   Census their original evidence (how many distinct calls each was built from);
   feed the result into the NEXT playbook generation as a rule ("≥2 distinct calls
   of evidence per move") — do NOT rewrite live playbooks (wording-as-lever refuted;
   a replacement re-triggers reclassification via the hash pins, by design).
6. **Parked, do not resurrect without new evidence:** rewriting the 24 blurry cells
   (superseded by the routing split); the 4 "genuinely mixed" cells (tiny n);
   Ask Naren issue #9 (separate context).

## 4. HOUSE RULES THAT BIT PEOPLE THIS ARC (obey, don't rediscover)

- **Never** open a connection with `SET SESSION default_transaction_read_only = on`
  (Neon pooler leak — five instances found and fixed; grep before writing any new
  "safety" connection; see docs/GOTCHAS.md).
- Neon DNS: append `hostaddr=18.138.49.39` (keep host in URL for SNI/SCRAM).
- Long runs: `PYTHONUNBUFFERED=1`, log under `Brain/logs/`.
- Blind reads: fresh Sonnet subagents, packet-only (opaque ids, no outcome data),
  full read enforced, one agent at a time; persist every read to `artifacts/`
  (an unpersisted read is permanently lost — happened once already).
- Pre-register gates in the findings doc BEFORE spend; a failed gate stops the work
  and brings options, it does not get renegotiated after the numbers exist.
- Tests from repo root venv: `..\.venv\Scripts\pytest tests/ -v` from `Brain/`
  (suite was 1,642 passing at handoff time).
- `tuning.yaml grader_arm` is the launch switch: `say` = the production say run.
  Flip deliberately, flip back after.

## 5. POINTERS

| thing | path |
| --- | --- |
| Full say-arm record (design, gates, results, §9 = Task A's spec) | `docs/findings/layer-d-say-arm.md` |
| Previous handoff (build session state) | `HANDOFF_LAYER_D_SAY_ARM_2026-08-28.md` |
| Routing map (hash-pinned) / loader | `artifacts/layer_d_move_classes.json` / `layer_d/move_classes.py` |
| Say grading + reports | `layer_d/prompts.py`, `layer_d/graders.py`, `layer_d/pipeline.py`, `layer_d/aggregate.py` |
| Call-level rollup (replay-verified) | `shared/storage.py::refresh_move_performance`, `get_say_densities` |
| G-S4 readout (re-runnable, free) | `calibration/layer_d_say_g4_readout.py` |
| Output audit incl. `--audit-say` | `calibration/layer_d_output_audit.py` |
| Gate artifacts + logs | `artifacts/layer_d_say_ab*.json`, `logs/say_*_20260828.log` |
| Naren benchmark events | `move_events` where grader_arm='say', run `695837c37614` |
