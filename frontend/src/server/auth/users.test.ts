// @vitest-environment node
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import type { Db } from '../db';
import { freshDb } from '../testing/pglite';
import { createSession, validateSession } from './sessions';
import {
  UserError,
  addUser,
  authenticateGoogle,
  disableUser,
  enableUser,
  listUsers,
  setRole,
  signOutEverywhere,
} from './users';

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

const PRIYA = { email: 'priya@joveo.com', name: 'Priya Shah' };

describe('authenticateGoogle', () => {
  it("links a seeded user's Google identity at first sign-in, then matches on it", async () => {
    const id = await addUser(db, PRIYA);
    expect(await authenticateGoogle(db, { sub: 'g-priya', email: 'Priya@joveo.com' })).toEqual({ id });
    // Google says an email can change; the identity it promises is stable is `sub`.
    expect(await authenticateGoogle(db, { sub: 'g-priya', email: 'priya.shah@joveo.com' })).toEqual({ id });
  });

  it('refuses a Google account with no seeded user, and creates nobody', async () => {
    expect(await authenticateGoogle(db, { sub: 'g-new', email: 'new@joveo.com' })).toBeNull();
    expect(await listUsers(db)).toEqual([]);
  });

  it('refuses a disabled user, whether or not their Google identity is linked yet', async () => {
    await addUser(db, PRIYA);
    await addUser(db, { email: 'gone@joveo.com', name: 'Gone' });
    expect(await authenticateGoogle(db, { sub: 'g-priya', email: PRIYA.email })).not.toBeNull();
    await disableUser(db, PRIYA.email);
    await disableUser(db, 'gone@joveo.com');

    expect(await authenticateGoogle(db, { sub: 'g-priya', email: PRIYA.email })).toBeNull();
    expect(await authenticateGoogle(db, { sub: 'g-gone', email: 'gone@joveo.com' })).toBeNull();
  });

  it('refuses a second Google identity claiming an email that is already linked', async () => {
    const id = await addUser(db, PRIYA);
    await authenticateGoogle(db, { sub: 'g-priya', email: PRIYA.email });
    expect(await authenticateGoogle(db, { sub: 'g-impostor', email: PRIYA.email })).toBeNull();
    expect(await authenticateGoogle(db, { sub: 'g-priya', email: PRIYA.email })).toEqual({ id });
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

  it('offboarding disables AND signs out, and keeps the user row', async () => {
    const id = await addUser(db, PRIYA);
    const { token } = await createSession(db, id);
    expect(await disableUser(db, PRIYA.email)).toBe(1);
    expect(await validateSession(db, token)).toBeNull();
    expect(await authenticateGoogle(db, { sub: 'g-priya', email: PRIYA.email })).toBeNull();
    const [row] = await listUsers(db);
    expect(row).toMatchObject({ email: PRIYA.email, sessions: 0 });
    expect(row.disabledAt).toBeInstanceOf(Date);

    await enableUser(db, PRIYA.email);
    expect(await authenticateGoogle(db, { sub: 'g-priya', email: PRIYA.email })).toEqual({ id });
  });

  it('disabling twice keeps the original offboarding date', async () => {
    await addUser(db, PRIYA);
    await disableUser(db, PRIYA.email);
    const first = (await listUsers(db))[0].disabledAt;
    await disableUser(db, PRIYA.email);
    expect((await listUsers(db))[0].disabledAt).toEqual(first);
  });

  it('signing out everywhere ends sessions and leaves the user able to sign in again', async () => {
    const id = await addUser(db, PRIYA);
    await createSession(db, id);
    expect(await signOutEverywhere(db, PRIYA.email)).toBe(1);
    expect(await authenticateGoogle(db, { sub: 'g-priya', email: PRIYA.email })).toEqual({ id });
  });

  it('a new user has no password and has not linked Google yet', async () => {
    await addUser(db, PRIYA);
    expect((await listUsers(db))[0]).toMatchObject({ googleLinked: false });
    await authenticateGoogle(db, { sub: 'g-priya', email: PRIYA.email });
    expect((await listUsers(db))[0]).toMatchObject({ googleLinked: true });
    const { rows } = await db.query<{ password_hash: string | null }>('select password_hash from ask_naren.users');
    expect(rows[0].password_hash).toBeNull();
  });

  it('a new user is a member; an admin can be made, and made a member again', async () => {
    await addUser(db, PRIYA);
    expect((await listUsers(db))[0].role).toBe('member');
    await setRole(db, 'Priya@joveo.com', 'admin');
    expect((await listUsers(db))[0].role).toBe('admin');
    await setRole(db, PRIYA.email, 'member');
    expect((await listUsers(db))[0].role).toBe('member');
  });

  it('knows only the two roles', async () => {
    await addUser(db, PRIYA);
    await expect(setRole(db, PRIYA.email, 'owner' as 'admin')).rejects.toThrow(UserError);
    await expect(setRole(db, 'nobody@joveo.com', 'admin')).rejects.toThrow('No user with email');
  });

  it('a signed-in user carries their role, so asking "admin?" needs no second read', async () => {
    const id = await addUser(db, PRIYA);
    const { token } = await createSession(db, id);
    expect(await validateSession(db, token)).toMatchObject({ email: PRIYA.email, role: 'member' });
    await setRole(db, PRIYA.email, 'admin');
    expect(await validateSession(db, token)).toMatchObject({ role: 'admin' });
  });

  it('names the missing user rather than silently doing nothing', async () => {
    await expect(disableUser(db, 'nobody@joveo.com')).rejects.toThrow('No user with email');
    await expect(setRole(db, 'nobody@joveo.com', 'admin')).rejects.toThrow(UserError);
  });
});
