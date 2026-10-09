# Layer D: one in three client moments is answered by someone other than the CSM (the deferral rate)

[Back to the index](INDEX.md)

**Status: measured 2026-08-25/27 as a by-product of the pairwise production run, first
written up 2026-09-05. Zero spend: every number below is a count over stored
`move_events` rows of run `137706da74c6` (the regraded `_v3` instrument, 100 of 106
mapped transcripts, one CSM).** This is a DESCRIPTION of how the calls are structured,
not a coaching claim -- see "What it does not mean" before quoting it.

## The number

Layer D detects "moments": client turns whose content routes to a coachable scenario.
For each moment it records who replied in the response window:

| response_outcome | meaning | moments | share |
| --- | --- | --- | --- |
| `csm` | the CSM replied, substantively | 601 | 49.9% |
| `other_joveo` | a Joveo colleague replied, not the CSM | **395** | **32.8%** |
| `interjection` | the CSM's "reply" was a fragment or backchannel (guard v1 2026-08-26, tightened to `_v4` 2026-09-06) | 206 | 17.1% |
| `none` | nobody on the Joveo side replied in the window | 3 | 0.2% |
| total | 96 calls with >= 1 moment | 1,205 | |

**Across 96 calls, 32.8% of the client moments Layer D found were answered by a Joveo
colleague rather than the CSM whose call it was.** Among moments that got a
substantive reply from anyone (`csm` + `other_joveo` + `none`), the colleague answered
39.5% of the time. (Counts updated 2026-09-06 for the `_v4` interjection guard, which
moved 20 backchannels from `csm` to `interjection`; the 395 did not move -- see
`layer-d-say-arm.md` §11c.) Only `csm` moments are graded; the other two thirds of the
non-CSM rows are recorded, never scored, so this rate is visible in the data but
invisible in every coaching report -- which is why it needed its own write-up.

## Where it concentrates

**By call, it is bimodal, not uniform.** Over the 84 calls with >= 5 moments: median
per-call deferral 17%; **35 calls had zero deferrals; 22 calls had half or more of
their moments answered by a colleague.** The 33% is not "the CSM steps back a third of
the time on every call" -- it is "on roughly a quarter of calls a colleague carries the
client conversation, and on 40% of calls the CSM carries it alone."

**By scenario, commercial and strategic topics defer more than hands-on technical
ones** (scenarios with >= 15 moments, deferred share of all moments):

| scenario | moments | deferred | CSM answered | deferred % |
| --- | --- | --- | --- | --- |
| niche_talent_scarcity_and_budget_reallocation | 21 | 11 | 9 | 52% |
| downstream_activation_and_cost_metrics | 25 | 11 | 10 | 44% |
| attribution_and_funnel_tracking | 19 | 8 | 9 | 42% |
| budget_allocation_and_testing | 31 | 12 | 16 | 39% |
| application_volume_and_prioritization | 246 | 93 | 114 | 38% |
| campaign_level_performance_tracking | 127 | 47 | 55 | 37% |
| technical_integration_and_timeline_scoping | 34 | 12 | 22 | 35% |
| xml_feed_setup_and_ingestion | 40 | 14 | 19 | 35% |
| job_board_budget_and_direct_agreements | 113 | 34 | 63 | 30% |
| programmatic_advertising_scope_and_capability | 87 | 25 | 51 | 29% |
| ats_integration_and_api_mapping | 84 | 23 | 42 | 27% |
| testing_and_implementation_timeline | 54 | 10 | 33 | 19% |
| pixel_placement_and_tracking | 36 | 5 | 26 | 14% |
| publisher_management_and_exclusions | 17 | 2 | 11 | 12% |

The two most-deferred topics are budget reallocation and cost metrics -- money
conversations. The two least-deferred are pixel placement and publisher exclusions --
implementation mechanics. Small cells (n 17-31) move by several points with one call,
so read the ORDER, not the individual percentages.

## What it does not mean (read before quoting)

- **A deferral is not a failure.** `other_joveo` records that a colleague spoke in the
  reply window. Many of these calls have an account lead, a solutions engineer or a
  manager present whose job is to answer exactly those questions; the CSM choosing not
  to talk over them is correct behaviour, not a gap. Nothing in the data says who was
  SUPPOSED to answer.
- **It is one CSM.** 96 calls, one person, one team composition. Whether 33% is high,
  low or normal is unknowable until a second CSM runs through the same instrument
  (the queue's item 4, deliberately held).
- **The graded report is therefore built on the ~half of moments she answered.** Every
  pairwise and say verdict is conditional on "the CSM chose to reply". A CSM who
  defers the hard questions and answers the easy ones would look BETTER on the graded
  cells, not worse. The deferral rate is the denominator that makes that visible.
- **The 17% interjection bucket is separate on purpose.** Before the P0 guard those
  fragments were graded as CSM replies (mostly as losses). Folding them into
  deferrals would have moved the 33% to 50% and changed its meaning; they are
  recorded as their own thing.

## What it is good for

1. **Context for every coaching number.** A per-scenario gap on `attribution_and_funnel_tracking`
   (the strongest pairwise finding) sits on 9 CSM-answered moments out of 19 detected;
   the other 8 were answered by a colleague. Say so when the gap is presented.
2. **A second-CSM comparison that costs nothing.** The rate is computed from moments
   Layer D already detects; no grading spend. When CSM #2 is ingested, this is the
   first number to compare, and the only one that needs no playbook.
3. **A conversation with the CSM's manager, not the CSM.** "On 22 of your calls a
   colleague answered most client questions -- is that the intended division of
   labour on those accounts?" is a staffing question. It should not appear in a
   coaching report addressed to the CSM.

## Provenance

Counts: `SELECT response_outcome, COUNT(*) FROM move_events WHERE grader_arm='pairwise'
AND rater_population='csm' AND run_id='137706da74c6' GROUP BY 1`. Per-call and
per-scenario tables are the same rows grouped by `call_id` / `scenario_key`. The
`interjection` guard and why it is kept separate: `docs/findings/layer-d-redesign.md`
(P0 fixes, 2026-08-26). The first mention of the 33% figure: same document, 2026-08-25
first production run (the pre-guard figure was within a point of this one).
