# Union-corpus taxonomy rebuild — the map that shipped (2026-08-18, night)

Spec (frozen pre-code, all gates evaluated as frozen):
`docs/superpowers/specs/2026-08-18-union-taxonomy-rebuild-design.md` — §9 holds the five
pre-run blind audits, §10 the full chronology. Handoff executed:
`HANDOFF_TAXONOMY_REBUILD_2026-08-18.md`.

**OUTCOME: `union_base` — the UN-rescued seed-42 clustering of the 58,002-turn union
corpus, adjudicated to 34 coachable scenarios — passed all four taxonomy gates AND the
playbook validation, and SHIPS as the playbook substrate.** The rescued arm — the one
the spec designated primary — failed the blinded coherence gate and is retired.

## The chain, with numbers

- **T0** old corpus exactly 20,788 CLIENT turns (hard equality). New corpus measured
  **37,214** turns — the spec's ~12–13k estimate was wrong ~2.9x (690 calls at the same
  ~54 turns/call as the old corpus). Union 58,002 turns / 1,059 calls.
- **Fetch: zero spend.** All 52,510 distinct texts were already in the gateway cache
  (paid during expanded-pool stage 1). The feared 37k-request fetch never happened.
- **Stage B (free):** 600 raw → 511 merged @0.97 → **307 surviving clusters**;
  `rescue_centroid` admitted 13,902 turns (noise 59.0%→35.1%). Both membership sets
  persisted; Stage C loaded them rather than re-fitting (no cross-launch UMAP risk).
- **Adjudication:** rescued arm 35 coachable / base arm 34 coachable, each 307/307
  clusters, **0 failed rows**, model uniform, T2 PASS both.
- **Gates, rescued arm:** G-R1 PASS (35/35 vs clean2_base 26/26 — the cohesion-vs-null
  instrument saturates at 100% on BOTH maps; null band 0.629–0.648, real margins
  +0.019 min), G-R2 PASS (new-corpus sink **49.1%** vs the motivating 64.3%; old
  48.2%), G-R3 PASS (35/35) — **G-R4 FAIL 8/12** (bar ≥9/12), veto-audited: REAL.
  Failures were substantive umbrella/fragment clusters, NOT explained by rescued-turn
  share (failing scenarios spanned 14–74% rescued; passers included 66%).
- **Gates, fallback base arm (operator-chosen, §1's pre-registered option):** G-R1
  34/34, G-R2 47.3%/48.1%, G-R3 34/34, **G-R4 PASS 10/12**, veto-audited (arm isolation
  proven to the literal transcript text; `non_technical_stakeholder_translation` scored
  0/3 under BOTH arms' independent readers — cross-arm replication).
- **PV on `union_base`:** PB0(snapped) **5/5**; PB2 **WON 4/5** (pooled 11–4, 4
  unanimous; all readers rejected 5/5 negatives); PB3 median 0.80; PB1 0/5 (standing
  non-decisive flag). **PV GATE PASS.**

## What died, and what it means

1. **The rescue is closed for the fourth and final time — this time on the product
   yardstick it was revived for.** §0.1 reopened rescue_centroid because its measured
   coverage wins (45→68% substantive coverage, 96→133 calls/scenario) were "exactly
   what playbook evidence selection consumes". The gates answered: the extra turns are
   what blinded readers see as incoherence (8/12 vs 10/12 on the same corpus, same
   procedure). The spec's own caveat ("the gates, not the rescue's pedigree, decide")
   did the work. Do not reopen without a NEW mechanism hypothesis.
2. **The map WAS the bottleneck, as G-XP1 said.** Same routing, same corpus: sink share
   fell 64.3%→49.1% (new pairs) purely by rebuilding the map on union data, and the old
   corpus improved too (57.9%→48.1%). More scenarios (26→34), all G-R3 floors cleared
   at 100%.
3. **Incoherent clusters are unsynthesizable — the gates agree with each other.** The
   frozen PV pick rule sampled `landing_page_and_conversion_setup` (a G-R4 0/3
   scenario). Its real playbook failed synthesis 6 straight times under
   gemini-3.5-flash-lite: fragmented evidence → 1-quote candidate moves → the 2-4-
   entries schema rejects. The coherence read and the synthesis schema detect the same
   defect through different instruments.
4. **A reasoning model rescues marginal scenarios.** `gemini-3.5-flash` at
   `reasoning_effort=low` synthesized that same document on its FIRST attempt, and the
   blinded readers then preferred it 2/3 with apply share 1.00. Gateway constraints,
   measured: `high` is unreachable (thinking shares max_tokens → truncation at 16,384;
   LiteLLM's server-side 120s cap → HTTP 408 regardless of client settings); `low`
   fits.
5. **Prompt-hardening lesson (three failed wordings on record):** any REQUIREMENT
   phrasing of "distinct accounts per move" makes flash-lite sacrifice the 2-quote
   schema minimum instead — including with explicit precedence and merge-or-drop
   instructions. The pilot's "prefer" wording plus post-hoc reporting (PB1) is the
   right division of labor.

## Costs

614 adjudication calls (307 × 2 arms) + 100 PV attempts (62 final + 38 across three
abandoned prompt-wording states, all preserved as `pbv_playbooks_v*_abandoned.json`) =
**714 chat calls**; embedding ~1.6k texts (2 prewarms + 1,123 selection top-up). Zero
Postgres writes; no published artifact touched.

## Shipped artifacts

`adjudication_ab_union_base.json` (THE map), `union_clusters.json` (both membership
sets; `idxs_base` is the shipped clustering), `union_pool_t0.json`,
`union_gates_fallback_*` (the passing gate suite), `pbv_*` (PV incl. 5 real playbooks
in `pbv_playbooks_snapped.json`), plus the rescued arm's full failed-gate record
(`adjudication_ab_union_rescued.json`, `union_gates_g1/g2g3/g4.json`).

## Pre-registered next steps (spec §7 — PV passed, so these are live)

1. **Three-arm routing A/B on the playbook yardstick** (`concat` vs `keyphrases` vs
   `r1 membership-lookup + description fallback`) — own spec, own frozen gates.
2. **Full playbook scale-up** on the winning routing (~3 calls/scenario × 34) + Layer D
   coarse-check derivation.
