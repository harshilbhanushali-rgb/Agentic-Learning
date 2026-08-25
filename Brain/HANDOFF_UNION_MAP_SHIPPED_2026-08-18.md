# HANDOFF — the union map SHIPPED; next is the routing A/B (2026-08-18, late night)

Supersedes `HANDOFF_TAXONOMY_REBUILD_2026-08-18.md` (executed to completion this
session). Read `docs/superpowers/specs/2026-08-18-union-taxonomy-rebuild-design.md`
§9–§10 for the full audited chronology and
`docs/findings/union-taxonomy-rebuild.md` for the finding.

## 0. STATE OF THE WORLD (settled tonight — do not re-derive)

1. **THE MAP IS `union_base`** — `artifacts/adjudication_ab_union_base.json`: 34
   coachable scenarios + sinks, adjudicated over the UN-rescued seed-42 clustering of
   the 58,002-turn union corpus (`recordings/` + `recordings_pull_keep/`, T0-anchored
   at exactly 20,788 old CLIENT turns). Memberships: `union_clusters.json` →
   `idxs_base`, joined by `cluster_id`. It passed ALL FOUR frozen taxonomy gates
   (G-R4 10/12, veto-audited) AND playbook validation (PB0 5/5, PB2 4/5 pooled 11–4,
   PB3 0.80). **It is the playbook substrate.**
2. **The RESCUED arm is retired** — failed G-R4 8/12 (veto-audited, substantive).
   `rescue_centroid` is now closed a FOURTH time, this time on the playbook yardstick
   it was revived for. Its full record stays on disk (`adjudication_ab_union_rescued.
   json`, `union_gates_g1/g2g3/g4.json`). Do not reopen without a NEW mechanism
   hypothesis.
3. **clean2_base is superseded as the map** (26 scenarios, old corpus only) but remains
   the frozen G-R1 reference and the pilot-trial substrate. Nothing clean2_*/pb_*/pbs_*
   was touched.
4. **Five real playbooks on the new map exist**: `pbv_playbooks_snapped.json` (with
   `pbv_pb0_report.json`, `pbv_report.json`). These are product-shaped output.
5. **Synthesis model facts (measured tonight, do not relearn):** flash-lite breaks on
   incoherent/fragmented evidence (1-quote moves vs the 2–4 schema); `gemini-3.5-flash`
   `reasoning_effort=low` fixes it (`trial_gateway.chat_json` now takes
   `reasoning_effort`); `high` is UNREACHABLE via the gateway (thinking shares
   max_tokens + LiteLLM's server-side 120s cap → HTTP 408). Any "distinct accounts"
   REQUIREMENT wording breaks flash-lite's schema compliance — three variants on
   record; keep it a preference, report PB1.

## 1. THE NEXT MOVE (pre-registered by name in spec §7; PV passed so it is LIVE)

**Three-arm routing A/B on the playbook yardstick**: `concat` (control, production) vs
`keyphrases` (`scenario_vector_mode`) vs `r1 membership-lookup + description fallback`.
Needs its OWN spec with frozen gates BEFORE any code — the standing routing bar ("no
routing change until an instrument can rank methods across population shapes") falls
only to a pre-registered playbook-yardstick win. ~30–45 chat calls per added arm.
After routing: full playbook scale-up (~3 calls/scenario × 34) + Layer D coarse-check
derivation from the playbooks' scorable checks.

**OPTIONAL, operator raised 2026-08-19, needs operator approval to pre-register:** a
"rescued map + reasoning-model synthesis" arm — the one mechanism hypothesis the four
rescue closures never tested (tonight was the first night a reasoning model was in the
loop). Cheap because the rescued adjudication is already paid
(`adjudication_ab_union_rescued.json`): route vs the rescued map, synthesize the same
pilot scenarios with flash-low, blinded head-to-head vs the base map's playbooks.
Fold into the routing spec as an arm or run after it — never instead of it. The
clause-vs-turn question stays CLOSED (structural, model-independent; see
`docs/findings/layer-a-pool-unit-1.md`).

## 2. MACHINERY THAT NOW EXISTS (reuse; all blind-audited pre-run, spec §9)

| need | use |
| --- | --- |
| union pool + T0 anchor | `calibration/union_pool_fetch.py` (`build_union_pool`, `load_t0`; old block leads — union idx i == old idx i < 20,788, sha-anchored) |
| the shipped clustering | `union_clusters.json` via `adjudication_ab.load_persisted_clusters(art, "base", ...)` |
| adjudication on persisted clusters | `adjudication_ab.py --clusters-from --membership --budget` (multi-dir `--recordings`, pre-POST attempt accounting) |
| taxonomy gates incl. blinded read | `calibration/union_taxonomy_gates.py --arm base` (arm-parameterized paths) |
| PV pipeline on any map | `calibration/playbook_validation.py` (rebind TAXONOMY; bounded top-up; reasoning-model transport notes inline) |
| substrate routing | `playbook_validation.build_pv_substrate` (union parse → pairs → prewarm → shim → production assign_scenarios) |

## 3. HOUSE RULES (unchanged, all held tonight)

Frozen gates pre-registered before code; blind CODE audit per harness before spend;
veto-audit unexpected results (two fired tonight — one FAIL and one PASS — both stood);
subagents one at a time, readers/outcome audits sonnet; `no_cache=True` every chat
call; never batch embeddings; VPN for the gateway; `run_visible.ps1` + UTF-16 logs
(iconv before grep); ZERO Postgres writes; never overwrite published artifacts (now
also: `union_*`, `pbv_*` are published); pytest file-by-file; a null is a real result.

## 4. SPEND RECORD (tonight)

614 adjudication (307 × 2 arms, 0 failures) + 100 PV attempts (62 final + 38 across
three abandoned prompt states, preserved as `pbv_playbooks_v*_abandoned.json`) = 714
chat calls. Embedding: ~1.6k texts. The 37k-turn union fetch cost ZERO (cache was
already warm from stage 1 — check the cache before pricing a fetch).

## 5. THE ASK FOR THE NEXT SESSION

(1) Write the routing A/B spec (three arms above, playbook yardstick, frozen gates,
budget) and get operator approval. (2) Harness + tests + blind audit. (3) Run, gates
frozen, veto-audit surprises. (4) If a routing winner emerges: scale up playbooks on it
and derive Layer D checks. Update P&F, findings, INDEX, and leave a fresh handoff.
