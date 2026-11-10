/**
 * Rate an answer (migration 0003).
 *
 *   POST `{thread_id, position, rating: 'good' | 'bad', reason?: string | null}` -> 200
 *   `{ok: true}`. Sent once when a thumb is clicked, and again with the reason if one is
 *   written; the second replaces the first.
 *
 * 401 without a session, 404 `thread_not_found` when the turn is missing, removed or someone
 * else's (one answer, so ids reveal nothing), 400 on a malformed body, 500
 * `store_unavailable` on a store fault. See ../session.ts.
 */
import type { NextRequest } from 'next/server';

import { db } from '@/server/db';
import { MAX_REASON_LENGTH, type Rating, recordFeedback } from '@/server/feedback';

import { JSON_HEADERS, parseThreadId, sessionUser, storeUnavailable, threadNotFound } from '../session';

export const dynamic = 'force-dynamic';

const invalid = () => Response.json({ error: 'invalid_feedback' }, { status: 400, headers: JSON_HEADERS });

export async function POST(request: NextRequest) {
  const session = await sessionUser(request);
  if (session.refused) return session.refused;

  let body: { thread_id?: unknown; position?: unknown; rating?: unknown; reason?: unknown } | null;
  try {
    body = await request.json();
  } catch {
    return invalid();
  }
  if (!body) return invalid();
  const threadId = parseThreadId(body.thread_id);
  const position = body.position;
  const rating = body.rating;
  const reason = body.reason;
  if (
    threadId === null ||
    typeof position !== 'number' || !Number.isInteger(position) || position < 1 ||
    (rating !== 'good' && rating !== 'bad') ||
    (reason !== undefined && reason !== null &&
      (typeof reason !== 'string' || reason.length > MAX_REASON_LENGTH))
  ) {
    return invalid();
  }

  try {
    const saved = await recordFeedback(db(), {
      userId: session.user.id,
      threadId,
      position,
      rating: rating as Rating,
      reason: (reason as string | null | undefined) ?? null,
    });
    if (!saved) return threadNotFound();
    return Response.json({ ok: true }, { headers: JSON_HEADERS });
  } catch (cause) {
    return storeUnavailable('feedback', cause);
  }
}
