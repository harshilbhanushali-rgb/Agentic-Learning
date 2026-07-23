import json
import psycopg

_database_url: str = ""


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
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO scenarios
              (scenario_key, primary_topic, sub_topic, keyphrases, soft_skills, bloom_level)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (scenario_key) DO UPDATE SET
                primary_topic = EXCLUDED.primary_topic,
                sub_topic     = EXCLUDED.sub_topic,
                keyphrases    = EXCLUDED.keyphrases,
                soft_skills   = EXCLUDED.soft_skills,
                bloom_level   = EXCLUDED.bloom_level
            RETURNING scenario_id
        """, (
            scenario["scenario_key"],
            scenario["primary_topic"],
            scenario["sub_topic"],
            scenario["keyphrases"],
            scenario["soft_skills"],
            scenario["bloom_level"],
        ))
        scenario_id = cur.fetchone()[0]
    conn.commit()
    return scenario_id


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
    with conn.cursor() as cur:
        cur.execute(
            "SELECT scenario_id, scenario_key, sub_topic, primary_topic, keyphrases, soft_skills "
            "FROM scenarios"
        )
        rows = cur.fetchall()
    return [
        {"scenario_id": r[0], "scenario_key": r[1], "sub_topic": r[2],
         "primary_topic": r[3], "keyphrases": r[4], "soft_skills": r[5]}
        for r in rows
    ]


def get_naren_responses_for_scenario(conn: psycopg.Connection, scenario_key: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.pair_id, p.response_text, c.filename
            FROM kb_pairs p JOIN calls c ON p.call_id = c.call_id
            WHERE p.scenario_key = %s
        """, (scenario_key,))
        rows = cur.fetchall()
    return [{"pair_id": r[0], "response_text": r[1], "call_filename": r[2]} for r in rows]


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
    with conn.cursor() as cur:
        cur.execute("""
            SELECT rubric_id, scenario_id, scenario_key, milestones, soft_skill_rubric, anti_patterns
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
    }


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
