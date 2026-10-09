-- Ask Naren stored threads (issue #46; decided in #37).
--
-- Same rules as 0001: schema `ask_naren` only, idempotent, applied by hand as the owner role
-- over the direct endpoint -- never by the app. Grants live in db/provision/, not here, so
-- this file runs unchanged in the tests.
--
--   psql "$OWNER_DATABASE_URL" -f db/migrations/0002_threads_and_turns.sql

-- One conversation. Created on its first ask, so there are no empty threads.
create table if not exists ask_naren.threads (
  id            bigint generated always as identity primary key,
  -- NO CASCADE: offboarding disables a user rather than deleting them, precisely so their
  -- threads survive. A user row with threads cannot be deleted by accident.
  user_id       integer not null references ask_naren.users (id),
  -- A rename. NULL means "derive it from the first question", which is the common case.
  title         text check (title is null or length(btrim(title)) between 1 and 120),
  created_at    timestamptz not null,
  last_turn_at  timestamptz not null,
  -- Numbers the next turn under a row lock (see src/server/threads.ts: recordTurn).
  turn_count    integer not null default 0 check (turn_count >= 0),
  -- SOFT delete: "removed from your list", never "erased". Retention is out of scope, and a
  -- hard delete would quietly become a retention policy.
  deleted_at    timestamptz
);

create index if not exists threads_user_recent_idx
  on ask_naren.threads (user_id, last_turn_at desc) where deleted_at is null;

-- One question and what came back. The response is kept VERBATIM; the columns beside it are
-- copies pulled out so the analytics question ("what do CSMs ask that the corpus doesn't
-- cover") needs no JSON parsing. The turn replayed to the service is NOT stored: it is
-- derived from question + response when needed, so storage shape and wire shape stay apart.
create table if not exists ask_naren.turns (
  id            bigint generated always as identity primary key,
  thread_id     bigint not null references ask_naren.threads (id) on delete cascade,
  position      integer not null check (position >= 1),
  question      text not null check (length(btrim(question)) > 0),
  response      jsonb not null,
  outcome       text not null check (outcome in ('answered', 'declined', 'clarify', 'rendered')),
  -- Rendered only. Not CHECKed against a list: the kinds are still growing.
  kind          text,
  -- Declined only. Without it, outages would count as coverage gaps.
  reason        text,
  intent        text,
  -- The scenario the response rests on. NULL where it names none, or several (call_prep).
  scenario_key  text,
  -- Only where the response carries `match`.
  cosine        real,
  asked_at      timestamptz not null,
  answered_at   timestamptz not null,
  check (outcome = response ->> 'outcome'),
  check ((kind is not null) = (outcome = 'rendered')),
  check (reason is null or outcome = 'declined'),
  unique (thread_id, position)
);
