# Ask Naren answers from the single nearest exchange, and applies no retrieval floor

Issue #7's blind read put Ask Naren at 20/24 answers right and traced **all four wrong answers to one mechanism**: retrieval whose primary scenario differed from the situation's. A follow-up ranking probe (`ask-naren/audit/probe_topk_headroom.py`) then found the right-topic moment was usually *present in the ranking but not first* — in the top-5 for 3 of the 4 failures, and for 19 of 20 successes against only 11 at rank 1. That framed an attractive hypothesis: rank-1 selection is discarding information retrieval already found, so showing the model a shortlist should fix answers. #7 also left open whether Ask Naren needs a **retrieval floor** below which it declines regardless of what the model says.

We decided, after measuring both, to **keep single-candidate selection (`answering.DEFAULT_K = 1`), add no retrieval floor, and add no rank cutoff.** The shortlist capability stays in the code (`RetrievalPool.topk`, `build_candidates_prompt`, `k=` on `answer_situation`) because it is what the A/B ran on and what any re-test would need, but it is not the default.

The hypothesis did not survive contact with a measurement. Shown five candidates the model **re-selected in 11 of 18 paired situations** — and k=1's pick was available in the shortlist all 18 times — yet correctness moved in exactly **one** case. Selection was never the binding constraint. Neither is retrieval strength, and neither is rank; all three were tested and none of them separates a right answer from a wrong one on this corpus.

## Result (2026-08-27): a wash on quality, and a floor would be actively harmful

Both arms ran over the same 36 situations through the shipped path (`ask_naren.answering.answer_situation`, same model, same prompt for k=1, grounding gate active in both). Harness: `build_answer_audit.py --k`, `compare_arms.py`. Two blind reads, each gated two-sided at 12/12 known-wrong caught and 12/12 known-right kept.

| | answers delivered (of 36) | right | wrong | accuracy on what it delivers |
| --- | --- | --- | --- | --- |
| k=1 | 24 | **19** | 5 | 79% |
| k=5 | 22 | **18** | 4 | 82% |

Paired on the 18 situations both arms answered: 15/18 against 16/18, **1 fixed by k=5, 0 broken**, McNemar exact two-sided p = 1.000. Every difference is one or two answers wide on n=36 and none is resolvable. The remaining choice between the arms is a product preference — answer more often, or be wrong less often — not a quality finding.

**Retrieval cosine does not separate right from wrong.** Across all 46 delivered answers: right n=37, mean 0.809, range 0.720–0.858; wrong n=9, mean 0.793, range 0.757–0.845. The two lowest-cosine answers in the whole set (0.720, 0.750) are both *right*; wrong answers appear at 0.845 and 0.824. Every floor tested destroys two to three right answers per wrong one removed — at 0.78 it cuts 8 right and 4 wrong; at 0.80, 14 right and 5 wrong; at 0.82, 22 right and 7 wrong. A floor is not merely useless here, it is negative.

**Rank does not predict rightness either.** k=5 by grounded rank: 1 → 7/8, 2 → 4/4, 3 → 3/5, 4 → 2/3, 5 → 2/2. The shortlist's tail is not junk, so there is no "top-K but only trust the first two" fallback.

**Shortlist dilution did not appear where it was most feared.** All six positive controls at k=5 grounded at rank 1 at cosine ≥ 0.999 — with the right exchange present and perfect, four distractors did not pull the model off it. The grounding gate also held: 35/36 verified at k=5 against 36/36 at k=1.

## What this closes, and what it does not

Closed: candidate selection as a lever, the retrieval floor, and any rank-based gate. **Do not re-propose these without new evidence** — they were measured, in both directions, under one framing, behind a passing control gate.

Still open: whatever makes the remaining ~20% of answers wrong is invisible to all three instruments tried. Two items were wrong at k=1 *and* wrong at k=5 while grounded at rank 3, having had five candidates to choose from. That is the frontier, and it needs a different kind of instrument.

Two limits on everything above, both unchanged from #7: n = 36 situations, and **the reader was a model, not a CSM**. Cross-read agreement was measured this time and is reassuring — two independent reads of 18 identical k=1 answers agreed 16/18 (89%) and returned the identical 15/18 marginal — but agreement between two model readers is not the same as agreement with a CS person. That check remains the cheapest available strengthening of every number in this ADR.
