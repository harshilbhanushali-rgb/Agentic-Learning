/**
 * Same-origin proxy to the Ask Naren service (issue #3).
 *
 * WHY A PROXY AT ALL. The service is an internal, stdlib `http.server` bound to localhost
 * (Brain/ask_naren/service.py). Pointing the browser straight at it would mean exposing it
 * beyond localhost and adding CORS to a stdlib handler that has no framework to do it. A
 * same-origin route keeps the service where it is.
 *
 * THIS FILE RESHAPES NOTHING. The body goes out as received and the response comes back
 * byte-for-byte with its status, so `AskNarenResponse` in src/types.ts describes ONE
 * contract rather than the frontend's idea of it. No retrieval, grounding or model-calling
 * logic lives here or anywhere else in the frontend -- that is the service's job, in one
 * place. Parsing the JSON here just to re-serialise it would be a second place where the
 * shape could drift.
 *
 * SCOPE. A service that answers -- including its own decline-shaped 503 -- is handled. A
 * service that is not RUNNING is issue #6's ticket: the fetch below rejects and Next
 * returns a 500, which the page renders as a plain line rather than a crash, but making
 * that read as a proper decline is #6's job and is deliberately not done here.
 */
import type { NextRequest } from 'next/server';

/** Matches the service's own DEFAULT_HOST/DEFAULT_PORT. Overridable for a non-local
 *  deployment without touching code. */
const SERVICE_URL = process.env.ASK_NAREN_SERVICE_URL ?? 'http://127.0.0.1:8787';

const JSON_HEADERS = { 'Content-Type': 'application/json; charset=utf-8' } as const;

export async function POST(request: NextRequest) {
  // Forwarded as text, not as a parsed-and-re-serialised object: the service does its own
  // validation of `situation` (non-empty string, body size cap) and returns a 400 with its
  // own message. Validating here too would put that rule in two places.
  const body = await request.text();

  const upstream = await fetch(`${SERVICE_URL}/ask`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body,
    // Generation takes seconds and the service is single-threaded by design, so requests
    // queue. Nothing here may be cached: two CSMs asking similar questions must not be
    // served each other's answer, which the service already enforces at the gateway.
    cache: 'no-store',
  });

  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: JSON_HEADERS,
  });
}
