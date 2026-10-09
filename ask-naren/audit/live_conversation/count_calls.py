"""Model calls implied by each live-run response's path (issue #25).

A LOWER BOUND: a second answer attempt after a failed quote check, an intake retry after a
malformed reply, and network-level retries are invisible in the response. A timed-out turn
is counted separately because its path is unknown.

Usage: python count_calls.py <live_run.json> [...]
"""
import json
import sys

SEARCHED_RENDERED = {"show_exchange", "what_happened_next", "coverage_check", "sequence",
                     "phrasing", "pitfalls", "scenario_check", "play_confidence",
                     "improve_at_move", "where_else_seen", "call_prep"}


def count(entry):
    r = entry["response"]
    if r.get("reason") == "deadline_exceeded" or "outcome" not in r:
        return None
    i = r.get("intake", {})
    chat, embed = 1, 0                                   # intake
    retries = r.get("retries", [])
    o = r["outcome"]
    searched = i.get("situation") == "opens" or "match" in r
    if o == "rendered":
        if r["kind"] in SEARCHED_RENDERED and searched:
            embed += 1
        return chat, embed
    if o == "clarify":
        if r.get("match"):                               # no-play clarify after a search
            embed += 1
        return chat, embed
    if o == "declined" and r["reason"] == "out_of_scope":
        return chat, embed
    if i.get("intent") == "follow_up" or r.get("reason") == "follow_up_ungrounded":
        chat += 1                                        # the follow-up generation
        if "searched" not in retries:
            return chat, embed
    if searched or "searched" in retries:
        embed += 1
    chat += 2 if r.get("reason") == "grounding_unverified" else 1
    if "wide" in retries:
        chat += 1
    return chat, embed


for path in sys.argv[1:]:
    run = json.load(open(path, encoding="utf-8"))
    rows = [count(e) for e in run]
    known = [x for x in rows if x is not None]
    print(f"{path}: {len(run)} turns, chat calls {sum(c for c, _ in known)}, "
          f"embedding calls {sum(e for _, e in known)}, timed out (uncounted) "
          f"{sum(1 for x in rows if x is None)}")
