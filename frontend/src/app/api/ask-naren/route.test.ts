import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { NextRequest } from 'next/server';

import type { Db } from '@/server/db';
import { SESSION_COOKIE } from '@/server/auth/cookie';
import { createSession } from '@/server/auth/sessions';
import { addUser, disableUser } from '@/server/auth/users';
import { freshDb } from '@/server/testing/pglite';

/* The route reaches the database through `db()`; point that at in-process Postgres, and let
 * a test swap in a broken one to play a store outage. */
let current: Db;
vi.mock('@/server/db', () => ({ db: () => current }));

const { POST } = await import('./route');

let testDb: Db;
let reset: () => Promise<void>;
let close: () => Promise<void>;
const upstream = vi.fn<typeof fetch>();

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
  upstream.mockResolvedValue(
    new Response(JSON.stringify({ outcome: 'declined', reason: 'no_close_match', message: 'm' }), {
      status: 200,
    }),
  );
});

function ask(token?: string) {
  return POST(
    new NextRequest('http://localhost/api/ask-naren', {
      method: 'POST',
      body: JSON.stringify({ situation: 'client wants to pause spend' }),
      headers: token ? { cookie: `${SESSION_COOKIE}=${token}` } : {},
    }),
  );
}

async function signedIn(): Promise<string> {
  const id = await addUser(testDb, { email: 'priya@joveo.com', name: 'Priya', password: 'pw-for-tests-1' });
  return (await createSession(testDb, id)).token;
}

describe('POST /api/ask-naren', () => {
  it('without a session: 401, and nothing reaches the service', async () => {
    const res = await ask();
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ error: 'signed_out' });
    expect(upstream).not.toHaveBeenCalled();
  });

  it('with a forged token: 401', async () => {
    await signedIn();
    expect((await ask('A'.repeat(43))).status).toBe(401);
    expect(upstream).not.toHaveBeenCalled();
  });

  it('with a session: proxies the body and returns the service response untouched', async () => {
    const res = await ask(await signedIn());
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ outcome: 'declined', reason: 'no_close_match', message: 'm' });
    expect(upstream).toHaveBeenCalledTimes(1);
    const [, init] = upstream.mock.calls[0];
    expect(init?.body).toBe(JSON.stringify({ situation: 'client wants to pause spend' }));
  });

  it('after offboarding, the same cookie is refused', async () => {
    const token = await signedIn();
    await disableUser(testDb, 'priya@joveo.com');
    expect((await ask(token)).status).toBe(401);
  });

  it('a store fault during the session check is a 500, never a 401', async () => {
    const token = await signedIn();
    current = { query: () => Promise.reject(new Error('connection refused')) };
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {});
    const res = await ask(token);
    quiet.mockRestore();
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({ error: 'session_check_failed' });
    expect(upstream).not.toHaveBeenCalled();
  });
});
