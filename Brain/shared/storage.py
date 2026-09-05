import json
import psycopg

_database_url: str = ""

# Must mirror the scenarios_bloom_level_check constraint in db/schema.sql.
_VALID_BLOOM_LEVELS = {"remember", "understand", "apply", "analyze", "evaluate", "create"}


def get_connection(database_url: str) -> psycopg.Connection:
    global _database_url
    _database_url = database_url
    return psycopg.connect(
        database_url,
        autocommit=True,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )


def reconnect_if_closed(conn: psycopg.Connection) -> psycopg.Connection:
    """Return conn if healthy, otherwise open a fresh connection."""
    try:
        conn.execute("SELECT 1")
        return conn
    except Exception:
        if not _database_url:
            raise RuntimeError("No database_url recorded — call get_connection first.")
        return get_connection(_database_url)


def is_read_only(conn: psycopg.Connection) -> bool:
    """Cheap pre-flight check (SHOW, no write) so a caller can fail fast before
    spending on grading, instead of discovering the database refuses writes only
    after an INSERT dies. A read-only project is a DIFFERENT failure from a dead
    connection: the connection itself is alive and healthy (reconnect_if_closed's
    SELECT 1 passes), so only an explicit permission check catches it.

    ROOT CAUSE, confirmed 2026-08-26 (not just observed): this is NEVER Neon
    itself restricting the project. It is a `SET SESSION
    default_transaction_read_only = on` left behind by some OTHER client (this
    project's own `_connect_read_only` helpers were one confirmed source, now
    fixed to reset before close) that leaks through Neon's pooled endpoint --
    PgBouncer transaction pooling reuses the same backend server connection
    across unrelated clients, so a session-level SET one client forgets to undo
    poisons whichever client gets that backend next. Proven directly: `SET
    SESSION default_transaction_read_only = off` on a "read-only" connection
    clears it immediately, every time, including live during this incident --
    a genuine server-side restriction could not be overridden that way. Because
    other, unfixed sources of the same anti-pattern can still exist (outside
    this codebase), see clear_read_only() below for the self-healing form
    production code should actually call.
    """
    with conn.cursor() as cur:
        cur.execute("SHOW default_transaction_read_only")
        return cur.fetchone()[0] == "on"


def clear_read_only(conn: psycopg.Connection) -> bool:
    """Actively un-poison conn if it inherited a leaked read-only session
    setting (see is_read_only's docstring), then report whether it's STILL
    read-only afterward. Prefer this over a bare is_read_only check in any
    loop that's about to spend before writing: a bare check only detects the
    leak and gives up, while this neutralizes it and lets the run continue
    (measured 2026-08-26: the leak recurred from an unidentified external
    source even after fixing this project's own known contributors, so
    detect-and-abort alone kept losing progress to something outside this
    codebase's control). A True return means the reset itself didn't take --
    the one shape a genuine, non-leak restriction would produce -- and the
    caller should treat it exactly like the old detect-and-abort path.
    """
    conn.execute("SET SESSION default_transaction_read_only = off")
    return is_read_only(conn)


def upsert_call(conn: psycopg.Connection, filename: str) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO calls (filename) VALUES (%s)
            ON CONFLICT (filename) DO UPDATE SET filename = EXCLUDED.filename
            RETURNING call_id
        """, (filename,))
        call_id = cur.fetchone()[0]
    conn.commit()
    return call_id


def upsert_scenario(conn: psycopg.Connection, scenario: dict, *, commit: bool = True) -> int:
    """Insert or update a scenario.

    The evidence columns default so that V1's Layer A, which has no clustering
    evidence to report, can keep calling this unchanged.

    `commit=False` EXISTS FOR ONE CALLER and is not a style preference. The default
    commit is correct for Layer A, which writes ~259 scenarios across a long run and
    must not hold a transaction open across slow work. It is WRONG for
    ops/ship_union_taxonomy.py, whose whole safety story is "deletes and load in one
    transaction": that script deletes every child table first, so the commit inside the
    FIRST of 259 upserts made those DELETEs permanent, and the later rollback on a
    post-load mismatch was a no-op that still printed "rolled back". Found 2026-08-20,
    fixed 2026-08-24. A caller passing commit=False owns the commit.

    bloom_level is LLM-generated and not guaranteed to land in the DB's enum
    (e.g. Gemma once returned "explain" instead of "understand") -- a bad
    value here must not raise mid-way through a batch of upserts and strand
    the rest of an expensive Gemma run unwritten.
    """
    bloom_level = scenario["bloom_level"]
    if bloom_level not in _VALID_BLOOM_LEVELS:
        print(f"  ! invalid bloom_level {bloom_level!r} for "
              f"{scenario['scenario_key']!r} -- defaulting to 'understand'")
        bloom_level = "understand"
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO scenarios
              (scenario_key, primary_topic, business_description, keyphrases, soft_skills,
               bloom_level, is_coachable, cluster_kind, support_calls, support_clauses,
               call_coverage, triage_verdict, adjudication_reason, primary_topic_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (scenario_key) DO UPDATE SET
                primary_topic = EXCLUDED.primary_topic,
                business_description = EXCLUDED.business_description,
                keyphrases    = EXCLUDED.keyphrases,
                soft_skills   = EXCLUDED.soft_skills,
                bloom_level   = EXCLUDED.bloom_level,
                is_coachable        = EXCLUDED.is_coachable,
                cluster_kind        = EXCLUDED.cluster_kind,
                support_calls       = EXCLUDED.support_calls,
                support_clauses     = EXCLUDED.support_clauses,
                call_coverage       = EXCLUDED.call_coverage,
                triage_verdict      = EXCLUDED.triage_verdict,
                adjudication_reason = EXCLUDED.adjudication_reason,
                primary_topic_key   = EXCLUDED.primary_topic_key
            RETURNING scenario_id
        """, (
            scenario["scenario_key"],
            scenario["primary_topic"],
            scenario["business_description"],
            scenario["keyphrases"],
            scenario["soft_skills"],
            bloom_level,
            scenario.get("is_coachable", True),
            scenario.get("cluster_kind", "scenario"),
            scenario.get("support_calls", 0),
            scenario.get("support_clauses", 0),
            scenario.get("call_coverage", 0.0),
            scenario.get("triage_verdict"),
            scenario.get("adjudication_reason"),
            scenario.get("primary_topic_key"),
        ))
        scenario_id = cur.fetchone()[0]
    if commit:
        conn.commit()
    return scenario_id


def upsert_primary_topic(conn: psycopg.Connection, topic: dict) -> int:
    """Insert or update a primary_topics row.

    Written once per macro-group after Layer A's per-subtopic adjudication loop
    finishes (zero Gemma calls at that point -- topic_grouping.group_post_hoc/
    group_nested and the label-batch Gemma call already ran), mirroring
    upsert_scenario's shape.
    """
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO primary_topics
              (primary_topic_key, label, description, keyphrases, grouping_method,
               support_calls, support_subtopics, call_coverage)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (primary_topic_key) DO UPDATE SET
                label             = EXCLUDED.label,
                description       = EXCLUDED.description,
                keyphrases        = EXCLUDED.keyphrases,
                grouping_method   = EXCLUDED.grouping_method,
                support_calls     = EXCLUDED.support_calls,
                support_subtopics = EXCLUDED.support_subtopics,
                call_coverage     = EXCLUDED.call_coverage
            RETURNING id
        """, (
            topic["primary_topic_key"],
            topic["label"],
            topic["description"],
            topic["keyphrases"],
            topic["grouping_method"],
            topic["support_calls"],
            topic["support_subtopics"],
            topic["call_coverage"],
        ))
        topic_id = cur.fetchone()[0]
    conn.commit()
    return topic_id


def set_rubric_status(conn: psycopg.Connection, scenario_key: str, status: str) -> None:
    """Record a scenario's terminal Layer C outcome.

    Every scenario must end with a non-null rubric_status. The reconciliation
    check at the end of the run asserts that, which is what makes a silent
    149-scenarios-but-148-rubrics gap impossible to produce.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scenarios SET rubric_status = %s WHERE scenario_key = %s",
            (status, scenario_key),
        )
    conn.commit()


def get_rubric_status_report(conn: psycopg.Connection) -> list[tuple]:
    """(cluster_kind, rubric_status, count) over every scenario, for the run summary."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT cluster_kind, COALESCE(rubric_status, 'MISSING') AS status, COUNT(*)
            FROM scenarios
            GROUP BY cluster_kind, status
            ORDER BY cluster_kind, status
        """)
        return cur.fetchall()


def count_scenarios_without_status(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM scenarios WHERE rubric_status IS NULL")
        return cur.fetchone()[0]


def insert_kb_pair(conn: psycopg.Connection, pair: dict) -> int:
    """Insert or UPDATE a pair, keyed on (call_id, turn_index).

    *** THIS WAS `DO NOTHING` AND THAT MADE RE-ROUTING SILENTLY IMPOSSIBLE. *** On a conflict
    the old row survived and the function returned its `pair_id`, so a second run after any
    routing change kept the OLD `scenario_key` in Postgres while its caller handed the NEW
    `scenario_key` to Pinecone as metadata under that same `pair_id`. The two stores then
    disagreed about which scenario a pair belonged to, with no error raised anywhere and
    nothing in either store admitting it. `DO UPDATE` makes a re-run mean what it says.

    The trigger/response text is refreshed too: a re-parse that changed speaker roles (the
    Avoma-roster and spaCy-component failures both moved ~20% of this corpus) must not leave
    stale text sitting under a fresh routing verdict.
    """
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO kb_pairs
              (call_id, scenario_id, scenario_key, scenario_keys, turn_index,
               trigger_text, response_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (call_id, turn_index) DO UPDATE SET
                scenario_id   = EXCLUDED.scenario_id,
                scenario_key  = EXCLUDED.scenario_key,
                scenario_keys = EXCLUDED.scenario_keys,
                trigger_text  = EXCLUDED.trigger_text,
                response_text = EXCLUDED.response_text
            RETURNING pair_id
        """, (
            pair["call_id"],
            pair.get("scenario_id"),
            pair.get("scenario_key"),
            pair.get("scenario_keys", []),
            pair["turn_index"],
            pair["trigger_text"],
            pair["response_text"],
        ))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "SELECT pair_id FROM kb_pairs WHERE call_id = %s AND turn_index = %s",
                (pair["call_id"], pair["turn_index"]),
            )
            row = cur.fetchone()
        pair_id = row[0]
    conn.commit()
    return pair_id


def upsert_rubric(conn: psycopg.Connection, rubric: dict) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO rubrics
              (scenario_id, scenario_key, milestones, soft_skill_rubric, anti_patterns, pipeline_version)
            VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
            ON CONFLICT (scenario_id) DO UPDATE SET
                milestones        = EXCLUDED.milestones,
                soft_skill_rubric = EXCLUDED.soft_skill_rubric,
                anti_patterns     = EXCLUDED.anti_patterns,
                pipeline_version  = EXCLUDED.pipeline_version
            RETURNING rubric_id
        """, (
            rubric["scenario_id"],
            rubric["scenario_key"],
            json.dumps(rubric["milestones"]),
            json.dumps(rubric["soft_skill_rubric"]),
            json.dumps(rubric["anti_patterns"]),
            rubric["pipeline_version"],
        ))
        rubric_id = cur.fetchone()[0]
    conn.commit()
    return rubric_id


def get_scenarios(conn: psycopg.Connection) -> list[dict]:
    """All scenarios, shaped like the scenario_map Layer A builds.

    is_coachable and cluster_kind must be included: this is the checkpoint-resume
    path, and without them a resumed run treats every mechanics sink as a real
    coachable scenario and generates rubrics for backchannel.

    Returns EVERY row -- sinks included -- and deliberately takes no filter
    argument. Layer B needs the sinks as match candidates (a junk trigger whose
    best match is a sink is filed there instead of contaminating a real rubric),
    and Layer D's similarity mode needs them for the same reason inverted: a sink
    winning is the only signal that a client turn is NOT worth scoring. A consumer
    that wants only coachable rows derives that itself -- see
    ego_trap/scenario_pool.py.

    rubric_status is observability only. It is NOT a filter predicate: a
    'skipped_insufficient_responses' scenario is a genuinely coachable topic that
    merely has too little evidence for a rubric yet, so filtering on it would hide
    a coverage gap rather than remove junk.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT scenario_id, scenario_key, business_description, primary_topic, keyphrases, "
            "soft_skills, is_coachable, cluster_kind, primary_topic_key, rubric_status "
            "FROM scenarios"
        )
        rows = cur.fetchall()
    return [
        {"scenario_id": r[0], "scenario_key": r[1], "business_description": r[2],
         "primary_topic": r[3], "keyphrases": r[4], "soft_skills": r[5],
         "is_coachable": r[6], "cluster_kind": r[7], "primary_topic_key": r[8],
         "rubric_status": r[9]}
        for r in rows
    ]


def get_primary_topics(conn: psycopg.Connection) -> list[dict]:
    """All primary_topics, shaped for shared.scenario_vectors.build_primary_topic_vecs.

    Analogous to get_scenarios() -- callers key this list by primary_topic_key
    to build the map Layer B's two-stage matching needs.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT primary_topic_key, label, description, keyphrases FROM primary_topics"
        )
        rows = cur.fetchall()
    return [
        {"primary_topic_key": r[0], "label": r[1], "description": r[2], "keyphrases": r[3]}
        for r in rows
    ]


def get_naren_responses_for_scenario(conn: psycopg.Connection, scenario_key: str) -> list[dict]:
    """Responses whose PRIMARY scenario_key is this one. Layer C's clause pool.

    Matches the scalar scenario_key only, never the scenario_keys[] array. Do not
    "fix" that here: this WHERE clause defines Layer C's clause pool (v1/layer_c.py,
    v2/layer_c.py, ops/rerun_layer_c.py all call this), so widening it would
    silently change the pool for every rubric and invalidate every calibrated
    layer_c threshold plus the 385-milestone replay baseline. A consumer that wants
    the multi-label population has its own query --
    get_responses_for_scenario_multilabel below.

    trigger_text is SELECTED but does not touch the WHERE clause, so the pool is
    byte-identical to before. Layer C's describe step has always been blind to the
    client turn -- which is why it cannot state a move's precondition -- and this
    is what lets a cluster reach the triggers of its own member pairs. See
    docs/superpowers/specs/2026-08-12-layer-c-profile-rebuild-design.md section 3.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.pair_id, p.response_text, c.filename, p.trigger_text
            FROM kb_pairs p JOIN calls c ON p.call_id = c.call_id
            WHERE p.scenario_key = %s
            ORDER BY p.pair_id
        """, (scenario_key,))
        rows = cur.fetchall()
    return [{"pair_id": r[0], "response_text": r[1], "call_filename": r[2],
             "trigger_text": r[3]} for r in rows]


def get_responses_for_scenario_multilabel(
    conn: psycopg.Connection, scenario_key: str
) -> list[dict]:
    """Every response filed under this scenario, as PRIMARY or SECONDARY match.

    Layer B assigns each pair up to max_scenarios_per_pair keys (measured
    production width: 63% one / 19% two / 18% three), storing the best in the
    scalar scenario_key and all of them in scenario_keys[]. Anything reading only
    the scalar column therefore cannot see roughly a third of the pairs that were
    judged relevant to a scenario.

    A separate function rather than a wider WHERE on
    get_naren_responses_for_scenario, because that one is Layer C's clause-pool
    predicate and must not move. This one exists for read-only display concerns
    (Layer D's benchmark reference), where a wider candidate set is free.

    The OR is not redundant with the array test: scenario_keys is
    NOT NULL DEFAULT '{}', so rows written before the column was added (2026-06-29)
    have an empty array and would vanish if matched on the array alone.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.pair_id, p.response_text, c.filename,
                   (p.scenario_key = %(key)s) AS is_primary
            FROM kb_pairs p JOIN calls c ON p.call_id = c.call_id
            WHERE p.scenario_key = %(key)s OR %(key)s = ANY(p.scenario_keys)
            ORDER BY p.pair_id
        """, {"key": scenario_key})
        rows = cur.fetchall()
    return [
        {"pair_id": r[0], "response_text": r[1], "call_filename": r[2], "is_primary": r[3]}
        for r in rows
    ]


# --- Layer D (Ego Trap) ---------------------------------------------------

def upsert_csm(conn: psycopg.Connection, csm_id: str, csm_name: str) -> str:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO csms (csm_id, csm_name) VALUES (%s, %s)
            ON CONFLICT (csm_id) DO UPDATE SET csm_name = EXCLUDED.csm_name
            RETURNING csm_id
        """, (csm_id, csm_name))
        result = cur.fetchone()[0]
    conn.commit()
    return result


def get_rubric_for_scenario(conn: psycopg.Connection, scenario_key: str) -> dict | None:
    """The Layer C rubric for a scenario, or None.

    pipeline_version must be included, for the same reason get_scenarios must
    include is_coachable: a consumer cannot interpret this rubric without it. A
    'v2' rubric's milestones are HDBSCAN clusters carrying real support counts; a
    'v1' rubric's are Gemma free-text with no evidence fields and no guarantee that
    even 'order' is present. Scoring against the two is not the same measurement,
    and sniffing source_v out of the JSONB is a workaround for a missing column.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT rubric_id, scenario_id, scenario_key, milestones, soft_skill_rubric,
                   anti_patterns, pipeline_version
            FROM rubrics WHERE scenario_key = %s LIMIT 1
        """, (scenario_key,))
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "rubric_id": row[0],
        "scenario_id": row[1],
        "scenario_key": row[2],
        "milestones": row[3],
        "soft_skill_rubric": row[4],
        "anti_patterns": row[5],
        "pipeline_version": row[6],
    }


def get_milestone_gap_profile(
    conn: psycopg.Connection, csm_id: str, min_attempts: int = 1
) -> list[dict]:
    """One row per milestone this CSM has attempted. Raw counters only.

    miss_rate and severity are derived by ego_trap.gap_output, never selected here
    and never stored -- mirroring the convention db/schema.sql already documents for
    the weighted score: any value computed from `attempts` goes stale the next time
    `attempts` increments.

    min_attempts is a report filter (Ego_trap.md's own coaching query acts only at
    attempts >= 3) and is deliberately a function argument rather than a tuning.yaml
    key: it bounds what a reader is shown, not what the pipeline decides.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT mp.scenario_key, mp.rubric_id, mp.milestone_id, mp.attempts,
                   mp.hits, mp.partial_hits, mp.last_attempted, r.pipeline_version
            FROM milestone_performance mp
            JOIN rubrics r ON r.rubric_id = mp.rubric_id
            WHERE mp.csm_id = %s AND mp.attempts >= %s
            ORDER BY mp.scenario_key, mp.milestone_id
        """, (csm_id, min_attempts))
        rows = cur.fetchall()
    return [
        {"scenario_key": r[0], "rubric_id": r[1], "milestone_id": r[2], "attempts": r[3],
         "hits": r[4], "partial_hits": r[5], "last_attempted": r[6], "pipeline_version": r[7]}
        for r in rows
    ]


def upsert_milestone_performance(
    conn: psycopg.Connection,
    csm_id: str,
    rubric_id: int,
    milestone_id: str,
    scenario_key: str,
    verdict: str,
) -> None:
    hits = 1 if verdict == "full_hit" else 0
    partial_hits = 1 if verdict == "partial_hit" else 0
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO milestone_performance
              (csm_id, rubric_id, milestone_id, scenario_key, attempts, hits, partial_hits, last_attempted)
            VALUES (%s, %s, %s, %s, 1, %s, %s, NOW())
            ON CONFLICT (csm_id, rubric_id, milestone_id) DO UPDATE SET
                attempts = milestone_performance.attempts + 1,
                hits = milestone_performance.hits + EXCLUDED.hits,
                partial_hits = milestone_performance.partial_hits + EXCLUDED.partial_hits,
                last_attempted = NOW()
        """, (csm_id, rubric_id, milestone_id, scenario_key, hits, partial_hits))
    conn.commit()


def upsert_signal_recognition_gap(
    conn: psycopg.Connection,
    csm_id: str,
    scenario_key: str,
    recognized: bool,
) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO signal_recognition_gaps
              (csm_id, scenario_key, occurrences, recognized, missed)
            VALUES (%s, %s, 1, %s, %s)
            ON CONFLICT (csm_id, scenario_key) DO UPDATE SET
                occurrences = signal_recognition_gaps.occurrences + 1,
                recognized = signal_recognition_gaps.recognized + EXCLUDED.recognized,
                missed = signal_recognition_gaps.missed + EXCLUDED.missed
        """, (csm_id, scenario_key, 1 if recognized else 0, 0 if recognized else 1))
    conn.commit()


def insert_gap_event(conn: psycopg.Connection, event: dict) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO gap_events
              (call_id, csm_id, scenario_key, rubric_id, signal_turn_index,
               gaps, milestones_hit, milestones_partial_hit, milestones_missed)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            RETURNING gap_event_id
        """, (
            event["call_id"],
            event["csm_id"],
            event["scenario_key"],
            event.get("rubric_id"),
            event.get("signal_turn_index"),
            json.dumps(event.get("gaps", [])),
            event.get("milestones_hit", []),
            event.get("milestones_partial_hit", []),
            event.get("milestones_missed", []),
        ))
        gap_event_id = cur.fetchone()[0]
    conn.commit()
    return gap_event_id


# --- Layer C (playbooks) --------------------------------------------------
# Spec: docs/superpowers/specs/2026-08-19-playbook-schema-design.md

# Must mirror the playbooks_status_check constraint in db/schema.sql.
_VALID_PLAYBOOK_STATUSES = {"live", "trial", "placebo", "superseded"}


def assign_move_ids(key_moves: list[dict]) -> list[dict]:
    """Return key_moves with move_id set to the ARRAY POSITION (M1..Mn).

    Any move_id the model supplied is DISCARDED and overwritten. This is the same
    rule as milestone_id (v2/layer_c.py) and coverage-area ids
    (shared/coverage_areas.py), and it exists for the same reason: a model-chosen id
    lets a re-synthesis silently repoint a person's accumulated history at different
    criteria. Order is therefore load-bearing -- reordering key_moves renumbers them.

    Pure and copying: the caller's dicts are never mutated, so a loader can compare
    the original artifact object after calling this and still see the artifact's shape.
    """
    return [
        {**move, "move_id": f"M{i}"}
        for i, move in enumerate(key_moves, start=1)
    ]


def strip_move_ids(key_moves: list[dict]) -> list[dict]:
    """Inverse of assign_move_ids, for round-trip fidelity checks (gate G-P2)."""
    return [{k: v for k, v in move.items() if k != "move_id"} for move in key_moves]


def upsert_playbook(conn: psycopg.Connection, playbook: dict) -> int:
    """Insert or update one playbook document, keyed (scenario_key, arm, source_artifact).

    source_artifact is in the conflict key deliberately: (scenario_key, arm) is
    collision-free across today's 32 documents only because the E1 extension used a
    disjoint topic set. A future extension re-running an existing arm over the
    original topics would otherwise overwrite a published document.

    move_id assignment happens HERE rather than in the loader so that every writer
    gets it -- a second caller that forgot to call assign_move_ids would otherwise
    write moves with no ids at all.

    At most one status='live' row per scenario_key is enforced by
    idx_playbooks_one_live in the database, not here. A second live document raises
    psycopg.errors.UniqueViolation, which is the intended behaviour: the caller must
    demote the incumbent to 'superseded' first rather than have one silently win.
    """
    status = playbook["status"]
    if status not in _VALID_PLAYBOOK_STATUSES:
        raise ValueError(
            f"invalid playbook status {status!r} for {playbook['scenario_key']!r} -- "
            f"expected one of {sorted(_VALID_PLAYBOOK_STATUSES)}"
        )
    body = playbook["playbook"]
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO playbooks
              (scenario_id, scenario_key, arm, status, source_artifact, donor_scenario_key,
               n_evidence, situation_signature, arc, key_moves, signature_language,
               pitfalls_and_variants, layer_d_checks, snap_log, identity)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
            ON CONFLICT (scenario_key, arm, source_artifact) DO UPDATE SET
                scenario_id           = EXCLUDED.scenario_id,
                status                = EXCLUDED.status,
                donor_scenario_key    = EXCLUDED.donor_scenario_key,
                n_evidence            = EXCLUDED.n_evidence,
                situation_signature   = EXCLUDED.situation_signature,
                arc                   = EXCLUDED.arc,
                key_moves             = EXCLUDED.key_moves,
                signature_language    = EXCLUDED.signature_language,
                pitfalls_and_variants = EXCLUDED.pitfalls_and_variants,
                layer_d_checks        = EXCLUDED.layer_d_checks,
                snap_log              = EXCLUDED.snap_log,
                identity              = EXCLUDED.identity
            RETURNING playbook_id
        """, (
            playbook["scenario_id"],
            playbook["scenario_key"],
            playbook["arm"],
            status,
            playbook["source_artifact"],
            playbook.get("donor_scenario_key"),
            playbook["n_evidence"],
            body["situation_signature"],
            json.dumps(body.get("arc", [])),
            json.dumps(assign_move_ids(body.get("key_moves", []))),
            json.dumps(body.get("signature_language", [])),
            json.dumps(body.get("pitfalls_and_variants", [])),
            json.dumps(body.get("layer_d_checks", [])),
            json.dumps(playbook["snap_log"]) if playbook.get("snap_log") is not None else None,
            json.dumps(playbook.get("identity", {})),
        ))
        playbook_id = cur.fetchone()[0]
    conn.commit()
    return playbook_id


_PLAYBOOK_COLUMNS = """
    playbook_id, scenario_id, scenario_key, arm, status, source_artifact,
    donor_scenario_key, n_evidence, situation_signature, arc, key_moves,
    signature_language, pitfalls_and_variants, layer_d_checks, snap_log, identity
"""


def _playbook_row_to_dict(row: tuple) -> dict:
    return {
        "playbook_id": row[0],
        "scenario_id": row[1],
        "scenario_key": row[2],
        "arm": row[3],
        "status": row[4],
        "source_artifact": row[5],
        "donor_scenario_key": row[6],
        "n_evidence": row[7],
        "playbook": {
            "situation_signature": row[8],
            "arc": row[9],
            "key_moves": row[10],
            "signature_language": row[11],
            "pitfalls_and_variants": row[12],
            "layer_d_checks": row[13],
        },
        "snap_log": row[14],
        "identity": row[15],
    }


def get_playbook_for_scenario(
    conn: psycopg.Connection,
    scenario_key: str,
    status: str = "live",
    arm: str | None = None,
) -> dict | None:
    """The playbook for a scenario, or None.

    DEFAULTS TO status='live' ON PURPOSE, and callers should almost never override it.
    The placebo twins and the UNRESOLVED r1 trial documents sit in this same table and
    are indistinguishable from production content without the filter -- serving a
    placebo to a CSM is exactly the failure this default prevents. Same reasoning as
    get_rubric_for_scenario returning pipeline_version: a consumer cannot interpret
    the row without knowing which kind of thing it is.

    RAISES if the filter matches more than one row instead of returning an arbitrary
    one. This mirrors get_rubric_for_scenario, but that function is safe with a bare
    LIMIT 1 only because rubrics.scenario_id is UNIQUE -- playbooks is deliberately
    NOT: at status='trial' every scenario has both a `concat` and an `r1` document, so
    a silent LIMIT 1 could hand back the r1 arm, which is UNRESOLVED and was never
    shipped. Pass `arm` to disambiguate.
    """
    if status not in _VALID_PLAYBOOK_STATUSES:
        raise ValueError(f"invalid playbook status filter {status!r}")
    sql = f"SELECT {_PLAYBOOK_COLUMNS} FROM playbooks WHERE scenario_key = %s AND status = %s"
    params: tuple = (scenario_key, status)
    if arm is not None:
        sql += " AND arm = %s"
        params += (arm,)
    sql += " ORDER BY arm, source_artifact"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        found = sorted({r[3] for r in rows})
        raise ValueError(
            f"{len(rows)} playbooks match scenario_key={scenario_key!r} status={status!r} "
            f"(arms {found}) -- pass arm= to choose one rather than getting an arbitrary row"
        )
    return _playbook_row_to_dict(rows[0])


def get_playbooks(conn: psycopg.Connection, status: str | None = None) -> list[dict]:
    """Every playbook, optionally filtered by status.

    Takes an EXPLICIT status filter with no default, unlike get_playbook_for_scenario:
    this is the inventory/verification path (the loader's gates read it), and a silent
    'live' default here would report 5 rows where 32 exist and read as data loss.
    """
    if status is not None and status not in _VALID_PLAYBOOK_STATUSES:
        raise ValueError(f"invalid playbook status filter {status!r}")
    sql = f"SELECT {_PLAYBOOK_COLUMNS} FROM playbooks"
    params: tuple = ()
    if status is not None:
        sql += " WHERE status = %s"
        params = (status,)
    sql += " ORDER BY scenario_key, arm, source_artifact"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_playbook_row_to_dict(r) for r in rows]


# --- Layer D redesign (Brain/layer_d/, 2026-08-20) --------------------------------
# See the move_events/move_performance DDL notes in db/schema.sql for why every
# design choice here is the way it is. The two rules that matter:
#   * move_events UPSERTS on its natural key, so re-running a transcript refreshes
#     rather than duplicates (the old gap_events double-count defect).
#   * move_performance is only ever MATERIALIZED by full recompute from move_events
#     -- never incremented in place (the old `attempts = attempts + 1` defect).

_VALID_RATER_POPULATIONS = {"csm", "naren"}
_VALID_GRADER_ARMS = {"checks", "pairwise"}


def get_pairs_for_scenario_multilabel(
    conn: psycopg.Connection, scenario_key: str
) -> list[dict]:
    """Naren's routed moments for one scenario: trigger AND response per pair.

    Same predicate as get_responses_for_scenario_multilabel (primary OR secondary
    label, with the empty-array guard for pre-2026-06-29 rows), kept as a separate
    function for the same reason that one is separate from Layer C's clause-pool
    predicate: this is Layer D's benchmark-population source, and it needs the
    trigger text that the response-only reader deliberately does not fetch.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.pair_id, p.trigger_text, p.response_text, c.filename,
                   (p.scenario_key = %(key)s) AS is_primary
            FROM kb_pairs p JOIN calls c ON p.call_id = c.call_id
            WHERE p.scenario_key = %(key)s OR %(key)s = ANY(p.scenario_keys)
            ORDER BY p.pair_id
        """, {"key": scenario_key})
        rows = cur.fetchall()
    return [
        {"pair_id": r[0], "trigger_text": r[1], "response_text": r[2],
         "call_filename": r[3], "is_primary": r[4]}
        for r in rows
    ]


def upsert_move_event(conn: psycopg.Connection, event: dict) -> int:
    """Insert or refresh one scored moment, keyed by its natural identity.

    ON CONFLICT refreshes the verdict payload: the same moment graded again (a
    deliberate re-run, a k_runs change) REPLACES its previous verdicts rather than
    coexisting with them. gap_events had no such key and a double run silently
    double-counted -- this is the fix, enforced by the database.
    """
    if event["rater_population"] not in _VALID_RATER_POPULATIONS:
        raise ValueError(f"invalid rater_population {event['rater_population']!r}")
    if event["grader_arm"] not in _VALID_GRADER_ARMS:
        raise ValueError(f"invalid grader_arm {event['grader_arm']!r}")
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO move_events
              (rater_population, rater_id, call_id, source_ref, scenario_key,
               playbook_id, grader_arm, grader_model, via, response_outcome,
               trigger_text, response_text, verdicts, k_runs, run_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (rater_population, call_id, source_ref, playbook_id, grader_arm)
            DO UPDATE SET
                rater_id         = EXCLUDED.rater_id,
                scenario_key     = EXCLUDED.scenario_key,
                grader_model     = EXCLUDED.grader_model,
                via              = EXCLUDED.via,
                response_outcome = EXCLUDED.response_outcome,
                trigger_text     = EXCLUDED.trigger_text,
                response_text    = EXCLUDED.response_text,
                verdicts         = EXCLUDED.verdicts,
                k_runs           = EXCLUDED.k_runs,
                run_id           = EXCLUDED.run_id
            RETURNING move_event_id
        """, (
            event["rater_population"], event["rater_id"], event["call_id"],
            event["source_ref"], event["scenario_key"], event["playbook_id"],
            event["grader_arm"], event.get("grader_model", ""), event["via"],
            event["response_outcome"], event["trigger_text"], event["response_text"],
            json.dumps(event["verdicts"]), event.get("k_runs", 1),
            event.get("run_id"),
        ))
        move_event_id = cur.fetchone()[0]
    conn.commit()
    return move_event_id


def refresh_move_performance(conn: psycopg.Connection) -> int:
    """Rebuild move_performance from move_events, completely. Returns rows written.

    DELETE + INSERT rather than any incremental path: the aggregate is then
    reproducible from events alone (calibration/layer_d_replay.py proves it), and
    re-running after ANY combination of upserts converges to the same table.
    'unscored' verdicts are counted in their own column and excluded from attempts.
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM move_performance")
        cur.execute("""
            INSERT INTO move_performance
              (rater_population, rater_id, playbook_id, move_id, grader_arm,
               attempts, hits, partials, unscored)
            SELECT e.rater_population, e.rater_id, e.playbook_id,
                   v.value->>'move_id', e.grader_arm,
                   COUNT(*) FILTER (WHERE v.value->>'verdict' IN ('hit', 'partial', 'miss')),
                   COUNT(*) FILTER (WHERE v.value->>'verdict' = 'hit'),
                   COUNT(*) FILTER (WHERE v.value->>'verdict' = 'partial'),
                   COUNT(*) FILTER (WHERE v.value->>'verdict' = 'unscored')
            FROM move_events e
            CROSS JOIN LATERAL jsonb_array_elements(e.verdicts) AS v
            WHERE v.value->>'move_id' IS NOT NULL
            GROUP BY e.rater_population, e.rater_id, e.playbook_id,
                     v.value->>'move_id', e.grader_arm
        """)
        n = cur.rowcount
    conn.commit()
    return n


def get_move_rates(
    conn: psycopg.Connection, rater_population: str, grader_arm: str
) -> dict[str, list[dict]]:
    """move_performance rows for one population+arm, keyed by rater_id and shaped
    for layer_d.aggregate.MoveRate."""
    if rater_population not in _VALID_RATER_POPULATIONS:
        raise ValueError(f"invalid rater_population {rater_population!r}")
    if grader_arm not in _VALID_GRADER_ARMS:
        raise ValueError(f"invalid grader_arm {grader_arm!r}")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT rater_id, playbook_id, move_id, attempts, hits, partials, unscored
            FROM move_performance
            WHERE rater_population = %s AND grader_arm = %s
            ORDER BY rater_id, playbook_id, move_id
        """, (rater_population, grader_arm))
        rows = cur.fetchall()
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r[0], []).append({
            "playbook_id": r[1], "move_id": r[2], "attempts": r[3],
            "hits": r[4], "partials": r[5], "unscored": r[6],
        })
    return out


def get_hit_quotes(
    conn: psycopg.Connection, rater_id: str, grader_arm: str
) -> dict[tuple[int, str], list[str]]:
    """Verified evidence quotes per (playbook_id, move_id) for one rater -- the
    'your call' lines in the coaching report. Only 'hit' verdicts carry quotes, and
    every stored quote already passed verify_quote before it was written."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.playbook_id, v.value->>'move_id', v.value->>'quote'
            FROM move_events e
            CROSS JOIN LATERAL jsonb_array_elements(e.verdicts) AS v
            WHERE e.rater_id = %s AND e.grader_arm = %s
              AND v.value->>'verdict' = 'hit'
              AND COALESCE(v.value->>'quote', '') <> ''
            ORDER BY e.move_event_id
        """, (rater_id, grader_arm))
        rows = cur.fetchall()
    out: dict[tuple[int, str], list[str]] = {}
    for pb, move_id, quote in rows:
        out.setdefault((pb, move_id), []).append(quote)
    return out
