# HANDOFF — the repertoire pass ran and passed its gates; W0 closed per-moment coaching (2026-09-05 → 06)

Executes `HANDOFF_LAYER_D_REPERTOIRE_AND_W0_2026-09-05.md` in full. Everything below is
measured; every artifact and log named exists on disk; every number is in
`docs/findings/layer-d-say-arm.md` §10–§12 with its provenance. Nothing has been pushed.

## 0. THE ONE-PARAGRAPH VERSION

Three sessions of uncommitted work are now nine clean commits on `layer-c-profile-rebuild`.
The warrant-legibility probe (W0) ran at zero spend and came back **NOT LEGIBLE** under the
rule frozen before it ran: trigger-text similarity carries a real but weak trace of when
Naren deploys a move (top decile 28% vs 15% base, p<0.002), nowhere near the 3×/50% a
per-moment "you missed it here" claim needs — that coaching shape is closed for good from
transcript data. The repertoire pass was built, blind-audited, pre-registered, and run:
100/100 transcripts, 0 failures, ~340 requests, Naren's benchmark preserved. G-R1 passed at
**89.6%** (bar 70%); G-R3 is pinned by tests; G-R2 found a five-word backchannel inside the
report's ONLY `never` cell, which drops it one call below the power threshold. Result:
**Madhumita verifiably uses 33 of Naren's 61 repertoire moves; zero repertoire gaps are
claimable today; 27 cells need more calls.** `grader_arm` is back on `pairwise`.

## 1. WHAT EXISTS NOW

| thing | where | state |
| --- | --- | --- |
| Commits | `git log b49aa13..HEAD` (9 commits) | P0 arc / say arm / docs / W0 prereg / W0 result / repertoire code+prereg / n_needed fix+flip / deferral+census / results+flip-back |
| Repertoire aggregation | `layer_d/repertoire.py`, `tests/test_layer_d_repertoire.py` (23 tests) | shipped, audited pre-spend (1 MINOR finding fixed: strict boundary in `n_needed`) |
| Combined report | `ops/run_layer_d.py --report-combined` → `logs/combined_report_20260906.log` | repertoire section leads; say-rate (diagnostic) and pairwise follow |
| CSM say events | `move_events` grader_arm='say', rater_population='csm', run `137706da74c6` | 1,205 rows / 96 calls; 621 graded |
| Naren say benchmark | run `695837c37614` | 1,001 rows, UNCHANGED (checkpoints copied to skip re-grade) |
| G-R1 reads | `artifacts/layer_d_oa_say_reader{1,2}.json`, `layer_d_oa_say_model_verdicts.json` | committed as provenance |
| G-R2 read | `artifacts/layer_d_never_cells_CSM_MADHUMITA.txt`, `_read1.json`, `_key.json` | committed |
| W0 probe | `calibration/layer_d_w0_warrant_probe.py`, `artifacts/layer_d_w0_warrant_probe.json` | committed; re-runnable at zero spend |
| Deferral write-up | `docs/findings/layer-d-deferral-rate.md` | new |
| Layer C census | findings §12, `logs/layer_c_census_20260905.txt` | done; rule proposal changed (see §3) |
| Plain-language history | `PROBLEMS_AND_FIXES.md` (new entry at the end) | done |
| Test suite | `..\.venv\Scripts\pytest tests/` from `Brain/` | 1,665 passing |

## 2. GATE RESULTS (all pre-registered in the findings doc BEFORE the numbers existed)

| gate | verdict | number |
| --- | --- | --- |
| W0 warrant legibility (§10) | **NOT LEGIBLE** | top decile 0.283 vs base 0.155 (1.82×; needed 3× AND ≥0.50); permutation p<0.002; AUC 0.61 |
| G-R1 blind output audit (§11) | **PASS** | 181/202 = 89.6% exact 3-way pooled over two Sonnet readers; binary 90.6%; reader-reader 91.7% |
| G-R2 never-cell spot-read | **survives content, fails power after correction** | 8/9 moments OK (≥80%); the NOT_HER moment removes a call → 8 < 9 needed → `insufficient data` |
| G-R3 power rule in code | **PASS** | `n_needed(0.15) == 19`; 18 zero-calls → insufficient, 19 → never; strict boundary `n_needed(19/20) == 2` |

## 3. WHAT THE OPERATOR SHOULD DECIDE NEXT (options, not recommendations forced)

1. **Whether to show the CSM a report with zero gaps.** The honest report for Madhumita is
   "33 repertoire moves in use (with your quotes), 28 not yet measurable". That is a
   confidence-building artifact, not a coaching one. It becomes coaching only as calls
   accumulate: the attribution cell needs ONE more clean routed call; the median
   insufficient cell needs 13–23 calls on scenarios where she currently has 1–7.
2. ~~The interjection guard's word-count hole~~ **DONE 2026-09-06 (operator decision).**
   `signals.is_substantive_reply` (≥5 distinct content lemmas AND one clause of ≥3 content
   words; "has a verb" was measured and does NOT catch "Sounds good") → `_v4`; 20 moments
   relabelled in both arms at zero spend by `ops/reclassify_interjections_v4.py` (full-row
   backup, checkpoints copied). Repertoire report now 33 / 0 / 28; G-R1 recomputed 89.2%
   without the two relabelled sample items; pairwise top cells drift ≤5 points. §11c.
3. **The say-rate section of the combined report** prints ~84 dead-check flags every time.
   It is the G-S4 finding restated. Demote to a one-line count, or drop.
4. **Second CSM** — now unblocked (the instrument question is settled). The deferral rate
   is the first zero-spend comparison; the repertoire section the second.
5. **Frontend wiring** — the repertoire section has a stable shape now (three lists, quotes
   per cell). `pipeline.build_combined_reports` returns text; a JSON shape would be the
   first step.
6. **Layer C next-generation rule** — the census REFUTED "≥2 distinct evidence calls per
   move" as the fix (removes 3 of 26 bad, 2 of 61 good). The supported rule is "one
   statable thing per move": split conjunctive criteria or route them DO. Not a rewrite of
   live playbooks.

## 3b. DECISION 2 EXECUTED (2026-09-06 morning, at the operator's request)

- Rule chosen by measurement over all 621 graded replies (table in findings §11c): the
  naive "require a verb" catches 0 of the 6 known backchannels; the chosen rule catches
  all 6 plus 14 more closings/acknowledgement strings, ~4 thin questions as collateral.
- Applied as a RELABEL, not a regrade: strictly stricter rule ⇒ a fresh `_v4` run equals
  the `_v3` events with those 20 moments set ungraded, in both arms. Audit before running
  found the backup could be clobbered on re-run and the updates were not transactional;
  both fixed first. `artifacts/layer_d_v4_reclassified_backup.json` holds the old rows.
- Instrument identity is `_v4` everywhere; `_v3` checkpoints copied so nothing re-grades.
- Result: repertoire 33 / 0 / 28 (the attribution cell reads "0 of 8 calls, 9 needed");
  G-R1 89.2% on the 38 untouched sample items; deferral 32.8% unchanged, interjections
  17.1%.

## 4. THINGS THAT BIT THIS SESSION (add to your priors)

- **A copy-aside without a directory check silently overwrote nine uncommitted files.**
  The Bash tool does not honour `set -e` inside a loop. Recovered from the diffs already
  in context and verified line-count-identical against the diffstat; memory saved
  (`verify-backup-before-overwrite`). Do `mkdir -p` + `cmp` before any overwrite.
- **The Naren benchmark inside `run_layer_d_batch` re-grades unless its checkpoints exist
  under the batch's run_id.** Copying the 33 `_naren` rows from `695837c37614` to
  `137706da74c6` (same layer string, same items, same sample) is what preserved the G-S4/W0
  events. Verified beforehand that all 33 live (scenario, playbook_id) pairs still match.
- **Heredocs in the Bash tool mangle escapes** (already in GOTCHAS) — write scripts with
  the Write tool and run them as files.
- **A `never` is only as strong as its weakest moment.** G-R2 is not optional; one
  backchannel changed the verdict.

## 5. POINTERS

Findings: `docs/findings/layer-d-say-arm.md` §10 (W0), §11/§11b (repertoire), §12 (census);
`docs/findings/layer-d-deferral-rate.md`. Logs: `logs/say_production_20260905.log`,
`logs/combined_report_20260906.log`, `logs/w0_warrant_probe_20260905.log`,
`logs/layer_c_census_20260905.txt`. Previous handoffs remain accurate for their dates.
