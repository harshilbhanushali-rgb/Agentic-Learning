# Skills Vocabulary — Can a Per-Person Profile Be Built at All? No (2026-08-13)

[Findings index](INDEX.md)

### Skills vocabulary — can a per-person profile be built at all? No (2026-08-13)

Pre-registration: `docs/superpowers/specs/2026-08-13-layer-c-skills-vocabulary-design.md`.
Harness `calibration/trial_skills.py`, artifacts `skills_trial.json` (full) /
`skills_trial_pilot.json`, logs `logs/trial_skills_full.log`. Zero Postgres writes.

The question is independent of the criteria failure and survives it: **the arms decide
whether criteria can grade; this decides whether there are axes to report on.** 405 axes at
~4-8 observations each is arithmetic no scoring fix repairs.

- **`skills.sweep`'s own honest-failure signal CANNOT fail.** `cross_scenario_coverage`
  goes to 1.0 by construction as the threshold falls (everything merges into one group), so
  the sweep alone always says yes at *some* granularity. Same defect class as the
  merge-blind `_match_milestones`: a metric that only counts the good outcome. The fix is a
  second curve that gets WORSE as groups fuse — merge validity `V(t)`, a batched judge
  returning a verdict on every group.
- **The gate is a WINDOW between two curves**, constraining from opposite sides: `V(t)`
  bounds coarseness from above, statistical power bounds it from below. PASS = some judged
  `t` has `K(t) <= bound` and `V(t) >= 0.80`. The lower bound is derived, never chosen —
  from 889 attempts / 405 milestones and the ±0.006 noise floor, giving K <= 11/17/18/35 for
  four standards. **K is optimistic; the operative gate is the MEDIAN skill's member count**
  (>=38/24/23/12), because K assumes an even split that never holds.
- **Result: no window at any bound.** Power is satisfiable only at t<=0.675 (K=6, median 13);
  `V` there is **0.20** against a bar of 0.80 — off by 4x, not a near miss. Validity rises
  monotonically 0.20 -> 0.25 -> 0.50 -> 1.00 as clustering gets finer, which is the shape a
  working counterweight should have.
- **The negative is trustworthy because the instrument passed its own checks first:** judge
  null 12/12 rejected (blinded, size-matched disguised pairs), positive control V=1.00 at
  t=0.95, as-written control confirms the abstraction is NOT inert (56 groups written vs 14
  abstracted at t=0.7), order permutation drift 0.11-0.17 at full scale. **First judge in
  this whole effort to pass its own null** — the applicability judge failed at 1.22:1 and
  the coverage judge at 64.9% vs 65.7%.
- **The cause: 78% of milestones (315/405) abstract to a behaviour string occurring exactly
  ONCE.** Only 22% recur at all, 11% recur 5+ times. So behaviours DO repeat — an
  *explains-a-mechanism* family covers 55 items, `call mechanics` 11, *asks open questions*
  8 — but they cover ~a fifth of the corpus. Pooling 405 into <=35 axes requires merging 315
  genuinely distinct one-off moves.

**CLOSED after three attempts, each varying exactly ONE thing (2026-08-13).** An earlier
version of this section argued a better embedder could not matter because the 78% figure is
exact string matching. **That reasoning was wrong and is retracted** — merging
differently-worded items that mean the same thing is precisely what clustering does, so the
grouping was always an embedding question. It was tested rather than argued.

| # | treatment | best validity | window |
| --- | --- | --- | --- |
| 1 | V1 prompt + bge | 0.50 | no |
| 2 | V1 prompt + **gemini** (`--reuse-behaviours`, embedder the only variable) | **0.667** | no |
| 3 | **V2 prompt** + gemini (`--abstract-prompt v2`) | 0.50 | no |

- **The embedder helped materially and was not enough.** Validity 0.50 -> 0.667 at t=0.725,
  and the sample groups read visibly better (a six-member set-expectations group that bge
  never produced). Still short of the 0.80 bar. Gemini's space also has a **cliff, not a
  gradient** — K=2 with median 202 at t<=0.70, then median 2.0 at K=6 — so no granularity
  gives both a workable K and real membership. Order drift also failed there (0.33 > 0.20).
- **The V2 prompt hit its target exactly and made the result WORSE (0.667 -> 0.50).** Banning
  the purpose clause collapsed *explains a mechanism* from 30 phrasings into ONE string with
  29 members — the fix worked. The model then varied on the adjective instead: `asks open` /
  `targeted` / `probing` / `clarifying questions`, 26 items across 4 strings. **Close one
  axis of variation and it finds another.** V2 did improve stability (drift 0.09-0.17):
  shorter strings cluster more consistently, just more consistently into fused groups.
- **The number that decides it barely moved: one-offs 78% -> 74%, distinct strings 342 ->
  323.** 299 of 405 behaviours still occur exactly once after a better embedder AND a prompt
  written specifically to collapse them.
- **The controls held identically across all three runs** — judge null 12/12 rejected and
  positive control 1.00 every time — so the instrument was stable while the treatments
  varied. That is what makes this a conclusion rather than three failures.
- **THE REAL SHAPE OF THE FAILURE, found 2026-08-13 by re-reading the sweeps rather than
  re-running anything: the behaviour distribution has NO MIDDLE.** At every non-degenerate
  threshold in all three runs, mean group size vastly exceeds median — bge t=0.65 is K=3
  median 12 **mean 135**; v2 t=0.575 is K=3 median 10 **mean 135**; v1+gemini sits at K=2
  median 202 from t=0.50 to 0.70. That is one enormous undifferentiated blob plus a tail of
  singletons, **at every granularity**. There is no threshold anywhere producing, say, 15
  groups of ~27 items. Coarsen and the blob eats everything; tighten and it shatters into
  singletons. This explains why all three attempts failed *identically* despite varying the
  embedder and the prompt — they were searching a space with no intermediate structure in it.
  A better statement of the result than the one-off count, and it is free to verify from the
  saved artifacts.
- **Two harness bugs found at the same time, both now fixed, both of which make the gate
  STRICTER — which is why the verdict survives them.** (1) `select_judge_thresholds` picked
  on the K bound ALONE, but median rises as the threshold falls, so every point that
  actually satisfied the power gate sat *below* everything judged and validity was never
  measured where the gate passed. Harmless in these runs only because those points were
  degenerate (K=1-2 holding all 405), i.e. harmless by luck. (2) **The median has a blind
  spot at small K**: three groups split `[1, 10, 394]` has median 10 and nearly clears a
  floor of 12 while describing nothing. Use `usable_item_fraction` (share of ITEMS in a
  group at or above the floor) alongside it — a mega-blob split cannot fool that.
- **What survives: a PARTIAL vocabulary.** The head is genuine — `explains a mechanism` (29),
  `asks open questions` (10), `call mechanics` (8), `builds rapport` (4), `proposes a next
  step` (3) — roughly 6-27 skills covering ~25% of milestones, with the rest in
  `skills.UNASSIGNED`. **Do not attempt a fourth wording or embedder pass.** The fix for thin
  axes is MORE CSM CALLS (multiply observations) rather than fewer axes (compress what is
  observed) — see the arithmetic in the Layer D section.
- **What this DOES support:** a *partial* vocabulary of the ~6-27 skills that genuinely
  recur, covering 11-22% of milestones, with the rest in `skills.UNASSIGNED`. What it rules
  out is a complete vocabulary at any granularity where every axis has enough observations.
- **Identified but NOT pulled:** the abstraction prompt asks the model to keep the *why*
  ("Keep what the person is DOING and WHY"), which splinters *explains a mechanism* into 30
  strings over 55 items. Dropping the WHY clause would materially move the curve. Left
  alone deliberately — re-running after a negative with a tweaked prompt is how a result
  gets tuned into existence, and three wording passes have already failed here. It needs a
  fresh pre-registration, not a retry.
- **The pilot could not open the window by construction** (91 milestones = 22% of the
  observations the floors were derived from) and the floors were deliberately NOT rescaled
  to fit — a bound moved to fit the run it is judging is not a bound. The report printed the
  stopping-condition verdict anyway on the first pass; now gated on the full corpus. Also
  note the pilot's order-permutation failure at t=0.725 (drift 0.44) did **not** reproduce
  at full scale — it was a small-sample artifact.

