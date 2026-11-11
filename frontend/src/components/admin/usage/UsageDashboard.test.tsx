import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { UsageReport } from '@/server/analytics';

import { axis } from './DailyChart';
import { UsageDashboard } from './UsageDashboard';

const NOW = new Date('2026-11-10T09:00:00Z');
const heat = Array.from({ length: 7 }, () => new Array<number>(24).fill(0));
heat[0][11] = 4;

const REPORT: UsageReport = {
  range: '7',
  from: new Date('2026-11-03T18:30:00Z'),
  to: NOW,
  daily: ['04', '05', '06', '07', '08', '09', '10'].map((d, i) => ({ day: `2026-11-${d}`, questions: i, people: i ? 1 : 0 })),
  questions: 21,
  chats: 10,
  activePeople: 3,
  previous: { questions: 14, activePeople: 3 },
  avgWeekdayPeople: 1.5,
  access: { enabled: 5, signedIn: 4, asked: 2, regulars: 1 },
  outcomes: { answered: 15, clarify: 2, declined: 4 },
  declines: { gap: 3, busy: 1, broke: 0 },
  ratings: { good: 8, bad: 2 },
  weeklyRatings: [{ week: '2026-11-02', good: 3, bad: 1 }, { week: '2026-11-09', good: 5, bad: 1 }],
  wait: { p50: 14.2, p90: 26 },
  heat,
  topics: [{ key: 'ats_integration', questions: 12, good: 1, bad: 3 }, { key: null, questions: 9, good: 7, bad: 0 }],
  people: [
    { id: 1, name: 'Ana', email: 'ana@joveo.com', questions: 15, activeDays: 4, chats: 6, good: 6, bad: 2, lastAsked: NOW },
    { id: 2, name: 'Karan', email: 'karan@joveo.com', questions: 6, activeDays: 2, chats: 4, good: 0, bad: 0, lastAsked: new Date('2026-11-06T06:00:00Z') },
  ],
  feedback: [
    { question: 'Client wants to pause spend', name: 'Ana', topic: null, at: NOW, rating: 'bad', reason: 'off topic' },
    { question: 'How long does ATS take?', name: 'Karan', topic: 'ats_integration', at: NOW, rating: 'good', reason: 'spot on' },
  ],
  gaps: [{ question: 'Renewal pushback', name: 'Karan', at: new Date('2026-11-09T06:00:00Z') }],
  nudges: {
    neverSignedIn: [{ name: 'Newbie', email: 'newbie@joveo.com' }],
    neverAsked: [],
    goneQuiet: [{ name: 'Old', email: 'old@joveo.com', lastAsked: new Date('2026-10-01T06:00:00Z') }],
  },
};

describe('UsageDashboard', () => {
  it('shows the headline numbers, people, ratings and gaps', () => {
    render(<UsageDashboard range="7" report={REPORT} />);
    expect(screen.getByRole('link', { name: '7 days' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Usage' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('+50% vs the period before')).toBeInTheDocument();
    expect(screen.getByText('Same as the period before')).toBeInTheDocument();

    const rows = within(screen.getByRole('table', { name: '' })).getAllByRole('row').slice(1);
    expect(within(rows[0]).getByText('Ana')).toBeInTheDocument();
    expect(within(rows[0]).getByText('Today 14:30')).toBeInTheDocument();
    expect(within(rows[1]).getByText('6 Nov')).toBeInTheDocument();

    // 8 of 10 rated answers liked.
    expect(within(screen.getByRole('region', { name: 'Are they liking it?' })).getByText('80%')).toBeInTheDocument();
    // Feedback shows both kinds, each with its comment.
    const feedback = within(screen.getByRole('region', { name: 'Latest feedback' }));
    expect(feedback.getByText('“Client wants to pause spend”')).toBeInTheDocument();
    expect(feedback.getByText('Thumbs down')).toBeInTheDocument();
    expect(feedback.getByText('Thumbs up')).toBeInTheDocument();
    expect(feedback.getByText('spot on')).toBeInTheDocument();
    expect(screen.getByText('“Renewal pushback”')).toBeInTheDocument();
    expect(screen.getByText(/Typical wait for an answer/).textContent).toBe('Typical wait for an answer: 14s · 9 in 10 under 26s');
    // A topic with 3+ ratings and under 70% liked is flagged.
    expect(screen.getByText('25%')).toHaveClass('text-error');
    expect(screen.getByText('Newbie')).toBeInTheDocument();
    expect(screen.getByText('Nobody.')).toBeInTheDocument();
  });

  it('switches the daily chart between questions and people', async () => {
    render(<UsageDashboard range="7" report={REPORT} />);
    const people = screen.getByRole('button', { name: 'people' });
    await userEvent.click(people);
    expect(people).toHaveAttribute('aria-pressed', 'true');
  });

  it('says so when there is nothing yet, rather than showing broken charts', () => {
    const empty: UsageReport = {
      ...REPORT, daily: [], questions: 0, chats: 0, activePeople: 0, previous: null, avgWeekdayPeople: 0,
      outcomes: { answered: 0, clarify: 0, declined: 0 }, declines: { gap: 0, busy: 0, broke: 0 },
      ratings: { good: 0, bad: 0 }, weeklyRatings: [], wait: null, topics: [], people: [], feedback: [], gaps: [],
    };
    render(<UsageDashboard range="all" report={empty} />);
    expect(screen.getByText('No questions yet.')).toBeInTheDocument();
    expect(screen.getByText('Nobody asked a question in this period.')).toBeInTheDocument();
    expect(screen.getByText('No answers were rated in this period.')).toBeInTheDocument();
  });

  it('reports a database fault as a fault', () => {
    render(<UsageDashboard range="30" report={null} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load usage just now');
  });
});

describe('axis', () => {
  it('uses round steps that cover the tallest bar', () => {
    expect(axis(31)).toEqual([40, 20, 0]);
    expect(axis(7)).toEqual([10, 5, 0]);
    expect(axis(0)).toEqual([1, 0]);
  });
});
