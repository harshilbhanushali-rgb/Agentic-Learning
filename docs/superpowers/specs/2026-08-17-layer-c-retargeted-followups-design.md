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
