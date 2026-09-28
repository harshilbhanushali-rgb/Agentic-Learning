"""[DEBUG-dcl9] Throwaway: can a gateway model do the answerability judgement the blind Opus
judges did? One call per question (all 50 candidates), per model; scored against the two
judges' AGREED verdicts. Prints precision/recall on YES, whether rank-1 was called right,
and latency. Delete after the diagnosis.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
ORACLE = ROOT / ".playwright-mcp" / "oracle"
env = {l.split("=", 1)[0]: l.split("=", 1)[1].strip().strip('"')
       for l in (ROOT / "Brain" / ".env").read_text(encoding="utf-8").splitlines()
       if "=" in l and not l.startswith("#")}
BASE, HEAD = env["LLM_GATEWAY_URL"].rstrip("/"), {"Authorization": f"Bearer {env['LLM_GATEWAY_KEY']}"}

key = json.loads((ORACLE / "key.json").read_text(encoding="utf-8"))
A = json.loads((ORACLE / "verdicts_A.json").read_text(encoding="utf-8"))
B = json.loads((ORACLE / "verdicts_B.json").read_text(encoding="utf-8"))


def prompt(q: dict) -> str:
    lines = [
        "A client said this to a Joveo CSM on a live call:",
        f'  "{q["client_asked"]}"',
        "",
        "Below are real exchanges from a senior CSM's (Naren's) calls with OTHER clients.",
        "Which of them contain a reply from Naren that, in substance, answers the SPECIFIC",
        "question or concern above -- so a CSM could paraphrase it as their reply?",
        "Same topic is NOT enough: it must address the same proposition (who does what, how",
        "long, whether X is possible). Reject subject inversions (the client's own plans),",
        "dropped qualifiers, and replies that only ask a clarifying question.",
        "",
    ]
    for c in q["candidates"]:
        lines += [f'[{c["cid"].split("-")[1]}] Client said: {c["client_said"]}',
                  f'     Naren replied: {c["naren_replied"]}', ""]
    lines += ['Return JSON only: {"answers": ["C7", ...]} -- the ids that answer it, best first.',
              'An empty list is a valid answer.']
    return "\n".join(lines)


import os
WINDOW = int(os.environ.get("DIAG_WINDOW", "50"))
EFFORT = os.environ.get("DIAG_EFFORT")


def ask(model: str, text: str) -> tuple[list[str], float]:
    t = time.time()
    body = {"model": model, "messages": [{"role": "user", "content": text}],
            "max_tokens": 4000, "temperature": 0}
    if EFFORT:
        body["reasoning_effort"] = EFFORT
    r = httpx.post(f"{BASE}/v1/chat/completions", headers=HEAD, timeout=120, json=body)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", content, re.S)
    ids = json.loads(m.group(0)).get("answers", []) if m else []
    return [str(i) for i in ids], time.time() - t


models = sys.argv[1:] or ["claude-5-opus", "claude-5-sonnet", "claude-4.5-haiku", "gemini-3.6-flash"]
for model in models:
    tp = fp = fn = 0
    rank1_ok = 0
    secs = []
    per_q = []
    for qid in key:
        q = json.loads((ORACLE / f"blind_{qid}.json").read_text(encoding="utf-8"))
        in_window = {c["cid"] for c in key[qid]["candidates"] if c["rank"] <= WINDOW}
        q["candidates"] = [c for c in q["candidates"] if c["cid"] in in_window]
        agreed_yes = {s for s in A[qid] if A[qid][s]["v"] == "YES" and B[qid][s]["v"] == "YES"}
        either_yes = {s for s in A[qid] if "YES" in (A[qid][s]["v"], B[qid][s]["v"])}
        ids, dt = ask(model, prompt(q))
        secs.append(dt)
        got = set(ids)
        tp += len(got & agreed_yes); fp += len(got - either_yes); fn += len(agreed_yes - got)
        rank1 = next(c["cid"].split("-")[1] for c in key[qid]["candidates"] if c["rank"] == 1)
        rank1_ok += (rank1 in got) == (rank1 in agreed_yes)
        by_cid = {c["cid"].split("-")[1]: c["rank"] for c in key[qid]["candidates"]}
        per_q.append(f'{qid}:{[by_cid.get(i, "?") for i in ids]}')
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    print(f"{model:20s} precision {prec:.2f}  recall {rec:.2f}  rank1-verdict-right {rank1_ok}/6  "
          f"secs/call median {sorted(secs)[len(secs) // 2]:.1f} max {max(secs):.1f}", flush=True)
    print("   picked ranks:", "  ".join(per_q), flush=True)
