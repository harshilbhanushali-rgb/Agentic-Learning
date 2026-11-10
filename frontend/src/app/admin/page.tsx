import { AdminPanel, type AdminUserRow } from '@/components/admin/AdminPanel';
import { isFixedAdmin, requireAdmin } from '@/server/auth/admins';
import { listUsers } from '@/server/auth/users';
import { db } from '@/server/db';

/**
 * Manage who can sign in (ADR 0016, 0018): add a user, set their role, disable or re-enable,
 * and see everyone. Admins are users with the admin role, plus the built-in admin; anyone
 * else gets a 404. Uses the app's own database login, which can manage users.
 */
export default async function AdminPage() {
  const me = await requireAdmin();

  let users: AdminUserRow[] | null = null;
  try {
    users = (await listUsers(db())).map(u => ({
      email: u.email,
      name: u.name,
      role: u.role,
      fixedAdmin: isFixedAdmin(u.email),
      googleLinked: u.googleLinked,
      disabled: u.disabledAt !== null,
      sessions: u.sessions,
    }));
  } catch (cause) {
    console.error('[ask-naren] admin page could not list users:', cause);
  }

  return <AdminPanel me={me.email} users={users} />;
}
