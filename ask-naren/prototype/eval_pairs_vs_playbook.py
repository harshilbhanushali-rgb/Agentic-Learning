#!/usr/bin/env python3
"""PROTOTYPE, throwaway — see README.md in this directory before touching this file.

THE QUESTION: for Ask Naren, does adding the retrieved scenario's Layer C playbook
(`key_moves`) to the prompt produce a better-grounded answer than the matched kb_pair alone?
(ADR 0001 — the switch was left as an empirical question, not settled by design.)

METHOD, and why it looks like this:

  - Retrieval is real, not simulated: cosine search over every coachable-scenario kb_pair's
    trigger embedding, in the SAME space Layer B's production index uses (gateway backend,
    gemini-embedding-2 @ 3072 dims — see Brain/CLAUDE.md "PRODUCTION STATE"). Never build a
    parallel local-bge vector here; the two embedding spaces are not comparable.
  - The held-out item's own call is excluded from its own retrieval pool (leave-one-call-out),
    the same rule Brain/calibration/probe_retrieval_gate.py uses — otherwise the "closest
    neighbour" is often just the same call's adjacent turn, which is not the question.
  - Judging is deliberately NOT a holistic "which answer is better" LLM judge. That exact
    shape — a blinded model comparing two replies to the same moment — already failed on
    this corpus: Brain/docs/findings/head-to-head-comparison.md measured position-swap
    agreement at 0.669 (bar >=0.75) and a transplant-penalty control at 0.835 (bar <0.75,
    replicated), i.e. the judge reverses itself on ~20% of swapped pairs and rewards
    retrieval artifacts as if they were answer quality. Layer D's later redesign only
    recovered a working pairwise grader by moving to binary, evidence-gated checks
    (verbatim quotes required) instead of holistic quality opinions — this harness follows
    that fix, not the failed shape. Every score below is programmatic/verifiable:
      * cites_retrieved_call  — does the model's own citation match what was retrieved
      * quote_verbatim        — does its quote actually appear in the real cited response
      * sim_to_ground_truth   — embedding cosine to the real historical answer (a number,
                                not an LLM's opinion of quality)
  - No independent ground-truth test set exists yet for Ask Naren, so this script builds a
    small one itself: one real (trigger, Naren's real response) pair per coachable scenario
    that already has a live playbook, sampled with a fixed seed. See README.md.

Zero writes to Postgres (read-only connection, enforced). Zero edits to tuning.yaml. Spends
~2 x N gemini-3.6-flash chat calls (N=25 by default); embeddings are ~free off the warm
gateway cache since these trigger texts were already embedded when the corpus was built.

    python ask-naren/prototype/eval_pairs_vs_playbook.py --run
    python ask-naren/prototype/eval_pairs_vs_playbook.py --load ask-naren/prototype/artifacts/eval_pairs_vs_playbook.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# ask-naren/prototype/this_file.py -> ask-naren/prototype -> ask-naren -> repo root -> Brain/
_BRAIN = Path(__file__).resolve().parent.parent.parent / "Brain"
if str(_BRAIN) not in sys.path:
    sys.path.insert(0, str(_BRAIN))

from config import load_config              # noqa: E402  (path bootstrap must come first)
from preprocessing import embedder           # noqa: E402
from shared import storage                  # noqa: E402
from shared.gateway import GatewayClient     # noqa: E402

CHAT_MODEL = "gemini-3.6-flash"
REASONING = "medium"
TARGET_N = 25
SEED = 20260826
MIN_TRIGGER_LEN = 40
MIN_RESPONSE_LEN = 60

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"


# --------------------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------------------

def _connect_read_only(database_url: str, hostaddr: str | None = None):
    """A connection Postgres itself refuses to write through — lifted from
    Brain/calibration/probe_retrieval_gate.py's `_connect_read_only`.

    `hostaddr` works around the local resolver refusing `*.neon.tech` (same fix as
    Brain/ops/ship_union_taxonomy.py's `connect()` — `host` stays in the URL for TLS
    SNI/SCRAM, `hostaddr` just tells the driver which IP to open the socket on)."""
    if hostaddr and "hostaddr=" not in database_url:
        database_url += ("&" if "?" in database_url else "?") + f"hostaddr={hostaddr}"
        print(f"[dns] hostaddr={hostaddr} (host kept in the URL for SNI/SCRAM)")
    conn = storage.get_connection(database_url)
    conn.execute("SET SESSION default_transaction_read_only = on")
    ro = conn.execute("SELECT current_setting('default_transaction_read_only')").fetchone()[0]
    if ro != "on":
        raise RuntimeError(f"read-only enforcement failed: setting is {ro!r}")
    return conn


def _load_coachable_pool(conn) -> tuple[list[dict], dict]:
    """Every kb_pair filed under a coachable scenario, plus each scenario's live playbook
    (or None). The retrieval SEARCH SPACE is every coachable pair regardless of length; only
    test-item SELECTION (below) additionally filters for substantive text.

    Deduped on (normalized trigger, normalized response): the corpus has some transcripts
    ingested twice under two different `calls.filename` values with byte-identical pairs
    (measured: 64 of 6528 coachable rows, 32 distinct pairs x 2 filenames, spread across 15
    scenarios). `_retrieve_top1`'s leave-one-call-out mask excludes by filename, so an
    un-deduped pool lets a held-out item's exact content-twin survive under the other
    filename, get selected as its own top-1 neighbour (cosine 1.0), and leak the held-out
    item's own ground-truth response into its own grounding prompt. Dropping the duplicate
    here, once, fixes it for both retrieval and test-item selection instead of teaching the
    mask about text content."""
    scenarios = storage.get_scenarios(conn)
    coachable = [s for s in scenarios if s["is_coachable"]]
    pool: list[dict] = []
    playbooks: dict = {}
    seen_content: set[tuple[str, str]] = set()
    for s in coachable:
        key = s["scenario_key"]
        for p in storage.get_naren_responses_for_scenario(conn, key):
            content_key = (_normalize(p["trigger_text"]), _normalize(p["response_text"]))
            if content_key in seen_content:
                continue
            seen_content.add(content_key)
            pool.append({**p, "scenario_key": key})
        playbooks[key] = storage.get_playbook_for_scenario(conn, key)
    return pool, playbooks


# --------------------------------------------------------------------------------------
# Pure helpers — no I/O, so the logic a silent bug would invalidate is directly readable.
# --------------------------------------------------------------------------------------

def _build_test_set(pool: list[dict], playbooks: dict, rng: np.random.Generator,
                    n: int) -> list[dict]:
    """One substantive real pair per coachable scenario that has a live playbook."""
    by_scenario: dict[str, list[dict]] = {}
    for p in pool:
        if (len(p["trigger_text"] or "") >= MIN_TRIGGER_LEN
                and len(p["response_text"] or "") >= MIN_RESPONSE_LEN):
            by_scenario.setdefault(p["scenario_key"], []).append(p)
    eligible = sorted(k for k, v in by_scenario.items() if v and playbooks.get(k))
    if not eligible:
        raise RuntimeError("no coachable scenario has both a live playbook and a "
                            "substantive kb_pair — nothing to build a test set from")
    chosen = sorted(rng.choice(eligible, size=min(n, len(eligible)), replace=False).tolist())
    items = []
    for key in chosen:
        candidates = by_scenario[key]
        items.append(candidates[int(rng.integers(0, len(candidates)))])
    return items


def _normalize(s: str) -> str:
    return " ".join((s or "").split()).lower()


def _retrieve_top1(query_vec: np.ndarray, pool_vecs: np.ndarray, call_filenames: list[str],
                   exclude_call: str) -> tuple[int, float]:
    """Leave-one-call-out top-1: the held-out item's own call is masked out of its own pool,
    so an adjacent turn of the same call can't stand in for "the closest OTHER moment"."""
    mask = np.array([cf != exclude_call for cf in call_filenames])
    sims = np.where(mask, pool_vecs @ query_vec, -np.inf)
    best = int(np.argmax(sims))
    return best, float(sims[best])


def _build_prompt(situation: str, matched: dict, moves: list[dict] | None) -> str:
    lines = [
        "You are \"Ask Naren\", an internal Joveo tool that helps a CSM handle a live client "
        "situation by grounding the answer in Naren's closest real historical response.",
        "",
        f"CSM's situation: {situation}",
        "",
        "Closest matching real exchange from Naren's own calls:",
        f"  Client said: {matched['trigger_text']}",
        f"  Naren replied: {matched['response_text']}",
        f"  (call: {matched['call_filename']})",
    ]
    if moves:
        lines += ["", "Known best-practice moves for this type of situation:"]
        for m in moves:
            lines.append(f"  - {m.get('name', '')}: {m.get('criterion', '')}")
    lines += [
        "",
        "Using ONLY the grounding above, write the answer a CSM should give. Paraphrase "
        "Naren's real reply rather than inventing a new answer. If the retrieved exchange is "
        "not actually a close match to the CSM's situation, decline instead of answering "
        "ungrounded.",
        "",
        "Respond as JSON with exactly these keys:",
        '  "declined": boolean,',
        '  "answer": the coaching answer for the CSM (empty string if declined),',
        '  "quote": a verbatim substring copied from Naren\'s reply above that the answer is '
        'based on (empty string if declined),',
        '  "cited_call": the call identifier given above, copied exactly (empty string if '
        'declined).',
    ]
    return "\n".join(lines)


def _score(answer: dict, matched: dict, gt_vec: np.ndarray | None,
          ans_vec: np.ndarray | None) -> dict:
    """Evidence-gated, programmatic checks — no LLM asked to judge quality. See module
    docstring for why a holistic judge is deliberately not used here.

    `sim_to_ground_truth` is None rather than 0.0 when either side has no vector (a
    declined/empty answer) — 0.0 would read as "orthogonal to the truth", a real and very
    different claim from "not answered, not comparable"."""
    quote = answer.get("quote") or ""
    sim = (float(np.dot(ans_vec, gt_vec)) if gt_vec is not None and ans_vec is not None
          else None)
    return {
        "declined": bool(answer.get("declined")),
        "cites_retrieved_call": _normalize(answer.get("cited_call", ""))
        == _normalize(matched["call_filename"]),
        "quote_verbatim": bool(quote.strip()) and _normalize(quote) in
        _normalize(matched["response_text"]),
        "sim_to_ground_truth": sim,
    }


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------

def run(n: int, seed: int, out_path: Path, hostaddr: str | None) -> None:
    config = load_config()
    conn = _connect_read_only(config.database_url, hostaddr)
    try:
        pool, playbooks = _load_coachable_pool(conn)
    finally:
        conn.close()
    if not pool:
        raise SystemExit("ERROR: no coachable kb_pairs found.")

    rng = np.random.default_rng(seed)
    test_items = _build_test_set(pool, playbooks, rng, n)
    print(f"test set: {len(test_items)} held-out items across "
          f"{len({t['scenario_key'] for t in test_items})} coachable scenarios "
          f"(seed={seed})")
    print(f"will spend ~{2 * len(test_items)} {CHAT_MODEL} calls "
          f"(reasoning_effort={REASONING})")

    triggers = [p["trigger_text"] for p in pool]
    call_filenames = [p["call_filename"] for p in pool]
    print(f"embedding {len(triggers)} coachable triggers (warm gateway cache -> mostly free)...")
    pool_vecs = np.asarray(embedder.embed_query_matrix(triggers), dtype=np.float32)
    pool_vecs /= np.maximum(np.linalg.norm(pool_vecs, axis=1, keepdims=True), 1e-12)
    id_to_idx = {p["pair_id"]: i for i, p in enumerate(pool)}

    # Checkpointed after EVERY item, not just at the end, and one item's failure doesn't
    # kill the run -- two real failures in a row (an empty-answer embed 400, then a
    # truncated-JSON parse error) each cost a full re-run of already-paid-for generation
    # calls before this was added. Scoring is free to re-derive; the chat calls are not.
    art = {"config": {"model": CHAT_MODEL, "reasoning": REASONING, "n": len(test_items),
                      "seed": seed},
          "results": []}
    results = art["results"]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with GatewayClient() as gw:
        for item in test_items:
            query_vec = pool_vecs[id_to_idx[item["pair_id"]]]
            best_idx, cosine = _retrieve_top1(query_vec, pool_vecs, call_filenames,
                                              item["call_filename"])
            matched = pool[best_idx]
            playbook = playbooks.get(matched["scenario_key"])
            moves = playbook["playbook"]["key_moves"] if playbook else None

            try:
                prompt_a = _build_prompt(item["trigger_text"], matched, moves=None)
                prompt_b = _build_prompt(item["trigger_text"], matched, moves=moves)
                # max_tokens=2048 truncated a JSON response mid-string on the first real
                # run -- reasoning_effort=medium spends part of the budget on reasoning
                # tokens before the visible completion, so the ceiling needs real
                # headroom, not just enough for the expected answer length.
                #
                # no_cache=True: Brain/shared/gateway.py measured the gateway caching chat
                # completions BY DEFAULT (byte-identical text across calls that look like
                # fresh generations) and documents that any harness measuring run-to-run
                # variance must set this -- an un-cached re-run, or a re-run after changing
                # REASONING, would otherwise silently echo the old answers instead of
                # generating new ones.
                ans_a, meta_a = gw.chat_json(prompt_a, model=CHAT_MODEL,
                                             reasoning_effort=REASONING, temperature=0.2,
                                             max_tokens=8192, no_cache=True)
                ans_b, meta_b = gw.chat_json(prompt_b, model=CHAT_MODEL,
                                             reasoning_effort=REASONING, temperature=0.2,
                                             max_tokens=8192, no_cache=True)
            except Exception as e:                      # noqa: BLE001 — recorded, not fatal
                print(f"  [{len(results) + 1}/{len(test_items)}] {item['scenario_key']} -> "
                      f"GENERATION FAILED, skipping: {e}")
                results.append({
                    "held_out": {"scenario_key": item["scenario_key"],
                                "pair_id": item["pair_id"]},
                    "error": str(e),
                })
                out_path.write_text(json.dumps(art, indent=2), encoding="utf-8")
                continue

            results.append({
                "held_out": {"scenario_key": item["scenario_key"], "pair_id": item["pair_id"],
                            "call_filename": item["call_filename"],
                            "trigger_text": item["trigger_text"],
                            "ground_truth_response": item["response_text"]},
                "retrieved": {"scenario_key": matched["scenario_key"],
                              "call_filename": matched["call_filename"], "cosine": cosine,
                              "trigger_text": matched["trigger_text"],
                              "response_text": matched["response_text"]},
                "playbook_available": playbook is not None,
                "answers": {"pairs_only": ans_a, "playbook_augmented": ans_b},
                # served_model records what actually answered, not just what was asked for --
                # Brain/CLAUDE.md measures the MODEL as the lever on this corpus (3.5-flash-lite
                # follows grounding instructions 11% of the time vs 3.6-flash at 77%), so a
                # silent gateway fallback to a weaker model would misattribute its behavior to
                # CHAT_MODEL with nothing in the artifact to catch it.
                "served_model": {"pairs_only": meta_a.get("served_model"),
                                "playbook_augmented": meta_b.get("served_model")},
            })
            out_path.write_text(json.dumps(art, indent=2), encoding="utf-8")
            print(f"  [{len(results)}/{len(test_items)}] {item['scenario_key']} -> "
                  f"retrieved {matched['scenario_key']} (cos={cosine:.3f}, "
                  f"playbook={'yes' if playbook else 'NO'})")

    n_failed = sum(1 for r in results if "error" in r)
    print(f"checkpointed {len(results)} items ({n_failed} failed) -> {out_path}")
    results[:] = [r for r in results if "error" not in r]
    art["config"]["n"] = len(results)

    _score_results(results)
    out_path.write_text(json.dumps(art, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    _report(art)


def _score_results(results: list[dict]) -> None:
    """Embeds ground truth + both variants' answers and fills in `scores`. Declined answers
    are empty strings, which the gateway's /embeddings rejects outright ("No text parts
    found") rather than returning a zero vector -- so those slots are skipped, not sent."""
    all_texts = []
    for r in results:
        all_texts.append(r["held_out"]["ground_truth_response"])
        all_texts.append(r["answers"]["pairs_only"].get("answer") or "")
        all_texts.append(r["answers"]["playbook_augmented"].get("answer") or "")

    non_empty = [(j, t) for j, t in enumerate(all_texts) if t.strip()]
    print(f"embedding {len(non_empty)}/{len(all_texts)} non-empty texts for ground-truth "
          f"similarity scoring ({len(all_texts) - len(non_empty)} declined/empty, skipped)...")
    doc_vecs: dict[int, np.ndarray] = {}
    if non_empty:
        idxs, texts_ne = zip(*non_empty)
        embedded = np.asarray(embedder.embed_document_matrix(list(texts_ne)), dtype=np.float32)
        embedded /= np.maximum(np.linalg.norm(embedded, axis=1, keepdims=True), 1e-12)
        for j, vec in zip(idxs, embedded):
            doc_vecs[j] = vec

    for i, r in enumerate(results):
        gt_vec = doc_vecs.get(3 * i)
        a_vec = doc_vecs.get(3 * i + 1)
        b_vec = doc_vecs.get(3 * i + 2)
        r["scores"] = {
            "pairs_only": _score(r["answers"]["pairs_only"], r["retrieved"], gt_vec, a_vec),
            "playbook_augmented": _score(r["answers"]["playbook_augmented"], r["retrieved"],
                                         gt_vec, b_vec),
        }


def _report(art: dict) -> None:
    results = art["results"]
    cfg = art["config"]
    print(f"\n{'=' * 78}\nn={len(results)}  model={cfg['model']}  reasoning={cfg['reasoning']}"
          f"  seed={cfg['seed']}\n{'=' * 78}")

    off_model = [(i, sm) for i, r in enumerate(results, 1)
                for variant, sm in r.get("served_model", {}).items()
                if sm and sm != cfg["model"]]
    if off_model:
        print(f"\n*** {len(off_model)} answer(s) were actually served by a DIFFERENT model "
              f"than {cfg['model']!r} (gateway fallback) -- their behavior is NOT evidence "
              f"about {cfg['model']!r}: {off_model[:5]}{' ...' if len(off_model) > 5 else ''}")

    for i, r in enumerate(results, 1):
        h, ret = r["held_out"], r["retrieved"]
        print(f"\n--- item {i}/{len(results)}: {h['scenario_key']} ---")
        print(f"CSM situation (held-out real trigger): {h['trigger_text'][:220]}")
        print(f"Ground truth Naren response [{h['call_filename']}]: "
              f"{h['ground_truth_response'][:220]}")
        print(f"Retrieved neighbour: {ret['scenario_key']} / {ret['call_filename']} "
              f"(cos={ret['cosine']:.3f})  playbook={'yes' if r['playbook_available'] else 'NO'}")
        for variant in ("pairs_only", "playbook_augmented"):
            a, s = r["answers"][variant], r["scores"][variant]
            sim = s["sim_to_ground_truth"]
            sim_str = f"{sim:.3f}" if sim is not None else "n/a"
            print(f"  [{variant}] declined={s['declined']}  "
                  f"cites_retrieved={s['cites_retrieved_call']}  "
                  f"quote_verbatim={s['quote_verbatim']}  "
                  f"sim_to_gt={sim_str}")
            print(f"    answer: {(a.get('answer') or '')[:220]}")

    print(f"\n{'=' * 78}")
    print("AGGREGATE — evidence-gated checks, NOT a holistic LLM judge (that shape already")
    print("failed on this corpus: see Brain/docs/findings/head-to-head-comparison.md)")
    print("=" * 78)
    for variant in ("pairs_only", "playbook_augmented"):
        n = len(results)
        declined_flags = [r["scores"][variant]["declined"] for r in results]
        declined = sum(declined_flags)
        answered = [r for r, d in zip(results, declined_flags) if not d]
        # Denominated on ANSWERED items, not n. A decline is empty cited_call/quote by
        # construction (see the prompt), so scoring it against n silently counts every
        # abstention as a grounding FAILURE rather than as "not attempted" -- a materially
        # different claim about grounding discipline. Measured cost of getting this wrong
        # on the first real run: 76%/72% printed vs the true 100%/95% among answered items.
        cites = sum(r["scores"][variant]["cites_retrieved_call"] for r in answered)
        quotes = sum(r["scores"][variant]["quote_verbatim"] for r in answered)
        sims = [r["scores"][variant]["sim_to_ground_truth"] for r in answered
               if r["scores"][variant]["sim_to_ground_truth"] is not None]
        cos_declined = [r["retrieved"]["cosine"] for r, d in zip(results, declined_flags) if d]
        cos_answered = [r["retrieved"]["cosine"] for r in answered]
        print(f"\n{variant}: n={n}")
        print(f"  declined:              {declined}/{n}")
        if answered:
            print(f"  cites retrieved call:  {cites}/{len(answered)} "
                  f"({cites / len(answered):.0%} of ANSWERED items)")
            print(f"  verbatim quote:        {quotes}/{len(answered)} "
                  f"({quotes / len(answered):.0%} of ANSWERED items)")
        else:
            print("  cites retrieved call:  n/a (every answer declined)")
            print("  verbatim quote:        n/a (every answer declined)")
        if sims:
            print(f"  sim to ground truth:   mean={np.mean(sims):.3f}  "
                  f"median={np.median(sims):.3f}  (n={len(sims)}/{n} answered)")
        else:
            print("  sim to ground truth:   n/a (every answer declined)")
        # Declining is NOT a random sample of items -- it correlates with weaker retrieval,
        # so excluding declines from the sim mean above is a selection effect, not free of
        # one: a variant that declines more on hard items can win on mean similarity without
        # producing a single better answer. Surface the correlation so that isn't hidden.
        if cos_declined and cos_answered:
            print(f"  (retrieval cosine: declined items avg {np.mean(cos_declined):.3f} vs "
                  f"answered items avg {np.mean(cos_answered):.3f} -- if declined is lower, "
                  f"the sim-to-ground-truth mean above is inflated by skipping the hard cases)")

    # A PAIRED comparison, not two independently-filtered means: only items where BOTH
    # variants answered are comparable at all -- an item where one declined and the other
    # didn't has no "loser's" score to compare against, and folding it into either variant's
    # mean (or dropping it silently) answers a narrower question than "which variant wins on
    # this item" without saying so. Compute and label it explicitly instead of leaving the
    # two per-variant means above to be read as directly comparable (they overlap but are not
    # the same item set whenever decline sets differ).
    paired_deltas = []
    both_declined = disagree = 0
    for r in results:
        sa, sb = r["scores"]["pairs_only"], r["scores"]["playbook_augmented"]
        if sa["declined"] and sb["declined"]:
            both_declined += 1
        elif sa["declined"] != sb["declined"]:
            disagree += 1
        else:
            sim_a, sim_b = sa["sim_to_ground_truth"], sb["sim_to_ground_truth"]
            if sim_a is not None and sim_b is not None:
                paired_deltas.append(sim_b - sim_a)
    print(f"\npaired comparison (sim_to_ground_truth, playbook_augmented - pairs_only):")
    print(f"  both declined: {both_declined}/{len(results)}   "
          f"disagreed on declining: {disagree}/{len(results)}   "
          f"both answered: {len(paired_deltas)}/{len(results)}")
    if paired_deltas:
        se = float(np.std(paired_deltas, ddof=1) / np.sqrt(len(paired_deltas))) \
            if len(paired_deltas) > 1 else float("nan")
        print(f"  mean delta: {np.mean(paired_deltas):+.4f}  (stderr {se:.4f})  "
              f"playbook higher: {sum(1 for d in paired_deltas if d > 0.01)}  "
              f"pairs_only higher: {sum(1 for d in paired_deltas if d < -0.01)}  "
              f"~tie: {sum(1 for d in paired_deltas if abs(d) <= 0.01)}")
        if disagree:
            print(f"  NOTE: {disagree} item(s) had the two variants disagree on whether to "
                  f"decline at all -- excluded from this paired delta (no comparable score "
                  f"on the declined side), but that disagreement is itself a real behavioral "
                  f"difference between the variants, not captured by this number.")

    with_playbook = sum(r["playbook_available"] for r in results)
    without = len(results) - with_playbook
    if without:
        print(f"\n({without}/{len(results)} items had no live playbook for the retrieved "
              f"scenario — playbook_augmented == pairs_only for those, so the comparison "
              f"above is diluted toward 'no difference' by exactly that many items)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true",
                    help="build the test set, retrieve, generate, and score; spends "
                    "~2xN gemini-3.6-flash calls")
    ap.add_argument("--load", help="re-print the report from a saved artifact, zero cost")
    ap.add_argument("--score", help="(re-)score a checkpointed artifact's generations and "
                    "write+report — zero Gemini spend, only the ground-truth embeddings")
    ap.add_argument("--n", type=int, default=TARGET_N)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=str(ARTIFACTS_DIR / "eval_pairs_vs_playbook.json"))
    ap.add_argument("--hostaddr", default="18.138.49.39",
                    help="IP for the Neon host; the system resolver refuses *.neon.tech "
                    "(same default Brain/ops scripts use). Pass '' to disable.")
    args = ap.parse_args()

    if args.load:
        _report(json.loads(Path(args.load).read_text(encoding="utf-8-sig")))
        return 0
    if args.score:
        path = Path(args.score)
        art = json.loads(path.read_text(encoding="utf-8-sig"))
        _score_results(art["results"])
        path.write_text(json.dumps(art, indent=2), encoding="utf-8")
        print(f"wrote {path}")
        _report(art)
        return 0
    if not args.run:
        ap.error("pass --run to spend the Gemini calls, --score PATH to score an existing "
                 "checkpoint, or --load PATH to re-report")
    run(args.n, args.seed, Path(args.out), args.hostaddr or None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
