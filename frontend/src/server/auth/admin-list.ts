import { normalizeEmail } from './users';

/**
 * Who may use the /admin page (ADR 0016): the built-in admins below, plus any emails in
 * `ASK_NAREN_ADMIN_EMAILS` (comma-separated, optional). Neither is a column on `users`, so
 * being an admin cannot be granted from the page itself.
 *
 * BUILT IN so the page works on a deployment with no extra setting (operator's call,
 * 2026-11-10). Changing who is built in is a code change and a deploy, on purpose.
 */
export const BUILT_IN_ADMINS: readonly string[] = ['harshil.bhanushali@joveo.com'];

export function adminEmails(raw: string | undefined = process.env.ASK_NAREN_ADMIN_EMAILS): Set<string> {
  return new Set(
    [...BUILT_IN_ADMINS, ...(raw ?? '').split(',')]
      .map(e => normalizeEmail(e))
      .filter(e => e.length > 0),
  );
}

export function isAdmin(email: string, raw?: string): boolean {
  return adminEmails(raw).has(normalizeEmail(email));
}
