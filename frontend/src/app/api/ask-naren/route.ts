/**
 * Same-origin proxy to the Ask Naren service (issues #3, #6).
 *
 * WHY A PROXY AT ALL. The service is an internal ASGI app on uvicorn bound to localhost
 * (Brain/ask_naren/service.py). Pointing the browser straight at it would mean exposing it
 * beyond localhost and adding CORS to a service that deliberately has no framework to do
 * it. A same-origin route keeps the service where it is.
 *
 * ON THE HAPPY PATH THIS FILE RESHAPES NOTHING. The body goes out as received and the
 * response comes back byte-for-byte with its status, so `AskNarenResponse` in src/types.ts
 * describes ONE contract rather than the frontend's idea of it. No retrieval, grounding or
 * model-calling logic lives here or anywhere else in the frontend.
 *
 * WHEN THE SERVICE CANNOT BE REACHED (issue #6) this route SYNTHESISES a decline rather
 * than letting the failure escape as a 500. Two reasons:
 *
 *   1. A CSM mid-call must never be handed a stack trace or a broken page. The service
 *      already writes CSM-safe copy for its own internal fault; an outage should read the
 *      same way -- plainly, in the tool's own voice.
 *   2. Emitting the decline SHAPE means the page needs no separate error branch. One render
 *      path cannot drift out of sync with itself, and there is no state the page can reach
 *      where it has neither an answer nor an explanation.
 *
 * BUT THE TWO CASES MUST NOT BECOME ONE. Conflating "nothing in Naren's calls is close
 * enough" with "the service is down" would hide an outage behind what looks like normal
 * conservative behaviour -- the tool would appear to be working and simply declining a lot.
 * So the reason code differs (`service_unreachable`, never `no_close_match`), the copy says
 * plainly that it is a fault on our side, and the failure is logged server-side with the
 * upstream URL and the underlying cause. The HTTP status stays 503: a monitor watching for
 * outages must see one.
 */
import type { NextRequest } from 'next/server';

/** Matches the service's own DEFAULT_HOST/DEFAULT_PORT. Overridable for a non-local
 *  deployment without touching code. */
const SERVICE_URL = process.env.ASK_NAREN_SERVICE_URL ?? 'http://127.0.0.1:8787';

/**
 * Generous on purpose, and now generous for a WEAKER reason than it was.
 *
 * A single answer takes ~12s (generation at reasoning_effort=medium). This used to be sized
 * for the serialised worst case: the service was single-threaded by design, so a third
 * caller genuinely waited ~37s and a tight timeout would have aborted healthy requests that
 * were merely in line. **That is no longer true** -- as of issues #30/#31 the service
 * answers several CSMs at once, so queueing is no longer what a long wait means
 * (reproduced by ask-naren/audit/check_concurrent_service.py; the measurement is
 * recorded in that directory's artifacts rather than quoted here, because gateway
 * latency moves).
 *
 * Left at 120s deliberately rather than tightened here: the ceiling is now the gateway's
 * 8-in-flight-per-key budget, and what a caller past it should get is a prompt "busy, try
 * again" from the SERVICE rather than a timeout from this proxy. Issue #32 adds that bound
 * and its deadline, and this number should be set against that deadline -- one place, not
 * two. Until then this exists to bound a hung socket, not to enforce a latency budget.
 */
const TIMEOUT_MS = 120_000;

const JSON_HEADERS = { 'Content-Type': 'application/json; charset=utf-8' } as const;

/** Kept in the service's voice, and deliberately NOT the no-match wording. A CSM should be
 *  able to tell "Naren never faced this" from "the tool is broken" without being shown a
 *  reason code. */
const UNREACHABLE = {
  outcome: 'declined',
  reason: 'service_unreachable',
  message:
    'Ask Naren could not be reached just now. Nothing was answered — this is a fault on ' +
    'our side, not a "no close match". Try again in a moment.',
} as const;

export async function POST(request: NextRequest) {
  // Forwarded as text, not as a parsed-and-re-serialised object: the service does its own
  // validation of `situation` (non-empty string, body size cap) and returns a 400 with its
  // own message. Validating here too would put that rule in two places.
  const body = await request.text();

  let upstream: Response;
  try {
    upstream = await fetch(`${SERVICE_URL}/ask`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body,
      // Nothing here may be cached: two CSMs asking similar questions must not be served
      // each other's answer, which the service already enforces at the gateway.
      cache: 'no-store',
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (cause) {
    // Connection refused, DNS failure, socket hang-up, or the timeout above. Logged with
    // the upstream URL because "the service is down" is an operator's problem and the
    // CSM-facing message deliberately cannot say which host failed.
    console.error(`[ask-naren] upstream unreachable at ${SERVICE_URL}/ask:`, cause);
    return Response.json(UNREACHABLE, { status: 503, headers: JSON_HEADERS });
  }

  const text = await upstream.text();

  // A reachable service that answered with something that is not JSON is also an outage,
  // just a stranger one -- a crashed worker, or a proxy in between returning HTML. The page
  // must not be handed a body it cannot parse, so it gets the same decline shape.
  try {
    JSON.parse(text);
  } catch {
    console.error(
      `[ask-naren] upstream returned non-JSON (status ${upstream.status}):`,
      text.slice(0, 500),
    );
    return Response.json(UNREACHABLE, { status: 503, headers: JSON_HEADERS });
  }

  return new Response(text, { status: upstream.status, headers: JSON_HEADERS });
}
