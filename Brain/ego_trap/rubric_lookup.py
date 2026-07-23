from __future__ import annotations
import psycopg
from ego_trap.transcript_parser import EgoTrapRole, EgoTrapTurn, turns_until_next_client
from shared import storage

_MAX_BENCHMARK_EXAMPLES = 2


def fetch_rubric(conn: psycopg.Connection, scenario_key: str) -> dict | None:
    """Steps 1-2: fetch the Layer C rubric for a detected scenario, or None if unmapped."""
    return storage.get_rubric_for_scenario(conn, scenario_key)


def get_benchmark_reference(conn: psycopg.Connection, scenario_key: str) -> str:
    """Naren's benchmark response(s) for this scenario, passed to Step 3 as reference only."""
    responses = storage.get_naren_responses_for_scenario(conn, scenario_key)
    return "\n\n".join(r["response_text"] for r in responses[:_MAX_BENCHMARK_EXAMPLES])


def extract_csm_response_window(turns: list[EgoTrapTurn], signal: dict) -> str:
    """All CSM turns after the signal's CLIENT turn, up to (not including) the next CLIENT turn."""
    following = turns_until_next_client(turns, signal["turn_index"])
    return " ".join(t.text for t in following if t.role == EgoTrapRole.CSM)
