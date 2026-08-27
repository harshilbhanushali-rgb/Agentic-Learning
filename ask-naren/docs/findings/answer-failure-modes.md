# Why the remaining ~20% of Ask Naren's answers are wrong

**Status: PARKED BY DECISION, 2026-08-27.** Accuracy is ~80% and considered good enough to
build the rest of the MVP on (#3, #4, #5, #6) before returning to it. This file exists so
that work resumes from evidence instead of re-deriving it. Follow-up: issue #9.

**Do not re-propose candidate selection, a retrieval-cosine floor, or a rank cutoff.** All
three were measured and rejected — see `adr/0005-candidate-selection-and-retrieval-floor-measured-and-rejected.md`.

## The number

Measured 2026-08-27 across two gated blind reads (issue #8), 36 situations, shipped path:

| | answers delivered | right | wrong |
| --- | --- | --- | --- |
| k=1 (shipped) | 24 of 36 | 19 | 5 |
| k=5 (rejected) | 22 of 36 | 18 | 4 |

Issue #7's earlier read put the same shipped arm at 20/24. Both land near 80% and are
within-packet numbers; see `../audit/blind_read_rubric.md` on why they must not be
subtracted from each other.

## All nine failures are ONE failure

Every wrong answer in both arms has the same shape: **the retrieved exchange is about the
right topic and answers a different question.** The answers are fluent, correctly cited, and
verbatim-quoted. Grounding is not the problem — relevance is.

| # | arm | cos | rank | same scenario | the mismatch |
| --- | --- | --- | --- | --- | --- |
| 1 | k=5 | 0.757 | 3 | yes | "Do you use WhatsApp for acquisition?" → answer about revamping docs and the ATS |
| 2 | k=1 | 0.810 | 1 | no | "we never capped at city level" → answer treats CPL variance as noise to monitor |
| 3 | k=5 | 0.792 | 3 | no | client's existing 10–20 day LinkedIn rotation → answer pitches Joveo's configurable rotation |
| 4 | k=1 | 0.772 | 1 | no | "Do **you** use WhatsApp?" → retrieved the **client's own** Line/WhatsApp plans |
| 5 | k=1 | 0.804 | 1 | no | same rotation situation → answer recommends a generic "every 4 days" from a slot-count exercise |
| 6 | k=1 | 0.766 | 1 | no | "how do I get data before June 1?" → imports a past incident's cause (Fountain tags, fixed Jan 20) |
| 7 | k=5 | 0.824 | 4 | no | "social ads for **gig work**?" → general Facebook mechanics; the qualifier was the question |
| 8 | k=1 | 0.845 | 1 | yes | "stored in the job posting on Indeed's side?" → the 80/20 rule on application data |
| 9 | k=5 | 0.762 | 1 | no | "give me reasons: efficiency, reach, ad-dollar control" → career-site SEO from a vendor-change exchange |

Three recurring sub-shapes, all propositional rather than topical:

1. **Subject inversion** (#4, #1) — "do *you* do X" retrieves "*we* are considering X". Near-identical in embedding space, opposite in meaning.
2. **Dropped qualifier** (#7, #8) — the specific narrowing term ("gig work", "in the job posting") is the entire question, and topical similarity ignores it.
3. **Imported specifics** (#6, #9, #3, #5) — a concrete detail from an adjacent exchange presented as if it applied here. This is the id 28/30 shape from #7 in general form.

## Why every instrument tried is blind to it

Cosine measures **aboutness**. These nine pairs genuinely *are* about the same subject, which
is why they score 0.757–0.845 — squarely inside the right answers' range (0.720–0.858).
Scenario labels are clusters of aboutness and inherit the blindness. Rank is cosine sorted.

None of the three can represent the **specific proposition being asked**, which is where all
nine failures live.

**The structural hole:** the grounding gate verifies the *answer against the source*. Nothing
anywhere verifies the *source against the question*. That check does not exist in the
pipeline.

## Two weak signals, both too small to act on (n=9)

- **Question marks**: failures carry 0.89 per item against 0.43 among right answers. Consistent with the mechanism — an explicit direct question has specific propositional content that "aboutness" discards.
- **Primary-scenario agreement**: 2/9 among wrong against 19/37 among right. Suggestive, but #7 established that scenario-label comparison is near-circular (labels and retrieval both come from cosine in the same space), and no runtime scenario classifier for a CSM's free text exists.

**Ruled out**: situation length. 82% right below 400 chars, 77% at or above — noise at every
threshold tested.

## The experiment to run when this is picked up

**The oracle test, and it is decisive.** For each item take a wide window (top-50 by cosine —
embeddings are already cached, no answer generation needed) and ask a model per candidate:
*does Naren's reply here answer the specific question this situation asks?* Two outcomes,
pointing at completely different products:

- **A qualifying exchange exists** → the corpus holds the answer and retrieval reached its neighbourhood; selection-by-cosine is the wrong criterion. Build an answerability reranker over a wide window. This would also explain why k=5 failed: five-by-cosine may never have contained the right candidate.
- **No qualifying exchange exists** → the corpus does not cover these situations and the correct behaviour is to decline. Build a better decline signal; no retrieval work would ever have helped.

**Design requirement, learned the expensive way twice on this project:** run the oracle over
the items judged RIGHT as well. If it reports "a better exchange exists" just as often for
answers that were already right, it is not diagnostic — it is a model that always says yes.
An instrument with no negative case measures nothing.

**Cheaper companion probe:** over the existing 46 items, judge *does the retrieved client turn
ask the same kind of question about the same subject as the situation?* If that separates 9
wrong from 37 right, it is a runtime relevance gate that beats cosine and it fills the
structural hole above. Needs only committed artifacts and ~46 judgments.

## The input distribution: MEASURED 2026-08-27, and it moves retrieval

Every situation in every read is a **verbatim client turn** lifted from a transcript. What a
CSM actually types is the client's words RELAYED inside a request frame -- established by
asking the operator, who put it as: *"A client said this thing, so can you help on how would
Naren reply to this situation?"* That is a relay, not a paraphrase, which means the eval's
query CONTENT was closer to production than assumed. The frame was the missing part.

`../audit/probe_query_framing.py` measures what the frame does. No generation, no reader --
only embeddings, so it was cheap enough to run before anything else.

| frame | top-1 changed | mean cosine | cosine range | same-scenario |
| --- | --- | --- | --- | --- |
| bare turn (what every eval used) | -- | 0.808 | 0.734-0.858 | 14/36 |
| operator's phrasing | **29/36 (81%)** | 0.766 | 0.737-0.813 | 9/36 |
| terse variant | 26/36 (72%) | 0.786 | 0.745-0.847 | 17/36 |
| verbose variant | **31/36 (86%)** | 0.766 | 0.738-0.805 | 6/36 |

**Production retrieval is not what any eval measured.** With a request frame, retrieval
reaches a DIFFERENT exchange in ~81% of situations. The ~80% accuracy figure was measured on
a retrieval distribution production would essentially not reproduce.

**The mechanism is dilution by boilerplate, and it is general rather than one bad template.**
The cosine range collapses from 0.124 wide to 0.076 and the top end falls 0.858 -> 0.813:
text shared by every query pulls all queries toward each other. The effect scales with frame
length (terse 26 < operator 29 < verbose 31), which is what rules out "just reword the
template".

**It also degrades cosine as an instrument** -- a compressed range carries less information,
so a retrieval floor is even less usable than ADR 0005 already found.

### What this does NOT establish

**That accuracy drops.** Retrieval changing is not retrieval degrading, and this project's own
issue #8 result is the counterweight: the model selecting a DIFFERENT exchange in 11 of 18
cases moved correctness exactly once. Different source does not imply different verdict.

Against that: both degrading signals point the same way here (cosine down, same-scenario
14->9), and unlike #8 -- which reshuffled within one query's top-5 -- framing moves the query
vector to a different neighbourhood entirely. Unmeasured, and it is the next experiment.

### The fix this suggests is a PRODUCT fix, not a model one

Do not embed the frame. Rather than build an extractor to guess which span of free text is
the client's words, **ask for them separately**: two fields, *what the client said* and *what
you need*, where only the first reaches retrieval and both reach generation. Cheaper and more
reliable than extraction, and mostly a change to the page built in #3.

## Standing limits on every number here

1. **n = 36 situations**, 9 wrong. Every pattern above is a hypothesis generated from the failures, not a finding.
2. **The reader was a model, not a CSM.** Cross-read agreement was measured (two independent reads of 18 identical answers agreed 16/18, same marginal) which is reassuring, but agreement between two model readers is not agreement with a CS person. A CS person checking the 9 wrong plus a sample of the 37 right remains the cheapest strengthening available.
