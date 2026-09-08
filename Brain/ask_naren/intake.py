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

from typing import Literal

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

#: Every intent intake may return today. Issues #17-#23 add more; each addition is a change
#: to the schema sent to the gateway AND to the prompt's discriminators, never one alone.
INTENTS = (REPLY_TO_CLIENT, CLARIFY, OUT_OF_SCOPE, FOLLOW_UP, PROCEDURE,
           DISCOVERY, FREQUENCY, SHOW_EXCHANGE, WHAT_HAPPENED_NEXT, COVERAGE_CHECK,
           SEQUENCE, PHRASING, PITFALLS, SCENARIO_CHECK, PLAY_CONFIDENCE)

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
                    SEQUENCE, PHRASING, PITFALLS, SCENARIO_CHECK, PLAY_CONFIDENCE)

#: Of those, the two that describe the WHOLE corpus and therefore search for nothing.
CORPUS_INTENTS = (DISCOVERY, FREQUENCY)

#: Every intent whose `retrieval_query` IS EMBEDDED. ONE definition, with three consumers:
#: this module's `_usable` validator (which rejects a decision without one), the prompt's
#: rules block (which is what asks the model to produce one), and `responding._guarded`
#: (which enforces ADR 0006's rule that the embedded query is a span of THIS message).
#:
#: IT IS ONE CONSTANT BECAUSE THE THREE HAD ALREADY DRIFTED. `_usable` listed all eight,
#: the rules block listed three of them, and the guard listed two -- so a playbook intent
#: was required to carry a query the prompt never asked for, and could reach the vector with
#: text intake composed out of the thread. Each was correct when written and none was
#: updated when #18 added five intents at once; a shared tuple is what makes "add an intent"
#: a single edit rather than four that must be remembered together.
RETRIEVING_INTENTS = (REPLY_TO_CLIENT, PROCEDURE, SHOW_EXCHANGE, WHAT_HAPPENED_NEXT,
                      COVERAGE_CHECK, *PLAYBOOK_INTENTS)


class IntakeDecision(BaseModel):
    """A validated intake decision -- the boundary between an untrusted model reply and the
    rest of the request path (ADR 0007).

    `extra="forbid"` is defence in depth rather than belt-and-braces. The gateway schema
    already forbids extra keys and that enforcement was MEASURED (ADR 0007), but enforcement
    is a property of a gateway deployment that can change underneath us. Validating here too
    means a silent regression there surfaces as an error instead of as a field nobody checks.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Literal["reply_to_client", "clarify", "out_of_scope", "follow_up",
                    "procedure", "discovery", "frequency", "show_exchange",
                    "what_happened_next", "coverage_check", "sequence", "phrasing",
                    "pitfalls", "scenario_check", "play_confidence"]
    #: The CLIENT'S OWN WORDS, which is what gets embedded -- never the CSM's framing around
    #: them. Empty for any intent that does not retrieve.
    retrieval_query: str = ""
    #: What to put to the CSM when clarifying. Empty otherwise.
    question: str = ""

    @model_validator(mode="before")
    @classmethod
    def _a_follow_up_searched_for_nothing(cls, data):
        """A follow-up and a corpus question run NO retrieval, so neither can carry a
        retrieval query.

        Cleared rather than rejected: a model that helpfully fills the field is not making
        an unusable decision, it is making a misleading one. Every response echoes
        `retrieval_query` so a bad extraction is visible in production
        (`responding._with_intake`), and on this path echoing a query that was never
        embedded would report a search that did not happen.
        """
        if isinstance(data, dict) and data.get("intent") in (FOLLOW_UP, *CORPUS_INTENTS):
            return {**data, "retrieval_query": ""}
        return data

    @field_validator("retrieval_query", "question")
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
        if self.intent in RETRIEVING_INTENTS and not self.retrieval_query:
            raise ValueError(f"{self.intent} with no retrieval_query would embed nothing")
        return self


def response_schema() -> dict:
    """The JSON Schema sent to the gateway, derived from the model so the two cannot drift.

    Pydantic emits `additionalProperties: false` from `extra="forbid"` and the enum from the
    Literal, so adding an intent to IntakeDecision updates what the gateway will accept
    without a second edit here.
    """
    return {"name": "intake_decision", "strict": True,
            "schema": IntakeDecision.model_json_schema()}


def build_prompt(message: str, thread=()) -> str:
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
        f'  "{SEQUENCE}" -- the CSM wants to know WHAT ORDER to do things in: "what do i '
        "do first\", \"what order should i run these in\", \"where do i start with this\".",
        "",
        f'  "{PHRASING}" -- the CSM wants THE WORDING NAREN HIMSELF USES: "how does he '
        "say it\", \"how does naren word that\", \"what language does he use for pushback\".",
        "",
        f'  "{PITFALLS}" -- the CSM wants to know WHAT GOES WRONG: "what usually goes wrong '
        "here\", \"what mistakes do people make\", \"what should i avoid\".",
        "",
        f'  "{SCENARIO_CHECK}" -- the CSM wants to know whether a play APPLIES to what they '
        "are seeing: \"does this play apply here\", \"is this that kind of situation\", "
        "\"am i in the right playbook\".",
        "",
        f'  "{PLAY_CONFIDENCE}" -- the CSM wants to know HOW WELL EVIDENCED a play is: "how '
        "solid is this\", \"how many calls is this based on\", \"how much should i trust "
        "this\".",
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
        "  - Reported speech counts. \"Client is asking why their spend went up 40% in "
        "March\" is not a quote, but it carries a specific claim that can be searched. "
        f'That is "{REPLY_TO_CLIENT}". Reserve "{CLARIFY}" for messages with no specifics '
        "at all.",
        "",
        *_thread_rules(thread),
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
    ]


def classify(message: str, gateway, *, thread=(), model: str = CHAT_MODEL,
             reasoning_effort: str | None = REASONING_EFFORT) -> tuple[IntakeDecision, dict]:
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
            payload, meta = gateway.chat_json(
                build_prompt(message, thread),
                model=model,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                schema=response_schema(),
                reasoning_effort=reasoning_effort,
                # Same reason as the answering path: two CSMs asking similar questions must
                # never be served each other's decision.
                no_cache=True,
            )
            return IntakeDecision.model_validate(payload), meta
        except Exception:                       # noqa: BLE001 -- see the docstring
            continue

    return fallback_decision(message), meta


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
