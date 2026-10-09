// @vitest-environment node
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Db } from '@/server/db';
import { createSession, validateSession } from '@/server/auth/sessions';
import { MAX_PASSWORD_LENGTH } from '@/server/auth/password';
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

const { signIn, signOut } = await import('./actions');

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

  it('asks for both fields before touching the store', async () => {
    current = { query: () => Promise.reject(new Error('must not be reached')) };
    const blank = { error: 'Enter your email and password.' };
    expect(await signIn({ error: null }, form('   ', 'pw-for-tests-1'))).toEqual(blank);
    expect(await signIn({ error: null }, form('priya@joveo.com', ''))).toEqual(blank);
    expect(await signIn({ error: null }, new FormData())).toEqual(blank);
  });

  it('refuses an over-long password without hashing it, in the same words as a wrong one', async () => {
    current = { query: () => Promise.reject(new Error('must not be reached')) };
    expect(await signIn({ error: null }, form('priya@joveo.com', 'x'.repeat(MAX_PASSWORD_LENGTH + 1)))).toEqual({
      error: 'That email and password do not match a Joveo user.',
    });
  });

  it('never redirects off-site after signing in', async () => {
    await addUser(testDb, { email: 'priya@joveo.com', name: 'Priya', password: 'pw-for-tests-1' });
    await expect(
      signIn({ error: null }, form('priya@joveo.com', 'pw-for-tests-1', '//evil.example')),
    ).rejects.toMatchObject({ to: '/ask-naren' });
  });
});

describe('signOut', () => {
  it('ends this browser’s session on the server, drops the cookie and goes to sign in', async () => {
    const userId = await addUser(testDb, { email: 'priya@joveo.com', name: 'Priya', password: 'pw-for-tests-1' });
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
