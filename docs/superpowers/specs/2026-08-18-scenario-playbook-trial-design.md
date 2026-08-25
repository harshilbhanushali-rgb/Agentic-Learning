# Scenario-Level Playbook Trial — 5-Scenario Pilot (2026-08-18)

**Status: FROZEN pending operator approval. No code exists yet. Gates PB0–PB3, the pilot
pick rule, the placebo construction, and the reader protocol below are frozen at approval
time and may never be adjusted after any result is seen.**

Handoff: `Brain/HANDOFF_PLAYBOOK_TRIAL_2026-08-18.md`. Evidence base (settled, not
re-litigated here): the pipeline-internal search space is exhausted (seven closures);
the gold-pair probe found the gemini@3072 space probably NOT move-blind (11/11
observations, round-2 AUC 0.966, formally underpowered vs its frozen n≥10 bar) while
same-move recurrence at clause granularity is SPARSE, measured three ways. Milestones
as recurring clause-clusters demand recurrence the corpus does not contain. The trial
target therefore changes: one synthesized, evidence-cited **playbook per scenario**,
gated so that the V1 failure mode (narration wearing citations) is caught, not shipped.

## 1. Question and decision rule

**Question:** can LLM synthesis over routed, diversity-sampled, verbatim-cited evidence
produce a per-scenario coaching document that (a) never fabricates evidence, and
(b) blinded readers can distinguish from an identically-synthesized placebo built on
permuted evidence?

**Decision rule (frozen):** the METHOD IS VALIDATED iff **PB0 passes (5/5 real
playbooks) AND PB2 is WON (real preferred in ≥ 4/5 scenarios, reader validity holding)**.
PB1 and PB3 are secondary readouts: reported, flagged on failure, never decisive.
PB2 lost or void ⇒ LLM synthesis on this corpus is narration even with citations forced;
document it and stop — the fallback conversation is operator-level. **A null is a real
result.** This is a directional pilot (n=5 scenarios): it validates the method for
scale-up, it does not by itself produce a significance claim.

## 2. Substrate (identical to the pool-unit trial's)

Rebuilt exactly as `calibration/layer_c_pool_unit.py::build_substrate` does: production
parse of `recordings/` + `recordings_pull_keep/` (read-only), stem-collision assert,
production `build_pairs` at (s0, a0), cache-only embedder shim at width 3072, production
`assign_scenarios` routing against the frozen `clean2_base` taxonomy, coachable scenarios
only. Sidecar account map: `flag_proper_noun_clusters.account_map` over BOTH dirs
(abort if either comes back empty), merged via `expanded_pool_stage1.merge_account_maps`,
then ONE `layer_b_arms.collapse_sibling_domains`.

**PB-F0 (substrate fidelity, hard abort):** the pool-unit V0 check, reused verbatim —
this process's production clause path must reproduce the stage-1 artifact
(`artifacts/layer_bc_xp_union.json`) per-scenario `clause_pool` list-identically for all
26 scenarios. Any diff = harness bug; nothing downstream is reportable.

**Evidence pool per scenario:** its routed (trigger, response) pairs whose call stem has
an account domain in the merged map. Pairs from account-less calls are excluded from
evidence (a citation without an account defeats PB1); the excluded share is printed.
Pairs whose response yields zero production-segmenter clauses are also excluded (they
have no cached selection vector and no quotable content); counted and printed.

**Selection vectors (zero new embedding spend):** each pair's response-level vector is
the cached gemini@3072 vector of its `u_turn` unit text — the response's production
segmenter clauses joined with a single space, exactly as
`layer_c_pool_unit.units_from_response(mode="u_turn")` derives it; these texts were
fetched and verified 0-missing by the pool-unit trial. Loaded via
`layer_bc_arms._load_cached`; **any cache miss aborts the run** (no silent refetch,
no gateway embedding spend).

## 3. Pilot pick rule (frozen — the rule, not the list)

Rank the 26 coachable scenarios by routed-pair count in this substrate, descending,
ties broken by ascending `scenario_key`. The pilot set is **ranks 1, 5, 10, 15, 20**.
The list is computed by the harness and recorded in the artifact; no substitution after
seeing anything downstream (drafts, gates, reads).

## 4. Evidence selection (frozen)

Per pilot scenario, select **N = min(50, pool size)** pairs, deterministically:

1. **Account floor first:** iterate account domains present in the pool in descending
   pair-count order (ties: ascending domain string); from each, take the pair whose
   selection vector is nearest the scenario pool centroid; stop when
   **min(8, #accounts-in-pool)** distinct accounts are covered.
2. **Diversity fill:** fill remaining slots by greedy max-min (farthest-point) selection
   on the selection vectors over the whole pool, seeded start = the already-selected
   set; ties broken by pool order.

The selected evidence (pair identities, call stems, accounts, vectors' source texts) is
recorded in the artifact before any synthesis call runs. No truncation of pair text.

## 5. Synthesis (the only Gemma spend)

- Transport: `calibration/trial_gateway.GatewayClient.chat_json`, model pinned
  `gemini-3.5-flash-lite` (no fallback chain), temperature 0.2, JSON-forced,
  **`no_cache=True` on every call** (documented gateway response-caching trap — this is
  an A/B against a placebo twin; a cache echo would destroy it). Gateway needs the Joveo
  VPN. Per-call usage, model, and timestamp recorded.
- **Map-reduce, frozen shape:** evidence split into batches of ≤ 25 pairs in selection
  order → one MAP call per batch (extract candidate moves, each with verbatim quotes +
  call stem + account) → one REDUCE call (merge into the final playbook JSON). N ≤ 25
  ⇒ 1 map + 1 reduce. N in 26..50 ⇒ 2 map + 1 reduce.
- **Playbook schema (JSON, machine-checkable):** `situation_signature` (from the
  scenario's `business_description`, keyphrases, and the selected triggers);
  `arc` (ordered move sequence); `key_moves` — **3 to 6 moves**, each
  `{name, criterion, evidence: [{quote, call, account}] with 2–4 quotes}`;
  `signature_language` (phrases/benchmarks, each with quote+call+account);
  `pitfalls_and_variants`; `layer_d_checks` (3–5 coarse scorable checks — descriptive
  only, wiring Layer D is out of scope). **The one hard authoring rule, enforced by
  prompt AND by PB0: no claim without a verbatim quote + call citation.**
- The prompt forbids naming Naren or any person (V1-narration lesson): criteria must be
  written as what a different CSM's handling must satisfy; quotes stay verbatim.
- Both arms (real and placebo) use byte-identical prompt templates and the identical
  map-reduce shape; only the evidence block differs.

**Budget (frozen):** planned ≤ 30 calls (5 scenarios × 2 documents × ≤ 3 calls).
Invalid-JSON/schema retries allowed, every attempt counted. **Hard stop at 50 total
chat calls** — at 50 the harness halts and the operator is asked before any further
spend.

## 6. Placebo twin (mandatory, frozen)

Per pilot scenario *i*, a second playbook synthesized **identically** — same scenario
header (`scenario_key`, `business_description`, keyphrases, and situation-signature
instructions for scenario *i*), same prompt template, same map-reduce shape, same
selection algorithm — but the evidence is drawn from a **donor scenario** instead
(destination-permutation precedent: `lcfr_common.permute_destinations` — assignment
shuffled, everything else preserved).

- **Donor assignment (frozen):** donors come from the 21 NON-pilot coachable scenarios.
  Walking the pilot scenarios in rank order (1, 5, 10, 15, 20), each is assigned the
  unassigned non-pilot scenario with the closest routed-pair count (ties: ascending
  `scenario_key`), without replacement. Donors are single scenarios so the placebo's
  evidence is internally coherent — the strongest possible placebo: synthesis polish
  over wrong-but-coherent evidence. Donors are outside the pilot set so no document
  content appears twice in a reader packet (a within-pilot derangement would let a
  reader spot the duplicated content and unblind the pair).
- **Volume/shape match:** placebo N = min(real N for scenario *i*, donor pool size),
  selected by the section-4 algorithm on the donor pool (floor min(8, donor #accounts)).
  Any volume mismatch is printed loudly and recorded.
- Placebo citations point at the donor evidence actually supplied — PB0 runs on them
  symmetrically (fidelity is about honesty of quoting, not truth of routing).

## 7. Gates (frozen)

### PB0 — citation fidelity (mechanical, free, per document, hard gate)

Every `quote` in a document must match **verbatim after normalization** inside the
`trigger_text` or `response_text` of a pair **from the cited call** within that
document's own selected evidence set (real → real evidence; placebo → its donor
evidence). Normalization, frozen: Unicode NFKC on both sides; curly single/double
quotes → straight; en/em dashes → hyphen; whitespace runs → single space; strip.
Case-sensitive substring match; anything beyond that normalization = a failed quote.
**ONE fabricated, altered, or misattributed quote ⇒ that document FAILS PB0.**
Also mechanical: every cited `account` must equal the merged account map's domain for
the cited call. Overall **PB0 PASS = 5/5 real playbooks pass**; placebo PB0 results are
reported symmetrically. A real/placebo PB0 asymmetry in either direction is an
unexpected result → veto audit (code AND output) before it is believed.

### PB1 — evidence breadth (secondary, per real playbook)

A playbook passes PB1 iff (a) **every** key move cites ≥ min(3, #accounts in its
selected evidence) distinct account domains, AND (b) its full citation set (all
sections) spans ≥ 60% of the distinct accounts available in its selected evidence.
Overall PB1 PASS = ≥ 4/5 real playbooks pass. Failures are padding-flags in the
readout; PB1 never overrides PB2.

### PB2 — PRIMARY: blinded discrimination read

Instrument (the `layer_c_bench_w4_build.py` / `blind_read_powered.py` discipline):

- **Packet:** the 5 scenario pairs (real vs placebo rendered by ONE shared renderer,
  identical field order and formatting; sides A/B randomized per item by seeded RNG)
  plus **5 NEG control singles**, all 10 items shuffled together, one text file.
  Identities live only in a sealed KEY file readers never see.
- **NEG controls (scattered attention/validity controls):** each is a fake "playbook"
  assembled from sections drawn from ≥ 3 different synthesized documents, glued under
  the header of a non-pilot scenario, rendered by the same renderer. Question: "is this
  one coherent, usable coaching document for the named scenario? YES/NO". POS singles
  are deliberately omitted: with only 10 real documents, any POS would duplicate a
  paired document verbatim and unblind it (the W4-F1/F2 lesson applied); the omission
  is on the record here.
- **PAIR question (forced choice, no EQUAL):** "Which document is the genuine, usable
  coaching playbook for the named scenario — A or B?" Plus, per document and per key
  move: APPLY (concrete enough for a new CSM to attempt on their next call) / VAGUE —
  collected blind for PB3 before any key is opened.
- **Readers:** independent blinded readers on the SMALL model (sonnet), dispatched ONE
  AT A TIME, each with a fresh context containing only the packet. **Validity bar,
  frozen: a reader is VALID iff they answer every item AND reject ≥ 4/5 NEG controls.**
  Readers are dispatched until 3 VALID readers exist, max 5 dispatches; fewer than 3
  valid ⇒ PB2 VOID (a void is reported, not retried past 5).
- **Judgments are committed to files before the key is opened** — the key is unsealed
  only after all three valid judgment files exist.

**Scoring, frozen:** a scenario is REAL-PREFERRED iff ≥ 2 of the 3 valid readers pick
the real document. **PB2 WON = real preferred in ≥ 4/5 scenarios.** Descriptive
companions (recorded, never gating): per-reader tallies, unanimity count, pooled
15-vote sign test. If readers cannot beat the placebo, the synthesis is narration
wearing citations — the V1 failure, caught. **NULL IS A REAL RESULT.**

### PB3 — usefulness floor (secondary)

From the blind APPLY/VAGUE ratings: a key move counts APPLY iff ≥ 2/3 valid readers
rated it APPLY. Per real playbook, compute the APPLY share of its key moves.
**PB3 PASS = median APPLY share across the 5 real playbooks ≥ 0.5.** Reported;
flagged on failure; never decisive — PB2 is the decision gate.

## 8. House rules binding this trial (re-earned this week)

Gates frozen at approval; never adjusted after a result. One pre-run blind CODE audit of
the harness (strong model allowed), all findings fixed and recorded in §10 before any
synthesis call. Outcome audits/vetoes and blinded readers on sonnet; subagents ONE AT A
TIME. Any unexpected gate/placebo result ⇒ veto audit of code AND output before belief.
ZERO Postgres writes; `recordings/` and `recordings_pull_keep/` read-only; no published
artifact overwritten — all new artifacts under `Brain/artifacts/` with
started_at/pid/seed/shas, `--overwrite` refused by default. Long tasks via
`ops/run_visible.ps1` (`-ScriptArgs` is ONE string) + a completion ping, never polled.
Gateway needs the Joveo VPN. pytest file-by-file (spaCy OOM). Every chat call
`no_cache=True`. Budget: ask the operator before exceeding 50 chat calls.

## 9. Harness, artifacts, tests

`calibration/scenario_playbook_trial.py` with stages, each refusing to clobber existing
outputs: `--select` (substrate + PB-F0 + pick rule + evidence + donors →
`pb_evidence.json`), `--synthesize` (→ `pb_playbooks.json`, resumable per document),
`--pb0` (→ `pb_pb0_report.json`), `--build-read` (→ `pb_read_packet.txt` +
`pb_read_KEY.json`), `--score` (judgments `pb_judgments_r*.json` + key →
`pb_report.json`, incl. PB1/PB3). Seeded RNG throughout (one master seed, 42).
`tests/test_scenario_playbook_trial.py` covers the pure parts: pick rule + tie-breaks,
selection determinism + account floor, donor assignment, PB0 normalization/matching
(incl. misattribution and near-miss cases), PB1 arithmetic, packet build determinism +
key/sample separation, scoring incl. validity bar and the 4/5 rule. A `--smoke` mode
runs the path end-to-end with zero chat calls.

## 10. Pre-run blind code audit findings

Audit ran 2026-08-18 (strong model, blind: spec + harness + tests + precedents), after
a passing `--smoke` and 35 passing unit tests, **before any synthesis call**. Verdict:
effectively clean — 1 outcome-bearing finding, 4 notes. All fixed pre-run except N4
(no change needed):

- **F1 (outcome-bearing, FIXED):** `--score` accepted duplicate judgment files as
  distinct readers — a duplicated dispatch (same reader saved under two filenames)
  would cast 2 of 3 votes per scenario and could flip PB2 across the 4/5 line.
  Fixed: `score_read` now aborts unless all judgment files carry pairwise-distinct
  `reader` identities AND pairwise-distinct answer payloads (+ regression test).
- **N1 (FIXED):** the PB0 real/placebo-asymmetry veto banner fired only when real
  passed and placebo failed; the spec declares either direction unexpected. Now
  symmetric.
- **N2 (FIXED):** `pb_evidence.json` dropped the selection vectors' source texts
  (`unit_text`) the spec said it records. Now kept.
- **N3 (FIXED):** a map-call schema reject crashed instead of retrying like the reduce
  loop (budget was still counted correctly). Now retried up to the same attempt cap.
- **N4 (no change):** `build_substrate`'s scenario-text prewarm is technically an
  embed-capable path, but the spec freezes the substrate as exactly `build_substrate`,
  the frozen taxonomy's texts are already cached (no-op in practice), and the §2
  zero-spend invariant is scoped to selection vectors, which load via the abort-on-miss
  cache reader.

The audit verified sound: blinding channels (one renderer, seeded side randomization,
no identity metadata in the packet), arm symmetry (identical prompts/validators/retry;
placebo truncation proven equivalent to running the frozen selection at the smaller N),
the PB0 matcher (own-evidence scoping, misattribution/account checks, symmetric
normalization), scoring (validity bar, majorities, 4/5 rule, PB3 conservatism, VOID
handling), budget counting (every POST counted, persisted pre-attempt, hard stop
enforced), and determinism (RNG-free `--select`, seed-42 `--build-read`, faithful
PB-F0 port). After fixes: 36/36 tests pass.

## 11. RESULTS (2026-08-18, all gates as frozen)

**Verdict by the frozen decision rule: PB0 FAIL ⇒ METHOD NOT VALIDATED.** PB2 WON and
survived a veto audit with one restriction; PB3 PASS; PB1 0/5 (flag). The binding
failure is verbatim-quote fidelity, precisely characterized below — not narration.

- **Substrate:** 12,444 routed pairs (3,977 old + 8,467 KEEP). **PB-F0 PASS 26/26.**
  Pilot (ranks 1/5/10/15/20 by routed-pair count): `multi_channel_spend_and_board_
  optimization` (1042p), `creative_approval_and_budget_phasing` (283p),
  `ats_api_integration_and_authentication` (187p), `trial_period_and_minimum_spend_
  negotiation` (108p), `publisher_mix_and_quality_review` (55p). Donors by count match:
  candidate_sourcing (371p), pixel_redirection (267p), expansion_market (183p),
  budget_timing (112p), outdated_career_site (55p). 50 pairs selected per document,
  16–30 accounts each (floor 8 cleared everywhere); exclusions negligible (≤34 no-acct,
  ≤5 no-clause per pool). `pb_evidence.json`.
- **Synthesis:** 10 documents in **32 of 50 budgeted chat attempts** (2 reduce-stage
  schema rejects, both recovered on retry), `gemini-3.5-flash-lite`, temp 0.2,
  `no_cache=True` throughout. `pb_playbooks.json`.
- **PB0 — FAIL (4/5 real):** real docs pass except `publisher_mix::real` (1 altered
  quote of 16). Placebos, symmetric: **1/5 pass** (3+3+3+5 bad quotes). **Veto audit of
  code AND output (frozen rule, run before believing):** every one of the 16 failing
  quotes has a near match (difflib ratio 0.88–0.995) in the correct cited call; exact
  diffs are model edits — dropped stutters/fillers ("the the"→"The", dropped "Right?"),
  one-word swaps ("That"→"This"), one splice — not normalization gaps and not matcher
  bugs (scoping, normalization, and account checks hand-verified). **PB0 FAIL is REAL.**
  Real-arm alteration rate ≈ 1/71 quotes; placebo ≈ 14/70 — header-mismatched evidence
  induces ~14x more quote-smoothing, itself evidence that grounding pressure is doing
  work. `pb_pb0_report.json`.
- **PB1 — 0/5 (secondary, flag):** spans 0.25–0.48 vs the 0.60 bar, and every doc has
  ≥1 key move under the account floor. On the record: with 12–16 quotes per document
  against 19–30 available accounts, the 60% span bar is arithmetically near-unreachable
  at this document size — the bar as frozen measures document length as much as
  padding. Reported as frozen; never decisive.
- **PB2 — WON on the frozen instrument, sustained by veto audit WITH ONE RESTRICTION:**
  3/3 readers VALID (5/5 NEG rejected each); real preferred **5/5 scenarios, 15/15
  votes** (descriptive sign p = 6.1e-5). The seed-42 side draw DEGENERATED — real
  landed on side A in all 5 pairs (a 1/32 draw) — making position preference an
  unexcluded confound, so a veto audit ran: identical packet re-rendered with sides
  inverted (same seed path, byte-identical NEGs), 3 fresh sonnet readers. Flipped
  result: **4/5 scenarios real-preferred, 11/15 votes** (all readers valid) — content-
  tracking confirmed; pooled across both orientations 26/30 for real. **Restriction:**
  `multi_channel_spend_and_board_optimization` was chosen as side A unanimously in
  BOTH orientations — that pair is position/presentation-driven and counts as
  indistinguishable, not a real win. `pb_report.json`, `pb_veto_audit_flip.json`,
  `pb_read_packet_flip.txt` + KEY (audit instrument; the frozen instrument untouched).
- **PB3 — PASS:** blind APPLY shares 0.5 / 0.5 / 0.75 / 0.75 / 1.0, median **0.75**
  (bar 0.5).
- **Spend:** 32 Gemma chat attempts (≤ 50 frozen); 6 sonnet readers (3 frozen + 3 veto
  audit); zero Postgres writes; zero embedding spend; no published artifact touched.

**Reading (verdict unchanged by it):** the synthesis is NOT narration — blinded readers
separate real from placebo robustly in both orientations, and placebos degrade in a
measurable, mechanism-consistent way (more quote alteration, less scenario fit). The
method fails exactly where PB0 aims: the model smooths disfluent verbatim speech at a
~1.4% per-quote rate in the real arm, and one altered quote is (by frozen design) fatal.
That failure mode is mechanically detectable (PB0 found it for free) and plausibly
mechanically repairable (post-synthesis verbatim snapping of near-miss quotes before
finalization) — but that is a HARNESS change, i.e. a new pre-registered trial, not a
re-scoring of this one.
