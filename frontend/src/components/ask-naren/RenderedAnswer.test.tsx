import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RenderedAnswer } from './RenderedAnswer';
import { citation, maximal, minimal, RENDERED_KINDS } from '../../../tests/fixtures/ask-naren';
import type { AskNarenRendered } from '@/types';

/**
 * A rendered answer is built from stored rows with no model call behind it, so what is
 * asserted here is that each `kind` reaches its own layout and that the copy which
 * qualifies an answer actually appears. The qualifiers are the point: several of them exist
 * specifically to stop a CSM reading an aggregate as a fact.
 */

describe('RenderedAnswer', () => {
  it('renders every kind in the union without throwing', () => {
    for (const kind of RENDERED_KINDS) {
      const { unmount } = render(<RenderedAnswer result={maximal[kind]} />);
      expect(screen.getByRole('article')).toBeInTheDocument();
      unmount();
    }
    expect(RENDERED_KINDS).toHaveLength(13);
  });

  it('renders every kind again in its minimal shape', () => {
    for (const kind of RENDERED_KINDS) {
      const { unmount } = render(<RenderedAnswer result={minimal[kind]} />);
      expect(screen.getByRole('article')).toBeInTheDocument();
      unmount();
    }
  });

  it('throws on a kind outside the union rather than rendering a blank card', () => {
    const rogue = { outcome: 'rendered', kind: 'not_a_kind' } as unknown as AskNarenRendered;
    expect(() => render(<RenderedAnswer result={rogue} />)).toThrow(/unhandled rendered kind/);
  });
});

describe('discovery', () => {
  it('groups by topic when the grouping is real', () => {
    render(<RenderedAnswer result={maximal.discovery} />);
    expect(screen.getByText('Delivery')).toBeInTheDocument();
    expect(screen.getByText('34 situations drawn from Naren’s real calls.')).toBeInTheDocument();
  });

  it('falls back to a flat list when it is not', () => {
    render(<RenderedAnswer result={minimal.discovery} />);
    expect(screen.queryByText('Delivery')).not.toBeInTheDocument();
    expect(screen.getByText('performance pushback')).toBeInTheDocument();
  });
});

describe('frequency', () => {
  it('prints the basis as the service wrote it, and the call counts', () => {
    render(<RenderedAnswer result={maximal.frequency} />);
    expect(
      screen.getByText('Ranked across Naren’s recorded calls, not across clients generally.'),
    ).toBeInTheDocument();
    expect(screen.getAllByText('9 calls')[0]).toBeInTheDocument();
  });
});

/* The two exchange views NAME THEIR SCENARIO, always (issue #52). A carried identifier can
 * strand on the old situation when a CSM moves on without saying so, and the scenario line
 * is the only thing on the card that gives that away (ADR 0013). */
describe.each(['show_exchange', 'what_happened_next'] as const)('%s', kind => {
  it('names the scenario of the exchange it shows', () => {
    const result = {
      ...maximal[kind],
      citation: citation({ scenario_key: 'contract_renewal' }),
    } as AskNarenRendered;
    render(<RenderedAnswer result={result} />);
    expect(screen.getByText('contract renewal')).toBeInTheDocument();
    expect(screen.getByRole('article').textContent).toContain('For contract renewal');
  });
});

describe('what_happened_next', () => {
  it('shows what followed', () => {
    render(<RenderedAnswer result={maximal.what_happened_next} />);
    expect(screen.getByText('Then')).toBeInTheDocument();
    expect(screen.getByText('And the CPA?')).toBeInTheDocument();
  });

  it('says so plainly when nothing did, rather than showing an empty list', () => {
    render(<RenderedAnswer result={minimal.what_happened_next} />);
    expect(screen.getByText('Nothing followed this in the call.')).toBeInTheDocument();
    expect(screen.queryByText('Then')).not.toBeInTheDocument();
  });
});

describe('coverage_check', () => {
  it('flags thin evidence and uses the singular for a single call', () => {
    render(<RenderedAnswer result={minimal.coverage_check} />);
    expect(screen.getByText('thin')).toBeInTheDocument();
    expect(screen.getByText(/just 1 call\./)).toBeInTheDocument();
  });

  it('reports the plain count when the evidence is solid', () => {
    render(<RenderedAnswer result={maximal.coverage_check} />);
    expect(screen.queryByText('thin')).not.toBeInTheDocument();
    expect(screen.getByText(/drawn from 9 of Naren’s calls\./)).toBeInTheDocument();
  });

  it('never reads as a confirmation that the situation is covered', () => {
    render(<RenderedAnswer result={maximal.coverage_check} />);
    expect(screen.getByText(/not a confirmation that your situation is covered/)).toBeInTheDocument();
  });
});

describe('call_prep', () => {
  it('says when the list was trimmed rather than exhaustive', () => {
    render(<RenderedAnswer result={maximal.call_prep} />);
    expect(screen.getByText(/the 1 most likely of 7 situations nearby/)).toBeInTheDocument();
    expect(screen.getByText('15 exchanges nearby')).toBeInTheDocument();
  });

  it('omits that clause when nothing was trimmed, and distinguishes a missing play', () => {
    render(<RenderedAnswer result={minimal.call_prep} />);
    expect(screen.queryByText(/most likely of/)).not.toBeInTheDocument();
    expect(screen.getByText('1 exchange nearby')).toBeInTheDocument();
    // "no play is recorded" is a fact about what we hold; an empty list would read as a
    // fact about the work.
    expect(screen.getByText(/No play is recorded for this one/)).toBeInTheDocument();
  });
});

describe('improve_at_move', () => {
  it('leads with the focused move and lists its pitfalls', () => {
    render(<RenderedAnswer result={maximal.improve_at_move} />);
    expect(screen.getByText('Getting better at this')).toBeInTheDocument();
    expect(screen.getByText('What tends to go wrong')).toBeInTheDocument();
    expect(screen.getByText('States the delivery number before any apology.')).toBeInTheDocument();
  });

  it('admits when it matched no single move and is showing the whole play', () => {
    render(<RenderedAnswer result={minimal.improve_at_move} />);
    expect(screen.getByText('The whole play')).toBeInTheDocument();
    expect(screen.getByText(/matched a single recorded move/)).toBeInTheDocument();
    expect(screen.queryByText('What tends to go wrong')).not.toBeInTheDocument();
  });
});

describe('where_else_seen', () => {
  it('states a range when the account count is uncertain, and flags the off-situation tail', () => {
    render(<RenderedAnswer result={maximal.where_else_seen} />);
    const body = screen.getByRole('article').textContent ?? '';
    expect(body).toContain('Between');
    expect(body).toContain('across 20 exchanges');
    expect(body).toContain('are about that same situation');
    // an unnameable call is shown as the filename it is, never as a client name
    expect(screen.getByText('8f2c19ae-5b31.json')).toBeInTheDocument();
    expect(screen.getByText(/4 exchanges · 2 calls/)).toBeInTheDocument();
  });

  it('collapses to a single count when both bounds agree, and drops the tail clause', () => {
    render(<RenderedAnswer result={minimal.where_else_seen} />);
    const body = screen.getByRole('article').textContent ?? '';
    expect(body).not.toContain('Between');
    expect(body).toContain('across 1 exchange');
    expect(body).not.toContain('about that same situation');
  });
});

describe('play_confidence', () => {
  it('marks a capped evidence count as a floor rather than a number', () => {
    render(<RenderedAnswer result={maximal.play_confidence} />);
    expect(screen.getByText(/Built from at least/)).toBeInTheDocument();
    expect(screen.getByText(/the real number may be higher/)).toBeInTheDocument();
    expect(screen.getByText('moves')).toBeInTheDocument();
    expect(screen.getByText('quotes')).toBeInTheDocument();
  });

  it('states it plainly when it is not capped, and uses singular labels', () => {
    render(<RenderedAnswer result={minimal.play_confidence} />);
    expect(screen.queryByText(/at least/)).not.toBeInTheDocument();
    expect(screen.getByText('move')).toBeInTheDocument();
    expect(screen.getByText('quote')).toBeInTheDocument();
  });
});

describe('the Layer C playbook kinds', () => {
  it('sequence numbers the steps under the scenario', () => {
    render(<RenderedAnswer result={maximal.sequence} />);
    expect(screen.getByText('The order Naren runs it in')).toBeInTheDocument();
    expect(screen.getByText('Check delivery.')).toBeInTheDocument();
  });

  it('phrasing shows the phrase, its verbatim quote and the call it came from', () => {
    render(<RenderedAnswer result={maximal.phrasing} />);
    expect(screen.getByText('How Naren words it')).toBeInTheDocument();
    expect(screen.getByText(/Let us look at delivery first/)).toBeInTheDocument();
    expect(screen.getByText(/Account A · March 2024/)).toBeInTheDocument();
  });

  it('pitfalls pairs our sentence with Naren’s quote', () => {
    render(<RenderedAnswer result={maximal.pitfalls} />);
    expect(screen.getByText('What usually goes wrong')).toBeInTheDocument();
    expect(screen.getByText('Promising a number before checking delivery.')).toBeInTheDocument();
  });

  it('scenario_check gives no verdict, only when the play applies', () => {
    render(<RenderedAnswer result={maximal.scenario_check} />);
    expect(screen.getByText('When this play applies')).toBeInTheDocument();
    expect(screen.getByText(/cannot tell from one sentence/)).toBeInTheDocument();
  });

  it('show_exchange prints both halves verbatim with its source', () => {
    render(<RenderedAnswer result={maximal.show_exchange} />);
    expect(screen.getByText('The real exchange')).toBeInTheDocument();
    expect(screen.getByText('Client said')).toBeInTheDocument();
    expect(screen.getByText('Naren replied')).toBeInTheDocument();
  });
});
