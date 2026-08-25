#!/usr/bin/env python3
"""SHIP LAYER B — route the union corpus against the live taxonomy and populate kb_pairs.

Handoff: Brain/HANDOFF_SHIP_LAYER_AB_2026-08-19.md
Runs AFTER ops/ship_union_taxonomy.py has loaded the 259 scenarios.

WHAT THIS DOES, in the order it does it
  1. route 12,444 pairs with PRODUCTION `assign_scenarios` over the gemini cache
  2. upsert every transcript into `calls`   (FK prerequisite — see TRAP 1)
  3. insert kb_pairs with the REAL DB scenario_id (see TRAP 2)
  4. upsert the TRIGGER vectors — all cached, free; Layer B is serviceable from here
  5. THE PACED TAIL: fetch the missing RESPONSE vectors and upsert them

*** THE ORDER IS DELIBERATE. *** The gateway caps `gemini-embedding-2` at 150 requests per
window per key (measured 2026-08-19: "Current limit: 150, Remaining: 0"), so the ~11.9k
response fetch is an ~85-MINUTE paced job. Routing consumes TRIGGER and SCENARIO vectors only,
so putting the fetch last means Layer B is live in ~10 minutes instead of ninety. The
intermediate state is serviceable, not broken: `query_triggers` reads the triggers namespace.

*** TRAP 1 — `calls` IS AN FK AND IT IS SHORT. *** `kb_pairs.call_id` references
`calls.call_id` ON DELETE NO ACTION. Measured 2026-08-19: `calls` held 416 rows against a
1,059-call union corpus, so ~640 calls were absent and two thirds of the pairs could not have
landed. Every call is upserted first, and the count is asserted before any pair is written.

*** TRAP 2 — THE ARTIFACT'S `scenario_id` IS NOT THE DATABASE'S. ***
`layer_bc_arms.scenario_map_from_rows` sets `scenario_id` to the artifact's ROW INDEX and says
so in its own docstring ("a synthetic index. Nothing here touches Postgres"). `scenarios.
scenario_id` is a SERIAL assigned at load time. Writing the synthetic value into
`kb_pairs.scenario_id` would attach pairs to whichever scenario happens to hold that serial —
plausible-looking and completely wrong. So the map is REBOUND to the live DB ids by
scenario_key before routing, and every key is asserted present.

WHY THE ROUTING RUNS THROUGH THE CACHE-ONLY SHIM. The taxonomy was clustered and adjudicated
in `gemini-embedding-2@3072`, and production still has `embedding.backend: local` (bge@768)
because the `gateway` backend does not exist yet — flipping it now would send fresh embeds to
Google AI Studio at ~1k/day. `install_embedder_shim` serves production's embedder from the
gateway cache and ABORTS on a miss, so this run is provably the same routing the trial
measured (G-R2: 47.3% new / 48.1% old sink) rather than a bge approximation of it.

Trigger vectors are 12,399/12,399 cached. Response vectors were 526/12,398 — the ~11.9k fetch
in step 5 is the last embedding debt on this corpus. `--vectors triggers` skips it entirely.

SAFETY: dry run is the DEFAULT; `--apply` is required. Neon's DNS block is handled with
hostaddr. **A BARE RE-RUN IS REFUSED once kb_pairs is non-empty** — use `--resume-vectors` when
the table is already correct and only Pinecone is unfinished (it reads each pair_id back by
(call_id, turn_index) and REFUSES on any missing pair or any routing drift), or `--replace` to
truncate and rebuild. `upsert_call` and the Pinecone upserts are idempotent by key.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe ops/ship_layer_b.py                 # dry run
    .\\ops\\run_visible.ps1 -Script ops/ship_layer_b.py -ScriptArgs '--apply'
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OLD_DIR = "recordings"
NEW_DIR = "recordings_pull_keep"
WIDTH = 3072
INDEX_3072 = "narens-brain-3072"
FETCH_CEILING = 15_000          # halt-and-ask above this; the measured need is ~11.9k


def connect(hostaddr: str | None):
    import psycopg
    from config import load_config

    url = load_config().database_url
    if not url:
        raise SystemExit("DATABASE_URL is not configured")
    if hostaddr and "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + f"hostaddr={hostaddr}"
    return psycopg.connect(url, connect_timeout=30)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--hostaddr", default="18.138.49.39")
    p.add_argument("--index", default=INDEX_3072)
    p.add_argument("--resume-vectors", action="store_true", dest="resume_vectors",
                   help="THE RESUME PATH. Skips the calls/kb_pairs writes entirely and only "
                        "does vector work, reading each pair_id back from the DB. Use this "
                        "when kb_pairs is already correct and only Pinecone is unfinished — "
                        "e.g. the paced response fetch died. Needs no --replace.")
    p.add_argument("--replace", action="store_true",
                   help="TRUNCATE kb_pairs before loading. Required for a re-run: without it "
                        "pairs this run does not produce would survive as stale orphans.")
    p.add_argument("--vectors", choices=("both", "triggers", "none"), default="both",
                   help="both = triggers (free) then the ~85min paced response fetch; "
                        "triggers = the namespace query_triggers reads, cache-only and free; "
                        "none = kb_pairs only")
    a = p.parse_args()

    from calibration.layer_bc_arms import (_load_cached, build_pairs, install_embedder_shim,
                                           parse_corpus, prewarm, scenario_map_from_rows,
                                           taxonomy_path)
    from calibration.expanded_pool_stage1 import assert_no_stem_collision
    from shared.scenario_vectors import scenario_text
    import json

    # ---- corpus -------------------------------------------------------------------
    parsed_old = parse_corpus(OLD_DIR)
    parsed_new = parse_corpus(NEW_DIR)
    assert_no_stem_collision({p_.stem for _, p_, _ in parsed_old},
                             {p_.stem for _, p_, _ in parsed_new})
    pairs = (build_pairs(OLD_DIR, "s0", "a0", parsed=parsed_old)
             + build_pairs(NEW_DIR, "s0", "a0", parsed=parsed_new))
    files = [p_.name for _, p_, _ in parsed_old] + [p_.name for _, p_, _ in parsed_new]
    print(f"[corpus] {len(files)} calls, {len(pairs)} pairs")

    # ---- taxonomy, REBOUND to the live DB ids (TRAP 2) ----------------------------
    art = json.loads(taxonomy_path("union_base").read_text(encoding="utf-8-sig"))
    scenario_map, _ = scenario_map_from_rows(art["rows"])

    with connect(a.hostaddr) as conn, conn.cursor() as cur:
        cur.execute("select scenario_key, scenario_id, is_coachable from scenarios")
        live = {k: (sid, co) for k, sid, co in cur.fetchall()}
        cur.execute("select count(*) from kb_pairs")
        kb_before = cur.fetchone()[0]
        cur.execute("select count(*) from calls")
        calls_before = cur.fetchone()[0]

    if not live:
        raise SystemExit("`scenarios` is EMPTY — run ops/ship_union_taxonomy.py first")
    if kb_before and not a.replace and not a.resume_vectors:
        raise SystemExit(
            f"kb_pairs already holds {kb_before:,} rows. `insert_kb_pair` is now a true upsert "
            f"so a re-run WOULD rewrite the routing — but any pair the new run does not "
            f"produce would survive as a stale orphan, and Pinecone would keep its vector. "
            f"Pass --replace to TRUNCATE kb_pairs first, which is the only way to guarantee "
            f"the table equals this run's output.")
    missing_keys = sorted(set(scenario_map) - set(live))
    if missing_keys:
        raise SystemExit(
            f"{len(missing_keys)} artifact key(s) are absent from the live `scenarios` table, "
            f"e.g. {missing_keys[:3]}. The DB taxonomy is not the one this artifact "
            f"describes; routing would attach pairs to the wrong scenarios. Halt.")
    synthetic = {k: v["scenario_id"] for k, v in scenario_map.items()}
    for k, v in scenario_map.items():
        v["scenario_id"] = live[k][0]          # THE REBIND
    n_rebound = sum(1 for k in scenario_map if synthetic[k] != scenario_map[k]["scenario_id"])
    print(f"[taxonomy] {len(scenario_map)} scenarios, {sum(1 for v in live.values() if v[1])} "
          f"coachable; rebound {n_rebound} synthetic id(s) to live DB serials")
    print(f"[db] calls={calls_before} kb_pairs={kb_before}")

    # ---- response-vector debt -----------------------------------------------------
    resp_texts = sorted({p_["response_text"] for p_ in pairs})
    _, resp_missing = _load_cached(resp_texts, WIDTH)
    trig_texts = sorted({p_["trigger_text"] for p_ in pairs})
    _, trig_missing = _load_cached(trig_texts, WIDTH)
    print(f"[vectors] triggers {len(trig_texts) - len(trig_missing)}/{len(trig_texts)} cached "
          f"({len(trig_missing)} missing) | responses "
          f"{len(resp_texts) - len(resp_missing)}/{len(resp_texts)} cached "
          f"({len(resp_missing)} to fetch)")
    if trig_missing:
        raise SystemExit(f"{len(trig_missing)} TRIGGER vector(s) uncached — routing would not "
                         f"be the routing that was measured. Halt.")
    if len(resp_missing) > FETCH_CEILING:
        raise SystemExit(f"{len(resp_missing)} response vectors to fetch exceeds the "
                         f"{FETCH_CEILING} ceiling — halt and ask the operator.")

    print("\nPLAN  (DB first, the paced fetch last)")
    print(f"  1. route {len(pairs)} pairs, production assign_scenarios, cache-only")
    print(f"  2. upsert {len(files)} calls  (currently {calls_before})")
    print(f"  3. insert kb_pairs  (currently {kb_before})")
    print(f"  4. upsert {len(pairs)} TRIGGER vectors into {a.index}  (cached, free)")
    print(f"  5. vectors mode={a.vectors}"
          + (f": fetch {len(resp_missing)} response vectors PACED (~"
             f"{len(resp_missing) / 140:.0f} min) then upsert them"
             if a.vectors == "both" else "  (no response work)"))
    if not a.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return

    from shared import pinecone_store, storage
    from config import load_config
    cfg = load_config()

    # *** ORDER MATTERS AND IT CHANGED. *** The response fetch is paced to the gateway's
    # measured 150-requests-per-window ceiling, so it is an ~85-MINUTE job. Running it first
    # would keep Layer B dark for an hour and a half for data ROUTING DOES NOT USE: routing
    # consumes TRIGGER and SCENARIO vectors only. So every DB write and the triggers namespace
    # land first (~10 min, all cache-only), and the paced tail runs last where it blocks
    # nothing. `query_triggers` reads the triggers namespace, so the intermediate state serves
    # lookups rather than being half-broken.

    # ---- route (cache-only shim; aborts on a miss, so this IS the measured routing) ----
    prewarm([scenario_text(v) for v in scenario_map.values()], 20)
    install_embedder_shim(WIDTH)
    from v1.layer_b import assign_scenarios
    print("[1/5] routing " + str(len(pairs)) + " pairs...", flush=True)
    trigger_vecs = assign_scenarios(pairs, scenario_map, None)
    sunk = sum(1 for p_ in pairs if not live[p_["scenario_key"]][1])
    share = sunk / len(pairs)
    print("[1/5] routed. sink share {:.1%}  (G-R2 measured 47.3% new / 48.1% old)"
          .format(share))
    if not 0.40 <= share <= 0.56:
        raise SystemExit(
            "SINK SHARE {:.1%} IS OUTSIDE THE MEASURED BAND (40-56%). The DB taxonomy, the "
            "artifact and the cached vectors disagree about something; refusing to write "
            "12,444 rows onto a substrate that cannot be vouched for.".format(share))

    # ---- calls, then pairs (SKIPPED on a vectors-only resume) --------------------
    if a.resume_vectors:
        # Read each pair's identity back from the DB rather than writing it. The join key is
        # (call_id, turn_index) — the same natural key the table is unique on — so a pair
        # cannot be matched to the wrong row. Any pair missing from the DB means kb_pairs is
        # NOT already correct, which is the one thing this mode assumes.
        with connect(a.hostaddr) as conn, conn.cursor() as cur:
            cur.execute("select c.filename, p.turn_index, p.pair_id, p.call_id, p.scenario_key"
                        " from kb_pairs p join calls c using(call_id)")
            bykey = {(fn, ti): (pid, cid, sk) for fn, ti, pid, cid, sk in cur.fetchall()}
        missing = [p_ for p_ in pairs if (p_["call_filename"], p_["turn_index"]) not in bykey]
        if missing:
            raise SystemExit(
                f"--resume-vectors assumes kb_pairs is already complete, but {len(missing)} "
                f"of {len(pairs)} pairs are absent from it. Run without this flag (add "
                f"--replace) to write the table properly.")
        drift = 0
        for p_ in pairs:
            pid, cid, sk = bykey[(p_["call_filename"], p_["turn_index"])]
            p_["pair_id"], p_["call_id"] = pid, cid
            if sk != p_["scenario_key"]:
                drift += 1
        if drift:
            raise SystemExit(
                f"{drift} pair(s) route differently now than what is stored in kb_pairs. "
                f"Upserting vectors would make Pinecone disagree with Postgres — the exact "
                f"divergence this mode exists to avoid. Re-run with --replace instead.")
        kb_after, calls_after = kb_before, calls_before
        print(f"[2-3/5] resume: matched all {len(pairs)} pairs to existing rows, "
              f"0 routing drift — skipping calls/kb_pairs writes")
    else:
      with connect(a.hostaddr) as conn:
          if a.replace and kb_before:
              with conn.cursor() as cur:
                  cur.execute("delete from kb_pairs")
                  print(f"[2/5] --replace: deleted {cur.rowcount:,} existing kb_pairs")
              conn.commit()
          call_ids = {}
          for n, fn in enumerate(files, 1):
              call_ids[fn] = storage.upsert_call(conn, fn)
              if n % 250 == 0 or n == len(files):
                  print("[2/5] calls " + str(n) + "/" + str(len(files)), flush=True)
          for i, p_ in enumerate(pairs):
              p_["call_id"] = call_ids[p_["call_filename"]]
              p_["pair_id"] = storage.insert_kb_pair(conn, p_)
              if (i + 1) % 2000 == 0 or i + 1 == len(pairs):
                  print("[3/5] kb_pairs " + str(i + 1) + "/" + str(len(pairs)), flush=True)
          with conn.cursor() as cur:
              cur.execute("select count(*) from kb_pairs")
              kb_after = cur.fetchone()[0]
              cur.execute("select count(*) from calls")
              calls_after = cur.fetchone()[0]
    print("[3/5] calls {} -> {}, kb_pairs {} -> {}".format(
        calls_before, calls_after, kb_before, kb_after))

    # ---- trigger vectors: free, all cached ---------------------------------------
    if a.vectors in ("both", "triggers"):
        # *** THE ONLY POSITIONAL PAIRING IN THIS SCRIPT, SO IT IS ASSERTED. ***
        # scenario_key travels ON the pair dict (assign_scenarios mutates it in place), so a
        # key can never land on the wrong pair. `trigger_vecs` is different: it is a PARALLEL
        # list matched by index, and it is correct only because `pairs` is never reordered
        # between routing and here. Nothing enforced that, so a future filter or sort would
        # silently attach every vector to the wrong pair.
        if len(trigger_vecs) != len(pairs):
            raise SystemExit(f"{len(trigger_vecs)} trigger vectors for {len(pairs)} pairs — "
                             f"the positional pairing is broken; refusing to upsert.")
        for i, p_ in enumerate(pairs):
            p_["trigger_vec"] = list(trigger_vecs[i])
        for i in range(0, len(pairs), 500):
            pinecone_store.upsert_pairs(cfg.pinecone_api_key, a.index, pairs[i:i + 500],
                                        namespaces=("triggers",))
            print("[4/5] trigger vectors " + str(min(i + 500, len(pairs))) + "/"
                  + str(len(pairs)), flush=True)
        print("[4/5] triggers namespace populated - LAYER B IS SERVICEABLE FROM HERE")

    # ---- responses: the paced tail ------------------------------------------------
    if a.vectors == "both" and resp_missing:
        from calibration.trial_gateway import EMBED_PER_MINUTE
        print("[5/5] fetching {} response vectors, paced at {}/min -> ~{:.0f} min. "
              "Resumable: the cache keeps every vector, so a kill costs nothing."
              .format(len(resp_missing), EMBED_PER_MINUTE,
                      len(resp_missing) / max(EMBED_PER_MINUTE, 1)), flush=True)
        from calibration.trial_pool_unit_gemini import embed_cached
        from shared.gateway import EMBED_MAX_PARALLEL
        # Was a hardcoded 8, which is EXACTLY the gateway's max_parallel_requests ceiling --
        # so the fetch ran permanently at the limit with no headroom for retries and died at
        # 7,200 of 7,472 on 2026-08-19. shared.gateway now clamps in-flight requests with a
        # semaphore regardless of what a caller asks for; matching the worker count to it just
        # avoids spawning threads that can only ever block.
        embed_cached(sorted(resp_missing), EMBED_MAX_PARALLEL)
        _, still = _load_cached(resp_texts, WIDTH)
        if still:
            raise SystemExit(str(len(still)) + " response vector(s) STILL uncached")
    if a.vectors == "both":
        resp_mat, miss = _load_cached([p_["response_text"] for p_ in pairs], WIDTH)
        if resp_mat is None:
            raise SystemExit("response vectors incomplete (" + str(len(miss)) + " missing)")
        for i, p_ in enumerate(pairs):
            p_["response_vec"] = [float(x) for x in resp_mat[i]]
        for i in range(0, len(pairs), 500):
            pinecone_store.upsert_pairs(cfg.pinecone_api_key, a.index, pairs[i:i + 500],
                                        namespaces=("responses",))
            print("[5/5] response vectors " + str(min(i + 500, len(pairs))) + "/"
                  + str(len(pairs)), flush=True)

    if a.vectors != "none":
        stats = pinecone_store._get_index(cfg.pinecone_api_key,
                                          a.index).describe_index_stats()
        ns = {k: v["vector_count"] for k, v in (stats.get("namespaces") or {}).items()}
        print("[vectors] {}: total={} namespaces={}".format(
            a.index, stats.get("total_vector_count"), ns))

    print(f"\nCOMMITTED. calls {calls_before} -> {calls_after}, "
          f"kb_pairs {kb_before} -> {kb_after}")
    print("SHIP LAYER B COMPLETE")


if __name__ == "__main__":
    main()
