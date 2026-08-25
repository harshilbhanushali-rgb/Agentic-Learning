# HANDOFF — playbook method VALIDATED via the snap trial (2026-08-18, evening)

> **SUPERSEDED (2026-08-18, night)** by `HANDOFF_TAXONOMY_REBUILD_2026-08-18.md` —
> the operator picked live move 1 (scale-up sequencing): the union-corpus taxonomy
> rebuild was specced and frozen
> (`docs/superpowers/specs/2026-08-18-union-taxonomy-rebuild-design.md`), with the
> rescue decision, the routing bar, and the three-arm routing A/B pre-registration
> recorded in that spec's §0. This file remains valid history.

Supersedes `HANDOFF_PLAYBOOK_RESULT_2026-08-18.md` (its recommended live move — the
snap successor — was operator-approved and RAN same-day). Read the two specs' RESULTS
(`docs/superpowers/specs/2026-08-18-scenario-playbook-trial-design.md` §11 and
`2026-08-18-playbook-snap-trial-design.md` §9), `docs/findings/scenario-playbook-trial.md`,
and the last two sections of `PROBLEMS_AND_FIXES.md` before proposing anything.

## 1. STATE: the method is VALIDATED (frozen gates, two trials, not re-litigable)

Pipeline: routed evidence → account-floor + max-min selection on cached vectors →
map-reduce synthesis (`gemini-3.5-flash-lite`, `no_cache=True`) → **deterministic
verbatim snap** → mechanical PB0. Two pre-registered trials, both blind-audited pre-run:

| | pilot | snap successor |
| --- | --- | --- |
| PB0 citation fidelity | FAIL 4/5 real (model quote-smoothing, veto-audited real) | **PASS 10/10** (snap load: real 0 snapped/1 dropped; placebo 7/7/2 moves) |
| PB2 blind discrimination | WON 5/5 but side-draw degenerated (all-A, 1/32); flip veto audit sustained 4/5 with one position-confounded pair | **WON 5/5, 14/15 votes, counterbalanced A/B/A/B/A**; the confounded pair now discriminates 3/3 |
| PB3 usefulness | PASS median 0.75 | PASS median 1.0 |
| PB1 breadth | 0/5 (bar arithmetically broken) | 0/5 resized (real readout: ≥1 move/doc cites <3 accounts — scale-up flag) |
| verdict (PB0 ∧ PB2) | NOT VALIDATED | **VALIDATED** |

Spend across both: 32 Gemma chat attempts (of 50 budgeted), 12 sonnet readers/auditors,
zero Postgres, zero embedding spend, nothing published overwritten.

## 2. THE LIVE MOVES (operator decisions)

1. **Scale-up sequencing (the standing plan):** the pilot ran on the FROZEN 26 because
   it tests the method, not the map. Full playbook set should coordinate with the
   **union-corpus taxonomy rebuild** (G-XP1: 64.3% of new-corpus pairs sink — the
   frozen taxonomy doesn't know the new corpus's topics; rebuild = 33k-turn pool fetch
   ~28 min + Gemma adjudication + its own pre-registration). Write playbooks against
   the rebuilt map if it exists; old scenarios stay valid either way. Cost per
   scenario document: ~3 chat calls + a free snap pass.
2. **Layer D coarse checks:** every playbook carries 3–5 scorable checks
   (`layer_d_checks`) — the designed hand-down to Layer D and the frontend library's
   real data shape. Wiring them is its own design (out of scope for both trials).
3. **PB1's residual flag for scale-up prompts:** synthesis concentrates some moves on
   1–2 accounts even with 16–30 available — a prompt-level "prefer distinct accounts
   per move" hardening is worth one arm in any scale-up spec, measured by PB1's
   per-move prong.

## 3. WHAT EXISTS

| | |
| --- | --- |
| specs (frozen, results filled) | `2026-08-18-scenario-playbook-trial-design.md`, `2026-08-18-playbook-snap-trial-design.md` |
| harnesses + tests | `calibration/scenario_playbook_trial.py` (36 tests), `calibration/playbook_snap_trial.py` (14 tests) |
| pilot artifacts | `pb_evidence.json`, `pb_playbooks.json`, `pb_pb0_report.json`, `pb_read_packet.txt`+KEY, `pb_judgments_r{1,2,3}.json`, `pb_report.json`, flip veto audit (`pb_read_packet_flip.txt`+KEY, `pb_veto_audit_flip.json`) |
| snap artifacts | `pbs_playbooks.json` (**the validated documents — operator-readable product output**), `pbs_pb0_report.json`, `pbs_read_packet.txt`+KEY, `pbs_judgments_r{1,2,3}.json`, `pbs_report.json` |
| logs | `logs/pb_select.log`, `logs/pb_synth.log` |

## 4. HOUSE RULES NOTES FOR THE NEXT SESSION

All standing rules held (frozen gates — three veto audits fired across the day, zero
gates adjusted; subagents one at a time; sonnet readers, strong-model code audits;
zero Postgres; clobber-refusing artifacts). New practical notes: `run_visible.ps1`
logs are UTF-16 (pipe through `iconv -f UTF-16LE` before grepping a completion-ping
condition); counterbalance blind-read sides deterministically, never per-item coins;
size breadth bars to the document's quote budget.
