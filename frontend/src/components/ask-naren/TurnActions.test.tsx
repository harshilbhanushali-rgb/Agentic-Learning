import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const sendFeedback = vi.fn();
vi.mock('./threadClient', () => ({ sendFeedback: (...a: unknown[]) => sendFeedback(...a) }));

import { TurnActions } from './TurnActions';

const target = { threadId: 9, position: 2 };

beforeEach(() => {
  sendFeedback.mockReset();
  sendFeedback.mockResolvedValue({ kind: 'ok', value: true });
});

describe('TurnActions', () => {
  it('saves the thumb on click, then the optional reason on Send', async () => {
    const user = userEvent.setup();
    render(<TurnActions copyText="the answer" target={target} />);

    await user.click(screen.getByRole('button', { name: 'Bad answer' }));
    expect(sendFeedback).toHaveBeenCalledWith(9, 2, 'bad', null);
    expect(screen.getByRole('button', { name: 'Bad answer' })).toHaveAttribute('aria-pressed', 'true');

    await user.type(screen.getByLabelText('What was wrong with this answer?'), 'wrong question');
    await user.click(screen.getByRole('button', { name: 'Send' }));
    expect(sendFeedback).toHaveBeenLastCalledWith(9, 2, 'bad', 'wrong question');
    expect(screen.getByText('Thanks — that helps.')).toBeInTheDocument();
    expect(screen.queryByLabelText('What was wrong with this answer?')).not.toBeInTheDocument();
  });

  it('asks why for a good answer too, and Skip keeps the thumb', async () => {
    const user = userEvent.setup();
    render(<TurnActions copyText={null} target={target} />);
    await user.click(screen.getByRole('button', { name: 'Good answer' }));
    expect(screen.getByLabelText('What made this answer good?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Skip' }));
    expect(sendFeedback).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Good answer' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('says so when the rating could not be saved', async () => {
    const user = userEvent.setup();
    sendFeedback.mockResolvedValue({ kind: 'unavailable' });
    render(<TurnActions copyText={null} target={target} />);
    await user.click(screen.getByRole('button', { name: 'Good answer' }));
    expect(await screen.findByText(/Could not save that just now/)).toBeInTheDocument();
  });

  it('offers only Copy for an answer that is not stored', () => {
    render(<TurnActions copyText="the answer" target={null} />);
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Good answer' })).not.toBeInTheDocument();
  });
});
