"""Ask Naren's HTTP boundary: one endpoint, plus liveness and readiness.

    app.py           build_app -- assembles everything below, and the lifespan
    server.py        serve -- one uvicorn, in this process (ADR 0010)
    routes.py        /ask, /health, /healthz, /ready
    answer_flow.py   the slot, the deadline, and noticing a caller who left
    admission.py     how many are answered at once, and how deep the queue is
    refusals.py      busy / deadline / fault -- the declines this layer writes
    handlers.py      exception handlers: the 400, the JSON 404, the refusals
    middleware.py    the streaming body cap, the trailing-slash normaliser
    models.py        the Pydantic request and response models (/docs)
    dependencies.py  the answerer, readiness check and gate, as FastAPI dependencies

Callers import from here: `api.build_app`, `api.serve`, and the names in `__all__`.

A FASTAPI APPLICATION ON UVICORN (2026-09-29).

It began as the stdlib `http.server` (ADR 0003), became a raw ASGI app with no framework in
issue #31 ("there is nothing here a framework would do"), and is now FastAPI -- the operator's
decision, reversing #31's, so the service follows Joveo's applib convention and its contract
is a schema at `/docs` rather than prose. The request is a Pydantic model (`AskRequest`), the
responses are documented models (`models.py`), the routes are an `APIRouter`,
the gate and the answerer are dependencies, and every way of saying no is an exception with
a handler.

WHAT THE CALLER SEES DID NOT MOVE, and three decisions are what keep it that way:

  * A BODY THAT FAILS VALIDATION IS A 400, NOT FASTAPI'S 422. The frontend's proxy leaves
    validating `situation` to this service and forwards its 400 as its own (route.ts), and
    it keys "answered nothing, do not record" on 400 (#37), as its own invalid-body answers
    are. A 422 would be a third status meaning the same thing. So a
    `RequestValidationError` handler answers `{"error": ...}` with 400, as before.
  * THE 64 KB CAP IS ENFORCED WHILE THE BODY STREAMS IN, by `middleware.BodyCap`, an ASGI middleware
    in front of FastAPI. FastAPI buffers the whole body before any dependency runs, so a cap
    anywhere inside it would be checked after the memory was already spent.
  * ANYTHING UNROUTED IS A JSON `{"error": "not found"}` 404 -- including a wrong method,
    which FastAPI would call a 405 -- and `/ask/` is `/ask` rather than a redirect, because a
    redirected POST arrives as a GET.

The one visible difference is the JSON's whitespace: responses are FastAPI's compact JSON
rather than `json.dumps`'s default separators. Nothing parses whitespace.

STILL ONE PROCESS, ONE EVENT LOOP (ADR 0010). FastAPI changes nothing about that: the
gateway's in-flight budget belongs to the API key, and the admission gate here is the only
thing enforcing it.

WHAT CHANGED FOR A CSM: ABOUT SIX OF THEM ARE ANSWERED AT ONCE, and the rest wait in a
bounded queue rather than being accepted and left to contend. Requests overlap while they
wait on the gateway, which is where essentially all of an answer goes.

*** SIX IS THE CEILING AND IT IS NOT OURS TO RAISE. *** It is the gateway's 8 requests in
flight per API KEY -- shared across chat and embeddings -- operated at 6 so a retry has
somewhere to go. Because that budget belongs to the key rather than the process, running a
second process does not double capacity; it violates one budget twice while looking healthy.
So the process count is part of the correctness argument, which is the whole subject of
ask-naren/docs/adr/0010-ask-naren-answers-concurrently-in-one-asyncio-process.md.

Behind those six, issue #32's `admission.py` holds a queue as deep as the request
deadline can absorb, refuses anyone past it immediately with an estimate rather than late
with nothing, and enforces the deadline on whoever it admits.

NO LATENCY FIGURE IS QUOTED HERE, deliberately: an answer's cost has been observed moving by
several times between runs, so any number written into this docstring is stale within a day
and checkable against nothing. The harnesses in ask-naren/audit/ measure it and write the
result to that directory's artifacts/ -- check_concurrent_service.py for overlap,
check_admission_live.py for the bound, the queue and the deadline.

WHAT CHANGED FOR AN OPERATOR: `/health` no longer queues behind an in-flight generation.
That was not cosmetic -- with a normal ingress health-check timeout it marked a healthy
process dead during EVERY answer, then flapped and killed it, which is why this service
could not be deployed behind a load balancer at all, even for one user.

KEEP-ALIVE IS ALLOWED AGAIN, and the `Connection: close` header is gone. ADR 0003 forced it
because keep-alive on a SERIAL server is a self-inflicted outage: the accept loop blocked in
`handle_one_request` on an idle socket and the next CSM's question waited on a connection
nobody was using (measured -- one lingering client made every subsequent request time out).
That failure mode is a property of serialisation and disappeared with it; an idle connection
now occupies no worker, while a fresh handshake per question is pure cost. The test that
caught the original defect still runs, with the same assertion and a new reason.

IT NOW DECIDES WHO IS ANSWERED, WHICH IS A DELIBERATE ADDITION AND NOT A DRIFT (issue #32).
The bound the async chain removed had to be put back: the real ceiling is the gateway's 8
requests in flight per API key, operated at 6, so accepting thirty simultaneous questions
means thirty people contending for six slots and everyone waiting about a minute -- WORSE
for the people at the front than the serial server was. So `/ask` takes a slot from
`admission.py`, waits for one if they are all busy (the default path, and what
almost every caller does), and refuses on arrival only when the queue is already as deep as
the deadline can absorb. The arithmetic is there; the statuses, reason codes and CSM-facing
sentences are here, because this is the layer that writes what a CSM reads.

A request also has a DEADLINE now, measured from arrival so it covers the wait as well as
the work, and an ABANDONED request is cancelled -- a CSM closing the tab releases their slot
or leaves the queue instead of making a colleague wait behind an answer nobody will read.
That last one is only expressible because of #30/#31: the threaded design had no way to
notice a vanished caller and no way to stop the work.

WHAT THIS LAYER STILL DOES NOT DO: no reshaping. Whatever the answerer decided is what the
caller reads -- retrieval, grounding and model-calling all live in one place, and it is not
here. Admission is not an exception to that: it decides WHETHER the answerer runs, never
what it says.
"""

from ask_naren.api.app import build_app
from ask_naren.api.dependencies import Answerer, ReadyCheck
from ask_naren.api.middleware import MAX_BODY_BYTES
from ask_naren.api.refusals import (DEADLINE_EXCEEDED, SERVICE_BUSY, SERVICE_ERROR,
                                    DeadlineExceeded, Refusal, ServiceBusy, ServiceFault)
from ask_naren.api.server import DEFAULT_HOST, DEFAULT_PORT, serve

__all__ = [
    "build_app", "serve", "DEFAULT_HOST", "DEFAULT_PORT", "MAX_BODY_BYTES",
    "Answerer", "ReadyCheck",
    "Refusal", "ServiceBusy", "DeadlineExceeded", "ServiceFault",
    "SERVICE_ERROR", "SERVICE_BUSY", "DEADLINE_EXCEEDED",
]
