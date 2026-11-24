"""The endpoints: `/ask`, `/health` (and its `/healthz` alias), `/ready` and `/verify`.

Thin on purpose. What `/ask` does beyond parsing -- the slot, the deadline, noticing a
caller who left -- is `answer_flow`, and every way it can say no is `refusals`.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ask_naren.api.answer_flow import admit_and_answer, unless_abandoned
from ask_naren.api.dependencies import (AnswererDep, GateDep, ReadyDep, SetupDep,
                                        VerifierDep)
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


@router.get("/verify", summary="Check the database and vectors this process answers from",
            response_model=None,
            responses={200: {"description": "Every check passed, or the store is one this "
                                            "endpoint does not verify (`not_applicable`)."},
                       404: {"description": "`not_configured`: built without a verifier."},
                       503: {"description": "`failed`: at least one check failed; each "
                                            "check says why."}})
async def verify(verifier: VerifierDep) -> JSONResponse:
    """VERIFICATION, for an operator after a database move (ask_naren/verification.py).

    Which database and user, read-only or not, pgvector's version, table counts, that every
    answerable exchange has a vector of the right width, and that sampled stored vectors find
    themselves. NOT a probe: it runs real queries and a few searches, so never wire it to a
    liveness or readiness check. It takes no admission slot -- an operator checking a
    saturated service must still get an answer -- and reveals no credentials.
    """
    if verifier is None:
        return JSONResponse({"status": "not_configured"}, status_code=404)
    ok, report = await verifier()
    return JSONResponse(report, status_code=200 if ok else 503)


_NOT_FOUND = {"detail": "Not Found"}


def _setup_refusal(jobs, request: Request) -> "JSONResponse | None":
    """OFF looks exactly like a route that does not exist; ON needs the bearer token."""
    if jobs is None:
        return JSONResponse(_NOT_FOUND, status_code=404)
    if not jobs.authorised(request.headers.get("authorization")):
        return JSONResponse({"status": "unauthorised"}, status_code=401)
    return None


@router.post("/admin/setup/{step}", include_in_schema=False)
async def start_setup(step: str, request: Request, jobs: SetupDep) -> JSONResponse:
    """Start a database setup step in the background (ask_naren/db/setup.py).

    404 unless ASK_NAREN_SETUP_TOKEN is set; 401 without `Authorization: Bearer <token>`;
    202 started; 409 while a step is already running. Takes no admission slot. Only ever
    FILLS AN EMPTY database -- it cannot wipe or overwrite one, whoever holds the token.
    """
    if (refusal := _setup_refusal(jobs, request)) is not None:
        return refusal
    from ask_naren.db.setup import STEPS
    if step not in STEPS:
        return JSONResponse({"status": "unknown_step", "steps": list(STEPS)}, status_code=400)
    if not jobs.start(step):
        return JSONResponse({"status": "busy", **jobs.snapshot()}, status_code=409)
    return JSONResponse({"status": "started", "step": step,
                         "follow": "GET /admin/setup"}, status_code=202)


@router.get("/admin/setup", include_in_schema=False)
async def setup_status(request: Request, jobs: SetupDep) -> JSONResponse:
    """The running or last setup step: status, log lines, result or error."""
    if (refusal := _setup_refusal(jobs, request)) is not None:
        return refusal
    return JSONResponse(jobs.snapshot())


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
