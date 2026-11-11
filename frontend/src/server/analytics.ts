import type { Db } from './db';

/**
 * Usage analytics for the admin Usage page: who uses Ask Naren, how much, whether they like
 * the answers, and what it cannot answer. READ-ONLY, over the tables the app already reads
 * (users, sessions, threads, turns, feedback) with the grants it already has.
 *
 * ALL DAYS AND HOURS ARE INDIA TIME. India has no daylight saving, so a fixed +05:30 offset is
 * exact in JS, and SQL uses 'Asia/Kolkata' for the same thing.
 *
 * Removed chats still count: a soft delete hides a thread from its owner's list, it does not
 * undo the question. Disabled people's questions count too; they are left out only of the
 * "who has access" numbers.
 */

export const RANGES = ['7', '30', '90', 'all'] as const;
export type UsageRange = (typeof RANGES)[number];

export function parseRange(raw: unknown): UsageRange {
  return (RANGES as readonly unknown[]).includes(raw) ? (raw as UsageRange) : '30';
}

const IST_OFFSET_MS = 330 * 60_000;
const DAY_MS = 86_400_000;

/** Start of the India-time calendar day that contains `t`. */
export function istDayStart(t: Date): Date {
  return new Date(Math.floor((t.getTime() + IST_OFFSET_MS) / DAY_MS) * DAY_MS - IST_OFFSET_MS);
}

/** `YYYY-MM-DD` of the India-time day that contains `t`. */
export function istDayKey(t: Date): string {
  return new Date(t.getTime() + IST_OFFSET_MS).toISOString().slice(0, 10);
}

/** Why a question was declined, in three groups an admin acts on differently. */
export type DeclineGroup = 'gap' | 'busy' | 'broke';
const GAP_REASONS = ['no_close_match', 'grounding_unverified', 'follow_up_ungrounded', 'out_of_scope'];
const BUSY_REASONS = ['service_busy', 'deadline_exceeded'];
export function declineGroup(reason: string | null): DeclineGroup {
  if (reason && GAP_REASONS.includes(reason)) return 'gap';
  if (reason && BUSY_REASONS.includes(reason)) return 'busy';
  return 'broke';
}

/** Days without a question after which someone counts as gone quiet. */
export const QUIET_DAYS = 14;
/** Distinct days with a question that make someone a regular. */
export const REGULAR_DAYS = 3;

export interface PersonUsage {
  id: number;
  name: string;
  email: string;
  questions: number;
  activeDays: number;
  chats: number;
  good: number;
  bad: number;
  lastAsked: Date | null;
}

export interface UsageReport {
  range: UsageRange;
  /** Start of the window (an India-time midnight), or null for all time. */
  from: Date | null;
  to: Date;
  /** Every India-time day from the window's first day to today, oldest first. */
  daily: { day: string; questions: number; people: number }[];
  questions: number;
  chats: number;
  /** People who asked at least one question in the window. */
  activePeople: number;
  /** The same two for the window before this one; null for all time. */
  previous: { questions: number; activePeople: number } | null;
  /** Mean people per weekday (Mon-Fri, India time) in the window, quiet days included. */
  avgWeekdayPeople: number;
  access: {
    /** People who can sign in now (not disabled). */
    enabled: number;
    signedIn: number;
    asked: number;
    regulars: number;
  };
  outcomes: { answered: number; clarify: number; declined: number };
  declines: Record<DeclineGroup, number>;
  ratings: { good: number; bad: number };
  /** Rated-answer share by week (weeks start Monday, India time). */
  weeklyRatings: { week: string; good: number; bad: number }[];
  /** Seconds from question to answer, for questions that got one. Null when none did. */
  wait: { p50: number; p90: number } | null;
  /** Question counts by [weekday, Monday = 0][hour 0..23], India time. */
  heat: number[][];
  /** Most-asked first. `key` null = the answer named no single scenario. */
  topics: { key: string | null; questions: number; good: number; bad: number }[];
  /** Everyone who asked in the window, most questions first. */
  people: PersonUsage[];
  /** The latest ratings, up and down, newest first. */
  feedback: { question: string; name: string; topic: string | null; at: Date; rating: 'good' | 'bad'; reason: string | null }[];
  gaps: { question: string; name: string; at: Date }[];
  nudges: {
    neverSignedIn: { name: string; email: string }[];
    neverAsked: { name: string; email: string }[];
    goneQuiet: { name: string; email: string; lastAsked: Date }[];
  };
}

/** The window: the last N India-time days including today, or everything. */
export function windowFor(range: UsageRange, now: Date): { from: Date | null; previousFrom: Date | null } {
  if (range === 'all') return { from: null, previousFrom: null };
  const days = Number(range);
  const from = new Date(istDayStart(now).getTime() - (days - 1) * DAY_MS);
  return { from, previousFrom: new Date(from.getTime() - days * DAY_MS) };
}

/** Every turn in the window, with its owner and the owner's rating. $1 = from (or null), $2 = to. */
const IN_WINDOW = `
  with w as (
    select q.id, q.question, q.outcome, q.reason, q.scenario_key, q.asked_at, q.answered_at,
           t.id as thread_id, t.user_id,
           f.rating, f.reason as rating_reason, f.updated_at as rated_at,
           q.asked_at at time zone 'Asia/Kolkata' as local
    from ask_naren.turns q
    join ask_naren.threads t on t.id = q.thread_id
    left join ask_naren.feedback f on f.turn_id = q.id and f.user_id = t.user_id
    where ($1::timestamptz is null or q.asked_at >= $1::timestamptz) and q.asked_at <= $2::timestamptz
  )`;

export async function loadUsage(db: Db, range: UsageRange, now: Date = new Date()): Promise<UsageReport> {
  const { from, previousFrom } = windowFor(range, now);
  const p = [from, now];

  const [totals, declineRows, dailyRows, heatRows, weekRows, topicRows, userRows, feedbackRows, gapRows, previous] =
    await Promise.all([
      db.query<{
        questions: number; chats: number; answered: number; clarify: number; declined: number;
        good: number; bad: number; wait_p50: number | null; wait_p90: number | null; first_day: string | null;
      }>(
        `${IN_WINDOW}
         select count(*)::int as questions,
                count(distinct thread_id)::int as chats,
                count(*) filter (where outcome in ('answered', 'rendered'))::int as answered,
                count(*) filter (where outcome = 'clarify')::int as clarify,
                count(*) filter (where outcome = 'declined')::int as declined,
                count(*) filter (where rating = 'good')::int as good,
                count(*) filter (where rating = 'bad')::int as bad,
                (percentile_cont(0.5) within group (order by extract(epoch from answered_at - asked_at))
                  filter (where outcome <> 'declined'))::float8 as wait_p50,
                (percentile_cont(0.9) within group (order by extract(epoch from answered_at - asked_at))
                  filter (where outcome <> 'declined'))::float8 as wait_p90,
                to_char(min(local), 'YYYY-MM-DD') as first_day
         from w`,
        p,
      ),
      db.query<{ reason: string | null; n: number }>(
        `${IN_WINDOW} select reason, count(*)::int as n from w where outcome = 'declined' group by reason`,
        p,
      ),
      db.query<{ day: string; questions: number; people: number }>(
        `${IN_WINDOW}
         select to_char(local, 'YYYY-MM-DD') as day, count(*)::int as questions,
                count(distinct user_id)::int as people
         from w group by 1`,
        p,
      ),
      db.query<{ dow: number; hour: number; n: number }>(
        `${IN_WINDOW}
         select extract(isodow from local)::int as dow, extract(hour from local)::int as hour,
                count(*)::int as n
         from w group by 1, 2`,
        p,
      ),
      db.query<{ week: string; good: number; bad: number }>(
        `${IN_WINDOW}
         select to_char(date_trunc('week', local), 'YYYY-MM-DD') as week,
                count(*) filter (where rating = 'good')::int as good,
                count(*) filter (where rating = 'bad')::int as bad
         from w where rating is not null group by 1 order by 1`,
        p,
      ),
      db.query<{ key: string | null; questions: number; good: number; bad: number }>(
        `${IN_WINDOW}
         select scenario_key as key, count(*)::int as questions,
                count(*) filter (where rating = 'good')::int as good,
                count(*) filter (where rating = 'bad')::int as bad
         from w group by 1 order by 2 desc, 1`,
        p,
      ),
      db.query<{
        id: number; name: string; email: string; disabled: boolean; signed_in: boolean;
        questions: number; days: number; chats: number; good: number; bad: number;
        last_asked: Date | null; last_ever: Date | null;
      }>(
        `${IN_WINDOW},
         per as (
           select user_id, count(*)::int as questions,
                  count(distinct to_char(local, 'YYYY-MM-DD'))::int as days,
                  count(distinct thread_id)::int as chats,
                  count(*) filter (where rating = 'good')::int as good,
                  count(*) filter (where rating = 'bad')::int as bad,
                  max(asked_at) as last_asked
           from w group by user_id
         ),
         ever as (
           select t.user_id, max(q.asked_at) as last_ever
           from ask_naren.turns q join ask_naren.threads t on t.id = q.thread_id
           group by t.user_id
         )
         select u.id, u.name, u.email, u.disabled_at is not null as disabled,
                (u.google_sub is not null or e.last_ever is not null
                  or exists (select 1 from ask_naren.sessions s where s.user_id = u.id)) as signed_in,
                coalesce(p.questions, 0) as questions, coalesce(p.days, 0) as days,
                coalesce(p.chats, 0) as chats, coalesce(p.good, 0) as good, coalesce(p.bad, 0) as bad,
                p.last_asked, e.last_ever
         from ask_naren.users u
         left join per p on p.user_id = u.id
         left join ever e on e.user_id = u.id
         order by questions desc, u.name`,
        p,
      ),
      db.query<{ question: string; name: string; topic: string | null; at: Date; rating: 'good' | 'bad'; reason: string | null }>(
        `${IN_WINDOW}
         select w.question, u.name, w.scenario_key as topic, w.rated_at as at, w.rating,
                w.rating_reason as reason
         from w join ask_naren.users u on u.id = w.user_id
         where w.rating is not null
         order by w.rated_at desc, w.id desc limit 8`,
        p,
      ),
      db.query<{ question: string; name: string; at: Date }>(
        `${IN_WINDOW}
         select w.question, u.name, w.asked_at as at
         from w join ask_naren.users u on u.id = w.user_id
         where w.outcome = 'declined' and w.reason = any($3::text[])
         order by w.asked_at desc, w.id desc limit 8`,
        [...p, GAP_REASONS],
      ),
      previousFrom && from
        ? db.query<{ questions: number; people: number }>(
            `select count(*)::int as questions, count(distinct t.user_id)::int as people
             from ask_naren.turns q join ask_naren.threads t on t.id = q.thread_id
             where q.asked_at >= $1 and q.asked_at < $2`,
            [previousFrom, from],
          )
        : Promise.resolve(null),
    ]);

  const t = totals.rows[0];

  // Every day of the window, quiet ones included, so the chart's gaps are real gaps.
  const byDay = new Map(dailyRows.rows.map(r => [r.day, r]));
  const daily: UsageReport['daily'] = [];
  let weekdayPeople = 0;
  let weekdays = 0;
  const firstDay = from ?? (t.first_day ? new Date(`${t.first_day}T00:00:00+05:30`) : null);
  if (firstDay) {
    for (let d = istDayStart(firstDay).getTime(); d <= now.getTime(); d += DAY_MS) {
      const key = istDayKey(new Date(d));
      const row = byDay.get(key);
      daily.push({ day: key, questions: row?.questions ?? 0, people: row?.people ?? 0 });
      const dow = new Date(`${key}T00:00:00Z`).getUTCDay();
      if (dow >= 1 && dow <= 5) {
        weekdays += 1;
        weekdayPeople += row?.people ?? 0;
      }
    }
  }

  const declines: Record<DeclineGroup, number> = { gap: 0, busy: 0, broke: 0 };
  for (const r of declineRows.rows) declines[declineGroup(r.reason)] += r.n;

  const heat = Array.from({ length: 7 }, () => new Array<number>(24).fill(0));
  for (const r of heatRows.rows) heat[r.dow - 1][r.hour] = r.n;

  const users = userRows.rows;
  const enabled = users.filter(u => !u.disabled);
  const quietBefore = now.getTime() - QUIET_DAYS * DAY_MS;

  return {
    range,
    from,
    to: now,
    daily,
    questions: t.questions,
    chats: t.chats,
    activePeople: users.filter(u => u.questions > 0).length,
    previous: previous ? { questions: previous.rows[0].questions, activePeople: previous.rows[0].people } : null,
    avgWeekdayPeople: weekdays ? weekdayPeople / weekdays : 0,
    access: {
      enabled: enabled.length,
      signedIn: enabled.filter(u => u.signed_in).length,
      asked: enabled.filter(u => u.questions > 0).length,
      regulars: enabled.filter(u => u.days >= REGULAR_DAYS).length,
    },
    outcomes: { answered: t.answered, clarify: t.clarify, declined: t.declined },
    declines,
    ratings: { good: t.good, bad: t.bad },
    weeklyRatings: weekRows.rows,
    wait: t.wait_p50 === null || t.wait_p90 === null ? null : { p50: t.wait_p50, p90: t.wait_p90 },
    heat,
    topics: topicRows.rows,
    people: users
      .filter(u => u.questions > 0)
      .map(u => ({
        id: u.id, name: u.name, email: u.email, questions: u.questions, activeDays: u.days,
        chats: u.chats, good: u.good, bad: u.bad, lastAsked: u.last_asked,
      })),
    feedback: feedbackRows.rows,
    gaps: gapRows.rows,
    nudges: {
      neverSignedIn: enabled.filter(u => !u.signed_in).map(u => ({ name: u.name, email: u.email })),
      neverAsked: enabled.filter(u => u.signed_in && !u.last_ever).map(u => ({ name: u.name, email: u.email })),
      goneQuiet: enabled
        .filter(u => u.last_ever && new Date(u.last_ever).getTime() < quietBefore)
        .sort((a, b) => new Date(b.last_ever!).getTime() - new Date(a.last_ever!).getTime())
        .map(u => ({ name: u.name, email: u.email, lastAsked: new Date(u.last_ever!) })),
    },
  };
}
