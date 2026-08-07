#!/usr/bin/env python3
"""Permanent, automatic homeless-topic graduation pass. See
docs/superpowers/specs/2026-08-07-response-taxonomy-auto-pass-design.md.

Runs after every V2 pipeline execution (called from v2/pipeline.py, wrapped in try/except at
that call site so a bug here can never fail the overall run). Clusters the sink pool exactly
the way dry_run_response_taxonomy.py does (via shared/response_taxonomy.py), tracks candidates
across runs by pair-id Jaccard overlap (never embedding similarity -- this codebase's Postgres
never stores vectors), and graduates any candidate that survives
response_taxonomy_consensus_runs consecutive runs into a real scenario.

Entry point: run_auto_pass(config, conn, run_id).
"""
from __future__ import annotations
import logging
import sys
import time
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

from config import Config
from shared import cluster_evidence, response_taxonomy, scenario_vectors, storage, topic_grouping
from shared.gemma import call_gemma
from shared.prompts import PROMPT_GRADUATE_SINK_TOPIC
from shared.tuning import load_tuning
from v2.layer_c import run_layer_c_v2

_LOG_PATH = Path(__file__).parent / "response_taxonomy_auto_pass.log"
_GEMMA_CALL_DELAY = 5
_NEAR_MISS_MARGIN = 0.05  # Decision 1: log (don't block) a second-best match within this band.

_logger = logging.getLogger("response_taxonomy_auto_pass")
if not _logger.handlers:
    _handler = logging.FileHandler(_LOG_PATH, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)


# --- Matching (Decision 1: ambiguous multi-match) --------------------------

def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _match_tracking_row(new_pair_ids: set, tracking_rows: list[dict], overlap_threshold: float) -> dict | None:
    """Best-match a candidate's pair-id set against existing tracking rows.

    Decision 1 (design spec): ambiguous multi-match is resolved by always taking the
    single highest-Jaccard row, never merging two rows -- this codebase has repeatedly
    rejected speculative-merge behavior elsewhere (by_cluster's destructive collapses,
    blended's instability), and an autonomous, unsupervised pass is exactly the wrong place
    to introduce a new merge mechanism. A second-best match within _NEAR_MISS_MARGIN of the
    winner is logged for visibility, not blocked on. Ties break toward the lower
    candidate_id for determinism.
    """
    scored = [
        (_jaccard(new_pair_ids, set(row["member_pair_ids"])), row)
        for row in tracking_rows
    ]
    qualifying = [(score, row) for score, row in scored if score >= overlap_threshold]
    if not qualifying:
        return None
    qualifying.sort(key=lambda sr: (-sr[0], sr[1]["candidate_id"]))
    best_score, best_row = qualifying[0]
    if len(qualifying) > 1 and qualifying[1][0] >= best_score - _NEAR_MISS_MARGIN:
        _logger.warning(
            "candidate matched multiple tracking rows within %.2f of the best score "
            "(best=%s score=%.3f, runner_up=%s score=%.3f) -- took the best match only",
            _NEAR_MISS_MARGIN, best_row["candidate_id"], best_score,
            qualifying[1][1]["candidate_id"], qualifying[1][0],
        )
    return best_row


# --- Tracking (Decision 2: candidate identity drift) ------------------------

def _load_tracking_rows(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT candidate_id, member_pair_ids, stable_pair_ids, consensus_count,
                   first_seen_run_id, last_seen_run_id, status
            FROM response_taxonomy_candidates
            WHERE status = 'tracking'
        """)
        rows = cur.fetchall()
    return [
        {"candidate_id": r[0], "member_pair_ids": r[1], "stable_pair_ids": r[2],
         "consensus_count": r[3], "first_seen_run_id": r[4], "last_seen_run_id": r[5],
         "status": r[6]}
        for r in rows
    ]


def _upsert_tracking_row(
    conn, run_id: str, new_pair_ids: set, matched_row: dict | None, label: str, description: str,
) -> None:
    """Insert a brand-new tracking row, or advance an existing one.

    Decision 2 (design spec): stable_pair_ids is the running intersection across every run a
    candidate has been seen in -- graduation reads from this, not the latest raw snapshot, so
    a pair that only appeared once drops out instead of riding along forever. If the
    intersection empties out, the candidate has already provably lost coherence and is
    discarded immediately rather than waiting for consensus_count to reach the threshold.
    """
    if matched_row is None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO response_taxonomy_candidates
                  (label, description, member_pair_ids, stable_pair_ids, consensus_count,
                   first_seen_run_id, last_seen_run_id, status)
                VALUES (%s, %s, %s, %s, 1, %s, %s, 'tracking')
                """,
                (label, description, sorted(new_pair_ids), sorted(new_pair_ids), run_id, run_id),
            )
        conn.commit()
        return

    if matched_row["last_seen_run_id"] == run_id:
        return  # idempotency guard: a no-op re-run of the same transcript set

    new_stable = set(matched_row["stable_pair_ids"]) & new_pair_ids
    with conn.cursor() as cur:
        if not new_stable:
            cur.execute(
                """
                UPDATE response_taxonomy_candidates
                   SET member_pair_ids = %s, stable_pair_ids = %s, status = %s,
                       last_seen_run_id = %s, updated_at = now()
                 WHERE candidate_id = %s
                """,
                (sorted(new_pair_ids), [], "discarded", run_id, matched_row["candidate_id"]),
            )
            _logger.info(
                "candidate_id=%s discarded: stable_pair_ids emptied out (drift)",
                matched_row["candidate_id"],
            )
        else:
            cur.execute(
                """
                UPDATE response_taxonomy_candidates
                   SET member_pair_ids = %s, stable_pair_ids = %s,
                       consensus_count = consensus_count + 1, last_seen_run_id = %s,
                       updated_at = now()
                 WHERE candidate_id = %s
                """,
                (sorted(new_pair_ids), sorted(new_stable), run_id, matched_row["candidate_id"]),
            )
    conn.commit()


# --- primary_topic_key resolution (fixes graduate_sink_topics.py:145's orphaning bug) ----

def _resolve_primary_topic_key(conn, merge_cosine_threshold: float, row: dict) -> str:
    """Fixes the primary_topic_key=None orphaning bug (graduate_sink_topics.py:145):
    primary_topics is only ever populated once, during Layer A's main grouping pass -- a
    scenario graduated afterward has no later grouping step to go through, so this resolves
    a real key instead of leaving the FK null forever.

    Reuses merge_cosine_threshold (the tight, subtopic-dedup threshold), not the looser
    primary_topic_merge_threshold used for INITIAL macro-grouping -- primary_topics rows are
    already tight-cohesion groups by the time they're stored (post tighten_coachable_groups),
    so the tight threshold is the comparable one, same reasoning passes_reconciliation_gate
    already applies to reusing an existing threshold rather than inventing a new one.
    """
    existing = storage.get_primary_topics(conn)
    by_key = {t["primary_topic_key"]: t for t in existing}
    keys, vecs = scenario_vectors.build_primary_topic_vecs(by_key)
    new_vec = scenario_vectors.scenario_vec(row)

    match = topic_grouping.match_existing_primary_topic(new_vec, keys, vecs, merge_cosine_threshold)
    if match is not None:
        return match

    storage.upsert_primary_topic(conn, {
        "primary_topic_key": row["scenario_key"],
        "label": row["scenario_key"].replace("_", " ").title(),
        "description": row["business_description"],
        "keyphrases": row["keyphrases"],
        "grouping_method": "graduated_singleton",
        "support_calls": row["support_calls"],
        "support_subtopics": 1,
        "call_coverage": row["call_coverage"],
    })
    return row["scenario_key"]


# --- Graduation --------------------------------------------------------------

def _support_stats_for_pairs(conn, pair_ids: list[int]) -> tuple[int, int, float]:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM calls")
        total_calls = int(cur.fetchone()[0])
        cur.execute(
            "SELECT COUNT(DISTINCT call_id) FROM kb_pairs WHERE pair_id = ANY(%s)",
            (pair_ids,),
        )
        distinct_calls = int(cur.fetchone()[0])
    return distinct_calls, len(pair_ids), distinct_calls / max(total_calls, 1)


def _generate_metadata(config: Config, proposed_label, proposed_description, reason, samples) -> dict:
    samples_block = "\n".join(
        f"  - CLIENT: {s['trigger_text'][:150]!r}\n    EXPERT: {s['response_text'][:400]!r}"
        for s in samples
    )
    prompt = PROMPT_GRADUATE_SINK_TOPIC.format(
        proposed_label=proposed_label, proposed_description=proposed_description,
        reason=reason, samples_block=samples_block,
    )
    result = call_gemma(prompt, config.gemma_api_keys)
    time.sleep(_GEMMA_CALL_DELAY)
    return result


def _discard(conn, candidate_id: int, reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE response_taxonomy_candidates SET status = %s, updated_at = now() WHERE candidate_id = %s",
            ("discarded", candidate_id),
        )
    conn.commit()
    _logger.info("candidate_id=%s discarded: %s", candidate_id, reason)


def _attempt_graduation(
    conn, config: Config, run_id: str, tracking_row: dict, nearest_coachable_sim: float,
    merge_cosine_threshold: float, proposed_label: str, proposed_description: str,
    reason: str, samples: list[dict],
) -> str | None:
    """Graduates a consensus-reaching candidate into a real scenario.

    Uses tracking_row["stable_pair_ids"] (Decision 2), never the latest raw member_pair_ids
    snapshot. Re-checks each pair's CURRENT is_coachable state (the cluster_6 protection --
    a pair already correctly homed to a real coachable scenario since this candidate was
    first tracked must never be disturbed). Reconciliation gate failure or zero surviving
    pairs both discard rather than force-routing. The write (scenario insert, primary_topic
    resolution, kb_pairs reroute, tracking-row status update) is one all-or-nothing sequence:
    any failure rolls back before Layer C ever sees a possibly-wrong pair set.
    """
    candidate_id = tracking_row["candidate_id"]
    stable_ids = list(tracking_row["stable_pair_ids"])

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT kb.pair_id, s.is_coachable
            FROM kb_pairs kb JOIN scenarios s ON s.scenario_id = kb.scenario_id
            WHERE kb.pair_id = ANY(%s)
            """,
            (stable_ids,),
        )
        rows = cur.fetchall()
    surviving = [pair_id for pair_id, is_coachable in rows if not is_coachable]

    if not surviving:
        _discard(conn, candidate_id, "zero pairs survived is_coachable re-check")
        return None

    if not cluster_evidence.passes_reconciliation_gate(nearest_coachable_sim, merge_cosine_threshold):
        _discard(conn, candidate_id, f"failed reconciliation gate ({nearest_coachable_sim:.3f})")
        return None

    meta = _generate_metadata(config, proposed_label, proposed_description, reason, samples)
    distinct_calls, n_pairs, call_coverage = _support_stats_for_pairs(conn, surviving)

    row = {
        "scenario_key": meta["scenario_key"],
        "business_description": meta["business_description"],
        "primary_topic": proposed_label,
        "keyphrases": meta.get("keyphrases") or [],
        "soft_skills": meta.get("soft_skills") or [],
        "bloom_level": meta.get("bloom_level") or "understand",
        "is_coachable": True,
        "cluster_kind": "scenario",
        "support_calls": distinct_calls,
        "support_clauses": n_pairs,
        "call_coverage": call_coverage,
        "triage_verdict": "graduated_from_sink_pool_auto_pass",
        "adjudication_reason": reason,
    }
    row["primary_topic_key"] = _resolve_primary_topic_key(conn, merge_cosine_threshold, row)

    try:
        scenario_id = storage.upsert_scenario(conn, row)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_pairs
                   SET scenario_key = %s, scenario_id = %s,
                       scenario_keys = array_append(scenario_keys, %s)
                 WHERE pair_id = ANY(%s)
                """,
                (row["scenario_key"], scenario_id, row["scenario_key"], surviving),
            )
            rerouted = cur.rowcount
        if rerouted != len(surviving):
            raise RuntimeError(
                f"candidate_id={candidate_id} rerouted {rerouted} pair(s), expected "
                f"exactly {len(surviving)} -- rolling back before Layer C ever sees a "
                f"possibly-wrong pair set."
            )
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE response_taxonomy_candidates
                   SET status = 'graduated', graduated_scenario_key = %s, updated_at = now()
                 WHERE candidate_id = %s
                """,
                (row["scenario_key"], candidate_id),
            )
    except Exception:
        conn.rollback()
        raise
    conn.commit()

    _logger.info(
        "candidate_id=%s graduated as scenario_key=%s (%s pairs, %s calls, %.1f%% coverage)",
        candidate_id, row["scenario_key"], n_pairs, distinct_calls, call_coverage * 100,
    )
    all_scenarios = {s["scenario_key"]: s for s in storage.get_scenarios(conn)}
    run_layer_c_v2({row["scenario_key"]: all_scenarios[row["scenario_key"]]}, config, conn, run_id="")
    return row["scenario_key"]


# --- Entry point --------------------------------------------------------------

def run_auto_pass(config: Config, conn, run_id: str) -> None:
    tuning = load_tuning()
    a = tuning.layer_a
    if not a.response_taxonomy_auto_pass_enabled:
        _logger.info("disabled -- skipping (run_id=%s)", run_id)
        return

    scenario_map = {r["scenario_key"]: r for r in storage.get_scenarios(conn)}
    pairs, total_calls = response_taxonomy.load_all_pairs(conn)
    if not pairs:
        _logger.info("no pairs available -- nothing to cluster (run_id=%s)", run_id)
        return

    vecs, labels, _mcs = response_taxonomy.cluster_corpus(pairs, tuning.layer_c, override=None)
    records = response_taxonomy.build_records(
        pairs, vecs, labels, scenario_map, total_calls, a.response_taxonomy_purity_gate, seed=0,
    )
    verdicts = response_taxonomy.adjudicate_clusters(records, config)

    new_candidates = [
        r for r in records
        if not r["purity_gated"] and verdicts.get(r["id"], {}).get("verdict") == "new_coachable_topic"
    ]
    _logger.info("run_id=%s: %d new_coachable_topic candidate(s) found", run_id, len(new_candidates))

    graduated = []
    for record in new_candidates:
        verdict = verdicts[record["id"]]
        new_pair_ids = set(record["member_pair_ids"])
        tracking_rows = _load_tracking_rows(conn)
        matched = _match_tracking_row(new_pair_ids, tracking_rows, a.response_taxonomy_candidate_match_overlap)
        _upsert_tracking_row(
            conn, run_id, new_pair_ids, matched,
            verdict.get("proposed_label", record["id"]), verdict.get("proposed_description", ""),
        )

        refreshed_candidate_id = matched["candidate_id"] if matched else None
        refreshed = next(
            (r for r in _load_tracking_rows(conn) if r["candidate_id"] == refreshed_candidate_id),
            None,
        ) if refreshed_candidate_id else next(
            (r for r in _load_tracking_rows(conn) if r["last_seen_run_id"] == run_id
             and set(r["member_pair_ids"]) == new_pair_ids),
            None,
        )
        if refreshed is None or refreshed["status"] != "tracking":
            continue
        if refreshed["consensus_count"] < a.response_taxonomy_consensus_runs:
            continue

        key = _attempt_graduation(
            conn, config, run_id, refreshed, record["nearest_coachable_sim"],
            a.merge_cosine_threshold, verdict.get("proposed_label", record["id"]),
            verdict.get("proposed_description", ""), verdict.get("reason", ""),
            record["samples"],
        )
        if key:
            graduated.append(key)

    _logger.info("run_id=%s: %d candidate(s) graduated: %s", run_id, len(graduated), graduated)
