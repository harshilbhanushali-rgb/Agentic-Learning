# Overnight Full Pipeline Run — Analysis & Verdict Plan

**Date written:** 2026-07-29
**For:** a fresh Claude Code session (no memory of the session that wrote this) picking up the next morning after an unattended overnight run.
**Do not re-derive:** everything under "Already settled" below. It cost real investigation time to establish; re-litigating it burns budget for no new information.

## What happened before this file was written

Brain's V2 pipeline (`Brain/`, Python, CS-platform repo) went through evidence-triage clustering rework (2026-07-27) and a Layer C rubric-depth rework (2026-07-28, UMAP+HDBSCAN clustering for milestones, sink-similarity review flag, batched Gemma judge — full detail in `docs/superpowers/specs/2026-07-28-layer-c-rubric-depth-design.md`, read its "Amendment" section first).

A production run of the reworked pipeline (`run_id=492c7be385c5`) produced 85 rubrics but only 241 total milestones — far below a Gemma-free dry-run prediction of 403-407. Investigation (see `CLAUDE.md`'s "Layer C UMAP+HDBSCAN is not reproducible across separate process launches" entry, and the design spec's Amendment section) confirmed the root cause: **UMAP's clustering output is not reproducible across separate process invocations**, `random_state=42` notwithstanding. This was proven with direct per-scenario evidence (`client_availability_and_scheduling_friction` produced 3, then 10, then 8 milestones across three separate process launches of identical code/config/corpus) and corroborated in aggregate: two independent full-corpus runs landed near each other (~400 milestones), while the original production run's 241 was the outlier.

Alongside that investigation, milestone-description Gemma calls were batched (`Brain/v2/layer_c.py`, `_DESCRIBE_BATCH_SIZE = 5`, new `PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH` prompt in `shared/prompts.py`) — replacing one Gemma call per milestone with groups of 5, cutting Layer C's dominant Gemma call count roughly 5x. `run_layer_c_v2` is now four passes (cluster → judge → sequence/kept → batch-describe → finish); see its docstring.

**The reproducibility question was left open, deliberately.** Three options were on the table and none was chosen: (a) accept the run-to-run variance and document it, (b) force stricter UMAP determinism (e.g. pin to a single BLAS thread via an env var), (c) run Pass 1 clustering multiple times per scenario and take a consensus/union of clusters. That decision is one of the things this plan asks you to make, informed by fresh data.

To get a clean baseline unaffected by stale checkpoints, `Brain/clear_data.py` was run (wipes `rubrics`, `kb_pairs`, `scenarios`, `calls`, and all SQLite checkpoints) and a **full fresh V2 pipeline run** (Layer A + B + C from scratch, not just Layer C) was kicked off to run overnight, logging to `run_full_pipeline_20260729.log` at the repo root (`c:\PF\Joveo\CS-platform\`). Command used (for reference, don't rerun unless the log shows it crashed):

```bash
cd "c:/PF/Joveo/CS-platform/Brain"
PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -u main.py > ../run_full_pipeline_20260729.log 2>&1 <<< "2"
```

## Already settled (do not re-check)

- Config (`Brain/tuning.yaml`) was verified correct on disk as of 2026-07-28: `layer_a.merge_cosine_threshold=0.85`, `layer_a.ubiquity_ceiling=0.60`, `layer_b.relative_margin=0.95` (confirmed correct at full 158-scenario scale, do not re-derive), `layer_c.milestone_relevance_percentile=40`, `min_milestone_call_fraction=0.10`, `min_milestone_calls_floor=2`, `milestone_hard_cap=15`, `umap_n_components=5`, `milestone_sink_similarity_percentile=95`.
- The Layer C non-determinism root cause (above) is confirmed, not a hypothesis. Do not re-run the "is it reproducible" experiment from scratch — the evidence already exists in `CLAUDE.md` and the design spec's Amendment section. Your job is to decide what to DO about it, using the new overnight run as a fourth data point.
- The judge/kept-list control flow in `v2/layer_c.py` was read line-by-line and ruled out as a bug source. The batching restructure (four passes) preserved this logic exactly — only *when* the describe Gemma calls fire changed, not the mechanics/genuine_milestone judging logic.
- Ego Trap (`Brain/ego_trap/`) is out of scope — already flagged elsewhere as invalidated by the 148→85 rubric count change, not touched by any of this work.
- 82 pytest tests pass (`cd Brain && ../.venv/Scripts/pytest tests/ -v`) as of the last check before the overnight run. If this regresses, that's new information worth investigating; if it still passes, don't belabor it.

## Snapshots available for comparison

All in the same Postgres database, different schemas (query with `SELECT * FROM <schema>.rubrics` etc. — `psql` is at `C:\Program Files\PostgreSQL\17\bin\psql`, or use `Brain/config.py`'s `load_config()` + `shared/storage.py`'s `get_connection()` from a Python script, never raw `.env` reads — see Gotchas in `CLAUDE.md`):

| Schema | What it is | Rubrics | Total milestones |
|---|---|---|---|
| `baseline_20260728` | Pre-rework (V1-ish taxonomy) | 148 | — (not migrated to evidence columns) |
| `v2_alpha_20260728` | Post evidence-triage rework, pre-UMAP Layer C | 85 | 175 |
| `v2_prebatch_20260728` | Post-UMAP Layer C, pre-batching — **the anomalous production run** | 85 | 241 |
| `v2_postbatch_20260729` | Post-UMAP + post-batching rerun (Layer C only, Layer A/B cached from the prebatch run) | 85 | 398 |
| *(live `public` schema, post-overnight-run)* | Tonight's full clean run — Layer A/B/C all fresh | TBD | TBD |

The live `public` schema tables (`scenarios`, `kb_pairs`, `rubrics`, `calls`) hold whatever the overnight run produced by the time you read this — that IS the new data point, don't snapshot it away before analyzing it. Snapshot it to a new schema (e.g. `v2_overnight_20260729`) *after* you've pulled the numbers you need, so it's preserved before anyone runs the pipeline again.

## What to do

### 1. Confirm the overnight run actually finished cleanly

Read the tail of `run_full_pipeline_20260729.log`. Look for:
- A `RECONCILIATION` block with `without a status : 0` and `All scenarios accounted for.` — if missing, the run crashed or is still going; check the process and don't proceed to analysis until it's actually done.
- Any `Traceback` — if present, that's a bug to triage first (systematic-debugging skill), not something to route around.
- Count of `[gemma] ... Escalating to next model/key` or `hit a rate/quota limit` lines (`shared/gemma.py`'s `MODEL_FALLBACK_ENABLED` mechanism) — if this fired heavily, some fraction of the run used a different model than `gemma-4-31b-it`, which is worth noting as a caveat on any comparison to prior runs (which may or may not have hit the same fallback).

### 2. Pull the headline numbers, all layers

Query the live (post-run) tables:
- `scenarios`: total count, `is_coachable` split, `cluster_kind` split, `rubric_status` distribution (compare shape to the 158/85/73 split from the prebatch/postbatch runs — is it structurally similar, wildly different, or in between?).
- `kb_pairs`: total count, and the one/two/three-scenario match-width distribution (`array_length(scenario_keys, 1)`) — compare to the "63%/19%/18%" production match width recorded in `CLAUDE.md`.
- `rubrics`: count, total milestones (`sum(jsonb_array_length(milestones))`), and the full depth distribution (`GROUP BY jsonb_array_length(milestones)`) — this is the number that answers the reproducibility question. Compare directly against 241 / 398 / the predicted 403-407 band.

### 3. Answer the reproducibility question with a 4th data point

Where does tonight's total milestone count land relative to 241 (anomalous), 398 (rerun), and 403-407 (dry-run prediction)?

- **If it's close to ~400 again:** that's now 3-of-4 runs clustering near 400, with the original 241 the sole outlier. Strengthens the case that 241 was a one-off unlucky draw, and leans the verdict toward option (a) — accept the variance, maybe rerun once if a rubric set looks thin, rather than investing in forcing determinism.
- **If it's notably different from BOTH 241 and ~400 (a new value):** that's stronger evidence of real run-to-run variance requiring an actual fix, not just "one bad run" — leans toward option (b) or (c).
- **If Layer A also produced a different scenario count than 158** (BERTopic has its own documented non-determinism in `CLAUDE.md`, "241→231→226 raw clusters"), account for that separately — a different scenario count changes what "the same taxonomy" even means for comparison, and the milestone-count comparison above is only apples-to-apples if the scenario taxonomy itself is roughly stable. If Layer A drifted a lot, say so explicitly rather than silently comparing milestone counts across different taxonomies.

### 4. Spot-check quality, not just counts

Pick 5-10 scenarios at random from tonight's run and read their actual milestone `label`/`description`/`detection_hint` fields plus a couple of their `support_calls`-backing clauses (via `kb_pairs` or by re-deriving from the transcript). Ask: do these read as genuine, coachable strategic moves, or does the higher milestone count (if it is higher) come with junk that the sink-similarity review flag and Gemma judge should have caught but didn't? A "win" on total count is not a win if depth came from backchannel leaking through. This is the same discipline the original design spec used (`--merge-detail`-style reading, not just counting) — don't skip it just because it's slower than a SQL query.

### 5. Render a verdict

Produce a written verdict (a new dated section appended to the design spec doc, `docs/superpowers/specs/2026-07-28-layer-c-rubric-depth-design.md`, plus a summary in `CLAUDE.md` following its existing dense-bullet style) covering:

- **Is the overnight run's output good enough to treat as the new live baseline**, or does it need another pass?
- **A recommendation on the non-determinism question** — pick one of (a)/(b)/(c) from "Still open" above, or propose something better, with reasoning grounded in tonight's actual data rather than re-running more experiments unless the data genuinely doesn't answer the question.
- **Any new issues found across Layer A/B/C** that weren't visible before (e.g. a new failure mode, a scenario that looks systematically broken, a match-width or coverage number that's moved in a concerning direction).
- **Concrete next action** — what should actually change in the codebase/tuning.yaml (if anything), or confirmation that nothing needs to change and the current state should just be adopted as-is.


