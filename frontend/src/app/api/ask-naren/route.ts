/**
 * Same-origin proxy to the Ask Naren service (issues #3, #6), and since #46 THE CALLER that
 * holds a CSM's thread.
 *
 * WHY A PROXY AT ALL. The service is an internal ASGI app on uvicorn bound to localhost
 * (Brain/ask_naren/api/). Pointing the browser straight at it would mean exposing it
 * beyond localhost and adding CORS to a service that deliberately has no framework to do
 * it. A same-origin route keeps the service where it is.
 *
 * THE ROUTE BUILDS THE THREAD, THE BROWSER DOES NOT (#46). The page sends
 * `{situation, thread_id}`. The route loads that thread's stored turns FOR THIS USER, derives
 * the wire turns with `turnFrom`, trims them and forwards `{situation, thread}` -- exactly
 * the body the page used to build. Nothing a browser holds can reach the service's prompt,
 * and a thread id that is not this user's is a 404 with nothing forwarded.
 *
 * THE RESPONSE BODY IS STILL THE SERVICE'S, BYTE FOR BYTE. Status, body and `Retry-After`
 * come back as the service sent them, so `AskNarenResponse` in src/types.ts describes ONE
 * contract rather than the frontend's idea of it. What this route adds travels in headers
 * only: `X-Ask-Naren-Thread` / `X-Ask-Naren-Position` when the turn was recorded, and
 * `X-Ask-Naren-Recorded: false` when the service answered but the write failed (#40) -- the
 * answer is still delivered, and the page starts the next question in a fresh thread rather
 * than replay a thread with a gap in it. No retrieval, grounding or model-calling logic lives
 * here or anywhere else in the frontend.
 *
 * WHAT IS RECORDED. Every response that carries a known `outcome` -- including the outage and
 * busy declines, so a CSM scrolling back sees that they asked and what happened, and so the
 * `reason` column can tell an outage from a coverage gap. Never a 400 or 401: neither
 * answered anything (#37). One retry of the write, then logged.
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
 * ONLY FOR A SIGNED-IN USER (issue #44, ADR 0011), checked here in the handler because this
 * is where the data is -- not in `middleware` (issue #42). No session is a 401; a store fault
 * during the check or the thread load is a 500 `store_unavailable` decline (#40), never a
 * 401 -- see ./session.ts.
 */
import type { NextRequest } from 'next/server';

import type { AskNarenResponse } from '@/types';
import { db } from '@/server/db';
import { loadThread, recordTurn } from '@/server/threads';
import { type ThreadTurn, trimThread, turnFrom } from '@/lib/thread';

import {
  JSON_HEADERS,
  POSITION_HEADER,
  RECORDED_HEADER,
  THREAD_HEADER,
  parseThreadId,
  sessionUser,
  storeUnavailable,
  threadNotFound,
} from './session';
import { DEFAULT_SERVICE_URL, createServiceGate, resolveServiceUrl } from '@/server/serviceUrl';

export const dynamic = 'force-dynamic';

/** Where the service is. The default matches the service's own DEFAULT_HOST/DEFAULT_PORT;
 *  a deployment overrides it without touching code -- see .env.example.
 *
 *  CHECKED BEFORE ANY QUESTION IS SENT (src/server/serviceUrl.ts). The host must be internal
 *  and must answer `/health` as the service does. Production once pointed this at a
 *  third-party wildcard domain, and every question went there. */
const TARGET = resolveServiceUrl(
  process.env.ASK_NAREN_SERVICE_URL,
  process.env.ASK_NAREN_ALLOWED_SERVICE_HOSTS,
);
const serviceBase = createServiceGate(TARGET);
if (!TARGET.ok) console.error(`[ask-naren] ${TARGET.reason}`);

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
    `[ask-naren] ASK_NAREN_SERVICE_URL is not set; falling back to ${DEFAULT_SERVICE_URL}. ` +
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
 * `Brain/ask_naren/api/admission.py` (`ANSWER_DEADLINE_SECONDS`) and announced by the service
 * at startup and on `/ready`; there is no shared config between the Python service and this
 * route, so this constant restates it and the margin exists so that a response the service
 * produced AT its deadline still gets through the wire. If the deadline moves, move this.
 * No latency figure is asserted here -- gateway latency has been observed moving ~6x
 * between runs, and measurements live in ask-naren/audit/artifacts/.
 *
 * The store reads and writes either side of the fetch are not covered by this timeout; #40
 * bounds them separately, with connect and query timeouts on the pool in src/server/db.ts.
 */
const SERVICE_DEADLINE_MS = 30_000;
const TIMEOUT_MS = SERVICE_DEADLINE_MS + 5_000;

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

const OUTCOMES: ReadonlySet<string> = new Set(['answered', 'declined', 'clarify', 'rendered']);

export async function POST(request: NextRequest) {
  const session = await sessionUser(request);
  if (session.refused) return session.refused;
  const { user } = session;

  // The browser's half of the body. `situation` is forwarded as received: the service
  // validates it (non-empty string, body size cap) and returns its own 400, and validating
  // here too would put that rule in two places. Only `thread_id` is this route's to check.
  let sent: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(await request.text());
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error();
    sent = parsed as Record<string, unknown>;
  } catch {
    return Response.json({ error: 'invalid_body' }, { status: 400, headers: JSON_HEADERS });
  }
  const situation = sent.situation;
  let threadId: number | null = null;
  if (sent.thread_id !== undefined && sent.thread_id !== null) {
    threadId = typeof sent.thread_id === 'number' ? parseThreadId(sent.thread_id) : null;
    if (threadId === null) {
      return Response.json({ error: 'invalid_thread_id' }, { status: 400, headers: JSON_HEADERS });
    }
  }

  // The replayed thread, from storage and nothing else. A thread that is not this user's --
  // missing, removed, someone else's -- is a 404 and the service is never called.
  let thread: ThreadTurn[] = [];
  if (threadId !== null) {
    let stored;
    try {
      stored = await loadThread(db(), user.id, threadId);
    } catch (cause) {
      return storeUnavailable('thread load', cause);
    }
    if (!stored) return threadNotFound();
    // TRIMMED, not truncated: a long conversation is shrunk by dropping old PROSE and never
    // a carried identifier, because the message that established the scenario is usually
    // the first one (ADR 0006). Without this the body eventually exceeds the service's cap
    // and every further question 400s.
    thread = trimThread(stored.turns.map(t => turnFrom(t.question, t.response)));
  }

  const askedAt = new Date();
  const { status, text, headers } = await forward(JSON.stringify({ situation, thread }));
  const answeredAt = new Date();

  const response = recordable(status, text);
  if (response && typeof situation === 'string' && situation.trim()) {
    const recorded = await record({
      userId: user.id,
      threadId,
      question: situation,
      response,
      askedAt,
      answeredAt,
    });
    if (recorded) {
      headers.set(THREAD_HEADER, String(recorded.threadId));
      headers.set(POSITION_HEADER, String(recorded.position));
    } else {
      headers.set(RECORDED_HEADER, 'false');
    }
  }
  return new Response(text, { status, headers });
}

/** The service's answer as status, body text and the headers to send on -- or the
 *  synthesised unreachable decline when there is no usable answer. */
async function forward(body: string): Promise<{ status: number; text: string; headers: Headers }> {
  const unreachable = () => ({
    status: 503,
    text: JSON.stringify(UNREACHABLE),
    headers: new Headers(JSON_HEADERS),
  });

  // Nothing a CSM typed leaves this process until the target is known to be the service.
  const target = await serviceBase();
  if (!target.ok) {
    console.error(`[ask-naren] question NOT sent: ${target.reason}`);
    return unreachable();
  }
  const serviceUrl = target.base;

  let upstream: Response;
  try {
    upstream = await fetch(`${serviceUrl}/ask`, {
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
    console.error(`[ask-naren] upstream unreachable at ${serviceUrl}/ask:`, cause);
    return unreachable();
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
    return unreachable();
  }

  const headers = new Headers(JSON_HEADERS);
  for (const name of FORWARDED_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  return { status: upstream.status, text, headers };
}

/** The response as a turn worth storing, or null. A 400 or 401 answered nothing (#37), and
 *  a body without a known `outcome` is not this contract. */
function recordable(status: number, text: string): AskNarenResponse | null {
  if (status === 400 || status === 401) return null;
  try {
    const body = JSON.parse(text) as { outcome?: unknown } | null;
    return body && typeof body.outcome === 'string' && OUTCOMES.has(body.outcome)
      ? (body as AskNarenResponse)
      : null;
  } catch {
    return null;
  }
}

/** `recordTurn` with ONE retry on a fault (#40). Null when it could not be recorded: both
 *  attempts threw, or the thread stopped being this user's between load and write (removed
 *  in another tab) -- which is not a fault, so it is not retried. */
async function record(
  input: Parameters<typeof recordTurn>[1],
): Promise<{ threadId: number; position: number } | null> {
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const recorded = await recordTurn(db(), input);
      if (!recorded) {
        console.error(
          `[ask-naren] turn not recorded: thread ${input.threadId} is no longer user ${input.userId}'s`,
        );
      }
      return recorded;
    } catch (cause) {
      console.error(`[ask-naren] turn write failed (attempt ${attempt} of 2):`, cause);
    }
  }
  return null;
}
