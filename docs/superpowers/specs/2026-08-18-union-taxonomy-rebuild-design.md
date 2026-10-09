# Union-Corpus Taxonomy Rebuild — Rescued Turn-Mode Map + Playbook Validation (2026-08-18)

**Status: FROZEN pending operator approval. No code exists yet. The gates (T0–T2,
G-R1–G-R4, PV) and every constant below are frozen at approval time and may never be
adjusted after any result is seen.**

Direction settled in-conversation with the operator (2026-08-18 evening), building on:
the playbook method validation (`2026-08-18-playbook-snap-trial-design.md` §9 — the
scale-up target), G-XP1 (64.3% of new-corpus pairs sink under the frozen `clean2_base`
map — the rebuild's motivation), the turn-mode finding (clause-mode fragments convicted;
`clean2_base` is turn-mode), and the Layer A clustering trial (`rescue_centroid`, the
one arm that ever beat the incumbent: +8/9 scenarios at every seed, blinded 10/10,
placebo-beaten, measured in exactly this rebuild's space — gemini@3072 turn mode).

## 0. Decisions taken and their rationale (on the record, not re-litigable)

1. **The rebuild clusters WITH `rescue_centroid`.** Its downstream closure ("rescue
   doesn't matter") was priced entirely against milestone metrics — a yardstick since
   retired as unable to see routing/evidence quality at all. What the rescue measurably
   delivers (substantive coverage 45%→68%, evidence breadth 96→133 calls/scenario,
   account concentration 16%→12%) is the currency the playbook target consumes. Cost is
   zero extra chat: rescue is computed at clustering time and holds cluster count fixed.
   Caveat on the record: the rescue's adjudication-level direction flipped between the
   dirty and clean corpora — the gates below, not the rescue's pedigree, decide whether
   the result ships. The un-rescued base clustering is kept on disk as the fallback arm
   (adjudicating it is a separate operator-approved spend).
2. **Routing stays production `concat` throughout this spec.** The routing record's
   standing bar ("no routing change until an instrument can rank methods across
   population shapes") holds; one variable at a time. The follow-up **three-arm routing
   A/B on the playbook yardstick** — `concat` vs `keyphrases` vs `r1 membership-lookup
   + description fallback` — is pre-registered BY NAME here and gets its own spec with
   frozen gates only after this spec's PV gate passes.
3. **The milestone pipeline is not run anywhere in this spec.** Layer C = playbooks.

## 1. Decision rule

**THE REBUILT MAP SHIPS AS THE PLAYBOOK SUBSTRATE iff all four taxonomy gates
(G-R1–G-R4) pass AND the playbook validation (PV) on the new map passes
(PB0 5/5 ∧ PB2 WON, the snap-trial bars).** Any gate failing → stop, report, and the
operator chooses between the base-clustering fallback arm and closing the direction.
A NULL IS A REAL RESULT.

## 2. Stage A — pool and embeddings (T0, fetch)

- **Corpus:** `recordings/` + `recordings_pull_keep/` (read-only), production parse per
  directory (`layer_bc_arms.parse_corpus` — production transcript parser, Avoma
  rosters, interview/staff/UNATTRIBUTED exclusions), stem-collision assert
  (`expanded_pool_stage1.assert_no_stem_collision`). Pool = CLIENT turns only.
- **T0 (pool fidelity, hard abort):** the old-corpus CLIENT-turn count must equal
  **20,788** exactly — the audited clean figure `clean2_base` was built on. Any other
  number = parse/roster regression; nothing downstream is reportable. New-corpus turn
  count is recorded (expected ~12–13k; union ~33k).
- **Embeddings:** `gemini-embedding-2` @ native 3072 via the gateway (VPN), ONE text
  per request at 20 concurrent — never batched (documented silent-shortfall trap) —
  through `trial_pool_unit_gemini.embed_cached`, verified 0-missing by cache re-read
  (`layer_bc_arms._load_cached`). Old turns are already cached; the new-corpus fetch is
  the ~28-minute spend. Run via `ops/run_visible.ps1` + completion ping (logs are
  UTF-16 — pipe through `iconv -f UTF-16LE` for ping greps).

## 3. Stage B — clustering + rescue (free, T1)

All constants frozen at `clean2_base`'s construction values, same space:

- UMAP (seed **42**, the base seed; UMAP non-reproducibility across launches is a known
  property — one base seed, frozen here, no post-hoc seed shopping) + HDBSCAN,
  turn mode, `MIN_CLUSTER_SIZE = 16`; near-duplicate cluster merge at cosine **0.97**;
  the same triage as `clean2_base`'s construction.
- **`rescue_centroid`, frozen rule:** an HDBSCAN-noise turn is admitted into its
  nearest surviving cluster iff `cos(turn, centroid_c) >= p25({cos(member, centroid_c)})`
  for that cluster. Cluster count and identity unchanged; memberships grow. Computed
  in-process (the stale-sidecar lesson).
- Both membership sets are persisted: **rescued** (adjudicated) and **base** (fallback,
  not adjudicated under this spec).
- **T1 (descriptive, non-gating):** cluster count, noise rate before/after rescue,
  rescued-turn count, size distribution — all recorded in the artifact.

## 4. Stage C — adjudication (the Gemma spend, T2)

The `adjudication_ab.py` machinery and its seven audited guards, new arm name
**`union_rescued`**, new artifact path (never touching the `clean2_*` artifacts):
sequential (accepted-list duplicate detection is an ordered dependency), representatives
= top-6 by centroid cosine, c-TF-IDF keywords, kinds scenario/mechanics/logistics/
merged/failed, failed rows recorded as failed (never synthesized), `served_model` per
row, checkpoint keyed on a membership content hash (resumable, kill-safe),
`no_cache=True`, model pinned `gemini-3.5-flash-lite`.

- **Budget (frozen): ~1 chat call per cluster, expected ~300–450. HARD STOP at 500
  adjudication calls** — halt and ask the operator. Every attempt counted and
  persisted before the POST (the snap-trial discipline).
- **T2 (integrity):** failed-row share ≤ 5% (else halt and ask); served_model
  uniformity reported, shout on mixture.
- Launched in a visible window with a completion ping; resumable at zero re-spend.

## 5. Stage D — taxonomy gates (all free)

- **G-R1 — cohesion vs random null (PRIMARY, comparative so it self-calibrates):**
  instrument = the fragment-finding's test. Per coachable scenario: mean pairwise
  cosine of member turns vs **200 size-matched random draws** from the same pool;
  scenario PASSES iff its cohesion exceeds the draws' 95th percentile. Run the
  IDENTICAL procedure on the new map and on `clean2_base` (its scenarios' member turns,
  same pool = union, same draws seed 42). **GATE: pass-rate(new map) ≥
  pass-rate(clean2_base).** The new map must not be structurally worse than the map it
  replaces.
- **G-R2 — sink rate on the new corpus (the motivating number):** route the union
  pairs with production `assign_scenarios` (concat) against the new map. **GATE:
  new-corpus pair sink share ≤ 59.3%** (≥ 5pp better than the 64.3% measured under
  `clean2_base`). Companion (reported, gating only against collapse): old-corpus sink
  share must not exceed **62.9%** (published 57.9% + 5pp) — the new map must learn the
  new corpus without unlearning the old one.
- **G-R3 — stranding:** **≥ 90% of coachable scenarios have ≥ 10 routed pairs spanning
  ≥ 3 account domains** (merged/collapsed account map, as in the playbook trial).
  Below-floor scenarios are named in the report.
- **G-R4 — blinded scenario-coherence read:** 12 coachable scenarios sampled by seeded
  RNG (seed 42, stratified: 4 from the top third by routed pairs, 4 middle, 4 bottom),
  each shown as 8 member turns (seeded sample); + **6 scrambled negatives** (turns from
  ≥ 4 different scenarios glued). 3 blinded sonnet readers, one at a time, fresh
  context, samples/key in separate files, judgments committed before the key opens,
  duplicate-reader guard. Reader VALID iff ≥ 5/6 negatives rejected. Scenario coherent
  iff ≥ 2/3 valid readers say YES ("one recognizable client situation"). **GATE: ≥ 9/12
  scenarios coherent.**

## 6. Stage E — playbook validation on the new map (PV)

The snap-trial pipeline re-run end to end on the new map, all bars carried unchanged
(they are frozen there; this spec only rebinds the map): pick rule ranks 1/5/10/15/20
of the new map's coachable scenarios by routed-pair count (ties ascending key); donors
= non-pilot count-matched without replacement; 50-pair evidence selection
(account-floor + greedy max-min on cache-only response vectors — one bounded top-up
fetch for newly-coachable responses is expected and budgeted as embedding spend, not
chat); map-reduce synthesis with the placebo twin; **verbatim snap (≥ 0.80)**; PB0;
counterbalanced read (real sides A/B/A/B/A), 3 fresh sonnet readers; PB3; PB1-resized
reported. One prompt hardening, frozen here: the reduce prompt's key-move instruction
gains "prefer evidence from distinct accounts within each move" as a REQUIREMENT
rather than a preference (targets the standing PB1 per-move flag; PB1 stays
non-decisive).

- **PV GATE = PB0 5/5 real ∧ PB2 ≥ 4/5 scenarios** (PB3/PB1 secondary, as before).
- **Budget: ≤ 50 chat calls** (10 documents × ≤ 3 + retries), the pilot-era cap.
- New artifact prefix `pbv_*`; nothing under `pb_*`/`pbs_*` is touched.

## 7. What comes after (pre-registered by name, NOT run under this spec)

1. **Three-arm routing A/B on the playbook yardstick** — `concat` (control) vs
   `keyphrases` (`scenario_vector_mode`, measured 42.1 vs 31.6, single observation) vs
   `r1 membership-lookup + description fallback` (repairs the turn-identity type error;
   its F4 rejection was against the retired milestone yardstick; caveats on record:
   account concentration, junk inheritance). Own spec, own frozen gates, runs only if
   PV passes. ~30–45 calls per additional arm.
2. **Full playbook scale-up** on the winning routing (~3 calls/scenario document) +
   Layer D coarse-check derivation. Out of scope here.

## 8. House rules binding this spec

Frozen gates; pre-run blind CODE audit of every new harness (strong model), findings
fixed and recorded in §9 before any spend; readers/outcome checks on sonnet; subagents
ONE AT A TIME; unexpected gate/placebo results veto-audited (code AND output) before
belief; ZERO Postgres writes; `recordings*/` read-only; no published artifact
overwritten — all outputs new, clobber-refusing, with started_at/pid/seed/shas; long
stages via `ops/run_visible.ps1` + completion pings, never polled; gateway needs the
Joveo VPN; pytest file-by-file; every chat call `no_cache=True`; embedding spend via
the cached path only, verified 0-missing. Budget escalation always asks the operator.

## 9. Pre-run blind code audit findings

*(filled per harness after each audit, before that harness spends anything)*

### 9.1 `calibration/union_pool_fetch.py` (Stage A) — audited 2026-08-18, blind, strong model

Nothing FATAL. Ordering identity (old block leads), T0 gating, cache-key symmetry
(write and re-read use the same `_key`), one-text-per-request enforcement, and chunked
resumability all verified sound against the imported machinery.

1. **MAJOR — fetch had no spend ceiling** (the "old turns are already cached" premise
   was assumed, never asserted): a missing/moved `gemini_embed_cache.db` or a grown
   `recordings_pull_keep/` would silently multiply the budgeted ~12–13k-request spend
   by up to ~2.7x. **FIXED before any spend:** `stage_fetch` now probes the cache first
   and ABORTS if uncached texts exceed the T0 manifest's `new_turns` (old-block cache
   erosion = §8's budget-escalation condition, so it halts and asks).
2. MINOR (residual risk, on the record, no fix possible in this harness): T0's anchor
   is a count; a parse drift landing on exactly 20,788 with different content would
   pass T0 — no byte-level anchor for the clean2 pool was ever persisted. Backstop is
   Stage D's position-for-position refit verification against `clean2_base`'s rows,
   which content drift cannot survive; `old_prefix_sha` creates the missing anchor
   going forward.
3. MINOR — block contiguity was trusted at manifest time. **FIXED:** `pool_manifest`
   now asserts every turn before the `old_turns` boundary carries an old-corpus stem.
4. MINOR (note): `pool_sha` hashes texts, not call attribution — a renamed transcript
   at the same sort position passes drift checks; distinct-call counts unaffected.
5. MINOR (latent, cannot fire here): `embed_cached` would double-pay duplicate uncached
   texts if handed a raw pool; this harness always passes `sorted(set(...))`.

### 9.2 `calibration/union_cluster_rescue.py` (Stage B) — audited 2026-08-18, blind, strong model

**No FATAL or MAJOR findings.** Verified against the imported machinery and the git
diff of the `derive_clusters` extraction: membership snapshots are true copies (no
aliasing), the rescue-noise population (HDBSCAN noise + triage-dropped) is identical to
the bench arm's and to what `clean2_rescued` ran through, the persisted artifact carries
every key Stage C/D read with a provably unique `cluster_id` join key, the base-verdict
policy matches `clean2_rescued` byte-for-byte, the triage knobs in `tuning.yaml` are
untouched since clean2, and exactly one seed-42 fit runs in the process.

1. MINOR — final artifact write was truncate-then-write. **FIXED:** tmp + `os.replace`.
2. MINOR — clobber check is start-of-process only; a second concurrent launch inside
   the fit window could race it. Accepted (house rule: one visible window per stage).

### 9.3 `adjudication_ab.py` delta + `ops/run_union_adjudication.py` (Stage C) — audited 2026-08-18, blind, strong model

**No FATAL or MAJOR findings.** Verified: resume identity cannot blend base/rescued
membership runs (the identity's rescue slot carries `clusters_from:<name>:<membership>`
and members_sha differs); old-style checkpoints resume cleanly; kill-then-resume can
only over-count attempts by ≤1 per kill (the intended pre-POST conservatism); prompt
fields on the clusters-from path are parity with what the clean2_rescued arm carried
(stats/thin recomputed at rescued membership, base-membership triage verdict, same
representative rule); the two union pool constructions are text-identical and sha-gated
against each other; GatewayClient(max_retries=1) means exactly one POST per attempt
(verified against the retry loop — total tries, not retries-after-first); T2 rows
cannot double-count and the driver exits nonzero on failure.

1. MINOR — a successful row whose gateway response omits the model field tallied as
   "(unrecorded)" and was excluded from uniformity, muting the mixture shout exactly
   when the fallback fired. **FIXED:** `t2_verdict` now reports `unrecorded_successes`
   and counts them against uniformity.
2. MINOR (on the record, no change): failed rows are permanent under max_retries=1 —
   a transient-429 burst past 5% halts T2 correctly but recovery is --fresh. A mid-run
   retry would perturb the accepted-list ordering, so failed-is-failed stands.
3. MINOR (residual risk, on the record): the persisted `triage_verdict` is not
   cross-checked against `tuning.yaml` at Stage C; §9.2 verified the knobs untouched
   since clean2, and both sides are recorded in the artifacts.

### 9.4 `calibration/union_taxonomy_gates.py` (Stage D) — audited 2026-08-18, blind, strong model

**No FATAL or MAJOR findings — cleared to run.** Verified: G-R1's sum-vector identity
exact for unit rows; the SeedSequence([42, n]) null is a pure function of (seed, size),
identical across both maps; suffixed-key joins deterministic on both sides; the
base-members refit compares like-for-like against exactly the fields `run_arm`
persisted; origin split uses the same filename form on both sides; assign_scenarios
leaves no pair unassigned; prewarm precedes the cache-only shim; blinding holds (REAL
and NEG groups size-identical, keys only in the KEY file); all frozen bars implemented
exactly; a VOID G-R4 can never aggregate as pass.

1. MINOR — `--report` printed a VOID G-R4 as "NOT RUN" (aggregation was already safe).
   **FIXED:** explicit VOID label.
2. MINOR (deviation from frozen wording, ON THE RECORD, conservative direction only):
   reader validity additionally requires every item answered — a reader rejecting 6/6
   negatives but skipping one REAL item is dropped. A skipped REAL answer is unusable
   for the coherence tally anyway; the deviation can only make passing harder.
3. MINOR — `build_scramble`'s exhaustion escape could in principle return a short
   negative (unreachable on this data). **FIXED:** hard abort if short.
4. MINOR — tercile-remainder docstring overstated np.array_split semantics. **FIXED**
   (comment only; the 4/4/4 sampling itself is a faithful frozen reading).

### 9.5 `calibration/playbook_validation.py` (Stage E) — audited 2026-08-18, blind, strong model

**No FATAL or MAJOR findings — cleared to run.** Stage-by-stage diff against the two
validated origins found no unintended behavioral divergence: the only deltas are the
taxonomy/corpus rebind, the pbv_* paths, the one frozen prompt hardening (anchor
count-asserted, no-op-guarded, byte-identical elsewhere — test-pinned), and the bounded
top-up. Counterbalancing, schema_collapsed→FAIL, NEG-pool exclusion of empty docs,
snapped-doc move counts for scoring, the 50-attempt pre-POST accounting (one POST per
attempt verified in the gateway retry loop), and pbv_-only writes all verified.

1. MINOR — top-up had no numeric ceiling under cache erosion. **FIXED:** halt-and-ask
   above 10,000 uncached selection vectors.
2. MINOR — snap/PB0 didn't assert synthesis completeness (a killed --synthesize could
   yield a misleading PB0 over a subset; the PV gate itself could not pass wrongly).
   **FIXED:** loader now requires the full 2-per-pilot document set.
3. MINOR — final report omitted the chat-attempt count. **FIXED:** carried forward.

## 10. RESULTS

*(chronology; gates evaluated as frozen)*

- **T0 (2026-08-18): PASS** — old corpus exactly **20,788** CLIENT turns. New corpus
  measured **37,214** CLIENT turns; union **58,002** over 1,059 calls — §2's "expected
  ~12–13k new / ~33k union" estimate was wrong by ~2.9x (690 new calls at the same
  ~54-turns/call rate as the old corpus; parse verified healthy on sampled role
  distributions before the number was believed).
- **BUDGET AMENDMENT (operator, 2026-08-18, on the record):** shown the real pool size,
  the ~2.9x fetch spend, and the cluster-count risk, the operator approved the full
  fetch and **removed the 500-call adjudication hard stop** ("do it and remove the 500
  limit thing and run everything in terminal where i can see"). The pre-POST attempt
  accounting and max_retries=1 discipline stay; only the stop is gone. All long stages
  run in visible windows.
- **Stage A fetch (2026-08-18): ZERO spend.** All 52,510 distinct union texts were
  already in the gateway cache (paid for during the expanded-pool stage-1 session);
  cache re-read verified 0 missing. The ~28-min budget line was never touched.
- **Stage B / T1 (2026-08-18, free):** seed-42 fit over 58,002 turns: 600 raw →
  511 merged @0.97 → **307 surviving clusters** (support floor 22 distinct calls).
  rescue_centroid admitted **13,902** turns; noise 59.0% → 35.1%; sizes base
  p50 53 / p90 148 / max 730 → rescued p50 76 / p90 250 / max 1,242. Both membership
  sets persisted to `union_clusters.json`. Expected Stage C spend ≈ 307 calls — inside
  the original ~300–450 band.
- **Stage C / T2 (2026-08-18): COMPLETE, T2 PASS.** Arm `union_rescued`: 307/307
  clusters adjudicated sequentially in 11.7 min, **307 chat attempts, 0 failed rows
  (0.0% ≤ 5%)**, served_model uniform (`gemini-3.5-flash-lite` × 307). Verdicts:
  **35 scenario / 53 merged / 200 mechanics / 19 logistics** (coachable re-based
  13.8%). Artifact `adjudication_ab_union_rescued.json`. Chat spend to date: **307**.
- **Stage D base-members (2026-08-18): VALID.** Seed-42 refit of the old pool
  reproduced `clean2_base` **195/195 position-for-position** (cluster_id, n_items,
  calls, keywords) — G-R1's reference memberships reconstructed, index identity
  anchored via `old_prefix_sha`.
- **G-R1 (2026-08-18): PASS.** New map **35/35 (100%)** vs `clean2_base` **26/26
  (100%)**; gate = pass-rate(new) ≥ pass-rate(base) holds at the tie. Output-checked
  before belief (saturation could mean a broken instrument): values are non-degenerate
  — null band 0.629–0.648 (the gemini space's cosine floor), cohesions 0.660–0.786,
  tightest margins +0.019 (new) / +0.036 (base). The instrument discriminates; the
  null is simply weak against cosine-built clusters, symmetrically for both maps.
- **G-R2 (2026-08-18): PASS.** Union routing (production concat, 12,444 pairs =
  8,467 old + 3,977 new; 254 scenario-text prewarm = the one bounded embed spend):
  **new-corpus sink 49.1%** (bar ≤ 59.3%; 15.2pp better than the motivating 64.3%),
  **old-corpus sink 48.2%** (bar ≤ 62.9%; also better than the published 57.9% — the
  new map learned the new corpus without unlearning the old).
- **G-R3 (2026-08-18): PASS.** **35/35 coachable scenarios (100%)** have ≥ 10 routed
  pairs spanning ≥ 3 account domains (bar 90%). No below-floor scenarios.
- **G-R4 (2026-08-18): FAIL — 8/12 coherent vs the frozen ≥ 9/12.** Three blinded
  sonnet readers, all VALID (each rejected 6/6 scrambled negatives); agreement 17–18/18
  (r1≡r3 byte-identical — flagged on the record, explained by honest convergence over
  18 binary items, separately-dispatched fresh contexts). Verdicts: 8 scenarios
  unanimous COHERENT, 3 unanimous NOT (`job_board_budget_and_publisher_management`,
  `gig_economy_driver_supply_management`, `non_technical_stakeholder_translation`),
  1 at 1/3 (`creative_asset_and_spec_management`).
- **VETO AUDIT of the G-R4 failure (sonnet, independent): RESULT STANDS.** The whole
  artifact chain was re-derived from scratch (production parse, production membership
  join, exact seeded RNG replay): score reproduces bit-for-bit; packet ↔ key alignment
  exact for all 18 groups; negatives genuinely ≥ 4-source; stratified sample matches
  the frozen rule; blinding intact (no name leaks, no size tell). Independent read of
  the four failing groups: the incoherence is SUBSTANTIVE — multi-thread umbrella
  clusters (job_board, creative_asset), mixed companies/situations (gig_economy), and
  a keyword-glue fragment cluster (non_technical: "Tech.", "Technical limitation."
  glued by the word "technical").
- **Diagnostic (on the record):** rescued-turn share does NOT explain the failures
  (failing scenarios span 14–74% rescued share; passing ones include 48% and 66%) —
  two of the four failures are mostly BASE members, so the base-clustering fallback
  arm is not a predicted fix for G-R4.
- **STAGE D VERDICT (rescued arm): gates NOT passed (G-R1/G-R2/G-R3 PASS, G-R4 FAIL,
  veto-audited). Per §1 the rebuild stopped; the operator chose the pre-registered
  base-clustering fallback arm ("we can test base clustering and see").**

### §10.1 FALLBACK ARM (`union_base`, operator-chosen 2026-08-18)

- **Adjudication: COMPLETE, T2 PASS.** 307/307 clusters (base memberships, order and
  keywords held at the same artifact's), 10.8 min, **0 failed rows**, model uniform.
  **34 coachable** / 48 merged / 206 mechanics / 19 logistics (re-based 13.1%).
  Artifact `adjudication_ab_union_base.json`. Cumulative chat spend: **614**.
- **G-R1: PASS** — 34/34 (100%) vs clean2_base 26/26 (100%).
- **G-R2: PASS** — new-corpus sink **47.3%** (bar ≤ 59.3%), old-corpus **48.1%**
  (bar ≤ 62.9%).
- **G-R3: PASS** — 34/34 scenarios ≥ 10 pairs over ≥ 3 domains.
- **G-R4: PASS — 10/12 coherent (bar ≥ 9/12).** Three fresh blinded sonnet readers,
  all VALID (6/6 negatives each); 9 unanimous COHERENT, 1 at 2/3, 2 at 0/3
  (`landing_page_and_conversion_setup`, `non_technical_stakeholder_translation`).
- **VETO AUDIT of the unexpected PASS (sonnet, independent): RESULT STANDS.** Arm
  isolation proven by matching literal packet text to `idxs_base` (rescued memberships
  visibly different); judgment-glob cross-contamination impossible; score, stratified
  sample and negatives all hand-reproduce exactly; blinding held; substantive read
  found no grade-inflation. Cross-arm replication: `non_technical_stakeholder_
  translation` scored 0/3 under BOTH arms' independent readers. On the record: the
  payload-duplicate flag fired on both arms (different reader pairs) — a known
  limitation of 18-binary-item reader design, not grounds to void.
- **STAGE D VERDICT (fallback arm): ALL FOUR GATES PASS.** Per §1, Stage E (PV) may
  run — bound to the `union_base` map. The rescue's measured coverage gains did not
  survive the coherence read; the un-rescued base clustering is the arm that cleared
  the gates. (Consistent with §0.1's own caveat: "the gates, not the rescue's
  pedigree, decide whether the result ships.")

### §10.2 STAGE E (PV on `union_base`, operator-approved 2026-08-18)

- **Select: COMPLETE.** Pilot (ranks 1/5/10/15/20 of 34): `application_volume(771p)`,
  `ats_integration(385p)`, `downstream_activation(233p)`, `landing_page(146p)`,
  `niche_talent_scarcity(104p)`; donors count-matched. 50 pairs each over 16–33
  accounts. Top-up: **1,123** newly-coachable selection vectors (bounded, ceiling
  10k). On the record: the frozen pick rule landed `landing_page_and_conversion_setup`
  (a G-R4 0/3 scenario) in the pilot; the rule stands.
- **HARNESS DEFECT found and fixed mid-stage (on the record):** the v1 wording of the
  frozen prompt hardening ("citing the same account twice … is a violated rule") made
  the model drop account-thin moves to ONE citation, violating the frozen 2–4-entries
  schema — 9 consecutive reduce rejects on `ats_integration::placebo`, diagnosed by
  per-move shape logging (all rejects were n_ev=1 moves with distinct-account
  compliance). v2 wording states the precedence explicitly (distinct accounts whenever
  candidates offer them; NEVER below 2 entries). **Operator chose a FULL fresh restart
  under v2 (within-pair and across-pair prompt symmetry) and raised the PV cap to ~85
  total: 25 v1 attempts on record (`pbv_playbooks_v1_abandoned.json`) + 60 for the v2
  run.**
- **v2 and v3 wordings ALSO failed (6 + 7 attempts, states preserved as
  `pbv_playbooks_v2/_v3_abandoned.json`):** the model persistently emitted a 1-citation
  move (same `americareusa.net`-anchored move across every attempt) despite an explicit
  precedence clause (v2) and an explicit merge-or-drop rule for 1-evidence candidates
  (v3). Conclusion on the record: ANY hard-requirement phrasing of the account rule
  destabilizes `gemini-3.5-flash-lite`'s schema compliance, while the pilot's original
  preference wording synthesized 10/10 cleanly.
- **HARDENING DROPPED (operator amendment, 2026-08-18):** PV runs with the pilot's
  validated reduce prompt VERBATIM. The hardening served only PB1 (reported, never
  decisive); the PV gate (PB0 ∧ PB2) is untouched. PB1-resized is still reported and
  now measures unprompted behavior. Spend at restart: 38 of the ~85 ceiling; the
  final state's own hard stop is 47.
- **Even the pilot prompt failed on `landing_page::real` (6 straight rejects across two
  map draws — the G-R4-incoherent scenario surfacing as fragmented 1-quote candidate
  moves), and its placebo once more. MODEL AMENDMENT (operator): remaining documents on
  `gemini-3.5-flash` with reasoning.** Transport discovery, all on the record:
  `reasoning_effort=high` is unreachable through the gateway (thinking tokens share
  max_tokens → truncation at 16,384; then LiteLLM's server-side 120s cap → HTTP 408
  even at 65,536/600s client timeout); **low effort fits and WORKED — the previously
  unsynthesizable `landing_page::real` cleared on its first low-reasoning attempt.**
  ~10 attempts burned on transport discovery, all counted.
- **SYNTHESIS COMPLETE: 10/10 documents.** 62 attempts in the final state + 38
  abandoned = 100 PV chat attempts total (operator raised the ceiling stepwise from 50,
  driving each retry). 6 docs on flash-lite, 4 on flash-low-reasoning; every pair
  internally model-symmetric.
- **PB0 (snapped): PASS — 5/5 real** (10/10 documents pass, zero bad quotes, no schema
  collapse; snap kept 9-15 quotes/doc, dropped ≤2, dropped ≤1 move on 3 docs).
- **PB2: WON — real preferred in 4/5 scenarios (bar ≥ 4/5), pooled 11–4, 4 unanimous.**
  3 fresh blinded sonnet readers, all VALID (5/5 negatives each; counterbalanced sides
  A/B/A/B/A). The one loss (`application_volume`, 0/3) is the hardest discrimination in
  the design: its placebo twin was built from the most topically-adjacent donor
  (`campaign_level_performance_tracking`). `landing_page` (G-R4-incoherent, reasoning-
  model doc): real preferred 2/3, apply share 1.00.
- **PB3: PASS** (median apply share 0.80 ≥ 0.5). **PB1-resized: 0/5 FLAG** — standing,
  non-decisive, measures unprompted per-move account breadth (hardening dropped).

### §10.3 VERDICT

**PV GATE PASS (PB0 PASS ∧ PB2 WON). Per §1: THE REBUILT MAP — `union_base`, 34
coachable scenarios over the 58,002-turn union corpus — SHIPS AS THE PLAYBOOK
SUBSTRATE.** The rescued arm's map failed G-R4 and is retired (rescue closed for the
fourth and final time, now on the playbook yardstick too). Total spend: 614 adjudication
+ 100 PV chat calls; embedding ~1.4k texts (254+254 prewarms, 1,123 top-up) — the
feared 37k-turn fetch cost zero (cache already warm). Next, pre-registered in §7: the
three-arm routing A/B on the playbook yardstick, then the full playbook scale-up.
