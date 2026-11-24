-- Grants for ask_naren_service. Run after every migration AND after every Brain copy
-- (migrate.py and ops/copy_brain_to_rds.py both run it). Idempotent.
--
-- EXPLICIT, TABLE BY TABLE, NEVER `ALTER DEFAULT PRIVILEGES` (same rule as
-- frontend/db/provision/grants.sql, ADR 0012): a table added later gets no access until a
-- line here says so. These are exactly what the service reads: shared/storage.py's
-- get_scenarios / get_call_pairs / get_naren_responses_for_scenario /
-- get_playbook_for_scenario, the brain_meta lookup, and the vector search.
--
-- Brain's own tables appear only once a Brain has been copied in (they come from
-- Brain/db/schema.sql, not from these migrations), so a table that does not exist yet is
-- skipped with a NOTICE rather than failing the run. Nothing is lost by that: the service's
-- first read of a table it cannot see fails loudly with "permission denied", and GET /verify
-- names it.

grant usage on schema brain, extensions to ask_naren_service;

do $$
declare
  t text;
begin
  -- primary_topics is not read by the service. It is here so a copy made AS this login
  -- (POST /admin/setup reads the source Brain with it) can carry the rows scenarios'
  -- primary_topic_key foreign key points at.
  foreach t in array array['scenarios', 'kb_pairs', 'calls', 'playbooks', 'brain_meta',
                           'trigger_vectors', 'primary_topics'] loop
    if to_regclass('brain.' || t) is null then
      raise notice 'brain.% does not exist yet -- not granted (copy a Brain in, then re-run)', t;
    else
      execute format('grant select on brain.%I to ask_naren_service', t);
    end if;
  end loop;
end $$;
