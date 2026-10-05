"""The HTTP contract of `ask_naren.api`, as Pydantic models: what `/ask` accepts, and what every
endpoint can answer.

THE REQUEST MODEL IS ENFORCED; THE RESPONSE MODELS DOCUMENT. `AskRequest` is what FastAPI
parses and validates every body against. The response models are what `/docs` shows, and
the ones THIS layer writes (busy, deadline, fault) are built from them -- but an answerer's
own response is sent as the answerer composed it, never filtered through `AskResponse`.
Filtering would make any drift between these models and the answer path a 500 in front of a
CSM, or worse, a field silently dropped; the answer path's own tests pin those shapes.

`AskResponse` MIRRORS `frontend/src/types.ts` (`AskNarenResponse`), which mirrors the
answer path. Three copies of one contract is the cost of a typed boundary in two languages;
when the answer path grows a field, this file and `types.ts` follow it.

`outcome` is the discriminator, and `kind` discriminates within `rendered` -- the same two
levels the frontend switches on, so the schema reads the way the render code does.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ask_naren.threads import ThreadTurn


# -- the request -------------------------------------------------------------------------

class AskRequest(BaseModel):
    """One question, and the thread it arrived in (issue #15).

    UNKNOWN KEYS ARE IGNORED, NOT REJECTED (issue #5): a caller cannot select the playbook
    variant, and the way that is guaranteed is that nothing here reads any other field. A
    TURN, by contrast, forbids unknown keys -- see `ThreadTurn` -- so the one field that
    grew cannot become a side channel.
    """

    situation: str = Field(
        min_length=1,
        description="What the client said, and what the CSM needs. Passed to the answerer "
                    "exactly as sent -- not stripped.",
        examples=["The client says our cost per application is three times their "
                  "in-house number. How do I respond?"])
    thread: list[ThreadTurn] | None = Field(
        default=None,
        description="Earlier turns of this conversation, replayed by the frontend. Absent "
                    "or null means a new thread. A thread that is present and malformed is "
                    "a 400, never ignored: it means the caller and the service disagree "
                    "about the shape.")

    @field_validator("situation")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("'situation' must be a non-empty string")
        return v

    def turns(self) -> tuple[ThreadTurn, ...]:
        """The thread as the answerer takes it: a tuple, empty when absent."""
        return tuple(self.thread or ())


# -- shared pieces -----------------------------------------------------------------------

class _Open(BaseModel):
    # Documenting, not filtering: a field the answer path adds before this file follows it
    # must not fail validation where these models ARE used (the service's own declines).
    model_config = ConfigDict(extra="allow")


class Intake(_Open):
    """What intake decided about the message, echoed so a silently failing intake is
    visible (issue #14)."""
    intent: str
    retrieval_query: str
    # Required here because this service always sends it; optional in types.ts, which also
    # reads responses stored before the field existed.
    situation: Literal["carried", "opens"] = Field(
        description="Whether the answer was carried from the thread or searched for (#53).")


class Citation(_Open):
    label: str
    call_filename: str
    pair_id: int | None = Field(default=None, description="Absent on a Layer C answer.")
    scenario_key: str


class Match(_Open):
    """Recorded, never rendered as a score."""
    cosine: float
    scenario_key: str
    rank: int


class ScenarioRef(_Open):
    scenario_key: str
    description: str


class Exchange(_Open):
    client_said: str
    naren_replied: str


class Evidence(_Open):
    quote: str
    call: str
    label: str


class Pitfall(_Open):
    text: str
    evidence: list[Evidence]


# -- the four outcomes -------------------------------------------------------------------

DeclineReason = Literal[
    "no_close_match", "grounding_unverified", "out_of_scope", "follow_up_ungrounded",
    "service_error", "service_busy", "deadline_exceeded",
    # These two are synthesised by the frontend's proxy and never sent by this service.
    # Listed because this union mirrors the frontend's.
    "service_unreachable", "store_unavailable",
]


class Answered(_Open):
    """A model wrote prose, and the grounding gate verified `quote` against a real source."""
    outcome: Literal["answered"]
    intake: Intake | None = None
    answer: str
    quote: str
    citation: Citation
    match: Match | None = Field(
        default=None, description="Absent on a follow-up, and on a carried procedure (#53).")
    my_reply: str | None = Field(default=None, description="Present only on a contrast.")


class Declined(_Open):
    """No answer. `message` is written for a CSM and rendered as-is."""
    outcome: Literal["declined"]
    intake: Intake | None = None
    reason: DeclineReason
    message: str
    match: Match | None = None
    retry_after_seconds: int | None = Field(
        default=None, description="Present only on `service_busy`.")


class Clarify(_Open):
    """Ask Naren asking for something back. Carries no answer, quote or citation, by
    construction."""
    outcome: Literal["clarify"]
    intake: Intake | None = None
    question: str
    match: Match | None = None


class _Rendered(_Open):
    """Built from stored rows, with no model call at all (issues #19, #20)."""
    outcome: Literal["rendered"]
    intake: Intake | None = None


class Topic(_Open):
    topic: str
    scenarios: list[ScenarioRef]


class Discovery(_Rendered):
    kind: Literal["discovery"]
    grouped: bool
    topics: list[Topic]
    scenarios: list[ScenarioRef]
    total: int


class RankedScenario(ScenarioRef):
    support_calls: int
    call_coverage: float | None


class Frequency(_Rendered):
    kind: Literal["frequency"]
    scenarios: list[RankedScenario]
    total: int
    basis: str


class ShowExchange(_Rendered):
    kind: Literal["show_exchange"]
    exchange: Exchange
    citation: Citation
    match: Match


class Following(Exchange):
    scenario_key: str


class WhatHappenedNext(_Rendered):
    kind: Literal["what_happened_next"]
    exchange: Exchange
    following: list[Following]
    is_last: bool
    citation: Citation
    match: Match


class Sequence(_Rendered):
    kind: Literal["sequence"]
    scenario_key: str
    steps: list[str]
    match: Match | None = Field(default=None, description="Absent when carried (#53).")


class Phrase(Evidence):
    phrase: str


class Phrasing(_Rendered):
    kind: Literal["phrasing"]
    scenario_key: str
    phrases: list[Phrase]
    match: Match | None = Field(default=None, description="Absent when carried (#53).")


class Pitfalls(_Rendered):
    kind: Literal["pitfalls"]
    scenario_key: str
    pitfalls: list[Pitfall]
    match: Match | None = Field(default=None, description="Absent when carried (#53).")


class ScenarioCheck(_Rendered):
    kind: Literal["scenario_check"]
    asked_about: str
    scenario_key: str
    applies_when: str
    match: Match | None = Field(default=None, description="Absent when carried (#53).")


class PlayConfidence(_Rendered):
    kind: Literal["play_confidence"]
    scenario_key: str
    moves: int
    quotes: int
    n_evidence: int
    n_evidence_capped: bool
    basis: str
    match: Match | None = Field(default=None, description="Absent when carried (#53).")


class Account(_Open):
    account: str
    named: bool
    exchanges: int
    calls: int


class WhereElseSeen(_Rendered):
    kind: Literal["where_else_seen"]
    asked_about: str
    scenario_key: str
    same_scenario: int
    accounts: list[Account]
    accounts_named: int
    accounts_at_least: int
    accounts_at_most: int
    unnamed_calls: int
    exchanges: int
    basis: str


class CitedExchange(Exchange):
    citation: Citation


class PrepScenario(_Open):
    scenario_key: str
    description: str
    exchanges: int
    has_play: bool
    steps: list[str]
    example: CitedExchange


class CallPrep(_Rendered):
    kind: Literal["call_prep"]
    asked_about: str
    scenarios: list[PrepScenario]
    scenarios_found: int
    exchanges: int
    basis: str


class Move(_Open):
    name: str
    criterion: str
    evidence: list[Evidence]


class ImproveAtMove(_Rendered):
    kind: Literal["improve_at_move"]
    asked_about: str
    scenario_key: str
    focused: bool
    moves: list[Move]
    pitfalls: list[Pitfall]
    basis: str
    match: Match | None = Field(default=None, description="Absent when carried (#53).")


class Nearest(ScenarioRef):
    support_calls: int
    evidence: Literal["thin", "solid"]


class CoverageCheck(_Rendered):
    kind: Literal["coverage_check"]
    asked_about: str
    nearest: Nearest
    citation: Citation
    match: Match


Rendered = Annotated[
    Union[Discovery, Frequency, ShowExchange, WhatHappenedNext, Sequence, Phrasing,
          Pitfalls, ScenarioCheck, PlayConfidence, WhereElseSeen, CallPrep, ImproveAtMove,
          CoverageCheck],
    Field(discriminator="kind"),
]

AskResponse = Union[Answered, Declined, Clarify, Rendered]


# -- everything that is not an answer ----------------------------------------------------

class Error(BaseModel):
    """A request the service could not read: a malformed body, an unknown path. `error` is
    for an engineer; nothing was asked, so there is nothing for a CSM to read."""
    error: str


class Health(BaseModel):
    status: Literal["ok"]


class Readiness(BaseModel):
    """Readiness, and the admission counts an operator reads to tell whether this API key's
    allowance has been outgrown (issue #32)."""
    model_config = ConfigDict(extra="allow")
    status: Literal["ready", "starting", "saturated"]
