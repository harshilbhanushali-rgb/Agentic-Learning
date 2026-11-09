import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';

/* useFormState / useFormStatus exist only in the React canary Next vendors; the stable
 * react-dom this suite runs on lacks them (see SignInForm.test.tsx). Minimal stand-ins. */
vi.mock('react-dom', async importOriginal => {
  const actual = await importOriginal<typeof import('react-dom')>();
  return {
    ...actual,
    useFormState: (_action: unknown, initial: unknown) => [initial, vi.fn()],
    useFormStatus: () => ({ pending: false }),
  };
});

vi.mock('@/app/admin/actions', () => ({
  addUserAction: vi.fn(),
  resetPasswordAction: vi.fn(),
  setDisabledAction: vi.fn(),
}));

import { AdminPanel, type AdminUserRow } from './AdminPanel';

const users: AdminUserRow[] = [
  { email: 'boss@joveo.com', name: 'Boss', hasPassword: true, disabled: false, sessions: 1 },
  { email: 'gone@joveo.com', name: 'Gone', hasPassword: true, disabled: true, sessions: 0 },
  { email: 'new@joveo.com', name: 'New', hasPassword: false, disabled: false, sessions: 3 },
];

describe('AdminPanel', () => {
  it('lists everyone with their status, and offers the right switch for each', () => {
    render(<AdminPanel me="Boss@joveo.com" users={users} />);
    const rows = screen.getAllByRole('row').slice(1);
    expect(within(rows[0]).getByText('Active')).toBeInTheDocument();
    expect(within(rows[0]).getByText('(you)')).toBeInTheDocument();
    // An admin cannot disable themselves from here.
    expect(within(rows[0]).getByRole('button', { name: 'Disable' })).toBeDisabled();
    expect(within(rows[1]).getByText('Disabled')).toBeInTheDocument();
    expect(within(rows[1]).getByRole('button', { name: 'Enable' })).toBeEnabled();
    expect(within(rows[2]).getByText('No password')).toBeInTheDocument();
    expect(within(rows[2]).getByText('3 browsers')).toBeInTheDocument();
  });

  it('says plainly when the list could not be loaded', () => {
    render(<AdminPanel me="boss@joveo.com" users={null} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load the user list');
    expect(screen.getByRole('heading', { name: 'Add a user' })).toBeInTheDocument();
  });
});
