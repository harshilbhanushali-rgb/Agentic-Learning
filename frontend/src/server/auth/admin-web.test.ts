// @vitest-environment node
import { beforeAll, beforeEach, describe, expect, it } from 'vitest';

import type { Db } from '../db';
import { freshDb } from '../testing/pglite';
import { adminEmails, isAdmin } from './admin-list';
import { webAddUser, webResetPassword, webSetDisabled } from './admin-web';
import { createSession } from './sessions';
import { authenticate, listUsers } from './users';

describe('who is an admin', () => {
  it('adds a comma-separated list to the built-in admins, ignoring case and spaces', () => {
    const raw = ' Vignesh@joveo.com , harshil.bhanushali@joveo.com,,';
    expect([...adminEmails(raw)]).toEqual(['harshil.bhanushali@joveo.com', 'vignesh@joveo.com']);
    expect(isAdmin('VIGNESH@joveo.com', raw)).toBe(true);
    expect(isAdmin('someone@joveo.com', raw)).toBe(false);
  });

  it('keeps the built-in admins with no setting at all, and no one else', () => {
    expect([...adminEmails(undefined)]).toEqual(['harshil.bhanushali@joveo.com']);
    expect(isAdmin('Harshil.Bhanushali@joveo.com', '')).toBe(true);
    expect(isAdmin('someone@joveo.com', '')).toBe(false);
  });
});

describe('the admin page actions', () => {
  let db: Db;
  let reset: () => Promise<void>;

  beforeAll(async () => {
    ({ db, reset } = await freshDb());
  });
  beforeEach(async () => {
    await reset();
  });

  it('adds a user with a generated password, shown once, that signs in', async () => {
    const r = await webAddUser(db, { email: ' Priya@Joveo.com ', name: 'Priya Sharma', password: '' });
    expect(r.error).toBeNull();
    expect(r.ok).toMatch(/Added priya@joveo.com/);
    expect(r.password).toMatch(/^[A-Za-z0-9_-]{24}$/);
    expect(await authenticate(db, 'priya@joveo.com', r.password!)).not.toBeNull();
  });

  it('adds a user with a typed password and does not echo it back', async () => {
    const r = await webAddUser(db, { email: 'a@joveo.com', name: 'A', password: 'a-long-enough-password' });
    expect(r.password).toBeNull();
    expect(await authenticate(db, 'a@joveo.com', 'a-long-enough-password')).not.toBeNull();
  });

  it('refuses a short password, an outside email and a duplicate, in words', async () => {
    expect((await webAddUser(db, { email: 'a@joveo.com', name: 'A', password: 'short' })).error).toMatch(/at least 12/);
    expect((await webAddUser(db, { email: 'a@gmail.com', name: 'A', password: '' })).error).toMatch(/not a @joveo.com/);
    await webAddUser(db, { email: 'a@joveo.com', name: 'A', password: '' });
    expect((await webAddUser(db, { email: 'A@joveo.com', name: 'A', password: '' })).error).toMatch(/already exists/);
    expect(await listUsers(db)).toHaveLength(1);
  });

  it('resets a password and signs the user out everywhere', async () => {
    await webAddUser(db, { email: 'a@joveo.com', name: 'A', password: 'the-old-password' });
    const [{ id }] = await listUsers(db);
    await createSession(db, id);
    await createSession(db, id);

    const r = await webResetPassword(db, { email: 'a@joveo.com', password: '' });
    expect(r.ok).toMatch(/2 browsers were signed out/);
    expect(await authenticate(db, 'a@joveo.com', 'the-old-password')).toBeNull();
    expect(await authenticate(db, 'a@joveo.com', r.password!)).not.toBeNull();
    expect((await listUsers(db))[0].sessions).toBe(0);
  });

  it('says so when resetting someone who does not exist', async () => {
    expect((await webResetPassword(db, { email: 'nobody@joveo.com', password: '' })).error).toMatch(/No user/);
  });

  it('disables and re-enables a user, but never the admin doing it', async () => {
    await webAddUser(db, { email: 'a@joveo.com', name: 'A', password: 'a-long-enough-password' });

    const self = await webSetDisabled(db, 'A@joveo.com', { email: 'a@joveo.com', disable: true });
    expect(self.error).toMatch(/your own account/);
    expect((await listUsers(db))[0].disabledAt).toBeNull();

    expect((await webSetDisabled(db, 'admin@joveo.com', { email: 'a@joveo.com', disable: true })).ok).toMatch(/Disabled/);
    expect(await authenticate(db, 'a@joveo.com', 'a-long-enough-password')).toBeNull();

    expect((await webSetDisabled(db, 'admin@joveo.com', { email: 'a@joveo.com', disable: false })).ok).toMatch(/Re-enabled/);
    expect(await authenticate(db, 'a@joveo.com', 'a-long-enough-password')).not.toBeNull();
  });
});
