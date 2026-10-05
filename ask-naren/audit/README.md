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

## Carried situations: the #55 gate, 2026-10-05

`measure_intake_accuracy.py` decides whether carried situations (ADR 0013, #51 to #54) ship. Model `gemini-3.6-flash`, reasoning `low`, every set run three times.

**Existing sets: no set dropped.** The old prompt is `8905756`, measured in a checkout of that commit on the same day and model. Best of three per set, old → new: fitted 12 → 12/12, heldout 10 → 10/11, threaded 10 → 10/11, procedure 7 → 7/7, rendered 8 → 8/8, playbook 8 → 8/8, contrast 9 → 9/9, whereelse 7 → 7/7, composite 8 → 8/8. That is `artifacts/intake_accuracy_55_existing_sets_old_vs_new.json`, with every run beside it as `intake_accuracy_55_{new,old}_<set>_run<n>.json`.

**The new held-out set (`--set carried`, `cases/carried_vs_opens_heldout.json`, 44 cases): both bars pass, identically in all three runs (42/44).**
- New client words read as carried: **0 of 20**. The bar is 0.
- Real carried messages recognised: **20 of 22, 91%**. The bar is 80%.
- Opens recognised as opens: 22 of 22.

The two misses:
- "back to meridian, what should I tell them" was read as `reply_to_client`. That intent always searches fresh, which is the safe direction.
- A wording question that named its topic was read as opening a new situation.

The prompt this was measured on is in `artifacts/intake_accuracy_55_carried_prompt.diff`. It is byte-identical with no thread; with a thread, the only change is the situation rule.

**How the set was written, and what that does not prove.** A separate model agent wrote the cases blind. It was forbidden from opening the prompt, this harness, the tests, the ADRs or the issues, and was given only a plain description of the tool and the thread shapes. The echo check flags 2 of 44 cases. One is an everyday phrase ("what do i do first"). The other repeats its own thread's text, which is allowed. The labels were checked against ADR 0013's definition. One of them, a CSM restating their own question after a clarify, is ambiguous and is labelled carried; it can only cost recall. **The cases are synthetic, not real CSM traffic.** The stored threads in `ask_naren.turns` are the better source once there is enough real use, and re-running this set on real follow-on messages is the honest next check.

