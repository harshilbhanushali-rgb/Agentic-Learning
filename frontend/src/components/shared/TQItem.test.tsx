import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TQItem } from './TQItem';
import { testQueueItem } from '../../../tests/fixtures/domain';

describe('TQItem', () => {
  it('marks a locked item disabled and explains why', () => {
    render(<TQItem item={testQueueItem({ status: 'locked' })} tierLabel="Tier 1" />);
    const row = screen.getByTitle('Complete the previous test to unlock');
    expect(row).toHaveAttribute('aria-disabled', 'true');
  });

  it('offers the Take action only while active', () => {
    const { rerender } = render(
      <TQItem item={testQueueItem({ status: 'active' })} tierLabel="Tier 2" />,
    );
    expect(screen.getByRole('button', { name: 'Take' })).toBeInTheDocument();

    rerender(<TQItem item={testQueueItem({ status: 'complete' })} tierLabel="Tier 2" />);
    expect(screen.queryByRole('button', { name: 'Take' })).not.toBeInTheDocument();
  });

  it('renders the score, time and note when present', () => {
    render(
      <TQItem
        item={testQueueItem({ scored: 91, time: '8 min', note: 'Retake available' })}
        tierLabel="Tier 1"
      />,
    );
    expect(screen.getByText(/Scored 91/)).toBeInTheDocument();
    expect(screen.getByText(/8 min/)).toBeInTheDocument();
    expect(screen.getByText('Retake available')).toBeInTheDocument();
  });

  it('omits all three when they are absent', () => {
    render(
      <TQItem
        item={testQueueItem({ scored: null, time: null, note: null, status: 'locked' })}
        tierLabel="Phase 1"
      />,
    );
    expect(screen.queryByText(/Scored/)).not.toBeInTheDocument();
    expect(screen.queryByText('Retake available')).not.toBeInTheDocument();
    // the tier label still renders, so the row is not simply empty
    expect(screen.getByText(/Phase 1/)).toBeInTheDocument();
  });
});
