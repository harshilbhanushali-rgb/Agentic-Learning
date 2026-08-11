# Giving Layer C an objective function: validate every milestone before it can be scored against

**Date:** 2026-08-11
**Status:** design proposed, NOT approved, nothing implemented
**Deliverable:** `Brain/calibration/validate_rubrics.py` + one `tuning.yaml` key + a per-milestone
`validation` object inside `rubrics.milestones` (no DDL)
**Depends on:** `2026-08-11-naren-ceiling-measurement-design.md` — every number quoted here comes
from that run's artifact, `Brain/artifacts/naren_ceiling.json`

---

## 1. The problem, stated precisely

Layer C decides whether a milestone survives using three gates:

| gate | what it measures |
| --- | --- |
| distinct-call support | does this **recur**? |
| relevance percentile (p40) | is this **on-topic**? |
| the review-flag batch judge | is this **plausible**? |

Nothing anywhere measures the two properties that turned out to matter:

- **discrimination** — can this criterion tell its own scenario apart from a different one?
- **satisfiability** — can anyone actually satisfy it when the moment calls for it?

So Layer C produces criteria that recur and are on-topic, because that is what it was asked for.
**It is working as specified; the specification was incomplete.** That is the root cause behind
four consecutive fixes each moving the hit rate slightly and none breaking 4%: every fix improved
something nobody was measuring, against a target nobody had defined.

The ceiling run measured what those two properties actually look like today:

- **Discrimination:** globally `W(A3) 0.114` vs an unrelated-rubric control at `W(B) 0.090`
  (same-model subset) — a signal-to-null ratio of 1.27 : 1. Per scenario it is **bimodal**: 16 of
  40 discriminate clearly, **7 invert** (the unrelated rubric scores *higher*), and 7 have a
  control score of exactly 0.000.
- **Satisfiability:** 66% of milestones (154/235) are never fully hit by the expert whose corpus
  produced them; 28% get zero full **and** zero partial.
- The two are **independent** (r = −0.038 between subject-naming and the discrimination gap), so
  they need separate measurement, not one combined score.

## 2. What this design does, and what it explicitly does not

**Does:** measure discrimination and satisfiability **per milestone**, store the verdict on the
milestone, and let Layer D refuse to score against a milestone that failed. That closes the
feedback loop which has never existed.

**Does not:**

- **Not** a new describe prompt. Fixing the wording is a separate change, and this spec is what
  would let anyone tell whether such a fix worked. Sequencing matters: build the ruler first.
- **Not** a Layer C re-run. UMAP+HDBSCAN is not reproducible across process launches
  (385/398/403/404 milestones for byte-identical input), so re-running to add validation would
  change the milestone set the validation describes. Annotate in place instead — the same
  reasoning `ops/rewrite_milestone_criteria.py` used.
- **Not** a fix for posture scenarios. For those, no discriminating criterion exists to be found;
  this design will *detect* that and mark them, which is the honest outcome, but replacing the
  unit of feedback is its own question.
- **Not** a `ubiquity_ceiling` for milestones. Measured: `correlation(support_calls, W) = −0.019`,
  buckets flat. Support is uninformative about hittability, so gating on it would be wasted work.

## 3. Design

### 3.1 Three numbers per milestone, not one

The ceiling run's arms become the instrument, run per milestone rather than per corpus:

| number | how it is measured | what it means |
| --- | --- | --- |
| `discrimination` | `W(A3) − W(B)`, both **unconditional** so the denominators match | does the criterion tell scenarios apart? |
| `satisfiability` | `W(A3)` over **applicable** instances only | can it be satisfied when the moment calls for it? |
| `applicable_rate` | fraction of A3 instances where the move was called for | how contingent is this milestone? |

Reusing the ceiling harness's definitions exactly:

- **A3** — expert responses filed under the scenario as a *secondary* label whose call
  contributed **zero** primary pairs, so nothing from that call wrote the criterion. Benchmark is
  held out at call level.
- **B** — the same texts scored against an unrelated scenario's rubric, paired by seeded
  derangement rejecting cosine ≥ `layer_a.merge_cosine_threshold`.

### 3.2 The applicability pre-check — the part that is new

Without it, `satisfiability` is confounded by contingency, and the ceiling run showed contingency
is the dominant term: 234 of 235 milestones are labelled `fixed` (mandatory) while the
`conditional` trigger (`position_variance > 0.3`) fires **0 of 226** times.

One Gemma call per batch of responses asks, per response, **which milestones of this rubric the
client's turn actually called for** — returning a subset, not a per-milestone verdict. That keeps
it at one call per 12 responses, the same batching shape as `score_milestones_batch`, rather than
one call per (milestone, response).

Then:

- `satisfiability` counts only applicable instances — "did you do it when it was needed".
- `discrimination` uses **unconditional** counts on both arms, because filtering arm B by
  applicability would shrink its denominator and inflate the null.
- `applicable_rate` is reported separately, and is itself the contingency measurement Layer C
  currently cannot produce.

### 3.3 Pre-registered verdicts

Fixed here before the run, so they cannot be moved afterwards. `W` is
`(hits + 0.5 × partial) / attempts` as everywhere else.

| verdict | condition | consequence in Layer D |
| --- | --- | --- |
| `not_discriminating` | `W(B) ≥ 0.5 × W(A3)` | never scored |
| `not_satisfiable` | applicable instances ≥ 6 and `W(A3 \| applicable) < 0.20` | never scored |
| `contingent` | `applicable_rate < 0.50` and otherwise passing | scored **only** when the applicability check passes for that response |
| `insufficient_evidence` | fewer than 6 applicable instances | never scored, and reported so it can be revisited |
| `validated` | none of the above | scored normally |

The `0.5 × W(A3)` and `0.20` figures are inherited from the ceiling spec's own gate and main
threshold, deliberately, so this instrument is calibrated against a measurement that already
exists rather than against fresh guesses.

### 3.4 Storage: JSONB, no DDL

Each milestone gains a `validation` object, following the precedent of `criteria_rewritten` and
`not_coachable_flag`:

```json
"validation": {
  "verdict": "validated",
  "a3_w": 0.271, "a3_w_applicable": 0.402, "b_w": 0.000,
  "discrimination": 0.271, "applicable_rate": 0.67,
  "a3_attempts": 8, "a3_applicable": 6, "b_attempts": 8,
  "scored_by": "gemini-3.1-flash-lite",
  "validated_at_run": "<run_id>"
}
```

**The load-bearing gotcha:** `upsert_rubric`'s `ON CONFLICT (scenario_id)` replaces `milestones`
in place, so **any Layer C run destroys every validation verdict.** `validated_at_run` records
which run the verdict describes, and `validate_rubrics.py` must refuse to report a stale verdict
whose run id no longer matches. This is the same failure family as `gap_events` copying evidence
rather than joining to it.

### 3.5 Layer D consumes it

One new validated `tuning.yaml` key under `layer_d:`:

```yaml
  # Skip milestones whose validation verdict is not 'validated'. Mirrors
  # skip_uncoachable_milestones, which already skips the 17 hand-flagged ones.
  require_validated_milestones: false   # default off until a full validation run exists
```

Default `false`, exactly like `response_taxonomy_auto_pass_enabled` shipped off. A milestone
marked `contingent` is not skipped — Layer D runs the applicability check for it and scores it
only where it applies, which is the fix for cause 2 in the ceiling spec.

### 3.6 Self-validation: does the validator reproduce a known answer?

The ceiling run already produced a labelled set, so the validator can be checked rather than
trusted:

- 7 scenarios with a control score of exactly **0.000** must come out `validated`-heavy
- the 7 **inverted** scenarios must come out `not_discriminating`-heavy
- the 65 milestones with zero full and zero partial hits must be split between
  `not_satisfiable` and `contingent` — and **which way that split falls is the real result**,
  because it says how much of the 66% is unreachable criteria versus contingency

If it cannot reproduce that split, the instrument is wrong and nothing it says counts. This is
the same discipline as the ceiling harness proving its hoisted benchmark ranking matched
production's before spending Gemma calls.

## 4. Cost

| scope | responses | applicability calls | scoring calls | total |
| --- | --- | --- | --- | --- |
| 49 scenarios Layer D touches, 8 per arm | ~750 | ~63 | ~63 | **~126** |
| all 84 rubrics, 8 per arm | ~1,340 | ~112 | ~112 | ~224 |

Recommend the 49-scenario scope first (~126 calls, ~25% of one key's daily 500), because it is the
population Layer D actually scores and it is directly comparable to the ceiling run.

Re-validation is needed after every Layer C run, which is a real ongoing cost and an argument for
running Layer C rarely rather than for skipping validation.

## 5. Risks

- **The applicability judge is itself unvalidated.** It is a new Gemma judgement with no control.
  Mitigation: it has a natural null — ask it about milestones from an *unrelated* rubric, where
  the applicable rate should collapse. Build that check in from the start; it is ~6 calls.
- **Circularity.** Validation uses the expert's own held-out responses, so a milestone describing
  something only he does still passes. This measures "satisfiable by the author on unseen calls",
  not "satisfiable by a competent CSM". That is a strictly weaker claim and must be stated
  wherever the verdict is used.
- **Gating could empty the rubrics.** If most milestones fail, Layer D scores almost nothing.
  That is an honest outcome rather than a bug, but it means `require_validated_milestones` must
  ship `false` and the first run must be read before flipping it.
- **Network dependence.** This session established that `neon.tech` DNS is *refused* on the
  user's college wifi while `generativelanguage.googleapis.com` resolves fine. The validator both
  reads and writes Postgres, so it cannot run on that network at all.

## 6. Verification plan

`score_milestones_batch` is reused unchanged. New testable surface, all pure:

- **verdict assignment** — hand-built counter dicts hit every branch of §3.3, including the
  boundary cases at exactly `0.5 × W(A3)`, exactly `0.20`, exactly `0.50` applicable rate, and
  exactly 6 applicable instances
- **stale-verdict refusal** — a `validation` object whose `validated_at_run` differs from the
  rubric's current run must be reported stale, never used
- **applicability parsing** — a returned subset naming a milestone id that is not in the rubric,
  or omitting ids entirely, must be handled without silently marking everything applicable
- **the write path** — validation must merge into the existing milestone object without dropping
  `support_calls`, `criteria_rewritten` or `not_coachable_flag`, proven by round-tripping a real
  milestone JSONB shape

Run file-by-file, per the documented 16GB-Windows spaCy constraint.

## 7. Open question this design deliberately leaves open

If the 65 zero-hit milestones turn out to be mostly **`contingent`** rather than
`not_satisfiable`, then the milestone rubric is largely sound and Layer D's scoring model was the
defect all along — a much cheaper world to be in. If they are mostly `not_satisfiable`, the
criteria genuinely cannot be met and the unit-of-feedback question becomes unavoidable. **This
run is what decides between those, and no amount of further reasoning will.**
