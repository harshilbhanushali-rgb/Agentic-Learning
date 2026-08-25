# Layer A — Primary-Topic Hierarchy & Adjudication A/B (2026-07-30/31, 2026-08-16)

[Findings index](INDEX.md)

### Layer A primary_topic hierarchy + Layer B two-stage matching (2026-07-30/31)

Designs: `docs/superpowers/specs/2026-07-30-layer-a-topic-hierarchy-design.md`, `2026-07-30-layer-b-two-stage-matching-design.md`, `2026-07-31-layer-a-primary-topic-coachability-split-design.md`.

Problem: `scenarios.primary_topic` was never a real grouping — free text Gemma reinvented per subtopic cluster, no dedup or shared identity across clusters. This work gives it a real parent entity (`primary_topics` table) and, separately, explores whether matching triggers to a `primary_topic` first and a subtopic second (instead of flat subtopic matching) improves Layer B assignment.

**Status — what's actually live vs still a harness, as of 2026-07-31:**

- **Production / wired in:** `v2/layer_a.py::_finalize_primary_topics` builds `primary_topics` rows via `topic_grouping.group_post_hoc`/`group_nested` + `split_by_coachability` (the coachability-mixing fix) + `tighten_coachable_groups` (2026-08-02, see below). This runs in every V2 pipeline execution now, including the full-corpus run described below.
- **NOT production — calibration-only:** `v1/layer_b.py::assign_scenarios_two_stage(strategy=...)` (strict/soft/fallback) is NOT called anywhere in the real pipeline. Its own docstring says so explicitly: *"UNCALIBRATED as of 2026-07-30 — primary_topics is empty until a real [run]... vectors in tests/test_two_stage_matching.py, never dry-run-compared."* The only caller today is `calibration/compare_matching_subset.py`, a standalone comparison harness. Production `assign_scenarios` (flat matching) is unchanged. Adopting a strategy means wiring it into `assign_scenarios` (or its caller) deliberately — it will not happen by itself.
- **Zero-Gemma double vector population:** primary_topic vectors (`build_primary_topic_vecs`) are a separate embedded population from scenario vectors, not a subset or reuse — expect `embed_cache.db` growth from this alone the first time a corpus runs through it.

**First full-corpus production run (2026-08-02), `public` schema:** 416 calls, 157 scenarios (81 coachable / 66 mechanics / 10 logistics), 80 `primary_topics`, 4605 kb_pairs, 80 rubrics — `grouping_method: nested` throughout. This is the run that surfaced the two bugs below; both are subtopic/label bugs in `_finalize_primary_topics`, not adjudication or matching bugs.

- **Loose primary-topic grouping fused unrelated coachable scenarios into a mega-blob — confirmed, then fixed.** 26% of coachable scenarios (21 of 81) landed in one `client_discovery_and_requirements` primary_topic spanning budget disclosure, ATS integration, job-board ecosystem, URL redirection config, and market landscape — content with nothing in common beyond a generic "discovery" direction under centroid averaging, the same failure mode `merge_cosine_threshold`'s own calibration already documents above one level down the hierarchy. Fix: `shared/topic_grouping.py::tighten_coachable_groups(groups, tight_threshold)` re-clusters every all-coachable group at the tight threshold (reuses `merge_cosine_threshold`, no new tuning key) instead of the loose one; sinks are left untouched (coarse sink grouping is harmless). Deliberately **not** gated on group size — a member-count ceiling is the exact `MAX_CLUSTERS=150` anti-pattern this file already warns against; coachability alone decides eligibility, so a small cohesive group just survives unchanged. Validated Gemma-free against the real 416-call corpus via `calibration/dry_run_layer_a.py`'s own clustering path (zero Gemma calls, zero DB writes, warm embed cache): 59 primary-topic groups (largest 28, an equivalent mega-blob) → 146 groups (largest 4), with the surviving multi-member groups reading as genuinely coherent themes on inspection.
- **Gemma-generated primary_topic labels can collide across separate batch calls.** `_label_primary_topics_batch` batches `_TOPIC_LABEL_BATCH_SIZE` groups per Gemma call, so two different calls can independently invent the same label string for unrelated groups — confirmed in production ("Positive Client Sentiment" assigned to both a 5-member and a 1-member group). `primary_topic_key` already had a uniqueness-suffix guard; the human-readable `label` did not. Fixed with the same suffix treatment (`"Label (1)"` / `"Label (2)"`) applied post-batch.

**150-call subset validation (post coachability-split + gemma-retry fix), measured 2026-07-31** — snapshotted to schema `subset150_postfix_20260731` (150 calls, 71 scenarios, 34 primary_topics, 1642 kb_pairs, 35 rubrics):

- Two-stage `fallback` strategy vs flat: 86.6% top-1 agreement, 86.6% recall-proxy, mean Jaccard 0.824 — better than `strict` (79.6%/79.6%/0.760) and roughly matching `soft` (85.9%/91.6%/0.827) but with fewer average matches (1.19 vs 1.29).
- `two_stage_fallback_floor` sweep (857 non-sink pairs): floor 0.30–0.40 barely reroutes anything (reroute% <0.5%, agreement ~79.6-79.8%); floor 0.50 reroutes 9.6% and lifts agreement to 86.6%; floor 0.60+ reroutes 42%+ and pushes agreement past 99% (at which point it's converging back toward flat matching, so the floor is trading away whatever benefit two-stage was supposed to add). **No floor has been chosen for production** — this sweep is input to that decision, not a decision itself.
- This was subset-scale only. Every other threshold in this codebase shifted between subset and full-corpus calibration before (`relative_margin`, `merge_cosine_threshold`) — the equivalent full-416-call validation is the next real step before treating any of these numbers as calibrated.

**Full-416-call validation, measured 2026-08-03 (`calibration/compare_matching_subset.py --sweep-floor` against the live `public` schema — no code change needed, the script has no hardcoded subset filter): the subset numbers did not hold, and got worse, not better.** Recall-proxy dropped for every strategy: strict 69.9%→61.3%, soft 83.6%→77.0%, fallback(floor 0.50) 82.1%→71.4%. Mechanically consistent with the design's own "central risk" — going from 69 scenarios/28 primary_topics (subset) to 157/80 (full corpus) gives the coarse first stage far more ways to pick the wrong parent category. The floor-sweep gaming pathology also reproduces at full scale (floor 0.50→11.5% reroute/71.4% agreement; floor 0.70→59.3% reroute/100% agreement — still just reverting to flat, not getting more accurate). **Verdict: full-scale data argues against adopting two-stage matching, not for it.** `matching_strategy` stays `flat`. See design spec's "Status update 4" for full detail.


---

### Adjudication A/B: does the noise-rescue change the TAXONOMY? Mostly no (2026-08-16)

Harness `calibration/adjudication_ab.py` (+ `tests/test_adjudication_ab.py`, 20 tests), driver
`ops/run_adjudication_ab.py`, readers `calibration/read_scenario_quality.py` /
`read_clean_clusters.py`. Zero Postgres writes. **Replaces `trial_adjudicate_gemini.py` for any
comparison** — see `HARNESS_DELETION_PROPOSAL_2026-08-16.md`.

**RESULT, cleaned corpus (20,788 turns, 224 clusters, 3 arms x ~224 sequential calls):**

| arm | scenarios | merged | mech | logi | coachable (rebased) |
| --- | --- | --- | --- | --- | --- |
| clean_base_a | 26 | 61 | 128 | 9 | 16.0% |
| clean_base_b | 28 | 58 | 131 | 7 | 16.9% |
| **clean_rescued** | **34** | 54 | 130 | 6 | **20.0%** |

- **Flip rate says NULL: treatment 12.5%/10.3% against a 12.9% noise floor.** The taxonomy
  churns as much between two IDENTICAL runs as it does under the treatment.
- **Scenario COUNT says otherwise: 34 vs a 26–28 base band.** Both are true because **a flip
  rate discards DIRECTION** — noise flips are symmetric (12 merged->scenario vs 10 the other
  way, net +2) while the treatment's are asymmetric (12 vs 6, net +6). **Report the direction
  of flips, never the rate alone.**
- **CLEANING THE CORPUS TIGHTENED THE NOISE FLOOR FROM ±7 SCENARIOS TO ±2** (40 vs 47 dirty;
  26 vs 28 clean). Contamination was not just junk, it was a major source of ADJUDICATION
  INSTABILITY — and it is why the first A/B was unreadable. On the dirty corpus the rescued arm
  (42) sat INSIDE the base range (40–47); on the clean one it sits clearly outside.
- **The treatment's direction FLIPPED between corpora** — consolidating on the dirty corpus
  (47->42), expanding on the clean one (26/28->34). A robust property of the rule would not do
  that; treat the taxonomy-shape claim as unproven.
- **A third base arm was considered and REJECTED as unnecessary**: it would tighten the floor
  around the weakest part of the case, the solid evidence (call coverage, account
  concentration) does not use the floor at all, and the corpus changed again anyway.
- **Reading confirms the cleanup, not the rescue.** Cleaned base top-5 scenarios: only 1 of 5
  account-bound (was 4 of 5), top scenario now 96 calls at 9% concentration. Mechanics are
  correctly sunk in both arms (scheduling, "Yeah.", time zones, "Okay.", late arrivals) with
  nothing substantive wrongly discarded. **The rescue nearly DOUBLES the largest sink
  (433->819) and sweeps some resourcing/alignment turns into discard — lost recall, not
  damage, since sink turns are dropped either way.**
- **Where the rescue IS solid, and it is not the taxonomy: evidence breadth.** Per scenario,
  base -> rescued: 96->133 calls, 68->114, 48->91; account concentration 16%->12%, 29%->21%.
  Measured in accounts and calls, units no clustering metric optimises.
- **STILL UNTESTED, and it is the only thing that decides adoption: Layer B/C.** Nothing
  downstream has run on either arm. The whole justification was "more evidence -> better-powered
  milestones" and not one link of that chain is measured.

