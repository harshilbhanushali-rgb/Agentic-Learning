import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AnswerCard } from './AnswerCard';
import { ClarifyPrompt } from './ClarifyPrompt';
import { DeclineNotice } from './DeclineNotice';
import { SituationForm } from './SituationForm';
import { answer, clarify, decline } from '../../../tests/fixtures/ask-naren';
import type { AskNarenDeclineReason } from '@/types';

describe('AnswerCard', () => {
  it('shows the guidance, the verbatim quote, the situation and the source', () => {
    render(<AnswerCard result={answer()} />);

    expect(screen.getByText('Open with the delivery number rather than an apology.')).toBeInTheDocument();
    // The quote is on the page, not behind a disclosure: the verification of that quote is
    // the reason to trust the answer at all.
    expect(screen.getByText(/Let us look at delivery before we touch the budget\./)).toBeInTheDocument();
    expect(screen.getByText('What Naren actually said')).toBeInTheDocument();
    // Naming the scenario is what lets a CSM catch an inherited identifier going stale.
    expect(screen.getByText('performance pushback')).toBeInTheDocument();
    expect(screen.getByText('Account A · March 2024')).toBeInTheDocument();
  });

  it('omits the reply block unless the response is a contrast', () => {
    const { rerender } = render(<AnswerCard result={answer()} />);
    expect(screen.queryByText('What you replied')).not.toBeInTheDocument();

    rerender(<AnswerCard result={answer({ my_reply: 'I offered a discount.' })} />);
    expect(screen.getByText('What you replied')).toBeInTheDocument();
    expect(screen.getByText('I offered a discount.')).toBeInTheDocument();
  });

  it('passes no verdict on the CSM reply', () => {
    render(<AnswerCard result={answer({ my_reply: 'I offered a discount.' })} />);
    const body = screen.getByRole('article').textContent ?? '';
    for (const verdict of ['correct', 'incorrect', 'wrong', 'score', 'better']) {
      expect(body.toLowerCase()).not.toContain(verdict);
    }
  });
});

describe('ClarifyPrompt', () => {
  it('reads as a question rather than a failure, and promises not to repeat itself', () => {
    render(<ClarifyPrompt result={clarify()} />);
    expect(screen.getByText('One thing first')).toBeInTheDocument();
    expect(screen.getByText('Which account, and what did they actually say?')).toBeInTheDocument();
    expect(screen.getByText(/will not ask you this again/)).toBeInTheDocument();
  });
});

describe('DeclineNotice', () => {
  /* One case per reason. The COPY table is declared exhaustive over the union, and this is
   * what proves it at runtime: a reason with no entry would render `undefined` rather than
   * fail to compile, since the lookup is by key. */
  const REASONS: AskNarenDeclineReason[] = [
    'no_close_match',
    'grounding_unverified',
    'out_of_scope',
    'follow_up_ungrounded',
    'service_error',
    'service_unreachable',
    'service_busy',
    'deadline_exceeded',
  ];

  it.each(REASONS)('renders a heading, the message and a hint for %s', reason => {
    render(<DeclineNotice result={decline(reason)} />);
    const body = screen.getByRole('article').textContent ?? '';

    expect(screen.getByText(`A CSM-safe sentence explaining ${reason}.`)).toBeInTheDocument();
    expect(body).not.toContain('undefined');
    expect(body.length).toBeGreaterThan(40);
  });

  it('keeps busy distinguishable from unavailable', () => {
    // Collapsing these is how a capacity problem ends up wearing a quality problem's
    // clothes -- the tool looks like it is working and simply declining a lot.
    const { rerender } = render(<DeclineNotice result={decline('service_busy')} />);
    expect(screen.getByText('Ask Naren is busy')).toBeInTheDocument();
    expect(screen.getByText(/nothing is broken/)).toBeInTheDocument();

    rerender(<DeclineNotice result={decline('service_unreachable')} />);
    expect(screen.getByText('Ask Naren is unavailable')).toBeInTheDocument();
  });

  it('tells a CSM when rewording cannot help', () => {
    render(<DeclineNotice result={decline('out_of_scope')} />);
    expect(screen.getByText(/Rewording will not help here/)).toBeInTheDocument();
  });

  it('points a failed follow-up at asking fresh rather than at nothing existing', () => {
    render(<DeclineNotice result={decline('follow_up_ungrounded')} />);
    expect(screen.getByText('Not in that call')).toBeInTheDocument();
    expect(screen.getByText(/Ask it as a fresh question/)).toBeInTheDocument();
  });
});

describe('SituationForm', () => {
  it('focuses the textarea on mount', () => {
    render(<SituationForm value="" onChange={vi.fn()} onSubmit={vi.fn()} busy={false} />);
    expect(document.activeElement).toBe(screen.getByLabelText('The situation'));
  });

  it('reports what was typed', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<SituationForm value="" onChange={onChange} onSubmit={vi.fn()} busy={false} />);

    await user.type(screen.getByLabelText('The situation'), 'flat');
    expect(onChange).toHaveBeenCalled();
  });

  it('cannot be submitted empty or whitespace-only', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const { rerender } = render(
      <SituationForm value="" onChange={vi.fn()} onSubmit={onSubmit} busy={false} />,
    );
    expect(screen.getByRole('button', { name: 'Ask Naren' })).toBeDisabled();

    rerender(<SituationForm value="   " onChange={vi.fn()} onSubmit={onSubmit} busy={false} />);
    screen.getByLabelText('The situation').focus();
    await user.keyboard('{Enter}');
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('submits on Enter, like a chat, and Shift+Enter starts a new line', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <SituationForm value="applies are flat" onChange={vi.fn()} onSubmit={onSubmit} busy={false} />,
    );
    screen.getByLabelText('The situation').focus();

    await user.keyboard('{Shift>}{Enter}{/Shift}');
    expect(onSubmit).not.toHaveBeenCalled();

    await user.keyboard('{Enter}');
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it('submits on the button', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <SituationForm value="applies are flat" onChange={vi.fn()} onSubmit={onSubmit} busy={false} />,
    );
    await user.click(screen.getByRole('button', { name: 'Ask Naren' }));
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it('locks the form and says so while a question is in flight', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <SituationForm value="applies are flat" onChange={vi.fn()} onSubmit={onSubmit} busy />,
    );

    expect(screen.getByRole('button', { name: 'Asking…' })).toBeDisabled();
    expect(screen.getByLabelText('The situation')).toBeDisabled();

    await user.keyboard('{Control>}{Enter}{/Control}');
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
