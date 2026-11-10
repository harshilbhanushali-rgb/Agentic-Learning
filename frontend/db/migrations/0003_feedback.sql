-- Good / bad ratings on answers, with an optional reason (scrumbles: "Good / bad rating on
-- every answer, with an optional why"). Both directions matter: a bad rating says where the
-- engine is wrong, a good one is a case an engine change must not break.
--
-- ONE ROW PER USER PER TURN: changing your mind replaces the rating rather than piling up
-- votes. Keyed on the turn row, so a rating always points at the exact answer that was shown
-- (the turn keeps the service's response verbatim).
--
-- IDEMPOTENT. Applied by hand as an owner role, then re-run db/provision/grants.sql.
--
--   psql "$OWNER_DATABASE_URL" -f db/migrations/0003_feedback.sql

create table if not exists ask_naren.feedback (
  id          bigint generated always as identity primary key,
  turn_id     bigint not null references ask_naren.turns (id) on delete cascade,
  user_id     integer not null references ask_naren.users (id),
  rating      text not null check (rating in ('good', 'bad')),
  -- Optional, and free text: why it was good or bad, in the CSM's words.
  reason      text check (reason is null or length(reason) between 1 and 2000),
  created_at  timestamptz not null,
  updated_at  timestamptz not null,
  unique (turn_id, user_id)
);
