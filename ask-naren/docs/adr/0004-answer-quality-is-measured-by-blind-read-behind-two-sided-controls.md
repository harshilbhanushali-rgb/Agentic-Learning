# Answer quality is measured by a blind read behind two-sided controls, never by a similarity score or a pairwise judge

Ask Naren's grounding gate guarantees that every answer cites a real call and quotes it verbatim. That is a guarantee about **traceability**, not about **correctness** — an answer can be perfectly grounded in a moment that is about something else. Measuring correctness needed a separate instrument, and the obvious candidates are all disqualified on this corpus.

We decided that answer quality is established by a **blind read of situation-against-answer, scored behind planted controls in both directions**, and that no other instrument may stand in for it.

## What is ruled out, and why

**A holistic pairwise "which answer is better" LLM judge.** Already failed here: position-swap agreement 0.669 against a >=0.75 bar, with a transplant-penalty control at 0.835 that would have produced a false headline (`Brain/docs/findings/head-to-head-comparison.md`). Layer D only recovered a working grader by moving to binary, evidence-gated checks.

**Embedding similarity to Naren's real answer.** It discriminates its target (+0.073 at Cohen's d = 1.35 against a transplant null, true target at median rank 2.5 of 24), so it is not noise — but its **absolute value is uninterpretable**. Two *unrelated real* answers score 0.717, higher than a correct generated answer against its own ground truth at 0.698, because real answers share a spoken register (fillers, self-interruption) that generated prose does not. The number is polluted by writing style. It is valid **paired and relative only, same text type on both sides**, which is how ADR 0001 used it and how issue #8's A/B may use it. It must never be quoted as an answer-quality figure.

**Scenario labels.** `scenario_key` and `scenario_keys[]` are assigned by matching embeddings in the same space retrieval searches, so using them to validate retrieval is close to circular. Agreement on them rules out an alarm; it cannot establish a reassurance.

**Retrieval cosine.** Does not separate right answers from wrong ones (0.814 vs 0.798, sd ~0.03) and does not predict the model's own declines. Unfit as a quality signal or as a threshold.

## What the blind read requires

**Controls in both directions, with their detection rates reported before any headline rate.** A blind reader's absolute rate is an artifact of framing — measured on this project, two blind reads of the same 123 criteria returned 84% and 17% gradable, differing only in how the reader was framed. So:

- **known-wrong plants** (a real retrieval/answer pair shown under a different situation) test for credulity. Miss these and the reader's "right" verdicts are worthless.
- **known-right plants** (an answer generated with retrieval unmasked, so grounding is exactly on target) test for indiscriminate rejection. Fail these and the reader's "wrong" verdicts are worthless.

A rate from a one-sided gate is bounded on one side only and must not be published.

**A positive control must satisfy the rubric it is scored against.** The first version of the known-right plant used Naren's own real reply as the answer, on the reasoning that it is by definition what he said. A blind reader rejected 6/6 of them and was right to: his raw reply is spoken transcript that is not a usable answer, and it fails the rubric by construction because the rubric asks whether the answer is supported by the *retrieved* reply while that plant came from a different call. A control that violates the rubric measures the control's defect, not the reader's judgment.

## Consequences

The measurement is more expensive and slower than a score, and it does not produce a number that can be tracked automatically per-commit. That is the trade: on this corpus every cheap instrument has been measured and found either circular, register-polluted, or already-failed, so a cheap number here would be false precision rather than a saving.

The current reading is 20/24 (83%, 95% CI [64%, 93%]) with a gate that passed 6/6 and 6/6 — issue #7. It rests on n=24, on a model rather than a CSM as reader, and on situations that are verbatim client turns rather than CSM paraphrases. All three limits are open.
