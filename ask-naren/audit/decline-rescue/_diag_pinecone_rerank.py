"""[DEBUG-dcl9] Throwaway: do Pinecone's hosted rerankers find the answering exchange?

Same 6 questions x 50 candidates as the blind oracle read; answer key = the two judges'
AGREED YES. For each model and document form, reports per question: the original rank of the
reranker's #1, whether that #1 is an agreed answer, where the best agreed answer lands after
reranking, the top score, and latency. Delete after the diagnosis.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pinecone import Pinecone

ROOT = Path(__file__).resolve().parents[2]
ORACLE = ROOT / ".playwright-mcp" / "oracle"
env = {l.split("=", 1)[0]: l.split("=", 1)[1].strip().strip('"')
       for l in (ROOT / "Brain" / ".env").read_text(encoding="utf-8").splitlines()
       if "=" in l and not l.startswith("#")}
pc = Pinecone(api_key=env["PINECONE_API_KEY"])
key = json.loads((ORACLE / "key.json").read_text(encoding="utf-8"))
A = json.loads((ORACLE / "verdicts_A.json").read_text(encoding="utf-8"))
B = json.loads((ORACLE / "verdicts_B.json").read_text(encoding="utf-8"))

FORMS = {
    "reply": lambda c: c["naren"],
    "pair": lambda c: f"Client: {c['client']}\nNaren: {c['naren']}",
}
MODELS = ["cohere-rerank-3.5", "cohere-rerank-4-fast", "bge-reranker-v2-m3", "pinecone-rerank-v0"]

for model in MODELS:
    for form, doc in FORMS.items():
        top1_ok = 0
        lines = []
        secs = []
        for qid, v in key.items():
            cands = sorted(v["candidates"], key=lambda c: c["rank"])
            agreed = {c["cid"] for c in cands
                      if A[qid][c["cid"].split("-")[1]]["v"] == "YES" and B[qid][c["cid"].split("-")[1]]["v"] == "YES"}
            t = time.time()
            try:
                r = pc.inference.rerank(model=model, query=v["question"], documents=[doc(c) for c in cands],
                                        top_n=len(cands), return_documents=False,
                                        parameters={"truncate": "END"})
            except Exception as e:
                lines.append(f"{qid}: ERROR {str(e)[:90]}")
                continue
            secs.append(time.time() - t)
            order = [cands[d.index] for d in r.data]
            first = order[0]
            ok = first["cid"] in agreed if agreed else None
            top1_ok += bool(ok)
            new_pos = [i + 1 for i, c in enumerate(order) if c["cid"] in agreed]
            lines.append(f"{qid}[{v['outcome'][:3]}]: #1 was rank {first['rank']:>2} "
                         f"{'ANSWERS' if ok else ('no-answer-exists' if ok is None else 'wrong')}"
                         f" | agreed answers now at {new_pos or '-'} | top score {r.data[0].score:.3f}")
        med = sorted(secs)[len(secs) // 2] if secs else float("nan")
        print(f"\n=== {model} / {form}: top-1 answers {top1_ok}/5 answerable  ({med:.1f}s/call)")
        print("\n".join("  " + l for l in lines), flush=True)
