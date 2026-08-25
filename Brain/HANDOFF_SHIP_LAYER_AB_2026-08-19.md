# HANDOFF — Layer A SHIPPED, Layer B shipping, Layer C blocked on schema (2026-08-19)

Supersedes `HANDOFF_UNION_MAP_SHIPPED_2026-08-18.md`, whose routing A/B was executed to
completion. Full record: `docs/superpowers/specs/2026-08-19-routing-playbook-ab-design.md`
(§12–§14 = audits and results) and `docs/findings/layer-b-routing-playbook-ab.md` (the finding).
Incident narratives: `PROBLEMS_AND_FIXES.md`. Operational traps: `docs/GOTCHAS.md`.
Production facts a session must know before touching anything: **`Brain/CLAUDE.md`**.

## 0. STATE OF THE WORLD (settled; do not re-derive)

1. **LAYER A IS LIVE IN POSTGRES.** 259 scenarios (34 coachable + 225 sinks), verified
   key-for-key against `adjudication_ab_union_base.json`; 0 empty descriptions, 0 zero-keyphrase
   rows, 0 CHECK violations. Full backup of all ten tables in schema **`pre_union_20260819`**
   (8,295 rows). Restore is a schema swap.
2. **ROUTING STAYS `concat`.** `keyphrases` is **REFUTED** (starves the map: top scenario
   771→0 routed pairs, a second also →0, coachable-routed 6,528→4,872, sink share 47.5%→60.9%;
   veto-audited by full re-derivation from raw transcripts). `r1` is **UNRESOLVED and NOT
   shipped** (3/5 topics, pooled 7–8, p=1.000; thinner documents — 41 moves/66 quotes vs the
   control's 46/84; 71% control fallback with 41% of its lookups going to sinks). **A fair test
   of membership routing does not exist on this substrate** — it needs a high-coverage clustering,
   and the only one (rescued, 64.9%) failed the coherence gate and is closed for the fourth time.
3. **THE BLINDED-READ INSTRUMENT IS THE BINDING CONSTRAINT, NOT ROUTING.** Readers answered "A"
   on 12 of 15 routing votes (80%) — pure position answering predicts the 7–8 result almost
   exactly. Plus a live move-count channel (control holds more moves on 5 of 11 topics; both
   original topics with differing counts went unanimously to the longer document) and ~1
   boilerplate move per document. Power ~28% at 11 topics / 3 readers. **A tie from this
   instrument is UNRESOLVED, never "routing does not matter."**
4. **Operator decisions taken:** Postgres writes authorised; production embeddings become
   gemini-only; `sink_margin_delta` added at a no-op; the read-instrument fix deferred; ceiling
   raised 70 → 85 → 100 (79 actually spent).
5. **`bloom_level`/`soft_skills` were never validated by any gate.** 24 of 259 are code-supplied
   defaults, all on sinks — zero coachable scenarios affected. Do not build product logic on
   these fields without measuring them.

## 1. WHERE THE SHIP GOT TO

- **`ops/ship_union_taxonomy.py` — DONE.** Snapshot-verified-then-replace. Not an upsert: only
  4 of 161 old keys overlapped the new 259.
- **`ops/ship_layer_b.py` — RUNNING when this was written.** Routed 12,444 pairs at
  **sink share 47.5%**, inside the 40–56% guard band (G-R2 measured 47.3%/48.1%), so the DB
  taxonomy, artifact and cached vectors provably agree. 1,083 calls upserted. `kb_pairs` inserting,
  then the triggers namespace, then the ~85-minute paced response tail.
  **STATE REACHED: `kb_pairs` = 12,444 (0 nulls, 0 broken FKs, 0 duplicates, 47.54% sink), all
  12,444 TRIGGER vectors in `narens-brain-3072`, and "LAYER B IS SERVICEABLE FROM HERE" printed.**
  Only the paced response fetch and the responses namespace remain.
  **HOW TO RESUME IT: `--resume-vectors`, NOT a bare re-run.** That mode skips the calls/kb_pairs
  writes, reads each `pair_id` back from the DB by `(call_id, turn_index)`, and REFUSES if any
  pair is missing or if any pair now routes differently than what is stored — which would be
  precisely the Postgres/Pinecone divergence to avoid. A bare re-run is now blocked by the
  `--replace` guard on purpose.
- **`narens-brain-3072` created.** 768-dim `narens-brain` (52,858 vectors) kept for rollback.
- **LAYER C IS DARK AND THIS IS THE NEXT REAL WORK.** `rubrics`/`gap_events`/
  `milestone_performance` were keyed to the old taxonomy and went with it, and **`db/schema.sql`
  has no playbook table**, so the 5 validated playbooks and E1's 22 documents cannot land.
  Layer C is *validated* but not *shippable*.

## 2. NEXT TASKS, in dependency order

1. **Finish/verify Layer B** (above). **RE-RUN NOW REQUIRES `--replace`** — see below.
   **VERIFICATION STILL OWED: re-route in memory and compare `scenario_key` per pair against
   all 12,444 DB rows.** Free (everything cached), ~5 min. A 400-pair Postgres↔Pinecone
   cross-check already agreed 400/400 on `scenario_key` + `pair_id` + `turn_index`, and the
   sink share reproduced (47.54% DB vs 47.5% in memory), but that is a sample plus an
   aggregate — only the full comparison covers every pair.
2. **Add the playbook schema + storage functions + loader.** This is what turns Layer C from
   validated into shipped. It is the highest-value remaining item.
3. **Finish `sink_margin_delta`.** DONE: the rule in `shared/relative_match.flat_pick` (optional
   6th arg, default 0.0), `LayerBTuning.sink_margin_delta`, `tuning.yaml` at 0.0 with full
   rationale, 6 tests including **400 randomized cases proving delta=0.0 is byte-identical**.
   **NOT DONE:** `v1.layer_b.assign_scenarios` has its own inline pick loop at
   `v1/layer_b.py:126-143` and never calls `flat_pick`, so the knob is **inert on the primary
   path**. Wire it, prove byte-identity at 0.0 against REAL scenario rows, and **do not set a
   non-zero value** — that needs a judged sample larger than the 80 turns that exist.
4. **Build the `gateway` embedding backend** in `preprocessing/embedder.py`. Required before
   production embeds any FRESH text; flipping `backend: gemini` today sends embeds to Google AI
   Studio at ~1k/day instead of the gateway, and the two caches use different key schemes.
   `task_type` is inert on gemini-embedding-2 (measured, cosine 1.0000), so gateway vectors are
   equivalent — and every vector for this corpus is already cached, making the switch nearly free.
   Move the transport into `preprocessing/`/`shared/` and have calibration import it, never the
   reverse.
5. **Review the `trigger_quality` cosine bands in gemini space.** They were fitted to bge
   (trigger p50 0.550) against a gemini cosine floor nearer 0.63. Flag, do not silently re-tune.
6. **The playbook scale-up**, with the corrected numbers: **~3.9 calls/document, not 3** (≈130
   for 34 scenarios), ~1 in 6 documents needing a retry, and a tail of scenarios too shallow to
   reach the schema's 3-move floor that **no retry budget can rescue**. Pre-register an exclusion
   rule and cap attempts at 2 BEFORE spending.

### 2.1 Write-fidelity defects found by questioning the ship (all three FIXED)

Prompted by "what guarantees the key is uploaded with its calculated pair", and worth recording
because two of them were mine and would have bitten a future re-run silently:

- **`storage.insert_kb_pair` was `ON CONFLICT DO NOTHING`, not an upsert**, despite its
  neighbours being upserts. On a collision the old row survived and the function returned its
  `pair_id` — so a re-run after any routing change would keep the OLD `scenario_key` in Postgres
  while handing the NEW one to Pinecone as metadata under that same `pair_id`. **The two stores
  would disagree about which scenario a pair belongs to, with no error anywhere.** Today's run
  was unaffected only because `kb_pairs` was empty. **FIXED:** true `DO UPDATE` on
  scenario_id/key/keys plus the trigger and response text (a re-parse that moved speaker roles
  must not leave stale text under a fresh verdict).
- **`ops/ship_layer_b.py` would happily layer a run over an existing table.** **FIXED:** it now
  REFUSES a non-empty `kb_pairs` without `--replace`, which truncates first. Upserting alone is
  not enough — any pair the new run does not produce would survive as a stale orphan with a live
  Pinecone vector.
- **The one positional pairing in the write path is now asserted.** `scenario_key` travels ON the
  pair dict (`assign_scenarios` mutates it in place), so a key can never land on the wrong pair —
  that is a structural guarantee, not a check. But `trigger_vecs` is a PARALLEL list matched by
  index, correct only because `pairs` is never reordered between routing and the upsert. Nothing
  enforced it; a future filter or sort would have attached every vector to the wrong pair.

## 3. OPEN DECISIONS THE OPERATOR STILL OWES

- **E1 is built, paid for (47 calls) and UNREAD** — 22 documents, G-F 6/6 both arms. Read it with
  the tilt reported, or leave it parked until the instrument is fixed? Everything pre-registered
  in §14.1/§14.1b remains binding if it is read.
- **Build the instrument fix?** Designed in §14.7, zero chat cost, all 22 documents reusable:
  per-reader packets with independently assigned sides (position bias then cancels within each
  topic AND measures itself), an anti-length instruction, and the 4 move-count-tied topics as a
  secondary.
- **The 24 fabricated sink `bloom_level` values** — make the column nullable and NULL them, or
  leave the defaults? They are currently indistinguishable from real data.
- **Who collects >80 judged turns** so `sink_margin_delta` can be set to something?
- **The rescued-map arm** (spec §11) — recommend CLOSING it rather than leaving it deferred: the
  rescued map failed on the coherence of the clusters themselves, judged on raw member turns, and
  no synthesis model can fix incoherent clusters because synthesis is downstream of them.

## 4. HOUSE RULES (all held today)

Frozen gates pre-registered before code; **one blind CODE audit per harness before it spends**,
findings fixed and recorded in the spec; veto-audit unexpected or contested results (code AND
output); subagents **ONE AT A TIME**, readers/outcome audits on sonnet, code audits may use the
strong model; `no_cache=True` on every chat call; **never batch the embedding endpoint**; VPN for
the gateway; long runs via `ops/run_visible.ps1` (`-ScriptArgs` is ONE string) in a visible window,
never polled — **logs are UTF-16, `iconv -f UTF-16LE` before grepping**; pytest file-by-file; never
overwrite a published artifact (`clean2_*`, `pb_*`, `pbs_*`, `pbv_*`, `union_*`, `layer_bc_*`,
`rt_*`, `rte_*`); a null is a real result; **at any gate failure stop and bring the operator
fallback options.**

**Traps that bit today — all now in `docs/GOTCHAS.md`:** the gateway caps embeddings at **150
requests/window/key** and the old retry ladder (2+4+8s) could not outlast a ~60s window, so a
corpus-sized fetch hard-failed — now paced by a module-level token bucket at 140/min; Pinecone
dimension is immutable and batch size must follow vector width; `layer_bc_arms.taxonomy_sha` is
**register-dependent** and cannot compare arms differing in `scenario_vector_mode` (use
`routing_playbook_ab.taxonomy_identity_sha`); and **the Bash tool's cwd can reset between calls**,
so a `cd Brain && …` chain short-circuited and *reported success having run nothing* — twice. Use
absolute paths for anything unattended.

## 5. SPEND RECORD (2026-08-19)

**79 chat calls** (original trial 32 = control 15 + r1 17; E1 47 = control 23 + r1 24) against a
ceiling raised to 100. Embeddings ≈ 1,050 requests plus the in-flight ~11,872 paced response
fetch. **Zero published artifacts overwritten.** Postgres: one authorised taxonomy replacement,
fully backed up. Four harness defects found by two blind audits, one veto audit and one real run;
five latent production defects found while shipping (`init_index`'s hardcoded 768,
`upsert_pairs`' fixed batch, the register-dependent sha, the missing pacing, the unusable backoff)
— all fixed with tests.
