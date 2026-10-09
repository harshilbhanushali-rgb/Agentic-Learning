import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen } from '@testing-library/react';

import type { SignInState } from '@/app/login/actions';

/* `useFormState` / `useFormStatus` exist only in the React canary that Next 14 vendors for
 * the app directory; the stable react-dom 18.3 this suite runs on does not export them. They
 * are replaced here with the smallest faithful stand-ins -- state that the action's return
 * value replaces, and a pending flag the test sets -- so the form's own behaviour is what is
 * under test, not React's. */
const form = vi.hoisted(() => ({
  pending: false,
  dispatch: null as null | ((data: FormData) => Promise<void>),
}));

vi.mock('react-dom', async importOriginal => {
  const actual = await importOriginal<typeof import('react-dom')>();
  const React = await import('react');
  return {
    ...actual,
    useFormState: (
      action: (prev: SignInState, data: FormData) => Promise<SignInState>,
      initial: SignInState,
    ) => {
      const [state, setState] = React.useState(initial);
      form.dispatch = async (data: FormData) => setState(await action(state, data));
      return [state, form.dispatch];
    },
    useFormStatus: () => ({ pending: form.pending }),
  };
});

const signIn = vi.fn<(prev: SignInState, data: FormData) => Promise<SignInState>>();
vi.mock('@/app/login/actions', () => ({ signIn: (p: SignInState, d: FormData) => signIn(p, d) }));

const { SignInForm } = await import('./SignInForm');

beforeEach(() => {
  form.pending = false;
  form.dispatch = null;
  signIn.mockReset();
});

describe('SignInForm', () => {
  it('asks for an email and a password, and carries where to go next', () => {
    const { container } = render(<SignInForm next="/ask-naren" />);
    expect(screen.getByLabelText('Email')).toHaveAttribute('type', 'email');
    expect(screen.getByLabelText('Email')).toHaveAttribute('autocomplete', 'username');
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password');
    expect(container.querySelector('input[type="hidden"][name="next"]')).toHaveValue('/ask-naren');
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows the refusal the action returns, and passes it the previous state', async () => {
    signIn.mockResolvedValue({ error: 'That email and password do not match a Joveo user.' });
    render(<SignInForm next="/ask-naren" />);

    const data = new FormData();
    data.set('email', 'a@joveo.com');
    await act(() => form.dispatch!(data));

    expect(screen.getByRole('alert')).toHaveTextContent('That email and password do not match a Joveo user.');
    expect(signIn).toHaveBeenCalledWith({ error: null }, data);
  });

  it('says it is signing in, and cannot be sent twice, while pending', () => {
    form.pending = true;
    render(<SignInForm next="/ask-naren" />);
    expect(screen.getByRole('button', { name: 'Signing in…' })).toBeDisabled();
  });
});
