#!/usr/bin/env python3
"""THREE-ARM ROUTING A/B ON THE PLAYBOOK YARDSTICK.

Spec: docs/superpowers/specs/2026-08-19-routing-playbook-ab-design.md (FROZEN, approved
2026-08-19 before this file existed). Substrate: the shipped `union_base` map.

    concat (control, production r0)  vs  keyphrases (scenario_vector_mode)  vs
    r1 (membership lookup + description fallback)

ONE variable moves: which 50 pairs the router delivers to a scenario. Map, corpus, pilot
scenario set, selection rule, prompts, model, snap, renderer and seed are all held
identical, and the comparison is HEAD-TO-HEAD PAIRED BY SCENARIO — not arm-vs-placebo.

  G-D  (pre-spend, free)  >= 10 of 50 selected pairs changed vs control on >= 3 of 5
                          pilot scenarios, else the arm is a NULL BY CONSTRUCTION and
                          spends nothing.
  G-F  (per arm)          all 5 snapped documents pass PB0 against their OWN evidence.
  G-V  (per packet)       3 valid readers (every item answered, >= 4/5 negatives rejected).
  G-P  (per packet)       the reader pool prefers the real document on >= 3 of 4
                          calibration pairs — a null from a pool that cannot detect a
                          KNOWN difference is a broken instrument, not a null. VOIDs a win
                          as readily as a null.
  G-W  (primary)          the arm is preferred over control in >= 4 of 5 scenarios.

BUDGET: 70 chat attempts TOTAL across all three arms (nominal 45, expected ~64). The
ceiling is enforced across arms by summing every arm's persisted counter, so a fresh
process cannot reset it. Every attempt is persisted BEFORE its POST.

*** ONE ARM PER PROCESS (spec §0.7). *** The keyphrases arm installs a replaced Tuning
into the `shared.tuning` singleton; a second arm in the same process could read a stale
singleton and produce a phantom result. Each --arm is its own invocation, its resolved
mode read back, asserted, and recorded in the artifact identity.

Usage (from Brain/):
    .\\ops\\run_visible.ps1 -Script calibration/routing_playbook_ab.py -ScriptArgs '--select --arm concat'
    .\\ops\\run_visible.ps1 -Script calibration/routing_playbook_ab.py -ScriptArgs '--select --arm keyphrases'
    .\\ops\\run_visible.ps1 -Script calibration/routing_playbook_ab.py -ScriptArgs '--select --arm r1'
    ..\\.venv\\Scripts\\python.exe calibration/routing_playbook_ab.py --divergence
    .\\ops\\run_visible.ps1 -Script calibration/routing_playbook_ab.py -ScriptArgs '--synthesize --arm concat'
    ..\\.venv\\Scripts\\python.exe calibration/routing_playbook_ab.py --snap --arm concat
    ..\\.venv\\Scripts\\python.exe calibration/routing_playbook_ab.py --pb0 --arm concat
    ..\\.venv\\Scripts\\python.exe calibration/routing_playbook_ab.py --build-read --comparison keyphrases
    # (3 blinded sonnet readers write artifacts/rt_<cmp>_judgments_r*.json, ONE AT A TIME)
    ..\\.venv\\Scripts\\python.exe calibration/routing_playbook_ab.py --score --comparison keyphrases
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402
from calibration.scenario_playbook_trial import (  # noqa: E402
    ACCT_FLOOR, ATTEMPTS_PER_CALL, BATCH_MAX, CHAT_TEMPERATURE, N_EVIDENCE_MAX, N_NEG,
    N_VALID_READERS, SEED, build_neg, build_pool, map_prompt, pb0_doc, pick_pilot,
    reader_valid, reduce_prompt, render_doc, scenario_header_text, sign_test_two_sided,
    validate_map, validate_playbook,
)
from calibration.playbook_snap_trial import (  # noqa: E402
    counterbalanced_side, pb1_doc_resized, snap_doc,
)

# --------------------------------------------------------------------------------------
# FROZEN CONSTANTS (spec §2, §5, §7, §9). None of these may move after a result is seen.
# --------------------------------------------------------------------------------------
TAXONOMY = "union_base"                  # the shipped playbook substrate
WIDTH = 3072                             # gemini-embedding-2 native
CONTROL = "concat"
ARMS = ("concat", "keyphrases", "r1")
ARM_MODE = {"concat": "concat", "keyphrases": "keyphrases", "r1": "concat"}
ARM_ROUTER = {"concat": "r0", "keyphrases": "r0", "r1": "r1"}

# T-R2's anchors, frozen (spec §3). Asserted rather than read from the artifact so the
# gate cannot become self-referential if union_pool_t0.json is ever regenerated.
T_R2_POOL_SHA = "475d2de4eee8df4f"
T_R2_OLD_PREFIX_SHA = "676ab677bc25e80f"
T_R2_OLD_TURNS = 20_788

GD_CHANGED_MIN = 10                      # of 50 selected pairs, vs control
GD_SCENARIOS_MIN = 3                     # of the 5 pilot scenarios
TOPUP_CEILING = 10_000                   # uncached selection vectors -> halt and ask

RT_BUDGET = 70                           # chat attempts, TOTAL across all three arms
RT_CHAT_MODEL = "gemini-3.5-flash"
RT_REASONING = "low"                     # `high` is unreachable: LiteLLM's 120s cap
RT_MAX_TOKENS = 65536                    # thinking shares the pool with the answer
RT_TIMEOUT = 600.0

# --------------------------------------------------------------------------------------
# G-P's calibration pairs — the powered-ness control (spec §7.2, AMENDED after the pre-run
# audit; see spec §12 finding 1 for the full reasoning).
#
# These are FOUR published real/placebo pairs from the snap trial (`pbs_*`, the OLD map),
# NOT pilot scenarios from this trial. Two independent reasons, both fatal to the original
# design:
#
#  1. STRUCTURE. Three pairs cannot be made bias-proof at a bar of 2: any A/B pattern over
#     3 items hands a purely position-answering reader 2 of 3, which IS the bar. Four pairs
#     at A/B/A/B hand it exactly 2 of 4, below a bar of 3 — so position bias CANNOT pass
#     G-P, by construction rather than by hoping readers are honest.
#  2. DIRECTION. Pilot-scenario calibration pairs reuse the published `pbv_*` documents,
#     which were synthesized from CONTROL-routed evidence. Showing a reader the "genuine"
#     control-derived document for scenario S and then asking it to judge S's routing pair
#     lets familiarity anchor it on the arm whose document most resembles what it just
#     endorsed — the CONTROL. That does not merely add noise, it MANUFACTURES NULLS, which
#     disqualifies it as the gate whose entire purpose is making a null believable.
#
# The `pbs_*` pairs measured PB2 5/5 with pooled votes 14-1 (p=0.001) — a known, strong,
# independently measured difference, which is exactly what a powered-ness control needs.
# `ats_api_integration_and_authentication` is deliberately EXCLUDED despite being available:
# it is topically the same subject as the pilot's `ats_integration_and_api_mapping`, and the
# anchoring argument above applies to a near-duplicate SUBJECT as much as to an identical
# key. Zero chat cost — every document already exists on disk.
CAL_SOURCE_TAXONOMY = "clean2_base"
CAL_SCENARIOS = ("creative_approval_and_budget_phasing",
                 "multi_channel_spend_and_board_optimization",
                 "publisher_mix_and_quality_review",
                 "trial_period_and_minimum_spend_negotiation")
CAL_PASS_MIN = 3                         # of 4 calibration pairs
WIN_SCENARIOS = 4                        # of 5 — the PB2 bar, unchanged
PHASE2_WIN = 3                           # of 5, keyphrases-vs-r1 tie-break only

COMPARISONS = {"keyphrases": ("keyphrases", CONTROL),
               "r1": ("r1", CONTROL),
               "k_vs_r1": ("keyphrases", "r1")}
COMPARISON_INDEX = {"keyphrases": 0, "r1": 1, "k_vs_r1": 0}   # counterbalancing offset

# published control-arm inputs, READ-ONLY (never written by this harness)
PBV_EVIDENCE = ARTIFACTS_DIR / "pbv_evidence.json"        # the frozen pilot set lives here
PBS_SNAPPED = ARTIFACTS_DIR / "pbs_playbooks.json"        # the G-P calibration pairs
UNION_CLUSTERS = ARTIFACTS_DIR / "union_clusters.json"

DIVERGENCE = ARTIFACTS_DIR / "rt_divergence.json"


def route_art(arm: str) -> Path:
    return ARTIFACTS_DIR / f"rt_route_{arm}.json"


def evidence_art(arm: str) -> Path:
    return ARTIFACTS_DIR / f"rt_evidence_{arm}.json"


def playbooks_art(arm: str) -> Path:
    return ARTIFACTS_DIR / f"rt_playbooks_{arm}.json"


def snapped_art(arm: str) -> Path:
    return ARTIFACTS_DIR / f"rt_snapped_{arm}.json"


def pb0_art(arm: str) -> Path:
    return ARTIFACTS_DIR / f"rt_pb0_{arm}.json"


def packet_art(cmp_: str) -> Path:
    return ARTIFACTS_DIR / f"rt_{cmp_}_read_packet.txt"


def key_art(cmp_: str) -> Path:
    return ARTIFACTS_DIR / f"rt_{cmp_}_read_KEY.json"


def report_art(cmp_: str) -> Path:
    return ARTIFACTS_DIR / f"rt_{cmp_}_report.json"


def judgments_glob(cmp_: str, round_: int | None = None) -> str:
    """The judgment files for one comparison, optionally scoped to a re-dispatch round.

    *** A VOID PACKET IS RE-DISPATCHED TO FRESH READERS (spec §7.4), AND WITHOUT A ROUND
    SCOPE THAT SILENTLY RE-SCORES THE DISCARDED TRIO. *** `score_headtohead` keeps the
    first `N_VALID_READERS` valid files in FILENAME order, and judgment files carry no
    round marker, so round 2's readers land in the same namespace and are never reached —
    the run would record "the packet VOIDed twice, the instrument is broken" when the
    replacement pool was never counted. Worse, fresh files that happen to sort EARLIER
    produce a verdict from a mixture of discarded and fresh readers, with nothing in the
    output saying so. The two namespaces are disjoint by construction: an unscoped glob
    cannot match `..._round2_judgments_*` and vice versa.
    """
    if round_ is None:
        return f"rt_{cmp_}_judgments_*.json"
    if round_ < 2:
        raise SystemExit("--round is for a RE-dispatch after a VOID; round 1 is the "
                         "unscoped default")
    return f"rt_{cmp_}_round{round_}_judgments_*.json"


def _check_arm(arm: str) -> str:
    if arm not in ARMS:
        raise SystemExit(f"--arm must be one of {ARMS}, got {arm!r}")
    return arm


def _check_comparison(cmp_: str) -> str:
    if cmp_ not in COMPARISONS:
        raise SystemExit(f"--comparison must be one of {sorted(COMPARISONS)}, got {cmp_!r}")
    return cmp_


def _no_clobber(path: Path) -> None:
    if path.exists():
        raise SystemExit(f"{path.name} exists — refusing to clobber a published artifact")


# ======================================================================================
# pure functions (unit-tested in tests/test_routing_playbook_ab.py)
# ======================================================================================

def project_base_clusters(union_art: dict) -> list[dict]:
    """`union_clusters.json` -> the minimal cluster list `member_sets` consumes.

    `member_sets` reads `cluster_id` and `idxs` and nothing else, so the base memberships
    are projected rather than rebuilt through `load_persisted_clusters` — that function
    recomputes support stats from the pool's vectors, which would materialise a ~712 MB
    matrix that r1 never touches. The projection is not trusted on those grounds: it is
    PINNED by `assert_membership_pin` below, which is the same content hash the
    adjudication recorded.

    A duplicate cluster_id would make the pin meaningless (two clusters, one join key), so
    it raises rather than letting last-write-wins decide which memberships are read.
    """
    clusters, seen = [], set()
    for c in union_art["clusters"]:
        cid = c["cluster_id"]
        if cid in seen:
            raise ValueError(f"duplicate cluster_id {cid!r} in union_clusters.json — the "
                             f"cluster_id join key is not unique, so member sets could be "
                             f"attached to the wrong scenario")
        seen.add(cid)
        idxs = [int(i) for i in c["idxs_base"]]
        if not idxs:
            raise ValueError(f"cluster {cid!r} has an empty idxs_base — artifact malformed")
        clusters.append({"cluster_id": cid, "idxs": idxs})
    return clusters


def assert_membership_pin(clusters: list[dict], adjudication_identity: dict) -> str:
    """T-R0. The projected memberships must hash to what the adjudication recorded.

    Verified 12d2f5fccee8106c on both sides while the spec was written; re-asserted here
    because a mismatch means r1's lookup would attach member sets to scenarios that were
    adjudicated over DIFFERENT clusters — every trigger routed to a plausible wrong place.
    """
    from calibration.adjudication_ab import members_sha

    want = adjudication_identity.get("members_sha")
    got = members_sha(clusters)
    if not want:
        raise SystemExit("the taxonomy artifact records no members_sha — there is nothing "
                         "to pin these memberships to. Refusing to route r1.")
    if want != got:
        raise SystemExit(f"T-R0 MEMBERSHIP MISMATCH: idxs_base hashes to {got}, the "
                         f"taxonomy was adjudicated over {want}. Every member set would be "
                         f"attached to the wrong scenario. Halt.")
    return got


def taxonomy_identity_sha(scenario_map: dict) -> str:
    """A MODE-INVARIANT hash of the taxonomy: key, coachability, description, keyphrases.

    *** `layer_bc_arms.taxonomy_sha` CANNOT BE USED TO COMPARE THESE ARMS. *** It hashes
    `scenario_text(info)`, which resolves `scenario_vector_mode` — so it differs between the
    concat and keyphrases arms BY CONSTRUCTION, because that is precisely the variable the
    treatment moves. Using it as a cross-arm identity check (as this harness first did)
    rejects the keyphrases arm for being the keyphrases arm.

    This hashes both registers unconditionally, so it is identical across every arm that
    reads the same map and changes only which register is embedded. The mode-DEPENDENT sha
    stays recorded too, where it earns its keep as a positive check: it must DIFFER between
    arms whose register differs (proving the treatment applied) and MATCH between arms
    sharing a register.
    """
    import hashlib

    h = hashlib.sha256()
    for k in sorted(scenario_map):
        info = scenario_map[k]
        h.update(f"{k}|{int(bool(info['is_coachable']))}|"
                 f"{info.get('business_description', '')}|"
                 f"{''.join(info.get('keyphrases') or [])}\n".encode("utf-8"))
    return h.hexdigest()[:16]


def install_scenario_vector_mode(mode: str) -> str:
    """Install the arm's scenario-vector register into the tuning singleton, and PROVE it.

    `shared.scenario_vectors._resolve_mode` reads `get_tuning()`, the process-wide
    singleton, so replacing it is what makes production `assign_scenarios` embed the
    keyphrases register without touching production code or tuning.yaml on disk. Frozen
    dataclasses mean `dataclasses.replace`, not attribute assignment.

    The read-back is not ceremony: an import-time config read that LOOKED authoritative
    while doing nothing is on this repo's record (`ego_trap/settings.py`), and a
    keyphrases arm that silently ran as concat would be a phantom result indistinguishable
    from a genuine null.
    """
    from shared import scenario_vectors
    from shared import tuning as tuning_mod

    if mode not in scenario_vectors.MODES:
        raise SystemExit(f"scenario_vector_mode {mode!r} not in {scenario_vectors.MODES}")
    t = tuning_mod.load_tuning()
    if t.layer_a.scenario_vector_mode != mode:
        t = dataclasses.replace(
            t, layer_a=dataclasses.replace(t.layer_a, scenario_vector_mode=mode))
    tuning_mod._cached = t
    got = tuning_mod.get_tuning().layer_a.scenario_vector_mode
    if got != mode:
        raise SystemExit(f"scenario_vector_mode install FAILED: singleton reports {got!r}, "
                         f"asked for {mode!r}. The arm would not be the arm.")
    return got


class ModeFallbackCounter(logging.Handler):
    """Counts `scenario_text`'s visible fallback-to-concat warnings.

    Measured before the run: 0 of 259 union_base scenarios have empty keyphrases, so the
    keyphrases arm runs pure. This asserts that rather than assuming it — a half-concat
    arm is a phantom treatment, and the fallback is deliberately a WARNING rather than an
    exception in production, so nothing else would stop it.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if "scenario_vector_mode" in str(record.msg):
            self.records.append(record.getMessage())

    def install(self) -> "ModeFallbackCounter":
        logging.getLogger("shared.scenario_vectors").addHandler(self)
        return self

    def assert_clean(self, mode: str) -> None:
        if self.records:
            raise SystemExit(
                f"{len(self.records)} scenario(s) fell back to concat under "
                f"scenario_vector_mode={mode!r}, e.g. {self.records[0]!r}. This arm would "
                f"be a keyphrases/concat MIXTURE, not the frozen treatment. Halt.")


def selected_ids(per_scenario: dict, scenario: str) -> set[str]:
    """The frozen identity of a selected pair: `<call stem>:<turn_index>`, which is
    exactly `build_pairs`' own `pair_id`. Set semantics are safe because a (call, turn)
    can appear at most once in a scenario's pool."""
    return {f"{s['call']}:{s['turn_index']}"
            for s in per_scenario[scenario]["selected"]}


def _jaccard(a: set, b: set) -> float:
    u = len(a | b)
    return (len(a & b) / u) if u else 1.0


def divergence_row(control_ps: dict, arm_ps: dict, scenario: str) -> dict:
    """One scenario's divergence between an arm's selection and the control's.

    `jaccard_routed` (audit finding 7) is the diagnostic that separates "routing is inert
    on this map" from "routing moved plenty and `select_evidence` absorbed it" — the
    distinction an operator needs to interpret a G-D failure. It needs the ROUTED pair-id
    sets, which `stage_select` therefore persists; older artifacts without them report None
    rather than silently reading as identical.
    """
    c = selected_ids(control_ps, scenario)
    a = selected_ids(arm_ps, scenario)
    rc = control_ps[scenario].get("routed_pair_ids")
    ra = arm_ps[scenario].get("routed_pair_ids")
    return {"scenario": scenario, "n_control": len(c), "n_arm": len(a),
            "changed": len(a - c), "shared": len(c & a),
            "jaccard_selected": _jaccard(c, a),
            "n_routed_control": len(rc) if rc is not None else None,
            "n_routed_arm": len(ra) if ra is not None else None,
            "jaccard_routed": (_jaccard(set(rc), set(ra))
                               if rc is not None and ra is not None else None)}


def gd_verdict(rows: list[dict]) -> dict:
    """G-D, exactly as frozen: >= GD_CHANGED_MIN changed on >= GD_SCENARIOS_MIN scenarios.

    An arm below the bar shares >= 80% of its evidence with the control on most scenarios;
    no blinded read can resolve that, so it is declared a NULL BY CONSTRUCTION and spends
    nothing rather than buying an unreadable comparison.
    """
    # A scenario qualifies only if the arm ALSO selected the same number of pairs as the
    # control (audit finding 4, second net): `changed` is an absolute count, so a collapsed
    # selection would clear the bar more easily while introducing a volume confound. The
    # select stage halts on any shortfall, so this can only fire on an artifact built before
    # that guard existed — in which case it must fail closed, not pass.
    qualifying = [r["scenario"] for r in rows
                  if r["changed"] >= GD_CHANGED_MIN and r["n_arm"] == r["n_control"]]
    mismatched = [r["scenario"] for r in rows if r["n_arm"] != r["n_control"]]
    return {"changed_min": GD_CHANGED_MIN, "scenarios_min": GD_SCENARIOS_MIN,
            "n_qualifying": len(qualifying), "qualifying": qualifying,
            "volume_mismatched": mismatched,
            "pass": len(qualifying) >= GD_SCENARIOS_MIN,
            "per_scenario": rows}


def treatment_side(rank_position: int, comparison_index: int) -> str:
    """Frozen counterbalancing (spec §7.3): the TREATMENT takes side A iff
    (rank_position + comparison_index) is even.

    Extends `counterbalanced_side` by the comparison offset so that (a) neither arm sits
    on one side across a packet and (b) the control does not occupy the same side in both
    comparisons — a reader who noticed either would be reading position, not content.
    Deterministic: a degenerate all-one-side draw is impossible.
    """
    return counterbalanced_side((rank_position + comparison_index) % 2)


ROUTE_PACKET_HEADER = [
    "BLIND READ -- scenario coaching playbooks",
    "",
    "Each PAIR item names one client-conversation SCENARIO and shows two candidate",
    "coaching playbooks, A and B. Judge ONLY what is written, and decide which one is the",
    "more usable coaching playbook FOR THE NAMED SCENARIO.",
    "",
    "For every PAIR item answer, in JSON (see the required format at the end):",
    '  "choice": "A" or "B" -- the more usable coaching playbook for the named scenario.',
    "  You MUST pick one; there is no EQUAL.",
    '  "apply_A" / "apply_B": one rating per KEY MOVE, in display order, each either',
    '  "APPLY" (concrete enough for a new account manager to attempt on their next call',
    '  in this scenario) or "VAGUE".',
    "",
    "SINGLE items show one document and name a scenario. Answer:",
    '  "answer": "YES" if it is one coherent, usable coaching document for that',
    '  scenario, "NO" otherwise.',
    "",
    "Do not try to infer where an item came from, and do not assume any particular",
    "share of answers. Answer EVERY item.",
    "=" * 96, ""]
# DELIBERATE DEVIATION FROM THE PILOT'S PACKET_HEADER, RECORDED IN SPEC §12. The pilot's
# wording says "exactly one is the genuine playbook synthesized from real evidence" --
# true of a real-vs-placebo read, FALSE here: on a routing item both documents are
# genuine, from the same map, differing only in which pairs the router delivered. Telling
# a reader to hunt for a fake would make them answer a question this design is not
# asking. The ANSWER FORMAT and the SINGLE-item wording are byte-identical to the frozen
# original, so `reader_valid` and the judgment schema are unchanged.


def neg_headers(ranking: dict[str, int], pilot: list[str]) -> list[str]:
    """The scenarios the SINGLE (negative) items are headed by: the highest-routed
    coachable scenarios that are NOT in the pilot, in the predecessor's own order.

    Audit finding 3 (MAJOR, fixed before any spend): heading a negative with a PILOT
    scenario is unsound here, because `build_neg` lifts key moves VERBATIM out of the very
    documents this packet displays — so a negative headed by its own source scenario can
    carry a genuine, well-evidenced move for the scenario named above it, and a reader who
    actually reads it can honestly answer YES. Two such answers drop that reader below
    NEG_REJECT_MIN, so G-V would preferentially invalidate the CAREFUL readers and retain
    the ones who reject any scrambled-looking document unread — exactly the readers whose
    ROUTE votes are worthless. `playbook_validation.py` drew its NEG headers from
    non-pilot, non-donor scenarios for this reason; this restores that rule (there are no
    donors in this design, so the pilot is the only exclusion).
    """
    out = [k for k in sorted(ranking, key=lambda k: (-ranking[k], k)) if k not in pilot]
    if len(out) < N_NEG:
        raise SystemExit(f"only {len(out)} non-pilot coachable scenario(s) available for "
                         f"{N_NEG} NEG headers")
    return out[:N_NEG]


def build_packet_items(pilot: list[str], comparison: str, rng) -> list[dict]:
    """The frozen packet composition (spec §7.2, as amended): 5 ROUTE pairs + 4 CAL pairs
    + 5 NEG = 14 items, order seeded per comparison. Rendering is the caller's."""
    treat_arm, base_arm = COMPARISONS[comparison]
    ci = COMPARISON_INDEX[comparison]
    items: list[dict] = []
    for i, scen in enumerate(pilot):
        items.append({"kind": "ROUTE", "scenario": scen, "rank_position": i,
                      "treat_arm": treat_arm, "base_arm": base_arm,
                      "treat_side": treatment_side(i, ci)})
    # *** COUNTERBALANCED ON POSITION WITHIN THE CALIBRATION SET. *** Audit finding 1
    # (FATAL): the original rule counterbalanced on PILOT RANK, and CAL_RANKS = (1, 3, 5)
    # are all odd, so the real document sat on side A in every calibration pair of every
    # packet. Enumerating the 4-pair CAL set gives A/B/A/B, under which a purely
    # position-answering reader scores exactly 2 of 4 — below CAL_PASS_MIN = 3. G-P is now
    # bias-proof by construction.
    for j, scen in enumerate(CAL_SCENARIOS):
        items.append({"kind": "CAL", "scenario": scen,
                      "real_side": counterbalanced_side(j)})
    for n in range(N_NEG):
        items.append({"kind": "NEG", "neg_index": n})
    rng.shuffle(items)
    return items


def packet_rng(comparison: str):
    """One shuffle stream per comparison.

    Audit finding 9 (MINOR, fixed; DEVIATION FROM THE FROZEN WORDING, ON THE RECORD,
    CONSERVATIVE DIRECTION ONLY — spec §12): a single `Random(SEED)` gave all three
    packets a byte-identical layout, which put the G-P calibration items at the reader's
    freshest positions and 4 of the 5 decisive ROUTE items at its most fatigued ones, in
    every packet. Deriving the stream from (SEED, comparison) keeps the order seeded and
    reproducible while making that asymmetry noise instead of a systematic tilt. It cannot
    favour either arm: sides are set by `treatment_side` before the shuffle ever runs.
    """
    import random
    # A fixed offset per comparison name, taken from the sorted key list so it does not
    # depend on dict insertion order or on Python's string hash randomisation.
    return random.Random(SEED + 1000 * (1 + sorted(COMPARISONS).index(comparison)))


def score_headtohead(key: dict, judgments: list[dict]) -> dict:
    """G-V, G-P, G-W from the sealed key and the committed judgments.

    Validity reuses the pilot's frozen `reader_valid` verbatim (every item answered, and
    >= 4/5 NEG rejected); ROUTE and CAL rows are both non-NEG kinds, so it applies without
    modification. The TALLY is this design's own -- a treatment/control preference, not a
    real/placebo one -- and is deliberately not a reinterpretation of `score_read`'s
    output, which would have meant reading "real" as "treatment".

    G-P IS A VOID CONDITION, NOT A FLAG. A packet whose readers cannot prefer the real
    document over its placebo on documents PB2 already measured cannot support a null: it
    has not been shown to discriminate at all.
    """
    names = [jd["reader"] for jd in judgments]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate reader identity among judgment files: {names}")
    payloads = [json.dumps(jd["items"], sort_keys=True) for jd in judgments]
    if len(set(payloads)) != len(payloads):
        raise ValueError("two judgment files carry byte-identical answers — a duplicated "
                         "dispatch, not two readers")

    validity, valid = {}, []
    for jd in judgments:
        ok, why = reader_valid(jd["items"], key["items"])
        validity[jd["reader"]] = {"valid": ok, "why": why}
        if ok and len(valid) < N_VALID_READERS:
            valid.append(jd)
    if len(valid) < N_VALID_READERS:
        return {"verdict": "VOID",
                "reason": f"G-V: only {len(valid)} valid reader(s) (< {N_VALID_READERS})",
                "validity": validity}

    per_scenario, pooled_t, pooled_b = {}, 0, 0
    apply_share: dict[str, float] = {}
    for row in key["items"]:
        if row["kind"] != "ROUTE":
            continue
        side = row["treat_side"]
        votes = 0
        applies = []
        for jd in valid:
            it = jd["items"].get(str(row["item"])) or {}
            votes += str(it.get("choice", "")).upper() == side
            applies.append([str(r).upper() == "APPLY"
                            for r in (it.get(f"apply_{side}") or [])])
        pooled_t += votes
        pooled_b += len(valid) - votes
        n_moves = row.get("n_moves_treat", 0)
        move_apply = [sum(1 for a in applies if mi < len(a) and a[mi]) >= 2
                      for mi in range(n_moves)]
        apply_share[row["scenario"]] = (sum(move_apply) / n_moves) if n_moves else 0.0
        per_scenario[row["scenario"]] = {
            "votes_treatment": votes, "n_valid": len(valid),
            "treatment_preferred": votes >= 2,
            "apply_share_treatment": apply_share[row["scenario"]]}

    cal = {}
    for row in key["items"]:
        if row["kind"] != "CAL":
            continue
        side = row["real_side"]
        votes = sum(1 for jd in valid
                    if str((jd["items"].get(str(row["item"])) or {}).get(
                        "choice", "")).upper() == side)
        cal[row["scenario"]] = {"votes_real": votes, "real_preferred": votes >= 2}
    cal_pass = sum(1 for r in cal.values() if r["real_preferred"])

    n_pref = sum(1 for r in per_scenario.values() if r["treatment_preferred"])
    shares = sorted(apply_share.values())
    median_share = (shares[len(shares) // 2] if len(shares) % 2
                    else (shares[len(shares) // 2 - 1] + shares[len(shares) // 2]) / 2
                    ) if shares else 0.0
    out = {
        "validity": validity, "valid_readers": [jd["reader"] for jd in valid],
        "g_p": {"calibration_pairs": cal, "n_real_preferred": cal_pass,
                "min_required": CAL_PASS_MIN, "pass": cal_pass >= CAL_PASS_MIN},
        "per_scenario": per_scenario,
        "g_w": {"scenarios_treatment_preferred": n_pref,
                "n_scenarios": len(per_scenario),
                "bar": WIN_SCENARIOS,
                "pooled_votes": {"treatment": pooled_t, "base": pooled_b,
                                 "sign_p_descriptive": sign_test_two_sided(pooled_t,
                                                                           pooled_b)},
                "unanimous_scenarios": sum(1 for r in per_scenario.values()
                                           if r["votes_treatment"] in (0, len(valid)))},
        "apply_share": {"per_scenario": apply_share, "median": median_share},
    }
    if not out["g_p"]["pass"]:
        out["verdict"] = "VOID"
        out["reason"] = (f"G-P: readers preferred the real document on only {cal_pass}/"
                         f"{len(cal)} calibration pairs (< {CAL_PASS_MIN}); this packet "
                         f"has not been shown to discriminate, so neither a win nor a "
                         f"null is readable from it")
        out["won"] = False
        return out
    out["won"] = n_pref >= WIN_SCENARIOS
    out["verdict"] = "TREATMENT WINS" if out["won"] else "NO WIN (control retained)"
    return out


def cal_channels(key: dict) -> dict:
    """Every NON-CONTENT channel a reader could ride to pass G-P, made visible.

    G-P is bias-proof against SIDE patterns by construction (A/B/A/B at a bar of 3 of 4),
    but the re-audit measured a second channel that the frozen pairs do carry: real vs
    placebo KEY-MOVE COUNTS are 4-vs-3 on two pairs and 4-vs-4 on the other two, and the
    two separable pairs are exactly the two the A/B/A/B rule puts real-on-A. So "prefer the
    document with more key moves, tie-break to B" scores 4 of 4 without reading a word, and
    reordering the pairs does not remove it (both tie-break variants still reach 3).

    The pairs cannot grow without readmitting the ATS near-duplicate whose exclusion is
    itself load-bearing, so this is REPORTED rather than engineered away: if the pool's
    calibration preferences track move count exactly, the G-P pass is not evidence of
    content discrimination and the reader pool must be treated as unproven. That judgment
    belongs to the operator, and it needs the numbers in front of it.
    """
    rows = [r for r in key["items"] if r["kind"] == "CAL"]
    return {"note": "a G-P pass that tracks move_count_favours_real is not evidence of "
                    "CONTENT discrimination — see spec §11",
            "per_pair": [{"scenario": r["scenario"], "real_side": r["real_side"],
                          "n_moves_real": r.get("n_moves_real"),
                          "n_moves_placebo": r.get("n_moves_placebo"),
                          "move_count_favours_real": (
                              None if r.get("n_moves_placebo") is None
                              else r.get("n_moves_real", 0) > r["n_moves_placebo"])}
                         for r in rows]}


def rt_doc_jobs(ev: dict) -> list[dict]:
    """The 5 synthesis jobs for one arm, in frozen pilot-rank order. Real documents only:
    the placebo twins this design needs are the PUBLISHED pbv_* pair (spec §7.2), so no
    arm pays to re-synthesize one."""
    return [{"doc_id": f"{key}::real", "scenario": key,
             "evidence": ev["per_scenario"][key]["selected"]}
            for key in ev["pilot"]]


def spend_so_far(exclude_arm: str | None = None) -> int:
    """Chat attempts persisted by EVERY arm. The frozen budget is a total across arms
    (spec §9), so a fresh process must not be able to reset it by starting a new arm."""
    total = 0
    for arm in ARMS:
        if arm == exclude_arm:
            continue
        p = playbooks_art(arm)
        if p.exists():
            total += int(json.loads(p.read_text(encoding="utf-8-sig")).get(
                "calls_used", 0))
    return total


# ======================================================================================
# Stage 0 + 1 + 2 — anchors, routing, selection (free apart from bounded embedding)
# ======================================================================================

def _load_taxonomy():
    from calibration.layer_bc_arms import scenario_map_from_rows, taxonomy_path

    tax = taxonomy_path(TAXONOMY)
    if not tax.exists():
        raise SystemExit(f"{tax.name} not found — the shipped map is missing")
    art = json.loads(tax.read_text(encoding="utf-8-sig"))
    if art.get("limit"):
        raise SystemExit(f"{tax.name} is a --limit path test, not a taxonomy")
    scenario_map, _ = scenario_map_from_rows(art["rows"])
    return art, scenario_map


def _cal_scenario_map() -> dict:
    """The OLD map's scenario rows, for the calibration items' headers only.

    Read-only, and it never touches the routing substrate: a CAL item's job is to show the
    reader a real/placebo pair whose answer is already known, and it must be headed by its
    OWN map's description or the pair would be judged against the wrong situation.
    """
    from calibration.layer_bc_arms import scenario_map_from_rows, taxonomy_path

    p = taxonomy_path(CAL_SOURCE_TAXONOMY)
    if not p.exists():
        raise SystemExit(f"{p.name} missing — the calibration headers live there")
    sm, _ = scenario_map_from_rows(json.loads(p.read_text(encoding="utf-8-sig"))["rows"])
    missing = [s for s in CAL_SCENARIOS if s not in sm]
    if missing:
        raise SystemExit(f"calibration scenario(s) {missing} absent from "
                         f"{CAL_SOURCE_TAXONOMY}")
    return sm


def _anchors():
    """T-R2 then the shared parse. Returns (t0_manifest, texts, parsed)."""
    from calibration.union_pool_fetch import _rebuild_and_check, load_t0
    from calibration.layer_bc_arms import parse_corpus
    from calibration.expanded_pool_stage1 import assert_no_stem_collision

    man = load_t0()                       # T-R2: refuses a failed T0 outright
    print("[T-R2] re-deriving the union pool and checking it against T0...", flush=True)
    texts, _call_ids, _old_stems = _rebuild_and_check(man)   # aborts on pool drift
    # THE FROZEN LITERALS, ASSERTED. Audit finding 6 (MINOR, fixed): `_rebuild_and_check`
    # compares the re-derived pool against whatever `union_pool_t0.json` currently records,
    # so if that artifact were ever regenerated T-R2 would become self-referential and pass
    # on a drifted corpus. The spec's own numbers are the anchor, so they live here.
    for field, want in (("pool_sha", T_R2_POOL_SHA),
                        ("old_prefix_sha", T_R2_OLD_PREFIX_SHA)):
        if man.get(field) != want:
            raise SystemExit(f"T-R2 FAILED: {field} is {man.get(field)!r}, the spec freezes "
                             f"it at {want!r}. This is not the audited substrate.")
    if man["t0"]["old_turns"] != T_R2_OLD_TURNS:
        raise SystemExit(f"T-R2: old-corpus CLIENT turns {man['t0']['old_turns']} != "
                         f"{T_R2_OLD_TURNS}")
    print(f"[T-R2] PASS — pool_sha {man['pool_sha']}, {len(texts)} turns, "
          f"old block {man['t0']['old_turns']}", flush=True)

    parsed_old = parse_corpus("recordings")
    parsed_new = parse_corpus("recordings_pull_keep")
    assert_no_stem_collision({p.stem for _, p, _ in parsed_old},
                             {p.stem for _, p, _ in parsed_new})
    return man, texts, parsed_old, parsed_new


def _route(arm: str, pairs: list[dict], scenario_map: dict, rows: list[dict],
           tax_identity: dict, texts: list[str], parsed) -> dict:
    """Route every pair under `arm`, mutating the pairs in place. Returns diagnostics."""
    router = ARM_ROUTER[arm]
    if router == "r0":
        from v1.layer_b import assign_scenarios
        print(f"[route {arm}] production assign_scenarios over {len(pairs)} pairs "
              f"(mode={ARM_MODE[arm]})...", flush=True)
        assign_scenarios(pairs, scenario_map, None)
        return {"router": "r0", "scenario_vector_mode": ARM_MODE[arm]}

    import numpy as np
    from calibration.layer_b_routers import (assign_scenarios_router,
                                             router_context_from_clusters)

    clusters = project_base_clusters(
        json.loads(UNION_CLUSTERS.read_text(encoding="utf-8-sig")))
    sha = assert_membership_pin(clusters, tax_identity)          # T-R0
    print(f"[T-R0] PASS — idxs_base members_sha {sha} matches the adjudication", flush=True)

    # r1 consumes NO vectors: `router_context_from_clusters` builds OutOfFoldCentroids
    # only for r2/r3. A real (58,002 x 3072) matrix would cost ~712 MB for nothing, so the
    # zero-column placeholder is passed deliberately and the harness refuses any other
    # router, which is what keeps that from becoming a silent assumption.
    if router != "r1":
        raise SystemExit(f"router {router!r} needs member vectors; this harness only "
                         f"implements the pre-registered r1 arm")
    print("[T-R1] verifying the positional pool join over every CLIENT turn...", flush=True)
    ctx = router_context_from_clusters(
        "r1", rows, clusters, parsed, texts,
        np.empty((len(texts), 0), dtype=np.float64), scenario_map, "s0")
    print(f"[T-R1] PASS — {ctx.diag['n_pool_items']} pool items joined, "
          f"{ctx.diag['n_member_keys']} member keys", flush=True)

    print(f"[route {arm}] membership lookup + description fallback over {len(pairs)} "
          f"pairs...", flush=True)
    assign_scenarios_router(pairs, scenario_map, "r1", ctx)
    if ctx.diag.get("r1_fallback_unmapped"):
        raise SystemExit(f"{ctx.diag['r1_fallback_unmapped']} trigger(s) had no pool "
                         f"index — that is a BROKEN JOIN, not a property of the "
                         f"clustering, and it must never be readable as one. Halt.")
    print(f"  lookup {ctx.diag['r1_lookup_share']:.1%} / fallback "
          f"{ctx.diag['r1_fallback_share']:.1%} "
          f"(to-sink {ctx.diag['r1_lookup_to_sink']})", flush=True)
    return {"router": "r1", "scenario_vector_mode": ARM_MODE[arm], **ctx.diag}


def _origin_sink_shares(pairs: list[dict], scenario_map: dict,
                        old_stems: set[str]) -> dict:
    """Sink share on each corpus block — the G-R2 shape, reported per arm."""
    out = {}
    for label, want_old in (("old", True), ("new", False)):
        sel = [p for p in pairs
               if (Path(p["call_filename"]).stem in old_stems) == want_old]
        sunk = sum(1 for p in sel
                   if not scenario_map[p["scenario_key"]]["is_coachable"])
        out[label] = {"pairs": len(sel),
                      "sink_share": (sunk / len(sel)) if sel else float("nan")}
    return out


def stage_select(arm: str) -> None:
    from calibration import layer_b_arms as lb
    from calibration.expanded_pool_stage1 import merge_account_maps
    from calibration.flag_proper_noun_clusters import account_map
    from calibration.layer_bc_arms import (_load_cached, build_pairs, corpus_sha,
                                           install_embedder_shim, prewarm, taxonomy_sha)
    from calibration.scenario_playbook_trial import select_evidence
    from preprocessing import segmenter
    from shared.scenario_vectors import scenario_text

    _no_clobber(route_art(arm))
    _no_clobber(evidence_art(arm))
    if not PBV_EVIDENCE.exists():
        raise SystemExit(f"{PBV_EVIDENCE.name} missing — the frozen pilot set lives there")

    tax_art, scenario_map = _load_taxonomy()
    man, texts, parsed_old, parsed_new = _anchors()
    pairs = (build_pairs("recordings", "s0", "a0", parsed=parsed_old)
             + build_pairs("recordings_pull_keep", "s0", "a0", parsed=parsed_new))

    # THE ARM'S ONE SWITCH, installed and proven before anything is embedded.
    fallbacks = ModeFallbackCounter().install()
    mode = install_scenario_vector_mode(ARM_MODE[arm])
    print(f"[arm {arm}] scenario_vector_mode={mode} (read back from the singleton), "
          f"router={ARM_ROUTER[arm]}", flush=True)

    # The ONE bounded embedding spend on scenario texts: the keyphrases register has never
    # been embedded for this map (~259 texts). Everything else is served cache-only.
    prewarm([scenario_text(v) for v in scenario_map.values()], 20)
    shim = install_embedder_shim(WIDTH)

    diag = _route(arm, pairs, scenario_map, tax_art["rows"], tax_art.get("identity", {}),
                  texts, parsed_old + parsed_new)
    fallbacks.assert_clean(mode)

    by_key: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        k = p["scenario_key"]
        if k and scenario_map[k]["is_coachable"]:
            by_key[k].append(p)
    coachable = {k: v for k, v in scenario_map.items() if v["is_coachable"]}
    counts = {k: len(by_key.get(k, [])) for k in coachable}

    # THE PILOT IS THE CONTROL'S, FROZEN (spec §0.3) — never this arm's own pick.
    pbv = json.loads(PBV_EVIDENCE.read_text(encoding="utf-8-sig"))
    pilot = list(pbv["pilot"])
    own_pick = pick_pilot(counts)
    if arm == CONTROL and own_pick != pilot:
        raise SystemExit(
            f"the control arm's own pick rule does NOT reproduce PV's frozen pilot.\n"
            f"  PV:   {pilot}\n  here: {own_pick}\n"
            f"Same map, same corpus, same router — so something upstream has drifted and "
            f"nothing in this trial is comparable to the published control. Halt.")
    print(f"[pilot] frozen (control's): {', '.join(f'{k}({counts[k]}p)' for k in pilot)}")
    if own_pick != pilot:
        print(f"[pilot] this arm's OWN pick would have been: {own_pick} (descriptive; the "
              f"frozen pilot stands)", flush=True)

    old_stems = {p.stem for _, p, _ in parsed_old}
    acct_old, _ = account_map("recordings")
    acct_new, _ = account_map("recordings_pull_keep")
    if not acct_old or not acct_new:
        raise SystemExit("ABORT: an account map came back empty — missing sidecars")
    acct, _ = lb.collapse_sibling_domains(merge_account_maps([acct_old, acct_new]))

    # AN EMPTY POOL DISQUALIFIES THIS ARM, IT DOES NOT ABORT THE TRIAL. Mirrors the
    # volume-parity structure for the same reason (§12.2.5): raising here left the arm's
    # artifacts unwritten, so `--divergence` — which needs all three arms — could never run
    # and an unrelated comparison was blocked by this arm's collapse. Measured on the
    # keyphrases arm, which routes ZERO pairs to the map's largest scenario. The arm is
    # recorded, shouted, and refused at the spend gate; the others proceed untouched.
    pools, empty = {}, []
    for key in pilot:
        pool, no_acct, no_clause = build_pool(by_key.get(key, []), acct,
                                              segmenter.segment_into_clauses)
        if not pool:
            empty.append(key)
        pools[key] = (pool, no_acct, no_clause)
    if empty:
        which = "those scenarios" if len(empty) > 1 else "that scenario"
        print(f"\n!! EMPTY EVIDENCE POOL under arm {arm!r} for {empty} — this arm cannot "
              f"synthesize a document for {which} at all, so it cannot be read head-to-head "
              f"on the frozen pilot. The arm is DISQUALIFIED; the others are unaffected.\n",
              flush=True)

    all_texts = sorted({p["unit_text"] for pool, _, _ in pools.values() for p in pool})
    _, missing = _load_cached(all_texts, WIDTH)
    n_fetched = 0
    if missing:
        from calibration.trial_pool_unit_gemini import embed_cached
        n_fetched = len(missing)
        if n_fetched > TOPUP_CEILING:
            raise SystemExit(f"TOP-UP CEILING: {n_fetched} uncached selection vectors "
                             f"(> {TOPUP_CEILING}) — the cache has eroded. HALT; ask the "
                             f"operator before re-paying.")
        print(f"[top-up] {n_fetched} uncached selection vector(s) — the ONE bounded "
              f"embedding top-up for this arm, fetching now...", flush=True)
        embed_cached(sorted(missing), 20)
        _, still = _load_cached(all_texts, WIDTH)
        if still:
            raise SystemExit(f"ABORT: {len(still)} unit text(s) STILL uncached after the "
                             f"top-up")

    per_scenario = {}
    for key in pilot:
        pool, no_acct, no_clause = pools[key]
        if not pool:
            # Recorded with an empty selection so the divergence row and the volume check
            # both see this scenario rather than skipping over it silently.
            per_scenario[key] = {
                "routed_pairs": counts[key], "pool_accounted": 0,
                "excluded_no_account": no_acct, "excluded_no_clause": no_clause,
                "accounts_in_pool": 0, "accounts_selected": 0,
                "routed_pair_ids": sorted(p["pair_id"] for p in by_key.get(key, [])),
                "selected": []}
            print(f"  [{key[:44]:<44}] pool    0 -> EMPTY, arm disqualified", flush=True)
            continue
        mat, _ = _load_cached([p["unit_text"] for p in pool], WIDTH)
        if mat is None:
            raise SystemExit(f"ABORT: cache miss after top-up for {key!r} — bug")
        idx = select_evidence(pool, mat, N_EVIDENCE_MAX,
                             min(ACCT_FLOOR, len({p["account"] for p in pool})))
        sel = [dict(pool[i]) for i in idx]
        per_scenario[key] = {
            "routed_pairs": counts[key], "pool_accounted": len(pool),
            "excluded_no_account": no_acct, "excluded_no_clause": no_clause,
            "accounts_in_pool": len({p["account"] for p in pool}),
            "accounts_selected": len({s["account"] for s in sel}),
            # The ROUTED set, not just its size: without it the routed-set Jaccard the spec
            # lists as a §5 descriptive is unrecoverable without re-running --select
            # (audit finding 7).
            "routed_pair_ids": sorted(p["pair_id"] for p in by_key.get(key, [])),
            "selected": sel}
        print(f"  [{key[:44]:<44}] pool {len(pool):>4} -> {len(sel)} selected, "
              f"{per_scenario[key]['accounts_selected']} accounts", flush=True)

    # *** VOLUME PARITY, CHECKED BEFORE ANY CHAT SPEND. *** Audit finding 4 (MAJOR, fixed
    # before any spend): `select_evidence` returns min(N_EVIDENCE_MAX, len(pool)), so an
    # arm that reroutes a scenario's pool below 50 would synthesize a THINNER document than
    # the control's — and the read would then be comparing volume as well as routing, with
    # the difference credited to routing. G-D would not catch it; its `changed` count is
    # absolute, so a collapsed selection passes the bar MORE easily, not less. Reachable on
    # r1, which reroutes up to ~41% of pairs and sends some of them to sinks, against
    # control pools as small as 98 accounted pairs. Halt and let the operator decide rather
    # than silently buying a confounded comparison.
    # RECORDED HERE, ENFORCED AT THE SPEND GATE — not raised here. Re-audit finding: raising
    # before the artifacts are written meant an r1 shortfall left `rt_evidence_r1.json`
    # absent, so `--divergence` (which needs all three arms) could never run and the
    # KEYPHRASES comparison was blocked by an unrelated arm's collapse. §5's intent for a
    # non-viable arm is "null by construction, spends nothing", never "the trial cannot
    # proceed". So the shortfall is persisted and shouted, `gd_verdict` disqualifies the
    # affected scenarios, and `stage_synthesize` refuses THIS arm only.
    short = {k: len(per_scenario[k]["selected"]) for k in pilot
             if len(per_scenario[k]["selected"]) < N_EVIDENCE_MAX}
    if short:
        print(f"\n!! VOLUME SHORTFALL under arm {arm!r}: {short} (each must be "
              f"{N_EVIDENCE_MAX}). A document built from fewer pairs than the control's "
              f"puts VOLUME in the read alongside routing. This arm CANNOT synthesize; the "
              f"other arms are unaffected. HALT and ask the operator.\n", flush=True)

    ident = {"started_at": datetime.datetime.now().isoformat(timespec="seconds"),
             "pid": os.getpid(), "seed": SEED, "arm": arm, "taxonomy": TAXONOMY,
             "scenario_vector_mode": mode, "router": ARM_ROUTER[arm],
             "pool_sha": man["pool_sha"], "old_prefix_sha": man["old_prefix_sha"],
             "corpus_sha": corpus_sha(pairs),
             # mode-DEPENDENT (differs iff the register differs — a positive check that the
             # treatment applied) and mode-INVARIANT (must be identical across all arms).
             "taxonomy_sha": taxonomy_sha(scenario_map),
             "taxonomy_sha_invariant": taxonomy_identity_sha(scenario_map),
             "spec": "2026-08-19-routing-playbook-ab-design.md"}

    route_art(arm).write_text(json.dumps({
        "identity": ident, "n_pairs": len(pairs),
        "routing_diag": diag,
        "sink_shares_by_origin": _origin_sink_shares(pairs, scenario_map, old_stems),
        "embedder_texts_served": shim.get("texts"),
        "routed_counts": counts, "frozen_pilot": pilot, "own_pilot_pick": own_pick,
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    evidence_art(arm).write_text(json.dumps({
        "identity": {**ident, "topup_fetched": n_fetched},
        "ranking": counts, "pilot": pilot,
        "volume_shortfall": short, "empty_pools": empty,
        "per_scenario": per_scenario,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[artifact] {route_art(arm).name} + {evidence_art(arm).name} written. "
          f"ZERO chat calls, {n_fetched} embedding top-ups, ZERO Postgres writes.")
    print(f"RT SELECT COMPLETE ({arm})", flush=True)


# ======================================================================================
# G-D — the pre-spend divergence gate (free)
# ======================================================================================

def stage_divergence() -> None:
    _no_clobber(DIVERGENCE)
    evs = {}
    for arm in ARMS:
        p = evidence_art(arm)
        if not p.exists():
            raise SystemExit(f"{p.name} missing — run --select --arm {arm} first")
        evs[arm] = json.loads(p.read_text(encoding="utf-8-sig"))

    pilot = evs[CONTROL]["pilot"]
    for arm, ev in evs.items():
        if ev["pilot"] != pilot:
            raise SystemExit(f"arm {arm!r} carries a different pilot set — the comparison "
                             f"would not be paired. Halt.")
        # The MODE-INVARIANT identity is what must match: same keys, same coachability, same
        # descriptions, same keyphrases. `taxonomy_sha` is mode-dependent and MUST differ
        # between arms whose register differs — see `taxonomy_identity_sha`.
        want_inv = evs[CONTROL]["identity"].get("taxonomy_sha_invariant")
        got_inv = ev["identity"].get("taxonomy_sha_invariant")
        if not want_inv or not got_inv:
            raise SystemExit(f"arm {arm!r} predates `taxonomy_sha_invariant`; re-run "
                             f"--select for every arm so the cross-arm identity is checked "
                             f"mode-invariantly rather than against the treatment itself.")
        if got_inv != want_inv:
            raise SystemExit(f"arm {arm!r} routed against a different taxonomy "
                             f"({got_inv} vs {want_inv}) — two variables at once. Halt.")
        same_mode = (ev["identity"]["scenario_vector_mode"]
                     == evs[CONTROL]["identity"]["scenario_vector_mode"])
        same_sha = ev["identity"]["taxonomy_sha"] == evs[CONTROL]["identity"]["taxonomy_sha"]
        if same_mode != same_sha:
            raise SystemExit(
                f"arm {arm!r}: scenario_vector_mode "
                f"{ev['identity']['scenario_vector_mode']!r} vs control's "
                f"{evs[CONTROL]['identity']['scenario_vector_mode']!r}, but the "
                f"register-dependent taxonomy_sha "
                f"{'matches' if same_sha else 'differs'}. Either the register did not "
                f"actually apply, or something other than the register moved. Halt.")
        if ev["identity"]["corpus_sha"] != evs[CONTROL]["identity"]["corpus_sha"]:
            raise SystemExit(f"arm {arm!r} routed a different corpus — two variables at "
                             f"once. Halt.")

    out = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "control": CONTROL, "pilot": pilot, "arms": {}}
    for arm in ARMS:
        if arm == CONTROL:
            continue
        rows = [divergence_row(evs[CONTROL]["per_scenario"], evs[arm]["per_scenario"], s)
                for s in pilot]
        v = gd_verdict(rows)
        out["arms"][arm] = v
        print(f"\n[{arm}] G-D {'PASS' if v['pass'] else 'FAIL — NULL BY CONSTRUCTION'} "
              f"({v['n_qualifying']}/{len(rows)} scenarios >= {GD_CHANGED_MIN} changed)")
        if v["volume_mismatched"]:
            print(f"  !! volume mismatch vs control on {v['volume_mismatched']} — those "
                  f"scenarios cannot qualify (a thinner document would put VOLUME in the "
                  f"read alongside routing)")
        for r in rows:
            jr = ("n/a" if r["jaccard_routed"] is None
                  else f"{r['jaccard_routed']:.3f}")
            print(f"  {r['scenario'][:46]:<46} changed {r['changed']:>2}/{r['n_arm']:<3} "
                  f"jaccard_sel {r['jaccard_selected']:.3f} jaccard_routed {jr}")
        print(f"  routed-count shift: "
              + ", ".join(f"{s[:20]}: {evs[CONTROL]['ranking'][s]}->{evs[arm]['ranking'][s]}"
                          for s in pilot))

    # *** DIVERGING IS NOT THE SAME AS BEING USABLE. *** G-D asks only "did this arm move
    # enough evidence to be readable"; an arm can pass that on its surviving scenarios while
    # being disqualified outright because it cannot produce a document for one of the frozen
    # pilot scenarios at all, or produces a thinner one. Measured on the keyphrases arm,
    # which passes G-D 3/5 and is nonetheless unusable. `stage_synthesize` refuses it either
    # way, but `arms_cleared_to_spend` is the RECORD, and it must not name an arm that is
    # disqualified.
    dq = {}
    for arm in ARMS:
        if arm == CONTROL:
            continue
        ev = evs[arm]
        reasons = {}
        if ev.get("empty_pools"):
            reasons["empty_pools"] = ev["empty_pools"]
        if ev.get("volume_shortfall"):
            reasons["volume_shortfall"] = ev["volume_shortfall"]
        if reasons:
            dq[arm] = reasons
            out["arms"][arm]["disqualified"] = reasons
    out["disqualified_arms"] = dq
    proceed = [a for a, v in out["arms"].items() if v["pass"] and a not in dq]
    out["arms_cleared_to_spend"] = proceed
    for arm, reasons in dq.items():
        print(f"\n[{arm}] DISQUALIFIED regardless of G-D: {reasons}")
    DIVERGENCE.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n" + "=" * 88)
    if not proceed:
        print("G-D: NO treatment arm clears the bar. Per spec §5 the ENTIRE chat spend is "
              "CANCELLED and the result is that routing is not a live variable on this "
              "yardstick at this map. Report; do not synthesize.")
    else:
        print(f"G-D: cleared to spend -> {proceed}. The control arm synthesizes too "
              f"(model symmetry, spec §0.4).")
    print("=" * 88)
    print("RT DIVERGENCE COMPLETE", flush=True)


# ======================================================================================
# Stage 3 — synthesis (the chat spend), snap, and G-F
# ======================================================================================

def stage_synthesize(arm: str) -> None:
    from calibration.trial_gateway import GatewayClient

    ev_path = evidence_art(arm)
    if not ev_path.exists():
        raise SystemExit(f"run --select --arm {arm} first")
    if not DIVERGENCE.exists():
        raise SystemExit("run --divergence first — G-D decides which arms may spend")
    gd = json.loads(DIVERGENCE.read_text(encoding="utf-8-sig"))
    # THE CANCELLATION IS CHECKED FIRST AND APPLIES TO THE CONTROL TOO. Audit finding 2
    # (MAJOR, fixed before any spend): both guards used to sit behind `arm != CONTROL`, so
    # with no treatment arm cleared, `--synthesize --arm concat` still bought 5 documents —
    # against spec §5, which cancels the ENTIRE chat spend at ZERO chat cost in exactly
    # that state. The control's documents have nothing to be compared against.
    if not gd.get("arms_cleared_to_spend"):
        raise SystemExit("NO treatment arm cleared G-D. Per spec §5 the ENTIRE chat spend "
                         "is cancelled — including the control's, which would have nothing "
                         "to be compared against. Report the null; do not synthesize.")

    ev = json.loads(ev_path.read_text(encoding="utf-8-sig"))
    # ARM-LEVEL DISQUALIFICATIONS ARE CHECKED BEFORE G-D CLEARANCE. Both refuse the same
    # arms, but "routes ZERO pairs to X" tells the operator what actually happened, while
    # "did not clear G-D" is the generic consequence. The specific diagnosis wins.
    if ev.get("empty_pools"):
        which = "those scenarios" if len(ev["empty_pools"]) > 1 else "that scenario"
        raise SystemExit(
            f"arm {arm!r} routes ZERO pairs to {ev['empty_pools']} — it cannot produce a "
            f"document for {which} at all, so it cannot be read head-to-head on the frozen "
            f"pilot. DISQUALIFIED; refusing to spend. The other arms are unaffected.")
    # The volume-parity gate, enforced per arm at the spend boundary (see stage_select).
    if ev.get("volume_shortfall"):
        raise SystemExit(
            f"arm {arm!r} has a selected-evidence VOLUME SHORTFALL "
            f"{ev['volume_shortfall']} (each pilot scenario must supply "
            f"{N_EVIDENCE_MAX} pairs). Its documents would be thinner than the control's, "
            f"putting VOLUME in the read alongside routing. Refusing to spend on this arm; "
            f"the other arms are unaffected. Ask the operator.")
    if arm != CONTROL and arm not in gd["arms_cleared_to_spend"]:
        raise SystemExit(f"arm {arm!r} did NOT clear G-D — it is a null by construction "
                         f"and spends nothing (spec §5). Refusing to synthesize.")
    _, scenario_map = _load_taxonomy()

    state = (json.loads(playbooks_art(arm).read_text(encoding="utf-8-sig"))
             if playbooks_art(arm).exists() else
             {"identity": {**ev["identity"],
                           "started_at": datetime.datetime.now().isoformat(
                               timespec="seconds"),
                           "pid": os.getpid(), "model": RT_CHAT_MODEL,
                           "reasoning_effort": RT_REASONING,
                           "max_tokens": RT_MAX_TOKENS,
                           "temperature": CHAT_TEMPERATURE, "no_cache": True,
                           "prompts": "pilot_verbatim_hardening_not_revived"},
              "calls_used": 0, "documents": {}})

    # ATOMIC, via the helper written for exactly this incident. Audit finding 5 (MINOR,
    # fixed): `write_text` truncates before writing and this file is re-serialised after
    # EVERY attempt, so a Ctrl-C / OOM / sleep inside the window leaves invalid JSON — which
    # would break both this arm's resume AND `spend_so_far`'s cross-arm ledger for the other
    # arms, turning "resumable at zero re-spend" into a hand repair.
    from calibration.adjudication_ab import save_checkpoint

    def save() -> None:
        save_checkpoint(playbooks_art(arm), state)

    other = spend_so_far(exclude_arm=arm)
    print(f"[budget] {other} attempt(s) already spent by other arms; this arm has "
          f"{state['calls_used']}; total ceiling {RT_BUDGET}", flush=True)

    gw = GatewayClient(max_retries=1, timeout=RT_TIMEOUT)   # exactly one POST per attempt

    def call(prompt: str, label: str) -> dict:
        last: Exception | None = None
        for attempt in range(1, ATTEMPTS_PER_CALL + 1):
            if other + state["calls_used"] >= RT_BUDGET:
                save()
                raise SystemExit(
                    f"HARD STOP: {other + state['calls_used']} chat attempts across all "
                    f"arms (frozen ceiling {RT_BUDGET}). Ask the operator before any "
                    f"further spend.")
            state["calls_used"] += 1
            save()                        # persist the count BEFORE the POST
            t0 = time.time()
            try:
                parsed, usage = gw.chat_json(prompt, model=RT_CHAT_MODEL,
                                             temperature=CHAT_TEMPERATURE,
                                             max_tokens=RT_MAX_TOKENS, no_cache=True,
                                             reasoning_effort=RT_REASONING)
                state.setdefault("calls", []).append(
                    {"label": label, "attempt": attempt, "ok": True,
                     "model": RT_CHAT_MODEL, "reasoning": RT_REASONING,
                     "seconds": round(time.time() - t0, 1), "usage": usage})
                save()
                return parsed
            except Exception as e:        # noqa: BLE001 — logged, counted, retried
                last = e
                state.setdefault("calls", []).append(
                    {"label": label, "attempt": attempt, "ok": False,
                     "seconds": round(time.time() - t0, 1), "error": str(e)[:300]})
                save()
                print(f"  [{label}] attempt {attempt} failed: {str(e)[:160]}", flush=True)
                time.sleep(4)
        raise SystemExit(f"{label}: {ATTEMPTS_PER_CALL} attempts failed; last: {last}")

    for job in rt_doc_jobs(ev):
        if job["doc_id"] in state["documents"]:
            print(f"[skip] {job['doc_id']} already synthesized", flush=True)
            continue
        header = scenario_header_text(scenario_map[job["scenario"]])
        batches = [job["evidence"][i:i + BATCH_MAX]
                   for i in range(0, len(job["evidence"]), BATCH_MAX)]
        print(f"[synth {arm}] {job['doc_id']}: {len(job['evidence'])} pairs, "
              f"{len(batches)} map + 1 reduce (arm calls: {state['calls_used']})",
              flush=True)
        maps = []
        for bi, batch in enumerate(batches):
            for attempt in range(1, ATTEMPTS_PER_CALL + 1):
                out = call(map_prompt(header, batch), f"{job['doc_id']}/map{bi}.{attempt}")
                try:
                    validate_map(out)
                    break
                except ValueError as e:
                    print(f"  [{job['doc_id']}/map{bi}] schema reject: {e}", flush=True)
                    if attempt == ATTEMPTS_PER_CALL:
                        raise SystemExit(f"{job['doc_id']}/map{bi}: never met the schema")
            maps.append(out)
        triggers = [e["trigger_text"] for e in job["evidence"]]
        for attempt in range(1, ATTEMPTS_PER_CALL + 1):
            doc = call(reduce_prompt(header, maps, triggers),
                       f"{job['doc_id']}/reduce{attempt}")
            try:
                validate_playbook(doc)
                break
            except ValueError as e:
                print(f"  [{job['doc_id']}] schema reject: {e}", flush=True)
                for m in (doc.get("key_moves") or []):
                    mev = m.get("evidence")
                    print(f"    move {str(m.get('name', ''))[:44]!r}: "
                          f"crit={bool(str(m.get('criterion', '')).strip())} "
                          f"n_ev={len(mev) if isinstance(mev, list) else 'MISSING'}",
                          flush=True)
                if attempt == ATTEMPTS_PER_CALL:
                    raise SystemExit(f"{job['doc_id']}: reduce never met the schema")
        state["documents"][job["doc_id"]] = {
            "scenario": job["scenario"], "arm": arm,
            "n_evidence": len(job["evidence"]), "playbook": doc}
        save()
        print(f"  -> ok ({len(doc['key_moves'])} moves)", flush=True)

    print(f"\nRT SYNTHESIS COMPLETE ({arm}): {len(state['documents'])} documents, "
          f"{state['calls_used']} attempts this arm, "
          f"{other + state['calls_used']}/{RT_BUDGET} total.", flush=True)


def _load_arm(arm: str) -> tuple[dict, dict]:
    ep, pp = evidence_art(arm), playbooks_art(arm)
    if not (ep.exists() and pp.exists()):
        raise SystemExit(f"need {ep.name} and {pp.name}")
    ev = json.loads(ep.read_text(encoding="utf-8-sig"))
    pb = json.loads(pp.read_text(encoding="utf-8-sig"))
    want = len(ev["pilot"])
    if len(pb.get("documents", {})) != want:
        raise SystemExit(f"{pp.name} holds {len(pb.get('documents', {}))} documents, "
                         f"expected {want} — synthesis incomplete; resume --synthesize "
                         f"first (a partial set would make G-F read as a PASS over a "
                         f"subset)")
    return ev, pb


def arm_doc_evidence(ev: dict, rec: dict) -> list[dict]:
    """A document's OWN evidence set — this arm's selection for that scenario. Every
    document here is a real one, so there is no donor branch to get wrong."""
    return ev["per_scenario"][rec["scenario"]]["selected"]


def stage_snap(arm: str) -> None:
    _no_clobber(snapped_art(arm))
    ev, pb = _load_arm(arm)
    from calibration.playbook_snap_trial import SNAP_MIN_SCORE

    out = {"identity": {"generated_at": datetime.datetime.now().isoformat(
                            timespec="seconds"),
                        "seed": SEED, "arm": arm, "snap_min_score": SNAP_MIN_SCORE,
                        "source": playbooks_art(arm).name,
                        "source_calls_used": pb.get("calls_used")},
           "documents": {}}
    for doc_id, rec in sorted(pb["documents"].items()):
        snapped, log = snap_doc(rec["playbook"], arm_doc_evidence(ev, rec))
        out["documents"][doc_id] = {**{k: v for k, v in rec.items() if k != "playbook"},
                                    "playbook": snapped, "snap_log": log}
        print(f"  [{doc_id[:52]:<52}] kept {log['kept']:>2} snapped {log['snapped']} "
              f"dropped {log['dropped']} moves_dropped {len(log['dropped_moves'])}"
              f"{'  ** SCHEMA COLLAPSED **' if log['schema_collapsed'] else ''}",
              flush=True)
    snapped_art(arm).write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                encoding="utf-8")
    print(f"[artifact] {snapped_art(arm).name} written. ZERO chat calls.")
    print(f"RT SNAP COMPLETE ({arm})", flush=True)


def stage_pb0(arm: str) -> None:
    """G-F: all 5 snapped documents must pass PB0 against their own evidence."""
    _no_clobber(pb0_art(arm))
    ev, _ = _load_arm(arm)
    sn = json.loads(snapped_art(arm).read_text(encoding="utf-8-sig"))
    report, n_pass = {}, 0
    for doc_id, rec in sorted(sn["documents"].items()):
        res = pb0_doc(rec["playbook"], arm_doc_evidence(ev, rec))
        if rec["snap_log"]["schema_collapsed"]:
            res = {**res, "pass": False,
                   "failures": res["failures"] + [{"reason": "schema_collapsed",
                                                   "path": "key_moves"}]}
        report[doc_id] = res
        n_pass += bool(res["pass"])
        print(f"  [{doc_id[:52]:<52}] {'PASS' if res['pass'] else 'FAIL':<5} "
              f"{res['n_quotes']:>3}q {len(res['failures'])}bad", flush=True)
    n_docs = len(sn["documents"])
    verdict = "PASS" if n_pass == n_docs else "FAIL"
    print(f"\nG-F ({arm}): {n_pass}/{n_docs} documents -> {verdict}")
    reasons = {f["reason"] for r in report.values() for f in r["failures"]}
    if reasons - {"schema_collapsed", "account mismatch"}:
        print(f"!! quote-level PB0 failure on SNAPPED documents "
              f"({reasons - {'schema_collapsed', 'account mismatch'}}) — by design "
              f"impossible: HARNESS BUG, veto-audit code AND output before believing "
              f"anything.")
    if verdict == "FAIL":
        print("Per spec §6 this arm is REPORTED and EXCLUDED from any win claim.")
    pb0_art(arm).write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "arm": arm, "verdict": verdict, "n_pass": n_pass, "n_docs": n_docs,
        "pb1_resized": {doc_id: pb1_doc_resized(rec["playbook"],
                                                arm_doc_evidence(ev, rec))
                        for doc_id, rec in sorted(sn["documents"].items())},
        "per_document": report}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {pb0_art(arm).name}")
    print(f"RT PB0/G-F COMPLETE ({arm})", flush=True)


# ======================================================================================
# Stage 4 — the blinded head-to-head read
# ======================================================================================

def stage_build_read(comparison: str) -> None:
    import random

    _no_clobber(packet_art(comparison))
    _no_clobber(key_art(comparison))
    treat_arm, base_arm = COMPARISONS[comparison]

    for arm in (treat_arm, base_arm):
        v = json.loads(pb0_art(arm).read_text(encoding="utf-8-sig")) \
            if pb0_art(arm).exists() else None
        if v is None:
            raise SystemExit(f"run --pb0 --arm {arm} first (G-F gates readability)")
        if v["verdict"] != "PASS":
            raise SystemExit(f"arm {arm!r} FAILED G-F ({v['n_pass']}/{v['n_docs']}); its "
                             f"documents are not evidence about routing. Refusing to "
                             f"build a read.")
    docs = {arm: json.loads(snapped_art(arm).read_text(encoding="utf-8-sig"))["documents"]
            for arm in (treat_arm, base_arm)}
    ev = json.loads(evidence_art(base_arm).read_text(encoding="utf-8-sig"))
    pilot = ev["pilot"]

    if not PBS_SNAPPED.exists():
        raise SystemExit(f"{PBS_SNAPPED.name} missing — the published snap-trial pairs are "
                         f"the G-P calibration items")
    cal_docs = json.loads(PBS_SNAPPED.read_text(encoding="utf-8-sig"))["documents"]
    cal_map = _cal_scenario_map()
    for scen in CAL_SCENARIOS:
        for side in ("real", "placebo"):
            if f"{scen}::{side}" not in cal_docs:
                raise SystemExit(f"{PBS_SNAPPED.name} has no {scen}::{side} document")
        if scen in pilot:
            raise SystemExit(f"calibration scenario {scen!r} is also a PILOT scenario — "
                             f"familiarity with a control-derived document would anchor "
                             f"the routing item and bias it toward the control")

    _, scenario_map = _load_taxonomy()
    rng = packet_rng(comparison)
    items = build_packet_items(pilot, comparison, rng)
    negs = neg_headers(ev["ranking"], pilot)

    # NEG documents are assembled from the documents this packet displays — the frozen
    # shape from W4 and PV, on the record there and unchanged here.
    neg_pool = [r["playbook"] for arm in (treat_arm, base_arm)
                for _, r in sorted(docs[arm].items()) if r["playbook"].get("key_moves")]
    if len(neg_pool) < 3:
        raise SystemExit("fewer than 3 documents with key_moves — cannot build negatives")

    lines = list(ROUTE_PACKET_HEADER)
    key_rows = []
    for i, it in enumerate(items, 1):
        if it["kind"] == "NEG":
            neg = build_neg(neg_pool, rng)
            head_scen = negs[it["neg_index"]]
            lines += [f"--- ITEM {i} (SINGLE) ---",
                      f"SCENARIO: {head_scen}\n  "
                      f"{scenario_map[head_scen].get('business_description', '')}",
                      "DOCUMENT:"]
            lines += render_doc(neg)
            key_rows.append({"item": i, "kind": "NEG", "header_scenario": head_scen})
            lines.append("")
            continue

        scen = it["scenario"]
        # A CAL item's scenario lives in the OLD map, a ROUTE item's in the new one.
        info = (cal_map if it["kind"] == "CAL" else scenario_map)[scen]
        head = f"SCENARIO: {scen}\n  {info.get('business_description', '')}"
        if it["kind"] == "ROUTE":
            t = docs[treat_arm][f"{scen}::real"]["playbook"]
            b = docs[base_arm][f"{scen}::real"]["playbook"]
            side = it["treat_side"]
            a_doc, b_doc = (t, b) if side == "A" else (b, t)
            key_rows.append({"item": i, "kind": "ROUTE", "scenario": scen,
                             "treat_arm": treat_arm, "base_arm": base_arm,
                             "treat_side": side,
                             "n_moves_treat": len(t["key_moves"]),
                             "n_moves_base": len(b["key_moves"])})
        else:
            real = cal_docs[f"{scen}::real"]["playbook"]
            plc = cal_docs[f"{scen}::placebo"]["playbook"]
            side = it["real_side"]
            a_doc, b_doc = (real, plc) if side == "A" else (plc, real)
            key_rows.append({"item": i, "kind": "CAL", "scenario": scen,
                             "real_side": side, "source": PBS_SNAPPED.name,
                             "n_moves_real": len(real["key_moves"]),
                             # the move-count channel, recorded at packet-build time so
                             # `cal_channels` can report it without re-opening pbs_*
                             "n_moves_placebo": len(plc["key_moves"])})
        lines += [f"--- ITEM {i} (PAIR) ---", head, "DOCUMENT A:"]
        lines += render_doc(a_doc)
        lines.append("DOCUMENT B:")
        lines += render_doc(b_doc)
        lines.append("")

    lines += [
        "=" * 96,
        "REQUIRED ANSWER FORMAT — one JSON object, nothing else:",
        '{"1": {"choice": "A", "apply_A": ["APPLY", ...], "apply_B": ["VAGUE", ...]},',
        ' "2": {"answer": "NO"}, ...}',
        "PAIR items take choice/apply_A/apply_B (one rating per KEY MOVE, display",
        "order); SINGLE items take answer. Every item number must appear.",
    ]
    packet_art(comparison).write_text("\n".join(lines), encoding="utf-8")
    key_art(comparison).write_text(json.dumps({
        "seed": SEED, "comparison": comparison,
        "treatment_arm": treat_arm, "base_arm": base_arm,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "counterbalanced": True, "composition": dict(Counter(r["kind"] for r in key_rows)),
        "items": key_rows}, indent=1), encoding="utf-8")
    print(f"wrote {packet_art(comparison).name} ({len(items)} items) and "
          f"{key_art(comparison).name} (readers must NEVER see the key)")
    print(f"treatment ({treat_arm}) sides: "
          + str({r['scenario']: r['treat_side'] for r in key_rows
                 if r['kind'] == 'ROUTE'}))
    print(f"RT PACKET READY ({comparison})", flush=True)


def stage_score(comparison: str, round_: int | None = None) -> None:
    _no_clobber(report_art(comparison) if round_ is None
                else ARTIFACTS_DIR / f"rt_{comparison}_round{round_}_report.json")
    if not key_art(comparison).exists():
        raise SystemExit(f"run --build-read --comparison {comparison} first")
    key = json.loads(key_art(comparison).read_text(encoding="utf-8-sig"))
    files = sorted(ARTIFACTS_DIR.glob(judgments_glob(comparison, round_)))
    if not files:
        raise SystemExit("no judgment files — dispatch blinded readers first")
    # A round holds exactly N_VALID_READERS readers. More files than that means two
    # dispatches have been mixed into one namespace, and silently truncating to the first
    # three in filename order is how a re-dispatched VOID gets re-scored as the discarded
    # trio. Refuse and make the operator name the round.
    if len(files) > N_VALID_READERS:
        raise SystemExit(
            f"{len(files)} judgment files match {judgments_glob(comparison, round_)!r} but "
            f"a round holds {N_VALID_READERS}. Two dispatches are mixed in one namespace; "
            f"scoring the first {N_VALID_READERS} in filename order would silently re-score "
            f"a discarded round. Re-dispatch into a scoped round "
            f"(rt_{comparison}_round2_judgments_r*.json) and pass --round 2.")
    judgments = [json.loads(f.read_text(encoding="utf-8-sig")) for f in files]
    print(f"[score] round {round_ or 1}, {len(judgments)} judgment file(s): "
          + ", ".join(f.name for f in files))

    res = score_headtohead(key, judgments)
    treat_arm, base_arm = COMPARISONS[comparison]

    # THE ROUTING DIAGNOSTICS TRAVEL WITH THE VERDICT (audit finding 7). Spec §0.9: r1's
    # lookup/fallback split is "a REPORTED number on the primary read, never a footnote" —
    # a win reported without it invites crediting membership for a result that is ~59% the
    # control's own routing. Spec §7.4 asks for every Stage 1 diagnostic here too.
    routing = {}
    for arm in (treat_arm, base_arm):
        if route_art(arm).exists():
            r = json.loads(route_art(arm).read_text(encoding="utf-8-sig"))
            routing[arm] = {"routing_diag": r.get("routing_diag"),
                            "sink_shares_by_origin": r.get("sink_shares_by_origin"),
                            "own_pilot_pick": r.get("own_pilot_pick")}
    gd_row = None
    if DIVERGENCE.exists():
        gd_row = json.loads(DIVERGENCE.read_text(encoding="utf-8-sig")
                            )["arms"].get(treat_arm)
    lookup = (routing.get(treat_arm, {}).get("routing_diag") or {}).get("r1_lookup_share")
    if lookup is not None:
        print(f"[routing] {treat_arm} lookup share {lookup:.1%} / fallback "
              f"{1 - lookup:.1%} — a result this arm produces is that share membership's "
              f"and the rest the control's.")
    bar = PHASE2_WIN if comparison == "k_vs_r1" else WIN_SCENARIOS
    if res["verdict"] != "VOID" and comparison == "k_vs_r1":
        # The tie-break's only difference is its bar (>= 3 of 5, spec §8.1).
        n = res["g_w"]["scenarios_treatment_preferred"]
        res["won"] = n >= PHASE2_WIN
        res["verdict"] = (f"{treat_arm} WINS" if res["won"]
                          else (f"{base_arm} WINS" if (len(res["per_scenario"]) - n)
                                >= PHASE2_WIN else "UNRESOLVED — operator chooses"))
    print("=" * 88)
    if res["verdict"] == "VOID":
        print(f"READ VOID — {res['reason']}")
    else:
        gp = res["g_p"]
        print(f"G-V 3/3 valid | G-P {gp['n_real_preferred']}/{len(gp['calibration_pairs'])} "
              f"{'PASS' if gp['pass'] else 'FAIL'} | "
              f"{treat_arm} preferred in {res['g_w']['scenarios_treatment_preferred']}"
              f"/{res['g_w']['n_scenarios']} (bar {bar}) | pooled "
              f"{res['g_w']['pooled_votes']['treatment']}–"
              f"{res['g_w']['pooled_votes']['base']} | apply-share median "
              f"{res['apply_share']['median']:.2f}")
        print(f"VERDICT ({comparison}): {res['verdict']}")
        if res.get("won") and comparison != "k_vs_r1":
            print("A win requires the §8.2 permutation placebo to be run and BEATEN "
                  "before any scale-up or production change. Ask the operator.")
    print("=" * 88)
    out_path = (report_art(comparison) if round_ is None
                else ARTIFACTS_DIR / f"rt_{comparison}_round{round_}_report.json")
    out_path.write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "comparison": comparison, "read_round": round_ or 1,
        "judgment_files": [f.name for f in files],
        "treatment_arm": treat_arm, "base_arm": base_arm,
        "bar_scenarios": bar, "taxonomy": TAXONOMY,
        "routing": routing, "divergence": gd_row,
        "calibration_channels": cal_channels(key), **res},
        indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_path.name}")
    print(f"RT SCORED ({comparison})", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arm", default=None)
    p.add_argument("--comparison", default=None)
    p.add_argument("--round", type=int, default=None, dest="round_",
                   help="re-dispatch round for --score after a VOID packet (>= 2); "
                        "readers write rt_<cmp>_round<N>_judgments_r*.json")
    p.add_argument("--select", action="store_true")
    p.add_argument("--divergence", action="store_true")
    p.add_argument("--synthesize", action="store_true")
    p.add_argument("--snap", action="store_true")
    p.add_argument("--pb0", action="store_true")
    p.add_argument("--build-read", action="store_true")
    p.add_argument("--score", action="store_true")
    a = p.parse_args()

    per_arm = (a.select, a.synthesize, a.snap, a.pb0)
    per_cmp = (a.build_read, a.score)
    if any(per_arm) and not a.arm:
        raise SystemExit("--arm is required for --select/--synthesize/--snap/--pb0")
    if any(per_cmp) and not a.comparison:
        raise SystemExit("--comparison is required for --build-read/--score")
    if sum(map(bool, [*per_arm, *per_cmp, a.divergence])) > 1:
        # ONE ARM PER PROCESS (spec §0.7) and, by the same reasoning, one stage per
        # process: the keyphrases arm mutates a process-wide singleton.
        raise SystemExit("run exactly one stage per process")

    if a.select:
        stage_select(_check_arm(a.arm))
    elif a.divergence:
        stage_divergence()
    elif a.synthesize:
        stage_synthesize(_check_arm(a.arm))
    elif a.snap:
        stage_snap(_check_arm(a.arm))
    elif a.pb0:
        stage_pb0(_check_arm(a.arm))
    elif a.build_read:
        stage_build_read(_check_comparison(a.comparison))
    elif a.score:
        stage_score(_check_comparison(a.comparison), a.round_)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
