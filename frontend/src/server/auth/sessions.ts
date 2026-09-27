import { createHash, randomBytes } from 'node:crypto';

import type { Db } from '../db';

/**
 * Sessions (ADR 0011): an opaque random token in a cookie, a row we own behind it.
 *
 * A ROW RATHER THAN A SIGNED COOKIE because signing out has to take effect on the server
 * immediately -- offboarding someone who has left is an admin deleting rows, and a
 * self-contained cookie cannot be cut off before it expires. See the ADR for the options
 * weighed.
 *
 * `now` is a parameter everywhere so the lifetime rules are testable without waiting.
 */
const DAY_MS = 24 * 60 * 60 * 1000;
/** Unused for this long, a session ends. */
export const IDLE_MS = 14 * DAY_MS;
/** However much it is used, a session ends this long after sign-in. */
export const ABSOLUTE_MS = 30 * DAY_MS;
/** `last_seen_at` is written at most this often, so a busy page is not a write per request. */
export const TOUCH_INTERVAL_MS = 60 * 60 * 1000;

const TOKEN_BYTES = 32;
/** base64url of 32 bytes. Anything else is not a token this code issued. */
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;

export interface SessionUser {
  id: number;
  email: string;
  name: string;
}

/** What the table stores in place of the token: reading the table must not yield a sign-in. */
export function hashToken(token: string): string {
  return createHash('sha256').update(token).digest('hex');
}

export async function createSession(
  db: Db,
  userId: number,
  now: Date = new Date(),
): Promise<{ token: string; expiresAt: Date }> {
  const token = randomBytes(TOKEN_BYTES).toString('base64url');
  const expiresAt = new Date(now.getTime() + ABSOLUTE_MS);
  await db.query(
    `insert into ask_naren.sessions (token_hash, user_id, created_at, last_seen_at, expires_at)
     values ($1, $2, $3, $3, $4)`,
    [hashToken(token), userId, now, expiresAt],
  );
  // Opportunistic cleanup of this user's dead sessions. An expired cookie is usually never
  // presented again, so without this its row would stay forever.
  await db.query(
    `delete from ask_naren.sessions
     where user_id = $1 and (expires_at <= $2 or last_seen_at <= $3)`,
    [userId, now, new Date(now.getTime() - IDLE_MS)],
  );
  return { token, expiresAt };
}

/**
 * The signed-in user for a cookie's token, or null.
 *
 * NULL MEANS SIGNED OUT, AND ONLY THAT. A database fault throws instead, so a store outage
 * surfaces as an error rather than masquerading as an expired session and sending a CSM to
 * a sign-in page that cannot work either (issue #40 decides what they read).
 */
export async function validateSession(
  db: Db,
  token: string | undefined,
  now: Date = new Date(),
): Promise<SessionUser | null> {
  if (!token || !TOKEN_PATTERN.test(token)) return null;
  const tokenHash = hashToken(token);
  const { rows } = await db.query<{
    user_id: number;
    email: string;
    name: string;
    disabled_at: Date | null;
    last_seen_at: Date;
    expires_at: Date;
  }>(
    `select s.user_id, u.email, u.name, u.disabled_at, s.last_seen_at, s.expires_at
     from ask_naren.sessions s
     join ask_naren.users u on u.id = s.user_id
     where s.token_hash = $1`,
    [tokenHash],
  );
  const row = rows[0];
  if (!row) return null;

  const t = now.getTime();
  const lastSeen = new Date(row.last_seen_at).getTime();
  const dead =
    row.disabled_at !== null ||
    new Date(row.expires_at).getTime() <= t ||
    lastSeen + IDLE_MS <= t;
  if (dead) {
    await db.query('delete from ask_naren.sessions where token_hash = $1', [tokenHash]);
    return null;
  }

  if (t - lastSeen >= TOUCH_INTERVAL_MS) {
    await db.query('update ask_naren.sessions set last_seen_at = $2 where token_hash = $1', [
      tokenHash,
      now,
    ]);
  }
  return { id: row.user_id, email: row.email, name: row.name };
}

/** Sign out: this browser only (ADR 0011). */
export async function deleteSession(db: Db, token: string): Promise<void> {
  await db.query('delete from ask_naren.sessions where token_hash = $1', [hashToken(token)]);
}

/** Every browser a user is signed in on -- a password change, or offboarding. */
export async function deleteUserSessions(db: Db, userId: number): Promise<number> {
  const { rows } = await db.query<{ n: number }>(
    `with gone as (delete from ask_naren.sessions where user_id = $1 returning 1)
     select count(*)::int as n from gone`,
    [userId],
  );
  return rows[0]?.n ?? 0;
}
