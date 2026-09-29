"""Who is served now, who waits, and who is turned away (issue #32).

*** THE ONE DECISION, AND EVERY OTHER NUMBER HERE FALLS OUT OF IT. ***

`ANSWER_DEADLINE_SECONDS` is how long a CSM is willing to wait before "no answer" beats
"still waiting". It is a product decision, taken at 30 seconds for someone mid-client-call:
long enough that at this team's real load essentially nobody is ever refused, short enough
that the unlucky person at the back of a full queue is told something inside half a minute
rather than sitting on a spinner while a client waits on the line.

Nothing else in this module is a chosen constant. In particular THE QUEUE DEPTH IS NOT A
LIMIT SOMEONE PICKED -- it is "how many people can still be served before the deadline
expires", computed from the deadline, the number of answers in flight and what an answer
costs. Written down as a literal it would quietly stop agreeing with the deadline the first
time any of those moved, and nothing would fail: the service would go on queueing people it
had already decided it could not serve in time, and each of them would wait out the whole
deadline to be told nothing. Which is the single worst outcome available here, and strictly
worse than being refused on arrival.

WHY A BOUND AT ALL, GIVEN #28-#31 JUST REMOVED ONE. The real ceiling is not this code --
it is the gateway's 8 requests in flight per API KEY, shared across chat and embeddings,
which Brain operates at 6 (Brain/docs/GOTCHAS.md). So about six CSMs are genuinely being
served at once no matter what this service accepts. Before the async chain the serial
server could not over-accept; it physically did one thing at a time. Removing that brake
means putting a deliberate one back, or thirty simultaneous questions all get accepted,
contend for those six slots, and everyone waits about a minute -- which is WORSE for the
people at the front than the serial server was.

QUEUEING IS THE DEFAULT AND THE REFUSAL IS RARE, and that ordering is the point. Capacity
is ~6 answers at a time, and 13 of the 19 intents do not generate at all, so a queue only
builds if generating questions keep arriving faster than they are answered -- a 40-person
CS team would each have to ask one every eighty seconds without pause. In normal use the
queue is empty or one deep. A refusal is not a capacity limit dressed up; it is a
don't-lie-to-people limit, and most CSMs should never see one.

NO LATENCY NUMBER IS QUOTED IN ANY DOC FOR THIS, deliberately -- gateway latency has moved
~6x between runs. `ANSWER_COST_SECONDS` is the one place a duration is written, it is a
SIZING INPUT rather than a claim about how fast the service is, and it is overridable from
the environment precisely because it will drift. Re-measure it with
`ask-naren/audit/check_concurrent_service.py` and read the result from that directory's
artifacts; do not trust the default here as a current measurement.

THIS MODULE TOUCHES NO HTTP. What a busy refusal looks like on the wire -- the 429, the
`Retry-After`, the reason code and the sentence a CSM reads -- is `ask_naren/api/`,
because that is the boundary that writes CSM-facing copy. Here there is only the
arithmetic and the gate.
"""
from __future__ import annotations

import asyncio
import contextlib
import math
import os

#: *** THE DECISION. *** The whole-request budget: queue wait PLUS the answer itself, not
#: the answer alone. A caller admitted at the back of a full queue is being promised an
#: answer within this, and the depth below is sized so that promise is keepable.
#:
#: 30s, for a CSM mid-call. The alternatives were weighed on how many people a burst turns
#: away rather than on how long an answer takes, and at this team's load being refused is
#: the likelier regret than the extra ten seconds. Changing it re-derives the depth
#: automatically, which is the whole reason the depth is computed rather than written down.
#:
#: WHOLE-REQUEST is what makes the depth smaller than issue #32's table suggests: the budget
#: has to cover the queue AND the answer, so the queue is 8 deep rather than ~15. See
#: `total_seconds_for`, and the live check that found the difference the hard way.
#:
#: *** THE OVERRIDE IS SAFE TO TIGHTEN AND NOT SAFE TO RAISE, for a CSM coming through the
#: web app. *** `frontend/src/app/api/ask-naren/route.ts` aborts its upstream fetch a few
#: seconds after this deadline, deliberately, so that every outcome the service can produce
#: arrives through the proxy rather than being cut off by it. Raise this past that and the
#: proxy fires FIRST -- and what a CSM then reads is `service_unreachable`, a fault, for
#: what was really a capacity event. That is precisely the conflation issue #32 exists to
#: prevent, arriving through the back door. Raising it means moving both numbers.
#: `ask-naren/audit/check_admission_live.py` does raise it, and is allowed to because it
#: speaks to the service directly and never goes near the proxy.
#: The shipped value, separate from the resolved one so that the number the frontend proxy
#: mirrors can be PINNED to it by a test. An operator's local override must not make that
#: test fail; what has to stay true is that the deployed proxy and the deployed service
#: agree. See test_the_frontend_proxy_timeout_is_set_against_this_deadline.
SHIPPED_DEADLINE_SECONDS = 30.0

ANSWER_DEADLINE_SECONDS = float(
    os.environ.get("ASK_NAREN_DEADLINE_SECONDS", SHIPPED_DEADLINE_SECONDS))

#: What one answer costs, used ONLY to size the queue -- never to promise anything to a
#: caller. It is the weakest number here: it is an average over intents that differ in cost
#: by ~6x (a generation against a rendered answer that calls no model at all), against a
#: gateway whose latency has been observed moving ~6x between runs. Sizing tolerates that,
#: because being wrong by a factor here moves the depth, not the deadline -- an admitted
#: caller is still held to 30s either way, and the deadline is enforced rather than
#: estimated. See the module docstring on where to re-measure.
ANSWER_COST_SECONDS = float(os.environ.get("ASK_NAREN_ANSWER_COST_SECONDS", "12.5"))


def gateway_in_flight_limit() -> int:
    """How many answers may be in flight: THE GATEWAY'S NUMBER, read rather than retyped.

    *** THIS IS THE ONE NAMED PLACE. *** `GATEWAY_MAX_PARALLEL` is already the per-API-key
    allowance the transport clamps itself to, and reading it here means asking the gateway
    team to raise this key's limit raises the service's bound in the same breath. A `6`
    typed into this file instead would make that a two-place change, and the second place
    would be found by a CSM being refused while the transport sat half idle.

    An answer's gateway calls are strictly SEQUENTIAL -- intake, then an embedding, then a
    generation -- so N concurrent answers are at most N concurrent gateway requests, and
    the two bounds are the same number rather than one being derived from the other by some
    fudge factor.

    A FUNCTION, and the import is inside it, so the gateway module's attribute is read at
    CALL time rather than copied into a constant here. Note precisely what that does and
    does not buy, because an earlier version of this docstring overclaimed:
    `BRAIN_GATEWAY_MAX_PARALLEL` is read once when `shared/gateway.py` is imported, so this
    does not make the environment variable live. What it does mean is that the number has
    exactly one home -- anything that rebinds `gateway.GATEWAY_MAX_PARALLEL`, including the
    test that proves this is not a copy, is honoured here without a second edit.
    """
    from shared.gateway import GATEWAY_MAX_PARALLEL
    return GATEWAY_MAX_PARALLEL


def wait_seconds_for(position: int, *, answer_cost: float, in_flight_limit: int) -> float:
    """How long the caller at `position` in the queue waits BEFORE being served.

    With `in_flight_limit` answers running and each taking `answer_cost`, a slot frees every
    `answer_cost / in_flight_limit` on average, so the p-th person in line waits for p of
    those. Position is 1-based: the person immediately behind a full set of slots is at
    position 1 and waits for the first one to free.

    The wait ALONE. What the caller experiences is this plus their own answer -- see
    `total_seconds_for`, which is the one to compare against a deadline.
    """
    return position * answer_cost / in_flight_limit


def total_seconds_for(position: int, *, answer_cost: float,
                      in_flight_limit: int) -> float:
    """How long the caller at `position` waits IN TOTAL: the queue, then their own answer.

    *** THE DISTINCTION FROM `wait_seconds_for` IS A DEFECT THIS CODE ALREADY HAD, found by
    `ask-naren/audit/check_admission_live.py` and not by any offline test. ***

    Issue #32's table sizes the queue by "person at the back waits", and the first version
    of this module implemented exactly that: the depth was the last position whose WAIT fit
    the deadline. But the deadline is the WHOLE-REQUEST budget, so a caller admitted at that
    position waits almost the entire deadline and then still needs a full answer -- roughly
    `deadline + answer_cost` in total, against a deadline of `deadline`. Every position in
    the last `in_flight_limit` of that queue was therefore GUARANTEED to be killed by the
    very deadline it was admitted under, which is "accepted and failed later", the one
    behaviour the ticket rules out in as many words.

    Measured, rather than reasoned about: a live burst against a slow gateway returned three
    504 `deadline_exceeded` responses with `deadlines_missed=3` and every count otherwise
    correct. Nothing offline could see it -- a stubbed answerer returns instantly, so the
    queue tail always fits.
    """
    return (wait_seconds_for(position, answer_cost=answer_cost,
                             in_flight_limit=in_flight_limit)
            + answer_cost)


def queue_depth_within(deadline: float, *, answer_cost: float,
                       in_flight_limit: int) -> int:
    """The largest queue position that can still be ANSWERED inside `deadline`.

    THE DEFINITION OF THE DEPTH, and the inverse of `total_seconds_for`. Two properties,
    both load-bearing and pinned by a test:

      * nobody is admitted who cannot be served in time -- `total_seconds_for(depth) <=
        deadline`;
      * nobody is turned away who could have been -- `total_seconds_for(depth + 1) >
        deadline`.

    Only the first is about honesty. The second is what stops a cautious-looking number
    from refusing people the service had room for, which is the failure that would be
    invisible in production: a refusal nobody needed looks exactly like a refusal that was
    necessary.

    NOTE IT IS SMALLER THAN THE TICKET'S TABLE, deliberately, and the table is the thing
    that is wrong. "30s -> ~15 deep" sizes the queue by the WAIT; leaving room for the
    answer as well gives 8. The difference is exactly `in_flight_limit`, i.e. one full round
    of answers, and those are the callers the old number admitted and then killed. See
    `total_seconds_for`.

    Zero is a legitimate result -- a deadline no longer than one answer means "serve the
    slots, queue nobody", not "refuse everybody"; see `Admission.saturated`.
    """
    if deadline <= answer_cost:
        return 0
    return max(0, int((deadline - answer_cost) * in_flight_limit // answer_cost))


class Busy(Exception):
    """Too many questions right now -- and NOT a fault, and NOT a no-close-match decline.

    Raised on arrival, before the caller has waited for anything. It carries the estimate
    rather than leaving the boundary to invent one, because the number comes from the queue
    the gate can see and nothing above it can.
    """

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"busy; retry in about {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


class Admission:
    """The gate. One per process, driven by ONE event loop.

    ONE LOOP IS NOT A STYLE POINT, and it is the same hazard `shared/gateway.py` documents:
    the semaphore binds to whichever loop first awaits it, and an asyncio primitive raises
    if awaited from another. A process wrapping each request in its own `asyncio.run` would
    get a fresh gate every time, so the bound would silently become per-request -- i.e.
    unbounded -- while looking perfectly healthy. `ops/serve_ask_naren.py` runs exactly one
    `asyncio.run` for the whole process, which is what makes this safe.

    The counters are plain ints because nothing here is threaded: a coroutine cannot be
    interrupted between two statements unless it awaits, and the increments do not. A lock
    would guard against something that cannot happen.
    """

    def __init__(self, *, in_flight_limit: int | None = None,
                 deadline: float = ANSWER_DEADLINE_SECONDS,
                 answer_cost: float = ANSWER_COST_SECONDS) -> None:
        self.in_flight_limit = (in_flight_limit if in_flight_limit is not None
                                else gateway_in_flight_limit())
        self.deadline = deadline
        self.answer_cost = answer_cost
        self.queue_limit = queue_depth_within(
            deadline, answer_cost=answer_cost, in_flight_limit=self.in_flight_limit)

        self._slots = asyncio.Semaphore(self.in_flight_limit)

        self.in_flight = 0
        self.queued = 0
        #: HOW MANY WERE LET IN, which is the denominator `refused` is meaningless without.
        #: "12 refused" is two opposite conclusions depending on whether it is 12 of 12 or
        #: 12 of ten thousand, and the ticket's own standard for the refusal -- "rare enough
        #: that most CSMs never see it" -- is a RATE. Added after a review pointed out that
        #: the counters could not answer the question they exist to answer.
        self.admitted = 0
        #: The peaks and the refusal count, not the instantaneous numbers, are what say
        #: whether we have outgrown the gateway allowance. An operator reading `in_flight`
        #: at a quiet moment learns nothing, and the interesting moment is never the one
        #: anybody is looking at.
        self.peak_in_flight = 0
        self.peak_queued = 0
        self.refused = 0
        self.deadlines_missed = 0

    def note_deadline_missed(self) -> None:
        """Record that an ADMITTED request ran out of time.

        A method rather than a public counter the HTTP layer increments, so that all four
        numbers `snapshot()` reports are maintained in one file. `refused` was already
        incremented in here and `deadlines_missed` was not, which is the sort of split that
        ends with two places disagreeing about what a "missed" request is.

        It is the sharpest number in the snapshot: a rising count means the cost estimate
        the depth is sized from has drifted, so the queue is admitting people it can no
        longer serve in time. Nothing here acts on it -- resizing is a decision, not an
        adjustment.
        """
        self.deadlines_missed += 1

    @property
    def saturated(self) -> bool:
        """Cannot take more work: every slot is busy AND the queue behind them is as deep
        as the deadline can absorb.

        The state `/ready` had nothing to report before this existed. Note what it is NOT:
        every slot being busy is normal and fine, because a busy slot means someone is
        being answered. Saturation is that PLUS a full queue behind them.

        *** BOTH HALVES ARE REQUIRED, and dropping the first one is a real defect rather
        than a tidier predicate. *** A deadline shorter than one answer's share of a slot
        makes `queue_limit` zero -- a legitimate configuration, meaning "serve the six,
        queue nobody" -- and `queued >= 0` is then true forever. The service refuses every
        caller, including the very first one against a completely idle process, while
        `/health` reports it perfectly alive. Caught by
        `test_the_deadline_fires_rather_than_letting_a_caller_hang`, which set a short
        deadline for an unrelated reason and got a 429 where it expected an answer.
        """
        return self._slots.locked() and self.queued >= self.queue_limit

    def retry_after_seconds_at(self, position: int) -> int:
        """How long the caller at `position` would have taken to get an answer, in total.

        THE REFUSED CALLER'S OWN WOULD-BE POSITION, which is what makes this an estimate
        rather than a constant wearing an estimate's clothes: it is the very number that
        was compared against the deadline and found too large. It is therefore never below
        the deadline at the moment of a refusal, so a caller who waits it out does not
        arrive back behind the same queue and get refused a second time.

        The TOTAL rather than the queue wait, for the same reason the depth uses the total:
        the wait alone understates what this caller was asking for.

        Deliberately not "the time until one slot frees", which would be arithmetically
        true -- a slot does free that often -- and useless, because the retrying caller
        lands behind the same queue.

        Never zero. A caller told to retry immediately does, and is refused again.
        """
        return max(1, math.ceil(total_seconds_for(
            position, answer_cost=self.answer_cost,
            in_flight_limit=self.in_flight_limit)))

    def snapshot(self) -> dict:
        """What `/ready` reports. Flat and JSON-ready; no objects, no derived opinions."""
        return {
            "in_flight": self.in_flight,
            "in_flight_limit": self.in_flight_limit,
            "queued": self.queued,
            "queue_limit": self.queue_limit,
            "deadline_seconds": self.deadline,
            "answer_cost_seconds": self.answer_cost,
            "peak_in_flight": self.peak_in_flight,
            "peak_queued": self.peak_queued,
            # `admitted` is here so the two below can be read as RATES. A refusal count on
            # its own says nothing about whether this API key's allowance is still enough.
            "admitted": self.admitted,
            "refused": self.refused,
            "deadlines_missed": self.deadlines_missed,
        }

    @contextlib.asynccontextmanager
    async def slot(self):
        """Hold one of the in-flight slots for the duration of the block.

        Waits if they are all taken -- THE DEFAULT PATH, and the one almost every caller
        takes. Raises `Busy` immediately, before waiting for anything, if the queue is
        already as deep as the deadline can absorb.

        CANCELLING THE TASK RELEASES WHATEVER IT HELD, which is how an abandoned request
        stops consuming capacity: a CSM closing the tab drops out of the queue instead of
        leaving a colleague waiting behind an answer nobody will read. Both `finally`
        blocks are await-free so they complete even inside a cancellation.
        """
        # A caller who needs no queue is never refused, which is why the depth check lives
        # INSIDE this branch. `Semaphore.acquire` returns without yielding when a slot is
        # free, so `locked()` is also what distinguishes real contention from none --
        # incrementing `queued` unconditionally would record a peak queue of 1 for a
        # service nobody is contending for, and `peak_queued` is one of the two numbers an
        # operator reads to decide whether this allowance is still enough. Checking
        # `locked()` and then acquiring is race-free for the same reason the counters need
        # no lock: nothing awaits in between.
        waiting = self._slots.locked()
        if waiting:
            if self.queued >= self.queue_limit:
                self.refused += 1
                raise Busy(self.retry_after_seconds_at(self.queued + 1))
            self.queued += 1
            self.peak_queued = max(self.peak_queued, self.queued)
        try:
            await self._slots.acquire()
        finally:
            if waiting:
                self.queued -= 1

        self.admitted += 1
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            yield
        finally:
            # Runs for a raised answer and a cancelled one as well as a served one. A fault
            # that leaked its slot would wedge the service into refusing everyone after six
            # of them, while still reporting itself alive.
            self.in_flight -= 1
            self._slots.release()
