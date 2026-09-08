"""Answers built from stored rows, with NO model call at all (issues #19, #20).

THE GROUNDING GUARANTEE HERE IS STRUCTURAL, NOT VERIFIED. Every other answer path generates
prose and then proves the prose rests on something real -- the grounding gate. These paths
never generate, so there is nothing to prove: a rendered list of the coachable scenarios
cannot invent a 35th, and a rendered exchange cannot drift from the exchange. That is why
they carry the `rendered` outcome rather than `answered`, and why no function here takes a
gateway.

It is a stronger guarantee than the gate, not a weaker one. The gate catches a model that
invented something; this catches nothing because there is nothing to catch.

WHAT THIS COSTS, and it is the honest trade: a rendered answer cannot adapt to how the
question was asked. "What do you cover" and "do you know anything about renewals" get the
same list. Issues #19 and #20 both accept that deliberately -- #12's words, "a rendered list
of the 34 scenario descriptions cannot invent a topic".

Nothing here touches Postgres or the gateway. The rows arrive already loaded, in the same
startup connection window as the pool.
"""
from __future__ import annotations

from ask_naren import citations, intake

RENDERED = "rendered"

#: What kind of rendered answer this is. A caller switches on it to choose a layout, the
#: same way it switches on `outcome` to choose a component. Kept as a separate key rather
#: than as five outcomes, because they share one guarantee and one shape -- splitting them
#: would make the response union five entries longer for no behavioural difference.
#:
#: THE SAME STRINGS AS THE INTENTS, and imported rather than re-declared. `responding`
#: switches on the intent and returns the kind, so two independent copies could drift into
#: a response whose `kind` disagreed with the `intake.intent` echoed beside it -- with
#: nothing to catch it, because each file's own tests would still pass.
DISCOVERY = intake.DISCOVERY
FREQUENCY = intake.FREQUENCY
SHOW_EXCHANGE = intake.SHOW_EXCHANGE
WHAT_HAPPENED_NEXT = intake.WHAT_HAPPENED_NEXT
COVERAGE_CHECK = intake.COVERAGE_CHECK

#: How many scenarios `frequency` ranks. All 34 is a wall of text a CSM will not read; the
#: point of the intent is "what comes up most", which is the head of the distribution.
FREQUENCY_TOP_N = 12

#: How many following exchanges `what_happened_next` shows. Two is enough to see where the
#: conversation went without pasting the rest of the call at a CSM mid-question.
NEXT_EXCHANGES = 2


def discovery(scenarios: list[dict]) -> dict:
    """What Ask Naren covers, grouped by primary topic (issue #19).

    `scenarios` is the COACHABLE list, already filtered by the caller through
    `retrieval.coachable_scenario_keys` -- Brain's one definition of "sink". Filtering here
    too would be a second definition of coachable, which `retrieval.py` warns is exactly the
    latent bug a CSM-facing tool should not discover.

    Every key in the output came from a row that was passed in, so this CANNOT emit a
    scenario the taxonomy does not have.

    *** THE GROUPING IS NOT AVAILABLE ON THE LIVE TAXONOMY, measured 2026-09-09. *** #19 asks
    for the list "grouped by primary topic", and every one of the 259 rows carries
    `primary_topic = 'ungrouped'` with `primary_topic_key = NULL`. The `primary_topics` table
    still holds 84 rows, but they belong to the PRE-UNION taxonomy -- they include sinks like
    "Social Greetings and Pleasantries" that the union map does not have -- and the
    primary-topic hierarchy is recorded as rejected in
    `Brain/docs/findings/layer-a-primary-topics-and-adjudication-ab.md`.

    So `grouped` says whether the grouping is real, and the caller renders a flat list when
    it is not. Showing 34 situations under one heading called "ungrouped" would be worse
    than showing 34 situations: it invents a category and tells a CSM that the tool's own
    taxonomy is disorganised, when the truth is that this particular field was never
    populated for this taxonomy. The grouping code stays because it is correct the day the
    field is.
    """
    groups: dict[str, list[dict]] = {}
    for scenario in scenarios:
        topic = (scenario.get("primary_topic") or "").strip()
        groups.setdefault(topic, []).append({
            "scenario_key": scenario["scenario_key"],
            "description": (scenario.get("business_description") or "").strip(),
        })
    grouped = len(groups) > 1
    return {
        "outcome": RENDERED,
        "kind": DISCOVERY,
        "grouped": grouped,
        "topics": [{"topic": topic or "Other", "scenarios": sorted(items, key=_by_key)}
                   for topic, items in sorted(groups.items())] if grouped else [],
        "scenarios": sorted((s for items in groups.values() for s in items), key=_by_key),
        "total": sum(len(items) for items in groups.values()),
    }


def frequency(scenarios: list[dict], top_n: int = FREQUENCY_TOP_N) -> dict:
    """Which situations come up most often with clients (issue #19).

    Ranked on `support_calls` -- the number of DISTINCT CALLS a scenario's cluster drew
    from, which the schema calls the evidence rollup recording why each scenario exists.

    IT RANKS THE CORPUS, NOT THE WORLD, and the response says so in `basis` rather than
    leaving a CSM to assume otherwise. A scenario is frequent here because Naren's recorded
    calls talk about it, which is a fact about what was recorded and routed as much as about
    what clients raise. Ask Naren has no client-facing telemetry to say more than that.
    """
    ranked = sorted(
        ({"scenario_key": s["scenario_key"],
          "description": (s.get("business_description") or "").strip(),
          "support_calls": s.get("support_calls") or 0,
          "call_coverage": s.get("call_coverage")}
         for s in scenarios),
        key=lambda s: (-s["support_calls"], s["scenario_key"]))
    return {
        "outcome": RENDERED,
        "kind": FREQUENCY,
        "scenarios": ranked[:top_n],
        "total": len(ranked),
        "basis": ("Ranked by how many of Naren's recorded calls each situation was drawn "
                  "from. That is a fact about this corpus, not about how often clients "
                  "raise it."),
    }


def show_exchange(match, label_for=citations.resolve_label) -> dict:
    """The real exchange behind a situation, verbatim (issue #20).

    NOT A PARAPHRASE, which is the entire point -- a CSM asking to see the exchange wants to
    judge the fit themselves rather than read our summary of it. So the client's words and
    Naren's reply are the stored strings, untouched.
    """
    pair = match.pair
    return {
        "outcome": RENDERED,
        "kind": SHOW_EXCHANGE,
        "exchange": {"client_said": pair["trigger_text"], "naren_replied": pair["response_text"]},
        "citation": _citation(pair, label_for),
        "match": {"cosine": match.cosine, "scenario_key": pair["scenario_key"], "rank": 1},
    }


def what_happened_next(match, following: list[dict], label_for=citations.resolve_label) -> dict:
    """How the conversation actually continued after that moment (issue #20).

    `following` is the exchanges after this one IN THE SAME CALL, in turn order, supplied by
    the caller from the startup index -- the service holds no database handle while
    answering.

    NOT FILTERED TO COACHABLE. The next thing said is frequently a logistics or backchannel
    turn that Layer A sinks, and skipping those would present a LATER exchange as the
    adjacent one: the difference between "what happened next" and "the next thing we happen
    to cover". `is_last` says plainly when there was nothing after it, rather than rendering
    an empty list a CSM has to interpret.
    """
    pair = match.pair
    return {
        "outcome": RENDERED,
        "kind": WHAT_HAPPENED_NEXT,
        "exchange": {"client_said": pair["trigger_text"], "naren_replied": pair["response_text"]},
        "following": [{"client_said": f["trigger_text"], "naren_replied": f["response_text"],
                       "scenario_key": f.get("scenario_key") or ""}
                      for f in following],
        "is_last": not following,
        "citation": _citation(pair, label_for),
    }


def coverage_check(asked: str, match, scenario: dict | None,
                   label_for=citations.resolve_label) -> dict:
    """Does Ask Naren cover this kind of situation at all (issue #20)?

    AN ANSWER, NOT A DECLINE, and the ticket is explicit about that. Today a CSM cannot tell
    "Ask Naren has nothing on this" from "I asked it the wrong way", because both look like
    a decline. This is the intent that separates them, so it must never itself decline --
    "no, nothing close" is a successful answer to the question that was asked.

    `asked` is THE CSM'S OWN MESSAGE, not intake's extracted `retrieval_query`. The page
    renders it back in quote marks, and quoting a model-authored span as though the CSM had
    written it is a small lie that gets believed -- the extracted query is already visible
    in the `intake` echo for anyone debugging.

    `scenario` is the Layer A row for what retrieval reached, or None if the taxonomy no
    longer has it. Its `business_description` is what makes the answer useful: naming the
    scenario alone tells a CSM nothing if the key is opaque.

    IT REPORTS THE NEAREST THING, AND REFUSES TO CLAIM THAT IS THE SAME AS COVERAGE. There
    is always a nearest exchange -- retrieval returns one for any string -- so rendering it
    as "the closest thing we cover is X" reads as a yes even when the CSM's topic is absent
    entirely, which is the very confusion this intent exists to end.

    THE HONEST ANSWER IS NOT A THRESHOLD. ADR 0005 measured retrieval cosine as unable to
    separate right answers from wrong ones (0.814 against 0.798), and #12 forbids using it
    as a decline gate. So this cannot say "we do not cover that" -- nothing in the data
    supports the claim. What it can do is hand the CSM what it actually knows and let them
    judge: the nearest situation, what that situation IS, and how much evidence sits behind
    it. `evidence` is that last part in words rather than a bare count, because "9 calls" is
    only meaningful against a distribution a CSM has never seen.
    """
    pair = match.pair
    support = (scenario or {}).get("support_calls") or 0
    return {
        "outcome": RENDERED,
        "kind": COVERAGE_CHECK,
        "asked_about": asked,
        "nearest": {
            "scenario_key": pair["scenario_key"],
            "description": ((scenario or {}).get("business_description") or "").strip(),
            "support_calls": support,
            "evidence": _evidence_band(support),
        },
        "citation": _citation(pair, label_for),
        "match": {"cosine": match.cosine, "scenario_key": pair["scenario_key"], "rank": 1},
    }


#: How many distinct calls a scenario needs before its evidence stops being "thin". NOT a
#: gate and NOT a quality threshold -- it decides one word in one sentence, and nothing
#: declines on it. A real threshold on this corpus would need the calibration ADR 0005 says
#: cosine does not support; this is a reading aid, and it is set where it is because the
#: median coachable scenario sits well above it.
THIN_EVIDENCE_CALLS = 5


def _evidence_band(support_calls: int) -> str:
    """"thin" or "solid", for a CSM deciding how much weight to put on a coverage answer.

    Words rather than the raw count, because "9 calls" means nothing without the
    distribution behind it -- and the count is in the payload beside this for anyone who
    wants it.
    """
    return "thin" if support_calls < THIN_EVIDENCE_CALLS else "solid"


def _citation(pair: dict, label_for) -> dict:
    return {
        "label": label_for(pair["call_filename"]) or pair["call_filename"],
        "call_filename": pair["call_filename"],
        "pair_id": pair["pair_id"],
        "scenario_key": pair["scenario_key"],
    }


def _by_key(item: dict) -> str:
    return item["scenario_key"]
