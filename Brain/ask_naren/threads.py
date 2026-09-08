"""A thread: one continuing conversation between a CSM and Ask Naren (issue #15).

THE SERVICE STORES NONE OF IT. A thread is held by the CALLER and replayed with every
message, which is what preserves the property the whole tool is built around -- Ask Naren
holds no database handle while answering, so it cannot write to Brain's pipeline
(`ops/serve_ask_naren.py`). Anything stored server-side would need one.

WHAT A TURN CARRIES, AND WHY IT IS NOT THE WHOLE RESPONSE. A turn is a reduced record: what
the CSM typed, what Ask Naren said back, and the IDENTIFIERS of the exchange the answer
rested on. It is deliberately not the response body replayed verbatim:

  * the body is capped (`service.MAX_BODY_BYTES`), and a thread grows with every message;
  * ADR 0006's corollary is that history may supply an IDENTIFIER but never text that gets
    embedded. Carrying `pair_id` lets a follow-up ground on the exchange already cited
    WITHOUT re-embedding anything, because the text is looked up from the pool we already
    hold. Carrying the exchange's text instead would put Naren's words into the thread,
    where the next answer could stitch a quote out of them (issue #16's quote bleed).

Pydantic rather than a dataclass, per ADR 0007: this is nested caller-supplied data, and
nothing behind it re-checks the shape.

Nothing here retrieves, generates or touches Postgres.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter, field_validator

#: How much of a thread reaches the request path, in characters. Two separate jobs, and
#: this is the SECOND one:
#:
#:   * `service.MAX_BODY_BYTES` (64KB) stops a runaway client reading the service out of
#:     memory. It is a transport guard and knows nothing about threads.
#:   * this cap bounds what a THREAD contributes to a prompt. A conversation that has run
#:     all afternoon must not quietly turn every question into a 60KB generation.
#:
#: 24k characters is roughly 6k tokens -- large enough that a real working session never
#: reaches it, small enough that hitting it is not a surprise bill.
MAX_THREAD_CHARS = 24_000

#: Turns whose prose is kept for as long as possible when trimming. The LAST turn is what a
#: follow-up ("and if they push back on price?") actually refers to, so its text is the last
#: thing to go.
KEEP_RECENT = 2

#: Roughly what an elided turn still costs on the wire: its outcome and its identifiers.
#: Used only so `trim` charges for a blanked turn rather than treating it as free.
_ELIDED_TURN_CHARS = 40


class ThreadTurn(BaseModel):
    """One exchange already in the thread: what was asked, what came back, and what it rested
    on.

    `extra="forbid"` for the same reason `IntakeDecision` has it -- this crosses a trust
    boundary and a key nobody validates is a key nobody notices.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: What the CSM typed. EMPTY when the turn has been elided by `trim` -- the identifiers
    #: below survive that, the prose does not.
    message: str = ""
    outcome: Literal["answered", "declined", "clarify"]
    #: What Ask Naren said back: the answer, the clarify's question, or the decline's
    #: message. One field rather than three, because `outcome` already says which it is and
    #: three optional fields is three ways for a caller to fill in the wrong one.
    reply: str = ""

    # -- the carried identifiers (ADR 0006). These are what a later message may inherit,
    # and they are what `trim` must never drop. None/empty when the turn grounded in
    # nothing, which is every clarify and every decline.
    scenario_key: str = ""
    pair_id: int | None = None
    call_filename: str = ""

    @field_validator("message", "reply", "scenario_key", "call_filename")
    @classmethod
    def _stripped(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("pair_id")
    @classmethod
    def _positive(cls, v: int | None) -> int | None:
        """A `pair_id` is a `kb_pairs` primary key. Zero or negative is not a row that can
        be looked up, and admitting one would turn a bad caller into a silent no-match."""
        if v is not None and v <= 0:
            raise ValueError("pair_id must be a positive kb_pairs id")
        return v

    @property
    def chars(self) -> int:
        return len(self.message) + len(self.reply) + _ELIDED_TURN_CHARS

    def elided(self) -> "ThreadTurn":
        """The same turn with its PROSE removed and its identifiers intact.

        This is the shape of trimming here, and it is why the ADR calls trimming "not
        truncation": what a later message inherits from an old turn is a scenario key or a
        pair id, not the sentence that produced it.
        """
        return self.model_copy(update={"message": "", "reply": ""})


_TURNS = TypeAdapter(list[ThreadTurn])


def parse(raw) -> tuple[ThreadTurn, ...]:
    """Validate a caller-supplied thread. Raises ValueError on anything that is not one.

    REJECTS RATHER THAN IGNORES. A thread that fails to parse means our own frontend and
    this service disagree about the shape -- a version skew after a deploy. Silently
    dropping it would answer every follow-up as a brand new question while looking entirely
    healthy, which is the exact failure `responding._with_intake` exists to make visible.
    The frontend validates what it reads out of `localStorage` and starts a fresh thread
    when it does not match, so this 400 is unreachable from our own client and is a genuine
    bug signal from anything else.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("'thread' must be a list of turns")
    try:
        return tuple(_TURNS.validate_python(raw))
    except Exception as e:                      # noqa: BLE001 -- reported, not swallowed
        raise ValueError(f"'thread' is not a valid thread: {e}") from None


def trim(turns, budget: int = MAX_THREAD_CHARS) -> tuple[ThreadTurn, ...]:
    """Fit a thread into `budget` characters WITHOUT losing a carried identifier.

    DROPPING THE OLDEST MESSAGES IS THE WRONG RULE, and ADR 0006 says so explicitly: the
    message that established the scenario is usually the first one, and every later turn
    inherits that identifier from it. Dropping it strands the conversation.

    So the unit of trimming is a turn's PROSE, not the turn. Turns are elided -- blanked of
    text, identifiers kept -- in this order:

      1. the middle, oldest first (everything but the first turn and the last KEEP_RECENT);
      2. then the FIRST turn's prose, its identifiers still surviving;
      3. then the older of the recent turns, newest kept longest;
      4. finally the last turn's reply, then its message, truncated to fit.

    Only if a thread of nothing but identifiers still does not fit are whole turns dropped,
    oldest first. At ~40 characters an elided turn that is 600 turns in one conversation --
    unreachable in practice, and the honest place to lose data if it ever happens, because
    the newest identifiers are the live ones.
    """
    turns = list(turns)
    if not turns:
        return ()
    if _total(turns) <= budget:
        return tuple(turns)

    # 1. the middle, oldest first.
    for i in range(1, max(1, len(turns) - KEEP_RECENT)):
        turns[i] = turns[i].elided()
        if _total(turns) <= budget:
            return tuple(turns)

    # 2. the first turn's prose. Its scenario_key is what mattered and it survives.
    turns[0] = turns[0].elided()
    if _total(turns) <= budget:
        return tuple(turns)

    # 3. the recent ones, newest kept longest.
    for i in range(max(1, len(turns) - KEEP_RECENT), len(turns) - 1):
        turns[i] = turns[i].elided()
        if _total(turns) <= budget:
            return tuple(turns)

    # 4. the last turn, which is the one a follow-up is actually about. Its reply goes
    # first, then its message is cut to whatever is left.
    last = turns[-1]
    turns[-1] = last.model_copy(update={"reply": ""})
    if _total(turns) <= budget:
        return tuple(turns)
    room = budget - _total(turns[:-1]) - _ELIDED_TURN_CHARS
    turns[-1] = turns[-1].model_copy(
        update={"message": turns[-1].message[:room] if room > 0 else ""})
    if _total(turns) <= budget:
        return tuple(turns)

    # 5. identifiers alone do not fit. Drop from the oldest end; the newest carried
    # identifier is the one a follow-up needs.
    while len(turns) > 1 and _total(turns) > budget:
        turns.pop(0)
    return tuple(turns)


def _total(turns) -> int:
    return sum(t.chars for t in turns)
