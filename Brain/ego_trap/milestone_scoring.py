"""Step 3: score a CSM's response against a rubric's milestones and soft skills.

Both scorers are batched -- one Gemma call covers every milestone (or every soft
skill) across every signal in the batch. The non-batched per-milestone variants were
deleted: nothing but their own tests called them, and keeping a second prompt that
states the verdict rules while never being exercised is how a rule change lands in
only one of two places.
"""
from __future__ import annotations

from config import Config
from shared import gemma as _gemma
from shared import coverage_areas
from shared import rubric_validation
from shared.gemma import call_gemma
from shared.prompts import (
    PROMPT_MILESTONE_APPLICABILITY_BATCH,
    PROMPT_STEP3_COVERAGE_SCORE_BATCH,
    PROMPT_STEP3_MILESTONE_SCORE_BATCH,
    PROMPT_STEP3_SOFT_SKILL_SCORE_BATCH,
)

# Layer D scores with flash-lite as PRIMARY, not gemma-4-31b-it.
#
# Measured 2026-08-10: gemma-4-31b-it has a 16k tokens-per-minute limit, while one
# scoring batch is ~20k tokens (each milestone line repeats the benchmark responses --
# see _GEMMA_BATCH_SIZE in pipeline.py). A single batch therefore cannot fit inside the
# TPM budget, so EVERY call was guaranteed to 429 and escalate. Observed 2 escalations
# per successful batch: the strong model was never doing the work, it was just burning a
# round trip first.
#
# Making the real worker explicit is a correctness fix, not only a speed one. While the
# chain downgraded silently, a stored verdict had unknown provenance -- which is why
# three separate 0%-hit-rate measurements could not be interpreted. Now the requested
# model is deliberate and the model that ANSWERED is recorded per result (`scored_by`).
#
# gemma-4-31b-it stays last in the chain: if both flash-lites are rate limited it is
# better to score with the strong model slowly than to fail the batch.
_SCORING_MODEL = "gemini-3.1-flash-lite"
_SCORING_FALLBACKS = ("gemini-3.5-flash-lite", "gemma-4-31b-it")

# call_gemma's default is 8192. A batch of 8 signals x ~5 milestones = ~40 verdicts, and
# each verdict carries reason + quote + gap_to_ideal, so ~125 tokens each => ~5k. That
# fits, but with little margin, and OVERFLOW IS SILENT: the JSON array gets truncated,
# the tail of ids never arrives, and every dropped milestone is stored as a miss. Raised
# so the batch-size ceiling is set by prompt quality rather than by output truncation,
# and score_milestones_batch now reports any shortfall explicitly.
_SCORING_MAX_OUTPUT_TOKENS = 16384

_DEFAULT_SKILL_NAME = "Soft Skill Execution"

# Output-vocabulary contracts. These mirror what the prompts ask for, exactly as
# storage._VALID_BLOOM_LEVELS mirrors the DB CHECK constraint -- so they stay module
# constants rather than tuning.yaml keys, which that file bars curated lists from.
_VALID_VERDICTS = {"full_hit", "partial_hit", "miss"}
_VALID_RATINGS = {"excellent", "adequate", "failing"}
_DEFAULT_RATING = "adequate"

# The clustering evidence v2/layer_c._finish_rubric writes onto each milestone.
# Absent on v1-fallback rubrics, which are a NORMAL part of the population, not an
# edge case.
_EVIDENCE_FIELDS = (
    "support_calls", "support_clauses", "relevance_mean",
    "position_variance", "sequencing_type", "source_v",
)


def milestone_ids(milestones: list[dict]) -> list[str]:
    """Stable, collision-free ids for one rubric's milestone list.

    The id is the milestone's 1-BASED POSITION in rubrics.milestones, NOT its 'order'
    field. Three reasons, all load-bearing:

      * v1-fallback rubrics store Gemma's raw array with zero validation
        (v1/layer_c.py), and PROMPT_LAYER_C_V1 only *asks* for 'order'. Reading
        milestone['order'] therefore KeyErrors on real data and kills the whole run.
        Those fallbacks are common, not rare -- one measured snapshot had 31 of 82
        scenarios entirely fallback.
      * Two milestones sharing an 'order' value collapse into ONE
        milestone_performance row, because its PK is
        (csm_id, rubric_id, milestone_id). Two distinct milestones' hit/miss counters
        then merge silently and permanently.
      * MIGRATION GUARANTEE: v2 writes order = order_idx + 1 over the same list it
        stores, so for every v2 rubric the positional id is byte-identical to the old
        f"M{order}". No existing milestone_performance row is orphaned by this change.

    Not a content hash of the description: Gemma rewords descriptions on every Layer C
    run, so a hashed id would fragment one CSM's performance history across runs.
    """
    return [f"M{i + 1}" for i in range(len(milestones))]


def milestone_evidence(milestone: dict) -> dict:
    """The Layer C clustering evidence behind one milestone.

    Every field defaults to None, never 0. support_calls=0 would assert "this
    milestone recurs in zero calls", which is false; None correctly says "never
    measured" -- the honest state for a v1-fallback milestone. source_v is the
    cheapest per-milestone v1/v2 discriminator a reader gets.

    sequencing_type is RECORDED here but deliberately not acted on. It is produced by
    v2/layer_c._sequence_milestones, which only runs for position_variance > 0.3 and
    only assigns a verdict when a short Gemma label happens to appear as a substring
    of two raw clauses -- so it is rarely populated. And PROMPT_LAYER_C_V2_ORDER
    defines 'conditional' as "position depends on context", i.e. ordering variance,
    NOT "this milestone is optional". Scoring a conditional miss differently would be
    reading a meaning into a field never measured for it, and excluding it from
    `attempts` would shrink the score denominator and flatter CSMs with no audit
    trail. Persisting it makes its real distribution visible in production data for
    the first time; that is the prerequisite for any rule, and any such rule belongs
    at query time over gap_events.gaps, not in a new column.
    """
    return {field: milestone.get(field) for field in _EVIDENCE_FIELDS}


def _normalize_verdict(raw: dict) -> str:
    verdict = raw.get("verdict")
    return verdict if verdict in _VALID_VERDICTS else "miss"


def _normalize_rating(raw: dict, skill_name: str) -> str:
    """Clamp Gemma's soft-skill rating into the vocabulary gap_output branches on.

    gap_output emits a Soft_Skill_Failure only on "failing", so before the prompt
    enumerated its allowed ratings a returned "poor" or "weak" produced no gap and no
    trace at all. The prompt now lists the three; this is the net for when it answers
    anyway, and the warning is the half of the fix that makes the silence visible.

    Clamps to "adequate", not "failing": mapping an unparseable string to a failure
    would put a fabricated coaching finding in front of a human. Clamp-and-warn rather
    than raise, mirroring storage.upsert_scenario's bloom_level handling, so one bad
    rating cannot strand an expensive Gemma batch unwritten mid-run.

    Not a synonym map ("poor" -> "failing"): that is a curated list, and it would let
    prompt drift silently manufacture findings. Constrain the model; this is only the
    net.
    """
    rating = raw.get("rating")
    if rating in _VALID_RATINGS:
        return rating
    if rating is not None:
        print(
            f"  ! Invalid soft-skill rating {rating!r} for {skill_name!r} "
            f"-- defaulting to {_DEFAULT_RATING!r}"
        )
    return _DEFAULT_RATING


def is_uncoachable(milestone: dict) -> bool:
    """Whether ops/flag_uncoachable_milestones.py marked this milestone unsatisfiable.

    Measured 2026-08-10: the 17 flagged milestones took 74 attempts and returned 0 hits.
    Scoring against them does not merely add noise -- each miss emits a Milestone_Omission
    gap with a gap_to_ideal, producing coaching advice that instructs a CSM to do something
    they structurally cannot do (use seniority they lack, tell a personal anecdote, offer to
    screen-share).
    """
    return bool(milestone.get("not_coachable_flag"))


def score_milestones_batch(
    items: list[dict], config: Config, skip_uncoachable: bool = False,
    require_validated: bool = False,
    applicable_by_item: list[set[str] | None] | None = None,
    show_benchmark: bool = True,
) -> list[list[dict]]:
    """One Gemma call scores every milestone across all items at once.

    items: [{"rubric": dict, "csm_response_text": str, "benchmark_response": str}]
    Returns a per-item list of milestone results, same order and length as items.

    skip_uncoachable drops milestones flagged not_coachable_flag: they are never sent to
    Gemma, so they produce no verdict, no milestone_performance row and no gap -- see
    is_uncoachable.

    require_validated additionally drops any milestone without a FRESH `validated` or
    `contingent` verdict from calibration/validate_rubrics.py (layer_d.
    require_validated_milestones). applicable_by_item carries the applicability judge's
    answer per item and gates `contingent` milestones only -- see
    shared.rubric_validation.should_score for why an unknown answer means "do not score".
    The two switches are independent: a milestone failing either is out, and keeping them
    separate is what lets a reader tell which one silenced it.

    show_benchmark=False withholds Naren's reference responses. Arm 0b of the
    profile-rebuild trial exists to measure what they are doing: the grader may be partly
    answering "does this look like the reference?" rather than "does this satisfy the
    criterion?", and because the benchmark travels with the RUBRIC that resemblance would
    inflate the unrelated-rubric null -- two competent sales responses resemble each other
    whatever the topic. Withholding it also removes leak 1 entirely rather than managing
    it, which is the only reason the call-level holdout machinery exists at all.

    Ids are still computed over the FULL milestone list before ANY filtering, because
    milestone_id is the array POSITION; deriving them from a filtered list would renumber
    every later milestone and silently repoint existing milestone_performance rows at the
    wrong criterion.
    """
    entries = []
    blocks = []
    for i, item in enumerate(items):
        milestones = item["rubric"].get("milestones") or []
        if not milestones:
            continue
        applicable = applicable_by_item[i] if applicable_by_item else None
        # The benchmark and CSM response are stated ONCE per exchange, not once per
        # milestone. Repeating them per milestone was ~4x the tokens for identical text.
        ms_lines = []
        # zip over the FULL list so milestone_id stays the true array position even when
        # some are skipped below.
        for milestone_id, milestone in zip(milestone_ids(milestones), milestones):
            if skip_uncoachable and is_uncoachable(milestone):
                continue
            if not rubric_validation.should_score(
                milestone, require_validated, milestone_id, applicable
            ):
                continue
            entries.append((i, milestone_id, milestone))
            ms_lines.append(
                f"    - id: S{i}_{milestone_id}\n"
                f"      MILESTONE: {milestone.get('description', '')}\n"
                f"      DETECTION HINT: {milestone.get('detection_hint', '')}"
            )
        if not ms_lines:
            continue
        benchmark_line = (
            f"  NAREN'S BENCHMARK RESPONSE (for reference only): "
            f"{item['benchmark_response']}\n" if show_benchmark else ""
        )
        blocks.append(
            f"- EXCHANGE {i}\n"
            + benchmark_line
            + f"  CSM RESPONSE: \"{item['csm_response_text']}\"\n"
            f"  MILESTONES TO SCORE:\n" + "\n".join(ms_lines)
        )

    results_by_item: list[list[dict]] = [[] for _ in items]
    if not entries:
        return results_by_item

    prompt = PROMPT_STEP3_MILESTONE_SCORE_BATCH.format(items_block="\n\n".join(blocks))
    raw = call_gemma(
        prompt, config.gemma_api_keys,
        model=_SCORING_MODEL, fallback_models=_SCORING_FALLBACKS,
        max_output_tokens=_SCORING_MAX_OUTPUT_TOKENS,
    )
    scored_by = _gemma.LAST_MODEL_USED
    raw_list = raw if isinstance(raw, list) else raw.get("results", [])
    by_id = {r["id"]: r for r in raw_list if "id" in r}

    # A missing id becomes a "miss" (see _normalize_verdict), so an id the model simply
    # failed to return is INDISTINGUISHABLE from a real miss in the stored data. That is
    # the quiet way output truncation manufactures a 0% hit rate: overflow
    # max_output_tokens, lose the tail of the array, and every dropped milestone is
    # recorded as a coaching failure. Report it loudly instead of absorbing it.
    expected = {f"S{i}_{mid}" for i, mid, _ in entries}
    missing = expected - set(by_id)
    unexpected = set(by_id) - expected
    if missing:
        print(
            f"  ! Step 3 returned {len(by_id)}/{len(expected)} milestone verdicts "
            f"({len(missing)} missing) from {scored_by}. Missing ids default to 'miss', "
            f"so this run's hit rate is a LOWER BOUND, not a measurement. Reduce "
            f"_GEMMA_BATCH_SIZE if this persists."
        )
    if unexpected:
        # Invented ids mean the model is not tracking the id space -- a stronger signal
        # of batch overload than a missing id, because it implies misattribution too.
        print(f"  ! Step 3 returned {len(unexpected)} id(s) that were never asked for: "
              f"{sorted(unexpected)[:5]} — verdicts may be misattributed.")

    for i, milestone_id, milestone in entries:
        r = by_id.get(f"S{i}_{milestone_id}", {})
        results_by_item[i].append({
            "milestone_id": milestone_id,
            "milestone_description": milestone.get("description", ""),
            # The rubric's own 'order' claim, kept for audit but never trusted for
            # identity -- see milestone_ids.
            "milestone_order": milestone.get("order"),
            "evidence": milestone_evidence(milestone),
            # Which model actually produced this verdict. Persisted into gap_events so a
            # future reader can tell a flash-lite score from a gemma-4-31b one instead of
            # having to guess, as every prior run required.
            "scored_by": scored_by,
            "verdict": _normalize_verdict(r),
            "confidence": r.get("confidence", "low"),
            "reason": r.get("reason", ""),
            "quote": r.get("quote", ""),
            "gap_to_ideal": r.get("gap_to_ideal", ""),
        })
    return results_by_item


def _is_contingent(milestone: dict) -> bool:
    validation = rubric_validation.validation_of(milestone)
    return bool(validation) and validation.get("verdict") == rubric_validation.CONTINGENT


def judge_applicability_batch(
    items: list[dict], config: Config, include=None
) -> list[set[str] | None]:
    """Which milestones each client turn actually called for.

    items: [{"rubric": dict, "client_utterance": str}]
    include: predicate over a milestone; defaults to "carries a fresh contingent verdict"
    Returns one entry per item: the applicable milestone ids, or None when the judge did
    not answer for that exchange (see rubric_validation.parse_applicability for why the
    third state exists rather than a default).

    LAYER D ASKS ONLY ABOUT CONTINGENT MILESTONES. A `validated` milestone already
    cleared the contingency threshold corpus-wide, so filtering it per response would
    apply the same correction twice and spend tokens doing it; a milestone gated out for
    any other reason is never scored, so its answer could not be used. An item with
    nothing to ask costs no line, and a batch with nothing to ask costs no call.

    calibration/validate_rubrics.py overrides `include` to ask about EVERYTHING, because
    it is measuring applicable_rate for milestones that have no verdict yet -- under the
    default selection nothing would be contingent and the measurement would silently come
    back empty.

    The CSM's response is deliberately not passed in and not shown. The question is
    whether the moment called for the move; a judge shown the response answers whether
    the move was made, which is what score_milestones_batch already measures.
    """
    include = include or _is_contingent
    expected: dict[int, list[str]] = {}
    blocks = []
    for i, item in enumerate(items):
        milestones = item["rubric"].get("milestones") or []
        lines = []
        for milestone_id, milestone in zip(milestone_ids(milestones), milestones):
            if not include(milestone):
                continue
            lines.append(
                f"    - id: {milestone_id}\n"
                f"      MILESTONE: {milestone.get('description', '')}\n"
                f"      DETECTION HINT: {milestone.get('detection_hint', '')}"
            )
            expected.setdefault(i, []).append(milestone_id)
        if lines:
            blocks.append(
                f"- EXCHANGE S{i}\n"
                f"  CLIENT TURN: \"{item['client_utterance']}\"\n"
                f"  MILESTONES:\n" + "\n".join(lines)
            )

    if not blocks:
        return [None] * len(items)

    raw = call_gemma(
        PROMPT_MILESTONE_APPLICABILITY_BATCH.format(items_block="\n\n".join(blocks)),
        config.gemma_api_keys,
        model=_SCORING_MODEL, fallback_models=_SCORING_FALLBACKS,
        max_output_tokens=_SCORING_MAX_OUTPUT_TOKENS,
    )
    parsed, report = rubric_validation.parse_applicability(raw, expected)
    if report["unanswered"]:
        print(f"  ! Applicability judge answered "
              f"{len(expected) - report['unanswered']}/{len(expected)} exchange(s). "
              f"Unanswered exchanges score NO contingent milestone, so this run's "
              f"contingent coverage is a LOWER BOUND.")
    if report["unknown_ids"]:
        print(f"  ! Applicability judge returned {len(report['unknown_ids'])} id(s) "
              f"never asked for: {report['unknown_ids'][:5]} — answers may be "
              f"misattributed.")

    # parse_applicability returns one entry per key of `expected`, in sorted key order;
    # re-expand to one entry per ITEM so a caller can index by position. Items with
    # nothing to ask stay None, which is correct -- they have no contingent milestone to
    # gate.
    by_index = dict(zip(sorted(expected), parsed))
    return [by_index.get(i) for i in range(len(items))]


def score_soft_skills_batch(items: list[dict], config: Config) -> list[list[dict]]:
    """One Gemma call scores every soft skill across all items at once.

    items: [{"rubric": dict, "csm_response_text": str, "skill_names": list[str]}]
    Returns a per-item list of soft-skill results, same order and length as items.
    """
    entries = []
    lines = []
    for i, item in enumerate(items):
        soft_skill_rubric = item["rubric"].get("soft_skill_rubric") or {}
        if not soft_skill_rubric:
            continue
        names = item["skill_names"] or [_DEFAULT_SKILL_NAME]
        for k, skill_name in enumerate(names):
            # Positional, not f"S{i}_{name.replace(' ', '_')}": that collided
            # "Active Listening" with "Active_Listening" and let a name containing a
            # newline corrupt the items block. Same positional-identity argument as
            # milestone_ids.
            entry_id = f"S{i}_K{k}"
            entries.append((i, skill_name, entry_id))
            lines.append(
                f"- id: {entry_id}\n"
                f"  SOFT SKILL: {skill_name}\n"
                f"  EXCELLENT EXECUTION: {soft_skill_rubric.get('excellent_execution', '')}\n"
                f"  FAILING EXECUTION: {soft_skill_rubric.get('failing_execution', '')}\n"
                f"  CSM RESPONSE: \"{item['csm_response_text']}\""
            )

    results_by_item: list[list[dict]] = [[] for _ in items]
    if not lines:
        return results_by_item

    prompt = PROMPT_STEP3_SOFT_SKILL_SCORE_BATCH.format(items_block="\n\n".join(lines))
    raw = call_gemma(prompt, config.gemma_api_keys)
    raw_list = raw if isinstance(raw, list) else raw.get("results", [])
    by_id = {r["id"]: r for r in raw_list if "id" in r}

    for i, skill_name, entry_id in entries:
        r = by_id.get(entry_id, {})
        results_by_item[i].append({
            "skill": skill_name,
            "rating": _normalize_rating(r, skill_name),
            "confidence": r.get("confidence", "low"),
            "reason": r.get("reason", ""),
        })
    return results_by_item


def score_coverage_batch(items: list[dict], config: Config) -> list[list[dict]]:
    """One Gemma call scores every COVERAGE AREA across all items at once.

    items: [{"rubric": {"areas": [...]}, "client_utterance": str,
             "csm_response_text": str, "benchmark_response": str}]
    Returns a per-item list of results, same order and length as items.

    The counterpart to score_milestones_batch for the profile-rebuild trial's coverage
    arms. Area ids are positional (C1, C2, ...) for the same reason milestone ids are:
    identity must not move when a re-run rewords something.

    A missing id defaults to not_covered rather than not_called_for -- see
    coverage_areas.normalize_verdict. Defaulting to not_called_for would shrink the
    denominator and flatter the score, which is the one failure direction nothing
    downstream can detect.
    """
    entries, blocks = [], []
    for i, item in enumerate(items):
        areas = (item["rubric"].get("areas") or [])
        if not areas:
            continue
        lines = []
        for area in areas:
            entry_id = f"S{i}_{area['id']}"
            entries.append((i, area, entry_id))
            lines.append(
                f"    - id: {entry_id}\n"
                f"      AREA: {area.get('description', '')}\n"
                f"      CALLED FOR WHEN: {area.get('precondition') or 'any turn'}"
            )
        blocks.append(
            f"- EXCHANGE {i}\n"
            f"  CLIENT TURN: \"{item.get('client_utterance', '')}\"\n"
            f"  REP RESPONSE: \"{item['csm_response_text']}\"\n"
            f"  COVERAGE AREAS:\n" + "\n".join(lines)
        )

    results_by_item: list[list[dict]] = [[] for _ in items]
    if not entries:
        return results_by_item

    raw = call_gemma(
        PROMPT_STEP3_COVERAGE_SCORE_BATCH.format(items_block="\n\n".join(blocks)),
        config.gemma_api_keys,
        model=_SCORING_MODEL, fallback_models=_SCORING_FALLBACKS,
        max_output_tokens=_SCORING_MAX_OUTPUT_TOKENS,
    )
    scored_by = _gemma.LAST_MODEL_USED
    raw_list = raw if isinstance(raw, list) else raw.get("results", [])
    by_id = {r["id"]: r for r in raw_list if isinstance(r, dict) and "id" in r}

    missing = {e for _, _, e in entries} - set(by_id)
    if missing:
        print(f"  ! Coverage scoring returned {len(by_id)}/{len(entries)} verdicts "
              f"({len(missing)} missing) from {scored_by}. Missing ids default to "
              f"'not_covered', so this run's rate is a LOWER BOUND.")

    for i, area, entry_id in entries:
        r = by_id.get(entry_id, {})
        results_by_item[i].append({
            "area_id": area["id"],
            "area_description": area.get("description", ""),
            "verdict": coverage_areas.normalize_verdict(r),
            "confidence": r.get("confidence", "low"),
            "reason": r.get("reason", ""),
            "quote": r.get("quote", ""),
            "gap_to_ideal": r.get("gap_to_ideal", ""),
            "scored_by": scored_by,
        })
    return results_by_item
