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


def upsert_scenario(conn: psycopg.Connection, scenario: dict) -> int:
    """Insert or update a scenario.

    The evidence columns default so that V1's Layer A, which has no clustering
    evidence to report, can keep calling this unchanged.

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
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO kb_pairs
              (call_id, scenario_id, scenario_key, scenario_keys, turn_index,
               trigger_text, response_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (call_id, turn_index) DO NOTHING
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
