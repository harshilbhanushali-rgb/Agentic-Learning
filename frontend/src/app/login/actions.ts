'use server';

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

import { db } from '@/server/db';
import { SESSION_COOKIE } from '@/server/auth/cookie';
import { deleteSession } from '@/server/auth/sessions';

/* Signing IN is Google's round trip (src/app/api/auth/google/, ADR 0018); there is no form. */

/** This browser only (ADR 0011). Signing out everywhere is the admin's job. */
export async function signOut(): Promise<void> {
  const token = cookies().get(SESSION_COOKIE)?.value;
  if (token) await deleteSession(db(), token);
  cookies().delete(SESSION_COOKIE);
  redirect('/login');
}
