// @vitest-environment node
import { createHash } from 'node:crypto';

import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { NextRequest } from 'next/server';

import type { Db } from '@/server/db';
import { freshDb } from '@/server/testing/pglite';

/* Google sign-in end to end: the start address, Google (faked at the network -- the only
 * thing that is), the return address, the real users and sessions tables, and the /admin
 * check that decides a signed-in person's role. */

let current: Db;
vi.mock('@/server/db', () => ({ db: () => current }));

/* For the role check, which reads the session the way every page does: through Next's cookie
 * jar. `cache` is a pass-through for the reason given in current-user.test.ts. */
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
  notFound: () => {
    throw new Error('NEXT_NOT_FOUND');
  },
}));

const { GET: start } = await import('./start/route');
const { GET: callback } = await import('./callback/route');
const { SESSION_COOKIE } = await import('@/server/auth/cookie');
const { validateSession } = await import('@/server/auth/sessions');
const { addUser, disableUser } = await import('@/server/auth/users');
const { requireAdmin } = await import('@/server/auth/admins');

const SITE = 'https://naren-ai.prod.joveo.com';
const CONFIG = {
  ASK_NAREN_GOOGLE_CLIENT_ID: 'client-123.apps.googleusercontent.com',
  ASK_NAREN_GOOGLE_CLIENT_SECRET: 'test-secret-not-real',
  ASK_NAREN_GOOGLE_REDIRECT_URI: `${SITE}/api/auth/google/callback`,
};

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
  await reset();
  jar.clear();
  for (const [k, v] of Object.entries(CONFIG)) vi.stubEnv(k, v);
});

const PRIYA = { email: 'priya@joveo.com', name: 'Priya Shah', password: 'priya-password-1' };
const BOSS = { email: 'boss@joveo.com', name: 'Boss', password: 'boss-password-12' };

/** The cookies a response sets, by name. */
function setCookies(res: Response): Map<string, string> {
  const out = new Map<string, string>();
  for (const line of res.headers.getSetCookie()) {
    const [pair] = line.split(';');
    const i = pair.indexOf('=');
    out.set(pair.slice(0, i), line);
  }
  return out;
}

describe('the start address', () => {
  it('sends the browser to Google for a joveo.com account, remembering this attempt', async () => {
    const res = await start(new NextRequest(`${SITE}/api/auth/google/start?next=/ask-naren/threads/4`));

    expect(res.status).toBe(303);
    const to = new URL(res.headers.get('location')!);
    expect(to.origin + to.pathname).toBe('https://accounts.google.com/o/oauth2/v2/auth');
    expect(to.searchParams.get('client_id')).toBe(CONFIG.ASK_NAREN_GOOGLE_CLIENT_ID);
    expect(to.searchParams.get('redirect_uri')).toBe(CONFIG.ASK_NAREN_GOOGLE_REDIRECT_URI);
    expect(to.searchParams.get('response_type')).toBe('code');
    expect(to.searchParams.get('scope')).toBe('openid email profile');
    expect(to.searchParams.get('hd')).toBe('joveo.com');
    expect(to.searchParams.get('code_challenge_method')).toBe('S256');
    for (const p of ['state', 'nonce', 'code_challenge']) {
      expect(to.searchParams.get(p)).toMatch(/^[A-Za-z0-9_-]{43}$/);
    }

    const flow = [...setCookies(res).values()].find(c => c.includes('ask_naren_google'));
    expect(flow).toMatch(/HttpOnly/i);
    expect(flow).toMatch(/SameSite=lax/i);
    expect(flow).toMatch(/Max-Age=600/i);
    // The secret half of the attempt is in the cookie, never in the URL Google sees.
    expect(res.headers.get('location')).not.toContain('verifier');
  });
});

/** Step 1, as a browser does it: what Google is told, and the cookie the browser keeps. */
async function startAttempt(next = '/ask-naren') {
  const res = await start(new NextRequest(`${SITE}/api/auth/google/start?next=${encodeURIComponent(next)}`));
  const to = new URL(res.headers.get('location')!);
  const [name, line] = [...setCookies(res).entries()].find(([n]) => n.includes('ask_naren_google'))!;
  return {
    state: to.searchParams.get('state')!,
    nonce: to.searchParams.get('nonce')!,
    challenge: to.searchParams.get('code_challenge')!,
    cookie: line.split(';')[0],
    cookieName: name,
  };
}

/** Google's token endpoint, answering with an ID token for this Google account. */
function googleAnswers(claims: Record<string, unknown>) {
  const b64 = (o: unknown) => Buffer.from(JSON.stringify(o)).toString('base64url');
  const now = Math.floor(Date.now() / 1000);
  const idToken = [
    b64({ alg: 'RS256', kid: 'k1', typ: 'JWT' }),
    b64({
      iss: 'https://accounts.google.com',
      aud: CONFIG.ASK_NAREN_GOOGLE_CLIENT_ID,
      email_verified: true,
      hd: 'joveo.com',
      iat: now,
      exp: now + 3600,
      ...claims,
    }),
    'signature-not-checked',
  ].join('.');
  const fetch = vi.fn<typeof globalThis.fetch>(async () =>
    Response.json({ id_token: idToken, access_token: 'ya29.x', token_type: 'Bearer', expires_in: 3599 }),
  );
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

/** Step 3: the browser arriving back from Google. */
function returnFromGoogle(query: string, cookie?: string) {
  return callback(
    new NextRequest(`${SITE}/api/auth/google/callback?${query}`, cookie ? { headers: { cookie } } : undefined),
  );
}

/** The session token a response signed the browser in with, if any. */
function sessionToken(res: Response): string | null {
  const line = setCookies(res).get(SESSION_COOKIE);
  const value = line?.split(';')[0].slice(SESSION_COOKIE.length + 1);
  return value ? value : null;
}

describe('the return address', () => {
  it('signs a seeded user in and lands them where they were going', async () => {
    const id = await addUser(testDb, PRIYA);
    const attempt = await startAttempt('/ask-naren/threads/4');
    const fetch = googleAnswers({ sub: 'g-priya', email: PRIYA.email, nonce: attempt.nonce });

    const res = await returnFromGoogle(`code=auth-code-1&state=${attempt.state}`, attempt.cookie);

    expect(res.status).toBe(303);
    expect(res.headers.get('location')).toBe('/ask-naren/threads/4');
    const token = sessionToken(res);
    expect(token).not.toBeNull();
    expect(await validateSession(testDb, token!)).toEqual({ id, email: PRIYA.email, name: PRIYA.name });
    // The attempt is used up.
    expect(setCookies(res).get(attempt.cookieName)).toMatch(/Max-Age=0|Expires=Thu, 01 Jan 1970/i);

    // The code was swapped with our secret and the attempt's PKCE verifier.
    const [url, init] = fetch.mock.calls[0];
    expect(String(url)).toBe('https://oauth2.googleapis.com/token');
    const body = new URLSearchParams(String(init!.body));
    expect(body.get('code')).toBe('auth-code-1');
    expect(body.get('client_secret')).toBe(CONFIG.ASK_NAREN_GOOGLE_CLIENT_SECRET);
    expect(body.get('redirect_uri')).toBe(CONFIG.ASK_NAREN_GOOGLE_REDIRECT_URI);
    expect(body.get('grant_type')).toBe('authorization_code');
    expect(createHash('sha256').update(body.get('code_verifier')!).digest('base64url')).toBe(attempt.challenge);
  });
});

describe('the return address, refusing', () => {
  /** Every refusal: back to the sign-in page with a reason, nobody signed in, attempt used up. */
  function expectRefused(res: Response, reason: string, cookieName?: string) {
    expect(res.status).toBe(303);
    expect(res.headers.get('location')).toBe(`/login?error=${reason}`);
    expect(sessionToken(res)).toBeNull();
    if (cookieName) expect(setCookies(res).get(cookieName)).toMatch(/Max-Age=0|Expires=Thu, 01 Jan 1970/i);
  }

  it('refuses an answer for an attempt this browser did not start, without asking Google', async () => {
    await addUser(testDb, PRIYA);
    const attempt = await startAttempt();
    const fetch = googleAnswers({ sub: 'g-priya', email: PRIYA.email, nonce: attempt.nonce });

    expectRefused(await returnFromGoogle(`code=c&state=forged-state`, attempt.cookie), 'google_failed', attempt.cookieName);
    expectRefused(await returnFromGoogle(`code=c&state=${attempt.state}`), 'google_failed');
    expectRefused(await returnFromGoogle(`code=c&state=${attempt.state}`, `${attempt.cookieName}=garbage`), 'google_failed');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('treats a cancelled or failed Google step as "try again"', async () => {
    const attempt = await startAttempt();
    const fetch = googleAnswers({});
    expectRefused(
      await returnFromGoogle(`error=access_denied&state=${attempt.state}`, attempt.cookie),
      'google_failed',
      attempt.cookieName,
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it('treats Google refusing the code, or being unreachable, as "try again"', async () => {
    await addUser(testDb, PRIYA);
    vi.spyOn(console, 'error').mockImplementation(() => {});

    let attempt = await startAttempt();
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ error: 'invalid_grant' }, { status: 400 })));
    expectRefused(await returnFromGoogle(`code=used&state=${attempt.state}`, attempt.cookie), 'google_failed');

    attempt = await startAttempt();
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('fetch failed'); }));
    expectRefused(await returnFromGoogle(`code=c&state=${attempt.state}`, attempt.cookie), 'google_failed');
  });

  it('refuses a Google account that is not a verified joveo.com one', async () => {
    await addUser(testDb, PRIYA);
    const attempt = await startAttempt();
    googleAnswers({ sub: 'g-personal', email: 'priya@gmail.com', hd: undefined, nonce: attempt.nonce });
    expectRefused(await returnFromGoogle(`code=c&state=${attempt.state}`, attempt.cookie), 'google_wrong_account');
  });

  it('refuses a token minted for a different attempt', async () => {
    await addUser(testDb, PRIYA);
    const attempt = await startAttempt();
    googleAnswers({ sub: 'g-priya', email: PRIYA.email, nonce: 'someone-elses-nonce' });
    expectRefused(await returnFromGoogle(`code=c&state=${attempt.state}`, attempt.cookie), 'google_wrong_account');
  });

  it('tells a Joveo account with no seeded user, or a disabled one, to ask the admin', async () => {
    let attempt = await startAttempt();
    googleAnswers({ sub: 'g-new', email: 'new@joveo.com', nonce: attempt.nonce });
    expectRefused(await returnFromGoogle(`code=c&state=${attempt.state}`, attempt.cookie), 'google_not_set_up');

    await addUser(testDb, PRIYA);
    await disableUser(testDb, PRIYA.email);
    attempt = await startAttempt();
    googleAnswers({ sub: 'g-priya', email: PRIYA.email, nonce: attempt.nonce });
    expectRefused(await returnFromGoogle(`code=c&state=${attempt.state}`, attempt.cookie), 'google_not_set_up');
  });

  it('reports a store outage as a fault, never as "not set up"', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const attempt = await startAttempt();
    googleAnswers({ sub: 'g-priya', email: PRIYA.email, nonce: attempt.nonce });
    current = { query: async () => { throw new Error('neon down'); } };
    expectRefused(await returnFromGoogle(`code=c&state=${attempt.state}`, attempt.cookie), 'unavailable');
  });

  it('says Google sign-in is off when it is not configured, at either address', async () => {
    const attempt = await startAttempt();
    vi.stubEnv('ASK_NAREN_GOOGLE_CLIENT_SECRET', '');
    expectRefused(await start(new NextRequest(`${SITE}/api/auth/google/start`)), 'google_off');
    expectRefused(await returnFromGoogle(`code=c&state=${attempt.state}`, attempt.cookie), 'google_off');
  });
});

describe('the start address, refusing', () => {
  it('never carries an off-site destination through Google', async () => {
    const attempt = await startAttempt('//evil.example/phish');
    await addUser(testDb, PRIYA);
    googleAnswers({ sub: 'g-priya', email: PRIYA.email, nonce: attempt.nonce });
    const res = await returnFromGoogle(`code=c&state=${attempt.state}`, attempt.cookie);
    expect(res.headers.get('location')).toBe('/ask-naren');
  });
});

describe('roles after a Google sign-in', () => {
  async function signInWithGoogle(user: typeof PRIYA, sub: string): Promise<string> {
    await addUser(testDb, user);
    const attempt = await startAttempt();
    googleAnswers({ sub, email: user.email, nonce: attempt.nonce });
    const token = sessionToken(await returnFromGoogle(`code=c&state=${attempt.state}`, attempt.cookie));
    jar.set(SESSION_COOKIE, token!);
    return token!;
  }

  it('an admin signed in with Google can open /admin', async () => {
    vi.stubEnv('ASK_NAREN_ADMIN_EMAILS', BOSS.email);
    await signInWithGoogle(BOSS, 'g-boss');
    expect(await requireAdmin()).toMatchObject({ email: BOSS.email });
  });

  it('anyone else signed in with Google gets the same 404 a password user does', async () => {
    vi.stubEnv('ASK_NAREN_ADMIN_EMAILS', BOSS.email);
    await signInWithGoogle(PRIYA, 'g-priya');
    await expect(requireAdmin()).rejects.toThrow('NEXT_NOT_FOUND');
  });
});
