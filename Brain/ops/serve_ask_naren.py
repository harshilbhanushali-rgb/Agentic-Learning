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

  * The coachable pool is loaded and deduped ONCE here at startup, not per request. Brain's
    pipeline runs are manual batches, so the pool only changes when someone re-runs a layer
    -- restart the service to pick that up.

  * It is NOT embedded. Every vector operation runs in Pinecone (ADR 0008), so startup is a
    Postgres read plus a coverage check, and this process holds NO VECTORS (79.8 MB -> 0).
    Startup is dominated by the Postgres read in both paths, so the gain is not wall-clock
    on a box with a warm local embed cache -- it is that a FRESH host no longer needs 6,496
    gateway embedding requests before it can serve. See ADR 0008.

  * Nothing is written to tuning.yaml, Pinecone, or any Brain table. The Pinecone index is
    QUERIED and its record ids are fetched; there is no upsert and no index creation here.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ask_naren import (citations, responding, retrieval, service,  # noqa: E402
                       vector_store)
from config import load_config                        # noqa: E402
from preprocessing import embedder                    # noqa: E402
from shared import storage                            # noqa: E402
from shared.gateway import GatewayClient              # noqa: E402

# The local resolver refuses *.neon.tech; `host` stays in the URL for TLS SNI/SCRAM and
# `hostaddr` only tells the driver which IP to open the socket on. Same default and same
# reason as ops/ship_union_taxonomy.py and the Ask Naren prototype.
DEFAULT_HOSTADDR = "18.138.49.39"

# Where the recorded participant sidecars live (`<stem>.speakers.json`, beside each
# transcript). They are the ONLY source that names the account for the ~31% of citable pairs
# whose call is an opaque UUID -- there is no meeting subject anywhere in the corpus. Read
# ONCE here at startup, the same lifetime as the pool; nothing is read while answering.
#
# These directories are gitignored and machine-local, so their absence must DEGRADE rather
# than break: without them every UUID call cites its raw filename, exactly as before issue #4.
SIDECAR_DIRS = ("recordings", "csm_recordings", "recordings_pull_keep", "recordings_pull_4yr")

# THE PLAYBOOK SWITCH (issue #5, ADR 0001). OFF, and flipping it is a CODE EDIT here --
# deliberately not an env var, a CLI flag or a request field:
#
#   * a request field would let a CSM (or anything calling the endpoint) select an
#     unevaluated prompt variant, which is what the ticket forbids;
#   * an env var or CLI flag can be set by accident on a restart, and this variant has
#     MEASURED no lift (ADR 0001: paired delta -0.005 to -0.007, roughly 12x smaller than
#     the effect the instrument can resolve). Something with no measured benefit should not
#     be one typo away from serving CSMs.
#
# It is kept rather than deleted because Layer C's criterion quality is still moving, and a
# recalibration should be able to re-measure this without rebuilding the variant. Both
# prompts are byte-identical to the prototype ADR 0001 actually measured, so a re-measure
# compares against the recorded number instead of a drifted prompt.
PLAYBOOK_AUGMENTED = False

# THE VECTOR STORE, and the rollback switch for ADR 0008. "pinecone" ships; "memory"
# restores the pre-0008 behaviour exactly -- embed the whole pool at startup and search a
# numpy matrix in-process.
#
# A CODE EDIT rather than an env var or a CLI flag, for the same reason PLAYBOOK_AUGMENTED
# is one: an env var can be set by accident on a restart, and which store is live decides
# whether the process needs Pinecone reachable to answer at all. That is not a thing to
# discover from a shell history.
VECTOR_STORE = "pinecone"

# The 3072-dim index, and NOT config.pinecone_index_name -- which is `narens-brain`, the
# 768-dim bge-era index that .env still points at and that main.py/ops/run_ego_trap.py
# still call init_index on. Ask Naren's pool is gemini-embedding-2 at 3072, so reading the
# 768 index would be a dimension error at best and a silently truncated match at worst.
# Same constant, same value, as ops/ship_layer_b.py's INDEX_3072 -- the job that populates
# it. Pinecone dimension is immutable, so this is a name to keep in step, not a config knob.
VECTOR_INDEX_NAME = "narens-brain-3072"

# How many pool identifiers the startup guard checks against the store. 1,000 of 6,496 --
# about 15% of the pool -- costs ~1.7s because the check transfers no vectors. The sample is
# random per start, so repeated restarts widen the coverage actually checked, and
# ops/check_vector_coverage.py does the full 6,496 after a layer ships.
COVERAGE_SAMPLE = 1000


def _connect_read_only(database_url: str, hostaddr: str | None):
    """A connection Postgres refuses to write through -- lifted from
    calibration/probe_retrieval_gate.py's `_connect_read_only`.

    close() is wrapped to RESET the session setting first. Neon's pooled
    endpoint reuses the same backend server connection across unrelated
    clients (PgBouncer transaction pooling) -- SET SESSION here, left in
    place, silently poisons whichever client gets this backend NEXT.
    Measured 2026-08-26: this is what made Brain's Layer D regrade see the
    whole database as read-only, repeatedly, with no write ever attempted on
    THIS connection's own session -- confirmed by reproducing the leak
    directly and then flushing the poisoned pool back to 'off'.
    """
    if hostaddr and "hostaddr=" not in database_url:
        database_url += ("&" if "?" in database_url else "?") + f"hostaddr={hostaddr}"
        print(f"[dns] hostaddr={hostaddr} (host kept in the URL for SNI/SCRAM)")
    conn = storage.get_connection(database_url)
    conn.execute("SET SESSION default_transaction_read_only = on")
    ro = conn.execute("SELECT current_setting('default_transaction_read_only')").fetchone()[0]
    if ro != "on":
        raise RuntimeError(f"read-only enforcement failed: setting is {ro!r}")
    _real_close = conn.close
    def _close_and_reset():
        try:
            conn.execute("SET SESSION default_transaction_read_only = off")
        except Exception:
            pass  # best-effort: the connection may already be broken/closed
        _real_close()
    conn.close = _close_and_reset
    return conn


def build_pool(hostaddr: str | None):
    """The pool, and (only when the playbook switch is on) the key moves per scenario.

    Both are read in ONE connection window, which is then closed before the first request is
    served -- the property this whole module is built around. A playbook cannot be fetched
    per request because there is no database handle to fetch it with, which is why
    answer_situation takes a `moves_for` function rather than looking one up itself.
    """
    config = load_config()
    conn = _connect_read_only(config.database_url, hostaddr)
    moves_by_scenario: dict[str, list] = {}
    try:
        pairs = retrieval.load_coachable_pairs(conn)
        if PLAYBOOK_AUGMENTED:
            moves_by_scenario = _load_key_moves(conn, pairs)
    finally:
        conn.close()
    if not pairs:
        raise SystemExit("ERROR: no coachable kb_pairs found -- refusing to serve a tool "
                         "that can only decline.")
    print(f"[pool] {len(pairs)} coachable kb_pairs after content dedup", flush=True)
    scenario_keys = sorted({p["scenario_key"] for p in pairs})
    pool = retrieval.RetrievalPool(pairs, store=_build_store(config, pairs, scenario_keys))
    print(f"[pool] ready: {len(pool)} pairs across {len(scenario_keys)} coachable scenarios",
          flush=True)
    return pool, moves_by_scenario


def _build_store(config, pairs: list[dict], scenario_keys: list[str]):
    """The store the pool ranks with, per the VECTOR_STORE switch above."""
    if VECTOR_STORE == "memory":
        print(f"[vectors] ROLLBACK PATH: embedding {len(pairs)} triggers in-process "
              f"(warm gateway cache -> mostly free)...", flush=True)
        vectors = embedder.embed_query_matrix([p["trigger_text"] for p in pairs])
        return vector_store.InMemoryTriggerStore([p["pair_id"] for p in pairs], vectors)
    if VECTOR_STORE != "pinecone":
        raise SystemExit(f"ERROR: unknown VECTOR_STORE {VECTOR_STORE!r} -- "
                         f"expected 'pinecone' or 'memory'.")
    store = vector_store.PineconeTriggerStore(
        config.pinecone_api_key, VECTOR_INDEX_NAME, scenario_keys)
    print(f"[vectors] {VECTOR_INDEX_NAME}, restricted to {len(scenario_keys)} coachable "
          f"scenarios -- nothing embedded, no vectors held", flush=True)
    _assert_store_covers_pool(store, pairs)
    return store


def _assert_store_covers_pool(store, pairs: list[dict]) -> None:
    """Refuse to serve if the index is missing pool pairs. See ADR 0008.

    The failure this prevents is silent, which is why it is worth a second of startup: a
    pipeline run that writes kb_pairs to Postgres before upserting their trigger vectors
    leaves those pairs in the pool and absent from the ranking, so they can NEVER be
    retrieved. Nothing errors, no log line appears, and a CSM simply never sees those
    exchanges -- it would surface as an unexplained quality complaint months later.

    Sampled rather than exhaustive, and the sample is random per start so repeated restarts
    widen the coverage actually checked. The full check is ops/check_vector_coverage.py, to
    be run after shipping a layer.
    """
    ids = [p["pair_id"] for p in pairs]
    sample = random.sample(ids, min(COVERAGE_SAMPLE, len(ids)))
    missing = store.covers(sample)
    if missing:
        raise SystemExit(
            f"ERROR: {len(missing)} of {len(sample)} sampled coachable kb_pairs have no "
            f"trigger vector in {VECTOR_INDEX_NAME} (e.g. {missing[:5]}). Those pairs could "
            f"never be retrieved, so this refuses to serve rather than degrade silently. "
            f"Ship the trigger vectors (ops/ship_layer_b.py --vectors triggers), then "
            f"verify with ops/check_vector_coverage.py.")
    print(f"[vectors] coverage guard: {len(sample)}/{len(sample)} sampled pairs present",
          flush=True)


def _load_key_moves(conn, pairs: list[dict]) -> dict[str, list]:
    """`scenario_key` -> live playbook `key_moves`, for the scenarios in the pool.

    Reads through storage.get_playbook_for_scenario, whose status='live' default is the
    guard that matters: the placebo twins and the UNRESOLVED r1 trial documents share this
    table and are indistinguishable from production content without it. A scenario with no
    live playbook is simply absent, and answering degrades to pairs-only for it -- which is
    the ordinary case for contract_and_legal_review, the 1 of 34 coachable scenarios whose
    playbook snap collapsed below the move floor.
    """
    moves: dict[str, list] = {}
    missing = []
    for key in sorted({p["scenario_key"] for p in pairs}):
        playbook = storage.get_playbook_for_scenario(conn, key)
        found = (playbook or {}).get("playbook", {}).get("key_moves")
        if found:
            moves[key] = found
        else:
            missing.append(key)
    print(f"[playbook] AUGMENTED PROMPT IS ON -- {len(moves)} scenarios have live key "
          f"moves, {len(missing)} do not and will use the pairs-only prompt", flush=True)
    if missing:
        print(f"[playbook] no live playbook: {', '.join(missing)}", flush=True)
    return moves


def build_label_resolver():
    """The filename -> readable-citation function, with the account index baked in."""
    root = Path(__file__).resolve().parent.parent
    index = citations.build_account_index(root / d for d in SIDECAR_DIRS)
    if index:
        print(f"[citations] {len(index)} UUID-named calls resolved to an account from "
              f"recorded participants", flush=True)
    else:
        print("[citations] no participant sidecars found -- UUID-named calls will cite "
              "their raw filename", flush=True)
    return lambda filename: citations.resolve_label(filename, index)


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

    pool, moves_by_scenario = build_pool(args.hostaddr or None)
    label_for = build_label_resolver()
    # None unless the constant above was edited. answer_situation treats None as pairs-only,
    # so the shipped path never touches the playbook code at all.
    moves_for = moves_by_scenario.get if PLAYBOOK_AUGMENTED else None

    with GatewayClient() as gateway:
        def answerer(situation: str, thread=()) -> dict:
            # Through responding.respond, not answer_situation directly (issue #14): intake
            # runs first and decides whether this is answerable as written, needs the
            # client's actual words, or is out of scope. answer_situation is unchanged and
            # is what the reply_to_client path calls.
            #
            # `thread` is the conversation the caller replayed (issue #15). Nothing is
            # stored here between requests, which is the point -- see the module docstring.
            return responding.respond(
                situation, pool, gateway, embed_query=embedder.embed_query_matrix,
                thread=thread, label_for=label_for, moves_for=moves_for)

        if args.ask:
            # One message, no thread. `--ask` is a single-shot check of the whole path.
            print(json.dumps(answerer(args.ask), indent=2))
            return 0
        service.serve(answerer, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
