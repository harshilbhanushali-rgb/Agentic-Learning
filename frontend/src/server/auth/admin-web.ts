import type { Db } from '../db';
import { isFixedAdmin } from './admin-list';
import type { Role } from './sessions';
import { UserError, addUser, disableUser, enableUser, normalizeEmail, setRole } from './users';

/**
 * What the /admin page's forms do (ADR 0016, 0018), kept out of the server actions so it is
 * tested against real Postgres. The same user functions the CLI uses: one set of rules, two
 * doors. Every result is a sentence for the admin.
 */
import { type AdminResult } from './admin-web-result';

export { type AdminResult, EMPTY_RESULT } from './admin-web-result';

const fail = (error: string): AdminResult => ({ ok: null, error });
const done = (ok: string): AdminResult => ({ ok, error: null });

/** A store fault, never phrased as the admin's mistake (issue #40's rule, applied here). */
export const UNAVAILABLE =
  'Could not reach the user store just now. Nothing was changed — try again in a moment.';

async function run(work: () => Promise<AdminResult>): Promise<AdminResult> {
  try {
    return await work();
  } catch (cause) {
    if (cause instanceof UserError) return fail(cause.message);
    console.error('[ask-naren] admin action failed on the store:', cause);
    return fail(UNAVAILABLE);
  }
}

/** A new member. There is nothing to hand over: they sign in with their Google account. */
export function webAddUser(db: Db, input: { email: string; name: string }): Promise<AdminResult> {
  return run(async () => {
    await addUser(db, input);
    return done(`Added ${normalizeEmail(input.email)}. They can sign in with Google now.`);
  });
}

/**
 * Two people's access the page never changes, so /admin can never be left without someone
 * who can open it: the admin doing it (who would lock themselves out), and the built-in admin.
 */
function protectedTarget(actorEmail: string, email: string, ownRefusal: string): string | null {
  if (email === normalizeEmail(actorEmail)) return ownRefusal;
  if (isFixedAdmin(email)) return `${email} is always an admin; that can’t be changed from here.`;
  return null;
}

export function webSetRole(
  db: Db,
  actorEmail: string,
  input: { email: string; role: string },
): Promise<AdminResult> {
  return run(async () => {
    const email = normalizeEmail(input.email);
    const refused = protectedTarget(actorEmail, email, 'You can’t change your own role from here.');
    if (refused) return fail(refused);
    await setRole(db, email, input.role as Role);
    return done(`${email} is now ${input.role === 'admin' ? 'an admin' : 'a member'}.`);
  });
}

export function webSetDisabled(
  db: Db,
  actorEmail: string,
  input: { email: string; disable: boolean },
): Promise<AdminResult> {
  return run(async () => {
    const email = normalizeEmail(input.email);
    if (input.disable) {
      const refused = protectedTarget(actorEmail, email, 'You can’t disable your own account from here.');
      if (refused) return fail(refused);
      await disableUser(db, email);
      return done(`Disabled ${email} and signed them out everywhere.`);
    }
    await enableUser(db, email);
    return done(`Re-enabled ${email}. They can sign in again.`);
  });
}
