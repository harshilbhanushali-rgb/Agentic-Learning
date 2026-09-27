/**
 * One of the signed-in user's threads (#39, #46).
 *
 *   GET    -> 200 `{thread: StoredThreadJson}`: every turn in order, each with the service's
 *             response VERBATIM, so the page renders old turns with the full cards.
 *   PATCH  `{title: string | null}` -> 200 `{thread: ThreadSummaryJson}`. A blank or null
 *             title clears the rename back to the first question.
 *   DELETE -> 200 `{ok: true}`. SOFT: "removed from your list", never erased (#37).
 *
 * Every one: 401 without a session, 404 `thread_not_found` when the thread is missing,
 * removed or somebody else's (the same answer, so an id reveals nothing), 500
 * `store_unavailable` on a store fault. See ../../session.ts.
 */
import type { NextRequest } from 'next/server';

import { db } from '@/server/db';
import { deleteThread, loadThread, renameThread } from '@/server/threads';
import { summaryJson, threadJson } from '@/lib/thread';

import {
  JSON_HEADERS,
  parseThreadId,
  sessionUser,
  storeUnavailable,
  threadNotFound,
} from '../../session';

export const dynamic = 'force-dynamic';

type Params = { params: { id: string } };

export async function GET(request: NextRequest, { params }: Params) {
  const session = await sessionUser(request);
  if (session.refused) return session.refused;
  const id = parseThreadId(params.id);
  if (id === null) return threadNotFound();
  try {
    const thread = await loadThread(db(), session.user.id, id);
    if (!thread) return threadNotFound();
    return Response.json({ thread: threadJson(thread) }, { headers: JSON_HEADERS });
  } catch (cause) {
    return storeUnavailable('thread load', cause);
  }
}

export async function PATCH(request: NextRequest, { params }: Params) {
  const session = await sessionUser(request);
  if (session.refused) return session.refused;
  const id = parseThreadId(params.id);
  if (id === null) return threadNotFound();

  let title: string | null;
  try {
    const body = (await request.json()) as { title?: unknown } | null;
    if (!body || (typeof body.title !== 'string' && body.title !== null)) throw new Error();
    title = body.title;
  } catch {
    return Response.json({ error: 'invalid_title' }, { status: 400, headers: JSON_HEADERS });
  }

  try {
    if (!(await renameThread(db(), session.user.id, id, title))) return threadNotFound();
    // Read back rather than echoed, so the rail shows the title the store now derives --
    // the first question again when the rename was cleared.
    const thread = await loadThread(db(), session.user.id, id);
    if (!thread) return threadNotFound();
    return Response.json({ thread: summaryJson(thread) }, { headers: JSON_HEADERS });
  } catch (cause) {
    return storeUnavailable('thread rename', cause);
  }
}

export async function DELETE(request: NextRequest, { params }: Params) {
  const session = await sessionUser(request);
  if (session.refused) return session.refused;
  const id = parseThreadId(params.id);
  if (id === null) return threadNotFound();
  try {
    if (!(await deleteThread(db(), session.user.id, id))) return threadNotFound();
    return Response.json({ ok: true }, { headers: JSON_HEADERS });
  } catch (cause) {
    return storeUnavailable('thread remove', cause);
  }
}
