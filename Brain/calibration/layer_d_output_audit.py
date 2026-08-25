"""Post-production output audit + the operator read-through packet. ZERO chat spend.

Two jobs over the STORED production verdicts (run 137706da74c6, csm/pairwise):

  --readthrough   The spec's verification step 5: an UNBLINDED file organized by the
                  top coaching priorities -- every moment behind each priority with
                  the client moment, the CSM's reply, the reconstructed benchmark
                  exemplar, and the model's per-move verdict. For the operator to
                  read against reality.

  --audit         A BLINDED at-scale check of the production instrument (which ran
                  single-order/noswap): a stratified sample of graded moments packed
                  into reader packets (C4 pattern -- KEY separate, no verdicts in
                  the packet). Readers judge independently; --score measures
                  reader-vs-model agreement on mutually decisive verdicts. Because
                  the stored verdicts came from the noswap instrument, this also
                  retroactively measures what dropping the swap cost.

Exemplar reconstruction: the production exemplar picker is DETERMINISTIC (top
cosine over the scenario's kb_pair triggers, all vectors cached), so re-running it
reproduces the exact reply B each judgment saw. Zero embedding spend on a warm
cache; the DB session is forced read-only.

Usage (from Brain/):
    python calibration/layer_d_output_audit.py --readthrough
    python calibration/layer_d_output_audit.py --audit
    python calibration/layer_d_output_audit.py --score artifacts/layer_d_oa_reader1.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402
from config import load_config  # noqa: E402
from layer_d.pipeline import live_playbooks_flat, make_exemplar_picker, playbook_move_specs  # noqa: E402
from shared import storage  # noqa: E402

READTHROUGH = ARTIFACTS_DIR / "layer_d_readthrough.md"
AUDIT_PACKET = ARTIFACTS_DIR / "layer_d_oa_packet{n}.txt"
AUDIT_KEY = ARTIFACTS_DIR / "layer_d_oa_KEY.json"
AUDIT_MODEL = ARTIFACTS_DIR / "layer_d_oa_model_verdicts.json"

TOP_CELLS = 3            # priorities covered by the read-through
AUDIT_N = 40             # blinded audit sample size
PACKET_SIZE = 20


def connect_ro():
    cfg = load_config()
    url = cfg.database_url
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + "hostaddr=18.138.49.39"
    import psycopg
    conn = psycopg.connect(url, connect_timeout=30)
    with conn.cursor() as cur:
        cur.execute("SET SESSION default_transaction_read_only = on")
    return conn


def load_events(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT move_event_id, call_id, scenario_key, playbook_id, source_ref,
                   trigger_text, response_text, verdicts
            FROM move_events
            WHERE rater_population='csm' AND grader_arm='pairwise'
              AND response_outcome='csm' AND verdicts != '[]'::jsonb
            ORDER BY move_event_id
        """)
        rows = cur.fetchall()
    return [
        {"id": r[0], "call_id": r[1], "scenario_key": r[2], "playbook_id": r[3],
         "source_ref": r[4], "trigger_text": r[5], "response_text": r[6],
         "verdicts": r[7]}
        for r in rows
    ]


def rebuild_exemplars(conn, events: list[dict]) -> dict[int, dict]:
    """move_event_id -> the exemplar production used, reconstructed exactly."""
    from preprocessing import embedder
    pickers: dict[str, callable] = {}
    out: dict[int, dict] = {}
    for scen in sorted({e["scenario_key"] for e in events}):
        pairs = storage.get_pairs_for_scenario_multilabel(conn, scen)
        pickers[scen] = make_exemplar_picker(pairs, embedder.embed_query_matrix)
    for e in events:
        out[e["id"]] = pickers[e["scenario_key"]]({"trigger_text": e["trigger_text"]})
    return out


def top_priority_cells(conn) -> list[tuple[int, str]]:
    """The report's top cells: lowest shrunken match-or-beat among rankable,
    non-blurry cells -- mirrors aggregate.rank_pairwise's ordering closely enough
    for packet selection (exact ranking lives in the report itself)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT playbook_id, move_id, attempts, hits, partials
            FROM move_performance
            WHERE rater_population='csm' AND grader_arm='pairwise' AND attempts >= 8
              AND partials::float / attempts < 0.8
            ORDER BY (hits + 0.5 * partials)::float / attempts ASC
            LIMIT %s
        """, (TOP_CELLS,))
        return [(r[0], r[1]) for r in cur.fetchall()]


def move_meta(conn) -> dict[tuple[int, str], dict]:
    out = {}
    for pb in live_playbooks_flat(conn):
        for m in pb["key_moves"]:
            out[(pb["playbook_id"], m["move_id"])] = {
                "scenario_key": pb["scenario_key"], "name": m.get("name", ""),
                "criterion": m.get("criterion", ""),
                "signature": pb.get("situation_signature", ""),
                "moves": playbook_move_specs(pb),
            }
    return out


def build_readthrough() -> None:
    conn = connect_ro()
    cells = top_priority_cells(conn)
    meta = move_meta(conn)
    events = load_events(conn)
    by_scen: dict[str, list[dict]] = {}
    for e in events:
        by_scen.setdefault(e["scenario_key"], []).append(e)

    wanted: list[dict] = []
    for pb_id, mv in cells:
        scen = meta[(pb_id, mv)]["scenario_key"]
        for e in by_scen.get(scen, []):
            verdict = next((v for v in e["verdicts"] if v["move_id"] == mv), None)
            if verdict and verdict["verdict"] in ("hit", "partial", "miss"):
                wanted.append({**e, "cell": (pb_id, mv), "cell_verdict": verdict})
    ex = rebuild_exemplars(conn, wanted)
    conn.close()

    label = {"hit": "SHE WON", "partial": "JUDGED EQUAL", "miss": "BENCHMARK WON"}
    lines = ["# Layer D read-through — the moments behind the top priorities",
             "", "Spec verification step 5: read each moment and ask ONE question —",
             "does the verdict match what a coach who knows these calls would say?",
             ""]
    for pb_id, mv in cells:
        m = meta[(pb_id, mv)]
        cell_events = [w for w in wanted if w["cell"] == (pb_id, mv)]
        counts = Counter(w["cell_verdict"]["verdict"] for w in cell_events)
        lines += [f"## [{m['scenario_key']}] {mv}: {m['name']}",
                  f"**Criterion:** {m['criterion']}",
                  f"**Record:** won {counts['hit']}, equal {counts['partial']}, "
                  f"lost {counts['miss']} of {len(cell_events)} moments", ""]
        for i, w in enumerate(cell_events, 1):
            lines += [f"### Moment {i} — call `{w['call_id']}` ({w['source_ref']}) "
                      f"→ **{label[w['cell_verdict']['verdict']]}**",
                      f"**Client:** {w['trigger_text']}", "",
                      f"**Madhumita:** {w['response_text']}", "",
                      f"**Benchmark exemplar (Naren):** {ex[w['id']]['response_text']}",
                      "", "---", ""]
    READTHROUGH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[readthrough] {READTHROUGH} ({len(wanted)} moments across {len(cells)} cells)")


def audit_sample(events: list[dict]) -> list[dict]:
    """Stratified, deterministic: prefer moments with at least one decisive verdict
    (they carry the checkable claims), round-robin across scenarios, topped up with
    all-equal moments so the reader also checks the judge's ties."""
    decisive = [e for e in events
                if any(v["verdict"] in ("hit", "miss") for v in e["verdicts"])]
    ties_only = [e for e in events if e not in decisive]
    picked: list[dict] = []
    for pool, cap in ((decisive, int(AUDIT_N * 0.75)), (ties_only, AUDIT_N)):
        by_scen: dict[str, list[dict]] = {}
        for e in pool:
            by_scen.setdefault(e["scenario_key"], []).append(e)
        while len(picked) < cap and any(by_scen.values()):
            for scen in sorted(by_scen):
                if by_scen[scen] and len(picked) < cap:
                    picked.append(by_scen[scen].pop(0))
    return picked[:AUDIT_N]


def build_audit() -> None:
    conn = connect_ro()
    meta = move_meta(conn)
    events = load_events(conn)
    sample = audit_sample(events)
    ex = rebuild_exemplars(conn, sample)
    conn.close()

    key_rows, model_rows, parts = [], [], []
    for i, e in enumerate(sample, 1):
        pb_meta = meta[(e["playbook_id"], next(iter(
            [v["move_id"] for v in e["verdicts"]])))]
        csm_a = int(hashlib.sha1(f"oa|{e['id']}".encode()).hexdigest(), 16) % 2 == 0
        exm = ex[e["id"]]
        reply_a = e["response_text"] if csm_a else exm["response_text"]
        reply_b = exm["response_text"] if csm_a else e["response_text"]
        trig_a = e["trigger_text"] if csm_a else exm["trigger_text"]
        trig_b = exm["trigger_text"] if csm_a else e["trigger_text"]
        key_rows.append({"item": i, "move_event_id": e["id"], "csm_is": "A" if csm_a else "B"})
        model_rows.append({"item": i, "move_event_id": e["id"],
                           "verdicts": [(v["move_id"], v["verdict"]) for v in e["verdicts"]]})
        moves_block = "\n".join(f"- {mv['move_id']} ({mv['name']}): {mv['criterion']}"
                                for mv in pb_meta["moves"])
        parts.append(f"""ITEM {i}
SCENARIO: {e['scenario_key']}
{pb_meta['signature']}

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

    header = ("BLINDED READ -- for each item and each move, answer A, B, or equal.\n"
              "Judge execution of the specific move, not polish or length.\n"
              "Respond as JSON: [{\"item\": 1, \"verdicts\": "
              "[{\"move_id\": \"M1\", \"better\": \"A\"}, ...]}, ...]\n\n")
    for n in range(1, -(-len(parts) // PACKET_SIZE) + 1):
        chunk = parts[(n - 1) * PACKET_SIZE: n * PACKET_SIZE]
        Path(str(AUDIT_PACKET).format(n=n)).write_text(
            header + ("\n" + "=" * 78 + "\n").join(chunk), encoding="utf-8")
    AUDIT_KEY.write_text(json.dumps(key_rows, indent=1), encoding="utf-8")
    AUDIT_MODEL.write_text(json.dumps(model_rows, indent=1), encoding="utf-8")
    n_packets = -(-len(parts) // PACKET_SIZE)
    print(f"[audit] {len(sample)} moments -> {n_packets} packet(s); KEY + model "
          f"verdicts kept OUT of the packets")


def score(answers_paths: list[Path]) -> None:
    key = {k["item"]: k["csm_is"] for k in json.loads(AUDIT_KEY.read_text(encoding="utf-8"))}
    model = {m["item"]: dict((mv, v) for mv, v in m["verdicts"])
             for m in json.loads(AUDIT_MODEL.read_text(encoding="utf-8"))}
    agree = disagree = both_equal = model_eq_reader_dec = reader_eq_model_dec = 0
    for path in answers_paths:
        for a in json.loads(path.read_text(encoding="utf-8")):
            item = int(a["item"])
            for v in a.get("verdicts", []):
                pick = str(v.get("better", "")).strip()
                mverdict = model.get(item, {}).get(str(v.get("move_id", "")))
                if mverdict is None:
                    continue
                m_dec = mverdict in ("hit", "miss")
                r_dec = pick in ("A", "B")
                if not m_dec and not r_dec:
                    both_equal += 1
                elif m_dec and not r_dec:
                    model_eq_reader_dec += 0  # model decisive, reader equal
                    reader_eq_model_dec += 1
                elif r_dec and not m_dec:
                    model_eq_reader_dec += 1
                else:
                    model_csm_won = (mverdict == "hit")
                    reader_csm_won = (pick == key[item])
                    if model_csm_won == reader_csm_won:
                        agree += 1
                    else:
                        disagree += 1
    n = agree + disagree
    print(f"mutually decisive: {n}; agreement {agree}/{n} = "
          f"{(agree / n if n else float('nan')):.1%}")
    print(f"both said equal: {both_equal}; model decisive but reader equal: "
          f"{reader_eq_model_dec}; reader decisive but model equal: {model_eq_reader_dec}")
    print(f"GATE (>=70% on mutually decisive, pre-registered): "
          f"{'PASS' if n and agree / n >= 0.70 else 'FAIL' if n else 'UNDECIDED'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--readthrough", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--score", nargs="+", default=[])
    args = ap.parse_args()
    if args.readthrough:
        build_readthrough()
    if args.audit:
        build_audit()
    if args.score:
        score([Path(p) for p in args.score])
    if not (args.readthrough or args.audit or args.score):
        print(__doc__)


if __name__ == "__main__":
    main()
