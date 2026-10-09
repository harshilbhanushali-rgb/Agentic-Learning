# Skills vocabulary — do 405 milestone axes fold into a profile? (2026-08-13)

**Status: pre-registered, not yet run.** Every threshold, control and stopping condition below
is fixed before a single Gemma call is spent. Companion to
`2026-08-12-layer-c-profile-rebuild-design.md` §5, which sketched this test; this document is
the runnable pre-registration, and it corrects three things §5 got wrong:

1. §5.1 names `cross_scenario_coverage` as the figure that lets the approach "fail honestly".
   It cannot fail — coarsening drives it to 1.0 by construction (§3.1).
2. §5.1 proposes discrimination-per-skill as the counterweight, which needs a full scoring run,
   not ~41 calls. Merge validity is substituted as the cheap signal that degrades with
   over-merging (§3).
3. §5 reasons in `K`, the skill count, which assumes observations spread evenly across skills.
   They will not, so the operative gate is the **median skill's member count** (§3.3).

## 1. The question

**Do the 405 milestone descriptions fold into few enough behavioural skills to carry a
per-person profile, without fusing distinct coaching moves?**

The profile today has 405 axes at roughly 8 observations each. That is arithmetic, not a
quality problem, and no improvement in criterion wording repairs it. Every measurement failure
recorded on 2026-08-12 traces back to it: a ±0.05 decision band sitting at a third the size of
its own noise, per-scenario verdicts agreeing 41–47% across runs, per-milestone gates tripping
on one stray partial hit.

### 1.1 Why this survives the trial's negative verdict

The four-arm trial closed negative — no arm reached `W(unrelated) < 0.5 × W(matched)`, and
pre-registered stopping condition #1 fired: criteria-based scoring is not achievable on this
corpus. This test is **not downstream of that result**, for two reasons:

- What makes a criterion a bad grader — being too generic to identify its own situation — is
  exactly what makes a good **skill label**. The trial's failure mode is this test's raw
  material.
- Any scoring mechanism that ever replaces criteria, head-to-head comparison included, still
  needs **axes to report on**. A profile with 405 thin axes is unusable regardless of how the
  observations are produced.

## 2. Pipeline

```text
milestone descriptions
   |-- [control] embed as-written ------------+
   \-- abstract (Gemma, batch 10) -> embed ---+-> sweep threshold -> K(t), V(t) -> window
```

| step | mechanism | cost |
| --- | --- | --- |
| abstract | `PROMPT_SKILL_ABSTRACT_BATCH` (`shared/prompts.py`), batch **10** | 41 calls at full scale |
| embed | `embedder.embed_document_matrix` | free, local, cached |
| cluster | `shared/skills.py::cluster_behaviours`, swept 0.50→0.95 step 0.025 (19 points) | free, pure numpy |
| measure | `shared/skills.py::sweep` + the new merge-validity judge | ~15 calls |

`shared/skills.py` is used **unchanged**. Batch size 10, not 20: `ops/rewrite_milestone_criteria.py`
measured one batch in 21 returning truncated JSON at 20, leaving those items unprocessed.
Truncation is the binding constraint here, not request count.

Embedding uses `embed_document`, not `embed_query`: this is a symmetric behaviour-to-behaviour
comparison, the same convention `shared/scenario_vectors.py` uses. The cache is keyed on the
prefix, so choosing the wrong one silently yields a different vector population.

## 3. The window

Two curves over one threshold axis. They constrain from opposite sides, and **the test is
whether the window between them is non-empty.**

- **`K(t)`** — skills produced at threshold `t`. Sets the **lower bound on coarseness**: too
  many axes and none has enough observations.
- **`V(t)`** — merge validity, the fraction of sampled groups a batched judge calls a single
  coaching move. Sets the **upper bound on coarseness**: it degrades as groups fuse distinct
  moves.

**PASS at bound B** iff some `t` satisfies `K(t) <= B` **and** `V(t) >= V_min`.

`V` is measured at only four thresholds — those where `K` crosses each bound, plus one much
finer point as a positive control — so `t` ranges over the judged thresholds, not all 19. That
is ~12–15 judge calls instead of ~60. The four operative bounds are **K <= 11, 17, 18 and 35**;
35 is the loosest, so "no window at any bound" means `V < V_min` everywhere `K <= 35`.

### 3.1 Why the counterweight is mandatory

`sweep`'s docstring names `cross_scenario_coverage` as the load-bearing figure and claims the
approach "fails honestly" if it stays near zero at every threshold. **It cannot stay near
zero.** As `t` falls, every item merges into one group and coverage goes to 1.0 by
construction. Nothing in the sweep gets worse as you over-merge, so the sweep alone always
says yes at *some* granularity.

This is the same defect class as the merge-blind `_match_milestones`, which scored three
baseline milestones collapsing into one 532-clause blob as three clean matches because it only
counted the good outcome. `V(t)` is the missing bad outcome.

### 3.2 The lower bound is derived, never chosen

No target count. `MAX_CLUSTERS=150` is the cautionary tale — a count halts at N whether
duplication remains or not. The skill count is an **output**; what is fixed in advance is the
*statistical requirement*, and the bound follows from measured values.

Measured inputs, all from this repo:

- **889 attempts across 237 milestones** — one CSM's Layer D run over 19 transcripts.
- **±0.006 weighted** — the noise floor from two identical runs (`arm3_run1_20260810` vs
  `arm3_run2_noisefloor_20260811`).
- **+0.02 weighted** — the smallest change measurable at this sample size.

**Derivation A — quantization.** `W = (hits + 0.5*partials)/attempts` moves in steps of
`1/(2n)`. Require the step to be no coarser than the target:

| standard | step <= | n per axis | max K |
| --- | --- | --- | --- |
| 1 · step <= noise band | 0.006 | 83 | **~11** |
| 2 · step <= half a measurable change | 0.010 | 50 | **~18** |
| 3 · step <= a measurable change | 0.020 | 25 | **~35** |

**Derivation B — ranking.** If the profile's job is "which skills is this person weakest at",
the requirement is resolving a difference between two noisy estimates, not representing one.
Grounded in the empirical band rather than a theoretical standard error, since mixing the two
would be apples-to-oranges: noise scales as `1/sqrt(n)`, and `n = 889/K`, so a per-axis band is
`0.006 * sqrt(K)`. To rank two skills whose true scores differ by delta, require that band <= delta/2:

| delta | max K | |
| --- | --- | --- |
| 0.025 | ~4 | sensitivity only |
| **0.05** (a plausible coaching difference) | **~17** | **the operative bound** |
| 0.10 | ~69 | sensitivity only |

Only delta = 0.05 is a bound; the other two rows show how hard the requirement bites if the
coaching difference worth detecting turns out smaller or larger. They are reported, not gated
on.

**Standards 2 and 4 converge on K ≈ 17–18 by two independent routes.** That is better support
than either derivation alone, and it is why no single bound is privileged: all four are
reported, and selecting one afterwards needs no re-run — the same property as Layer C's
`(percentile, fraction)` grid.

### 3.3 K is an optimistic bound; the median skill is the operative test

Every figure above assumes observations distribute evenly across skills. **They will not.** A
skill absorbing 40 milestones and one absorbing 2 both count toward `K` while only the first
can carry an axis.

So the harness reports the **member-count distribution** and evaluates the requirement against
the **median** skill, not against `K`. Attempts distribute over milestones at roughly
`889/405 ≈ 2.20` per milestone, giving `observations ≈ 2.20 * member_milestones`:

| standard | median skill needs >= N member milestones |
| --- | --- |
| 1 · noise band | 38 |
| 2 · half a measurable change | 23 |
| 3 · a measurable change | 12 |
| 4 · rank at delta = 0.05 | 24 |

With 405 items a median of 38 members implies K ≈ 11 under an even split, so the two framings
agree where the assumption holds — but the
member-count form survives an uneven distribution and the `K` form does not. **The member-count
row is the gate; `K` is the headline.**

Caveats recorded now: 889 attempts is one CSM over one roster, so the constant moves with the
roster while the shape does not; and ±0.006 is empirical, including grader nondeterminism as
well as sampling, so `1/sqrt(n)` scaling is an approximation rather than an identity.

## 4. Controls

Four, all pre-registered, three of them free.

| control | what it protects against | fails if |
| --- | --- | --- |
| **as-written sweep** | crediting the abstraction pass for a curve it did not cause | abstracted ≈ as-written |
| **judge null, blinded** | a rubber-stamp judge | rejects < 80% of disguised distinct pairs |
| **mechanics positive control** | an abstraction pass that is not abstracting | mechanics items do not collapse |
| **order permutation** | a vocabulary that reshuffles between runs | median abs(delta K) > 20% over 5 shuffles |

**As-written sweep.** Same items, same thresholds, no abstraction pass. This is
`arm0r_legacy_regen`'s lesson applied in advance: the trial's `arm0_baseline` varied prompt,
clustering and model at once and produced a number nobody could attribute. It also **repairs
the prior negative result** — "290 of 338 clusters held a single scenario" was measured at a
single threshold, and 338 groups from 405 items means roughly 1.2 items per group, which is a
symptom of a very high threshold rather than proof of topic dominance. The prior result may be
confounded by threshold choice; the control curve settles it.

**Judge null.** Two judges have now failed their own nulls here — the applicability judge at
1.22 : 1, and the coverage judge at 64.9% vs 65.7%. The merge-validity judge is therefore
nulled before it is trusted: bottom-decile-cosine pairs are **disguised as groups and mixed
into the same batches** as real groups, so the judge cannot tell which is which. A judge that
calls maximally-dissimilar behaviours the same move is broken, and the run reports that instead
of a granularity.

**Prompt discipline.** The judge returns **an explicit verdict on every group, never a returned
subset.** That is the generalising lesson recorded from the objective function's failure: the
prompt instructed sparsity, and "return a subset" invites picking a top few and stopping.

**Order permutation.** `cluster_behaviours` is greedy nearest-centroid and order-dependent by
its own docstring. Five shuffles, free. This is stopping condition #3 of the parent design
(§6.6) measured directly rather than assumed.

## 5. Pre-registered thresholds — inherited vs invented

Stating which is which, because §6.1 of the parent design earned its credibility by inheriting
its gate rather than inventing one.

| value | source |
| --- | --- |
| batch size 10 | **inherited** — `rewrite_milestone_criteria.py`, truncation-measured |
| ±0.006 noise band | **inherited** — measured, two identical runs |
| +0.02 measurable change | **inherited** — measured |
| 889 attempts / 405 milestones | **inherited** — live Layer D run |
| judge null rejection >= 80% | **invented** |
| **`V_min = 0.80`** | **invented** — the one number with no precedent |
| order stability abs(delta K) <= 20% | **invented** |
| sweep range 0.50–0.95 | **invented**, but cheap to widen — the sweep is free |
| delta = 0.05 coaching difference | **invented** |

`V_min = 0.80` means one skill in five may fuse distinct moves. There is no direct precedent
for it: `by_cluster` was rejected at 8 merged of 385, which is far stricter, but that was
protecting an existing baseline from damage rather than admitting a new vocabulary.

## 6. Staging

**Stage 1 — pilot, 91 items, no Postgres.** The 91 baseline descriptions already in
`artifacts/trial_final.json`: ~10 abstraction + ~12 judge ≈ **22 calls**. Exercises every path
end to end. Gemma calls obviously need the network; what stage 1 avoids is the database, which
is also what makes it immune to the neon DNS block.

**The pilot cannot open the window, by construction.** The member floors in §3.3 are derived
from 889 attempts over the full 405 milestones; 91 milestones carry roughly 22% of those
observations, so a median-38 skill is unreachable at pilot scale. The floors are deliberately
**not** rescaled to fit — a bound moved to fit the run it is judging is not a bound. Stage 1
validates the paths and the four controls; only stage 2 can return a window verdict, and the
report prints this caveat rather than leaving the number to be misread.

This is the smoke test whose absence killed two launches on 2026-08-13, both on defects
`py_compile` cannot catch — a missing import and a positional slice over a reordered tuple.
`score_naren_ceiling.py` already had exactly this in `--max-items-per-arm`.

The pilot population is **not** an alphabetical prefix: it comes from the trial's seeded
stratified sample (seed 20260812) and is **8 client-posture / 12 subject-matter across 20
scenarios**, 1–9 milestones each. Composition is printed in the report header, and the report
shouts if a stratum is empty.

**Stage 2 — full 405.** Via `ops/run_visible.ps1 -Script calibration/trial_skills.py
-HostAddr 18.138.49.39 -ScriptArgs '--run --out artifacts/skills_trial.json'` — `-ScriptArgs`
must be ONE STRING, because `-File` does not preserve array syntax. neon.tech DNS is refused on
this network while TCP 5432 works, which is what the `-HostAddr` bypass exists for.
~41 abstraction + ~15 judge ≈ **56 calls**. Runs only if stage 1's curves are sane.

Total ≈ **78 calls**.

## 7. Zero writes — enforced, not promised

- Connection opened via `score_naren_ceiling._connect_read_only`, which issues
  `SET SESSION default_transaction_read_only = on`, so a stray write fails at Postgres rather
  than relying on care.
- Output is `artifacts/skills_trial.json`, with `--load PATH` to re-report at zero cost.
- **No skill vocabulary is frozen this run.** §5.3 is right that one must eventually exist or
  every profile is orphaned by the next Layer C run — but freezing one before the window is
  known would be picking a granularity by hand, which is the failure this whole design exists
  to avoid.
- Every stage flushes to disk as it completes. One scored run previously lost all 95 LLM
  results because a free DB lookup gated the persistence of expensive work; never let a free
  operation gate an expensive one's persistence.

## 8. Stopping conditions

1. **Judge fails its null** → no valid counterweight. Report that; claim no granularity.
2. **Abstracted curve ≈ as-written curve** → the abstraction pass is inert, topic-dominance was
   the wrong diagnosis, and the prior negative stands on repaired evidence.
3. **Window empty at every bound** (`V < V_min` wherever `K <= 35`) → behavioural skills do not
   exist at usable granularity on this corpus. **Profile-by-skills is not buildable.** That is
   a real answer, not a failure to tune, and it is decision-relevant either way.
4. **Order permutation unstable** → report; a vocabulary that reshuffles cannot carry a profile
   however well it groups once.

Reading the groups is non-negotiable at whichever threshold the window opens. `merge_cosine_threshold`
was chosen by reading what each threshold fused, not by counting: at 0.80 it fused campaigns,
sales teams, brands, markets and vendors while the count still looked reasonable.

## 9. Files

| file | change |
| --- | --- |
| `calibration/trial_skills.py` | new — the harness |
| `shared/prompts.py` | add `PROMPT_SKILL_MERGE_VALIDITY_BATCH` |
| `tests/test_skills.py` | extend — window computation, null-pair selection, permutation |
| `shared/skills.py` | **unchanged** |

Pure helpers (window computation, null-pair selection, member-count evaluation) live where they
can be unit-tested without Gemma or a DB, the same split `shared/cluster_evidence.py` and
`shared/topic_grouping.py` already follow.

## 10. Verification

- `--load` replays the artifact with zero calls, so every number is re-derivable.
- New pure helpers get tests before the harness runs.
- Stage 1 gates stage 2. No full run without a clean pilot.
- Run tests file-by-file: the suite is unreliable in one process on 16GB Windows because four
  files each load spaCy's 392MiB contiguous vector table.

## 11. Honest prior

**Somewhat better than even** — better than the arms' even odds, on two grounds. The mechanism
is arithmetic (pooling observations) rather than persuasion (getting a model to grade well),
and the target behaviour is already visible by eye in the 91: *"propose a starting point for
technical discovery"*, *"propose a simplified initial implementation… before scaling"* and
*"propose specific points for deeper analysis or future follow-up"* sit in three different
scenarios and are arguably one move.

The risk is not that behaviours fail to repeat. It is that `V` collapses before `K` gets under
~18 — that the moves which genuinely recur are so generic ("asks a question", "proposes a next
step") that pooling them produces axes too coarse to coach against. That would be the current
failure in a new form, and it is what the two-sided window is built to detect rather than
explain away.

Recorded now so it cannot be revised afterwards.
