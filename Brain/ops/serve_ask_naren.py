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
import asyncio
import json
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ask_naren import (api, citations, rendering, responding, retrieval,  # noqa: E402
                       vector_store)
from ask_naren.api import admission                    # noqa: E402
from config import load_config                        # noqa: E402
from preprocessing import embedder                    # noqa: E402
from shared import storage                            # noqa: E402
from shared.gateway import (AsyncGatewayClient, EMBED_DIMENSIONS,  # noqa: E402
                            EMBED_MODEL)
from shared.tuning import get_tuning                 # noqa: E402

# No pinned IP since the 2026-10-10 Brain adoption: Neon DNS resolves again (verified for both
# databases), and the old pin 18.138.49.39 is the PRE-rebuild database's address -- pinned
# against the new host it fails channel binding. If the resolver ever refuses *.neon.tech
# again, pass --hostaddr <an IP of the live host>; `host` stays in the URL for SNI/SCRAM.
DEFAULT_HOSTADDR = ""

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

# ISSUE #25's THREE SWITCHES. Code edits for the reason PLAYBOOK_AUGMENTED is one. Separate
# so a measurement can tell which one moved an answer; turning one off restores exactly the
# pre-#25 behaviour of its part.
#
# ALL ON SINCE 2026-10-10, on the measurement in ask-naren/audit/README.md ("Issue #25"):
# intake sets unchanged (threaded 10/11, carried 42/44, zero false carries), #49's six
# questions 6/18 -> 12/18 right, the 36-situation audit rescued 4 right for 1 wrong, and the
# live conversation test was 6 turns better and 1 worse with no timeouts. Known cost: a
# question the corpus cannot answer can now get a wrong answer instead of a decline.
#
# SEARCH_FROM_CONVERSATION: a message that leans on the conversation ("the ats one") is
# searched with a search intake writes from the CSM's own earlier words, and a follow-up the
# carried exchange cannot answer is searched instead of declined. It relaxes ADR 0006 under
# a check (responding._guarded 7).
#
# ANSWER_SEES_CONVERSATION: the answer model sees the conversation and the whole message,
# not only the words searched on.
#
# WIDE_RETRY: a "no close match" from the nearest exchange is retried once with the nearest
# 20, when at least 15s of the deadline are left, and abandoned for the first decline if it
# is still running 2s before the deadline. Never touches a first answer. OFF since
# ANSWER_SHORTLIST_K below shows 20 from the start, and a retry can add nothing then.
#
# ANSWER_SHORTLIST_K: how many of the nearest exchanges the answer model is shown at once.
# 20 SINCE 2026-10-10, ON THE REBUILT BRAIN. Measured on 36 questions in one blind read
# (ask-naren/audit/README.md, "The rebuilt Brain"): top 20 from the start 23 right, 1 wrong,
# 12 declined, median 11.5s, ~36 calls -- against nearest 1 then 20 on a decline, 25 right,
# 1 wrong, 10 declined, median 17.2s with one answer at 30.0s, ~60 calls. Equal on rightness
# (the reader alone moved 3 between reads), faster, no second generation near the deadline.
# On this Brain only 6 of 24 answers came from the nearest exchange, and 8 from ranks 11-20.
# 1 restores the nearest-only first attempt (then turn WIDE_RETRY back on).
SEARCH_FROM_CONVERSATION = True
ANSWER_SEES_CONVERSATION = True
WIDE_RETRY = False
ANSWER_SHORTLIST_K = 20

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
# ADOPTED 2026-10-10: the rebuilt Brain's index. It moves TOGETHER with DATABASE_URL -- vector
# ids are the kb_pairs serials of the database that shipped them. `narens-brain-3072` is the
# pre-rebuild Brain's (rollback: both back together).
VECTOR_INDEX_NAME = "narens-brain-rebuild-3072"

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


async def build_pool(hostaddr: str | None):
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
    pool = retrieval.RetrievalPool(
        pairs, store=await _build_store(config, pairs, scenario_keys))
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


async def _build_store(config, pairs: list[dict], scenario_keys: list[str]):
    """The store the pool ranks with, per the VECTOR_STORE switch above.

    THE ROLLBACK PATH IS THE ONE PLACE IN THIS PROCESS THE SYNCHRONOUS GATEWAY CLIENT IS
    STILL USED. It embeds the pool HERE, at startup, before anything is served and before
    the async client makes a single call -- and it is also the path that still WANTS the
    embed cache, because 6,496 triggers is exactly the corpus-sized work the cache exists
    for.

    That is permitted by the SEQUENTIAL-use carve-out in Brain/docs/GOTCHAS.md, which is
    where the rule and its one residual hazard live: the two limiters do not share a rate
    WINDOW, so on a cold-cache rollback start the first CSM questions can land in the same
    window as the tail of those startup embeddings. Read that entry before relying on this.
    """
    if VECTOR_STORE == "memory":
        print(f"[vectors] ROLLBACK PATH: embedding {len(pairs)} triggers in-process "
              f"(warm gateway cache -> mostly free)...", flush=True)
        vectors = embedder.embed_query_matrix([p["trigger_text"] for p in pairs])
        return vector_store.InMemoryTriggerStore([p["pair_id"] for p in pairs], vectors)
    if VECTOR_STORE != "pinecone":
        raise SystemExit(f"ERROR: unknown VECTOR_STORE {VECTOR_STORE!r} -- "
                         f"expected 'pinecone' or 'memory'.")
    store = await vector_store.PineconeTriggerStore.open(
        config.pinecone_api_key, VECTOR_INDEX_NAME, scenario_keys=scenario_keys)
    print(f"[vectors] {VECTOR_INDEX_NAME}, restricted to {len(scenario_keys)} coachable "
          f"scenarios -- nothing embedded, no vectors held", flush=True)
    try:
        await _assert_store_covers_pool(store, pairs)
    except BaseException:
        # Closed HERE, by the function that opened it. The guard exits the process on a
        # fatal coverage gap, so `_build_store` never returns and `_run`'s `finally` has no
        # pool to close -- the operator would get "Unclosed client session" noise stacked on
        # top of the multi-line coverage error the guard exists to make readable.
        # BaseException, not Exception: SystemExit is the case that actually happens.
        await store.aclose()
        raise
    return store


async def _assert_store_covers_pool(store, pairs: list[dict]) -> None:
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
    fatal, stale = await store.unretrievable(sample)
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
    """The two filename resolvers, sharing ONE account index read once at startup.

    `label_for` answers "what should this citation read as" and always returns something.
    `account_for` answers "which client was this" and returns None where the recorded data
    does not say -- issue #22 needs that distinction, because its whole output is a list of
    client names and a wrong one is worse than an opaque one.

    ONE INDEX, TWO READERS. Building it twice would read the sidecar directories twice for
    an identical result, and would let the two functions disagree about a call if the
    directories changed between them.
    """
    root = Path(__file__).resolve().parent.parent
    index = citations.build_account_index(root / d for d in SIDECAR_DIRS)
    if index:
        print(f"[citations] {len(index)} UUID-named calls resolved to an account from "
              f"recorded participants", flush=True)
    else:
        # Criterion 3 of issue #22, and the state of any machine without the (gitignored,
        # machine-local) recordings directories: every UUID call cites its raw filename and
        # names no account. Thinner, not broken.
        print("[citations] no participant sidecars found -- UUID-named calls will cite "
              "their raw filename and name no account", flush=True)
    return (lambda filename: citations.resolve_label(filename, index),
            lambda filename: citations.account_for(filename, index))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=api.DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=api.DEFAULT_PORT)
    ap.add_argument("--ask", help="answer one situation, print JSON, exit")
    ap.add_argument("--hostaddr", default=DEFAULT_HOSTADDR,
                    help="IP for the Neon host; the system resolver refuses *.neon.tech. "
                         "Pass '' to disable.")
    args = ap.parse_args()

    # *** ONE EVENT LOOP FOR THE WHOLE PROCESS, and it is not a style choice. ***
    #
    # `shared/gateway.py`'s admission gate is keyed on the running loop, because an asyncio
    # primitive raises if awaited from a loop other than the one it bound to. A process that
    # wrapped each request in its own `asyncio.run` would therefore get a FRESH limiter and
    # semaphore every time -- so the per-API-key bound would silently become per-request,
    # i.e. unbounded, and look perfectly healthy until the gateway started rejecting.
    #
    # ONE `asyncio.run` around the whole of main is what guarantees that, and issue #31 is
    # what made it possible: with an ASGI server, uvicorn runs INSIDE our loop instead of
    # blocking it, so there is no longer a blocking `serve_forever` to work around and no
    # `run_until_complete`-per-request bridge to maintain. That bridge existed for exactly
    # one ticket and is now deleted.
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        # Uvicorn re-raises SIGINT after its graceful shutdown has completed, so by here the
        # server has stopped and `on_shutdown` has closed everything. Reporting that as a
        # traceback and exit 130 would make an ordinary Ctrl-C look like a crash to whatever
        # supervises this process. The stdlib server used to catch this itself.
        return 0


def _embed_query(gateway):
    """The request path's embedder: straight to the async gateway, past `preprocessing`.

    *** THIS IS WHAT REMOVES THE BLOCKER ADR 0003 WAS BUILT AROUND, and not the way that
    ADR predicted. *** It named the embed cache's thread affinity as the thing to fix --
    `shared/embed_cache.py` opens SQLite without `check_same_thread=False`, so a second
    request thread touching that connection raises outright.

    It does not need fixing, because on this path it does not need to EXIST. Routing around
    `preprocessing/embedder.py` means `_cache_for_backend()` is never called, so the
    connection that raises is never created -- there is no thread-bound object in the
    request path at all. Nothing in `shared/` is edited and Brain's pipeline is untouched.

    And nothing is lost by skipping the cache: a live CSM situation is a NOVEL STRING and
    therefore a guaranteed miss. The cache would pay a SQLite write for a hit that never
    comes. It stays enabled everywhere it earns its keep -- the pipeline, and this file's
    own `memory` rollback path, which embeds 6,496 triggers at startup.

    Returns a numpy matrix because that is what every caller of `embed_query` already
    expects, so this substitution is invisible above it.
    """
    # Model and width come from tuning.yaml, exactly as preprocessing/embedder does, rather
    # than from shared.gateway's defaults. They agree today. They must not be ALLOWED to
    # disagree: a change to `embedding.gemini_model` re-embeds the corpus and re-ships
    # Pinecone, and a request path still querying with the old model would compare vectors
    # across two embedding spaces at the same width -- which Brain/CLAUDE.md calls the
    # biggest live hazard in this project, and which raises no error at all.
    cfg = get_tuning().embedding
    model = cfg.gemini_model or EMBED_MODEL
    dimensions = cfg.gemini_dimensions or EMBED_DIMENSIONS

    async def embed(texts: list[str]):
        return np.asarray(
            await gateway.embed(list(texts), model=model, dimensions=dimensions),
            dtype=np.float32)
    return embed


async def _run(args) -> int:
    # `pool` and `gateway` are bound before the try so the finally can close whatever got
    # as far as existing -- a failure part-way through startup must not leave an open
    # Pinecone session for `loop.close()` to tear down underneath. The coverage guard's own
    # exit is handled where the store is opened, in `_build_store`, because on that path
    # `build_pool` never returns and there is no pool here to close.
    pool = gateway = None
    closed = False

    async def _close() -> None:
        """Release the gateway client and the pool's store. Safe to call twice.

        Called from the server's lifespan shutdown AND from the `finally` below, because
        neither covers every exit on its own -- see the note at the `serve` call. Closing an
        httpx client twice is harmless, but the Pinecone session is not, hence the flag.
        """
        nonlocal closed
        if closed:
            return
        closed = True
        # An unclosed AsyncClient leaks its connection pool and warns on exit. The pool
        # closes its own store -- see RetrievalPool.aclose.
        if gateway is not None:
            await gateway.aclose()
        if pool is not None:
            await pool.aclose()

    try:
        (pool, moves_by_scenario, playbooks_by_scenario, coachable_scenarios,
         following_by_pair) = await build_pool(args.hostaddr or None)
        label_for, account_for = build_label_resolver()
        # None unless the constant above was edited. answer_situation treats None as
        # pairs-only, so the shipped path never touches the playbook code at all.
        moves_for = moves_by_scenario.get if PLAYBOOK_AUGMENTED else None

        gateway = AsyncGatewayClient()
        embed_query = _embed_query(gateway)

        async def answer(situation: str, thread=()) -> dict:
            # Through responding.respond, not answer_situation directly (issue #14): intake
            # runs first and decides whether this is answerable as written, needs the
            # client's actual words, or is out of scope. answer_situation is unchanged and
            # is what the reply_to_client path calls.
            #
            # `thread` is the conversation the caller replayed (issue #15). Nothing is
            # stored here between requests, which is the point -- see the module docstring.
            return await responding.respond(
                situation, pool, gateway, embed_query=embed_query,
                thread=thread, label_for=label_for, moves_for=moves_for,
                playbook_for=playbooks_by_scenario.get,
                scenarios_for=lambda: coachable_scenarios,
                following_for=lambda pair_id: following_by_pair.get(pair_id, []),
                account_for=account_for,
                search_from_conversation=SEARCH_FROM_CONVERSATION,
                answer_sees_conversation=ANSWER_SEES_CONVERSATION,
                wide_retry=WIDE_RETRY, k=ANSWER_SHORTLIST_K,
                time_left=admission.seconds_left)

        if args.ask:
            # One message, no thread. `--ask` is a single-shot check of the whole path.
            print(json.dumps(await answer(args.ask, ()), indent=2))
            return 0

        # `ready` is trivially true by the time we get here -- the pool is loaded and the
        # coverage guard has passed, or this line was never reached. It is wired anyway
        # because the endpoint's value is in a state the process can report WHILE
        # listening, which is what issue #32's queue bound will need; leaving it
        # unconnected now would mean discovering the seam does not reach the answerer then.
        #
        # `on_shutdown` IS HOW THE TEARDOWN ACTUALLY RUNS ON Ctrl-C, and the `finally` below
        # is not enough on its own. Measured: `asyncio.run` installs a SIGINT handler that
        # cancels this task, uvicorn re-raises the signal into it, and by the time the
        # `finally` runs the task is already cancelled -- so its first `await ...aclose()`
        # raises CancelledError and the client and Pinecone session leak. Uvicorn runs the
        # lifespan shutdown as part of its GRACEFUL stop, before any of that. The `finally`
        # still matters for every other exit: `--ask`, a startup failure, a bind failure.
        await api.serve(answer, host=args.host, port=args.port, ready=lambda: True,
                            on_shutdown=_close)
    finally:
        # Covers `--ask`, a startup failure and a bind failure. On Ctrl-C the lifespan
        # shutdown has already run `_close`, and this task is cancelled by then -- which is
        # exactly why the teardown does not live here alone.
        await _close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
