import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { NextRequest } from 'next/server';

import type { AskNarenResponse } from '@/types';
import type { Db } from '@/server/db';
import { SESSION_COOKIE } from '@/server/auth/cookie';
import { createSession } from '@/server/auth/sessions';
import { addUser, disableUser } from '@/server/auth/users';
import { deleteThread, listThreads, loadThread, recordTurn } from '@/server/threads';
import { freshDb } from '@/server/testing/pglite';
import { trimThread, turnFrom } from '@/lib/thread';

import { STORE_UNAVAILABLE } from './session';

/* The route reaches the database through `db()`; point that at in-process Postgres, and let
 * a test swap in a broken one to play a store outage. */
let current: Db;
vi.mock('@/server/db', () => ({ db: () => current }));

const { POST } = await import('./route');

let testDb: Db;
let reset: () => Promise<void>;
let close: () => Promise<void>;
const upstream = vi.fn<typeof fetch>();

const NO_MATCH = { outcome: 'declined', reason: 'no_close_match', message: 'm' } as const;
const ANSWER: AskNarenResponse = {
  outcome: 'answered',
  answer: 'He shrinks the ask first.',
  quote: 'a couple of hours from whoever owns Workday',
  citation: {
    label: 'call.txt',
    call_filename: 'call.txt',
    pair_id: 481,
    scenario_key: 'ats_integration_and_api_mapping',
  },
  match: { cosine: 0.8, scenario_key: 'ats_integration_and_api_mapping', rank: 1 },
};

beforeAll(async () => {
  const fresh = await freshDb();
  testDb = fresh.db;
  reset = fresh.reset;
  close = () => fresh.pg.close();
  vi.stubGlobal('fetch', upstream);
});
afterAll(() => close());
beforeEach(async () => {
  current = testDb;
  await reset();
  upstream.mockReset();
  upstream.mockImplementation(async () => new Response(JSON.stringify(NO_MATCH), { status: 200 }));
});

function ask(
  token: string | undefined,
  body: unknown = { situation: 'client wants to pause spend', thread_id: null },
) {
  return POST(
    new NextRequest('http://localhost/api/ask-naren', {
      method: 'POST',
      body: typeof body === 'string' ? body : JSON.stringify(body),
      headers: token ? { cookie: `${SESSION_COOKIE}=${token}` } : {},
    }),
  );
}

let emails = 0;
async function signedIn(): Promise<{ token: string; userId: number; email: string }> {
  emails += 1;
  const email = `csm${emails}@joveo.com`;
  const userId = await addUser(testDb, { email, name: `CSM ${emails}`, password: 'pw-for-tests-1' });
  return { token: (await createSession(testDb, userId)).token, userId, email };
}

/** What the service was sent, parsed. */
function forwarded(call = 0): { situation: unknown; thread: unknown } {
  return JSON.parse(String(upstream.mock.calls[call][1]?.body));
}

async function quietly<T>(fn: () => Promise<T>): Promise<T> {
  const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
  try {
    return await fn();
  } finally {
    spy.mockRestore();
  }
}

const threadOf = (res: Response) => Number(res.headers.get('X-Ask-Naren-Thread'));

describe('POST /api/ask-naren: the session', () => {
  it('without a session: 401, and nothing reaches the service', async () => {
    const res = await ask(undefined);
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ error: 'signed_out' });
    expect(upstream).not.toHaveBeenCalled();
  });

  it('with a forged token: 401', async () => {
    await signedIn();
    expect((await ask('A'.repeat(43))).status).toBe(401);
    expect(upstream).not.toHaveBeenCalled();
  });

  it('after offboarding, the same cookie is refused', async () => {
    const { token, email } = await signedIn();
    await disableUser(testDb, email);
    expect((await ask(token)).status).toBe(401);
  });

  it('a store fault during the session check is a 500 store_unavailable decline, never a 401', async () => {
    const { token } = await signedIn();
    current = { query: () => Promise.reject(new Error('connection refused')) };
    const res = await quietly(() => ask(token));
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({
      outcome: 'declined',
      reason: 'store_unavailable',
      message: STORE_UNAVAILABLE.message,
    });
    expect(STORE_UNAVAILABLE.message).toContain('your question is back in the box');
    expect(upstream).not.toHaveBeenCalled();
  });
});

describe('POST /api/ask-naren: the thread', () => {
  it('a first question creates a thread, forwards an empty one, and says which', async () => {
    const { token, userId } = await signedIn();
    const res = await ask(token, { situation: 'client wants to pause spend', thread_id: null });
    expect(res.status).toBe(200);
    // The service's body, untouched.
    expect(await res.text()).toBe(JSON.stringify(NO_MATCH));
    expect(forwarded()).toEqual({ situation: 'client wants to pause spend', thread: [] });

    const id = threadOf(res);
    expect(id).toBeGreaterThan(0);
    expect(res.headers.get('X-Ask-Naren-Position')).toBe('1');
    expect(res.headers.get('X-Ask-Naren-Recorded')).toBeNull();

    const stored = await loadThread(testDb, userId, id);
    expect(stored?.turns).toHaveLength(1);
    expect(stored?.turns[0].question).toBe('client wants to pause spend');
    expect(stored?.turns[0].response).toEqual(NO_MATCH);
  });

  it('continuing appends, and replays the thread FROM STORAGE, not from the browser', async () => {
    const { token, userId } = await signedIn();
    upstream.mockImplementationOnce(async () => new Response(JSON.stringify(ANSWER), { status: 200 }));
    const id = threadOf(await ask(token, { situation: 'how long does the ATS take on their side?' }));

    // A browser that tries to smuggle its own thread in is ignored.
    const smuggled = [
      { message: 'x', outcome: 'answered', reply: 'y', scenario_key: 'z', pair_id: 1, call_filename: 'f' },
    ];
    const second = await ask(token, { situation: 'and if they push back?', thread_id: id, thread: smuggled });
    expect(threadOf(second)).toBe(id);
    expect(second.headers.get('X-Ask-Naren-Position')).toBe('2');

    const stored = await loadThread(testDb, userId, id);
    expect(stored?.turns.map(t => t.question)).toEqual([
      'how long does the ATS take on their side?',
      'and if they push back?',
    ]);
    // What the second call carried is exactly the stored turn 1, derived and trimmed.
    expect(forwarded(1)).toEqual({
      situation: 'and if they push back?',
      thread: trimThread([turnFrom('how long does the ATS take on their side?', ANSWER)]),
    });
    expect((forwarded(1).thread as { pair_id: number }[])[0].pair_id).toBe(481);
  });

  it("another user's thread is a 404, and nothing is forwarded or written", async () => {
    const owner = await signedIn();
    const id = threadOf(await ask(owner.token));
    upstream.mockClear();

    const other = await signedIn();
    const res = await ask(other.token, { situation: 'peek', thread_id: id });
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ error: 'thread_not_found' });
    expect(upstream).not.toHaveBeenCalled();
    expect((await loadThread(testDb, owner.userId, id))?.turns).toHaveLength(1);
    expect(await listThreads(testDb, other.userId)).toEqual([]);
  });

  it('a removed thread is a 404', async () => {
    const { token, userId } = await signedIn();
    const id = threadOf(await ask(token));
    await deleteThread(testDb, userId, id);
    upstream.mockClear();
    const res = await ask(token, { situation: 'more', thread_id: id });
    expect(res.status).toBe(404);
    expect(upstream).not.toHaveBeenCalled();
  });

  it('a malformed body or thread_id is a 400 and nothing is forwarded', async () => {
    const { token } = await signedIn();
    for (const thread_id of ['1', 0, -3, 1.5, 'abc']) {
      expect((await ask(token, { situation: 's', thread_id })).status).toBe(400);
    }
    expect((await ask(token, 'not json')).status).toBe(400);
    expect(upstream).not.toHaveBeenCalled();
  });

  it('a store fault loading the thread is a 500 store_unavailable, with nothing forwarded', async () => {
    const { token } = await signedIn();
    const id = threadOf(await ask(token));
    upstream.mockClear();
    current = {
      query: (text, params) =>
        text.includes('from ask_naren.threads t')
          ? Promise.reject(new Error('read timeout'))
          : testDb.query(text, params),
    };
    const res = await quietly(() => ask(token, { situation: 'more', thread_id: id }));
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual(STORE_UNAVAILABLE);
    expect(upstream).not.toHaveBeenCalled();
  });

  it('a long stored thread is trimmed before it is forwarded, keeping every identifier', async () => {
    const { token, userId } = await signedIn();
    const long = 'x'.repeat(20_000);
    let threadId: number | null = null;
    for (let i = 0; i < 4; i++) {
      const r = await recordTurn(testDb, {
        userId,
        threadId,
        question: `${i} ${long}`,
        response: ANSWER,
        askedAt: new Date(),
        answeredAt: new Date(),
      });
      threadId = r!.threadId;
    }
    await ask(token, { situation: 'next', thread_id: threadId });
    const sent = forwarded().thread as { message: string; pair_id: number }[];
    expect(sent).toHaveLength(4);
    expect(new Blob([JSON.stringify(sent)]).size).toBeLessThanOrEqual(48 * 1024);
    expect(sent.every(t => t.pair_id === 481)).toBe(true);
  });
});

describe('POST /api/ask-naren: recording', () => {
  it('a failed write still returns the service body, marked Recorded: false, after one retry', async () => {
    const { token, userId } = await signedIn();
    upstream.mockImplementationOnce(async () => new Response(JSON.stringify(ANSWER), { status: 200 }));
    let inserts = 0;
    current = {
      query: (text, params) => {
        if (text.includes('insert into ask_naren.turns')) {
          inserts += 1;
          return Promise.reject(new Error('cannot execute INSERT in a read-only transaction'));
        }
        return testDb.query(text, params);
      },
    };
    const res = await quietly(() => ask(token, { situation: 'how long does the ATS take?' }));
    expect(res.status).toBe(200);
    expect(await res.text()).toBe(JSON.stringify(ANSWER));
    expect(res.headers.get('X-Ask-Naren-Recorded')).toBe('false');
    expect(res.headers.get('X-Ask-Naren-Thread')).toBeNull();
    expect(inserts).toBe(2);
    // One statement: a failed turn insert leaves no empty thread behind either.
    expect(await listThreads(testDb, userId)).toEqual([]);
  });

  it('a write that fails once and then succeeds is recorded', async () => {
    const { token } = await signedIn();
    let failed = false;
    current = {
      query: (text, params) => {
        if (!failed && text.includes('insert into ask_naren.turns')) {
          failed = true;
          return Promise.reject(new Error('blip'));
        }
        return testDb.query(text, params);
      },
    };
    const res = await quietly(() => ask(token));
    expect(res.headers.get('X-Ask-Naren-Position')).toBe('1');
    expect(res.headers.get('X-Ask-Naren-Recorded')).toBeNull();
  });

  it('a thread removed while the question was in flight: answer delivered, Recorded: false', async () => {
    const { token, userId } = await signedIn();
    const id = threadOf(await ask(token));
    upstream.mockImplementationOnce(async () => {
      await deleteThread(testDb, userId, id);
      return new Response(JSON.stringify(NO_MATCH), { status: 200 });
    });
    const res = await quietly(() => ask(token, { situation: 'more', thread_id: id }));
    expect(res.status).toBe(200);
    expect(await res.text()).toBe(JSON.stringify(NO_MATCH));
    expect(res.headers.get('X-Ask-Naren-Recorded')).toBe('false');
  });

  it('a service 400 is returned as-is and not stored', async () => {
    const { token, userId } = await signedIn();
    const refusal = { error: 'situation must be a non-empty string' };
    upstream.mockImplementationOnce(async () => new Response(JSON.stringify(refusal), { status: 400 }));
    const res = await ask(token, { situation: '' });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual(refusal);
    expect(res.headers.get('X-Ask-Naren-Thread')).toBeNull();
    expect(res.headers.get('X-Ask-Naren-Recorded')).toBeNull();
    expect(await listThreads(testDb, userId)).toEqual([]);
  });

  it('an unreachable service is a 503 decline, and the outage is recorded as one', async () => {
    const { token, userId } = await signedIn();
    upstream.mockImplementationOnce(async () => {
      throw new TypeError('fetch failed');
    });
    const res = await quietly(() => ask(token));
    expect(res.status).toBe(503);
    const body = await res.json();
    expect(body.reason).toBe('service_unreachable');
    const stored = await loadThread(testDb, userId, threadOf(res));
    expect(stored?.turns[0].response).toEqual(body);
  });

  it('a busy refusal keeps its status, body and Retry-After, and is recorded', async () => {
    const { token } = await signedIn();
    const busy = {
      outcome: 'declined',
      reason: 'service_busy',
      message: 'ask again in about 30 seconds',
      retry_after_seconds: 30,
    };
    upstream.mockImplementationOnce(
      async () => new Response(JSON.stringify(busy), { status: 429, headers: { 'Retry-After': '30' } }),
    );
    const res = await ask(token);
    expect(res.status).toBe(429);
    expect(res.headers.get('Retry-After')).toBe('30');
    expect(await res.text()).toBe(JSON.stringify(busy));
    expect(res.headers.get('X-Ask-Naren-Position')).toBe('1');
  });
});
