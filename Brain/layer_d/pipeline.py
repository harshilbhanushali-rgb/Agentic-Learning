"""Layer D orchestrator: CSM calls and Naren's own moments through one instrument.

Order of operations per CSM transcript:
  1. parse + FAIL-CLOSED speaker check (an unverified client speaker excludes the
     transcript; the old pipeline scored unlisted Joveo colleagues as clients)
  2. segmentation + sink-relative signal detection  -> moments
  3. moments whose scenario has a LIVE playbook and a CSM reply -> graded
     (deferral/silence moments are stored ungraded; coverage gaps are reported)
  4. move_events upserted; the transcript checkpoint is marked ONLY after every
     one of its batches succeeded (the old pipeline checkpointed failed batches
     and lost their signals permanently)

Then the benchmark pass: for every live playbook, a sample of Naren's own routed
kb_pairs is graded with the SAME arm and written as rater_id='naren'. Finally
move_performance is rebuilt from events (full recompute, idempotent).

Chat transport: shared.gateway.GatewayClient.chat_json with no_cache=True (house
rule), injected as a callable so tests and the C2 harness never touch the network.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ego_trap import csm_registry
from ego_trap.transcript_parser import parse_transcript
from layer_d import aggregate, graders, signals
from shared import checkpoint, relative_match, storage
from shared.tuning import get_tuning

# Naren moments graded per live playbook in the benchmark pass. A sample, not the
# full population: the 12,444-pair corpus would cost ~50x more and the benchmark
# rate stabilises long before that. Module constant (request packing / spend shape,
# not a data property); the C3 harness sweeps it before anything trusts the rates.
NAREN_SAMPLE_PER_SCENARIO = 30

_REPORT_TOP_N = 5


def checkpoint_layer(tuning_d, classes_fp: str = "") -> str:
    """Checkpoint identity: segmentation arm, grader arm, MODEL and EFFORT are all
    load-bearing (changing any of them MUST invalidate prior progress — same rule
    as the old ego_trap_{mode}_v2 suffix, extended so two instruments' verdicts can
    never silently mix under one identity)."""
    # _v2: the checks contract gained the partial tier (2026-08-24) -- a prompt/
    # vocabulary change is an instrument change, so prior progress must invalidate.
    # The swap flag is part of the identity for the same reason.
    # _v3 (2026-08-26): the interjection guard changes which moments get graded at
    # all, and the exemplar-substantive filter changes WHAT they're graded against
    # -- both change verdicts for moments already checkpointed under _v2, so prior
    # progress must invalidate the same way a model/effort change would.
    # classes_fp (say arm only): the SAY/DO routing fingerprint. A re-classified
    # move changes which moves get graded at all -- an instrument change, same rule.
    # _v4 (2026-09-06): the interjection guard tightened (signals.is_substantive_reply:
    # distinct lemmas + one real clause). Strictly stricter than _v3 -- it only ever
    # REMOVES graded moments -- so the _v3 events were reclassified in place and the
    # _v3 checkpoints copied to _v4 (findings §11c) instead of a paid regrade.
    swap = "swap" if tuning_d.pairwise_swap else "noswap"
    cls = f"_cls{classes_fp}" if classes_fp else ""
    return (f"layer_d_{tuning_d.segmentation_arm}_{tuning_d.grader_arm}"
            f"_{tuning_d.grader_model}_{tuning_d.grader_reasoning_effort}_{swap}{cls}_v4")


def gateway_chat(model: str | None = None,
                 reasoning_effort: str | None = None) -> Callable[[str], Any]:
    """The production chat callable, configured from tuning.yaml's grader keys.

    max_tokens 65536 and the 600s client timeout are the playbook-validation
    lessons: Gemini reasoning models spend THINKING tokens from the same
    max_tokens pool (16384 truncated JSON mid-string after ~14k of thinking), and
    a client-side read timeout burns an attempt the server still bills.
    A malformed GENERATION (non-JSON / empty completion) is resampled up to twice:
    the transport already retries HTTP failures, but a parse failure raised straight
    through and killed a whole scenario on the first 33-playbook run (flash-lite,
    'Expecting property name', 1 of 33 scenarios). With no_cache=True every retry is
    a genuinely fresh sample, so transient malformation usually clears. Anything
    else — rate limits, transport, budget — still propagates untouched.
    Lazy import so tests never need httpx creds.
    """
    from shared.gateway import GatewayClient, GatewayError
    d = get_tuning().layer_d
    client = GatewayClient(timeout=600.0)
    chosen = model or d.grader_model
    effort = reasoning_effort if reasoning_effort is not None \
        else d.grader_reasoning_effort
    effort_arg = None if effort in ("", "none") else effort

    def chat(prompt: str) -> Any:
        last: Exception | None = None
        for attempt in range(3):
            try:
                parsed, _usage = client.chat_json(
                    prompt, model=chosen, max_tokens=65536, no_cache=True,
                    reasoning_effort=effort_arg)
                return parsed
            except GatewayError as e:
                msg = str(e)
                if "non-JSON" not in msg and "empty completion" not in msg:
                    raise
                last = e
                print(f"[layer_d] malformed completion "
                      f"(attempt {attempt + 1}/3), resampling: {msg[:120]}")
        raise last  # three malformed samples in a row is a real signal, not noise

    return chat


def select_stems(
    recordings_dir: str | Path,
    mapping: dict[str, tuple[str, str]],
    *,
    limit: int = 0,
    exclude: tuple[str, ...] = (),
) -> list[str]:
    """The transcripts a run will score, in filename order. ONE definition, used by
    both the batch and ops/run_layer_d.py's run_id derivation -- run_id is a sha1 of
    this list, so the selection and the id must never be computed twice differently.

    `limit` keeps the LAST N (most recent; Avoma files are date-prefixed), matching
    run_ego_trap.py's convention. Unmapped stems are dropped (no csm_id, nothing to
    attribute a gap to); `exclude` is validated by the ops script before it gets here.
    """
    stems = sorted(p.stem for p in Path(recordings_dir).glob("*.txt"))
    stems = [s for s in stems if s in mapping and s not in set(exclude)]
    return stems[-limit:] if limit else stems


def load_client_roster(path: str | Path) -> frozenset[str]:
    """One verified client speaker name per line (case-insensitive). The roster is
    what lets speaker classification fail CLOSED -- see signals.unverified_speakers."""
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    return frozenset(l.strip().lower() for l in lines if l.strip())


def live_playbooks_flat(conn) -> list[dict]:
    """The live playbook rows with the nested `playbook` body flattened to the top.

    storage._playbook_row_to_dict returns `key_moves`/`situation_signature` UNDER a
    `playbook` key (round-trip fidelity for the loader's G-P2 gate). Everything in
    this module wants them flat, and the first blind audit (2026-08-23) caught the
    mismatch: reading `playbook["key_moves"]` on the raw row KeyErrors, and
    `.get("situation_signature", "")` silently stripped the scenario description
    from every grader prompt. ALL get_playbooks reads in this module go through
    here so the two shapes can never mix again.
    """
    return [{**p, **p["playbook"]} for p in storage.get_playbooks(conn, "live")]


def playbook_move_specs(playbook: dict) -> list[dict]:
    """The grader-facing move list from one FLATTENED playbook row (see
    live_playbooks_flat): move_id (positional, loader-assigned), name, criterion."""
    return [
        {"move_id": m["move_id"], "name": m.get("name", ""),
         "criterion": m.get("criterion", "")}
        for m in playbook["key_moves"]
    ]


def grade_moment_set(
    chat: Callable[[str], Any],
    playbook: dict,
    moments: list[dict],
    tuning_d,
    exemplar_for: Callable[[dict], dict] | None = None,
    say_specs: list[dict] | None = None,
) -> dict[str, list[graders.MoveVerdict]]:
    """Grade a set of same-playbook moments under the configured arm, k_runs times,
    with the k-run consensus applied. Returns {moment_id: verdicts}.

    say arm: `say_specs` (move_classes.say_moves output -- the SAY-routed subset,
    anchors included) replaces the full move list; verdicts cover ONLY those moves.
    Grading a say playbook against its full move list would write unscored rows for
    every DO move under the say identity, polluting the arm's unscored rate."""
    if tuning_d.grader_arm == "say":
        if not say_specs:
            raise ValueError("say arm needs a non-empty say_specs list "
                             "(callers skip playbooks with no SAY-routed moves)")
        moves = say_specs
    else:
        moves = playbook_move_specs(playbook)
    scenario_key = playbook["scenario_key"]
    signature = playbook.get("situation_signature", "")
    k = tuning_d.grader_k_runs

    runs_by_moment: dict[str, list[list[graders.MoveVerdict]]] = {}
    for _ in range(k):
        if tuning_d.grader_arm == "checks":
            graded = graders.grade_checks_batch(
                chat, scenario_key, signature, moves, moments,
                tuning_d.quote_verify_min_overlap)
        elif tuning_d.grader_arm == "say":
            graded = graders.grade_say_batch(
                chat, scenario_key, signature, moves, moments,
                tuning_d.quote_verify_min_overlap)
        elif tuning_d.grader_arm == "pairwise":
            if exemplar_for is None:
                raise ValueError("pairwise arm needs an exemplar_for callable")
            graded = [
                graders.grade_pairwise(
                    chat, scenario_key, signature, moves, m, exemplar_for(m),
                    swap=tuning_d.pairwise_swap,
                    # deterministic per-moment side so position noise cancels
                    csm_side="A" if int(hashlib.sha1(
                        str(m["moment_id"]).encode()).hexdigest(), 16) % 2 == 0
                    else "B")
                for m in moments
            ]
        else:
            raise ValueError(f"unknown grader_arm: {tuning_d.grader_arm!r}")
        for g in graded:
            runs_by_moment.setdefault(g.moment_id, []).append(g.verdicts)

    return {
        mid: graders.aggregate_runs(runs, moves)
        for mid, runs in runs_by_moment.items()
    }


def make_exemplar_picker(
    pairs: list[dict],
    embed_query_matrix: Callable[[list[str]], np.ndarray],
) -> Callable[[dict], dict]:
    """Pairwise arm only: the Naren pair whose TRIGGER is most similar to the
    moment's trigger, picked only from pairs whose RESPONSE is itself substantive
    -- the exemplar-misfire fix. Benchmarking a CSM reply against Naren filler
    ("Yep. Absolutely. Perfect.") produced both false wins and unfair losses in
    the first production run's read-through. Falls back to the full unfiltered
    pool, with a printed warning, if the filter empties it for this scenario:
    failing that scenario's whole grading batch would be a worse outcome than
    grading against an imperfect benchmark for once (see the C3 "landing_page is
    ~0 under every unit" precedent -- a thin scenario is a real finding, not
    grounds to crash).

    Pair-trigger vectors are already paid for in the gateway cache; the moment
    trigger was embedded by signal detection, so this re-read is a cache hit."""
    if not pairs:
        raise ValueError("no Naren pairs to pick an exemplar from")
    from v1.layer_b import _is_substantive  # lazy: spaCy model load
    substantive = [p for p in pairs if _is_substantive(p["response_text"])]
    if not substantive:
        print(f"[layer_d] WARNING: all {len(pairs)} Naren exemplar candidates for "
              f"this scenario are non-substantive; falling back to the unfiltered "
              f"pool")
        substantive = pairs
    trigger_vecs = embed_query_matrix([p["trigger_text"] for p in substantive])

    def pick(moment: dict) -> dict:
        vec = embed_query_matrix([moment["trigger_text"]])
        sims = relative_match.cosine_sims(np.asarray(vec), np.asarray(trigger_vecs))[0]
        best = substantive[int(np.argmax(sims))]
        return {"trigger_text": best["trigger_text"],
                "response_text": best["response_text"]}

    return pick


def verdicts_to_json(verdicts: list[graders.MoveVerdict]) -> list[dict]:
    return [
        {"move_id": v.move_id, "verdict": v.verdict, "quote": v.quote,
         "quote_score": v.quote_score, "reason": v.reason}
        for v in verdicts
    ]


def run_layer_d_batch(
    config,
    conn,
    *,
    recordings_dir: str | Path,
    run_id: str,
    limit: int = 0,
    exclude: tuple[str, ...] = (),
    client_roster: frozenset[str] | None = None,
    allow_unverified_speakers: bool = False,
    chat: Callable[[str], Any] | None = None,
    naren_sample: int = NAREN_SAMPLE_PER_SCENARIO,
) -> tuple[dict, Any]:
    """The full batch. Returns (report, conn) -- also printed by ops/run_layer_d.py.

    The connection is reconnected (storage.reconnect_if_closed) at the start of
    every transcript when conn is not None, so a dropped connection self-heals
    instead of cascading into every remaining transcript's write failing (and its
    grading spend being wasted) for the rest of the run. conn is returned because
    reconnecting swaps in a NEW object -- the caller's original handle can be dead
    by the time this returns, so the caller must rebind to what comes back, same
    contract as ego_trap.pipeline.run_ego_trap_batch.

    A DIFFERENT failure, also checked per transcript (storage.clear_read_only):
    the connection can inherit a LEAKED `SET SESSION
    default_transaction_read_only = on` from an unrelated client sharing the
    same pooled Neon backend (confirmed 2026-08-24/26 -- see clear_read_only's
    docstring for the pooling mechanism and the direct proof). The connection
    stays alive (reconnect above is a no-op), only writes are refused, so this
    needs its own check. Unlike a dead connection, THIS one self-heals --
    clear_read_only actively resets the leaked setting rather than merely
    detecting it, so the run continues instead of losing progress to
    something outside this codebase's control. The batch only ABORTS
    (report["aborted_read_only"] = True) if the reset itself doesn't take,
    which is what a genuine (non-leak) restriction would look like.

    Refuses to start without a client roster unless the operator explicitly allows
    it: fail-open speaker classification is how internal chatter became coaching
    findings on the 100-call run.
    """
    if client_roster is None and not allow_unverified_speakers:
        raise RuntimeError(
            "No client roster supplied. Provide csm_recordings/client_speakers.txt "
            "(one verified client speaker per line; build it from "
            "ops/check_csm_speakers.py + the Avoma rosters) or pass "
            "--allow-unverified-speakers to accept fail-open classification."
        )

    tuning_d = get_tuning().layer_d

    # say arm: the routing classification is part of the instrument. Loaded ONCE,
    # fail-closed (a live move missing from the artifact, or whose criterion hash
    # drifted, raises in say_specs_for below), and its fingerprint is part of the
    # checkpoint identity so a re-classification invalidates prior progress.
    classes = fp = None
    if tuning_d.grader_arm == "say":
        from layer_d import move_classes
        classes = move_classes.load_move_classes()
        fp = move_classes.classes_fingerprint(classes)
    layer = checkpoint_layer(tuning_d, classes_fp=fp or "")
    chat = chat or gateway_chat()

    scenario_rows = storage.get_scenarios(conn)
    scenario_map = {r["scenario_key"]: r for r in scenario_rows}
    coachable_keys = {k for k, r in scenario_map.items() if r["is_coachable"]}
    live_playbooks = {p["scenario_key"]: p for p in live_playbooks_flat(conn)}

    # Validate + pre-compute the SAY move subset per playbook up front: a routing
    # problem should refuse the RUN, before any spend, not fail one transcript in.
    say_specs_by_key: dict[str, list[dict]] = {}
    if classes is not None:
        say_specs_by_key = {
            k: move_classes.say_moves(pb, classes)
            for k, pb in live_playbooks.items()
        }

    recordings = Path(recordings_dir)
    mapping = csm_registry.load_mapping(recordings / "mapping.csv")
    stems = select_stems(recordings, mapping, limit=limit, exclude=exclude)

    scorer = signals.SignalScorer(
        scenario_map,
        margin=tuning_d.similarity_relative_margin,
        cap=tuning_d.max_scenarios_per_signal,
    )

    report = {
        "run_id": run_id, "layer": layer, "grader_arm": tuning_d.grader_arm,
        "segmentation_arm": tuning_d.segmentation_arm,
        "transcripts": len(stems), "processed": 0, "skipped_checkpointed": 0,
        "excluded_unverified_speakers": [], "failed": [],
        "moments": 0, "graded": 0, "deferrals": 0, "silence": 0, "interjections": 0,
        "coverage_gaps": {},        # scenario_key -> moment count (coachable, no playbook)
        "no_say_moves": 0,          # say arm only: moments on playbooks with zero SAY moves
        "events_written": 0, "aborted_read_only": False,
    }

    for stem in stems:
        if checkpoint.is_done(run_id, stem, layer):
            report["skipped_checkpointed"] += 1
            continue
        # A dropped connection (idle timeout, a network blip during the previous
        # transcript's chat calls) otherwise cascades: every subsequent transcript's
        # write fails identically and its grading spend is wasted for nothing --
        # measured 2026-08-26, ~60-95 transcripts lost to exactly this per incident.
        # Same fix already used everywhere else in this project (ego_trap/pipeline.py,
        # v2/layer_c.py, etc.) -- this was the one place it had never been wired in.
        # Skipped when conn is None: every layer_d test drives this function with
        # storage entirely mocked and no real connection to reconnect.
        if conn is not None:
            conn = storage.reconnect_if_closed(conn)
            if storage.clear_read_only(conn):
                remaining = len(stems) - report["processed"] - report["skipped_checkpointed"]
                print(f"[layer_d] DB is READ-ONLY and a reset didn't clear it (a "
                      f"genuine restriction, not just a leaked session setting) -- "
                      f"aborting before '{stem}' rather than wasting grading spend "
                      f"on {remaining} more transcript(s) that would fail to write "
                      f"anyway. Nothing checkpointed this call; re-run once writable "
                      f"to resume from here.")
                report["aborted_read_only"] = True
                break
        csm_id, csm_name = mapping[stem]
        turns = parse_transcript(
            str(recordings / f"{stem}.txt"), csm_name.strip().lower(),
            config.joveo_speakers_lower)

        if client_roster is not None:
            unverified = signals.unverified_speakers(turns, client_roster)
            if unverified:
                report["excluded_unverified_speakers"].append(
                    {"stem": stem, "speakers": sorted(unverified)})
                continue

        try:
            moments = signals.detect_moments(
                turns, stem, scorer, arm=tuning_d.segmentation_arm)
            report["moments"] += len(moments)

            storage.upsert_csm(conn, csm_id, csm_name)
            events: list[dict] = []
            by_playbook: dict[str, list[dict]] = {}
            for m in moments:
                if m.scenario_key not in coachable_keys:
                    continue                    # a sink cannot win admit(); belt+braces
                pb = live_playbooks.get(m.scenario_key)
                if pb is None:
                    report["coverage_gaps"][m.scenario_key] = (
                        report["coverage_gaps"].get(m.scenario_key, 0) + 1)
                    continue
                if classes is not None and not say_specs_by_key.get(m.scenario_key):
                    # Say run, playbook has zero SAY-routed moves: this moment is
                    # pairwise's territory entirely -- nothing to grade OR record
                    # under the say identity.
                    report["no_say_moves"] += 1
                    continue
                base = {
                    "rater_population": "csm", "rater_id": csm_id,
                    "call_id": stem, "source_ref": m.source_ref,
                    "scenario_key": m.scenario_key, "playbook_id": pb["playbook_id"],
                    "grader_arm": tuning_d.grader_arm,
                    "grader_model": tuning_d.grader_model, "via": m.via,
                    "response_outcome": m.response_outcome,
                    "trigger_text": m.trigger_text, "response_text": m.response_text,
                    "k_runs": tuning_d.grader_k_runs, "run_id": run_id,
                }
                if m.response_outcome == "csm" and m.response_text:
                    by_playbook.setdefault(m.scenario_key, []).append(
                        {**base, "moment_id": m.moment_id})
                else:
                    # Deferral / silence / interjection: stored ungraded so the
                    # rates are queryable. "interjection" gets its own bucket
                    # rather than folding into "deferrals" -- the deferral rate is
                    # an already-reported finding and shouldn't silently move.
                    bucket = {"other_joveo": "deferrals",
                              "interjection": "interjections"}.get(
                                  m.response_outcome, "silence")
                    report[bucket] += 1
                    events.append({**base, "verdicts": []})

            for scen_key, pb_moments in by_playbook.items():
                pb = live_playbooks[scen_key]
                exemplar_for = None
                if tuning_d.grader_arm == "pairwise":
                    from preprocessing import embedder  # lazy: heavy import
                    exemplar_for = make_exemplar_picker(
                        storage.get_pairs_for_scenario_multilabel(conn, scen_key),
                        embedder.embed_query_matrix)
                kwargs = {"exemplar_for": exemplar_for}
                if classes is not None:
                    kwargs["say_specs"] = say_specs_by_key.get(scen_key)
                verdicts = grade_moment_set(chat, pb, pb_moments, tuning_d, **kwargs)
                for m in pb_moments:
                    events.append({
                        **{k: v for k, v in m.items() if k != "moment_id"},
                        "verdicts": verdicts_to_json(verdicts[m["moment_id"]]),
                    })
                    report["graded"] += 1

            for e in events:
                storage.upsert_move_event(conn, e)
            report["events_written"] += len(events)
        except Exception as exc:  # noqa: BLE001 -- fail the TRANSCRIPT, not the batch
            # NO checkpoint on failure: the next run retries this transcript. The old
            # pipeline marked failed batches done, losing their signals permanently.
            report["failed"].append({"stem": stem, "error": str(exc)[:200]})
            print(f"  ! {stem} FAILED, not checkpointed: {str(exc)[:200]}")
            continue

        checkpoint.mark_done(run_id, stem, layer)
        report["processed"] += 1
        print(f"  {stem}: {len(moments)} moments, {report['graded']} graded so far")

    if report.get("aborted_read_only"):
        # Skip the naren pass and the aggregate rebuild too -- both are writes
        # (or, for refresh_move_performance, a DELETE) that would fail identically
        # and pointlessly, on top of the abort already logged above.
        report["naren"] = {"skipped": "aborted_read_only", "failed": []}
        report["move_performance_rows"] = None
        return report, conn

    if tuning_d.grader_arm == "pairwise":
        # The benchmark is INSIDE every pairwise judgment (Naren's exemplar is
        # reply B), so a separate benchmark pass would measure nothing the
        # verdicts don't already contain. C2 (2026-08-24) settled the arm.
        report["naren"] = {"skipped": "pairwise embeds the benchmark", "failed": []}
    else:
        report["naren"], conn = run_naren_benchmark(
            config, conn, chat=chat, run_id=run_id, sample=naren_sample)
        if report["naren"].get("aborted_read_only"):
            report["aborted_read_only"] = True
            report["move_performance_rows"] = None
            return report, conn

    if conn is not None:
        conn = storage.reconnect_if_closed(conn)
        if storage.clear_read_only(conn):
            # Audit #7 gap: every transcript already checkpointed successfully at
            # this point (nothing lost), but an unguarded DELETE here would raise
            # an unhandled traceback and lose the printed report for a run that,
            # in substance, fully completed. Same clean-abort shape as mid-loop.
            print("[layer_d] DB is READ-ONLY at the final aggregate step and a "
                  "reset didn't clear it (a genuine restriction) -- all grading "
                  "is safely checkpointed, only the move_performance rebuild was "
                  "skipped. Re-run once writable (cheap: --report-only) to "
                  "rebuild it and print the report.")
            report["aborted_read_only"] = True
            report["move_performance_rows"] = None
            return report, conn
    report["move_performance_rows"] = storage.refresh_move_performance(conn)
    # Return the LIVE connection: reconnect_if_closed above may have swapped it for
    # a fresh object, so the caller's original handle can be dead by now. Same
    # rebind contract as ego_trap.pipeline.run_ego_trap_batch -- returning the live
    # one is what lets the caller close the connection it actually still has open,
    # and use it for anything after this call (e.g. build_reports), instead of a
    # dead handle.
    return report, conn


def run_naren_benchmark(
    config, conn, *, chat: Callable[[str], Any], run_id: str, sample: int,
    only: set[str] | None = None,
) -> tuple[dict, Any]:
    """Grade a sample of Naren's own routed moments per live playbook -- the SAME
    instrument, so the benchmark rate is measured, never assumed.

    Checkpointed per scenario WITH the playbook_id in the item: a remade playbook
    gets a fresh id, so its scenario regrades automatically instead of silently
    reusing the superseded document's "done" marker (this fired for real on
    2026-08-24 when the OG-5 documents were remade under the gradability rule).
    A failed scenario is retried next run, never marked done. `only` restricts to
    named scenario_keys -- the caller pays per scenario, so the caller chooses.

    Returns (out, conn) -- same rebind contract as run_layer_d_batch. Reconnects
    per scenario when conn is not None: this loop is exactly as exposed to a
    dropped connection cascading through every remaining scenario's write as the
    per-transcript loop was (audit #6, 2026-08-26) -- it grades real moments
    (real spend) before writing, and its except/continue would otherwise turn a
    single connection drop into every subsequent scenario's spend being wasted.
    """
    tuning_d = get_tuning().layer_d
    classes = fp = None
    if tuning_d.grader_arm == "say":
        from layer_d import move_classes
        classes = move_classes.load_move_classes()
        fp = move_classes.classes_fingerprint(classes)
    layer = checkpoint_layer(tuning_d, classes_fp=fp or "") + "_naren"
    out = {"scenarios": 0, "graded": 0, "skipped_no_say_moves": 0,
           "failed": [], "aborted_read_only": False}

    for pb in live_playbooks_flat(conn):
        scen_key = pb["scenario_key"]
        if only is not None and scen_key not in only:
            continue
        say_specs = None
        if classes is not None:
            say_specs = move_classes.say_moves(pb, classes)
            if not say_specs:
                out["skipped_no_say_moves"] += 1
                continue
        item = f"{scen_key}:pb{pb['playbook_id']}"
        if checkpoint.is_done(run_id, item, layer):
            continue
        if conn is not None:
            conn = storage.reconnect_if_closed(conn)
            if storage.clear_read_only(conn):
                print(f"[layer_d] DB is READ-ONLY (reset didn't clear it -- a "
                      f"genuine restriction) -- aborting naren benchmark before "
                      f"'{scen_key}' rather than wasting grading spend on the "
                      f"remaining live playbooks. Re-run once writable to resume.")
                out["aborted_read_only"] = True
                break
        pairs = storage.get_pairs_for_scenario_multilabel(conn, scen_key)
        # Deterministic sample: primary-label pairs first, then pair_id order --
        # reproducible across runs without a seed.
        if classes is not None:
            # Say arm samples WHOLE CALLS (docs/findings/layer-d-say-arm.md §2):
            # the arm's unit is the call, so a call-level denominator built from
            # calls sampled pair-by-pair would systematically hand Naren fewer
            # moments per call than the CSM side gets. Calls are ordered by their
            # best pair under the same (primary-first, pair_id) rule, and taken
            # whole until the pair budget is covered.
            by_call: dict[str, list[dict]] = {}
            for p in pairs:
                by_call.setdefault(p["call_filename"], []).append(p)
            call_order = sorted(
                by_call,
                key=lambda c: min((not p["is_primary"], p["pair_id"])
                                  for p in by_call[c]))
            picked: list[dict] = []
            for c in call_order:
                if len(picked) >= sample:
                    break
                picked.extend(sorted(by_call[c], key=lambda p: p["pair_id"]))
            pairs = picked
        else:
            pairs = sorted(pairs, key=lambda p: (not p["is_primary"], p["pair_id"]))[:sample]
        moments = [
            {"moment_id": f"{p['call_filename']}:p{p['pair_id']}",
             "trigger_text": p["trigger_text"], "response_text": p["response_text"],
             "pair_id": p["pair_id"], "call_filename": p["call_filename"]}
            for p in pairs if p["response_text"].strip()
        ]
        if not moments:
            continue
        try:
            exemplar_for = None
            if tuning_d.grader_arm == "pairwise":
                # The benchmark's own exemplar is the playbook's cited evidence:
                # comparing Naren to Naren-top-match would grade him against himself.
                first_ev = (pb["key_moves"][0].get("evidence") or [{}])[0]
                anchor = {"trigger_text": pb.get("situation_signature", ""),
                          "response_text": first_ev.get("quote", "")}
                exemplar_for = lambda m, _a=anchor: _a  # noqa: E731
            kwargs = {"exemplar_for": exemplar_for}
            if classes is not None:
                kwargs["say_specs"] = say_specs
            verdicts = grade_moment_set(chat, pb, moments, tuning_d, **kwargs)
            for m in moments:
                storage.upsert_move_event(conn, {
                    "rater_population": "naren", "rater_id": aggregate.NAREN,
                    "call_id": m["call_filename"], "source_ref": f"pair:{m['pair_id']}",
                    "scenario_key": scen_key, "playbook_id": pb["playbook_id"],
                    "grader_arm": tuning_d.grader_arm,
                    "grader_model": tuning_d.grader_model, "via": "last_turn",
                    "response_outcome": "csm",
                    "trigger_text": m["trigger_text"],
                    "response_text": m["response_text"],
                    "verdicts": verdicts_to_json(verdicts[m["moment_id"]]),
                    "k_runs": tuning_d.grader_k_runs, "run_id": run_id,
                })
                out["graded"] += 1
        except Exception as exc:  # noqa: BLE001
            out["failed"].append({"scenario_key": scen_key, "error": str(exc)[:200]})
            print(f"  ! naren/{scen_key} FAILED, not checkpointed: {str(exc)[:200]}")
            continue
        checkpoint.mark_done(run_id, item, layer)
        out["scenarios"] += 1
    return out, conn


def build_reports(conn, csm_names: dict[str, str]) -> str:
    """Ranked coaching priorities per CSM, as one text block. Pure read: rates come
    from move_performance. Branches on the arm: checks compares two populations'
    absolute rates; pairwise ranks the win/equal/loss record directly (the benchmark
    is inside every verdict) and flags blurry axes instead of dead checks."""
    tuning_d = get_tuning().layer_d
    arm = tuning_d.grader_arm

    def to_rates(rows: list[dict]) -> list[aggregate.MoveRate]:
        return [aggregate.MoveRate(r["playbook_id"], r["move_id"], r["attempts"],
                                   r["hits"], r["partials"]) for r in rows]

    csm_rates = {rid: to_rates(rows)
                 for rid, rows in storage.get_move_rates(conn, "csm", arm).items()}

    move_meta: dict[tuple[int, str], dict] = {}
    for pb in live_playbooks_flat(conn):
        for m in pb["key_moves"]:
            first_quote = (m.get("evidence") or [{}])[0].get("quote", "")
            move_meta[(pb["playbook_id"], m["move_id"])] = {
                "scenario_key": pb["scenario_key"], "name": m.get("name", ""),
                "criterion": m.get("criterion", ""), "naren_quote": first_quote,
            }

    blocks: list[str] = []
    if arm == "pairwise":
        ranked, blurry = aggregate.rank_pairwise(
            csm_rates,
            prior_strength=tuning_d.shrinkage_prior_strength,
            min_attempts=tuning_d.min_attempts_to_rank,
        )
        for rater_id, gaps in sorted(ranked.items()):
            blocks.append(aggregate.format_pairwise_priorities(
                csm_names.get(rater_id, rater_id), gaps, move_meta))
        if blurry:
            lines = ["", "BLURRY-AXIS FLAGS (the judge calls nearly every comparison",
                     "equal on these moves; rewrite candidates, not coachable gaps):"]
            for b in blurry:
                meta = move_meta.get((b["playbook_id"], b["move_id"]), {})
                lines.append(f"  [{meta.get('scenario_key', b['playbook_id'])}] "
                             f"{b['move_id']} tie share {b['tie_share']:.0%} "
                             f"over {b['attempts']} attempts")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    naren_rows = storage.get_move_rates(conn, "naren", arm).get(aggregate.NAREN, [])
    naren_rates = to_rates(naren_rows)
    ranked, dead = aggregate.rank_gaps(
        csm_rates, naren_rates,
        prior_strength=tuning_d.shrinkage_prior_strength,
        min_attempts=tuning_d.min_attempts_to_rank,
        dead_floor=tuning_d.dead_check_naren_floor,
    )
    naren_by_cell = {(r.playbook_id, r.move_id): r for r in naren_rates}
    for rater_id, gaps in sorted(ranked.items()):
        evidence = storage.get_hit_quotes(conn, rater_id, arm)
        if arm == "say":
            csm_by_cell = {(r.playbook_id, r.move_id): r
                           for r in csm_rates.get(rater_id, [])}
            blocks.append(aggregate.format_say_priorities(
                csm_names.get(rater_id, rater_id), gaps, move_meta,
                csm_by_cell, naren_by_cell, evidence,
                densities=storage.get_say_densities(conn)))
        else:
            blocks.append(aggregate.format_priorities(
                csm_names.get(rater_id, rater_id), gaps, move_meta, evidence,
                _REPORT_TOP_N))
    if dead:
        unit = "calls" if arm == "say" else "attempts"
        lines = ["", "DEAD-CHECK FLAGS (the benchmark itself fails these; review the",
                 "check, do not coach the gap):"]
        for d in dead:
            meta = move_meta.get((d.playbook_id, d.move_id), {})
            lines.append(f"  [{meta.get('scenario_key', d.playbook_id)}] {d.move_id} "
                         f"naren {d.naren_rate:.0%} over {d.naren_attempts} {unit}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_combined_reports(conn, csm_names: dict[str, str]) -> str:
    """The production report once BOTH arms have data. Three sections, never
    merged into one ranking because their semantics differ:

    1. REPERTOIRE (layer_d/repertoire.py, findings §11): for every SAY move in
       Naren's repertoire, uses it / never / insufficient data, with the power rule
       enforced per cell. This is the coaching deliverable for say-type moves --
       the rate framing below is dead at the shipped floor (G-S4).
    2. SAY rate-vs-benchmark (kept as a diagnostic: naren_rate - csm_rate, with
       dead-check flags -- expect most cells flagged, that IS the G-S4 finding).
    3. PAIRWISE on DO/MIXED-routed moves (run 137706da74c6's events -- the
       benchmark exemplar is inside every verdict; gap = 1 - match_or_beat).
    Pure read."""
    from layer_d import move_classes, repertoire
    classes = move_classes.load_move_classes()
    tuning_d = get_tuning().layer_d

    def to_rates(rows: list[dict]) -> list[aggregate.MoveRate]:
        return [aggregate.MoveRate(r["playbook_id"], r["move_id"], r["attempts"],
                                   r["hits"], r["partials"]) for r in rows]

    move_meta: dict[tuple[int, str], dict] = {}
    route_by_cell: dict[tuple[int, str], str] = {}
    for pb in live_playbooks_flat(conn):
        for m in pb["key_moves"]:
            quotes = [q for q in ((ev.get("quote") or "").strip()
                                  for ev in (m.get("evidence") or [])) if q]
            cell = (pb["playbook_id"], m["move_id"])
            move_meta[cell] = {
                "scenario_key": pb["scenario_key"], "name": m.get("name", ""),
                "criterion": m.get("criterion", ""),
                "naren_quote": quotes[0] if quotes else "",
                "naren_quotes": quotes,       # every evidence quote: the repertoire
            }                                 # report shows his real deployments
            entry = classes.get(f"{pb['scenario_key']}:{m['move_id']}")
            route_by_cell[cell] = entry["route"] if entry else "pairwise"

    blocks: list[str] = []

    say_csm = {rid: to_rates(rows)
               for rid, rows in storage.get_move_rates(conn, "csm", "say").items()}
    say_naren = to_rates(
        storage.get_move_rates(conn, "naren", "say").get(aggregate.NAREN, []))

    # --- REPERTOIRE section (the say-type coaching deliverable) --------------
    rep_moves = repertoire.naren_repertoire(say_naren)
    coverage = repertoire.repertoire_coverage(rep_moves, say_csm)
    for rater_id, cells in sorted(coverage.items()):
        blocks.append(repertoire.format_repertoire_report(
            csm_names.get(rater_id, rater_id), cells, move_meta,
            csm_quotes=storage.get_verified_quotes(conn, rater_id, "say")))

    # --- SAY section (rate-vs-benchmark, diagnostic) -------------------------
    ranked_say, dead = aggregate.rank_gaps(
        say_csm, say_naren,
        prior_strength=tuning_d.shrinkage_prior_strength,
        min_attempts=tuning_d.min_attempts_to_rank,
        dead_floor=tuning_d.dead_check_naren_floor,
    )
    naren_by_cell = {(r.playbook_id, r.move_id): r for r in say_naren}
    densities = storage.get_say_densities(conn)
    for rater_id, gaps in sorted(ranked_say.items()):
        csm_by_cell = {(r.playbook_id, r.move_id): r
                       for r in say_csm.get(rater_id, [])}
        evidence = storage.get_hit_quotes(conn, rater_id, "say")
        blocks.append(aggregate.format_say_priorities(
            csm_names.get(rater_id, rater_id), gaps, move_meta,
            csm_by_cell, naren_by_cell, evidence, densities=densities))

    # --- PAIRWISE section (DO/MIXED-routed cells only) -----------------------
    pw_csm = {
        rid: [r for r in to_rates(rows)
              if route_by_cell.get((r.playbook_id, r.move_id), "pairwise") == "pairwise"]
        for rid, rows in storage.get_move_rates(conn, "csm", "pairwise").items()
    }
    ranked_pw, blurry = aggregate.rank_pairwise(
        pw_csm,
        prior_strength=tuning_d.shrinkage_prior_strength,
        min_attempts=tuning_d.min_attempts_to_rank,
    )
    for rater_id, gaps in sorted(ranked_pw.items()):
        blocks.append(aggregate.format_pairwise_priorities(
            csm_names.get(rater_id, rater_id) + " (do-type moves, vs exemplar)",
            gaps, move_meta))

    notes: list[str] = []
    if dead:
        notes += ["", "DEAD-CHECK FLAGS, say arm (the benchmark itself rarely says",
                  "these; review the move, do not coach the gap):"]
        for d in dead:
            meta = move_meta.get((d.playbook_id, d.move_id), {})
            notes.append(f"  [{meta.get('scenario_key', d.playbook_id)}] {d.move_id} "
                         f"naren {d.naren_rate:.0%} over {d.naren_attempts} calls")
    if blurry:
        notes += ["", "BLURRY-AXIS FLAGS, pairwise arm (do-type cells the judge",
                  "cannot separate; rewrite candidates, not coachable gaps):"]
        for b in blurry:
            meta = move_meta.get((b["playbook_id"], b["move_id"]), {})
            notes.append(f"  [{meta.get('scenario_key', b['playbook_id'])}] "
                         f"{b['move_id']} tie share {b['tie_share']:.0%} "
                         f"over {b['attempts']} attempts")
    if notes:
        blocks.append("\n".join(notes))
    return "\n\n".join(blocks)
