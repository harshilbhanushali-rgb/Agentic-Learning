# HANDOFF — the say arm was built, gated, and STOPPED at G-S4; one decision is open (2026-08-28)

Continues from `HANDOFF_LAYER_D_SPEECH_ACT_DESIGN_2026-08-28.md` (this session executed
its §1). Full evidence trail: `docs/findings/layer-d-say-arm.md`. Everything below is
measured, not asserted; every artifact and log named here exists on disk.

## 0. THE ONE-PARAGRAPH VERSION

The say arm (occurrence + specificity grading of speech-act moves, rolled up to the
call) was designed with pre-registered gates, built, blind-audited, and run through its
gate ladder the same day. The instrument itself is GOOD: when it credits, it is right
(call-level matched-vs-unrelated 7-0, p=0.008) and it never fabricates (126/126 quotes
verified across both gate runs). But the Naren benchmark run over all 33 playbooks
(910 events, zero failures) measured the thing nobody had measured at this unit
before: **Naren states a given playbook move on a median of ~15% of his own routed
calls.** The playbook is a repertoire, not a per-call checklist — so the pre-registered
G-S4 gate (≥50% of cells non-dead at the shipped 0.50 floor) failed at 3/87, and the
CSM production run was NOT launched. A repertoire-coverage reframe of the same
instrument ("which of Naren's moves has this CSM NEVER used, over enough calls for
never to mean something") is fully specified, well-powered on the data already in
hand, and awaits the operator's go/no-go.

## 1. WHAT EXISTS NOW (all tested — suite is 1642 passing — and blind-audited pre-spend)

- **Routing**: `artifacts/layer_d_move_classes.json` — all 121 live moves classified
  SAY/DO by TWO blind reader subagents (84% agreement; disagreement → pairwise;
  87 say / 34 pairwise; criterion sha256-pinned, fail-closed in
  `layer_d/move_classes.py`). Both raw reads persisted (`ld_moveclass_read{1,2}.txt`)
  — the previous session's classification was lost by not persisting; not repeated.
- **The arm**: `PROMPT_SAY_BATCH` (contract v1 — a measured comment in
  `layer_d/prompts.py` says why the looser v2 must not come back), say functions in
  `layer_d/graders.py`, routing + call-sampled benchmark in `layer_d/pipeline.py`,
  call-level rollup in `storage.refresh_move_performance` (replay-verified 16/16
  against an independent recomputation), say + combined reports
  (`--report-combined`), `get_say_densities` opportunity readout, schema CHECKs
  widened (live DB already altered, idempotent in `db/schema.sql`).
- **Harnesses**: `calibration/layer_d_move_classes_packet.py` (blind routing packet),
  `calibration/layer_d_say_ab.py` (G-S1/2/3, moment + call units),
  `calibration/layer_d_say_g4_readout.py` (G-S4, zero spend, re-runnable),
  `calibration/layer_d_output_audit.py --audit-say/--score-say` (G-S5, built, unused).
- **Benchmark data**: 910 naren/say `move_events` under run_id `695837c37614` —
  real measurements, keyed by arm, invisible to pairwise reads, kept.
- **Drive-by fix**: `calibration/layer_d_grader_ab.py` was a FIFTH instance of the
  Neon read-only-GUC leak (docs/GOTCHAS.md updated); the GUC is removed.

## 2. GATE RESULTS (pre-registered in the findings doc BEFORE any code ran)

| gate | verdict | number |
| --- | --- | --- |
| G-S1b call-level discrimination (v1 contract) | **PASS** | 100% over 7 decided calls, p=0.0078 |
| G-S2 quote verification | **PASS** (twice) | 45/45 and 81/81 = 126/126 |
| G-S3 specificity tier spread | **FAIL** (both contracts) | ~90-94% of scored verdicts are "no" at every unit; specific:generic among credits ≈ 27:6 |
| G-S4 benchmark viability at shipped floor 0.50 | **FAIL** | 3/87 cells non-dead (0.30 → 12/87; 0.10 → 58/87) |
| G-S5 output audit | not run | no production data to audit, by design |

Also measured: the element-credit v2 contract (the ONE pre-registered revision)
made discrimination WORSE (71% over 14 decided, p=0.09) — element-level credit
leaks onto topically-adjacent scenarios. v1 artifact: `layer_d_say_ab_v1.json`;
v2: `layer_d_say_ab.json`. Zero k-run flips in either (k=3).

## 3. THE FINDING THAT CHANGES THE PICTURE

Every framing of "did the rep perform the playbook move" now has a measured verdict
at every unit: per-moment 3-6% (C3, checks death), per-call median ~15% (G-S4, this
session). One mechanism explains the whole Layer D arc: **playbook moves are
low-base-rate, situation-triggered behaviors.** Absolute demands fail at any unit,
and pairwise ties whenever the situation triggered the move for neither rep — which
is most moments. This is a fact about the playbook's relationship to calls, not
about any grader. (It is also a Layer C content finding: the playbook describes what
Naren does ACROSS his corpus, not what he does on each call.)

## 4. THE OPEN DECISION (the only thing blocking further progress)

**Proposed: rerun the same licensed instrument, aggregate as REPERTOIRE COVERAGE.**
A move is in Naren's repertoire if he verifiably said it on ≥2 distinct calls
(61/87 qualify — data already in hand). The coaching question per (CSM, move):
does her whole body of routed calls contain even ONE verified instance? "Never once
over n calls" is significant at p<0.05 within median 13 calls (46/61 moves need
≤20; Madhumita has ≥8 graded calls on 18/30 playbooks, median 11, max 55). No rate
comparison → no dead-check floor → G-S4's failure mode does not apply. Cost: the
CSM production say run, ~300-400 requests. Gates for it are drafted in the findings
doc §9 (output audit + spot-read of every "never" cell + per-cell power rule).

Alternatives (argued in §9): ship rate-gaps at a 0.10 floor (recommended AGAINST —
confident-looking noise at these n's); abandon say moves and coach only the 34
pairwise cells (the fallback; discards 72% of the playbook).

## 5. HOUSE STATE

- `tuning.yaml grader_arm` is back on `pairwise` (fail-safe: setting it to `say` is
  what launches the unlicensed production run — don't, before the §4 decision).
- The pairwise production data (run `137706da74c6`) is untouched and remains the
  live coaching source for DO/MIXED moves; `--report-combined` exists and will show
  say sections automatically once say CSM data exists.
- Everything is uncommitted on `layer-c-profile-rebuild`, on top of the also-
  uncommitted P0 arc. Nothing pushed. (Committing was already on the last handoff's
  list; the pile is now two sessions deep.)
- Spend this session: ~120 gate requests + ~200 benchmark requests, all logged
  (`logs/say_ab_20260828.log`, `logs/say_ab_v2_20260828.log`,
  `logs/say_naren_benchmark_20260828.log`).
