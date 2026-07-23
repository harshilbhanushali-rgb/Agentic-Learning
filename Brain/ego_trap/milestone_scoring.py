from __future__ import annotations
from config import Config
from shared.gemma import call_gemma
from shared.prompts import (
    PROMPT_STEP3_MILESTONE_SCORE,
    PROMPT_STEP3_MILESTONE_SCORE_BATCH,
    PROMPT_STEP3_SOFT_SKILL_SCORE,
    PROMPT_STEP3_SOFT_SKILL_SCORE_BATCH,
)

_DEFAULT_SKILL_NAME = "Soft Skill Execution"
_VALID_VERDICTS = {"full_hit", "partial_hit", "miss"}


def _normalize_verdict(raw: dict) -> str:
    verdict = raw.get("verdict")
    return verdict if verdict in _VALID_VERDICTS else "miss"


def score_milestones(
    rubric: dict,
    csm_response_text: str,
    benchmark_response: str,
    config: Config,
) -> list[dict]:
    """Step 3: one Gemma call per rubric milestone. milestone_id is synthesized as f"M{order}"."""
    results = []
    for milestone in rubric.get("milestones", []):
        milestone_id = f"M{milestone['order']}"
        prompt = PROMPT_STEP3_MILESTONE_SCORE.format(
            milestone_description=milestone.get("description", ""),
            detection_hint=milestone.get("detection_hint", ""),
            benchmark_response=benchmark_response,
            csm_response=csm_response_text,
        )
        result = call_gemma(prompt, config.gemma_api_key)
        results.append({
            "milestone_id": milestone_id,
            "milestone_description": milestone.get("description", ""),
            "verdict": _normalize_verdict(result),
            "confidence": result.get("confidence", "low"),
            "reason": result.get("reason", ""),
            "quote": result.get("quote", ""),
            "gap_to_ideal": result.get("gap_to_ideal", ""),
        })
    return results


def score_soft_skills(
    rubric: dict,
    csm_response_text: str,
    skill_names: list[str],
    config: Config,
) -> list[dict]:
    """Step 3: score the rubric's soft_skill_rubric against each of the scenario's soft_skills labels."""
    soft_skill_rubric = rubric.get("soft_skill_rubric") or {}
    if not soft_skill_rubric:
        return []

    names = skill_names or [_DEFAULT_SKILL_NAME]
    results = []
    for skill_name in names:
        prompt = PROMPT_STEP3_SOFT_SKILL_SCORE.format(
            skill_name=skill_name,
            excellent_execution=soft_skill_rubric.get("excellent_execution", ""),
            failing_execution=soft_skill_rubric.get("failing_execution", ""),
            csm_response=csm_response_text,
        )
        result = call_gemma(prompt, config.gemma_api_key)
        results.append({
            "skill": skill_name,
            "rating": result.get("rating", "adequate"),
            "confidence": result.get("confidence", "low"),
            "reason": result.get("reason", ""),
        })
    return results


def score_milestones_batch(items: list[dict], config: Config) -> list[list[dict]]:
    """Batched Step 3: one Gemma call scores every milestone across all items at once.

    items: list of {"rubric": dict, "csm_response_text": str, "benchmark_response": str}
    Returns: list (same order/length as items) of milestone-result lists, same shape as score_milestones().
    """
    entries = []
    lines = []
    for i, item in enumerate(items):
        for milestone in item["rubric"].get("milestones", []):
            milestone_id = f"M{milestone['order']}"
            entry_id = f"S{i}_{milestone_id}"
            entries.append((i, milestone_id, milestone.get("description", "")))
            lines.append(
                f"- id: {entry_id}\n"
                f"  MILESTONE: {milestone.get('description', '')}\n"
                f"  DETECTION HINT: {milestone.get('detection_hint', '')}\n"
                f"  NAREN'S BENCHMARK RESPONSE (for reference only): {item['benchmark_response']}\n"
                f"  CSM RESPONSE: \"{item['csm_response_text']}\""
            )

    results_by_item: list[list[dict]] = [[] for _ in items]
    if not lines:
        return results_by_item

    prompt = PROMPT_STEP3_MILESTONE_SCORE_BATCH.format(items_block="\n\n".join(lines))
    raw = call_gemma(prompt, config.gemma_api_key)
    raw_list = raw if isinstance(raw, list) else raw.get("results", [])
    by_id = {r["id"]: r for r in raw_list if "id" in r}

    for i, milestone_id, description in entries:
        r = by_id.get(f"S{i}_{milestone_id}", {})
        results_by_item[i].append({
            "milestone_id": milestone_id,
            "milestone_description": description,
            "verdict": _normalize_verdict(r),
            "confidence": r.get("confidence", "low"),
            "reason": r.get("reason", ""),
            "quote": r.get("quote", ""),
            "gap_to_ideal": r.get("gap_to_ideal", ""),
        })
    return results_by_item


def score_soft_skills_batch(items: list[dict], config: Config) -> list[list[dict]]:
    """Batched Step 3: one Gemma call scores every soft skill across all items at once.

    items: list of {"rubric": dict, "csm_response_text": str, "skill_names": list[str]}
    Returns: list (same order/length as items) of soft-skill-result lists, same shape as score_soft_skills().
    """
    entries = []
    lines = []
    for i, item in enumerate(items):
        soft_skill_rubric = item["rubric"].get("soft_skill_rubric") or {}
        if not soft_skill_rubric:
            continue
        names = item["skill_names"] or [_DEFAULT_SKILL_NAME]
        for skill_name in names:
            safe_name = skill_name.replace(" ", "_")
            entry_id = f"S{i}_{safe_name}"
            entries.append((i, skill_name, entry_id))
            lines.append(
                f"- id: {entry_id}\n"
                f"  SOFT SKILL: {skill_name}\n"
                f"  EXCELLENT EXECUTION: {soft_skill_rubric.get('excellent_execution', '')}\n"
                f"  FAILING EXECUTION: {soft_skill_rubric.get('failing_execution', '')}\n"
                f"  CSM RESPONSE: \"{item['csm_response_text']}\""
            )

    results_by_item: list[list[dict]] = [[] for _ in items]
    if not lines:
        return results_by_item

    prompt = PROMPT_STEP3_SOFT_SKILL_SCORE_BATCH.format(items_block="\n\n".join(lines))
    raw = call_gemma(prompt, config.gemma_api_key)
    raw_list = raw if isinstance(raw, list) else raw.get("results", [])
    by_id = {r["id"]: r for r in raw_list if "id" in r}

    for i, skill_name, entry_id in entries:
        r = by_id.get(entry_id, {})
        results_by_item[i].append({
            "skill": skill_name,
            "rating": r.get("rating", "adequate"),
            "confidence": r.get("confidence", "low"),
            "reason": r.get("reason", ""),
        })
    return results_by_item
