import { AdminPanel, type AdminUserRow } from '@/components/admin/AdminPanel';
import { requireAdmin } from '@/server/auth/admins';
import { listUsers } from '@/server/auth/users';
import { db } from '@/server/db';

/**
 * Manage who can sign in (ADR 0016): add a user, reset a password, disable or re-enable,
 * and see everyone. Admins are the emails in ASK_NAREN_ADMIN_EMAILS; anyone else gets a
 * 404. Uses the app's own database login, which can manage users (ADR 0016).
 */
export default async function AdminPage() {
  const me = await requireAdmin();

  let users: AdminUserRow[] | null = null;
  try {
    users = (await listUsers(db())).map(u => ({
      email: u.email,
      name: u.name,
      hasPassword: u.hasPassword,
      disabled: u.disabledAt !== null,
      sessions: u.sessions,
    }));
  } catch (cause) {
    console.error('[ask-naren] admin page could not list users:', cause);
  }

  return <AdminPanel me={me.email} users={users} />;
}
