# Brain rebuild into a fresh database, built end to end, evaluated at the end (2026-10-10)

## What and why

Operator request (2026-10-10): rebuild the Brain into an empty Neon database
(`DATABASE_URL_REBUILD`) with every change that was measured positive, on
`gemini-3.6-flash` @ `reasoning_effort=medium` for all layers, and then evaluate whether
the new Brain is better than the live one. **Operator decision: no quality gates between
stages -- build the whole thing, evaluate once at the end.**

Layers C and D already run on that model, so the only MODEL change is Layer A's
adjudication (`gemini-3.5-flash-lite` today). The other change is the gradability rule for
playbooks: live on 5 of 33 documents, and since 2026-08-25 written into the base prompt
(`scenario_playbook_trial.MAP_RULES` / `REDUCE_RULES`), so every regenerated playbook
carries it.

Left OFF on the record and NOT part of this rebuild: `sink_margin_delta` (needs a judged
sample > 80 turns), a `contract_and_legal_review` retry ("more evidence or permanent
exclusion -- not a retry"), the catch-all split proposal (untested, separate experiment).

Production is never written: new database, new Pinecone index `narens-brain-rebuild-3072`,
`checkpoints_rebuild.db`, rebuild-prefixed artifacts. Ask Naren keeps reading live.
Runner: `ops/rebuild_brain.py`.

## The build (`rebuild_brain.py all`)

| step | what | requests |
| --- | --- | --- |
| a | the live map's own 307 clusters (`union_clusters.json`, membership `base`, no refit) re-adjudicated -> `union_base36`; G-R1 and G-R2/G-R3 measured | ~307 + ~259 embeds |
| b | `init_db`, `ship_union_taxonomy`, `ship_layer_b` into the rebuild DB and index | none |
| c | `playbook_backfill.py` for every coachable scenario (minus the exclusion), loaded live | ~100-150 |
| d | Layer D pairwise: her calls, then Naren's benchmark | ~800-1,000 |
| eval-build | every blind-read packet below | none |

Only INTEGRITY checks stop the build -- they mean the run is broken, not that it lost:
T2 failed-row share > 5%; Layer B sink share outside G-R2's measured share +/- 3pp; the
playbook loader's write verification (G-P1..P5).

## The evaluation (after the build)

All within-packet comparisons, because levels never compare across packets (findings §13:
the same items scored 84% then 17% under two framings). Blinded sonnet readers, one at a time.

1. **Taxonomy** -- the frozen union-rebuild gates on `union_base36`, beside the live map's
   recorded results (`union_gates_fallback_report.json`): G-R1 cohesion, G-R2 sink share,
   G-R3 stranding, G-R4 coherence read (3 readers).
2. **Routing head-to-head** (`rebuild_stage_a_h2h.py`) -- every union pair routed under both
   maps; pairs whose scenario changed (or whose coachability flipped) are sampled, 60 +
   6 negatives; readers pick which label fits the client turn. Readout: new-label share of
   decided items, two-sided binomial p. If < 5% of coachable pairs change, the maps route alike.
3. **Playbook head-to-head** (`rebuild_stage_c_h2h.py`) -- 10 situations, regenerated
   document vs the live document of the same (or counterpart) scenario, counterbalanced;
   readers judge every criterion (gradable?) and quote (demonstrates the move?), 5 planted
   negatives. Readout: situations won by each side; census floors (PB0, single-account
   share, coverage).
4. **Layer D** -- the say run (after a two-reader move classification of the regenerated
   moves), a blinded output audit of the new verdicts (gate >= 70%, as shipped), and the
   combined report side by side with live: rankable cells, tie share, decided verdicts per
   cell, decidable repertoire cells, top priorities.

The new Brain is reported **better** where the head-to-heads favour it and the integrity
gates hold; switching Ask Naren or anything else to it is a separate operator decision.
