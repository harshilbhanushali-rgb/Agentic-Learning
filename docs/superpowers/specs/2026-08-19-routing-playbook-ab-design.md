# Three-Arm Routing A/B on the Playbook Yardstick (2026-08-19)

**Status: FROZEN pending operator approval. No code exists yet. Every gate (T-R0–T-R2,
G-D, G-F, G-V, G-P, G-W) and every constant below is frozen at approval time and may
never be adjusted after any result is seen. A NULL IS A REAL RESULT.**

Pre-registered BY NAME in `2026-08-18-union-taxonomy-rebuild-design.md` §7.1 and made
live by that spec's PV gate passing (§10.3). Substrate: the shipped `union_base` map (34
coachable scenarios over the 58,002-turn union corpus). Prior art that binds this design:
`docs/findings/layer-a-routing.md` (the withdrawn 16-arm ranking and the standing routing
bar), `docs/findings/layer-b-redesign.md` (`r1`'s F4 rejection on the retired milestone
yardstick), `docs/findings/scenario-playbook-trial.md` (the yardstick itself).

---

## 0. Decisions taken and their rationale (on the record, not re-litigable)

1. **The playbook yardstick is the instrument that clears the standing routing bar.**
   The bar reads: *"no routing change may ship, including `scenario_vector_mode`, until an
   instrument exists that can rank methods ACROSS population shapes."* The bench's own
   metric could not, because it was the centroid arms' objective function (`description`
   went 32% → 97% under its own objective; a random partition beat it under a "neutral"
   lexical one). The playbook read is arm-neutral by construction: no arm optimises for
   a blinded human preference between two synthesized coaching documents, and no arm can
   see the metric. This is the one yardstick on which a routing change may ship.

2. **The comparison is HEAD-TO-HEAD, PAIRED BY SCENARIO — not each-arm-vs-its-placebo.**
   Every arm produces a document for the SAME scenario from the SAME map with the SAME
   prompt and model, differing only in which 50 pairs the router delivered. A reader shown
   both and the scenario's own definition answers exactly the question the bar asks.
   Real-vs-placebo would only re-measure what PV already measured.

3. **The pilot scenario set is FROZEN AT THE CONTROL ARM'S** — the five scenarios PV
   already selected under production routing (`application_volume_and_prioritization`,
   `ats_integration_and_api_mapping`, `downstream_activation_and_cost_metrics`,
   `landing_page_and_conversion_setup`, `niche_talent_scarcity_and_budget_reallocation`).
   Letting each arm re-apply the rank-1/5/10/15/20 pick rule to its OWN routed counts
   would have the arms writing playbooks for DIFFERENT scenarios, which is unpairable and
   therefore unreadable. Each arm's own pick is computed and REPORTED as a descriptive, so
   a frozen pilot that is unrepresentative for an arm is visible rather than hidden.

4. **THE CONTROL ARM IS RE-SYNTHESIZED; the published `pbv_*` documents are NOT reused.**
   Measured this session: of PV's five real documents, three ran on
   `gemini-3.5-flash-lite` and two on `gemini-3.5-flash` `reasoning_effort=low` (the
   model amendment fired mid-run). Reusing them would confound MODEL with ROUTING on
   three of five scenarios — the exact class of two-variables-at-once error this repo has
   retracted findings over. All three arms synthesize fresh under ONE pinned model. Cost:
   15 nominal chat calls, and it buys the only clean control available.

5. **The model is pinned to `gemini-3.5-flash`, `reasoning_effort=low`, for every
   document in every arm.** It is the configuration that synthesized the previously
   unsynthesizable `landing_page::real` on its first attempt, and the only one measured to
   survive fragmented evidence — which is precisely what a routing change can produce.
   `reasoning_effort=high` is UNREACHABLE through the gateway (thinking shares max_tokens;
   LiteLLM's server-side 120s cap → HTTP 408) and is not attempted. `max_tokens=65536`,
   client timeout 600s, `temperature=0.2`, `no_cache=True`, one POST per attempt.

6. **The reduce/map prompts are the pilot's VALIDATED wording, VERBATIM.** The frozen
   "distinct accounts" hardening is not revived: three wordings each destabilized schema
   compliance while the original synthesized 10/10 (spec §10.2). PB1-resized stays
   reported and non-decisive.

7. **ONE ARM PER PROCESS.** The `keyphrases` arm works by installing a
   `dataclasses.replace`d `Tuning` into the `shared.tuning` singleton before any routing;
   a second arm in the same process could read a stale singleton and silently produce a
   phantom arm. Each arm is a separate invocation, its mode read back and asserted, and
   the resolved mode recorded in the arm's artifact identity.

8. **The optional "rescued map + reasoning synthesis" arm is NOT folded into this spec.**
   Measured this session, before any design was written: the rescued map shares only **6
   of 34/35 coachable keys** with `union_base`, and only **1 of the 5 pilot scenarios**
   exists in it at all. Paired per-scenario reading — the entire source of this design's
   power — is impossible at 1/5. It needs its own pick rule and its own instrument.
   §11 carries the proposal as a separate, cheap, operator-approvable follow-up. It is
   deferred, NOT dropped, and never runs instead of this.

9. **`r1` is a MAJORITY-FALLBACK hybrid on this map, and that ceiling is stated before
   the run, not after.** `union_base` is the UN-rescued clustering: its memberships cover
   **23,770 of 58,002 pool turns (41.0%)**. So ~59% of triggers are HDBSCAN noise and
   fall back to control routing by construction. `r1` cannot move more than ~41% of the
   pairs, and the lookup/fallback split is a REPORTED number on the primary read, never a
   footnote — a result that is really the control's must never be credited to membership.

10. **Milestones are not run anywhere in this spec.** Layer C = playbooks.

---

## 1. Decision rule

**A treatment arm WINS iff, in its own blinded read, it is preferred over the control in
≥ 4 of 5 pilot scenarios (per-scenario preference = ≥ 2 of 3 VALID readers), with the
read not VOID (G-V) and the powered-ness control passing (G-P).**

- If exactly one arm wins → it is the routing candidate; the conditional permutation
  placebo (§8.2) must then be run and beaten before any scale-up or production change.
- If both win → the conditional phase-2 tie-break (§8.1) decides, then the placebo.
- If neither wins → **the standing routing bar HOLDS and production stays `concat`.**
  That is a real result: it closes `scenario_vector_mode` and `r1` on the one yardstick
  that was allowed to reopen them.
- Any gate failing → **STOP, report, and the operator chooses the fallback.** Nothing is
  re-derived after a result is seen.

**Nothing here ships a routing change to production.** A win licenses (a) the playbook
scale-up running on the winning router and (b) a separate production-transfer question —
production embeds with local **bge@768** while everything here is **gemini-embedding-2@3072**,
and that transfer has never been tested (findings: "no routing change may ship to
production citing these numbers alone").

---

## 2. The arms, and what is held identical

| arm | id | router | scenario vector | chat cost |
| --- | --- | --- | --- | --- |
| **control (production)** | `concat` | `r0` (production `assign_scenarios`, verbatim) | `business_description` + `keyphrases` | 5 docs |
| **treatment 1** | `keyphrases` | `r0`, verbatim | `keyphrases` only (`scenario_vector_mode`) | 5 docs |
| **treatment 2** | `r1` | `layer_b_routers` membership lookup, **fallback to `r0`+`concat`** on HDBSCAN noise | concat (fallback path only) | 5 docs |

Held identical across all three arms: the map (`union_base`), the corpus (union,
`recordings/` + `recordings_pull_keep/`), the pair extraction (`s0`/`a0`), the pilot
scenario set (§0.3), the account map, the evidence-selection rule (account floor 8 +
greedy max-min, `N_EVIDENCE_MAX=50`), the map/reduce prompts, the model and every sampling
parameter (§0.5), the snap algorithm (`SNAP_MIN_SCORE=0.80` and its collapse rules), the
renderer, `SEED=42`, and the read design. **Exactly one thing moves: which pairs the
router delivers to a scenario.**

Measured pre-emptively so the `keyphrases` arm cannot run half-concat by accident: **0 of
259 scenarios in `union_base` have empty `keyphrases`** (min 1, median 3, max 4 per
scenario) and 0 have an empty description. The arm runs pure; the harness still asserts
**zero** `scenario_text` mode-fallback warnings and aborts if any fire.

### Machinery reused, never re-implemented

| need | use |
| --- | --- |
| union pool + T0 anchor | `union_pool_fetch.build_union_pool`, `load_t0` (old block leads) |
| corpus parse (one object, shared with the router join) | `layer_bc_arms.parse_corpus` per dir, concatenated old→new |
| pairs | `layer_bc_arms.build_pairs(..., parsed=…)` |
| control routing | `v1.layer_b.assign_scenarios` (production, verbatim) |
| `r1` routing + its guards | `layer_b_routers.router_context_from_clusters`, `assign_scenarios_router` |
| membership pin | `adjudication_ab.members_sha` |
| substrate/prewarm/cache-only shim | `layer_bc_arms.prewarm`, `install_embedder_shim`, `_load_cached` |
| pilot/donor/selection/prompts/PB0/score | `scenario_playbook_trial` (pure functions) |
| snap, counterbalancing, PB1-resized | `playbook_snap_trial` |
| account map | `flag_proper_noun_clusters.account_map` + `expanded_pool_stage1.merge_account_maps` + `layer_b_arms.collapse_sibling_domains` |

`build_router_context` is NOT used: it re-fits a single-directory clustering and pins by
`members_sha`. This corpus is two directories and the clustering is persisted, so the
**pure** half (`router_context_from_clusters`) is called with clusters projected from
`union_clusters.json` — and the projection is pinned by recomputing `members_sha` (T-R0).
The projection reads only `{cluster_id, idxs}`, which is all `member_sets` consumes;
`load_persisted_clusters` is deliberately avoided because its stats recomputation would
materialise a ~712 MB pool matrix that `r1` never touches.

---

## 3. Stage 0 — integrity anchors (free, hard aborts)

- **T-R0 (membership pin):** projecting `idxs_base` from `union_clusters.json` must hash
  to the `members_sha` recorded in `adjudication_ab_union_base.json`'s identity.
  **VERIFIED WHILE WRITING THIS SPEC: `12d2f5fccee8106c` on both sides.** Re-asserted in
  code at run time; a mismatch means the lookup would attach member sets to scenarios
  that were adjudicated over different clusters, and it aborts.
- **T-R1 (positional join):** `turn_to_pool_index(parsed, pool_texts)` must verify every
  CLIENT turn text-for-text against the pool, over all 58,002 items, and abort on the
  first mismatch. This is `r1`'s load-bearing guard: a silently misaligned join routes
  every trigger to the wrong cluster while producing perfectly plausible numbers.
- **T-R2 (pool identity):** `pool_sha` must equal `union_pool_t0.json`'s
  (`475d2de4eee8df4f`), `old_prefix_sha` must match, old-corpus CLIENT turns must be
  exactly **20,788**, and stems must not collide across the two directories.

Any T-R failure = nothing downstream is reportable. Halt.

---

## 4. Stage 1 — routing (free; one bounded embedding prewarm)

Per arm, one process: parse → pairs → prewarm scenario texts → cache-only shim → route.
Recorded per arm: routed-pair count per scenario, coachable/sink split, sink share on the
old and new corpus blocks, the arm's OWN rank-1/5/10/15/20 pick (descriptive), and for
`r1` the full `diag` — `r1_lookup_resolved` / `r1_lookup_share` /
`r1_fallback_noise` / `r1_fallback_unmapped` / `r1_lookup_to_sink`.

Expected ~12,444 pairs (8,467 old + 3,977 new), matching G-R2. Trigger vectors are
already cached from G-R2; the only embedding spend is the **keyphrases-register scenario
prewarm (~259 texts, one text per request at 20 concurrent, never batched)**. Every other
embedder call is served by the shim, which ABORTS on a miss rather than silently spending.

`r1_fallback_unmapped` must be **0**: a trigger whose pool index cannot be found is a
broken join (T-R1's failure mode), not a property of the clustering, and it aborts.

---

## 5. Stage 2 — evidence selection and the pre-spend divergence gate (free + bounded top-up)

Per arm, for each of the five FROZEN pilot scenarios: build the pool with production
clause segmentation (`build_pool`), then the frozen two-phase `select_evidence`
(account floor `min(8, #accounts)`, then greedy max-min) to 50 pairs. Donor pools are NOT
built — placebo twins come from the published `pbv_*` documents (§7.2), so no arm pays for
a donor.

One bounded top-up fetch per arm for selection vectors the cache has never seen (the new
arms route pairs into these scenarios that control routing never did), with PV's
**ceiling of 10,000 uncached texts → HALT AND ASK**, and a post-fetch assertion that
nothing is still uncached.

### G-D — DIVERGENCE (frozen, decides which arms are allowed to spend)

For each treatment arm T and pilot scenario s, with S(s) the selected 50-pair set:

> **arm T proceeds to synthesis iff `|S_T(s) \ S_control(s)| ≥ 10` on ≥ 3 of the 5
> pilot scenarios.**

Below that bar the arm's documents would share ≥ 80% of their evidence with the control's
on most scenarios; no blinded read can resolve that, and any preference measured would be
model noise dressed as a routing result. **An arm failing G-D is reported as a NULL BY
CONSTRUCTION with its divergence numbers and spends nothing.** If BOTH treatment arms
fail G-D, the entire chat spend is cancelled and the finding is that routing is not a live
variable on this yardstick at this map — a real result at zero chat cost.

Reported alongside (descriptive, non-gating): per-scenario routed-set Jaccard vs control,
selected-set overlap, accounts-in-pool and accounts-selected per arm, and the arm's own
pilot pick.

---

## 6. Stage 3 — synthesis, snap, and the fidelity gate (the chat spend)

For each arm clearing G-D, and for the control: 5 real documents, `doc_id` =
`<arm>::<scenario>::real`. Two map batches (`BATCH_MAX=25`) + one reduce per document =
**3 nominal calls/doc**; `ATTEMPTS_PER_CALL=3`; every attempt persisted BEFORE its POST;
resumable per document at zero re-spend; killed runs resume, never restart.

Then the deterministic verbatim snap (`snap_doc`, threshold 0.80, move dropped below 2
citations, document `schema_collapsed` below 3 moves).

### G-F — FIDELITY (frozen, per arm)

> **All 5 of an arm's snapped documents must pass PB0 against their OWN evidence set
> (zero fabricated / altered / misattributed quotes, zero account mismatches, no schema
> collapse).**

An arm failing G-F is REPORTED and EXCLUDED from any win claim: documents whose quotes
cannot be tied to real text are not evidence about routing. A quote-level PB0 failure on
a SNAPPED document is by design impossible → it is a harness bug and triggers a veto
audit of code AND output before anything is believed.

---

## 7. Stage 4 — the blinded head-to-head read (free)

### 7.1 Two independent packets, not one

**Comparison 1:** `keyphrases` vs `concat`. **Comparison 2:** `r1` vs `concat`.

They are read in SEPARATE packets by SEPARATE readers. One combined packet would show the
same control document twice, letting a reader recognise it and anchor — a tell that would
corrupt both comparisons at once. Readers are free; the confound is not.

### 7.2 Packet composition (14 items each, order seeded at `SEED=42`)

**AMENDED 2026-08-19 after the pre-run audit — see §12 finding 1. The original composition
(13 items; 3 calibration pairs drawn from the published `pbv_*` documents at pilot ranks
1/3/5) was FATALLY defective and could not be repaired at 3 pairs.**

| items | what | role |
| --- | --- | --- |
| 5 | PAIR: the arm's document vs the control's, under the scenario's own header | **the treatment** |
| 4 | PAIR: published **`pbs_*`** (snap-trial, OLD map) real vs its placebo twin — `creative_approval_and_budget_phasing`, `multi_channel_spend_and_board_optimization`, `publisher_mix_and_quality_review`, `trial_period_and_minimum_spend_negotiation` | **G-P powered-ness control** |
| 5 | SINGLE: scrambled composite (`build_neg`, ≥ 3 source documents), headed by the highest-routed **non-pilot** coachable scenarios | **G-V validity control** |

Readers see one renderer for every document, are told nothing about arms or routing, and
answer the frozen format: PAIR → `choice` (A/B, no EQUAL) + one APPLY/VAGUE rating per
key move per side; SINGLE → `answer` YES/NO. The key is written to a SEPARATE file; three
fresh blinded sonnet readers per packet, dispatched **ONE AT A TIME**, judgments committed
before the key is opened, duplicate-identity AND duplicate-payload guards enforced.

The calibration pairs cost nothing (both documents already exist on disk) and their model
mix is irrelevant: they measure whether the reader pool can prefer a genuinely better
document at all, not routing.

### 7.3 Counterbalancing (frozen, deterministic — never a coin)

For pilot rank position `i` (0-based) in comparison `c` (0 = keyphrases, 1 = r1), the
**treatment** takes side **A iff `(i + c) % 2 == 0`**, else B. Extends
`counterbalanced_side` by the comparison offset so no arm sits on one side across a
packet and the control does not occupy the same side in both comparisons.

**Calibration pairs are counterbalanced on their index WITHIN THE CALIBRATION SET** —
`counterbalanced_side(j)` for `j = 0..3`, giving **A/B/A/B** (amended; §12 finding 1). Four
alternating pairs hand a purely position-answering reader exactly 2 of 4, below G-P's bar
of 3, so **no side pattern can pass G-P**. This is a structural guarantee, not an appeal to
reader honesty: at 3 pairs no pattern achieves it, which is why the count moved from 3 to 4.

Item order is seeded per comparison (`SEED + 1000·index(comparison)`) rather than from one
shared `Random(SEED)` — §12 finding 9. Sides are assigned before the shuffle, so ordering
cannot favour an arm.

### 7.4 Gates

- **G-V (validity):** a reader is VALID iff it answered every item AND rejected ≥ 4 of 5
  SINGLE negatives. Fewer than 3 valid readers → the packet is **VOID** (not a null) and
  is re-dispatched with fresh readers, on the record.
- **G-P (powered-ness):** the reader pool must prefer the real document (≥ 2 of 3 valid
  readers) on **≥ 3 of the 4 calibration pairs** (amended from 2 of 3; §12 finding 1). If
  G-P fails, the packet is **VOID** — a "no difference" result from a pool that cannot
  detect a known difference is not a null, it is a broken instrument. This is the guard
  that makes a null in this design believable, and it VOIDS a win as readily as a null: a
  pool that cannot detect the known difference cannot certify an unknown one either.
- **G-W (the primary win rule):** as §1 — the arm preferred in ≥ 4 of 5 pilot scenarios.

Reported, never decisive: pooled votes (of 15) with a descriptive two-sided sign test,
unanimity count, apply-share per scenario and its median (PB3 shape), PB1-resized per
document, and every Stage 1 routing diagnostic.

---

## 8. Conditional stages (pre-registered here; each needs its own operator go-ahead to spend)

### 8.1 Phase-2 tie-break — fires ONLY if BOTH treatments clear G-W

A third packet, `keyphrases` vs `r1`, same 5 scenarios, same construction, 3 fresh
readers. **ZERO chat calls** — both sides' documents already exist. Winner = preferred in
≥ 3 of 5 scenarios; a 2–3 split with no majority is reported as UNRESOLVED and the
operator chooses. Pre-registered so the tie-break is not invented after seeing a tie.

### 8.2 Permutation placebo — fires ONLY if an arm wins, and MUST be beaten

The F4 control for a routing arm: keep WHAT the router moved and WHERE, randomise WHICH
pair goes where — route under control and under the winner, take the pairs whose
destination CHANGED, keep that exact destination multiset and permute which pair receives
which (deterministic at `PLACEBO_SEED`, with the destination-multiset and no-loss
invariants ASSERTED). This answers "did the router CHOOSE well" rather than "did churn
help", and it is the question that sank `a4` and `r1` before.

- Winner `r1` → the existing audited `r1p` path in `layer_b_routers`, used as-is.
- Winner `keyphrases` → the identical construction against the keyphrases changed-set,
  which does NOT exist in `layer_b_routers` (`_PLACEBO_OF` covers r1p/r2p/r3p only). It is
  new code, gets its own blind code audit before spending, and the audit finding goes in
  §12 like every other harness.
- Cost: 5 documents (~15 nominal, ~21 expected chat calls) + one 14-item packet, 3 fresh
  readers. **A win that does not beat its placebo is NOT a win** and is recorded as such.

---

## 9. Budget (frozen; every number asked for before it is spent)

| line | nominal | expected | hard stop |
| --- | --- | --- | --- |
| Stage 3 synthesis, 3 arms × 5 docs × 3 calls | 45 | ~64 | **70 — halt and ask** |
| Stage 4 read (6 readers, 2 packets) | 0 | 0 | 0 chat |
| §8.1 tie-break, conditional | 0 | 0 | 0 chat |
| §8.2 placebo, conditional, **separately approved** | 15 | ~21 | **25 — halt and ask** |

The ~64 expectation is measured, not guessed: PV's four flash-low documents cost 17
attempts (4.25/doc) once transport was solved. **Total ceiling if every conditional
fires: 95 chat calls, of which no more than 70 may be spent without coming back.**

Embedding: the keyphrases scenario prewarm (~259 texts) plus one bounded selection-vector
top-up per arm (ceiling 10,000 → halt and ask). Never batched; the cache is checked before
anything is priced (the 37k-turn fetch that cost zero is the precedent). **ZERO Postgres
writes. Zero writes anywhere under `recordings*/`.**

New artifact prefix **`rt_*`**. Nothing under `clean2_*`, `pb_*`, `pbs_*`, `pbv_*`,
`union_*`, `layer_bc_*` is written, moved or overwritten — all clobber-refusing, all
stamped with `started_at`/`pid`/`seed`/shas/resolved mode.

---

## 10. House rules binding this spec

Frozen gates pre-registered before code; **one blind CODE audit per harness before that
harness spends anything**, findings fixed and recorded in §12; unexpected results
veto-audited (code AND output) before belief; subagents **ONE AT A TIME**, readers and
outcome audits on sonnet, code audits may use the strong model; `no_cache=True` on every
chat call; embeddings cache-first and never batched; the gateway needs the Joveo VPN;
long stages via `ops/run_visible.ps1` in a visible window with a completion ping, never
polled (logs are UTF-16 — `iconv -f UTF-16LE` before grepping); pytest file-by-file; a
null is a real result; any gate failure stops the run and returns to the operator with
fallback options rather than a repair.

---

## 11. Recorded limitations, and the deferred rescued-map arm

**Limitations, stated not buried.**
- **5 scenarios is a weak instrument.** At 3 readers × 5 scenarios the win bar (4/5) is
  the same one PB2 was validated at, but it cannot resolve a small routing effect. A
  narrow loss is NOT evidence of no effect; it is an unresolved question, and the finding
  will say so.
- **`r1` is capped at ~41% of pairs on this map** (§0.9) and is majority-control by
  construction. A null for `r1` here is a null for *`r1` on an un-rescued clustering*.
- **Everything is gemini-embedding-2@3072; production is bge@768.** The transfer is
  untested by deliberate choice and no production change may cite these numbers alone.
- **The frozen pilot is the control's.** It is the only pairable choice, and it is mildly
  favourable to the control: those five scenarios are the ones control routing ranked
  1/5/10/15/20. Each arm's own pick is reported so the size of that tilt is visible.
- **One scenario in the pilot (`landing_page_and_conversion_setup`) scored 0/3 on the
  G-R4 coherence read.** It stays: the pick rule is frozen and it was in PV's pilot too.
- **G-P is bias-proof against SIDE patterns by construction, but not against every
  non-content strategy** (§12 findings 1 and 12.2.2). Two residuals, both stated rather than
  closed. (a) *Partial* position bias: alternating sides mean it cannot favour either arm on
  the routing items — it adds noise — but two partially biased readers could reach 3 of 4 by
  luck. (b) **A key-move-count channel: measured on disk, the four calibration pairs are
  4-vs-3 moves on two of them and 4-vs-4 on the other two, and the two separable pairs are
  exactly the two the A/B/A/B rule puts real-on-A — so "prefer the document with more key
  moves, tie-break to B" scores 4 of 4 without reading a word.** Reordering the pairs does
  not remove it, and the set cannot grow without readmitting the excluded ATS near-duplicate.
  It is therefore REPORTED, not engineered away: `rt_<cmp>_report.json` carries
  `calibration_channels` with each pair's move counts, and **a G-P pass whose preferences
  track move count exactly is not evidence of content discrimination — the reader pool must
  then be treated as unproven and the packet re-dispatched.** A test pins the on-disk move
  counts so a future edit cannot silently change how exploitable G-P is.
- **The calibration pairs come from the OLD map, a different synthesis model, AND a
  different question.** Map and model are irrelevant to what they measure (can this pool
  prefer a genuine document over a placebo) and are what keep them from sharing a scenario
  with any routing item. The framing is a real transfer gap: their known 14–1 / PB2 5/5
  strength was measured under "exactly one is the genuine playbook", a sentence this packet
  deliberately deletes (both routing documents ARE genuine). So a G-P failure is ambiguous
  between "this reader pool cannot discriminate" and "the strength did not transfer to the
  new framing", and must be reported as such rather than only as a broken pool.

**The deferred rescued-map arm (§0.8) — proposal, needs its own spec and approval.**
The one mechanism hypothesis four rescue closures never tested is a reasoning model in the
synthesis loop. It cannot be an arm HERE because only 1 of 5 pilot scenarios exists in the
rescued map (6 shared coachable keys of 34/35, measured). A clean separate design exists:
take the **6 keys present in BOTH maps**, apply a frozen pick rule inside that set, route
each map's union pairs to its own version of those scenarios, synthesize under the same
pinned flash-low model, and read blinded head-to-head under a header that is stated
(rather than silently chosen) to come from one map. Cheap — the rescued adjudication is
already paid — but it is a MAP question, not a routing question, and mixing them would put
two variables in one read. Recommend running it after this spec resolves.

---

## 12. Pre-run blind code audit findings

### 12.1 `calibration/routing_playbook_ab.py` — audited 2026-08-19, blind, strong model

Audited before any spend, against this spec, the imported machinery, and the validated
predecessor `playbook_validation.py`. **Verdict: DO NOT RUN UNTIL FIXED (1 FATAL, 3 MAJOR).
All nine findings fixed; tests grew 49 → 65. Zero chat calls and zero embedding calls were
made at any point during the audit or the repair — verified by the absence of any `rt_*`
artifact and by untouched cache mtimes.**

Verified sound and left alone: the T-R0 pin discriminates (base vs rescued shas differ);
the cluster projection is faithful (`member_sets` reads only `cluster_id`/`idxs`, and `vecs`
is dereferenced only for r2/r3, so the zero-column array is never touched); T-R1 joins the
same parse the pairs were built from, in the pool's own order, with a hard raise; the arm
switch genuinely moves production's vectors (`assign_scenarios` → `build_scenario_vecs` →
`_resolve_mode` → `get_tuning()`) and r1's fallback is bit-identical to r0's rule; exactly
one POST per counted attempt, counted before the POST, ceiling checked before increment;
all writes `rt_*`; zero Postgres; zero `recordings*/` writes; every embedding path
cache-only-with-abort or ceiling-guarded, one text per request.

1. **FATAL — G-P was satisfiable by position bias alone, so the gate that makes a null
   believable certified nothing.** `CAL_RANKS = (1, 3, 5)` are all odd, so
   `counterbalanced_side(r - 1)` returned **"A" for all three** calibration pairs in every
   packet; the comment claiming a degenerate draw was impossible, and the key's
   `"counterbalanced": true`, were both false as used. **Fixed in two steps, because the
   first was insufficient and measurement caught it:** counterbalancing on the CAL-set
   index gives A/B/A, but that still hands an always-A reader 2 of 3 — *exactly* the bar —
   and the first regression test contained an escape clause that hid the residual. The
   design defect is that **no side pattern over 3 pairs is bias-proof at a bar of 2.**
   A second, independent and DIRECTIONAL defect was then found in the same construction:
   the calibration pairs reused PILOT scenarios via the `pbv_*` documents, which were
   synthesized from **control-routed** evidence — showing a reader the genuine
   control-derived document for scenario S and then asking it to judge S's routing pair
   lets familiarity anchor it on the control, which does not add noise but **manufactures
   nulls**, disqualifying for this gate. **Final fix:** 4 calibration pairs drawn from the
   published `pbs_*` snap trial (OLD map, PB2 5/5, pooled 14–1 — a known, strong, measured
   difference), sides A/B/A/B, bar 3 of 4. A position-answering reader now scores 2 of 4 and
   **cannot pass, by construction.** `ats_api_integration_and_authentication` was available
   and deliberately excluded: it is the same subject as the pilot's
   `ats_integration_and_api_mapping`, and the anchoring argument applies to a near-duplicate
   subject as much as to an identical key. Zero chat cost — every document already existed.
2. **MAJOR — the control arm could spend in the state the spec cancels the entire spend.**
   Both G-D guards sat behind `arm != CONTROL`, so with no treatment arm cleared,
   `--synthesize --arm concat` still bought 5 documents (~21 expected attempts) against §5's
   "entire chat spend is cancelled … at ZERO chat cost". `stage_divergence` printed the
   cancellation but nothing enforced it. **FIXED:** the cancellation check runs first and
   applies to every arm, with a test.
3. **MAJOR — the G-V negatives were headed by PILOT scenarios while being built from the
   documents the packet displays.** `build_neg` lifts key moves verbatim, so ~53% of
   negatives carried a genuine, well-evidenced move for the scenario named above them, and
   a reader who actually read one could honestly answer YES. Two such answers drop that
   reader below `NEG_REJECT_MIN`, so **G-V would preferentially invalidate the CAREFUL
   readers and retain the ones who reject any scrambled-looking document unread** — exactly
   the readers whose routing votes are worthless. The validated predecessor drew NEG headers
   from non-pilot scenarios for this reason; this harness had diverged without authority.
   **FIXED:** the predecessor's rule restored (highest-routed non-pilot coachable
   scenarios), with tests.
4. **MAJOR — no evidence-volume parity between arms.** `select_evidence` returns
   `min(50, len(pool))`, so an arm that reroutes a scenario's pool below 50 would synthesize
   a THINNER document and the read would compare volume as well as routing — credited to
   routing. G-D could not catch it: `changed` is an absolute count, so a collapsed selection
   clears the bar **more** easily. Reachable on r1 (reroutes ~41% of pairs, some to sinks)
   against control pools as small as 98 accounted pairs. **FIXED:** `--select` halts and
   asks on any shortfall below `N_EVIDENCE_MAX`, before any chat spend; G-D additionally
   refuses to qualify a scenario whose selection size differs from the control's.
5. MINOR — the resumable synthesis state was written with truncate-then-write, reopening a
   corruption window after every attempt; a kill inside it would break both this arm's
   resume and `spend_so_far`'s cross-arm ledger. **FIXED:** routed through
   `adjudication_ab.save_checkpoint` (tmp + `os.replace`), the helper written for this
   exact incident.
6. MINOR — T-R2 compared the re-derived pool only against whatever `union_pool_t0.json`
   currently records, so a regenerated T0 artifact would make the gate self-referential;
   `old_prefix_sha` was stamped but never checked. **FIXED:** both frozen shas and the
   20,788 turn count are module constants and are asserted.
7. MINOR — two frozen reporting requirements were unmet: §0.9's insistence that r1's
   lookup/fallback split is reported **on the primary read** (it lived only in a separate
   artifact, so a win could be read without seeing that ~59% of its pairs were
   control-routed), and §5's per-scenario **routed-set** Jaccard, which was not even
   computable from the persisted artifacts. **FIXED:** routed pair-id sets are persisted,
   `jaccard_routed` is computed and printed, and the routing diagnostics plus the arm's G-D
   row are spliced into the primary report.
8. MINOR (test quality) — the suite passed 49/49 **with the FATAL present**: the
   counterbalancing test asserted in its docstring that neither packet may be all-one-side
   but only iterated the treatment side, and `real_side` was never asserted anywhere. The
   G-D → synthesis gate had no test at all. **FIXED:** the G-P bias property is now tested
   as behaviour ("an always-A/always-B reader must fall below the bar") rather than as a
   side pattern, plus tests for gate enforcement, the clobber guard, one-stage-per-process,
   the NEG header rule, and volume mismatch.
9. MINOR — one shared `Random(SEED)` gave all three packets an identical layout, placing the
   G-P items at the reader's freshest positions and 4 of 5 decisive routing items at its
   most fatigued ones, in every packet. **FIXED** by deriving one stream per comparison.
   **DEVIATION FROM §7.2's "shuffled at SEED=42", ON THE RECORD, CONSERVATIVE DIRECTION
   ONLY:** order stays seeded and reproducible, sides are assigned before the shuffle, so no
   arm can be favoured; it only stops a shared-layout artifact from being systematic.

---

### 12.2 Focused RE-AUDIT of the repairs — 2026-08-19, blind, strong model

The G-P gate was rewritten entirely by the author after audit 12.1, so it was code no
auditor had seen — and 12.1 had already let a FATAL through. A second blind pass was run
over the repaired surface only. **Verdict: DO NOT RUN UNTIL FIXED (0 FATAL, 1 MAJOR). All
five findings fixed; tests 65 → 71. Still zero chat and zero embedding spend.**

Independently re-verified sound: T-R0 recomputes to `12d2f5fccee8106c` and the rescued
projection differs (`cc82f5e65236bcd9`), so the pin discriminates; T-R2's three frozen
literals match the artifact and assert in the right direction; **`v1.layer_b`'s own
`load_tuning()` call cannot revert the installed register** (it does not touch `_cached`),
closing the phantom-arm path; the four calibration scenarios resolve in `clean2_base`, are
non-collapsed, were all real-preferred in `pbs_report.json`, and **none of the four keys
exists in `union_base` at all** — no key collision, no duplicate scenario in a packet, no
CAL/NEG header overlap; NEG headers are the top 5 non-pilot coachable keys; shuffle streams
are distinct and consumed strictly after side assignment; the control's `pick_pilot`
reproduces PV's frozen pilot and all five control pools are ≥ 98 accounted, so the volume
gate cannot spuriously fire on the control; `save_checkpoint` round-trips this state and the
ledger survives a kill; `--score` survives absent artifacts without a KeyError.

1. **MAJOR — a re-dispatched VOID packet silently re-scored the DISCARDED readers.** §7.4
   re-dispatches a VOID to fresh readers, but `--score` globbed every
   `rt_<cmp>_judgments_*.json` and `score_headtohead` keeps the first `N_VALID_READERS`
   valid files **in filename order**, with no round marker on any file. The auditor
   reproduced it: round 1 VOIDs, three fresh readers are dispatched as `r4..r6`, `--score`
   prints 6 files and scores **r1–r3 again**, recording "the packet VOIDed twice, the
   instrument is broken" when the replacement pool was never counted. The mirror case is
   worse — fresh files sorting earlier yield a verdict silently mixed from two dispatches.
   G-P VOID is a live outcome (the weakest frozen pair measured 2/3 in `pbs_report.json`),
   so this was on the likely path, not a corner. **FIXED:** re-dispatches go to a disjoint
   scoped namespace (`rt_<cmp>_round<N>_judgments_r*.json`, `--round N`, N ≥ 2) writing a
   round-scoped report, and `--score` REFUSES outright when more files match than a round
   holds rather than truncating. Tested both directions of the glob disjointness.
2. MINOR — G-P's "bias-proof by construction" holds for side patterns only; the frozen pairs
   carry a **key-move-count channel** worth 4 of 4 to a reader that never reads. Cannot be
   engineered away (see §11). **FIXED as reporting:** `calibration_channels` in every report,
   plus a test pinning the on-disk move counts.
3. MINOR — the harness header still advertised the superseded "≥ 2 of 3" G-P bar, one
   docstring still said 3 CAL pairs, and spec §8.2 still budgeted a 13-item packet. **FIXED**
   in all three places.
4. MINOR — the calibration pairs' known strength was measured under a different reader
   question than this packet asks. **FIXED as a recorded limitation** (§11), so a G-P failure
   is interpretable as a framing-transfer failure and not only as a broken reader pool.
5. MINOR — finding 12.1.4's volume halt raised BEFORE writing the arm's artifacts, so an r1
   shortfall left `rt_evidence_r1.json` absent, `--divergence` (which needs all three arms)
   could never run, and the **keyphrases comparison was blocked by an unrelated arm's
   collapse** — against §5's "null by construction, spends nothing". **FIXED:** the shortfall
   is persisted and shouted at select time, `gd_verdict` disqualifies the affected scenarios,
   and the refusal moved to `stage_synthesize`, which blocks that arm ONLY.

### §13 VERDICT — the read, and what production does

- **G-V PASS** (3/3 readers valid, each rejecting 5/5 negatives). **G-P PASS at exactly the bar**
  (3 of 4 calibration pairs).
- **G-W: r1 preferred in 3 of 5 scenarios against a bar of 4. Pooled votes r1 7 - control 8,
  two-sided sign p = 1.000.** Per-scenario: control took `downstream_activation` and
  `application_volume` 3-0, r1 took `landing_page` 3-0 and both `ats_integration` and
  `niche_talent` 2-1.
- **VERIFIED BEFORE BELIEF** (the result was contested by the operator, which is the trigger):
  side mapping confirmed by locating each arm's UNIQUE quotes in the packet — on the decisive
  item all 9 of r1's unique quotes sit in block B and all 9 of the control's in block A, matching
  the KEY; zero cross-arm citation leaks on any scenario; tally hand-recomputed to 3/5 and 7-8.
  **The result is mechanically sound.**
- **`concat` IS RETAINED. The standing routing bar HOLDS.** Note the bar is asymmetric by design
  and so **the control did not "win" either** — under the same 4/5 bar it took only 2 of 5. The
  correct reading is that the challenger failed to displace the incumbent, not that the incumbent
  is better.
- **AND THE READ IS NOW SUSPECT IN A WAY THAT WEAKENS THE NULL FURTHER.** Readers answered "A" on
  12 of 15 routing votes (80%); r1 held A on 2 topics and B on 3, so pure position answering
  predicts **r1 6 - control 9** against the 7-8 observed. G-P's 3 passes are also largely
  side-explained: 2 of the 3 were real-on-A pairs, and on the two real-on-B pairs the pool went
  **1 for 2**. The content signal rests on a single item. **Reported as UNRESOLVED, never as
  evidence that routing does not matter.**

### §13.1 SHIPPED TO PRODUCTION (2026-08-19, operator-authorised Postgres writes)

- **Layer A is LIVE.** `ops/ship_union_taxonomy.py` replaced the taxonomy: **259 scenarios (34
  coachable + 225 sinks)**, verified key-for-key against the artifact, 0 empty descriptions, 0
  zero-keyphrase rows, 0 CHECK violations. Full backup of all ten tables in schema
  `pre_union_20260819` (**8,295 rows**), row counts verified against source *before* any delete,
  deletes and load in one transaction with a post-load assertion.
- Not an upsert: only **4 of 161** old keys overlapped the new 259, so an upsert would have left a
  416-row mixed-era table. Children deleted before parents (`ON DELETE NO ACTION` forbids
  otherwise): 2,473 `gap_events`, 378 `milestone_performance`, 84 `rubrics`, 4,605 `kb_pairs`.
- **`primary_topic` := the literal `'ungrouped'`** for all 259 with `primary_topic_key` NULL. The
  column is `NOT NULL` and absent from every adjudication row; production derives it by
  centroid-grouping plus an LLM labelling pass the union adjudication never ran, and
  `matching_strategy: flat` means the only consumer is off. A sentinel rather than the
  `scenario_key`, so nobody mistakes it for a derived hierarchy.
- **`bloom_level` audited on request:** 235 of 259 carry a genuine LLM value; **24 were empty in
  the artifact and defaulted to `'understand'`, and all 24 are SINKS — zero coachable scenarios
  were defaulted.** All 34 coachable levels are real (apply 19, analyze 7, evaluate 4, understand
  4) and all 114 `remember` rows are sinks. On the record: **`bloom_level` and `soft_skills` were
  never validated by any gate** — unlike the clusters (G-R1/G-R4) or the descriptions and
  keyphrases (which are the routing vectors, exercised by G-R2). Do not build product logic on
  them without measuring them first.
- **`narens-brain-3072` created** (3072/cosine/aws-us-east-1). The 768-dim `narens-brain` with its
  52,858 vectors is untouched for rollback.
- **Layer B: `ops/ship_layer_b.py`** — routes 12,444 pairs through production `assign_scenarios`
  on the cache-only gemini shim, upserts 1,083 calls, inserts `kb_pairs` with the **live DB
  `scenario_id`**, then populates the triggers namespace, then the paced response tail. Carries a
  hard abort if the sink share leaves **40-56%**, since G-R2 measured 47.3%/48.1% on this exact
  map and router.
- **LAYER C IS DARK BY DESIGN AND THIS IS THE NEXT REAL WORK.** `rubrics`, `gap_events` and
  `milestone_performance` were keyed to the old taxonomy and went with it, and **`db/schema.sql`
  has no playbook table**, so the 5 validated playbooks and E1's 22 documents have nowhere to
  land. Layer C is *validated* but not *shippable* until that schema exists.

### §14.7 The instrument fix — designed, NOT built (the operator deferred it)

Three measured confounds all point at the blinded read rather than at routing: 80% position bias,
a live move-count channel, and ~1 boilerplate move per document. The designed fix, at zero chat
cost since all 22 documents are reusable:

1. **Per-reader packets with independently assigned sides.** Position bias then cancels *within*
   each topic instead of accumulating for one arm — and it **measures itself**: two readers seeing
   one topic in opposite orders who both answer "A" are provably answering position. Report, per
   topic, whether readers agreed on the DOCUMENT or merely on the SIDE.
2. One line in the reader instructions against rewarding length.
3. The 4 move-count-tied topics as a pre-registered secondary, where the length channel is off by
   construction.

Accepting this makes E1 *more topics AND a better instrument*, so it stops being a clean
one-variable extension — it would be declared a new test, with the original 5-topic result still
standing as this spec's primary.

## 14. EXTENSION E1 — widened, higher-powered re-test of `r1` vs control

**Status: FROZEN 2026-08-19, pre-registered BEFORE any extension code or spend, AFTER the
original 5-topic result was known. That ordering is stated openly because it is the whole
risk here: an extension chosen after seeing a near-tie is exactly how a null gets shopped
into a win. Everything that could be tuned toward a desired answer is therefore fixed
below, and the original result is untouchable.**

### 14.0 Why this is being run, and what it may not do

The original read returned **r1 preferred in 3/5 topics (bar 4/5), pooled 7–8, p=1.000** — a
dead heat, mechanically verified (side mapping, arm isolation, hand-recomputed tally, §13).
The operator's objection was that r1 *ought* to win, since it reads the label Layer A already
assigned to that exact turn rather than guessing by cosine. Two defensible reasons the
original could not have shown that even if true:

1. **The bar was inherited from a much coarser comparison.** 4/5 was validated for PB2, real
   playbook vs placebo built from a DIFFERENT scenario's evidence — an enormous difference.
   Reusing it for a subtle within-map routing change, where both document sets draw on
   overlapping evidence, sets a bar a genuinely better router may not clear.
2. **Power, computed not asserted.** At 5 topics and 3 readers, a bar of 5/5 has **~17%**
   power even if r1 truly wins 70% of topics. The original design could fail to detect a real
   effect four times out of five.

**What this extension does NOT fix:** on `union_base`, r1 resolves only **29%** of triggers
and 41% of those resolve to a sink; the other 71% ARE the control. No amount of reading fixes
a treatment that is mostly the control. **If E1 also returns a tie, the correct conclusion is
still "unresolved on this substrate", never "membership routing does not help"** — and the
recorded reason is that the question needs a clustering that labels most of the pool (the
rescued arm labelled 65%, and it is retired for coherence).

### 14.1 Frozen design

- **BUDGET AMENDMENT (operator, 2026-08-19):** ceiling raised **70 → 85** to fund a sixth
  extension topic. 32 already spent; E1's 12 documents cost 36 nominal / **~41 expected** at
  the measured 3.4 attempts/doc, landing at ~73 of 85. **HARD STOP at 85; halt and ask.** **AMENDED (operator, 2026-08-19): ceiling raised 85 → 100** after a second document hit three schema rejects (`n_ev=1` on an over-reached move). Without headroom a stubborn document halts mid-arm and strands E1 with an incomplete r1 arm, wasting the 63 attempts already spent. Expected landing stays ~78.
- **Topics: 11 = the original 5 + 6 new.** The 6 are fixed by a rule ranked on the
  **CONTROL's** routed-pair count — never r1's, so the selection cannot favour the challenger
  — over scenarios that are *eligible*: not already in the pilot, and **≥ 56 routed pairs in
  BOTH arms** (56 because the measured pool/routed ratio is 0.958–0.986, so 56 guarantees a
  50-pair pool and no volume-shortfall disqualification). Taking **eligible ranks 1, 4, 7, 10,
  13, 16** — evenly spaced, spanning the size range as the original 1/5/10/15/20 did:
  `campaign_level_performance_tracking` (643/566), `programmatic_advertising_scope_and_capability`
  (373/317), `xml_feed_setup_and_ingestion` (247/227), `testing_and_implementation_timeline`
  (205/174), `craigslist_and_classifieds_strategy` (116/108), `job_role_taxonomy_and_scoping`
  (101/92).
- **Everything about document production is carried over UNCHANGED:** same map, same corpus,
  same routing artifacts, same 50-pair selection rule, same prompts verbatim, same model pin
  (`gemini-3.5-flash`, `reasoning_effort=low`, `max_tokens=65536`, temperature 0.2,
  `no_cache=True`), same snap, same G-F fidelity gate per arm.
- **Read: two packets** (6 and 5 routing pairs), each with the SAME 4 calibration pairs and 5
  negatives as §7.2, **3 fresh readers per packet, dispatched ONE AT A TIME**. The original 5
  topics are re-read by fresh readers — free, and it doubles their evidence.
- **READER COUNT STAYS AT 3 — AMENDED 2026-08-19 (operator), replacing a 5-reader draft.**
  Two measured reasons. (a) Readers are correlated draws from ONE model: measured **ICC ≈ 0.47**
  on the original judgments, so design effect `1+(m−1)·ICC` turns 33 raw votes at m=3 into
  **~17 effective** and 55 at m=5 into **~19**. (b) A real-on-B calibration pair needs 3/5
  instead of 2/3, dropping from ~0.104 to ~0.058 against a side-biased pool.
  **BOTH FIGURES WERE SUBSEQUENTLY CORRECTED BY THE RE-AUDIT AND ARE RECORDED HERE AS WRONG,
  because the decision was taken on them:** (a) the ICC estimator takes chance agreement as
  0.5, which conflates MARGINAL SKEW with reader correlation — this pool answered "A" on 80%
  of routing items, so chance agreement is 0.68 and the true exchangeable correlation is
  **ρ ≈ 0.167, not 0.467**; at that ρ, 3→5 readers buys **~34%** more effective votes, not 12%.
  And effective votes are not power: simulated at 11 topics with a reader model fitted to the
  original judgments, **P(declare r1 | r1 truly wins 70% of topics) = 0.28 at m=3 vs 0.49 at
  m=5.** (b) At the GATE (A/B/A/B, bar 3 of 4) a purely position-answering pool passes G-P
  with **0.160 at 3 readers vs 0.100 at 5** — so 3 readers make G-P *easier* for a biased pool
  to slip through, the opposite of the recorded rationale, while 5 make it easier for a good
  pool to clear (0.973 vs 0.939 on a real-on-B pair). **The 3-reader choice therefore costs
  roughly half the power and weakens the very gate that protects the null; it stands only
  because it holds the instrument identical to the original read, and the cost is now on the
  record rather than hidden in a wrong number.** **OPERATOR CONFIRMED 3 READERS
  (2026-08-19) after being shown the corrected ρ, the 0.28-vs-0.49 power figures and the
  gate-level G-P numbers.** So E1 moves exactly one variable, and a null from it must be
  reported as UNRESOLVED at ~28% power — never as evidence that routing does not matter.
  Keeping 3 also means **E1 moves exactly ONE variable from the original** (the topic count),
  which is this repo's standing discipline — and the original read already demonstrates this
  pool clears G-P at 3 readers (3/4, including a real-on-B pair at 3/3), so no pre-flight is
  needed.
- **PRIMARY statistic: the POOLED VOTE**, 11 topics × 3 readers = **33 votes**, two-sided sign
  test, **CORRELATION-ADJUSTED**. **E1 declares a winner iff the direction favours that arm AND
  BOTH the raw and the adjusted p are < 0.05.** The adjustment divides the vote count by the
  design effect derived from the observed pairwise agreement, and is labelled approximate
  wherever reported. Without it the nominal 5% test runs at a true error rate near **16%** —
  which is exactly the "second bite at an easier bar" an extension designed after a null must
  not take. Pooled votes are primary because they use every judgment rather than collapsing
  each topic to a binary, which is where the original design threw away most of its power.
- **SECONDARY, reported, never decisive:** topic count at ≥ 2/3 readers per topic, with its own
  binomial p; apply-share; per-topic vote splits; reader agreement structure.
- **G-V and G-P unchanged, per packet.** A packet failing either is VOID and re-dispatched to a
  scoped round (§12.2.1), never reported as a null.
- **Power, stated in advance:** the binding quantity is ~11 near-independent topics, not the
  raw vote count. **E1 roughly doubles the original's independent observations and remains a
  low-powered test** — a clean sweep of 5 topics with unanimous readers does not even reach
  p<0.05 after the correlation adjustment. It is reported as such, and a tie will again be
  called UNRESOLVED rather than a null.
- **Reader-correlation caveat, now enforced rather than only disclosed:** sonnet readers are
  draws from ONE model — G-R4 produced byte-identical readers last night. The pairwise
  agreement matrix, the derived ICC and design effect, and the adjusted p are all reported,
  and the adjusted p **gates the verdict**.
- **SIDE-SHARE IS REPORTED per packet and per reader** — the channel that turned out to explain
  the original result. Measured there: readers answered "A" on **12 of 15** routing votes (80%)
  and 20 of 27 pair items (74%), while r1 held A on 2 topics and B on 3, so pure position
  answering predicts r1 6–9 against the 7–8 observed. E1 cannot repeat that silently.
- **G-D over the 6 new topics is computed and reported as a DIAGNOSTIC** (not a spend gate —
  the frozen topic set may not be narrowed after the fact), so a new topic whose two arms
  barely differ is visible as a coin-flip contributor rather than invisible.
- **Embedding spend, stated:** the 6 new topics were never pooled, so essentially every
  selection vector is uncached — an estimated **~1,700–2,200** one-text-per-request
  gemini-embedding-2@3072 fetches across the two arms, against 502 for the entire original
  trial. Bounded by the inherited 10,000-vector halt-and-ask ceiling.

### 14.1b G-D diagnostic result, and a secondary DECLARED BEFORE ANY READ EXISTS

Measured 2026-08-19, after both `--select` runs and **before any E1 chat spend or judgment**:
of the 6 new topics, **4 clear the divergence bar and 2 do not** —
`campaign_level_performance_tracking` (8/50 changed, selected-set Jaccard 0.724) and
`programmatic_advertising_scope_and_capability` (8/50, 0.724). The other four run 10–19 of 50
changed. Both arms selected a full 50 pairs on every topic; no shortfall, no empty pool.

**The frozen 11-topic set is NOT narrowed.** Dropping topics after seeing their divergence
would be exactly the post-hoc selection this spec exists to prevent, and the dilution is
CONSERVATIVE — two near-identical topics add coin-flip votes, which pushes the pooled result
toward no-difference and therefore cannot manufacture an r1 win. All 12 documents are bought
as pre-registered.

**DECLARED NOW, before any judgment is cast:** the pooled statistic will ALSO be reported
restricted to the 9 topics that clear G-D (the original 5 + the 4 qualifying new ones).
**This is a DIAGNOSTIC, not a second chance at a win.** If the primary is null and the
restricted set is null too, the null is stronger. If the primary is null while the restricted
set shows a difference, that is a HYPOTHESIS for a future, properly pre-registered test — it
is never reported as E1 winning. The verdict is the full-set primary, always.

### 14.2 What is protected

**The original result (§13) is the primary pre-registered outcome of this spec and is not
superseded, merged, re-scored, or re-binned by E1.** E1 is reported as a separate, clearly
labelled, post-hoc-motivated test. New artifact prefix `rte_*`; nothing under `rt_*` or any
published prefix is rewritten. If E1 and the original disagree, both are reported with E1's
post-hoc motivation stated plainly.

### 14.3 Audit findings for the extension harness

*(filled after the blind audit, before E1 spends anything)*

### 14.4 E1 RESULTS

- **Select, both arms: COMPLETE and clean.** T-R0/T-R1/T-R2 pass; the routing-drift assert
  confirmed this run's routed counts **reproduce the original trial exactly**, so E1's documents
  rest on the same substrate as the originals they are packeted against. All 6 new topics
  yielded a full 50-pair selection in both arms — no shortfall, no empty pool. Embedding
  top-ups: 250 (control) + 35 (r1), far under the ~1,700-2,200 estimate because most vectors
  were already cached.
- **G-D over the new topics (§14.1b): 4 of 6 clear the bar.** Below bar:
  `campaign_level_performance_tracking` and `programmatic_advertising_scope_and_capability`
  (both 8/50 changed, selected Jaccard 0.724). **Not dropped**, per §14.1b — the dilution is
  conservative and narrowing a frozen topic set after seeing which topics misbehave is the
  manipulation this spec exists to prevent.
- **Synthesis: COMPLETE, 12/12 documents, 47 chat attempts** (control 23, r1 24) — 79 of the
  amended 100 ceiling including the original trial's 32. Two documents needed retries, both
  diagnosed by the newly added per-move logging as **`n_ev=1` on an over-reached move**; on the
  second the model emitted 3 moves instead of 4 on retry and passed. See §13's correction: this
  is structural, not a flash-lite artefact.
- **G-F: PASS 6/6 on BOTH arms, zero bad quotes, no schema collapse.** All 22 documents across
  both trials are honest evidence.
- **An independent outcome audit of the first three control documents returned DOCUMENTS
  TRUSTWORTHY:** 42 citations checked, **40 byte-exact, 1 repairable near-miss, 1 scoring
  artefact, 0 fabricated, 0 misattributed**, zero arm-isolation breaches, no identifying tells.
  It also flagged that **every move cites exactly 2 evidence entries — the schema minimum** — and
  that a near-identical "phased rollout" move appears in 2 of 3 documents, i.e. ~1 generic move
  per document that is arm-independent and dilutes any real difference.
- **MOVE-COUNT ASYMMETRY, measured before any reading (this is why the read was paused):**
  across the 11 topics the control holds **more moves on 5, r1 on 2, tied on 4** — totals **46 vs
  41 moves and 84 vs 66 surviving quotes.** Since readers demonstrably prefer the longer document
  (§13), the read is structurally tilted **toward the control**. That direction cannot manufacture
  an r1 win, so an r1 win would mean more than the bare numbers; but a control preference would be
  partly artefactual and must not be reported as "control routes better".
- **THE READ WAS NOT RUN. E1 IS BUILT, PAID FOR AND UNREAD** — the operator elected to fix the
  instrument first (§14.7). Everything pre-registered above remains binding if it is ever read:
  the pooled 33-vote **correlation-adjusted** sign test is PRIMARY, the topic count is secondary,
  and the 9-topic G-D-restricted subset is a declared diagnostic and never a second chance at a
  win.

### 14.5 E1 audit findings (both passes, all fixed before it spent)

**Pass 1 — `DO NOT RUN UNTIL FIXED (0 FATAL, 5 MAJOR)`.** `--build-read` **crashed** on
`rt.packet_rng("ext_p1")` and would have fired only AFTER the whole chat spend (no test covered
that stage); a VOID packet still named a `winner` from a split that is not neutral between the
arms; the pooled sign test treated 55 correlated votes as independent (measured ICC ~0.47, true
type-I error ~0.16); side-share — the one channel that actually explained the original result —
was not reported at all; and the §12.2.1 VOID re-dispatch defect had returned (`ext_judgments_glob`
accepted a round and nothing ever passed one). Plus: a false drift-detection docstring, missing
`cal_channels`/apply-share, no G-D diagnostic for the new topics, an unstated ~1.7-2.2k embedding
estimate, and four test-quality defects including a tautological floor test and a vacuous tie test.

**Pass 2 — `CLEARED TO RUN`, and it verified NO TILT toward r1**, which was the highest-priority
question given E1 was designed after a null. Simulated at 11 topics with a reader model fitted to
the original judgments: **P(declare r1) = 0.28 at 3 readers vs 0.49 at 5**, and counterbalancing
puts r1 on side A for only 5 of 11 topics, so against the pool's 80%-A habit pure position
answering predicts control 17.4 - 15.6. It found 11 MINORs, all fixed: the only *permissive*
deviation was `int(round(share x n_eff))`, which shifted the adjusted win threshold **one vote
below** the share it claimed to preserve (at agreement 0.733, t=25/33 rounded UP into a "win");
rounding now floors toward the null. Also restored: the §12.1.1 CAL-vs-topic anchoring guard over
all 11 topics, the "snapped PB0 failure = HARNESS BUG" alarm, per-packet round resolution so a
single-packet VOID is re-scorable, and bias diagnostics computed over all submitted readers on a
G-V VOID (previously written as `null` — precisely the packet where they are needed).

**It also corrected the arithmetic behind the reader-count amendment** (§14.1): the ICC estimator
conflates marginal skew with correlation, so 3→5 readers buys ~34% more effective votes rather
than the ~12% quoted, and at the gate a position-answering pool passes G-P with **0.160 at 3
readers vs 0.100 at 5** — the opposite of the recorded rationale. The operator was shown these
corrected figures and confirmed 3 readers, so E1 moves exactly one variable and its null (if ever
read) is a ~28%-power null.

## 13. RESULTS

*(chronology; gates evaluated exactly as frozen above)*

### Stage 0–2, all three arms (2026-08-19) — ZERO chat spend

- **T-R2 PASS on every arm** — pool re-derived to `pool_sha 475d2de4eee8df4f`, 58,002 turns,
  old block exactly 20,788, `old_prefix_sha` matched. 12,444 pairs (8,467 old + 3,977 new),
  identical to G-R2's published figures. `corpus_sha 1bcc986d15af6f5d` and
  `taxonomy_sha 79808dec1995be46` identical across all three arms.
- **CONTROL (`concat`) — clean, and an exact reproduction of the published control.** Its own
  `pick_pilot` reproduced PV's frozen pilot pair-for-pair (771/385/233/146/104), so the
  frozen-pilot assertion passed; pools 759/377/231/140/98 → **50 selected on all five**, no
  volume shortfall. Embedding spend ZERO (all 259 concat scenario texts already cached).
- **`keyphrases` — REFUTED ON THIS PILOT, not merely null. Routed counts collapse:
  `application_volume_and_prioritization` 771 → **0**, ats 385 → 212, downstream 233 → 62,
  landing_page 146 → 73, niche_talent 104 → 39.** The arm ABORTED on an empty evidence pool
  for the map's largest scenario, and its own pick rule would have chosen five entirely
  different scenarios. Embedding spend: 244 requests (the keyphrases register, ~7 s).
- **VETO AUDIT of the keyphrases collapse (sonnet, independent): RESULT STANDS.** The corpus
  was re-parsed from raw transcripts, all 12,444 pairs rebuilt, and production
  `assign_scenarios` re-run under both registers cache-only: the **control's numbers
  reproduced exactly on all 34 coachable scenarios**, and the keyphrases numbers reproduced
  exactly too. Harness correctness confirmed on every hypothesis tested: the register is
  applied to all 259 scenarios (34 coachable + 225 sinks) uniformly; **0 of 259 scenarios
  have empty keyphrases**, so no silent concat fallback occurred; the cache is keyed on exact
  text so no cross-register collision is possible; scenario vectors are non-degenerate under
  both registers (pairwise cosine mean 0.670 concat vs 0.581 keyphrases, **zero** pairs
  ≥ 0.995). Additional findings: a **second** scenario also collapses to 0
  (`job_role_taxonomy_and_scoping`); system-wide, coachable-routed pairs fall **6,528 →
  4,872** and **sink share rises 47.5% → 60.9%**. Mechanism, traced on the actual 771 pairs:
  the scenario is never even in the top-6 candidates under keyphrases — not narrowly beaten;
  413 of the 771 (54%) fall to backchannel sinks and the remaining 358 fragment across ~15
  coachable competitors with no single winner. **Reconciliation with the withdrawn bench
  (`keyphrases` 42.1 vs `concat` 31.6): not a contradiction. That metric scored the share of
  scenarios clearing a coherence-vs-null bar, and shedding 61% of pairs to sinks leaves
  smaller, tighter populations that score BETTER on it while starving the evidence a playbook
  needs. This is precisely the discrimination the standing routing bar was waiting for.**
- **`r1` — VIABLE, and G-D PASS 5/5.** **T-R0 PASS** (`idxs_base` members_sha
  `12d2f5fccee8106c` matches the adjudication) and **T-R1 PASS** (all 58,002 pool items
  joined text-for-text, `r1_fallback_unmapped` = 0). Pools 631/714/313/440/103 → **50
  selected on all five**, no volume shortfall. Embedding top-up 258 vectors (ceiling 10,000).
  - **Lookup share 29.0% / fallback 71.0%** (3,604 resolved, 8,840 noise-fallback).
    **§0.9's pre-registered estimate of ~41% was WRONG and is corrected here:** 41% was the
    membership share of the whole 58,002-turn pool, but pair TRIGGERS are a biased subset of
    it, and only 29% of them carry a cluster label. **r1 is even more control-dominated than
    the spec claimed** — 71% of its routing is literally the control's.
  - **41.0% of resolved lookups land on a SINK** (1,479 of 3,604), yet overall sink share
    FALLS: old block 48.1% → 43.0%, new block 47.3% → 43.6%.
  - Routed counts shift substantially in both directions: 771→640, 385→**734**, 233→318,
    146→**459**, 104→107. G-D: **5/5 scenarios qualifying**, 12–35 of 50 selected pairs
    changed, selected-set Jaccard 0.176–0.613, routed-set Jaccard 0.310–0.828.
- **BLOCKER (harness, same class as §12.2.5 in a sibling path):** the empty-pool ABORT fired
  inside the pool-building loop, *before* the arm's artifacts were written, so
  `rt_evidence_keyphrases.json` did not exist and `--divergence` — which requires all three
  arms — could not run. The volume-shortfall case had been repaired this way; the empty-pool
  case had not. Stopped and returned to the operator per §10.
  **OPERATOR DECISION (2026-08-19): (a) proceed with TWO arms, `r1` vs control, reporting
  `keyphrases` as a refutation; (b) fix the empty-pool path by record-and-continue, mirroring
  the volume fix.** Implemented: an empty pool is persisted as `empty_pools`, shouted, and
  refused at the spend gate for THAT ARM ONLY; the re-run then also surfaced a **second**
  independent disqualification the abort had hidden — `niche_talent` yields only **38**
  selected pairs against the required 50.

### G-D (2026-08-19, free) — `r1` CLEARED, `keyphrases` DISQUALIFIED

`rt_divergence.json`, all three arms, identity cross-checked mode-invariantly:

- **`r1`: G-D PASS 5/5.** Changed selected pairs per scenario 14 / 35 / 17 / 30 / 12 of 50;
  selected-set Jaccard 0.562 / 0.176 / 0.493 / 0.250 / 0.613; routed-set Jaccard 0.828 /
  0.427 / 0.685 / 0.310 / 0.773. No volume mismatch. **Cleared to spend.**
- **`keyphrases`: G-D PASS 3/5 but DISQUALIFIED regardless** — `empty_pools`
  `[application_volume_and_prioritization]` and `volume_shortfall`
  `{application_volume: 0, niche_talent: 38}`. On its three surviving scenarios it diverges
  enormously (changed 40/50, 36/50, 31/50; selected Jaccard 0.111–0.235), which is precisely
  why it cannot be read: the divergence is a symptom of the map being starved, not of a
  better route. **Not cleared to spend.**
- **Per §1, the trial proceeds as a TWO-ARM comparison, `r1` vs control**, on the operator's
  decision. `keyphrases` is reported as a REFUTATION on the playbook yardstick.

#### Harness defect: DIVERGING is not the same as being USABLE (found by running; no verdict changed)

`--divergence` first reported `arms_cleared_to_spend: ['keyphrases', 'r1']`. G-D's arithmetic
was correct — it refused to let the two broken scenarios qualify — but the arm still passed on
its other three, so the SUMMARY FIELD named a disqualified arm as spendable. `stage_synthesize`
would have refused it anyway (defence in depth held, and no money could have been spent), but
the artifact is the record and it stated something false. **FIXED:** `arms_cleared_to_spend`
now excludes any arm carrying `empty_pools` or `volume_shortfall`, `disqualified_arms` records
why, and the G-D pass is still reported separately so the two facts stay distinguishable.
Tested. **Pattern worth noting across today's four harness defects: the gate arithmetic has
been right every time; the summary lines and the plumbing around the gates have not.**

#### Harness defect found BY RUNNING, not by audit (2026-08-19) — no verdict changed

`--divergence` refused the keyphrases arm with "routed against a different taxonomy_sha — two
variables at once". **This was a FALSE ALARM produced by my own guard, and the guard was
wrong in an instructive way.** `layer_bc_arms.taxonomy_sha` hashes `scenario_text(info)`,
which resolves `scenario_vector_mode` — so it is **register-dependent by construction**, and
using it as a cross-arm identity check rejects the keyphrases arm precisely *for being the
keyphrases arm*. The tell was that `concat` and `r1` hashed identically (`79808dec1995be46`)
while `keyphrases` differed (`f7b0c663a62f107a`), exactly tracking the register rather than
the taxonomy. **FIXED:** a mode-INVARIANT `taxonomy_identity_sha` (key | coachability |
description | keyphrases) is now recorded per arm and is what the cross-arm check compares;
the register-dependent sha is retained and promoted to a **positive** check — it must DIFFER
between arms whose register differs (proving the treatment actually applied) and MATCH between
arms sharing one. All three `--select` stages were re-run (free, deterministic, cache-warm) so
every arm carries the invariant field. Two tests pin mode-invariance and that the invariant
still detects a genuine description/keyphrase/coachability/key change. **No gate, bar, or
verdict is affected: `keyphrases` was already disqualified on two independent grounds and
`r1` on none.**
