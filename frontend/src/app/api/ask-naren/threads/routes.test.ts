// @vitest-environment node
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { NextRequest } from 'next/server';

import type { AskNarenResponse } from '@/types';
import type { Db } from '@/server/db';
import { SESSION_COOKIE } from '@/server/auth/cookie';
import { createSession } from '@/server/auth/sessions';
import { addUser } from '@/server/auth/users';
import { loadThread, recordTurn } from '@/server/threads';
import { freshDb } from '@/server/testing/pglite';

import { STORE_UNAVAILABLE } from '../session';

let current: Db;
vi.mock('@/server/db', () => ({ db: () => current }));

const list = await import('./route');
const one = await import('./[id]/route');

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

const DECLINE: AskNarenResponse = { outcome: 'declined', reason: 'no_close_match', message: 'm' };

let emails = 0;
async function signedIn(): Promise<{ token: string; userId: number }> {
  emails += 1;
  const userId = await addUser(testDb, {
    email: `rail${emails}@joveo.com`,
    name: `Rail ${emails}`,
    password: 'pw-for-tests-1',
  });
  return { token: (await createSession(testDb, userId)).token, userId };
}

async function threadWith(userId: number, questions: string[], at = new Date()): Promise<number> {
  let threadId: number | null = null;
  for (const question of questions) {
    const r = await recordTurn(testDb, { userId, threadId, question, response: DECLINE, askedAt: at, answeredAt: at });
    threadId = r!.threadId;
  }
  return threadId!;
}

function req(token: string | undefined, method = 'GET', body?: unknown) {
  return new NextRequest('http://localhost/api/ask-naren/threads', {
    method,
    body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
    headers: token ? { cookie: `${SESSION_COOKIE}=${token}` } : {},
  });
}
const params = (id: number | string) => ({ params: { id: String(id) } });

async function quietly<T>(fn: () => Promise<T>): Promise<T> {
  const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
  try {
    return await fn();
  } finally {
    spy.mockRestore();
  }
}

const broken: Db = { query: () => Promise.reject(new Error('connection refused')) };

describe('GET /api/ask-naren/threads', () => {
  it("lists only the user's own threads, newest first, as JSON", async () => {
    const me = await signedIn();
    const other = await signedIn();
    const older = await threadWith(me.userId, ['first question'], new Date('2026-09-01T10:00:00Z'));
    const newer = await threadWith(me.userId, ['second question', 'follow-up'], new Date('2026-09-20T10:00:00Z'));
    await threadWith(other.userId, ['not mine']);

    const res = await list.GET(req(me.token));
    expect(res.status).toBe(200);
    const { threads } = await res.json();
    expect(threads.map((t: { id: number }) => t.id)).toEqual([newer, older]);
    expect(threads[0]).toEqual({
      id: newer,
      title: 'second question',
      renamed: false,
      createdAt: '2026-09-20T10:00:00.000Z',
      lastTurnAt: '2026-09-20T10:00:00.000Z',
      turnCount: 2,
    });
  });

  it('401 without a session; 500 store_unavailable on a store fault', async () => {
    expect((await list.GET(req(undefined))).status).toBe(401);
    const me = await signedIn();
    current = broken;
    const res = await quietly(() => list.GET(req(me.token)));
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual(STORE_UNAVAILABLE);
  });
});

describe('GET /api/ask-naren/threads/[id]', () => {
  it('returns every turn in order with the response verbatim', async () => {
    const me = await signedIn();
    const id = await threadWith(me.userId, ['q1', 'q2']);
    const res = await one.GET(req(me.token), params(id));
    expect(res.status).toBe(200);
    const { thread } = await res.json();
    expect(thread.id).toBe(id);
    expect(thread.turns.map((t: { position: number; question: string }) => [t.position, t.question])).toEqual([
      [1, 'q1'],
      [2, 'q2'],
    ]);
    expect(thread.turns[0].response).toEqual(DECLINE);
    expect(typeof thread.turns[0].askedAt).toBe('string');
  });

  it("someone else's, a removed one, a missing one and a malformed id are all the same 404", async () => {
    const me = await signedIn();
    const other = await signedIn();
    const theirs = await threadWith(other.userId, ['theirs']);
    const removed = await threadWith(me.userId, ['gone']);
    await one.DELETE(req(me.token, 'DELETE'), params(removed));

    for (const id of [theirs, removed, 999999, 'abc', '0', '1e3']) {
      const res = await one.GET(req(me.token), params(id));
      expect(res.status).toBe(404);
      expect(await res.json()).toEqual({ error: 'thread_not_found' });
    }
  });

  it('401 without a session; 500 store_unavailable on a store fault', async () => {
    const me = await signedIn();
    const id = await threadWith(me.userId, ['q']);
    expect((await one.GET(req(undefined), params(id))).status).toBe(401);
    current = broken;
    const res = await quietly(() => one.GET(req(me.token), params(id)));
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual(STORE_UNAVAILABLE);
  });
});

describe('PATCH /api/ask-naren/threads/[id]', () => {
  it('renames, and a null or blank title goes back to the first question', async () => {
    const me = await signedIn();
    const id = await threadWith(me.userId, ['how long does the ATS take?']);

    const renamed = await one.PATCH(req(me.token, 'PATCH', { title: '  Northwind ATS  ' }), params(id));
    expect(renamed.status).toBe(200);
    expect((await renamed.json()).thread).toMatchObject({ id, title: 'Northwind ATS', renamed: true });

    const cleared = await one.PATCH(req(me.token, 'PATCH', { title: null }), params(id));
    expect((await cleared.json()).thread).toMatchObject({ title: 'how long does the ATS take?', renamed: false });

    const blank = await one.PATCH(req(me.token, 'PATCH', { title: '   ' }), params(id));
    expect((await blank.json()).thread.renamed).toBe(false);
  });

  it("a bad body is a 400; someone else's thread is a 404 and is not renamed", async () => {
    const me = await signedIn();
    const other = await signedIn();
    const mine = await threadWith(me.userId, ['q']);
    const theirs = await threadWith(other.userId, ['theirs']);

    expect((await one.PATCH(req(me.token, 'PATCH', { title: 3 }), params(mine))).status).toBe(400);
    expect((await one.PATCH(req(me.token, 'PATCH', 'nope'), params(mine))).status).toBe(400);

    const res = await one.PATCH(req(me.token, 'PATCH', { title: 'mine now' }), params(theirs));
    expect(res.status).toBe(404);
    expect((await loadThread(testDb, other.userId, theirs))?.renamed).toBe(false);
  });

  it('401 without a session; 500 store_unavailable on a store fault', async () => {
    const me = await signedIn();
    const id = await threadWith(me.userId, ['q']);
    expect((await one.PATCH(req(undefined, 'PATCH', { title: 't' }), params(id))).status).toBe(401);
    current = broken;
    const res = await quietly(() => one.PATCH(req(me.token, 'PATCH', { title: 't' }), params(id)));
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual(STORE_UNAVAILABLE);
  });
});

describe('DELETE /api/ask-naren/threads/[id]', () => {
  it('removes it from the list, keeps the rows, and a second remove is a 404', async () => {
    const me = await signedIn();
    const id = await threadWith(me.userId, ['q']);
    const res = await one.DELETE(req(me.token, 'DELETE'), params(id));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });

    const { threads } = await (await list.GET(req(me.token))).json();
    expect(threads).toEqual([]);
    // Soft: the turn is still there (#37).
    const { rows } = await testDb.query('select count(*)::int as n from ask_naren.turns where thread_id = $1', [id]);
    expect(rows[0]).toEqual({ n: 1 });

    expect((await one.DELETE(req(me.token, 'DELETE'), params(id))).status).toBe(404);
  });

  it("someone else's thread is a 404 and stays on their list", async () => {
    const me = await signedIn();
    const other = await signedIn();
    const theirs = await threadWith(other.userId, ['theirs']);
    expect((await one.DELETE(req(me.token, 'DELETE'), params(theirs))).status).toBe(404);
    expect(await loadThread(testDb, other.userId, theirs)).not.toBeNull();
  });

  it('401 without a session; 500 store_unavailable on a store fault', async () => {
    const me = await signedIn();
    const id = await threadWith(me.userId, ['q']);
    expect((await one.DELETE(req(undefined, 'DELETE'), params(id))).status).toBe(401);
    current = broken;
    const res = await quietly(() => one.DELETE(req(me.token, 'DELETE'), params(id)));
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual(STORE_UNAVAILABLE);
  });
});
