import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Db } from '@/server/db';
import { addUser } from '@/server/auth/users';
import { freshDb } from '@/server/testing/pglite';

/* Server actions reach cookies and redirect through Next; stand both in, and point `db()` at
 * in-process Postgres -- or at a broken one, to play an outage. */
const jar = new Map<string, string>();
vi.mock('next/headers', () => ({
  cookies: () => ({
    get: (name: string) => (jar.has(name) ? { value: jar.get(name) } : undefined),
    set: (name: string, value: string) => jar.set(name, value),
    delete: (name: string) => jar.delete(name),
  }),
}));
vi.mock('next/navigation', () => ({
  redirect: (to: string) => {
    throw Object.assign(new Error('NEXT_REDIRECT'), { to });
  },
}));
let current: Db;
vi.mock('@/server/db', () => ({ db: () => current }));

const { signIn } = await import('./actions');

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
  jar.clear();
  await reset();
});

function form(email: string, password: string, next = '/ask-naren') {
  const f = new FormData();
  f.set('email', email);
  f.set('password', password);
  f.set('next', next);
  return f;
}

describe('signIn', () => {
  it('signs in, sets the cookie and redirects to next', async () => {
    await addUser(testDb, { email: 'priya@joveo.com', name: 'Priya', password: 'pw-for-tests-1' });
    await expect(signIn({ error: null }, form('priya@joveo.com', 'pw-for-tests-1'))).rejects.toMatchObject({
      to: '/ask-naren',
    });
    expect(jar.get('ask_naren_session')).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });

  it('a wrong password is the refusal', async () => {
    await addUser(testDb, { email: 'priya@joveo.com', name: 'Priya', password: 'pw-for-tests-1' });
    expect(await signIn({ error: null }, form('priya@joveo.com', 'nope'))).toEqual({
      error: 'That email and password do not match a Joveo user.',
    });
  });

  it('a store outage says so, and never reads as a wrong password', async () => {
    current = { query: () => Promise.reject(new Error('connection refused')) };
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {});
    const result = await signIn({ error: null }, form('priya@joveo.com', 'pw-for-tests-1'));
    quiet.mockRestore();
    expect(result.error).toMatch(/^Sign-in is unavailable right now/);
    expect(result.error).not.toMatch(/do not match/);
    expect(jar.size).toBe(0);
  });
});
