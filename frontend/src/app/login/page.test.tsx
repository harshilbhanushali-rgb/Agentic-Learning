import { describe, it, expect, vi, beforeEach } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

/* A server component: called as the async function it is, and what it returns rendered.
 * `redirect` throws in Next, and is made to here, so "already signed in" cannot fall through
 * to the form. */
const redirect = vi.fn((to: string) => {
  throw new Error(`NEXT_REDIRECT ${to}`);
});
vi.mock('next/navigation', () => ({ redirect: (to: string) => redirect(to) }));

const getCurrentUser = vi.fn();
vi.mock('@/server/auth/current-user', () => ({ getCurrentUser: () => getCurrentUser() }));

const { default: LoginPage } = await import('./page');

beforeEach(() => {
  getCurrentUser.mockReset();
  redirect.mockClear();
});

function googleOn() {
  vi.stubEnv('ASK_NAREN_GOOGLE_CLIENT_ID', 'id');
  vi.stubEnv('ASK_NAREN_GOOGLE_CLIENT_SECRET', 'secret');
  vi.stubEnv('ASK_NAREN_GOOGLE_REDIRECT_URI', 'https://naren-ai.prod.joveo.com/api/auth/google/callback');
}

describe('LoginPage', () => {
  it('signs in with Google only, carrying a safe next, and says who to ask', async () => {
    googleOn();
    getCurrentUser.mockResolvedValue(null);
    render(await LoginPage({ searchParams: { next: '/ask-naren/threads/4' } }));
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Sign in with Google/ })).toHaveAttribute(
      'href',
      '/api/auth/google/start?next=%2Fask-naren%2Fthreads%2F4',
    );
    expect(screen.queryByLabelText(/password/i)).toBeNull();
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.getByText(/Ask the Ask Naren admin/)).toBeInTheDocument();
  });

  it('never carries an off-site or repeated next through to Google', async () => {
    googleOn();
    getCurrentUser.mockResolvedValue(null);
    render(await LoginPage({ searchParams: { next: '//evil.example' } }));
    expect(screen.getByRole('link', { name: /Sign in with Google/ })).toHaveAttribute(
      'href',
      '/api/auth/google/start?next=%2Fask-naren',
    );
    cleanup();
    render(await LoginPage({ searchParams: { next: ['/a', '/b'] } }));
    expect(screen.getByRole('link', { name: /Sign in with Google/ })).toHaveAttribute(
      'href',
      '/api/auth/google/start?next=%2Fask-naren',
    );
  });

  it('says sign-in is not set up, rather than showing an empty page, when Google is off', async () => {
    vi.stubEnv('ASK_NAREN_GOOGLE_CLIENT_ID', '');
    getCurrentUser.mockResolvedValue(null);
    render(await LoginPage({ searchParams: {} }));
    expect(screen.queryByRole('link', { name: /Sign in with Google/ })).toBeNull();
    expect(screen.getByRole('alert')).toHaveTextContent(/isn.t set up on this site/);
  });

  it.each([
    ['google_not_set_up', /isn.t set up for Ask Naren yet/],
    ['google_wrong_account', /joveo\.com Google account/],
    ['google_failed', /didn.t finish/],
    ['google_off', /isn.t available/],
    ['unavailable', /fault on our side/],
  ])('explains a Google sign-in that came back with %s', async (error, copy) => {
    googleOn();
    getCurrentUser.mockResolvedValue(null);
    render(await LoginPage({ searchParams: { error } }));
    expect(screen.getByRole('alert')).toHaveTextContent(copy);
  });

  it('shows nothing for an error code it does not know -- never the text it was given', async () => {
    googleOn();
    getCurrentUser.mockResolvedValue(null);
    render(await LoginPage({ searchParams: { error: 'Your account is locked, call 555-0100' } }));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(/555-0100/)).toBeNull();
  });

  it('sends someone already signed in straight on', async () => {
    getCurrentUser.mockResolvedValue({ id: 1, name: 'A', email: 'a@joveo.com' });
    await expect(LoginPage({ searchParams: { next: '/ask-naren' } })).rejects.toThrow('NEXT_REDIRECT /ask-naren');
    expect(redirect).toHaveBeenCalledWith('/ask-naren');
  });
});
