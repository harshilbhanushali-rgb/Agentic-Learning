// @vitest-environment node
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Db } from '@/server/db';
import { createSession, validateSession } from '@/server/auth/sessions';
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

const { signOut } = await import('./actions');

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

describe('signOut', () => {
  it('ends this browser’s session on the server, drops the cookie and goes to sign in', async () => {
    const userId = await addUser(testDb, { email: 'priya@joveo.com', name: 'Priya' });
    const { token } = await createSession(testDb, userId);
    jar.set('ask_naren_session', token);

    await expect(signOut()).rejects.toMatchObject({ to: '/login' });
    expect(jar.has('ask_naren_session')).toBe(false);
    expect(await validateSession(testDb, token)).toBeNull();
  });

  it('with no cookie, still lands on sign in without a store read', async () => {
    current = { query: () => Promise.reject(new Error('must not be reached')) };
    await expect(signOut()).rejects.toMatchObject({ to: '/login' });
  });
});
