-- Ask Naren sign-in: users and sessions (issue #44, ADR 0011).
--
-- IN ITS OWN SCHEMA, `ask_naren`, because these tables live in Brain's Neon instance next to
-- Brain's own tables in `public`. A schema is what lets the app's role be granted this and
-- nothing else (issue #38) -- the property Ask Naren is built around is that it cannot write
-- to Brain's pipeline.
--
-- IDEMPOTENT, so applying it twice is harmless. It is applied by whoever provisions the
-- database, as an owner role, never by the app at startup: the app's own role should not
-- hold DDL at all.
--
--   psql "$OWNER_DATABASE_URL" -f db/migrations/0001_users_and_sessions.sql

create schema if not exists ask_naren;

-- A person who can sign in. Not called `accounts`: that word means a Joveo client in this
-- codebase (ask-naren/CONTEXT.md, "User").
create table if not exists ask_naren.users (
  id            integer generated always as identity primary key,
  -- Stored lower-case so lookup is exact; the app normalises before it queries.
  email         text not null unique
                check (email = lower(email) and email like '%@joveo.com'),
  name          text not null check (length(btrim(name)) > 0),
  -- NULLABLE FROM DAY ONE. At the Google Workspace cutover password sign-in is switched off
  -- and hashes are cleared; a null here means "cannot sign in with a password".
  password_hash text,
  -- Filled at a user's first Google sign-in, then the match key from then on (ADR 0011).
  google_sub    text unique,
  created_at    timestamptz not null default now(),
  -- Offboarding. A disabled user cannot sign in, and is kept rather than deleted so their
  -- threads and analytics rows survive them.
  disabled_at   timestamptz
);

-- One signed-in browser. The cookie carries a random token; only its SHA-256 is stored, so
-- reading this table does not hand anyone a live sign-in.
create table if not exists ask_naren.sessions (
  token_hash    text primary key check (token_hash ~ '^[0-9a-f]{64}$'),
  user_id       integer not null references ask_naren.users (id) on delete cascade,
  created_at    timestamptz not null,
  -- Moves forward as the session is used: the 14-day idle limit counts from here.
  last_seen_at  timestamptz not null,
  -- Fixed at creation: the 30-day absolute limit.
  expires_at    timestamptz not null
);

create index if not exists sessions_user_id_idx on ask_naren.sessions (user_id);
