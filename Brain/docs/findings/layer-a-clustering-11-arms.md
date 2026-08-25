# Layer A — Clustering Bench, 11 Arms (2026-08-16)

[Findings index](INDEX.md)

### Layer A clustering: 11 arms, and the ONE that beat the incumbent is a noise-rescue (2026-08-16)

Spec `docs/superpowers/specs/2026-08-16-layer-a-clustering-method-design.md` (pre-registered
before any arm ran; the P-arm selection rule frozen before the diagnostic probes were read).
Harness `calibration/clustering_bench.py` (+ `tests/test_clustering_bench.py`, 22 tests),
`calibration/diagnose_layer_a_noise.py`, `calibration/clustering_objective_audit.py`,
`calibration/read_clustering_samples.py`. **Zero chat calls, zero embedding requests, zero
Postgres writes** (cache-only embeddings, abort on miss). **Nothing wired to production.**

Question: routing was closed, so the CLUSTERS are the ceiling — the positive control reaches
only 20/38 and 47% of the pool is HDBSCAN noise. Can a different clustering do better?

| arm | GATE | lexical | description | subst cov | sign p |
| --- | --- | --- | --- | --- | --- |
| **rescue_centroid** | **28/38 = 74%** | 47% | 47% | 67.6% | **0.008 (+8/−0)** |
| agglo_cosine | 22/38 = 58% | 39% | 50% | 56.2% | 0.774 |
| **incumbent** | **20/38 = 53%** | **61%** | **61%** | 45.1% | — |
| p_eps050 / p_ms2 | 53% / 50% | 53% / 50% | 39% / 34% | 49.8% / 48.8% | 1.000 |
| leiden_knn | 42% | 50% | 45% | **98.4%** | 0.344 |
| jitter_s1 / jitter_s7 | 45% / 39% | 47% / 45% | 34% / 34% | 43.8% / 45.4% | — |
| p_eps075 *(frozen rule's pick)* | 24% | 34% | 37% | 67.7% | 0.013 |
| rescue_soft / rescue_placebo | 13% / 8% | 29% / 21% | — / 47% | 68.2% / 67.2% | 0.000 |
| placebo_shuffle | 0% | 0% | — | 45.1% | 0.000 |

- **The published control is 20/38 = 53%, NOT the 21/38 that was circulating.** Corrected
  against `null_test_taxonomy.json` and reproduced live. F2 (identity transfer) passed exactly.
- **F1 is clear by the widest margin this repo has recorded: `placebo_shuffle` scores 0/38 and
  0% lexical.** Compare routing's `placebo_centroid` at 3.3%. The gate is readable.
- **THE INCUMBENT'S 53% IS THE TOP OF ITS OWN UMAP-SEED BAND (39–53% at seeds 7/1/42).**
  Re-partitioning costs 3–5 scenarios. Never quote the seed-42 number as "the" incumbent level,
  and this is why F7 (a treatment must clear BOTH jitter seeds) exists.
- **`rescue_centroid` satisfies S1 and S2 and nothing else does.** It admits a noise turn into
  its nearest surviving cluster iff `cos(t, centroid_c) >= p25({cos(m, centroid_c)})` — a
  per-cluster property of the data, no global constant. **+8/−0: it gains 8 scenarios and loses
  none.** Substantive-turn coverage 45.1% → 67.6%.
- **F5 HAD A GAP AND IT IS NOW CLOSED — cite the LIFT, not the level.** F5 requires a winning
  STOCHASTIC arm to hold at two more seeds, and `STOCHASTIC` was coded `{"leiden_knn"}` because
  `rescue_centroid` has no RNG. But the arm is deterministic only GIVEN ITS INPUT, and its input
  is a seeded UMAP spanning 39–53%, so the 74% was measured on the best of three bases.
  **F5 guarded the arm's OWN randomness and missed INHERITED randomness — any rule that
  post-processes a stochastic stage needs this test.** Re-run free (the jitter memberships were
  already persisted) via arms `rescue_centroid_s{1,7}`:

  | UMAP seed | base | + rescue | lift | paired sign test |
  | --- | --- | --- | --- | --- |
  | 42 | 20/38 = 53% | 28/38 = 74% | +8 | +8/−0, p=0.0078 |
  | 1 | 17/38 = 45% | 26/38 = 68% | +9 | +11/−2, p=0.0225 |
  | 7 | 15/38 = 39% | 24/38 = 63% | +9 | +9/−0, p=0.0039 |

  **Lift stable at +8/+9/+9 and LARGER at the worse seeds** (the opposite of seed luck),
  significant independently at all three, and **the ranges DO NOT OVERLAP — rescued 24–28/38 vs
  base 15–20/38**, so the worst rescued seed beats the best unrescued one by 4 scenarios.
  Substantive coverage 67.6/68.4/68.4% vs bases 45.1/43.8/45.4%; F4 stays 10.2–11.9% at every
  seed. **74% was seed-42-flattered in its LEVEL; the EFFECT (~+8–9 scenarios, ~+23 coverage
  points on whatever base UMAP hands it) is a property of the rule.**
- **Its mandatory volume-matched placebo collapses to 3/38 = 8%**, so the gain is the SELECTION,
  not the volume — the comparison eight rounds of per-pair sink-rescue never had.
- **THE GATE IS PARTLY THIS ARM'S OWN OBJECTIVE FUNCTION, and the signature is visible in the
  table.** Gate and lexical track each other for every arm (53/61, 53/53, 50/50, 45/47, 42/50,
  39/45, 24/34, 13/29, 8/21, 0/0) and diverge for exactly one: `rescue_centroid`, 74 vs 47 —
  the only arm that selects members BY the statistic the gate measures. **Cite the direction,
  never the magnitude; +21 points is an upper bound.**
- **`rescue_centroid` ties its own random placebo under the `description` objective (47% vs 47%,
  both +3/−8) — and that null is the OBJECTIVE's defect, not the arm's.** Gemma wrote each
  description from samples of the INCUMBENT's cluster, so it anchors to the original content and
  penalises ANY membership change equally; both rescue arms change it by identical volume. **It
  measures how much a population CHANGED, not whether it changed well.** The asymmetry was
  written into the script's docstring before it ran ("if a rescue arm WINS here despite the
  anchoring that is strong; if it loses, the anchoring is a sufficient explanation"), which is
  the only reason the tie did not read as a refutation. The unanchored lexical objective DOES
  separate them, 47% vs 21%.
- **The blinded reading settles it: `rescue_centroid`'s added turns beat random 10 OF 10**
  (p≈0.002), including both items where the coin flip put it in slot A. `managing_uat_and_
  testing_phases` drew *"it's a 3 or 4 week testing, UAT kind of time"* against audio dropouts;
  `job_board_distribution` drew *"Indeed has $3 cost per API call"* against *"I've read a bunch
  on g two."* The rule admits real content.
- **THE FIRST READING WAS CONFOUNDED AND THE MISTAKE GENERALISES: for an arm that MODIFIES
  populations rather than partitions them, the unit of reading must be the MODIFICATION.**
  `rescue_centroid` keeps the incumbent's 245 clusters and only grows them, so sampling 10
  clusters per arm independently compares two random draws from the SAME cluster set — with ~2/3
  of clusters being sinks that measures which draw was junk-heavier. `--added` mode compares
  what each rule ADDS to the SAME scenario at the SAME count: symmetric filtering applied to a
  reading rather than to a metric.
- **Account-glue: the rescue INHERITS it, it does not create it.** Top-account share of ADDED
  turns over 86 coachable clusters — centroid 0.365, placebo 0.221, the clusters' OWN ORIGINALS
  0.471. More concentrated than random (57/86, p<0.0001) but LESS than the originals (only
  21/86 rise, p<0.0001); 5 clusters get >=80%-one-account additions against the originals' 17,
  and every one is already-documented (`tracking_pixels` = Uber 0.95–1.00, `managing_non_
  technical_stakeholders` = Banfield 1.00). On average it DILUTES concentration.
- **The frozen P-rule picked a loser (`p_eps075`, 24%) and that is pre-registration working.**
  Its probe row already looked bad; the rule was followed and the gate judged it.
- **`leiden_knn` is the one arm that breaks the coverage/quality trade every other arm obeys.**
  No noise class, as predicted: it assigns **98.4% of substantive turns** and still scores 42%,
  far above the other high-coverage arms (`rescue_soft` 68.2%/13%, `p_eps075` 67.7%/24%). Not a
  win, but the only cheap coverage on offer. γ scale-matched to 1e-2 (271 communities vs 245).
- **CPM's γ range CANNOT be guessed — it is compared against intra-community edge-weight
  density, so it depends on the graph's cosine scale.** A 500-vector probe shattered from 2
  communities to 0 across one decade. The grid spans 1e-6..1e1 and the run WARNS if the
  selection rule lands on an endpoint: a rule applied to a truncated domain silently returns the
  edge of the grid instead of the point it was asked for.
- **`agglo_cosine` ran fine** (2.3 GB condensed matrix, no MemoryError — "limited to a few
  thousand" is folklore) with the cleanest junk profile of any arm (F4 2.3%), but 58% is not
  significant (p=0.774) and it leaves 5 of 38 scenarios unrankable.
- **`rescue_soft` (HDBSCAN soft membership) is the anti-result to `rescue_centroid`:** near
  identical coverage (68.2%) and 13%. Same idea, different signal, opposite outcome — so
  "rescue works" is false as a general claim; only this rule works.
- **NO PRODUCTION CHANGE MAY CITE ANY OF THIS.** All gemini-embedding-2@3072 in TURN mode;
  production is local bge@768 in CLAUSE mode, where the noise pool, the centroid band and
  `merge_cosine_threshold` all differ. The honest next step is re-running `rescue_centroid`
  against the production embedder and unit before any `tuning.yaml` key is proposed.
- **Still open:** the 47% noise is only half-answered. `rescue_centroid` recovers noise into
  EXISTING scenarios and cannot create new ones, so the diagnostic's 268 subject-bearing
  noise-only clusters stay outside the taxonomy by construction of the transfer gate.

Diagnostic that motivated the arms (`calibration/diagnose_layer_a_noise.py`, artifact
`layer_a_noise_diagnostic.json`): **the noise pool is CLEANER than the kept pool — 22% of noise
is content-free vs 42% of clustered.** Backchannel clusters tightly ("yep yep" ×51); substantive
discussion is what gets discarded. 8,834 noise turns are substantive, and 4,574 of them sit
inside the member cosine band while HDBSCAN's own soft membership gives them max-prob p50=0.020.
**The loss happens in the UMAP→HDBSCAN stage, not in the content** — which is precisely why a
full-space cosine rule (`rescue_centroid`) recovers what a UMAP-space rule (`rescue_soft`) cannot.

