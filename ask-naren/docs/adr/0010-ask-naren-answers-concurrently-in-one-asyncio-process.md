# Ask Naren answers concurrently in one asyncio process, and the process count is load-bearing

Supersedes `0003-the-service-is-single-threaded-on-purpose.md`.

ADR 0003 decided the service would serve requests one at a time, and gave two independent
reasons. Issues #28–#32 reversed that decision. One of 0003's reasons turned out to be
**right about the constraint and wrong about the fix**; the other **still holds and was
honoured**. This records what actually happened, in that order, because a reader who cannot
tell those two halves apart will either go and fix a non-problem or undo the half that is
still live.

It lands after the code rather than before it, and it therefore records some things that
turned out differently from the plan — including a piece of arithmetic in issue #32's own
ticket that was wrong.

## Why concurrency became necessary

Not throughput. **`/health` queued behind every generation.**

ADR 0003 named that consequence and accepted it: "`/health` queues behind an in-flight
generation, and total throughput is one question at a time. For the current audience that is
acceptable." What it did not follow through to is that this is a **deploy blocker**, not a
comfort. With a normal ingress health-check timeout, a healthy process is marked dead during
*every single answer*, then flapped and killed. The service could not sit behind a load
balancer at all — not even for one user asking one question at a time, which is the
configuration 0003 was optimising for.

The throughput argument is real but secondary: six CSMs asking at once used to mean the
sixth waited for the five in front, and the tool is for people mid-client-call.

## Where ADR 0003 was wrong about the fix

0003's closing line: *"If Ask Naren ever needs concurrency, the blocker to remove first is
the embed cache's thread affinity, not the choice of server."*

The constraint was correctly identified and is **still true today**:
`shared/embed_cache.py` opens SQLite with a bare `sqlite3.connect(path)`, no
`check_same_thread=False`, so a second thread touching that connection raises outright.

The prescription was wrong. Issue #30 did not make that cache thread-safe, and did not pin
embedding to a worker thread. It **routed the request path around
`preprocessing/embedder.py` entirely**, so `_cache_for_backend()` is never called and the
connection that raises is never constructed. There is no thread-bound object in the request
path to be unsafe about. Nothing in `shared/` was edited, so no other Brain consumer was
touched.

And nothing was lost by skipping the cache: **a live CSM situation is a novel string and
therefore a guaranteed miss.** The cache would have paid a SQLite write for a hit that never
comes. It stays enabled everywhere it earns its keep — the pipeline, and this service's own
startup path, which embeds thousands of triggers on a cold rollback.

The general lesson, and the reason this paragraph is in an ADR rather than a commit message:
**0003 asked "how do we make this component safe under concurrency" when the available move
was "do not put that component in the concurrent path."** A constraint being real does not
make the fix it suggests the right one.

## What survived, and was honoured

0003's second reason: *"There is nothing here a framework would do. One JSON POST and one
health GET. Adding `fastapi` and `uvicorn` to Brain's venv to route two paths is cost without
benefit."*

The `fastapi` half stood and was respected when this ADR was written: the application was a
plain `async def app(scope, receive, send)` doing its own routing.

> **REVERSED 2026-09-29, by the operator.** The service is now a FastAPI application: a
> Pydantic request model, documented response models (`Brain/ask_naren/api_models.py`), an
> `APIRouter`, dependencies for the gate and the answerer, and exception handlers for every
> refusal. The reason is the one 0003 was not weighing: a contract readable as a schema at
> `/docs`, and a service shaped like Joveo's other applib services. What the frontend sees
> did not move -- a malformed body is still a 400 (a handler overrides FastAPI's 422), the
> 64 KB cap is still enforced while the body streams (an ASGI middleware in front of
> FastAPI), and anything unrouted is still a JSON 404. **None of this touches the decision
> below: one process, one event loop, never `--workers`.** FastAPI is an application
> framework; the budget argument is about processes.

The `uvicorn` half is overridden deliberately. That dependency is what buys concurrency, and
0003 was weighing it against *routing two paths* rather than against *answering more than one
CSM at a time*. It is a server, not a framework, and it is the only dependency the whole
chain added.

`Connection: close` is also gone, and 0003 reversed itself on its own terms: it said not to
undo it "without first removing the single-threading constraint", which is exactly what
happened. Keep-alive on a serial server is a self-inflicted outage — the accept loop blocks
on an idle socket and the next caller waits on a connection nobody is using. That failure
mode is a property of serialisation and disappeared with it. The test that caught the
original defect still runs, with the same assertion and a new reason.

## What we decided

**Concurrency by asyncio, inside exactly one process, with one event loop for the life of
that process.**

All three clauses are load-bearing, and the third is the one most likely to be broken by
accident.

### The constraint that decides it: the gateway's limits are per API KEY

This is the fact everything else follows from, and it is measured rather than assumed.

The gateway enforces `max_parallel_requests = 8`, and **that budget is shared across
`/chat/completions` and `/embeddings`** — it is a property of the key, not of an endpoint.
Measured 2026-09-10 against the production gateway with a direct async client and no retry
ladder, so nothing absorbed the rejections:

| what was fired | result |
| --- | --- |
| 1, 2, 4, 6, 8 concurrent chat completions | all clean |
| 10 concurrent chat completions | **2 rejected**, `max_parallel_requests` |
| 6 chat **+** 6 embed together (12 in flight) | **9 ok, 3 rejected** |

The transport clamps itself to **6 of that 8**, and the two spare slots are not slack: a
retry is itself a request, so operating *on* the ceiling leaves a rejection nowhere to go. A
corpus fetch run at exactly 8 survived 70 minutes and 7,200 of 7,472 vectors before losing
all four retries inside one window and hard-failing.

The clamp is a **module-level** primitive, for exactly this reason: the limit belongs to the
key, so every client in the process must share one counter.

### Considered and rejected: several processes

The ordinary way to scale a Python web service — gunicorn workers, or N replicas behind the
ingress.

**Rejected because it violates the gateway's budget by construction, and cannot be made not
to.** Each process gets its own module-level limiter and semaphore, each politely stays under
the cap it believes it owns, and together they run at N×6 against a real ceiling of 8. There
is no coordination available: the limiter is in-process state, there is no shared store in
this deployment, and adding one means operating a distributed rate limiter for an internal
tool that uses a single API key.

So **the process count is not a deployment detail — it is part of the correctness
argument.** Anyone scaling this service horizontally must obtain more key allowance first,
or shard across several keys with the limiter keyed per key. That is a conversation with the
gateway team, not a change to a process count.

### Considered and rejected: threads

`ThreadingHTTPServer`, or a thread pool, which is what ADR 0003 itself contemplated.

Two reasons, and the second is the stronger one:

1. **It walks straight into the hazard 0003 named.** The embed cache's thread-bound SQLite
   connection is still thread-bound. Threads would require fixing `shared/` for every Brain
   consumer to serve one CSM-facing endpoint — the cost 0003 correctly refused to pay. One
   thread sidesteps it rather than paying it.
2. **The work is a network wait, which is what async is for.** Essentially all of an answer's
   duration is spent waiting on the gateway; there is no CPU-bound section for threads to
   parallelise. Threads would add locking obligations around the module-level limiter and the
   admission counters in exchange for nothing. Under one event loop, a coroutine cannot be
   interrupted between two statements that do not await, so those counters need no lock at
   all — a real simplification, not a stylistic one.

### Considered and rejected: an `asyncio.run` per request

Tempting as an incremental step, and it existed for exactly one ticket (#30) as a bridge
while the server was still the blocking stdlib one.

**Rejected, and it is the trap worth writing down, because it fails silently.** The async
gateway client's limiter and semaphore are keyed on the **running loop** — an asyncio
primitive raises if awaited from a loop other than the one it bound to. A process wrapping
each request in its own `asyncio.run` therefore gets a *fresh* limiter every time, so
admission control degrades from per-key to **per-request, i.e. unbounded**, while every
health check passes and every log line looks normal. It would look perfectly healthy right
up to the point the gateway started rejecting.

One `asyncio.run` around the whole of `main()` in `Brain/ops/serve_ask_naren.py` is what
guarantees this, and issue #31 is what made it possible: with an ASGI server, uvicorn runs
*inside* our loop instead of blocking it, so there is no blocking `serve_forever` to work
around and no per-request bridge to maintain.

## The ceiling, and what issue #32 built on top of it

Removing the serial brake created a problem the serial design could not have: the service
says yes to everyone. Thirty simultaneous questions were all accepted, contended for six
slots, and each took about a minute — **worse for the people at the front than the serial
server had been.**

Issue #32 put a deliberate brake back, in `Brain/ask_naren/admission.py`:

- **six answers in flight**, read from the transport's own `GATEWAY_MAX_PARALLEL` rather than
  retyped, so raising the key's allowance raises the service's bound in the same breath;
- **a whole-request deadline of 30 seconds** — a product decision about how long a CSM
  mid-call will wait before "no answer" beats "still waiting", and the only chosen number in
  the design;
- **a queue sized by what that deadline can absorb**, computed rather than picked;
- **a busy refusal** (HTTP 429, reason `service_busy`, with an estimate) for a caller who
  arrives past that, returned on arrival rather than after a wait;
- **`/ready` reporting saturation**, which is a state it had no way to express before.

### Where issue #32's own ticket was wrong, since this ADR records what happened

The ticket's table sized the queue by **how long the person at the back waits** — a 30s
deadline giving a queue about 15 deep. That is wrong, and the first implementation reproduced
it faithfully.

A caller admitted at position 15 waits nearly the whole 30s budget **and then still needs
their own answer.** Every position in the final round was therefore guaranteed to be killed
by the very deadline it had just been admitted under — which is "accepted and failed later",
the one behaviour the ticket forbids in as many words. Sizing on *when the caller actually
has an answer in hand* gives a queue **8 deep behind 6**, and the discarded difference is
exactly one round of answers.

**No offline test could have caught it**, and that is the transferable part: a stubbed
answerer returns instantly, so the queue's tail always fits inside any deadline. It took a
live burst against a slow gateway, which returned three `504 deadline_exceeded` responses
with every other count correct. `ask-naren/audit/check_admission_live.py` is that check.

## Capacity, stated plainly and without over-promising

- **About six concurrent answers.** This is the structural number and the one to trust: it is
  the key's allowance, minus headroom for retries.
- **Roughly 29 generating answers per minute** — six at a time at the per-answer cost the
  queue is sized from. Treat this as a planning figure, not a measurement: it moves with that
  cost, and the cost has been observed varying by several times between runs on the same
  machine. Deliberately no latency figure is quoted anywhere in this repo's documentation for
  that reason; the measured numbers are written to `ask-naren/audit/artifacts/` by the
  harnesses and re-measured on demand.
- **Most questions are cheaper than that suggests, though none is free.** Thirteen of the
  nineteen intents are **rendered** — assembled from stored rows rather than generated — so
  none of them reaches the generation budget. Be precise about what that does and does not
  save: eleven of those thirteen are still in `intake.RETRIEVING_INTENTS` and embed a query,
  which is a second gateway call against the *same* per-key budget, and only `discovery` and
  `frequency` search nothing at all. And every request holds one of the six admission slots
  for its whole life whatever its intent. What rendered buys is the expensive call, not the
  slot. A queue therefore only builds if *generating* questions keep arriving faster than
  they are answered, which at this team's size means every CSM asking one every eighty
  seconds without pause.
- **The honest bad case: thirty simultaneous generating requests still means the last person
  waits about a minute** — except that as of #32 they are told so immediately instead, with
  an estimate, because a queue that deep exceeds the deadline. That is the trade #32 chose:
  the wait did not get shorter, the lie got shorter.
- **This ceiling does not move by deploying more of anything.** See "Considered and rejected:
  several processes".

## Consequences

- **Horizontal scaling is unavailable until the key's allowance changes.** Not hard —
  *unavailable*: adding a second process makes the service violate the gateway's budget while
  appearing to work. This is the single most important line in this ADR for anyone operating
  the service.
- **One event loop is an invariant, not a preference.** Breaking it silently removes
  admission control. `Brain/ops/serve_ask_naren.py` carries the reasoning at the
  `asyncio.run` call; `Brain/docs/GOTCHAS.md` carries it for the transport.
- **A CSM at the edge of capacity gets a sentence, not a spinner.** The three ways of saying
  no — fault, busy, no-close-match — are kept distinct in the HTTP status, the reason code
  and the words on screen, because a capacity problem wearing a quality problem's clothes
  would make the tool look like it was working and simply declining a lot.
- **The proxy's timeout is now set against the deadline** rather than being a second,
  independent budget. It is mirrored in TypeScript because there is no shared config between
  the service and the Next.js app, and a test pins the mirrored deadline CONSTANT equal while
  requiring the proxy's actual abort to fall a few seconds LATER. Do not read that as "set
  them equal": a proxy that fires at the same instant can beat the service to its own clean
  deadline, and what a CSM then reads is `service_unreachable` — a fault, "tell someone" —
  for what was really a capacity event. The margin is the point, and the test enforces both
  halves.
- **Ctrl-C teardown had to move into the ASGI lifespan.** `asyncio.run` installs a SIGINT
  handler that cancels the main task and uvicorn re-raises the signal into it, so a `finally`
  around `serve()` is already cancelled when it tries to close the gateway client. This is
  cheap to get wrong and invisible when wrong — the client and the Pinecone session simply
  leak.

## What would change this

- **A raised `max_parallel_requests` on this key.** The bound reads the transport's constant,
  so the service follows automatically; the queue depth re-derives from it.
- **Sharding across several API keys**, with the limiter keyed per key rather than per module.
  That is the only route to more than one process, and it is a real piece of work rather than
  a configuration change.
- **A gateway that queued on our behalf**, which would make most of this ADR unnecessary.

## What this does NOT establish

**That a single answer got faster.** One person asking one question sees no change from any
of #28–#32 — the whole chain is about how many people can be served at once and what happens
to the ones who cannot be. Making an individual answer faster is issue #10, still open and
untouched by all of this.

**That the service is now horizontally scalable.** It is deliberately and specifically not,
for the reason above. Concurrency and scalability are different properties and this chain
delivered exactly one of them.
