-- Ask Naren database roles (issue #47; decided in #38, ADR 0012).
--
-- CREATED WITH SQL, NEVER IN THE NEON CONSOLE. A Console/CLI/API role is added to
-- `neon_superuser`, which is a member of `pg_write_all_data` -- it could write Brain's
-- kb_pairs whatever this file grants. A role created here gets only what db/provision/
-- grants.sql gives it. The app's startup check (src/server/privilege.ts) refuses a role that
-- has more.
--
-- Run as neondb_owner over the DIRECT endpoint. Idempotent. Passwords are NOT set here, so
-- none is ever in this repository -- see db/provision/README.md. NOTE: Neon refuses a
-- pre-hashed SCRAM verifier ("Neon only supports being given plaintext passwords"), so psql's
-- \password does not work there; the password is sent in plaintext over TLS and stored as
-- SCRAM by Postgres.

do $$
begin
  if not exists (select from pg_roles where rolname = 'ask_naren_app') then
    create role ask_naren_app login nosuperuser nocreatedb nocreaterole nobypassrls noinherit
      connection limit 10;
  end if;
  if not exists (select from pg_roles where rolname = 'ask_naren_admin') then
    create role ask_naren_admin login nosuperuser nocreatedb nocreaterole nobypassrls noinherit
      connection limit 3;
  end if;
end
$$;
