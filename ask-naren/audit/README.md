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


## Issue #25: the conversation in the search, and the wide retry, 2026-10-10

Three switches in `Brain/ops/serve_ask_naren.py`, all ON since this measurement: `SEARCH_FROM_CONVERSATION`, `ANSWER_SEES_CONVERSATION`, `WIDE_RETRY`. Decision and reasoning in ADR 0014.

**Intake** (`measure_intake_accuracy.py --rewrite`, best of three). Only the two sets with a thread can move; every other set sends a byte-identical request. Three prompt generations are kept:
- `intake_accuracy_25_*`: the first wording. Threaded 10/11, carried 42/44, no false carry. But live, the search was never written for messages intake calls carried, so it never fired.
- `intake_accuracy_25b_*`: "fill it whether carried or not". Fixed that, but one new-client message (a CSM's own drafted reply) was read as carried 3/3. That fails the zero bar. Rejected.
- `intake_accuracy_25c_*`: **shipped.** Threaded 10/11 ×3; carried 40, 42, 42 of 44; false carries 0 ×3. One search borrowed earlier words in one run, on a CSM answering Ask Naren's question about the same client (intended). The carried set was seen once during this prompt work, so it is no longer fully held out.

**#49's six questions** (`live_conversation/rescue_49.py`, scored by `decline-rescue-oracle/`, three runs each): 6/18 right today, 12/18 with the wide retry, with or without the conversation prompt. The CSV-export question, which should decline, is answered wrongly 3/3. Results: `artifacts/rescue_49_25*.json`.

**The 36-situation audit** (`build_answer_audit.py --wide-retry`, then `score_answer_audit.py --out ...`): 11 first-try declines, 5 rescued. The blind reader cleared both bars 6/6, judged the rescues 4 right and 1 wrong. Artifacts: `answer_audit_*_wide.json`.

**The live messy-conversation test** (`live_conversation/`): `converse.py` drives the running service through whole conversations, rebuilding the thread as the web app does. `conversations.json` is the original 11; `conversations_25_new.json` adds four, one per new behaviour. Each switch was run on its own and then all three (`results/<config>.json`; `before*.json` is the switches-off baseline). All three on, against before: 6 turns better, 1 worse, 0 timeouts; median on searched turns about 15s to 23s; model calls +10 to 26% (`count_calls.py`, a lower bound). One run per configuration, and the answer model's decline on a single exchange flips between runs, so read ±1 or 2 turns as noise.

`results/first_attempt_all_on.json` is the run that found two defects, both fixed before the matrix: the search was thrown away on carried messages, and three retries ran past the 30s deadline. Retries now stop 2s before it.
