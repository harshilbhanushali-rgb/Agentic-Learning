"""The Layer D scenario-population split. Pure -- no DB, no I/O, no Gemma.

`scenarios` has been a TWO-population table since the 2026-07-27 evidence-triage
rework: coachable scenarios plus non-coachable sinks (mechanics, logistics,
backchannel) kept deliberately as landfill for junk Layer B matches. Layer D was
written before that and still treats the table as a flat list of coachable topics.

The fix is not one filter, because the two Step 0 modes need sinks for OPPOSITE
reasons:

  full map (all rows)   -> similarity mode's vector pool. A sink winning the match
                           is the ONLY mechanism that says "this client turn is not
                           a signal". Remove sinks and the best match is a
                           non-sink by definition, so the relative margin admits
                           every turn -- which is the old absolute-0.35-floor
                           pathology in a new shape, not a fix for it.

  coachable map         -> the gemma-mode prompt. Listing
                           `conversational_confirmation_and_fillers` as a
                           detectable scenario is an INVITATION to report
                           backchannel as coachable. This is the root cause the
                           2026-07-06 zero-hit-rate investigation landed on:
                           topic-irrelevant small talk matched to real scenarios.

So the split lives here, applied per mode by the caller, and NOT inside
storage.get_scenarios or pipeline._load_scenario_map -- a filter at either of those
points removes similarity mode's only rejection mechanism.

Keys off `is_coachable` and nothing else:

  * NOT cluster_kind. Equivalent on today's live data (66 mechanics + 10 logistics
    == the 76 is_coachable=false rows) but is_coachable is what
    shared.relative_match.is_sink_flags and layer_b.assign_scenarios branch on.
    Layer D must not invent a second definition of "sink"; two definitions that
    agree today is a latent bug.

  * NOT rubric_status. A 'skipped_insufficient_responses' scenario is a genuinely
    coachable topic that merely lacks the evidence for a rubric yet. Its signals are
    the single most useful thing Layer D produces -- they say "a client raised this
    and we have no answer key". Filtering it out at detection time would hide that
    coverage gap instead of reporting it (pipeline.py writes a Rubric_Coverage_Gap
    for exactly this case).

  * NEVER a hardcoded key list. response_taxonomy_auto_pass graduates sinks into
    coachable scenarios between runs, so the split must be re-derived from the DB
    every run or a newly-graduated scenario stays invisible to Layer D forever.
"""
from __future__ import annotations


def is_coachable(info: dict) -> bool:
    """Whether one scenario row is coachable. Defaults True on a missing key, so a
    hand-built map in a test need not spell it out -- matching
    shared.relative_match.is_sink_flags."""
    return bool(info.get("is_coachable", True))


def coachable_only(scenario_map: dict[str, dict]) -> dict[str, dict]:
    """The subset Layer D is allowed to detect and score against."""
    return {k: v for k, v in scenario_map.items() if is_coachable(v)}


def sink_keys(scenario_map: dict[str, dict]) -> set[str]:
    """The non-coachable keys, for reporting a leak rather than filtering."""
    return {k for k, v in scenario_map.items() if not is_coachable(v)}


def pool_summary(scenario_map: dict[str, dict]) -> str:
    """One-line description of the split, for the run log.

    Breaks the sinks down by cluster_kind so a reader can see whether the sink
    population still looks like the taxonomy they calibrated, and counts coachable
    scenarios with no rubric because that number IS the Rubric_Coverage_Gap surface.
    """
    total = len(scenario_map)
    coachable = coachable_only(scenario_map)
    sinks = [v for k, v in scenario_map.items() if k not in coachable]
    kinds: dict[str, int] = {}
    for v in sinks:
        kind = v.get("cluster_kind") or "unknown"
        kinds[kind] = kinds.get(kind, 0) + 1
    kind_text = " / ".join(f"{n} {k}" for k, n in sorted(kinds.items())) or "none"
    no_rubric = sum(
        1 for v in coachable.values() if v.get("rubric_status") != "rubric_generated"
    )
    return (
        f"Scenario pool: {total} total, {len(coachable)} coachable, "
        f"{len(sinks)} sink ({kind_text}). Gemma prompt lists {len(coachable)}. "
        f"{no_rubric} coachable scenario(s) have no rubric."
    )
