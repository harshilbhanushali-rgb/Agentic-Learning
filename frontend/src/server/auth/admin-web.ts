import { randomBytes } from 'node:crypto';

import type { Db } from '../db';
import { MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH } from './password';
import { UserError, addUser, disableUser, enableUser, normalizeEmail, setPassword } from './users';

/**
 * What the /admin page's forms do (ADR 0016), kept out of the server actions so it is tested
 * against real Postgres. The same user functions the CLI uses: one set of rules, two doors.
 *
 * Every result is a sentence for the admin. A generated password is returned once, to be
 * shown once and handed over directly -- it is never stored anywhere but as its hash.
 */
import { type AdminResult } from './admin-web-result';

export { type AdminResult, EMPTY_RESULT } from './admin-web-result';

const fail = (error: string): AdminResult => ({ ok: null, error, password: null });

/** A store fault, never phrased as the admin's mistake (issue #40's rule, applied here). */
export const UNAVAILABLE =
  'Could not reach the user store just now. Nothing was changed — try again in a moment.';

export function generatePassword(): string {
  return randomBytes(18).toString('base64url');
}

/** The typed password, or a generated one when the field was left empty. */
function choosePassword(typed: string): { password: string; generated: boolean } | string {
  if (!typed) return { password: generatePassword(), generated: true };
  if (typed.length < MIN_PASSWORD_LENGTH || typed.length > MAX_PASSWORD_LENGTH) {
    return `A password must be at least ${MIN_PASSWORD_LENGTH} characters. Leave it empty to generate one.`;
  }
  return { password: typed, generated: false };
}

async function run(work: () => Promise<AdminResult>): Promise<AdminResult> {
  try {
    return await work();
  } catch (cause) {
    if (cause instanceof UserError) return fail(cause.message);
    console.error('[ask-naren] admin action failed on the store:', cause);
    return fail(UNAVAILABLE);
  }
}

export function webAddUser(
  db: Db,
  input: { email: string; name: string; password: string },
): Promise<AdminResult> {
  return run(async () => {
    const chosen = choosePassword(input.password);
    if (typeof chosen === 'string') return fail(chosen);
    await addUser(db, { email: input.email, name: input.name, password: chosen.password });
    const email = normalizeEmail(input.email);
    return {
      ok: chosen.generated
        ? `Added ${email}. Copy the password below now — it is shown only once.`
        : `Added ${email} with the password you typed.`,
      error: null,
      password: chosen.generated ? chosen.password : null,
    };
  });
}

export function webResetPassword(
  db: Db,
  input: { email: string; password: string },
): Promise<AdminResult> {
  return run(async () => {
    const chosen = choosePassword(input.password);
    if (typeof chosen === 'string') return fail(chosen);
    const ended = await setPassword(db, input.email, chosen.password);
    const signedOut = ended === 1 ? '1 browser was signed out' : `${ended} browsers were signed out`;
    return {
      ok: `Password reset for ${normalizeEmail(input.email)}; ${signedOut}.${chosen.generated ? ' Copy the new password below now — it is shown only once.' : ''}`,
      error: null,
      password: chosen.generated ? chosen.password : null,
    };
  });
}

export function webSetDisabled(
  db: Db,
  actorEmail: string,
  input: { email: string; disable: boolean },
): Promise<AdminResult> {
  return run(async () => {
    const email = normalizeEmail(input.email);
    // An admin who disables themselves is locked out of the page that would undo it.
    if (input.disable && email === normalizeEmail(actorEmail)) {
      return fail('You can’t disable your own account from here.');
    }
    if (input.disable) {
      await disableUser(db, email);
      return { ok: `Disabled ${email} and signed them out everywhere.`, error: null, password: null };
    }
    await enableUser(db, email);
    return { ok: `Re-enabled ${email}. They can sign in again.`, error: null, password: null };
  });
}
