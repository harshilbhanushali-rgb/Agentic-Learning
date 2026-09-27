'use server';

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

import { db } from '@/server/db';
import { SESSION_COOKIE, safeNext, sessionCookieOptions } from '@/server/auth/cookie';
import { createSession, deleteSession } from '@/server/auth/sessions';
import { authenticate } from '@/server/auth/users';
import { MAX_PASSWORD_LENGTH } from '@/server/auth/password';

export type SignInState = { error: string | null };

/** One sentence for every refusal, so the form does not say which half was wrong. */
const REFUSED = 'That email and password do not match a Joveo user.';

export async function signIn(_prev: SignInState, form: FormData): Promise<SignInState> {
  const email = String(form.get('email') ?? '');
  const password = String(form.get('password') ?? '');
  if (!email.trim() || !password) return { error: 'Enter your email and password.' };
  if (password.length > MAX_PASSWORD_LENGTH) return { error: REFUSED };

  const user = await authenticate(db(), email, password);
  if (!user) return { error: REFUSED };

  const { token, expiresAt } = await createSession(db(), user.id);
  cookies().set(SESSION_COOKIE, token, sessionCookieOptions(expiresAt));
  // Outside any try: `redirect` works by throwing.
  redirect(safeNext(form.get('next')));
}

/** This browser only (ADR 0011). Signing out everywhere is the admin CLI's job. */
export async function signOut(): Promise<void> {
  const token = cookies().get(SESSION_COOKIE)?.value;
  if (token) await deleteSession(db(), token);
  cookies().delete(SESSION_COOKIE);
  redirect('/login');
}
