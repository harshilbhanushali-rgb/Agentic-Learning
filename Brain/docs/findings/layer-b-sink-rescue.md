# Layer B — Sink-Rescue: response_only / or_rule / blended (2026-08-04/05)

[Findings index](INDEX.md)

### Layer B sink-rescue: response_only / or_rule / blended (2026-08-04)

Design: `docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md`.

Problem: `assign_scenarios` decides sink-vs-real using only the trigger's embedding — if the
trigger's own best match is a non-coachable sink (mechanics/backchannel/logistics), the pair is
filed there alone and permanently excluded from every rubric, even when the trigger is filler
("I'm fine with whatever you guys think") but the response that follows is long and substantive (an
entire analytics-dashboard walkthrough). Reading real sink-filed pairs found this discards real
content at a materially high rate (39.7%–45.8% of pairs across the two production runs, roughly
half of a 30-pair manual sample judged genuinely coachable). `assign_scenarios_with_sink_rescue`
(`v1/layer_b.py`) adds a second, already-computed signal — the response's own embedding — that flat
matching ignores, via three strategies selected by a `strategy` argument exactly like
`assign_scenarios_two_stage`'s: `response_only` (only reconsiders pairs that are sink-bound today,
via the response's own top-K match), `or_rule` (also reconsiders any pair, sink or not, whose
trigger's own top-1 similarity is below a floor), and `blended` (replaces the matching vector for
*every* pair with a weighted trigger+response average, so it can flip the sink decision itself).
**NOT production** — `assign_scenarios` (flat) is unchanged; the only caller of the new function is
`calibration/compare_sink_rescue.py`, a new standalone calibration script (added alongside
`calibration/compare_matching_subset.py` in the Utility scripts list below) that re-runs all three strategies
against the real, already-embedded `kb_pairs`/`scenarios` and prints rescue rates plus verbatim
sample pairs for manual reading.

**Measured 2026-08-04 against the live `public` schema** (157 scenarios, 4,605 pairs, 1,865
sink-bound; full output `Brain/logs/compare_sink_rescue_20260804.log`):

- **Response-vs-scenario similarity is a genuinely different, higher band than the trigger-vs-
  scenario band `relative_margin` was calibrated against** — p10=0.552, p25=0.598, p50=0.635,
  p75=0.664, p90=0.688, vs. the trigger band's p10=0.496, p50=0.550, p90=0.613. This is why the two
  floors this design needs are two separate tuning keys, not one: `sink_rescue_response_min_similarity`
  (response-vs-scenario, document-vs-document) and `sink_rescue_trigger_weak_floor`
  (trigger-vs-scenario, query-vs-document, the same band `relative_margin` uses) — sharing one value
  between them silently breaks whichever wasn't the one being tuned.

- **`response_only` over-rescues badly at the 0.50 placeholder** — 95.2% of sink-bound pairs
  (1,775/1,865) get rescued, and reading the 20 samples confirms most are wrong (goodbyes filed as
  `client_direct_denial`, a "can you hear me?" check filed as `feasibility_and_implementation_request`).
  Absorption concentrates hard in 3 scenarios (798 of 1,775 rescues, nearly half) — the same
  "gravity well" category-collapse pattern already seen at the primary-topic and duplicate-scenario
  levels of this pipeline. Needs `sink_rescue_response_min_similarity` raised toward the measured
  band (p50/p75, not the current 0.50) before this rate means anything.

- **`or_rule` is the only one that isn't obviously broken, but its low 8.5% rescue rate (159/1,865)
  is largely a gating artifact, not evidence of better precision.** ~1,616 of the 1,865 sink-bound
  pairs never reach the response check at all — their trigger's own similarity to the sink is
  already ≥ `sink_rescue_trigger_weak_floor` (0.50), so the trigger-weak gate excludes them before
  the response is ever looked at. That means `or_rule` **structurally cannot address this design's
  own headline motivating case** — a trigger that CONFIDENTLY matches a sink while its response
  carries real content — it only ever helps the narrower, different case of a trigger that is itself
  weak. Also touches 4.7% of already-non-sink pairs (the risk surface the design named). Of the 20
  rescued samples, ~8-9 read as genuinely correct, including recovering the exact case the original
  sink-absorption audit flagged as real lost content.

- **`blended` is not viable at `alpha=0.6`** — rescues 22.4% of sink-bound pairs but destabilizes
  47.6% of pairs that were already matching correctly under flat matching, with no evidence the new
  answers are better.

- **Bottom line: none of the three is wired into production.** `matching_strategy` and
  `sink_rescue_strategy` both stay at their non-adopting defaults (`flat` / `none`) in `tuning.yaml`.
  `or_rule` is the only one worth a second calibration pass — and that pass must move its two floors
  independently: `sink_rescue_response_min_similarity` toward the response band (p50=0.635/p75=0.664),
  while `sink_rescue_trigger_weak_floor` is tuned against the trigger band (p10=0.496/p50=0.550) and
  raising it further would only shrink `or_rule`'s already-narrow qualifying population, not fix its
  precision on the population it does touch.

**Verdict (2026-08-05, after three more rounds): sink-rescue is exhausted — no gating signal tried
separates real content from junk at a usable operating point.** Round 2 raised `or_rule`'s two
floors toward the measured bands and reproduced `blended`'s exact fatal flaw (39.5% rescue rate but
41.9% collateral churn on already-correct non-sink pairs) — confirming this is a signal problem, not
a threshold-tuning problem. The design then pivoted to non-embedding content signals in
`shared/trigger_quality.py`: `concrete_content_density(response)` — measured against a real
150-pair Gemma-labeled ground-truth sample via `calibration/label_trigger_quality_sample.py` — showed almost
total distribution overlap (coachable/not-coachable medians 0.400/0.400, AUC 0.523, indistinguishable
from chance). The two remaining functions in that module were then measured against the same
labeled sample: `sink_real_margin` points the statistically correct direction but is far too weak
(AUC 0.437) — real/sink scenario centroids both sit too close together in embedding space relative
to any one trigger to leave a usable margin — and `trigger_response_coupling` (cosine between a
pair's own trigger and response embeddings) is the best of everything tried, a real and consistent
signal (AUC 0.617), but still nowhere near a value any threshold elsewhere in this codebase was ever
adopted at (compare `response_word_count`'s own AUC of 0.853 in the same sample — a real signal, just
not one that fits this design's content-specificity hypothesis, and not adopted either). Four signal
families — absolute cosine floors (rounds 1-2), content density, and embedding-relationship signals
— have now all failed to reach a usable operating point. `sink_rescue_strategy` stays `none`;
`matching_strategy` stays `flat`; no further signal search is planned. `calibration/label_trigger_quality_sample.py`
now persists its full labeled sample (text, label, reason, every signal, raw embeddings) to
`Brain/artifacts/labeled_trigger_quality_sample.json` and accepts `--load PATH` to re-report with zero DB/Gemma
calls — so a future signal idea against this same ground truth is free. Full detail:
`docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md`'s Status updates 2-5.

**Sibling design also written off, before any code was built (2026-08-05).** A second design,
`docs/superpowers/specs/2026-08-04-layer-b-trigger-quality-gate-design.md` (drop a junk pair between
`extract_pairs` and `assign_scenarios` instead of rerouting it), shared the same labeled sample and
leaned on the same functions — its own combining rule names `concrete_content_density(response)` as
"what the drop decision actually hinges on." That signal's AUC (0.523) and its trigger-side
counterpart's AUC (0.519) are both chance-level, so the rule can't be built. `filter_junk_pairs` and
`compare_trigger_quality_gate.py` were never written — the effort stopped at the design's own
"read the labeled sample first" checkpoint. Both sink-discarding designs are now closed.

**A third, follow-up design (`2026-08-05-layer-b-combined-signal-analysis-design.md`) tried
combining the strongest signals instead of searching for a new one — also closed.** Combining
`response_word_count`, `trigger_response_coupling`, and a new `length_ratio` feature via logistic
regression scored AUC 0.845, *below* `response_word_count` alone (0.853), despite the two core
signals being nearly uncorrelated (r=0.087). Adopting length alone was then reconsidered on its
own merits (its aggregate precision/recall looked decent) and rejected after reading real
samples: it systematically flags long administrative/logistics/small-talk as coachable, and
systematically discards short, sharp strategic pivots and discovery questions as junk — actively
penalizing the terse expert-brevity coaching moves this pipeline exists to capture. Six signal
shapes total, each measured and each failed for a specific, sample-verified reason.

**Approach B (turn position in the call) found one more real signal, still insufficient.**
`edge_distance` (distance from the nearest edge of the call) alone scores AUC 0.636 and is
qualitatively confirmed — pairs right at a call's start/end are predominantly logistics/wrap-up.
Combined with length (near-zero correlation, r=-0.034) it reaches AUC 0.876, the first
combination in this whole effort to beat a single signal (0.853) — but reading its false
negatives found the *same* terse strategic pivots misclassified as before; the aggregate gain
doesn't fix length's core bias. Eight signal shapes measured total, all either failed outright or
carry a disqualifying bias found only by reading real samples. Full detail:
`docs/superpowers/specs/2026-08-05-layer-b-combined-signal-analysis-design.md`.

