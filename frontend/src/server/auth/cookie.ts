/**
 * The session cookie (ADR 0011). Kept free of Next imports so the route, the server actions
 * and the tests all read the same name and flags.
 */
export const SESSION_COOKIE = 'ask_naren_session';

export function sessionCookieOptions(expiresAt: Date) {
  return {
    // Script on the page can never read it -- the token is the whole of a sign-in.
    httpOnly: true,
    // Sent on top-level navigations from elsewhere (a link in Slack still lands signed in),
    // not on cross-site subrequests.
    sameSite: 'lax' as const,
    // Off only in development, where the app is served over plain http://localhost.
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    // The absolute limit. The idle limit is enforced by the server, which is the only place
    // it can be, since the cookie cannot know when it was last used.
    expires: expiresAt,
  };
}

/** Where a sign-in may send someone afterwards: a path on this site, nothing else. A `next`
 *  that could name another origin would make the sign-in page an open redirect. */
export function safeNext(raw: unknown, fallback = '/ask-naren'): string {
  if (typeof raw !== 'string') return fallback;
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) return fallback;
  if (/[\u0000-\u001f]/.test(raw)) return fallback;
  if (raw === '/login' || raw.startsWith('/login?') || raw.startsWith('/login/')) return fallback;
  return raw;
}
