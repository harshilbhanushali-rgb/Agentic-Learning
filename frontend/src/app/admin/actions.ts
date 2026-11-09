'use server';

import { revalidatePath } from 'next/cache';

import { type Db, db as appDb } from '@/server/db';
import { isAdmin } from '@/server/auth/admin-list';
import {
  type AdminResult,
  UNAVAILABLE,
  webAddUser,
  webResetPassword,
  webSetDisabled,
} from '@/server/auth/admin-web';
import { getCurrentUser } from '@/server/auth/current-user';
import type { SessionUser } from '@/server/auth/sessions';

/**
 * The /admin page's forms (ADR 0016). A server action is a public endpoint whatever page it
 * was written for, so EVERY action checks the caller is a signed-in admin itself -- the
 * page's own check does not protect these.
 */

const NOT_ALLOWED: AdminResult = { ok: null, error: 'Only an admin can do that.', password: null };
const DOWN: AdminResult = { ok: null, error: UNAVAILABLE, password: null };

async function asAdmin(work: (db: Db, me: SessionUser) => Promise<AdminResult>): Promise<AdminResult> {
  let me: SessionUser | null;
  try {
    me = await getCurrentUser();
  } catch (cause) {
    // A store fault is never "signed out" (issue #40).
    console.error('[ask-naren] admin action could not read the session:', cause);
    return DOWN;
  }
  if (!me || !isAdmin(me.email)) return NOT_ALLOWED;

  let db: Db;
  try {
    db = appDb();
  } catch (cause) {
    // ASK_NAREN_DATABASE_URL unset on this deployment.
    console.error('[ask-naren] admin action has no database:', cause);
    return DOWN;
  }
  const result = await work(db, me);
  if (!result.error) revalidatePath('/admin');
  return result;
}

const field = (form: FormData, name: string) => String(form.get(name) ?? '');

export async function addUserAction(_prev: AdminResult, form: FormData): Promise<AdminResult> {
  return asAdmin(db =>
    webAddUser(db, {
      email: field(form, 'email'),
      name: field(form, 'name'),
      password: field(form, 'password'),
    }),
  );
}

export async function resetPasswordAction(_prev: AdminResult, form: FormData): Promise<AdminResult> {
  return asAdmin(db =>
    webResetPassword(db, { email: field(form, 'email'), password: field(form, 'password') }),
  );
}

export async function setDisabledAction(_prev: AdminResult, form: FormData): Promise<AdminResult> {
  return asAdmin((db, me) =>
    webSetDisabled(db, me.email, {
      email: field(form, 'email'),
      disable: field(form, 'disable') === 'true',
    }),
  );
}
