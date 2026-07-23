from __future__ import annotations
import psycopg
from ego_trap import settings
from shared import storage

# Miss-rate -> severity thresholds from Ego_trap.md section 5.
_SEVERITY_THRESHOLDS = (
    (0.60, "critical"),
    (0.35, "high"),
    (0.15, "moderate"),
)


def compute_severity(miss_rate: float) -> str:
    for threshold, label in _SEVERITY_THRESHOLDS:
        if miss_rate >= threshold:
            return label
    return "low"


def build_gap_record(
    call_id: str,
    csm_id: str,
    scenario_key: str,
    rubric_id: int,
    signal: dict,
    milestone_results: list[dict],
    soft_skill_results: list[dict],
) -> dict:
    """Step 4: assemble the gap output structure from Ego_trap.md section 5."""
    gaps = []
    milestones_hit = []
    milestones_partial_hit = []
    milestones_missed = []

    for m in milestone_results:
        verdict = m["verdict"]
        if verdict == "full_hit":
            milestones_hit.append(m["milestone_id"])
            continue

        if verdict == "partial_hit":
            milestones_partial_hit.append(m["milestone_id"])
        else:
            milestones_missed.append(m["milestone_id"])

        gaps.append({
            "gap_type": "Milestone_Omission",
            "milestone_id": m["milestone_id"],
            "milestone_description": m["milestone_description"],
            "verdict": verdict,
            "confidence": m["confidence"],
            "reason": m["reason"],
            "quote": m["quote"],
            "gap_to_ideal": m["gap_to_ideal"],
        })

    for s in soft_skill_results:
        if s["rating"] == "failing":
            gaps.append({
                "gap_type": "Soft_Skill_Failure",
                "skill": s["skill"],
                "rating": s["rating"],
                "reason": s["reason"],
            })

    return {
        "call_id": call_id,
        "csm_id": csm_id,
        "scenario_key": scenario_key,
        "rubric_id": rubric_id,
        "turn_index": signal["turn_index"],
        "gaps": gaps,
        "milestones_hit": milestones_hit,
        "milestones_partial_hit": milestones_partial_hit,
        "milestones_missed": milestones_missed,
    }


def write_gap_record(
    conn: psycopg.Connection,
    csm_id: str,
    csm_name: str,
    rubric_id: int,
    gap_record: dict,
) -> None:
    storage.upsert_csm(conn, csm_id, csm_name)
    for milestone_id in gap_record["milestones_hit"]:
        storage.upsert_milestone_performance(
            conn, csm_id, rubric_id, milestone_id, gap_record["scenario_key"], verdict="full_hit"
        )
    for milestone_id in gap_record["milestones_partial_hit"]:
        storage.upsert_milestone_performance(
            conn, csm_id, rubric_id, milestone_id, gap_record["scenario_key"], verdict="partial_hit"
        )
    for milestone_id in gap_record["milestones_missed"]:
        storage.upsert_milestone_performance(
            conn, csm_id, rubric_id, milestone_id, gap_record["scenario_key"], verdict="miss"
        )
    storage.upsert_signal_recognition_gap(conn, csm_id, gap_record["scenario_key"], recognized=True)

    if settings.ENABLE_GAP_EVENTS:
        storage.insert_gap_event(conn, {
            "call_id": gap_record["call_id"],
            "csm_id": csm_id,
            "scenario_key": gap_record["scenario_key"],
            "rubric_id": rubric_id,
            "signal_turn_index": gap_record["turn_index"],
            "gaps": gap_record["gaps"],
            "milestones_hit": gap_record["milestones_hit"],
            "milestones_partial_hit": gap_record["milestones_partial_hit"],
            "milestones_missed": gap_record["milestones_missed"],
        })


def write_signal_recognition_failure(
    conn: psycopg.Connection,
    csm_id: str,
    csm_name: str,
    call_id: str,
    scenario_key: str,
    signal: dict,
) -> None:
    """Step 0 true miss (response_outcome == "none"): log Signal_Recognition_Failure.

    No milestone scoring runs — nobody addressed the client's point.
    """
    storage.upsert_csm(conn, csm_id, csm_name)
    storage.upsert_signal_recognition_gap(conn, csm_id, scenario_key, recognized=False)

    if settings.ENABLE_GAP_EVENTS:
        storage.insert_gap_event(conn, {
            "call_id": call_id,
            "csm_id": csm_id,
            "scenario_key": scenario_key,
            "rubric_id": None,
            "signal_turn_index": signal["turn_index"],
            "gaps": [{
                "gap_type": "Signal_Recognition_Failure",
                "client_utterance": signal["client_utterance"],
                "reason": "CSM did not respond to a recognized client signal.",
            }],
            "milestones_hit": [],
            "milestones_missed": [],
        })


def write_deferred_to_teammate(
    conn: psycopg.Connection,
    csm_id: str,
    csm_name: str,
    call_id: str,
    scenario_key: str,
    signal: dict,
) -> None:
    """Step 0 response_outcome == "other_joveo": a teammate addressed the client's point, not the CSM.

    Reclassified out of Signal_Recognition_Failure — the point WAS handled, just not by the CSM
    personally, so it should not count against the CSM's recognition rate. Kept out of
    signal_recognition_gaps (which only tracks the CSM's own recognized/missed) but preserved in
    gap_events for traceability. No milestone scoring runs — there is no CSM response to score.
    """
    storage.upsert_csm(conn, csm_id, csm_name)

    if settings.ENABLE_GAP_EVENTS:
        storage.insert_gap_event(conn, {
            "call_id": call_id,
            "csm_id": csm_id,
            "scenario_key": scenario_key,
            "rubric_id": None,
            "signal_turn_index": signal["turn_index"],
            "gaps": [{
                "gap_type": "Deferred_To_Teammate",
                "client_utterance": signal["client_utterance"],
                "reason": "A Joveo teammate addressed this client signal, not the CSM.",
            }],
            "milestones_hit": [],
            "milestones_missed": [],
        })
