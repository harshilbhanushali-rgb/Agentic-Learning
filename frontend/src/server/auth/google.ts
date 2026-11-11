import { createHash, randomBytes } from 'node:crypto';

import { safeNext } from './cookie';
import { isJoveoEmail, normalizeEmail } from './users';

/**
 * Google sign-in (ADR 0011, "The Google Workspace swap"; ADR 0017).
 *
 * The OpenID Connect authorization-code flow, by hand, as the rest of sign-in is (ADR 0011):
 *   1. /api/auth/google/start  -- remembers this attempt in a short cookie, sends the browser
 *                                 to Google.
 *   2. Google                  -- the person picks their joveo.com account.
 *   3. /api/auth/google/callback -- checks the answer belongs to the attempt, swaps the code
 *                                 for an ID token with our secret, checks the token, finds or
 *                                 adds the user (ADR 0019), and starts an ordinary session.
 */

/** The Workspace whose accounts may sign in. `hd` is Google's own statement of it. */
export const JOVEO_DOMAIN = 'joveo.com';

export const GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth';
export const GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token';

export interface GoogleConfig {
  clientId: string;
  clientSecret: string;
  /** Exactly as registered with Google -- it is compared character for character. */
  redirectUri: string;
}

/**
 * The OAuth client, or null when Google sign-in is not set up -- then the sign-in page says so,
 * because there is no other way in (ADR 0018). All three or nothing: the redirect address is set
 * explicitly rather than worked out from the request, because behind the deployment's proxy
 * the request's own host is not the public one Google was told about.
 */
export function googleConfig(env: NodeJS.ProcessEnv = process.env): GoogleConfig | null {
  const clientId = env.ASK_NAREN_GOOGLE_CLIENT_ID?.trim();
  const clientSecret = env.ASK_NAREN_GOOGLE_CLIENT_SECRET?.trim();
  const redirectUri = env.ASK_NAREN_GOOGLE_REDIRECT_URI?.trim();
  if (!clientId || !clientSecret || !redirectUri) return null;
  return { clientId, clientSecret, redirectUri };
}

/** One sign-in attempt: what the return address checks Google's answer against. */
export interface GoogleFlow {
  /** Echoed back by Google; proves the answer is for an attempt this browser started. */
  state: string;
  /** Echoed inside the ID token; proves the token was minted for this attempt. */
  nonce: string;
  /** PKCE: only its hash goes to Google, so a stolen code is useless without this cookie. */
  verifier: string;
  /** Where to land afterwards. */
  next: string;
}

/**
 * The cookie that carries a GoogleFlow between steps 1 and 3. In production its name has the
 * `__Host-` prefix, which browsers refuse to accept from any other *.joveo.com site -- without
 * it, a sibling subdomain could plant an attempt of its own and sign a CSM in as someone else.
 */
export function googleFlowCookieName(): string {
  return process.env.NODE_ENV === 'production' ? '__Host-ask_naren_google' : 'ask_naren_google';
}

/** Ten minutes to pick an account; an attempt left longer than that starts again. */
export const GOOGLE_FLOW_MAX_AGE_S = 600;

export function googleFlowCookieOptions() {
  return {
    httpOnly: true,
    // Lax, not Strict: Google's redirect back is a cross-site top-level navigation, and Strict
    // would leave the cookie behind on exactly that request.
    sameSite: 'lax' as const,
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: GOOGLE_FLOW_MAX_AGE_S,
  };
}

const randomToken = () => randomBytes(32).toString('base64url');

export function newGoogleFlow(rawNext: unknown): GoogleFlow {
  return { state: randomToken(), nonce: randomToken(), verifier: randomToken(), next: safeNext(rawNext) };
}

export function encodeGoogleFlow(flow: GoogleFlow): string {
  return Buffer.from(JSON.stringify(flow)).toString('base64url');
}

export function decodeGoogleFlow(raw: string | undefined): GoogleFlow | null {
  if (!raw) return null;
  try {
    const f = JSON.parse(Buffer.from(raw, 'base64url').toString('utf8')) as Record<string, unknown>;
    if (typeof f.state !== 'string' || typeof f.nonce !== 'string' || typeof f.verifier !== 'string') {
      return null;
    }
    return { state: f.state, nonce: f.nonce, verifier: f.verifier, next: safeNext(f.next) };
  } catch {
    return null;
  }
}

/** Where step 1 sends the browser. */
export function googleAuthUrl(config: GoogleConfig, flow: GoogleFlow): string {
  const url = new URL(GOOGLE_AUTH_URL);
  url.search = new URLSearchParams({
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    response_type: 'code',
    scope: 'openid email profile',
    state: flow.state,
    nonce: flow.nonce,
    code_challenge: createHash('sha256').update(flow.verifier).digest('base64url'),
    code_challenge_method: 'S256',
    // A hint that narrows Google's account picker to joveo.com. NOT a check -- anyone can
    // edit the URL -- which is why checkGoogleClaims insists on `hd` in the token itself.
    hd: JOVEO_DOMAIN,
    prompt: 'select_account',
  }).toString();
  return url.toString();
}

/**
 * Step 3's exchange: the one-time code for the ID token's claims (still to be checked by
 * checkGoogleClaims). Throws on anything but a well-formed answer from Google.
 */
export async function exchangeGoogleCode(
  config: GoogleConfig,
  code: string,
  verifier: string,
): Promise<unknown> {
  const res = await fetch(GOOGLE_TOKEN_URL, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      code,
      client_id: config.clientId,
      client_secret: config.clientSecret,
      redirect_uri: config.redirectUri,
      grant_type: 'authorization_code',
      code_verifier: verifier,
    }).toString(),
    signal: AbortSignal.timeout(10_000),
  });
  if (!res.ok) throw new Error(`Google's token endpoint answered ${res.status}: ${await res.text()}`);
  const body = (await res.json()) as { id_token?: unknown };
  const parts = typeof body.id_token === 'string' ? body.id_token.split('.') : [];
  if (parts.length !== 3) throw new Error("Google's token endpoint returned no ID token.");
  return JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'));
}

/**
 * Why a Google sign-in went back to /login. The page turns each into fixed copy.
 *   google_off           -- Google sign-in is not configured on this deployment.
 *   google_failed        -- the round trip did not complete (cancelled, expired, Google down):
 *                           try again.
 *   google_wrong_account -- Google answered for an account that is not a verified joveo.com one.
 *   google_refused       -- a Joveo account that may not sign in: disabled by an admin, or
 *                           its email is already linked to a different Google account.
 *   unavailable          -- our store failed: a fault, not the person's account.
 */
export type GoogleSignInError =
  | 'google_off'
  | 'google_failed'
  | 'google_wrong_account'
  | 'google_refused'
  | 'unavailable';

const GOOGLE_ISSUERS = new Set(['https://accounts.google.com', 'accounts.google.com']);

/**
 * The identity Google vouches for, or null. `claims` is the payload of the ID token this app
 * received from Google's token endpoint.
 *
 * NO SIGNATURE CHECK, deliberately: the token came straight from Google's token endpoint over
 * TLS, in answer to a request authenticated with our client secret, so TLS has already proved
 * who issued it (OpenID Connect Core 3.1.3.7; Google's own OIDC guide says the same). What
 * TLS cannot prove is that the token is for THIS app, THIS sign-in attempt, still valid, and
 * a verified Joveo account -- those are checked here.
 */
export function checkGoogleClaims(
  claims: unknown,
  expected: { clientId: string; nonce: string; now: Date },
): { sub: string; email: string; name: string | null } | null {
  if (typeof claims !== 'object' || claims === null) return null;
  const c = claims as Record<string, unknown>;
  const email = typeof c.email === 'string' ? normalizeEmail(c.email) : '';
  const ok =
    typeof c.iss === 'string' && GOOGLE_ISSUERS.has(c.iss) &&
    c.aud === expected.clientId &&
    typeof c.exp === 'number' && c.exp * 1000 > expected.now.getTime() &&
    c.nonce === expected.nonce &&
    typeof c.sub === 'string' && c.sub.length > 0 &&
    c.hd === JOVEO_DOMAIN &&
    // Google sends a boolean; an older format sent the string. Both mean verified.
    (c.email_verified === true || c.email_verified === 'true') &&
    isJoveoEmail(email);
  // The name is only a label for a first sign-in (ADR 0019), never a check.
  const name = typeof c.name === 'string' && c.name.trim() ? c.name.trim() : null;
  return ok ? { sub: c.sub as string, email, name } : null;
}
