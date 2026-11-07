"""Where does a COMPOSE answer's time go? Plan vs gather (embed + vector search) vs write.

Asked 2026-11-06 before deciding whether Jev (a fast typed-decision model) is worth adding:
Jev can only replace DECISIONS (the planner's kind), not text (the planner's search queries,
the writer's answer), so the seconds it could save are bounded by the plan stage's share.

How: builds the pool exactly as `Brain/ops/serve_ask_naren.py` does, wraps composing's three
stages and the gateway's two calls with timers -- NOTHING in the answer path is edited --
and replays a converse.py-format conversation file in thread order, each message under the
same 30s deadline the HTTP server applies. In-process, one message at a time, so it never
uses more than one of the gateway's per-key slots.

Usage (from Brain/, VPN on):
  ../.venv/bin/python ../ask-naren/audit/time_compose_stages.py \
      ../ask-naren/golden/naren-2026-11-04.replay.json <out.json> [--passes 2] [--hostaddr IP]
"""
import argparse
import asyncio
import contextvars
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRAIN = HERE.parent.parent / "Brain"
sys.path.insert(0, str(BRAIN))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


serve = _load("serve_ask_naren", BRAIN / "ops" / "serve_ask_naren.py")
converse = _load("converse", HERE / "live_conversation" / "converse.py")
from ask_naren import composing, responding, threads  # noqa: E402
from ask_naren.api import admission  # noqa: E402
from shared.gateway import AsyncGatewayClient  # noqa: E402

DEADLINE_S = 30.0
_stage = contextvars.ContextVar("stage", default="other")
_log: contextvars.ContextVar[list] = contextvars.ContextVar("log")


def _timed_stage(name, fn):
    async def wrapper(*a, **kw):
        token = _stage.set(name)
        t0 = time.perf_counter()
        try:
            return await fn(*a, **kw)
        finally:
            _log.get().append({"what": f"stage:{name}", "s": time.perf_counter() - t0})
            _stage.reset(token)
    return wrapper


def _timed_call(kind, fn):
    async def wrapper(*a, **kw):
        t0 = time.perf_counter()
        try:
            return await fn(*a, **kw)
        finally:
            _log.get().append({"what": f"{kind}@{_stage.get()}", "s": time.perf_counter() - t0})
    return wrapper


async def main_async(a):
    composing.plan = _timed_stage("plan", composing.plan)
    composing.gather = _timed_stage("gather", composing.gather)
    composing.write = _timed_stage("write", composing.write)

    pool, moves_by, playbooks_by, coachable, following_by = await serve.build_pool(a.hostaddr or None)
    label_for, account_for = serve.build_label_resolver()
    gateway = AsyncGatewayClient()
    gateway.chat_json = _timed_call("llm", gateway.chat_json)
    gateway.embed = _timed_call("embed", gateway.embed)
    embed_query = serve._embed_query(gateway)
    if not serve.COMPOSE:
        raise SystemExit("COMPOSE is off in serve_ask_naren.py -- this measures the compose path")

    async def answer(message, thread):
        return await responding.respond(
            message, pool, gateway, embed_query=embed_query, thread=thread,
            label_for=label_for, moves_for=None, playbook_for=playbooks_by.get,
            scenarios_for=lambda: coachable,
            following_for=lambda pid: following_by.get(pid, []), account_for=account_for,
            search_from_conversation=serve.SEARCH_FROM_CONVERSATION,
            answer_sees_conversation=serve.ANSWER_SEES_CONVERSATION,
            wide_retry=serve.WIDE_RETRY, k=serve.ANSWER_SHORTLIST_K,
            time_left=admission.seconds_left, compose=True)

    conversations = json.load(open(a.conversations, encoding="utf-8"))
    rows = []
    try:
        for p in range(1, a.passes + 1):
            for conv in conversations:
                thread = []
                for n, msg in enumerate(conv["messages"], 1):
                    log = []
                    _log.set(log)
                    loop = asyncio.get_running_loop()
                    t0 = time.perf_counter()
                    with admission.deadline_at(loop.time() + DEADLINE_S):
                        try:
                            # The HTTP layer parses the replayed thread into ThreadTurns; do the same.
                            r = await asyncio.wait_for(answer(msg, threads.parse(list(thread))),
                                                       DEADLINE_S)
                        except asyncio.TimeoutError:
                            r = {"outcome": "declined", "reason": "deadline_exceeded",
                                 "message": "(harness) deadline exceeded"}
                        except Exception as e:  # noqa: BLE001 -- recorded as a failed answer
                            r = {"outcome": "error", "reason": f"{type(e).__name__}: {str(e)[:120]}"}
                    total = time.perf_counter() - t0
                    row = {"pass": p, "n": n, "message": msg, "total_s": round(total, 2),
                           "outcome": r.get("outcome"), "reason": r.get("reason"),
                           "plan_kind": (r.get("intake") or {}).get("plan_kind"),
                           "events": [{**e, "s": round(e["s"], 3)} for e in log]}
                    rows.append(row)
                    by = {}
                    for e in log:
                        by[e["what"]] = by.get(e["what"], 0) + e["s"]
                    print(f"p{p} #{n:<2} {total:5.1f}s {row['outcome']:<9} "
                          + "  ".join(f"{k}={v:.1f}" for k, v in sorted(by.items())), flush=True)
                    if r.get("outcome") in ("answered", "declined", "clarify", "rendered"):
                        thread.append(converse.turn_from(msg, r))
    finally:
        json.dump(rows, open(a.out, "w", encoding="utf-8"), indent=2)
        await gateway.aclose()
        await pool.aclose()
    summarise(rows)


def summarise(rows):
    keys = sorted({e["what"] for r in rows for e in r["events"]})
    print("\nPER MESSAGE, seconds -- median / max across all messages (0 where a stage did not run)")
    totals = [r["total_s"] for r in rows]
    print(f"  {'total':<20} {statistics.median(totals):5.1f} / {max(totals):5.1f}")
    for k in keys:
        vals = [sum(e["s"] for e in r["events"] if e["what"] == k) for r in rows]
        share = sum(vals) / sum(totals)
        print(f"  {k:<20} {statistics.median(vals):5.1f} / {max(vals):5.1f}   {share:5.0%} of all time")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conversations")
    ap.add_argument("out")
    ap.add_argument("--passes", type=int, default=2)
    ap.add_argument("--hostaddr", default="")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
