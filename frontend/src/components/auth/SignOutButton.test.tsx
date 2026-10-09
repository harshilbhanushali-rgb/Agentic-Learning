import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('@/app/login/actions', () => ({ signOut: vi.fn() }));

import { SignOutButton } from './SignOutButton';

describe('SignOutButton', () => {
  it('leaves no legacy thread and no unsent draft behind on a shared machine', async () => {
    const user = userEvent.setup();
    localStorage.setItem('cs-ask-naren-thread-v1', '[]');
    localStorage.setItem('cs-ask-naren-thread-v1:7', '[]');
    localStorage.setItem('cs-theme', 'dark');
    sessionStorage.setItem('cs-ask-naren-draft', JSON.stringify({ userId: 7, draft: 'd', threadId: 1 }));

    render(<SignOutButton />);
    const button = screen.getByRole('button', { name: 'Sign out' });
    expect(button).toHaveAttribute('type', 'submit');
    // jsdom cannot submit a form to a server action; the clearing happens on the click.
    button.closest('form')!.addEventListener('submit', e => e.preventDefault());
    await user.click(button);

    expect(localStorage.getItem('cs-ask-naren-thread-v1')).toBeNull();
    expect(localStorage.getItem('cs-ask-naren-thread-v1:7')).toBeNull();
    expect(localStorage.getItem('cs-theme')).toBe('dark');
    expect(sessionStorage.getItem('cs-ask-naren-draft')).toBeNull();
  });
});
