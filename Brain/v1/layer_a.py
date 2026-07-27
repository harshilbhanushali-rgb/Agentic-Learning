from __future__ import annotations
import psycopg
from config import Config
from shared.gemma import call_gemma
from shared.prompts import PROMPT_LAYER_A_V1
from shared import storage


def identify_scenarios(transcripts_text: str, config: Config) -> list[dict]:
    """Call Gemma only — no DB. Returns raw scenario list."""
    prompt = PROMPT_LAYER_A_V1.format(transcripts_text=transcripts_text)
    print("[Layer A] Calling Gemma for scenario identification...")
    result = call_gemma(prompt, config.gemma_api_keys)
    scenarios = result if isinstance(result, list) else result.get("scenarios", [])
    print(f"[Layer A] Gemma identified {len(scenarios)} scenario(s).")
    return scenarios


def store_scenarios(scenarios: list[dict], conn: psycopg.Connection) -> dict[str, dict]:
    """Upsert scenarios to DB — no Gemma. Returns scenario_map keyed by scenario_key."""
    scenario_map: dict[str, dict] = {}
    for s in scenarios:
        scenario_id = storage.upsert_scenario(conn, s)
        scenario_map[s["scenario_key"]] = {
            "scenario_id": scenario_id,
            "keyphrases": s.get("keyphrases", []),
            "sub_topic": s.get("sub_topic", ""),
            "primary_topic": s.get("primary_topic", ""),
        }
        print(f"  v {s['scenario_key']} -> scenario_id={scenario_id}")
    return scenario_map


def run_layer_a(
    transcripts_text: str,
    config: Config,
    conn: psycopg.Connection,
) -> dict[str, dict]:
    """Combined: identify via Gemma then store. Use split functions when conn lifecycle matters."""
    return store_scenarios(identify_scenarios(transcripts_text, config), conn)
