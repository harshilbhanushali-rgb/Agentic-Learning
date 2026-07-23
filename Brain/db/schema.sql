-- Call registry
CREATE TABLE IF NOT EXISTS calls (
    call_id     SERIAL PRIMARY KEY,
    filename    TEXT UNIQUE NOT NULL,
    imported_at TIMESTAMPTZ DEFAULT NOW()
);

-- Layer A: scenario taxonomy
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id   SERIAL PRIMARY KEY,
    scenario_key  TEXT UNIQUE NOT NULL,
    primary_topic TEXT NOT NULL,
    sub_topic     TEXT NOT NULL,
    keyphrases    TEXT[] NOT NULL DEFAULT '{}',
    soft_skills   TEXT[] NOT NULL DEFAULT '{}',
    bloom_level   TEXT NOT NULL CHECK (bloom_level IN (
                      'remember','understand','apply','analyze','evaluate','create'
                  )),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_scenarios_keyphrases
    ON scenarios USING GIN(keyphrases);

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

-- Layer D: Ego Trap gap-analysis profiles, accumulated per CSM
CREATE TABLE IF NOT EXISTS csms (
    csm_id     TEXT PRIMARY KEY,
    csm_name   TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- milestone_id is synthesized as f"M{order}" from rubrics.milestones (no stable id in that JSONB)
-- hits = full_hit count only; partial_hits tracks partial_hit count separately.
-- Weighted score is computed at query time: (hits + 0.5 * partial_hits) / attempts.
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
