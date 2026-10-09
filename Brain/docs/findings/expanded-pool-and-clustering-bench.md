# Expanded Pool (Data Effect) & Layer C Clustering Bench — both closed (2026-08-17)

[Findings index](INDEX.md)

### Stage 1: was DATA the constraint? NULL — it was not (2026-08-17, night)

Spec `docs/superpowers/specs/2026-08-17-expanded-pool-stage1-design.md` (gates frozen
pre-run). Harness `calibration/expanded_pool_stage1.py`. Corpus: published 393 calls +
690 KEEP calls (120 new accounts), taxonomy `clean2_base` FROZEN. Zero chat, zero
Postgres, embeddings cache-only (fetches verified 0-missing pre-run). Post-run audit on
operator request: CLEAN — every number reproduces from artifacts; the identical
primary/sensitivity 12/13 split is arithmetically forced (zero pairs flip sign; the
yardstick shift is 10x smaller than every pair's gap).

- **G-XP0 PASS** — 26/26 old-restricted prefilter pools byte-identical to the published
  control. **G-XP1 testable** — new pairs sink at 64.3% (old re-sank at its published
  57.9% in the same run); 3,024 new pairs reached coachable scenarios.
- **G-XP2 PRIMARY NULL: up=12 down=13 p=1.0** (own yardsticks; sensitivity frame agrees).
  The contrast that explains it: raw N_eff up=20 down=5 p=0.004, k median 26→71 —
  clusters reach ~3x more accounts, but EXACTLY at the rate random draws from the richer
  231-account pool predict (lift median fell 1.097→0.941). Not roster-confounded (4.6pp).
- **G-XP3: milestones 171→128** (merged=64 dominates; 18 scenarios down / 6 up). Audited
  mechanism: pools grew 2.4–4x, `min_cluster_size` hits its 25-clamp and
  `required_support` rises (6→19, 16→48) exactly where pools grew — the clusterer
  coarsens and the gate hardens together. The 60 gains are honest (45 new-data-necessary,
  50 new-account-backed) but are consolidation leftovers.
- All 33 failing candidates matched; 30 now clear the union gate; zero scenario flips.
- **Promotion of the 690 into production is NOT supported by this gate** (operator's
  decision). "The clusterer eats evidence faster than data supplies it" — pre-registered
  reading, now measured.

### The clustering bench: 8 arms vs UMAP+HDBSCAN, NO WINNER (2026-08-17, night)

Spec `docs/superpowers/specs/2026-08-17-layer-c-clustering-bench-design.md`. Harness
`calibration/layer_c_cluster_bench.py` — one substrate (F0-bench PASS vs the stage-1
artifact), one shared support gate, F0-seed PASS at bases 42/1/7. W4 instrument
`calibration/layer_c_bench_w4_build.py` (own pre-run audit: 4 outcome-bearing defects
fixed — identical-twin pairs, metadata-separable controls, rescue gate-crossing exclusion
put on record, unequal bullet counts).

- **Dead on gates:** `agglo` (merges 121/128 of c0's milestones at matched count),
  `hdb_dbl` (noise 50.5%), `hdb_raw` (96.1% noise at gemini@3072 — the bge-768 raw-space
  pathology is not an embedding-width artifact).
- **W1–W3 survivors** `leiden`, `hdb_half`, `rescue` held directions at seeds 1 and 7
  (W5) — then **both partitioners LOST the blinded coherence read to the incumbent**
  (leiden 5-8-2 frac 0.33; hdb_half 6-8-1 frac 0.40; instrument valid: 9/9 reader-packets
  rejected 8/8 scrambled negatives, ~92% inter-reader agreement). Leiden's +196 gained
  milestones are fragmentation, not structure.
- **rescue, third and final confirmation:** selection quality replicates (admitted clauses
  preferred 10-5-0 over placebo's, p=0.30 NOT WON) while every aggregate stays
  placebo-equal at every seed and the placebo out-gains it everywhere. Closed.
- **The positive controls are the sharpest number of the night:** readers strict enough to
  reject 100% of scrambled negatives accepted only **0–3 of 8** of the incumbent's
  highest-support milestones as coherent coaching moves. The published "~half incoherent"
  was optimistic; on the union corpus the pipeline's best output fails a coherence read
  5–8 times out of 8.
- No arm improved account-diversity lift (would have been the first ever).

### The combined lesson

Same night, same substrate: more data does not move lift (stage 1); a different
partitioner does not either, and every partition of the same pool has a low coherence
ceiling (bench). Routing (F10), intake filters (F1/F2), admission knobs, rescue, data
volume, and the clusterer are now ALL measured non-binding. The never-varied variable is
the **pooling unit** — response clauses at this granularity may not contain
cluster-recoverable coaching moves at the assumed rate. The Layer A pool-unit trial
(clause vs turn, shipped OFF) is the precedent; the Layer C analogue has never been run
and is the pre-registration-worthy next question. Everything above is gemini@3072 on the
turn-mode `clean2_base` taxonomy — directions transfer, numbers do not; no `tuning.yaml`
change may cite these results alone.

### The pool-unit trial: clause vs window vs turn, NULL (2026-08-18, overnight)

Spec `docs/superpowers/specs/2026-08-18-layer-c-pool-unit-design.md` (V0-V4 frozen
pre-code). Harness `calibration/layer_c_pool_unit.py`. The last untested variable —
prompted by the operator's catch that Layer A pools TURNS (clause pooling was convicted
there for posture contamination) while Layer C clusters CLAUSES. Canonical-membership
rule: every unit milestone resolves to its clause set, so all accounting and reads are
unit-fair by construction. V0 (production clause path == stage-1 pools) PASS at both
bases run.

- **u_turn: dead at the frozen stop rule** (36 ms vs floor 64) — whole-response vectors
  over-blur and distinct-call support collapses.
- **u_win: survived V1+V3 at base 42** (71 ms, noise 30.4% vs 35.0%, lift 16/10 — best
  direction ever seen at Layer C) **then lost the blinded read 0/15, p=0.0001**, three
  valid readers unanimous for the incumbent. Veto-audited before being believed
  (hand-recomputed exactly, mapping verified both directions, no blinding tell): REAL.
  Mechanism: windows drag neighbor clauses (status chatter, intro filler) into every
  displayed evidence set. Seed-1 readout buried it: 63 ms (under that base's floor 68),
  lift flipped 12/14 — the base-42 survivals were seed jitter.
- **Caveat on the record:** the read judges resolved clause SETS, so windows lost on
  composition; window grouping-decision quality per se is untested (anchor-clause-only
  display = a new instrument, pre-register it or drop the question).

**Program state after this: the pipeline-internal search space is exhausted.** Seven
closures — routing, intake filter, admission, rescue, data volume, partitioner, pooling
unit. The incumbent stands by forfeit; its best milestones still fail coherence reads.
Live moves are all outside the current shape (operator decisions): the gold-pair
embedding probe (does move-similarity exist in the vector space AT ALL — near-free,
decisive), the union-corpus taxonomy rebuild (Gemma spend), or LLM move-labeling before
clustering (new representation, new instrument, V1-narration lesson applies).

### Gold-pair probe: not move-blind (probably), but move recurrence is SPARSE (2026-08-18)

Harness `calibration/gold_pair_probe.py` (design/bars frozen in its docstring pre-data;
no standalone spec by operator instruction). Full narrative in PROBLEMS_AND_FIXES.md.

- **Math battery:** real geometric structure in every pool (modularity 0.41-0.54 vs 0.17
  null); weak Hopkins; small call-identity excess; lexical near-repeats nearly absent.
- **Labeled rounds:** round 1 void for power (1 gold pair; its 26-triplet print rejected
  as pseudo-replication). Round 2 (nominate-by-reading, blind 2-verifier confirmation,
  all attention controls passed): **8 gold same-move pairs vs 11 gold distractors, AUC
  0.966, p=0.0007 — formally UNDERPOWERED by the frozen n>=10 bar, not upgraded.**
- **Finding 1:** 11/11 observations across three instruments separate same-move from
  same-topic — the space is probably not move-blind; clustering's failure is not an
  embedding defect.
- **Finding 2 (the important one):** same-move recurrence at clause granularity is
  SPARSE, measured three independent ways. The milestone-as-recurring-clause-cluster
  target demands recurrence the corpus does not contain — retrospectively explaining the
  week of nulls better than any mechanism hypothesis. The scarce commodity is
  recurrence, not signal.
- Program implication: representation is usable (retrieval is sound); the TARGET is the
  question. Scenario-level playbooks (evidence-cited synthesis per scenario, coarser
  Layer D checks) fit both findings; operator decision pending.
