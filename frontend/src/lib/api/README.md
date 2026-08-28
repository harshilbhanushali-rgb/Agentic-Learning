# The frontend / backend boundary

The UI talks to exactly one interface: `ApiClient` in [`types.ts`](./types.ts).
Two implementations exist.

| File | Owner | Status |
|---|---|---|
| `mock.ts` | frontend | done — fed by `src/data`, streams, can fail on demand |
| `http.ts` | backend  | stub — every method throws |

Switch between them with one env var:

```bash
NEXT_PUBLIC_API_MODE=mock   # default, no server required
NEXT_PUBLIC_API_MODE=live   # uses http.ts
```

## For whoever builds the backend

Implement `ApiClient` in `http.ts`. Nothing else in the frontend changes —
no component imports an adapter directly, and no `fetch` exists outside
that file.

**`sendMessage` must actually stream.** The UI renders tokens as they
arrive and shows retrieval sources before the first token. An
implementation that buffers the whole reply and yields it once will
type-check and still look broken.

Suggested transport — SSE over POST, since `EventSource` cannot POST:

```
POST /chat/sessions/{id}/messages
Accept: text/event-stream

event: retrieval
data: {"sources":[{"id":"r1","label":"QBR Mastery","kind":"module","matches":4}]}

event: token
data: {"text":" Open"}

event: citation
data: {"citation":{"id":"c1","label":"QBR Mastery · Module 2 · §1.1","kind":"module"}}

event: done
data: {"messageId":"msg_123"}
```

Event order is `retrieval → token* → citation* → done`. An `error` event may
arrive at any point and terminates the stream. Honour `args.signal` so that
cancelling a reply actually closes the connection.

Citations are structured events, not markers inside the answer text — the UI
never parses prose to find them.

### Note on the Brain

`Brain/` is a batch pipeline: it reads transcripts from disk and runs
clustering for minutes. Chat needs a *query* path — Pinecone retrieval plus
synthesis, answering in seconds. The retrieval primitives exist
(`shared/pinecone_store`) but no interactive endpoint does. That is likely
the longest pole in this project.

## Exercising the mock

The mock is deliberately slow and fallible, so the UI keeps its loading and
error states honest. Tune it from the browser console:

```js
__oracle.latency = 1200  // ms before first byte
__oracle.speed   = 8     // ms between tokens
__oracle.fail    = true  // next reply errors a third of the way in
```

Questions with scripted answers: QBR openings, ROI/CPH benchmarks, and the
"we have internal tools" objection. Anything else hits a fallback.
