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
SEQUENCE = intake.SEQUENCE
PHRASING = intake.PHRASING
PITFALLS = intake.PITFALLS
SCENARIO_CHECK = intake.SCENARIO_CHECK
PLAY_CONFIDENCE = intake.PLAY_CONFIDENCE
WHERE_ELSE_SEEN = intake.WHERE_ELSE_SEEN
CALL_PREP = intake.CALL_PREP
IMPROVE_AT_MOVE = intake.IMPROVE_AT_MOVE

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

    `match` IS THE SAME BLOCK `show_exchange` CARRIES (issue #45). This path retrieves its
    exchange exactly as that one does and already had the cosine in hand; leaving it off
    meant a stored turn recorded NULL for a number that was computed and thrown away.
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
        "match": {"cosine": match.cosine, "scenario_key": pair["scenario_key"], "rank": 1},
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


# -- the Layer C playbook, rendered (issue #18) --------------------------------------------
#
# ALL FIVE RENDER RATHER THAN GENERATE, and that is a deliberate reading of the ticket
# rather than a shortcut. #18 asks that each answer be "verified against its grounding
# source, or declines" -- but the playbook ALREADY IS the answer in each case, and it was
# itself generated offline and verbatim-snapped (the step that validated the Layer C method:
# the pilot failed PB0 pre-snap on quote-smoothing and passed 10/10 after). Generating here
# would paraphrase a verified document and add an invention risk to replace text that is
# already there. Rendering makes verification UNNECESSARY rather than skipped -- the same
# argument #12 makes for Layer A, and the one issues #19 and #20 ship on.
#
# Three of the five have nothing quotable at all: `arc` is a list of move NAMES, and
# `situation_signature` and `n_evidence` are a sentence and a number. There is no quote for
# a gate to check even in principle.


def sequence(scenario_key: str, playbook: dict) -> dict:
    """What order to run the moves in (issue #18), from `arc`.

    `arc` is a list of move names in the order Naren tends to run them -- OUR words, derived
    from his calls, with no quote attached to any step. `db/schema.sql` records that the
    order is load-bearing, so nothing here re-sorts it.
    """
    return {
        "outcome": RENDERED,
        "kind": SEQUENCE,
        "scenario_key": scenario_key,
        "steps": [str(step).strip() for step in (playbook.get("arc") or [])
                  if str(step).strip()],
    }


def phrasing(scenario_key: str, playbook: dict,
             label_for=citations.resolve_label) -> dict:
    """How Naren actually words it (issue #18), from `signature_language`.

    THE STRONGEST-GROUNDED PATH IN THE TOOL, and by accident of shape rather than by design:
    a `signature_language` entry is `{phrase, quote, call, account}`, so the phrase and the
    real quote it came from are one-to-one. Unlike a `procedure` answer -- where one verified
    quote covers one move of several (ADR 0009) -- everything shown here has its own quote
    beside it.

    Paraphrasing would defeat the question outright: a CSM asking how Naren words something
    wants HIS words, not ours about his.

    SO EVERY QUOTE IS ATTRIBUTED. This is the one rendered path that shows Naren's verbatim
    words from a real client call, and ADR 0002's whole argument for unredacted citations is
    that "a verifiable, real citation is what makes the answer trustworthy rather than a bare
    assertion" -- which a CSM cannot act on if the call is not named. ADR 0009 singles this
    path out as the one that can vouch for its whole answer; dropping the source here would
    make the best-grounded answer in the tool look like the worst.
    """
    return {
        "outcome": RENDERED,
        "kind": PHRASING,
        "scenario_key": scenario_key,
        "phrases": [{"phrase": (e.get("phrase") or "").strip(),
                     "quote": (e.get("quote") or "").strip(),
                     **_source((e.get("call") or "").strip(), label_for)}
                    for e in (playbook.get("signature_language") or [])
                    if (e.get("quote") or "").strip()],
    }


def pitfalls(scenario_key: str, playbook: dict,
             label_for=citations.resolve_label) -> dict:
    """What usually goes wrong (issue #18), from `pitfalls_and_variants`.

    Each pitfall is our sentence with Naren's own evidence under it, so a CSM can see both
    the claim and the moment it came from. An entry whose evidence is empty is still shown --
    the pitfall itself is the answer, and dropping it would under-report what is known.

    The evidence quotes are attributed for the same reason `phrasing`'s are: they are
    Naren's real words from a real call, and a quote a CSM cannot trace is a bare assertion.
    """
    return {
        "outcome": RENDERED,
        "kind": PITFALLS,
        "scenario_key": scenario_key,
        "pitfalls": [{"text": (item.get("text") or "").strip(),
                      "evidence": [{"quote": (e.get("quote") or "").strip(),
                                    **_source((e.get("call") or "").strip(), label_for)}
                                   for e in (item.get("evidence") or [])
                                   if (e.get("quote") or "").strip()]}
                     for item in (playbook.get("pitfalls_and_variants") or [])
                     if (item.get("text") or "").strip()],
    }


def _source(call_filename: str, label_for) -> dict:
    """What a CSM reads, plus the raw filename an engineer traces with.

    TWO KEYS RATHER THAN ONE, matching `answering._citation` and `_citation` below: resolving
    the label was never a shape change for a caller, and the raw identifier stays available
    for anyone tracing a bad answer.

    NO `pair_id`, for the same reason `answer_procedure`'s citation carries none -- a
    playbook evidence quote records the call it came from, not a `kb_pairs` row, and
    inventing one would point at an exchange the quote does not come from.

    The label falls back to the raw filename, which is what `resolve_label` itself does
    wherever resolution would have to guess: 31.3% of citable calls are opaque UUIDs, and a
    blank source line reads as less trustworthy than the filename the call really has.
    """
    return {"call": call_filename,
            "label": label_for(call_filename) or call_filename}


def scenario_check(asked: str, scenario_key: str, playbook: dict) -> dict:
    """Whether this play applies to what the CSM is seeing (issue #18), from
    `situation_signature`.

    IT DOES NOT ANSWER YES OR NO, and cannot. Whether a play fits a live client is a
    judgement about a situation Ask Naren has only the CSM's sentence for; claiming it
    would be exactly the confident-and-wrong answer a catch-all scenario produces. So it
    shows WHEN the play applies, in the playbook's own words, and lets the CSM compare --
    the same shape as `coverage_check`, and for the same reason.
    """
    return {
        "outcome": RENDERED,
        "kind": SCENARIO_CHECK,
        "asked_about": asked,
        "scenario_key": scenario_key,
        "applies_when": (playbook.get("situation_signature") or "").strip(),
    }


#: The evidence-selection cap `calibration/scenario_playbook_trial.py` builds a playbook
#: under (`N_EVIDENCE_MAX`). Restated here rather than imported, deliberately: `ask_naren`
#: imports nothing from `calibration`, because the service must not depend on the pipeline
#: it reads the output of. It is used ONLY to label a number honestly, never to compute one,
#: so a drift makes a caption slightly wrong rather than an answer wrong.
EVIDENCE_SELECTION_CAP = 50


def play_confidence(scenario_key: str, record: dict) -> dict:
    """How well evidenced the play is (issue #18).

    IT LEADS WITH WHAT SURVIVED THE SNAP, not with `n_evidence`, and that is the fix for a
    real defect #18's spec review found. `n_evidence` is a property of the RECORD rather
    than of the document -- `playbook_backfill` sets it to the number of evidence entries
    SELECTED AS INPUT, capped at the selection limit, and never recomputes it after the
    verbatim snap drops quotes and moves.

    MEASURED ON THE LIVE ROWS, 2026-09-09: 25 of 33 live playbooks carry exactly 50, so for
    three quarters of the corpus the number is a constant that cannot separate a
    well-evidenced play from a thin one -- which is precisely what this intent exists to do.
    Worse, it inverts: `programmatic_advertising_scope_and_capability` reports 50 and rests
    on 8 verified quotes, while `non_technical_stakeholder_translation` reports 16 and rests
    on 9. `Brain/docs/findings/layer-d-say-arm.md` had already recorded the median at 50 for
    both good and bad move groups.

    So `moves` and `quotes` are counted from the LIVE DOCUMENT and are what the answer leads
    on: they describe what is actually there. `n_evidence` is still reported -- it is a real
    recorded fact about how the play was built -- but flagged with `n_evidence_capped` so
    "50" is read as "50 or more, and that is the ceiling" rather than as a score.
    """
    playbook = record.get("playbook") or {}
    moves = playbook.get("key_moves") or []
    n_evidence = record.get("n_evidence") or 0
    return {
        "outcome": RENDERED,
        "kind": PLAY_CONFIDENCE,
        "scenario_key": scenario_key,
        "moves": len(moves),
        "quotes": sum(len(m.get("evidence") or []) for m in moves),
        "n_evidence": n_evidence,
        #: True when `n_evidence` sits on the builder's selection cap, which means the real
        #: number was AT LEAST this and the value carries no information above it.
        "n_evidence_capped": n_evidence >= EVIDENCE_SELECTION_CAP,
        "basis": ("The moves and quotes are what this play actually rests on today. The "
                  "evidence count is how many moments were considered when it was built, "
                  "before the verbatim check dropped any -- so it says how much was looked "
                  "at, not whether the play is right for your client."),
    }


# -- which accounts a situation has come up with (issue #22) -------------------------------

#: How many neighbouring exchanges `where_else_seen` scans. NOT a candidate-selection
#: change and NOT in tension with ADR 0005, which measured a SHORTLIST for ANSWERING and
#: rejected it: an answer rests on one exchange, so showing the model five was a change to
#: how one exchange gets picked. This intent's question is "how widely does this come up",
#: which has no single-exchange form at all -- one neighbour cannot answer it. The breadth
#: is required by the question rather than chosen as a tuning knob.
#:
#: 25 because the answer is a shape, not a census: it has to be wide enough to tell one
#: client from several and short enough that the tail is not noise. Nothing thresholds on
#: it and no answer is withheld because of it.
NEIGHBOURS_SCANNED = 25


def where_else_seen(asked: str, matches: list, account_for=citations.account_for) -> dict:
    """Which accounts a situation has come up with (issue #22).

    The question behind it is "is this a one-client quirk or a pattern across the book",
    which a CSM cannot answer from a single exchange -- so this is the one intent that reads
    a neighbourhood rather than a nearest match.

    IT NAMES AN ACCOUNT ONLY WHERE THE RECORDED DATA STATES IT UNAMBIGUOUSLY, which is the
    ticket's own constraint and the reason `citations.account_for` returns None rather than
    a filename. 31.3% of citable calls are opaque UUIDs, and of the 323 opaque calls 40
    carry two to four external participant domains -- one measured example lists both a
    brand and its agency. Picking the likelier one would print an agency's name where a CSM
    expects their client's, in an answer whose entire content is client names.

    SO AN UNNAMEABLE CALL IS LISTED AS ITS FILENAME, not dropped and not guessed. Dropping
    it would UNDER-report the spread -- the opposite error, and a quieter one, since a CSM
    would read "two accounts" where the evidence says "two accounts and two calls we cannot
    attribute".

    THE ACCOUNT COUNT IS A RANGE, AND THAT IS THE HONEST SHAPE. Two named accounts plus two
    unnameable calls is somewhere between two and four distinct clients: each unnamed call
    might be a third and fourth client, or might be one of the two already listed. Reporting
    a single number would pick one end of that and state it as a fact about the book.

    Degrades rather than breaks when the participant sidecars are absent (criterion 3):
    `account_for` then names only what a FILENAME states, every UUID call becomes unnameable,
    and the answer gets thinner rather than wrong.
    """
    if not matches:
        # THE SAME RULE `RetrievalPool.top1` AND `answering.answer_situation` APPLY, and this
        # is the one rendered path where it had to be stated rather than inherited: an empty
        # authorised ranking is a fact about the INDEX, not about the corpus. Rendered as an
        # answer it would read "0 accounts, across 0 exchanges" -- which a CSM takes as "no
        # other client has ever raised this", the exact wrong conclusion this intent exists
        # to prevent, with a broken index hidden behind it for as long as nobody checked.
        raise RuntimeError(
            "retrieval returned no kb_pair the pool authorises -- the vector store and the "
            "pool disagree about what exists. Run ops/check_vector_coverage.py.")

    named: dict[str, dict] = {}
    unnamed: dict[str, dict] = {}
    for match in matches:
        call = match.pair["call_filename"]
        account = account_for(call)
        bucket, key = (named, account) if account else (unnamed, call)
        entry = bucket.setdefault(key, {"account": key, "named": bool(account),
                                        "exchanges": 0, "_calls": set()})
        entry["exchanges"] += 1
        entry["_calls"].add(call)

    def rows(bucket):
        out = []
        for entry in bucket.values():
            calls = entry.pop("_calls")
            out.append({**entry, "calls": len(calls)})
        # Most-carried first, then alphabetically so the order is stable across requests --
        # a list that reshuffles between two identical questions reads as new information.
        return sorted(out, key=lambda e: (-e["exchanges"], e["account"]))

    named_rows, unnamed_rows = rows(named), rows(unnamed)
    # THE NEAREST EXCHANGE'S SCENARIO, and how much of the neighbourhood agrees with it.
    #
    # #12's story 10 asks every answer to name the scenario it is about, and this path was
    # the one Layer B answer with no `match` block at all -- so a misroute had nothing to
    # give it away. It matters MORE here than elsewhere, because the answer is an aggregate
    # over 25 neighbours rather than one exchange: `ask-naren/audit/artifacts/
    # topk_headroom.json` measures the top-20 neighbourhood at a mean of only 6.19/20
    # same-situation (0.39/1 at top 1, 2.00/5, 3.31/10). So some of the accounts listed are
    # about something else.
    #
    # REPORTED, NOT FILTERED. Dropping the off-scenario neighbours would be a relevance rule
    # nobody has measured, and this project's bar for adding one is a measured failure, not
    # a plausible story (ADR 0005 applied that bar to a cosine floor and rejected it). What
    # the CSM needs is to be able to tell a genuine book-wide pattern from a wide,
    # incoherent neighbourhood -- and two numbers do that without deciding for them.
    scenario_key = matches[0].pair["scenario_key"]
    same_scenario = sum(1 for m in matches if m.pair["scenario_key"] == scenario_key)
    return {
        "outcome": RENDERED,
        "kind": WHERE_ELSE_SEEN,
        "asked_about": asked,
        "scenario_key": scenario_key,
        "same_scenario": same_scenario,
        # NAMED FIRST, whatever they carry. An unnameable call is real evidence but nothing
        # a CSM can act on, so it belongs below every account that has a name.
        "accounts": named_rows + unnamed_rows,
        #: A PLAIN FACT: how many accounts the recorded data could name. Not the floor of
        #: the range -- see below.
        "accounts_named": len(named_rows),
        #: The bottom of the range, and NOT the same number. With no participant sidecars
        #: every UUID call is unnameable and `accounts_named` is 0 -- but exchanges that
        #: exist came from SOMEBODY, so "between 0 and 3 accounts" states something
        #: impossible. One is the honest floor the moment any exchange was found.
        "accounts_at_least": max(len(named_rows), 1),
        #: The top: every unnameable CALL could be a client not already listed.
        "accounts_at_most": len(named_rows) + sum(e["calls"] for e in unnamed_rows),
        "unnamed_calls": sum(e["calls"] for e in unnamed_rows),
        "exchanges": sum(e["exchanges"] for e in named_rows + unnamed_rows),
        "basis": ("The nearest exchanges to what you asked, and which account each came "
                  "from. Only the recorded call participants name an account, so calls "
                  "without them are listed by filename rather than guessed -- which is why "
                  "the number of accounts is a range, not a count. Not every nearby "
                  "exchange is about the same situation; the count above says how many "
                  "are."),
    }


# -- the two composites (issue #23) --------------------------------------------------------
#
# BOTH RENDER, AND NEITHER GENERATES. #23 asks each to "compose existing answer paths rather
# than introducing a new grounding rule", and ADR 0009 warns that a composite stitching a
# Layer C summary onto a Layer B answer INHERITS THE WEAKER OF THE TWO GUARANTEES and should
# say so. The way not to inherit a weaker guarantee is not to take one on: compose only the
# RENDERED paths, and the composite keeps the structural guarantee both halves already have
# -- nothing was generated, so nothing can have been invented, and there is no gate to
# reconcile because neither half has one.
#
# That is a real constraint on what they can say, not a free win. Neither composite can
# summarise, prioritise or tailor its advice to the CSM's particular client; they assemble
# stored rows and let the CSM read. A generating version of `call_prep` -- "here is your
# brief" -- would be a better product and would inherit exactly the mixed guarantee ADR 0009
# describes. It is the obvious next ticket, not this one.

#: How many scenarios `call_prep` shows. A CSM about to join a call reads three things, not
#: eight, and the tail of a 25-exchange neighbourhood is mostly drift (`topk_headroom.json`:
#: a mean of 6.19/20 share the top hit's situation).
PREP_SCENARIOS = 3


def call_prep(asked: str, matches: list, *, scenarios: list[dict], playbook_for,
              label_for=citations.resolve_label) -> dict:
    """Preparing for a call on a topic (issue #23): what is likely to come up, the play for
    each, and a real exchange to read.

    THREE EXISTING PATHS COMPOSED, one per criterion clause. The likely SCENARIOS come from
    the neighbourhood, the same way `where_else_seen` reads one. Each PLAY is the scenario's
    `arc`, exactly what `sequence` renders. Each EXAMPLE is a stored exchange shown verbatim,
    exactly what `show_exchange` renders. Nothing here is a new way of knowing something.

    RANKED BY HOW MUCH OF THE NEIGHBOURHOOD EACH SCENARIO CARRIES, which is the only signal
    available that is not a cosine -- and ADR 0005 measured cosine as unable to separate
    right answers from wrong ones, so it must not become a relevance score here either.

    A SCENARIO WITH NO LIVE PLAYBOOK IS SHOWN WITH `has_play` FALSE rather than dropped or
    given an empty step list. 1 of 34 coachable scenarios has none. Dropping it would hide a
    thing the CSM should still expect on the call; an empty list reads as "there is no play",
    which is a different claim from "we have not recorded one".
    """
    if not matches:
        # The same rule as every other retrieving path: an empty authorised ranking is a
        # fact about the INDEX, not about the corpus (ADR 0008).
        raise RuntimeError(
            "retrieval returned no kb_pair the pool authorises -- the vector store and the "
            "pool disagree about what exists. Run ops/check_vector_coverage.py.")

    described = {s["scenario_key"]: (s.get("business_description") or "").strip()
                 for s in scenarios}
    grouped: dict[str, list] = {}
    for match in matches:
        grouped.setdefault(match.pair["scenario_key"], []).append(match)

    # MOST-CARRIED FIRST, AND TIES BROKEN BY NEARNESS. `grouped` is built by walking
    # `matches` nearest-first and Python's sort is stable, so sorting on the count alone
    # keeps the closer scenario ahead of an equally-common further one -- deterministic
    # without a second key.
    #
    # A `scenario_key` tiebreak looked tidier and was wrong. `topk_headroom.json` puts the
    # top-20 neighbourhood at a mean of 6.19/20 same-situation, so one scenario usually
    # dominates and the rest is a long tail of singletons -- which makes positions 2 and 3,
    # two of the three things a CSM is told to walk in ready for, decided by the tiebreak
    # nearly every time. Alphabetical would hand them to the earliest letter, and
    # `application_volume_and_prioritization` -- the catch-all ADR 0009 names, 11.8% of
    # coachable pairs with 16% of what routes there off-topic -- starts with 'a'.
    ranked = sorted(grouped.items(), key=lambda kv: -len(kv[1]))
    out = []
    for key, seen in ranked[:PREP_SCENARIOS]:
        playbook = ((playbook_for(key) if playbook_for else None) or {}).get("playbook") or {}
        steps = [str(s).strip() for s in (playbook.get("arc") or []) if str(s).strip()]
        example = seen[0].pair
        out.append({
            "scenario_key": key,
            "description": described.get(key, ""),
            "exchanges": len(seen),
            "has_play": bool(steps),
            "steps": steps,
            # Verbatim, for the reason `show_exchange` is verbatim: a CSM preparing for a
            # call wants to judge the fit themselves rather than read our summary of it.
            "example": {"client_said": example["trigger_text"],
                        "naren_replied": example["response_text"],
                        "citation": _citation(example, label_for)},
        })

    return {
        "outcome": RENDERED,
        "kind": CALL_PREP,
        "asked_about": asked,
        "scenarios": out,
        "scenarios_found": len(grouped),
        "exchanges": len(matches),
        "basis": ("The situations that come up most in the exchanges nearest to what you "
                  "described, each with its recorded play and one real moment to read. "
                  "Nothing here is written for you -- it is what is on file, so the "
                  "judgement about your client stays yours."),
    }


def improve_at_move(asked: str, scenario_key: str, record: dict,
                    label_for=citations.resolve_label) -> dict:
    """Getting better at one specific thing (issue #23): the criterion, its pitfalls, and
    Naren doing it.

    THREE PARTS OF ONE DOCUMENT, all rendered. The criterion is a `key_moves` entry, the
    same rows `procedure` answers from; the pitfalls are what `pitfalls` renders; the quotes
    are the move's own evidence, verbatim-snapped offline like every other playbook quote.

    THE MOVE IS CHOSEN BY PLAIN WORD OVERLAP with what the CSM asked -- deterministic, no
    model call and no second embedding. It is a weak matcher and it is meant to be: the
    alternative is asking a model which move they meant, which is a generation, an invention
    risk and a new failure mode on a path whose whole guarantee is that nothing was
    generated.

    NO MATCH SHOWS EVERY MOVE, and `focused` says which happened. Picking one on no evidence
    would answer a question the CSM did not ask, and the whole play is a useful answer to
    "help me get better at this" while a wrongly-picked move is not.

    *** IT FOCUSES 26% OF THE TIME, MEASURED 2026-09-09. *** Over eight realistic asks against
    all 33 live playbooks (264 pairs), the matcher picked a single move in 69. The reason is
    in the data: a live `key_moves` name averages 9.4 words and is a generated sentence
    ("Implement standardized campaign parameter structures and tracking solutions to eliminate
    attribution gaps"), not a short label, so a CSM's plain words rarely overlap one.

    So THREE QUARTERS OF THE TIME this answers with the whole play. That still delivers every
    part the ticket asks for -- the criteria, the pitfalls and Naren's own words -- but it is
    not narrowed to the one thing they named, and `focused` is what makes the difference
    visible instead of silent.

    RAISING IT WOULD NEED A LABELLED SET THAT DOES NOT EXIST. A looser matcher focuses more
    often and there is nothing to say whether it focuses on the RIGHT move; a higher rate
    bought that way is a worse answer that looks like a better one. This project's bar for a
    matching change is a measurement (ADR 0005 applied it to a retrieval floor and rejected
    it), and the honest state is that this one has a rate and no accuracy.
    """
    playbook = (record or {}).get("playbook") or {}
    moves = [m for m in (playbook.get("key_moves") or []) if (m.get("name") or "").strip()]
    chosen = _best_move(asked, moves)

    def rendered(move: dict) -> dict:
        return {
            "name": (move.get("name") or "").strip(),
            "criterion": (move.get("criterion") or "").strip(),
            "evidence": [{"quote": (e.get("quote") or "").strip(),
                          **_source((e.get("call") or "").strip(), label_for)}
                         for e in (move.get("evidence") or [])
                         if (e.get("quote") or "").strip()],
        }

    return {
        "outcome": RENDERED,
        "kind": IMPROVE_AT_MOVE,
        "asked_about": asked,
        "scenario_key": scenario_key,
        #: True when the CSM's own words picked the move out. False means this is the whole
        #: play rather than the one thing they asked about, which the page must say.
        "focused": chosen is not None,
        "moves": [rendered(chosen)] if chosen else [rendered(m) for m in moves],
        # The scenario's pitfalls, not the move's -- `pitfalls_and_variants` is a property of
        # the play rather than of a step, and there is no recorded link from one to the other.
        # Filtering by the same word overlap would be inventing that link.
        "pitfalls": pitfalls(scenario_key, playbook, label_for=label_for)["pitfalls"],
        "basis": ("The recorded criterion for this move, what tends to go wrong around it, "
                  "and Naren's own words doing it. All of it is on file rather than written "
                  "for you."),
    }


#: Words too common to carry a match. Small and literal, for the same reason `citations`'
#: token sets are: a general stop-word list is a dependency and a tuning knob, and this needs
#: to be readable by whoever debugs a wrong move six months from now.
_COMMON = frozenset(
    "a an and are as at be better but by can do does for from get getting good has have how "
    "i if in is it its me my of on or should so that the their them then there they this to "
    "up want was what when where which who why with you your at".split())


def _best_move(asked: str, moves: list[dict]) -> dict | None:
    """The move whose NAME the CSM's words overlap most, or None when nothing overlaps.

    Name only, not the criterion: a criterion is a sentence of our prose and long enough that
    almost anything overlaps it a little, which would make every question "focused" and the
    flag meaningless.
    """
    words = {w for w in _norm_words(asked) if w not in _COMMON}
    best, best_score = None, 0
    for move in moves:
        score = len(words & {w for w in _norm_words(move.get("name"))
                             if w not in _COMMON})
        if score > best_score:
            best, best_score = move, score
    return best


def _norm_words(text: str | None) -> set[str]:
    keep = "".join(c if c.isalnum() or c.isspace() else " " for c in (text or "").lower())
    return set(keep.split())


def _citation(pair: dict, label_for) -> dict:
    return {
        "label": label_for(pair["call_filename"]) or pair["call_filename"],
        "call_filename": pair["call_filename"],
        "pair_id": pair["pair_id"],
        "scenario_key": pair["scenario_key"],
    }


def _by_key(item: dict) -> str:
    return item["scenario_key"]
