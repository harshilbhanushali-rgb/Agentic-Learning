"""Call-level milestone scoring: one request covers the whole transcript, several scenarios.

Design: docs/superpowers/specs/2026-08-15-layer-d-call-level-scoring-design.md
Gated by `layer_d.scoring_unit: call`. The shipped default is `moment` and nothing here runs
until that key is deliberately changed.

WHY THIS EXISTS. `milestone_scoring.score_milestones_batch` scores a reply against criteria
over a 1-3 turn response window. A CSM who answers the budget question ten turns later, or
pre-empts it before the client asks, is recorded as a miss purely because of where the window
stopped. This scores the whole call instead.

WHAT IT IS NOT A FIX FOR, measured before it was built: the ~9% hit rate. Per-reply credit
14.9% vs per-CALL credit 16.7%, and of the 87 criteria never credited on any reply, ZERO were
credited anywhere in any call. Those moves are never performed at all -- they are the expert's
seniority and relationship behaviour, and they are handled by the onboarding review, not here.

PURE BY DESIGN. Everything in this module except `score_call` is a pure function over plain
data: no DB, no embedder, no LLM. That is what lets the chunking, the parsing, the
missing-id defaulting and the quote verification be tested without a network, and it is the
same split `shared/cluster_evidence.py` uses.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from config import Config
from shared import gemma as _gemma
from shared.gemma import call_gemma
from shared.prompts import PROMPT_STEP3_CALL_LEVEL_BATCH

from .milestone_scoring import (
    _normalize_verdict,
    is_uncoachable,
    milestone_evidence,
    milestone_ids,
)

_SCORING_MODEL = "gemini-3.1-flash-lite"
_SCORING_FALLBACKS = ("gemini-3.5-flash-lite", "gemma-4-31b-it")
_SCORING_MAX_OUTPUT_TOKENS = 16384


@dataclass(frozen=True)
class ScenarioBlock:
    """One candidate situation to ask about, with everything needed to score it."""

    scenario_key: str
    description: str
    rubric: dict
    trigger_turns: list[tuple[int, str]] = field(default_factory=list)
    benchmark_response: str = ""


def chunk_scenarios(blocks: list[ScenarioBlock], per_request: int) -> list[list[ScenarioBlock]]:
    """Split candidate scenarios into per-request groups.

    The binding constraint is OUTPUT length, not request count: at 20 milestones per request
    one batch in 21 returned truncated JSON during the criteria rewrite, and a missing id is
    recorded as a MISS -- so truncation manufactures coaching failures instead of erroring.
    """
    if per_request < 1:
        raise ValueError(f"scenarios_per_request must be >= 1, got {per_request}")
    return [blocks[i:i + per_request] for i in range(0, len(blocks), per_request)]


def format_transcript(turns: list[tuple[str, str]]) -> str:
    """Number every turn. The numbers are the address space `turn` refers back to.

    Numbering is 1-based over the turns AS PASSED, so the caller's list order is the
    contract. A verdict's turn number is only checkable against the same list.
    """
    return "\n".join(f"[{i}] {speaker}: {' '.join((text or '').split())}"
                     for i, (speaker, text) in enumerate(turns, start=1))


def build_situations_block(chunk: list[ScenarioBlock], skip_uncoachable: bool = False
                           ) -> tuple[str, dict[str, list[tuple[str, dict]]]]:
    """Render one chunk, and return the id -> milestone map needed to reconcile the reply.

    Ids are computed over the FULL milestone list before ANY filtering, because milestone_id
    is the array POSITION -- deriving them from a filtered list would renumber every later
    milestone and silently repoint existing milestone_performance rows at the wrong criterion.
    """
    parts: list[str] = []
    expected: dict[str, list[tuple[str, dict]]] = {}
    for i, b in enumerate(chunk):
        milestones = b.rubric.get("milestones") or []
        lines: list[str] = []
        kept: list[tuple[str, dict]] = []
        for mid, m in zip(milestone_ids(milestones), milestones):
            if skip_uncoachable and is_uncoachable(m):
                continue
            kept.append((mid, m))
            lines.append(f"      - id: {mid}\n"
                         f"        MILESTONE: {m.get('description', '')}\n"
                         f"        DETECTION HINT: {m.get('detection_hint', '')}")
        if not lines:
            continue
        sid = f"S{i}"
        expected[sid] = kept
        trig = "\n".join(f"      [{n}] {' '.join(t.split())}" for n, t in b.trigger_turns[:4])
        bench = (f"    EXPERT REFERENCE ANSWER: {b.benchmark_response}\n"
                 if b.benchmark_response else "")
        parts.append(
            f"- SITUATION {sid}: {b.scenario_key}\n"
            f"    WHAT IT IS: {b.description}\n"
            + (f"    CLIENT TURNS THAT APPEAR TO RAISE IT:\n{trig}\n" if trig else "")
            + bench
            + "    MILESTONES TO SCORE:\n" + "\n".join(lines))
    return "\n\n".join(parts), expected


def parse_response(raw, expected: dict[str, list[tuple[str, dict]]],
                   chunk: list[ScenarioBlock]) -> tuple[list[dict], list[str]]:
    """Reconcile the model's reply against what was asked. Returns (results, warnings).

    A scenario the model never mentioned is treated as NOT OCCURRED rather than as all-miss.
    That direction is deliberate: the alternative silently converts a dropped id into a full
    set of fabricated coaching failures, which is exactly how truncation would corrupt a run.
    A milestone missing from a scenario the model DID score still defaults to miss, matching
    score_milestones_batch, and every drop of either kind is reported.
    """
    rows = raw if isinstance(raw, list) else (raw or {}).get("results", [])
    by_sid = {str(r.get("situation_id")): r for r in rows if isinstance(r, dict)}
    scored_by = _gemma.LAST_MODEL_USED
    results: list[dict] = []
    warnings: list[str] = []

    for i, b in enumerate(chunk):
        sid = f"S{i}"
        if sid not in expected:
            continue
        r = by_sid.get(sid)
        if r is None:
            warnings.append(f"{b.scenario_key}: no verdict returned; scored nothing")
            results.append({"scenario_key": b.scenario_key, "returned": False,
                            "scored_by": scored_by, "milestones": []})
            continue
        got = {str(m.get("id")): m for m in (r.get("milestones") or []) if isinstance(m, dict)}  # noqa: E501
        missing = [mid for mid, _ in expected[sid] if mid not in got]
        if missing:
            warnings.append(f"{b.scenario_key}: {len(missing)} milestone id(s) missing "
                            f"({', '.join(missing)}); each defaults to miss")
        out = []
        for mid, m in expected[sid]:
            g = got.get(mid, {})
            # Takes the whole dict, not the verdict string, and defaults anything
            # unrecognised (or absent) to "miss" -- the same contract as the moment scorer.
            verdict = _normalize_verdict(g)
            turn = g.get("turn")
            try:
                turn = int(turn)
            except (TypeError, ValueError):
                turn = None
            turns_list = [t for t in (g.get("turns") or [])
                          if isinstance(t, int) or (isinstance(t, str) and t.isdigit())]
            turns_list = [int(t) for t in turns_list]
            out.append({
                "milestone_id": mid,
                "milestone_description": m.get("description", ""),
                "verdict": verdict,
                "confidence": g.get("confidence") or "low",
                "reason": (g.get("reason") or "").strip(),
                # EVIDENCE IS KEPT ON FULL HITS. v1 blanked it, copying the moment scorer
                # where evidence only explains a shortfall -- but in call mode locating the
                # evidence IS the point, and blanking it left 200 of 239 credits unverifiable,
                # so the fabrication check only ever saw the partial hits.
                "evidence_kind": (g.get("evidence_kind") or "").strip(),
                "quote": (g.get("quote") or "").strip(),
                "turn": turn,
                "turns": turns_list,
                "pattern": (g.get("pattern") or "").strip(),
                "gap_to_ideal": "" if verdict == "full_hit"
                                else (g.get("gap_to_ideal") or "").strip(),
                "evidence": milestone_evidence(m),
                "scored_by": scored_by,
                "returned": mid in got,
            })
        results.append({"scenario_key": b.scenario_key, "returned": True,
                        "scored_by": scored_by, "milestones": out})

    unexpected = set(by_sid) - {f"S{i}" for i in range(len(chunk))}
    if unexpected:
        warnings.append(f"model returned unknown situation ids: {sorted(unexpected)}")
    return results, warnings


def verify_evidence(results: list[dict], turns: list[tuple[str, str]],
                    window: int = 2, scored_roles: tuple[str, ...] = ("NAREN",)) -> dict:
    """Is every CREDIT actually locatable in the transcript? FREE, no model, no human.

    Checks EVERY full_hit and partial_hit, not just the ones that happen to carry a quote --
    v1 blanked the quote on full hits and so verified 26 of 239 credits, the biased 11%.

    *** BOTH EVIDENCE FORMS ARE ROLE-CHECKED. v1 role-checked only one of them. ***
      at_turn       the quote must appear at or near the turn it claims, IN A TURN SPOKEN BY
                    THE PERSON BEING SCORED. v1 checked only that the text existed somewhere
                    in the +/-window, and the window necessarily sweeps in client turns -- 12
                    credits passed while quoting the CLIENT, e.g. "Would it help, Naren, if we
                    sync same time tomorrow?" credited as a CSM milestone.
      across_turns  at least two cited turns must exist AND be spoken by the person scored.
                    No quote to match, so the check is that the cited moments are real and are
                    the right speaker -- which stops "across_turns" becoming a hole any
                    unevidenced credit escapes through.

    `scored_roles` MUST be spelled as SpeakerRole member names. v1 asked for "OTHER_JOVEO"
    when the member is `JOVEO_OTHER`, and for "CSM", which does not exist at all -- so the
    filter silently admitted only NAREN, rejected 24% of cited turns on a transposition, and
    raised nothing. Callers should derive this from the enum, never type the strings.

    A credit with NO usable evidence of either kind fails. That is the point: the prompt says
    a credit you cannot evidence is a miss, and this is what makes that claim enforceable.

    `by_kind` breaks the rate down per form, because pooling them hid that one branch was too
    strict (the transposition) while the other was too lenient (no role check) -- so a single
    pooled rate was an under-estimate and an over-estimate at once.
    """
    texts = [" ".join((t or "").split()).lower() for _, t in turns]
    roles = [(r or "").upper() for r, _ in turns]
    want = {r.upper() for r in scored_roles}
    unknown = want - set(roles) if roles else set()
    checked = verified = 0
    failures = []
    kinds: dict[str, int] = {}
    by_kind: dict[str, list[int]] = {}
    speaker_mix: dict[str, int] = {}
    for r in results:
        for m in r.get("milestones", []):
            if m.get("verdict") == "miss":
                continue
            checked += 1
            kind = (m.get("evidence_kind") or "").strip().lower()
            if not kind:
                kind = "at_turn" if m.get("quote") else (
                    "across_turns" if m.get("turns") else "none")
            kinds[kind] = kinds.get(kind, 0) + 1
            tally = by_kind.setdefault(kind, [0, 0])
            tally[0] += 1
            ok, why = False, ""
            if kind == "across_turns":
                cited = [t for t in (m.get("turns") or []) if 1 <= t <= len(texts)]
                for t in cited:
                    speaker_mix[roles[t - 1]] = speaker_mix.get(roles[t - 1], 0) + 1
                good = [t for t in cited if roles[t - 1] in want]
                ok = len(good) >= 2
                why = (f"{len(good)} cited turns are the scored speaker, of "
                       f"{len(m.get('turns') or [])} cited")
            else:
                q = " ".join((m.get("quote") or "").split()).lower()
                t = m.get("turn")
                if q and isinstance(t, int) and 1 <= t <= len(texts):
                    lo, hi = max(0, t - 1 - window), min(len(texts), t + window)
                    # Match ONLY within turns the scored speaker owns. Searching the joined
                    # window would credit a milestone to words the client said.
                    hits = [i for i in range(lo, hi) if q in texts[i]]
                    for i in hits:
                        speaker_mix[roles[i]] = speaker_mix.get(roles[i], 0) + 1
                    ok = any(roles[i] in want for i in hits)
                    why = ("" if ok else
                           "quote is in the window but spoken by someone else" if hits
                           else "quote not at cited turn")
                else:
                    why = "no quote or no turn"
            if ok:
                verified += 1
                tally[1] += 1
            else:
                q = " ".join((m.get("quote") or "").split()).lower()
                failures.append({"scenario_key": r["scenario_key"],
                                 "milestone_id": m["milestone_id"],
                                 "verdict": m.get("verdict"), "kind": kind,
                                 "turn": m.get("turn"), "turns": m.get("turns"),
                                 "quote": (m.get("quote") or "")[:120], "why": why,
                                 "found_elsewhere": bool(q) and any(q in x for x in texts)})
    return {"checked": checked, "verified": verified,
            "rate": verified / checked if checked else float("nan"),
            "kinds": kinds,
            "by_kind": {k: {"checked": v[0], "verified": v[1],
                            "rate": v[1] / v[0] if v[0] else float("nan")}
                        for k, v in by_kind.items()},
            "cited_speaker_mix": speaker_mix,
            "scored_roles": sorted(want),
            "unknown_roles": sorted(unknown),
            "failures": failures}


def score_call(transcript_turns: list[tuple[str, str]], blocks: list[ScenarioBlock],
               config: Config, scenarios_per_request: int = 3,
               skip_uncoachable: bool = False, model: str | None = None,
               fallback_models: tuple[str, ...] | None = None) -> tuple[list[dict], list[str]]:
    """Score one call against several candidate scenarios. The only impure function here."""
    transcript = format_transcript(transcript_turns)
    all_results: list[dict] = []
    all_warnings: list[str] = []
    for chunk in chunk_scenarios(blocks, scenarios_per_request):
        situations, expected = build_situations_block(chunk, skip_uncoachable)
        if not expected:
            continue
        prompt = PROMPT_STEP3_CALL_LEVEL_BATCH.format(
            transcript=transcript, situations_block=situations)
        try:
            raw = call_gemma(
                prompt, config.gemma_api_keys,
                model=model or _SCORING_MODEL,
                fallback_models=(_SCORING_FALLBACKS if fallback_models is None
                                 else fallback_models),
                max_output_tokens=_SCORING_MAX_OUTPUT_TOKENS,
            )
        except Exception as e:                                          # noqa: BLE001
            # A whole transcript plus several rubrics is a long generation, and a single
            # malformed reply (gemma.py parses with a strict json.loads, so trailing content
            # after the array raises) must not destroy a 45-call run. It is RECORDED and
            # COUNTED, never swallowed: the scenarios in this chunk score nothing, which
            # parse_response already distinguishes from all-miss, and the caller is told.
            all_warnings.append(f"CHUNK FAILED ({len(chunk)} scenario(s), "
                                f"{[b.scenario_key for b in chunk]}): {str(e)[:160]}")
            all_results.extend({"scenario_key": b.scenario_key, "returned": False,
                                "scored_by": None, "chunk_failed": True, "milestones": []}
                               for b in chunk)
            continue
        results, warnings = parse_response(raw, expected, chunk)
        all_results.extend(results)
        all_warnings.extend(warnings)
    for w in all_warnings:
        print(f"  ! call scoring: {w}", flush=True)
    return all_results, all_warnings
