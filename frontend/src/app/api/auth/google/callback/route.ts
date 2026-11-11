import { timingSafeEqual } from 'node:crypto';

import { NextResponse, type NextRequest } from 'next/server';

import { db } from '@/server/db';
import { SESSION_COOKIE, sessionCookieOptions } from '@/server/auth/cookie';
import {
  type GoogleSignInError,
  checkGoogleClaims,
  decodeGoogleFlow,
  exchangeGoogleCode,
  googleConfig,
  googleFlowCookieName,
} from '@/server/auth/google';
import { createSession } from '@/server/auth/sessions';
import { authenticateGoogle } from '@/server/auth/users';

/* Per request, always: a GET handler is otherwise built as a static route (see start/route.ts). */
export const dynamic = 'force-dynamic';

/**
 * Step 3 of Google sign-in (src/server/auth/google.ts): Google sends the browser back here.
 * The person ends up signed in with an ordinary session row and cookie, which everything
 * downstream -- the admin check included -- reads the same way.
 *
 * Every way out but success goes back to /login with a reason code the page turns into fixed
 * copy. Never reflected text: this address is reachable by anyone with a link.
 */
export async function GET(request: NextRequest): Promise<Response> {
  const config = googleConfig();
  if (!config) return refuse('google_off');

  const params = request.nextUrl.searchParams;
  const flow = decodeGoogleFlow(request.cookies.get(googleFlowCookieName())?.value);
  const code = params.get('code');
  // The attempt must be one this browser started, or someone else's code could sign this
  // browser in as them. Checked before Google is asked anything.
  if (!flow || !code || params.get('error') || !sameString(params.get('state') ?? '', flow.state)) {
    return refuse('google_failed');
  }

  let claims: unknown;
  try {
    claims = await exchangeGoogleCode(config, code, flow.verifier);
  } catch (cause) {
    console.error('[ask-naren] Google sign-in: the code exchange failed:', cause);
    return refuse('google_failed');
  }
  const identity = checkGoogleClaims(claims, { clientId: config.clientId, nonce: flow.nonce, now: new Date() });
  if (!identity) return refuse('google_wrong_account');

  let session: { token: string; expiresAt: Date };
  try {
    const user = await authenticateGoogle(db(), identity);
    if (!user) return refuse('google_refused');
    session = await createSession(db(), user.id);
  } catch (cause) {
    // A store fault, never phrased as a refusal (issue #40).
    console.error('[ask-naren] Google sign-in failed on the store:', cause);
    return refuse('unavailable');
  }

  const res = seeOther(flow.next);
  res.cookies.delete(googleFlowCookieName());
  res.cookies.set(SESSION_COOKIE, session.token, sessionCookieOptions(session.expiresAt));
  return res;
}

function refuse(reason: GoogleSignInError): NextResponse {
  const res = seeOther(`/login?error=${reason}`);
  res.cookies.delete(googleFlowCookieName());
  return res;
}

function seeOther(location: string): NextResponse {
  return new NextResponse(null, { status: 303, headers: { location } });
}

function sameString(a: string, b: string): boolean {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}
