# HANDOFF — Layer D calibrated end-to-end; first coaching report produced (2026-08-23 → 25)

Supersedes `HANDOFF_LAYER_D_REDESIGN_2026-08-20.md` (everything it listed as owed is done).
Full evidence trail: **`docs/findings/layer-d-redesign.md`** (this arc's single source of
truth — gates, numbers, retractions, the read). Production facts: `Brain/CLAUDE.md`.

## 0. STATE OF THE WORLD (settled; do not re-derive)

1. **The instrument is `layer_d_e_pairwise_gemini-3.6-flash_medium_noswap_v2`** and every
   piece of it is a measured verdict, not a choice:
   - **pairwise, not checks** — C2 head-to-head: pairwise 77.1% win share over 35 decided
     (p=0.00094) PASS; checks 53.9% over 13 decided FAIL (45/58 moments tied 0–0).
   - **why checks failed** — C3, run 4x: the expert's own per-moment rate is 3–6%
     regardless of grader model (flash-lite 0.11 vs 3.6-flash 0.057, same moments) and
     regardless of check wording (gradability rewrite moved 0.050 → 0.031, DOWN). The
     absolute per-moment unit is structurally wrong for arc-level moves. Do not revive it.
   - **noswap** — both orders agree 95.2% (600/630, C2) / 96.3% (C4); operator dropped the
     swap at their own >90% bar; CSM side RANDOMIZED per moment (hash) so position bias
     cancels; retroactively validated by the output audit (below).
   - **k=1** — zero verdict flips across k=3 in either arm at C2.
2. **C4 (human seal): blinded Sonnet reader vs model on production-shaped judgments —
   11/11 mutually-decisive agreement (gate ≥70%).**
3. **THE FIRST PRODUCTION RUN COMPLETED** (run_id 137706da74c6): 100 transcripts (6
   excluded, all Avoma "Unknown Speaker" — fail-closed gate), 1,206 moments, 807 graded
   (~807 requests, ZERO failures), 395 deferrals + 3 silences stored ungraded, 2,897
   verdicts (274 win / 2,134 equal / 489 loss), 251 move_performance rows.
   `ops/run_layer_d.py --report-only --hostaddr 18.138.49.39` reprints the report free.
4. **THE OUTPUT AUDIT: 40 stratified production moments, two blinded readers, 144
   verdicts — 46/47 mutually-decisive agreement (97.9%).** The model is the MORE
   conservative party (decisive-where-reader-equal 6 vs reader-decisive-where-model-equal
   19). One true disagreement in the sample.
5. **SPEC STEP 5 (the read): PASSES WITH NOTES.** The headline finding is true on the
   page (attribution moments: Naren interrogates/structures, Madhumita acknowledges/
   defers). Two production defects found — fragment replies graded (~2/11 of the top
   cell's losses are artifacts) and exemplar misfires (non-responsive or filler
   exemplars) — see §2. Direction unaffected; magnitudes shave.
6. **26 of 77 rankable cells are BLURRY (≥80% tie)** — incl. application_volume M1–M3
   (151 attempts) and ats_integration M3 (100% tie over 60). This list IS the targeted
   playbook-rewrite shortlist; a blanket 28-document rewrite stays unlicensed (the other
   session's G-Q1 census caveat).
7. **The 33% deferral rate** (395/1,206 moments answered by someone other than the CSM)
   is a real, zero-LLM coaching finding sitting in `move_events`, unreported so far.

## 1. VERDICT: SHIPPABLE AS A COACH-FACING DRAFT, NOT YET AS A CSM-FACING SCORE

Ship now to: the operator/coach, as ranked hypotheses with evidence attached — every
claim traces to transcripts and survived a 97.9% blind audit. Do NOT yet: show a CSM
their numbers, because ~2/11 of top-cell losses are segmentation artifacts and one
exemplar-misfire verdict is outright disputed. The three P0 fixes below close that gap.

## 2. THE FIXES, in order

**P0 (before any CSM-facing run; small, named, ~1 day total):**
1. **Interjection guard** — a response window below a structural substantiveness bar is
   classified like a deferral (recorded, NOT graded). Structural rule in
   `layer_d/signals.py`/`pipeline.py`, NOT a cosine threshold (per-item cosine filters
   failed 9x; this is a length/shape rule like `classify_response_outcome`).
2. **Substantive-exemplar filter** — run exemplar candidates through `_is_substantive`
   (exists in `v1/layer_b.py`) before top-cosine in `pipeline.make_exemplar_picker`.
   Kills both failure directions (filler benchmark, and her losing to it).
3. **Report grouping** — one priority per SCENARIO (moves within), in
   `aggregate`/`build_reports`; today's top-3 are one finding shown thrice.
   Then regrade (checkpoint identity changes with the guard; ~800 requests) and re-run
   the output audit on the new verdicts (zero spend machinery exists).

**P1 (product):** report the deferral finding; blurry-axis playbook rewrites (the 26-cell
shortlist, coordinate with the Layer C session); wire the report into the frontend
workspace; onboarding review (§5 of the 2026-08-15 spec) once a customer is in the loop.

**P2 (scale):** more CSMs (mapping.csv + rosters are the only prerequisites); trend
queries once calls accumulate; consider `hiring_forecasts`/`gig_economy` etc. joining the
rankable set as volume grows (10 scenarios are below the 8-attempt floor today).

## 3. MACHINERY BUILT THIS ARC (reuse, do not re-implement)

- `calibration/layer_d_grader_ab.py` — C2 head-to-head (resume, per-item flush).
- `calibration/layer_d_c4_read.py` — production-shaped judgments + blinded packet + KEY
  + `--score` (reader-vs-model agreement).
- `calibration/layer_d_output_audit.py` — `--readthrough` (spec step 5 packet),
  `--audit` (stratified blinded packets at scale), `--score`. ZERO chat spend: exemplars
  reconstruct deterministically from cache.
- `calibration/layer_d_bands.py` — C0 (bands, admitted/gradable counts).
- `ops/build_client_roster.py` — verified client roster from Avoma `.speakers.json`
  (email-domain ground truth); the fail-closed speaker gate's input.
- Grader knobs all in `tuning.yaml layer_d` (grader_model/effort, pairwise_swap,
  grader_k_runs — every value carries its measurement inline).

## 4. HOUSE LESSONS THIS ARC RE-PROVED

- **The pre-spend blind code audit went 4-for-4** (nested-playbook shape; checks-arm
  6x spend + instrument mismatch + arm-asymmetric population; C4 packet task/blinding
  gap; plus the first session's audit). Never skip it.
- **Relative beats absolute, third confirmation** (cosine floors → sink rescue → grading).
- **Run the cheap decisive measurement before the expensive planned one** — C3-first
  (operator's call) killed two wrong theories for ~350 calls before C2 spent ~1,000 on
  the right question; the 95%-swap-agreement check halved production cost in 5 minutes.
- **Absolute rates belong to the instrument** (0.11 vs 0.057, same behavior, two models).
  Never quote a Layer D rate without its instrument identity string.
