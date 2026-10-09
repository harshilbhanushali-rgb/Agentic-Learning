# Head-to-Head Comparison — the Last Live Idea for Wall 1, Closed (2026-08-13)

[Findings index](INDEX.md)

### Head-to-head comparison — the last live idea for wall 1, and it is CLOSED (2026-08-13)

Pre-registration: `docs/superpowers/specs/2026-08-13-head-to-head-comparison-design.md`.
Plan: `docs/superpowers/plans/2026-08-13-head-to-head.md`. Harness
`calibration/trial_head_to_head.py` (+ `calibration/probe_retrieval_gate.py`,
`shared/head_to_head.py`, `PROMPT_HEAD_TO_HEAD_BATCH`, `tests/test_head_to_head.py`).
Zero Postgres writes, zero `tuning.yaml` keys. **~250 Gemma calls total.**

Drop criteria entirely: for a CSM's client moment, retrieve Naren's real reply to the nearest
comparable moment and ask a blinded judge which reply handled it better. Named in the
profile-rebuild spec as the fallback if its gate failed. It failed; this is that fallback.
**The attraction was that the null is STRUCTURAL** — a useless judge scores 50%, so unlike
every criteria attempt there is nothing to argue about.

**DO NOT RETRY THIS. It failed for two INDEPENDENT reasons, and only one of them is about the
design.**

| control | run 1 | run 2 (pinned, both keys) | bar | |
| --- | --- | --- | --- | --- |
| C1 position-swap agreement, pooled | 0.694 | **0.669** | >= 0.75 | **FAIL** both |
| C2 expert vs expert | 0.582 | 0.543 | within [0.40, 0.60] | pass both |
| C3 sensitivity vs deranged-unrelated | 0.713 | 0.750 | >= 0.75 | marginal, lands ON the bar |
| **C4 transplant penalty** | **0.843** | **0.835** | < 0.75 | **FATAL**, replicated to 0.008 |

- **C4 is the one that matters, and it would have produced a spectacular FALSE POSITIVE.**
  Both sides of C4 are Naren; the only difference is that one reply is *native* to the moment
  and the other *transplanted* from a neighbouring one. Native wins **83.5%**. In the headline
  the CSM is always native and the expert always transplanted, so **W3 would have reported
  "the CSM outperforms Naren" — pure retrieval artifact.** The control caught it before the
  headline was ever computed. This is the argument for pre-registering controls, not a
  footnote to it.
- **Not length** (C4's length-matched cell is 0.875, *higher*), **not position** (slot-1 win
  rates 0.485–0.520, i.e. no positional bias at all), **not retrieval quality** (by cosine
  quartile 0.90/0.82/0.83/0.79 — tighter matching reduces it but never below the bar).
- **C1 is the deeper failure and no pairing design fixes it.** The judge reverses itself on
  ~20% of items when the two replies are swapped; signal share is `2a-1` = **0.34**. That is a
  property of the judge, not of the comparison.
- **C3 is the tell.** The judge separates a matched reply from a *deliberately unrelated* one
  only 75/25. A judge that can barely tell relevant from irrelevant cannot tell good from
  better. Same shape as the criteria scorer's 1.2:1 — weakly above chance, not an instrument.
- **The mechanism is understood, not merely observed:** Naren never spoke into this client's
  moment, so his reply can only ever reach the judge as a transplant. That is what comparing
  across corpora *is*; it is not a tuning problem.

**Model provenance is recorded per verdict (`judged_by`) and per artifact (`models`) — do this
in any future judge harness.** Run 2 pinned `gemini-3.5-flash-lite` with `gemini-3.1-flash-lite`
as the only fallback and still blended 8-18% of batches under rate limits (c4 was least
blended at 92.5% primary, and still 0.835). Without this field a verdict has unknown
provenance, which is exactly what makes the ceiling run's arm B uninterpretable.
**Gotcha found the same day: `call_gemma(fallback_enabled=False)` also disables KEY ROTATION**
— a failure then raises `GemmaError` instead of `_ModelExhausted`, and only the latter is
caught by the key loop ("single-model, single-key" in its own docstring). To pin the model
while keeping both keys live, pass `fallback_enabled=True, fallback_models=()`.

**What survives and is reusable by any future approach:**

- **`artifacts/h2h_moments.json` — 589 verified moments across 98 calls / 68 scenarios**,
  content-hashed (`moments_sha`). Built from all 106 `csm_recordings/` transcripts, because
  the unit is a *moment* and needs no rubric, no `milestone_performance` and no Layer D run.
  Funnel: 6,482 client turns -> 4,114 substantive -> 2,200 non-sink -> 853 with a CSM reply
  -> 589 after the symmetry fix and the retrieval floor.
- **The retrieval gate passes, in both directions**, and `calibration/probe_retrieval_gate.py`
  re-reports free via `--load`. Naren->Naren clean top-1 **0.812** vs a 0.631 base (95% CI on
  the lift [+0.168, +0.196]); cross-corpus CSM->Naren **0.791** vs 0.631 ([+0.130, +0.190]).
  Retrieval was never the problem.
- **First measurement of the trigger-vs-trigger cosine band in this repo:** p10=0.630
  p25=0.659 p50=0.689 p75=0.717 p90=0.746 — higher and tighter than the trigger-vs-scenario
  band `relative_margin` was calibrated against (p10=0.496 p50=0.550 p90=0.613). **Never
  borrow a floor between the two.**
- Restricting retrieval to **coachable-filed pairs** removes the 18.8% of neighbours that are
  sink-filed, by construction. This is also why retrieval runs against Postgres and not
  Pinecone: `is_coachable` is not in the `"triggers"` namespace metadata, so the filter is not
  expressible there.

> **WALL 1 IS REOPENED (2026-08-15).** The claim below rests on the ceiling's 1.2:1, which is
> now retracted as an arm-construction artifact — see the RETRACTED block in the ceiling
> section. Measured symmetrically and leakage-clean, the scorer discriminates in 77-82% of
> scenarios across two draws. **Wall 2 (no vocabulary) and the head-to-head failure (C1 0.669,
> C4 0.835 replicated) both stand** — those did not depend on the ceiling. What falls is
> specifically "the criteria scorer cannot tell a matched rubric from an unrelated one". The
> replacement problem is the LEVEL: `W(matched)` is 0.089-0.095 leakage-clean, i.e. the
> criteria are unpassable even by their own author. **Read the rest of this paragraph as the
> state of belief before that measurement, kept for the reasoning it records.**

**Where this leaves the profile effort: BOTH WALLS ARE NOW CLOSED BY MEASUREMENT.** Wall 1
(the ruler) has had criteria scoring, the four-arm rebuild and head-to-head all fail
pre-registered gates. Wall 2 (the axes) has no vocabulary at any granularity with enough
observations. Four approaches, four gates, four failures, each with a specific measured cause.
**A fifth variant of "get a model to referee" is not the next step** — every approach tried so
far asks an LLM to judge quality, and the referee is what keeps failing. What would be
different in kind is a unit of evidence whose ground truth is not another model's opinion:
real outcomes (deal progression, churn) or human labels from the CS team.

