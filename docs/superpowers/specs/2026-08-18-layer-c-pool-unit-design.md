# Layer C pooling-unit trial — clause vs window vs turn (2026-08-18)

**Status: PRE-REGISTERED, NO CODE YET. Gates frozen in this file before any harness
exists.** Handoff context: `Brain/HANDOFF_POST_BENCH_2026-08-17.md`. Predecessors:
stage 1 (`2026-08-17-expanded-pool-stage1-design.md`, G-XP2 NULL) and the clustering
bench (`2026-08-17-layer-c-clustering-bench-design.md`, NO WINNER). Zero chat calls,
zero Postgres writes; ONE bounded embedding fetch (see §6) then cache-only.

## 1. Question

Six directions are measured non-binding at Layer C: routing quality, intake filtering,
admission knobs, noise rescue, data volume, and the partitioner itself. The one variable
never varied is the POOLING UNIT. Layer C clusters response CLAUSES — the exact unit the
Layer A pool-unit trial measured as the root cause of posture-scenario contamination and
shipped OFF (`Brain/docs/findings/layer-a-pool-unit-1.md`); Layers A and B both operate
turn-shaped and bench fine. Tonight's W4 positive controls (readers accepted 0–3 of 8 of
the incumbent's best milestones) match the clause-mode failure signature. Operator
observation that triggered this spec: "Layer A is built turn-based and the rest is not."

Does changing the unit Layer C embeds and clusters — clause → discourse window → whole
response turn — produce milestones that WIN a blinded coherence read against the clause
incumbent, without degrading account-diversity lift?

## 2. The unit ladder (arms, frozen)

All arms share: the union corpus (393+690 calls), taxonomy `clean2_base` FROZEN, stage-1
routing (pairs and scenario assignments IDENTICAL across arms — the unit changes nothing
upstream of Layer C), production UMAP+HDBSCAN with production-rule granularity (the bench
just established no alternative partitioner is better; changing unit AND partitioner
would be two variables), the production p40 relevance filter applied to each arm's own
unit texts (symmetric percentile), and the production support gate
(`required_milestone_support`, distinct calls — unit-independent by construction).

| arm | unit embedded & clustered | frozen construction rule |
| --- | --- | --- |
| `u0` clause | production verbatim | = the bench's `c0` (artifact reused, not re-run) |
| `u_win` window | contiguous non-overlapping windows of 3 clauses within one response | remainder window kept if >= 2 clauses, else merged into the previous window; a response with < 3 clauses is one window |
| `u_turn` turn | one whole response turn = one unit | the response text as segmented input, whole |

**The canonical-membership rule (what makes arms comparable):** whatever the unit, a
milestone RESOLVES to its underlying clause set (a turn = its clauses; a window = its
clauses). All cross-arm accounting (`match_milestones`), the support gate, and every
blind-read display operate on resolved clause sets. Units change the GEOMETRY the
clusterer sees, never the bookkeeping.

Stated risk, both directions, on the record now: `u_turn` may over-blur (one Naren
response can contain several moves + pleasantries — one vector averages them);
`u_win` at 3 clauses is the "move arc" length bet. `u0` may under-slice. That is the
ladder's point.

## 3. Gates (frozen). A winning unit must clear ALL of V0–V4

- **V0 — validity (mandatory).** The harness's `u0` clause path must reproduce the bench
  `c0` artifact's per-scenario milestones exactly (same substrate discipline as F0-bench).
  Any diff → harness bug, nothing reportable. Seed-jitter floors are inherited from the
  bench's base-42 report (the floor is a property of the incumbent's seed sensitivity,
  defined once — W5-procedure precedent).
- **V1 — support accounting (stop rule).** An arm whose total surviving-milestone count
  falls below HALF of `u0`'s is reported as support-starved and cannot win (a unit that
  cannot clear the existing evidence bar is not an answer to this question — stated now
  so a 5-milestone arm cannot be narrated as a win).
- **V2 — PRIMARY: blinded coherence read, WON.** The audited W4 instrument reused
  verbatim (`calibration/layer_c_bench_w4_build.py` discipline: twin exclusion at
  Jaccard 0.5 on RESOLVED clause sets, no metadata on singles, equal bullet counts,
  samples/key separate, judgments committed before the key opens, scrambled negatives
  >= 80% rejected or the reader is void, positive controls recorded). Items = paired
  arm-vs-`u0` milestone RESOLVED clause sets at matched support; n >= 12 pairs;
  WON = arm preferred in >= 2/3 of pairs AND two-sided sign test p < 0.05. Independent
  blinded readers, dispatched ONE AT A TIME (operator limits rule).
- **V3 — account-diversity lift not degraded.** Rev-4 paired sign test vs `u0`, ONE
  yardstick (`null_draw_weights_union.json`). DEGRADED = down > up AND p < 0.05. An arm
  that IMPROVES lift is reported as such — it would be the first move of this metric ever.
- **V4 — stability.** V1–V3 directions hold at base seeds 1 and 7 (UMAP inheritance —
  same W5 procedure as the bench: `u0`'s reference re-runs included).

## 4. Readouts (descriptive, pre-registered)

Per arm: unit-count and unit-length distributions; post-p40 pool sizes; resolved
milestone counts against the ~6-milestone repartition floor; per-scenario outcome table;
gained/lost/merged vs `u0` on resolved clause sets; positive-control acceptance rate in
the V2 read (does any arm's best beat the incumbent's 0–3 of 8?); wall time. The
`mcs`/`required_support` values actually resolved per scenario per arm (unit changes pool
sizes, so the fraction-scaled knobs move — that is part of the treatment, not a confound,
and is reported not "corrected").

## 5. What this CANNOT answer (stated now)

- Whether coaching moves exist at ANY unit (all-arms-null → the gold-pair probe /
  "the grain does not exist" conversation, a separate pre-registration).
- Anything about production bge@768: everything here is gemini@3072 turn-mode taxonomy.
  Directions transfer, numbers do not. **No `tuning.yaml` change may cite this trial
  alone.**
- Whether V1-style LLM-direct milestone generation beats clustering (closed once as
  narration; re-opening it is a different spec with a different instrument).

## 6. Cost & mechanics

One bounded embedding fetch BEFORE the run (then cache-only shim, abort on miss):
`u_turn` needs ~12.4k distinct response-turn texts; `u_win` needs ~25–30k window texts
(join of cached clauses — text differs from any cached string, so it is a real fetch).
Estimated 30–45 min gateway total at observed req/s; VPN required. Zero chat calls.
Runs from `Brain/` via `ops/run_visible.ps1` with completion pings, never polled.
New harness file + tests; ONE pre-run blind subagent audit (strict bar) before any arm
runs; artifacts `layer_bc_pu_<arm>[_b<seed>].json`, no published artifact overwritten.

## Pre-run blind audit

One subagent audit (2026-08-18, before any arm ran), strict bar: **CLEAN — no
outcome-bearing defect.** Checked hardest: (1) V0 exit-ladder fidelity — the harness's
clause-path mirror reproduces stage 1's `clause_pool` derivation in every reachable state
(all three capture-bearing outcomes hold the full post-filter pool; the `<2/<6/<6` exits
map to `[]` on both sides); any residual drift fails V0 loudly and `score()` refuses on
`v0_fail`. (2) Fetch coverage — `--fetch` is a strict superset of what the arms embed;
the V0 clause path's texts are proven cached by stage 1's own completed cache-only run;
any gap hits the shim's abort, never a silent measurement. (3) Scorer join + seed
plumbing — both milestone shapes carry every field `match_milestones` /
`milestone_calls` / `distribution_stats` read; `base_seed` reaches the clusterer for
both arms; the V4 join targets the bench's `c0_b<seed>` artifacts by their exact names.

Two audit notes adopted into this spec: **(a) V0's operationalization is the
POST-FILTER CLAUSE POOL identity against the stage-1 artifact** (same instrument as the
bench's F0-bench) — c0's labels are production's in-process output that cannot be
re-derived across processes, and c0 is frozen as "reused, never re-run", so pool-level
identity IS the V0 contract, stated here so it cannot be read post hoc as a weakened
gate. **(b)** pu milestones' `median_position` is a median-of-unit-medians, a
descriptive field no V0–V4 gate reads; if the V2 instrument ever samples or pairs by
position it must resolve position from the milestone's RESOLVED clause set instead.

## RESULTS

Run 2026-08-18, unattended (operator asleep). `--fetch` 6.3 min (15,248 distinct unit
texts, 14,883 fetched, cache re-read 0 missing); `--run` 12.9 min; **V0 PASS on the full
corpus** (every scenario's production clause path reproduced stage 1's post-filter pool).
Zero chat calls, zero Postgres. Readers ran on the small model per operator limits rule;
the veto audit likewise.

**Base-42 gate table** (u0 = bench c0: 128 ms, 35.0% noise; V1 floor = 64):

| arm | ms | noise% | matched | merged | split | lost | gained | lift up/dn (p) | V1 | V3 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| u_win | 71 | 30.4 | 18 | 23 | 9 | 78 | 46 | 16/10 (.33) | Y | Y |
| u_turn | 36 | 36.7 | 6 | 16 | 8 | 98 | 24 | 13/10 (.68) | **n** | Y |

- **u_turn: DEAD at V1** (36 < 64 — support-starved), exactly the over-blur risk §2
  stated: one vector per response averages several moves plus pleasantries, and units
  per call shrink so distinct-call support collapses. Cannot win by the frozen stop rule.
- **u_win: survived V1+V3** — noise below the incumbent (30.4% vs 35.0%) and the most
  positive lift direction ANY Layer C arm has ever shown (16 up / 10 down; p=0.33, not
  significant — recorded as direction, not evidence).
- **V2 PRIMARY: NOT WON — 0 arm / 15 c0 / 0 tie, p=0.0001.** Three independent blinded
  readers (all VALID: 8/8 scrambled negatives rejected each; positive controls 2/0/3 of
  8 accepted — the incumbent's best milestones again read mostly incoherent) unanimously
  preferred the incumbent's milestone sets in every pair. Per the placebo-veto rule this
  extreme result was NOT believed until audited: the veto audit hand-recomputed all 15
  pairs from the raw key+judgments (exact reproduction; the arm-side mapping verified in
  both directions on items 1 and 18; NEG/POS indexing spot-checked clean; arm_side split
  10A/5B — uneven but n=15-normal, scoring is per-item so unaffected) and read 6 pairs
  blind-first: **CONFIRMED, real content effect.** Mechanism: a window milestone's
  resolved clause set includes each window's NEIGHBOR clauses — status-check chatter,
  call-intro/handoff filler — so every displayed group is diluted by conversational
  context, while c0's single-clause groups contain only clauses that each independently
  instantiate the move.
- **V4: moot** — V2 is failed at base 42 and gates are conjunctive; the seed-1 re-run
  (already in flight when V2 closed) is recorded as a descriptive readout only, not a
  gate. That readout REINFORCES the null: at base 1 (V0 PASS again), u_win falls to 63
  milestones — under that base's own V1 floor of 68 — and its lift lean flips to 12/14.
  The base-42 V1/V3 survivals were seed-fragile; the 16/10 lift lean was jitter. Seed 7
  not run (moot twice over).

**VERDICT: NULL — neither alternative unit beat the clause incumbent under the frozen
instrument.** The unit ladder's two ends both failed for the reasons pre-stated as
risks: turns over-blur (support starvation), windows drag context (coherence dilution).

**Instrument caveat, on the record (from the veto audit, verbatim in spirit):** this
read compares RESOLVED clause sets — the canonical-membership rule §2 froze that
deliberately — so the window arm's loss is attributable to window COMPOSITION (neighbor
clauses entering the displayed evidence), not necessarily to worse GROUPING decisions.
A unit-fair rematch would need anchor-clause-only display (one clause per window
instance), which is a NEW instrument requiring its own pre-registration. Until someone
pre-registers that, the honest claim is: **window-built milestone evidence sets are
unanimously worse to read; window clustering-decision quality is untested.**

**Where this leaves the program:** every candidate binding constraint is now measured —
routing, intake filtering, admission, rescue, data volume, the partitioner, and the
pooling unit (at both alternative granularities). The clause+UMAP+HDBSCAN incumbent
survives its seventh challenge by forfeit while its own best output fails coherence
reads. The remaining moves are OUTSIDE this pipeline shape: (a) the gold-pair probe —
does the embedding space encode move-similarity at all, at any unit? (~free, decisive
about whether ANY clustering can work); (b) the union-corpus taxonomy rebuild (Layer A
scope, Gemma spend); (c) a representation change (e.g. LLM move-labeling before
clustering — chat spend, needs its own instrument). All three are operator decisions.
