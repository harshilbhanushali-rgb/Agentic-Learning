import type { Role } from './sessions';
import { normalizeEmail } from './users';

/**
 * Who may use the /admin page (ADR 0018): anyone whose role is `admin`, set on /admin itself,
 * plus the built-in admin below.
 *
 * BUILT IN, AND NOT DEMOTABLE FROM THE PAGE, so /admin can never be left with nobody able to
 * open it (operator's call, 2026-11-10). Changing who is built in is a code change and a
 * deploy, on purpose. The old ASK_NAREN_ADMIN_EMAILS setting is no longer read.
 */
export const BUILT_IN_ADMINS: readonly string[] = ['harshil.bhanushali@joveo.com'];

export function isFixedAdmin(email: string): boolean {
  return BUILT_IN_ADMINS.includes(normalizeEmail(email));
}

export function isAdmin(user: { email: string; role: Role }): boolean {
  return user.role === 'admin' || isFixedAdmin(user.email);
}
