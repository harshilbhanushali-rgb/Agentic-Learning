# HANDOFF — stage 1 and the clustering bench are BOTH CLOSED (2026-08-17, late night)

Everything in `HANDOFF_STAGE1_RUN_2026-08-17.md` RAN tonight, end to end, unattended.
Both verdicts are in, written up, and audited. Nothing is left mid-flight. This handoff
is the state of the world for the next session.

## 1. WHAT RAN AND WHAT IT SAID (details: the two specs' RESULTS + PROBLEMS_AND_FIXES.md + `docs/findings/expanded-pool-and-clustering-bench.md`)

- **Trigger-embedding fetch**: the prior session's background fetch had DIED at 4,800/6,548;
  resumed from cache in ~1 min, verified 0-missing. (Lesson intact: verify fetch logs end
  with their completion marker before trusting them.)
- **Stage 1 (data effect)**: G-XP0 PASS, G-XP1 testable (new-pair sink 64.3%),
  **G-XP2 PRIMARY NULL** (12up/13down p=1.0; raw N_eff up 20/5 p=0.004 — reach grew
  exactly at chance rate for the richer pool), G-XP3 milestones **171→128** (merged=64;
  mcs-clamp + rising required_support where pools grew — audited mechanism).
  **Data was NOT the constraint. Promotion of the 690 is NOT supported** (operator call).
- **Clustering bench**: F0-bench + F0-seed PASS at bases 42/1/7. agglo/hdb_dbl/hdb_raw die
  on gates (hdb_raw: 96.1% noise — the raw-space pathology survives at 3072). Survivors
  leiden/hdb_half/rescue held W1–W3 at all three seeds (W5), then **both partitioners LOST
  the W4 blinded coherence read to the incumbent** (5-8-2, 6-8-1); rescue NOT WON (10-5-0
  p=0.30, aggregates placebo-equal at every seed — third and final closure of rescue).
  **NO WINNER — the incumbent stands by forfeit.**
- **The sharpest number of the night**: W4's positive controls. Readers who rejected 100%
  of scrambled negatives accepted only **0–3 of 8** of the incumbent's HIGHEST-SUPPORT
  milestones as coherent coaching moves. "~half incoherent" was optimistic.
- **Two subagent audits beyond the pre-registered ones, both on operator request**:
  the W4 builder pre-read audit (4 outcome-bearing defects fixed — twin pairs, metadata-
  separable controls, rescue estimand restriction now on record, unequal bullet counts)
  and a post-run stage-1 audit (CLEAN; the identical primary/sensitivity 12/13 split is
  arithmetically forced — recomputed per-pair; 171→128 is a pipeline property, not a
  harness artifact).

## 2. THE STANDING PICTURE (what is now MEASURED non-binding)

Routing quality (F10) · intake filtering (F1/F2, ~20pp ceiling) · admission knobs (a1/a4)
· noise rescue (three closures) · **data volume (tonight)** · **the partitioner (tonight)**.
The never-varied variable is the **POOLING UNIT**: response clauses at this granularity may
not contain cluster-recoverable coaching moves at the assumed rate. Precedent:
`docs/findings/layer-a-pool-unit-1.md` (clause vs turn, measured at Layer A, shipped OFF).
The Layer C analogue has never been run — that is the pre-registration-worthy next
question. Alternative next direction (operator preference may differ): the taxonomy
rebuild on the union corpus (needs the 33,373-turn Layer A pool fetch, ~28 min gateway,
deliberately NOT done tonight).

An idea floated by the operator tonight, parked with reasoning recorded: loosening the
segmenter's 4-token floor — rejected for now because that population games the
distinct-call support gate and every adjacent measurement says intake volume is not
binding; if revisited, it needs a content-matched placebo and a coherence-read outcome
metric, never the support metric.

## 3. NON-NEGOTIABLES (unchanged; all held tonight)

Frozen gates never adjusted post-result; placebos match what the arm ADDS; symmetric
filtering; import production code (the bench's one paraphrase is F0-checked per scenario);
read real samples before believing aggregates (unit of reading for a modifying rule = the
MODIFICATION); blind reads: samples/keys in separate files, judgments committed before the
key opens, scrambled-negative validity bar; NEVER write to Postgres; never overwrite a
published artifact; a null is a real result. Everything tonight is gemini@3072 turn-mode
`clean2_base` — **no `tuning.yaml` change may cite these numbers.** Run pytest
file-by-file (spaCy OOM). Launch long runs via `ops/run_visible.ps1`, set a completion
ping, never poll. Operator limits note (tonight): subagents ONE AT A TIME unless told
otherwise.

## 4. ARTIFACT INVENTORY (all new tonight, none overwrite anything published)

| | |
| --- | --- |
| stage-1 arm + report | `artifacts/layer_bc_xp_union.json`, `xp_stage1_report.json` |
| union yardstick | `artifacts/null_draw_weights_union.json` (sha b6bae0af6e245678, 12,444p; staleness guard is n_pairs-only — noted) |
| bench arms base 42 | `artifacts/layer_bc_cb_<arm>.json` (10 arms) |
| bench arms seeds 1/7 | `artifacts/layer_bc_cb_<arm>_b1.json` / `_b7.json` (c0, leiden, hdb_half, rescue, rescue_plc) |
| bench gate reports | `artifacts/layer_c_bench_report.json`, `_b1.json`, `_b7.json` |
| W4 instrument | `calibration/layer_c_bench_w4_build.py`; packets `artifacts/w4_read_*.txt`, keys `*_KEY.json`, judgments `w4_judgments_*.json`, report `w4_report.json` |
| published control / yardstick | UNTOUCHED (`layer_bc_s0a0r0_b.json`, `null_draw_weights.json`) |
| logs | `logs/xp_stage1_run.log`, `layer_c_bench_run.log`, `_b1.log`, `_b7.log`, `fetch_pull_keep_triggers.log` |

## 5. THE ASK FOR THE NEXT SESSION

Nothing is owed. Both trials are closed and written up (specs' RESULTS,
PROBLEMS_AND_FIXES.md, `docs/findings/expanded-pool-and-clustering-bench.md` + INDEX row).
The two live directions are OPERATOR DECISIONS, not continuations: (a) pre-register a
Layer C pooling-unit trial (the one never-varied variable), or (b) the union-corpus
taxonomy rebuild (fetch the 33k-turn pool first). Do not re-propose rescue, intake
filters, admission knobs, more data, or a different clusterer without reading
`docs/findings/expanded-pool-and-clustering-bench.md` first — all measured, all closed.
