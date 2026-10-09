"""Drive the live Ask Naren service through whole conversations, the way the web app does.

Each response becomes a thread turn by the same rules as frontend/src/lib/thread.ts
`turnFrom` (answered: citation identifiers; rendered: per-kind anchor; clarify/declined:
nothing), and the thread is replayed with every next message.
"""
import json
import sys
import time
import urllib.request

URL = "http://127.0.0.1:8787/ask"
REPLIES = {
    "discovery": "Showed what Ask Naren covers.", "frequency": "Showed which situations come up most.",
    "show_exchange": "Showed the real exchange.", "what_happened_next": "Showed how that conversation continued.",
    "coverage_check": "Reported what is covered near that situation.",
    "sequence": "Showed the order Naren runs it in.", "phrasing": "Showed how Naren words it.",
    "pitfalls": "Showed what usually goes wrong.", "scenario_check": "Showed when that play applies.",
    "play_confidence": "Showed how well evidenced that play is.",
    "where_else_seen": "Listed which accounts that has come up with.",
    "call_prep": "Laid out what is likely to come up on that call.",
    "improve_at_move": "Showed the criterion, the pitfalls and Naren doing it.",
}


def turn_from(message, r):
    base = {"message": message, "outcome": r["outcome"], "reply": "", "scenario_key": "",
            "pair_id": None, "call_filename": ""}
    if r["outcome"] == "answered":
        c = r["citation"]
        return {**base, "reply": r["answer"], "scenario_key": c["scenario_key"],
                "pair_id": c.get("pair_id"), "call_filename": c["call_filename"]}
    if r["outcome"] == "clarify":
        return {**base, "reply": r["question"]}
    if r["outcome"] == "declined":
        return {**base, "reply": r["message"]}
    k = r["kind"]
    base["reply"] = REPLIES[k]
    if k in ("show_exchange", "what_happened_next"):
        return {**base, "scenario_key": r["citation"]["scenario_key"],
                "pair_id": r["citation"].get("pair_id")}
    if k in ("sequence", "phrasing", "pitfalls", "scenario_check", "play_confidence",
             "improve_at_move"):
        return {**base, "scenario_key": r["scenario_key"]}
    if k == "coverage_check":
        return {**base, "scenario_key": r["nearest"]["scenario_key"]}
    return base


def ask(situation, thread):
    body = json.dumps({"situation": situation, "thread": thread}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read()), time.time() - t0
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}"), time.time() - t0


def summary(r):
    i = r.get("intake", {})
    head = (f"{r['outcome']}{'/' + r['kind'] if r.get('kind') else ''}  "
            f"intent={i.get('intent')} situation={i.get('situation')} "
            f"query={i.get('retrieval_query')!r} match={'yes' if 'match' in r else 'no'}"
            + (f" SEARCH={i['search_query']!r}" if i.get('search_query') else "")
            + (f" RETRIES={r['retries']}" if r.get('retries') else "")
            + (f" rank={r['match']['rank']}" if r.get('match') else ""))
    o, k = r["outcome"], r.get("kind")
    if o == "answered":
        body = (f"scenario={r['citation']['scenario_key']} pair={r['citation'].get('pair_id')}\n"
                f"      ANSWER: {r['answer']}\n      QUOTE: {r['quote']}")
        if r.get("my_reply"):
            body += f"\n      MY_REPLY: {r['my_reply']}"
    elif o == "clarify":
        body = f"QUESTION: {r['question']}"
    elif o == "declined":
        body = f"reason={r['reason']}  {r['message']}"
    elif k in ("show_exchange", "what_happened_next"):
        body = (f"scenario={r['citation']['scenario_key']} pair={r['citation'].get('pair_id')}\n"
                f"      CLIENT: {r['exchange']['client_said'][:300]}\n"
                f"      NAREN: {r['exchange']['naren_replied'][:300]}")
        if k == "what_happened_next":
            nxt = r["following"][:2]
            body += "".join(f"\n      THEN CLIENT: {f['client_said'][:200]}\n      THEN NAREN: "
                            f"{f['naren_replied'][:200]}" for f in nxt) or "\n      (nothing followed)"
    elif k == "sequence":
        body = f"scenario={r['scenario_key']}  STEPS: {r['steps']}"
    elif k == "phrasing":
        body = f"scenario={r['scenario_key']}  " + " | ".join(p["phrase"] for p in r["phrases"][:4])
    elif k == "pitfalls":
        body = f"scenario={r['scenario_key']}  " + " | ".join(p["text"] for p in r["pitfalls"][:3])
    elif k == "scenario_check":
        body = f"scenario={r['scenario_key']}  APPLIES WHEN: {r['applies_when']}"
    elif k == "play_confidence":
        body = f"scenario={r['scenario_key']}  moves={r['moves']} quotes={r['quotes']} n={r['n_evidence']}"
    elif k == "improve_at_move":
        body = (f"scenario={r['scenario_key']} focused={r['focused']}  MOVES: "
                + " | ".join(m["name"] for m in r["moves"][:3]))
    elif k == "coverage_check":
        body = f"nearest={r['nearest']['scenario_key']} calls={r['nearest']['support_calls']} ({r['nearest']['evidence']})"
    elif k == "where_else_seen":
        body = (f"scenario={r['scenario_key']} accounts {r['accounts_at_least']}-{r['accounts_at_most']} "
                f"same_scenario={r['same_scenario']}/{r['exchanges']}: "
                + ", ".join(a["account"] for a in r["accounts"][:5]))
    elif k == "call_prep":
        body = "SCENARIOS: " + " | ".join(f"{s['scenario_key']}({s['exchanges']})" for s in r["scenarios"])
    elif k in ("discovery", "frequency"):
        body = f"{r.get('total')} scenarios: " + ", ".join(s["scenario_key"] for s in r["scenarios"][:6])
    else:
        body = json.dumps(r)[:300]
    return head, body


def main():
    conversations = json.load(open(sys.argv[1], encoding="utf-8"))
    log = []
    for conv in conversations:
        print(f"\n{'=' * 100}\nCONVERSATION: {conv['name']}\n{'=' * 100}")
        thread = []
        for n, msg in enumerate(conv["messages"], 1):
            r, secs = ask(msg, thread)
            if "outcome" not in r:
                print(f"\n[{n}] CSM: {msg}\n   ERROR {r}")
                log.append({"conv": conv["name"], "message": msg, "response": r})
                continue
            head, body = summary(r)
            print(f"\n[{n}] CSM: {msg}\n   -> {head}  ({secs:.1f}s)\n      {body}")
            log.append({"conv": conv["name"], "message": msg, "thread_in": list(thread),
                        "response": r, "seconds": round(secs, 1)})
            thread.append(turn_from(msg, r))
    json.dump(log, open(sys.argv[2], "w", encoding="utf-8"), indent=2)


if __name__ == "__main__":
    main()
