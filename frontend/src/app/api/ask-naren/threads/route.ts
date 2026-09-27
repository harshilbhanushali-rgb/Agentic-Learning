/**
 * GET /api/ask-naren/threads -- the signed-in user's thread rail (#39, #46): their own
 * threads only, newest first, removed ones gone.
 *
 * 200 `{threads: ThreadSummaryJson[]}`; 401 without a session; 500 `store_unavailable` on a
 * store fault. See ../session.ts for why those three look the way they do.
 */
import type { NextRequest } from 'next/server';

import { db } from '@/server/db';
import { listThreads } from '@/server/threads';
import { summaryJson } from '@/lib/thread';

import { JSON_HEADERS, sessionUser, storeUnavailable } from '../session';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const session = await sessionUser(request);
  if (session.refused) return session.refused;
  try {
    const threads = await listThreads(db(), session.user.id);
    return Response.json({ threads: threads.map(summaryJson) }, { headers: JSON_HEADERS });
  } catch (cause) {
    return storeUnavailable('thread list', cause);
  }
}
