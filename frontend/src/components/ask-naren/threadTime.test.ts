import { describe, expect, it } from 'vitest';

import { bucketOf, groupByBucket, relativeTime } from './threadTime';

// Local-time constructors, so the test holds in whatever zone it runs in.
const at = (y: number, mo: number, d: number, h = 12, mi = 0) => new Date(y, mo - 1, d, h, mi);
const NOW = at(2026, 9, 28, 9, 30);

describe('bucketOf', () => {
  it('groups by calendar day, not by 24-hour windows', () => {
    expect(bucketOf(at(2026, 9, 28, 0, 5), NOW)).toBe('Today');
    // Under 24 hours ago, but on the previous calendar day.
    expect(bucketOf(at(2026, 9, 27, 23, 50), NOW)).toBe('Yesterday');
    expect(bucketOf(at(2026, 9, 22), NOW)).toBe('This week');
    expect(bucketOf(at(2026, 9, 21), NOW)).toBe('This month');
    expect(bucketOf(at(2026, 8, 30), NOW)).toBe('This month'); // 29 days
    expect(bucketOf(at(2026, 8, 29), NOW)).toBe('Earlier'); // 30 days
  });
});

describe('groupByBucket', () => {
  it('keeps bucket order and the given order within a bucket, and drops empty buckets', () => {
    const items = [at(2026, 9, 28, 9), at(2026, 9, 28, 8), at(2026, 9, 10), at(2025, 1, 1)];
    const groups = groupByBucket(items, d => d, NOW);
    expect(groups.map(g => [g.label, g.items.length])).toEqual([
      ['Today', 2],
      ['This month', 1],
      ['Earlier', 1],
    ]);
    expect(groups[0].items[0]).toBe(items[0]);
  });
});

describe('relativeTime', () => {
  it('reads naturally after "last asked"', () => {
    expect(relativeTime(at(2026, 9, 28, 9, 30), NOW)).toBe('just now');
    expect(relativeTime(at(2026, 9, 28, 9, 29), NOW)).toBe('1 minute ago');
    expect(relativeTime(at(2026, 9, 28, 9, 5), NOW)).toBe('25 minutes ago');
    expect(relativeTime(at(2026, 9, 28, 6, 0), NOW)).toBe('3 hours ago');
    expect(relativeTime(at(2026, 9, 27, 23, 0), NOW)).toBe('yesterday');
    expect(relativeTime(at(2026, 9, 25), NOW)).toBe('3 days ago');
    // ICU spells September 'Sep' or 'Sept' depending on its version.
    expect(relativeTime(at(2026, 9, 4), NOW)).toMatch(/^on 4 Sept?$/);
    expect(relativeTime(at(2025, 12, 1), NOW)).toBe('on 1 Dec 2025');
  });
});
