import { afterEach, describe, expect, it, vi } from 'vitest';

import { safeNext, sessionCookieOptions } from './cookie';

describe('safeNext', () => {
  it('keeps a path on this site', () => {
    expect(safeNext('/ask-naren')).toBe('/ask-naren');
    expect(safeNext('/library?tab=cases')).toBe('/library?tab=cases');
  });

  it('refuses anything that could leave the site, and falls back', () => {
    for (const bad of [
      'https://evil.example',
      '//evil.example',
      '/\\evil.example',
      'javascript:alert(1)',
      'ask-naren',
      '/ask\nnaren',
      '',
      undefined,
      ['/ask-naren'],
    ]) {
      expect(safeNext(bad)).toBe('/ask-naren');
    }
  });

  it('never sends a sign-in back to the sign-in page', () => {
    expect(safeNext('/login')).toBe('/ask-naren');
    expect(safeNext('/login?next=/x')).toBe('/ask-naren');
  });
});

describe('session cookie', () => {
  afterEach(() => vi.unstubAllEnvs());

  it('is HttpOnly, Lax, site-wide, and expires at the absolute limit', () => {
    const expiresAt = new Date('2026-10-27T09:00:00Z');
    expect(sessionCookieOptions(expiresAt)).toMatchObject({
      httpOnly: true,
      sameSite: 'lax',
      path: '/',
      expires: expiresAt,
    });
  });

  it('is Secure in production', () => {
    vi.stubEnv('NODE_ENV', 'production');
    expect(sessionCookieOptions(new Date()).secure).toBe(true);
    vi.stubEnv('NODE_ENV', 'development');
    expect(sessionCookieOptions(new Date()).secure).toBe(false);
  });
});
