# A carried situation is judged by intake and resolved by lookup

**Status:** decided 2026-10-05 (issue #26). Built for the **scenario** intents (#51, #52, #53); carrying an **exchange** is #54. **Not yet measured**: #55 is the gate that decides whether it ships. Builds on ADR 0006, which permits it.

A CSM asks about a situation, gets an answer, then asks "what's the play here". Today every answer path except `follow_up` finds its situation by searching on the words of the current message. "What's the play here" names no situation, so it has nothing to search on, and it falls back and retrieves noise. The thread already records what the last answer rested on, and nothing but `follow_up` reads it.

ADR 0006 allows the fix and says so explicitly: history may supply an **identifier**, never **text that gets embedded**. This ADR records *how*. The requirement that shaped it is that it must work **for intents that do not exist yet**, not only the five playbook intents where the bug was first seen.

## Decision

1. **Intake judges whether a message is on a carried situation or opens one.** Intake returns a new field beside `intent`. The model judges *same situation or new*. It already makes this judgement for `follow_up` and is measured on it (10/11 held out; 7/7 on the "a new client situation is not a follow-up" negative).
2. **Code resolves which situation, by lookup.** The anchor comes from **the most recent answered or rendered turn** (clarifies and declines skipped, never walking further back), the same rule as `threads.carried_source`. The model never names a `scenario_key` or `pair_id`: a model that can name a row can name one that does not exist.
3. **Every intent declares the anchor its path consumes**: scenario, exchange, neighbourhood or none, plus whether it is **new-only**.
   - The declarations live in one table covering every intent, and **a test fails when an intent is missing from it**. A new intent can't be added without saying what it consumes, and saying that is part of writing its path anyway.
   - An exchange satisfies a scenario need; a scenario never satisfies an exchange need.
   - When the carried turn does not hold the anchor the intent needs, Ask Naren asks a **fixed, code-written clarify** rather than searching the fragment or walking back to an older turn.
4. **`reply_to_client` and `contrast_my_reply` are new-only.** They always carry new client words, and answering those from an inherited scenario is the worst failure this tool has: grounded, coherent, and about the wrong client. Neighbourhood intents (`where_else_seen`, `call_prep`) are also new-only for now. Carrying them needs a vector-store query by id, which is a separate capability.
5. **With no thread, every message opens a situation.** The prompt rule appears only inside the thread-rules block, because in this prompt the placement of a block has been measured moving other intents' routing.
6. **A carried answer reports no `match`.** No search ran, the same reason a follow-up carries none. Answers name their scenario on the page, which now includes `show_exchange` and `what_happened_next`, because that is the only defence against a carried identifier that has stranded on the wrong situation.

## Considered and rejected

- **Infer "carried" when the copy guard fails and the thread has an anchor.** This needs no prompt change, which is its whole appeal. But the copy guard also fails when the model paraphrases a *new* situation (measured live: `call_prep` composed "meijer team feed problems" for a message containing none of those words). Under this rule that message would be answered from the previous client's scenario. Only the model can tell "no situation in this message" from "a situation, badly copied".
- **A per-intent fix in the five playbook paths.** This was rejected by the requirement above. It would be re-argued for every intent added after it, and one session added nine.
- **Folding `follow_up` into the new model** ("carried + exchange + generate"). Cleaner in principle, but it puts the only measured multi-turn number at risk for no difference a CSM would see. Revisit once the new field is measured.
- **Rewriting the query from the thread.** This is ADR 0006's own rejected alternative and issue #25's territory. Nothing here embeds a word of history.

## Consequences

- **The intake contract changes, so all eight intake sets are re-measured.** No set may drop by more than one case, best of three. A new held-out "carried vs opens" set, drawn from real thread shapes rather than written from the prompt, has an asymmetric bar:
  - **zero** messages with new client words read as carried;
  - at least **80%** of real carried messages recognised.

  A missed carry costs today's behaviour or a clarify. A false carry is a confident answer about the wrong client.
- **Rendered turns start recording the identifiers their responses already carry** (`scenario_key`; `pair_id` where the response cites one exchange). This does not change `follow_up`, whose grounding source is still read only from *answered* turns.
