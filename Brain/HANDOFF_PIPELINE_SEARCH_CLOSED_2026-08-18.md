# HANDOFF — the pipeline-internal search space is EXHAUSTED (2026-08-18, morning)

Supersedes `HANDOFF_POST_BENCH_2026-08-17.md` (still valid history). Three trials closed
in one overnight arc, all pre-registered, all audited, all null:

| trial | spec | verdict |
| --- | --- | --- |
| Stage 1 (data effect) | `2026-08-17-expanded-pool-stage1-design.md` | **NULL** — data was not the constraint; milestones fell 171→128 |
| Clustering bench (8 arms) | `2026-08-17-layer-c-clustering-bench-design.md` | **NO WINNER** — survivors lost the blinded read to the incumbent |
| Pool-unit trial (window/turn) | `2026-08-18-layer-c-pool-unit-design.md` | **NULL** — turn support-starves (36<64); window loses the read 0/15 (veto-audited, real) |

Full narratives: `PROBLEMS_AND_FIXES.md` (three new sections),
`docs/findings/expanded-pool-and-clustering-bench.md` (all three trials + program state).

## 1. THE STATE OF KNOWLEDGE (seven closures, none re-openable without new evidence)

Routing quality (F10) · intake filtering (F1/F2, ~20pp ceiling) · admission knobs ·
noise rescue (three separate closures; selection always good, delivery never matters) ·
data volume (G-XP2) · the partitioner (8 arms) · the pooling unit (window + turn).
**The clause+UMAP+HDBSCAN incumbent survives every challenge by forfeit while its own
best milestones fail blinded coherence reads (0–3 of 8 accepted, measured twice by
independent reader panels on the union corpus).** Do not re-propose anything in that
list without reading the findings file first — every one is measured, recorded, and has
its mechanism explained.

## 2. THE THREE LIVE MOVES (all operator decisions, none started)

1. **Gold-pair embedding probe** (cheapest, most decisive): hand-label 30–50 pairs of
   clause groups as same-move vs same-topic-different-move; measure whether gemini@3072
   separates them at all (AUC, blinded labeling, pre-registered bar). AUC~0.5 ⇒ NO
   clustering method can ever work on these vectors and the representation must change —
   redirects everything for the cost of one labeling session. This is the natural next
   spec.
2. **Union-corpus taxonomy rebuild** (Layer A scope): needs the 33,373-turn pool fetch
   (~28 min gateway, deliberately never done) + Gemma describe/adjudication spend + its
   own pre-registration of what "better taxonomy" means. Motivation: G-XP1 measured 64.3%
   of new-corpus pairs sinking — the frozen taxonomy doesn't know the new corpus's
   topics.
3. **Representation change** (LLM move-labeling before clustering): re-opens V1's
   direction with modern discipline — chat spend, new instrument, and the V1-narration
   lesson (`layer-c-milestones-narration-and-ceiling.md`) applies in full.

Parked with reasoning recorded: segmenter-floor loosening (games the support gate);
anchor-clause-display window rematch (new instrument, only worth it if someone still
believes in windows after the seed-1 collapse).

## 3. OPERATOR RULES ADDED THIS SESSION (now in memory too)

- Subagents ONE AT A TIME (limits).
- Outcome audits/vetoes and blinded readers run on the SMALL model (sonnet); code audits
  may use the strong model.
- Everything else unchanged: frozen gates, placebo-veto on unexpected results (fired
  once tonight on the 0/15 — confirmed real), visible windows + completion pings, never
  poll, no Postgres, no published-artifact overwrites, nulls are real results, pytest
  file-by-file, no tuning.yaml change may cite gemini@3072 numbers.

## 4. NEW ARTIFACTS THIS ARC (nothing published was touched)

| | |
| --- | --- |
| pool-unit arms | `layer_bc_pu_u_win.json`, `layer_bc_pu_u_turn.json`, `layer_bc_pu_u_win_b1.json` |
| pool-unit reports | `layer_c_pu_report.json`, `layer_c_pu_report_b1.json` |
| V2 read | `w4_read_u_win.txt` (+KEY), `w4_judgments_u_win.json`, `w4_report_pu.json` |
| unit-text embeddings | 14,883 fetched into the gemini cache (`logs/pu_fetch.log`) |
| harness + tests | `calibration/layer_c_pool_unit.py`, `tests/test_layer_c_pool_unit.py` (16) |
| instrument extension | `layer_c_bench_w4_build.py` now takes `--arms`; pu reads write `w4_report_pu.json`, bench's closed `w4_report.json` untouched |
| stage-1 + bench artifacts | see `HANDOFF_POST_BENCH_2026-08-17.md` §4 |

## 5. THE ASK

Nothing is owed. Pick a live move (§2) — the gold-pair probe is the recommended next
spec (near-free, decisive, and every other move's value depends on its answer).

## 6. ADDENDUM (2026-08-18, day): the gold-pair probe ran

Live move (a) from §2 is DONE — `calibration/gold_pair_probe.py`, run without a
standalone spec on operator instruction, bars frozen in the docstring pre-data. Results
in `gp_math_report.json` / `gp_report.json` / `gp_report2.json`, narratives in
PROBLEMS_AND_FIXES.md and the findings file. Two findings: (1) the space is probably NOT
move-blind — 11/11 gold/anchor observations separate same-move from same-topic (round 2:
AUC 0.966, p=0.0007 on 8 unanimous gold pairs — formally UNDERPOWERED by the frozen
n>=10 bar, reported as such, not upgraded); (2) **same-move recurrence at clause
granularity is SPARSE** (three independent measurements), which undermines the
milestone-as-clause-cluster target regardless of embedding quality and retrospectively
explains the week of nulls. Pending: OPERATOR DECISION between fixing the milestone
pipeline (recurrence says don't), the taxonomy rebuild, and the scenario-level playbook
pivot (evidence-cited synthesis per scenario; fits both findings; discussed with the
operator, awaiting their call). Nominator/verifier/labeler agents all passed every
attention control; all ran on the small model per the operator's limits rule.
