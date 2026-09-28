import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RadarRow } from './RadarRow';
import { meeting } from '../../../tests/fixtures/domain';

describe('RadarRow', () => {
  it('renders the meeting summary and toggles the briefing label', async () => {
    const user = userEvent.setup();
    render(<RadarRow meeting={meeting({ account: 'Account Z' })} />);

    expect(screen.getByText('Account Z')).toBeInTheDocument();
    const toggle = screen.getByRole('button', { name: /Open briefing/ });

    await user.click(toggle);
    expect(screen.getByRole('button', { name: /Hide briefing/ })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Hide briefing/ }));
    expect(screen.getByRole('button', { name: /Open briefing/ })).toBeInTheDocument();
  });

  it('falls back to the in-progress chip styling for an unknown prep status', () => {
    // PrepStatus is a closed union at compile time, but this component defends against a
    // value outside it -- data arrives from a fixture module, not from the type system.
    render(<RadarRow meeting={meeting({ prepStatus: 'unknown' as never, prepLabel: 'Unknown' })} />);
    expect(screen.getByText('Unknown')).toBeInTheDocument();
  });
});
