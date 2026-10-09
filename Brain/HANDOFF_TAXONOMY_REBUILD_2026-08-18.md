# HANDOFF — execute the union-corpus taxonomy rebuild (2026-08-18, night)

You are executing an APPROVED, FROZEN spec:
`docs/superpowers/specs/2026-08-18-union-taxonomy-rebuild-design.md`. Read it in full
first — every gate (T0–T2, G-R1–G-R4, PV), every constant, and the §0 decisions are
frozen and not re-litigable. This file tells you the state of the world, what to reuse,
and the order of work. Supersedes `HANDOFF_PLAYBOOK_VALIDATED_2026-08-18.md`.

## 0. WHY (settled 2026-08-18 — do not re-derive)

1. **The playbook method is VALIDATED** — two same-day pre-registered trials
   (`2026-08-18-scenario-playbook-trial-design.md` §11,
   `2026-08-18-playbook-snap-trial-design.md` §9): synthesis → verbatim snap → PB0
   passed 10/10; blinded counterbalanced discrimination WON 5/5 scenarios (14/15
   votes); PB3 median 1.0. The first Layer C product path ever to beat its placebo.
   Playbooks are the Layer C target; milestones are retired (recurrence is sparse —
   gold-pair probe).
2. **The map is the bottleneck** — G-XP1 measured 64.3% of new-corpus pairs sinking
   under the frozen `clean2_base` 26: the taxonomy doesn't know the new corpus's
   topics. The rebuild is the standing open Layer A move, now with a consumer.
3. **Rebuild WITH `rescue_centroid`** (spec §0.1) — its "doesn't matter" closure was
   priced against the retired milestone yardstick; its measured wins (substantive
   coverage 45→68%, 96→133 calls/scenario, account concentration down) are exactly
   what playbook evidence selection consumes; zero extra chat (cluster count fixed by
   construction); measured in this rebuild's own space (gemini@3072 turn mode). The
   un-rescued base clustering is persisted as fallback, NOT adjudicated.
4. **Routing stays production `concat`** (spec §0.2, standing bar from the routing
   record) — the three-arm routing A/B (`concat` / `keyphrases` / `r1
   membership-lookup+fallback`) is pre-registered by name, runs ONLY after PV passes,
   under its own future spec.

Operator approvals given in-session: the direction, the rescue decision, and the
budget — **~300–450 adjudication chat calls (HARD STOP 500), ≤ 50 PV calls, ~28-min
embedding fetch**. Ask before exceeding any of those, and at every gate failure.

## 1. THE ORDER OF WORK

1. **Harness + tests** per stage (pool/fetch, cluster+rescue, adjudication driver,
   taxonomy gates, PV rebind). Reuse, never re-implement (see §2). Pure rules
   unit-tested with hand-built inputs (the house pattern).
2. **One blind CODE audit per new harness** (strong model), all findings fixed and
   recorded in spec §9 BEFORE that harness spends anything.
3. **Stage A:** T0 pool check (old corpus must be exactly 20,788 CLIENT turns — hard
   abort otherwise), then the new-turn embedding fetch in a visible window + ping.
4. **Stage B:** cluster + rescue (free), persist both membership sets, T1 readout.
5. **Stage C:** adjudication, arm `union_rescued`, visible window + ping, resumable,
   every attempt counted and persisted pre-POST, T2 integrity checks.
6. **Stage D:** taxonomy gates G-R1–G-R4 (all free; G-R4 needs 3 blinded sonnet
   readers, one at a time, sealed key, duplicate-reader guard).
7. **Stage E:** playbook validation on the new map (PV) — the snap-trial pipeline
   rebound to the new map, `pbv_*` artifacts, bars unchanged, plus the one frozen
   prompt hardening (distinct accounts per key move = requirement).
8. Fill spec §10 RESULTS, update `PROBLEMS_AND_FIXES.md`, the findings file
   (`docs/findings/scenario-playbook-trial.md` gets the PV outcome; a new findings
   file + INDEX row for the rebuild itself), and leave a fresh handoff.

## 2. MACHINERY TO REUSE (import it; paraphrasing production is the repo's oldest bug)

| need | use |
| --- | --- |
| parse + pairs + routing | `calibration/layer_bc_arms.py` (`parse_corpus`, `build_pairs`, `scenario_map_from_rows`, `install_embedder_shim`, `prewarm`), `v1/layer_b.assign_scenarios`, `expanded_pool_stage1.assert_no_stem_collision` |
| embeddings | `calibration/trial_pool_unit_gemini.embed_cached` (fetch), `layer_bc_arms._load_cached` (cache-only read, abort on miss) |
| turn-mode clustering + rescue_centroid | `calibration/clustering_bench.py` machinery (constants: min_cluster_size 16, merge 0.97, seed 42; rescue p25 rule) |
| adjudication loop + guards | `calibration/adjudication_ab.py` (sequential accepted-list, centroid-cosine representatives, content-hash checkpoint, per-row `served_model`, failed-is-failed, own artifact path per arm) — driver precedent `ops/run_adjudication_ab.py` |
| cohesion-vs-null instrument (G-R1) | the fragment-finding's test (mean pairwise cosine vs 200 size-matched draws, pass = >p95); run identically on new map AND `clean2_base` |
| account map | `flag_proper_noun_clusters.account_map` both dirs → `expanded_pool_stage1.merge_account_maps` → one `layer_b_arms.collapse_sibling_domains` |
| blinded reads | `calibration/playbook_snap_trial.py` / `scenario_playbook_trial.py` patterns (sealed KEY, committed judgments, NEG validity bar, duplicate-reader guard, counterbalanced sides) |
| playbook PV pipeline | `scenario_playbook_trial.py` (selection, synthesis, PB0) + `playbook_snap_trial.py` (snap, counterbalanced read, scoring) rebound to the new map, new `pbv_*` paths |
| chat transport | `trial_gateway.GatewayClient.chat_json`, model pinned `gemini-3.5-flash-lite`, `no_cache=True` on EVERY call, `max_retries=1` + harness-counted attempts (the snap-trial budget discipline) |

## 3. HOUSE RULES (all held through three trials today; non-negotiable)

Frozen gates — three veto audits fired today, zero gates adjusted after results.
Subagents ONE AT A TIME; blinded readers + outcome audits on sonnet, code audits may
use the strong model. Unexpected gate/placebo result → veto-audit code AND output
before believing it. ZERO Postgres writes; `recordings/`, `recordings_pull_keep/`
read-only; never overwrite a published artifact (`clean2_*`, `pb_*`, `pbs_*`,
`layer_bc_*` all frozen); new artifacts carry started_at/pid/seed/shas and refuse to
clobber. Long stages via `ops/run_visible.ps1` (`-ScriptArgs` is ONE string) + a
completion ping, never poll — **its logs are UTF-16: pipe through
`iconv -f UTF-16LE -t UTF-8` before grepping a ping condition.** Gateway needs the
Joveo VPN (symptom when off: DNS resolves, TCP times out). pytest file-by-file (spaCy
OOM). Never batch the embedding endpoint; concurrency only. UMAP is
non-reproducible across launches — seed 42 is the one frozen base, no seed shopping.
A null is a real result.

## 4. WHAT THIS SESSION LEFT ON DISK (2026-08-18)

| | |
| --- | --- |
| validated playbook method | specs + RESULTS: `2026-08-18-scenario-playbook-trial-design.md`, `2026-08-18-playbook-snap-trial-design.md`; harnesses `calibration/scenario_playbook_trial.py` (36 tests), `calibration/playbook_snap_trial.py` (14 tests) |
| validated documents | `artifacts/pbs_playbooks.json` (5 real playbooks — the product shape) |
| trial artifacts | `pb_*` (pilot incl. flip veto audit), `pbs_*` (snap trial) — all frozen |
| the rebuild spec (THIS handoff's job) | `docs/superpowers/specs/2026-08-18-union-taxonomy-rebuild-design.md` |
| narratives | `PROBLEMS_AND_FIXES.md` (two new sections), `docs/findings/scenario-playbook-trial.md`, INDEX row |
| prior handoffs (history) | `HANDOFF_PLAYBOOK_TRIAL_...` → `HANDOFF_PLAYBOOK_RESULT_...` → `HANDOFF_PLAYBOOK_VALIDATED_...` → this file |

## 5. THE ASK

(1) Build + test the rebuild harnesses. (2) Blind-audit each, fix, record in spec §9.
(3) Run stages A→E in order, visible windows + pings, gates evaluated as frozen.
(4) At any gate failure: stop, veto-audit if unexpected, report to the operator with
the fallback options (base-clustering arm vs closing). (5) Fill spec §10, update P&F +
findings + INDEX, leave a fresh handoff. The operator is limits-conscious: sequence
agents, sonnet for readers, and respect the three budget lines in §0 — ask before
crossing any of them.
