// @vitest-environment node
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import type { AskNarenResponse } from '@/types';

import { declineGroup, istDayKey, loadUsage, parseRange, windowFor } from './analytics';
import type { Db } from './db';
import { recordFeedback } from './feedback';
import { freshDb } from './testing/pglite';
import { recordTurn } from './threads';

let db: Db;
let reset: () => Promise<void>;
let close: () => Promise<void>;

beforeAll(async () => {
  const fresh = await freshDb();
  db = fresh.db;
  reset = fresh.reset;
  close = () => fresh.pg.close();
});
afterAll(() => close());
beforeEach(() => reset());

// Tuesday 10 Nov 2026, 14:30 India time.
const NOW = new Date('2026-11-10T09:00:00Z');

const ANSWERED = {
  outcome: 'answered',
  answer: 'a',
  quote: 'q',
  citation: { label: 'c', call_filename: 'c', scenario_key: 'ats_integration' },
  match: { cosine: 0.8, scenario_key: 'ats_integration', rank: 1 },
} as AskNarenResponse;
const CLARIFY = { outcome: 'clarify', question: 'Which client?' } as AskNarenResponse;
const SEQUENCE = {
  outcome: 'rendered', kind: 'sequence', scenario_key: 'xml_feed', steps: ['a'],
} as unknown as AskNarenResponse;
const declined = (reason: string) =>
  ({ outcome: 'declined', reason, message: 'm' }) as unknown as AskNarenResponse;

async function user(name: string, opts: { linked?: boolean; disabled?: boolean } = {}): Promise<number> {
  const { rows } = await db.query<{ id: number }>(
    `insert into ask_naren.users (email, name, google_sub, disabled_at) values ($1, $2, $3, $4) returning id`,
    [`${name.toLowerCase()}@joveo.com`, name, opts.linked ? `g-${name}` : null, opts.disabled ? NOW : null],
  );
  return rows[0].id;
}

async function ask(userId: number, threadId: number | null, at: string, response: AskNarenResponse, question = `q at ${at}`) {
  const askedAt = new Date(at);
  const r = await recordTurn(db, {
    userId, threadId, question, response, askedAt, answeredAt: new Date(askedAt.getTime() + 12_000),
  });
  return r!;
}

async function seed() {
  const ana = await user('Ana', { linked: true });
  const karan = await user('Karan', { linked: true });
  const old = await user('Old', { linked: true });
  await user('Newbie');
  await user('Lurker', { linked: true });
  const gone = await user('Gone', { linked: true, disabled: true });

  // Ana: four questions in three chats on three India-time days -- a regular.
  const t1 = await ask(ana, null, '2026-11-10T08:00:00Z', ANSWERED);
  await ask(ana, t1.threadId, '2026-11-10T08:05:00Z', CLARIFY);
  const t2 = await ask(ana, null, '2026-11-09T05:00:00Z', declined('no_close_match'), 'Client wants to pause spend');
  await ask(ana, null, '2026-11-05T10:00:00Z', SEQUENCE);
  await recordFeedback(db, { userId: ana, threadId: t1.threadId, position: 1, rating: 'good', now: NOW });
  await recordFeedback(db, { userId: ana, threadId: t2.threadId, position: 1, rating: 'bad', reason: 'off topic', now: NOW });

  // Karan: 19:00 UTC on 3 Nov is 00:30 on Wednesday 4 Nov in India -- inside a 7-day window.
  await ask(karan, null, '2026-11-03T19:00:00Z', declined('service_busy'));
  await ask(karan, null, '2026-10-30T06:00:00Z', ANSWERED); // the window before

  await ask(old, null, '2026-10-01T06:00:00Z', ANSWERED); // long ago: gone quiet
  await ask(gone, null, '2026-11-06T06:00:00Z', ANSWERED); // disabled now, but asked
  return { ana, karan };
}

describe('helpers', () => {
  it('reads a range, defaulting to 30 days', () => {
    expect(parseRange('7')).toBe('7');
    expect(parseRange('all')).toBe('all');
    expect(parseRange('365')).toBe('30');
    expect(parseRange(undefined)).toBe('30');
  });

  it('starts a window at India-time midnight', () => {
    const { from, previousFrom } = windowFor('7', NOW);
    expect(from).toEqual(new Date('2026-11-03T18:30:00Z'));
    expect(previousFrom).toEqual(new Date('2026-10-27T18:30:00Z'));
    expect(istDayKey(new Date('2026-11-03T19:00:00Z'))).toBe('2026-11-04');
  });

  it('groups decline reasons by what an admin would do about them', () => {
    expect(declineGroup('no_close_match')).toBe('gap');
    expect(declineGroup('out_of_scope')).toBe('gap');
    expect(declineGroup('service_busy')).toBe('busy');
    expect(declineGroup('deadline_exceeded')).toBe('busy');
    expect(declineGroup('service_error')).toBe('broke');
    expect(declineGroup(null)).toBe('broke');
  });
});

describe('loadUsage', () => {
  it('is empty, not broken, with no data', async () => {
    const r = await loadUsage(db, '30', NOW);
    expect(r.questions).toBe(0);
    expect(r.daily).toHaveLength(30);
    expect(r.wait).toBeNull();
    expect(r.people).toEqual([]);
    expect((await loadUsage(db, 'all', NOW)).daily).toEqual([]);
  });

  it('counts the last 7 India-time days', async () => {
    const { ana } = await seed();
    const r = await loadUsage(db, '7', NOW);

    expect(r.questions).toBe(6);
    expect(r.chats).toBe(5);
    expect(r.activePeople).toBe(3);
    expect(r.previous).toEqual({ questions: 1, activePeople: 1 });
    expect(r.access).toEqual({ enabled: 5, signedIn: 4, asked: 2, regulars: 1 });
    // Rendered answers count as answered.
    expect(r.outcomes).toEqual({ answered: 3, clarify: 1, declined: 2 });
    expect(r.declines).toEqual({ gap: 1, busy: 1, broke: 0 });
    expect(r.ratings).toEqual({ good: 1, bad: 1 });
    expect(r.weeklyRatings).toEqual([{ week: '2026-11-09', good: 1, bad: 1 }]);
    expect(r.wait).toEqual({ p50: 12, p90: 12 });

    expect(r.daily.map(d => d.day)).toEqual([
      '2026-11-04', '2026-11-05', '2026-11-06', '2026-11-07', '2026-11-08', '2026-11-09', '2026-11-10',
    ]);
    expect(r.daily[0]).toEqual({ day: '2026-11-04', questions: 1, people: 1 });
    expect(r.daily[6]).toEqual({ day: '2026-11-10', questions: 2, people: 1 });
    // Weekdays 4, 5, 6, 9, 10 Nov had 1, 1, 1, 1, 1 people.
    expect(r.avgWeekdayPeople).toBe(1);
    // Wednesday 00:30 in India.
    expect(r.heat[2][0]).toBe(1);

    expect(r.people.map(p => p.name)).toEqual(['Ana', 'Gone', 'Karan']);
    expect(r.people[0]).toMatchObject({ id: ana, questions: 4, activeDays: 3, chats: 3, good: 1, bad: 1 });

    // Most-asked first; the clarify and the two declines named no topic.
    expect(r.topics).toEqual([
      { key: null, questions: 3, good: 0, bad: 1 },
      { key: 'ats_integration', questions: 2, good: 1, bad: 0 },
      { key: 'xml_feed', questions: 1, good: 0, bad: 0 },
    ]);
    // Both kinds, newest first (same time: the later turn first); the reason only where given.
    expect(r.feedback).toEqual([
      { question: 'Client wants to pause spend', name: 'Ana', topic: null, at: NOW, rating: 'bad', reason: 'off topic' },
      { question: 'q at 2026-11-10T08:00:00Z', name: 'Ana', topic: 'ats_integration', at: NOW, rating: 'good', reason: null },
    ]);
    // Only coverage gaps -- the busy decline is not a question Naren's calls failed.
    expect(r.gaps.map(g => g.question)).toEqual(['Client wants to pause spend']);

    expect(r.nudges.neverSignedIn.map(p => p.name)).toEqual(['Newbie']);
    expect(r.nudges.neverAsked.map(p => p.name)).toEqual(['Lurker']);
    expect(r.nudges.goneQuiet).toEqual([
      { name: 'Old', email: 'old@joveo.com', lastAsked: new Date('2026-10-01T06:00:00Z') },
    ]);
  });

  it('covers everything for all time, from the first question', async () => {
    await seed();
    const r = await loadUsage(db, 'all', NOW);
    expect(r.from).toBeNull();
    expect(r.previous).toBeNull();
    expect(r.questions).toBe(8);
    expect(r.daily[0].day).toBe('2026-10-01');
    expect(r.daily.at(-1)!.day).toBe('2026-11-10');
    expect(r.daily).toHaveLength(41);
  });

  it('still counts questions from a removed chat', async () => {
    const { ana } = await seed();
    await db.query('update ask_naren.threads set deleted_at = $1 where user_id = $2', [NOW, ana]);
    expect((await loadUsage(db, '7', NOW)).questions).toBe(6);
  });
});
