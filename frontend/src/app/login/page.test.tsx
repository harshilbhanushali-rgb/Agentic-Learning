import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

/* A server component: called as the async function it is, and what it returns rendered.
 * `redirect` throws in Next, and is made to here, so "already signed in" cannot fall through
 * to the form. */
const redirect = vi.fn((to: string) => {
  throw new Error(`NEXT_REDIRECT ${to}`);
});
vi.mock('next/navigation', () => ({ redirect: (to: string) => redirect(to) }));

const getCurrentUser = vi.fn();
vi.mock('@/server/auth/current-user', () => ({ getCurrentUser: () => getCurrentUser() }));

vi.mock('@/components/auth/SignInForm', () => ({
  SignInForm: ({ next }: { next: string }) => <form data-testid="sign-in" data-next={next} />,
}));

const { default: LoginPage } = await import('./page');

beforeEach(() => {
  getCurrentUser.mockReset();
  redirect.mockClear();
});

describe('LoginPage', () => {
  it('shows the form, says who to ask instead of offering a reset, and passes a safe next', async () => {
    getCurrentUser.mockResolvedValue(null);
    render(await LoginPage({ searchParams: { next: '/ask-naren' } }));
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByTestId('sign-in')).toHaveAttribute('data-next', '/ask-naren');
    expect(screen.getByText(/Ask the Ask Naren admin/)).toBeInTheDocument();
  });

  it('never passes an off-site or repeated next through to the form', async () => {
    getCurrentUser.mockResolvedValue(null);
    render(await LoginPage({ searchParams: { next: '//evil.example' } }));
    expect(screen.getByTestId('sign-in')).toHaveAttribute('data-next', '/ask-naren');

    render(await LoginPage({ searchParams: { next: ['/a', '/b'] } }));
    expect(screen.getAllByTestId('sign-in')[1]).toHaveAttribute('data-next', '/ask-naren');
  });

  it('offers Google first when it is set up, keeping the password form, and carries next', async () => {
    vi.stubEnv('ASK_NAREN_GOOGLE_CLIENT_ID', 'id');
    vi.stubEnv('ASK_NAREN_GOOGLE_CLIENT_SECRET', 'secret');
    vi.stubEnv('ASK_NAREN_GOOGLE_REDIRECT_URI', 'https://naren-ai.prod.joveo.com/api/auth/google/callback');
    getCurrentUser.mockResolvedValue(null);
    render(await LoginPage({ searchParams: { next: '/ask-naren/threads/4' } }));
    expect(screen.getByRole('link', { name: /Sign in with Google/ })).toHaveAttribute(
      'href',
      '/api/auth/google/start?next=%2Fask-naren%2Fthreads%2F4',
    );
    expect(screen.getByTestId('sign-in')).toBeInTheDocument();
  });

  it('offers no Google button when Google is not set up', async () => {
    vi.stubEnv('ASK_NAREN_GOOGLE_CLIENT_ID', '');
    getCurrentUser.mockResolvedValue(null);
    render(await LoginPage({ searchParams: {} }));
    expect(screen.queryByRole('link', { name: /Sign in with Google/ })).toBeNull();
  });

  it.each([
    ['google_not_set_up', /isn.t set up for Ask Naren yet/],
    ['google_wrong_account', /joveo\.com Google account/],
    ['google_failed', /didn.t finish/],
    ['google_off', /isn.t available/],
    ['unavailable', /fault on our side/],
  ])('explains a Google sign-in that came back with %s', async (error, copy) => {
    getCurrentUser.mockResolvedValue(null);
    render(await LoginPage({ searchParams: { error } }));
    expect(screen.getByRole('alert')).toHaveTextContent(copy);
  });

  it('shows nothing for an error code it does not know -- never the text it was given', async () => {
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
