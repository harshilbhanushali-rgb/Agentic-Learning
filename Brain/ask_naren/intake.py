"""Intake: what happens to a CSM's message BEFORE anything is retrieved.

One model call decides three things -- which INTENT the message carries, what text should
actually be searched on, and whether to CLARIFY instead of answering. See
`ask-naren/CONTEXT.md` for all three terms; `intake` is deliberately not called "the read",
because a *read* in this project is a blind read.

WHY THIS EXISTS AT ALL, in one measurement. Ask Naren's accuracy was measured with a bare
verbatim client turn as the query, but a CSM RELAYS the client's words inside a request
frame -- "A client said this, can you help with..." -- and adding a frame changes which
exchange retrieval reaches for 81% of situations, collapsing the cosine range from 0.124 to
0.076 wide (`ask-naren/docs/findings/answer-failure-modes.md`). The frame is boilerplate
shared by every query, so it pulls all queries toward each other.

The finding's own recommendation was to stop guessing which span is the client's words and
ASK for them in a second input field. Intake does something strictly better for the CSM: it
extracts them when they are there, and asks only when they are not.

INTAKE IS AN OPTIMISATION, NOT A GATE. Everything here fails toward `reply_to_client` with
the raw message as the query -- which is exactly what the tool did before intake existed. A
model that returns rubbish twice, or a gateway that is down, must degrade to the working
tool rather than to an error. This is the single most important property in this module.

Nothing here retrieves, generates an answer, or touches Postgres.
"""
from __future__ import annotations

import re
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ask_naren import threads

# The licensed config, matching the answering path (ADR 0001 measured the MODEL as the lever
# on this corpus: gemini-3.5-flash-lite follows grounding instructions 11% of the time
# against 3.6-flash's 77%). Intake is a cheaper decision than answering, but a misrouted
# question wastes a whole generation, so it is not the place to save on model quality.
CHAT_MODEL = "gemini-3.6-flash"
TEMPERATURE = 0.0
MAX_TOKENS = 1024

# "low", and this is a REDUCTION, not an addition. Sending nothing does NOT mean "no
# reasoning": gemini-3.6-flash reasons heavily when left unconstrained -- measured at 6,042
# reasoning tokens across 10 messages against 342 at "low", cutting total usage 36% (15,847
# -> 10,185) with identical routing (10/10 both). Intake is a classification with a schema
# already constraining the shape, so an unbounded reasoning budget was paying for nothing.
# Full A/B, including flash-lite, in ask-naren/audit/measure_intake_accuracy.py.
REASONING_EFFORT = "low"

# One retry, matching answering.MAX_ATTEMPTS. A second unusable reply is not a transient
# blip worth a third call -- it means this message is not one the model can classify, and
# the fallback below is a working answer rather than a failure.
MAX_ATTEMPTS = 2

REPLY_TO_CLIENT = "reply_to_client"
CLARIFY = "clarify"
OUT_OF_SCOPE = "out_of_scope"
FOLLOW_UP = "follow_up"
PROCEDURE = "procedure"
DISCOVERY = "discovery"
FREQUENCY = "frequency"
SHOW_EXCHANGE = "show_exchange"
WHAT_HAPPENED_NEXT = "what_happened_next"
COVERAGE_CHECK = "coverage_check"
SEQUENCE = "sequence"
PHRASING = "phrasing"
PITFALLS = "pitfalls"
SCENARIO_CHECK = "scenario_check"
PLAY_CONFIDENCE = "play_confidence"
CONTRAST_MY_REPLY = "contrast_my_reply"
WHERE_ELSE_SEEN = "where_else_seen"
CALL_PREP = "call_prep"
IMPROVE_AT_MOVE = "improve_at_move"

#: Every intent intake may return today. Issues #17-#23 add more; each addition is a change
#: to the schema sent to the gateway AND to the prompt's discriminators, never one alone.
INTENTS = (REPLY_TO_CLIENT, CLARIFY, OUT_OF_SCOPE, FOLLOW_UP, PROCEDURE,
           DISCOVERY, FREQUENCY, SHOW_EXCHANGE, WHAT_HAPPENED_NEXT, COVERAGE_CHECK,
           SEQUENCE, PHRASING, PITFALLS, SCENARIO_CHECK, PLAY_CONFIDENCE,
           CONTRAST_MY_REPLY, WHERE_ELSE_SEEN, CALL_PREP, IMPROVE_AT_MOVE)

#: The intents answered from a scenario's LAYER C PLAYBOOK by rendering it (issue #18).
#: Grouped because one rule covers all five: the playbook already holds the answer, so
#: generating one would paraphrase a document that was itself generated offline and
#: verbatim-snapped -- adding an invention risk to replace text that is already there.
PLAYBOOK_INTENTS = (SEQUENCE, PHRASING, PITFALLS, SCENARIO_CHECK, PLAY_CONFIDENCE)

#: The intents that answer from STORED ROWS with no model call (issues #19, #20). They are
#: grouped here because two rules apply to all five and to nothing else: they need no
#: grounding gate (nothing is generated, so nothing can be invented), and `discovery` and
#: `frequency` need no retrieval either -- they are about the corpus rather than about a
#: situation.
RENDERED_INTENTS = (DISCOVERY, FREQUENCY, SHOW_EXCHANGE, WHAT_HAPPENED_NEXT, COVERAGE_CHECK,
                    SEQUENCE, PHRASING, PITFALLS, SCENARIO_CHECK, PLAY_CONFIDENCE,
                    WHERE_ELSE_SEEN, CALL_PREP, IMPROVE_AT_MOVE)

#: Of those, the two that describe the WHOLE corpus and therefore search for nothing.
CORPUS_INTENTS = (DISCOVERY, FREQUENCY)

#: Every intent whose `retrieval_query` IS EMBEDDED. ONE definition, with three consumers:
#: this module's `_usable` validator (which rejects a decision without one), the prompt's
#: rules block (which is what asks the model to produce one), and `responding._guarded`
#: (which enforces ADR 0006's rule that the embedded query is a span of THIS message).
#:
#: IT IS ONE CONSTANT BECAUSE THE THREE HAD ALREADY DRIFTED. At #18 ten intents embedded a
#: query: `_usable` listed all ten, the prompt's rules block listed three of them, and the
#: guard listed two -- so a playbook intent was required to carry a query the prompt never
#: asked for, and could reach the vector with text intake composed out of the thread. Each
#: list was correct when written and none was updated when #18 added five intents at once.
#: A shared tuple is what makes "add an intent" a single edit rather than four that must be
#: remembered together.
#:
#: COUNT IT FROM THE TUPLE, never from prose. The write-up of that very fix said "eight",
#: which was itself wrong, and `CONTEXT.md` then said "nine" -- two hand-maintained counts of
#: the thing whose hand-maintenance was the bug. Nothing in the code reads a number.
RETRIEVING_INTENTS = (REPLY_TO_CLIENT, PROCEDURE, SHOW_EXCHANGE, WHAT_HAPPENED_NEXT,
                      COVERAGE_CHECK, *PLAYBOOK_INTENTS, CONTRAST_MY_REPLY,
                      WHERE_ELSE_SEEN, CALL_PREP, IMPROVE_AT_MOVE)

#: The intents that may carry a conversation-aware `search_query` (issue #25): every one that
#: searches on a situation, plus a follow-up, which is searched when the exchange it carries
#: cannot answer it. NOT a contrast: it searches on the client's words quoted in this
#: message, and its own reply is set against exactly those.
REWRITABLE_INTENTS = tuple(i for i in RETRIEVING_INTENTS if i != CONTRAST_MY_REPLY) + (
    FOLLOW_UP,)

#: The kinds of ANCHOR an answer path can consume (`ask-naren/CONTEXT.md`). An exchange
#: implies its scenario; a scenario does not pick an exchange.
SCENARIO_ANCHOR = "scenario"
EXCHANGE_ANCHOR = "exchange"
NEIGHBOURHOOD_ANCHOR = "neighbourhood"
NO_ANCHOR = "none"
#: `follow_up` alone. It does consume an exchange, but finds it by its own measured rule --
#: the last ANSWERED turn's pair (`threads.carried_source`) -- and ADR 0013 deliberately
#: leaves it out of the anchor model until the new field is measured.
OWN_PATH = "own_path"
#: The anchors that are about ONE situation, and so the only ones a thread can supply.
ONE_SITUATION_ANCHORS = (SCENARIO_ANCHOR, EXCHANGE_ANCHOR)


class AnchorNeed(NamedTuple):
    """What one intent's answer path consumes, and whether it may ever take it from the
    thread."""
    kind: str
    #: Always searches fresh, even on a message intake judged to be on a carried situation.
    #: The two intents marked so always carry NEW client words, and answering those from an
    #: inherited scenario is the worst failure this tool has: grounded, coherent, and about
    #: the wrong client (ADR 0013 point 4).
    new_only: bool = False


#: EVERY INTENT DECLARES ITS ANCHOR, and a test fails when one is missing (issue #51). This
#: is what makes carrying a situation correct for intents that do not exist yet: the
#: resolution step reads this table rather than a list of intents, so adding an intent
#: means saying what its path consumes -- which is part of writing the path anyway -- and
#: nothing else needs editing. Same reason `RETRIEVING_INTENTS` is one constant.
ANCHORS: dict[str, AnchorNeed] = {
    SEQUENCE: AnchorNeed(SCENARIO_ANCHOR),
    PHRASING: AnchorNeed(SCENARIO_ANCHOR),
    PITFALLS: AnchorNeed(SCENARIO_ANCHOR),
    SCENARIO_CHECK: AnchorNeed(SCENARIO_ANCHOR),
    PLAY_CONFIDENCE: AnchorNeed(SCENARIO_ANCHOR),
    IMPROVE_AT_MOVE: AnchorNeed(SCENARIO_ANCHOR),
    PROCEDURE: AnchorNeed(SCENARIO_ANCHOR),
    SHOW_EXCHANGE: AnchorNeed(EXCHANGE_ANCHOR),
    WHAT_HAPPENED_NEXT: AnchorNeed(EXCHANGE_ANCHOR),
    COVERAGE_CHECK: AnchorNeed(EXCHANGE_ANCHOR),
    # Carrying a neighbourhood needs a vector-store query by the carried pair's id, which is
    # a separate capability with its own check. Until then these always search.
    WHERE_ELSE_SEEN: AnchorNeed(NEIGHBOURHOOD_ANCHOR),
    CALL_PREP: AnchorNeed(NEIGHBOURHOOD_ANCHOR),
    REPLY_TO_CLIENT: AnchorNeed(EXCHANGE_ANCHOR, new_only=True),
    CONTRAST_MY_REPLY: AnchorNeed(EXCHANGE_ANCHOR, new_only=True),
    DISCOVERY: AnchorNeed(NO_ANCHOR),
    FREQUENCY: AnchorNeed(NO_ANCHOR),
    CLARIFY: AnchorNeed(NO_ANCHOR),
    OUT_OF_SCOPE: AnchorNeed(NO_ANCHOR),
    FOLLOW_UP: AnchorNeed(OWN_PATH),
}


#: The two values of `IntakeDecision.situation` (`ask-naren/CONTEXT.md` **Carried
#: situation**). Which one a message is, is a judgement about the message; WHICH situation is
#: carried is never asked of the model -- it is whatever the last answer rested on.
CARRIED = "carried"
OPENS = "opens"


def may_carry(intent: str) -> bool:
    """Can this intent's anchor come from the thread rather than from a search?

    Only a scenario or one exchange can, and never on a new-only intent. Everything else
    treats a message on a carried situation exactly as one that opens a situation.
    """
    need = ANCHORS[intent]
    return need.kind in ONE_SITUATION_ANCHORS and not need.new_only


class IntakeDecision(BaseModel):
    """A validated intake decision -- the boundary between an untrusted model reply and the
    rest of the request path (ADR 0007).

    `extra="forbid"` is defence in depth rather than belt-and-braces. The gateway schema
    already forbids extra keys and that enforcement was MEASURED (ADR 0007), but enforcement
    is a property of a gateway deployment that can change underneath us. Validating here too
    means a silent regression there surfaces as an error instead of as a field nobody checks.
    """

    model_config = ConfigDict(extra="forbid", frozen=True,
                              json_schema_extra=lambda schema: _require(schema, "situation"))

    intent: Literal["reply_to_client", "clarify", "out_of_scope", "follow_up",
                    "procedure", "discovery", "frequency", "show_exchange",
                    "what_happened_next", "coverage_check", "sequence", "phrasing",
                    "pitfalls", "scenario_check", "play_confidence",
                    "contrast_my_reply", "where_else_seen", "call_prep",
                    "improve_at_move"]
    #: The CLIENT'S OWN WORDS, which is what gets embedded -- never the CSM's framing around
    #: them. Empty for any intent that does not retrieve.
    retrieval_query: str = ""
    #: What to put to the CSM when clarifying. Empty otherwise.
    question: str = ""
    #: THE CSM'S OWN REPLY, on a `contrast_my_reply` only (issue #21). Empty otherwise.
    #:
    #: A SECOND SPAN OF THE SAME MESSAGE, AND IT IS NEVER EMBEDDED. The client's words go to
    #: the vector as on every retrieving path; this goes to the PROMPT, as the thing Naren's
    #: real reply is set against. Adding it to the query would be exactly the dilution
    #: intake exists to strip (ADR 0006's mechanism), with the CSM's own wording as the
    #: shared boilerplate -- and it would search for what the CSM said rather than for what
    #: the client said, which is a different conversation.
    my_reply: str = ""
    #: Is this message ON A CARRIED SITUATION -- about the one the thread already established,
    #: naming none of its own -- or does it OPEN one (issue #53, ADR 0013)? REQUIRED in the
    #: gateway schema, so the model always says; defaulted here only so an absent value
    #: lands on `opens`, the behaviour every message had before this field existed.
    situation: Literal["carried", "opens"] = OPENS
    #: THE SEARCH WRITTEN FROM THE CONVERSATION (issue #25), when this message leans on what
    #: the CSM said earlier ("the ats one"). Empty when the message stands on its own, which
    #: means: search `retrieval_query` as before. Asked for only when the switch is on and
    #: there is a thread; `responding._guarded` checks every word was typed by the CSM. May
    #: sit on a CARRIED decision: it is searched only when there is nothing to carry.
    search_query: str = ""

    @model_validator(mode="before")
    @classmethod
    def _a_follow_up_searched_for_nothing(cls, data):
        """A follow-up and a corpus question run NO retrieval, so neither can carry a
        retrieval query.

        Cleared rather than rejected: a model that helpfully fills the field is not making
        an unusable decision, it is making a misleading one. Every response echoes
        `retrieval_query` so a bad extraction is visible in production
        (`responding._echo_intake`), and on this path echoing a query that was never
        embedded would report a search that did not happen.
        """
        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        intent = cleaned.get("intent")
        if intent in (FOLLOW_UP, *CORPUS_INTENTS):
            cleaned["retrieval_query"] = ""

        # WHAT "CARRIED" MEANS DEPENDS ON THE INTENT (issue #53), and is settled here so
        # everything downstream -- the guard, the paths, the echo -- reads one answer.
        #   * a follow-up is ALWAYS on a carried situation: that is what it is;
        #   * an intent that cannot carry (new-only, neighbourhood, none) treats it as
        #     opening one, and KEEPS its query, because that query is what it searches on;
        #   * a carried decision on an intent that can carry searches for nothing, so its
        #     query is cleared for the same reason a follow-up's is.
        # Only the literal "carried" is coerced, so an unknown value still reaches the
        # Literal and is refused there.
        if intent == FOLLOW_UP:
            cleaned["situation"] = CARRIED
        elif cleaned.get("situation") == CARRIED and not (intent in ANCHORS
                                                          and may_carry(intent)):
            cleaned["situation"] = OPENS
        if cleaned.get("situation") == CARRIED:
            cleaned["retrieval_query"] = ""
        # SAME RULE, SECOND FIELD (issue #21). Only a contrast shows the CSM's own reply
        # back, so a `my_reply` on any other intent describes a comparison that never ran --
        # misleading rather than unusable, which is why it is cleared and not rejected.
        if cleaned.get("intent") != CONTRAST_MY_REPLY:
            cleaned["my_reply"] = ""
        # SAME RULE, THIRD FIELD (issue #25). A search on a message that searches nothing
        # would be echoed as a search that never ran. KEPT ON A CARRIED MESSAGE: whether it
        # is used is `responding`'s call -- carrying wins when there is an anchor, and the
        # search is what runs when there is none, or when the exchange a follow-up carries
        # cannot answer it. Live, intake calls "the ats one" carried.
        if intent not in REWRITABLE_INTENTS:
            cleaned["search_query"] = ""
        return cleaned

    @field_validator("retrieval_query", "question", "my_reply", "search_query")
    @classmethod
    def _stripped(cls, v: str) -> str:
        return (v or "").strip()

    @model_validator(mode="after")
    def _usable(self) -> "IntakeDecision":
        """Rejects decisions that parse but cannot be acted on.

        A clarify with no question shows a CSM nothing to answer, and an answering decision
        with no query would embed an empty string and retrieve noise. Both are shape-valid
        and useless, which is precisely the class of thing a schema cannot catch.
        """
        if self.intent == CLARIFY and not self.question:
            raise ValueError("a clarify with no question is a dead end, not a clarify")
        # A CARRIED decision embeds nothing -- its anchor comes from the thread -- so only a
        # decision that opens a situation needs something to search on.
        if (self.intent in RETRIEVING_INTENTS and self.situation == OPENS
                and not self.retrieval_query):
            raise ValueError(f"{self.intent} with no retrieval_query would embed nothing")
        if self.intent == CONTRAST_MY_REPLY and not self.my_reply:
            raise ValueError("a contrast with no reply to contrast has nothing to compare")
        return self


def response_schema(rewrite: bool = False) -> dict:
    """The JSON Schema sent to the gateway, derived from the model so the two cannot drift.

    Pydantic emits `additionalProperties: false` from `extra="forbid"` and the enum from the
    Literal, so adding an intent to IntakeDecision updates what the gateway will accept
    without a second edit here.

    `search_query` is offered only when `rewrite` is on (issue #25), so with the switch off
    the gateway is sent the schema intake's accuracy was measured on.
    """
    schema = IntakeDecision.model_json_schema()
    if not rewrite:
        schema["properties"].pop("search_query", None)
    return {"name": "intake_decision", "strict": True, "schema": schema}


def _require(schema: dict, field: str) -> None:
    """Mark `field` required in the gateway schema while the model keeps a default.

    The model must always SAY whether a message carries a situation, so the schema requires
    it. The validated decision still defaults it, so a decision built in code -- the
    fallback, a test -- means "opens" without spelling it out.
    """
    required = schema.setdefault("required", [])
    if field not in required:
        required.append(field)


def build_prompt(message: str, thread=(), rewrite: bool = False) -> str:
    """Intake's prompt. NOT frozen -- unlike the answering prompts (ADR 0001), no measured
    number rests on its wording, and routing accuracy is measured against labelled messages
    rather than asserted in a test. Improve it, then re-measure.

    The discriminators are spelled out because a classifier fails on near neighbours, not on
    distant ones.

    `thread` is the conversation so far (issue #16). It is shown so intake can do the three
    things it cannot do without it -- tell a follow-up from a new situation, recognise a
    message as the answer to its own earlier clarify, and avoid asking a question twice.

    *** THE PROMPT IS NO LONGER THE ONE #14's ROUTING ACCURACY WAS MEASURED ON. *** Through
    #16 an empty thread still produced that exact text, and this docstring said so. Issue
    #17 added the `procedure` intent and its discriminator to the UNCONDITIONAL section --
    correctly, because a CSM can ask for the general play with or without a conversation --
    which means every message, first or not, is now classified by a different prompt.

    That is a real change to the one step whose accuracy is on record, so it was re-measured
    rather than assumed: see `ask-naren/audit/measure_intake_accuracy.py`, which now carries
    `procedure` cases and the negative cases that must NOT route to it. Do not restore the
    old claim without re-running that harness.
    """
    history = []
    if thread:
        history = [
            "The conversation so far, oldest first:",
            "",
            threads.render(thread),
            "",
        ]

    return "\n".join([
        'You are the intake step of "Ask Naren", an internal Joveo tool that answers a CSM '
        "by finding what Naren said in the closest real client situation from his call "
        "transcripts.",
        "",
        "Decide what should happen to this message from a CSM.",
        "",
        *history,
        f"CSM's message: {message}",
        "",
        "Choose ONE intent:",
        "",
        f'  "{REPLY_TO_CLIENT}" -- the message contains what a client actually SAID, so we '
        "can search Naren's calls for the closest matching moment. Usually the client's "
        "words relayed inside a request like \"a client said this, how would Naren reply\".",
        "",
        f'  "{CLARIFY}" -- the message names a topic or a mood and gives NOTHING CONCRETE to '
        "search on (\"client is unhappy about pricing\", \"they are frustrated with "
        "performance\"). Searching on a bare summary reaches a different part of the corpus "
        "than searching on what was really said, so ask for the client's actual words.",
        "    A GREETING OR AN OPENER WITH NO QUESTION IN IT (\"hey\", \"hi\", \"you "
        "there?\") is also this. It names no situation and asks nothing, so there is "
        f'nothing to search AND nothing being asked about the tool -- it is not "{DISCOVERY}".',
        "",
        f'  "{PROCEDURE}" -- the CSM wants the GENERAL PLAY for a kind of situation, not a '
        "reply to one thing a client said. They are preparing rather than reacting: \"how "
        "do we usually handle renewals that stall\", \"what's the play when spend "
        "overruns\", \"how should i approach a QBR where performance is down\". No client "
        "is quoted and none needs to be.",
        f"    A PLAY IS LOOKED UP BY THE KIND OF SITUATION, so the message has to name one. "
        f'"difficult clients", "tricky accounts", "when things get tense" name a MOOD, not '
        f'a situation -- those are "{CLARIFY}". Ask which kind of situation they mean.',
        "",
        f'  "{CALL_PREP}" -- the CSM has a CALL COMING UP and wants to walk in ready: "im '
        "on a renewal call with them tomorrow, what should i be ready for\", \"prepping for "
        "a QBR where spend overran, where do i start\", \"walk me through what usually "
        "comes up on an onboarding kickoff\". They want the LIKELY GROUND rather than one "
        "answer -- what tends to come up, the play for each, and something real to read.",
        "",
        f'  "{SHOW_EXCHANGE}" -- the CSM wants to SEE the real exchange rather than a '
        "summary of it: \"show me what he actually said\", \"can i see the real "
        "conversation\", \"what were his exact words about renewals\".",
        "",
        f'  "{WHAT_HAPPENED_NEXT}" -- the CSM wants to know how that conversation CONTINUED '
        "after the moment: \"what did the client say back\", \"how did that call go on\", "
        "\"what came after that\".",
        "",
        f'  "{COVERAGE_CHECK}" -- the CSM is asking whether Ask Naren KNOWS ANYTHING about a '
        "kind of situation, rather than asking it to answer one: \"do you have anything on "
        "renewals\", \"is there coverage for pricing escalations\", \"would you know about "
        "this\".",
        "",
        f'  "{DISCOVERY}" -- the CSM wants to know what Ask Naren covers OVERALL, with no '
        "particular situation in mind: \"what can i ask you\", \"what topics do you know "
        "about\", \"what do you cover\".",
        "",
        f'  "{FREQUENCY}" -- the CSM wants to know which situations come up MOST, again '
        "across everything rather than about one case: \"what comes up most with clients\", "
        "\"which situations are most common\", \"what should i learn first\".",
        "",
        f'  "{WHERE_ELSE_SEEN}" -- the CSM wants to know WHICH OTHER ACCOUNTS a situation '
        "has come up with, so they can tell a one-client quirk from a pattern: \"which "
        "other clients have raised this\", \"is this just them or does everyone ask\", "
        "\"have we seen this anywhere else\", \"how common is this across the book\".",
        "",
        f'  "{SEQUENCE}" -- the CSM wants to know WHAT ORDER to do things in: "what do i '
        "do first\", \"what order should i run these in\", \"where do i start with this\".",
        "",
        f'  "{PHRASING}" -- the CSM wants THE WORDING NAREN HIMSELF USES: "how does he '
        "say it\", \"how does naren word that\", \"what language does he use for pushback\".",
        "",
        f'  "{PITFALLS}" -- the CSM wants to know WHAT GOES WRONG: "what usually goes wrong '
        "here\", \"what mistakes do people make\", \"what should i avoid\".",
        "",
        f'  "{IMPROVE_AT_MOVE}" -- the CSM wants to GET BETTER at one specific thing they '
        "already do: \"i keep fumbling the part where i reframe on their own baseline\", "
        "\"how do i get sharper at pushing back on a benchmark comparison\", \"what should "
        "i practise about setting expectations on timelines\". They are working on "
        "THEMSELVES rather than handling a live client.",
        "",
        f'  "{SCENARIO_CHECK}" -- the CSM wants to know whether a play APPLIES to what they '
        "are seeing: \"does this play apply here\", \"is this that kind of situation\", "
        "\"am i in the right playbook\".",
        "",
        f'  "{PLAY_CONFIDENCE}" -- the CSM wants to know HOW WELL EVIDENCED a play is: "how '
        "solid is this\", \"how many calls is this based on\", \"how much should i trust "
        "this\".",
        "",
        f'  "{CONTRAST_MY_REPLY}" -- the CSM HAS ALREADY REPLIED to the client and wants '
        "their own reply set against Naren's: \"i told them we'd review the settings this "
        "week, is that how naren would have handled it\", \"i said we'd get back to them "
        "friday -- would he have said something different\", \"here's what i sent, how "
        "does that compare\". The message contains BOTH the client's words AND the CSM's "
        "own reply to them.",
        "",
        f'  "{OUT_OF_SCOPE}" -- THE CSM is asking YOU for an internal fact about Joveo: a '
        "list price, a contract term, which integrations exist, what a policy says. Naren's "
        "call transcripts are not a product document. Do NOT clarify these; there is nothing "
        "the CSM could reword that would make them answerable.",
        "",
        *_follow_up_intent(thread),
        "Rules:",
        f'  - For "{REPLY_TO_CLIENT}", set retrieval_query to a VERBATIM SPAN COPIED from '
        "the message -- the client's own words with the CSM's framing removed (\"a client "
        "said\", \"how would Naren reply\", \"can you help\", \"what do i say\"). That "
        "framing is boilerplate shared by every question and it degrades the search.",
        "    COPY, DO NOT REPHRASE. Do not tidy the grammar, do not turn a statement into a "
        "question, and above all DO NOT CHANGE WHO IS BEING TALKED ABOUT. Swapping "
        "\"their side\" for \"our side\", or \"you\" for \"we\", produces text that is "
        "nearly identical to the original in search terms and means the opposite -- which "
        "is the single most common way this tool retrieves the wrong exchange. If the "
        "client's content is spread across the message, copy the longest run that carries "
        "it rather than composing a new sentence.",
        f'  - For "{CLARIFY}", set question to one short, specific thing to ask the CSM -- '
        "normally asking them to paste what the client actually said or wrote.",
        f'  - For "{OUT_OF_SCOPE}", "{DISCOVERY}" and "{FREQUENCY}"'
        + (f' and "{FOLLOW_UP}"' if thread else "")
        + ", leave retrieval_query and question empty.",
        f'  - For "{SHOW_EXCHANGE}", "{WHAT_HAPPENED_NEXT}" and "{COVERAGE_CHECK}", set '
        "retrieval_query to the SITUATION being asked about, copied from the message with "
        "the asking-framing removed. It is used to find which exchange they mean.",
        *(["  - The retrieval_query must be copied from the CSM's CURRENT message only. "
           "Never from the conversation above. Text repeated across several questions makes "
           "them all look alike to the search and reaches the wrong exchange."]
          if thread else []),
        "",
        f'  - For "{CALL_PREP}" and "{IMPROVE_AT_MOVE}", set retrieval_query to the SITUATION '
        "or the MOVE they named, copied from the message with the framing removed (\"im on "
        "a call tomorrow about\", \"i keep fumbling\", \"how do i get sharper at\"). It is "
        "used to find which kind of situation they mean.",
        "    COPY ONE CONTINUOUS RUN OF THE MESSAGE. These questions often mention the "
        "account, the timing and the topic in one sentence, and stitching the useful words "
        "together from different parts of it produces text that is in the message nowhere. "
        "Take the LONGEST UNBROKEN RUN that carries the situation, even if it drags along a "
        "word or two you would rather drop.",
        "",
        f'  - For "{WHERE_ELSE_SEEN}", set retrieval_query to the SITUATION being asked '
        "about, copied from the message with the asking-framing removed (\"which other "
        "clients\", \"have we seen this anywhere else\"). It is used to find the "
        "neighbouring exchanges whose accounts get listed.",
        "",
        f'  - For "{PROCEDURE}", set retrieval_query to the SITUATION the CSM is asking '
        "about, copied from their message with the asking-framing removed (\"what's the "
        "play when\", \"how do we usually handle\", \"how should i approach\"). It is used "
        "to find which kind of situation they mean.",
        "",
        f'  - For "{SEQUENCE}", "{PHRASING}", "{PITFALLS}", "{SCENARIO_CHECK}" and '
        f'"{PLAY_CONFIDENCE}", do the same: set retrieval_query to the SITUATION the play is '
        "about, copied from the message. All five ask about a play, and the play is found by "
        "searching for the situation it belongs to.",
        "    If the message names no situation at all -- \"what do i do first\", \"what "
        f'usually goes wrong\" with nothing after it -- choose "{CLARIFY}" and ask which '
        "kind of situation they mean, rather than composing a situation out of the "
        "conversation above.",
        "",
        f'  - For "{CONTRAST_MY_REPLY}", set BOTH: retrieval_query to the CLIENT\'S words '
        "(that is what gets searched -- we are looking for the moment Naren faced the same "
        "thing), and my_reply to the CSM'S OWN reply, both copied verbatim from the "
        "message. Do NOT put the CSM's reply in retrieval_query; searching on it would look "
        "for the wrong side of the conversation.",
        "",
        "Two distinctions that are easy to get wrong:",
        "",
        f'  - ABOUT ONE SITUATION or ABOUT THE WHOLE CORPUS separates "{COVERAGE_CHECK}" '
        f'from "{DISCOVERY}". "Do you have anything on renewals" names a situation and is '
        f'"{COVERAGE_CHECK}"; "what topics do you cover" names none and is "{DISCOVERY}".',
        "",
        f'  - WANTING HIS WORDS vs WANTING AN ANSWER separates "{SHOW_EXCHANGE}" from '
        f'"{REPLY_TO_CLIENT}". Asking to SEE the exchange is "{SHOW_EXCHANGE}"; asking what '
        f'to say is "{REPLY_TO_CLIENT}", even when a client is quoted in both.',
        "",
        f'  - A SPECIFIC MEETING THEY ARE ABOUT TO BE IN separates "{CALL_PREP}" from '
        f'"{PROCEDURE}". Both are preparing rather than reacting. "{PROCEDURE}" asks for the '
        f'play for ONE kind of situation; "{CALL_PREP}" is about an upcoming meeting and '
        "wants the several things likely to come up in it.",
        f'    WHAT MAKES IT "{CALL_PREP}" is something pinning the meeting to a real '
        "occasion: a time (\"tomorrow\", \"thursday\", \"next week\"), a named account, or "
        "a possessive (\"my\", \"our\"). Naming a kind of meeting in general, with no "
        "particular one coming up, is not enough on its own.",
        "",
        f'  - WORKING ON THEMSELVES separates "{IMPROVE_AT_MOVE}" from "{PHRASING}" and '
        f'"{PITFALLS}". "How does naren word it" wants HIS language; "what usually goes '
        "wrong\" wants the failure modes; \"i keep fumbling this bit, help me get better\" "
        f'wants both plus the criterion, aimed at their own practice -- that is '
        f'"{IMPROVE_AT_MOVE}". Look for the CSM naming their own weakness.',
        "",
        f'  - WHO ELSE vs WHAT IS COVERED separates "{WHERE_ELSE_SEEN}" from '
        f'"{COVERAGE_CHECK}". "Do you have anything on renewals" asks whether Ask Naren '
        f'KNOWS the topic and is "{COVERAGE_CHECK}"; "which other clients have raised '
        f'renewals" asks WHICH ACCOUNTS it came up with and is "{WHERE_ELSE_SEEN}". Asking '
        f'how OFTEN across the whole corpus with no situation named is "{FREQUENCY}".',
        "",
        f'  - A SPECIFIC CLIENT UTTERANCE is what separates "{REPLY_TO_CLIENT}" from '
        f'"{PROCEDURE}". "Client said our CPA is 3x, what do i say" quotes a client and is '
        f'"{REPLY_TO_CLIENT}". "How do we usually handle CPA complaints" quotes nobody and '
        f'is "{PROCEDURE}". Reported speech still counts as a client utterance; a '
        "hypothetical does not.",
        "",
        "  - A CLIENT asking about Joveo's product is still "
        f'"{REPLY_TO_CLIENT}", not "{OUT_OF_SCOPE}". "Do you guys use WhatsApp for '
        "outreach?\" is a client turn Naren has faced and answered. Only route to "
        f'"{OUT_OF_SCOPE}" when the CSM is asking YOU for the fact, with no client in the '
        "picture.",
        "",
        f'  - HAS THE CSM ALREADY REPLIED separates "{CONTRAST_MY_REPLY}" from '
        f'"{REPLY_TO_CLIENT}". "Client said X, what do i say" wants an answer and is '
        f'"{REPLY_TO_CLIENT}". "Client said X, i told them Y, is that right" already has '
        f'an answer and wants it compared -- that is "{CONTRAST_MY_REPLY}". A message that '
        "describes what the CSM PLANS to say (\"i was going to tell them...\") counts as "
        "already replied: it is a draft to compare, not a question to answer.",
        "",
        f'  - A CSM asking how they DID is still "{CONTRAST_MY_REPLY}", not a request for a '
        "grade. We show what Naren did in the closest real moment and let them compare. "
        "Route it here whether they ask \"was that right\" or \"how does that compare\".",
        "",
        "  - Reported speech counts. \"Client is asking why their spend went up 40% in "
        "March\" is not a quote, but it carries a specific claim that can be searched. "
        f'That is "{REPLY_TO_CLIENT}". Reserve "{CLARIFY}" for messages with no specifics '
        "at all.",
        "",
        *_thread_rules(thread),
        *(_search_rules() if rewrite and thread else []),
        f'When genuinely torn, prefer "{REPLY_TO_CLIENT}". Answering and being slightly off '
        "is more useful to a CSM mid-call than being asked for something they thought they "
        "had already given.",
    ])


def _follow_up_intent(thread) -> list[str]:
    """The follow-up option, offered ONLY when there is a conversation to follow up on.

    MEASURED, not assumed. The first version of this prompt listed the intent always and
    told the model it was "only available when there is a conversation above" -- and on the
    thread-shaped set, "and what if they push back on price?" with NO conversation was
    routed `follow_up` anyway (2026-09-08, 10/11). A rule stating that an option does not
    apply is weaker than not offering the option, and this is the cheap version of the
    lesson ADR 0001 paid for: the model is the lever, and what you put in front of it
    decides more than what you tell it about what you put in front of it.

    It also means a FIRST message is classified by exactly the intent list that shipped in
    #14, so the routing accuracy on record still describes the text it was measured on.

    Nothing was broken in production by the misroute -- `responding._guarded` turns a
    follow-up with no carried source into an ordinary answer -- but it would have burned the
    fallback on a case that should never have reached it.
    """
    if not thread:
        return []
    return [
        f'  "{FOLLOW_UP}" -- the message only means anything against the answer just given '
        "(\"and if they push back on price?\", \"what if that does not land?\", \"why does "
        "he say it that way?\"). It goes DEEPER on the exchange already answered from and "
        "describes no new client situation, so there is nothing new to search for.",
        "",
    ]


def _thread_rules(thread) -> list[str]:
    """The rules that only exist when there IS a conversation.

    Kept out of the prompt entirely for a first message, so a single-message classification
    is the exact text #14's routing accuracy was measured on rather than that text plus four
    paragraphs about a conversation that does not exist.
    """
    if not thread:
        return []
    return [
        "Using the conversation above:",
        "",
        f'  - A NEW CLIENT SITUATION IS NOT A "{FOLLOW_UP}", even in the same conversation. '
        "A CSM may move to a completely different client or problem without saying so. If "
        "the message describes something a client said or did that is not what was already "
        f'answered, it is "{REPLY_TO_CLIENT}" and gets its own search.',
        "",
        "  - If Ask Naren's last turn ASKED THE CSM A QUESTION, this message is their "
        "answer to it. Treat it as completing the earlier question rather than as a brand "
        f'new one: route "{REPLY_TO_CLIENT}" and copy the client\'s words out of THIS '
        "message.",
        "",
        f'  - NEVER ask a question that already appears above. If the message still does '
        "not give you what you asked for, answer it as best you can with what is there "
        "rather than asking again.",
        "",
        f'  - Set situation to "{CARRIED}" when the message is about the situation the '
        "conversation above already established and describes none of its own: \"what's "
        "the play here\", \"how does he word it\", \"what usually goes wrong\", \"how sure "
        "is that play\", \"show me the actual exchange\", \"what happened after that\". "
        f'Set it to "{OPENS}" when the message describes a situation itself.',
        f'    ANY NEW CLIENT WORDS MAKE IT "{OPENS}", however much the message sounds like a '
        "continuation (\"now they say the budget is frozen\", \"different client: they "
        "think our CPA is too high\"). Answering new client words from the situation above "
        "is answering about the wrong client.",
        f'    For "{CARRIED}", choose the intent the message asks for and leave '
        "retrieval_query empty: what it is about comes from the conversation, not from a "
        f'search. Do not "{CLARIFY}" to ask which situation they mean -- the conversation '
        f'above already says. A "{FOLLOW_UP}" is always "{CARRIED}".',
        "",
    ]


def _search_rules() -> list[str]:
    """How to write `search_query` (issue #25). Only when the switch is on AND there is a
    conversation, so a first message -- and every message with the switch off -- is
    classified by exactly the text that was measured.

    retrieval_query keeps its meaning (copied from THIS message); this is a second field
    rather than a loosened first one, so the copy rule and its guard are untouched.
    """
    return [
        "  - search_query is the search this message needs, written so it would make sense "
        "with no conversation around it.",
        "    FILL IT ONLY WHEN THIS MESSAGE LEANS ON SOMETHING THE CSM SAID EARLIER and is "
        "too vague to search on alone (\"the second one\", \"ok but what if they blame the "
        "vendor for it\", \"anyone else run into that\"). Then write the "
        "situation by joining the specific words of this message with the specific words "
        "the CSM typed in earlier messages.",
        "    USE ONLY WORDS THE CSM TYPED. Never take words from Ask Naren's replies, never "
        "add words of your own, and do not change who is being talked about (\"their\" "
        "stays \"their\").",
        "    LEAVE IT EMPTY when the message already says what it is about, or when it "
        "brings up a new client or a new problem (search on its own words, never on the "
        "earlier client's).",
        "    WRITING IT CHANGES NOTHING ELSE. Choose the intent and situation exactly as the "
        "rules above say, as if this field did not exist; then, separately, write "
        f'search_query for any message that leans on earlier words -- a "{FOLLOW_UP}" '
        "included. Whether it is used is decided after you.",
        "",
    ]


async def classify(message: str, gateway, *, thread=(), model: str = CHAT_MODEL,
             reasoning_effort: str | None = REASONING_EFFORT,
             rewrite: bool = False) -> tuple[IntakeDecision, dict]:
    """Decide what happens to `message`. Returns (decision, meta).

    `thread` is the conversation so far (issues #15, #16). It is shown to the model for the
    three judgements it cannot make without it: is this a follow-up, is it the answer to a
    clarify already asked, and has this question been asked before. The FOURTH history job
    -- which grounding source a follow-up inherits -- is deliberately NOT asked of the model
    (`threads.carried_source`): it is a lookup with one right answer, and a model that can
    invent a `pair_id` is a model that can ground an answer in a row that does not exist.

    An EMPTY thread produces byte-identically the prompt that shipped in #14, so a first
    message is still classified by the text the recorded routing accuracy was measured on.

    `model` and `reasoning_effort` exist so a cheaper configuration can be A/B'd on the same
    labelled cases (`ask-naren/audit/measure_intake_accuracy.py --model ... --reasoning ...`)
    rather than swapped in on the assumption that classification is easy. Both default to the
    shipped values, so production does not move until a measurement says it should.

    `reasoning_effort=None` sends no reasoning budget at all, which is how intake shipped
    first and what the flash-lite A/B was originally run at.

    `rewrite` is issue #25's switch: ask for a conversation-aware `search_query` too. Off,
    the prompt and schema are exactly what they were, and a stray one is dropped.

    NEVER RAISES for a model or gateway problem. Two unusable replies, a malformed reply, or
    a gateway that is down all fall through to answering the message as written -- the
    behaviour the tool had before intake existed. Intake improves the query; it must not be
    able to take the tool down.
    """
    if not (message or "").strip():
        raise ValueError("message is empty")

    meta: dict = {}
    for _ in range(MAX_ATTEMPTS):
        try:
            payload, meta = await gateway.chat_json(
                build_prompt(message, thread, rewrite=rewrite),
                model=model,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                schema=response_schema(rewrite=rewrite and bool(thread)),
                reasoning_effort=reasoning_effort,
                # Same reason as the answering path: two CSMs asking similar questions must
                # never be served each other's decision.
                no_cache=True,
            )
            if not thread and isinstance(payload, dict):
                # A FIRST MESSAGE OPENS ITS SITUATION, whatever the model said (ADR 0013
                # point 5) -- there is nothing above it to carry. Forced BEFORE validation,
                # so the query the model also copied survives rather than being cleared.
                payload = {**payload, "situation": OPENS}
            if not (rewrite and thread) and isinstance(payload, dict):
                payload = {k: v for k, v in payload.items() if k != "search_query"}
            if _carried_with_nothing_to_search(payload):
                # The prompt says to leave the query empty when carried; on an intent that
                # always searches, that leaves nothing to search on. Not a malformed reply
                # worth a second model call -- the existing fallback, at once (ADR 0013) --
                # unless the model wrote a search from the conversation (issue #25), which
                # is exactly what "where else has this come up" needs to be searched on.
                if not str(payload.get("search_query") or "").strip():
                    return fallback_decision(message), meta
                payload = {**payload, "situation": OPENS,
                           "retrieval_query": message.strip()}
            return IntakeDecision.model_validate(payload), meta
        except Exception:                       # noqa: BLE001 -- see the docstring
            continue

    return fallback_decision(message), meta


def _carried_with_nothing_to_search(payload) -> bool:
    """A carried reply on an intent that cannot carry (new-only or neighbourhood), with no
    query of its own. It is read as opening a situation, and has nothing to open it with."""
    if not isinstance(payload, dict) or payload.get("situation") != CARRIED:
        return False
    intent = payload.get("intent")
    return (intent in RETRIEVING_INTENTS and not may_carry(intent)
            and not str(payload.get("retrieval_query") or "").strip())


def is_verbatim_span(query: str, message: str) -> bool:
    """Is `query` genuinely COPIED out of `message`, rather than composed?

    ADR 0006 IS THE REASON THIS IS A FUNCTION AND NOT A PROMPT LINE. Since #16 intake is
    shown the thread, and the thread contains previous answers -- so a model that composes
    instead of copying can now assemble a query out of HISTORY, which is precisely the one
    thing the ADR forbids reaching the embedded query. The prompt asks for a copied span;
    asking is not enforcing, and `measure_intake_accuracy.py` has already caught this model
    composing rather than copying, once with a perspective flip that inverts meaning.

    ONE DEFINITION, shared with that harness, so the offline instrument and the runtime
    guard cannot come to disagree about what "copied" means.

    Case-, whitespace- and quote-insensitive: lifting a span out of quotation marks or
    normalising spacing is still copying. Nothing looser -- no stemming, no fuzzy ratio --
    because the failure being caught is a near-identical rewrite, and a fuzzy bar would
    admit exactly that.
    """
    return _normalize(query) in _normalize(message)


#: Joining words a search written from several turns needs and that carry no meaning a
#: search could flip. NO PRONOUNS: "our" for "their" is the flip `is_verbatim_span` exists
#: to catch, so a pronoun must have been typed by the CSM like any other word.
_JOINING_WORDS = frozenset(
    "a an the and or of to in on for with about after before at by from as is are was "
    "were".split())


def uses_only_csm_words(search: str, message: str, turns) -> bool:
    """Is every word of `search` one the CSM typed -- now or earlier in the thread (#25)?

    THE CHECK THAT MAKES A CONVERSATION-AWARE SEARCH CHECKABLE. ADR 0006 refused to let a
    rewrite reach the vector because a bad one is invisible; this is what a rewrite has to
    pass before it is searched on, and the plain words are searched instead if it fails.

    ONLY THE CSM'S OWN MESSAGES COUNT, never Ask Naren's replies. Those are paraphrases of
    the exchange already shown, and searching on them reaches that exchange again -- the
    shared-text pull ADR 0006 measured.

    Word by word rather than a span, because the point of a rewrite is to join words from
    different turns ("the ats one" + what the CSM said two turns ago). Exact words, no
    stemming, for the same reason `is_verbatim_span` takes no fuzzy ratio.
    """
    typed = set(_words(message))
    for turn in turns:
        typed.update(_words(turn.message))
    words = _words(search)
    return bool(words) and all(w in typed or w in _JOINING_WORDS for w in words)


def _words(text: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower().replace("'", "").replace("’", ""))


def _normalize(text: str) -> str:
    cleaned = "".join(c for c in (text or "") if c not in "“”\"‘’'")
    return " ".join(cleaned.split()).lower()


def fallback_decision(message: str) -> IntakeDecision:
    """Answer the message as written -- exactly what the tool did before intake existed.

    PUBLIC, and there is ONE definition on purpose. This is the behaviour the module
    docstring calls its single most important property, and `responding.respond` needs it too
    for the case where `classify` itself raises. Two copies of a safety fallback is two places
    for it to stop agreeing about what "degrade gracefully" means.
    """
    return IntakeDecision(intent=REPLY_TO_CLIENT, retrieval_query=message.strip())
