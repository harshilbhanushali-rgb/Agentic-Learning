# HANDOFF — scenario-level playbook trial (2026-08-18)

You are picking up a DECIDED direction: the operator chose to trial **scenario-level
playbooks** as the new Layer C product target. Nothing of the trial exists yet — your
job is to pre-register it, build it, gate it, and run a 5-scenario pilot. Read this
whole file before touching anything.

## 0. WHY THIS DIRECTION (the evidence you must not re-litigate)

The week of 2026-08-16/18 closed the milestone pipeline's ENTIRE internal search space —
routing, intake filtering, admission, rescue (x3), data volume, the partitioner (8 arms),
and the pooling unit — all pre-registered, all audited, all null. Then the gold-pair
probe (2026-08-18) established the two facts that pick this direction:

1. **The gemini@3072 embedding space is (very probably) NOT move-blind** — 11/11
   gold/anchor observations separate same-move from same-topic (round 2: AUC 0.966,
   p=0.0007 on 8 unanimous gold pairs; formally UNDERPOWERED vs its frozen n>=10 bar and
   reported as such). Retrieval/similarity on these vectors is sound.
2. **Same-move recurrence at clause granularity is SPARSE** — measured three independent
   ways. Milestones (clause-clusters recurring across 19+ distinct calls) demand
   recurrence the corpus does not contain. That is why the week nulled, and why stage 1
   measured "more data -> FEWER milestones" (171->128).

Read before proposing anything: `Brain/docs/findings/expanded-pool-and-clustering-bench.md`
(the whole arc), `Brain/docs/findings/layer-c-milestones-narration-and-ceiling.md`
(how V1's LLM-direct milestones failed: NARRATION, NOT CRITERIA — the failure mode this
trial's gates exist to catch), `Brain/PROBLEMS_AND_FIXES.md` (last four sections),
`Brain/HANDOFF_PIPELINE_SEARCH_CLOSED_2026-08-18.md`.

## 1. WHAT A PLAYBOOK IS

One synthesized document per scenario: **"how Naren handles <scenario>"** —
- situation signature (when a CSM is in this scenario; built from the triggers that
  route here — the machinery that benches clean),
- the ARC (how he sequences: e.g. acknowledge -> reframe -> benchmark -> concrete step),
- key moves, EACH backed by verbatim quoted evidence with call IDs and account domains,
- his actual language (signature phrases, benchmark numbers),
- pitfalls / variants by client type,
- 3-5 coarse scorable checks derivable for Layer D (descriptive in the pilot; wiring
  Layer D is OUT OF SCOPE).

The one hard authoring rule: **no claim without a verbatim quote + call citation.**

## 2. THE TRIAL SHAPE (pre-register this as a spec FIRST — the probe's no-spec mode was
a one-off operator instruction; this trial spends Gemma calls and gets a real spec in
`docs/superpowers/specs/`, gates frozen before any synthesis call runs)

- **Substrate:** the stage-1 union substrate, rebuilt exactly as
  `calibration/layer_c_pool_unit.py::build_substrate` does (production parse -> pairs ->
  routing, cache-only embeddings, F0 against `artifacts/layer_bc_xp_union.json`). Per
  scenario: routed (trigger, response) pairs + call files + the sidecar account map
  (`calibration/flag_proper_noun_clusters.account_map` over BOTH dirs, merged via
  `calibration.expanded_pool_stage1.merge_account_maps`, ONE `collapse_sibling_domains`).
- **Pilot scenarios (freeze the pick rule, not the list):** 5 scenarios spanning pool
  sizes — e.g. ranks 1, 5, 10, 15, 20 by routed-pair count among the 26. No cherry-pick
  after seeing drafts.
- **Evidence selection (free):** ~40-60 pairs per scenario via diversity sampling on the
  cached vectors (e.g. greedy max-min / MMR) + an account-diversity floor (evidence from
  >= 8 distinct account domains where the pool allows). Selection is part of the frozen
  design; record what was selected in the artifact.
- **Synthesis (the Gemma spend):** structured prompt per scenario -> the playbook.
  Expect map-reduce (evidence batches -> section drafts -> merge) if context forces it.
  **Every chat call `no_cache=True`** (documented gateway response-caching trap for
  A/B). Budget estimate: 5 scenarios x (3-6 calls + placebo twin) ~ 30-50 calls total.
- **PLACEBO TWIN (mandatory, the placebo-veto culture):** per pilot scenario, a second
  playbook synthesized identically from PERMUTED evidence — same volume/shape, evidence
  drawn from OTHER scenarios (destination-permutation precedent:
  `lcfr_common.permute_destinations`). The placebo matches what the arm ADDS (synthesis
  polish); only evidence-grounding differs.

## 3. GATES (sketch — freeze exact numbers in your spec BEFORE running)

- **PB0 — citation fidelity (mechanical, free, per playbook):** every quoted string must
  match verbatim (after whitespace normalization — define it) inside the cited call's
  routed pairs for that scenario. ONE fabricated/altered/misattributed quote = the
  playbook FAILS PB0. Run on real AND placebo twins symmetrically (placebos cite their
  permuted evidence — fidelity is about honesty of quoting, not truth of routing).
- **PB1 — evidence breadth:** each key move cites >= 3 distinct account domains; a
  playbook's full citation set spans >= 60% of the accounts available in its selected
  evidence. Below = padding-flagged (readout, define pass/fail in spec).
- **PB2 — PRIMARY, blinded discrimination read:** independent blinded readers get
  paired real-vs-placebo playbooks (same scenario, order randomized, identities sealed
  in a KEY file; judgments committed before the key opens — the
  `calibration/layer_c_bench_w4_build.py` discipline and code are the precedent, and
  `calibration/blind_read_powered.py` before it). Readers pick which is the genuine,
  usable coaching document and answer scattered attention controls. WON = real preferred
  in >= 4/5 scenarios AND per-reader validity holds (controls bar you freeze). If
  readers cannot beat the placebo, the synthesis is narration wearing citations — the
  V1 failure, caught. NULL IS A REAL RESULT.
- **PB3 — usefulness floor (secondary):** readers rate actionability per section
  (define the item and bar in the spec; keep it modest — PB2 is the decision gate).

## 4. HOUSE RULES (all re-earned this week; non-negotiable)

Pre-register gates, never adjust one after a result. One pre-run blind CODE audit of the
new harness (strong model allowed) with all findings fixed before running; **outcome
audits/vetoes and blinded readers on the SMALL model (sonnet)**; subagents ONE AT A TIME
— both are standing operator rules (see memory + §3 of the pipeline-search handoff).
Any unexpected gate/placebo result gets a veto audit of code AND output before being
believed (fired twice this week; once confirmed, once found real). ZERO Postgres writes.
Never overwrite a published artifact; new artifacts under `Brain/artifacts/` with
started_at/pid/seed/shas. Long tasks via `ops/run_visible.ps1` + a completion ping,
never poll (`-ScriptArgs` is ONE string). Gateway needs the Joveo VPN (symptom when off:
DNS resolves, TCP times out). pytest file-by-file (spaCy OOM). Embeddings via the cached
gemini path (`calibration/trial_pool_unit_gemini.embed_cached` to fetch,
`layer_bc_arms._load_cached` / the embedder shim to read); everything this trial needs
is ALREADY CACHED except nothing — chat is the only new spend. `Brain/CLAUDE.md` and
`docs/GOTCHAS.md` for the rest.

## 5. WHAT SUCCESS / FAILURE MEAN

- PB0-PB2 pass -> the METHOD is validated. Scale-up should then coordinate with the
  union-corpus TAXONOMY REBUILD (the open Layer A move: 33k-turn pool fetch + Gemma
  adjudication): G-XP1 measured new-corpus pairs sinking at 64.3%, so a rebuild will
  likely add scenarios and re-home sunk content — write the full playbook set against
  the REBUILT map if it exists, or the current 26 with a note that more scenarios are
  coming (old scenarios stay valid; new ones just mean more playbooks, no rework).
  Then derive Layer D coarse checks and bring the frontend library a real data shape.
  The pilot deliberately runs on the FROZEN 26 because it tests the method, not the
  map — method validity transfers to any scenario set.
- PB2 fails -> LLM synthesis on this corpus is narration even with citations forced;
  document it, and the honest fallback conversation is the product target itself
  (operator-level, not another harness).
- Either way: fill the spec's RESULTS, update `PROBLEMS_AND_FIXES.md`, the findings
  file + INDEX row, and leave a fresh handoff.

## 6. THE ASK

(1) Write the spec (gates frozen, pilot pick rule, placebo construction, reader
protocol, exact PB bars). (2) Build harness + tests. (3) One blind code audit, fix
findings, record in the spec. (4) Run the pilot in a visible window with pings.
(5) Score, read hard, write up, hand off. The operator is limits-conscious: sequence
agents, small model for readers/outcome checks, and ask before anything that would
expand the Gemma budget beyond the ~50-call pilot estimate.
