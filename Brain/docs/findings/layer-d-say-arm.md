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


## 12. Layer C census of the 26 out-of-repertoire SAY moves (2026-09-05, zero spend)

**The question.** 26 of the 87 SAY moves were said by Naren on fewer than 2 of his own
benchmark calls (G-S4 data). The queue's hypothesis (handoff §3 item 5): these are
Layer C over-specification -- moves built from too little evidence -- and a rule
"every move needs evidence from >= 2 distinct calls" for the NEXT playbook generation
would have prevented them. The census reads each move's stored evidence
(`key_moves[].evidence[].call`) and checks whether that rule separates the two groups.

**Result: the evidence-count rule does NOT separate them.**

| distinct calls in a move's evidence | out-of-repertoire (26) | in-repertoire (61) |
| --- | --- | --- |
| 1 | 3 | 2 |
| 2 | 9 | 9 |
| 3 | 8 | 33 |
| 4 | 6 | 17 |
| share with >= 2 calls | 88% | 97% |
| share with >= 3 calls | 54% | 82% |

Evidence quotes per move (2/3/4): out 4/15/7, in 3/39/19. Playbook `n_evidence`
median: 50 for both groups. The proposed ">= 2 distinct calls" rule would remove 3 of
the 26 out-of-repertoire moves and 2 of the 61 in-repertoire ones -- it does not
identify the problem set. A stricter ">= 3" rule removes 12/26 but also 11/61 good
moves. There is an association (in-repertoire moves are better evidenced on average)
but it is far too weak to be a generation rule.

**Two better readings of the 26, both from the data already in hand:**

1. **Much of "out of repertoire" is small-n.** The benchmark measured each scenario on
   11-26 of Naren's calls. A move he genuinely says on 1 call in 10 shows <= 1
   instance in 15 calls 55% of the time. Twelve of the 26 were said exactly once
   (1/11 to 1/26); at the median benchmark rate they are indistinguishable from the
   in-repertoire tail. The in/out split at ">= 2 calls" is a power floor for the
   repertoire report (it keeps p_hat estimable), not a verdict on the move.
2. **The moves that were said ZERO times in 11-16 calls are described at a level he
   does not state whole.** Names like "Transition to an omnichannel distribution
   strategy", "Enforce job feed data integrity and highlight API...", "Structure
   campaign hierarchy and budget allocation" are ARC-level summaries of what he does
   across a call, with 3-4 real evidence quotes each. The say contract (v1, the one
   that passed its gate) credits a move only when the reply states the move's content
   whole -- and a summary of several statements is rarely stated in one reply. This is
   the same unit finding as C3 and G-S4 one level down: the evidence is real, the
   description is at the wrong grain for occurrence grading.

**What this means for the next playbook generation (a rule the census DOES support):**
not "more evidence calls", but "one statable thing per move". A move whose criterion is
a conjunction of things Naren says in different turns should be split into its
statable parts, each with its own evidence, OR be routed DO/pairwise. The routing
classification already flags MIXED moves; the census suggests the SAY class itself
contains bundled criteria that a per-reply occurrence grader can never credit. This is
a Layer C content note for the next generation, per the handoff: live playbooks are
NOT rewritten (wording-as-lever refuted; a replacement re-triggers reclassification
through the hash pins, by design).

The full 26-row table (scenario, move, evidence quotes, distinct evidence calls,
said/calls) is in `logs/layer_c_census_20260905.txt`.


### 11b. RESULTS (2026-09-05 -> 06): the run completed, G-R1 and G-R3 PASS, G-R2 downgrades the only `never` -- zero repertoire gaps are claimable today

**The run.** `tuning.yaml grader_arm: say`, `ops/run_layer_d.py --hostaddr 18.138.49.39`,
23:06 -> ~00:50 IST, log `logs/say_production_20260905.log`. 106 selected, **100
processed, 0 failed**, 6 excluded by the fail-closed speaker gate (the same 6 as the
pairwise run). 1,206 moments -> 621 graded / 395 deferrals / 186 interjections / 3
silence -- identical segmentation to the pairwise run, as it must be (same arm-e
moments, only the grader changed). 1,205 say events written under run
`137706da74c6`; the Naren benchmark pass was skipped by the copied checkpoints
(`"naren": {"scenarios": 0}`), so the 1,001 benchmark events G-S4 and W0 were
measured on are byte-for-byte the rows they were. CSM say verdicts: 1,464 miss /
125 hit / 27 partial / 73 unscored (4.3% -- the quote gate refusing unverifiable
credits, the arm working as designed). `move_performance` rebuilt: 416 rows, 78 of
them csm/say. `grader_arm` flipped back to `pairwise` at 00:52 before any report
was read.

**The report** (`ops/run_layer_d.py --report-combined`, saved as
`logs/combined_report_20260906.log`), repertoire section for Madhumita:

| state | cells (of 61 in-repertoire moves) |
| --- | --- |
| uses it | **33** |
| never | 1 (before G-R2; 0 after, see below) |
| insufficient data | 27 |

Her routed-call count per scenario runs from 0 (five scenarios where her calls
never route -- pricing, forecasts, stakeholder translation) to 54
(application_volume). Every "uses it" cell carries her verified quotes; every
"insufficient" cell says how many calls it still needs.

**G-R1 blind output audit: PASS, 89.6%.** `--audit-say` built 2 packets / 40
moments (24 with a positive model claim, 16 miss-only, stratified by scenario); two
fresh Sonnet readers, packet-only, both reads persisted
(`artifacts/layer_d_oa_say_reader{1,2}.json`; model verdicts in
`layer_d_oa_say_model_verdicts.json`, never shown to a reader).

| | exact 3-way | binary said/not-said | n |
| --- | --- | --- | --- |
| pooled (the pre-registered number) | **181/202 = 89.6%** (bar >= 70%) | 183/202 = 90.6% | 202 |
| reader 1 | 89/101 = 88.1% | 89.1% | 101 |
| reader 2 | 92/101 = 91.1% | 92.1% | 101 |
| reader 1 vs reader 2 | 100/109 = 91.7% | 92.7% | 109 |

Confusion (model, reader), pooled: miss/miss 145, hit/hit 31, **hit/miss 11**,
partial/partial 5, miss/hit 4, partial/miss 3, partial/hit 2, miss/partial 1. The
readers are on the same level as the pairwise audits (97.9% / 92.7%) and agree with
each other as often as with the model. The one asymmetry worth naming: of 21
disagreements, 14 are the model crediting where a reader did not (hit->miss 11,
partial->miss 3) and 5 the reverse -- the model is slightly the more generous
party. That means a "uses it" built on a single hit has roughly a 1-in-4 chance
the reader would have called it no; "uses it" cells with >= 2 instances are solid,
and the report already shows the count.

**G-R2 spot-read of every `never` cell: the one cell SURVIVES the content bar
and FAILS the power rule after correction.** The single never cell --
attribution_and_funnel_tracking M1 "Explain Attribution Mechanisms and Operational
Edge Cases", Naren 6/20 calls (every ~3), her 0 of 9 calls with n_needed = 9 --
has 9 scored moments on 9 distinct calls. Packet `artifacts/layer_d_never_cells_CSM_MADHUMITA.txt`;
my own read and an independent Sonnet read (`layer_d_never_cells_read1.json`)
agree exactly: **8 OK, 0 MISROUTED, 1 NOT_HER** -- moment 2's "reply" is
`"Sounds good. Sounds good. Okay."`, a backchannel the interjection guard let
through (it clears the >= 5 content-word bar on word count alone). 8/9 = 89% >=
80%, so the cell is not a segmentation artifact. But striking that moment removes
its call, and **8 valid calls < 9 needed: under the power rule the cell is
`insufficient data`, one call short.** It is downgraded. The report as generated
shows it under NEVER; the report as READ has zero never cells. This is the rule
doing exactly what it was frozen to do -- a zero that is one call short of
significance is not a gap.

**G-R3 power rule: PASS** -- enforced per cell in `repertoire.classify`, pinned by
`tests/test_layer_d_repertoire.py` (suite 1,664 passing), including the strict
boundary the pre-spend audit found (`n_needed(19/20) == 2`).

**What this says, in plain terms.** Madhumita verifiably uses 33 of the 61 moves
in Naren's repertoire -- more than half -- with quotes behind every one. Of the 28
she has never been seen using, 27 sit on scenarios where she has had too few
routed calls for a zero to mean anything (median n needed 13-23; her median on
those scenarios is 1-7 calls), and the one that was measurable is one call short.
**There is no repertoire gap the data can carry today.** That is a real result,
not a null: the instrument passed its audit, the rule held, and the honest answer
is "she covers the repertoire broadly and we cannot yet say what she never does."
Every additional ingested call on her thin scenarios moves cells out of
insufficient; the attribution cell needs exactly one more clean routed call.

**Two things the run exposed, for the queue (not fixed tonight -- instrument
changes mid-gate are exactly what pre-registration forbids):**
1. **The interjection guard has a word-count hole.** 6 of 621 graded CSM moments
   (1%) are <= 8 words, all backchannels ("Got it. Sounds good. Sounds good.",
   "Hi, Jim. Hello. Hey. Hi. Welcome."); 2 are <= 5 words. Tiny in volume, but one
   landed in the one cell where it mattered. A content-word rule that also
   requires a verb or a noun phrase would catch these; it is a `_v4` checkpoint
   bump and a regrade of the affected moments, i.e. an operator decision.
2. **The say arm is slightly generous on single hits** (14 of 21 disagreements).
   The repertoire report is robust to this by construction (any verified instance
   is an instance, and the count is shown), but a future rate-style use of these
   verdicts should not assume symmetric error.

**Spend.** ~340 gateway requests for the CSM grading (621 moments in batches of
<= 6 per playbook per transcript; k=1), zero for the benchmark, zero for W0, zero
for G-R2; reader tokens for G-R1.

**State after this section.** `grader_arm: pairwise`. Say events for both
populations in `move_events`; `--report-combined` prints repertoire + say-rate +
pairwise sections from stored data at zero spend. The say-rate section still
prints its dead-check flags for ~84 cells -- that is the G-S4 finding restated
every time, and the operator may want it demoted to a one-line count.


### 11c. The interjection guard, tightened (_v4) -- operator decision 2026-09-06, registered BEFORE the relabel

**Decision.** The operator chose option 2 from §11b: close the word-count hole. Done as
an instrument change with a checkpoint bump, not a per-cell patch.

**The rule (`layer_d/signals.is_substantive_reply`, applies to the CSM response window
only).** A reply is substantive iff (1) it has >= 5 DISTINCT content lemmas
(alphabetic, non-stop; "Sounds good. Sounds good." counts once), AND (2) at least one
sentence (split on . ? !) carries >= 3 content words -- an actual clause. Measured
before choosing, over all 621 graded CSM replies of run `137706da74c6`:

| candidate rule | replies reclassified | catches the 6 known backchannels? |
| --- | --- | --- |
| v3: >= 5 content words | 0 (the baseline) | no |
| "has a verb" | 4 | no ("Sounds" is a verb) |
| >= 5 distinct lemmas AND a clause of >= 4 | 37 | yes, but sweeps real questions |
| **>= 5 distinct lemmas AND a clause of >= 3 (chosen)** | **20 (3.2%)** | **yes** |

Of the 20: six are the known backchannels, ten more are closings and acknowledgement
strings ("Got it. Got it. Makes sense. Okay. Yeah. Makes sense. I'll have to ask."),
and about four are thin clarifying questions ("And then started, does it mean they've
started at the client's location?") -- the collateral, accepted: a four-content-word
question carries no gradeable playbook content, and the P0 guard exists precisely
because fragments were being scored as losses. The exemplar-substantive filter on
Naren's candidates is NOT changed (that would alter every pairwise judgment's
reference and require a real regrade).

**Why the regrade is a relabel, and exact.** The _v4 rule is strictly stricter than
_v3: it only ever turns graded replies into interjections, never the reverse, and an
interjection is stored ungraded (`response_outcome='interjection'`, `verdicts='[]'`).
A fresh _v4 run over the same transcripts would therefore produce the _v3 events with
those 20 moments relabelled -- in BOTH arms, since both graded the same moments -- and
nothing else. `ops/reclassify_interjections_v4.py` does exactly that: backs up the 40
affected rows (full row, both arms) to `artifacts/layer_d_v4_reclassified_backup.json`,
relabels them, copies the _v3 checkpoint rows to their _v4 layer strings (so a future
batch resumes instead of re-grading ~700 requests), and rebuilds `move_performance`.
The Naren benchmark is untouched (its pass never used the guard).

**What gets re-checked after the relabel, decided now:**
1. `--report-combined` regenerated; the repertoire section re-read. The attribution
   cell must now show 8 calls (it loses the backchannel's call) and sit under
   INSUFFICIENT. Any NEW `never` cell gets the full G-R2 read (cannot appear in
   principle -- removing moments only lowers call counts -- but it is checked, not
   assumed).
2. G-R1 is unaffected in principle (agreement is measured on graded moments); if any
   of the 20 relabelled moments was in the 40-moment audit sample, the score is
   recomputed without it and both numbers are reported.
3. The pairwise report's top scenarios before/after are diffed; drift beyond the
   attempt counts the 20 moments account for is a bug, not a finding.
4. Deferral-rate doc: the interjection bucket becomes 206/1,206 (17.1%); the
   deferral figure (395) does not move -- that separation is the reason the bucket
   exists.


**11c RESULT (2026-09-06, applied as registered).** Pre-spend audit of the guard and the
relabel script: the "strictly stricter" claim verified TRUE (distinct-lemma count <=
content-word count, same spaCy pipeline, same stored string); one MAJOR finding fixed
before running -- a re-run would have overwritten the only backup of the _v3 verdicts,
and the updates were autocommitted rather than one transaction; both fixed (refuse to
overwrite; `conn.transaction()`), plus two minor assertions. Suite 1,677 passing.

`ops/reclassify_interjections_v4.py --apply` (log `logs/reclassify_v4_20260906.log`):
**20 moments, 40 rows relabelled** (both arms), full-row backup in
`artifacts/layer_d_v4_reclassified_backup.json`, _v3 checkpoints copied to _v4 for all
four layers (100 / 100 / 33 / 33), `move_performance` rebuilt (416 rows). CSM outcomes
are now identical in both arms: **601 csm / 206 interjection / 395 other_joveo / 3 none**
(was 621 / 186 / 395 / 3 -- the deferral figure did not move, by construction).

Post-checks, as registered:

| check | before (_v3) | after (_v4) | reading |
| --- | --- | --- | --- |
| repertoire: uses it / never / insufficient | 33 / 1 / 27 | **33 / 0 / 28** | the attribution cell is now "0 of 8 calls (9 needed)" under INSUFFICIENT -- the code now says what the G-R2 read said |
| new `never` cells | -- | 0 | none, as expected (removing moments only lowers counts) |
| G-R1 (items 28 and 29 of the sample were relabelled moments; recomputed without them) | 181/202 = 89.6% | **173/194 = 89.2%** | PASS either way; binary 90.2% |
| pairwise section (DO/MIXED cells): rankable cells | 18 in 9 scenarios | 18 in 9 scenarios | unchanged set |
| pairwise attempts in rankable cells | 461 | 435 | -26, the relabelled moments' move-attempts |
| pairwise top cell (attribution) gap | 78% | 75% | drift within the removed attempts; order of the top 5 shifts by one place (testing 65% -> 60% swaps with xml_feed 63%) |
| say-arm dead-check flags | 84 | 84 | the G-S4 finding, unchanged |
| deferral rate | 395/1,205 = 32.8% | 395/1,205 = 32.8% | unchanged; interjection bucket 15.4% -> 17.1% |

**What this means.** The report's one gap is gone, and it is gone for the right reason:
the rule the code enforces now matches what a human read found. Madhumita: **33 of 61
repertoire moves in use, 28 not yet measurable, zero claimable gaps.** The pairwise
findings are stable to within the removed attempts. Instrument identity is
`layer_d_e_{pairwise|say}_gemini-3.6-flash_medium_noswap[_cls…]_v4`; any `_v3` verdict is
now stale. A future `ops/run_layer_d.py` on the same transcripts skips everything
under either arm; new transcripts grade under _v4 from the start.


## 13. The "rarely" tier -- PRE-REGISTERED 2026-09-07, before the code that applies it existed

**Operator decision (2026-09-07):** try a frequency comparison BETWEEN "uses it" and "never",
on high-volume scenarios only. Zero grading spend: it reads the say verdicts already in
`move_events`.

**Why this is not §9(a) again.** §9 rejected rate-gap coaching because at 8-20 calls per
cell the per-cell standard error (8-13 points) swamps any plausible gap -- confident-looking
noise. This tier applies only where her call count is large enough that the error bar is a
fraction of the gap, and it carries Naren's OWN uncertainty (his benchmark cells on the
eligible scenarios have only 11 calls each -- measured 2026-09-07) through an exact test
instead of treating his rate as a fixed floor. G-S4's dead-check floor is not used at all.

**Eligibility (per cell, all required):**
- state would otherwise be `uses it` (>= 1 verified instance; `never`/insufficient are
  untouched by this tier);
- her routed calls on the scenario >= 30 (`MIN_CSM_CALLS_RATE`);
- Naren's benchmark calls on the scenario >= 8 (`MIN_NAREN_CALLS_RATE`, the project's
  `min_attempts_to_rank`);
- opportunity parity: her scored moments per call >= 0.5 x Naren's on that cell
  (`storage.get_say_densities`) -- a side that gets fewer chances per call is not
  compared on rate.
Today that is 9 cells: application_volume_and_prioritization (her 53 calls / his 11),
job_board_budget_and_direct_agreements (34 / 11), programmatic_advertising_scope_and_capability
(33 / 11). Nothing else qualifies until more calls are ingested.

**The test (frozen).** One-sided Fisher exact test on the 2x2 table
[[her said-calls, her not-said calls], [his said-calls, his not-said calls]], alternative
"her rate is lower". A cell is **`uses it, rarely`** iff p < 0.05 AND her call-level rate is
below half of Naren's (an effect-size guard: a statistically real 35%-vs-45% difference is not
coaching material). Otherwise it stays `uses it`. Report line: her count and rate, his count
and rate, the p-value, the moments-per-call on both sides, Naren's verbatim deployments,
and her verified quotes (so the reader sees what she DID say the times she said it).

**Gates before anything is shown:**
- **G-R4a (code):** the tier is enforced per cell and pinned by tests -- eligibility
  thresholds, the effect-size guard, the opportunity guard, and that `never`/insufficient
  cells are never touched.
- **G-R4b (spot-read):** every flagged cell's moment population gets the same blind read
  as the `never` cell (OK / MISROUTED / NOT_HER, >= 80% OK to survive), because a "rarely"
  built on mis-routed or non-CSM moments is the same artifact as a "never" built on them.
  The struck moments are removed from her count and the test re-run; a cell that drops
  below significance after the strike is demoted to `uses it`.

**Expected yield, written down now:** 0 to 3 of the 9 eligible cells. Zero is an
acceptable result and will be reported as such. If it flags cells, they are the first
frequency-based coaching lines this system has produced, and they apply to three
scenarios; this tier does not widen to the other 27 scenarios until they reach 30 calls.

**Not done, deliberately:** no floor, no prompt change, no change to which moments are
graded, no change to the `never` rule.
