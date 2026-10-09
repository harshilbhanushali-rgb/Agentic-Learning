# Layer C follow-ups: support-targeted rescue, and the conjunction filter swept

**Date:** 2026-08-17, same session as
`2026-08-17-layer-c-relative-filter-and-rescue-design.md` (read its §7 first).
**Status:** PRE-REGISTERED. Gates below frozen before any follow-up code or run exists.
Both follow-ups re-aim mechanisms that PASSED a gate tonight; neither may cite tonight's
post-hoc numbers as results.
**Cost:** zero chat, zero new embeddings (cache-only shim), zero Postgres. Subagents: 1
audit of the new code; 1 independent blinded reader if F2 produces readable items.

## F1 — support-targeted rescue

Tonight's rescue selected right (blinded read 12/12) and delivered wrong (99.3% of
admissions to already-passing clusters; only 33 of 204 clusters were base-failing). F1
changes ONLY the destination set: candidate destinations are the base-FAILING clusters of
each scenario (support_calls < required_support). Admission test unchanged —
`cos(clause, centroid_c) >= p25({cos(member, centroid_c)})`, full space, nearest eligible
cluster. Everything else (clustering, gate, denominator) identical to the real/p40 arm.

- **Placebo:** same COUNT of additions per failing cluster, drawn uniformly (seeded) from
  the same scenario's noise pool — the same shape as tonight's, restricted to the same
  destinations. Counts asserted equal.
- **Primary gate G-F1:** milestones GAINED (fail→pass flips). PASS iff rescue gains
  strictly more than its placebo AND the paired per-cluster sign test on flipped-vs-not
  reaches p < 0.05. If neither arm flips ≥5 clusters, the result is UNDERPOWERED-NULL:
  reported as "the noise pool cannot power the failing clusters at p25 admission", with
  the per-cluster deficit-vs-adds table as the evidence.
- **Secondary (reported):** blinded read of added content for up to 12 flipped-or-nearly
  flipped clusters (same protocol, independent reader, ≥10/12 to claim selection held);
  account-diversity lift of gained milestones; new-distinct-calls per cluster vs deficit.
- **Failure statement:** if G-F1 fails or is underpowered, the noise-rescue direction at
  Layer C closes entirely — selection was never the problem and delivery cannot be fixed
  by re-aiming, so the remaining noise-pool value sits in re-clustering, not rescue.

## F2 — conjunction filter, K swept

Tonight: p40 rejects junk but is routing-blind (60.0%/60.0%); rank(8) rejects mis-routing
but keeps filler; their conjunction scored 16.3pp at 47.2% retention POST-HOC. F2
pre-registers the sweep the post-hoc number cannot stand in for.

- **Grid:** conjunction p40 AND rank(K) for K ∈ {8, 9, 10, 11, 12, 13, 14}, measured on
  the SAME real/permuted pools and permutation as tonight (seed 42), same one-code-path
  symmetric application.
- **Gate G-F2 (identical bars to G-T1a, unchanged):** PASS iff some K has
  survival(real) ≥ 0.50 and gap ≥ 25pp; NULL if no K with survival(real) ≥ 0.50 reaches
  15pp. Operating point: max gap subject to the floor, ties toward higher real survival,
  then smaller K.
- **Read (reported):** 20 sampled disagreements each way between the chosen conjunction
  and p40 alone, same no-print-before-sampling protocol — the check that the conjunction
  actually removed the filler rank admitted.
- **Failure statement:** if G-F2 is WEAK again (15–25pp), the honest conclusion is that
  ~20pp is the ceiling this taxonomy's granularity allows any intake filter, and further
  filter-shape search at Layer C stops; the constraint moves to the taxonomy (scenario
  overlap) or the clustering.

## RESULTS (2026-08-17, same session — both follow-ups CLOSED)

Follow-up harness `calibration/lcfr_followups.py` + `tests/test_lcfr_followups.py`
(5 tests, one added post-audit to pin cross-dedup), blind audit CLEAN before running.

### G-F2: NULL — ~20pp is the ceiling, and filter-shape search at Layer C stops

| K | real | permuted | gap (pp) |
| --- | --- | --- | --- |
| 8 | 0.472 | 0.309 | 16.3 |
| 9 | 0.490 | 0.340 | 15.0 |
| 10 | 0.508 | 0.369 | **13.8** ← first K clearing the 0.50 floor |
| 11 | 0.524 | 0.396 | 12.7 |
| 12 | 0.537 | 0.421 | 11.6 |
| 13 | 0.549 | 0.441 | 10.8 |
| 14 | 0.558 | 0.462 | 9.6 |

The gap decays monotonically as K loosens; retention and discrimination trade one-for-one
and never meet the (0.50, 25pp) corner — nor even the 15pp NULL bar once retention is
satisfied. Combined with the main trial (best single rule 20.0pp at 0.587 retention), the
pre-registered failure statement applies: **on this taxonomy, ~20pp is the ceiling for any
intake filter; further filter-shape search stops. The constraint is scenario overlap (26
topically-adjacent scenarios) or the clustering, not the filter.**

### G-F1: UNDERPOWERED-NULL — and the mechanism closes the rescue direction entirely

Flips: rule 2, placebo 4 (paired 0 up / 2 down / 31 tie, sign p=0.50; both arms under the
pre-registered floor of 5). The per-cluster detail says why, and it is stronger than
"underpowered": **28 of 33 failing clusters received ZERO admissions even when they were
the ONLY eligible destinations — 15 total adds corpus-wide.** The noise pool does not
contain the failing clusters' content at p25 similarity. Where the rule did add, same-call
gluing replicated exactly (one cluster: 8 adds → 2 new distinct calls for the rule vs 5
for the placebo).

The placebo again out-flipped the rule; no fresh audit was run because this direction is
the one this morning's placebo-veto audit PREDICTED from the same mechanism (new calls per
added clause: rule 0.235 vs placebo 0.385), and the artifact's internals reproduce it. The
blinded read was skipped: only 3 clusters had ≥2 adds in both arms, and no read outcome
could move an UNDERPOWERED-NULL gate; the selection question was already answered 12/12
this morning.

**Per the pre-registered failure statement: the noise-rescue direction at Layer C closes
entirely.** Selection was never the problem, delivery cannot be fixed by re-aiming, and the
evidence the under-supported milestones lack does not exist in the discarded pool. The
noise pool's remaining value is in RE-CLUSTERING (a Layer C clustering-method bench), not
in rescue.

## Guards (unchanged from tonight, restated as binding)

- Both follow-ups run through the audited `lcfr_common.py` machinery; new code is additive
  (a destination-restricted `members` dict for F1; a conjunction mask for F2), unit-tested
  with skewed fixtures, and audited by one blind subagent before running.
- F0 revalidation not required (no pass-1 change for F2; F1 reuses the captured real/p40
  clustering exactly as tonight's rescue did).
- The placebo-veto rule stands: any unexpected placebo result is audited (code + output)
  before being believed.
- Adoption claims require the Bonferroni note at 2 gated tests (0.025), and nothing ships
  to production from gemini@3072 numbers alone.
