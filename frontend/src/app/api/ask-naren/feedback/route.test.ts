// @vitest-environment node
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { NextRequest } from 'next/server';

import type { AskNarenResponse } from '@/types';
import type { Db } from '@/server/db';
import { SESSION_COOKIE } from '@/server/auth/cookie';
import { createSession } from '@/server/auth/sessions';
import { addUser } from '@/server/auth/users';
import { recordFeedback } from '@/server/feedback';
import { deleteThread, recordTurn } from '@/server/threads';
import { freshDb } from '@/server/testing/pglite';

let current: Db;
vi.mock('@/server/db', () => ({ db: () => current }));

const { POST } = await import('./route');

let testDb: Db;
let reset: () => Promise<void>;
let close: () => Promise<void>;

beforeAll(async () => {
  const fresh = await freshDb();
  testDb = fresh.db;
  reset = fresh.reset;
  close = () => fresh.pg.close();
});
afterAll(() => close());
beforeEach(async () => {
  current = testDb;
  await reset();
});

const ANSWER: AskNarenResponse = {
  outcome: 'answered',
  answer: 'Joveo tracks applicants through your ATS.',
  quote: 'we capture an anonymized ID',
  citation: { label: 'call.txt', scenario_key: 'tracking', call_filename: 'call.txt' },
} as unknown as AskNarenResponse;

let n = 0;
async function userWithTurn(): Promise<{ token: string; userId: number; threadId: number }> {
  n += 1;
  const userId = await addUser(testDb, { email: `fb${n}@joveo.com`, name: `FB ${n}`, password: 'pw-for-tests-1' });
  const at = new Date();
  const turn = await recordTurn(testDb, { userId, threadId: null, question: 'q', response: ANSWER, askedAt: at, answeredAt: at });
  return { token: (await createSession(testDb, userId)).token, userId, threadId: turn!.threadId };
}

function req(token: string | undefined, body: unknown) {
  return new NextRequest('http://localhost/api/ask-naren/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { cookie: `${SESSION_COOKIE}=${token}` } : {}) },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

async function stored() {
  const { rows } = await testDb.query<{ rating: string; reason: string | null }>(
    'select rating, reason from ask_naren.feedback order by id',
  );
  return rows;
}

describe('POST /api/ask-naren/feedback', () => {
  it('saves the thumb, then the reason, as one rating', async () => {
    const { token, threadId } = await userWithTurn();
    expect((await POST(req(token, { thread_id: threadId, position: 1, rating: 'bad' }))).status).toBe(200);
    expect(await stored()).toEqual([{ rating: 'bad', reason: null }]);

    await POST(req(token, { thread_id: threadId, position: 1, rating: 'bad', reason: ' answered a different question ' }));
    expect(await stored()).toEqual([{ rating: 'bad', reason: 'answered a different question' }]);
  });

  it('keeps the reason on a repeat click, and drops it when the rating flips', async () => {
    const { token, threadId } = await userWithTurn();
    await POST(req(token, { thread_id: threadId, position: 1, rating: 'good', reason: 'sent it as is' }));
    await POST(req(token, { thread_id: threadId, position: 1, rating: 'good' }));
    expect(await stored()).toEqual([{ rating: 'good', reason: 'sent it as is' }]);
    await POST(req(token, { thread_id: threadId, position: 1, rating: 'bad' }));
    expect(await stored()).toEqual([{ rating: 'bad', reason: null }]);
  });

  it('refuses a signed-out caller', async () => {
    const { threadId } = await userWithTurn();
    expect((await POST(req(undefined, { thread_id: threadId, position: 1, rating: 'good' }))).status).toBe(401);
    expect(await stored()).toEqual([]);
  });

  it('answers 404 for someone else’s turn, a missing turn, or a removed thread', async () => {
    const owner = await userWithTurn();
    const other = await userWithTurn();
    expect((await POST(req(other.token, { thread_id: owner.threadId, position: 1, rating: 'good' }))).status).toBe(404);
    expect((await POST(req(owner.token, { thread_id: owner.threadId, position: 2, rating: 'good' }))).status).toBe(404);
    await deleteThread(testDb, owner.userId, owner.threadId);
    expect((await POST(req(owner.token, { thread_id: owner.threadId, position: 1, rating: 'good' }))).status).toBe(404);
    expect(await stored()).toEqual([]);
  });

  it('rejects a malformed body', async () => {
    const { token, threadId } = await userWithTurn();
    for (const body of [
      'not json',
      { thread_id: threadId, position: 1, rating: 'meh' },
      { thread_id: threadId, position: 0, rating: 'good' },
      { thread_id: 'x', position: 1, rating: 'good' },
      { thread_id: threadId, position: 1, rating: 'good', reason: 'x'.repeat(2001) },
    ]) {
      expect((await POST(req(token, body))).status).toBe(400);
    }
  });

  it('says the store is down rather than failing silently', async () => {
    const { token, threadId } = await userWithTurn();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const real = testDb;
    // The session check succeeds; the feedback write then fails.
    current = {
      query: (text, params) =>
        text.includes('ask_naren.feedback') ? Promise.reject(new Error('down')) : real.query(text, params),
    };
    expect((await POST(req(token, { thread_id: threadId, position: 1, rating: 'good' }))).status).toBe(500);
  });

  it('stores one rating per user per turn, whatever the click count', async () => {
    const { userId, threadId } = await userWithTurn();
    for (let i = 0; i < 3; i += 1) {
      expect(await recordFeedback(testDb, { userId, threadId, position: 1, rating: 'good' })).toBe(true);
    }
    expect(await stored()).toHaveLength(1);
  });
});
