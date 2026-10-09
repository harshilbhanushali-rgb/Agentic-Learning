# HANDOFF — the gradability arm is LIVE; the QUALITY INSTRUMENT is the thing that needs fixing

Supersedes `HANDOFF_LAYER_C_BACKFILLED_2026-08-20.md` (executed). Full record:
`docs/findings/layer-c-playbook-schema-and-gateway.md` **§13**. Narrative:
`PROBLEMS_AND_FIXES.md` (last section). Production facts: **`Brain/CLAUDE.md`**. Traps:
`docs/GOTCHAS.md`.

**Spend this session: ZERO chat calls.** Everything came from artifacts already on disk, the
free verifiers, and blind reads. Zero published artifacts overwritten.

## 0. STATE (verified this session, not assumed)

1. **Layer A live** — 259 scenarios, 34 coachable. **Layer B COMPLETE** — 12,444 `kb_pairs`.
   `config_reproduces_live.py`: **12,444/12,444** identical, sink share 47.5%.
   `gateway_backend_check.py`: 300/300 from cache with the transport **disabled**.
2. **LAYER C: 33 of 34 scenarios live. 65 rows — 33 live / 22 trial / 5 placebo / 5 superseded.**
   All seven loader gates green. `contract_and_legal_review` is still the only gap.
3. **The live 33 are `pbq_36flash_medium_grad_snapped` (5) + `pbf_rest` (25) + `pbf_thin` (3).**
   The 5 pbv originals are `superseded` — retained, invisible to production reads.
4. **PB1 is retired as a gate; G-Q4 is diagnostic; G-Q7 (replacement must beat incumbent) added.**
5. **`ship_union_taxonomy.py` is now genuinely one transaction.** It was not, for five days.
6. **Full suite: 69 files, 1,501 tests, zero failures**, after fixing 4 permanently-red ones.

## 1. THE ONE THING TO READ BEFORE TOUCHING ANY QUALITY NUMBER

**A blind-read `usable%` / `gradable%` is a property of the INSTRUMENT, not the documents.**
Measured twice, from two directions, same day:

| what varied | population | result |
| --- | --- | --- |
| reader framing (lenient vs strict) | the SAME 123 live criteria | **84% then 17%** |
| packet composition | the SAME 59 relevance-arm quotes | **95% then 78%** |

The framing pair also **INVERTED the cohort ranking** — the original 5 came out worst under one
framing and best under the other, and every replace/re-run decision had been resting on that
ordering.

**THE RULE: run every arm you want to compare INSIDE ONE PACKET, counterbalanced, one reader.
Report contrasts, never levels. Never compare a number from one audit to a number from another.**

The "reproducible to ~3pt" claim on record is **retracted** — it rested on one 81%/84% pair.
§11.3's headline "a 5-doc probe said 95%, 28 docs said 73%, so probes overestimate by 22pt" is
**partly the instrument, not the sample**; a retraction is stamped inline there. The direction is
probably still right. The magnitude was never measured.

## 2. WHAT THE CLEAN COMPARISON SAYS

Within one packet, counterbalanced — the only valid contrast available:

| arm | quotes | SUPPORTS | WEAK | FAILS | usable |
| --- | --- | --- | --- | --- | --- |
| + relevance rule | 59 | 46 | 12 | 1 | 78% |
| **+ gradability rule** | 56 | 50 | 6 | **0** | **89%** |

**Gradability won 4 of 5 situations.** It is NOT a trade: narrower criteria made the quotes fit
better. **This is the counter-example to §12's "every rule costs a sixth thing"** — that pattern
is real but not a law, and a rule that reduces scope can pay for itself.

Production, measured deterministically before/after the promotion
(`calibration/playbook_gradability_census.py`):

| | before | after |
| --- | --- | --- |
| banned adjectives, promoted cohort | 15% | **0%** |
| single-account, ALL LIVE | 10% | **9%** |
| quotes>=3, ALL LIVE | 82% | **93%** |

## 3. THE BINDING CONSTRAINT IS NOW **BUNDLING**, AND IT HAS NEVER BEEN MEASURED

Ungradability has **two causes that pull opposite ways**:

- **evaluative vagueness** — "clearly explain the business impact". No anchor.
- **bundling** — "name the exact tracking columns AND walk through drop-off analysis". Two
  demands in one criterion, so partial performance has no defined answer.

The lenient reader rewarded concrete nouns (long criteria win); the strict reader punished
compound demands (the same criteria lose). That is the whole 84/17 gap.

**Why it matters more than the vagueness half.** Layer D's shipped `checks` arm asks a strictly
binary `performed: true/false` per move and requires a verbatim quote (`partial` is produced only
by the `pairwise` arm). So a bundled criterion there does **not** cause grader disagreement — it
causes **HIT INFLATION**, because the grader anchors its mandatory quote on the easiest clause.
A silent failure in the flattering direction.

**Nobody has measured bundling in the 94 backfill moves, and an atomicity rule ("one criterion =
one checkable demand") has never been probed.** That is the obvious next lever and it is cheap:
the 5 originals have frozen evidence, so a probe is ~15 calls on `quote_floor_ab.py --tag atom`.
Per §12 and §13.3, measure what it costs as well as what it buys.

## 4. OPEN DECISIONS — bring these, do not decide them

- **Roll the gradability config across the other 28?** NOT licensed today: it fails G-Q1 at
  census scale (11% single-account). ~85 calls. I recommend probing atomicity first (§3).
- **Probe the atomicity rule** (~15 calls, frozen evidence, one packet with the grad arm)?
- **The 3 thin documents stay live** on your instruction — 22% single-account, `uber.com` in 8 of
  9 moves. Revisit or leave.
- **`contract_and_legal_review`** — 25 pairs, collapsed at 2 moves against a floor of 3. Corpus
  work or permanent exclusion. Not a retry.
- **The quote judge** — needs a FRESH labelling pass first; the "236 labelled quotes" do not
  exist (§5). This project has closed two judges as failures.
- **The schema gap (§9 of the old handoff) is smaller than it looked.** `pitfalls_and_variants`
  is fully populated — 73 entries, 2.3/doc, zero empties — but holds **anti-patterns from the
  CSM's side** ("Failing to clearly explain boolean logic…"), not objection branches. Only 3 of
  73 carry any client-pushback cue. So the gap is a missing **response side**, possibly a PROMPT
  change rather than a schema change — but the 3/73 rate also confirms the evidence rarely
  contains objections at all, so the corpus is still the ceiling.
- **`storage.upsert_playbook` still commits per row**, so `load_playbooks.py` is not atomic.
  Low risk (deletes nothing, idempotent). Fix or accept.

## 5. TWO PREMISES OF THE LAST HANDOFF WERE WRONG — check before budgeting

1. **The ~15-call re-run of the 5 originals was ALREADY PAID FOR.** Three arms sat in
   `artifacts/`: `pbq_36flash_medium_*`, `*_relev_*`, `*_grad_*` — all 5 scenarios, snapped, none
   collapsed. The `grad` artifact is stamped `2026-08-24T00:01:54`, i.e. the "probe in flight" had
   long finished. **`quote_floor_ab.py --report` re-scores any of them for free.**
2. **The "236 labelled quotes that now exist" DO NOT EXIST.** Only aggregates survive in prose;
   the per-quote labels lived in a conversation and were never persisted. **Persist per-item
   labels, not just the aggregate** — both new harnesses do.

## 6. MACHINERY (reuse, do not re-implement)

- `calibration/playbook_gradability_census.py` **(new, zero spend)** — censuses every criterion
  in every live playbook: deterministic banned-adjective **floor** (declared a floor, not the
  rate), single-account/PB1/quote-floor by cohort, thin-band concentration, `--packet` to build a
  blind packet with the key in a separate file, `--dump` for per-item records.
- `calibration/pbg_score_blind_read.py` **(new, zero spend)** — joins a read to the key,
  **REFUSES a partial read**, prints the deterministic-vs-blind confusion.
- `calibration/quote_floor_ab.py` — the paired A/B rig. **`--report` is free.** Each
  (model, effort, tag) writes its OWN artifact set. G-Q1 is now single-account; G-Q4/PB1 are
  diagnostics; G-Q7 is the replacement test. **A pass here is not comparable to a pre-2026-08-24
  pass** — the docstring says so explicitly.
- `ops/load_playbooks.py` — dry-run default, seven gates, `assert_snapped()`, auto-excludes
  `schema_collapsed`. **A PROMOTION IS DECLARATIVE**: flip the incumbent's arm to `superseded`,
  add the replacement as `live`. **ARTIFACT_PLAN ORDER IS LOAD-BEARING** — the demoting entry must
  precede its replacement or `idx_playbooks_one_live` refuses the write. Two tests pin it.
- `calibration/playbook_backfill.py`, `playbook_backfill_scope.py`,
  `config_reproduces_live.py`, `gateway_backend_check.py`, `gemini_cosine_bands.py`,
  `sink_margin_delta_identity.py` — unchanged.

## 7. HOUSE RULES + NEW TRAPS

Frozen gates pre-registered before code; ONE blind code audit per new harness before it spends;
subagents ONE AT A TIME (readers on sonnet); `no_cache=True` on every chat call; VPN for the
gateway; long runs via `ops/run_visible.ps1` with an **explicit `-Log`**; logs are UTF-16;
pytest file-by-file; never overwrite a published artifact; **a null is a real result**; at any
gate failure STOP and bring fallback options. **Say what you are about to do in plain words
before changing files.**

New traps, both in `docs/GOTCHAS.md`:

- **A blind-read rate is not comparable across packets or framings** (§1 above).
- **A hardcoded status list hid 5 documents from the dry run.** The plan printed
  `for status in ("live","placebo","trial")`; the promotion added `superseded`, so a summary
  totalling 60 printed under a "PLAN 65 documents" header. Every gate passed — the bug was in
  the display, i.e. in the thing a human approves. Now iterates the statuses present and asserts
  the summary accounts for every document.
- **A rate bar needs enough n to be evaluable.** The 10% single-account ceiling was calibrated on
  123 moves; on an 18-move probe the achievable values are 0%, 5.6%, 11.1%, so "11% vs 10%" is
  one move. Do NOT lower a bar to fit a result (the capped-`need` anti-pattern §9 reverted) — add
  a relative gate instead, and print both verdicts separately.
- **Heredocs through the Bash tool broke twice** on quoting, silently writing nothing. Write the
  file with the Write tool and `cat` it in.
- **The Bash tool's cwd reset twice mid-session.** Absolute paths, always.
