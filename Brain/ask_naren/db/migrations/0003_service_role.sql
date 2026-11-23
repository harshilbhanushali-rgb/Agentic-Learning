-- 0003: ask_naren_service, the login the Ask Naren Python service uses on RDS.
--
-- SQL-CREATED, NEVER IN THE AWS CONSOLE, and never the master user: the master is a member
-- of rds_superuser and can write every table here, the other application's included. This
-- role can read six Brain tables (grants.sql) and nothing else, and every transaction it
-- opens is read-only.
--
-- The password is NOT set here, so none is ever in this repository. After this migration:
--     ALTER ROLE ask_naren_service PASSWORD '<generated>';
-- See ask_naren/db/README.md.

do $$
begin
  if not exists (select from pg_roles where rolname = 'ask_naren_service') then
    create role ask_naren_service login nosuperuser nocreatedb nocreaterole nobypassrls
      noinherit connection limit 10;
  end if;
end $$;

-- Unqualified table names in shared/storage.py resolve to `brain`; `vector` and `<=>`
-- resolve to `extensions`. `public` (the other application) is not on the path at all.
alter role ask_naren_service set search_path = brain, extensions;
alter role ask_naren_service set default_transaction_read_only = on;
-- The startup read is a handful of whole-table selects; a search is one exact scan.
alter role ask_naren_service set statement_timeout = '30s';
