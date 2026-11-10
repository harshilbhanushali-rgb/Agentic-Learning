// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

/* The security property of the /admin page lives here, not in the page: a server action is a
 * public endpoint, so each one must refuse anyone who is not a signed-in admin by itself. */

const getCurrentUser = vi.fn();
const appDb = vi.fn();
const webAddUser = vi.fn();
const webSetRole = vi.fn();

vi.mock('@/server/auth/current-user', () => ({ getCurrentUser: () => getCurrentUser() }));
vi.mock('@/server/db', () => ({ db: () => appDb() }));
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));
vi.mock('@/server/auth/admin-web', async importOriginal => ({
  ...(await importOriginal<typeof import('@/server/auth/admin-web')>()),
  webAddUser: (...args: unknown[]) => webAddUser(...args),
  webSetRole: (...args: unknown[]) => webSetRole(...args),
}));

import { addUserAction, setRoleAction } from './actions';
import { EMPTY_RESULT } from '@/server/auth/admin-web-result';

const ADMIN = { id: 1, email: 'boss@joveo.com', name: 'Boss', role: 'admin' };
const MEMBER = { id: 2, email: 'csm@joveo.com', name: 'CSM', role: 'member' };

function form(fields: Record<string, string> = { email: 'new@joveo.com', name: 'New Person' }): FormData {
  const f = new FormData();
  for (const [k, v] of Object.entries(fields)) f.set(k, v);
  return f;
}

beforeEach(() => {
  appDb.mockReturnValue({ query: vi.fn() });
  webAddUser.mockResolvedValue({ ok: 'Added new@joveo.com.', error: null });
  webSetRole.mockResolvedValue({ ok: 'csm@joveo.com is now an admin.', error: null });
});

describe('admin server actions', () => {
  it('refuses someone signed out, without touching the database', async () => {
    getCurrentUser.mockResolvedValue(null);
    expect((await addUserAction(EMPTY_RESULT, form())).error).toBe('Only an admin can do that.');
    expect((await setRoleAction(EMPTY_RESULT, form({ email: 'x@joveo.com', role: 'admin' }))).error).toBe(
      'Only an admin can do that.',
    );
    expect(appDb).not.toHaveBeenCalled();
    expect(webAddUser).not.toHaveBeenCalled();
    expect(webSetRole).not.toHaveBeenCalled();
  });

  it('refuses a signed-in member -- they cannot make themselves an admin', async () => {
    getCurrentUser.mockResolvedValue(MEMBER);
    expect((await addUserAction(EMPTY_RESULT, form())).error).toBe('Only an admin can do that.');
    expect((await setRoleAction(EMPTY_RESULT, form({ email: MEMBER.email, role: 'admin' }))).error).toBe(
      'Only an admin can do that.',
    );
    expect(appDb).not.toHaveBeenCalled();
  });

  it('lets an admin add a user by email and name', async () => {
    getCurrentUser.mockResolvedValue(ADMIN);
    expect((await addUserAction(EMPTY_RESULT, form())).ok).toBe('Added new@joveo.com.');
    expect(webAddUser).toHaveBeenCalledWith(expect.anything(), { email: 'new@joveo.com', name: 'New Person' });
  });

  it('lets an admin set a role, naming themselves as the one doing it', async () => {
    getCurrentUser.mockResolvedValue(ADMIN);
    const r = await setRoleAction(EMPTY_RESULT, form({ email: 'csm@joveo.com', role: 'admin' }));
    expect(r.ok).toBe('csm@joveo.com is now an admin.');
    expect(webSetRole).toHaveBeenCalledWith(expect.anything(), ADMIN.email, { email: 'csm@joveo.com', role: 'admin' });
  });

  it('lets the built-in admin in even while their role says member', async () => {
    getCurrentUser.mockResolvedValue({ id: 3, email: 'harshil.bhanushali@joveo.com', name: 'H', role: 'member' });
    expect((await addUserAction(EMPTY_RESULT, form())).ok).toBe('Added new@joveo.com.');
  });

  it('reports a store fault as a fault, never as "not allowed"', async () => {
    getCurrentUser.mockRejectedValue(new Error('neon down'));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    expect((await addUserAction(EMPTY_RESULT, form())).error).toMatch(/Could not reach the user store/);
  });

  it('reports a missing database setting as a fault', async () => {
    getCurrentUser.mockResolvedValue(ADMIN);
    appDb.mockImplementation(() => { throw new Error('ASK_NAREN_DATABASE_URL is not set'); });
    vi.spyOn(console, 'error').mockImplementation(() => {});
    expect((await addUserAction(EMPTY_RESULT, form())).error).toMatch(/Could not reach the user store/);
    expect(webAddUser).not.toHaveBeenCalled();
  });
});
