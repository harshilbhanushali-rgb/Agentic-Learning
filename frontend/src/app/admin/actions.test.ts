// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

/* The security property of the /admin page lives here, not in the page: a server action is a
 * public endpoint, so each one must refuse anyone who is not a signed-in admin by itself. */

const getCurrentUser = vi.fn();
const appDb = vi.fn();
const webAddUser = vi.fn();

vi.mock('@/server/auth/current-user', () => ({ getCurrentUser: () => getCurrentUser() }));
vi.mock('@/server/db', () => ({ db: () => appDb() }));
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));
vi.mock('@/server/auth/admin-web', async importOriginal => ({
  ...(await importOriginal<typeof import('@/server/auth/admin-web')>()),
  webAddUser: (...args: unknown[]) => webAddUser(...args),
}));

import { addUserAction } from './actions';
import { EMPTY_RESULT } from '@/server/auth/admin-web-result';

function form(): FormData {
  const f = new FormData();
  f.set('email', 'new@joveo.com');
  f.set('name', 'New Person');
  f.set('password', '');
  return f;
}

beforeEach(() => {
  vi.stubEnv('ASK_NAREN_ADMIN_EMAILS', 'boss@joveo.com');
  appDb.mockReturnValue({ query: vi.fn() });
  webAddUser.mockResolvedValue({ ok: 'Added new@joveo.com.', error: null, password: 'x' });
});

describe('admin server actions', () => {
  it('refuses someone signed out, without touching the database', async () => {
    getCurrentUser.mockResolvedValue(null);
    expect((await addUserAction(EMPTY_RESULT, form())).error).toBe('Only an admin can do that.');
    expect(appDb).not.toHaveBeenCalled();
    expect(webAddUser).not.toHaveBeenCalled();
  });

  it('refuses a signed-in user who is not on the admin list', async () => {
    getCurrentUser.mockResolvedValue({ id: 2, email: 'csm@joveo.com', name: 'CSM' });
    expect((await addUserAction(EMPTY_RESULT, form())).error).toBe('Only an admin can do that.');
    expect(appDb).not.toHaveBeenCalled();
  });

  it('lets an admin through', async () => {
    getCurrentUser.mockResolvedValue({ id: 1, email: 'Boss@joveo.com', name: 'Boss' });
    expect((await addUserAction(EMPTY_RESULT, form())).ok).toBe('Added new@joveo.com.');
    expect(webAddUser).toHaveBeenCalledWith(expect.anything(), {
      email: 'new@joveo.com',
      name: 'New Person',
      password: '',
    });
  });

  it('reports a store fault as a fault, never as "not allowed"', async () => {
    getCurrentUser.mockRejectedValue(new Error('neon down'));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    expect((await addUserAction(EMPTY_RESULT, form())).error).toMatch(/Could not reach the user store/);
  });

  it('reports a missing database setting as a fault', async () => {
    getCurrentUser.mockResolvedValue({ id: 1, email: 'boss@joveo.com', name: 'Boss' });
    appDb.mockImplementation(() => { throw new Error('ASK_NAREN_DATABASE_URL is not set'); });
    vi.spyOn(console, 'error').mockImplementation(() => {});
    expect((await addUserAction(EMPTY_RESULT, form())).error).toMatch(/Could not reach the user store/);
    expect(webAddUser).not.toHaveBeenCalled();
  });
});
