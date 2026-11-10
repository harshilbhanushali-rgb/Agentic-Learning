import type { Db } from './db';

/**
 * Good / bad ratings on answers (migration 0003). The data that tells us where the engine is
 * wrong AND which answers are right -- the second is what an engine change gets tested
 * against, so it must not break them.
 */
export type Rating = 'good' | 'bad';
export const MAX_REASON_LENGTH = 2000;

/**
 * Rate one turn of the user's own thread. Returns false when there is no such turn for this
 * user -- missing, removed, or someone else's, the same answer (as for threads).
 *
 * One rating per user per turn: a second call replaces it. A call with no reason keeps the
 * reason already given for the SAME rating (the thumb is saved on click, the reason a moment
 * later), and drops it when the rating flips -- a "why it was good" must not survive as the
 * reason for a "bad".
 */
export async function recordFeedback(
  db: Db,
  input: {
    userId: number;
    threadId: number;
    position: number;
    rating: Rating;
    reason?: string | null;
    now?: Date;
  },
): Promise<boolean> {
  const reason = input.reason?.trim() ? input.reason.trim().slice(0, MAX_REASON_LENGTH) : null;
  const { rows } = await db.query<{ id: string | number }>(
    `insert into ask_naren.feedback (turn_id, user_id, rating, reason, created_at, updated_at)
     select q.id, $1, $4, $5, $6, $6
     from ask_naren.turns q
     join ask_naren.threads t on t.id = q.thread_id
     where t.id = $2 and t.user_id = $1 and t.deleted_at is null and q.position = $3
     on conflict (turn_id, user_id) do update set
       rating = excluded.rating,
       reason = case
         when excluded.reason is not null then excluded.reason
         when ask_naren.feedback.rating = excluded.rating then ask_naren.feedback.reason
         else null
       end,
       updated_at = excluded.updated_at
     returning id`,
    [input.userId, input.threadId, input.position, input.rating, reason, input.now ?? new Date()],
  );
  return rows.length > 0;
}
