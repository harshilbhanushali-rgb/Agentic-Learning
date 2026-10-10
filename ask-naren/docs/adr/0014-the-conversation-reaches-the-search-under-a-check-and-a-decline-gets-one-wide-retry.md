# The conversation reaches the search under a check, and a decline gets one wide retry

**Status:** decided 2026-10-10 (issue #25). Built behind three switches in `Brain/ops/serve_ask_naren.py`, all on. **Partly supersedes ADR 0006:** its rule was "history never reaches the embedded query", and ADR 0006 itself named how to reopen it: measure whether answers get better, not argue from the cosine table. This is that measurement.

A message that leans on the conversation ("the ats one", "where else has this come up") was searched on its own few words and got an unrelated or wrong answer. And a decline came from showing the model ONE exchange when the one that answers often sits at rank 5 to 22 (issue #49). We decided three things:

1. **Search from the conversation.** Intake may write a `search_query` from the CSM's own earlier messages. Code checks that every word of it was typed by the CSM, never taken from Ask Naren's replies (those are the exchange already shown, and searching on them finds it again, which is ADR 0006's mechanism). A failed check searches the plain words. The search that ran is echoed in the response. Carrying (ADR 0013) still wins when there is something to carry; the search runs when there is not. A follow-up that the carried exchange cannot answer is searched instead of declined.
2. **The answer sees the conversation.** The answer model gets the conversation and the CSM's whole message, not only the searched words. The grounding gate is unchanged: the quote must verify against the exchanges shown this time, so a quote lifted from an earlier answer fails.
3. **One wide retry on a decline.** A "no close match" from the nearest exchange is retried once with the nearest 20. It never touches a first answer and never turns an answer into a decline, so it is not the refuted relevance gate (ADR 0005). It starts only with at least 15s of the 30s deadline left, and is abandoned for the first decline if still running 2s before it.

## What was measured

- **Intake.** Unchanged on the two conversation sets (threaded 10/11; carried 42/44). Zero new-client messages read as carried, over three runs. One of 20 new-words messages had its search borrow earlier words in one of three runs, and it is the CSM answering Ask Naren's own question about the same client, which is the intended use. A first prompt wording ("fill it whether carried or not") caused a false carry 3/3 and was reworded. The carried held-out set was therefore seen once during prompt work.
- **Issue #49's six questions** (three runs each, scored by #49's blind-judge oracle). 6/18 right became 12/18.
- **The 36-situation audit.** 11 first-try declines, 5 rescued by the wide retry, and the blind reader judged 4 right and 1 wrong. The reader cleared both control bars 6/6.
- **The live messy-conversation test** (41 turns). 6 turns better, 1 worse, no timeouts. Median answer time on searched turns rose about 15s to 23s, and model calls rose 10 to 26%.

## Consequences

- **A question the corpus cannot answer can now get a wrong answer instead of a decline.** The CSV-export question in #49 does, 3/3. That is the price, accepted at roughly 2 to 4 rescued right answers per new wrong one.
- **A declining question can cost two generations**, so the admission queue's sizing (ADR 0010, `ASK_NAREN_ANSWER_COST_SECONDS`) is now optimistic for decline-heavy traffic. Re-measure before relying on its throughput figure.
- **Not fixed:** a retrieved exchange that is on the right topic but answers a different question (issue #9) is still the main failure. "the ats one" now finds ATS exchanges, not the right one.
- **Turning a switch off restores exactly the pre-#25 behaviour of its part**, including intake's prompt, byte for byte.

## Update 2026-10-10: on the rebuilt Brain, the top 20 from the start

The pipeline was re-run (6,863 exchanges in 49 scenarios, against 6,496 in 34), and on it the nearest exchange alone declines far more: 21 of 36 first attempts. Part 3 above is therefore replaced: the answer model is shown the **20 nearest from the start** (`ANSWER_SHORTLIST_K = 20`) and the wide retry is off. In one blind read of the same 36 questions: top 20 from the start was 23 right, 1 wrong, 12 declined, median 11.5s, about 36 calls. The nearest first, then 20 on a decline, was 25 right, 1 wrong, 10 declined, median 17.2s with one answer at 30.0s, about 60 calls. That is equal on rightness (the same reader moved 3 between two reads of the same answers), and faster, with no second generation racing the deadline. Only 6 of the 24 answers came from the nearest exchange; 8 came from ranks 11 to 20.

This reverses issue #49's finding that 20 every time was worse. That finding was made on the old Brain with six questions, and was not reproduced here. What was not re-tested: whether a reliably right answer turns unstable across repeated runs, which is what #49 saw on the MSA question.

