# A Layer C answer is verified at build time for the document and at request time for one quote

Issue #17 shipped `procedure`, the first Layer C answer path: a CSM asks for the general play for a kind of situation and gets it from that scenario's playbook. It goes through the same grounding gate as a Layer B answer, and it passes.

But it is not grounded as strongly, and the first live run made that visible rather than theoretical. This records the difference precisely, because "grounded answer" is a term this project uses as a guarantee and a reader who assumes it means the same thing on both paths would be wrong.

## The difference, in one comparison

Asked "whats the play when spend overruns halfway through the month" (2026-09-09, live), the answer was a three-move play. **One** quote was verified at request time.

| | Layer B (`reply_to_client`) | Layer C (`procedure`) |
| --- | --- | --- |
| What the answer is | a paraphrase of ONE exchange | a summary of N moves |
| What the model must quote | Naren's reply in that exchange | one evidence quote from one move |
| What the verified quote covers | essentially the whole answer | one move of N |
| Where the rest comes from | nowhere — there is no rest | the other moves in the playbook |

So the guarantee **"this answer rests on something Naren really said"** holds identically on both paths. The guarantee **"every claim in this answer was verified against a transcript in this request"** holds on Layer B and does not hold on Layer C.

## The mitigating fact, and it is measured

The unquoted moves are not ungrounded in the sense of invented. **A playbook's evidence was verified offline, at build time, by the verbatim snap** — and that snap is what validated the Layer C method at all:

- the pilot **failed** PB0 pre-snap on model quote-smoothing (~1.4% drift per quote) and passed **10/10** after it;
- the snap repaired **17 quotes** across four artifacts;
- `ops/load_playbooks.py` **refuses** to load a pre-snap document, because "pre-snap documents carry quotes that match no real evidence".

So Layer C's grounding is real, it is just **verified in a different place and at a different time**: the whole document at build time, one quote at request time. Layer B verifies the whole answer at request time and has no build step to lean on.

That is the honest statement of what ships, and it is the title of this ADR.

## What we decided

**One verified quote per Layer C answer, not one per move.** The `procedure` path asks for a single `quote`/`cited_call` pair, exactly as every other path does, and the gate verifies it against the evidence of the moves the prompt actually rendered (`answering.procedure_moves`).

### Considered and rejected: a quote per move

The model returns an array of `(move, quote, cited_call)` and the gate verifies each one, declining unless all of them hold.

Strictly stronger, and rejected for now on three counts:

1. **It changes the JSON contract**, which is currently identical across all four answer paths. One contract is what lets one gate serve all of them; a second shape is a second thing to get wrong, and ADR 0007 already records that the model's output shape is the part a schema can constrain while judgement is not.
2. **It raises the decline rate on a path with no measured accuracy yet.** A three-move answer would need three verified quotes or nothing. Issue #17 has a routing measurement (6/7 held out) and **no answer-quality measurement at all** — the blind read that would justify trading answers for strictness has not been run on this path.
3. **It is not obviously what a CSM wants.** The play IS the summary; a per-move quote requirement pushes the answer toward reciting transcript rather than telling someone what to do.

### Considered and rejected: answer from one move only

The strongest possible grounding — quote it, verify it, answer from it. Rejected because it stops being the play. Issue #17 asked for "the general play for a kind of situation", and one move is not that.

### Considered and rejected: render the moves and skip the gate

Never seriously. The gate is a gate, not a metric (ADR 0002, `CONTEXT.md`), and an answer path without one is the soft underbelly issue #12's story 38 exists to prevent.

## Consequences

- **`grounded answer` means something weaker on Layer C, and the glossary now says so.** Anyone quoting "every answer is grounded" as a per-claim guarantee is over-claiming on this path.
- **The blind read is what would settle it.** If a Layer C answer's unquoted moves turn out to drift from the play, that is an answer-quality finding and the instrument for it already exists (`ask-naren/audit/`, ADR 0004). Nobody has run it on this path.
- **Issue #18's intents inherit this**, all five of them. `phrasing` is the interesting exception: `signature_language` entries ARE quote-shaped one-to-one, so that path can plausibly verify its whole answer. Do not assume the others can.
- **A catch-all scenario makes it worse**, which is why `procedure` names its scenario. `application_volume_and_prioritization` carries 11.8% of coachable pairs and 16% of what routes there is about jobs rather than applications — a Layer C answer routed there is a summary of the wrong play, verified quote and all.

## What would change this

A measured case of a Layer C answer being wrong in an unquoted move. That converts the per-move alternative from "strictly stronger in principle" into "fixes an observed failure", which is the bar this project applies to every other gate it has considered — and it is the same bar ADR 0005 used to reject a retrieval floor.

## What this does NOT establish

**That Layer C answers are less accurate than Layer B answers.** This is a statement about what the request-time gate verifies, not about how often either path is right. Layer B's ~80% was measured; Layer C has no equivalent number, and the honest reading of this ADR is that one is owed — not that the path is weaker in outcome.
