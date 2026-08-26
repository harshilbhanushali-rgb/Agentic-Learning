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
The check Ask Naren runs at request time, before a grounded answer reaches the CSM: the model's returned quote must verify as verbatim against the cited `kb_pair`'s response text, and the call it cites must be the one that was actually retrieved. On failure Ask Naren regenerates once and then declines rather than showing an unverified answer. This is what makes the citation guarantee in `docs/adr/0002-citations-are-unredacted.md` a property of every live answer instead of a statistic from an offline eval.
_Avoid_: quote check, verbatim check, hallucination filter.

**Retrieval floor**:
A minimum-similarity threshold below which Ask Naren would decline regardless of what the model says. Proposed, **not built**: retrieval cosine was measured not to separate right answers from wrong ones (0.814 against 0.798), so a floor on it would refuse answers at random with respect to quality. Whether a floor is needed on some other signal is open — see `docs/adr/0004-answer-quality-is-measured-by-blind-read-behind-two-sided-controls.md` and issue #8.
_Avoid_: confidence threshold, similarity cutoff.

**Candidate selection**:
Which retrieved moments reach the prompt. Ask Naren ships top-1 — the single nearest `kb_pair`. Distinct from retrieval quality, and measured to be the more tractable problem: the right-topic moment is usually present in the ranking without being first. Issue #8 measures top-1 against top-5.
_Avoid_: reranking, top-k tuning.
