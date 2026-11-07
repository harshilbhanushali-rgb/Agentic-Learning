"""Plan -> Gather -> Write: one answer path for every question about a situation.

WHY THIS EXISTS. Intake sorted each message into one of nineteen intents, and each intent
showed its model a narrow slice: a follow-up saw ONE exchange, a procedure saw the playbook's
steps but not its pitfalls or phrasing, and phrasing/pitfalls printed a stored list with no
model at all. A message spanning several of those ("give me the playbook, some interactions,
what to keep in mind") could only land in one, so it got a quarter of an answer, and every
answer read like the template it came from.

Here there is one path:

1. PLAN (one model call). Read the message and the conversation; decide what kind of
   question it is and write one to `MAX_SEARCHES` short searches -- one for a narrow
   question, several angles for a broad one. Replaces intake's routing call, so a question
   costs about what it did before.
2. GATHER (no model). Embed every search in one call, take the nearest exchanges for each,
   interleave and dedupe them, and attach the WHOLE playbook of the situations they hit.
3. WRITE (one model call). The writer sees all of it plus the conversation and answers in
   whatever shape the question needs, citing one verbatim quote.

THE GATE IS THE SAME GATE (`grounding.check`). Its sources are every exchange shown and every
evidence quote of every playbook shown -- key moves, phrasing and pitfalls alike -- because
the rule is "cite something you were actually shown", and the writer was shown all of them.
One verified quote per answer, not one per point: the product decision of 2026-10-10.

WHAT IS GIVEN UP, deliberately: the playbook intents printed stored text with no invention
risk; here a model writes from that text. And searches are written by the planner rather
than checked to be the CSM's own words (ADR 0006/0014's rule), because splitting a broad
question into angles needs words the CSM did not type. The planner is told never to search
on Ask Naren's own earlier answers, which is the mechanism ADR 0006 guarded against.

The two questions about the WHOLE corpus -- what it covers and what comes up most -- stay
rendered from stored rows (`rendering.discovery`, `rendering.frequency`): there is no
situation to search for, and a list of the taxonomy cannot invent a scenario.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import sys
import time
import uuid
from collections import Counter

from ask_naren import answering, citations, grounding, rendering, threads
from ask_naren.retrieval import Match, RetrievalPool
from shared.gateway import GatewayReplyNotJSON

PLAN_REASONING_EFFORT = "low"
PLAN_MAX_TOKENS = 2048
#: LOW, not the single-search path's medium: measured 2026-10-10 on four live questions,
#: medium spent ~2,000 reasoning tokens before a 3,000-character answer and took 18-28s of a
#: 30s request deadline on its own.
WRITE_REASONING_EFFORT = "low"

#: A broad question splits into at most this many angles. Four covers "how it goes / what to
#: say / what goes wrong / what happened next"; more dilutes the shortlist each angle gets.
MAX_SEARCHES = 4
#: Searches are short phrases of the situation. Long framed text drags every query toward
#: every other (`ask-naren/docs/findings/answer-failure-modes.md`, the framing probe).
MAX_SEARCH_CHARS = 200
#: Search the CSM's message as written alongside the planner's searches (`with_message`).
#: ON. Measured 2026-11-07: no difference on the golden set, but every held-out pairwise read
#: with it on beat the old code by more than any read with it off, and on with long quotes beat
#: off with short quotes head-to-head 18-13. Its cost is a fuller shortlist and a longer writer
#: prompt (median ~57k chars vs ~48k). `ask-naren/golden/README.md`.
SEARCH_CSM_WORDS = True
#: The planner writes a `why_search` (a field of its own in its JSON) aimed at Naren's REASON a
#: result comes about, for questions about getting a client results; it is searched alongside the
#: rest. Built 2026-11-07 for Naren's "explain the why": his reasoning for "hire nurses faster"
#: (track down the funnel, then optimize to quality) sits in calls about tracking, which no topic
#: search reaches; a writer rule to borrow reasons from other situations cost answer quality, and
#: a bullet asking the planner for such a search was skipped. OFF until measured.
SEARCH_FOR_THE_WHY = False
#: The writer's JSON carries a `why` key, written before `answer`: the reason Naren gives for why
#: the approach gets the client the result, and the answer states it. Built 2026-11-08 after a
#: bug hunt found the search already brings Naren's reasons for "hire nurses faster" to the writer
#: (the funnel-indicators playbook 3/3, pair 1795 2/3) and the writer prompt dropped them: rule 1
#: skips exchanges answering a different question, each exchange carried Layer B's situation
#: label (pair 1795 is filed under a craigslist situation), and the header claimed a ranking the
#: interleaved list does not have. ON also drops that label and that claim. OFF until measured.
WRITER_STATES_THE_WHY = False

#: Nearest exchanges taken per search, and the cap on the merged list the writer sees. 20 is
#: the shortlist the single-search path ships with (ADR 0014's update); several searches
#: share a slightly larger budget rather than multiplying it.
PER_SEARCH_K = 12
MAX_EXCHANGES = 24
#: Playbooks attached: the situations the gathered exchanges fall in most often.
MAX_PLAYBOOKS = 2

#: The writer's second attempt (after a failed quote) starts only with this much of the
#: request deadline left; a generation over this much material takes most of it.
RETRY_NEEDS_SECONDS = 12.0

SITUATION = "situation"
TOPICS = "topics"
FREQUENCY = "frequency"
CLARIFY = "clarify"
OUT_OF_SCOPE = "out_of_scope"
#: A rework: the planner judged that the answer is mostly in the conversation already. The
#: writer gets the conversation, the material the last answer rested on -- its exchange and
#: its situation's playbook -- AND what the planner's backup searches find, and the quote is
#: checked against all of it. It searched nothing until 2026-11-07; on Naren's golden set a
#: NEW question on a topic the thread had touched was planned as a rework in most runs, and
#: the carried material alone could not answer it. The planner is given the principle, not
#: a list of cases, so the call is its own.
FROM_CONVERSATION = "from_conversation"
#: No search and no writer: the message is conversation with Ask Naren itself, not a request
#: for anything Naren knows. The planner's own short `reply` is sent back, and it is told to
#: give no advice or claim about client work -- a message needing any is a situation.
CONVERSATION = "conversation"
KINDS = (SITUATION, FROM_CONVERSATION, CONVERSATION, TOPICS, FREQUENCY, CLARIFY,
         OUT_OF_SCOPE)

#: Sent when the planner picks `conversation` but writes no reply.
CONVERSATION_FALLBACK = ("Hi! Describe a client situation, or what a client said, and I'll "
                         "answer from how Naren handled it on his calls.")

#: Echoed as `intake.intent` on every response from this path, so a stored response says
#: which pipeline produced it.
INTENT = "composed"

def plan_schema() -> dict:
    """The planner's JSON schema; `why_search` exists only while `SEARCH_FOR_THE_WHY` is on."""
    properties = {
        "kind": {"type": "string", "enum": list(KINDS)},
        "searches": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_SEARCHES},
        "question": {"type": "string"},
        "reply": {"type": "string"},
    }
    if SEARCH_FOR_THE_WHY:
        properties["why_search"] = {"type": "string"}
    return {"name": "ask_naren_plan", "strict": True,
            "schema": {"type": "object", "additionalProperties": False,
                       "required": list(properties), "properties": properties}}


# -- plan --------------------------------------------------------------------------------

def build_plan_prompt(message: str, turns) -> str:
    lines = [
        'You plan the lookups for "Ask Naren", an internal Joveo tool. A CSM (customer '
        "success manager) asks about client situations, and Ask Naren answers from Naren's "
        "real recorded client calls -- Naren is Joveo's most experienced CSM. The calls are "
        "mostly about getting clients live (onboarding, setup, tracking, integrations, "
        "budgets, reporting), with some about running campaigns.",
        "",
    ]
    if turns:
        lines += ["The conversation so far, oldest first:", "", threads.render(turns), ""]
    lines += [
        f"The CSM's message now: {message}",
        "",
        "Decide what kind of message this is (`kind`):",
        '  "situation"    -- answering needs something from Naren\'s calls that this '
        "conversation does not already contain. Most messages are this.",
        '  "from_conversation" -- everything the answer needs is already in this '
        "conversation: what Ask Naren has said so far, and what that was based on, is "
        "enough, and searching Naren's calls again would add nothing the answer needs. "
        "Decide by what the answer needs, not by how the message is worded. An earlier "
        "answer covers only what it was asked: a question none of them answered is a "
        "situation, even when the conversation has already touched its topic. Impossible "
        "before Ask Naren has answered anything.",
        '  "conversation" -- the message is talk with Ask Naren itself rather than a request '
        "for anything Naren knows, so neither his calls nor this conversation's material is "
        "needed to reply. Write the reply in `reply`: one or two friendly sentences as Ask "
        "Naren, which answers CSMs from Naren's real client calls. The reply gives no advice, "
        "facts or claims about client work or about Naren -- if replying would need any, "
        "the kind is not this.",
        '  "topics"       -- asks what Ask Naren covers or knows about in general, with no '
        "particular situation named.",
        '  "frequency"    -- asks which situations come up most often with clients.',
        '  "clarify"      -- no situation can be identified even with the conversation. '
        "Put one short question back to the CSM in `question`.",
        '  "out_of_scope" -- clearly not about client work at all.',
        "",
        "For a situation, write `searches`: 1 to 4 short phrases (5 to 15 words each) "
        "describing what a client would be raising or discussing on a call, in plain "
        "words. These are matched against what CLIENTS said on Naren's calls, so describe "
        "the client's side, not the CSM's request -- never 'how would Naren reply to'.",
        "  - A narrow question (one client remark, one thing to say) needs ONE search. If "
        "the CSM quotes the client, that quote is the search.",
        "  - A broad question ('tell me everything about X', 'playbook and what to keep in "
        "mind') needs several, each a different angle: setting it up, what goes wrong or "
        "gets pushback, what the client asks for, how it gets verified or followed up.",
        "  - A follow-up ('tell me more', 'what about this') is about the situation the "
        "conversation is on: write searches for what the CSM wants NOW, naming that "
        "situation in your own words.",
        "  - Never copy Ask Naren's earlier answers into a search -- they describe an "
        "exchange already found, and searching on them only finds it again.",
        "",
        "For from_conversation, still write the searches you would use if the earlier "
        "material turns out not to be available.",
        "",
        *(["For a situation, also write `why_search`. When the question is about getting a "
           "client results, it is one short search for Naren explaining the reason Joveo's "
           "approach produces that result -- how Joveo measures or optimizes towards it -- not "
           "the channel or topic the question names. Leave it empty when the question is not "
           "about getting results.", ""] if SEARCH_FOR_THE_WHY else []),
        "Respond as JSON: `kind`, `searches` (empty unless kind is situation or "
        "from_conversation), `question` (empty unless kind is clarify), `reply` (empty "
        "unless kind is conversation)"
        + (", `why_search` (empty unless kind is situation)." if SEARCH_FOR_THE_WHY else "."),
    ]
    return "\n".join(lines)


def fallback_plan(message: str) -> dict:
    """What runs when the planner fails: search the message as written -- a working tool."""
    return {"kind": SITUATION, "searches": [" ".join(message.split())[:MAX_SEARCH_CHARS]],
            "question": "", "reply": ""}


def _usable_plan(payload: dict, message: str) -> dict:
    kind = payload.get("kind")
    if kind not in KINDS:
        return fallback_plan(message)
    question = str(payload.get("question") or "").strip()
    if kind == CLARIFY and not question:
        return fallback_plan(message)
    searches: list[str] = []
    for raw in payload.get("searches") or []:
        text = " ".join(str(raw).split())[:MAX_SEARCH_CHARS]
        if text and text.lower() not in {s.lower() for s in searches}:
            searches.append(text)
    searches = searches[:MAX_SEARCHES]
    if kind == SITUATION and not searches:
        return fallback_plan(message)
    why = " ".join(str(payload.get("why_search") or "").split())[:MAX_SEARCH_CHARS]
    return {"kind": kind, "searches": searches, "question": question,
            "reply": str(payload.get("reply") or "").strip(),
            "why_search": why if SEARCH_FOR_THE_WHY and kind == SITUATION else ""}


def with_message(searches: list[str], message: str) -> list[str]:
    """The planner's searches plus the CSM's message as written, unless already among them.

    Added 2026-11-07: on Naren's golden set the planner's rewording sometimes moved off what
    he asked, and the message itself is the one search that cannot. It is one more phrase in
    the same embedding call. The finding that framed CSM text drags retrieval
    (`ask-naren/docs/findings/answer-failure-modes.md`) is why it is an EXTRA search,
    interleaved with the planner's, rather than the only one.
    """
    text = " ".join(message.split())[:MAX_SEARCH_CHARS]
    if not text or text.lower() in {s.lower() for s in searches}:
        return list(searches)
    return [*searches, text]


async def plan(message: str, turns, gateway) -> dict:
    """The plan for this message. Never raises: a failed plan is the message searched as is."""
    started = time.perf_counter()
    try:
        payload, meta = await gateway.chat_json(
            build_plan_prompt(message, turns), model=answering.CHAT_MODEL,
            reasoning_effort=PLAN_REASONING_EFFORT, temperature=answering.TEMPERATURE,
            max_tokens=PLAN_MAX_TOKENS, no_cache=True, schema=plan_schema())
    except Exception as e:                  # noqa: BLE001 -- see the docstring
        _trace("plan", seconds=time.perf_counter() - started, failed=type(e).__name__)
        return fallback_plan(message)
    the_plan = _usable_plan(payload if isinstance(payload, dict) else {}, message)
    _trace("plan", seconds=time.perf_counter() - started, kind=the_plan["kind"],
           searches=len(the_plan["searches"]), **_usage(meta))
    return the_plan


# -- gather ------------------------------------------------------------------------------

async def gather(searches: list[str], pool: RetrievalPool, *, embed_query,
                 playbook_for=None) -> tuple[list[Match], list[tuple[str, dict]]]:
    """The exchanges and playbooks the writer will see.

    Exchanges are INTERLEAVED by rank across searches -- every search's nearest, then every
    search's second -- so a broad question's narrower angles are not crowded out by whichever
    angle happens to sit in a denser part of the corpus. A pair found by two searches appears
    once, at its first position.

    Playbooks are chosen by how many gathered exchanges fall in each situation, so the
    writer gets the play for what the searches actually landed on rather than for a scenario
    a model named.
    """
    started = time.perf_counter()
    vectors = await embed_query(searches)
    embedded = time.perf_counter()
    ranked = await asyncio.gather(*(pool.topk(vectors[i], PER_SEARCH_K)
                                    for i in range(len(searches))))
    if not any(ranked):
        # The same infrastructure fault `answer_situation` raises on: the store and the pool
        # disagree about what exists. Not a decline -- see there.
        raise RuntimeError(
            "retrieval returned no kb_pair the pool authorises -- the vector store and the "
            "pool disagree about what exists. Run ops/check_vector_coverage.py.")

    seen: set = set()
    merged: list[Match] = []
    for position in range(PER_SEARCH_K):
        for matches in ranked:
            if position >= len(matches) or len(merged) >= MAX_EXCHANGES:
                continue
            match = matches[position]
            key = match.pair.get("pair_id", id(match.pair))
            if key not in seen:
                seen.add(key)
                merged.append(match)

    playbooks: list[tuple[str, dict]] = []
    if playbook_for is not None:
        counts = Counter(m.pair["scenario_key"] for m in merged)
        for key, _n in counts.most_common():
            row = playbook_for(key)
            document = (row or {}).get("playbook") if row else None
            if document:
                playbooks.append((key, document))
            if len(playbooks) >= MAX_PLAYBOOKS:
                break
    _trace("gather", seconds=time.perf_counter() - started,
           embed_seconds=embedded - started,
           pair_ids=[m.pair.get("pair_id") for m in merged],
           scenarios=dict(Counter(m.pair["scenario_key"] for m in merged).most_common(4)),
           playbooks=[key for key, _ in playbooks])
    return merged, playbooks


# -- write -------------------------------------------------------------------------------

def situation_label(scenario_key: str) -> str:
    return (scenario_key or "").replace("_", " ")


def _evidence_line(entry: dict, label_for) -> str:
    call = entry.get("call", "")
    label = label_for(call) if call else ""
    where = f"{call}" + (f" -- {label}" if label and label != call else "")
    return f'Naren said: "{entry.get("quote", "")}" (call: {where})'


def build_write_prompt(message: str, turns, searches: list[str], pairs: list[dict],
                       playbooks: list[tuple[str, dict]], label_for, *,
                       reworking: bool = False, carried: int = 0) -> str:
    """The writer's prompt. On a rework, the first `carried` of `pairs` are what the last
    answer rested on and the rest are what the backup searches found."""
    lines = [
        'You are "Ask Naren", an internal Joveo tool. A CSM (customer success manager) asks '
        "about client situations, and you answer from Naren's real recorded client calls. "
        "Naren is Joveo's most experienced CSM.",
        "",
    ]
    if turns:
        lines += ["The conversation so far, oldest first:", "", threads.render(turns), ""]
    lines.append(f"The CSM's message now: {message}")
    if reworking:
        lines += ["", "The CSM wants you to rework what you have already told them. Below is "
                      "the material your last answer rested on, then what was looked up in "
                      "case the request needs more."]
        if carried:
            lines += ["", "THE REAL EXCHANGE from Naren's calls your last answer rested on:"]
    for n, pair in enumerate(pairs, 1):
        if n == carried + 1:
            lines += ["", "What was looked up for it: " + "; ".join(searches), "",
                      "REAL EXCHANGES from Naren's calls, in no particular order:"
                      if WRITER_STATES_THE_WHY else
                      "REAL EXCHANGES from Naren's calls, closest first within each lookup:"]
        call = pair["call_filename"]
        label = label_for(call) or call
        filed = ("" if WRITER_STATES_THE_WHY
                 else f"; situation: {situation_label(pair['scenario_key'])}")
        lines += ["",
                  f"  [{n}] Client said: {pair['trigger_text']}",
                  f"      Naren replied: {pair['response_text']}",
                  f"      (call: {call} -- {label}{filed})"]

    for scenario_key, playbook in playbooks:
        lines += ["", f"HOW NAREN RUNS \"{situation_label(scenario_key)}\", distilled from "
                      "many of his calls:",
                  f"  When it comes up: {playbook.get('situation_signature', '')}"]
        arc = [str(s).strip() for s in (playbook.get("arc") or []) if str(s).strip()]
        if arc:
            lines.append("  The order he usually runs it in: " + " -> ".join(arc))
        for move in answering.procedure_moves(playbook):
            lines += [f"  Move: {move.get('name', '')} -- {move.get('criterion', '')}"]
            lines += [f"    {_evidence_line(e, label_for)}"
                      for e in move.get("evidence") or []]
        phrasing = playbook.get("signature_language") or []
        if phrasing:
            lines.append("  How he phrases it:")
            lines += [f"    {_evidence_line(e, label_for)}" for e in phrasing]
        pitfalls = playbook.get("pitfalls_and_variants") or []
        if pitfalls:
            lines.append("  What to watch out for:")
            for item in pitfalls:
                lines.append(f"    - {item.get('text', '')}")
                lines += [f"      {_evidence_line(e, label_for)}"
                          for e in item.get("evidence") or []]

    lines += [
        "",
        "Write the answer to what the CSM actually asked.",
        "- Start from the exchanges where Naren answers this same question, and build the "
        "answer on what he said there. Use the rest of the material only for what those "
        "exchanges leave out, and skip anything on the topic that answers a different "
        "question.",
        "- Keep the substance of what Naren said, not just its topic: the reasons he gives "
        "for why it matters to the client, and any offer, condition or next step he commits "
        "to. Features without his reasons lose what makes his answers work.",
        *(["- When you give a why, the answer states it: it is what lets the CSM make the case "
           "to the client."] if WRITER_STATES_THE_WHY else []),
        "- Answer in the form the question asks for. A question put the way a client would "
        "put it gets an answer the CSM can say to that client, speaking as Joveo. A question "
        "about handling a situation gets a walkthrough of how Naren handles it. Fit the "
        "length to that.",
        "- Where Naren's calls say different things about the same fact, go with the most "
        "recent call.",
        "- When you mention a real example, name the client by the account shown beside its "
        "call, never by a person's first name from the transcript.",
        "- Everything you state must come from the material above. Do not add product "
        "facts, numbers, timelines or promises that are not there.",
        ("- You may reuse what you already told the CSM in the conversation, reshaped as "
         "they ask, but add nothing that is neither there nor in the material above.")
        if reworking else
        ("- Use the conversation only to understand what the CSM means. It is not something "
         "Naren said."),
        "- Do not mention 'exchanges', 'the playbook', 'the material' or bracketed numbers.",
        "- Format: short paragraphs. For a longer answer you may use '## ' headings, '- ' "
        "bullets, numbered lists and **bold**. No tables, no links.",
        ("- If the request needs something that is neither in the conversation nor above, "
         "decline instead of answering.") if reworking else
        "- If nothing above is relevant to what the CSM asked, decline instead of answering.",
        "",
        "Respond as JSON with exactly these keys:",
        '  "declined": boolean,',
        *(['  "why": the reason Naren gives, anywhere in the material above, for why this '
           "approach gets the client the result they want -- in his words, so the answer can "
           "state it (empty string if the material gives none, or if declined),"]
          if WRITER_STATES_THE_WHY else []),
        '  "answer": your answer (empty string if declined),',
        '  "quote": a verbatim substring copied from ONE "Naren replied" or "Naren said" '
        "line above, one or two sentences long: the part the answer most rests on, copied "
        "exactly -- " + ("never from a move's own description, a 'when it comes up', or a "
                         "watch-out line" if WRITER_STATES_THE_WHY else
                         "never from a move, a 'when it comes up', or a watch-out line")
        + ", which are summaries rather than his words (empty string if declined),",
        '  "cited_call": the call identifier printed beside that quote, copied exactly '
        "(empty string if declined),",
        '  "used_calls": the call identifiers of everything you drew on.',
    ]
    return "\n".join(lines)


def grounding_sources(pairs: list[dict], playbooks: list[tuple[str, dict]]
                      ) -> tuple[list[grounding.GroundingSource], dict[int, str]]:
    """Every exchange shown, and every evidence quote of every playbook shown.

    Returns the sources and, for each playbook evidence entry (by identity), the scenario it
    belongs to -- an evidence quote records its call, not its situation.
    """
    sources = grounding.from_pairs(pairs)
    scenario_of: dict[int, str] = {}
    for scenario_key, playbook in playbooks:
        entries = answering.move_evidence(answering.procedure_moves(playbook))
        entries += list(playbook.get("signature_language") or [])
        for item in playbook.get("pitfalls_and_variants") or []:
            entries += list(item.get("evidence") or [])
        for entry in entries:
            scenario_of[id(entry)] = scenario_key
        sources += grounding.from_playbook_evidence(entries)
    return sources, scenario_of


#: One id per `respond` call, so every trace line of one question can be read together.
_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("ask_naren_request_id",
                                                                   default="-")


def _trace(event: str, **fields) -> None:
    """One stderr line per stage of one question (added 2026-11-07 to diagnose timeouts,
    grounding drops and run-to-run variance from a server log). Stage START lines matter:
    a request cancelled at the deadline never logs its end, so the last start line says
    which stage the time ran out in. Message text, quotes and answers are never logged."""
    record = {"event": event, "rid": _REQUEST_ID.get()}
    for key, value in fields.items():
        record[key] = round(value, 2) if isinstance(value, float) else value
    print("[ask-naren] " + json.dumps(record, ensure_ascii=False, default=str),
          file=sys.stderr, flush=True)


def _usage(meta) -> dict:
    """Token counts from a gateway reply, including reasoning tokens where reported."""
    meta = meta if isinstance(meta, dict) else {}
    details = meta.get("completion_tokens_details") or {}
    return {"prompt_tokens": meta.get("prompt_tokens"),
            "completion_tokens": meta.get("completion_tokens"),
            "reasoning_tokens": (details.get("reasoning_tokens")
                                 if isinstance(details, dict) else None)}


def _log_gate_failure(reason: str, payload: dict, sources, attempt: int, reworking: bool) -> None:
    """One stderr line per failed grounding check, so a `grounding_unverified` decline in a
    server log says WHY. A truncated quote start is logged, never the full quote."""
    record = {"event": "grounding_failed", "reason": reason, "attempt": attempt,
              "rework": reworking, **grounding.explain_failure(payload, sources)}
    print("[ask-naren] " + json.dumps(record, ensure_ascii=False), file=sys.stderr, flush=True)


def _drawn_from(used_calls, shown: set[str], label_for) -> list[dict]:
    """The calls the writer says it drew on, kept only where it was actually shown them,
    reported under the name shown."""
    out, seen = [], set()
    canonical = {grounding.call_key(name): name for name in shown}
    for raw in used_calls if isinstance(used_calls, list) else []:
        call = canonical.get(grounding.call_key(str(raw)))
        if call is not None and call not in seen:
            seen.add(call)
            out.append({"label": label_for(call) or call, "call_filename": call})
    return out


async def write(message: str, turns, searches: list[str], matches: list[Match],
                playbooks: list[tuple[str, dict]], gateway, *, label_for, time_left=None,
                carried_pairs: list[dict] = (), reworking: bool = False) -> dict:
    """Write and gate one answer.

    `matches` is what the searches found. On a rework (`FROM_CONVERSATION`) the writer also
    gets `carried_pairs`, the exchange the last answer rested on, shown first; an exchange
    the searches found again is shown once. A cited exchange the searches found reports its
    match; a carried one the searches did not find has no cosine to report. Every decline
    here followed a search, so it records the nearest match.
    """
    carried = list(carried_pairs)
    carried_ids = {p.get("pair_id") for p in carried}
    pairs = carried + [m.pair for m in matches if m.pair.get("pair_id") not in carried_ids]
    prompt = build_write_prompt(message, turns, searches, pairs, playbooks, label_for,
                                reworking=reworking, carried=len(carried))
    sources, scenario_of = grounding_sources(pairs, playbooks)

    def declined(reason: str) -> dict:
        return answering._decline(reason, matches[0], 1, label_for)

    for attempt in range(answering.MAX_ATTEMPTS):
        if attempt and time_left is not None and time_left() < RETRY_NEEDS_SECONDS:
            print("[ask-naren] " + json.dumps({"event": "grounding_retry_skipped",
                                               "seconds_left": round(time_left(), 1),
                                               "needs": RETRY_NEEDS_SECONDS}),
                  file=sys.stderr, flush=True)
            break
        started = time.perf_counter()
        _trace("write_start", attempt=attempt + 1, rework=reworking, prompt_chars=len(prompt),
               exchanges=len(pairs), playbooks=len(playbooks), sources=len(sources))
        try:
            payload, meta = await gateway.chat_json(
                prompt, model=answering.CHAT_MODEL, reasoning_effort=WRITE_REASONING_EFFORT,
                temperature=answering.TEMPERATURE, max_tokens=answering.MAX_TOKENS,
                no_cache=True)
        except GatewayReplyNotJSON:
            # A reply the lenient parser could not read (1 of 41 held-out answers on
            # 2026-11-07): a fresh generation usually parses, so it takes the second attempt
            # when there is one and the deadline fits it. Otherwise it stays a service fault.
            _trace("write_not_json", attempt=attempt + 1,
                   seconds=time.perf_counter() - started)
            if (attempt + 1 < answering.MAX_ATTEMPTS
                    and (time_left is None or time_left() >= RETRY_NEEDS_SECONDS)):
                continue
            raise
        _trace("write", attempt=attempt + 1, seconds=time.perf_counter() - started,
               declined=bool(payload.get("declined")),
               answer_chars=len(str(payload.get("answer") or "")),
               **({"why_chars": len(str(payload.get("why") or ""))}
                  if WRITER_STATES_THE_WHY else {}),
               cited_call=payload.get("cited_call") or "", **_usage(meta))
        if payload.get("declined"):
            return declined(answering.NO_CLOSE_MATCH)
        gate = grounding.check(payload, sources)
        if not gate.passed:
            _log_gate_failure(gate.reason, payload, sources, attempt + 1, reworking)
            continue
        if gate.corrected:
            _trace("citation_corrected", attempt=attempt + 1,
                   cited_call=payload.get("cited_call") or "",
                   actual_call=gate.source.identifier)
        verified = gate.source.payload
        if any(p is verified for p in pairs):
            citation = answering._citation(verified, label_for)
            rank = next((i for i, m in enumerate(matches, 1)
                         if m.pair.get("pair_id") == verified.get("pair_id")), None)
            match = ({"match": answering._match_info(matches[rank - 1], rank)}
                     if rank is not None else {})
        else:
            # A playbook evidence quote: it records its call, not a kb_pairs row, so there is
            # no pair_id and no cosine to report (the same rule as `answer_procedure`).
            citation = {"label": label_for(verified["call"]) or verified["call"],
                        "call_filename": verified["call"],
                        "scenario_key": scenario_of.get(id(verified), "")}
            match = {}
        return {"outcome": answering.ANSWERED,
                "answer": payload["answer"].strip(),
                "quote": payload["quote"].strip(),
                "citation": citation,
                **match,
                "drawn_from": _drawn_from(payload.get("used_calls"),
                                          {s.identifier for s in sources}, label_for)}
    return declined(answering.GROUNDING_UNVERIFIED)


def carried_material(turns, pool: RetrievalPool, playbook_for=None
                     ) -> tuple[list[dict], list[tuple[str, dict]]]:
    """What the last answer rested on: its exchange, if it cited one still in the pool, and
    the whole playbook of its situation. Both empty when the thread has nothing to rework."""
    last = threads.last_answer(turns)
    if last is None:
        return [], []
    pair = pool.by_pair_id(last.pair_id) if last.pair_id is not None else None
    row = playbook_for(last.scenario_key) if (playbook_for and last.scenario_key) else None
    document = (row or {}).get("playbook")
    return ([pair] if pair else []), ([(last.scenario_key, document)] if document else [])


# -- the whole path ----------------------------------------------------------------------

def _echo(response: dict, message: str, the_plan: dict, *, searched: bool = True,
          carried: bool = False) -> dict:
    return {**response, "intake": {"intent": INTENT,
                                   "retrieval_query": (" | ".join(the_plan["searches"])
                                                       if searched else ""),
                                   "situation": ("carried" if carried or not searched
                                                 else "opens"),
                                   "plan_kind": the_plan["kind"]}}


async def respond(message: str, turns, pool: RetrievalPool, gateway, *, embed_query,
                  label_for=citations.resolve_label, playbook_for=None, scenarios_for=None,
                  time_left=None) -> dict:
    """Answer one message by planning, gathering and writing. `turns` is already trimmed."""
    token = _REQUEST_ID.set(uuid.uuid4().hex[:8])
    started = time.perf_counter()
    _trace("start", turns=len(turns), message_chars=len(message))
    try:
        result = await _respond(message, turns, pool, gateway, embed_query=embed_query,
                                label_for=label_for, playbook_for=playbook_for,
                                scenarios_for=scenarios_for, time_left=time_left)
        _trace("done", seconds=time.perf_counter() - started, outcome=result.get("outcome"),
               reason=result.get("reason"), plan_kind=(result.get("intake") or {}).get("plan_kind"),
               cited_pair=(result.get("citation") or {}).get("pair_id"))
        return result
    finally:
        _REQUEST_ID.reset(token)


async def _respond(message: str, turns, pool: RetrievalPool, gateway, *, embed_query,
                   label_for, playbook_for, scenarios_for, time_left) -> dict:
    the_plan = await plan(message, turns, gateway)
    kind = the_plan["kind"]

    if kind in (TOPICS, FREQUENCY) and scenarios_for is not None:
        scenarios = scenarios_for()
        rendered = (rendering.discovery(scenarios) if kind == TOPICS
                    else rendering.frequency(scenarios))
        return _echo(rendered, message, the_plan)
    if kind == CLARIFY and not threads.clarify_already_asked(turns, the_plan["question"]):
        return _echo(answering.clarify(the_plan["question"]), message, the_plan)
    if kind == CONVERSATION:
        # Shaped as a clarify -- no answer, quote or citation, so nothing in it can pass for
        # grounded -- and flagged so the page shows it as a reply rather than as a question
        # Ask Naren needs answered.
        return _echo({"outcome": answering.CLARIFY,
                      "question": the_plan["reply"] or CONVERSATION_FALLBACK,
                      "conversational": True}, message, the_plan, searched=False)
    if kind == OUT_OF_SCOPE:
        return _echo(answering.decline_without_search(answering.OUT_OF_SCOPE), message,
                     the_plan)
    if kind == FROM_CONVERSATION:
        carried_pairs, carried_playbooks = carried_material(turns, pool, playbook_for)
        if carried_pairs or carried_playbooks:
            # Searched on the planner's backup searches (the message if it wrote none), but
            # never on the message as an extra search: a rework request ("make it shorter")
            # names no situation.
            the_plan = {**the_plan, "searches": (the_plan["searches"]
                                                 or fallback_plan(message)["searches"])}
            matches, found_playbooks = await gather(the_plan["searches"], pool,
                                                    embed_query=embed_query,
                                                    playbook_for=playbook_for)
            shown = {key for key, _ in carried_playbooks}
            playbooks = carried_playbooks + [(k, d) for k, d in found_playbooks
                                             if k not in shown]
            written = await write(message, turns, the_plan["searches"], matches, playbooks,
                                  gateway, label_for=label_for, time_left=time_left,
                                  carried_pairs=carried_pairs, reworking=True)
            return _echo(written, message, the_plan, carried=True)
        # Nothing to rework -- no earlier answer, or one that rested on nothing still
        # available. Search instead, on the planner's backup searches if it wrote any.
        the_plan = ({**the_plan, "kind": SITUATION} if the_plan["searches"]
                    else fallback_plan(message))
    elif kind == SITUATION:
        if the_plan.get("why_search"):
            the_plan = {**the_plan, "searches": with_message(the_plan["searches"],
                                                             the_plan["why_search"])}
        if SEARCH_CSM_WORDS:
            the_plan = {**the_plan, "searches": with_message(the_plan["searches"], message)}
    else:
        # A corpus question with no scenario list, or a clarify already asked once: answer
        # the message as written rather than asking the same thing twice.
        the_plan = fallback_plan(message)

    matches, playbooks = await gather(the_plan["searches"], pool,
                                      embed_query=embed_query, playbook_for=playbook_for)
    written = await write(message, turns, the_plan["searches"], matches, playbooks,
                          gateway, label_for=label_for, time_left=time_left)
    return _echo(written, message, the_plan)
