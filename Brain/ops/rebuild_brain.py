#!/usr/bin/env python3
"""Rebuild the Brain into a FRESH database end to end, then evaluate it against live (2026-10-10).

Spec: docs/superpowers/specs/2026-10-10-brain-rebuild-staged-design.md

Operator decision (2026-10-10): NO quality gates between stages. The whole new Brain is
built straight through -- Layer A re-adjudicated on gemini-3.6-flash @ medium, every
playbook regenerated on the current prompts (gradability rule included), Layer D graded --
and the comparison with the live Brain happens ONCE, at the end. Only INTEGRITY checks stop
a run (a failed-row share above 5%, a sink share outside the measured band, the playbook
loader's write verification): those mean the run is broken, not that it lost.

Every child process gets the rebuild environment, never the live one:
    DATABASE_URL        := DATABASE_URL_REBUILD     (refused if it equals the live host)
    BRAIN_HOSTADDR      := ""                        (no pinned live-Neon IP)
    BRAIN_CHECKPOINT_DB := checkpoints_rebuild.db    (the live file would mark all done)
    BRAIN_MOVE_CLASSES  := artifacts/layer_d_move_classes_rebuild.json
    BRAIN_OA_PREFIX     := layer_d_oa_rebuild        (production's audit files stay put)
    BRAIN_MC_PREFIX     := ld_moveclass_rebuild      (same, for the move-class packet)
    BRAIN_TAXONOMY      := union_base36
and every Pinecone write goes to PINECONE_INDEX_NAME_REBUILD. Production -- the live
database, narens-brain-3072, checkpoints.db, the live move classes -- is never written.

    python ops/rebuild_brain.py all          # the BRAIN pipeline only: a, b, c, eval-build
    python ops/rebuild_brain.py status

The pieces of `all`, each resumable on its own after a crash:
    a           ~307 requests   re-adjudicate the live map's 307 clusters on gemini-3.6-flash
    b           no chat         load taxonomy, calls, kb_pairs, trigger/response vectors
    c           ~142            regenerate a playbook for every coachable scenario, load them
    eval-build  free            the blind-read packets for the Brain evaluation

Layer D is NOT part of `all` (operator, 2026-10-10). Only by name, never implied:
    d           1,000+          Layer D pairwise: her calls, then Naren's benchmark
    d-eval-build free           Layer D's packets (after `d`)

The evaluation, after the blind reads (Claude runs those as sonnet readers, one at a time):
    say R1 R2   ~340            score the two move-class reads, then the say run (both raters)
    eval        free            score every read, write artifacts/rebuild_eval_report.json
    report      free            Layer D's combined report on the new database

Recovery: `reset-db` drops every table in the REBUILD database, empties the rebuild Pinecone
index and deletes the rebuild checkpoints (refused on the live host).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

BRAIN = Path(__file__).resolve().parent.parent
PY = BRAIN.parent / ".venv" / "Scripts" / "python.exe"
ART = BRAIN / "artifacts"
CHECKPOINTS = BRAIN / "checkpoints_rebuild.db"
MOVE_CLASSES = ART / "layer_d_move_classes_rebuild.json"
OA_PREFIX = "layer_d_oa_rebuild"
MC_PREFIX = "ld_moveclass_rebuild"
NEW_ARM = "union_base36"
TAG = "rebuild"
EXCLUDED = ("contract_and_legal_review",)   # on the record: "not a retry"
PLAYBOOK_CEILING = 450        # 49 coachable on union_base36 x ~3 calls, with retry room
TOPUP_CEILING = 1500          # selection unit-text vectors a NEW map never bought (540 seen)
EVAL_OUT = ART / "rebuild_eval_report.json"

sys.path.insert(0, str(BRAIN))


# ---------------------------------------------------------------------------------------
# environment and plumbing
# ---------------------------------------------------------------------------------------

def rebuild_env() -> dict[str, str]:
    from dotenv import dotenv_values
    dv = {k: v for k, v in dotenv_values(BRAIN / ".env").items() if v is not None}
    env = dict(os.environ)
    env.update({k: v for k, v in dv.items() if k not in env})
    live, new = dv.get("DATABASE_URL", ""), dv.get("DATABASE_URL_REBUILD", "")
    if not new:
        raise SystemExit("DATABASE_URL_REBUILD is not set in Brain/.env")
    if urlparse(live).hostname == urlparse(new).hostname:
        raise SystemExit("DATABASE_URL_REBUILD points at the LIVE host -- refusing")
    index = dv.get("PINECONE_INDEX_NAME_REBUILD", "")
    if not index or index == "narens-brain-3072":
        raise SystemExit("PINECONE_INDEX_NAME_REBUILD missing or equal to the live index")
    env.update({
        "DATABASE_URL": new,
        "BRAIN_HOSTADDR": "",
        "BRAIN_CHECKPOINT_DB": str(CHECKPOINTS),
        "BRAIN_MOVE_CLASSES": str(MOVE_CLASSES),
        "BRAIN_OA_PREFIX": OA_PREFIX,
        "BRAIN_MC_PREFIX": MC_PREFIX,
        "BRAIN_TAXONOMY": NEW_ARM,
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    return env


def run(args: list[str]) -> None:
    print(f"\n{'=' * 78}\n  {' '.join(args)}\n{'=' * 78}", flush=True)
    rc = subprocess.call([str(PY), *args], cwd=str(BRAIN), env=rebuild_env())
    if rc != 0:
        raise SystemExit(f"STEP FAILED (exit {rc}): {' '.join(args)} -- fix the cause and "
                         f"re-run; every paid step resumes from its own checkpoint")


def connect():
    import psycopg
    return psycopg.connect(rebuild_env()["DATABASE_URL"], connect_timeout=30, autocommit=True)


def scalar(sql: str):
    with connect() as c, c.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def coachable_keys() -> list[str]:
    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT scenario_key FROM scenarios WHERE is_coachable ORDER BY 1")
        return [r[0] for r in cur.fetchall() if r[0] not in EXCLUDED]


def readers(glob: str) -> list[Path]:
    return sorted(ART.glob(glob))


# ---------------------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------------------

GATES = ["calibration/union_taxonomy_gates.py", "--arm", "base36"]


def stage_a() -> None:
    from calibration.adjudication_ab import paths, t2_verdict
    done = paths(NEW_ARM)[1]
    if not (done.exists() and not json.loads(done.read_text(encoding="utf-8-sig"))
            .get("incomplete")):
        _adjudicate()
    art = json.loads(done.read_text(encoding="utf-8-sig"))
    t2 = t2_verdict(art["stats"], art.get("served_models", {}))
    _after_adjudication(t2)


def _adjudicate() -> None:
    run(["calibration/adjudication_ab.py", "--arm", NEW_ARM,
         "--recordings", "recordings,recordings_pull_keep",
         "--clusters-from", "artifacts/union_clusters.json", "--membership", "base",
         "--budget", "100000",
         "--chat-model", "gemini-3.6-flash", "--reasoning-effort", "medium"])


def _after_adjudication(t2: dict) -> None:
    print(f"[T2] failed {t2['failed']}/{t2['n']}, served {t2['served_models']}")
    if not t2["pass"]:
        raise SystemExit("INTEGRITY: more than 5% of clusters failed -- the map is incomplete. "
                         "Re-run `a` (it resumes) before building on it.")
    if not t2["served_uniform"]:
        print("!! the gateway answered part of the run with a fallback model -- on the record")
    # Measurements, not gates: G-R1 (cohesion) and G-R2/G-R3 (routing) are free, and Stage B's
    # sink-share integrity band comes from G-R2's measured share.
    for flag in ("--g1", "--g2g3"):
        out = ART / f"union_gates_base36_{'g1' if flag == '--g1' else 'g2g3'}.json"
        if not out.exists():
            run(GATES + [flag])


def stage_b() -> None:
    env = rebuild_env()
    from shared import pinecone_store
    pinecone_store.init_index(env["PINECONE_API_KEY"], env["PINECONE_INDEX_NAME_REBUILD"],
                              dimension=3072)
    run(["db/init_db.py"])
    if scalar("SELECT count(*) FROM scenarios") == 0:
        run(["ops/ship_union_taxonomy.py", "--apply", "--hostaddr", "",
             "--snapshot", "rebuild_pre_load"])
    g23 = json.loads((ART / "union_gates_base36_g2g3.json").read_text(encoding="utf-8"))
    shares = (g23["g2"]["new_sink_share"], g23["g2"]["old_sink_share"])
    band = f"{max(min(shares) - 0.03, 0):.3f},{min(max(shares) + 0.03, 1):.3f}"
    from pinecone import Pinecone
    ix = Pinecone(api_key=env["PINECONE_API_KEY"]).Index(env["PINECONE_INDEX_NAME_REBUILD"])

    def namespaces() -> dict:
        stats = ix.describe_index_stats()
        return {k: v["vector_count"] for k, v in (stats.get("namespaces") or {}).items()}

    n_pairs, ns = scalar("SELECT count(*) FROM kb_pairs"), namespaces()
    if n_pairs and ns.get("triggers") == n_pairs and ns.get("responses") == n_pairs:
        print(f"[B] already loaded: {n_pairs} kb_pairs, vectors {ns} -- skipped")
    else:
        resume = ["--resume-vectors"] if n_pairs else []
        run(["ops/ship_layer_b.py", "--apply", "--hostaddr", "",
             "--index", env["PINECONE_INDEX_NAME_REBUILD"], "--sink-band", band, *resume])
        ns = namespaces()
    print(f"[B] scenarios {scalar('SELECT count(*) FROM scenarios')} "
          f"({scalar('SELECT count(*) FROM scenarios WHERE is_coachable')} coachable), "
          f"kb_pairs {scalar('SELECT count(*) FROM kb_pairs')}, vectors {ns}")


def stage_c() -> None:
    keys = coachable_keys()
    print(f"[C] {len(keys)} coachable scenarios (excluding {EXCLUDED})")
    base = ["calibration/playbook_backfill.py", "--scenarios", ",".join(keys), "--tag", TAG,
            "--ceiling", str(PLAYBOOK_CEILING), "--topup-ceiling", str(TOPUP_CEILING)]
    if not (ART / f"pbf_{TAG}_snapped.json").exists():
        run(base)                                    # free: evidence + the budget line
        run(base + ["--synthesize"])
    if scalar("SELECT count(*) FROM playbooks") == 0:
        run(["ops/load_playbooks.py", "--apply", "--hostaddr", "",
             "--plan-artifact", f"pbf_{TAG}_snapped.json"])
    n_live = scalar("SELECT count(*) FROM playbooks WHERE status='live'")
    print(f"[C] live playbooks: {n_live}")


def stage_d() -> None:
    run(["ops/run_layer_d.py", "--grader-arm", "pairwise"])
    run(["ops/run_layer_d.py", "--grader-arm", "pairwise", "--naren-only"])


def stage_eval_build() -> None:
    steps = [
        (ART / "union_gates_base36_read_packet.txt", GATES + ["--g4-build"]),
        (ART / "rebuild_a_h2h_build.json", ["calibration/rebuild_stage_a_h2h.py", "--build"]),
        (ART / "rebuild_c_h2h_packet.txt",
         ["calibration/rebuild_stage_c_h2h.py", "--build", "--tag", TAG, "--taxonomy", NEW_ARM]),
    ]
    for done, args in steps:
        if done.exists():
            print(f"[eval-build] {done.name} exists -- kept (packets are frozen once built)")
        else:
            run(args)
    print("\nBLIND READS NEEDED (sonnet readers, one at a time), then `eval`:\n"
          "  union_gates_base36_read_packet.txt   3 readers -> union_gates_base36_judgments_r*.json\n"
          "  rebuild_a_h2h_packet.txt             3 readers -> rebuild_a_h2h_judgments_r*.json\n"
          "  rebuild_c_h2h_packet.txt             3 readers -> rebuild_c_h2h_judgments_r*.json")


def stage_d_eval_build() -> None:
    """Layer D's packets -- only after an explicit `d`."""
    if not scalar("SELECT count(*) FROM move_events"):
        raise SystemExit("no Layer D verdicts in the rebuild database -- `d` has not run")
    for done, args in (
            (ART / f"{MC_PREFIX}_packet.txt",
             ["calibration/layer_d_move_classes_packet.py", "--packet"]),
            (ART / f"{OA_PREFIX}_KEY.json", ["calibration/layer_d_output_audit.py", "--audit"])):
        if not done.exists():
            run(args)
    print(f"READERS: {OA_PREFIX}_packet*.txt, {MC_PREFIX}_packet.txt (2 readers, then `say R1 R2`)")


def stage_all() -> None:
    # The BRAIN pipeline only. Layer D is not part of `all` (operator, 2026-10-10): it runs
    # only when asked for by name -- `d`, then `d-eval-build`, `say R1 R2`.
    for f in (stage_a, stage_b, stage_c, stage_eval_build):
        print(f"\n######## {f.__name__} ########", flush=True)
        f()
    print("\nBRAIN BUILD COMPLETE (Layers A-C). Layer D was not run. Blind reads next.")


# ---------------------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------------------

def stage_say(r1: str, r2: str) -> None:
    run(["calibration/layer_d_move_classes_packet.py", "--score", r1, r2, "--write"])
    run(["ops/run_layer_d.py", "--grader-arm", "say"])
    run(["ops/run_layer_d.py", "--grader-arm", "say", "--naren-only"])


def _json(name: str):
    p = ART / name
    return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else None


def stage_eval() -> None:
    if readers("union_gates_base36_judgments_*.json") and not (ART / "union_gates_base36_g4.json").exists():
        run(GATES + ["--g4-score"])
    run(GATES + ["--report"])
    if readers("rebuild_a_h2h_judgments_*.json"):
        run(["calibration/rebuild_stage_a_h2h.py", "--score"])
    if readers("rebuild_c_h2h_judgments_*.json"):
        run(["calibration/rebuild_stage_c_h2h.py", "--score", "--tag", TAG,
             "--taxonomy", NEW_ARM])
    oa = [str(p.relative_to(BRAIN)) for p in readers(f"{OA_PREFIX}_reader*.json")]
    if oa:
        run(["calibration/layer_d_output_audit.py", "--score", *oa])
    live_gates = _json("union_gates_fallback_report.json")
    report = {
        "taxonomy": {"live": "union_base (gemini-3.5-flash-lite)",
                     "new": f"{NEW_ARM} (gemini-3.6-flash medium)",
                     "gates_live": live_gates and live_gates.get("gates"),
                     "gates_new": (_json("union_gates_base36_report.json") or {}).get("gates")},
        "routing_head_to_head": _json("rebuild_a_h2h_result.json")
                                or _json("rebuild_a_h2h_build.json"),
        "playbook_head_to_head": _json("rebuild_c_h2h_result.json"),
        "new_database": {
            "scenarios": scalar("SELECT count(*) FROM scenarios"),
            "coachable": scalar("SELECT count(*) FROM scenarios WHERE is_coachable"),
            "kb_pairs": scalar("SELECT count(*) FROM kb_pairs"),
            "live_playbooks": scalar("SELECT count(*) FROM playbooks WHERE status='live'"),
            "move_events": scalar("SELECT count(*) FROM move_events"),
        },
        "layer_d_output_audit": "see the `--score` output above (gate >= 70%)" if oa else None,
    }
    EVAL_OUT.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps(report, indent=1, default=str))
    print(f"\nwrote {EVAL_OUT.name}. Live Layer D numbers for the side-by-side: "
          f"`python ops/run_layer_d.py --report-combined --hostaddr 18.138.49.39` "
          f"(live DB) vs `rebuild_brain.py report`.")


def stage_report() -> None:
    run(["ops/run_layer_d.py", "--report-combined"])


def reset_db() -> None:
    env = rebuild_env()
    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT current_database()")
        print(f"[reset] dropping every table in the REBUILD database {cur.fetchone()[0]}")
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cur.execute("DROP SCHEMA IF EXISTS rebuild_pre_load CASCADE")
    from pinecone import Pinecone
    ix = Pinecone(api_key=env["PINECONE_API_KEY"]).Index(env["PINECONE_INDEX_NAME_REBUILD"])
    for ns in ("triggers", "responses"):
        try:
            ix.delete(delete_all=True, namespace=ns)
        except Exception as e:                      # noqa: BLE001  (an empty namespace)
            print(f"[reset] {ns}: {str(e)[:80]}")
    if CHECKPOINTS.exists():
        CHECKPOINTS.unlink()
    print("[reset] done: empty database, empty rebuild index, no rebuild checkpoints")


def status() -> None:
    env = rebuild_env()
    print(f"database : {urlparse(env['DATABASE_URL']).hostname}")
    print(f"index    : {env['PINECONE_INDEX_NAME_REBUILD']}")
    print(f"taxonomy : {env['BRAIN_TAXONOMY']}")
    for t in ("scenarios", "kb_pairs", "playbooks", "move_events"):
        try:
            print(f"{t:<9}: {scalar(f'SELECT count(*) FROM {t}')}")
        except Exception:                           # noqa: BLE001  (tables not created yet)
            print(f"{t:<9}: (no table)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=("all", "a", "b", "c", "d", "eval-build", "d-eval-build",
                                     "say", "eval",
                                     "report", "status", "reset-db"))
    p.add_argument("reads", nargs="*", help="say: the two move-class reads")
    a = p.parse_args()
    {"all": stage_all, "a": stage_a, "b": stage_b, "c": stage_c, "d": stage_d,
     "eval-build": stage_eval_build, "d-eval-build": stage_d_eval_build,
     "eval": stage_eval, "report": stage_report,
     "status": status, "reset-db": reset_db,
     "say": lambda: stage_say(*a.reads)}[a.stage]()


if __name__ == "__main__":
    main()
