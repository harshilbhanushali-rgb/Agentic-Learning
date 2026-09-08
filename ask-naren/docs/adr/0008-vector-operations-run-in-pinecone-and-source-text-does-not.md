# Ask Naren's vector operations run in Pinecone, and its source text does not

Ask Naren's retrieval was entirely in-process. At startup it read ~6,496 coachable `kb_pairs` from Postgres, sent every trigger text to the gateway to be embedded, and held the resulting 6,496 × 3,072 float32 matrix in memory — about 80 MB — searching it with a numpy dot product and an `argsort`. Nothing durable was read: the vectors were re-derived on every boot.

That is what blocked deployment. Ask Naren serves one situation at a time (ADR 0003), so deployment means several processes behind an ingress, and every process paid the full startup — measured at ~1 minute, and only that fast because a local embedding cache was warm. On a fresh host with an empty cache the same startup becomes thousands of requests against a rate-limited gateway.

We decided to **move every vector operation into Pinecone's existing `narens-brain-3072` index, and to leave the source text where it is** — in the pool read once from Postgres at startup, through a connection Postgres refuses to write through, closed before the first situation is served.

The governing shape is **Pinecone ranks; the retrieval pool authorises and supplies the text.** Pinecone returns ranked `(pair_id, cosine)`. Each identifier is resolved through the pool's identifier map in rank order, and anything the pool does not hold is skipped.

## What moved, and what did not

| Operation | Before | After |
| --- | --- | --- |
| Embedding the 6,496 pool triggers | service, at startup | **nowhere** — the vectors are already stored |
| Unit-normalising the pool matrix | service, numpy | Pinecone (`metric: cosine`) |
| The 6,496 × 3,072 dot product | service, numpy | Pinecone |
| Ranking (`argsort`) | service, numpy | Pinecone |
| Restricting to coachable scenarios | service, filtered at pool build | Pinecone (`scenario_key $in [34]`), then re-checked by the pool |
| The reported cosine | service, computed locally | Pinecone's returned score |
| Trigger and response text, and the citation | Postgres pool row | **unchanged — Postgres pool row** |

No vector arithmetic remains in the request path. numpy leaves it entirely.

## The measurements this rests on, all taken 2026-09-08

Three facts were unverified when this was proposed, and each one could have changed the decision. They were checked first, by read-only probes.

| Question | Answer |
| --- | --- |
| Is the index the right width? | The configured `narens-brain` is **768** — the bge era. But **`narens-brain-3072` already exists** at 3072/cosine and `ops/ship_layer_b.py` upserts trigger vectors into it. **No index is created.** |
| Is a Postgres vector extension available? | `vector 0.8.6` is available on the Neon instance but **not installed**; only `plpgsql` is. The connecting role is not a superuser. No vector, array or `bytea` column exists in `public`. |
| Does the `triggers` namespace hold the coachable pool? | **6,496 / 6,496** present. The namespace holds 12,444 in total; of 300 sampled non-pool rows, **0** carried a coachable scenario key. |

And the number that made this a change of *place* rather than of *behaviour*:

**`cosine(stored vector, freshly embedded trigger) = 1.000000 on 24 of 24 pairs`**, exact to 1e-6. Layer B upserted the same gateway embeddings the service re-derives.

### But the query is approximate, and an earlier draft of this ADR overstated it

That spot check says the stored *values* are exact. It does **not** say the search is, and a first version of this ADR wrongly concluded that "reading them back cannot move an answer."

Querying the index with one of its own stored unit vectors returns that record at scores between **0.999321 and 1.00135**. A cosine of a unit vector with itself is exactly 1, and nothing above 1 is a cosine at all — so scores come from a **quantized ANN representation**, not exact arithmetic. Fetched values, by contrast, have norm 1.00000 and reproduce cos = 1.00000000 against themselves. The approximation is ~1.5e-3, it is inherent to a serverless vector index, and it is not a defect to be fixed.

Measured over 47 real situations (`ask-naren/audit/equivalence_vector_store.py`), ranking the whole pool both ways:

| | Result |
| --- | --- |
| Same top-ranked `kb_pair` | **47 / 47 (100%)** |
| Identical top-5 ordering | 37 / 47 (79%) |
| Cosine \|delta\| on shared ranks | max 1.62e-3, mean 3.67e-4 |
| Rank-1 margin, exact arm | p50 = 0.165, p10 = 0.0035, min = 0.00090 |
| **Situations whose rank-1 margin is below the ~1.5e-3 error** | **3 / 47 (6.4%)** |

Read those last two rows honestly. All ten shortlist differences are near-ties — six are the same five pairs reordered, four differ only in the fifth slot, and every swap point has a gap of ≤5.2e-4, *smaller than the error itself*. Nothing consumes that order: shipped candidate selection is 1 (ADR 0005). But the last row is the real exposure: in about 6% of situations the top two exchanges are closer together than the approximation's error, so the approximation **could** pick the other one. None of the 47 did.

We accepted this, for a reason that is itself a measurement rather than a shrug: ADR 0005 found retrieval cosine does not separate right answers from wrong ones (0.809 against 0.798, with every floor tested doing net harm). When two exchanges sit within 1e-3 of each other, which one is chosen is not a quality-relevant decision by this project's own instrument. What would change that judgement is evidence that near-tie situations answer worse — which no instrument here has, and which would be a finding about retrieval, not about the store.

The reported `match.cosine` is clamped into [-1, 1], because that field is documented as a real cosine and handing a caller 1.00135 would be handing them a number that cannot exist. The clamp bounds the range; it does not hide the error, which the harness characterises.

| Timing | Result |
| --- | --- |
| Pinecone query, unfiltered | **221 ms** median |
| Pinecone query, `scenario_key $in [34 coachable]` | **218 ms** median — the restriction is free |
| Fetching all 6,496 vectors out of Pinecone | **~168 s** (25.9 s per 1,000) |

### The startup claim, corrected

An earlier draft of this ADR said cold start goes "from ~60 s to ~4.5 s, a 13× improvement." **That is wrong on a developer machine, and the phase breakdown shows why.**

| Phase | Measured |
| --- | --- |
| `connect_read_only` | 0.6–1.2 s |
| `load_coachable_pairs` (6,496 rows, 34 queries to Neon) | **3.9 s / 7.3 s / 13.0 s across runs** |
| Embedding 6,496 triggers, **warm local SQLite cache** | 0.4–4.2 s |
| Coverage guard, 1,000 ids | 1.7–3.5 s |

Startup is **dominated by the Postgres read**, which this change does not touch and which varies by 3× run to run. Against that, embedding the pool off a warm machine-local cache is nearly free — so on this box the in-memory path starts *as fast or faster* than the Pinecone path, because the Pinecone path pays a coverage guard the other one does not.

The honest comparison depends entirely on whether that machine-local cache is warm:

| Scenario | In-memory path | Pinecone path |
| --- | --- | --- |
| Dev box, warm local embed cache | Postgres + ~1–4 s | Postgres + ~2–3.5 s guard |
| **Fresh deployment host, empty cache** | Postgres + **6,496 gateway requests** (recorded at ~1 minute in a prior session, against a rate-limited endpoint) | Postgres + ~2–3.5 s guard, **unchanged** |

So the startup win is real but it is **specific to a fresh host**, which is precisely the deployment case — a new process on a new machine has no warm cache, and N processes across hosts each need their own. The unconditional wins, true on every machine, are the two that do not depend on cache state at all:

- **Resident vectors: 79.8 MB → 0**, measured.
- **No dependence on a warm machine-local SQLite cache**, which is what makes N processes on fresh hosts an ordinary decision rather than a rate-limit incident.

Do not quote a 13× cold-start figure. The defensible claim is "removes 80 MB per process and removes the corpus embedding from startup entirely"; the time saved is whatever 6,496 gateway round trips would have cost on the host in question.

## A claim in the code that was wrong, and is now corrected

`ask_naren/retrieval.py` justified the in-memory search like this:

> `is_coachable` is not in Pinecone's metadata, so the coachable-only restriction **cannot be expressed there at all.**

The first clause is true and the conclusion does not follow. Coachability is a property of a *scenario*, and `scenario_key` **is** in the metadata — so the restriction is expressible as `scenario_key $in [the coachable keys]`, at no measurable cost. The docstring is corrected rather than left as a rationale for a decision it no longer supports.

The predicate itself did not move. The list of coachable keys still comes from `shared.relative_match.is_sink_flags`, Brain's one definition of a sink, read from Postgres at startup. The filter is *populated from* that list, so no second definition of "sink" is written into metadata.

## Why the metadata filter is an optimisation and the pool is the authority

Two correctness gates exist today, and neither is expressible in Pinecone:

**Content dedup.** The corpus holds transcripts ingested twice under two `calls.filename` values — 32 duplicate pairs across 15 scenarios, byte-identical. `retrieval.dedupe_pairs` drops them at pool build. Both `pair_id`s are in Pinecone and both carry coachable scenario keys, so the filter admits them and only the pool rejects them. Without the post-filter, two identical exchanges compete as separate neighbours for one situation.

**Authorisation.** Pinecone holds whatever the pipeline shipped, which is 1.92× the pool.

So the post-filter is the mechanism, not a safety net. A hit Pinecone ranks but the pool does not hold is skipped, and the search over-fetches so that skipping cannot starve the result.

## Why not a vector extension on Brain's Postgres

It is the more elegant end state — one store, with `is_coachable` and content dedup both expressible in SQL — and we rejected it for now.

Querying it per situation requires **a live handle on Brain's Postgres while answering**. Ask Naren's central guarantee is not that it is read-only; it is that it holds no handle at all, so it *cannot* write to Brain's pipeline. A per-situation `ORDER BY trigger_vec <=> $1` does not weaken that guarantee, it deletes it — and it is the same property that forced `answer_situation` to take a `moves_for` function instead of doing a lookup. Pinecone does not have this problem because it is not Brain's Postgres.

Secondary, and each one sufficient on its own to defer: the extension is not installed and the role is not a superuser, so enabling it is a change to the pipeline's production database; the shared schema file is a pipeline artefact; and backfilling would need the vectors, which cost ~168 s to extract.

**Revisit trigger, stated so this is deferred rather than forgotten:** reconsider only if operating two stores causes *measured* pain, and only after the no-database-handle guarantee has been explicitly renegotiated with the operator. Not before.

## Why not keep the search in memory and store the vectors durably

This was the honest alternative reading of "put the vectors in a database", and a measurement killed it: extracting 6,496 vectors from Pinecone takes **~168 s**, which is worse than the ~60 s of embedding it would replace. There is no version of "fetch at startup, search locally" that is cheaper than what it replaces.

## Consequences, including the unpleasant ones

**A new hard dependency in the request path.** Ask Naren cannot answer while Pinecone is unreachable, where previously it could. The request path already required the gateway for the situation's embedding and for generation, so this goes from one external dependency to two rather than from zero to one — but it is a new way to be down. Mitigated by a module-level rollback constant that selects the in-memory store, a code edit beside `PLAYBOOK_AUGMENTED` and for that switch's stated reason: an environment variable can be set by accident on a restart.

**A free operation became a paid one.** ~220 ms per situation against an answer that takes ~12.5 s — about 1.8%, dominated by generation. This is a real trade and it was made deliberately: it buys a ~13× faster cold start, zero resident vectors, and no corpus embedding on any deploy or restart. Do not reverse it on the grounds that the search "used to be free" without also pricing the startup.

**A second staleness mode exists, and a presence-only guard misses it entirely.** Found by a code audit after the first implementation, and it is the more dangerous of the two.

The search filters on `scenario_key`. The pool's copy of that key is read **live from Postgres** at startup; the index's copy was written **at vector-ship time**. Two pipeline scripts move it in Postgres with no re-upsert and no re-embed:

- `response_taxonomy_auto_pass.py` — `UPDATE kb_pairs SET scenario_key = …`
- `calibration/graduate_sink_topics.py` — the same, its docstring saying "No re-embedding, no re-clustering"

Both **graduate a sink into a coachable scenario**, which is exactly the movement `retrieval.coachable_scenario_keys` already warns happens between runs. After either runs, the rerouted pairs enter the pool under their new coachable key while their index records still carry the old sink key — so the filter excludes them and they become invisible to every situation. The records are unambiguously *present*, so a guard that checks only `pair_id` presence reports **full coverage** while a whole scenario is unretrievable.

Measured on 2026-09-08 across the entire pool: **0 of 6,496 drifted.** So this is latent today, not live. The guard now checks both conditions and separates them:

| Condition | Verdict |
| --- | --- |
| No record for the `pair_id` | **fatal** — refuse to serve (confirmed by an exact `fetch` first, so an ANN false alarm cannot down a healthy index) |
| Indexed `scenario_key` not admitted by the filter | **fatal** — refuse to serve |
| Indexed `scenario_key` differs but is still admitted | **warn** — still retrievable; the pool decides the scenario an answer reports |

Checking the key costs nothing: the metadata is already in the response the presence check reads.

**Staleness became possible, and is guarded.** The pool is derived from Postgres at every boot, so it was never stale. Retrieval now also depends on Layer B having upserted trigger vectors for every coachable pair. A pipeline run that writes `kb_pairs` to Postgres before upserting their vectors leaves those pairs **permanently unretrievable** — a silent quality regression, which is the worst failure shape available here. So startup samples pool identifiers against the store and refuses to serve on any shortfall, and `ops/check_vector_coverage.py` does the full 6,496 check after a layer ships. Enumerating all identifiers takes ~29 s, which is why the full check is an operations script and not a startup step.

**Concurrency is unblocked but not solved.** ADR 0003 stands: the per-situation query embedding still writes through the thread-bound SQLite cache, so threading remains unsafe. What a 4.5 s cold start buys is that *N separate processes* becomes an ordinary decision — each owns its own connection, so ADR 0003 never arises — without editing `shared/`, which the pipeline also uses.

**The pipeline is untouched.** No index created, no upsert, no schema change, no `tuning.yaml` change, no Brain table written. The change to `shared/pinecone_store.py` is purely additive, so every existing caller is unaffected by construction. The legacy 768 index is left in place for the pipeline's own rollback.

## What this closes, and what it does not

Closed: the store choice, and the two alternatives, each on a measurement rather than a preference. **Do not re-propose "search in memory from a durable store" (~168 s) or a per-situation Postgres vector query (deletes the no-handle guarantee) without new evidence.**

Not closed, and explicitly not this decision: making the service multi-threaded, or skipping the disk cache for the situation's own embedding — a smaller fix that would make threading safe but edits a module the pipeline shares. Also untouched: authentication, VPN reachability, secret handling, observability, and ADR 0002's internal-only citation scope. Each is a real deployment blocker; none is this ADR.

Nothing here touches answer quality. Candidate selection stays at 1, no retrieval floor is introduced, and no matching strategy changes — all three were measured and rejected in ADR 0005.
