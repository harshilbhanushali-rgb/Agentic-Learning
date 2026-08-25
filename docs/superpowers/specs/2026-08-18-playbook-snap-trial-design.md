# Playbook Snap Trial — Verbatim Repair Successor (2026-08-18)

**Status: FROZEN. Direction operator-approved 2026-08-18 ("the snap thing — run it");
gates below are frozen before any code exists and are never adjusted after a result.**

Predecessor: `2026-08-18-scenario-playbook-trial-design.md` — METHOD NOT VALIDATED
solely on PB0 (one altered quote in one real playbook; veto-audited real). PB2 won and
survived a side-flip veto audit; PB3 passed. This successor changes exactly ONE
pipeline variable — a deterministic post-synthesis verbatim-repair stage ("snapping")
— plus the two instrument fixes the predecessor put on the record. Model unchanged
(`gemini-3.5-flash-lite` outputs reused), evidence unchanged, placebo construction
unchanged, reader protocol unchanged.

## 1. Question and decision rule

**Question:** with mechanical verbatim repair between synthesis and gating, does the
playbook pipeline pass citation fidelity while still beating its placebo blind?

**Decision rule (frozen): METHOD VALIDATED iff PB0(snapped) passes 5/5 real playbooks
AND PB2(snapped, counterbalanced) is WON (≥ 4/5 scenarios, validity holding).**
PB1 (resized, §5) and PB3 stay secondary. A document reduced below the schema floor by
snapping (< 3 key moves) FAILS PB0 — snapping must not be able to launder a hollow
document into a pass. NULL IS A REAL RESULT.

## 2. Inputs (frozen artifacts, reused — zero Gemma spend)

The predecessor's `pb_evidence.json` and `pb_playbooks.json` are the inputs, byte-frozen.
Snapping is deterministic, so re-synthesis would only resample the same distribution at
30+ chat calls' cost; reusing the pilot's documents also gives exact attribution — same
documents, only the repair stage differs. Both arms (real and placebo) are snapped
symmetrically. No stage writes to any predecessor artifact.

## 3. The snap stage (frozen algorithm)

For every citation `{quote, call, account}` in a document (key_moves evidence,
signature_language, pitfalls evidence), against the document's OWN evidence set
(real → its scenario's selection; placebo → its donor slice, as before):

1. Candidates = the normalized (`norm_quote`) `response_text` then `trigger_text` of
   each evidence pair from the cited call, in recorded evidence order.
2. If the normalized quote is already a substring of a candidate → KEEP unchanged.
3. Else, per candidate, align with `difflib.SequenceMatcher(None, quote, text,
   autojunk=False)`; take the minimal text span covering all non-empty matching blocks;
   score = `SequenceMatcher(None, quote, span).ratio()`. Best candidate = highest
   score, ties to the earlier candidate in scan order.
4. Score ≥ **0.80** → SNAP: the citation's quote becomes that exact span (stripped).
   The predecessor's 16 failures all scored ≥ 0.87 on this family of measure, so 0.80
   repairs the observed failure mode with margin while a fabricated quote (no real
   source passage) has no 0.80 span to snap to.
5. Score < 0.80, or the cited call absent from the evidence set, or the stripped span
   empty → DROP the citation (a claim that cannot be tied to real text loses its
   evidence, and with it its place).
6. After drops: a key move with < 2 remaining citations is dropped entirely (and
   removed from `arc`); signature/pitfall entries with no remaining citation are
   dropped. A document left with < 3 key moves is marked `schema_collapsed` and FAILS
   PB0 by rule (§1). `call`/`account` fields are never altered by snapping.

Everything is logged per document: kept / snapped / dropped counts, per-citation
scores, dropped moves. Snapping is pure and unit-tested; identical inputs → identical
outputs.

## 4. PB0 / PB2 / PB3 on the snapped documents

- **PB0:** the predecessor's matcher, unchanged (same normalization, same
  one-bad-quote-fails rule, account checks, symmetric on placebos), run on the SNAPPED
  documents. PASS = 5/5 real (schema-collapsed counts as FAIL). Kept/snapped citations
  pass by construction — PB0 remains the independent verification that the snap stage
  actually delivers what it promises; any failure it finds in a snapped document is a
  harness bug → veto audit.
- **PB2:** new packet from the snapped documents, predecessor protocol with the
  **counterbalancing fix (frozen):** walking the pilot scenarios in rank order, the
  real document takes side A at odd positions (1st, 3rd, 5th) and side B at even
  (2nd, 4th) — a deterministic rule, never an independent coin, so a degenerate
  all-one-side draw is impossible. Item order still seed-42 shuffled; NEG singles
  rebuilt from the snapped documents by the same `build_neg`; 3 valid fresh sonnet
  readers dispatched one at a time (validity = answer everything + reject ≥ 4/5 NEG,
  max 5 dispatches); judgments committed before the key opens; scenario real-preferred
  iff ≥ 2/3 valid readers; **WON = ≥ 4/5 scenarios.** Duplicate-reader guard carries
  over.
- **PB3:** unchanged (blind APPLY/VAGUE per key move of the snapped documents, move
  APPLY iff ≥ 2/3 readers, PASS = median real APPLY share ≥ 0.5).

## 5. PB1, resized (secondary, frozen)

The predecessor measured its 60%-of-available-accounts span bar as arithmetically
near-unreachable at 12–16 quotes/document. Resized denominator: a real playbook passes
PB1 iff (a) every key move cites ≥ min(3, available accounts) distinct accounts, AND
(b) its distinct cited accounts ≥ 60% of **min(available accounts, total citations in
the document)**. Overall PASS = ≥ 4/5 real. Secondary, never decisive.

## 6. House rules binding this trial

Frozen gates; one pre-run blind CODE audit of the new code (strong model), findings
fixed and recorded in §8 before the run; readers/outcome checks on sonnet, subagents
one at a time; unexpected gate/placebo results veto-audited before belief; zero
Postgres; zero embedding spend; zero Gemma spend (reuse is the design); no predecessor
artifact overwritten — all outputs new under `Brain/artifacts/` as `pbs_*`; stages
refuse to clobber. Local stages run inline (all are seconds-fast; no visible window
needed — nothing long-running or gateway-bound in this trial).

## 7. Harness, artifacts, tests

`calibration/playbook_snap_trial.py`, importing the predecessor's pure functions
(`norm_quote`, `pb0_doc`, `render_doc`, `build_neg`, `score_read`, `iter_cited`) —
never re-implementing them. Stages: `--snap` (→ `pbs_playbooks.json` with snap logs),
`--pb0` (→ `pbs_pb0_report.json`), `--build-read` (→ `pbs_read_packet.txt` +
`pbs_read_KEY.json`), `--score` (`pbs_judgments_*.json` + key → `pbs_report.json`).
`tests/test_playbook_snap_trial.py`: kept/snapped/dropped paths, snap determinism,
snapped-quote-passes-PB0 property, move/document collapse rules, counterbalance rule,
resized PB1, threshold boundary.

## 8. Pre-run blind code audit findings

Audit ran 2026-08-18 (strong model, blind: spec + harness + tests + predecessor),
before the run. Verdict: effectively clean — no verdict-bearing defect; 4 low-severity
findings, 3 fixed, 1 no-change:

- **F1 (FIXED):** the PB0 "harness bug" banner over-claimed — it also fired on
  `schema_collapsed` (a legitimate result per §1) and would fire on an account
  mismatch (a data defect snap never touches). The banner now labels quote-level
  failures (harness bug), account mismatches (data defect), and collapse (result)
  separately. JSON verdicts were already correct.
- **F2 (FIXED):** `build_neg` would crash on a schema-collapsed document with zero
  key moves; empty documents are now excluded from the NEG source pool (loud-crash
  robustness only; cannot fire on the frozen inputs, all 16 near-misses ≥ 0.87).
- **F3 (no change, verified):** two predecessor guards on NEG-header selection were
  dropped — the `is_coachable` filter is redundant (`ranking` is built over coachable
  keys only) and the shortage guard cannot bind (≥16 candidates for 5 slots); a
  hypothetical shortage fails conservative (readers go VOID), never falsely VALIDATED.
- **F4 (FIXED):** the §7-promised threshold-boundary test was missing; added
  (score == 0.80 snaps, 0.7999 drops — pins the ≥ semantics).

Verified sound: no snap-laundering path (spans always come from the cited call's own
evidence; a 0.80-scoring span is length-bounded so scattered matches cannot clear it),
kept/snapped quotes pass PB0 by construction (same normalization both sides, idempotent
on normalized substrings), collapse rules airtight against PB1/PB3 leakage,
counterbalance consistent between packet and key, duplicate-reader guard inherited, no
glob collision with predecessor artifacts, all stages clobber-refusing, decision rule
exactly §1. After fixes: 14/14 tests pass.

## 9. RESULTS (2026-08-18, all gates as frozen)

**METHOD VALIDATED — PB0(snapped) PASS (5/5 real, 10/10 overall) ∧ PB2 WON (5/5
scenarios, 14/15 votes, counterbalanced sides).** Zero Gemma spend, 3 sonnet readers.

- **Snap stage** (`pbs_playbooks.json`): real documents nearly untouched — 0 snapped,
  1 dropped (the predecessor's spliced `publisher_mix` quote scored under 0.80 on the
  covering-span measure and was dropped; its move kept 3 citations). Placebos took the
  repair load: 7 snapped + 7 dropped, 2 moves dropped (each still ≥ 3 moves). **No
  document schema-collapsed** — snapping could not and did not launder a hollow pass.
- **PB0(snapped): PASS** — 10/10 documents, 0 bad quotes, real AND placebo
  (`pbs_pb0_report.json`). The by-construction claim held; no veto trigger fired.
- **PB2: WON** — counterbalanced real sides A/B/A/B/A (a degenerate draw now
  impossible); 3/3 fresh sonnet readers VALID (5/5 NEG rejected each); **real preferred
  in 5/5 scenarios, 14/15 pooled votes** (descriptive sign p = 0.00098), 4/5 scenarios
  unanimous. Readers' choices tracked the real document across both sides — including
  `multi_channel_spend_and_board_optimization` (3/3), the pair the predecessor's veto
  audit had flagged as position-confounded; under counterbalancing it discriminates
  cleanly. The single dissenting vote was one reader on `publisher_mix` (2/3, still
  preferred).
- **PB3: PASS** — blind APPLY shares 0.5 / 0.75 / 1.0 / 1.0 / 1.0, median **1.0**
  (bar 0.5).
- **PB1 (resized): 0/5, secondary flag.** The resized span bar now behaves (spans
  0.33–0.79 vs the predecessor's 0.25–0.48; 3/5 clear 0.60) — the remaining failures
  are all on the per-move prong: every document has ≥ 1 key move citing < 3 distinct
  accounts. A real breadth readout at last: synthesis concentrates some moves on 1–2
  accounts even with 16–30 available. Scale-up guidance, never decisive.

**Reading:** the predecessor's sole failure (verbatim fidelity) is fully repaired by a
deterministic stage costing nothing, while the discrimination signal not only survived
re-measurement under a sound instrument — it strengthened (14/15 vs the predecessor's
confounded 15/15, now with sides counterbalanced and the previously-confounded pair
discriminating cleanly). The pipeline (synthesis → snap → PB0/PB2/PB3) is validated on
the frozen 26-scenario map; per §5 of the predecessor's handoff, scale-up should
coordinate with the union-corpus taxonomy rebuild.
