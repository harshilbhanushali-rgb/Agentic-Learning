import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AppShell from './AppShell';

/* The slim shell that goes with Ask Naren being the only live page. The full shell it
 * replaced (Oracle, mode switch, notifications) is archived and tested beside itself in
 * src/components/_archive/AppShell.test.tsx. */

let pathname = '/ask-naren';

vi.mock('next/navigation', () => ({ usePathname: () => pathname }));
vi.mock('next/link', () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

type User = { name: string; email: string } | null;

function renderShell(user: User = { name: 'Asha Rao', email: 'asha.rao@joveo.com' }) {
  return render(
    <AppShell user={user}>
      <p>page content</p>
    </AppShell>,
  );
}

beforeEach(() => {
  pathname = '/ask-naren';
});

describe('AppShell', () => {
  it('renders its children and one navigation item', () => {
    renderShell();
    expect(screen.getByText('page content')).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Pages' });
    expect(nav.querySelectorAll('a')).toHaveLength(1);
    expect(screen.getByRole('link', { name: 'Ask Naren' })).toHaveAttribute('href', '/ask-naren');
  });

  it('marks Ask Naren current by exact match and by prefix, and not elsewhere', () => {
    const { unmount } = renderShell();
    expect(screen.getByRole('link', { name: 'Ask Naren' })).toHaveAttribute('aria-current', 'page');
    unmount();

    pathname = '/ask-naren/anything';
    const second = renderShell();
    expect(screen.getByRole('link', { name: 'Ask Naren' })).toHaveAttribute('aria-current', 'page');
    second.unmount();

    // A route that merely starts with the same letters is not the page.
    pathname = '/ask-narenx';
    renderShell();
    expect(screen.getByRole('link', { name: 'Ask Naren' })).not.toHaveAttribute('aria-current');
  });

  it('has no mode switch: Ask Naren renders the same in both modes', () => {
    renderShell();
    expect(screen.queryByRole('button', { name: 'Veteran' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Newbie' })).not.toBeInTheDocument();
  });
});

describe('AppShell signed-in user', () => {
  it('shows who is signed in, with initials', () => {
    const { container } = renderShell();
    expect(screen.getByText('Asha Rao')).toBeInTheDocument();
    expect(screen.getByText('asha.rao@joveo.com')).toBeInTheDocument();
    expect(container.querySelector('.sidebar-user-avatar')).toHaveTextContent('AR');
  });

  it('shows nobody when nobody is signed in', () => {
    const { container } = renderShell(null);
    expect(container.querySelector('.sidebar-user')).toBeNull();
  });

  it.each([
    ['E2E Test (Claude)', 'ET'],
    ['madhumita', 'M'],
    ['  Naren   K  S ', 'NS'],
    ['(( ))', '?'],
    ['2nd Shift', '2S'],
  ])('initials of %j are %j', (name, expected) => {
    const { container } = renderShell({ name, email: 'x@joveo.com' });
    expect(container.querySelector('.sidebar-user-avatar')).toHaveTextContent(expected);
  });

  it('titles the user block only when the sidebar is collapsed', async () => {
    const user = userEvent.setup();
    const { container } = renderShell();
    expect(container.querySelector('.sidebar-user')).not.toHaveAttribute('title');
    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }));
    expect(container.querySelector('.sidebar-user')).toHaveAttribute('title', 'Asha Rao · asha.rao@joveo.com');
    expect(screen.getByRole('link', { name: 'Ask Naren' })).toHaveAttribute('title', 'Ask Naren');
  });
});

describe('AppShell sidebar', () => {
  it('collapses and expands, remembering the choice', async () => {
    const user = userEvent.setup();
    const { container } = renderShell();
    const toggle = screen.getByRole('button', { name: 'Collapse sidebar' });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    await user.click(toggle);
    expect(container.querySelector('.app-layout')).toHaveClass('sidebar-collapsed');
    expect(localStorage.getItem('cs-sidebar')).toBe('closed');

    await user.click(screen.getByRole('button', { name: 'Expand sidebar' }));
    expect(container.querySelector('.app-layout')).not.toHaveClass('sidebar-collapsed');
    expect(localStorage.getItem('cs-sidebar')).toBe('open');
  });

  it('restores a collapsed sidebar', async () => {
    localStorage.setItem('cs-sidebar', 'closed');
    const { container } = renderShell();
    expect(await screen.findByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument();
    expect(container.querySelector('.app-layout')).toHaveClass('sidebar-collapsed');
  });
});

describe('AppShell theme', () => {
  it('toggles dark mode onto the document element and remembers it', async () => {
    const user = userEvent.setup();
    renderShell();
    const toDark = await screen.findByRole('button', { name: 'Switch to dark mode' });
    expect(toDark).toHaveAttribute('aria-pressed', 'false');

    await user.click(toDark);
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(localStorage.getItem('cs-theme')).toBe('dark');

    await user.click(screen.getByRole('button', { name: 'Switch to light mode' }));
    expect(document.documentElement.dataset.theme).toBe('');
    expect(localStorage.getItem('cs-theme')).toBe('light');
  });

  it('restores dark mode on mount', async () => {
    localStorage.setItem('cs-theme', 'dark');
    renderShell();
    expect(await screen.findByRole('button', { name: 'Switch to light mode' })).toHaveAttribute('aria-pressed', 'true');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });
});
