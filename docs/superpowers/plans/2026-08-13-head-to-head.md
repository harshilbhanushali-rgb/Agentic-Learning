# Head-to-head comparison — Implementation Plan

> **For agentic workers:** implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Every task states its own verification. **No task marked `PAID` may start until every `FREE` task
> before it is verified green.**

**Spec:** `docs/superpowers/specs/2026-08-13-head-to-head-comparison-design.md`. The spec is the
authority on *what is measured and why*; this plan is only *how it gets built*. Where they appear to
disagree, the spec wins and this file is wrong.

**Goal:** replace criteria-based scoring with a direct pairwise comparison — for a client moment,
is the CSM's response better or worse than the expert's real response to the nearest comparable
moment? A useless judge lands at 50%, so the bar is arithmetic rather than arguable.

**Already done, not to be rebuilt:** `calibration/probe_retrieval_gate.py` and
`artifacts/retrieval_gate.json`. Retrieval cleared its gate (0.812 clean vs a 0.631 base, 95% CI on
the lift [+0.168, +0.196]; same-scenario 11× chance). Its pure helpers are already unit-verified.

---

## Milestone ordering, and what may run in parallel

```text
M1 helpers+prompt (FREE) ──┐
                           ├──> M2 W0 moment set (FREE) ──> M3 smoke (~20 calls)
                           │                                     │
                           │            ┌────────────────────────┤
                           │            v            v           v
                           │        M4a C2       M4b C3      M4c C4     (PAID, ~40 each)
                           │            └────────────┴───────────┘
                           │                         v
                           └────────────────> M5 controls verdict (FREE)
                                                     v
                                            M6 W3 headline (PAID, ~120)
```

- **M4a / M4b / M4c are the only genuinely parallel paid work.** They read one frozen artifact and
  write three separate ones.
- Default execution is **sequential**. Splitting across sessions requires one API key per concurrent
  stream (tokens bind first — 34.66K/30K TPM was measured while requests sat at 6/100).
- **M5 is a hard gate.** If any control fails, M6 does not run; the finding is the failed control.

---

## M1 · Pure helpers and the prompt (FREE, no DB, no network)

Everything here is testable without Gemma or Postgres, the same split
`shared/cluster_evidence.py` and `shared/topic_grouping.py` already follow.

- [ ] **T1.1 — `shared/head_to_head.py`, swap-batch assignment.**
  `assign_swap_batches(item_ids, batch_size, seed) -> list[list[tuple[item_id, order]]]`.
  Each item appears exactly twice, once as order `AB` and once as `BA`.
  **The two orders of one item must never land in the same batch.** A judge shown the same pair
  twice in one call is consistent from memory, and C1 would report that memory as reliability.
  *Verify:* property test over 200 random `(n, batch_size, seed)` combinations asserting every item
  appears exactly twice, once per order, and no batch contains both orders of any item.

- [ ] **T1.2 — order-averaging and win rates.**
  `order_average(ab_verdict, ba_verdict) -> "A" | "B" | "tie"` — disagreement between the two orders
  is a **tie**, not a coin flip.
  `win_rate(outcomes) -> {rate, n_decisive, tie_share}` — ties excluded from the denominator and
  their share returned alongside, never dropped silently.
  *Verify:* hand-built cases including all-tie (rate must be `None`/NaN, not 0.0), unanimous, and
  a 50/50 split.

- [ ] **T1.3 — C1 agreement.**
  `swap_agreement(pairs) -> {agreement, n_scored, both_tie_share}`. Measured over items where **at
  least one** order was decisive; items both orders called a tie are excluded and reported.
  *Verify:* an all-flip set scores 0.0; an all-consistent set scores 1.0; a both-tie set is excluded
  rather than counted as agreement.

- [ ] **T1.4 — C2 pair selection.**
  `adjacent_rank_pairs(sims_row, tolerance=0.01) -> (idx_hi, idx_lo) | None` — two neighbours at
  adjacent ranks whose cosines differ by ≤ tolerance, so neither has a fit advantage.
  *Verify:* returns `None` when no adjacent pair is within tolerance; picks the tightest when several
  qualify.

- [ ] **T1.5 — stratifiers.**
  `by_decile(outcomes, values)` for the retrieval-cosine strata, and
  `length_matched(items, band=0.25)` selecting items with `|log(len_a/len_b)| <= band`.
  *Verify:* a synthetic set where the win rate is engineered to differ between strata is recovered.

- [ ] **T1.6 — `moments_sha(moments) -> str`.** Stable content hash over the frozen moment set:
  sorted, field-explicit, insensitive to dict ordering.
  *Verify:* reordering the list or the keys does not change the hash; changing any trigger or
  response text does.

- [ ] **T1.7 — `PROMPT_HEAD_TO_HEAD_BATCH` in `shared/prompts.py`.**
  - Responses labelled **"Response 1" / "Response 2"** only. No names, no roles, no hint which is
    the expert. Blinding is the whole instrument.
  - **One trigger shown**, the query moment's. Naren's own trigger is never shown (spec §2.1).
  - **An explicit verdict on every item.** Never "return the ones that…". This is the generalising
    lesson from the objective function's failure: its prompt instructed sparsity, and "return a
    subset" invites picking a top few and stopping.
  - Output per item: `{"item_id", "winner": "1"|"2"|"tie", "reason"}`.
  - **No instruction telling the judge to ignore length.** Three wording passes have failed in this
    repo; length is handled by the length-matched stratum in T1.5, not by asking nicely.

**M1 gate:** `..\.venv\Scripts\pytest tests/test_head_to_head.py -v` green. Run tests
**file-by-file** — four test files each load spaCy's 392 MiB contiguous table and the suite is
unreliable in one process on 16 GB Windows.

---

## M2 · W0 — build and freeze the moment set (FREE)

`calibration/trial_head_to_head.py --stage w0`. Read-only via `_connect_read_only`
(`SET SESSION default_transaction_read_only = on`, verified, not promised).

- [ ] **T2.1 — parse all 106 `csm_recordings/` transcripts** via `ego_trap/transcript_parser.py`,
  resolving roles through `mapping.csv` + `JOVEO_SPEAKER_NAMES`.
  **Report every speaker that resolved to CLIENT and is not in `mapping.csv`.** The list fails OPEN —
  an unlisted Joveo colleague becomes the CLIENT and invents coaching signals from internal chatter;
  14 were caught on the first 106-call pull. Print them; do not silently proceed.

- [ ] **T2.2 — client-turn filter.** Apply `v1/layer_b._is_substantive` to every client turn, so the
  CSM side admits nothing the expert side structurally cannot (spec §2.1).

- [ ] **T2.3 — selection.** Embed surviving turns with `embed_query_matrix`; match against
  **scenario vectors over the FULL map, sinks included**; reject any turn whose best match is a
  sink, via `relative_match.is_sink_flags`. Report the rejection rate — Layer D measured 60.7% and a
  wildly different figure means the port is wrong, not that the corpus differs.

- [ ] **T2.4 — CSM response window** via `rubric_lookup.extract_csm_response_window`.
  Known defect, bounded not fixed: it sometimes captures scheduling chatter instead of the answer.
  Persist 30 random windows for the §8 read (T2.8).

- [ ] **T2.5 — retrieval.** Match each surviving turn against **`kb_pairs` trigger vectors
  restricted to coachable-filed pairs**. Keep top-1 plus ranks 2–5 (C2 needs adjacent ranks; W3 needs
  only top-1). Apply the floor **p10 = 0.630** from §4's measured band — and record every item's
  cosine so higher floors are recoverable by stratification without a re-run.

- [ ] **T2.6 — re-measure §4's metrics cross-corpus.** Same two metrics, same bootstrap, now
  CSM→Naren instead of Naren→Naren. **This is stopping condition #1**: if the lift's 95% CI includes
  zero, stop here and spend nothing.

- [ ] **T2.7 — freeze.** Write `artifacts/h2h_moments.json` including `moments_sha`, the embedding
  backend (`local_bge`, pinned explicitly — **never read from `tuning.yaml`'s `embedding.backend`**,
  which the parallel embedder work may change under us), and the sample composition.

- [ ] **T2.8 — READ THE SAMPLES.** 20 retrieved pairs verbatim: are these the same *kind* of moment?
  30 CSM response windows: how many are scheduling chatter? Report the mis-extraction rate as the
  headline's stated contamination bound. Non-negotiable — a passing aggregate does not substitute.

**M2 gate:** T2.6's CI excludes zero, and T2.8 has actually been read by a human.

---

## M3 · Smoke test (~20 calls)

- [ ] **T3.1 — `--stage smoke`**: 2 items through **every** stage (C2, C3, C4, W3), both orders,
  real Gemma, real parsing, real artifact write.

`py_compile` catches neither a missing import nor a positional slice over a reordered tuple, and two
launches on 2026-08-13 died mid-generation on exactly those. Add the AST check that every
`v2.layer_c`-style imported name actually resolves.

**M3 gate:** all four stages produce a parseable artifact. No exceptions, no empty verdict lists.

---

## M4 · The three controls (PAID, ~40 calls each) — parallelisable

Each stage reads `h2h_moments.json`, **asserts `moments_sha` matches**, and refuses to run on a
mismatch. Without that assert, two sessions judge different moment sets and their results cannot be
combined — the same defect as `arm0_baseline` being scored against a different clustering run than
the arms compared to it.

Each writes its own artifact and its own log. **Flush after every batch** — one prior run completed
all 95 LLM calls and lost every result because a free DB lookup gated the persistence of expensive
work. Persist **raw judge output**, not only derived rates.

- [ ] **T4a — C2, expert vs expert.** `--stage c2` → `artifacts/h2h_control_c2.json`.
  Two Naren responses at adjacent ranks within cosine 0.01 (T1.4). **Bar: the higher-ranked
  neighbour's win rate within [0.40, 0.60].**
- [ ] **T4b — C3, sensitivity.** `--stage c3` → `artifacts/h2h_control_c3.json`.
  Matched response vs one from a **deranged unrelated scenario** — reuse `score_naren_ceiling.derange`
  with `merge_cosine_threshold`, **inherited**, so no `tuning.yaml` key is added.
  **Bar: matched wins ≥ 0.75.**
- [ ] **T4c — C4, transplant penalty.** `--stage c4` → `artifacts/h2h_control_c4.json`.
  Naren's real response to T vs a retrieved neighbour of his own, **his whole call held out**
  (`hold_out`, call-level — row-level would leave a near-duplicate sibling in the pool).
  **Reported; ≥ 0.75 native is fatal.**

---

## M5 · Controls verdict (FREE) — the gate

- [ ] **T5.1 — pool C1 across all three control artifacts.** C1 costs nothing extra because every
  control judges both orders. It is finalised only once all three exist.
- [ ] **T5.2 — evaluate every stopping condition in spec §9** and print an explicit PASS/FAIL per
  control, with the tie share beside every rate.
- [ ] **T5.3 — READ 20 items where the two orders disagreed.** A judge flipping on layout should look
  incoherent there; one flipping on genuine ties should not.

**M5 gate — M6 runs only if all four hold:**

| | bar |
|---|---|
| C1 agreement | ≥ 0.75 |
| C2 higher-ranked win rate | within [0.40, 0.60] |
| C3 matched win rate | ≥ 0.75 |
| C4 native win rate | < 0.75 |

A failure here means the **instrument is broken, not underpowered**. More data rescues none of them,
and none may be retried with a reworded prompt — that is how a result gets tuned into existence, and
it has already failed three times in this codebase.

---

## M6 · W3 — the headline (PAID, ~120 calls)

- [ ] **T6.1 — sample 300 moments, seeded and stratified.** **Never `--limit N`** — an alphabetical
  prefix returned every subject-matter scenario and not one client-posture scenario, and four arm
  comparisons ran that way before it was noticed. Print composition in the header; shout if a stratum
  is empty. If W0 yielded materially fewer than 300, shrink and **say so** rather than sample with
  replacement.
- [ ] **T6.2 — judge both orders**, disjoint batches, batch size 5.
- [ ] **T6.3 — report the headline with all four corrections attached**: overall win rate + tie
  share; stratified by retrieval-cosine decile; the length-matched subset; raw position-1 win rate;
  C1 re-measured on these items; and the C4 transplant penalty stated beside the number, since the
  headline is uninterpretable without it.

**M6 gate:** if the headline sits inside C1's noise band, report the band. Do not pick a winner.

---

## Verification summary

- [ ] Pure helpers tested **before** any spend (M1).
- [ ] `--load PATH` replays every artifact at zero cost, so every number is re-derivable and a
  changed criterion does not cost the budget twice.
- [ ] Read-only enforcement asserted at Postgres level in every stage.
- [ ] `tuning.yaml` **unchanged** — every threshold is inherited, measured, or harness-local.
- [ ] No Layer D table touched; `ops/clear_ego_trap_data.py` is **not** required and this cannot
  corrupt a Layer D baseline.
- [ ] Tests run file-by-file.

## Cost

| | calls |
|---|---|
| M3 smoke | ~20 |
| M4a / M4b / M4c | ~40 each |
| M6 headline | ~120 |
| **total** | **~260** |

Against the four-arm trial's ~1,090.

## Command reference

neon.tech DNS is REFUSED on this network while TCP 5432 works, so DB-touching stages need the
`hostaddr` bypass. `-ScriptArgs` is **one string** — `-File` does not preserve array syntax.

```powershell
.\ops\run_visible.ps1 -Script calibration/trial_head_to_head.py -HostAddr 18.138.49.39 -ScriptArgs '--stage w0'
.\ops\run_visible.ps1 -Script calibration/trial_head_to_head.py -HostAddr 18.138.49.39 -ScriptArgs '--stage smoke'
.\ops\run_visible.ps1 -Script calibration/trial_head_to_head.py -HostAddr 18.138.49.39 -ScriptArgs '--stage c2'
```

`--load` needs no DB and therefore no bypass.
