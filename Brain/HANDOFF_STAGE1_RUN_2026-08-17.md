# HANDOFF — run stage 1 + the Layer C clustering bench (2026-08-17, night)

Everything is BUILT, TESTED, AUDITED and PRE-REGISTERED; almost nothing has RUN. The prior
session (this one) spent its time on harness construction and two pre-run blind audits so
that the runs themselves are mechanical. Operator context: prefers NEW harnesses over
extending old ones; placebo-veto rule (any unexpected placebo result gets a subagent audit
of code AND output before being believed); minimal subagents (1 blind audit per new harness
+ independent blinded readers only); run long tasks in a VISIBLE window
(`ops/run_visible.ps1`); after launching a task set a completion PING, never poll.

## 1. WHERE THINGS STAND

- **Two new harnesses, both audited pre-run with all findings fixed** (audit records are IN
  the specs — read them before touching either file):
  - `calibration/expanded_pool_stage1.py` + `tests/test_expanded_pool_stage1.py` (17 tests)
    — spec `docs/superpowers/specs/2026-08-17-expanded-pool-stage1-design.md` (gates
    G-XP0..G-XP3 frozen; 6 audit findings fixed, incl. 2 crashes).
  - `calibration/layer_c_cluster_bench.py` + `tests/test_layer_c_cluster_bench.py` (9
    tests) — spec `docs/superpowers/specs/2026-08-17-layer-c-clustering-bench-design.md`
    (arms + gates W1–W5 frozen; W5 procedure frozen after the audit caught it unscoreable;
    3 outcome-bearing findings fixed).
- **Embeddings:** response clauses for `recordings_pull_keep/` are FETCHED AND VERIFIED
  (58,618, 0 missing on cache re-read — `logs/fetch_pull_keep_embeddings.log`). A trigger
  fetch (8,467 new-corpus triggers; `scope_layer_bc_embeddings.py --fetch` covers CLAUSES
  ONLY — read its source, that was nearly missed) was launched in the background:
  `logs/fetch_pull_keep_triggers.log`, must end with `TRIGGER FETCH COMPLETE`.
  **FIRST ACTION: check that log; if it did not complete, re-run
  `scratchpad fetch_pull_keep_triggers.py` — it resumes from cache** (the script body is
  8 lines; if the scratchpad is gone, rebuild it from this description: parse_corpus +
  build_pairs over `recordings_pull_keep`, uniq trigger_texts, `embed_cached(uniq, 20)`,
  verify via `layer_bc_arms._load_cached`). Gateway needs the Joveo VPN (symptom when off:
  DNS resolves, TCP times out).
- **The 33,373-turn Layer A pool was deliberately NOT fetched** — needed only for a future
  taxonomy rebuild (operator decision), not for stage 1 or the bench. Do not fetch it as a
  side effect; it is ~28 min of gateway spend.
- **Nothing measured yet:** no smoke, no stage-1 run, no union weights file, no bench arms.
- `recordings/` (393) and `recordings_pull_keep/` (690 + sidecars) both untouched;
  taxonomy `clean2_base` frozen (26 coachable + 125 sinks); published control =
  `artifacts/layer_bc_s0a0r0_b.json` (171 ms / 26 scen, corpus_sha `870b46b3b6d10ad6`).

## 2. THE RUN SEQUENCE (all from `Brain/`, venv `..\.venv\Scripts\python.exe`)

1. **Verify trigger fetch complete** (above).
2. **Smoke stage 1** (~3–5 min, path test only, writes a SMOKE artifact, never scoreable):
   `..\..venv\Scripts\python.exe calibration/expanded_pool_stage1.py --smoke`
   Two full launches in this repo died mid-generation on defects `py_compile` cannot catch
   — do not skip this. If it crashes, fix and re-smoke before the real run.
3. **Full stage-1 run in a visible window** (est. 40–90 min: two spaCy parses of 1,083
   calls, routing ~12k pairs, 26 UMAP+HDBSCAN fits):
   `powershell -File ops/run_visible.ps1 -Script calibration/expanded_pool_stage1.py
   -ScriptArgs "--run" -Log logs/xp_stage1_run.log`
   (run_visible gotchas are documented in the script: `-ScriptArgs` must be ONE string.)
   Set a background ping on artifact appearance
   (`while (-not (Test-Path artifacts/layer_bc_xp_union.json)) { Start-Sleep 30 }` as a
   background task), then do other work — e.g. pre-read the bench code.
   The run writes `artifacts/layer_bc_xp_union.json` + `null_draw_weights_union.json`.
   It prints `[G-XP0] F0-union: PASS` — **if FAIL, nothing is reportable; debug the
   harness, do not score.**
4. **Score stage 1** (free, re-runnable):
   `..\..venv\Scripts\python.exe calibration/expanded_pool_stage1.py --score`
   writes `artifacts/xp_stage1_report.json`. NOTE: `score_layer_b_arms.py` canNOT score
   the union arm (its account map spans two dirs; the two-yardstick logic lives in
   `--score`). READ THE OUTPUT HARD, in this order:
   - **G-XP1** new-pair sink share (stop bar 0.75; old corpus published 57.9%). If it
     STOPs: the finding IS the routing readout — the new corpus talks about things this
     taxonomy doesn't know. Read where new pairs actually went (top-5 absorption,
     new accounts per scenario) before writing anything.
   - **G-XP2 PRIMARY** — rev-4 account-diversity paired sign test. PASS = p<0.05 AND
     net>0 AND the shared-yardstick sensitivity view agrees in direction. **Nothing has
     EVER moved this metric; a PASS means data was the constraint and promotion of the
     690 is justified** (that promotion itself is the OPERATOR's decision, not yours).
     A NULL is a real result: the clusterer eats evidence faster than data supplies it —
     it raises the bench's stakes.
   - **G-XP3** milestone accounting: read counts against the ~6-milestone UMAP
     repartition floor; report DIRECTION of flips; gains split into new_data_necessary /
     new_account_backed vs repeat-account padding.
   - Roster-confound flag: if accounted_frac gaps >10pp between arms, say the primary is
     confounded — the new sidecars may resolve accounts at a different rate.
   - The 33 failing clusters' fate + scenario no_support→clustered flips (descriptive).
5. **Fill the stage-1 spec's RESULTS section** + update `Brain/PROBLEMS_AND_FIXES.md` and
   CLAUDE.md (a compressed section like the existing 2026-08-17 ones).
6. **Smoke the bench**: `calibration/layer_c_cluster_bench.py --smoke` (needs stage-1
   artifact present; writes nothing).
7. **Run the bench in a visible window** (est. several hours — 26 scenarios × ~9 arms;
   `hdb_raw` on the largest pools and the per-scenario 8-point leiden γ grid dominate):
   `powershell -File ops/run_visible.ps1 -Script calibration/layer_c_cluster_bench.py
   -ScriptArgs "--run" -Log logs/layer_c_bench_run.log`
   Ping on `artifacts/layer_bc_cb_rescue_plc.json` (written last in registry order).
8. **Score**: `calibration/layer_c_cluster_bench.py --score` → gate table W1–W3 per arm
   (floors: partitioners ≤ seed-jitter max; rescue ≤ its placebo). Then:
   - **W4 blind read ONLY for W1–W3 survivors**: independent reader subagents, samples
     and answer key in SEPARATE files, judgments committed before the key is opened;
     items = paired arm-vs-c0 milestone clause sets at matched support + scrambled
     negatives (≥80% rejected or the reader is void) + positive controls (EXPECTED
     ~half-imperfect). n≥12 pairs, won = ≥2/3 preference, sign test p<0.05.
     `calibration/blind_read_powered.py` is the builder precedent.
   - **W5 for survivors**: `--run --base-seed 1 --arms c0,<survivors>[,rescue_plc]` then
     `--score --base-seed 1` (the partitioner W2 floor auto-loads from the base-42
     report), same at seed 7. W1–W3 directions must hold at both.
9. **Spec RESULTS, PROBLEMS_AND_FIXES.md, CLAUDE.md, and a fresh handoff.**

## 3. NON-NEGOTIABLES (unchanged, all re-earned this week)

Gates are FROZEN in the two specs — changing one after seeing a result is gate-tampering;
a metric that is an arm's objective cannot rank arms; placebos match what the arm ADDS;
report flip DIRECTION never a rate; symmetric filtering (diff the filtered lists per arm);
import production code, never paraphrase (the bench's one paraphrase,
`_cluster_milestones_seeded`, is F0-checked against production per scenario); read real
samples before believing any aggregate (the unit of reading for a modifying rule is the
MODIFICATION — for `rescue` read its ADMITTED clauses, not whole clusters); `no_cache=True`
on any gateway chat A/B (no chat calls are expected in any of this); NEVER write to
Postgres; never overwrite a published artifact (`--overwrite` scopes are deliberate);
artifacts carry started_at/pid/seed/shas. Everything is gemini@3072 on the turn-mode
taxonomy — **no `tuning.yaml` change may cite these numbers.** Run pytest file-by-file
(documented spaCy OOM on this box).

## 4. WHERE THINGS LIVE

| | |
| --- | --- |
| `calibration/expanded_pool_stage1.py` | stage 1: --smoke / --run / --score |
| `calibration/layer_c_cluster_bench.py` | bench: --smoke / --run / --score / --base-seed |
| the two specs (gates + audit records) | `docs/superpowers/specs/2026-08-17-expanded-pool-stage1-design.md`, `...-layer-c-clustering-bench-design.md` |
| published control | `artifacts/layer_bc_s0a0r0_b.json` |
| failing-cluster baseline (F0-proven) | `artifacts/layer_bc_lcfr_real_p40.json` |
| published yardstick (never touch) | `artifacts/null_draw_weights.json` (sha 6d3a2ba9e5894719) |
| union yardstick (written by --run, staleness-guarded) | `artifacts/null_draw_weights_union.json` |
| stage-1 outputs | `artifacts/layer_bc_xp_union.json`, `xp_stage1_report.json` |
| bench outputs | `artifacts/layer_bc_cb_<arm>[_b<seed>].json`, `layer_c_bench_report[_b<seed>].json` |
| embed cache logs | `logs/fetch_pull_keep_embeddings.log` (clauses, DONE), `logs/fetch_pull_keep_triggers.log` (CHECK FIRST) |
| prior handoff (context for all of this) | `Brain/HANDOFF_EXPANDED_POOL_2026-08-17.md` |

## 5. THE ASK

Verify the trigger cache, smoke, run stage 1 visibly, score it, READ it hard (especially
where the new pairs and new accounts actually land), fill the spec, then the bench end to
end (W4 only for survivors, W5 at seeds 1 and 7). A null anywhere is a real result. Update
CLAUDE.md / PROBLEMS_AND_FIXES.md as you go, and leave your own handoff.
