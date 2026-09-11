"""ask_naren/admission.py -- who is served now, who waits, and who is turned away.

The arithmetic and the gate, with no HTTP anywhere near it. The HTTP shape of a busy
refusal is pinned in test_ask_naren_service.py; what is pinned here is that the numbers are
DERIVED and that the gate honours them under real contention.

WHY THE ARITHMETIC GETS TESTS OF ITS OWN. Issue #32's queue depth is not a constant someone
picked -- it is "how many people can still be served before the deadline expires". Written
as a literal it would silently stop matching the deadline the first time either number
moved, and nothing would fail: the service would keep queueing people it had already
decided it could not serve, and they would wait out the full deadline to be told nothing.
So the relationship itself is what is asserted, in both directions.
"""
import asyncio
import math
import pathlib
import re

import pytest

from ask_naren import admission


# -- the derivation ----------------------------------------------------------------------

def test_the_queue_depth_is_the_last_position_that_can_still_be_answered_in_time():
    """THE CENTRAL INVARIANT, and the reason depth is computed rather than written down.

    Both halves matter and they fail independently. The first says nobody is admitted who
    cannot be served in time; the second says nobody is turned away who could have been.
    A depth that satisfied only the first would be a correct-looking number that refuses
    people the service had capacity for.

    *** MEASURED AGAINST THE TOTAL, NOT THE QUEUE WAIT, and that is the fix for a real
    defect. *** The first version of this test compared `wait_seconds_for` against the
    deadline, which is what issue #32's table does -- and it passed while the last
    `in_flight_limit` positions of the queue were guaranteed to be killed by the deadline
    they had just been admitted under. A stubbed answerer returns instantly, so no offline
    test could see it; a live burst against a slow gateway returned three 504s and found it.
    """
    limit = admission.gateway_in_flight_limit()
    cost = admission.ANSWER_COST_SECONDS
    deadline = admission.ANSWER_DEADLINE_SECONDS
    depth = admission.queue_depth_within(
        deadline, answer_cost=cost, in_flight_limit=limit)

    fits = admission.total_seconds_for(depth, answer_cost=cost, in_flight_limit=limit)
    over = admission.total_seconds_for(depth + 1, answer_cost=cost, in_flight_limit=limit)

    assert fits <= deadline < over, (
        f"depth {depth}: the caller at position {depth} is answered after {fits:.1f}s and "
        f"the one at {depth + 1} after {over:.1f}s, against a {deadline}s deadline")

    # AND THE SIZE OF THE DEFECT IS PINNED. A queue sized on the wait alone is exactly one
    # full round of answers deeper, and every one of those extra positions is answered
    # after the deadline -- that set is precisely the callers the old arithmetic admitted
    # and then killed. Asserting the gap keeps the fix from being quietly undone by
    # somebody "restoring the ticket's table".
    wait_sized = int(deadline * limit // cost)
    assert wait_sized == depth + limit, (wait_sized, depth, limit)
    assert admission.total_seconds_for(
        wait_sized, answer_cost=cost, in_flight_limit=limit) > deadline


@pytest.mark.parametrize("deadline,cost,limit,expected", [
    # Issue #32's table gave 9 / ~15 / ~29 for these, sized on the queue WAIT. Each of
    # these is that number minus one full round of answers, because the budget has to cover
    # the caller's own answer too -- see total_seconds_for.
    (20.0, 12.5, 6, 3),
    (30.0, 12.5, 6, 8),
    (60.0, 12.5, 6, 22),
    # A deadline that divides exactly: the boundary position IS admitted, because it is
    # answered exactly at the deadline rather than after it.
    (25.0, 12.5, 6, 6),
    # A deadline no longer than one answer. Nobody can be queued -- but the in-flight slots
    # are still served, so this is a queue of zero rather than an outage.
    (12.5, 12.5, 6, 0),
    (1.0, 12.5, 6, 0),
])
def test_the_depth_follows_the_deadline_the_concurrency_and_the_cost(
        deadline, cost, limit, expected):
    assert admission.queue_depth_within(
        deadline, answer_cost=cost, in_flight_limit=limit) == expected


def test_a_longer_deadline_never_shrinks_the_queue():
    """Monotonic in the deadline, which is what makes the number arguable at all: raising
    the deadline is a decision to accept longer waits in exchange for refusing fewer
    people, and it must actually do that."""
    depths = [admission.queue_depth_within(d, answer_cost=12.5, in_flight_limit=6)
              for d in (5.0, 10.0, 20.0, 30.0, 45.0, 60.0)]
    assert depths == sorted(depths)
    assert depths[0] < depths[-1]


def test_the_in_flight_bound_follows_the_gateways_number_rather_than_copying_it(
        monkeypatch):
    """The bound exists to keep us inside the gateway's 8-in-flight-per-key allowance,
    operated at 6 (Brain/docs/GOTCHAS.md). Retyping that 6 here would mean the gateway team
    raising this key's limit fixes the transport and leaves the service still refusing
    people -- the exact failure the "ONE named place" criterion is about.

    *** IT MOVES THE GATEWAY'S NUMBER AND CHECKS THE BOUND FOLLOWED, because the obvious
    form of this test cannot fail. *** Asserting
    `gateway_in_flight_limit() == gateway.GATEWAY_MAX_PARALLEL` is a tautology: the
    function's body IS `return GATEWAY_MAX_PARALLEL`, so replacing it with `return 6` --
    the precise defect being guarded against -- passes it. Found by review, which is where
    this project's last three unfailable checks were found too.

    3 is chosen because it is neither the shipped 6 nor any other number in this file, so a
    constant hardcoded anywhere along the chain shows up as a mismatch rather than as a
    coincidence. And the whole chain is checked rather than just the reader: a fresh
    `Admission` given no explicit limit must pick the new number up, and must re-derive its
    queue depth from it.
    """
    from shared import gateway
    monkeypatch.setattr(gateway, "GATEWAY_MAX_PARALLEL", 3)

    assert admission.gateway_in_flight_limit() == 3
    gate = admission.Admission(deadline=30.0, answer_cost=12.5)
    assert gate.in_flight_limit == 3
    assert gate.queue_limit == admission.queue_depth_within(
        30.0, answer_cost=12.5, in_flight_limit=3)


# -- the gate under contention -----------------------------------------------------------

async def _promptly(awaitable, what):
    """Await something that must not block, and FAIL rather than hang if it does.

    Every use of this marks a spot where a broken guard would leave a coroutine waiting for
    a slot that is never coming. Mutation-testing found three of them, each of which
    deadlocked the suite instead of failing it -- correct in the sense that the mutation was
    not missed, and useless in CI.
    """
    try:
        return await asyncio.wait_for(awaitable, timeout=2)
    except asyncio.TimeoutError:                # noqa: PT017 -- the assertion IS the point
        raise AssertionError(f"{what} blocked; it must not wait at all") from None


def _gate(**kw):
    """A gate with an ABSURDLY long deadline by default, so a test about the in-flight
    bound cannot accidentally be a test about the queue depth. Every test that is about the
    depth passes its own deadline."""
    kw.setdefault("in_flight_limit", 2)
    kw.setdefault("deadline", 200.0)
    kw.setdefault("answer_cost", 12.5)
    return admission.Admission(**kw)


def test_no_more_than_the_bound_are_in_flight_at_once():
    gate = _gate(in_flight_limit=2)
    peak = 0
    live = 0

    async def work():
        nonlocal peak, live
        async with gate.slot():
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.02)
            live -= 1

    async def body():
        # `_promptly` because a leaked slot makes the six behind the first two wait
        # forever. Eight of these cost four rounds of 20ms, so the margin is enormous.
        await _promptly(asyncio.gather(*(work() for _ in range(8))),
                        "eight requests against a bound of two")

    asyncio.run(body())
    assert peak == 2, f"{peak} answers were in flight against a bound of 2"
    assert gate.peak_in_flight == 2


def test_a_request_beyond_the_bound_waits_and_is_then_served():
    """THE DEFAULT PATH, and the one almost every caller takes. A queue that refused
    instead of waiting would make a rejection a routine part of using the tool, which is
    what issue #32 was amended to stop."""
    gate = _gate(in_flight_limit=1)
    order = []

    async def work(name):
        async with gate.slot():
            order.append(f"{name}:start")
            await asyncio.sleep(0.02)
            order.append(f"{name}:done")

    async def body():
        first = asyncio.create_task(work("A"))
        await asyncio.sleep(0)              # let A take the only slot
        await _promptly(asyncio.gather(first, work("B")),
                        "a request queued behind the only slot")

    asyncio.run(body())
    # B was not refused, and it did not overlap A: it waited for the slot.
    assert order == ["A:start", "A:done", "B:start", "B:done"], order


def test_a_request_past_the_deadline_derived_depth_is_refused_at_once():
    """Refused because it cannot be served in time, not because a counter hit a limit --
    and refused ON ARRIVAL. Accepting it and failing it later is strictly worse than
    saying so immediately, which is the whole argument of the ticket."""
    gate = _gate(in_flight_limit=1, deadline=25.0, answer_cost=12.5)
    assert gate.queue_limit == 1         # one slot, and room to answer exactly one waiter

    held = asyncio.Event()
    refusals = []

    async def work():
        async with gate.slot():
            await held.wait()

    async def refused_one():
        try:
            async with gate.slot():
                pass
        except admission.Busy as busy:
            refusals.append(busy)

    async def body():
        in_flight = asyncio.create_task(work())
        await asyncio.sleep(0)
        queued = asyncio.create_task(work())    # fills the depth-1 queue
        await asyncio.sleep(0)
        await _promptly(refused_one(),          # arrives past it
                        "a request past the queue depth")
        held.set()
        await asyncio.gather(in_flight, queued)

    asyncio.run(body())
    assert len(refusals) == 1
    assert gate.refused == 1


def test_the_refusal_carries_an_estimate_drawn_from_the_actual_queue():
    """"Busy" alone reads as "broken". The service knows the depth, so the estimate is free
    -- and it is honest: it is how long the backlog in front of this caller takes to
    drain, so someone who waits that long really does find room."""
    gate = _gate(in_flight_limit=6, deadline=30.0, answer_cost=12.5)
    assert gate.queue_limit == 8             # the shipped numbers

    held = asyncio.Event()
    seen = []

    async def work():
        async with gate.slot():
            await held.wait()

    async def body():
        tasks = [asyncio.create_task(work()) for _ in range(6 + gate.queue_limit)]  # 14
        await asyncio.sleep(0)              # everyone is in flight or queued
        try:
            async with gate.slot():
                pass
        except admission.Busy as busy:
            seen.append(busy.retry_after_seconds)
        held.set()
        await asyncio.gather(*tasks)

    asyncio.run(body())
    # The refused caller would have been 9th behind six slots at 12.5s each: ~19s of queue
    # and then a ~12.5s answer, so ~31s in total, just past the 30s deadline -- exactly as
    # it must be, since position 9 being over the deadline is WHY this caller was refused.
    assert seen == [math.ceil(9 * 12.5 / 6 + 12.5)]
    assert seen[0] >= admission.ANSWER_DEADLINE_SECONDS, (
        "an estimate below the deadline sends the caller back into the same full queue")


def test_the_estimate_shrinks_with_the_queue():
    """Derived from the depth rather than being a constant wearing a derivation's clothes.
    Two different queue states must produce two different estimates, or the whole
    "estimate" is decoration."""
    gate = _gate(in_flight_limit=2, deadline=30.0, answer_cost=12.5)
    assert gate.retry_after_seconds_at(14) > gate.retry_after_seconds_at(3)
    assert gate.retry_after_seconds_at(0) >= 1      # never tells anyone to retry instantly


def test_an_idle_service_refuses_nobody_even_with_a_queue_of_zero():
    """A REAL DEFECT, caught by a service test that set a short deadline for an unrelated
    reason and got a 429 where it expected an answer.

    A deadline shorter than one answer's share of a slot makes the depth zero, which is a
    legitimate configuration -- "serve the slots, queue nobody". Refusal keyed on the queue
    alone (`queued >= 0`) is then true forever, so every caller is turned away, including
    the first one against a completely idle process, while `/health` reports it alive. The
    slots must still be served; only the queue is gone.
    """
    gate = _gate(in_flight_limit=2, deadline=0.001, answer_cost=12.5)
    assert gate.queue_limit == 0
    assert not gate.saturated

    served = []

    async def work(name):
        async with gate.slot():
            served.append(name)
            await asyncio.sleep(0.01)

    async def body():
        await _promptly(asyncio.gather(work("A"), work("B")),
                        "two callers against two free slots and no queue")
        # And the third IS refused, because there is no queue for it to join.
        with pytest.raises(admission.Busy):
            held = asyncio.create_task(work("C"))
            await asyncio.sleep(0)
            also = asyncio.create_task(work("D"))
            await asyncio.sleep(0)
            async with gate.slot():
                pass                        # pragma: no cover -- must not be reached
        held.cancel()
        also.cancel()

    asyncio.run(body())
    assert sorted(served[:2]) == ["A", "B"]


def test_an_abandoned_request_stops_consuming_capacity():
    """A CSM closing the tab must not leave a colleague queued behind an answer nobody will
    read. Async is what makes this expressible at all -- the threaded design had no way to
    notice, and no way to stop."""
    gate = _gate(in_flight_limit=1)
    served = []

    async def work(name):
        async with gate.slot():
            served.append(name)
            await asyncio.sleep(0.02)

    async def body():
        abandoned = asyncio.create_task(work("gone"))
        await asyncio.sleep(0)                  # it holds the only slot
        waiting = asyncio.create_task(work("waiting"))
        await asyncio.sleep(0)                  # and this one is queued behind it
        assert gate.queued == 1
        abandoned.cancel()
        await asyncio.wait_for(waiting, timeout=1)

    asyncio.run(body())
    assert served == ["gone", "waiting"]
    assert gate.in_flight == 0


def test_an_abandoned_request_that_was_still_queued_leaves_the_queue():
    gate = _gate(in_flight_limit=1)
    held = asyncio.Event()

    async def work():
        async with gate.slot():
            await held.wait()

    async def body():
        in_flight = asyncio.create_task(work())
        await asyncio.sleep(0)
        queued = asyncio.create_task(work())
        await asyncio.sleep(0)
        assert gate.queued == 1
        queued.cancel()
        await asyncio.sleep(0.01)
        assert gate.queued == 0, "a cancelled waiter is still counted against the depth"
        held.set()
        await in_flight

    asyncio.run(body())


def test_the_counts_are_observable_while_work_is_in_flight():
    """Enough to tell whether we have outgrown the gateway allowance. The peaks and the
    refusal count are the signal -- instantaneous numbers read at a quiet moment say
    nothing, and the interesting moment is never the one an operator is looking at."""
    gate = _gate(in_flight_limit=2, deadline=25.0, answer_cost=12.5)
    assert gate.queue_limit == 2
    held = asyncio.Event()

    async def work():
        async with gate.slot():
            await held.wait()

    async def body():
        tasks = [asyncio.create_task(work()) for _ in range(2 + gate.queue_limit)]
        await asyncio.sleep(0)
        snapshot = gate.snapshot()

        async def past_the_depth():
            with pytest.raises(admission.Busy):
                async with gate.slot():
                    pass

        await _promptly(past_the_depth(), "a request past the queue depth")
        held.set()
        await asyncio.gather(*tasks)
        return snapshot

    snapshot = asyncio.run(body())
    assert snapshot["in_flight"] == 2
    assert snapshot["in_flight_limit"] == 2
    # THE DENOMINATOR. "12 refused" is two opposite conclusions depending on whether it is
    # 12 of 12 or 12 of ten thousand, and the standard the ticket sets for a refusal --
    # rare enough that most CSMs never see one -- is a rate rather than a count. Without
    # this, the numbers cannot answer the question they exist to answer.
    assert snapshot["admitted"] == 2
    assert snapshot["queued"] == gate.queue_limit
    assert snapshot["queue_limit"] == gate.queue_limit
    assert snapshot["deadline_seconds"] == 25.0
    assert gate.snapshot()["refused"] == 1
    assert gate.snapshot()["peak_in_flight"] == 2
    assert gate.snapshot()["peak_queued"] == gate.queue_limit
    # Everyone who was let in, counted once each -- the two in flight plus the two queued
    # behind them, and NOT the one that was refused.
    assert gate.snapshot()["admitted"] == 2 + gate.queue_limit


def test_saturation_is_a_state_the_process_can_report_while_listening():
    """What `/ready` had no way to say before. The startup window is already covered by the
    port not being open; this is the other state -- listening, healthy, and unable to take
    more work."""
    gate = _gate(in_flight_limit=1, deadline=25.0, answer_cost=12.5)
    held = asyncio.Event()
    assert not gate.saturated

    async def work():
        async with gate.slot():
            await held.wait()

    async def body():
        tasks = [asyncio.create_task(work()) for _ in range(1 + gate.queue_limit)]
        await asyncio.sleep(0)
        saturated = gate.saturated
        held.set()
        await asyncio.gather(*tasks)
        return saturated

    assert asyncio.run(body()) is True
    assert not gate.saturated, "saturation must clear when the work drains"


def test_a_slot_is_released_when_the_answer_raises():
    """A fault must not cost a slot permanently. Six faults would otherwise wedge the
    service into refusing everyone while looking alive."""
    gate = _gate(in_flight_limit=1)

    async def body():
        with pytest.raises(RuntimeError):
            async with gate.slot():
                raise RuntimeError("the answerer blew up")
        assert gate.in_flight == 0

        # And the slot is genuinely reusable, not merely uncounted. `_promptly` because a
        # leaked slot makes this wait forever rather than fail.
        async def take_it_again():
            async with gate.slot():
                assert gate.in_flight == 1

        await _promptly(take_it_again(), "the slot a failed answer gave back")

    asyncio.run(body())


# -- the one number that lives in two languages ------------------------------------------

def test_the_frontend_proxy_timeout_is_set_against_this_deadline():
    """THE "ONE PLACE" CRITERION, MADE ENFORCEABLE (issue #32).

    The ticket asks that the proxy's timeout be set against the service's deadline so that
    "the number lives in one place rather than two". It cannot literally live in one place:
    the deadline is Python and the proxy is TypeScript in a separate Next.js app, and there
    is no shared config between them -- Ask Naren's only seam is the HTTP contract itself.
    So it is mirrored, and this test is what makes the mirror trustworthy instead of a
    comment promising it.

    WHY IT IS WORTH A TEST RATHER THAN A NOTE. If the proxy gives up FIRST, a CSM reads
    `service_unreachable` -- a fault, "tell someone" -- for what was really a busy moment
    or the service's own clean deadline. That is exactly the capacity-problem-wearing-a-
    quality-problem's-clothes conflation this whole ticket exists to prevent, arriving
    through the one door nothing else in the change watches. A review pointed out that
    nothing detected it.

    Pinned against SHIPPED_DEADLINE_SECONDS rather than the resolved
    `ANSWER_DEADLINE_SECONDS`, so an operator running with `ASK_NAREN_DEADLINE_SECONDS` set
    locally does not fail this. What has to agree is the two DEPLOYED numbers.
    """
    route = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "app"
             / "api" / "ask-naren" / "route.ts")
    assert route.exists(), f"the proxy this deadline is mirrored into is missing: {route}"
    source = route.read_text(encoding="utf-8")

    declared = re.search(r"const SERVICE_DEADLINE_MS = ([\d_]+);", source)
    assert declared, ("frontend/src/app/api/ask-naren/route.ts no longer declares "
                      "SERVICE_DEADLINE_MS -- if the proxy's timeout stopped being set "
                      "against this deadline, that is the finding, not this regex")
    mirrored_seconds = int(declared.group(1).replace("_", "")) / 1000
    assert mirrored_seconds == admission.SHIPPED_DEADLINE_SECONDS, (
        f"the proxy mirrors a {mirrored_seconds}s deadline against the service's "
        f"{admission.SHIPPED_DEADLINE_SECONDS}s one")

    # And its abort must be LATER than the deadline, not merely equal: a response the
    # service produced at the deadline still has to reach the browser.
    timeout = re.search(r"const TIMEOUT_MS = SERVICE_DEADLINE_MS \+ ([\d_]+);", source)
    assert timeout, ("route.ts no longer derives TIMEOUT_MS from SERVICE_DEADLINE_MS, so "
                     "the proxy's abort is no longer set against the deadline at all")
    assert int(timeout.group(1).replace("_", "")) > 0
