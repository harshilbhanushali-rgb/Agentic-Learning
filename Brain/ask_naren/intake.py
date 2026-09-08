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

#: Every intent intake may return today. Issues #17-#23 add more; each addition is a change
#: to the schema sent to the gateway AND to the prompt's discriminators, never one alone.
INTENTS = (REPLY_TO_CLIENT, CLARIFY, OUT_OF_SCOPE)


class IntakeDecision(BaseModel):
    """A validated intake decision -- the boundary between an untrusted model reply and the
    rest of the request path (ADR 0007).

    `extra="forbid"` is defence in depth rather than belt-and-braces. The gateway schema
    already forbids extra keys and that enforcement was MEASURED (ADR 0007), but enforcement
    is a property of a gateway deployment that can change underneath us. Validating here too
    means a silent regression there surfaces as an error instead of as a field nobody checks.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Literal["reply_to_client", "clarify", "out_of_scope"]
    #: The CLIENT'S OWN WORDS, which is what gets embedded -- never the CSM's framing around
    #: them. Empty for any intent that does not retrieve.
    retrieval_query: str = ""
    #: What to put to the CSM when clarifying. Empty otherwise.
    question: str = ""

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
        if self.intent == REPLY_TO_CLIENT and not self.retrieval_query:
            raise ValueError("reply_to_client with no retrieval_query would embed nothing")
        return self


def response_schema() -> dict:
    """The JSON Schema sent to the gateway, derived from the model so the two cannot drift.

    Pydantic emits `additionalProperties: false` from `extra="forbid"` and the enum from the
    Literal, so adding an intent to IntakeDecision updates what the gateway will accept
    without a second edit here.
    """
    return {"name": "intake_decision", "strict": True,
            "schema": IntakeDecision.model_json_schema()}


def build_prompt(message: str) -> str:
    """Intake's prompt. NOT frozen -- unlike the answering prompts (ADR 0001), no measured
    number rests on its wording, and routing accuracy is measured against labelled messages
    rather than asserted in a test. Improve it, then re-measure.

    The discriminators are spelled out because a classifier fails on near neighbours, not on
    distant ones.
    """
    return "\n".join([
        'You are the intake step of "Ask Naren", an internal Joveo tool that answers a CSM '
        "by finding what Naren said in the closest real client situation from his call "
        "transcripts.",
        "",
        "Decide what should happen to this message from a CSM.",
        "",
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
        f'  "{OUT_OF_SCOPE}" -- THE CSM is asking YOU for an internal fact about Joveo: a '
        "list price, a contract term, which integrations exist, what a policy says. Naren's "
        "call transcripts are not a product document. Do NOT clarify these; there is nothing "
        "the CSM could reword that would make them answerable.",
        "",
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
        f'  - For "{OUT_OF_SCOPE}", leave retrieval_query and question empty.',
        "",
        "Two distinctions that are easy to get wrong:",
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
        f'When genuinely torn, prefer "{REPLY_TO_CLIENT}". Answering and being slightly off '
        "is more useful to a CSM mid-call than being asked for something they thought they "
        "had already given.",
    ])


def classify(message: str, gateway, *, model: str = CHAT_MODEL,
             reasoning_effort: str | None = REASONING_EFFORT) -> tuple[IntakeDecision, dict]:
    """Decide what happens to `message`. Returns (decision, meta).

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
                build_prompt(message),
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


def fallback_decision(message: str) -> IntakeDecision:
    """Answer the message as written -- exactly what the tool did before intake existed.

    PUBLIC, and there is ONE definition on purpose. This is the behaviour the module
    docstring calls its single most important property, and `responding.respond` needs it too
    for the case where `classify` itself raises. Two copies of a safety fallback is two places
    for it to stop agreeing about what "degrade gracefully" means.
    """
    return IntakeDecision(intent=REPLY_TO_CLIENT, retrieval_query=message.strip())
