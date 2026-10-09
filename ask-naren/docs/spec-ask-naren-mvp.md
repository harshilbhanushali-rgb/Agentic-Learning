# Spec: Ask Naren MVP

## Problem Statement

A CSM facing a live, unfamiliar client situation has no fast way to find out how Naren — Joveo's most senior CSM — actually handled the closest comparable moment in his own real calls. The knowledge exists (Brain's pipeline has already mined and structured it), but it's locked inside a research pipeline with no CSM-facing surface: reaching it today means knowing the pipeline exists, knowing which scenario a situation maps to, and manually digging through transcripts or derived artifacts.

## Solution

A text-based internal tool where a CSM describes their situation in their own words and gets back a single grounded answer: Naren's closest real historical response, paraphrased and cited by the specific call it came from. If nothing in Naren's history is a close enough match, the tool says so rather than guessing. The tool answers using only the matched `kb_pair` (Brain's Layer B) — the empirical question of whether adding Layer C playbook context helps was evaluated and answered no (see `ask-naren/docs/adr/0001-layer-c-is-a-switch-not-a-default.md`), so the playbook-augmented variant stays built but off, not user-facing.

## User Stories

1. As a CSM, I want to type a description of a live client situation into a single input, so that I don't need to know Brain's internal scenario taxonomy to ask for help.
2. As a CSM, I want to receive one grounded answer paraphrasing Naren's closest real response, so that I get concrete, proven guidance rather than generic advice.
3. As a CSM, I want every answer to cite the specific real call it's paraphrasing (account/date, unredacted), so that I can verify the guidance against the source myself, per `ask-naren/docs/adr/0002-citations-are-unredacted.md`.
4. As a CSM, I want the tool to decline rather than answer when there's no close match to my situation, so that I never act on a confidently-wrong invented answer.
5. As a CSM, I want a response back within a few seconds of asking, so that I can use this mid-call or between calls without breaking my workflow.
6. As a CSM, I want the tool available as its own page in the CS platform, alongside Workspace and Library, so that it's part of my normal toolset rather than a separate system to remember.
7. As a CSM in either Veteran or Newbie mode, I want Ask Naren to behave identically, so that grounded guidance isn't gated behind a persona toggle that has nothing to do with this feature.
8. As a CSM, I want to ask a new, unrelated situation right after getting an answer, so that I can work through several live questions in a row without extra steps.
9. As a CS team lead, I want Ask Naren's retrieval restricted to the 34 scenarios Brain has classified as coachable, so that the tool never surfaces guidance rooted in backchannel/mechanics "sink" content that was never meant to be advice.
10. As a CS team lead, I want confidence that Ask Naren cannot write back into Brain's pipeline (scenarios, kb_pairs, playbooks), so that a CSM-facing tool can never corrupt the research pipeline's data.
11. As a Brain pipeline maintainer, I want Ask Naren to reuse the existing gateway client, embedder, and storage modules exactly as they are, so that retrieval and generation behavior stays identical to what was already validated in the prototype eval, with no second implementation to keep in sync.
12. As a Brain pipeline maintainer, I want the playbook-augmented prompt path to remain in the codebase behind an internal config flag (not deleted, not user-facing), so that Layer C's continued recalibration can be re-evaluated later without rebuilding the variant from scratch.
13. As a CSM, I want the answer's citation to show a human-readable account/call reference rather than a raw internal filename, so that the citation is actually meaningful to me, not an opaque identifier.
14. As a CSM, when Ask Naren declines, I want a plain explanation of why (no close match found) rather than a bare error, so that I understand it's a real "no match," not a broken tool.
15. As a CS team lead, I want it to be structurally impossible for Ask Naren to show an answer whose "verbatim quote" isn't actually verbatim in the cited response, so that the grounding guarantee in ADR 0002 is enforced at runtime, not just measured after the fact in an offline eval.
16. As a developer maintaining the CS platform, I want Ask Naren's backend to be a separate, independently testable service from the Next.js app, so that a change to retrieval/generation logic doesn't require touching or redeploying the frontend, and vice versa.
17. As a developer, I want the frontend's only responsibility to be rendering the question input and the answer/citation/decline states, so that all retrieval, grounding, and model-calling logic lives in one place (the Python service) rather than being duplicated across the stack.
18. As a CSM, I want to see a clear loading state while an answer is being generated, so that I know the tool is working and not frozen, given generation can take a few seconds.
19. As an engineer debugging a bad Ask Naren answer, I want the citation to be resolvable back to the exact `kb_pairs` row and `calls` row it came from, so that a wrong or confusing answer can be traced to its real source data.

## Implementation Decisions

**Two new modules, one new HTTP boundary.**

1. **A new Python HTTP service, added under `Brain/`.** It exposes one endpoint that accepts a CSM's free-text situation and returns a grounded answer or a decline. It is a thin orchestration layer over modules the prototype (`ask-naren/prototype/eval_pairs_vs_playbook.py`) already validated end-to-end — it does not reimplement retrieval, embedding, or generation, it calls the existing `shared.storage`, `shared.gateway`, and `preprocessing.embedder` modules directly, using the same read-only Postgres connection discipline the prototype and Brain's own calibration scripts already use. It never writes to Postgres — matches `CONTEXT-MAP.md`'s stated Ask Naren → Brain relationship.

2. **A new Next.js API route in `frontend/`** that proxies a request from the browser to the Python service and returns its response unchanged. This is the ONLY new frontend-side network seam; no retrieval/generation/DB logic lives in TypeScript. Keeps the browser same-origin (no CORS configuration needed) and keeps the Python service's location as an internal implementation detail.

3. **A new frontend page/route** (sibling to `/workspace`, `/library`, `/simulator`), added to `AppShell`'s nav item list the same way those three are. A single free-text input, a submit action, and three response states: answered (text + citation), declined (plain explanation), loading. Mode-agnostic — renders identically in Veteran and Newbie mode, since this is a utility tool, not a persona-branched dashboard like Workspace/Library.

**Retrieval.** Mirrors the prototype exactly: pull every `kb_pairs` row filed under a coachable (`is_coachable = true`) scenario, embed all of it via `preprocessing.embedder.embed_query_matrix` (which already resolves to the shipped `gateway`/`gemini-embedding-2`@3072 backend per `tuning.yaml`), and do the nearest-neighbour search as an in-memory cosine, not a live Pinecone query — `is_coachable` isn't in Pinecone's metadata, so the coachable-only restriction can't be expressed there (same reasoning `calibration/probe_retrieval_gate.py` and the prototype both already document). The coachable pool should be loaded and embedded once at service startup (or on a periodic refresh), not per request — embedding hits a warm gateway cache so this is cheap, but re-querying Postgres and recomputing ~6.5k-row cosine per request is unnecessary latency to pay on every question. The pool must be deduped on normalized (trigger, response) content before use — the prototype's second audit found the corpus contains a handful of transcripts ingested twice under different filenames, and an un-deduped pool risks a query matching its own content-duplicate.

**Generation.** Two prompt variants exist in code (mirroring the prototype's `_build_prompt`): pairs-only (ships as the default and the only one reachable from the UI) and playbook-augmented (kept behind an internal config flag, never exposed to the CSM — per the ADR 0001 result, it measured no benefit). Model config is the licensed one already used for Layer C's playbook backfill and Layer D's pairwise grader: `gemini-3.6-flash`, `reasoning_effort=medium`, called via `shared.gateway.GatewayClient.chat_json` with `no_cache=True` (the prototype's second audit found the gateway caches chat completions by default, which would silently serve stale answers to different CSMs asking similarly-worded questions).

**Runtime grounding contract, enforced, not just measured.** The model's JSON response carries `declined`, `answer`, `quote`, `cited_call` — the exact shape the prototype validated. In production this must be enforced at request time, not just scored offline: if `declined` is false, the service must verify `quote` is an actual verbatim substring of the cited `kb_pair`'s response text (the same check `_score`'s `quote_verbatim` does offline) before returning the answer to the CSM. If that check fails, the service does not show the unverified answer — it retries generation once, and if the retry also fails verification, it returns a decline rather than an ungrounded or unverifiable answer. This is what makes ADR 0002's "every answer cites the specific past call it paraphrases" a runtime guarantee rather than an eval-time statistic.

**Citation display.** The response must resolve to something more human-readable than a raw call filename before it reaches the CSM (an account name and a date, not a `calls.filename` string). The exact resolution method (parsing the filename convention vs. a dedicated lookup) is left to the implementer — see Further Notes.

## Testing Decisions

Tests should verify external behavior — given a situation, does the service return either (a) an answer with a citation that is verifiably grounded, or (b) a decline — never internal call counts or prompt string contents.

**Python service.** Follows Brain's existing test conventions (`pytest`, run via the root venv per `Brain/CLAUDE.md`). Retrieval logic is tested the way `tests/test_layer_b_assignment.py` and `tests/test_two_stage_matching.py` already test Layer B matching: hand-built vectors exercising the *rule* (nearest-neighbour selection, coachable-only filtering, dedup-before-search), not live embeddings. Generation and the runtime quote-verification gate are tested with a stubbed `GatewayClient` (no real API calls) returning fixed JSON payloads, including a case where the returned quote does NOT verify, to confirm the service retries and then declines rather than ever forwarding an unverified answer.

**Next.js proxy route.** A small integration test with the outbound call to the Python service mocked, confirming the route passes the situation through and returns the service's response shape unchanged, plus the error-path (service unreachable → a decline-shaped response, not a raw 500 the CSM would see as a broken page). `frontend/` currently has no test framework configured (`CLAUDE.md`: "No test framework is configured. `npm run build` is the type-check gate"); introducing one is its own decision and is out of scope here — if this spec's implementation needs to add one to write this test, that choice should be made explicitly at build time, not implied by this spec.

## Out of Scope

- Exposing the playbook-augmented variant as a user-facing toggle or A/B — ADR 0001's result found no benefit; it stays an internal, non-UI config flag only.
- Recalibrating the decline rate/threshold. The prototype observed a 24–50% decline rate across runs on real coachable-scenario situations; whether that's correctly conservative or too cautious for production is a real open question but not one this spec resolves — ship the validated prompt contract as-is and revisit with real usage data.
- Multi-turn conversation or follow-up questions. Ask Naren is single-shot: one situation in, one grounded answer or decline out — matching `CONTEXT.md`'s definition, with no notion of conversational memory.
- Any new authentication/access-control system. `frontend/` currently has no auth; Ask Naren inherits that boundary rather than introducing its own.
- Any admin UI for managing scenarios, kb_pairs, or playbooks — those are already Brain's `ops/` scripts and out of this tool's scope entirely.
- Introducing a frontend test framework (see Testing Decisions).
- Any write path from Ask Naren back into Brain's Postgres tables, under any circumstance.

## Further Notes

- The citation-display resolution (turning a call filename into an account name + date a CSM can actually read) is a real implementation gap this spec surfaces but doesn't close. A safe fallback for a first ship is to show the raw filename as-is (still technically "unredacted, verifiable" per ADR 0002) while a cleaner resolution is built.
- The eval that grounds this spec's "pairs-only by default" decision is prototype-scale (n=24–25 per run, ~12–17 paired). It answered "is there an effect large enough to see" (no), not "does an effect exist" (unknown) — see the Result section appended to ADR 0001. If Ask Naren's usage ever makes the playbook question load-bearing again, re-run with a larger sample rather than trusting this number indefinitely.
- Retrieval pool refresh cadence (how often the Python service reloads/re-embeds the coachable `kb_pairs` pool) should track how often Brain's own pipeline actually updates that data — likely infrequent, given Brain's pipeline runs are manual/batch, not continuous.
