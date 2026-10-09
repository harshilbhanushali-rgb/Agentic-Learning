/**
 * The door every Ask Naren route handler goes through (issues #44, #40, #46): who is asking,
 * and the three answers that are not about the question.
 *
 * ONE RULE, SHARED, so the proxy and the thread APIs cannot drift on what "signed out" or
 * "store down" looks like:
 *
 *   - NO SESSION -> 401 `{error: 'signed_out'}`. Not an answer and not a decline; the page
 *     keeps the question and sends the CSM to sign in.
 *   - A FAULT READING THE STORE -> 500 with a decline body, `reason: 'store_unavailable'`
 *     (#40). Never a 401: reporting a store outage as "signed out" would send a CSM to a
 *     sign-in page that cannot work either and hide the outage behind an expired session.
 *     Decline-SHAPED so the page renders it through the one DeclineNotice path, like
 *     `service_unreachable`, and distinct from that by status, reason and wording.
 *   - A THREAD THAT IS NOT THIS USER'S -> 404 `{error: 'thread_not_found'}`. Missing,
 *     removed and somebody else's are the same answer, so an id reveals nothing.
 *
 * Not a route file: Next only routes `route.ts`, so this sits beside the handlers it serves.
 */
import type { NextRequest } from 'next/server';

import type { AskNarenDecline } from '@/types';
import { db } from '@/server/db';
import { SESSION_COOKIE } from '@/server/auth/cookie';
import { type SessionUser, validateSession } from '@/server/auth/sessions';

export const JSON_HEADERS = { 'Content-Type': 'application/json; charset=utf-8' } as const;

/** What the proxy adds to the service's response, in headers so the body stays the
 *  service's byte for byte (#40, #46). Thread and position are set when the turn was
 *  recorded; `Recorded: false` when the service answered but the write failed. */
export const THREAD_HEADER = 'X-Ask-Naren-Thread';
export const POSITION_HEADER = 'X-Ask-Naren-Position';
export const RECORDED_HEADER = 'X-Ask-Naren-Recorded';

/** #40's copy, verbatim. Says what did NOT happen (nothing was asked) and where the question
 *  went, because the page puts it back in the box. */
export const STORE_UNAVAILABLE: AskNarenDecline = {
  outcome: 'declined',
  reason: 'store_unavailable',
  message:
    'Ask Naren could not check your sign-in just now, so nothing was asked. This is a fault ' +
    'on our side, not a "no close match" — your question is back in the box. Try again in a ' +
    'moment.',
};

export function storeUnavailable(what: string, cause: unknown): Response {
  console.error(`[ask-naren] store unavailable (${what}):`, cause);
  return Response.json(STORE_UNAVAILABLE, { status: 500, headers: JSON_HEADERS });
}

export function signedOut(): Response {
  return Response.json({ error: 'signed_out' }, { status: 401, headers: JSON_HEADERS });
}

export function threadNotFound(): Response {
  return Response.json({ error: 'thread_not_found' }, { status: 404, headers: JSON_HEADERS });
}

/** The signed-in user, or the Response to send instead. */
export async function sessionUser(
  request: NextRequest,
): Promise<{ user: SessionUser; refused?: undefined } | { user?: undefined; refused: Response }> {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return { refused: signedOut() };
  let user: SessionUser | null;
  try {
    user = await validateSession(db(), token);
  } catch (cause) {
    return { refused: storeUnavailable('session check', cause) };
  }
  return user ? { user } : { refused: signedOut() };
}

/** A thread id as it may arrive -- a path segment or a JSON value -- or null if it cannot be
 *  one. Bounded well below 2^53 so it survives the trip through a JS number. */
export function parseThreadId(raw: unknown): number | null {
  const text = typeof raw === 'number' ? String(raw) : raw;
  if (typeof text !== 'string' || !/^[1-9]\d{0,14}$/.test(text)) return null;
  return Number(text);
}
