# Layer C clustering-method bench on the union corpus (2026-08-17, evening)

**Status: PRE-REGISTERED. Arms and gates frozen in this file BEFORE any arm ran.**
Handoff: `Brain/HANDOFF_EXPANDED_POOL_2026-08-17.md` §2 stage 2. Harness:
`calibration/layer_c_cluster_bench.py` (new). Tests: `tests/test_layer_c_cluster_bench.py`.
Zero chat calls, zero Postgres writes, embeddings cache-only. Runs REGARDLESS of stage 1's
verdict (stage 1 spec: `2026-08-17-expanded-pool-stage1-design.md`).

## 1. Question

Layer C's clusterer (UMAP+HDBSCAN) is the one never-benched stage. It discards ~42% of its
post-relevance pool at CONTENT PARITY (noise 26.3% content-free vs clustered-kept 27.3%),
and the blind read found ~half of even the best-supported milestones incoherent. Can a
different clustering method turn the same post-p40 clause pools into more, coherent,
support-clearing milestones — measured on the union corpus, where evidence is deepest?

## 2. Substrate

One in-process substrate shared by every arm: the stage-1 union pools (same parse, pairs,
routing, p40 filter — production functions). **F0-bench (mandatory validity gate): the
substrate's per-scenario post-filter clause pools must be list-identical to the stage-1
artifact `layer_bc_xp_union.json`'s `clause_pool`.** Any diff → harness bug, nothing
reportable. All arms cluster the IDENTICAL per-scenario `(clauses, vecs, calls, positions)`;
the support gate (`required_milestone_support`, distinct calls) and every downstream count
are computed by ONE shared function for all arms — symmetric by construction.

## 3. Arms (frozen; nothing may be added after a result is seen)

| arm | what varies | granularity rule (frozen) |
| --- | --- | --- |
| `c0` incumbent | production `_cluster_milestones` verbatim (UMAP seed 42 + HDBSCAN, production `min_cluster_size`) | production |
| `c0_s1`, `c0_s7` | incumbent at UMAP seeds 1, 7 | the seed-jitter NOISE FLOOR, not candidates |
| `agglo` | AgglomerativeClustering, cosine, average linkage, no noise class | scale-matched: n_clusters = c0's cluster count per scenario (Layer A bench precedent: γ scale-matching; a count copied from the incumbent is a granularity match, not an objective) |
| `leiden` | k-NN graph (k=15, cosine weights), Leiden CPM, no noise class | γ from grid 1e-6..1e1 (7 decades), per-scenario pick = smallest γ whose community count >= c0's cluster count; WARN if the rule lands on a grid endpoint (Layer A lesson) |
| `hdb_half`, `hdb_dbl` | incumbent pipeline, `min_cluster_size` at 0.5x / 2x production's resolved value (floor 3) — the never-swept knob | production otherwise |
| `hdb_raw` | HDBSCAN on the raw 3072-d unit vectors (no UMAP), production mcs | production caveat on record: raw-space at bge-768 hit 100% noise on 28/85 scenarios; this measures whether gemini@3072 escapes that |
| `rescue` | c0 labels + `rescue_centroid` (p25 member-cosine admission, `lcfr_common.rescue_assign`) | re-testable ONLY because the corpus changed — the old-corpus closure ("the noise pool does not contain the failing clusters' content") is a property of the old corpus |
| `rescue_plc` | c0 labels + volume-matched placebo (`lcfr_common.placebo_assign`, same count per cluster, random noise draw) | mandatory companion to `rescue` |

Seed variants for UMAP-inheriting treatment arms (F5 lesson — inherited randomness counts):
`hdb_half`, `hdb_dbl`, `rescue` are re-run on the seed-1 and seed-7 bases if and only if they
survive gates W1–W3 at seed 42 (they are deterministic GIVEN their base, like
`rescue_centroid` was). `agglo`, `leiden`, `hdb_raw` have no UMAP dependence and no RNG
(agglo, deterministic; leiden seeded 42, re-run at partition seeds 1, 7 if surviving).

The production-verbatim rule: `c0` calls `v2.layer_c._cluster_milestones` ITSELF. The seed
variants need a seed argument production does not expose, so a paraphrase
`_cluster_milestones_seeded` exists in the harness and is **F0-checked: at seed 42 it must
reproduce production's labels array exactly, per scenario** (within-process determinism is
documented). If that check fails, the seed variants are void; `c0` is unaffected.

## 4. Gates (frozen). A winner must clear ALL of W1–W5

- **W1 — noise rate down.** Share of post-filter clauses assigned to NO cluster, arm <
  incumbent (c0). For no-noise-class arms (agglo, leiden) this is 0 by construction — W1 is
  then reported as trivially-true and the arm's case rests entirely on W2–W5 (the Layer A
  bench's coverage/quality trade, stated up front).
- **W2 — merged <= the arm's own noise floor.** `match_milestones` (merge-aware) vs c0.
  Partitioner arms: merged count <= max(merged of c0_s1, c0_s7 vs c0) — the seed-jitter
  floor. `rescue`: merged <= `rescue_plc`'s merged vs c0. (The merge-blind trap, guarded.)
- **W3 — account-diversity lift not degraded.** Rev-4 paired sign test vs c0, ONE yardstick
  for all arms (the union corpus null of stage 1 — same corpus, arm-independent).
  DEGRADED = (down > up AND p < 0.05). A winner must not be degraded; an arm that
  IMPROVES lift (up > down, p < 0.05) is reported as such — that would be the first
  clustering-stage move of this metric ever.
- **W4 — blinded coherence read won.** Run ONLY for arms surviving W1–W3 (bounds subagent
  cost). Instrument: samples and answer key in separate files, judgments committed before
  the key is opened (`read_routed_samples_v2` discipline); items = milestone clause sets,
  paired arm-vs-c0 at matched support, plus scrambled negatives (real clauses from unrelated
  milestones glued — coherence destroyed, register preserved) and positive controls
  (highest-support c0 milestones — EXPECTED imperfect, ~half incoherent per the published
  blind read; the negatives are the instrument check, >= 80% rejected or the reader is
  void). WON = reader prefers the arm's member sets in >= 2/3 of paired items, n >= 12 pairs,
  sign test p < 0.05.
- **W5 — stability.** Every W1–W3 direction must hold on the seed-1 and seed-7 bases (for
  arms with any UMAP inheritance or RNG; see §3). The 74%-at-seed-42 lesson: a level
  measured on one base is the best of three unless proven otherwise.
  **W5 procedure (frozen pre-run, forced by the audit):** a re-run at base seed b must
  include `c0` itself at that base (the reference) and `rescue_plc` if rescue survived;
  the PARTITIONER W2 floor at a non-42 base is the base-42 seed-jitter floor (loaded from
  the base-42 report — the floor is a property of the incumbent's seed sensitivity,
  defined once); leiden's W5 variant re-runs with PARTITION seed = b (it has no UMAP).

## 5. Readouts (descriptive, pre-registered)

Per arm: milestone count, support_frac distribution, clusters-vs-noise split, per-scenario
outcome table, gained/lost/split/merged vs c0, account-lift distribution, wall time.
Content-parity check on whatever noise remains (content-free share of noise vs kept — the
motivating 26.3/27.3 measurement, re-taken on the union corpus). Everything is
gemini@3072 on the turn-mode `clean2_base` taxonomy: directions transfer, numbers do not;
no `tuning.yaml` change may cite this bench alone.

## 6. Provenance

Every artifact (`layer_bc_cb_<arm>.json`, scoreable by `score_layer_b_arms.py` unchanged)
carries started_at / pid / seed / base seed / width / corpus_sha / taxonomy_sha / tuning
block / the granularity value actually resolved per scenario (the leiden γ picked, the agglo
n_clusters, the hdbscan mcs). No published artifact is overwritten.

## Pre-run blind audit (2026-08-17, before any run)

One subagent audit, strict bar: 3 outcome-bearing findings, ALL FIXED pre-run — (1)
`score()` never gated on F0-SEED failure, so void jitter arms could silently set the W2
floor (now dropped loudly); (2) no substrate identity cross-check between arms, so a
partial `--arms --overwrite` re-run after the corpus changed would score a corpus diff as
an arm effect (now corpus_sha/taxonomy_sha asserted against c0); (3) the W5 procedure as
documented was unscoreable (no c0 at the new base, no floor definition off base 42) — the
frozen W5 procedure above is the fix. Hardening also applied: leiden partition seed follows
`--base-seed` (its W5 was unrunnable); agglo/leiden are SKIPPED, not clamped 0→1, where c0
found zero clusters (the clamp manufactured a gained whole-pool milestone exactly where the
incumbent failed); hard-cap binds are flagged loudly (bench never truncates, symmetric);
the all-noise outcome is labelled `fallback_no_clusters`, matching production. Verified
clean: skip symmetry, seeded-paraphrase constructor identity, rescue index translation and
the numpy-Generator placebo contract (checked live), support-gate parity, pick_gamma rule
+ endpoint flags, two-pass W2 floors, emit closure binding, NaN symmetry.

## RESULTS

Run 2026-08-17 night, unattended. `--run` 14.0 min (10 arms, cache fully warm), W5 re-runs
7.6/6.8 min. **F0-bench PASS** (substrate list-identical to the stage-1 artifact) and
**F0-seed PASS at all three bases** — c0 is production verbatim, the jitter floor is valid.
Zero chat calls, zero Postgres. Leiden exceeded production's hard cap (15) in 4 scenarios
(16–28 milestones; flagged, untruncated, symmetric). No leiden γ landed on a grid endpoint.

**Gate table (base 42):** c0 = 128 ms / 35.0% noise; seed-jitter merge floor 22.

| arm | ms | noise% | merged | gained | lift up/dn (p) | W1 | W2 | W3 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| c0_s1 / c0_s7 | 137 / 124 | 37.5 / 37.4 | 16 / 22 | 36 / 27 | — | (floor arms) | | |
| agglo | 43 | 0.0 | **121** | 12 | 16/10 (.33) | Y | **n** | Y |
| leiden | 251 | 0.0 | 2 | 196 | 11/10 (1.0) | Y* | Y | Y |
| hdb_half | 155 | 32.8 | 11 | 74 | 11/10 (1.0) | Y | Y | Y |
| hdb_dbl | 73 | 50.5 | 47 | 16 | 13/10 (.68) | **n** | **n** | Y |
| hdb_raw | 5 | **96.1** | 4 | 2 | 3/1 (.63) | **n** | Y | Y |
| rescue | 134 | 22.1 | 0 | 6 | 13/8 (.38) | Y | Y | Y |
| rescue_plc | 138 | 22.1 | 0 | 10 | 12/8 (.50) | (placebo) | | |

(*trivially-true, no noise class.) `hdb_raw`'s bge-768 pathology persists at gemini@3072
(96.1% noise). `agglo` at matched cluster count merges 121 of c0's 128 milestones into
blobs — cosine-average linkage produces one giant cluster + satellites. No arm IMPROVED
lift (that would have been the first clustering-stage move of the metric ever); W3 passed
everywhere as not-degraded. **W1–W3 survivors: leiden, hdb_half, rescue.**

**W5 (seeds 1 and 7, c0 + survivors + rescue_plc, F0s PASS both):** every W1–W3 direction
held at both seeds for all three survivors. Texture for the record: hdb_half's W1 margin
was −2.2pp / −5.1pp / −0.6pp (thin at seed 7); its merged stayed far under floor (11/10/2).
Leiden's lift sign swings freely (11/10 → 8/13 → 14/7) — noise around a null. Rescue
remained aggregate-indistinguishable from its placebo at every seed (placebo out-gained it
10-vs-6, 15-vs-9, 15-vs-10).

**W4 blinded coherence read** (instrument: `calibration/layer_c_bench_w4_build.py` —
pre-run blind audit found 4 outcome-bearing defects, all fixed and recorded in its
docstring: identical-twin pairs, metadata-separable controls, rescue gate-crossing
exclusion put on the record, unequal bullet counts; 15 pairs + 8 pos + 8 neg per packet;
3 independent blinded readers, judgments committed before the key was opened):

- **Instrument VALID:** all 3 readers rejected 8/8 scrambled negatives in all 3 packets;
  inter-reader agreement ~92%.
- **leiden NOT WON — 5 arm / 8 c0 / 2 tie (frac 0.33, p=0.58).** Readers preferred the
  INCUMBENT's clusters. The 196 gained milestones are fragmentation, not recovered
  structure.
- **hdb_half NOT WON — 6 / 8 / 1 (frac 0.40, p=0.79).** Same direction.
- **rescue NOT WON — 10 / 5 / 0 (frac 0.667, p=0.30).** Its admitted clauses ARE
  preferred over the placebo's (the 12/12 selection-quality finding replicates
  directionally) but nowhere near significance at n=15, and every aggregate is
  placebo-equal. Estimand restriction on record: 6 gate-crossing clusters (≤376 clauses)
  were excluded from the read (artifacts persist surviving milestones only).
- **Positive controls, the sharpest number of the night:** readers accepted only 0–3 of 8
  of c0's HIGHEST-SUPPORT milestones as coherent moves. The published "~half incoherent"
  blind-read finding replicates on the union corpus, harsher (readers this strict still
  rejected 100% of negatives — the strictness is discrimination, not noise).

**VERDICT: NO WINNER. The incumbent stands — by forfeit, not by merit.** None of the 8
frozen alternatives turned the same post-p40 pools into more coherent, support-clearing
milestones; the two partitioner survivors LOST the coherence read to the incumbent, and
the incumbent's own best milestones fail an audited coherence read 5–8 times out of 8.
Combined with stage 1's G-XP2 NULL (same night, same substrate): neither data volume nor
any tried clustering method moves account-diversity lift or coherence. The binding
constraint now looks like the POOLING UNIT itself — response clauses at this granularity
do not contain cluster-recoverable coaching moves at the rate the pipeline assumes — and
that question (upstream of the partitioner) is the pre-registration-worthy next target.
