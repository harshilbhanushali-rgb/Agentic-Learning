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
from collections import Counter

from ask_naren import answering, citations, grounding, rendering, threads
from ask_naren.retrieval import Match, RetrievalPool

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
#: No search: the planner judged that everything the answer needs is already in the
#: conversation. The writer gets the conversation and the material the last answer rested
#: on -- its exchange and its situation's playbook -- and the quote is checked against those.
#: The planner is given the principle, not a list of cases, so the call is its own.
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

PLAN_SCHEMA = {
    "name": "ask_naren_plan",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "searches", "question", "reply"],
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "searches": {"type": "array", "items": {"type": "string"},
                         "maxItems": MAX_SEARCHES},
            "question": {"type": "string"},
            "reply": {"type": "string"},
        },
    },
}


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
        "Decide by what the answer needs, not by how the message is worded. Impossible "
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
        "Respond as JSON: `kind`, `searches` (empty unless kind is situation or "
        "from_conversation), `question` (empty unless kind is clarify), `reply` (empty "
        "unless kind is conversation).",
    ]
    return "\n".join(lines)


def fallback_plan(message: str) -> dict:
    """What runs when the planner fails: search the message as written -- a working tool."""
    return {"kind": SITUATION, "searches": [message.strip()[:MAX_SEARCH_CHARS]],
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
    return {"kind": kind, "searches": searches, "question": question,
            "reply": str(payload.get("reply") or "").strip()}


async def plan(message: str, turns, gateway) -> dict:
    """The plan for this message. Never raises: a failed plan is the message searched as is."""
    try:
        payload, _meta = await gateway.chat_json(
            build_plan_prompt(message, turns), model=answering.CHAT_MODEL,
            reasoning_effort=PLAN_REASONING_EFFORT, temperature=answering.TEMPERATURE,
            max_tokens=PLAN_MAX_TOKENS, no_cache=True, schema=PLAN_SCHEMA)
    except Exception:                       # noqa: BLE001 -- see the docstring
        return fallback_plan(message)
    return _usable_plan(payload if isinstance(payload, dict) else {}, message)


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
    vectors = await embed_query(searches)
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
                       reworking: bool = False) -> str:
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
        lines += ["", "Nothing new was looked up: the CSM wants you to rework what you have "
                      "already told them. Below is the material your last answer rested on.",
                  ""]
        if pairs:
            lines.append("THE REAL EXCHANGE from Naren's calls your last answer rested on:")
    else:
        lines += ["", "What was looked up for it: " + "; ".join(searches), "",
                  "REAL EXCHANGES from Naren's calls, closest first within each lookup:"]
    for n, pair in enumerate(pairs, 1):
        call = pair["call_filename"]
        label = label_for(call) or call
        lines += ["",
                  f"  [{n}] Client said: {pair['trigger_text']}",
                  f"      Naren replied: {pair['response_text']}",
                  f"      (call: {call} -- {label}; situation: "
                  f"{situation_label(pair['scenario_key'])})"]

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
        "Write the answer to what the CSM actually asked, the way an experienced colleague "
        "who has listened to all of these calls would explain it to them.",
        "- Fit the length and shape to the question. If they need words for a client, give "
        "them words they can say. If they want to learn a situation, walk them through it: "
        "how it usually goes, what Naren says, what to watch out for, and real examples. "
        "A simple question gets a short answer.",
        "- When you mention a real example, name the client by the account shown beside its "
        "call, never by a person's first name from the transcript.",
        "- Use everything above that is relevant and combine it; skip anything that is on "
        "the topic but answers a different question.",
        "- Everything you state must come from the material above. Do not add product "
        "facts, numbers, timelines or promises that are not there.",
        ("- You may reuse what you already told the CSM in the conversation, reshaped as "
         "they ask, but add nothing that is neither there nor in the material above.")
        if reworking else
        ("- Use the conversation only to understand what the CSM means. It is not something "
         "Naren said."),
        "- Talk about what Naren does and says. Do not mention 'exchanges', 'the playbook', "
        "'the material' or bracketed numbers.",
        "- Format: short paragraphs. For a longer answer you may use '## ' headings, '- ' "
        "bullets, numbered lists and **bold**. No tables, no links.",
        ("- If the request needs something that is neither in the conversation nor above, "
         "decline instead of answering.") if reworking else
        "- If nothing above is relevant to what the CSM asked, decline instead of answering.",
        "",
        "Respond as JSON with exactly these keys:",
        '  "declined": boolean,',
        '  "answer": your answer (empty string if declined),',
        '  "quote": a verbatim substring copied from ONE "Naren replied" or "Naren said" '
        "line above that the answer most rests on -- never from a move, a 'when it comes "
        "up', or a watch-out line, which are summaries rather than his words (empty string "
        "if declined),",
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


def _drawn_from(used_calls, shown: set[str], label_for) -> list[dict]:
    """The calls the writer says it drew on, kept only where it was actually shown them."""
    out, seen = [], set()
    for raw in used_calls if isinstance(used_calls, list) else []:
        call = str(raw).strip()
        if call in shown and call not in seen:
            seen.add(call)
            out.append({"label": label_for(call) or call, "call_filename": call})
    return out


async def write(message: str, turns, searches: list[str], matches: list[Match] | None,
                playbooks: list[tuple[str, dict]], gateway, *, label_for, time_left=None,
                carried_pairs: list[dict] = ()) -> dict:
    """Write and gate one answer.

    `matches` is what a search found. None means NOTHING WAS SEARCHED (`FROM_CONVERSATION`):
    the writer reworks the conversation over `carried_pairs` and `playbooks`, the material
    the last answer rested on, so there is no cosine to report and a decline is the
    follow-up decline (`answering.NO_SEARCH_REASONS`) rather than one recording a match.
    """
    reworking = matches is None
    pairs = list(carried_pairs) if reworking else [m.pair for m in matches]
    prompt = build_write_prompt(message, turns, searches, pairs, playbooks, label_for,
                                reworking=reworking)
    sources, scenario_of = grounding_sources(pairs, playbooks)

    def declined(reason: str) -> dict:
        if reworking:
            return answering.decline_without_search(answering.FOLLOW_UP_UNGROUNDED)
        return answering._decline(reason, matches[0], 1, label_for)

    for attempt in range(answering.MAX_ATTEMPTS):
        if attempt and time_left is not None and time_left() < RETRY_NEEDS_SECONDS:
            break
        payload, _meta = await gateway.chat_json(
            prompt, model=answering.CHAT_MODEL, reasoning_effort=WRITE_REASONING_EFFORT,
            temperature=answering.TEMPERATURE, max_tokens=answering.MAX_TOKENS,
            no_cache=True)
        if payload.get("declined"):
            return declined(answering.NO_CLOSE_MATCH)
        gate = grounding.check(payload, sources)
        if not gate.passed:
            continue
        verified = gate.source.payload
        rank = next((i for i, p in enumerate(pairs, 1) if p is verified), None)
        if rank is not None:
            citation = answering._citation(verified, label_for)
            match = ({} if reworking
                     else {"match": answering._match_info(matches[rank - 1], rank)})
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

def _echo(response: dict, message: str, the_plan: dict, *, searched: bool = True) -> dict:
    return {**response, "intake": {"intent": INTENT,
                                   "retrieval_query": (" | ".join(the_plan["searches"])
                                                       if searched else ""),
                                   "situation": "opens" if searched else "carried",
                                   "plan_kind": the_plan["kind"]}}


async def respond(message: str, turns, pool: RetrievalPool, gateway, *, embed_query,
                  label_for=citations.resolve_label, playbook_for=None, scenarios_for=None,
                  time_left=None) -> dict:
    """Answer one message by planning, gathering and writing. `turns` is already trimmed."""
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
        pairs, playbooks = carried_material(turns, pool, playbook_for)
        if pairs or playbooks:
            written = await write(message, turns, [], None, playbooks, gateway,
                                  label_for=label_for, time_left=time_left,
                                  carried_pairs=pairs)
            return _echo(written, message, the_plan, searched=False)
        # Nothing to rework -- no earlier answer, or one that rested on nothing still
        # available. Search instead, on the planner's backup searches if it wrote any.
        the_plan = ({**the_plan, "kind": SITUATION} if the_plan["searches"]
                    else fallback_plan(message))
    elif kind != SITUATION:
        # A corpus question with no scenario list, or a clarify already asked once: answer
        # the message as written rather than asking the same thing twice.
        the_plan = fallback_plan(message)

    matches, playbooks = await gather(the_plan["searches"], pool,
                                      embed_query=embed_query, playbook_for=playbook_for)
    written = await write(message, turns, the_plan["searches"], matches, playbooks,
                          gateway, label_for=label_for, time_left=time_left)
    return _echo(written, message, the_plan)
