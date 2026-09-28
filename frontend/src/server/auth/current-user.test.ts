// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

/* The cookie and the redirect come from Next; the session lookup is sessions.ts's own job
 * and has its own tests against PGlite. What is under test is the one rule: no cookie, no
 * database read; a cookie, exactly one lookup; a page that needs a user redirects back to
 * itself through sign-in. */
/* `cache` is in the React canary Next 14 vendors for server components, not in the stable
 * react 18.3 this suite runs on. Its per-request memoisation is React's behaviour, not this
 * module's, so a pass-through stands in for it. */
vi.mock('react', async importOriginal => ({
  ...(await importOriginal<typeof import('react')>()),
  cache: <F,>(fn: F) => fn,
}));

const jar = new Map<string, string>();
vi.mock('next/headers', () => ({
  cookies: () => ({ get: (name: string) => (jar.has(name) ? { value: jar.get(name) } : undefined) }),
}));
vi.mock('next/navigation', () => ({
  redirect: (to: string) => {
    throw Object.assign(new Error('NEXT_REDIRECT'), { to });
  },
}));
const theDb = { query: vi.fn() };
vi.mock('../db', () => ({ db: () => theDb }));
const validateSession = vi.fn();
vi.mock('./sessions', () => ({ validateSession: (...a: unknown[]) => validateSession(...a) }));

const { getCurrentUser, requireUser } = await import('./current-user');
const { SESSION_COOKIE } = await import('./cookie');

const USER = { id: 7, email: 'asha@joveo.com', name: 'Asha' };

beforeEach(() => {
  jar.clear();
  validateSession.mockReset();
});

describe('getCurrentUser', () => {
  it('is nobody, without a database read, when there is no cookie', async () => {
    expect(await getCurrentUser()).toBeNull();
    expect(validateSession).not.toHaveBeenCalled();
  });

  it('validates the session cookie', async () => {
    jar.set(SESSION_COOKIE, 'tok');
    validateSession.mockResolvedValue(USER);
    expect(await getCurrentUser()).toEqual(USER);
    expect(validateSession).toHaveBeenCalledWith(theDb, 'tok');
  });
});

describe('requireUser', () => {
  it('returns the signed-in user', async () => {
    jar.set(SESSION_COOKIE, 'tok');
    validateSession.mockResolvedValue(USER);
    expect(await requireUser('/ask-naren')).toEqual(USER);
  });

  it('sends anyone else to sign in, coming back to where they were going', async () => {
    jar.set(SESSION_COOKIE, 'expired');
    validateSession.mockResolvedValue(null);
    await expect(requireUser('/ask-naren')).rejects.toMatchObject({ to: '/login?next=%2Fask-naren' });
  });
});
