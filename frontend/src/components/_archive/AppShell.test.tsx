import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AppShell from './AppShell';

const push = vi.fn();
let pathname = '/workspace';

vi.mock('next/navigation', () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push }),
}));

/* next/link is mocked down to a plain anchor. Not strictly required on Next 14, but it
 * removes a class of router-context flake for four lines. */
vi.mock('next/link', () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function renderShell() {
  return render(
    <AppShell>
      <p>page content</p>
    </AppShell>,
  );
}

beforeEach(() => {
  push.mockClear();
  pathname = '/workspace';
});

describe('AppShell mount', () => {
  it('renders its children and the navigation', async () => {
    renderShell();
    expect(screen.getByText('page content')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: /Workspace/ })).toBeInTheDocument();
  });

  it('marks the current page, by exact match and by prefix', async () => {
    const { unmount } = renderShell();
    expect(screen.getByRole('link', { name: /Workspace/ })).toHaveAttribute('aria-current', 'page');
    unmount();

    pathname = '/library/deep/page';
    renderShell();
    expect(screen.getByRole('link', { name: /Library/ })).toHaveAttribute('aria-current', 'page');
  });

  /* The mode switcher and theme button are gated on `mounted`, so they appear only after
   * the mount effect. Asserting that is asserting the no-hydration-mismatch design: what
   * localStorage says cannot be known during the server render. */
  it('reveals the mode switcher only after mounting, defaulting to veteran', async () => {
    renderShell();
    const veteran = await screen.findByRole('button', { name: 'Veteran' });
    expect(veteran).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Newbie' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('restores a stored newbie mode', async () => {
    localStorage.setItem('cs-mode', 'newbie');
    renderShell();
    expect(await screen.findByRole('button', { name: 'Newbie' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('restores a collapsed sidebar', async () => {
    localStorage.setItem('cs-sidebar', 'closed');
    const { container } = renderShell();
    await screen.findByRole('button', { name: 'Veteran' });
    expect(container.querySelector('.app-layout')).toHaveClass('sidebar-collapsed');
  });

  it('restores dark mode onto the document element', async () => {
    localStorage.setItem('cs-theme', 'dark');
    renderShell();
    await screen.findByRole('button', { name: 'Veteran' });
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(screen.getByRole('button', { name: 'Switch to light mode' })).toBeInTheDocument();
  });
});

describe('AppShell controls', () => {
  it('toggles the sidebar and remembers the choice', async () => {
    const user = userEvent.setup();
    const { container } = renderShell();

    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }));
    expect(container.querySelector('.app-layout')).toHaveClass('sidebar-collapsed');
    expect(localStorage.getItem('cs-sidebar')).toBe('closed');

    await user.click(screen.getByRole('button', { name: 'Expand sidebar' }));
    expect(container.querySelector('.app-layout')).not.toHaveClass('sidebar-collapsed');
    expect(localStorage.getItem('cs-sidebar')).toBe('open');
  });

  it('toggles the theme in both directions', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(await screen.findByRole('button', { name: 'Switch to dark mode' }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(localStorage.getItem('cs-theme')).toBe('dark');

    await user.click(screen.getByRole('button', { name: 'Switch to light mode' }));
    expect(document.documentElement.dataset.theme).toBe('');
    expect(localStorage.getItem('cs-theme')).toBe('light');
  });

  it('broadcasts a mode switch so useMode consumers follow it', async () => {
    const user = userEvent.setup();
    const heard: string[] = [];
    const listener = (e: Event) => heard.push((e as CustomEvent<string>).detail);
    window.addEventListener('cs-mode-change', listener);

    renderShell();
    await user.click(await screen.findByRole('button', { name: 'Newbie' }));

    expect(heard).toEqual(['newbie']);
    expect(localStorage.getItem('cs-mode')).toBe('newbie');
    expect(screen.getByRole('status')).toHaveTextContent('Switched to Newbie view');

    window.removeEventListener('cs-mode-change', listener);
  });

  it('ignores a click on the mode already active', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(await screen.findByRole('button', { name: 'Veteran' }));
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
    expect(localStorage.getItem('cs-mode')).toBeNull();
  });

  it('auto-dismisses the mode toast', async () => {
    vi.useFakeTimers();
    try {
      renderShell();
      const newbie = await vi.waitFor(() => screen.getByRole('button', { name: 'Newbie' }));

      fireEvent.click(newbie);
      expect(screen.getByRole('status')).toHaveTextContent('Switched to Newbie view');

      act(() => {
        vi.advanceTimersByTime(2600);
      });
      expect(screen.getByRole('status')).toBeEmptyDOMElement();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('AppShell oracle', () => {
  it('suggests on focus and filters as you type', async () => {
    const user = userEvent.setup();
    renderShell();
    const box = screen.getByRole('combobox', { name: 'Knowledge Oracle' });

    await user.click(box);
    expect(screen.getByText('Suggested')).toBeInTheDocument();
    expect(screen.getAllByRole('option')).toHaveLength(5);

    await user.type(box, 'ROI');
    expect(screen.getByText('Results for "ROI"')).toBeInTheDocument();
    expect(screen.getByText(/powered by Oracle/)).toBeInTheDocument();
  });

  it('uses the singular in the footer for a single result', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.type(screen.getByRole('combobox', { name: 'Knowledge Oracle' }), 'Atlas');
    expect(screen.getAllByRole('option')).toHaveLength(1);
    expect(screen.getByText('1 result · powered by Oracle')).toBeInTheDocument();
  });

  it('says so when nothing matches', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.type(screen.getByRole('combobox', { name: 'Knowledge Oracle' }), 'zzzz');
    expect(screen.getByText(/No results for/)).toBeInTheDocument();
    expect(screen.queryByRole('option')).not.toBeInTheDocument();
  });

  it('navigates the list with the arrow keys and selects with Enter', async () => {
    const user = userEvent.setup();
    renderShell();
    const box = screen.getByRole('combobox', { name: 'Knowledge Oracle' });

    await user.click(box);
    await user.keyboard('{ArrowDown}');
    expect(box).toHaveAttribute('aria-activedescendant', 'oracle-opt-0');

    await user.keyboard('{ArrowDown}');
    expect(box).toHaveAttribute('aria-activedescendant', 'oracle-opt-1');

    await user.keyboard('{ArrowUp}');
    expect(box).toHaveAttribute('aria-activedescendant', 'oracle-opt-0');

    await user.keyboard('{Enter}');
    expect(box).toHaveValue('ROI benchmarks by industry');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('clamps the arrow keys at both ends', async () => {
    const user = userEvent.setup();
    renderShell();
    const box = screen.getByRole('combobox', { name: 'Knowledge Oracle' });

    await user.click(box);
    // Up from nothing selected stays at nothing selected.
    await user.keyboard('{ArrowUp}');
    expect(box).not.toHaveAttribute('aria-activedescendant');

    for (let i = 0; i < 10; i++) await user.keyboard('{ArrowDown}');
    expect(box).toHaveAttribute('aria-activedescendant', 'oracle-opt-4');
  });

  it('selects on click', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole('combobox', { name: 'Knowledge Oracle' }));
    await user.click(screen.getAllByRole('option')[2]);

    expect(screen.getByRole('combobox', { name: 'Knowledge Oracle' })).toHaveValue(
      'Account A · 18-month renewal arc',
    );
  });

  it('closes on Escape and on an outside click', async () => {
    const user = userEvent.setup();
    renderShell();
    const box = screen.getByRole('combobox', { name: 'Knowledge Oracle' });

    await user.click(box);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

    await user.click(box);
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    fireEvent.mouseDown(document.body);
    await waitFor(() => expect(screen.queryByRole('listbox')).not.toBeInTheDocument());
  });
});

describe('AppShell keyboard shortcuts', () => {
  it('opens the oracle on Ctrl+K', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.keyboard('{Control>}k{/Control}');
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByRole('combobox', { name: 'Knowledge Oracle' }));
  });

  it('routes on the g-chord', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.keyboard('gl');
    expect(push).toHaveBeenCalledWith('/library');

    await user.keyboard('ga');
    expect(push).toHaveBeenCalledWith('/ask-naren');
  });

  it('ignores a g-chord that names no destination', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.keyboard('gz');
    expect(push).not.toHaveBeenCalled();
  });

  it('forgets a pending g after the chord window closes', async () => {
    vi.useFakeTimers();
    try {
      renderShell();
      fireEvent.keyDown(window, { key: 'g' });
      act(() => {
        vi.advanceTimersByTime(1300);
      });
      fireEvent.keyDown(window, { key: 'w' });
      expect(push).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  /* Typing "g" into a field must never navigate. Both tag names are checked because the app
   * has one of each: the oracle input, and the Ask Naren textarea. */
  it('does not fire shortcuts while typing in a field', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole('combobox', { name: 'Knowledge Oracle' }));
    await user.keyboard('gl');
    expect(push).not.toHaveBeenCalled();

    const textarea = document.createElement('textarea');
    document.body.appendChild(textarea);
    textarea.focus();
    fireEvent.keyDown(textarea, { key: 'g' });
    fireEvent.keyDown(textarea, { key: 'w' });
    expect(push).not.toHaveBeenCalled();
    textarea.remove();
  });
});
