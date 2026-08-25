-- Call registry
CREATE TABLE IF NOT EXISTS calls (
    call_id     SERIAL PRIMARY KEY,
    filename    TEXT UNIQUE NOT NULL,
    imported_at TIMESTAMPTZ DEFAULT NOW()
);

-- Primary-topic taxonomy (added 2026-07-30): a genuine, deduplicated parent
-- entity for scenarios.primary_topic_key to reference, instead of a free-text
-- primary_topic string independently reinvented per subtopic cluster with no
-- shared identity across clusters. Produced by shared/topic_grouping.py, which
-- one of two mechanisms (grouping_method) builds -- see tuning.yaml.
--   grouping_method    'post_hoc_merge' | 'nested_cluster' -- which mechanism
--                       produced this row; an audit trail, not meant to vary
--                       within one run.
--   keyphrases          exists so a later spec can build an embeddable
--                       primary-topic vector without a schema change.
--   support_calls / support_subtopics / call_coverage
--                       evidence rollup: the union of member subtopics' call
--                       sets, mirroring the evidence columns scenarios already
--                       has.
CREATE TABLE IF NOT EXISTS primary_topics (
    id                SERIAL PRIMARY KEY,
    primary_topic_key TEXT NOT NULL UNIQUE,
    label             TEXT NOT NULL,
    description       TEXT NOT NULL,
    keyphrases        TEXT[] NOT NULL DEFAULT '{}',
    grouping_method   TEXT NOT NULL,
    support_calls     INTEGER NOT NULL,
    support_subtopics INTEGER NOT NULL,
    call_coverage     REAL NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Layer A: scenario taxonomy
--
-- Evidence columns (added 2026-07-27) record WHY each scenario exists, so the
-- taxonomy is auditable without re-running the pipeline:
--   is_coachable   false => no rubric; acts as a sink for junk Layer B matches
--   cluster_kind   scenario | mechanics | logistics
--   support_calls  distinct calls the cluster drew clauses from
--   call_coverage  support_calls / total calls in the corpus
--   triage_verdict scenario_candidate | needs_review (evidence routing, pre-LLM)
--   adjudication_reason  the LLM's one-sentence justification. Required reading
--                  for any needs_review cluster that stayed coachable.
--   rubric_status  rubric_generated | skipped_not_coachable
--                  | skipped_insufficient_responses | failed
--
-- business_description (renamed from sub_topic 2026-07-30): a one-sentence
-- business description of the subtopic, used as embedding text and pasted
-- into rubric prompts. primary_topic stays a NOT NULL denormalized copy of the
-- parent primary_topics row's label (existing simple readers keep working with
-- zero code change); primary_topic_key is the real FK used for grouping/joins.
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id   SERIAL PRIMARY KEY,
    scenario_key  TEXT UNIQUE NOT NULL,
    primary_topic TEXT NOT NULL,
    business_description TEXT NOT NULL,
    keyphrases    TEXT[] NOT NULL DEFAULT '{}',
    soft_skills   TEXT[] NOT NULL DEFAULT '{}',
    bloom_level   TEXT NOT NULL CHECK (bloom_level IN (
                      'remember','understand','apply','analyze','evaluate','create'
                  )),
    is_coachable        BOOLEAN NOT NULL DEFAULT TRUE,
    cluster_kind        TEXT    NOT NULL DEFAULT 'scenario',
    support_calls       INTEGER NOT NULL DEFAULT 0,
    support_clauses     INTEGER NOT NULL DEFAULT 0,
    call_coverage       REAL    NOT NULL DEFAULT 0,
    triage_verdict      TEXT,
    adjudication_reason TEXT,
    rubric_status       TEXT,
    primary_topic_key   TEXT REFERENCES primary_topics(primary_topic_key),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_scenarios_keyphrases
    ON scenarios USING GIN(keyphrases);

-- init_db.py only creates missing tables, it never alters existing ones, so
-- every column above needs an explicit ALTER for already-provisioned databases.
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS is_coachable        BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS cluster_kind        TEXT    NOT NULL DEFAULT 'scenario';
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS support_calls       INTEGER NOT NULL DEFAULT 0;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS support_clauses     INTEGER NOT NULL DEFAULT 0;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS call_coverage       REAL    NOT NULL DEFAULT 0;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS triage_verdict      TEXT;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS adjudication_reason TEXT;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS rubric_status       TEXT;
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS primary_topic_key   TEXT REFERENCES primary_topics(primary_topic_key);

-- RENAME COLUMN has no IF EXISTS form, unlike ADD/DROP COLUMN above -- init_db.py
-- re-runs this whole file on every startup, so the rename is guarded explicitly
-- to stay idempotent on a database that already has business_description.
--
-- table_schema MUST be qualified: information_schema.columns spans every
-- schema, including the baseline_*/v2_*/pre_hierarchy_* snapshot schemas this
-- project keeps around, several of which predate this rename and still have
-- their own snapshot copy of a 'scenarios' table with a literal 'sub_topic'
-- column. An unqualified lookup matches one of those, evaluates true, and the
-- unqualified ALTER below then runs against public.scenarios (via search_path)
-- where sub_topic no longer exists -- confirmed 2026-07-30, this exact bug
-- fired on the first init_db() call after the snapshots existed.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'scenarios' AND column_name = 'sub_topic'
    ) THEN
        ALTER TABLE scenarios RENAME COLUMN sub_topic TO business_description;
    END IF;
END $$;

-- Layer B: trigger-response pairs
-- Vectors stored in Pinecone (index: narens-brain, namespaces: triggers / responses)
-- scenario_key  = primary scenario (first multi-match, or centroid fallback)
-- scenario_keys = all scenarios this pair matched above the similarity threshold
CREATE TABLE IF NOT EXISTS kb_pairs (
    pair_id            SERIAL PRIMARY KEY,
    call_id            INTEGER NOT NULL REFERENCES calls(call_id),
    scenario_id        INTEGER REFERENCES scenarios(scenario_id),
    scenario_key       TEXT,
    scenario_keys      TEXT[] NOT NULL DEFAULT '{}',
    turn_index         INTEGER NOT NULL,
    trigger_text       TEXT NOT NULL,
    response_text      TEXT NOT NULL,
    benchmark_response TEXT,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_pairs_call_turn
    ON kb_pairs (call_id, turn_index);

-- Layer C: evaluation rubrics (one per scenario)
CREATE TABLE IF NOT EXISTS rubrics (
    rubric_id         SERIAL PRIMARY KEY,
    scenario_id       INTEGER NOT NULL UNIQUE REFERENCES scenarios(scenario_id),
    scenario_key      TEXT NOT NULL,
    milestones        JSONB NOT NULL DEFAULT '[]',
    soft_skill_rubric JSONB NOT NULL DEFAULT '{}',
    anti_patterns     JSONB NOT NULL DEFAULT '[]',
    pipeline_version  TEXT NOT NULL CHECK (pipeline_version IN ('v1', 'v2')),
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Response-taxonomy auto-pass (added 2026-08-07): tracks candidate "homeless topic" clusters
-- across pipeline runs so a genuinely recurring gap in the CLIENT-clause-only taxonomy can be
-- graduated into a real scenario automatically, once it survives response_taxonomy_
-- consensus_runs consecutive runs. See docs/superpowers/specs/2026-08-07-response-taxonomy-
-- auto-pass-design.md.
--   member_pair_ids  latest run's raw cluster snapshot -- kept for observability/debugging.
--   stable_pair_ids  running intersection of every member_pair_ids snapshot seen since
--                    first_seen_run_id. THIS is what gets graduated, not member_pair_ids --
--                    a pair that only appeared in one noisy run drops out automatically
--                    instead of riding along on the latest snapshot alone.
--   status           tracking | graduated | discarded
CREATE TABLE IF NOT EXISTS response_taxonomy_candidates (
    candidate_id            SERIAL PRIMARY KEY,
    label                   TEXT NOT NULL,
    description             TEXT NOT NULL,
    member_pair_ids         INTEGER[] NOT NULL,
    stable_pair_ids         INTEGER[] NOT NULL,
    consensus_count         INTEGER NOT NULL DEFAULT 1,
    first_seen_run_id       TEXT NOT NULL,
    last_seen_run_id        TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'tracking',
    graduated_scenario_key  TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- init_db.py only creates missing tables, it never alters existing ones.
ALTER TABLE response_taxonomy_candidates ADD COLUMN IF NOT EXISTS stable_pair_ids INTEGER[] NOT NULL DEFAULT '{}';

-- Layer D: Ego Trap gap-analysis profiles, accumulated per CSM
CREATE TABLE IF NOT EXISTS csms (
    csm_id     TEXT PRIMARY KEY,
    csm_name   TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- milestone_id is the milestone's 1-BASED POSITION in rubrics.milestones, formatted
-- f"M{i+1}" by ego_trap.milestone_scoring.milestone_ids. The array position is the only
-- stable identity available: that JSONB has no id field, v1-fallback rubrics have no
-- guaranteed 'order' key at all (Gemma's raw output is stored unvalidated), and two
-- milestones sharing an 'order' value would merge into ONE row under this PK, silently
-- fusing two distinct milestones' counters. v2's own 'order' is already dense 1-based
-- over the same list, so positional ids match it exactly for every v2 rubric.
--
-- CAVEAT: upsert_rubric's ON CONFLICT (scenario_id) keeps rubric_id stable while
-- replacing milestones, so a Layer C re-run can make "M2" mean a different milestone
-- while rows here keep accumulating under it. Run ops/clear_ego_trap_data.py after any
-- Layer C re-run.
--
-- hits = full_hit count only; partial_hits tracks partial_hit count separately.
-- Weighted score is computed at query time: (hits + 0.5 * partial_hits) / attempts.
-- Never stored -- it changes every time attempts increments. ego_trap.gap_output
-- derives miss_rate as its exact complement, and severity from that.
CREATE TABLE IF NOT EXISTS milestone_performance (
    csm_id         TEXT NOT NULL REFERENCES csms(csm_id),
    rubric_id      INTEGER NOT NULL REFERENCES rubrics(rubric_id),
    milestone_id   TEXT NOT NULL,
    scenario_key   TEXT NOT NULL,
    attempts       INTEGER NOT NULL DEFAULT 0,
    hits           INTEGER NOT NULL DEFAULT 0,
    partial_hits   INTEGER NOT NULL DEFAULT 0,
    last_attempted TIMESTAMPTZ,
    PRIMARY KEY (csm_id, rubric_id, milestone_id)
);
ALTER TABLE milestone_performance ADD COLUMN IF NOT EXISTS partial_hits INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS signal_recognition_gaps (
    csm_id       TEXT NOT NULL REFERENCES csms(csm_id),
    scenario_key TEXT NOT NULL,
    occurrences  INTEGER NOT NULL DEFAULT 0,
    recognized   INTEGER NOT NULL DEFAULT 0,
    missed       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (csm_id, scenario_key)
);

-- Raw per-call gap output, kept for traceability. Writes here are gated by
-- ego_trap.settings.ENABLE_GAP_EVENTS so this can be disabled without a code change.
-- signal_turn_index: position in the parsed transcript, not a wall-clock time — these
-- transcripts carry no timestamps (see ego_trap/transcript_parser.py).
-- milestones_hit = full_hit ids only; milestones_partial_hit tracks partial_hit ids separately.
CREATE TABLE IF NOT EXISTS gap_events (
    gap_event_id           SERIAL PRIMARY KEY,
    call_id                TEXT NOT NULL,
    csm_id                 TEXT NOT NULL REFERENCES csms(csm_id),
    scenario_key           TEXT NOT NULL,
    rubric_id              INTEGER REFERENCES rubrics(rubric_id),
    signal_turn_index      INTEGER,
    gaps                   JSONB NOT NULL DEFAULT '[]',
    milestones_hit         TEXT[] NOT NULL DEFAULT '{}',
    milestones_partial_hit TEXT[] NOT NULL DEFAULT '{}',
    milestones_missed      TEXT[] NOT NULL DEFAULT '{}',
    created_at             TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE gap_events ADD COLUMN IF NOT EXISTS milestones_partial_hit TEXT[] NOT NULL DEFAULT '{}';

-- Layer C: scenario playbooks (added 2026-08-19).
-- Spec: docs/superpowers/specs/2026-08-19-playbook-schema-design.md
--
-- This is what turns Layer C from *validated* into *shipped*. Before it existed,
-- pbv_playbooks_snapped.json and the 22 routing-trial documents had nowhere to land.
--
-- WHY scenario_id IS A HARD FK (operator decision, 2026-08-19): a playbook is an output of
-- ONE taxonomy and dies with it, exactly like rubrics. The JSON artifacts on disk are the
-- archive. THE CONSEQUENCE IS LOAD-BEARING: every FK here is ON DELETE NO ACTION, so
-- `playbooks` MUST appear in ops/ship_union_taxonomy.py's children-first delete chain or the
-- NEXT taxonomy replacement is refused by Postgres partway through.
--
-- WHY JSONB AND NOT playbook_moves/playbook_citations: follows the `rubrics` precedent, which
-- already survived Layer D wiring. move_id is the ARRAY POSITION (M1..Mn), assigned by the
-- loader and never taken from the model -- the same rule as milestone_id (v2/layer_c.py) and
-- coverage-area ids (shared/coverage_areas.py), for the same reason: a model-chosen id lets a
-- re-run silently repoint a person's history at different criteria. key_moves ORDER IS
-- LOAD-BEARING; do not reorder it in place.
--
--   arm      routing arm for rt_*/rte_* documents ('concat'/'r1'); 'real'/'placebo' for pbv_*.
--   status   'live'      the validated production document (PB0 5/5, PB2 4/5 pooled 11-4)
--            'placebo'   a placebo twin -- NEVER production content
--            'trial'     a routing-A/B document; `r1` is UNRESOLVED and was not shipped
--            'superseded' retired but kept for traceability
--            PRODUCTION READS MUST FILTER status = 'live'. Placebo twins and UNRESOLVED trial
--            documents live in this same table and are indistinguishable without it.
--   identity the source artifact's provenance block (model, seed, corpus/taxonomy shas).
--   snap_log per-citation verbatim-snap provenance; NULL for un-snapped documents. The snap
--            step is what VALIDATED the method, so its record is kept, not discarded.
--
-- source_artifact is part of the uniqueness key on purpose: (scenario_key, arm) is
-- collision-free across today's 32 documents ONLY because E1 used a disjoint topic set. An E2
-- re-running `concat` over the original topics would collide.
-- The block between the two markers below is extracted verbatim by ops/load_playbooks.py --
-- DO NOT REMOVE THE MARKERS, and keep the block free of anything but playbooks DDL. The
-- loader executes only those statements, over its own already-hostaddr-corrected connection,
-- instead of running this whole file through db/init_db.py: that would open a second
-- connection from the raw URL (which the system resolver refuses for *.neon.tech) and would
-- take ACCESS EXCLUSIVE on five unrelated live tables for its dozen
-- "ADD COLUMN IF NOT EXISTS" statements -- the lock is acquired BEFORE the IF NOT EXISTS is
-- evaluated, so it blocks concurrent runs even when there is nothing to do. Keeping the text
-- here rather than duplicating it in the loader means there is still exactly one definition.
-- >>> PLAYBOOKS DDL BEGIN
CREATE TABLE IF NOT EXISTS playbooks (
    playbook_id           SERIAL PRIMARY KEY,
    scenario_id           INTEGER NOT NULL REFERENCES scenarios(scenario_id),
    scenario_key          TEXT NOT NULL,
    arm                   TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('live', 'trial', 'placebo', 'superseded')),
    source_artifact       TEXT NOT NULL,
    donor_scenario_key    TEXT,
    n_evidence            INTEGER NOT NULL,
    situation_signature   TEXT NOT NULL,
    arc                   JSONB NOT NULL DEFAULT '[]',
    key_moves             JSONB NOT NULL DEFAULT '[]',
    signature_language    JSONB NOT NULL DEFAULT '[]',
    pitfalls_and_variants JSONB NOT NULL DEFAULT '[]',
    layer_d_checks        JSONB NOT NULL DEFAULT '[]',
    snap_log              JSONB,
    identity              JSONB NOT NULL DEFAULT '{}',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scenario_key, arm, source_artifact)
);

-- At most ONE live playbook per scenario, enforced by the DATABASE rather than by the loader.
-- A partial unique index is the only way to say "unique among live rows" while still allowing
-- the placebo twin and the trial documents to share the scenario_key.
CREATE UNIQUE INDEX IF NOT EXISTS idx_playbooks_one_live
    ON playbooks (scenario_key) WHERE status = 'live';

CREATE INDEX IF NOT EXISTS idx_playbooks_scenario_key ON playbooks (scenario_key);
-- <<< PLAYBOOKS DDL END <<<

-- ============================================================================
-- Layer D redesign (2026-08-20): gap analysis against playbooks (Brain/layer_d/)
--
-- Replaces the rubric-era gap_events / milestone_performance / signal_recognition_gaps
-- tables above, which are EMPTY (keyed to the pre-union taxonomy) and retire with
-- ego_trap/. Design decisions, each one paid for by a measured defect:
--
--   * move_events carries a NATURAL UNIQUE KEY, so a re-run UPSERTS instead of
--     duplicating. The old gap_events had a serial PK only, and a double run
--     silently double-counted 28 signals ("two runs, one DB", layer-d-realignment.md).
--   * move_performance is MATERIALIZED from move_events by full recompute
--     (storage.refresh_move_performance), never incremented in place. The old
--     `attempts = attempts + 1 ON CONFLICT` is what made re-runs destructive.
--   * verdicts include 'unscored' (instrument failure: id missing from the response,
--     quote failed verification, swap-inconsistent). Unscored NEVER counts as an
--     attempt -- the old pipeline normalized parse failures to 'miss', so output
--     truncation manufactured coaching failures.
--   * playbook_id is a NOT NULL FK: a moment is scored against ONE playbook's moves
--     (move_id = the array position M1..Mn -- see the playbooks DDL note above), and
--     these rows die with the taxonomy like playbooks do. Both tables are in
--     ops/ship_union_taxonomy.py's SNAPSHOT_TABLES and DELETE_ORDER.
--   * rater_population/rater_id: the SAME instrument scores Naren's own routed
--     moments (rater_id 'naren', source_ref 'pair:<pair_id>') and CSM moments
--     (rater_id = csms.csm_id, source_ref 'turn:<index>'). A gap is a rate
--     DIFFERENCE against the measured benchmark, never an absolute score. Derived
--     numbers (rates, shrinkage, gap ranking, dead-check flags) are computed at
--     report time by layer_d/aggregate.py and never stored.
-- ============================================================================

CREATE TABLE IF NOT EXISTS move_events (
    move_event_id    SERIAL PRIMARY KEY,
    rater_population TEXT NOT NULL CHECK (rater_population IN ('csm', 'naren')),
    rater_id         TEXT NOT NULL,
    call_id          TEXT NOT NULL,      -- transcript stem (csm) / calls.filename (naren)
    source_ref       TEXT NOT NULL,      -- 'turn:<anchor_index>' or 'pair:<pair_id>'
    scenario_key     TEXT NOT NULL,
    playbook_id      INTEGER NOT NULL REFERENCES playbooks(playbook_id),
    grader_arm       TEXT NOT NULL CHECK (grader_arm IN ('checks', 'pairwise')),
    grader_model     TEXT NOT NULL DEFAULT '',  -- per-row provenance: which model graded
    via              TEXT NOT NULL,      -- 'last_turn' | 'stitched' (segmentation arm e)
    response_outcome TEXT NOT NULL CHECK (response_outcome IN ('csm', 'other_joveo', 'none')),
    trigger_text     TEXT NOT NULL,
    response_text    TEXT NOT NULL,
    verdicts         JSONB NOT NULL DEFAULT '[]',  -- [{move_id, verdict, quote, quote_score, reason}]
    k_runs           INTEGER NOT NULL DEFAULT 1,
    run_id           TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (rater_population, call_id, source_ref, playbook_id, grader_arm)
);

CREATE INDEX IF NOT EXISTS idx_move_events_rater ON move_events (rater_population, rater_id);
CREATE INDEX IF NOT EXISTS idx_move_events_playbook ON move_events (playbook_id);

CREATE TABLE IF NOT EXISTS move_performance (
    rater_population TEXT NOT NULL CHECK (rater_population IN ('csm', 'naren')),
    rater_id         TEXT NOT NULL,
    playbook_id      INTEGER NOT NULL REFERENCES playbooks(playbook_id),
    move_id          TEXT NOT NULL,      -- 'M1'..'Mn', positional (see playbooks DDL note)
    grader_arm       TEXT NOT NULL CHECK (grader_arm IN ('checks', 'pairwise')),
    attempts         INTEGER NOT NULL,   -- scored verdicts only; unscored excluded
    hits             INTEGER NOT NULL,
    partials         INTEGER NOT NULL,
    unscored         INTEGER NOT NULL,   -- instrument-failure count, reported not scored
    refreshed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (rater_population, rater_id, playbook_id, move_id, grader_arm)
);
