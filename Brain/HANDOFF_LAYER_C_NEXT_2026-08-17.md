# HANDOFF — after the Layer C filter + rescue trial (2026-08-17, unattended session)

Continue-from-here after `HANDOFF_LAYER_C_2026-08-17.md`'s items 1, 3 and 4 ran. Read
`docs/superpowers/specs/2026-08-17-layer-c-relative-filter-and-rescue-design.md` §7 first,
then `CLAUDE.md`'s "Layer C: the two live directions ran" section, then
`PROBLEMS_AND_FIXES.md`'s last section. Every number below is committed there; this file is
only the ranking of what to do next and what tonight did NOT anticipate.

## What the previous handoff did not anticipate

1. **Both its top-ranked fixes half-worked, in complementary halves.** The per-clause
   relative filter (item 1) discriminates routing where the percentile is provably blind
   (20pp vs 0.0pp; permuted intake 0.658× vs 1.000×) — but it trades junk-blindness for
   substance-blindness: reading the disagreement set showed it drops broadly-relevant
   substantive clauses and keeps home-pointing filler. The rescue (item 3) selects
   perfectly (12/12 blinded, p=0.0005) — and delivers 99.3% of its volume to clusters that
   already pass the support gate. Neither mechanism is wrong; both are AIMED wrong.
2. **The literature transferred at the frame level and failed at the formula level.**
   Hubness/CSLS named our pooled-frame defect exactly, but full CSLS lost to plain rank at
   26 classes. Cite frames, re-derive formulas.
3. **The support-starvation metric did not move for ANY arm, including the ones that
   passed their gates.** Account-diversity lift: every arm null. Whatever raises evidence
   breadth per milestone, it is none of: routing quality (Layer B trial), filter shape,
   or nearest-centroid noise rescue.
4. **Item 4 (zero-clause-call denominator) closed as a no-op at the shipped setting** —
   0 flips. Keep the check for admission arms only.

## Next steps, ranked (each needs its own pre-registration)

1. **Support-targeted rescue.** Same p25 admission test, but rank destinations by NEED:
   restrict candidate destinations to base-FAILING clusters (or weight admission toward
   them), instead of global nearest-centroid. The selection instrument is already
   validated 12/12; only delivery needs re-aiming. Gate suggestion: gained milestones vs
   a volume-matched placebo restricted to the same destinations, plus the same blinded
   read. Everything needed is in `lcfr_common.py` (`rescue_assign` takes a `members` dict —
   pass it only the failing clusters' members).
2. **Conjunction filter (p40 AND rank(K)), K swept.** Post-hoc number tonight: 16.3pp gap
   at 47.2% retention at K=8. Sweep K=8..14 for the retention/gap trade and pre-register
   the eligibility floor BEFORE looking. The prize is a Layer C intake that rejects both
   junk (percentile axis) and mis-routing (relative axis).
3. **The noise pool is the bigger lever than either.** 42% of the post-relevance pool is
   discarded at content parity (26.3% vs 27.3% content-free), and it is real expert
   content. Rescue recovers 31.7% of it into existing clusters; nothing recovers the rest,
   and `rescue` cannot create clusters. The Layer A diagnostic's conclusion — the loss is
   UMAP→HDBSCAN itself — now holds at Layer C. A clustering-method pass at Layer C
   (agglomerative/leiden equivalents of `clustering_bench.py`, one level down) has never
   been run.
4. **Layer C's UNIT question (previous handoff item 2) is still untouched** — it clusters
   response sentences; the pool-unit work says sentence units manufacture junk. The D2
   numbers make this MORE interesting, not less: if 27% of kept clauses are content-free,
   the unit may be why. Segmenter is shared with Layer A — shim it in the harness.
5. **S2 (teammate speech, 25.4% of the corpus)** — unchanged, still needs its own
   brainstorm, still the largest unmeasured lever.

## Traps confirmed again tonight (do not relearn)

- A percentile of a run's own population cannot reject anything — now measured for BOTH
  the relevance filter (60.0%/60.0%) and the sink review flag (5.3%/5.4% within-run, 9.2%
  cross-applied to fully random routing). Any new defence must be absolute or relative
  per-item, never relative to the run's own distribution.
- Per-cluster medians of top-account share are quantization noise at 1–4 additions — the
  0.50-vs-0.33 "account glue" reading was withdrawn after audit. Pool or condition on
  distinct-call count instead.
- The placebo-veto rule (operator instruction: audit any unexpected placebo result with a
  subagent before believing it) caught the withdrawal above and confirmed the 0-vs-1
  gained split was an n=1 coin flip. Keep the rule.
- F0-style self-validation (harness must reproduce the published control byte-for-byte
  before anything else is reportable) cost ~30 lines and made every other number in the
  session trustworthy. Make it standard for any new Layer C harness.

## Where things live

| | |
| --- | --- |
| `calibration/lcfr_common.py` | rules, rescue, placebo, pass1 variant, substrate — all pure parts unit-tested |
| `calibration/layer_c_relative_filter.py` | `--stage instrument` / `downstream` / `noise-read` |
| `calibration/layer_c_noise_rescue.py` | rescue (called from downstream), `--build-read` / `--score-read` |
| `calibration/lcfr_posthoc_conjunction.py` | the labelled post-hoc conjunction check |
| `tests/test_layer_c_filter_rescue.py` | 14 tests, skewed fixtures |
| `artifacts/layer_bc_lcfr_*.json` | 6 arms, scoreable by `score_layer_b_arms.py` |
| `artifacts/lcfr_instrument.json` | the full survival table + frozen operating point |
| `artifacts/lcfr_diagnostics.json` | G-T1b, T3, D1, disagreement counts |
| `artifacts/lcfr_d2.json` + `lcfr_noise_pool.json` | D2 shares + the raw pools |
| `artifacts/lcfr_rescue_detail.json` | per-cluster additions, thresholds, read source |
| `logs/lcfr_*.log` | full run output |

Session cost: zero chat calls, zero new embeddings, zero Postgres writes; 3 subagents
(2 audits, 1 blinded reader).
