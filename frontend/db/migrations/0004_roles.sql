-- Ask Naren roles (ADR 0018): who may open /admin is a column, set from /admin itself.
--
-- 'member' uses Ask Naren; 'admin' also manages users. Everyone existing becomes a member;
-- the one built-in admin (src/server/auth/admin-list.ts) is an admin whatever this says, so
-- the page is never left without someone who can open it.
--
-- IDEMPOTENT, applied by hand as the owner like every migration here; re-run
-- db/provision/grants.sql after it.

alter table ask_naren.users
  add column if not exists role text not null default 'member'
  constraint users_role_check check (role in ('member', 'admin'));
