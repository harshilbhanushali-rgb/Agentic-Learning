import { normalizeEmail } from './users';

/**
 * Who may use the /admin page (ADR 0016): the emails in `ASK_NAREN_ADMIN_EMAILS`,
 * comma-separated. Not a column on `users`, so being an admin cannot be granted from the
 * page itself, and an empty or unset list means nobody -- the page then exists for no one.
 */
export function adminEmails(raw: string | undefined = process.env.ASK_NAREN_ADMIN_EMAILS): Set<string> {
  return new Set(
    (raw ?? '')
      .split(',')
      .map(e => normalizeEmail(e))
      .filter(e => e.length > 0),
  );
}

export function isAdmin(email: string, raw?: string): boolean {
  return adminEmails(raw).has(normalizeEmail(email));
}
