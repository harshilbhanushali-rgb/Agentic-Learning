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
  setRoleAction: vi.fn(),
  setDisabledAction: vi.fn(),
}));

import { AdminPanel, type AdminUserRow } from './AdminPanel';

const users: AdminUserRow[] = [
  { email: 'boss@joveo.com', name: 'Boss', role: 'admin', fixedAdmin: false, googleLinked: true, disabled: false, sessions: 1 },
  { email: 'gone@joveo.com', name: 'Gone', role: 'member', fixedAdmin: false, googleLinked: true, disabled: true, sessions: 0 },
  { email: 'new@joveo.com', name: 'New', role: 'member', fixedAdmin: false, googleLinked: false, disabled: false, sessions: 3 },
  { email: 'harshil.bhanushali@joveo.com', name: 'Harshil', role: 'member', fixedAdmin: true, googleLinked: true, disabled: false, sessions: 0 },
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
    expect(within(rows[2]).getByText('Not signed in yet')).toBeInTheDocument();
    expect(within(rows[2]).getByText('3 browsers')).toBeInTheDocument();
  });

  it('offers a role for each person, but not for yourself or the built-in admin', () => {
    render(<AdminPanel me="boss@joveo.com" users={users} />);
    const rows = screen.getAllByRole('row').slice(1);
    const role = (i: number) => within(rows[i]).getByRole('combobox', { name: /Role for/ });

    expect(role(0)).toHaveValue('admin');
    expect(role(0)).toBeDisabled();
    expect(role(2)).toHaveValue('member');
    expect(role(2)).toBeEnabled();
    expect(within(role(2)).getAllByRole('option').map(o => o.textContent)).toEqual(['Member', 'Admin']);
    // The built-in admin always reads as an admin, and cannot be changed or disabled here.
    expect(role(3)).toHaveValue('admin');
    expect(role(3)).toBeDisabled();
    expect(within(rows[3]).getByRole('button', { name: 'Disable' })).toBeDisabled();
  });

  it('has no passwords anywhere: people sign in with Google', () => {
    render(<AdminPanel me="boss@joveo.com" users={users} />);
    expect(screen.queryByLabelText(/password/i)).toBeNull();
    expect(screen.queryByRole('button', { name: /password/i })).toBeNull();
    expect(screen.getByRole('button', { name: 'Add user' })).toBeInTheDocument();
  });

  it('says plainly when the list could not be loaded', () => {
    render(<AdminPanel me="boss@joveo.com" users={null} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load the user list');
    expect(screen.getByRole('heading', { name: 'Add a user' })).toBeInTheDocument();
  });
});
