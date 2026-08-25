# Layer C shipped (playbook schema) + the gateway embedding backend — 2026-08-19

[Back to the findings index](INDEX.md) · Spec:
`docs/superpowers/specs/2026-08-19-playbook-schema-design.md` · Handoff:
`Brain/HANDOFF_SHIP_LAYER_AB_2026-08-19.md`

Zero chat spend. Zero embedding spend. Zero published artifacts overwritten.

---

## 1. LAYER C IS SHIPPED — but at 5 scenarios, not 34

`db/schema.sql` had no playbook table, so the validated documents had nowhere to land and
Layer C was *validated but unshippable*. It now has one, and all 32 existing documents are
loaded.

**What is actually in production: 5 playbooks.** They cover 5 of the 34 coachable scenarios —
the pilot set that passed PB0 5/5 and PB2 4/5 pooled 11–4. **The other 29 coachable scenarios
have no playbook.** Shipping the schema did not create coverage; it created the place coverage
can land. The scale-up is still ~130 chat calls (≈3.9/document, ~1 in 6 needing a retry, plus
a tail too shallow for the 3-move floor that no retry budget rescues).

| status | rows | what it is |
| --- | --- | --- |
| `live` | 5 | the validated documents — the ONLY production content |
| `placebo` | 5 | placebo twins, never servable |
| `trial` | 22 | routing-A/B documents; the 11 `r1` ones are UNRESOLVED and were not shipped |

**The design decisions, both taken by the operator before code:**

1. **`scenario_id` is a NOT NULL FK to `scenarios`, exactly like `rubrics`.** A playbook is an
   output of one taxonomy and dies with it; the JSON artifacts on disk are the archive. The
   consequence is load-bearing and is why `playbooks` now sits in
   `ship_union_taxonomy.py`'s children-first `DELETE_ORDER` — every FK is ON DELETE NO ACTION,
   so omitting it would make the NEXT taxonomy replacement fail partway through.
2. **JSONB blobs with positional move ids**, following the `rubrics` precedent that already
   survived Layer D wiring. `move_id` is `M1..Mn` BY ARRAY POSITION, assigned by the loader and
   never taken from the model — the same rule as `milestone_id` and coverage-area ids, for the
   same reason: a model-chosen id lets a re-synthesis silently repoint a person's accumulated
   history at different criteria. **`key_moves` order is therefore load-bearing.**

**Safety property worth stating plainly:** placebo twins and UNRESOLVED trial documents live in
the same table as production content and are indistinguishable without the `status` filter.
`storage.get_playbook_for_scenario` defaults to `status='live'` for exactly that reason, and
"at most one live playbook per scenario" is enforced by a **partial unique index**, not by
application code — proven by attempting the violation for real:

```
[PROVEN] duplicate key value violates unique constraint "idx_playbooks_one_live"
```

All seven pre-registered gates passed (G-P1 FK satisfiability, G-P2 round-trip incl.
`scenario_id`, G-P3 exact counts, G-P4 one-live, G-P5 positional ids, G-P6 idempotence,
G-P7 delete-chain).

## 2. `sink_margin_delta` IS NO LONGER INERT

The knob existed in `flat_pick` and `tuning.yaml` while `v1.layer_b.assign_scenarios` carried
its own inline copy of the pick rule and never called it — production read the value and then
ignored it. **Same failure class as the retired `ego_trap/settings.py` and the inert
`layer_a.min_content_words`: a configured value that reads as authoritative while doing
nothing.**

Wired, after proving the substitution is a no-op at the shipped value **against real data
rather than synthetic vectors**: `calibration/sink_margin_delta_identity.py` compares the
inline rule against `flat_pick(delta=0.0)` over all 12,444 live pairs — real scenario rows with
their real `is_coachable` flags, real trigger text, real cached vectors — on the FULL ordered
`scenario_keys` list, not just top-1.

> **IDENTICAL on 12444/12444 pairs.**

**The value stays 0.0.** Wiring the knob and choosing its value are different acts; only the
first is done. Setting it non-zero still needs a judged sample larger than the 80 turns that
exist. Four new tests pin the wiring so it cannot silently go inert again, including a tripwire
asserting the shipped value is still a no-op.

## 3. THE `gateway` EMBEDDING BACKEND

`preprocessing/embedder.py` now has a third backend. The transport moved from
`calibration/trial_gateway.py` to **`shared/gateway.py`**, and calibration re-exports it —
the direction the house rule requires (nothing in `v1/`/`v2/`/`shared/`/`preprocessing/` may
import `calibration/`; now enforced by a test that AST-parses every production module).

**Why it exists.** `backend: gemini` routes to Google AI Studio at ~1k/day; the gateway is a
different transport with a different cache under a different key scheme, and **every vector
for this corpus was paid into the gateway's file**. Selecting `gemini` would re-buy ~25k
vectors against a cache holding none of them.

Verified against live data (`calibration/gateway_backend_check.py`): 300 real triggers served
**300/300 from cache with the transport monkeypatched to raise**, so a single miss fails the
check instead of quietly spending.

**Two defects this verification caught that review had not:**

- **Keying on the REQUESTED width would have re-bought the corpus.** The gateway cache is
  keyed on the model's NATIVE 3072 — which is why calibration can re-analyse at 768 for free.
  My first implementation put the requested width in the key, so `gemini_dimensions: 768`
  would have missed all ~196k rows and re-embedded everything at 140 req/min. Caught by a unit
  test before it could run.
- **Production and calibration disagreed by 2.98e-08.** Traced to normalisation: the
  calibration shim renormalises on every read, and a stored float32 vector's norm is
  ~0.99999994, not 1.0. **The residual difference is irreducible** — 85 of 300 rows still
  differ in the last float32 bit, in both directions, because the shim normalises a whole
  (n, 3072) matrix while the cache normalises single rows, so numpy blocks its pairwise
  summation differently. Same class as the CUDA reduction-order nondeterminism already
  recorded for bge. The check asserts a float32 tolerance plus cosine 1.0, not equality.

`tuning.yaml` stayed on `local` when this was written, and was **switched to `gateway` later
the same day** as part of the config-reality repair — see §8.

## 4. THE bge-FITTED COSINE FLOORS ARE INVERTED IN GEMINI SPACE — FLAGGED, NOT RE-TUNED

Measured over all 12,444 live pairs against `union_base` in gemini-embedding-2@3072
(`calibration/gemini_cosine_bands.py`, zero spend):

| trigger-vs-scenario best match | p10 | p25 | p50 | p75 | p90 |
| --- | --- | --- | --- | --- | --- |
| **bge@768** (what the floors were fitted to) | 0.496 | — | 0.550 | — | 0.613 |
| **gemini@3072** (the live space) | 0.653 | 0.670 | 0.690 | 0.710 | 0.729 |

The whole distribution moved up ~0.14, and this **inverts** `sink_rescue_trigger_weak_floor`.
It was set to 0.65 in round 2 specifically to sit *comfortably above* bge's p90 so the
`t_sims[best] < floor` test would catch nearly every pair. In gemini space 0.65 sits *below
p10*, so the same comparison now catches almost none. **The number did not change; the
distribution underneath it did.**

**Not re-tuned, deliberately.** Nothing is live (`sink_rescue_strategy: none`), and this key's
own history is the argument against a quick fix — round 2 already moved it by percentile and
that is recorded as insufficient. It needs the labelled sample `tuning.yaml` has demanded since
the key was written. `sink_rescue_relative_margin` (relative) and `sink_rescue_blend_alpha`
(a weight) are unaffected by the band shift.

**The response-side band could not be measured**: 6,672 of 12,398 distinct responses were not
yet cached when this ran. Re-run the script once the paced fetch finishes.

### A measurement trap worth internalising

The first run of that script reported a trigger p50 of **0.065** at "dim 768" — because
`build_scenario_vecs` fell through to the live `local` backend while the triggers came from the
gemini cache, so it measured a cosine band **across two different embedding spaces**. It
produced a clean-looking table and only the absurd magnitude gave it away. This is the hazard
`CLAUDE.md` names as the biggest live one, and it bites measurement scripts silently. The
script now installs the shim before building any vector AND asserts the resulting width.

## 5. THE BLIND CODE AUDIT EARNED ITS KEEP

Nine findings on the playbook harness before it wrote anything; two would have fired on the
first `--apply`:

- **The loader created its table via `db/init_db.py`, which opens its own connection from the
  raw URL** — skipping the `hostaddr` workaround for a resolver that REFUSES `*.neon.tech`. It
  would have died at schema creation *after* printing three PASS lines, reading like partial
  success.
- **Adding `playbooks` to `SNAPSHOT_TABLES` made `ship_union_taxonomy.py` unrunnable** on any
  database lacking the table, because it counts rows *before* the dry-run guard. Combined with
  the first finding this was a deadlock: the migration tool needed the table, and the loader
  that creates it could not run.
- Also: G-P6 was narrated rather than enforced (and produced no verdict at all on a first
  load); G-P4 passed vacuously at zero live rows; `verify()` never read back `scenario_id`;
  and `get_playbook_for_scenario`'s bare `LIMIT 1` could return the UNRESOLVED `r1` arm at
  `status='trial'`, where the `rubrics` precedent it copied is safe only because
  `rubrics.scenario_id` is UNIQUE.

One finding was recorded and NOT fixed, as out of scope: **`ship_union_taxonomy.py`'s "deletes
and the load run in ONE transaction" guarantee is already false** — its connection is not
autocommit but `storage.upsert_scenario` ends with `conn.commit()`, so the first of the 259
upserts commits the children-first DELETEs and the later `rollback()` cannot restore anything.
The dated snapshot schema, not the transaction, is the real safety net. Escalated to the
operator.

## 6. Methodology notes that recur

- **A gate that cannot fail is not a gate.** Three of the nine findings were this shape:
  vacuous at zero rows, narrated instead of asserted, or checking that an index *exists*
  rather than that it *enforces*. The one-live rule was only believed after attempting the
  violation and being refused by name.
- **Prove a "no-op" refactor against real rows, not synthetic ones.** The 400 randomized
  synthetic cases were already there and were not sufficient evidence to wire the knob into
  the primary path; 12,444 real pairs were.
- **Verify a cache claim with the transport disabled.** "Everything is already cached" is
  cheap to assert and cheap to check — but only if a miss is made to fail loudly rather than
  silently spend.

## 7. A SECOND gateway limit, found at 7,200 of 7,472 vectors

The paced response fetch hard-failed with **272 vectors left**, on a limit this project had not
seen:

```
HTTP 429 ... "Limit type: max_parallel_requests. Current limit: 8, Remaining: 0."
```

**This is not the 150-requests-per-window cap already recorded.** That one is a RATE ceiling;
this is a CONCURRENCY ceiling — how many requests may be in flight simultaneously. The
module-level token bucket added on 2026-08-19 morning governs how often a request *starts* and
says nothing about how many are *outstanding*, so it cannot prevent this.

`ops/ship_layer_b.py` hardcoded `embed_cached(..., 8)` — **exactly the ceiling**. The fetch
therefore ran permanently at the limit with zero headroom, and because a retry is itself a
request, any slot the gateway had not finished releasing rejected the next one. It survived 70
minutes at ~1.7 req/s before losing all four retries inside a single window.

**Fixed in the transport, not at the call site.** `shared/gateway.py` now holds a module-level
`threading.Semaphore(EMBED_MAX_PARALLEL)`, default **6**, across the entire `_post` including
its retries — releasing it before a retry would let another request start while this one is
still logically alive. Module level for the same reason as the rate limiter: the limit is per
API KEY, so two clients in one process must share one counter. Clamping in the transport is what
makes it real, because every calibration script written before today passes `workers=20` and
none of them can be trusted to change.

**A concurrency 429 also needs the opposite backoff from a quota 429**, which is why they are
now classified separately. A quota rejection wants a window-length wait and a shared penalty. A
concurrency rejection clears the instant a sibling finishes, so it gets a short *jittered* wait
and deliberately does NOT penalise the bucket — slowing the whole job down does not create a free
parallel slot, and releasing every worker on the same schedule just reproduces the collision that
caused it.

Nothing was lost: `embed_cached` commits every 400 vectors, so the resume had 7,200 already
cached.

### The traceback lied, and it was my fault

The crash printed, as the failing line inside `_post`:

```
"embed_batched output is positionally correct either way",
```

— a line from a completely different function. `calibration/trial_gateway.py` had been rewritten
at 21:54 while that process, started at 21:34, had it imported. **The edit did not change the
running code** (Python had already compiled the module into memory; the module was imported
before the edit, and step 5 began at ~21:47). But a traceback re-reads the file from disk to
render source lines, so the line NUMBERS came from the old file and the TEXT from the new one.

Harmless to execution, actively misleading to debugging, and worth the rule now in
`docs/GOTCHAS.md`: if a traceback's source line makes no sense for the function it claims to be
in, check whether the file changed after the process started, and trust the exception message
over the rendered source.

## 8. THE CONFIG DESCRIBED A DIFFERENT SYSTEM FROM THE ONE IN PRODUCTION

Found by asking a plain question — "turn mode is already live in the main pipeline, right?" —
and checking instead of answering from memory. It was not.

`tuning.yaml` and the live database disagreed on **three** of the values that determine what
Layer A builds:

| key | `tuning.yaml` said | the live `union_base` taxonomy actually used |
| --- | --- | --- |
| `layer_a.pool_unit` | `clause` | **`turn`** (`union_pool_fetch.py`: "clusters the UNION corpus in turn mode") |
| `layer_a.merge_cosine_threshold` | `0.85` | **`0.97`** (the artifact's own `identity.merge`) |
| `embedding.backend` | `local` (bge@768) | **gemini-embedding-2@3072 via the gateway** |

Three knobs that agreed (`min_call_support_fraction` 0.02, `min_call_support_floor` 4,
`ubiquity_ceiling` 0.6) made the divergence easy to miss.

**This was destructive, not cosmetic.** Layer A *upserts* scenarios. So `python main.py` would
have pooled a different unit, merged it at a floor calibrated for the other unit, in the wrong
embedding space, and written the result over the live 259-scenario taxonomy — with every
downstream artifact still keyed to the old one. Nothing was protecting against it except the
fact that nobody had run it.

The three are not independent, which is what makes it a single defect rather than three: the
file's own comment on `pool_unit` states that flipping it **invalidates
`merge_cosine_threshold`**, because turn-level cosines sit in a different band and a floor must
never be borrowed across bands. The rebuild honoured that (0.97, not 0.85) and clustered in
gemini space. The config honoured none of it.

**Repaired by moving the config to reality, not the other way round.** 0.97 is not a fresh
calibration or a guess — it is the value recorded in
`artifacts/adjudication_ab_union_base.json`'s `identity.merge`. The clause-mode measurement
grid is retained above the key as history, explicitly marked as no longer applicable.

### A latent bug the change surfaced before it could fire

`shared/pinecone_store.init_index` derived its dimension as:

```python
dimension = emb.gemini_dimensions if emb.backend == "gemini" else 768
```

An **allow-list of hosted backends, which fails OPEN**. The new `gateway` name is not
`"gemini"`, so it took the `else` branch and would have created a **768-dim index for
3072-dim vectors** — and a Pinecone index's dimension is IMMUTABLE, so that is a new index to
create, not a value to correct. Now inverted to ask whether the backend is the LOCAL one, so
any future backend inherits the right answer by default.

### Verified end to end, with the transport disabled

`calibration/config_reproduces_live.py` runs production `assign_scenarios` driven **only by
`tuning.yaml`** — deliberately *without* `install_embedder_shim`, because the entire point is
to exercise the path a real run takes; if it passed only with the shim, production would still
be misconfigured and the shim would be hiding it.

> **IDENTICAL on 12,444/12,444 pairs**, sink share 47.5% (the live ship recorded 47.5%; G-R2
> measured 47.3%/48.1%), gateway transport monkeypatched to raise so a cache miss fails
> instead of spending.

### What the repair does NOT fix

`embedding.backend` is **global**, so it reaches past Layer A/B:

- **Layer B is safe and proven.** Its live knobs are *relative* — `relative_margin` and
  `sink_margin_delta` rank against a trigger's own best match, which is scale-invariant — and
  the 12,444-pair reproduction above is the proof, not an argument.
- **Layer B's absolute floors** (`sink_rescue_*`) are inverted in this space (§4). Inert:
  `sink_rescue_strategy: none`.
- **Layer C and Layer D thresholds are now UNCALIBRATED** and must not be trusted until
  re-derived. Tolerable only because both layers are dark — `rubrics`, `gap_events` and
  `milestone_performance` are all empty. **This is a real debt, not a resolved item.**

### Two tests changed, and both changes are the interesting part

- `test_pool_unit_is_present_and_ships_clause` **failed, which is the tripwire working.** It
  existed precisely so this value could not move as a side effect. Re-pinned rather than
  deleted — to `turn` AND `0.97` asserted together, since shipping one without the other is
  the incoherent state.
- `test_skips_when_reconciliation_gate_fails` **silently inverted.** Its fixture hardcoded
  `sim=0.90` as a value that fails the gate — true only while the threshold was 0.85. At 0.97
  the same fixture PASSES the gate, so the test stopped testing the skip path and failed
  downstream on an unrelated `None`. Now derived as `threshold + 0.005`, the same way
  `test_layer_b_assignment`'s near-tie fixture is expressed as a relationship to
  `relative_margin`. **A fixture that hardcodes a number on one side of a tuning knob is a
  test that silently changes meaning when the knob moves.**

## 9. PB1 WAS UNREACHABLE BY ARITHMETIC, NOT FAILED ON QUALITY (2026-08-20)

Reported as "PB1 fails 0/11, that is a property of the method". It was not.

- Prompt: `"evidence" with 2-4 entries` per move. PB1: `min(3, accounts_available)` = always 3
  distinct accounts. **A 2-quote move cannot cite 3 accounts**, and **59/66 moves (89%) carried
  exactly 2 quotes**. The gate contradicted the schema it graded.
- `select_evidence` was never the problem: it delivers **18–33 distinct accounts** per document.
- The model already maximised spread subject to quote count: **50/59** two-quote moves cite 2
  distinct accounts, **5/7** three-quote moves cite 3.
- Genuine narrowness is **9/66 moves (14%)** on a single account — not "nearly every move".

**Fix:** `MIN_EVIDENCE_PER_MOVE = 3`, prompt floor raised to 3-4 entries, `_PREFER`/`_REQUIRE`
reconciled, `pb1_doc` reports `quotes`/`need`. A capped-`need` variant was tried and **reverted**
— capping by the move's own quote count makes a 2-quote move pass by lowering the bar to meet it.

**Constraint on any future tightening:** a stronger v1 diversity rule already backfired — models
satisfied distinctness by dropping to ONE entry, causing 9 consecutive reduce rejects. Diversity
must never outrank the entry-count rule.

**Lesson:** a gate can be unmeetable by construction and still look like a quality verdict. Check
that a bar is reachable before believing a 0% pass rate — and that the harness's own drift
tripwire (`pv_reduce_rules`) is what caught the incoherent prompt edit, not review.

## 10. THE 3-QUOTE FLOOR WORKS AND DOES NOT FIX PB1 — NULL, 15 calls (2026-08-20)

Spec: `docs/superpowers/specs/2026-08-20-quote-floor-ab-design.md`. Harness:
`calibration/quote_floor_ab.py`. Artifacts: `pbq_*`. Paired A/B, 5 live scenarios
re-synthesized on the OLD arm's own 50-pair selections (G-Q5 proved the pairing by finding
every OLD citation inside the pool handed to the NEW arm).

| | OLD (2-entry floor) | NEW (3-entry floor + hardened) |
| --- | --- | --- |
| quotes ≥3 per move | 35% | **100% (19/19)** |
| PB1 per-move | 2/20 = **10%** | 2/19 = **11%** |
| single-account moves | 3/20 | **5/19** |
| PB0 | 5/5 | **5/5** |
| moves per doc | 4,4,5,4,3 | 3,4,4,4,4 |

**G-Q4 PASS, G-Q2 PASS, G-Q3 PASS, G-Q1 FAIL (11% vs a 70% bar). Backfill blocked.**

**The intervention did exactly what it said and did not produce the effect it was for.** The
model complies with the entry floor perfectly — every move now carries 3 quotes — but the third
quote comes from an account it had already cited. Single-account moves got WORSE, 3/20 → 5/19.
An explicit "MUST come from at least 3 DISTINCT accounts" instruction did not override it.

**Two mechanisms ruled out, both free:**
- **Selection** is not the constraint: pools carry 19–33 distinct accounts.
- **Batching** is not the constraint: the selection is near-perfectly interleaved (1–3 adjacent
  same-account pairs out of 49), and each 25-pair map batch sees 13–19 distinct accounts.

**What is left is the likeliest explanation and it is uncomfortable for PB1 itself:** a move
specific enough to be actionable tends to be *demonstrated in depth by one or two clients*.
Account breadth and move specificity may be in genuine tension at move granularity, in which
case PB1-per-move is measuring the wrong unit rather than catching a defect. Note the
document-level span clause already runs 0.58–0.86, i.e. breadth exists ACROSS a document
even when it does not exist WITHIN a move.

**Cost of learning this: 15 chat calls, against ~90 it prevented from being spent on the
assumption that the floor change worked.** That is what the probe was for.

### 10b. RESOLVED — the constraint was the MODEL, and a config now PASSES every gate

The null above held the model fixed at `gemini-3.5-flash-lite`. Re-running the same paired A/B
across two more arms found the actual lever. Identical evidence, identical prompt, identical
gates throughout:

| arm | PB1 per-move | single-account moves | quotes >=3 | PB0 |
| --- | --- | --- | --- | --- |
| OLD shipped (flash-lite, 2-entry) | 2/20 = **10%** | 3/20 | 35% | 5/5 |
| flash-lite, low, 3-entry | 2/19 = **11%** | 5/19 | 100% | 5/5 |
| **3.6-flash, low**, 3-entry | 11/19 = **58%** | 1/19 | 95% | 5/5 |
| **3.6-flash, MEDIUM**, 3-entry | **17/22 = 77%** | **0/22** | 100% | 5/5 |

**ALL GATES PASS on the last arm** (G-Q1 77% vs a 70% bar, G-Q2 5/5, G-Q3 no collapse, G-Q4
100%). Monotonic across the ladder, and single-account moves — the "one client's quirk" risk
this whole thread was about — reach **ZERO**.

**THE INSTRUCTION WAS NEVER THE PROBLEM; COMPLIANCE WAS.** "MUST come from at least 3 DISTINCT
accounts" is byte-identical in the flash-lite and 3.6-flash arms. flash-lite ignores it
(11%); 3.6-flash follows it (58% at low, 77% at medium). Three diagnoses were wrong before
this one: `select_evidence` (pools already carry 19-33 accounts), batching (already
interleaved), and the quote floor (took perfectly at 100% and moved PB1 by one point).

**Cost of the whole investigation: 50 chat calls.** It changed the backfill config from one
that would have produced 29 documents at ~11% PB1 to one producing them at ~77%.

**Caveats that must travel with this.** n=5 scenarios / 22 moves. The passing arm differs from
the OLD arm in FOUR ways at once (model, reasoning effort, entry floor, hardened wording), so
it licenses a configuration, not an attribution. PB1 is an evidence-breadth check, not a
quality judgement — no human has read these documents, and the blinded-read instrument remains
the binding constraint on any quality claim.

**Backfill config this licenses:** `gemini-3.6-flash`, `reasoning_effort=medium`,
`MIN_EVIDENCE_PER_MOVE=3`, hardened `_REQUIRE`. Budget ~87 calls minimum for 29 documents, and
note medium runs at a **60.8s median** per call, so ~90 minutes of wall clock.

**Open for the operator:** keep the 3-entry floor (better-evidenced moves, PB0 unaffected) or
revert it (single-account concentration is slightly worse)? And is PB1-per-move the right unit
at all, or should breadth be judged per document?

## 11. THE BACKFILL — 33 of 34 scenarios live, and what a blind read says they are worth

Harness: `calibration/playbook_backfill.py` (`pbf_*` artifacts). Config licensed by §10b:
`gemini-3.6-flash`, `reasoning=medium`, `MIN_EVIDENCE_PER_MOVE=3`, hardened `_REQUIRE`, plus
a quote-relevance rule added after §10b (see below).

### 11.1 The relevance rule — 0 failing quotes, at the cost of PB1

Before the backfill, one more prompt change: *"a quote must DEMONSTRATE the move, not react to
it"*, with the failure taxonomy spelled out (bare acknowledgement, greeting, question the CSM
asked, garbled fragment, announcement of intent) and *"DROP the move rather than keep it on
weak evidence."* Measured on the same 5 scenarios, blind, against the arm without it:

| | quotes | SUPPORTS | WEAK | FAILS | usable |
| --- | --- | --- | --- | --- | --- |
| 3.6-medium, no rule | 74 | 62 | 7 | 5 (6.8%) | 84% |
| **3.6-medium + rule** | 59 | 56 | 3 | **0** | **95%** |

It also cut moves 22 → 18 and PB1 77% → 67%, **which is the rule working**: the model dropped
moves it could not evidence, and the moves it dropped were disproportionately PB1-passers. Two
metrics pulling opposite ways, and only one of them measures what a reader gets.

**A precedence conflict I created, visible in the data.** `_REQUIRE` says entry-count outranks
diversity ("repeating an account rather than dropping below 3"); the new rule says discard weak
quotes. When a move's third account offers only a weak quote, the only way to satisfy both is
to repeat a good account — which is exactly what all six PB1 failures look like
(`uber`x2 + `scale`, `touchmark`x2 + `charter`). **You cannot have "3 quotes, 3 accounts, all
demonstrative" when the third account has nothing demonstrative to say.**

### 11.2 Sequencing on evidence volume — the thin band first

The A/B was measured only on scenarios with 104-771 routed pairs. Three of the 29 have 16-21.
Run first, deliberately, for 6 calls:

| band | docs | moves | PB1 per-move | single-account moves |
| --- | --- | --- | --- | --- |
| 50-pair (full) | 20 | 77 | **75%** | **4%** |
| <50-pair (partial) | 5 | 17 | 41% | 24% |
| thin (16-21 pairs) | 3 | 9 | 11% | 22% |

**Evidence volume is the sole driver of breadth, and the degradation is monotonic.** Not a
prompt problem and not a model problem: `geographic_targeting_and_location_mapping` has THREE
accounts in its entire pool, and `uber.com` appears in 8 of the thin band's 9 moves. Those
conversations only ever happened with a couple of clients. No prompt fixes absent evidence.

The real cut point is ~35 pairs, not the 50 the bands were drawn at:
`market_insights_and_competitive_intelligence` at 39 pairs scored a clean 3/3.

**One collapse:** `contract_and_legal_review` (25 pairs) produced 2 moves against a floor of 3.
The pre-registered exclusion rule fired; it is the one scenario with no playbook.

**Cost: 76 calls for 26 documents, zero failed attempts, 68 minutes**, exactly the estimate.

### 11.3 THE BLIND READ OF ALL 28 — the probe overestimated badly

| | quotes | SUPPORTS | WEAK | FAILS | usable |
| --- | --- | --- | --- | --- | --- |
| probe, 5 docs | 59 | 56 | 3 | 0 | **95%** |
| **backfill, 28 docs** | 334 | 245 | 68 | **21 (6.3%)** | **73%** |
| the original 5, for reference | 43 | 27 | 10 | 6 (14%) | **63%** |

**A 22-point gap between a 5-document probe and 28 documents of the same config** — far beyond
the ~3pt calibration noise measured between two independent audits of the same arm. The config
is genuinely better than what shipped (73% vs 63%), and the probe's 95% was small-sample luck.
**Do not let a good probe promise a rate again; a probe can establish that something CHANGED,
not what the rate will be.**

> **RETRACTION, 2026-08-24 — read this before citing any number in the table above.** The
> "~3pt calibration noise" this section leans on is WRONG, and with it the interpretation of the
> 22-point gap. The same 59 relevance-arm quotes later scored **95% in one audit and 78% in
> another**, and the same 123 live criteria scored **84% then 17%** under two reader framings
> (which also inverted the cohort ranking). So a blind-read `usable%` is not comparable across
> packets at all, and **part of the 95%→73% gap is the instrument, not the sample size.** The
> direction is probably still right — 28 documents will regress from 5 — but 22 points was never
> a measurement. Only within-packet counterbalanced contrasts are valid. See §13 and
> `docs/GOTCHAS.md`.

### 11.4 The two findings that matter more than the percentages

**Roughly half the criteria cannot be graded from a transcript**, which is fatal for Layer D's
entire purpose — it scores real calls against these moves. The line is sharp:

| gradable | not gradable |
| --- | --- |
| "state an SLA turnaround number" | "clearly explain business impact" |
| "name the fee and pass-through spend separately" | "ensure media plans are as scientific" |
| "give a numeric radius constraint" | "demonstrate operational relief and proactive partnership value" |

Gradable criteria name **a specific artifact, number, or structure**; ungradable ones use an
evaluative adjective describing an **effect on the listener**. You cannot score "was it clear?"

**They teach what an expert said once, not a procedure.** Missing across all 28: objection
branches (what to say when the client pushes back), decision rules stated as policy rather than
as one call's anecdotal number, and a canonical "good version" of the utterance separate from
transcript noise. So gap feedback often cannot tell a CSM what doing it right sounds like.
**That is a schema change, not a prompt change** — and evidence that does not contain an
objection cannot be made to yield an objection branch without fabricating one.

**Most common quote defect:** citing a question the CSM ASKED as proof they did something
(6 of 21 failures). The prompt already forbade it; those turns open declaratively and then ask,
so the model does not classify them as questions.

### 11.5 A deterministic question filter was measured and REJECTED

Tempting, and wrong: 28 of the 334 quotes end in "?" but only **4** are failures. The rest are
statements with a tag — *"Additional dollars should lead to incremental applications. Right,
and…"*. **14% precision; it would delete 24 good quotes to catch 4.** Same verdict the earlier
regex sweep reached on the old corpus. The failures are semantic, not lexical, and no pattern
match reaches them. The only mechanical rules that survive scrutiny are ack-share >= 0.35 and
content-words < 12, together worth about 1 quote in 60.

### 11.6 State

**33 of 34 coachable scenarios have a live playbook** (5 original + 25 backfill + 3 thin);
`contract_and_legal_review` is excluded by the collapse rule. Loaded by
`ops/load_playbooks.py --apply`, all seven gates green, 60 rows total (33 live / 5 placebo /
22 trial).

**G-P3 caught a bug in the loader on the way in**, worth recording because it is the class of
error gates exist for: `EXPECTED_COUNTS` was used for BOTH the raw artifact count (26) and the
post-write DB count (25, after the collapse exclusion). One constant, two meanings. The write
had already succeeded; the verification refused to call it good. Split into `EXPECTED_LOADED`.

**Session cost: 153 chat calls** across seven runs.

## 12. THE GRADABILITY RULE WORKS — AND INSTRUCTION LOAD IS NOW THE PATTERN (2026-08-20)

Probe: `pbq_36flash_medium_grad_*`, 5 scenarios, same frozen evidence, 15 calls.

**It did exactly what it was asked.** Criteria carrying a banned evaluative adjective:

| arm | criteria | banned adjective | naming something concrete |
| --- | --- | --- | --- |
| OLD live | 20 | 3 (15%) | 35% |
| backfill (no grad rule) | 96 | 20 (21%) | 16% |
| **+ gradability rule** | 18 | **0 (0%)** | **67%** |

They read as gradable: *"State a specific alternative integration or tracking mechanism"*,
*"Request downstream candidate status data (shortlist, interview, or hire counts)"*.

**AND IT DEGRADED THE TWO RULES BEFORE IT. G-Q1 FAIL (56%), G-Q4 FAIL (83%).**

| arm | PB1 per-move | quotes >=3 | usable quotes |
| --- | --- | --- | --- |
| 3.6-medium | 77% | 100% | 84% |
| + relevance rule | 67% | 100% | **95%** |
| + gradability rule | **56%** | **83%** | not measured |

**THIS IS THE PATTERN, AND IT IS THE MOST TRANSFERABLE THING LEARNED TODAY.** Every rule added
to this prompt bought its own objective and spent one of the others:

- 3-entry floor → 100% compliance, PB1 +1pt (the floor was never the constraint)
- account diversity → PB1 77%, but only on a model that follows instructions
- relevance rule → failing quotes to ZERO, and PB1 77%→67% (dropped unevidenced moves)
- gradability rule → adjectives to ZERO, and PB1 67%→56%, entry floor 100%→83%

Four constraints — 3 quotes, 3 accounts, all demonstrative, all gradable — that the evidence
cannot always satisfy at once. The model is not disobeying; it is triaging, and each new
instruction shifts what it sacrifices. **Adding a fifth rule should be assumed to cost a
sixth thing, and the cost measured rather than hoped away.**

**Consequence for the pre-registered gates:** G-Q1 and G-Q4 both now fail on the arm with the
best criteria. Holding them would reject the only config that produces gradable criteria —
the property Layer D actually requires. This is the second time a frozen gate has rejected an
improvement (see §11.1). The gates were frozen when PB1 was believed to be the quality
measure; it is not.

**NOT DECIDED HERE.** The 26 were NOT re-run against this config. What is live remains the
non-gradable set.

## 13. THE GRADABILITY ARM IS SHIPPED, AND THE QUALITY INSTRUMENT IS NOT WHAT WE THOUGHT (2026-08-24)

Zero chat calls spent. Everything below came from artifacts already on disk, free verifiers, and
blind reads.

### 13.1 State re-established before anything was touched

All three free verifiers re-run green: `config_reproduces_live.py` (**12,444/12,444** pairs
identical, sink share 47.5%), `gateway_backend_check.py` (300/300 from cache with the transport
DISABLED, 204,366 vectors), `playbook_backfill_scope.py` (33 live, `contract_and_legal_review`
the only gap). Postgres agreed: 60 rows, 33 live / 5 placebo / 22 trial.

**Two premises in the handoff were WRONG, and checking cost nothing:**

1. **The ~15-call re-run of the 5 originals had ALREADY BEEN PAID FOR.** Three arms of it were
   sitting in `artifacts/` — `pbq_36flash_medium_*`, `*_relev_*`, `*_grad_*` — all 5 scenarios,
   all snapped, none collapsed. The `grad` artifact is stamped `2026-08-24T00:01:54`: it is the
   probe the handoff described as "in flight", and it completed.
2. **The "236 labelled quotes that now exist" DO NOT EXIST** in reusable form. Only aggregate
   counts survive in this file; the per-quote SUPPORTS/WEAK/FAILS labels lived in a conversation
   and were never persisted. Nothing in the tree contains them. Any judge-validation plan must
   budget a fresh labelling pass. **Persist per-item labels, not just the aggregate** — the new
   harnesses below both do.

### 13.2 THE INSTRUMENT FAILED ITS OWN REPRODUCIBILITY CHECK — the most important result here

Measured from two independent directions on the same day:

| what varied | population | result |
| --- | --- | --- |
| reader framing (lenient vs strict) | the SAME 123 live criteria | **84% then 17% gradable** |
| packet composition | the SAME 59 relevance-arm quotes | **95% then 78% usable** |

The framing pair also **inverted the cohort ranking**: original-5 came out WORST under the
lenient framing (60% vs backfill 89%) and BEST under the strict one (35% vs backfill 14%).

**So usable%/gradable% is a property of the instrument, not of the documents**, and the
"reproducible to ~3pt" note on record is retracted (it rested on a single 81%/84% pair). Only
**within-packet, counterbalanced, one-reader contrasts** are valid. §11.3's headline
95%-to-73% "the probe overestimates" conclusion is partly instrument, not sample size — see the
retraction inline there.

**Why the two framings disagreed so violently — two real defects pulling opposite ways:**

- **evaluative vagueness** — "clearly explain the business impact" has no concrete anchor.
- **bundling** — "name the exact tracking columns AND walk through drop-off analysis" is two
  demands in one criterion.

The lenient reader rewarded concrete nouns, so long rich criteria won. The strict reader
penalised compound demands, so the same criteria lost. **The gradability rule turns out to
improve BOTH** (§13.3), which is why it was not the trade §12 assumed.

Layer D's shipped `checks` arm asks a strictly binary `performed: true/false` per move
(`partial` is produced only by `pairwise`), and requires a verbatim quote. So bundling there does
not cause grader disagreement — it causes **HIT INFLATION**, because the grader anchors its
mandatory quote on the easiest clause. Different defect, same cause, and unmeasured.

### 13.3 THE ONLY CLEAN COMPARISON: gradability beats relevance, within one packet

Same packet, counterbalanced, one reader — the only methodologically valid contrast available:

| arm | quotes | SUPPORTS | WEAK | FAILS | usable |
| --- | --- | --- | --- | --- | --- |
| + relevance rule | 59 | 46 | 12 | 1 | 78% |
| **+ gradability rule** | 56 | 50 | 6 | **0** | **89%** |

**Gradability won 4 of 5 situations.** So it is NOT a trade against quote quality: narrower
criteria made the quotes FIT BETTER. The mechanism the reader gave: the relevance arm writes
compound criteria bundling two or three actions, so a quote satisfying one clause reads WEAK.
The gradability rule forced criteria phrased closer to what the evidence actually says.

**This is the counter-example to §12's "every rule costs a sixth thing".** The pattern is real
but not universal — a rule that narrows scope can pay for itself.

### 13.4 PB1 RETIRED, G-Q4 DEMOTED, and a replacement gate that a small n can answer

**PB1 is no longer a gate** (operator decision). It had rejected a real improvement twice
(§11.1, §12). Replaced by **single-account moves <= 10%**, which on the 123-move census flagged
exactly the cohorts the qualitative read already distrusted (original-5 15%, thin-3 22%) and
passed the one it did not (backfill 7%).

**G-Q4 (quotes>=3 at >=90%) demoted to diagnostic — the THIRD instance of the same pattern.** It
is a treatment-verification check ("did the floor take?"), and it did its job: 100% on the medium
and relevance arms. But the relevance and gradability rules both instruct the model to DROP weak
evidence, so on those arms G-Q4 measures the intended behaviour and calls it failure. **These
gates count evidence entries; the rules that improve quality remove weak ones.**

**A rate bar needs enough n to be evaluable.** The 10% ceiling was calibrated on 123 moves
(0.8pp resolution). A 5-document probe carries ~18 moves, where the achievable values are 0%,
5.6%, 11.1% — so "11% vs a 10% bar" is one move, not a distinction. The bar was **not** lowered
(that is the capped-need anti-pattern §9 reverted). Instead **G-Q7** was added: a replacement
must be no worse than the incumbent it supersedes. Relative questions survive small n; absolute
ones do not. The two verdicts are reported SEPARATELY so a census-scale failure cannot be
laundered by a relative pass.

| arm | G-Q1 (<=10%) | G-Q2 PB0 | G-Q3 | G-Q7 vs incumbent | PB1 *(diag)* | G-Q4 *(diag)* |
| --- | --- | --- | --- | --- | --- | --- |
| medium (licensed) | PASS 0% | 5/5 | PASS | PASS 0% vs 15% | 77% | 100% |
| + relevance | PASS 6% | 5/5 | PASS | PASS 6% vs 15% | 67% | 100% |
| **+ gradability** | **FAIL 11%** | 5/5 | PASS | **PASS 11% vs 15%** | 56% | 83% |

### 13.5 SHIPPED: the gradability arm replaced the original 5

`ARTIFACT_PLAN` flipped `pbv_playbooks_snapped.json`'s `real` arm to `superseded` and added
`pbq_36flash_medium_grad_snapped.json` as `live`. **The demotion is DECLARATIVE** —
`upsert_playbook` is `ON CONFLICT ... DO UPDATE SET status = EXCLUDED.status` — so no
hand-written UPDATE was needed. **Plan ORDER is load-bearing**: the demoting entry must precede
its replacement or `idx_playbooks_one_live` refuses the write. Pinned by a test.

All seven gates green. 65 rows: **33 live / 22 trial / 5 placebo / 5 superseded**. Coverage
unchanged at 33 of 34 — a one-for-one swap, also pinned by a test.

Production improved on every measurable axis (independent census, not the loader's own report):

| | before | after |
| --- | --- | --- |
| banned adjectives, that cohort | 15% | **0%** |
| single-account, ALL LIVE | 10% | **9%** (now inside the ceiling) |
| quotes>=3, ALL LIVE | 82% | **93%** |
| PB1, ALL LIVE *(diagnostic)* | 55% | 63% |

### 13.6 Two latent bugs fixed, one found by the fix

**`ops/ship_union_taxonomy.py`'s single-transaction guarantee was false and is now true.**
`storage.upsert_scenario` ended in `conn.commit()`, so the first of 259 upserts committed step
2's children-first DELETEs; the post-load `conn.rollback()` was then a no-op that still printed
"rolled back". Fixed with a keyword-only `commit: bool = True` (the default preserves all 15
call sites) and `commit=False` at the one site that needs it. Four tests plus a source tripwire.
**`storage.upsert_playbook` has the same per-row commit** — far less dangerous (the loader
deletes nothing and is idempotent) but recorded, not fixed.

**A hardcoded status list hid 5 documents from the dry run.** The plan printed
`for status in ("live", "placebo", "trial")`, so the promotion's `superseded` rows produced a
summary totalling 60 under a "PLAN 65 documents" header. Every gate passed — the bug was in the
display, i.e. in the thing a human approves. Now iterates the statuses present and asserts the
summary accounts for every document. See `docs/GOTCHAS.md`.

### 13.7 Housekeeping

**Four permanently-red tests fixed** in `test_playbook_storage.py`. All stale expectations, zero
data problems: `EXPECTED_TOTAL == 32`, "only the five validated documents are live", and — the
irony — the last place still committing the "one constant, two meanings" conflation §11.6 fixed
in the loader (comparing post-exclusion counts to raw `EXPECTED_COUNTS`). Also replaced "no
artifact contains a collapsed document" with the invariant that matters: collapsed documents may
exist on disk (that null result is deliberately kept) but must never reach the load plan.
**Full suite: 69 files, 1,501 tests, zero failures.**

**New harnesses, both zero-spend and both persisting per-item labels:**
`calibration/playbook_gradability_census.py` (census over every live criterion: deterministic
banned-adjective floor, single-account/PB1 rates by cohort, and `--packet` to build a blind
packet with the key withheld) and `calibration/pbg_score_blind_read.py` (joins a read back to
the key, REFUSES a partial read, and prints the A-vs-B confusion so the deterministic scan stays
honest about being a floor).

### 13.8 What is NOT resolved

- **A taxonomy-wide rollout of the gradability config is NOT licensed.** It fails G-Q1 at census
  scale. Only the 5 promoted documents are licensed.
- **`contract_and_legal_review` still has no playbook** (25 pairs, collapsed at 2 moves). Corpus
  work, not a retry.
- **The 3 thin documents remain live** on the operator's instruction, at 22% single-account with
  `uber.com` in 8 of their 9 moves.
- **Bundling in the 94 backfill moves is unmeasured**, and under Layer D's binary `checks` arm it
  inflates hits rather than causing disagreement. An atomicity rule ("one criterion = one
  checkable demand") is the obvious next probe and has never been run.
- **The judge (problem #5) needs a fresh labelling pass first** — see §13.1.
- **Layer D's C-gates have still never run.** It is the only instrument that measures whether
  these criteria yield signal on real calls, and it is zero-spend in `--report-only`.
