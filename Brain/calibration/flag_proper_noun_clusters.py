#!/usr/bin/env python3
"""How many of the 38 coachable turn-mode clusters are ONE ACCOUNT rather than a situation?

Spec: docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md, "The caveat that
qualifies the 38: PROPER-NOUN CLUSTERS PERSIST". This is that section's "cheap unrun check".

ZERO chat calls, ZERO embedding requests (the 24k turn vectors are already cached), ZERO
Postgres. Everything here is derived from artifacts and the transcripts on disk.

THE QUESTION. `implementing_and_maintaining_tracking_pixels` reads as a coaching situation
and is really "the Happy Dance account" -- its top c-TF-IDF keywords are `happy dance, dance,
happy`. A rubric written against one client's name transfers to no other client, so every
such cluster inflates the coachable count. Both Gemma and nine blind judges accept these,
because the six sampled utterances look substantive. Neither is a defence.

THREE SIGNALS, NOT ONE, because the spec's phrasing ("top keywords are dominated by a proper
noun") is a PROXY and the thing actually at stake is transferability:

  A  ACCOUNT CONCENTRATION (primary, and the direct measure). Every transcript has an Avoma
     `.speakers.json` roster; the modal non-joveo email domain is the account. A cluster's
     score is the share of its turns from its single largest account. This asks the real
     question -- would a rubric built here transfer -- rather than a lexical proxy for it.

  B  KEYWORD-ACCOUNT CONCENTRATION (which word binds it). For each top c-TF-IDF keyword,
     the share of corpus turns containing that word that come from one account. `budget`
     spreads across accounts; `jovio` and `dance` do not. This is what names the culprit.

  C  PROPER-NOUN RATE (the spec's own wording, for cross-reference). spaCy POS over the pool,
     plus a POS-free capitalisation cross-check. Reported, never used alone.

THE NULL IS MANDATORY AND IS THE WHOLE POINT. `uber.com` alone is 55 of 416 calls, so a
large cluster is expected to look account-concentrated with no pathology whatsoever. Each
cluster is compared against a Monte-Carlo null of the SAME size drawn from the same turn
pool, so the corpus's own account skew is priced in and the flag is a lift over chance, not
a raw share. Without it this script would flag the biggest clusters and call it a finding.

NO CURATED LISTS. There is no list of client names anywhere here -- the account key is read
from the roster and the concentration is measured. That is deliberate: a hand-kept name list
is the anti-pattern this codebase's own threshold rule forbids, and it would silently miss
every account nobody thought to add.

WHAT THIS CANNOT ANSWER. Account concentration does not prove a cluster is worthless -- one
account can raise a genuinely general problem, and the flag says "read this one", not "delete
it". The verdict on any flagged cluster comes from reading its turns, which --show prints.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/flag_proper_noun_clusters.py --load   # free re-report
    ..\\.venv\\Scripts\\python.exe calibration/flag_proper_noun_clusters.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

MERGE = 0.97                    # derived by reading groups in Gemini's centroid band
MIN_CLUSTER_SIZE = 16           # scale-matched count, not a cosine
ADJUDICATION = ARTIFACTS_DIR / "adjudicate_gemini_min16.json"
OUT = ARTIFACTS_DIR / "proper_noun_clusters.json"
NULL_REPS = 400
TOP_KEYWORDS = 3                # how many c-TF-IDF keywords define "the top keywords"
_WORD = re.compile(r"[a-z][a-z0-9'\-]*")


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--show", type=int, default=6,
                   help="member turns printed per flagged cluster. READ THESE -- every "
                        "aggregate in this effort that misled was caught by sample reading.")
    p.add_argument("--no-spacy", action="store_true",
                   help="skip signal C (POS). The capitalisation cross-check still runs.")
    p.add_argument("--load", action="store_true", help="re-report the artifact, free")
    return p.parse_args()


# -- accounts ---------------------------------------------------------------------------

def account_map(recordings: str) -> tuple[dict[str, str], dict[str, str]]:
    """call stem -> account domain, from the Avoma roster sidecars.

    The account is the modal non-joveo email domain among the meeting's speakers. Calls
    whose roster carries no client email at all get no account and are EXCLUDED from every
    concentration denominator rather than being lumped together -- pooling them would
    manufacture a fake shared account and inflate exactly the number this script reports.
    """
    acct: dict[str, str] = {}
    reason: dict[str, str] = {}
    for f in sorted(Path(recordings).glob("*.speakers.json")):
        stem = f.name[: -len(".speakers.json")]
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:                                   # noqa: BLE001
            reason[stem] = "unreadable roster"
            continue
        doms: Counter[str] = Counter()
        for s in data.get("speakers") or []:
            email = (s.get("email") or "").strip().lower()
            if "@" not in email:
                continue                                    # Avoma stores stubs like "db"
            dom = email.split("@", 1)[1]
            if dom == "joveo.com":
                continue
            doms[dom] += 1
        if doms:
            acct[stem] = doms.most_common(1)[0][0]
        else:
            reason[stem] = "no client email on the roster"
    return acct, reason


def phrase_tokens(keyword: str) -> tuple[str, ...]:
    """A c-TF-IDF keyword as its normalised token tuple. BERTopic runs ngram_range=(1,2),
    so ~40% of the top-3 keywords are bigrams and a unigram-only lookup misses all of them."""
    return tuple(_WORD.findall(keyword.lower()))


def keyword_turns(texts: list[str], keywords: list[str]) -> dict[str, list[int]]:
    """keyword -> indices of the turns containing it, phrases matched as token SEQUENCES.

    One sliding pass over the corpus restricted to the keywords actually asked for, rather
    than a scan per keyword: the wanted set is known up front because the adjudication
    artifact stores each cluster's keyword string.
    """
    wanted: dict[int, dict[tuple[str, ...], str]] = defaultdict(dict)
    for k in keywords:
        toks = phrase_tokens(k)
        if toks:
            wanted[len(toks)][toks] = k
    hits: dict[str, list[int]] = {k: [] for k in keywords}
    for i, t in enumerate(texts):
        ws = _WORD.findall(t.lower())
        for n, table in wanted.items():
            seen = set()
            for j in range(len(ws) - n + 1):
                g = tuple(ws[j:j + n])
                if g in table and g not in seen:
                    seen.add(g)
                    hits[table[g]].append(i)
    return hits


def keyword_pos_rates(docs, keywords: list[str]) -> tuple[dict[str, float], dict[str, float]]:
    """PROPN rate and mid-sentence capitalisation rate per keyword, phrases included.

    A phrase counts as PROPN on an occurrence when EVERY one of its tokens is tagged PROPN,
    which reduces to the unigram definition at n=1 rather than being a second rule. Same for
    capitalisation. `docs` is an iterable of spaCy Docs so the caller keeps ownership of the
    pipeline and of when the model is released.
    """
    lens = sorted({len(phrase_tokens(k)) for k in keywords if phrase_tokens(k)})
    table = {phrase_tokens(k): k for k in keywords if phrase_tokens(k)}
    propn_hit: Counter[str] = Counter()
    propn_tot: Counter[str] = Counter()
    cap_hit: Counter[str] = Counter()
    cap_tot: Counter[str] = Counter()
    for doc in docs:
        toks, prev_end = [], True
        for tok in doc:
            if not tok.is_alpha:
                prev_end = tok.text in ".!?"
                continue
            toks.append((tok.text.lower(), tok.pos_ == "PROPN",
                         tok.text[:1].isupper(), not prev_end))
            prev_end = False
        for n in lens:
            for j in range(len(toks) - n + 1):
                w = toks[j:j + n]
                k = table.get(tuple(x[0] for x in w))
                if k is None:
                    continue
                propn_tot[k] += 1
                if all(x[1] for x in w):
                    propn_hit[k] += 1
                if all(x[3] for x in w):        # mid-sentence: capitalisation is a signal
                    cap_tot[k] += 1
                    if all(x[2] for x in w):
                        cap_hit[k] += 1
    _MIN = 3
    return ({k: propn_hit[k] / propn_tot[k] for k in propn_tot if propn_tot[k] >= _MIN},
            {k: cap_hit[k] / cap_tot[k] for k in cap_tot if cap_tot[k] >= _MIN})


def concentration(labels: list[str]) -> tuple[str, float, int]:
    if not labels:
        return "", float("nan"), 0
    c = Counter(labels)
    top, n = c.most_common(1)[0]
    return top, n / len(labels), len(c)


def null_band(pool_labels: np.ndarray, size: int, rng, reps: int = NULL_REPS):
    """Top-account share for `reps` random draws of `size` turns from the same pool."""
    if size <= 0 or len(pool_labels) == 0:
        return float("nan"), float("nan")
    shares = np.empty(reps, dtype=np.float64)
    for r in range(reps):
        pick = pool_labels[rng.integers(0, len(pool_labels), size=size)]
        _, counts = np.unique(pick, return_counts=True)
        shares[r] = counts.max() / size
    return float(shares.mean()), float(np.percentile(shares, 99))


# -- report -----------------------------------------------------------------------------

def report(payload: dict, show: int) -> None:
    rows = payload["clusters"]
    coach = [r for r in rows if r["kind"] == "scenario"]
    unk = payload["turns_without_account"]

    print("\n" + "=" * 92)
    print("ACCOUNT CONCENTRATION OF THE TURN-MODE CLUSTERS")
    print("=" * 92)
    print(f"  {payload['n_calls_with_account']} of {payload['n_calls']} calls carry an "
          f"account ({payload['n_accounts']} distinct accounts)")
    print(f"  {unk['turns']}/{payload['n_turns']} turns ({unk['share']*100:.1f}%) come from "
          f"calls with no account and are excluded from every share below")
    print(f"  largest account by turns: {payload['largest_account']} at "
          f"{payload['largest_account_share']*100:.1f}% of the pool  <- the null prices this in")

    print("\n--- Signal A vs its size-matched null, by adjudicated kind ---")
    print(f"{'kind':<12}{'n':>5}{'top-acct share':>17}{'null mean':>11}{'lift':>8}"
          f"{'> null p99':>12}")
    for kind in ("scenario", "merged", "mechanics", "logistics"):
        sub = [r for r in rows if r["kind"] == kind]
        if not sub:
            continue
        obs = np.mean([r["top_account_share"] for r in sub])
        nul = np.mean([r["null_mean"] for r in sub])
        over = sum(1 for r in sub if r["exceeds_null_p99"])
        print(f"{kind:<12}{len(sub):>5}{obs:>16.1%}{nul:>11.1%}{obs-nul:>+8.1%}"
              f"{over:>7} ({over/len(sub)*100:>3.0f}%)")

    flagged = [r for r in coach if r["exceeds_null_p99"]]
    print("\n" + "=" * 92)
    print(f"THE 38 COACHABLE, RANKED BY ACCOUNT CONCENTRATION LIFT "
          f"({len(flagged)} exceed their own null's p99)")
    print("=" * 92)
    print(f"{'scenario_key':<46}{'turns':>6}{'cal':>4}{'top acct':>9}{'null':>7}"
          f"{'lift':>7}{'acc':>5}  top keywords")
    for r in sorted(coach, key=lambda x: -x["lift"]):
        mark = "!" if r["exceeds_null_p99"] else " "
        print(f"{mark}{r['scenario_key'][:45]:<45}{r['n_items']:>6}{r['calls']:>4}"
              f"{r['top_account_share']:>9.0%}{r['null_mean']:>7.0%}{r['lift']:>+7.0%}"
              f"{r['n_accounts']:>5}  {r['top_keywords_str'][:34]}")

    print("\n--- Signal B: the keyword that binds each flagged cluster ---")
    print(f"{'scenario_key':<40}{'account':<28}  keyword account-concentration")
    for r in sorted(flagged, key=lambda x: -x["lift"]):
        kws = ", ".join(f"{k}={v:.0%}" for k, v in r["keyword_account_share"].items())
        print(f"{r['scenario_key'][:39]:<39} {r['top_account'][:27]:<28}  {kws}")

    print("\n--- Signal C: proper-noun rate of those keywords (spaCy POS / capitalisation) ---")
    print(f"{'scenario_key':<40}{'propn':>8}{'capitalised':>13}   keywords tagged PROPN")
    for r in sorted(coach, key=lambda x: -x["propn_rate"])[:14]:
        tagged = ", ".join(k for k, v in r["keyword_propn"].items() if v >= 0.5) or "-"
        cap = r["cap_rate"]
        print(f"{r['scenario_key'][:39]:<39}{r['propn_rate']:>8.0%}"
              f"{cap:>13.0%}   {tagged[:34]}")

    print("\n" + "=" * 92)
    print(f"READ THESE -- {show} member turns from each flagged coachable cluster")
    print("=" * 92)
    for r in sorted(flagged, key=lambda x: -x["lift"]):
        print(f"\n[{r['scenario_key']}]  {r['n_items']} turns / {r['calls']} calls | "
              f"{r['top_account_share']:.0%} from {r['top_account']} "
              f"(null {r['null_mean']:.0%}) | kw: {r['top_keywords_str'][:40]}")
        print(f"   {r['business_description'][:150]}")
        for s in r["samples"][:show]:
            print(f"   - [{s['account'] or '?'}] {s['text'][:150]}")


def main() -> None:
    a = _args()
    if a.load:
        report(json.loads(OUT.read_text(encoding="utf-8-sig")), a.show)
        return

    from config import load_config
    from shared import cluster_evidence
    from shared.tuning import load_tuning
    from preprocessing.transcript_parser import parse_transcript, load_roster
    from v2.layer_a import build_client_pool, fit_topic_model
    from calibration.trial_pool_unit_gemini import embed_cached

    adj = json.loads(ADJUDICATION.read_text(encoding="utf-8-sig"))
    adj_rows = adj["rows"]
    print(f"joining against {ADJUDICATION.name}: {len(adj_rows)} adjudicated clusters")

    ta = load_tuning().layer_a
    cfg = load_config()

    # PRODUCTION ENTRY POINT, PRODUCTION ARGUMENTS. Two scratchpad scripts in this effort
    # disagreed with production by ~20% -- one loaded spaCy with components disabled (moving
    # sentence boundaries), one omitted the Avoma roster (misclassifying speakers). Both
    # inflated silently. This is the same call trial_adjudicate_gemini.py makes.
    turns = []
    for f in sorted(Path(a.recordings).glob("*.txt")):
        turns.extend(parse_transcript(str(f), cfg.joveo_speakers_lower,
                                      cfg.naren_name_lower, roster=load_roster(str(f))))
    texts, call_ids = build_client_pool(turns, unit="turn")
    total_calls = len(set(call_ids))
    print(f"{len(texts)} CLIENT turns over {total_calls} calls")

    acct, no_acct_reason = account_map(a.recordings)
    pool_acct = [acct.get(c) for c in call_ids]
    known = np.array([i for i, x in enumerate(pool_acct) if x])
    n_unknown = len(texts) - len(known)
    acct_counts = Counter(x for x in pool_acct if x)
    largest_acct, largest_n = acct_counts.most_common(1)[0]
    print(f"[account] {len(set(acct[c] for c in set(call_ids) if c in acct))} accounts over "
          f"{sum(1 for c in set(call_ids) if c in acct)} of {total_calls} calls; "
          f"{n_unknown} turns ({n_unknown/len(texts)*100:.1f}%) have no account")
    print(f"[account] largest is {largest_acct} at {largest_n/max(len(known),1)*100:.1f}% "
          f"of accounted turns")

    # --- Signal C, DELIBERATELY BEFORE THE UMAP FIT -------------------------------------
    # spaCy en_core_web_lg needs a CONTIGUOUS 392MiB vector table and this machine's
    # documented failure is address-space FRAGMENTATION, not exhaustion (it has failed at
    # 2.7GB free). Claiming that block while the heap is still clean, rather than after a
    # 24k x 3072 UMAP fit has churned it, is the cheap way not to find out.
    # The keywords are known BEFORE clustering because the adjudication artifact stores each
    # cluster's keyword string -- which is also what lets the POS pass stay ahead of the UMAP
    # fit while still scoring multiword keywords. Safe only because the position-verified join
    # below asserts these are byte-identical to the recomputed ones and exits if they are not.
    wanted_keywords = sorted({w.strip() for r in adj_rows
                              for w in r["keywords"].split(",")[:TOP_KEYWORDS] if w.strip()})
    n_multi = sum(1 for k in wanted_keywords if len(phrase_tokens(k)) > 1)
    print(f"[keywords] {len(wanted_keywords)} distinct top-{TOP_KEYWORDS} keywords, "
          f"{n_multi} multiword ({n_multi/max(len(wanted_keywords),1)*100:.0f}%) -- BERTopic "
          f"runs ngram_range=(1,2), so these must be matched as phrases")

    propn_rate: dict[str, float] = {}
    cap_rate: dict[str, float] = {}
    if not a.no_spacy:
        import spacy
        print("[pos] tagging the turn pool (parser/ner off -- no segmentation happens here, "
              "so this cannot touch Layer C's clause pool) ...", flush=True)
        nlp = spacy.load("en_core_web_lg", disable=["parser", "ner", "lemmatizer"])
        propn_rate, cap_rate = keyword_pos_rates(nlp.pipe(texts, batch_size=64),
                                                 wanted_keywords)
        rated = sum(1 for k in wanted_keywords if k in propn_rate)
        print(f"[pos] {rated}/{len(wanted_keywords)} keywords occur >=3 times and are rated; "
              f"{sum(1 for v in propn_rate.values() if v >= 0.5)} are PROPN in >=50% of "
              f"their occurrences")
        del nlp

    vecs = embed_cached(texts, workers=20)                  # fully cached: no requests
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)

    print(f"[cluster] min_cluster_size={MIN_CLUSTER_SIZE}, merge {MERGE} ...", flush=True)
    tm, topics = fit_topic_model(texts, vecs, min_cluster_size=MIN_CLUSTER_SIZE)
    topics = np.array(topics)
    members = defaultdict(list)
    for i, t in enumerate(topics):
        if t != -1:
            members[int(t)].append(i)
    raw_ids = sorted(members)
    cent = np.stack([cluster_evidence.support_stats(
        [call_ids[i] for i in members[t]], vecs[members[t]], total_calls).centroid
        for t in raw_ids])
    groups = cluster_evidence.merge_by_similarity(cent, MERGE)
    min_support = cluster_evidence.required_call_support(
        total_calls, ta.min_call_support_fraction, ta.min_call_support_floor)
    print(f"[cluster] {len(raw_ids)} raw -> {len(groups)} merged; support floor {min_support}")

    clusters = []
    for g in groups:
        tids = [raw_ids[x] for x in g]
        idxs = [i for t in tids for i in members[t]]
        st = cluster_evidence.support_stats([call_ids[i] for i in idxs], vecs[idxs],
                                            total_calls, texts=[texts[i] for i in idxs])
        if cluster_evidence.triage(st, min_support, ta.ubiquity_ceiling) == \
                cluster_evidence.INSUFFICIENT_EVIDENCE:
            continue
        lead = max(tids, key=lambda z: len(members[z]))
        clusters.append({"idxs": idxs, "n": st.n_items, "calls": st.distinct_calls,
                         "keywords": ", ".join(w for w, _ in tm.get_topic(lead)[:10])})
    clusters.sort(key=lambda c: c["n"], reverse=True)       # adjudication's own order

    # --- POSITION-VERIFIED JOIN. The adjudication artifact stores only `i`, so membership
    # can be re-attached only by reproducing the identical ordering. Verify it rather than
    # assume it: a silently misaligned join would attribute one cluster's turns to another
    # scenario's name and every number below would be fiction.
    if len(clusters) != len(adj_rows):
        raise SystemExit(f"JOIN FAILED: {len(clusters)} clusters vs {len(adj_rows)} rows. "
                         "Clustering did not reproduce; do not trust any downstream number.")
    bad = [i for i, (c, r) in enumerate(zip(clusters, adj_rows))
           if c["n"] != r["n_items"] or c["calls"] != r["calls"] or c["keywords"] != r["keywords"]]
    if bad:
        raise SystemExit(f"JOIN FAILED at {len(bad)} positions (first {bad[:5]}): "
                         "n_items/calls/keywords disagree with the adjudication artifact.")
    print(f"[join] verified position-for-position on n_items, calls and keywords "
          f"({len(clusters)}/{len(clusters)})")

    # --- Signal B setup: which turns each keyword appears in -------------------------------
    kw_turns = keyword_turns(texts, wanted_keywords)

    def keyword_account_share(word: str) -> float:
        """Share of accounted turns containing `word` that come from one account."""
        labs = [pool_acct[i] for i in kw_turns.get(word, ()) if pool_acct[i]]
        return concentration(labs)[1] if labs else float("nan")

    kw_cache: dict[str, float] = {}
    rng = np.random.default_rng(42)
    pool_labels = np.array([pool_acct[i] for i in known])

    out_rows = []
    print(f"\n[null] {NULL_REPS} size-matched draws per cluster ...", flush=True)
    for c, r in zip(clusters, adj_rows):
        labs = [pool_acct[i] for i in c["idxs"] if pool_acct[i]]
        top, share, n_acc = concentration(labs)
        nmean, np99 = null_band(pool_labels, len(labs), rng)
        kws = [w.strip() for w in c["keywords"].split(",")][:TOP_KEYWORDS]
        for w in kws:
            if w not in kw_cache:
                kw_cache[w] = keyword_account_share(w)
        kw_pr = {w: propn_rate.get(w, float("nan")) for w in kws}
        kw_cap = {w: cap_rate.get(w, float("nan")) for w in kws}
        finite_pr = [v for v in kw_pr.values() if v == v]
        finite_cap = [v for v in kw_cap.values() if v == v]
        samples = [{"text": " ".join(texts[i].split()),
                    "account": pool_acct[i], "call": call_ids[i]}
                   for i in c["idxs"][:40]]
        out_rows.append({
            "i": r["i"], "scenario_key": r["scenario_key"], "kind": r["kind"],
            "decision": r["decision"], "n_items": c["n"], "calls": c["calls"],
            "thin": r["thin"], "business_description": r["business_description"],
            "top_keywords_str": ", ".join(kws), "top_keywords": kws,
            "accounted_turns": len(labs),
            "top_account": top, "top_account_share": share, "n_accounts": n_acc,
            "null_mean": nmean, "null_p99": np99, "lift": share - nmean,
            "exceeds_null_p99": bool(share > np99),
            "keyword_account_share": {w: kw_cache[w] for w in kws},
            "keyword_propn": kw_pr, "keyword_cap": kw_cap,
            "propn_rate": float(np.mean(finite_pr)) if finite_pr else float("nan"),
            "cap_rate": float(np.mean(finite_cap)) if finite_cap else float("nan"),
            "samples": samples,
        })

    payload = {
        "merge": MERGE, "min_cluster_size": MIN_CLUSTER_SIZE, "null_reps": NULL_REPS,
        "top_keywords": TOP_KEYWORDS, "source": ADJUDICATION.name,
        "n_turns": len(texts), "n_calls": total_calls,
        "n_calls_with_account": sum(1 for c in set(call_ids) if c in acct),
        "n_accounts": len(set(acct[c] for c in set(call_ids) if c in acct)),
        "turns_without_account": {"turns": int(n_unknown),
                                  "share": float(n_unknown / len(texts))},
        "largest_account": largest_acct,
        "largest_account_share": float(largest_n / max(len(known), 1)),
        "calls_without_account": len(no_acct_reason),
        "clusters": out_rows,
    }
    OUT.write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    report(payload, a.show)
    print(f"\nwrote {OUT}")
    print("Zero chat calls, zero embedding requests, zero Postgres writes.")


if __name__ == "__main__":
    main()
