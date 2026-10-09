-- Ask Naren grants (issue #47; decided in #38, ADR 0012). Run after every migration, as
-- neondb_owner over the direct endpoint. Idempotent.
--
-- EXPLICIT AND COLUMN-LEVEL, NEVER `ALTER DEFAULT PRIVILEGES`: a table added later gets no
-- access until a line here says so. Nothing is granted on `public`, where Brain lives.
-- src/server/grants.test.ts runs the app's and the CLI's real queries under these roles, so a
-- missing line fails a test rather than a CSM's request.

grant usage on schema ask_naren to ask_naren_app, ask_naren_admin;

-- ask_naren_app: the web app. Reads users (it signs them in) but can never create one or set
-- a password -- that is the admin's credential.
grant select on ask_naren.users to ask_naren_app;
grant select, insert, delete on ask_naren.sessions to ask_naren_app;
grant update (last_seen_at) on ask_naren.sessions to ask_naren_app;
grant select on ask_naren.threads to ask_naren_app;
grant insert (user_id, created_at, last_turn_at, turn_count) on ask_naren.threads to ask_naren_app;
grant update (title, last_turn_at, turn_count, deleted_at) on ask_naren.threads to ask_naren_app;
-- Turns are append-only for the app. Removing a thread is a soft delete on `threads`.
grant select on ask_naren.turns to ask_naren_app;
grant insert (thread_id, position, question, response, outcome, kind, reason, intent,
              scenario_key, cosine, asked_at, answered_at) on ask_naren.turns to ask_naren_app;

-- ask_naren_admin: the users CLI (scripts/users.ts). Users and their sessions, nothing else.
grant select on ask_naren.users to ask_naren_admin;
grant insert (email, name, password_hash) on ask_naren.users to ask_naren_admin;
grant update (password_hash, disabled_at) on ask_naren.users to ask_naren_admin;
grant select, delete on ask_naren.sessions to ask_naren_admin;
