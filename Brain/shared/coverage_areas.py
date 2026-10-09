"""Coverage areas: 3-4 things strong handling covers, instead of ~5 gradable criteria.

Design: docs/superpowers/specs/2026-08-12-layer-c-profile-rebuild-design.md section 4.
Selected by layer_c.describe_mode == 'coverage'.

WHY THE UNIT CHANGES. Layer D currently asks ~5 binary questions per moment -- "did she
satisfy criterion 3?" -- against criteria measured to be scenario-agnostic (the expert
scores 0.114 against his own rubrics and 0.090 against unrelated ones). A coverage
question is coarser, more concrete, and answerable more reliably; "you never explained
the cause" is also better coaching than "criterion 3: miss".

WHAT THIS MODULE GUARDS. Collapsing 5 moves into 3 areas can quietly FUSE genuinely
distinct coaching moves. That exact merge-blindness inflated a whole Layer C A/B while
the milestone count went UP, and it was invisible in every summary statistic the run
produced. So every area must declare which moves it covers, and the coverage is checked
rather than trusted: unknown ids, uncovered moves, double-claimed moves and wide merges
are all reported.

Pure -- no Gemma, no DB, no torch. The prompt lives in shared/prompts.py and the call
site in v2/layer_c.py.
"""
from __future__ import annotations

# An area covering this many moves or more is flagged for a human to read. NOT blocked:
# sometimes four moves really are one coaching idea, and a hard cap would be a count-based
# rule, which this codebase bars for the MAX_CLUSTERS=150 reason. The flag exists so the
# collapse is visible in the artifact instead of hiding behind a tidy-looking area count.
WIDE_MERGE_MOVES = 4

_REQUIRED = ("description",)


def parse_areas(raw, cluster_ids: list[str]) -> tuple[list[dict], dict]:
    """Validated coverage areas plus a report of everything that did not line up.

    raw          Gemma's reply: a bare array or {"results": [...]}; both shapes occur.
    cluster_ids  every move id that was offered, in order.

    Ids are REASSIGNED positionally (C1, C2, ...) regardless of what the model returned,
    for the same reason milestone_id is the array position: a model-chosen id lets a
    re-run silently repoint a person's history at a different area.

    Areas covering nothing are dropped. An area with no moves behind it has no evidence,
    which is precisely the unfalsifiable prose the covers_clusters requirement exists to
    prevent.
    """
    rows = raw if isinstance(raw, list) else (raw or {}).get("results", [])
    allowed = list(cluster_ids)
    allowed_set = set(allowed)

    areas: list[dict] = []
    unknown: list[str] = []
    claimed: dict[str, int] = {}
    empty: list[str] = []
    malformed = 0

    for row in rows:
        if not isinstance(row, dict) or any(not row.get(f) for f in _REQUIRED):
            malformed += 1
            continue
        covers, seen = [], set()
        for cid in row.get("covers_clusters") or []:
            if cid not in allowed_set:
                unknown.append(cid)
            elif cid not in seen:
                seen.add(cid)
                covers.append(cid)
                claimed[cid] = claimed.get(cid, 0) + 1
        if not covers:
            empty.append(str(row.get("id", f"<unnamed #{len(areas) + 1}>")))
            continue
        areas.append({
            "id": f"C{len(areas) + 1}",
            "label": row.get("label") or f"Area {len(areas) + 1}",
            "description": row["description"],
            "precondition": row.get("precondition") or None,
            "covers_clusters": covers,
            "exemplars": [e for e in (row.get("exemplars") or []) if isinstance(e, str)],
        })

    report = {
        "unknown_clusters": unknown,
        "uncovered_clusters": [c for c in allowed if c not in claimed],
        "double_claimed_clusters": [c for c in allowed if claimed.get(c, 0) > 1],
        "empty_areas": empty,
        "malformed_areas": malformed,
    }
    return areas, report


def attach_evidence(areas: list[dict], clusters_by_id: dict[str, dict]) -> list[dict]:
    """Roll each area's evidence up from the moves it covers.

    Without this an area is prose with no audit trail and "does this actually recur?"
    becomes unanswerable -- the question the whole evidence-triage design exists to keep
    answerable.

    support_calls is a MAX, not a sum. Two moves can recur in the SAME calls, so adding
    their counts would claim more distinct calls than the scenario has. Max is the honest
    lower bound available without per-move call sets, and understating support is the
    safe direction: it can only make a gate stricter.
    """
    out = []
    for area in areas:
        members = [clusters_by_id[c] for c in area["covers_clusters"] if c in clusters_by_id]
        support_calls = max((m.get("support_calls") or 0 for m in members), default=0)
        support_clauses = sum(len(m.get("clauses") or []) for m in members)
        relevances = [m["relevance_mean"] for m in members if m.get("relevance_mean") is not None]
        out.append(dict(
            area,
            support_calls=support_calls,
            support_clauses=support_clauses,
            relevance_mean=(sum(relevances) / len(relevances)) if relevances else None,
            covers_n_moves=len(members),
            wide_merge=len(members) >= WIDE_MERGE_MOVES,
            source_v="v2_coverage",
        ))
    return out


# --------------------------------------------------------------------------------------
# Verdicts. Four, not three -- and the fourth is the whole point.
# --------------------------------------------------------------------------------------

COVERED = "covered"
PARTLY_COVERED = "partly_covered"
NOT_COVERED = "not_covered"
NOT_CALLED_FOR = "not_called_for"

VALID_VERDICTS = frozenset({COVERED, PARTLY_COVERED, NOT_COVERED, NOT_CALLED_FOR})

# not_called_for is EXCLUDED from the conditional denominator: it is the contingency
# correction, obtained inside the coverage judgement instead of via the separate
# applicability pre-check that failed its own null on 2026-08-12 (0.147 matched vs 0.120
# unrelated, 1.22:1). Folding it in works because the judge sees the client turn AND the
# response together, which a trigger-only judge structurally could not.
_CONDITIONAL_EXCLUDED = frozenset({NOT_CALLED_FOR})


def normalize_verdict(raw: dict) -> str:
    """Clamp a returned verdict into the vocabulary, defaulting to not_covered.

    NOT to not_called_for: defaulting an unparseable answer to "the moment did not
    require it" would silently shrink the denominator and flatter every score, which is
    the failure direction that cannot be detected downstream. Mirrors
    milestone_scoring._normalize_verdict's reasoning, in the opposite direction, for the
    same reason: default to the answer that cannot inflate a result.
    """
    verdict = raw.get("verdict")
    return verdict if verdict in VALID_VERDICTS else NOT_COVERED


def score(verdicts: list[str]) -> dict:
    """Weighted coverage, reported BOTH ways.

    Unconditional includes not_called_for in the denominator; conditional excludes it.
    Both are required, and reporting only one is a comparability trap: an arm using the
    fourth verdict computes over a different population than one that does not, so the
    two are not comparable unless the unconditional figure exists on both sides. Same
    discipline as keeping discrimination unconditional on both arms in the ceiling
    design -- filtering one side inflates the null.
    """
    counts = {v: 0 for v in VALID_VERDICTS}
    for verdict in verdicts:
        counts[verdict if verdict in VALID_VERDICTS else NOT_COVERED] += 1

    hits = counts[COVERED]
    partial = counts[PARTLY_COVERED]
    total = sum(counts.values())
    applicable = total - sum(counts[v] for v in _CONDITIONAL_EXCLUDED)
    return {
        "counts": counts,
        "attempts": total,
        "applicable": applicable,
        "w_unconditional": (hits + 0.5 * partial) / total if total else 0.0,
        "w_conditional": (hits + 0.5 * partial) / applicable if applicable else 0.0,
        "not_called_for_rate": counts[NOT_CALLED_FOR] / total if total else 0.0,
    }
