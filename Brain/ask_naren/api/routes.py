"""The four endpoints: `/ask`, `/health` (and its `/healthz` alias) and `/ready`.

Thin on purpose. What `/ask` does beyond parsing -- the slot, the deadline, noticing a
caller who left -- is `answer_flow`, and every way it can say no is `refusals`.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ask_naren.api.answer_flow import admit_and_answer, unless_abandoned
from ask_naren.api.dependencies import AnswererDep, GateDep, ReadyDep
from ask_naren.api.models import AskRequest, AskResponse, Declined, Error, Health, Readiness

router = APIRouter()

_DECLINE = {"model": Declined}


@router.get("/health", response_model=Health, summary="Liveness")
@router.get("/healthz", response_model=Health, summary="Liveness (the applib probe spelling)")
async def health() -> dict:
    """LIVENESS. Awaits nothing, so it cannot queue behind an answer no matter how many are
    in flight. Deliberately says nothing about readiness: an ingress restarting a
    busy-but-healthy process is the failure this endpoint exists to prevent.

    TWO SPELLINGS, ONE ANSWER. `/health` is this service's own contract and what the audit
    harnesses poll; `/healthz` is what the Joveo applib template's probes expect.
    """
    return {"status": "ok"}


@router.get("/ready", response_model=Readiness, summary="Readiness and saturation",
            responses={503: {"model": Readiness,
                             "description": "`starting`, or `saturated`: alive and healthy, "
                                            "but the queue is as deep as the deadline can "
                                            "absorb."}})
async def ready(gate: GateDep, is_ready: ReadyDep) -> JSONResponse:
    """READINESS, AND SATURATION (issue #32). "Saturated" is alive, healthy, answering as many
    as it can, and unable to take another without breaking the deadline -- the QUEUE behind
    the busy slots is as deep as the deadline can absorb. The counts ride along on all three
    answers, because the peaks and the refusal count are how an operator tells whether we
    have outgrown this API key's allowance."""
    if not is_ready():
        return JSONResponse({"status": "starting", **gate.snapshot()}, status_code=503)
    if gate.saturated:
        return JSONResponse({"status": "saturated", **gate.snapshot()}, status_code=503)
    return JSONResponse({"status": "ready", **gate.snapshot()})


@router.post(
    "/ask",
    summary="Answer one situation",
    response_model=None,
    responses={
        200: {"model": AskResponse,
              "description": "An answer, a rendered answer, a clarify, or a decline. A "
                             "`no_close_match` decline is a 200: it is the tool working "
                             "correctly, not an error."},
        400: {"model": Error, "description": "The body could not be read: not JSON, no "
                                             "`situation`, a blank one, a malformed "
                                             "`thread`, or over 64 KB. Costs no slot."},
        429: {**_DECLINE, "description": "`service_busy`: refused on arrival, with "
                                         "`Retry-After`.",
              "headers": {"Retry-After": {"schema": {"type": "integer"},
                                          "description": "Seconds until there is room."}}},
        503: {**_DECLINE, "description": "`service_error`: a fault on our side."},
        504: {**_DECLINE, "description": "`deadline_exceeded`: admitted, then ran out of "
                                         "time."},
    },
)
async def ask(body: AskRequest, request: Request, gate: GateDep,
              answerer: AnswererDep) -> Response:
    """One question, under a bound and a deadline, and abandonable (issue #32).

    THE ORDER OF THE THREE THINGS HERE IS THE DESIGN:

      1. The body is read and validated FIRST -- by FastAPI, before this function runs. A
         malformed request is a 400 that costs no slot: it would be perverse to queue
         someone behind a request that was never going to be answered, and worse to refuse
         them as "busy" because of it.

      2. The disconnect watcher starts BEFORE the slot is taken, not after. That ordering is
         the whole of the abandonment criterion: the expensive case is a CSM who closed the
         tab while still QUEUED, and a watcher started after admission would not notice them
         until they were already being answered. Started here, they simply leave the queue
         and the colleague behind them moves up.

      3. Admission and the answer run inside ONE deadline that starts at arrival, so the
         budget covers the wait as well as the work. A deadline measured from admission
         would be a promise about the part we control instead of about what a CSM
         experiences, and the queue depth is derived from the whole-request figure.

    The answerer's response is sent AS IT COMPOSED IT, not through `AskResponse` -- see
    `models` for why the response models document rather than filter.
    """
    answer = await unless_abandoned(
        admit_and_answer(answerer, body.situation, body.turns(), gate), request.receive)
    if answer is None:
        # THE CALLER IS GONE. Nothing useful can be sent; this empty response exists only
        # so the framework has something to return on a socket that no longer exists.
        return Response(status_code=499)
    return JSONResponse(answer)
