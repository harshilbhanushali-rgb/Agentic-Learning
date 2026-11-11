import type { Db } from '../db';
import { type Role, deleteUserSessions } from './sessions';

/**
 * Users (ADR 0011, 0018, 0019): keyed on a `@joveo.com` email. Anyone with a verified Joveo
 * Google account may sign in, and their first sign-in adds them as a member (ADR 0019); an
 * admin can also add people ahead of time. They sign in with Google only; the admin CLI
 * (scripts/users.ts) and /admin both manage them through this module.
 */
export function normalizeEmail(raw: string): string {
  return raw.trim().toLowerCase();
}

export function isJoveoEmail(email: string): boolean {
  return /^[^\s@]+@joveo\.com$/.test(email);
}

/** A name for someone who joins by signing in: Google's, else made from the email
 *  ("priya.shah@joveo.com" -> "Priya Shah"). The column refuses an empty one. */
export function displayName(identity: { email: string; name?: string | null }): string {
  const given = identity.name?.trim().slice(0, 200);
  if (given) return given;
  const local = normalizeEmail(identity.email).split('@')[0];
  const words = local.split(/[._-]+/).filter(Boolean);
  return words.map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ') || local;
}

/**
 * The user a Google identity signs in as, or null (ADR 0011, "The Google Workspace swap";
 * ADR 0019).
 *
 * `identity` must already be checked as Google's own word about a verified @joveo.com
 * account (google.ts). Matching is on `sub` -- Google's stable id -- once it is known. The
 * first time, a user with that email is found and `sub` is saved onto it; if there is none,
 * one is created as a member (ADR 0019: any Joveo account may use the tool). Refused: a
 * disabled user, and an email already linked to a DIFFERENT Google identity.
 */
export async function authenticateGoogle(
  db: Db,
  identity: { sub: string; email: string; name?: string | null },
): Promise<{ id: number } | null> {
  const bySub = async () => {
    const { rows } = await db.query<{ id: number; disabled_at: Date | null }>(
      'select id, disabled_at from ask_naren.users where google_sub = $1',
      [identity.sub],
    );
    return rows[0] ? (rows[0].disabled_at === null ? { id: rows[0].id } : null) : undefined;
  };
  // One statement, so two first sign-ins racing for the same user cannot both link it.
  const link = async () => {
    const { rows } = await db.query<{ id: number }>(
      `update ask_naren.users set google_sub = $2
       where email = $1 and google_sub is null and disabled_at is null
       returning id`,
      [email, identity.sub],
    );
    return rows[0] ? { id: rows[0].id } : null;
  };
  const email = normalizeEmail(identity.email);

  const known = await bySub();
  if (known !== undefined) return known;
  const linked = await link();
  if (linked) return linked;

  // Nobody with this email yet: they join as a member. ON CONFLICT DO NOTHING leaves an
  // existing row -- disabled, or linked to someone else -- exactly as it was, still refused.
  await db.query(
    `insert into ask_naren.users (email, name) values ($1, $2) on conflict (email) do nothing`,
    [email, displayName(identity)],
  );
  // Linked now, unless a concurrent first sign-in by the same person got there first.
  return (await link()) ?? (await bySub()) ?? null;
}

export interface UserSummary {
  id: number;
  email: string;
  name: string;
  role: Role;
  /** Has signed in with Google at least once (their Google account is linked). */
  googleLinked: boolean;
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

export async function addUser(db: Db, input: { email: string; name: string }): Promise<number> {
  const email = normalizeEmail(input.email);
  if (!isJoveoEmail(email)) throw new UserError(`${email} is not a @joveo.com address.`);
  const name = input.name.trim();
  if (!name) throw new UserError('A user needs a name.');
  const existing = await db.query('select 1 from ask_naren.users where email = $1', [email]);
  if (existing.rows.length) throw new UserError(`${email} already exists.`);
  const { rows } = await db.query<{ id: number }>(
    `insert into ask_naren.users (email, name) values ($1, $2) returning id`,
    [email, name],
  );
  return rows[0].id;
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

export const ROLES: readonly Role[] = ['member', 'admin'];

/** ADR 0018. Takes effect on the user's next request: the role is read with the session. */
export async function setRole(db: Db, email: string, role: Role): Promise<void> {
  if (!ROLES.includes(role)) throw new UserError(`${role} is not a role. Use member or admin.`);
  const id = await idFor(db, email);
  await db.query('update ask_naren.users set role = $2 where id = $1', [id, role]);
}

export async function signOutEverywhere(db: Db, email: string): Promise<number> {
  return deleteUserSessions(db, await idFor(db, email));
}

export async function listUsers(db: Db): Promise<UserSummary[]> {
  const { rows } = await db.query<{
    id: number;
    email: string;
    name: string;
    role: Role;
    google_linked: boolean;
    disabled_at: Date | null;
    sessions: number;
  }>(
    `select u.id, u.email, u.name, u.role, u.google_sub is not null as google_linked, u.disabled_at,
            (select count(*)::int from ask_naren.sessions s where s.user_id = u.id) as sessions
     from ask_naren.users u
     order by u.email`,
  );
  return rows.map(r => ({
    id: r.id,
    email: r.email,
    name: r.name,
    role: r.role,
    googleLinked: r.google_linked,
    disabledAt: r.disabled_at,
    sessions: r.sessions,
  }));
}
