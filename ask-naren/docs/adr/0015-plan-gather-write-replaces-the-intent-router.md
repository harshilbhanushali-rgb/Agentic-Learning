# Plan, gather, write replaces the intent router

**Status:** decided 2026-10-10. Built behind `COMPOSE` in `Brain/ops/serve_ask_naren.py`, **on**. Not yet blind-read against the router. Code: `Brain/ask_naren/composing.py`.

Answers read as rigid and left out what the corpus held. Intake sorted each message into one of nineteen intents, and each intent showed its model a narrow slice. A follow-up saw one exchange. A `procedure` saw the playbook's steps and key moves but not its phrasing or pitfalls. `phrasing` and `pitfalls` printed stored lists. "Give me the playbook, some interactions, what to keep in mind" spans four intents and could land in only one. On the pixel-tracking question it got four numbered steps. The live playbook also held five phrasing quotes and two pitfalls, and none of them were shown.

We decided to replace the router with one path:

1. **Plan** (one call, low reasoning, JSON schema). The model reads the message and the conversation, and picks a kind: situation, topics, frequency, clarify, or out of scope. For a situation it writes 1 to 4 short searches: one for a narrow question, several angles for a broad one.
2. **Gather** (no model). All searches are embedded in one batch. The nearest 12 per search are interleaved by rank, deduplicated and capped at 24. The **whole** playbook is attached for the two situations those exchanges fall in most.
3. **Write** (one call, low reasoning). The writer sees all of it plus the conversation, and answers in the shape the question needs.

**The plan may choose not to search, in two ways.** The planner is given the principle, not a list of cases, so the call is its own. `from_conversation` applies when everything the answer needs is already in the conversation. Nothing is embedded or searched. The writer gets the conversation plus what the last answer rested on: its exchange, if it cited one, and its situation's whole playbook. It may reuse its earlier answer, and the quote is checked against that carried material. If the thread has nothing to rework, the planner's backup searches run instead. A rework that cannot be grounded gets the follow-up decline. Live check, one thread holding a pixel answer: the planner picked correctly on 7 of 7 messages (4 reworks; "tell me more", a new objection and a new topic all searched). The email rework took 4.9s. With the prompt rewritten to state the principle only, it was 11 of 12, including 5 messages the prompt never mentions. The miss searched when it did not need to.

`conversation` applies when the message is talk with Ask Naren itself ("how are you", "thanks"). The planner's own one- or two-sentence reply is sent back, shaped as a clarify with `conversational: true`, so it has no quote or citation field. It is told to give no advice or claim about client work, and to pick another kind if replying would need any. Live: 16 of 18 across all kinds. "who are you and what can you do" went to `topics`, which is arguably right. Small talk wrapped around a real question ("hey how are you, quick one: client wants to cancel...") searched.

`topics` and `frequency` stay rendered from stored rows. They are about the whole corpus, and a list of the taxonomy cannot invent a scenario.

## What stays and what is given up

- **The gate is the same `grounding.check`, with one verified quote per answer.** That was a product decision: one quote per point was offered and declined. Its sources are every exchange shown and every playbook evidence quote shown (moves, phrasing, pitfalls). The rest of a long answer is unverified synthesis of material the writer was shown.
- **Searches are written by the planner, not checked to be the CSM's own words** (ADR 0006 and ADR 0014 rule 1). Splitting a broad question needs words the CSM did not type. The planner is told never to search on Ask Naren's earlier answers, which is the mechanism ADR 0006 guarded against. The searches are echoed in `intake.retrieval_query`.
- **Follow-ups are no longer pinned to the carried exchange.** "Tell me more" is planned like any other message, with the conversation in view.
- **`drawn_from`** lists the calls the writer says it used, filtered to calls it was shown. It is not verified the way the quote is.

## Measured so far (one run each, not a blind read)

Four live questions on the rebuilt Brain: a broad pixel question, a narrow "client said" question, a follow-up, and a CPA escalation. All four were answered, with the quote verified on the first attempt.

- **Medium writer reasoning:** 16 to 57s, over the 30s deadline on two of the four. The writer spent about 2,000 reasoning tokens.
- **Low writer reasoning:** 10.3, 12.4, 16.1 and 19.4s. That run also told the writer to stay under about 500 words. The limit was removed afterwards at the operator's request, so answers will be longer and somewhat slower than these figures. Re-time before relying on them.
- **Embedding varies:** 4 searches took 1.3 to 10.8s across runs, from the gateway.

## Consequences

- **Every situation question now costs two model calls.** Before, thirteen intents were rendered and cost one (intake). `ASK_NAREN_ANSWER_COST_SECONDS` and the throughput figure in ADR 0010 are therefore optimistic. Re-measure before relying on them.
- **The intent router, ADR 0013's carrying and ADR 0014's three switches do not run while `COMPOSE` is on.** They are not deleted, and `False` restores them exactly.
- **Before treating this as settled:** run the 36-question blind read (`ask-naren/audit/`) with `COMPOSE` on against the router, plus a set of broad "teach me" questions the router could not answer. The main known failure, a right-topic exchange that answers a different question (issue #9), is not addressed by design. Wider gathering may help it or hide it.
