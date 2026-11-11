// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { checkGoogleClaims } from './google';

const NOW = new Date('2026-11-10T09:00:00Z');
const EXPECTED = { clientId: 'client-123.apps.googleusercontent.com', nonce: 'nonce-abc', now: NOW };

/** What Google's token endpoint puts in an ID token for a Joveo Workspace account. */
const CLAIMS = {
  iss: 'https://accounts.google.com',
  aud: 'client-123.apps.googleusercontent.com',
  sub: '110169484474386276334',
  email: 'Priya@joveo.com',
  email_verified: true,
  hd: 'joveo.com',
  nonce: 'nonce-abc',
  iat: NOW.getTime() / 1000 - 5,
  exp: NOW.getTime() / 1000 + 3600,
};

describe('checkGoogleClaims', () => {
  it("accepts Google's answer for a verified Joveo account, issued to this app", () => {
    expect(checkGoogleClaims(CLAIMS, EXPECTED)).toEqual({
      sub: '110169484474386276334',
      email: 'priya@joveo.com',
      name: null,
    });
    // Google's name, when it sends one, is passed on as a label for a first sign-in.
    expect(checkGoogleClaims({ ...CLAIMS, name: ' Priya Shah ' }, EXPECTED)).toMatchObject({ name: 'Priya Shah' });
  });

  it('also accepts the issuer spelled without the scheme, which Google documents as valid', () => {
    expect(checkGoogleClaims({ ...CLAIMS, iss: 'accounts.google.com' }, EXPECTED)).not.toBeNull();
  });

  it.each([
    ['a personal Google account (no Workspace domain)', { hd: undefined, email: 'priya@gmail.com' }],
    ['another Workspace', { hd: 'notjoveo.com', email: 'priya@notjoveo.com' }],
    ['a joveo.com Workspace account whose email is elsewhere', { email: 'priya@gmail.com' }],
    ['an email Google has not verified', { email_verified: false }],
    ['a token issued to a different app', { aud: 'someone-else.apps.googleusercontent.com' }],
    ['a token that has expired', { exp: NOW.getTime() / 1000 - 1 }],
    ['a token from a different sign-in attempt', { nonce: 'nonce-from-elsewhere' }],
    ['a token Google did not issue', { iss: 'https://evil.example.com' }],
    ['a token with no subject', { sub: '' }],
  ])('refuses %s', (_case, change) => {
    expect(checkGoogleClaims({ ...CLAIMS, ...change }, EXPECTED)).toBeNull();
  });

  it('refuses something that is not a claims object at all', () => {
    expect(checkGoogleClaims(null, EXPECTED)).toBeNull();
    expect(checkGoogleClaims('a string', EXPECTED)).toBeNull();
  });
});
