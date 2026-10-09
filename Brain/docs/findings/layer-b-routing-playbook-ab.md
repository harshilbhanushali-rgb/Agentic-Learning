# Layer B — Three-Arm Routing A/B on the Playbook Yardstick (2026-08-19)

[Findings index](INDEX.md)

Spec: `docs/superpowers/specs/2026-08-19-routing-playbook-ab-design.md` (pre-registered
before any code; §12–§14 carry the audit findings and results).
Harnesses: `calibration/routing_playbook_ab.py` (76 tests),
`calibration/routing_playbook_ext.py` (39 tests). Artifacts `rt_*` / `rte_*`.
**Spend: 79 chat calls, ~1,050 embedding requests, zero Postgres writes during the trial.**

## Verdict: production routing STAYS `concat`. `keyphrases` is REFUTED. `r1` is UNRESOLVED.

The standing routing bar ("no routing change ships until an instrument can rank methods across
population shapes") was to fall only to a pre-registered playbook-yardstick win. No arm won.

### `keyphrases` — REFUTED, and it starves the map (the session's strongest result)

Routing every scenario on its keyphrases alone instead of `business_description + keyphrases`:

| | concat | keyphrases |
| --- | --- | --- |
| `application_volume_and_prioritization` routed pairs | 771 | **0** |
| coachable-routed pairs (of 12,444) | 6,528 | **4,872** |
| sink share | 47.5% | **60.9%** |

A **second** scenario also collapses to zero (`job_role_taxonomy_and_scoping`). The arm
ABORTED on an empty evidence pool for the map's largest scenario and could not produce a
document at all, so it never reached a blinded read. **Veto-audited (sonnet, independent):
the corpus was re-parsed from raw transcripts, all 12,444 pairs rebuilt, and production
`assign_scenarios` re-run under both registers — the control's numbers reproduced exactly on
all 34 coachable scenarios and the keyphrases numbers reproduced too.** Harness correctness
confirmed on every hypothesis: the register is applied to all 259 scenarios uniformly; **0 of
259 have empty keyphrases** so no silent concat fallback occurred; the cache is keyed on exact
text so no cross-register collision is possible; scenario vectors are non-degenerate under
both registers (pairwise cosine mean 0.670 concat vs 0.581 keyphrases, **zero** pairs ≥ 0.995).
Mechanism, traced on the actual 771 pairs: the scenario is never even in the top-6 candidates
under keyphrases — not narrowly beaten. 413 of the 771 (54%) fall to backchannel sinks and the
remaining 358 fragment across ~15 competitors with no single winner.

**THIS RECONCILES THE WITHDRAWN BENCH RATHER THAN CONTRADICTING IT.** `routing_bench` measured
keyphrases 42.1 vs concat 31.6 on a coherence-vs-null metric — the share of scenarios clearing
a bar. Shedding 61% of pairs to sinks leaves smaller, tighter populations that score BETTER on
exactly that metric while starving the evidence a playbook needs. **This is precisely the
discrimination the standing bar was waiting for, and it closes `scenario_vector_mode`.**

### `r1` (membership lookup + description fallback) — UNRESOLVED, not shipped

Blinded head-to-head vs control, 5 topics, 3 sonnet readers: **preferred in 3/5 (bar 4/5),
pooled 7–8, sign p = 1.000.** Mechanically verified before belief — side mapping confirmed by
locating each arm's unique quotes in the packet (9/9 in the correct block on the decisive
item), zero cross-arm citation leaks, tally hand-recomputed. G-F 5/5 both arms.

What r1 *does* deliver, and why it still was not shipped:

- **Sink share falls** 48.1% → 43.0% (old) and 47.3% → 43.6% (new): ~5pp more evidence
  reaching coachable scenarios.
- **But its documents are measurably thinner.** Across 11 topics on the same 50-pair budget:
  **46 moves / 84 surviving quotes (control) vs 41 / 66 (r1).** A move requires the same
  behaviour appearing ≥ 2 times, so r1's selections support fewer *recurring* behaviours — its
  evidence sets hang together less well.
- **It is 71% control by construction.** `union_base` is the UN-rescued clustering: memberships
  cover **23,770 of 58,002 turns (41.0%)**, and only **29.0% of pair triggers** carry a label.
  Of the 3,604 it does resolve, **41% point at a sink**. So membership genuinely decides ~17%
  of pairs. (§0.9 of the spec pre-registered ~41% and was WRONG — that is the pool share, not
  the trigger share.)
- **The +5pp coverage is the exact signal that sank r1 at F4** (`layer-b-redesign.md`): "Layer C
  responds to routing VOLUME, not routing QUALITY", where a volume-matched **random** placebo
  produced 112 milestones to r1's 126 and scored *better*.
- Production cost: r1 needs the positional turn→pool join rebuilt over all 58,002 turns every
  run, aborting on parse drift.

**A FAIR TEST OF MEMBERSHIP ROUTING DOES NOT EXIST ON THIS SUBSTRATE, AND THAT IS THE REAL
FINDING.** r1 needs a clustering that labels most of the pool; the rescued clustering does
(37,672/58,002 = 64.9%) but FAILED the blinded coherence gate 8/12 and is closed for the
fourth time. Base passes coherence and starves the lookup. So this is a dead end, not an
unfinished experiment — do not re-run r1 here expecting a different answer.

## THE BLINDED-READ INSTRUMENT IS THE BINDING CONSTRAINT, NOT ROUTING

Three independent confounds, all measured, all pointing the same way:

1. **Position bias.** Readers answered "A" on **12 of 15** routing votes (80%) and 20 of 27
   pair items. r1 held A on 2 topics and B on 3 — so *pure position answering predicts r1 6 –
   control 9* against the **7–8 observed.** The read may have measured side, not content.
2. **Move-count channel.** Both original topics where move counts differed went **unanimously
   to the arm with more moves** (`landing_page` 4v3 → r1 3/3; `downstream` 3v4 → control 3/3);
   the three move-count-tied topics split messily. Control holds more moves on 5 of 11 topics.
   The four frozen G-P calibration pairs carry the same channel: real-vs-placebo move counts
   are 4v3 on two and 4v4 on two, and the two separable ones are exactly the two placed
   real-on-A — so "prefer the longer document, tie-break B" scores **4 of 4 without reading**.
3. **Boilerplate.** ~1 generic move per document (a near-identical "phased rollout" move
   appeared in 2 of 3 audited documents). Arm-independent, so it dilutes any real difference.

**Power, computed not asserted:** at 5 topics / 3 readers a 5/5 bar has **~17%** power if r1
truly wins 70% of topics; at 11 topics / 3 readers, **~28%**. Readers are correlated draws from
ONE model (measured pairwise agreement 0.733), so raw vote counts overstate information — the
naive sign test's true type-I error is near **0.16**, not 0.05, and E1 therefore gates its
verdict on a design-effect-adjusted p. **A tie from this instrument means UNRESOLVED, never
"routing does not matter."**

**The designed-but-unbuilt fix** (spec §14.7): give each reader their own packet with sides
assigned independently, so position bias cancels within each topic AND measures itself — two
readers seeing one topic in opposite orders who both answer "A" are provably answering
position. Zero chat cost; all 22 existing documents are reusable.

## E1 — the widened re-test: BUILT, PAID FOR, UNREAD

11 topics (the original 5 + 6 chosen by a frozen rule ranked on the CONTROL's counts), 12 new
documents, **G-F 6/6 both arms, zero bad quotes**. 47 chat calls. **No packet was ever read** —
the operator paused the read to fix the instrument first. Pre-registered and still binding if
it is ever read: the pooled 33-vote correlation-adjusted sign test is PRIMARY, the topic count
is secondary, and §14.1b's G-D-restricted 9-topic subset is a declared diagnostic, never a
second chance at a win. **2 of the 6 new topics fell below the divergence bar** (8/50 pairs
changed, Jaccard 0.724) and were deliberately NOT dropped — narrowing a frozen topic set after
seeing which topics misbehave is exactly the manipulation the design exists to prevent, and the
dilution is conservative.

## `sink_margin_delta` — the one routing lever the evidence endorses, now BUILT at a no-op

`accept a coachable scenario iff best_coachable − best_sink >= delta`, added to
`shared/relative_match.flat_pick` and `tuning.yaml` at **0.0**, which is byte-identical to the
shipped rule (proven by 400 randomized cases). The measured top1–top2 gap is ~0.01, so
near-ties are the NORM and every near-tie currently resolves in favour of the junk bin. From
the PR curve over 80 blind-judged turns: **delta = −0.0117 buys +5.1pp recall for −2.6pp
precision**, against a centroid swap's +4.0pp for **−14.0pp**. **DO NOT set a non-zero value
without sweeping it against a judged sample larger than 80 turns.**
**Incomplete:** `v1.layer_b.assign_scenarios` has its own inline copy of the pick logic and
never calls `flat_pick`, so the knob is currently **inert on the primary path**.

## Correction to a recorded claim (union-taxonomy-rebuild.md)

That file records `gemini-3.5-flash` at `reasoning_effort=low` as **fixing** flash-lite's
1-quote-move schema failures. **Too strong.** The mechanism is structural — the model reaches
for a move it can evidence only once — and it recurred **twice in 12 documents** on flash-low
with the pilot prompt, on healthy 373- and 205-pair topics, not just thin incoherent ones.

```
PV  (flash-lite → flash-low, 3 prompt states): 100 attempts / 10 docs = 10.0 per doc
today (flash-low, pilot prompt throughout):     47 attempts / 12 docs =  3.9 per doc
```

A real 2.5× improvement, **not immunity.** Diagnosed exactly by per-move shape logging:
`n_ev=1` on an over-reached move, twice; on the second the model emitted 3 moves instead of 4
on retry and passed. The topic supports ~4 moves and the schema's 3–6 range invites a fifth —
**both arms over-reach**, the control merely scraped 2 quotes together where r1 found 1.

**Consequences for the playbook scale-up:** budget **~3.9 calls/document, not 3** (≈130 calls
for 34 scenarios, not ~102); expect ~1 in 6 documents to need a retry; and expect a tail of
scenarios too shallow to reach the 3-move floor at all, which **no retry budget can rescue**.
Recommend pre-registering an exclusion rule (a scenario failing to produce 3 evidenced moves in
N attempts is excluded and reported), capping attempts at **2** (the third bought nothing on
either failure), and shipping the per-move diagnostic — without it both failures were
unreadable, and PV burned ~38 attempts on that same blindness.

## Methodology lessons worth keeping

- **Four harness defects, and the pattern is instructive: the gate arithmetic was right every
  time; the summary lines and the plumbing around the gates were not.** G-P was satisfiable by
  answering "A" (all four calibration pairs landed real-on-A because `CAL_RANKS = (1,3,5)` are
  all odd); a VOID packet still named a winner; `arms_cleared_to_spend` listed a disqualified
  arm; a re-dispatched VOID re-scored the *discarded* readers.
- **Two audits and one run catch different classes of bug.** Two blind code audits read the
  line `taxonomy_sha != taxonomy_sha` and neither flagged it, because comparing a taxonomy hash
  across arms looks obviously right. It is wrong only if you know `taxonomy_sha` hashes
  `scenario_text()` and is therefore **register-dependent** — a fact two files away. Running
  the keyphrases arm surfaced it in seconds. **Use `routing_playbook_ab.taxonomy_identity_sha`
  for any cross-arm identity check.**
- **Write down the cheapest strategy that passes a gate without doing the work.** For G-P that
  is "always answer A" and "prefer the longer document" — the first was the FATAL, the second
  is a residual that could not be closed. Five minutes of that arithmetic would have caught
  both before a line of code.
- **Design the measurement carefully AND the instrument check carefully.** Every gate that
  decides whether the answer is *correct* held on the first pass. Every defect was in the gates
  that decide whether the answer is *believable*, built from leftovers because they were free.
