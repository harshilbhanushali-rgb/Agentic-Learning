import type { RadarMeeting, TestQueueItem, CaseStudy, FailureEntry, PrepStatus } from '@/types';

/**
 * Hand-built props, deliberately NOT drawn from src/data.
 *
 * The fixture data in src/data happens to be homogeneous -- every meeting there carries
 * the same shape of optional field, every test-queue item the same combination. Rendering
 * a page against it takes one side of most `className` ternaries and never the other,
 * which reads as green while measuring nothing. Branch coverage comes from props built
 * to hit a specific leg; line coverage comes from the page-level renders. Both are needed.
 */

export function meeting(over: Partial<RadarMeeting> = {}): RadarMeeting {
  return {
    id: 1,
    day: 'TUE',
    time: '10:00',
    relative: 'in 2 days',
    account: 'Account A',
    title: 'Renewal review',
    tags: 'renewal · enterprise',
    prepStatus: 'in-progress',
    prepLabel: 'In progress',
    industry: 'Healthcare',
    clip: { quote: 'Let me show you the numbers first.', meta: 'Naren · 2024' },
    tip: 'Open with the delivery number, not the apology.',
    waterfall: [
      { state: 'done', kind: 'Watch', label: 'Expert clip', meta: 'Completed' },
      { state: 'active', kind: 'Read', label: 'Account brief', meta: '3 min' },
      { state: 'locked', kind: 'Apply', label: 'Simulation', meta: 'Locked' },
    ],
    ...over,
  };
}

/** A meeting whose every optional/variant field takes the opposite leg to `meeting()`. */
export function meetingVariant(prepStatus: PrepStatus): RadarMeeting {
  return meeting({
    prepStatus,
    prepLabel: prepStatus,
    clip: { label: 'Custom clip label', quote: 'Different quote.', meta: 'Naren · 2023' },
    waterfall: [
      // a locked step carrying real `meta` -- the title text differs from the
      // generic "Complete the previous step to unlock" that a bare 'Locked' gets
      { state: 'locked', kind: 'Apply', label: 'Simulation', meta: 'Unlocks Thursday' },
    ],
  });
}

export function testQueueItem(over: Partial<TestQueueItem> = {}): TestQueueItem {
  return {
    id: 1,
    title: 'Discovery call scoring',
    tier: 1,
    level: 'Apply',
    scored: 82,
    status: 'complete',
    time: '12 min',
    note: 'Retake available',
    ...over,
  };
}

export function caseStudy(over: Partial<CaseStudy> = {}): CaseStudy {
  return {
    id: 1,
    account: 'Account A',
    headline: 'Recovered a stalled ramp',
    sector: 'Healthcare',
    region: 'NA',
    monthsActive: 7,
    total: 12,
    status: 'live',
    justDropped: true,
    participants: 4,
    context: 'Applications were flat for three weeks while spend ran.',
    chapters: [{ num: 1, title: 'The stall', summary: 'Spend was live, applies were not.' }],
    ...over,
  };
}

export function failureEntry(over: Partial<FailureEntry> = {}): FailureEntry {
  return {
    id: 1,
    deal: 'Account Q renewal',
    category: 'Over-promised delivery',
    lesson: 'Quote the floor, not the ceiling.',
    quarter: 'Q3 2024',
    fullPostMortem: 'The client heard a forecast as a commitment, and we never corrected it.',
    ...over,
  };
}
