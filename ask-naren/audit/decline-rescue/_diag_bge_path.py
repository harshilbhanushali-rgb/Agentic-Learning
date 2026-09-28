"""[DEBUG-dcl9] Throwaway: bge-reranker-v2-m3 inside the REAL answer path.

For each question: the shipped answer (rank-1), then bge reranks the same top-50 (client line
+ Naren reply), and two policies are run through the production prompt, model and grounding
gate:
  rescue  -- keep the shipped answer; only if it declined, try bge's top 3 in order.
  replace -- always try bge's top 3 in order (answer from the first the model accepts).
The source each policy answers from is scored against the blind judges' verdicts
(.playwright-mcp/oracle). 6 rerank calls in total. Delete after the diagnosis.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pinecone import Pinecone  # noqa: E402

import serve_ask_naren as s  # noqa: E402
from ask_naren import answering, grounding  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ORACLE = ROOT / ".playwright-mcp" / "oracle"
TRIES = 3
env = {l.split("=", 1)[0]: l.split("=", 1)[1].strip().strip('"')
       for l in (ROOT / "Brain" / ".env").read_text(encoding="utf-8").splitlines()
       if "=" in l and not l.startswith("#")}
pc = Pinecone(api_key=env["PINECONE_API_KEY"])
key = json.loads((ORACLE / "key.json").read_text(encoding="utf-8"))
A = json.loads((ORACLE / "verdicts_A.json").read_text(encoding="utf-8"))
B = json.loads((ORACLE / "verdicts_B.json").read_text(encoding="utf-8"))


def verdict(qid: str, pair_id) -> str:
    c = next(c for c in key[qid]["candidates"] if c["pair_id"] == pair_id)
    a, b = A[qid][c["cid"].split("-")[1]]["v"], B[qid][c["cid"].split("-")[1]]["v"]
    return "RIGHT" if a == b == "YES" else ("maybe" if "YES" in (a, b) else "WRONG")


async def try_answer(gateway, situation: str, pair: dict) -> bool:
    prompt = answering.build_prompt(situation, pair)
    for _ in range(answering.MAX_ATTEMPTS):
        payload, _ = await gateway.chat_json(
            prompt, model=answering.CHAT_MODEL, reasoning_effort=answering.REASONING_EFFORT,
            temperature=answering.TEMPERATURE, max_tokens=answering.MAX_TOKENS, no_cache=True)
        if payload.get("declined"):
            return False
        if grounding.check(payload, grounding.from_pairs([pair])).passed:
            return True
    return False


async def first_accepted(gateway, situation, pairs) -> tuple[dict | None, int | None]:
    for i, p in enumerate(pairs[:TRIES], 1):
        if await try_answer(gateway, situation, p):
            return p, i
    return None, None


async def main() -> None:
    pool, *_ = await s.build_pool(None)
    gateway = s.AsyncGatewayClient()
    embed_query = s._embed_query(gateway)
    try:
        for qid, v in key.items():
            q = v["question"]
            top = await pool.topk((await embed_query([q]))[0], 50)
            pairs = [m.pair for m in top]
            t = time.time()
            rr = pc.inference.rerank(model="bge-reranker-v2-m3", query=q, top_n=len(pairs),
                                     documents=[f"Client: {p['trigger_text']}\nNaren: {p['response_text']}" for p in pairs],
                                     parameters={"truncate": "END"})
            rerank_s = time.time() - t
            reranked = [pairs[d.index] for d in rr.data]
            orig_rank = {id(p): i for i, p in enumerate(pairs, 1)}

            shipped_ok = await try_answer(gateway, q, pairs[0])
            shipped = f"answers from rank 1 [{verdict(qid, pairs[0]['pair_id'])}]" if shipped_ok else "declines"

            if shipped_ok:
                rescue = shipped + " (untouched)"
            else:
                p, i = await first_accepted(gateway, q, reranked)
                rescue = (f"answers from bge #{i} (orig rank {orig_rank[id(p)]}) [{verdict(qid, p['pair_id'])}]"
                          if p else "still declines")
            p, i = await first_accepted(gateway, q, reranked)
            replace = (f"answers from bge #{i} (orig rank {orig_rank[id(p)]}) [{verdict(qid, p['pair_id'])}]"
                       if p else "declines")
            print(f"{qid} ({v['outcome']} live) rerank {rerank_s:.1f}s\n   shipped : {shipped}\n"
                  f"   rescue  : {rescue}\n   replace : {replace}", flush=True)
    finally:
        await gateway.aclose()
        await pool.aclose()


asyncio.run(main())
