# A thread's history never reaches the embedded query

Ask Naren is gaining multi-turn **threads**, so a follow-up can be answered in the light of what was already asked and answered. The obvious implementation is to search on the conversation: concatenate the thread, embed that, retrieve. A reader who finds that we did not do this will assume it was an oversight, so this records that it was a decision.

We decided that **a thread's history never reaches the embedded query.** Retrieval always embeds the current message alone.

The rule is about the **vector**, not about which components may read the thread. History reaches **intake** (which cannot detect a follow-up, resolve its own clarify, or avoid re-asking one without it) and it reaches **generation**. It does not reach the string that becomes a query vector.

The corollary, which is what makes multi-turn workable at all:

> History may supply an **identifier**. It may never supply **text that gets embedded**.

A scenario key, a `pair_id`, "the grounding source already cited" — passing any of those forward involves no embedding, so none of the dilution measured below applies to them. This is not a loophole; it is the whole distinction. "And what usually goes wrong?" is a question about a scenario it does not name, and the scenario can only come from the thread. Reading this ADR as forbidding that would make multi-turn Layer C impossible while preventing nothing the measurement warns about.

The reason is a measured mechanism, not a preference. `ask-naren/audit/probe_query_framing.py` measured what happens when text shared across queries is added to the search side, and it is not benign.

## What the framing probe measured (2026-08-27, embeddings only, n=36)

| query | top-1 changed | mean cosine | cosine range | same-scenario |
| --- | --- | --- | --- | --- |
| bare client turn | — | 0.808 | 0.734–0.858 (0.124 wide) | 14/36 |
| + terse frame | 26/36 (72%) | 0.786 | 0.745–0.847 | 17/36 |
| + operator's own phrasing | **29/36 (81%)** | 0.766 | 0.737–0.813 (**0.076 wide**) | 9/36 |
| + verbose frame | **31/36 (86%)** | 0.766 | 0.738–0.805 | 6/36 |

**The mechanism is dilution by boilerplate, and it is general rather than one bad template.** Text shared by every query pulls all queries toward each other: the cosine range collapses from 0.124 to 0.076 wide and the top end falls 0.858 → 0.813. The effect scales monotonically with how much shared text is added (terse 26 < operator 29 < verbose 31), which is what rules out "just word it better".

**A thread is the same mechanism, and worse.** Previous turns are text shared across every subsequent query in that thread, and unlike a fixed frame the quantity grows with the conversation. The dilution compounds turn over turn.

It also degrades cosine as an instrument in its own right: a compressed range carries less information, which makes a retrieval floor even less usable than ADR 0005 already found it to be.

## Considered and rejected: let intake rewrite a standalone query

The alternative was to have **intake** judge whether a message is self-contained and, when it is not, rewrite it into a standalone query to embed. This is strictly better in principle — it handles "what about the second one?", which retrieves nothing useful on its own words.

Rejected for two reasons. First, a rewrite is an unmeasured new failure mode inserted into the only path in this tool that carries a measured accuracy number; a bad rewrite is indistinguishable from a bad question and would be invisible in the response. Second, the case it exists for is already covered: intake routes a **follow-up** to *no retrieval at all*, answering from the thread and the grounding source already cited. There is no new search to dilute, so there is nothing for a rewrite to fix.

## Consequences

- A follow-up that is **both** not self-contained **and** genuinely needs a different grounding source than the one already cited is the gap this leaves. Intake must classify it as a new question rather than a follow-up, which means the CSM's own wording has to carry enough to retrieve on. Where it does not, the correct behaviour is **clarify**, not a silent guess.
- Every retrieval in a thread stays comparable to the retrieval the ~80% accuracy number was measured on, because the query is one message either way.
- **Carried identifiers are load-bearing, so trimming a thread is not truncation.** The request body is capped, and the obvious trim rule — drop the oldest messages — is wrong here: the message that established the scenario is usually the first one, and later turns inherit that identifier. Whatever is dropped, the carried identifiers have to survive it.
- **A carried identifier can strand.** If the CSM moves to a new situation without saying so, an inherited scenario key makes every later answer quietly about the wrong scenario. Naming the scenario in the answer is what lets a CSM catch it.

## What this does NOT establish

**That conditioning retrieval on history would actually reduce accuracy.** The probe shows retrieval *changes*, not that it *degrades*, and this project's own issue #8 is the counterweight: the model selecting a different exchange in 11 of 18 situations moved correctness exactly once. Different source does not imply different verdict.

So this is a decision taken under a **measured hazard, not a measured harm**. It is the conservative choice on the one path with a recorded number. If someone later wants retrieval to see the thread, the honest way in is to measure accuracy under both, not to argue from the cosine table above — which reports a distribution shift and nothing about right or wrong.
