import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { cache } from 'react';

import { db } from '../db';
import { SESSION_COOKIE } from './cookie';
import { type SessionUser, validateSession } from './sessions';

/**
 * THE ONE PLACE A SERVER COMPONENT, ROUTE HANDLER OR SERVER ACTION LEARNS WHO IS SIGNED IN
 * (issue #42's constraint). Not `middleware`: it runs on prefetches too and on Next 14
 * cannot reach a database. Not a layout: layouts do not re-render on navigation and do not
 * stop a child segment rendering. Every page and server action that needs a user asks here;
 * the proxy route, which has the request in hand, calls `validateSession` with the same
 * cookie directly -- the one rule, reached two ways.
 *
 * `cache` makes it one database read per request however many components ask.
 */
export const getCurrentUser = cache(async (): Promise<SessionUser | null> => {
  // The cookie first: reading it is what marks the page dynamic, and with no cookie there is
  // nobody to look up, so a visitor who never signed in costs no database round trip.
  const token = cookies().get(SESSION_COOKIE)?.value;
  if (!token) return null;
  return validateSession(db(), token);
});

/** For pages: the signed-in user, or a redirect to sign in that comes back to `returnTo`. */
export async function requireUser(returnTo: string): Promise<SessionUser> {
  const user = await getCurrentUser();
  if (!user) redirect(`/login?next=${encodeURIComponent(returnTo)}`);
  return user;
}
