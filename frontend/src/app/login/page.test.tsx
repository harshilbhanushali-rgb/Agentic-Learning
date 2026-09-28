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

  it('sends someone already signed in straight on', async () => {
    getCurrentUser.mockResolvedValue({ id: 1, name: 'A', email: 'a@joveo.com' });
    await expect(LoginPage({ searchParams: { next: '/ask-naren' } })).rejects.toThrow('NEXT_REDIRECT /ask-naren');
    expect(redirect).toHaveBeenCalledWith('/ask-naren');
  });
});
