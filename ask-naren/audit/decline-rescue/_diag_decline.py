"""[DEBUG-dcl9] Throwaway diagnostic for the reply_to_client no_close_match declines.

Loads the pool once exactly as ops/serve_ask_naren.py does, then for each question:
  1. runs the real responding.respond path (the user's symptom: outcome + reason),
  2. shows the single exchange answer_situation hands the model (client turn + Naren reply),
  3. re-asks the model the SAME prompt N times and prints each raw payload's `declined`.
Delete after the diagnosis.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import serve_ask_naren as s  # noqa: E402
from ask_naren import answering, responding  # noqa: E402

N_REPEATS = 3

QUESTIONS = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))


async def main() -> None:
    pool, moves_by, playbooks_by, coachable, following_by = await s.build_pool(None)
    label_for, account_for = s.build_label_resolver()
    gateway = s.AsyncGatewayClient()
    embed_query = s._embed_query(gateway)
    out = []
    try:
        for q in QUESTIONS:
            resp = await responding.respond(
                q, pool, gateway, embed_query=embed_query, thread=(), label_for=label_for,
                moves_for=None, playbook_for=playbooks_by.get, scenarios_for=lambda: coachable,
                following_for=lambda pid: following_by.get(pid, []), account_for=account_for)
            intake = resp.get("intake") or {}
            rq = intake.get("retrieval_query") or q
            vec = (await embed_query([rq]))[0]
            top = (await pool.topk(vec, 3))
            pair = top[0].pair
            prompt = answering.build_prompt(rq if intake.get("intent") else q, pair)
            verdicts = []
            for _ in range(N_REPEATS):
                payload, _ = await gateway.chat_json(
                    prompt, model=answering.CHAT_MODEL, reasoning_effort=answering.REASONING_EFFORT,
                    temperature=answering.TEMPERATURE, max_tokens=answering.MAX_TOKENS, no_cache=True)
                verdicts.append(bool(payload.get("declined")))
            row = {
                "question": q,
                "intent": intake.get("intent"),
                "embedded": rq,
                "outcome": resp.get("outcome"), "reason": resp.get("reason"),
                "top3": [(round(m.cosine, 4), m.pair["scenario_key"], m.pair.get("pair_id")) for m in top],
                "shown_client_said": pair["trigger_text"],
                "shown_naren_replied": pair["response_text"][:700],
                "repeat_declined": verdicts,
            }
            out.append(row)
            print(json.dumps(row, indent=2, ensure_ascii=False), flush=True)
    finally:
        await gateway.aclose()
        await pool.aclose()
    Path(sys.argv[2]).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


asyncio.run(main())
