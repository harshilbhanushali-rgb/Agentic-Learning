#!/usr/bin/env python3
"""Issue #14's gate: how often does INTAKE route a message correctly?

    python ask-naren/audit/measure_intake_accuracy.py                  # the fitted set
    python ask-naren/audit/measure_intake_accuracy.py --set heldout    # the real number
    python ask-naren/audit/measure_intake_accuracy.py --set threaded   # issue #16
    python ask-naren/audit/measure_intake_accuracy.py --set procedure  # issue #17
    python ask-naren/audit/measure_intake_accuracy.py --set rendered   # issues #19, #20
    python ask-naren/audit/measure_intake_accuracy.py --set playbook   # issue #18
    python ask-naren/audit/measure_intake_accuracy.py --limit 6        # smoke test

WHY THIS IS CHEAP, AND WHY THAT MATTERS. Every other quality question in this project needs a
blind reader, two-sided controls and a warning that absolute rates are artifacts of framing.
Routing is not like that: it is a CLASSIFICATION WITH A KNOWABLE CORRECT ANSWER. A message
either does or does not contain the client's own words. So this needs no reader, no
generation of answers, no packet and no gate -- one intake call per message and a comparison
against a label written by hand.

THE NEGATIVE CASES ARE NOT OPTIONAL. Roughly half of these messages must NOT clarify. An
instrument with no negative case measures nothing: an intake that clarified on absolutely
everything would score 100% against a clarify-only set while being useless, and this project
has paid for that lesson twice (`ask-naren/audit/README.md`, ADR 0004). The two rates that
matter are reported separately for exactly that reason.

*** THE FIRST RECORDED SCORE IS FITTED, NOT HELD OUT. *** The initial run scored 10/12 and
the two failures were used to rewrite intake's prompt discriminators (a client asking about
Joveo's product is still a client turn; reported speech with specifics is searchable). The
rerun scored 12/12 ON THE SAME TWELVE CASES. That is a repaired instrument, NOT an accuracy
rate, and quoting it as one would be the same error as comparing two blind reads. n=12.

To get a number worth quoting, add cases that were NOT used to write the prompt and report
them separately. The two failures are worth keeping in mind when writing them, because they
are where the real boundary lies:

  - "Do you guys use WhatsApp?" -- a CLIENT asking about our product, which is a client turn
    Naren has answered, not an out-of-scope internal question.
  - "client is asking why spend went up 40% in March" -- reported speech carrying a specific
    claim. Over-clarifying here is the failure that makes the tool annoying rather than wrong.

## THE INSTRUMENT WAS WRONG BEFORE THE MODELS WERE (read this first)

An early version of the held-out set contained "do we have a case study for a client like
this", labelled `out_of_scope`. The label was AMBIGUOUS -- by the prompt's own definition it
is out_of_scope, but "a client like this" gestures at an undescribed client situation, which
makes clarify equally defensible. Every model tested flipped on that one case and on no other,
so a 9-vs-10 gap that read as a model difference was ONE BAD LABEL. It was withdrawn and
split into two unambiguous cases, one per reading.

The cost of not catching it sooner: three successive and contradictory recommendations about
which model to ship. **A model comparison is only as good as its weakest label**, and a single
ambiguous case in n=10 is enough to invert the ranking. Check that a case has one defensible
answer before adding it.

## MODEL AND REASONING BUDGET: MEASURED 2026-09-08

### Final, on the repaired 11-case held-out set, all at reasoning=low

| model | route | quality checks | $/1k queries |
| --- | --- | --- | --- |
| **gemini-3.6-flash** | **11/11** | all clean | **0.83** |
| gemini-2.5-flash-lite | 10/11 | all clean | 0.37 |
| gemini-3.5-flash-lite | 10/11 | framing leaked on one | 0.37 |

Both cheaper models drop one case, and DIFFERENT ones -- 2.5 misses the clarify, 3.5 misses
the out_of_scope and leaks framing. `gemini-3.6-flash` stays shipped: the saving is $0.46 per
thousand questions, which buys a misroute roughly every eleventh question.

### The reasoning-budget finding, which is the bigger win and independent of the model

Measured over the earlier 10 held-out cases:

Prompted by "can we use flash-lite, it's cheaper". Five configs, same prompt, same schema,
same cases, with token usage captured because once two configs tie on accuracy the decision
is cost:

| model | reasoning | route | total tokens | of which reasoning |
| --- | --- | --- | --- | --- |
| gemini-3.6-flash | none sent | 10/10 | 15,847 | 6,042 |
| **gemini-3.6-flash** | **low** | **10/10** | **10,185** | **342** |
| gemini-3.5-flash-lite | none sent | 9/10 | 9,909 | 0 |
| gemini-3.5-flash-lite | low | 9/10 | 9,902 | 0 |
| gemini-3.5-flash-lite | medium | 10/10 | 15,674 | 5,813 |

**SENDING NO `reasoning_effort` IS NOT "NO REASONING".** `gemini-3.6-flash` reasons heavily
when left unconstrained -- 6,042 reasoning tokens across ten short classifications. Sending
`"low"` is a REDUCTION: 36% fewer total tokens for identical routing. Intake shipped without
the parameter and was therefore the most expensive config on this table. Fixed.

**flash-lite is not the saving it looks like.** It only reaches 10/10 with `medium`, and at
that point it costs the same tokens as unconstrained 3.6-flash -- so the cheaper per-token
rate is buying back only what its own reasoning budget spends. Against `3.6-flash` + `low` it
is within 3% on tokens and a whole model tier worse on judgement.

**flash-lite is also not deterministic here.** It scored 8/10 and then 9/10 on the same ten
cases at `temperature=0.0`. On n=10 that makes any 8-vs-9-vs-10 comparison partly noise, and
the run-to-run variance is itself a reason to prefer the stronger model for a step whose whole
job is a stable decision.

Two cases separate the tiers, both boundary cases: "client asked me straight up what our list
price is" (lite routes it `out_of_scope`, missing that a CLIENT asked -- the same discriminator
3.6-flash only got right after the prompt was rewritten) and "do we have a case study for a
client like this" (lite routes it `clarify`).

**And the split worth reusing:** lite held out scored 10/10 verbatim-span, 10/10 meaning
preserved, 10/10 framing stripped, and 9/10 on the route. Schema enforcement makes a weaker
model's OUTPUT safe and does nothing for its JUDGEMENT -- a sharper form of ADR 0001's "the
model is the lever, not the prompt", in the one place the schema was expected to close the gap.

Do not re-propose flash-lite for intake without new held-out cases and a better result. Do not
remove `reasoning_effort` on the assumption that absence means cheap.

## THE THREAD-SHAPED SET (`--set threaded`, issue #16)

Every packet in this project before this one was single-message, so intake's three history
judgements had nothing to be scored against. Each case here is a CONVERSATION plus the next
message, and the three judgements are: is this a follow-up, is this the answer to a clarify
already asked, and has this question been put before.

It carries TWO negative cases rather than one, and the second is the one specific to
threads:

  - messages that must not CLARIFY (as above), and
  - messages in a thread that must not be read as FOLLOW-UPS. This is the one that matters
    most here. An intake that treats everything in a conversation as a follow-up scores
    perfectly on the positive cases while answering every new client situation from
    whatever call happened to be cited last -- an answer that is grounded, internally
    coherent, and about the wrong client. Nothing downstream can catch that.

The `verbatim_span` check does double duty on this set: the retrieval query must be a span
of the CURRENT message, so a query assembled out of the conversation shows up as composed
rather than copied. That is ADR 0006's rule -- history may supply an identifier, never text
that gets embedded -- checked from the outside.

### The threaded result, 2026-09-08, gemini-3.6-flash at reasoning=low

| run | overall | must-not-clarify | must-not-follow-up | verbatim | meaning | framing |
| --- | --- | --- | --- | --- | --- | --- |
| held out, before any fix | 10/11 | 9/9 | 7/7 | 11/11 | 11/11 | 11/11 |
| after the prompt fix (**fitted**) | 11/11 | 9/9 | 7/7 | 11/11 | 11/11 | 11/11 |

*** THE 11/11 IS FITTED. QUOTE 10/11. *** The prompt was changed after reading the first
run, which is exactly what makes the second one a repaired instrument rather than an
accuracy rate -- the same distinction the twelve fitted cases above carry. n=11.

The single failure and its fix are worth more than either number. "And what if they push
back on price?" with NO conversation was routed `follow_up`. The prompt listed the intent
unconditionally and told the model it was "only available when there is a conversation
above"; the model took it anyway. The fix was to stop OFFERING the option when there is no
thread (`intake._follow_up_intent`), and the lesson generalises: **a rule saying an option
does not apply is weaker than the option's absence.** Nothing would have broken in
production -- `responding._guarded` turns a follow-up with no carried source into an
ordinary answer -- but the fallback would have been carrying a case that should never have
reached it.

### The single-message held-out set no longer reproduces its recorded 11/11

Re-run twice as a regression check after the threaded work: **10/11 both times**, failing
the same case both times -- "a client like this one would want a case study, do we have
something" (expected `clarify`, got `reply_to_client`).

**It is not the thread work.** With an empty thread `build_prompt` is BYTE-IDENTICAL to the
version at commit 88b7ed4, verified by loading that revision and comparing the output
directly rather than by reading the diff. Same model name, same temperature, same schema,
`no_cache=True`, so it is not a cache echo either.

So one of two things is true and this harness cannot distinguish them: `gemini-3.6-flash`
is not run-to-run stable on this case at temperature 0, or the model behind that name moved
under us. **Treat the recorded 11/11 as unreproduced rather than as a target.**

Note which case it is. This is one of the two rewrites of the ambiguous case withdrawn on
2026-09-08 -- the one written to be unambiguously `clarify`. The model's answer here is not
a defensible reading (there is no client utterance anywhere in it), so this is a genuine
miss rather than another bad label. It is left in place deliberately: withdrawing a case
because it started failing is tuning the instrument to the result.

WHAT THIS DOES NOT MEASURE. Whether the ANSWER is right. Intake changes which text reaches
retrieval; whether that produces better answers is issue #9's question and needs the blind
read. A perfect routing score here is compatible with no change in answer quality at all.

Needs the VPN (one gateway call per message). No Postgres, no embeddings, no writes.
## THE PROCEDURE SET (`--set procedure`, issue #17), 2026-09-08

`procedure` answers "what is the general play for X" from a scenario's Layer C playbook, and
adding it CHANGED THE PROMPT FOR EVERY MESSAGE -- the intent and its discriminator sit in the
unconditional section, because a CSM can ask for a play with or without a conversation. That
makes it a change to the one step whose accuracy is on record, so it was measured.

| run | overall | must-not-clarify | verbatim | meaning | framing |
| --- | --- | --- | --- | --- | --- |
| held out, before any fix | **6/7** | 6/6 | 7/7 | 7/7 | 7/7 |
| after the prompt fix (**fitted**) | 7/7 | 6/6 | 7/7 | 7/7 | 7/7 |

*** QUOTE 6/7. *** The prompt was changed after reading the first run, which makes the second
a repaired instrument rather than an accuracy rate -- the same distinction the fitted twelve
and the threaded set already carry. n=7.

The failure, and why it was worth a prompt change rather than a shrug: **"how do we usually
handle difficult clients" routed to `procedure`.** A play is looked up BY THE KIND OF
SITUATION, and "difficult" is a mood -- so there is no scenario to look up. Routed to
`procedure` it would embed "difficult clients", retrieve whatever is nearest (a catch-all,
most likely -- `application_volume_and_prioritization` carries 11.8% of coachable pairs), and
answer confidently with that scenario's play. Grounded, coherent, about nothing the CSM
asked. The discriminator now says a mood is not a situation.

**The negative half is the discriminator issue #12 names explicitly**: "presence of a
specific client utterance separates `reply_to_client` from `procedure`". Cases 4 and 5 are
the same topics as cases 1 and 2 with a client actually speaking, and they must stay on the
Layer B path -- the one with the measured accuracy number. An intake that routed every
how-do-we question to `procedure` would score 3/3 on the positive cases while quietly
diverting real client situations away from it.


# RENDERED-INTENT cases (issues #19, #20). The five intents that answer from stored rows
# with no model call: discovery, frequency, show_exchange, what_happened_next,
# coverage_check.
#
# HELD OUT: written before the discriminators were worded, not edited after a result.
#
# THE NEGATIVE HALF IS THE WHOLE POINT AGAIN, and here it cuts two ways. These five sit next
# to `reply_to_client` and to each other on boundaries a classifier actually fails on:
#
#   - about ONE SITUATION vs about the WHOLE CORPUS separates coverage_check from discovery;
#   - wanting NAREN'S WORDS vs wanting AN ANSWER separates show_exchange from
#     reply_to_client -- and a client can be quoted in both, which is what makes it hard.
#
# An intake that routed every "do you know about X" to `discovery` would return the whole
# topic list to someone asking about one situation, and an intake that read every quoted
# client turn as `show_exchange` would show a transcript to someone who asked what to say.


## THE RENDERED-INTENT SET (`--set rendered`, issues #19, #20), 2026-09-09

Five intents that answer from stored rows with no model call at all: `discovery`,
`frequency`, `show_exchange`, `what_happened_next`, `coverage_check`.

**8/8 HELD OUT, and this one needs no asterisk** -- the prompt was not changed after reading
the result, so unlike the procedure and threaded sets this is an accuracy rate rather than a
repaired instrument. n=8.

| set | overall | must-not-clarify | verbatim | meaning | framing |
| --- | --- | --- | --- | --- | --- |
| rendered, held out | **8/8** | 8/8 | 8/8 | 8/8 | 8/8 |

The two boundaries it exists to hold, both of which a classifier really can fail on:

  - **about ONE SITUATION vs about the WHOLE CORPUS** separates `coverage_check` from
    `discovery`. "Do you have anything on contract renewals" names a situation; "what kinds
    of things can i ask you about" names none. Getting this wrong returns the entire topic
    list to someone asking about one thing.
  - **wanting HIS WORDS vs wanting AN ANSWER** separates `show_exchange` from
    `reply_to_client`, and a client is quoted in BOTH cases -- which is what makes it the
    hard negative rather than a giveaway. Getting it wrong shows a transcript to someone who
    asked what to say.

### Adding five intents did NOT move the earlier sets

Ten intents now share one prompt, and every message is classified by all of it. So the two
recorded sets were re-run as a regression check rather than assumed:

| set | before #19/#20 | after |
| --- | --- | --- |
| held out (the core `reply_to_client` path) | 10/11 | **10/11** |
| procedure | 7/7 | **7/7** |

Same rate, and on the held-out set the same single case -- "a client like this one would
want a case study, do we have something". It now routes `coverage_check` rather than
`reply_to_client`, which is a nearer miss than before but still a miss: `coverage_check`
asks whether Ask Naren covers a SITUATION, and this asks whether we have a marketing
artifact. The case has now defeated three different intent sets and is worth watching, not
withdrawing -- withdrawing a case because it keeps failing is tuning the instrument to the
result.

*** A LESSON THAT COST NOTHING ONLY BY LUCK. *** The #17 notes above were appended to this
file as BARE PROSE outside the module docstring -- a syntax error that sat committed and
undetected, because `Brain/tests/` does not import anything under `ask-naren/audit/` and
nothing else compiles it. It surfaced only when the next edit happened to run the script.
If you add a section here, add it INSIDE this docstring, and if you touch any audit script,
compile it before committing.


## THE PLAYBOOK-INTENT SET (`--set playbook`, issue #18), 2026-09-09

The five a scenario's Layer C playbook answers by being rendered: `sequence`, `phrasing`,
`pitfalls`, `scenario_check`, `play_confidence`.

**8/8 HELD OUT, no asterisk.** The prompt was not changed after reading the result.

#18 makes this measurement an acceptance criterion in its own words -- "intake distinguishes
procedure from phrasing and from sequence, and those discriminators are MEASURED rather than
assumed" -- and it is the hardest set in this file, because SIX intents ask about THE SAME
PLAYBOOK for THE SAME SITUATION. Only the part wanted separates them:

| intent | what the CSM wants |
| --- | --- |
| `procedure` | the moves -- what do i do |
| `sequence` | the order -- what do i do FIRST |
| `phrasing` | the words -- how does he SAY it |
| `pitfalls` | the failure modes -- what goes WRONG |
| `scenario_check` | the preconditions -- does this even APPLY |
| `play_confidence` | the evidence -- how much is this BUILT ON |

Two negatives keep it honest: the same topic with a client QUOTED must stay on
`reply_to_client` (the Layer B path, the one with the measured accuracy number), and "how
many calls did we run for Uber last quarter" looks like `play_confidence` and is an internal
account fact.

### Fifteen intents share one prompt, and the earlier sets did not move

Re-run rather than assumed, as after every intent addition:

| set | before #18 | after |
| --- | --- | --- |
| held out (core `reply_to_client`) | 10/11 | **10/11** |
| rendered (#19, #20) | 8/8 | **8/8** |
| procedure (#17) | 7/7 | **7/7** |

The held-out failure is the same case it has been for three intent sets now -- "a client like
this one would want a case study, do we have something". It has moved `reply_to_client` ->
`coverage_check` as intents were added, each time to a nearer miss, and it is still a miss:
`coverage_check` asks whether Ask Naren covers a SITUATION, and this asks whether we have a
marketing artifact. Worth watching, not withdrawing.

## RE-RUN AFTER #18's REVIEW, 2026-09-09 (`*_post_guard.json`)

#18's review found that the prompt's rules block never told the model to set a
`retrieval_query` for the five playbook intents, although the decision validator REQUIRED
one -- so a decision that omitted it failed validation twice and fell through to
`reply_to_client` on the raw framed message. Fixing it added a rules line naming all five,
which changes the prompt for EVERY message.

So all four sets were re-run. **Held out, not fitted** -- the change fixed a structural
defect found by reading the code, not a score, and it was written before any of these ran:

| set | recorded | after the fix |
| --- | --- | --- |
| playbook (#18) | 8/8 | **8/8** |
| rendered (#19, #20) | 8/8 | **8/8** |
| procedure (#17) | 7/7 | **7/7** |
| held out (core `reply_to_client`) | 10/11 | **10/11** -- the same case-study case |

Verbatim-span, meaning-preserved and framing-stripped were clean on all 34 cases.

**THE INSTRUMENT WAS NARROWER THAN THE GUARD.** `verbatim_span` was scored only where
`intent == "reply_to_client"`, while `responding._guarded` enforces the span rule on every
intent in `intake.RETRIEVING_INTENTS`. Closed with #21: it is now scored on the same list
the service enforces, so the instrument, the guard, the validator and the prompt's rules all
read one tuple. Every case passed it under the old narrow check and under the new wide one,
so nothing was being hidden -- but that was luck rather than design.

**Still owed**: thread-shaped playbook cases. A composed query is a thread phenomenon -- "and
what usually goes wrong?" names no situation, so that is where a model has to compose to
answer at all -- and every case in the playbook and contrast sets is single-message. The
widened check therefore covers the right intents on the wrong shape of case.

## THE CONTRAST SET (`--set contrast`, issue #21), 2026-09-09

`contrast_my_reply`: the CSM has ALREADY replied to a client and wants their reply set
against Naren's closest real one.

**8/9 HELD OUT. Quote that number.** Stable across three runs on the shipped prompt.

### The first version of this set scored 8/8 and measured nothing

Worth recording because the mistake is subtle and this file exists to catch exactly it. The
first four positives were near-restatements of `intake.build_prompt`'s OWN illustrative
examples -- "i told them we'd review the settings this week, is that how naren would have
handled it" is in the prompt almost verbatim. The prompt was never tuned to the cases, and
file mtimes prove the ordering, so by the letter of the rule the score was held out.

It was still fitted, by the other route: **the cases were written from the prompt.** A set
built that way can only confirm that a model reproduces the examples it was given, which is
not a question anybody needed answered. It scored 8/8 and hid a real failure.

Rewritten to the bar `HELD_OUT` sets: different verbs, typos, colloquial speech, content
buried mid-message, nothing reusing a phrasing that appears in the prompt. The rewrite found
the miss immediately.

### What it measures

TWO SPANS out of one message -- the client's words, which get embedded, and the CSM's own
reply, which never does. So this set scores something no earlier set could: **the CSM's
reply is a copied span, 3/3 clean**, reported over the cases that produce one rather than
over all nine, because a 9/9 covering six silent rows reads as evidence when it is silence.

The discriminator is HAS THE CSM ALREADY REPLIED, and the MINIMAL PAIR is the whole test:
case 5 is case 1 with the reply removed and nothing else changed, and must stay
`reply_to_client` -- the Layer B path with the measured accuracy number. It holds.

### The one failure, and a fix that was measured and REJECTED

Case 3 routes `reply_to_client` instead of `contrast_my_reply`:

    on the call the client goes "we're not seeing any of this in our ATS". i answered that
    the feed runs nightly so theres a lag. is that the sort of thing hed say

The CSM has replied ("i answered that...") and asks whether it is what Naren would say. It
is unambiguously a contrast, and it is a fair case. The likely mechanism: a QUOTED client
turn plus a trailing "is that the sort of thing hed say" reads as asking what to say.

The obvious fix was tried and made things WORSE. Adding an explicit reply-marker list ("i
said", "i told them", "i replied", "i answered"...) plus "a quoted client turn does not
decide this" scored **7/9, stable across three runs** -- case 3 still failed AND case 4
started failing. Reverted. The artifact is kept as
`intake_accuracy_contrast_rejected_marker_rule.json` rather than deleted, because a measured
negative result is the cheapest thing to re-derive by accident.

Three runs each side, because `gemini-3.6-flash` is not run-to-run stable and a single pair
of runs could not tell an 8-vs-7 apart from noise. It is not noise: 8/9, 8/9, 8/9 against
7/9, 7/9, 7/9.

Not withdrawn, on the same principle as the persistent held-out case-study failure: tuning
the instrument to the result is how a set stops measuring anything.

### Sixteen intents share one prompt, and the earlier sets did not move

| set | before #21 | after |
| --- | --- | --- |
| held out (core `reply_to_client`) | 10/11 | **10/11** |
| playbook (#18) | 8/8 | **8/8** |
| rendered (#19, #20) | 8/8 | **8/8** |
| procedure (#17) | 7/7 | **7/7** |

Same persistent held-out failure, four intent additions running: "a client like this one
would want a case study, do we have something". Still `coverage_check`.

"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "Brain"))

from ask_naren import intake, threads              # noqa: E402
from config import load_config                     # noqa: E402
from shared.gateway import GatewayClient           # noqa: E402

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


# The span predicate lives in `intake` and is shared, not reimplemented here. Since #16 it
# is also a REQUEST-TIME GUARD (`responding._guarded`): a query the model composed rather
# than copied is discarded and the message is answered as written. Two definitions of
# "copied" would let this instrument certify something the service does not enforce.

# Hand-labelled. Each message says what a CSM would plausibly type and what intake must do
# with it. `note` records WHY the label is what it is, so a disagreement later is a debate
# about the case rather than about what the author meant.
CASES = [
    # -- must route to answering: the client's own words are present ---------------------
    {"message": "A client said this, can you help with how Naren would reply? "
                "\"Our cost per hire is way higher than what you promised in the pitch.\"",
     "expect": "reply_to_client",
     "query_must_not_contain": ["can you help", "Naren would reply"],
     "note": "the operator's own phrasing, with the client's words quoted inside it"},
    {"message": "client just told me \"we never agreed to cap spend at the city level\", "
                "what do i say",
     "expect": "reply_to_client",
     "query_must_not_contain": ["what do i say"],
     "note": "relayed words plus a trailing ask"},
    {"message": "\"Do you guys actually use WhatsApp for candidate outreach?\"",
     "expect": "reply_to_client",
     "note": "bare quoted client turn, no framing at all"},
    {"message": "On the call she said their LinkedIn rotation is every 10 to 20 days and "
                "asked why ours is different",
     "expect": "reply_to_client",
     "note": "reported speech rather than a quote -- still the client's actual content"},
    {"message": "how do i respond when a client says the applications we send are low "
                "quality and they are getting nothing usable",
     "expect": "reply_to_client",
     "note": "hypothetical framing, but the client's position is fully stated"},
    {"message": "client is asking why their spend went up 40% in March when nothing changed "
                "on their side",
     "expect": "reply_to_client",
     "note": "specific enough to retrieve on: a number, a month and a claim"},

    # -- must clarify: a summary where the client's words are needed ---------------------
    {"message": "client is unhappy about pricing",
     "expect": "clarify",
     "note": "the canonical thin message -- a topic label, no content"},
    {"message": "having a tough conversation with an account tomorrow, help",
     "expect": "clarify",
     "note": "no situation at all, only that one exists"},
    {"message": "they are frustrated with performance",
     "expect": "clarify",
     "note": "a mood and a topic; retrieval on this reaches everything and nothing"},

    # -- must decline: not in the corpus, and rewording cannot change that ---------------
    {"message": "what is our list price for a 12 month managed services contract",
     "expect": "out_of_scope",
     "note": "a pricing fact -- Layer B will happily answer this on-topic and wrong"},
    {"message": "does our contract allow a client to terminate for convenience at 30 days",
     "expect": "out_of_scope",
     "note": "a contract fact, same failure shape"},
    {"message": "what integrations do we support with Workday",
     "expect": "out_of_scope",
     "note": "a product fact"},
]

# HELD OUT. Written AFTER the prompt was finalised and never used to change it, which is the
# only reason a score over them means anything (the twelve above are fitted -- see the
# docstring). Deliberately nastier: negation, subject ambiguity, typos, a client asking about
# pricing, and a positive situation rather than a complaint.
#
# `query_must_contain` is the check that matters most here. A span can be copied and still be
# wrong if the model copies the WRONG span -- dropping a "not", or keeping "our" where the
# message said "their". Those are the two ways subject inversion and negation loss get in,
# and they are invisible to a routing-only score.
HELD_OUT = [
    {"message": "client asked me straight up what our list price is for a 12 month deal, "
                "how would Naren handle that",
     "expect": "reply_to_client",
     "note": "THE TRAP: a pricing question, but a CLIENT asked it, so it is a client turn "
             "Naren has faced -- not an internal fact lookup"},
    {"message": "she said they had NOT approved the budget increase and were surprised to "
                "see it live",
     "expect": "reply_to_client",
     "query_must_contain": ["not"],
     "note": "negation must survive the copy -- dropping 'not' inverts the situation"},
    {"message": "client wants to know whether we capped their city level spend or whether "
                "their own team did it",
     "expect": "reply_to_client",
     "query_must_contain": ["their own team"],
     "note": "two subjects in one sentence; a rewrite that collapses them changes the "
             "question being asked"},
    {"message": "cliant said thier cpa is like 3x what we quotd, wht do i tell them",
     "expect": "reply_to_client",
     "query_must_not_contain": ["wht do i tell them"],
     "note": "typos throughout -- the client's content is still fully present"},
    {"message": "client mentioned CPA again",
     "expect": "clarify",
     "note": "one specific noun and nothing else; not enough to search on"},
    {"message": "hey",
     "expect": "clarify",
     "note": "no situation at all"},
    {"message": "client said the last campaign was the best they have run in two years and "
                "asked how we would scale it, what do i say",
     "expect": "reply_to_client",
     "query_must_not_contain": ["what do i say"],
     "note": "a POSITIVE situation -- every fitted case was a complaint"},
    {"message": "whats our standard payment terms for a new enterprise logo",
     "expect": "out_of_scope",
     "note": "internal fact, no client in the picture"},
    {"message": "we got on the call and honestly it went everywhere, they talked about "
                "hiring targets for a while and then the client said the applications "
                "coming through are mostly out of state which is useless for their "
                "warehouse roles, and then we moved on to timelines",
     "expect": "reply_to_client",
     "query_must_contain": ["out of state"],
     "note": "client content BURIED in a rambling message -- the copy has to find it"},
    # WITHDRAWN 2026-09-08, and the reason matters more than the case.
    #
    #   {"message": "do we have a case study for a client like this",
    #    "expect": "out_of_scope"}
    #
    # The label was AMBIGUOUS and it was quietly deciding a model comparison. By the prompt's
    # own definition it is out_of_scope (the CSM asking about OUR materials), but "a client
    # like this" refers to a client situation that was never described, which makes clarify
    # equally defensible -- a human would split on it too. Both gemini-3.6-flash and
    # gemini-2.5-flash-lite flip on this one case and on no other, so a 9-vs-10 gap that
    # looked like a model difference was one bad label.
    #
    # Rewritten below as two UNAMBIGUOUS cases, one for each reading, which is what the
    # original was trying to be.
    {"message": "send me the Mercor case study pdf",
     "expect": "out_of_scope",
     "note": "unambiguously asking for our own material; no client situation at all"},
    {"message": "a client like this one would want a case study, do we have something",
     "expect": "clarify",
     "note": "gestures at a client situation without describing it -- nothing to search on, "
             "and the CSM has to say which situation before anything can be answered"},
]

# THREAD-SHAPED CASES (issue #16). Every packet in this project before this one was
# single-message, and intake's three history judgements -- is this a follow-up, is this the
# answer to a clarify I already asked, have I asked this before -- cannot be scored without
# a conversation to judge them against.
#
# HELD OUT by construction: written before intake's thread rules existed and not edited
# after reading a result. If they are ever used to rewrite the prompt, say so here and stop
# quoting the score, exactly as the fitted twelve above do.
#
# THE NEGATIVE CASES CARRY THE INSTRUMENT, and there are two kinds here rather than one:
#
#   * messages that must NOT be read as follow-ups. An intake that called everything in a
#     conversation a follow-up would score perfectly on the three positive cases while
#     answering every new client situation from whatever call happened to be cited last --
#     a wrong answer that looks completely normal, which is the worst shape of failure this
#     tool has.
#   * messages that must STILL clarify. Loop prevention must not become never asking: a CSM
#     who switches to a thin new situation mid-thread deserves their own question.
#
# `thread` is a list of turns in the wire shape (`Brain/ask_naren/threads.py`).
_ANSWERED = {
    "message": "client said \"our cost per hire is way higher than what you promised\", "
               "what do i say",
    "outcome": "answered",
    "reply": "Pull the last 90 days and show cost per hire against their own baseline "
             "rather than against our benchmark.",
    "pair_id": 4211,
    "scenario_key": "performance_pushback",
    "call_filename": "20230503_uber_joveo_weekly_performance_review.txt",
}
_ASKED_BACK = {
    "message": "client is unhappy about pricing",
    "outcome": "clarify",
    "reply": "What did the client actually say?",
}

# PROCEDURE cases (issue #17). The intent that answers "what is the general play for X" from
# a scenario's Layer C playbook, with no client quoted at all.
#
# HELD OUT: written before the discriminator was worded and not edited after reading a
# result. The negative half is the point, as everywhere else here -- issue #12 names the
# discriminator explicitly ("presence of a specific client utterance separates
# reply_to_client from procedure"), and an intake that routed every how-do-we question to
# `procedure` would score perfectly on the positive cases while quietly diverting real
# client situations away from the path with the measured accuracy number.
PROCEDURE = [
    # -- must route to the play: no client is quoted and none needs to be ------------------
    {"message": "how do we usually handle it when a client says their cost per hire is "
                "higher than we pitched",
     "expect": "procedure",
     "note": "the canonical one -- a KIND of situation, phrased hypothetically"},
    {"message": "whats the play when spend overruns halfway through the month",
     "expect": "procedure",
     "note": "preparing rather than reacting; no client in the room"},
    {"message": "how should i approach a QBR where performance is down",
     "expect": "procedure",
     "note": "asks for an approach, not for a reply to anything"},

    # -- must NOT route to the play: a client actually said something ----------------------
    {"message": "client just said \"our cost per hire is higher than you pitched\", what "
                "do i say",
     "expect": "reply_to_client",
     "query_must_contain": ["cost per hire"],
     "query_must_not_contain": ["what do i say"],
     "note": "THE DISCRIMINATOR. Same topic as the first case above, but a client utterance "
             "is present -- so it belongs on the path with the measured accuracy number"},
    {"message": "she told me on the call that spend overran and nobody warned her",
     "expect": "reply_to_client",
     "query_must_contain": ["spend"],
     "note": "reported speech is still a client utterance; the hypothetical version of this "
             "is the procedure case above"},

    # -- must NOT route to the play: still out of scope, still too thin --------------------
    {"message": "whats our standard discount for a two year commitment",
     "expect": "out_of_scope",
     "note": "a how-do-we question about OUR terms is an internal fact, not a play"},
    {"message": "how do we usually handle difficult clients",
     "expect": "clarify",
     "note": "names no situation at all -- 'difficult' is a mood. A play needs a KIND of "
             "situation to look up, so this one has to be asked about first"},
]


RENDERED = [
    # -- corpus-wide: no situation named ---------------------------------------------------
    {"message": "what kinds of things can i ask you about",
     "expect": "discovery",
     "note": "names no situation at all -- the canonical discovery question"},
    {"message": "which situations come up most often with clients",
     "expect": "frequency",
     "note": "asks for a ranking across everything, not about one case"},

    # -- about one situation ---------------------------------------------------------------
    {"message": "do you have anything on contract renewals",
     "expect": "coverage_check",
     "query_must_contain": ["renewal"],
     "note": "THE DISCRIMINATOR against discovery: it names a situation, so the answer is "
             "about that situation rather than the whole topic list"},
    {"message": "show me what naren actually said when a client pushed back on cost per hire",
     "expect": "show_exchange",
     "query_must_contain": ["cost per hire"],
     "note": "wants his words verbatim, not a paraphrase"},
    {"message": "how did that conversation carry on after he explained the pacing rules",
     "expect": "what_happened_next",
     "query_must_contain": ["pacing"],
     "note": "asks about the continuation of a call, not about a client situation"},

    # -- must NOT be read as rendered ------------------------------------------------------
    {"message": "client said \"our cost per hire is way above what you pitched\", what do i say",
     "expect": "reply_to_client",
     "query_must_not_contain": ["what do i say"],
     "note": "THE HARD NEGATIVE. A client is quoted here AND in the show_exchange case "
             "above; what separates them is wanting an ANSWER rather than wanting his words"},
    {"message": "how do we usually handle renewals that stall",
     "expect": "procedure",
     "note": "names a situation like coverage_check does, but asks for the PLAY rather than "
             "for whether we cover it"},
    {"message": "whats our renewal notice period in the standard MSA",
     "expect": "out_of_scope",
     "note": "an internal contract fact, however close the word 'renewal' sits to the "
             "coverage_check case"},
]


# PLAYBOOK-INTENT cases (issue #18). The five a scenario's Layer C playbook answers by being
# rendered: sequence, phrasing, pitfalls, scenario_check, play_confidence.
#
# HELD OUT: written before the discriminators were worded, not edited after a result.
#
# #18 NAMES THE MEASUREMENT AS A CRITERION -- "intake distinguishes procedure from phrasing
# and from sequence, and those discriminators are MEASURED rather than assumed" -- and it is
# the hardest set here, because all six of these intents ask about THE SAME PLAYBOOK for THE
# SAME SITUATION. What separates them is only which part of it the CSM wants:
#
#     procedure       -> the moves            (what do i do)
#     sequence        -> the order            (what do i do FIRST)
#     phrasing        -> the words            (how does he SAY it)
#     pitfalls        -> the failure modes    (what goes WRONG)
#     scenario_check  -> the preconditions    (does this even APPLY)
#     play_confidence -> the evidence         (how much is this BUILT ON)
#
# The negative cases are the ones that must stay OFF the playbook entirely: a quoted client
# turn still belongs to reply_to_client, however playbook-shaped the rest of the sentence is.
PLAYBOOK_SET = [
    {"message": "what do i do first when a client pushes back on cost per hire",
     "expect": "sequence",
     "note": "THE DISCRIMINATOR against procedure: asks for the ORDER, not the moves"},
    {"message": "how does naren actually word it when he reframes on their own baseline",
     "expect": "phrasing",
     "note": "wants his language, not an action"},
    {"message": "what usually goes wrong when people handle cost per hire complaints",
     "expect": "pitfalls",
     "note": "asks for failure modes"},
    {"message": "does the cost per hire play even apply if the client is comparing us to a competitor",
     "expect": "scenario_check",
     "note": "asks whether the play fits, not what it is"},
    {"message": "how many calls is the cost per hire play actually built on",
     "expect": "play_confidence",
     "note": "asks how well evidenced it is"},

    {"message": "how do we usually handle cost per hire pushback",
     "expect": "procedure",
     "note": "THE ANCHOR. Same situation as all five above; asks for the MOVES, which is "
             "the one procedure owns"},

    {"message": "client said \"your cost per hire is nowhere near what you pitched\", what "
                "do i say",
     "expect": "reply_to_client",
     "query_must_not_contain": ["what do i say"],
     "note": "THE HARD NEGATIVE. Same topic again, but a client is quoted -- so it belongs "
             "on the Layer B path, the one with the measured accuracy number"},
    {"message": "how many calls did we run for Uber last quarter",
     "expect": "out_of_scope",
     "note": "'how many calls' looks like play_confidence and is an internal account fact"},
]


#: NOT WRITTEN FROM THE PROMPT. The first draft of this set restated intake's own
#: illustrative examples back at it -- "i told them we'd review the settings this week, is
#: that how naren would have handled it" appears almost verbatim in `intake.build_prompt`.
#: It scored 8/8, and that 8/8 measured nothing: the prompt was never tuned TO the cases, but
#: the cases were written FROM the prompt, which produces a fitted number by the other route
#: and it is the same mistake `CASES` below is labelled FITTED for.
#:
#: Rewritten to the bar `HELD_OUT` sets: different vocabulary, different verbs, typos,
#: colloquial speech, reported and quoted client turns, content buried mid-message. Nothing
#: here reuses a phrasing that appears in the prompt.
CONTRAST = [
    {"message": "spoke to the ops lead at northstar, she said the applications we're "
                "sending are mostly out of state. i pushed back and told her the targeting "
                "radius was what they signed off on. would naren have gone there",
     "expect": "contrast_my_reply",
     "note": "THE CANONICAL CASE, in nobody's words but a CSM's. Reported client turn, "
             "reported reply, and 'would naren have gone there' -- a phrasing the prompt "
             "does not contain"},
    {"message": "they wrote in saying the january invoice doesnt match what we agreed. my "
                "response was that id pull the reconciliation and send it over by eod. "
                "curious how he handles those",
     "expect": "contrast_my_reply",
     "note": "typo'd, and the ask is 'curious how he handles those' rather than any of the "
             "prompt's example phrasings"},
    {"message": "on the call the client goes \"we're not seeing any of this in our ATS\". i "
                "answered that the feed runs nightly so theres a lag. is that the sort of "
                "thing hed say",
     "expect": "contrast_my_reply",
     "note": "QUOTED client turn this time, colloquial framing, reply buried in the middle"},
    {"message": "client escalated that we've missed the go live twice now. my plan is to "
                "say ill own it personally and come back tomorrow with a dated plan. how "
                "does that stack up",
     "expect": "contrast_my_reply",
     "note": "a DRAFT rather than a sent reply -- 'my plan is to say'. The prompt names this "
             "case but in different words ('i was going to tell them'), so this tests the "
             "rule rather than the example"},

    # -- the negatives ---------------------------------------------------------------------
    {"message": "spoke to the ops lead at northstar, she said the applications we're "
                "sending are mostly out of state. what do i say",
     "expect": "reply_to_client",
     "query_must_not_contain": ["what do i say"],
     "note": "THE MINIMAL PAIR, and the whole discriminator: case 1 with the CSM's reply "
             "removed and nothing else changed. Wanting an answer is not wanting a "
             "comparison, and this must stay on the Layer B path -- the one with the "
             "measured accuracy number"},
    {"message": "i replied to that client thing yesterday, was that how naren would do it",
     "expect": "clarify",
     "note": "A REPLY WITH NOTHING TO SEARCH ON. The CSM has replied, so the first half of "
             "the discriminator fires -- but no client words and no topic are anywhere in "
             "the message, so there is nothing to find the matching moment with. A contrast "
             "needs BOTH halves; this has one"},
    {"message": "how do we usually handle it when applications come in from the wrong "
                "region",
     "expect": "procedure",
     "note": "no client quoted and no reply written -- the general play"},
    {"message": "how does naren actually word it when he pushes back on targeting "
                "complaints",
     "expect": "phrasing",
     "note": "asks for HIS words with no reply of the CSM's own. The nearest playbook intent "
             "to a contrast, because both are about wording"},
    {"message": "whats our standard discount for a two year commitment",
     "expect": "out_of_scope",
     "note": "an internal fact, with no client and no reply anywhere in it"},
]


THREADED = [
    # -- must be read as follow-ups: no new situation, only the one already answered -------
    {"thread": [_ANSWERED],
     "message": "and what if they push back on price?",
     "expect": "follow_up",
     "note": "the canonical follow-up -- means nothing on its own words, and there is "
             "nothing new to search for"},
    {"thread": [_ANSWERED],
     "message": "why does he frame it against their own baseline instead of ours?",
     "expect": "follow_up",
     "note": "asks about the answer just given, not about a client"},
    {"thread": [_ANSWERED],
     "message": "what do i do if that does not land",
     "expect": "follow_up",
     "note": "no client utterance, no new situation -- going deeper on the same one"},

    # -- must NOT be read as follow-ups: a new situation in the same conversation ----------
    {"thread": [_ANSWERED],
     "message": "different client now -- she said \"we never agreed to cap spend at the "
                "city level\", how do i handle it",
     "expect": "reply_to_client",
     "query_must_contain": ["city level"],
     "query_must_not_contain": ["how do i handle it"],
     "note": "THE HAZARD: read as a follow-up this gets answered from the cost-per-hire "
             "call, which is grounded, coherent and about the wrong thing"},
    {"thread": [_ANSWERED],
     "message": "client just told me their ATS integration broke this morning and nothing "
                "is syncing",
     "expect": "reply_to_client",
     "query_must_contain": ["ATS"],
     "note": "a new client situation with its own content; the conversation is irrelevant "
             "to what should be searched"},

    # -- the answer to a clarify already asked: run the ORIGINAL question, do not re-ask ---
    {"thread": [_ASKED_BACK],
     "message": "he said \"your rates are 30% above what we budgeted for this quarter\"",
     "expect": "reply_to_client",
     "query_must_contain": ["30%"],
     "query_must_not_contain": ["he said"],
     "note": "the CSM supplying exactly what was asked for -- this must complete the "
             "earlier question, not be read as a brand new one"},
    {"thread": [_ASKED_BACK],
     "message": "she told me the applications coming through are mostly out of state and "
                "useless for their warehouse roles",
     "expect": "reply_to_client",
     "query_must_contain": ["out of state"],
     "note": "same, in reported speech rather than a quote"},

    # -- the loop: a clarify already asked must not be asked again -------------------------
    {"thread": [_ASKED_BACK],
     "message": "i dont have their exact words, they were just annoyed about pricing again",
     "expect": "reply_to_client",
     "note": "THE LOOP CASE. The CSM cannot supply what was asked for. Asking again is the "
             "dead end story 14 forbids, so this must fall through to a best-effort answer"},

    # -- loop prevention must not become never asking --------------------------------------
    {"thread": [_ANSWERED],
     "message": "another account is unhappy too, can you help",
     "expect": "clarify",
     "note": "a genuinely NEW thin situation mid-thread. It deserves its own question, and "
             "an intake that has learned never to ask would answer this from nothing"},

    # -- a conversation does not change what is out of scope --------------------------------
    {"thread": [_ANSWERED],
     "message": "whats our standard payment terms for a new enterprise logo",
     "expect": "out_of_scope",
     "note": "an internal fact is an internal fact whatever came before it"},

    # -- follow-up shaped, but there is nothing to follow up ---------------------------------
    {"thread": [],
     "message": "and what if they push back on price?",
     "expect": "clarify",
     "note": "the SAME words as the first case with no conversation behind them. A topic "
             "and no content, so there is nothing to search and nothing to go deeper on"},
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, help="only the first N cases (smoke test)")
    ap.add_argument("--out", default=str(ARTIFACTS / "intake_accuracy.json"))
    ap.add_argument("--set", dest="which", default="fitted",
                    choices=("fitted", "heldout", "threaded", "procedure", "rendered",
                             "playbook", "contrast", "both"),
                    help="fitted = the 12 the prompt was tuned on (NOT an accuracy "
                         "rate); heldout = cases never used to change the prompt; "
                         "threaded = the conversation-shaped cases (issue #16)")
    ap.add_argument("--reasoning", default=intake.REASONING_EFFORT,
                    help="reasoning_effort to send; omit for the shipped value, "
                         "'none' to send no reasoning budget")
    ap.add_argument("--model", default=intake.CHAT_MODEL,
                    help="override intake's model, to A/B a cheaper one on the same cases")
    args = ap.parse_args()

    load_config()
    pool = {"fitted": CASES, "heldout": HELD_OUT, "threaded": THREADED,
            "procedure": PROCEDURE, "rendered": RENDERED, "playbook": PLAYBOOK_SET,
            "contrast": CONTRAST, "both": CASES + HELD_OUT}[args.which]
    cases = pool[:args.limit] if args.limit else pool

    rows = []
    with GatewayClient() as gw:
        for n, case in enumerate(cases, 1):
            # Parsed rather than passed raw, so a case that does not match the wire shape
            # fails here instead of quietly measuring a thread the service would reject.
            thread = threads.parse(case.get("thread"))
            decision, _ = intake.classify(
                case["message"], gw, thread=thread, model=args.model,
                reasoning_effort=None if args.reasoning in (None, "none") else args.reasoning)
            leaked = [s for s in case.get("query_must_not_contain", [])
                      if s.lower() in decision.retrieval_query.lower()]
            # Tokens whose LOSS changes the meaning: a dropped "not", or a subject
            # collapsed away. A span can be copied and still be the wrong span.
            dropped = [s for s in case.get("query_must_contain", [])
                       if s.lower() not in decision.retrieval_query.lower()]
            # Is the query a span COPIED from the message, or prose the model composed?
            # A composed query is how subject inversion gets introduced -- "nothing changed
            # on their side" rewritten to "our side" is near-identical in embedding space
            # and means the opposite, which is the corpus's most common failure shape
            # (docs/findings/answer-failure-modes.md). Checked only where a query is
            # expected at all.
            #
            # SCORED ON EVERY INTENT THAT EMBEDS, matching what the service enforces. It was
            # scored only for `reply_to_client` while `responding._guarded` checked two
            # intents and eight embedded -- so the instrument was narrower than the guard,
            # which was narrower than the truth. One list, `intake.RETRIEVING_INTENTS`, now
            # drives the prompt's rules, the validator, the runtime guard and this.
            verbatim = (decision.intent not in intake.RETRIEVING_INTENTS
                        or intake.is_verbatim_span(decision.retrieval_query,
                                                   case["message"]))
            # The CSM's own reply (issue #21) is a SECOND span of the same message and is
            # guarded the same way -- not because it is embedded (it is not) but because it
            # is shown back to the CSM as what they wrote.
            reply_verbatim = (not decision.my_reply
                              or intake.is_verbatim_span(decision.my_reply, case["message"]))
            row = {
                "message": case["message"],
                "thread_turns": len(thread),
                "expect": case["expect"],
                "got": decision.intent,
                "correct": decision.intent == case["expect"],
                "retrieval_query": decision.retrieval_query,
                "my_reply": decision.my_reply,
                "my_reply_verbatim": reply_verbatim,
                "question": decision.question,
                "framing_leaked": leaked,
                "verbatim_span": verbatim,
                "meaning_dropped": dropped,
                "note": case["note"],
            }
            rows.append(row)
            mark = "ok  " if row["correct"] else "WRONG"
            print(f"  [{n}/{len(cases)}] {mark} expect={case['expect']:<15} "
                  f"got={decision.intent:<15} {case['message'][:55]!r}", flush=True)
            if leaked:
                print(f"          FRAMING LEAKED INTO THE QUERY: {leaked}", flush=True)
            if dropped:
                print(f"          MEANING-BEARING TEXT DROPPED: {dropped}", flush=True)
                print(f"          query was {decision.retrieval_query!r}", flush=True)

    Path(args.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print("\n" + "=" * 78)
    label = {"fitted": "FITTED cases (not an accuracy rate)",
             "heldout": "HELD-OUT cases",
             "threaded": "THREAD-SHAPED cases (issue #16)",
             "procedure": "PROCEDURE cases (issue #17)",
             "rendered": "RENDERED-INTENT cases (issues #19, #20)",
             "playbook": "PLAYBOOK-INTENT cases (issue #18)",
             "contrast": "CONTRAST cases (issue #21)",
             "both": "fitted + held-out"}[args.which]
    print(f"ROUTING ACCURACY -- {args.model} "
          f"(reasoning={args.reasoning or chr(110)+chr(111)+chr(110)+chr(101)}) -- {label}")
    print("=" * 78)

    overall = sum(r["correct"] for r in rows)
    print(f"  overall: {overall}/{len(rows)}")

    # Reported per class, never pooled. A pooled rate hides the failure that matters: an
    # intake biased toward clarify looks fine overall while making the tool ask questions
    # instead of answering.
    for label in ("reply_to_client", "clarify", "out_of_scope", "follow_up", "procedure",
                  "discovery", "frequency", "show_exchange", "what_happened_next",
                  "coverage_check", "sequence", "phrasing", "pitfalls", "scenario_check",
                  "play_confidence"):
        group = [r for r in rows if r["expect"] == label]
        if group:
            hit = sum(r["correct"] for r in group)
            print(f"  {label:<16} {hit}/{len(group)}")

    answerable = [r for r in rows if r["expect"] != "clarify"]
    over_clarified = [r for r in answerable if r["got"] == "clarify"]
    print(f"\n  NEGATIVE CASE -- messages that must NOT clarify: "
          f"{len(answerable) - len(over_clarified)}/{len(answerable)} held")
    if over_clarified:
        print("  Over-clarifying is the failure that makes the tool annoying rather than "
              "wrong; each of these asked a CSM a question when it could have answered:")
        for r in over_clarified:
            print(f"    - {r['message'][:70]!r}")

    # The second negative case, and the one that only exists once there is a conversation.
    # An intake that reads everything in a thread as a follow-up scores perfectly on the
    # positive cases while answering every new client situation from whatever call happened
    # to be cited last -- grounded, coherent, and about the wrong client.
    in_thread = [r for r in rows if r["thread_turns"]]
    if in_thread:
        not_follow_ups = [r for r in in_thread if r["expect"] != "follow_up"]
        over_followed = [r for r in not_follow_ups if r["got"] == "follow_up"]
        print(f"\n  NEGATIVE CASE -- messages in a thread that must NOT be read as "
              f"follow-ups: {len(not_follow_ups) - len(over_followed)}/"
              f"{len(not_follow_ups)} held")
        if over_followed:
            print("  Each of these would have been answered from the call cited earlier in "
                  "the conversation, without searching for anything:")
            for r in over_followed:
                print(f"    - {r['message'][:70]!r}")

    composed = [r for r in rows if not r["verbatim_span"]]
    print(f"\n  VERBATIM -- the query is a span COPIED from the message: "
          f"{len(rows) - len(composed)}/{len(rows)} clean")
    if composed:
        print("  A COMPOSED query is how subject inversion gets in: rewriting \"their side\"")
        print("  to \"our side\" is near-identical in embedding space and means the opposite,")
        print("  which is this corpus's most common failure shape. Each of these was written")
        print("  rather than copied:")
        for r in composed:
            print(f"    - {r['retrieval_query'][:64]!r}")
            print(f"      from {r['message'][:64]!r}")

    # Only meaningful where a reply was extracted at all, so it is reported over those rows
    # rather than over all of them -- a 34/34 that is really 0 cases checked reads as
    # evidence when it is silence.
    replies = [r for r in rows if r["my_reply"]]
    if replies:
        bad = [r for r in replies if not r["my_reply_verbatim"]]
        print(f"\n  THE CSM'S OWN REPLY is a span COPIED from the message: "
              f"{len(replies) - len(bad)}/{len(replies)} clean")
        if bad:
            print("  A COMPOSED reply puts words in the CSM's mouth on a page whose whole")
            print("  subject is what they wrote:")
            for r in bad:
                print(f"    - {r['my_reply'][:64]!r}")
                print(f"      from {r['message'][:64]!r}")

    lost = [r for r in rows if r["meaning_dropped"]]
    print(f"\n  MEANING PRESERVED -- no negation or subject dropped from the query: "
          f"{len(rows) - len(lost)}/{len(rows)} clean")
    if lost:
        print("  A copied span can still be the WRONG span. Each of these lost text")
        print("  that changes what is being asked:")
        for r in lost:
            print(f"    - dropped {r[chr(39)+chr(109)+chr(101)+chr(97)+chr(110)+chr(105)+chr(110)+chr(103)+chr(95)+chr(100)+chr(114)+chr(111)+chr(112)+chr(112)+chr(101)+chr(100)+chr(39)]} from {r[chr(39)+chr(109)+chr(101)+chr(115)+chr(115)+chr(97)+chr(103)+chr(101)+chr(39)][:56]!r}")

    leaks = [r for r in rows if r["framing_leaked"]]
    print(f"\n  FRAMING STRIPPED from the retrieval query: "
          f"{len(rows) - len(leaks)}/{len(rows)} clean")
    if leaks:
        print("  Framing left in the query is the exact thing intake exists to remove:")
        for r in leaks:
            print(f"    - {r['framing_leaked']} in {r['retrieval_query'][:60]!r}")

    print(f"\n  -> {args.out}")
    print("\nNOTE: this measures ROUTING, not answer quality. Whether better queries produce "
          "better answers is issue #9 and needs the blind read.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
