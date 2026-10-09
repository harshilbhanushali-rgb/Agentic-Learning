"""C4: the human seal on PRODUCTION-SHAPED pairwise judgments.

Pre-registration: docs/findings/layer-d-redesign.md (§ open after C2). C2 proved the
judge's eyesight on exemplar-vs-exemplar pairs with known truth (77.1%, p=0.00094);
production compares the CSM'S ACTUAL REPLY vs Naren's matched exemplar, a similar
but not identical task. C4 has blinded readers independently judge a sample of
exactly those production-shaped comparisons and measures reader-vs-model agreement.

GATE (frozen before the read): on the verdicts where BOTH the model and the reader
are decisive (neither says equal/unscored), agreement >= 70%. Below that, the
production run does not launch on this instrument.

NOT PRODUCTION. Zero DB writes (read-only session). Spend: n_items x 2 requests
(order swap) at k=1 -- ~30 calls at the default 15 items.

Outputs:
  artifacts/layer_d_c4_judgments.json   the model's verdicts (NOT in the packet)
  artifacts/layer_d_c4_packet.txt       the blinded reader packet
  artifacts/layer_d_c4_KEY.json         blinding key: which reply is whose, per item

Usage (from Brain/, VPN up):
    python calibration/layer_d_c4_read.py            # the bill, zero spend
    python calibration/layer_d_c4_read.py --spend    # judge + build packet
    python calibration/layer_d_c4_read.py --score artifacts/layer_d_c4_reader1.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402
from calibration.layer_d_grader_ab import exemplar_index, top_exemplar  # noqa: E402
from config import load_config  # noqa: E402
from layer_d import graders  # noqa: E402
from layer_d.pipeline import gateway_chat, live_playbooks_flat, playbook_move_specs  # noqa: E402
from shared import storage  # noqa: E402

C2_ARTIFACT = ARTIFACTS_DIR / "layer_d_grader_ab.json"
JUDGMENTS = ARTIFACTS_DIR / "layer_d_c4_judgments.json"
PACKET = ARTIFACTS_DIR / "layer_d_c4_packet.txt"
KEY = ARTIFACTS_DIR / "layer_d_c4_KEY.json"

PER_SCENARIO = 3     # 5 scenarios x 3 = 15 items


def csm_is_a(moment_id: str) -> bool:
    """Deterministic blinding: which side the CSM reply takes in the PACKET.
    Hash-based so it is stable, reproducible, and roughly balanced -- never derived
    from the verdict, so a reader cannot learn a rule like 'A is always the CSM'."""
    return int(hashlib.sha1(moment_id.encode()).hexdigest(), 16) % 2 == 0


def sample_moments() -> list[tuple[str, str]]:
    """First PER_SCENARIO (moment_id, scenario_key) per scenario from the C2
    artifact's population -- already production-detected, gate-passed,
    deterministic. scenario_key travels along so the rebuild can ASSERT the moment
    reproduces under the same routing (audit note: same-id-different-content drift
    would otherwise be silent)."""
    art = json.loads(C2_ARTIFACT.read_text(encoding="utf-8"))
    seen: dict[str, int] = {}
    out = []
    for rec in art["moments"]:
        key = rec["scenario_key"]
        if seen.get(key, 0) >= PER_SCENARIO:
            continue
        seen[key] = seen.get(key, 0) + 1
        out.append((rec["moment_id"], key))
    return out


def rebuild_moment_texts(cfg, wanted: list[str]) -> list[dict]:
    """Re-derive trigger/response text for the sampled moment_ids by re-running
    detection on just the needed transcripts (all embeddings are cache hits)."""
    from ego_trap import csm_registry
    from ego_trap.transcript_parser import parse_transcript
    from layer_d import signals
    from shared.tuning import get_tuning

    d = get_tuning().layer_d
    wanted_ids = {mid for mid, _ in wanted}
    stems = {mid.split(":t")[0] for mid in wanted_ids}
    conn = storage.get_connection(cfg.database_url)
    with conn.cursor() as cur:
        cur.execute("SET SESSION default_transaction_read_only = on")
    scenario_map = {r["scenario_key"]: r for r in storage.get_scenarios(conn)}
    conn.close()
    scorer = signals.SignalScorer(scenario_map, margin=d.similarity_relative_margin,
                                  cap=d.max_scenarios_per_signal)
    recordings = Path(__file__).resolve().parent.parent / "csm_recordings"
    mapping = csm_registry.load_mapping(recordings / "mapping.csv")
    found: dict[str, dict] = {}
    for stem in sorted(stems):
        _, csm_name = mapping[stem]
        turns = parse_transcript(str(recordings / f"{stem}.txt"),
                                 csm_name.strip().lower(), cfg.joveo_speakers_lower)
        for m in signals.detect_moments(turns, stem, scorer, arm=d.segmentation_arm):
            if m.moment_id in wanted_ids:
                found[m.moment_id] = {
                    "moment_id": m.moment_id, "scenario_key": m.scenario_key,
                    "trigger_text": m.trigger_text, "response_text": m.response_text,
                }
    missing = [mid for mid, _ in wanted if mid not in found]
    if missing:
        raise RuntimeError(f"could not re-derive {len(missing)} moment(s): {missing}")
    for mid, expected_key in wanted:
        got = found[mid]["scenario_key"]
        if got != expected_key:
            raise RuntimeError(f"routing drift: {mid} rebuilt as {got!r}, "
                               f"C2 recorded {expected_key!r}")
    return [found[mid] for mid, _ in wanted]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spend", action="store_true")
    ap.add_argument("--score", default="",
                    help="path to a reader's answers JSON: "
                         "[{'item': 1, 'verdicts': [{'move_id': 'M1', 'better': 'A'}]}]")
    args = ap.parse_args()

    if args.score:
        score(Path(args.score))
        return

    wanted = sample_moments()
    print(f"[sample] {len(wanted)} moments from the C2 population")
    print(f"[bill] {len(wanted) * 2} chat requests (production shape, k=1), "
          f"plus resamples on malformed generations")
    if not args.spend:
        print("Zero spend. Re-run with --spend.")
        return

    cfg = load_config()
    moments = rebuild_moment_texts(cfg, wanted)
    conn = storage.get_connection(cfg.database_url)
    with conn.cursor() as cur:
        cur.execute("SET SESSION default_transaction_read_only = on")
    playbooks = {p["scenario_key"]: p for p in live_playbooks_flat(conn)}
    keys = tuple(sorted({m["scenario_key"] for m in moments}))
    ex_index = exemplar_index(conn, keys)
    conn.close()

    from preprocessing import embedder
    trig_vecs = np.asarray(embedder.embed_query_matrix(
        [m["trigger_text"] for m in moments]))

    # Resume (audit finding: paid verdicts must persist as they happen; the
    # artifact is the cache). Items already judged on a prior partial run are kept.
    judgments: list[dict] = []
    key_rows: list[dict] = []
    packet_parts: list[str] = []
    done_ids: set[str] = set()
    if JUDGMENTS.exists():
        judgments = json.loads(JUDGMENTS.read_text(encoding="utf-8"))
        done_ids = {j["moment_id"] for j in judgments}
        if KEY.exists():
            key_rows = json.loads(KEY.read_text(encoding="utf-8"))
        if done_ids:
            print(f"[resume] {len(done_ids)} already-judged item(s) kept")

    chat = gateway_chat()
    for i, m in enumerate(moments):
        pb = playbooks[m["scenario_key"]]
        moves = playbook_move_specs(pb)
        exemplar = top_exemplar(ex_index, m["scenario_key"], trig_vecs[i])
        a_is_csm = csm_is_a(m["moment_id"])

        if m["moment_id"] not in done_ids:
            g = graders.grade_pairwise(
                chat, m["scenario_key"], pb.get("situation_signature", ""), moves,
                m, exemplar)   # moment = the CSM's real reply; production shape
            judgments.append({
                "item": i + 1, "moment_id": m["moment_id"],
                "scenario_key": m["scenario_key"],
                "model_verdicts": [(v.move_id, v.verdict, v.reason)
                                   for v in g.verdicts],
            })
            key_rows.append({"item": i + 1, "moment_id": m["moment_id"],
                             "csm_is": "A" if a_is_csm else "B"})
            JUDGMENTS.write_text(json.dumps(judgments, indent=1), encoding="utf-8")
            KEY.write_text(json.dumps(key_rows, indent=1), encoding="utf-8")
            print(f"  [{i + 1}/{len(moments)}] judged {m['moment_id']}")

        # The packet MIRRORS the model's task exactly (audit finding: the model saw
        # each reply with ITS OWN client moment; showing the reader only the CSM's
        # trigger both changes the task and soft-unblinds -- the native reply is
        # identifiable). Both triggers are shown, assigned by the same blinding.
        trig_a = m["trigger_text"] if a_is_csm else exemplar["trigger_text"]
        trig_b = exemplar["trigger_text"] if a_is_csm else m["trigger_text"]
        reply_a = m["response_text"] if a_is_csm else exemplar["response_text"]
        reply_b = exemplar["response_text"] if a_is_csm else m["response_text"]
        moves_block = "\n".join(f"- {mv['move_id']} ({mv['name']}): {mv['criterion']}"
                                for mv in moves)
        packet_parts.append(f"""ITEM {i + 1}
SCENARIO: {m['scenario_key']}
{pb.get('situation_signature', '')}

MOVES TO JUDGE ON:
{moves_block}

CLIENT MOMENT (context for reply A):
{trig_a}

REPLY A:
{reply_a}

CLIENT MOMENT (context for reply B):
{trig_b}

REPLY B:
{reply_b}

For each move, which reply performs it better: A, B, or equal?
""")

    PACKET.write_text(
        "BLINDED READ -- for each item and each move, answer A, B, or equal.\n"
        "Judge execution of the specific move, not polish or length.\n"
        "Respond as JSON: [{\"item\": 1, \"verdicts\": "
        "[{\"move_id\": \"M1\", \"better\": \"A\"}, ...]}, ...]\n\n"
        + ("\n" + "=" * 78 + "\n").join(packet_parts),
        encoding="utf-8")
    print(f"[artifacts] {JUDGMENTS}\n            {PACKET}\n            {KEY}")
    print("\nNext: a blinded reader answers ONLY the packet file (never the KEY or "
          "judgments); score with --score <answers.json>.")


def score(answers_path: Path) -> None:
    """Reader-vs-model agreement on mutually decisive verdicts. The reader answered
    in PACKET space (A/B as displayed); the model verdicts are in CSM space
    (hit = the CSM's reply won both orders) -- KEY maps between them."""
    judgments = {j["item"]: j for j in json.loads(JUDGMENTS.read_text(encoding="utf-8"))}
    key = {k["item"]: k["csm_is"] for k in json.loads(KEY.read_text(encoding="utf-8"))}
    answers = json.loads(answers_path.read_text(encoding="utf-8"))

    agree = disagree = 0
    for a in answers:
        item = a["item"]
        model = {mv: verdict for mv, verdict, _ in judgments[item]["model_verdicts"]}
        for v in a.get("verdicts", []):
            reader_pick = str(v.get("better", "")).strip()
            model_verdict = model.get(str(v.get("move_id", "")))
            if reader_pick not in ("A", "B") or model_verdict not in ("hit", "miss"):
                continue                     # only mutually decisive verdicts count
            reader_csm_won = (reader_pick == key[item])
            model_csm_won = (model_verdict == "hit")
            if reader_csm_won == model_csm_won:
                agree += 1
            else:
                disagree += 1
    n = agree + disagree
    rate = agree / n if n else float("nan")
    print(f"mutually decisive verdicts: {n}; agreement {agree}/{n} = {rate:.1%}")
    print(f"GATE (>=70% pre-registered): "
          f"{'PASS' if n and rate >= 0.70 else 'FAIL' if n else 'UNDECIDED (n=0)'}")


if __name__ == "__main__":
    main()
