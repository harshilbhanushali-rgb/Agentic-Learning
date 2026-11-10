import type { Db } from '../db';
import { dummyHash, hashPassword, verifyPassword } from './password';
import { deleteUserSessions } from './sessions';

/**
 * Users (ADR 0011): admin-seeded, keyed on a `@joveo.com` email, no self-signup.
 *
 * The admin CLI (scripts/users.ts) and the sign-in form both come through this module, so a
 * password the admin sets is hashed by exactly the code that later verifies it.
 */
export function normalizeEmail(raw: string): string {
  return raw.trim().toLowerCase();
}

export function isJoveoEmail(email: string): boolean {
  return /^[^\s@]+@joveo\.com$/.test(email);
}

/**
 * The user this email and password sign in as, or null.
 *
 * EVERY REFUSAL LOOKS THE SAME -- unknown email, wrong password, disabled user, a user with
 * no password -- and does the same scrypt work, so neither the answer nor its timing says
 * whether an email belongs to someone. There is no throttling (ADR 0011: the app relies on a
 * network boundary), which makes this the only thing standing between a guessable email
 * format and a list of who uses the tool.
 */
export async function authenticate(
  db: Db,
  email: string,
  password: string,
): Promise<{ id: number } | null> {
  const { rows } = await db.query<{
    id: number;
    password_hash: string | null;
    disabled_at: Date | null;
  }>('select id, password_hash, disabled_at from ask_naren.users where email = $1', [
    normalizeEmail(email),
  ]);
  const row = rows[0];
  const ok = await verifyPassword(password, row?.password_hash ?? (await dummyHash()));
  if (!row || !row.password_hash || !ok || row.disabled_at !== null) return null;
  return { id: row.id };
}

export interface UserSummary {
  id: number;
  email: string;
  name: string;
  hasPassword: boolean;
  disabledAt: Date | null;
  sessions: number;
}

export class UserError extends Error {}

async function idFor(db: Db, email: string): Promise<number> {
  const { rows } = await db.query<{ id: number }>(
    'select id from ask_naren.users where email = $1',
    [normalizeEmail(email)],
  );
  if (!rows[0]) throw new UserError(`No user with email ${normalizeEmail(email)}.`);
  return rows[0].id;
}

export async function addUser(
  db: Db,
  input: { email: string; name: string; password: string },
): Promise<number> {
  const email = normalizeEmail(input.email);
  if (!isJoveoEmail(email)) throw new UserError(`${email} is not a @joveo.com address.`);
  const name = input.name.trim();
  if (!name) throw new UserError('A user needs a name.');
  const existing = await db.query('select 1 from ask_naren.users where email = $1', [email]);
  if (existing.rows.length) throw new UserError(`${email} already exists.`);
  const { rows } = await db.query<{ id: number }>(
    `insert into ask_naren.users (email, name, password_hash) values ($1, $2, $3) returning id`,
    [email, name, await hashPassword(input.password)],
  );
  return rows[0].id;
}

/** An admin reset. Ends every session the user has, so an old password's sign-ins do not
 *  outlive it. */
export async function setPassword(db: Db, email: string, password: string): Promise<number> {
  const id = await idFor(db, email);
  await db.query('update ask_naren.users set password_hash = $2 where id = $1', [
    id,
    await hashPassword(password),
  ]);
  return deleteUserSessions(db, id);
}

/**
 * Offboarding: disabled AND signed out everywhere. Ending sessions alone would let them sign
 * straight back in; deleting the user would take their threads with it.
 */
export async function disableUser(db: Db, email: string): Promise<number> {
  const id = await idFor(db, email);
  await db.query(
    'update ask_naren.users set disabled_at = coalesce(disabled_at, now()) where id = $1',
    [id],
  );
  return deleteUserSessions(db, id);
}

export async function enableUser(db: Db, email: string): Promise<void> {
  const id = await idFor(db, email);
  await db.query('update ask_naren.users set disabled_at = null where id = $1', [id]);
}

export async function signOutEverywhere(db: Db, email: string): Promise<number> {
  return deleteUserSessions(db, await idFor(db, email));
}

export async function listUsers(db: Db): Promise<UserSummary[]> {
  const { rows } = await db.query<{
    id: number;
    email: string;
    name: string;
    has_password: boolean;
    disabled_at: Date | null;
    sessions: number;
  }>(
    `select u.id, u.email, u.name, u.password_hash is not null as has_password, u.disabled_at,
            (select count(*)::int from ask_naren.sessions s where s.user_id = u.id) as sessions
     from ask_naren.users u
     order by u.email`,
  );
  return rows.map(r => ({
    id: r.id,
    email: r.email,
    name: r.name,
    hasPassword: r.has_password,
    disabledAt: r.disabled_at,
    sessions: r.sessions,
  }));
}
