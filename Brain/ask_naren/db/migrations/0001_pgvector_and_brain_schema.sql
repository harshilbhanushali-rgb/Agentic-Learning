-- 0001: pgvector, and the schema Brain's tables live in on RDS.
--
-- THE DATABASE IS SHARED. On RDS `public` already holds another application's tables
-- (users, modules, assessment_*), so nothing of ours goes there: Brain's tables live in
-- `brain`, Ask Naren's sign-in tables in `ask_naren` (frontend/db/migrations), and pgvector
-- in `extensions`, so its type and operators are reachable without putting `public` on any
-- role's search_path.
--
-- Run as the RDS master user (a member of rds_superuser, which CREATE EXTENSION needs) by
-- ask_naren/db/migrate.py. Idempotent.

create schema if not exists extensions;
create extension if not exists vector with schema extensions;

-- `if not exists` would silently accept a pgvector someone installed into `public` earlier,
-- and every role here resolves `vector` and `<=>` through `extensions`. Refuse instead.
do $$
declare where_installed text;
begin
  select n.nspname into where_installed
  from pg_extension e join pg_namespace n on n.oid = e.extnamespace
  where e.extname = 'vector';
  if where_installed <> 'extensions' then
    raise exception 'pgvector is installed in schema %, expected extensions', where_installed;
  end if;
end $$;

create schema if not exists brain;
