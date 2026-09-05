# HANDOFF — Layer D P0 fixes shipped, regrade complete, output audit re-passed (2026-08-26 → 27)

Supersedes `HANDOFF_LAYER_D_CALIBRATED_2026-08-25.md` (everything it listed as owed is done).
Full evidence trail: **`docs/findings/layer-d-redesign.md`** (this arc's single source of
truth — gates, numbers, retractions, the P0 fixes, the regrade saga, the output audit). The
pooler-leak bug is also written up standalone in `docs/GOTCHAS.md`. Production facts:
`Brain/CLAUDE.md`.

## 0. STATE OF THE WORLD (settled; do not re-derive)

1. **All three P0 fixes are shipped, audited, tested, and regraded against real production
   data.** Instrument is now `layer_d_e_pairwise_gemini-3.6-flash_medium_noswap_v3` (the `_v3`
   bump IS the fix boundary — any `_v2` verdict is stale):
   - **Interjection guard** (`layer_d/signals.py::detect_moments`) — a `"csm"` response window
     that fails `_is_substantive` (≥5 content words, the same rule used project-wide) is
     reclassified to a new `response_outcome = "interjection"`, recorded ungraded, kept
     separate from `"other_joveo"` so the already-reported 33% deferral rate doesn't move.
     Required a schema change: `move_events.response_outcome`'s CHECK constraint gained
     `'interjection'` (idempotent in `db/schema.sql`, already applied to the live DB).
   - **Exemplar-substantive filter** (`layer_d/pipeline.py::make_exemplar_picker`) — Naren
     candidates are filtered through `_is_substantive` before top-cosine pick; falls back to
     the unfiltered pool (logged) if filtering would empty it for a scenario.
   - **Report grouping** (`layer_d/aggregate.py::group_by_scenario` +
     `format_pairwise_priorities`) — one block per scenario, moves nested inside, ordered by
     each scenario's WORST move's gap (never averaged). The old `_REPORT_TOP_N=5` cutoff is
     gone for the pairwise arm — verified the real scale is ~19 scenarios / ~50 rankable cells
     for one CSM, not hundreds, so nothing needs hiding.
2. **The regrade is complete: 100 of 106 mapped transcripts, 0 failures, `move_performance`
   fully rebuilt (251 rows).** Took 8 attempts — not because the P0 fixes were wrong, but
   because two unrelated operational bugs surfaced only once real spend was riding on a
   long-running batch. Both are now fixed and are standing infrastructure, not one-offs (§2).
3. **The regraded numbers barely moved from the pre-fix run — read this as confirmation, not
   a null result.** Top cell: 11 attempts/1-3-7/23% → 9 attempts/1-2-6/22%. Other cells within
   1-2 points, attempt counts dropping by exactly what the interjection guard predicts. The
   original run was mostly real signal; the P0 defects were a small, now-removed distortion —
   matching the read-through's own estimate (~2 of 11 top-cell losses were artifacts).
4. **The output audit was re-run on the fresh regraded data and passed: 92.7% agreement**
   (38/41 mutually decisive verdicts, two independent blind readers vs the model), gate ≥70%,
   consistent with the original run's 97.9%.
5. **26-ish blurry cells are still the targeted playbook-rewrite shortlist** — unchanged in
   kind, count shifted slightly with the regrade (~24 now). Still coordinate with the Layer C
   session; still no blanket rewrite license.
6. **The 33% deferral rate is still a real, unreported finding** — now cleanly separated from
   the new `"interjection"` bucket, so it's a slightly more honest number than before, not
   materially different.

## 1. VERDICT: STILL SHIPPABLE AS A COACH-FACING DRAFT — THE P0 GAP TO CSM-FACING IS NOW CLOSED

The three defects that made the first report risky to show a CSM (fragment replies scored as
losses, filler benchmarks, one scenario tripled across the top-3) are fixed, regraded, and
re-validated. What is **not** closed by this work — don't read it as closed:

- **Still one CSM** (Madhumita). Nothing here generalizes to "CS reps struggle with X" until
  more CSMs run through it (P2).
- **Still ~a third of the playbook is blank** (blurry cells — no signal, not a measured gap).
- **Rates are still relative/shrunk**, appropriate for ranking priorities, not for a precise
  absolute claim — several cells sit on n=9–16.

Do NOT use this data yet to author broad training/reading content or test questions off the
whole report — the operator's own read on this (2026-08-27 session): pilot narrowly off the
single strongest, best-measured, non-blurry finding (`attribution_and_funnel_tracking`, 78%
gap, n=9) before scaling to anything comprehensive, since criterion wording quality is uneven
project-wide and a lesson built on a blurry or soon-to-be-rewritten criterion is wasted work.

## 2. THE TWO BUGS THE REGRADE EXPOSED, both now fixed and standing infrastructure

**Bug 1 — no connection reconnect.** `run_layer_d_batch` and `run_naren_benchmark` held one
long-lived connection for a whole batch with no health check; one dropped connection (a WiFi
blip) cascaded into every remaining transcript's write failing, wasting real grading spend on
each. Fixed with `storage.reconnect_if_closed` (the pattern already used everywhere else in
this project) wired into both functions' per-item loops; both now return `(result, conn)` so
the caller rebinds to the live connection.

**Bug 2 — the real one: a leaked session GUC through Neon's connection pooler.** Four scripts
(`ops/serve_ask_naren.py`, `calibration/probe_retrieval_gate.py`,
`calibration/score_naren_ceiling.py`, `calibration/layer_d_output_audit.py`) each open a
"safety" read-only connection (`SET SESSION default_transaction_read_only = on`) and closed it
without resetting first. Neon's pooled endpoint reuses backend connections across unrelated
clients (PgBouncer transaction pooling), so the leftover setting poisoned whichever client got
that backend next — including a completely unrelated Layer D run, minutes later, with zero
actual write conflict involved. **Directly reproduced and directly disproved as a genuine
restriction** (a plain `SET SESSION ... = off` cleared it instantly, every time, including
live mid-incident). Full writeup: `docs/GOTCHAS.md`.

Fixed two ways: (a) all four scripts patched at the source (`.close()` wrapped to reset first);
(b) Layer D made self-healing regardless of source — `storage.clear_read_only(conn)` actively
resets a leaked setting and only aborts if the reset genuinely doesn't take, wired into every
write loop in `layer_d/pipeline.py`. This mattered because the leak kept recurring from an
unidentified fifth source even after the four known scripts were fixed (confirmed via
`pg_stat_activity` that no known process was the cause) — the self-heal let the regrade push
through three separate re-poisoning events in one run instead of aborting on the first.

## 3. HOUSE LESSONS THIS SESSION RE-PROVED OR ADDED

- **Systematic debugging over guessing, even under pressure to just re-run.** The "it's
  probably the concurrent chatbot" theory was plausible and half-right, but `pg_stat_activity`
  and a direct reproduction test found the actual, fixable mechanism (a leaked pooled-session
  GUC) rather than settling for an unfalsifiable "something external" explanation.
- **A pre-spend blind code audit, every time code governing spend changes** — 4 more audits
  this session (5–8), on top of the arc's prior 4. Audit #7 caught a real second gap in the
  fix it was reviewing (the final-aggregate step was unguarded); audit #6 caught the identical
  gap in a sibling function. The pattern holds: reviewing your own fix in isolation misses the
  sibling that has the same bug.
- **Checkpointing is what makes 8 failed attempts cheap instead of catastrophic** — natural-key
  upserts + per-item checkpoint marks meant every failure lost at most the transcripts
  mid-flight, never redid confirmed work, and the final state is identical to what a single
  clean run would have produced.
- **A fix that "detects and aborts" is not the same as a fix that "resolves."** The read-only
  fail-fast (audit #7) was a real improvement over cascading failure, but self-healing
  (audit #8) is what actually let the regrade finish — worth reaching for the stronger fix when
  the failure is proven to recur from outside your own code's control.
