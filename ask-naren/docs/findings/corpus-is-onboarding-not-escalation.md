# The corpus is onboarding, not escalation — and it sets what any new feature can deliver

**Status: LIVE FINDING, 2026-09-12.** Not a defect and nothing to fix. It is a property of
the data that bounds what Ask Naren can be asked to do, and it has already produced wrong
expectations once — see "How this was found".

**Read this before scoping any new intent, eval set, or answer path.** The cost of not
reading it is a feature that is measured on well-covered ground, ships looking accurate, and
then declines or misroutes on the questions it was actually built for.

## The claim

Naren's recorded calls are dominated by **getting clients contracted, integrated, configured
and live**. They contain comparatively little about **rescuing a campaign that is already
running badly**.

So questions about implementation land well, and questions about mid-flight performance
problems — spend pacing, applicant quality falling off, a discount request after a bad month
— decline or misroute far more often. The tool is not weaker at those questions. It has less
to answer them from.

## The evidence

### 1. The frequency ranking, read off the live corpus

`frequency` returns the twelve most-supported situations of the thirty-four. Measured
2026-09-12:

| # | Situation | Calls it was drawn from | About |
| --- | --- | --- | --- |
| 1 | contract_and_legal_review | 102 | getting live |
| 2 | budget_allocation_and_testing | 101 | getting live |
| 3 | xml_feed_setup_and_ingestion | 90 | getting live |
| 4 | ats_integration_and_api_mapping | 88 | getting live |
| 5 | landing_page_and_conversion_setup | 87 | getting live |
| 6 | dashboard_access_and_reporting | 82 | access + setup |
| 7 | job_board_budget_and_direct_agreements | 69 | commercial setup |
| 8 | campaign_level_performance_tracking | 67 | **ongoing performance** |
| 9 | creative_and_media_plan_review | 67 | getting live |
| 10 | publisher_management_and_exclusions | 60 | configuration |
| 11 | vendor_transition_and_partnership_evaluation | 58 | switching vendor |
| 12 | market_insights_and_competitive_intelligence | 48 | advisory |

**Exactly one of the twelve is squarely about a running campaign's performance.** The other
eleven are about contracts, feeds, integrations, pages, dashboards, creative, publishers and
vendor transitions. The two situations that are most obviously about performance rescue —
`downstream_activation_and_cost_metrics` and
`niche_talent_scarcity_and_budget_reallocation` — do not make the top twelve at all.

The "About" column is a judgement, not a measured label. The call counts are not.

### 2. A natural experiment, run by accident

Nineteen invented questions were put to the live service while writing
`docs/what-ask-naren-answers.md`. They split cleanly by subject matter, and the outcome split
with them.

**Five questions about mid-flight performance problems — zero clean answers:**

| Asked | Outcome |
| --- | --- |
| the general play when a client wants to pause spend halfway through a quarter | **declined**, `no_close_match` |
| applicant quality has dropped off a cliff, here is my reply, how does it compare | **declined**, `no_close_match` |
| how Naren phrases telling a client their cost-per-hire target is unrealistic | **misroute** — returned phrases about publisher agnosticism and duplicate job postings |
| what goes wrong when a client asks for a discount after a bad month | **misroute** — returned pitfalls about go-live dates and recruiter tool adoption |
| when the play for **low** applicant volume applies | **misroute** — returned the play for **high** applicant volume |

**The same question types, retargeted onto implementation ground — all answered first try:**

| Asked | Outcome |
| --- | --- |
| the general play for how long the ATS integration takes on their side | answered, grounded, 4 moves |
| ATS writeback vs manual export, here is my reply, how does it compare | answered, grounded |
| "and if they push back on that" as a follow-up to that | answered from the same call |
| what goes wrong when agreeing a go-live date | 2 pitfalls with evidence |
| when the play for handling large volumes of applications applies | answered |
| how do I get better at defining testing scope and integration timelines | answered, matched to one specific move |

Nothing changed between the two tables except the subject matter. Same nineteen intents, same
service, same session.

**Treat this as a strong hint and not a measurement.** n is five against six, the questions
were invented by one person, and there was no blind read. What makes it worth recording is
that the direction agrees with the frequency ranking, which *is* measured — two independent
reasons pointing the same way.

## Why it is this way

The corpus is whatever calls were recorded and mined, and the mining is described in
`Brain/CLAUDE.md`. Recorded calls skew toward **scheduled, multi-party, agenda-driven
conversations** — kickoffs, integration syncs, MSA reviews, UAT walkthroughs, go-live
planning. Those are the meetings that get booked, attended by several people, and recorded.

A campaign going wrong in week six tends to be handled in a Slack thread, an email, or an
unscheduled call nobody hit record on. So the corpus under-represents exactly the moments a
CSM is most stressed about — which is also when they are most likely to reach for this tool.

This is a sampling property of the source material. It is not something a retrieval change,
a threshold, or a better prompt can fix.

## What this means for new features

1. **Check coverage before scoping, not after building.** `coverage_check` exists for this
   and costs one request: it names the nearest situation and how many calls back it. If a
   proposed feature's core questions land on situations backed by a handful of calls, the
   feature will decline a lot no matter how well it is built.

2. **Draw eval questions FROM the covered situations, never from intuition about CS work.**
   This is the trap that produced the table above. An eval set written from what a CSM
   *plausibly* asks will measure subject-matter coverage while looking like it measures the
   feature. Related but distinct from the rule in
   `ask-naren/audit/blind_read_rubric.md` about cases that restate the prompt — this one is
   about cases that restate the author's assumptions about the domain.

3. **A decline rate is not a single number for the tool.** It is a number for one intent on
   one kind of subject matter. A rate measured on onboarding questions will not hold on
   escalation questions, and quoting it as though it will is how a feature gets signed off
   and then disappoints.

4. **Expect the failure mode to cluster where the corpus is thin.** All three misroutes above
   were in sparse territory, and each was confidently worded and correctly sourced. That is
   the same shape recorded in `answer-failure-modes.md` — on the right topic, answering a
   different question — which means issue #9's relevance work should be measured on BOTH
   well-covered and thin ground, or a fix that only holds on the former will look general.

5. **Say so in anything CSM-facing.** `docs/what-ask-naren-answers.md` states which ground
   lands and which is thin. A guide that implies even coverage sets a CSM up to conclude the
   tool is broken the first time it declines on the question they cared most about.

6. **This is an argument for more corpus, not a better model.** If escalation coverage
   matters, the move is to get those conversations recorded and mined — not to tune
   retrieval against material that is not there.

## What would change this

**More recorded calls of the unscheduled kind.** If mid-flight escalations start being
recorded and mined, re-run `frequency` and redo the table above. The ranking is read live
from the corpus, so it answers this question cheaply at any time.

Nothing else changes it. In particular, do not re-propose a retrieval floor, candidate
selection, or a rank cutoff as a response to the declines here — all three were measured and
rejected (`adr/0005-candidate-selection-and-retrieval-floor-measured-and-rejected.md`), and
none of them creates evidence that does not exist.

## What this does NOT establish

**That the tool is inaccurate.** Where the corpus is thick, the nineteen-question sweep
answered cleanly and with traceable quotes. This is a statement about *what it has material
for*, not about how well it handles what it has.

**That onboarding questions are the valuable ones.** Quite possibly the opposite — the
escalation moments may be where a CSM needs help most. This finding says the tool currently
serves them least well, which is a product problem worth knowing, not a reason to redirect
the product at what happens to be easy.

**A precise split of the thirty-four situations.** The "About" column is one person's
reading. If a decision rests on the exact proportion, classify the situations deliberately
rather than citing this table.
