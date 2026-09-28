# Decline rescue: evidence from 2026-09-28 (parked)

Why `reply_to_client` declines "no close match" on on-topic questions, and what fixing it would
take. Parked by the operator; the ticket holds the conclusions. This folder holds the evidence,
so the work resumes from it rather than from memory.

**Throwaway scripts, not maintained.** They import `Brain/ops/serve_ask_naren.py` internals as
of commit `d47ff29` and need Tailscale/VPN, the gateway, Pinecone and Neon. Run from `Brain/`
with the repo venv.

| File | What it does |
|---|---|
| `_diag_decline.py` | Real `respond` path per question; shows the exchange the model was given. **Its 3-repeat check predates the gateway cache fix (d47ff29), so its repeats were cache echoes.** |
| `_diag_top50.py` | Dumps the top-50 by similarity per question, shuffled into blind files plus a private key. |
| `oracle/blind_Q*.json`, `oracle/key.json` | The 6 questions × 50 candidates (blind), and the key mapping them to rank, cosine and pair. |
| `oracle/verdicts_A.json`, `verdicts_B.json` | Two independent blind Claude (Opus) judges: YES / PARTIAL / NO, "does Naren's reply answer this specific question". 93% exact agreement. |
| `_diag_judge_models.py` | Gateway models as the answerability judge, scored against the agreed verdicts. |
| `_diag_pinecone_rerank.py`, `_diag_bge_path.py` | Pinecone rerankers (bge, pinecone-rerank-v0) as a ranking, and inside the real answer path. |
| `_diag_k20.py` | The production `answer_situation` with k=N (Gemini picks from the top N), N uncached runs. |
| `diag_q.json`, `diag_out.json` | The 6 questions and the first harness's output. |

Every RIGHT/WRONG here is **Claude's reading, not a CSM's**. n = 6.
