# HANDOFF — playbook pilot RAN: not narration, failed on verbatim fidelity (2026-08-18)

Supersedes `HANDOFF_PLAYBOOK_TRIAL_2026-08-18.md` (that trial is now DONE, all five
steps: spec → harness+tests → blind audit → pilot → scored/written up). Read the spec's
RESULTS (`docs/superpowers/specs/2026-08-18-scenario-playbook-trial-design.md` §11),
the findings file (`docs/findings/scenario-playbook-trial.md`), and the last section of
`PROBLEMS_AND_FIXES.md` before proposing anything.

## 1. THE VERDICT (frozen gates, not re-litigable)

**METHOD NOT VALIDATED** — by the frozen decision rule (PB0 PASS ∧ PB2 WON):

- **PB0 citation fidelity FAILED 4/5 real** (one altered quote in `publisher_mix::real`;
  veto-audited by hand — a genuine model edit, "That"→"This" + a splice, NOT a matcher
  or normalization bug). Placebos passed only 1/5 (~14x the alteration rate — grounding
  pressure measurably bends quotes).
- **PB2 blinded discrimination WON** — 5/5 scenarios, 15/15 votes — and survived a veto
  audit forced by a degenerate side draw (real landed on side A in ALL 5 pairs, 1/32):
  a side-flipped re-render with 3 fresh readers still cleared the bar (4/5, 11/15;
  26/30 pooled). One restriction: `multi_channel_spend_and_board_optimization` went
  unanimous side-A in BOTH orientations — position-driven, indistinguishable.
- **PB3 PASS** (median blind APPLY share 0.75). **PB1 0/5** but its 60% account-span
  bar is arithmetically near-unreachable at 12–16 quotes/document (on the record).

**The headline that matters for the program: the V1 narration failure did NOT recur.**
This is the first Layer C instrument ever to beat its placebo. The failure is verbatim
quote fidelity — mechanical, detected for free by PB0.

## 2. THE LIVE MOVE (operator decision, not started)

**Successor trial: same design + mechanical verbatim repair.** One new stage between
synthesis and PB0: for each near-miss quote, find its best exact-substring match in the
document's OWN evidence (the veto audit already proved 16/16 failures have one at
difflib ≥ 0.88) and snap the quote to it; a quote with no adequate match is dropped
with its claim. That directly targets the only failed gate. It is a HARNESS change —
new spec, gates re-frozen (carry PB0/PB2/PB3 as-is), pre-run audit, its own pilot.
Two instrument fixes to bake into any successor, both earned here:

1. **Counterbalance pair sides deterministically** (e.g. real on A for odd pilot ranks,
   B for even) — never an independent coin per item; the 1/32 degenerate draw happened
   on the first try and cost a full veto-audit read to untangle.
2. **Size the PB1 span bar to the document's quote budget**, not the pool's account
   count.

Also open from before (unchanged): the union-corpus taxonomy rebuild (G-XP1: 64.3% of
new pairs sink — more scenarios exist than the frozen 26); playbook scale-up should
coordinate with it if the successor validates.

## 3. WHAT EXISTS (nothing published was touched)

| | |
| --- | --- |
| spec (frozen, results filled) | `docs/superpowers/specs/2026-08-18-scenario-playbook-trial-design.md` |
| harness + tests | `calibration/scenario_playbook_trial.py`, `tests/test_scenario_playbook_trial.py` (36) |
| evidence + playbooks | `artifacts/pb_evidence.json`, `artifacts/pb_playbooks.json` (10 docs, 32/50 chat attempts) |
| gates | `artifacts/pb_pb0_report.json`, `artifacts/pb_report.json` |
| frozen read instrument | `artifacts/pb_read_packet.txt` + `pb_read_KEY.json`, `pb_judgments_r{1,2,3}.json` |
| veto-audit instrument | `artifacts/pb_read_packet_flip.txt` + `pb_read_KEY_flip.json`, `artifacts/pb_veto_audit_flip.json` |
| logs | `logs/pb_select.log`, `logs/pb_synth.log` |

The 10 synthesized playbooks themselves are worth an operator read — they are the first
concrete product-shaped output of this program (`pb_playbooks.json`, `documents.*::real`).

## 4. HOUSE RULES (all held this session; unchanged)

Frozen gates (two veto audits fired — PB0's confirmed the failure real, PB2's sustained
the win with a restriction — neither gate was adjusted). Subagents one at a time;
readers + outcome checks on sonnet, code audit on the strong model. Zero Postgres, zero
embedding spend, no published-artifact overwrites, visible windows + completion pings
(NOTE: `run_visible.ps1` logs are UTF-16 — pipe through `iconv -f UTF-16LE` before
grepping a ping condition). Budget discipline: 32/50 chat attempts, counted per POST,
persisted pre-attempt.
