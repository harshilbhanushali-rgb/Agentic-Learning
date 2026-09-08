#!/usr/bin/env python3
"""Issue #14's gate: how often does INTAKE route a message correctly?

    python ask-naren/audit/measure_intake_accuracy.py                  # the fitted set
    python ask-naren/audit/measure_intake_accuracy.py --set heldout    # the real number
    python ask-naren/audit/measure_intake_accuracy.py --set threaded   # issue #16
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
                    choices=("fitted", "heldout", "threaded", "both"),
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
            "both": CASES + HELD_OUT}[args.which]
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
            verbatim = (decision.intent != "reply_to_client"
                        or intake.is_verbatim_span(decision.retrieval_query,
                                                   case["message"]))
            row = {
                "message": case["message"],
                "thread_turns": len(thread),
                "expect": case["expect"],
                "got": decision.intent,
                "correct": decision.intent == case["expect"],
                "retrieval_query": decision.retrieval_query,
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
             "both": "fitted + held-out"}[args.which]
    print(f"ROUTING ACCURACY -- {args.model} "
          f"(reasoning={args.reasoning or chr(110)+chr(111)+chr(110)+chr(101)}) -- {label}")
    print("=" * 78)

    overall = sum(r["correct"] for r in rows)
    print(f"  overall: {overall}/{len(rows)}")

    # Reported per class, never pooled. A pooled rate hides the failure that matters: an
    # intake biased toward clarify looks fine overall while making the tool ask questions
    # instead of answering.
    for label in ("reply_to_client", "clarify", "out_of_scope", "follow_up"):
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
