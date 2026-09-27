/**
 * How the thread rail talks about time (#39): the date groups, and "last asked 3 days ago".
 *
 * CALENDAR DAYS IN THE READER'S OWN TIME ZONE, not 24-hour windows. A thread asked at 23:50
 * is "Yesterday" at 00:10, because that is what a CSM means by yesterday. Which is also why
 * nothing here may run during the server render: the server's zone is not the reader's, so
 * callers pass a `now` that exists only after mount.
 */

const DAY_MS = 86_400_000;

export const BUCKETS = ['Today', 'Yesterday', 'This week', 'This month', 'Earlier'] as const;
export type Bucket = (typeof BUCKETS)[number];

function startOfDay(d: Date): number {
  const s = new Date(d);
  s.setHours(0, 0, 0, 0);
  return s.getTime();
}

/** Whole calendar days from `then` to `now`; rounded, because a DST change makes a day 23h
 *  or 25h long. */
function calendarDays(then: Date, now: Date): number {
  return Math.round((startOfDay(now) - startOfDay(then)) / DAY_MS);
}

export function bucketOf(then: Date, now: Date): Bucket {
  const days = calendarDays(then, now);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return 'This week';
  if (days < 30) return 'This month';
  return 'Earlier';
}

/** Group newest-first items under their bucket, in bucket order, dropping empty buckets.
 *  Order inside a group is the order given. */
export function groupByBucket<T>(items: T[], when: (item: T) => Date, now: Date): { label: Bucket; items: T[] }[] {
  const groups = new Map<Bucket, T[]>();
  for (const item of items) {
    const label = bucketOf(when(item), now);
    groups.set(label, [...(groups.get(label) ?? []), item]);
  }
  return BUCKETS.filter(b => groups.has(b)).map(label => ({ label, items: groups.get(label)! }));
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** "just now", "5 minutes ago", "3 hours ago", "yesterday", "4 days ago", "on 4 Sep". Reads
 *  after "last asked". */
export function relativeTime(then: Date, now: Date): string {
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${plural(minutes, 'minute')} ago`;
  const days = calendarDays(then, now);
  if (days <= 0) return `${plural(Math.floor(minutes / 60), 'hour')} ago`;
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days} days ago`;
  const sameYear = then.getFullYear() === now.getFullYear();
  return `on ${then.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    ...(sameYear ? {} : { year: 'numeric' }),
  })}`;
}
