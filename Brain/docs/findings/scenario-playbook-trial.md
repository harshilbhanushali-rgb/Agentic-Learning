# Scenario-Playbook Pilot — Not Narration, but One Altered Quote Is Fatal (2026-08-18)

[Findings index](INDEX.md)

### The trial (spec-frozen, operator-approved before code)

Spec `docs/superpowers/specs/2026-08-18-scenario-playbook-trial-design.md`; harness
`calibration/scenario_playbook_trial.py` (+36 tests); pre-run blind code audit's one
outcome-bearing finding (duplicate judgment files could double-count a reader's PB2
votes) fixed pre-run and recorded in spec §10. Direction chosen after the gold-pair
probe: milestones-as-recurring-clause-clusters demand recurrence the corpus lacks, so
the target moved to one evidence-cited playbook per scenario, gated against the V1
narration failure.

Design: 5 pilot scenarios at ranks 1/5/10/15/20 by routed-pair count on the 12,444-pair
union substrate (PB-F0 = the pool-unit V0 check, PASS 26/26); 50 evidence pairs per
scenario by account-floor + greedy max-min on cached gemini@3072 response vectors (zero
embedding spend); map-reduce synthesis on `gemini-3.5-flash-lite`, `no_cache=True`,
32 of 50 budgeted attempts; per scenario a PLACEBO twin synthesized identically from a
count-matched NON-pilot donor scenario's evidence under the real scenario's header.

### Results (all bars as frozen)

| gate | result |
| --- | --- |
| PB0 citation fidelity | **FAIL — 4/5 real** (1 altered quote); placebo 1/5 (symmetric) |
| PB1 account breadth | 0/5 (secondary flag; bar shown arithmetically miscalibrated) |
| PB2 blinded discrimination | **WON — 5/5 scenarios, 15/15 votes**; veto-audited, sustained with one restriction |
| PB3 usefulness floor | PASS (median blind APPLY share 0.75) |
| **decision (PB0 ∧ PB2)** | **METHOD NOT VALIDATED** |

1. **PB0's veto audit confirmed the failure is real and characterized it exactly:**
   all 16 failing quotes (both arms) near-match the correct cited call at difflib
   0.88–0.995; the diffs are model edits — dropped stutters/fillers, one-word swaps
   ("That"→"This") — not matcher or normalization bugs. Real-arm alteration rate
   ~1.4%/quote; one altered quote is fatal by frozen design.
2. **Placebos altered quotes at ~14x the real rate (1/5 pass vs 4/5)** — forcing
   synthesis from header-mismatched evidence makes the model bend quotes toward the
   header. Grounding pressure is real and measurable.
3. **PB2's seed-42 side draw degenerated** (real on side A in all 5 pairs, p=1/32), so
   the unanimous 15/15 could not exclude position bias; the veto audit re-rendered the
   packet with sides inverted (byte-identical NEGs) for 3 fresh readers: 4/5 scenarios,
   11/15 votes — content-tracking confirmed, 26/30 pooled. **Restriction:**
   `multi_channel_spend_and_board_optimization` went unanimous side-A in BOTH
   orientations — position-driven, indistinguishable, not a real win
   (`artifacts/pb_veto_audit_flip.json`).
4. **The V1 failure mode did not occur.** Readers strict enough to reject 15/15 + 15/15
   scrambled negatives still separated real from placebo in both orientations, and
   rated a median 75% of real key moves concretely applicable, blind.

### What transfers

- **Synthesis over routed+diversity-sampled evidence is NOT narration on this corpus** —
  the first Layer C instrument ever won against its placebo (every clustering-side read
  this month lost or tied). The scarce commodity being recurrence, the document-level
  target fits the corpus in a way the cluster-level target measurably did not.
- **The binding defect is verbatim fidelity, and it is mechanical.** PB0 detects it for
  free; the natural successor design adds post-synthesis verbatim snapping (replace each
  near-miss quote with its best exact-substring match from the document's own evidence)
  — a harness change requiring its own pre-registration, not a re-scoring of this trial.
- **Instrument lessons:** counterbalance pair sides deterministically (odd/even rank),
  never an independent coin per item — a 1/32 degenerate draw happened on the first
  try; size any account-span bar to the document's quote budget, not the pool's account
  count (12–16 quotes cannot span 60% of 19–30 accounts).

Artifacts: `pb_evidence.json`, `pb_playbooks.json`, `pb_pb0_report.json`,
`pb_read_packet.txt`+KEY, `pb_judgments_r{1,2,3}.json`, `pb_report.json`,
`pb_read_packet_flip.txt`+KEY, `pb_veto_audit_flip.json`. Full narrative:
`PROBLEMS_AND_FIXES.md`.

### The successor ran same-day: snap trial VALIDATED the method (2026-08-18)

Spec `docs/superpowers/specs/2026-08-18-playbook-snap-trial-design.md` (frozen
pre-code; own blind audit clean, 3 small findings fixed). Harness
`calibration/playbook_snap_trial.py` (+14 tests). One variable changed: the
deterministic verbatim-snap stage sketched above (keep verbatim; snap near-misses
≥ 0.80 alignment onto the exact evidence span; drop the rest, with collapse rules so a
hollowed document FAILS). Inputs = the pilot's frozen synthesis artifacts — zero Gemma
spend; both instrument fixes applied (counterbalanced sides A/B/A/B/A, quote-budget
PB1 denominator).

- **Snap load confirmed the diagnosis:** real docs 0 snapped / 1 dropped; placebos
  7 snapped / 7 dropped / 2 moves dropped; nothing collapsed.
- **PB0(snapped) PASS 10/10** (0 bad quotes, both arms).
- **PB2 WON 5/5 scenarios, 14/15 votes** (descriptive p=0.001), 3/3 fresh readers
  valid, 4 scenarios unanimous — including the previously position-confounded
  `multi_channel` pair, which discriminates cleanly under counterbalancing.
- **PB3 median blind APPLY share 1.0. PB1(resized) 0/5** — spans now healthy
  (0.33–0.79); every failure is the per-move prong (≥ 1 move per doc citing < 3
  accounts): a real breadth readout for scale-up, no longer a length artifact.

**METHOD VALIDATED (PB0 ∧ PB2, as frozen)** — the first Layer C product path ever to
pass its own placebo test. Scale-up coordinates with the union-corpus taxonomy rebuild
(G-XP1: 64.3% of new pairs sink), then derives Layer D coarse checks from the
playbooks' scorable-check sections. Successor artifacts: `pbs_playbooks.json`,
`pbs_pb0_report.json`, `pbs_read_packet.txt`+KEY, `pbs_judgments_r{1,2,3}.json`,
`pbs_report.json`.

## PV: the method held on the rebuilt map (2026-08-18, night — closes the scale-up question)

The union-corpus rebuild's Stage E re-ran this pipeline end to end on the new
`union_base` map (34 scenarios, 58k-turn union corpus): **PB0(snapped) 5/5, PB2 WON 4/5
(pooled 11–4, 4 unanimous, all readers 5/5 on negatives), PB3 median 0.80 → PV PASS;
the map shipped as the playbook substrate.** Two additions to this method's record:
(1) an incoherent scenario is unsynthesizable under the frozen schema (fragmented
evidence → 1-quote candidate moves) — synthesis failure is a coherence signal, not just
noise; (2) `gemini-3.5-flash` at low reasoning cleared the marginal scenario flash-lite
never could, and its document won its blinded pair 2/3 with apply 1.00. The "distinct
accounts per move" hardening was dropped after three REQUIREMENT wordings each broke
schema compliance — PB1 stays a reported flag, never a prompt constraint. Full record:
[union-taxonomy-rebuild.md](union-taxonomy-rebuild.md).
