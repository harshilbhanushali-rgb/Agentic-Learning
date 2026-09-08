# Ask Naren

An internal tool, built on top of the Brain pipeline's knowledge base, where a CSM describes a situation and receives an answer grounded in Naren's closest real historical response to it.

## Language

**Ask Naren**:
The on-demand, text-based internal tool where a CSM describes a situation and receives an answer grounded in Naren's closest real historical response to it.
_Avoid_: coaching bot, Naren chatbot, the chatbot.

**Grounded answer**:
An Ask Naren answer that cites the specific past call (`kb_pair`, from Brain's Layer B) it paraphrases. Ask Naren never returns an answer without one — if no close match exists, it declines rather than answering ungrounded.
_Avoid_: cited answer, sourced answer.

**Pairs-only prompt**:
The Ask Naren prompt variant that answers using only the matched `kb_pair` (Brain's Layer B), with no playbook context.
_Avoid_: variant A, baseline prompt.

**Playbook-augmented prompt**:
The Ask Naren prompt variant that adds the scenario's Brain Layer C playbook (`key_moves`) to the matched `kb_pair` as extra context.
_Avoid_: variant B, playbook prompt.

**Grounding gate**:
The check Ask Naren runs at request time, before a grounded answer reaches the CSM: the model's returned quote must verify as verbatim against the answer's **grounding source**, and what it cites must be something it was actually shown. There is ONE gate; what differs between answer paths is the grounding source, never whether an answer has one. **Only the `kb_pair` source is built** -- the gate verifies against a retrieved pair's response text today; issue #17 generalises it. On failure Ask Naren regenerates once and then declines rather than showing an unverified answer. This is what makes the citation guarantee in `docs/adr/0002-citations-are-unredacted.md` a property of every live answer instead of a statistic from an offline eval.
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
**Built for three intents** (issue #14): answering from a client's words, clarifying, and declining an out-of-scope question. Issues #17-#23 add the rest. What kind of question a CSM is asking — reply to a client, the general play for a scenario, Naren's phrasing, what the tool even covers. A classification with a knowable correct answer, which is what makes intake measurable without a reader or a generation.
_Avoid_: question type, category, route.

**Answer path**:
**Partly built** -- `reply_to_client` ships, and intake also routes to clarify and to an out-of-scope decline (issue #14); the layer paths are issues #17-#23. The machinery that serves one intent end to end, including which Brain layer it reads. Distinct from an intent because a composite path reads several layers, and distinct from Brain's **routing**, which means assigning a pair or turn to a scenario — something Ask Naren also does, which is why the two must not share a word.
_Avoid_: route, handler, pipeline.

**Grounding source**:
**Named now, variable later** -- every live answer grounds in a `kb_pair`; the playbook source is issue #17. The specific stored text an answer must rest on, and what the grounding gate verifies its quote against. A Layer B answer grounds in the matched `kb_pair`'s response text; a Layer C answer grounds in the playbook's evidence quotes.
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
