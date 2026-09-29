"""One question under a bound, a deadline and a watcher (issue #32): the part of `/ask` that
is not parsing.

`routes.ask` calls these in one line; the order they run in is the design and is written
up in its docstring.
"""
from __future__ import annotations

import asyncio
import contextlib
import sys
import traceback
from typing import Awaitable

from ask_naren.api import admission
from ask_naren.api.dependencies import Answerer
from ask_naren.api.refusals import DeadlineExceeded, Refusal, ServiceBusy, ServiceFault


async def unless_abandoned(work_coro: Awaitable[dict], receive) -> dict | None:
    """The answer, or None if the caller left first. A `Refusal` from the work propagates
    to its handler.

    `asyncio.wait` rather than `gather`: we need to know WHICH of the two finished, and the
    loser must be cancelled and awaited rather than left to surface later as an
    unretrieved-task warning.
    """
    abandoned = asyncio.create_task(wait_for_disconnect(receive))
    work = asyncio.ensure_future(work_coro)
    try:
        done, _ = await asyncio.wait({work, abandoned}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Also on OUR cancellation (a server shutting down mid-answer): neither task may
        # outlive the request.
        for task in (work, abandoned):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    if work not in done:
        # THE CALLER IS GONE. Cancelling (above) is what released the slot or dropped us out
        # of the queue -- `Admission.slot`'s teardown is await-free precisely so it
        # completes inside a cancellation.
        return None
    return work.result()


async def admit_and_answer(answerer: Answerer, situation: str, thread: tuple,
                            gate: "admission.Admission") -> dict:
    """Take a slot and answer -- or raise the `Refusal` that says why not.

    Every exit is the answer or one of the three refusals; nothing else escapes, because a
    CSM must never see a traceback.
    """
    # The deadline object is bound so `expired()` can be asked afterwards. A `TimeoutError`
    # is NOT proof that our budget ran out -- anything underneath us may raise one, and in
    # 3.11 `asyncio.TimeoutError` IS the builtin `TimeoutError`, an `OSError`. Treating
    # every TimeoutError as ours would report a gateway socket timeout as "we ran out of
    # time": a fault mislabelled as a capacity event, which is exactly the conflation this
    # ticket exists to prevent, one layer further down.
    budget = asyncio.timeout(gate.deadline)
    try:
        async with budget:
            try:
                async with gate.slot():
                    return await answerer(situation, thread)
            except admission.Busy as busy:
                print(f"[ask-naren] busy: refused a question with {gate.queued} queued "
                      f"and {gate.in_flight} in flight ({gate.refused} refused so far)",
                      file=sys.stderr, flush=True)
                raise ServiceBusy(busy.retry_after_seconds) from None
    except Refusal:
        raise
    except TimeoutError:
        if budget.expired():
            # The only timeout before this was the gateway's 120s, and no CSM waits 120s.
            # Counted, because a rising number here means the cost estimate the depth is
            # sized from has drifted, and the depth is now admitting people it cannot serve.
            gate.note_deadline_missed()
            print(f"[ask-naren] deadline: gave up after {gate.deadline:.0f}s "
                  f"({gate.deadlines_missed} so far)", file=sys.stderr, flush=True)
            raise DeadlineExceeded() from None
        traceback.print_exc(file=sys.stderr)
        raise ServiceFault() from None
    except Exception:                     # noqa: BLE001 -- a CSM must never see a traceback
        traceback.print_exc(file=sys.stderr)
        raise ServiceFault() from None


async def wait_for_disconnect(receive) -> None:
    """Return once the client has gone.

    ASGI reports a vanished caller by handing `http.disconnect` to the next `receive()`, so
    noticing means having a `receive()` outstanding -- which is why this is a task of its
    own rather than a check somewhere. Calling `receive()` again after the body is complete
    is safe, and is what Starlette's `is_disconnected` does: a keep-alive connection's NEXT
    request cannot arrive as an event on this one, because HTTP/1.1 will not begin it until
    this response is finished.
    """
    while True:
        if (await receive())["type"] == "http.disconnect":
            return
