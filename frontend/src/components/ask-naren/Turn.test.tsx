import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import type { AskNarenResponse } from '@/types';

import { answer, clarify, decline, maximal } from '../../../tests/fixtures/ask-naren';
import { Asked, NotSavedNote, Outcome } from './Turn';

describe('Outcome', () => {
  it.each([
    ['answered', answer(), 'What Naren actually said'],
    ['declined', decline('no_close_match'), 'No grounded answer'],
    ['clarify', clarify(), 'One thing first'],
    ['rendered', maximal.show_exchange, 'The real exchange'],
  ] as const)('renders %s through its own card', (_label, result, text) => {
    render(<Outcome result={result as AskNarenResponse} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  /* The `never` check makes a fifth outcome a build failure; at runtime, a body that slipped
   * past the contract guard must throw rather than paint a blank area. */
  it('throws on an outcome outside the union', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<Outcome result={{ outcome: 'maybe' } as unknown as AskNarenResponse} />)).toThrow(
      /unhandled outcome/,
    );
  });
});

describe('Asked', () => {
  it('shows the question, and when it was asked only once that is known', () => {
    const { rerender } = render(<Asked message={'line one\nline two'} />);
    expect(screen.getByText('You asked')).toHaveTextContent(/^You asked$/);
    expect(screen.getByText(/line one/)).toHaveClass('whitespace-pre-line');

    rerender(<Asked message="q" when="3 days ago" />);
    expect(screen.getByText('You asked', { exact: false })).toHaveTextContent('You asked · 3 days ago');
  });
});

describe('NotSavedNote', () => {
  it('says the answer is real but not stored, and what happens next', () => {
    render(<NotSavedNote />);
    expect(screen.getByText('Not saved to this thread.')).toBeInTheDocument();
    expect(screen.getByText(/Your next question starts a new thread/)).toBeInTheDocument();
  });
});
