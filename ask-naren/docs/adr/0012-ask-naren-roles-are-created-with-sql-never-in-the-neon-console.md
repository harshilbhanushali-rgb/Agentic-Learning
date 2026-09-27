# Ask Naren's database roles are created with SQL, never in the Neon Console

Ask Naren's web app writes to Brain's Neon instance: users, sessions, threads and turns, in schema `ask_naren` (#37, #44). What makes the tool safe is that it **cannot write to Brain's pipeline**. Until now nothing enforced that except the Python service switching itself to read-only, on credentials that could write everything. Adding a writing app makes it a real permission question (#38).

The obvious way to make a least-privileged role on Neon is the Console. **We decided never to use it.** The app's roles are created with SQL `CREATE ROLE` (`frontend/db/provision/roles.sql`). Someone tidying up is likely to "fix" that, so this records why.

## Why not the Console

A read-only catalog probe of the instance on 2026-09-28 found the following:
- Neon adds every role created in the Console, CLI or API to `neon_superuser`.
- `neon_superuser` is a member of **`pg_read_all_data` and `pg_write_all_data`**.
- `has_table_privilege('neon_superuser', 'public.kb_pairs', 'INSERT')` is **true**.

So a Console-made role can write `kb_pairs` whatever `ask_naren` grants it. The grants would isolate nothing, and every health check would still pass. A role created with SQL gets only the Postgres defaults plus what `grants.sql` gives it.

## What was decided with it

- **Two roles, not one.**
  - `ask_naren_app` (the web app) can read users but never create one or set a password.
  - `ask_naren_admin` (the users CLI) can do that, and can't read threads.
  - One shared role would let a compromised web app mint itself a permanent sign-in.
- **The grants are explicit and column-level**, with no `ALTER DEFAULT PRIVILEGES`, so a new table has no access until `grants.sql` says so.
  - Turns are append-only for the app.
  - Threads are soft-deleted, so the app cannot hard-delete them.
  - Nothing is granted on `public`.
  - `src/server/grants.test.ts` runs every query the app and CLI make under these grants. It fails on a grant that is missing and on one that is too wide.
- **The app refuses to serve an over-privileged role.** On first use it asks Postgres whether its role is a superuser, can create roles or databases, can bypass RLS, is a member of `neon_superuser` / `pg_read_all_data` / `pg_write_all_data`, can read `public.kb_pairs`, or can create schemas. It throws if any answer is yes (`src/server/privilege.ts`).
  - A missing grant needs no such check: it is already loud, as "permission denied".
- **`neondb_owner` owns the schema** and runs migrations over the direct endpoint. There is no separate NOLOGIN owner, because switching to one needs `SET ROLE`, which is session state and unsafe on Neon's pooler.
- **The app uses the pooled endpoint.** Its own role gets its own PgBouncer pool, never shared with the backends where the service applies `SET SESSION default_transaction_read_only`, which has leaked before (Brain/docs/GOTCHAS.md).

## Consequences

- **Neon refuses a pre-hashed password** ("Neon only supports being given plaintext passwords"), so psql's `\password` does not work. Passwords are set in plaintext over TLS (`db/provision/README.md`).
- **The Python service is still on `neondb_owner`** with its self-applied read-only setting. Giving it a real read-only role on the same principle changes Brain, so it is its own effort (#48).
