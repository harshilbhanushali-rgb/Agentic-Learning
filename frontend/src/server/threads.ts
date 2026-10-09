import type { AskNarenResponse } from '@/types';

import type { Db } from './db';

/**
 * Stored threads (issue #46; decided in #37 and #39).
 *
 * EVERY FUNCTION TAKES THE USER. There is no "load thread by id": a CSM sees only their own
 * threads, so ownership is part of every query rather than a check a caller could forget.
 * A thread that is someone else's, deleted, or missing is the same answer -- null / false --
 * so an id reveals nothing about threads that are not yours.
 */

export interface StoredTurn {
  position: number;
  question: string;
  response: AskNarenResponse;
  askedAt: Date;
  answeredAt: Date;
}

export interface ThreadSummary {
  id: number;
  /** The rename if there is one, otherwise the first question. */
  title: string;
  renamed: boolean;
  createdAt: Date;
  lastTurnAt: Date;
  turnCount: number;
}

export interface StoredThread extends ThreadSummary {
  turns: StoredTurn[];
}

export const MAX_TITLE_LENGTH = 120;

/**
 * The columns copied out of a response for querying. Generic over the arms on purpose: the
 * rendered kinds are still growing, and a per-kind switch here would silently store NULL for
 * every kind added after it. So each field is looked for where the contract puts it.
 */
export function extractColumns(response: AskNarenResponse): {
  outcome: string;
  kind: string | null;
  reason: string | null;
  intent: string | null;
  scenarioKey: string | null;
  cosine: number | null;
} {
  const r = response as unknown as Record<string, unknown>;
  const obj = (v: unknown) => (v && typeof v === 'object' ? (v as Record<string, unknown>) : undefined);
  const str = (v: unknown) => (typeof v === 'string' && v ? v : null);
  const match = obj(r.match);
  const scenarioKey =
    str(match?.scenario_key) ??
    str(r.scenario_key) ??
    str(obj(r.citation)?.scenario_key) ??
    str(obj(r.nearest)?.scenario_key);
  return {
    outcome: String(r.outcome),
    kind: r.outcome === 'rendered' ? str(r.kind) : null,
    reason: r.outcome === 'declined' ? str(r.reason) : null,
    intent: str(obj(r.intake)?.intent),
    scenarioKey,
    cosine: typeof match?.cosine === 'number' ? match.cosine : null,
  };
}

/**
 * Record one turn, creating the thread if `threadId` is null. ONE STATEMENT either way, so
 * a thread never exists without its first turn and a turn never lands in a thread it does
 * not own.
 *
 * The position comes from `turn_count + 1` under the row lock the UPDATE takes, so two tabs
 * asking in one thread at once are both recorded, in arrival order (#37). Returns null when
 * the thread is not the user's, or was deleted -- the caller must not have got this far.
 */
export async function recordTurn(
  db: Db,
  input: {
    userId: number;
    threadId: number | null;
    question: string;
    response: AskNarenResponse;
    askedAt: Date;
    answeredAt: Date;
  },
): Promise<{ threadId: number; position: number } | null> {
  const c = extractColumns(input.response);
  const turnValues = [
    input.question,
    JSON.stringify(input.response),
    c.outcome,
    c.kind,
    c.reason,
    c.intent,
    c.scenarioKey,
    c.cosine,
    input.askedAt,
    input.answeredAt,
  ];
  const insertTurn = `
    insert into ask_naren.turns
      (thread_id, position, question, response, outcome, kind, reason, intent, scenario_key,
       cosine, asked_at, answered_at)
    select t.id, t.turn_count, $1, $2::jsonb, $3, $4, $5, $6, $7, $8, $9, $10 from t
    returning thread_id, position`;

  const { rows } =
    input.threadId === null
      ? await db.query<{ thread_id: string | number; position: number }>(
          `with t as (
             insert into ask_naren.threads (user_id, created_at, last_turn_at, turn_count)
             values ($11, $9, $10, 1)
             returning id, turn_count)
           ${insertTurn}`,
          [...turnValues, input.userId],
        )
      : await db.query<{ thread_id: string | number; position: number }>(
          `with t as (
             update ask_naren.threads
             set turn_count = turn_count + 1, last_turn_at = $10
             where id = $11 and user_id = $12 and deleted_at is null
             returning id, turn_count)
           ${insertTurn}`,
          [...turnValues, input.threadId, input.userId],
        );
  const row = rows[0];
  // bigint arrives as a string from `pg`; ids stay far below 2^53.
  return row ? { threadId: Number(row.thread_id), position: row.position } : null;
}

const SUMMARY_COLUMNS = `
  t.id, t.title, t.created_at, t.last_turn_at, t.turn_count,
  coalesce(t.title, (select q.question from ask_naren.turns q
                     where q.thread_id = t.id and q.position = 1)) as display_title`;

type SummaryRow = {
  id: string | number;
  title: string | null;
  display_title: string | null;
  created_at: Date;
  last_turn_at: Date;
  turn_count: number;
};

function summary(row: SummaryRow): ThreadSummary {
  return {
    id: Number(row.id),
    title: row.display_title ?? '',
    renamed: row.title !== null,
    createdAt: new Date(row.created_at),
    lastTurnAt: new Date(row.last_turn_at),
    turnCount: row.turn_count,
  };
}

/** The rail (#39): newest first, deleted ones gone. */
export async function listThreads(db: Db, userId: number): Promise<ThreadSummary[]> {
  const { rows } = await db.query<SummaryRow>(
    `select ${SUMMARY_COLUMNS} from ask_naren.threads t
     where t.user_id = $1 and t.deleted_at is null
     order by t.last_turn_at desc, t.id desc`,
    [userId],
  );
  return rows.map(summary);
}

/** A whole thread in order, or null if it is not this user's to see. */
export async function loadThread(
  db: Db,
  userId: number,
  threadId: number,
): Promise<StoredThread | null> {
  const head = await db.query<SummaryRow>(
    `select ${SUMMARY_COLUMNS} from ask_naren.threads t
     where t.id = $1 and t.user_id = $2 and t.deleted_at is null`,
    [threadId, userId],
  );
  if (!head.rows[0]) return null;
  const { rows } = await db.query<{
    position: number;
    question: string;
    response: AskNarenResponse | string;
    asked_at: Date;
    answered_at: Date;
  }>(
    `select position, question, response, asked_at, answered_at
     from ask_naren.turns where thread_id = $1 order by position`,
    [threadId],
  );
  return {
    ...summary(head.rows[0]),
    turns: rows.map(r => ({
      position: r.position,
      question: r.question,
      response: typeof r.response === 'string' ? JSON.parse(r.response) : r.response,
      askedAt: new Date(r.asked_at),
      answeredAt: new Date(r.answered_at),
    })),
  };
}

/** A rename; null or blank clears it back to the derived title. False if not the user's. */
export async function renameThread(
  db: Db,
  userId: number,
  threadId: number,
  title: string | null,
): Promise<boolean> {
  const cleaned = title?.trim() ? title.trim().slice(0, MAX_TITLE_LENGTH) : null;
  const { rows } = await db.query(
    `update ask_naren.threads set title = $3
     where id = $1 and user_id = $2 and deleted_at is null returning id`,
    [threadId, userId, cleaned],
  );
  return rows.length > 0;
}

/** "Remove from your list" (#39). Soft: the rows stay (#37). False if not the user's. */
export async function deleteThread(db: Db, userId: number, threadId: number): Promise<boolean> {
  const { rows } = await db.query(
    `update ask_naren.threads set deleted_at = now()
     where id = $1 and user_id = $2 and deleted_at is null returning id`,
    [threadId, userId],
  );
  return rows.length > 0;
}
