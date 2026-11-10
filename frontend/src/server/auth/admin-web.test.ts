// @vitest-environment node
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Db } from '../db';
import { freshDb } from '../testing/pglite';
import { isAdmin, isFixedAdmin } from './admin-list';
import { webAddUser, webSetDisabled, webSetRole } from './admin-web';
import { authenticateGoogle, listUsers } from './users';

describe('who is an admin', () => {
  it('is whoever has the admin role', () => {
    expect(isAdmin({ email: 'vignesh@joveo.com', role: 'admin' })).toBe(true);
    expect(isAdmin({ email: 'vignesh@joveo.com', role: 'member' })).toBe(false);
  });

  it('always includes the built-in admin, whatever their role says', () => {
    expect(isFixedAdmin('Harshil.Bhanushali@joveo.com')).toBe(true);
    expect(isAdmin({ email: 'Harshil.Bhanushali@joveo.com', role: 'member' })).toBe(true);
    expect(isFixedAdmin('vignesh@joveo.com')).toBe(false);
  });

  it('no longer reads an email list from the environment', () => {
    vi.stubEnv('ASK_NAREN_ADMIN_EMAILS', 'vignesh@joveo.com');
    expect(isAdmin({ email: 'vignesh@joveo.com', role: 'member' })).toBe(false);
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

  it('adds a member by email and name; they sign in with Google', async () => {
    const r = await webAddUser(db, { email: ' Priya@Joveo.com ', name: 'Priya Sharma' });
    expect(r).toEqual({ ok: 'Added priya@joveo.com. They can sign in with Google now.', error: null });
    expect((await listUsers(db))[0]).toMatchObject({ email: 'priya@joveo.com', role: 'member' });
    expect(await authenticateGoogle(db, { sub: 'g-priya', email: 'priya@joveo.com' })).not.toBeNull();
  });

  it('refuses an outside email and a duplicate, in words', async () => {
    expect((await webAddUser(db, { email: 'a@gmail.com', name: 'A' })).error).toMatch(/not a @joveo.com/);
    await webAddUser(db, { email: 'a@joveo.com', name: 'A' });
    expect((await webAddUser(db, { email: 'A@joveo.com', name: 'A' })).error).toMatch(/already exists/);
    expect(await listUsers(db)).toHaveLength(1);
  });

  it('makes someone an admin and a member again', async () => {
    await webAddUser(db, { email: 'a@joveo.com', name: 'A' });
    expect((await webSetRole(db, 'boss@joveo.com', { email: 'A@joveo.com', role: 'admin' })).ok).toBe(
      'a@joveo.com is now an admin.',
    );
    expect((await listUsers(db))[0].role).toBe('admin');
    expect((await webSetRole(db, 'boss@joveo.com', { email: 'a@joveo.com', role: 'member' })).ok).toBe(
      'a@joveo.com is now a member.',
    );
    expect((await listUsers(db))[0].role).toBe('member');
  });

  it('never changes the role of the admin doing it, or of the built-in admin', async () => {
    await webAddUser(db, { email: 'a@joveo.com', name: 'A' });
    await webAddUser(db, { email: 'harshil.bhanushali@joveo.com', name: 'Harshil' });
    await webSetRole(db, 'boss@joveo.com', { email: 'a@joveo.com', role: 'admin' });

    expect((await webSetRole(db, 'A@joveo.com', { email: 'a@joveo.com', role: 'member' })).error).toMatch(/your own role/);
    expect((await webSetRole(db, 'a@joveo.com', { email: 'harshil.bhanushali@joveo.com', role: 'member' })).error).toMatch(
      /always an admin/,
    );
    expect((await listUsers(db)).map(u => u.role)).toEqual(['admin', 'member']);
  });

  it('refuses an unknown role or person, in words', async () => {
    await webAddUser(db, { email: 'a@joveo.com', name: 'A' });
    expect((await webSetRole(db, 'boss@joveo.com', { email: 'a@joveo.com', role: 'owner' })).error).toMatch(/not a role/);
    expect((await webSetRole(db, 'boss@joveo.com', { email: 'nobody@joveo.com', role: 'admin' })).error).toMatch(/No user/);
  });

  it('disables and re-enables a user, but never the admin doing it or the built-in admin', async () => {
    await webAddUser(db, { email: 'a@joveo.com', name: 'A' });
    await webAddUser(db, { email: 'harshil.bhanushali@joveo.com', name: 'Harshil' });

    const self = await webSetDisabled(db, 'A@joveo.com', { email: 'a@joveo.com', disable: true });
    expect(self.error).toMatch(/your own account/);
    expect((await webSetDisabled(db, 'a@joveo.com', { email: 'harshil.bhanushali@joveo.com', disable: true })).error).toMatch(
      /always an admin/,
    );
    expect((await listUsers(db)).every(u => u.disabledAt === null)).toBe(true);

    expect((await webSetDisabled(db, 'admin@joveo.com', { email: 'a@joveo.com', disable: true })).ok).toMatch(/Disabled/);
    expect(await authenticateGoogle(db, { sub: 'g-a', email: 'a@joveo.com' })).toBeNull();

    expect((await webSetDisabled(db, 'admin@joveo.com', { email: 'a@joveo.com', disable: false })).ok).toMatch(/Re-enabled/);
    expect(await authenticateGoogle(db, { sub: 'g-a', email: 'a@joveo.com' })).not.toBeNull();
  });
});
