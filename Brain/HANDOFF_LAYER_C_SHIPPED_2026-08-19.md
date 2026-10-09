# HANDOFF — Layer C SHIPPED (5 of 34), gateway backend built, three knobs de-inerted (2026-08-19)

Supersedes `HANDOFF_SHIP_LAYER_AB_2026-08-19.md`, whose four priority items are all executed.
Full record: `docs/findings/layer-c-playbook-schema-and-gateway.md` (the finding) and
`docs/superpowers/specs/2026-08-19-playbook-schema-design.md` (§5 frozen gates, §7 the audit,
§8 the result). Incident narrative: `PROBLEMS_AND_FIXES.md`. Production facts:
**`Brain/CLAUDE.md`**. Operational traps: `docs/GOTCHAS.md`.

**Spend this session: ZERO chat calls, ZERO embeddings** (beyond the pre-existing paced fetch).
Zero published artifacts overwritten. Test suite green: **1,399 tests**, file-by-file.

## 0. STATE OF THE WORLD (settled; do not re-derive)

1. **LAYER A IS LIVE.** 259 scenarios (34 coachable + 225 sinks). Backup in schema
   `pre_union_20260819`. **ROUTING STAYS `concat`**; `keyphrases` REFUTED, `r1` UNRESOLVED and
   not shipped. Nothing here changed.
2. **LAYER B IS COMPLETE. `SHIP LAYER B COMPLETE` printed.** 12,444 `kb_pairs` (0 nulls, 0
   broken FKs, 0 duplicates, 47.54% sink) and **both** Pinecone namespaces full:
   `narens-brain-3072: total=24888 {'responses': 12444, 'triggers': 12444}`. The full-corpus
   routing verification the last handoff listed as owed was produced **three times** — every
   resume printed `matched all 12444 pairs to existing rows, 0 routing drift`. Nothing is
   outstanding here.
3. **LAYER C IS SHIPPED — AT 5 SCENARIOS, NOT 34.** The `playbooks` table exists and all 32
   documents are loaded. **Five are production content.** 29 coachable scenarios have no
   playbook. See §2.
4. **`sink_margin_delta` IS WIRED** and still `0.0`. **The bge-fitted cosine floors are
   INVERTED in gemini space** — both now measured, flagged, not re-tuned.
5. **`tuning.yaml` NOW DESCRIBES THE LIVE SYSTEM. THREE VALUES CHANGED — READ §2.5.** It
   previously described a different one, destructively: `pool_unit: clause` → **`turn`**,
   `merge_cosine_threshold: 0.85` → **`0.97`**, `embedding.backend: local` → **`gateway`**.
   Verified by reproducing the live routing on 12,444/12,444 pairs from config alone.
6. **`bloom_level`/`soft_skills` were never validated by any gate.** 24 of 259 are code-supplied
   defaults, all on sinks. Unchanged; still an open decision (§4).

## 1. THE LAYER B TAIL — FINISHED

It took three attempts and both interruptions were informative.

**Attempt 2** was killed mid-fetch at the operator's request and **the restart cost nothing** —
7,472 left to fetch versus 11,472 on the first attempt, so all 4,000 already-paid vectors came
back from the cache exactly as the docstring promised.

**Attempt 2 then DIED AT 7,200 OF 7,472 ON A LIMIT WE HAD NOT SEEN, now fixed.**

```
HTTP 429 ... "Limit type: max_parallel_requests. Current limit: 8, Remaining: 0."
```

A **concurrency** ceiling, entirely separate from the 150-requests-per-window **rate** ceiling
already in `GOTCHAS.md`. The token bucket governs how often a request starts and says nothing
about how many are in flight, so it could not prevent this — and `ship_layer_b.py` hardcoded
`embed_cached(..., 8)`, i.e. **exactly the ceiling**, leaving zero headroom for retries.

**Fixed in the transport rather than at the call site**, because every calibration script that
predates this passes `workers=20`: `shared/gateway.py` holds a module-level
`Semaphore(EMBED_MAX_PARALLEL)` (default **6**) across the whole `_post` including retries, and
a concurrency 429 is now classified separately from a quota 429 — short jittered wait, and
explicitly no `penalise()` of the shared bucket, since slowing the job down does not create a
free parallel slot. Five tests pin it. Full detail: `docs/GOTCHAS.md` and the finding §7.

**Attempt 3 completed cleanly** with the semaphore in place — 272/272 at 1.9 req/s, zero
rejections — and printed:

```text
[vectors] narens-brain-3072: total=24888 namespaces={'responses': 12444, 'triggers': 12444}
COMMITTED. calls 1106 -> 1106, kb_pairs 12444 -> 12444
SHIP LAYER B COMPLETE
```

**Should you ever need to resume it again:** `.\ops\run_visible.ps1 -Script
ops/ship_layer_b.py -ScriptArgs '--apply --resume-vectors' -HostAddr 18.138.49.39 -Log
'logs\ship_layer_b_resumeN.log'` — pass an explicit `-Log`, or the default name **clobbers
`logs/ship_layer_b.log`** via `Tee-Object`.

**Known ergonomic wart, still worth fixing:** `--resume-vectors` redoes step 4 (the
12,444-vector trigger re-upsert) on every resume, because `--vectors` offers only
`both|triggers|none`. It is free and idempotent — all trigger vectors are cached — but cost
several minutes on each of three resumes. A `--vectors responses` choice removes it.

**And a debugging trap: do not edit a module while a process has it imported.** The crash above
printed a source line from an unrelated function, because `calibration/trial_gateway.py` was
rewritten at 21:54 while a process started at 21:34 held it. Execution was unaffected (Python
had already compiled the module; the import predated the edit) but the traceback rendered old
line NUMBERS against new file TEXT. Trust the exception message over the rendered source.

## 2. LAYER C: WHAT SHIPPED, AND WHAT DID NOT

`ops/load_playbooks.py` (dry run by default) loaded 32 documents. **All seven pre-registered
gates passed**, and G-P4 was additionally proven at the database level by attempting the
violation and being refused by constraint name.

| status | rows | meaning |
| --- | --- | --- |
| `live` | **5** | the validated documents — the ONLY production content |
| `placebo` | 5 | placebo twins — NEVER servable |
| `trial` | 22 | routing A/B; the 11 `r1` documents are UNRESOLVED and were never shipped |

**Read `Brain/CLAUDE.md`'s playbook bullets before touching this table.** The four things that
matter: `status` is a safety boundary and production reads must filter `status='live'`;
one-live-per-scenario is enforced by a partial unique index, not by code; `move_id` is the array
position and `key_moves` order is load-bearing; `scenario_id` is a NOT NULL FK, so `playbooks`
is in the taxonomy delete chain and a future replacement DELETES these rows (the JSON artifacts
are the archive).

**Layer D:** `rubrics`/`gap_events`/`milestone_performance` remain empty by design. As of
2026-08-20 a Layer D REDESIGN (`Brain/layer_d/`) landed concurrently — NOT this session's work
— which scores against playbooks via `move_events`/`move_performance` keyed on `playbook_id`.
That vindicates the positional `move_id` choice, and it makes the playbook backfill upstream of
Layer D: it can only score scenarios that have a playbook, i.e. 5 of 34 today.

## 2.5 THE CONFIG-REALITY REPAIR — three values changed in `tuning.yaml`

`tuning.yaml` described a **different system** from the one in production, and because Layer A
*upserts* scenarios, running `main.py` would have overwritten the live taxonomy with it.

| key | was | now | source of the new value |
| --- | --- | --- | --- |
| `layer_a.pool_unit` | `clause` | **`turn`** | `union_pool_fetch.py`: "clusters the UNION corpus in turn mode" |
| `layer_a.merge_cosine_threshold` | `0.85` | **`0.97`** | the artifact's own `identity.merge` |
| `embedding.backend` | `local` | **`gateway`** | the corpus was paid for in gemini@3072 through the gateway |

These are one defect, not three: `tuning.yaml`'s own comment says flipping `pool_unit`
**invalidates** `merge_cosine_threshold`, because turn-level cosines sit in a different band.
The rebuild honoured that; the config honoured none of it. **No value was invented** — 0.97 is
what the live taxonomy was actually built with.

**Verified, not asserted.** `calibration/config_reproduces_live.py` runs production
`assign_scenarios` driven ONLY by `tuning.yaml`, deliberately WITHOUT `install_embedder_shim`
(if it passed only with the shim, production would still be broken and the shim would hide it),
with the gateway transport patched to raise so a miss fails instead of spending:

> **IDENTICAL on 12,444/12,444 pairs**, sink share 47.5%. Re-run it after touching these keys.

**A latent bug it surfaced first.** `pinecone_store.init_index` derived its width as
`emb.gemini_dimensions if emb.backend == "gemini" else 768` — an allow-list of hosted backends
that **fails OPEN**. `gateway` is not `"gemini"`, so it would have created a **768-dim index for
3072-dim vectors**, and Pinecone dimensions are IMMUTABLE. Now inverted to test for `local`.

**WHAT THIS DOES NOT FIX, and it is a real debt:** `embedding.backend` is GLOBAL. Layer B's
relative knobs are scale-invariant and proven unaffected, but **`layer_c` and `layer_d`
thresholds were fitted to bge bands and are now UNCALIBRATED.** Tolerable only because both
layers are dark. **Do not run Layer C or Layer D against this backend and trust the numbers.**

**Two tests moved, and both are instructive.** `test_pool_unit_is_present_and_ships_clause`
failed — the tripwire working exactly as intended — and is re-pinned to `turn` AND `0.97`
asserted together. `test_skips_when_reconciliation_gate_fails` silently INVERTED: its fixture
hardcoded `sim=0.90` as a gate-failing value, true only at threshold 0.85; at 0.97 the same
fixture passes the gate. Now derived as `threshold + 0.005`.

## 3. NEXT TASKS, in dependency order

1. **THE PLAYBOOK SCALE-UP — SCOPED AND HANDED OFF. See
   `HANDOFF_LAYER_C_BACKFILL_2026-08-20.md`**, which carries the 29-scenario list with measured
   evidence supply, the pre-registered exclusion rule, the 2-attempt cap, the 120-call ceiling,
   and the promote-or-resynthesize choice on the 6 E1 documents. Operator has approved a FULL
   backfill to 34/34; implementation and execution were deferred to a later session.
   Superseded detail below, kept for the numbers: 29 coachable scenarios have no playbook. Corrected numbers from the last handoff:
   **~3.9 calls/document (≈130 for the full set)**, ~1 in 6 documents needing a retry, and a
   tail of scenarios too shallow to reach the schema's 3-move floor that **no retry budget can
   rescue**. **Pre-register an exclusion rule and cap attempts at 2 BEFORE spending**, and get
   an explicit ceiling from the operator. The infrastructure is now ready: the loader is
   idempotent and re-runnable, so new documents land with one command.
2. **DONE — the response band is now measured** (it was blocked on the fetch). Both
   absolute floors are confirmed inverted, and there is a structural finding underneath:
   **the trigger and response bands have COLLAPSED INTO ONE on gemini** (p50 0.690 vs 0.692,
   against bge's 0.550 vs 0.635), because task_type is inert so there is no query/document
   asymmetry. Every comment in `tuning.yaml` insisting these are two different comparisons was
   true of bge and is not true now. Any sink-rescue redesign should start from that.
3. **Decide whether Layer D gets rebuilt against playbooks.** `layer_d_checks` is descriptive
   only by design, and the schema deliberately presumes nothing. This is a design question, not
   a coding one.
4. **Consider `--vectors responses`** on `ship_layer_b.py` (§1). Small, free, saves minutes on
   every future resume.

## 4. OPEN DECISIONS THE OPERATOR STILL OWES

Unchanged from the last handoff except where noted — none were decided this session, and none
were decided unilaterally.

- **E1 is built, paid for (47 calls) and UNREAD** — 22 documents, G-F 6/6 both arms. They are
  now IN THE DATABASE as `status='trial'`, so reading them no longer requires finding a file.
  Read with the tilt reported, or leave parked until the instrument is fixed? Everything
  pre-registered in the routing spec §14.1/§14.1b remains binding if read.
- **Build the read-instrument fix?** Designed in routing spec §14.7, zero chat cost, all 22
  documents reusable. **The binding constraint is still the instrument, not routing** — readers
  answered "A" on 12 of 15 votes.
- **The 24 fabricated sink `bloom_level` values** — make the column nullable and NULL them, or
  leave the defaults? Currently indistinguishable from real data.
- **Who collects >80 judged turns** so `sink_margin_delta` can be set to something. The knob is
  now live on the primary path, so a value would actually take effect — which raises the stakes
  on this slightly.
- **The rescued-map arm** (routing spec §11) — recommend CLOSING; rescue has now failed four
  times on cluster coherence, and synthesis is downstream of clustering.
- **NEW: `ship_union_taxonomy.py`'s single-transaction guarantee is false.** Found by the audit,
  recorded, NOT fixed. Its connection is not autocommit but `storage.upsert_scenario` commits,
  so the first of 259 upserts commits the children-first DELETEs and the later `rollback()`
  cannot restore anything. The dated snapshot schema is the real safety net and it works. Fixing
  it means threading `commit=False` through the storage helpers — worth its own change, and it
  should happen before the next taxonomy replacement.

## 5. HOUSE RULES (all held today)

Frozen gates pre-registered before code; **one blind CODE audit per harness before it spends**,
findings fixed and recorded in the spec; veto-audit unexpected or contested results; subagents
**ONE AT A TIME**, readers/outcome audits on sonnet, code audits may use the strong model;
`no_cache=True` on every chat call; **never batch the embedding endpoint**; VPN for the gateway;
long runs via `ops/run_visible.ps1` (`-ScriptArgs` is ONE string, and **pass `-Log` explicitly**)
in a visible window, never polled — **logs are UTF-16, `iconv -f UTF-16LE` before grepping**;
pytest file-by-file; never overwrite a published artifact; a null is a real result; **at any gate
failure stop and bring the operator fallback options.**

**Traps that bit or nearly bit today:**

- **The Bash tool's cwd reset again**, mid-session, exactly as `GOTCHAS.md` warns. `../.venv/...`
  became "No such file or directory". **Use absolute paths.**
- **A measurement script compared two embedding spaces and produced a clean-looking table.**
  `build_scenario_vecs` fell through to the live `local` backend while triggers came from the
  gemini cache; the result was a cosine band with p50=0.065. Only the absurd magnitude gave it
  away. **Install `install_embedder_shim` before building ANY vector, and assert the width.**
- **A cache keyed on the requested rather than the native vector width silently re-buys the
  corpus.** Caught by a unit test before it ran.
- **`db/init_db.py` opens its own connection from the raw URL**, bypassing the `hostaddr` DNS
  workaround. Anything unattended that needs a table should create it over its own corrected
  connection — and running the whole schema takes ACCESS EXCLUSIVE on five live tables for its
  `ADD COLUMN IF NOT EXISTS` statements (the lock is taken *before* the IF NOT EXISTS is
  evaluated), which can stall a concurrent run.
- **Heredocs through the Bash tool broke on quoting** partway through the session and wrote
  nothing while appearing to run. Verify the file changed, or write via a temp file.

## 6. MACHINERY (reuse, do not re-implement)

- `ops/load_playbooks.py` — the playbook loader. Dry run by default; seven gates re-verified
  after the write; idempotent by `ON CONFLICT (scenario_key, arm, source_artifact)`.
- `shared/storage.py` — `upsert_playbook`, `get_playbook_for_scenario` (defaults to `live`,
  raises on ambiguity), `get_playbooks`, `assign_move_ids`, `strip_move_ids`.
- `shared/gateway.py` — THE gateway transport (chat + embeddings), module-level rate limiter.
  `calibration/trial_gateway.py` re-exports it. **Never import calibration from production**;
  a test now enforces this by AST-parsing every module in `v1/v2/shared/preprocessing/ego_trap`.
- `shared/embed_cache.py` — `EmbedCache` (bge, prefix-keyed) and `GatewayVecCache` (gateway,
  native-width-keyed, prefix ignored because task_type is inert on this model).
- `calibration/sink_margin_delta_identity.py` — 12,444-pair byte-identity proof. Re-run it
  before changing anything in the pick path.
- `calibration/gateway_backend_check.py` — proves the gateway backend serves the corpus **with
  the transport disabled**, so a miss fails instead of spending.
- `calibration/gemini_cosine_bands.py` — the gemini-space cosine bands.
- `calibration/config_reproduces_live.py` — proves `tuning.yaml` AS SHIPPED reproduces the live
  Layer B routing (12,444/12,444), with NO calibration shim and the transport disabled. Run it
  after ANY change to `pool_unit`, `merge_cosine_threshold` or `embedding.backend`.
- **All four verification harnesses are zero-spend and safe to re-run.**
