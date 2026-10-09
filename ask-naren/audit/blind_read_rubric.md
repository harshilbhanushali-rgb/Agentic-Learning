# The blind-read rubric

The exact framing handed to a blind reader scoring an Ask Naren answer packet. **Use this
file verbatim.** Do not paraphrase it, improve it, or add examples per-run.

## Why it is a file

Issue #7's read produced the 83% figure, and its framing lived only in that session's
subagent prompt — it was never written down. That cost something: the number cannot be
reproduced, and no later read can be compared against it, because a blind reader's absolute
rate on this material is an artifact of framing (measured on this project: two reads of the
same 123 criteria returned 84% and 17% gradable, differing only in how the reader was
framed).

The consequence is worth stating plainly: **#7's 83% is a within-packet result and cannot
be subtracted from any future read.** Comparisons between arms must put both arms in ONE
packet under ONE framing — which is what `compare_arms.py` does, and why the lost rubric
did not invalidate issue #8's A/B.

From here on, a read that departs from this file must say so and explain why, because it
becomes non-comparable with every read that used it.

## Who reads

A model reader, not a CSM. Sonnet-class is the standing choice. This is a known limit on
every number produced here, recorded on issue #7: the cheapest strengthening available is a
CS person checking the items judged wrong plus a sample of those judged right.

## The prompt

> You are auditing an internal coaching tool. For each numbered item you are shown four
> things:
>
> - **situation** — what a client said, which a CSM needs help responding to.
> - **retrieved_client_said** — a client turn from one of Naren's (a senior CSM) past
>   recorded calls, which the tool selected as the closest match to the situation.
> - **retrieved_naren_replied** — what Naren actually said in reply, in that past call.
>   This is spoken transcript: fragmentary, unpolished, sometimes mid-sentence. Judge it as
>   speech, not as writing.
> - **answer** — what the tool produced for the CSM to use.
>
> For each item, judge ONE question: **is this answer right?**
>
> An answer is **right** when both of these hold:
>
> 1. It addresses the situation the CSM is actually facing.
> 2. It is supported by `retrieved_naren_replied` — it paraphrases or applies what Naren
>    really said there, rather than adding substance that reply does not contain.
>
> An answer is **wrong** when either fails. The most important case to catch: an answer that
> is fluent, confident and correctly quoted, but answers a DIFFERENT question than the
> situation asks — because the retrieved exchange was about something adjacent. Such an
> answer can assert the opposite of the truth while looking impeccable. Fluency is not
> evidence. Neither is a verbatim quote.
>
> Judge the answer as delivered. Do not credit an answer for being close to something right,
> and do not penalise it for being brief, plainly worded, or for omitting things the
> retrieved reply also omits.
>
> Use **uncertain** only when the situation itself is too fragmentary to tell what was being
> asked. It is not a hedge for a hard call.
>
> Some items in this packet are planted. Do not try to identify them; judge every item on
> its merits.
>
> Return JSON only: a list of objects with keys `id`, `verdict` (`"right"`, `"wrong"` or
> `"uncertain"`), and `reason` (one sentence naming the specific thing that made it right or
> wrong).

## What the reader must NOT be told

- Which items are controls, or that controls come in two kinds.
- Which arm, variant, prompt or configuration produced an item.
- Any rate, hypothesis, or expectation about the outcome.
- That two items may share a situation.

The last one matters for `compare_arms.py`, whose packet holds each situation twice, once
per arm. The reader may notice; they must not be primed to.
