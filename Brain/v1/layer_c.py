from __future__ import annotations
import psycopg
from config import Config
from shared.gemma import call_gemma
from shared.prompts import PROMPT_LAYER_C_V1
from shared import storage, checkpoint


def run_layer_c(
    scenario_map: dict[str, dict],
    config: Config,
    conn: psycopg.Connection,
    run_id: str = "",
) -> None:
    """For each scenario, fetch Naren responses and generate rubrics via Gemma."""
    for scenario_key, info in scenario_map.items():
        if run_id and checkpoint.is_done(run_id, scenario_key, "layer_c"):
            print(f"[Layer C] {scenario_key} already done — skipping.")
            continue
        print(f"[Layer C] Processing scenario: {scenario_key}")
        responses = storage.get_naren_responses_for_scenario(conn, scenario_key)
        if not responses:
            print(f"  ! No Naren responses found for {scenario_key} -- skipping.")
            continue

        responses_text = "\n\n".join(
            f"[{r['call_filename']}]\n{r['response_text']}"
            for r in responses
        )
        prompt = PROMPT_LAYER_C_V1.format(
            scenario_key=scenario_key,
            sub_topic=info["sub_topic"],
            primary_topic=info["primary_topic"],
            n_instances=len(responses),
            responses_text=responses_text,
        )
        result = call_gemma(prompt, config.gemma_api_key)
        rubric = {
            "scenario_id": info["scenario_id"],
            "scenario_key": scenario_key,
            "milestones": result.get("milestones", []),
            "soft_skill_rubric": result.get("soft_skill_rubric", {}),
            "anti_patterns": result.get("anti_patterns", []),
            "pipeline_version": "v1",
        }
        rubric_id = storage.upsert_rubric(conn, rubric)
        if run_id:
            checkpoint.mark_done(run_id, scenario_key, "layer_c")
        print(f"  v Rubric stored (id={rubric_id}), {len(rubric['milestones'])} milestone(s).")
