import type { Db } from './db';

/**
 * Refuse to serve an over-privileged database role (issue #38, ADR 0012).
 *
 * "Ask Naren cannot write to Brain's pipeline" has to be a PERMISSION, and a permission can be
 * misconfigured silently: a role made in the Neon Console joins `neon_superuser`, which holds
 * `pg_write_all_data`, and every health check still passes. So the app asks Postgres what its
 * own role can do before the first query, and throws if the answer is "too much".
 *
 * It proves the role is NOT over-privileged. A MISSING grant needs no check -- it is already
 * loud, as "permission denied" on the query that needed it.
 */
export class PrivilegeError extends Error {}

const CHECK = `
  select (r.rolsuper or r.rolcreaterole or r.rolcreatedb or r.rolbypassrls) as elevated,
         exists (select 1 from pg_roles s
                 where s.rolname in ('neon_superuser', 'pg_read_all_data', 'pg_write_all_data')
                   and pg_has_role(current_user, s.oid, 'MEMBER')) as privileged_member,
         coalesce(has_table_privilege(to_regclass('public.kb_pairs'), 'SELECT'), false)
           as reads_kb_pairs,
         has_database_privilege(current_database(), 'CREATE') as can_create_schema,
         current_user as role
  from pg_roles r where r.rolname = current_user`;

export async function assertLeastPrivilege(db: Db): Promise<void> {
  const { rows } = await db.query<{
    elevated: boolean;
    privileged_member: boolean;
    reads_kb_pairs: boolean;
    can_create_schema: boolean;
    role: string;
  }>(CHECK);
  const r = rows[0];
  if (!r) throw new PrivilegeError('Could not read the current role from pg_roles.');
  const problems = [
    r.elevated && 'is a superuser or can create roles/databases/bypass RLS',
    r.privileged_member && 'is a member of neon_superuser / pg_read_all_data / pg_write_all_data',
    r.reads_kb_pairs && "can read Brain's public.kb_pairs",
    r.can_create_schema && 'can create schemas in the database',
  ].filter(Boolean);
  if (problems.length) {
    const message =
      `[ask-naren] Refusing to use database role "${r.role}": it ${problems.join('; ')}. ` +
      'The app must connect as a SQL-created role granted only the ask_naren schema -- see ' +
      'db/provision/ and ADR 0012. (Local development only: ASK_NAREN_SKIP_PRIVILEGE_CHECK=1.)';
    console.error(message);
    throw new PrivilegeError(message);
  }
}
