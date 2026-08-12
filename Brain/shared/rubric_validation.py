"""Layer C's objective function: is a milestone worth scoring anyone against?

Design: docs/superpowers/specs/2026-08-11-layer-c-objective-function-design.md

WHY THIS EXISTS

Layer C admits a milestone on three gates -- distinct-call support (does it recur?),
relevance percentile (is it on-topic?) and the review-flag judge (is it plausible?).
Nothing measures the two properties the 2026-08-11 ceiling run proved actually matter:

  discrimination   can this criterion tell its own scenario apart from a different one?
  satisfiability   can anyone satisfy it when the moment calls for it?

So Layer C produces criteria that recur and are on-topic, because that is what it was
asked for. It is working as specified; the specification was incomplete. That is the
root cause behind four consecutive fixes each moving the hit rate slightly and none
breaking 4% -- every fix improved something nobody was measuring, against a target
nobody had defined.

This module is the pure half: the verdict rules, the staleness check, the parse of the
applicability judge's reply, and the JSONB merge. The Gemma calls, sampling and DB reads
live in calibration/validate_rubrics.py.

IT LIVES IN shared/, NOT calibration/, ON PURPOSE. Layer D consumes the verdict
(should_score below), and nothing in v1/, v2/, shared/ or preprocessing/ may import
calibration -- that separation is what keeps the measurement tooling out of the pipeline.
"""
from __future__ import annotations

import hashlib

# Pre-registered in the design spec before any data was seen. Both figures are INHERITED
# from the ceiling spec -- T_DISCRIMINATION is its instrument-validity gate and
# T_SATISFIABLE its "rubric or scorer fundamentally broken" threshold -- so this
# instrument is calibrated against a measurement that already exists rather than against
# fresh guesses.
T_DISCRIMINATION = 0.5      # W(B) >= this * W(A3)          -> not_discriminating
T_SATISFIABLE = 0.20        # W(A3 | applicable) < this     -> not_satisfiable
T_CONTINGENT = 0.50         # applicable_rate < this        -> contingent
MIN_APPLICABLE = 6          # fewer applicable instances    -> insufficient_evidence

VALIDATED = "validated"
NOT_DISCRIMINATING = "not_discriminating"
NOT_SATISFIABLE = "not_satisfiable"
CONTINGENT = "contingent"
INSUFFICIENT_EVIDENCE = "insufficient_evidence"

# Every verdict except these two means "do not score against this milestone".
# CONTINGENT is scored, but only where the applicability check passes for that response
# -- it is the fix for the dominant proximate cause (contingent moves emitted as
# mandatory), not a failure.
_SCOREABLE = frozenset({VALIDATED, CONTINGENT})


def weighted(hits: int, partial: int, attempts: int) -> float:
    """(hits + 0.5*partial) / attempts -- the definition used everywhere in this pipeline.

    Duplicated from score_naren_ceiling rather than imported: shared/ must not import
    calibration/, and this is four tokens of arithmetic pinned by tests on both sides.
    """
    return (hits + 0.5 * partial) / attempts if attempts else 0.0


def classify(a3: dict, b: dict, applicable: dict,
             applicability_scored: dict | None = None) -> dict:
    """The verdict for one milestone, plus every count needed to re-derive it.

    a3                    counters over ALL arm-A3 instances (call-level holdout,
                          matched rubric)
    b                     counters over ALL arm-B instances (same texts, unrelated
                          rubric)
    applicable            counters over the A3 subset the judge said was called for
    applicability_scored  counters over the A3 subset the judge ANSWERED AT ALL;
                          defaults to a3, i.e. every response was judged

    Each is {"attempts", "hits", "partial"}, the shape score_naren_ceiling.aggregate
    already produces.

    DISCRIMINATION USES UNCONDITIONAL COUNTS ON BOTH ARMS. Filtering arm B by
    applicability would shrink its denominator and inflate the null, which is the one
    way to make this instrument flatter itself.

    CONTINGENCY USES THE ANSWERED SUBSET as its denominator. If the judge dropped half a
    batch, dividing by the whole arm reports a mandatory milestone as contingent purely
    because of the drop -- a measurement gap disguised as a finding.
    """
    scored = applicability_scored if applicability_scored is not None else a3
    a3_w = weighted(a3["hits"], a3["partial"], a3["attempts"])
    b_w = weighted(b["hits"], b["partial"], b["attempts"])
    a3_w_applicable = weighted(applicable["hits"], applicable["partial"],
                               applicable["attempts"])
    applicable_rate = (applicable["attempts"] / scored["attempts"]
                       if scored["attempts"] else 0.0)

    record = {
        "a3_w": a3_w,
        "a3_w_applicable": a3_w_applicable,
        "b_w": b_w,
        "discrimination": a3_w - b_w,
        "applicable_rate": applicable_rate,
        "a3_attempts": a3["attempts"],
        "a3_applicable": applicable["attempts"],
        "a3_applicability_scored": scored["attempts"],
        "b_attempts": b["attempts"],
    }
    record["verdict"] = _verdict(a3_w, b_w, a3_w_applicable, applicable["attempts"],
                                 applicable_rate)
    return record


def _verdict(a3_w: float, b_w: float, a3_w_applicable: float,
             n_applicable: int, applicable_rate: float) -> str:
    """The §3.3 table, in the one order that keeps its §3.6 self-validation reproducible.

    `a3_w > 0` guards the discrimination gate. Without it the inequality reads 0 >= 0 for
    every milestone the author never hits, labelling all 65 zero-hit milestones
    `not_discriminating` -- and splitting exactly that population between
    `not_satisfiable` and `contingent` is the result this run exists to produce. A
    milestone nobody scores on has a satisfiability problem; calling it a discrimination
    problem is a category error. score_naren_ceiling's own gate carries the same guard.
    """
    if a3_w > 0 and b_w >= T_DISCRIMINATION * a3_w:
        return NOT_DISCRIMINATING
    if n_applicable < MIN_APPLICABLE:
        return INSUFFICIENT_EVIDENCE
    if a3_w_applicable < T_SATISFIABLE:
        return NOT_SATISFIABLE
    if applicable_rate < T_CONTINGENT:
        return CONTINGENT
    return VALIDATED


# --------------------------------------------------------------------------------------
# SCENARIO-level classification -- the resolution that actually held.
#
# The per-milestone verdicts above failed both of their own validity gates when measured
# 2026-08-12: at 8 attempts per arm W is quantized to steps of 0.0625, so the
# discrimination gate trips on a single stray partial hit in the control, and the 7
# scenarios the ceiling run proved were real working instruments produced 0 of 33
# scoreable milestones. The SAME comparison at scenario resolution -- 16 to 88 attempts
# aggregated across a rubric's milestones -- reproduced the ceiling run's published table
# exactly. Coarser, cheaper, and it is the one measurement in this line of work that has
# passed every check, so it is what a gate should be built on.
# --------------------------------------------------------------------------------------

SCENARIO_SHIP = "ship"
SCENARIO_HOLD = "hold"
SCENARIO_DISABLE = "disable"
SCENARIO_INSUFFICIENT = "insufficient_data"

# Verified against naren_ceiling.json 2026-08-12: at these values the reconstruction
# returns 40 qualifying scenarios, 16 discriminating, 7 zero-control and 7 inverted --
# the ceiling run's published table, to the number. The band applies in BOTH directions;
# reading "inverted" as merely gap < 0 gives 15 rather than 7.
SCENARIO_MIN_ATTEMPTS = 15
SCENARIO_BAND = 0.05


def classify_scenario(a3: dict, b: dict,
                      min_attempts: int = SCENARIO_MIN_ATTEMPTS,
                      band: float = SCENARIO_BAND) -> dict:
    """Ship / hold / disable one scenario's rubric, from its two arms.

    a3  counters over every A3 instance for this scenario (own rubric)
    b   counters over every B instance  (same shape, an unrelated rubric)

    Both arms must clear min_attempts: a scenario with plenty of matched attempts but a
    tiny control has no null worth comparing against. 33 of 82 rubrics have never been
    exercised at all, so `insufficient_data` is a real state and not an edge case --
    calling those broken would condemn a rubric on no evidence, and calling them fine
    would ship one on none.

    A control of exactly 0.000 ships regardless of band, but only when the matched arm
    scores something: 0.000 against 0.000 is silence on both sides, not an instrument.
    """
    a3_w = weighted(a3["hits"], a3["partial"], a3["attempts"])
    b_w = weighted(b["hits"], b["partial"], b["attempts"])
    gap = a3_w - b_w
    control_is_zero = b_w == 0.0 and a3_w > 0

    if a3["attempts"] < min_attempts or b["attempts"] < min_attempts:
        verdict = SCENARIO_INSUFFICIENT
    elif control_is_zero or gap > band:
        verdict = SCENARIO_SHIP
    elif gap < -band:
        verdict = SCENARIO_DISABLE
    else:
        verdict = SCENARIO_HOLD

    return {"verdict": verdict, "a3_w": a3_w, "b_w": b_w, "gap": gap,
            "a3_attempts": a3["attempts"], "b_attempts": b["attempts"],
            "control_is_zero": control_is_zero}


# --------------------------------------------------------------------------------------
# Staleness. A verdict describes the TEXT it was measured against, and that text is
# replaced in place by any Layer C run.
# --------------------------------------------------------------------------------------

def milestone_fingerprint(milestone: dict) -> str:
    """A digest of the exact text the grader is shown for this milestone.

    NOT the run_id the design sketched. Two reasons it has to be content, both fatal to
    the run_id version:

      * `rubrics` has no run_id column (db/schema.sql), so there is nothing on the row to
        compare a stored run id against.
      * run_id is a sha1 of the sorted transcript stems, so re-running Layer C over the
        SAME corpus yields the SAME run_id while UMAP+HDBSCAN produce a different
        milestone set (385/398/403/404 for byte-identical input). A run id would
        therefore match precisely in the case it exists to catch.

    Covers description AND detection_hint because score_milestones_batch sends both to
    the grader -- a milestone whose hint changed is not the criterion that was measured.
    validated_at_run is still recorded alongside, as provenance for a human reader.
    """
    payload = "\x00".join((str(milestone.get("description") or ""),
                           str(milestone.get("detection_hint") or "")))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def is_stale(milestone: dict) -> bool:
    """True when a verdict is present but no longer describes this milestone's text.

    Absent is NOT stale: "never measured" and "measured, then invalidated" are different
    states and the report must tell them apart. A verdict carrying no fingerprint at all
    is stale by definition -- it cannot be shown to describe the current text, and
    "probably still fine" is exactly how a stale verdict gets used.
    """
    validation = milestone.get("validation")
    if not validation:
        return False
    return validation.get("milestone_fingerprint") != milestone_fingerprint(milestone)


def validation_of(milestone: dict) -> dict | None:
    """This milestone's verdict, or None if it is absent or stale."""
    validation = milestone.get("validation")
    if not validation or is_stale(milestone):
        return None
    return validation


def should_score(milestone: dict, require_validated: bool,
                 milestone_id: str | None = None,
                 applicable_ids: set[str] | None = None) -> bool:
    """Whether Layer D may score THIS response against this milestone.

    With the flag off, everything is scoreable and behaviour is unchanged -- the same
    shipping posture as response_taxonomy_auto_pass_enabled.

    With it on, a milestone with no fresh verdict is NOT scored. Turning the flag on
    against a never-validated rubric therefore empties it; that is the honest outcome the
    design names as the reason it ships false and the first run must be read before
    flipping it.

    applicable_ids is the applicability judge's answer FOR THIS RESPONSE, and it gates
    `contingent` milestones only. A `validated` milestone is not filtered by it: it
    already cleared the contingency threshold corpus-wide, and filtering per response as
    well would apply the same correction twice.

    A contingent milestone with NO applicability information is NOT scored. Scoring it
    reinstates the exact defect this key exists to fix, and each resulting miss emits a
    Milestone_Omission gap -- coaching advice telling a CSM they failed to do something
    the moment never called for.

    Deliberately separate from is_uncoachable: that flag is a hand-audited judgement
    about 17 specific milestones, this is a measurement, and collapsing them would make
    it impossible to tell which one silenced a milestone.
    """
    if not require_validated:
        return True
    validation = validation_of(milestone)
    if not validation:
        return False
    verdict = validation.get("verdict")
    if verdict == CONTINGENT:
        return applicable_ids is not None and milestone_id in applicable_ids
    return verdict in _SCOREABLE


# --------------------------------------------------------------------------------------
# The applicability judge's reply
# --------------------------------------------------------------------------------------

def parse_applicability(raw, expected: dict[int, list[str]]
                        ) -> tuple[list[set[str] | None], dict]:
    """Which milestones each exchange actually called for.

    raw       Gemma's reply: a bare array, or {"results": [...]} -- both shapes occur,
              which is why CLAUDE.md requires the isinstance guard on every parse here.
    expected  {exchange index: [milestone ids in that exchange's rubric]}

    Returns (per-exchange applicable sets, report). An entry is None when the judge did
    not answer for that exchange at all.

    THE THIRD STATE IS THE WHOLE POINT. Defaulting an unanswered exchange to "all
    applicable" inflates the satisfiability denominator and makes a contingent milestone
    read unsatisfiable; defaulting it to "none applicable" manufactures contingency.
    Neither is a measurement, so an unanswered exchange is dropped from the analysis and
    counted out loud -- the same discipline as score_milestones_batch reporting a missing
    id rather than absorbing it as a miss.

    An empty list is NOT unanswered: it is the judge saying the moment called for none of
    these, which is exactly the observation a fully contingent milestone produces.
    """
    rows = raw if isinstance(raw, list) else (raw or {}).get("results", [])
    by_index: dict[int, list] = {}
    unknown_ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or "id" not in row:
            continue
        try:
            idx = int(str(row["id"]).lstrip("Ss"))
        except ValueError:
            continue
        if idx in expected:
            by_index[idx] = row.get("applicable") or []

    out: list[set[str] | None] = []
    for idx in sorted(expected):
        if idx not in by_index:
            out.append(None)
            continue
        allowed = set(expected[idx])
        got = set()
        for mid in by_index[idx]:
            if mid in allowed:
                got.add(mid)
            else:
                # An invented id means the judge is not tracking the id space, which
                # implies misattribution rather than mere omission -- a stronger warning
                # than a missing one.
                unknown_ids.append(f"S{idx}:{mid}")
        out.append(got)

    return out, {"unanswered": sum(1 for x in out if x is None),
                 "unknown_ids": unknown_ids}


# --------------------------------------------------------------------------------------
# The write path
# --------------------------------------------------------------------------------------

def with_validation(milestone: dict, record: dict, run_id: str,
                    scored_by: str | None = None) -> dict:
    """A COPY of the milestone carrying its verdict.

    Merges rather than replaces, and returns a new dict rather than mutating: everything
    already on the milestone -- the Layer C support evidence gap_events copies, plus
    criteria_rewritten and not_coachable_flag from the two earlier repair passes -- is
    destroyed permanently if this drops it, because upsert_rubric replaces the whole
    `milestones` column.

    The fingerprint is taken from the milestone as written, so a verdict is fresh the
    moment it lands and goes stale the moment Layer C rewords the criterion.
    """
    out = dict(milestone)
    validation = dict(record)
    validation["milestone_fingerprint"] = milestone_fingerprint(milestone)
    validation["validated_at_run"] = run_id
    validation["scored_by"] = scored_by
    out["validation"] = validation
    return out
