import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EgoTrapCard } from './EgoTrapCard';
import { EGO_TRAPS } from '@/data/workspace';

describe('EgoTrapCard', () => {
  it('opens on the first trap with its tab selected', () => {
    render(<EgoTrapCard />);
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(EGO_TRAPS.length);
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(EGO_TRAPS[0].question);
  });

  it('switches trap when another tab is chosen', async () => {
    const user = userEvent.setup();
    render(<EgoTrapCard />);
    const tabs = screen.getAllByRole('tab');

    await user.click(tabs[1]);
    expect(tabs[1]).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(EGO_TRAPS[1].question);
  });

  it('ignores a click on the already-selected tab', async () => {
    const user = userEvent.setup();
    render(<EgoTrapCard />);

    // Open the mirror, then re-click the ACTIVE tab. selectTrap() returns early on a
    // no-op selection, so the mirror must stay open -- choosing a different trap closes it.
    await user.click(screen.getByRole('button', { name: /View mirror/ }));
    await user.click(screen.getAllByRole('tab')[0]);
    expect(screen.getByRole('button', { name: /Hide mirror/ })).toBeInTheDocument();
  });

  it('closes the mirror when a different trap is selected', async () => {
    const user = userEvent.setup();
    render(<EgoTrapCard />);

    await user.click(screen.getByRole('button', { name: /View mirror/ }));
    await user.click(screen.getAllByRole('tab')[1]);
    expect(screen.getByRole('button', { name: /View mirror/ })).toBeInTheDocument();
  });

  it('shows applied and missed moments once the mirror is open', async () => {
    const user = userEvent.setup();
    render(<EgoTrapCard />);
    await user.click(screen.getByRole('button', { name: /View mirror/ }));

    expect(screen.getByText('What you applied')).toBeInTheDocument();
    expect(screen.getByText('What you missed')).toBeInTheDocument();
    expect(screen.getByText(EGO_TRAPS[0].appliedMoments[0].quote)).toBeInTheDocument();
  });
});
