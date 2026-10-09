# HANDOFF — Layer D redesign BUILT, zero spend, gates not yet run (2026-08-20)

Sequenced after `HANDOFF_LAYER_C_SHIPPED_2026-08-19.md` (its item 3, "decide whether Layer D
gets rebuilt against playbooks", is now DECIDED and BUILT). Spec:
`docs/superpowers/specs/2026-08-20-layer-d-redesign-design.md`. Production facts:
**`Brain/CLAUDE.md`** (updated). Literature grounding is summarized in the spec §3.

**Spend this session: ZERO chat calls, ZERO embeddings, ZERO Pinecone.** No DB row written
(the schema additions are files; nothing ran against Neon). Test suite green file-by-file.

## 0. WHAT WAS DECIDED (operator, 2026-08-20)

1. **Standard = live playbooks** (`key_moves`, positional M1..Mn). Rubrics stay dead.
2. **Run on what's live** (5 playbooks now); scenarios without one are coverage-gap counts.
3. **Deliverable = ranked coaching priorities** — no headline score, no severity buckets.
4. **Spend staged, gates pre-registered**, operator approves each stage.
5. **BOTH graders built**; the C2 head-to-head picks `layer_d.grader_arm`.

## 1. WHAT EXISTS NOW

**`Brain/layer_d/`** — segmentation (arms today/e), signals (memoized sink-relative admit,
fail-closed `unverified_speakers`), verify_quotes (containment + best_span ≥ 0.80),
graders (checks: binary evidence-gated, batched ≤6/request; pairwise: 3-way vs exemplar,
order-swapped, position-consistent only; 4-state verdicts; k-run majority), aggregate
(attempt-weighted cohort priors, EB shrinkage, dead-check flags, gap ranking, report text),
pipeline (checkpoint-on-success-only, naren benchmark pass, `build_reports`), prompts.

**The one mechanism to hold in your head:** the SAME instrument scores Naren's routed
kb_pairs (rater_id `'naren'`, `source_ref 'pair:<id>'`) and CSM moments (`'turn:<idx>'`).
A gap is `naren_rate − shrunken_csm_rate` per `(playbook_id, move_id)`; a check Naren
himself fails >50% is flagged as a BAD CHECK and excluded from ranking.

**Verdict vocabulary is FOUR states and `unscored` is the point** — id missing from the
response, quote failed verification, swap-inconsistent, run disagreement. Unscored never
counts as an attempt. The old pipeline turned parse failures into misses.

**DB:** `move_events` (natural unique key; verdicts JSONB) + `move_performance` (full
recompute via `storage.refresh_move_performance`, NEVER incremented). Both in
`ship_union_taxonomy.py`'s SNAPSHOT_TABLES and DELETE_ORDER (children before `playbooks`).
New storage helpers: `get_pairs_for_scenario_multilabel`, `upsert_move_event`,
`refresh_move_performance`, `get_move_rates`, `get_hit_quotes`.

**tuning.yaml layer_d additions** (rubric-era keys KEPT until ego_trap retires; both test
helpers that construct `LayerDTuning` were extended): `segmentation_arm: e`,
`grader_arm: checks` (PROVISIONAL), `grader_k_runs: 1`, `quote_verify_min_overlap: 0.80`,
`shrinkage_prior_strength: 5.0` (UNCALIBRATED), `dead_check_naren_floor: 0.50`,
`min_attempts_to_rank: 8` (UNCALIBRATED).

**Ops:** `ops/run_layer_d.py` (`--limit/--exclude/--report-only/--naren-sample/
--allow-unverified-speakers`; run_id = sha1 of the selected stems via
`pipeline.select_stems`, ONE definition; exits 2 if anything failed-and-not-checkpointed),
`ops/clear_layer_d_data.py` (deliberate wipe ONLY — re-runs are safe by construction; no
`__main__` guard, same convention as the other clears). `calibration/layer_d_bands.py` is
the C0 harness: prints the bill without `--spend`, refuses on a non-gateway backend.

**Tests:** 6 new files, 99 new tests (`test_layer_d_{verify_quotes,segmentation,aggregate,
graders,signals,pipeline}.py`), all rule-pinning with hand-built verdicts/similarities.
The AST guard (`test_no_production_module_imports_calibration`) now covers `layer_d/`.

## 2. WHAT DID NOT HAPPEN (deliberately)

- **No C-stage has run.** Every threshold is UNCALIBRATED in gemini@3072 space. Do not
  trust `ops/run_layer_d.py` output before C0→C3 pass. C2/C3 harnesses are NOT yet
  written — each needs its ONE blind code audit before it spends (house rule).
- **No client roster exists yet.** `csm_recordings/client_speakers.txt` (one verified
  client speaker per line) must be built from `ops/check_csm_speakers.py` + the Avoma
  rosters before a production run; the runner refuses without it.
- **ego_trap/ is untouched** and still owns the old tables + tuning keys. Retire it (and
  `gap_events`/`milestone_performance`/`signal_recognition_gaps` + their storage helpers +
  the rubric-era tuning keys) only after the redesign passes its gates.
- **`db/init_db.py` has not run** — the two new tables exist in schema.sql only. Remember
  the GOTCHA: running the whole schema takes ACCESS EXCLUSIVE on live tables; prefer
  creating just the two new tables over a dedicated connection.
- **Naren-side segmentation reuses kb_pairs as-is.** The known Layer B stopping-rule loss
  (6.6% pairs lost) stays bundled with the future Layer B rebuild, as previously decided.

## 3. NEXT TASKS, in dependency order

1. **Build `csm_recordings/client_speakers.txt`** (operator + `ops/check_csm_speakers.py`).
2. **C0:** `python calibration/layer_d_bands.py --spend` (VPN up; ~6.5k paced embeddings,
   cached forever; ~45 min). Read the bands + gradable-moment count. This also warms the
   cache that makes C1 free.
3. **C1:** re-run `calibration/trial_client_move_arms.py` (now cache-hit) — arm E must
   reproduce lost=0 in gemini space.
4. **Write + audit + run C2** (grader head-to-head, ~60 moments, both arms, k=3;
   pre-registered gates in spec §5). Set `grader_arm` from its verdict.
5. **Write + audit + run C3** (Naren ceiling; publishes per-check rates + dead flags).
6. **C4 reader panel**, then the first production run + item-analysis pass in its report.
7. Record everything in `docs/findings/layer-d-redesign.md` + INDEX (file does not exist
   yet — created by whoever runs the first stage).

## 4. TRAPS SPECIFIC TO THIS BUILD

- `move_id` comes from the STORED playbook JSONB (loader-assigned). Never re-derive it
  from array position at read time in new code paths — reordering `key_moves` renumbers.
- `checkpoint_layer()` encodes `{segmentation_arm}_{grader_arm}`: changing either key
  invalidates checkpoints ON PURPOSE. A re-run after a knob change regrades everything —
  which is safe (upserts) but costs chat spend. Budget accordingly.
- The pairwise arm needs an exemplar per moment; `make_exemplar_picker` embeds pair
  triggers through the production embedder — cache-hits for kb_pairs, PAID for novel
  text. The checks arm needs no exemplar and no extra embedding.
- `--report-only` calls `refresh_move_performance` (a DELETE+INSERT). Harmless on real
  data (it is a recompute) but do not point it at a DB whose move_events you just wiped
  expecting the table to survive.
