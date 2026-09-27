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
 *
 * ONLY FOR A SIGNED-IN USER (issue #44, ADR 0011). The session is checked here, in the handler,
 * because this is where the data is -- not in `middleware` (issue #42). No session is a 401
 * with no body the page renders: it is not an answer and not a decline, nothing was asked of
 * the service, and the page's response to it is to keep the question and send the CSM to
 * sign in. A FAULT DURING THE CHECK IS NOT A 401. Reporting a store outage as "signed out"
 * would send a CSM to a sign-in page that cannot work either, and hide the outage behind
 * what looks like an expired session; it is a 500, logged. What a CSM should read then is
 * issue #40's to decide.
 */
import type { NextRequest } from 'next/server';

import { db } from '@/server/db';
import { SESSION_COOKIE } from '@/server/auth/cookie';
import { type SessionUser, validateSession } from '@/server/auth/sessions';

/** Matches the service's own DEFAULT_HOST/DEFAULT_PORT. Overridable for a non-local
 *  deployment without touching code -- see .env.example. */
const SERVICE_URL = process.env.ASK_NAREN_SERVICE_URL ?? 'http://127.0.0.1:8787';

/* WARN ONCE AT STARTUP WHEN THE URL IS UNCONFIGURED, because every other signal this module
 * produces is indistinguishable from the tool working normally. The default is correct for
 * local development, where the service is on this machine. Anywhere else -- a container, a
 * deployed environment -- it resolves to that host itself, so the fetch below always fails
 * and every question comes back as a `service_unreachable` decline: CSM-safe copy, no stack
 * trace, no crash, page renders fine. An operator looking at a healthy process serving 200s
 * has nothing to go on. This line is that something.
 *
 * Deliberately a warning and not a throw: refusing to boot without the service would make a
 * frontend that is perfectly usable on every other page unstartable. */
if (!process.env.ASK_NAREN_SERVICE_URL) {
  console.warn(
    `[ask-naren] ASK_NAREN_SERVICE_URL is not set; falling back to ${SERVICE_URL}. ` +
      'That is correct locally and wrong everywhere else -- outside local development this ' +
      'is unreachable and every question will be declined with reason `service_unreachable`.',
  );
}

/**
 * SET AGAINST THE SERVICE'S OWN DEADLINE (issue #32), which is the thing that decides how
 * long a CSM waits. It is deliberately NOT a second latency budget.
 *
 * The 120s this replaces was sized for a serialised server, where a third caller genuinely
 * waited in line and a tight timeout would have aborted healthy requests. Issues #30/#31
 * removed the serialisation and #32 replaced the queueing-forever behaviour with a bounded
 * queue and a per-request deadline, so every outcome the service can produce -- an answer,
 * a decline, a busy refusal, its own deadline -- now arrives inside that deadline. A proxy
 * timeout shorter than it would abort requests the service was about to answer correctly,
 * and one much longer than it would only ever fire for a socket that has stopped
 * responding, which is what this is now for.
 *
 * ONE SOURCE OF TRUTH, MIRRORED ONCE. The deadline is declared in
 * `Brain/ask_naren/admission.py` (`ANSWER_DEADLINE_SECONDS`) and announced by the service
 * at startup and on `/ready`; there is no shared config between the Python service and this
 * route, so this constant restates it and the margin exists so that a response the service
 * produced AT its deadline still gets through the wire. If the deadline moves, move this.
 * No latency figure is asserted here -- gateway latency has been observed moving ~6x
 * between runs, and measurements live in ask-naren/audit/artifacts/.
 */
const SERVICE_DEADLINE_MS = 30_000;
const TIMEOUT_MS = SERVICE_DEADLINE_MS + 5_000;

const JSON_HEADERS = { 'Content-Type': 'application/json; charset=utf-8' } as const;

/** Response headers worth forwarding from the service, rather than replacing wholesale.
 *
 *  `Retry-After` rides on a busy refusal (issue #32) and carries the same estimate as the
 *  body's `retry_after_seconds`. Rebuilding the response with only `Content-Type` DROPPED
 *  it -- which made this file quietly reshape a response on the happy path, the one thing
 *  its own docstring says it never does, and made the contract note on `service_busy` in
 *  src/types.ts false: it promises a header nothing downstream ever saw.
 *
 *  An allowlist rather than forwarding every upstream header, because the rest describe the
 *  upstream connection rather than the answer -- `content-length` in particular would be
 *  wrong the moment anything here re-encoded a body. */
const FORWARDED_HEADERS = ['retry-after'] as const;

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
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  let user: SessionUser | null = null;
  try {
    if (token) user = await validateSession(db(), token);
  } catch (cause) {
    console.error('[ask-naren] session check failed:', cause);
    return Response.json({ error: 'session_check_failed' }, { status: 500, headers: JSON_HEADERS });
  }
  if (!user) {
    return Response.json({ error: 'signed_out' }, { status: 401, headers: JSON_HEADERS });
  }

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

  const headers = new Headers(JSON_HEADERS);
  for (const name of FORWARDED_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  return new Response(text, { status: upstream.status, headers });
}
