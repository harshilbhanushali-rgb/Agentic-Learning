"""[DEBUG-dcl9] Throwaway: the production answer path with k=20 (Gemini sees the top-20 by
similarity and picks one), scored against the blind judges' verdicts. Delete after.

Usage: python ops/_diag_k20.py [k] [runs]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import serve_ask_naren as s  # noqa: E402
from ask_naren import answering  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ORACLE = ROOT / ".playwright-mcp" / "oracle"
K = int(sys.argv[1]) if len(sys.argv) > 1 else 20
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 2
key = json.loads((ORACLE / "key.json").read_text(encoding="utf-8"))
A = json.loads((ORACLE / "verdicts_A.json").read_text(encoding="utf-8"))
B = json.loads((ORACLE / "verdicts_B.json").read_text(encoding="utf-8"))


def verdict(qid: str, pair_id) -> tuple[int, str]:
    c = next(c for c in key[qid]["candidates"] if c["pair_id"] == pair_id)
    a, b = A[qid][c["cid"].split("-")[1]]["v"], B[qid][c["cid"].split("-")[1]]["v"]
    return c["rank"], ("RIGHT" if a == b == "YES" else ("maybe" if "YES" in (a, b) else "WRONG"))


async def main() -> None:
    pool, *_ = await s.build_pool(None)
    label_for, _account = s.build_label_resolver()
    gateway = s.AsyncGatewayClient()
    embed_query = s._embed_query(gateway)
    try:
        for qid, v in key.items():
            outs = []
            for _ in range(RUNS):
                t = time.time()
                r = await answering.answer_situation(v["question"], pool, gateway, embed_query=embed_query,
                                                     k=K, label_for=label_for)
                dt = time.time() - t
                if r["outcome"] == "answered":
                    rank, verd = verdict(qid, r["citation"]["pair_id"])
                    outs.append(f"answers from rank {rank} [{verd}] {dt:.0f}s")
                else:
                    outs.append(f"declines ({r['reason']}) {dt:.0f}s")
            print(f"{qid} (k=1 today: {v['outcome']}) -> " + " | ".join(outs), flush=True)
    finally:
        await gateway.aclose()
        await pool.aclose()


asyncio.run(main())
