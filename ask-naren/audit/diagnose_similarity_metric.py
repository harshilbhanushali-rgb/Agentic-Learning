#!/usr/bin/env python3
"""Issue #7, first task part 2: does `sim_to_ground_truth` discriminate anything?

THE METRIC UNDER TEST. The prototype behind ADR 0001 scored each generated answer by the
embedding cosine between it and Naren's real historical response to the same moment, and
reported mean 0.698 (median 0.694, range 0.592-0.807, n=12 answered). ADR 0001's conclusion
-- that adding Layer C playbook context gives no benefit -- rests on a PAIRED DELTA in this
metric (-0.005 to -0.007). If the metric cannot discriminate, that delta is a difference
between two numbers that both mean nothing, and the ADR's evidence has to be re-stated even
if its decision stands.

WHY IT WAS SUSPECTED, AND WHY THAT REASONING WAS WRONG. The suspicion was that 0.698 sits
near the median of a measured cosine band for this corpus (trigger band p50 ~0.690), and
that it ran the wrong way against retrieval quality (off-scenario 0.712 vs on-scenario
0.688). BOTH ARGUMENTS ARE BAD, and the run below shows why:

  * That trigger band is a DIFFERENT text-type comparison (trigger vs scenario description).
    Cosine bands are a property of the two text types being compared, not of the space, so
    a band measured on one pairing says nothing about another. The right null had to be
    measured on THIS pairing, which is what this script does.
  * The 0.712-vs-0.688 inversion is n=5 against n=7 with a matched sd of 0.056 -- entirely
    inside noise. It was never evidence of anything.

RESULT (2026-08-26): THE METRIC DISCRIMINATES; ITS ABSOLUTE VALUE STILL DOES NOT MEAN WHAT
IT LOOKS LIKE. Matched 0.698 vs transplant 0.625, lift +0.073 at Cohen's d = +1.35, and the
true ground truth's median rank is 2.5 of 24 candidates against a chance 12.5. So this is
not a dead instrument and ADR 0001's paired delta is not a difference between two
meaningless numbers.

The absolute value remains uninterpretable for a reason the suspicion never guessed: two
UNRELATED REAL Naren answers score 0.717, HIGHER than a generated answer against its own
ground truth (0.698). Real answers share Naren's spoken register -- fillers, self-
interruption, transcript noise -- while generated answers are clean written prose, and that
register gap depresses every cross-type cosine regardless of correctness. A matched score
below the unrelated-real-pair null is therefore NOT evidence of a bad answer.

USE RULE, which is what this script exists to establish: paired and relative only, with the
same text type on both sides. Never quote the absolute number as an answer-quality figure.
ADR 0001 used it exactly that way (a paired delta between two generated variants against the
same target), so its conclusion stands -- and now stands on a measured instrument: the
playbook effect was -0.005 to -0.007, roughly 12x smaller than the +0.073 this metric is
demonstrably able to see.

THE NULL, and why this particular one. The informative comparison is not "answer vs its own
ground truth" against zero -- nothing in cosine space scores zero, so a high absolute number
proves only that both texts are English. It is against a TRANSPLANT null: the same generated
answer scored against a DIFFERENT item's ground truth. That holds the answer's register,
length and topic-family constant and changes only whether the target is the right one. If
the metric carries signal, matched pairs must beat transplanted pairs by a margin larger
than the spread. If they score the same, the metric is measuring "both of these are
customer-success prose" and must stop being quoted as answer quality.

Also reported: the RANK of the true ground truth among all candidate ground truths for each
answer. A metric with real discriminating power should rank the right target first most of
the time; that is a more legible statement than any mean, and it needs no threshold.

Embeddings only -- no chat calls, and these texts were embedded by the prototype's own
scoring pass, so this runs off the warm cache. Reads nothing but the artifact.

    python ask-naren/audit/diagnose_similarity_metric.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "Brain"))

from preprocessing import embedder        # noqa: E402

ARTIFACT = _ROOT / "ask-naren" / "prototype" / "artifacts" / "eval_pairs_vs_playbook_v2.json"
OUT = Path(__file__).resolve().parent / "artifacts" / "similarity_metric_diagnosis.json"
VARIANT = "pairs_only"


def _unit(matrix: np.ndarray) -> np.ndarray:
    return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artifact", default=str(ARTIFACT))
    args = ap.parse_args()

    results = json.loads(Path(args.artifact).read_text(encoding="utf-8-sig"))["results"]

    # Every item's ground truth is a candidate target, including items whose answer was
    # declined: a bigger candidate pool makes the rank test harder and more honest, and the
    # ground truths exist regardless of whether the model chose to answer.
    ground_truths = [r["held_out"]["ground_truth_response"] for r in results]
    answered_idx = [i for i, r in enumerate(results)
                    if not r["scores"][VARIANT]["declined"]
                    and (r["answers"][VARIANT].get("answer") or "").strip()]
    answers = [results[i]["answers"][VARIANT]["answer"] for i in answered_idx]
    print(f"artifact: {Path(args.artifact).name}  variant={VARIANT}")
    print(f"{len(answers)} answers scored against {len(ground_truths)} candidate ground "
          f"truths\n")

    print("embedding (warm cache -> near free)...", flush=True)
    gt_vecs = _unit(np.asarray(embedder.embed_document_matrix(ground_truths),
                               dtype=np.float32))
    ans_vecs = _unit(np.asarray(embedder.embed_document_matrix(answers), dtype=np.float32))

    sims = ans_vecs @ gt_vecs.T                      # (n_answers, n_ground_truths)

    matched, transplant, ranks = [], [], []
    for row, true_i in enumerate(answered_idx):
        matched.append(float(sims[row, true_i]))
        transplant.extend(float(sims[row, j]) for j in range(len(ground_truths))
                          if j != true_i)
        # rank of the true target, 1 = the metric put the right answer first
        order = np.argsort(sims[row])[::-1]
        ranks.append(int(np.where(order == true_i)[0][0]) + 1)

    gt_null = [float(gt_vecs[i] @ gt_vecs[j])
               for i in range(len(gt_vecs)) for j in range(i + 1, len(gt_vecs))]

    m, t = np.array(matched), np.array(transplant)
    print("=" * 78)
    print("Is `sim_to_ground_truth` measuring anything?")
    print("=" * 78)
    print(f"  MATCHED    answer vs its OWN ground truth   : mean={m.mean():.3f}  "
          f"sd={m.std(ddof=1):.3f}  n={len(m)}")
    print(f"  TRANSPLANT answer vs a DIFFERENT ground truth: mean={t.mean():.3f}  "
          f"sd={t.std(ddof=1):.3f}  n={len(t)}")
    print(f"  CORPUS     two unrelated real Naren answers  : mean={np.mean(gt_null):.3f}  "
          f"sd={np.std(gt_null, ddof=1):.3f}  n={len(gt_null)}")

    lift = m.mean() - t.mean()
    pooled = float(np.sqrt((m.var(ddof=1) + t.var(ddof=1)) / 2))
    print(f"\n  lift of matched over transplant: {lift:+.3f}")
    print(f"  pooled sd: {pooled:.3f}   standardised effect (Cohen's d): "
          f"{lift / pooled if pooled else float('nan'):+.2f}")

    print(f"\n  rank of the TRUE ground truth among {len(ground_truths)} candidates:")
    r = np.array(ranks)
    print(f"    ranked 1st : {(r == 1).sum()}/{len(r)}  ({(r == 1).mean():.0%})")
    print(f"    top 3      : {(r <= 3).sum()}/{len(r)}  ({(r <= 3).mean():.0%})")
    print(f"    median rank: {np.median(r):.1f}   (chance would be "
          f"{(len(ground_truths) + 1) / 2:.1f})")
    print(f"    worst rank : {r.max()}")

    print("\n" + "=" * 78)
    print("READING")
    print("=" * 78)
    # Keyed on effect size and median rank, NOT on a "ranks 1st >= 50%" bar. With 24
    # candidate ground truths drawn from a taxonomy whose scenarios genuinely overlap,
    # several targets are near-interchangeable for any given answer, so demanding the exact
    # one rank first understates a working instrument. Median rank against chance is the
    # threshold-free statement.
    d = lift / pooled if pooled else float("nan")
    chance_rank = (len(ground_truths) + 1) / 2
    if d >= 0.8 and np.median(r) <= chance_rank / 2:
        print(f"  The metric DISCRIMINATES its target. Matched pairs beat transplants by")
        print(f"  {lift:+.3f} at d={d:+.2f} (a large effect), and the true ground truth's")
        print(f"  median rank is {np.median(r):.1f} of {len(ground_truths)} against a chance")
        print(f"  {chance_rank:.1f}. This is not a dead instrument.")
        print()
        print("  BUT THE ABSOLUTE VALUE REMAINS UNINTERPRETABLE, and this run shows why more")
        print("  sharply than the suspicion that prompted it: two UNRELATED REAL answers")
        print(f"  score {np.mean(gt_null):.3f}, HIGHER than a generated answer against its own")
        print(f"  ground truth ({m.mean():.3f}). Real answers share Naren's spoken register --")
        print("  fillers, self-interruption, transcript noise -- while generated answers are")
        print("  clean written prose, and that register gap depresses every cross-type cosine")
        print("  regardless of correctness. So a matched score BELOW the unrelated-real-pair")
        print("  null is not evidence of a bad answer.")
        print()
        print("  USE RULE: paired and relative only, same text type on both sides. Never")
        print("  quote the absolute number as an answer-quality figure.")
    elif d <= 0.2:
        print("  The metric does NOT discriminate. An answer scores about the same against")
        print("  the WRONG ground truth as the right one, so it is detecting shared register")
        print("  and vocabulary, not correctness. It must stop being quoted as answer")
        print("  quality, and ADR 0001's paired delta needs re-stating.")
    else:
        print(f"  Weak separation (d={d:+.2f}, median rank {np.median(r):.1f} of")
        print(f"  {len(ground_truths)}, chance {chance_rank:.1f}). Treat any delta smaller")
        print("  than the matched-vs-transplant lift as unsupported at this n.")

    print()
    print(f"  For scale: this instrument resolves a {lift:+.3f} difference at d={d:+.2f}.")
    print(f"  ADR 0001's playbook effect was -0.005 to -0.007 -- roughly "
          f"{lift / 0.006:.0f}x smaller than an effect it demonstrably CAN see.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "variant": VARIANT,
        "n_answers": len(m), "n_ground_truths": len(ground_truths),
        "matched": {"mean": m.mean(), "sd": m.std(ddof=1), "values": matched},
        "transplant": {"mean": t.mean(), "sd": t.std(ddof=1)},
        "corpus_null": {"mean": float(np.mean(gt_null)), "sd": float(np.std(gt_null, ddof=1))},
        "lift": lift, "pooled_sd": pooled,
        "ranks": ranks,
    }, indent=2, default=float), encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
