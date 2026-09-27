# Provisioning Ask Naren's database (issue #47, ADR 0012)

The Ask Naren tables live in the `ask_naren` schema of **Brain's Neon instance**. The app
connects as roles that can reach only that schema. Everything here runs as `neondb_owner`
over the **direct** endpoint (the host without `-pooler`). Every file is idempotent.

1. Apply `../migrations/*.sql` in order.
2. Apply `roles.sql`. It creates `ask_naren_app` and `ask_naren_admin` **with SQL**. **Never
   create these roles in the Neon Console, CLI or API.** Those join `neon_superuser`, which
   holds `pg_write_all_data` and can write Brain's `kb_pairs` whatever the grants say.
3. Set each role's password: `ALTER ROLE ask_naren_app PASSWORD '<generated>'`, and the same
   for admin. Neon accepts only plaintext here (sent over TLS). Generate at least 60 bits of
   entropy. Don't reuse the passwords, and don't paste them anywhere but the env file.
4. Apply `grants.sql`. **Re-run it after every new migration**: a new table has no grants
   until a line there adds them.
5. Put the connection strings in `frontend/.env.local` (gitignored). Both use the **pooled**
   host, with `sslmode=verify-full`:
   - `ASK_NAREN_DATABASE_URL` for `ask_naren_app` (the web app)
   - `ASK_NAREN_ADMIN_DATABASE_URL` for `ask_naren_admin` (`npm run users`)

On its first query the app checks its own role. It refuses to serve if the role could
reach Brain's pipeline (`src/server/privilege.ts`). `src/server/grants.test.ts` runs every
query the app and CLI make under these exact grants.

**Provisioned on 2026-09-28** (both roles verified over the pooler: least-privileged,
`public.kb_pairs` denied, app role cannot insert users). **No users seeded yet** — add them with
`npm run users -- add <email> <name>`.
