# Layer D say-arm: occurrence + specificity grading for speech-act moves (2026-08-28)

[Back to the index](INDEX.md)

**Status: BUILT, AUDITED, GATES RUN TO COMPLETION — PRODUCTION NOT LAUNCHED (§8).**
G-S1b (call-level discrimination) and G-S2 (quotes) PASSED under contract v1;
G-S3 (specificity spread) FAILED both contracts — the tier is diagnostic-only;
**G-S4 FAILED at the shipped dead-check floor** (Naren's own call-level occurrence
is median ~15%: the playbook is a repertoire, not a per-call checklist), so the
CSM production run did not launch, per pre-registration. §9 carries the proposed
repertoire-coverage reframe, which awaits an operator decision.

Continues from `HANDOFF_LAYER_D_SPEECH_ACT_DESIGN_2026-08-28.md` (the operator decision
this doc executes) and `docs/findings/layer-d-redesign.md` (the instrument this extends).

## 1. The problem, in one paragraph (verified against stored data, not quoted)

Recomputed 2026-08-28 from `artifacts/ld_acttype_KEY.json` (the per-cell tie rates of
run `137706da74c6`): 77 rankable cells, mean tie rate **67.8%**, and the 53 non-blurry
cells still average **57.9%** ties — a continuum running hot everywhere, not 24 broken
cells. Five wording explanations measured null (blind, pre-registered); the surviving
explanation is structural: ~84% of playbook moves are **speech acts** ("state X, warn
about Y") that are complete once said, and a pairwise "which reply performs this move
better" question has no answer once both replies have or haven't said the thing. The
p=0.26 caveat stands: the per-cell act-type→blurriness link is NOT statistically
proven, and this design does not rest on it — it rests on the verified tie flood plus
the structural argument, and the gates below are what actually test the fix.

## 2. The design

**A third `grader_arm` value: `say`.** Moves are classified once, at the MOVE level,
into SAY / DO / MIXED (blind protocol, §4). DO and MIXED moves stay on pairwise —
their verdicts from run `137706da74c6` remain the production data. SAY moves get the
new arm. The combined coaching report reads pairwise cells for DO/MIXED moves and say
cells for SAY moves.

**The say-arm question, per moment, per SAY move:** *did the rep's reply raise this
move's content, and how specifically?*

| model answer | stored verdict | meaning |
| --- | --- | --- |
| `specific` | `hit` | stated AND anchored to THIS client (names, numbers, tools, dates, exact next step) — verbatim quote required, verified |
| `generic` | `partial` | stated in words that could be said to any client — verbatim quote required, verified |
| `no` | `miss` | not stated (no quote — you cannot quote a silence) |
| anything else / quote fails | `unscored` | instrument failure, never counted |

Mapping onto the existing four-state vocabulary is deliberate: `weighted = hits +
0.5*partials` becomes an occurrence-weighted specificity rate, and the ENTIRE
downstream machinery — shrinkage, `rank_gaps`, dead-check flags, `min_attempts_to_rank`
— is reused unchanged. Verdict semantics per arm are documented at the schema.

**The unit change — the load-bearing decision.** Grading stays at the MOMENT level
(same arm-e segmentation, same mandatory verbatim quote verified by
`layer_d/verify_quotes.py` against that moment's reply — the 23%-fabrication defence
is untouched). But **aggregation for the say arm rolls up to the CALL**: a
(rater, call, playbook, move) cell's verdict is the BEST verdict across that call's
scored moments (`specific > generic > no`), and `move_performance.attempts` counts
**calls**, not moments. This is what the old checks arm never had, and why it died:
per-moment absolute occurrence of an arc-level move runs at a 3–6% base rate even for
Naren (proven 4× at C3), so binary per-moment rates discriminate at coin-flip (53.9%,
C2). A fact stated once per call is naturally a per-call event. The 2026-08-15
"call-level scoring" rejection is NOT contradicted: that trial moved the GRADING to
the call level and fabricated 23% of its quotes; this keeps grading per-moment and
quote-gated, and only the COUNTING unit changes.

**Anchored specificity (the BARS/OSCE move).** The prompt defines `specific` with the
move's own benchmark evidence quote (first evidence entry of the playbook move) as an
in-prompt example of what specific looks like. Anchoring levels to concrete behavioral
examples rather than adjectives is the standard variance-reducer (BARS; RAEE's
reference-anchoring result already in the 2026-08-20 lit sweep, −44% SE). Medical
education's OSCE literature hit this exact wall: binary checklists reward occurrence
but fail to discriminate expertise (reliability .42–.76) while anchored global ratings
discriminate experts (.70–.86), and the standard remedy is the hybrid —
checklist-for-occurrence + anchored-scale-for-quality — which is precisely this arm
(occurrence tier + specificity tier). Sources: Regehr et al. 1998
(pubmed.ncbi.nlm.nih.gov/9759104), "The risks of thoroughness" (Adv Health Sci Educ),
PMC10320738.

**Benchmark symmetry.** The same instrument grades Naren's routed kb_pairs
(`rater_population='naren'`), and a gap is `naren_rate − shrunken_csm_rate`, never an
absolute number. For the say arm the benchmark SAMPLES BY CALL (whole calls until the
per-scenario sample is covered) rather than by pair, so the call-level denominator is
built from complete calls on both sides. The report publishes moments-per-call on both
sides per cell so opportunity asymmetry (CSM segmentation finds moments differently
than Layer B routing) is visible rather than hidden.

**Dead checks still apply.** A SAY move Naren himself rarely states at call level
(below `dead_check_naren_floor`) is evidence about the check, not about any rep —
flagged, excluded from ranking. This is the graceful handling for "say-type moves that
are really playbook over-specification".

## 3. Why this is not the dead checks arm with extra steps

Two independent differences, each aimed at a measured cause of death:

1. **Unit**: checks counted per-moment attempts (3–6% expert base rate → coin-flip
   discrimination). Say counts per-call attempts, where the expert base rate is the
   natural "does he say this on calls where the scenario arises" quantity.
2. **Gradient**: checks was binary (partial added late, still "substantive start"
   semantics). Say's generic/specific split is an expertise gradient — exactly the
   dimension the OSCE literature shows discriminates experts when binary occurrence
   doesn't, and exactly what a CSM can be coached on ("you said it, but not anchored
   to the client's own numbers").

## 4. The move classification: blind, fixed, hash-pinned — not a per-item filter

This project has hit the per-item-filter failure 9 times. This is not that shape:

- The classification is **at the MOVE level, fixed once per playbook move** — never a
  per-response or per-moment decision. 121 moves across the 33 live playbooks.
- It is produced **blind**: readers see ONLY shuffled criteria under opaque ids (the
  `ld_acttype_packet` protocol) — no scenario names, no tie rates, no move ids. Two
  independent readers; disagreements default to DO/MIXED (i.e. stay on pairwise — the
  conservative side, since pairwise is the validated instrument).
- The routing artifact (`artifacts/layer_d_move_classes.json`) stores a **criterion
  text hash per move**; the pipeline REFUSES to run if a live move's criterion no
  longer matches its hash (a remade playbook must be re-classified, loudly, not
  silently mis-routed). A live SAY-eligible move missing from the artifact is a
  refusal too, fail-closed.
- The earlier blind read (65 say / 9 do / 3 mixed over the 77 rankable cells) was
  never persisted; this classification re-runs it over ALL 121 moves and reports
  reader agreement as part of the record.

## 5. Pre-registered gates (frozen 2026-08-28, before any code ran or any spend)

| Gate | What | Bar | Spend |
| --- | --- | --- | --- |
| G-S1 discrimination | C2's exact construction (same 5 pbq scenarios, same moment population, matched playbook vs size-matched unrelated playbook), SAY moves only, score = weighted specificity | win share ≥ 0.70 over decided moments, binomial p < 0.05 vs 0.5 | ~30–60 requests |
| G-S2 quote gate | every `specific`/`generic` credit in the G-S1 sample | ≥ 95% verify programmatically | free (same run) |
| G-S3 tier spread | scored verdicts in the G-S1 matched arm | no single tier > 90% of scored verdicts AND `specific` fires ≥ 1× — else it is binary-with-extra-steps and fails | free (same run) |
| G-S4 benchmark readout | Naren say benchmark over all live playbooks' SAY moves, call-sampled | per-cell rates published; sub-floor cells flagged BEFORE any coaching number is read; no pass/fail bar (it is a readout), but ≥ 50% of SAY cells must be non-dead for the arm to be worth shipping | ~150–200 requests |
| G-S5 blind output audit | ~40 (criterion, reply, verdict) triples from the production run, two blind readers, opaque ids | ≥ 70% agreement with model verdicts among mutually decisive items (same bar as the pairwise audits, which hit 97.9%/92.7%) | free + reader tokens |

Any gate failure ⇒ stop, write up the failure, bring operator options (pre-listed in
§7). The C2-style harness gets a blind code audit before it spends, same as every
prior spend harness.

**k-runs**: C2 measured ZERO verdict flips across k=3 on both arms at this
model/temperature; the say harness re-checks with k=3 on a ~12-moment subset and
reports flips, but k=1 is the default unless flips appear.

## 6. Code changes (all tested before the audit, audited before spend)

1. `db/schema.sql` + live DB: widen `move_events`/`move_performance` `grader_arm`
   CHECK to include `'say'` (idempotent drop+add, same pattern as
   `response_outcome`). Schema comment documents per-arm verdict semantics and that
   say-arm `attempts` counts CALLS.
2. `shared/storage.py`: `_VALID_GRADER_ARMS` += `'say'`;
   `refresh_move_performance` gets a say-specific rollup (per-call MAX over verdict
   rank, calls with ≥1 scored moment count as attempts, all-unscored calls counted
   in `unscored`) and excludes `'say'` from the per-moment rollup.
3. `layer_d/move_classes.py` (new): load + validate the routing artifact
   (hash-pinned, fail-closed), expose `say_moves(playbook)` filtering.
4. `layer_d/prompts.py`: `PROMPT_SAY_BATCH` (per-move benchmark example lines
   included as specificity anchors).
5. `layer_d/graders.py`: `build_say_prompt` / `parse_say_response` /
   `grade_say_batch` (mirrors the checks batch shape, `CHECKS_BATCH_SIZE`).
6. `layer_d/pipeline.py`: `grader_arm='say'` path in `grade_moment_set` (moves
   filtered to SAY), benchmark pass call-sampling for say, checkpoint layer suffix
   carries the classes-artifact hash (a classification change invalidates progress,
   same rule as a model change).
7. `layer_d/aggregate.py`: say-arm report formatting ("stated specifically /
   generically / not raised" language) + a combined report that merges pairwise
   (DO/MIXED cells) and say (SAY cells) into one ranked block per CSM.
8. `calibration/layer_d_move_classes_packet.py` (new): full-121-move blind packet +
   key + `--score` (refuses partial reads) + artifact writer.
9. `calibration/layer_d_say_ab.py` (new): the G-S1/2/3 harness, mirroring
   `layer_d_grader_ab.py`'s construction and artifact discipline (bill first,
   `--spend` to run, `--load` to re-report).
10. `calibration/layer_d_output_audit.py`: `--audit-say` / `--score-say` (G-S5) —
    blinded occurrence-shaped packets (criterion + anchor + reply, reader answers
    no/generic/specific), exact 3-way agreement vs the model, gate ≥ 70%. (The
    pre-spend audit caught this item as promised-but-missing; built before G-S5.)
11. `layer_d/aggregate.py` + `shared/storage.py::get_say_densities`: the
    moments-per-call opportunity readout in every say report block (the audit's
    one finding — the §2 promise was unimplemented; fixed before spend).

## 5b. AMENDMENT (2026-08-28, registered mid-G-S1, before its report was read)

The G-S1 run's FIRST scenario returned 12/12 ties, every one 0.0-vs-0.0 with all
108 matched-side verdicts `miss`. This section was written at that point — before
any other scenario's outcome, and before the run's report — to register two changes
with their rationale, rather than quietly adjusting after a failure:

1. **G-S1b, a call-level construction of the same gate.** The moment-level
   matched-vs-unrelated construction was inherited from C2, where it correctly
   licensed pairwise — a RELATIVE judgment that works below the absolute
   occurrence threshold. An absolute arm at a 0-5% per-moment base rate ties 0-0
   on almost every moment REGARDLESS of its real discrimination, so the
   moment-level gate cannot license (or damn) it; this is the same
   unit-mismatch C3 established, reproduced inside the gate itself. G-S1b:
   group the SAME population's moments by CALL within a scenario; grade every
   moment against matched and (separately) unrelated playbook; roll each side up
   per call (best verdict per move — exactly production's rollup); score =
   weighted over moves; win = matched > unrelated. **Same bar: win share >= 0.70
   over decided calls, binomial p < 0.05.** G-S1 (moment-level) is reported
   as-run; G-S1b at the arm's actual shipping unit is the licensing gate.
2. **say_v2 contract: the generic tier credits a CONCRETE ELEMENT.** The v1
   prompt required "the move's content" whole; live criteria are conjunctive
   ("detail friction mechanisms AND offer no-login options"), so whole-content
   occurrence per reply is structurally rare. The checks arm already paid for
   this lesson: its `partial` tier exists because "conjunctive criteria make
   half-credit meaningful", and the criteria-rewrite A/B's only measured grading
   gain (x1.6) came through partials. v2 aligns the generic tier with that
   measured contract ("a real, substantive statement of the move's content or a
   concrete element of it — merely mentioning the topic is NOT enough");
   specific = the same, anchored to THIS client. This is a prior measured
   finding applied, not wording iteration: the refuted lever was rewriting
   PLAYBOOK criteria, not aligning a grader contract with the half-credit
   result.

The v1 artifact is preserved as `layer_d_say_ab_v1.json`; G-S1b runs under
contract `say_v2_element_credit` and writes `layer_d_say_ab.json`.

## 7. Pre-listed fallbacks if the arm fails its gates

- **G-S1 fails** (can't tell matched from unrelated): fall back to occurrence-only
  at call level reported DESCRIPTIVELY (coverage stats, no ranking), and coach only
  the 9–12 DO/MIXED cells from pairwise. Also brainstorm alternatives — e.g.
  two-stage pairwise (compare specificity only among replies that both raised it) —
  but nothing ships without its own gate ladder.
- **G-S3 fails** (tiers collapse): the specificity definition is not extracting a
  gradient; try ONE pre-registered anchor variant (per-move anchors from a different
  evidence quote), then stop — the house lesson is that wording is rarely the lever.
- **G-S4 shows >50% dead cells**: the playbook's say-moves are over-specified
  relative to what Naren actually says; that is a Layer C content finding, reported
  as such, not patched in the grader.

## 8. RESULTS - appended as they run

### Gate run 1: contract say_v1, 55 moments / 5 pbq scenarios / k=3 (2026-08-28)

Artifact: layer_d_say_ab_v1.json; log logs/say_ab_20260828.log.

| gate | result | detail |
| --- | --- | --- |
| G-S1 (moment) | **PASS** | win 7 / loss 1 / tie 47 -> 87.5% over 8 decided, p=0.035 |
| G-S1b (call, S5b) | **PASS** | win 7 / loss 0 / tie 33 -> 100% over 7 decided calls, p=0.0078 |
| G-S2 quotes | **PASS** | 45/45 credited claims verified (100%) |
| G-S3 tier spread | **FAIL** | miss 94% / specific 5% / generic 1% of 525 scored - the gradient collapsed |
| noise | clean | 0/55 moments flipped across k=3 (matches C2's zero-flip result) |

Readings: (1) when ANYTHING decides, the matched playbook wins - the instrument
detects real content, and G-S2 says its credits are never fabricated; (2) the tie
flood is 0.0-vs-0.0 all the way down (36/36 ties in the worst scenario were
all-miss on both sides) - the v1 whole-content generic tier reproduces the checks
arm's base-rate starvation at the moment level, exactly as S5b diagnosed mid-run;
(3) specific outnumbered generic 27:6, i.e. v1's "state the whole criterion
generically" is a nearly-empty tier: when a rep states a whole bundled criterion,
they are almost always doing it with client detail. The element-credit contract
(say_v2) is the pre-registered response; its run decides licensing.

### Gate run 2: contract say_v2_element_credit, same population, k=3 (2026-08-28)

Artifact: layer_d_say_ab.json (v2); log logs/say_ab_v2_20260828.log.

| gate | result | detail |
| --- | --- | --- |
| G-S1 (moment) | **FAIL** | win 12 / loss 5 / tie 38 -> 70.6% over 17 decided, p=0.072 |
| G-S1b (call) | **FAIL** | win 10 / loss 4 / tie 26 -> 71.4% over 14 decided calls, p=0.090 |
| G-S2 quotes | **PASS** | 81/81 verified (100%) |
| G-S3 tier spread | **FAIL** | miss 90.3% of 525 scored (bar <= 90%); call-level 88% |
| noise | clean | 0/55 flips across k=3 |

### DECISIONS (2026-08-28, from the two runs together)

1. **The shipping contract is v1** (the rule was stated before v2's report was
   read: whichever contract passes G-S1b ships; v1 passes, v2 does not). The
   element-credit revision DOUBLED decided-N but imported losses: element-level
   credit fires on content shared with topically-adjacent scenarios (the
   size-matched partners here are adjacent by construction - ats_integration <->
   downstream_activation both carry tracking content), so looser credit costs
   scenario-discrimination. The checks partial-tier lesson does NOT transfer to
   an occurrence instrument's cross-scenario validity. v1's strictness is the
   feature: when it credits, it is right (7-0 decided calls, 100% verified
   quotes across 126 claims in both runs).
2. **G-S3 is a definitive FAIL under both contracts (94%/90% moment, 91%/88%
   call) - the specificity gradient did not materialize.** The one pre-registered
   revision has been spent. Per S7: STOP iterating. The specific/generic tier
   stays in storage (hit vs partial - they are facts about the reply) and in the
   report as descriptive counts, but **no coaching claim rests on the gradient**:
   the arm ships as an OCCURRENCE instrument at the call level. The OSCE
   checklist+GRS hybrid hypothesis did not survive contact with this population -
   when a rep states playbook content at all, it is nearly always client-specific
   already (specific outnumbered generic 27:6 and 45:6), so the middle tier is
   almost empty.
3. **What remains licensed and what remains open.** Licensed by these runs:
   occurrence-at-call-level discrimination (G-S1b v1), the quote gate (G-S2 twice,
   126/126), zero run-to-run noise. Open and decisive for shipping: G-S4 - Naren's
   own call-level occurrence rates on SAY moves. The C3 precedent (per-call
   occurrence 0.00-0.24 under the checks contract) says the benchmark may be low;
   if fewer than half the SAY cells are non-dead at the shipped
   dead_check_naren_floor, the arm is not worth its production spend (S5 bar) and
   the S7 fallback fires. G-S4 runs under contract v1, with a floor-sensitivity
   table (0.50 shipped / 0.30 / 0.10) reported for the operator.

### Gate run 3: G-S4, the Naren say benchmark (2026-08-28, run_id 695837c37614)

All 33 live playbooks, whole-call sampling (>=30 pairs/scenario), contract v1.
910 naren/say move_events written, zero failures, zero unscored anywhere in the
readout, every one of the 87 SAY cells measured at 11-26 calls. The rollup SQL was
replay-verified mid-run against an independent Python recomputation (16/16 cells
identical). Readout: calibration/layer_d_say_g4_readout.py (zero spend, re-runnable).

**G-S4: FAIL at the shipped floor.**

| dead-check floor | non-dead cells |
| --- | --- |
| 0.50 (shipped) | **3/87 (3%) -> FAIL** |
| 0.30 | 12/87 (14%) |
| 0.10 | 58/87 (67%) |

**What the number means -- this is the finding of the day.** Naren states a given
playbook move's content on a MEDIAN of ~15% of his own routed calls (range 0.00 to
0.50). The playbook is a REPERTOIRE he deploys occasionally when the moment inside
a call warrants it -- not a per-call checklist, and not a per-moment one (C3 already
measured 3-6% there). Every occurrence framing at every unit now has a measured
verdict: per-moment 3-6% (dead, C3), per-call ~15% median (below any defensible
"the expert should mostly pass" floor). This closes the loop on the checks arm's
death and the pairwise tie flood with one mechanism: playbook moves are
low-base-rate, situation-triggered behaviors, so absolute per-unit demands fail
and pairwise comparisons tie whenever the situation did not trigger the move for
either rep -- which is most of the time.

**Consequence per pre-registration: the CSM production say run did NOT launch.**
tuning.yaml grader_arm is flipped back to pairwise. G-S5 (output audit) is moot
without production data. The naren/say benchmark events remain in move_events
(they are real measurements, keyed by arm, invisible to pairwise reads).

## 9. PROPOSED NEXT (not run -- needs the operator): repertoire coverage

The failed framing was "rate difference per call vs a benchmark floor". The data
supports a different aggregation of the SAME instrument (nothing about grading,
quotes, or routing changes -- only the report-level question):

    A move is IN NAREN'S REPERTOIRE if he verifiably said it on >= 2 distinct
    calls (61 of 87 say moves qualify from the benchmark already in hand).
    For each such move, the coaching question is: does the CSM's whole body of
    routed calls contain even ONE verified instance? "Never once, over enough
    calls" is a REPERTOIRE GAP: "here is a move you have never used; Naren
    deploys it every ~N calls of this type; here are his verbatim examples."

Why this is well-powered where the rate framing was not: P(zero occurrences in n
calls | p) makes "never" significant at p<0.05 within n = log(.05)/log(1-p) calls
-- median 13, and 46 of the 61 in-repertoire moves need <= 20. Madhumita has >= 8
graded calls on 18 of 30 playbooks (median 11, max 55), so a meaningful subset of
(move, CSM) cells is decidable TODAY, and every additional ingested call improves
it. The binary ever/never verdict also sidesteps the dead-check floor entirely:
no rate comparison, so no floor.

What it needs (all pre-registerable before any spend):
  1. The CSM production say run (~300-400 requests over the 100 transcripts) --
     the spend G-S4 paused; grading and quote-gating identical to the licensed v1.
  2. A repertoire aggregation + report section (cheap, pure code on move_events).
  3. Gates: (a) G-S5 blind output audit as designed (the --audit-say machinery is
     built); (b) a spot-read of every "never" cell's moment population (a "never"
     built on 3 mis-segmented moments is not a gap); (c) the power rule enforced
     per cell (a "never" over fewer calls than the move's n_needed is reported as
     "insufficient data", never as a gap).

Alternatives considered and NOT recommended: (a) shipping rate-gap coaching at a
0.10 floor -- 58 cells survive, but at base rates 0.1-0.3 with 8-20 CSM calls per
cell, the per-cell standard error (~8-13pp) swamps most gaps; it would produce
confident-looking noise. (b) More prompt iteration -- the one pre-registered
revision was spent (v2, failed), and wording-as-lever is refuted 6x in this
project. (c) Abandoning say moves entirely and coaching only the 34
pairwise-routed cells -- discards 72% of the playbook when a viable aggregation
exists; keep as the fallback if the operator rejects the repertoire run.

## 10. W0 -- the warrant-legibility probe (PRE-REGISTERED 2026-09-05, before the probe ran)

**The question.** Naren deploys a given SAY move on ~1 routed call in 7 (§8, G-S4).
Is whatever makes him deploy it at one moment and not another VISIBLE in the
client's trigger text? If yes, a per-moment "you missed the chance HERE" detector
(W1) is buildable from transcripts; if no, it is impossible from transcripts in
principle and per-moment missed-chance claims come off the table with evidence.
Ask Naren's ADR 0005 already found retrieval cosine alone could not separate right
from wrong answers in a neighbouring problem, so the prior here is skeptical --
which is exactly why this is a zero-spend probe and not a build.

**Data (already in the DB, no spend).** The naren/say `move_events` of run
`695837c37614` (all 33 live playbooks; 1,001 events with verdicts, 850 distinct
trigger texts -- the doc's earlier "910" counted the readout's scored cells at the
time; the stored row count is what the probe reads). Per (playbook, move, moment):
deployed = verdict hit or partial; not deployed = miss; unscored excluded. A move
is in scope if it is IN NAREN'S REPERTOIRE (deployed on >= 2 distinct calls; 61 of
87 SAY moves, recomputed 2026-09-05 from `move_performance`).

**Embeddings.** gateway/gemini-embedding-2 @ 3072, CACHE-ONLY through
`calibration.layer_bc_arms._load_cached` (the same reader the calibration shim
uses): abort on any cache miss, assert width 3072. Verified before freezing this
section: all 850 trigger texts are cached, 0 missing. (The 2026-08-19 gotcha -- a
script that forgets the shim silently compares two embedding spaces -- cannot bite
a script that never calls the embedder at all.)

**Method (frozen).**
1. For each in-repertoire move: its deployment triggers = the trigger texts of the
   moments where Naren deployed it.
2. For EVERY scored moment of that move's scenario, the score is the max cosine
   similarity to the move's deployment triggers, **leave-one-CALL-out**: deployment
   triggers from the same call as the moment being scored are excluded. This is
   stricter than the handoff's leave-one-moment-out and it is the primary rule on
   purpose: a W1 detector would score a CSM's moment against Naren's deployments on
   OTHER calls, and two on-topic moments inside one call are similar because they
   share a client, not because the trigger carries warrant. Leave-one-moment-out is
   reported as a diagnostic. A moment with no remaining reference deployment is
   dropped from the pool (reported).
3. Pool all (moment, move) pairs across moves (per-move n is 2-8 deployments, too
   thin alone); base rate = deployed pairs / all pairs. Bucket by similarity decile
   and report deployment rate per decile. Per-move curves are diagnostics only.
4. Permutation null: within each move, shuffle the deployed labels over that move's
   moments and recompute steps 1-3 (the reference set moves with the labels), 500
   times; p = share of permutations whose top-decile deployment rate >= the observed.

**Decision rule (frozen; adjust nothing after the numbers exist).**
Warrant is **LEGIBLE** iff, on the primary (leave-one-call-out) pooled curve, the
TOP DECILE of (moment, move) pairs by similarity has deployment rate
(a) >= 3x the base rate AND (b) >= 0.50 absolute AND (c) permutation p < 0.05.
Otherwise **NOT LEGIBLE**. The top-20% band is reported alongside as context, not
as a second chance.

**What each outcome means, decided now.**
- LEGIBLE -> design the W1 ladder: a per-moment detector calibrated on Naren's own
  conditional deployment rates, validated on held-out Naren calls, then a blind
  read of flagged CSM moments. W1 is a PER-ITEM CLASSIFIER -- the shape that has
  failed 9 times in this project -- so its gates must be merciless, and it must
  never be validated against an LLM's opinion of "warranted", only against Naren's
  measured behaviour.
- NOT LEGIBLE -> per-moment missed-chance claims from transcript data are closed,
  with this as the evidence. Coaching stays at the repertoire level (§9 / §11).

Artifact: `artifacts/layer_d_w0_warrant_probe.json`; script:
`calibration/layer_d_w0_warrant_probe.py`. Results are appended below as §10b.

### 10b. W0 RESULT (2026-09-05, run as frozen; zero spend): **NOT LEGIBLE**

Artifact `artifacts/layer_d_w0_warrant_probe.json`; log `logs/w0_warrant_probe_20260905.log`;
seed 20260905, 500 permutations. 1,001 events, 61/87 in-repertoire cells, 1,840
(moment, move) pairs scored under leave-one-call-out (0 dropped for lack of a
reference); base deployment rate 0.155.

| decile (10 = most similar) | cosine range | deployment rate |
| --- | --- | --- |
| 10 | 0.800-1.000 | **0.283** |
| 9 | 0.784-0.800 | 0.217 |
| 8 | 0.774-0.784 | 0.196 |
| 7 | 0.762-0.774 | 0.130 |
| 6 | 0.752-0.762 | 0.168 |
| 5 | 0.743-0.752 | 0.114 |
| 4 | 0.731-0.743 | 0.120 |
| 3 | 0.717-0.731 | 0.120 |
| 2 | 0.697-0.717 | 0.092 |
| 1 | 0.591-0.697 | 0.114 |

| rule clause | needed | measured | |
| --- | --- | --- | --- |
| (a) top decile >= 3x base | >= 0.465 | 0.283 (1.82x) | **FAIL** |
| (b) top decile >= 0.50 absolute | >= 0.50 | 0.283 | **FAIL** |
| (c) permutation p < 0.05 | < 0.05 | 0.000 (null mean 0.167, p95 0.223) | pass |

Diagnostics: AUC(similarity -> deployed) = 0.611 primary, 0.637 leave-one-moment-out
(top decile 0.310 there -- the same-call leak is small: only 18% of deployed moments
have their nearest other deployment in the same call, so the stricter construction
cost little). Top-20% band: 0.250.

**Reading.** There IS a trace of warrant in the trigger text -- the enrichment is
far outside the permutation null, so this is not noise -- but it is weak in the way
that matters: even among the 10% of moments MOST like the ones where Naren deployed
a move, he deployed it on 28%. A per-moment "you missed the chance here" detector
built on trigger similarity would be wrong about 7 times in 10 in its very best
band, and worse everywhere else. That is the same shape as ADR 0005's finding one
problem over (cosine finds the topic, not the decision). The decision to deploy is
made on something the trigger text does not carry -- what was said earlier in the
call, the account's history, what the CSM already knows -- and none of that is
recoverable per moment from the transcript. The rule was frozen with a 3x/50% bar
precisely so a "real but weak" signal like this one would not get talked into a
build; it is not being talked into one.

**Consequence (pre-registered).** Per-moment missed-chance claims from transcript
data are OFF THE TABLE. W1 is not designed. Coaching stays at the repertoire level
(§9 / §11): "you have never used this move over n calls" is a claim the data can
carry; "you should have used it at 14:32" is not.

**One door left ajar, not opened.** The 0.61 AUC is a measured fact. If a future
session wants to revisit W1 it must bring a NEW feature (something beyond trigger
cosine -- e.g. call-position, prior-turn content, or the account's state), re-freeze a
rule of the same strictness, and clear it. Re-running THIS probe with a looser bar
is not a revisit, it is the thing the pre-registration exists to prevent.


## 11. THE REPERTOIRE PASS (Task A) -- pre-registered 2026-09-05, before the production say run

Operator-approved 2026-09-05 (HANDOFF_LAYER_D_REPERTOIRE_AND_W0_2026-09-05.md §1).
This section is written BEFORE `tuning.yaml grader_arm` is flipped to `say` and
before a single CSM moment is graded under the say identity.

**What ships.** `layer_d/repertoire.py` (pure code, tests in
`tests/test_layer_d_repertoire.py`) + a REPERTOIRE section leading
`pipeline.build_combined_reports` (`ops/run_layer_d.py --report-combined`). Per
(CSM, in-repertoire SAY move), one of three states:

| state | rule | reported as |
| --- | --- | --- |
| `uses it` | >= 1 quote-verified instance (hit OR partial) on any of her routed calls | fact + up to 3 of her verified quotes |
| `never` | zero instances AND her routed-call count n >= n_needed(p_hat) | a repertoire gap: the move, Naren's frequency ("every ~N calls"), his verbatim evidence quotes |
| `insufficient data` | zero instances, n < n_needed | listed as data with the count still needed; NEVER worded as a gap |

Definitions, fixed: in-repertoire = Naren said it on >= 2 distinct benchmark calls
(61/87 SAY moves, recomputed from `move_performance` 2026-09-05); p_hat = his
(hits + partials) / attempts on the naren/say row (attempts count CALLS);
n_needed = ceil(ln 0.05 / ln(1 - p_hat)) -- median 13, 46/61 <= 20; her n = the
csm/say row's attempts (calls with >= 1 scored moment for the move).

**Spend.** The CSM production say run over the same 100 mapped transcripts as the
pairwise run (~300-400 gateway requests). The Naren benchmark pass inside the batch
is SKIPPED by copying run `695837c37614`'s 33 `_naren` checkpoint rows to the
batch's run_id (identical instrument identity, identical items, identical sample):
re-grading would UPSERT over the very benchmark events that G-S4 and W0 were
measured on, so skipping is correctness, not thrift.

**Gates (pre-registered; a failure STOPS the work and brings options, it does not
get renegotiated after the numbers exist):**

- **G-R1 blind output audit.** `calibration/layer_d_output_audit.py --audit-say`
  over the stored CSM say verdicts (40 moments, stratified 60% with a positive
  claim / 40% miss-only), TWO fresh Sonnet reader subagents, packet-only (no
  model verdicts, opaque item ids), every read persisted to `artifacts/` before
  scoring. `--score-say`: **>= 70% exact 3-way agreement** (no/generic/specific vs
  miss/partial/hit) among mutually decisive verdicts, pooled over both readers.
  Binary said/not-said agreement is reported as a diagnostic; the repertoire
  report only USES the binary collapse, so if 3-way fails but binary >= 80% the
  verdict is "3-way FAIL, binary PASS" and the operator decides -- written up,
  not waved through.
- **G-R2 spot-read of every `never` cell.** Zero spend. For EVERY cell the report
  calls `never`, read its stored moment population (the CSM's scored moments on
  that playbook): are they real client moments on that scenario, with substantive
  CSM replies? A `never` whose moments are mis-routed, deferrals mis-classified as
  CSM replies, or fragments is a segmentation artifact and is struck from the
  report (and counted). Bar: **>= 80% of `never` cells survive**; below that the
  section does not ship and the segmentation, not the prompt, is the suspect.
- **G-R3 power rule in code.** Enforced per cell in `repertoire.classify`, pinned
  by `tests/test_layer_d_repertoire.py` (n_needed(0.15) == 19; 18 zero-calls ->
  insufficient; 19 -> never). Already green before this section was written.

**Fallback if G-R1 or G-R2 fails (pre-listed):** do-type-only coaching -- the 34
pairwise-routed cells (§7/§9(c)). No prompt iteration (refuted 6x); no floor
tuning. **After the run, regardless of outcome:** `grader_arm` flips back to
`pairwise` (fail-safe convention).

Results are appended below as §11b.
