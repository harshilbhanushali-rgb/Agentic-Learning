# Ask Naren

An internal tool, built on top of the Brain pipeline's knowledge base, where a CSM describes a situation and receives an answer grounded in Naren's closest real historical response to it.

## Language

**Ask Naren**:
The on-demand, text-based internal tool where a CSM describes a situation and receives an answer grounded in Naren's closest real historical response to it.
_Avoid_: coaching bot, Naren chatbot, the chatbot.

**Grounded answer**:
An Ask Naren answer that cites the specific past call it rests on. Ask Naren never returns an answer without one — if nothing close enough exists, it declines rather than answering ungrounded.

**IT MEANS SOMETHING WEAKER ON A LAYER C ANSWER, and the difference is recorded in `docs/adr/0009-a-layer-c-answer-is-verified-at-build-time-and-at-request-time.md`.** A Layer B answer paraphrases ONE exchange and its verified quote covers essentially the whole answer. A Layer C answer summarises N playbook moves and its verified quote covers ONE of them — the rest were verified offline, at build time, by the verbatim snap that validated the Layer C method. "This answer rests on something Naren really said" holds on both paths; "every claim was verified against a transcript in this request" holds only on Layer B.
_Avoid_: cited answer, sourced answer.

**Pairs-only prompt**:
The Ask Naren prompt variant that answers using only the matched `kb_pair` (Brain's Layer B), with no playbook context.
_Avoid_: variant A, baseline prompt.

**Playbook-augmented prompt**:
The Ask Naren prompt variant that adds the scenario's Brain Layer C playbook (`key_moves`) to the matched `kb_pair` as extra context.
_Avoid_: variant B, playbook prompt.

**Grounding gate**:
The check Ask Naren runs at request time, before a grounded answer reaches the CSM: the model's returned quote must verify as verbatim against the answer's **grounding source**, and what it cites must be something it was actually shown. There is ONE gate; what differs between answer paths is the grounding source, never whether an answer has one. Two sources are built: a retrieved `kb_pair`'s response text, and a playbook's evidence quotes (issue #17). On failure Ask Naren regenerates once and then declines rather than showing an unverified answer. This is what makes the citation guarantee in `docs/adr/0002-citations-are-unredacted.md` a property of every live answer instead of a statistic from an offline eval.
_Avoid_: quote check, verbatim check, hallucination filter.

**Retrieval floor**:
A minimum-similarity threshold below which Ask Naren would decline regardless of what the model says. Proposed, **not built**: retrieval cosine was measured not to separate right answers from wrong ones (0.814 against 0.798), so a floor on it would refuse answers at random with respect to quality. Whether a floor is needed on some other signal is open — see `docs/adr/0004-answer-quality-is-measured-by-blind-read-behind-two-sided-controls.md` and issue #8.
_Avoid_: confidence threshold, similarity cutoff.

**Candidate selection**:
Which retrieved moments reach the prompt. Ask Naren ships top-1 — the single nearest `kb_pair`. Distinct from retrieval quality. Issue #8 measured top-1 against top-5 and found candidate selection is NOT the lever: shown five candidates the model re-selected in 11 of 18 situations and correctness moved once. The right-topic moment usually IS present in the ranking without being first -- that part held -- but reaching it does not make the answer right.
_Avoid_: reranking, top-k tuning.

**Candidate shortlist**:
The k nearest `kb_pairs` retrieval hands the model for one situation, nearest first, when Ask Naren is run with `k > 1`. Measured against single-candidate selection in issue #8 and NOT adopted — `answering.DEFAULT_K` is 1, so in the shipped path the shortlist is one exchange long. See `docs/adr/0005-candidate-selection-and-retrieval-floor-measured-and-rejected.md`.
_Avoid_: top-K, candidate set, the five, retrieval window.

**Grounded candidate**:
The one exchange from a candidate shortlist that an answer actually rests on — the one whose reply the model's quote verifies against. It is frequently not the nearest one, which is why a response's `citation`, `match.cosine` and `match.rank` all describe the grounded candidate rather than rank 1.
_Avoid_: chosen pair, selected match, the winner.

**Request frame**:
The wrapper a CSM puts around a client's words when asking Ask Naren for help — "A client said this, can you help with how Naren would reply?" A CSM RELAYS the client's words inside a frame rather than paraphrasing them, which is why the eval's query content was closer to production than assumed and the frame was the missing part. Measured 2026-08-27: adding a frame changes which exchange retrieval reaches for 81% of situations, because boilerplate shared by every query pulls all queries toward each other. See `docs/findings/answer-failure-modes.md`.
_Avoid_: prompt prefix, wrapper text, preamble.

**Situation**:
The client circumstance a CSM describes — what is happening with a client, not the message that describes it and not the conversation it arrives in. One thread can carry several messages about a single situation.
_Avoid_: query, question, prompt, case.

**Intake**:
The step that reads an incoming message before any retrieval and decides what happens to it: which intent it carries, what should be searched for, and whether to clarify instead of answering. Deliberately NOT "the read" — in this project a _read_ is a blind read, the judged evaluation of outputs, and "we measured the intake" must not be ambiguous with it.
_Avoid_: the read, the router, triage, dispatcher.

**Intent**:
**Built for NINETEEN intents** -- `reply_to_client`, `clarify`, `out_of_scope` (issue #14), `follow_up` (issue #16), `procedure` (issue #17), the five RENDERED intents `discovery`, `frequency`, `show_exchange`, `what_happened_next` and `coverage_check` (issues #19, #20), the five PLAYBOOK intents `sequence`, `phrasing`, `pitfalls`, `scenario_check` and `play_confidence` (issue #18), `contrast_my_reply` (issue #21), `where_else_seen` (issue #22), and the two COMPOSITES `call_prep` and `improve_at_move` (issue #23). That is the whole set #12 asked for.

**WHERE AN INTENT'S BLOCK SITS IN THE PROMPT CHANGES ROUTING FOR OTHER INTENTS**, measured 2026-09-09. Adding `where_else_seen` immediately before the `contrast_my_reply` block dropped the contrast set from 8/9 to 6/9 over three runs; moving the same text beside `coverage_check`, its semantic neighbour, restored it with no wording change. After adding an intent, re-run every set — and if one moves, try moving the block before rewriting it, because moving is the cheap fix and rewriting is the one more likely to break a third thing.

**It is worth trying first, not a guarantee — and check the diff before you believe the regression.** #23 added two more intents, `contrast` fell 8/9 → 7/9 stable over three runs, and moving the blocks did not recover it. The conclusion being drafted was that the boundary degrades as intents are added. It was wrong: inserting a block had eaten one space from an adjacent line, so the shipped prompt read `"what do ido first"`. Repairing it took contrast to 9/9. **A stable score is not a correct score**, and a prompt typo is invisible to the tests, the frozen-prompt harness and the build alike — none of them reads this prompt's text.

**FOURTEEN of them EMBED a query and the rest do not**, which is the division that matters in code rather than the ticket each came from: `intake.RETRIEVING_INTENTS` is the single list, and the prompt's rules, the decision validator, `responding._guarded`'s ADR 0006 check and the offline harness's span score all read it. They had drifted apart into three disagreeing lists before #18's review. **Count it from the tuple, never from this sentence** — the count written here has been wrong twice, which is exactly the failure the tuple exists to prevent and is why nothing in the code reads a number.
What kind of question a CSM is asking — reply to a client, the general play for a scenario, Naren's phrasing, what the tool even covers. A classification with a knowable correct answer, which is what makes intake measurable without a reader or a generation.
_Avoid_: question type, category, route.

**Composite**:
**Built** (issue #23). An answer that reads several layers at once: `call_prep` (the likely situations for a call, each with its play and a real exchange) and `improve_at_move` (a move's criterion, the pitfalls around it, and Naren doing it).

**BOTH RENDER, AND THAT IS THE GUARANTEE.** `docs/adr/0009-...` warns that a composite stitching a Layer C summary onto a Layer B answer inherits the weaker of the two — so these compose only **rendered** paths and inherit neither. The cost is real and is the honest trade: neither can summarise, prioritise or tailor its advice to a particular client. They assemble what is on file and leave the judgement with the CSM. A generating `call_prep` — "here is your brief" — would be a better product and would inherit exactly the mixed guarantee ADR 0009 describes; it is a later ticket, not this one.

**`improve_at_move` focuses on one move 26% of the time**, measured over 8 realistic asks against all 33 live playbooks. A live `key_moves` name averages 9.4 words and is a generated sentence, so plain word overlap with a CSM's words rarely hits. The rest of the time it shows the whole play and says so via `focused` — which still carries every part the ticket asks for, just not narrowed. Raising the rate needs a labelled set that does not exist; a looser matcher focuses more often with nothing to say it focuses correctly.
_Avoid_: brief, summary, digest.

**Where else seen**:
**Built** (issue #22). A rendered answer listing which ACCOUNTS a situation has come up with, so a CSM can tell a one-client quirk from a pattern across the book. The only rendered answer that reads a NEIGHBOURHOOD rather than one nearest exchange — its question has no single-exchange form, so the breadth is required by the question rather than chosen. That is why it is not in tension with `docs/adr/0005-...`, which measured and rejected a candidate SHORTLIST for **answering**.

**It names an account only where the recorded data states it unambiguously**, and lists everything else by raw filename. ~31% of citable calls are opaque UUIDs, and 40 of those 323 carry several external participant domains — one measured example is a brand and its agency. Guessing would print an agency where a CSM expects their client; dropping would under-report the spread. So **the account count is a range, not a count**: each unnameable call could be a new client or one already listed.
_Avoid_: which clients, account list, client spread.

**Contrast**:
**Built** (issue #21). An answer that sets the CSM's OWN reply — one they have already sent or drafted — against Naren's closest real reply to the same client turn. It is an `answered` response with the ordinary grounding gate; what makes it its own intent is that intake must extract TWO spans from one message, and only the client's half is embedded.

**IT NEVER SAYS THE CSM WAS RIGHT OR WRONG.** That judgement is Layer D's grader — it needs a rubric, a pairwise comparison and a measured instrument, none of which exist on this path. What Ask Naren has is one real moment where Naren faced the same thing, which is evidence a CSM can weigh rather than a verdict. A verdict would be believed on the strength of a single retrieved exchange.

**The residual risk, stated rather than left implicit:** a CSM who arrives by asking "was that right" — which intake deliberately routes here — may read a description as the answer to that question. A contrast naturally comes out deficit-shaped ("you said one thing; Naren did four"), because a real reply usually contains more than a one-line summary of the CSM's. Nothing in the response claims a verdict and the page adds no evaluative chrome, but the shape can imply one. **There is no answer-quality measurement on this path** — the same state `procedure` is in (ADR 0009), and the blind read is the instrument that would settle it.
_Avoid_: grading, scoring my reply, was I right.

**Answer path**:
**Partly built** -- `reply_to_client`, clarify and the out-of-scope decline (issue #14), `follow_up` (issue #16), and `procedure`, the first LAYER C path, which answers the general play for a scenario from its playbook `key_moves` and `arc` (issue #17). The five RENDERED paths ship too: `discovery` and `frequency` over Layer A, and `show_exchange`, `what_happened_next` and `coverage_check` over Layer B (issues #19, #20). So do the five that render a scenario's Layer C playbook — `sequence`, `phrasing`, `pitfalls`, `scenario_check` and `play_confidence` (issue #18) — `contrast_my_reply`, which sets the CSM's own reply against Naren's (issue #21), `where_else_seen`, which lists the accounts a situation has come up with (issue #22), and the two COMPOSITES (issue #23). The machinery that serves one intent end to end, including which Brain layer it reads. Distinct from an intent because a composite path reads several layers, and distinct from Brain's **routing**, which means assigning a pair or turn to a scenario — something Ask Naren also does, which is why the two must not share a word.
_Avoid_: route, handler, pipeline.

**Rendered answer**:
**Built** (issues #19, #20). An answer assembled from stored rows with NO model call at all — the coachable scenario list, a ranking of them, or a stored exchange reproduced verbatim. It carries the `rendered` outcome rather than `answered`, because its guarantee is different in kind: nothing was generated, so there is nothing for the grounding gate to check and nothing that could have been invented. A rendered list of the 34 scenarios cannot emit a 35th. The cost is that it cannot adapt to how the question was asked — every CSM asking what the tool covers gets the same list.
_Avoid_: static answer, canned response, lookup.

**Grounding source**:
**Built and variable** (issue #17). Modelled as `grounding.GroundingSource` -- an identifier the model must cite, the text its quote must appear in, and the payload the caller gets back. Layer B builds them from retrieved pairs, Layer C from a playbook's evidence quotes; one gate checks both. It needed no new field in the model's JSON contract, because every playbook evidence quote already records the call it came from. The specific stored text an answer must rest on, and what the grounding gate verifies its quote against. A Layer B answer grounds in the matched `kb_pair`'s response text; a Layer C answer grounds in the playbook's evidence quotes.
_Avoid_: context, the source, evidence, grounding text.

**Clarify**:
Returning a question to the CSM instead of an answer, decided BEFORE retrieval, in one of two cases: the message lacks the **material** a search needs (a paraphrase where the client's actual words are what retrieval must see), or it is genuinely ambiguous which **intent** it carries. Distinct from a decline, which is decided after retrieval has run — and distinct from an out-of-scope question, which is answered with a decline rather than a question, because asking a CSM to reword something Ask Naren fundamentally cannot answer helps nobody.
_Avoid_: ask-back, prompt for detail, follow-up question.

**Thread**:
**Built** (issue #15). One continuing conversation between a CSM and Ask Naren. Ask Naren stores none of it — a thread is held by the caller and replayed with each message, in keeping with the service holding no database handle while answering. A **turn** in it carries what the CSM typed, what Ask Naren said back, and the identifiers of the exchange the answer rested on — never the exchange's text, which is what keeps ADR 0006's corollary true and keeps Naren's words out of a later prompt's reach.
_Avoid_: session, chat, history, conversation.

**Trimming a thread**:
Shrinking a thread to fit a cap by blanking a turn's **prose** while keeping its **carried identifiers**. Not truncation, and specifically not "drop the oldest messages": the message that established the scenario is usually the first one and every later turn inherits its identifier, so dropping it strands the conversation (ADR 0006). Applied twice with two jobs — the page trims to fit the request body, the service trims to bound what a thread contributes to a prompt.
_Avoid_: truncation, windowing, cutting history.

**Follow-up**:
**Built** (issue #16). A message that only carries meaning inside its thread ("and if they push back on price?"). It is the case that retrieves nothing useful on its own words, so it is answered from the thread and the grounding source already cited rather than by searching again. A message that describes a NEW client situation is not a follow-up, even in the same thread — it gets its own search.
_Avoid_: continuation, next turn, reply.

**Carried identifier**:
A `pair_id`, a `scenario_key` or a call filename passed forward from an earlier turn in a thread. The thing ADR 0006 permits history to supply, as against text that gets embedded: carrying one involves no embedding, so the dilution the ADR measures does not apply to it. It is what lets a follow-up ground in the exchange already cited without searching, and it is what trimming a thread must never drop. It can **strand** — a CSM who moves to a new situation without saying so inherits a scenario key that makes every later answer quietly about the wrong thing, which is why an answer names its scenario.
_Avoid_: context id, session key, sticky scenario.

**Quote bleed**:
An answer stitching its quote out of an EARLIER turn's grounding source rather than its own. Putting history in a prompt is what creates it: previously quoted Naren text is in the context window, and a quote lifted from there is genuinely verbatim of something he said — just not of the exchange this answer rests on. Prevented structurally rather than by instruction: the follow-up prompt is shown one exchange, and the grounding gate verifies against that same one.
_Avoid_: cross-contamination, stale quote, leakage.

**Vector store**:
**Built** (ADR 0008). Where Ask Naren's vector operations run: Brain's Pinecone
`narens-brain-3072` index, queried per situation. It **ranks**; it does not decide what is
answerable. The **retrieval pool** — the coachable `kb_pairs` read once from Postgres at
startup — remains the authority, and a ranked `pair_id` the pool does not hold is skipped.
That split is load-bearing: the two correctness gates (content dedup, and the coachable-only
restriction delegated to Brain's one definition of a sink) are not fully expressible in a
metadata filter. Its search is **approximate** — an ANN index, scoring a stored unit vector
against itself between 0.999321 and 1.00135 — which is why `match.cosine` is clamped into
[-1, 1] and why equality with the old in-memory search is a measurement (top-1 47/47) rather
than a property.
_Avoid_: the vector DB, the index, embeddings store, retrieval backend.
