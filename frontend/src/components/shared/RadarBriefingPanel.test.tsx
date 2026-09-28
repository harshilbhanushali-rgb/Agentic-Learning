import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RadarBriefingPanel } from './RadarBriefingPanel';
import { meeting, meetingVariant } from '../../../tests/fixtures/domain';

describe('RadarBriefingPanel', () => {
  it('asks a cold meeting to start at step 01', () => {
    render(<RadarBriefingPanel meeting={meeting({ prepStatus: 'cold' })} />);
    expect(screen.getByRole('button', { name: /Start Step 01/ })).toBeInTheDocument();
    expect(screen.queryByText(/Ready to walk in/)).not.toBeInTheDocument();
  });

  it('asks an in-progress meeting to continue at step 02', () => {
    render(<RadarBriefingPanel meeting={meeting({ prepStatus: 'in-progress' })} />);
    expect(screen.getByRole('button', { name: /Continue Step 02/ })).toBeInTheDocument();
  });

  it('shows no CTA once ready, and says so instead', () => {
    render(<RadarBriefingPanel meeting={meeting({ prepStatus: 'ready' })} />);
    expect(screen.queryByRole('button', { name: /Step 0/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Ready to walk in/)).toBeInTheDocument();
  });

  it('falls back to a default clip label, and uses a supplied one', () => {
    const { rerender } = render(<RadarBriefingPanel meeting={meeting()} />);
    expect(screen.getByText('Expert clip · 2 min')).toBeInTheDocument();

    rerender(<RadarBriefingPanel meeting={meetingVariant('cold')} />);
    expect(screen.getByText('Custom clip label')).toBeInTheDocument();
  });

  it('renders each waterfall state, and numbers the steps', () => {
    render(<RadarBriefingPanel meeting={meeting()} />);
    expect(screen.getByText(/Step 01/)).toBeInTheDocument();
    expect(screen.getByText(/Step 03/)).toBeInTheDocument();
    expect(screen.getByText('Now')).toBeInTheDocument();
    // a bare 'Locked' meta gets the generic explanation
    expect(screen.getByTitle('Complete the previous step to unlock')).toBeInTheDocument();
  });

  it('prefers a locked step’s own meta over the generic explanation', () => {
    render(<RadarBriefingPanel meeting={meetingVariant('cold')} />);
    expect(screen.getByTitle('Unlocks Thursday')).toBeInTheDocument();
    expect(screen.queryByTitle('Complete the previous step to unlock')).not.toBeInTheDocument();
  });
});
