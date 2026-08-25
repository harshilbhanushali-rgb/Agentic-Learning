# Embeddings, Model Choice & the Joveo Gateway (2026-08-13/16)

[Findings index](INDEX.md)

### Embedding backend: local bge vs hosted Gemini (2026-08-13)

`preprocessing/embedder.py` grew a `gemini` backend beside local bge, selected by
`tuning.yaml`'s `embedding.backend` and **shipping `local`** so nothing moved. Harness
`calibration/compare_embedders.py`, artifact `embedder_compare.json`.

**Four facts measured against the live API, none of them assumable:**

- **`embed_content` does NOT batch.** `contents=[3 strings]` returns **ONE** embedding — the
  list is treated as the parts of a single document. N texts cost N requests. This first
  surfaced as an `IndexError` several lines downstream because 161 scenarios in 2 batches
  produced 2 vectors and a boolean mask happened to check the length; **had the count been
  2 it would have run clean and produced fabricated numbers.** `_encode_gemini` now asserts
  one vector per text. **Consequence: a 74k-clause backfill is 74k requests against a
  1k/day cap = 74 days. `client.batches.create_embeddings` is mandatory for production, not
  an optimisation.**
- **Tokens bind, not requests, and by a wide margin.** Measured on the first real run:
  **34.66K/30K TPM while RPM sat at 6/100 and RPD at 7/1000.** Pacing on request count alone
  429s immediately. `_throttle` tracks both over a rolling 60s window.
- **`genai.Client` must be cached at module level.** Built inline it is garbage-collected
  mid-request — `Cannot send a request, as the client has been closed`. Same rule
  `pinecone_store` already carries.
- **`output_dimensionality` IS accepted; native width is 3072.** The model is
  Matryoshka-trained, so one call yields every width.

**Comparison result (150-pair labelled sample + 161 scenarios): 1 of 3 pre-registered
criteria — DOES NOT PASS.** But two of the three criteria were badly built by me, so this is
an inconclusive instrument rather than a clean no:

| space | margin(corr) | coupling | p50 | spread |
| --- | --- | --- | --- | --- |
| bge_768 | 0.561 | 0.617 | 0.558 | 0.141 |
| gemini_3072 | 0.672 | 0.560 | 0.672 | 0.083 |
| gemini_768 | **0.686** | 0.569 | 0.686 | 0.082 |

- **`sink_real_margin` 0.561 -> 0.686 is a real, clean win**, clearing its bar at every
  width. That signal's failure was explicitly diagnosed as an embedding-space problem
  ("real and sink centroids sit too close together"), and the diagnosis was right.
- **768 BEAT 3072** (0.686 vs 0.672), so the wide vector earns nothing: no new Pinecone
  index, no 867 MiB Layer A matrix, no migration.
- **The `spread` criterion measures the wrong thing.** p10-p90 of best-match cosine is the
  model's cosine SCALE, not its discrimination — Gemini's scores are uniformly higher and
  bunched. The right measure is top-1 minus top-2 per trigger, which was never taken.
- **The `coupling` criterion is confounded by the harness.** Triggers went in as
  `RETRIEVAL_QUERY` and responses as `RETRIEVAL_DOCUMENT` — correct for trigger-vs-scenario,
  wrong for comparing a trigger to its own response, which needs one symmetric task type.
  The bge baseline had no such split.
- **`sink_real_margin`'s published AUC 0.437 is NOT "worse than chance".** The signal is
  inverted by construction (higher = more filler-like), so it is direction-correct and worth
  **0.563** corrected. A pass mark set at ">=0.55" would have passed on zero improvement.
- **Harness miss to not repeat: the raw vectors were not persisted**, only the derived
  scores — so changing a criterion costs another 461 requests. Flush the PAID artifact, not
  just the conclusions drawn from it.

**Every threshold in `tuning.yaml` was calibrated against bge's cosine bands.** Gemini's p50
is 0.686 vs bge's 0.558 — switching backends invalidates `relative_margin`,
`merge_cosine_threshold`, the p40 relevance percentile and Layer D's sink comparison until
they are re-derived. That re-calibration, not the model, is the cost of the swap.


---

### Default Gemma model is now `gemini-3.5-flash-lite` (2026-08-13)

`shared/gemma.py::_DEFAULT_MODEL`, was `gemma-4-31b-it`, which stays last in the fallback
chain. Its 16k TPM ceiling could not hold the prompts this pipeline sends (one situated
describe call burned 8+ minutes of backoff), so call sites had been overriding it one at a
time; `v2/layer_c._FAST_DESCRIBE_MODEL` matched. **This changes production output, and every
number in this file was produced under `gemma-4-31b-it`** — comparisons against them are
model-confounded exactly as `arm0_baseline` (1.58) vs `arm0r_legacy_regen` (1.04) already is.


---

### Gemini backend via the Joveo gateway, and the adjudicator bottleneck (2026-08-15)

Spec: `docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md` Status update 10.
Harnesses `calibration/trial_pool_unit_gemini.py`, `trial_adjudicate_gemini.py`,
`export_cluster_batches.py`, `aggregate_cluster_verdicts.py`, on top of
`calibration/trial_gateway.py`. **Zero Postgres writes; the live 161 scenarios untouched.**

- **NEVER batch the gateway's `/embeddings`.** It silently returns FEWER vectors than inputs,
  intermittently -- the same request batches or collapses depending on when it is sent, and it
  hits SHORT text hardest, which is 29% of this corpus. Throughput comes from CONCURRENCY
  (one text per request, N workers), which cannot reintroduce the collapse. Measured: 24k
  requests at ~46 req/s with 20 workers, ~8 minutes.
- **Fetch the NATIVE width (3072) and truncate locally; key the cache on the native width.**
  Matryoshka validated at corpus scale -- `cos(api_768, renormalised first-768-of-3072)` over
  **11,977 real turns, min 1.000000**. Keying the cache on the ANALYSIS width would make
  `--width 768` miss every row and re-pay 24k requests.
- **3072 BEATS 768 for clustering, contradicting `compare_embedders.py`.** That file recorded
  `gemini_768` beating `gemini_3072` (0.686 vs 0.672 on `sink_real_margin`) and it does NOT
  transfer -- that measured per-trigger centroid margins, this measures cluster quality after
  UMAP+HDBSCAN. 3072 wins at every merge threshold from 0.92 up. Requesting 768 directly would
  have shipped the worse config with no way to notice.
- **`merge_cosine_threshold` on this backend is 0.97, not bge's 0.92.** Gemini's centroid band
  is p10 0.722 **p50 0.810** p90 0.886; at 0.92 only 136 clusters survive with a 1,790-item
  blob. Turn-vs-turn spread is 0.130 vs bge's 0.141 -- the compressed-space worry did NOT
  materialise. Two backends, two values, ONE config key.
- **Gemini clustering REPRODUCES EXACTLY across processes** (292 raw -> 245 merged in four
  separate runs, verified position-for-position on turn count). Deterministic embeddings
  remove one of the two sources of the run-to-run variance documented for bge.
- **GEMMA AND NINE BLIND JUDGES AGREE 100% ON WHAT TO DISCARD -- and an earlier claim here
  that Gemma "over-sinks 14.6% of the corpus" was MY ANALYSIS BUG, now retracted.** Cross-tab
  over 245 min-16 clusters: of the **138 clusters Gemma genuinely sank (mechanics+logistics),
  judges want ZERO**. The apparent 56-cluster disagreement was entirely `merge_into`
  decisions, which `_KIND_BY_DECISION` maps to `kind="merged"` -- a duplicate FOLDED INTO an
  existing scenario, i.e. RETAINED -- while my aggregator tested `kind == "scenario"` and
  counted them as sinks. Retention is **107/245 clusters, 41.0% of turns**: 38 distinct
  scenarios enriched by 69 merged duplicates. The only real disagreement runs the other way
  (15 clusters Gemma kept that judges would drop), so Gemma is marginally PERMISSIVE.
  **A prompt fix (`--turn-aware`, in the harness, OFF) was built for the phantom problem and
  moved agreement 76% -> 76% with 12-in/7-out churn; that null result is what exposed the
  bug.** A fix aimed at a real defect does not leave its target metric exactly where it began.
- **An ANALYSIS script manufactures findings as readily as a measurement script.** Four
  guards existed on the data path (blind judging, position-verified joins, path tests, a
  pre-registered gate) and none on the analysis path; the bug was one equality test against a
  four-valued enum, two of whose values mean "retained". **When a category has more than two
  outcomes, print the full cross-tab instead of collapsing to a boolean** -- the cross-tab
  makes this class of error impossible to miss.
- **The content-free proxy is sound.** With merges counted correctly all three measures agree:
  proxy 39.6% subject-bearing, blind judges 38% coachable, Gemma retention 43.7%. It is an
  excellent junk detector (>=70% content-free -> judges call **1%** coachable) and a
  serviceable quality measure. An earlier "the proxy was directionally wrong" verdict, based
  on comparing it to Gemma's `scenario`-only count, is withdrawn -- that comparison excluded
  the 69 merged clusters.
- **Finer granularity is BETTER, contrary to intuition:** min 16 beats min 50 on coherence
  (84% vs 75%), coachability (38% vs 33%) and coachable turn volume (35.1% vs 31.0%).
- **Blind the judges.** A judge shown the verdict grades the label, not the cluster. Same
  discipline as the head-to-head trial's position-swapped judging.
- Adjudication **must stay SEQUENTIAL**: the prompt carries "NEAREST SCENARIOS ALREADY
  ACCEPTED" and that accumulating list IS the duplicate-detection mechanism (69 merges fired
  at min 16). Concurrency was right for embeddings -- independent requests -- and is wrong
  here. Ordered dependency, not throughput.
- Turn-mode scenarios come out with VERBATIM keyphrases without any prompt change
  (`'launching this RFP'`, `'cost per activation'`, `'radius search'`) against production's
  analyst-speak (`'platform nuances'`, `'feature capabilities'`) -- whole turns give the model
  real client language to quote.

- **VALIDATED AGAINST LAYER D, not against itself** (`calibration/validate_taxonomy_vs_layerd.py`,
  free, read-only, both taxonomies embedded with the SAME model so only the taxonomy differs).
  Over **6,468 real CSM client turns**: production accepts 46.7% as signals, the turn-mode
  taxonomy 35.6% -- and reading the 1,071 turns production accepts that turn mode sinks, 4 of 6
  sampled are correctly rejected. **Production routes `"If."` and `"I'm not sure."` to coachable
  scenarios** -- specifically `client_validates_proposed_scenario` and
  `client_expresses_uncertainty`, the posture scenarios that fail the random-null test. The two
  agree on 78% of turns. Turn mode strands **0** scenarios with no rubric (production strands 1)
  and its weakest has 8 distinct calls.
- **The top1-top2 matching margin is ~0.01 cosine in BOTH taxonomies** (p50 0.009-0.010, mean
  0.0147 vs 0.0164). Every Layer B/D scenario assignment rests on the winner beating the
  runner-up by a hair. Unexamined, and arguably a bigger problem than which taxonomy is used.
- **A coverage test whose ground truth is the OLD taxonomy CANNOT be read at face value.**
  Sampling 600 turns from the 84 scenarios `gap_events` fired against, production keeps 85.3%
  and turn mode 74.0% -- but the moments are defined BY production, and the top two sources
  (`client_requests_operational_visualization` 184 events,
  `client_validates_proposed_scenario` 131) are posture scenarios that fail the null test. The
  test cannot separate "misses real coaching" from "correctly declines the old taxonomy's
  noise". An unbiased version needs labels independent of both -- e.g. the 589 verified moments
  in `artifacts/h2h_moments.json`, which need no rubric and no scenario assignment. NOT RUN.
- **PROPER-NOUN CLUSTERS SURVIVE THE UNIT CHANGE and make any coachable COUNT soft.**
  `implementing_and_maintaining_tracking_pixels` is really "the Happy Dance account": its top
  c-TF-IDF keywords are `happy dance, dance, happy`, and of 12 sampled turns only ~5 concern
  pixels -- the rest are timelines, field changes, banter and an Oracle/Workday tangent. Gemma
  named it for the pixels visible in its six samples; the binding is the client name. Same as
  the `jovio` cluster. Both Gemma AND the blind judges accept these because the samples look
  substantive, so neither is a defence. A rubric for "Happy Dance" transfers to no other
  client. Cheap unrun check: flag clusters whose top keywords are a proper noun.


---

### THE JOVEO GATEWAY CACHES CHAT COMPLETIONS (2026-08-16) — read before any A/B

**Measured directly.** The same prompt returned BYTE-IDENTICAL free text in 1741ms, then 249ms,
then 236ms. A prompt differing by ONE TRAILING SPACE returned different text in 806ms.
`cache: {"no-cache": true}` bypasses it (946ms/794ms, genuinely different text each call), and
`trial_gateway.chat_json` now takes `no_cache=True` — **default False so existing callers are
unchanged**, because for a one-shot production pass the cache is a saving, not a hazard.

**It silently destroys any design of the form "run the same thing twice and measure the
spread", and it already did.** A 245-cluster adjudication re-run as a noise floor came back
**245/245 identical — verdicts, keys, reasons AND free-text descriptions**. That reads as
perfect determinism; it was arm 1's answers echoed back. The tell was that identical *prose*
across 245 varied prompts is not plausible at temperature 0.2 — a verdict match would have
been. **Check a free-text field, not just the label, before believing a 0% floor.**
Wall-clock is the second tell (4.2m vs 7.1m for the same work).

**ANY harness measuring run-to-run variance MUST set `no_cache=True`, and every arm must use
the SAME cache policy** — bypassing on one arm and not the other is the asymmetric-filtering
error this repo keeps re-learning.

