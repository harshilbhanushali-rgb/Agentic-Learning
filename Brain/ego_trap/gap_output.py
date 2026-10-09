"""Steps 4-5: assemble gap records, write them, and report accumulated gap profiles."""
from __future__ import annotations

import psycopg

from shared import storage
from shared.tuning import LayerDTuning


def milestone_miss_rate(attempts: int, hits: int, partial_hits: int) -> float:
    """1 - the weighted score db/schema.sql documents for milestone_performance.

    Defined as the exact complement, so a reported score and its severity bucket can
    never disagree. attempts == 0 returns 0.0: a milestone nobody attempted has no
    gap, and calling it 'critical' would be a lie about a CSM who was never tested.
    """
    if attempts <= 0:
        return 0.0
    return (attempts - hits - 0.5 * partial_hits) / attempts


def compute_severity(miss_rate: float, tuning: LayerDTuning) -> str:
    """Severity bucket for a CSM's ACCUMULATED miss rate on one milestone.

    Takes an aggregate over milestone_performance, never a single gap_event: one
    event's miss_rate is only ever 0.0 / 0.5 / 1.0, so per-event severity is always
    'low' or 'critical' and carries no information. Not stored anywhere for the same
    reason the weighted score is not stored -- it changes every time attempts
    increments.
    """
    for threshold, label in (
        (tuning.gap_severity_critical_miss_rate, "critical"),
        (tuning.gap_severity_high_miss_rate, "high"),
        (tuning.gap_severity_moderate_miss_rate, "moderate"),
    ):
        if miss_rate >= threshold:
            return label
    return "low"


def format_gap_profile(
    rows: list[dict],
    milestones_by_rubric: dict[int, list[dict]],
    tuning: LayerDTuning,
) -> str:
    """Render one CSM's accumulated milestone gap profile. Pure -- no DB, no I/O.

    milestones_by_rubric supplies the human-readable label, because
    milestone_performance stores only the positional id ("M3"). Indexed positionally,
    which milestone_ids's scheme makes well-defined, and tolerant of a short or
    missing list: a later Layer C run can shrink a rubric under the same rubric_id.
    """
    if not rows:
        return "  (no milestone attempts recorded)"

    scored = []
    for r in rows:
        rate = milestone_miss_rate(r["attempts"], r["hits"], r["partial_hits"])
        milestones = milestones_by_rubric.get(r["rubric_id"]) or []
        try:
            position = int(str(r["milestone_id"]).lstrip("M")) - 1
        except ValueError:
            position = -1
        label = ""
        if 0 <= position < len(milestones):
            label = milestones[position].get("label") or ""
        scored.append((rate, r, label))

    scored.sort(key=lambda x: -x[0])
    lines = [
        f"  {'severity':<9} {'miss':>5}  {'a/h/p':>8}  {'ver':<3} scenario / milestone"
    ]
    for rate, r, label in scored:
        lines.append(
            f"  {compute_severity(rate, tuning):<9} {rate:>5.2f}  "
            f"{r['attempts']}/{r['hits']}/{r['partial_hits']:>2}  "
            f"{(r.get('pipeline_version') or '?'):<3} "
            f"{r['scenario_key']} :: {r['milestone_id']}"
            f"{' — ' + label if label else ''}"
        )
    return "\n".join(lines)


def build_gap_record(
    call_id: str,
    csm_id: str,
    scenario_key: str,
    rubric_id: int,
    signal: dict,
    milestone_results: list[dict],
    soft_skill_results: list[dict],
    pipeline_version: str | None = None,
) -> dict:
    """Step 4: assemble the gap output structure.

    Each milestone gap carries a COPY of the Layer C evidence it was scored against,
    rather than a reference back to rubrics.milestones. That is deliberate:
    upsert_rubric replaces `milestones` in place under the same rubric_id, so the next
    Layer C run destroys the evidence a past gap_event was graded against. The copy is
    the only durable record.

    Evidence appears only on non-full_hit entries, because `gaps` holds only those --
    adding hits would break the column's documented semantics and any reader counting
    len(gaps). Hit-side evidence is recoverable by joining gap_events.rubric_id to
    rubrics.milestones and indexing positionally.
    """
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
            "evidence": m.get("evidence", {}),
            "rubric_pipeline_version": pipeline_version,
            # Which model produced this verdict. Set by score_milestones_batch from
            # gemma.LAST_MODEL_USED; persisted here because the model chain downgrades
            # silently on a rate limit, and a verdict whose scorer is unknown cannot be
            # compared against one from a different run.
            "scored_by": m.get("scored_by"),
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
    tuning: LayerDTuning,
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

    if tuning.gap_events_enabled:
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
    tuning: LayerDTuning,
) -> None:
    """Step 0 true miss (response_outcome == "none"): log Signal_Recognition_Failure.

    No milestone scoring runs -- nobody addressed the client's point.
    """
    storage.upsert_csm(conn, csm_id, csm_name)
    storage.upsert_signal_recognition_gap(conn, csm_id, scenario_key, recognized=False)

    if tuning.gap_events_enabled:
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
    tuning: LayerDTuning,
) -> None:
    """Step 0 response_outcome == "other_joveo": a teammate addressed the point.

    Reclassified out of Signal_Recognition_Failure -- the point WAS handled, just not
    by the CSM personally, so it should not count against the CSM's recognition rate.
    Kept out of signal_recognition_gaps (which only tracks the CSM's own
    recognized/missed) but preserved in gap_events for traceability. No milestone
    scoring runs -- there is no CSM response to score.
    """
    storage.upsert_csm(conn, csm_id, csm_name)

    if tuning.gap_events_enabled:
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


def write_rubric_coverage_gap(
    conn: psycopg.Connection,
    csm_id: str,
    csm_name: str,
    call_id: str,
    scenario_key: str,
    signal: dict,
    rubric_status: str | None,
    tuning: LayerDTuning,
) -> None:
    """A coachable scenario was recognized, but Layer C produced no rubric for it.

    Previously this case produced NO DB row anywhere: Step 0 detected a real client
    signal, Stage 2 found no rubric, and the run printed UNMAPPED_SCENARIO and moved
    on. That silently discarded Layer D's most actionable output -- "a client raised
    this and we have no answer key" is a gap in the KNOWLEDGE BASE, and knowing which
    topics keep recurring without a rubric is what tells Layer C where to look next.

    Deliberately does NOT touch signal_recognition_gaps. The CSM recognized the signal
    and answered it; there is simply nothing to score against. Writing recognized=True
    would inflate the recognition rate with un-scored events, and missed=True would be
    a straightforward lie.

    Zero schema change: gaps is unconstrained JSONB, gap_type is already a free-form
    string, and gap_events.rubric_id is nullable.
    """
    storage.upsert_csm(conn, csm_id, csm_name)

    if tuning.gap_events_enabled:
        storage.insert_gap_event(conn, {
            "call_id": call_id,
            "csm_id": csm_id,
            "scenario_key": scenario_key,
            "rubric_id": None,
            "signal_turn_index": signal["turn_index"],
            "gaps": [{
                "gap_type": "Rubric_Coverage_Gap",
                "client_utterance": signal["client_utterance"],
                "rubric_status": rubric_status,
                "reason": "Coachable scenario recognized, but no rubric exists to score against.",
            }],
            "milestones_hit": [],
            "milestones_missed": [],
        })
