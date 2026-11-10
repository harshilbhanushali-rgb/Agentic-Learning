import { notFound, redirect } from 'next/navigation';

import { isAdmin } from './admin-list';
import { getCurrentUser } from './current-user';
import type { SessionUser } from './sessions';

export { isAdmin, isFixedAdmin } from './admin-list';

/**
 * For the admin page (ADR 0016): the signed-in admin, a redirect to sign in, or a 404 for
 * anyone else -- a 404 rather than "forbidden", so the page does not announce that it exists.
 */
export async function requireAdmin(path = '/admin'): Promise<SessionUser> {
  const user = await getCurrentUser();
  if (!user) redirect(`/login?next=${encodeURIComponent(path)}`);
  if (!isAdmin(user)) notFound();
  return user;
}
