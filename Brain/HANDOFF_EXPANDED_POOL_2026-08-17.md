# HANDOFF — expanded-pool stage 1 + Layer C clustering bench (2026-08-17, evening)

Continue-from-here after: (a) the Layer C filter/rescue trial CLOSED both its directions
(read `docs/superpowers/specs/2026-08-17-layer-c-relative-filter-and-rescue-design.md` §7
and `...-layer-c-retargeted-followups-design.md` RESULTS), and (b) a 4-year Naren pull was
fetched, filtered and staged. `CLAUDE.md`'s two 2026-08-17 sections and
`Brain/PROBLEMS_AND_FIXES.md`'s last two sections are the compressed record. Operator
context: prefers NEW harnesses over extending old ones; placebo-veto rule (any unexpected
placebo result gets a subagent audit of code + output before being believed); minimal
subagents otherwise (1 blind audit per new harness + independent blinded readers only).

## 1. WHERE THINGS STAND

- **Methods are exhausted; data was the constraint; the data now exists.** Every Layer B/C
  mechanism tried this week closed with pre-registered nulls or capped gains. The one
  never-benched stage is Layer C's clusterer itself, which discards ~42% of its
  post-relevance pool at CONTENT PARITY (26.3% vs 27.3% content-free).
- **The pull:** 4,650 meetings swept (2022-08 → 2026-08), 1,197 Naren-speaking transcripts
  in quarantine `recordings_pull_4yr/` (0 fetch failures, manifest complete). After the
  full contamination funnel (interviews 12, internal 78, phantom 5, overlap 412):
  **690 KEEP calls staged in `recordings_pull_keep/`** with roster sidecars.
  **120 NEW client accounts** (appvault 17, springhealth 16, cielotalent 16, angi 13...),
  +36,978 client turns (existing corpus: 20,788). Full numbers:
  `artifacts/naren_pull_audit.json` (audit script `calibration/audit_naren_pull.py`).
- **recordings/ (the curated 393) was NEVER touched.** Do not promote anything into it —
  that is the operator's decision, gated on stage 1's result.
- **Embedding warm was IN PROGRESS at handoff time** —
  `calibration/scope_layer_bc_embeddings.py --recordings recordings_pull_keep --fetch`
  (log `logs/fetch_pull_keep_embeddings.log`; scope said 58,618 clauses + 8,467 triggers +
  33,373 turn-pool = ~92k effective). **FIRST ACTION: check whether it finished; if not,
  re-run the same command — it skips cached texts and resumes.** Gateway requires the
  Joveo VPN (symptom when off: DNS resolves, TCP times out).

## 2. THE TWO TASKS (both pre-registered BEFORE running, per house rules)

### Stage 1 — the data effect ("was data the constraint?")

Incumbent Layer C (UMAP+HDBSCAN, production functions, p40 filter) on UNION pools:
existing taxonomy `clean2_base` frozen (26 coachable + 125 sinks), pairs = production
`extract_pairs` over BOTH `recordings/` and `recordings_pull_keep/`, routing = production
`assign_scenarios` (r0). New calls only JOIN existing scenarios; they never create any.

- Build on `calibration/lcfr_common.py` (audited CLEAN today; `load_substrate` needs a
  two-directory variant — parse each dir with `parse_corpus`, concat pairs; stems don't
  collide). Artifacts in the `layer_bc_lcfr_*`/new naming so `score_layer_b_arms.py`
  scores them unchanged.
- **F0-union (mandatory validity gate):** restricting the union arm's per-scenario
  PREFILTER pools to old-corpus calls must reproduce the published control's pools
  byte-for-byte (routing of old pairs is deterministic and cache-served, so any diff is a
  harness bug). Nothing is reportable if this fails.
- **Readouts:** (i) routing of new pairs — sink share, absorption, how many new
  calls/accounts reach each scenario (if new pairs overwhelmingly sink, STOP: the new
  corpus may talk about things the taxonomy doesn't know; that changes the plan);
  (ii) gained/lost/merged milestone accounting vs the published control, with gains
  classified by whether the qualifying calls come from NEW accounts (honest) or repeat
  accounts (padding); (iii) the rev-4 account-diversity paired sign test vs control —
  **nothing has EVER moved this metric; if it moves up, data was the constraint and
  promotion is justified**; (iv) support_frac distributions and the 33 failing clusters'
  fate. Remember the placebo lesson: perturbing a pool at all costs ~6 milestones to UMAP
  re-partitioning — read counts against that floor, and report DIRECTION of flips.

### Stage 2 — the Layer C clustering-method bench (runs REGARDLESS of stage 1's verdict)

Stage 1's run IS the bench's control arm (incumbent on union pools). Arms on the SAME
union pools, gates frozen first: agglomerative cosine, Leiden k-NN (no noise class;
γ scale-matched — its range cannot be guessed, see the Layer A bench notes), HDBSCAN
`min_cluster_size` sweep (never swept at Layer C), raw-space vs UMAP-space, plus ONE
labeled `incumbent + rescue_centroid` arm with volume-matched placebo — re-testable ONLY
because today's closure ("the noise pool does not contain the failing clusters' content")
is a property of the OLD corpus and the corpus changed. A winner must clear ALL of:
noise rate down, `merged` ≤ placebo's (the merge-blind trap), account lift not degraded
(paired sign test), blinded coherence read won (independent reader, scrambled negatives +
positive controls — expect the positive control to be imperfect: ~half of high-support
milestones are incoherent today), and stability across UMAP seeds {42, 1, 7} where the
arm inherits UMAP (F5 lesson: inherited randomness counts).

### Phase 3 — reopen Layer B against the fixed ruler (operator-endorsed, sequenced LAST)

The operator explicitly wants Layer B's discards revisited ONCE Layer C is fixed, and the
record supports it: **every Layer B null this week is conditional on a downstream detector
that was proven blind** (F10 = "Layer C responds to volume, not quality" — a verdict about
the detector, not the defendant). When a stage-2 winner makes Layer C quality-sensitive,
those nulls expire in this order:

1. **Re-run `r1`** (route by the turn's own Layer A cluster label). Already built
   (`calibration/layer_b_routers.py`), already repairs the +62%→+0.8% break (+39% clauses,
   lookup 45.9%→72.8%); it lost ONLY to a blind judge. One day's work against the new ruler.
2. **The sink short-circuit** — ~40–58% of pairs filed to sinks, ~half of a read sample
   genuinely coachable. Eight per-pair signals failed; retry only WITH a quality-sensitive
   Layer C as the outcome measure, never against AUC proxies again.
3. **S2 (teammate speech, 25.4% of the corpus)** — needs the operator's brainstorm first;
   it changes what a rubric IS (`ego_trap` wrote Deferred_To_Teammate on the opposite premise).

Do NOT start phase 3 before a stage-2 winner exists: improving Layer B recall now would
pour more evidence into a clusterer that discards 42% at content parity, which is the
exact trap the week's nulls were bought to avoid.

### Afterwards (operator decisions, not yours)

Promotion of the 690 into production (full re-run, new run_id, real Gemma spend);
taxonomy rebuild on the ~1,083-call corpus (Layer A rescue_centroid becomes the leading
pre-registered candidate there); Layer D re-grade as the final judge.

## 3. NON-NEGOTIABLES (unchanged, all re-earned this week)

Pre-register gates before running; a metric that is an arm's objective cannot rank arms;
placebos match what the arm ADDS (permutation for routing-shaped changes) with invariants
asserted in code; report flip DIRECTION never a rate; symmetric filtering (diff the
filtered lists per arm); import production code, never paraphrase (F0-style equivalence
checks); one blind subagent audit per new harness, strict bar; read real samples before
believing any aggregate (the unit of reading for a modifying rule is the MODIFICATION);
`no_cache=True` on any gateway chat A/B; never write to Postgres; never overwrite a
published artifact; artifacts carry started_at/pid/seed/tuning/shas. Everything is
gemini@3072 on the turn-mode taxonomy — no `tuning.yaml` change may cite these numbers.

## 4. WHERE THINGS LIVE

| | |
| --- | --- |
| `recordings_pull_4yr/` | full 1,197-call quarantine + `_manifest.json` (subjects/dates) |
| `recordings_pull_keep/` | the 690 KEEP calls + sidecars — stage 1/2's second corpus dir |
| `artifacts/naren_pull_audit.json` | funnel verdicts per call + diversity tables |
| `artifacts/pull_keep_embed_scope.json` | the embedding bill; re-run with --fetch to resume |
| `ops/fetch_naren_4yr.py` | the puller (lenient old-data validation, net retries) |
| `calibration/lcfr_common.py` | audited substrate: pass1_lcfr, rules, rescue, placebo |
| `calibration/score_layer_b_arms.py` | rev-4 scorer, works on any `layer_bc_*` artifact |
| `calibration/layer_bc_arms.py` match_milestones | the merge-aware milestone accounting |
| `calibration/blind_read_powered.py` | blind-read builder with controls |
| today's specs | `2026-08-17-layer-c-relative-filter-and-rescue-design.md` + `-retargeted-followups-` |

24 unit tests from today: `tests/test_layer_c_filter_rescue.py`, `tests/test_lcfr_followups.py`.
Run suites file-by-file (documented spaCy OOM on this box).

## 5. THE ASK

Run stage 1, read it hard (especially the routing of new pairs and WHERE the new accounts
land), then the bench. A null on stage 1 is a real result — it would say the clusterer
eats evidence faster than data can supply it, which raises the bench's stakes. Update
CLAUDE.md / PROBLEMS_AND_FIXES.md / the new spec as you go, and leave your own handoff.
