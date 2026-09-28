"""[DEBUG-dcl9] Throwaway: dump the top-50 exchanges per question for a blind answerability read.

Embeds each question's retrieval_query (6 embedding calls, no chat), pulls top-50 from the
pool exactly as answer_situation does, and writes:
  - key file (private): question id -> [(candidate id, rank, cosine, pair_id, scenario)]
  - blind file: per question, the client's words + the 50 candidates SHUFFLED, with no rank,
    cosine, scenario or outcome, so the judge cannot tell which question declined.
Delete after the diagnosis.
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import serve_ask_naren as s  # noqa: E402

K = 50
diag = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))  # output of _diag_decline.py
out_dir = Path(sys.argv[2])


async def main() -> None:
    pool, *_ = await s.build_pool(None)
    gateway = s.AsyncGatewayClient()
    embed_query = s._embed_query(gateway)
    rng = random.Random(20260928)
    key, blind = {}, []
    try:
        for qi, row in enumerate(diag, 1):
            vec = (await embed_query([row["embedded"]]))[0]
            top = await pool.topk(vec, K)
            cands = [{"rank": r, "cosine": round(m.cosine, 4), "pair_id": m.pair.get("pair_id"),
                      "scenario": m.pair["scenario_key"], "client": m.pair["trigger_text"],
                      "naren": m.pair["response_text"]} for r, m in enumerate(top, 1)]
            order = list(range(len(cands)))
            rng.shuffle(order)
            qid = f"Q{qi}"
            key[qid] = {"question": row["embedded"], "outcome": row["outcome"],
                        "candidates": [{"cid": f"{qid}-C{j + 1}", **cands[i]} for j, i in enumerate(order)]}
            blind.append({"qid": qid, "client_asked": row["embedded"],
                          "candidates": [{"cid": f"{qid}-C{j + 1}", "client_said": cands[i]["client"],
                                          "naren_replied": cands[i]["naren"]} for j, i in enumerate(order)]})
            print(f"{qid}: {len(cands)} candidates", flush=True)
    finally:
        await gateway.aclose()
        await pool.aclose()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "key.json").write_text(json.dumps(key, indent=2, ensure_ascii=False), encoding="utf-8")
    for b in blind:
        (out_dir / f"blind_{b['qid']}.json").write_text(json.dumps(b, indent=2, ensure_ascii=False), encoding="utf-8")


asyncio.run(main())
