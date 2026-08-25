# HANDOFF — Layer C backfilled to 33/34; the binding constraint is now CRITERION GRADABILITY

Supersedes `HANDOFF_LAYER_C_BACKFILL_2026-08-20.md` (its plan was executed) and
`HANDOFF_LAYER_C_SHIPPED_2026-08-19.md`. Full record:
`docs/findings/layer-c-playbook-schema-and-gateway.md` §9-§11. Narrative:
`PROBLEMS_AND_FIXES.md`. Production facts: **`Brain/CLAUDE.md`**. Traps: `docs/GOTCHAS.md`.
Specs: `2026-08-19-playbook-schema-design.md`, `2026-08-20-quote-floor-ab-design.md`.

**Spend: 153 chat calls** across seven runs, plus a ~15-call probe in flight at handoff time.
Zero published artifacts overwritten.

## 0. STATE (settled; do not re-derive)

1. **Layer A live** — 259 scenarios, 34 coachable. **Layer B COMPLETE** — 12,444 `kb_pairs`,
   both Pinecone namespaces at 12,444 in `narens-brain-3072`, `SHIP LAYER B COMPLETE` printed.
2. **`tuning.yaml` describes the live system** (`pool_unit: turn`, `merge_cosine_threshold:
   0.97`, `embedding.backend: gateway`), verified by `calibration/config_reproduces_live.py`
   reproducing live routing on 12,444/12,444 pairs from config alone, no shim.
3. **LAYER C: 33 of 34 scenarios have a live playbook.** 60 rows — 33 live, 5 placebo, 22
   trial. `contract_and_legal_review` is the only gap (snap collapsed at 2 moves, floor 3).
4. **The licensed synthesis config** is `gemini-3.6-flash`, `reasoning=medium`,
   `MIN_EVIDENCE_PER_MOVE=3`, hardened `_REQUIRE`, quote-relevance rule. **The MODEL was the
   lever** — identical instruction, flash-lite 11% vs 3.6-flash 77%.
5. **What is live is 73% usable, not 95%.** A 5-doc probe said 95%; 28 documents said 73%.
   The original 5 are the worst at 63%.

## 1. THE BINDING CONSTRAINT: ~HALF THE CRITERIA CANNOT BE GRADED

Layer D scores real calls against these moves. That is impossible for a criterion phrased as
an effect on the listener:

| gradable | NOT gradable |
| --- | --- |
| "state an SLA turnaround number" | "clearly explain business impact" |
| "name the fee and pass-through spend separately" | "ensure media plans are as scientific" |
| "give a numeric radius constraint" | "demonstrate operational relief" |

**A gradability rule was added to both prompt stages on 2026-08-20** (bans evaluative
adjectives, demands a concrete artifact/number/structure, drops moves that cannot be expressed
that way). **The documents in Postgres PREDATE it.**

**A 5-document probe of that rule was RUNNING when this was written** —
`calibration/quote_floor_ab.py --model gemini-3.6-flash --reasoning medium --tag grad`,
artifacts `pbq_36flash_medium_grad_*`, log `logs/pbq_grad.log`.

**How to judge it — and do NOT judge it on a quality percentage.** The probe overestimates
(§11.3). Read the criteria and ask one question: do they name something present or absent in a
transcript, or do they use an adjective? That is visible by inspection.

**If the criteria changed shape:** re-run all 34 at ~3 calls each (~102), then reload. **If
not:** the fix is not a prompt and the next lever is the schema (§3.2).

## 2. RE-RUNNING WHAT IS LIVE — one real obstacle

The 5 originals are from the old config and re-running them means replacing production content.
**`idx_playbooks_one_live` will REFUSE a second live playbook for the same scenario**, and a
new artifact filename produces new rows rather than updating old ones (the conflict key is
`(scenario_key, arm, source_artifact)`). So the incumbents must be demoted to `superseded`
first. That is a deliberate step, not an overwrite — design it, do not discover it.

## 3. NEXT, in dependency order

1. **Finish the gradability probe and decide** (§1). Cheapest high-value item.
2. **The three thin documents are weak and should probably not be `live`.** 16-21 pairs, PB1
   11%, 22% single-account moves, and `uber.com` appears in 8 of their 9 moves. They are live
   now on the operator's instruction ("all usable, for testing"). Demoting them to `trial` is
   a status flip.
3. **`contract_and_legal_review` has no playbook** and its evidence (25 pairs) could not
   support 3 moves. More evidence or permanent exclusion — not a retry.
4. **The schema gap (§11.4), if Layer D needs it.** Objection branches, decision rules as
   policy, a canonical "good version" phrase per move. **This is a schema change, and evidence
   that contains no objection cannot yield an objection branch without fabricating one** — the
   exact thing PB0 exists to prevent. Design before building.
5. **Layer D's own C0-C4 gates have never run** (that work landed concurrently and is not
   mine). It can now reach 33 scenarios instead of 5 — but see §1 before trusting its scores.

## 4. OPEN DECISIONS

- Re-run the 5 originals (63% usable) against the new config? Needs §2's demotion step.
- Demote the 3 thin documents to `trial`?
- Retire **PB1 as a gate**? It is a proxy; the blind read is the better instrument, and PB1
  now punishes the relevance rule for dropping unevidenced moves. A candidate replacement that
  is not arbitrary: **single-account moves ≤10%** (backfill: 7%; original 5: 15%).
- The 22 `trial` documents (11 UNRESOLVED `r1`, 11 `concat`) — read, promote, or leave parked.
- The 84 orphaned `signal_recognition_gaps` rows pointing at dead scenario keys.
- **`ship_union_taxonomy.py`'s single-transaction guarantee is false** (found 2026-08-19, not
  fixed): its connection is not autocommit but `upsert_scenario` commits, so the first of 259
  upserts commits the children-first DELETEs. The dated snapshot schema is the real safety net.
  Fix before the next taxonomy replacement.

## 5. HOUSE RULES + TRAPS FROM THIS SESSION

Frozen gates pre-registered before code; ONE blind code audit per harness before it spends;
subagents ONE AT A TIME (readers/outcome audits on sonnet); `no_cache=True` on every chat call;
never batch the embedding endpoint; VPN for the gateway; long runs via `ops/run_visible.ps1`
with an **explicit `-Log`**; logs are UTF-16, `iconv -f UTF-16LE` before grepping; pytest
file-by-file; never overwrite a published artifact; **a null is a real result**; at any gate
failure STOP and bring fallback options.

**Traps that bit, all now in `docs/GOTCHAS.md`:**

- **An error message quoting a limit is not a property of the system.** `Timeout passed=15.0`
  was recorded as a gateway-wide cap; `gemini-3.6-flash` then ran 60s, 70s and 152s requests
  with zero failures. It was one model's route. The wrong note would have ruled out the
  configuration that passed every gate.
- **`ATTEMPTS_PER_CALL` nests.** An outer schema-retry loop around a `call()` that retries
  internally is 3x3, not 3. Only the ceiling bounds real spend.
- **A gate verifies fidelity to the artifact you NAME.** 22 pre-snap documents loaded with all
  seven gates green, because "did you point at the right file" is selection, not fidelity.
  `assert_snapped()` closes it.
- **One constant cannot mean two things.** `EXPECTED_COUNTS` served as both the raw artifact
  count and the post-exclusion loaded count; G-P3 failed on its author. Split.
- **Do not edit a module a running process has imported** — execution is unaffected but the
  traceback renders old line numbers against new file text.
- **The Bash tool's cwd resets between calls.** Use absolute paths.
- Heredocs through the Bash tool can break on quoting and write nothing while appearing to run.

## 6. MACHINERY (reuse, do not re-implement)

- `calibration/playbook_backfill.py` — synthesis for scenarios lacking a playbook.
  `--band thin|rest`, dry-run default, own `pbf_*` prefix, **writes nothing to Postgres**,
  cache-only selection with a bounded top-up.
- `calibration/quote_floor_ab.py` — the paired A/B rig. **Every (model, effort, tag) writes its
  OWN artifact set**, so runs never overwrite each other. Reuses frozen evidence, so the arms
  are paired; G-Q5 proves it by finding every old citation in the new pool.
- `calibration/playbook_backfill_scope.py` — free scoping (pairs, accounts, bands).
- `ops/load_playbooks.py` — the loader. Seven gates, idempotent, `assert_snapped()`, and it
  excludes `schema_collapsed` documents automatically.
- `calibration/config_reproduces_live.py`, `gateway_backend_check.py`,
  `gemini_cosine_bands.py`, `sink_margin_delta_identity.py` — zero-spend verifiers.
- **The blind-read protocol is the best quality instrument available** and costs no chat calls:
  build a counterbalanced packet with opaque document ids, hold the key back, have a subagent
  bucket every quote SUPPORTS/WEAK/FAILS. Reproducible to ~3pt between independent runs. See
  `calibration/pbq_read_packet.py`.
