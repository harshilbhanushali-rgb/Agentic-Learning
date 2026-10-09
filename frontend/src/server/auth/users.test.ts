// @vitest-environment node
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Db } from '../db';
import { freshDb } from '../testing/pglite';
import * as password from './password';
import { createSession, validateSession } from './sessions';
import {
  UserError,
  addUser,
  authenticate,
  disableUser,
  enableUser,
  listUsers,
  setPassword,
  signOutEverywhere,
} from './users';

// Wraps the real function, so every test still hashes for real; the one below reads the calls.
vi.mock('./password', async importOriginal => {
  const actual = await importOriginal<typeof import('./password')>();
  return { ...actual, verifyPassword: vi.fn(actual.verifyPassword) };
});

let db: Db;
let reset: () => Promise<void>;
let close: () => Promise<void>;

beforeAll(async () => {
  const fresh = await freshDb();
  db = fresh.db;
  reset = fresh.reset;
  close = () => fresh.pg.close();
});
afterAll(() => close());
beforeEach(() => reset());

const PRIYA = { email: 'priya@joveo.com', name: 'Priya Shah', password: 'first-password-1' };

describe('authenticate', () => {
  it('signs in with the password the admin set', async () => {
    const id = await addUser(db, PRIYA);
    expect(await authenticate(db, PRIYA.email, PRIYA.password)).toEqual({ id });
  });

  it('matches the email however it is typed', async () => {
    const id = await addUser(db, PRIYA);
    expect(await authenticate(db, '  Priya@Joveo.COM ', PRIYA.password)).toEqual({ id });
  });

  it('refuses a wrong password, an unknown email, a disabled user and a cleared password alike', async () => {
    await addUser(db, PRIYA);
    await addUser(db, { email: 'gone@joveo.com', name: 'Gone', password: 'gone-password-1' });
    await addUser(db, { email: 'swapped@joveo.com', name: 'Swapped', password: 'swap-password-1' });
    await disableUser(db, 'gone@joveo.com');
    await db.query(
      "update ask_naren.users set password_hash = null where email = 'swapped@joveo.com'",
    );

    expect(await authenticate(db, PRIYA.email, 'not-her-password')).toBeNull();
    expect(await authenticate(db, 'nobody@joveo.com', PRIYA.password)).toBeNull();
    expect(await authenticate(db, 'gone@joveo.com', 'gone-password-1')).toBeNull();
    expect(await authenticate(db, 'swapped@joveo.com', 'swap-password-1')).toBeNull();
  });

  it('does the same scrypt work for an unknown email, so timing does not reveal who exists', async () => {
    const verify = vi.mocked(password.verifyPassword);
    verify.mockClear();
    await authenticate(db, 'nobody@joveo.com', 'whatever');
    expect(verify).toHaveBeenCalledTimes(1);
    expect(verify.mock.calls[0][1]).toBe(await password.dummyHash());
  });
});

describe('admin operations', () => {
  it('only seeds @joveo.com users, once each, with a name', async () => {
    await expect(addUser(db, { ...PRIYA, email: 'priya@gmail.com' })).rejects.toThrow(UserError);
    await expect(addUser(db, { ...PRIYA, email: 'priya@notjoveo.com' })).rejects.toThrow(UserError);
    await expect(addUser(db, { ...PRIYA, name: '  ' })).rejects.toThrow(UserError);
    await addUser(db, PRIYA);
    await expect(addUser(db, { ...PRIYA, email: 'PRIYA@joveo.com' })).rejects.toThrow('already exists');
  });

  it('never stores the password itself', async () => {
    await addUser(db, PRIYA);
    const { rows } = await db.query('select * from ask_naren.users');
    expect(JSON.stringify(rows)).not.toContain(PRIYA.password);
  });

  it('a new password replaces the old one and signs the user out everywhere', async () => {
    const id = await addUser(db, PRIYA);
    const laptop = await createSession(db, id);
    const phone = await createSession(db, id);
    expect(await setPassword(db, PRIYA.email, 'second-password-2')).toBe(2);
    expect(await authenticate(db, PRIYA.email, PRIYA.password)).toBeNull();
    expect(await authenticate(db, PRIYA.email, 'second-password-2')).toEqual({ id });
    expect(await validateSession(db, laptop.token)).toBeNull();
    expect(await validateSession(db, phone.token)).toBeNull();
  });

  it('offboarding disables AND signs out, and keeps the user row', async () => {
    const id = await addUser(db, PRIYA);
    const { token } = await createSession(db, id);
    expect(await disableUser(db, PRIYA.email)).toBe(1);
    expect(await validateSession(db, token)).toBeNull();
    expect(await authenticate(db, PRIYA.email, PRIYA.password)).toBeNull();
    const [row] = await listUsers(db);
    expect(row).toMatchObject({ email: PRIYA.email, sessions: 0 });
    expect(row.disabledAt).toBeInstanceOf(Date);

    await enableUser(db, PRIYA.email);
    expect(await authenticate(db, PRIYA.email, PRIYA.password)).toEqual({ id });
  });

  it('disabling twice keeps the original offboarding date', async () => {
    await addUser(db, PRIYA);
    await disableUser(db, PRIYA.email);
    const first = (await listUsers(db))[0].disabledAt;
    await disableUser(db, PRIYA.email);
    expect((await listUsers(db))[0].disabledAt).toEqual(first);
  });

  it('signing out everywhere ends sessions without touching the password', async () => {
    const id = await addUser(db, PRIYA);
    await createSession(db, id);
    expect(await signOutEverywhere(db, PRIYA.email)).toBe(1);
    expect(await authenticate(db, PRIYA.email, PRIYA.password)).toEqual({ id });
  });

  it('names the missing user rather than silently doing nothing', async () => {
    await expect(disableUser(db, 'nobody@joveo.com')).rejects.toThrow('No user with email');
    await expect(setPassword(db, 'nobody@joveo.com', 'x'.repeat(12))).rejects.toThrow(UserError);
  });
});
