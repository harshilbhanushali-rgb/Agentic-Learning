# Brain rebuild on gemini-3.6-flash — built end to end, evaluated, ADOPTED (2026-10-10)

[Back to the index](INDEX.md)

**Question.** Rebuild the Brain into a fresh database with every change measured positive, on
`gemini-3.6-flash` @ `reasoning_effort=medium`, then evaluate whether it beats the live one.
Spec: `docs/superpowers/specs/2026-10-10-brain-rebuild-staged-design.md`. Runner:
`ops/rebuild_brain.py`. Operator choices: no gates between stages (evaluate once at the end);
Layer D NOT run.

**What could change.** Layers C and D already ran on 3.6-flash medium, so the only model change
was Layer A's adjudication (flash-lite). Clusters were NOT refit: clustering uses no LLM, the
corpus had not changed since the clusters were built (newest transcript 2026-08-17, clusters
2026-08-18), and a refit only adds launch-to-launch UMAP noise. The second change was the
gradability rule, which had been written into the base playbook prompt on 2026-08-25 but was
live on only 5 of 33 documents. Left off on the record: `sink_margin_delta`, a
`contract_and_legal_review` retry, the catch-all split proposal.

## Build

- **Layer A:** 307/307 clusters re-adjudicated, 0 failed, all served by gemini-3.6-flash →
  `union_base36`: **279 scenarios, 49 coachable** (live: 259 / 34). Of the 49, 27 are clusters the
  live map also called scenarios and **22 are clusters flash-lite had merged into an umbrella** —
  the catch-all problem `layer-abc-levers-for-layer-d.md` §2 named, addressed by the model alone.
- **Layer B:** 12,444 pairs; 6,863 coachable after content dedup (live 6,496).
- **Layer C:** 49 playbooks, 142 requests (exactly the no-retry estimate), 0 collapsed — including
  `contract_sow_and_legal_review_coordination`, the counterpart of the one scenario the live map
  could not support — PB0 every document, single-account moves 8.6% (live 9%). 540 selection
  vectors had to be bought: the playbook selection embeds clause units, not whole responses, and
  15 scenarios had never been selected before (a legitimate top-up, not an eroded cache).

## Evaluation (all blinded sonnet readers, one at a time; all readers passed their negatives)

| | live (`union_base`) | rebuilt (`union_base36`) |
| --- | --- | --- |
| G-R1 cohesion vs null | 100% | 100% |
| G-R2 sink share, new / old corpus | 47.3% / 48.1% | **45.0% / 43.9%** |
| G-R3 stranding | 34/34 | 49/49 |
| G-R4 coherence read | 10/12 | 10/12 (different packets — both pass, not rankable) |

**Routing head-to-head** (within one packet; 80% of coachable-relevant pairs change scenario,
mostly into the split-out scenarios): readers preferred the new label **34 vs 21** of 55 decided
(61.8%, two-sided binomial p = 0.10 — a lean, not decisive). By kind: sink → coachable (the new
map rescues a turn) **16 vs 2 for new**; coachable → sink (the new map discards one) **11 vs 7
for OLD** — its one clear weakness; coachable → other coachable 11 vs 8.

**Playbook head-to-head** (10 situations, regenerated vs the live document of the counterpart
scenario, counterbalanced): situations 6 vs 4 for new (chance level). Item level, pooled over 3
readers, same packet: criteria judged gradable **100% vs 91.5%**; quotes judged to demonstrate the
move **84% vs 80%** — the gradability rule doing what it was promoted for.

The three G-R4 readers returned byte-identical answers (plausible for 18 binary items; on the
record). Routing readers agreed 58/66 pairwise, playbook readers 315/332.

## Decision and switch

Operator ADOPTED the rebuild (2026-10-10). `Brain/.env` `DATABASE_URL` → the rebuilt database
(previous kept as `DATABASE_URL_PRE_REBUILD`); `serve_ask_naren.VECTOR_INDEX_NAME` and
`ship_layer_b.INDEX_3072` → `narens-brain-rebuild-3072`; no pinned IP (DNS verified for both
databases). Verified: `check_vector_coverage` 6,863/6,863; Ask Naren startup guard 1,000/1,000;
one live question answered and grounded (pair 1224, `down_funnel_ats_tracking_and_attribution`);
2,133 tests green.

**Not re-measured:** Ask Naren's answer accuracy (~80% on n=36) and intake accuracy were measured
on the previous Brain. Layer D has no verdicts on the rebuilt Brain. The production deployment
(`joveo/coder-pets-tray`) is switched separately.
