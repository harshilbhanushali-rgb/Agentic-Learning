# HANDOFF — the next Layer D question is a design decision, not a bug (2026-08-27 → 28)

Continues from `HANDOFF_LAYER_D_P0_SHIPPED_2026-08-27.md` (does not supersede it — that one's
state is still accurate: P0 shipped, regraded, output-audit re-passed). This handoff exists to
carry forward the ONE thing that session left open, and it deserves its own document because
it's the load-bearing next step, not a line item.

## 0. WHAT'S SETTLED (do not re-derive)

After P0 shipped, the natural next move looked like "rewrite the 24 blurry playbook cells."
A parallel Layer C session tested that plan against the data instead of executing it, and it
died on contact — properly, with five blind nulls and one self-corrected near-miss:

- **Wording does not predict pairwise blurriness.** Adjective count, criterion length,
  bundling (conjunctions), exemplar pool size — all measured blind across all 77 rankable
  cells, all null (blurry vs sharp cells are statistically indistinguishable on every one).
  Attempt volume was tested too and came back *inverted* (blurry rate does not fall with more
  data) — a genuine counter-example exists: `ats_integration_and_api_mapping` M3 is crisply
  worded, zero adjectives, gradability-remade, and still 100% tie over 42 attempts.
- **A blind classification (a fresh subagent, packet-only, could NOT see tie rates) sorted all
  77 moves into speech-act ("say something") vs work ("do something"): 65 say / 9 do / 3
  mixed.** The pre-registered test technically passed (34% vs 11% blurry) but the session
  correctly flagged it as underpowered and ran the real significance test: **p=0.26, not
  significant** — do not treat "act-type causes blurriness" as statistically proven at the
  per-cell level. Say so plainly to anyone who wants to cite the 34%-vs-11% number.
- **What IS independently verified (I checked it myself against the actual report data, not
  just trusted the claim): tie rate averages ~68% across ALL 77 cells, and ~54-58% even among
  the 53 "good" (non-blurry) ones.** This is the real finding, and it doesn't depend on the
  underpowered significance test above. The 80%-tie cutoff used to flag "blurry" is a line on
  a continuum that runs hot everywhere, not a bimodal broken/fine split.
- **Conclusion the evidence actually supports**: 84% of this playbook (65 of 77 moves) is
  "complete once said" content — a fact either stated or not, which a comparison question
  ("who did it better") structurally cannot discriminate, no matter how the criterion is
  worded. This is the SAME shape of problem that killed the checks arm at C2/C3 (per-moment
  absolute unit wrong for arc-level moves) — one level up. Full writeup, both sessions' data:
  `docs/findings/layer-d-redesign.md`; the Layer C session's own harness is
  `calibration/layer_d_act_type_packet.py` if the classification needs re-running or
  extending.
- **Nothing was touched.** No playbook rewritten, no money spent test-and-learn style. The 24
  blurry cells are exactly as they were.

## 1. THE MAIN TASK: what question should Layer D ask of a "say-type" move?

This is an operator decision on framing, not something to delegate to a build session without
a decision first — same category of call as "pairwise vs checks" was, and it deserves the same
seriousness (that decision got a full C0–C4 ladder before anything shipped).

**The concrete problem**: pairwise ("which reply performs this move better") is the right
question for do-type moves (9 of 77) and ties near-constantly on say-type ones (65 of 77),
because once both replies have or haven't stated something, there's genuinely no "better."

**The dead end already ruled out**: reviving the old binary `checks` arm as-is won't work —
it's the SAME arm that failed C2 (53.9% discrimination, DEAD for arc-level moves, proven 4x at
C3). A say-type redesign has to be something that isn't just occurrence-checking with extra
steps.

**Sketch on the table** (from the Layer C session, not yet designed or tested): something
closer to "did they raise it, and how specifically" — an occurrence check with a graded
specificity dimension, rather than pure binary or pure comparison. This is a STARTING POINT
for design, not a spec. Concretely undecided:
- Is specificity a 2-3 level scale (none/vague/specific) or something else?
- Does it need its own exemplar-comparison step at all, or is it purely occurrence + a
  rubric-graded specificity tier?
- Does the existing quote-verification machinery (`layer_d/verify_quotes.py`,
  `quote_verify_min_overlap`) still apply, or does a say-type check need a different
  evidence-grounding mechanism?
- Does this become a THIRD `grader_arm` value alongside `checks`/`pairwise`, applied only to
  moves classified say-type, with do-type moves staying on pairwise? (Likely shape, given the
  blind classification already sorts moves into the two buckets — but confirm this doesn't
  reopen the "per-item filter" failure pattern this project has hit 9 times before; the
  classification here is at the MOVE level, fixed once per playbook move, not a per-response
  filter, which is a meaningfully different risk profile — worth stating explicitly in
  whatever design doc comes out of this, since it will get challenged.)

**Process, once a shape is picked**: this needs the same discipline as every other Layer D
instrument decision in this project — literature grounding if relevant, pre-registered gates,
a blind code audit before any spend, and a held-out measurement (does the new arm actually
discriminate on say-type moves the way pairwise does on do-type ones?) before it's trusted.
Do not skip straight to a production run on a new arm that's never been measured.

**What this is NOT**: an invitation to just try prompt variants until something looks better.
This project has a specific, repeated house lesson against exactly that (see
`docs/GOTCHAS.md`, the several "per-item filter failed" and "wording wasn't the driver, the
unit was" entries) — the fix here is almost certainly a UNIT/QUESTION change, not a wording
tweak, and the evidence above already rules out wording as the lever.

## 2. Everything else on the list (secondary — none of it is blocked by §1)

- **Report the 33% deferral rate.** Free, already measured, zero LLM spend, just needs
  writing up and showing to someone.
- **Wire the coaching report into the CS-platform frontend.** The actual usage bottleneck —
  right now nothing outside a terminal can see any of this.
- **The 4 "genuinely mixed" cells** (`campaign_level_performance_tracking` M3,
  `pixel_placement_and_tracking` M4, `downstream_activation_and_cost_metrics` M4,
  `landing_page_and_conversion_setup` M1) are the only remaining plausible rewrite candidates
  under the OLD plan — low priority, small n, and `landing_page` was already flagged by C3 as
  ~0 under every unit tested. A real pre/post needs an actual CSM regrade on the affected
  scenarios (not `--naren-only`, which does not measure pairwise tie-rate — see the correction
  in this session's transcript if that comes up again).
- **Hold off on more CSMs (P2)** until §1 is resolved — scaling an instrument that's
  structurally weak on 84% of the playbook just produces more soft signal at more cost.
- **Commit the code.** Everything from the P0 arc (three fixes, the reconnect/self-heal fixes,
  the four pooler-leak fixes) is still sitting uncommitted, locally, on
  `layer-c-profile-rebuild`. Nothing has been pushed.

## 3. House lessons this exchange re-proved

- **A blind classification is worth building even for a "soft" variable like act-type** — the
  same discipline (a fresh reader that cannot see the outcome) that's been used for every
  human-judgment check in this project generalizes past yes/no verdicts to labeling tasks too.
- **Report the underpowered test as underpowered.** The 34%-vs-11% ratio was real and would
  have been an easy, flattering thing to lead with; running the actual significance test and
  reporting p=0.26 instead is exactly the standard this project holds everywhere else, and it
  should hold here too when this gets picked back up.
- **A negative result on the assumed fix (rewriting) is still a result** — it closed off a
  plausible-sounding P1 item cheaply (zero spend, one blind classification) instead of letting
  a rewrite pass burn real effort on 24 documents that were never going to move the number.
