#!/usr/bin/env python3
"""Batch-runs the REDESIGNED Layer D (Brain/layer_d/) over Brain/csm_recordings/.

Run from Brain/ with the venv active and the Joveo VPN up (chat + any novel
embeddings go through the gateway):

    python ops/run_layer_d.py                 # every mapped transcript
    python ops/run_layer_d.py --limit 5       # smoke test: 5 most recent
    python ops/run_layer_d.py --report-only   # zero spend: re-rank from stored events

*** DO NOT TRUST A PRODUCTION RUN BEFORE THE C-STAGE GATES HAVE PASSED. ***
tuning.yaml's layer_d redesign block is UNCALIBRATED in gemini@3072 space until
C0 (bands) / C1 (segmentation replay) / C2 (grader head-to-head) / C3 (Naren
ceiling) have run. See docs/superpowers/specs/2026-08-20-layer-d-redesign-design.md.

Speaker classification FAILS CLOSED: the run refuses to start without
csm_recordings/client_speakers.txt (one verified client speaker name per line)
unless --allow-unverified-speakers is passed. Build the roster from
ops/check_csm_speakers.py plus the Avoma participant rosters.

Re-runs are SAFE, unlike the old ops/run_ego_trap.py: move_events upserts on its
natural key and move_performance is rebuilt by full recompute, so there is no
double-count path and no mandatory clear step. ops/clear_layer_d_data.py exists
for a deliberate from-scratch wipe only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config  # noqa: E402
from shared import checkpoint, storage  # noqa: E402

_BRAIN = Path(__file__).resolve().parent.parent
_RECORDINGS = _BRAIN / "csm_recordings"
_ROSTER = _RECORDINGS / "client_speakers.txt"


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-run the redesigned Layer D.")
    parser.add_argument("--limit", type=int, default=0,
                        help="score only the last N transcripts (filename order). The "
                             "subset gets its own run_id, so its checkpoints never "
                             "collide with a full run's.")
    parser.add_argument("--exclude", default="",
                        help="comma-separated stems to skip. Validated against the "
                             "directory so a typo fails instead of silently excluding "
                             "nothing.")
    parser.add_argument("--allow-unverified-speakers", action="store_true",
                        help="run without a client roster (fail-OPEN classification -- "
                             "the defect that scored internal chatter as client turns "
                             "on the 100-call run). Calibration only.")
    parser.add_argument("--naren-sample", type=int, default=None,
                        help="Naren moments graded per live playbook (default: "
                             "layer_d.pipeline.NAREN_SAMPLE_PER_SCENARIO).")
    parser.add_argument("--report-only", action="store_true",
                        help="zero spend: rebuild move_performance from stored events "
                             "and print the coaching reports. No grading, no embedding.")
    parser.add_argument("--hostaddr", default="",
                        help="Neon DNS workaround: literal IP for the pooler host, "
                             "appended as hostaddr= while keeping host in the URL "
                             "(Neon routes by TLS SNI and binds SCRAM to the "
                             "hostname). Same flag as ops/ship_union_taxonomy.py; "
                             "18.138.49.39 is the value the 08-19 ships used.")
    parser.add_argument("--naren-only", action="store_true",
                        help="run ONLY the benchmark pass (Naren's routed kb_pairs "
                             "through the grader; the C3 measurement). Needs no client "
                             "roster and no CSM transcripts. Chat spend ~= "
                             "ceil(sample/6) requests per live playbook per k_run on "
                             "the checks arm.")
    parser.add_argument("--scenarios", default="",
                        help="naren-only: comma-separated scenario_keys to restrict "
                             "the benchmark to (e.g. after specific playbooks were "
                             "remade). Validated against the live set so a typo fails "
                             "instead of silently benchmarking nothing.")
    args = parser.parse_args()

    print("\n=== Layer D (redesign) Batch Runner ===")
    config = load_config()

    from ego_trap import csm_registry  # noqa: E402  (heavy import chain)
    from layer_d import pipeline  # noqa: E402

    mapping_path = _RECORDINGS / "mapping.csv"
    if not mapping_path.exists():
        print(f"ERROR: No mapping.csv found at {mapping_path}")
        sys.exit(1)
    mapping = csm_registry.load_mapping(mapping_path)

    url = config.database_url
    if args.hostaddr and "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + f"hostaddr={args.hostaddr}"
        print(f"[dns] hostaddr={args.hostaddr} (host kept in the URL for SNI/SCRAM)")
    conn = storage.get_connection(url)
    try:
        if args.report_only:
            storage.refresh_move_performance(conn)
            names = {cid: name for cid, name in mapping.values()}
            print(pipeline.build_reports(conn, names))
            return

        if args.naren_only:
            sample = (args.naren_sample if args.naren_sample is not None
                      else pipeline.NAREN_SAMPLE_PER_SCENARIO)
            live_keys = sorted(p["scenario_key"]
                               for p in storage.get_playbooks(conn, "live"))
            if not live_keys:
                print("ERROR: no live playbooks in the DB; nothing to benchmark.")
                sys.exit(1)
            only = None
            if args.scenarios:
                only = {s.strip() for s in args.scenarios.split(",") if s.strip()}
                missing = only - set(live_keys)
                if missing:
                    print(f"ERROR: --scenarios names {len(missing)} key(s) with no "
                          f"live playbook: {sorted(missing)}")
                    sys.exit(1)
            selected = sorted(only) if only else live_keys
            # run_id from what is actually scored (the selection + sample size), same
            # select-first-then-derive rule as the transcript path: changing either
            # gets fresh checkpoints instead of silently reusing the old ones.
            run_id = hashlib.sha1(
                f"naren|{sample}|{'|'.join(selected)}".encode()).hexdigest()[:12]
            print(f"Naren benchmark only: {len(selected)} of {len(live_keys)} live "
                  f"playbook(s), sample {sample}/scenario; run_id {run_id}")
            checkpoint.init(run_id)
            out = pipeline.run_naren_benchmark(
                config, conn, chat=pipeline.gateway_chat(), run_id=run_id,
                sample=sample, only=only)
            rows = storage.refresh_move_performance(conn)
            print(f"\n=== NAREN BENCHMARK ===\n{json.dumps(out, indent=2)}")
            print(f"move_performance rows: {rows}")
            print("\nPer-check Naren rates (the C3 readout -- a low rate is a BAD "
                  "CHECK, not a gap):")
            from shared.tuning import get_tuning
            arm = get_tuning().layer_d.grader_arm
            for rid, cells in storage.get_move_rates(conn, "naren", arm).items():
                for c in cells:
                    rate = ((c["hits"] + 0.5 * c["partials"]) / c["attempts"]
                            if c["attempts"] else float("nan"))
                    print(f"  playbook {c['playbook_id']} {c['move_id']}: "
                          f"{c['hits']}h/{c['partials']}p/{c['attempts']}att "
                          f"rate={rate:.2f} unscored={c['unscored']}")
            if out["failed"]:
                sys.exit(2)
            return

        excluded = tuple(s.strip() for s in args.exclude.split(",") if s.strip())
        present = {p.stem for p in _RECORDINGS.glob("*.txt")}
        missing = set(excluded) - present
        if missing:
            print(f"ERROR: --exclude names {len(missing)} stem(s) not in "
                  f"csm_recordings/: {sorted(missing)}")
            sys.exit(1)

        stems = pipeline.select_stems(_RECORDINGS, mapping,
                                      limit=args.limit, exclude=excluded)
        if not stems:
            print(f"ERROR: no mapped transcripts selected in {_RECORDINGS}")
            sys.exit(1)
        run_id = hashlib.sha1("|".join(stems).encode()).hexdigest()[:12]
        print(f"Selected {len(stems)} transcript(s); run_id {run_id}")

        roster = None
        if _ROSTER.exists():
            roster = pipeline.load_client_roster(_ROSTER)
            print(f"Client roster: {len(roster)} verified speaker name(s)")
        elif not args.allow_unverified_speakers:
            print(f"ERROR: {_ROSTER} not found and --allow-unverified-speakers not set.")
            sys.exit(1)

        checkpoint.init(run_id)
        report = pipeline.run_layer_d_batch(
            config, conn,
            recordings_dir=_RECORDINGS, run_id=run_id,
            limit=args.limit, exclude=excluded,
            client_roster=roster,
            allow_unverified_speakers=args.allow_unverified_speakers,
            naren_sample=(args.naren_sample
                          if args.naren_sample is not None
                          else pipeline.NAREN_SAMPLE_PER_SCENARIO),
        )
        print("\n=== RUN REPORT ===")
        print(json.dumps(report, indent=2, default=str))

        names = {cid: name for cid, name in mapping.values()}
        print("\n=== COACHING REPORTS ===")
        print(pipeline.build_reports(conn, names))

        if report["failed"] or report["naren"]["failed"]:
            print("\nSOME ITEMS FAILED AND WERE NOT CHECKPOINTED -- re-run to retry them.")
            sys.exit(2)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
