#!/usr/bin/env python3
"""Runs the Ask Naren service: a CSM's situation in, a grounded answer or a decline out.

Run from Brain/ with the venv active and the Joveo VPN up (generation and any novel
embedding go through the gateway):

    python ops/serve_ask_naren.py                          # serve on 127.0.0.1:8787
    python ops/serve_ask_naren.py --port 9000
    python ops/serve_ask_naren.py --ask "client says our cost per hire is way too high"

`--ask` answers one situation, prints the response as JSON and exits -- the cheapest way to
verify the whole path end to end without a browser or a frontend.

WHAT THIS PROCESS DOES AND DOES NOT TOUCH:

  * Postgres is read ONCE, through a connection Postgres itself refuses to write through,
    and that connection is CLOSED before the first request is served. The service holds no
    database handle at all while answering, which is a stronger guarantee than read-only:
    Ask Naren cannot write to Brain's pipeline because it is not connected to it. Matches
    CONTEXT-MAP.md's stated Ask Naren -> Brain relationship.

  * The coachable pool is loaded, deduped and embedded ONCE here at startup, not per
    request. Brain's pipeline runs are manual batches, so the pool only changes when
    someone re-runs a layer -- restart the service to pick that up.

  * Nothing is written to tuning.yaml, Pinecone, or any Brain table.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ask_naren import answering, retrieval, service   # noqa: E402
from config import load_config                        # noqa: E402
from preprocessing import embedder                    # noqa: E402
from shared import storage                            # noqa: E402
from shared.gateway import GatewayClient              # noqa: E402

# The local resolver refuses *.neon.tech; `host` stays in the URL for TLS SNI/SCRAM and
# `hostaddr` only tells the driver which IP to open the socket on. Same default and same
# reason as ops/ship_union_taxonomy.py and the Ask Naren prototype.
DEFAULT_HOSTADDR = "18.138.49.39"


def _connect_read_only(database_url: str, hostaddr: str | None):
    """A connection Postgres refuses to write through -- lifted from
    calibration/probe_retrieval_gate.py's `_connect_read_only`."""
    if hostaddr and "hostaddr=" not in database_url:
        database_url += ("&" if "?" in database_url else "?") + f"hostaddr={hostaddr}"
        print(f"[dns] hostaddr={hostaddr} (host kept in the URL for SNI/SCRAM)")
    conn = storage.get_connection(database_url)
    conn.execute("SET SESSION default_transaction_read_only = on")
    ro = conn.execute("SELECT current_setting('default_transaction_read_only')").fetchone()[0]
    if ro != "on":
        raise RuntimeError(f"read-only enforcement failed: setting is {ro!r}")
    return conn


def build_pool(hostaddr: str | None) -> retrieval.RetrievalPool:
    config = load_config()
    conn = _connect_read_only(config.database_url, hostaddr)
    try:
        pairs = retrieval.load_coachable_pairs(conn)
    finally:
        conn.close()
    if not pairs:
        raise SystemExit("ERROR: no coachable kb_pairs found -- refusing to serve a tool "
                         "that can only decline.")
    print(f"[pool] {len(pairs)} coachable kb_pairs after content dedup", flush=True)
    print(f"[pool] embedding {len(pairs)} triggers "
          f"(warm gateway cache -> mostly free)...", flush=True)
    vectors = embedder.embed_query_matrix([p["trigger_text"] for p in pairs])
    pool = retrieval.RetrievalPool(pairs, vectors)
    print(f"[pool] ready: {len(pool)} pairs across "
          f"{len({p['scenario_key'] for p in pairs})} coachable scenarios", flush=True)
    return pool


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=service.DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=service.DEFAULT_PORT)
    ap.add_argument("--ask", help="answer one situation, print JSON, exit")
    ap.add_argument("--hostaddr", default=DEFAULT_HOSTADDR,
                    help="IP for the Neon host; the system resolver refuses *.neon.tech. "
                         "Pass '' to disable.")
    args = ap.parse_args()

    pool = build_pool(args.hostaddr or None)

    with GatewayClient() as gateway:
        def answerer(situation: str) -> dict:
            return answering.answer_situation(
                situation, pool, gateway, embed_query=embedder.embed_query_matrix)

        if args.ask:
            print(json.dumps(answerer(args.ask), indent=2))
            return 0
        service.serve(answerer, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
