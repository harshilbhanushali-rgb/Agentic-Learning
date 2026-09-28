import { describe, it, expect, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import WorkspacePage from './_archive/workspace/page';
import LibraryPage from './_archive/library/page';
import SimulatorPage from './_archive/simulator/page';
import { useMode } from '@/hooks/useMode';
import { SPOTLIGHT } from '@/data/library';

vi.mock('next/navigation', () => ({ redirect: vi.fn() }));
import { redirect } from 'next/navigation';
import Home from './page';

/* The mode system renders completely different component trees within the same page, so
 * every page below is exercised in BOTH modes. Reading one mode only would leave half of
 * each page's branches permanently untaken while the line number still climbed. */
function setMode(mode: 'veteran' | 'newbie') {
  localStorage.setItem('cs-mode', mode);
}

describe('Home', () => {
  it('redirects to Ask Naren, the only live page', () => {
    // A Server Component with no JSX -- called as a plain function rather than rendered,
    // which is all it is.
    Home();
    expect(redirect).toHaveBeenCalledWith('/ask-naren');
  });
});

describe('useMode', () => {
  function Probe() {
    return <span data-testid="mode">{useMode()}</span>;
  }

  it('defaults to veteran when storage holds no choice', async () => {
    render(<Probe />);
    expect(await screen.findByTestId('mode')).toHaveTextContent('veteran');
  });

  it('reads the stored choice on mount', async () => {
    setMode('newbie');
    render(<Probe />);
    expect(await screen.findByTestId('mode')).toHaveTextContent('newbie');
  });

  it('follows a cs-mode-change event', async () => {
    render(<Probe />);
    await screen.findByTestId('mode');

    act(() => {
      window.dispatchEvent(new CustomEvent('cs-mode-change', { detail: 'newbie' }));
    });
    expect(screen.getByTestId('mode')).toHaveTextContent('newbie');
  });

  it('stops listening once unmounted', async () => {
    const remove = vi.spyOn(window, 'removeEventListener');
    const { unmount } = render(<Probe />);
    await screen.findByTestId('mode');

    unmount();
    expect(remove).toHaveBeenCalledWith('cs-mode-change', expect.any(Function));
  });
});

describe('WorkspacePage', () => {
  it('renders the veteran tree', async () => {
    setMode('veteran');
    render(<WorkspacePage />);
    expect(await screen.findByText(/two meetings on the deck/i)).toBeInTheDocument();
    expect(screen.getByText('Weekly Radar')).toBeInTheDocument();
    expect(screen.getByText('Knowledge drops')).toBeInTheDocument();
  });

  it('renders an entirely different newbie tree', async () => {
    setMode('newbie');
    render(<WorkspacePage />);
    expect(await screen.findByText(/days into your track/i)).toBeInTheDocument();
    expect(screen.getByText('Your week')).toBeInTheDocument();
    expect(screen.queryByText('Weekly Radar')).not.toBeInTheDocument();
  });
});

describe('LibraryPage', () => {
  it('opens on Courses and names the mode it is filtered for', async () => {
    setMode('veteran');
    render(<LibraryPage />);

    expect(await screen.findByText('Filtered for Veteran')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Courses' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText(SPOTLIGHT.veteran.title)).toBeInTheDocument();
  });

  it('shows the newbie spotlight in newbie mode', async () => {
    setMode('newbie');
    render(<LibraryPage />);
    expect(await screen.findByText('Filtered for Newbie')).toBeInTheDocument();
    expect(screen.getByText(SPOTLIGHT.newbie.title)).toBeInTheDocument();
  });

  it('switches between all three tabs', async () => {
    const user = userEvent.setup();
    render(<LibraryPage />);

    await user.click(screen.getByRole('button', { name: 'Case Studies' }));
    expect(screen.getByRole('button', { name: 'Case Studies' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText(/Accounts told in chapters/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Failure Library' }));
    expect(screen.getByText(/Post-mortems of churned and lost deals/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Courses' }));
    expect(screen.getByRole('button', { name: 'Courses' })).toHaveAttribute('aria-current', 'page');
  });

  it('opens and closes the failure modal from the failure tab', async () => {
    const user = userEvent.setup();
    render(<LibraryPage />);

    await user.click(screen.getByRole('button', { name: 'Failure Library' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    const cards = screen.getAllByRole('button').filter(b => !b.getAttribute('aria-current'));
    await user.click(cards.find(b => b.className.includes('lib-fl-card'))!);
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Close modal' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

describe('SimulatorPage', () => {
  it('flips its copy once the visitor asks to be notified', async () => {
    const user = userEvent.setup();
    render(<SimulatorPage />);

    expect(screen.getByText('Be first in your cohort to run a session.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Notify me when it launches/ }));
    expect(screen.getByText(/We'll ping you the moment it's ready\./)).toBeInTheDocument();
    expect(screen.getByRole('button')).toBeDisabled();
  });
});
