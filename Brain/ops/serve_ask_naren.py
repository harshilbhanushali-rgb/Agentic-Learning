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

from ask_naren import (citations, rendering, responding, retrieval,  # noqa: E402
                       service, vector_store)
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
    playbooks_by_scenario: dict[str, dict] = {}
    try:
        pairs = retrieval.load_coachable_pairs(conn)
        if PLAYBOOK_AUGMENTED:
            moves_by_scenario = _load_key_moves(conn, pairs)
        playbooks_by_scenario = _load_playbooks(conn, pairs)
        coachable_scenarios = _load_coachable_scenarios(conn)
        following_by_pair = _load_call_adjacency(conn, pairs)
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
    return (pool, moves_by_scenario, playbooks_by_scenario,
            coachable_scenarios, following_by_pair)


def _load_coachable_scenarios(conn) -> list[dict]:
    """The Layer A rows `discovery` and `frequency` render (issue #19).

    COACHABLE ONLY, and filtered through `retrieval.coachable_scenario_keys` rather than by
    reading `is_coachable` here -- that function delegates to `shared.relative_match`, which
    Brain calls the one definition of "this scenario is a sink". A second definition that
    agrees today is the latent bug `retrieval.py` warns about, and a list a CSM reads of
    what the tool covers is a poor place to discover one.
    """
    scenarios = storage.get_scenarios(conn)
    coachable = set(retrieval.coachable_scenario_keys(scenarios))
    rows = [s for s in scenarios if s["scenario_key"] in coachable]
    print(f"[layer-a] {len(rows)} coachable scenarios loaded for discovery/frequency",
          flush=True)
    return rows


def _load_call_adjacency(conn, pairs: list[dict]) -> dict[int, list[dict]]:
    """`pair_id` -> the exchanges that came AFTER it in the same call (issue #20).

    Built once at startup because the service holds no database handle while answering, and
    "how did that conversation continue" is a question about a row nobody retrieved.

    NOT FILTERED TO COACHABLE. The next thing said is frequently a logistics or backchannel
    turn Layer A sinks, and skipping those would silently present a LATER exchange as the
    adjacent one -- "the next thing we happen to cover" wearing the label "what happened
    next". `storage.get_call_pairs` returns everything for exactly this reason.

    WHAT THIS ACTUALLY HOLDS, because the obvious reading is wrong. `NEXT_EXCHANGES` bounds
    the LENGTH of each list, not what stays resident: the slices hold REFERENCES, so every
    row that is anyone's successor is retained -- which is nearly the whole `kb_pairs`
    corpus, its text included, alongside the pool's own copy of the coachable rows. ADR 0008
    banked "the process holds NO vectors (79.8 MB -> 0)", so a second corpus arriving quietly
    through the back door is exactly the thing worth stating rather than glossing. Measured
    at startup and printed below.

    Keys are restricted to POOL pairs. Only a pool pair can be retrieved, so only a pool
    pair can ever be the subject of "what happened next" -- an entry for anything else is a
    lookup nothing will perform.
    """
    pool_ids = {p["pair_id"] for p in pairs}
    following: dict[int, list[dict]] = {}
    by_call: dict[str, list[dict]] = {}
    for row in storage.get_call_pairs(conn):
        by_call.setdefault(row["call_filename"], []).append(row)
    for rows in by_call.values():
        # get_call_pairs already orders by (filename, turn_index); this only guards a caller
        # that changes that ordering, since adjacency read out of order is silently wrong.
        rows.sort(key=lambda r: r["turn_index"])
        for i, row in enumerate(rows):
            if row["pair_id"] not in pool_ids:
                continue
            nxt = rows[i + 1:i + 1 + rendering.NEXT_EXCHANGES]
            if nxt:
                following[row["pair_id"]] = nxt
    # Counted by identity, because the same row is the successor of at most a couple of
    # others and double-counting it would overstate what is resident.
    retained = {id(r): r for rows in following.values() for r in rows}
    held_mb = sum(len(r["trigger_text"] or "") + len(r["response_text"] or "")
                  for r in retained.values()) / 1_000_000
    print(f"[adjacency] {len(following)} pool exchanges have a following turn, across "
          f"{len(by_call)} calls; {len(retained)} rows retained, ~{held_mb:.1f} MB of text",
          flush=True)
    return following


def _load_playbooks(conn, pairs: list[dict]) -> dict[str, dict]:
    """`scenario_key` -> the LIVE playbook document, for the scenarios in the pool (#17).

    READ IN THE SAME CONNECTION WINDOW AS THE POOL, and for the same reason: the service
    holds no database handle while answering, so a playbook cannot be fetched per request.
    That is why `responding.respond` takes a `playbook_for` function rather than looking one
    up itself -- the same shape as `moves_for` and `label_for`.

    `status='live'` is `storage.get_playbook_for_scenario`'s default and is the guard that
    matters: the placebo twins and the UNRESOLVED r1 trial documents sit in this same table
    and are indistinguishable from production content without it. Serving a placebo to a CSM
    is exactly what that filter prevents, so this calls the function rather than writing its
    own SELECT.

    A scenario with no live playbook is simply absent, and the procedure path falls back to
    the Layer B answer for it -- the ordinary case for contract_and_legal_review, 1 of 34.
    """
    playbooks: dict[str, dict] = {}
    missing = []
    for key in sorted({p["scenario_key"] for p in pairs}):
        row = storage.get_playbook_for_scenario(conn, key)
        if (row or {}).get("playbook"):
            # THE WHOLE ROW, not just row["playbook"]. `n_evidence` is a sibling of the
            # document rather than a field inside it, and `play_confidence` (issue #18) is
            # exactly the question "how much evidence does this play rest on" -- storing only
            # the document silently drops the one number that intent exists to report.
            playbooks[key] = row
        else:
            missing.append(key)
    print(f"[playbook] {len(playbooks)} scenarios have a live playbook, {len(missing)} do "
          f"not and will answer from Layer B instead", flush=True)
    if missing:
        print(f"[playbook] no live playbook: {', '.join(missing)}", flush=True)
    return playbooks


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
    sample = random.sample(pairs, min(COVERAGE_SAMPLE, len(pairs)))
    fatal, stale = store.unretrievable(sample)
    if stale:
        print(f"[vectors] WARNING: {len(stale)} of {len(sample)} sampled pairs are filed "
              f"under a different scenario_key in the index than in Postgres, but remain "
              f"searchable (e.g. {stale[0][0]}: {stale[0][1]}). Re-ship the trigger vectors "
              f"to resync.", flush=True)
    if fatal:
        detail = "; ".join(f"{pair_id} ({reason})" for pair_id, reason in fatal[:3])
        raise SystemExit(
            f"ERROR: {len(fatal)} of {len(sample)} sampled coachable kb_pairs CANNOT be "
            f"retrieved from {VECTOR_INDEX_NAME} -- {detail}. Those exchanges would be "
            f"invisible to every situation, so this refuses to serve rather than degrade "
            f"silently. Re-ship the trigger vectors (ops/ship_layer_b.py --vectors "
            f"triggers), then verify with ops/check_vector_coverage.py.")
    print(f"[vectors] coverage guard: {len(sample)}/{len(sample)} sampled pairs present "
          f"and admitted by the scenario filter", flush=True)


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

    (pool, moves_by_scenario, playbooks_by_scenario, coachable_scenarios,
     following_by_pair) = build_pool(args.hostaddr or None)
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
                thread=thread, label_for=label_for, moves_for=moves_for,
                playbook_for=playbooks_by_scenario.get,
                scenarios_for=lambda: coachable_scenarios,
                following_for=lambda pair_id: following_by_pair.get(pair_id, []))

        if args.ask:
            # One message, no thread. `--ask` is a single-shot check of the whole path.
            print(json.dumps(answerer(args.ask), indent=2))
            return 0
        service.serve(answerer, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
