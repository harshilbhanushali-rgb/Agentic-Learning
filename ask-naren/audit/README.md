# AUDIT — measurement harnesses for Ask Naren's answers

Unlike `../prototype/`, this is **not** throwaway. These are the instruments that established what Ask Naren's answers are actually worth, and issue #8 reuses them directly. Each script's module docstring carries its own reasoning and result; this file is only the map.

Everything here is read-only against Postgres and writes nothing but its own `artifacts/`.

## Run them from the repo root

```bash
.venv/Scripts/python.exe ask-naren/audit/<script>.py
```

The Joveo VPN must be up for anything that generates or embeds. Building the retrieval pool costs about a minute (6,496 coachable pairs off the warm gateway cache).

## The scripts, in the order they were run

| Script | Cost | What it settled |
| --- | --- | --- |
| `diagnose_scenario_mismatch.py` | free | The "retrieval lands on the wrong scenario 10/24" alarm was mostly a **measurement artifact** — it compared only the primary of two multi-label lists. On any shared label: 20/24, and 12/12 among answered. Mask starvation ruled out. |
| `diagnose_similarity_metric.py` | embeddings only | The answer-similarity metric **does** discriminate (+0.073 at d=1.35 against a transplant null), but its absolute value is uninterpretable. Paired-use only. |
| `build_answer_audit.py` | ~1 generation per item | Builds the blind packet: real items, known-wrong plants, known-right plants, shuffled, with a separate key file. |
| `score_answer_audit.py` | free | Applies the two-sided control gate and **refuses to print a headline rate unless it passes**. |
| `probe_topk_headroom.py` | embeddings only | The right-topic moment is in the top-5 for 3 of 4 failures, and for 19 of 20 successes against 11 of 20 at rank 1. Rank-1 selection is discarding what retrieval already found. This is issue #8's premise. |

## Reusing this for issue #8

`artifacts/answer_audit_raw.json` already holds **the top-1 arm's 36 generations**. Pass `--from-raw` to `build_answer_audit.py` to rebuild a packet without re-paying for them — that flag exists precisely so a control-design fix or a new comparison arm does not re-roll the sample under test at the same time.

## Two rules these harnesses exist to enforce

Both are recorded properly in `../docs/adr/0004-answer-quality-is-measured-by-blind-read-behind-two-sided-controls.md`; repeated here because they are easy to skip.

1. **Controls in both directions, detection reported first.** A blind reader's absolute rate is a framing artifact (84% vs 17% on identical documents, measured on this project). A one-sided gate bounds the error on one side only.
2. **A positive control must satisfy the rubric it is scored against.** The first known-right plant used Naren's own raw reply and a blind reader rejected 6/6 — correctly, because spoken transcript is not a usable answer and the plant violated the rubric's "supported by the retrieved reply" clause by construction.

## Result as of 2026-08-26

20 of 24 answers judged right — **83%, 95% CI [64%, 93%]** — with the gate passing 6/6 known-wrong and 6/6 known-right. All four failures came from retrieval whose primary scenario differed from the situation's. Full account in issue #7's comments.

Not established: n is 24, the reader was a model rather than a CSM, and the situations were verbatim client turns rather than the paraphrases a CSM would actually type.
